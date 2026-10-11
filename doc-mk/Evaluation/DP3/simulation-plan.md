# DP3 Simulation Plan (사전 등록)

> 상태: **registered** (2026-10-11, 평가 실행 전). 이 문서의 가정·경계는 결과를 본 뒤 바꾸지 않는다(SKILL H5, H16). 바꾸면 사유와 이전 값을 결과 문서 한계에 기록한다.
> 결과 문서: `results/YYYY-MM-DD_dp3-qa-evaluation.md`. 별 기준: `../qa-star-criteria-unified.md`(QA2, QA3, QA5).

# 1. 대상과 후보

DP3: Long Context KV 캐시 압축·재사용. Baseline = As-Is(전체 Context KV 재사용). 후보: C1 Offline(Query-agnostic, 대표 Query로 사전 압축·공유), C2 Online(Query-aware, 요청 시점 압축). 선정 QA: QA2 지연, QA3 자원(HBM), QA5 기능 정확성.

# 2. 방법 (simulator = `sim/dp3sim.py`)

| 항목 | 내용 |
|---|---|
| 하드웨어 | DP1 simulator의 SYS profile을 import해서 쓴다(`DP1/sim/configs`): SYS-H100, SYS-B200 통합. 8-GPU 노드를 TP8 하나의 aggregate 장치로 모델(DP1과 같음). 메모리 6종의 용량·대역폭·지연은 `system-specs.md` |
| 모델 | Llama-3.1-70B BF16, KV 320 KiB/token |
| 요청 흐름 | 도착(Poisson) → HBM 공간 확보(admission) → KV 적재(tier 링크, tier별 FIFO) → GPU prefill job → decode iteration(활성 요청 전체 공유). GPU는 하나의 timeline: 대기 중 prefill job이 있으면 먼저 실행, 없으면 decode iteration |
| Baseline | 전체 L token KV를 적재, attention도 L 전체 |
| C1 | 유지 r·L token을 저장·적재·attention, 선택 재계산 rho·r·L token(prefill_s(r·L, rho·r·L)), Comp.KV는 요청 간 공유라 HBM 상주 객체도 r·L |
| C2 | 전체 L 적재 → Query×KV attention 점수 계산(GPU에서 L token의 KV를 한 번 읽는 시간 또는 attention FLOPs 중 큰 값) → r·L 유지, 선택 재계산, 이후 요청의 작업 사본은 r·L(점수 계산 뒤 (1-r)·L 반환). HBM 상주 객체는 전체 KV |
| 지표 | TTFT P99/P50 = 첫 토큰 시각 - 도착 시각(admission 대기, 적재, GPU 대기 포함). TPOT P99/P50 = (마지막 - 첫 토큰)/(출력-1). HBM 점유 = 문맥 KV(상주 객체 + 요청 작업 사본)의 시간 평균 GiB, 측정 구간 = 처음 10% 제외 |
| 정확도 | simulator가 아니다. `accuracy/`의 소형 모델 실측 + `sim/accuracy.py`의 모델(문헌 값과 실측값을 입력으로 한 외삽). [B+C]이며 별은 "가정 의존"으로 표기 |
| 도착률 | Baseline만으로 용량(SLO 만족 최대 도착률, seed 11, bisect) → lam0 = 0.7 x 용량. 모든 정책에 같은 lam0. Baseline이 어떤 도착률에서도 SLO를 못 맞추면 `infeasible` |
| 반복 | seed 11, 23, 37, 53, 71. 부하 lam0 x {0.5, 0.75, 1.0, 1.25}. 별은 lam0 x 1.0에서 |
| 집계 | 시나리오 x 시스템 쌍별 값의 기하평균, comparison-valid 쌍만. saturated(모든 정책이 서로 2% 이내)와 infeasible은 목록에 남기고 집계에서 뺀다 |

# 3. 가정 (ASSUMED, 민감도 필요)

| 가정 | 값 | 이유·한계 |
|---|---|---|
| 유지 비율 r | 0.30 | KVzip 3~4배 KV 축소(NeurIPS 2025). 후보 간 같은 r로 비교. 민감도 r = 0.15, 0.5 |
| 선택 재계산 rho | 0.15 (유지 토큰의 15%) | CacheBlend: 15% 미만 재계산에서 품질 유지(EuroSys 2025). |
| HBM 사용 가능 비율 | 0.90 | 활성화·단편화 여유(가정) |
| 외부 배치 | 시나리오별 tier 비율을 모든 정책에 동일 적용 | 배치는 DP1 소관. 압축 객체가 더 작아 더 많이 HBM에 상주할 수 있다는 이득은 모델링하지 않았다(보수적) |
| 선정 연산 비용 | Query×KV attention만 계산. top-k 선택·압축 사본 복사는 0 | C2에 유리한 단순화(C2 TTFT를 낮게 본다) |
| Comp.KV 사전 산출 비용 | 요청 경로 밖(오프라인). 별도 보고하지 않음 | C1에 유리한 단순화. 사전 압축 비용·저장 공간 증가는 모델링하지 않았다 |
| 재계산 실행 자원 | GPU | DP2가 정하는 자원은 고정 |
| 노드 | 1개, 노드 간 전송 없음 | DP4 범위 |

# 4. Baseline-regression loop (사전 등록)

- 트리거: comparison-valid 시나리오에서 후보가 Baseline보다 TTFT P99 또는 TPOT P99 또는 HBM 점유가 나쁜 경우(95% CI 밖).
- 예상(결과를 보기 전 가설): (a) C2는 문맥이 짧고 적재가 싸면(8K, DRAM) 점수 계산 시간이 이득을 넘어 TTFT가 Baseline보다 나쁠 수 있다. (b) C1은 TTFT·HBM이 좋아지지만 동시성이 늘어 TPOT 꼬리가 나빠질 수 있다. 둘 다 정책 상수를 시나리오별로 조정하지 않는다.
- 허용 변경: 분류 B(benchmark-fit, 시나리오 추가·재설계), S(profile), M(cost model 오류 수정), N(seed 추가). 정책 상수(r, rho) 재조정은 금지.
- 후보가 지는 시나리오는 삭제·숨김하지 않는다. 최대 6 iteration.

# 5. 평가하지 않는 것

실측(real HW), 노드 간 전송, DP1 배치 정책 변경, 다중 문맥 blending 품질, 사전 압축 비용·공간.

# 변경 이력 (사전 등록 이후)

- **2026-10-11 (QA1 추가, 소유자 요청)**: DP3 선정 QA에 QA1(처리량)을 추가한다. 평가 실행 전 정의: Max SLO goodput = 요청별 SLO(TTFT ≤ 2 s 그리고 TPOT ≤ 50 ms)를 만족한 요청의 output token / 측정 구간, 부하 격자 lam0 × {0.5, 0.75, 1.0, 1.25, 1.5, 2, 3, 4, 6, 8}의 최대(seed 평균). 기존 격자(최대 lam0 × 1.25 = Baseline 용량의 87%)는 포화에 닿지 않아 처리량을 잴 수 없어 격자를 넓힌다(`sim/run_qa1.py`). 정책 상수·시나리오·SLO는 바꾸지 않는다. 기존 결과는 보존하고 별도 파일(`results/data/dp3_qa1.json`)에 쓴다. 비교 가능 쌍은 기존 집계와 같은 집합에 Baseline goodput > 0을 더한다.
