# DP2 — QA 선정 근거와 평가 시나리오 설계 노트

> 상태: **draft** (평가 구현 전). 이 문서는 설계 근거와 사전 가설을 기록한다. 평가 정의와 시나리오는 `doc-mk/Evaluation/DP2/`가 원천이다.
>
> - 구조/결정 시점: [`dp2-prefill-execution-planning-decision-timing.md`](dp2-prefill-execution-planning-decision-timing.md)
> - QA 정의: [`../Evaluation/DP2/qa-criteria-dp2.md`](../Evaluation/DP2/qa-criteria-dp2.md)
> - 평가 방법: [`../Evaluation/DP2/simulation-plan.md`](../Evaluation/DP2/simulation-plan.md)
> - 시나리오: [`../Evaluation/DP2/benchmark.md`](../Evaluation/DP2/benchmark.md)

---

# 0. 요약

| 항목 | 내용 |
|---|---|
| 결정 대상 | **Turn 단위로 Prefill 실행 위치(n_p)와 Decode 시작 위치(n_d)** |
| 후보 | C1 스케줄링 시점 결정 / C2 사전 계획 결정 (같은 Cost Model, 결정 시점만 다름) |
| QA | QA1 Throughput, QA2 TTFT, QA2 TPOT, QA3 Resource Utilization, QA4 Modifiability, QA5 Scalability(DP2 전용) |
| 환경 | DP1 평가 환경 재사용: SYS-H100 / SYS-B200 통합, 노드당 6종 메모리, Llama-3.1-70B BF16, SLO TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms |
| 새로 필요한 것 | 노드 간 P/D 모델, 노드 간 링크 profile(ASSUMED), 멀티턴 세션 workload, Planner(C1/C2) 모델. **DP1 simulator는 단일 노드라 확장이 필요하다** |
| 가장 큰 리스크 | 결정 시간(`T_decision`)이 수 ms인데 TTFT가 수백 ms이면 C1/C2 차이가 후보 수가 커질 때만 나타남. Decision cost 모델이 가정이라 C1/C2 결론이 그 가정에 의존함 |

---

# 1. 범위 확정

- **DP2는 Turn 단위로 연산이 실행될 위치(Prefill 위치, Decode 시작 위치)를 정한다.** Decode 실행 중 Memory Tier 간 KV 이동은 DP1이 담당한다.
- n은 노드와 compute-memory resource의 조합이다: `(node, {GPU/HBM, GPU/HBF, ScHBM·CXL-PNM attention 오프로드})`.
- `Evaluation/DP2/README.md`가 "DP 번호 정의가 문서마다 다르므로 DP2 착수 시 범위를 확정한다"고 남겨 둔 항목을 위 범위로 확정하자고 제안한다 (소유자 확인 필요).
- DP0의 정책 P4(비용 기반 P/D 분리 판단), P5(요청별 노드 지시)가 DP2 결정을 llm-d 위에서 실행하는 경로다. 구현 프레임워크와의 코드 레벨 매핑은 DP2 범위에서 제외한다.

## Decode 시작 위치는 Prefill과 같은 시점에 결정한다

- 정보 의존성은 양적 차이뿐이다. n_d가 의존하는 D 노드 상태는 Prefill 실행 시점보다 `T_queue + T_prefill`만큼 뒤의 값이라 stale 위험이 약간 클 뿐이다.
- layer-wise KV 전송을 Prefill과 겹치려면 Prefill 시작 시점에 목적지를 알아야 하고, D 노드의 KV block을 미리 예약할 수 있다.
- 따라서 `ExecutionPlan = (n_p, n_d)`를 하나의 plan으로 두고 C1/C2의 lifecycle을 동일하게 적용한다. C2의 Late Validation에 n_d의 용량·health 확인만 추가한다.

---

# 2. 이기종 메모리에서만 결정이 달라지는 경우

평가 시나리오의 근거다. 부하만으로 설명되는 경우(HBM만 있는 환경에서도 성립하는 경우)는 제외했다.

## 2.1 계산 전제

- Llama-3.1-70B BF16: KV = 2 × 80 layers × 8 kv heads × 128 × 2 B = **327,680 B/token (320 KiB)**.
- Tier 사양은 `system-specs.md`의 H100 기준(B200은 값이 다름). 노드 간 링크는 사양에 없어 **50 GB/s로 가정(ASSUMED)**하고 평가에서 sweep한다.
- 아래 시간은 이론 대역폭 기반 하한이며 프로토콜 오버헤드와 경합은 반영하지 않았다.

| Tier | 외부 BW | 내부 BW | 비고 |
|---|---:|---:|---|
| HBM (GPU 8장 합) | 26,800 GB/s | — | GPU가 attention·FFN 실행 |
| ScHBM (노드 1개, 160 GiB) | 63 GB/s (PCIe 5.0 x16, GPU→host→ScHBM) | 6,700 GB/s | attention 오프로드 가능 |
| CXL-PNM (512 GiB) | 63 GB/s | 400 GB/s | attention 오프로드 가능 |
| DRAM (1 TiB) | 64 GB/s | — | |
| HBF (2 TiB) | 읽기 1,000 / 쓰기 50 GB/s (GPU 직접) | — | |
| SSD-PIM (16 TiB) | 16 GB/s | 200 GB/s | GEMV만 (벡터 DB) |

## 2.2 사례 A — History KV가 놓인 Tier에 따라 Prefill 위치가 바뀐다

Agent 세션, History 60K 토큰(약 19.7 GB), Tool 결과 0.5K 토큰. History는 Decode 노드(D)에 있다.

| History가 놓인 Tier | D에서 Prefill (Tmove) | P에서 Prefill (Tmove, 링크 50 GB/s) | 판단 |
|---|---|---|---|
| HBM | 0 | 약 0.39 s (+ 결과 KV 재전송) | D 로컬이 확실히 유리 (기존 규칙과 동일) |
| HBF | 직접 읽기 (승격 불필요) | 약 0.39 s | D 로컬 유리 |
| DRAM | 승격 약 0.31 s + HBM eviction | 약 0.39 s | Tmove 격차 0.08 s로 축소. **D의 Decode 부하와 HBM eviction 비용이 결정을 가름** |
| CXL-PNM | 약 0.31 s | 약 0.39 s | 위와 동일 |
| SSD-PIM | 약 1.23 s | 약 1.23 s (Tier BW가 병목) | 격차 0. 간섭이 결정 (재계산 후보는 현재 후보 집합에 없음) |

- HBM만 있는 환경에서는 이 표가 HBM 한 줄뿐이라 "KV가 있는 곳에서 실행"이라는 고정 규칙과 같은 답이 나온다.
- 이기종에서는 Tier에 따라 이동 비용 격차가 0.39 s에서 0까지 변하고, 격차가 간섭 비용보다 작아지는 지점에서 결정이 뒤집힌다. 노드 간 링크가 64 GB/s 이상이면 DRAM/CXL 행도 격차가 사라지므로 링크 대역폭 sweep이 핵심 민감도다.

## 2.3 사례 B — Decode 시작 위치와 TPOT (Tier가 TPOT 하한과 용량을 정한다)

200K 토큰 세션, KV 약 65.5 GB. Decode는 매 토큰 KV 전체를 읽는다. 아래는 batch 1에서 **KV 읽기만의 TPOT 하한**이다 (weight 읽기와 연산 제외).

| KV가 놓인 Tier | 읽기 BW | 토큰당 KV 읽기 시간 | TPOT SLO 50 ms |
|---|---:|---:|---|
| HBM (GPU 합) | 26,800 GB/s | 약 2.4 ms | 충족 |
| ScHBM (내부, attention 오프로드) | 6,700 GB/s | 약 9.8 ms | 충족 |
| HBF (GPU 직접) | 1,000 GB/s | 약 65 ms | 초과 (컨텍스트 약 150K 이하면 충족) |
| CXL-PNM (내부, 오프로드) | 400 GB/s | 약 164 ms | 초과 |
| DRAM (PCIe로 스트리밍) | 64 GB/s | 약 1.02 s | 초과 |
| SSD-PIM | 16 GB/s | 약 4.1 s | 초과 |

- 용량 제약도 Tier 의존이다. H100 노드의 HBM은 640 GiB(약 687 GB)에서 weight 약 140 GB를 빼면 KV용 약 547 GB여서 200K 세션이 약 8개 올라가고, ScHBM(160 GiB)에는 2개가 올라간다.
- 따라서 n_d는 `(노드, Tier)` 선택이고, HBM 용량이 찬 D 노드에서는 "다른 D 노드의 HBM(노드 간 전송 약 1.3 s)" 대 "같은 노드의 ScHBM 오프로드(TPOT 약 10 ms)" 같은 선택이 생긴다. 고정 규칙은 HBM에서 시작하다 용량이 차면 DRAM으로 흘려 TPOT이 1 s대로 악화된다.
- 앞선 논의에서 CXL-PNM에서의 Decode 시작을 유리한 예로 들었으나 400 GB/s 사양에서는 200K 세션이 SLO를 넘는다. 이 사례는 ScHBM 오프로드와 HBM 중심으로 쓰고, CXL-PNM은 컨텍스트 약 60K 이하(KV 약 20 GB 이하)에서만 유효하다.

## 2.4 사례로 쓰지 않는 것

- **HBF 쓰기 비대칭**: 32K 토큰 Tool 결과의 신규 KV 약 10.7 GB를 HBF에 직접 쓰면 50 GB/s에서 약 0.21 s다. 현 사양에서는 결정을 뒤집을 만큼 크지 않다. 신규 KV는 HBM에서 생성되고 DP1이 이후 내린다.

---

# 3. QA 선정과 정의

| QA | 지표 (방향) | 판정하는 설계 요소 |
|---|---|---|
| QA1 Throughput | Max SLO Goodput (tok/s) ↑ | 결정 오버헤드와 resource 선택 품질 |
| QA2 TTFT | P99 · P50 (ms) ↓ | `T_move`, `T_queue`, `T_decision` |
| QA2 TPOT | P99 · P50 (ms) ↓ | n_d 선택, Decode 간섭 |
| QA3 Resource Utilization | useful P/D 풀 GPU 사용률 (%) ↑ | Resource State 신선도(C1/C2), 후보 집합 확장 효과 |
| QA4 Modifiability | module · 공수 · 에이전트 비용 ↓ | Pluggable Tier I/F, Cost Model 교체 용이성 |
| QA5 Scalability | scaling efficiency ↑ | 후보 수 `\|N_p\| × \|N_d\| × Tier` 증가 시 결정 확장성 |

모든 칸은 `정량 값 (Baseline 대비 배수)` 형식이다.

## 3.1 TTFT와 TPOT를 분리한다

결정 하나가 두 지표를 반대로 움직인다. Prefill을 D에서 하면 TTFT는 좋아지고 TPOT는 나빠진다. 합치면 DP2의 핵심 trade-off가 표에서 사라진다. 이는 DP1의 단일 행과 다르지만, DP1에는 Decode 위치 결정이 없었다. (공통 QA 문서도 TTFT와 TPOT 별도 행 보고를 규정한다.)

## 3.2 Decision Latency와 Decision Quality는 QA가 아니라 진단 지표다

- Decision Latency는 TTFT 분해식의 한 항(`T_decision`)이다. 다만 TTFT에만 영향을 주지 않고 scheduler step 시간을 늘려 다른 요청의 TPOT와 처리량에도 영향을 준다(async scheduling이면 완화). 그래서 TTFT·TPOT·Throughput에 걸친 보조 지표로 둔다.
- Decision Quality(regret, plan age, re-plan 비율)는 최종 지표의 원인 변수다. `ΔTTFT(C2 − C1) ≈ −ΔT_decision + stale plan으로 인한 regret`. 요청 단위 지연은 정상인데 시스템 단위로만 나빠지는 경우(다른 요청의 TPOT 악화, 불필요한 KV 이동)에는 이 지표가 최종 지표보다 먼저 이상을 보여준다.

## 3.3 Resource Utilization(QA3)의 역할과 DP1과의 차이

- DP1의 QA3는 HBM 사용량이다. 이동이 데이터 총량을 바꾸지 않아 풀 활용률이 후보 간 같았기 때문이다.
- DP2는 실행 위치가 바뀌어 P/D 풀의 사용률이 후보마다 달라진다. 그래서 `qa-evaluation-criteria.md` §6이 DP2 항목으로 둔 Prefill/Decode 노드 사용률을 headline으로 쓴다.
- 고정 부하 한 점에서 측정하면 Latency/Throughput에 안 보이는 차이(여유 headroom, 노드 쏠림, 링크 소비)를 보여주는 선행 지표다. 반면 부하를 포화까지 sweep하면 대부분 Throughput과 P99에 나타나므로 Throughput과 일부 겹친다. 그래서 노드 간 CV와 KV 이동량은 진단 줄로 두고 headline은 사용률 하나로 한다.
- 별점 threshold는 criteria §6의 65/85%를 쓴다. useful utilization의 정의는 임시 정의이며 측정 전에 `qa-criteria-dp2.md`에 사전 등록한다.

---

# 4. 평가 환경

| 항목 | 내용 | 출처 |
|---|---|---|
| 시스템 | SYS-H100, SYS-B200 통합(쌍별 기하평균). 노드 = 8-GPU HGX, 6종 메모리 | DP1과 동일 (`system-specs.md`) |
| 모델 | Llama-3.1-70B BF16 | 공통 고정 |
| SLO | TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms | 공통 고정 |
| 토폴로지 | P 노드 / D 노드 (llm-d + vLLM worker), 노드당 TP8 인스턴스 1개 | 공통 criteria §8 |
| 노드 간 링크 | RDMA, 기본 50 GB/s (ASSUMED), sweep 12.5~400 GB/s | **신규 profile 필요** |
| DP1 tier 배치 | Baseline-static(공통 initial placement, migration 없음) 고정. DP1-C1 on은 민감도 | DP1과 DP2 효과 분리 |
| 통계 | seed 11/23/37/53/71, load sweep, 95% CI, CV | DP1과 동일 |

DP1 simulator는 단일 노드 가정이고 노드 간 전송을 다루지 않는다. 재사용 가능한 부분은 물리 모델(`model.py`의 prefill/decode/offloaded attention 시간, 메모리 spec), 설정, 같은 trace 비교, TTFT/TPOT 계산 방식이다. 새로 필요한 것은 `simulation-plan.md` §4에 정리했다.

---

# 5. 시나리오 설계 원칙과 사전 가설

## 5.1 원칙

- Baseline이 SLO를 만족하는(feasible) 상태에서 고정 규칙이 suboptimal해지는 workload만 쓴다. Baseline이 infeasible한 시나리오는 flag하고 승리 근거로 쓰지 않는다.
- Baseline만 돌려 설계하고 후보 실행 전에 고정한다 (DP1 Dynamic 방식).
- **이득이 없어야 정상인 시나리오도 의도적으로 포함한다**: 공통 시나리오 CB-1~3(단일 턴), Tool 결과가 큰 경우. 이들은 Planner가 Baseline보다 나빠지지 않음과 결정 오버헤드를 확인한다.

## 5.2 사전 가설 (실행 전 기록, 결과로 수정하지 않는다)

| 시나리오 | 가설 |
|---|---|
| CB-1~3 | 모든 QA가 Baseline과 같다(saturated 예상). Decision overhead만 측정 |
| `dp2_turn_hbm_small_tool` | 후보 모두 TTFT 개선 (작은 증분의 History 왕복 제거) |
| `dp2_turn_dram_small_tool` / `_hbf_hist` | Tier에 따라 D 로컬과 P 경로가 갈림. HBF는 D 로컬, DRAM은 D 부하에 따라 결정 |
| `dp2_turn_ssd_hist` | Tier BW가 병목이라 이득이 작음 (대조군) |
| `dp2_tool_large_result` | P가 최적이라 Baseline과 같음 (대조군) |
| `dp2_prefill_burst_p_saturated` | TTFT P99 개선, TPOT는 SLO 내 소폭 악화 가능 |
| `dp2_decode_heavy_p_idle` | P/D 풀 사용률 상승, TPOT·goodput 개선 |
| `dp2_long_ctx_decode_offload` | TPOT 개선. Baseline infeasible이면 flag |
| `dp2_session_size_skew` | 노드 간 CV 감소 |
| `dp2_internode_link_contention` | Baseline TTFT 악화, Planner는 로컬 실행으로 이동 |
| C1 대 C2 | 직관상 C1은 QA3·TPOT 우세, C2는 Decision Latency·Scalability 우세, TTFT/Throughput은 불확실. **실험으로만 판단** |

---

# 6. 열린 결정 사항과 위험

1. **평가 수단**: simulator 확장(권장) 범위와 일정. 소규모 프로토타입으로 Cost Model을 실제 HBM/DRAM/SSD Tier에서 검증할지.
2. **노드 간 링크 profile**: 값(50 GB/s)은 ASSUMED. 근거(NIC 구성, NIXL 실측)를 정해야 한다. 결정이 이 값에 민감하다.
3. **Decision cost 모델**: C1/C2 결론은 결정 비용(후보당 µs~ms)의 가정에 의존한다. 실제 Planner 프로토타입으로 [A] 측정하지 않으면 파라미터 sweep으로만 보고한다.
4. **QA3 headline 정의**: useful utilization의 임시 정의 확정, 별 threshold(criteria §6의 65/85%) 사용 확인.
5. **QA5 Scalability**: 공통 QA 문서에 추가할지, DP2 전용으로 둘지, threshold(0.70/0.90은 제안값) 확정.
6. **재계산 후보**: SSD Tier의 History를 로드하지 않고 재계산하는 후보를 ExecutionPlan 후보 집합에 넣을지.
7. **DP1과의 상호작용**: DP2 결과는 DP1 정책이 만든 Tier 분포에 의존한다. Baseline-static 고정을 주 결과로, DP1-C1 on을 민감도로 둔다.
8. `vllm-cost-model-prefill-execution-planning-architecture.md`는 아직 `PrefillExecutionPlanner` 명칭과 Prefill 단일 결정을 쓴다. 본 변경(ExecutionPlanner, (n_p, n_d))에 맞춰 후속 정리가 필요하다.
