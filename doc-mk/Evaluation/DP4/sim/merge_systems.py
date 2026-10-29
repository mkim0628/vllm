"""Merge per-system qa_result.json files into ONE integrated result ((scenario, system) pairs are the unit).

    uv run --no-project python merge_systems.py SYS-H100 SYS-B200   # -> ../results/data/INT-H100-B200/qa_result.json
    uv run --no-project python merge_systems.py SYS-H100 SYS-B200 --data-dir ../results/data/ablation/C2-no-scan  (tagged inputs)

Same rule as DP1/sim/merge_systems.py: every pair is labelled and aggregated like a single-system run; QA1 = geometric
mean of ratios over valid pairs; per-system results stay available for consistency checks.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

import qa_eval as q
from arms import BASE, C1, C2

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data"
SETS = ("common_benchmark", "dp4_benchmark")


def merge(systems, data_dir=DATA, cands=None):
    src = {s: json.loads((data_dir / s / "qa_result.json").read_text()) for s in systems}
    return merge_src(src, systems, cands)


def merge_src(src, systems, cands=None):
    cands = tuple(cands or src[systems[0]]["meta"]["candidates"])
    result, all_ps, all_lab = {}, {}, {}
    for label in SETS:
        ps, extra = {}, {"c1_vs_c2": {}, "failure": {}, "cp_capacity": {}, "briefs": {}, "exposes": {}}
        for s in systems:
            d = src[s][label]
            for sn, v in d["per_scenario"].items():
                ps[f"{sn}@{s[4:]}"] = v
            for key in ("c1_vs_c2", "failure", "cp_capacity"):
                for sn, v in d.get(key, {}).items():
                    extra[key][f"{sn}@{s[4:]}"] = v
            extra["briefs"].update(d["briefs"])
            extra["exposes"].update(d["exposes"])
        lab = q.label_scenarios(ps, cands)
        feasible = [k for k, l in lab.items() if l["fit"] != "infeasible"]
        discr = [k for k, l in lab.items() if l["fit"] == "comparison_valid"]
        result[label] = dict(
            per_scenario=ps, qa=q.qa_table(ps, None, cands), qa_feasible=q.qa_table(ps, feasible, cands),
            qa_discriminating=q.qa_table(ps, discr, cands) if discr else {}, fit={k: l["fit"] for k, l in lab.items()},
            scenario_labels=lab, tally={c: q.tally(lab, c) for c in cands[1:]}, **extra)
        if label == "dp4_benchmark":
            eff = {}
            for a in cands:
                eff[a] = {}
                for n in ("4", "8", "16"):
                    vals = [src[s][label]["scaling_efficiency"][a][n] for s in systems if src[s][label].get("scaling_efficiency", {}).get(a, {}).get(n)]
                    eff[a][n] = q.geomean(vals) if vals else None
                eff[a]["per_system"] = {s: {n: src[s][label]["scaling_efficiency"][a][n] for n in ("4", "8", "16")} for s in systems}
                eff[a]["note"] = "geometric mean over systems; proposal metric, not an official QA; no stars (H11)"
            result[label]["scaling_efficiency"] = eff
        all_ps.update({f"{label}/{k}": v for k, v in ps.items()})
        all_lab.update({f"{label}/{k}": v for k, v in lab.items()})
    feas = [k for k, l in all_lab.items() if l["fit"] != "infeasible"]
    disc = [k for k, l in all_lab.items() if l["fit"] == "comparison_valid"]
    result["combined"] = dict(
        scope="integrated over systems " + ", ".join(systems) + "; unit = (scenario, system) pair",
        n_feasible=len(feas), n_discriminating=len(disc),
        qa_feasible=q.qa_table(all_ps, feas, cands) if feas else {}, qa_discriminating=q.qa_table(all_ps, disc, cands) if disc else {},
        tally={c: q.tally(all_lab, c) for c in cands[1:]})
    m = src[systems[0]]["meta"]
    result["meta"] = dict(system="INT-" + "-".join(s[4:] for s in systems), systems=list(systems), seeds=m["seeds"], loads=m["loads"],
                          max_load=m["max_load"], t95=m["t95"], material_rel=m["material_rel"], evidence=m["evidence"], sets=list(SETS),
                          candidates=list(cands), qa_definitions=m["qa_definitions"], config=m["config"], config_sha1=m["config_sha1"],
                          source_git={s: src[s]["meta"]["git"] for s in systems}, source_commands={s: src[s]["meta"]["command"] for s in systems},
                          git=q.git_info(), command="python merge_systems.py " + " ".join(systems))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("systems", nargs="*", default=["SYS-H100", "SYS-B200"])
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--out-dir", type=Path, default=None)
    a = ap.parse_args()
    res = merge(a.systems, a.data_dir)
    out = a.out_dir or (a.data_dir / res["meta"]["system"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "qa_result.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print("wrote", out / "qa_result.json", "n_feasible", res["combined"]["n_feasible"], "n_valid", res["combined"]["n_discriminating"])
