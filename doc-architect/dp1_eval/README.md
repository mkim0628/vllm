# DP1 C1/C2 Architecture Evaluator

현재 DP1 설계(`dp1-data-placement-design.md`, `dp1-data-placement-uml-rendered.md`)의 두 후보를 동일한 환경에서 비교하기 위한 **architecture-level discrete-time simulator**다.

- **C1 — Memory-centric**: `Telemetry Collector → Resource State Monitor → Candidate Builder → Memory State View → Resource-aware Placement`
- **C2 — Data-centric**: `Data Classifier + Runtime State Monitor → Data Characteristic Interpreter → Tier Affinity Evaluator → Memory Tier Selector`

이 코드는 실제 vLLM 서버 벤치마크가 아니라 DP 후보 선택을 위한 설계 검증기다. 물리/토폴로지 입력은 기존 `../configs/`의 JSON을 직접 읽으며, 시나리오 trace는 후보와 무관하게 먼저 생성한다.

## Inputs

기본값은 다음 repository configuration을 그대로 사용한다.

- `../configs/memories_default.json`
- `../configs/clusters.json` → `b200_8gpu`
- `../configs/models.json` → `llama_3_1_70b`

## Run

```bash
cd doc-architect/dp1_eval
python run_eval.py \
  --seeds 11,23,37,51,71 \
  --output results.json \
  --report report.md
```

특정 시나리오만 실행하려면:

```bash
python run_eval.py \
  --scenarios classifier_error,hbm_bw_shock,mixed_hot_cold \
  --seeds 11,23,37,51,71
```

다른 config를 비교하려면 `--config-dir`, `--cluster`, `--model`을 사용한다.

## Tests

```bash
cd doc-architect/dp1_eval
python -m unittest -v test_eval.py
```

## Checked-in Results

- `results_runs.csv` — C1/C2 18 scenarios × 5 seeds = 180 candidate runs
- `oracle_runs.csv` — 동일 trace의 reference heuristic 90 runs
- `results_summary.json` — QA aggregate, 별점, scenario별 paired comparison
- `scenario_manifest.json` — scenario 목록과 seed
- `../dp1-qa-evaluation.md` — 평가 기준, 결과, 해석, 제한사항

## Important Modeling Rules

1. **Same trace**: 같은 `(scenario, seed)`에서 C1/C2/reference가 완전히 동일한 object trace를 사용한다.
2. **Current design only**: 기존 `../dp1_sim/`은 과거 KV-centric 구조의 실험 코드다. 본 디렉터리는 현재 Resource State Monitor / Data Classifier 구조를 기준으로 새로 작성했다.
3. **DP4 boundary**: migration mechanism은 구현하지 않는다. 이동 시간 proxy의 20%만 다음 request critical path에 노출시키고 나머지는 background overlap으로 둔다.
4. **No fabricated AI-token metric**: 이 실행 환경은 coding-agent token usage를 제공하지 않으므로 Modifiability의 AI Token Consumption은 `N/A`로 기록한다.
5. **Absolute vs relative**: config에는 ASSUMED 항목도 있으므로 절대 성능값보다 동일 trace에서의 C1/C2 상대 비교를 더 신뢰해야 한다.
