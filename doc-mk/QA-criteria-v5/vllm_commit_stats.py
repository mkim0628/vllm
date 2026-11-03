"""vLLM 최근 commit의 변경 파일 수 분포 (QA-04 별 기준 근거).
사용: python vllm_commit_stats.py <vllm-project/vllm clone 경로> [N commits=1500]
squash merge라 main의 commit 1개 ≈ PR 1개로 본다(확인하지 않음). shallow 경계 commit은 제외.
소스 = tests/ .buildkite/ .github/ docs/ examples/ benchmarks/ *.md 를 뺀 파일.
"""
import json, re, subprocess, sys
import numpy as np
repo = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
raw = subprocess.run(["git", "-C", repo, "log", f"-n{n-1}", "--no-merges", "--name-only",
                      "--pretty=format:@@%H|%ad|%s", "--date=short"], capture_output=True, text=True, check=True).stdout
cm, cur = [], None
for ln in raw.split("\n"):
    if ln.startswith("@@"):
        h, d, t = ln[2:].split("|", 2); cur = dict(d=d, t=t, f=[]); cm.append(cur)
    elif ln and cur is not None: cur["f"].append(ln)
cm = [c for c in cm if c["f"]]
def is_src(f): return not (f.startswith(("tests/", ".buildkite/", ".github/", "docs/", "examples/", "benchmarks/")) or f.endswith(".md"))
def dist(vals):
    v = np.array(vals)
    return dict(n=len(v), mean=float(v.mean()), median=float(np.median(v)), p75=float(np.percentile(v, 75)),
                p80=float(np.percentile(v, 80)), p90=float(np.percentile(v, 90)),
                cdf={str(k): float((v <= k).mean()) for k in range(1, 11)})
kv = [c for c in cm if any(re.search(r"kv_transfer|kv_offload|kv_connector|simple_kv_offload", f) for f in c["f"])]
feat = [c for c in kv if re.search(r"\b(add|support|introduce|new|implement)\b", c["t"], re.I)
        and re.search(r"connector|offload|nixl|mooncake|lmcache|flexkv|hf3fs|moriio|p2p", c["t"], re.I)]
src = lambda cs: [x for x in (sum(is_src(f) for f in c["f"]) for c in cs) if x > 0]
out = dict(commits=len(cm), date_from=min(c["d"] for c in cm), date_to=max(c["d"] for c in cm),
           all_files=dist([len(c["f"]) for c in cm]), src_files=dist(src(cm)),
           kv_all=dist([len(c["f"]) for c in kv]), kv_src=dist(src(kv)), kv_feature_src=dist(src(feat)),
           kv_feature_titles=[(c["d"], len(c["f"]), sum(is_src(f) for f in c["f"]), c["t"][:100]) for c in feat])
json.dump(out, open(__file__.replace("vllm_commit_stats.py", "vllm_commit_stats.json"), "w"), indent=1, ensure_ascii=False)
for k in ("all_files", "src_files", "kv_src", "kv_feature_src"):
    d = out[k]; print(k, d["n"], "median", d["median"], "p80", d["p80"], {a: round(b, 2) for a, b in d["cdf"].items() if int(a) <= 6})
