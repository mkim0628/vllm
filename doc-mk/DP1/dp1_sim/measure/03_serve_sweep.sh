#!/usr/bin/env bash
# Phase 1 + 3 (+5): vLLM serving baseline sweep with runtime-trace collection (A evidence).
#
#   MODE=common   : Common Benchmark (8K in / 256 out, no prefix reuse), request-rate sweep
#                   with `vllm bench serve`  -> QA1 T_ref, QA2 baseline, calibration check
#   MODE=dp1      : DP1 workloads (multiturn / hotness_flip / long_cold) replayed with
#                   dp1_client.py from the SAME JSONL the simulator uses
#   OFFLOAD_GIB=N : additionally enable vLLM native CPU KV offloading (B1 real executor, Phase 5)
#   KV_BYTES=N    : pin KV cache size (--kv-cache-memory-bytes) to create HBM pressure
#                   identically in real run and simulation (sim: --kv-capacity-bytes N)
#
#   GPU_KEY=a100_sxm4_80g TP=4 MODE=common RATES="0.1 0.2 0.3 0.5 0.8" bash measure/03_serve_sweep.sh
#   GPU_KEY=h100_sxm5_80g TP=4 MODE=dp1 KINDS="multiturn hotness_flip" RATES="0.5 1 1.5 2" bash measure/03_serve_sweep.sh
source "$(dirname "$0")/common.sh"
: "${MODE:=common}"
: "${RATES:=0.1 0.2 0.3 0.5 0.8 1.2}"
: "${KINDS:=multiturn hotness_flip long_cold}"
: "${NUM_PROMPTS:=200}"
: "${HORIZON:=300}"
: "${SEEDS:=0}"
: "${OFFLOAD_GIB:=}"
: "${KV_BYTES:=}"
TAG="${MODE}${OFFLOAD_GIB:+_offload${OFFLOAD_GIB}}${KV_BYTES:+_kv${KV_BYTES}}"
RUN="$OUT/serve_${MODEL_KEY}_tp${TP}_${TAG}"
mkdir -p "$RUN"

EXTRA=()
[[ -n "$OFFLOAD_GIB" ]] && EXTRA+=(--kv-offloading-size "$OFFLOAD_GIB" --kv-offloading-backend native)
[[ -n "$KV_BYTES" ]] && EXTRA+=(--kv-cache-memory-bytes "$KV_BYTES")

# dev mode exposes POST /reset_prefix_cache (same empty initial state per sweep point)
VLLM_SERVER_DEV_MODE=1 "$PY" -m vllm.entrypoints.cli.main serve "$MODEL" \
  --served-model-name dp1 --port "$PORT" \
  --tensor-parallel-size "$TP" --dtype bfloat16 \
  --gpu-memory-utilization 0.90 --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs 256 --max-num-batched-tokens 8192 \
  --enable-prefix-caching --enable-prompt-tokens-details \
  --kv-events-config '{"enable_kv_cache_events": true, "publisher": "zmq", "endpoint": "tcp://*:5557", "topic": "kv-events"}' \
  "${EXTRA[@]}" > "$RUN/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; wait $SERVER 2>/dev/null' EXIT
until curl -sf "http://localhost:$PORT/health" >/dev/null; do
  kill -0 $SERVER 2>/dev/null || { echo "server died, see $RUN/server.log"; exit 1; }
  sleep 5
done
grep -m1 "GPU KV cache size" "$RUN/server.log" | tee "$RUN/kv_capacity.txt" || true

collect() {  # $1 = trace file
  "$PY" "$HERE/collect_trace.py" --out "$1" --metrics "http://localhost:$PORT/metrics" --kv-endpoint tcp://localhost:5557 &
  COLL=$!
}
stop_collect() { kill -INT $COLL 2>/dev/null; wait $COLL 2>/dev/null || true; }

if [[ "$MODE" == "common" ]]; then
  for R in $RATES; do
    for S in $SEEDS; do
      collect "$RUN/trace_r${R}_s${S}.jsonl"
      "$PY" -m vllm.entrypoints.cli.main bench serve --backend vllm --model "$MODEL" --served-model-name dp1 \
        --port "$PORT" --endpoint /v1/completions \
        --dataset-name random --random-input-len 8192 --random-output-len 256 --random-range-ratio 0 \
        --ignore-eos --num-prompts "$NUM_PROMPTS" --request-rate "$R" --seed "$S" \
        --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,90,99 \
        --goodput ttft:2000 tpot:50 \
        --save-result --save-detailed --result-dir "$RUN" --result-filename "bench_r${R}_s${S}.json"
      stop_collect
    done
  done
else
  for K in $KINDS; do
    for R in $RATES; do
      for S in $SEEDS; do
        WL="$RUN/wl_${K}_r${R}_s${S}.jsonl"
        (cd "$SIM_DIR" && "$PY" run_dp1.py workload --kind "$K" --rate "$R" --seed "$S" --horizon "$HORIZON" --out "$WL")
        collect "$RUN/trace_${K}_r${R}_s${S}.jsonl"
        "$PY" "$HERE/dp1_client.py" --workload "$WL" --out "$RUN/client_${K}_r${R}_s${S}.jsonl" \
          --model dp1 --url "http://localhost:$PORT/v1/completions" --max-model-len "$MAX_MODEL_LEN"
        stop_collect
        # reset prefix cache between points so every point starts from the same (empty) initial state
        curl -sf -X POST "http://localhost:$PORT/reset_prefix_cache?reset_external=true" >/dev/null || true
      done
    done
  done
fi
echo "results in $RUN"
