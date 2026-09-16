"""M-F1 — Flexibility를 **판정 정확도**로 정량화한다.

기존 M-F1(신규 메모리를 배치에 썼는가)의 결함은 측정에서 드러났다:
`ssd_pim_v2`를 "지원"한 두 정책이 모두 Goodput을 13~15% **잃었다**.
지원했다는 것이 이득을 뜻하지 않으므로, 이산 계수는 Flexibility의
지표가 될 수 없다.

대신 **오라클과의 일치율**로 정의한다. 신규 메모리 하나를 투입하고

    오라클 : 그 메모리를 넣었을 때 Goodput이 실제로 늘었는가
             (넣은 구성 vs 안 넣은 구성을 짝지어 비교. 정책과 무관한 사실)
    정책   : 그 메모리에 실제로 배치했는가

를 비교한다. 네 경우가 나온다.

    이득 O & 배치 O   적중 (TP)  — 새 특성을 살렸다
    이득 O & 배치 X   놓침 (FN)  — 기회를 못 봤다
    이득 X & 배치 O   오용 (FP)  — **기존 지표가 '지원'으로 세던 것**
    이득 X & 배치 X   회피 (TN)  — 쓰지 않는 것이 옳은 판단이었다

    M-F1  정확도    = (TP + TN) / N          [0, 1]
    M-F1b 오용률    = FP / (FP + TN)         낮을수록 좋다
    M-F1c 기회손실  = FN / (TP + FN)         낮을수록 좋다

정확도를 주 지표로 쓰되 오용률을 함께 봐야 한다 — 아무것도 안 쓰는
정책은 오용률 0이지만 기회손실 1이고, 다 쓰는 정책은 그 반대다.

투입 세트는 실행 전에 고정하고 사후에 바꾸지 않는다.
"""

from __future__ import annotations

import statistics
from dataclasses import replace

from .core import ATTENTION_PRIMITIVE_SET, Medium, MemorySpec

#: 이득 판정의 최소 크기. §4.0의 최소검출차(8.4%)보다 작으면
#: "이득 있음"이라고 말할 수 없다.
MIN_DETECTABLE_GAIN = 0.084


def _mk(name: str, **kw) -> MemorySpec:
    base = dict(
        medium=Medium.DRAM, capacity_bytes=int(2e12),
        ext_bw_bytes_per_s=6.3e10, int_bw_bytes_per_s=4.0e11,
        latency_s=2.0e-7, gpu_reachable=False,
        supported_primitives=frozenset(), compute_tflops_fp16=None,
        attention_bw_efficiency=None, write_amplification=1.0,
        endurance_budget_bytes=None, tdp_watts=100.0,
    )
    base.update(kw)
    return MemorySpec(name=name, **base)


#: 특성 공간의 축을 하나씩 대표하는 투입 세트.
#: 기존 4종에 **이득이 없어야 정상인 것**을 더 넣어 오용을 잡을 수 있게 했다.
PROBES: dict[str, tuple[MemorySpec, str]] = {
    "lpddr_bulk": (
        _mk("lpddr_bulk", capacity_bytes=int(4e12), ext_bw_bytes_per_s=8.0e10),
        "DRAM급 대역폭 + 대용량, 연산 없음"),
    "ssd_pim_v2": (
        _mk("ssd_pim_v2", medium=Medium.SSD_PIM, capacity_bytes=int(16e12),
            ext_bw_bytes_per_s=1.6e10, int_bw_bytes_per_s=2.0e11, latency_s=6.0e-5,
            supported_primitives=frozenset(ATTENTION_PRIMITIVE_SET),
            compute_tflops_fp16=2.0e12, attention_bw_efficiency=0.5,
            write_amplification=4.0, endurance_budget_bytes=1.0e16),
        "SOFTMAX 지원하나 내부 대역폭·지연이 나쁘다 — **써서는 안 되는 것**"),
    "nvm_fast": (
        _mk("nvm_fast", medium=Medium.HBF, capacity_bytes=int(2e12),
            ext_bw_bytes_per_s=1.0e12, int_bw_bytes_per_s=1.0e12,
            latency_s=5.0e-6, gpu_reachable=True),
        "HBM의 1/8 대역폭 + GPU 직결, 연산 없음"),
    "cxl_direct": (
        _mk("cxl_direct", medium=Medium.CXL_PNM, capacity_bytes=int(1e12),
            ext_bw_bytes_per_s=1.21e11, int_bw_bytes_per_s=1.1e12, latency_s=1.5e-7,
            gpu_reachable=True, supported_primitives=frozenset(ATTENTION_PRIMITIVE_SET),
            compute_tflops_fp16=1.6e13, attention_bw_efficiency=0.7),
        "GPU 직결 CXL + 충분한 연산"),
    "tiny_fast": (
        _mk("tiny_fast", capacity_bytes=int(8e9), ext_bw_bytes_per_s=2.0e12,
            int_bw_bytes_per_s=2.0e12, gpu_reachable=True),
        "매우 빠르나 8 GB뿐 — 용량이 모자라 **쓸 수 없는 것**"),
    "big_slow": (
        _mk("big_slow", capacity_bytes=int(64e12), ext_bw_bytes_per_s=4.0e9,
            int_bw_bytes_per_s=1.0e10, latency_s=2.0e-4),
        "64 TB인데 4 GB/s — 용량만 큰 **함정**"),
}


def evaluate(run_one, scenario, kinds, seeds, horizon_s, arrival_multiplier,
             base_memories) -> dict:
    """정책별 M-F1 정확도 / 오용률 / 기회손실."""
    out: dict = {}
    base_cache: dict[tuple, float] = {}

    for kind in kinds:
        tp = fn = fp = tn = 0
        detail = {}
        for nm, (spec, why) in PROBES.items():
            with_g, without_g, placed = [], [], 0
            for sd in seeds:
                r = run_one(scenario, kind, sd, horizon_s=horizon_s,
                            arrival_multiplier=arrival_multiplier,
                            memories_override=lambda ms, s=spec: base_memories + [s])
                with_g.append(r["goodput_tok_s"])
                placed += r["placement_hist"].get(nm, 0)
                key = (kind, sd)
                if key not in base_cache:
                    b = run_one(scenario, kind, sd, horizon_s=horizon_s,
                                arrival_multiplier=arrival_multiplier,
                                memories_override=lambda ms: base_memories)
                    base_cache[key] = b["goodput_tok_s"]
                without_g.append(base_cache[key])
            gw, gwo = statistics.mean(with_g), statistics.mean(without_g)
            gain = (gw - gwo) / max(gwo, 1e-9)
            helpful = gain >= MIN_DETECTABLE_GAIN     # 오라클
            used = placed > 0                          # 정책의 판단
            if helpful and used:      tp += 1; verdict = "적중"
            elif helpful and not used: fn += 1; verdict = "놓침"
            elif not helpful and used: fp += 1; verdict = "오용"
            else:                      tn += 1; verdict = "회피"
            detail[nm] = {"why": why, "gain": round(gain, 4), "helpful": helpful,
                          "used": used, "verdict": verdict,
                          "goodput_with": round(gw, 2), "goodput_without": round(gwo, 2)}
        n = tp + fn + fp + tn
        out[kind] = {
            # ⚠️ 유익한 투입이 없는 실험에서는 정확도가 "회피 능력"만 잰다.
            #    그 경우 `oracle_has_positive`가 False로 나오며 Flexibility의
            #    측정으로 인용해서는 안 된다.
            "M_F1_accuracy": (tp + tn) / n,
            "M_F1b_misuse_rate": fp / max(1, fp + tn),
            # TP+FN=0 이면 "유익한 투입이 하나도 없었다"는 뜻이므로 미정의다.
            # 0으로 두면 아무것도 안 쓰는 정책이 만점으로 보인다.
            "M_F1c_missed_rate": (fn / (tp + fn)) if (tp + fn) > 0 else None,
            "oracle_has_positive": (tp + fn) > 0,
            "confusion": {"TP": tp, "FN": fn, "FP": fp, "TN": tn},
            "detail": detail,
        }
    return out
