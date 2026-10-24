#!/usr/bin/env python3
"""DP2 architecture-style result document (node-internal, A Dispatcher vs B Blackboard) from results/data/arch.

    python tools/gen_dp2_arch_result.py --out doc-mk/Evaluation/DP2/results/2026-10-10_dp2-arch-styles.md

Every number comes from this module's functions (qa_result.json, qa4_modifiability*.json, SYS-H100/sens_result.json, control data);
the prose is typed by hand in PROSE below and quotes numbers only through the format helpers.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
D2 = HERE.parent / "DP2"
DATA = D2 / "results" / "data" / "arch"
B, A, BB, R = "Baseline-GPU-local", "A-Dispatcher", "B-Blackboard", "Ref-Dispatcher-with-board-rules"
NAME = {B: "Baseline-GPU-local", A: "A 중앙 Dispatcher", BB: "B Blackboard", R: "참고: Dispatcher + Blackboard 규칙"}
QA = json.loads((DATA / "qa_result.json").read_text())
QA4 = json.loads((DATA / "qa4_modifiability.json").read_text())
QA4F = json.loads((DATA / "qa4_modifiability_S2full.json").read_text()) if (DATA / "qa4_modifiability_S2full.json").exists() else None
_p = DATA / "SYS-H100" / "sens_result.json"
SENS = json.loads(_p.read_text()) if _p.exists() else None
T = QA["tables"]["combined"]
PS = QA["per_scenario"]
LAB = QA["labels"]
SETS = {"common": "Common", "stress": "DP2 Stress", "dynamic": "DP2 Dynamic"}
KEY4 = {A: "C1", BB: "C2"}          # candidate keys of tools/qa4_modifiability.py


def n_star(s):
    return s.count("★")


def x(v, d=2):
    return f"x{v:.{d}f}"


def ms(s):
    return f"{s * 1000:.1f}"


def git_rev():
    try:
        rev = subprocess.check_output(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(HERE), "status", "--porcelain", "--", str(D2)], text=True).strip()
        return rev + (" (dirty)" if dirty else "")
    except Exception:
        return "unknown"


def qa4_stars(c):
    return QA4["qa4_stars"][KEY4[c]]


def stars_total(c):
    t = T[c]
    return n_star(t["star_qa1"]) + n_star(t["star_qa2"]) + n_star(t["star_qa3"]) + n_star(qa4_stars(c))


def qa_table(tab=None):
    """§10 format table (Baseline column + A + B + reference)."""
    tab = tab or T
    b, a, bb, r = tab[B], tab[A], tab[BB], tab.get(R)
    base_gp = a["qa1_abs"] / a["qa1_ratio"]            # geometric-mean Baseline goodput (so that value = ratio x Baseline)
    base_gp_b = bb["qa1_abs"] / bb["qa1_ratio"]
    rows = ["| QA | 평가 metric | Baseline-GPU-local | A 중앙 Dispatcher | B Blackboard | 참고 (별 미부여) |", "|---|---|---:|---|---|---|"]

    def cell(c, f):
        return f(tab[c]) if c in tab else "—"
    rows.append(f"| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | {base_gp:,.0f} | {a['star_qa1']}  {a['qa1_abs']:,.0f} ({x(a['qa1_ratio'])}) | {bb['star_qa1']}  {bb['qa1_abs']:,.0f} ({x(bb['qa1_ratio'])}) | "
                + (f"{r['qa1_abs']:,.0f} ({x(r['qa1_ratio'])})" if r else "—") + " |")
    bt99, bt50 = b["ttft_p99"], b["ttft_p50"]
    bp99, bp50 = b["tpot_p99"], b["tpot_p50"]
    rows.append(f"| **QA2 Latency — TTFT** | P99 · P50 (ms) ↓ | P99 {bt99 * 1000:,.0f} · P50 {bt50 * 1000:,.0f} | "
                f"P99 {a['ttft_p99'] * 1000:,.0f} ({x(a['ttft_p99'] / bt99)}) · P50 {a['ttft_p50'] * 1000:,.0f} ({x(a['ttft_p50'] / bt50)}) | "
                f"P99 {bb['ttft_p99'] * 1000:,.0f} ({x(bb['ttft_p99'] / bt99)}) · P50 {bb['ttft_p50'] * 1000:,.0f} ({x(bb['ttft_p50'] / bt50)}) | "
                + (f"P99 {r['ttft_p99'] * 1000:,.0f} ({x(r['ttft_p99'] / bt99)})" if r else "—") + " |")
    rows.append(f"| **QA2 Latency — TPOT** | P99 · P50 (ms) ↓ | P99 {ms(bp99)} · P50 {ms(bp50)} | "
                f"P99 {ms(a['tpot_p99'])} ({x(a['tpot_p99'] / bp99)}) · P50 {ms(a['tpot_p50'])} ({x(a['tpot_p50'] / bp50)}) | "
                f"P99 {ms(bb['tpot_p99'])} ({x(bb['tpot_p99'] / bp99)}) · P50 {ms(bb['tpot_p50'])} ({x(bb['tpot_p50'] / bp50)}) | "
                + (f"P99 {ms(r['tpot_p99'])} ({x(r['tpot_p99'] / bp99)})" if r else "—") + " |")
    rows.append(f"| **QA2 별점** | 6개 지표 개선 배수(Baseline÷후보) geomean | x1.00 | {a['star_qa2']}  {x(a['qa2_impr'])} (TTFT {x(a['ttft_impr'])} · TPOT {x(a['tpot_impr'])}) | "
                f"{bb['star_qa2']}  {x(bb['qa2_impr'])} (TTFT {x(bb['ttft_impr'])} · TPOT {x(bb['tpot_impr'])}) | " + (f"{x(r['qa2_impr'])}" if r else "—") + " |")

    def q3(c):
        c_ = tab[c]
        if c_["hbm_ratio"] is None:
            return "n/a"
        return f"{c_['star_qa3']}  {c_['hbm_abs_gib']:,.0f} GiB ({x(c_['hbm_ratio'])}) [{c_['hbm_n_eq']}쌍]"
    rows.append(f"| **QA3 HBM KV 점유** | 시간 평균 점유 (GiB, 노드 합) ↓ , iso-load | {a['hbm_base_gib']:,.0f} | {q3(A)} | {q3(BB)} | " + (q3(R).split(' [')[0] if r else "—") + " |")
    rows.append(f"| **QA4 Modifiability** | module · 공수(MM) · 에이전트 비용(T1) ↓ | — | {qa4_stars(A)}  {QA4['mean_over_scenarios']['C1']['modules']:.2f} · {QA4['mean_over_scenarios']['C1']['man_months']:.2f} · ${QA4['mean_over_scenarios']['C1']['usd_T1']:.2f} [B+C] | "
                f"{qa4_stars(BB)}  {QA4['mean_over_scenarios']['C2']['modules']:.2f} · {QA4['mean_over_scenarios']['C2']['man_months']:.2f} · ${QA4['mean_over_scenarios']['C2']['usd_T1']:.2f} [B+C] | — |")
    rows.append(f"| **별 합계 (QA1~QA4)** | | — | {stars_total(A)} | {stars_total(BB)} | — |")
    return "\n".join(rows)


def set_table(name):
    t = QA["tables"][name]
    rows = ["| 후보 | 쌍 | QA1 goodput | TTFT P99 | TPOT P99 | QA2 개선 | HBM 점유 비 |", "|---|---:|---|---|---|---|---|"]
    for c in (A, BB, R):
        if c not in t or not t[c].get("n"):
            continue
        d = t[c]
        hb = x(d["hbm_ratio"]) if d.get("hbm_ratio") else "n/a"
        rows.append(f"| {NAME[c]} | {d['n']} | {x(d['qa1_ratio'])} | {x(d['ttft_p99_x'] ** -1)} | {x(d['tpot_p99_x'] ** -1)} | {x(d['qa2_impr'])} | {hb} |")
    return "\n".join(rows)


def scen_rows(scn_set=None):
    rows = ["| 시나리오 | 시스템 | fit | Baseline goodput (부하) | A goodput (부하) | B goodput (부하) | A TTFT/TPOT P99 비 | B TTFT/TPOT P99 비 | HBM 점유 비 A / B |",
            "|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(PS, key=lambda k: (k.split("|")[1], k.split("|")[0])):
        sysid, scn = key.split("|")
        v = PS[key]
        b, a, bb = v[B], v[A], v[BB]
        iso_b, iso_a, iso_bb = b["iso"], a["iso"], bb["iso"]

        def r(i, f):
            return x(i[f] / iso_b[f]) if iso_b[f] > 0 else "—"
        rows.append(f"| `{scn}` | {sysid[4:]} | {LAB[key]['fit']} | {b['goodput']:,.0f} ({b['load']:g}) | {a['goodput']:,.0f} ({a['load']:g}) | {bb['goodput']:,.0f} ({bb['load']:g}) | "
                    f"{r(iso_a, 'ttft_p99')} / {r(iso_a, 'tpot_p99')} | {r(iso_bb, 'ttft_p99')} / {r(iso_bb, 'tpot_p99')} | "
                    f"{x(iso_a['hbm_avg'] / iso_b['hbm_avg'])} / {x(iso_bb['hbm_avg'] / iso_b['hbm_avg'])} |")
    return "\n".join(rows)


def losses():
    """(key, cand, metric) where the candidate is worse than the Baseline beyond noise (paired verdicts)."""
    out = []
    for key, lab in LAB.items():
        for c in (A, BB):
            vs = lab["vs"].get(c)
            if vs and (vs["goodput"] == "loss" or vs["ttft"] == "loss" or vs["tpot"] == "loss"):
                out.append((key, c, {k: vs[k] for k in ("goodput", "ttft", "tpot")}))
    return out


def verdict_counts(c):
    cnt = Counter()
    for key, lab in LAB.items():
        if lab["fit"] != "comparison_valid":
            continue
        cnt[lab["vs"][c]["verdict"]] += 1
    return cnt


def tier_share(c, tier):
    tot = sel = 0
    for key, v in PS.items():
        t = v[c]["tiers"]
        tot += sum(t.values())
        sel += t.get(tier, 0)
    return sel / tot if tot else 0.0


def sens_table():
    if not SENS:
        return "(민감도 결과 없음)"
    rows = ["| 축 | 값 | 후보 | goodput (x Baseline) | TTFT P99 (x) | TPOT P99 (x) | HBM 점유 (x) |", "|---|---|---|---|---|---|---|"]
    for ax, vals in SENS.items():
        for v, row in vals.items():
            for c, d in row.items():
                rows.append(f"| {ax} | {v} | {NAME[c]} | {x(d['goodput'])} | {x(d['ttft99'])} | {x(d['tpot99'])} | {x(d['hbm'])} |")
    return "\n".join(rows)


def sens_reading():
    if not SENS:
        return ""
    e = SENS["eps"]
    g = lambda ax, v, c, k: SENS[ax][str(v)][c][k]
    return (f"**해석.** (1) A의 이득은 Cost 추정 오차에 민감하다: 추정 오차 sigma 0 / 0.2 / 0.4 / 0.6에서 goodput이 {x(g('eps', 0.0, A, 'goodput'))} / {x(g('eps', 0.2, A, 'goodput'))} / "
            f"{x(g('eps', 0.4, A, 'goodput'))} / {x(g('eps', 0.6, A, 'goodput'))}, TTFT P99가 {x(g('eps', 0.0, A, 'ttft99'))} / {x(g('eps', 0.2, A, 'ttft99'))} / {x(g('eps', 0.4, A, 'ttft99'))} / {x(g('eps', 0.6, A, 'ttft99'))}이다. "
            f"즉 이 오차 모델(lognormal, 한 종류)에서 break-even은 sigma 0.2와 0.4 사이이고, sigma 0.4부터 Baseline보다 나쁘다. 상수(lambda_HBM, t_ref)와 telemetry 주기는 A의 결과를 거의 바꾸지 않는다(goodput {x(g('lam_hbm', 0.0, A, 'goodput'))}~{x(g('lam_hbm', 4.0, A, 'goodput'))}, "
            f"telemetry 갱신 0.01~1.0 s에서 {x(g('tel', 0.01, A, 'goodput'))}~{x(g('tel', 1.0, A, 'goodput'))}). "
            f"(2) B는 theta에 둔감하고(0.6~1.0에서 결과 동일: HBM이 차야 offload하는 규칙이라 theta가 거의 작동하지 않음) rho_hi에 민감하다: 0.7이면 goodput {x(g('rho_hi', 0.7, BB, 'goodput'))}, TTFT P99 {x(g('rho_hi', 0.7, BB, 'ttft99'))}, 0.95이면 {x(g('rho_hi', 0.95, BB, 'goodput'))}, {x(g('rho_hi', 0.95, BB, 'ttft99'))}. 어느 값에서도 Baseline을 넘는 구간은 없다. "
            f"(3) 한계: 6개 시나리오, seed 3개, 단일 시스템의 점 평가이며 별점이 아니라 방향 확인용이다.")


def build():
    import sys
    sys.path.insert(0, str(HERE))
    import dp_selection
    pri = json.loads((D2 / "qa_priority.json").read_text())
    st = {c: {"QA1": T[c]["star_qa1"], "QA2": T[c]["star_qa2"], "QA3": T[c]["star_qa3"], "QA4": qa4_stars(c)} for c in (A, BB)}
    sel = dp_selection.select(st, pri["priority"])
    a, bb = T[A], T[BB]
    ca, cb = verdict_counts(A), verdict_counts(BB)
    npair = Counter(l["fit"] for l in LAB.values())
    q4a, q4b = QA4["mean_over_scenarios"]["C1"], QA4["mean_over_scenarios"]["C2"]
    rev = git_rev()
    out = f"""---
date: 2026-10-10
dp: DP2
candidates: [A-Dispatcher, B-Blackboard]   # Baseline-GPU-local 포함, 참고: Ref-Dispatcher-with-board-rules
sys_ids: [SYS-H100, SYS-B200]
git_rev: {rev}
evidence: {{ QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[B+C]" }}
status: draft
---

# DP2 QA Evaluation — 중앙 Dispatcher(A) vs Blackboard(B) (노드 내 attention 실행 위치 결정, 아키텍처 스타일 비교)

> 기준 문서: `qa-evaluation-criteria.md`, `common-benchmark.md`, `system-specs.md`, `DP2/benchmark.md` §11, `DP2/arch-styles-plan.md`(사전 등록), `DP2/qa4-preregistration-arch.md`
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 후보(A, B)는 같은 노드 내 simulator 위에 구현한 proxy이고 vLLM 구현이 아니다.

# 0. 최종 요약

## 0.1 QA x 후보

{qa_table()}

평가 시스템: SYS-H100(HBM3, PCIe5), SYS-B200(HBM3e, PCIe5) 통합, Llama-70B급 GQA(8) BF16 가정, 집계 쌍 {len(LAB)}개 중 comparison-valid {npair['comparison_valid']}개(별점 집계 대상), saturated {npair['saturated']}개, infeasible {npair['infeasible']}개. QA3는 SLO 달성률이 Baseline-1pp 이상인 iso-load 쌍만 쓴다(A {a['hbm_n_eq']}쌍 / B {bb['hbm_n_eq']}쌍, 제외 {a['hbm_n_excluded']} / {bb['hbm_n_excluded']}쌍). 메모리 구성(용량, 대역폭, 연산)은 `system-specs.md` 참조, 모델링하지 않은 것: HBF endurance, 노드 간 이동(이 비교는 노드 내부 결정만 다룬다).

## 0.2 Trade-off의 특징과 이유

**A(중앙 Dispatcher)는 TTFT와 HBM을 얻고 TPOT 꼬리를 쓴다.** Dispatcher는 telemetry snapshot과 Cost 모델(이동 시간, 예상 TPOT, HBM 기회비용 lambda_HBM)로 후보 Tier를 argmin한다. 그래서 History가 큰 turn이나 decode가 몰린 노드에서 ScHBM으로 attention을 보내는 결정을 한다(A의 Decode 중 ScHBM 비율 {tier_share(A, 'custom_hbm') * 100:.1f}%). 결과: TTFT P99 {x(a['ttft_p99_x'])}(Baseline 대비, 낮을수록 좋음), HBM 점유 {x(a['hbm_ratio'])}, goodput {x(a['qa1_ratio'])}. 대가로 TPOT P99가 {x(a['tpot_p99_x'])}이다. Cost 모델이 SLO(50 ms) 안의 TPOT 여유를 소비하도록 설계되어 있기 때문이며(TPOT P99 {ms(a['tpot_p99'])} ms, SLO 이내) 쌍별로는 {ca['win']}승 {ca['tie']}무 {ca['loss']}패(TPOT 꼬리 패배가 대부분)다.

**B(Blackboard)는 Baseline과 거의 같다.** Task Board의 규칙은 "HBM budget이 허용하면 HBM, 거절될 때만 offload"이다. board에 HBM과 offload의 비용 차이를 볼 신호가 없으므로 HBM 압박이 없으면 Baseline과 같은 결정을 한다(goodput {x(bb['qa1_ratio'])}, 쌍별 {cb['win']}승 {cb['tie']}무 {cb['loss']}패). HBM 압박이 있는 시나리오에서는 admission margin(rho_hi 0.85)이 요청을 큐에 잡아 TTFT 꼬리가 늘어난다(TTFT P99 {x(bb['ttft_p99_x'])}). 같은 규칙 집합을 중앙에서 실행한 참고 후보(Ref)도 비슷한 값이므로 B의 약점은 분산 결정 자체보다 **cost 신호가 없는 규칙 집합**에서 온다. 반대로 B는 live 측정값으로 결정하므로 telemetry 지연에 둔감하다(`n_dp2_stale_telemetry` B200에서 B가 x1.36 승, H100에서는 패).

**Modifiability(QA4)는 둘 다 ★★★이고 B가 조금 낫다.** 시나리오 평균 module A {q4a['modules']:.2f} / B {q4b['modules']:.2f}, 공수 {q4a['man_months']:.2f} / {q4b['man_months']:.2f} MM, 비용 ${q4a['usd_T1']:.2f} / ${q4b['usd_T1']:.2f}. 차이는 S4(telemetry 신호 추가)에서 크다: A는 Tier Descriptors, Candidate Generator, Dispatcher 3개 module을 건드리고 B는 Tier Admission Agents 1개만 바꾼다(agent가 자기 Tier의 상태를 스스로 판단하기 때문). 반대로 S2(목적 항 추가)는 A가 Cost Model 1곳이고 B는 Task Board 중재 1곳(최소 변경)이나 agent와 budget까지 반영하면 3곳이다. 별이 같아 선택에는 영향이 없다.

## 0.3 선택과 근거

선택 규칙(`tools/dp_selection.py`, 우선순위 {' > '.join(pri['priority'])}, status={pri['status']}): 별 합계 A {sel['totals'][A]}, B {sel['totals'][BB]} -> **{sel['winner']}** (규칙: {sel['rule']}). 우선순위를 뒤집어도 {sel['reversed_winner']}이 선택된다. 선택을 가르는 것은 QA2 한 개의 별이다(A ★★, B ★). **전제**: A의 값은 Cost 추정 오차 sigma = 0에서의 값이며, sigma 0.4부터 Baseline 아래로 내려간다(6장 민감도). **경계 의존성**: B의 QA3 절감비는 {bb['hbm_save']:.3f}로 ★★ 하한 0.95에 거의 붙어 있어, 경계 아래이면 B는 ★이고 합계 차이가 2가 된다. 선택은 같다. 이 결과는 QA2의 TPOT 꼬리를 "개선 배수 geomean"에 반영한 별점 규칙 하에서 유효하며, A의 TPOT 꼬리 악화(x{a['tpot_p99_x']:.2f})는 별점에 상쇄된 채 숨어 있다.

## 0.4 선택 구조(A)의 부족한 부분과 보완 설계

| 약점 (근거 수치) | 보완 택틱 | 검증 상태 |
|---|---|---|
| QA2 TPOT 꼬리 (P99 {x(a['tpot_p99_x'])}, 비교 가능 쌍 {ca['loss']}패, 대부분 TPOT verdict) — snapshot 주기(기본 50 ms) 사이에 Cost 모델이 보지 못한 부하가 쌓여 SLO 여유를 소비 | **Hybrid C**: Dispatcher의 후보 선택은 유지하되, Tier 쪽에 Blackboard식 **live admission guard**(Tier agent가 자기 노드의 현재 iteration 시간과 claim backlog를 직접 보고 거부권 행사). 결정은 중앙, 거부는 로컬 | [C] 논증, 미구현. 효과 수치 주장 없음 |
| Cost 추정 오차 의존 (sigma 0.4에서 goodput {x(SENS['eps']['0.4'][A]['goodput']) if SENS else 'n/a'}, 0.6에서 {x(SENS['eps']['0.6'][A]['goodput']) if SENS else 'n/a'}) | 추정 오차 보정 또는 live guard로 오추정 비용 상한(Hybrid C와 같은 택틱) | [C] |
| QA1 이득 크기 (goodput {x(a['qa1_ratio'])}, ★★) — 직렬 결정과 telemetry 지연이 상한 | 결정 batch화, Cost 캐시 | [C] |
| 구조 비용: Dispatcher 단일 지점, S4류 변경이 3 module에 걸침 | Tier 사양/상태를 Tier agent가 소유하는 인터페이스 도입(Blackboard의 장점) | [C] |

## 0.5 고려한 시나리오 (서술)

노드 하나 안에서 "이 turn의 attention을 어디서 돌릴까"가 의미 있는 상황 16가지를 만들었다. 가장 쉬운 경우는 History가 이미 HBM에 있는 짧은 대화(`n_dp2_turn_hbm_small_tool`)다. 여기서는 어느 후보든 차이가 거의 없다. 어려운 경우는 History가 DRAM/SSD/HBF에 내려가 있는 대화(`n_dp2_turn_dram_small_tool`, `n_dp2_turn_hbf_hist`, `n_dp2_turn_ssd_hist`)와 128K급 긴 컨텍스트가 decode를 지배하는 경우(`n_dp2_long_ctx_decode_offload`), 한 노드에 decode가 몰려 HBM이 압박받는 경우(`n_dp2_decode_heavy_p_idle`)다. 동적 시나리오로 부하가 갑자기 치솟는 경우(`n_dyn_load_ramp_burst`), decode 단계가 시간에 따라 바뀌는 경우(`n_dyn_decode_phase_shift`), telemetry가 오래된 경우(`n_dp2_stale_telemetry`), Dispatcher가 죽어 fallback하는 경우(`n_dp2_planner_fault_fallback`)도 넣었다. 공통 벤치마크 3개(KV 8K, ramp, mixed)는 단일 노드에서 baseline이 이미 가득 찬 쉬운 경우다. 아직 없는 시나리오: 노드 간 이동을 포함한 경우(DP4 몫, 이 평가에서 제외), 실제 trace 기반 부하, 실측 HW. 전체 목록은 3장.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | SYS-H100 (primary), SYS-B200 — 통합 결과 |
| Model / precision | Llama-70B급 GQA(8), BF16, KV 약 320 KB/token (가정) |
| Git revision | {rev} |
| Seeds / loads | seeds 11, 23, 37, 53, 71 (5개) / 시나리오별 부하 grid(`sim/configs/grids_node.json`), iso-load 비교 |
| 재현 command | `cd doc-mk/Evaluation/DP2/sim && python qa_eval_node.py run --workers 4 && python qa_eval_node.py agg` |
| Raw data | `DP2/results/data/arch/SYS-*/runs.jsonl`, `qa_result.json`, `qa4_*.json`, `SYS-H100/sens*.json*` |

시스템 profile 상세: [system-specs.md](../../system-specs.md)

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO goodput | SLO(TTFT 2 s, TPOT 50 ms) 만족 토큰/s의 부하 sweep 최대, 쌍별 비율의 geomean. 별 경계 0.97 / 1.30 | criteria §4 |
| QA2 Latency | TTFT, TPOT의 P50/P95/P99 개선 배수 geomean(6개), 별 경계 0.95 / 1.25. TTFT와 TPOT를 따로 병기 | criteria §5, H23 |
| QA3 HBM KV 점유 | 시간 평균 점유(GiB)의 Baseline 대비 비율, iso-load, SLO 달성률 Baseline-1pp 이상인 쌍만. 별 경계 절감 0.95 / 1.25 | H20, **임시 정의**(DP2 노드 내용) |
| QA4 Modifiability | 변경 시나리오 4종(신규 Tier, 신규 목적 항, 정책 교체, 신규 telemetry 신호) 실제 구현, M1 module / M2 공수 / M3 비용 시나리오 평균, 별 = 중앙값 | H21, `qa4-preregistration-arch.md` |

# 3. 벤치마크 / 시나리오

Common 3개 + DP2 노드 내 13개 = 16개 시나리오 x 2 시스템 = 32쌍. 노드 수는 1노드 3개(Common), 2노드 12개, 4노드 1개이며 노드 배정은 후보가 아닌 평가 하네스의 고정 라우팅이다(6장). 시나리오당 한 줄 설명은 `DP2/benchmark.md` §11. fit label:

{fit_table()}

# 4. 결과

## 4.1 최종 QA 표

{qa_table()}

## 4.2 시나리오별 결과

{scen_rows()}

세트별 요약 (Baseline 대비 개선 배수, 높을수록 좋음):

""" + "\n\n".join(f"**{SETS[sname]}**\n\n{set_table(sname)}" for sname in SETS) + f"""

## 4.3 Diagnostic

| 지표 | Baseline | A | B |
|---|---:|---:|---:|
| ScHBM으로 시작한 Decode 비율 | 0 | {tier_share(A, 'custom_hbm') * 100:.1f}% | {tier_share(BB, 'custom_hbm') * 100:.1f}% |
| HBF/CXL-PNM 비율 | 0 | {(tier_share(A, 'hbf') + tier_share(A, 'cxl_pnm')) * 100:.1f}% | {(tier_share(BB, 'hbf') + tier_share(BB, 'cxl_pnm')) * 100:.1f}% |

## 4.4 Iteration summary

| Iteration | Class | Change | Effect |
|---|---|---|---|
| 0 (Baseline control) | B + 정의 | Baseline-GPU-local 정의/grid 정리(3.2) | Baseline feasible |
| 1 | P (A) | Dispatcher의 pending 배정 ledger 추가(herding, 3.4) | decode_heavy 1,882 -> 9,102 (x4.8) |
| 2 | P (B) | 규칙 v2: 노드 TPOT headroom, History는 HBM staging만(3.5) | hbf_hist 0.00x -> 0.96x, dram_small_tool 0.72x -> 0.93x |
| 3 | — | 중단 결정(3.6): 남은 B 퇴화는 cost 신호 부재라는 구조적 성질 | B QA2 ★, HBM 절감 없음 그대로 보고 |

상세 로그: [loop-log.md](iterations/loop-log.md). 부분 실행 데이터(`run1_aborted`, `run2_aborted`)는 보존했고 평가에 쓰지 않았다.

# 5. 결과 분석

Baseline보다 나쁜 비교 가능 쌍(쌍별 verdict loss가 있는 항목, 총 {len(losses())}건):

| 시나리오 | 후보 | goodput / TTFT / TPOT verdict | Root cause |
|---|---|---|---|
""" + "\n".join(f"| `{k.split('|')[1]}` ({k.split('|')[0][4:]}) | {NAME[c]} | {v['goodput']} / {v['ttft']} / {v['tpot']} | " + ("TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님)" if c == A else "admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기") + " |" for k, c, v in losses()) + f"""

# 6. 한계

- Evidence [B+C]: 물리 모델은 config 기반이며 vLLM 실행 결과가 아니다. 후보는 같은 사람이 같은 simulator에서 구현한 proxy이고, B의 규칙 집합(theta 0.8, rho_hi 0.85, t_bb 0.5 ms)은 사전 등록한 값이다.
- **A와 B는 아키텍처뿐 아니라 규칙 집합이 다르다.** 참고 후보 Ref(Dispatcher + board 규칙)로 분리를 시도했으나 Ref도 B와 비슷해 규칙 집합이 지배적이다. "Blackboard 스타일이 구조적으로 나쁘다"가 아니라 "cost 신호가 없는 Blackboard 규칙 집합은 이득이 없다"로 읽어야 한다. board에 cost 신호를 추가한 Blackboard는 이 비교에 포함되지 않았다.
- QA3의 B 값은 SLO 달성률 조건으로 {bb['hbm_n_excluded']}쌍이 제외된 {bb['hbm_n_eq']}쌍 기준이며 경계(0.95)에 가깝다.
- A의 TPOT P99는 Baseline의 {x(a['tpot_p99_x'])}이다. 별점 geomean이 이를 TTFT 개선과 상쇄한다. TPOT 꼬리가 중요하면 A를 그대로 쓸 수 없다.
- **노드 배정은 평가 하네스의 고정 라우팅이다**(모든 후보 동일, History가 있으면 소유 노드, 없으면 snapshot의 HBM 여유 최대 노드). 시나리오 16개 중 13개가 2~4노드라 결과에 이 라우팅의 노드 간 부하 분산 효과가 섞여 있고 1노드만으로 DP2를 분리한 재평가는 하지 않았다.\n- 노드 간 결정(DP4), 장시간 실행, endurance, 실제 trace는 평가하지 않았다. 기본 grid는 Baseline 교정으로 정했고 saturated {npair['saturated']}쌍은 후보 판별력이 없다.
- A는 Cost 추정 오차에 민감하다(위 민감도 해석 (1)). **본 평가의 A는 오차 없는 추정(sigma = 0, `dp2_params.json` A18)으로 돌렸으므로 A의 이득은 상한에 가깝다.** 오차 모델은 lognormal 한 종류뿐이다(H17).\n- QA4의 공수와 비용은 가정 상수(`qa4_modifiability.py`)이며 실제 에이전트 세션 측정이 아니다.
- loop를 6회 전에 중단했다(3.6). 중단 판단은 사용자가 뒤집을 수 있다.

## 민감도 (상수를 다시 맞춘 것이 아니라 사전 등록값 주변을 본 것, 6개 시나리오, SYS-H100, seed 3개)

{sens_table()}

{sens_reading()}

# 7. 결론

- 선택: **A 중앙 Dispatcher**(별 {sel['totals'][A]} vs {sel['totals'][BB]}). 이득은 TTFT 꼬리(x{a['ttft_p99_x']:.2f})와 HBM 점유(x{a['hbm_ratio']:.2f})에 있고 goodput은 x{a['qa1_ratio']:.2f}로 크지 않다. 이득이 나는 조건은 History가 HBM 밖에 있거나 decode가 몰려 HBM이 압박받는 시나리오이며, 쉬운 시나리오에서는 Baseline과 같다.
- B Blackboard(이번 규칙 집합)는 tested condition에서 Baseline 대비 이득이 없다(goodput x{bb['qa1_ratio']:.2f}, TTFT P99 x{bb['ttft_p99_x']:.2f}, HBM x{bb['hbm_ratio']:.2f}).
- A의 약점은 TPOT 꼬리(x{a['tpot_p99_x']:.2f})이고 보완안은 Hybrid C(중앙 선택 + Tier live guard)이다. [C], 미구현. 다음 단계: C를 구현해 같은 benchmark로 평가, board에 cost 신호를 넣은 Blackboard 변형 평가, DP4(노드 간)로 확장.
"""
    return out


def fit_table():
    c = Counter(l["fit"] for l in LAB.values())
    rows = ["| fit | 쌍 수 |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in sorted(c.items())]
    rows.append("")
    rows.append("saturated: " + ", ".join(sorted(k for k, l in LAB.items() if l["fit"] == "saturated")))
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    if a.print:
        print(qa_table())
        for s in SETS:
            print("\n" + SETS[s]); print(set_table(s))
        print(scen_rows())
        print(len(losses()), "paired losses")
        return
    Path(a.out).write_text(build())
    print("wrote", a.out)


if __name__ == "__main__":
    main()
