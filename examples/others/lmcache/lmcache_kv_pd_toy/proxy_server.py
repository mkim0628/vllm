# SPDX-License-Identifier: Apache-2.0

"""Toy proxy for LMCache-based prefill/decode disaggregation.

Flow:
1) Send a short non-streaming request to prefiller.
2) Extract kv_transfer_params from prefiller response.
3) Attach kv_transfer_params to decoder request and stream result to client.
"""

from __future__ import annotations

import argparse
import copy
import json
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--prefill-base-url", type=str,
                        default="http://127.0.0.1:8100/v1")
    parser.add_argument("--decode-base-url", type=str,
                        default="http://127.0.0.1:8200/v1")
    return parser.parse_args()


def _auth_headers(request: Request) -> dict[str, str]:
    auth = request.headers.get("authorization")
    return {"authorization": auth} if auth else {}


def _prefill_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prefill_payload = copy.deepcopy(payload)
    prefill_payload["stream"] = False
    prefill_payload["max_tokens"] = 1
    if "max_completion_tokens" in prefill_payload:
        prefill_payload["max_completion_tokens"] = 1
    if "stream_options" in prefill_payload:
        prefill_payload.pop("stream_options", None)
    return prefill_payload


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
    limits = httpx.Limits(max_keepalive_connections=None, max_connections=None)

    app.state.prefill_client = httpx.AsyncClient(
        base_url=app.state.prefill_base_url,
        timeout=timeout,
        limits=limits,
    )
    app.state.decode_client = httpx.AsyncClient(
        base_url=app.state.decode_base_url,
        timeout=timeout,
        limits=limits,
    )
    yield
    await app.state.prefill_client.aclose()
    await app.state.decode_client.aclose()


def create_app(prefill_base_url: str, decode_base_url: str) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.prefill_base_url = prefill_base_url
    app.state.decode_base_url = decode_base_url

    async def run_prefill_then_attach_kv(
        endpoint: str,
        client_payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        prefill_resp = await app.state.prefill_client.post(
            endpoint,
            json=_prefill_payload(client_payload),
            headers=headers,
        )
        prefill_resp.raise_for_status()

        prefill_json = prefill_resp.json()
        kv_transfer_params = prefill_json.get("kv_transfer_params")

        decode_payload = copy.deepcopy(client_payload)
        if isinstance(kv_transfer_params, dict) and kv_transfer_params:
            decode_payload["kv_transfer_params"] = kv_transfer_params
        else:
            # Some LMCache/vLLM versions do not emit kv_transfer_params in
            # prefill output and rely on implicit lookup keys instead.
            decode_payload.pop("kv_transfer_params", None)
        return decode_payload

    async def stream_decode(
        endpoint: str,
        decode_payload: dict[str, Any],
        headers: dict[str, str],
    ):
        async with app.state.decode_client.stream(
            "POST",
            endpoint,
            json=decode_payload,
            headers=headers,
        ) as decode_resp:
            decode_resp.raise_for_status()
            async for chunk in decode_resp.aiter_bytes():
                yield chunk

    async def non_stream_decode(
        endpoint: str,
        decode_payload: dict[str, Any],
        headers: dict[str, str],
    ) -> JSONResponse:
        decode_resp = await app.state.decode_client.post(
            endpoint,
            json=decode_payload,
            headers=headers,
        )
        decode_resp.raise_for_status()
        return JSONResponse(content=decode_resp.json(),
                            status_code=decode_resp.status_code)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "prefill_base_url": app.state.prefill_base_url,
            "decode_base_url": app.state.decode_base_url,
        }

    @app.post("/v1/completions")
    async def completions(request: Request):
        payload = await request.json()
        headers = _auth_headers(request)

        decode_payload = await run_prefill_then_attach_kv(
            "/completions", payload, headers)
        if payload.get("stream", False):
            return StreamingResponse(
                stream_decode("/completions", decode_payload, headers),
                media_type="text/event-stream",
            )
        return await non_stream_decode("/completions", decode_payload, headers)

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = await request.json()
        headers = _auth_headers(request)

        decode_payload = await run_prefill_then_attach_kv(
            "/chat/completions", payload, headers)
        if payload.get("stream", False):
            return StreamingResponse(
                stream_decode("/chat/completions", decode_payload, headers),
                media_type="text/event-stream",
            )
        return await non_stream_decode("/chat/completions", decode_payload, headers)

    @app.exception_handler(httpx.HTTPStatusError)
    async def http_status_error_handler(_, exc: httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            body = exc.response.json()
        except json.JSONDecodeError:
            body = {"error": exc.response.text}
        return JSONResponse(status_code=status, content=body)

    return app


if __name__ == "__main__":
    args = parse_args()
    app = create_app(args.prefill_base_url, args.decode_base_url)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
