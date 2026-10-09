# DP1 요구사항 도출: 기능 요구사항, 품질 속성, 품질 시나리오, 제약 사항

> 상태: **초안(제안)**. 작성 기준: `requirements-derivation` 스킬 Phase 2. 전제와 공통 제약은 [`project-context.md`](project-context.md), 과제 시나리오와 UC는 [`usecases.md`](usecases.md).
> 출처 표기: `DP문서`(위치 표기) / `도출`(Claude가 구조·시나리오에서 추론) / `사용자`. 수치 근거: `[DP문서]` `[기준]`(공통·DP1 평가 기준) `[가정]`(확정 필요). Evidence: 시뮬레이션 값은 모두 **[B+C]**이며 실측 [A]가 아니다(GC-1).
> 상태 열: `문서 확정`(DP1 문서에 명시된 내용) / `제안`(도출했거나 문서 내용을 요구사항 문장으로 바꾼 것, 사용자 확인 전).

## 0. 읽은 입력

| 구분 | 파일 | 읽은 범위 |
|---|---|---|
| 설계 | `DP1/dp1-ai-data-migration-decision-architecture.md` (2,780줄) | §1~§4, §5.8(Backend I/F), §18, §19, §25, §26 전체 읽음. §5.9, §6~§17, §20~§24는 목차와 요약 수준(C1/C2 컴포넌트 세부는 PPT와 §25로 대체) |
| 설계 | `DP1/dp1-constraints.md` | 전체 |
| 평가 | `Evaluation/qa-evaluation-criteria.md`, `common-benchmark.md` | 전체 |
| 평가 | `Evaluation/DP1/qa-criteria-dp1.md`, `benchmark.md`, `qa4-preregistration.md`, `qa_priority.json` | 전체 |
| 평가 결과 | `Evaluation/DP1/results/2026-10-02_dp1-qa-evaluation.md` | §0(최종 요약)만. §1~§7은 읽지 않음 |
| PPT | `DP1/DP-memory-backend-if.pptx`(1~14장), `DP1-appendix-qa-result.pptx`, `DP1-complement-design-tactics.pptx`, `affinity-mapper-role.pptx`, `DP1-appendix-c1-c2.pptx`(1~2장) | 텍스트 추출. 그림 요소는 읽지 못함 |
| **읽지 못함** | `dp1-c1-qa1-complement-design.md`, `dp1-vllm-uml.md`, `Evaluation/DP1/simulation-plan.md`(759줄), `system-specs.md`, `DP1-c1-qa1-*.pptx`, `DP1/ref/*.pptx`, `DP-memory-backend-if.pptx` 15~17장 | 필요 시 다음에 읽음 |

## 1. DP1 구조 재구성 (제약 도출용)

DP1은 **이미 존재하는 AI data(KV, Agent memory, LoRA, MoE expert, RAG 인덱스)를 runtime 중 언제, 무엇을, 어느 memory tier로 옮길지 결정**한다. initial placement는 대상이 아니다 (설계 §1, §3).

```text
Runtime Event ──► Migration Scheduler (event-driven, async)
                      │
        ┌─────────────┴──────────────┐
   C1 pipeline                  C2 pipeline
   Resource State Monitor       Data Behavior Monitor
   Resource Trend Analyzer      Behavior Trend Analyzer
   Data Eviction Manager        Future Behavior Predictor
   Data-Memory Affinity Mapper  (type-aware Registry)
   (type-agnostic Registry)
        └─────────────┬──────────────┘
        Migration Data Selector + Destination Tier Selector
                      │ MigrationIntent {MOVE|REPLICATE|DROP|REMAP|RECLASSIFY}
                      ▼
            공통 Migration subsystem (범위 밖: reserve/copy/commit/rollback)
 
 Resource Manager (Telemetry Collector, Memory Registry)
        ▲ ② Telemetry · ① Descriptor · ③ Binding
 공통 Memory Backend I/F (plug-in): HBM · ScHBM · DRAM · CXL-PNM · HBF · SSD · SSD-PIM · +New
```

- 설계 쟁점 1 (C1/C2): 메모리 특성과 데이터 특성을 aware한 migration. 쟁점 2: 신규 메모리 확장 시 기존 구조 변경 최소화(Backend I/F).
- DP1이 하는 일: WHEN(Scheduler), WHAT/WHERE(C1/C2). 공통 Migration subsystem이 하는 일: HOW(전송, 순서, 일관성, commit/rollback). (설계 §2)
- 평가 상태: **C1 선택**(별 합계 10 대 9, 근소, 별 경계에 민감). 이 요구사항은 C1/C2 **공통**과 **후보별**로 나눠 쓴다. (평가 결과 §0.3, status: draft)

## 2. 기능 요구사항 (DP1-FR)

### 2.1 공통 요구사항 (C1, C2 모두)

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP1-FR-01 | 시스템은 메모리 압박, 요청 도착·종료, 자원 상태 변화 같은 runtime event가 발생하면 **서빙 경로(forward)를 막지 않고** migration 평가 cycle을 시작해야 한다 | DP문서 §2, §5.2, C-P4 | Migration Scheduler | UC-1, 3, 9 | event 발생 시점과 forward 지연 비교(TPOT 증분), event-to-decision 지연 | 문서 확정 |
| DP1-FR-02 | 시스템은 평가 cycle마다 **이동할 data object와 목적지 tier를 결정**하고, 결과를 `MigrationIntent`(action, 대상, source, target, reason, priority)로 공통 Migration subsystem에 전달해야 한다. DP1 자신은 위치를 직접 바꾸지 않는다 | DP문서 §2, C-S6 | Migration Data Selector, Destination Tier Selector | UC-1~5 | Intent 로그와 실제 commit 결과 대조 | 문서 확정 |
| DP1-FR-03 | 시스템은 byte copy 없는 선택지(**DROP, REMAP, RECLASSIFY**)와 복사 선택지(MOVE, REPLICATE)를 모두 표현해야 한다. 데이터를 잃는 DROP(replica도 재계산 경로도 없는 authoritative copy)은 금지한다 | DP문서 §2.1, C-R2 | MigrationAction, Registry의 replica·recomputable 정보 | UC-1, 3, 4 | DROP reject 테스트, action별 Intent 생성 | 문서 확정 |
| DP1-FR-04 | 시스템은 모든 data object의 **위치, 크기, 현재 tier, 이동 가능 상태**를 조회할 수 있어야 한다. 위치 갱신은 공통 Migration subsystem의 commit 결과로만 이뤄진다 | DP문서 §5.3, C-S6 | Data Object Registry (C1: type-agnostic, C2: type-aware) | UC-1~5 | Registry와 실제 위치 일치 property test | 문서 확정 |
| DP1-FR-05 | 시스템은 각 memory의 **capacity, bandwidth, load, 링크 사용률**을 서빙 경로 밖에서 주기적으로 수집하고, 수집 시각을 기록해 오래된 값(허용 age 초과)은 값 없음으로 취급해야 한다 | DP문서 §5.8.2.3, §5.8.4 | Telemetry Collector, Memory Backend I/F ② | UC-1, 9 | snapshot age 테스트, decision 경로에서 backend 직접 호출 0 | 문서 확정 |
| DP1-FR-06 | 시스템은 목적지 후보를 **memory 이름이 아니라 capability(용량, BW, 지연, GPU 접근 가능 여부, 지원 연산, 전송 비용)** 로 걸러야 한다. 이름 기반 분기(`if tier == "CXL"`)를 두지 않는다 | DP문서 §5.8.7 원칙 1, 2 | Memory Registry, Destination Tier Selector, Descriptor ①, Binding ③ | UC-6 | 신규 memory 추가 시 decision 코드 diff 0 | 문서 확정 |
| DP1-FR-07 | 시스템은 신규 memory를 **plug-in 1개 + Descriptor 1개(+ 필요 시 TransferHandler 1개)** 추가만으로 편입해야 하며, capability vocabulary는 추가만 허용한다(기존 의미 변경 금지) | DP문서 §5.8.6, §19.4 | Memory Backend I/F (쟁점 2) | UC-6 | QS-5 | 문서 확정 |
| DP1-FR-08 | 시스템은 이동이 사용하는 링크 시간을 **서빙 링크 시간의 제한된 몫(budget)** 안에서만 쓰고(foreground 승격을 background 정리보다 우선), 예상 서빙 이득이 이동 비용보다 작으면 이동하지 않아야 한다 | DP문서 §26-14, C-P1, C-P2 | Migration Scheduler budget, benefit-vs-cost gating | UC-9 | 링크 점유율, 이동 전후 서빙 지연 | 문서 확정 (gating은 C2에 적용, C1은 미구현 T2) |
| DP1-FR-09 | 시스템은 서빙 penalty를 키우거나 **SLO를 위반하는 tier**(예: attention 경로 TPOT 300~600 ms인 tier)로 data를 보내지 않아야 한다 (do-no-harm) | DP문서 C-P3 | Destination Tier Selector의 SLO 필터 | UC-1, 3, 6 | 시나리오별 SLO 만족 여부 | 문서 확정 |
| DP1-FR-10 | 시스템은 이동 **대상을 불변(sealed) data로 한정**하고, 실행 중 요청이 참조하는 block(ref_cnt > 0)의 물리 위치는 그 step 중에 바꾸지 않아야 한다. 이동 중인 source는 eviction이나 재할당을 당하지 않는다 | DP문서 C-H3, C-H5, C-H6 | KVDataAdapter `can_migrate_now`, source pin | UC-1, 2 | tail block 이동 reject 테스트, 실행 중 block 이동 시도 테스트 | 문서 확정(vLLM 코드 확인 포함) |
| DP1-FR-11 | 시스템은 이동·복제·복원·재배치를 해도 **모델 출력이 placement와 무관**해야 한다(같은 precision이면 bit-exact) | 사용자(GC-7), DP문서 C-I6 | 공통 Migration subsystem 의존(G1), DP1은 이를 깨는 action(변환, 압축) 금지(C-S5) | 전체 | 이동 전후 hash 비교, 출력 token 비교 | 문서 확정 |
| DP1-FR-12 | 시스템은 **이동 결정마다 reason, action, 대상, source, target, 이동 bytes, 예상/실제 전송 시간**을 기록해 관측 가능하게 해야 한다 | DP문서 §5.9.6, constraints §6.2(O1 관측), §19 | MigrationIntent.reason, 측정-추정 closed loop | 전체 | 로그 필드 완비율 | 제안 |
| DP1-FR-13 | 시스템은 memory health가 변하면(thermal throttle, 링크 열화, 용량 변화) 이를 event로 받아 migration을 **재평가**해야 한다 | DP문서 §5.8.2.3 규칙 5 | `RESOURCE_CHANGED` event | UC-9 | host link 대역폭 저하 시나리오에서 재평가 지연 | 문서 확정 |
| DP1-FR-14 | 시스템은 write 수명이 제한된 매체(HBF, SSD-PIM)로의 demotion을 **endurance 예산 안에서만** 수행하고, 가능하면 replica를 만들어 이후 DROP으로 끝내야 한다 | DP문서 §2.1, §5.9.5, C-R5 | `endurance_budget`, REPLICATE→DROP 경로 | UC-1, 3 | tier별 write bytes 추적(시뮬레이터 미모델링) | 문서 확정(검증 불가 표시 필요) |
| DP1-FR-15 | 시스템은 target 공간을 먼저 예약한 뒤 copy를 시작하고, 승격 교환(swap)이 서로의 slot을 기다리는 deadlock이 없도록 demotion을 먼저 단계화해야 한다 | DP문서 C-R1, C-R3 | Planner 단계화(DP1은 요청, 실행은 공통 subsystem) | UC-1, 9 | 용량 경계 테스트, swap 시나리오 | 문서 확정 |

### 2.2 C1 (Resource State-driven + Data-Memory Affinity) 특화

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP1-FR-C1-01 | 시스템은 memory의 capacity·BW·load가 임계 압박에 도달하거나 추세가 압박을 예고하면 **victim object를 골라 하위 tier로 내려야(demote)** 한다 | DP문서 §6, §8.2~8.4 | Resource State Monitor, Resource-based Trend Analyzer, Data Eviction Manager | UC-1, 2 | 압박 시나리오에서 HBM 점유 감소량 | 문서 확정 |
| DP1-FR-C1-02 | 시스템은 data class와 operation(attention, GEMV 등)별 **정적 선호 정보(latency/BW 민감도, 선호·금지 tier, 이동 비용 class)** 를 victim 선별과 목적지 선택에 반영해야 한다. 정적 정보는 설계 시점에 정의되며 학습하지 않는다 | DP문서 §8.6, affinity-mapper-role.pptx | Data-Memory Affinity Mapper (+ hint 표) | UC-3, 4, 5, 6 | 같은 압박에서 class별 victim 순서 | 문서 확정 |
| DP1-FR-C1-03 | 시스템은 하위 tier에 있지만 **HBM에 있어야 SLO를 만족하는 object를 승격**하고, 자리가 없으면 정적 페널티가 작은 HBM 거주 object와 교환해야 한다 | DP문서 §17.2, complement-design-tactics T1 | C1 promotion pass | UC-1, 3 | 승격 pass 제거 변형 대비 처리량(x1.05 대 x1.30) | 문서 확정 |
| DP1-FR-C1-04 | 시스템은 attention처럼 **연산 가능 tier가 지원하는 연산**이 있으면 그 tier(ScHBM, CXL-PNM, SSD-PIM의 GEMV)를 선호 목적지 후보에 포함해야 한다. 연산 자체의 실행 위치 결정은 DP2 소관이다 | DP문서 §3.2, §5.8.3(`near_data_compute` flag), affinity-mapper-role.pptx 3번 | Affinity Mapper, Descriptor primitive | UC-6 | 연산 지원 tier로의 배치 결정 확인 | 문서 확정 |

### 2.3 C2 (AI Data Behavior-driven) 특화

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP1-FR-C2-01 | 시스템은 object별 **접근 빈도, 재사용, lifetime, tool 관련 행동**을 관측하고 data class별 특성을 type-aware Registry에 유지해야 한다 | DP문서 §11, §13.2, §13.3 | Data Behavior Monitor, type-aware Registry | UC-1, 3, 4, 5 | 관측 필드 완비, 오버헤드 측정 | 문서 확정 |
| DP1-FR-C2-02 | 시스템은 관측한 행동 trend로 **미래 접근을 예측**해 hot이 될 object는 미리 상위로, cold가 될 object는 하위로 옮겨야 한다. 같은 data class 안의 hot/cold를 구분한다 | DP문서 §13.4, §13.5 | Behavior-based Trend Analyzer, Future Behavior Predictor | UC-1, 3, 5 | `dyn_*` 시나리오 이득, 예측 hit/miss 구분 | 문서 확정 |
| DP1-FR-C2-03 | 시스템은 예측이 틀려 오배치하거나 같은 object를 왕복 이동(thrashing)하지 않도록 **신뢰도, hysteresis, cooldown, migration budget**을 적용해야 한다 | DP문서 §26-8 | C2 Anti-thrashing | UC-1, 9 | 왕복 이동 비율, 예측 오차 sweep(e=0~0.6) | 문서 확정(세부 미설계) |

### 2.4 과제 UC와 DP1의 관계 (`usecases.md` FR과 대조)

| 과제 FR (usecases.md) | DP1이 담당하는 부분 | DP1이 담당하지 않는 부분 |
|---|---|---|
| FR-1~3, 5 (UC-1 idle KV demote, 재방문 재사용, 공간 부족 정리) | DP1-FR-02, 03, 10, C1-01/03, C2-02. **ref_cnt = 0인 cached block**(요청 종료 후 prefix cache로 남은 block)을 이동한다. 이는 UC-1의 가정 Q-1(a)와 일치한다 | **tool 호출 시점의 KV 유지/회수/복구(lifecycle) 제어와 FR-4 prefetch는 DP1 범위 밖**(설계 §3.2, "별도 DP"). DP1은 접근 행동·자원 압박만으로 판단한다 |
| FR-7, 8 (UC-2 long-context가 HBM 초과) | demote로 용량 확보. 단 **실행 중 요청의 block(ref_cnt > 0)은 step 중 이동하지 않음**(C-H5)이라 in-flight 요청의 KV는 REPLICATE 후 step 경계 REMAP이 필요하다 | FR-9 (정확도 손실이 있는 선택적 Drop)은 DP3 소관. DP1의 DROP은 replica/recomputable에 한정된 **무손실** |
| FR-10, 11 (UC-3 RAG hot/cold) | DP1-FR-C1-02, C2-02. 평가에 RAG 시나리오(`rag_*`) 포함 | Phase 1은 sealed KV만(C-D1). RAG 인덱스 이동은 후속 phase |
| FR-13~15 (UC-4 LoRA), FR-16, 17 (UC-5 MoE) | REPLICATE(LoRA 복제), 선호 tier(MoE→BW-rich tier). 평가에 `lora_*`, `moe_*` 시나리오 포함 | **Phase 1은 sealed KV만**(C-D1). LoRA/MoE는 immutability 정의 후 후속 phase. 설계 문서와 평가의 범위가 어긋난다(§8 D-4) |
| FR-18~20 (UC-6 연산 가능 메모리) | Descriptor에 지원 연산·성능을 받고(FR-06) 연산 지원 tier를 선호(C1-04) | **연산 위치 결정(GPU vs PIM/PNM)과 fallback은 DP2**. near-data compute는 DP1 action이 아님(C-S5) |
| FR-21~25 (UC-7, 8 노드 간, P/D) | 없음. 노드 간 이동은 DP0/DP4 소관(C-S1, S2) | 전부 |
| FR-26~28 (UC-9 혼합 부하) | DP1-FR-08(링크 budget), 13 | FR-27(과부하 admission/우선순위)은 DP0 |
| FR-6 (출력 불변) | DP1-FR-11 | 일관성 보장 자체는 공통 Migration subsystem(G1) |

## 3. 품질 속성 (QA)

### 3.1 (a) DP1이 선정한 QA

DP1은 4개를 선정했다 (`DP-memory-backend-if.pptx` 1장, 설계 §18, `qa-criteria-dp1.md`). 이름·지표는 원문을 따른다.

| ID | QA | metric (원문) | DP1 별점 기준 (공식, v5) | 출처 |
|---|---|---|---|---|
| DP1-QA1 | Performance — Throughput | **Max SLO Goodput** (output token/s). SLO를 만족한 request의 output token만 센 goodput의 sweep 최대값. 공통 지표명 TPS | Baseline 대비 ratio: ★ < 0.97 / ★★ 0.97~1.30 / ★★★ ≥ 1.30 (comparison-valid 시나리오의 geometric mean) | PPT 1장, 설계 §18·19.1, `qa-evaluation-criteria.md` §4, `qa-criteria-dp1.md` §A |
| DP1-QA2 | Performance — Latency | **TTFT와 TPOT를 분리**. P50/P95/P99. 별점은 (TTFT, TPOT) x (P50, P95, P99) 6개 개선 배수(Baseline ÷ 후보)의 geometric mean | ★ < 0.95 / ★★ 0.95~1.25 / ★★★ ≥ 1.25. 공통 절대 기준: TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms (★★★) | PPT 1장, 설계 §18·19.2, 공통 §5 |
| DP1-QA3 | Resource Utilization | DP1 공식(v6): **HBM 사용량(GiB, tier `hbm`의 시간 평균 점유)** 의 Baseline 대비 비율, 낮을수록 좋음. 진단: pooled useful utilization U, tier별 사용률, 링크 점유, 이동량, 비용 가중 점유 | 절감 배수(1/비율): ★ < 0.95 / ★★ 0.95~1.25 / ★★★ ≥ 1.25. 공통 절대 기준 U: ★ < 65% / ★★ 65~85% / ★★★ ≥ 85% (참고 병기) | PPT 1장, 설계 §19.3, `qa-criteria-dp1.md` §I, 공통 §6 |
| DP1-QA4 | Modifiability | 변경 module 수, 개발 공수(man-month), code-agent 토큰 비용($). 4개 변경 시나리오(신규 memory, 신규 data class, 정책 교체, 신규 event)를 구현해 측정, 시나리오 평균 | M1: ★★★ ≤ 2 / ★★ 3~5 / ★ ≥ 6 module(또는 major interface 변경). M2: ≤ 0.5 / ≤ 1.0 / > 1.0 MM. M3: ≤ $3 / ≤ $10 / > $10 (frontier tier). QA4 별 = 세 sub-star의 중앙값 | PPT 1장, 설계 §19.4, `qa4-preregistration.md` |

QA 우선순위(소유자 확정, status: proposal): QA1 > QA2 > QA3 > QA4 (`qa_priority.json`).

### 3.2 (b) 추가 후보 QA (DP1 시나리오와 관련 있어 보이는 것)

> 선정 여부는 사용자 결정이다. 아래 `권장/보류`는 Claude의 의견이다. 프로젝트 전제로 Reliability/Availability 중 device runtime 내부 오류와 복구는 범위 밖이고(GC-3), 우리 계층의 degradation 처리는 후보다.

| ID | QA | 관련 이유 (어느 구조·시나리오 때문에) | 미선정 시 위험 | 선정 QA와의 관계 | 의견 |
|---|---|---|---|---|---|
| DP1-QA5 | **Decision Latency / Scalability** (결정 지연, object·tier 수 증가 시 결정 비용) | 설계 §19.2가 `T_event_to_decision = T_queue + T_monitor + T_analysis + T_selection`을 정의했다. 평가에서 결정 연산 C2 111 ms/run 대 C1 3 ms/run. 공통 QA 문서도 Decision Latency를 후속 QA로 예고(§1) | 결정이 늦어지면 hot object 승격 시점을 놓쳐 QA1/QA2 이득이 사라진다. C2의 monitoring/prediction 비용이 이득과 상쇄될 수 있음 | QA1/QA2와 trade-off(정확한 예측일수록 결정 비용 증가). QA4(C2 특화 모듈 증가)와도 연동 | **권장** |
| DP1-QA6 | **Stability / Predictability** (thrashing, 꼬리 지연, 예측 오차에 대한 강건성) | C2는 예측이 틀리면 오배치가 생긴다(PPT 9장 단점, 설계 §15). 링크 간섭 반영 후 C2 migration 1,339 GiB(C1 138 GiB)로 TTFT 꼬리가 영향받음. C1은 TTFT P99가 Baseline 대비 x1.04~x1.27 악화하는 사례. 모델 오차 sweep(H17) | 평균은 좋아도 P99 꼬리나 왕복 이동으로 SLO가 깨진다 | QA2(꼬리)와 직접 연결, QA1과는 이득을 얻기 위한 이동량과 충돌 | **권장** |
| DP1-QA7 | **Functional Correctness (무결성)** — 이동 후 data 일치, 이동 중 접근 정합성 | 사용자 확정 GC-7(DP3 제외 모두 출력 불변). 제약 C-I6, C-H1~H9가 요구. 시뮬레이터는 hazard를 모델링하지 않는다(C-E1) | 이동이 silent corruption을 일으키면 성능 이득이 무의미 | QA1~QA3와 독립(사전 조건) 성격이지만 설계 검토 대상으로 QA화하면 검증 가능 | **권장** (DP1 책임 범위는 "깨는 action을 하지 않는다"까지. 보장은 공통 subsystem) |
| DP1-QA8 | **Availability — degradation 처리** (링크·메모리 상태 열화 시 재평가와 성능 유지) | `RESOURCE_CHANGED` event(설계 §5.8.2.3 규칙 5), Dynamic 시나리오 `dyn_host_path_contention_kv`(host link 25%로 저하), `host_path_pressure_b64`, `hbm_bw_shock_b256`. device runtime 내부 장애·복구는 GC-3으로 범위 밖이고 **우리 계층의 대응만** 대상 | 열화된 경로에 spill 상태를 유지해 SLO 위반이 지속 | QA2(꼬리)와 연계 | **권장** |
| DP1-QA9 | **Observability** (이동 결정·이유·비용 추적) | constraints §6.2: DP1이 O1 overhead를 통제할 수 없지만 **관측은 할 수 있어야 한다**. `est_transfer_s` 노출, 측정-추정 closed loop(§5.9.6). 평가의 diagnostic 전부가 관측값에 의존 | 이득이 어디서 오는지, 결정이 왜 틀렸는지 알 수 없어 정책 튜닝과 디버깅 불가 | 모든 QA의 검증 수단 | **권장** (정량화는 완비율 수준) |
| DP1-QA10 | Endurance (HBF/SSD-PIM write 수명 보호) | C-R5, `endurance_budget`, §5.9.5. 시뮬레이터 미모델링(C-E3), 차세대 메모리는 시뮬레이션 기반(GC-1) | 장기 운용 시 수명 소진 가능 | QA1/QA3의 이동 정책과 충돌(이동 줄이면 이득 감소) | **보류**: 측정 근거가 없어 정량 시나리오를 만들 수 없음. 제약(§5)으로만 둠 |
| DP1-QA11 | Interoperability (vLLM upstream 호환: block pool, kv_offload, CUDA graph, async scheduling) | C-H2, C-H5, C-X2, `v1/core/block_pool.py`. DP0 C4(upstream 추적) | upstream 변경 시 DP1 hook이 깨짐 | QA4와 겹침 | **보류**: 평가 기준과 데이터 없음. 제약으로 기록 |
| DP1-QA12 | Cost efficiency (비용 가중 점유) | 비용 가중 점유(`cost_model.py`, DRAM 대비 상대 $/GiB, ASSUMED)를 QA3 보조로 병기 중 | HBM 대신 더 싼 tier로 보냈는지 구분 못함 | QA3의 보조 | **보류**: 가격이 가정값. QA3 진단으로 유지 |
| DP1-QA13 | Security / Isolation (tenant 격리) | C-H10(이동·해제된 slot 내용 노출 방지) | — | — | **제외**: 프로젝트 범위 밖(GC-6). 기존 cache salt 정책 유지가 전제 |

## 4. 품질 시나리오 (6요소, 정량)

공통 사항: 환경의 평가 시스템은 **SYS-H100, SYS-B200**(각 8-GPU 1노드, Llama-3.1-70B BF16, 6종 메모리: HBM, ScHBM, CXL-PNM, DRAM, HBF, SSD-PIM)이며 호스트 링크는 PCIe 5.0 x16이다. 비교 대상 **Baseline-static**은 As-Is proxy(초기 배치 후 migration 없음)다. 별 경계는 `qa-criteria-dp1.md` §A(v5, 결과를 본 뒤 정함 `defined_after_first_look`)이며 근거 `[기준]`이다. 시뮬레이션 값은 [B+C]이고, 차세대 메모리 성능은 GC-1, device runtime 오버헤드는 GC-2에 따라 반영하지 않는다. "현 평가값"은 이미 계산된 값으로 목표 달성 여부를 판단하는 참고다 (평가 결과 §0.1, 21쌍, 선택 C1).

### 4.1 선정 QA

#### DP1-QS-1 Throughput — 사용자 그룹이 교대로 활성화될 때의 처리량 (구분: 선정, DP1-QA1)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 다수의 agent/chat 요청 클라이언트(사용자 그룹) |
| 2. 자극 | 사용자 그룹이 60 s 주기로 번갈아 활성화되어 hot KV 집합이 바뀐다(`dyn_kv_rotating_hotset`: KV 320K context, batch 16). 부하는 request-rate sweep x0.5~2.0 |
| 3. 환경 | 정상 운전, HBM 용량 x0.3 압박, SYS-H100과 SYS-B200, Llama-3.1-70B BF16, 6종 메모리 사용 가능, SLO: TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms |
| 4. 자극 대상체 | DP1 migration decision pipeline (Migration Scheduler → C1/C2 pipeline → Destination Tier Selector → MigrationIntent) |
| 5. 응답 | 새로 활성화된 그룹의 KV를 상위 tier로 승격하고 비활성 그룹의 KV는 하위 tier로 내려 SLO를 유지한 채 처리량을 높인다 |
| 6. 응답 측정 | **Max SLO Goodput(output tok/s) ≥ 1.30 × Baseline-static** — comparison-valid 쌍(Common + Stress + Dynamic, H100+B200 통합, 현재 21쌍) 쌍별 비율의 **geometric mean**, 95% CI 하한 > 1.0, seed ≥ 5. `[기준: DP1 QA1 ★★★ 경계]` 근거는 DP1의 정책 판단(migration layer 정당화에 30% 이상 필요, GPU 약 1.85장분) |
| 현 평가값 | C1 x1.30 (1.298, 95% CI가 경계에 걸림), C2 x1.42. 이득은 static 배치가 stale해지는 dynamic 조건에서만 확인(C2 6/6, C1 3/6 Dynamic 시나리오) [B+C] |
| 연결 | QA: DP1-QA1. UC-1, 3. FR: DP1-FR-02, C1-01/03, C2-02. 평가: `Evaluation/DP1/benchmark.md` G.2 |

#### DP1-QS-2 Throughput — 이득이 없는 정상 상태에서의 퇴보 금지 (구분: 선정, DP1-QA1)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 일반 chat 서비스의 요청 클라이언트 |
| 2. 자극 | 공통 시나리오 CB-1~3(`cb_kv_8k_b32`, `cb_kv_8k_b32_ramp`, `cb_mixed_8k_b32`): 입력 8K, 출력 256 토큰, 동시 32, HBM x0.12 압박/ramp, KV + LoRA + MoE + Agent/Tool 혼합. 부하 sweep |
| 3. 환경 | 정상 운전, SYS-H100과 SYS-B200, Llama-3.1-70B BF16, 기본 SLO(TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms) |
| 4. 자극 대상체 | DP1 migration decision pipeline 전체와 Migration Scheduler의 benefit-vs-cost gating |
| 5. 응답 | 이동의 이득이 없으면 이동하지 않아(do-no-harm) Baseline 수준의 처리량을 유지한다 |
| 6. 응답 측정 | **Max SLO Goodput ≥ 0.97 × Baseline-static**, CB-1~3 모든 (시나리오, 시스템) 쌍에서, seed ≥ 5. `[기준: 하한 0.97 = Baseline끼리 5묶음 측정한 잡음 대역 0.968~1.033, qa-criteria-dp1 §J.1]` |
| 현 평가값 | 공통 시나리오에서 두 후보 모두 Baseline과 같은 수준(parity) [B+C] |
| 연결 | QA: DP1-QA1. FR: DP1-FR-08, 09. 평가: `common-benchmark.md` §2.1 |

#### DP1-QS-3 Latency (TTFT) — 도착 burst에서의 첫 응답 지연 (구분: 선정, DP1-QA2)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 요청 클라이언트(burst로 도착하는 요청군) |
| 2. 자극 | HBM 여유가 적은 상태에서 요청이 burst로 도착(`kv_b16_c32k_burst_chbm`: KV 32K, batch 16, HBM x0.12), 같은 시점에 cold 객체가 상위 tier를 점유 |
| 3. 환경 | 정상 운전(과부하 직전), SYS-H100과 SYS-B200, 부하 sweep |
| 4. 자극 대상체 | Destination Tier Selector와 Migration Scheduler(승격 경로, 링크 budget) |
| 5. 응답 | 도착한 요청의 KV가 느린 tier에 있어도 승격이나 접근 경로 선택으로 TTFT를 줄이고, 이동 트래픽이 TTFT 꼬리를 키우지 않는다 |
| 6. 응답 측정 | **TTFT P99 ≤ 2 s** `[기준: 공통 SLO]`, **6개 지표(TTFT·TPOT x P50·P95·P99) 개선 배수(Baseline ÷ 후보)의 geometric mean ≥ 1.25** `[기준: DP1 QA2 ★★★ 경계]`(TTFT와 TPOT 개선 배수는 항상 따로 보고, SKILL H23), **TTFT P99가 Baseline의 1.10배를 넘는 (시나리오, 시스템) 쌍 = 0** `[가정]`(근거: Baseline 잡음 sd 약 0.017~0.020의 약 5배 여유. 확정 필요, Q-D1). seed ≥ 5 |
| 현 평가값 | TTFT P99: Baseline 1,084 ms, C1 1,128 ms (x1.04, 악화), C2 785 ms (x0.72). 6지표 개선 배수 C1 x1.28, C2 x1.56 (둘 다 목표 1.25 충족, C1은 경계 바로 위). TTFT 개선 배수 C1 x1.58, C2 x2.18. 쌍별 최악 값은 이 문서에서 확인하지 못함(결과 §4 필요) [B+C] |
| 연결 | QA: DP1-QA2. UC-1, 3, 9. FR: DP1-FR-C1-03, C2-02, DP1-FR-08. 평가: QA2 §5 |

#### DP1-QS-4 Latency (TPOT) — decode 중 토큰당 지연 (구분: 선정, DP1-QA2)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 요청 클라이언트(긴 context의 decode 중 요청) |
| 2. 자극 | 압박이 시간에 따라 증가하는 상황(`hbm_pressure_ramp_b64`: KV + LoRA + MoE, 128K, batch 64, HBM capacity ramp) 중 hot KV·expert가 느린 tier로 밀림 |
| 3. 환경 | 정상 운전 → 압박 증가, SYS-H100과 SYS-B200, 부하 sweep |
| 4. 자극 대상체 | Resource State Monitor/Trend Analyzer(C1) 또는 Behavior Predictor(C2), Data Eviction Manager, Destination Tier Selector |
| 5. 응답 | 압박이 오기 전에 선제적으로 이동하고 attention 경로의 TPOT가 SLO를 넘는 tier로 data를 보내지 않는다 |
| 6. 응답 측정 | **TPOT P99 ≤ 50 ms** `[기준: 공통 SLO]`, TPOT P99가 Baseline의 1.10배를 넘는 쌍 = 0 `[가정, Q-D1]`. 별점 기준인 6지표 geomean ≥ 1.25는 QS-3에 있고, 여기서는 TPOT를 따로 보고한다(SKILL H23). seed ≥ 5 |
| 현 평가값 | TPOT P99: Baseline 17.1 ms, C1 18.3 ms (x1.07), C2 16.0 ms (x0.94). TPOT 개선 배수 C1 x1.04, C2 x1.12. Baseline이 이미 SLO(50 ms)의 약 1/3이라 TPOT 단독 개선 폭은 작고, QA2 별의 개선은 주로 TTFT에서 나온다. C1은 TPOT P99가 Baseline보다 7% 나쁘다 [B+C] |
| 연결 | QA: DP1-QA2. FR: DP1-FR-09, C1-01. 평가: QA2 §5, 결과 §0.1 |

#### DP1-QS-5 Resource Utilization — 쓰지 않는 data가 HBM을 점유할 때 (구분: 선정, DP1-QA3)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 요청 클라이언트(chat 요청이 갑자기 몰림). 선행 상태는 idle Agent memory·KV |
| 2. 자극 | 오래 보관만 되던 Agent memory(약 320K context 규모)가 HBM을 선점한 상태에서 chat 요청이 폭주(`dyn_cold_resident_chat_wave`, `dyn_idle_kv_holds_hbm`: KV 320K, batch 16, HBM x0.4) |
| 3. 환경 | 정상 운전, SYS-H100과 SYS-B200, 6종 메모리, 부하 sweep |
| 4. 자극 대상체 | Data Eviction Manager(C1) / Data Behavior Monitor와 Predictor(C2), Data Object Registry, Destination Tier Selector |
| 5. 응답 | 쓰이지 않는 data를 HBM에서 하위 tier로 내려 hot KV가 HBM에 있게 한다 |
| 6. 응답 측정 | **HBM 사용량(GiB, 시간 평균)이 Baseline의 0.80배 이하**(절감 배수 ≥ 1.25), comparison-valid 쌍 geometric mean, seed ≥ 5 `[기준: DP1 QA3 ★★★ 경계]`. **동시에 QS-1(≥ 1.30)과 QS-3·4의 SLO를 만족**해야 인정(HBM을 비우되 성능이 나빠지는 정책 배제). 진단 병기: tier별 사용률, 링크 점유율 |
| 현 평가값 | HBM 사용량: Baseline 146.6 GiB, C1 142.7 GiB (x0.97, 절감 1.03), C2 178.0 GiB (x1.21, 절감 0.82). **두 후보 모두 목표 1.25에 미달**. C2는 성능을 얻으려 HBM을 더 쓴다. 공통 기준 pooled U는 모든 후보 ★(< 65%) [B+C] |
| 연결 | QA: DP1-QA3. UC-1, 3, 9. FR: DP1-FR-C1-01, C2-02. 평가: `qa-criteria-dp1.md` §I |

#### DP1-QS-6 Modifiability — 신규 메모리 편입 (구분: 선정, DP1-QA4)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자(신규 메모리 통합 담당) |
| 2. 자극 | 신규 memory 1종 추가 요구. 예: CXL.mem DRAM expander(1 TiB, 외부 63 GB/s, 내부 200 GB/s, 지연 600 ns, PNM primitive 없음) — 사전 등록 시나리오 S1 |
| 3. 환경 | 개발 시점. 기존 7종 plug-in(HBM, ScHBM, DRAM, CXL-PNM, HBF, SSD, SSD-PIM) 등록 상태, vLLM revision 고정 |
| 4. 자극 대상체 | Common Memory Backend I/F(Descriptor, Telemetry, Binding)와 그 위의 Destination Tier Selector, Resource State Monitor, Registry, Affinity Table |
| 5. 응답 | Backend plug-in 1 + Descriptor 1(+ TransferHandler 1) 추가만으로 편입하고, decision plane은 변경하지 않으며 기존 주요 interface를 유지한다 |
| 6. 응답 측정 | **변경 module ≤ 2**(`decision/` 하위 변경 파일 = 0, 추가 파일 = Backend plug-in 1 + Descriptor 1 + Handler ≤ 1) `[DP문서 §19.4]`, **개발 공수 ≤ 0.5 MM**, **code-agent 비용 ≤ $3**(frontier tier) `[기준: qa4-preregistration §5]`, smoke: 신규 memory를 목적지로 한 committed migration ≥ 1건. 공수·비용은 ASSUMED 상수 기반 추정 [B+C] |
| 현 평가값 | 4개 시나리오 평균(S1~S4): C1 1.75 module / 0.38 MM / $1.16, C2 2.50 module / 0.51 MM / $1.49. C2 공수 평균은 경계 0.5를 0.006 넘은 값이라 상수에 민감. S1 단독 값은 이 문서에서 확인하지 못함 |
| 연결 | QA: DP1-QA4. UC-6. FR: DP1-FR-06, 07. 평가: `qa4-preregistration.md` S1 |

#### DP1-QS-7 Modifiability — 신규 data class와 정책·event 변경 (구분: 선정, DP1-QA4)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자 |
| 2. 자극 | (S2) 신규 AI data class 추가: `SPARSE_EMBED`(8~64 GiB, touch 2%, write .05). (S3) 정책 교체: C1 Affinity Mapper를 latency-first 점수로, C2 Predictor를 "관측 rate만 쓰는" 예측기로. (S4) 신규 event type `SLO_ALERT`(HBM capacity_util ≥ 0.94) 추가 |
| 3. 환경 | 개발 시점, 기존 pipeline 동작 중, 생성자 주입 방식으로 교체 가능 |
| 4. 자극 대상체 | C1: Registry·Affinity hint 표·Estimator hint. C2: Type-aware Registry·class prior·Predictor. 공통: Event Source, Scheduler 이벤트 schema |
| 5. 응답 | 새 class/정책/event가 기존 구조 변경 없이 추가되어 의도대로 동작한다(class 인식 결정, 교체 구현 호출, decision cycle 시작) |
| 6. 응답 측정 | 시나리오당 **변경 module ≤ 2, 공수 ≤ 0.5 MM, 비용 ≤ $3**, 4개 시나리오 평균 적용(평균 집계는 결과를 본 뒤 변경, `defined_after_first_look`). major interface 변경 0(필드·enum 추가는 허용) `[기준: qa4-preregistration]`. smoke 합격 기준(spy 호출 > 0 등) 통과 [B+C] |
| 현 평가값 | 시나리오 평균은 QS-6의 값과 같다(합산 평균). C1은 새 data class에 module 1개, C2는 3개(결과 §0.2) |
| 연결 | QA: DP1-QA4. FR: DP1-FR-C1-02, C2-01. 평가: `qa4-preregistration.md` S2~S4 |

### 4.2 추가 후보 QA (채택 전 초안)

#### DP1-QS-8 Decision Latency / Scalability — 결정 지연과 규모 (구분: 추가, DP1-QA5)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | Runtime event(메모리 압박, 요청 도착, 자원 변화)를 일으키는 서빙 엔진 |
| 2. 자극 | event 폭주(HBM 압박 ramp 중 초당 수십 건)와 추적 object 수 증가(기본 40~48 object → 10배 규모, `six_tier_capacity_stress`, `mixed_all_ai_data_b64`) |
| 3. 환경 | 정상 운전, 6종 memory 활성, 시뮬레이션 기반(device runtime·commit overhead 제외, GC-2, C-E1) |
| 4. 자극 대상체 | Migration Scheduler(event coalescing 포함)와 C1/C2 decision pipeline |
| 5. 응답 | 서빙 경로(forward)를 막지 않는 비동기로 결정을 내리고, object 수가 늘어도 결정 시간이 선형 이하로 증가한다 |
| 6. 응답 측정 | **`T_event_to_decision`(= T_queue + T_monitor + T_analysis + T_selection) P99 ≤ 100 ms** `[가정]`(근거: 17.8 GiB KV object를 63 GB/s host link로 옮기는 시간 약 0.3 s의 1/3 이하여야 결정 지연이 이동 이득을 잠식하지 않음. 확정 필요, Q-D2). **서빙 경로 영향**: decision on/off 비교 TPOT P50 차이 ≤ 2% `[가정]`(Baseline 잡음 sd 1.7% 수준). **규모**: object 10배 시 cycle 시간 ≤ 10배(선형 이하) `[가정]`. seed ≥ 5 |
| 현 평가값 | 결정 연산 총량 C1 3 ms/run, C2 111 ms/run. event-to-decision 지연의 P99는 이 문서에서 확인하지 못함(미측정) [B+C] |
| 연결 | QA: DP1-QA5. FR: DP1-FR-01, C2-01. 평가: 설계 §19.1~19.2 |

#### DP1-QS-9 Stability — 급반전 접근 패턴에서 thrashing과 꼬리 (구분: 추가, DP1-QA6)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 요청 클라이언트(hot/cold가 급반전하는 workload) |
| 2. 자극 | 객체별 hotness 급반전(`behavior_flip_stress`: mix5, KV 32K, batch 16, RAG idx 512 GiB)과 예측 오차 e = 0.2/0.4/0.6 (lognormal sigma) |
| 3. 환경 | 정상 운전, SYS-H100과 SYS-B200, 부하 sweep, 예측 모델 오차 주입 |
| 4. 자극 대상체 | C2 Anti-thrashing(신뢰도, hysteresis, cooldown, budget), C1 promotion·eviction 정책, Migration Scheduler budget |
| 5. 응답 | 같은 object를 왕복 이동하지 않고, 이동 트래픽이 서빙 링크를 일정 몫 이하로만 쓰며, 예측이 틀려도 Baseline 이상을 유지한다 |
| 6. 응답 측정 | **migration 링크 점유율 ≤ 25%**(평균) `[DP문서: C-P1 LINK_SHARE 0.25]`. **오차 e = 0.6에서도 Max SLO Goodput ≥ 0.97 × Baseline** `[기준: 하한 0.97]`. **cooldown 시간 내 반대 방향 재이동 비율 ≤ 5%** `[가정]`(근거 없음, 임의 제안. 확정 필요, Q-D3). seed ≥ 5 |
| 현 평가값 | 링크 점유율 C1 1.6%, C2 10.5%(둘 다 ≤ 25%). 오차 e ≤ 0.6까지 C2 우위 유지(결과 4.6, lognormal 한 종류라는 한계). 왕복 비율은 미측정 [B+C] |
| 연결 | QA: DP1-QA6. FR: DP1-FR-08, C2-03. 평가: 설계 §26-8, SKILL H17 |

#### DP1-QS-10 Functional Correctness — 이동 전후 무결성 (구분: 추가, DP1-QA7)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | DP1 Migration Scheduler가 낸 MigrationIntent(이동 결정) |
| 2. 자극 | 이동 중에 같은 prefix를 가진 요청이 도착(prefix hit), tail block 이동 시도, 실행 중 요청의 block 이동 시도, abort/preemption, prefix cache reset |
| 3. 환경 | 정상 운전, async scheduling 켠 상태, multi-GPU rank, 공통 Migration subsystem과 결합된 구현(시뮬레이터 아님) |
| 4. 자극 대상체 | DP1의 이동 대상 선택(`can_migrate_now`, sealed 한정, ref_cnt 확인)과 공통 Migration subsystem의 copy-then-commit |
| 5. 응답 | 이동 대상은 sealed, ref_cnt = 0인 object만 되고, 이동 후 data와 모델 출력이 이동 전과 동일하다 |
| 6. 응답 측정 | **이동 전후 KV block hash 불일치 0건**, **이동 유무에 따른 출력 token 불일치 0건**(같은 precision, bit-exact), **tail block·실행 중 block 이동 시도 reject 100%**, 위 항목을 hazard 주입 테스트(C-H1~H9)로 확인 `[DP문서: dp1-constraints 검증 방법]`. 확인 규모는 `[가정]`: 테스트당 ≥ 1,000 이벤트 |
| 현 평가값 | **미검증**. 시뮬레이터는 hazard가 없다고 가정(C-E1). 검증 책임은 공통 Migration subsystem (G1) |
| 연결 | QA: DP1-QA7. FR: DP1-FR-10, 11. 제약: DP1-C-6, 7, 11 |

#### DP1-QS-11 Availability(degradation) — host 경로 열화 시 대응 (구분: 추가, DP1-QA8)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 다른 작업과의 host link 공유 경합 또는 링크 열화(시스템 상태 변화, 외부 요인) |
| 2. 자극 | 실행 중간에 host link 대역폭이 25%로 저하(`dyn_host_path_contention_kv`: KV 128K, batch 16, hostBW x0.25), 또는 HBM 대역폭 급락(`hbm_bw_shock_b256`: x0.28) |
| 3. 환경 | 정상 운전 중 갑작스런 열화. device runtime 장치 오류는 제외(GC-3) |
| 4. 자극 대상체 | `RESOURCE_CHANGED` event 처리, Telemetry Collector, Destination Tier Selector |
| 5. 응답 | 열화를 event로 감지해 재평가하고 열화된 경로에 spill 상태를 유지하지 않도록 data를 재배치해 SLO를 회복한다 |
| 6. 응답 측정 | **열화 후 SLO 만족 비율이 열화 전의 95%까지 회복되는 시간 ≤ 60 s**(= 1 hotset 주기) `[가정]`(근거: 평가 시나리오의 기본 hotset 주기 60 s. 확정 필요, Q-D4). **열화 구간 Max SLO Goodput ≥ 1.0 × Baseline-static**(CI 내 parity 이상) `[기준]` |
| 현 평가값 | `dyn_host_path_contention_kv`의 시나리오별 값은 이 문서에서 확인하지 못함. HBM BW shock는 시뮬레이터가 모델링하지 못해 평가 benchmark에서 제외(benchmark.md §2). 회복 시간 미측정 [B+C] |
| 연결 | QA: DP1-QA8. UC-9. FR: DP1-FR-13. 평가: `benchmark.md` G.1~G.2 |

#### DP1-QS-12 Observability — 이동 결정 추적 (구분: 추가, DP1-QA9)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자(성능 이상을 조사하는 운영·튜닝 담당) |
| 2. 자극 | 성능이 Baseline보다 나빠진 시나리오가 발견되어 원인 분석을 요청 |
| 3. 환경 | 운영 또는 평가 중, decision 로그가 켜진 상태 |
| 4. 자극 대상체 | MigrationIntent(reason 필드), Telemetry 이력, 측정-추정 closed loop |
| 5. 응답 | 이동 결정마다 reason, action, 대상, source, target, bytes, 예상·실제 전송 시간이 남고, 이를 근거로 root cause를 분류할 수 있다 |
| 6. 응답 측정 | **MigrationIntent 로그 필수 필드 완비율 100%** `[가정]`, **예상 전송 시간 대비 실제 전송 시간 오차를 이동마다 기록하고 오차 P50/P95를 보고** `[DP문서 §5.9.6]`. 평가의 diagnostic(tier별 access, migration 횟수/bytes, decision overhead)을 로그에서 재생성 가능 |
| 현 평가값 | 시뮬레이터는 diagnostic을 출력한다. 구현 수준 로그는 미정 |
| 연결 | QA: DP1-QA9. FR: DP1-FR-12. 평가: SKILL §5 root cause 분류 |

## 5. 제약 사항 (예상 질문 기반)

설계 구조도의 각 블록과 화살표에서 리뷰어가 던질 질문을 만들고, 설계 범위를 벗어나는 것을 제약으로 확정했다. 근거 칼럼의 `C-xx`는 `dp1-constraints.md`의 ID, `G/O`는 같은 문서 §6이다. 프로젝트 공통 제약은 `project-context.md`의 GC-n.

| ID | 예상 질문 | 제약 문장 | 유형 | 설계 영향 | 출처 | 근거 위치 |
|---|---|---|---|---|---|---|
| DP1-C-1 | "노드 간 이동은 누가 결정하나?" | DP1은 **단일 노드(한 서버) 안의** tier 사이 이동만 결정한다. 노드 간 이동과 원격 memory를 tier로 보는 이동은 DP0 소관이며 DP1과는 접점 계약(KV 이벤트 `medium`, 메트릭, `kv_transfer_params`)으로만 연결한다. 따라서 노드 간 KV 이동은 DP1 요구사항이 아니다 | 범위 밖/경계 | Registry의 tier 집합이 한 노드로 한정. 평가도 단일 노드 8-GPU만 모델링. (노드 간 PCIe 64GB/s는 GC-9) | DP문서 | 설계 §3.3, C-S1~S3 |
| DP1-C-2 | "처음 data를 어디에 놓나?" | **초기 배치(initial placement)는 범위 밖**이다. DP1은 이미 존재하는 object의 재배치만 결정한다. allocation 경로는 기존 그대로 | 범위 밖 | 할당 경로(`allocate_slots`)를 DP1이 바꾸지 않는다 | DP문서 | C-S4, 설계 §3.2 |
| DP1-C-3 | "KV 압축·양자화·near-data compute도 migration인가?" | **data 내용을 바꾸는 변환은 migration이 아니다.** DP1 action은 MOVE/REPLICATE/DROP/REMAP/RECLASSIFY뿐이다. 정확도 손실이 있는 KV Drop·압축은 DP3, 연산 위치 결정은 DP2 소관이다. DP1의 DROP은 replica나 재계산이 가능한 **무손실**에 한정한다 | 범위 밖/경계 | action enum 제한. 출력 동일성(GC-7) 보존 | DP문서 | C-S5, 설계 §2.1, §3.2 |
| DP1-C-4 | "tool 호출 시점에 KV를 유지/회수/복구하는 건 어디서 하나?" | **Agent tool-call lifecycle에 따른 KV residency 관리는 DP1이 하지 않는다.** DP1은 resource 상태와 data 접근 행동만 보고 "어떤 KV를 어느 tier로" 결정한다. 따라서 `usecases.md`의 FR-4(재개 전 prefetch)는 DP1 요구사항이 아니다 | 범위 밖/경계 | C1은 tool lifecycle을 해석하지 않고 static hint만 둔다. 보완은 별도 DP(어느 DP인지는 문서마다 다름, §8 D-1) | DP문서 | 설계 §3.2, PPT 10장 |
| DP1-C-5 | "실제 byte 전송, commit, rollback은 누가 하나? 그 overhead는?" | DP1은 **결정(WHAT/WHERE/WHEN)** 만 책임진다. byte 전송, reserve/release, source pin, version check, atomic commit, 실패 rollback은 공통 Migration subsystem 소관(G1)이며 그 **overhead(commit 지연, epoch grace에 의한 slot 점유 연장, 완료 통지 지연)는 DP1이 모델링하거나 최적화하지 않는다(O1)**. 따라서 DP1의 평가 수치는 "G1~G3이 비용 없이 성립한다"는 **조건부 값**이다 | 범위 밖/증거 한계 | 이득 수치는 실제 구현에서 줄 수 있다. 결과 한계에 명시. 프로젝트의 GC-2(device runtime overhead 미고려)와 같은 방향 | DP문서 | 설계 §2, constraints §6, C-E1 |
| DP1-C-6 | "이동 중에 읽거나 쓰면?" (부분 복사, 해제된 slot, 이동 중 쓰기, 이동 중 prefix hit) | **이동 대상은 sealed(불변) data이고 ref_cnt = 0인 object**다. 실행 중 요청이 참조하는 block(ref_cnt > 0)의 물리 위치는 그 step 중에 바꾸지 않는다. 이동 중에는 항상 source가 authoritative이며 commit 전 target은 어떤 reader에게도 보이지 않는다. 이를 **지키도록 보장하는 것은 공통 subsystem(G1)이고 DP1은 이를 깨는 이동 대상을 고르지 않는다** | 전제/경계 | 이동 가능 object 집합이 평가가 가정한 것보다 **좁을 수 있다**(평가는 참조 중 object도 이동한다고 가정, constraints §11-1) | DP문서 | C-I1~I4, C-H1~H9, §11 |
| DP1-C-7 | "TP/PP/DP 다중 rank나 CUDA graph에서도 되나?" | 모든 rank가 같은 step 경계에서 같은 commit을 적용하고(모든 rank copy 완료 후 commit), CUDA graph replay 중에는 block table 주소를 바꾸지 않는다. **vLLM의 rank별 block 소유 방식은 확인하지 못했다**. 따라서 multi-rank, CUDA graph 호환은 아직 요구사항으로 확정할 수 없다 | 전제(미확인)/한계 | 평가는 GPU 8장을 집계 모델로 다룸. 구현 시 확인 필요 | DP문서 | C-X1, C-X2 `[가정]` |
| DP1-C-8 | "초기 phase에서 어떤 data를 이동하나? LoRA/MoE/RAG는?" | **Phase 1은 sealed KV만 이동 대상**이다. LoRA, MoE, RAG 인덱스, Agent memory는 immutability를 별도로 정의한 뒤의 후속 phase다. 휘발 tier에는 재계산 가능하거나 replica가 있는 data만 유일 사본으로 둔다 | 범위/단계 | UC-3~5와 FR-10~17의 DP1 충족은 Phase 2 이후. 시뮬레이터 평가는 이 class들을 포함하므로 **설계 문서와 평가 범위가 불일치**(§8 D-4) | DP문서 | C-D1, C-D2, 아키텍처 §24 |
| DP1-C-9 | "신규 memory를 쓸 때 driver, 주소 변환, 전송 엔진은?" | HW 수준 주소 변환(page table, IOMMU, CXL HDM decoder), TLB 무효화, DMA/copy engine, coherency 프로토콜, vendor driver와 TransferHandler **구현**은 DP1 범위 밖이며 device driver/runtime 소관이다(G2, G3, O2). 가상 주소를 유지한 채 backing만 바꾸는 REMAP은 기본 경로가 아니며 descriptor가 지원을 선언한 장치에서만 쓴다 | 범위 밖/전제 | 프로젝트의 GC-2, GC-3, GC-5와 일치. REMAP 미지원 시 MOVE로 재계획 | DP문서 | G2, G3, O2, C-X6, C-X7 |
| DP1-C-10 | "차세대 메모리 성능 수치는 실측인가?" | HBF, ScHBM, CXL-PNM, SSD-PIM의 성능은 **config parameter 기반 시뮬레이션 [B+C]** 이며 실측 [A]가 아니다. 이득 수치는 simulator 모델의 가정(비용 추정 오차 0, queueing/saturation 없음, 링크 간섭 모델 한 종류)에 의존하고, HBF write amplification, endurance, PCIe/CXL protocol overhead, 전력은 모델링하지 않는다 | 증거 한계 | 구현 후 [A] 실측과 cost 추정 보정 필요. QA 별점 해석은 조건부 | 사용자(GC-1), DP문서 | C-E2~E4, 설계 §26-14, GC-1 |
| DP1-C-11 | "tenant 간 격리는? 이동된 slot 내용이 노출되지 않나?" | tenant 격리와 보안은 **과제 범위 밖**이다(GC-6). 기존 cache salt 정책이 유지된다는 전제만 둔다. 공유 pool(CXL) 해제 시 sanitize 정책은 요구사항이 아니다 | 범위 밖/전제 | DP1 문서의 C-H10은 `[가정]` 상태로 남음. 프로젝트 범위로 제외 | 사용자(GC-6), DP문서 | C-H10 |
| DP1-C-12 | "write 수명 제한 매체에는 얼마나 쓰나?" | HBF/SSD-PIM의 endurance 예산은 설계 제약이지만 **시뮬레이터에서 검증되지 않는다**. 따라서 DP1-FR-14는 검증 불가 요구사항으로 표시한다 | 증거 한계 | DP1-QA10을 정량 시나리오로 만들 수 없음 | DP문서 | C-R5, C-E3 |
| DP1-C-13 | "평가는 어떤 환경까지 일반화되나?" | 평가 시스템은 **SYS-H100, SYS-B200**(GPU 8장 1노드, Llama-3.1-70B BF16)이다. SYS-A100, SYS-VR은 소유자 결정으로 제외했다. 결과는 이 두 시스템의 쌍(시나리오 x 시스템) 단위 geometric mean이다. 비교 가능 쌍은 64쌍 중 21쌍이고 포화 10쌍, Baseline이 SLO 불가 33쌍은 집계에서 제외(목록에는 유지) | 환경/증거 한계 | 초장문·대용량 인덱스 시나리오는 Baseline이 infeasible이라 이득이 집계에 반영되지 않음 | DP문서 | 평가 결과 §0.5, SKILL H19 |
| DP1-C-14 | "Baseline이 실제 vLLM과 같은가? Dynamic benchmark는 공정한가?" | Baseline-static은 **As-Is proxy**(공통 initial placement 후 migration 없음)이며 vLLM의 실제 `kv_offload`/CPU offload 동작과 동일하다고 확인한 것이 아니다. Dynamic benchmark는 Baseline의 실패 양상을 알고 설계했으므로 **이득은 static 배치가 stale해지는 경우에 한정해 읽는다** | 증거 한계 | 이득 주장 범위를 dynamic 조건으로 제한 | DP문서 | benchmark.md §2, 설계 §26-14 |
| DP1-C-15 | "별점 경계는 객관적인가? 우열이 뒤집히지 않나?" | DP1 별점 경계(QA1 1.30 등)는 **결과를 본 뒤 정했다**(`defined_after_first_look`). C1 x1.298은 경계 1.30 바로 아래, C2 x1.422는 위이고 선택(C1 10 대 9)은 이 경계와 QA3 정의 이력에 민감하다. 따라서 QA 목표값을 확정할 때 경계 선택을 함께 명시해야 한다 | 증거 한계/전제 | 목표값(QS-1, 3~5)의 확정 필요(Q-D5) | DP문서 | qa-criteria-dp1 §A, §J |

프로젝트 공통 제약 중 DP1에 직접 걸리는 것: **GC-1**(차세대 메모리는 시뮬레이션), **GC-2**(device runtime overhead 미고려), **GC-3**(device runtime의 reliability, availability 보장 가정), **GC-5**(kernel/compiler runtime 범위 밖), **GC-6**(tenant 격리, 장애 복구 범위 밖), **GC-7**(출력 불변, DP3 제외), **GC-10**(stale KV 무효화 범위 밖). GC-9(노드 간 PCIe 64GB/s)는 DP1이 단일 노드라 직접 걸리지 않는다. 단일 노드 안의 host link(PCIe 5.0 x16, 약 63 GB/s)는 평가 시스템 값이다.

## 6. 추적성

### 6.1 UC → DP1 FR → QS

| UC | DP1 FR | 품질 시나리오 |
|---|---|---|
| UC-1 idle KV 점유 해소, 재방문 | FR-02, 03, 08, 10, C1-01/03, C2-02 | QS-1, 3, 5, 9 |
| UC-2 long-context (HBM 초과) | FR-02, 10, C1-01 | QS-4, 5 (정확도 손실 Drop은 DP3) |
| UC-3 RAG hot/cold | FR-03, C1-02, C2-02 (Phase 2) | QS-1, 3, 5 |
| UC-4 LoRA, UC-5 MoE | FR-03, C1-02, C2-01 (Phase 2) | QS-1, 7 |
| UC-6 연산 가능 메모리 | FR-06, 07, C1-04 | QS-6 |
| UC-9 혼합 부하 | FR-01, 08, 13, 15 | QS-2, 3, 4, 8, 9, 11 |

### 6.2 QA → QS → 제약

| QA | QS | 주로 걸리는 제약 |
|---|---|---|
| DP1-QA1 Throughput | QS-1, 2 | DP1-C-5, 10, 13, 14, 15 |
| DP1-QA2 Latency | QS-3, 4 | DP1-C-5, 10, 15 |
| DP1-QA3 Resource Utilization | QS-5 | DP1-C-6, 10, 15 |
| DP1-QA4 Modifiability | QS-6, 7 | DP1-C-8, 9 |
| DP1-QA5 Decision Latency (추가) | QS-8 | DP1-C-5, 10 |
| DP1-QA6 Stability (추가) | QS-9 | DP1-C-10, 14 |
| DP1-QA7 Correctness (추가) | QS-10 | DP1-C-6, 7 |
| DP1-QA8 Availability-degradation (추가) | QS-11 | DP1-C-5, 9, 10 |
| DP1-QA9 Observability (추가) | QS-12 | DP1-C-5 |

## 7. 문서 간 불일치와 확인이 필요한 점 (사용자 확정 필요)

### 7.1 불일치 (어느 쪽이 맞는지 확인 필요)

| ID | 내용 | 영향 |
|---|---|---|
| D-1 | **DP 번호 체계가 문서마다 다르다.** `DP-memory-backend-if.pptx` 1장: DP2 = Prefill/Decode 실행, DP3 = Long Context KV Eviction & Reuse, **DP4 = Agent Tool-wait KV residency**. 그런데 `doc-mk/DP4/dp4-inter-node-kv-sharing-structure-draft.md`는 DP4 = 노드 간 KV 공유. DP1 PPT 10장은 "Agent aware KV 관리는 (DP3)"로 쓰고, DP1 설계 문서 §3.2는 "별도 DP"로 쓴다 | `usecases.md`의 UC-1 FR-4(prefetch)와 UC-7의 DP 연결을 어느 DP에 매핑할지 정해야 한다. 현재 UC 추적 표의 DP4는 노드 간 공유를 가정 |
| D-2 | **UC-1(tool 대기 중 idle KV)의 담당.** DP1 설계는 tool lifecycle 관리를 범위 밖으로 하지만, DP1 평가의 Dynamic benchmark에는 `dyn_idle_kv_holds_hbm`("tool 대기 중 idle KV가 HBM 점유")이 포함되어 있다 | DP1은 UC-1의 "HBM 해소" 부분만 담당하고 "재개 전 복원" 부분은 다른 DP라고 정리했다(§2.4). 맞는지 확인 필요 |
| D-3 | **QA3 정의.** 공통 문서(§6)는 "useful resource utilization(65/85%)", DP1 공식(v6)은 "HBM 사용량(GiB)"이다. 정의 이력에서 한때 QA3를 별점에서 빼고 진단으로 돌렸다가 v6에서 HBM 사용량으로 복귀했다. `qa_priority.json`은 4개를 모두 유지 | 품질 시나리오 QS-5는 DP1 v6 정의를 썼다. 과제 요구사항의 QA3 metric으로 이를 확정할지 확인 필요 |
| D-4 | **Phase 범위.** 설계(C-D1)는 Phase 1을 sealed KV로 한정하는데 평가는 LoRA, MoE, RAG, Agent memory 시나리오를 포함한다 | UC-3~5의 DP1 충족 범위. 요구사항을 "Phase 1 KV 한정"과 "후속 phase"로 나눠 표시했다 |

### 7.2 확정이 필요한 `[가정]` 값

| ID | 값 | 현재 가정 | 근거 | 영향 |
|---|---|---|---|---|
| Q-D1 | TTFT/TPOT P99가 Baseline의 1.10배를 넘는 쌍 = 0 | 1.10배 | Baseline 잡음 sd(0.017~0.020)의 약 5배 | QS-3, QS-4. 현재 C1은 TTFT P99 x1.04, TPOT P99 x1.07로 평균은 범위 안이나 쌍별 최악은 미확인 |
| Q-D2 | event-to-decision P99 ≤ 100 ms, decision on/off TPOT P50 차이 ≤ 2%, 10배 규모 시 ≤ 10배 | 위 값 | 17.8 GiB KV 이동 시간 약 0.3 s의 1/3 | QS-8 (현재 미측정) |
| Q-D3 | 왕복 재이동 비율 ≤ 5% | 5% | 근거 없음(임의) | QS-9 |
| Q-D4 | degradation 후 SLO 95% 회복 시간 ≤ 60 s | 60 s | 평가의 hotset 주기 | QS-11 |
| Q-D5 | QA 목표값: QA1 ≥ 1.30, QA2 ≥ 1.25, QA3 절감 ≥ 1.25 (DP1 ★★★ 경계)를 **요구사항의 목표값으로 확정**할지, 공통 기준(QA1 ≥ 1.10)을 쓸지 | DP1 기준 | DP1 평가 문서 | QS-1~5. 현재 설계는 QA1(C1이 경계 직전, 1.298), QA3(두 후보 모두 절감 1.25 미달)이 목표에 못 미침 |
| Q-D6 | 추가 후보 QA의 채택 | QA5~QA9 권장, QA10~12 보류, QA13 제외 | §3.2 | QS-8~12의 확정 여부 |
| Q-D7 | 로그 필수 필드 완비율 100%, 무결성 테스트 규모 ≥ 1,000 이벤트 | 위 값 | 근거 없음 | QS-10, 12 |

## 8. 체크리스트 (스킬 §7)

- [x] 항목에 출처와 상태가 있다 (FR, 제약). QA 표에는 출처 열을 두었다.
- [x] 선정 QA(§3.1)와 추가 후보(§3.2)를 분리했고 추가 후보에 관련 이유와 미선정 위험이 있다.
- [x] 품질 시나리오 12개가 6요소를 모두 채웠다.
- [x] 응답 측정에 metric, 통계량, 임계값, 비교 기준, 측정 조건, 근거 라벨이 있다. 확인하지 못한 값은 "미확인/미측정"으로 표기했다.
- [x] 평가 문서의 metric 정의를 재사용했다 (Max SLO Goodput, TTFT/TPOT, HBM 사용량, module/MM/$). 신규 metric: `migration 재이동 비율`, `degradation 회복 시간`, `로그 완비율`은 신규(QS-9, 11, 12), 정의는 각 QS에 있다.
- [x] 제약마다 예상 질문과 유형이 있다.
- [x] 추적성 표가 있다 (UC ↔ FR ↔ QS, QA ↔ QS ↔ 제약).
- [x] `[가정]` 값을 §7.2에 올렸다.
- [x] 읽지 못한 입력을 §0에 명시했다.
