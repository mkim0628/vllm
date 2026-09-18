# DP1 V2 Representative QA Evaluation

> 목적: 23개 전체 시나리오의 평균으로 Architecture 차이가 희석되는 문제를 피하고, **각 구조의 핵심 mechanism을 대표하는 소수 시나리오**만으로 QA를 다시 본다.
>
> Source run: GitHub Actions `35372527324` — representative evaluator completed successfully.
>
> 별도 evaluator: `run_v2_representative.py` — 6 scenarios × 5 seeds × 5 loads × 3 candidates = **450 cells**.
>
> 대표 시나리오는 결과 winner를 보고 고른 것이 아니라 **mechanism coverage** 기준으로 정의한다.

## 1. Representative Scenario Set

### Neutral / Negative Control

- `kv_b16_c32k` — 일반적인 HBM-fit KV
- `kv_b1_c32k_cold_cxl` — CXL이 존재해도 느리면 offload하지 않아야 하는 negative control

### C1 Target — Resource Dynamics

- `host_path_pressure_b64` — Host/remote memory path BW 변화에 대한 Resource-state adaptation
- `data_mix_shift_b64` — Runtime 중 Data mix가 변하며 Tier별 pressure가 달라지는 상황

> 단순 HBM shock/ramp처럼 Placement가 거의 변하지 않는 case보다, **C1의 Resource State Monitor와 Resource Utility가 실제 cross-tier decision을 만들어야 하는 case**를 대표값으로 사용한다.

### C2 Target — Data / Operation-aware

- `kv_b16_c32k_burst_chbm` — Custom-HBM near-memory Attention path
- `rag_8tib_b64_ssd_pim` — SSD-PIM local GEMV path

> `rag_8tib_b64_ssd_pim`은 Data-near GEMV architecture stress/reference이며 실제 production vector-DB latency를 의미하지 않는다.

---

## 2. Quantitative Star Rule

모든 성능 수치는 동일 HW / 동일 trace / 동일 offered load에서 **As-Is 대비 ratio**로 계산한다.

5개 load point `[0.25, 0.50, 0.75, 1.00, 1.25]`를 각 `(scenario, seed)` 안에서 geometric mean으로 묶고, 이후 scenario-seed 간 geometric mean과 paired 95% CI를 계산한다.

### Throughput / Resource Utilization — higher is better

| 별점 | 기준 |
|---|---|
| ★★★ | ratio ≥ 1.10 AND CI lower ≥ 1.0 |
| ★★☆ | 0.90 ≤ ratio < 1.10 OR CI가 1.0 포함 |
| ★☆☆ | ratio < 0.90 AND CI upper < 1.0 |

### TTFT / TPOT — lower is better

| 별점 | 기준 |
|---|---|
| ★★★ | ratio ≤ 0.90 AND CI upper ≤ 1.0 |
| ★★☆ | 0.90 < ratio ≤ 1.10 OR CI가 1.0 포함 |
| ★☆☆ | ratio > 1.10 AND CI lower > 1.0 |

---

## 3. Representative QA Table

| QA | C1-R2 | C2-R2 | 정량 근거 — As-Is 대비 |
|---|:---:|:---:|---|
| **Performance Throughput — Overall** | **★★☆** | **★★☆** | C1 **0.963×** [0.929, 0.999], C2 **1.005×** [0.987, 1.024] |
| **Performance Throughput — C1 Target** | **★★☆** | **★★☆** | C1 **0.988×** [0.972, 1.005], C2 **1.000×** [1.000, 1.000] |
| **Performance Throughput — C2 Target** | **★★☆** | **★★☆** | C1 **0.905×** [0.818, 1.000], C2 **1.016×** [0.960, 1.075] |
| **Performance Latency — TTFT — Overall** | **★★☆** | **★★★** | C1 **0.986×** [0.930, 1.044], C2 **0.534×** [0.342, 0.835] |
| **Performance Latency — TTFT — C1 Target** | **★★☆** | **★★★** | C1 **0.994×** [0.955, 1.034], C2 **0.202×** [0.065, 0.623] |
| **Performance Latency — TTFT — C2 Target** | **★★☆** | **★★★** | C1 **0.963×** [0.809, 1.148], C2 **0.754×** [0.621, 0.915] |
| **Performance Latency — TPOT — Overall** | **★☆☆** | **★★☆** | C1 **1.441×** [1.132, 1.835], C2 **0.999×** [0.998, 1.000] |
| **Performance Latency — TPOT — C1 Target** | **★★☆** | **★★☆** | C1 **1.381×** [0.906, 2.103], C2 **1.000×** [1.000, 1.000] |
| **Performance Latency — TPOT — C2 Target** | **★☆☆** | **★★☆** | C1 **2.169×** [1.306, 3.604], C2 **0.998×** [0.994, 1.001] |
| **Resource Utilization — Overall** | **★★☆** | **★★☆** | C1 **1.056×** [0.971, 1.149], C2 **0.962×** [0.899, 1.031] |
| **Resource Utilization — C1 Target** | **★★★** | **★★☆** | C1 **1.127×** [1.006, 1.261], C2 **1.036×** [0.918, 1.170] |
| **Resource Utilization — C2 Target** | **★★☆** | **★★☆** | C1 **1.046×** [0.831, 1.316], C2 **0.860×** [0.740, 1.000] |
| **Modifiability — Overall** | **★★★** | **★☆☆** | Representative change surface: C1 **1.5 modules/change**, C2 **4.0 modules/change** |

---

## 4. Modifiability Quantitative Basis

Modifiability는 성능 simulation 값이 아니라 **대표적인 Architecture change가 몇 개 module에 전파되는지**로 계산한다.

두 가지 대표 change를 사용한다.

| Change | C1-R2 | C2-R2 |
|---|---:|---:|
| 새로운 Memory Tier / Compute Capability 추가 | **2 modules** | **4 modules** |
| 새로운 AI Data / Operation class 추가 | **1 module** | **4 modules** |
| **평균 Change Surface** | **1.5** | **4.0** |
| Object-level behavior state fields | **0** | **5** |

### Count 근거

C1의 새 Tier는 주로:

1. Memory Registry
2. Resource Utility / Static Performance Cost

에 영향을 준다.

새 AI Data class도 C1은 Data behavior model이 없으므로 static capability/cost rule 정도만 추가한다.

C2의 새 Tier/Operation은 보통:

1. Memory Registry
2. Placement Path Builder
3. Data-Operation Cost Evaluator
4. Affinity / Data Characteristic mapping

까지 영향을 준다.

또한 C2 Runtime State Monitor는 object별로 rate EWMA, sample count, last access, reuse interval EWMA, first-seen time 등의 behavior state를 유지한다.

Modifiability 별점:

- 평균 변경 module ≤ 2 → ★★★
- ≤ 3 → ★★☆
- > 3 → ★☆☆

---

## 5. 이 표에서 보이는 Trade-off

대표 scenario만 놓으면 후보군의 차이가 더 명확하다.

### C1-R2

**장점**

- C1 Target Resource Utilization: **1.127× → ★★★**
- Modifiability: **★★★**
- Data behavior prediction 없이 동작하므로 구조가 단순하고 prediction dependency가 낮음

**단점**

- Overall TPOT: **1.441× → ★☆☆**
- C2의 Data/Operation-aware path 최적화는 수행하지 못함

### C2-R2

**장점**

- Overall TTFT: **0.534× → ★★★**
- C2 Target TTFT: **0.754× → ★★★**
- TPOT은 대표 suite에서 거의 As-Is 수준 유지
- Data-near Compute / Data lifecycle optimization 가능

**단점**

- C1 Target Resource Utilization에서는 C1의 개선폭이 더 큼
- Modifiability: **★☆☆**
- Runtime behavior state와 prediction logic이 추가됨

따라서 Trade-off는 다음으로 요약한다.

> **C1-R2 = Resource efficiency / Simplicity / Modifiability**
>
> **C2-R2 = Data-aware optimization / TTFT / Heterogeneous Compute 활용**

DP1이 단순 Resource Balancing만 목표로 한다면 C1-R2가 더 경제적이다.  
반대로 DP1이 **AI Data 특성과 Memory-side Compute를 활용하는 Data Placement Runtime**을 목표로 한다면 추가 complexity를 감수하고 C2-R2를 선택할 근거가 생긴다.
