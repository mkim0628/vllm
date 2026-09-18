# DP1 V2 Evaluation — Pure System Performance

> DP1 Performance QA는 serving SLO를 사용하지 않는다.
>
> 동일 HW / 동일 trace / 동일 offered load에서 **As-Is 대비 순수 system performance**를 비교한다.
>
> - Throughput: 높을수록 좋음
> - TTFT / TPOT: 낮을수록 좋음
> - load sweep = `[0.25, 0.50, 0.75, 1.00, 1.25]`
> - 각 `(scenario, seed)` 내부에서 5개 load ratio를 먼저 geometric mean으로 묶고, 이후 scenario-seed 간 geometric mean + paired 95% CI를 계산한다.
>
> Architecture-level simulation이며 실제 B200/vLLM 실측 benchmark가 아니다.

---

## 1. QA 평가표

| QA | C1-R2 | C2-R2 | As-Is 대비 ratio |
|---|:---:|:---:|---|
| **Performance Throughput — Overall** | **★☆☆** | **★★☆** | C1 **0.729×** [0.653, 0.815] / C2 **0.994×** [0.983, 1.005] |
| **Performance Throughput — C1 유리 Case** | **★☆☆** | **★★☆** | C1 **0.876×** [0.819, 0.938] / C2 **1.002×** [1.000, 1.003] |
| **Performance Throughput — C2 유리 Case** | **★☆☆** | **★★☆** | C1 **0.518×** [0.372, 0.722] / C2 **1.011×** [0.988, 1.034] |
| **Performance Latency — TTFT — Overall** | **★☆☆** | **★☆☆** | C1 **1.254×** [1.105, 1.423] / C2 **1.306×** [1.052, 1.622] |
| **Performance Latency — TTFT — C1 유리 Case** | **★★☆** | **★★☆** | C1 **1.152×** [0.801, 1.656] / C2 **1.709×** [0.815, 3.583] |
| **Performance Latency — TTFT — C2 유리 Case** | **★☆☆** | **★★☆** | C1 **1.215×** [1.066, 1.383] / C2 **0.931×** [0.832, 1.041] |
| **Performance Latency — TPOT — Overall** | **★☆☆** | **★☆☆** | C1 **3.444×** [2.532, 4.685] / C2 **1.184×** [1.088, 1.289] |
| **Performance Latency — TPOT — C1 유리 Case** | **★☆☆** | **★★☆** | C1 **3.636×** [2.808, 4.708] / C2 **1.000×** [1.000, 1.000] |
| **Performance Latency — TPOT — C2 유리 Case** | **★☆☆** | **★☆☆** | C1 **6.264×** [2.432, 16.135] / C2 **1.392×** [1.159, 1.673] |
| **Resource Utilization — Overall** | **★★★** | **★★☆** | RUI: C1 **0.859**, C2 **0.756** |
| **Modifiability — Overall** | 재산정 필요 | 재산정 필요 | R2 구조 기준 별도 측정 필요 |

### 별점 기준

- **Throughput**: ≥1.10× + CI lower ≥1.0 → ★★★ / 0.90~1.10 또는 CI가 1 포함 → ★★☆ / <0.90× + CI upper <1.0 → ★☆☆
- **TTFT·TPOT**: ≤0.90× + CI upper ≤1.0 → ★★★ / 0.90~1.10 또는 CI가 1 포함 → ★★☆ / >1.10× + CI lower >1.0 → ★☆☆

---

## 2. Case Group

### C1 유리 Case — Resource-pressure 중심

- `hbm_pressure_ramp_b64`
- `hbm_bw_shock_b256`
- `host_path_pressure_b64`
- `data_mix_shift_b64`
- `mixed_all_ai_data_b64`

여기서 “C1 유리”는 **C1의 Resource-centric mechanism이 필요해지는 workload**라는 뜻이다. 결과를 보고 C1 winner인 scenario만 골라낸 것이 아니다.

### C2 유리 Case — Data-aware / Data-near / Lifecycle 중심

- `kv_b16_c32k_burst_chbm`
- `kv_b1_c32k_cold_cxl`
- `kv_mispredict_dram_wait`
- `agent_memory_long_lived`
- `rag_8tib_b64_ssd_pim`
- `rag_8tib_b256_ssd_pim`

---

## 3. 왜 C1 유리 Case에서 C2가 Throughput/TPOT가 더 좋은가

현재 C1-R2의 **Emergency Pressure Policy 목적함수가 resource pressure relief에 너무 치우쳐 있기 때문**이다.

C1-R2:

```text
HBM pressure >= high watermark
        ↓
HBM pressure를 낮추기 위해 object offload
        ↓
Custom HBM / CXL / restore path 사용
        ↓
HBM pressure, RUI 개선
        ↓
remote Attention / activation round-trip / restore cost 증가
        ↓
TPOT 증가 → Throughput 감소
```

즉 C1은 **“HBM이 덜 바쁜가?”는 잘 해결하지만, “request가 실제로 더 빨라졌는가?”를 Emergency path에서 충분히 강하게 보지 않는다.**

반면 C2-R2는 Data/Operation path cost와 Performance Guard를 사용한다.

```text
Offload candidate
        ↓
End-to-end cost vs HBM/As-Is
        ↓
느리면 offload하지 않음
```

그래서 C2는 Resource를 C1만큼 적극적으로 분산하지 않더라도 **TPOT와 Throughput을 보존하기 쉽다.**

따라서 현재 결과는 “Resource-centric C1의 개념이 틀렸다”는 의미가 아니라, **C1-R2 Emergency Policy에도 service-time / execution-cost 항을 Resource Utility에 포함해야 한다**는 의미다.

---

## 4. Measurement Boundary

- SLO / Admission / Autoscaling target은 상위 serving layer의 책임으로 보고 DP1 Performance QA에는 사용하지 않는다.
- TTFT는 network/HTTP가 아니라 model/runtime first-token readiness다.
- DP1은 Data Placement decision을 평가한다. 실제 migration mechanism/path scheduling은 DP4 범위이며 여기서는 migration/path cost proxy를 포함한다.
