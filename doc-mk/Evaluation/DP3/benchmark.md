# DP3 Benchmark (DP3 맞춤형)

> 상태: **registered** (평가 실행 전에 고정, 결과를 본 뒤 바꾸지 않는다). 최종 결과 = **Common Benchmark + 이 문서의 DP3 전용 benchmark**.
> 시나리오 단일 소스는 `sim/dp3_scenarios.py`이며 이 표는 `sim/gen_benchmark_doc.py`가 만든다(수동 편집 금지).
> 평가 방법과 가정은 [`simulation-plan.md`](simulation-plan.md), 별 기준은 `../qa-star-criteria-unified.md`.

# 1. 구성

| Set | 수 | 목적 |
|---|---:|---|
| Common (CB-1~3) | 3 | 공통 입구. 8K 문맥 재사용에서 압축·재사용이 Baseline보다 나빠지지 않는지 |
| DP3 Stress | 12 | 문맥 길이, tier, 재사용 양상, 질의 길이, 용량 압박에 따른 trade-off |
| DP3 Dynamic | 3 | Baseline이 처음엔 SLO를 만족하다 hot 문맥 이동·burst·압박 증가로 나빠지는 패턴 |

# 2. 고정 조건 (모든 시나리오 공통)

Llama-3.1-70B BF16(KV 320 KiB/token), 8-GPU 노드 1개(SYS-H100, SYS-B200 통합), 출력 256 token, SLO TTFT P99 ≤ 2 s / TPOT P99 ≤ 50 ms.
문맥 KV는 노드의 외부 배치(tier별 비율)에 놓여 있고 **배치는 모든 정책에 같다**(배치는 DP1 소관). 질의 길이 기본 256.
도착률은 Baseline만 돌려 얻은 용량(SLO를 지키는 최대 도착률)의 70%(`lam0`)로 고정한다. 부하 sweep은 lam0의 0.5/0.75/1.0/1.25배.

# 3. 정책

| 정책 | 설명 | 파라미터 |
|---|---|---|
| Baseline-As-Is | 전체 Context KV를 그대로 재사용(압축 없음). 다른 tier에 있으면 전량 적재 후 전체에 attention | — |
| C1-Offline | 사전에 만든 Comp.KV(요청 간 공유)를 적재·재사용, 선택 재계산 | 유지 비율 r = 0.30, 재계산 rho = 0.15 (유지 토큰 기준) |
| C2-Online | 요청 시점에 전체 KV를 적재하고 Query x KV attention으로 선정·압축, 선택 재계산 | r = 0.30, rho = 0.15 |

r과 rho는 문헌의 대표값(KVzip 3~4배 KV 축소, CacheBlend 15% 재계산)을 쓰며 결과를 본 뒤 바꾸지 않는다. 민감도(r 0.15/0.5)는 별도 보고한다.

# 4. Common Benchmark 실현 (CB-1~3)

| ID | 무엇인가 | 핵심 파라미터 |
|---|---|---|
| `CB-1` | 공통: 8K 문맥 재사용, HBM 압박 고정(KV 몫 12%) | ctx 8K, query 256, 풀 40개, hbm 30% dram 70%, HBM KV 몫 x0.12 |
| `CB-2` | 공통: CB-1과 같고 HBM 압박이 점진 증가 | ctx 8K, query 256, 풀 40개, hbm 30% dram 70%, HBM KV 몫 x0.2, 압박 ramp |
| `CB-3` | 공통: 다른 데이터가 HBM을 쓰는 혼합(KV 몫 50%) | ctx 8K, query 256, 풀 48개, hbm 30% dram 45% cxl_pnm 25%, HBM KV 몫 x0.5 |

# 5. DP3 Stress (12)

| ID | 무엇인가 | 핵심 파라미터 |
|---|---|---|
| `ST-01` | 32K 문맥, DRAM에서 재사용 | ctx 32K, query 256, 풀 40개, hbm 10% dram 90% |
| `ST-02` | 64K 문맥, DRAM에서 재사용 | ctx 64K, query 256, 풀 32개, hbm 10% dram 90% |
| `ST-03` | 128K 문맥, DRAM에서 재사용 | ctx 128K, query 256, 풀 24개, hbm 10% dram 90% |
| `ST-04` | 256K 문맥, CXL·DRAM 혼합 | ctx 256K, query 256, 풀 12개, hbm 10% cxl_pnm 30% dram 60% |
| `ST-05` | 128K 문맥이 SSD에 있는 차가운 재사용 | ctx 128K, query 256, 풀 24개, hbm 10% dram 20% ssd_pim 70% |
| `ST-06` | 128K 문맥이 HBF(GPU 직접 읽기)에 있음 | ctx 128K, query 256, 풀 24개, hbm 10% hbf 90% |
| `ST-07` | 소수 문맥에 재사용 집중(hot set 작음) | ctx 64K, query 256, 풀 40개, hbm 25% dram 75%, zipf 1.4 |
| `ST-08` | 재사용 분산(hot set 없음), 대부분 적재 | ctx 64K, query 256, 풀 40개, hbm 10% dram 90%, zipf 0.0 |
| `ST-09` | 긴 질의(2K) — prefill 비중이 큼 | ctx 64K, query 2048, 풀 32개, hbm 10% dram 90% |
| `ST-10` | 짧은 질의(64) — 적재·attention 비중이 큼 | ctx 64K, query 64, 풀 32개, hbm 10% dram 90% |
| `ST-11` | 128K 문맥 + HBM KV 몫 15%(동시성이 용량에 막힘) | ctx 128K, query 256, 풀 24개, hbm 10% dram 90%, HBM KV 몫 x0.15 |
| `ST-12` | 대표 Query와 실제 Query가 멀다(정확도 조건) | ctx 32K, query 256, 풀 40개, hbm 10% dram 90%, mismatch 0.8 |

# 6. DP3 Dynamic (3)

| ID | 무엇인가 | 핵심 파라미터 |
|---|---|---|
| `DY-01` | 중간에 hot 문맥이 HBM에서 내려감 | ctx 64K, query 256, 풀 32개, hbm 30% dram 70%, T/2에 hot 문맥 HBM 이탈 |
| `DY-02` | 도착률 burst(중간 1/3 구간 x2.5) | ctx 64K, query 256, 풀 32개, hbm 10% dram 90%, burst x2.5 |
| `DY-03` | 128K 문맥 + HBM 압박이 점진 증가 | ctx 128K, query 256, 풀 24개, hbm 10% dram 90%, HBM KV 몫 x0.3, 압박 ramp |

# 7. 아직 모델링하지 못하는 것

- 정확도(F1)는 이 simulator의 출력이 아니다(`accuracy/`의 소형 모델 측정과 `sim/accuracy.py` 모델).
- 여러 문맥을 이어 붙일 때의 blending 품질, chunked prefill 세부, attention kernel 효율의 문맥 길이 의존, KV 전송 중 HBM 겹침.
- 압축·재사용이 DP1 배치·DP2 실행 자원 결정과 상호작용하는 효과(여기서는 배치를 고정하고 GPU에서 실행).
