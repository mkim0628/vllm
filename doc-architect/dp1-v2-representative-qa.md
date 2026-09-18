# DP1 V2 Representative QA Evaluation — C1 Static Affinity Refinement

> Source run: GitHub Actions `35377054084` — SUCCESS
>
> C1-R2에 **Data-Memory Affinity Registry**를 추가한 뒤 다시 평가했다.
>
> - 8 representative scenarios
> - 5 seeds
> - 5 load points
> - 3 candidates
> - 총 **600 cells**
>
> Serving SLO는 사용하지 않는다. 모든 Performance/Resource 별점은 동일 HW / trace / offered load에서 As-Is 대비 paired ratio와 95% CI를 사용한다.
>
> Architecture-level simulation이며 실제 B200/vLLM 실측 benchmark가 아니다.

---

## 1. Representative Scenario Set

### Neutral / Control

- `kv_b16_c32k`
- `kv_b1_c32k_cold_cxl`

### C1 Target — Resource Dynamics

- `host_path_pressure_b64`
- `data_mix_shift_b64`

### Shared Static Affinity — C1/C2 모두 사용 가능

- `rag_8tib_b64_ssd_pim`
- `mixed_all_ai_data_b64`

검증 대상:

- RAG Vector Index → SSD-PIM GEMV
- MoE Expert → HBM pressure 시 HBF spill
- Agent / Tool / LoRA 등 deterministic Data↔Tier preference

### C2 Dynamic Target — Runtime Behavior가 필요한 경우

- `kv_mispredict_dram_wait` — KV lifecycle / HBM relief 기반 stage/promotion
- `moe_expert_skew_b256` — 같은 MOE_EXPERT Type 내부의 object별 popularity skew

> 내부 scenario 이름 `kv_mispredict_dram_wait`은 과거 명칭이다. 현재 C2-R2의 Data Type은 deterministic이며 이 case의 의미는 classification uncertainty가 아니라 runtime lifecycle/reuse behavior다.

---

## 2. QA Table

| QA | C1-R2 | C2-R2 | As-Is 대비 ratio |
|---|:---:|:---:|---|
| **Performance Throughput — Overall** | **★★☆** | **★★☆** | C1 **0.977×** [0.951, 1.004]; C2 **1.004×** [0.990, 1.018] |
| **Performance Throughput — C1 Target** | **★★☆** | **★★☆** | C1 **0.988×** [0.972, 1.005]; C2 **1.000×** [1.000, 1.000] |
| **Performance Throughput — Static Affinity** | **★★☆** | **★★☆** | C1 **1.018×** [0.961, 1.079]; C2 **1.016×** [0.960, 1.075] |
| **Performance Throughput — C2 Dynamic Target** | **★★☆** | **★★☆** | C1 **0.905×** [0.839, 0.976]; C2 **1.000×** [1.000, 1.000] |
| **Performance Latency — TTFT — Overall** | **★★★** | **★★★** | C1 **0.733×** [0.539, 0.996]; C2 **0.436×** [0.283, 0.673] |
| **Performance Latency — TTFT — C1 Target** | **★★☆** | **★★★** | C1 **0.997×** [0.961, 1.034]; C2 **0.202×** [0.065, 0.623] |
| **Performance Latency — TTFT — Static Affinity** | **★★★** | **★★★** | C1 **0.210×** [0.093, 0.477]; C2 **0.179×** [0.073, 0.440] |
| **Performance Latency — TTFT — C2 Dynamic Target** | **★☆☆** | **★★☆** | C1 **1.374×** [1.115, 1.692]; C2 **1.000×** [1.000, 1.001] |
| **Performance Latency — TPOT — Overall** | **★☆☆** | **★★☆** | C1 **1.509×** [1.185, 1.921]; C2 **0.999×** [0.999, 1.000] |
| **Performance Latency — TPOT — C1 Target** | **★★☆** | **★★☆** | C1 **1.381×** [0.906, 2.103]; C2 **1.000×** [1.000, 1.000] |
| **Performance Latency — TPOT — Static Affinity** | **★★☆** | **★★☆** | C1 **1.374×** [0.904, 2.091]; C2 **0.998×** [0.994, 1.001] |
| **Performance Latency — TPOT — C2 Dynamic Target** | **★☆☆** | **★★☆** | C1 **2.730×** [1.416, 5.265]; C2 **1.000×** [1.000, 1.000] |
| **Resource Utilization — Overall** | **★★☆** | **★★☆** | C1 **1.060×** [1.011, 1.111]; C2 **0.981×** [0.931, 1.034] |
| **Resource Utilization — C1 Target** | **★★☆** | **★★☆** | C1 **1.090×** [0.952, 1.247]; C2 **1.036×** [0.918, 1.170] |
| **Resource Utilization — Static Affinity** | **★★☆** | **★★☆** | C1 **1.057×** [0.945, 1.183]; C2 **0.893×** [0.756, 1.056] |
| **Resource Utilization — C2 Dynamic Target** | **★★☆** | **★★☆** | C1 **1.095×** [1.019, 1.176]; C2 **1.000×** [1.000, 1.000] |
| **Modifiability — Overall** | **★★☆** | **★☆☆** | Avg modules changed: C1 **2.5**, C2 **4.0**; behavior-state fields: C1 **0**, C2 **5** |

### 별점 기준

- Throughput / Resource: ≥1.10× + CI lower ≥1 → ★★★ / 0.90~1.10 또는 CI가 1 포함 → ★★☆ / <0.90× + CI upper <1 → ★☆☆
- TTFT / TPOT: ≤0.90× + CI upper ≤1 → ★★★ / 0.90~1.10 또는 CI가 1 포함 → ★★☆ / >1.10× + CI lower >1 → ★☆☆
- Modifiability: 평균 변경 module ≤2 → ★★★ / ≤3 → ★★☆ / >3 → ★☆☆

---

## 3. Data-Memory Affinity Registry가 실제로 동작했는가

동작했다.

C1-R2에서 Registry가 **Resource-only best tier를 다른 tier로 바꾼 횟수**는 평균:

- 전체: **29.7회/run**
- `rag_8tib_b64_ssd_pim`: **52.2회/run**
- `mixed_all_ai_data_b64`: **50.9회/run**

또한 `mixed_all_ai_data_b64`에서 C1의 **MoE placement decision 중 79.4%가 HBF**를 사용했다.

RAG case에서도 C1은 SSD-PIM의 GEMV capability를 deterministic affinity로 인지하여 vector similarity를 data-near하게 수행할 수 있다.

즉 다음 두 optimization은 더 이상 C2 전용이 아니다.

```text
RAG_DATA + Vector Similarity
→ SSD-PIM GEMV

MOE_EXPERT + HBM pressure
→ HBF preferred spill
```

---

## 4. Refinement 후 C1/C2 차이

이제 비교는 다음처럼 보는 것이 정확하다.

### C1-R2

```text
Resource State
+ Data-Memory Affinity Registry
+ Static Execution Cost
+ Performance Guard
```

C1도 deterministic하게 알 수 있는 AI-specific optimization은 수행한다.

따라서:

- RAG→SSD-PIM
- MoE→HBF
- obvious한 Data↔Memory affinity

같은 mapping은 C1에서도 사용할 수 있다.

### C2-R2

```text
C1 수준의 Static Knowledge
+
Runtime State Monitor
+
Hotness / Reuse / Lifetime
+
Object-level adaptive path selection
```

C2의 차별점은 **AI Data Type을 안다는 것 자체가 아니다.**

> 같은 Data Type이라도 Runtime behavior가 다르면 object별로 Placement를 달리할 수 있다는 것이 차별점이다.

---

## 5. 결과 해석

### Static Affinity 영역

C1과 C2의 차이가 상당히 줄었다.

- Throughput: C1 **1.018×**, C2 **1.016×**
- TTFT: C1 **0.210×**, C2 **0.179×**
- TPOT: 둘 다 ★★☆

즉 deterministic domain knowledge만으로 해결 가능한 workload에서는 **C1도 충분히 강하다.**

### Dynamic Behavior 영역

차이가 다시 크게 벌어진다.

- C1 TTFT: **1.374× / ★☆☆**
- C2 TTFT: **1.000× / ★★☆**
- C1 TPOT: **2.730× / ★☆☆**
- C2 TPOT: **1.000× / ★★☆**

C1은 static mapping은 알지만, 같은 Type 안에서 object별 behavior가 달라질 때 이를 추적하지 않는다.

따라서 현재 Architecture trade-off는 다음으로 정리한다.

> **C1 = Resource-centric + Deterministic AI Domain Knowledge**
>
> **C2 = C1의 Static Knowledge + Runtime Behavior Adaptation**

이 구조가 기존의 `Resource only vs Data-aware` 비교보다 현실적이고 공정하다.

---

## 6. Modifiability Trade-off

C1에 Registry가 추가되었기 때문에 Modifiability 비용도 반영했다.

대표 변경:

| Change | C1-R2 | C2-R2 |
|---|---:|---:|
| New Memory Tier / Capability | 3 modules | 4 modules |
| New AI Data / Operation | 2 modules | 4 modules |
| 평균 Change Surface | **2.5** | **4.0** |
| Object-level Runtime Behavior State | **0** | **5 fields** |

따라서 C1의 Modifiability는 이전 ★★★에서 **★★☆**로 조정된다.  
C1이 더 이상 완전히 generic한 Resource-only policy가 아니기 때문에 타당한 비용이다.

---

## 7. Measurement Boundary

- Serving SLO는 사용하지 않는다.
- TTFT는 network/HTTP가 아니라 model/runtime first-token readiness다.
- SSD-PIM은 **RAG Vector Similarity GEMV만** 수행한다. Ranking/top-k는 controller/host 후처리다.
- HBF는 read-intensive/static weight spill에 사용하며 active append-heavy KV의 일반 목적 tier로 보지 않는다.
- 실제 migration execution은 DP4 범위이며 evaluator에서는 path/migration cost proxy만 포함한다.
