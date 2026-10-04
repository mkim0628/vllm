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

## Iteration 1 — 결과 (2026-10-04, 사전 등록 규칙대로 실행, main 값 불변)

- 12셀 격자(η_cxl × 배경 상한), η_rdma/overlap/배경, control plane(S, probe, cs, threads, batch, metadata cost), 별점 경계 ±10% 모두 실행. 통제 셀(η 0.5, bg 0.85)이 main과 최대 차 0으로 재현. raw/요약: `../data/sensitivity/summary.json`, `tables.md`.
- **가설 부분 확인.** QA1 parity(ratio ≥ 0.99)는 η_cxl ≈ 0.67(bg 0.85 및 0.5), 배경 0에서는 η 0.5에서 이미 동률. 이는 유효 대역 동등점(후보 노드 CXL 126·η GB/s = Baseline RDMA 85 GB/s)과 같다. TTFT P99 꼬리는 η ≥ 0.70에서 해소. **QA3는 η에 대해 break-even이 η 0.74(bg 0.85)에서만** 있고 bg ≤ 0.5에서는 격자 내 없음(구조적 plateau ≈ 0.90 = 풀 사본 + D/P 사본).
- break-even 값의 provenance: η_cxl 0.67~0.75는 등록된 ASSUMED 범위 [0.25, 0.9] 안이며 η_cxl은 ASSUMED(PAPER 근거는 어댑터 63 GB/s × 2), Baseline 쪽 η_rdma 0.85도 ASSUMED. 즉 **ASSUMED 대 ASSUMED 비교**이며 main 승격 안 함.
- C1/C2는 모든 셀에서 QA1·QA2·QA3 동일(차이 ≤ 0.03%). control-plane 파라미터는 CB 결과를 움직이지 않음.
- 결정: 후보 구조 변경 없음. 진단 결과 격차는 **data plane 효율 가정**이며 일관성 구조(C1 vs C2)와 무관하다. 단, 진단 중 시뮬레이터 모델 결함 1건 확인 → Iteration 2.

## Iteration 2 — 사전 등록 (실행 전 기록, 이후 수정 금지)

**진단 (a).** Class **M (simulator cost-model gap)**. 현재 move path는 write(P→풀)와 read(풀→D)를 하나의 cut-through flow로 겹쳐 모델링한다. 블록은 publish 이후에만 읽을 수 있으므로 물리적으로 read는 write 완료(publish) 뒤에 시작해야 한다(레이어 파이프라인 overlap은 write 쪽에만 적용 가능). 현재 모델은 **후보에 유리하게 편향**되어 있다(DESIGN_NOTES A.1에 기재된 간소화).

**가설.** 순서를 바로잡으면 후보의 TTFT가 증가하고 QA1 ratio가 더 낮아진다(η_cxl 0.5 기준 ×0.733 미만). break-even η_cxl*은 0.67보다 커진다. C1과 C2의 상대 차이는 변하지 않는다(같은 data plane).

**변경 (c) — 한 class(M)만.** move path를 (P→풀 write, overlap 규칙은 prefill과의 겹침에만 적용) → publish → pin → (풀→D read)의 순차 구조로 수정한다. 물리적 근거: 호스트 간 비일관 풀에서 reader는 publish(READY) 이후에만 payload를 신뢰할 수 있음(TraCT/Beluga 공통, 본 설계 문서 §1 ①). Evidence [B] 근거 + [C] 구현. Baseline 경로와 모든 정책 상수는 불변. 수정 전 main 결과는 `results/data/pre_serial_read/`에 보존(H9, H22 방식).

**실행 (d).** 전체 benchmark set(Common + DP4)을 SYS-H100, SYS-B200, 통합, ablation, star basis 전부 재실행하고, Iteration 1의 η_cxl × 배경 격자와 break-even도 같은 모델로 재산출한다. 이전 값과 바뀐 값을 결과 문서 한계에 적는다.

**판정 규칙(사전).** 수정 후 결과가 main이 된다(이전 main은 superseded로 보존). 후보가 여전히 Baseline 미만이면 §5 (ii)에 따라 "tested conditions에서 Baseline 대비 이득 없음"으로 보고한다 — 추가 iteration으로 η_cxl 등을 조정하지 않는다. QA3 tier-weighted residency는 결과를 본 뒤 정의한 것이므로 **민감도로만** 낸다(`defined_after_first_look`, H11), 별점에 쓰지 않는다.
