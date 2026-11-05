# DP별 QA 확정 상태와 QA3 핵심 자원 정리

> 작성: 2026-10-09. 질문: "지금 논의 단계에서 DP별 QA가 아직 정해지지 않았지? DP2는 확신이 안 든다." 답: **그렇다. 확정도가 DP마다 다르고, DP2가 가장 불안정하다.** 이 문서는 현재 상태와 QA3의 핵심 자원을 DP별로 다시 따져 본 것이다.

## 1. DP별 QA 확정 상태

| DP | 선정 QA(문서 기준) | 확정도 | 불안정한 점 |
|---|---|---|---|
| **DP4** | Throughput, Latency(TTFT 중심), Modifiability, Scalability. Resource utilization·Functional correctness는 사유와 함께 제외 | **높음**(우선순위와 별점 소유자 확정 v5, 제외 사유 명시) | 정의가 문서에 따라 다름(TPOT 포함 여부). 구현 방식 비교(OSS 대 자체)가 설계 질문인지 미결(경계 논의) |
| **DP1** | Throughput, Latency(TTFT, TPOT), Resource utilization, Modifiability | **중간**(PPT와 설계 문서에 명시. 단 QA3 정의가 결과를 본 뒤 여러 번 바뀜) | 이동 가능 범위 가정 오류로 평가 무효 가능, 추가 후보 QA 미채택 |
| **DP3** | Latency, Functional correctness(Accuracy F1), Resource utilization(PPT에서 물음표). 설계 문서 A는 Goodput을 주 지표로 둠 | **중간 이하**(프레임 B로 확정되며 QA 목록이 PPT와 A 문서 사이에서 어긋남, Modifiability 없음) | 프레임 B 기준의 QA 목록 재확인 필요, 평가 문서 없음 |
| **DP2** | Throughput, TTFT, TPOT, Resource utilization, Modifiability, **Scalability(DP2 전용 신규)** | **낮음**(평가 문서 자체가 "소유자 결정 O1~O11 미확정, 별 경계·선택 규칙은 제안 상태") | 아래 §2 |

## 2. DP2의 QA가 불안정한 이유 (Claude 분석)

1. **DP4와의 경계가 미결**이다(`memo-dp2-dp4-boundary.md`). DP2가 "노드 안 자원 선택"인지 "노드와 자원 모두"인지에 따라 QA의 의미가 달라진다.
2. **종단 QA(Goodput, TTFT, TPOT)가 DP4와 같은 지표**라 DP2 고유의 판별력이 아니다. DP2의 후보(C1/C2)를 가르는 것은 결정 시점에 관한 속성(결정 지연, 결정 품질, planner 확장)이다.
3. **QA3(P/D 풀 사용률)는 DP2의 목표가 아니고 Throughput과 중복**이다(`memo-qa3-resource-utilization.md`).
4. **QA5 Scalability**는 DP2에만 있고 임계값이 제안값이며 결정 비용 가정(ASSUMED)에 의존한다.
5. 따라서 **DP2의 QA는 경계 논의가 끝나기 전에는 확정하지 않는 것**이 맞다고 본다. 지금은 `DP2-requirements.md`의 QA를 "제안(미확정)"으로 둔다.

**DP2의 QA를 정하는 순서(제안)**: ① 경계 결정(방식 ① 또는 ②) → ② DP2가 풀려는 병목 자원과 결정 변수 확정 → ③ 종단 QA(공유)와 DP2 고유 QA(결정 시점 속성)로 나눔 → ④ QA3는 병목 자원 기준으로 재정의.

## 3. QA3의 "핵심 자원"을 DP별로 다시 따져 보기

원칙: **DP가 존재하는 이유가 되는 병목 자원 하나**를 고르고, SLO 충족 조건에서 그 소모량을 Baseline과 비교한다. 성능과 섞지 않는다.

| DP | DP가 풀려는 병목 | 핵심 자원 후보 | 확신 | 비고 |
|---|---|---|---|---|
| DP1 | HBM pressure를 풀려는 데이터 이동 | **HBM 점유(용량)** | 높음 | 사용자 확인. 비싼 메모리를 덜 쓰는가 |
| DP3 | long-context KV의 HBM 용량, I/O, attention 비용 | **HBM KV footprint**(DP3 설계 A가 DP1과 같은 정의로 쓰라고 명시), 보조로 I/O bytes | 중간 | 프레임 B는 동기를 "용량·I/O·attention 비용이 TTFT를 키움"으로 적어, 용량 외에 I/O와 연산 비용도 자원이다 |
| DP2 | Prefill 포화(연산), History 전송(링크), D 노드 HBM 용량, Tier별 attention 대역폭 | **GPU 연산 시간**(GPU-time per output token 또는 필요 노드 수) / **링크 이동 bytes** / **D 노드 HBM 용량** 중 무엇인지 **미결** | **낮음** | 시나리오마다 병목이 다르다(Prefill burst는 연산, 링크 경합은 링크, 긴 context는 HBM). 경계 결정 후 정함. 방식 ①(노드 안)이면 HBM 대역폭(attention 오프로드로 해소)이 후보 |
| DP4 | 캐시를 보유하지 않은 서버로 가는 라우팅 → 중복 Prefill, 서버 간 부하 불균형 | **중복 Prefill 토큰 수**(캐시 miss로 다시 계산한 토큰 = 낭비된 GPU 연산), 보조로 서버 간 부하 CV | 중간 | 현 DP4 문서는 QA3를 제외(독립 판별력 없음). 이 지표는 라우팅 품질을 직접 반영한다. 별점이 아닌 진단으로 둘 수도 있음 |

**결론**
- **핵심 자원이 DP마다 달라도 정의의 형태("병목 자원의 소모량, SLO 충족 조건, Baseline 대비")는 같게** 할 수 있다. DP1의 HBM은 그대로 둔다.
- DP2는 병목이 시나리오별로 달라 **하나의 자원으로 고정하기 어렵다.** 선택지는 (a) 시나리오 대표 자원을 정하기, (b) DP2의 QA3를 진단으로 내리기, (c) 방식 ① 확정 후 HBM 대역폭 등으로 재정의하기다. (a)~(c)는 경계 결정 후 고른다.
- DP4는 현 입장(제외)을 유지하거나 "중복 Prefill 토큰 수"를 진단으로 두는 것이 가능하다.

## 4. 사용자 결정 기록 (2026-10-09)
- QA3를 "SLO 충족 조건에서 핵심 자원의 소모량"으로 통일하는 방향에 **동의**.
- DP3 정확도 한도 "F1 하락 1%"는 **상대 비율**.
- DP2의 QA는 **확신이 서지 않음**. 경계 논의(다른 세션)와 함께 결정.
