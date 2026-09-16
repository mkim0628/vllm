"""부하 격자 측정 — 클러스터 x 모델 x (KV 압력 x context) x 정책.

부하는 **배치 크기 x context 길이**로 준다 (LLM 서빙 벤치마크의 통상 축).
다만 격자의 좌표는 배치를 직접 찍지 않고 **GPU HBM 용량 초과 배수**로
잡고 거기서 배치를 역산한다.

    KV 총량 = batch x context x KV/token  =  압력배수 x HBM 용량
    ->  batch = ceil(압력배수 x HBM 용량 / (context x KV/token))

이유: KV가 HBM에 다 들어가는 구간은 DP1의 문제 공간이 아니다. 그 구간에서는
어떤 정책이든 HBM에 두는 것이 최적이므로 배치 결정이 실재하지 않는다.
모델마다 KV/token이 자릿수로 다르고(320KB vs 107KB) 클러스터마다 HBM
용량이 다르므로, 배치를 고정값으로 찍으면 셀마다 압력이 제각각이 되어
비교가 성립하지 않는다.

배치 1은 평가에서 뺀다 - 단일 세션은 배치 결정이 무의미하다.
동시 세션 한도를 배치 크기로 두고, 도착률은 그 한도를 채우도록 배치에
비례해 키운다 - 도착률은 배치를 채우는 수단일 뿐 부하의 좌표가 아니다.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from .core import apply_cluster, load_cluster, load_config, load_model
from .run_eval import run_one
from .workload import SCENARIOS

HERE = Path(__file__).resolve().parent.parent
MEMCFG = HERE / "configs" / "memories_default.json"
CLCFG = HERE / "configs" / "clusters.json"
MDCFG = HERE / "configs" / "models.json"

CLUSTERS = ["b200_8gpu", "vera_rubin_8gpu"]
MODELS = ["llama_3_1_70b", "llama_4_maverick", "glm_5"]
KINDS = ["as-is", "C1", "C2"]

#: 부하 좌표 — GPU HBM 용량의 몇 배를 KV로 채우는가. 전부 1.0 초과다.
#: 이 구간에서는 TTFT SLO(2s)가 물리적으로 도달 불가라 SLO-gated goodput이
#: 전부 0이 된다. 주 지표는 throughput 과 TTFT/TPOT 꼬리다.
KV_PRESSURE = [1.2, 1.5, 2.0, 4.0]
#: context 길이. 배치는 (압력, context)에서 역산한다.
CONTEXT_LEVELS = [131072, 524288]
#: 배치 상한. 넘으면 그 셀은 상한으로 잘리고 실제 압력이 목표보다 낮아진다.
MAX_BATCH = 1024
#: 세션 도착률을 배치에 비례해 키운다. horizon의 이 비율 안에 배치가 차도록.
FILL_FRACTION = 0.15

KEYS = ["goodput_tok_s", "throughput_tok_s", "ttft_p50_s", "ttft_p99_s",
        "tpot_p50_s", "tpot_p99_s", "slo_attainment", "move_bytes_per_token",
        "joules_per_token", "rejected", "offload_adoption"]


def arrival_for(scenario, batch, horizon):
    """배치를 horizon의 FILL_FRACTION 안에 채우는 도착률 배수."""
    target_rate = batch / max(1e-9, horizon * FILL_FRACTION)
    return max(1.0, target_rate / scenario.arrival_rate_per_s)


def cell(scenario, kind, seeds, *, memories, gpu, model, gpu_tdp, batch, ctx, horizon):
    am = arrival_for(scenario, batch, horizon)
    rs = [run_one(scenario, kind, sd, horizon_s=horizon,
                  memories_override=lambda ms: memories,
                  model_override=model, gpu_override=gpu,
                  arrival_multiplier=am,
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
                            "scenario": a.scenario, "kv_pressure": KV_PRESSURE,
                            "context_levels": CONTEXT_LEVELS,
                            "max_batch": MAX_BATCH,
                            "fill_fraction": FILL_FRACTION}, "grid": {}}

    for cl in CLUSTERS:
        gpu, meta = load_cluster(CLCFG, cl)
        mems = apply_cluster(base_mems, meta)
        res["grid"][cl] = {"hbm_capacity_bytes": meta["hbm_capacity_bytes"],
                           "gpu_tdp_watts": meta["tdp_watts"], "models": {}}
        for mn in MODELS:
            model = load_model(MDCFG, mn)
            mrow: dict = {"kv_bytes_per_token": model.kv_bytes_per_token(),
                          "attention_kind": model.attention_kind, "cells": {}}
            for press in KV_PRESSURE:
                for ctx in CONTEXT_LEVELS:
                    per = model.kv_bytes_for(ctx)
                    b = math.ceil(press * meta["hbm_capacity_bytes"] / per)
                    b = max(2, min(MAX_BATCH, b))     # 배치 1은 평가에서 제외
                    key = f"p{press:g}_c{ctx // 1024}k"
                    kv_total = b * per
                    c = {"kv_total_bytes": kv_total, "batch": b,
                         "target_pressure": press,
                         "actual_pressure": kv_total / meta["hbm_capacity_bytes"],
                         "batch_capped": b == MAX_BATCH,
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
