---
date: 2026-10-11
dp: DP3
candidates: [C1-Offline, C2-Online]
sys_ids: [SYS-H100, SYS-B200]
git_rev: 4776de4+dirty   # +dirty = 같은 폴더의 accuracy/ 측정 파일이 아직 commit되지 않은 상태. sim 코드·시나리오는 commit 4776de4 그대로
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA5: "[A 소형 모델 실측 + C 매핑]" }
status: draft
---

# DP3 QA Evaluation — C1 Offline(Query-agnostic) vs C2 Online(Query-aware) (Long Context KV 압축·재사용)

> 기준 문서: `../../qa-star-criteria-unified.md`(별 기준 v2), `../../common-benchmark.md`, `../../system-specs.md`, `../benchmark.md`, `../simulation-plan.md`(사전 등록)
> 이 문서의 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 정확도(QA5)만 소형 모델 실측이고 규모·모델이 다르다.

# 0. 요약

| QA | Baseline (As-Is) | C1 Offline | C2 Online |
|---|---:|---|---|
| QA1 Max SLO goodput (tok/s) ↑ | 897 | 1,357 (×1.51) | 885 (×0.99) |
| QA1 별 | — | ★★★ | ★★☆ |
| QA2 TTFT P99 (ms) ↓ | 571 | **268** (x2.14 개선) | 693 (x0.82, **Baseline보다 나쁨**) |
| QA2 TPOT P99 (ms) ↓ | 8.1 | 8.4 (x0.98) | 8.7 (x0.94) |
| QA2 별 | — | ★★★ (r=1.44, SLO 충족) | ★☆☆ (r=0.88 < 0.90 → ★) |
| QA3 HBM KV 시간평균 (GiB) ↓ | 107.1 | **30.3** (감소 x3.53) | 85.1 (감소 x1.26) |
| QA3 별 | — | ★★★ | ★★★ (경계 1.25에서 +0.6%) |
| QA5 F1 상대 하락 (%) ↓ | 0 (정의상) | 17.0 | -2.0 |
| QA5 별 | — | ★☆☆ | ★★★ |

- 집계: 18 시나리오 × 2 시스템 중 **comparison-valid 32쌍**의 기하평균(제외 4쌍은 §3). 부하 = Baseline 용량의 70%.
- **C1 Offline은 지연·HBM 모두 크게 낫다**(TTFT 28/32쌍, HBM 32/32쌍에서 이김). **C2 Online은 HBM은 줄이지만 TTFT는 32쌍 중 2쌍만 이긴다**(온라인 점수 계산 + 재계산이 요청 경로에 들어오고, 전체 KV를 적재해야 해서 적재 이득이 없다).
- 약점: **Baseline이 GPU 직접 읽기(HBF) tier에서 적재 비용 없이 서빙할 때 C1·C2 모두 TTFT가 ×0.09~0.14로 크게 진다**(ST-06). 이득은 유지 비율 r = 0.30 가정에 의존한다(r = 0.5이면 C1 TTFT 이득이 H100에서 사라진다, §5).
- 별 합계(QA5 제외): C1 10, C2 9.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | SYS-H100 (primary), SYS-B200 |
| Model / precision | Llama-3.1-70B BF16, KV 320 KiB/token, 8-GPU 노드 1개를 TP8 aggregate 장치 1개로 모델 |
| Git revision | 4776de4+dirty |
| Seeds / loads | seeds 11, 23, 37, 53, 71 / lam0 × 0.5, 0.75, 1.0, 1.25 (별은 × 1.0) |
| 재현 command | `cd doc-mk/Evaluation/DP3/sim && python run_eval.py --system SYS-H100 --system SYS-B200 && python aggregate.py && python sensitivity.py && python gen_result_doc.py` |
| Raw data | `DP3/results/data/SYS-H100/dp3_results.json`, `.../SYS-B200/dp3_results.json`, `dp3_summary.json`, `dp3_sensitivity.json` |

시스템 profile 상세: [system-specs.md](../../system-specs.md). profile 값은 DP1 simulator의 것을 import했고 provenance는 거기에 있다(ASSUMED 포함).

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO goodput | 요청별 SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms)를 만족한 요청의 output token / 측정 구간, 부하 격자 lam0 × {0.5 … 8}(최대가 끝이면 × 64까지 확장)의 최대, 쌍별 비율의 기하평균 | unified §3.1, simulation-plan 변경 이력 |
| QA2 TTFT P99 / TPOT P99 | TTFT = 첫 토큰 시각 − 도착 시각(admission 대기·KV 적재·GPU 대기 포함). TPOT = (마지막 − 첫 토큰)/(출력 − 1). 요청 P99, seed 평균, 쌍별 기하평균. r = √(TTFT 배수 × TPOT 배수) | unified §3.2 |
| QA3 HBM 사용량 | HBM에 올라간 KV(상주 Comp.KV 객체 + 요청 작업 사본)의 시간 평균 GiB. DP3 후보가 바꾸는 AI Data는 KV뿐이라 KV만 잰다(LoRA·MoE 등은 시나리오에 없음). 처음 10% 제외. 감소 배수 = Baseline ÷ 후보 | unified §3.3 |
| QA5 F1 상대 하락 | (F1_full − F1_후보) ÷ F1_full, 같은 모델·task, 압축 전 full KV 대비 | unified §3.5 |
| 집계 | comparison-valid 쌍(= Baseline이 모든 요청을 끝냄, run당 완료 요청 ≥ 10, 정책 간 2% 이상 차이)의 기하평균 | simulation-plan §2 |
| 임시 정의 | QA5의 C1 매핑(대표 Query 근접 비율 = 1 − mismatch), §6 | simulation-plan §3 |

# 3. 벤치마크 / 시나리오 (fit label)

시나리오 정의: [benchmark.md](../benchmark.md). 아래 라벨은 Baseline 기준(부하 × 1.0).

| Set | 시나리오 | SYS-H100 | SYS-B200 | 비고 |
|---|---|---|---|---|
| common | `CB-1` 공통: 8K 문맥 재사용, HBM 압박 고정(KV 몫 12%) | comparison-valid | comparison-valid | |
| common | `CB-2` 공통: CB-1과 같고 HBM 압박이 점진 증가 | comparison-valid | comparison-valid | |
| common | `CB-3` 공통: 다른 데이터가 HBM을 쓰는 혼합(KV 몫 50%) | comparison-valid | comparison-valid | |
| stress | `ST-01` 32K 문맥, DRAM에서 재사용 | comparison-valid | comparison-valid | |
| stress | `ST-02` 64K 문맥, DRAM에서 재사용 | comparison-valid | comparison-valid | |
| stress | `ST-03` 128K 문맥, DRAM에서 재사용 | comparison-valid | comparison-valid | |
| stress | `ST-04` 256K 문맥, CXL·DRAM 혼합 | comparison-valid | comparison-valid | |
| stress | `ST-05` 128K 문맥이 SSD에 있는 차가운 재사용 | 제외: Baseline가 요청을 끝내지 못함(infeasible) | 제외: Baseline가 요청을 끝내지 못함(infeasible) | |
| stress | `ST-06` 128K 문맥이 HBF(GPU 직접 읽기)에 있음 | comparison-valid | comparison-valid | |
| stress | `ST-07` 소수 문맥에 재사용 집중(hot set 작음) | comparison-valid | comparison-valid | |
| stress | `ST-08` 재사용 분산(hot set 없음), 대부분 적재 | comparison-valid | comparison-valid | |
| stress | `ST-09` 긴 질의(2K) — prefill 비중이 큼 | comparison-valid | comparison-valid | |
| stress | `ST-10` 짧은 질의(64) — 적재·attention 비중이 큼 | comparison-valid | comparison-valid | |
| stress | `ST-11` 128K 문맥 + HBM KV 몫 15%(동시성이 용량에 막힘) | 제외: Baseline가 요청을 끝내지 못함(infeasible) | comparison-valid | |
| stress | `ST-12` 대표 Query와 실제 Query가 멀다(정확도 조건) | comparison-valid | comparison-valid | |
| dynamic | `DY-01` 중간에 hot 문맥이 HBM에서 내려감 | comparison-valid | comparison-valid | |
| dynamic | `DY-02` 도착률 burst(중간 1/3 구간 x2.5) | comparison-valid | comparison-valid | |
| dynamic | `DY-03` 128K 문맥 + HBM 압박이 점진 증가 | 제외: Baseline가 요청을 끝내지 못함(infeasible) | comparison-valid | |

- 제외된 4쌍을 숨기지 않는다: ST-05(SSD 차가운 128K)는 Baseline 용량이 0.02~0.03 req/s라 90초 horizon에서 run당 요청이 0~3건이다(표본 부족, 두 SYS 모두). ST-11·DY-03 H100은 128K 문맥이 HBM에 안 들어가 Baseline이 요청을 끝내지 못하는데(infeasible), **C1은 끝낸다**(ST-11 TTFT P99 461 ms, DY-03 679 ms). 집계에서는 뺐지만 C1이 "Baseline이 못 하는 것을 하는" 사례다.
- ST-05는 horizon을 늘리면(class B) 평가할 수 있다. 사전 등록에서 horizon을 고정했으므로 이번에는 바꾸지 않았다(다음 단계).

# 4. 결과

## 4.1 최종 QA 표 (Common + DP-specific 통합, criteria §10 형식)

| QA | 평가 metric | Baseline (T_ref) | C1 Offline | C2 Online |
|---|---|---:|---|---|
| QA1 Throughput | Max SLO goodput (tok/s) ↑ | 897 | ★★★ 1,357 (×1.51) [B+C] | ★★☆ 885 (×0.99) [B+C] |
| QA2 Latency (TTFT) | TTFT P99 (ms) ↓ | 571 | 268 (x2.14) [B+C] | 693 (x0.82) [B+C] |
| QA2 Latency (TPOT) | TPOT P99 (ms) ↓ | 8.1 | 8.4 (x0.98) | 8.7 (x0.94) |
| QA2 별점 | 개선 r + SLO 강등 | — | ★★★ [B+C] | ★☆☆ [B+C] |
| QA3 Resource (HBM) | HBM KV 시간평균 GiB ↓ | 107.1 | ★★★ 30.3 (감소 x3.53) [B+C] | ★★★ 85.1 (감소 x1.26) [B+C] |
| QA5 Accuracy | F1 상대 하락 % ↓ | 0 | ★☆☆ 17.0% ± 9.5 [소형 실측+매핑] | ★★★ -2.0% ± 4.8 [소형 실측+매핑] |

**시스템:** SYS-H100, SYS-B200 통합(8-GPU TP8 aggregate). 집계 단위: comparison-valid 32쌍의 기하평균. 괄호는 Baseline ÷ 후보(TTFT·TPOT·HBM 모두 >1이 개선).

## 4.2 시나리오별 결과 (부하 lam0 × 1.0, seed 평균, n_seeds = 5)

TTFT/TPOT는 P99(ms), HBM은 시간평균 GiB. 배수 = Baseline ÷ 후보(>1 개선). 신뢰구간 밖 손실은 §5.

### SYS-H100

| 시나리오 | Fit | TTFT Base / C1 / C2 | TTFT 배수 C1 / C2 | TPOT Base / C1 / C2 | HBM Base / C1 / C2 | HBM 배수 C1 / C2 |
|---|---|---|---|---|---|---|
| CB-1 | valid | 545 / 60 / 101 | 9.06 / 5.38 | 8.7 / 8.3 / 8.5 | 41.7 / 12.3 / 33.6 | 3.40 / 1.24 |
| CB-2 | valid | 551 / 63 / 106 | 8.76 / 5.20 | 9.8 / 9.2 / 9.4 | 44.4 / 13.0 / 34.4 | 3.42 / 1.29 |
| CB-3 | valid | 56 / 39 / 70 | 1.41 / 0.79 | 6.1 / 6.0 / 6.1 | 34.0 / 10.2 / 33.8 | 3.33 / 1.01 |
| ST-01 | valid | 664 / 290 / 745 | 2.29 / 0.89 | 21.2 / 18.4 / 19.8 | 161.7 / 40.5 / 78.4 | 3.99 / 2.06 |
| ST-02 | valid | 467 / 296 / 615 | 1.58 / 0.76 | 7.8 / 7.5 / 7.3 | 65.6 / 19.4 / 62.5 | 3.37 / 1.05 |
| ST-03 | valid | 1,452 / 1,084 / 1,831 | 1.34 / 0.79 | 15.0 / 19.0 / 19.9 | 146.8 / 42.7 / 117.1 | 3.44 / 1.25 |
| ST-04 | valid | 1,854 / 2,557 / 3,822 | 0.72 / 0.48 | 17.2 / 24.5 / 25.4 | 128.4 / 38.3 / 115.7 | 3.36 / 1.11 |
| ST-05 | 제외 | — / — / — | — / — | 0.0 / 0.0 / 0.0 | 38.6 / 11.1 / 38.2 | 3.46 / 1.01 |
| ST-06 | valid | 93 / 1,176 / 1,281 | 0.08 / 0.07 | 19.3 / 26.1 / 29.5 | 176.0 / 56.7 / 124.0 | 3.11 / 1.42 |
| ST-07 | valid | 486 / 499 / 765 | 0.97 / 0.63 | 20.4 / 20.1 / 22.2 | 230.5 / 67.9 / 211.8 | 3.39 / 1.09 |
| ST-08 | valid | 1,948 / 563 / 2,088 | 3.46 / 0.93 | 19.1 / 20.3 / 20.6 | 249.9 / 65.9 / 152.0 | 3.79 / 1.64 |
| ST-09 | valid | 1,055 / 789 / 1,582 | 1.34 / 0.67 | 25.7 / 21.9 / 34.7 | 141.4 / 36.3 / 94.9 | 3.89 / 1.49 |
| ST-10 | valid | 1,186 / 525 / 1,326 | 2.26 / 0.89 | 18.7 / 20.3 / 20.3 | 181.5 / 49.7 / 108.3 | 3.65 / 1.68 |
| ST-11 | 제외 | — / 461 / — | — / — | 0.0 / 6.4 / 0.0 | 23.7 / 7.5 / 23.7 | 3.16 / 1.00 |
| ST-12 | valid | 577 / 275 / 654 | 2.09 / 0.88 | 22.1 / 18.6 / 20.2 | 174.6 / 42.6 / 80.6 | 4.10 / 2.17 |
| DY-01 | valid | 516 / 290 / 663 | 1.78 / 0.78 | 7.9 / 7.7 / 7.7 | 203.6 / 60.6 / 199.6 | 3.36 / 1.02 |
| DY-02 | valid | 522 / 322 / 680 | 1.62 / 0.77 | 8.7 / 8.4 / 8.5 | 67.3 / 19.9 / 63.3 | 3.38 / 1.06 |
| DY-03 | 제외 | — / 679 / — | — / — | 0.0 / 11.0 / 0.0 | 73.4 / 26.1 / 72.6 | 2.81 / 1.01 |

### SYS-B200

| 시나리오 | Fit | TTFT Base / C1 / C2 | TTFT 배수 C1 / C2 | TPOT Base / C1 / C2 | HBM Base / C1 / C2 | HBM 배수 C1 / C2 |
|---|---|---|---|---|---|---|
| CB-1 | valid | 153 / 42 / 161 | 3.61 / 0.95 | 6.9 / 5.9 / 6.2 | 74.7 / 19.8 / 43.3 | 3.77 / 1.73 |
| CB-2 | valid | 158 / 43 / 165 | 3.68 / 0.96 | 7.3 / 6.1 / 6.5 | 74.5 / 19.8 / 43.2 | 3.77 / 1.73 |
| CB-3 | valid | 47 / 24 / 54 | 2.01 / 0.88 | 2.5 / 2.5 / 2.5 | 33.5 / 10.1 / 33.4 | 3.33 / 1.00 |
| ST-01 | valid | 1,053 / 153 / 1,083 | 6.88 / 0.97 | 5.2 / 5.2 / 5.0 | 93.7 / 23.9 / 66.4 | 3.91 / 1.41 |
| ST-02 | valid | 453 / 183 / 517 | 2.47 / 0.87 | 3.1 / 2.9 / 2.9 | 62.2 / 18.4 / 60.9 | 3.37 / 1.02 |
| ST-03 | valid | 1,446 / 480 / 1,609 | 3.02 / 0.90 | 4.5 / 5.4 / 5.1 | 111.4 / 30.6 / 102.2 | 3.64 / 1.09 |
| ST-04 | valid | 1,817 / 1,084 / 2,488 | 1.68 / 0.73 | 6.1 / 7.0 / 7.1 | 103.0 / 28.0 / 98.5 | 3.68 / 1.05 |
| ST-05 | 제외 | — / — / — | — / — | 0.0 / 0.0 / 0.0 | 37.2 / 10.7 / 37.0 | 3.47 / 1.00 |
| ST-06 | valid | 97 / 699 / 797 | 0.14 / 0.12 | 14.6 / 26.1 / 30.0 | 279.5 / 110.2 / 197.0 | 2.54 / 1.42 |
| ST-07 | valid | 691 / 291 / 787 | 2.38 / 0.88 | 11.6 / 11.8 / 13.5 | 245.1 / 71.2 / 220.2 | 3.44 / 1.11 |
| ST-08 | valid | 1,928 / 325 / 1,992 | 5.93 / 0.97 | 4.3 / 5.1 / 4.2 | 140.5 / 36.1 / 118.2 | 3.89 / 1.19 |
| ST-09 | valid | 1,337 / 390 / 1,410 | 3.42 / 0.95 | 7.9 / 7.3 / 9.9 | 111.9 / 28.9 / 89.4 | 3.87 / 1.25 |
| ST-10 | valid | 1,264 / 274 / 1,327 | 4.62 / 0.95 | 5.0 / 5.1 / 4.9 | 107.9 / 28.5 / 88.1 | 3.79 / 1.22 |
| ST-11 | valid | 1,490 / 496 / 1,504 | 3.01 / 0.99 | 4.1 / 4.5 / 4.1 | 98.3 / 27.8 / 92.6 | 3.54 / 1.06 |
| ST-12 | valid | 635 / 144 / 663 | 4.40 / 0.96 | 4.9 / 4.7 / 4.7 | 79.5 / 21.4 / 58.2 | 3.72 / 1.37 |
| DY-01 | valid | 502 / 184 / 567 | 2.73 / 0.89 | 3.1 / 3.0 / 3.0 | 197.8 / 59.0 / 196.3 | 3.36 / 1.01 |
| DY-02 | valid | 509 / 192 / 574 | 2.65 / 0.89 | 3.3 / 3.1 / 3.1 | 63.2 / 18.7 / 61.6 | 3.38 / 1.02 |
| DY-03 | valid | 887 / 377 / 1,050 | 2.35 / 0.85 | 3.6 / 3.8 / 3.4 | 81.6 / 23.7 / 78.9 | 3.45 / 1.03 |

## 4.3 Diagnostic — 집계 분해

| 집계 | C1 TTFT | C1 TPOT | C1 HBM | C2 TTFT | C2 TPOT | C2 HBM |
|---|---:|---:|---:|---:|---:|---:|
| common | 3.80 | 1.08 | 3.50 | 1.61 | 1.06 | 1.30 |
| stress | 1.80 | 0.93 | 3.58 | 0.68 | 0.89 | 1.31 |
| dynamic | 2.18 | 1.04 | 3.38 | 0.83 | 1.05 | 1.03 |
| 전체 | 2.14 | 0.98 | 3.53 | 0.82 | 0.94 | 1.26 |

이긴 쌍 수(32쌍 중): C1 TTFT 28, TPOT 18, HBM 32 / C2 TTFT 2, TPOT 19, HBM 32.

## 4.4 Iteration summary

상세 로그: [iterations/loop-log.md](iterations/loop-log.md)

| Iteration | Class | Change | Effect |
|---|---|---|---|
| 0 (initial) | — | — | C1 TTFT x2.14, C2 x0.82. loop **발동**(C2 집계가 Baseline 미만, 두 후보 모두 일부 시나리오에서 CI 밖 손실) |
| 1 | P (what-if 진단, 적용 안 함) | 선택 재계산 rho 0.15 → 0 | C2 TTFT x1.30(H100)/x1.05(B200), ST-06 C1 x2.39. 재계산이 원인. 설계·정책 상수 변경이라 허용 변경이 아니어서 **적용하지 않음** |

중단 사유: 허용되는 변경이 없다(설계 문서를 바꾸거나 정책 상수를 조정하는 것뿐). SKILL의 중단 조건 (i)(ii)와 다르므로 소유자에게 올린다(§7).

# 5. 결과 분석

## 5.1 Baseline보다 나쁜 시나리오와 원인

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| 거의 전체 (C2 TTFT, 32쌍 중 30쌍에서 Baseline보다 느림) | C2 TTFT ×0.49~0.97 (CI 밖 손실 다수) | C2는 전체 KV를 적재하므로 적재 이득이 없고 Query×KV 점수 계산 + 선택 재계산이 TTFT에 더해진다 | P | rho = 0이면 C2 TTFT ×1.30/×1.05(H100/B200). 재계산이 지배 |
| ST-06 (HBF 직접 읽기) | C1 TTFT ×0.09(H100)/×0.14(B200), C2 ×0.08/×0.12 | Baseline은 적재 비용 없이 HBF를 직접 읽는다. 압축 후보는 재계산(r·rho·L ≈ 5.9K token prefill)이 순손실 | P | rho = 0이면 C1 ×2.39/×3.49로 역전 |
| ST-03, 04, 06~10, 11 (C1/C2 TPOT) | ×0.50~0.94 | 압축으로 HBM이 풀려 동시 요청 수가 늘고 decode iteration이 공유되어 TPOT 꼬리가 길어진다 (사전 가설 (b)) | P | 같은 시나리오에서 C1 HBM 감소(§4.2) |
| ST-04 (256K) C1 TTFT | H100에서 ×0.73 | 256K 재계산 prefill 자체가 길다 | P | 같은 시나리오에서 B200은 ×1.7 |

이득의 원인: C1은 유지 r·L token만 적재·상주시키므로 적재 시간(DRAM→HBM)과 admission 대기가 줄어 TTFT가 낮아지고, 상주 KV가 1/3로 줄어 HBM 점유가 32쌍 모두에서 줄어든다. 8K Common(CB-1~3)에서도 C1 TTFT 배수 3.80로 이긴다. C2의 HBM 이득은 요청의 작업 사본에서만 생기고(점수 계산 뒤 (1−r)·L 반환) 상주 객체는 전체 KV라 작다.

## 5.2 민감도 (비교 가능 쌍, 부하 × 1.0, Baseline ÷ 후보)

| 정책 | 시스템 | TTFT 배수 | HBM 감소 배수 | 쌍 수 |
|---|---|---:|---:|---:|
| C1 r=0.15 | SYS-H100 | 3.90 | 8.26 | 15 |
| C1 r=0.30 | SYS-H100 | 1.70 | 3.56 | 15 |
| C1 r=0.50 | SYS-H100 | 0.60 | 1.29 | 15 |
| C2 r=0.15 | SYS-H100 | 1.08 | 1.54 | 15 |
| C2 r=0.30 | SYS-H100 | 0.87 | 1.34 | 15 |
| C2 r=0.50 | SYS-H100 | 0.43 | 0.83 | 15 |
| C1 r=0.30 rho=0 (diag) | SYS-H100 | 5.02 | 4.20 | 15 |
| C2 r=0.30 rho=0 (diag) | SYS-H100 | 1.30 | 1.48 | 15 |
| C1 r=0.15 | SYS-B200 | 5.98 | 7.91 | 17 |
| C1 r=0.30 | SYS-B200 | 2.68 | 3.54 | 17 |
| C1 r=0.50 | SYS-B200 | 1.06 | 1.56 | 17 |
| C2 r=0.15 | SYS-B200 | 0.95 | 1.33 | 17 |
| C2 r=0.30 | SYS-B200 | 0.84 | 1.20 | 17 |
| C2 r=0.50 | SYS-B200 | 0.57 | 0.90 | 17 |
| C1 r=0.30 rho=0 (diag) | SYS-B200 | 4.87 | 3.97 | 17 |
| C2 r=0.30 rho=0 (diag) | SYS-B200 | 1.05 | 1.29 | 17 |

- 유지 비율 r이 별을 가른다: **C1은 r = 0.5에서 H100 TTFT 이득이 사라진다**(×0.60). C2는 r = 0.5에서 HBM 감소가 1 아래다(H100 ×0.83: 작업 사본이 더 커져서 상주 객체 이득이 없어진다). 즉 이 결과는 r = 0.30(KVzip 3~4배 축소 값)이라는 가정에서 나왔다.
- 이 표는 별 평가가 아니고 사전 등록한 민감도다. rho = 0 행은 진단(what-if)이며 평가 결과가 아니다.

## 5.3 QA5 정확도
소형 모델 실측(`../accuracy`, Qwen2.5-1.5B-Instruct, SQuAD 단락 약 1381 token, **n = 93개** 예시, r = 0.30 eviction, 질의 점수 방식별). 예시 단위 paired bootstrap(2,000회) 95% CI.

| 점수 방식 (r = 0.30) | F1 | F1 상대 하락 % [95% CI] |
|---|---:|---|
| aware (C2: 실제 질의로 점수) | 0.745 | -2.0 [-6.8, 2.7] |
| repB (C1 근접: 같은 단락의 다른 질문) | 0.680 | +6.9 [-1.3, 15.3] |
| repA (일반 지시문) | 0.430 | +41.2 [29.5, 52.7] |
| repC (C1 원거리: 다른 단락의 질문) | 0.457 | +37.4 [25.7, 49.6] |
| random (대조군) | 0.332 | +54.5 [44.7, 63.9] |

full KV F1 = 0.730. r = 1.0 경로가 full과 일치하는 sanity: 93/93.

매핑(`sim/accuracy.py`): C2 = aware. C1 = (1 − m)·repB + m·repC, m = 시나리오 mismatch의 평균 0.33. 결과: **C1 F1 하락 17.0%, C2 -2.0%**.

# 6. 한계

1. **Evidence**: QA2·QA3는 시뮬레이션 [B+C]이다. 실측이 아니며 DP1 simulator의 SYS profile(ASSUMED 포함)과 Llama-3.1-70B 가정에 의존한다.
2. **정확도(QA5)는 시뮬레이터 밖**이다. 소형 모델(1.5B)·단락 1.5K token·eviction만(선택 재계산 없음)의 실측이며 32K~256K 문맥, 70B 모델, CacheBlend식 재계산의 효과는 측정하지 않았다. 재계산이 있으면 실제 하락은 이 값보다 작거나 같을 것으로 보지만 이는 가정이다. C1 매핑(대표 Query 근접 비율 = 1 − mismatch)은 임시 정의다. 별은 "가정 의존"이다.
3. **사전 등록한 가정이 결과를 좌우한다**: r = 0.30, rho = 0.15, 도착률 0.7 × Baseline 용량, HBM 사용 가능 0.9. 결과를 본 뒤 바꾸지 않았다. §5.2 민감도에서 r이 바뀌면 C1 이득이 사라질 수 있음을 보였다.
4. **미모델링**: C1의 Comp.KV 사전 산출 비용·저장 공간(C1에 유리), C2의 top-k 선택·압축 사본 복사 비용(C2에 유리), 다중 문맥 blending, 노드 간 전송, DP1 배치 정책 변경. 외부 배치는 모든 정책에 같다. 압축 객체가 작아 HBM에 더 많이 상주할 수 있다는 이득은 모델링하지 않아 압축 후보에 불리한 방향이다.
5. 노드 1개, 출력 256 token 고정, 요청 간 문맥 재사용은 Zipf 풀로 모델. 실제 RAG/Agent trace가 아니다.
6. **QA3 C2 판정은 경계에 붙어 있다**: 감소 배수 1.258 vs 경계 1.25. H100만 보면 1.34, B200만 보면 1.20이다.
7. 정확도 micro-benchmark 폴더와 sim 폴더가 같은 commit에 없어 git_rev에 +dirty가 붙었다. sim 코드·시나리오는 commit 4776de4 그대로다.

# 7. 결론

- **결정 관련 진술**: Baseline(전체 KV 재사용) 대비 **C1 Offline은 지연(TTFT ×2.14)과 HBM(×3.53)을 크게 줄이고 TPOT는 비슷하다**. **C2 Online은 HBM 절감이 작고 TTFT는 Baseline보다 나쁘다**(×0.82). 별 합계(QA5 제외)는 C1 10, C2 9로 C1이 앞선다. QA5 포함 최종 선택은 QA5 결과가 나온 뒤 확정한다(QA 우선순위 제안: QA2 > QA5 > QA3).
- **이득이 존재하는 조건 / 없는 조건**: C1 이득은 외부 tier에서 문맥을 적재해야 하는 경우(DRAM·CXL)와 HBM이 빠듯한 경우에 크다. **Baseline이 GPU 직접 읽기 tier(HBF)에서 서빙하는 경우, 유지 비율을 0.5로 키우는 경우(H100), 256K처럼 재계산 prefill이 긴 경우에는 이득이 없거나 진다.** C2는 어떤 조건에서도 TTFT 이득이 작다.
- **다음 단계**: (1) 소유자: C2에서 선택 재계산이 필수인지, HBF 같은 직접 읽기 tier에서는 압축을 끄는 정책을 설계에 넣을지 결정(loop-log (f)). (2) ST-05 horizon을 늘려(class B) SSD 차가운 시나리오 평가. (3) QA5 micro-benchmark 표본 확대와 재계산 포함 실측. (4) r 경계(1% / 3%) 확인.
