# DP2 보충: Prefill 실행 위치 결정의 영향 점검, Decode 편중에서 2안이 더 나쁜 이유

> 날짜: 2026-10-11. 근거: `2026-10-10_dp2-arch-styles.md`와 `data/arch/*`(재실행 없음, 기존 결과의 재집계·분해). Evidence [B+C].

# 1. 평가가 결정하는 것 (사실 확인)

`dp2sim/nodeint.py`의 노드 내 평가에서 **Prefill은 모든 후보가 노드의 GPU에서 실행한다**. 후보가 정하는 것은 Decode 구간 attention을 어느 Tier(HBM, ScHBM, CXL-PNM, HBF)에서 돌릴지다. 설계 문서의 "Prefill/Decode 실행 위치"에서 Prefill 위치는 이 평가에서 변수가 아니다.

# 2. Prefill 위치까지 결정하면 결과가 달라지는가

모델링하지 않았으므로 시뮬레이션으로 답할 수는 없고, 상한으로 점검했다.

| 시스템 | GPU 연산 (8 GPU, FP16) | ScHBM 연산 | 비율 | CXL-PNM 연산 | 비율 |
|---|---:|---:|---:|---:|---:|
| SYS-H100 | 7,912 TFLOPS | 197.8 TFLOPS | 2.5% | 3.28 TFLOPS | 0.04% |
| SYS-B200 | 18,000 TFLOPS | 450 TFLOPS | 2.5% | 3.28 TFLOPS | 0.02% |

- Prefill은 연산 지배(compute-bound)라 Tier의 내부 대역폭(ScHBM 6.7~16 TB/s)이 이득이 되지 않고 연산 능력이 결정한다. Prefill을 ScHBM·CXL-PNM으로 보내도 GPU 대비 추가 처리 능력은 **최대 약 2.5%**다.
- 이는 QA1의 잡음 폭(0.97~1.03)과 같은 수준이라 Prefill 위치 결정을 추가해도 별이 바뀔 가능성은 작다. 단 GPU가 Prefill로 포화인 구간의 TTFT 꼬리에는 영향이 있을 수 있다(미평가).
- 확정하려면 Prefill을 ScHBM에서 실행하는 cost model(Prefill attention의 in-situ 실행, 활성값 왕복)을 simulator에 추가해야 한다(M 클래스 변경, 사전 등록 필요). 결정이 필요하면 알려 달라.

# 3. Decode 편중(`n_dp2_decode_heavy_p_idle`)에서 2안(Blackboard)이 더 떨어지는 이유

Baseline의 최적 부하, 5 seed 평균(tier별 요청 수는 seed 11의 1회 run).

| | Baseline | 1안 Dispatcher | 2안 Blackboard |
|---|---:|---:|---:|
| B200 TTFT P99 (s) | 5.73 | 0.73 (×0.13) | 23.08 (×4.03) |
| B200 admission 대기 평균 (s) | 0.00 | 0.00 | 0.36 |
| B200 Decode tier 요청 수 | HBM 3,134 | HBM 2,870 · ScHBM 505 · 기타 17 | HBM 3,102 · ScHBM 1 |
| H100 TTFT P99 (s) | 21.5 | 4.18 (×0.19) | 40.24 (×1.87) |
| H100 admission 대기 평균 (s) | 0.69 | 0.00 | 1.32 |
| H100 Decode tier 요청 수 | HBM 1,408 | HBM 1,213 · ScHBM 232 · 기타 20 | HBM 1,376 |

해석:
1. 2안의 규칙은 "HBM 먼저, HBM budget(사용률 ≤ ρ_hi = 0.85)이 거절할 때만 offload"이고, offload Tier agent는 자기 Tier의 측정된 attention 시간이 SLO_TPOT의 θ = 0.8배 이내일 때만 claim한다.
2. Decode가 한 노드에 몰리면 HBM 사용률이 0.85를 넘어 HBM 경로가 거절하고, offload agent도 headroom이 없어 거절한다. Task는 Board에서 기다린다(admission 대기 0.36 s, H100 1.32 s). Decode 3,100여 개 중 ScHBM으로 간 것은 1개다.
3. 1안은 Cost 모델(HBM 기회비용 항 λ_HBM 포함)이 사용률이 오르기 전에 Decode의 약 15%를 ScHBM으로 보낸다(B200 505개). 그래서 HBM에 여유가 생겨 admission 대기가 0이다.
4. 2안이 **Baseline보다도** 나쁜 이유(×4.03, ×1.87)는 Baseline도 HBM에서 대기하는데 2안은 거기에 admission margin(0.85)이 더해져 더 일찍 막기 때문으로 보인다(추정, 요청 단위 분해는 하지 않음). 처리량은 Baseline과 비슷하다(×0.97, ×0.98).
5. 대가: 1안의 TPOT 꼬리(H100 ×1.54). ScHBM attention이 GPU보다 느려 SLO 이내의 TPOT 여유를 TTFT·HBM과 교환한다.

한계: Baseline 최적 부하가 과부하 구간이라 TTFT 절대값이 크다. 비율이 결정적이며 θ, ρ_hi는 사전 등록 상수다.
