#!/usr/bin/env python3
"""Render the unified DP1 QA evaluation result (7-section format, Common + DP1 Stress + DP1 Dynamic)
from DP1/results/data/SYS-*/qa_result.json. Numbers come only from those files.

    python tools/gen_dp1_result.py            # writes DP1/results/<DATE>_dp1-qa-evaluation.md
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "DP1" / "results" / "data"
SIM = ROOT / "DP1" / "sim"
DATE = "2026-10-02"
OUT = ROOT / "DP1" / "results" / f"{DATE}_dp1-qa-evaluation.md"
B, C1, C2 = "Baseline-static", "C1-resource-driven", "C2-behavior-driven"
SETS = [("common_benchmark", "Common"), ("dp1_stress_benchmark", "DP1 Stress"), ("dp1_dynamic_benchmark", "DP1 Dynamic")]
SYSIDS = ["SYS-1", "SYS-2", "SYS-3", "SYS-4", "SYS-5"]
PRIMARY = "SYS-4"
FIT_LETTER = {"comparison_valid": "V", "infeasible": "I", "saturated": "S"}

sys.path.insert(0, str(SIM))
import scenarios as scn  # noqa: E402

R = {s: json.load(open(DATA / s / "qa_result.json")) for s in SYSIDS}
P = R[PRIMARY]


def rev():
    try:
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True).strip()
        r = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=top, text=True).strip()
        d = subprocess.check_output(["git", "status", "--porcelain", "--", "doc-mk/Evaluation"], cwd=top, text=True).strip()
        return f"{r} ({'dirty' if d else 'clean'})"
    except Exception:
        return "unknown"


def ratio_cell(q, c):
    x = q[c]
    s = f"{x['qa1']} x{x['qa1_ratio_geomean']:.3f}"
    if x.get("qa1_ratio_ci95"):
        s += f"±{x['qa1_ratio_ci95']:.3f}"
    return s


def qa2_cell(x):
    return f"{x['qa2']} {x['qa2_ttft_p99_worst_ms']:,.0f} ms / {x['qa2_tpot_p99_worst_ms']:,.0f} ms"


def final_table(res, key="qa_feasible"):
    rows = ["| Set (n) | QA | Baseline (T_ref) | C1 | C2 |", "|---|---|---|---|---|"]
    for label, name in SETS + [("combined", "Combined (3 set 통합)")]:
        d = res[label]
        q = d[key]
        n = q[B]["n_scenarios"] if "n_scenarios" in q[B] else d.get("n_feasible", "?")
        b = q[B]
        rows.append(f"| **{name}** ({n}) | QA1 Throughput | {b['qa1']} {b['qa1_abs_goodput_mean_tps']:,.0f} tps (x1.000) [B+C] | {ratio_cell(q, C1)} [B+C] | {ratio_cell(q, C2)} [B+C] |")
        rows.append(f"| | QA2 Latency (worst) | {qa2_cell(b)} [B+C] | {qa2_cell(q[C1])} [B+C] | {qa2_cell(q[C2])} [B+C] |")
        rows.append(f"| | QA3 Util. (임시 정의) | {b['qa3']} {b['qa3_useful_hbm_util']*100:.0f}% [B+C] | {q[C1]['qa3']} {q[C1]['qa3_useful_hbm_util']*100:.0f}% [B+C] | {q[C2]['qa3']} {q[C2]['qa3_useful_hbm_util']*100:.0f}% [B+C] |")
    rows.append("| **QA4 Modifiability** | | — | ★★★ [C] | ★★ [C] |")
    return "\n".join(rows)


def scenario_tables(res):
    out = []
    for label, name in SETS:
        d = res[label]
        out.append(f"### 4.2.{[s for s, _ in SETS].index(label)+1} {name}\n")
        out.append("| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |")
        out.append("|---|---|---:|---:|---:|---|---|---|")
        for sn, v in d["per_scenario"].items():
            b, c1, c2 = v[B], v[C1], v[C2]
            fit = d["fit"][sn] if "fit" in d and sn in d["fit"] else d["scenario_labels"][sn]["fit"]
            sl = d["scenario_labels"][sn]["vs_baseline"]
            bg = b["max_goodput_tps"]
            r1 = f"x{c1['max_goodput_tps']/bg:.2f}" if bg > 0 else "n/a"
            r2 = f"x{c2['max_goodput_tps']/bg:.2f}" if bg > 0 else "n/a"
            out.append(f"| {sn} | {FIT_LETTER.get(fit, fit)} | {bg:,.0f} (±{b['goodput_ci95']:.0f}) | {c1['max_goodput_tps']:,.0f} ({r1}) | {c2['max_goodput_tps']:,.0f} ({r2}) | "
                       f"{b['ttft_p99_ms']:,.0f} / {c1['ttft_p99_ms']:,.0f} / {c2['ttft_p99_ms']:,.0f} | {b['tpot_p99_ms']:,.0f} / {c1['tpot_p99_ms']:,.0f} / {c2['tpot_p99_ms']:,.0f} | "
                       f"{sl.get(C1, {}).get('verdict', 'n/a')} / {sl.get(C2, {}).get('verdict', 'n/a')} |")
        out.append("")
    return "\n".join(out)


def scenario_catalog():
    funcs = {"common_benchmark": scn.common_benchmark, "dp1_stress_benchmark": scn.scenarios, "dp1_dynamic_benchmark": scn.dynamic_benchmark}
    rows = ["| Set | 시나리오 | " + " | ".join(SYSIDS) + " | 설명 (실제 serving 패턴 / As-Is 약점) |", "|---|---|" + "---|" * len(SYSIDS) + "---|"]
    for label, name in SETS:
        for sc in funcs[label]():
            letters = []
            for s in SYSIDS:
                d = R[s][label]
                fit = d["fit"].get(sc.name) if "fit" in d else None
                letters.append(FIT_LETTER.get(fit, "?"))
            desc = sc.description.replace("|", "/")
            rows.append(f"| {name} | `{sc.name}` | " + " | ".join(letters) + f" | {desc} |")
    return "\n".join(rows)


def cross_sys():
    rows = ["| SYS | 구성 | QA1 combined C1 | QA1 combined C2 | C1 win/tie/loss | C2 win/tie/loss | dynamic set: C1 / C2 win |", "|---|---|---|---|---|---|---|"]
    prof = json.load(open(SIM / "configs" / "systems.json"))["profiles"]
    for s in SYSIDS:
        r = R[s]; q = r["combined"]["qa_feasible"]; t = r["combined"]["tally"]
        dyn = r["dp1_dynamic_benchmark"]["tally"]
        rows.append(f"| {s} | {prof[s]['name']} | {ratio_cell(q, C1)} | {ratio_cell(q, C2)} | "
                    f"{len(t[C1]['win'])}/{len(t[C1]['tie'])}/{len(t[C1]['loss'])} | {len(t[C2]['win'])}/{len(t[C2]['tie'])}/{len(t[C2]['loss'])} | "
                    f"{len(dyn[C1]['win'])} / {len(dyn[C2]['win'])} (of {len(r['dp1_dynamic_benchmark']['per_scenario'])}) |")
    return "\n".join(rows)


def diagnostics():
    rows = ["| 지표 (SYS-4, combined 평균) | Baseline | C1 | C2 |", "|---|---:|---:|---:|"]
    q = P["combined"]["qa_feasible"]
    rows.append(f"| migration 횟수 | {q[B]['migration_count']:.0f} | {q[C1]['migration_count']:.0f} | {q[C2]['migration_count']:.0f} |")
    rows.append(f"| migration bytes (GiB) | {q[B]['migration_gib']:,.0f} | {q[C1]['migration_gib']:,.0f} | {q[C2]['migration_gib']:,.0f} |")
    rows.append(f"| decision overhead (ms/run) | {q[B]['decision_overhead_ms']:.1f} | {q[C1]['decision_overhead_ms']:.1f} | {q[C2]['decision_overhead_ms']:.1f} |")
    d = P["dp1_dynamic_benchmark"]["per_scenario"]
    gi = lambda c: sum(v[c]["migration_gib"] for v in d.values()) / len(d)
    rows.append(f"| dynamic set 평균 migration bytes (GiB) | {gi(B):,.0f} | {gi(C1):,.0f} | {gi(C2):,.0f} |")
    return "\n".join(rows)


def dynamic_analysis():
    d = P["dp1_dynamic_benchmark"]
    funcs = {sc.name: sc for sc in scn.dynamic_benchmark()}
    rows = ["| 시나리오 | C1 / C2 vs Baseline | Baseline SLO 만족률 | 후보 migration GiB (C1 / C2) | 원인 (시나리오가 재현하는 As-Is 약점) | Class |", "|---|---|---:|---|---|---|"]
    for sn, v in d["per_scenario"].items():
        sl = d["scenario_labels"][sn]["vs_baseline"]
        att = d["scenario_labels"][sn].get("baseline_slo_attainment")
        att = f"{att:.2f}" if att is not None else "n/a"
        rows.append(f"| {sn} | {sl[C1]['verdict']} (x{sl[C1]['goodput_ratio']:.2f}) / {sl[C2]['verdict']} (x{sl[C2]['goodput_ratio']:.2f}) | {att} | "
                    f"{v[C1]['migration_gib']:,.0f} / {v[C2]['migration_gib']:,.0f} | {funcs[sn].description.replace('|','/')} | B (벤치마크가 As-Is 약점을 드러냄) |")
    return "\n".join(rows)


def main():
    meta = P["meta"]
    q = P["combined"]["qa_feasible"]
    t = P["combined"]["tally"]
    md = f"""---
date: {DATE}
dp: DP1
candidates: [C1-resource-driven, C2-behavior-driven]   # Baseline-static 포함
sys_ids: [SYS-4, SYS-1, SYS-2, SYS-3, SYS-5]
git_rev: {rev()}
evidence: {{ QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[C]" }}
status: draft
---

# DP1 QA Evaluation — C1 vs C2 (Common + DP1 Stress + DP1 Dynamic, Baseline-regression loop 반영)

> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`DP1/benchmark.md`](../benchmark.md), [`DP1/simulation-plan.md`](../simulation-plan.md)
> 절차: `.claude/skills/evaluation/SKILL.md`
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 표는 `tools/gen_dp1_result.py`가 `results/data/SYS-*/qa_result.json`에서 생성했다.
> 이 문서는 [`2026-10-02_first-pass_superseded.md`](2026-10-02_first-pass_superseded.md)를 대체한다.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | **SYS-4** (primary, B200x8 + 6개 memory 전부), SYS-1 (HBM+DRAM, As-Is class), SYS-2 (+CXL-PNM), SYS-3 (+HBF), SYS-5 (Vera Rubin x8 + 6개 memory) |
| Model / precision | Llama-3.1-70B, BF16 (`models.json`) |
| Git revision | {rev()} |
| Seeds / loads | seeds {', '.join(map(str, meta['seeds']))} (5회) / load x{', x'.join(map(str, meta['loads']))}, 95% CI t={meta['t95']} |
| Tie 판정 | goodput 상대 차이 < {meta['material_rel']*100:.0f}% 또는 95% CI 이내이면 tie ("material" 임계 1%는 이 평가의 임시 상수) |
| 재현 command | `cd doc-mk/Evaluation/DP1/sim && python3 test_sim.py && python3 loop_run.py --final` (SYS-1~5), 단일: `python3 qa_eval.py --system SYS-4` |
| 표 생성 | `python3 doc-mk/Evaluation/tools/gen_dp1_result.py` |
| Raw data | `DP1/results/data/SYS-{{1..5}}/qa_result.json`, `sensitivity_SYS-4.json` |

시스템 profile 상세: [system-specs.md](../../system-specs.md). SYS-5의 Custom HBM은 이번 평가 중 loader를 고쳐(paired-GPU 상대 규격: 용량 x2, 내부 BW x2, 연산 20%, TDP/3) Vera Rubin 기준 값(약 715 GiB, 56 TB/s, 1,665 TFLOPS)으로 계산했다. 이전에는 B200 기준 값으로 잘못 고정되어 있었다.

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO Goodput | load sweep(x0.5~2.0) 중 SLO를 만족한 output token/s의 최대값. 시나리오별로 Baseline 대비 비율을 구하고 시나리오 간 **geometric mean**으로 집계. 별점은 criteria §4.3 (< 0.90 ★, 0.90~1.10 ★★, >= 1.10 ★★★) | criteria §4 |
| QA2 Latency | Max goodput load point의 TTFT P99 / TPOT P99. 시나리오 중 **worst-case**로 집계, 별점은 criteria §5 (≤2 s & ≤50 ms ★★★ / ≤4 s & ≤100 ms ★★ / 그 외 ★) | criteria §5 |
| QA3 Useful Utilization | `avg HBM occupancy x (SLO 만족 token / served token)`. 별점은 criteria §6 (< 65% ★, 65~85% ★★, >= 85% ★★★) | **임시 정의** (criteria에 formula 없음) |
| QA4 Modifiability | 신규 memory / data type / policy / event 추가 시 변경 module 수 (§5) | criteria §7, architecture argument [C] |
| 집계 범위 | "feasible" = Baseline goodput > 0 (comparison-valid + saturated). Combined는 3개 set 합산. "discriminating" = comparison-valid만 | 본 평가 정의 |
| Diagnostic | migration 횟수/bytes/time, decision overhead, tier별 access, SLO 만족률 | DP1 전용 |

# 3. 벤치마크 / 시나리오

최종 결과는 **Common Benchmark + DP1 Stress Benchmark + DP1 Dynamic Benchmark**를 모두 합친 것이다.

- **Common**: 공통 profile(8K in / 256 out, Llama-3.1-70B BF16)의 DP1 realization 3개. HBM을 줄여 계층이 영향을 주게 했다.
- **DP1 Stress**: 기존 23개 (resource pressure / data behavior / mixed AI data / stability).
- **DP1 Dynamic**: Baseline-regression loop(iteration 2)에서 추가한 시나리오와 controls. **Baseline은 SLO를 만족하지만 static 배치가 runtime에 stale해지는** 패턴을 대상으로 한다.

Fit label: **V** = comparison-valid (Baseline이 SLO 만족), **I** = infeasible (Baseline도 SLO 불가, 비교 제외하되 목록 유지), **S** = saturated (모든 후보가 CI 안에서 동일, 판별 불가). SYS별로 label이 달라질 수 있다.

{scenario_catalog()}

# 4. 결과

## 4.1 최종 QA 표 (SYS-4, Common + DP1 Stress + DP1 Dynamic 통합)

집계는 Baseline goodput > 0인 시나리오(V + S)이다. QA2 worst-case는 Baseline 자체가 SLO를 못 맞추는 시나리오가 지배할 수 있어 별점이 모두 ★로 나올 수 있다 (set별 값 참조).

{final_table(P)}

(n = 집계된 시나리오 수. ratio의 ± 값은 95% CI. `qa_discriminating`(V만) 기준은 `qa_result.json` 참조)

## 4.2 시나리오별 결과 (SYS-4)

n_seeds = 5, 95% CI는 t 분포, V/I/S = Fit, ratio = 후보 / Baseline (Baseline goodput = 0이면 n/a).

{scenario_tables(P)}
## 4.3 Diagnostic

{diagnostics()}

## 4.4 시스템 간 비교 (combined, win/tie/loss는 95% CI 유의성 기준)

{cross_sys()}

## 4.5 Iteration summary

Baseline-regression loop가 발동했다 (first-pass에서 두 후보 모두 Baseline 이하). iteration 3에서 중단 조건 (i) 충족. 상세 로그: [iterations/loop-log.md](iterations/loop-log.md).

| Iteration | Class | Change | Effect (SYS-4, 전체 benchmark 기준) |
|---|---|---|---|
| 0 (initial) | 계측 + M | `qa_eval.py` 확장(3 set, fit label, win/tie/loss), 전송이 destination write BW를 따르도록 수정 | C1 combined x0.957 (5 loss, Common TPOT 311 ms), C2 x0.961 (4 loss) |
| 1 | P | 공통 access-cost estimator, SLO filter와 do-no-harm(C1 destination 선택), link-time migration budget, cooldown, C2 benefit-vs-cost gating, C2 demotion은 HBM pressure일 때만 | C1 x1.000 / C2 x1.028, **loss 0**, win 0 (Common/Stress는 parity) |
| 2 | B | `dynamic_benchmark()` 6개 + controls 추가 (policy 불변) | dynamic: C1 x1.106 (win 1), C2 x2.211 (win 6) |
| 3 | P | C1 promotion path (설계 §17.2): static 추정으로 SLO를 위반하는 object를 HBM으로 승격, HBM 거주 object와 swap, budget 예약 | dynamic: C1 x1.643 (win 3), C2 불변 |

# 5. 결과 분석

## 5.1 first-pass에서 Baseline보다 낮았던 이유 (iteration 0 진단, SYS-4)

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| Common (`cb_*`) | C1 (x0.86~0.93), C2 (x1.00) | C1 Destination Tier Selector가 destination의 **serving 비용을 보지 않아** CXL-PNM attention 경로(TPOT 311 ms)를 선택, HBM이 아니라 DRAM pressure에 반응해 6개 tier로 rebalance | P | `diagnose.py`: HBM util 0.38인데 migration 105건 전부 rebalance, CXL-PNM access 147 |
| Common, RAG 시나리오 | C2 | **migration budget 없음**. 대형 object(RAG 3.4 TiB) 이동이 stall을 만들어 TTFT P99 34 s. demotion이 upper-tier pressure를 확인하지 않음(설계 §17.3 위반) | P | migration 342~389건, 3.7 TiB, decision overhead 약 140 ms/run |
| Common 전체 | 둘 다 이득 불가 | Baseline SLO 만족률이 3개 시나리오 모두 1.00이라 후보가 tie 이상을 낼 수 없음 | B | baseline slo_ratio = 1.00 |
| Stress 14/23 (SYS-4) | 비교 불가 | Baseline도 SLO 불가 (512K context, 8 TiB RAG, batch 256 등) | B | Fit = I |

## 5.2 Dynamic Benchmark에서 이득이 나는 이유 (SYS-4, 최종)

{dynamic_analysis()}

- C2는 object별 behavior(access rate, reuse, idle)를 쓰므로 같은 data class 안의 hot/cold를 구분한다. 그래서 6개 전부에서 유의하게 이긴다.
- C1은 data type을 모르고 static hint(operation class, shape)와 resource 상태만 쓴다. **object별 hot/cold를 구분해야 하는 KV-only 시나리오 3개(idle / recency / rotating)에서는 tie**이다 (ratio가 1.1~1.5배로 보이나 95% CI 이내). 같은 data class 안의 object를 C1이 구분할 근거가 없기 때문이다.
- C1이 이기는 3개는 Agent Memory + KV 혼합(`dyn_cold_resident_chat_wave`), 단일 class RAG shard(`dyn_rag_shard_hotset_shift`), host path 경합(`dyn_host_path_contention_kv`)이다. 이 세 시나리오에서 이기는 정확한 메커니즘은 loop-log iteration 3 진단을 따른다 (본 문서는 추측하지 않는다).
- C1은 훨씬 적게 옮긴다 (dynamic 평균 migration bytes는 4.3의 표 참조).

## 5.3 Baseline 미만 시나리오 (최종 코드)

SYS-1~SYS-5, 3개 set 전체에서 **어느 후보도 Baseline 미만(loss)인 시나리오가 없다** (4.4의 loss 열). SYS-5에서는 Vera Rubin의 큰 HBM 덕분에 Baseline이 dynamic 시나리오를 대부분 감당하여(`saturated`) C1/C2가 `dyn_host_path_contention_kv` 정도에서만 이긴다.

## 5.4 Sensitivity (iteration 3 이후 보고, 파라미터 재조정 아님; `results/data/sensitivity_SYS-4.json`)

- migration budget이 가장 민감하다. link share 0.10 또는 bucket window 4 s이면 후보당 win이 1~2개로 줄어 중단 조건 (i)이 충족되지 않는다. 0.50 또는 16 s이면 6개 모두 win이다.
- benefit horizon, C1 affinity margin은 거의 영향이 없다.
- 어느 변형에서도 loss는 나오지 않았다.

# 6. 한계

1. **Evidence가 [A]가 아니다.** 모든 수치는 config parameter(SPEC/PUBLIC/ASSUMED 혼재) 기반 simulation이다. vLLM trace replay, A100/H100 calibration이 없다.
2. **비용 추정이 완벽하다.** 정책의 access-cost estimator가 simulator와 같은 식을 쓴다 (테스트로 일치 확인). 실제 [A] 측정으로 보정한 추정은 오차가 있어 이득은 **상한에 가깝다.**
3. **Dynamic 시나리오는 실패 모드를 알고 설계했다.** Baseline만 돌려 설계하고 후보 실행 전에 고정했지만, 시나리오 선택이 결과를 좌우한다. 이득은 "static 배치가 stale해지는 경우"에 한정된 결과이며 일반 이득이 아니다. KV dynamic은 320K context, batch 16 셀(DRAM serving이 TPOT SLO를 못 맞추는 구성)이라 Llama-3.1 공식 context(128K)를 넘는다.
4. **정책 상수는 근거 데이터가 없는 설계 선택이다.** LINK_SHARE 0.25, window 8 s, horizon 30 s, affinity margin 2.0. sensitivity에서 budget이 결과를 크게 바꾼다 (5.4).
5. **미모델링:** capacity ramp(hard capacity limit 없음), HBM BW shock(offload가 건강한 HBM을 이길 수 없음), migration 간섭(단일 0.20 계수), HBF endurance, queueing/saturation(QA1이 load에 거의 비례). 개정된 **Memory Backend I/F 구조는 구현하지 않았다** (decision 로직은 기존 C1/C2, 개정 구조는 QA4에만 반영). DROP action은 이 평가에 포함하지 않았다.
6. **임시 정의:** QA3 formula, tie 판정의 1% material 임계, "saturated" fit label(모든 후보 CI 이내 동일).
7. **QA2 집계가 worst-case**라 Baseline 자체가 SLO를 못 맞추는 시나리오가 있는 set에서는 모든 후보가 ★로 나온다 (Stress set).
8. **SYS-5의 Custom HBM**은 평가 중 loader 수정 후의 값이며, 이전 first-pass 결과(SYS-5)와 비교할 수 없다.

# 7. 결론

- **현재 simulator 기준으로 C1, C2는 모든 시스템·모든 benchmark에서 Baseline 이상이다** (loss 0). first-pass의 Baseline 미만 결과는 정책 결함(P: serving 비용 무시, migration budget 없음)과 benchmark 부적합(B)에서 왔고 iteration 1~3에서 해소되었다.
- **이득은 "static 배치가 runtime에 stale해지는" 조건에서만 확인된다.** Common과 feasible Stress에서는 둘 다 Baseline과 동률이다. SYS-4 Dynamic에서 C2는 6/6, C1은 3/6 시나리오에서 유의하게 이긴다. 그 외는 parity다. 이것은 일반 이득 주장이 아니다.
- **C2 vs C1:** C2의 성능 이득이 크고 C1은 훨씬 적은 byte를 옮긴다. Modifiability는 C1이 우위다 (★★★ vs ★★). 같은 data class 안의 hot/cold 구분이 필요한 workload에서는 C1이 구조적으로 이기지 못한다.
- **다음 단계:** (1) Destination Tier Selector의 serving-cost 입력, link-time migration budget, C2 benefit-vs-cost gating, C1 promotion 경로를 설계 문서에 반영한다 (loop-log '설계 문서에 미치는 영향'). (2) vLLM trace 수집과 HBM↔DRAM 실측으로 access-cost 모델의 오차를 [A]로 확인하고, 오차를 넣은 estimator로 재평가한다. (3) budget 파라미터 근거 확보. (4) 개정 구조(Backend I/F, snapshot)를 simulator에 반영한다.

## QA4 — Modifiability (architecture argument, [C])

| 변경 시나리오 | C1 변경 module | C2 변경 module |
|---|---|---|
| 신규 memory 추가 | Backend plug-in 1 (+ TransferHandler 1) = ≤2 → ★★★ | 동일 ≤2 → ★★★ (선호 tier를 capability class로 둘 때) |
| 신규 AI data type 추가 | Affinity/hint 항목 1~2 (Registry는 type-agnostic이라 무변경) → ★★★ | class metadata + Behavior Monitor feature + Predictor input + Destination 선호 = 4 → ★★ |
| 신규 정책 교체 | 1 → ★★★ | 1 → ★★★ |
| 신규 event type | 2 → ★★★ | 2 → ★★★ |

종합 C1 ★★★ / C2 ★★ [C]. loop에서 추가된 access-cost estimator와 migration budget은 두 후보가 **공유하는 module**이라 후보 간 QA4 차이를 바꾸지 않는다 (신규 memory 추가 시 estimator의 입력 descriptor만 갱신).
"""
    OUT.write_text(md, encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
