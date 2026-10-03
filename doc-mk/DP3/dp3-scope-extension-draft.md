# DP3 범위 확장안 (초안) — KV 축소·재사용 구조

| 항목 | 내용 |
|---|---|
| 상태 | **초안 (제안)** — 원본 `dp3-long-context-kv-cache-eviction.md`는 수정하지 않았다 |
| 작성 일자 | 2026-10-02 (최종 수정 2026-10-03: 사용자 확인 반영 — eviction은 Drop이며 복원(재계산) 절차는 미설계) |
| 기준 문서 | [`dp3-long-context-kv-cache-eviction.md`](dp3-long-context-kv-cache-eviction.md) (§ 번호는 이 문서 기준), [`../DP1/dp1-ai-data-migration-decision-architecture.md`](../DP1/dp1-ai-data-migration-decision-architecture.md), [`../Evaluation/qa-evaluation-criteria.md`](../Evaluation/qa-evaluation-criteria.md) |
| 근거 수준 | **[A]** 실측 / **[B]** 문헌 보고 수치 (as reported) / **[C]** 구조 논증·가설 |
| 원칙 | 원본의 용어 고정(**Eviction = Drop**), "DP1 먼저·DP3는 실패 경로" 규칙(§2.4), B1 기준선(§9.2), 가정값 미기재 원칙(§9)을 **그대로 유지**한다 |

---

# 0. 한눈에 보기

**무엇을 확장하는가 — 세 가지**

| # | 확장 | 원본의 어디가 바뀌는가 |
|---|---|---|
| ① | 회수 동작 분류를 넓힌다. **하신 일은 Drop(eviction)과 Blend(selective recompute) 두 가지**이고(둘을 연결할지는 §4.6), Compress·Select는 문헌 기반 확장 후보다 | §2.1 |
| ② | **설계 쟁점 2**를 추가한다 — "축소 동작을 어떤 소프트웨어 구조에 둘 것인가"(S1 엔진 내장 / S2 경계 플러그인) | §3 이후에 신설 |
| ③ | **공통 컴포넌트와 블록 상태 모델**(위치 × 충실도 직교)을 정의한다 | 신설 (§3.2~3.3) |

**유지하는 것**: 쟁점 1(중요도 평가 시점: C1 Offline / C2 Online), 용어 고정, DP1 우선 규칙, B1 기준선, §9의 지표 체계.

**사용자 확인 (2026-10-03)**: 하신 eviction은 **폐기(Drop)** 이다. blending(selective recompute)도 하신 일이지만, **폐기된 KV가 다시 필요해질 때의 복원(재계산) 절차는 아직 설계하지 않았다.** Drop과 Blend를 한 쌍으로 묶는 것은 **제안**(§2, §4.6)이며 확정이 아니다. Compress·Select는 새 동작을 추가할 때의 확장성(Modifiability)을 시험하는 후보로 둔다.

**왜 필요한가**: 원본의 후보 C1/C2는 "중요도를 언제 평가하는가"라는 **알고리즘 축**이다. 이 축만으로는 모듈 책임, 상태, 인터페이스가 정의되지 않아 소프트웨어 구조 설계의 대상이 되지 못한다. 또 재사용 시 일부 토큰만 다시 계산하는 selective recompute(blending)는 §2.1의 Demote/Drop 두 분류에 들어갈 자리가 없다.

---

# 1. 현재 문서로는 구조 설계가 안 되는 이유

| # | 관찰 (원본 확인 결과) | 영향 |
|---|---|---|
| 1 | §4~§5의 후보 C1/C2는 모두 **중요도 평가 시점**이 다른 알고리즘이다. 문서 전체에 모듈 뷰·컴포넌트 뷰·상태 모델이 없다 | 어떤 모듈이 무엇을 책임지고 어떤 인터페이스로 엔진과 DP1에 붙는지 설계할 수 없다 |
| 2 | §2.1은 회수 동작을 **Demote(무손실, 위치만 변경)와 Drop(손실, 폐기)** 둘로만 나눈다 | 재사용 시 일부 토큰만 다시 계산하는 blending(selective recompute)이 분류 밖에 있다. 정밀도 압축, 보존하되 attention에서 제외하는 선택은 문헌 기반 확장 후보다 |
| 3 | "Accuracy 교환은 **Drop에서만** 성립한다"(§2.1)는 서술 | 압축·선택도 손실을 낳으므로 성립 조건을 "손실을 허용하는 동작이 포함될 때"로 일반화해야 한다 |
| 4 | §1 ③의 도식과 문장은 중요도 낮은 KV를 "Low Tier로 Eviction"하는 것으로 그려져 있다 | 사용자 확인(§4.5)으로 하신 eviction은 **Drop(폐기)** 이다. 그런데 "Low Tier로"는 §2.1의 정의로는 Demote로 읽히므로 "폐기"로 고쳐야 한다. §4 서두는 이미 "Drop을 가리킨다"고 정리하지만 §1 ③은 그 앞에 있다 |

---

# 2. 확장 ① — 회수·축소 동작 분류 (§2.1 개정안)

원본의 표를 다음과 같이 확장한다. **결정 주체**는 DP1이 위치, DP3가 충실도(fidelity)를 맡는 구분을 따른다(§3.3).

| 동작 | 정의 | 회수되는 것 | Accuracy | 가역성 | 대가 | 결정 주체 | 문헌 예 [B] | 하신 일 |
|---|---|---|---|---|---|---|---|---|
| **Demote** | 하위 tier로 이동, 내용 보존 | HBM 용량만 | 무손실 | 가역 | 재접근 시 대역폭·지연 | **DP1** | (DP1) | DP1 영역 |
| **Compress** | 정밀도·표현을 줄여 크기를 축소 | 크기 감소분 (위치에 따라 HBM 또는 전체) | **부분 손실** | 원본 미보존 시 비가역 | 코덱 연산, 품질 저하 | **DP3** | HBM 내부 양자화(KIVI, KVQuant), 경계 압축(CacheGen, KVTC) | **하신 일에 없음** (문헌 기반 확장 후보) |
| **Select (Skip)** | KV는 보존하되 해당 질의의 attention 대상에서 제외 | 접근·연산 비용 (보존 위치에 따라 용량도) | **손실 (근사 attention)** | 가역 (보존 시) | 선택 판단 비용 | **DP3** | Quest, InfiniGen, ShadowKV | **하신 일에 없음** (확장 후보) |
| **Drop** | 어느 계층에도 남기지 않고 폐기 | 전체 용량 | 손실 | 비가역, 재계산만 가능 | 재계산 (M-R1) | **DP3** | H2O, StreamingLLM, SnapKV | **하신 eviction (오프라인·온라인)** — 폐기로 확인 (§4.5) |
| **Blend / Selective Recompute** (재사용 시점) | 다시 계산할 토큰을 고르고 재연산까지 수행해 폐기된 KV를 복원 | 용량 회수가 아니라 **Drop의 재접근 비용 절감·복원** | 보정 정도에 따라 | — | 선택 재계산 연산 | **DP3** (연산 배치는 DP2) | CacheBlend | **하신 blending** (두 이름은 같은 동작) — Drop 이후 복원 경로로 쓸지는 미정 (§4.6) |

> **문헌 예의 근거 수준.** 위 [B] 항목은 조사 에이전트가 초록을 열람해 분류한 것이다(부록 A). 이 문서에서 직접 열람해 재확인한 것은 CacheBlend(arXiv 2405.16444)뿐이다. 나머지는 인용 전 원문 재확인이 필요하다.

**Drop과 Blend를 한 쌍으로 묶을 수 있다 (제안, 미확정).** 하신 eviction은 폐기이며, 폐기된 토큰이 다시 필요해질 때의 복원 절차는 아직 설계되지 않았다. 복원을 둔다면 **전부를 Prefill로 다시 계산하는 대신** 다시 계산할 토큰을 골라 일부만 재연산하는 구성이 가능하다.

```text
FULL ──Drop(중요도 낮은 토큰 폐기)──► DROPPED ──재접근──► Blend(재연산할 토큰 선택 + 재연산) ──► 복원
```

원본 §9.5의 M-R1은 Drop 후 재접근 시 Prefill 재연산을 가정한다. Blend는 이 재계산 비용을 줄이는 경로이므로 M-R1의 정의가 바뀐다(§6). 반면 Blend로 복원한 KV는 재연산에서 빠진 토큰만큼 FULL과 다를 수 있어, **Drop의 손실에 Blend의 근사가 더해지는 구조**일 수 있다 [C]. 두 선택(무엇을 버릴지 / 무엇을 다시 계산할지)이 같은 중요도 점수를 쓰는지는 §4.6의 질문이다.

**§2.1 서술의 일반화 (제안)**

> 원본: "Attention Importance가 Accuracy와 교환되는 것은 **Drop에서만** 성립한다."
> 제안: Importance가 Accuracy와 교환되는 것은 **손실을 허용하는 동작(Compress, Select, Drop)이 회수 동작에 포함될 때에만** 성립한다. Demote만 수행하는 구조에서는 Accuracy 행이 성립하지 않는다(원본의 결론 유지).

**§2.2(Drop이 필요해지는 조건)에 대한 영향 [C]**: (a)(b)(c)는 Drop이 값을 하는 조건이다. Compress와 Select는 하위 계층까지 포화되지 않아도 HBM 점유와 접근 비용을 줄이므로 값을 할 수 있다. 다만 이 주장은 가설이며 §9의 M-C4·M-C5 분해로 검증해야 한다. 복원 절차를 둔다면 Blend는 (c) 이후의 재접근 비용을 낮춰 Drop이 값을 하는 범위를 넓힐 수 있다 [C].

---

# 3. 확장 ② — 설계 쟁점 2: 축소 동작의 소프트웨어 구조

## 3.1 설계 질문

> **Drop(eviction)과 Blend(selective recompute)를 비롯한 KV 축소·복원 동작을, 엔진 내부의 어느 구조에 둘 것인가? 새 동작(예: Compress, Select)이나 새 메모리가 추가될 때 기존 구조를 얼마나 바꿔야 하는가?**

DP1의 쟁점 2(공통 Memory Backend I/F, plug-in)와 같은 형태의 쟁점이며, QA는 **Modifiability**와 **Functional Correctness**가 걸린다.

## 3.2 공통 컴포넌트

```mermaid
flowchart LR
    ENG["vLLM Worker\nattention / KV manager"]
    PM["Memory Pressure Monitor"]
    POL["Reduction Policy\n(쟁점 1: C1 Offline / C2 Online\n중요도 평가가 여기에 위치)"]
    AB["Accuracy Budget\n(허용 정확도 한도)"]
    REG["Operator Registry\n(plug-in 등록)"]
    subgraph OPS["Reduction Operators"]
        OC["Compress (확장 후보)"]
        OS["Select (확장 후보)"]
        OD["Drop"]
        OB["Blend / Selective Recompute"]
    end
    META["Block Metadata\nlocation x fidelity"]
    QG["Quality Guard\n정확도 검증 · 복구"]
    DP1["DP1 Placement /\nMigration Scheduler"]
    DP2["DP2 연산 배치"]

    ENG -- "1 메모리 압박 신호" --> PM
    PM -- "2 압박 수준" --> POL
    AB -- "3 한도" --> POL
    POL -- "4 연산자 선택 요청" --> REG
    REG --> OPS
    OPS -- "5 충실도 변경" --> META
    POL -- "6 위치 변경이 먼저 가능한가?" --> DP1
    DP1 -- "7 배치 실패(용량 제약)" --> POL
    OPS -- "8 결과 검증" --> QG
    QG -- "9 위반 시 full 복원 · 재계산" --> META
    META -- "10 블록 상태 조회" --> POL
    OB -- "11 재연산 실행 요청" --> DP2
```

| 컴포넌트 | 책임 | 원본·DP1과의 관계 |
|---|---|---|
| **Memory Pressure Monitor** | 상위 메모리 점유와 압박 추세를 관측해 신호를 낸다 | DP1 Resource Manager의 Telemetry와 같은 신호를 공유할 수 있다 |
| **Reduction Policy** | 압박 수준과 정확도 한도에서 **어떤 동작을 어떤 블록에** 적용할지 결정한다. **쟁점 1(오프라인/온라인 중요도 평가)이 이 컴포넌트 안에 위치한다** | §4~§5의 C1/C2가 들어가는 자리 |
| **Accuracy Budget** | 허용하는 정확도 저하 한도(전역·요청별·task별)를 정의한다 | 신규. 정확도가 QA인 DP이므로 필요 |
| **Operator Registry** | 축소 동작을 plug-in으로 등록·조회한다 | 신규. DP1 §5.8의 Backend I/F와 같은 계열의 확장 지점 |
| **Reduction Operators** | Drop, Blend/Selective Recompute(하신 일)와 확장 후보 Compress, Select를 각각 구현한다 | 하신 eviction(Drop)과 selective recompute(blending)가 여기에 위치(§4) |
| **Block Metadata** | 블록의 **위치**(DP1 소유)와 **충실도**(DP3 소유)를 직교 속성으로 관리한다 | §3.3 |
| **Quality Guard** | 적용 후 정확도 저하를 검증하고, 한도를 넘으면 full 복원 또는 재계산으로 되돌린다 | 신규. M-A1, M-A2와 연결 |
| **DP1 Placement** | 위치 결정. DP1이 먼저 시도하고 실패할 때만 DP3가 개입한다 | §2.4 고정 규칙 그대로 |

## 3.3 블록 메타데이터: 위치와 충실도를 직교 속성으로 분리

DP1과 DP3의 경계를 문서 규칙에서 **데이터 모델 규칙**으로 내리는 제안이다.

| 속성 | 소유 | 값 (예) | 변경 주체 |
|---|---|---|---|
| **location** | DP1 | HBM, DRAM, CXL, SSD, … | DP1 Migration Scheduler만 |
| **fidelity** | DP3 | FULL, DROPPED(재계산 가능), RECOMPUTED-PARTIAL(선택 재연산으로 복원), (확장: COMPRESSED(level), SELECTED-OUT) | DP3 Reduction Operators만 |

규칙:
1. DP1은 fidelity를 읽을 수 있으나 변경하지 않는다. DP3는 location을 읽을 수 있으나 변경하지 않는다.
2. 같은 블록에 두 결정이 동시에 걸리면 §2.4의 순서(DP1 먼저)를 따른다.
3. DROPPED 블록은 location이 없다(어느 계층에도 남지 않음). 재접근 시 전체 재계산(FULL) 또는 선택 재연산(RECOMPUTED-PARTIAL)으로 복귀한다.

충실도 전이 (제안):

| 현재 | → | 조건 | 동작 |
|---|---|---|---|
| FULL | DROPPED | DP1 배치 실패(용량 제약) + 정확도 한도 여유 | Drop (오프라인/온라인 중요도로 대상 선정) |
| DROPPED | RECOMPUTED-PARTIAL | 재접근 (복원 절차를 두는 경우) | Blend: 재연산할 토큰 선택 + 재연산 |
| DROPPED | FULL | 재접근 + 선택 재연산이 부적합하거나 정확도 한도 위반 | 전체 재계산 (M-R1) |
| RECOMPUTED-PARTIAL | FULL | Quality Guard 위반 | 전체 재계산 |
| (확장) FULL | COMPRESSED / SELECTED-OUT | 압박 + 정확도 한도 여유 / 질의별 중요도 낮음 | Compress / Select |
| (확장) COMPRESSED / SELECTED-OUT | FULL | Quality Guard 위반 또는 재접근 | 복원 (원본 보존 시) |

공유 Block(Prefix Cache 후보)은 §2.4대로 **모든 DP3 동작의 대상에서 제외**한다. (확장 동작인) Compress도 공유 Block에 적용하면 다른 세션의 정확도에 영향을 주므로 같은 규칙을 적용하는 것이 안전하다 [C].

## 3.4 연산자 인터페이스 스케치

구현이 아니라 **인터페이스가 가져야 할 것**을 보이는 스케치다.

```text
ReductionOperator
 ├─ name / kind            : drop | blend  (확장: compress | select)
 ├─ applicable(block, ctx) : 이 블록에 적용 가능한가 (공유 Block 제외 등)
 ├─ estimate(block, ctx)   : (회수 bytes, 예상 정확도 영향, 비용)  ← Policy가 비교에 사용
 ├─ apply(block, budget)   : 충실도 변경 수행. Accuracy Budget 안에서만
 ├─ restore(block)         : 복원 가능 여부와 비용 (불가능하면 not_restorable)
 └─ requires_engine_hook   : attention 경로 접근이 필요한가 (S1/S2 판단 근거)
```

`estimate`와 `restore`를 인터페이스에 넣는 이유는 Policy가 동작을 **비용·정확도 영향·가역성**으로 비교해 고르게 하기 위해서다. 이 정보 없이는 Policy가 특정 동작에 하드코딩된다.

## 3.5 구조 후보 — S1 / S2

쟁점 1의 C1/C2와 이름이 겹치지 않도록 구조 후보는 **S1, S2**로 부른다.

| | **S1. 엔진 내장(인라인)** | **S2. 경계 플러그인 파이프라인** |
|---|---|---|
| 구조 | 연산자가 vLLM worker의 attention·KV manager 경로 **안에** 구현된다 | 연산자가 tier 경계(강등·승격·load)의 **별도 단계**이며 Operator Registry로 교체한다 |
| 정확도 제어 단위 | 레이어·헤드·토큰 (attention 정보 직접 접근) | 블록 (경계에서 관측 가능한 정보) |
| 지연·처리량 [C] | 추가 복사 없음 | 코덱 단계가 이동 경로에 추가. 비동기로 숨길 수 있는지는 **측정 대상** |
| 적용 범위 | HBM 압박 중심 | 하위 tier·서버 간 전송(DP4)까지 연결 |
| 엔진 수정 | 큼 (attention backend, KV manager) | 작음. 단 **온라인 Drop(Stage 1)과 Blend는 엔진 훅이 필요**(아래) |
| Modifiability [C] | ★★ 추정 (연산자 추가 시 attention backend, KV manager, scheduler 등 3개 이상 모듈 변경 가능성) | ★★★ 추정 (연산자 구현 + 등록, ≤ 2 모듈) |

> **S2가 "엔진 무수정"은 아니다 [C].** 온라인 Drop은 실제 질의의 attention(Stage 1)으로 점수를 내므로 attention 경로에 접근해야 하고, Blend/Selective Recompute는 일부 토큰을 forward 경로에서 다시 계산하므로 같은 경로에 들어가야 한다. 따라서 S2에서도 연산자의 `requires_engine_hook`이 참인 동작은 **엔진 훅 1~2개**가 필요하다. 오프라인 Drop(사전 프로파일 기반)만 경계 단계로 처리하기 쉽다. 이를 숨기면 S2의 Modifiability가 과대평가된다.

표의 Modifiability 점수는 [`qa-evaluation-criteria.md`](../Evaluation/qa-evaluation-criteria.md) §7의 기준(★ ≥ 6 모듈, ★★ 3~5, ★★★ ≤ 2)을 적용한 **구조 논증(C)** 이며 prototype으로 확인하기 전까지 가설이다. 변경 시나리오는 "Compress 또는 Select 같은 새 동작을 추가한다"로 둔다(확장 후보가 이 평가의 시험 대상이다). 문헌에서도 같은 갈림이 보인다: eviction·HBM 내부 양자화 계열은 엔진 안, 전송·저장 경계 압축은 경계 단계에 있다(부록 A, [B]).

## 3.6 쟁점 1 × 쟁점 2 조합

| | S1 엔진 내장 | S2 경계 플러그인 |
|---|---|---|
| **C1 Offline** (사전 중요도 프로파일) | 자연스러움. 프로파일을 엔진 내부에서 조회 | 자연스러움. 프로파일이 경계에서 조회되는 정적 입력 |
| **C2 Online** (실제 질의 attention) | 자연스러움. attention 점수가 엔진 내부에 있음 | **attention 점수를 경계로 내보내는 경로가 필요** — 새 설계 위험 [C] |

(C2, S2)는 질의별 attention 점수를 엔진 밖으로 내보내야 하므로 추가 비용과 인터페이스 변경이 생긴다. 이 조합이 성립하는지가 S2 평가의 핵심 위험이다.

---

# 4. 지금까지 한 작업의 위치 (사용자 설명 반영)

> 이 절은 사용자가 설명한 실제 구현 내용으로 다시 썼다. 이전 판은 "KV 압축"을 정밀도 압축으로 잘못 가정했다.

## 4.1 하신 작업

| 작업 | 내용 |
|---|---|
| **KV "압축" = 토큰 eviction** | 중요도가 낮은 토큰을 내보내고 높은 토큰만 남긴다. 중요도는 attention score로 정한다 |
| ├ 오프라인 | 해당 context에 들어올 사용자 질의를 예측한 **대표 질의**들로 미리 attention을 수행해 score를 얻고, 높은 것만 남기고 낮은 것은 내린다. (원본 §4의 **C1**) |
| └ 온라인 | **실제 사용자 질의**로 먼저 attention 연산(**Stage 1**)을 수행해 score를 얻고, 같은 방식으로 높은 것만 남기고 낮은 것은 내린다. (원본 §5의 **C2**) |
| **Blending = Selective Recompute** (같은 동작) | 다시 계산할 토큰을 고르고, 그 토큰을 실제로 재연산하는 과정까지 모두 포함한다 |

즉 오프라인과 온라인은 **중요도를 언제 평가하느냐만 다르고** 하는 일(점수가 낮은 토큰을 내린다)은 같다. 정밀도를 줄이는 압축(Compress)은 하신 일에 없다. §2 표에서는 문헌 기반 확장 후보로만 남겼다.

## 4.2 이 문서의 구조에서의 위치

표의 칸 이름은 다음 뜻이다. **동작 종류**는 §2 표의 행 하나, **구조도의 박스**는 §3.2 그림의 네모(소프트웨어 모듈) 하나다.

| 하신 작업 | 동작 종류 (§2) | 구조도의 박스 (§3.2) |
|---|---|---|
| 오프라인 eviction (C1) | **Drop** (§4.5 확인) | **Reduction Policy**(중요도를 사전에 평가) + Drop Operator |
| 온라인 eviction (C2) | **Drop** | **Reduction Policy**(중요도를 Stage 1 attention으로 평가) + Drop Operator |
| Blending (Selective Recompute) | Blend | **Operator**. 어떤 토큰을 다시 계산할지 고르는 부분은 Policy 쪽 판단이고, 실제 재연산 실행은 DP2(연산 배치)와 접점이다 |

## 4.3 이미 있는 것과 새로 설계할 것

| | 내용 |
|---|---|
| **이미 있는 것** | 중요도 산출(대표 질의 프로파일 / Stage 1), 토큰 eviction 로직, 선택 재연산 로직. 근거 수준은 확인 필요(실측이면 [A]) |
| **새로 설계할 것** | 위 로직들을 **하나의 구조로 묶는 부분**: 압박 시 어떤 방식을 쓸지 정하는 Policy와 정확도 한도, 어떤 토큰이 내려갔고 재연산됐는지 기록하는 블록 상태, 오프라인·온라인 eviction과 selective recompute를 같은 틀로 호출하는 Operator 인터페이스, 정확도 검증·복구(Quality Guard), 엔진과의 경계(S1/S2) |

## 4.4 용어: Stage 1

"Stage 1"은 온라인 방식에서 실제 질의로 attention 점수를 산출하는 단계를 가리키는 용어로 받았다. 원본 DP3 문서에는 이 용어가 없다. 원본 §5(C2)에 같은 이름으로 명시하는 것을 권한다.

## 4.5 확인 완료 — 내려간 토큰은 폐기된다 (사용자 확인). 복원 절차는 미설계

| 내려간 토큰의 이후 | §2의 동작 종류 | Accuracy 교환 | 판정 |
|---|---|---|---|
| (a) 하위 tier에 보존, 이후 attention에도 참여 | Demote | 없음 | 해당 없음 |
| (b) 하위 tier에 보존, 이후 attention에서 제외 | Select (Skip) | 있음, 가역 | 해당 없음 |
| **(c) 폐기** (필요할 때 재계산하는 절차는 아직 설계하지 않음) | **Drop** (복원 경로는 §4.6) | 있음, 비가역 | **하신 일** |

결과:
1. 하신 eviction은 **Drop**이며, 원본 DP3 문서의 정확도(QA) 논리가 그대로 성립한다. DP1 영역(Demote)과 겹치지 않는다.
2. Blend(하신 일)를 Drop 이후의 복원 경로로 연결할지는 **미정**이다(§4.6). 재계산 절차는 아직 설계되지 않았다.
3. 원본 §1 ③의 "Low Tier로 Eviction" 표현은 Demote로 읽히므로 "폐기"로 고쳐야 한다(§1 관찰 4, §7).

## 4.6 Drop–Blend 쌍이 만드는 설계 질문 [C]

하신 작업을 구조로 묶을 때 정해야 하는 질문이다. 현재 구현이 어떻게 되어 있는지는 확인하지 않았다.

| # | 질문 | 구조에 주는 영향 |
|---|---|---|
| 0 | 폐기된 토큰이 다시 필요해질 때 **복원할 것인가**, 손실을 수용하는가 | 복원하면 재접근 감지·복원 방식 선택·재연산이 구조에 추가되고 M-R1이 의미를 가진다. 수용하면 Blend는 Drop과 별개의 기능(재사용 시 보정)이 된다 |
| 1 | 무엇을 버릴지(Drop)와 무엇을 다시 계산할지(Blend)가 **같은 중요도 점수**를 쓰는가, 별개인가 | 같다면 Policy가 하나이고 점수를 공유한다. 별개라면 Policy가 둘이고 Operator 인터페이스가 점수를 공유할 수 없다 |
| 2 | 재연산 시점: 재접근 시 즉시(lazy)인가, 유휴 시 미리(eager)인가 | 재연산이 TTFT에 직렬로 붙는지 결정한다 (원본 §2.3의 실행 시점 축과 비슷하다) |
| 3 | 재연산을 어느 자원에서 실행하는가 | GPU 연산을 소비하므로 DP2와의 접점이다. 원본 M-R1의 "메모리 압력을 GPU 압력으로 전환"과 같은 문제 |
| 4 | Blend로 복원한 KV의 정확도를 누가 보증하는가 | Quality Guard의 위치와 개입 조건 |

---

# 5. DP1 · DP2 · DP4와의 연결

```text
DP1  데이터를 어디에 둘까        위치 결정 (Demote 포함)          ── location 소유
 │
DP2  연산을 어디서 할까          연산 배치 (Prefill, 재계산, 선택 재계산의 실행 위치)
 │
DP3  쌓인 데이터를 어떻게 줄일까  충실도 결정 (Drop, Blend / 확장: Compress, Select) ── fidelity 소유
 │
DP4  이 순환을 서버 여러 대로 확장할 때 결정을 어디서 내릴까
```

| 연결 | 내용 |
|---|---|
| DP1 → DP3 | §2.4 규칙 유지: DP1 먼저, 용량 제약 실패 시에만 DP3. location/fidelity 직교 모델(§3.3)로 데이터 수준에서 보장 |
| DP3 → DP2 | Drop 후 재접근 시의 재연산(M-R1)과 Blend의 선택 재연산은 **연산 수요**를 만든다. 흐름은 DP1(배치) → DP2(연산) → DP3(축소)이지만 Blend 때문에 **DP3 → DP2로 되돌아오는 경로**가 생긴다. 원본 M-R1은 "Prefill은 GPU 고정"을 전제하므로 DP2 문서와 맞춰야 한다 |
| DP3 → DP4 | 서버 간에 Drop·Blend 상태(어떤 토큰이 폐기·재연산됐는지)를 공유해야 하고, 확장 동작(Compress, Select)을 도입하면 압축된·선택된 KV가 서버 간 전송·공유에 쓰이므로 **충실도 메타데이터와 압축 포맷의 서버 간 일치**가 필요하다. 포맷 버전 불일치는 새로운 위험이다 |

### 명칭 정정 (확인 완료)

DP1 후보의 명칭은 DP1 문서 기준이 맞다고 확인되었다.

| | DP1 문서 (기준) | 원본 DP3 §7의 현 표기 | 정정안 |
|---|---|---|---|
| C1 | **Type-agnostic Placement Registry** (Resource State-driven Migration) | "Memory State based" | "DP1-C1: Type-agnostic Placement Registry (Resource State-driven)" |
| C2 | **Type-aware AI Data Registry** (AI Data Behavior-driven Migration) | "Data Property based" | "DP1-C2: Type-aware AI Data Registry (AI Data Behavior-driven)" |

원본 §7의 본문 설명(C1은 Capacity/BW/Load를, C2는 Access Pattern/Hotness/Lifetime을 신호로 쓴다)은 DP1 문서 §4의 "핵심 decision signal" 행과 의미가 일치하므로 **명칭만** 바꾸면 된다. 해당 위치: 원본 §7의 도식 라벨(`C1. Memory State based` / `C2. Data Property based`)과 "DP1-C1을 선택하는 경우" / "DP1-C2를 선택하는 경우" 소제목.

### 용어 충돌 주의

DP1 문서는 victim을 고르는 컴포넌트를 **"Data Eviction Manager", "generic eviction policy"** 라고 부른다(DP1 §5.3 C1). 이것은 위치를 옮길 대상을 고르는 것이라 DP3의 용어 고정(**Eviction = Drop**)과 의미가 다르다. 한쪽을 "Victim Selection" 등으로 바꾸거나, 각 문서 서두에 구분을 명시하는 것을 권한다.

---

# 6. 평가 지표 — 원본 §9 대비 추가·변경

원본의 원칙(가정값 미기재, B1 = 1.0 기준선, Performance와 Accuracy를 합치지 않음, 이중 보고)은 그대로 둔다.

| 항목 | 변경 | 이유 |
|---|---|---|
| **M-C5 확장** | Drop/Demote 분해에 **Recompute 항목**(선택 재연산 토큰 수, 전체 재계산 횟수)을 추가. 확장 동작 도입 시 Compress·Select 바이트도 분해 | Drop의 이득과 Blend 복원 비용을 분리하고 DP1(Demote)의 이득과도 분리 |
| **M-R1 변경** | 재계산 비용을 "Prefill 전체 재연산"이 아니라 **선택 재연산 비용 + 전체 재계산 fallback 비용**으로 정의 | 복원 절차를 두는 경우, Blend가 Drop의 재접근 비용을 줄이는 효과를 측정에 반영 |
| **M-B1 (신규)** | Blend의 재연산 토큰 비율과 그에 따른 Accuracy 회복량(Drop 후 · Blend 후 · B0 대비) | 선택 재연산이 비용 대비 정확도를 얼마나 되돌리는지 |
| **M-A1 귀속** | 동작을 **하나씩 켜는 단독 조건(ablation)**(Drop만 / Drop + Blend)을 대조군에 추가하고 Accuracy 손실을 동작별로 귀속 | 정확도 손실이 Drop에서 오는지 Blend 근사에서 오는지 분리 |
| **M-M1 (신규)** | Modifiability: 새 연산자를 추가할 때 변경되는 모듈 수·인터페이스 수·LOC·신규 type-specific 분기 수 | S1/S2 비교용. [`qa-evaluation-criteria.md`](../Evaluation/qa-evaluation-criteria.md) §7의 보조 측정 항목을 따른다 |
| **M-G1 (신규)** | Quality Guard 개입률과 복구 비용(full 복원·재계산 시간) | Guard가 자주 개입하면 한도 설정이나 Policy가 잘못된 것 |
| **Sweep 추가** | Accuracy Budget 크기, 연산자 조합, (C2, S2)의 attention 점수 export 경로 | 후보 우열이 바뀔 수 있는 축 |
| **정합성 점검 확장** | 원본 "Drop이 0이면 Accuracy는 B0와 같아야 한다"를 "**손실 허용 동작이 모두 0이면** B0와 같아야 한다"로 확장 | 측정 파이프라인 오류 검출 |

---

# 7. 원본에 반영한다면 — 변경 목록

| 원본 위치 | 변경 |
|---|---|
| §1 ③ | "Low Tier로 Eviction" 표현을 "폐기(Drop)"로 고친다 (사용자 확인: 하신 eviction은 폐기) |
| §2.1 | 동작 분류 표를 확장하고 Drop–Blend 쌍을 명시 (본 문서 §2) |
| §2.1 인용문, §6 서두 | "Drop에서만 성립"을 "손실 허용 동작이 포함될 때"로 일반화 |
| §3 | 설계 쟁점 2 신설 (본 문서 §3.1) |
| §5 (C2) | 온라인 방식의 "실제 질의로 Stage 1 attention 수행"을 명시 (본 문서 §4.4) |
| §4~§6 뒤 | S1/S2 후보와 조합 표 신설 (본 문서 §3.5~§3.6) |
| 신설 | 공통 컴포넌트, 블록 메타데이터 (본 문서 §3.2~§3.4) |
| §7 | DP1 후보 명칭을 DP1 문서 기준으로 정정 (본 문서 §5) |
| §9.5 M-R1 | 재계산 비용을 선택 재연산 기준으로 재정의 (본 문서 §6) |
| §9 | 지표 추가·변경 (본 문서 §6) |
| §10 | 선정 질문에 "S1과 S2 중 어느 범위에서 무엇이 성립하는가"를 추가 |

---

# 8. 열린 질문과 위험

| # | 내용 | 영향 |
|---|---|---|
| 1 | (해소) 내려간 토큰은 폐기 (§4.5). 복원 절차는 미설계 (§4.6 #0) | 해소 / 후속 설계 |
| 1-b | 엔진 수정 범위와 blending의 적용 시나리오(§2.4 공유 Block 규칙과의 충돌 여부)는 아직 확인하지 않았다 | 정정 필요 |
| 2 | 범위 확대로 DP3가 DP1·DP2와 다시 겹칠 수 있다. 직교 속성 모델(§3.3)과 DP1 우선 규칙으로 막는 설계이나, 실제 충돌 사례는 prototype으로 확인해야 한다 | 경계 위험 |
| 3 | (C2, S2) 조합의 attention 점수 export 비용 | S2 평가의 핵심 위험 |
| 3-b | Drop과 Blend의 선택 기준 공유 여부, 재연산 시점, Blend 복원 KV의 정확도 보증 (§4.6) | 구조 설계 입력 |
| 3-c | **Drop의 손실에 Blend의 근사가 더해지는 이중 정확도 위험** — 분리해 측정하지 않으면 원인 귀속이 안 된다 | M-A1 단독 조건으로 대응 |
| 4 | 정확도 측정 인프라(task, 지표, 한도)를 먼저 정의해야 후보 비교가 성립한다. 원본 §9.4의 M-A1 정의를 따른다 | 선행 조건 |
| 5 | (확장 동작 도입 시) 압축된 KV를 서버 간에 공유할 때 포맷·파라미터 버전 불일치(DP4와의 접점) | DP4 설계 입력 |
| 6 | 부록의 문헌 항목은 대부분 arXiv 초록 수준의 확인이며, 인용 전 원문(모델·벤치마크·수치) 재확인이 필요하다 | 근거 수준 [B] |
| 7 | 표의 우열·Modifiability 점수는 모두 구조 논증 [C]이며 prototype 실측 전에는 정성 가설이다 | 원본 §6과 같은 원칙 |

---

# 부록 A. 문헌 앵커 (분류 근거)

**근거 수준 [B]. 조사 에이전트가 초록을 열람한 분류를 옮긴 것이며, 이 문서에서 직접 재확인한 것은 CacheBlend뿐이다. 수치는 인용하지 않는다.**

| 분류 | 이름 | 위치 | URL |
|---|---|---|---|
| Compress (HBM 내부 양자화) | KIVI | 엔진 내부 | arxiv.org/abs/2402.02750 |
| | KVQuant | 엔진 내부 | arxiv.org/abs/2401.18079 |
| Compress (전송·저장 경계) | CacheGen | 전송·디스크 | arxiv.org/abs/2310.07240 |
| | KVTC | HBM·오프로드·디스크 | arxiv.org/abs/2511.01815 |
| Select (전체 KV 보존) | Quest | 엔진 내부 | arxiv.org/abs/2406.10774 |
| | InfiniGen | CPU 보관 + prefetch | arxiv.org/abs/2406.19707 |
| | ShadowKV | low-rank K + V 오프로드 | arxiv.org/abs/2410.21465 |
| Drop (비가역 eviction) | H2O | 엔진 내부 | arxiv.org/abs/2306.14048 |
| | StreamingLLM | 엔진 내부 | arxiv.org/abs/2309.17453 |
| | SnapKV | 엔진 내부 | arxiv.org/abs/2404.14469 |
| Blend / Selective Recompute | **CacheBlend** (직접 확인) | 재사용 시점 | arxiv.org/abs/2405.16444 |
| 검증형 압축 (출력 동일) | VeriCache | 압축 KV로 초안, 원본으로 검증 | arxiv.org/abs/2605.17613 |

CacheBlend 초록(직접 확인): 재사용 KV 캐시에서 **토큰의 일부만 선택적으로 재계산**해 각 재사용 KV를 갱신한다. 초록은 TTFT 2.2~3.3배 감소, 처리량 2.8~5배 증가를 보고한다(논문 주장, 실험 조건은 본문 확인 필요).

조사 원본: 에이전트 조사 결과 전문은 세션 작업 디렉터리의 `research/03-kv-compression.md`에 있다 (저장소에는 포함하지 않음).
