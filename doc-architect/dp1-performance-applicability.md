# DP1 Performance Applicability Matrix

> 목적: C1/C2 후보를 **As-Is 대비 Performance가 실제로 좋아지는 workload domain**과 그렇지 않은 domain으로 나누어 본다.
>
> 원칙:
> 1. 모든 scenario를 실행한다.
> 2. 결과를 본 뒤 유리한 scenario만 남기지 않는다.
> 3. Target Domain은 architecture mechanism으로 사전 정의한다.
> 4. scenario별 Goodput / TTFT / TPOT을 모두 보여주고 WIN / TRADE-OFF / LOSS / STRESS로 분류한다.
>
> 기준 데이터: C1/C2 baseline 및 C1-R/C2-R reinforcement run.

---

# 1. 왜 All-scenario Aggregate 하나만 보면 안 되는가

As-Is HBM-first는 working set이 HBM에 잘 들어가고 별도 memory-side compute가 필요 없는 workload에서는 매우 강한 baseline이다.

반대로 DP1 후보의 목적은 다음과 같은 상황이다.

- HBM capacity/BW pressure
- large cold data
- heterogeneous memory tier
- SSD-PIM / Custom HBM / CXL-PNM의 data-near compute opportunity
- long-lived / reuse-sensitive AI Data

따라서 후보 구조의 의미는:

```text
모든 workload에서 무조건 As-Is를 이김
```

이 아니라:

```text
Target Domain에서는 As-Is보다 Performance 개선
Neutral Domain에서는 As-Is에 수렴
Adverse Domain에서는 잘못된 offload를 피함
Stress Domain에서는 HW/SLO feasibility boundary를 명확히 보고
```

로 검증해야 한다.

V2에서는 이를 위해 Performance Guard / Baseline Bypass를 추가한다.

---

# 2. 판정 기준

Performance는 합성 score 하나로 만들지 않는다.

- Max Sustainable SLO Goodput
- TTFT p99
- TPOT p99

을 각각 본다.

## WIN

- Goodput이 As-Is보다 의미 있게 높거나
- throughput을 거의 유지하면서 TTFT/TPOT가 의미 있게 좋아짐.

## TRADE-OFF

예:

- Goodput은 약간 낮지만 TTFT가 크게 개선
- Goodput은 높지만 TPOT가 악화

## NEUTRAL

As-Is와 실질적으로 유사.

## LOSS

Architecture가 의도한 mechanism을 사용했지만 Goodput/Latency가 전반적으로 악화.

## STRESS / INFEASIBLE

모든 후보의 SLO Goodput이 0. Policy winner를 정하지 않고 HW/SLO boundary로 본다.

---

# 3. 현재 Feasible Scenario Matrix

Goodput은 각 후보의 Max Sustainable SLO Goodput을 As-Is로 나눈 값이다.  
TTFT/TPOT는 nominal load에서 As-Is 대비 배수다. 값이 **1보다 작으면 latency 개선**이다.

| Scenario | Domain | C1 Goodput | C1 TTFT | C1 TPOT | C1 판정 | C2 Goodput | C2 TTFT | C2 TPOT | C2 판정 |
|---|---|---:|---:|---:|---|---:|---:|---:|---|
| `kv_b16_c32k` | Neutral / HBM-fit | 1.000 | 1.00× | 1.00× | NEUTRAL | 1.000 | 1.00× | 1.00× | NEUTRAL |
| `rag_1tib_b16` | Neutral / HBM-fit | 1.000 | 1.00× | 1.00× | NEUTRAL | 1.000 | 1.00× | 1.00× | NEUTRAL |
| `tool_result_bursty` | Neutral / HBM-fit | 1.000 | 1.00× | 1.00× | NEUTRAL | 1.000 | 3.79× | 1.00× | LOSS — C2 first-response overhead |
| `rag_8tib_b64_ssd_pim` | C2 Data-near Compute | 1.000 | 0.92× | 1.00× | TRADE-OFF / slight TTFT gain | 0.957 | **0.35×** | 1.00× | **TRADE-OFF — TTFT 큰 개선, Goodput -4.3%** |
| `kv_b16_c32k_burst_chbm` | C2 Data-near Compute | 0.139 | 1.82× | 4.40× | LOSS | 0.896 | 1.25× | 3.81× | LOSS — C1보다는 낫지만 As-Is 미달 |
| `kv_b1_c32k_cold_cxl` | C2 Data-near Compute / Negative Control | 1.000 | 1.00× | 1.00× | NEUTRAL | 0.249 | 6.47× | 54.41× | **LOSS — CXL offload를 선택하면 안 되는 케이스** |
| `kv_mispredict_dram_wait` | C2 Data-lifecycle | 0.389 | 1.95× | 7.30× | LOSS | 0.822 | 7.89× | 6.27× | LOSS — Resource headroom은 좋아지지만 Performance는 악화 |
| `agent_memory_long_lived` | C2 Data-lifecycle | 1.000 | 1.00× | 1.00× | NEUTRAL | 0.665 | 51.72× | 1.02× | LOSS |
| `classifier_error` | Robustness | 0.988 | 1.02× | 2.94× | Robustness regression | 0.982 | 52.67× | 1.00× | Robustness regression |

이 표에서 중요한 것은 **C2가 data-aware라는 이유만으로 모든 data-near scenario가 좋아지는 것이 아니라는 점**이다.

예:

```text
SSD-PIM RAG:
data-near GEMV benefit이 external traffic 감소를 이김
→ TTFT 개선

Cold KV on CXL-PNM:
remote Attention + activation/link cost가 benefit보다 큼
→ As-Is HBM path가 더 빠름
```

따라서 V2의 Performance Guard는 `kv_b1_c32k_cold_cxl` 같은 케이스에서 **CXL-PNM을 선택하지 않아야 한다.**

---

# 4. Reinforcement 이후 확인된 Performance Win

Baseline C1/C2만 보면 명확한 As-Is throughput superiority는 아직 부족했다.

그러나 보완 후 다음이 확인됐다.

## C1-R — 전체 Heavy Domain

```text
Heavy Goodput / As-Is
C1   ≈ 1.000
C1-R ≈ 1.064
```

즉 Resource-centric 접근은 migration stability를 보완한 뒤 **heavy aggregate에서 As-Is보다 약 6.4% 높은 Goodput**을 냈다.

## C2-R — Large RAG / SSD-PIM

`rag_8tib_b64_ssd_pim`에서:

```text
C2 baseline Goodput / As-Is ≈ 0.957
C2-R Goodput / As-Is       ≈ 1.193
```

동시에 TTFT도 As-Is보다 크게 낮다.

따라서 현재 가장 명확한 C2 target-domain performance evidence는:

> **대용량 SSD-resident Vector DB + SSD-PIM GEMV similarity**

이다.

---

# 5. Stress / Feasibility Scenario

다음 scenario는 현재 모든 후보의 SLO Goodput이 0인 영역이다.

- `data_mix_shift_b64`
- `hbm_bw_shock_b256`
- `hbm_pressure_ramp_b64`
- `host_path_pressure_b64`
- `kv_b256_c128k_burst`
- `kv_b256_c512k_stress`
- `kv_b64_c128k_cold`
- `kv_b64_c512k_long`
- `kv_rag_b64_c128k`
- `lora_multi_tenant_b64`
- `mixed_all_ai_data_b64`
- `moe_expert_skew_b256`
- `rag_8tib_b256_ssd_pim`
- `six_tier_capacity_stress`

이 영역은 “C1/C2 중 누가 더 좋은가”를 throughput ratio로 판단하지 않는다.

대신 다음을 본다.

- 어느 resource가 feasibility boundary를 만드는가
- TTFT 또는 TPOT 중 무엇이 SLO를 깨는가
- 다른 tier / data-near compute가 failure boundary를 얼마나 이동시키는가
- upper scheduler/autoscaler로 어떤 feedback이 필요한가

---

# 6. V2에서 원하는 결과 형태

다음 V2 재평가에서 후보별로 다음 세 결과를 동시에 만들어야 한다.

## 6.1 Target-domain Performance

```text
C1-R2:
Resource-pressure target domain에서 As-Is보다 Goodput 개선

C2-R2:
Data-near / Data-lifecycle target domain에서
Goodput 또는 TTFT/TPOT를 As-Is보다 개선
```

## 6.2 Neutral-domain No-regression

```text
No special benefit
      ↓
Performance Guard
      ↓
As-Is / HBM-first path
      ↓
Performance ≈ As-Is
```

## 6.3 Negative-control Rejection

예:

`kv_b1_c32k_cold_cxl`

C2-R2가 CXL-PNM offload를 계속 선택해서 As-Is보다 느리면 실패다.

V2에서는:

```text
Predicted CXL path > HBM-first cost
        ↓
Baseline Bypass
        ↓
HBM 유지
```

가 되어야 한다.

---

# 7. 최종 후보 선택 방식

최종 보고서는 한 개의 aggregate 숫자만 보고 선택하지 않는다.

```text
All scenarios
    ↓
┌────────────────────────────┐
│ Target-domain WIN          │
│ Neutral-domain NO-REGRESS  │
│ Adverse-domain BYPASS      │
│ Stress-domain BOUNDARY     │
└────────────────────────────┘
    ↓
Performance Trade-off Matrix
    ↓
Resource Utilization / Modifiability 비용을 함께 비교
```

즉 후보 선택의 질문은:

> **“C1/C2가 평균적으로 몇 점인가?”**

보다:

> **“어떤 workload에서 As-Is보다 확실히 빠르고, 어떤 workload에서는 As-Is로 안전하게 수렴하며, 그 대가로 Resource/Complexity에서 무엇을 지불하는가?”**

가 되어야 한다.
