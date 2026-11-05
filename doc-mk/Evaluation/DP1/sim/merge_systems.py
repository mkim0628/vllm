"""Merge per-system qa_result.json files into ONE integrated result (scenario x system pairs become the unit).

    python merge_systems.py SYS-H100 SYS-B200            # -> ../results/data/INT-H100-B200/qa_result.json
    python dp1_rating.py ../results/data/INT-H100-B200/qa_result.json

Every (scenario, system) pair is labelled (comparison-valid / saturated / infeasible) and aggregated exactly like a
single-system run; QA1 = geometric mean of ratios over valid pairs, etc. Per-system results stay available for
consistency checks. Owner decision 2026-10-03: the summary reports the integrated result, not a per-system matrix.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import qa_eval as q

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data"
SETS = ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark")


def merge(systems, root=DATA):
    src = {s: json.loads((root / s / "qa_result.json").read_text()) for s in systems}
    result, all_ps, all_lab = {}, {}, {}
    for label in SETS:
        ps = {}
        for s in systems:
            for sn, v in src[s][label]["per_scenario"].items():
                ps[f"{sn}@{s[4:]}"] = v
        lab = q.label_scenarios(ps)
        feasible = [k for k, l in lab.items() if l["fit"] != "infeasible"]
        discr = [k for k, l in lab.items() if l["fit"] == "comparison_valid"]
        result[label] = dict(
            per_scenario=ps, qa=q.qa_table(ps), qa_feasible=q.qa_table(ps, feasible), qa_discriminating=q.qa_table(ps, discr),
            fit={k: l["fit"] for k, l in lab.items()}, scenario_labels=lab,
            tally={c: q.tally(lab, c) for c in q.CANDS[1:]})
        all_ps.update({f"{label}/{k}": v for k, v in ps.items()})
        all_lab.update({f"{label}/{k}": v for k, v in lab.items()})
    feas = [k for k, l in all_lab.items() if l["fit"] != "infeasible"]
    disc = [k for k, l in all_lab.items() if l["fit"] == "comparison_valid"]
    result["combined"] = dict(
        scope="integrated over systems " + ", ".join(systems) + "; unit = (scenario, system) pair",
        n_feasible=len(feas), n_discriminating=len(disc),
        qa_feasible=q.qa_table(all_ps, feas) if feas else {}, qa_discriminating=q.qa_table(all_ps, disc) if disc else {},
        tally={c: q.tally(all_lab, c) for c in q.CANDS[1:]})
    m = src[systems[0]]["meta"]
    result["meta"] = dict(system="INT-" + "-".join(s[4:] for s in systems), systems=list(systems), seeds=m["seeds"], loads=m["loads"],
                          t95=m["t95"], material_rel=m["material_rel"], evidence=m["evidence"], sets=list(SETS))
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    root = DATA
    if "--tag" in args:
        i = args.index("--tag"); root = DATA / args[i + 1]; del args[i:i + 2]
    systems = args or ["SYS-H100", "SYS-B200"]
    res = merge(systems, root)
    out = root / res["meta"]["system"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "qa_result.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print("wrote", out / "qa_result.json", "n_feasible", res["combined"]["n_feasible"], "n_valid", res["combined"]["n_discriminating"])
