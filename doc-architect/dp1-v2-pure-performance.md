# DP1 V2 Evaluation — Pure System Performance

> Source run: GitHub Actions `35332171648`
>
> Performance QA는 serving SLO를 사용하지 않는다. 동일 HW / 동일 trace / 동일 offered load에서 As-Is 대비 순수 system performance를 비교한다.
>
> Throughput은 높을수록, TTFT/TPOT은 낮을수록 좋다. Load sweep은 각 `(scenario, seed)` 내부에서 먼저 geometric mean으로 묶은 뒤 scenario-seed 단위로 aggregate한다.
>
> Architecture-level simulation이며 실제 B200/vLLM 실측 benchmark가 아니다.

## 1. QA 평가표

| QA | C1-R2 | C2-R2 | As-Is 대비 ratio |
|---|:---:|:---:|---|
| **Performance Throughput — Overall** | **★☆☆** | **★★☆** | C1 0.729× [0.653, 0.815]; C2 0.994× [0.983, 1.005] |
| **Performance Throughput — C1 유리 Case** | **★☆☆** | **★★☆** | C1 0.876× [0.819, 0.938]; C2 1.002× [1.000, 1.003] |
| **Performance Throughput — C2 유리 Case** | **★☆☆** | **★★☆** | C1 0.518× [0.372, 0.722]; C2 1.011× [0.988, 1.034] |
| **Performance Latency — TTFT — Overall** | **★☆☆** | **★☆☆** | C1 1.254× [1.105, 1.423]; C2 1.306× [1.052, 1.622] |
| **Performance Latency — TTFT — C1 유리 Case** | **★★☆** | **★★☆** | C1 1.152× [0.801, 1.656]; C2 1.709× [0.815, 3.583] |
| **Performance Latency — TTFT — C2 유리 Case** | **★☆☆** | **★★☆** | C1 1.215× [1.066, 1.383]; C2 0.931× [0.832, 1.041] |
| **Performance Latency — TPOT — Overall** | **★☆☆** | **★☆☆** | C1 3.444× [2.532, 4.685]; C2 1.184× [1.088, 1.289] |
| **Performance Latency — TPOT — C1 유리 Case** | **★☆☆** | **★★☆** | C1 3.636× [2.808, 4.708]; C2 1.000× [1.000, 1.000] |
| **Performance Latency — TPOT — C2 유리 Case** | **★☆☆** | **★☆☆** | C1 6.264× [2.432, 16.135]; C2 1.392× [1.159, 1.673] |
| **Resource Utilization — Overall** | **★★★** | **★★☆** | RUI C1 0.859; C2 0.756 |
| **Modifiability — Overall** | 재산정 필요 | 재산정 필요 | R2 구조 기준 별도 측정 필요 |

### 별점 기준

- Throughput: ≥1.10× and CI lower ≥1.0 → ★★★; 0.90~1.10 또는 CI가 1 포함 → ★★☆; <0.90× and CI upper <1.0 → ★☆☆
- TTFT/TPOT: ≤0.90× and CI upper ≤1.0 → ★★★; 0.90~1.10 또는 CI가 1 포함 → ★★☆; >1.10× and CI lower >1.0 → ★☆☆

## 2. Case Group

**C1 유리 Case — Resource-pressure 중심**

- `hbm_pressure_ramp_b64`
- `hbm_bw_shock_b256`
- `host_path_pressure_b64`
- `data_mix_shift_b64`
- `mixed_all_ai_data_b64`

**C2 유리 Case — Data-aware / Data-near / Lifecycle 중심**

- `kv_b16_c32k_burst_chbm`
- `kv_b1_c32k_cold_cxl`
- `kv_mispredict_dram_wait`
- `agent_memory_long_lived`
- `rag_8tib_b64_ssd_pim`
- `rag_8tib_b256_ssd_pim`

## 3. 왜 C1 Case에서 C2 Performance가 더 좋을 수 있는가

C1 Case는 C1이 실제 winner라는 뜻이 아니라 **Resource-centric mechanism이 필요해지는 workload group**이라는 뜻이다.

현재 C1-R2 Emergency Pressure Policy는 HBM pressure relief를 우선한다. KV를 Custom HBM/CXL/restore path로 이동하면 HBM pressure와 RUI는 좋아질 수 있지만, remote Attention, activation round-trip, restore 비용이 TPOT critical path에 들어가면서 Throughput/TPOT가 악화될 수 있다.

반면 C2-R2는 Data/Operation path cost와 Performance Guard를 사용한다. Offload가 end-to-end performance에 손해면 HBM/As-Is path를 유지한다. 따라서 Resource를 덜 적극적으로 분산해도 Throughput/TPOT를 더 잘 보존할 수 있다.

즉 현재 결과는 Resource-centric C1 철학 자체의 문제라기보다, **C1-R2 Emergency objective가 pressure relief에 치우치고 execution/service-time cost가 충분히 강하게 들어가지 않은 구현 문제**를 보여준다.

## 4. Measurement Boundary

- SLO / Admission / Autoscaling target은 상위 serving layer의 책임이며 DP1 Performance QA에는 사용하지 않는다.
- TTFT는 network/HTTP가 아니라 model/runtime first-token readiness다.
- Migration execution 자체는 DP4 범위이며 여기서는 path-cost proxy를 포함한다.
