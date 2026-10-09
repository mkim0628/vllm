# DP3 요구사항 도출: 기능 요구사항, 품질 속성, 품질 시나리오, 제약 사항

> 상태: **초안(제안)**. 2026-10-09 사용자 지시에 따라 **정량 임계값과 평가 결과는 이 문서에 쓰지 않는다**(전 DP를 훑은 뒤 통합 단계에서 일관된 값으로 정함). 품질 시나리오의 6요소는 모두 채웠고, 응답 측정은 **metric, 통계량, 비교 기준, 측정 조건**까지 쓰고 임계값은 `TBD(통합 단계)`로 둔다.
> DP 번호는 최종 번호([`project-context.md`](project-context.md) §0): **DP3 = KV eviction 및 reuse** (long-context KV의 선택적 제거와 압축 KV 재사용). 출처: `DP문서`(위치 표기) / `도출` / `사용자`. 상태: `문서 확정` / `제안`.
> **[2026-10-09 사용자 결정]** (1) **DP3의 설계 문서는 `dp3-kv-compression-reuse-structure-draft.md`(문서 B, 압축·재사용·선택 재계산)** 이다. 원본 문서 A(Drop/Demote 용량 압박 틀)에서 온 항목(DP1 우선 규칙 FR-05, 실행 시점 E1~E4 FR-06, B0/B1 기준선, Drop/Demote 분해 M-C5)은 **B 프레임에서의 유효성을 확인할 때까지 보류 표시**한다. (2) **허용 정확도 한도**: **압축하기 전 + full recompute**(selective recompute가 아닌 전체 재계산)한 결과 대비 **모델 정확도(F1 score) 하락 1% 이내**.

## 0. 읽은 입력

| 구분 | 파일 | 읽은 범위 |
|---|---|---|
| 설계 A | `DP3/dp3-long-context-kv-cache-eviction.md` (824줄) | 전체. Demote/Drop 구분, C1 Offline/C2 Online, 실행 시점 E1~E4, DP1 연결, 평가 metric M-C1~M-R2, 보고 원칙 |
| 설계 B | `DP3/dp3-kv-compression-reuse-structure-draft.md` (255줄, 2026-10-03 초안) | 전체. 모듈 구조(Query Sampler, KV Sampler, KV Cache Compressor, Recompute Token Selector, Selective Recomputer), Comp.KV 재사용, DP1·DP2 계약 |
| PPT | `DP3-slides-draft.pptx`, `DP-memory-backend-if.pptx` 1장(QA 표) | QA 표만 확인. DP3-slides-draft 본문은 읽지 않음 |
| 평가 | `Evaluation/DP3/README.md`, `benchmark.md` | **둘 다 TBD, 평가 문서·결과가 아직 없다**(치워 둘 평가 결과가 없음) |
| **읽지 못함** | `DP3-slides-draft.pptx` 본문, `vllm-dp3-memory-placement-abstraction-candidates.md`(옛 DP3 주제, 번호 불일치 문서) | 필요 시 읽음 |

## 1. DP3 구조 재구성

두 설계 문서는 **같은 동작을 다른 각도에서 쓴 것**이다(B §1). A는 "HBM 용량 압박에서 DP1이 배치를 마친 뒤에도 모자랄 때 무엇을 **버릴 것인가**(Drop)", B는 "attention 점수가 낮은 토큰을 제거해 압축 KV(Comp.KV)를 만들고 **재사용**하며 일부 토큰만 **선택 재계산**한다"이다. 사용자 정의의 "KV eviction 및 reuse"는 둘을 합친 것으로 읽었다.

```text
        [사전: C1만]                                  [서빙 시]
Query Sampler ─► Attention Manager ─► KV Sampler ─┬─► KV Cache Compressor ─► Comp.KV ──► (KV 저장소, DP1 관리)
 (대표 Query)     (기존 LLM 생성 구조)  (낮은 토큰 선정)  │      (토큰 제거)               │
                                                   └─► Recompute Token Selector ─────────┴─► Selective Recomputer (기존) ─► Decode
User Query Manager ─(C2는 실제 Query로 Stage 1 attention을 요청 시점에 수행)
```

- **설계 쟁점**: 중요도(Query-dependent KV importance)를 **언제** 평가하는가. C1 Offline = 서빙 전 대표 Query, 압축 결과를 요청 간 공유. C2 Online = 요청 시점 실제 Query, 요청 단위 압축.
- **Demote와 Drop은 다른 결정**이다(A §2.1). Demote(DP1 소관)는 무손실로 HBM 용량만 회수하고, Drop(DP3 소관)은 전체 용량을 회수하지만 **정확도 손실**과 재계산 비용이 따른다. 본 문서에서 Eviction = Drop이다.
- DP1과의 순서 규칙: DP1이 먼저 배치하고 DP3는 용량 제약을 못 맞출 때만 개입(A §2.4). 단 C1 오프라인 압축은 서빙 전에 일어나므로 이 규칙의 적용 범위를 정해야 한다(B §5, 미결).
- **현재 상태: 구현·시뮬레이터·평가가 없다.** 모든 내용은 구조 논증 [C]이고 문헌 [B]는 원문 확인 전이다.

## 2. 기능 요구사항 (DP3-FR)

### 2.1 공통 (C1, C2)

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP3-FR-01 | 시스템은 Query와 Context KV 사이의 **attention score로부터 KV(토큰) 중요도를 산출**해야 한다 | DP문서 A §3, B §2 | Attention Manager(기존), KV Sampler | UC-2, 3 | 산출한 중요도와 attention 점수의 일치 | 문서 확정 |
| DP3-FR-02 | 시스템은 중요도가 낮은 토큰을 **선정해 제거**(Drop)하고 압축 KV(Comp.KV)를 만들어야 한다 | 사용자(2026-10-09, UC-2 FR-9), DP문서 A §2.1, B §2 | KV Sampler, KV Cache Compressor | UC-2 | 제거 토큰 목록, 압축 KV 크기 | 문서 확정 |
| DP3-FR-03 | 시스템은 압축 KV를 쓸 때 정확도를 지키기 위해 **일부 토큰만 선택적으로 재계산**하고(blending 계열), 재계산할 토큰을 Recompute Token Selector가 정해 Selective Recomputer에 전달해야 한다. 선택 재계산의 구체적 방법은 이후에 정한다(사용자 설명) | DP문서 B §0, §2 | Recompute Token Selector, Selective Recomputer(기존) | UC-2, 3 | 재계산 토큰 선정 결과와 재계산 실행 | 문서 확정(방법 미정) |
| DP3-FR-04 | 시스템은 **Drop 대상의 범위**를 제한해야 한다. 다른 세션이 hit할 수 있는 **공유 prefix cache block은 Drop 대상에서 제외**한다(중요도가 자기 세션의 Query 기준이라 다른 세션에 대한 판정 근거가 없음) | DP문서 A §2.4 | Drop 대상 필터 | UC-1, 3 | 공유 block Drop 건수 0 | 문서 확정 |
| DP3-FR-05 (**A 유래, B 프레임 유효성 확인 필요**) | 시스템은 용량 회수에서 **DP1의 배치(Demote)가 먼저** 시도되고, DP3의 Drop은 DP1이 용량 제약을 만족시키지 못할 때(전체 용량 포화, 재접근 비용이 SLO를 깸, 이동 비용이 보관 이득을 넘음)에만 개입하도록 해야 한다 | DP문서 A §2.2, §2.4 | DP1 Placement ↔ DP3 Drop 판정 | UC-2 | 개입 조건 로그, DP1 단독으로 해결된 경우 Drop 0 | 문서 확정(C1 오프라인에는 적용 범위 미결) |
| DP3-FR-06 (**A 유래, 보류**) | 시스템은 **회수 실행 시점**(E1 watermark, E2 admission, E3 decode step 경계, E4 비활성 전환)을 정책으로 선택할 수 있어야 하고, 두 후보를 비교할 때는 **같은 실행 시점**을 적용할 수 있어야 한다 | DP문서 A §2.3, §9.6 | Eviction 실행 시점 정책 | UC-2 | 실행 시점별 동작 | 문서 확정 |
| DP3-FR-07 | 시스템은 **압축률(유지 비율) 또는 Drop 비율 상한**을 정책 변수로 설정할 수 있어야 한다. 누가 정하는지는 미결이다 | DP문서 B §8-6, A §9.6(Drop 비율 상한 축) | 압축 정책 변수 | UC-2 | 변수 변경에 따른 압축 크기와 정확도 | 문서 확정(주체 미결) |
| DP3-FR-08 | 시스템은 Drop한 KV에 **다시 접근**하면 **재계산(Prefill)** 으로 복구해야 한다. Drop은 되돌릴 수 없다 | DP문서 A §2.1, M-R1 | 재계산 경로(Prefill, 실행 자원은 DP2) | UC-1, 2 | 재접근 건수와 재계산 시간 | 문서 확정 |
| DP3-FR-09 | 시스템은 알고리즘(중요도 점수, 토큰 선택, 재계산 토큰 선정)을 **교체 가능한 정책 모듈**로 두고, DP 수준의 고정은 **결정 시점, DP 간 데이터 계약, 검증 지점**으로 한다 | DP문서 B §0 | 정책 모듈 경계 | — | QS-8 | 문서 확정 |
| DP3-FR-10 | 시스템은 **압축 적용 후 정확도를 검증하고 기준에 못 미치면 되돌리거나 완화(fallback)** 할 수 있어야 한다 | DP문서 B §4.2([C, 신규 제안]) | 정확도 검증과 fallback | UC-2 | 검증 실패 시 원복 | 제안 |
| DP3-FR-11 | 시스템은 **Drop과 Demote의 바이트를 분해해 기록**하고, 중요 KV 오분류율과 대표 Query–실제 Query 중요도 일치율을 계측할 수 있어야 한다 | DP문서 A §9.3~§9.4 (M-C5, M-A2, M-A3) | Observability | 전체 | 계측 필드 완비 | 문서 확정 |
| DP3-FR-12 | 시스템은 선택 재계산 토큰 수와 압축 KV 크기를 **DP2(실행 위치 결정)에 전달**하고 DP2의 실행 자원 결정·큐 지연을 받아야 한다. Comp.KV의 위치·로드 비용은 **DP1과 주고받는다** | DP문서 B §5 (제안 [C]) | DP 간 계약 | UC-2, 3 | 계약 필드 | 제안 |

### 2.2 C1 Offline 특화

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP3-FR-C1-01 | 시스템은 서빙 전에 **워크로드별 대표 Query를 선정**하고 대표 Query와 Context KV의 attention으로 중요도 프로파일을 산출해야 한다 | DP문서 A §4, B §3 | Query Sampler, Attention Manager | UC-2 | 선정한 Query 집합, 프로파일 | 문서 확정 |
| DP3-FR-C1-02 | 시스템은 사전에 만든 **Comp.KV와 재계산 토큰 선정 결과를 저장**하고(저장 위치는 어디든 가능, 배치는 DP1), **요청 간에 공유**해야 한다 | DP문서 B §3(사용자 설명), §5 | Comp.KV 저장, DP1 KV 저장소 | UC-3 | 재사용 횟수, 공유 hit | 문서 확정 |
| DP3-FR-C1-03 | 시스템은 Comp.KV에 **유지 토큰 정보, 압축 기준(대표 Query 집합), 프로파일 버전**의 메타데이터를 붙여 식별 가능하게 해야 한다. 워크로드가 바뀌면 오프라인 산출물을 **갱신**하는 정책이 필요하다(정책 미정) | DP문서 B §5, §8-3, §8-4 | Comp.KV 식별 단위, 갱신 정책 | UC-3 | 버전 불일치 탐지 | 제안(갱신 정책 미결) |

### 2.3 C2 Online 특화

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP3-FR-C2-01 | 시스템은 요청이 입력된 뒤 **실제 Query와 Context KV의 attention(Stage 1)** 으로 중요도를 산출하고 그 요청의 압축·재계산 토큰을 결정해야 한다 | DP문서 A §5, B §3 | Attention Manager, KV Sampler | UC-2 | 요청별 압축 결과 | 문서 확정 |
| DP3-FR-C2-02 | 시스템은 C2의 판단 비용(Stage 1 attention, 압축, 선택)이 **요청 경로(critical path) 위에 있음**을 전제로, 그 비용을 측정·관리할 수 있어야 한다. C2의 압축 결과가 요청별인지 재사용 가능한지는 미결이다 | DP문서 A §2.3(E3), B §8-2 | Runtime Overhead | UC-2 | 결정 지연 | 문서 확정(재사용 여부 미결) |

### 2.4 과제 UC와 DP3의 관계 (`usecases.md` FR과 대조)

| 과제 FR | DP3가 담당하는 부분 | 담당하지 않는 부분 |
|---|---|---|
| FR-9 (UC-2 정확도 손실이 있는 선택적 Drop, **필수 흐름**, 사용자 확정) | **핵심 담당**: DP3-FR-01~08, 10 | Demote(무손실 이동)는 DP1 |
| FR-7, 8 (UC-2 long-context가 HBM 초과) | Drop으로 working set을 줄임(DP1 Demote로 부족할 때) | 용량 확보를 위한 Tier 간 이동은 DP1 |
| FR-10, 11 (UC-3 RAG hot/cold, 다중 문서 KV) | 여러 Context KV(Context1 KV, Context2 KV)를 **압축해 이어 붙여 재사용**하고 일부 토큰을 선택 재계산(B §1 ③) | 문서 갱신 시 KV 무효화는 범위 밖(GC-10) |
| FR-1~5 (UC-1 agent 다회 turn) | 누적 context가 길어질 때 오래된 KV의 선택적 제거 | idle KV의 Tier 이동·prefetch는 DP1 |
| FR-6 (출력 불변) | **예외**: DP3만 정확도 손실을 허용(GC-7). 허용 한도는 요구사항 변수 | — |

## 3. 품질 속성 (QA)

### 3.1 (a) DP3가 선정한 QA

DP3 문서는 이미 **ISO 25010 용어**(Performance Efficiency, Time Behaviour, Resource Utilization, Functional Suitability, Functional Correctness)로 QA를 쓰고 있다(A §9.1). PPT 표(`DP-memory-backend-if.pptx` 1장)는 DP3에 **Performance latency, Functional Correctness(Accuracy, F1 score), Resource Utilization(물음표 표기)** 을 적었고 Modifiability 칸은 비어 있다.

| ID | QA | metric (원문, 수치 없음) | ISO/IEC 25010:2023 매핑 | 출처 |
|---|---|---|---|---|
| DP3-QA1 | Performance efficiency (종합) | **M-C1 SLO-제약 Goodput**(주 지표): SLO(TTFT, TPOT)를 만족한 request의 output token ÷ 시간. **Accuracy가 떨어진 request를 분자에 넣지 않거나 M-A1과 반드시 쌍으로만 보고** | Performance efficiency > Capacity (Time behavior 겸) | A §9.3 |
| DP3-QA2 | Time behavior | **M-C2 TTFT**(Drop된 KV에 접근한 request와 접근하지 않은 request를 분리, p50/p99), **M-C3 회수 결정 latency**(C1은 Online Phase 조회 비용 + Offline Phase 비용 별도, C2는 critical path) | Performance efficiency > Time behavior | A §9.3, PPT |
| DP3-QA3 | Resource utilization | **M-C4 HBM KV footprint & peak occupancy**, KV compression ratio, **M-C5 Drop/Demote 분해**(Drop 비중). DP1의 M-P6와 같은 정의 | Performance efficiency > Resource utilization | A §9.3, PPT(물음표) |
| DP3-QA4 | Functional correctness | **M-A1 Task accuracy retention**(주 지표, task별 분리, 단일 평균 금지; PPT는 F1), **M-A2 중요 KV 오분류율(FNR)**, **M-A3 대표–실제 중요도 일치율**(C1 고유) | Functional suitability > Functional correctness | A §9.4, PPT |
| (공통 risk) | — | **M-R1 재계산 비용**(총 시간과 사건 횟수), **M-R2 prefix cache 오염** | M-R1: Time behavior, M-R2: Functional correctness(공유 block 제외 규칙 준수 확인) | A §9.5 |

설계 문서는 **Performance efficiency와 Functional correctness를 하나의 점수로 합치지 않는다**(가중치를 사람이 정하는 순간 결론이 가중치의 함수가 되므로, A §9.1). 보고는 iso-accuracy와 iso-compression의 이중 보고다(A §9.6).

### 3.2 (b) 추가 후보 QA (ISO/IEC 25010:2023 목록 안)

| ID | ISO 특성 > 하위 특성 | 후보 | 관련 이유 | 미선정 시 위험 | 선정 QA와의 관계 | 의견 |
|---|---|---|---|---|---|---|
| DP3-QA5 | Maintainability > Modifiability, Modularity | importance 점수, 토큰 선택, 선택 재계산 방법 교체 | B §0: 알고리즘은 교체 가능한 정책 모듈로 두는 것이 DP 구조의 핵심. 선택 재계산 방법은 아직 미정(사용자 설명). DP1·DP2·DP4는 모두 Modifiability를 QA로 둠(DP3만 비어 있음) | 알고리즘이 바뀔 때마다 구조가 흔들림 | DP1·DP2·DP4와 QA 정합 | **권장** |
| DP3-QA6 | Reliability > Fault tolerance, Recoverability | 압축 후 정확도 검증과 fallback, 대표 Query 불일치 시 대응 | B §4.2(정확도 검증과 fallback [C, 신규 제안]), C1의 핵심 위험(대표 Query mismatch)과 오프라인 산출물이 낡을 때 | 중요 KV 오제거가 정확도 저하로 직결되어도 되돌릴 수 없음(Drop은 비가역) | QA4와 연계 | **권장**(GC-3: device runtime 오류는 제외, 우리 계층의 대응만) |
| DP3-QA7 | Compatibility > Interoperability | DP1·DP2와의 접점 계약(Comp.KV 객체, 로드 비용, 재계산 토큰 수, 실행 자원) | B §5가 4방향 계약을 제안([C]). C1 오프라인 산출물 생성은 서빙 전 별도 단계라 DP1 규칙과 충돌 | 접점이 어긋나면 DP3 이득이 DP1·DP2 구성에 따라 사라짐 | 모든 선정 QA에 영향 | **권장** |
| DP3-QA8 | Maintainability > Analysability | Drop/Demote 분해, FNR, 일치율, 재접근률 계측 | A §9: 이득이 DP1의 것인지 DP3의 것인지 구분하는 유일한 수단이 분해 지표 | 이득의 출처를 가릴 수 없음 | DP3-QA3, QA4의 검증 수단 | **권장** |
| DP3-QA9 | Flexibility > Scalability | context 길이, 동시 세션 수 증가에 따른 판단 비용과 이득 | A §9.6이 Context 길이와 동시 세션을 sweep 축으로 둠. 별도 QA는 아님 | C2 판단 비용이 규모에서 급증 | DP3-QA2와 일부 겹침 | **보류**(Time behavior 시나리오의 변수로 편입 가능) |
| (제외) | Security > Confidentiality | 요청 간 Comp.KV 공유 시 세션 간 정보 노출 | GC-6(보안, tenant 격리 범위 밖) | — | — | **제외** |

## 4. 품질 시나리오 (6요소, 정량 임계값 없음)

> 모든 시나리오의 응답 측정은 `metric / 통계량 / 비교 기준 / 측정 조건`을 쓰고 **임계값은 `TBD(통합 단계)`** 다. 이 DP는 구현·평가가 없으므로 현 평가값도 없다. 정확도는 실제 모델 실행으로 측정할 수 있지만([A] 가능, 도출) 차세대 메모리 성능은 시뮬레이션이다(GC-1).

#### DP3-QS-1 Capacity — long-context × 동시성에서의 Goodput (선정, DP3-QA1 · ISO: Capacity)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 누적 context가 긴 agent·RAG 요청 클라이언트(다수) |
| 2. 자극 | context 길이와 동시 세션 수가 증가해 HBM 용량 압박이 DP1 Demote만으로는 해소되지 않음(전체 용량 포화, 재접근이 SLO를 깸, 이동 비용 > 보관 이득 중 하나). 부하 sweep |
| 3. 환경 | 정상 운전, 연산형 메모리(ScHBM, CXL-PNM) 용량은 sweep 축(가장 중요), DP1 구성 병기, 실행 시점(E1~E4) 두 후보 동일 고정, Scheduler 선점 방식(Recompute/Swap)과 prefix caching 고정 |
| 4. 자극 대상체 | KV Sampler, KV Cache Compressor, Recompute Token Selector(C1/C2 pipeline)와 DP1 Placement |
| 5. 응답 | 중요도가 낮은 KV를 제거해 working set을 줄이고 SLO를 유지하면서 더 많은 요청을 처리한다 |
| 6. 응답 측정 | **M-C1 SLO-제약 Goodput**(tok/s). 기준선은 **B1(Demote-only) = 1.0**(B0 대비로 보고하면 DP1의 이득이 DP3 성과로 집계됨). **Accuracy 하한을 SLO에 포함하거나 M-A1과 쌍으로만 보고**. iso-accuracy와 iso-compression 이중 보고. 같은 seed 쌍 반복, 신뢰구간이 0을 지나면 차이 없음. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA1. UC-2. FR: DP3-FR-02, 05, 06, 07. 제약: DP3-C-5, 6 |

#### DP3-QS-2 Time behavior — Drop한 KV에 접근할 때의 TTFT (선정, DP3-QA2 · ISO: Time behavior)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | agent 요청 클라이언트(이전 turn의 context를 포함한 요청) |
| 2. 자극 | 요청이 Drop된 KV에 접근하는 경우와 접근하지 않는 경우가 섞여 도착. C2는 실제 Query의 Stage 1 attention이 요청 경로에 추가 |
| 3. 환경 | 정상 운전, 실행 시점·Scheduler 고정 규칙 적용, DP1 구성 병기 |
| 4. 자극 대상체 | Selective Recomputer, 재계산 경로(Prefill), C2의 Attention Manager Stage 1 |
| 5. 응답 | 접근하지 않는 요청의 TTFT는 압축 KV로 줄고, 접근하는 요청은 선택 재계산으로 복구해 TTFT 증가를 제한한다 |
| 6. 응답 측정 | **M-C2 TTFT p50/p99**, **Drop된 KV에 접근한 request와 접근하지 않은 request를 분리 보고**(합치면 Drop의 대가가 평균에 희석). B1 대비. 후보별 TTFT 분해(C1: incremental prefill + 재계산, C2: attention + importance + 결정 + incremental prefill). **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA2. UC-1, 2. FR: DP3-FR-03, 08, C2-01 |

#### DP3-QS-3 Time behavior — 회수 결정 지연과 Offline 비용의 상각 (선정, DP3-QA2 · ISO: Time behavior)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 서빙 엔진(회수가 필요한 시점)과 워크로드 변화(대표 Query 재산출 요구) |
| 2. 자극 | C2: 매 요청 시점의 importance 판단. C1: 워크로드가 바뀌어 오프라인 단계를 다시 실행 |
| 3. 환경 | 정상 운전, E3(decode step 경계)에서는 활성 Decode의 critical path 위, context 길이와 동시 세션 수를 sweep |
| 4. 자극 대상체 | KV Sampler와 회수 결정 경로(C2 critical path, C1 오프라인 단계) |
| 5. 응답 | C2는 판단 비용을 critical path에서 최소화하고, C1은 오프라인 비용이 Comp.KV 재사용으로 회수된다 |
| 6. 응답 측정 | **M-C3 회수 결정 latency** = (importance 산출 + 대상 선정 시간) ÷ 결정 건수. **M-C1에 합산**해 C2 판단 비용이 회수 이득을 상쇄하는 **Crossover**를 보고. C1 Offline 비용은 별도 보고하고 **Comp.KV 재사용 횟수로 상각**. 정규화 기준은 B1. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA2. FR: DP3-FR-C1-01, C1-02, C2-02 |

#### DP3-QS-4 Resource utilization — HBM KV footprint (선정, DP3-QA3 · ISO: Resource utilization)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 긴 context 요청 클라이언트 |
| 2. 자극 | long context × concurrency로 상위 memory capacity pressure 증가 |
| 3. 환경 | 정상 운전, DP1 구성 병기(연산형 메모리 용량 sweep), 실행 시점 고정 |
| 4. 자극 대상체 | KV Cache Compressor와 Drop 판정, DP1 Demote와의 분담 |
| 5. 응답 | HBM에 상주하는 KV working set을 줄이되, 그 감소가 Drop인지 Demote인지 구분되어 기록된다 |
| 6. 응답 측정 | **HBM KV footprint**(step별 상주 bytes, 평균과 최대), **HBM peak occupancy**, **KV compression ratio**를 **반드시 M-C5(Drop/Demote 분해)와 함께 보고**(분자에 Drop과 Demote가 섞이면 구분이 사라짐). 세션 수 기준과 바이트 기준 양쪽. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA3. FR: DP3-FR-02, 05, 11. 제약: DP3-C-1, 5 |

#### DP3-QS-5 Functional correctness — task별 Accuracy 유지 (선정, DP3-QA4 · ISO: Functional correctness)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | long-context task를 요청하는 클라이언트(요약, 검색형 needle-in-haystack, 추론형) |
| 2. 자극 | 중요도가 낮은 KV가 Drop된 상태에서 task 요청 처리. 대표 Query와 실제 Query의 attention 패턴이 다른 경우 포함(C1) |
| 3. 환경 | 정상 운전, Drop 비율 상한 sweep, 상위 k(Importance 임계)는 실행 전에 고정, B0(전량 HBM) 성립 구성에서 Accuracy 상한 확보 후 외삽 |
| 4. 자극 대상체 | KV Sampler(판정), Recompute Token Selector, Selective Recomputer |
| 5. 응답 | 중요한 KV를 남기고 필요한 토큰을 재계산해 task 결과의 품질 저하를 최소화한다 |
| 6. 응답 측정 | **M-A1 Accuracy retention** = Task accuracy(후보) ÷ Task accuracy(B0), **task별 분리, 단일 평균 금지**(PPT: F1). **Drop이 0인 실행에서 B0와 다르면 측정 파이프라인 오류**(정합성 점검, 통과 못하면 비교 불가). Accuracy를 Drop된 바이트에 귀속. 반복 횟수는 성능 지표보다 크게. **임계값(허용 정확도 저하 한도): F1 하락 1% 이내, 기준 = 압축 전 + full recompute** `[사용자 확정 2026-10-09]`(상대/절대 확인 필요). 다른 임계값은 TBD(통합 단계) |
| 연결 | QA: DP3-QA4. UC-2. FR: DP3-FR-02, 03, 10. 제약: DP3-C-4 |

#### DP3-QS-6 Functional correctness — 판정 품질과 대표–실제 불일치 (선정, DP3-QA4 · ISO: Functional correctness)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 워크로드의 query 분포(다양성) |
| 2. 자극 | 대표 Query의 attention 패턴이 실제 Query와 다른 상황, 워크로드 다양성 증가 |
| 3. 환경 | 정상 운전, 대표 Query 선정 방법·개수를 결과와 함께 명시, k는 실행 전 고정 |
| 4. 자극 대상체 | Query Sampler와 KV Sampler(C1), Attention Manager(C2) |
| 5. 응답 | 실제 Query에서 중요한 KV를 Drop하지 않는다(오분류가 낮다) |
| 6. 응답 측정 | **M-A2 FNR** = 실제 Query에서 attention 상위 k에 들었으나 Drop된 KV 수 ÷ 상위 k KV 수(여러 k의 곡선). **M-A3 일치율** = 대표 Query 기준 상위 k ∩ 실제 Query 기준 상위 k ÷ k(C2는 정의상 1.0 → 정합성 점검). FNR이 낮은데 Accuracy가 떨어지면 "상위 k만 남기면 된다"는 전제가 반증됨. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA4. FR: DP3-FR-C1-01, 11 |

#### DP3-QS-7 Time behavior / Functional correctness — 재계산 비용과 prefix cache 오염 (선정, 공통 risk, DP3-QA2·QA4)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | Drop한 KV를 다시 필요로 하는 요청과 prefix를 공유하는 다른 세션의 요청 |
| 2. 자극 | Drop한 KV에 재접근, 다른 세션이 공유 prefix block에 hit 시도 |
| 3. 환경 | 정상 운전, prefix caching on/off와 Recompute 선점 방식을 별도 조건으로 보고 |
| 4. 자극 대상체 | 재계산 경로(Prefill은 GPU), Drop 대상 필터(공유 block 제외) |
| 5. 응답 | 재접근 시 재계산으로 복구하되 총 비용이 이득을 넘지 않고, 공유 block은 Drop되지 않아 다른 세션의 hit가 유지된다 |
| 6. 응답 측정 | **M-R1** 재계산 총 시간과 사건 횟수, 재접근률(세션 수·바이트 기준). **M-R2** Prefix cache hit rate 변화(후보 − B1), 타 세션 영향(Drop으로 hit에 실패한 request 수). **M-R2 ≠ 0이면 구현이 공유 block 제외 규칙을 위반한 것이며 해당 실행은 비교 불가**. Scheduler의 Recompute 선점과 DP3 Drop을 구분(선점이 이미 하는 일을 DP3 성과로 집계하지 않음). **임계값: TBD(통합 단계)** |
| 연결 | FR: DP3-FR-04, 08. 제약: DP3-C-3, 6 |

### 4.2 추가 후보 QA (채택 전 초안)

#### DP3-QS-8 Modifiability — 알고리즘 교체 (추가, DP3-QA5 · ISO: Modifiability, Modularity)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자 |
| 2. 자극 | (a) importance 점수 방식 교체, (b) 토큰 선택 방식 교체, (c) 선택 재계산 방법 확정·교체, (d) 신규 task 유형 추가 |
| 3. 환경 | 개발 시점, C1과 C2 각각, 정책 모듈 경계가 있는 구조 |
| 4. 자극 대상체 | KV Sampler, Recompute Token Selector, Selective Recomputer 인터페이스, 정책 모듈 경계 |
| 5. 응답 | DP 수준 구조(결정 시점, DP 간 계약, 검증 지점)를 바꾸지 않고 정책 모듈만 교체한다 |
| 6. 응답 측정 | 변경 **module 수, 개발 공수(man-month), 에이전트 비용($)**(DP1·DP2·DP4와 **같은 공식**으로 측정할 후보, 통합 단계에서 정의 통일), 변경한 주요 interface 수. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA5. FR: DP3-FR-09 |

#### DP3-QS-9 Fault tolerance / Recoverability — 압축 후 정확도 저하 또는 오프라인 산출물이 낡을 때 (추가, DP3-QA6 · ISO: Reliability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 워크로드 변화, 대표 Query 불일치, 적용 후 정확도 검증 실패 |
| 2. 자극 | C1의 오프라인 프로파일이 바뀐 워크로드에 맞지 않거나, 압축 적용 후 검증에서 정확도 저하 감지 |
| 3. 환경 | 정상 운전 중 워크로드 분포가 이동. device runtime 오류는 제외(GC-3) |
| 4. 자극 대상체 | 정확도 검증과 fallback, Comp.KV 갱신 정책 |
| 5. 응답 | 저하를 감지해 압축을 완화하거나 압축하지 않은 KV로 되돌리고(가능한 범위, Drop은 비가역이므로 이미 버린 것은 재계산) 서비스를 이어 간다 |
| 6. 응답 측정 | 불일치 발생부터 **감지까지 걸린 시간**, 감지 후 **정확도 회복까지 걸린 시간**, 회복 중 Goodput(Baseline B1 대비). **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA6. FR: DP3-FR-10, C1-03 |

#### DP3-QS-10 Interoperability — DP1, DP2와의 접점 계약 (추가, DP3-QA7 · ISO: Interoperability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자(DP1 구성 또는 DP2 정책 변경) |
| 2. 자극 | DP1의 KV 저장소 구성이 바뀜(Tier 추가), DP2의 실행 자원 결정이 바뀜, Comp.KV 식별 단위 변경 |
| 3. 환경 | 개발·통합 시점 |
| 4. 자극 대상체 | DP3↔DP1 계약(Comp.KV 객체, 로드 비용, 용량 압박 신호), DP3↔DP2 계약(재계산 토큰 수, 실행 자원, 큐 지연) |
| 5. 응답 | 계약을 유지한 채 각 DP가 독립적으로 진화하고 DP3의 이득 측정이 DP1·DP2 구성을 병기해 비교 가능하다 |
| 6. 응답 측정 | 계약 필드 변경이 번지는 **module 수와 interface 수**, 결과 보고에 DP1 Configuration 병기 여부(완비율). **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA7. FR: DP3-FR-12. 제약: DP3-C-5, 12 |

#### DP3-QS-11 Analysability — 이득의 출처 분해 (추가, DP3-QA8 · ISO: Analysability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자(성능 이득의 원인 분석) |
| 2. 자극 | Goodput 상승이 관찰되었으나 DP1의 Demote 덕인지 DP3의 Drop 덕인지 불명 |
| 3. 환경 | 평가·운영 중, 계측 활성 |
| 4. 자극 대상체 | Observability(Drop/Demote 분해, FNR, 일치율, 재접근률) |
| 5. 응답 | 이득을 DP1과 DP3로 분해해 보고할 수 있도록 계측값을 남긴다 |
| 6. 응답 측정 | **Drop 비중** = Drop bytes ÷ (Drop bytes + Demote bytes), 필수 계측 필드 완비율. 비중이 낮은데 Goodput이 올랐다면 그 이득은 DP1의 것으로 판정. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP3-QA8. FR: DP3-FR-11 |

## 5. 제약 사항 (예상 질문 기반)

| ID | 예상 질문 | 제약 문장 | 유형 | 설계 영향 | 출처 | 근거 위치 |
|---|---|---|---|---|---|---|
| DP3-C-1 | "Eviction은 Demote인가 Drop인가? DP1과 뭐가 다른가?" | 본 DP에서 **Eviction = Drop**이다. 하위 Tier로의 이동(Demote)은 DP1의 결정이며 Accuracy와 교환되지 않는다. Demote만 하는 구조에서는 Attention Importance를 쓸 이유가 없다 | 범위/경계 | 문서 용어 정리 필요(DP1의 Data Eviction Manager와 충돌) | DP문서 | A §2.1, B §7 |
| DP3-C-2 | "DP3는 언제 개입하나?" | DP3의 Drop은 **DP1 배치가 용량 제약을 만족하지 못할 때만** 개입한다(DP3는 DP1의 실패 처리 경로). 단 C1 오프라인 압축은 서빙 전에 일어나므로 이 규칙은 **런타임에 이미 상주하는 KV를 회수하는 경우로 한정할지** 결정해야 한다 | 경계/미결 | 원본 A §2.4 개정 필요 | DP문서 | A §2.4, B §5, §8-7 |
| DP3-C-3 | "다른 세션이 쓰는 prefix cache는?" | **공유 prefix block은 Drop 대상에서 제외**한다. 중요도는 자기 세션의 Query 기준이라 다른 세션에 대한 판정 근거가 없다 | 범위 밖/전제 | 공유 block 비율이 높은 workload에서 이득 한정 | DP문서 | A §2.4 |
| DP3-C-4 | "정확도를 잃어도 되나? 얼마까지?" | DP3는 **프로젝트의 정확도 불변 제약(GC-7)의 유일한 예외**다. 허용 한도는 **압축 전 + full recompute(selective recompute가 아닌 전체 재계산) 대비 모델 정확도(F1 score) 하락 1% 이내**다 `[사용자 확정 2026-10-09]`. "1%"가 상대인지 절대 포인트인지는 미확인이다. 제거한 토큰은 비가역이므로 한도를 넘으면 재계산만 가능하다 | 전제 | 정확도 한도가 QS-1, 5의 합격 조건 | 사용자(GC-7), DP문서 | A §2.1, §9.4 |
| DP3-C-5 | "이 이득은 어떤 구성에서 성립하나?" | DP3의 이득은 **DP1 구성의 함수**다. 연산형 메모리(ScHBM, CXL-PNM)로 강등해도 KV를 그 자리에서 쓸 수 있으면 Drop의 필요성이 줄어든다. 따라서 연산형 계층의 용량을 sweep 축에 넣지 않은 결론은 그 구성에서만 유효하고, **B1(Demote-only)이 이미 용량 제약을 만족하면 DP3는 필요 없다**(실패가 아니라 결과) | 환경/전제 | 결과 보고에 DP1 Configuration 병기 필수 | DP문서 | A §2.2, §9.2, §9.6, §10 |
| DP3-C-6 | "Scheduler의 선점(preemption)과 뭐가 다른가?" | **Recompute 기반 선점도 KV를 버리고 재계산**하므로 DP3와 경쟁하는 교란 요인이다. 차이는 버릴 대상을 Attention Importance로 고르는가 request 단위로 고르는가뿐이다. 평가 조건은 선점 방식, prefix caching, 최대 동시 시퀀스, chunked prefill을 고정해야 한다 | 증거/조건 | Scheduler 고정 규칙 | DP문서 | A §9.6.1 |
| DP3-C-7 | "attention score는 어디서 얻나? 커널은?" | importance 산출은 **기존 LLM 생성 구조의 Attention Manager가 attention score를 제공**한다는 것을 전제한다. fused attention kernel은 score를 내보내지 않는 경우가 많으므로 **kernel·compiler 수정이 필요하면 프로젝트 범위 밖(GC-5)** 이다. 이 점은 문서에 명시되지 않은 **도출**이며 확인이 필요하다 | 전제/범위 밖(도출) | score 공급 방식이 구현 가능성을 정함 | 도출(GC-5) | B §2(Attention Manager 소속) |
| DP3-C-8 | "선택 재계산은 어떤 방법인가?" | 선택 재계산의 구체적 방법은 **이후에 정한다**(사용자). 현재 문서는 재계산 토큰 선정 결과가 Selective Recomputer로 전달된다는 **데이터 흐름만** 사용하며, 재계산 토큰 수의 가변성이 DP2 계약의 입력 크기를 정한다 | 범위(미결) | FR-03은 방법 비특정 | 사용자, DP문서 | B §0, §8-5 |
| DP3-C-9 | "압축률은 누가 정하나?" | 압축률(유지 비율)·Drop 비율 상한은 **정책 변수**이며 결정 주체가 미결이다. 이 변수가 Accuracy와 이득의 동작점을 만든다 | 미결 | 평가는 이 변수 sweep(iso-accuracy, iso-compression)로 보고 | DP문서 | B §8-6, A §9.6 |
| DP3-C-10 | "Comp.KV는 어디에 저장·식별되나?" | Comp.KV는 새로운 데이터 객체이고 **저장 위치와 이동은 DP1이 결정**한다(저장 위치는 어디든 가능, 사용자 설명). 식별 단위(Context 청크 키, 압축 기준 버전)와 갱신 정책은 미결이다. DP1-C1(Type-agnostic Registry)은 위치·크기만 관리하므로 이 메타데이터는 DP3 쪽에서 관리해야 한다 | 경계/미결 | DP1 Registry 설계와 연동 | DP문서 | B §5, §8-3 |
| DP3-C-11 | "평가는 어디까지 되어 있나?" | DP3는 **구현, 시뮬레이터, 평가 문서가 없다**(`Evaluation/DP3`는 TBD). 모든 내용은 구조 논증 [C]이며 문헌 [B]는 인용 전 원문 확인이 필요하고 수치는 인용하지 않는다(직접 확인한 것은 CacheBlend 초록뿐). 정확도는 실제 모델 실행으로 측정할 수 있지만(도출) 차세대 메모리 성능은 시뮬레이션(GC-1)이다 | 증거 한계 | 근거 수준을 결과에 병기 | DP문서, 사용자(GC-1) | B 부록 A, Evaluation/DP3 |
| DP3-C-12 | "두 문서는 어느 쪽이 현재 프레임인가?" | 원본 A(Drop/Demote 용량 압박 틀)와 초안 B(압축·재사용·선택 재계산 틀)는 **같은 압축 동작의 다른 각도**이지만 동기, 동작(2종 vs 압축 + 선택 재계산), 용어(Eviction 대 압축)가 다르다. B는 A를 수정하지 않았고 반영할 항목 목록(§7)을 갖고 있다. **DP3의 요구사항은 둘의 합집합**으로 읽었다 | 문서 불일치/확인 필요 | 문서 개정 후 FR 표 갱신 | DP문서 | B §1, §7 |
| DP3-C-13 | "서버 간(multi-node) KV 재사용은?" | DP3는 **인스턴스 안**의 KV 회수·재사용이다. 서버 간 요청 배분은 DP4, 서버 간 KV 공유는 DP6 범위다 | 범위 밖/경계 | — | 사용자(DP 번호), DP문서 | DP4 문서 |

프로젝트 공통 제약 중 DP3에 직접 걸리는 것: **GC-1**(차세대 메모리는 시뮬레이션), **GC-2**, **GC-3**, **GC-5**(attention kernel 수정은 범위 밖), **GC-6**, **GC-7(DP3는 예외)**, **GC-10**(KV 무효화 범위 밖).

## 6. 추적성 및 확인 사항

### 6.1 UC → DP3 FR → QS

| UC | DP3 FR | 품질 시나리오 |
|---|---|---|
| UC-2 long-context (HBM 초과, Drop 필수) | FR-01~08, 10 | QS-1~6 |
| UC-3 RAG 다중 문서 KV | FR-03, 04, C1-02 | QS-2, 5, 7 |
| UC-1 agent 다회 turn | FR-04, 08 | QS-2, 7 |

### 6.2 DP 간 비교를 위한 관찰 (통합 단계 입력)

| ID | 관찰 |
|---|---|
| X-3-1 | **DP3에는 평가 결과도 별점 기준도 없다.** DP1·DP2·DP4가 가진 "Baseline 대비 별 경계"를 DP3는 갖고 있지 않고 설계 문서가 "수치는 prototype 실측 후 확정, 가정값을 적지 않는다"고 했다. 통합 시 DP3는 새로 정하는 쪽이다 |
| X-3-2 | **기준선의 성격이 다르다.** DP3는 B0(전량 HBM)와 **B1(Demote-only)** 을 구분하고 B1을 기준선(=1.0)으로 쓴다. DP1(Baseline-static), DP2(Baseline-PD-fixed), DP4(정책 없는 기본 라우팅)와 서로 다른 Baseline이며, 특히 **DP3의 B1은 DP1 정책을 포함**한다 |
| X-3-3 | **Accuracy가 QA인 DP는 DP3뿐**(GC-7 예외). 허용 한도는 사용자 결정이 필요한 값이며 통합 단계의 핵심 미결 항목이다 |
| X-3-4 | DP3의 Resource utilization은 **DP1의 M-P6(HBM KV footprint)와 같은 정의를 쓰도록 설계 문서가 명시**한다(A §9.3). QA3 통합(별도 메모)의 근거로 쓸 수 있다 |
| X-3-5 | DP3는 Modifiability가 QA에 없다(PPT의 QA4 칸이 비어 있음). DP1·DP2·DP4는 모두 있다 |
| X-3-6 | 정확도는 실제 모델로 측정 가능하지만 이득(HBM 용량, I/O)은 메모리 구성에 의존해 **측정 방법이 둘로 나뉜다**(정확도 [A] 가능, 성능 [B+C]) |

### 6.3 사용자 확정이 필요한 점

| ID | 질문 | 현재 가정 |
|---|---|---|
| ~~Q-3-1~~ | **해소**: DP3 설계 문서는 B(압축·재사용·선택 재계산). A에서 온 항목은 보류 표시 | B 프레임 |
| Q-3-2 | **부분 해소**: 기준 = 압축 전 + full recompute 대비 F1 하락 1% 이내(사용자). **남은 확인**: "1%"가 상대 비율(F1이 0.80이면 0.792까지)인가 절대 포인트(1%p, 0.79까지)인가, 어떤 task·데이터셋의 F1인가 | 상대/절대 미정 |
| Q-3-3 | attention score를 어떻게 얻는가(기존 구조가 제공한다고 전제해도 되는가) | 제공됨(GC-5) |
| Q-3-4 | 추가 후보 QA(QA5~QA8) 채택 여부. 특히 Modifiability | QA5~QA8 권장, QA9 보류 |
| Q-3-5 | C1 오프라인 산출물 생성은 DP1과의 순서 규칙(DP1 먼저)의 예외인가 | 예외로 구분(미결) |
| Q-3-6 | C2의 압축 결과가 요청별인가 재사용 가능한가 | 요청별 추정 |
