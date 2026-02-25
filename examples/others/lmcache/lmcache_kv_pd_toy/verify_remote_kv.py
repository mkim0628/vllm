#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify decoder consumed prefiller-generated KV cache.

This script does an A/B check using decoder logs:
- A (baseline): decode-only request (no kv_transfer_params)
- B (disagg): prefill request -> extract kv_transfer_params -> decode request

It then parses decoder logs for LMCache hit lines and verifies B > A.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

LMHIT_RE = re.compile(r"LMCache hit tokens:\s*(\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefill-url", default="http://127.0.0.1:8100/v1")
    parser.add_argument("--decode-url", default="http://127.0.0.1:8200/v1")
    parser.add_argument(
        "--decoder-log",
        default="examples/others/lmcache/lmcache_kv_pd_toy/decoder.log",
    )
    parser.add_argument("--model", default="meta-llama/Llama-3.1-8B-Instruct")
    parser.add_argument("--max-tokens", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def read_new_log(path: Path, start_offset: int) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        f.seek(start_offset)
        return f.read()


def get_log_offset(path: Path) -> int:
    if not path.exists():
        return 0
    return path.stat().st_size


def extract_last_lmcache_hit(log_text: str) -> int | None:
    matches = LMHIT_RE.findall(log_text)
    if not matches:
        return None
    return int(matches[-1])


def build_payload(model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }


def post_json(client: httpx.Client, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = client.post(endpoint, json=payload)
    r.raise_for_status()
    return r.json()


def main() -> int:
    args = parse_args()
    log_path = Path(args.decoder_log)

    timeout = httpx.Timeout(connect=30.0, read=args.timeout, write=30.0, pool=30.0)
    with httpx.Client(base_url=args.prefill_url, timeout=timeout) as prefill_client, httpx.Client(
        base_url=args.decode_url,
        timeout=timeout,
    ) as decode_client:
        # A) baseline decode-only
        prompt_a = f"[baseline-{uuid.uuid4()}] Explain KV transfer in one sentence."
        payload_a = build_payload(args.model, prompt_a, args.max_tokens)

        start_a = get_log_offset(log_path)
        _ = post_json(decode_client, "/chat/completions", payload_a)
        time.sleep(0.8)
        log_a = read_new_log(log_path, start_a)
        hit_a = extract_last_lmcache_hit(log_a)
        if hit_a is None:
            print("[warn] Could not find baseline LMCache hit log line; treating as 0")
            hit_a = 0

        # B) disaggregated prefill -> decode with forwarded kv_transfer_params
        prompt_b = f"[disagg-{uuid.uuid4()}] Explain KV transfer in one sentence."
        prefill_payload = build_payload(args.model, prompt_b, max_tokens=1)
        prefill_payload["stream"] = False

        prefill_resp = post_json(prefill_client, "/chat/completions", prefill_payload)
        kv_transfer_params = prefill_resp.get("kv_transfer_params")
        if not isinstance(kv_transfer_params, dict) or not kv_transfer_params:
            raise RuntimeError(
                "Prefill response missing kv_transfer_params; cannot verify remote KV consumption"
            )

        payload_b = build_payload(args.model, prompt_b, args.max_tokens)
        payload_b["kv_transfer_params"] = kv_transfer_params

        start_b = get_log_offset(log_path)
        _ = post_json(decode_client, "/chat/completions", payload_b)
        time.sleep(0.8)
        log_b = read_new_log(log_path, start_b)
        hit_b = extract_last_lmcache_hit(log_b)
        if hit_b is None:
            raise RuntimeError(
                "Could not find LMCache hit tokens log in disagg run. "
                "Check decoder log level / connector logs."
            )

        result = {
            "baseline_hit_tokens": hit_a,
            "disagg_hit_tokens": hit_b,
            "kv_transfer_params_keys": sorted(kv_transfer_params.keys()),
            "verification_passed": hit_b > hit_a,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if hit_b <= hit_a:
            raise RuntimeError(
                f"Verification failed: disagg_hit_tokens ({hit_b}) <= baseline ({hit_a})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
