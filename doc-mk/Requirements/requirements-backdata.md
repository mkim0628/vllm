# 요구사항 백데이터 (FR 20건 추가, QA 후보 21건, 제약 확정안, 유틸리티 트리)

> 작성: 2026-10-09. 덱(요구사항 정제 슬라이드)에는 **핵심 FR/QA/C만** 올리고, 이 문서는 그 뒤에 있는 백데이터(Appendix, 추적용)이다.
> 정량 값(metric 목표)은 모두 공란이다. 중요도와 난이도는 Claude의 제안이며 소유자 확정 전이다.

## 1. 제약사항 (사용자 확정 2026-10-09)

| 번호 | 제약 사항 | 설명 | 이전 번호 |
|---|---|---|---|
| C-01 | 차세대 메모리 | 차세대 메모리(HBF, ScHBM 등)의 device runtime/driver는 **인터페이스를 가정**하고 스펙에 따라 성능을 시뮬레이션한다. 내부 기능은 정상 동작하고 신뢰성이 보장된다고 가정한다 | GC-1, 2, 3, 4, 5 |
| C-02 | 시스템 확장 평가 | 시스템 확장(메모리 type·tier·노드 증가)은 시뮬레이션 기반으로 평가한다 | GC-1 일부 |
| C-03 | 추론 엔진 | 추론 엔진은 오픈소스 서빙 프레임워크 **vLLM** 기반에서 구현한다 | GC-11 일부, DP1 설계 |
| C-04 | 출력 불변 | 모델 출력은 변하지 않아야 한다 | GC-7 |

번호 정리: 사용자가 "C03 서버 간 연결은 빼"라고 하여 삭제했고, 이후 C04(엔진)→C-03, C05(출력)→C-04로 당겨 적었다. 덱에서 번호가 다르면 다시 맞춘다. 필요하면 사용자가 말한 번호(C-01~C-05, C-03 결번)를 그대로 쓴다.

### 1.1 확인이 필요한 점 (Claude 의견)
1. **C-04와 DP3 충돌**: DP3는 중요도 기반 Drop으로 출력이 달라질 수 있어 "출력 불변"과 직접 충돌한다. DP3 허용 한도(F1 상대 1% 이내)를 예외로 문장에 넣을지, DP3의 정확도 QA로만 둘지 정해야 한다. 지금 문장대로면 DP3는 제약을 위반한다.
2. **C-03(서버 간 연결) 삭제의 영향**: DP4 "KV 전송 vs 재계산" 판단과 DP2 P/D 전송 비용에는 링크 대역폭 가정이 필요하다. 제약에서 빼면 **평가 환경 파라미터**(예: 64GB/s)로 내려야 한다. 어디에도 적지 않으면 DP2·4의 비용 모델이 근거를 잃는다.
3. **C-02 문구**: "시스템 확장"이 노드 수 증가인지 메모리 type 증가인지 둘 다인지 모호하다. QA5 Scalability가 둘 다 다루므로 "노드·메모리 type 증가"로 풀어 쓰기를 권한다.
4. **추가 후보 제약**(말씀하신 "더 있으면"):
   - 대상 모델·워크로드 범위(Transformer 기반 LLM, 평가에 쓰는 모델·데이터셋 목록).
   - vLLM 변경 범위(upstream 수정 허용 여부, 대상 버전 고정).
   - 이동은 step 경계에서만 가능(참조 중 블록 이동 불가). 이전 C8 내용이며 C-03에 합치거나 별도 제약으로 둔다.
   - 평가 하드웨어(GPU 종류, 실장 서버 수). 제약보다 평가 환경으로 둔다.
   - 개발 일정. 기준 덱에는 있었으나 우리 자료에는 아직 없다.
5. 범위 밖(학습, 보안·테넌트 격리, 장애 복구, stale KV, 스케줄링이 초점)은 제약이 아니라 **과제 범위** 슬라이드에 둔다.

## 2. 기능 요구사항

핵심 9건(덱에 표시, 사용자 승인)과 백데이터 20건이다. 백데이터는 핵심 FR의 세부 기능이며 "무엇을 할 수 있어야 하는가"만 쓴다.

### 2.1 핵심 FR (덱)

| 번호 | 기능 요구사항 |
|---|---|
| FR-01 | 이기종 메모리 계층(HBM, Host DRAM, CXL, HBF, 연산 가능 메모리)을 하나의 계층 구조로 인식하고 관리할 수 있어야 한다 |
| FR-02 | 이기종 메모리 간에 데이터를 복사하거나 이동할 수 있어야 한다 |
| FR-03 | 데이터를 어느 메모리에 둘지 정책에 따라 결정할 수 있어야 한다 |
| FR-04 | vLLM 같은 inference engine 위에서 동작하고 연동할 수 있어야 한다 |
| FR-05 | KV cache, LoRA adapter, MoE expert, RAG 문서 KV를 모두 다룰 수 있어야 한다 |
| FR-06 | 보관 중인 KV를 찾아 재사용하고, 제거된 부분은 재계산할 수 있어야 한다 |
| FR-07 | HBM 용량을 넘는 요청을 다른 메모리를 함께 써서 처리할 수 있어야 한다 |
| FR-08 | GPU, 연산 가능 메모리, Prefill/Decode 노드 중 연산을 수행할 위치를 정할 수 있어야 한다 |
| FR-09 | 여러 서버 중 요청을 처리할 서버를 정하고 서버 간 KV를 전달할 수 있어야 한다 |

### 2.2 백데이터 FR (20건)

| 번호 | 기능 요구사항 | 상위 FR | 관련 DP | 관련 UC |
|---|---|---|---|---|
| FR-10 | 데이터(KV, adapter, expert, 문서 KV)의 현재 위치(메모리 tier, 서버)를 조회할 수 있어야 한다 | FR-01, 03 | DP1, 4 | UC-1, 7 |
| FR-11 | 데이터별 접근 이력(빈도, 최근 접근 시각)을 수집할 수 있어야 한다 | FR-03 | DP1, 3 | UC-1, 3, 4, 5 |
| FR-12 | 메모리 tier별 용량과 사용량을 조회할 수 있어야 한다 | FR-01 | DP1, 2, 3 | UC-1, 2 |
| FR-13 | 메모리 장치의 스펙(대역폭, 지연, 용량, 지원 연산)을 입력으로 받을 수 있어야 한다 | FR-01 | DP1, 2 | UC-6 |
| FR-14 | 상위 메모리의 데이터를 하위 메모리로 내릴 수 있어야 한다 (evict) | FR-02, 03 | DP1 | UC-1 |
| FR-15 | 필요한 시점 전에 데이터를 상위 메모리로 미리 가져올 수 있어야 한다 (prefetch) | FR-02, 03 | DP1 | UC-1 |
| FR-16 | 같은 prefix를 가진 KV를 어느 tier에 있든 찾을 수 있어야 한다 | FR-06 | DP1, 3, 4 | UC-3 |
| FR-17 | 중요도가 낮은 KV를 선택적으로 제거할 수 있어야 한다 | FR-06 | DP3 | UC-2 |
| FR-18 | 압축한 KV를 재사용할 수 있어야 한다 | FR-06 | DP3 | UC-2 |
| FR-19 | 제거했거나 손실된 KV 중 필요한 부분만 선택적으로 재계산할 수 있어야 한다 | FR-06 | DP3 | UC-2 |
| FR-20 | LoRA adapter를 HBM에 적재하거나 해제할 수 있어야 한다 | FR-05 | DP1 | UC-4 |
| FR-21 | MoE expert의 배치 위치를 바꿀 수 있어야 한다 | FR-05 | DP1 | UC-5 |
| FR-22 | RAG 문서의 KV를 미리 계산해 보관할 수 있어야 한다 | FR-05, 06 | DP1 | UC-3 |
| FR-23 | Prefill과 Decode를 서로 다른 자원에서 분리 실행할 수 있어야 한다 | FR-08 | DP2 | UC-8 |
| FR-24 | Prefill에서 만든 KV를 Decode 쪽으로 전달할 수 있어야 한다 | FR-08, 09 | DP2 | UC-8 |
| FR-25 | 연산을 연산 가능 메모리(PIM/PNM)에 맡길 수 있어야 한다 | FR-08 | DP2 | UC-6 |
| FR-26 | 연산 가능 메모리가 지원하지 않는 연산을 GPU 경로로 수행할 수 있어야 한다 | FR-08 | DP2 | UC-6 |
| FR-27 | 서버별 KV 보유 정보를 다른 서버나 orchestrator가 알 수 있도록 공유할 수 있어야 한다 | FR-09 | DP4 | UC-7 |
| FR-28 | 서버 간에 KV를 전송할 수 있어야 한다 | FR-09 | DP2, 4 | UC-7, 8 |
| FR-29 | 이동·배치·라우팅 정책을 교체하거나 추가할 수 있어야 한다 | FR-03 | 전체 | 개발자 |

참고:
- 기존 FR-1~28의 "복원 후 출력 불변", "결정은 서빙을 막지 않음", "이동 트래픽 제한", "과부하 시 대기·우선순위·거절", "관측 지표 제공"은 기능이 아니라 품질이므로 FR에서 뺐다. QA 후보(§3)로 옮겼다.
- FR-29는 기능으로 보이지만 Modifiability와 겹친다. 정책 교체가 인터페이스로 존재하는가(기능)와 교체 비용이 얼마인가(QA)로 나눈다.

## 3. 품질 속성 후보 (백데이터, 21건)

ISO/IEC 25010:2023 특성에 매핑했다. 금액·임계값은 쓰지 않았고 후보 metric은 단위 종류만 적었다. "상태"가 선정이면 덱의 QA1~QA6 시나리오가 있다.

| ID | ISO 특성 > 하위 특성 | 후보 QA | 후보 metric (정의만) | 관련 DP | 상태 |
|---|---|---|---|---|---|
| QB-01 | Performance efficiency > Capacity | Throughput: SLO를 만족하는 최대 처리량 | Max SLO Goodput (req/s 또는 tokens/s) | DP1, 2, 4 (DP3 보조) | **선정(QA1)** |
| QB-02 | Performance efficiency > Time behaviour | TTFT | 고정 부하에서 TTFT 분포(P50, P99) | DP1, 3, 4 | **선정(QA2)** |
| QB-03 | Performance efficiency > Time behaviour | TPOT | 고정 부하에서 TPOT 분포 | DP1, 2, 3 | **선정(QA2)** |
| QB-04 | Performance efficiency > Time behaviour | Tail latency, 지연 변동성 | P99/P50 비, SLO 위반율 | 전체 | 후보 |
| QB-05 | Performance efficiency > Resource utilization | HBM 점유율 | SLO 충족 조건에서 HBM 점유율(평균, 피크) | 전체(DP1·3 목표, DP2·4 측정) | **선정(QA3)** |
| QB-06 | Performance efficiency > Resource utilization | 링크·tier 대역폭 활용률 | tier별·링크별 대역폭 사용률 | DP1, 2, 4 | 후보 |
| QB-07 | Performance efficiency > Resource utilization | 에너지 효율 | tokens/J 또는 W당 처리량 | 전체 | 후보 |
| QB-08 | Performance efficiency > Capacity | 수용 능력 | 지원 최대 context 길이, 동시 세션 수, adapter 수 | DP1, 3 | 후보 |
| QB-09 | Maintainability > Modifiability | 새 memory tier 추가 용이성 | 변경 모듈 수, 공수(man-month) | DP1, 2 | **선정(QA4)** |
| QB-10 | Maintainability > Modifiability | 새 정책·객체 유형 추가 용이성 | 변경 모듈 수, 공수 | DP1, 2, 4 | **선정(QA4)** |
| QB-11 | Flexibility > Scalability | 노드 수 증가 | Scaling Efficiency | DP2, 4 | **선정(QA5)** |
| QB-12 | Flexibility > Scalability | 메모리 type·tier 수 증가 | Capacity scaling efficiency, 결정 지연 증가 추세, placement optimality gap | DP1, 2 | **선정(QA5, 제안)** |
| QB-13 | Flexibility > Scalability | 세션·객체 수 증가 | 결정 지연, 메타데이터 메모리 | DP1, 4 | 후보 |
| QB-14 | Flexibility > Adaptability | 워크로드 변화 적응 | hot 대상 변화 후 성능 회복 시간 | DP1 | 후보 |
| QB-15 | Compatibility > Interoperability | 엔진·프레임워크 연동 | 지원 엔진 버전 수, 변경 없이 연동되는 인터페이스 수 | DP4 | 후보 |
| QB-16 | Compatibility > Co-existence | 혼합 부하 공존 | 이동 트래픽 동시 수행 시 서빙 지연 증가율 | DP1, 4 | 후보 |
| QB-17 | Maintainability > Analysability | 결정 근거 진단 | 결정 로그로 오결정 원인을 찾는 데 걸리는 시간 | DP4, 전체 | 후보 |
| QB-18 | Maintainability > Testability | 정책 단위의 재현·시뮬레이션 가능성 | 시뮬레이터에서 정책을 단독 실행해 재현 가능한 비율 | 전체 | 후보 |
| QB-19 | Reliability > Fault tolerance | 전송·offload 실패 시 대체 | fallback 성공률 | DP2, 4 | 후보 |
| QB-20 | Functional suitability > Correctness | 출력 불변(bit-exact) | 이동·복원 유무에 따른 출력 비교 | DP1, 2, 4 | **선정(QA6)** |
| QB-21 | Functional suitability > Correctness | Drop 후 정확도 | 압축 전 + full recompute 대비 F1 변화(상대) | DP3 | **선정(QA6)** |

제외한 것: Availability, Recoverability(장애 복구는 범위 밖), Installability, Replaceability(필요성 낮음). Reliability는 device runtime이 보장된다는 C-01에 의해 Fault tolerance만 후보로 남겼다.

## 4. 선정 QA의 유틸리티 트리 (6요소 시나리오, 정량 값 공란)

중요도·난이도(H/M/L)는 Claude 제안이다. 난이도는 기술 난이도이며 OSS 재사용은 반영했다. 순위는 중요도 H와 난이도 H/M 중심으로 제안한다.

| QA | Refinement | 시나리오 (출처 / 자극 / 환경 / 대상 / 응답 / 측정) | 중요도 | 난이도 | 순위(제안) |
|---|---|---|---|---|---|
| QA1 Throughput | Agent idle KV 이동 (DP1, 3) | 출처: Agent 클라이언트 / 자극: 요청이 지속 도착 / 환경: tool 대기 KV가 HBM을 점유한 정상 운영 / 대상: 이동 결정 스케줄러 / 응답: idle KV를 HBM 밖으로 옮겨 다른 요청을 처리 / 측정: SLO 충족 Max Goodput이 Baseline 대비 [   ] 이상 | H | M | 4 |
| QA1 Throughput | P/D 실행 위치 (DP2) | 출처: 서비스 클라이언트 / 자극: Prefill burst와 긴 history가 섞여 도착 / 환경: P/D 자원이 분리 가능한 클러스터 / 대상: 실행 위치 결정 모듈 / 응답: 요청별 분리 여부와 (n_p, n_d) 결정 / 측정: SLO 충족 Max Goodput이 Baseline 대비 [   ] 이상 | M | H | |
| QA1 Throughput | 요청 배분 (DP4) | 출처: 클라이언트 / 자극: 같은 prefix 요청이 도착 / 환경: KV 캐시가 서버별로 분산된 다중 서버 / 대상: orchestrator / 응답: KV 위치를 보고 서버를 선택 / 측정: SLO 충족 Max Goodput이 Baseline 대비 [   ] 이상 | M | M | |
| QA2 Latency | TTFT 재개·재사용 | 출처: 같은 세션 또는 같은 문서 prefix 요청 / 자극: 후속 요청 도착 / 환경: KV가 HBM 밖 tier에 있는 상태, 고정 부하 / 대상: prefetch·복원·탐색 모듈 / 응답: KV를 찾아 복원하고 재계산 최소화 / 측정: TTFT(P50, P99)가 Baseline 대비 [   ] 이내 | H | M | 5 |
| QA2 Latency | TPOT 다계층 attention | 출처: 서비스 클라이언트 / 자극: decode 진행 / 환경: KV 일부가 느린 tier에 있고 고정 부하 / 대상: 배치 결정과 tier 접근 / 응답: 접근 빈도가 높은 KV를 빠른 tier에 배치 / 측정: TPOT(P50, P99)가 Baseline 대비 [   ] 이내 | H | H | 1 |
| QA3 Resource utilization | HBM 점유율 (전체 DP, 동일 조건) | 출처: 서비스 클라이언트 / 자극: 동일 부하 유입 / 환경: 동일 workload·SLO·Baseline / 대상: 이동·Drop·배치 결정 / 응답: KV·adapter·expert를 HBM 밖으로 배치 / 측정: HBM 점유율(평균, 피크)이 Baseline 대비 [   ] 이하 | H | M | 3 |
| QA4 Modifiability | 새 tier 추가 | 출처: 시스템 개발자 / 자극: 새 메모리 tier(HBF, CXL 등) 추가 요청 / 환경: 개발 시점 / 대상: 정책·배치 모듈 / 응답: 인터페이스에 맞춰 tier를 추가 / 측정: 변경 모듈 [   ] 개, 공수 [   ] man-month 이내 | H | M | |
| QA4 Modifiability | 새 정책·객체 추가 | 출처: 시스템 개발자 / 자극: 새 이동·라우팅 정책 또는 새 객체 유형 추가 / 환경: 개발 시점 / 대상: 정책 인터페이스 / 응답: 서빙 경로 수정 없이 반영 / 측정: 변경 모듈 [   ] 개, 공수 [   ] 이내 | M | L | |
| QA5 Scalability | 노드 수 증가 (DP2, 4) | 출처: 운영자 / 자극: 노드 수를 N에서 2N, 4N으로 증설 / 환경: 시뮬레이션 기반 평가(C-02) / 대상: 결정 모듈 / 응답: 결정이 병목이 되지 않고 처리량 증가 / 측정: Scaling Efficiency [   ] 이상 | M | H | |
| QA5 Scalability | 메모리 type·tier 수 증가 (제안) | 출처: 운영자 / 자극: 새 type의 메모리를 tier로 추가 / 환경: 스펙 기반 시뮬레이션(C-01, C-02) / 대상: 배치 결정 모듈 / 응답: 추가된 용량을 활용하며 결정 품질 유지 / 측정: Capacity scaling efficiency [   ] 이상, 결정 지연 증가율 [   ] 이내, optimality gap [   ] 이내 | M | M | |
| QA6 Correctness | 출력 bit-exact (DP1, 2, 4) | 출처: 클라이언트 / 자극: 이동·복원·offload·재사용을 거친 요청 / 환경: 같은 precision / 대상: 데이터 이동·복원 경로 / 응답: 경로를 거치지 않은 경우와 같은 출력 / 측정: 출력 불일치 [   ] 건 이내 | H | L | |
| QA6 Correctness | Drop 후 정확도 (DP3) | 출처: 클라이언트 / 자극: 중요도 기반 Drop·압축 재사용 적용 / 환경: 지정 task와 dataset(미정) / 대상: Drop·재사용 정책 / 응답: 정확도 한도 안에서 Drop / 측정: 압축 전 + full recompute 대비 F1 하락 상대 [   ] 이내 | H | H | 2 |

주의:
- QA6의 DP3 시나리오는 C-04("출력 불변")와 충돌하므로 §1.1의 1번 결정이 필요하다.
- "순위"는 H/H, H/M 중심 제안이며 사업 목표를 몰라 소유자 판단이 필요하다.
- QA2 TTFT/TPOT는 고정 부하에서 분포를 재고, QA1은 SLO를 고정해 최대 처리량을 재도록 나눠 순환 정의를 피한다(대화에서 제안).

## 5. 다음 단계
1. §1.1 결정(DP3와 C-04, 링크 대역폭의 위치, C-02 문구).
2. QA 후보 21건 중 덱에 올릴 QA 확정, 중요도·난이도 조정.
3. 덱 재작성: 요구사항 정제(첨부 형식), 유틸리티 트리, 아키텍처 드라이버. PPT가 열리지 않는 문제도 이때 구조를 단순화해 다시 만든다.
