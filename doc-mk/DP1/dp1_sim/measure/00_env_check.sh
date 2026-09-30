#!/usr/bin/env bash
# Phase 0/1: record the exact HW/SW revision (criteria §2.1 "동일 SW revision").
source "$(dirname "$0")/common.sh"
nvidia-smi -q > "$OUT/nvidia-smi-q.txt"
nvidia-smi topo -m > "$OUT/nvidia-smi-topo.txt" || true
lscpu > "$OUT/lscpu.txt" || true
numactl -H > "$OUT/numactl.txt" 2>/dev/null || true
"$PY" - <<PY
import json, os, platform, subprocess
q = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,pcie.link.gen.max,pcie.link.width.max,driver_version",
                    "--format=csv,noheader"], capture_output=True, text=True).stdout.strip().splitlines()
mem = [l for l in open("/proc/meminfo") if l.startswith("MemTotal")][0].split()[1]
env = {"gpus": q, "host_mem_bytes": int(mem) * 1024, "hostname": platform.node(),
       "cpu": platform.processor(), "python": platform.python_version()}
try:
    import torch, vllm
    env.update(torch=torch.__version__, cuda=torch.version.cuda, vllm=vllm.__version__)
except Exception as e:  # noqa
    env["import_error"] = str(e)
try:
    env["git_rev"] = subprocess.run(["git", "-C", os.environ["SIM_DIR"], "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
except Exception:
    pass
json.dump(env, open(os.path.join(os.environ["OUT"], "env.json"), "w"), indent=2)
print(json.dumps(env, indent=2))
PY
