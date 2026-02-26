#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

MODEL_NAME="${MODEL_NAME:-meta-llama/Llama-3.1-8B-Instruct}"
PREFILL_PORT="${PREFILL_PORT:-8100}"
DECODE_PORT="${DECODE_PORT:-8200}"
PROXY_PORT="${PROXY_PORT:-9000}"

PREFILL_CONFIG="${PREFILL_CONFIG:-${SCRIPT_DIR}/configs/lmcache-prefiller-config.yaml}"
DECODE_CONFIG="${DECODE_CONFIG:-${SCRIPT_DIR}/configs/lmcache-decoder-config.yaml}"

if ! command -v vllm >/dev/null 2>&1; then
  echo "vllm CLI not found in PATH"
  exit 1
fi

if [[ ! -f "${PREFILL_CONFIG}" ]]; then
  echo "prefill config not found: ${PREFILL_CONFIG}"
  exit 1
fi
if [[ ! -f "${DECODE_CONFIG}" ]]; then
  echo "decode config not found: ${DECODE_CONFIG}"
  exit 1
fi

cleanup() {
  echo "[toy] cleaning up processes..."
  pkill -P $$ || true
}
trap cleanup EXIT INT TERM

echo "[toy] MODEL=${MODEL_NAME}"
echo "[toy] starting prefiller:${PREFILL_PORT}, decoder:${DECODE_PORT}, proxy:${PROXY_PORT}"
echo "[toy] prefill config: ${PREFILL_CONFIG}"
echo "[toy] decode config : ${DECODE_CONFIG}"

echo "[toy] note: fixed PYTHONHASHSEED is used for demo-only key compatibility"
export PYTHONHASHSEED="${VLLM_PYTHON_HASH_SEED:-123}"

(
  cd "${ROOT_DIR}"
  UCX_TLS=cuda_ipc,cuda_copy,tcp \
  LMCACHE_CONFIG_FILE="${PREFILL_CONFIG}" \
  LMCACHE_USE_EXPERIMENTAL=True \
  VLLM_ENABLE_V1_MULTIPROCESSING=1 \
  VLLM_WORKER_MULTIPROC_METHOD=spawn \
  CUDA_VISIBLE_DEVICES="${PREFILL_CUDA_VISIBLE_DEVICES:-0}" \
  vllm serve "${MODEL_NAME}" \
    --port "${PREFILL_PORT}" \
    --enforce-eager \
    --kv-transfer-config '{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_producer","kv_connector_extra_config":{"discard_partial_chunks":false,"lmcache_rpc_port":"producer1"}}'
) > "${SCRIPT_DIR}/prefiller.log" 2>&1 &

(
  cd "${ROOT_DIR}"
  UCX_TLS=cuda_ipc,cuda_copy,tcp \
  LMCACHE_CONFIG_FILE="${DECODE_CONFIG}" \
  LMCACHE_USE_EXPERIMENTAL=True \
  VLLM_ENABLE_V1_MULTIPROCESSING=1 \
  VLLM_WORKER_MULTIPROC_METHOD=spawn \
  CUDA_VISIBLE_DEVICES="${DECODE_CUDA_VISIBLE_DEVICES:-1}" \
  vllm serve "${MODEL_NAME}" \
    --port "${DECODE_PORT}" \
    --enforce-eager \
    --kv-transfer-config '{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_consumer","kv_connector_extra_config":{"discard_partial_chunks":false,"lmcache_rpc_port":"consumer1"}}'
) > "${SCRIPT_DIR}/decoder.log" 2>&1 &

(
  cd "${ROOT_DIR}"
  python3 "${SCRIPT_DIR}/proxy_server.py" \
    --host 0.0.0.0 \
    --port "${PROXY_PORT}" \
    --prefill-base-url "http://127.0.0.1:${PREFILL_PORT}/v1" \
    --decode-base-url "http://127.0.0.1:${DECODE_PORT}/v1"
) > "${SCRIPT_DIR}/proxy.log" 2>&1 &

wait
