# Evaluation

DP1~DP4의 평가 기준, benchmark, 시스템 프로파일, simulation, 결과를 관리하는 폴더.

> **평가 작업은 반드시 `.claude/skills/evaluation/SKILL.md`(repo root 기준)를 따른다.** 폴더 규칙 요약은 `CLAUDE.md`.

## 폴더 구조

~~~text
doc-mk/Evaluation/
├── README.md                    # 이 문서
├── CLAUDE.md                    # 이 폴더 작업 규칙
├── qa-evaluation-criteria.md    # 공통 QA1~4, 별점, Evidence A/B/C (DP1~DP4 공통)
├── common-benchmark.md          # 공통 benchmark profile, baseline(T_ref), sweep/반복 규칙
├── system-specs.md              # 메모리 세대별 시스템 프로파일 SYS-A100/H100/B200/VR (+legacy SYS-1..5, 일부 자동 생성)
├── result-template.md           # 결과 문서 템플릿
├── tools/
│   ├── gen_system_specs.py      # system-specs.md 생성 블록 렌더
│   ├── gen_dp1_benchmark_doc.py # DP1/benchmark.md 생성 블록 렌더
│   └── gen_dp1_result.py        # DP1 통합 결과 문서 생성 (results/data/SYS-*/qa_result.json -> 표)
├── DP1/                         # AI Data Migration
│   ├── simulation-plan.md       # 평가/시뮬레이션 방법
│   ├── benchmark.md             # DP1 맞춤형 benchmark (시나리오 표 자동 생성)
│   ├── qa-criteria-dp1.md       # DP1 보조 평가 기준 (세부 tier, 집계, C1 vs C2 직접 비교)
│   ├── results/                 # 결과 문서 (YYYY-MM-DD_<topic>.md), data/ (qa_result.json), iterations/ (loop-log.md)
│   └── sim/                     # simulator (scenarios.py, policies.py, simulator.py, qa_eval.py, configs/)
├── DP2/  README.md, benchmark.md (TBD), results/
├── DP3/  README.md, benchmark.md (TBD), results/
└── DP4/  README.md, benchmark.md (TBD), results/
~~~

## 읽는 순서

1. `qa-evaluation-criteria.md` — 무엇을 어떤 기준으로 평가하는가
2. `system-specs.md` — 어떤 시스템(SYS-id)에서 평가하는가
3. `common-benchmark.md` — 모든 DP 공통 workload / baseline / 통계 규칙
4. `DPn/README.md` -> `DPn/simulation-plan.md` -> `DPn/benchmark.md` — DP별 방법과 시나리오
5. `result-template.md` -> `DPn/results/` — 결과 작성 / 조회

## 핵심 규칙

- 최종 결과 = Common Benchmark + DP-specific Benchmark.
- 모든 결과는 SYS id + model + config git revision을 인용한다.
- `system-specs.md`와 `DP1/benchmark.md`의 생성 블록은 수동 편집하지 않고 `tools/`의 스크립트로 재생성한다.
- 시스템 spec은 Evidence [B], simulation 결과는 [B+C]이며 [A]로 쓰지 않는다.
- QA 별점 threshold는 결과를 본 뒤 바꾸지 않는다. 평가 정의의 누락·오류 수정(예: QA3 v3)은 사유와 이전 값을 문서에 기록하고 허용한다.
- 공통 시나리오(CB-n)는 `common-benchmark.md`, DP 전용 시나리오는 `DPn/benchmark.md`(시나리오당 한 줄). 시스템은 메모리 세대 profile(DP1: SYS-H100/B200)로 평가하고 여러 시스템은 통합해 한 결과로 낸다(`merge_systems.py`). QA3는 전 메모리 풀 기준(v4, DP1에서는 진단), 이동 비용은 링크 간섭 모델로 지연·처리량에 반영, QA4는 module/공수/에이전트 비용 3 sub-metric(사전 등록).
- 결과 문서는 §0 최종 요약으로 시작하고, 선택은 QA 우선순위 규칙(`tools/dp_selection.py`)으로 설명한다. 산출 PPT는 `tools/gen_dp_pptx.py`.

## 상태

| DP | 범위 | 상태 |
|---|---|---|
| DP1 | AI Data Migration (simulator 있음) | 진행 중 |
| DP2 | TBD | 미착수 |
| DP3 | TBD | 미착수 |
| DP4 | TBD | 미착수 |
