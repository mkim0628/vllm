# DP1 프로토타입 명세

무엇을 어떻게 재는지에 대한 참조 문서.
결과는 [`dp1-prototype-results.md`](dp1-prototype-results.md)에 있다.

---

## 1. 목적함수 `J`는 무엇인가

```
J = Σ 접근시간 + Σ write시간 + Σ migration시간     [단위: 초]
```

**총 메모리 점유 시간**이다. 시뮬레이션이 끝난 뒤 채점자가 각 객체의 실제 접근
이력을 전부 훑어 합산한다.

### J가 재는 것

문서 §7의 4개 QA 중 **Performance Efficiency 한 칸**이다. 그것도 부분적이다.

| §7 QA | J가 재는가 |
|---|---|
| Performance Efficiency | **부분적으로 재고 있음** (아래 한계 참조) |
| Functional Correctness | ✗ |
| Maintainability | ✗ |
| Flexibility | ✗ |

**`J`만 보고 "어느 후보가 낫다"고 판단하면 질문의 1/4에 답한 것이다.**
나머지 3개는 이 문서 §4에서 별도 지표로 산출한다.

### J의 세 항

`J = Σ 접근시간 + Σ write시간 + Σ migration시간`의 세 항은 모두 같은 모양이다:

```
시간 = 지연(latency) + bytes / 유효대역폭(bandwidth)
```

"지연"과 "유효대역폭"이 **경합에 따라 이미 보정된 값**이라는 것이 핵심이다.
경합은 네 번째 항이 아니라, 위 세 항 전부에 공통으로 곱해지는 배수(§2)다 —
별도로 더하는 비용이 없다.

**접근 비용.** GPU 연산은 HBM을 읽는다. GPU가 직접 못 읽는 tier에 있는 데이터는
HBM으로 먼저 스트리밍해야 한다(staging). 이 전송을 **매 접근마다** 과금하며,
객체를 HBM으로 승격시키지 않는다.

```
if 이 tier가 그 연산을 자체 처리 가능:
    지연(경합 보정) + bytes / 유효_내부대역폭(경합 보정)
elif GPU가 이 tier를 직접 읽을 수 있음:
    지연(경합 보정) + bytes / 유효_외부대역폭(경합 보정)
else:
    (tier에서 읽기, 경합 보정) + (HBM에서 읽기, 경합 보정)    ← staging
```

매 접근마다 과금하는 이유: 이 설계 포인트가 다루는 객체가 실제로 그렇게 쓰인다.
수 TB짜리 embedding table은 요청마다 gather하고 승격시키지 않는다. 그리고 이 항이
**연산-capability 매칭이 성능으로 환산되는 유일한 경로**다. 이게 없으면 capability
매칭은 주장만 가능하고 획득이 불가능하다.

부작용: 느린 tier에 잘못 놓인 hot 객체는 누군가 옮겨줄 때까지 계속 비싸다.
그게 reactivity 축이 존재하는 이유다.

**Write 비용.** flash 계열은 증폭된 write를 지불하고 유한한 endurance를 소모한다.
read 중심 지표로는 저내구성 매체에 놓인 write 집약 객체가 보이지 않으므로 별도로
과금하고 tier별 endurance pressure를 추적한다.

### J가 재지 않는 것 — 결과 해석에 중요

**GPU occupancy 항이 없다.** 메모리 안에서 연산을 돌리면 GPU 연산 유닛이 비어
다른 일을 할 수 있다. 메모리 시간만 보는 목적함수에는 이 이득이 보이지 않는다.
따라서 **compute-capable memory에 관한 모든 결과는 이득의 하한**이다.

**에너지 항이 없다.** 같은 방향으로 작용한다.

**Rejection이 J에 포함되지 않는다.** 별도로 센다. 페널티를 매기면 정책이 저자가
정한 환율로 "거부"와 "지연"을 맞바꿀 수 있게 된다. 대신 rejection이 있는 실행은
**비교 불가**로 표시한다. 보고된 전 조건에서 rejection은 0이다.

### 정규화

절대 초 값은 스케일 의존적이므로, 문서 §2의 **As-Is (HBM 우선 할당)** 를 1.0으로
정규화한다. 낮을수록 좋다. As-Is를 분모로 쓰는 이유는 문서가 이미 그것을 오늘의
정책이라고 주장하기 때문이다 — 이 프로토타입이 증명할 수 없는 최적해를 분모로
쓰지 않는다.

---

## 2. 경합 — 세 항에 공통으로 곱해지는 배수

경합은 §1의 세 항과 나란히 더해지는 네 번째 항이 **아니다.** 접근시간·write시간·
migration시간 각각을 계산할 때 쓰는 지연과 유효대역폭 **자체가 경합에 따라
보정된 값**이다.

```
유효대역폭(tier, 이용률 u) = 피크대역폭 × 대역폭_비율(u)
지연(tier, 이용률 u)       = 피크지연 × (1 + α · min(u, cap)^p)
```

대역폭은 공유 자원이고, 경합하면 피크보다 적게 나온다 — row-buffer 충돌, bank
충돌, 프로토콜 오버헤드, flash garbage collection. **유계** 효율 손실로
모델링하며, 달성 대역폭이 floor(기본 0.4)로 수렴하고 그 이하로 안 떨어진다.

> **유계여야 하는 이유:** 초기 버전은 지연을 `지연 × (1 + α·u²)`로 무한히
> 키웠는데, 이는 이중 계산이다. `J`는 tier 점유 시간의 합이고, 포화된 tier의
> 총 점유 시간은 이미 선형 전송 항의 `D/bw`로 계산돼 있다. 그 버전은 0.2초
> 구간에 **32,000초**를 산출했고, 완벽한 정보를 가진 정책이 naive baseline보다
> 4배 나쁘게 나왔다.

경합 항이 **왜 필요한가:** 없으면 집중이 공짜가 되어 "가장 빠른 tier에 용량
한계까지 밀어넣기"가 항상 최적이 되고, **tier의 load라는 신호가 아무 정보도
갖지 않는다.** 그러면 memory-state-first 정책이 조용히 capacity-only 정책으로
퇴화한다. 경합이 load에게 최적화할 대상을 준다.

이 배수는 접근·write·migration 세 항 **전부**에 적용된다. migration의 경우
src와 dst 중 더 붐비는 쪽의 유효대역폭을 쓴다.

---

## 3. 정책 5개

| 이름 | 역할 | 무엇을 보는가 |
|---|---|---|
| `hbm_first` | **As-Is 기준선**, 모든 정규화의 분모 | capacity만. GPU-reachable 우선, 그 다음 대역폭 내림차순으로 first fit |
| `random` | **탐지기.** 명백히 최악이어야 함 | 여유 있는 tier 중 균등 무작위 |
| `trace_aware` | **참조.** 얼마나 여유가 있는지 표시 | 진짜 접근 이력 (의도적 반칙) |
| `memory_centric` | **후보 C1** | tier 관측값 + 선언된 요청. **지금, 1회 접근** |
| `data_centric` | **후보 C2** | 같은 tier 관측값 + **추정된** 접근률·lifetime·write 비율. **객체 생애 전체** |

### C1과 C2의 구조적 차이

문서 §5가 정확히 말한다: 두 후보 모두 memory state를 볼 수 있고, 차이는 **어떤
특성이 후보를 형성하는가**다. 그대로 구현했다.

- **C1**: 공유 추정기를 **현재 관측된 load를 넣어서** 호출 → memory state가
  점수 **안에** 있고 어느 tier가 이기는지를 결정
- **C2**: 같은 추정기를 **빈 demand map으로** 호출해 데이터 적합도만으로 후보
  집합을 만들고 → 그 안에서 memory state가 선택

**두 후보는 동일한 산술을 쓴다.** 각자 다른 점수 함수를 주면 비교가 "누가 heuristic을
더 잘 썼는지"를 재게 된다. 다른 것은 **입력과 시간 지평**뿐이다.

### 왜 `trace_aware`가 하한이 아닌가

객체별 greedy이고 미래 경합을 모른다. 실제로 한 조건에서 As-Is에 진다. 그래서
분모로 쓰지 않고 "여유가 얼마나 남았는지" 표시로만 쓴다.

---

## 4. QA 4개를 각각 어떻게 재는가

증거의 **종류가 다르므로** 그 사실을 명시한다.

| QA | 증거 종류 | 방법 |
|---|---|---|
| Performance Efficiency | **측정** | 목적함수 `J`, As-Is 대비 정규화 |
| Functional Correctness | **측정** | 입력 오차 → 결과 오차 전달 함수 |
| Maintainability | **대리 지표** | 소스에서 센 구조적 수치 |
| Flexibility | **실험** | 새 tier를 넣고 실제로 쓰는지 확인 |

### Functional Correctness

§7: "입력 정보 및 예측 오차가 존재할 때 적절한 Placement를 결정할 수 있는가"

추정기에 **알려진 오차**를 주입하고, 그것이 배치 결과에 얼마나 도달하는지 본다.

```
증폭률 = (해당 오차에서의 J / 오차 0에서의 J − 1) / 입력 오차
```

추정하지 않는 정책은 증폭률이 **정확히 0**이다 — 이건 정의상 그렇고, 검증
가능하다(C1이 전 구간 0.0000). 추정하는 정책은 전달 함수를 갖고, **그 함수가
곧 이 QA**다.

### Maintainability

§7: "Placement 정책의 구현·분석·검증·변경이 용이한가"

런에서 측정 불가능하므로 소스에서 센다:

| 지표 | 의미 |
|---|---|
| decisions | 결정 경로의 분기·루프 수 |
| knobs | 동작을 바꾸는 생성자 인자 (공유 협력자·reactivity 제외) |
| state | 엔진 residency와 일관성을 유지해야 하는 정책 내부 dict 수 |
| methods | 정책에 정의된 호출 가능 객체 수 |
| lines | 빈 줄·주석 제외 |

> **이건 대리 지표다.** 변경 비용과 상관은 있지만 그것을 측정하지는 않는다.
> 논증의 방향으로 읽어야 하고 결론으로 읽으면 안 된다.

### Flexibility

§7: "새로운 Memory/Data/Operation 특성에 대응 가능한가"

런이 산출하는 숫자가 아니라 **실험**이다. pool에 없던 조합의 tier를 추가하고,
각 정책이 거기에 무언가를 놓는지 본다.

추가한 tier (`dram_pnm`, [`configs/tiers_plus_elementwise_pnm.json`](configs/tiers_plus_elementwise_pnm.json)):

| 속성 | 값 | pool에서 새로운 점 |
|---|---|---|
| 외부 대역폭 | 150 GB/s | DRAM과 CXL 사이 |
| 내부 대역폭 | 600 GB/s (4배) | 넓은 내부 경로 + DRAM급 지연 조합이 없었음 |
| 지연 | 200 ns | |
| in-place 연산 | ELEMENTWISE | `tiers_default.json`의 6-tier pool에서 지원 tier가 **0개**인 유일한 non-GEMM/GEMV 연산 |
| 용량 | 2 TiB | |

기존 `Medium`(DRAM)의 새 인스턴스로 만든 것은 **의도적**이다. 그러면 코드 수정 없이
로드되므로, 이 실험이 enum 편집이 아니라 **정책의 적응력**을 측정한다.

> **점수가 좋으면서 새 매체를 무시하는 정책은 적응한 것이 아니다.** 그것에도
> 불구하고 성공한 것이다. 그래서 `adapted` 여부를 objective 변화와 **따로**
> 보고한다.

---

## 5. 시나리오 13개

각 시나리오는 **어떤 변수를 고립시키는가**로 정의된다. 예상 승자는 기재하지 않는다.
그렇게 쓰면 파라미터 범위를 그 결론이 나오게 고르게 된다.

공통 설정: 120 step, scale 0.25, 조건별 20 paired seeds.

### tier pool과 연산 커버리지

`configs/tiers_default.json`의 6-tier pool은 `ComputeOp` 6종을 균등하게
지원하지 않는다.

| tier | medium | 지원 연산 |
|---|---|---|
| `hbm` | HBM | 없음 (승격 대상) |
| `custom_hbm` | CUSTOM_HBM | GEMM |
| `dram` | DRAM | 없음 |
| `cxl` | CXL | GEMM |
| `hbf` | HBF | 없음 |
| `ssd_pim` | SSD_PIM | GEMV |

`ELEMENTWISE`, `EMBEDDING_LOOKUP`, `SCAN`, `TOPK` — 이 넷은 지원 tier가
**0개**다. 이 연산이 주 연산인 구산자(`ACTIVATION`, `EMBEDDING_TABLE_SHARD`,
`RAG_INDEX_SHARD`)는 어느 정책을 쓰든 항상 HBM으로 staging된다. 이는 이
pool의 실제 귀결이며, `pim_heavy`처럼 SCAN/gather 위주 워크로드를 고립시키는
시나리오를 읽을 때 전제로 깔아야 한다 — §2 결과의 "`pim_heavy`에서 C1이
이긴다" 절에서 이 사실이 왜 중요한지 다룬다.

### Capacity 압력 3단계

**"tier 배율"은 해당 tier의 `capacity_bytes`에 곱하는 배수다.** 대역폭·지연은
그대로 두고 용량만 줄여서, "이 워크로드가 실제 물리 pool보다 훨씬 크다면"을
흉내 낸다. `configs/tiers_default.json`의 원래 용량 기준:

| 이름 | tier 배율 | 실제 크기로 환산 | 왜 이렇게 |
|---|---|---|---|
| `ROOMY` | 없음 (배율 딕셔너리가 비어있음) | HBM 192 GiB 그대로 | 워크로드가 가장 빠른 tier에 다 들어감 |
| `HBM_ONLY_SQUEEZE` | hbm×0.05, custom_hbm×0.05 | HBM 192→9.6 GiB | GPU-reachable만 줄임. **DRAM이 넘침을 쉽게 흡수** |
| `FULL_SQUEEZE` | hbm×0.02, custom_hbm×0.02, dram×0.02 | HBM 192→3.84 GiB, DRAM 1TiB→20.5 GiB | 빠른 tier 전부 줄임. 객체가 **정말 부적합한 매체까지** 내려감 |

> HBM만 줄이면 계층 압력이 생기지 않는다. HBM이 내놓은 것을 custom_hbm이,
> 그 나머지를 DRAM이 흡수해서 **어떤 정책도 나쁜 선택지 사이에서 고민하지 않는다.**
> 그래서 `HBM_ONLY_SQUEEZE`는 custom_hbm도 함께 줄이고, `FULL_SQUEEZE`는 DRAM까지
> 줄인다.

### 고정 시나리오

처음 8개는 memory-level 시나리오다 — "메모리에 무슨 일이 생기는가"로 정의된다.
나머지 5개는 application-level 시나리오다 — 서빙이 실제로 마주치는 워크로드
패턴(long-context, multi-tenant, reasoning, MoE, agentic tool-calling)이
KV cache의 hotness·lifetime·접근률에 미치는 영향으로 정의된다. 모두 기존
knob(`mix`, `capacity_scales`, `sample_rate`)과 새 knob
`spec_overrides`(§6 참조)만 조합하며, 신규 `DataClass`는 쓰지 않는다.

| # | 이름 | 고립시키는 변수 | 설정 |
|---|---|---|---|
| 1 | `baseline` | 가장 빠른 tier에 여유가 있으면 배치가 의미가 있는가? | ROOMY |
| 2 | `hbm_pressure` | GPU-reachable tier만 희소할 때 어떻게 되는가? | HBM_ONLY_SQUEEZE |
| 3 | `hierarchy_pressure` | 빠른 tier가 전부 희소할 때 어떻게 되는가? | FULL_SQUEEZE |
| 4 | `pim_heavy` | scan/gather 위주 워크로드에서 연산-capability 매칭이 얼마를 벌어주는가? | FULL_SQUEEZE + RAG 4배, embedding 4배, KV 0.3배 |
| 5 | `write_heavy` | write 집약도가 배치를 바꾸는가? | FULL_SQUEEZE + KV 2.5배, activation 2.5배, RAG 0.3배 |
| 6 | `hotness_drift` | 접근 mix가 변할 때 재배치가 비용을 정당화하는가? | FULL_SQUEEZE + reactive + step 60에서 접근률 4배 |
| 7 | `partial_observation` | profiling이 샘플링만 할 수 있을 때 data-first가 무엇을 잃는가? | FULL_SQUEEZE + reactive + sample_rate 5% |
| 8 | `flexibility_new_tier` | pool에 없던 매체를 쓰는가, 존재를 견디는 것인가? | FULL_SQUEEZE + `dram_pnm` 추가 |
| 9 | `long_context` | long context로 KV block **개수**가 늘고 각 block도 더 오래·느리게 식을 때 hotness·lifetime 추정이 버티는가? | FULL_SQUEEZE + reactive + KV 3배 + KV lifetime (150,1500)·decay 0.995 |
| 10 | `multi_tenant` | 많은 tenant가 섞여 추적 예산이 부족할 때 data-first의 추정이 완만하게 저하되는가? | FULL_SQUEEZE + reactive + sample_rate 5% + KV 2.5배 |
| 11 | `reasoning` | 개수는 그대로, chain-of-thought로 개별 block의 lifetime만 길어질 때 `long_context`와 구별되는가? | FULL_SQUEEZE + reactive + KV lifetime (600,3000) |
| 12 | `moe_heavy` | expert weight 트래픽이 지배하고 KV cache가 줄어들 때 read-intensive·routing-skew 트래픽이 배치를 바꾸는가? | FULL_SQUEEZE + MoE 4배, KV 0.3배 |
| 13 | `agentic_tool_calling` | tool-call 대기 중 KV cache가 "점유는 비싸고 접근은 드묾" 상태일 때 어느 후보가 덜 비싼 곳에 두는가? | FULL_SQUEEZE + reactive + KV accesses_per_step (0.02,0.15)·lifetime (300,2000)·decay 1.0 |

`hierarchy_pressure` ↔ `flexibility_new_tier`는 **쌍으로 읽어야** 의미가
나온다. `long_context`와 `reasoning`도 쌍이다 — 전자는 KV block **개수**가
늘고 각 block의 lifetime도 늘지만, 후자는 개수는 그대로 두고 lifetime만
늘려서 두 메커니즘을 분리한다.

`agentic_tool_calling`의 스코프 한계: 전체 KV population을 agentic-idle로
모델링하며, steady-decode와 혼합된 배치는 표현하지 않는다. 혼합 배치를
지원하려면 새 `DataClass`가 필요하며, 이번 스코프에서는 하지 않는다.

### Sweep 3개

한 파라미터를 훑어 우열이 바뀌는 지점을 찾는다. 단일 수치는 "튜닝했잖아"라는
반론을 자초하므로 sweep이 고정 시나리오보다 중요하다.

| 이름 | 파라미터 | 범위 | 기반 시나리오 | 고립시키는 변수 |
|---|---|---|---|---|
| `epsilon` | 추정기 노이즈 크기 | 0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.9 | `hierarchy_pressure` | 어느 추정 품질에서 앞을 보는 것이 값을 못 하게 되는가? |
| `bias` | 계통 오차 | 0, 0.2, 0.4, 0.8 (ε=0.1 고정) | `hierarchy_pressure` | 계통 미보정이 같은 크기의 무작위 노이즈보다 나쁜가? (평균해서 사라지지 않으므로) |
| `sample_rate` | profiling 추적 비율 | 0.01, 0.05, 0.2, 0.5, 1.0 | `hierarchy_pressure` + reactive | data-first가 얼마의 추적 범위를 필요로 하는가? |

`epsilon`은 **log 스케일 노이즈 크기**이고 band 오분류 확률이 아니다. band는
오염된 수치에서 파생되며, 실제 band 정확도는 knob에서 가정하지 않고 별도로 측정한다.

### Cost model 민감도 5개

결론의 **부호가 파라미터 선택의 산물인지** 확인한다. 부호가 안정한 구간에서만
주장한다.

| 이름 | 설정 | 의미 |
|---|---|---|
| `default` | floor 0.4, α 1.0, knee 0.5 | 문서화된 기본값 |
| `weak_contention` | floor 0.7, α 0.5 | 경합이 약함 |
| `strong_contention` | floor 0.2, α 2.0 | 경합이 강함 |
| `late_knee` | knee 1.0 | 포화 직전까지 열화 없음 |
| `early_knee` | knee 0.25 | 일찍부터 열화 |

---

## 6. 워크로드: LLM 추론 구산자 7종

객체 수가 3~4 자릿수 차이 난다(weight tensor 10¹ vs KV block 10⁴). **§8의 모든
비가중 비율이 무의미해지는 이유**이고, 모든 비율 지표를 개수 기준과 바이트 기준
양쪽으로 보고하는 이유다.

| 구산자 | 크기 | scale 1.0 개수 | 접근률/step | Lifetime | Write | 연산 | 접근 비율 |
|---|---|---:|---|---|---|---|---|
| Model weights | 512 MiB–2 GiB | 40 | 0.8–1.0 | 런 전체 | 없음 | GEMM | 1.0 |
| KV cache block | 1–16 MiB | 4000 | 0.5–2.0 (감쇠 0.98) | 20–400 step | 5–30% | GEMV | 1.0 |
| Activation | 16–256 MiB | 400 | 2.0–6.0 | 1–4 step | 30–50% | ELEMENTWISE | 1.0 |
| MoE expert | 128 MiB–1 GiB | 256 | 0.02–0.2, **15%가 12배** | 런 전체 | 없음 | GEMM | 1.0 |
| Embedding shard | 1–8 GiB | 16 | 1.0–4.0 | 런 전체 | 없음 | EMBEDDING_LOOKUP | **0.0005–0.005** |
| RAG index shard | 2–32 GiB | 12 | 0.1–1.0, **10%가 8배** | 런 전체 | 없음 | SCAN | 0.05–0.5 |
| LoRA adapter | 16–128 MiB | 64 | 0.2–2.0, **20%가 4배** | 50–500 step | 0–5% | GEMM | 1.0 |

### 시나리오가 행동 자체를 바꾸는 법: `spec_overrides`

`Scenario.mix`는 `ClassSpec.count`만 스케일한다. §5의 application-level
시나리오(`long_context`, `reasoning`, `agentic_tool_calling`)는 **개수가
아니라 행동**을 바꿔야 한다 — KV block이 더 오래 살거나, 접근률이 낮아지거나,
식는 속도가 달라지는 것. `Scenario.spec_overrides`(`{class: {field: value}}`
형태)가 이 knob이다. `WorkloadConfig.with_spec_overrides`가 `dataclasses.replace`로
지정한 필드만 교체하고, `mix`보다 **먼저** 적용된다 — 그래야 override된
스펙의 `count`를 `mix`가 여전히 스케일할 수 있다. 알 수 없는 class key는
`KeyError`로 거부한다.

### class 내부 변동이 의도적인 이유

**class가 행동을 결정하면 lookup table이 오라클이 되고 data-first 후보가 아무것도
추정하지 않고 이긴다.** 그래서 class 안에서 행동이 변한다 — MoE expert는 라우팅
skew가 커서 소수만 hot, KV block은 요청 lifetime에 따라 다른 속도로 식고, RAG
shard는 scan 빈도가 자릿수로 다르다.

결과: 배치 시점에는 관측할 것이 없으므로 추정치가 class prior이고, **ε=0에서도
class에 전형적이지 않은 객체에 대해 틀린다.** 이 오차는 문제의 성질이며 C2에
씌운 핸디캡이 아니다 — KV block을 어디 둘지 결정하는 순간 그 요청이 20 step
살지 400 step 살지 **원래 알 수 없다.**

---

## 7. 무엇이 선언되고 무엇이 추정되는가

공정성 경계다.

| | 정책이 보는가 |
|---|---|
| **선언됨** (요청 안, 모든 정책) | 크기, 구산자 class, 주 연산 |
| **행동적** (추정 필요, C2만) | 접근률, lifetime, write 비율, 접근 비율 |
| **관측됨** (tier 상태, 모든 정책) | 여유 용량, 점유율, **완료된 step**의 load, endurance 소모 |
| **진짜 접근 이력** | 아무도 못 봄. `trace_aware`만 의도적 예외 |

`load`가 완료된 step만 평균하는 것이 핵심이다. 결정 시점에 정책은 아직 끝나지
않은 step의 수요를 알 수 없다. 이것이 **자원 변동을 실제 비용으로 만들고**,
모든 정책에 동일하게 적용된다.

---

## 8. 판정 규칙 (실행 전 고정)

| | |
|---|---|
| Seed | 조건별 20 paired seeds. 모든 정책이 같은 seed에서 **동일한 세계**를 봄 |
| 차이 계산 | seed별로 계산한 뒤 평균. 독립 추출을 비교하면 워크로드 분산이 차이보다 커짐 |
| 신뢰구간 | 95% 양측, paired 차이에 대한 정규 근사 |
| **판정** | **구간이 0을 지나면 "차이 없음"** — 점 추정의 부호가 아니라 |
| Crossover | 단일 지점이 아니라 **band**로 보고. sweep 해상도 이상의 정밀도를 주장하지 않음 |
| 무결성 | rejection이나 dropped migration이 있으면 **비교 불가**로 표시 |

C2−C1이 음수면 data-first가 쌌다는 뜻이다.

---

## 9. 재현

stdlib만 쓴다. torch·numpy·GPU 불필요.

```bash
cd doc-architect

# 커밋된 모든 수치 (약 30~40분, 시나리오 13개 + sweep 3개 + contention 민감도 5개 + QA, 20 paired seeds)
PYTHONPATH=. python -m dp1_placement.run_eval --all

# QA 지표만
PYTHONPATH=. python -m dp1_placement.run_eval --quality

# 한 시나리오만 빠르게
PYTHONPATH=. python -m dp1_placement.run_eval --scenario hierarchy_pressure --seeds 4

# 특정 sweep만
PYTHONPATH=. python -m dp1_placement.run_eval --sweep epsilon
```

원자료는 [`results/dp1_results.json`](results/dp1_results.json)에 커밋되어 있다.
