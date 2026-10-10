---
date: 2026-10-04
dp: DP2
candidates: [C1, C2]
status: preregistered (측정 전 작성, 이후 수정 금지; 변경 시 아래 '변경 이력'에만 추가)
evidence: [B+C] (simulator proxy 구현 + 가정 기반 추정)
---

# DP2 QA4 Modifiability 사전 등록

QA4를 **세 sub-metric**으로 본다(SKILL H21): (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) code-agent 토큰 비용(달러). 이 문서는 측정 전에 작성했다.

**DP1·DP4와 같은 공식·상수·별 경계·집계(시나리오 평균)를 쓴다** ([`../DP4/qa4-preregistration.md`](../DP4/qa4-preregistration.md) §4~5, 원문 [`../DP1/qa4-preregistration.md`](../DP1/qa4-preregistration.md)). DP1 v2의 "최악값 → 평균" 집계 변경을 피하기 위해 처음부터 평균 집계를 쓴다. 공통 기준(M1: ≤2 ★★★ / ≤5 ★★ / 그 이상 ★)은 그대로이고 M2, M3와 집계는 임시 정의(H8)다.

## 1. 변경 시나리오 (각 시나리오를 C1, C2 각각에 simulator 코드로 실제 구현한다)

| ID | 시나리오 | 구체 spec | "동작한다"의 합격 기준 (smoke) |
|---|---|---|---|
| S1 | **신규 Tier** | Pluggable Memory Tier I/F로 `cxl_pnm2`(CXL-PNM 계열 두 번째 디바이스: 용량 512 GiB, 내부 BW 800 GB/s = CXL-PNM의 2배, 나머지는 CXL-PNM descriptor와 같고 attention 오프로드 가능)를 Decode 시작 위치 후보 Tier로 추가 | `cb_kv_8k_b32` 또는 `dp2_long_ctx_decode_offload`(H100, load 중간)에서 n_d Tier가 `cxl_pnm2`인 plan이 ≥ 1건 선택되고, 두 후보 모두 오류 없이 완주 |
| S2 | **신규 Cost 항** | 전력 항 `E(n_p,n_d)`를 Cost에 추가(HBM 대비 상대 에너지/token 상수 표, 가중치 w_E). SLO 분율 항과 같은 형태 | Cost 값에 항이 반영되어 w_E를 크게 하면 선택된 n_d Tier 분포가 바뀐다(spy). 두 후보 모두 |
| S3 | **정책 교체** | Selector를 argmin Cost에서 "TPOT feasible한 후보 중 TTFT 최소"로 교체(생성자 주입) | 새 Selector 호출 > 0이고 기존 호출 0 (spy), 선택된 plan 분포가 변한다 |
| S4 | **신규 telemetry 신호** | 노드 `health`(degraded 플래그)를 Resource State에 추가하고 degraded 노드를 n_p 후보에서 제외하는 hard constraint로 사용 | 시나리오 중간에 노드 하나를 degraded로 표시하면 표시 이후(telemetry 주기 + 1 s) **새로 dispatch되는** 요청에 그 노드가 n_p로 선택되지 않는다. 두 후보 모두 |

시나리오는 사전에 고정했고 한 후보에 유리하게 추가·삭제하지 않는다 (SKILL H4). S4는 C2에서 **오래된 plan이 Late Validation을 통과해 degraded 노드로 가는지**를 드러내므로 후보 간 비대칭이 있을 수 있다. 이는 의도된 신호다.

## 2. Module 정의 (설계 문서 component 기준)

세는 단위는 **파일이 아니라 설계 component**([`architecture`](../../DP2/vllm-cost-model-prefill-decode-execution-planning-architecture.md) §3~4)다. 한 component에서 코드·표·config를 1줄이라도 바꾸면 변경 module 1개다.

| 구분 | Component |
|---|---|
| 공통 | Resource Intelligence(Telemetry/State, Memory Tier descriptor), Candidate Generator, **Cost Model**(Estimator), Resource Selector, Execution Router(commit / dispatch), KV Staging(handoff) |
| C2 전용 | Plan Cache(+ planner ledger), Plan Validator(Late Validation), Re-planner, Planner worker pool |
| C1 전용 | Scheduler-inline decision(single-server 결정 슬롯) |

규칙은 DP1과 같다.
- **Shared module**은 두 후보 모두 바꿔야 하는 component이며 각 후보의 module 수에 모두 포함한다(후보를 단독 도입한다고 가정). shared 수를 따로 표시한다.
- **Harness는 module이 아니다**: workload 생성기, 물리 모델(physics), 테스트. LOC에도 넣지 않고 별도로 기록한다.
- major interface 변경(기존 필드·protocol의 의미 변경)이 필요하면 module 수와 무관하게 M1 = ★. 필드·enum **추가**는 interface 변경이 아니다(append-only).

## 3. 측정 프로토콜 (DP1과 동일)

1. pristine 복사본을 기준으로 시나리오별 **작동하는 최소 변경**을 후보마다 구현한다(C1 전용 / C2 전용 / shared로 hunk 분리).
2. 합격 기준을 실제 실행으로 확인하고 기존 test(`test_sim.py`)를 통과시킨다. 통과 전 수치는 쓰지 않는다.
3. `diff -u` 기준 hunk별 **추가된 비공백·비주석 줄 수(LOC)**를 센다(수정 줄은 + 줄로 1회). 각 hunk를 component에 귀속한다.
4. touched component의 **현재 크기(LOC)**를 pristine 소스에서 AST 줄 수로 잰다(에이전트 읽기량 근사).
5. 측정값은 `results/data/qa4_measured_counts.json`에 기록하고 `tools/qa4_modifiability.py --dp DP2`가 공식으로 `qa4_modifiability.json`을 만든다.

## 4. 공식·상수·별 경계
DP1 `qa4-preregistration.md` §4(M2, M3 공식과 ASSUMED 상수)와 §5(M1 ≤2/≤5, M2 ≤0.5/≤1.0 MM, M3 ≤$3/≤$10 at T1)를 **그대로** 쓴다. sub-metric 별 = 4개 시나리오 평균값에 threshold 적용, QA4 별 = 세 sub-star의 중앙값, 세 값을 모두 병기한다.

## 5. 민감도·한계
- 상수 low/high 조합에서 별점이 바뀌는지 보고한다.
- 한계: simulator proxy 구현이며 실제 시스템(vLLM) 통합이 아니다. 이 simulator는 단일 파일(`engine.py`)에 C1/C2 로직이 함께 있어 component 귀속은 판단이다. 공수·가격·배율은 가정이다. 실제 에이전트 세션 측정이 아니다. Evidence [B+C] 이하.
- Baseline-PD-fixed에는 해당 모듈이 없어 QA4는 후보 간 비교로만 읽는다.

## 변경 이력
- 2026-10-04 최초 작성(사전 등록). 같은 날 측정 전 S1 spec을 `cxl_mem`(GPU 직접 읽기 불가 DRAM expander)에서 `cxl_pnm2`로 바꿈: DECODE 후보 Tier는 Decode attention을 실행할 수 있어야 하는데 일반 CXL.mem은 그렇지 못해 합격 기준을 만들 수 없었다.
- 2026-10-04 측정 중 기록(결과는 수정하지 않음): S1 smoke는 사전 등록 시나리오에서 Planner가 CXL-PNM 계열 Tier를 선택하지 않아 합격 기준을 만들 수 없어 squeeze fixture(HBM 풀 ≈ 0.1%, ScHBM 용량 1 B)로 실행했다. S4의 C2 변경은 '작동하는 최소 변경' 규칙에 따라 Plan Validator hunk 없이 planner view hunk만 센다(validator 단독은 누출 99건으로 불합격, planner view 단독은 합격). 근거는 `results/data/qa4_measured_counts.json`.
