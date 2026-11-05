# DP2 설계와 평가 정리: 중앙 Dispatcher 대 Blackboard (노드 내 attention 실행 위치 결정)

> 작성: 2026-10-10. 상태: **초안**. 모든 수치는 시뮬레이션 **[B+C]** 이며 실측 [A]가 아니다. 숫자의 원천은 `../Evaluation/DP2/results/2026-10-10_dp2-arch-styles.md`(생성기 출력)이고 이 문서는 그 요약이다.
> 관련: 후보 구조 논의 [`dp2-decision-structure-candidates-A-B-C.md`](dp2-decision-structure-candidates-A-B-C.md), 재설계 메모 [`../Requirements/memo-dp2-redesign-ideation.md`](../Requirements/memo-dp2-redesign-ideation.md), 발표 덱 [`../slides/dp2-arch-styles-dispatcher-vs-blackboard.pptx`](../slides/dp2-arch-styles-dispatcher-vs-blackboard.pptx)
> 표기: **[사용자 결정] / [Claude 제안] / [추정] / [가설] / [문서 근거]**

## 1. 한 장 요약

| 항목 | 내용 |
|---|---|
| 결정 | Turn(대화 턴) 시작 시, 한 노드 안에서 KV 구간별 attention을 어디서 실행할지: `GPU_STAGE`(KV를 HBM으로 옮겨 GPU attention) 또는 `IN_SITU(tier)`(KV가 있는 Tier에서 fused attention, `(m,l,o)` LSE 병합) |
| 비교 축 | **아키텍처 스타일**: 1안 중앙 Dispatcher(Master–Worker) 대 2안 Blackboard(공유 Task Board + 자율 Knowledge Source) |
| 평가 | Q1 처리량, Q2 지연, Q3 HBM KV 점유, Q4 변경 용이성. Baseline-GPU-local 대비, SYS-H100 + SYS-B200 통합, seed 5개 |
| 선택 | **1안 Dispatcher** (별 합계 9 대 8). 우선순위를 뒤집어도 같음 |
| 약점과 보완 | Dispatcher의 TPOT 꼬리(P99 ×1.34)와 Cost 추정 오차 의존 → **Hybrid C**(중앙 선택 + Tier 로컬 live 거부권), 미구현 [C] |

## 2. 설계

### 2.1 DP2의 범위 [사용자 결정]
- P/D 구분 없는 노드 내부 결정. 연산은 항상 GPU에서 시작하고 **attention만** 위치를 옮길 수 있다.
- DP1이 정한 KV 배치(Tier별 위치)는 입력이다. DP1 = 이동 후 데이터가 남는 배치, DP2 = 실행을 위한 일시적 staging. DP1과 DP2는 따로 평가한다.
- DP4는 이를 멀티 노드로 확장해 P/D 노드 역할을 가른다(이 문서 범위 밖).

### 2.2 왜 선택이 갈리는가 [추정]
- attention 연산 강도는 약 Tq×8 FLOP/B(Llama-70B급, GQA 8, BF16). H100 ridge ≈ 300이므로 Decode는 memory-bound, Prefill은 compute-bound다.
- KV는 약 320 KB/token(128K ≈ 43 GB, PCIe 64 GB/s에서 ≈ 0.67 s). Decode는 같은 KV를 출력 길이만큼 반복해 읽으므로 대역폭이 큰 Tier에서 제자리 실행이 유리하고, Prefill은 GPU가 유리하다. break-even Tq는 ScHBM ≲ 390, CXL-PNM ≲ 6.
- 동시 요청이 많으면 KV를 HBM으로 끌어오는 비용(HBM 용량, 쓰기 대역폭, 링크)이 처리량을 깎는다. 따라서 실행 위치 결정은 HBM 기회비용을 알아야 한다.

### 2.3 후보 구조 (같은 입력, 같은 출력 값)

#### 2.3.1 공통 전제와 입출력
- **입력**: 큐에 들어온 요청(요청마다 History 토큰 `hist`, 새 입력 `q`, 예상 출력 `out`), 세션 KV의 현재 위치(`owner = (node, tier)`), 노드와 Tier별 여유 용량·점유·실행 중인 Decode 그룹, Tier 사양(용량, 대역폭, attention 가능 여부, 연산 능력).
- **출력**: 요청마다 **Decode attention이 실행될 Tier 하나**(`hbm | custom_hbm | cxl_pnm | hbf`)와, 그 Tier로 KV를 두기 위한 용량 예약. 어느 후보든 출력 형태는 같다.
- **노드는 이미 정해져 있다**: DP2의 결정은 "노드 안에서 어느 Tier인가"뿐이다. 요청이 어느 노드로 가는지는 DP2의 설계 범위가 아니다(노드 선택은 DP4). 평가 환경에서 노드를 배정하는 고정 라우팅은 설계가 아니라 평가 하네스이며 3.1에 적었다.
- **고정 규칙(후보 간 동일)**: ① Prefill은 항상 그 노드의 GPU에서 chunked로 실행한다(노드 내 P/D 분리 없음). ② 노드의 Prefill 대기 토큰이 한도(`qcap`)에 있으면 어느 후보든 요청을 큐에 남긴다. ③ 조정 요소가 장애(`fault`)이면 모든 후보가 Baseline 규칙으로 복귀한다(안전 복귀).
- **Decode 반복 시간 모델**(`physics.iter_time`): `κ·(비-attention(n_tok) + max(GPU attention 합, offload Tier attention 최대값))`. Tier별 attention 시간은 HBM = KV/BW 또는 FLOPs/연산, HBF = GPU 직접 읽기(외부 BW·효율 + layer당 지연), attention 가능한 Tier = 내부 BW·연산 + 활성화 전송 + layer당 지연. 두 후보는 같은 모델로 TPOT를 예측·측정한다.

#### 2.3.2 기준선 Baseline-GPU-local (T_ref)
vLLM As-Is에 해당한다. 모든 Decode attention을 GPU(HBM)에서 한다. History가 HBM에 있으면 그대로, 그 밖(HBF, DRAM, SSD)이면 HBM으로 staging(swap-in)한 뒤 실행하고, 새 KV는 HBM에 둔다. 결정 비용 0, 결정 지점 없음, 후보 선택 없음.

#### 2.3.3 1안: 중앙 Dispatcher (Master–Worker)

**Component와 책임** (코드 `arch_dispatcher.py`, `policies.py`)

| Component | 책임 | 입력 → 출력 | 상태 |
|---|---|---|---|
| Tier Descriptors | Tier 사양과 용량, 현재 그룹을 `NodeView`로 제공 | 물리 모델 → NodeView | 읽기 전용 |
| State Repository | telemetry snapshot(갱신 주기 50 ms) 보관 + `PendingLedger` | snapshot, 자기 dispatch → 겹쳐 본 NodeView | snapshot과 ledger |
| Candidate Generator | 노드의 Tier 후보(`DECODE_TIERS`)와 필터(용량, HBM은 축출 가능분 포함, HBF 존재 여부, TPOT feasibility) | NodeView, 요청 → 후보 집합 | 없음 |
| Cost Model | 후보별 Cost(SLO 분율의 합)와 HBM 기회비용 λ_HBM | 후보 → 스칼라 | 상수 c = 1.0 |
| Resource Selector | TTFT가 SLO 안인 후보 중 Cost 최소(없으면 SLO 초과비 최소) 선택 | 후보 순위 → ExecutionPlan | 없음 |
| Dispatcher | 큐 스캔(최대 64개), 직렬 결정 시간 부과, commit 호출 | 큐 → Plan 확정 | `sched_busy`(한 번에 하나) |
| Tier Worker / GPU Worker | 확정된 Plan의 실행(용량 예약, Prefill, Decode 시작), 상태 보고 | Plan → telemetry | 각자의 큐·그룹 |

**Cost** (기존 SLO 분율 Cost + 신규 항)
```
fd(t)   = tpot(t)/SLO_TPOT                          # 이 Task를 t에 더했을 때의 노드 TPOT 예측
        + x3(t)                                     # 이미 실행 중인 Decode들이 받는 TPOT 악화(SLO 분율)
        + 축출 전송시간/SLO_TTFT                       # HBM에서 idle 세션을 내릴 때만
        + λ_HBM(t)   (t = hbm 일 때만, 다른 Tier는 0)  # 신규 항: c · u² · Δ/cap, u = min(1.5, (사용+Δ)/cap)
Cost    = 앞단(Prefill: 대기 + staging + chunked 시간)/SLO_TTFT + 타 요청 지연 항
        + 핸드오프 stall/(out-1)/SLO_TPOT + fd(t)
```
λ_HBM의 u²는 HBM이 비어 있을 때 거의 0이고 가득 찰수록 급해지는 shadow price다. 이 항이 "HBM에 두면 빠르지만 다른 세션을 밀어낸다"는 비용을 Cost에 넣는 장치다.

**처리 흐름**
1. 요청이 큐(`gq`)에 쌓인다. Dispatcher는 `sched_busy`가 아닐 때 큐를 앞에서부터 최대 64개 스캔한다.
2. 요청마다 (하네스가 배정한) 노드의 snapshot에 `PendingLedger`(이미 dispatch했지만 snapshot에 아직 안 보이는 Decode)를 겹쳐 본다. 후보는 그 노드의 Tier만이다. 노드의 Prefill 대기가 한도면 건너뛴다.
3. `Estimator.evaluate`가 Tier 후보를 만든다(용량 부족이면 제외, TPOT 예측이 SLO를 넘으면 제외) → 후보별 Cost 계산 → TTFT feasible 후보 중 argmin을 Plan으로 확정(`k` = Tier 후보 수).
4. 결정은 scheduler에서 **직렬**이다: 결정 시간 `t_ref·k/64`를 `sched_busy`로 점유한 뒤 `c1done` 이벤트에서 commit한다. commit이 용량 예약과 필요 시 idle 세션 축출, Prefill 시작을 수행하고 `PendingLedger`에 기록한다.
5. Decode가 시작되면 ledger에 시작 시각을 적고, 새 snapshot(그 시각 이후)이 오면 해당 항목을 지운다(`prune`).
6. 추정 오차는 `eps`(lognormal)로 Cost 입력에 곱한다(본 평가 기본 0, 민감도에서 0~0.6).

**특성**: 결정 정보가 snapshot 지연(≤ 50 ms) + 추정기이므로 네트워크 상황이 아니라 **정보 신선도와 오차**가 한계다. `PendingLedger`는 한 갱신 구간의 요청이 모두 같은 Tier로 몰리는 herding을 막기 위한 필수 구성이다(없을 때 decode_heavy 1,882 대 8,382). 결정 지점이 하나라 장애 시 전체가 멈추므로 Baseline 복귀 경로를 둔다.

#### 2.3.4 2안: Blackboard

**Component와 책임** (코드 `arch_blackboard.py`)

| Component | 책임 | 입력 → 출력 | 상태 |
|---|---|---|---|
| Poster (Thin Scheduler) | 큐의 요청마다 Task를 게시(최대 128개, 중복 게시 방지). 비용 계산 없음 | 큐 → Task | `posted` 집합 |
| Task Board | Task의 상태(posted → claimed → done), claim 라운드 실행, 중재, claim backlog 관리 | Task, claim → 확정 | `posted`, **모든 Tier의 claim backlog**(노드 → 요청 → (Tier, ctx)) |
| Tier Admission Agent (custom_hbm, cxl_pnm, **hbf**) | 자기 Tier의 용량과 **노드 TPOT headroom**을 라이브 측정해 claim 여부 결정 | 노드 그룹, backlog → bool | 자기 claim backlog |
| HBM Budget Admission | HBM staging·상주 허용 여부: 용량(여유 + 축출 가능) 충족, 이용률 ≤ ρ_hi(idle 세션은 비어 있는 것으로 계산). 이미 HBM에 있으면 용량만 확인 | 노드 점유 → bool | 없음 |
| GPU Worker | HBM staging과 GPU attention 실행 | — | — |
| Tier Descriptors | Tier 사양 | — | 읽기 전용 |

**Agent의 headroom** (v2): `iter_time(live 그룹 ⊕ 노드의 모든 claim backlog ⊕ 이 Task를 이 Tier에 추가) ≤ θ·SLO_TPOT`, θ = 0.8(= 40 ms). 측정은 snapshot이 아니라 노드의 **현재** 상태이고 estimator도 쓰지 않는다. 그리고 claim했지만 Decode가 아직 시작되지 않은 Task(backlog)를 포함해야 한다(없을 때 모든 Task가 같은 Tier로 몰린다).

**결정 규칙 (`TaskBoard.decide`, v2)**
```
ctx = hist + q + out/2
1. History가 Tier ot(hbm 제외)에 있고 ot의 agent가 있으면(custom_hbm, cxl_pnm, hbf)
     agent[ot].claim(용량 충족 and 노드 headroom) → 성공이면 ot 에서 실행 (KV 있는 곳에서 실행)
2. HBM Budget Admission.grant(...) → 성공이면 hbm (History는 staging, 새 KV는 상주)
3. hist > 0 이면 → 거절(None): board에 이동 비용 신호가 없어 History는 HBM staging까지만 시도
4. hist == 0 (새 KV) 이면 offload 사다리: custom_hbm → cxl_pnm 순으로 claim 가능한 agent 중
     첫 claimant (중재 = AGENT_ORDER 순서)
5. 모두 거절 → Task는 큐에 남고 다음 게시 때 다시 claim 시도 (rejects 카운터)
```

**처리 흐름**
1. Poster가 큐의 요청마다 Task를 게시하고 `t_bb`(0.5 ms) 뒤 `bbclaim` 이벤트를 예약한다(여러 Task가 병렬로 진행, 직렬화 없음).
2. `on_claim`: 요청이 아직 큐에 있으면, 장애면 Baseline 규칙으로, 아니면 (하네스가 배정한) 노드의 outstanding이 한도 미만일 때 `decide`를 호출한다.
3. 성공이면 commit(용량 예약, Prefill 시작)하고 board와 해당 agent의 backlog에 기록, 큐에서 제거한다. Decode가 시작되면 backlog에서 지운다.
4. 실패면 큐에 남고 다음 이벤트의 게시 때 재시도한다.

**규칙 집합 v1 → v2 (loop 2)**: v1은 `hbf`를 용량만 보고 admit하고 offload agent의 headroom을 그 Tier의 attention 시간만으로 판단했으며, History를 offload 사다리에 올렸다. 그 결과 128K 컨텍스트가 HBF 직접 읽기로 계속 Decode되거나(`hbf_hist` goodput ×0.00) History 이동이 폭증(`dram_small_tool` ×0.72)했다. v2는 모든 Tier를 노드 수준 headroom으로 admit하고 History는 HBM staging까지만 시도한다. 상수는 바꾸지 않았다.

**특성**: 결정이 라이브 측정에 기반하므로 telemetry 지연에 둔감하고 중앙 결정 비용이 없다. 반면 **전역 목적(비용 함수)이 없고 규칙 집합이 곧 정책**이다. board에는 HBM에 두는 것과 offload의 비용 차이를 볼 신호가 없어서 HBM 압박(ρ_hi)이 있을 때만 offload한다. 새 Tier는 agent 한 개 추가로, 새 telemetry 신호는 해당 agent 한 곳에 국소화된다.

#### 2.3.5 두 구조의 차이 (구조적 속성 → 영향 QA)

| 속성 | 1안 Dispatcher | 2안 Blackboard | 주로 영향받는 QA |
|---|---|---|---|
| 결정 주체 | 중앙 1곳(Planner) | 분산(Knowledge Source) | Q4(신규 요소 추가), 장애 격리 |
| 결정 정보 | snapshot(≤ 50 ms 지연) + 추정기(오차 ε) + 자기 dispatch 기록 | 노드의 라이브 측정 + claim backlog, 추정기 없음 | Q2(꼬리), 오차 민감도 |
| 목적 함수 | 전역 Cost(TPOT, TTFT, 타 요청 악화, HBM 기회비용) | 없음(Tier별 임계 규칙) | Q1, Q3 |
| 결정 시점·비용 | Turn 시작, 직렬(`t_ref·k/64`) | Turn 시작, 병렬(`t_bb`) | Q2(TTFT 대기) |
| 제어 흐름 | 중앙 → Worker command | 보드 event, KS가 구독하고 claim | 결합도, Q4 |
| 상태 소유 | 중앙이 Tier 상태 사본 보유(snapshot, ledger) | Tier agent가 자기 상태 소유 | Q4(신호 추가 시 변경 범위: 3 module 대 1) |
| 정책 변경 지점 | Cost Model, Selector | Task Board 중재, agent 규칙 | Q4(정책 교체) |
| 약점 | 정보 신선도·추정 오차, 단일 지점 | 비용 신호 부재, admission margin | Q2, Q3 |

#### 2.3.6 보완안 Hybrid C의 구조 (미구현 [C], 4.2 참조)
Dispatcher의 Cost Evaluator → Selector는 그대로 두고, Tier 쪽에 **Tier Guard**(Knowledge Source형, 2안의 agent headroom을 차용)를 둔다. 흐름: ① Dispatcher가 후보 순위를 산출해 1순위로 `plan(cmd)`를 보낸다 → ② Tier Guard가 노드 live iteration 시간 + claim backlog로 거부 여부를 판단하고 거부하면 `veto(reason)`로 되돌려 보낸다 → ③ Dispatcher가 다음 후보를 시도한다(재계획 요청 수신 Component 추가). 결정 권한과 전역 Cost는 중앙에 유지하고 **거부권만** 분산한다. 이 구조에서 Tier 상태·한도를 Guard가 소유하면 신호 추가가 Guard 한 곳에 국소화될 것이라는 것이 가설이다(검증 전).

#### 2.3.7 코드 매핑
| 설계 요소 | 코드 |
|---|---|
| 공통 노드 시뮬레이터, Baseline, 점유 측정 | `Evaluation/DP2/sim/dp2sim/nodeint.py` (`NodeSim`, `baseline_plan_gpu`) |
| (평가 하네스) 노드 배정 고정 라우팅 | `nodeint.py` (`assign_node`), 설계 요소가 아님 |
| Dispatcher, ledger, λ_HBM | `arch_dispatcher.py` (`DispatcherPlanner`, `PendingLedger`, `HbmOpportunityCost`) |
| Cost Model, Candidate Generator, Selector | `policies.py` (`Estimator.evaluate`; 신규 훅 `price_fn`) |
| Blackboard | `arch_blackboard.py` (`TaskBoard`, `TierAdmissionAgent`, `HbmBudgetAdmission`, `Poster`) |
| 참고 후보(Dispatcher + Blackboard 규칙) | `arch_dispatcher.py` (`RuleDispatcher`) |
| 물리 모델(iteration 시간, Tier 사양) | `physics.py` |
| 시나리오 | `scenarios_node.py`, `configs/grids_node.json` |

### 2.4 구조 비교 (평가 전 예상과 평가 후 관찰)
| | 1안 | 2안 |
|---|---|---|
| 장점 | 전역 Cost로 처리량, 지연, HBM을 함께 최적화. 정책 변경 지점이 Cost와 Selector에 모임 | live 측정이라 telemetry 지연에 둔감. 결정 비용 없음. 신규 Tier는 Agent 추가로 국소 확장 |
| 단점 | snapshot 지연과 추정 오차 의존. 단일 결정 지점 | 규칙 집합이 곧 정책이고 cost 신호가 없음. 게시→claim 홉과 재시도 비용 |

## 3. 평가

### 3.1 설정 (사전 등록: `../Evaluation/DP2/arch-styles-plan.md`, `qa4-preregistration-arch.md`)
- **노드 배정은 평가 하네스다(설계 아님)**: 시뮬레이터가 멀티 노드 엔진이라 Tier 결정 전에 요청을 노드에 배정해야 한다. 모든 후보에 같은 고정 규칙을 쓴다(`assign_node`: History가 있으면 소유 노드, 없으면 snapshot에서 HBM 여유가 가장 큰 노드). 후보는 배정된 노드의 Tier만 정한다. 시나리오의 노드 수는 기존 시나리오의 D 노드 수를 그대로 썼다(1노드 3개, 2노드 12개, 4노드 1개). 따라서 결과에는 "한 노드 안의 결정"뿐 아니라 이 고정 라우팅에 의한 노드 간 부하 분산 효과가 섞여 있다. 후보 간에는 중립이지만 DP2만 분리한 측정은 아니다.
- 시스템: SYS-H100(HBM3, PCIe5), SYS-B200(HBM3e, PCIe5) 통합. 시나리오 16개 x 2 시스템 = 32쌍, 그중 comparison-valid 21, saturated 11, infeasible 0.
- 시나리오: Common 3(`n_cb_*`) + DP2 노드 내 13(HBM 상주 짧은 대화, History가 DRAM/SSD/HBF에 있는 대화, 128K 긴 컨텍스트 decode, decode 집중, 부하 급증, decode 단계 전환, stale telemetry, Dispatcher 장애 fallback 등). 정의는 `../Evaluation/DP2/benchmark.md` §11.
- 실행: seed 5개(11, 23, 37, 53, 71), 시나리오별 부하 grid, 5,320 run. iso-load로 QA2와 QA3를 비교.
- QA: Q1 Max SLO goodput(경계 0.97/1.30), Q2 TTFT와 TPOT의 P50/P95/P99 개선 배수 geomean(0.95/1.25), Q3 HBM KV 점유 비(절감 0.95/1.25, SLO 달성률이 Baseline-1pp 이상인 쌍만), Q4 변경 시나리오 4종 실제 구현(M1 module, M2 공수, M3 비용). 우선순위(제안) Q1 > Q3 > Q2 > Q4.

### 3.2 결과 (Baseline-GPU-local 대비)

| QA | Baseline | 1안 Dispatcher | 2안 Blackboard |
|---|---:|---|---|
| Q1 goodput (tok/s) | 1,075 | ★★ 1,155 (×1.07) | ★★ 1,081 (×1.00) |
| Q2 TTFT P99 · P50 (ms) | 3,529 · 327 | 1,995 (×0.57) · 283 (×0.87) | 4,053 (×1.15) · 313 (×0.96) |
| Q2 TPOT P99 · P50 (ms) | 14.5 · 8.3 | 19.5 (×1.34) · 8.6 (×1.03) | 15.1 (×1.05) · 8.4 (×1.00) |
| Q2 별 (개선 배수 geomean) | ×1.00 | ★★ ×1.11 | ★ ×0.95 |
| Q3 HBM 점유 (GiB) | 631 | ★★ 586 (×0.94) [20쌍] | ★★ 692 (×1.05) [14쌍] |
| Q4 module · MM · 비용(T1) | — | ★★★ 1.75 · 0.31 · $1.17 | ★★★ 1.25 · 0.22 · $0.96 |
| 별 합계 | | **9** | 8 |

쌍별 판정(comparison-valid 21쌍): 1안 Dispatcher 11승 3무 7패(패의 대부분이 TPOT 꼬리이며 SLO 이내), 2안 Blackboard 3승 11무 7패.

### 3.3 왜 이렇게 나왔나
- **1안**: Cost에 HBM 기회비용이 있어 History가 큰 turn이나 decode가 몰린 노드에서 ScHBM으로 보낸다(Decode의 16.5%). 그래서 TTFT 꼬리와 HBM 점유를 얻고, Cost가 SLO 안의 TPOT 여유를 소비하므로 TPOT 꼬리가 커진다(P99 19.5 ms, SLO 50 ms 이내).
- **2안**: 규칙이 "HBM budget이 허용하면 HBM, 거절될 때만 offload"이고 board에 HBM 대 offload의 비용 차이를 볼 신호가 없다. 압박이 없으면 Baseline과 같은 결정을 하고(예: `n_dp2_long_ctx_decode_offload` H100에서 1안은 ScHBM 1,066 turn, 2안은 0), 압박이 있으면 admission margin(ρ_hi)이 요청을 큐에 잡아 TTFT 꼬리가 늘어난다. 같은 규칙을 중앙에서 돌린 참고 후보(Ref)가 비슷한 값(goodput ×0.99, TTFT P99 ×1.16)이므로 원인은 아키텍처보다 **규칙 집합**이다.
- **Q4**: 둘 다 ★★★. 시나리오별 변경 module 수(A / B): 신규 Tier 2/2, 신규 목적 항 1/1, 정책 교체 1/1, 신규 telemetry 신호 3/1. 신호 추가에서 B가 국소적이다(Agent 1곳). B의 목적 항 확장판(agent와 budget까지 반영)은 3 module.

### 3.4 민감도 (사전 등록값 주변, 6개 시나리오, SYS-H100, seed 3개)
- Cost 추정 오차 σ: 0 / 0.2 / 0.4 / 0.6에서 1안 goodput ×1.02 / ×1.01 / ×0.91 / ×0.75, TTFT P99 ×0.74 / ×0.72 / ×1.41 / ×2.14. **break-even은 σ 0.2와 0.4 사이**. 본 평가는 σ = 0으로 돌렸다.
- λ_HBM, t_ref, telemetry 주기(0.01~1 s)는 1안 결과를 거의 바꾸지 않는다(goodput ×1.01~×1.04).
- 2안은 θ에 둔감(0.6~1.0에서 동일)하고 ρ_hi에 민감하나(0.7에서 goodput ×0.85), 어느 값에서도 Baseline을 넘지 못한다.

### 3.5 Baseline-regression loop 이력 (`../Evaluation/DP2/results/iterations/loop-log.md` §3)
| 단계 | 내용 |
|---|---|
| Baseline control | Baseline-GPU-local을 Decode 항상 HBM으로 정의(초기 정의는 TPOT infeasible), grid 끝 peak 확장 |
| loop 1 (A, class P) | herding(decode_heavy 1,882 대 8,382)을 `PendingLedger`로 수정 → 9,102 |
| loop 2 (B, class P) | `hbf_hist` ×0.00, `dram_small_tool` ×0.72의 파국을 규칙 v2로 수정 → ×0.96, ×0.93 |
| loop 3 | 남은 B 퇴화는 cost 신호 부재라는 구조적 성질이라 판단, **중단**(최대 6회 전). 사용자가 되돌릴 수 있음 |
중단된 1, 2회차 부분 데이터는 `run1_aborted`, `run2_aborted`로 보존했고 평가에 쓰지 않았다.

### 3.6 사전 등록 가설의 결과
1. HBM 여유 시나리오에서 후보가 Baseline보다 나쁘지 않다 → 1안 대체로 성립, 2안은 일부 시나리오에서 0.93~0.98×.
2. 압박 시나리오에서 두 후보가 offload를 써서 Q1과 Q3가 좋아진다 → **1안만** 성립. 2안은 offload를 쓰지 않거나 큐 대기로 오히려 TTFT 꼬리가 늘었다.
3. 2안이 stale telemetry와 큰 ε에서 덜 나빠진다 → 부분 성립(B200 `n_dp2_stale_telemetry`에서 2안 ×1.36, H100에서는 패). ε 민감도는 1안이 크게 취약함을 확인.
4. Q4에서 A는 교차 관심사, B는 국소 확장이 유리 → 신호 추가만 B가 유리, 나머지는 같았다.
5. 장애 fallback에서 Baseline 수준 유지 → saturated로 판별력 없음.

## 4. 선택과 보완 설계

### 4.1 선택 (`tools/dp_selection.py`, 우선순위 proposal)
별 합계 1안 9, 2안 8로 **1안 Dispatcher** 선택, 우선순위를 뒤집어도 동일. 차이는 Q2의 별 하나다. 2안의 Q3 절감비 0.952는 ★★ 하한 0.95에 거의 붙어 있어 경계 의존적이나 선택은 같다. 단 **1안의 값은 σ = 0 전제**다.

### 4.2 보완 설계: Hybrid C (중앙 선택 + Tier 로컬 거부권) [Claude 제안, 미구현 [C]]
| 약점 (근거) | 택틱 | 상태 |
|---|---|---|
| TPOT 꼬리 P99 ×1.34 (snapshot 사이 부하를 Cost가 못 봄) | Tier Guard가 live 측정(노드 iteration 시간 + claim backlog)으로 거부하고 Dispatcher가 다음 후보 선택 | [C] |
| Cost 추정 오차 의존 (σ 0.4에서 ×0.91) | 오추정이 SLO를 넘기 전에 Guard가 최악 경계 역할 | [C] |
| 신호 추가 시 3 module | Tier 상태·한도를 Guard가 소유해 변경을 국소화 | [C] 가설 |

**왜 처음부터 C를 두지 않았나**: 혼합안은 이득이 Cost 모델에서 오는지 live 측정에서 오는지 분리할 수 없고, component와 인터페이스가 늘어 Q4에서 손해를 보는 것이 예상되므로 각 스타일의 장단을 먼저 측정해야 했다. 어떤 부분을 빌려 올지는 측정 후에 알 수 있었다(1안의 약점은 TPOT 꼬리와 추정 오차, 2안의 강점은 live 측정이고 약점은 cost 신호 부재). 그래서 C는 2안 전체가 아니라 admission 거부권만 빌린다. 이는 평가 후 정리한 이유이며 C의 효과는 검증되지 않았다.

## 5. 한계
- **노드 배정 고정 라우팅이 결과에 섞여 있다**(3.1). 16개 시나리오 중 13개가 2~4노드이고, 1노드만으로 DP2를 분리한 재평가는 하지 않았다.
- Evidence [B+C]: 같은 사람이 같은 simulator에서 구현한 proxy이고 vLLM 구현이 아니다. QA4의 공수와 비용은 가정 상수다.
- A와 B는 아키텍처와 규칙 집합이 함께 다르다. 2안의 결과는 "cost 신호 없는 Blackboard 규칙 집합"에 대한 것이며 cost 신호를 넣은 Blackboard 변형은 평가하지 않았다.
- 1안은 σ = 0에서 평가했고 오차 모델은 lognormal 한 종류다. QA3의 2안 값은 SLO 조건으로 7쌍이 제외된 14쌍 기준이다.
- 1안의 TPOT 꼬리 악화(×1.34)는 별점 geomean에서 TTFT 개선과 상쇄된다. TPOT 꼬리가 중요하면 그대로 쓸 수 없다.
- 노드 간 결정(DP4), 실제 trace, 실측 HW, endurance는 다루지 않았다. QA 우선순위는 제안 상태다.

## 6. 다음 단계
1. Hybrid C 구현 후 같은 benchmark로 Baseline-regression 평가.
2. board에 cost 신호를 넣은 Blackboard 변형 평가, 1안의 σ ≥ 0.4 대응.
3. QA 우선순위 확정, DP4(노드 간)로 확장.

## 7. 파일 지도
| 종류 | 경로 |
|---|---|
| 결과 문서 | `../Evaluation/DP2/results/2026-10-10_dp2-arch-styles.md` (생성기 `../Evaluation/tools/gen_dp2_arch_result.py`) |
| 사전 등록 | `../Evaluation/DP2/arch-styles-plan.md`, `qa4-preregistration-arch.md`, `benchmark.md` §11 |
| 반복 로그 | `../Evaluation/DP2/results/iterations/loop-log.md` §3 |
| 원자료 | `../Evaluation/DP2/results/data/arch/` |
| 코드 | `../Evaluation/DP2/sim/dp2sim/{nodeint,arch_dispatcher,arch_blackboard,scenarios_node}.py`, 실행 `sim/{node_control,qa_eval_node,sens_arch,qa4_arch,qa4_apply}.py` |
| 발표 | `../slides/dp2-arch-styles-dispatcher-vs-blackboard.pptx` (+ 설명 `.md`) |
