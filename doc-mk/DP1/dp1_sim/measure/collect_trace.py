"""vLLM runtime trace collector (Evaluation §6, Phase 3). Non-invasive.

Runs next to a `vllm serve` started by 03_serve_sweep.sh and writes JSONL:
  {"src":"metrics", "t":..., "running":..., "waiting":..., "kv_usage":..., "preemptions":..., "prefix_hits":..., "prefix_queries":...}
  {"src":"gpu", "t":..., "gpu":i, "mem_used":..., "util":...}              (pynvml, HBM occupancy / GPU util)
  {"src":"kv", "t":..., "stored_blocks":n, "removed_blocks":n, "cleared":bool, "medium":...}
                                                           (--kv-events-config ZMQ publisher: block alloc/evict)
Stop with SIGINT/SIGTERM.

  python measure/collect_trace.py --out trace.jsonl --metrics http://localhost:8000/metrics --kv-endpoint tcp://localhost:5557
"""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
import urllib.request
from pathlib import Path

WANT = {
    "vllm:num_requests_running": "running",
    "vllm:num_requests_waiting": "waiting",
    "vllm:kv_cache_usage_perc": "kv_usage",
    "vllm:num_preemptions_total": "preemptions",
    "vllm:prefix_cache_hits_total": "prefix_hits",
    "vllm:prefix_cache_queries_total": "prefix_queries",
    # hits served from the KV connector / CPU offload tier (B1 validation)
    "vllm:external_prefix_cache_hits_total": "ext_prefix_hits",
    "vllm:external_prefix_cache_queries_total": "ext_prefix_queries",
}

stop = threading.Event()


def scrape(url: str) -> dict:
    txt = urllib.request.urlopen(url, timeout=2).read().decode()
    out: dict = {}
    for line in txt.splitlines():
        if not line or line[0] == "#":
            continue
        name = line.split("{", 1)[0].split(" ", 1)[0]
        key = WANT.get(name)
        if key is None:
            continue
        try:
            out[key] = out.get(key, 0.0) + float(line.rsplit(" ", 1)[1])
        except ValueError:
            pass
    return out


def metrics_loop(url, period, sink):
    while not stop.is_set():
        t = time.time()
        try:
            sink({"src": "metrics", "t": t, **scrape(url)})
        except Exception as e:  # noqa: BLE001
            sink({"src": "metrics", "t": t, "error": repr(e)})
        stop.wait(period)


def gpu_loop(period, sink):
    try:
        import pynvml
    except ImportError:
        sink({"src": "gpu", "error": "pynvml not installed (pip install nvidia-ml-py)"})
        return
    pynvml.nvmlInit()
    hs = [
        pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())
    ]
    while not stop.is_set():
        t = time.time()
        for i, h in enumerate(hs):
            m = pynvml.nvmlDeviceGetMemoryInfo(h)
            u = pynvml.nvmlDeviceGetUtilizationRates(h)
            sink(
                {
                    "src": "gpu",
                    "t": t,
                    "gpu": i,
                    "mem_used": m.used,
                    "mem_total": m.total,
                    "util": u.gpu,
                    "mem_util": u.memory,
                }
            )
        stop.wait(period)


def kv_loop(endpoint, topic, sink):
    try:
        import zmq
        from msgspec.msgpack import Decoder

        from vllm.distributed.kv_events import BlockRemoved, BlockStored, KVEventBatch
    except ImportError as e:
        sink({"src": "kv", "error": repr(e)})
        return
    dec = Decoder(type=KVEventBatch)
    sub = zmq.Context().socket(zmq.SUB)
    sub.connect(endpoint)
    sub.setsockopt_string(zmq.SUBSCRIBE, topic)
    sub.setsockopt(zmq.RCVTIMEO, 500)
    while not stop.is_set():
        try:
            _, _seq, payload = sub.recv_multipart()
        except zmq.Again:
            continue
        b = dec.decode(payload)
        st = sum(len(e.block_hashes) for e in b.events if isinstance(e, BlockStored))
        rm = sum(len(e.block_hashes) for e in b.events if isinstance(e, BlockRemoved))
        media = sorted(
            {
                getattr(e, "medium", None) or "GPU"
                for e in b.events
                if hasattr(e, "medium")
            }
        )
        sink(
            {
                "src": "kv",
                "t": b.ts,
                "stored_blocks": st,
                "removed_blocks": rm,
                "cleared": any(
                    type(e).__name__ == "AllBlocksCleared" for e in b.events
                ),
                "media": media,
            }
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--metrics", default="http://localhost:8000/metrics")
    ap.add_argument("--kv-endpoint", default="tcp://localhost:5557")
    ap.add_argument("--kv-topic", default="kv-events")
    ap.add_argument("--period", type=float, default=0.5)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    f = args.out.open("w")
    lock = threading.Lock()

    def sink(rec):
        with lock:
            f.write(json.dumps(rec) + "\n")

    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *_: stop.set())
    th = [
        threading.Thread(
            target=metrics_loop, args=(args.metrics, args.period, sink), daemon=True
        ),
        threading.Thread(target=gpu_loop, args=(args.period, sink), daemon=True),
        threading.Thread(
            target=kv_loop, args=(args.kv_endpoint, args.kv_topic, sink), daemon=True
        ),
    ]
    for t in th:
        t.start()
    while not stop.is_set():
        stop.wait(0.5)
    for t in th:
        t.join(timeout=2)
    f.close()


if __name__ == "__main__":
    main()
