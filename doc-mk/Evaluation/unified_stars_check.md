# 공통 별 기준 v3 적용 점검 (자동 생성, 직접 편집 금지)

> 생성: `python doc-mk/Evaluation/tools/unified_stars.py`. 규칙은 `qa-star-criteria-unified.md`. 값은 `tools/unified_inputs.json`(출처 기록), DP1·DP2 `results/data/qa4_modifiability.json`, DP3 `results/data/dp3_summary.json`.

## 1. 기존 별과 공통 기준 v3 별의 비교

| DP | 후보 | QA | 값 | 기존 별 | 공통 기준 v3 별 | 일치 |
|---|---|---|---|---|---|---|
| DP1 | C1 | QA1 | 436 tok/s (x1.298) | ★★☆ | ★★☆ | O |
| DP1 | C1 | QA2 | TTFT P99 1,128 ms · TPOT P99 18.3 ms · r=0.95 | ★★★ | ★★☆ | **X** |
| DP1 | C1 | QA3 | HBM 142.7 GiB (감소율 +2.7%) | ★★☆ | ★★☆ | O |
| DP1 | C1 | QA4 | $0.39 · 0.38 MM · 1.75 module → sub ★★★/★★★/★★★ | ★★★ | ★★★ | O |
| DP1 | C2 | QA1 | 478 tok/s (x1.423) | ★★★ | ★★★ | O |
| DP1 | C2 | QA2 | TTFT P99 785 ms · TPOT P99 16.0 ms · r=1.21 | ★★★ | ★★★ | O |
| DP1 | C2 | QA3 | HBM 178.0 GiB (감소율 -21.4%) | ★☆☆ | ★☆☆ | O |
| DP1 | C2 | QA4 | $0.49 · 0.51 MM · 2.50 module → sub ★★★/★★☆/★★☆ | ★★☆ | ★★☆ | O |
| DP2 | C1 | QA1 | 1,155 tok/s (x1.075) | ★★☆ | ★★☆ | O |
| DP2 | C1 | QA2 | TTFT P99 1,995 ms · TPOT P99 19.5 ms · r=1.15 | ★★☆ | ★★☆ | O |
| DP2 | C1 | QA3 | HBM 586.1 GiB (감소율 +6.0%) | ★★☆ | ★★☆ | O |
| DP2 | C1 | QA4 | $0.39 · 0.31 MM · 1.75 module → sub ★★★/★★★/★★★ | ★★★ | ★★★ | O |
| DP2 | C2 | QA1 | 1,081 tok/s (x1.005) | ★★☆ | ★★☆ | O |
| DP2 | C2 | QA2 | TTFT P99 4,053 ms · TPOT P99 15.1 ms · r=0.91 · SLO 초과 | ★☆☆ | ★☆☆ | O |
| DP2 | C2 | QA3 | HBM 691.6 GiB (감소율 -5.0%) | ★★☆ | ★★☆ | O |
| DP2 | C2 | QA4 | $0.32 · 0.22 MM · 1.25 module → sub ★★★/★★★/★★★ | ★★★ | ★★★ | O |
| DP4 | C1 | QA1 | 3,360 tok/s (x1.050) | ★★☆ | ★★☆ | O |
| DP4 | C1 | QA2 | TTFT P99 2,060 ms · TPOT P99 48.0 ms · r=1.11 · SLO 초과 | ★★☆ | ★☆☆ | **X** |
| DP4 | C1 | QA4 | $1.02 · 0.16 MM · 2.70 module → sub ★★☆/★★★/★★☆ | ★★☆ | ★★☆ | O |
| DP4 | C1 | QA6 | SE(16) 93% | ★★★ | ★★★ | O |
| DP4 | C2 | QA1 | 3,340 tok/s (x1.040) | ★★☆ | ★★☆ | O |
| DP4 | C2 | QA2 | TTFT P99 1,940 ms · TPOT P99 48.0 ms · r=1.14 | ★★★ | ★★☆ | **X** |
| DP4 | C2 | QA4 | $0.48 · 0.15 MM · 2.30 module → sub ★★★/★★★/★★☆ | ★★★ | ★★☆ | **X** |
| DP4 | C2 | QA6 | SE(16) 64% | ★☆☆ | ★☆☆ | O |
| DP1-1안 | C1 | QA1 | 354 tok/s (x1.054) | ★★☆ | ★★☆ | O |
| DP1-1안 | C1 | QA2 | TTFT P99 1,372 ms · TPOT P99 18.2 ms · r=0.86 | ★★☆ | ★☆☆ | **X** |
| DP1-1안 | C1 | QA3 | HBM 144.6 GiB (감소율 +1.4%) | ★★☆ | ★★☆ | O |
| DP1-1안 | C1 | QA4 | $0.39 · 0.38 MM · 1.75 module → sub ★★★/★★★/★★★ | ★★★ | ★★★ | O |
| DP3 | C1 | QA1 | 1,357 tok/s (x1.514) | — | ★★★ | N/A |
| DP3 | C1 | QA2 | TTFT P99 268 ms · TPOT P99 8.4 ms · r=1.44 | — | ★★★ | N/A |
| DP3 | C1 | QA3 | HBM 30.3 GiB (감소율 +71.7%) | — | ★★★ | N/A |
| DP3 | C1 | QA5 | F1 하락 16.98% | — | ★☆☆ | N/A |
| DP3 | C2 | QA1 | 885 tok/s (x0.987) | — | ★★☆ | N/A |
| DP3 | C2 | QA2 | TTFT P99 693 ms · TPOT P99 8.7 ms · r=0.88 | — | ★☆☆ | N/A |
| DP3 | C2 | QA3 | HBM 85.1 GiB (감소율 +20.5%) | — | ★★★ | N/A |
| DP3 | C2 | QA5 | F1 하락 -1.99% | — | ★★★ | N/A |

| DP | 후보 | 별 합계(기존, 비교 가능 QA) | 별 합계(공통 기준 v3) | 일치 |
|---|---|---:|---:|---|
| DP1 | C1 | 10 | 9 | **X** |
| DP1 | C2 | 9 | 9 | O |
| DP2 | C1 | 9 | 9 | O |
| DP2 | C2 | 8 | 8 | O |
| DP4 | C1 | 9 | 8 | **X** |
| DP4 | C2 | 9 | 7 | **X** |
| DP1-1안 | C1 | 9 | 8 | **X** |
| DP3 | C1 | — | 10 | N/A |
| DP3 | C2 | — | 9 | N/A |

## 2. v2 → v3에서 바뀐 별

| DP | 후보 | QA | v2 별 | v3 별 | 이유 |
|---|---|---|---|---|---|
| DP1 | C1 | QA2 | ★★★ | ★★☆ | 개선 r=0.95, TTFT 1,128 ms / TPOT 18.3 ms (SLO 초과 시 ★) |
| DP1 | C2 | QA1 | ★★☆ | ★★★ | R=1.423 (★★★ 경계 2.0 → 4/3) |
| DP2 | C1 | QA2 | ★★★ | ★★☆ | 개선 r=1.15, TTFT 1,995 ms / TPOT 19.5 ms (SLO 초과 시 ★) |
| DP2 | C2 | QA2 | ★★☆ | ★☆☆ | 개선 r=0.91, TTFT 4,053 ms / TPOT 15.1 ms (SLO 초과 시 ★) |
| DP4 | C1 | QA2 | ★★☆ | ★☆☆ | 개선 r=1.11, TTFT 2,060 ms / TPOT 48.0 ms (SLO 초과 시 ★) |
| DP4 | C2 | QA2 | ★★★ | ★★☆ | 개선 r=1.14, TTFT 1,940 ms / TPOT 48.0 ms (SLO 초과 시 ★) |
| DP4 | C2 | QA4 | ★★★ | ★★☆ | 세 지표 AND 조건 (최소 sub-star) |
| DP1-1안 | C1 | QA2 | ★★☆ | ★☆☆ | 개선 r=0.86, TTFT 1,372 ms / TPOT 18.2 ms (SLO 초과 시 ★) |
| DP3 | C1 | QA1 | ★★☆ | ★★★ | R=1.514 (★★★ 경계 2.0 → 4/3) |
| DP3 | C2 | QA2 | ★★☆ | ★☆☆ | 개선 r=0.88, TTFT 693 ms / TPOT 8.7 ms (SLO 초과 시 ★) |

## 3. 민감도·경계 근접

- QA1 보고된 R 값(오름차순): DP3 C2 0.987, DP2 C2 1.005, DP4 C2 1.040, DP4 C1 1.050, DP1-1안 C1 1.054, DP2 C1 1.075, DP1 C1 1.298, DP1 C2 1.423, DP3 C1 1.514 — ★★★(R≥1.3333333333333333) 도달 후보: DP1 C2, DP3 C1
- QA1 DP1 C1(보완 버전 = C1+Affinity)은 R=1.2976이라 '×1.3'으로 반올림되지만 v1 경계 1.30에서도 0.2% 아래라 ★★이다. v2(2.0)에서도 ★★.
- QA2 DP1 C1: r=0.948 (R 경계 1.2/0.9까지 -21.0%/+5.3%), SLO 충족, R=2
- QA2 DP1 C2: r=1.215 (R 경계 1.2/0.9까지 +1.2%/+35.0%), SLO 충족, R=3
- QA2 DP2 C1: r=1.147 (R 경계 1.2/0.9까지 -4.4%/+27.4%), SLO 충족, R=2
- QA2 DP2 C2: r=0.913 (R 경계 1.2/0.9까지 -24.0%/+1.4%), SLO 초과(★), R=2
- QA2 DP4 C1: r=1.110 (R 경계 1.2/0.9까지 -7.5%/+23.4%), SLO 초과(★), R=2
- QA2 DP4 C2: r=1.144 (R 경계 1.2/0.9까지 -4.7%/+27.1%), SLO 충족, R=2
- QA2 DP1-1안 C1: r=0.862 (R 경계 1.2/0.9까지 -28.2%/-4.3%), SLO 충족, R=1
- QA2 DP3 C1: r=1.444 (R 경계 1.2/0.9까지 +20.3%/+60.4%), SLO 충족, R=3
- QA2 DP3 C2: r=0.881 (R 경계 1.2/0.9까지 -26.6%/-2.1%), SLO 충족, R=1
- QA4 DP1 C1: 비용/공수/module sub-star = ★★★/★★★/★★★ (AND 조건 → ★★★)
- QA4 DP1 C2: 비용/공수/module sub-star = ★★★/★★☆/★★☆ (AND 조건 → ★★☆)
- QA4 DP2 C1: 비용/공수/module sub-star = ★★★/★★★/★★★ (AND 조건 → ★★★)
- QA4 DP2 C2: 비용/공수/module sub-star = ★★★/★★★/★★★ (AND 조건 → ★★★)
- QA4 DP4 C1: 비용/공수/module sub-star = ★★☆/★★★/★★☆ (AND 조건 → ★★☆)
- QA4 DP4 C2: 비용/공수/module sub-star = ★★★/★★★/★★☆ (AND 조건 → ★★☆)
- QA4 DP1-1안 C1: 비용/공수/module sub-star = ★★★/★★★/★★★ (AND 조건 → ★★★)
- DP4 C1 QA4 (PPT 원 값, S2~S4 가중 2): sub ★★☆/★★★/★★☆ → ★★☆
- DP4 C2 QA4 (PPT 원 값, S2~S4 가중 2): sub ★★★/★★★/★★★ → ★★★
