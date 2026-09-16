"""평가 실행기 — 시나리오 x 부하 x 정책 x seed 로 QA를 측정한다.

판정 규칙은 실행 전에 고정한다:
  - 워크로드는 정책과 무관하게 먼저 생성한다(trace). 같은 seed면 세 정책이
    **완전히 같은 입력**을 본다.
  - 정책 간 차이는 동일 seed에서 짝지어(paired) 비교하고, 95% 신뢰구간이
    0을 지나면 "차이 없음"으로 판정한다. 점 추정의 부호로 판정하지 않는다.
  - Goodput의 분모는 horizon으로 고정한다.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path

from .analyzer import KVCharacteristicAnalyzer
from .core import QueueStateView, load_config
from .engine import Engine, summarize
from .policies import AsIsPolicy, DataCentricPolicy, MemoryCentricPolicy
from .policy import TierScorer
from .workload import SCENARIOS, WorkloadGenerator, build_trace

CONFIG = Path(__file__).resolve().parent.parent / "configs" / "memories_default.json"
STEP_BUDGET_S = 0.05
KINDS = ["as-is", "C1", "C2"]

#: 부하 수준. 도착률 배수로 저부하 / 중부하 / 고부하를 대표한다.
LOADS = {"low": 1.0, "mid": 4.0, "high": 6.0}


def run_one(scenario, kind, seed, *, horizon_s, memories_override=None,
            tool_latency_scale=1.0, burst=False, max_concurrent=128, batch_size=16,
            arrival_multiplier=1.0, gpu_tdp_watts=8000.0):
    gpu, model, memories = load_config(CONFIG)
    if memories_override is not None:
        memories = memories_override(memories)

    # 워크로드는 정책과 무관하게 먼저 확정한다 (paired 비교의 전제).
    trace = build_trace(scenario, seed, horizon_s, tool_latency_scale,
                        arrival_multiplier, burst)
    rng = random.Random(seed ^ 0x5F5F)
    gen = WorkloadGenerator(scenario, rng, tool_latency_scale=tool_latency_scale,
                            arrival_multiplier=arrival_multiplier)
    max_ext = max(m.ext_bw_bytes_per_s for m in memories)
    scorer = TierScorer(model, max_ext, STEP_BUDGET_S)

    qv = QueueStateView()
    if kind == "as-is":
        policy, analyzer = AsIsPolicy(model, STEP_BUDGET_S), None
    elif kind == "C1":
        policy, analyzer = MemoryCentricPolicy(model, scorer, STEP_BUDGET_S), None
    else:
        analyzer = KVCharacteristicAnalyzer(qv)
        policy = DataCentricPolicy(model, scorer, analyzer, STEP_BUDGET_S)

    eng = Engine(policy, gpu, model, memories, gen, rng, trace=trace, analyzer=analyzer,
                 horizon_s=horizon_s, burst=burst, max_concurrent=max_concurrent,
                 batch_size=batch_size, step_budget_s=STEP_BUDGET_S)
    eng.queue_view = qv
    return summarize(eng.run(), memories, gpu_tdp_watts)


def paired_ci(a: list[float], b: list[float]) -> dict:
    """짝지은 차이 (a-b)의 평균과 95% 신뢰구간."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    if n < 2:
        return {"mean_diff": d[0] if d else 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0,
                "significant": False, "n": n}
    m = statistics.mean(d)
    sd = statistics.stdev(d)
    half = 1.96 * sd / math.sqrt(n)
    return {"mean_diff": m, "ci95_lo": m - half, "ci95_hi": m + half,
            "significant": (m - half) * (m + half) > 0, "n": n}


_AGG_KEYS = [
    "goodput_tok_s", "throughput_tok_s", "slo_attainment", "ttft_p50_s", "ttft_p99_s",
    "tpot_p50_s", "tpot_p99_s", "restore_s_total", "move_s_total",
    "decision_us_per_decision", "decision_ops_per_decision", "candidates_scored_avg",
    "offload_adoption", "hbm_kv_avg_gb", "hbm_idle_kv_avg_gb", "resource_parallelism",
    "gpu_busy_s", "mem_busy_s", "rejected", "turns",
    "move_s_per_turn", "decision_s_per_turn", "overhead_share",
]


def agg(rs: list[dict]) -> dict:
    out = {}
    for k in _AGG_KEYS:
        vals = [r[k] for r in rs if k in r]
        if vals:
            out[k] = statistics.mean(vals)
            out[k + "_sd"] = statistics.stdev(vals) if len(vals) > 1 else 0.0
    for field in ("placement_hist", "mode_hist"):
        h = {}
        for r in rs:
            for name, c in r.get(field, {}).items():
                h[name] = h.get(name, 0) + c
        out[field] = h
    end = {}
    for r in rs:
        for name, v in r.get("endurance", {}).items():
            end[name] = end.get(name, 0.0) + v
    out["endurance"] = end
    return out


_CMP_METRICS = ["goodput_tok_s", "slo_attainment", "ttft_p99_s", "ttft_p50_s",
                "hbm_idle_kv_avg_gb", "decision_us_per_decision",
                "offload_adoption", "resource_parallelism", "restore_s_total",
                "move_s_per_turn", "overhead_share"]


def _cell(scenario, seeds, horizon, **kw) -> dict:
    per = {k: [run_one(scenario, k, s, horizon_s=horizon, **kw) for s in seeds]
           for k in KINDS}
    cell = {k: agg(per[k]) for k in KINDS}
    cmp = {}
    for metric in _CMP_METRICS:
        for lhs, rhs in [("C2", "C1"), ("C1", "as-is"), ("C2", "as-is")]:
            cmp[f"{metric}:{lhs}-{rhs}"] = paired_ci(
                [x[metric] for x in per[lhs]], [x[metric] for x in per[rhs]])
    cell["paired"] = cmp
    return cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--horizon", type=float, default=400.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    seeds = list(range(1000, 1000 + args.seeds))
    short = seeds[: max(6, args.seeds // 2)]
    res: dict = {"config": {"seeds": args.seeds, "horizon_s": args.horizon,
                            "loads": LOADS, "step_budget_s": STEP_BUDGET_S},
                 "scenarios": {}, "sweeps": {}}
    mixed = next(s for s in SCENARIOS if s.name == "mixed_uniform")

    # ── 1) 시나리오 x 부하
    for sc in SCENARIOS:
        res["scenarios"][sc.name] = {"description": sc.description, "loads": {}}
        for lname, mult in LOADS.items():
            res["scenarios"][sc.name]["loads"][lname] = _cell(
                sc, seeds, args.horizon, arrival_multiplier=mult)
            print(f"  [scenario] {sc.name} / load={lname}", flush=True)

    # ── 2) 유휴 시간 분포 Sweep — 결론이 툴 실행 시간에 걸려 있는가
    res["sweeps"]["tool_latency"] = {
        f"x{s}": _cell(mixed, short, args.horizon, tool_latency_scale=s,
                       arrival_multiplier=LOADS["mid"])
        for s in [0.1, 0.3, 1.0, 3.0, 10.0]}
    print("  [sweep] tool_latency", flush=True)

    # ── 3) 배치 크기 Sweep — §4.3의 왕복 상쇄
    res["sweeps"]["batch_size"] = {
        f"b{b}": _cell(mixed, short, args.horizon, batch_size=b,
                       arrival_multiplier=LOADS["mid"])
        for b in [1, 4, 16, 64]}
    print("  [sweep] batch_size", flush=True)

    # ── 4) 동시성 한계 Sweep — Scheduler 설정이 우열을 뒤집는가
    res["sweeps"]["concurrency"] = {
        f"mc{m}": _cell(mixed, short, args.horizon, max_concurrent=m,
                        arrival_multiplier=LOADS["high"])
        for m in [8, 16, 32, 128]}
    print("  [sweep] concurrency", flush=True)

    # ── 5) Burst 도착 — 동적으로 변하는 부하
    res["sweeps"]["burst"] = {
        lname: _cell(mixed, seeds, args.horizon, burst=True, arrival_multiplier=mult)
        for lname, mult in LOADS.items()}
    print("  [sweep] burst", flush=True)

    # ── 6) 과부하 — 붕괴 지점
    res["sweeps"]["overload"] = {
        f"x{m}": _cell(mixed, short, args.horizon, arrival_multiplier=m)
        for m in [8.0, 12.0]}
    print("  [sweep] overload", flush=True)

    # ── 7) Flexibility (M-F1)
    res["flexibility"] = flexibility(short, args.horizon)
    print("  [flexibility]", flush=True)

    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "results.json"
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"\nwrote {out}")


def flexibility(seeds, horizon):
    """M-F1 — 신규 메모리를 **Configuration 교체만으로** 투입했을 때
    정책이 실제로 그 메모리에 배치했는가.

    투입 세트는 실행 전에 고정하고 사후에 바꾸지 않는다. 각각 기존 6종이
    갖지 못한 특성 조합을 하나씩 대표한다.

    계수 규칙 (설계 문서 §11.3):
      배치 bytes = 0            -> 미지원 (존재를 견딘 것이지 적응이 아니다)
      코드 수정 없이 배치 발생  -> 지원
    """
    from .core import ATTENTION_PRIMITIVE_SET, Medium, MemorySpec

    def mk(name, **kw):
        base = dict(medium=Medium.DRAM, capacity_bytes=int(2e12),
                    ext_bw_bytes_per_s=6.4e10, int_bw_bytes_per_s=4.0e11,
                    latency_s=2.0e-7, gpu_reachable=False,
                    supported_primitives=frozenset(), compute_tflops_fp16=None,
                    attention_bw_efficiency=None, write_amplification=1.0,
                    endurance_budget_bytes=None)
        base.update(kw)
        return MemorySpec(name=name, **base)

    new_mems = {
        "lpddr_bulk": (mk("lpddr_bulk", capacity_bytes=int(4e12),
                          ext_bw_bytes_per_s=8.0e10),
                       "DRAM급 대역폭 + CXL-PNM급 용량, 연산 없음"),
        "ssd_pim_v2": (mk("ssd_pim_v2", medium=Medium.SSD_PIM, capacity_bytes=int(16e12),
                          ext_bw_bytes_per_s=1.6e10, int_bw_bytes_per_s=2.0e11,
                          latency_s=6.0e-5,
                          supported_primitives=frozenset(ATTENTION_PRIMITIVE_SET),
                          compute_tflops_fp16=2.0e12, attention_bw_efficiency=0.5,
                          write_amplification=4.0, endurance_budget_bytes=1.0e16),
                       "SOFTMAX까지 지원하는 SSD-PIM — Mode C 대상이 되는가"),
        "nvm_fast": (mk("nvm_fast", medium=Medium.HBF, capacity_bytes=int(2e12),
                        ext_bw_bytes_per_s=1.0e12, int_bw_bytes_per_s=1.0e12,
                        latency_s=5.0e-6, gpu_reachable=True),
                     "HBM의 1/4 대역폭 + GPU 직결, 연산 없음 — Mode A 상주 매체가 되는가"),
        "cxl_direct": (mk("cxl_direct", medium=Medium.CXL_PNM, capacity_bytes=int(1e12),
                          ext_bw_bytes_per_s=2.56e11, int_bw_bytes_per_s=1.1e12,
                          latency_s=1.5e-7, gpu_reachable=True,
                          supported_primitives=frozenset(ATTENTION_PRIMITIVE_SET),
                          compute_tflops_fp16=1.6e13, attention_bw_efficiency=0.7),
                       "GPU 직결 CXL — CPU 두 홉 제약이 사라진 경우"),
    }

    mixed = next(s for s in SCENARIOS if s.name == "mixed_uniform")
    out = {}
    base_cache: dict[int, dict] = {}
    for kind in KINDS:
        supported, detail = 0, {}
        for nm, (spec, why) in new_mems.items():
            placements = 0.0
            gw = gwo = 0.0
            for seed in seeds:
                r = run_one(mixed, kind, seed, horizon_s=horizon,
                            arrival_multiplier=LOADS["mid"],
                            memories_override=lambda ms, s=spec: ms + [s])
                placements += r["placement_hist"].get(nm, 0)
                gw += r["goodput_tok_s"]
                key = (kind, seed)
                if key not in base_cache:
                    base_cache[key] = run_one(mixed, kind, seed, horizon_s=horizon,
                                              arrival_multiplier=LOADS["mid"])
                gwo += base_cache[key]["goodput_tok_s"]
            used = placements > 0
            detail[nm] = {"why": why, "placements": placements, "supported": used,
                          "goodput_with": gw / len(seeds),
                          "goodput_without": gwo / len(seeds)}
            supported += int(used)
        out[kind] = {"supported": supported, "of": len(new_mems), "detail": detail}
    return out


if __name__ == "__main__":
    main()
