# DP1 C1/C2 Architecture Evaluator

현재 DP1 설계(`dp1-data-placement-design.md`, `dp1-data-placement-uml-rendered.md`)의 두 후보를 동일 trace에서 비교하는 **architecture-level discrete-time simulator**다.

- **C1 — Memory-centric**: `Telemetry Collector → Resource State Monitor → Candidate Builder → Memory State View → Resource-aware Placement`
- **C2 — Data-centric**: `Data Classifier + Runtime State Monitor → Data Characteristic Interpreter → Tier Affinity Evaluator → Memory Tier Selector`

## Scope

이 evaluator는 KV Cache만 대상으로 하지 않는다. DP1 문서의 AI Runtime Data를 모두 포함한다.

- `KV_CACHE`
- `RAG_DATA`
- `AGENT_MEMORY`
- `TOOL_RESULT`
- `LOG_DATA`
- `LORA_ADAPTER`
- `MOE_EXPERT`

또한 `memories_default.json`의 6개 target tier를 모두 사용한다.

- `hbm`
- `custom_hbm`
- `cxl_pnm`
- `dram`
- `hbf`
- `ssd_pim`

실제 run 결과에서도 C1/C2 모두 6개 tier에 placement decision이 발생하는지 검증한다.

## Common QA basis

최종 QA 별점은 `../evaluation-criteria.md`의 **DP1~DP4 공통 기준**만 사용한다.

1. Performance Throughput
2. Performance Latency
3. Resource Utilization
4. Modifiability

별도 evaluator가 임의의 QA threshold를 만들지 않는다. fault-injection / infeasible-capacity / six-tier coverage stress는 trade-off 분석에는 포함하지만 정상 운용 QA 별점에는 넣지 않는다.

## Inputs

기본값은 다음 repository configuration을 직접 읽는다.

- `../configs/memories_default.json`
- `../configs/clusters.json` → `b200_8gpu`
- `../configs/models.json` → `llama_3_1_70b`

## Scenario suite

20개 scenario × 5 seeds × 2 candidates = **200 candidate runs**.

대표 시나리오:

- stable hot KV
- KV + RAG mixed
- RAG hot/cold index
- long-lived Agent Memory
- bursty Tool Result
- append-heavy AI runtime / Agent execution Log
- Multi-LoRA
- MoE expert skew
- all-AI-data coexistence
- HBM capacity ramp / BW shock
- host-path pressure / resource oscillation
- hotness flip / data-mix shift
- long context
- cold archive reactivation
- classifier error fault injection
- capacity crunch
- six-tier stress

`runtime_log_append`는 **SST/SSTable이 아니다.** DP1의 `Tool Result / Runtime Log` 범주 중 AI runtime/agent execution log를 모델링한다. SSTable은 storage-engine 내부 자료구조이므로 DP1 AI Runtime Data로 취급하지 않는다.

## Run

```bash
cd doc-architect/dp1_eval
python run_eval.py
```

출력:

- `out/results_runs.csv`
- `out/results_summary.json`
- `out/scenario_manifest.json`
- `out/dp1-qa-evaluation.md`

## Tests

```bash
cd doc-architect/dp1_eval
python -m unittest -v test_eval.py
```

7개 test가 config 6-tier 로딩, 7종 AI Data coverage, six-tier scenario, C1 resource prediction, C2 classifier, deterministic trace, Runtime Log의 non-SST 의미를 확인한다.

## Important modeling rules

1. **Same trace**: 같은 `(scenario, seed)`에서 C1/C2가 같은 object trace를 사용한다.
2. **Current design only**: 기존 `../dp1_sim/`은 과거 KV-centric 설계를 검증한 코드이므로 현재 C1/C2 최종 QA 별점에는 사용하지 않는다.
3. **DP4 boundary**: migration mechanism 자체는 구현하지 않는다. tier 변경 시 idealized path cost의 20%만 다음 access critical path에 반영한다.
4. **Modifiability token**: 실제 API usage가 아니라 공통 기준의 static source read/write token estimate(char/3.6)를 사용한다.
5. **Absolute vs relative**: config의 ASSUMED 값 때문에 절대값보다 동일 trace의 후보 간 차이와 failure mode를 더 신뢰한다.
