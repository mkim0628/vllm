# DP1 C1 vs C2 Overall Trade-off QA — Final

> Source run: GitHub Actions `35445200136` — SUCCESS
>
> 8 representative scenarios × 5 seeds × 5 loads × 3 candidates = **600 cells**.
>
> Overall only. C1-favorable / C2-favorable subgroup scoring은 사용하지 않는다.
>
> Architecture-level simulation이며 실제 B200/vLLM hardware benchmark가 아니다.

## 1. Candidate Boundary

### C1 — Resource-centric Placement

- Primary signal: Memory Resource State
- Runtime monitoring: Capacity / BW / Pressure / trend / near-future Resource prediction
- Data-Memory Affinity Registry: deterministic Data↔Memory / Operation knowledge
- 예: RAG→SSD-PIM GEMV, MoE→HBF spill, KV의 HBM-direct / near-memory Attention / restore path 비교

### C2 — Data-centric Placement

- Primary signal: Data-object Runtime State
- Runtime monitoring: Access / Reuse / Idle / Lifetime
- Data Type은 Data Descriptor에서 deterministic하게 사용
- Resource 정보는 current capacity / operation capability의 feasibility check로 사용
- C1의 Resource State Monitor를 포함하는 superset 구조가 아니다.

## 2. Comparative Star Rule

별점은 절대 성능 등급이 아니라 **C1/C2 Architecture trade-off를 시각화하는 comparative score**다.

- 후보 차이 ≤ **0.5%**: simulation noise band로 보고 둘 다 ★★☆
- 후보 차이 > **0.5%**: 더 좋은 후보 ★★★, 다른 후보 ★★☆
- 뒤지는 후보가 As-Is 대비 severe regression까지 보이면 ★☆☆
  - higher-is-better: ratio < 0.90 and CI upper < 1
  - lower-is-better: ratio > 1.10 and CI lower > 1
- Modifiability: average changed modules가 작은 후보 ★★★; 25% 이상 큰 후보 ★☆☆

95% CI는 별도 표기하며, comparative star 자체는 작은 Architecture 차이도 표현하기 위한 시각화다.

## 3. Overall QA

| QA | C1 Resource-centric | C2 Data-centric | Quantitative Basis |
|---|:---:|:---:|---|
| **Performance Throughput** | **★★☆** | **★★★** | C1 **0.999×** [0.985, 1.014], C2 **1.005×** [0.991, 1.019] — C2 **+0.6%** |
| **Performance TTFT** | **★★☆** | **★★★** | C1 **0.757×** [0.571, 1.005], C2 **0.658×** [0.501, 0.863] — C2 **15.2% lower** |
| **Performance TPOT** | **★☆☆** | **★★★** | C1 **1.176×** [1.025, 1.350], C2 **0.999×** [0.999, 1.000] — C2 **17.7% lower** |
| **Resource Utilization** | **★★★** | **★★☆** | C1 **1.034×** [0.974, 1.098], C2 **0.989×** [0.956, 1.023] — C1 **4.4% better** |
| **Modifiability** | **★★★** | **★☆☆** | Avg changed modules: C1 **2.5**, C2 **4.0**; object behavior state fields: C1 **0**, C2 **5** |

## 4. Trade-off Interpretation

### Throughput — C2가 근소하게 우세

C1도 KV decode path, RAG SSD-PIM 등 deterministic Data-Memory Affinity를 이미 알고 있으므로 static operation mapping 차이 때문은 아니다.  
C1은 Resource pressure 완화를 1차 목표로 하기 때문에 일부 placement/migration에서 end-to-end service capacity를 조금 희생할 수 있고, C2는 object access/reuse 상태를 중심으로 active data를 안정적인 path에 유지해 평균 throughput 손실이 더 작다.

### TTFT — C2 우세

두 구조 모두 RAG→SSD-PIM 같은 deterministic first-response 최적화를 사용할 수 있다.  
차이는 C2가 object별 Access/Reuse/Idle 상태를 이용해 현재 다시 쓰일 가능성이 높은 Data를 구분하는 반면, C1은 Resource 상태 변화에 의해 placement를 바꿀 수 있어 first-use migration/restore cost가 더 자주 critical path에 들어갈 수 있다는 점이다.

### TPOT — C2 우세

**KV decode를 어디에서 수행하는 것이 유리한지는 C1의 Data-Memory Affinity Registry에도 포함된다.** C1도 HBM direct, near-memory Attention, storage-tier restore path의 static cost를 비교한다.  
남는 차이는 C1이 Resource relief를 위해 statically 허용 가능한 offload를 선택할 수 있다는 점이다. 이 결정이 aggregate queue/link contention과 겹치면 p99 TPOT이 악화될 수 있는 반면, C2는 Resource balancing 자체를 목표로 하지 않고 object Runtime behavior를 중심으로 active/reused Data의 steady-state path를 보존한다.

### Resource Utilization — C1 우세

C1의 핵심 정보가 바로 Capacity/BW/Pressure와 그 trend이므로 Memory Tier 간 pressure를 분산시키는 방향으로 적극적으로 배치한다.  
C2는 Resource를 placement optimization signal로 깊게 추적하지 않고 현재 capacity/capability feasibility만 확인하기 때문에 Resource balancing 효과가 C1보다 작다.

### Modifiability — C1 우세

C1은 Memory Resource Monitor와 deterministic Data-Memory Affinity Registry를 중심으로 하므로 대표 change의 영향 범위가 평균 **2.5 modules**다.  
C2는 Runtime State Monitor, Data Characteristic Interpreter, object별 behavior state와 placement logic이 연결되어 평균 **4 modules**와 **5개 object-state field**가 영향을 받는다.

## 5. Final Trade-off Shape

```text
                 C1 Resource-centric      C2 Data-centric

Throughput             ★★☆                    ★★★
TTFT                   ★★☆                    ★★★
TPOT                   ★☆☆                    ★★★
Resource Utilization   ★★★                    ★★☆
Modifiability          ★★★                    ★☆☆
```

즉 현재 후보군의 trade-off는:

> **C1은 Resource efficiency와 구조 단순성에 강하고, C2는 end-to-end Performance에 강하다.**

중요하게, C2의 Performance 장점은 “C2만 KV decode/Data-Memory affinity를 안다”에서 나오지 않는다.  
그 deterministic knowledge는 C1에도 있고, 차이는 **C1은 Resource state를 중심으로 최적화하고 C2는 Data-object runtime behavior를 중심으로 최적화한다**는 데서 나온다.
