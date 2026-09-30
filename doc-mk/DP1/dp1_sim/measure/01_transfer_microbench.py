"""Phase 2 HW microbenchmark: HBM <-> host DRAM migration path (A evidence).

Measures, on the GPU box:
  1. H2D / D2H bandwidth vs transfer size (pinned + pageable)         -> TransferCurve
  2. fitted launch latency alpha (t = alpha + size/bw)                  -> host_link_latency
  3. KV-block-shaped scattered copies (many small chunks, per-chunk
     cudaMemcpyAsync vs gather->contiguous copy)                        -> chunk sensitivity
  4. all-GPU concurrent H2D (root complex / socket limits)              -> per-GPU share
  5. interference: HBM-bound and GEMM kernels with concurrent H2D+D2H   -> copy_interference
  6. allocation cost: cudaHostAlloc (pinned) / cudaMalloc               -> alloc overhead

Output: measured/<GPU_KEY>/transfer.json  (read by hw.py)

  GPU_KEY=a100_sxm4_80g python measure/01_transfer_microbench.py
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import threading
import time
from pathlib import Path

import torch

MiB = 1024**2


def _time_cuda(fn, iters: int, stream=None) -> list[float]:
    out = []
    for _ in range(iters):
        s = torch.cuda.Event(enable_timing=True)
        e = torch.cuda.Event(enable_timing=True)
        s.record(stream)
        fn()
        e.record(stream)
        e.synchronize()
        out.append(s.elapsed_time(e) / 1e3)
    return out


def size_sweep(
    dev: int, pinned: bool, iters: int, max_bytes: int
) -> tuple[list[dict], list[dict]]:
    torch.cuda.set_device(dev)
    sizes = [4096 * 4**k for k in range(12) if 4096 * 4**k <= max_bytes]
    h2d, d2h = [], []
    big_h = torch.empty(max_bytes, dtype=torch.uint8, pin_memory=pinned)
    big_d = torch.empty(max_bytes, dtype=torch.uint8, device=f"cuda:{dev}")
    for n in sizes:
        hs, ds = big_h[:n], big_d[:n]
        for _ in range(3):
            ds.copy_(hs, non_blocking=pinned)
        torch.cuda.synchronize()
        t = statistics.median(
            _time_cuda(lambda: ds.copy_(hs, non_blocking=pinned), iters)
        )
        h2d.append({"bytes": n, "t_s": t, "bw_Bps": n / t})
        t = statistics.median(
            _time_cuda(lambda: hs.copy_(ds, non_blocking=pinned), iters)
        )
        d2h.append({"bytes": n, "t_s": t, "bw_Bps": n / t})
    del big_h, big_d
    return h2d, d2h


def fit_alpha(rows: list[dict]) -> float:
    """Least-squares intercept of t = a + n/b over the full sweep."""
    xs = [r["bytes"] for r in rows]
    ys = [r["t_s"] for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return max(0.0, my - b * mx)


def kv_block_copy(
    dev: int, total_bytes: int, chunk_bytes_list: list[int], iters: int
) -> list[dict]:
    """vLLM KV layout: per layer, per block, K and V are separate small chunks.

    For Llama-70B TP=4, one 16-token block per layer per K/V is
    16 * (8/4 heads) * 128 * 2 B = 8 KiB per rank. Offloading moves many such
    chunks; the effective BW depends on how they are batched.
    """
    torch.cuda.set_device(dev)
    out = []
    src = torch.empty(total_bytes, dtype=torch.uint8, device=f"cuda:{dev}")
    dst = torch.empty(total_bytes, dtype=torch.uint8, pin_memory=True)
    for cb in chunk_bytes_list:
        n = total_bytes // cb
        # strided chunks (every other chunk) to mimic non-contiguous blocks
        idx = list(range(0, n, 2))
        srcv = src[: n * cb].view(n, cb)
        dstv = dst[: n * cb].view(n, cb)

        def per_chunk():
            for i in idx:
                dstv[i].copy_(srcv[i], non_blocking=True)

        gather_buf = torch.empty(
            (len(idx), cb), dtype=torch.uint8, device=f"cuda:{dev}"
        )
        host_buf = torch.empty((len(idx), cb), dtype=torch.uint8, pin_memory=True)
        it = torch.tensor(idx, device=f"cuda:{dev}")

        def gathered():
            torch.index_select(srcv, 0, it, out=gather_buf)
            host_buf.copy_(gather_buf, non_blocking=True)

        moved = len(idx) * cb
        t1 = statistics.median(_time_cuda(per_chunk, max(3, iters // 4)))
        t2 = statistics.median(_time_cuda(gathered, iters))
        out.append(
            {
                "chunk_bytes": cb,
                "moved_bytes": moved,
                "per_chunk_memcpy_Bps": moved / t1,
                "gather_then_copy_Bps": moved / t2,
            }
        )
    return out


def concurrent_all_gpu(n_gpu: int, nbytes: int, iters: int) -> float:
    bufs = []
    for d in range(n_gpu):
        torch.cuda.set_device(d)
        bufs.append(
            (
                torch.empty(nbytes, dtype=torch.uint8, pin_memory=True),
                torch.empty(nbytes, dtype=torch.uint8, device=f"cuda:{d}"),
            )
        )
    barrier = threading.Barrier(n_gpu)
    times = [0.0] * n_gpu

    def worker(d):
        torch.cuda.set_device(d)
        h, g = bufs[d]
        g.copy_(h, non_blocking=True)
        torch.cuda.synchronize(d)
        barrier.wait()
        t0 = time.perf_counter()
        for _ in range(iters):
            g.copy_(h, non_blocking=True)
        torch.cuda.synchronize(d)
        times[d] = time.perf_counter() - t0

    th = [threading.Thread(target=worker, args=(d,)) for d in range(n_gpu)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    return n_gpu * nbytes * iters / max(times)


def interference(dev: int, iters: int) -> dict:
    """Slowdown of an HBM-bound (decode-like) and a GEMM (prefill-like) kernel
    while H2D + D2H DMAs run on side streams."""
    torch.cuda.set_device(dev)
    x = torch.empty(2 * 1024**3 // 2, dtype=torch.bfloat16, device=f"cuda:{dev}")
    y = torch.empty_like(x)
    a = torch.randn(8192, 8192, dtype=torch.bfloat16, device=f"cuda:{dev}")
    b = torch.randn(8192, 8192, dtype=torch.bfloat16, device=f"cuda:{dev}")
    hbuf = torch.empty(512 * MiB, dtype=torch.uint8, pin_memory=True)
    dbuf = torch.empty(512 * MiB, dtype=torch.uint8, device=f"cuda:{dev}")
    hbuf2 = torch.empty(512 * MiB, dtype=torch.uint8, pin_memory=True)
    dbuf2 = torch.empty(512 * MiB, dtype=torch.uint8, device=f"cuda:{dev}")
    s_up, s_dn = torch.cuda.Stream(), torch.cuda.Stream()

    def mem_kernel():
        y.copy_(x)

    def gemm():
        torch.mm(a, b)

    res = {}
    for name, fn in (("decode_like", mem_kernel), ("gemm", gemm)):
        for _ in range(3):
            fn()
        torch.cuda.synchronize()
        alone = statistics.median(_time_cuda(fn, iters))
        stop = threading.Event()

        def pump():
            while not stop.is_set():
                with torch.cuda.stream(s_up):
                    dbuf.copy_(hbuf, non_blocking=True)
                with torch.cuda.stream(s_dn):
                    hbuf2.copy_(dbuf2, non_blocking=True)
                s_up.synchronize()
                s_dn.synchronize()

        th = threading.Thread(target=pump)
        th.start()
        time.sleep(0.05)
        busy = statistics.median(_time_cuda(fn, iters))
        stop.set()
        th.join()
        res[f"{name}_alone_s"] = alone
        res[f"{name}_with_dma_s"] = busy
        res[f"{name}_slowdown"] = busy / alone - 1.0
    return res


def alloc_cost(dev: int) -> dict:
    torch.cuda.set_device(dev)
    out = {}
    for n in (64 * MiB, 1024 * MiB):
        t0 = time.perf_counter()
        h = torch.empty(n, dtype=torch.uint8, pin_memory=True)
        out[f"pinned_alloc_{n // MiB}MiB_s"] = time.perf_counter() - t0
        del h
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        d = torch.empty(n, dtype=torch.uint8, device=f"cuda:{dev}")
        torch.cuda.synchronize()
        out[f"cuda_malloc_{n // MiB}MiB_s"] = time.perf_counter() - t0
        del d
        torch.cuda.empty_cache()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu-key", default=os.environ.get("GPU_KEY"))
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--max-mib", type=int, default=1024)
    ap.add_argument("--num-gpus", type=int, default=torch.cuda.device_count())
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    assert args.gpu_key, "set --gpu-key or GPU_KEY"
    out = (
        args.out
        or Path(__file__).resolve().parent.parent
        / "measured"
        / args.gpu_key
        / "transfer.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    res = {
        "device_name": torch.cuda.get_device_name(args.device),
        "torch": torch.__version__,
    }
    print("size sweep (pinned) ...")
    res["h2d_pinned"], res["d2h_pinned"] = size_sweep(
        args.device, True, args.iters, args.max_mib * MiB
    )
    print("size sweep (pageable) ...")
    res["h2d_pageable"], res["d2h_pageable"] = size_sweep(
        args.device, False, max(3, args.iters // 4), 256 * MiB
    )
    res["alpha_s"] = fit_alpha(res["h2d_pinned"])
    print("kv-block-shaped copies ...")
    res["kv_block_copy"] = kv_block_copy(
        args.device, 256 * MiB, [8 * 1024, 64 * 1024, 512 * 1024, 2 * MiB], args.iters
    )
    if args.num_gpus > 1:
        print(f"concurrent H2D on {args.num_gpus} GPUs ...")
        res["all_gpu_concurrent_h2d_Bps"] = concurrent_all_gpu(
            args.num_gpus, 512 * MiB, 10
        )
        res["num_gpus_concurrent"] = args.num_gpus
    print("interference ...")
    itf = interference(args.device, args.iters)
    res["interference"] = {
        **itf,
        "decode_like_slowdown": max(0.0, itf["decode_like_slowdown"]),
    }
    res["alloc"] = alloc_cost(args.device)
    out.write_text(json.dumps(res, indent=2))
    peak = max(r["bw_Bps"] for r in res["h2d_pinned"]) / 1e9
    print(
        f"wrote {out}\n  peak pinned H2D {peak:.1f} GB/s, alpha {res['alpha_s'] * 1e6:.1f} us, "
        f"decode-like slowdown {res['interference']['decode_like_slowdown'] * 100:.1f}%"
    )


if __name__ == "__main__":
    main()
