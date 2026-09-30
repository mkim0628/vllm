# DP1 A-evidence runbook (A100 / H100에서 직접 돌릴 것)

이 디렉터리의 스크립트는 **실측값 [A]** 를 만든다. 결과는 모두
`doc-mk/DP1/dp1_sim/measured/<GPU_KEY>/` 아래에 떨어지고, `hw.py`가
자동으로 읽어 catalog의 B 값을 덮어쓴다 (evidence label이 `[B]` → `[A]`로 바뀜).

```text
measure/00_env_check.sh        SW/HW revision, host DRAM 용량                  -> env.json
measure/01_transfer_microbench HBM<->DRAM BW/latency/chunk/동시성/간섭/alloc    -> transfer.json
measure/02_step_profile.py     vLLM offline step profile (perf model 캘리브레이션) -> step_profile_*/, vllm_kv_capacity.json
measure/03_serve_sweep.sh      vLLM serve + trace 수집 (common / dp1 / offload)  -> serve_*/
measure/04_decision_overhead   C1/C2 decision latency on the serving host CPU    -> decision_overhead.json
measure/dp1_client.py          동일 workload JSONL 재생 client (03이 호출)
measure/collect_trace.py       /metrics + NVML + KV-events(ZMQ) trace (03이 호출)
```

## 0. 준비 (한 번)

```bash
cd <repo root>                     # 이 vLLM checkout
uv venv --python 3.12 && source .venv/bin/activate
VLLM_USE_PRECOMPILED=1 uv pip install -e . --torch-backend=auto
uv pip install aiohttp nvidia-ml-py pyzmq msgspec
huggingface-cli login              # Llama-3.1 gated model
cd doc-mk/DP1/dp1_sim
export PY=$(which python)
```

GPU_KEY는 `configs/hw_catalog.json`의 key와 정확히 같아야 한다.

| 보유 장비 | GPU_KEY |
|---|---|
| A100 SXM4 80GB | `a100_sxm4_80g` |
| A100 PCIe 80GB | `a100_pcie_80g` |
| H100 SXM5 80GB | `h100_sxm5_80g` |
| H100 PCIe 80GB | `h100_pcie_80g` |

> **TP 선택.** Llama-3.1-70B BF16 가중치만 141 GB → 80 GB GPU 최소 2장. 기본 `TP=4`.
> A100×4에서는 8K prompt prefill 1회가 이론상 ~1.9 s (2·70.6e9·8192 / (4·312 TFLOPS·0.5))라
> **TTFT P99 ≤ 2 s SLO를 저부하에서도 거의 못 맞춘다.** A100은 `TP=8`을 권장하고,
> 반드시 A100/H100을 **같은 TP**로 측정해야 §12 cross-validation이 성립한다.
> GPU가 1장뿐이면 `MODEL=meta-llama/Llama-3.1-8B-Instruct MODEL_KEY=llama_3_1_8b TP=1`.

## 1. 순서 (A100 먼저 → H100)

각 GPU 박스에서 `GPU_KEY`만 바꿔 동일하게 실행한다.

```bash
export GPU_KEY=a100_sxm4_80g TP=4        # H100 박스에서는 h100_sxm5_80g

# (1) 환경 기록 — 1분
bash measure/00_env_check.sh

# (2) HBM<->DRAM migration path microbenchmark — ~5분, 모델 불필요
$PY measure/01_transfer_microbench.py --num-gpus $TP

# (3) step profile — 모델 1회 로드 + 30 point, ~40-60분 (--quick: ~15분)
$PY measure/02_step_profile.py

# (4) Common Benchmark sweep (8K/256, prefix reuse 없음) — rate당 ~5-10분
MODE=common RATES="0.1 0.2 0.3 0.5 0.8" SEEDS="0 1 2" bash measure/03_serve_sweep.sh

# (5) DP1 workload (multi-turn / hotness_flip / long_cold) — 동일 JSONL을 sim도 사용
MODE=dp1 KINDS="multiturn hotness_flip long_cold" RATES="0.25 0.5 1 1.5" bash measure/03_serve_sweep.sh

# (6) Phase 5: 실제 migration executor (vLLM native CPU offload) + HBM pressure 고정
#     KV를 GPU당 10 GiB(TP4 합 40 GiB)로 묶어 pressure를 만들고 offload 유/무를 비교
MODE=dp1 KINDS="multiturn" RATES="0.5 1" KV_BYTES=10737418240 bash measure/03_serve_sweep.sh
MODE=dp1 KINDS="multiturn" RATES="0.5 1" KV_BYTES=10737418240 OFFLOAD_GIB=256 bash measure/03_serve_sweep.sh

# (7) decision overhead (GPU 불필요, 하지만 serving host CPU에서) — ~5분
$PY measure/04_decision_overhead.py --kind multiturn --rate 1.0
```

KV_BYTES는 vLLM `--kv-cache-memory-bytes` 의미(**per-GPU**)다. run 디렉터리 이름에 `_kv<N>`이 남으므로
`run_dp1.py validate/shadow`가 자동으로 sim KV 용량을 `N × TP`로 맞춘다 (수동: `--kv-capacity-bytes`).

## 2. 측정 후 (어디서든, GPU 불필요)

```bash
# A100 perf model 캘리브레이션 [A]
$PY run_dp1.py calibrate --gpu a100_sxm4_80g --tp 4
# H100도 캘리브레이션 (blind 비교의 상한선 = "own fit")
$PY run_dp1.py calibrate --gpu h100_sxm5_80g --tp 4
# §12 Step 2-3: A100 모델 + H100 spec -> H100 blind prediction vs H100 actual
$PY run_dp1.py crossval --src a100_sxm4_80g --dst h100_sxm5_80g --tp 4
# sim vs actual (같은 trace), offload run은 B1으로 자동 비교
$PY run_dp1.py validate --gpu h100_sxm5_80g --tp 4 --run-dir measured/h100_sxm5_80g/serve_llama_3_1_70b_tp4_dp1
# Phase 4 Shadow: 실제 trace 위에 C1/C2 decision overlay
$PY run_dp1.py shadow --gpu h100_sxm5_80g --tp 4 --run-dir measured/h100_sxm5_80g/serve_llama_3_1_70b_tp4_dp1
# Phase 7: 미보유 HW projection (검증된 오차 band가 자동으로 붙음)
$PY run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --tiers dram,cxl_mem,hbf --kind hotness_flip --rates 0.5,1,1.5,2
$PY run_dp1.py sweep --gpu b200_sxm_180g --tp 4 --step-model-from h100_sxm5_80g --tiers dram,hbf --kind multiturn
```

## 3. 결과를 나에게 줄 때

`measured/` 디렉터리 전체를 commit 하거나 압축해서 전달하면 된다. 특히 필요한 파일:

- `measured/<gpu>/transfer.json`, `env.json`, `vllm_kv_capacity.json`
- `measured/<gpu>/step_profile_*/b*_i*_o*.json`
- `measured/<gpu>/serve_*/bench_r*_s*.json` (common), `client_*.jsonl` + `.summary.json` (dp1), `trace_*.jsonl`, `server.log`
- `measured/<gpu>/decision_overhead.json`

`server.log`의 `GPU KV cache size: N tokens`와 `vllm_kv_capacity.json`이 서로 5% 이상 다르면
알려줄 것 (activation profile이 max_model_len/max_num_batched_tokens 설정에 따라 달라짐).

## 4. 주의 / 알려진 한계

- `01`의 interference 테스트는 **단일 GPU에서 HBM-bound copy kernel vs PCIe DMA** 간섭이다.
  실제 decode attention kernel과의 간섭은 `03` offload run의 TPOT 차이로 교차 확인한다.
- vLLM native offload(B1)는 "evict 시 LRU로 CPU에 store"에 가까운 동작으로 모델링했다.
  `external_prefix_cache_hits_total` (trace의 `ext_prefix_hits`)로 실제 CPU-tier hit 수를 확인해
  sim의 `reuse_lower_hit_rate`와 비교한다.
- SSD 경로를 A로 만들고 싶으면 (선택): `fio --name=r --rw=read --bs=2M --size=16G --direct=1 --numjobs=4 --iodepth=32 --filename=<nvme mount>/f`
  결과 BW(4 jobs 합)를 `measured/<gpu>/transfer.json`에 `"nvme_read_Bps": <bytes/s>`로 추가하면
  hw.py가 `nvme_ssd` tier의 device BW를 A로 대체한다 (drive 1개 기준 값으로 넣을 것).
