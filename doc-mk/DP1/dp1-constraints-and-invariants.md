---
title: DP1 제약사항·불변식·접근 hazard 목록
status: draft (설계 단계, 구현·측정 없음)
date: 2026-10-06
basis: doc-mk/DP1/dp1-ai-data-migration-decision-architecture.md §3.3, doc-mk/vllm-ai-data-migration-architecture.md §7·14·19, vLLM 코드(`vllm/v1/core/block_pool.py`, `vllm/v1/core/sched/*`)
---

# DP1 제약사항·불변식·접근 hazard 목록

DP1(이기종 메모리 AI data migration)을 vLLM에 구현할 때 **지켜야 하는 것**을 한곳에 모은다. 설계 문서에는 범위 제약(C-S1~S3)과 일관성 불변식(I1~I4, R1~R4)이 흩어져 있고, 이동 중 접근 hazard는 명시되어 있지 않아 새로 정리했다.

각 항목의 **근거 태그**: `[문서]` = 기존 설계 문서에 있음, `[vLLM]` = vLLM 코드에서 확인한 사실, `[제안]` = 이 문서가 새로 제안하는 제약(검토 필요), `[가정]` = 확인하지 못한 가정.
**열 설명**: 제약(보장 내용) / 어기면 생기는 hazard / 강제 수단(누가 어떻게) / 검증 방법.

---

## A. 범위 제약 (Scope)

| ID | 제약 | 위반 시 / 이유 | 강제 수단 | 검증 | 근거 |
|---|---|---|---|---|---|
| C-S1 | 이동 범위는 **단일 노드 내부** (HBM, ScHBM, DRAM, CXL-PNM, HBF, SSD/SSD-PIM 사이)만 | 노드 간 이동은 DP0의 결정. 경계가 섞이면 책임 중복 | Registry의 tier 집합이 한 노드로 한정 | 설계 리뷰 | [문서] §3.3 |
| C-S2 | 노드 간 연결은 DP0 접점 계약(KV 이벤트 `medium`, 메트릭, `kv_transfer_params`)으로만 | 직접 연결 시 결합도 증가 | 인터페이스 한정 | 설계 리뷰 | [문서] §3.3 |
| C-S3 | 평가 시뮬레이터도 단일 노드 8-GPU 서버만 모델링 | 노드 간 비용/원격 tier는 평가 범위 밖 | 시뮬레이터 profile | `test_sim.py` | [문서] §3.3 |
| C-S4 | **초기 배치(initial placement)는 DP1 범위 밖.** DP1은 이미 존재하는 object의 재배치만 결정 | 할당 경로(`allocate_slots`)를 DP1이 바꾸면 범위 확대 | allocation은 기존 경로, DP1은 사후 migration만 | 코드 리뷰 | [문서] §5.8 표 |
| C-S5 | **data 내용을 바꾸는 변환은 migration이 아니다** (quantization/압축/in-place transform, near-data compute). DP1 action은 MOVE/REPLICATE/DROP/REMAP/RECLASSIFY뿐 | 내용이 바뀌면 version/identity/출력 동일성이 깨짐 | action enum 제한 | 단위 테스트 | [문서] §3.2 |
| C-S6 | DP1은 location을 **직접 변경하지 않는다.** 결정(Intent)만 내고 location commit은 공통 Migration subsystem | 결정 주체와 commit 주체가 섞이면 일관성 보장 불가 | Registry는 commit 결과로만 갱신 | 코드 리뷰 | [문서] §22.3, 아키텍처 §14 |

## B. Location / Identity 불변식

| ID | 제약 | 위반 시 | 강제 수단 | 검증 | 근거 |
|---|---|---|---|---|---|
| C-I1 | 모든 object는 **항상 정확히 하나의 authoritative location**을 가진다 (recomputable은 "absent" 허용) | authoritative 부재 구간에서 접근하면 데이터 소실/오독 | DataLocationStore 단일 레코드, DROP 시 승격+해제를 한 commit으로 | property test: 임의 이벤트 순서에서 I1 유지 | [문서] I1, R1 |
| C-I2 | authoritative location은 **copy 성공 및 검증 전에는 바뀌지 않는다** | 부분 복사 target을 정상 데이터로 읽음 | copy-then-commit 순서 고정 (reserve → pin → copy → verify → atomic commit → release) | 상태기계 테스트 | [문서] I2, §7 |
| C-I3 | object당 **동시에 in-flight job 하나** | 같은 object에 대한 충돌 migration(예: MOVE와 DROP 동시) | `LocationRecord.inflight_job` | 동시성 테스트 | [문서] I3 |
| C-I4 | commit은 LocationRecord 단위로 **atomic** | 위치와 version이 따로 갱신되면 reader가 불일치 상태를 봄 | 단일 임계 구역/CAS | 동시성 테스트 | [문서] I4 |
| C-I5 | **logical identity(block id, content hash)는 이동 전후 불변**; 물리 주소만 교체 | prefix cache hash와 block table이 서로 다른 object를 가리킴 | logical id ≠ physical address, PhysicalLocation(resource, alloc, offset, version) | identity round-trip 테스트 | [문서] 아키텍처 §15 |
| C-I6 | **bit-exact 복사.** 이동 후 내용 동일, 모델 출력이 placement와 무관 | silent corruption으로 출력이 달라짐 | 전송 handler의 길이/정렬 검증, 선택적 checksum | 이동 전후 hash 비교 테스트 | [제안] |
| C-I7 | DP1 Registry는 commit 결과로만 갱신, 완료 통지가 유실돼도 **idempotent reconciliation**으로 수렴 | completion 유실 시 location이 영원히 in-flight로 남음 | 상태 질의 + timeout | 장애 주입 테스트 | [문서] §19 |

## C. 이동 중 접근 Hazard (핵심)

사용자가 지적한 4가지(부분 복사 읽기, 해제된 슬롯 읽기, 이동 중 쓰기, 이동 중 prefix hit)와 추가 검토 항목이다.

| ID | Hazard | 제약 (이렇게 되어야 한다) | 강제 수단 | 검증 | 근거 |
|---|---|---|---|---|---|
| C-H1 | **부분 복사된 block 읽기** | commit 전에는 target이 **어떤 reader에게도 보이지 않는다**: block table, prefix-cache hash 표, 위치 조회에 target을 노출하지 않고, 모든 접근은 source로 간다 | target은 commit 때에만 mapping에 등록. copy 완료 이벤트(stream event) 이후에만 compute stream이 target을 읽음 | copy 도중 접근 주입 테스트 (source 값 확인) | [문서] I2 + [제안] 가시성 규칙 |
| C-H2 | **해제된 슬롯 읽기 (async scheduling)** | source 슬롯은 commit 직후에도 **그 위치를 담은 SchedulerOutput을 받은 모든 step이 끝나기 전에는 해제/재할당하지 않는다.** async scheduling에서는 scheduler가 step N+1을 만들 때 step N이 아직 worker에서 실행 중일 수 있어, 옛 위치를 가리키는 in-flight step이 commit 이후에도 존재한다 | location에 **epoch**를 두고 SchedulerOutput에 epoch를 실음. source 해제는 "옛 epoch를 가진 step이 모두 retire"된 뒤(grace period). 해제 큐에 보류 | async scheduling 켠 상태에서 commit 직후 step을 주입하는 테스트 | [vLLM] `v1/core/sched/async_scheduler.py` 존재, `num_output_placeholders`로 scheduler가 앞서 실행함. 해제 grace는 [제안] |
| C-H3 | **이동 중 쓰기** | 이동 대상은 **불변(sealed) data**로 한정. active tail block, 부분 채워진 block, 쓰기 중인 object는 **이동 후보에서 제외** (defer 또는 write barrier 후 freeze). 쓰기가 발생하면 version이 올라가 verify에서 abort | `KVDataAdapter.can_migrate_now` (sealed만 true), version 기록 → commit 직전 검증 | tail block migration 시도 reject 테스트, 중간에 version 변경 시 abort 테스트 | [문서] 아키텍처 §14.1~14.3. Phase 1은 sealed만 |
| C-H4 | **이동 중 prefix hit** | prefix cache 조회가 이동 중인 block에 hit하면 **source를 가리켜야 하고(authoritative)**, hit한 reader의 ref가 해제 전 source를 붙잡아야 한다. commit 후에는 hash → 새 location이 **한 번에** 바뀌어야 하며, hash가 해제됐거나 아직 쓰이지 않은 슬롯을 가리키는 구간이 없어야 한다 | hash 표 갱신을 DataLocationStore commit과 같은 atomic 구간에. source는 `ref_cnt`/pin이 0이 될 때까지 해제 보류 | 이동 중 같은 prefix를 가진 요청 주입 테스트 | [vLLM] `block_pool.touch()`가 hit 시 `ref_cnt += 1`하고 free queue에서 제거함. hash 표 갱신 순서는 [제안] |
| C-H5 | **block table의 stale 물리 주소** | **실행 중인 요청이 참조하는 block(ref_cnt > 0)의 물리 위치는 그 step 중에 바꾸지 않는다.** 이동은 (a) 참조가 없는 cached block(ref_cnt = 0, free queue에 있음)이나 (b) step 경계에서 block table을 다시 만드는 경우에만 | 이동 후보를 ref_cnt == 0으로 제한하거나, 참조 중이면 REPLICATE 후 다음 step 경계에서 REMAP | 실행 중 요청의 block을 이동 시도하는 테스트 | [vLLM] 요청은 block id 목록(block table)을 들고 step을 실행함. 정책은 [제안] |
| C-H6 | **이동 중 eviction** | block pool의 LRU eviction이 **이동 중인 source를 evict/재할당하지 못한다** | job 시작 시 source pin(= ref 보유)해 free queue에서 제외, pin 해제는 commit 이후 | pressure 중 migration 테스트 | [vLLM] `free_blocks()`는 ref_cnt 0이 되면 free queue에 넣고 `_maybe_evict_cached_block`이 hash를 제거함. pin은 [문서] §7 |
| C-H7 | **stale replica 읽기** | REPLICATE된 replica는 version을 기록하고, source가 바뀌면 **invalid**로 표시해 사용하지 않는다. active tail은 REPLICATE 대상 제외 | replica마다 version | version 불일치 테스트 | [문서] 아키텍처 §14.4 |
| C-H8 | **이동 중 request abort / preemption** | 요청이 취소돼도 job은 일관되게 끝나거나 취소되어야 하고 **source/target이 정확히 한 번씩 해제**된다 (double-free, leak 금지) | job 상태기계의 CANCELLED 경로, ref 소유자 추적 | abort 경로 fuzz | [문서] §7 상태기계. 세부는 [제안] |
| C-H9 | **이동 중 reset/무효화** (prefix cache reset, 모델 weight 갱신 등) | 무효화 시 in-flight job을 취소하고 target을 폐기한다. 무효화된 hash를 새 위치에 심지 않는다 | reset 이벤트 → 모든 job CANCEL | RLHF류 reset 테스트 | [vLLM] `BlockPool.reset_prefix_cache`, `evict_blocks` 존재. 연동은 [제안] |
| C-H10 | **tenant 격리** | 이동·해제된 슬롯의 내용이 **다른 tenant에게 노출되지 않는다.** 재할당 전 내용이 덮어써지거나 접근 권한이 분리된다 | cache salt를 hash에 포함(기존), 공유 pool(CXL)이면 해제 시 sanitize | 격리 테스트 | [가정] 기존 salt 정책과의 상호작용 미확인 |

## D. 다중 주체 / 플랫폼 제약

| ID | 제약 | 위반 시 | 강제 수단 | 검증 | 근거 |
|---|---|---|---|---|---|
| C-X1 | **TP/PP/DP rank 간 같은 commit.** 모든 rank가 같은 step 경계에서 같은 위치 변경을 적용하고, **모든 rank의 copy가 끝난 뒤에만** commit한다. 한 rank만 실패하면 전체 rollback | rank마다 다른 위치를 보면 collective에서 hang이나 오답 | 완료 집계(all-ranks) 후 commit, `SchedulerOutput`로 같은 시점 전파 | multi-GPU 테스트 | [가정] vLLM의 rank별 block 소유 방식 미확인 |
| C-X2 | **CUDA graph와의 호환.** graph replay 중에는 block table 주소를 바꾸지 않는다. 위치 변경은 replay 사이(step 경계)에서만 반영 | captured graph가 옛 주소를 읽음 | step 경계 적용 | graph 켠 상태 테스트 | [가정] |
| C-X3 | **전송 stream과 compute stream의 순서.** compute가 target을 읽기 전에 copy 완료 event를 기다린다. 전송이 compute를 막지 않도록 별도 stream | copy가 끝나기 전 읽거나, 전송이 forward를 지연 | event 기반 의존성 (`migration_dependencies`) | 타이밍 테스트 | [문서] 아키텍처 §11 |
| C-X4 | **coherency 도메인.** host DRAM/CXL/HBF/SSD 경로는 **CPU 캐시/DMA 순서**를 고려해 copy 완료를 fence로 보장한다. 하드웨어 coherent 영역(CXL.mem)과 비coherent 영역을 구분해 flush/invalidate 규칙을 둔다 | DMA 완료와 가시성이 어긋나 오래된 값을 읽음 | handler별 fence 의무, `MemoryDescriptor`에 coherency 속성 | handler 단위 테스트 | [가정] 장치별 coherency 모델은 확인하지 못함 |
| C-X5 | **Worker는 copy executor.** 위치 결정/commit 권한은 EngineCore만 가진다. Worker가 독립적으로 location을 바꾸지 않는다 | 여러 Worker가 같은 object를 충돌하게 이동 | 단일 authority | 구조 리뷰 | [문서] 아키텍처 §10 |

## E. 자원 / 용량 제약

| ID | 제약 | 위반 시 | 강제 수단 | 검증 | 근거 |
|---|---|---|---|---|---|
| C-R1 | **target을 먼저 예약**한 뒤에만 copy를 시작한다 (용량 초과로 mid-copy 실패 금지) | copy 중 target 부족 → 반쯤 쓴 상태 | reserve → copy | 용량 경계 테스트 | [문서] §7 |
| C-R2 | **데이터를 잃는 이동 금지.** replica도 recompute 경로도 없는 authoritative copy를 DROP하지 않는다 | 데이터 소실 | DROP 규칙 R1~R3 | DROP reject 테스트 | [문서] 아키텍처 §7.1 |
| C-R3 | **swap/교환의 deadlock 방지.** 승격 swap은 두 job이 서로의 자리를 기다리지 않도록 reserve 순서를 고정(demotion 먼저)하고 budget을 예약한다 | 두 object가 서로의 slot을 기다리며 정체 | 단계화 + 예약 | swap 시나리오 테스트 | [문서] 설계 §17.2, 시뮬레이터 구현(`_promotion_pass`)에서 확인 |
| C-R4 | **이동 단위/정렬 제약 준수.** SSD page, HBF erase block 등 `MemoryDescriptor.granularity/alignment`를 따른다 | 정렬 위반 전송이 실패하거나 write amplification | Planner가 단위에 맞춰 분할 | handler 테스트 | [문서] 설계 §5.8 |
| C-R5 | **endurance 예산.** HBF/SSD-PIM의 write 횟수/대역폭 예산을 넘지 않는다 (write_limited tier로의 demotion은 예산 내에서만) | 소자 수명 소진 | `endurance_budget` 관리 | 장기 시나리오 | [문서] 설계 §5.8 flag. **시뮬레이터는 미모델링** |

## F. 성능 / 간섭 제약

| ID | 제약 | 위반 시 | 강제 수단 | 검증 | 근거 |
|---|---|---|---|---|---|
| C-P1 | **migration은 serving 링크 시간을 제한된 몫만 쓴다** (token bucket, 평가의 `LINK_SHARE` 0.25). 한 번에 쏟아붓지 않는다 | 이동이 서빙 대역폭을 잠식해 TTFT/TPOT 꼬리가 악화 (평가에서 C1 TTFT P99 ×4 확인) | budget + (제안) staged pacing | loop iteration 4 sweep | [문서] 설계 §26 항목 8(link-time migration budget), 평가 loop-log iteration 4 [B+C] |
| C-P2 | **foreground(blocking) 우선, background는 양보.** 요청이 기다리는 promotion이 background demotion보다 먼저 | 요청 지연 | MigrationScheduler 우선순위 | 우선순위 테스트 | [문서] 아키텍처 §9 |
| C-P3 | **do-no-harm.** rebalance/이동이 해당 object의 서빙 penalty를 키우지 않으며, SLO를 위반하는 tier로 보내지 않는다 | CXL-PNM attention 경로 TPOT 300~600 ms 같은 SLO 위반 | Destination Tier Selector의 SLO 필터 | 평가 시나리오 | [문서] 설계, 시뮬레이터에서 확인 |
| C-P4 | **decision overhead는 서빙 경로에 있지 않다.** Selector/Executor는 비동기 이벤트로 동작하고 forward를 막지 않는다 | 결정 지연이 TTFT에 합산 | 이벤트 push 비동기 | 오버헤드 측정 | [문서] §5.1~5.2 |

## G. 데이터 종류 / 내구성 제약

| ID | 제약 | 위반 시 | 강제 수단 | 검증 | 근거 |
|---|---|---|---|---|---|
| C-D1 | **Phase 1은 sealed KV만 이동 대상.** LoRA/MoE/RAG/Agent memory는 후속 phase (immutability 별도 정의 후) | mutable data 이동 시 C-H3 위반 | adapter별 `can_migrate_now` | 단계별 테스트 | [문서] 아키텍처 §24 |
| C-D2 | **휘발 tier에 유일한 사본으로 둘 수 있는 data는 recomputable이거나 replica가 있는 것뿐.** Agent memory/Tool result처럼 재계산 불가능한 mutable data는 내구성 있는 tier(또는 replica)에만 둔다 | 장치/프로세스 장애 시 소실 | data class별 durability 속성, Selector의 필터 | 장애 주입 | [제안] (C1이 type-agnostic이면 hint에 durability를 실어야 함) |
| C-D3 | **Worker/EngineCore 크래시 후 안전한 재시작.** in-flight job은 폐기되고 source가 authoritative이므로 KV는 recompute로 복구한다 | 반쯤 쓴 target을 정상으로 오인 | commit 전 target은 metadata에 없음 | 재시작 테스트 | [문서] 아키텍처 §19 |

## H. 평가(시뮬레이터) 제약 — 위 제약을 시뮬레이터가 어떻게 가정하는가

| ID | 사실 | 영향 |
|---|---|---|
| C-E1 | 시뮬레이터는 **위 hazard(C-H1~H10)가 모두 없다고 가정**한다. copy-then-commit, 이동 중 접근, 해제 grace, rank 동기화, coherency 비용을 모델링하지 않는다 | 실제 구현의 일관성 비용(예: epoch grace로 인한 source 점유 연장, 부분 이동 실패)은 평가 값에 없다 |
| C-E2 | 이동 비용은 **링크 간섭 모델**(이동이 쓴 링크 시간만큼 해당 tier의 서빙 BW 감소)과 다음 접근에 부과되는 exposure(`MIGRATION_EXPOSURE` 0.20)로만 반영된다. queueing/saturation 없음 | TTFT 꼬리 크기는 모델 의존 (loop-log iteration 4) |
| C-E3 | HBF write amplification/endurance, PCIe/CXL protocol overhead, 전력은 모델링하지 않는다 | C-R5는 평가로 검증되지 않음 |
| C-E4 | 모든 평가 수치는 [B+C] simulation이며 실측 [A]가 아니다 | 구현 후 실측 필요 |

---

## I. 우선순위가 높은 열린 질문 (검토 요청)

1. **C-H5(실행 중 요청의 block은 이동 금지)가 DP1의 효과를 얼마나 제한하는가.** 평가의 hot/cold 시나리오는 "참조 중인 object도 이동"을 가정한다. vLLM에서는 ref_cnt > 0인 block은 step 경계 REMAP 없이는 못 움직이므로, 실제로 이동 가능한 object 집합이 평가보다 좁을 수 있다.
2. **C-H2(해제 grace)의 비용.** async scheduling에서 source 슬롯 점유가 몇 step 연장되는지에 따라 HBM 절감(QA3) 이득이 줄 수 있다.
3. **C-X1(다중 rank)**: block 소유와 migration의 rank별 분할이 어떻게 되는지 확인하지 못했다.
4. **C-D2**: C1은 type-agnostic이라 durability를 모른다. hint에 durability class를 추가하면 type-agnostic 원칙과 어떻게 양립하는지 결정이 필요하다.
5. **C-H10(tenant 격리)**: CXL 공유 pool을 쓰면 sanitize 비용과 정책이 필요하다.
