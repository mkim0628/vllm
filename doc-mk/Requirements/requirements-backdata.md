# 요구사항 백데이터 (제약, FR, ISO 25010 기반 QA 후보, 유틸리티 트리)

> 개정: 2026-10-09 (사용자 피드백 반영). 덱에는 핵심 항목만 올리고 이 문서는 그 뒤의 백데이터(추적용)이다.
> 문체: FR, 제약, 시나리오는 모두 "~이다 / ~한다" 평서형이다.
> 정량 값은 모두 공란 `[   ]`이다. 중요도·난이도는 Claude 제안이며 소유자 확정 전이다.

## 1. 제약사항

| 번호 | 제약 사항 | 설명 |
|---|---|---|
| C-01 | 차세대 메모리 | 차세대 메모리(HBF, ScHBM 등)의 device runtime/driver는 인터페이스를 가정하고 스펙에 따라 성능을 시뮬레이션한다. 내부 기능은 정상 동작하며 신뢰성은 보장된다고 가정한다 |
| C-02 | 시스템 확장 평가 | 실장 환경이 없는 규모 이상으로의 시스템 확장(노드 증가)은 시뮬레이션 기반으로 평가한다 |
| C-03 | 추론 엔진 | 추론 엔진은 오픈소스 서빙 프레임워크 vLLM 기반에서 구현한다 |
| C-04 | 대상 모델 | 대상 모델은 Transformer 기반 모델이다. 상태 기반 어텐션(state-based attention)은 제외한다 |
| C-05 | 대상 워크로드 | 대상 워크로드는 agent 워크로드이다 |

변경 이력:
- 서버 간 연결(C-03 구)은 삭제했다.
- "모델 출력 불변"(C-04 구)은 사용자 지시로 제약에서 뺐다. 정확도는 **QA6 Functional correctness**에서 다룬다. DP3의 Drop과 충돌하던 문제도 이로써 사라진다.
- 번호는 새로 매겼다. 이전 번호로 부르고 싶으면 알려 준다.

### 1.1 추가 후보 (사용자 판단 대기)
1. vLLM 변경 범위: upstream 수정 허용 여부와 대상 버전 고정.
2. 이동은 step 경계에서만 가능하다(참조 중인 블록은 step 중 이동 불가). C-03에 합치거나 별도 제약으로 둔다.
3. 개발 일정(기준 덱에는 있으나 우리 자료에는 없음).
4. 서버 간 링크 대역폭은 제약이 아니므로 **평가 환경 파라미터**로 남겨야 DP2·DP4의 전송 vs 재계산 판단이 근거를 갖는다.
5. 범위 밖(학습, 보안·테넌트 격리, 장애 복구, stale KV, 스케줄링이 초점)은 제약이 아니라 과제 범위 슬라이드에 둔다.
6. C-04의 "agent 워크로드"는 RAG, long-context, LoRA, MoE를 포함하는지 확인이 필요하다. 지금은 포함하는 것으로 두고 FR에 모두 둔다.

## 2. 기능 요구사항

기본 원칙: 시스템이 **무엇을 지원하는가**만 쓴다. 성능·정확도·DP 판단 내용은 FR에 넣지 않는다.

### 2.1 핵심 FR (덱, 10건)

| 번호 | 기능 요구사항 |
|---|---|
| FR-01 | 이기종 메모리(HBM, Host DRAM, CXL 메모리, HBF 등)를 지원한다 |
| FR-02 | 이기종 메모리 간 데이터 복사(이동)를 지원한다 |
| FR-03 | vLLM 추론 엔진 연동을 지원한다 |
| FR-04 | KV cache의 offload와 재사용을 지원한다 |
| FR-05 | LoRA adapter 서빙을 지원한다 |
| FR-06 | RAG 서빙을 지원한다 |
| FR-07 | MoE 모델 서빙을 지원한다 |
| FR-08 | Prefill/Decode disaggregation을 지원한다 |
| FR-09 | 연산 offload와 GPU fallback을 지원한다 |
| FR-10 | 서버 간 KV 전송을 지원한다 |

### 2.2 백데이터 FR (20건)

| 번호 | 기능 요구사항 | 상위 FR |
|---|---|---|
| FR-11 | Long-context(HBM 용량을 넘는 context) 요청 서빙을 지원한다 | FR-01, 04 |
| FR-12 | Multi-turn 세션의 KV 유지를 지원한다 | FR-04 |
| FR-13 | Prefix caching을 지원한다 | FR-04 |
| FR-14 | Tool 호출 대기 중인 agent 세션의 처리를 지원한다 | FR-04 |
| FR-15 | KV 압축을 지원한다 | FR-04 |
| FR-16 | KV 선택적 제거(eviction)를 지원한다 | FR-04 |
| FR-17 | KV 재계산을 지원한다 | FR-04 |
| FR-18 | 데이터 prefetch를 지원한다 | FR-02 |
| FR-19 | 다수 LoRA adapter의 동시 서빙을 지원한다 | FR-05 |
| FR-20 | MoE expert offload를 지원한다 | FR-07 |
| FR-21 | 연산 가능 메모리(PIM/PNM)에서의 연산 수행을 지원한다 | FR-09 |
| FR-22 | 다중 GPU 서빙을 지원한다 | FR-03 |
| FR-23 | 다중 서버 서빙을 지원한다 | FR-10 |
| FR-24 | 요청 라우팅(서버 선택)을 지원한다 | FR-23 |
| FR-25 | 서버별 KV 위치 조회를 지원한다 | FR-10, 24 |
| FR-26 | 메모리 장치 스펙(대역폭, 지연, 용량, 지원 연산) 입력을 지원한다 | FR-01 |
| FR-27 | 메모리 사용량과 접근 통계 수집을 지원한다 | FR-01 |
| FR-28 | 이동·배치 정책의 교체를 지원한다 | FR-02 |
| FR-29 | 스트리밍 응답을 지원한다 | FR-03 |
| FR-30 | 요청별 SLO와 우선순위 지정을 지원한다 | FR-03 |

참고:
- 이전 FR의 "출력 불변", "결정이 서빙을 막지 않음", "경합 제어", "관측 지표" 등은 QA(§3)로 옮겼다.
- FR-15~17은 DP3의 기능이다. "압축·제거·재계산을 지원한다"까지만 쓰고 허용 정확도나 중요도 기준은 FR에 쓰지 않는다.

## 3. 품질 속성 후보 (ISO/IEC 25010:2023 하위 특성 기준, 20건)

제품 품질 모델의 9개 특성 중 이 과제와 관련된 하위 특성을 모두 후보로 두었다. 에너지 효율, 수용 능력 같은 독자 항목은 쓰지 않는다. 관련 없는 특성은 맨 아래에 제외 사유와 함께 적었다.

| ID | 특성 > 하위 특성 | 이 과제에서의 의미 | 관련 DP | 상태 |
|---|---|---|---|---|
| QB-01 | Functional suitability > Functional completeness | 대상 객체(KV, adapter, expert, RAG 문서)와 모델 유형을 빠짐없이 지원 | 전체 | 후보 |
| QB-02 | Functional suitability > Functional correctness | 이동·복원 후 출력의 정확성(bit-exact), DP3는 F1 | 전체 | **선정 (QA6)** |
| QB-03 | Functional suitability > Functional appropriateness | 결정(이동·offload·라우팅)이 목적에 적합한 정도 | DP1, 2, 4 | 후보 |
| QB-04 | Performance efficiency > Time behaviour | TTFT, TPOT (처리 시간) | 전체 | **선정 (QA2)** |
| QB-05 | Performance efficiency > Resource utilization | HBM 점유율 | 전체 | **선정 (QA3)** |
| QB-06 | Performance efficiency > Capacity | SLO를 만족하는 최대 처리량(Max SLO Goodput), 최대 context·세션 수 | DP1, 2, 3, 4 | **선정 (QA1)** |
| QB-07 | Compatibility > Co-existence | 이동 트래픽이 서빙과 함께 동작 | DP1, 4 | 후보 |
| QB-08 | Compatibility > Interoperability | vLLM, llm-d, NIXL 등 외부 구성요소 연동 | DP4 | 후보 |
| QB-09 | Interaction capability > Operability | 운영자가 정책·메모리 설정을 쉽게 조작 | 전체 | 후보 (낮음) |
| QB-10 | Reliability > Availability | 서빙이 계속 가능한 정도 (런타임 계층에서는 열어 둠) | 전체 | 후보 |
| QB-11 | Reliability > Fault tolerance | 전송·offload 실패 시 서빙 지속(재계산 대체) | DP2, 4 | 후보 |
| QB-12 | Reliability > Recoverability | 장애 후 복구 (과제 범위 밖) | - | 제외 |
| QB-13 | Maintainability > Modularity | 모듈 간 영향 최소화 | 전체 | 후보 |
| QB-14 | Maintainability > Reusability | 모듈을 다른 DP·엔진에서 재사용 | 전체 | 후보 |
| QB-15 | Maintainability > Analysability | 결정 근거 기록과 원인 진단 | DP4, 전체 | 후보 |
| QB-16 | Maintainability > Modifiability | 새 tier·정책·객체 추가 용이성 | DP1, 2, 4 | **선정 (QA4)** |
| QB-17 | Maintainability > Testability | 정책을 시뮬레이터에서 단독 재현·검증 | 전체 | 후보 |
| QB-18 | Flexibility > Adaptability | 워크로드·입력 분포 변화에 대한 적응 | DP1 | 후보 |
| QB-19 | Flexibility > Scalability | 노드·메모리 type 증가에 따른 확장성 | DP2, 4 | **선정 (QA5)** |
| QB-20 | Flexibility > Replaceability | 구현 교체(OSS 대 자체 구현, 정책 교체) | DP4 | 후보 |

제외한 특성과 사유:
- Security 전 하위 특성: 보안·테넌트 격리는 범위 밖.
- Safety 전 하위 특성: 해당 없음.
- Interaction capability의 나머지(Learnability 등): 최종 사용자 UI가 없음.
- Installability: 지금은 중요하지 않음.
- Faultlessness: 구현 결함 문제이며 요구 수준 QA가 아님.

ISO 정의 확인 (정직하게 적는다):
- 25010의 Time behaviour는 "응답·처리 시간과 **throughput rate**가 요구를 충족하는 정도"이다. 따라서 Throughput을 Time behaviour로 볼 수도 있다. Capacity는 "제품 매개변수의 최대 한도"이다.
- 이 과제의 QA1은 "SLO 조건에서 지속 가능한 최대 처리량"이므로 **Capacity**로 두었다. TTFT·TPOT는 Time behaviour이다. 단순 throughput(tokens/s)만 재면 Time behaviour로 가야 한다. 이 구분을 소유자가 확인해 달라.

## 4. 선정 QA의 유틸리티 트리 (6요소, 정량 값 공란)

| QA (ISO 하위 특성) | Refinement | 시나리오 (출처 / 자극 / 환경 / 대상 / 응답 / 측정) | 중요도 | 난이도 | 순위(제안) |
|---|---|---|---|---|---|
| QA1 Capacity | Agent idle KV 이동 (DP1, 3) | 출처는 agent 클라이언트이다. 요청이 지속 도착한다. 환경은 tool 대기 KV가 HBM을 점유한 정상 운영이다. 대상은 이동 결정 스케줄러이다. 응답은 idle KV를 HBM 밖으로 옮겨 다른 요청을 처리하는 것이다. 측정은 SLO 충족 Max Goodput이 Baseline 대비 [   ] 이상이다 | H | M | 4 |
| QA1 Capacity | P/D 실행 위치 (DP2) | 출처는 서비스 클라이언트이다. Prefill burst와 긴 history가 섞여 도착한다. 환경은 P/D 자원이 분리 가능한 클러스터이다. 대상은 실행 위치 결정 모듈이다. 응답은 요청별 분리 여부와 (n_p, n_d) 결정이다. 측정은 SLO 충족 Max Goodput이 Baseline 대비 [   ] 이상이다 | M | H | |
| QA1 Capacity | 요청 배분 (DP4) | 출처는 클라이언트이다. 같은 prefix 요청이 도착한다. 환경은 KV 캐시가 서버별로 분산된 다중 서버이다. 대상은 orchestrator이다. 응답은 KV 위치를 보고 서버를 고르는 것이다. 측정은 SLO 충족 Max Goodput이 Baseline 대비 [   ] 이상이다 | M | M | |
| QA2 Time behaviour | TTFT 재개·재사용 | 출처는 같은 세션 또는 같은 문서 prefix 요청이다. 후속 요청이 도착한다. 환경은 KV가 HBM 밖 tier에 있고 부하가 고정된 상태이다. 대상은 prefetch·복원·탐색 모듈이다. 응답은 KV를 찾아 복원하고 재계산을 최소화하는 것이다. 측정은 TTFT(P50, P99)가 Baseline 대비 [   ] 이내이다 | H | M | 5 |
| QA2 Time behaviour | TPOT 다계층 attention | 출처는 서비스 클라이언트이다. decode가 진행된다. 환경은 KV 일부가 느린 tier에 있고 부하가 고정된 상태이다. 대상은 배치 결정과 tier 접근이다. 응답은 접근 빈도가 높은 KV를 빠른 tier에 두는 것이다. 측정은 TPOT(P50, P99)가 Baseline 대비 [   ] 이내이다 | H | H | 1 |
| QA3 Resource utilization | HBM 점유율 (전체 DP, 동일 조건) | 출처는 서비스 클라이언트이다. 동일 부하가 유입된다. 환경은 동일 workload·SLO·Baseline이다. 대상은 이동·Drop·배치 결정이다. 응답은 KV·adapter·expert를 HBM 밖에 두는 것이다. 측정은 HBM 점유율(평균, 피크)이 Baseline 대비 [   ] 이하이다 | H | M | 3 |
| QA4 Modifiability | 새 tier 추가 | 출처는 시스템 개발자이다. 새 메모리 tier(HBF, CXL 등) 추가를 요청한다. 환경은 개발 시점이다. 대상은 정책·배치 모듈이다. 응답은 인터페이스에 맞춰 tier를 추가하는 것이다. 측정은 변경 모듈 [   ] 개, 공수 [   ] man-month 이내이다 | H | M | |
| QA4 Modifiability | 새 정책·객체 추가 | 출처는 시스템 개발자이다. 새 이동·라우팅 정책 또는 객체 유형을 추가한다. 환경은 개발 시점이다. 대상은 정책 인터페이스이다. 응답은 서빙 경로 수정 없이 반영하는 것이다. 측정은 변경 모듈 [   ] 개, 공수 [   ] 이내이다 | M | L | |
| QA5 Scalability | 노드 수 증가 (DP2, 4) | 출처는 운영자이다. 노드 수를 N에서 2N, 4N으로 늘린다. 환경은 실장이 없는 규모를 포함한 시뮬레이션이다(C-02). 대상은 결정 모듈이다. 응답은 결정이 병목이 되지 않고 처리량이 늘어나는 것이다. 측정은 Scaling Efficiency가 [   ] 이상이다 | M | H | |
| QA5 Scalability | 메모리 type·tier 수 증가 (제안) | 출처는 운영자이다. 새 type의 메모리를 tier로 추가한다. 환경은 스펙 기반 시뮬레이션이다(C-01, C-02). 대상은 배치 결정 모듈이다. 응답은 추가 용량을 활용하며 결정 품질을 유지하는 것이다. 측정은 Capacity scaling efficiency가 [   ] 이상, 결정 지연 증가율이 [   ] 이내, optimality gap이 [   ] 이내이다 | M | M | |
| QA6 Functional correctness | 출력 bit-exact (DP1, 2, 4) | 출처는 클라이언트이다. 이동·복원·offload·재사용을 거친 요청이다. 환경은 같은 precision이다. 대상은 데이터 이동·복원 경로이다. 응답은 거치지 않은 경우와 같은 출력을 내는 것이다. 측정은 출력 불일치가 [   ] 건 이내이다 | H | L | |
| QA6 Functional correctness | Drop 후 정확도 (DP3) | 출처는 클라이언트이다. 중요도 기반 Drop·압축 재사용을 적용한다. 환경은 지정 task와 dataset(미정)이다. 대상은 Drop·재사용 정책이다. 응답은 정확도 한도 안에서 Drop하는 것이다. 측정은 압축 전 + full recompute 대비 F1 하락이 상대 [   ] 이내이다 | H | H | 2 |

QA2는 고정 부하에서 분포를 재고, QA1은 SLO를 고정해 최대 처리량을 재도록 나눠 순환 정의를 피한다.

## 5. 다음 단계
1. 소유자 확인: C-01~C-05 문장, §1.1 추가 후보, QA1의 ISO 매핑(Capacity 대 Time behaviour), 선정 QA의 중요도·난이도.
2. 덱 재작성: 요구사항 정제(첨부 형식, FR·제약 표 + Use-case diagram), 유틸리티 트리, 아키텍처 드라이버. PPT가 열리지 않는 문제는 이때 구조를 단순화해 다시 만든다.
