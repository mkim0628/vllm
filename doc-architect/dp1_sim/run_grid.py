"""부하 격자 측정 — 클러스터 x 모델 x (배치 x context) x 정책.

부하는 **배치 크기 x context 길이**로 준다 (LLM 서빙 벤치마크의 통상 축).
배치를 실제 부하로 만들기 위해 동시 세션 한도를 배치 크기로 두고,
도착률은 그 한도를 채울 만큼 충분히 높게 준다 — 도착률은 배치를 채우는
수단일 뿐 부하의 좌표가 아니다.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from .core import apply_cluster, load_cluster, load_config, load_model
from .run_eval import run_one
from .workload import BATCH_LEVELS, CONTEXT_LEVELS, SCENARIOS

HERE = Path(__file__).resolve().parent.parent
MEMCFG = HERE / "configs" / "memories_default.json"
CLCFG = HERE / "configs" / "clusters.json"
MDCFG = HERE / "configs" / "models.json"

CLUSTERS = ["b200_x16_2node", "gb200_nvl72", "rubin_x16_2node"]
MODELS = ["llama_3_1_70b", "llama_4_maverick", "glm_5"]
KINDS = ["as-is", "C1", "C2"]
#: 배치를 채우기 위한 도착률 배수. 좌표가 아니라 포화 수단이다.
SATURATING_ARRIVAL = 40.0

KEYS = ["goodput_tok_s", "throughput_tok_s", "ttft_p50_s", "ttft_p99_s",
        "tpot_p50_s", "tpot_p99_s", "slo_attainment", "move_bytes_per_token",
        "joules_per_token", "rejected", "offload_adoption"]


def cell(scenario, kind, seeds, *, memories, gpu, model, gpu_tdp, batch, ctx, horizon):
    rs = [run_one(scenario, kind, sd, horizon_s=horizon,
                  memories_override=lambda ms: memories,
                  model_override=model, gpu_override=gpu,
                  arrival_multiplier=SATURATING_ARRIVAL,
                  max_concurrent=batch, batch_size=batch,
                  context_tokens=ctx, gpu_tdp_watts=gpu_tdp)
          for sd in seeds]
    out = {k: statistics.mean(r.get(k, 0.0) for r in rs) for k in KEYS}
    agg: dict = {}
    for r in rs:
        t = max(1, sum(r["placement_hist"].values()))
        for k, v in r["placement_hist"].items():
            agg[k] = agg.get(k, 0.0) + v / t / len(rs)
    out["placement"] = {k: round(v, 4) for k, v in sorted(agg.items(), key=lambda x: -x[1])}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--horizon", type=float, default=200.0)
    ap.add_argument("--scenario", default="mixed_uniform")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "grid_results.json"))
    a = ap.parse_args()

    seeds = list(range(1000, 1000 + a.seeds))
    sc = next(s for s in SCENARIOS if s.name == a.scenario)
    _, _, base_mems = load_config(MEMCFG)

    res: dict = {"config": {"seeds": a.seeds, "horizon_s": a.horizon,
                            "scenario": a.scenario, "batch_levels": BATCH_LEVELS,
                            "context_levels": CONTEXT_LEVELS,
                            "saturating_arrival": SATURATING_ARRIVAL}, "grid": {}}

    for cl in CLUSTERS:
        gpu, meta = load_cluster(CLCFG, cl)
        mems = apply_cluster(base_mems, meta)
        res["grid"][cl] = {"hbm_capacity_bytes": meta["hbm_capacity_bytes"],
                           "gpu_tdp_watts": meta["tdp_watts"], "models": {}}
        for mn in MODELS:
            model = load_model(MDCFG, mn)
            mrow: dict = {"kv_bytes_per_token": model.kv_bytes_per_token(),
                          "attention_kind": model.attention_kind, "cells": {}}
            for b in BATCH_LEVELS:
                for ctx in CONTEXT_LEVELS:
                    key = f"b{b}_c{ctx // 1024}k"
                    kv_total = b * model.kv_bytes_for(ctx)
                    c = {"kv_total_bytes": kv_total,
                         "exceeds_hbm": kv_total > meta["hbm_capacity_bytes"]}
                    for kind in KINDS:
                        c[kind] = cell(sc, kind, seeds, memories=mems, gpu=gpu,
                                       model=model, gpu_tdp=meta["tdp_watts"],
                                       batch=b, ctx=ctx, horizon=a.horizon)
                    mrow["cells"][key] = c
            res["grid"][cl]["models"][mn] = mrow
            print(f"  [grid] {cl} / {mn}", flush=True)

    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
