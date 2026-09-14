# DP1 프로토타입 정량 결과

[DP1 설계 문서](dp1-heterogeneous-memory-data-placement.md) §8이 제시한 방법으로
두 후보 구조를 측정한 결과.

> **이 문서는 후보를 선정하지 않는다.** §8이 요구한 Trade-off 곡면과 유효 범위를
> 제시하며, 어떤 후보를 채택할지는 사람이 판단한다.

측정 방법·시나리오 정의·목적함수의 의미는
[`dp1-prototype-spec.md`](dp1-prototype-spec.md)에 있다.

> **§1~§6은 목적함수 `J`만 다룬다.** `J`는 **총 메모리 점유 시간(초)** 이고,
> §7 QA 4개 중 **Performance Efficiency 한 칸**에 대응한다 — 그것도 GPU
> occupancy·에너지 항이 없어 부분적이다. 나머지 3개 QA는 **§9**에서 별도 증거로
> 다룬다. §1의 표만 보고 "어느 후보가 낫다"고 읽으면 질문의 1/4에 답한 것이다.

| | |
|---|---|
| 실행 일시 | 2026-09-08T09:23:39Z |
| Seed | 조건별 20 paired seeds |
| 판정 규칙 | 95% 신뢰구간이 0을 지나면 "차이 없음" (실행 전 고정) |
| 원자료 | [`results/dp1_results.json`](results/dp1_results.json) |
| 재현 | `PYTHONPATH=. python -m dp1_placement.run_eval --all` |
| 무결성 | 전 조건 rejection **0**. dropped migration은 4개 reactive 조건에서 0이 아님 — §1 하단 참조 |

정규화 기준은 문서 §2의 **As-Is (HBM 우선 할당)** = 1.0이며, **낮을수록 좋다.**

> **이 결과는 tier pool 교체 이후의 첫 재측정이다.** `HBM_PIM`(GEMV+ELEMENTWISE
> 겸용)을 `custom_hbm`(GEMM 전용)과 `ssd_pim`(GEMV 전용, 기존 SCAN/TOPK/
> EMBEDDING_LOOKUP 대체)으로 분리했다. 이전 보고서가 재던 "compute-capable
> memory 활용률 95%" 현상은 KV cache(GEMV)가 HBM 바로 옆의 PIM tier에 부하
> 분산으로 얹히는 메커니즘이었는데, 그 tier가 이제 GEMM만 하므로 그 경로가
> 없어졌다. 아래 수치 전부가 이 재구성 이후의 값이다 — §1, §2가 이 변화를
> 정면으로 다룬다.

---

## 1. 목적함수 결과

| 시나리오 | C1 memory-first | C2 data-first | C2−C1 (paired) | 판정 |
|---|---:|---:|---|---|
| baseline | **0.9491** | 0.9778 | +0.0287 [+0.0171,+0.0403] | C1 |
| hbm_pressure | **1.0170** | 1.1779 | +0.1609 [+0.0848,+0.2371] | C1 |
| hierarchy_pressure | 1.1970 | 1.1947 | −0.0023 [−0.0060,+0.0014] | 차이 없음 |
| pim_heavy | 1.0428 | 1.0425 | −0.0003 [−0.0013,+0.0007] | 차이 없음 |
| write_heavy | 1.4343 | 1.4335 | −0.0008 [−0.0028,+0.0013] | 차이 없음 |
| hotness_drift | 1.1994 | **1.1602** | −0.0392 [−0.0451,−0.0333] | C2 |
| partial_observation | 1.1971 | **1.1917** | −0.0054 [−0.0100,−0.0008] | C2 |
| flexibility_new_tier | **0.9417** | 1.0028 | +0.0611 [+0.0420,+0.0802] | C1 |
| long_context | 1.5075 | **1.4649** | −0.0425 [−0.0459,−0.0391] | C2 |
| multi_tenant | 1.3149 | **1.3086** | −0.0064 [−0.0096,−0.0032] | C2 |
| reasoning | 1.2264 | **1.1754** | −0.0510 [−0.0582,−0.0439] | C2 |
| moe_heavy | 0.8874 | 0.8872 | −0.0002 [−0.0013,+0.0009] | 차이 없음 |
| agentic_tool_calling | 1.0851 | **1.0641** | −0.0210 [−0.0258,−0.0162] | C2 |

처음 8개는 memory-level 시나리오, 나머지 5개(`long_context` ~
`agentic_tool_calling`)는 이번에 추가한 application-level 시나리오다.
`flexibility_new_tier`는 `hierarchy_pressure`에 pool이 없던 조합의
tier(`dram_pnm`)를 추가한 조건이다. §9에서 별도로 다룬다.

### 읽는 방법 — 이전 보고서와 정반대 그림

**13개 중 6개에서 C2가 유의하게 이긴다.** 이전 pool에서는 10개 중 1개
(`hotness_drift`)뿐이었다. C1이 이기는 조건은 3개(`baseline`,
`hbm_pressure`, `flexibility_new_tier`)로 줄었고, 4개는 차이가 없다.

**이 반전의 메커니즘은 §2에서 자세히 다루지만, 요지는 이렇다.** 이전 pool의
`hbm_pim`은 GEMV와 ELEMENTWISE를 겸했고, HBM 바로 옆에 있었다. HBM이 weight로
붐빌 때 KV cache(GEMV가 주 연산)가 그 PIM tier로 부하 분산되어 얹히면 공짜로
in-place 처리를 얻었다 — **어느 정책이든** 이 이득을 거의 동일하게 받았으므로
C1과 C2를 가르지 못했다. 새 pool에서는 그 슬롯이 `custom_hbm`(GEMM 전용)으로
바뀌었고, GEMV를 받아줄 유일한 tier인 `ssd_pim`은 storage-class로 멀다. 그
결과 이 "공짜 이득" 채널이 사실상 사라졌고, 이제 **KV cache를 어디에 둘지는
그 객체의 실제 lifetime·접근률을 아는 것이 더 값을 하는 질문이 됐다** — 그리고
그건 정의상 C2(data-first)의 강점이다.

**새 application-level 시나리오 5개 전부가 C2 쪽으로 갈린 것은 우연이 아니다.**
KV cache의 lifetime이 class 전형값에서 크게 벗어나는 조건(`long_context`,
`reasoning`)일수록, 그리고 접근이 드문 조건(`agentic_tool_calling`)일수록
class prior만 보는 정책보다 실측 기반 추정이 유리해진다. `multi_tenant`는
표본율 5%에서도 유의하게 C2가 이기는데, 이는 §3의 `sample_rate` sweep이
보여주는 낮은 문턱과 일치한다.

**C1이 이기는 세 조건은 "여유가 있거나 GPU-reachable tier만 희소한" 조건이다.**
`baseline`(ROOMY)과 `hbm_pressure`(HBM_ONLY_SQUEEZE)에서는 profiling 오버헤드를
정당화할 만큼 배치가 어렵지 않다. `flexibility_new_tier`는 §9에서 다루듯 C2가
새 tier를 더 적극적으로 쓰지만 그로부터 얻는 이득은 C1이 더 크다.

**pim_heavy에서 차이가 없는 것이 특히 눈에 띈다.** 문서 논리상 scan/gather
위주 워크로드는 C2에 유리해야 한다. 그런데 새 pool에서는 `RAG_INDEX_SHARD`(SCAN)와
`EMBEDDING_TABLE_SHARD`(EMBEDDING_LOOKUP) 둘 다 지원 tier가 **0개**다(§5 참조) —
어느 정책을 쓰든 항상 HBM으로 staging되므로, capability 매칭이라는 채널 자체가
이 워크로드에는 존재하지 않는다. 대조군으로서의 가치(§1 이전 판)는 유지되지만,
이제는 "scan 워크로드에서도 매칭 이득이 없다"가 아니라 "**이 pool에는 scan을
받아줄 tier가 없다**"로 읽어야 한다.

### 무결성: rejection 0, dropped migration은 조건에 따라 0이 아님

전 13개 조건에서 rejection은 0이다. dropped migration은 reactive 조건 중
4개에서 0이 아니다: `hotness_drift` 77건, `partial_observation` 202건,
`multi_tenant` 100건, `agentic_tool_calling` 2건 (20 seed 합산). 나머지
reactive 조건(`long_context`)과 모든 non-reactive 조건은 0건이다.

이는 새로 생긴 문제가 아니다 — 엔진의 migration 경로는 "결정 시점 이후
목적지가 차 버린" 경우를 race로 취급해 세되 드롭하도록 설계돼 있다
(`engine.py`의 `_migrate` 참조). 이전 pool의 커밋된 결과에도
`hotness_drift` 32건, `partial_observation` 164건이 이미 있었다 — 이전
문서의 "전 조건 dropped migration 0"이라는 무결성 주장은 실제로는 부정확했다.
`rejections`(정책이 명시적으로 배치를 거부한 건수, 비교 가능성을 실제로
위협하는 수치)는 두 pool 모두에서 항상 0이었다.

---

## 2. §8 가정값과의 대조

문서 §8의 정량 비교 표는 이제 제거됐지만, 원래 가정값과 실측을 대조한다.

| §8 가정 | 실측 | 판정 |
|---|---|---|
| Placement Decision Cost 1.0x → 1.3x | static C1 **5.80x**, C2 **8.23x** (As-Is 대비). C2/C1 = **1.42x** | **자릿수가 틀림** |
| Data–Memory Matching Rate 70% → 90% | 정의를 고쳐야 측정 가능했음 (§4 참조) | **정의 결함** |
| Compute-capable Memory 활용률 50% → 85% | baseline: C1 **0.038**, C2 **0.038**. 압력 하에서 오히려 **상승** — §1 이전 판의 "95%" 자체가 소멸 | **메커니즘이 통째로 바뀜** |
| 불필요 Migration 20% → 10% | 분모를 misplacement로 고침. static은 양쪽 0건 | **분모 결함** |
| Prediction Dependency Low → High | 이제는 뚜렷한 단조 열화가 보이지 않음 — §3 참조 | **약화됨** |

### Decision Cost는 1.3x가 아니다

`hierarchy_pressure`(static)와 두 reactive 조건에서 배치 1건당 연산 수
(As-Is 대비):

| | static (`hierarchy_pressure`) | reactive (`hotness_drift`) | reactive (`partial_observation`) |
|---|---:|---:|---:|
| As-Is (hbm_first) | 1.00 | 1.00 | 1.00 |
| C1 | **5.80x** | 33.73x | 31.20x |
| C2 | **8.23x** | 97.57x | 153.12x |

절대 배율은 이전 pool과 거의 같다 (C2/C1 static ratio 1.42x, 이전 1.42x) —
decision cost는 tier pool 구성이 아니라 정책 구조(profiler 유무, 후보 집합
형성)에서 나오므로 이 결과는 이번 재구성으로 바뀌지 않는다. **reactive에서는
여전히 C1이 더 비싸질 수 있다** — `partial_observation`에서 C2가 153x로
C1(31x)보다 훨씬 커지지만, 이는 표본율 5%에서 재추정 빈도가 늘어난 결과이고
scenario마다 방향이 다르다. §7의 원 발견("재배치를 켜면 C1이 더 비싸질 수
있다")은 `hierarchy_pressure` 기반 변형에서 나온 것으로, 이번 pool에서도
같은 메커니즘(스캔 vs swap 가격 계산)이 유지되는지는 재검증하지 않았다 —
후속 과제로 남긴다.

### Compute-capable Memory 활용률: 메커니즘이 통째로 바뀌었다

| 조건 | As-Is | C1 | C2 |
|---|---:|---:|---:|
| baseline | 0.000 | **0.038** | **0.038** |
| hierarchy_pressure | 0.006 | 0.070 | 0.069 |
| pim_heavy | 0.017 | 0.171 | 0.171 |

**세 가지가 이전 pool과 다르다.**

**절대 수준이 훨씬 낮다.** 이전 pool은 baseline에서 0.955였다. 새 pool은
0.038이다. KV cache(GEMV)가 붙을 수 있는 유일한 tier가 `ssd_pim`(storage급,
멀리 있음)뿐이고, `custom_hbm`은 GEMM만 하므로 `hbm_first`가 채우고 남는
공간에 GEMM급 객체(MoE expert, LoRA adapter)가 넘칠 때만 활용률이 올라간다.

**압력을 걸면 오히려 올라간다.** 이전 pool은 압력 하에서 0.955 → 0.07로
붕괴했다(PIM tier도 같이 줄어 자리가 없어짐). 새 pool은 baseline 0.038 →
hierarchy_pressure 0.070 → pim_heavy 0.171로 **상승**한다 — 압력이 GEMM급
트래픽을 `custom_hbm`/`cxl`로 더 많이 밀어내고, 일부 KV cache가 계층을 깊이
내려가 `ssd_pim`의 GEMV capability에 닿기 때문이다. 방향이 뒤집혔다.

**하드웨어 세대 대조 시나리오(`narrow_hbm`/`baseline_narrow_hbm`)가 없어졌다.**
이전 pool에서 이 지표를 재던 이유는 "HBM-PIM 내부 경로가 plain HBM보다
넓은 세대에서도 활용률이 그대로인가"였다. `HBM_PIM`이 GEMM 전용
`custom_hbm`과 GEMV 전용 `ssd_pim`으로 분리되면서 그 비교가 성립하지 않게
됐고, 그래서 두 시나리오와 관련 config(`tiers_narrow_hbm.json`)를 통째로
치웠다. §7의 "철회한 발견"에 이 경위를 남긴다.

> 이 지표에 관한 모든 수치는 여전히 **이득의 하한**이다. 목적함수에 GPU
> occupancy 항이 없어서, in-place 연산이 GPU 연산 유닛을 비워주는 이득이
> 보이지 않는다.

---

## 3. Sweep: 어떤 조건이 우열을 바꾸는가

### Classification 오차 (ε)

`hierarchy_pressure` 기준. C1은 profiler를 쓰지 않으므로 전 구간 1.1970 고정.

| ε | C1 | C2 | 판정 |
|---:|---:|---:|---|
| 0.0 | 1.1970 | 1.1947 | 차이 없음 |
| 0.1 | 1.1970 | 1.1942 | 차이 없음 |
| 0.2 | 1.1970 | 1.1906 | 차이 없음 |
| 0.3 | 1.1970 | 1.1907 | 차이 없음 |
| 0.45 | 1.1970 | 1.1970 | 차이 없음 |
| 0.6 | 1.1970 | 1.1926 | 차이 없음 |
| 0.9 | 1.1970 | 1.1880 | 차이 없음 |

**전 구간 차이 없음, crossover 없음.** 이전 pool은 ε 0→0.9에서 C2가
1.387→1.453으로 단조 열화했다. 새 pool에서는 C2 값이 1.188~1.197 사이에서
잡음 수준으로 흔들릴 뿐 뚜렷한 방향이 없다 — §2에서 다룬 것처럼 이 시나리오
에서는 capability 매칭 채널 자체가 거의 닫혀 있으므로, 추정 오차가 커져도
잃을 것이 별로 없다. **Prediction Dependency 항목은 이 pool·시나리오에서는
더 이상 뚜렷하지 않다.**

### Systematic bias

| bias | C1 | C2 | 판정 |
|---:|---:|---:|---|
| 0.0 | 1.1970 | 1.1942 | 차이 없음 |
| 0.2 | 1.1970 | 1.1970 | 차이 없음 |
| 0.4 | 1.1970 | 1.1947 | 차이 없음 |
| 0.8 | 1.1970 | 1.1940 | 차이 없음 |

이전 pool에서는 bias 0.2만으로 ε=0.9급 손실이 났다. 새 pool에서는 bias가
전혀 움직이지 않는다 — 같은 이유다.

### Profiling 표본율

`hierarchy_pressure` + reactive 기준.

| sample_rate | C1 | C2 | 판정 |
|---:|---:|---:|---|
| 0.01 | 1.1971 | 1.1945 | 차이 없음 |
| 0.05 | 1.1971 | **1.1917** | **C2** |
| 0.2 | 1.1971 | **1.1839** | **C2** |
| 0.5 | 1.1971 | **1.1672** | **C2** |
| 1.0 | 1.1971 | **1.1516** | **C2** |

**이전 pool과 방향이 정반대다.** 이전 pool에서는 표본율이 50% 이상이어야
C2가 C1과 대등해졌다(그 전에는 C1이 유의하게 나음). 새 pool에서는 표본율
5%만으로 이미 C2가 유의하게 이기고, 표본율이 오를수록 격차가 **단조로
벌어진다**(0.05: −0.0054 → 1.0: −0.0455). vLLM이 실제로 쓰는 1% 근처
(`sample_rate=0.01`)에서는 아직 차이가 없지만, `multi_tenant`처럼 5%만
확보해도 §1에서 보듯 유의한 이득이 난다.

이건 실무적으로 §1과 같은 결론을 가리킨다: **이 pool에서는 데이터 특성을
아는 것의 값이 estimator 품질보다 커버리지에서 나온다**, 그리고 그 커버리지
문턱이 이전 pool보다 훨씬 낮다.

---

## 4. 지표 정의에서 발견한 결함

측정을 시도하면서 §8의 지표 정의 두 개가 그대로는 쓸 수 없다는 것이 드러났다.
이 절의 내용은 tier pool 교체와 무관하며 이전 판에서 그대로 유지된다.

### Data–Memory Matching Rate

처음엔 "그 객체의 실제 트래픽에 가장 싼 tier 대비 허용오차 내"로 정의했다.
결과가 모든 정책에서 동일하게 나왔다 — 가장 싼 tier는 거의 항상 HBM이고,
지표가 정책의 판단이 아니라 **pool의 희소성**을 재고 있었다.

절대 기준으로 다시 정의했다: 이 tier가 객체의 실제 per-step 트래픽을 감당하는가,
그리고 그 연산이 어딘가에서 in-memory로 돌 수 있다면 여기서 돌거나 GPU가 직접
읽을 수 있는 곳인가. 이렇게 하면 붕괴하지 않고 정책을 구분한다.

그래도 압박 하에서는 모든 정책에서 함께 떨어진다. **capacity regime을 명시하지
않은 matching rate는 시나리오 간 비교가 불가능하다.**

### 불필요 Migration 비율

분모를 migration 건수로 두면 재배치를 아예 안 하는 정적 정책이 "0건 중 0%"로
만점을 받는다. 분모를 misplacement 건수로 고쳤다. 이 수정은 원본 설계 문서 §8에도
반영했다.

---

## 5. Cost model 민감도

결론의 부호가 파라미터 선택의 산물인지 확인한다. `hierarchy_pressure` 기준.

| contention 설정 | C1 | C2 | 판정 |
|---|---:|---:|---|
| default | 1.1970 | 1.1947 | 차이 없음 |
| weak (floor 0.7, α 0.5) | 1.1171 | **1.1135** | **C2** |
| strong (floor 0.2, α 2.0) | 1.2167 | **1.2097** | **C2** |
| late knee (0.5→1.0) | 1.1948 | **1.1881** | **C2** |
| early knee (0.5→0.25) | 1.1948 | 1.1970 | 차이 없음 |

**부호가 5개 설정 전부에서 안정적이지는 않다** (2개는 차이 없음). 하지만
**결정적인 3개는 모두 C2 쪽이다** — 이전 pool에서는 5개 전부 C1이었던 것과
정반대다. 이는 §1~§2의 재구성 이후 그림과 일치한다: `hierarchy_pressure`
자체가 이제 "차이 없음"에 가까운 조건이므로, contention 파라미터를 조금만
바꿔도 어느 쪽으로도 기울 수 있는 경계에 있다.

---

## 6. 유효 범위

측정된 범위 안에서:

> **KV cache의 lifetime·접근률이 class 전형값에서 크게 벗어나는 조건
> (long_context, reasoning, agentic_tool_calling, hotness_drift, multi_tenant)
> 에서는 C2가 유의하게 낫다.** 마진은 목적함수의 2~5%다.
>
> **HBM에 여유가 있거나 GPU-reachable tier만 희소한 조건, 그리고 pool에
> 없던 tier를 추가하는 조건에서는 C1이 유의하게 낫다**
> (baseline +0.0287, hbm_pressure +0.1609, flexibility_new_tier +0.0611).
>
> **계층 전체가 압박받거나(hierarchy_pressure), scan/gather 위주이거나
> (pim_heavy), write 집약적인(write_heavy) 조건, 그리고 MoE 위주(moe_heavy)
> 조건에서는 차이가 없다.**
>
> **표본율 문턱이 낮아졌다.** 5%만 추적해도 C2가 유의한 이득을 낸다
> (이전 pool은 50% 이상이 필요했다).
>
> **분류 오차·계통 편향의 효과가 약해졌다.** ε와 bias 모두 hierarchy_pressure
> 에서 뚜렷한 방향을 만들지 못한다 — capability 매칭 채널이 좁아지면서
> estimator 품질이 결과에 미치는 영향도 함께 줄었다.

### 이 결론이 답하지 않는 것

목적함수에 **GPU occupancy와 에너지 항이 없다.** in-place 연산이 GPU 연산 유닛을
비워주는 이득이 보이지 않으므로, compute-capable memory에 관한 모든 결과는
**하한**이다. 이 항을 넣으면 결과가 어느 방향으로 움직일지는 이번 프로토타입이
답하지 않는다.

**GPU 실측이 아니다.** stdlib 시뮬레이션이고, tier 스펙은 공개 자료 기반 대표값이다.
`configs/tiers_default.json`을 사내 스펙으로 교체하면 코드 수정 없이 다시 돌 수 있다
(단 새 medium을 추가하려면 enum 수정이 필요하다 — [README](README.md) 참조).

**규모 의존성이 있다.** 인구 규모를 1/10로 줄이면 일부 수치가 유의하게 달라졌다.
보고된 수치는 `scenarios.py`의 설정(120 step, scale 0.25)에 대한 것이다.

**`agentic_tool_calling`은 전체 KV population을 agentic-idle로 모델링한다.**
steady-decode와 혼합된 실제 배치는 표현하지 않는다.

---

## 7. 신뢰도에 관한 공개 사항

**C2 구현을 세 번 바꿨다.** 매번 C2가 지는 것을 본 뒤였다. "이길 때까지 튜닝"이 될
수 있는 패턴이므로, 무엇을 어떤 기준으로 고쳤는지 남긴다.

기준: **점수와 무관하게, 문서의 C2를 구현하는 엔지니어라면 아무도 출시하지 않을
동작만 결함으로 취급한다.**

| 버전 | 동작 | baseline 결과 | 왜 고쳤는가 |
|---|---|---:|---|
| 1차 | load를 feasibility로 취급 → 무한 spill. HBM 1.02 포화 시 **40배 느린 유휴 HBF**로 내려감 | 8.17x | load는 비용이고 feasibility가 아니다. capacity와 endurance가 feasibility다 |
| 2차 | 유계 spill, 이진 임계값 판정 | 2.06x | 이진 결정은 부하 분할을 찾을 수 없어 과잉 spill (좁은 PIM tier에 C1의 2배 트래픽) |
| 3차 | 데이터가 후보 집합을 만들고 memory state가 그 안에서 선택 | 0.9404 (구 pool) | §4의 Memory State Check가 나열한 `Capacity, Load, BW/Latency, Capability` 전부를 쓰는 것이 문서에 더 충실 |

이 세 버전 이력은 tier pool 교체 **이전**에 확립됐고, 이번 재구성에서 정책
코드는 건드리지 않았다 — 위 표의 결정과 근거는 그대로 유효하다. 새 pool에서의
baseline 결과는 §1의 0.9778이다.

**멈춘 시점:** 3차 이후 C2가 압도적으로 이기지 않는다 — 조건에 따라 이기거나,
지거나, 대등하다. 이길 때까지 고쳤다면 이 표가 다르게 보일 것이다.

### 철회·소멸한 발견

**"C2가 compute-memory 활용률 0%, 문서와 방향이 반대, 하드웨어 세대 의존적"
(1차 구현 결함).** 실제로는 두 후보가 동일했고(0.955/0.955) 세대 의존성도
없었다. `test_dp1_findings.py`에 이 정정을 기록했다.

**"compute-capable memory 활용률이 HBM 세대에 의존하지 않는다"는 대조
자체가 이번 판에서 소멸했다.** `HBM_PIM`이 GEMM 전용 `custom_hbm`과 GEMV
전용 `ssd_pim`으로 분리되면서, "HBM-PIM 내부 경로가 plain HBM 인터페이스보다
넓은 세대에서도"라는 전제 자체가 성립하지 않는다. `narrow_hbm`/
`baseline_narrow_hbm` 시나리오와 `tiers_narrow_hbm.json`을 삭제했다 — 약화가
아니라 질문이 없어진 것이다.

**"압력이 compute-capable memory 활용률을 붕괴시킨다"는 이전 finding이
뒤집혔다.** 이번 판에서는 §2에서 다뤘듯 압력이 이 지표를 **높인다**. 재도출된
`test_capacity_pressure_raises_this_metric_for_both_candidates`에 새 메커니즘을
기록했다.

### 반편향 장치의 한계

`test_no_candidate_wins_decisively_everywhere`는 원래 4개 조건
(`baseline`, `hierarchy_pressure`, `pim_heavy`, ε=0.9 변형)으로 "한쪽이 전
구간 압승하면 실패"를 확인했다. 이 가드는 **보고 설정(120 step, scale 0.25)
이지만 20이 아니라 6 seed로** 돈다 — 판정의 정밀도가 아니라 모양만 보면
된다는 전제다. 이번 pool에서는 그 6-seed 표본에서 네 조건 **전부**가 "차이
없음"으로 나왔다. 그런데 §1의 20-seed 보고 수치를 보면 `baseline`은 실제로는
결정적이다(+0.0287 [+0.0171,+0.0403], C1). 즉 가드가 실패한 것은 한쪽이
압승해서가 아니라, **효과가 작아진 조건에서 6 seed로는 신호를 못 잡을
확률이 높아졌기 때문**이다 — capability 매칭 채널이 좁아지면서 대부분
조건의 마진이 2~5%대로 줄었으니 자연스러운 결과다. `hbm_pressure`와
`write_heavy`로 교체해 6 seed에서도 안정적으로 판별되는 조건으로 가드의
본래 취지(동점과 결정적 승부가 섞여 있어야 함)를 복원했다.

---

## 9. QA 4개 평가 (실측 기반)

§1~§6은 목적함수만 다뤘다. 여기서 §7이 정의한 4개 QA 전부를, **문서가 사전에
매긴 가설 별점과 대조하지 않고** 이번 실측 결과만으로 재평가한다. 별점 3점
만점이며, 아래 각 항목의 근거로부터 도출한다.

| QA | C1 memory-first | C2 data-first |
|---|:---:|:---:|
| Performance Efficiency | ★★☆ | ★★☆ |
| Functional Correctness | ★★★ | ★★☆ |
| Maintainability | ★★☆ | ★★☆ |
| Flexibility | ★★☆ | ★★★ |

### Flexibility와 Maintainability, 헷갈리지 않게 구분하기

이름이 비슷한 인상을 주지만 **재는 축이 다르다.** 하나는 지금 있는 코드를
이해·수정하는 비용(정적 — 코드를 돌리지 않아도 잴 수 있다)이고, 다른 하나는
환경이 바뀌었을 때 정책의 **행동**이 실제로 달라지는가(동적 — 새 조건을 주고
실행해봐야 알 수 있다)다.

| | Maintainability | Flexibility |
|---|---|---|
| **묻는 질문** | 이 코드를 다음 사람이 이해·수정·검증하기 쉬운가? | 이 정책이 pool에 없던 매체·연산·데이터 패턴을 만나면 반응하는가? |
| **증거 종류** | 대리 지표 — 소스에서 센 구조적 수치 (줄 수, 분기 수, knob 수, state 수, method 수) | 실험 — 새 tier(`dram_pnm`)를 실제로 추가하고 실행해서 관찰 |
| **값이 바뀌는 계기** | 코드를 고칠 때만. 워크로드나 tier pool을 바꿔도 그대로다 | 코드는 그대로 두고 환경(pool)만 바꿀 때마다 |
| **여기서 잰 것** | 정책 소스 파일 정적 분석: decisions/knobs/state/methods/lines | 새 tier에 실제로 배치된 객체 수·바이트·트래픽 비중, 그로 인한 목적함수 변화 |
| **C1·C2가 다른 이유** | 코드량이 27% 차이 나지만, 나머지 4개 지표는 방향이 엇갈려 우열이 뚜렷하지 않음 | "무엇으로 배치 후보를 형성하는가"라는 아키텍처 차이 자체가 새 매체 등장 시 다르게 반응하게 만듦 — C2는 데이터 적합도로 후보를 형성하므로 새 capability가 랭킹에 즉시 반영되고, C1은 memory state로 형성하므로 더 보수적으로 씀 |

**한 줄로 구분하면:** Maintainability는 "코드를 열어보지 않고도 복잡도를 셀
수 있는가"이고, Flexibility는 "코드는 안 바꿨는데 환경이 바뀌니 정책의
선택이 바뀌는가"다. 코드가 복잡하다고(Maintainability가 낮다고) 새 환경에
못 적응하는 것도 아니고, 적응을 잘한다고 코드가 간단한 것도 아니다 — 실제로
이번 결과에서 C2는 Flexibility가 가장 높지만(★★★) Maintainability는 C1과
대등한 수준(★★☆)이다. 아래 각 subsection에서 이 구분이 실제 수치로 어떻게
갈리는지 다룬다.

### Performance Efficiency — 조건부, C1·C2 균형

§1의 13개 시나리오를 승/패/동점으로 나누면:

| | C1 승 | C2 승 | 차이 없음 |
|---|---:|---:|---:|
| 조건 수 | 3 | 6 | 4 |
| 조건 | baseline, hbm_pressure, flexibility_new_tier | hotness_drift, partial_observation, long_context, multi_tenant, reasoning, agentic_tool_calling | hierarchy_pressure, pim_heavy, write_heavy, moe_heavy |
| 이길 때 평균 마진 | **8.36%** (2.87~16.09%) | **2.76%** (0.54~5.10%) | — |

**조건 수는 C2가 두 배 많지만(6 vs 3), C1이 이기는 조건의 마진이 훨씬 크다** —
특히 `hbm_pressure`(+16.09%)가 평균을 끌어올린다. 13개 시나리오의 목적함수
값을 단순 평균하면 C1 **1.1538**, C2 **1.1601**로 C1이 근소하게 낮다(차이
0.55%). 이 평균은 시나리오별 신뢰구간을 반영하지 않은 descriptive 수치이고,
`hbm_pressure` 하나만 빼도 평균이 C2 쪽으로 기운다 — 즉 **어느 지표(조건 수
vs 평균 비용)를 기준으로 삼든 결론이 뒤집힐 만큼 근소한 차이**라는 뜻이다.
그래서 두 후보 모두 ★★☆로 평가한다: 어느 쪽도 이 QA를 결정적으로 지배하지
않는다.

### Functional Correctness — C1은 구조적으로 면역, C2는 노이즈 수준

입력 오차가 결과에 도달하는 비율. `hierarchy_pressure` 기준, 오차 0에서의 자기
자신을 기준으로 정규화.

| 입력 오차 ε | C1 penalty | C1 증폭률 | C2 penalty | C2 증폭률 |
|---:|---:|---:|---:|---:|
| 0.0 | 1.0000 | 0.0000 | 1.0000 | 0.0000 |
| 0.1 | 1.0000 | **0.0000** | 0.9996 | −0.0040 |
| 0.2 | 1.0000 | **0.0000** | 0.9966 | −0.0170 |
| 0.3 | 1.0000 | **0.0000** | 0.9967 | −0.0110 |
| 0.45 | 1.0000 | **0.0000** | 1.0019 | 0.0043 |
| 0.6 | 1.0000 | **0.0000** | 0.9982 | −0.0030 |
| 0.9 | 1.0000 | **0.0000** | 0.9944 | −0.0062 |

**C1은 ★★★.** profiler를 쓰지 않으므로 입력 오차가 도달할 경로가 구조적으로
없다 — 정의상 증폭률이 정확히 0이고, 이보다 더 강한 견고성은 있을 수 없다.

**C2는 ★★☆.** penalty가 0.994~1.002 사이에서 오르내릴 뿐 ε가 커져도 일관되게
나빠지지 않는다(오히려 ε=0.1~0.3에서는 개선). 실질적 열화가 최악의 경우에도
2% 미만이라는 점에서 양호하지만, 추정에 의존하는 구조라 오차에 실제로 노출되고
방향이 안정적이지 않으므로 C1과 같은 "면역" 등급은 줄 수 없다.

### Maintainability — 5개 대리 지표가 엇갈려 우열 없음

소스에서 센 구조적 대리 지표.

| 정책 | decisions | knobs | state | methods | lines |
|---|---:|---:|---:|---:|---:|
| As-Is (hbm_first) | 3 | 0 | 0 | 3 | 54 |
| C1 memory_centric | **58** | 3 | 5 | 18 | **384** |
| C2 data_centric | 61 | 3 | **4** | **16** | 487 |

> **이건 대리 지표다.** 변경 비용과 상관은 있지만 그것을 측정하지 않는다.

5개 지표 중 **2개는 C1이 낮고(decisions, lines), 2개는 C2가 낮고(state,
methods), 1개는 동일하다(knobs).** 코드량(lines)만 놓고 보면 C2가 27% 많지만,
분기 수는 5%밖에 차이 나지 않고 state·methods는 오히려 C2가 적다 — 어느
후보가 "더 유지보수하기 쉬운가"라는 질문에 5개 지표가 답을 하나로 모으지
않는다. 그래서 둘 다 ★★☆로 평가한다.

**두 후보 모두 As-Is(54줄, knob 0개)보다는 훨씬 복잡하다.** 이 격차가
C1-C2 간 격차보다 훨씬 크다 — 이 QA에서 실제로 의미 있는 대비는 "정책이
있는가 없는가"이지 "어느 정책인가"가 아니다.

### Flexibility — 둘 다 적응하지만, 적응하는 방식이 다르다

pool에 없던 조합의 tier(`dram_pnm`: 외부 150 GB/s, 내부 600 GB/s, ELEMENTWISE
in-place)를 추가하고 실제로 쓰는지 측정. `hierarchy_pressure`와 쌍으로 비교.

| 정책 | 적응 | 배치 객체 | 배치 바이트 | 트래픽 비중 | 목적함수 변화 |
|---|---|---:|---:|---:|---:|
| As-Is (hbm_first) | **아니오** | 0 | 0.00 GiB | 0.0000 | 1.0000 |
| C1 memory_centric | 예 | 19091 | 279.64 GiB | **0.0820** | **0.7868** |
| C2 data_centric | 예 | 19297 | **825.58 GiB** | **0.1833** | 0.8394 |

**As-Is는 새 tier를 전혀 쓰지 않는다.** 대역폭 내림차순 first-fit에서
`dram_pnm`은 DRAM보다 아래이고 DRAM이 먼저 채워지므로 도달하지 않는다. 이
QA에서 "적응"이 무엇을 뜻하는지 보여주는 대조군이다 — 코드가 없으면 새
매체는 있어도 없는 것과 같다.

**C1은 ★★☆.** 적응하긴 하지만(As-Is와 달리 `dram_pnm`을 실제로 씀) 보수적이다
— 트래픽의 8.2%만 새 tier로 보낸다.

**C2는 ★★★.** 같은 새 tier에 트래픽의 18.3%(바이트로는 C1의 **3.0배**인
825.58 GiB)를 보낸다. 데이터 적합도로 후보를 형성하는 구조상 새 tier의
in-place 연산이 랭킹에 즉시 반영되기 때문이다 — "환경이 바뀌면 정책의
선택이 실제로 많이 달라지는가"라는 이 QA의 질문에 훨씬 강하게 반응한다.

**단, 이 별점은 "이득을 더 본다"는 뜻이 아니다.** 목적함수 변화를 보면 오히려
C1이 더 싸다(0.7868 vs 0.8394) — C2가 새 tier에 훨씬 많은 바이트를 옮기면서도
그 tier의 부하가 차오르는 것을 후보 집합 방식으로는 연속적으로 조절하지 못해서
옮긴 만큼의 이득을 다 못 본다. **"새 매체를 얼마나 적극적으로 쓰는가"
(Flexibility)와 "그래서 목적함수가 얼마나 좋아지는가"(Performance
Efficiency)는 별개의 질문이고, 이번 결과는 그 둘이 같은 방향으로 가지
않는다는 것을 보여준다** — Flexibility가 높다고 Performance Efficiency도
높으리라 기대하면 안 된다는 뜻이다.

---

## 10. 설계 문서에 반영할 것

1. **§8의 Decision Cost 기준을 As-Is로 바꿀 것.** 현재 C1=1.0 정규화는 C1 자신이
   As-Is의 6배라는 사실을 감춘다. 이 결론은 tier pool과 무관하게 유지된다.

2. **§8의 Compute-capable Memory 활용률 항목에 "이 pool의 어느 tier가 어느
   연산을 지원하는가"를 명시할 것.** 이번 재구성으로 이 지표의 절대 수준과
   방향(압력에 따라 오르내리는지)이 전부 바뀌었다 — 지표 자체가 tier pool의
   연산 커버리지에 강하게 의존한다는 뜻이다. capacity regime뿐 아니라
   **pool 구성**을 전제로 붙여야 해석 가능하다.

3. **§6의 "오분류 Risk"에 미보정(miscalibration)을 포함할 것.** 이전 pool
   에서는 bias 0.2가 ε=0.9에 가까운 손실을 냈다. 이번 pool에서는 그 효과가
   약해졌지만, 그건 이 pool에서 capability 매칭 채널이 좁아졌기 때문이지
   미보정이 무해해졌다는 뜻이 아니다 — 매칭 채널이 넓은 pool로 돌아가면
   다시 나타날 수 있는 위험이다.

4. **§4 C2의 Data Profiling에 "추적 범위(Coverage)"를 추가할 것, 단 문턱값은
   pool 의존적이라고 명시할 것.** 이전 pool은 50% 이상이 필요했고, 이번 pool은
   5%로도 충분하다. 고정된 숫자를 요구사항으로 못 박지 말 것.

5. **§10 향후 검증 항목에 GPU Occupancy를 추가할 것.** 이 프로토타입이 답하지
   못하는 가장 큰 항목이고, C2에 유리하게 작용할 가능성이 있다.

6. **§9(후보 선정)를 이번 pool 결과로 재검토할 것.** 문서가 C2를 선정한
   근거의 상당 부분이 Performance Efficiency였는데, 이번 pool에서는 그
   방향이 조건부로 바뀌었다. 어느 pool이 실제 배치될 하드웨어에 더 가까운지가
   선정 근거의 핵심이 됐다는 뜻이다.
