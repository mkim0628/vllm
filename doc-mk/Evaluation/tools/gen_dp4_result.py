#!/usr/bin/env python3
"""Generate the DP4 QA evaluation result document from the committed result data (no hand-typed numbers).

    uv run --no-project python doc-mk/Evaluation/tools/gen_dp4_result.py [--check]

Inputs (all under DP4/results/data/): INT-H100-B200/qa_result.json (main, integrated), SYS-H100/, SYS-B200/ (consistency),
ablation/, star_basis/, sensitivity/, pre_serial_read/ (superseded model, old -> new), protocol_check*.json, qa4_*.json,
plus DP4/qa_priority.json and results/iterations/loop-log.md (cross-check only).
Output: DP4/results/2026-10-04_dp4-qa-evaluation.md. Deterministic: no clock, no live git query (git revision = the one recorded in the data meta).
Also imported by gen_dp4_pptx.py so that slides and document share the same numbers.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dp_selection import n as nstar, select  # noqa: E402

ROOT = HERE.parent                      # doc-mk/Evaluation
DP = ROOT / "DP4"
DATA = DP / "results" / "data"
SIM = DP / "sim"
DATE = "2026-10-04"
OUT = DP / "results" / f"{DATE}_dp4-qa-evaluation.md"

B, C1, C2 = "Baseline-RDMA", "C1-central-serialization", "C2-distributed-lock"
CANDS = (C1, C2)
SHORT = {B: "Baseline", C1: "C1", C2: "C2"}
SYSIDS = ["SYS-H100", "SYS-B200"]
MERGED = "INT-H100-B200"
SETS = [("common_benchmark", "Common"), ("dp4_benchmark", "DP4-specific")]
FIT_LETTER = {"comparison_valid": "V", "infeasible": "I", "saturated": "S"}


def jl(p):
    return json.loads(Path(p).read_text())


R = {s: jl(DATA / s / "qa_result.json") for s in SYSIDS + [MERGED]}
RM = R[MERGED]
PRE = jl(DATA / "pre_serial_read" / MERGED / "qa_result.json")
PRE_SYS = {s: jl(DATA / "pre_serial_read" / s / "qa_result.json") for s in SYSIDS}
ABL = jl(DATA / "ablation" / MERGED / "qa_result.json")
ABL_SYS = {s: jl(DATA / "ablation" / s / "qa_result.json") for s in SYSIDS}
SB = {s: jl(DATA / "star_basis" / f"star_basis_{s}.json") for s in SYSIDS}
SENS = jl(DATA / "sensitivity" / "summary.json")
PRE_SENS = jl(DATA / "pre_serial_read" / "sensitivity" / "summary.json")
PC = {2: jl(DATA / "protocol_check.json"), 3: jl(DATA / "protocol_check_n3.json")}
Q4 = jl(DATA / "qa4_modifiability.json")
Q4M = jl(DATA / "qa4_measured_counts.json")
PRIO = jl(DP / "qa_priority.json")
CFG = jl(SIM / "configs" / "cluster_dp4.json")["params"]
LOOPLOG = (DP / "results" / "iterations" / "loop-log.md").read_text()
DP1CFG = ROOT / "DP1" / "sim" / "configs"
CLUSTERS = jl(DP1CFG / "clusters.json")
SYSPROF = jl(DP1CFG / "systems.json")["profiles"]
MODELS = jl(DP1CFG / "models.json")["models"]

CBQ = RM["common_benchmark"]["qa_feasible"]       # official star basis (pre-registered: Common Benchmark only)
CBLAB = RM["common_benchmark"]["scenario_labels"]
DPLAB = RM["dp4_benchmark"]["scenario_labels"]
CBPS = RM["common_benchmark"]["per_scenario"]
DPPS = RM["dp4_benchmark"]["per_scenario"]
COMB = RM["combined"]
META = RM["meta"]
Q4_STARS = {C1: Q4["qa4_stars"]["C1"], C2: Q4["qa4_stars"]["C2"]}


# --------------------------------------------------------------------------- small helpers
def f0(v):
    return f"{v:,.0f}"


def f1(v):
    return f"{v:,.1f}"


def f2(v):
    return f"{v:,.2f}"


def f3(v):
    return f"{v:,.3f}"


def xr(v, nd=2):
    return f"x{v:.{nd}f}"


def pct(v, nd=1):
    return f"{v * 100:.{nd}f}%"


def gm(xs):
    xs = list(xs)
    return math.exp(sum(math.log(max(1e-12, x)) for x in xs) / len(xs))


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def sysname(sn):
    return sn.split("@")[1] if "@" in sn else ""


def bysys(d, f=None):
    """'H100 x0.52, B200 x1.66' from {row@SYS: value}."""
    f = f or (lambda v: xr(v, 2))
    return ", ".join(f"{k.split('@')[1]} {f(v)}" for k, v in d.items())


def git_line():
    """Revision exactly as recorded in the data meta (not a live query: the document must not change when HEAD moves)."""
    sg = META["source_git"]
    fl = lambda g: "dirty" if g["dirty"] else "clean"
    return (f"{META['git']['revision']} (integrated file: {fl(META['git'])}; SYS-H100 run: {fl(sg['SYS-H100'])}, SYS-B200 run: {fl(sg['SYS-B200'])}; "
            f"flags as recorded in `qa_result.json` meta; `dirty` = uncommitted changes under `doc-mk/Evaluation/DP4` at run time)")


# --------------------------------------------------------------------------- facts shared by document and slides
def stars_cb():
    """{cand: {QA1..QA4: stars}} on the official (Common Benchmark) basis."""
    return {c: {"QA1": CBQ[c]["qa1"], "QA2": CBQ[c]["qa2"], "QA3": CBQ[c]["qa3"], "QA4": Q4_STARS[c]} for c in CANDS}


def selection():
    return select(stars_cb(), PRIO["priority"])


def fit_counts(res=None):
    res = res or RM
    out = {}
    for lab, _ in SETS:
        fit = res[lab]["fit"]
        out[lab] = {k: sum(1 for v in fit.values() if v == k) for k in ("comparison_valid", "saturated", "infeasible")}
    return out


def tally_counts(cand, res=None):
    t = (res or RM)["combined"]["tally"][cand]
    return len(t["win"]), len(t["tie"]), len(t["loss"])


def qa4_at_scale(c, s):
    """QA4 sub-stars if the pre-registered thresholds are multiplied by s (mean aggregation, unrounded means)."""
    m = Q4["mean_over_scenarios_unrounded"]["C1" if c == C1 else "C2"]
    def star(v, lo, hi):
        return 3 if v <= lo * s else (2 if v <= hi * s else 1)
    sub = dict(M1=star(m["modules"], 2, 5), M2=star(m["man_months"], 0.5, 1.0), M3=star(m["usd_T1"], 3, 10))
    return sub, sorted(sub.values())[1]


def qa4_variants():
    """[(label, stars_C1, stars_C2)] of QA4 under the aggregation / constants / structure alternatives reported in qa4_modifiability.json."""
    st = lambda n: "★" * n
    out = [("main: 시나리오 평균 집계, 중간 상수", Q4_STARS[C1], Q4_STARS[C2]),
           ("최악값 집계 (v1, 사전 정의 이전 형태)", Q4["qa4_stars_worst_case"]["C1"], Q4["qa4_stars_worst_case"]["C2"])]
    for k, v in Q4["sensitivity_constants"].items():
        if k != "mid":
            out.append((f"상수 {k} (low/high 동시)", v["C1"]["qa4"], v["C2"]["qa4"]))
    for k, v in Q4["sensitivity_constants_cross"].items():
        out.append((f"상수 교차 {k}", v["C1"]["qa4"], v["C2"]["qa4"]))
    for k, v in Q4["sensitivity_one_at_a_time"].items():
        out.append((f"상수 1개만 {k}", v["C1"]["qa4"], v["C2"]["qa4"]))
    for k, v in Q4["sensitivity_structure_alternatives"].items():
        out.append((f"구조 대안 {k}", v["C1"]["qa4"], v["C2"]["qa4"]))
    for s in (0.9, 1.1):
        out.append((f"별 경계 x{s} (M1/M2/M3 threshold 동시)", st(qa4_at_scale(C1, s)[1]), st(qa4_at_scale(C2, s)[1])))
    return out


def decision_under(q4c1, q4c2):
    stars = stars_cb()
    stars[C1] = dict(stars[C1], QA4=q4c1)
    stars[C2] = dict(stars[C2], QA4=q4c2)
    return select(stars, PRIO["priority"])


def decision_table():
    rows, kept, tied = [], 0, 0
    for lab, a, b in qa4_variants():
        o = decision_under(a, b)
        w = {C1: "C1", C2: "C2", None: "**미결정(동점)**"}[o["winner"]]
        kept += o["winner"] == C1
        tied += o["winner"] is None
        rows.append((lab, a, b, o["totals"][C1], o["totals"][C2], w))
    return rows, kept, tied


def scenario_rows(label):
    """[(row@SYS, scenario_row_name, sysid)] in stable order."""
    names = sorted({k.split("@")[0] for k in RM[label]["per_scenario"]})
    return names


def valid_pairs(label):
    return [k for k, l in RM[label]["scenario_labels"].items() if l["fit"] == "comparison_valid"]


def cp_ranges():
    """control-plane op latency ranges over the DP4 rows (C1 and C2 P50, C2/C1 P50 ratio)."""
    out = {}
    for kd in ("lookup", "publish", "pin", "unpin"):
        l = [v["cp_op_latency"][kd] for v in RM["dp4_benchmark"]["c1_vs_c2"].values() if kd in v["cp_op_latency"]]
        out[kd] = dict(c1=(min(x["c1_p50_us"] for x in l), max(x["c1_p50_us"] for x in l)),
                       c2=(min(x["c2_p50_us"] for x in l), max(x["c2_p50_us"] for x in l)),
                       ratio=(min(x["p50_ratio_c2_over_c1"] for x in l), max(x["p50_ratio_c2_over_c1"] for x in l)), n=len(l))
    return out


def headroom():
    """[(headroom_x, row, cand, sat_rps, offered_rps)] sorted ascending: control-plane saturation rate / offered request rate of the same row (own-peak load)."""
    rows = []
    for sn, v in RM["dp4_benchmark"]["cp_capacity"].items():
        for c in CANDS:
            off = DPPS[sn][c]["offered_rps"]
            rows.append((v[c]["saturation_rps"] / off, sn, c, v[c]["saturation_rps"], off))
    return sorted(rows)


def agg_dev_c1_c2():
    """max relative difference between C2 and C1 over the Common set QA values and over all non-failure DP4 pairs."""
    q = {k: abs(CBQ[C2][k] / CBQ[C1][k] - 1) for k in ("qa1_abs_goodput_geomean_tps", "qa2_common_ttft_p99_ms_geomean", "qa3_kv_resident_gib_geomean")}
    dpd = [abs(v["goodput_ratio_c2_over_c1"] - 1) for sn, v in RM["dp4_benchmark"]["c1_vs_c2"].items() if "fail" not in sn and v["goodput_ratio_c2_over_c1"]]
    return q, max(dpd)


def fail_rows():
    return sorted(RM["dp4_benchmark"]["failure"])


def goodput_ratio(label, sn, c):
    ps = (CBPS if label == "common_benchmark" else DPPS)[sn]
    return ps[c]["max_goodput_tps"] / ps[B]["max_goodput_tps"]


_SCEN = {}


def dp4_scenarios():
    """DP4/sim/scenarios.py loaded under a private module name (DP1/sim/scenarios.py has the same file name)."""
    if "m" not in _SCEN:
        import importlib.util
        spec = importlib.util.spec_from_file_location("dp4_scenarios_src", SIM / "scenarios.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["dp4_scenarios_src"] = mod
        spec.loader.exec_module(mod)
        _SCEN["m"] = mod
    return _SCEN["m"]


def row_nodes():
    """{result row name: number of nodes (P + D)} from the single scenario source DP4/sim/scenarios.py."""
    scenarios = dp4_scenarios()
    out = {}
    for fn in (scenarios.common_benchmark, scenarios.dp4_benchmark):
        for sc in fn():
            for name, k in sc.rows():
                out[name] = k["n_p"] + k["n_d"]
    return out


def n_dp4_scen():
    return len(dp4_scenarios().dp4_benchmark())


def lab_of(sn):
    return "common_benchmark" if sn in CBPS else "dp4_benchmark"


def win_pairs():
    """pairs where the candidates beat the Baseline (verdict 'win'); C1 and C2 are identical here (asserted)."""
    out = []
    for lab, labs in (("common_benchmark", CBLAB), ("dp4_benchmark", DPLAB)):
        for k in sorted(labs):
            v = labs[k]["vs_baseline"]
            if v[C1]["verdict"] == "win" or v[C2]["verdict"] == "win":
                assert v[C1]["verdict"] == v[C2]["verdict"], k
                out.append((lab, k))
    return out


def n_goodput_wins():
    """number of (pair, candidate) cells whose goodput is better than the Baseline outside the 95% CI / 1% tie band."""
    return sum(1 for labs in (CBLAB, DPLAB) for l in labs.values() for c in CANDS if l["fit"] != "infeasible" and l["vs_baseline"][c]["goodput"] == "win")


def seed_list(sn, arm, key="seeds_goodput_tps"):
    return (CBPS if sn in CBPS else DPPS)[sn][arm][key]


def dp4_ttft_tail():
    """own-peak TTFT P99 candidate / Baseline over the non-failure DP4 pairs (SKILL section 10 tail check) and the verdict counts."""
    ratios, loss = [], 0
    for k, v in DPPS.items():
        if "fail" in k:
            continue
        ratios.append(v[C1]["ttft_p99_ms"] / v[B]["ttft_p99_ms"])
        loss += DPLAB[k]["vs_baseline"][C1]["ttft"] == "loss"
    return dict(n=len(ratios), loss=loss, lo=min(ratios), hi=max(ratios), med=statistics.median(ratios), worse=sum(1 for r in ratios if r > 1.01))


# --------------------------------------------------------------------------- system / memory configuration (H24)
def kv_bytes_per_token():
    m = MODELS["llama_3_1_70b"]
    return 2 * m["num_layers"] * m["num_kv_heads"] * m["head_dim"] * m["dtype_bytes"]


def sys_facts(sid):
    prof = SYSPROF[sid]
    cl = CLUSTERS["clusters"][prof["cluster"]]
    gpu = CLUSTERS["gpus"][cl["gpu"]]
    n = cl["gpus_per_scaleup_domain"]
    return dict(gen=prof["generation"], hbm_gib=gpu["hbm_capacity_bytes"] * n / 2**30, hbm_bw=gpu["hbm_bw_bytes_per_s"] * n / 1e12,
                fp16=gpu["dense_fp16_flops"] / 1e12, gpus=n, hbm_med=gpu["hbm_medium"], gpu=cl["gpu"])


def cfgv(name):
    return CFG[name]["value"]


def link_numbers():
    """Back-of-envelope link times of one 8K request (config constants only, not simulator output)."""
    kv = kv_bytes_per_token() * 8192
    bg = 0.85
    nic = cfgv("nic_bw_Bps") * cfgv("eta_rdma")
    cxl = cfgv("cxl_adapters_per_node") * cfgv("cxl_adapter_bw_Bps") * cfgv("eta_cxl")
    return dict(kv_gib=kv / 2**30, kv_gb=kv / 1e9, nic=nic / 1e9, cxl=cxl / 1e9,
                t_rdma_ms=kv / (nic * (1 - bg)) * 1e3, t_cxl_ms=kv / (cxl * (1 - bg)) * 1e3,
                t_rdma_free_ms=kv / nic * 1e3, t_cxl_free_ms=kv / cxl * 1e3, bg=bg)


def prefill_ms():
    """8K prefill time per system from the DP1 physics (DP4/sim/dp1_bridge, read-only reuse)."""
    sys.path.insert(0, str(SIM))
    import dp1_bridge  # noqa: E402
    return {s: dp1_bridge.load_dp1_system(s).prefill_s(8192, 8192) * 1e3 for s in SYSIDS}


# --------------------------------------------------------------------------- consistency checks between data files
def consistency():
    out = []
    # (a) integrated per-pair values equal per-system values
    worst = 0.0
    n = 0
    for lab, _ in SETS:
        for sid in SYSIDS:
            for sn, v in R[sid][lab]["per_scenario"].items():
                for c in (B, C1, C2):
                    a = v[c]["max_goodput_tps"]
                    b_ = RM[lab]["per_scenario"][f"{sn}@{sid[4:]}"][c]["max_goodput_tps"]
                    worst = max(worst, abs(a - b_) / max(1.0, abs(a)))
                    n += 1
    out.append(("통합 파일의 (시나리오, 시스템) 쌍별 Max SLO goodput = 시스템별 파일", n, worst, worst == 0.0))
    # (b) integrated QA1 geomean recomputed from per-system pair ratios
    for c in CANDS:
        rat = []
        for sid in SYSIDS:
            for sn, v in R[sid]["common_benchmark"]["per_scenario"].items():
                rat.append(v[c]["max_goodput_tps"] / v[B]["max_goodput_tps"])
        d = abs(gm(rat) - CBQ[c]["qa1_ratio_geomean"])
        out.append((f"{SHORT[c]} Common QA1 geomean 재계산(시스템별 쌍 {len(rat)}개) vs 통합 파일", len(rat), d, d < 1e-9))
    # (c) ablation control = main
    worst, n = 0.0, 0
    for lab, _ in SETS:
        for sn, v in ABL[lab]["per_scenario"].items():
            for c in (B, C1, C2):
                m = RM[lab]["per_scenario"][sn][c]["max_goodput_tps"]
                worst = max(worst, abs(m - v[c]["max_goodput_tps"]) / max(1.0, abs(m)))
                n += 1
    out.append(("ablation 대조군(full C1/C2/Baseline) = 본 결과 (SKILL §9)", n, worst, worst <= 1e-9))
    # (d) sensitivity control cell
    cc = SENS["control_check"]
    out.append(("sensitivity 통제 셀(eta_cxl 0.5, bg 0.85) = 본 결과", len(cc), max(v["max_abs_diff"] for v in cc.values()), all(v["match"] for v in cc.values())))
    # (e) star basis group 0 = main Baseline
    worst, n = 0.0, 0
    for sid in SYSIDS:
        g0 = SB[sid]["per_group"][0]["goodput"]
        for sn, v in R[sid]["common_benchmark"]["per_scenario"].items():
            worst = max(worst, abs(g0[sn] - v[B]["max_goodput_tps"]) / v[B]["max_goodput_tps"])
            n += 1
    out.append(("star_basis 첫 seed 묶음(11..71) = 본 결과 Baseline", n, worst, worst <= 1e-9))
    # (f) loop-log text vs data (old -> new)
    pq, nq = PRE["common_benchmark"]["qa_feasible"][C1], CBQ[C1]
    checks = [f"{pq['qa1_ratio_geomean']:.3f}", f"{nq['qa1_ratio_geomean']:.3f}", f"{PRE['common_benchmark']['qa_feasible'][C1]['qa3_saving_multiplier']:.2f}",
              f"{nq['qa3_saving_multiplier']:.3f}"]
    ok = all(c in LOOPLOG for c in checks)
    out.append(("loop-log 본문의 수치 (QA1 0.733 -> 0.704, QA3 0.230 -> 0.223) 가 데이터와 일치", len(checks), 0.0 if ok else 1.0, ok))
    t0, t2 = tally_counts(C1, PRE), tally_counts(C1)
    ok = f"{t0[0]}/{t0[1]}/{t0[2]}" in LOOPLOG and f"{t2[0]}/{t2[1]}/{t2[2]}" in LOOPLOG
    out.append(("loop-log의 승/무/패 (2/34/8 -> 4/33/7) 가 데이터와 일치", 2, 0.0 if ok else 1.0, ok))
    # (g) QA4 inputs: files of the proxy implementation vs current sources
    import hashlib
    diff = [f for f, h in Q4M["provenance"]["base_sha1"].items()
            if hashlib.sha1((SIM / f).read_bytes()).hexdigest() != h]
    out.append((f"QA4 측정 기준 소스(sha1)와 현재 `DP4/sim` 소스 일치 (불일치: {', '.join(diff) if diff else '없음'})", len(Q4M['provenance']['base_sha1']), float(len(diff)), not diff))
    return out, diff


# --------------------------------------------------------------------------- 0.1 final table
def final_cells():
    """All numbers of the final QA table (shared by the document and the slides)."""
    q = {c: CBQ[c] for c in (B, C1, C2)}
    cell = {}
    for c in (B, C1, C2):
        x = q[c]
        cell[c] = dict(
            qa1=x["qa1_abs_goodput_geomean_tps"], qa1_r=x["qa1_ratio_geomean"], qa1_ci=x["qa1_ratio_ci95"], s1=x["qa1"], s2=x["qa2"], s3=x["qa3"],
            t99=x["qa2_ttft_p99_ms_geomean"], t50=x["qa2_ttft_p50_ms_geomean"], o99=x["qa2_tpot_p99_ms_geomean"], o50=x["qa2_tpot_p50_ms_geomean"],
            ct99=x["qa2_common_ttft_p99_ms_geomean"], ct50=x["qa2_common_ttft_p50_ms_geomean"], co99=x["qa2_common_tpot_p99_ms_geomean"], co50=x["qa2_common_tpot_p50_ms_geomean"],
            tw=x["qa2_ttft_p99_worst_ms"], ow=x["qa2_tpot_p99_worst_ms"], res=x["qa3_kv_resident_gib_geomean"], save=x["qa3_saving_multiplier"],
            res_own=x["qa3_at_own_peak_gib_geomean"], save1=x["qa3_load1_saving_multiplier"], comp=x["qa3_components_gib_mean"])
    return cell


def final_qa_table():
    """criteria section 10 / H24 table: value + (x Baseline), TTFT and TPOT as separate rows, stars in separate rows or next to the value."""
    c = final_cells()
    b = c[B]
    m = Q4["mean_over_scenarios"]
    sub = Q4["sub_stars"]
    rt = lambda cd, k: cd[k] / b[k]
    rows = ["| QA | 평가 metric | Baseline (T_ref) | C1 중앙 직렬화 | C2 분산 락 |", "|---|---|---:|---|---|"]
    rows.append(f"| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | {f0(b['qa1'])} (Baseline 별 {b['s1']}) | **{c[C1]['s1']}** {f0(c[C1]['qa1'])} ({xr(c[C1]['qa1_r'], 3)} ±{c[C1]['qa1_ci']:.3f}) [B+C] | **{c[C2]['s1']}** {f0(c[C2]['qa1'])} ({xr(c[C2]['qa1_r'], 3)} ±{c[C2]['qa1_ci']:.3f}) [B+C] |")
    def two(cd, a99, a50, fmt):
        return f"P99 {fmt(cd[a99])} ({xr(rt(cd, a99))}) · P50 {fmt(cd[a50])} ({xr(rt(cd, a50))}) [B+C]"
    rows.append(f"| **QA2 Latency — TTFT** (각 arm의 Max-goodput load) | TTFT (ms) ↓ | P99 {f0(b['t99'])} · P50 {f0(b['t50'])} | {two(c[C1], 't99', 't50', f0)} | {two(c[C2], 't99', 't50', f0)} |")
    rows.append(f"| **QA2 Latency — TTFT** (공통 load = Baseline peak load) | TTFT (ms) ↓ | P99 {f0(b['ct99'])} · P50 {f0(b['ct50'])} | {two(c[C1], 'ct99', 'ct50', f0)} | {two(c[C2], 'ct99', 'ct50', f0)} |")
    rows.append(f"| **QA2 Latency — TPOT** (각 arm의 Max-goodput load) | TPOT (ms) ↓ | P99 {f2(b['o99'])} · P50 {f2(b['o50'])} | {two(c[C1], 'o99', 'o50', f2)} | {two(c[C2], 'o99', 'o50', f2)} |")
    rows.append(f"| **QA2 Latency — TPOT** (공통 load) | TPOT (ms) ↓ | P99 {f2(b['co99'])} · P50 {f2(b['co50'])} | {two(c[C1], 'co99', 'co50', f2)} | {two(c[C2], 'co99', 'co50', f2)} |")
    rows.append(f"| QA2 별점 | 6쌍 중 최악 P99 (criteria §5: <=2 s & <=50 ms ★★★, <=4 s & <=100 ms ★★) | {b['s2']} (TTFT {f0(b['tw'])} · TPOT {f1(b['ow'])}) | **{c[C1]['s2']}** (TTFT {f0(c[C1]['tw'])} · TPOT {f1(c[C1]['ow'])}) [B+C] | **{c[C2]['s2']}** (TTFT {f0(c[C2]['tw'])} · TPOT {f1(c[C2]['ow'])}) [B+C] |")
    rows.append(f"| **QA3 Resource usage** | 클러스터 KV 상주 메모리 (GiB, 시간 평균, Baseline peak load) ↓ | {f1(b['res'])} (Baseline 별 {b['s3']}) | **{c[C1]['s3']}** {f1(c[C1]['res'])} ({xr(c[C1]['res'] / b['res'])}; 절감 배수 {xr(c[C1]['save'])}) [B+C] | **{c[C2]['s3']}** {f1(c[C2]['res'])} ({xr(c[C2]['res'] / b['res'])}; 절감 배수 {xr(c[C2]['save'])}) [B+C] |")
    rows.append(f"| **QA4 Modifiability** | 변경 module 수 · 공수(man-month) · 에이전트 비용($, frontier tier), 시나리오 4종 평균 ↓ | — | **{Q4_STARS[C1]}** {m['C1']['modules']:.2f} · {m['C1']['man_months']:.2f} · ${m['C1']['usd_T1']:.2f} (sub-star {sub['C1']['M1']}/{sub['C1']['M2']}/{sub['C1']['M3']}) [B+C] | **{Q4_STARS[C2]}** {m['C2']['modules']:.2f} · {m['C2']['man_months']:.2f} · ${m['C2']['usd_T1']:.2f} (sub-star {sub['C2']['M1']}/{sub['C2']['M2']}/{sub['C2']['M3']}) [B+C] |")
    o = selection()
    rows.append(f"| **별 합계** (QA1..QA4) | | — | **{o['totals'][C1]}** | **{o['totals'][C2]}** |")
    return "\n".join(rows)


def memory_config_table():
    """H24 memory configuration: capacity, host connection and PCIe/CXL generation, bandwidth, compute (TFLOPS) and supported ops."""
    sf = {s: sys_facts(s) for s in SYSIDS}
    h, b2 = sf["SYS-H100"], sf["SYS-B200"]
    pool_cap = cfgv("pool_capacity_bytes") / 2**40
    node_cxl = cfgv("cxl_adapters_per_node") * cfgv("cxl_adapter_bw_Bps") / 1e9
    rows = ["| 메모리 / 경로 | 용량 | host 연결 (세대) | 대역폭 | 연산 능력 (FP16) · 지원 연산 | 시뮬레이터 반영 |", "|---|---|---|---|---|---|",
            f"| HBM (노드의 GPU {h['gpus']}장 합) | H100 {h['hbm_gib']:,.0f} GiB ({h['hbm_med']}) / B200 {b2['hbm_gib']:,.0f} GiB ({b2['hbm_med']}) | GPU on-package (host CPU와는 {h['gen']['host_link']}) | H100 {h['hbm_bw']:.1f} / B200 {b2['hbm_bw']:.1f} TB/s (노드 합) | GPU FP16 dense {h['fp16']:,.0f} / {b2['fp16']:,.0f} TFLOPS/GPU, attention·FFN 실행 | decode step·prefill 시간(DP1 물리 재사용), 잔류량 집계. **용량 한계(OOM)는 미반영** |",
            f"| CXL 공유 풀 (후보 C1·C2의 KV 저장소) | {pool_cap:g} TiB | {h['gen']['cxl']} 스위치 풀, 노드당 어댑터 {cfgv('cxl_adapters_per_node')}개 x PCIe 5.0 x16 | 어댑터 {cfgv('cxl_adapter_bw_Bps') / 1e9:g} GB/s x {cfgv('cxl_adapters_per_node')} = 노드당 {node_cxl:g} GB/s (방향별), 풀 집계 {cfgv('pool_bw_Bps') / 1e12:g} TB/s, 유효 효율 η_cxl {cfgv('eta_cxl'):g} (ASSUMED) → 노드 유효 {node_cxl * cfgv('eta_cxl'):g} GB/s | 없음 (순수 저장소) · 지원 연산 없음 | 대역폭(η 포함), 접근 지연의 control plane 비용, 풀 점유율(퇴출 연산). 스위치 혼잡·bank 경합은 **미반영** |",
            f"| RDMA NIC (Baseline-RDMA의 KV 경로) | — (전송 버퍼만) | 노드당 4 x 200 Gbps | {cfgv('nic_bw_Bps') / 1e9:g} GB/s x η_rdma {cfgv('eta_rdma'):g} (ASSUMED) = {cfgv('nic_bw_Bps') * cfgv('eta_rdma') / 1e9:g} GB/s | 없음 · 지원 연산 없음 | 대역폭(η 포함), 중앙 인덱스 조회 {cfgv('index_lookup_us'):g} us. fragmentation 페널티는 의도적으로 **미반영**(강한 baseline) |",
            f"| host DRAM | — | {h['gen']['host_link']} | — | — | **사용하지 않음** (모든 arm에서 0) |",
            "| ScHBM, CXL-PNM, HBF, SSD-PIM (DP1 6종 메모리 중 나머지) | — | — | — | — | **DP4 평가 범위 밖**(profile에는 있으나 이 시뮬레이터는 쓰지 않음) |"]
    return "\n".join(rows)


def system_note():
    sf = {s: sys_facts(s) for s in SYSIDS}
    names = "; ".join(f"**{sid}** ({sf[sid]['gpu'].upper()}x{sf[sid]['gpus']}, {sf[sid]['gen']['gpu_hbm']}, {sf[sid]['gen']['host_link']}, {sf[sid]['gen']['cxl']})" for sid in SYSIDS)
    ft = fit_counts()
    n_pairs = {lab: len(RM[lab]["fit"]) for lab, _ in SETS}
    nv = ft["common_benchmark"]["comparison_valid"]
    return (f"**평가한 시스템:** {names}. 시스템당 P/D 분리 클러스터(CB 기본 P 1대 + D 1대, 노드 = GPU 8장), Llama-3.1-70B BF16(KV {kv_bytes_per_token():,} B/token), "
            f"두 시스템을 **통합**했다(통합 결과 하나, 시나리오 x 시스템 쌍이 단위). 별점의 집계 단위는 **Common Benchmark {nv}쌍**(CB-1~3 x 2시스템, 모두 comparison-valid; "
            f"사전 등록 규칙: 공통 별점은 Common set에서만 산출). DP4-specific는 {n_pairs['dp4_benchmark']}쌍(비교 가능 {ft['dp4_benchmark']['comparison_valid']}, 포화 {ft['dp4_benchmark']['saturated']}, 비교 불가 {ft['dp4_benchmark']['infeasible']})이며 diagnostic과 QA4 근거로만 쓴다. "
            f"값은 쌍별 값의 **기하평균**, 괄호는 **후보 ÷ Baseline 배수**(↑ 높을수록 좋음, ↓ 낮을수록 좋음), QA1의 ±는 seed 묶음 기하평균의 95% CI(t=2.776, 5 seeds)이다. Evidence [B+C]; QA4는 [B+C] proxy 구현.")


# --------------------------------------------------------------------------- tables for chapter 4
def per_pair_table(label):
    ps = (CBPS if label == "common_benchmark" else DPPS)
    lab = (CBLAB if label == "common_benchmark" else DPLAB)
    rows = ["| 시나리오 @ 시스템 | Fit | Baseline goodput ±CI (CV) | C1 goodput (ratio) | C2 goodput (ratio) | TTFT P99 ms B / C1 / C2 | TPOT P99 ms B / C1 / C2 | 판정 vs Baseline C1 / C2 |", "|---|---|---|---|---|---|---|---|"]
    for k in sorted(ps, key=lambda s: (s.split("@")[0], s.split("@")[1])):
        v = ps[k]
        t = lambda c, m: v[c][f"{m}_p99_ms"]
        fmtt = lambda x: f0(x) if x < 1e8 else "never"
        fmtp = lambda x: f2(x) if x < 1e8 else "never"
        vb = lab[k]["vs_baseline"]
        rows.append(f"| `{k}` | {FIT_LETTER[lab[k]['fit']]} | {f1(v[B]['max_goodput_tps'])} ±{f1(v[B]['goodput_ci95'])} ({v[B]['goodput_cv'] * 100:.1f}%) | "
                    f"{f1(v[C1]['max_goodput_tps'])} ({xr(v[C1]['max_goodput_tps'] / v[B]['max_goodput_tps'], 3)}) | {f1(v[C2]['max_goodput_tps'])} ({xr(v[C2]['max_goodput_tps'] / v[B]['max_goodput_tps'], 3)}) | "
                    f"{fmtt(t(B, 'ttft'))} / {fmtt(t(C1, 'ttft'))} / {fmtt(t(C2, 'ttft'))} | {fmtp(t(B, 'tpot'))} / {fmtp(t(C1, 'tpot'))} / {fmtp(t(C2, 'tpot'))} | "
                    f"{vb[C1]['verdict']} (g {vb[C1]['goodput']}, ttft {vb[C1]['ttft']}, tpot {vb[C1]['tpot']}) / {vb[C2]['verdict']} (g {vb[C2]['goodput']}, ttft {vb[C2]['ttft']}, tpot {vb[C2]['tpot']}) |")
    return "\n".join(rows)


def common_load_table():
    rows = ["| 시나리오 @ 시스템 | Baseline peak load | goodput B / C1 / C2 (tok/s, 그 load에서) | TTFT P99 ms B / C1 / C2 | KV 상주 GiB B / C1 / C2 | 각 arm의 own-peak load (B / C1 / C2) |", "|---|---:|---|---|---|---|"]
    for k in sorted(CBPS):
        v = CBPS[k]
        bp = {c: v[c]["at_base_peak"] for c in (B, C1, C2)}
        rows.append(f"| `{k}` | x{v['_base_peak_load']:g} | {f0(bp[B]['goodput_tps'])} / {f0(bp[C1]['goodput_tps'])} / {f0(bp[C2]['goodput_tps'])} | {f0(bp[B]['ttft_p99_ms'])} / {f0(bp[C1]['ttft_p99_ms'])} / {f0(bp[C2]['ttft_p99_ms'])} | "
                    f"{f1(bp[B]['kv_resident_gib'])} / {f1(bp[C1]['kv_resident_gib'])} / {f1(bp[C2]['kv_resident_gib'])} | x{v[B]['load']:g} / x{v[C1]['load']:g} / x{v[C2]['load']:g} |")
    return "\n".join(rows)


def combined_table():
    """Common + DP4-specific geometric means; second block without the failure rows (a stuck request is recorded as 1e9 ms and distorts a geometric mean)."""
    pairs_all = [(lab, k) for lab, ps in (("common_benchmark", CBPS), ("dp4_benchmark", DPPS)) for k in ps]
    pairs_nf = [(lab, k) for lab, k in pairs_all if "fail" not in k]
    def ps_of(lab):
        return CBPS if lab == "common_benchmark" else DPPS
    def g(pairs, c, f):
        return gm(f(ps_of(lab)[k][c]) for lab, k in pairs)
    rows = ["| 지표 (기하평균) | Baseline | C1 | C2 |", "|---|---:|---:|---:|"]
    for name, pairs in ((f"전체 {len(pairs_all)}쌍", pairs_all), (f"장애 행 제외 {len(pairs_nf)}쌍", pairs_nf)):
        gp = lambda x: x["max_goodput_tps"]
        tt = lambda x: x["at_base_peak"]["ttft_p99_ms"]
        kv = lambda x: x["at_base_peak"]["kv_resident_gib"]
        for lab_, f, fmt in ((f"Max SLO goodput (tok/s), {name}", gp, f0), (f"TTFT P99 공통 load (ms), {name}", tt, f0), (f"KV 상주 (GiB), {name}", kv, f1)):
            b_ = g(pairs, B, f)
            rows.append(f"| {lab_} | {fmt(b_)} | " + " | ".join(f"{fmt(g(pairs, c, f))} ({xr(g(pairs, c, f) / b_, 3 if f is gp else 2)})" for c in CANDS) + " |")
    return "\n".join(rows) + ("\n\nDP4-specific 행은 background 0이라 링크 압박이 없어 Common보다 Baseline에 가깝다. 전체 쌍의 TTFT 행은 장애 행에서 고착된 요청(기록값 1e9 ms)이 기하평균을 왜곡하므로 장애 행 제외 값을 함께 둔다. "
                              "C1과 C2의 차이는 장애 행에서만 온다. 별점은 Common 6쌍에서만 산출하므로 이 표는 H3(최종 결론은 두 benchmark 합산)을 위한 참고다.")


def per_system_table():
    rows = ["| 범위 | 쌍 수 | Baseline goodput (tok/s) | QA1 C1 (=C2) | QA2 별 (TTFT 최악 ms) C1 | QA3 절감 배수 C1 (=C2) | 승/무/패 C1 (44쌍 기준, 시스템별) |", "|---|---:|---:|---|---|---|---|"]
    for sid in SYSIDS + [MERGED]:
        d = R[sid]
        q = d["common_benchmark"]["qa_feasible"]
        t = d["combined"]["tally"][C1]
        rows.append(f"| {sid} | {q[B]['n_scenarios']} | {f0(q[B]['qa1_abs_goodput_geomean_tps'])} | **{q[C1]['qa1']}** {xr(q[C1]['qa1_ratio_geomean'], 3)} (C2 {xr(q[C2]['qa1_ratio_geomean'], 3)}) | "
                    f"**{q[C1]['qa2']}** ({f0(q[C1]['qa2_ttft_p99_worst_ms'])}) | **{q[C1]['qa3']}** {xr(q[C1]['qa3_saving_multiplier'])} (C2 {xr(q[C2]['qa3_saving_multiplier'])}) | "
                    f"{len(t['win'])}/{len(t['tie'])}/{len(t['loss'])} |")
    return "\n".join(rows)


def diag_table():
    q = CBQ
    rows = ["| 지표 (Common 6쌍 평균, Baseline peak load) | Baseline | C1 | C2 |", "|---|---:|---:|---:|"]
    g = lambda k: [q[c][k] for c in (B, C1, C2)]
    rows.append("| 링크 점유율 egress / ingress | " + " | ".join(f"{pct(q[c]['diag_link_util_egress'], 0)} / {pct(q[c]['diag_link_util_ingress'], 0)}" for c in (B, C1, C2)) + " |")
    rows.append("| 풀 점유율 | " + " | ".join(pct(x, 1) for x in g("diag_pool_util")) + " |")
    rows.append("| 서버 점유율 (C1 metadata server) | " + " | ".join(f"{x:.2e}" for x in g("diag_server_util")) + " |")
    rows.append("| 전역 락 점유율 최대 (C2) | " + " | ".join(f"{x:.2e}" for x in g("diag_global_lock_util_max")) + " |")
    rows.append("| 락 대기 P99 (ms) | " + " | ".join(f2(x) for x in g("diag_lock_wait_p99_ms")) + " |")
    rows.append("| coherence CPU core-equivalent | " + " | ".join(f2(x) for x in g("diag_cpu_core_eq")) + " |")
    rows.append("| KV 상주 구성 (GiB, P buffer / D HBM / 풀) | " + " | ".join(f"{f1(q[c]['qa3_components_gib_mean']['p_buffer'])} / {f1(q[c]['qa3_components_gib_mean']['d_hbm'])} / {f1(q[c]['qa3_components_gib_mean']['pool'])}" for c in (B, C1, C2)) + " |")
    return "\n".join(rows)


def cp_op_table():
    r = cp_ranges()
    rows = [f"| control-plane 연산 (DP4 행 {r['lookup']['n']}쌍의 Baseline-peak load 기준) | C1 P50 (us) | C2 P50 (us) | C2 ÷ C1 (P50) |", "|---|---|---|---|"]
    for kd in ("lookup", "publish", "pin", "unpin"):
        x = r[kd]
        rows.append(f"| {kd} | {f2(x['c1'][0])} ~ {f2(x['c1'][1])} | {f1(x['c2'][0])} ~ {f1(x['c2'][1])} | {f1(x['ratio'][0])} ~ {f1(x['ratio'][1])} |")
    return "\n".join(rows)


def headroom_table():
    rows = ["| 시나리오 @ 시스템 | 제공 request rate (req/s, 클러스터) | C1 포화 rate (req/s) | C2 포화 rate (req/s) | 여유 배수 C1 / C2 |", "|---|---:|---:|---:|---|"]
    cc = RM["dp4_benchmark"]["cp_capacity"]
    for sn in sorted(cc):
        off = DPPS[sn][C1]["offered_rps"]
        s1, s2 = cc[sn][C1]["saturation_rps"], cc[sn][C2]["saturation_rps"]
        rows.append(f"| `{sn}` | {f1(off)} | {f0(s1)} | {f0(s2)} | {f0(s1 / off)} / {f0(s2 / off)} |")
    return "\n".join(rows)


def scaling_table():
    se = RM["dp4_benchmark"]["scaling_efficiency"]
    rows = ["| 노드 수 N (P+D) | Baseline | C1 | C2 | Baseline H100 / B200 | C1 H100 / B200 |", "|---|---:|---:|---:|---|---|"]
    for n in ("4", "8", "16"):
        ps = lambda c: " / ".join(f3(se[c]["per_system"][s][n]) for s in SYSIDS)
        rows.append(f"| {n} ({int(n) // 2}+{int(n) // 2}) | {f3(se[B][n])} | {f3(se[C1][n])} | {f3(se[C2][n])} | {ps(B)} | {ps(C1)} |")
    return "\n".join(rows)


def failure_table():
    fl = RM["dp4_benchmark"]["failure"]
    rows = ["| 행 @ 시스템 | goodput ÷ Baseline C1 / C2 | SLO 위반 증가 (요청) B / C1 / C2 | 미완료(고착) 요청 C1 / C2 | 가용성 창 (s) C1 / C2 | 고착 stripe C2 | TTFT P99 (ms, 장애 포함) B / C1 / C2 |", "|---|---|---|---|---|---|---|"]
    for k in fail_rows():
        v = fl[k]
        w = lambda x: "∞" if x == float("inf") else f1(x)
        tt = lambda x: "never" if x >= 1e8 else f0(x)
        rows.append(f"| `{k}` | {xr(goodput_ratio('dp4_benchmark', k, C1), 3)} / {xr(goodput_ratio('dp4_benchmark', k, C2), 3)} | "
                    f"{f0(v[B]['slo_viol_excess'])} / {f0(v[C1]['slo_viol_excess'])} / {f0(v[C2]['slo_viol_excess'])} | {f0(v[C1]['n_incomplete_stuck'])} / {f0(v[C2]['n_incomplete_stuck'])} | "
                    f"{w(v[C1]['window_s'])} / {w(v[C2]['window_s'])} | {f0(v[C2]['stuck_stripes'])} | {tt(v[B]['ttft_p99_ms_with'])} / {tt(v[C1]['ttft_p99_ms_with'])} / {tt(v[C2]['ttft_p99_ms_with'])} |")
    return "\n".join(rows)


def iteration_rows():
    pq, nq = PRE["common_benchmark"]["qa_feasible"], CBQ
    tp, tn = tally_counts(C1, PRE), tally_counts(C1)
    ttft_w = lambda q: q[C1]["tail_check_common_load"]["ttft"]
    pre_sys = {s: PRE_SYS[s]["common_benchmark"]["qa_feasible"][C1]["qa1_ratio_geomean"] for s in SYSIDS}
    new_sys = {s: R[s]["common_benchmark"]["qa_feasible"][C1]["qa1_ratio_geomean"] for s in SYSIDS}
    pbe = PRE_SENS["break_even"][MERGED][C1]["bg0.85"]
    nbe = SENS["break_even"][MERGED][C1]["bg0.85"]
    return [
        ("0 (initial, git 0e44b58)", "—", "변경 없음. 기준 실행", f"**Trigger 발동.** Common QA1 C1=C2 {xr(pq[C1]['qa1_ratio_geomean'], 3)} (H100 {xr(pre_sys['SYS-H100'], 3)}, B200 {xr(pre_sys['SYS-B200'], 3)}), "
         f"QA3 절감 {xr(pq[C1]['qa3_saving_multiplier'], 3)}, TTFT P99 악화 쌍 {ttft_w(pq)['n_worse']}/{ttft_w(pq)['n_pairs']}(최악 {xr(ttft_w(pq)['worst_ratio'], 1)}), 승/무/패 {tp[0]}/{tp[1]}/{tp[2]}"),
        ("1", "S (진단, main 불변)", "η_cxl {0.5, 0.7, 0.85, 1.0} x 배경 부하 {0, 0.5, 0.85} 12셀 + η_rdma, overlap, bg ±0.1, control-plane 파라미터(S, probe, cs, threads, batch, metadata cost), 별 경계 ±10% 민감도. main 값은 바꾸지 않음",
         f"격차는 data plane 효율 가정에서 옴. 당시 모델의 break-even η_cxl* (QA1 parity, bg 0.85) = {pbe['qa1_ratio_parity']['x']:.3f}. C1/C2는 모든 셀에서 QA1~QA3 동일(loop-log 기록: 차이 <= 0.03%). 모델 결함 1건(read가 write와 겹침) 확인 -> Iteration 2"),
        ("2", "M", "후보 move path를 write(prefill과만 겹침) -> publish -> pin -> read -> decode의 순차로 수정 (read는 publish 이후에만 시작). Baseline 경로·모든 파라미터 불변. 수정 전 결과는 `results/data/pre_serial_read/`에 보존",
         f"QA1 {xr(pq[C1]['qa1_ratio_geomean'], 3)} -> **{xr(nq[C1]['qa1_ratio_geomean'], 3)}** (H100 {xr(pre_sys['SYS-H100'], 3)} -> {xr(new_sys['SYS-H100'], 3)}, B200 {xr(pre_sys['SYS-B200'], 3)} -> {xr(new_sys['SYS-B200'], 3)}); "
         f"QA3 절감 {xr(pq[C1]['qa3_saving_multiplier'], 3)} -> {xr(nq[C1]['qa3_saving_multiplier'], 3)}; TTFT P99 악화 쌍 {ttft_w(pq)['n_worse']}/6 -> {ttft_w(nq)['n_worse']}/6 (최악 {xr(ttft_w(pq)['worst_ratio'], 1)} -> {xr(ttft_w(nq)['worst_ratio'], 1)}); 승/무/패 {tp[0]}/{tp[1]}/{tp[2]} -> {tn[0]}/{tn[1]}/{tn[2]}; "
         f"break-even η_cxl* {pbe['qa1_ratio_parity']['x']:.3f} -> {nbe['qa1_ratio_parity']['x']:.3f}. 판정: 후보는 Baseline 미만 -> **사전 등록 규칙에 따라 중단**, 추가 iteration으로 파라미터를 조정하지 않음"),
    ]


def ablation_table():
    names = [B, C1, "C1-no-batch", C2, "C2-no-scan"]
    cb = ABL["common_benchmark"]["qa_feasible"]
    dp = ABL["dp4_benchmark"]["qa_feasible"]
    rows = ["| arm | Common QA1 (ratio) | Common QA3 절감 | Common TTFT P99 공통 load (ms) | DP4 38쌍 QA1 ratio | 별 합계 (QA1~3, Common) |", "|---|---|---|---|---|---|"]
    for c in names:
        s = sum(nstar(cb[c][k]) for k in ("qa1", "qa2", "qa3"))
        rows.append(f"| {c} | {cb[c]['qa1']} {xr(cb[c]['qa1_ratio_geomean'], 4)} | {xr(cb[c]['qa3_saving_multiplier'], 4)} | {f0(cb[c]['qa2_common_ttft_p99_ms_geomean'])} | {xr(dp[c]['qa1_ratio_geomean'], 4)} | {s} |")
    return "\n".join(rows)


def ablation_effect():
    """max relative goodput difference of each ablated arm vs its full arm over all pairs; control-plane latency effect on one row."""
    out = {}
    for abl, full in (("C1-no-batch", C1), ("C2-no-scan", C2)):
        d = 0.0
        for lab, _ in SETS:
            for k, v in ABL[lab]["per_scenario"].items():
                d = max(d, abs(v[abl]["max_goodput_tps"] / v[full]["max_goodput_tps"] - 1))
        out[abl] = d
    row = "d4_hot_prefix_fanout@B200"
    v = ABL["dp4_benchmark"]["per_scenario"][row]
    out["lat"] = dict(row=row,
                      c2_pin=v[C2]["at_base_peak"]["cp_lat"]["pin"]["p50_us"], c2n_pin=v["C2-no-scan"]["at_base_peak"]["cp_lat"]["pin"]["p50_us"],
                      c1_pub=v[C1]["at_base_peak"]["cp_lat"]["publish"]["p50_us"], c1n_pub=v["C1-no-batch"]["at_base_peak"]["cp_lat"]["publish"]["p50_us"],
                      c1_look=v[C1]["at_base_peak"]["cp_lat"]["lookup"]["p50_us"], c1n_look=v["C1-no-batch"]["at_base_peak"]["cp_lat"]["lookup"]["p50_us"])
    return out


def star_basis_table():
    rows = ["| 시스템 | Baseline끼리 QA1 잡음 (겹치지 않는 seed 묶음 4개, 쌍 6개) 최대 편차 / 평균 편차 | 하한 0.90 ÷ 잡음 (여유 배수) | QA3 절감 배수 잡음 최대 편차 | QA3 하한 0.95 대비 |", "|---|---|---|---|---|"]
    for sid in SYSIDS:
        s = SB[sid]
        rows.append(f"| {sid} | {pct(s['qa1_noise_max_dev'])} / {pct(s['qa1_noise_mean_dev'])} | {s['lower_margin_over_noise']:.1f} | {pct(s['qa3_noise_max_dev'])} (평균 {pct(s['qa3_noise_mean_dev'])}) | "
                    f"{'잡음이 경계(5%)보다 큼' if s['qa3_noise_max_dev'] > 0.05 else '잡음이 경계보다 작음'} |")
    return "\n".join(rows)


def eta_grid_tables():
    out = []
    cfgs = SENS["configs"]["eta_cxl_bg"]
    for title, key, fmt in (("QA1 geomean ratio (>= 1.00이면 Baseline 도달; C1 = C2)", "qa1_ratio", f3), ("QA3 절감 배수 (Baseline peak load; >= 1.00이면 도달)", "qa3_multiplier", f3)):
        rows = [f"**{title}** (통합, 12셀; η_cxl x 배경 부하 상한)", "", "| η_cxl \\ bg | 0.0 | 0.5 | 0.85 |", "|---|---|---|---|"]
        for e in (0.5, 0.7, 0.85, 1.0):
            cells = []
            for b_ in (0.0, 0.5, 0.85):
                x = cfgs[f"eta{e}_bg{b_}"][MERGED]["candidates"]
                cells.append(f"{fmt(x[C1][key])} / {fmt(x[C2][key])}")
            rows.append(f"| {e:g} | " + " | ".join(cells) + " |")
        out.append("\n".join(rows))
    rows = ["**TTFT P99 악화 쌍 수 (공통 load, 6쌍 중) C1 / C2**", "", "| η_cxl \\ bg | 0.0 | 0.5 | 0.85 |", "|---|---|---|---|"]
    for e in (0.5, 0.7, 0.85, 1.0):
        cells = []
        for b_ in (0.0, 0.5, 0.85):
            x = cfgs[f"eta{e}_bg{b_}"][MERGED]["candidates"]
            cells.append(f"{x[C1]['tail_ttft_worse_common']} / {x[C2]['tail_ttft_worse_common']}")
        rows.append(f"| {e:g} | " + " | ".join(cells) + " |")
    out.append("\n".join(rows))
    return "\n\n".join(out)


def break_even_table():
    rows = ["| 범위 | 기준 | bg 0.0 | bg 0.5 | bg 0.85 (main 배경) |", "|---|---|---|---|---|"]
    lab = {"qa1_ratio_parity": "QA1 ratio >= 0.99 (parity, 1% tie 기준)", "qa1_ratio_ge_1": "QA1 ratio >= 1.00", "qa3_multiplier_parity": "QA3 절감 배수 >= 0.99"}
    for sid in (MERGED, "SYS-H100", "SYS-B200"):
        for k, name in lab.items():
            cells = []
            for bg in ("bg0.0", "bg0.5", "bg0.85"):
                v = SENS["break_even"][sid][C1][bg][k]
                cells.append(f"η_cxl* {v['x']:.3f}" if v["status"] == "interpolated" else ("η 0.5(격자 최소)에서 이미 충족" if v["status"] == "met_at_lowest" else f"격자 내 없음 (최고 {v['best']:.3f} @ η {v['at']:g})"))
            rows.append(f"| {sid} | {name} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def one_param_table():
    rows = ["| 변경 | 값 | QA1 ratio C1 / C2 | QA3 절감 C1 / C2 | TTFT P99 악화 쌍 (공통 load) |", "|---|---|---|---|---|"]
    for grp, by_c in SENS["one_param_sweeps"].items():
        for val, x in by_c[C1].items():
            y = by_c[C2][val]
            rows.append(f"| {grp} | {val} | {f3(x['qa1_ratio'])} / {f3(y['qa1_ratio'])} | {f3(x['qa3_multiplier'])} / {f3(y['qa3_multiplier'])} | {x['ttft_worse_common']} / {y['ttft_worse_common']} |")
    return "\n".join(rows)


def cp_sweep_table():
    """control-plane parameter sweeps: only available for the superseded model (Iteration 2 did not re-run them, loop-log)."""
    rows = ["| 파라미터 | 값 | Common QA1 ratio C1 / C2 | Common QA3 절감 C1 / C2 |", "|---|---|---|---|"]
    for grp in ("lock_stripes", "probe_us", "cs_per_request", "meta_cost_us", "rpc_hash_batch", "server_threads"):
        for val, x in PRE_SENS["one_param_sweeps"][grp][C1].items():
            y = PRE_SENS["one_param_sweeps"][grp][C2][val]
            rows.append(f"| {grp} | {val} | {f3(x['qa1_ratio'])} / {f3(y['qa1_ratio'])} | {f3(x['qa3_multiplier'])} / {f3(y['qa3_multiplier'])} |")
    return "\n".join(rows)


def star_boundary_table():
    sb = SENS["star_boundary_pm10"][MERGED]
    rows = ["| 경계 배율 (모든 QA1~QA3 경계에 동시 적용) | Baseline (QA1/QA2/QA3, 합) | C1 | C2 |", "|---|---|---|---|"]
    for s in ("0.9", "1.0", "1.1"):
        f = lambda c: f"{sb[s][c]['qa1']}/{sb[s][c]['qa2']}/{sb[s][c]['qa3']} (합 {sb[s][c]['total']})"
        rows.append(f"| x{s} | {f(B)} | {f(C1)} | {f(C2)} |")
    return "\n".join(rows)


def qa4_scenario_table():
    rows = ["| 변경 시나리오 | C1 module (shared) · LOC · module 크기 · 공수 MM · 비용 $ (T1) | C2 module (shared) · LOC · module 크기 · 공수 MM · 비용 $ (T1) |", "|---|---|---|"]
    for k, v in Q4["scenarios"].items():
        f = lambda c: f"{c['modules']} ({c['shared_modules']}) · {c['loc_added']} · {c['module_size_loc']} · {c['man_months']:.3f} · ${c['agent']['T1_frontier']['usd']:.2f}"
        rows.append(f"| {k}: {v['title']} | {f(v['C1'])} | {f(v['C2'])} |")
    m = Q4["mean_over_scenarios"]
    rows.append(f"| **평균 (별 판정 기준)** | **{m['C1']['modules']:.2f} · {m['C1']['man_months']:.3f} MM · ${m['C1']['usd_T1']:.2f}** | **{m['C2']['modules']:.2f} · {m['C2']['man_months']:.3f} MM · ${m['C2']['usd_T1']:.2f}** |")
    return "\n".join(rows)


def qa4_boundary_lines():
    mu = Q4["mean_over_scenarios_unrounded"]
    d1, d2 = mu["C1"]["man_months"], mu["C2"]["man_months"]
    return dict(c1=d1, c2=d2, c1_margin=(0.5 - d1) / 0.5, c2_margin=(d2 - 0.5) / 0.5, m1=mu["C1"]["modules"], m1_margin=(mu["C1"]["modules"] - 2) / 2)


def pc_table(n):
    d = PC[n]
    rows = ["| 변종 | 종류 | 기대 위반 | 탐색 (상태 수, 전수 여부) | I1 가시성 | I2 use-after-free | I3 상호 배제 | I4 stale index | 반례 최단 길이 |", "|---|---|---|---|---|---|---|---|---|"]
    sym = {"pass": "통과(전수)", "no_violation_found_exploration_capped": "반례 없음(상한 도달, 불완전)", "violated": "**위반**"}
    for r in d["results"]:
        inv = r["invariants"]
        cx = [f"{k}:{v['cex_length']}" for k, v in inv.items() if v["result"] == "violated"]
        rows.append(f"| {r['variant']} | {r['kind']} | {', '.join(r['expected_violations']) or '—'} | {r['states']:,} ({'전수' if r['complete'] else '**상한 도달**'}) | "
                    + " | ".join(sym[inv[k]["result"]] for k in ("I1", "I2", "I3", "I4")) + f" | {', '.join(cx) or '—'} |")
    return "\n".join(rows)


def pc_facts():
    r2 = {r["variant"]: r for r in PC[2]["results"]}
    r3 = {r["variant"]: r for r in PC[3]["results"]}
    viol = lambda r: [k for k, v in r["invariants"].items() if v["result"] == "violated"]
    capped2 = [k for k, r in r2.items() if r["capped"]]
    exp_hit2 = {k: set(r["expected_violations"]) <= set(viol(r)) for k, r in r2.items() if r["kind"] == "defect"}
    detected3 = [k for k, r in r3.items() if r["kind"] == "defect" and viol(r)]
    return dict(r2=r2, r3=r3, viol=viol, capped2=capped2, exp_hit2=exp_hit2, detected3=detected3, cap=PC[2]["params"]["max_states"],
                defects=[k for k, r in r2.items() if r["kind"] == "defect"])


# --------------------------------------------------------------------------- pre-registered predictions (simulation-plan section 10)
def cc_sat(k, c=None):
    return RM["dp4_benchmark"]["cp_capacity"][k][c or C2]["saturation_rps"]


def predictions():
    q, dpd = agg_dev_c1_c2()
    ft = fit_counts()
    hr = headroom()
    cr = cp_ranges()
    fl = RM["dp4_benchmark"]["failure"]
    nodeloss = {k: goodput_ratio("dp4_benchmark", k, C1) for k in fail_rows() if "node_loss" in k}
    lh = {k: (goodput_ratio("dp4_benchmark", k, C2), fl[k][C2]["n_incomplete_stuck"], fl[k][C2]["stuck_stripes"]) for k in fail_rows() if "as_published" in k}
    lease = {k: goodput_ratio("dp4_benchmark", k, C2) for k in fail_rows() if "[lease]" in k}
    restart = {k: goodput_ratio("dp4_benchmark", k, C1) for k in fail_rows() if "restart" in k}
    agent_full = {k: goodput_ratio("dp4_benchmark", k, C1) for k in DPPS if k.startswith("d4_agent_multiturn")}
    sat_c2 = {k: v[C2]["saturation_rps"] for k, v in RM["dp4_benchmark"]["cp_capacity"].items()}
    sat_c1 = {k: v[C1]["saturation_rps"] for k, v in RM["dp4_benchmark"]["cp_capacity"].items()}
    # control-plane time share of TTFT on one representative row
    k = "d4_hot_prefix_fanout@H100"
    v = DPPS[k]
    cp = {c: sum(v[c]["at_base_peak"]["cp_lat"][o]["p50_us"] for o in ("lookup", "publish", "pin", "unpin")) for c in CANDS}
    share = {c: cp[c] * 1e-3 / v[c]["at_base_peak"]["ttft_p50_ms"] for c in CANDS}
    rows = []
    rows.append(("1. control plane 지연은 µs 규모, KV 이동·prefill은 수십~수백 ms라 C1과 C2의 QA1·QA2 차이는 노이즈 수준일 것",
                 "**성립 (단, 'saturated 라벨'은 아님)**",
                 f"C1 대비 C2 차이: Common QA1 {pct(q['qa1_abs_goodput_geomean_tps'], 3)}, 공통 load TTFT P99 {pct(q['qa2_common_ttft_p99_ms_geomean'], 3)}, QA3 {pct(q['qa3_kv_resident_gib_geomean'], 3)}; 장애 행을 뺀 DP4 쌍의 goodput 차이 최대 {pct(dpd, 3)}. "
                 f"연산당 control plane P50은 C1 {f1(min(x['c1'][0] for x in cr.values()))}~{f1(max(x['c1'][1] for x in cr.values()))} µs, C2 {f1(min(x['c2'][0] for x in cr.values()))}~{f1(max(x['c2'][1] for x in cr.values()))} µs이고 "
                 f"`{k}`에서 요청 하나의 4연산 합은 C1 {f1(cp[C1])} µs, C2 {f1(cp[C2])} µs로 TTFT P50의 {pct(share[C1], 3)} / {pct(share[C2], 3)}. "
                 f"**그러나** 계획 §6.2는 대부분이 saturated일 것이라 예상했는데 실제 fit 라벨은 DP4 {sum(ft['dp4_benchmark'].values())}쌍 중 comparison-valid {ft['dp4_benchmark']['comparison_valid']}, saturated {ft['dp4_benchmark']['saturated']}이다. "
                 "saturated는 모든 arm(Baseline 포함)이 같을 때만 붙는데 Baseline과 후보의 data plane 차이가 있어 C1≈C2여도 comparison-valid가 된다(Iteration 2 이후 read가 TTFT에 노출되어 6쌍 -> 37쌍으로 바뀜). 예측의 '후보 간 차이 없음'은 맞고 '라벨'은 틀렸다"))
    nodes = row_nodes()
    per_node = {k: DPPS[k][C1]["offered_rps"] / nodes[k.split("@")[0]] for k in DPPS}
    kmax = max(per_node, key=per_node.get)
    hrc = hr[0]
    c2sat_node = {k: cc_[C2]["saturation_rps"] / nodes[k.split("@")[0]] for k, cc_ in RM["dp4_benchmark"]["cp_capacity"].items()}
    k512 = "d4_lock_stripes_512@H100"
    rows.append(("2. 차이는 control plane 연산률이 지배하는 영역(작은 prompt, 작은 block, 높은 rate, 많은 노드)에서만 나타나고, 현실적 rate(노드당 수십 req/s)에서는 두 구조 모두 포화하지 않을 것",
                 "**부분 성립**",
                 f"제공 rate는 클러스터 최대 {f1(max(DPPS[k][C1]['offered_rps'] for k in DPPS))} req/s, 노드당 최대 {f1(per_node[kmax])} req/s(`{kmax.split('@')[0]}`, 노드 {nodes[kmax.split('@')[0]]}개)이고 이 범위에서 두 구조 모두 포화하지 않았다(포화 rate ÷ 제공 rate 최소 {f0(hrc[0])}배: {hrc[2].split('-')[0]} `{hrc[1]}`, 포화 {f0(hrc[3])} req/s ÷ 제공 {f1(hrc[4])} req/s). "
                 f"작은 prompt·작은 block·16노드 행에서도 C1≈C2(위 1.)라 '그 영역에서 차이가 나타난다'는 부분은 **확인되지 않았다**. 다만 C2는 S x N에 따라 포화 rate가 줄어(아래 3.) `{k512.split('@')[0]}`(노드 {nodes[k512.split('@')[0]]}개)의 C2 포화 rate {f0(cc_sat(k512))} req/s는 노드당 {f0(c2sat_node[k512])} req/s에 해당해, 계획이 말한 '노드당 수십 req/s'를 이 구성에 가하면 포화 영역에 들어간다(산술 환산이며 시뮬레이션하지 않은 외삽)"))
    rows.append(("3. C2는 락 매니저 scan 비용(S x N x t_probe)과 hot 락 경합에서 갈리고, C1은 서버 단일 큐 포화와 SPOF에서 갈릴 것",
                 "**성립 (포화 rate와 장애에서 확인, QA에는 안 드러남)**",
                 f"C2 포화 rate는 stripe {sorted({1, 8, 64, 512})[0]}/8/(64)/512에서 {f0(sat_c2['d4_lock_stripes_1@H100'])}/{f0(sat_c2['d4_lock_stripes_8@H100'])}/{f0(sat_c2['d4_server_threads_2@H100'])}/{f0(sat_c2['d4_lock_stripes_512@H100'])} req/s, 노드 수 4/8/16에서 {f0(sat_c2['d4_node_scale_n4@H100'])}/{f0(sat_c2['d4_node_scale_n8@H100'])}/{f0(sat_c2['d4_node_scale_n16@H100'])} req/s로 S x N이 커질수록 낮아진다. "
                 f"C1 포화 rate는 서버 스레드 1/2/4에서 {f0(sat_c1['d4_lock_stripes_1@H100'])}/{f0(sat_c1['d4_server_threads_2@H100'])}/{f0(sat_c1['d4_server_threads_4@H100'])} req/s. "
                 f"SPOF: 서버 프로세스 재시작(0.5 s, 인덱스 보존)은 영향이 없고({', '.join(xr(x, 3) for x in restart.values())}) 노드 손실(인덱스 재구성 30 s)은 Baseline 대비 goodput {bysys(nodeloss, lambda v: xr(v, 3))}. "
                 f"C2 락 보유 노드 장애(as-published)는 stripe가 풀리지 않아 요청 {', '.join(f0(v[1]) for v in lh.values())}건 고착, 가용성 창 ∞, goodput {', '.join(xr(v[0], 3) for v in lh.values())}; lease 1 s 보완안은 {', '.join(xr(x, 3) for x in lease.values())}. "
                 f"hot 락 경합은 락 대기 P99 {f2(DPPS['d4_hot_prefix_fanout@H100'][C2]['at_base_peak']['lock_wait_p99_ms'])} ms로 존재하나 goodput에는 보이지 않는다"))
    rows.append(("4. Baseline-RDMA 대비 후보의 이득은 data plane 상수(η_cxl, η_rdma, 중첩 비율)가 지배하고 두 후보가 같으므로 선택 근거가 못 된다. 이득 주장은 reuse 시나리오와 민감도로 한정",
                 "**부분 성립 (data plane 지배는 성립, reuse 이득은 확정 못 함)**",
                 f"Common QA1 격차는 두 후보에서 같고(위 1.) η_cxl 격자에서 {xr(SENS['configs']['eta_cxl_bg']['eta0.5_bg0.85'][MERGED]['candidates'][C1]['qa1_ratio'], 3)} -> {xr(SENS['configs']['eta_cxl_bg']['eta1.0_bg0.85'][MERGED]['candidates'][C1]['qa1_ratio'], 3)}로 움직인다(break-even η_cxl* {SENS['break_even'][MERGED][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f}). overlap 0.5/0.9는 거의 영향 없음, η_rdma 0.6/0.95에서 {xr(SENS['one_param_sweeps']['eta_rdma'][C1]['eta_rdma0.6']['qa1_ratio'], 3)}/{xr(SENS['one_param_sweeps']['eta_rdma'][C1]['eta_rdma0.95']['qa1_ratio'], 3)}. "
                 f"reuse 시나리오 `d4_agent_multiturn`의 goodput 비는 {bysys(agent_full, lambda v: xr(v, 3))}로 H100에서는 높고 B200에서는 낮다. H100의 이득은 Baseline seed 일부의 붕괴에서 오며 goodput 판정은 tie라(5.2) '이득이 reuse에 있다'는 예측도 통계적으로 확정되지 않았고 시스템에 의존한다"))
    rows.append(("5. 실질적 trade-off는 QA1/QA2가 아니라 QA4, 확장 한계, 장애·정확성에 있고, 확인되면 '정합성 구조는 성능 레버가 아니다'가 결론",
                 "**성립 (QA4 차이는 경계 근처)**",
                 f"QA1~QA3은 C1=C2(별 같음). 별이 갈리는 곳은 QA4뿐이며 C1 {Q4_STARS[C1]} (MM {Q4['mean_over_scenarios']['C1']['man_months']:.3f}) 대 C2 {Q4_STARS[C2]} ({Q4['mean_over_scenarios']['C2']['man_months']:.3f}), 경계 0.5 MM와의 거리 C1 {pct(qa4_boundary_lines()['c1_margin'])}(아래) / C2 {pct(qa4_boundary_lines()['c2_margin'])}(위). "
                 "장애 특성(C1 SPOF 노드 손실, C2 락 고착)과 model check(C1 vs C2)는 별점 밖에서 갈린다. 결론은 '성능 레버가 아니다'로 확인되며, QA1~QA3의 Baseline 격차는 후보가 아니라 data plane에서 온다"))
    return rows


# --------------------------------------------------------------------------- document sections
def sec0():
    o = selection()
    c = final_cells()
    ft = fit_counts()
    ln = link_numbers()
    pf = prefill_ms()
    q, dpd = agg_dev_c1_c2()
    cr = cp_ranges()
    hr = headroom()
    be = SENS["break_even"][MERGED][C1]["bg0.85"]
    bel = SENS["break_even"]
    ql = qa4_boundary_lines()
    dt, kept, tied = decision_table()
    nvar = len(dt)
    tp = {cc: tally_counts(cc) for cc in CANDS}
    fl = RM["dp4_benchmark"]["failure"]
    nodeloss = {k: goodput_ratio("dp4_benchmark", k, C1) for k in fail_rows() if "node_loss" in k}
    nodeloss_c2 = {k: goodput_ratio("dp4_benchmark", k, C2) for k in fail_rows() if "node_loss" in k}
    lh = {k: (fl[k][C2]["n_incomplete_stuck"], goodput_ratio("dp4_benchmark", k, C2)) for k in fail_rows() if "as_published" in k}
    lease = {k: goodput_ratio("dp4_benchmark", k, C2) for k in fail_rows() if "[lease]" in k}
    se = RM["dp4_benchmark"]["scaling_efficiency"]
    cc = RM["dp4_benchmark"]["cp_capacity"]
    pcf = pc_facts()
    agent = {k.split("@")[1]: goodput_ratio("dp4_benchmark", k, C1) for k in DPPS if k.startswith("d4_agent_multiturn")}
    wp = win_pairs()
    ag = "d4_agent_multiturn@H100"
    ag_b, ag_c = seed_list(ag, B), seed_list(ag, C1)
    seeds_s = lambda xs: "/".join(f0(x) for x in xs)
    ratio_txt = ", ".join(kd + " " + f1(cr[kd]["ratio"][0]) + "~" + f0(cr[kd]["ratio"][1]) + "배" for kd in cr)
    sw = SENS["star_boundary_pm10"][MERGED]
    pr_rev = o["reversed_winner"]
    L = []
    L.append("# 0. 최종 요약\n")
    L.append("> 발표용 요약이다. H100과 B200 두 세대를 **하나로 통합**했고(시나리오 x 시스템 쌍이 단위), 별점은 사전 등록된 공통 기준(`qa-evaluation-criteria.md`, Common Benchmark 6쌍)이다. 근거 표는 4장, 분석은 5장, 한계는 6장. "
             "**이 DP의 선택 질문은 'CXL 풀을 쓸 것인가'가 아니라 'CXL 풀 위에서 메타데이터 일관성의 책임을 누가 지는가(C1 중앙 직렬화 vs C2 분산 락, control plane 책임)'이다.** "
             "C1과 C2의 별점 차이는 QA4에서만 나오며 0.5 man-month 경계 근처이고, 두 후보가 Baseline-RDMA보다 낮은 QA1~QA3의 격차는 일관성 구조가 아니라 **data plane 상수**에서 온다.\n")
    L.append("## 0.1 QA별 비교\n")
    L.append(final_qa_table() + "\n")
    L.append(system_note() + "\n")
    L.append("**메모리 구성** (H24: 용량 · host 연결과 세대 · 대역폭 · 연산 능력과 지원 연산 · 시뮬레이터 반영 여부):\n")
    L.append(memory_config_table() + "\n")
    L.append("Baseline = Baseline-RDMA(CXL 풀 없음, P→D RDMA 점대점 + 중앙 인덱스, 노드 간 prefix 공유 없음). 별 경계는 결과를 본 뒤 바꾸지 않았다. 'Baseline 별'은 같은 기준을 Baseline에 적용한 참고값이다. "
             "QA2의 두 행(각 arm의 own-peak load / 공통 load)은 **서로 다른 질문**이다: 후보는 Baseline보다 낮은 load에서 goodput peak를 갖기 때문에 own-peak 값만 보면 후보 TTFT가 더 좋아 보이지만, 같은 offered load(Baseline의 peak)에서는 후보가 크게 나쁘다(위 두 행).\n")
    # 0.2
    L.append("## 0.2 Trade-off와 그 이유\n")
    L.append(f"**두 후보는 QA1~QA3에서 값이 사실상 같고(차이 {pct(max(q.values()), 3)} 이하), 둘 다 Baseline-RDMA보다 낮다. 별이 갈리는 곳은 QA4뿐이다. 성능 쪽 격차는 data plane(CXL 풀 경로 대 RDMA 경로)에서 오고, control plane 책임(C1 대 C2)에서 오지 않는다.**\n")
    L.append(f"- **왜 Baseline보다 낮은가 (QA1 {xr(c[C1]['qa1_r'], 3)}, QA3 절감 {xr(c[C1]['save'])}, 공통 load TTFT P99 {xr(c[C1]['ct99'] / c[B]['ct99'])}).** 8K 요청 하나의 KV는 {ln['kv_gib']:.2f} GiB다. Common 압박(background {ln['bg']:g})에서 Baseline은 RDMA 유효 {ln['nic']:g} GB/s로 한 번 보내 링크 시간 {f0(ln['t_rdma_ms'])} ms이고, 후보는 풀에 쓴 뒤(P egress) publish·pin 이후 다시 읽어야 하므로(D ingress, Iteration 2에서 순차로 수정) 노드 CXL 유효 {ln['cxl']:g} GB/s로 쓰기 {f0(ln['t_cxl_ms'])} ms + 읽기 {f0(ln['t_cxl_ms'])} ms가 든다(config 상수로 계산한 어림값, 시뮬레이터 출력 아님). "
             f"prefill은 H100 {f0(pf['SYS-H100'])} ms, B200 {f0(pf['SYS-B200'])} ms라 B200에서는 링크가 병목이 되어 격차가 크다(QA1: H100 {xr(R['SYS-H100']['common_benchmark']['qa_feasible'][C1]['qa1_ratio_geomean'], 3)}, B200 {xr(R['SYS-B200']['common_benchmark']['qa_feasible'][C1]['qa1_ratio_geomean'], 3)}). "
             f"QA3는 같은 offered load(Baseline peak)에서 후보가 이미 포화해 P 노드 전송 버퍼에 요청이 쌓이는 효과다(P buffer 평균 {f1(c[C1]['comp']['p_buffer'])} GiB 대 Baseline {f1(c[B]['comp']['p_buffer'])} GiB). "
             f"이 격차는 η_cxl(ASSUMED 0.5)과 η_rdma(ASSUMED 0.85)에 좌우되며 break-even η_cxl*는 QA1 parity {be['qa1_ratio_parity']['x']:.3f}(H100 {bel['SYS-H100'][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f}, B200 {bel['SYS-B200'][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f}), QA3 절감 {bel[MERGED][C1]['bg0.85']['qa3_multiplier_parity']['x']:.3f}이다(**ASSUMED 대 ASSUMED 비교**, 둘 다 C1=C2).")
    L.append(f"- **C1과 C2는 왜 같은 값이 나오는가.** control plane은 연산당 µs 규모다(C1 P50 {f1(min(x['c1'][0] for x in cr.values()))}~{f1(max(x['c1'][1] for x in cr.values()))} µs, C2 {f1(min(x['c2'][0] for x in cr.values()))}~{f0(max(x['c2'][1] for x in cr.values()))} µs; 연산별 C2 ÷ C1 P50은 {ratio_txt}). "
             f"그러나 요청 하나의 TTFT는 수백~수천 ms이고 KV 이동·prefill이 지배한다. 두 후보의 Common QA 차이는 {pct(max(q.values()), 3)} 이하, 장애 행을 뺀 DP4 쌍의 goodput 차이는 최대 {pct(dpd, 3)}다. data plane은 두 후보가 공유하므로 control plane은 성능 레버가 아니다.")
    L.append(f"- **C1과 C2가 실제로 갈리는 곳(별점 밖).** (1) **확장 한계:** control plane 포화 rate는 C2에서 S x N에 따라 줄고(stripe 1 -> 512에서 {f0(cc['d4_lock_stripes_1@H100'][C2]['saturation_rps'])} -> {f0(cc['d4_lock_stripes_512@H100'][C2]['saturation_rps'])} req/s, 노드 4 -> 16에서 {f0(cc['d4_node_scale_n4@H100'][C2]['saturation_rps'])} -> {f0(cc['d4_node_scale_n16@H100'][C2]['saturation_rps'])} req/s), C1은 서버 스레드로 늘어난다({f0(cc['d4_lock_stripes_1@H100'][C1]['saturation_rps'])} -> {f0(cc['d4_server_threads_4@H100'][C1]['saturation_rps'])} req/s, 1 -> 4 스레드). 다만 이 시뮬레이션의 제공 rate(최대 {f0(max(DPPS[k][C1]['offered_rps'] for k in DPPS))} req/s)보다 최소 {f0(hr[0][0])}배 위라 N <= 16에서는 어느 쪽도 포화하지 않았다(Scaling Efficiency는 제안 지표라 별 없음: N=16에서 C1 {f3(se[C1]['16'])}, C2 {f3(se[C2]['16'])}, Baseline {f3(se[B]['16'])}; 1을 넘는 것은 P 노드가 늘며 대기열이 풀링되는 효과). "
             f"(2) **장애:** C1은 메타데이터 서버가 SPOF여서 노드 손실(30 s 재구성)에서 Baseline 대비 goodput {bysys(nodeloss)}(C2 {bysys(nodeloss_c2)}); 프로세스 재시작(0.5 s)은 영향이 없다. "
             f"C2는 as-published 락이 풀리지 않아 요청 {bysys({k: v[0] for k, v in lh.items()}, f0)}건이 고착되고 가용성 창이 ∞이며(goodput {bysys({k: v[1] for k, v in lh.items()}, lambda v: xr(v, 3))}), lease 1 s 보완안은 {bysys(lease, lambda v: xr(v, 3))}로 회복한다(보완안은 평가자의 가정). "
             f"(3) **정확성(model check [C], 별점 아님):** 정상 C1·C2는 2노드에서 전수 탐색했고 4개 불변식에 반례가 없다. 결함 변종 {len(pcf['defects'])}개 중 {sum(pcf['exp_hit2'].values())}개가 2노드에서 기대한 위반을 냈다. 3노드는 탐색 상한({pcf['cap']:,} 상태)에 걸려 불완전하다(4.9).")
    L.append(f"- **QA4가 갈리는 이유와 취약성.** 두 후보의 module 수 평균은 같다({Q4['mean_over_scenarios']['C1']['modules']:.2f}). 갈리는 것은 공수 평균이다: C1 {ql['c1']:.3f} MM, C2 {ql['c2']:.3f} MM. 신규 topology(풀 2개, S4)에서 C2의 diff가 더 크다(측정 기록: proxy가 락 배열을 하나로 묶어 둬 풀별 분리 변경이 큼): LOC {Q4['scenarios']['S4']['C2']['loc_added']} 대 {Q4['scenarios']['S4']['C1']['loc_added']}, module 크기 {Q4['scenarios']['S4']['C2']['module_size_loc']} 대 {Q4['scenarios']['S4']['C1']['module_size_loc']} 줄이라 공수가 {Q4['scenarios']['S4']['C2']['man_months']:.3f} 대 {Q4['scenarios']['S4']['C1']['man_months']:.3f} MM다. "
             f"그런데 이 차이가 별을 가르는 것은 ★★★/★★ 경계(0.5 MM)가 두 값 사이에 있기 때문이다: C1은 경계보다 {pct(ql['c1_margin'])} 아래, C2는 {pct(ql['c2_margin'])} 위다. 경계를 ±10% 옮기거나 가정 상수를 바꾸면 두 후보가 같은 별이 되는 경우가 많다(0.3).")
    L.append(f"- **이득의 조건.** 후보가 Baseline을 이기는 것으로 판정된 쌍은 {len(wp)}쌍(44쌍 중, C1 = C2)이지만 **goodput이 95% CI 밖으로 좋아진 쌍은 {n_goodput_wins()}쌍**이고 4쌍 모두 지연 등급(QA2 별) 판정이다. 그 중 3쌍(H100 CB-1, CB-2, reference 행 `d4_node_scale_n2`)은 각 arm의 own-peak load를 비교한 효과라 같은 load에서는 후보가 더 느리다(5.2). "
             f"나머지 1쌍은 reuse 시나리오 `{ag}`로 같은 load에서 TTFT P99 {f0(DPPS[ag][B]['ttft_p99_ms'])} -> {f0(DPPS[ag][C1]['ttft_p99_ms'])} ms, TPOT P99 {f1(DPPS[ag][B]['tpot_p99_ms'])} -> {f1(DPPS[ag][C1]['tpot_p99_ms'])} ms이지만, 이는 Baseline의 seed 5개 중 일부에서 goodput이 붕괴한 결과다(seed별 goodput Baseline {seeds_s(ag_b)} 대 C1 {seeds_s(ag_c)} tok/s, Baseline CV {pct(DPPS[ag][B]['goodput_cv'], 0)}; goodput 판정은 tie). 같은 시나리오가 B200에서는 goodput {xr(agent['B200'], 2)}로 반대다. 따라서 **통계적으로 확정된 이득은 없고, 이득의 단서는 특정 조건(H100, 에이전트 reuse)에만 있으며 시스템에 따라 부호가 바뀐다.**\n")
    # 0.3
    L.append("## 0.3 선택과 근거\n")
    pstat = PRIO["status"]
    L.append(f"1. **선택 질문:** C1(중앙 직렬화) 대 C2(분산 락). 둘 다 같은 CXL 풀 data plane을 쓰므로 후보 간 비교는 control plane 책임의 비교다. CXL 풀 data plane 대 RDMA 비교(도입 여부)는 Baseline 비교이며 결론은 '이득 없음'이다(0.1, 7장).")
    L.append(f"2. **QA 우선순위: {' > '.join(PRIO['priority'])}, status = \"{pstat}\"**, 즉 사용자가 확정하지 않은 **제안**이다. 근거: {PRIO['rationale']}")
    L.append("3. **규칙(`tools/dp_selection.py`, H13):** 별 합계가 높은 후보를 선택하고, 합계가 같을 때만 우선순위 위에서부터 처음으로 별이 갈리는 QA가 결정한다.")
    L.append(f"4. **결과:** C1 {o['totals'][C1]}점(QA1 {CBQ[C1]['qa1']}, QA2 {CBQ[C1]['qa2']}, QA3 {CBQ[C1]['qa3']}, QA4 {Q4_STARS[C1]}), C2 {o['totals'][C2]}점(QA4 {Q4_STARS[C2]}). 합계가 달라 **선택: C1** (규칙: {o['rule']}). QA1~QA3은 두 후보가 같아 1점 차이는 전부 QA4(★★★ 대 ★★)에서 온다.")
    L.append(f"5. **결정 민감도(우선순위를 뒤집었을 때):** 합계로 정해졌으므로 우선순위와 무관하다. 우선순위를 뒤집어도({' > '.join(reversed(PRIO['priority']))}) 첫 차이 QA는 {o['reversed_deciding_qa']}이고 승자는 {SHORT.get(pr_rev, '-')}로 같다. **그러나 QA4가 같은 별이 되면 QA1~QA3이 모두 같아 어떤 우선순위로도 선택이 정해지지 않는다(미결정).**")
    L.append(f"6. **별 경계 민감도.** (a) QA1~QA3 경계를 x0.9/x1.1로 옮겨도 두 후보의 별은 변하지 않는다(둘 다 1/1/1, 합 {sw['1.0'][C1]['total']}; Baseline만 바뀜). (b) **QA4가 선택을 좌우한다.** M2(공수) 경계 0.5 MM와의 거리는 C1 {pct(ql['c1_margin'])}(아래), C2 {pct(ql['c2_margin'])}(위)다. 경계/집계/가정 상수/구조 대안 {nvar}가지 변형 중 C1이 선택되는 경우는 {kept}가지, **미결정(동점)은 {tied}가지**다:\n")
    L.append("| QA4 변형 | C1 QA4 | C2 QA4 | 합계 C1 / C2 | 선택 |\n|---|---|---|---|---|")
    for lab, a, b_, t1, t2, w in dt:
        L.append(f"| {lab} | {a} | {b_} | {t1} / {t2} | {w} |")
    L.append("")
    L.append(f"7. **정의 의존성(참고, H20).** QA3는 사전 등록 정의(Baseline peak load에서의 같은 요청 구간 비교)를 썼다. 후보가 이미 포화한 load에서 비교되어 값이 크게 나빠진다. 각 arm의 own-peak load에서의 KV 상주는 Baseline {f1(c[B]['res_own'])} GiB, 후보 {f1(c[C1]['res_own'])} GiB(절감 배수 {xr(c[B]['res_own'] / c[C1]['res_own'])}, 별 ★★ 구간), x1.0 load에서는 절감 배수 {xr(c[C1]['save1'])}이다. 이는 **민감도 보고일 뿐 정의를 바꾼 것이 아니며** 어느 정의에서도 C1=C2라 선택은 변하지 않는다(두 후보에 같은 별이 가산됨).")
    L.append(f"8. **선택 근거(문장).** QA1~QA3에서 두 후보는 구분되지 않으므로 성능은 근거가 아니다. C1을 고르는 근거는 (i) QA4에서 개발 공수·에이전트 비용이 낮다는 점(단 경계 근처의 작은 차이), (ii) 일관성 논증이 단일 직렬화 지점 하나로 단순하다는 구조적 특성이다(model check에서 정상 C1·C2 모두 2노드 전수 통과로 정확성 차이는 없었다). C1을 고를 때의 대가는 서버 SPOF(노드 손실 시 goodput {', '.join(xr(v, 2) for v in nodeloss.values())})이고, C2를 고를 때의 대가는 as-published 락 고착이다(lease 같은 보완안이 필요). **선택 C1은 QA4 하나에 기댄 약한 선택이다.**\n")
    # 0.4
    L.append("## 0.4 선택한 구조의 부족한 부분과 보완 설계\n")
    L.append("택틱 상세는 `doc-mk/DP4/DP4-complement-design-tactics.pptx`. **검증 상태:** [B] = 구현·측정됨(시뮬레이터 출력, [B+C]) / [C] = 논증·미구현. **미구현 택틱의 효과는 수치로 주장하지 않는다**(H14).\n")
    L.append(complement_table())
    L.append("")
    # 0.5
    L.append("## 0.5 어떤 시나리오를 고려했는지\n")
    ncb, ndp = len(RM["common_benchmark"]["fit"]), len(RM["dp4_benchmark"]["fit"])
    sat = [k for k, v in RM["dp4_benchmark"]["fit"].items() if v == "saturated"]
    L.append(f"서버 두 종류(prefill 담당, decode 담당)로 나뉜 클러스터에서 prefill 서버가 만든 KV cache(대화 문맥의 중간 계산 결과)를 decode 서버로 넘기는 경로를 비교했다. 현재 방식(Baseline)은 서버 사이를 네트워크(RDMA)로 직접 복사하고, 후보는 두 서버가 함께 쓰는 CXL 공유 메모리 풀에 한 번 두고 서로 읽는다. 공유 풀은 서버 간 캐시 일관성을 하드웨어가 주지 않아서 '누가 목록(메타데이터)을 관리하고 어떻게 서로 안전하게 읽는가'가 문제이며, 그 두 가지 답이 C1(한 서버가 전부 직렬로 처리)과 C2(모든 노드가 락을 잡고 직접 갱신)다.\n")
    L.append(f"총 **{ncb}쌍(공통 {len(CBLAB) // 2}개 시나리오 x 2시스템)과 {ndp}쌍(DP4 전용 {n_dp4_scen()}개 시나리오, 변종 포함 {len(DPLAB) // 2}행 x 2시스템)** = {ncb + ndp}쌍을 평가했다. Baseline도 SLO를 만족하는 비교 가능 쌍 {ft['common_benchmark']['comparison_valid'] + ft['dp4_benchmark']['comparison_valid']}쌍, 모든 arm이 같아 구분하지 못하는 포화 {ft['common_benchmark']['saturated'] + ft['dp4_benchmark']['saturated']}쌍({', '.join(sorted(sat))}), Baseline이 SLO를 못 맞춰 비교할 수 없는 쌍 {ft['common_benchmark']['infeasible'] + ft['dp4_benchmark']['infeasible']}쌍이다. 비교할 수 없는 쌍은 없었고, 승/무/패(Baseline 대비, 95% CI·1% 기준)는 C1 {tp[C1][0]}/{tp[C1][1]}/{tp[C1][2]}, C2 {tp[C2][0]}/{tp[C2][1]}/{tp[C2][2]}이다.\n")
    L.append(f"- **압박이 걸린 기본 서비스 상황(공통 3개).** 8K 토큰 입력·256 토큰 생성의 대화 서비스에서 서버 사이 링크가 다른 트래픽으로 거의 차 있는 경우(background 0.85), 처음에는 여유가 있다가 점점 막히는 경우(0.2에서 0.9로 증가), KV 외에 LoRA·MoE·Agent·Tool 데이터가 섞여 풀을 오가는 경우다. **별점은 여기서만** 나온다. 대표 예: 링크가 {ln['bg'] * 100:.0f}% 차 있을 때 KV {ln['kv_gib']:.1f} GiB를 옮기는 데 Baseline은 한 번({f0(ln['t_rdma_ms'])} ms), 후보는 쓰고 다시 읽어 두 번({f0(2 * ln['t_cxl_ms'])} ms) 걸린다(config 어림값).")
    L.append("- **접근이 쏠린 경우.** 요청의 90%가 같은 긴 prefix를 공유하는 경우(`d4_hot_prefix_fanout`: 같은 메타데이터 항목에 요청이 몰려 C1 서버 대기열과 C2 락 경합을 건드림). 고르게 흩어진 접근만 따로 본 시나리오는 없다.")
    L.append("- **데이터 종류별.** KV cache가 중심이고, 8턴 에이전트처럼 History KV가 쌓이며 재사용되는 경우(`d4_agent_multiturn`, 재사용을 켠 별도 행)와 KV·LoRA·MoE·Agent·Tool이 섞인 혼합(공통 CB-3)을 본다. 종류별 접근 패턴 차이는 모델링하지 않았다.")
    L.append("- **자원 조건과 규모의 변화.** 서버 수를 4·8·16대로 늘리는 경우, 한 번에 옮기는 블록 크기를 16·256 토큰으로 바꾸는 경우, 작은 prompt를 높은 rate로 받는 경우, 풀이 95% 차서 매번 퇴출이 필요한 경우, C2의 락 stripe 수와 C1의 서버 스레드 수를 바꾸는 경우를 본다.")
    L.append("- **장애.** C1 메타데이터 서버가 죽었다가 재시작하는 경우와 노드 손실로 인덱스를 다시 만드는 경우, C2 락을 쥔 노드가 죽는 경우(as-published는 락이 풀리지 않음, lease 보완안은 풀림).")
    L.append(f"- **정확성(별점 밖).** 비일관 캐시를 추상화한 모델에서 두 프로토콜과 결함 변종 {len(pcf['defects'])}개를 검사했다(4.9).")
    L.append("- **아직 없는 것.** 실제 CXL 풀 하드웨어 측정, 서버 2대 초과의 실측, 다중 테넌트 격리, 풀 장치 장애, 스위치 혼잡, KV 외 객체의 종류별 접근 패턴, 균일 접근 전용 시나리오, 실제 trace. 전체 시나리오 목록은 3장과 [`benchmark.md`](../benchmark.md).")
    L.append("")
    return "\n".join(L)


def complement_rows():
    """Weaknesses of the selected structure (C1) with evidence numbers and the complement tactic. Status: [B] implemented and measured / [C] argued, not implemented."""
    fl = RM["dp4_benchmark"]["failure"]
    nodeloss = {k.split("@")[1]: goodput_ratio("dp4_benchmark", k, C1) for k in fail_rows() if "node_loss" in k}
    restart = {k.split("@")[1]: goodput_ratio("dp4_benchmark", k, C1) for k in fail_rows() if "[restart]" in k}
    cc = RM["dp4_benchmark"]["cp_capacity"]
    hr = headroom()
    c = final_cells()
    ql = qa4_boundary_lines()
    pcf = pc_facts()
    agent = {k.split("@")[1]: goodput_ratio("dp4_benchmark", k, C1) for k in DPPS if k.startswith("d4_agent_multiturn")}
    be = SENS["break_even"][MERGED][C1]["bg0.85"]["qa1_ratio_parity"]["x"]
    ncl = pcf["r2"]["C1_no_clflush_on_server"]
    rows = [
        ("W1", f"메타데이터 서버 SPOF: 노드 손실(인덱스 재구성 30 s)에서 Baseline 대비 goodput {', '.join(f'{k} {xr(v, 2)}' for k, v in nodeloss.items())} (C2는 영향 없음). 프로세스 재시작(0.5 s, 인덱스는 CXL에 보존)은 {', '.join(f'{k} {xr(v, 3)}' for k, v in restart.items())}로 영향 없음",
         "스탠바이 메타데이터 서버를 다른 노드에 두고 CXL에 있는 인덱스를 그대로 인계(takeover). 재구성 풀 스캔을 피하는 것이 목적", "QA1·QA2 (장애 시)",
         "[B] 프로세스 재시작 경로(인덱스 CXL 보존)는 구현·측정됨. [C] 스탠바이 인계는 미구현, 효과 수치 없음"),
        ("W2", f"서버 포화 rate가 유한: 1 스레드 {f0(cc['d4_lock_stripes_1@H100'][C1]['saturation_rps'])} req/s(hot prefix, 노드 8), block 16에서 {f0(cc['d4_block16@H100'][C1]['saturation_rps'])} req/s. 제공 rate 대비 여유는 최소 {f0(min(h[0] for h in hr if h[2] == C1))}배라 N <= 16에서는 포화 없음. 서버 busy-poll 코어 {f1(CBQ[C1]['diag_cpu_core_eq'])}개 상시 점유",
         "서버 스레드 증설(1 -> 2 -> 4). 큰 block(256)으로 연산 수 감소", "QA1 (확장 시)",
         f"[B] 구현·측정됨: 서버 스레드 2/4에서 포화 rate {f0(cc['d4_server_threads_2@H100'][C1]['saturation_rps'])}/{f0(cc['d4_server_threads_4@H100'][C1]['saturation_rps'])} req/s (`d4_server_threads_*`), block 256에서 {f0(cc['d4_block256@H100'][C1]['saturation_rps'])} req/s. CPU 코어 비용 증가는 별도"),
        ("W3", f"정확성이 서버의 CLFLUSH-before-read와 슬롯 프로토콜에 의존: model check에서 `C1_no_clflush_on_server`는 I1 위반(반례 {ncl['invariants']['I1']['cex_length']} step, 2·3노드 모두 검출). 이 결과는 '슬롯 body 줄은 이전 요청의 값을 담은 채 서버 캐시에 있을 수 있다'는 저자 가정에 의존",
         "요청 슬롯의 body와 flag를 같은 cacheline 안의 sequence-numbered 항목으로 두거나 body에 검증값(checksum, seq)을 넣어 stale body를 서버가 감지하게 함(누락된 flush를 safety가 아닌 liveness 문제로 낮춤). 프로토콜 conformance 시험 추가", "정확성 (별점 밖)",
         "[C] 논증·미구현. 모델 README의 가정 설명에 근거, 효과 수치 없음"),
        ("W4", f"QA1 {xr(c[C1]['qa1_r'], 3)}, QA3 절감 {xr(c[C1]['save'])}, 공통 load TTFT P99 {xr(c[C1]['ct99'] / c[B]['ct99'])}: **data plane**(풀 경유 쓰기 + 읽기 순차)이 원인이며 C2도 같다. break-even η_cxl* {be:.3f}(ASSUMED)",
         "(a) 풀에서 필요한 블록만 읽는 partial read와 풀 사본 제거, (b) 청크 단위 publish로 쓰기와 읽기를 겹침(publish가 가시성 경계라는 제약 유지), (c) 단일 사용 KV는 RDMA 직접 경로로 두고 풀은 공유·재사용 객체에만 쓰는 하이브리드", "QA1·QA2·QA3",
         "[C] 논증·미구현. Iteration 2의 원인 분석(순차 read)에 근거. **효과 수치를 주장하지 않으며** 시뮬레이터 적용은 새 iteration으로 사전 등록해야 함"),
        ("W5", f"reuse 이득이 시스템에 의존하고 통계적으로 확정되지 않음: `d4_agent_multiturn` goodput 비 {', '.join(f'{k} {xr(v, 2)}' for k, v in agent.items())}. H100의 이득은 Baseline의 seed 5개 중 일부 붕괴(CV {pct(DPPS['d4_agent_multiturn@H100'][B]['goodput_cv'], 0)})에서 오며 goodput 판정은 tie",
         "reuse가 있는 객체(History KV, 공유 prefix)에만 풀을 쓰는 선택적 경로(W4-c와 동일 계열)와 시스템별 경로 선택 기준 마련. seed 수를 늘려 Baseline 붕괴의 빈도 확인(class N)", "QA1·QA2",
         "[C] 논증·미구현 (seed 추가는 미실시). 두 시스템 외 일반화 근거 없음"),
        ("W6", f"QA4 별이 경계 근처: C1 {ql['c1']:.3f} MM이 0.5 MM보다 {pct(ql['c1_margin'])} 아래이고 C2와의 차이는 {ql['c2'] - ql['c1']:.3f} MM. 측정 기준 시뮬레이터 소스가 Iteration 2 이전이라 재측정이 필요(4.5, 4.10)",
         "Iteration 2 이후 소스에서 QA4 변경 시나리오 4종 재구현·재측정, 가능하면 실제 vLLM 통합에서 module/LOC 측정", "QA4",
         "[C] 미실시. 재측정 전에는 QA4 별을 확정하지 않음"),
    ]
    return rows


def complement_table():
    rows = ["| # | 약점 (평가 근거 수치) | 보완 택틱 | 개선 대상 | 검증 상태 |", "|---|---|---|---|---|"]
    for r in complement_rows():
        rows.append("| " + " | ".join(esc(x) for x in r) + " |")
    return "\n".join(rows)


def sec1():
    pf = prefill_ms()
    sf = {s: sys_facts(s) for s in SYSIDS}
    cmd = ("cd doc-mk/Evaluation/DP4/sim && uv run --no-project python -m unittest test_sim -v && "
           "uv run --no-project python qa_eval.py --system SYS-H100 --jobs 4 --out-dir ../results/data/SYS-H100 && "
           "uv run --no-project python qa_eval.py --system SYS-B200 --jobs 4 --out-dir ../results/data/SYS-B200 && "
           "uv run --no-project python merge_systems.py SYS-H100 SYS-B200")
    L = ["# 1. 시스템 환경\n",
         "| 항목 | 값 |", "|---|---|",
         f"| SYS id | **SYS-H100** ({sf['SYS-H100']['gen']['gpu_hbm']}, {sf['SYS-H100']['gen']['host_link']}, {sf['SYS-H100']['gen']['cxl']}), **SYS-B200** ({sf['SYS-B200']['gen']['gpu_hbm']}, {sf['SYS-B200']['gen']['host_link']}, {sf['SYS-B200']['gen']['cxl']}), 통합 `{MERGED}`. SYS-A100/SYS-VR은 평가하지 않았다(DP1과 같은 세대 축, profile은 유지) |",
         "| 클러스터 profile | `DP4/sim/configs/cluster_dp4.json`(신규, 모든 파라미터에 value/range/provenance PAPER·SPEC·ASSUMED), sha1 `" + META["config_sha1"] + "`. 기존 profile은 수정하지 않았다(H10) |",
         f"| 노드 / topology | 노드 1개 = GPU {sf['SYS-H100']['gpus']}장(TP=8), P/D 분리. CB 기본 P1+D1(사용자 환경 서버 2대와 같은 규모), DP4-specific는 P2+D2 기본, 노드 수 sweep 4/8/16 |",
         f"| Model / precision | Llama-3.1-70B, BF16 (`DP1/sim/configs/models.json`), KV {kv_bytes_per_token():,} B/token (8K = {kv_bytes_per_token() * 8192 / 2**30:.2f} GiB). 8K prefill {f0(pf['SYS-H100'])} ms(H100) / {f0(pf['SYS-B200'])} ms(B200) (DP1 물리 재사용) |",
         f"| Git revision | {git_line()} |",
         f"| Seeds / loads | seeds {', '.join(str(s) for s in META['seeds'])} (5회) / load x{', x'.join(f'{x:g}' for x in META['loads'])}, peak가 grid 끝이면 x{META['max_load']:g}까지 상향 확장, 최저점이 peak이면 x0.0625까지 하향 확장(시나리오별 실제 load는 `meta.loads_run`). 95% CI t(0.975, df=4)=2.776, tie 판정 상대 차이 1% |",
         f"| Evidence | 시뮬레이션 [B+C] (입력 파라미터: PAPER 문헌값 [B], ASSUMED 가정), QA4 [B+C] proxy 구현, protocol model check [C]. **CXL 공유 풀 하드웨어가 없어 [A] 실측은 없다** |",
         f"| 재현 command | `{cmd}` ; ablation `python ablation.py --system SYS-H100` (SYS-B200도, 이후 `merge_systems.py SYS-H100 SYS-B200 --data-dir ../results/data/ablation`), `python star_basis.py --system SYS-H100`, `python sensitivity.py run --group grid` ; model check `cd sim/protocol_check && python check.py --nodes 2` (`--nodes 3`) ; 문서 `uv run --no-project python doc-mk/Evaluation/tools/gen_dp4_result.py` |",
         f"| 기록된 실행 명령 | 통합: `{META['command']}`; SYS-H100: `{META['source_commands']['SYS-H100']}`; SYS-B200: `{META['source_commands']['SYS-B200']}` |",
         "| Raw data | `DP4/results/data/`: `INT-H100-B200/`, `SYS-H100/`, `SYS-B200/`(`qa_result.json`, `*_runs.csv`), `ablation/`, `star_basis/`, `sensitivity/`(`summary.json`, `tables.md`), `pre_serial_read/`(수정 전 모델, 대체됨), `protocol_check.json`, `protocol_check_n3.json`, `qa4_measured_counts.json`, `qa4_modifiability.json` |",
         f"| 데이터 revision 참고 | 주 결과는 `{META['git']['revision']}`. 아래 파일은 다른 revision에서 생성되었다(기록값): " + ", ".join(f"{name} `{d['meta']['git']['revision']}`" for name, d in (("ablation", ABL), ("pre_serial_read", PRE))) + ". sensitivity/star_basis는 meta에 revision이 없다. 모두 같은 `cluster_dp4.json`(sha1 일치)과 같은 모델 코드를 쓴 것으로 대조군 일치로 확인했다(4.5) |",
         ""]
    L.append("시스템 profile 상세: [system-specs.md](../../system-specs.md). H100/B200 규격은 PUBLIC(확인 필요)이며, CXL·RDMA·락 관련 파라미터의 provenance는 `cluster_dp4.json`과 `simulation-plan.md` §4에 필드별로 있다. **C2의 락 상수(scan 비용, critical section 길이, stripe 수, 장애 처리)는 논문에 없어 ASSUMED이다.**\n")
    L.append(memory_config_table() + "\n")
    return "\n".join(L)


def sec2():
    L = ["# 2. 평가 항목\n", "| 항목 | 정의 / formula | 출처 |", "|---|---|---|",
         "| QA1 Max SLO Goodput | 요청별 SLO(TTFT <= 2 s and TPOT <= 50 ms)를 만족한 request의 output token/s. load sweep(x0.5~2.0, 필요 시 확장)의 최대값. **별점:** Common Benchmark 6쌍의 (후보 ÷ Baseline) **기하평균**, < 0.90 ★ / 0.90~1.10 ★★ / >= 1.10 ★★★ (공통 기준 그대로). T_ref = Baseline-RDMA | criteria §4, `qa-criteria-dp4.md` §1 |",
         "| QA2 TTFT P99 / TPOT P99 | 두 metric을 **별도 행**으로 보고(P50/P95/P99 모두 저장). 별 = 6쌍 중 각 arm의 Max-goodput load에서의 **최악 P99**: <= 2 s & <= 50 ms ★★★ / <= 4 s & <= 100 ms ★★ / 그 외 ★. 같은 offered load(Baseline peak)에서의 값(`*_common`)과 x1.0 load의 값(`*_load1`)을 병기 | criteria §5, DESIGN_NOTES A.8 |",
         "| QA3 Resource usage | **클러스터 KV 상주 메모리 시간 평균 GiB**(P 노드 전송 버퍼 + D HBM + 풀), Baseline peak load에서 같은 요청 구간 비교, 낮을수록 좋음. 별 = 절감 배수(Baseline ÷ 후보) < 0.95 ★ / 0.95~1.25 ★★ / >= 1.25 ★★★ (DP1 QA3 경계를 가져옴). 성능을 섞지 않는다(H20) | **임시 정의**: `qa-criteria-dp4.md` §2 |",
         "| QA4 Modifiability | 변경 시나리오 4종(신규 HW capability / 객체 class / 정책 교체 / topology)을 시뮬레이터 proxy에 구현해 (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) 에이전트 토큰 비용($, T1 frontier). 시나리오 평균에 경계 적용(M1 <= 2 / <= 5, M2 <= 0.5 / <= 1.0 MM, M3 <= $3 / <= $10), QA4 별 = 세 sub-star의 중앙값 | M1은 criteria §7, M2·M3·집계는 **임시 정의**(`qa4-preregistration.md`, DP1과 같은 공식·상수) |",
         "| Scalability (제안) | Scaling Efficiency = Goodput(N) / ((N/2) x Goodput(2)), N = 4/8/16, 노드당 부하 고정. **공식 QA가 아니며 값만 보고, 별점 없음**(사용자 확정 전, H11) | `qa-criteria-dp4.md` §3 |",
         "| 정확성 (별점 아님) | protocol model check: 불변식 I1 가시성 / I2 use-after-free / I3 상호 배제 / I4 stale index. 제약이지 QA가 아님 | `simulation-plan.md` §8, 4.9 |",
         "| 집계 범위 | **별점 = Common Benchmark 6쌍만**(사전 등록, `common-benchmark.md` §7). DP4-specific 38쌍은 diagnostic과 QA4 근거이며 별점에 섞지 않는다. 승/무/패, fit 라벨, 결론은 두 set 44쌍 모두를 쓴다 (H3) | `qa-criteria-dp4.md` §1 |",
         "| Diagnostic | control-plane op latency P50/P99(lookup/publish/pin/unpin), control-plane 포화 rate(open-loop sweep, P99 chain latency가 10배가 되는 최저 rate), 서버·락·풀·링크 점유율, 락 대기, coherence CPU core-equivalent, 장애 시 SLO 위반 수·가용성 창 | DP4 전용 |",
         "| 승/무/패 | 쌍별로 goodput(상대 차이 < 1% 또는 95% CI 이내는 tie)과 지연 등급을 비교(`qa_eval.compare_pair`) | DP1과 같은 규칙 |",
         "| 모델 오차 sweep (H17) | **해당 없음**: DP4 후보는 estimator/predictor에 의존하지 않는다 | — |",
         ""]
    return "\n".join(L)


def sec3():
    L = ["# 3. 벤치마크 / 시나리오\n",
         "정의와 시나리오당 한 줄 설명은 [`DP4/benchmark.md`](../benchmark.md)(생성: `tools/gen_dp4_benchmark_doc.py`, 단일 소스 `DP4/sim/scenarios.py`)와 [`common-benchmark.md`](../../common-benchmark.md). fit 라벨: **V** comparison-valid / **S** saturated / **I** infeasible (H100 / B200 순, SKILL §4 정의). 제외한 시나리오는 없다(비교 불가 0).\n",
         "| Benchmark set | 시나리오 (행) | 드러내는 As-Is 약점 (`Scenario.exposes`) | Fit (H100 / B200) | 비고 |", "|---|---|---|---|---|"]
    notes = {"d4_node_scale_n2": "Scaling Efficiency 분모용 reference 행(benchmark.md의 공식 시나리오가 아니나 집계 쌍에 포함됨)",
             "d4_agent_multiturn": "reuse 켬(별도 행)", "d4_fail_server[restart]": "프로세스 재시작 0.5 s", "d4_fail_server[node_loss]": "노드 손실, 인덱스 재구성 30 s",
             "d4_fail_lockholder[as_published]": "as-published(락 해제 없음)", "d4_fail_lockholder[lease]": "lease 1 s 보완안 (평가자의 가정)"}
    for lab, name in SETS:
        names = sorted({k.split("@")[0] for k in RM[lab]["fit"]})
        for n in names:
            fit = {s: RM[lab]["fit"][f"{n}@{s}"] for s in ("H100", "B200")}
            ex = RM[lab]["exposes"][n]
            br = RM[lab]["briefs"][n]
            L.append(f"| {name} | `{n}` — {esc(br)} | {esc(ex)} | {FIT_LETTER[fit['H100']]} / {FIT_LETTER[fit['B200']]} | {esc(notes.get(n, ''))} |")
    L.append("")
    ft = fit_counts()
    sat = [k for k, v in RM["dp4_benchmark"]["fit"].items() if v == "saturated"]
    L.append(f"fit 집계: Common {ft['common_benchmark']} / DP4 {ft['dp4_benchmark']}. saturated 쌍: {', '.join(f'`{s}`' for s in sat)}. "
             "참고: Iteration 2 이전 모델에서는 DP4 행의 comparison-valid가 6쌍, saturated가 32쌍이었다. 순차 read로 수정한 뒤 read가 TTFT에 노출되어 대부분 쌍에서 TTFT가 Baseline과 유의하게 달라져 라벨이 바뀌었다(기계적 변화, loop-log Iteration 2).\n")
    L.append("**시나리오 선택 의존성.** 시나리오는 결과 전에 `simulation-plan.md` §6에 사전 등록했다. 압박(background 0.85, 0.2~0.9)은 ASSUMED이며 결과를 본 뒤 바꾸지 않았다. Common의 압박 정의(링크 background)는 DP1의 HBM 용량 축소와 의미가 달라 DP 간 공통 별점 직접 비교에 한계가 있다.\n")
    return "\n".join(L)


def sec4():
    c = final_cells()
    L = ["# 4. 결과\n", "표의 모든 숫자는 `results/data/INT-H100-B200/qa_result.json`(및 SYS-*, ablation, sensitivity 등 아래 명시한 파일)에서 `tools/gen_dp4_result.py`가 옮겼다. 손으로 쓴 수치는 없다.\n"]
    L.append("## 4.1 최종 QA 표 (Common 별점 기준, 통합 H100 + B200)\n")
    L.append(final_qa_table() + "\n")
    L.append(system_note() + "\n")
    L.append("### 4.1a 시스템별 단독 (일관성 확인용, 0장에는 매트릭스로 내지 않음)\n")
    L.append(per_system_table() + "\n")
    L.append("### 4.1b 전체 benchmark 합산 참고 (Common + DP4-specific 44쌍, **별점 산출에 쓰지 않음**)\n")
    L.append(combined_table() + "\n")
    L.append("## 4.2 시나리오별 결과\n")
    L.append(f"n_seeds = {len(META['seeds'])}, 95% CI = t(0.975, df=4)=2.776, CV = 표준편차/평균(seed 간). 'g'=goodput 판정, 'ttft', 'tpot' = 해당 P99 판정(win/tie/loss). 후보 CV 범위: Common C1 {pct(min(CBPS[k][C1]['goodput_cv'] for k in CBPS))}~{pct(max(CBPS[k][C1]['goodput_cv'] for k in CBPS))}, DP4 C1 {pct(min(DPPS[k][C1]['goodput_cv'] for k in DPPS))}~{pct(max(DPPS[k][C1]['goodput_cv'] for k in DPPS))}; Baseline DP4 최대 {pct(max(DPPS[k][B]['goodput_cv'] for k in DPPS))}(`{max(DPPS, key=lambda k: DPPS[k][B]['goodput_cv'])}`).\n")
    L.append("### 4.2.1 Common (각 arm의 Max-goodput load 기준)\n")
    L.append(per_pair_table("common_benchmark") + "\n")
    L.append("#### 같은 offered load(Baseline peak load)에서의 비교\n")
    L.append("각 arm의 peak load는 다르므로 위 표의 TTFT는 서로 다른 load 점의 값이다. 아래는 Baseline의 peak load에서 세 arm을 같은 요청 흐름으로 비교한 값이다(QA3와 `*_common` QA2의 기준).\n")
    L.append(common_load_table() + "\n")
    L.append("### 4.2.2 DP4-specific\n")
    L.append(per_pair_table("dp4_benchmark") + "\n")
    ag = "d4_agent_multiturn@H100"
    L.append(f"**주의 (`{ag}`):** Baseline goodput의 CV가 {pct(DPPS[ag][B]['goodput_cv'], 0)}인 것은 seed 5개 중 일부에서 TTFT P99가 폭증하며 goodput이 붕괴하기 때문이다. seed별 goodput(tok/s, seed {', '.join(str(x) for x in META['seeds'])}): Baseline {' / '.join(f0(x) for x in seed_list(ag, B))}; C1 {' / '.join(f0(x) for x in seed_list(ag, C1))}; "
             f"seed별 TTFT P99(ms): Baseline {' / '.join(f0(x) for x in seed_list(ag, B, 'seeds_ttft_p99_ms'))}; C1 {' / '.join(f0(x) for x in seed_list(ag, C1, 'seeds_ttft_p99_ms'))}. 이 쌍의 goodput 판정은 tie(쌍별 차이의 95% CI ±{f0(DPLAB[ag]['vs_baseline'][C1]['goodput_diff_ci95'])} tok/s)이다.\n")
    L.append("## 4.3 Diagnostic\n")
    L.append(diag_table() + "\n")
    L.append(cp_op_table() + "\n")
    L.append("**Control-plane 포화(open-loop sweep).** 연산(lookup/publish/pin/unpin)만 실행하는 요청 흐름을 100 req/s부터 2배씩 올려 P99 chain latency가 100 req/s 때의 10배가 되는 최저 rate를 포화로 본다. 제공 rate는 해당 행의 own-peak load에서 시뮬레이션이 실제로 낸 rate다.\n")
    L.append(headroom_table() + "\n")
    L.append("## 4.4 C1 vs C2 직접 비교 / Scalability / 장애\n")
    q, dpd = agg_dev_c1_c2()
    qn = {"qa1_abs_goodput_geomean_tps": "QA1 goodput", "qa2_common_ttft_p99_ms_geomean": "공통 load TTFT P99", "qa3_kv_resident_gib_geomean": "QA3 KV 상주"}
    L.append(f"**성능:** C2 대 C1의 Common QA 차이 {', '.join(qn[k] + ' ' + pct(v, 4) for k, v in q.items())}; 장애 행을 뺀 DP4 쌍의 goodput 차이 최대 {pct(dpd, 4)}. 값은 같고 C1과 C2는 QA1~QA3에서 구분되지 않는다.\n")
    L.append("**Scalability (제안 지표, 별 없음, 노드당 부하 고정, 통합=시스템 기하평균):** 1을 넘는 값은 P 노드 수가 늘며 대기열이 풀링되는 효과(DESIGN_NOTES A.22)이며 control plane 병목 부재를 뜻하지 않는다. 값은 Baseline도 같은 범위다.\n")
    L.append(scaling_table() + "\n")
    L.append("**장애** (as-published와 보완안을 분리 보고, 시스템별):\n")
    L.append(failure_table() + "\n")
    L.append("## 4.5 시스템·파일 간 일관성 확인\n")
    cons, diff = consistency()
    L.append("| 확인 항목 | 비교 수 | 최대 편차 | 결과 |\n|---|---:|---:|---|")
    for name, n, d, ok in cons:
        L.append(f"| {name} | {n} | {d:.2e} | {'일치' if ok else '**불일치**'} |")
    L.append("")
    if diff:
        L.append(f"**불일치 보고:** QA4 변경 시나리오의 측정은 Iteration 2(순차 read) 이전의 시뮬레이터 복사본(측정 기준 소스 중 `{', '.join(sorted(diff))}`가 현재와 다름)에서 이루어졌다. QA4가 센 module(CXL-RPC channel, metadata server, 락·할당기·flush 계층)은 `arms.py`에 있고 `arms.py`와 `cluster_dp4.json`은 base와 일치하지만, 공통 module인 GPU↔CXL Copy/DMA handler는 `simulator.py`에 있어 Iteration 2에서 바뀐 부분이다(S4의 shared 크기 산정에 영향 가능). 재측정하지 않았으며 6장에 한계로 적었다.\n")
    L.append("## 4.6 Ablation (SKILL §9, `DP4/sim/ablation.py`)\n")
    ae = ablation_effect()
    L.append("각 후보의 핵심 구성요소를 제거한 변형을 같은 시나리오·시스템·seed로 실행했다. `C1-no-batch` = RPC당 블록 hash 1개(batch 제거), `C2-no-scan` = 락 매니저 scan 대기 제거(직접 hand-off). 대조군(full 후보)은 본 결과와 일치한다(4.5). 데이터 revision은 `" + ABL["meta"]["git"]["revision"] + "`이다.\n")
    L.append(ablation_table() + "\n")
    lat = ae["lat"]
    L.append(f"제거 변형과 full 후보의 goodput 차이는 최대 {pct(ae['C1-no-batch'], 4)}(C1-no-batch), {pct(ae['C2-no-scan'], 4)}(C2-no-scan)이며 별 합계와 선정 결과는 변하지 않는다 -> **제거해도 순위가 바뀌지 않는다.** 단 control-plane 지연에는 영향이 있다(`{lat['row']}`, Baseline peak load): C2 pin P50 {f1(lat['c2_pin'])} us -> scan 제거 시 {f1(lat['c2n_pin'])} us, C1 publish P50 {f1(lat['c1_pub'])} us -> batch 제거 시 {f1(lat['c1n_pub'])} us(lookup {f1(lat['c1_look'])} -> {f1(lat['c1n_look'])} us). 이 영향은 TTFT의 {pct(1e-3 * max(lat['c2_pin'], lat['c1n_pub']) / DPPS['d4_hot_prefix_fanout@B200'][C2]['at_base_peak']['ttft_p50_ms'], 3)} 미만이라 QA에 드러나지 않는다. 효과가 어느 하위 메커니즘에서 오는지 분해하면: 성능(QA1~QA3) 차이는 어느 구성요소에서도 나오지 않고(data plane 지배) control-plane 지연 차이만 각 구성요소(scan, batching)에서 나온다.\n")
    L.append("## 4.7 별점 경계의 근거 (SKILL §10, `DP4/sim/star_basis.py`)\n")
    L.append(star_basis_table() + "\n")
    L.append("- **하한(★/★★) QA1 0.90:** Baseline-vs-Baseline 잡음(겹치지 않는 seed 묶음 4개의 같은 집계)의 최대 편차보다 크다(여유 배수 위 표). 측정은 시뮬레이션 잡음이며 하드웨어 잡음이 아니다 [B+C].")
    L.append(f"- **QA3 하한 0.95는 잡음 안에 있다:** Baseline 간 QA3 절감 배수의 흔들림이 SYS-H100에서 {pct(SB['SYS-H100']['qa3_noise_max_dev'])}, SYS-B200에서 {pct(SB['SYS-B200']['qa3_noise_max_dev'])}로 5%보다 크다. 후보의 QA3 절감 배수({xr(c[C1]['save'])})는 경계(0.95)보다 훨씬 아래라 ★ 판정은 잡음에 민감하지 않지만, Baseline의 ★★ 판정과 0.95 경계의 의미는 측정으로 뒷받침되지 않는다.")
    L.append("- **상한(★★/★★★) 1.10, 1.25와 QA2의 시간 경계, QA4 경계:** 측정으로 정해지는 값이 아니라 정책 선택(공통 문서의 사전 정의)이다. 환산 근거를 만들지 않았다(미구현). 후보가 상한 근처에 있지 않으므로(QA1 {xr(c[C1]['qa1_r'], 3)}, QA3 절감 {xr(c[C1]['save'])}) 상한 민감도는 선택에 영향이 없다.\n".replace("{xr(c[C1]['qa1_r'], 3)}", xr(c[C1]['qa1_r'], 3)).replace("{xr(c[C1]['save'])}", xr(c[C1]['save'])))
    L.append("\n**QA1~QA3 경계 x0.9 / x1.1 (모든 경계 동시) 시 별** (INT, 사전 등록 경계를 결과 후 바꾼 것이 아닌 민감도):\n")
    L.append(star_boundary_table() + "\n")
    L.append("## 4.8 민감도 (Iteration 1, 파라미터 재조정이 아닌 보고; main 값은 불변)\n")
    L.append("모든 설정을 SYS-H100·SYS-B200에서 같은 benchmark로 재실행했고 (η_cxl 0.5, bg 0.85) 셀은 main 결과를 정확히 재현했다(4.5). **어떤 셀도 main으로 승격하지 않았다.** 배경 부하 bg는 ASSUMED 시나리오 상수다(CB-1/3의 수준 c로 모든 bg를 c/0.85배, CB-2는 형태 유지).\n")
    L.append(eta_grid_tables() + "\n")
    L.append("**Break-even** (후보가 Baseline에 도달하는 η_cxl; 보간값). 대역폭 동등점(후보 노드 CXL 유효 대역 = Baseline RDMA 유효 대역)은 η_cxl = " + f"{SENS['meta']['eta_bw_parity']:.3f}" + f"(= {cfgv('nic_bw_Bps') * cfgv('eta_rdma') / 1e9:g} GB/s ÷ {cfgv('cxl_adapters_per_node') * cfgv('cxl_adapter_bw_Bps') / 1e9:g} GB/s)이다.\n")
    L.append(break_even_table() + "\n")
    L.append("**provenance:** η_cxl* 값은 모두 사전 등록 ASSUMED 범위 [0.25, 0.9] 안이다. η_cxl 자체가 ASSUMED(PAPER 근거는 어댑터 63 GB/s x 2)이고 비교 대상인 η_rdma도 ASSUMED(0.85)이므로 **ASSUMED 대 ASSUMED 비교**다. 어느 쪽이 맞는지 이 평가는 알지 못한다. TTFT P99 악화 쌍 0은 격자의 어떤 설정에서도 달성되지 않았다(최소 1쌍).\n")
    L.append("**단일 파라미터 민감도 (통합, Common)**\n")
    L.append(one_param_table() + "\n")
    L.append("**Control-plane 파라미터 민감도 (S, probe, critical section 수, metadata 비용, RPC batch, 서버 스레드)** — **Iteration 2에서 재실행하지 않았다**(loop-log: move path 수정과 무관하며 Iteration 1에서 Common 결과를 움직이지 않음). 아래는 수정 전 모델(`pre_serial_read`, git " + PRE["meta"]["git"]["revision"] + ")의 값이며 대체된 모델의 값이라 절대값(예: 0.733)을 현재 값과 섞지 말 것. 결론(Common 결과가 control-plane 상수에 무관)만 인용한다.\n")
    L.append(cp_sweep_table() + "\n")
    L.append("## 4.9 Protocol model check (정확성, [C], 별점 아님)\n")
    L.append(protocol_section())
    L.append("## 4.10 QA4 상세 (측정: `qa4_measured_counts.json`, 계산: `qa4_modifiability.json`, 도구 `tools/qa4_modifiability.py`)\n")
    L.append(qa4_scenario_table() + "\n")
    L.append(f"sub-star(시나리오 평균): C1 {Q4['sub_stars']['C1']['M1']}/{Q4['sub_stars']['C1']['M2']}/{Q4['sub_stars']['C1']['M3']}, C2 {Q4['sub_stars']['C2']['M1']}/{Q4['sub_stars']['C2']['M2']}/{Q4['sub_stars']['C2']['M3']} (M1/M2/M3). 최악값 집계(v1)에서는 두 후보 모두 {Q4['qa4_stars_worst_case']['C1']}이다. "
             f"M2 공수 평균 C1 {qa4_boundary_lines()['c1']:.3f}, C2 {qa4_boundary_lines()['c2']:.3f} MM (경계 0.5). M1 평균 module {qa4_boundary_lines()['m1']:.2f}은 ★★★ 경계(2)보다 {pct(qa4_boundary_lines()['m1_margin'])} 위다.\n")
    L.append("QA4의 가정 상수 민감도와 구조 대안별 별은 0.3의 표에 있다. 구조 대안 설명: " + "; ".join(f"{k}: {v['note']}" for k, v in Q4["sensitivity_structure_alternatives"].items()) + ". "
             "측정은 실제 에이전트 세션이 아니라 **시뮬레이터 proxy 구현**의 diff이며, 공수·가격·배율은 가정이다. component 귀속은 판단이다.\n")
    L.append("## 4.11 Iteration summary (Baseline-regression loop, [`iterations/loop-log.md`](iterations/loop-log.md))\n")
    L.append("| Iteration | Class (P/B/S/M/N) | Change | Effect (전체 benchmark 기준) |\n|---|---|---|---|")
    for r in iteration_rows():
        L.append("| " + " | ".join(esc(x) for x in r) + " |")
    L.append("")
    L.append(f"**중단 규칙 결과.** 모든 comparison-valid 시나리오와 집계 QA에서 후보 >= Baseline이어야 한다는 중단 조건 (i)은 충족되지 않았다(후보 < Baseline인 Common 쌍이 남고, goodput이 95% CI 밖으로 좋아진 쌍(N_win)도 {n_goodput_wins()}쌍으로 기준 3 미만). 로그의 사전 등록 판정 규칙(Iteration 2)에 따라 추가 iteration으로 η_cxl 등 가정을 조정하지 않고 멈췄다(최대 6 iteration 중 2회 사용). 시도한 변경: Iteration 1 = 민감도 진단(변경 없음, class S), Iteration 2 = 순차 read 수정(class M). 문장: "
             "**under the tested conditions the architecture shows no benefit over the baseline** (CXL 공유 풀 data plane 대 RDMA data plane; 후보 C1·C2 모두). 이 문서가 사용자에게 올리는 escalation이다.\n")
    L.append("## 4.12 수정 전 결과와의 대조 (H16, H9)\n")
    L.append(pre_post_table() + "\n")
    return "\n".join(L)


def pre_post_table():
    pq, nq = PRE["common_benchmark"]["qa_feasible"], CBQ
    rows = ["| 지표 (통합 Common, C1 = C2) | 수정 전 (`pre_serial_read`, git " + PRE["meta"]["git"]["revision"] + ") | 수정 후 (main, git " + META["git"]["revision"] + ") |", "|---|---|---|"]
    g = lambda q, k: q[C1][k]
    rows.append(f"| QA1 ratio | {f3(g(pq, 'qa1_ratio_geomean'))} ({g(pq, 'qa1')}) | {f3(g(nq, 'qa1_ratio_geomean'))} ({g(nq, 'qa1')}) |")
    for sid in SYSIDS:
        rows.append(f"| QA1 ratio {sid} | {f3(PRE_SYS[sid]['common_benchmark']['qa_feasible'][C1]['qa1_ratio_geomean'])} | {f3(R[sid]['common_benchmark']['qa_feasible'][C1]['qa1_ratio_geomean'])} |")
    rows.append(f"| QA2 별 / TTFT P99 공통 load (ms) | {g(pq, 'qa2')} / {f0(g(pq, 'qa2_common_ttft_p99_ms_geomean'))} | {g(nq, 'qa2')} / {f0(g(nq, 'qa2_common_ttft_p99_ms_geomean'))} |")
    rows.append(f"| QA3 절감 배수 / KV 상주 (GiB) | {f3(g(pq, 'qa3_saving_multiplier'))} / {f1(g(pq, 'qa3_kv_resident_gib_geomean'))} | {f3(g(nq, 'qa3_saving_multiplier'))} / {f1(g(nq, 'qa3_kv_resident_gib_geomean'))} |")
    tp, tn = tally_counts(C1, PRE), tally_counts(C1)
    rows.append(f"| 승/무/패 (44쌍) C1 | {tp[0]}/{tp[1]}/{tp[2]} | {tn[0]}/{tn[1]}/{tn[2]} |")
    fp, fn = fit_counts(PRE), fit_counts()
    rows.append(f"| fit (DP4 행) comparison-valid / saturated | {fp['dp4_benchmark']['comparison_valid']} / {fp['dp4_benchmark']['saturated']} | {fn['dp4_benchmark']['comparison_valid']} / {fn['dp4_benchmark']['saturated']} |")
    rows.append(f"| QA1 parity break-even η_cxl* (통합, bg 0.85) | {PRE_SENS['break_even'][MERGED][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f} | {SENS['break_even'][MERGED][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f} |")
    rows.append(f"| 별 (QA1/QA2/QA3) | {g(pq, 'qa1')}/{g(pq, 'qa2')}/{g(pq, 'qa3')} | {g(nq, 'qa1')}/{g(nq, 'qa2')}/{g(nq, 'qa3')} |")
    return "\n".join(rows) + "\n\n사유: 후보 move path가 write와 read를 한 cut-through flow로 겹쳐 후보에 유리하게 편향되어 있었다(read는 publish 이후에만 가능). 수정으로 별은 바뀌지 않았고 격차가 커졌다. 수정은 사전 등록(loop-log Iteration 2)했고 이전 결과는 `results/data/pre_serial_read/`에 보존했다."


def protocol_section():
    pcf = pc_facts()
    r2, r3 = pcf["r2"], pcf["r3"]
    L = []
    L.append(f"모델: {PC[2]['model']}, Evidence {PC[2]['evidence']}. explicit-state BFS(정확 상태 dedupe, 최단 반례). 한 block 수명 동안 eviction 1회와 재할당, 전역 락 stripe 1개, 노드 2개(또는 3개) + 락 매니저 호스트(C2) / 서버 호스트(C1), 상태 상한 {pcf['cap']:,}. 불변식: " + "; ".join(f"**{k}** {v}" for k, v in PC[2]["invariant_definitions"].items()) + ".\n")
    L.append("### 4.9.1 2노드 (`protocol_check.json`)\n")
    L.append(pc_table(2) + "\n")
    n_hit = sum(pcf["exp_hit2"].values())
    L.append(f"- **정상 프로토콜:** C1과 C2 모두 상태 {r2['C1']['states']:,} / {r2['C2']['states']:,}개를 **전수 탐색**했고 I1~I4에 반례가 없다(모델 안에서의 통과, 구현의 정확성이 아님).")
    L.append(f"- **결함 변종 검출(검사기 자체의 검증):** 결함 변종 {len(pcf['defects'])}개 중 기대한 불변식 위반을 낸 것은 {n_hit}개({', '.join(k for k, v in pcf['exp_hit2'].items() if v)}). "
             "각 변종이 위반한 불변식: " + "; ".join(f"`{k}` -> {', '.join(pcf['viol'](r2[k])) or '없음'}" for k in pcf["defects"]) + ". 일부는 기대 외의 불변식도 위반했다(예: `C2_manager_double_grant`는 기대한 I3 외에 I1, I2도 위반).")
    L.append(f"- **탐색 상한(cap)에 걸려 전수가 아닌 변종:** {', '.join(f'`{k}`' for k in pcf['capped2'])}. 이 변종들에서 '반례 없음'으로 표시된 불변식은 **탐색한 부분에서 못 찾았다는 뜻일 뿐 통과가 아니다**. 이미 위반으로 찾은 불변식은 반례(최단 경로)가 있으므로 그 위반은 모델 안에서 실재한다(trace는 `check.py`가 행동열을 처음부터 replay해 생성). "
             f"예: `C2_clflushopt`는 I2 위반만 찾았고 I1·I3·I4는 상한 도달로 불완전하며, `payload_via_cpu_cache`는 I1 위반을 찾았으나 I2~I4는 불완전하다. 정상 C1/C2와 `C2_no_invalidate_before_read`, `C2_manager_double_grant`, `publish_before_dma_complete`는 상한 안에서 전수 탐색했다(전수 탐색에서 '통과'로 표시된 불변식은 모델 안에서 완전한 결과).\n")
    L.append("### 4.9.2 3노드 (`protocol_check_n3.json`) — **n=3 caveat**\n")
    L.append(pc_table(3) + "\n")
    n3_normal_capped = all(r3[k]["capped"] for k in ("C1", "C2"))
    L.append(f"- **n=3에서는 모든 변종의 탐색이 상한({pcf['cap']:,} 상태)에 걸렸다**(정상 C1·C2 포함{'' if n3_normal_capped else ' 일부'}). 따라서 3노드의 정상 C1·C2 결과는 '탐색한 범위에서 반례 없음'일 뿐 통과가 아니다. 결함 변종 {len(pcf['defects'])}개 중 3노드에서 위반을 검출한 것은 **{len(pcf['detected3'])}개({', '.join(f'`{k}`' for k in pcf['detected3'])})뿐**이다. "
             "나머지 변종이 3노드에서 검출되지 않은 것은 결함이 없어서가 아니라(2노드에서는 검출됨) 상태 공간이 상한 안에서 해당 반례에 닿지 못했기 때문이다. 즉 3노드 결과는 검사기의 한계를 보여 주며 후보에 대한 증거로 쓰지 않는다. 2노드 전수 결과가 이 DP의 정확성 증거이고, N >= 3 확장은 **미검증**이다.")
    ncl = r2["C1_no_clflush_on_server"]
    L.append(f"- **`C1_no_clflush_on_server`의 결과를 결정하는 가정(stale slot-body).** 이 변종은 I1을 위반했다(반례 {ncl['invariants']['I1']['cex_length']} step, 2노드·3노드 모두). 그러나 이 결과는 **저자 가정**에 의존한다: 요청 슬롯이 flag 줄과 별도의 body 줄로 나뉘고 body 줄은 재사용되어 이전 요청(UNPIN)의 내용을 담은 채 서버 캐시에 이미 있을 수 있다. 이 가정이 없고 sequence-numbered 핸드셰이크를 쓰면 서버의 CLFLUSH 누락은 안전성 위반이 아니라 liveness 문제(영원히 stale 값을 기다림)가 되며, 이 검사기는 safety만 본다(liveness 미검사). 논문에는 이 슬롯 배치가 규정되어 있지 않다(모델 README의 '논문 근거 대 저자 가정' 표). 락 매니저 배치, 슬롯 재사용 규칙도 저자 가정이다.")
    L.append("- **검사하지 않은 것:** safety만(I1~I4), liveness/progress 미검사, 단일 워드 cell, 한 block 수명, 락 stripe 1개, DMA read는 워드 단위 동기, allocator 상태는 entry cell에 흡수(다중 writer allocator 경합 미모델), 실제 CPU/CXL 하드웨어 메모리 모델의 검증이 아님. 한계 원문: " + " / ".join(PC[2]["limitations"][:3]) + "\n")
    return "\n".join(L)


def sec5():
    c = final_cells()
    L = ["# 5. 결과 분석\n"]
    L.append("## 5.1 Baseline 미만 (또는 이득이 의심스러운) 모든 쌍의 root cause\n")
    rows = ["| 쌍 | 후보 < Baseline? (C1 / C2 판정) | Root cause | Class | 근거 diagnostic |", "|---|---|---|---|---|"]
    ln = link_numbers()
    for lab, ps, labs in (("common_benchmark", CBPS, CBLAB), ("dp4_benchmark", DPPS, DPLAB)):
        for k in sorted(ps):
            vb = labs[k]["vs_baseline"]
            if vb[C1]["verdict"] != "loss" and vb[C2]["verdict"] != "loss":
                continue
            v = ps[k]
            bp = {a: v[a]["at_base_peak"] for a in (B, C1, C2)}
            if lab == "common_benchmark":
                where = (f"후보는 더 낮은 load(x{v[C1]['load']:g})에서 goodput peak를 갖고 Baseline peak load(x{v['_base_peak_load']:g})에서는 포화한다" if v[C1]["load"] < v["_base_peak_load"]
                         else f"후보도 같은 load(x{v[C1]['load']:g})에서 peak이나 goodput이 낮고 TTFT P99가 악화된다")
                cause = (f"data plane: 풀 경유 쓰기 + 읽기 순차가 Baseline의 단일 RDMA 전송보다 링크를 더 오래 점유(config 어림값: RDMA {f0(ln['t_rdma_ms'])} ms 대 CXL {f0(2 * ln['t_cxl_ms'])} ms/요청, bg {ln['bg']:g})하고 η_cxl {cfgv('eta_cxl'):g} 대 η_rdma {cfgv('eta_rdma'):g}(둘 다 ASSUMED). " + where)
                cls = "S (η 가정) + M (순차 read 모델 수정, Iteration 2); P 아님"
                diag = (f"goodput {xr(goodput_ratio(lab, k, C1), 3)}; 공통 load TTFT P99 {f0(bp[B]['ttft_p99_ms'])} -> {f0(bp[C1]['ttft_p99_ms'])} ms; 링크 점유 B {pct(v[B]['link_util_egress'], 0)} / C1 {pct(v[C1]['link_util_egress'], 0)}; KV 상주 {f1(bp[B]['kv_resident_gib'])} -> {f1(bp[C1]['kv_resident_gib'])} GiB")
            elif k.startswith("d4_agent_multiturn"):
                cause = ("reuse 시나리오에서 Baseline은 세션 고정 D가 History KV를 보유해 후속 턴에 D-local 증분 prefill만 하는 반면, 후보는 매 턴 전체 context를 풀에서 읽는다(D ingress)(DESIGN_NOTES A.11). B200은 prefill이 빨라 Baseline의 D-local 경로가 유리하고, "
                         "H100에서는 같은 구조가 반대로 나온다(5.2, Baseline seed 불안정). 한 시나리오 쌍의 진단이며 일반화하지 않는다")
                cls = "B/S (benchmark·시스템 의존, 구조 결함 단정 불가)"
                diag = (f"goodput B {f0(v[B]['max_goodput_tps'])} / C1 {f0(v[C1]['max_goodput_tps'])} (peak load x{v[B]['load']:g} / x{v[C1]['load']:g}); C1 ingress 점유 {pct(v[C1]['link_util_ingress'], 0)} (Baseline {pct(v[B]['link_util_ingress'], 0)}); 풀 상주 {f0(v[C1]['resid_gib']['pool'])} GiB")
            else:
                who = "C1" if vb[C1]["verdict"] == "loss" else "C2"
                ca = C1 if who == "C1" else C2
                cause = ("C1 메타데이터 서버 노드 손실 후 30 s 인덱스 재구성 동안 요청이 대기(SPOF)" if who == "C1" else "C2 락 보유 노드 장애에서 as-published 락이 풀리지 않아 stripe 고착")
                cls = "P (후보 구조의 장애 특성; 설계 결함이 아니라 문서화된 한계. 보완안: 스탠바이 / lease)"
                fk = RM["dp4_benchmark"]["failure"][k]
                diag = f"{who} goodput {xr(goodput_ratio(lab, k, ca), 3)}; 가용성 창 {'∞' if fk[ca]['window_s'] == float('inf') else f1(fk[ca]['window_s'])} s; 고착 요청 {f0(fk[ca]['n_incomplete_stuck'])}"
            rows.append(f"| `{k}` | {vb[C1]['verdict']} / {vb[C2]['verdict']} | {esc(cause)} | {esc(cls)} | {esc(diag)} |")
    L.append("\n".join(rows) + "\n")
    L.append("**Common Benchmark 6쌍 모두에서 TTFT P99(공통 load)가 Baseline보다 나쁘다**(꼬리 점검, SKILL §10): " + ", ".join(f"{sn.split('@')[1]} {sn.split('@')[0]} {xr(CBPS[sn][C1]['at_base_peak']['ttft_p99_ms'] / CBPS[sn][B]['at_base_peak']['ttft_p99_ms'], 2)}" for sn in sorted(CBPS)) + f". TPOT P99는 악화 쌍 {CBQ[C1]['tail_check_common_load']['tpot']['n_worse']}쌍. 이 꼬리 악화는 이득이 아니라 같은 data plane 원인(순차 read와 낮은 유효 대역)에서 오며 Baseline-regression loop를 돈 이유다.\n")
    tl = dp4_ttft_tail()
    L.append(f"**DP4-specific 행의 꼬리.** 장애 행을 뺀 {tl['n']}쌍에서 후보 TTFT P99(own-peak)는 Baseline의 x{tl['lo']:.3f}~x{tl['hi']:.3f}이고 1% 넘게 나쁜 쌍이 {tl['worse']}쌍, TTFT 판정이 loss인 쌍이 {tl['loss']}쌍이다. 중앙값 x{tl['med']:.3f}로 크기는 작지만 거의 모든 쌍에서 같은 방향이며, 순차 read가 TTFT에 노출된 효과다(goodput 판정은 tie라 쌍 판정은 tie). 이 방향성은 이득이 아니라 약한 비용으로 읽는다.\n")
    L.append("## 5.2 이득으로 판정된 쌍의 원인 (과대평가 점검)\n")
    L.append(f"'win' 판정은 {len(win_pairs())}쌍(C1 = C2)이며 **goodput이 95% CI 밖으로 좋아진 쌍은 {n_goodput_wins()}쌍**이다. 4쌍 모두 지연 등급 판정이다(`compare_pair`: QA2 별이 올라가고 TTFT 또는 TPOT 판정이 win).\n")
    rows = ["| 쌍 | goodput 판정 / 지연 등급 판정 | 같은 load 비교? | 원인 |", "|---|---|---|---|"]
    for lab, k in win_pairs():
        v = (CBPS if lab == "common_benchmark" else DPPS)[k]
        vb = (CBLAB if lab == "common_benchmark" else DPLAB)[k]["vs_baseline"][C1]
        same = v[B]["load"] == v[C1]["load"]
        if not same:
            why = (f"**own-peak 비교 효과**: goodput은 {vb['goodput']}({xr(goodput_ratio(lab, k, C1), 3)})이고 후보의 peak load(x{v[C1]['load']:g})가 Baseline(x{v[B]['load']:g})보다 낮아 own-peak TTFT P99가 {f0(v[B]['ttft_p99_ms'])} -> {f0(v[C1]['ttft_p99_ms'])} ms로 보일 뿐, "
                   f"Baseline peak load에서는 {f0(v[B]['at_base_peak']['ttft_p99_ms'])} -> {f0(v[C1]['at_base_peak']['ttft_p99_ms'])} ms로 후보가 더 느리다. 이득 근거로 쓰지 않는다")
        else:
            why = (f"같은 load(x{v[B]['load']:g})에서 TTFT P99 {f0(v[B]['ttft_p99_ms'])} -> {f0(v[C1]['ttft_p99_ms'])} ms, TPOT P99 {f1(v[B]['tpot_p99_ms'])} -> {f1(v[C1]['tpot_p99_ms'])} ms. goodput은 {xr(goodput_ratio(lab, k, C1), 2)}이나 {vb['goodput']}(쌍별 차이 95% CI ±{f0(vb['goodput_diff_ci95'])} tok/s): "
                   f"Baseline seed별 goodput {'/'.join(f0(x) for x in seed_list(k, B))} 대 C1 {'/'.join(f0(x) for x in seed_list(k, C1))}으로 Baseline이 일부 seed에서 붕괴(CV {pct(v[B]['goodput_cv'], 0)})해 생긴 차이다. 후보의 TTFT/TPOT가 seed 간 안정적이라는 신호는 있으나(후보 CV {pct(v[C1]['goodput_cv'], 0)}) 5 seed로는 확정할 수 없고 B200에서는 반대다")
        rows.append(f"| `{k}` | {vb['goodput']} / {vb['latency_class']} | {'예' if same else '아니오'} | {esc(why)} |")
    L.append("\n".join(rows) + "\n")
    L.append("## 5.3 QA별 '왜 이 값인가' 요약\n")
    qa1_pairs = ", ".join(f"{k.split('@')[1]} {k.split('@')[0].replace('cb_', '')} {xr(v, 2)}" for k, v in CBQ[C1]["qa1_per_scenario"].items())
    L.append(f"- **QA1 (x{c[C1]['qa1_r']:.3f}):** 쌍별 비 {qa1_pairs}. B200의 prefill이 빨라 링크가 병목이라 낮고, H100 CB-1/2는 거의 같으나 CB-3(혼합, 객체 수 증가)은 {xr(CBQ[C1]['qa1_per_scenario']['cb_mixed_8k_b32@H100'], 2)}.")
    L.append(f"- **QA2:** Baseline도 TTFT P99 최악 {f0(c[B]['tw'])} ms로 ★이다. 후보는 {f0(c[C1]['tw'])} ms(★). TPOT P99는 {f2(c[B]['o99'])} vs {f2(c[C1]['o99'])} ms로 거의 같다 — TPOT는 decode의 HBM 대역폭이 정하고 DP4는 decode 방식을 바꾸지 않기 때문이다(KV는 decode 시작 전에 HBM에 도착). TTFT는 KV 이동이 TTFT에 노출되는 경로라 영향을 받는다.")
    L.append(f"- **QA3:** 사전 등록 정의에서 후보가 Baseline peak load에서 포화해 P buffer에 쌓인 요청이 KV 상주를 키운다(P buffer {f1(c[C1]['comp']['p_buffer'])} vs {f1(c[B]['comp']['p_buffer'])} GiB). 풀 사본(평균 {f1(c[C1]['comp']['pool'])} GiB)은 후보 값의 작은 부분이다. 각 arm의 own-peak에서는 {f1(c[C1]['res_own'])} vs {f1(c[B]['res_own'])} GiB로 후보가 낮다. 정의 의존성은 0.3의 7번.")
    L.append("- **QA4:** 4.10. 신규 HW capability(S1)와 정책 교체(S3)는 두 후보 모두 module 1개, 객체 class(S2)와 topology(S4)는 shared module이 지배한다. 차이는 S4와 S1에서 C2의 module이 더 커서 생긴다.\n")
    L.append("## 5.4 사전 등록 예측(`simulation-plan.md` §10)과 결과\n")
    L.append("결과를 보기 전에 기록한 5개 예측을 결과로 채점한다. 예측을 고쳐 쓰지 않았다(H16).\n")
    rows = ["| 사전 예측 | 판정 | 근거 (데이터) |", "|---|---|---|"]
    for a, b_, d in predictions():
        rows.append(f"| {esc(a)} | {b_} | {esc(d)} |")
    L.append("\n".join(rows) + "\n")
    L.append("**맞지 않은 부분:** (i) 'saturated' 라벨 예측(위 1.) — Baseline과 후보의 data plane 차이 때문에 라벨이 comparison-valid가 되었다; (ii) '차이는 control plane이 지배하는 영역에서 나타난다'(위 2.) — 그런 영역을 만들어도 C1≈C2였다; (iii) '이득을 reuse 시나리오로 한정'(위 4.) — reuse 시나리오의 H100 이득은 통계적으로 확정되지 않았고(Baseline seed 붕괴) B200에서는 반대였다. 나머지 예측(C1≈C2, scan 비용과 SPOF/락 고착, QA4·장애에서의 trade-off)은 데이터로 확인되었다.\n")
    return "\n".join(L)


def sec6():
    q = final_cells()
    pq = PRE["common_benchmark"]["qa_feasible"][C1]
    _, diff = consistency()
    ql = qa4_boundary_lines()
    L = ["# 6. 한계\n"]
    items = [
        "**Evidence:** 사용자 환경에 CXL 공유 풀이 없어 **모든 성능 수치는 [B+C]이며 [A] 실측은 없다.** 입력은 두 논문(Beluga, TraCT)의 서버 2대·단일 벤더 장치 조건 측정이고, 8·16노드는 외삽이다. η_cxl, η_rdma, 중첩 비율, background 부하, lease는 ASSUMED이다.",
        f"**Baseline 대비 결론은 ASSUMED 상수에 의존한다.** 격차의 크기와 break-even(η_cxl* {SENS['break_even'][MERGED][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f})은 η_cxl(0.5)과 η_rdma(0.85) 두 ASSUMED 값의 비교다. 문헌값(PAPER)으로 확정된 효율은 없다. '이득 없음'은 이 가정 범위의 결과이며 CXL 풀이 일반적으로 이득이 없다는 주장이 아니다. 풀의 이득은 prefix 공유·reuse에서 기대하는 것이고 이 평가의 reuse 시나리오는 1개(`d4_agent_multiturn`)다.",
        "**C2의 락 관련 상수는 논문에 없는 ASSUMED**(scan 비용 t_probe, critical section 길이/수, stripe 수, 장애 처리)이다. C2의 절대 성능 주장은 하지 않으며, C2의 control-plane 지연·포화 rate는 이 가정에 의존한다. 락 보유 노드 장애의 보완안(lease)은 평가자의 가정이다. control-plane 파라미터 민감도는 Iteration 2 이후 재실행하지 않았고 수정 전 모델의 결과만 있다(4.8).",
        f"**Model checker는 추상 모델**이다. 실제 CPU·CXL 하드웨어 메모리 모델의 검증이 아니며 safety만 본다. 2노드 전수 탐색이 증거이고 3노드는 모든 변종이 탐색 상한에 걸려 불완전하다(4.9). 일부 2노드 결함 변종도 상한에 걸렸다. `C1_no_clflush_on_server` 결과는 stale slot-body 가정에 의존한다.",
        f"**QA4는 proxy 구현이다.** 실제 vLLM이 아니라 시뮬레이터 복사본에 변경을 구현해 diff를 센 것이고 공수·가격·배율은 가정이다. 두 후보의 차이는 M2 경계(0.5 MM)에서 C1 {pct(ql['c1_margin'])} 아래, C2 {pct(ql['c2_margin'])} 위로 근소하며 경계/집계/상수 변형 {len(qa4_variants())}가지 중 상당수에서 두 후보가 같은 별이 된다(0.3). **별 차이가 경계 선택에 의존한다**(H11 (d)). "
        + (f"QA4 측정에 쓴 시뮬레이터 소스 중 {', '.join(diff)}는 측정 이후 바뀌었다(Iteration 2: `simulator.py`의 move path). 재측정하지 않았다." if diff else ""),
        f"**QA4 집계(시나리오 평균)는 DP1 v2의 소유자 결정과 같은 규칙을 처음부터 등록한 것**이며(사후 변경 아님) 최악값 집계에서는 두 후보 모두 {Q4['qa4_stars_worst_case']['C1']}이다.",
        "**Scalability는 공식 QA가 아닌 제안**이다. 값만 보고하고 별점을 매기지 않았다. 값이 1을 넘는 것은 P 노드 대기열 풀링 효과이며 N=2 기준(단일 P 노드)이 대기열 한계라 해석에 주의.",
        f"**`qa_priority.json`은 {PRIO['status']}**이다. 선택(0.3)은 이 제안 우선순위와 무관하게 별 합계로 정해지지만(합계 6 대 5) 합계 차이는 QA4 한 칸이다.",
        f"**정의 이력(H16).** (i) Iteration 2에서 후보 move path를 순차 read로 수정했다(M). 수정 전→후: Common QA1 {xr(pq['qa1_ratio_geomean'], 3)} → {xr(q[C1]['qa1_r'], 3)}, QA3 절감 {xr(pq['qa3_saving_multiplier'], 3)} → {xr(q[C1]['save'], 3)}, 공통 load TTFT P99 악화 쌍 {pq['tail_check_common_load']['ttft']['n_worse']}/6 → {CBQ[C1]['tail_check_common_load']['ttft']['n_worse']}/6, 승/무/패 {'/'.join(map(str, tally_counts(C1, PRE)))} → {'/'.join(map(str, tally_counts(C1)))}. 별은 두 경우 모두 QA1 ★, QA2 ★, QA3 ★로 변하지 않았다(4.12). (ii) 평가 정의(QA1~QA3 경계, SLO, Baseline)는 결과를 본 뒤 바꾸지 않았다. (iii) QA3 정의는 DP1 경계를 가져온 임시 정의이며 DP4에서의 적정성은 검증되지 않았다.",
        f"**Common의 '압박' 정의는 임의적이다.** 링크 background load(0.85, 0.2→0.9)는 DP1의 HBM 용량 축소와 의미가 달라 DP 간 공통 별점 직접 비교에 한계가 있다. 압박을 0.5로 낮추면 QA1 ratio가 {f3(SENS['configs']['eta_cxl_bg']['eta0.5_bg0.5'][MERGED]['candidates'][C1]['qa1_ratio'])}, 0으로 낮추면 {f3(SENS['configs']['eta_cxl_bg']['eta0.5_bg0.0'][MERGED]['candidates'][C1]['qa1_ratio'])}이다(4.8).",
        "**QA3와 QA2의 load 의존성.** QA3(사전 등록: Baseline peak load, 같은 요청 구간)는 후보가 포화한 load에서 비교되어 값이 크게 나쁘다. own-peak 기준으로는 ★★ 구간이다(0.3의 7번). QA2의 별은 각 arm의 own-peak load 기준이라 후보 TTFT가 더 좋아 보이는 효과가 있으며 공통 load 행을 병기했다. 별 경계 하한 QA3 0.95는 Baseline 잡음 안에 있다(4.7).",
        "**시뮬레이터가 모델링하지 않는 것:** 실제 CXL 장치·CPU 캐시 동작, GPU↔CXL DMA 세부(scatter/gather는 평균 효율에 흡수), 풀 장치 bank 경합·인터리빙·스위치 혼잡(집계 BW 상한만), 락 매니저·서버 스레드의 CPU 스케줄링 간섭, 풀 장치 장애, HBM·풀 용량 한계, node-local 락 대기열, host DRAM tier, DP3 압축, KV 외 객체의 종류별 접근 패턴, 다중 테넌트. Baseline의 fragmentation 페널티는 의도적으로 넣지 않았다(강한 baseline).",
        f"**Fit 라벨과 승/무/패 해석:** DP4 행 대부분이 comparison-valid인 것은 Baseline과 후보 사이 data plane 차이 때문이며 C1과 C2의 차이가 아니다. `d4_node_scale_n2`는 reference 행인데 집계 쌍({len(RM['dp4_benchmark']['fit'])}쌍)에 포함되어 있다(DESIGN_NOTES A.5). Baseline의 `d4_agent_multiturn@H100` goodput CV가 {pct(DPPS['d4_agent_multiturn@H100'][B]['goodput_cv'], 0)}로 커서 그 이득의 정밀도는 낮다.",
        "**통합 파일 meta의 git dirty 플래그:** 통합 및 SYS-B200 실행은 dirty, SYS-H100 실행은 clean으로 기록되어 있다(1장). dirty는 `doc-mk/Evaluation/DP4` 아래의 미커밋 변경을 뜻하며 같은 `cluster_dp4.json`(sha1 일치)과 대조군 일치로 숫자의 동일성은 확인했으나 코드 revision 완전 일치는 아니다. 같은 명령 + 같은 revision에서 같은 숫자가 나오는지는 `test_sim.py`의 `test_same_seed_same_result`가 검증한다. ablation(`fb9ecab`)과 수정 전 결과(`0e44b58`)는 다른 revision에서 생성되었다.",
        "**미구현·미실시 항목:** 0.4의 보완 택틱 중 [C]로 표시한 것(W1 스탠바이 인계, W3 슬롯 검증값, W4 partial read·청크 publish·하이브리드, W5, W6)은 구현하지 않았고 효과를 측정하지 않았다. [B]는 이미 시뮬레이터에 있는 기능(프로세스 재시작, 서버 스레드, block 크기)의 측정이다. QA4 재측정, 서버 2대 초과·실제 CXL 풀 측정, `d4_agent_multiturn`의 seed 추가, control-plane 민감도의 재실행, N >= 3 model check의 전수 탐색도 미실시다.",
        "**H17(모델 오차 sweep)은 해당 없음**(estimator 비의존). **DP1의 H10 profile 규칙**: 기존 profile은 수정하지 않았고 DP4 profile을 신규 추가했다.",
    ]
    for i, t in enumerate(items, 1):
        L.append(f"{i}. {t}")
    L.append("")
    return "\n".join(L)


def sec7():
    o = selection()
    c = final_cells()
    be = SENS["break_even"]
    ql = qa4_boundary_lines()
    dt, kept, tied = decision_table()
    agent = {k.split("@")[1]: goodput_ratio("dp4_benchmark", k, C1) for k in DPPS if k.startswith("d4_agent_multiturn")}
    L = ["# 7. 결론\n"]
    L.append(f"- **결정 관련 진술 (1): Baseline 대비.** **under the tested conditions the architecture shows no benefit over the baseline** — CXL 공유 풀 data plane은 C1과 C2 모두에서 Baseline-RDMA보다 QA1 {xr(c[C1]['qa1_r'], 3)}(★), QA3 절감 {xr(c[C1]['save'])}(★), 공통 load TTFT P99 {xr(c[C1]['ct99'] / c[B]['ct99'])}로 낮다. Baseline-regression loop를 2회 수행(iteration 0 기준, 1 진단 sweep, 2 모델 수정)했고 후보는 Baseline 미만으로 남아 로그의 사전 등록 규칙에 따라 중단했다. "
             f"시도한 변경: Iteration 1(η_cxl x 배경 부하 등 민감도, 변경 없음), Iteration 2(순차 read 수정). **break-even η_cxl*는 QA1 parity {be[MERGED][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f}(H100 {be['SYS-H100'][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f}, B200 {be['SYS-B200'][C1]['bg0.85']['qa1_ratio_parity']['x']:.3f}), QA1 >= 1.00 {be[MERGED][C1]['bg0.85']['qa1_ratio_ge_1']['x']:.3f}, QA3 절감 {be[MERGED][C1]['bg0.85']['qa3_multiplier_parity']['x']:.3f}**(bg 0.85 기준; bg 0.5에서는 QA1 parity {be[MERGED][C1]['bg0.5']['qa1_ratio_parity']['x']:.3f}, QA3는 격자 내 없음)이며 **둘 다 ASSUMED 상수(η_cxl 대 η_rdma)의 비교**라 어느 쪽이 맞는지 이 평가로는 모른다. 대역폭 동등점은 {SENS['meta']['eta_bw_parity']:.3f}이다. 이 문서가 skill §5의 escalation이다: 사용자 판단이 필요한 것은 η_cxl/η_rdma의 확정(실측 또는 문헌)이다.")
    L.append(f"- **결정 관련 진술 (2): C1 대 C2.** 선택 질문은 control plane 책임(중앙 직렬화 vs 분산 락)이다. QA1~QA3에서는 구분되지 않고(차이 {pct(max(agg_dev_c1_c2()[0].values()), 3)} 이하) 별 차이는 QA4에서만 나온다: C1 {Q4_STARS[C1]} 대 C2 {Q4_STARS[C2]}, 합계 {o['totals'][C1]} 대 {o['totals'][C2]}. 이 차이는 M2 경계(0.5 MM) 근처({ql['c1']:.3f} 대 {ql['c2']:.3f})이고 변형 {len(dt)}가지 중 {tied}가지에서 동점이 된다. **제안 우선순위(proposal)** 기준 선택은 **C1**이나 **약한 선택**이다. "
             "그 밖의 차이는 별점 밖에 있다: C1은 서버 SPOF, C2는 락 고착과 scan 비용(S x N)이라는 서로 다른 장애·확장 특성이며 정상 프로토콜의 정확성은 2노드 전수 모델 검사에서 둘 다 문제가 없었다. C1·C2의 QA1~QA3 격차 대 Baseline은 데이터 plane 상수에서 오며 일관성 구조 선택으로 줄일 수 없다.")
    L.append(f"- **이득이 존재하는 조건 / 존재하지 않는 조건.** goodput이 95% CI 밖으로 좋아진 쌍은 **{n_goodput_wins()}쌍**이다(N_win = {n_goodput_wins()} < 3). 'win' {len(win_pairs())}쌍은 모두 지연 등급 판정이며, 이득의 단서는 `d4_agent_multiturn`(8턴 에이전트, History KV 재사용)의 H100 한 쌍(같은 load에서 TTFT P99 {f0(DPPS['d4_agent_multiturn@H100'][B]['ttft_p99_ms'])} -> {f0(DPPS['d4_agent_multiturn@H100'][C1]['ttft_p99_ms'])} ms; goodput {xr(agent['H100'], 2)}이나 Baseline seed 일부 붕괴로 CV {pct(DPPS['d4_agent_multiturn@H100'][B]['goodput_cv'], 0)}, 판정 tie)뿐이며 같은 시나리오가 B200에서는 {xr(agent['B200'], 2)}로 손해다. Common CB-1/2의 H100 'win'은 own-peak 지연 등급 판정이며 같은 load에서는 후보가 느리다. 이득이 없는 조건: 링크 압박이 큰 모든 Common 쌍(특히 B200), 장애 시 C1(노드 손실)과 C2(as-published). 압박이 없고(bg 0) η_cxl >= {be[MERGED][C1]['bg0.5']['qa1_ratio_parity']['x']:.2f} 근처의 가정이면 QA1이 Baseline에 근접한다(민감도, main 아님).")
    L.append("- **다음 단계(사용자 결정 필요).** (1) **η_cxl, η_rdma, background 부하**를 실측 또는 문헌으로 확정한다(현재 결론의 핵심 가정). (2) 풀의 이득이 있다고 기대하는 prefix 공유·reuse 시나리오를 늘린다(현재 1개; 후보 구조 변경이 아니라 시나리오 추가, 실패한 것도 유지). (3) 보완 설계 W4(partial read, 청크 publish, 하이브리드 경로)를 새 iteration으로 사전 등록해 구현·측정한다(P class). (4) QA4를 Iteration 2 이후 소스에서 재측정하고 가능하면 실제 vLLM 통합에서 측정한다. (5) `qa_priority.json`(proposal)과 Scalability QA 추가 여부를 확정한다. (6) 정확성: N >= 3 노드 검증은 탐색 상한 때문에 미완이며 stale slot-body 가정의 논문 확인이 필요하다.")
    L.append("- **선택 질문과 별점 차이의 위치(재확인).** DP4의 선택 질문은 C1 대 C2이며, C1-대-C2 별 차이는 **QA4에서만** 나오고 0.5 MM 경계 근처이며, QA1~QA3의 Baseline 격차는 **data plane 상수**가 정하고 coherence 구조가 정하지 않는다.\n")
    L.append("---\n")
    return "\n".join(L)


def front_matter():
    return ("---\n"
            f"date: {DATE}\n"
            "dp: DP4\n"
            "candidates: [C1-central-serialization, C2-distributed-lock]   # Baseline-RDMA 포함\n"
            "sys_ids: [SYS-H100, SYS-B200]   # 통합 INT-H100-B200\n"
            f"git_rev: {META['git']['revision']} (dirty flags as recorded in data meta: INT {'dirty' if META['git']['dirty'] else 'clean'}, SYS-H100 {'dirty' if META['source_git']['SYS-H100']['dirty'] else 'clean'}, SYS-B200 {'dirty' if META['source_git']['SYS-B200']['dirty'] else 'clean'})\n"
            "evidence: { QA1: \"[B+C]\", QA2: \"[B+C]\", QA3: \"[B+C]\", QA4: \"[B+C]\", protocol_check: \"[C]\" }\n"
            "status: draft\n"
            "---\n")


def build():
    parts = [front_matter(),
             "# DP4 QA Evaluation — C1 중앙 직렬화 vs C2 분산 락 (비일관 CXL 공유 메모리 KV 일관성 구조)\n",
             "> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`DP4/benchmark.md`](../benchmark.md), [`DP4/simulation-plan.md`](../simulation-plan.md), [`qa-criteria-dp4.md`](../qa-criteria-dp4.md), [`qa4-preregistration.md`](../qa4-preregistration.md)\n"
             "> 절차: `.claude/skills/evaluation/SKILL.md`. 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다(CXL 공유 풀 하드웨어 없음). model check는 [C]. 이 문서는 `tools/gen_dp4_result.py`가 `results/data/`에서 생성했다(같은 데이터에서 두 번 돌리면 같은 출력).\n",
             sec0(), sec1(), sec2(), sec3(), sec4(), sec5(), sec6(), sec7()]
    return "\n".join(parts).rstrip() + "\n"


def main():
    txt = build()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text() == txt else 1)
    OUT.write_text(txt)
    print(f"wrote {OUT} ({len(txt):,} chars)")


if __name__ == "__main__":
    main()
