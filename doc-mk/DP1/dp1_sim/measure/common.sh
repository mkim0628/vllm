#!/usr/bin/env bash
# Shared settings for all DP1 measurement scripts. Override via environment.
#   GPU_KEY : key in configs/hw_catalog.json (a100_sxm4_80g | a100_pcie_80g | h100_sxm5_80g | h100_pcie_80g)
#   TP      : tensor parallel size (70B BF16 needs >= 2 x 80GB; 4 recommended, 8 for A100 TTFT SLO)
#   MODEL   : HF id or local path
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "$HERE/.." && pwd)"
: "${GPU_KEY:?set GPU_KEY, e.g. export GPU_KEY=a100_sxm4_80g}"
: "${TP:=4}"
: "${MODEL:=meta-llama/Llama-3.1-70B-Instruct}"
: "${MODEL_KEY:=llama_3_1_70b}"          # key in hw_catalog.json models
: "${PORT:=8000}"
: "${PY:=python}"                        # the venv python where this vLLM checkout is installed
: "${MAX_MODEL_LEN:=32768}"
OUT="$SIM_DIR/measured/$GPU_KEY"
mkdir -p "$OUT"
export GPU_KEY TP MODEL MODEL_KEY PORT PY OUT SIM_DIR HERE MAX_MODEL_LEN
