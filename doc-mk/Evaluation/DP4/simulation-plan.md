# DP4 Simulation & Evaluation Plan

> 대상: **DP4 — 비일관(non-coherent) CXL 공유 메모리에서 서버 간 KV 블록·메타데이터의 일관성을 소프트웨어로 보장하는 구조**.
> 설계 근거: [`../../DP4/dp4-inter-node-kv-sharing-structure-draft.md`](../../DP4/dp4-inter-node-kv-sharing-structure-draft.md) (재작성본).
> 평가 규칙: [`.claude/skills/evaluation/SKILL.md`](../../../.claude/skills/evaluation/SKILL.md) 필수. QA 정의는 [`../qa-evaluation-criteria.md`](../qa-evaluation-criteria.md), 공통 benchmark는 [`../common-benchmark.md`](../common-benchmark.md).
>
> 상태: **draft (사전 등록 문서)** — 결과를 보기 전에 작성한다. 이 문서의 정의·상수·기준은 결과를 본 뒤 바꾸지 않는다(H5, H16). 변경은 §15 변경 이력에만 추가한다.
>
> **평가 방식 (사용자 결정, 2026-10-04): 시뮬레이션 + 구조 논증.** 사용자 환경(서버 2대, GPU 8장씩)에는 CXL 공유 풀이 없으므로 **실측 [A]는 없다.** 시뮬레이션 출력은 [B+C], 구조 논증과 protocol model check는 [C]이다.

---

# 1. 평가 목표

**문제문.** CXL 2.0 스위치 풀은 호스트 CPU 간 캐시 일관성도 cross-node atomic도 제공하지 않는다. 이 위에서 서버 간 KV 블록과 메타데이터(prefix index, allocator, refcount)의 가시성·상호 배제를 소프트웨어로 보장하는 구조를 고른다.

**후보 (택일).**

| 후보 | 구조 | 대표 문헌 [B] |
|---|---|---|
| **C1 중앙 직렬화** | 메타데이터 서버 한 곳이 모든 메타데이터 연산을 직렬화한다. 클라이언트는 CXL 공유 메모리 슬롯 기반 RPC로 요청한다. 락이 필요 없다. KV 블록은 단일 writer·다중 reader | Beluga (SIGMOD'26) §6 |
| **C2 분산 락** | 메타데이터를 CXL 공유 메모리에 두고 모든 노드가 직접 갱신한다. 2단 락(노드 로컬 DRAM 락 + CXL 전역 락 배열 + 락 매니저 스레드)과 변경 캐시라인 `clflush`로 상호 배제·가시성을 확보한다 | TraCT (arXiv 2512.18194) §3 |

**공통 전제 (두 후보가 같음 → 후보 차이는 control plane에서만 나온다).**
- 페이로드 가시성: KV 블록은 GPU↔CXL DMA(캐시 우회)로 쓰고 읽는다. 쓰기 완료 뒤 메타데이터를 READY로 publish하는 시점이 가시성 경계다.
- KV 블록은 **불변(immutable)이고 prefix 체인 해시로 식별**된다. 쓰기 1회, 읽기 N회.
- refcount + LRU 퇴출.

**Common Reference Baseline (As-Is).** 같은 P/D 분리 클러스터에서 **CXL 풀 없이** KV를 RDMA(NIXL/UCX류)로 P→D 점대점 전송하고, 위치는 중앙 인덱스(이벤트 push, llm-d류)로 추적한다. 노드 간 prefix 공유는 없다(Common Benchmark 규칙: baseline prefix reuse 통제).

**평가 질문 (우선순위 순).**
1. 두 후보 중 어느 구조가 QA를 더 잘 만족하는가 (**C1 vs C2 직접 비교**, 주 질문).
2. 두 후보가 As-Is Baseline보다 나쁘지 않은가 (H4, Baseline-regression loop).
3. 각 후보가 포화하는 조건(control plane 용량 한계)은 어디인가.
4. 각 후보의 장애·복구 특성과 정확성(stale read 부재)은 어떠한가 — 성능과 분리한 구조 논증.

---

# 2. 평가 구성 (4개 축)

| 축 | 방법 | Evidence | 산출 |
|---|---|---|---|
| **(a) 클러스터 성능 시뮬레이션** | P/D 분리 클러스터 DES. 데이터 plane은 두 후보 동일, control plane만 후보별 | [B+C] | QA1~QA3, 진단 |
| **(b) control plane 포화 분석** | 노드 수·요청률·block 크기·락 stripe 수 sweep으로 포화 load 탐색 | [B+C] | 포화점, Scalability |
| **(c) protocol model check** | 비일관 캐시 의미론의 explicit-state 모델로 불변식 검증(결함 변종 검출 확인 포함) | [C] | 정확성(통과/반례). 별점 아님 |
| **(d) 구조 논증 (QA4)** | 변경 시나리오를 시뮬레이터 코드에 구현해 module/LOC 측정 + 장애 처리 논증 | [B+C] / [C] | QA4, 장애 특성 |

(c)는 Functional Correctness가 **제약**이라는 DP3·DP0의 정리를 따른다: 후보가 통과해야 하는 조건이지 별점을 매기는 QA가 아니다. 반례가 나오면 해당 후보 정의의 결함이며 별점 비교 전에 보고한다.

---

# 3. 시스템과 모델

| 항목 | 값 | 비고 |
|---|---|---|
| Model | `llama_3_1_70b`, BF16 | `DP1/sim/configs/models.json`. KV = 327,680 B/token (2×80×8×128×2). 8K = 2.5 GiB |
| 노드 | scale-up 도메인 1개 = GPU 8장 (`DP1/sim/configs/clusters.json`) | 계산 물리 모델은 `DP1/sim/model.py`의 `SystemSpec.prefill_s`, `decode_step_s`를 **import해 재사용**한다(수정 금지, H10) |
| 평가 SYS | **SYS-H100, SYS-B200** (통합 결과 하나, H19) | DP1과 같은 세대 축. GPU/HBM/PCIe 값은 `system-specs.md` 그대로 |
| 클러스터 profile | **신규** `DP4/sim/configs/cluster_dp4.json` | P/D 노드 수, 링크, 풀. provenance를 필드별로 기록(§4). 기존 profile은 수정하지 않는다(H10) |
| Topology | P/D 분리. 노드 수는 시나리오 파라미터(`n_p`, `n_d`) | CB 기본 `n_p=1, n_d=1` (= 사용자 환경 2대) |

**계산 모델.** Prefill은 노드 전체(TP=8)가 한 request씩 FCFS 처리하고 시간은 `prefill_s(context, query)`다. Decode는 연속 배칭(batch cap 32)이며 step 시간은 `decode_step_s(context, batch, "hbm")`다. 이 계산 물리는 **세 arm에서 동일**하다. 후보 차이는 KV 이동·메타데이터 경로에서만 생긴다.

**TTFT 정의.** DP2 문서 §8의 분해와 같다: `TTFT = T_queue + T_metadata + T_move + T_prefill (+ 첫 decode step 시작 대기)`. T_move는 KV가 decode 노드 HBM에 도달하는 데 걸리는 시간이다(레이어 단위 pipeline으로 prefill과 일부 중첩하되 중첩 비율은 §4의 상수).

---

# 4. 입력 파라미터와 provenance

provenance 태그: **PAPER**(두 논문 본문에서 직접 확인한 값, Evidence B), **SPEC**, **ASSUMED**(가정; sweep 대상). 논문 값은 모두 서버 2대, 단일 벤더 장치 조건의 측정이며 일반화하지 않는다.

## 4.1 data plane (두 후보 공통)

| 파라미터 | 기본값 | 범위(sweep) | provenance |
|---|---|---|---|
| CXL 접근 지연 | 640 ns | 400~650 ns | PAPER (TraCT: Niagara 2.0 640 ns, 10.1 GB/s 장치) |
| 풀 용량 / 집계 BW | 8 TiB / 1 TB/s | — | PAPER (Beluga: XConn CXL 2.0 스위치, 최대 16서버) |
| 노드당 CXL 어댑터 | 2 × PCIe5 x16 (63 GB/s/어댑터) | — | PAPER (Beluga Table 2) |
| 노드 CXL 유효 BW 효율 η_cxl | 0.5 | 0.25 / 0.5 / 0.9 | **ASSUMED** |
| KV 블록 | 64 tokens (20 MiB) | 16 / 64 / 256 | PAPER (TraCT 64, vLLM 16) / ASSUMED |
| 노드 CXL 유효 BW | 2 × 63 × η_cxl GB/s | | 위에서 유도 |
| GPU→CXL write 16 KB | 9.14 µs (DDIO off), CPU flush 경유 11.06 µs | — | PAPER (Beluga Table 4) |
| prefill/transfer 중첩 | 레이어 pipeline, 중첩 비율 0.7 | 0.5 / 0.7 / 0.9 | **ASSUMED** |

## 4.2 control plane — C1 (중앙 직렬화, Beluga)

| 파라미터 | 기본값 | 범위 | provenance |
|---|---|---|---|
| CXL-RPC 왕복 (64 B, QD=1) | 2.11 µs | — | PAPER (Beluga Exp #11; RDMA-RC 8.39 µs, UD 8.83 µs) |
| 서버 스레드 1개 처리량 | 12.13 Mops (≈ 82 ns/op, QD=128) | 서버 스레드 1 / 2 / 4 | PAPER (Beluga Exp #11) |
| RPC 한 번에 담는 블록 hash 수 | 8 (64 B / 8 B) | 4 / 8 / 16 | **ASSUMED** |
| 클라이언트 요청 쓰기 | ntstore 2.41 µs (16 KB 기준 값은 64 B로 비례 축소하지 않고 하한 RTT에 포함) | — | PAPER (Beluga Table 4) |
| 서버 읽기 전 CLFLUSH | RTT에 포함 | — | PAPER |
| 신뢰성 | CXL-RPC는 RDMA보다 보장이 낮고 상위 계층이 책임진다 | — | PAPER (Beluga §7) |
| 서버 프로세스 재시작 시간 | 0.5 s (인덱스는 CXL에 있어 보존) | 0.1 / 0.5 / 2 s | **ASSUMED** |
| 서버 노드 손실 시 인덱스 재구성 | 30 s (풀 스캔) | 10 / 30 / 120 s | **ASSUMED** |

## 4.3 control plane — C2 (분산 락, TraCT)

TraCT 본문에 **없는** 값(락 매니저 scan 비용, critical section 길이, stripe 수, 장애 처리)은 모두 ASSUMED이며 sweep한다. 이 값들이 C2 결과를 좌우하므로 **C2의 절대 성능 주장은 하지 않고 민감도와 포화 조건으로만 읽는다.**

| 파라미터 | 기본값 | 범위 | provenance |
|---|---|---|---|
| 메타데이터 한 cacheline 읽기(flush-before-read 포함) | 1.0 µs (CXL 지연 640 ns + flush) | 0.7 / 1.0 / 2.0 µs | ASSUMED (PAPER: 지연 640 ns, flush-before-read 존재) |
| 한 cacheline 쓰기+`clflush` | 1.0 µs | 0.7 / 1.0 / 2.0 µs | ASSUMED (`clflush`는 동기, `clflushopt`는 가시성 오류로 불채택 — PAPER) |
| 전역 락 stripe 수 S | 64 | 1 / 8 / 64 / 512 | ASSUMED (PAPER: "고정 크기 전역 락 배열") |
| 락 매니저 scan 1 probe | 0.35 µs | 0.1 / 0.35 / 0.7 µs | ASSUMED |
| 락 매니저 scan 1회 | `S × N × t_probe` | | ASSUMED (PAPER: "각 할당 락 항목의 노드별 슬롯을 probe") |
| 노드 로컬 락 (DRAM mutex) | 0.1 µs (비경합) | — | ASSUMED |
| request당 critical section | 3회 (pin / publish / unpin), 락 id는 stripe에 균등 분산 | 2 / 3 / 5 | ASSUMED |
| critical section 보유 시간 | `n_lines × (읽기 + 쓰기+flush)`, hit 블록 수에 비례하되 batch | | ASSUMED |
| 조회(lookup) | lock-free 읽기: bucket probe × 평균 1.3 (linear probing) | | PAPER("lookup은 메타데이터를 수정하지 않음") / ASSUMED(probe 수) |
| 락 보유 노드 장애 처리 | **as-published: 없음**(락이 풀리지 않음). 보완안: lease 1 s | lease 0.2 / 1 / 5 s | PAPER(논문에서 확인하지 못함) / ASSUMED |

## 4.4 Baseline-RDMA

| 파라미터 | 기본값 | 범위 | provenance |
|---|---|---|---|
| 노드 NIC | 4 × 200 Gbps (100 GB/s) | — | PAPER (Beluga RDMA baseline 하드웨어) |
| 유효 효율 η_rdma | 0.85 | 0.6 / 0.85 / 0.95 | **ASSUMED** (강한 baseline: layer 단위 연속 블록 전송, fragmentation 페널티 없음) |
| 중앙 인덱스 조회 | 100 µs (TCP/ZMQ류 RPC) | 50 / 100 / 300 µs | ASSUMED |
| 인덱스 갱신 | 이벤트 push, 비동기 | | |

> **Baseline을 약하게 만들지 않는다**(skill 금지 항목). RDMA의 작은 블록 비효율(Beluga가 관찰한 fragmentation)은 별도 **민감도 행**으로만 보고하고 별점에는 쓰지 않는다.

## 4.5 장애·복구 상수
§4.2, §4.3의 ASSUMED 상수만 쓴다. 장애 시나리오는 별점이 아니라 **구조 진단**이며(§8) 결과에 "as-published"와 "보완안(lease 등)" 두 행을 분리해 보고한다.

---

# 5. Policy 고정 (DP1·DP2·DP3은 상수로 둔다)

| DP | 이 평가에서의 고정 방식 |
|---|---|
| DP1 | 노드 내부 tier 배치는 고정(HBM 우선, 초과는 풀로). 풀 내부 배치는 단일 풀로 단순화 |
| DP2 | **비용 기반 argmin**(T_move + T_prefill + T_queue)을 세 arm 모두 같은 규칙으로 쓴다. Baseline은 후보 노드가 {P 노드들, KV를 보유한 D 노드}이고 후보는 풀 접근이 균일해 {P 노드들}이다 |
| DP3 | 압축·선택 재계산 **끔** (Comp.KV 없음). 별도 행 없음 |

---

# 6. Benchmark

정의는 [`benchmark.md`](benchmark.md)에 시나리오당 한 줄로 두고, **단일 소스는 `DP4/sim/scenarios.py`** 다.

| Set | 목적 | 별점 산출 |
|---|---|---|
| **Common (CB-1~3)** | 공통 QA1~QA3. 압박은 **링크·풀 background load**로 구현(§6.1) | 공통 별점은 여기서만 (H3, `common-benchmark.md` §7) |
| **DP4-specific (D4-n)** | control plane 포화, scalability, reuse, 장애 | diagnostic, QA4 근거. 공통 별점에 섞지 않는다 |

## 6.1 Common Benchmark 실현

고정 파라미터(Llama-3.1-70B BF16, 8K in / 256 out, batch 32, SLO TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms, baseline prefix reuse 통제)를 따른다. **압박의 의미**: 이 DP에서는 메모리 용량이 아니라 **서버 간 KV 이동 경로(링크/풀)의 경합**이 압박이다.

| ID | 코드명 | 실현 |
|---|---|---|
| CB-1 | `cb_kv_8k_b32` | KV만, 정상 상태. 압박 = **tight**: 노드 KV 링크의 background load 0.85 (효과 BW × 0.15) |
| CB-2 | `cb_kv_8k_b32_ramp` | CB-1과 같은 KV, background load가 0.2 → 0.9로 점진 증가 |
| CB-3 | `cb_mixed_8k_b32` | KV 50 / LoRA 15 / MoE 15 / Agent 10 / Tool 10 % (풀 트래픽·객체 수 기준). 압박 = tight |

background load 0.85, 0.2~0.9는 **ASSUMED**이며 결과를 본 뒤 바꾸지 않는다. 이 압박 정의가 임의적이라는 점은 한계에 적는다.

## 6.2 DP4-specific 시나리오 (사전 등록)

| ID | 무엇인가 | 드러내는 것 |
|---|---|---|
| `d4_agent_multiturn` | 8턴 에이전트, History KV 누적. **reuse 켬(별도 행)** | Baseline의 D→P 왕복 전송 누적 vs 풀 공유 |
| `d4_hot_prefix_fanout` | 긴 공통 prefix를 대부분의 request가 공유 | C1 서버 대기열, C2 hot 락 경합·refcount 갱신 |
| `d4_small_prompt_highqps` | 512 in / 64 out, 높은 request rate | control plane 연산률 지배 영역 |
| `d4_node_scale_n4` / `_n8` / `_n16` | 노드당 부하 고정, 노드 수 4/8/16 | Scalability (C1 서버 포화, C2 scan 비용 `S×N`) |
| `d4_block16` / `d4_block256` | block 크기 16 / 256 tokens | 블록당 control plane 연산 수 ∝ 1/block |
| `d4_pool_full_eviction` | 풀 점유 95%에서 퇴출과 reader 경합 | refcount 경합, 퇴출 지연 |
| `d4_lock_stripes_{1,8,512}` | C2 stripe 수 sweep | stripe 수의 contention vs scan 비용 |
| `d4_server_threads_{2,4}` | C1 서버 스레드 수 sweep | 중앙 직렬화의 확장 여지 |
| `d4_fail_server` | C1 메타데이터 서버 프로세스 crash 후 복구 | 가용성 창, SLO 위반 |
| `d4_fail_lockholder` | C2 락 보유 노드 crash (as-published / lease 보완) | 락 고착, 영향 범위 |

각 시나리오에 fit label(comparison-valid / infeasible / saturated, SKILL §4)을 부여한다. **예상: 대부분이 QA1·QA2에서 C1 ≈ C2(saturated)다(§10)**. saturated는 이득 근거로 쓰지 않는다.

---

# 7. 평가 지표

공통 QA(별점 규칙은 `../qa-evaluation-criteria.md`)와 DP4 정의는 [`qa-criteria-dp4.md`](qa-criteria-dp4.md)에 둔다.

| QA | DP4 metric | 비고 |
|---|---|---|
| QA1 | Max SLO Goodput (output tok/s), load sweep (×0.5 / 1.0 / 1.5 / 2.0, peak가 grid 끝이면 확장) | T_ref = Baseline-RDMA |
| QA2 | TTFT P99, TPOT P99 (P50/P95 병기), 별도 행 (H23) | |
| QA3 | **클러스터 KV 상주 메모리(HBM + host + 풀) 시간평균 GiB ↓** (자원 사용량만, 성능 미혼합, H20) | 진단: coherence CPU core-equivalent, 링크 점유율 |
| QA4 | 변경 module 수 / 공수 / 에이전트 비용 (사전 등록: [`qa4-preregistration.md`](qa4-preregistration.md)) | H21 |
| (제안) Scalability | Scaling efficiency (N 노드 goodput ÷ (N/2 × 2노드 goodput)) | **공식 QA 아님, 사용자 확정 전까지 값만 보고**, 별점 없음 (H11) |

**DP4 diagnostic.** metadata op latency P50/P99(연산 종류별), control plane 점유율(서버 / 락 매니저 / 전역 락), 락 대기 시간, 포화 offered load, stale-visibility 반례 수(model check), 장애 시 SLO 위반 request 수·창 길이.

---

# 8. 장애·정확성 평가 (성능과 분리)

| 항목 | 방법 | 보고 |
|---|---|---|
| 정확성 (stale read 부재) | `DP4/sim/protocol_check/`의 explicit-state model check. 모델: 노드별 비일관 로컬 캐시, DMA 캐시 우회, `clflush`/`clflushopt`+fence, 메타데이터 publish 순서. **결함 변종**(clflushopt 비동기, 읽기 전 invalidate 누락, publish가 DMA 완료보다 앞섬)을 반드시 넣어 검사기가 반례를 찾는지 확인 | 후보별 불변식 통과/반례. 검사기 자체의 검증(결함 변종 검출) 포함 |
| 장애 특성 | 시뮬레이션(`d4_fail_*`) + 논증. as-published와 보완안을 분리 | SPOF·고착 범위·복구 시간 |
| 확장 한계 | control plane 포화 분석(§9) | 포화 offered load, 노드 수 |

**한계 명시.** model check는 설계 수준 추상 모델이며 실제 하드웨어 메모리 모델·CPU 캐시 구현의 검증이 아니다. 통과는 "모델 안에서 반례 없음"이다.

---

# 9. 통계·재현 규칙

- seed **11, 23, 37, 53, 71** (≥ 5), load sweep ×0.5 / 1.0 / 1.5 / 2.0, 95% CI(t(0.975, df=4)=2.776), CV. 같은 `(scenario, seed, load)` trace를 세 arm에 쓴다(paired).
- 집계 단위는 (시나리오, SYS) 쌍, 여러 쌍은 **기하평균**. 통합 결과 하나(`merge_systems`와 같은 규칙).
- 숫자는 코드 출력(`qa_eval.py`)에서만 옮긴다. raw는 `DP4/results/data/`. git revision과 dirty 여부를 기록한다.
- 후보가 Baseline보다 나쁘면 SKILL §5 Baseline-regression loop를 돈다. 중단 조건 (i)의 N_win은 **3**(기본).

---

# 10. 사전 예측 (결과 보기 전 기록, H16)

이 절은 back-of-envelope 추정이며 결과로 **반증될 수 있다.**

1. **control plane 지연은 µs 규모, KV 페이로드·prefill은 수십~수백 ms 규모다.** 8K KV는 2.5 GiB로 링크 전송만 수십 ms, prefill 계산이 수백 ms다. 따라서 CB-1~3에서 **C1과 C2의 QA1·QA2 차이는 노이즈 수준(saturated)일 것으로 예상**한다.
2. 차이는 control plane 연산률이 지배하는 영역(작은 prompt, 작은 block, 높은 request rate, 많은 노드)에서만 나타나고, 그 영역에서도 **현실적인 request rate(노드당 수십 req/s)에서는 두 구조 모두 포화하지 않을 것**으로 예상한다. 포화 offered load는 시뮬레이션의 보고 대상이다.
3. C1 대비 C2가 갈리는 지점은 **노드 수 N과 stripe 수 S에 비례하는 락 매니저 scan 비용**(`S×N×t_probe`)과 hot prefix의 락 경합이다. C1은 서버 단일 큐의 포화와 **SPOF**다.
4. **Baseline-RDMA 대비 후보의 이득은 data plane 상수(η_cxl, η_rdma, 중첩 비율)에 지배**되고 두 후보가 같으므로, 후보 선택의 근거가 되지 못한다. 이득 주장은 reuse 시나리오(`d4_agent_multiturn`)와 그 sensitivity로 한정한다.
5. 따라서 **이 DP의 실질적 trade-off는 성능(QA1/QA2)보다 QA4(변경 용이성), 확장 한계, 장애·정확성 쪽에 있을 것**으로 예상한다. 이것이 결과로 확인되면 "coherence 구조는 성능 레버가 아니다"가 결론이다(H16: 지배하면 그것이 결론).

---

# 11. 모델링하지 않는 것 (한계 사전 명시)

- 실제 CXL 하드웨어·CPU 캐시 동작, GPU↔CXL DMA의 세부(커널 launch, 조각난 KV layout의 scatter/gather는 평균 효율에 흡수).
- 풀 장치의 bank 경합·인터리빙, 스위치 혼잡(집계 BW 상한만).
- 락 매니저·서버 스레드의 CPU 스케줄링 간섭.
- 풀 장치 장애·오류(KV 재계산 가능 전제).
- DP2 정책의 세부, DP3 압축.
- 논문 측정은 서버 2대·소형 모델·단일 벤더. 16노드 값은 외삽이다.

---

# 12. 경계 (다른 DP와)

| DP | 경계 |
|---|---|
| DP1 | 노드 내부 tier 배치와 단일 도메인 내 이동은 DP1. DP4는 노드 간 공유 풀의 일관성 |
| DP2 | Prefill 노드 선택은 DP2. DP4는 선택이 쓰는 T_move·위치 정보의 제공 방식(공유 풀 접근이 균일하면 T_move가 균일해짐, 가설) |
| DP3 | Comp.KV는 평가에서 끔. 공유 객체로서의 확장은 DP3 문서 |

---

# 13. 구현 계획

| Phase | 내용 | 산출 |
|---|---|---|
| 0 | 사전 등록 (이 문서, criteria, QA4 prereg, priority proposal, benchmark) | 문서 |
| 1 | 시뮬레이터 (`DP4/sim/`): 모델, 세 arm 정책, 시나리오, `qa_eval.py`, 테스트 | 코드, 테스트 통과 |
| 2 | protocol model check (`DP4/sim/protocol_check/`) | 코드, 결함 변종 검출 테스트 |
| 3 | 전체 benchmark 실행(≥ 5 seeds, SYS-H100/B200) | `results/data/` |
| 4 | QA4 측정(변경 시나리오 구현), 민감도, loop 필요 시 반복 | `qa4_*.json`, loop-log |
| 5 | 결과 문서(7섹션), PPT | `results/YYYY-MM-DD_dp4-qa-evaluation.md`, pptx |

# 14. 실행 체크리스트
[ ] simulator test 통과  [ ] 모든 숫자가 `qa_eval.py` 출력  [ ] git revision 기록  [ ] SYS-H100/B200 통합  [ ] Baseline 미만 시 loop  [ ] model check 결과와 결함 변종 검출 확인  [ ] 한계에 §10 예측과 결과의 일치 여부 기록

# 15. 변경 이력
- 2026-10-04: 최초 작성(사전 등록).
