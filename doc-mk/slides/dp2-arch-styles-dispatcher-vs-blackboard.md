# DP2 아키텍처 스타일 비교 덱 (4장) 설명

파일: [`dp2-arch-styles-dispatcher-vs-blackboard.pptx`](dp2-arch-styles-dispatcher-vs-blackboard.pptx) · 스타일: [`README.md`](README.md)의 DP PPT 기준 · 작성 2026-10-10
모든 수치는 시뮬레이션 [B+C]이며 실측([A])이 아니다.

## 한 줄 요약
DP2(노드 내에서 KV 구간별 attention을 어디서 실행할지 Turn 시작 시 정하는 결정)를 **중앙 Dispatcher**(1안)와 **Blackboard**(2안) 구조로 구현해 Q1~Q4로 평가했다. 별 합계 9 대 8로 Dispatcher를 선택했고, 약점인 TPOT 꼬리를 **Hybrid C**(중앙 선택 + Tier 로컬 거부권)로 보완하는 안을 제시한다.

## 장별 내용

| 장 | 제목 | 내용 |
|---|---|---|
| 1 | 배경 (1/2) | 사전 지식: GPU_STAGE 대 IN_SITU, Prefill/Decode의 attention 연산 강도 차이, 128K KV 이동 비용(가정 기반 추정) |
| 2 | 배경 (2/2) | As-Is(모든 attention을 GPU에서)의 goodput 급락과 To-Be, 설계 쟁점 |
| 3 | 설계 | 1안/2안 **구조 다이어그램**(component와 connector), 장단점, Tradeoff 표(Q1~Q4 별과 값) |
| 4 | 보완 설계 | 선택 구조의 평가, Hybrid C 구조, 약점 → 택틱 → 검증 상태 표 |

슬라이드 노트에 핵심 → 근거 순으로 설명이 있다. 4장 노트에는 "왜 처음부터 C를 후보로 두지 않았나"가 서술형으로 들어 있다.

## 평가 결과 (Baseline-GPU-local 대비, SYS-H100 + SYS-B200 통합)

| QA | 1안 Dispatcher | 2안 Blackboard |
|---|---|---|
| Q1 처리량 | ★★ goodput ×1.07 | ★★ ×1.00 |
| Q2 지연 | ★★ TTFT P99 ×0.57, TPOT P99 ×1.34 | ★ TTFT P99 ×1.15, TPOT P99 ×1.05 |
| Q3 HBM 점유 | ★★ ×0.94 | ★★ ×1.05 |
| Q4 변경 용이성 | ★★★ | ★★★ |
| 합계 | **9** | 8 |

## 읽을 때 주의할 점
- Dispatcher의 이득은 Cost 추정 오차 0에서의 값이다. 오차 sigma 0.4부터 goodput이 Baseline 아래(×0.91)로 내려간다.
- Blackboard의 한계는 구조 자체가 아니라 **cost 신호가 없는 규칙 집합**에서 온다. cost 신호를 넣은 Blackboard는 평가하지 않았다.
- Hybrid C는 **미구현**이며 효과 수치를 주장하지 않는다.
- QA 우선순위(Q1 > Q3 > Q2 > Q4)는 제안 상태이고, 이 선택은 우선순위를 뒤집어도 같다.
- Baseline-regression loop를 3회차에서 중단했다(사유: loop-log 3.6). 사용자가 되돌릴 수 있다.

## 근거 문서
- 결과 문서(7장 형식): `../Evaluation/DP2/results/2026-10-10_dp2-arch-styles.md`
- 사전 등록: `../Evaluation/DP2/arch-styles-plan.md`, `../Evaluation/DP2/qa4-preregistration-arch.md`
- 반복 로그: `../Evaluation/DP2/results/iterations/loop-log.md` (§3)
- 원자료: `../Evaluation/DP2/results/data/arch/`, 코드: `../Evaluation/DP2/sim/dp2sim/`
- 설계 논의 배경: `../DP2/dp2-decision-structure-candidates-A-B-C.md`, `../Requirements/memo-dp2-redesign-ideation.md`
