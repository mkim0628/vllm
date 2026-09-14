# DP2 프로토타입 명세

무엇을 어떻게 재는지에 대한 참조 문서. `dp1-prototype-spec.md`와 같은 형식을 따른다.
결과는 [`dp2-prototype-results.md`](dp2-prototype-results.md)에 있다.

---

## 1. QA 3개를 각각 어떻게 재는가 (구현 전에 고정)

`dp2-agent-prefill-placement.md` §3의 QA(Performance Efficiency / Functional Correctness / Scalability)를 다음 지표로 잰다. 세 지표 모두 **정책의 내부 표현이 아니라 채점자가 실행 결과에서 독립적으로 계산한 값**이다 — 정책이 자기 답을 채점하게 하지 않는다(DP1 `metrics.py`와 같은 원칙).

| QA | 지표 | 근거 |
|---|---|---|
| **Performance Efficiency** | `objective_seconds = Σ(C_data + C_queue + C_prefill + C_interference)`, `AlwaysLocalPolicy` 대비 정규화 | §7.2 Cost Model을 실행 전체에 적분한 것. 실제로 발생한 비용의 합이며, 스케일 독립성을 위해 As-Is 기준선 대비 상대값으로 보고한다. |
| **Functional Correctness** | `regret_seconds` = 선택한 노드의 실제 Cost − 완전정보 Oracle(같은 시점 실제 Runtime State로 모든 Candidate의 Cost를 계산해 고른 최솟값)의 Cost. `oracle_match_rate` = Oracle과 같은 노드를 고른 비율 | "그 순간 실제로 무엇이 최선이었는가"를 채점자가 독립적으로 계산해 비교한다. C1은 Runtime State를 안 보므로 Runtime이 변할 때 regret이 규칙적으로 생기고, C2는 이 Oracle을 근사하는 것이 설계 의도이므로 regret이 0에 가까워야 한다 — §9 Scenario 2/3의 서술을 측정으로 검증하는 지점. |
| **Scalability** | `decision_ops_per_placement` (`DecisionCostCounter`가 `RuntimeStateView` 읽기 시점에 직접 charge). Node 수/Memory Resource 수 sweep에서의 증가율 | §6~8에서 서술로만 주장한 "C1은 Node 수와 무관, C2는 Candidate마다 값을 읽어 늘어난다"를 직접 계량. |

---

## 2. 목적함수와 Cost Model

```
objective_seconds = Σ over requests of C(node_chosen)
C(n) = C_data(n) + C_queue(n) + C_prefill(n) + C_interference(n)
```

각 항을 실제로 계산 가능한 식으로 고정한다. 상수는 대표값이며 벤더 기밀이 아니다(`tiers_default.json` 방식과 동일).

### C_data — KV Access/Movement Cost

`configs/tiers_default.json`의 tier `bw_bytes_per_s`/`latency_s`를 그대로 쓴다(`dp1_placement.tiers.load_tiers`로 로드).

```
locality == LOCAL 또는 SHARED:
    C_data(n) = tier.latency_s + history_kv_bytes / tier.bw_bytes_per_s

locality == REMOTE (KV가 다른 노드에 붙어 있어 inter-node fabric을 타야 함):
    C_data(n) = NodeFabric.latency_s + history_kv_bytes / NodeFabric.bw_bytes_per_s
```

`NodeFabric`은 새로 도입하는 상수(스캐폴딩): `bw_bytes_per_s = 5.0e10`(50 GB/s, NVLink/InfiniBand급 scale-up fabric 대표값), `latency_s = 2.0e-6`. Prefill 완료 후 D 노드로 결과를 돌려주는 sync-back 비용은 `delta_input_tokens` 분량(History 전체가 아니라 새로 생긴 조각만)에 같은 공식을 적용해 더한다.

### C_queue — Queue Cost

```
C_queue(n) = node.queue_length * QUEUE_WAIT_PER_ITEM_SECONDS
```

`QUEUE_WAIT_PER_ITEM_SECONDS = 5.0e-3` (대기 중인 항목당 평균 대기시간 근사, Little's law 스타일 가정).

### C_prefill — Prefill Execution Cost

```
C_prefill(n) = delta_input_tokens / PREFILL_TOKENS_PER_SECOND
```

`PREFILL_TOKENS_PER_SECOND = 8000.0` (노드는 compute capability가 동질적이라고 가정).

### C_interference — Interference Cost

```
C_interference(n) = node.active_decode_requests * (DECODE_TPOT_INFLATION_FACTOR - 1) * DECODE_TPOT_BASELINE_SECONDS
```

`DECODE_TPOT_BASELINE_SECONDS = 0.03`, `DECODE_TPOT_INFLATION_FACTOR = 3.0` — `dp2-agent-prefill-placement.md` 7.2절에 이미 적어둔 예시(30ms → 90ms)를 그대로 재사용한다. 이 항은 Prefill을 배정할 노드에 이미 진행 중인 Decode가 있을 때만 0보다 커진다.

### 정규화

`AlwaysLocalPolicy`(항상 `D_current`에서 실행, Runtime State/Rule 모두 무시)를 As-Is 기준선으로 삼아 1.0으로 정규화한다. DP1이 `hbm_first`를 분모로 쓰는 것과 같은 이유 — 이 프로토타입이 증명할 수 없는 최적해를 분모로 쓰지 않는다.

---

## 3. 정책 3개

| 이름 | 역할 | 무엇을 보는가 |
|---|---|---|
| `always_local` | **As-Is 기준선**, 정규화의 분모 | 아무것도 안 봄. `D_current`로 고정 |
| `c1_rule_based` | **후보 C1** | Request의 선언 필드(ΔInput, History KV Size, Request Type, KV Location)만. Runtime State 미반영 |
| `c2_cost_aware` | **후보 C2** | 같은 선언 필드 + 각 Candidate Node의 실시간 Observation(Load/Queue/Active Decode) |

### C1과 C2의 구조적 차이

`dp2-implementation-uml.md` §2.2/§2.3 그대로 구현한다. C1은 `RuleChain`(R1~R5, 첫 매치)만 쓰고 `RuntimeStateView.observation_of()`를 호출하지 않는다. C2는 `CandidateFilter`로 후보를 줄인 뒤 각 후보의 `observation_of()`를 읽어 `CostModel.total_cost()`를 계산하고 `argmin`을 고른다. **두 후보 모두 같은 Candidate 목록(`{D_current} ∪ P_eligible`)에서 시작**하며, 다른 것은 Runtime State를 보는지 여부뿐이다 — DP1이 C1/C2에 동일한 산술을 강제한 것과 같은 이유.

---

## 4. 시나리오 2개 + 스윕 2개

각 시나리오는 **어떤 변수를 고립시키는가**로 정의된다. 예상 승자는 기재하지 않는다.

공통 설정: 100 step, 조건별 10 paired seeds(DP1의 20개보다 축소 — 스코프에 맞춘 것으로 여기에 명시). 모든 정책이 같은 seed에서 동일한 세계(같은 PrefillRequest 도착 스트림, 같은 배경 Decode 트레이스)를 본다.

| 이름 | 고립시키는 변수 | 설정 |
|---|---|---|
| `low_variation` | 워크로드 변화가 적을 때 Rule과 Cost 계산이 같은 결정에 도달하는가? | ΔInput/History KV 분포 폭 좁음, RequestType 대부분 BACKGROUND, 배경 Decode load 완만하게 일정 |
| `high_variation` | ΔInput/History KV/RequestType/배경 Load가 크게 흔들릴 때 Runtime State를 보는 것이 값을 하는가? | ΔInput/History KV에 긴 꼬리, RequestType 혼합, 배경 Decode load에 step 50에서 spike(4배) |

### Node Count Sweep

**Scalability**를 보기 위해 P Node 수를 바꾼다 (D Node 수는 4로 고정): `2, 4, 8, 16`. `decision_ops_per_placement`와 `objective_seconds`가 어떻게 변하는지 본다. 기반 시나리오는 `high_variation`.

### Memory Resource Sweep

`tiers_default.json` 6-tier 중 이 클러스터에 실존하는 tier 수를 바꾼다: `2`(hbm, dram만) vs `6`(전체). 기반 시나리오는 `high_variation`.

---

## 5. 워크로드 생성기

`generators.WorkloadConfig`가 만드는 것:

1. **PrefillRequest 도착 스트림** — 매 step 일정 확률로 도착. 각 요청은 ΔInput tokens/History KV bytes/RequestType/KV Location(tier + locality)을 분포에서 샘플.
2. **배경 Decode 트레이스** — 이 시뮬레이션이 보내는 Prefill과 무관하게 각 노드의 `active_decode_requests`/기반 `queue_length`를 흔드는 외생 프로세스. DP1이 워크로드를 정책과 무관하게 미리 통째로 생성하는 것과 같은 이유 — 정책이 자기 결정의 결과를 미리 보면 안 된다.

---

## 6. 무엇이 선언되고 무엇이 관측되는가 (공정성 경계)

| | 정책이 보는가 |
|---|---|
| **선언됨** (Request 안, 모든 정책) | ΔInput tokens, History KV bytes, Request Type, KV Location |
| **관측됨** (Node 상태, C2만 읽음) | Load, Queue Length, Active Decode Requests — **완료된 step까지만** |
| **완전정보 (Oracle)** | 아무 정책도 못 봄. 채점자가 Functional Correctness를 재려고 사후에만 계산 |

DP1과 동일하게 `load`/`queue_length`는 완료된 step만 평균한다 — 결정 시점에 아직 끝나지 않은 step의 수요는 알 수 없다.

---

## 7. 판정 규칙 (실행 전 고정)

| | |
|---|---|
| Seed | 조건별 10 paired seeds. 모든 정책이 같은 seed에서 동일한 세계를 봄 |
| 차이 계산 | seed별로 계산한 뒤 평균 |
| 신뢰구간 | 95% 양측, paired 차이에 대한 정규 근사 |
| 판정 | 구간이 0을 지나면 "차이 없음" — 점 추정의 부호가 아니라 |
| 무결성 | rejection이 있으면 비교 불가로 표시 (이 프로토타입에는 capacity 기반 rejection이 없음 — 모든 Candidate가 항상 실행 가능) |

---

## 8. 재현

stdlib만 쓴다.

```bash
cd doc-architect

# 커밋된 모든 수치 (시나리오 2개 + 스윕 2개, 10 paired seeds)
PYTHONPATH=. python -m dp2_placement.run_eval --all

# 한 시나리오만
PYTHONPATH=. python -m dp2_placement.run_eval --scenario high_variation --seeds 4

# 특정 스윕만
PYTHONPATH=. python -m dp2_placement.run_eval --sweep node_count
```

원자료는 [`results/dp2_results.json`](results/dp2_results.json)에 커밋한다.
