# Continuum (KV-Cache TTL 스케줄링) 구현 설계서

- 논문: *Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live* (arXiv:2511.02230v7)
- 공개 코드: <https://github.com/Hanchenli/vllm-continuum> (HEAD `316a587`, vLLM ≈0.10.x 기반 포크)
- 이식 대상: 본 저장소 (최신 vLLM V1, `vllm/v1/core/sched/scheduler.py` 2295줄)
- 작성 범위: **분석 + 설계** (구현 코드는 포함하지 않음). 논문이 명시하지 않아 내가 해석/결정한 항목은 `[D#]`, 근거가 약해 검증이 필요한 항목은 `[검증필요]`로 표시.

---

## 0. 요약 (TL;DR)

1. 공개 코드는 논문의 **스케줄링 골격(pin + program-level FCFS)** 만 구현했고, 논문의 핵심인 **cost/benefit 모델(Eq.1–2), tool-duration CDF, η(memoryfulness), T(queue delay), offline profile(Prefill-Reload), 3단계 cold-start** 는 전부 없다. 대신 `FIXED_THRESHOLD_CONTINUUM = 2.0s` 하드코딩 + "평균 tool 시간 > 2s 이면 pin 안 함" 이라는 휴리스틱이 들어 있다. (README도 "without the estimation in the paper"라고 명시)
2. 공개 코드는 구버전 vLLM 포크라서 **패치 이식이 불가능**하다. 현재 저장소는 `skipped_waiting` 큐, streaming session, async scheduling, hybrid KV group 등이 있어 스케줄러 구조가 다르다. → "포크 diff 적용"이 아니라 **논문 기준 재설계 + 최소 훅 이식**으로 진행한다.
3. 핵심 수식은 `MemUsage(r)/M` 가 양변에서 소거되어 **스케줄러 hot path에서 계산할 것은 4개뿐**이다:
   `τ* = argmax_τ P(τ,f)·(T·η + PrefillReload(r)) − τ`
   → 필요한 상태 = ① tool별 duration 분포 `S[f]` ② 큐잉 지연 `T` ③ memoryfulness `η` ④ prefill/reload 시간 모델.
4. vLLM의 pin은 새로운 메커니즘이 필요 없다. **"finish 시 `kv_cache_manager.free()`를 호출하지 않는 것" = pin** (ref-count 유지). `KVCacheManager`/`BlockPool` 수정 없이 스케줄러 레벨만으로 가능하다.
5. 제안 구조: `vllm/v1/core/sched/continuum/` 서브패키지(순수 함수 위주 → 단위테스트 용이) + 스케줄러 훅 5곳 + 큐 1개 + config 1개. 논문의 "≈1k줄 Python, 스케줄러 변경 최소" 목표와 부합.

---

## 1. 논문 분석: 알고리즘 사양 (구현 기준)

### 1.1 문제 설정
ReAct형 agent는 `LLM step → tool 실행 → LLM step …`을 반복. 기존 엔진은 request 종료 즉시 KV를 evict(end-of-turn eviction)하므로 (a) 다음 turn에서 prefill/reload 비용, (b) **per-turn queueing delay**(다른 요청이 GPU를 점유 → turn마다 누적)가 발생. InferCept는 (a)만 모델링, Autellix(PLAS)는 tool-unaware.

### 1.2 Utility 모델 (§4.1)
| 기호 | 의미 |
|---|---|
| τ | TTL (초) |
| MemUsage(r) | r의 KV가 점유한 GPU 메모리 |
| M | 관측된 request의 평균 메모리 점유 |
| Prefill-Reload(r) | KV 재구성 시간 (offload 켜면 reload, 아니면 prefill) |
| T | evict된 후 돌아온 request의 평균 큐잉 지연 (sliding window) |
| η = −Corr(k, N−k) | workload memoryfulness (k: 처리된 turn 수, N: program 총 turn 수) |
| P(τ,f) | tool f가 τ 내 종료할 확률 (경험적 CDF) |

```
Cost(τ, r)          = MemUsage(r)/M · τ
CacheMissCost(r)    = MemUsage(r)/M · PrefillReload(r)
OutOfOrderCost(r)   = T/M · MemUsage(r) · η
Benefit(r)          = CacheMissCost(r) + OutOfOrderCost(r)

τ* = argmax_τ  P(τ,f)·Benefit(r) − Cost(τ,r)                       (Eq.1)
   = argmax_τ  P(τ,f)·( T·η + PrefillReload(r) ) − τ               (Eq.2, MemUsage/M 소거)
```
- η=1 (모든 program이 고정 N turn): pin이 SJF를 근사 → 큐잉 지연 절약 최대. η=0 (geometric N): 순서 유지가 이득 없음. η<0 (heavy-tail): 이론상 허용(이 경우 benefit이 줄어 TTL→0 쪽).
- `P`가 계단함수이고 `−τ`는 선형 감소이므로 최적해는 **관측된 tool duration 값들 ∪ {0}** 중에 있다 → 후보 열거로 정확히 해결 (§4.2).

### 1.3 TTL 설정 3단계 (cold-start, §4.2)
`K = 100` (본문에 "threshold M"과 "K"가 혼용 — K로 해석 `[D1]`)
| 조건 | 사용 분포 |
|---|---|
| \|S\| ≤ K (전역 기록도 부족) | `T_default`: Exp(1) tool duration + η=1 가정에서의 τ* |
| \|S\| > K 이고 \|S[f]\| ≤ K | 전역 CDF `Σ_{t∈S} I[t≤τ]/\|S\|` |
| \|S[f]\| > K | tool별 CDF |
- T는 0으로 초기화.

### 1.4 스케줄링 우선순위 (§4.3) — 다중 키, 순서대로
1. **Preempted** 요청 우선 (원 vLLM과 동일)
2. **TTL 내 pinned** program의 요청 우선
3. **Program 도착 시각** FCFS (request 도착 시각이 아님)

### 1.5 Algorithm 1 (의사코드 요약)
- `OnRequestArrive(r)`: `Q ∪= r`; 기존 program이면 직전 tool의 (f, t=도착−직전 finish)를 `S[f]`에 기록.
- `OnRequestFinish(r)`: last request면 KV free. 아니면 `P[id] = CalcTTL(r, S[f])` (pin).
- `Schedule()`: 매 step, `P`의 만료 항목 중 `id ∉ Q.programs`인 것만 unpin(=free). 이후 `argmax CalcPriority`로 request 선택 → 메모리 안 맞으면 break, 맞으면 issue 후 해당 program의 pin 항목 제거.

### 1.6 시스템 요소 (§5)
- **Tool Call Handler**: 요청 도착/종료 시 호출되는 독립 클래스. 응답에서 tool call 식별(OpenAI function_call schema; SWE-bench는 bash 블록의 첫 단어), 서버측 timestamp로 `도착(i+1) − finish(i)`를 tool 실행 시간으로 기록.
- **Request Pinning/Unpinning**: `pinned_requests{req → expire}`; finish 시 blocks free 생략. 매 step `unpin_requests()` (TTL 만료 **and** program이 waiting에 없음).
- **Deadlock 방지**: 스케줄 실패 시 `pinned_requests` 중 **program 도착 시각이 가장 늦은 것**부터 unpin → 첫 request가 들어갈 때까지.
- **Offline profile**: (1) GPU↔CPU 대역폭(평균 offload throughput), (2) context 길이 {1000, 2000, 4000, …, max_ctx}로 prefill 시간 측정 후 **2차 곡선 fit**. 하드웨어·모델 쌍당 <10분. 부분 잔존 page는 무시하고 full prefill로 근사.
- 평가 기본값: vLLM 0.10.2, chunk 2048, LMCache 0.3.7 (A100 DRAM 100GB, H100/B200 200GB/GPU).

---

## 2. 공개 코드 분석

### 2.1 구현된 것 (논문과의 매핑)
| 논문 요소 | 공개 코드 위치 | 상태 |
|---|---|---|
| program_id 전달 | `entrypoints/openai/protocol.py` 3곳에 `job_id`, `is_last_step` 필드 → `extra_args` → `Request` | ✅ (client가 직접 `is_last_step` 제공) |
| Request pin/unpin | `scheduler.py: pin_request / unpin_request / unpin_requests_regular / is_pinned` | ✅ 단, `list[(req, end_time)]` 선형 스캔 |
| finish 시 free 생략 | `scheduler._free_blocks` | ✅ |
| Program-level FCFS | `request_queue.ContinuumRequestQueue` + `job_id_first_entry_time` | ✅ 단, 선형 스캔 |
| pinned 우선 | `peek_request`: pinned job_id 중 가장 이른 program → 없으면 전체 최조 program | ✅ (preempted 우선 키 **없음**) |
| Deadlock 방지 | `pop_running_request_based_on_last_step`: `len(running)<=1`일 때만 pin 중 `end_time` **최대**를 victim | ⚠️ 논문(program 도착 최신순)과 다름 |
| 평균 tool 시간 기록 | `ToolCallEstimator.update_func_call_exec_time` | ⚠️ **평균만** 저장 (CDF 아님) |
| Tool 식별 | `ToolCallParser`: ```` ```bash ```` 블록 첫 단어 (mini-swe-agent 전용) | ⚠️ 하드코딩, 요청 종료 시 **전체 출력 detokenize** |
| 관측/로깅 | `Continuum_Recorder` (JSON dump) | ✅ 실험용 |

### 2.2 **없는** 것 (= 이번 작업의 본체)
| # | 논문 요소 | 공개 코드 대체물 |
|---|---|---|
| G1 | Eq.1/2 τ* 최적화 | `set_up_pin()`: `평균 exec_time > 2.0s → 0, 아니면 2.0s` |
| G2 | 경험적 CDF `P(τ,f)` | 평균값 1개 |
| G3 | η (memoryfulness) 추정 | 없음 |
| G4 | T (큐잉 지연) sliding-window | 없음 (`Continuum_Recorder`가 로그만 남김) |
| G5 | Prefill-Reload 모델 + offline profiler | 없음 (`test_scripts/`에도 없음) |
| G6 | 3단계 cold-start / `T_default` | 없음 (2.0s가 사실상 static TTL) |
| G7 | 우선순위 키 1번 (preempted 우선) | 없음 |
| G8 | 논문식 deadlock victim 선택 | 부분 구현 |
| G9 | tool call 파서 일반화 (OpenAI schema 등) | bash 정규식 1종 |
| G10 | 서버측 `is_last_step` 판정 | 클라이언트 제공 필수 |

### 2.3 공개 코드의 구현 품질 이슈 (이식 시 답습 금지)
- `time.time()` 기반 (wall-clock) — NTP 보정에 취약. scheduler는 monotonic 사용 권장.
- `waiting` 순회 O(|Q|)로 매 step `waiting_job_ids` 리스트 생성, pin 리스트 선형 탐색.
- `_free_blocks`에서 같은 job의 기존 pin을 free → 재pin 순서가 요청 finish 시점이라 **다음 request가 스케줄되는 시점에 pin 해제**하는 논문 Alg.1(line 26)과 타이밍이 다름.
- pinned request를 `self.requests`에서 삭제 → 이후 `finish_requests/abort`/`reset_prefix_cache` 경로와의 상호작용이 불분명.
- 포크 README: multi-node는 sticky routing 필요 (program 단위 affinity).

---

## 3. 현재 저장소(이식 대상) 구조 분석

| 항목 | 위치 | 설계 시 의미 |
|---|---|---|
| 정책 enum | `config/scheduler.py:21` `SchedulerPolicy = Literal["fcfs","priority"]`, `request_queue.py` `SchedulingPolicy` | `"continuum"` 추가 지점 |
| 큐 팩토리 | `request_queue.create_request_queue(policy)` | `ContinuumRequestQueue` 등록 |
| 큐 2개 | `scheduler.py:167-169` `waiting`, `skipped_waiting` + `_select_waiting_queue_for_scheduling` (1567) | non-FCFS는 `waiting_req < skipped_req`(=`Request.__lt__`: priority, arrival_time)로 큐 선택 → **continuum key 비교로 대체 필요** |
| Preempt 루프 | `schedule()` 452–520, `_preempt_request` 952 | PRIORITY 분기와 동일 위치에 CONTINUUM 분기 / **pin 우선 회수** 삽입 |
| Waiting 루프 | `schedule()` 566–830 (`get_computed_blocks` → `allocate_slots`) | pin 해제 순서(할당 성공 **후**) 및 deadlock 해제 지점 |
| 종료 경로 | `update_from_output` 1420–1428 `_handle_stopped_request` → `_free_request` (1813) → `_free_blocks` (1831) | finish 훅 = pin 결정 지점. `delay_free_blocks` 선례 존재 |
| Abort 경로 | `finish_requests` (1750) → `_free_request` | abort는 **pin하지 않음** (명시 분기) |
| 요청 추가 | `add_request` (1728) → `_enqueue_waiting_request` | arrive 훅 |
| KV free | `KVCacheManager.free` → `coordinator.free(request_id)` | free 미호출 = ref 유지 = pin. **수정 불필요** |
| 사용자 파라미터 | `vllm_xargs` → `SamplingParams.extra_args` (chat/completion protocol 이미 지원) | 포크처럼 protocol 3곳 수정 불필요 → `program_id` 등을 `extra_args`로 수신 |
| Request | `v1/request.py` (`arrival_time`, `priority`, `num_preemptions`, `resumable`) | `program_id`/`is_last_step`/`tool_hint`는 `extra_args`에서 읽는 property로 추가 |
| KV connector | `_connector_finished` → `delay_free_blocks` | connector가 free 지연 중이면 pin 불가(§6.5) |

> `[검증필요]` 현재 저장소의 **streaming session**(`resumable`, `WAITING_FOR_STREAMING_REQ`, `_update_request_as_session`)은 "같은 request를 이어 쓰는" 별도 multi-turn 메커니즘이다. Continuum과 직접 충돌하진 않지만(서로 다른 request_id를 쓰는 stateless agent가 대상) 두 기능의 상호작용은 아직 분석하지 않았다. P0에서 확인한다.

---

## 4. 목표 아키텍처

```
vllm/v1/core/sched/continuum/
├── __init__.py
├── config.py          # ContinuumConfig (dataclass; SchedulerConfig에서 참조)
├── cost_model.py      # 순수함수: solve_ttl(), t_default(), benefit()   ← 논문 Eq.1/2
├── tool_stats.py      # ToolDurationStore: S[f], S_global, CDF, 후보 열거
├── workload_stats.py  # QueueDelayWindow(T), MemorylessEstimator(η)
├── profile.py         # PrefillReloadModel + 로드/저장 + (옵션) 온라인 보정
├── tool_parser.py     # ToolCallParser 프로토콜 + Hint/Regex/TokenId 구현
├── pin_manager.py     # PinTable: pin/expire/victim/lookup (min-heap by expiry)
└── handler.py         # ToolCallHandler: on_arrive / on_finish / decide_ttl
vllm/v1/core/sched/request_queue.py   # + ContinuumRequestQueue
vllm/v1/core/sched/scheduler.py       # 훅 5곳 (§6)
vllm/config/scheduler.py              # policy Literal + continuum_* 필드
vllm/v1/request.py                    # program_id / is_last_step / tool_name property
vllm/entrypoints/... (선택)           # X-Program-Id 헤더 → extra_args (편의)
vllm/continuum/profile_cli.py (또는 benchmarks/continuum/profile_prefill.py)  # offline profiler
```
설계 원칙: (1) **순수 로직(cost_model, stats)과 엔진 의존 코드(pin_manager, handler)를 분리** → GPU 없이 단위테스트. (2) 모든 시간은 **주입 가능한 monotonic clock**. (3) `policy != "continuum"`이면 오버헤드 0 (훅은 `if self.continuum is not None`).

### 4.1 모듈별 명세

#### (A) `cost_model.py` — 논문 Eq.1/2 (순수 함수)
```python
def solve_ttl(durations_sorted: Sequence[float],  # S[f] 또는 S, 오름차순
              benefit: float,                      # B = T·η + PrefillReload(r)   [초]
              ) -> float:
    # n = len(durations); 후보 τ_i = d_i (i=1..n), P(τ_i) = (#{d ≤ τ_i})/n
    # value_i = P_i·B − τ_i ;  value_0 = 0 (τ=0)
    # 중복 값은 마지막 인덱스의 P를 사용. return argmax (동률이면 더 작은 τ)
```
- O(n) 스윕 (정렬 상태 유지 → 삽입 시 `bisect.insort`, 상한 `max_history` 초과 시 FIFO 제거를 위해 별도 deque 병행). `[D2]`
- 결과 `τ* ≤ 0.0` 이거나 `B ≤ 0` → pin 안 함.
- `t_default(B, mean=1.0)`: Exp(mean μ) 가정에서 `P=1−e^{−τ/μ}`, `d/dτ = (B/μ)e^{−τ/μ} − 1 = 0` ⇒ `τ = μ·ln(B/μ)` (B>μ일 때, 아니면 0). 논문 "unit mean" 단위를 **μ=1s** 로 해석 `[D3]`, `continuum_default_tool_mean_s`로 노출. T=0, η=1 초기화이므로 cold-start에서 `B = PrefillReload(r)` → 컨텍스트가 길수록 TTL이 자동으로 길어짐(공개 코드의 고정 2.0s보다 합리적).
- 검증: 브루트포스(촘촘한 τ grid) 대비 일치, B 스케일에 대한 단조성, 닫힌 해와의 일치.

#### (B) `tool_stats.py` — `S[f]`, `S`
- `ToolDurationStore.record(tool, seconds)`, `select(tool) -> (sorted_list, tier)` 에서 §1.3의 3단계 분기(K=100)를 한 곳에 캡슐화.
- 메모리 상한: tool당 최근 `max_history`(기본 1000, `[D2]`)개 윈도우 → 분포 drift 대응. 윈도우 크기는 논문 미명시.
- tool 종류 폭증 방지: tool 수 상한(기본 256) 초과 시 LRU로 제거.

#### (C) `workload_stats.py`
- **T (queue delay)**: 샘플 = "연속 turn(program의 2번째 이상 request)이 **pin이 없는 상태로** 도착해 첫 스케줄될 때까지의 대기시간"; `deque(maxlen=W)` 평균, `W=100` `[D4]`. 샘플 0개면 T=0 (논문 초기값). 정체 방지를 위해 마지막 샘플이 오래되면(>`T_stale_s`) 지수 감쇠 `[D4]`.
  - 측정 지점: `add_request`에서 `t_enq`, waiting 루프에서 `allocate_slots` 성공 직후 `now − t_enq`. **preempted 재진입은 제외**(turn 간 지연이 아니라 batch 내 경합).
- **η**: program이 종료될 때 총 turn 수 N 확정. `Corr(k, N−k)`를 모든 완료 program의 `k=1..N−1`쌍을 풀링해 계산. 충분통계(Σk, Σ(N−k), Σk², Σ(N−k)², Σk(N−k), count)를 N별 닫힌식(`Σk=N(N−1)/2`, `Σk²=(N−1)N(2N−1)/6` …)으로 O(1) 갱신, 최근 `W_p`개 program 윈도우 `[D5]`. 분산 0이면 η=1(cold-start 기본), 결과 `clip(−1, 1)`.
  - 완료 판정: `is_last_step=True` 요청 finish, **또는** 마지막 finish 후 `program_idle_timeout_s`(기본 600s) 무응답 → 만료 처리(abandoned program도 N 확정/메모리 회수) `[D5]`.
  - **sanity test**: 모든 program N 고정 → η=1, N~Geometric → η≈0 (논문 §4.1 예시와 동일).

#### (D) `profile.py` — PrefillReload(r) 모델
- `PrefillReloadModel(coef=(a,b,c), reload_bw_Bps, kv_bytes_per_token)`:
  - offload 없음: `t = a·L² + b·L + c` (L = 재구성할 context token 수; 논문대로 full prefill 근사)
  - offload(KV connector) 있음: `t = L·kv_bytes_per_token / reload_bw` (+ 상수 지연). 논문: 두 모드 중 택일.
  - `kv_bytes_per_token`은 `kv_cache_config`(page size ÷ block_size, KV group 합산)에서 계산 — hybrid(SWA/mamba) 모델은 group별 합산 `[검증필요]`.
- **Offline profiler** (논문 §5.2 재현): prefix cache OFF, `max_tokens=1`, L∈{1k,2k,4k,…,max_model_len}로 prefill 시간 측정 → `numpy.polyfit(deg=2)`; offload 켜진 경우 GPU↔CPU 평균 throughput 측정. 결과를 JSON(`{model, gpu, dtype, tp, coef, bw}`)으로 저장, `--scheduler-continuum-profile PATH`로 로드. 모델/하드웨어 mismatch 시 경고.
- **Profile이 없을 때 fallback** `[D6]`: (1) 기본: 보수적 선형 모델 `t = L / fallback_prefill_tok_per_s`(config, 기본 20k tok/s급은 7B/H100 가정 — 사용자 경고 로그), (2) 선택: 온라인 보정 — 실제 chunked-prefill step 시간으로 EMA 회귀(배치 간섭으로 노이즈 큼, `[검증필요]`). 논문은 오프라인만 사용하므로 (1)+프로파일 권장.

#### (E) `tool_parser.py` — tool 식별 + last-step 판정
공개 코드는 finish 때마다 **전체 출력 detokenize**(스케줄러 critical path)를 한다. 개선안 — 파서 플러그형, 비용 순:
1. **HintParser (기본·권장)**: client가 `vllm_xargs={"program_id":..., "tool_name"?:..., "is_last_step"?:...}` 전달. 비용 0. 단 `tool_name`은 응답을 보기 전엔 모르므로 **"직전 request가 호출한 tool"을 다음 request가 알려주는 방식**(`last_tool`)도 수용 → 도착 시 `S[last_tool]`에 duration 기록(논문 Alg.1 L4–5 형태와 정확히 일치).
2. **TokenIdParser**: 모델별 tool-call 시작 special token(예: `<tool_call>`, `<|python_tag|>`) id가 출력 토큰에 있는지 검사(O(n) 스캔, detokenize 없음) → tool 유무만 판정(tool 이름은 불가 → global `S` 사용).
3. **RegexParser (mini-swe-agent 호환)**: 출력 **마지막 ≤N 토큰만** decode 후 ```` ```bash ```` 첫 단어. 공개 코드 재현·평가용.
- 인터페이스: `parse(request) -> ParsedTurn(has_tool_call: bool, tool: str|None)`.
- **last-step 판정 규칙**: `is_last_step` hint가 있으면 최우선, 없으면 `not has_tool_call` (논문 §5.2 "parsed to contain a tool call이 아니면 last step").

#### (F) `pin_manager.py` — PinTable
```python
@dataclass
class PinEntry: program_id; request: Request; expire_at: float; program_arrival: float; num_blocks: int
class PinTable:
    by_program: dict[str, PinEntry]          # program당 최대 1개 (ReAct = program당 in-flight 1개)
    expiry_heap: list[(expire_at, program_id)]   # lazy deletion
    def pin(entry); def pop(program_id); def expire(now, is_waiting: Callable) -> list[PinEntry]
    def victims(n_needed_blocks) -> Iterator[PinEntry]   # program_arrival 최신순
```
- **불변식**: pinned request의 blocks는 `kv_cache_manager.free()`가 호출되지 않은 상태 = ref>0. `PinTable`이 소유하는 동안 `scheduler.requests`에는 없음(finish 처리 완료) 하지만 **coordinator는 request_id로 blocks를 추적**하므로 request_id 충돌 방지 위해 pin 중에는 해당 id 재사용 금지(vLLM은 id 유일).
- 해제는 항상 `PinTable.pop → kv_cache_manager.free(entry.request)` 한 경로로 통일(누수 방지).
- 매 step 만료 스캔은 heap top만 보므로 **O(#만료+1)** (공개 코드 O(#pins·|Q|) 개선).
- `is_waiting(program_id)`: 큐가 관리하는 `program_id → count` dict (O(1)).

#### (G) `handler.py` — ToolCallHandler (논문 Fig.7)
```python
class ToolCallHandler:
    def on_request_arrive(self, req, now) -> None
        # 같은 program의 직전 finish 시각이 있으면 duration = now − t_finish → S[last_tool], S 에 기록
        # program 첫 turn이면 program_arrival = now 기록 (priority key)
    def on_request_finish(self, req, now) -> PinDecision   # (pin: bool, ttl: float)
        # parse → last step? → solve_ttl(S 선택, B = T·η + PR(ctx_len)) 
    def on_request_scheduled(self, req, now)   # T 샘플 기록, 해당 program의 pin 소거 신호
    def on_program_end(self, program_id)       # η 갱신
```
논문의 3개 인터페이스(`func_call_finish`, `update_tool_call_time`, `set_up_ttl`)는 각각 `on_request_finish`(기록부) / `on_request_arrive` / `decide_ttl`에 대응.

#### (H) `ContinuumRequestQueue` (우선순위 §1.4)
- 정렬 키: `(0 if preempted else 1, 0 if pinned else 1, program_arrival, request.arrival_time, request_id)`.
- **정적 키 보장**: ReAct에서 program은 in-flight request가 1개이고, 큐에 있는 동안은 unpin되지 않으므로(Alg.1 L16) pinned 여부는 **enqueue 시점에 확정**하면 된다. 예외(deadlock 해제로 큐 대기 중 unpin) 시에만 `remove + re-add`.
  → 힙(`heapq`) + lazy deletion으로 O(log n) (공개 코드 O(n) 스캔 대체). 단 `prepend_request` 계열 API 계약(PRIORITY 큐처럼 순서가 키로 결정)을 만족해야 함.
- `program_id → 큐 내 request 수` dict 유지 (unpin 판정용).
- `waiting`/`skipped_waiting` 두 큐 간 비교는 `peek_request()`의 키 튜플 비교로 `_select_waiting_queue_for_scheduling` 확장 `[D7]`.
- `program_id` 없는 일반 요청: `program_arrival = request.arrival_time`, not pinned → 기존 FCFS와 동일하게 동작 (**비-agent 트래픽 호환**).

---

## 5. 핵심 알고리즘 상세

### 5.1 `on_request_finish` — TTL 결정 (Alg.1 L6–12)
```
parsed = parser.parse(req)
if is_last_step(req) or not parsed.has_tool_call or req aborted/length-failed: free KV, program 종료 처리; return
f      = parsed.tool                      # None 가능 → 전역 S
S, tier = tool_stats.select(f)            # tier ∈ {DEFAULT, GLOBAL, PER_TOOL}
PR     = profile.prefill_reload(ctx_len = req.num_tokens)
B      = T.mean() * η.value() + PR        # T=0 초기값
ttl    = t_default(B) if tier == DEFAULT else solve_ttl(S, B)
if ttl >= ttl_min (예 10ms) :  pin_table.pin(req, now+ttl)  # free 생략
else: free KV
```
- `ctx_len`: 다음 turn에서 재구성해야 할 prefix = 현재까지의 `num_tokens`(prompt+output).
- `ttl_max` 가드(config, 기본 ∞)는 논문에는 없는 안전장치 — 기본값은 논문 동작 유지 `[D8]`.

### 5.2 Waiting 루프에서의 순서 (Alg.1 L13–26, 현재 저장소 대응)
1. `schedule()` 시작: `pin_table.expire(now, is_waiting)` → 만료 + 큐에 없는 program만 free.
2. `request = queue.peek_request()` → `get_computed_blocks(request)`: pinned blocks는 아직 hash table + ref>0이므로 **prefix cache hit** 로 잡힌다.
3. `allocate_slots(...)` **성공 후에만** 같은 program의 pin을 `pop → free`. (pin 블록은 이미 `touch`되어 ref가 증가했으므로 free해도 새 request가 보유 → evict 안 됨. **먼저 free하면 free-queue에 올라가 다른 할당에 evict될 위험** `[D9]`)
4. 실패(`new_blocks is None`) 시 deadlock 회수(§5.3) 후 재시도, 그래도 안 되면 break.

### 5.3 메모리 회수 순서 (논문은 deadlock만 명시 → 일반화) `[D10]`
`allocate_slots` 실패 시(running 루프·waiting 루프 공통):
1. **pin 회수 먼저**: `victims()`를 program_arrival 최신순으로 하나씩 free하며 재시도. (논문 §5.2: "선택 victim = pinned_requests 중 latest program arrival"). 단 요청 program보다 **먼저 도착한 program의 pin은 회수하지 않음**(순서 역전 방지)… 단 deadlock(running 비어 있음) 시에는 무조건 회수.
2. pin이 없으면 기존 vLLM preempt(`running.pop()` 또는 priority 규칙). 공개 코드는 `is_last_step` 아닌 running 중 program 도착이 가장 늦은 것을 victim으로 삼음 → 동일 규칙 채택(program-level FCFS와 일관) `[D10]`.
- 근거: pin 회수는 계산된 작업을 버리지 않지만 running preempt는 `num_computed_tokens=0`으로 재계산을 유발.

### 5.4 Abort / reset / 종료 처리
- `finish_requests(abort)`: pin 하지 않음. 해당 program의 기존 pin도 해제.
- `reset_prefix_cache`: pin 전체 해제 후 수행(ref>0 블록이 있으면 reset 실패하므로 필수) `[검증필요: reset_prefix_cache가 running만 preempt하는 경로 확인]`.
- `shutdown`/sleep mode: pin 전체 해제.
- `_connector_finished`가 `delay_free_blocks=True`면(원격 KV 전송 대기) **pin 하지 않고** 기존 경로 유지(1차 구현 범위 제외, §8).

---

## 6. 스케줄러 변경 지점 (현재 저장소 기준)
| # | 위치 | 변경 |
|---|---|---|
| H1 | `config/scheduler.py:21,109` | `SchedulerPolicy`에 `"continuum"`, `continuum_*` 필드(profile 경로, K, W, ttl_min/max, parser 종류, idle timeout) |
| H2 | `request_queue.py` | `SchedulingPolicy.CONTINUUM`, `ContinuumRequestQueue`, `create_request_queue` |
| H3 | `Scheduler.__init__` (159–170) | `self.continuum = ContinuumManager(...)` (policy가 continuum일 때만), prefix caching 비활성이면 `ValueError` |
| H4 | `add_request`/`_enqueue_waiting_request` (1728/1561) | `handler.on_request_arrive` ; 큐 enqueue 시 pinned/preempted 키 계산 |
| H5 | `schedule()` 상단 + running 루프 allocate 실패(~480) + waiting 루프 allocate 성공/실패(~700) | expire / 회수 / pin pop (§5.2–5.3) |
| H6 | `update_from_output` finish (~1428) → `_free_request`/`_free_blocks` | `on_request_finish` → pin 시 `kv_cache_manager.free` 생략 (`delay_free_blocks` 선례처럼 분기) |
| H7 | `_select_waiting_queue_for_scheduling` (1567) | continuum 키 비교 |
| H8 | `finish_requests` (1750), `reset_prefix_cache` (1858), `shutdown` (1983) | pin 정리 |
| H9 | `make_stats` / metrics | pin 관련 지표(§7) |

`Request` 확장: `program_id`, `is_last_step`, `last_tool`(hint) — `sampling_params.extra_args`에서 읽는 property (프로토콜 수정 불필요). 선택적으로 `X-Program-Id` 헤더 → `extra_args` 매핑(편의).

---

## 7. 관측성 (Observability)
- Prometheus: `continuum_pin_total`, `continuum_pin_hit_total`(pin 중 다음 request 도착), `continuum_pin_expired_total`(TTL 만료 후 도착 = **낭비**), `continuum_pin_forced_unpin_total`(deadlock/회수), `continuum_pinned_blocks`(gauge), `continuum_ttl_seconds`(histogram), `continuum_T_seconds`, `continuum_eta`, `continuum_tool_duration_seconds{tier}`.
- 로깅: 공개 코드의 `Continuum_Recorder` 대응 — 디버그 JSON dump는 옵션(`VLLM_CONTINUUM_TRACE_DIR`).
- 핵심 진단 지표: **pin hit rate**, **TTL 효율 = pin_hit_total / pin_total**, **평균 per-turn queueing delay**(논문 Fig.4/11의 bubble).

---

## 8. 범위와 비범위
**1차 범위 (논문 재현)**: 단일 엔진, GPU-only 및 LMCache식 offload(connector) 중 `delay_free_blocks=False`인 경우, Hint/Regex/TokenId parser, Eq.2 + 3단계 cold-start + η + T + offline profiler, program-level FCFS, deadlock 회수.
**비범위/후속**: DP·multi-node 라우팅(sticky session은 상위 라우터 책임), parallel tool call/non-ReAct 흐름(논문 §7에서도 future work), async-scheduling과의 최적화, SSD tier, connector가 finish를 지연하는 경우의 pin, speculative decoding 상호작용 `[검증필요]`.

---

## 9. 검증 계획
### 9.1 단위 테스트 (GPU 불필요) — `tests/v1/core/sched/continuum/`
| 대상 | 케이스 |
|---|---|
| `solve_ttl` | 브루트포스 grid 일치 / 빈 `S`·B≤0 → 0 / 중복 값 / B 증가 시 τ* 단조 증가 / `t_default` 닫힌식 |
| `tool_stats.select` | \|S\|≤K→DEFAULT, \|S\|>K & \|S[f]\|≤K→GLOBAL, 이상→PER_TOOL 경계값(K=100) |
| `MemorylessEstimator` | N 고정 → η=1, Geometric → η≈0(통계 허용오차), 분산 0 처리, idle-timeout 정산 |
| `QueueDelayWindow` | 초기 T=0, 윈도우 교체, 감쇠 |
| `PrefillReloadModel` | 2차 fit 복원, offload 모드 전환 |
| `ContinuumRequestQueue` | 우선순위 3키 조합 전수, lazy-deletion, program 카운트, 비-agent 요청이 FCFS와 동일 |
| `PinTable` | expiry heap, waiting 중 program은 만료 무시, victim 순서 |

### 9.2 스케줄러 통합 (기존 `tests/v1/core/test_scheduler.py`의 `create_scheduler` 패턴 + mock clock)
- pin → 다음 turn이 TTL 내 도착 → **prefix hit 토큰 수 = 이전 컨텍스트**, free 호출 없음.
- TTL 만료 후 도착 → hit 0, pin_expired 카운트.
- 메모리 포화: pin이 전부 차지 → 신규 요청 스케줄 가능(deadlock 없음), victim = 최신 program.
- preempted > pinned > program FCFS 순서 보장.
- abort 시 pin 누수 없음 (`block_pool` free 블록 수 보존 불변식).

### 9.3 E2E / 성능 재현
- 소형 모델(`facebook/opt-125m`)로 tool 지연을 시뮬레이션하는 trace replayer (`benchmarks/continuum/replay.py`): program 도착 Poisson, tool duration은 논문 Table 2 통계(SWE-bench: 평균 925ms, σ 3550ms의 **heavy-tail**) 모사.
- 비교군: `fcfs` / program-FCFS only / static TTL(T_default) / full Continuum. 지표: avg·P95 job completion time, throughput (논문 Fig.8·10·16 재현).
- 기대 경향(논문): full > static TTL > program-FCFS > vLLM; turn 수 증가 시 격차 확대(Fig.14). **절대 수치 재현은 GPU/모델 환경 의존이므로 경향성 검증**.

---

## 10. 구현 단계 (마일스톤)
| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **P0** 사전 분석 | streaming session·reset·async scheduling·connector 상호작용 코드 확인, `Request.__lt__`/큐 계약 확정 | `[검증필요]` 항목 해소 |
| **P1** 순수 로직 | `cost_model`, `tool_stats`, `workload_stats`, `profile`(모델·fit) + 단위테스트 | 9.1 통과 |
| **P2** 큐/PinTable | `ContinuumRequestQueue`, `PinTable`, config/policy 등록 | 큐·테이블 테스트 통과 |
| **P3** 스케줄러 통합 | H3–H8, parser(Hint/Regex/TokenId), metrics | 9.2 통과, `policy=fcfs` 회귀 없음 |
| **P4** Profiler/Replay | offline profiler CLI, trace replayer | 9.3 경향성 재현 |
| **P5** 하드닝 | 장시간 soak(pin 누수/힙 성장), 문서·튜닝 가이드 | 메모리·블록 불변식 유지 |

---

## 11. 결정/가정 목록 (논문 미명시 → 리뷰 요청)
| ID | 결정 | 이유 / 대안 |
|---|---|---|
| D1 | 본문 "threshold M"을 **K=100**으로 해석 | 같은 문단에 `K = 100` 명시 |
| D2 | `S[f]` 윈도우 상한 1000(config) | 논문 미명시, drift·메모리 균형 |
| D3 | `T_default`의 "unit mean"을 **1초**로 해석, μ는 config | 단위 미명시. `τ=μ·ln(B/μ)` |
| D4 | T = 최근 W=100개 평균, preempted 재진입 제외, stale 감쇠 | "sliding window average" 외 미정의 |
| D5 | η = 완료 program의 (k, N−k) 풀링 상관, 최근 W_p 윈도우, idle-timeout 600s | N은 종료 후에만 확정 |
| D6 | profile 부재 시 보수적 선형 fallback + 경고 | 논문은 offline profile 전제 |
| D7 | 두 waiting 큐 비교를 continuum 키로 확장 | 현재 저장소 구조(skipped_waiting) 때문 |
| D8 | `ttl_max` 기본 ∞ (논문 동작) | 안전장치는 opt-in |
| D9 | pin 해제는 **할당 성공 후** | block evict race 방지 |
| D10 | 할당 실패 시 pin 회수(최신 program 순) → 그 다음 running preempt(최신 program 순) | 논문은 deadlock 케이스만 기술, 재계산 회피 |

---

## 12. 리스크
| 리스크 | 영향 | 완화 |
|---|---|---|
| pin 블록이 hit 안 되는 경우(컨텍스트 prefix 불일치: 템플릿/system prompt 변경, cache_salt) | pin 낭비 | hit rate 지표, program별 hit 실패 시 TTL 학습/비활성(후속) |
| Hybrid KV group(SWA, mamba)에서 pin된 블록이 `remove_skipped_blocks`로 줄어듦 | 효과 감소 | 1차는 full-attention 모델 대상, hybrid는 `[검증필요]` |
| 서버측 tool duration에 client 오버헤드 포함 | 분포 편향 | 의도된 동작(실제 gap이 필요한 값) |
| η/T 초기 불안정 | cold-start TTL 부정확 | 3단계 cold-start가 방어(논문 설계) |
| 스케줄러 hot path 지연 | step latency | heap/dict O(1)~O(log n), 논문 Table 4 수준(≤ +0.1ms) 목표를 벤치로 확인 |
| 포크 구조와 상이 | 이식 오류 | 포크 코드는 **참고용**, 논문 사양 기준 테스트로 검증 |
