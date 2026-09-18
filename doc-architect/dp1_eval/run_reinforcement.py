from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from model import load_system
from scenarios import scenarios
from simulator import run_sim
from qa_utils import best_sustainable_rows, p99_slo_feasible

SEEDS=[11,23,37,51,71]
LOAD_SCALES=(0.25,0.50,0.75,1.00,1.25)
CANDIDATES=(
    "As-Is-HBM-first",
    "C1-memory-centric",
    "C1-R-stable-resource",
    "C2-data-centric",
    "C2-R-feasibility-stable",
)
ROBUSTNESS={
    "classifier_error",
    "kv_mispredict_dram_wait",
    "six_tier_capacity_stress",
}

def ci95(vals):
    if not vals: return [0.0,0.0]
    if len(vals)<2: return [vals[0],vals[0]]
    m=statistics.mean(vals)
    h=1.96*statistics.stdev(vals)/math.sqrt(len(vals))
    return [m-h,m+h]

def geom_mean(vals):
    xs=[max(1e-9,x) for x in vals]
    return math.exp(sum(math.log(x) for x in xs)/len(xs)) if xs else 0.0

def stars(n):
    return "★"*n+"☆"*(3-n)

def star_goodput(ratio,ci):
    lo,hi=ci
    if ratio>=1.10 and lo>=1.0: return 3
    if ratio<.90 and hi<1.0: return 1
    return 2

def star_latency_ttft(ms):
    return 3 if ms<=2000 else 2 if ms<=4000 else 1

def star_latency_tpot(ms):
    return 3 if ms<=25 else 2 if ms<=50 else 1

def star_resource(x):
    return 3 if x>=.85 else 2 if x>=.65 else 1

def normal_names():
    return {s.name for s in scenarios() if s.name not in ROBUSTNESS}

def heavy_names():
    return {s.name for s in scenarios()
            if s.name not in ROBUSTNESS and (s.batch_size>=64 or s.context_tokens>=131072)}

def best_rows(rows,candidate,names):
    return best_sustainable_rows(rows,candidate,names)

def ratio_vs_as_is(rows,candidate,names):
    base=best_rows(rows,"As-Is-HBM-first",names)
    cand=best_rows(rows,candidate,names)
    vals=[]; infeasible=[]; extension=[]
    for k,b in base.items():
        c=cand.get(k)
        if c is None:
            vals.append(0.0)
            infeasible.append(k)
        else:
            vals.append(c["slo_goodput"]/max(1e-9,b["slo_goodput"]))
    for k in cand:
        if k not in base:
            extension.append(k)
    if not vals:
        return 0.0,[0.0,0.0],infeasible,extension
    logs=[math.log(max(1e-9,x)) for x in vals]
    lci=ci95(logs)
    return geom_mean(vals),[math.exp(lci[0]),math.exp(lci[1])],infeasible,extension

def aggregate(rows,candidate):
    normal=normal_names(); heavy=heavy_names()
    nominal=[r for r in rows
             if r["candidate"]==candidate and r["scenario"] in normal
             and abs(r["load_scale"]-1.0)<1e-9]

    ratio,ratio_ci,infeasible,extension=ratio_vs_as_is(rows,candidate,heavy)

    maps={c:best_rows(rows,c,normal) for c in CANDIDATES}
    all_keys=set().union(*(x.keys() for x in maps.values()))
    feasible={
        k for k in all_keys
        if any(maps[c].get(k,{}).get("slo_goodput",0)>0 for c in CANDIDATES)
    }
    lat=[maps[candidate][k] for k in feasible if k in maps[candidate]]
    ttft=max((r["ttft_p99_ms"] for r in lat),default=0.0)
    tpot=max((r["tpot_p99_ms"] for r in lat),default=0.0)
    rui=statistics.mean(r["resource_index"] for r in nominal)

    return {
        "goodput_ratio_vs_as_is_heavy":ratio,
        "goodput_ratio_ci95":ratio_ci,
        "infeasible_heavy_cells":len(infeasible),
        "feasibility_extension_heavy_cells":len(extension),
        "token_throughput_mean":statistics.mean(r["token_throughput"] for r in nominal),
        "slo_goodput_mean":statistics.mean(r["slo_goodput"] for r in nominal),
        "ttft_p99_worst_scored_ms":ttft,
        "tpot_p99_worst_scored_ms":tpot,
        "resource_utilization_index":rui,
        "hbm_pressure_violation_rate":statistics.mean(r["hbm_pressure_violation_rate"] for r in nominal),
        "bw_saturation_rate":statistics.mean(r["bw_saturation_rate"] for r in nominal),
        "migration_count_mean":statistics.mean(r["migration_count"] for r in nominal),
        "fallback_count_mean":statistics.mean(r.get("fallback_count",0) for r in nominal),
        "deferred_stage_count_mean":statistics.mean(r.get("deferred_stage_count",0) for r in nominal),
        "deferred_promotion_count_mean":statistics.mean(r.get("deferred_promotion_count",0) for r in nominal),
        "suppressed_migrations_mean":statistics.mean(r.get("suppressed_migrations",0) for r in nominal),
        "feasibility_filtered_mean":statistics.mean(r.get("feasibility_filtered",0) for r in nominal),
        "infeasible_stable_hold_mean":statistics.mean(r.get("infeasible_stable_hold",0) for r in nominal),
        "decision_us_avg":statistics.mean(r["decision_us_avg"] for r in nominal),
        "stars":{
            "throughput":star_goodput(ratio,ratio_ci),
            "ttft":star_latency_ttft(ttft),
            "tpot":star_latency_tpot(tpot),
            "resource":star_resource(rui),
        },
    }

def fallback_reasons(rows,candidate):
    c=Counter()
    for r in rows:
        if r["candidate"]==candidate:
            c.update(r.get("fallback_reason",{}))
    return dict(c)

def scenario_delta(rows):
    out=[]
    for sc in scenarios():
        maps={c:best_rows(rows,c,{sc.name}) for c in CANDIDATES}
        keys=sorted(maps["As-Is-HBM-first"])
        vals={}
        for c in CANDIDATES:
            rs=[]
            for k in keys:
                b=maps["As-Is-HBM-first"][k]
                x=maps[c][k]
                if b["slo_goodput"]<=0 and x["slo_goodput"]<=0:
                    continue
                rs.append(10.0 if b["slo_goodput"]<=0<x["slo_goodput"]
                          else x["slo_goodput"]/max(1e-9,b["slo_goodput"]))
            vals[c]=geom_mean(rs) if rs else None
        out.append({
            "scenario":sc.name,
            "batch":sc.batch_size,
            "context":sc.context_tokens,
            "role":"robustness" if sc.name in ROBUSTNESS else "QA-score",
            "as_is":vals["As-Is-HBM-first"],
            "c1":vals["C1-memory-centric"],
            "c1r":vals["C1-R-stable-resource"],
            "c2":vals["C2-data-centric"],
            "c2r":vals["C2-R-feasibility-stable"],
        })
    return out

def pct_change(new,old):
    return 100*(new-old)/old if old else 0.0

def write_report(path,summary):
    a=summary["aggregate"]
    c1=a["C1-memory-centric"]; c1r=a["C1-R-stable-resource"]
    c2=a["C2-data-centric"]; c2r=a["C2-R-feasibility-stable"]

    h1={
      "goodput_preserved": c1r["goodput_ratio_vs_as_is_heavy"] >= .95*c1["goodput_ratio_vs_as_is_heavy"],
      "migration_reduced_20pct": c1r["migration_count_mean"] <= .80*c1["migration_count_mean"],
      "rui_not_lower": c1r["resource_utilization_index"] >= c1["resource_utilization_index"]-.01,
    }
    h2={
      "fallback_le_20": c2r["fallback_count_mean"] <= 20,
      "migration_le_24": c2r["migration_count_mean"] <= 24,
      "goodput_ge_095": c2r["goodput_ratio_vs_as_is_heavy"] >= .95,
      "rui_ge_078": c2r["resource_utilization_index"] >= .78,
    }
    summary["acceptance"]={"C1-R":h1,"C2-R":h2}

    lines=[
      "# DP1 Reinforcement Evaluation — C1/C2 Before vs After",
      "",
      "> Baseline C1/C2는 수정하지 않고, C1-R/C2-R을 별도 후보로 추가해 동일 trace에서 재평가한다.",
      "",
      "## 1. Aggregate Before / After","",
      "| Metric | C1 | C1-R | C2 | C2-R |",
      "|---|---:|---:|---:|---:|",
    ]
    rowspec=[
      ("Heavy Goodput / As-Is","goodput_ratio_vs_as_is_heavy"),
      ("Mean SLO Goodput [tok/s]","slo_goodput_mean"),
      ("Resource Utilization Index","resource_utilization_index"),
      ("HBM pressure violation","hbm_pressure_violation_rate"),
      ("BW saturation","bw_saturation_rate"),
      ("Migration / run","migration_count_mean"),
      ("Fallback / run","fallback_count_mean"),
      ("Suppressed migration / run","suppressed_migrations_mean"),
      ("Feasibility-filtered candidates / run","feasibility_filtered_mean"),
      ("Stable infeasible hold / run","infeasible_stable_hold_mean"),
      ("Decision proxy [us]","decision_us_avg"),
    ]
    for label,key in rowspec:
        lines.append(
          f"| {label} | {c1[key]:.4f} | {c1r[key]:.4f} | {c2[key]:.4f} | {c2r[key]:.4f} |")

    lines += [
      "","## 2. QA Star View","",
      "| QA | C1 | C1-R | C2 | C2-R |",
      "|---|:---:|:---:|:---:|:---:|",
    ]
    for key,label in [("throughput","Throughput"),("ttft","Latency — TTFT"),
                      ("tpot","Latency — TPOT"),("resource","Resource Utilization")]:
        lines.append(
          f"| {label} | {stars(c1['stars'][key])} | {stars(c1r['stars'][key])} | {stars(c2['stars'][key])} | {stars(c2r['stars'][key])} |")

    lines += [
      "","## 3. Improvement Delta","",
      f"- C1-R migration change: **{pct_change(c1r['migration_count_mean'],c1['migration_count_mean']):+.1f}%**",
      f"- C1-R heavy-goodput change: **{pct_change(c1r['goodput_ratio_vs_as_is_heavy'],c1['goodput_ratio_vs_as_is_heavy']):+.1f}%**",
      f"- C2-R fallback change: **{pct_change(c2r['fallback_count_mean'],c2['fallback_count_mean']):+.1f}%**",
      f"- C2-R migration change: **{pct_change(c2r['migration_count_mean'],c2['migration_count_mean']):+.1f}%**",
      f"- C2-R heavy-goodput change: **{pct_change(c2r['goodput_ratio_vs_as_is_heavy'],c2['goodput_ratio_vs_as_is_heavy']):+.1f}%**",
      "",
      "## 4. Acceptance Check","",
      "### C1-R",
    ]
    for k,v in h1.items():
        lines.append(f"- {'PASS' if v else 'FAIL'} — `{k}`")
    lines.append("")
    lines.append("### C2-R")
    for k,v in h2.items():
        lines.append(f"- {'PASS' if v else 'FAIL'} — `{k}`")

    lines += [
      "","## 5. Fallback Reason Before / After","",
      "### C2 baseline","",
    ]
    for k,v in sorted(summary["fallback_reasons"]["C2-data-centric"].items(),key=lambda x:-x[1]):
        lines.append(f"- `{k}`: {v:,}")
    lines += ["","### C2-R",""]
    for k,v in sorted(summary["fallback_reasons"]["C2-R-feasibility-stable"].items(),key=lambda x:-x[1]):
        lines.append(f"- `{k}`: {v:,}")

    lines += [
      "","## 6. Scenario-level Goodput / As-Is","",
      "| Scenario | B | Ctx | C1 | C1-R | C2 | C2-R |",
      "|---|---:|---:|---:|---:|---:|---:|",
    ]
    def fmt(v): return "N/A" if v is None else f"{v:.3f}"
    for x in summary["scenario_delta"]:
        lines.append(
          f"| `{x['scenario']}` | {x['batch']} | {x['context']//1024}K | "
          f"{fmt(x['c1'])} | {fmt(x['c1r'])} | {fmt(x['c2'])} | {fmt(x['c2r'])} |")

    lines += [
      "","## 7. Interpretation Rule","",
      "- C1-R의 개선이 작더라도 migration을 줄이면서 성능을 유지하면 Resource-centric 설계의 안정성 강화로 본다.",
      "- C2-R은 fallback/migration 감소가 핵심이다. Goodput이 회복되지 않으면 Data-aware prediction보다 cost model 또는 workload model의 추가 수정이 필요하다.",
      "- 보완 결과가 좋더라도 baseline 문서를 덮어쓰지 않는다. 최초 trade-off와 개선 효과를 분리해 보존한다.",
    ]
    path.write_text("\n".join(lines).replace("`","`"),encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config-dir",type=Path,default=Path(__file__).resolve().parents[1]/"configs")
    ap.add_argument("--output-dir",type=Path,default=Path(__file__).resolve().parent/"out_reinforcement")
    args=ap.parse_args()

    system=load_system(args.config_dir)
    out=args.output_dir
    out.mkdir(parents=True,exist_ok=True)

    rows=[]
    for sc in scenarios():
        for seed in SEEDS:
            for candidate in CANDIDATES:
                for load in LOAD_SCALES:
                    rows.append(run_sim(system,sc,seed,candidate,load))

    special={"placement_decisions","class_tier","fallback_reason"}
    fields=[k for k in rows[0] if k not in special]+[
      "placement_decisions_json","class_tier_json","fallback_reason_json"]
    with (out/"reinforcement_runs.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for r in rows:
            x={k:v for k,v in r.items() if k not in special}
            x["placement_decisions_json"]=json.dumps(r["placement_decisions"],sort_keys=True)
            x["class_tier_json"]=json.dumps(r["class_tier"],sort_keys=True)
            x["fallback_reason_json"]=json.dumps(r.get("fallback_reason",{}),sort_keys=True)
            w.writerow(x)

    summary={
      "meta":{
        "seeds":SEEDS,
        "load_scales":LOAD_SCALES,
        "scenario_count":len(scenarios()),
        "candidates":CANDIDATES,
      },
      "aggregate":{c:aggregate(rows,c) for c in CANDIDATES},
      "fallback_reasons":{c:fallback_reasons(rows,c) for c in CANDIDATES if c.startswith("C2")},
      "scenario_delta":scenario_delta(rows),
    }
    write_report(out/"dp1-reinforcement-evaluation.md",summary)
    (out/"reinforcement_summary.json").write_text(
      json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(summary["aggregate"],indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
