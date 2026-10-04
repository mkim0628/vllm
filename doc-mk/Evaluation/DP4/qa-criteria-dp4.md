# DP4 QA Criteria (DP4 전용 정의·보조 기준)

> 공통 QA 정의와 별점 threshold는 [`../qa-evaluation-criteria.md`](../qa-evaluation-criteria.md)이며 **여기서 바꾸지 않는다**(H11). 이 문서는 DP4에서 QA3의 구체 metric, 집계 규칙, **공식이 아닌 제안(Scalability)**, C1 vs C2 직접 비교 방법을 정한다.
> 상태: **사전 등록(결과 전)**. 결과를 본 뒤 정의를 바꾸면 사유와 이전 값을 결과 문서 한계에 적는다(H16).

# 1. 공통 QA 적용

| QA | DP4 적용 |
|---|---|
| QA1 Throughput | 공통 정의 그대로. Max SLO Goodput, T_ref = Baseline-RDMA의 Max SLO Goodput |
| QA2 Latency | 공통 정의 그대로. TTFT P99와 TPOT P99를 별도 행으로 보고(H23), P50/P95 병기 |
| QA3 Resource Utilization | **DP4 metric 정의(§2)** — 자원 사용량만 |
| QA4 Modifiability | 공통 정의(변경 module 수) + H21의 세 sub-metric. 사전 등록: [`qa4-preregistration.md`](qa4-preregistration.md) |

별점 집계는 **Common Benchmark(CB-1~3)** 에서만 산출한다. DP4-specific 시나리오는 diagnostic이다(공통 문서 §7).

# 2. QA3 — 클러스터 KV 상주 메모리 (DP4 정의)

**원칙(H20):** QA3는 자원 사용량만 잰다. 성능을 섞지 않는다.

**Metric:** 클러스터 전체에서 KV 객체가 점유한 메모리(HBM + host DRAM + CXL 풀)의 **시간 평균 GiB**, 낮을수록 좋음. 같은 request 수를 처리하는 구간에서 비교한다.

- Baseline의 KV는 P 노드 전송 버퍼, D 노드 HBM에 **복사본**으로 존재한다. 후보는 풀에 한 부씩 둔다(블록 불변, prefix 해시로 중복 제거).
- 별점: Baseline 대비 절감 배수(1/비율)에 DP1 QA3와 같은 경계(0.95 / 1.25)를 쓴다. ★ = 절감 < 0.95, ★★ = 0.95~1.25, ★★★ = ≥ 1.25. (경계는 DP1 QA3를 그대로 가져온 것이며 DP4에서 결과를 본 뒤 조정하지 않는다. DP4에서의 적정성은 임시 정의로 표기한다.)

**진단 (별점에 쓰지 않음):** coherence 처리에 쓴 CPU core-equivalent(서버 spin-wait, 락 매니저 scan, flush 사이클), 링크·풀 점유율, 풀 점유율.

> 두 후보는 data plane이 같아 **QA3 값이 같을 것으로 예상**한다. 이는 정상이며 후보를 구분하지 않는 QA3는 "차이 없음"으로 보고한다.

# 3. Scalability — **공식 QA가 아닌 제안**

사용자의 QA 목록(슬라이드 1)에는 Scalability가 있으나 `qa-evaluation-criteria.md`에는 없다. 추가는 사용자 결정 사항(§9 형식)이므로 **여기서는 값만 보고하고 별점을 매기지 않는다**(H11).

| 항목 | 내용 |
|---|---|
| 이름 | Scalability (제안) |
| Motivation | 서버가 늘 때 control plane(중앙 서버, 락 매니저)이 처리량을 제한하는가 |
| Metric | **Scaling Efficiency** = Goodput(N) / ((N/2) × Goodput(2)), 노드당 부하 고정, N = 2, 4, 8, 16 (단위 %) |
| 제안 경계 (사용자 확정 전) | ★ < 70%, ★★ 70~90%, ★★★ ≥ 90% |
| 적용 DP | DP2, DP4 (사용자 QA 목록 기준) |
| Evidence | N=2는 사용자 환경과 같은 규모이고 N ≥ 4는 외삽이므로 [B+C] |
| 진단 | 포화 offered load, control plane 점유율 |

# 4. 선택 규칙과 우선순위

`qa_priority.json`은 **proposal**이다. 규칙(H13, `tools/dp_selection.py`): 별 합계가 높은 후보가 선택되고, 합계가 같을 때만 우선순위로 판정한다. **이 DP에서는 QA1~QA3가 같을 가능성이 높아(§10 사전 예측) 선택이 QA4와 구조 논증에 의해 정해질 수 있다.** 이 경우 결과 문서는 점수가 아니라 선택 근거(확장 한계, 장애·정확성, 변경 용이성)를 문장으로 쓴다(H13).

# 5. C1 vs C2 직접 비교

공통 별점이 후보를 구분하지 못할 때를 대비해 DP1 `qa-criteria-dp1.md`와 같은 방식으로 **직접 비교**를 둔다(공식 별점이 아님).

| 비교 항목 | 정의 |
|---|---|
| control plane op latency | 연산 종류별(lookup / publish / pin / unpin) P50, P99 비율 (C2 ÷ C1) |
| 포화 offered load | control plane이 SLO를 깨기 시작하는 request rate (CB 기준 base rate 배수) |
| scaling | Scaling Efficiency 비교 |
| 장애 | 가용성 창 길이, 영향 범위, SLO 위반 request 수 (as-published / 보완안 분리) |
| 정확성 | model check 결과(불변식 통과/반례) |

# 6. 민감도 (필수 보고)

| 축 | 값 | 이유 |
|---|---|---|
| η_cxl, η_rdma, 중첩 비율 | §4 범위 | Baseline 대비 결과를 좌우 |
| C2 락 stripe 수 S, 락 매니저 probe 비용, critical section 수 | §4 범위 | 논문에 없는 ASSUMED 값. C2 결과 해석의 한계 |
| C1 서버 스레드 수, RPC batch | §4 범위 | |
| 링크 background load | CB-1 ±0.1 | 압박 정의의 임의성 |
| 장애 복구 상수 | §4 범위 | |
| 기준 경계 근처 값 | 경계 ±10% | 별점이 경계에 의존하는지 |

# 7. 한계 (사전 명시)

- Evidence는 [B+C]이며 [A] 없음. CXL 공유 풀 하드웨어가 없다.
- C2의 락 관련 상수는 논문에 없어 ASSUMED이다. C2의 절대 성능 주장은 하지 않는다.
- CB의 "압박" 정의(link background load)는 임의 정의이며 DP1의 HBM 용량 축소와 의미가 다르다. 공통 별점의 DP 간 직접 비교에는 한계가 있다.
- model check는 설계 수준 추상 모델이다.
