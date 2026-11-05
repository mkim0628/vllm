---
date: 2026-10-25
dp: DP4
candidates: [C1-central-serialization, C2-distributed-lock]   # Baseline-RDMA 포함
sys_ids: [SYS-H100, SYS-B200]
git_rev: 23638d3fe (dirty: scenarios.py, qa_eval.py, sensitivity.py 변경 포함, 결과 생성 시점)
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "—(이번 set 미평가)" }
status: draft
---

# DP4 QA Evaluation — Agent KV Fleet 시나리오 (C1 vs C2, Baseline-RDMA 대비)

> 기준 문서: `qa-evaluation-criteria.md`, `common-benchmark.md`, `system-specs.md`, `DP4/benchmark.md` §4b, `DP4/simulation-plan.md`. 모든 수치는 simulation 출력 Evidence [B+C]이며 [A] 실측이 아니다(CXL 풀 하드웨어 없음).

# 0. 최종 요약

- 시나리오: 16K in/256 out, 10턴 에이전트(History KV 재사용), 노드 2/4/8/16(P:D=1:1). 시뮬레이터에서 실제로 실행했다(seeds 5, load 0.5~2.0).
- **SYS-H100: 후보가 이긴다.** 노드가 늘수록 이득이 커진다: 노드 4 x1.00(동률), 노드 8 x1.21~1.23, 노드 16 x1.40~1.42 (Baseline-RDMA 대비 Max SLO goodput). 노드 16 TPOT P99 17.3→14.7 ms.
- **SYS-B200: 4개 시나리오 모두 후보가 진다 (x0.51~0.52).** 후보는 load 1.0에서 D 쪽 CXL ingress 링크가 100% 포화하고 TTFT P99가 ~29 s로 폭증한다(Baseline은 같은 load에서 ingress 7%).
- C1과 C2는 이 시나리오에서 구분되지 않는다(차이 ≤1.5%, CI 이내).
- **이 결과는 이론 모델의 "DP4 ×3.09 vs GPU-only B0"와 직접 비교할 수 없다.** sim의 Baseline-RDMA는 GPU-only B0도 단순 offloading B1도 아니다(§6).

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | SYS-H100 (primary), SYS-B200 (profile: `system-specs.md`) |
| Model / precision | Llama-3.1-70B BF16, KV 327,680 B/token |
| Git revision | 23638d3fe (dirty) |
| Seeds / loads | 11 23 37 53 71 / x0.5, 1.0, 1.5, 2.0 (B200은 peak가 하단이라 0.25 추가 실행) |
| 재현 command | `cd doc-mk/Evaluation/DP4/sim && python3 qa_eval.py --system SYS-H100 --sets agent_fleet_benchmark --no-cp --jobs 4 --out-dir ../results/data/agent_fleet/SYS-H100` (SYS-B200 동일) |
| Raw data | `DP4/results/data/agent_fleet/{SYS-H100,SYS-B200}/` (`qa_result.json`, `*_runs.csv`) |

테스트: `python3 -m unittest test_sim` 69 통과(수정 후). provenance ASSUMED 파라미터(η_rdma 0.85, turn_gap_s 8 s, turn_new_tokens 1024 등)는 `configs/cluster_dp4.json` 그대로.

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO Goodput | 요청별 SLO(TTFT≤2 s, TPOT≤50 ms) 만족 요청의 output tok/s 최대(load sweep) | criteria §4 |
| QA2 TTFT/TPOT P99 | 각 arm의 Max-goodput load에서 | criteria §5 |
| QA3 | 시간평균 KV 상주량(P buffer+D HBM+pool) GiB | 임시 정의 (qa-criteria-dp4 §2) |
| Scaling Efficiency | Goodput(N)/((N/2)·Goodput(2)) | 제안 지표, 별점 없음 |

# 3. 벤치마크 / 시나리오

| Benchmark set | 시나리오 | 실제 serving 패턴 | Fit label | 비고 |
|---|---|---|---|---|
| agent_fleet_benchmark | af_n2 (기준) / af_n4 / af_n8 / af_n16 | 장문 에이전트 10턴 History KV 재사용, 노드 수 확장 | 전부 comparison-valid (H100, B200) | 단일 소스 `scenarios.py`, 한 줄 설명 `DP4/benchmark.md` §4b |
| Common CB-1~3, DP4-specific | 이번 실행 제외 | — | — | 기존 결과 `2026-10-04_dp4-qa-evaluation.md` 유지 (H3: 최종 결론은 둘을 합쳐야 하므로 이 문서는 **보완 결과**) |

# 4. 결과

## 4.1 QA 표 (agent_fleet 4개 시나리오 기하평균, 후보 ÷ Baseline)

| 시스템 | QA | Baseline-RDMA | C1 | C2 |
|---|---|---:|---|---|
| H100 | QA1 goodput 배수 | 1.000 | x1.169 (±0.061) | x1.177 (±0.057) |
| H100 | TTFT P99 worst (ms) | 3,869 | 2,607 | 2,590 |
| H100 | TPOT P99 worst (ms) | 22.6 | 15.8 | 15.7 |
| H100 | KV 상주 (GiB, 기하평균 쌍) | 723.5 | 911.1 (x0.794 절감) | 911.2 (x0.794) |
| B200 | QA1 goodput 배수 | 1.000 | x0.513 (±0.022) | x0.513 (±0.022) |
| B200 | TTFT P99 worst (ms) | 858 | 1,044 | 1,044 |
| B200 | TPOT P99 worst (ms) | 9.4 | 3.4 | 3.4 |
| B200 | KV 상주 (GiB) | 1,417.8 | 1,778.6 (x0.797) | 1,778.0 (x0.797) |

**시스템:** SYS-H100/SYS-B200, Llama-3.1-70B BF16, 4 시나리오 × 5 seeds. 별점은 이 set에서 산출하지 않는다(DP 전용 set; 공통 별점은 Common set에서만).

## 4.2 시나리오별 (Max SLO goodput tok/s, ±95% CI)

| 시스템 | 시나리오 | Baseline | C1 (ratio) | C2 (ratio) | TTFT P99 Base/C1 (ms) | TPOT P99 Base/C1 (ms) |
|---|---|---:|---:|---:|---|---|
| H100 | af_n2 | 1,127 ±142 | 1,236 (x1.10) | 1,236 (x1.10) | 3,869 / 2,575 | 22.6 / 13.3 |
| H100 | af_n4 | 2,574 ±205 | 2,584 (x1.00) | 2,583 (x1.00) | 1,507 / 1,525 | 21.0 / 11.6 |
| H100 | af_n8 | 5,128 ±367 | 6,179 (x1.20) | 6,291 (x1.23) | 876 / 2,607 | 18.6 / 15.8 |
| H100 | af_n16 | 9,970 ±542 | 14,010 (x1.41) | 14,168 (x1.42) | 803 / 2,270 | 17.3 / 14.7 |
| B200 | af_n2 | 2,936 ±222 | 1,491 (x0.51) | 1,491 (x0.51) | 858 / 1,044 | 9.4 / 3.4 |
| B200 | af_n4 | 5,828 ±400 | 2,971 (x0.51) | 2,971 (x0.51) | 478 / 729 | 8.2 / 3.4 |
| B200 | af_n8 | 11,294 ±527 | 5,902 (x0.52) | 5,902 (x0.52) | 357 / 636 | 7.6 / 3.3 |
| B200 | af_n16 | 22,409 ±510 | 11,509 (x0.51) | 11,509 (x0.51) | 351 / 583 | 6.8 / 3.2 |

n_seeds=5, 95% CI t=2.776. CV 2~13%. H100 af_n2/n4는 CI 안(동률). 후보가 이기는 H100 af_n8/n16은 peak load가 1.5로 Baseline(1.0)보다 높다.

## 4.3 Scaling Efficiency (Goodput(N)/((N/2)·Goodput(2)))

| 시스템 | arm | N=4 | N=8 | N=16 |
|---|---|---:|---:|---:|
| H100 | Baseline | 1.14 | 1.14 | 1.11 |
| H100 | C1 / C2 | 1.04 / 1.04 | 1.25 / 1.27 | 1.42 / 1.43 |
| B200 | Baseline | 0.99 | 0.96 | 0.95 |
| B200 | C1 / C2 | 1.00 | 0.99 | 0.97 |

SE > 1은 N=2 기준 행이 소규모에서 불리해서(대기열 변동) 생기는 값이며 "초선형 확장"으로 읽지 않는다. 의미 있는 비교는 같은 N에서 arm 간 비율이다.

## 4.4 Iteration summary

loop 발동: SYS-B200에서 후보 < Baseline(CI 밖). 상세 [iterations/loop-log.md](iterations/loop-log.md) Iteration 3.

| Iteration | Class | Change | Effect |
|---|---|---|---|
| 0 (initial) | B | 시나리오 set 추가(변경 없음) | H100 x1.00~1.42, B200 x0.51 |
| 1 | — | 소유자 결정 대기 (sim에 HBM 용량 모델 추가는 M class) | — |

# 5. 결과 분석

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| H100 af_n2/n4 | 아니오(동률, CI 내) | 계산(prefill)이 병목이라 KV 이동 차이가 가려짐 | — | CV 6~10%, TTFT 비슷 |
| H100 af_n8/n16 | 아니오(이김) | Baseline은 History를 D에 두는 대신 매 턴 D→P 왕복 전송, 후보는 풀에서 복원. 노드가 늘수록 Baseline 링크 경합 | — | TPOT P99 감소(17.3→14.7 ms), 단 TTFT P99는 Baseline보다 큼(803→2,270 ms) |
| B200 전부 | 예 (x0.51) | 후보는 매 턴 History 전체를 풀→D로 복원(16K×327,680 B ≈ 5 GiB/턴). B200은 계산이 빨라 CXL ingress(2×63 GB/s×η)가 먼저 포화(load 1.0에서 ingress 점유 1.00, pool 점유 0.31) | P(설계) + M(Baseline HBM 무제한) | af_n4 by_load: Baseline ingress 0.07 vs C1 1.00 |

H100 이득의 한계: TTFT P99는 후보가 나쁘다(af_n8 876→2,607 ms, af_n16 803→2,270 ms). goodput 이득은 TPOT 개선과 Baseline의 더 낮은 peak load에서 온다.

# 6. 한계

1. Evidence: 전부 simulation [B+C]. CXL 풀·H100 4노드 실측 아님.
2. **미모델링**: HBM 용량 압박(Baseline이 History를 D HBM에 무제한 보관 → 상주 KV 1,000~3,300 GiB), DRAM/SSD tier, 유휴 eviction. 즉 sim Baseline-RDMA ≠ GPU-only B0 ≠ 단순 offloading B1. 이 시나리오의 핵심 가치(HBM 한계에서의 용량 확장)는 sim에서 드러나지 않는다.
3. 임시 정의: QA3 KV 상주, Scaling Efficiency.
4. 시나리오/profile 의존성: turn_gap_s=8 s(ASSUMED); 이론 모델의 유휴 Exp(60 s)와 다르다. 결과는 CXL 링크 대역폭(η_cxl 0.85 ASSUMED)에 민감하다(기존 `2026-10-04` 문서의 break-even 참조).
5. 이론 모델(`QA-criteria-v4/theory_model.py`)의 DP4 ×3.09(vs B0)와 sim ×1.0~1.4(vs Baseline-RDMA)는 기준과 모델이 달라 대조 불가. 이론 값을 sim으로 "검증"했다고 쓰지 않는다.

# 7. 결론

- 결정 관련 진술: 이 시나리오에서 H100은 노드 8 이상에서 이득(x1.2~1.4), B200은 CXL ingress 병목으로 Baseline-RDMA 미만(x0.51). 기존 2026-10-04 결과(전반적 열세)와 일관된다. C1/C2 선택 근거는 이 시나리오에서 나오지 않는다.
- 이득 존재 조건: H100 + 노드 ≥8. 부재 조건: B200(계산이 빠른 세대), 노드 ≤4.
- 다음 단계(소유자 결정 필요): (a) sim에 HBM 용량·유휴 eviction 추가(M class)해 용량 압박 시나리오를 재실행, (b) 후보가 매 턴 전체 History를 복원하지 않도록 하는 설계 검토(P class). 이 두 가지는 모델/설계 변경이라 임의로 하지 않았다.
