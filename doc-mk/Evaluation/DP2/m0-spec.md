# DP2 Simulator — M0 사양 (Spec Freeze 후보)

> 상태: **draft — 소유자 확정 대기** (§13). 확정되면 이 문서와 `sim/configs/*.json`을 동결하고 git revision을 기록한다 (§12).
> 상위 문서: [`sim-extension-scope.md`](sim-extension-scope.md) (범위·단계), [`simulation-plan.md`](simulation-plan.md), [`benchmark.md`](benchmark.md), [`qa-criteria-dp2.md`](qa-criteria-dp2.md). 규칙: `.claude/skills/evaluation/SKILL.md`.
> 기계가 읽는 사양: `sim/configs/{dp2_params,internode_links,scenario_params}.json`, `sim/configs/result_schema.json`. 참조값: `sim/m0_reference_values.json` (`sim/m0_check.py`가 재생성·검증).

# 0. M0 산출물과 이번 단계의 결과

| 산출물 | 위치 | 상태 |
|---|---|---|
| 사양 문서 | 이 문서 | draft |
| 파라미터 레지스터 (32개, 항목별 evidence·sweep·확정 필요 여부) | `sim/configs/dp2_params.json` | draft |
| 노드 간 링크 profile (신규, ASSUMED) | `sim/configs/internode_links.json` | draft |
| 시나리오 시작 파라미터 19개 | `sim/configs/scenario_params.json` | draft (`benchmark.md`와 이름 일치 검사 통과) |
| 결과 스키마 | `sim/configs/result_schema.json` | draft |
| 참조값 생성·검증 | `sim/m0_check.py`, `sim/m0_reference_values.json` | `python m0_check.py --verify` 통과 |

**M0에서 새로 확인한 것 (참조값 계산 결과, 시뮬레이션 아님)**

| # | 발견 | 조치 |
|---|---|---|
| F-1 | **32K 토큰 Prefill은 H100에서 단독 1.88 s**(큐 0)라 SLO(TTFT 2 s)에 거의 닿는다. `dp2_tool_large_result`(tool 32K), `dp2_prefill_burst`(prompt 최대 32K)는 Baseline이 구조적으로 infeasible | tool 16K, prompt 8/12/16K로 수정 (`scenario_params.json`의 `_m0_fix`, `benchmark.md` 갱신) |
| F-2 | **128K~256K cold Prefill은 TTFT 2 s를 단독으로 넘는다.** `dp2_long_ctx_decode_offload`를 cold 세션 시작으로 두면 항상 infeasible | 이미 resident한 긴 History의 **재개 Turn**(tool 2K)으로 변경. DP1도 증분 query만 Prefill하는 같은 관례 |
| F-3 | **DP1 모델은 HBF를 GPU-direct Decode attention 대상으로 다루지 않는다** (`decode_step_s`가 `attention_capable`이 아닌 Tier에 inf). DP2는 HBF 읽기 Decode를 후보로 쓴다 | 새 규칙 A12 정의 (§4.5) |
| F-4 | **CXL-PNM Decode는 컨텍스트 약 38K 이하에서만 TPOT 50 ms 충족** (batch 1), HBF 약 120K(H100)/129K(B200). 앞선 rationale의 "약 60K"/"약 150K"는 KV 읽기만의 하한 | rationale 수정, 후보 feasibility는 §6.3 제약으로 처리 |
| F-5 | **CB-1은 H100에서만 압박이 걸린다.** KV 풀 76.8 GiB(H100) 대비 수요 약 82.5 GiB, B200은 풀 184 GiB로 압박 없음 | DP1 CB와 같은 관례 유지. B200의 CB는 `saturated` 예상 (DP1 결과와 일치) |

# 1. 범위 (동결 대상)

- 결정: Turn 단위 `ExecutionPlan = (n_p, n_d)`. 실행 중 재결정과 Tier 이동은 없다 (DP1 소관).
- 후보: C1(스케줄링 시점), C2(사전 계획). **Cost Model은 같다.**
- 참조 정책(별점 아님): D-local-always, Oracle, P-retain. Common Reference Baseline은 **Baseline-PD-fixed** (§7).
- 시스템: SYS-H100, SYS-B200 통합. 모델 Llama-3.1-70B BF16, SLO TTFT P99 ≤ 2 s / TPOT P99 ≤ 50 ms (공통 고정).
- **비범위**: prefix cache 공유, NIXL 프로토콜 오버헤드, preemption·recompute, TP 병렬 효율, HBF endurance·write amp, 전력, KV 외 데이터(LoRA/MoE/Agent/Tool)의 접근 비용(CB-3에서는 용량 점유만 반영).

# 2. 표기

- `n_p = (node)`: Prefill은 항상 GPU/HBM에서 실행하므로 노드만 정한다. `n_d = (node, tier)`, tier ∈ {`hbm`, `custom_hbm`(Samsung Custom HBM, ScHBM), `cxl_pnm`, `hbf`}.
- Tier id는 DP1 그대로: `hbm, custom_hbm, cxl_pnm, dram, hbf, ssd_pim`. `dram`·`ssd_pim`은 Decode 시작 Tier가 아니다(blocking swap-in 후 HBM에서 Decode).
- 시간은 초, 용량은 byte, 대역폭은 byte/s. KV는 `kv_bytes_per_token = 327,680`.
- **세션 KV의 owner**: 세션의 KV가 영속적으로 놓인 `(node, tier)`. 전송은 복사이며, Turn이 끝나면 owner는 `n_d`다(§4.3).

# 3. 시스템·토폴로지

| 항목 | 사양 |
|---|---|
| 노드 | 8-GPU HGX 1대 = DP1 `SystemSpec` 1개(GPU 8장 합산: HBM 용량·BW, FP16 연산). `gpu_bw_eff=0.9`, `gpu_compute_eff=0.5` (DP1 값). TP 병렬 효율은 반영하지 않음 |
| 인스턴스 | 노드당 TP8 인스턴스 1개, 같은 SYS의 동일 노드로 구성 |
| 기본 구성 | CB 1P+1D, Stress/Dynamic 2P+2D, `dp2_session_size_skew` 2P+4D, `dp2_long_ctx_decode_offload` 1P+2D, Scalability 2~64 노드 |
| 역할 | Baseline은 P/D 역할 고정. Planner는 role-flexible(모든 노드가 Prefill 또는 Decode 후보) |
| 노드 내 메모리 | 6종, DP1 `system-specs.md` 값 그대로 (`load_profile`) |
| 노드 간 링크 | `internode_links.json`: 기본 `rdma_400g_1rail` = 50 GB/s, 지연 100 µs, 효율 1.0 (ASSUMED). sweep 12.5 / 50 / 200 / 400 GB/s |

# 4. 물리 모델 규칙

## 4.1 재사용과 신규

DP1 `model.py`는 **read-only import**로 쓴다 (`prefill_s`, `gpu_non_attention_decode_s`, `hbm_attention_s`, `offloaded_attention_s`, `decode_step_s`). 아래 4.2~4.7은 DP2 신규 규칙이다.

## 4.2 Iteration 모델 (노드별 continuous batching)

노드는 iteration 단위로 진행한다. 스케줄 규칙(A06): **decode 우선**, 남은 token budget(8,192)을 FCFS chunked prefill(chunk ≤ 2,048)에 배정. `max_num_seqs` 256.

한 iteration의 Decode 시퀀스 집합을 D, Prefill chunk 토큰 수를 `c`, `n_tok = |D| + c`라 하면

```text
T_nonattn = gpu_non_attention_decode_s(n_tok)            # weight/FFN roofline (DP1)
T_gpu_att = Σ_{HBM 시퀀스} hbm_attention + Σ_{HBF 시퀀스} gpu_direct_attention (4.5)
            + prefill chunk attention  (= max(compute, History 읽기 BW))
T_off(t)  = offloaded_attention_s(tier t의 시퀀스 묶음)   # custom_hbm, cxl_pnm. 병렬 장치
T_iter    = κ × ( T_nonattn + max( T_gpu_att , max_t T_off(t) ) )      # κ=1.0 (A07), sweep 1.0/1.15/1.3
```

Prefill–Decode 간섭은 별도 계수가 아니라 **iteration에 Prefill chunk가 섞이는 효과**로 나타난다. κ는 커널·스케줄링의 잔여 비효율을 위한 배수이며 가정이다.

## 4.3 요청 생명주기

```text
arrival → [global queue] → 결정(C1/C2) → staging(History → n_p HBM) → Prefill(chunked) → 첫 토큰(TTFT 종료)
        → handoff(새 KV 및 필요 시 History → n_d) → Decode steps → 완료(owner = n_d)
```

- **staging**: History가 GPU-reachable HBM이면 0. HBF면 제자리 읽기(전송 없음). `dram`/`custom_hbm`/`cxl_pnm`/`ssd_pim`이면 HBM으로 **승격**(A11). 승격과 연산은 **순차**(overlap 없음, 보수적). 오프로드 Prefill attention은 PNM 연산(3.28 TFLOPS)으로 비현실적이라 허용하지 않는다.
- **P 경로**(`n_p ≠ History owner 노드`): History를 owner의 Tier에서 `n_p`의 HBM으로 **복사**(owner는 History를 유지). P 노드는 상태를 유지하지 않는다(A10): handoff 후 `n_p`의 임시 KV를 폐기.
- **handoff 바이트** = `새 KV(q × kv_bytes)` + (`n_d.node ≠ History owner 노드`이면 History 전체). `n_d.tier ≠ hbm`이면 해당 Tier로 쓰는 시간(Tier `write_bw`) 포함.
- **첫 토큰**은 `n_p`에서 Prefill이 끝나는 iteration 종료 시점에 나온다. KV handoff는 그 뒤에 진행되고 두 번째 토큰 간격에 반영된다.

## 4.4 전송과 링크 (A05)

- 자원: `nic_egress(node)`, `nic_ingress(node)`, `tier_ext(node, tier)`(HBM·HBF 제외 Tier의 host 링크), `hbm_write(node)`. 코어 fabric은 non-blocking.
- 모든 전송(노드 간 복사, 승격, 강등, swap-in)은 자원 집합을 쓰고, **활성 전송들이 max-min fair share**로 대역폭을 나눈다. 이 규칙이 DP1의 `link_interference`(전송이 서빙 대역폭을 줄임)를 포함한다.
- 전송 시간 = `지연 + bytes / 속도`. 속도는 사용 자원 중 최소 점유율(파이프라인). 단일 전송 이론값은 `m0_reference_values.json`(`history_move_s`)에 있다.

## 4.5 Decode 규칙

- `hbm`: DP1 `decode_step_s(..., "hbm")`.
- `custom_hbm`, `cxl_pnm`: DP1 `offloaded_attention_s` 그대로 (A13).
- **`hbf` (신규, A12)**: GPU가 직접 읽는다.
  `T_attn = max( kv_bytes / (hbf_read_bw × gpu_bw_eff), attention_flops / (gpu_compute × eff) ) + layers × latency_s`, `T_step = T_nonattn + T_attn`.
- `dram`, `ssd_pim`: Decode 불가. **blocking swap-in**으로 HBM에 올린 뒤 HBM에서 Decode(A14). HBM KV 풀에 자리가 없으면 대기한다.
- Decode 중 Tier 이동과 재결정은 없다 (DP1). 컨텍스트는 step마다 1 증가하고 KV append는 n_d Tier에 쓴다 (plan 시점에 `ctx_end`분 예약).

## 4.6 KV 풀, 외부 allocator, capacity-fit 강등

- **KV 풀 규약(A08)**: `풀 = Tier 용량 × hbm_capacity_mult`, weight는 풀에서 제외 (DP1 규약). CB의 x0.12 / x0.20도 같은 의미다.
- **외부 allocator(A09)**: DP1과 같다. 순서 `hbm(목표 80%) > dram > cxl_pnm > hbf > ssd_pim > custom_hbm`(목표 90%).
- **예약**: plan 시점에 `n_d` Tier에 `ctx_end` byte를 예약한다. 가용 조건은 `점유 + 예약 + 필요량 ≤ 목표율 × 풀`.
- **capacity-fit 강등(A24)**: HBM 풀이 부족한 승격은 idle LRU 세션을 allocator 순서의 다음 Tier로 강등해 자리를 만든다. 강등은 전송으로 링크를 쓰고, DP1 정책이 아니라 **물리적 필요**다. 후보가 없으면 요청은 대기한다.

## 4.7 Baseline Decode 의미 (A14)

DP1 As-Is와 같다. GPU attention만 쓰고 오프로드 Tier를 쓰지 않는다. HBM/HBF 밖의 KV는 swap-in 후 Decode한다.

# 5. Workload 사양

## 5.1 생성기

- **세션**: Turn을 `turns`번 반복(기본 8), 끝나면 같은 초기 파라미터의 새 세션으로 교체. Turn k의 입력은 `tool` 토큰(첫 Turn은 `hist0` 또는 `prompt`), 출력은 `out`, History는 누적.
- **Tool 대기**: lognormal(중앙값 10 s, σ 0.5), 세션 Turn 사이 (ASSUMED). 외부 demotion 시나리오는 대기를 길게 가정.
- **도착**: open loop(Poisson, MMPP burst, ramp) 또는 closed loop(동시 세션/클라이언트 수 고정).
- **bg_decode**: D 노드를 바쁘게 만드는 배경 Decode 세션(8K 컨텍스트, 출력 2,048, HBM 상주).
- **결정론**: seed와 시나리오 이름으로 RNG를 만들고, 모든 후보가 **같은 trace**를 본다.
- **측정 구간**: horizon 300 s, warm-up 30 s 제외, 측정 Turn이 1,000개 미만이면 최대 1,800 s까지 연장(P99 표본 수 확보).

## 5.2 부하 축 (A21, A22)

- **open loop**: `λ0 = 0.6 × λ_sat(Baseline)`, M1의 Baseline-only 제어 실행에서 정하고 후보 실행 전에 동결. grid `x{0.5, 0.75, 1.0, 1.25, 1.5, 2.0}`, Baseline goodput의 peak가 grid 끝이면 확장.
- **closed loop**: CB는 동시 32 클라이언트, sweep `{16, 32, 48, 64, 96}`.
- **세션 수 sweep**(멀티턴 시나리오): 시나리오별 grid.

## 5.3 시나리오 시작값 (`sim/configs/scenario_params.json`)

시작값(ASSUMED)이다. **Baseline만 돌린 B-class loop로만** 바꿀 수 있고, 후보 실행 전에 `results/iterations/loop-log.md`에 기록한다.

| 시나리오 | 파라미터 |
|---|---|
| `cb_kv_8k_b32` | 1P+1D · closed C=32 · prompt 8192 · out 256 · 단일 턴 · hbm_mult 0.12 |
| `cb_kv_8k_b32_ramp` | 1P+1D · closed C=32 · prompt 8192 · out 256 · hbm_mult 0.2 + DP1 capacity_ramp |
| `cb_mixed_8k_b32` | 1P+1D · closed C=32 · prompt 8192 · out 256 · hbm_mult 0.12 · 비-KV는 용량 점유만 |
| `dp2_turn_hbm_small_tool` | 2P+2D · 세션 24 {12..48} · hist0 32768 · tool 512 · out 256 · tier HBM 고정 · hbm 1.0 · bg 0 |
| `dp2_turn_dram_small_tool` | 2P+2D · 세션 24 · hist0 65536 · tool 512 · tier DRAM 고정 · hbm 0.35 · bg 16 |
| `dp2_turn_hbf_hist` | 2P+2D · 세션 16 {8..32} · hist0 131072 · tool 2048 · tier HBF 고정 · hbm 0.35 · bg 16 |
| `dp2_turn_ssd_hist` | 2P+2D · 세션 8 {4..16} · hist0 65536 · tool 512 · tier SSD-PIM 고정 · hbm 0.35 · bg 16 |
| `dp2_tool_large_result` | 2P+2D · 세션 16 {8..32} · hist0 16384 · **tool 16384** · tier HBM · hbm 1.0 · bg 16 |
| `dp2_prefill_burst_p_saturated` | 2P+2D · open λ0, MMPP on-phase 3x λ0 10 s/60 s · 단일 턴 · **prompt U{8192, 12288, 16384}** · out 256 |
| `dp2_decode_heavy_p_idle` | 2P+2D · closed 64 chat 세션 · prompt 2048 · out 2048 · 8 turns |
| `dp2_long_ctx_decode_offload` | 1P+2D · 세션 8 {4..16} · **hist0 U[131072, 262144] · tool 2048** · turns 4 · allocator 배치 · hbm 0.3 · 오프로드 Tier 허용 |
| `dp2_session_size_skew` | 2P+4D · open λ0 · hist0 5% 262144 / 95% 8192 · tool 512 · 8 turns |
| `dp2_internode_link_contention` | `dp2_turn_dram_small_tool` + P↔D NIC x0.25 |
| `dp2_stale_telemetry` | `dp2_prefill_burst_p_saturated` + telemetry 갱신 {10 ms, 100 ms, 1 s} |
| `dp2_planner_fault_fallback` | `dp2_prefill_burst_p_saturated` + Planner 중단(T/2부터 60 s) |
| `dyn_turn_demotion_wave` | 2P+2D · 세션 24 · hist0 32768 · tool 512 · HBM 시작, t=T/3에 idle(>30 s) 세션의 History를 DRAM, t=2T/3에 CXL-PNM (모든 후보 동일 외부 schedule) |
| `dyn_load_ramp_burst` | 2P+2D · open λ(t)=λ0(0.4+0.7 t/T) + T/2에 3x burst 10 s · hist0 32768 · tool 512 |
| `dyn_p_node_degrade` | `dp2_turn_dram_small_tool` + T/2에 P0 처리량·NIC x0.5 |
| `dyn_decode_phase_shift` | 2P+2D · closed 64 chat · prompt 2048 · out 256→2048 (T/2) · 8 turns |

# 6. Planner 사양

## 6.1 후보 공간

- `n_p`: 노드 전체(role-flexible).
- `n_d`: `(node, tier)`, tier ∈ {`hbm`, `custom_hbm`, `cxl_pnm`, `hbf`} 중 **용량과 TPOT가 feasible**한 것. `dram`, `ssd_pim`은 제외(swap-in이 필요한 상태는 결정 비용에 반영되지만 Decode 시작 Tier가 아님).
- 2P+2D 기준 `|n_p| × |n_d| = 4 × 16 = 64`개. 이것이 결정 비용의 기준 K다(`K_ref = 64`). top-k pruning은 옵션: P 4개, D 4개로 제한.
- **재계산(recompute) 후보는 넣지 않는다**(소유자 결정, §13 O11).

## 6.2 Cost 정의 (A19, 단위: request-seconds)

```text
Cost(n_p, n_d) = E2E_self(n_p, n_d) + X(n_p, n_d)

E2E_self = Wait(n_p) + Tstage(History → n_p) + Tprefill(n_p)
         + Thandoff(n_p → n_d) + Wait_dec(n_d) + (N̂_out − 1) × TPOT_est(n_d)

X (타 요청에 주는 지연)  =  |D_run(n_p)| × n_iter_pf × ΔT_iter_chunk           # Prefill chunk가 co-resident Decode를 늦춤
                         +  |큐에서 이 요청 뒤의 Prefill| × Tprefill(n_p)         # 뒤 요청 대기 증가
                         +  |D_run(n_d)| × N̂_out × (T_iter(|D|+1) − T_iter(|D|))   # n_d batch 증가에 의한 Decode 지연
```

- `Wait(n_p) = 큐 앞 Prefill 토큰 ÷ n_p의 Prefill 처리율 추정`, `Wait_dec(n_d)`는 swap-in/승격 대기와 batch 합류 지연.
- 모든 항은 §4의 `execmodel` 함수로 계산한다. 즉 estimator와 실행은 같은 식이고 **차이는 상태(telemetry 연령)와 오차 ε**뿐이다.
- `N̂_out`은 시나리오의 `out` (정확히 안다고 가정, ASSUMED).

## 6.3 제약과 선택

1. 하드 제약: `n_d`의 KV 용량(4.6), `TTFT_est ≤ 2 s`, `TPOT_est(n_d) ≤ 50 ms`.
2. feasible 후보 중 `Cost` 최소.
3. feasible 후보가 없으면 `max(TTFT_est/2 s, TPOT_est/50 ms)`가 최소인 후보(최소 위반). 그것도 없으면 Baseline 규칙(§7)으로 fallback.

## 6.4 C1 — 스케줄링 시점

- 요청은 **global queue**에서 대기한다. 어떤 P 후보의 대기 Prefill 토큰이 `node_queue_cap`(16,384, A16) 미만이 되면 dispatch 가능.
- dispatch 시 scheduler(**단일 server**)가 결정한다. 결정 시간 `T_dec`동안 scheduler는 다음 요청을 처리하지 못한다(직렬). 입력은 결정 시작 시점의 telemetry snapshot.
- 결정 비용(A17): `T_dec = T_ref × (K / 64)`, `T_ref = 1 ms`(sweep 0.1 / 1 / 10 ms).

## 6.5 C2 — 사전 계획

- 요청이 **도착하면** planner worker(기본 4, sweep 1/4/16)가 병렬로 plan을 만들어 Plan Cache에 둔다: `(plan, 순위 backup 3개, t_plan)`. 계획 시간은 C1과 같은 `T_dec`지만 **critical path 밖**이다.
- dispatch 시 scheduler가 lookup과 **Late Validation**(`c_val = 20 µs`, 직렬)을 수행한다. 검사: 노드 health, `n_d` 용량, 노드 큐 ≤ `node_queue_cap`의 2배, `plan_age ≤ 2 s`(A17d), 경로 도달성.
- 실패하면 backup 순서로 재검증, 모두 실패하면 **동기 re-plan**(C1과 같은 비용).
- 대기가 없으면 plan이 준비될 때까지 dispatch가 기다린다. 즉 **C2가 `T_dec`을 숨기는 것은 요청이 global queue에서 기다릴 때뿐**이다.

## 6.6 Telemetry (A15)

- 노드별 snapshot: 대기 Prefill 토큰, Decode 시퀀스 수, Tier별 컨텍스트 합, Tier별 KV 여유, 활성 전송 수, health.
- 갱신 주기 50 ms(sweep 10 ms / 100 ms / 1 s). 시점 t의 snapshot은 `floor(t/Δ) × Δ`에 찍힌 값(연령 U(0, Δ)).
- **C1과 C2는 같은 telemetry 메커니즘**을 쓴다. 둘의 차이는 **plan age(대기 시간)와 결정 지연**이며 telemetry 신선도가 아니다.
- Oracle은 결정 시점의 정확한 상태와 정확한 비용, 결정 비용 0을 쓴다(달성 불가능한 상한).

## 6.7 Estimator 오차 (A18)

- 구성요소(`Tstage`, `Tprefill`, `Wait`, `TPOT_est`)마다 lognormal(σ=ε) 배수를 곱한다. 기본 ε=0, sweep 0/0.2/0.4/0.6 (SKILL H17).
- 배수는 `(seed, request id, candidate id, component)`로 결정해 **C1과 C2가 같은 오차를 본다**(paired).

## 6.8 Fallback

Planner 중단, telemetry가 `5Δ` 이상 끊김, feasible 후보 없음 → Baseline 규칙. `dp2_planner_fault_fallback`이 이 경로를 검증한다.

# 7. 참조 정책

| 정책 | 규칙 |
|---|---|
| **Baseline-PD-fixed** (Common Reference Baseline) | `n_p` = P 역할 노드 중 대기 Prefill 토큰 최소(telemetry). `n_d` = 세션 owner D 노드(없으면 HBM KV 풀 여유 최대인 D). Prefill 전에 History 전체를 owner Tier에서 `n_p` HBM으로 복사, Prefill 후 새 KV만 P→D. P는 상태 비유지(A10). D는 Prefill하지 않고 P는 Decode하지 않음. Decode는 HBM(필요 시 swap-in) |
| D-local-always | `n_p` = `n_d` = 세션 owner 노드. staging은 4.3의 승격 규칙 |
| Oracle | §6.2~6.3의 Planner를 정확한 상태·정확한 비용·결정 비용 0으로 실행 |
| P-retain | Baseline에서 P가 입력 KV를 LRU로 유지(용량 한도). 더 강한 As-Is 참고 행 |

**Baseline 정의는 소유자 결정(§13 O2)**이다. P 상태 비유지(A10)는 슬라이드 14의 As-Is("D→P 전송")와 공통 규칙(Baseline의 prefix reuse 통제)을 따른 것이고 Baseline에 불리하다. 그래서 P-retain을 참고 행으로 반드시 함께 보고한다(SKILL: Baseline을 약하게 만들지 않는다).

# 8. 메트릭과 QA 산출식 (동결 대상)

| 항목 | 정의 |
|---|---|
| TTFT | 첫 토큰 시각(`n_p`의 Prefill 종료 iteration 끝) − 도착 시각 |
| TPOT_req | `(t_done − t_first) / (N_out − 1)` (요청별 평균 토큰 간격, handoff·swap-in 포함). max ITL은 진단 |
| 요청 SLO 충족 | `TTFT ≤ 2 s` **그리고** `TPOT_req ≤ 50 ms` |
| Goodput (QA1) | SLO를 충족한 요청의 출력 토큰 ÷ 측정 시간. load sweep 최대값 = Max SLO Goodput |
| QA2 | 요청 분포의 P50/P95/P99. TTFT와 TPOT 별도 행 |
| U_useful (QA3 headline) | `Σ_iteration ( iteration 시간 × [SLO 충족 요청 토큰 비중] ) ÷ ( 노드 수 × 측정 시간 )`, 노드별·풀별 계산 |
| 노드 간 불균형 | 풀(P, D)별 노드 busy fraction의 CV (진단) |
| KV 이동량 | Turn당 노드 간 전송 bytes (진단, QA3 보조) |
| η (QA5) | `Max SLO Goodput(N=32 노드) ÷ ( 16 × Max SLO Goodput(1P+1D) )` |
| regret (진단) | dispatch 시점의 정확한 상태에서 `Cost(선택) − min Cost`, ≥ 0 |
| plan age (진단) | `t_dispatch − t_plan` (C1은 0) |
| mis-selection (진단) | regret > 0인 결정의 비율 |

`U_useful`은 `qa-criteria-dp2.md`의 임시 정의를 위 식으로 확정한다(전송 stall 항은 iteration busy 시간에 포함되지 않으므로 제거). 정의 변경 사유와 이전 정의는 그 문서에 기록한다.

# 9. 평가 실행 규격

| 항목 | 규격 |
|---|---|
| seed | 11, 23, 37, 53, 71 (≥ 5), 같은 `(scenario, seed, load)`에서 모든 후보가 같은 trace |
| 통계 | 95% CI(`t(0.975, 4) = 2.776`), CV 기록, 쌍별 paired 비교, 차이 < 1%는 tie (DP1 `MATERIAL_REL`) |
| fit label | **infeasible**: Baseline Max SLO Goodput = 0. **saturated**: 모든 후보가 95% CI 내 동일. **comparison_valid**: 그 외. 결과 확인 전, Baseline-only 제어 실행으로 SYS별 확정 |
| 집계 | comparison_valid 쌍의 기하평균 (scenario × SYS 쌍), 제외 쌍과 사유 표기 |
| 별점 | QA1 0.90/1.10 x T_ref. QA2 TTFT P99 ≤ 2 s / 4 s, TPOT P99 ≤ 50 / 100 ms (공통 §5). QA3 65/85% (공통 §6). QA4 module ≤2 / 3~5 / ≥6 + 공수·비용(SKILL H21). QA5 η 0.90 / 0.70 (제안) |
| 민감도 | 링크 BW, κ, telemetry 주기, `T_ref`, ε, worker 수, DP1-C1 on/off |
| 동등성 점검 | N>8에서 step coalescing(10 iteration)을 쓰되 N=8에서 iteration-level 대비 TTFT/TPOT P50 차이 ≤ 2% (A25) |
| 재현 | 명령, seed, load, git revision(dirty 포함), `params_sha`를 결과에 기록 (`result_schema.json`) |

# 10. 참조값 (`sim/m0_reference_values.json`)

단일 경로의 closed-form 값이다(시뮬레이션 결과가 아님). H100 기준, B200은 JSON 참조.

| 항목 | 값 |
|---|---|
| KV / token, weight | 327,680 B, 141.2 GB |
| History 64K(약 21.5 GB) 이동 | HBM: D 로컬 0 / P 경로 0.43 s · DRAM: 0.34 / 0.43 · CXL-PNM·ScHBM: 0.34 / 0.43 · HBF: 제자리 읽기 / 0.43 · SSD-PIM: 1.34 / 1.34 s |
| Decode step, ctx 200K, batch 1 | HBM 8.6 ms · ScHBM 20.0 ms · HBF 79.1 ms · CXL-PNM 240 ms (B200: 3.6 / 8.5 / 75.7 / 236.6 ms) |
| TPOT 50 ms 충족 최대 컨텍스트 (batch 1) | HBM > 3M · ScHBM 약 629K · HBF 약 120K · CXL-PNM 약 38K (B200: > 3M / 1.6M / 129K / 41K) |
| Prefill (단독, 큐 0) | 8K 0.337 s · 16K 0.763 s · 32K 1.881 s (B200: 0.148 / 0.335 / 0.827) |
| blocking swap-in | 200K 컨텍스트 DRAM 1.02 s, SSD-PIM 4.1 s |
| CB KV 풀 | CB-1 76.8 GiB (H100) / 184.3 GiB (B200), CB-2 128 / 307.2 GiB |

rationale의 사례 표는 **KV 읽기만의 이론 하한**이고, 시뮬레이터 기준은 위 값이다(M1 종료 기준은 이 표와의 일치).

# 11. 가정 레지스터

전체는 `sim/configs/dp2_params.json`(항목별 id, 값, 근거, evidence, sweep, `owner_confirm`). Evidence 구분: SPEC / PUBLIC / ASSUMED, DP1에서 상속한 값은 `DP1`.

소유자 확정이 필요한 항목(`owner_confirm: true`): A01 구성, A02 링크, A07 κ, A10 P 상태, A15 telemetry 주기, A16 큐 한도, A17 결정 비용, A17d plan age 한도, A19 Cost 정의, A21 부하 규칙, A25 step coalescing.

# 12. 동결 규칙

확정 후 동결(변경 시 새 버전으로 취급):
SLO, 별 threshold, 메트릭·QA 산출식(§8), fit label 규칙, 비교군 정의, Cost 정의(A19), 시스템 profile.

허용되는 변경 (SKILL H16): (i) 정의의 오류·누락 수정(사유와 이전 값 기록), (ii) 공개된 가정의 변경과 민감도 보고, (iii) 시나리오 추가(실패한 것도 유지). 시나리오 시작값은 Baseline-only B-class loop로만, 후보 실행 전에 기록한다.

# 13. M0 종료 체크리스트와 소유자 결정

- [x] 참조값 재현 가능 (`python sim/m0_check.py --verify`)
- [x] 시나리오 이름이 `benchmark.md`와 일치, 결과 스키마 로드
- [x] Baseline이 이론상 infeasible한 시작값 3건 수정 (F-1, F-2)
- [ ] 소유자 확정 (아래 O1~O11) → 동결 revision 기록

| ID | 결정 | 제안 |
|---|---|---|
| O1 | 접근 B(이산 사건 신규)와 `sim/` 위치 | 승인 |
| O2 | Common Reference Baseline: P 상태 비유지(A10) 대 P-retain | **P 상태 비유지를 기준으로 하고 P-retain을 참고 행으로 병기** |
| O3 | 노드 간 링크 기본값 50 GB/s, sweep 12.5~400 | 그대로 (근거 확보 전까지 ASSUMED) |
| O4 | κ 기본 1.0, sweep 1.0/1.15/1.3 | 그대로 |
| O5 | telemetry 50 ms, node queue 한도 16,384 토큰 | 그대로 |
| O6 | 결정 비용 `T_ref` 1 ms @K=64, worker 4, plan age 한도 2 s | 그대로, 민감도 필수 |
| O7 | Cost 정의 A19 (E2E + 외부효과, 하드 제약) | 승인 |
| O8 | 부하 규칙(λ0 = 0.6 λ_sat, CB closed loop 32) | 승인 |
| O9 | QA3 `U_useful`(§8), QA5 η 0.70/0.90 | 승인 |
| O10 | N>8 step coalescing(10 iteration, 2% 동등성) | 승인 |
| O11 | recompute 후보 제외 | 제외 (SSD History는 swap-in 비용으로 처리) |
