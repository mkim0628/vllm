# DP4 Baseline-regression loop log

Baseline = Baseline-RDMA (T_ref, 점대점 RDMA 전송 + 중앙 인덱스). 규칙: `.claude/skills/evaluation/SKILL.md` §5.

## Iteration 0 (기준 실행, 변경 없음) — 2026-10-04

- 실행: `sim/qa_eval.py --system SYS-H100|SYS-B200` + `merge_systems.py` (git rev 0e44b58, seed 11/23/37/53/71). raw: `../data/`.
- **Trigger 발동** (SKILL §5): 통합 QA1 ratio C1=C2=×0.733 (<1.00; H100 ×0.812, B200 ×0.663), QA3 절감 배수 ×0.23 (Baseline 15.9 GiB vs 후보 69.2 GiB), TTFT P99가 공통 부하에서 Baseline보다 나쁜 쌍 5/6(최악 ×25), 44쌍 중 후보 승 2 / 무 34 / 패 8.
- 후보 간(C1 vs C2)은 goodput·TTFT·TPOT·잔류량 차이가 0.02% 이내로 구분되지 않음(사전 예측 1과 일치).

## Iteration 1 — 사전 등록 (실행 전 기록, 이후 수정 금지)

**진단 (a).** 두 후보가 같은 data plane을 공유하며 같은 값만큼 Baseline보다 낮으므로, 격차는 **일관성 구조(C1/C2)가 아니라 data plane 모델**에서 온다. 후보 원인은 (1) `eta_cxl`=0.5 대 `eta_rdma`=0.85 (둘 다 ASSUMED 성격의 효율 상수), (2) 풀 aggregate가 바이트를 두 번(write+read) 나름, (3) 배경 부하 0.85를 풀과 NIC에 똑같이 적용, (4) 풀 사본이 잔류량(QA3)에 추가됨. 분류: **S (system/config 가정 의존)** — P(구조 결함)·M(모델 오류)로 단정할 증거는 아직 없음. N(noise) 아님(QA1 Baseline-vs-Baseline 잡음 1.7%/5.0%).

**가설.** 격차는 `eta_cxl`과 배경 부하에 대한 민감도로 대부분 설명되며, `eta_cxl`이 `eta_rdma`에 근접하고 배경 부하가 낮아지면 QA1 ratio가 1.00 근처에 도달한다. 풀 사본 잔류(QA3)와 TTFT P99 꼬리는 `eta_cxl` 변경으로 사라지지 않는다(구조적).

**변경 (c) — 한 class(S)만, main 값은 바꾸지 않는다 (H16).** main 결과(`eta_cxl`=0.5 등)는 그대로 두고, 같은 benchmark 전체를 다음 민감도 설정에서 SYS-H100·SYS-B200 모두 재실행한다: `eta_cxl` ∈ {0.5, 0.7, 0.85, 1.0} × 배경 부하 상한 ∈ {0, 0.5, 0.85} (12 조합, 나머지 고정; `Params.with_overrides`). 그 외 qa-criteria §6 민감도(η_rdma, overlap, S/probe/T, 별점 경계 ±10%)도 같이 낸다. 신규 profile은 provenance를 적어 추가하고 기존 profile 값은 수정하지 않는다.

**판정 규칙(사전).** 어떤 설정에서 후보 ≥ Baseline이 되어도 그 설정을 main으로 승격하지 않는다. break-even(`eta_cxl*`, 배경 부하*)을 보고하고, 이 값이 PAPER/SPEC 범위 안인지 ASSUMED 범위 안인지 표기한다. break-even이 없으면 "이 모델에서는 없음"으로 쓴다.

**중단 조건.** 이 iteration은 진단이다. 결과와 무관하게 Iteration 1에서 후보 구조를 바꾸지 않는다. 구조 변경(P class, 예: 풀 사본 제거·partial read)이 필요하면 Iteration 2로 새로 사전 등록한다. 최대 6 iteration.
