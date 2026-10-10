# DP4 요구사항 도출: 기능 요구사항, 품질 속성, 품질 시나리오, 제약 사항

> 상태: **초안(제안)**. 2026-10-09 사용자 지시에 따라 **정량 임계값과 평가 결과(별점, 예상치)는 이 문서에 쓰지 않는다**. 품질 시나리오는 6요소를 채우되 응답 측정의 임계값은 `TBD(통합 단계)`로 둔다.
> DP 번호는 최종 번호([`project-context.md`](project-context.md) §0): **DP4 = 요청 조율 계층 구조**(옛 DP0, 폴더 `doc-mk/DP4/`). 사용자 지시로 `doc-mk/DP0-1/`(구조 S1/S2 비교)은 **무시**했다. 따라서 이 문서가 다루는 DP4는 기존 DP0 문서의 **후보 1(llm-d 등 OSS 확장) 대 후보 2(자체 구현)** 이다. 출처 표기: `DP문서` / `도출` / `사용자`.

## 0. 읽은 입력

| 구분 | 파일 | 읽은 범위 |
|---|---|---|
| 요구사항 | `DP4/dp0-requirements.md` (옛 DP0 요구사항: F1~F6, Q1~Q4, C1~C6, P1~P5) | 전체 (이전 작업 중) |
| 설계 | `DP4/dp0-request-orchestration-framework.md` (933줄) | 임원용 요약, §0~§4, §7(평가), §10 읽음. §5~§6(후보 구조 상세), §8~§9, §11~§12는 목차만 |
| 평가 슬라이드 | `DP4/DP0-qa-result-slides.pptx` (10장) | 텍스트 추출. 값(예상치)은 **치워 둠** |
| README | `DP4/README.md` | 전체 |
| **읽지 못함** | `DP0-slides.pptx`, `DP0-slides-v2.pptx`, `qa-model/modifiability_model.py`, llm-d/Dynamo 분석 문서(외부 저장소), §5~§6 상세 | 필요 시 읽음 |
| **무시** | `doc-mk/DP0-1/` (사용자 지시), `Evaluation/DP4/`(**옛 DP4 = 현 DP6의 평가 폴더**, 이름 변경 전) | — |

> 주의: DP4 문서의 본문은 아직 **옛 번호**(DP0, DP1~DP4)를 쓴다(예: "DP3 = 메모리 배치 추상화, DP4 = 연산 배치 스케줄링"). 최종 번호로 문서 개정이 필요하다.

## 1. DP4 구조 재구성

DP4는 **여러 vLLM 인스턴스(서버)를 묶어 요청을 어느 인스턴스가 처리할지 정하는 cluster-level 요청 조율 계층(Orchestration)** 이다. 경계는 물리 서버가 아니라 **vLLM 인스턴스**다. 인스턴스 안의 결정(batch, block, memory tier)은 node level이고 DP1~DP3의 범위다.

```text
Client ─► Orchestrator (cluster level)
            ├─ Substrate (A 요청 경로, F 발견·확장)
            ├─ State     (C KV index · worker 메트릭 · 이벤트)
            └─ Decision  (B filter·score·pick, D 흐름 제어, E P/D 조율)
              │ HTTP + kv_transfer_params          ▲ KV events(ZMQ), /metrics
              ▼                                    │
            vLLM 인스턴스들 (prefill / decode / aggregated)  ◄─ NIXL KV 전송 ─►
```

- **고정 전제**: Engine = vLLM, 경계 = vLLM 인스턴스, 요구 정책 = P1~P5, **불변 조건: 손실형 KV 전송이나 근사 캐시 hit를 도입하지 않는다**(정확도 보존).
- **설계 질문**: 이 계층(블록 A~F)을 OSS(llm-d, NVIDIA Dynamo)를 **확장해 구성**할 것인가(후보 1), **우리가 decision plane과 state plane을 소유하는 자체 구현**으로 구성할 것인가(후보 2). 성능 관점 질문은 "이기종 메모리의 node level 이득이 cluster level 결정에서 **보존**되는가(입력 해상도, 출력 해상도, 지연·신선도)"이다.
- **접점 계약(vLLM)**: KV events(`BlockStored`/`BlockRemoved`, `medium` 필드), `/metrics`, `kv_transfer_params`(P/D 시 원격 KV 위치, `max_load_tokens`, `kv_load_tiers`), NIXL KV 전송.
- 후보 1은 정책 P1~P4를 설정과 확장 모듈로 **합성 백엔드 끝단에서 실행 확인**했다[A]. 나머지(실제 vLLM end-to-end, 지연, 확장성)는 미측정이며 후보 간 우열은 모두 가설이다.

## 2. 기능 요구사항 (DP4-FR)

기존 `dp0-requirements.md`의 F1~F6과 정책 P1~P5를 DP4 ID로 옮기고, 요청 경로(블록 A)와 정확도 불변을 요구사항 문장으로 추가했다. OSS 기본 제공 여부는 원문 표를 참조한다.

### 2.1 공통 (후보 1, 후보 2)

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP4-FR-01 (F1) | 시스템은 들어온 요청을 어느 vLLM 인스턴스가 처리할지 고른다. 서버별로 **KV 캐시가 어느 메모리 tier에 있는지**와 **부하**를 반영한다 | DP문서 dp0-requirements §2 F1 | 블록 B 결정 로직(Filter→Score→Pick) | UC-1, 3, 4 | 합성 백엔드로 EPP 끝단 실행 [A], 실제 vLLM end-to-end는 E4 | 문서 확정 |
| DP4-FR-02 (F2) | 시스템은 각 서버에서 올라오는 **KV 보유 위치(메모리 종류) 이벤트**와 **메모리 사용량·전송 대기 같은 실시간 수치**를 수집해 결정의 입력으로 쓴다. **새 메모리 종류(CXL, HBF 등)를 구분**할 수 있어야 한다 | dp0-requirements §2 F2 | 블록 C 상태 수집 | UC-1, 3, 9 | P1·P2 설정으로 새 메모리 이름·수치 반영 [A], 상태 신선도 E3 | 문서 확정 |
| DP4-FR-03 (F3) | 시스템은 요청마다 **Prefill/Decode 분리 실행 여부와 Prefill 위치를 정하고** 서버 간 KV 전송(NIXL) 정보를 전달·조율한다 | dp0-requirements §2 F3 | 블록 B, E P/D 조율 | UC-8 | P4 wrapper 끝단 실행 [A], 실제 NIXL 전송은 E4 | 문서 확정 |
| DP4-FR-04 (F4) | 시스템은 요청마다 서버에 **메모리 사용 지시**(어느 메모리에서 몇 토큰까지 불러올지: `kv_load_tiers`, `max_load_tokens`)를 내려보낸다. 지시의 수신·실행은 vLLM(엔진) 쪽이다 | dp0-requirements §2 F4, 설계 §4.2 | 블록 E | UC-1 | aggregated 경로 body 변경 확인 [A], P/D 경로는 코드 분석 [C], 실제 효과 미확인 | 문서 확정 |
| DP4-FR-05 (F5) | 시스템은 과부하일 때 요청을 **대기·우선순위·거절**로 조절해 SLO를 지킨다 | dp0-requirements §2 F5 | 블록 D 흐름 제어 | UC-9 | 기능 존재 확인 [C], 효과는 E4 | 문서 확정 |
| DP4-FR-06 (F6) | 시스템은 서버(인스턴스)가 추가·제거되면 **자동으로 알아채고** 요청 대상에 반영한다 | dp0-requirements §2 F6 | 블록 F 발견·확장 | UC-9 | file-discovery로 EPP 기동 [A], 실제 확장은 미확인 | 문서 확정 |
| DP4-FR-07 | 시스템은 클라이언트 요청(OpenAI API)을 수신해 선택한 인스턴스로 전달하고 응답을 중계한다(모든 F의 전제) | dp0-requirements §1 블록 A, 설계 §4 | 블록 A 요청 경로 | 전체 | 요청 중계 단위 테스트 | 문서 확정(전제) |
| DP4-FR-08 (P1) | 시스템은 **새 메모리 종류를 캐시 적중 점수에 반영**한다. 캐시가 HBM/DRAM/CXL/SSD 중 어디에 있는지에 따라 가중치를 다르게 준다(가중치 표) | dp0-requirements §5 P1 | Score 정책 | UC-1, 3 | 설정 확인 [A] | 문서 확정 |
| DP4-FR-09 (P2) | 시스템은 **실시간 메모리 상태**(서버가 알려 주는 메모리 사용량·전송 대기)를 읽어 점수에 가감한다 | P2 | Score 정책 + customMetrics | UC-9 | 설정 확인 [A] | 문서 확정 |
| DP4-FR-10 (P3) | 시스템은 **비용 기반 적중 점수**를 낸다(KV 재계산 비용과 해당 메모리에서 가져오는 비용을 비교, 점유율이 높으면 감점) | P3 | Scorer 확장 모듈 | UC-1, 3 | 끝단 실행 [A] | 문서 확정 |
| DP4-FR-11 (P4) | 시스템은 **비용 기반 P/D 분리 판단**을 한다(분리 여부, Prefill 위치) | P4 | ProfileHandler wrapper | UC-8 | wrapper 끝단 실행 [A] | 문서 확정 |
| DP4-FR-12 (P5) | 시스템은 **요청별 노드 지시를 계산하고 `kv_transfer_params`에 첨부**해 보낸다. 지시 수신은 vLLM이며 사용자 fork에는 아직 수신부가 없다 | P5, 설계 §4.2 | 블록 E | UC-1 | 일반 경로 확인 [A], P/D 경로 [C] | 문서 확정 |
| DP4-FR-13 | 시스템은 어떤 구성에서도 **손실형 KV 전송이나 근사 캐시 hit를 도입하지 않고** 모델 출력이 같아야 한다 | 사용자(GC-7), dp0-requirements C3 | 불변 조건 | 전체 | 출력 비교 | 문서 확정 |
| DP4-FR-14 | 시스템은 결정(서버 선택, P/D 판단, 지시)의 **근거를 기록**해 관측 가능해야 한다 | 도출(DP4 문서에 명시 없음) | Observability | 전체 | 로그 필드 | 제안 |

### 2.2 후보 1 (OSS 확장, llm-d 대표) 특화

| ID | 요구사항 | 출처 | 상태 |
|---|---|---|---|
| DP4-FR-C1-01 | 새 메모리 종류 가중치와 상태 수치 이름은 **설정만**으로 추가하고, 비용 기반 점수·P/D 판단은 **확장 모듈(plugin, wrapper)** 로 추가한다. P/D 경로의 P5는 **기존 보조 프로세스(pd-sidecar) 수정**이 필요하다 | dp0-requirements §5, 설계 §7.3 | 문서 확정 |
| DP4-FR-C1-02 | 시스템은 Kubernetes 위에서 InferencePool로 서버 발견·확장·흐름 제어(OSS 제공)를 사용하고 자체 EPP 이미지를 빌드·배포·추종한다 | 설계 §7.4, §10.3 | 문서 확정 |

### 2.3 후보 2 (자체 구현) 특화

| ID | 요구사항 | 출처 | 상태 |
|---|---|---|---|
| DP4-FR-C2-01 | 시스템은 decision plane과 state plane을 직접 소유하고, 정책을 **Strategy**(ScoreStrategy, PDPlanStrategy)와 **Decorator**(지시 구성)로 구현한다 | 설계 §6.3, DP0 슬라이드 2장 | 문서 확정 |
| DP4-FR-C2-02 | 시스템은 Router 레플리카, 로드밸런서, HA, 상태 저장소(etcd 등), 흐름 제어를 직접 구축한다. 레플리카가 상태를 공유하지 않아 각 레플리카가 전체 이벤트·메트릭을 처리하는 구조이며 서버 샤딩은 보완안(가설)이다 | 설계 §6.3, §7.4 | 문서 확정(구현량은 추정) |

### 2.4 과제 UC와 DP4의 관계 (`usecases.md` FR과 대조)

| 과제 FR | DP4가 담당하는 부분 | DP4가 담당하지 않는 부분 |
|---|---|---|
| FR-1, 3 (UC-1 세션 재개, 재사용), FR-10 (UC-3 RAG) | **서버 선택**: 재방문 요청을 KV(또는 문서 prefix)를 보유한 서버로 라우팅(DP4-FR-01, 02, 08, 10) | 서버 내부 Tier 이동(DP1), 압축 KV 재사용(DP3) |
| FR-13 (UC-4 LoRA adapter 보유 서버 선택) | 서버 선택 시 adapter 보유 상태 반영 가능(상태 수집 확장). 현재 DP4 문서는 LoRA를 명시하지 않음(도출) | adapter 이동·복제는 DP1 |
| FR-24, 25 (UC-8 P/D 분리) | **분리 여부와 Prefill 서버 결정, 서버 간 KV 전송 정보 전달**(DP4-FR-03, 11) | **DP2와 책임이 겹친다**(§5 DP4-C-3). DP2는 Turn 단위로 (n_p, n_d)를 정하고 DP4의 P4는 cluster 성분(pod 선택, P/D 결정)을 맡는다는 구분이 문서에 있지만 경계가 명확하지 않다 |
| FR-21~23 (UC-7 노드 간 KV 이동) | 서버 선택·P/D 조율에 노드 간 전송 비용 반영 | 비일관 CXL 공유 메모리의 일관성은 **DP6** |
| FR-26~28 (UC-9 혼합 부하) | **흐름 제어**(admission, 우선순위, 거절), 서버 발견·확장(DP4-FR-05, 06) | — |
| FR-6 (출력 불변) | DP4-FR-13 | — |

## 3. 품질 속성 (QA)

### 3.1 (a) DP4가 선정한 QA

DP4 문서는 과제 QA 목록(Throughput, Latency, Resource Utilization, Functional Correctness, Modifiability, Scalability) 중 **4개를 선정**했다(설계 §7.1~7.2, 요구사항 §3). 이름·지표는 원문을 따르고 **별 경계와 예상치는 쓰지 않는다**.

| ID | QA | metric (원문) | ISO/IEC 25010:2023 매핑 | 출처 |
|---|---|---|---|---|
| DP4-QA1 (Q1) | Throughput | **Max SLO Goodput**(서비스 목표(SLO)를 지키면서 낼 수 있는 최대 처리량, output token/s) | Performance efficiency > Capacity | 요구사항 §3.1, 설계 §7.1 |
| DP4-QA2 (Q2) | Latency | **TTFT** P50/P99, 그중 **결정 경로가 더하는 시간**("null 결정" 대비 증분), **TPOT 악화 여부**. 설계 §7.1은 TTFT만, 요구사항 §3.1은 TPOT 악화 없음을 포함 | Performance efficiency > Time behavior | 요구사항 §3.1, 설계 §7.1 |
| DP4-QA3 (Q3) | Modifiability(변경·유지 용이성) | 변경 시나리오 **S1~S6**(새 tier 매체 추가, 비용 함수 교체, P/D 결정 정책 교체, 노드 지시 추가, vLLM·NIXL 계약 변경 대응, 신규 기능)에서 **변경 module 수, 개발 공수(man-day), 에이전트 토큰 비용($)**. 우선순위는 비용 > 공수 > module 수(소유자 결정) | Maintainability > Modifiability(+ Modularity). S5·S6는 Compatibility > Interoperability(upstream·계약 추종)와 일부 겹침 | 요구사항 §3.1, 설계 §7.3, 슬라이드 |
| DP4-QA4 (Q4) | Scalability | **Scaling Efficiency SE(N)** = Goodput(N) ÷ ((N / N0) × Goodput(N0)) (과제 공통 정의), 조율 계층이 병목이 되는 시점 | Flexibility > Scalability | 요구사항 §3.1, 설계 §7.1 |

QA 우선순위(소유자 확정, 설계 §7.4.4): Q1 Throughput > Q2 Latency > Q3 Modifiability > Q4 Scalability.

**DP4가 제외한 QA와 사유**(설계 §7.2, 요구사항 §3.3):
- **Resource Utilization**: 활용률은 라우팅 품질의 결과로 Throughput과 같은 원인에서 나오므로 독립 판별력이 없고, 조율 계층 자체의 CPU 소비는 무시할 수 있다. 측정 로그로만 남긴다.
- **Functional Correctness**(AI 모델 정확도): orchestrator는 같은 모델·가중치로 요청만 나르고 KV 재사용·전송은 비손실이므로 후보 간 차이가 없다. QA가 아니라 **제약**(C3)으로 처리한다.

### 3.2 (b) 추가 후보 QA (ISO/IEC 25010:2023 목록 안)

| ID | ISO 특성 > 하위 특성 | 후보 | 관련 이유 | 미선정 시 위험 | 선정 QA와의 관계 | 의견 |
|---|---|---|---|---|---|---|
| DP4-QA5 | Compatibility > Interoperability | vLLM 접점 계약(KV events의 `medium`, `/metrics`, `kv_transfer_params`, NIXL)과 업스트림 변화 대응 | 제약 C4(업스트림 추적), C5(접점 계약 고정). 설계 리스크: upstream 중복, 사용자 fork가 upstream보다 뒤처짐, 확장 모듈이 OSS 내부 동작에 의존 | 업스트림이 바뀔 때 조용히 깨짐(wrapper가 `disagg.Handler` 관찰 동작에 의존) | QA3 Modifiability의 S5와 겹침 | **권장** |
| DP4-QA6 | Performance efficiency > Time behavior | **상태 신선도**(KV 이벤트→색인 지연, 낡은 캐시 적중 비율) | 요구사항 §3.2의 E3 실험. 결정의 입력 해상도가 낮거나 낡으면 이기종 메모리 이득을 점수에 반영할 수 없음(F2의 존재 이유) | 낡은 상태로 오라우팅해 캐시 이득이 사라짐 | QA2(TTFT)의 원인 변수 | **권장** |
| DP4-QA7 | Reliability > Fault tolerance, Recoverability, Availability | orchestrator 장애(레플리카, 상태 stale, KV 이벤트 유실)와 서버 장애 시 fallback | 설계 §7.2가 "fail-open/close 같은 장애 규약은 정확도가 아니라 가용성이라 QA 목록 밖"이라고 명시. 후보 2는 레플리카·HA를 직접 구축. **device runtime 내부 오류·복구는 GC-3으로 제외, 우리 계층(조율 계층)의 degradation 처리만 후보**(GC-6: 장애 복구 자체는 범위 밖) | 조율 계층 장애가 전체 서비스 중단으로 이어짐 | QA1·QA4와 연계 | **권장** |
| DP4-QA8 | Functional suitability > Functional correctness | 라우팅·P/D 짝짓기·`kv_transfer_params` 정합(요청이 의도한 서버로 가고, 원격 KV 위치가 정확) | 정확도 불변은 제약으로 두었으나(DP4-FR-13) **정합성 오류는 정확도와 별개** | 잘못된 서버로 전달되거나 KV 위치가 어긋나 실패 | 사전 조건 성격 | **보류**(검증 시나리오는 제약 검증으로 편입 가능) |
| DP4-QA9 | Maintainability > Analysability | 결정 근거 기록·진단 | DP4-FR-14. 후보 간 비교와 실험(E1~E4) 해석에 필수 | 결정이 틀린 이유를 알 수 없음 | 모든 QA의 검증 수단 | **권장** |
| DP4-QA10 | Performance efficiency > Resource utilization | 서버 간 부하 균형 | 설계가 제외(Throughput과 같은 원인). 단 DP2의 "P/D 풀 사용률"과 같은 계열의 논점 | — | QA1의 원인 변수 | **보류**(DP4 입장 유지. QA3 통합 메모 참고) |
| (제외) | Security, Interaction capability, Safety | — | GC-6, UI 없음 | — | — | 제외/해당 없음 |

## 4. 품질 시나리오 (6요소, 정량 임계값 없음)

> 응답 측정은 `metric / 통계량 / 비교 기준 / 측정 조건`까지 쓰고 **임계값은 `TBD(통합 단계)`** 다. 평가 결과(예상치)는 쓰지 않는다. 실험 환경 제약(서버 2대, 차세대 메모리는 시뮬레이션)은 제약 절에 있다.

#### DP4-QS-1 Capacity — 캐시 재사용 요청이 많은 상황의 SLO Goodput (선정, DP4-QA1 · ISO: Capacity)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 클라이언트(요청 생성기): 같은 대화·문서 prefix를 반복하는 요청이 지속 유입 |
| 2. 자극 | 캐시 재사용률이 변하는 요청(재사용 없음~높음)과 긴 입력 요청이 섞여 유입, 요청률을 SLO가 깨지기 직전까지 올림(load sweep) |
| 3. 환경 | 정상 운전, **메모리 종류가 섞인 추론 서버 ≥ 2대**, 시스템 프로파일은 통합 단계에서 정렬, 같은 seed·부하로 Baseline과 짝지음 |
| 4. 자극 대상체 | 요청 조율 계층의 결정 로직과 상태 수집(블록 B, C) |
| 5. 응답 | 이기종 메모리 상태(P1~P3)를 반영해 KV를 보유한 서버로 요청을 보내고 SLO를 지킨다 |
| 6. 응답 측정 | **Max SLO Goodput**(SLO를 위반한 요청의 토큰을 뺀 output tok/s의 load sweep 최대값)을 **Baseline(정책 없는 기본 라우팅) 대비**로 보고, seed ≥ 5, 95% CI. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA1(Q1). UC-1, 3. FR: DP4-FR-01, 02, 08~10 |

#### DP4-QS-2 Time behavior — 결정 경로가 더하는 지연 (선정, DP4-QA2 · ISO: Time behavior)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 클라이언트 |
| 2. 자극 | 요청 1건이 도착해 서버가 선택되는 순간. 부하 수준별(저·중·고)과 Prefill/Decode 분리 경로 |
| 3. 환경 | 정상 운전, 서버 ≥ 2대 |
| 4. 자극 대상체 | 요청 조율 계층의 결정 경로(블록 A, B, 원격 호출 포함, P/D 경로의 보조 프로세스 경유) |
| 5. 응답 | 결정을 내려 요청을 서버로 전달하며 **결정 경로가 더하는 시간이 TTFT에 드러나지 않을 만큼 작다** |
| 6. 응답 측정 | **TTFT P50/P99**, 그중 **결정 경로 추가 시간**(결정을 비운 "null 결정" 대비 증분, E1), **TPOT 악화 여부**(TTFT와 TPOT를 분리 보고). Baseline 대비. 후보 1(원격 호출 1회 hop)과 후보 2(단일 프로세스) 비교. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA2(Q2). UC-8. FR: DP4-FR-01, 03, 11. 제약: DP4-C-7 |

#### DP4-QS-3 Modifiability — 변경 시나리오 S1~S6 (선정, DP4-QA3 · ISO: Modifiability, Modularity, Interoperability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 개발자(우리 팀). S5는 업스트림(vLLM, NIXL, llm-d)의 변경 |
| 2. 자극 | S1 새 tier 매체 추가, S2 cost 함수 교체, S3 P/D 결정 정책 교체, S4 node 지시 추가, S5 vLLM·NIXL 계약 변경 대응, S6 신규 기능(흐름 제어 고도화, multi-cluster 등) |
| 3. 환경 | 개발 시점, OSS 업스트림이 계속 변경되는 중, 변경은 에이전트 세션 모델로 환산(시뮬레이션 [C]) |
| 4. 자극 대상체 | 요청 조율 계층의 코드·설정. 후보 1은 설정, 외부 plugin, wrapper, 보조 프로세스, 후보 2는 Strategy/Decorator 구현체 |
| 5. 응답 | 기존 구조를 바꾸지 않고 설정·확장 모듈(후보 1) 또는 구현체 교체(후보 2)로 반영한다 |
| 6. 응답 측정 | 시나리오별 **변경 module 수, 개발 공수(man-day 또는 man-month), 에이전트 토큰 비용($)**, 외부(OSS) 코드 수정 여부, 재배포 필요 여부. 시나리오 집계 방식(가중, 평균)은 통합 단계에서 DP1·DP2와 맞춤. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA3(Q3). FR: DP4-FR-08~12, C1-01, C2-01. 평가: 설계 §7.3 |

#### DP4-QS-4 Scalability — 서버·노드 증설 (선정, DP4-QA4 · ISO: Scalability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 운영자와 클라이언트(요청률 증가) |
| 2. 자극 | 서버 수 N을 N0의 배수로 늘리고 서버당 부하를 고정(서버 N배, 요청률 N배) |
| 3. 환경 | 정상 운전, **실환경은 서버 2대라 N > 2는 모델 외삽**(시뮬레이션) |
| 4. 자극 대상체 | 요청 조율 계층 전체(블록 A~F): 후보 1은 K8s 복제·서버 풀·흐름 제어, 후보 2는 레플리카·LB·HA·상태 동기 |
| 5. 응답 | 조율 계층이 병목이 되지 않고 선형에 가깝게 확장한다 |
| 6. 응답 측정 | **Scaling Efficiency SE(N) = Goodput(N) ÷ ((N / N0) × Goodput(N0))** (N0 = 보유 환경의 기준 서버 수), **조율 계층이 병목이 되는 시점**, 레플리카당 이벤트·메트릭 처리 부하의 증가율. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA4(Q4). UC-9. FR: DP4-FR-05, 06, C2-02. 제약: DP4-C-4 |

### 4.2 추가 후보 QA (채택 전 초안)

#### DP4-QS-5 Interoperability — vLLM 접점 계약과 업스트림 변경 (추가, DP4-QA5 · ISO: Interoperability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 업스트림 vLLM / llm-d / Dynamo의 릴리스 |
| 2. 자극 | KV event schema(`medium` enum), `/metrics` 이름, `kv_transfer_params` 키, NIXL 동작이 바뀜 |
| 3. 환경 | 개발·운영, 사용자 fork가 upstream보다 뒤처진 상태 |
| 4. 자극 대상체 | 접점 계약 어댑터, 후보 1의 확장 모듈·wrapper·보조 프로세스 수정분, 후보 2의 State Plane·Dispatcher |
| 5. 응답 | 계약 변경을 흡수·추종하고 깨지면 조기에 탐지되며 서비스를 이어 간다 |
| 6. 응답 측정 | 변경 대응에 필요한 **module 수·재검증 횟수**, 호환성 깨짐을 **탐지하기까지의 시간 또는 탐지율**(통합 테스트 커버), 업스트림 추종 주기. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA5. FR: DP4-FR-02, 04, 12. 제약: DP4-C-5, 6 |

#### DP4-QS-6 Time behavior — 상태 신선도 (추가, DP4-QA6 · ISO: Time behavior)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | vLLM 인스턴스(KV event, 메트릭 발행) |
| 2. 자극 | 블록 저장·삭제 이벤트와 메모리 사용량이 높은 빈도로 변함 |
| 3. 환경 | 정상 운전, 서버 수 증가, 후보 2는 레플리카가 상태를 공유하지 않음 |
| 4. 자극 대상체 | 상태 수집(블록 C): KV indexer, 메트릭 수집, 이벤트 plane |
| 5. 응답 | 결정에 쓰는 상태가 실제 상태를 충분히 빠르게 반영한다 |
| 6. 응답 측정 | **이벤트 발생→색인 반영 지연**(p50/p99), **낡은 캐시 적중 비율**(점수는 hit였는데 실제로는 없는 비율). 서버 수·이벤트율별. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA6. FR: DP4-FR-02. 평가: 요구사항 E3 |

#### DP4-QS-7 Fault tolerance — 조율 계층·서버 장애 시 degradation (추가, DP4-QA7 · ISO: Reliability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | orchestrator 프로세스·레플리카 중단, KV 이벤트 유실, 서버(인스턴스) 이탈 |
| 2. 자극 | 상태 수집 경로가 끊기거나 지연, 후보 서버 중 일부가 사라짐 |
| 3. 환경 | 정상 운전 중 장애 발생. device runtime 장치 오류는 제외(GC-3), 장애 복구 자체는 범위 밖(GC-6) |
| 4. 자극 대상체 | 상태 수집, 결정 로직, 서버 발견(블록 C, B, F), 레플리카·HA |
| 5. 응답 | 부하 기반 단순 라우팅 등 **안전한 경로로 degrade**하고 요청을 계속 처리하며, 서버 이탈을 반영한다 |
| 6. 응답 측정 | degrade 중 **SLO Goodput의 Baseline 대비 비율**, 요청 실패 수, **degrade 전환 시간**, 서버 이탈 반영 지연. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA7. UC-9. FR: DP4-FR-02, 06, C2-02 |

#### DP4-QS-8 Analysability — 결정 근거 추적 (추가, DP4-QA9 · ISO: Analysability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 개발자(성능 저하 원인 분석) |
| 2. 자극 | 같은 prefix 요청이 캐시가 없는 서버로 가는 사례 발견 |
| 3. 환경 | 운영·평가 중, 결정 로그 활성 |
| 4. 자극 대상체 | 결정 근거 기록(점수 항목별 기여, 입력 상태 snapshot, P/D 판단, 지시 내용) |
| 5. 응답 | 선택된 서버의 점수 구성, 사용한 상태의 시각, 지시 내용을 남겨 원인을 분류할 수 있다 |
| 6. 응답 측정 | 결정 로그 **필수 필드 완비율**, 결정마다 입력 상태의 수집 시각 기록 여부. **임계값: TBD(통합 단계)** |
| 연결 | QA: DP4-QA9. FR: DP4-FR-14 |

## 5. 제약 사항 (예상 질문 기반)

원본 `dp0-requirements.md`의 C1~C6을 예상 질문 형식으로 옮기고, 설계 문서에서 도출한 항목을 더했다.

| ID | 예상 질문 | 제약 문장 | 유형 | 설계 영향 | 출처 | 근거 위치 |
|---|---|---|---|---|---|---|
| DP4-C-1 | "엔진을 바꾸면?" | **추론 엔진은 vLLM으로 고정**이다. 다른 엔진 대응은 비교 대상이 아니다 | 전제 | 조율 계층은 vLLM 접점(KV 이벤트, `/metrics`, `kv_transfer_params`, NIXL)에 맞춤 | DP문서 | 요구사항 C1 |
| DP4-C-2 | "실험은 어디까지 되나? 서버 몇 대인가?" | 실험 환경은 **GPU 8장 서버 2대(총 16 GPU)**, Kubernetes 숙련도가 낮고, **서버 간 연결은 PCIe 64 GB/s**(사용자 확인, GC-9)이며 RDMA/NIC 종류는 미확인이다. 기존 DP4 문서는 "RDMA 유무 미확인, 400 Gb/s ≈ 50 GB/s 가정"으로 쓰고 있어 **값이 다르다** | 환경 | Scalability(N > 2)는 실측 불가이므로 시뮬레이션, K8s 학습 비용이 실질 비용, P/D 전송 성능은 연결 방식에 좌우 | DP문서, 사용자(GC-9) | 요구사항 C2, 슬라이드 5장 |
| DP4-C-3 | "DP2와 뭐가 다른가? P/D 판단은 누가 하나?" | DP4의 **P4(비용 기반 P/D 분리 판단, Prefill 서버 결정)** 와 DP2(Turn 단위 (n_p, n_d) 비용 기반 결정)는 **같은 비용 기반 결정을 다룬다**. 설계 문서는 "Prefill 실행 위치는 cluster 성분(pod 선택, P/D 결정 = P4)과 node 성분(인스턴스 내부 resource 선택)으로 나뉜다"고만 적었고 경계가 명확하지 않다. 구현 프레임워크 매핑은 DP2 범위 밖이므로 llm-d 위에서의 실행은 DP4의 P4, P5가 맡는다 | 경계(미정) | DP2·DP4의 결정 주체와 정보 흐름을 통합 단계에서 정리해야 함 | DP문서 | 설계 §10.1, DP2 문서 §11 |
| DP4-C-4 | "서버를 늘리면 확장되나? 실측했나?" | 2노드로는 **확장성 실측이 불가**하며 N > 2는 모델 외삽이다. 후보 2의 레플리카 상태 비공유 구조의 확장성 가설(레플리카당 갱신 부하 ∝ N)은 검증되지 않았다 | 환경/증거 한계 | Scalability 결과는 가설 [C] | DP문서 | 요구사항 C2, 설계 §7.4 |
| DP4-C-5 | "OSS가 바뀌면?" | **오픈소스 업스트림을 추적할 수 있어야 한다**. 포크를 최소화하고 공개 확장 지점(설정, plugin) 위주로 구현한다. 후보 1은 확장 모듈이 OSS 내부 동작에 의존하고(호환성 약속 미확인) 자체 EPP 이미지(Go)의 빌드·배포·추종이 우리 몫이다 | 전제/리스크 | 후보 1: 설정 > 확장 모듈 > 기존 모듈 수정 순 선호 | DP문서 | 요구사항 C4, 설계 §10.3 |
| DP4-C-6 | "서버 내부 설계(DP1~DP3)와의 접점은?" | **접점 계약(KV 이벤트의 `medium` 필드, 메트릭, `kv_transfer_params`, NIXL)** 을 고정한다. 새 메모리 종류를 KV 이벤트에 싣는 것(현재 `Medium` enum은 CPU/STORAGE뿐)과 P5 지시 수신부는 **vLLM 변경이 필요한 공통 선결**이다. 사용자 fork에는 `kv_load_tiers`/`max_load_tokens`가 없고 upstream보다 크게 뒤처져 있어 동기화 결정이 필요하다 | 경계/전제 | DP1~DP3와 병렬 진행 가능, 단 fork 동기화가 선결 | DP문서 | 요구사항 C5, 설계 §4.2, §10.2 |
| DP4-C-7 | "P5는 실제로 효과가 있나?" | `kv_load_tiers`/`max_load_tokens`가 vLLM에서 **실제로 메모리 선택을 바꾸는 효과는 미확인**이다(`max_*`는 experimental). P/D 경로의 P5는 후보 1에서 보조 프로세스 수정이 필요하고 후보 2에서는 Directive Builder 한 곳이다 | 증거 한계 | 후보 2의 P/D 경로 이점과 S4 이점이 이 미확인에 의존 | DP문서 | 설계 §7.3~7.4, §10.4 |
| DP4-C-8 | "정책 5개를 다 표현할 수 있어야 하나?" | **정책 P1~P5를 모두 표현할 수 있어야** 한다. 표현이 막히면 서버 내부에서 얻은 성능 이득이 서버 간 배분 단계에서 사라진다. 후보 1은 P1~P4를 설정·확장 모듈로 표현 [A], P5의 P/D 경로만 기존 모듈 수정 [C] | 전제 | 후보의 필수 조건 | DP문서 | 요구사항 C6 |
| DP4-C-9 | "이 평가는 실제 시스템인가?" | 후보 1의 P1~P4 확인은 **합성 백엔드**에서의 끝단 실행이며 **실제 vLLM end-to-end는 아니다**. Dynamo는 코드·문서 읽기 기반이고 Rust 빌드를 하지 않았다. 지연(E1), 상태 신선도(E3), end-to-end Goodput(E4)은 **미수행**이다 | 증거 한계 | 후보 간 우열은 전부 가설 | DP문서 | 요구사항 §8, 설계 §9 |
| DP4-C-10 | "후보 2는 구현했나?" | 후보 2(자체 구현)는 **설계안이며 미구현**이고 구현량(블록 6/6, 레플리카·HA·흐름 제어)은 추정이다. 후보 2 선택은 아직 증명되지 않은 가설(특히 Latency)에 의존한다. 후보 1이 되돌아갈 경로(fallback)로 유지된다 | 증거 한계 | 선택 게이트 E1 | DP문서 | 설계 §7.4.3~7.4.4 |
| DP4-C-11 | "정확도는?" | 모델 정확도는 **불변**이다(KV 전송·재사용은 비손실, 손실형 압축·근사 hit 금지). Functional Correctness는 QA가 아니라 제약으로 둔다. 프로젝트의 GC-7과 같다 | 전제 | — | 사용자(GC-7), DP문서 | 요구사항 C3 |
| DP4-C-12 | "과부하·장애 처리와 서버 증설은 어디까지?" | 흐름 제어와 서버 발견·확장은 기능이지만 **장애 복구 자체는 프로젝트 범위 밖**(GC-6)이고 device runtime 오류는 GC-3으로 제외한다. 조율 계층의 degradation 처리만 후보 QA다 | 범위 밖/경계 | HA·레플리카 설계는 구현 부담으로만 다룸 | 사용자(GC-3, GC-6) | 설계 §7.2 |
| DP4-C-13 | "서버 간 KV 공유(공유 메모리)는?" | **비일관 CXL 공유 메모리에서 서버 간 KV 일관성을 보장하는 구조는 DP6** 소관이다. DP4는 요청을 서버로 배분하고 P/D KV 전송(NIXL) 정보를 조율하는 데까지다 | 범위 밖/경계 | DP4↔DP6 접점 계약 필요 | 사용자(DP 번호), 도출 | project-context §0 |
| DP4-C-14 | "문서는 최종 번호인가?" | DP4 문서 본문과 `DP0-slides*.pptx`는 **옛 DP 번호(DP0, DP3 = 메모리 배치 추상화, DP4 = 연산 배치)** 를 쓴다. 최종 번호(DP1 migration, DP2 P/D, DP3 KV eviction/reuse, DP4 요청 조율, DP6 CXL 공유 메모리 일관성)로 개정이 필요하다 | 문서 불일치 | 문서 개정 | 사용자(DP 번호) | DP4 문서 §0 |

프로젝트 공통 제약 중 DP4에 직접 걸리는 것: **GC-1**(차세대 메모리는 시뮬레이션), **GC-2**, **GC-3**, **GC-5**, **GC-6**, **GC-7**, **GC-9**(서버 간 PCIe 64 GB/s, DP4-C-2).

## 6. 추적성 및 확인 사항

### 6.1 UC → DP4 FR → QS

| UC | DP4 FR | 품질 시나리오 |
|---|---|---|
| UC-1 세션 재개, UC-3 RAG | FR-01, 02, 08~10, 12 | QS-1, 6, 8 |
| UC-4 LoRA 멀티 테넌트 | FR-01, 02 (adapter 보유 상태 반영은 도출) | QS-1 |
| UC-7 노드 간 KV 이동 | FR-01, 03 | QS-1, 2 |
| UC-8 P/D 분리 | FR-03, 11, 12 | QS-2 |
| UC-9 혼합 부하 | FR-05, 06 | QS-1, 4, 7 |
| 전체(개발 관점) | FR-08~12 | QS-3, 5 |

### 6.2 DP 간 비교를 위한 관찰 (통합 단계 입력)

| ID | 관찰 |
|---|---|
| X-4-1 | **평가 환경의 성격이 다르다.** DP4는 평가를 **보유 시스템(H100 SXM x8, 2노드 16 GPU)에서 Baseline을 실측하고 실물이 없는 메모리와 후보 2만 시뮬레이터로 연동**하는 절차로 계획했다([A]+[C], 모든 값은 예상치·미실행). DP1·DP2는 SYS-H100/B200 **순수 시뮬레이션**이다. 서버 2대와 PCIe 64 GB/s는 사용자 확인 사항이라 DP2의 RDMA 50 GB/s(ASSUMED)와도 다르다 |
| X-4-2 | **Baseline이 다르다.** DP4 = 정책 없는 기본 라우팅(상태·캐시 비인지), DP1 = Baseline-static(migration 없음), DP2 = Baseline-PD-fixed, DP3 = B0/B1. 같은 "Baseline 대비 배수"가 다른 개선을 뜻한다 |
| X-4-3 | **QA 선정이 다르다.** DP4는 Resource Utilization을 제외하고 Latency를 TTFT 중심으로 정의(TPOT은 악화 여부), DP1·DP2는 TTFT와 TPOT를 모두 별도 보고한다 |
| X-4-4 | **Modifiability(Q3) 정의가 DP1·DP2와 다르다.** DP4는 세 sub-metric(토큰 비용, 공수, module 수)에 **우선순위 규칙(비용 > 공수 > module)** 을 두고 별 결정이 비용 기준이다. DP1·DP2는 같은 세 sub-metric에 **중앙값 규칙**을 쓴다. 시나리오 수는 DP4 S1~S6(가중 포함), DP1·DP2 4개(평균) |
| X-4-5 | **Scalability 정의가 다르다.** DP4 SE(N) = Goodput(N) ÷ ((N/N0) × Goodput(N0)), N0 = 2 노드 기준이고 N_max는 16. DP2 η(N) = Goodput(N 노드) ÷ (N/2 × Goodput(1P+1D)), N = 32 |
| X-4-6 | DP4는 별 경계 중 **공개 요구사항 출처를 찾지 못한 것**(Q1의 1.10배·0.90배, Q3 비용·공수 경계)을 슬라이드에서 내부 환산·가정으로 표기했다. 값의 근거 수준을 표기한 점이 DP1·DP2보다 정직하다. 통일 시 이 표기 방식을 참고할 수 있다 |
| X-4-7 | DP4의 "평가 값"은 모두 **예상치(미실행)** 이고 요구사항 문서는 "목표 수치는 baseline 측정 후 확정하며 지금은 만들어 두지 않는다"고 했다. 이 문서의 방침(임계값을 통합 단계에서 정함)과 같은 방향이다 |

### 6.3 사용자 확정이 필요한 점

| ID | 질문 | 현재 가정 |
|---|---|---|
| Q-4-1 | DP4의 범위를 **후보 1(OSS 확장) 대 후보 2(자체 구현)** 의 구현 방식 비교로 보고 `DP0-1`(구조 S1/S2)은 무시하라는 지시를 그대로 따랐다. 맞는가 | 맞음 |
| Q-4-2 | DP2와 DP4의 P/D 결정 경계(DP4-C-3) | 미정, 통합 단계에서 정리 |
| Q-4-3 | 서버 간 연결 가정(PCIe 64 GB/s)과 기존 DP4 문서의 RDMA 50 GB/s 가정 중 무엇을 따를 것인가 | PCIe 64 GB/s(사용자 확인) |
| Q-4-4 | 추가 후보 QA(QA5~QA7, QA9) 채택 여부 | 권장 4개, 보류 2개 |
| Q-4-5 | LoRA adapter 보유 서버 선택(UC-4)을 DP4의 상태 수집에 포함할지 | 포함 가능(도출) |
| Q-4-6 | Resource Utilization 제외 입장(DP4)을 QA3 통합 방침에서 어떻게 볼 것인가 | `memo-qa3-resource-utilization.md` 참고 |
