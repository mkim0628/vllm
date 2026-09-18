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

23개 scenario × 5 seeds × 3 policies(As-Is/C1/C2) × 5 offered-load scales를 실행한다. Throughput은 load sweep에서 얻은 **Max Sustainable SLO Goodput**으로 평가한다.

대표 시나리오:

- KV batch 16/64/256 + context 32K/128K/512K
- Cold KV on CXL-PNM and burst KV on Custom HBM attention offload
- 1 TiB / 8 TiB RAG vector index + SSD-PIM GEMV similarity path
- long-lived Agent Memory / bursty Tool Result
- Multi-LoRA / MoE expert skew
- mixed all-AI-data coexistence
- HBM capacity ramp / BW shock / host-path pressure
- classifier error fault injection + C2 Safe Fallback
- prediction error + HBM relief + DRAM deferred-promotion recovery
- six-tier capacity stress

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

Unit test는 config 6-tier 로딩, primary AI Data coverage, large-batch/long-context 존재, SSD-PIM RAG primitive 경계, Custom HBM/CXL-PNM Attention 지원, C2 fallback, deterministic trace를 확인한다.

## Important modeling rules

1. **Same trace**: 같은 `(scenario, seed, load_scale)`에서 As-Is/C1/C2가 같은 object trace를 사용한다.
2. **Current design only**: 기존 `../dp1_sim/`은 과거 KV-centric 설계를 검증한 코드이므로 현재 C1/C2 최종 QA 별점에는 사용하지 않는다.
3. **DP4 boundary**: migration mechanism 자체는 구현하지 않는다. tier 변경 시 idealized path cost의 20%만 다음 access critical path에 반영한다.
4. **Latency split**: network transport는 모델링하지 않으므로 first-response metric은 TTFT다. TTFT와 TPOT은 별도 별점으로 보고 하나로 합치지 않는다.
5. **Operation-aware placement**: KV Attention은 Custom HBM/CXL-PNM에서 수행 가능하되 FFN은 GPU에 남고 activation round-trip을 포함한다. SSD-PIM은 GEMV만 지원하며 SSD-resident Vector DB의 similarity 계산에만 사용한다. similarity score 이후 ranking/top-k는 controller/host 후처리다.
4. **Modifiability token**: 실제 API usage가 아니라 공통 기준의 static source read/write token estimate(char/3.6)를 사용한다.
5. **Absolute vs relative**: config의 ASSUMED 값 때문에 절대값보다 동일 trace의 후보 간 차이와 failure mode를 더 신뢰한다.


## Evaluation history

DP1 후보 비교는 결과를 덮어쓰지 않고 단계별로 보존한다.

1. `../dp1-c1-c2-baseline-assessment.md`
   - 최초 C1/C2 비교 결과 동결
   - C2 fallback/migration storm 발견

2. `../dp1-reinforcement-design.md`
   - C1-R / C2-R 1차 보완 설계
   - C1-R: hysteresis / minimum residency / migration benefit gate
   - C2-R: feasibility-first / cooldown / stable fallback

3. `../dp1-reinforcement-evaluation.md`
   - 동일 workload에서 before/after 재평가
   - C1-R migration -88.5%
   - C2-R fallback -81.2%, migration -76.5%, heavy-goodput +10.2%

4. `../dp1-reinforcement-v2-design.md`
   - C1-R2: emergency pressure escape
   - C2-R2: explicit infeasibility state / low-confidence envelope / pressure override

Reinforcement 재현:

```bash
cd doc-architect/dp1_eval
python run_reinforcement.py
```

출력:

- `out_reinforcement/reinforcement_runs.csv`
- `out_reinforcement/reinforcement_summary.json`
- `out_reinforcement/dp1-reinforcement-evaluation.md`

- `../dp1-reinforcement-uml-rendered.md` — C1-R/C2-R 보완 구조도 및 sequence diagram
