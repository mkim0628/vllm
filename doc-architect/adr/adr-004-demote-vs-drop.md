# ADR-004. 회수를 Demote와 Drop으로 가르고 Drop만 DP3에 귀속시킨다

| | |
|---|---|
| **상태** | Accepted |
| **일자** | 2026-09-15 |
| **범위** | DP3 (DP1과의 경계를 정의) |
| **근거 문서** | DP3 설계 문서 §2.1, §2.2 / DP3 구현 UML §0, §2.1 |

---

## 1. Context

DP3 설계 문서는 회수 동작을 일관되게 **"Low Tier로 Eviction"** 이라고 서술했다. 그런데 평가 지표는 `Fully Retained KV 대비 Task Accuracy`, `중요 KV 오분류율`을 포함했다.

**두 서술은 양립하지 않는다.** KV를 하위 계층으로 **옮기면** 내용이 보존되므로 Attention 결과가 비트 단위로 동일하고 Accuracy 손실이 발생하지 않는다. Accuracy가 떨어지려면 KV를 **버려야** 한다.

이 모순을 방치하면 DP3의 핵심 Trade-off("System Efficiency ↔ Model Accuracy")가 근거 없이 서 있게 되고, 측정 단계에서 **Accuracy 손실이 0으로 나와도 그것이 설계가 옳아서인지 지표가 틀려서인지 구분되지 않는다.**

**Goals**

- 회수 동작의 의미를 하나로 고정한다
- DP1과 DP3의 역할 경계를 동작 수준에서 가른다
- Attention Importance를 쓸 이유가 있는 범위를 명확히 한다

**Non-goals**

- 어떤 KV를 버릴지의 판단 기준 — 그것이 C1/C2의 축이다

## 2. Decision Drivers

| 순위 | Driver | 왜 중요한가 |
|---:|---|---|
| 1 | 측정 가능성 | 구분이 없으면 Accuracy 지표를 해석할 수 없다 |
| 2 | 역할 경계 | DP1과 DP3가 같은 동작을 두고 경쟁하면 안 된다 |
| 3 | 되돌릴 수 있는가 | Drop은 되돌릴 수 없다 — 다른 무게의 결정이다 |

## 3. Options Considered

| 옵션 | 요약 | 장점 | 단점 | 되돌리기 |
|---|---|---|---|---|
| **A. 회수를 단일 동작으로 유지** | 현행 서술 유지 | 문서 변경 없음 | **Accuracy 지표가 근거를 잃는다.** DP1의 Demote 이득이 DP3 성과로 집계된다 | — |
| **B. Demote와 Drop을 가르고 둘 다 DP3가 수행** | DP3가 회수 전반을 소유 | 회수 로직이 한곳 | **DP1의 배치 결정과 직접 충돌.** 같은 KV를 두 정책이 서로 다른 기준으로 옮긴다 | 어려움 |
| **C. Demote는 DP1, Drop은 DP3** | 채택 | 역할 경계가 동작과 일치. Accuracy가 Drop에만 귀속되어 해석 가능 | DP3의 적용 범위가 좁아진다 — 그만큼 이득 주장도 작아진다 | 어려움 |

## 4. Decision

**옵션 C를 선택한다.**

| | **Demote (강등)** | **Drop (폐기)** |
|---|---|---|
| 회수되는 것 | HBM 용량만 | 전체 용량 |
| Accuracy | **무손실** | **손실 발생** |
| 되돌리기 | Restore 또는 in-place 연산 | **불가** — 재계산뿐 |
| **결정 주체** | **DP1** | **DP3** |

- **Attention Importance가 Accuracy와 교환되는 것은 Drop에서만 성립한다.** Demote만 하는 구조에서는 재접근 시점·확률로 충분하며 그것은 DP1의 기준이다.
- **용어를 고정한다** — DP3 문서에서 "Eviction"은 Drop을 가리킨다.
- 옵션 B는 DP1을 무력화한다. 옵션 A는 지표가 무의미해진다.

## 5. Architecture Impact

**경계와 계약**

- `ReclaimAction`이 `DEMOTE`/`DROP` 두 값을 갖고, **`DROP`은 DP3 정책만, `DEMOTE`는 DP1 정책만 발행할 수 있다.** 하나의 정책이 둘 다 내면 구분이 런타임에 무너진다.
- `ReclaimPlan.issued_by`가 발행 주체를 값으로 들고 다닌다.

**측정에 미치는 영향 (가장 중요한 귀결)**

- **대조군이 셋이 된다** — B0(No Reclamation) / B1(Demote-only) / 후보(B1 + Drop).
- **기준선은 B1이다.** B0 대비로 보고하면 DP1의 Demote 이득이 DP3 성과로 집계된다.
- `M-C5 Drop/Demote 분해`가 **DP3가 실제로 한 일의 크기**를 재는 지표가 된다.
- **Drop이 0인 실행에서 Accuracy가 B0와 다르면 측정 파이프라인 오류다** — 정합성 점검으로 쓸 수 있다.

**실패 모드**

| 실패 모드 | 조기 탐지 |
|---|---|
| 구현이 Demote를 Drop으로 집계 | Drop 0건 실행에서 Accuracy가 B0와 불일치 |
| B0를 기준선으로 보고 | M-C5의 Drop 비중이 낮은데 Goodput 개선을 DP3 성과로 주장 |

## 6. Validation

- **정합성 점검을 먼저 돌린다** — Drop 비율 0으로 고정한 실행의 Accuracy가 B0와 일치해야 한다. 불일치하면 이후 모든 Accuracy 결과가 무효다.
- **M-C5와 M-A1을 같은 그래프의 두 축으로 보고한다.** 이 한 장이 본 결정이 만든 Trade-off 전부다.

## 7. Consequences

**긍정**

- Accuracy 지표가 해석 가능해진다
- DP1/DP3의 이득이 분리되어 집계된다
- Drop의 되돌릴 수 없음이 타입에 드러나 설계에서 조심스럽게 다뤄진다

**대가**

- **DP3의 주장 가능 범위가 줄어든다.** B1이 이미 용량 제약을 해소하는 구성에서는 DP3가 불필요하다는 결론이 나올 수 있다 — 이는 실패가 아니라 결과이며, 조건부 선정에 그대로 기술한다
- 기존 §6 Trade-off 표가 조건부(Drop을 포함할 때만 유효)가 된다

## 8. 재검토 트리거

| 트리거 | 무엇이 달라지는가 |
|---|---|
| **손실 압축(Quantization·저정밀 저장)을 회수 수단에 추가** | Demote와 Drop 사이의 제3의 동작이 생긴다. Accuracy 손실이 있으면서 되돌릴 수는 있는 동작이므로 `ReclaimAction`에 값을 추가하고 본 ADR을 갱신해야 한다 |
| 연산형 계층 용량이 충분히 커져 (a)(b)(c)가 발생하지 않음 | DP3 자체가 불필요해진다 |
| 재계산 비용이 Drop 비용보다 항상 작은 워크로드 발견 | Drop의 대가 구조가 달라진다 |

## 9. Links

- DP3 설계 문서 §2.1 · §2.2 · §9.2 · §9.4
- DP3 구현 UML §0 · §2.1 · §3.1 · §3.5
- [ADR-005](adr-005-dp1-before-dp3.md) — 이 구분 위에 서는 순서 결정
- [ADR-006](adr-006-shared-block-drop-exclusion.md) — Drop의 되돌릴 수 없음에서 나오는 범위 제한
