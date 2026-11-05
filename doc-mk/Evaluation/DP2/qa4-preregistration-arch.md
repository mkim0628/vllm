---
date: 2026-10-10
dp: DP2
candidates: [A-Dispatcher, B-Blackboard]
status: preregistered (측정 전 작성, 이후 수정 금지; 변경은 아래 '변경 이력'에만 추가)
evidence: [B+C] (simulator proxy 구현 + 가정 기반 추정)
---

# DP2 QA4 Modifiability 사전 등록 (아키텍처 스타일 비교)

SKILL H21의 세 sub-metric(M1 변경 module 수, M2 개발 공수, M3 에이전트 비용)을 쓴다. **공식·상수·별 경계·시나리오 평균 집계는 DP1/DP2/DP4 사전 등록과 같다** (`qa4-preregistration.md` §4~5, `tools/qa4_modifiability.py`). 측정 전에 작성했다.

## 1. 변경 시나리오 (A, B 각각에 simulator 코드로 실제 구현)

| ID | 시나리오 | 구체 spec | 합격 기준 (smoke) |
|---|---|---|---|
| S1 | **신규 Tier** | `cxl_pnm2` (CXL-PNM 계열 두 번째 디바이스, 용량 512 GiB, 내부 BW 800 GB/s = CXL-PNM의 2배, 나머지는 CXL-PNM descriptor와 같고 attention 오프로드 가능)를 Decode attention 실행 후보 Tier로 추가 | 두 후보 모두 오류 없이 완주하고 `cxl_pnm2`로 Decode가 시작된 turn이 ≥ 1건 (squeeze fixture 허용, 사용 시 공개) |
| S2 | **신규 목적 항** | 전력 항: Tier별 상대 에너지/token 표와 가중치 w_E를 의사결정에 반영 | w_E를 크게 하면 선택된 Tier 분포가 w_E = 0 대비 바뀐다(spy). 두 후보 모두 |
| S3 | **정책 교체** | A: Selector를 argmin Cost에서 "TPOT feasible한 후보 중 TTFT 최소"로 교체(생성자 주입). B: Task Board의 중재(arbitration)를 "우선순위 순서 첫 claim"에서 "측정 부하가 가장 낮은 claimant"로 교체(생성자 주입) | 새 정책 호출 > 0이고 기존 호출 0 (spy), 선택된 Tier 분포가 변한다 |
| S4 | **신규 telemetry 신호** | Tier `degraded` 플래그. degraded Tier는 새 dispatch의 Decode attention 실행 후보에서 제외(hard constraint) | 시나리오 중간에 한 offload Tier를 degraded로 표시하면 표시 이후(telemetry 주기 + 1 s) **새로 dispatch되는** turn은 그 Tier를 선택하지 않는다. 두 후보 모두 |

시나리오는 사전에 고정했고 한 후보에 유리하게 추가·삭제하지 않는다 (H4). S2, S3는 두 아키텍처의 **대응 변경**을 정의했다(A의 Cost 항 / B의 admission 규칙, A의 Selector / B의 중재). 대응이 어색한 부분은 의도된 신호이며(한 스타일이 어떤 변경에 구조적으로 불리한 것), 결과 해석에서 이를 명시한다.

## 2. Module 정의 (설계 component 기준, 한 component에서 1줄이라도 바꾸면 변경 module 1개)

| 후보 | Component |
|---|---|
| A Dispatcher | Tier Descriptors(메모리 Tier 사양, snapshot view) · Candidate Generator(후보 Tier 집합과 필터) · Cost Model(Estimator, λ_HBM) · Resource Selector(argmin/순위) · Dispatcher(scheduler 직렬 결정, commit 경로) |
| B Blackboard | Tier Descriptors · Task Board(게시/claim 프로토콜, 중재, 재시도) · Tier Admission Agents(Tier별 headroom 규칙) · HBM Budget Admission · Poster(Thin Scheduler의 Task 게시) |

규칙은 DP1/DP2와 같다.
- **Harness는 module이 아니다**: workload 생성기, 물리 모델(physics의 시간 계산), 테스트, NodeSim의 공통 기반(`assign_node`, 점유 측정, commit 래퍼).
- major interface 변경(기존 필드·protocol의 의미 변경)이면 module 수와 무관하게 M1 = ★. 필드·enum **추가**는 interface 변경이 아니다.
- 귀속은 변경된 줄을 **둘러싼 class/함수**를 `qa4_count_arch.py`의 표로 component에 매핑한다. 표에 없는 줄은 오류(미귀속)로 처리해 귀속이 명시적이고 검토 가능하게 한다.
- 측정: pristine 복사본(`base`) 대비 시나리오별 작동하는 최소 변경, `diff -u`의 추가된 비공백·비주석 줄 수(LOC), touched component의 현재 크기(AST 줄 수). 합격 기준을 실제 실행으로 확인하고 `test_sim.py`와 기존 후보 결과 일치 확인을 통과한 뒤에만 수치를 쓴다.

## 3. 해석 주의 (결과 전에 공개)

- A와 B를 같은 사람이 같은 simulator에서 구현했고, 구조(어떤 기능이 어떤 component에 놓이는가)는 설계 문서의 스타일 정의를 따라 구현한다. 구현 방식의 자유도가 module 수에 영향을 줄 수 있다는 한계가 있다.
- 공수·가격은 가정 상수이며 실제 에이전트 세션 측정이 아니다 (Evidence [B+C] 이하).
- 상수 low/high 조합에서 별점이 바뀌는지 보고한다.

## 변경 이력
- 2026-10-10 최초 작성(사전 등록).
- 2026-10-10 (측정 전, 후보 평가 실행 전) 구현 정의 명확화: (1) B의 S2는 "각 Tier의 admission 판단에 전력이 반영된다"는 A의 S2(모든 Tier에 적용되는 Cost 항)와 기능이 같도록 **Tier Admission Agent의 headroom과 HBM Budget Admission의 임계 모두**에 전력 가중을 넣는 것으로 구현한다(HBM 규칙만 바꾸는 더 작은 변경은 기능이 더 좁아 대응하지 않는다). (2) S3의 정책 주입 지점은 두 후보 모두 **기본 코드에 없고 변경에 포함**된다(A: Selector 정렬 키 주입, B: Task Board 중재 주입). 기본 코드의 B는 중재를 "AGENT_ORDER 첫 claimant"로 고정해 두었다.
- 2026-10-10 (측정 중, 후보 평가 실행 전) 공개: (1) 위 (1)의 B S2 구현 정의는 **smoke에서 실패**했다(agent와 HBM budget의 에너지 반영만으로는 Tier 분포가 바뀌지 않음, 중재가 에너지를 보지 않음). 사전 등록 규칙(최소 변경)에 따라 주 값은 **smoke를 통과하는 최소 변경**(Task Board의 중재가 에너지를 반영)으로 하고, agent와 budget까지 넣은 확장판(`S2full`)은 민감도로 보고한다. (2) S1 smoke fixture는 A와 B 모두에서 ScHBM과 CXL-PNM 용량을 1 B로 줄인다(원 fixture는 B에서 `cxl_pnm2`가 선택되지 않음). (3) 시스템 코드 점검 중 B의 agent가 claim backlog를 세지 않는 결함을 발견해 평가 전에 고쳤다(`loop-log.md` 3.3).

- 2026-10-10 (후보 평가 실행 전) B 규칙 집합 v2(`loop-log.md` 3.5)로 B 코드의 일부 줄이 바뀌어 QA4 harness의 B 변경 anchor(`S2full`, `S4`)를 새 줄에 맞게 갱신했다. 시나리오 정의·공식·경계는 그대로이고 QA4는 v2 코드에서 다시 측정한다.
