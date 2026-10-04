# DP4 Benchmark (DP4 맞춤형)

> 대상: **DP4 — 비일관 CXL 공유 메모리의 KV·메타데이터 일관성 구조 (C1 중앙 직렬화 vs C2 분산 락)**. 최종 결과 = **Common Benchmark + 이 문서의 DP4 전용 benchmark**.
>
> 공통 시나리오 CB-1~3은 [`../common-benchmark.md`](../common-benchmark.md) 2.1장에 정의되어 있다. 이 문서는 DP4에서의 **실현**과 **DP4 전용 시나리오**만 둔다. 상세 정의는 [`simulation-plan.md`](simulation-plan.md) §6.
>
> 상태: **사전 등록(수기)**. 시뮬레이터 구현 후 **단일 소스는 `DP4/sim/scenarios.py`** 이며 아래 표는 생성 블록으로 대체한다.

# 1. 구성

| Set | 수 | 목적 |
|---|---|---|
| Common (CB-1~3) | 3 | 공통 QA1~QA3 별점 |
| DP4-specific (D4-n) | 17 (sweep 포함) | control plane 포화, scalability, reuse, 장애 — diagnostic, QA4 근거 |

# 2. Common Benchmark 실현 (압박 = 링크·풀 background load)

| ID | 코드명 | 실현 | 압박 |
|---|---|---|---|
| CB-1 | `cb_kv_8k_b32` | KV만, 정상 상태, n_p=1 n_d=1 | background load 0.85 (tight) |
| CB-2 | `cb_kv_8k_b32_ramp` | CB-1과 같은 KV | background load 0.2 → 0.9 ramp |
| CB-3 | `cb_mixed_8k_b32` | KV 50 / LoRA 15 / MoE 15 / Agent 10 / Tool 10 % (풀 트래픽·객체 수) | background load 0.85 |

고정: Llama-3.1-70B BF16, 8K in / 256 out, batch 32, SLO TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms, baseline prefix reuse 통제. 압박 수치는 ASSUMED이며 결과를 본 뒤 바꾸지 않는다.

# 3. Common Reference Baseline

| 항목 | 내용 |
|---|---|
| Baseline 구조 | **Baseline-RDMA**: CXL 풀 없음. P→D RDMA 점대점 KV 전송 + 중앙 위치 인덱스. 노드 간 prefix 공유 없음 |
| 구현 | `DP4/sim/policies.py` (구현 후 기록) |
| 사용 SYS | SYS-H100, SYS-B200 (통합). baseline과 후보가 같은 SYS |
| T_ref | Baseline-RDMA의 Max SLO Goodput (output tok/s) |
| 강한 baseline | η_rdma 0.85, fragmentation 페널티 없음. 약한 baseline 변형은 별점에 쓰지 않는다 |

# 4. DP4-specific 시나리오 (사전 등록, 한 줄씩)

| 시나리오 | 무엇인가 | 드러내는 것 | 핵심 파라미터 |
|---|---|---|---|
| `d4_agent_multiturn` | 8턴 에이전트, History KV 누적 (reuse 켬, 별도 행) | Baseline D→P 왕복 전송 누적 vs 풀 공유 | turns 8, 8K→ 누적 |
| `d4_hot_prefix_fanout` | 긴 공통 prefix를 대부분이 공유 | 서버 대기열 / hot 락 경합 | shared-prefix 90% |
| `d4_small_prompt_highqps` | 512 in / 64 out, 높은 rate | control plane 연산률 지배 | in 512 out 64 |
| `d4_node_scale_n4` / `_n8` / `_n16` | 노드당 부하 고정, 노드 수 4/8/16 | Scalability, scan 비용 S×N | n = 4/8/16 |
| `d4_block16` / `d4_block256` | block 크기 16 / 256 tokens | 블록당 control plane 연산 수 | block 16/256 |
| `d4_pool_full_eviction` | 풀 점유 95%에서 퇴출·reader 경합 | refcount 경합, 퇴출 지연 | pool 0.95 |
| `d4_lock_stripes_1` / `_8` / `_512` | C2 stripe 수 sweep | contention vs scan | S = 1/8/512 |
| `d4_server_threads_2` / `_4` | C1 서버 스레드 수 sweep | 중앙 직렬화 확장 여지 | threads 2/4 |
| `d4_fail_server` | C1 서버 crash 후 복구 | 가용성 창, SLO 위반 | restart 0.5s |
| `d4_fail_lockholder` | C2 락 보유 노드 crash (as-published / lease) | 락 고착, 영향 범위 | lease none/1s |

# 5. fit 분류 규칙
comparison-valid / infeasible / saturated (SKILL §4, 공통 문서 §4). saturated는 이득 근거가 아니다. 분류는 결과를 보기 전 SLO 기준으로 한다.

# 6. 모델링하지 않는 시나리오
CXL 풀 장치 장애·오류, 스위치 혼잡, 다중 테넌트 격리(문헌에서도 공백).
