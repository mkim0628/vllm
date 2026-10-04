#!/usr/bin/env python3
"""Render the generated block of doc-mk/Evaluation/system-specs.md from the JSON configs.

Usage: python3 gen_system_specs.py [--check]
Sources: DP1/sim/configs/{systems,clusters,memories_default,models}.json (stdlib only).
Only the text between <!-- BEGIN GENERATED --> and <!-- END GENERATED --> is replaced.
"""
import json, subprocess, sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
CFG = EVAL / "DP1" / "sim" / "configs"
DOC = EVAL / "system-specs.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"
MEM_ORDER = ["hbm", "custom_hbm", "cxl_pnm", "dram", "hbf", "ssd_pim"]


def load(n):
    return json.loads((CFG / n).read_text())


def bw(x):
    if x is None: return "-"
    return f"{x/1e12:.3g} TB/s" if x >= 1e12 else f"{x/1e9:.3g} GB/s"


def cap(x):
    return f"{x/2**40:.3g} TiB" if x >= 2**40 else f"{x/2**30:.3g} GiB"


def lat(x):
    return f"{x*1e9:.0f} ns" if x < 1e-6 else f"{x*1e6:.3g} us"


def tflops(x):
    return "-" if x is None else f"{x/1e12:.4g} TFLOPS"


def num(x, unit=""):
    return "-" if x is None else f"{x:.4g}{unit}"


def endur(x):
    return "-" if x is None else f"{x/1e15:.3g} PB"


def provenance_flag(text):
    t = text or ""
    return "ASSUMED" in t or "확인 필요" in t


def git_rev():
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--format=%h", "--", str(CFG)],
            cwd=EVAL, text=True, stderr=subprocess.DEVNULL).strip() or "n/a"
    except Exception:
        return "n/a"


def esc(s):
    return " ".join((s or "").split()).replace("|", "\\|")


LINK_BOUND = ("custom_hbm", "cxl_pnm", "dram", "ssd_pim")  # keep in sync with model.LINK_BOUND_MEMORIES


def eff(m, g, n, prof):
    """Effective memory dict for a profile: mirrors model.load_system() (cluster HBM, paired-GPU cHBM, link scale, overrides)."""
    m = dict(m)
    if m["name"] == "hbm":
        m["capacity_bytes"] = g["hbm_capacity_bytes"] * n
        m["ext_bw_bytes_per_s"] = g["hbm_bw_bytes_per_s"] * n
        m["int_bw_bytes_per_s"] = m["ext_bw_bytes_per_s"]
    elif m["name"] == "custom_hbm":
        m["capacity_bytes"] = g["hbm_capacity_bytes"] * 2
        m["int_bw_bytes_per_s"] = g["hbm_bw_bytes_per_s"] * 2
        m["compute_tflops_fp16"] = g["dense_fp16_flops"] * 0.2
        m["tdp_watts"] = g["tdp_watts"] / 3
    if m["name"] in LINK_BOUND:
        m["ext_bw_bytes_per_s"] *= (prof.get("link") or {}).get("ext_bw_scale", 1.0)
    for k, v in (prof.get("overrides") or {}).get(m["name"], {}).items():
        if k in ("capacity_bytes", "ext_bw_bytes_per_s", "int_bw_bytes_per_s", "latency_s"):
            m[k] = v
    return m


def mem_row(m):
    c, e, i = m["capacity_bytes"], m["ext_bw_bytes_per_s"], m["int_bw_bytes_per_s"]
    hops = " -> ".join(m.get("hops", [])) or ("on-package" if m["name"] == "hbm" else "-")
    wbw = m.get("write_bw_bytes_per_s")
    return [m["name"], cap(c), bw(e), bw(i), lat(m["latency_s"]),
            "yes" if m.get("gpu_reachable") else "no", hops,
            tflops(m.get("compute_tflops_fp16")),
            bw(wbw) if wbw else "= ext",
            num(m.get("write_amplification"), "x"), endur(m.get("endurance_budget_bytes")),
            num(m.get("tdp_watts"), " W")]


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def ctx(sy, cl, mems, pid):
    p = sy["profiles"][pid]; c = cl["clusters"][p["cluster"]]; g = cl["gpus"][c["gpu"]]
    return p, c, g, c["gpus_per_scaleup_domain"], {n: eff(mems[n], g, c["gpus_per_scaleup_domain"], p) for n in p["memories"]}


def render_summary():
    sy, cl, mem = load("systems.json"), load("clusters.json"), load("memories_default.json")
    mems = {m["name"]: m for m in mem["memories"]}
    ids = [k for k, p in sy["profiles"].items() if p.get("primary")]
    cs = {k: ctx(sy, cl, mems, k) for k in ids}
    rows = []
    def add(label, f):
        rows.append([label] + [f(*cs[k]) for k in ids])
    add("GPU class (x GPUs/domain)", lambda p, c, g, n, e: f"{c['gpu']} x{n}")
    add("HBM generation", lambda p, c, g, n, e: g["hbm_medium"])
    add("HBM / GPU: cap, BW", lambda p, c, g, n, e: f"{cap(g['hbm_capacity_bytes'])}, {bw(g['hbm_bw_bytes_per_s'])}")
    add("HBM domain total BW", lambda p, c, g, n, e: bw(e["hbm"]["ext_bw_bytes_per_s"]))
    add("FP16 dense / GPU", lambda p, c, g, n, e: tflops(g["dense_fp16_flops"]))
    add("Host link / CXL", lambda p, c, g, n, e: f"{p['generation']['host_link']} / {p['generation']['cxl'].split(' (')[0]}")
    add("Link BW (x16, per dir)", lambda p, c, g, n, e: bw(63e9 * p["link"]["ext_bw_scale"]))
    add("Samsung Custom HBM(ScHBM): cap / int BW / ext BW", lambda p, c, g, n, e: f"{cap(e['custom_hbm']['capacity_bytes'])} / {bw(e['custom_hbm']['int_bw_bytes_per_s'])} / {bw(e['custom_hbm']['ext_bw_bytes_per_s'])}")
    add("CXL-PNM: int / ext BW", lambda p, c, g, n, e: f"{bw(e['cxl_pnm']['int_bw_bytes_per_s'])} / {bw(e['cxl_pnm']['ext_bw_bytes_per_s'])}")
    add("DRAM gen: int / ext BW", lambda p, c, g, n, e: f"{p['generation']['dram']} : {bw(e['dram']['int_bw_bytes_per_s'])} / {bw(e['dram']['ext_bw_bytes_per_s'])}")
    add("HBF: read BW (link-independent)", lambda p, c, g, n, e: bw(e["hbf"]["ext_bw_bytes_per_s"]))
    add("SSD gen / SSD-PIM ext BW", lambda p, c, g, n, e: f"{p['generation']['ssd']} : {bw(e['ssd_pim']['ext_bw_bytes_per_s'])}")
    L = ["> 4개 generation profile. **6종 메모리(HBM, Samsung Custom HBM(ScHBM), CXL-PNM, DRAM, HBF, SSD-PIM)는 모든 profile에 항상 존재**하고 "
         "세대(GPU/HBM, host link, DRAM, SSD)만 다르다. 값의 provenance는 아래 G.3 / G.4 및 3장. 이 블록은 `tools/gen_system_specs.py`가 생성한다.", ""]
    L += table(["Item"] + [f"**{k}**" for k in ids], rows)
    return "\n".join(L)


def render():
    sy, cl, mem, mod = load("systems.json"), load("clusters.json"), load("memories_default.json"), load("models.json")
    mems = {m["name"]: m for m in mem["memories"]}
    L = [f"> Generated by `doc-mk/Evaluation/tools/gen_system_specs.py` from `DP1/sim/configs/*.json` "
         f"(config git revision: `{git_rev()}`). Do not edit by hand.", ""]
    L += ["## G.1 Profile list", ""]
    L += table(["SYS id", "Role", "Name", "Cluster", "Memories", "Default"],
               [[f"**{k}**", "primary (generation)" if p.get("primary") else "legacy (memory-subset ablation)",
                 esc(p["name"]), p["cluster"], ", ".join(p["memories"]),
                 "yes" if k == sy["default"] else ""] for k, p in sy["profiles"].items()])
    L += ["", "## G.2 GPU / cluster specs", ""]
    rows = []
    for cid, c in cl["clusters"].items():
        g = cl["gpus"][c["gpu"]]; n = c["gpus_per_scaleup_domain"]
        rows.append([cid, c["gpu"], g["hbm_medium"], f"{g['hbm_capacity_bytes']/1e9:.0f} GB ({cap(g['hbm_capacity_bytes'])})", bw(g["hbm_bw_bytes_per_s"]),
                     tflops(g["dense_fp16_flops"]), num(g["tdp_watts"], " W"), str(n),
                     c["domain_interconnect"], str(c["custom_hbm_nodes_per_domain"]),
                     f"{g['hbm_capacity_bytes']*n/1e9:.0f} GB / {bw(g['hbm_bw_bytes_per_s']*n)}"])
    L += table(["Cluster", "GPU", "HBM", "HBM cap/GPU", "HBM BW/GPU", "FP16 dense/GPU", "TDP/GPU",
                "GPUs/domain", "Interconnect", "cHBM nodes/domain", "Domain HBM (cap / BW)"], rows)
    L += ["", "Provenance (clusters.json):", ""]
    for gid, g in cl["gpus"].items():
        flag = " **[ASSUMED/확인 필요 포함]**" if provenance_flag(g["provenance"]) else ""
        L.append(f"- `{gid}`{flag}: {esc(g['provenance'])}")
    for cid, c in cl["clusters"].items():
        L.append(f"- `{cid}`: {esc(c.get('_why'))}")
    t = cl.get("_topology", {})
    L += ["", f"Topology note: {esc(t.get('path'))}. {esc(t.get('bottleneck'))}.", ""]
    L += ["## G.3 Per-profile memory tables (primary: generation profiles)", "",
          "HBM row = domain aggregate (per-GPU x GPUs/domain), custom_hbm = paired-GPU rule, link-bound tiers "
          "(custom_hbm, cxl_pnm, dram, ssd_pim) ext BW = baseline x link scale, as computed by `model.load_profile()`. "
          "`write BW = ext`: no separate write BW (simulator uses ext BW). All values Evidence [B].", ""]
    head = ["Memory", "Capacity", "Ext BW", "Int BW", "Latency", "GPU-reachable", "Access hops",
            "Compute FP16", "Write BW", "Write amp.", "Endurance", "TDP"]
    for sid, p in sy["profiles"].items():
        if not p.get("primary"):
            continue
        _, c, g, n, e = ctx(sy, cl, mems, sid)
        gen = p["generation"]
        L += [f"### {sid} - {esc(p['name'])}", "",
              f"- Purpose: {esc(p['purpose'])}",
              f"- Cluster `{p['cluster']}` ({n}x {c['gpu']}, {c['domain_interconnect']}); generations: "
              + ", ".join(f"{k}={v}" for k, v in gen.items()), ""]
        L += table(head, [mem_row(e[m]) for m in MEM_ORDER if m in e])
        L += ["", "Provenance (generation-specific):", "",
              f"- GPU/HBM `{c['gpu']}`: {esc(g['provenance'])}",
              f"- Link {esc(p['link']['name'])} (scale x{p['link']['ext_bw_scale']:g}): {esc(p['link']['provenance'])}"]
        for mn, ov in (p.get("overrides") or {}).items():
            L.append(f"- override `{mn}`: {esc(ov.get('provenance') or ov.get('provenance_append'))}")
        L += [f"- {esc(p['emerging_scaling_note'])}", ""]
    L += ["### Legacy profiles (memory-subset ablation, values unchanged)", ""]
    for sid, p in sy["profiles"].items():
        if p.get("primary"):
            continue
        L.append(f"- **{sid}** `{p['cluster']}`: {', '.join(p['memories'])} - {esc(p['purpose'])}")
    L += ["", "Legacy values = same cluster + `memories_default.json` baseline (PCIe 5.0 link, DDR5-6400). "
          "SYS-4 == SYS-B200 field by field; SYS-5 == SYS-VR except link-bound ext BW (PCIe 5.0 vs 6.0).", ""]
    L += ["## G.4 Memory device provenance (shared by all profiles; baseline = PCIe 5.0 / DDR5 values)", ""]
    for n in MEM_ORDER:
        mm = mems[n]
        pv = esc(mm["provenance"]); tp = esc(mm.get("tdp_provenance", ""))
        flag = ("**[ASSUMED]** " if provenance_flag(mm["provenance"]) else "")
        tflag = "**[ASSUMED]** " if "ASSUMED" in tp else ""
        L.append(f"- `{n}` {flag}{pv}" + (f" / TDP: {tflag}{tp}" if tp else ""))
    L += ["", "## G.5 Model spec", "", f"Default model: `{mod['default']}` (models.json).", ""]
    mm = mod["models"]["llama_3_1_70b"]
    kvb = 2 * mm["num_layers"] * mm["num_kv_heads"] * mm["head_dim"] * mm["dtype_bytes"]
    L += table(["Field", "Value"], [[k, "-" if v is None else str(v)] for k, v in mm.items()])
    L += ["", f"Derived: KV bytes/token = 2 x layers x kv_heads x head_dim x dtype_bytes = {kvb} B "
              f"({kvb/1024:.0f} KiB); 8K context = {kvb*8192/2**30:.2f} GiB per sequence.", ""]
    return "\n".join(L)


def splice(txt, begin, end, body):
    if begin not in txt or end not in txt:
        sys.exit(f"markers {begin} not found in {DOC}")
    return txt[:txt.index(begin)] + f"{begin}\n{body}\n{end}" + txt[txt.index(end) + len(end):]


SB, SE = "<!-- BEGIN GENERATED SUMMARY -->", "<!-- END GENERATED SUMMARY -->"


def main():
    if not DOC.exists():
        print(render_summary()); print(render()); return
    txt = DOC.read_text()
    new = splice(splice(txt, SB, SE, render_summary()), BEGIN, END, render())
    if "--check" in sys.argv:
        sys.exit(0 if new == txt else 1)
    DOC.write_text(new)
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
