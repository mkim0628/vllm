# DP1 V2 Evaluation — Pure System Performance

> Source run: GitHub Actions `35335145731`
>
> Performance QA는 serving SLO를 사용하지 않는다. 동일 HW / 동일 trace / 동일 offered load에서 As-Is 대비 순수 system performance를 비교한다.
>
> Throughput은 높을수록, TTFT/TPOT은 낮을수록 좋다. Load sweep은 각 `(scenario, seed)` 내부에서 먼저 geometric mean으로 묶은 뒤 scenario-seed 단위로 aggregate한다.
>
> Architecture-level simulation이며 실제 B200/vLLM 실측 benchmark가 아니다.

## 1. QA 평가표

| QA | C1-R2 | C2-R2 | As-Is 대비 ratio |
|---|:---:|:---:|---|
| **Performance Throughput — Overall** | **★★☆** | **★★☆** | C1 **0.926×** [0.892, 0.960]; C2 **0.994×** [0.983, 1.005] |
| **Performance Throughput — C1 Target Case** | **★★☆** | **★★☆** | C1 **0.994×** [0.988, 1.001]; C2 **1.002×** [1.000, 1.003] |
| **Performance Throughput — C2 Target Case** | **★★☆** | **★★☆** | C1 **0.945×** [0.901, 0.992]; C2 **1.011×** [0.988, 1.034] |
| **Performance Latency — TTFT — Overall** | **★★☆** | **★☆☆** | C1 **0.984×** [0.867, 1.117]; C2 **1.306×** [1.052, 1.622] |
| **Performance Latency — TTFT — C1 Target Case** | **★★☆** | **★★☆** | C1 **0.664×** [0.428, 1.029]; C2 **1.709×** [0.815, 3.583] |
| **Performance Latency — TTFT — C2 Target Case** | **★★☆** | **★★☆** | C1 **1.075×** [0.961, 1.202]; C2 **0.931×** [0.832, 1.041] |
| **Performance Latency — TPOT — Overall** | **★☆☆** | **★☆☆** | C1 **1.645×** [1.403, 1.929]; C2 **1.184×** [1.088, 1.289] |
| **Performance Latency — TPOT — C1 Target Case** | **★☆☆** | **★★☆** | C1 **1.293×** [1.022, 1.637]; C2 **1.000×** [1.000, 1.000] |
| **Performance Latency — TPOT — C2 Target Case** | **★☆☆** | **★☆☆** | C1 **1.809×** [1.328, 2.465]; C2 **1.392×** [1.159, 1.673] |
| **Resource Utilization — Overall** | **★★☆** | **★★☆** | RUI C1 **0.809**; C2 **0.756** |
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

이 그룹에서 평균적으로:

- Performance bypass: **35.3회/run**
- Emergency 진입: **16.2회/run**
- 성능 손실 때문에 Emergency migration 차단: **12.2회/run**
- 실제 Emergency migration: **4.0회/run**

즉 Emergency가 발생했다고 무조건 offload하지 않고, **성능 손실이 큰 이동의 대부분을 차단**했다.

## 4. 왜 아직 C1 TPOT이 1.293×인가

Guard 적용으로 C1 Target Case TPOT은 **3.636× → 1.293×**까지 크게 개선됐지만 아직 As-Is보다 느리다.

남은 문제는 주로 mixed workload에서 발생한다.

- `data_mix_shift_b64`
- `mixed_all_ai_data_b64`

이런 workload에서는 KV뿐 아니라 LoRA/MoE/RAG/Agent data가 같이 움직이므로, Resource Utility와 실제 critical-path cost 사이의 approximation error가 아직 남아 있다.

따라서 다음 보완 포인트는 threshold를 더 느슨하게/빡빡하게 사후 tuning하는 것이 아니라:

> **C1 Resource Utility의 static execution-cost proxy를 실제 simulator critical-path model과 더 일치시키는 것**

이다.

## 5. C1과 C2의 차이는 유지된다

Performance Guard의 원칙은 동일하지만 입력 정보는 다르다.

| | C1-R2 | C2-R2 |
|---|---|---|
| Primary signal | Resource State | Data + Resource State |
| Runtime Data behavior | 사용 안 함 | Hotness / Reuse / Lifetime |
| Performance Guard | Static resource/execution cost | Data/Operation-aware path cost |
| Emergency/Pressure 대응 | Resource pressure relief + Guard | Data-aware path selection + Guard |

따라서 C1에 Performance Guard를 넣어도 C1/C2가 같은 architecture가 되는 것은 아니다.

## 6. Measurement Boundary

- SLO / Admission / Autoscaling target은 상위 serving layer의 책임이며 DP1 Performance QA에는 사용하지 않는다.
- TTFT는 network/HTTP가 아니라 model/runtime first-token readiness다.
- Migration execution 자체는 DP4 범위이며 여기서는 path-cost proxy를 포함한다.
