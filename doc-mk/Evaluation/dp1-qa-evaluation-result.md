# DP1 QA Evaluation — C1 vs C2 (simulation, 1st pass)

> 기준 문서: `doc-mk/Evaluation/qa-evaluation-criteria.md`, `doc-mk/Evaluation/dp1-simulation-plan.md`
> 대상 구조: DP1 개정안 (Resource Manager + 공통 Memory Backend I/F, 슬라이드 8~10 기준)
> 도구: `doc-mk/DP1/dp1_sim` (`python qa_eval.py`, 결과: `out_qa/qa_result.json`)
>
> **이 결과는 모두 Evidence [B+C] (config parameter 기반 simulation)이며 [A] 실측이 아니다.**
> 최종 별점으로 쓰기 전에 아래 "한계"를 반드시 확인한다.

---

# 1. 평가 방법과 평가 룰 적용

| 항목 | 적용 |
|---|---|
| 후보 | C1, C2, 그리고 **Common Reference Baseline = Baseline-static** (As-Is proxy: 공통 initial placement 후 migration 없음, tier 순서 고정) |
| Workload | **Common Benchmark** — Llama-3.1-70B BF16, **8K input / 256 output**, deterministic trace (`scenarios.common_benchmark()` 3종). HBM을 축소해(`hbm_capacity_mult` 0.12~0.2) 계층이 실제로 영향을 주게 함 |
| 보조 Workload | **DP1 Stress Benchmark** — 기존 23개 시나리오 (진단용, 별점 산정에 쓰지 않음) |
| Load sweep | offered load ×0.5 / 1.0 / 1.5 / 2.0 |
| 반복 | seed 5개 (11, 23, 37, 53, 71), 평균과 95% CI (t=2.776), CV 기록 |
| QA1 | Max SLO Goodput (sweep 최대, token/s), `T_ref` = Baseline. 시나리오별 비율의 geometric mean으로 별점 |
| QA2 | Max Goodput load point의 TTFT P99 / TPOT P99. 시나리오 중 **worst-case**로 별점 (룰: 둘 중 낮은 등급) |
| QA3 | Useful Utilization = `avg HBM occupancy × (SLO 만족 token / served token)`. (룰에 formula가 없어 본 평가에서 **임시 정의**) |
| QA4 | architecture argument (§5) |
| Threshold | 룰 문서 값을 결과를 본 뒤 조정하지 않음 |

시뮬레이터 변경(이번 평가를 위해 추가): `Baseline-static` 정책, `common_benchmark()` 시나리오, `qa_eval.py`.
기존 C1/C2 decision 로직은 변경하지 않았다.

---

# 2. 최종 결과 (Common Benchmark)

| QA | Baseline (T_ref) | C1 | C2 |
|---|---|---|---|
| QA1 Throughput | ★★ ×1.000 [B+C] | ★★ ×0.905 [B+C] | ★★ ×0.998 [B+C] |
| QA2 Latency | ★★★ TTFT 337 ms / TPOT 5 ms [B+C] | ★ TTFT 568 ms / TPOT 311 ms [B+C] | ★★ TTFT 449 ms / TPOT 71 ms [B+C] |
| QA3 Resource Util. | ★ 44% [B+C] | ★ 37% [B+C] | ★ 50% [B+C] |
| QA4 Modifiability | — | ★★★ [C] | ★★ [C] |

- QA1은 어느 후보도 baseline을 10% 이상 넘지 못해 모두 ★★이다. C1은 ×0.905로 ★★ 경계(0.90) 바로 위다.
- QA3는 세 후보 모두 ★(<65%)이다. 이는 HBM occupancy 자체가 40~50%대인 시나리오 구성의 영향이 크다.
- 괄호 없는 숫자는 모두 시뮬레이션 값이다.

## 시나리오별 (Max SLO Goodput, token/s)

| 시나리오 | Baseline | C1 (비율) | C2 (비율) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) |
|---|---:|---:|---:|---|---|
| cb_kv_8k_b32 | 3,578 (±192) | 3,093 (×0.86) | 3,578 (×1.00) | 337 / 568 / 154 | 5 / 311 / 12 |
| cb_kv_8k_b32_ramp | 3,595 (±41) | 3,332 (×0.93) | 3,586 (×1.00) | 318 / 514 / 131 | 5 / 311 / 71 |
| cb_mixed_8k_b32 | 2,641 (±308) | 2,440 (×0.92) | 2,632 (×1.00) | 329 / 541 / 449 | 5 / 251 / 12 |

95% CI는 baseline 기준 ±1~12% (CV 1~10%)이다. C1이 baseline보다 낮은 차이는 `cb_kv_8k_b32`(×0.86)와 `cb_kv_8k_b32_ramp`(×0.93)에서는 CI를 넘어 구분되지만, `cb_mixed_8k_b32`(×0.92)는 CI와 겹쳐 통계적으로 구분되지 않는다. C2와 baseline의 차이는 모든 시나리오에서 CI 안이다.

## Diagnostic

| 지표 (평균) | Baseline | C1 | C2 |
|---|---:|---:|---:|
| migration 횟수 | 0 | 110 | 389 |
| migration bytes (GiB) | 0 | 1,266 | 3,767 |
| decision overhead (ms/run) | 0.0 | 4.2 | 168.6 |
| pool util (전체 6 tier) | 3.7% | 3.5% | 4.1% |

---

# 3. DP1 Stress Benchmark (진단, 별점 없음)

23개 시나리오 중 **14개는 baseline goodput이 0**이다(512K context, 8 TiB RAG, batch 256 등 SLO 자체를 만족할 수 없는 구성). 이 시나리오에서는 C1/C2도 goodput을 만들지 못했다(rescued 0건).
baseline goodput > 0인 9개 시나리오에서 baseline 대비 geometric mean은 **C1 ×0.975, C2 ×0.949** 이다.

대표 관찰:

| 시나리오 | 관찰 |
|---|---|
| `rag_1tib_b16` | C2가 migration 34회, **3.4 TiB / 174 s 전송** (seed 11) → TTFT P99 **약 31~34 s** (baseline 83 ms) |
| `rag_8tib_b64_ssd_pim` | C1 ×0.89, C2 ×0.74 |
| `agent_memory_long_lived`, `behavior_flip_stress` | C2 TTFT P99가 3.0 s / 9.5 s로 급증 (C1은 baseline과 동일) |
| `kv_b16_c32k_burst_chbm` | C2 ×1.00, TPOT 19 ms. C1 ×0.94, TPOT **617 ms** |
| `hbm_pressure_ramp_b64`, `hbm_bw_shock_b256` | 세 후보 모두 goodput 0 (migration이 SLO 만족으로 이어지지 못함) |


---

# 4. 원인 분석 (진단 근거)

`cb_kv_8k_b32`, seed 11, load 1.0 기준:

| | tier별 access | migration | 비고 |
|---|---|---|---|
| Baseline | HBM 334, DRAM 889 | 0 | HBM 초과분은 DRAM(64 GB/s)에 얹힘. KV 복원 비용이 256 output token에 분산되어 TPOT 5 ms |
| C1 | HBM 334, DRAM 213, **HBF 428, CXL-PNM 147, Custom HBM 82, SSD-PIM 19** | 105회, 전부 **rebalance** (demotion 0) | HBM이 아니라 **DRAM pressure**(초기 배치가 DRAM을 90%까지 채움)에 반응해 KV를 6개 tier로 분산. CXL-PNM attention 경로는 batch 32에서 TPOT 311 ms |
| C2 | HBM 498, Custom HBM 690 | 342회 (promotion 167 / demotion 155), 3.8 TiB | 승격과 강등이 반복(churn). decision overhead 약 140 ms/run (C1 약 4 ms) |

해석:

1. **C1의 문제는 destination 선택에 serving 비용(해당 tier에서 접근할 때의 TPOT)이 들어가지 않는다는 점이다.** pressure와 affinity만 보기 때문에, 이동 후 더 느려지는 tier도 고른다. 구조(Resource Manager가 Destination Tier Selector에 capability와 transfer cost만 제공)에서 오는 한계이기도 하다. 접근 비용 model은 DP1 입력에 없다.
2. **C2는 prediction 기반으로 TPOT는 지켰지만(12~71 ms) migration churn과 overhead가 크다.** anti-thrashing(§26 항목 8: hysteresis, cooldown, migration budget)이 필요한 영역이다. cooldown 8 s만 있고 byte 기준 budget이 없어 대형 object(RAG 3.4 TiB)가 TTFT를 망친다.
3. **Baseline이 강한 이유는 비용 model 때문이기도 하다.** 시뮬레이터에서 DRAM에 둔 KV는 복원 비용이 출력 token 수로 amortize되어 매우 싸다. 실제 vLLM의 CPU offload는 이 가정이 성립하지 않을 수 있다([A] 실측 필요).
4. 위 두 결과는 migration layer 자체가 무익하다는 뜻이 **아니다**. 이 workload와 비용 model에서는 baseline의 정적 배치가 이미 충분히 좋아 이동 이득이 비용을 넘지 못했다는 뜻이다. 반대로 static 배치가 나쁜 경우(initial placement가 틀린 경우, 중간에 workload가 바뀌는 경우)의 이득은 이번 benchmark가 충분히 포함하지 못했다.

---

# 5. QA4 — Modifiability (architecture argument, [C])

변경 단위는 module 수. 신규 memory는 Memory Backend I/F(§5.8)가 있는 개정 구조 기준이다.

| 변경 시나리오 | C1 변경 module | C2 변경 module | 비고 |
|---|---|---|---|
| 신규 memory 추가 | Backend plug-in 1 (+ 필요 시 TransferHandler 1) = **≤2** → ★★★ | 동일 **≤2** → ★★★ | Selector/Monitor/Registry 무변경. C2 선호 tier를 memory 이름이 아닌 capability class로 두는 것이 전제 |
| 신규 AI data type 추가 | Affinity Table 항목 1 (Registry는 type-agnostic이라 무변경) = **1~2** → ★★★ | class metadata(Registry) + Behavior Monitor feature + Predictor prior + Destination 선호 = **4** → ★★ | C1은 type 분기 0건, C2는 type 참조 10곳 + tier 선호 6항목 (`policies.py` 기준) |
| 신규 정책(예: predictor) 교체 | Affinity/Eviction 정책 1 → ★★★ | Predictor 1 → ★★★ | |
| 신규 event type | Scheduler + Monitor = 2 → ★★★ | 동일 → ★★★ | |

**종합: C1 ★★★ [C], C2 ★★ [C]** (C2는 신규 data type이 4 module에 영향).
참고: 현재 simulator의 C2는 `TYPE_TIER_PREFERENCE`에 tier 이름을 직접 쓰므로, 설계 의도(capability class)대로 바꾸기 전에는 신규 memory에도 +1 module이 든다.

---

# 6. 한계 (결과 해석 전 필수)

1. **Evidence가 [A]가 아니다.** vLLM trace 기반 shadow 평가(Phase 3~4)를 하지 않았고 H100/A100 calibration도 없다. config 값에는 ASSUMED 항목(Vera Rubin FP16 등)이 포함된다.
2. **시뮬레이터가 개정 구조를 모델링하지 않는다.** Memory Backend I/F, Telemetry snapshot, capability class 기반 Selector는 구현되지 않았다. decision 로직은 개정 전 C1/C2와 같고, 개정 구조는 QA4에서만 반영된다. QA1~3은 "개정 구조가 성능을 바꾸지 않는다"는 가정 하의 값이다.
3. **QA1은 포화를 보지 못한다.** simulator에 queueing/saturation 모델이 없어 goodput이 load에 거의 비례한다. Max SLO Goodput이 항상 sweep 최대 load에서 나오므로 후보 간 비율만 의미가 있다.
4. **QA3 formula는 임시 정의**이며 HBM occupancy 기준이다. pool util(전체 6 tier)은 0.1 수준이라 룰의 65%/85% threshold를 적용할 수 없다.
5. **Common Benchmark가 3개 시나리오**뿐이고 HBM 축소 정도(0.12~0.2)가 결과에 영향을 준다. threshold를 바꾸지는 않았지만 시나리오 선택이 결과를 좌우할 수 있다.
6. DROP action(replica)은 이 평가에 포함하지 않았다.

---

# 7. 결론

- **현재 simulator + Common Benchmark 기준으로 C1, C2 모두 baseline 대비 성능 이득이 확인되지 않았다.** QA1은 모두 ★★, C2가 baseline과 동률(×0.998), C1이 약간 낮다(×0.905).
- **C2가 C1보다 낫다.** 같은 benchmark에서 TPOT P99는 C2 12~71 ms, C1 251~311 ms. 다만 C2의 비용(migration churn, decision overhead 약 140 ms/run, 대형 object TTFT 스파이크)은 크다.
- **Modifiability는 C1이 우위**(★★★ vs ★★).
- 따라서 지금 단계의 판단은 "C1/C2 중 하나를 고르기"보다 **(a) Destination Tier Selector에 접근 비용을 넣고, (b) migration budget/anti-thrashing을 넣은 뒤 재평가**하는 것이 맞다. 두 항목은 후보 선택과 무관한 공통 개선이다.

## 다음 단계

1. Destination Tier Selector의 serving-cost 입력 정의 (Memory Registry의 capability와 어떻게 결합할지)
2. migration byte budget / cooldown 개선 후 재평가 (§26 항목 8)
3. 개정 구조(Backend I/F, snapshot) 반영한 simulator 갱신
4. vLLM trace 수집 → shadow mode ([A]) 및 HBM↔DRAM 실측으로 cost model 검증
5. Common Benchmark 시나리오 확대와 queueing 모델 추가 (QA1 포화 관측)
