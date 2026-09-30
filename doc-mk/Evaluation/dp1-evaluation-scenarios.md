# DP1 Evaluation Scenarios

> 대상: **DP1 — AI Data Migration**
>
> 이 문서는 DP1 평가에서 실제로 돌리는 **시나리오 matrix**를 정의한다.
> - 평가 방법/phase: `dp1-simulation-plan.md`
> - QA 정의/별점: `qa-evaluation-criteria.md`
> - 코드: `doc-mk/DP1/dp1_sim/` (serving simulator), 실측 절차: `doc-mk/DP1/dp1_sim/measure/README.md`

---

# 1. Scenario Matrix 구조

~~~text
Scenario = Workload (4)  x  HW / Tier 구성 (6)  x  Pressure 강도  x  Load sweep  x  Seed (5)
           └───────────────────── 각 cell에서 B0 / B1 / C1 / C2 동일 조건 비교 ─────────────────────┘
~~~

동일 workload JSONL을 **실제 vLLM(A)** 과 **serving simulator(C)** 에 모두 투입한다.
따라서 C1/C2는 같은 workload, 같은 initial state, 같은 runtime trace에서 비교된다 (plan §1).

---

# 2. Workload 시나리오 (`dp1_sim/workload.py`)

| kind | 구성 | 평가 목적 | 예상 차이 |
|---|---|---|---|
| **common** | 8K in / 256 out, Poisson, 재사용 없음 (criteria §8) | QA1 T_ref, QA2 baseline, calibration / A100→H100 cross-validation | DP1 개입 여지 없음 → B0≈C1≈C2가 정상. 차이가 나면 model 오류 |
| **multiturn** | 세션당 4–12 turn. 첫 turn 문서 평균 3K tok (lognormal, 최대 12K), 이후 turn 100–600 tok, 출력 100–300. hot 세션 60% (think 평균 3 s) / cold 40% (평균 45 s) | 기본 migration 효과: 끝난 turn의 session KV를 HBM 유지 / lower tier / drop 중 무엇으로 할지 | lower tier 존재 시 recompute 제거. C1/C2는 victim 선택에서 갈림 |
| **hotness_flip** | multiturn + 각 세션 절반 지점에서 hot↔cold 반전 | C2 prediction lag, thrashing (§13 hotness flip / reuse pattern shift) | C2가 flip 직후 오예측. C1은 behavior를 보지 않으므로 무관 |
| **long_cold** | 세션 70%가 큰 문서 + 1–2 turn 후 재사용 없음 | long-lived cold object 식별 (§13) | C2는 class-level 생존모델로 dead KV를 먼저 내리거나 버림. C1은 LRU×size로 늦게 잡음 |

- turn k>0은 이전 turn 완료 후 `think_s` 뒤에 도착 (세션별 closed loop).
- `behavior` 필드는 분석용 ground truth이며 어떤 policy도 보지 않는다.
- 각 kind마다 load(세션 도착률) sweep, seed 5개 median + 95% CI + CV (criteria §2.1).

---

# 3. HW / Tier 구성

| 구성 | `--tiers` | Evidence | 목적 |
|---|---|---|---|
| HBM only | `''` | A | lower tier 없이 eviction 판단만 비교 (drop vs LRU) |
| HBM + DRAM | `dram` | A (PCIe 실측) | 실측 가능한 유일한 경로. B1 ↔ vLLM native offload 대조로 simulator 검증 |
| HBM + NVMe | `nvme_ssd` | B (fio 실측 시 A) | 복원이 느린 tier에서 prefetch / placement 가치 |
| HBM + CXL mem (+NVMe) | `cxl_mem[,nvme_ssd]` | B+C | 확장 메모리 tier, multi-tier destination 선택 |
| HBM + HBF | `hbf` | B+C | GPU-direct read, 쓰기 비싼 tier |
| 미보유 GPU (B200 등) | `--gpu b200_sxm_180g --step-model-from h100_sxm5_80g` | B+C (±검증 band) | Phase 7 projection |

Tier 파라미터와 출처: `dp1-simulation-plan.md` §11.1, `dp1_sim/configs/hw_catalog.json`.

---

# 4. Pressure 강도

| 방법 | 실제 vLLM | Simulator |
|---|---|---|
| HBM KV 용량 고정 | `KV_BYTES=<per-GPU bytes>` (`--kv-cache-memory-bytes`) | run 디렉터리 이름에서 자동 적용 (`N × TP`), 또는 `--kv-capacity-bytes` |
| HBM 추가 축소 (stress) | – | `--hbm-kv-scale 0.x` |
| 실제 migration executor | `OFFLOAD_GIB=<GiB>` (vLLM native CPU offload) | B1 과 비교 (Phase 5) |

기본 권장 pressure 점: 기본 KV 용량 (no pressure), GPU당 10 GiB (TP4 합 40 GiB, 강한 pressure).

---

# 5. 비교 대상 (모든 cell 공통)

| 후보 | 내용 | Registry | Promotion |
|---|---|---|---|
| **B0** vllm-lru-drop | vLLM 기본: LRU drop, miss 시 recompute | – | – |
| **B1** lru-offload | LRU로 DRAM offload (≈ `--kv-offloading-size`) | type-agnostic | demand only |
| **C1** resource-driven | ResourceStateMonitor/Trend → generic eviction (idle×size) → Affinity Mapper → Destination Tier Selector | type-agnostic | capacity recovery (DP1 §17.2) |
| **C2** behavior-driven | Behavior Monitor → class-level reuse 생존모델 + object EWMA → Future Behavior Predictor → restore-aware tier 선택 | type-aware | predicted reuse + headroom (DP1 §17.3) |

vLLM runtime fallback (LRU drop, preemption-recompute, demand promotion)은 모든 후보에 동일 → 차이는 DP1 decision pipeline에서만 발생.

---

# 6. 측정 지표

평가 규칙 (결과 보기 전 고정):

- **QA1** 각 후보의 Max SLO Goodput (request 단위 TTFT ≤ 2 s AND TPOT ≤ 50 ms). T_ref = 같은 workload/HW의 B0 값.
- **QA2** TTFT / TPOT P99 — **모든 후보를 B0의 max-goodput load에서** 비교.
- **QA3** useful HBM util = 시간평균(running KV + 이후 재접근되는 retained KV) / HBM KV 용량 × SLO attainment — QA2와 같은 load.
- Evidence label = 입력 evidence(HW trail + step model) + C. 불확실성 = `measured/validation_*.json`의 최악 오차, 없으면 "NOT validated" + 가정 입력 목록.

진단 지표 (plan §14.2):

- reuse 위치 비율: HBM hit / lower-tier hit / miss(recompute)
- recompute tokens, preemptions
- migration GiB, promotion / demotion / drop 수
- promotion wait (demand fetch 대기)
- prefetch hit, unnecessary promotion, unnecessary demotion (demotion 후 30 s 내 재접근)
- thrash events (30 s 내 4회 이상 이동)
- decision overhead (modeled / wall-clock)

---

# 7. Plan §13 대비 Coverage

| §13 항목 | 상태 | 위치 |
|---|---|---|
| hotness flip / reuse pattern shift | ✅ | serving sim `hotness_flip` |
| long-lived cold object | ✅ | serving sim `long_cold` |
| promotion / demotion, prediction lag, thrashing | ✅ | 전 시나리오 진단 지표 |
| HBM capacity pressure (정적) | ✅ | `KV_BYTES` / `--hbm-kv-scale` |
| **HBM capacity ramp** (시간 변화) | ⚠️ | legacy `run_eval.py`만 (B+C) |
| **HBM BW shock / host path(PCIe) pressure** | ⚠️ | legacy `run_eval.py`만 (B+C) |
| **Mixed AI Data** (RAG / Agent Memory / Tool / LoRA / MoE) | ⚠️ | legacy `run_eval.py`만 (B+C); vLLM trace로 표현 불가 → A 불가 |
| **suddenly hot object / migration storm / tier imbalance** | ❌ | 명시 시나리오 없음 (hotness_flip·thrash로 간접) |

## 7.1 알려진 편향 및 TODO

현재 serving sim matrix는 **C2에 유리한 쪽(behavior 변화)** 에 치우쳐 있다.
C1이 유리해야 할 **resource 상태 급변** 시나리오가 serving sim에 없다. 공정 비교를 위해 추가 예정:

| 추가 시나리오 | 내용 | 기대 |
|---|---|---|
| `capacity_ramp` | 시간에 따라 HBM KV 용량 감소 (다른 AI data / co-located tenant 유입 모사) | C1 trend 기반 선제 demotion 유리 |
| `pcie_contention` | 외부 DMA 트래픽 주입 (host path pressure) | C1 bw-state 인지, C2 prefetch 비용 증가 |
| `burst` | 세션 도착 급증 (migration storm 유발) | 두 후보의 storm / thrash 내성 비교 |

---

# 8. 실행

~~~bash
cd doc-mk/DP1/dp1_sim
# simulator (GPU 불필요)
python run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --kind multiturn    --tiers dram               --rates 0.5,1,1.5,2
python run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --kind hotness_flip --tiers nvme_ssd           --rates 0.5,1,1.5
python run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --kind long_cold    --tiers cxl_mem,nvme_ssd   --rates 0.5,1,1.5
# 실측 (A100/H100): measure/README.md
~~~

결과: `out/sweep_*/qa_table.md`, `summary.json`, `runs.csv`.
