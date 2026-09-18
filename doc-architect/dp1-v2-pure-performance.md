# DP1 V2 Evaluation — Pure System Performance

> Source run: GitHub Actions `35335718071`
>
> Performance QA는 serving SLO를 사용하지 않는다. 동일 HW / 동일 trace / 동일 offered load에서 As-Is 대비 순수 system performance를 비교한다.
>
> Throughput은 높을수록, TTFT/TPOT은 낮을수록 좋다. Load sweep은 각 `(scenario, seed)` 내부에서 먼저 geometric mean으로 묶은 뒤 scenario-seed 단위로 aggregate한다.
>
> Architecture-level simulation이며 실제 B200/vLLM 실측 benchmark가 아니다.

## 1. QA 평가표

| QA | C1-R2 | C2-R2 | As-Is 대비 ratio |
|---|:---:|:---:|---|
| **Performance Throughput — Overall** | **★★☆** | **★★☆** | C1 **0.926×** [0.892, 0.960]; C2 **0.989×** [0.975, 1.004] |
| **Performance Throughput — C1 Target Case** | **★★☆** | **★★☆** | C1 **0.994×** [0.988, 1.001]; C2 **1.000×** [1.000, 1.000] |
| **Performance Throughput — C2 Target Case** | **★★☆** | **★★☆** | C1 **0.945×** [0.901, 0.992]; C2 **1.013×** [0.991, 1.037] |
| **Performance Latency — TTFT — Overall** | **★★☆** | **★★★** | C1 **0.984×** [0.867, 1.117]; C2 **0.740×** [0.615, 0.891] |
| **Performance Latency — TTFT — C1 Target Case** | **★★☆** | **★★★** | C1 **0.664×** [0.428, 1.029]; C2 **0.296×** [0.155, 0.565] |
| **Performance Latency — TTFT — C2 Target Case** | **★★☆** | **★★★** | C1 **1.075×** [0.961, 1.202]; C2 **0.878×** [0.803, 0.960] |
| **Performance Latency — TPOT — Overall** | **★☆☆** | **★★☆** | C1 **1.645×** [1.403, 1.929]; C2 **1.081×** [1.011, 1.156] |
| **Performance Latency — TPOT — C1 Target Case** | **★☆☆** | **★★☆** | C1 **1.293×** [1.022, 1.637]; C2 **1.000×** [1.000, 1.000] |
| **Performance Latency — TPOT — C2 Target Case** | **★☆☆** | **★★☆** | C1 **1.809×** [1.328, 2.465]; C2 **0.999×** [0.998, 1.000] |
| **Resource Utilization — Overall** | **★★☆** | **★★☆** | RUI C1 **0.809**; C2 **0.771** |
| **Modifiability — Overall** | 재산정 필요 | 재산정 필요 | R2 구조 기준 별도 측정 필요 |

### 별점 기준

- Throughput: ≥1.10× and CI lower ≥1.0 → ★★★; 0.90~1.10 또는 CI가 1 포함 → ★★☆; <0.90× and CI upper <1.0 → ★☆☆
- TTFT/TPOT: ≤0.90× and CI upper ≤1.0 → ★★★; 0.90~1.10 또는 CI가 1 포함 → ★★☆; >1.10× and CI lower >1.0 → ★☆☆

## 2. C1-R2 Performance Guard 적용 전/후

C2-R2의 “candidate path가 실제로 더 빠른가?”라는 no-regret 원칙을 C1-R2에도 적용했다.

단, C1은 C2처럼 Hotness / Reuse / Lifetime을 사용하지 않는다. C1 Guard는 다음만 사용한다.

```text
Resource State
+ Memory Capability
+ Static Execution / Transfer Cost
+ Migration Cost
```

| Metric | Guard 적용 전 | Guard 적용 후 | 변화 |
|---|---:|---:|---:|
| Overall Throughput / As-Is | 0.729× | **0.926×** | **+26.9%** |
| Overall TTFT / As-Is ↓ | 1.254× | **0.984×** | **-21.5%** |
| Overall TPOT / As-Is ↓ | 3.444× | **1.645×** | **-52.2%** |
| C1 Target Throughput / As-Is | 0.876× | **0.994×** | **+13.5%** |
| C1 Target TTFT / As-Is ↓ | 1.152× | **0.664×** | **-42.4%** |
| C1 Target TPOT / As-Is ↓ | 3.636× | **1.293×** | **-64.4%** |
| RUI | **0.859** | 0.809 | -0.050 |

즉 Performance Guard를 넣으면서 **성능은 크게 회복했고, 그 대가로 Resource Utilization 일부를 포기했다.**

## 3. C1 Target Case에서 Guard가 실제로 한 일

C1 Target Case:

- `hbm_pressure_ramp_b64`
- `hbm_bw_shock_b256`
- `host_path_pressure_b64`
- `data_mix_shift_b64`
- `mixed_all_ai_data_b64`

이 그룹에서 Guard는 Emergency가 발생했다고 무조건 offload하지 않고, Candidate Path가 Current/HBM Path보다 크게 느려지는 이동을 차단한다.

핵심 의미는:

```text
Resource pressure relief
        +
Relative Performance Guard
        ↓
둘 다 만족하는 이동만 허용
```

이다.

## 4. 왜 아직 C1 TPOT이 1.293×인가

Guard 적용으로 C1 Target Case TPOT은 **3.636× → 1.293×**까지 크게 개선됐지만 아직 As-Is보다 느리다.

남은 문제는 주로 mixed workload에서 발생한다.

- `data_mix_shift_b64`
- `mixed_all_ai_data_b64`

이런 workload에서는 여러 Data/Operation이 같이 존재해 Resource-only static cost proxy와 실제 critical path 사이 approximation error가 남는다.

따라서 다음 보완 포인트는 threshold 사후 tuning이 아니라:

> **C1 Resource Utility의 static execution-cost proxy를 실제 critical-path model과 더 일치시키는 것**

이다.

## 5. C2-R2도 SLO-independent로 정리

Pure system-performance 원칙과 맞추기 위해 C2-R2 내부의 2s/50ms 절대 SLO gate도 제거했다.

C2-R2는 이제:

```text
Candidate Path
vs
Current / HBM Path
```

의 상대 service time / TTFT / TPOT을 비교한다.

그 결과 C2-R2는:

- Overall TTFT: **0.740× → ★★★**
- C2 Target TTFT: **0.878× → ★★★**
- C2 Target TPOT: **0.999× → ★★☆**

로 나타났다.

즉 C2의 장점은 특정 SLO를 만족시키는 데서 나오는 것이 아니라 **Data/Operation-aware path selection 자체가 first-response latency를 줄이는 데서 나온다.**

## 6. C1과 C2의 차이는 유지된다

| | C1-R2 | C2-R2 |
|---|---|---|
| Primary signal | Resource State | Data + Resource State |
| Runtime Data behavior | 사용 안 함 | Hotness / Reuse / Lifetime |
| Performance Guard | Static resource/execution cost | Data/Operation-aware path cost |
| Pressure 대응 | Resource pressure relief + Guard | Data-aware path selection + Guard |

따라서 C1에 Performance Guard를 넣어도 C1/C2가 같은 architecture가 되는 것은 아니다.


## 7. Architecture Trade-off & Selection Rationale

이 비교의 목적은 C1/C2 중 하나가 모든 지표에서 이기는지를 증명하는 것이 아니다.  
두 구조가 **어떤 정보와 복잡도를 추가로 사용하고, 그 대가로 어떤 최적화 기회를 얻는지**를 명확히 하는 것이 핵심이다.

| 관점 | C1-R2 — Resource-centric | C2-R2 — Data-centric |
|---|---|---|
| **핵심 장점** | 구조가 단순하고 Resource pressure에 직접 반응 | Data/Operation 특성을 이용해 더 정교한 Placement 가능 |
| **Decision input** | Capacity / BW / Latency / Capability | C1 정보 + Data Type + Hotness / Reuse / Lifetime |
| **Runtime monitoring** | **작음** — object-level behavior 추적 불필요 | **큼** — object별 access/reuse 상태 유지 필요 |
| **Decision overhead** | **낮음** | 상대적으로 높음 |
| **State / Metadata overhead** | **낮음** | 상대적으로 높음 |
| **Prediction dependency** | **낮음** — Resource trend 위주 | **높음** — Runtime behavior prediction 사용 |
| **Prediction error robustness** | **높음** — Data behavior 오예측 영향이 작음 | 상대적으로 민감하므로 Guard 필요 |
| **Resource pressure 대응** | **직접적이고 설명하기 쉬움** | Data lifecycle까지 고려해 선택적으로 대응 |
| **Data-near Compute 활용** | 제한적 — capability/static cost 수준 | **강점** — Data/Operation path와 직접 연결 |
| **RAG / Agent / KV별 차별화** | 제한적 | **강점** |
| **Modifiability** | **높음** — 모듈/상태가 적고 확장 영향이 작음 | 상대적으로 낮음 — Data model/monitor/path model 동시 변경 가능 |
| **설명 가능성** | **높음** — “Resource가 부족해 이동” | 더 복잡함 — “이 Data/Operation에는 이 Path가 유리” |
| **적합 환경** | 단순한 Tiering, Resource balancing, 낮은 Runtime overhead가 중요한 환경 | AI Data 종류와 near-memory capability가 다양하고 최적화 폭이 큰 환경 |

### C1-R2를 선택할 논리

다음이 우선이면 C1-R2가 더 자연스럽다.

- Memory Tier 간 **Capacity/BW pressure 관리 자체가 핵심 문제**
- Runtime에서 Data object별 behavior state를 유지하고 싶지 않음
- 낮은 decision/monitoring overhead가 중요
- Predictability와 단순한 운영이 중요
- 새로운 Data Type이 추가될 때 Placement logic 변경을 최소화하고 싶음

즉:

> **“무슨 Data인지보다 현재 어느 Resource가 여유 있는지가 더 중요하다”**

는 시스템이면 C1-R2가 적합하다.

### C2-R2를 선택할 논리

다음이 우선이면 C2-R2가 더 자연스럽다.

- KV / RAG / Agent Memory / LoRA / MoE처럼 **Data별 access/execution 특성이 크게 다름**
- CXL-PNM / Custom HBM / SSD-PIM처럼 **Tier별 Compute Capability가 다름**
- 같은 Memory Tier라도 `HBM Direct / Near-compute / Restore / Stage`처럼 실행 Path가 달라짐
- Data-near Compute를 실제 end-to-end 성능 이득이 있을 때만 사용해야 함
- Long-lived / cold / reuse-sensitive Data를 Runtime behavior에 따라 다르게 배치할 필요가 있음

즉:

> **“Resource 상태만으로는 어떤 Tier가 좋은지 결정할 수 없고, Data와 Operation을 같이 봐야 한다”**

는 시스템이면 C2-R2가 적합하다.

### DP1 최종 선택 근거

DP1의 목표가 단순 Memory balancing이 아니라 **AI Data를 heterogeneous Memory/Compute Tier에 배치하는 Runtime architecture**라는 점을 기준으로 하면, 최종 후보는 **C2-R2**로 두는 것이 논리적이다.

선택 이유는 “모든 수치에서 C2가 더 좋았기 때문”이 아니다.

핵심 이유는 다음과 같다.

1. **AI Data 종류별 특성이 다르다.** KV, RAG, Agent Memory, LoRA/MoE를 동일한 Resource score만으로 다루면 최적화 기회를 놓친다.
2. **Memory Tier마다 가능한 Operation이 다르다.** SSD-PIM의 GEMV, CXL/Custom-HBM의 near-memory Attention처럼 Placement와 Execution Path가 연결된다.
3. **DP1의 차별화 포인트가 Data-aware Placement다.** 단순 Resource balancing만 필요하면 C1 구조로 충분하지만, AI Runtime 관점의 확장성은 C2가 더 크다.
4. **C2의 단점은 명확하고 관리 가능하다.** Monitoring overhead, metadata, prediction error, implementation complexity가 대가이며 Performance Guard와 modular design으로 제한한다.

따라서 의사결정은 다음 한 문장으로 정리할 수 있다.

> **C1은 단순하고 robust한 Resource-centric 대안이지만, DP1은 AI Data와 Operation 특성에 따라 heterogeneous Memory/Compute Tier를 활용하는 것이 핵심이므로 C2-R2를 최종 Architecture로 선택한다.**

이때 C1-R2는 버리는 설계가 아니라 **baseline / simpler alternative**로 남겨 두어, C2가 추가하는 Data awareness의 비용과 효과를 설명하는 비교 기준으로 사용한다.

## 7. Measurement Boundary

- SLO / Admission / Autoscaling target은 상위 serving layer의 책임이며 DP1 Performance QA에는 사용하지 않는다.
- TTFT는 network/HTTP가 아니라 model/runtime first-token readiness다.
- Migration execution 자체는 DP4 범위이며 여기서는 path-cost proxy를 포함한다.
