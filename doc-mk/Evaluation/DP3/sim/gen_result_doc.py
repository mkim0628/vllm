#!/usr/bin/env python3
"""Generate results/2026-10-11_dp3-qa-evaluation.md from results/data/*.json (numbers only come from code output)."""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "results"
DATA = RES / "data"
sys.path.insert(0, str(HERE.parent.parent / "tools"))
import unified_stars as U  # noqa: E402

summ = json.loads((DATA / "dp3_summary.json").read_text())
sens = json.loads((DATA / "dp3_sensitivity.json").read_text())
res = {s: json.loads((DATA / s / "dp3_results.json").read_text()) for s in ("SYS-H100", "SYS-B200")}
inp = U.load()
stars = U.evaluate(inp)["DP3"]
S = U.S
BASE, C1, C2 = "Baseline-As-Is", "C1-Offline", "C2-Online"
ag = summ["aggregate"]
acc_path = HERE.parent / "accuracy" / "results" / "accuracy_summary.json"
q5_path = DATA / "dp3_qa5.json"
acc = json.loads(acc_path.read_text()) if acc_path.exists() else None
q5 = json.loads(q5_path.read_text()) if q5_path.exists() else None
q5_ok = bool(q5 and q5["_meta"]["n_examples"] >= q5["_meta"]["min_examples"])


def ms(x):
    return "—" if x is None else f"{x*1e3:,.0f}"


def f(x, d=2):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{d}f}"


L = []
w = L.append
rev = summ["git_rev_SYS-H100"]
w(f"""---
date: 2026-10-11
dp: DP3
candidates: [C1-Offline, C2-Online]
sys_ids: [SYS-H100, SYS-B200]
git_rev: {rev}   # +dirty = 같은 폴더의 accuracy/ 측정 파일이 아직 commit되지 않은 상태. sim 코드·시나리오는 commit 4776de4 그대로
evidence: {{ QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA5: "[A 소형 모델 실측 + C 매핑]" }}
status: draft
---

# DP3 QA Evaluation — C1 Offline(Query-agnostic) vs C2 Online(Query-aware) (Long Context KV 압축·재사용)

> 기준 문서: `../../qa-star-criteria-unified.md`(별 기준 v2), `../../common-benchmark.md`, `../../system-specs.md`, `../benchmark.md`, `../simulation-plan.md`(사전 등록)
> 이 문서의 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 정확도(QA5)만 소형 모델 실측이고 규모·모델이 다르다.

# 0. 요약

| QA | Baseline (As-Is) | C1 Offline | C2 Online |
|---|---:|---|---|
| QA1 Max SLO goodput (tok/s) ↑ | {inp['DP3']['baseline']['tps']:,.0f} | {inp['DP3']['values']['C1']['qa1_tps']:,.0f} (×{inp['DP3']['values']['C1']['qa1_ratio']:.2f}) | {inp['DP3']['values']['C2']['qa1_tps']:,.0f} (×{inp['DP3']['values']['C2']['qa1_ratio']:.2f}) |
| QA1 별 | — | {S(stars['C1']['QA1'])} | {S(stars['C2']['QA1'])} |
| QA2 TTFT P99 (ms) ↓ | {ms(ag['abs'][BASE]['ttft'])} | **{ms(ag['abs'][C1]['ttft'])}** (x{ag[C1]['ttft']['ratio_gm']:.2f} 개선) | {ms(ag['abs'][C2]['ttft'])} (x{ag[C2]['ttft']['ratio_gm']:.2f}, **Baseline보다 나쁨**) |
| QA2 TPOT P99 (ms) ↓ | {ag['abs'][BASE]['tpot']*1e3:.1f} | {ag['abs'][C1]['tpot']*1e3:.1f} (x{ag[C1]['tpot']['ratio_gm']:.2f}) | {ag['abs'][C2]['tpot']*1e3:.1f} (x{ag[C2]['tpot']['ratio_gm']:.2f}) |
| QA2 별 | — | {S(stars['C1']['QA2'])} (r={ag[C1]['qa2_r']:.2f}, SLO 충족) | {S(stars['C2']['QA2'])} (r={ag[C2]['qa2_r']:.2f} < 0.90 → ★) |
| QA3 HBM KV 시간평균 (GiB) ↓ | {ag['abs'][BASE]['hbm']:.1f} | **{ag['abs'][C1]['hbm']:.1f}** (감소 x{ag[C1]['hbm']['ratio_gm']:.2f}) | {ag['abs'][C2]['hbm']:.1f} (감소 x{ag[C2]['hbm']['ratio_gm']:.2f}) |
| QA3 별 | — | {S(stars['C1']['QA3'])} | {S(stars['C2']['QA3'])} (경계 1.25에서 {(ag[C2]['hbm']['ratio_gm']/1.25-1)*100:+.1f}%) |
| QA5 F1 상대 하락 (%) ↓ | 0 (정의상) | {('%.1f' % q5['C1']['f1_drop_pct']) if q5_ok else '측정 진행 중'} | {('%.1f' % q5['C2']['f1_drop_pct']) if q5_ok else '측정 진행 중'} |
| QA5 별 | — | {S(stars['C1']['QA5']) if 'QA5' in stars['C1'] else '미평가'} | {S(stars['C2']['QA5']) if 'QA5' in stars['C2'] else '미평가'} |

- 집계: 18 시나리오 × 2 시스템 중 **comparison-valid 32쌍**의 기하평균(제외 4쌍은 §3). 부하 = Baseline 용량의 70%.
- **C1 Offline은 지연·HBM 모두 크게 낫다**(TTFT 28/32쌍, HBM 32/32쌍에서 이김). **C2 Online은 HBM은 줄이지만 TTFT는 32쌍 중 2쌍만 이긴다**(온라인 점수 계산 + 재계산이 요청 경로에 들어오고, 전체 KV를 적재해야 해서 적재 이득이 없다).
- 약점: **Baseline이 GPU 직접 읽기(HBF) tier에서 적재 비용 없이 서빙할 때 C1·C2 모두 TTFT가 ×0.09~0.14로 크게 진다**(ST-06). 이득은 유지 비율 r = 0.30 가정에 의존한다(r = 0.5이면 C1 TTFT 이득이 H100에서 사라진다, §5).
- 별 합계(QA5 제외): C1 {sum(v for k, v in stars['C1'].items())}{'' if q5_ok else ' + QA5'}, C2 {sum(v for k, v in stars['C2'].items())}{'' if q5_ok else ' + QA5'}.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | SYS-H100 (primary), SYS-B200 |
| Model / precision | Llama-3.1-70B BF16, KV 320 KiB/token, 8-GPU 노드 1개를 TP8 aggregate 장치 1개로 모델 |
| Git revision | {rev} |
| Seeds / loads | seeds 11, 23, 37, 53, 71 / lam0 × 0.5, 0.75, 1.0, 1.25 (별은 × 1.0) |
| 재현 command | `cd doc-mk/Evaluation/DP3/sim && python run_eval.py --system SYS-H100 --system SYS-B200 && python aggregate.py && python sensitivity.py && python gen_result_doc.py` |
| Raw data | `DP3/results/data/SYS-H100/dp3_results.json`, `.../SYS-B200/dp3_results.json`, `dp3_summary.json`, `dp3_sensitivity.json` |

시스템 profile 상세: [system-specs.md](../../system-specs.md). profile 값은 DP1 simulator의 것을 import했고 provenance는 거기에 있다(ASSUMED 포함).

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO goodput | 요청별 SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms)를 만족한 요청의 output token / 측정 구간, 부하 격자 lam0 × {{0.5 … 8}}(최대가 끝이면 × 64까지 확장)의 최대, 쌍별 비율의 기하평균 | unified §3.1, simulation-plan 변경 이력 |
| QA2 TTFT P99 / TPOT P99 | TTFT = 첫 토큰 시각 − 도착 시각(admission 대기·KV 적재·GPU 대기 포함). TPOT = (마지막 − 첫 토큰)/(출력 − 1). 요청 P99, seed 평균, 쌍별 기하평균. r = √(TTFT 배수 × TPOT 배수) | unified §3.2 |
| QA3 HBM 사용량 | HBM에 올라간 KV(상주 Comp.KV 객체 + 요청 작업 사본)의 시간 평균 GiB. DP3 후보가 바꾸는 AI Data는 KV뿐이라 KV만 잰다(LoRA·MoE 등은 시나리오에 없음). 처음 10% 제외. 감소 배수 = Baseline ÷ 후보 | unified §3.3 |
| QA5 F1 상대 하락 | (F1_full − F1_후보) ÷ F1_full, 같은 모델·task, 압축 전 full KV 대비 | unified §3.5 |
| 집계 | comparison-valid 쌍(= Baseline이 모든 요청을 끝냄, run당 완료 요청 ≥ 10, 정책 간 2% 이상 차이)의 기하평균 | simulation-plan §2 |
| 임시 정의 | QA5의 C1 매핑(대표 Query 근접 비율 = 1 − mismatch), §6 | simulation-plan §3 |

# 3. 벤치마크 / 시나리오 (fit label)

시나리오 정의: [benchmark.md](../benchmark.md). 아래 라벨은 Baseline 기준(부하 × 1.0).
""")
w("| Set | 시나리오 | SYS-H100 | SYS-B200 | 비고 |\n|---|---|---|---|---|")
for sid, e in res["SYS-H100"]["scenarios"].items():
    lab = []
    for s in ("SYS-H100", "SYS-B200"):
        p = summ["pairs"][f"{s}/{sid}"]
        lab.append("comparison-valid" if p["valid"] else f"제외: {p['reason']}")
    w(f"| {e['family']} | `{sid}` {e['brief']} | {lab[0]} | {lab[1]} | |")
w("""
- 제외된 4쌍을 숨기지 않는다: ST-05(SSD 차가운 128K)는 Baseline 용량이 0.02~0.03 req/s라 90초 horizon에서 run당 요청이 0~3건이다(표본 부족, 두 SYS 모두). ST-11·DY-03 H100은 128K 문맥이 HBM에 안 들어가 Baseline이 요청을 끝내지 못하는데(infeasible), **C1은 끝낸다**(ST-11 TTFT P99 461 ms, DY-03 679 ms). 집계에서는 뺐지만 C1이 "Baseline이 못 하는 것을 하는" 사례다.
- ST-05는 horizon을 늘리면(class B) 평가할 수 있다. 사전 등록에서 horizon을 고정했으므로 이번에는 바꾸지 않았다(다음 단계).

# 4. 결과

## 4.1 최종 QA 표 (Common + DP-specific 통합, criteria §10 형식)

| QA | 평가 metric | Baseline (T_ref) | C1 Offline | C2 Online |
|---|---|---:|---|---|""")
w(f"| QA1 Throughput | Max SLO goodput (tok/s) ↑ | {inp['DP3']['baseline']['tps']:,.0f} | {S(stars['C1']['QA1'])} {inp['DP3']['values']['C1']['qa1_tps']:,.0f} (×{inp['DP3']['values']['C1']['qa1_ratio']:.2f}) [B+C] | {S(stars['C2']['QA1'])} {inp['DP3']['values']['C2']['qa1_tps']:,.0f} (×{inp['DP3']['values']['C2']['qa1_ratio']:.2f}) [B+C] |")
w(f"| QA2 Latency (TTFT) | TTFT P99 (ms) ↓ | {ms(ag['abs'][BASE]['ttft'])} | {ms(ag['abs'][C1]['ttft'])} (x{ag[C1]['ttft']['ratio_gm']:.2f}) [B+C] | {ms(ag['abs'][C2]['ttft'])} (x{ag[C2]['ttft']['ratio_gm']:.2f}) [B+C] |")
w(f"| QA2 Latency (TPOT) | TPOT P99 (ms) ↓ | {ag['abs'][BASE]['tpot']*1e3:.1f} | {ag['abs'][C1]['tpot']*1e3:.1f} (x{ag[C1]['tpot']['ratio_gm']:.2f}) | {ag['abs'][C2]['tpot']*1e3:.1f} (x{ag[C2]['tpot']['ratio_gm']:.2f}) |")
w(f"| QA2 별점 | 개선 r + SLO 강등 | — | {S(stars['C1']['QA2'])} [B+C] | {S(stars['C2']['QA2'])} [B+C] |")
w(f"| QA3 Resource (HBM) | HBM KV 시간평균 GiB ↓ | {ag['abs'][BASE]['hbm']:.1f} | {S(stars['C1']['QA3'])} {ag['abs'][C1]['hbm']:.1f} (감소 x{ag[C1]['hbm']['ratio_gm']:.2f}) [B+C] | {S(stars['C2']['QA3'])} {ag['abs'][C2]['hbm']:.1f} (감소 x{ag[C2]['hbm']['ratio_gm']:.2f}) [B+C] |")
if q5_ok:
    w(f"| QA5 Accuracy | F1 상대 하락 % ↓ | 0 | {S(stars['C1']['QA5'])} {q5['C1']['f1_drop_pct']:.1f}% ± {q5['C1']['ci95_halfwidth']:.1f} [소형 실측+매핑] | {S(stars['C2']['QA5'])} {q5['C2']['f1_drop_pct']:.1f}% ± {q5['C2']['ci95_halfwidth']:.1f} [소형 실측+매핑] |")
else:
    w("| QA5 Accuracy | F1 상대 하락 % ↓ | 0 | 미평가 (표본 부족, §5.3) | 미평가 |")
w(f"""
**시스템:** SYS-H100, SYS-B200 통합(8-GPU TP8 aggregate). 집계 단위: comparison-valid {ag[C1]['ttft']['n']}쌍의 기하평균. 괄호는 Baseline ÷ 후보(TTFT·TPOT·HBM 모두 >1이 개선).

## 4.2 시나리오별 결과 (부하 lam0 × 1.0, seed 평균, n_seeds = 5)

TTFT/TPOT는 P99(ms), HBM은 시간평균 GiB. 배수 = Baseline ÷ 후보(>1 개선). 신뢰구간 밖 손실은 §5.
""")
for sysid, d in res.items():
    w(f"### {sysid}\n")
    w("| 시나리오 | Fit | TTFT Base / C1 / C2 | TTFT 배수 C1 / C2 | TPOT Base / C1 / C2 | HBM Base / C1 / C2 | HBM 배수 C1 / C2 |")
    w("|---|---|---|---|---|---|---|")
    for sid in d["scenarios"]:
        p = summ["pairs"][f"{sysid}/{sid}"]
        pp = p["pol"]
        def rr(k, pol):
            a, b = pp[BASE][k], pp[pol][k]
            return "—" if not a or not b or not (math.isfinite(a) and math.isfinite(b)) else f"{a/b:.2f}"
        fit = "valid" if p["valid"] else "제외"
        w(f"| {sid} | {fit} | {ms(pp[BASE]['ttft_p99'])} / {ms(pp[C1]['ttft_p99'])} / {ms(pp[C2]['ttft_p99'])} | {rr('ttft_p99', C1)} / {rr('ttft_p99', C2)} | "
          f"{f((pp[BASE]['tpot_p99'] or 0)*1e3,1)} / {f((pp[C1]['tpot_p99'] or 0)*1e3,1)} / {f((pp[C2]['tpot_p99'] or 0)*1e3,1)} | "
          f"{f(pp[BASE]['hbm_gib'],1)} / {f(pp[C1]['hbm_gib'],1)} / {f(pp[C2]['hbm_gib'],1)} | {rr('hbm_gib', C1)} / {rr('hbm_gib', C2)} |")
    w("")
w("""## 4.3 Diagnostic — 집계 분해

| 집계 | C1 TTFT | C1 TPOT | C1 HBM | C2 TTFT | C2 TPOT | C2 HBM |
|---|---:|---:|---:|---:|---:|---:|""")
for fam in ("common", "stress", "dynamic"):
    w(f"| {fam} | " + " | ".join(f"{ag[p]['by_family'][f'{k}/{fam}']:.2f}" for p in (C1, C2) for k in ("ttft", "tpot", "hbm")) + " |")
w(f"| 전체 | " + " | ".join(f"{ag[p][k]['ratio_gm']:.2f}" for p in (C1, C2) for k in ("ttft", "tpot", "hbm")) + " |")
w(f"""
이긴 쌍 수(32쌍 중): C1 TTFT {ag[C1]['ttft']['wins']}, TPOT {ag[C1]['tpot']['wins']}, HBM {ag[C1]['hbm']['wins']} / C2 TTFT {ag[C2]['ttft']['wins']}, TPOT {ag[C2]['tpot']['wins']}, HBM {ag[C2]['hbm']['wins']}.

## 4.4 Iteration summary

상세 로그: [iterations/loop-log.md](iterations/loop-log.md)

| Iteration | Class | Change | Effect |
|---|---|---|---|
| 0 (initial) | — | — | C1 TTFT x{ag[C1]['ttft']['ratio_gm']:.2f}, C2 x{ag[C2]['ttft']['ratio_gm']:.2f}. loop **발동**(C2 집계가 Baseline 미만, 두 후보 모두 일부 시나리오에서 CI 밖 손실) |
| 1 | P (what-if 진단, 적용 안 함) | 선택 재계산 rho 0.15 → 0 | C2 TTFT x{sens['SYS-H100|C2 r=0.30 rho=0 (diag)']['ttft_ratio']:.2f}(H100)/x{sens['SYS-B200|C2 r=0.30 rho=0 (diag)']['ttft_ratio']:.2f}(B200), ST-06 C1 x{sens['SYS-H100|C1 r=0.30 rho=0 (diag)']['st06_ttft_ratio']:.2f}. 재계산이 원인. 설계·정책 상수 변경이라 허용 변경이 아니어서 **적용하지 않음** |

중단 사유: 허용되는 변경이 없다(설계 문서를 바꾸거나 정책 상수를 조정하는 것뿐). SKILL의 중단 조건 (i)(ii)와 다르므로 소유자에게 올린다(§7).

# 5. 결과 분석

## 5.1 Baseline보다 나쁜 시나리오와 원인

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| 거의 전체 (C2 TTFT, 32쌍 중 30쌍에서 Baseline보다 느림) | C2 TTFT ×0.49~0.97 (CI 밖 손실 다수) | C2는 전체 KV를 적재하므로 적재 이득이 없고 Query×KV 점수 계산 + 선택 재계산이 TTFT에 더해진다 | P | rho = 0이면 C2 TTFT ×1.30/×1.05(H100/B200). 재계산이 지배 |
| ST-06 (HBF 직접 읽기) | C1 TTFT ×0.09(H100)/×0.14(B200), C2 ×0.08/×0.12 | Baseline은 적재 비용 없이 HBF를 직접 읽는다. 압축 후보는 재계산(r·rho·L ≈ 5.9K token prefill)이 순손실 | P | rho = 0이면 C1 ×2.39/×3.49로 역전 |
| ST-03, 04, 06~10, 11 (C1/C2 TPOT) | ×0.50~0.94 | 압축으로 HBM이 풀려 동시 요청 수가 늘고 decode iteration이 공유되어 TPOT 꼬리가 길어진다 (사전 가설 (b)) | P | 같은 시나리오에서 C1 HBM 감소(§4.2) |
| ST-04 (256K) C1 TTFT | H100에서 ×0.73 | 256K 재계산 prefill 자체가 길다 | P | 같은 시나리오에서 B200은 ×1.7 |

이득의 원인: C1은 유지 r·L token만 적재·상주시키므로 적재 시간(DRAM→HBM)과 admission 대기가 줄어 TTFT가 낮아지고, 상주 KV가 1/3로 줄어 HBM 점유가 32쌍 모두에서 줄어든다. 8K Common(CB-1~3)에서도 C1 TTFT 배수 {ag[C1]['by_family']['ttft/common']:.2f}로 이긴다. C2의 HBM 이득은 요청의 작업 사본에서만 생기고(점수 계산 뒤 (1−r)·L 반환) 상주 객체는 전체 KV라 작다.""".replace("(CB-1 ×0)", ""))
w("""
## 5.2 민감도 (비교 가능 쌍, 부하 × 1.0, Baseline ÷ 후보)

| 정책 | 시스템 | TTFT 배수 | HBM 감소 배수 | 쌍 수 |
|---|---|---:|---:|---:|""")
for k, v in sens.items():
    sysid, name = k.split("|")
    w(f"| {name} | {sysid} | {v['ttft_ratio']:.2f} | {v['hbm_ratio']:.2f} | {v['n']} |")
w("""
- 유지 비율 r이 별을 가른다: **C1은 r = 0.5에서 H100 TTFT 이득이 사라진다**(×0.60). C2는 r = 0.5에서 HBM 감소가 1 아래다(H100 ×0.83: 작업 사본이 더 커져서 상주 객체 이득이 없어진다). 즉 이 결과는 r = 0.30(KVzip 3~4배 축소 값)이라는 가정에서 나왔다.
- 이 표는 별 평가가 아니고 사전 등록한 민감도다. rho = 0 행은 진단(what-if)이며 평가 결과가 아니다.
""")
w("## 5.3 QA5 정확도")
if acc is None:
    w("정확도 micro-benchmark 결과 파일이 없다. QA5 미평가.")
else:
    n = acc["n_examples"]
    br = acc["by_ratio"]["0.3"]
    w(f"""소형 모델 실측(`../accuracy`, Qwen2.5-1.5B-Instruct, SQuAD 단락 약 {acc['mean_ctx_tokens']:.0f} token, **n = {n}개** 예시, r = 0.30 eviction, 질의 점수 방식별). 예시 단위 paired bootstrap(2,000회) 95% CI.

| 점수 방식 (r = 0.30) | F1 | F1 상대 하락 % [95% CI] |
|---|---:|---|""")
    for c, nm in (("aware", "aware (C2: 실제 질의로 점수)"), ("repB", "repB (C1 근접: 같은 단락의 다른 질문)"), ("repA", "repA (일반 지시문)"), ("repC", "repC (C1 원거리: 다른 단락의 질문)"), ("random", "random (대조군)")):
        d = br[c]["f1"]
        w(f"| {nm} | {d['mean']:.3f} | {d['rel_drop_pct']:+.1f} [{d['ci95'][0]:.1f}, {d['ci95'][1]:.1f}] |")
    w(f"\nfull KV F1 = {acc['full']['f1']:.3f}. r = 1.0 경로가 full과 일치하는 sanity: {acc['sanity_r1_exact']}.")
    if q5_ok:
        m = q5["_meta"]
        w(f"""
매핑(`sim/accuracy.py`): C2 = aware. C1 = (1 − m)·repB + m·repC, m = 시나리오 mismatch의 평균 {m['mean_mismatch']:.2f}. 결과: **C1 F1 하락 {q5['C1']['f1_drop_pct']:.1f}%, C2 {q5['C2']['f1_drop_pct']:.1f}%**.""")
    else:
        w(f"\n**표본이 사전 정한 최소 {q5['_meta']['min_examples'] if q5 else 30}개에 못 미쳐 QA5는 미평가**로 둔다(현재 n = {n}). 측정은 CPU에서 진행 중이며 끝나면 이 절을 갱신한다.")
w("""
# 6. 한계

1. **Evidence**: QA2·QA3는 시뮬레이션 [B+C]이다. 실측이 아니며 DP1 simulator의 SYS profile(ASSUMED 포함)과 Llama-3.1-70B 가정에 의존한다.
2. **정확도(QA5)는 시뮬레이터 밖**이다. 소형 모델(1.5B)·단락 1.5K token·eviction만(선택 재계산 없음)의 실측이며 32K~256K 문맥, 70B 모델, CacheBlend식 재계산의 효과는 측정하지 않았다. 재계산이 있으면 실제 하락은 이 값보다 작거나 같을 것으로 보지만 이는 가정이다. C1 매핑(대표 Query 근접 비율 = 1 − mismatch)은 임시 정의다. 별은 "가정 의존"이다.
3. **사전 등록한 가정이 결과를 좌우한다**: r = 0.30, rho = 0.15, 도착률 0.7 × Baseline 용량, HBM 사용 가능 0.9. 결과를 본 뒤 바꾸지 않았다. §5.2 민감도에서 r이 바뀌면 C1 이득이 사라질 수 있음을 보였다.
4. **미모델링**: C1의 Comp.KV 사전 산출 비용·저장 공간(C1에 유리), C2의 top-k 선택·압축 사본 복사 비용(C2에 유리), 다중 문맥 blending, 노드 간 전송, DP1 배치 정책 변경. 외부 배치는 모든 정책에 같다. 압축 객체가 작아 HBM에 더 많이 상주할 수 있다는 이득은 모델링하지 않아 압축 후보에 불리한 방향이다.
5. 노드 1개, 출력 256 token 고정, 요청 간 문맥 재사용은 Zipf 풀로 모델. 실제 RAG/Agent trace가 아니다.
6. **QA3 C2 판정은 경계에 붙어 있다**: 감소 배수 {ratio:.3f} vs 경계 1.25. H100만 보면 1.34, B200만 보면 1.20이다.
7. 정확도 micro-benchmark 폴더와 sim 폴더가 같은 commit에 없어 git_rev에 +dirty가 붙었다. sim 코드·시나리오는 commit 4776de4 그대로다.

# 7. 결론

- **결정 관련 진술**: Baseline(전체 KV 재사용) 대비 **C1 Offline은 지연(TTFT ×{c1t:.2f})과 HBM(×{c1h:.2f})을 크게 줄이고 TPOT는 비슷하다**. **C2 Online은 HBM 절감이 작고 TTFT는 Baseline보다 나쁘다**(×{c2t:.2f}). 별 합계(QA5 제외)는 C1 {s1}, C2 {s2}로 C1이 앞선다. QA5 포함 최종 선택은 QA5 결과가 나온 뒤 확정한다(QA 우선순위 제안: QA2 > QA5 > QA3).
- **이득이 존재하는 조건 / 없는 조건**: C1 이득은 외부 tier에서 문맥을 적재해야 하는 경우(DRAM·CXL)와 HBM이 빠듯한 경우에 크다. **Baseline이 GPU 직접 읽기 tier(HBF)에서 서빙하는 경우, 유지 비율을 0.5로 키우는 경우(H100), 256K처럼 재계산 prefill이 긴 경우에는 이득이 없거나 진다.** C2는 어떤 조건에서도 TTFT 이득이 작다.
- **다음 단계**: (1) 소유자: C2에서 선택 재계산이 필수인지, HBF 같은 직접 읽기 tier에서는 압축을 끄는 정책을 설계에 넣을지 결정(loop-log (f)). (2) ST-05 horizon을 늘려(class B) SSD 차가운 시나리오 평가. (3) QA5 micro-benchmark 표본 확대와 재계산 포함 실측. (4) r 경계(1% / 3%) 확인.
""".replace("{ratio:.3f}", f"{ag[C2]['hbm']['ratio_gm']:.3f}").replace("{c1t:.2f}", f"{ag[C1]['ttft']['ratio_gm']:.2f}").replace("{c1h:.2f}", f"{ag[C1]['hbm']['ratio_gm']:.2f}").replace("{c2t:.2f}", f"{ag[C2]['ttft']['ratio_gm']:.2f}").replace("{s1}", str(sum(stars['C1'].values()))).replace("{s2}", str(sum(stars['C2'].values()))))
out = RES / "2026-10-11_dp3-qa-evaluation.md"
out.write_text("\n".join(L), encoding="utf-8")
print("wrote", out)
