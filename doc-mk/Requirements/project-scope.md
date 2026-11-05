# 과제 범위 (Project Scope)

> 상태: **초안(제안)**. 작성: 2026-10-09. 지금까지 모은 제약사항 중 **범위(무엇을 하고 무엇을 하지 않는가)에 해당하는 것**을 한곳에 추렸다. 발표에서 범위를 먼저 밝히고 가기 위한 문서다. 각 항목의 출처 ID는 `project-context.md`(GC), `DP1~DP4-requirements.md`(DP*-C)다. DP 번호는 최종 번호(project-context §0).

## 1. 과제의 초점 (사용자 정리 2026-10-09)

> **이 과제의 초점은 스케줄링, 즉 이기종 메모리 환경에서 "무엇을, 어디에, 언제 둘지(실행할지)를 정하는 결정"이다.**

- 과제 정의: 계층적 memory 시스템에서 메모리를 효율적으로 사용해 성능을 높이는 **런타임**을 개발한다. 메모리는 대역폭·용량이 다른 여러 메모리와 연산 가능 메모리(PIM, PNM)를 포함한다.
- DP별로 보면 모두 **결정 문제**다.

| DP | 결정하는 것 |
|---|---|
| DP1 | 데이터를 **어느 메모리 tier로, 언제 이동할지**(evict, promote, prefetch) |
| DP2 | Prefill과 Decode를 **어느 자원(노드, 자원)에서 실행할지** |
| DP3 | KV에서 **무엇을 제거·재사용하고 어떤 토큰을 재계산할지** |
| DP4 | 요청을 **어느 서버로 보내고 P/D를 어떻게 나눌지** |

- 이 초점은 **기능 요구사항**(시스템은 결정을 내린다), **제약사항**(결정 이외의 실행 메커니즘은 입력으로 주어진다), **과제 범위**(아래)에 모두 반영한다. 반영 위치: 이 문서 §2~3, `project-context.md` GC-11, `usecases.md`의 공통 기능 요구사항 FR-G1.

## 2. 범위 안 (In scope)

| 구분 | 내용 | 출처 |
|---|---|---|
| 결정(스케줄링) | 데이터 이동·배치(DP1), 연산 실행 위치(DP2), KV 제거·재사용·선택 재계산(DP3), 요청 배분과 P/D 분배(DP4) | §1, 각 DP 문서 |
| 대상 데이터 | KV, LoRA adapter, MoE expert, RAG 인덱스, Agent memory/Tool result (DP1에 모두 포함, 사용자 확정) | 사용자(2026-10-09) |
| 환경 | 단일 노드와 멀티 노드, GPU 8장 서버 2대, 이기종 메모리(HBM, DRAM, SSD 실장 / HBF, ScHBM, PIM, CXL-PNM 시뮬레이션) | project-context §1~2 |
| 엔진 | vLLM 고정 | GC(project-context §2), DP4-C-1 |
| 성능 목표 | SLO를 지키는 처리량·지연, 자원 효율, 변경 용이성, 확장성(DP별 QA) | 각 DP 문서 |
| 결정의 입력 관측 | 메모리 상태(capacity, bandwidth, load), 데이터 접근 행동, 요청 정보를 수집해 결정 입력으로 쓰는 것 | DP1-FR-05, DP2-FR-06, DP4-FR-02 |

## 3. 범위 밖 (Out of scope)

### 3.1 과제 전체

| ID | 범위 밖 | 처리 | 출처 |
|---|---|---|---|
| S-1 | **학습/훈련** | 제외 | 사용자(2026-10-09) |
| S-2 | **보안, tenant 격리** | 제외. LoRA 멀티 테넌트는 서빙 성능만 다룸 | 사용자, GC-6 |
| S-3 | **장애 복구**(device runtime 내부 오류·복구 포함) | 제외. 우리 계층의 degradation 처리(Fault tolerance, Recoverability)는 QA 후보로 둠 | 사용자, GC-3, GC-6 |
| S-4 | **device runtime**과 그 reliability, availability | 보장된다고 가정 | GC-3 |
| S-5 | **device runtime의 오버헤드** | 고려하지 않음(큰 제약) | GC-2 |
| S-6 | **device runtime, 연산 가능 메모리를 지원하는 kernel·compiler 관련 runtime** | 범위 밖. 연산 가능 여부와 성능은 profile 값으로 받음 | GC-5 |
| S-7 | **제품(메모리 장치) 자체의 단위 테스트, 간단 응용 테스트** | 완료되었다고 가정 | 사용자 |
| S-8 | **문서·데이터 갱신 시 KV 무효화(stale KV)** | 제외 | GC-10 |
| S-9 | **모델 정확도 변경** | 정확도는 불변(bit-exact). **DP3의 KV 제거만 예외**(F1 하락 1% 이내, 압축 전 + full recompute 기준) | GC-7, DP3-C-4 |
| S-10 | 차세대 메모리 성능의 실측 | 시뮬레이션 기반 예상 성능 | GC-1 |
| S-11 | 차세대 메모리 관련 추가 제약 | 사용자가 별도 글로 제공 예정 | GC-8 |

### 3.2 DP별 범위 밖 (결정 이외의 실행 메커니즘 포함)

| ID | DP | 범위 밖 | 담당 | 출처 |
|---|---|---|---|---|
| S-12 | DP1 | **실제 byte 전송, reserve/release, source pin, version check, atomic commit, rollback, 일관성 보장** | 공통 Migration subsystem(G1) | DP1-C-5 |
| S-13 | DP1 | HW 주소 변환, DMA/copy engine, coherency 프로토콜, vendor driver 구현 | device driver/runtime(G2, G3, O2) | DP1-C-9 |
| S-14 | DP1 | **초기 배치(initial placement)** | 기존 할당 경로 | DP1-C-2 |
| S-15 | DP1 | 데이터 **내용을 바꾸는 변환**(압축, 양자화, near-data compute)은 migration이 아님 | DP3, DP2 | DP1-C-3 |
| S-16 | DP1 | **노드 간 이동**(단일 노드 안만) | DP4 | DP1-C-1 |
| S-17 | DP1 | 이동 대상은 **불변(sealed) 데이터이고 참조 중(ref_cnt > 0) block은 step 중 이동하지 않음** | 범위 한정 | DP1-C-6 |
| S-18 | DP2 | **Cost Model 자체의 설계와 정확도** | 별도(ε sweep으로만 다룸) | DP2-C-1 |
| S-19 | DP2 | **Decode 실행 중 Tier 간 KV 이동** | DP1 | DP2-C-2 |
| S-20 | DP2 | vLLM 코드 레벨 매핑(구현 프레임워크와 독립) | 구현 단계 | DP2-C-3 |
| S-21 | DP2 | 재계산 후보(SSD의 History를 불러오지 않고 재계산) | 미결 | DP2-C-9 |
| S-22 | DP3 | Demote(하위 tier로의 무손실 이동) | DP1 | DP3-C-1 |
| S-23 | DP3 | **attention kernel 수정**(score 노출) | GC-5에 따라 범위 밖(확인 필요) | DP3-C-7 |
| S-24 | DP3 | 선택 재계산의 구체적 방법 | 이후에 정함(사용자) | DP3-C-8 |
| S-25 | DP3 | 인스턴스 밖(서버 간) KV 재사용 | DP4, DP6 | DP3-C-13 |
| S-26 | DP4 | 서버 **내부** 결정(batch, block, tier) | DP1~DP3 | DP4 문서 §2.1 |
| S-27 | DP4 | 엔진 교체(vLLM 고정) | 전제 | DP4-C-1 |
| S-28 | DP4 | **비일관 CXL 공유 메모리의 서버 간 KV 일관성** | DP6 | DP4-C-13 |
| S-29 | DP4 | 흐름 제어의 고도화·multi-cluster 등은 신규 기능 시나리오로만 다룸 | — | DP4 문서 S6 |

## 4. 전제 (Assumptions)

- A-1 DP 번호는 최종 번호를 쓴다(project-context §0). DP5는 없고 DP6은 이번 범위에서 제외한다.
- A-2 서버 2대는 PCIe 64 GB/s로 연결되어 있고 차세대 메모리 기반 서버도 우선 PCIe 기반이다(GC-9).
- A-3 DP1의 공통 Migration subsystem이 일관성(G1)을, device driver가 전송 완료 의미(G2)와 주소 변환 일관성(G3)을 보장한다(DP1 §6).
- A-4 attention score는 기존 LLM 생성 구조(Attention Manager)가 제공한다(도출, 확인 필요).
- A-5 연산 가능 메모리의 지원 연산과 성능은 profile 값으로 주어진다(GC-5).

## 5. DP 간 경계 (범위 안에서 누가 무엇을 맡는가)

| 경계 | 설명 | 상태 |
|---|---|---|
| DP1 ↔ DP3 | Demote(무손실, DP1) 대 제거·압축·재사용(DP3). Comp.KV의 저장 위치는 DP1 | 확정(DP3 문서 B 기준) |
| DP1 ↔ DP2 | Decode 중 Tier 간 이동은 DP1, Turn 단위 실행 위치는 DP2 | 확정 |
| DP2 ↔ DP3 | 선택 재계산의 실행 자원은 DP2, 재계산 토큰 선정은 DP3 | 제안 |
| **DP2 ↔ DP4** | **미결**. `memo-dp2-dp4-boundary.md` 참조 | **미결** |
| DP4 ↔ DP6 | 서버 간 KV 공유의 일관성은 DP6 | 확정(DP 번호 기준) |

## 6. 발표용 범위 문장 초안

1. "이 과제는 이기종 메모리 환경에서의 **스케줄링(결정)** 을 다룬다. 전송·commit·driver 같은 실행 메커니즘과 device runtime은 주어진 것으로 본다."
2. "모델 정확도는 바꾸지 않는다. 단 KV 제거는 압축 전 full recompute 대비 F1 1% 이내의 하락을 허용한다."
3. "차세대 메모리(HBF, ScHBM, PIM, CXL-PNM)의 성능은 시뮬레이션 기반 예상 성능이며 device runtime 오버헤드는 반영하지 않는다."
4. "학습, 보안·격리, 장애 복구, 문서 갱신 시 KV 무효화는 범위 밖이다."
