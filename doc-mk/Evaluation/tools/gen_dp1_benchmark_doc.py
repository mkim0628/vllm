#!/usr/bin/env python3
"""Render the generated block of doc-mk/Evaluation/DP1/benchmark.md from DP1/sim/scenarios.py.

Discovers public zero-arg callables in scenarios.py named `scenarios` or `*_benchmark`
that return a list of Scenario dataclasses; one table per set. Stdlib only.
Short format: one row per scenario (brief | weakness | key params); Common set is only counted.
Usage: python3 gen_dp1_benchmark_doc.py [--check]
"""
import dataclasses, importlib, inspect, sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
SIM = EVAL / "DP1" / "sim"
DOC = EVAL / "DP1" / "benchmark.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"

TITLES = {
    "common_benchmark": "Common Benchmark realization (cb_*)",
    "scenarios": "DP1 Stress Benchmark",
    "dynamic_benchmark": "DP1 Dynamic Benchmark",
}
ORDER = ["common_benchmark", "scenarios"]
# Common set is defined in ../common-benchmark.md (CB-1..CB-3); it is only counted here, not listed.
SKIP_TABLE = {"common_benchmark"}
# Designed As-Is weakness each scenario is built to expose (documentation only; chosen from the
# scenario design, not from results).
WEAK = {
    "kv_b1_c32k_cold_cxl": "차가운 KV를 비싼 tier에 상주",
    "kv_b16_c32k": "중간 규모 기준선 (대조군)",
    "kv_b16_c32k_burst_chbm": "burst 시 HBM 부족분 전량 DRAM 복원",
    "kv_hbm_relief_behavior_recovery": "HBM 회복 후에도 승격 안 함",
    "kv_b64_c128k_cold": "cold KV 복원 비용을 host link로 지불",
    "kv_b256_c128k_burst": "burst + 공유 링크 포화",
    "kv_b64_c512k_long": "초장문 KV 용량 초과",
    "kv_b256_c512k_stress": "전 tier 용량 한계",
    "rag_1tib_b16": "인덱스 지역성 변화 미반영",
    "rag_8tib_b64_ssd_pim": "대용량 인덱스 전체를 host로 이동",
    "rag_8tib_b256_ssd_pim": "고동시성에서 동일 문제 악화",
    "kv_rag_b64_c128k": "KV-RAG HBM 경합",
    "agent_memory_long_lived": "cold 객체가 상위 tier 점유",
    "tool_result_bursty": "갑자기 hot해진 객체 승격 지연",
    "lora_multi_tenant_b64": "인기도 skew 미반영",
    "moe_expert_skew_b256": "expert skew 미반영",
    "mixed_all_ai_data_b64": "data type 무관 단일 정책의 한계",
    "hbm_pressure_ramp_b64": "압박 증가 시 선제 이동 못함",
    "hbm_bw_shock_b256": "HBM BW 저하에 고정 배치",
    "host_path_pressure_b64": "host 경로 경합 시 고정 tier 순서",
    "data_mix_shift_b64": "mix 변화 후 배치가 stale",
    "behavior_flip_stress": "급반전 시 정적 배치 stale",
    "six_tier_capacity_stress": "6개 tier 활용 못함",
    "dyn_cold_resident_chat_wave": "cold 데이터가 HBM 선점, hot KV는 DRAM",
    "dyn_idle_kv_holds_hbm": "도착 순서가 HBM 상주를 결정",
    "dyn_kv_hotset_recency_shift": "과거 working set에 배치 고정",
    "dyn_kv_rotating_hotset": "첫 window에만 맞는 배치",
    "dyn_rag_shard_hotset_shift": "hot shard를 DRAM에서 스캔",
    "dyn_host_path_contention_kv": "저하된 host 경로에 spill 유지",
}
# Representative scenarios (picked by design coverage before looking at results; the result document
# chooses its own representatives from data).
REPRESENTATIVE = {
    "kv_b16_c32k_burst_chbm", "hbm_pressure_ramp_b64", "rag_8tib_b64_ssd_pim", "behavior_flip_stress",
    "dyn_cold_resident_chat_wave", "dyn_kv_rotating_hotset",
}
ABBR = {"KV_CACHE": "KV", "RAG_DATA": "RAG", "AGENT_MEMORY": "Agent", "TOOL_RESULT": "Tool",
        "LORA_ADAPTER": "LoRA", "MOE_EXPERT": "MoE"}


def discover(mod):
    found = []
    for n, f in vars(mod).items():
        if n.startswith("_") or not callable(f) or inspect.isclass(f):
            continue
        if not (n == "scenarios" or n.endswith("_benchmark")):
            continue
        if getattr(f, "__module__", None) != mod.__name__:
            continue
        try:
            if any(p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                   for p in inspect.signature(f).parameters.values()):
                continue
            res = f()
        except Exception as e:  # tolerate half-edited code
            found.append((n, None, f"{type(e).__name__}: {e}"))
            continue
        if isinstance(res, list) and res and dataclasses.is_dataclass(res[0]):
            found.append((n, res, ""))
    key = lambda t: (ORDER.index(t[0]) if t[0] in ORDER else len(ORDER), t[0])
    return sorted(found, key=key)


def fmt_ctx(n):
    return f"{n//1024}K" if n % 1024 == 0 and n >= 1024 else str(n)


def params(sc):
    """Compact key params, e.g. `KV 32K b16 hbm x0.12 burst`."""
    mix = "+".join(ABBR.get(k, k) for k in sc.data_mix)
    if len(sc.data_mix) > 3:
        mix = f"mix{len(sc.data_mix)}"
    p = [mix, fmt_ctx(sc.context_tokens), f"b{sc.batch_size}"]
    for f, lab in (("hbm_capacity_mult", "hbm"), ("capacity_mult", "cap"), ("hbm_bw_mult", "hbmBW"),
                   ("host_bw_mult", "hostBW"), ("size_scale", "size")):
        v = getattr(sc, f)
        if v != 1.0:
            p.append(f"{lab} x{v:g}")
    if sc.rag_index_total_gib:
        g = sc.rag_index_total_gib
        p.append(f"idx {g/1024:g}T" if g >= 1024 else f"idx {g:g}G")
    if sc.phase:
        p.append(sc.phase.replace("_", "-"))
    if sc.disabled_tiers:
        p.append("no " + ",".join(sc.disabled_tiers))
    return " ".join(p)


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def render():
    sys.path.insert(0, str(SIM))
    mod = importlib.import_module("scenarios")
    sets = discover(mod)
    L = ["> Generated by `doc-mk/Evaluation/tools/gen_dp1_benchmark_doc.py` from `DP1/sim/scenarios.py` "
         "(`brief`, 파라미터) 및 생성기 내 WEAK 사전 (As-Is 약점). Do not edit by hand.", "",
         "| Benchmark set | Function | Scenarios |", "|---|---|---|"]
    for n, res, err in sets:
        L.append(f"| {TITLES.get(n, n)} | `scenarios.{n}()` | {len(res) if res is not None else 'ERROR'} |")
    L.append("")
    L.append("★ = 대표 시나리오. 파라미터: `b`=batch, `hbm x`=HBM 용량 배율, `idx`=RAG 인덱스 크기, "
             "나머지는 `scenarios.py` 필드. Dynamic은 시간별 객체 plan이 있어 코드 참조.")
    L.append("")
    gi = 0
    for n, res, err in sets:
        if n in SKIP_TABLE:
            continue
        gi += 1
        L += [f"## G.{gi} {TITLES.get(n, n)} ({len(res) if res else 0})", ""]
        if res is None:
            L += [f"> ERROR while calling `{n}()`: {err}", ""]
            continue
        L += ["| 시나리오 | 무엇인가 | 드러내는 As-Is 약점 | 핵심 파라미터 |", "|---|---|---|---|"]
        for sc in res:
            weak = WEAK.get(sc.name)
            if weak is None or not sc.brief:
                sys.exit(f"missing WEAK/brief for {sc.name}")
            star = " ★" if sc.name in REPRESENTATIVE else ""
            L.append("| " + " | ".join(esc(x) for x in [f"`{sc.name}`{star}", sc.brief, weak, params(sc)]) + " |")
        L.append("")
    return "\n".join(L).rstrip()


def main():
    block = f"{BEGIN}\n{render()}\n{END}"
    if not DOC.exists():
        print(block); return
    txt = DOC.read_text()
    if BEGIN not in txt or END not in txt:
        sys.exit(f"markers not found in {DOC}")
    new = txt[:txt.index(BEGIN)] + block + txt[txt.index(END) + len(END):]
    if "--check" in sys.argv:
        sys.exit(0 if new == txt else 1)
    DOC.write_text(new)
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
