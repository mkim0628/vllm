from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from model import load_system
from scenarios import scenarios
from simulator import run_sim

SEEDS=[11,23,37,51,71]
LOAD_SCALES=(0.25,0.50,0.75,1.00,1.25)
CANDIDATES=(
    "As-Is-HBM-first",
    "C1-memory-centric",
    "C1-R-stable-resource",
    "C1-R2-emergency-resource",
    "C2-data-centric",
    "C2-R-feasibility-stable",
    "C2-R2-path-aware",
)

ROBUSTNESS={"classifier_error","six_tier_capacity_stress"}

DOMAINS={
    "neutral_hbm_fit":{"kv_b16_c32k","rag_1tib_b16","tool_result_bursty"},
    "c1_resource_pressure":{
        "hbm_pressure_ramp_b64","hbm_bw_shock_b256","host_path_pressure_b64",
        "data_mix_shift_b64","mixed_all_ai_data_b64",
    },
    "c2_data_near":{
        "rag_8tib_b64_ssd_pim","rag_8tib_b256_ssd_pim",
        "kv_b16_c32k_burst_chbm","kv_b1_c32k_cold_cxl",
    },
    "c2_data_lifecycle":{"kv_mispredict_dram_wait","agent_memory_long_lived"},
}

def geom(vals):
    vals=[max(1e-9,v) for v in vals]
    return math.exp(sum(math.log(v) for v in vals)/len(vals)) if vals else None

def ci95_log(vals):
    if not vals: return None
    logs=[math.log(max(1e-9,x)) for x in vals]
    if len(logs)==1:
        return [vals[0],vals[0]]
    m=statistics.mean(logs)
    h=1.96*statistics.stdev(logs)/math.sqrt(len(logs))
    return [math.exp(m-h),math.exp(m+h)]

def best_rows(rows,candidate,names):
    best={}
    for r in rows:
        if r["candidate"]!=candidate or r["scenario"] not in names:
            continue
        k=(r["scenario"],r["seed"])
        if k not in best or r["slo_goodput"]>best[k]["slo_goodput"]:
            best[k]=r
    return best

def ratios(rows,candidate,names):
    b=best_rows(rows,"As-Is-HBM-first",names)
    c=best_rows(rows,candidate,names)
    out=[]
    for k,br in b.items():
        cr=c[k]
        if br["slo_goodput"]<=0 and cr["slo_goodput"]<=0:
            continue
        if br["slo_goodput"]<=0<cr["slo_goodput"]:
            out.append(10.0)
        else:
            out.append(cr["slo_goodput"]/max(1e-9,br["slo_goodput"]))
    return out

def aggregate(rows,candidate):
    normal={s.name for s in scenarios() if s.name not in ROBUSTNESS}
    heavy={s.name for s in scenarios()
           if s.name not in ROBUSTNESS and (s.batch_size>=64 or s.context_tokens>=131072)}
    nominal=[r for r in rows if r["candidate"]==candidate and r["scenario"] in normal
             and abs(r["load_scale"]-1.0)<1e-9]
    rr=ratios(rows,candidate,heavy)
    return {
        "heavy_goodput_ratio_vs_as_is":geom(rr),
        "heavy_goodput_ci95":ci95_log(rr),
        "mean_slo_goodput":statistics.mean(r["slo_goodput"] for r in nominal),
        "mean_token_throughput":statistics.mean(r["token_throughput"] for r in nominal),
        "resource_index":statistics.mean(r["resource_index"] for r in nominal),
        "hbm_pressure_violation":statistics.mean(r["hbm_pressure_violation_rate"] for r in nominal),
        "bw_saturation":statistics.mean(r["bw_saturation_rate"] for r in nominal),
        "migration_count":statistics.mean(r["migration_count"] for r in nominal),
        "fallback_count":statistics.mean(r.get("fallback_count",0) for r in nominal),
        "degraded_count":statistics.mean(r.get("degraded_count",0) for r in nominal),
        "performance_bypass_count":statistics.mean(r.get("performance_bypass_count",0) for r in nominal),
        "emergency_migrations":statistics.mean(r.get("emergency_migrations",0) for r in nominal),
        "no_physical_capacity_count":statistics.mean(r.get("no_physical_capacity_count",0) for r in nominal),
    }

def domain_summary(rows,candidate):
    out={}
    for name,scs in DOMAINS.items():
        rr=ratios(rows,candidate,scs)
        out[name]={
            "goodput_ratio_vs_as_is":geom(rr),
            "ci95":ci95_log(rr),
            "paired_cells":len(rr),
        }
    return out

def scenario_matrix(rows):
    out=[]
    for sc in scenarios():
        maps={c:best_rows(rows,c,{sc.name}) for c in CANDIDATES}
        keys=sorted(maps["As-Is-HBM-first"])
        row={"scenario":sc.name,"batch":sc.batch_size,"context":sc.context_tokens}
        for c in CANDIDATES:
            vals=[]
            tt=[]; tp=[]
            for k in keys:
                b=maps["As-Is-HBM-first"][k]
                x=maps[c][k]
                if b["slo_goodput"]<=0 and x["slo_goodput"]<=0:
                    continue
                vals.append(
                    10.0 if b["slo_goodput"]<=0<x["slo_goodput"]
                    else x["slo_goodput"]/max(1e-9,b["slo_goodput"])
                )
                tt.append(x["ttft_p99_ms"]/max(1e-9,b["ttft_p99_ms"]))
                tp.append(x["tpot_p99_ms"]/max(1e-9,b["tpot_p99_ms"]))
            row[c]={
                "goodput_ratio":geom(vals),
                "ttft_ratio":statistics.mean(tt) if tt else None,
                "tpot_ratio":statistics.mean(tp) if tp else None,
            }
        out.append(row)
    return out

def verdict(g,t1,t2):
    if g is None:
        return "SLO-INFEASIBLE/STRESS"
    if g>=1.05 and (t1 is None or t1<=1.10) and (t2 is None or t2<=1.10):
        return "WIN"
    if g>=.98 and (t1 is None or t1<=1.05) and (t2 is None or t2<=1.05):
        return "NEUTRAL"
    if ((t1 is not None and t1<=.80) or (t2 is not None and t2<=.80)) and g>=.90:
        return "TRADE-OFF"
    return "LOSS"

def write_report(path,summary):
    a=summary["aggregate"]
    lines=[
        "# DP1 V2 Simulation Result",
        "",
        "> C1-R2: Resource Utility + Emergency Pressure Policy",
        "> C2-R2: deterministic Data Type + Placement Path Cost + Performance Guard + Degraded Placement",
        "",
        "## 1. Aggregate",
        "",
        "| Candidate | Heavy Goodput / As-Is | Mean SLO Goodput | RUI | HBM pressure | Migration/run | Fallback/run | Degraded/run |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in CANDIDATES:
        x=a[c]
        lines.append(
            f"| {c} | {x['heavy_goodput_ratio_vs_as_is'] or 0:.3f} | "
            f"{x['mean_slo_goodput']:.1f} | {x['resource_index']:.3f} | "
            f"{x['hbm_pressure_violation']:.3f} | {x['migration_count']:.2f} | "
            f"{x['fallback_count']:.2f} | {x['degraded_count']:.2f} |"
        )

    lines += ["","## 2. Target-domain Goodput / As-Is","",
              "| Candidate | Neutral/HBM-fit | C1 Resource-pressure | C2 Data-near | C2 Data-lifecycle |",
              "|---|---:|---:|---:|---:|"]
    for c in CANDIDATES:
        d=summary["domains"][c]
        def f(k):
            v=d[k]["goodput_ratio_vs_as_is"]
            return "N/A" if v is None else f"{v:.3f}"
        lines.append(f"| {c} | {f('neutral_hbm_fit')} | {f('c1_resource_pressure')} | {f('c2_data_near')} | {f('c2_data_lifecycle')} |")

    lines += ["","## 3. Scenario Matrix — V2 candidates","",
              "| Scenario | C1-R2 Goodput | C1-R2 TTFT | C1-R2 TPOT | Verdict | C2-R2 Goodput | C2-R2 TTFT | C2-R2 TPOT | Verdict |",
              "|---|---:|---:|---:|---|---:|---:|---:|---|"]
    for r in summary["scenario_matrix"]:
        c1=r["C1-R2-emergency-resource"]; c2=r["C2-R2-path-aware"]
        def fm(v): return "N/A" if v is None else f"{v:.3f}"
        lines.append(
            f"| `{r['scenario']}` | {fm(c1['goodput_ratio'])} | {fm(c1['ttft_ratio'])} | {fm(c1['tpot_ratio'])} | "
            f"{verdict(c1['goodput_ratio'],c1['ttft_ratio'],c1['tpot_ratio'])} | "
            f"{fm(c2['goodput_ratio'])} | {fm(c2['ttft_ratio'])} | {fm(c2['tpot_ratio'])} | "
            f"{verdict(c2['goodput_ratio'],c2['ttft_ratio'],c2['tpot_ratio'])} |"
        )

    lines += ["","## 4. V2-specific counters","",
              f"- C1-R2 emergency migrations/run: **{a['C1-R2-emergency-resource']['emergency_migrations']:.2f}**",
              f"- C2-R2 performance bypass/run: **{a['C2-R2-path-aware']['performance_bypass_count']:.2f}**",
              f"- C2-R2 degraded placements/run: **{a['C2-R2-path-aware']['degraded_count']:.2f}**",
              f"- C2-R2 true no-physical-capacity/run: **{a['C2-R2-path-aware']['no_physical_capacity_count']:.2f}**",
              "",
              "`Fallback`은 C2-R2 정상 개념에서 제거했기 때문에 C2-R2 fallback count는 0이어야 한다. "
              "SLO-feasible path가 없으면 `DEGRADED`로 기록하고, 모든 memory가 물리적으로 꽉 찬 경우만 no-physical-capacity로 분리한다."]
    path.write_text("\n".join(lines).replace("`","`"),encoding="utf-8")

def main():
    system=load_system(Path(__file__).resolve().parents[1]/"configs")
    out=Path(__file__).resolve().parent/"out_v2"
    out.mkdir(parents=True,exist_ok=True)

    rows=[]
    for sc in scenarios():
        for seed in SEEDS:
            for c in CANDIDATES:
                for load in LOAD_SCALES:
                    rows.append(run_sim(system,sc,seed,c,load))

    special={"placement_decisions","class_tier","fallback_reason","path_mode_count"}
    fields=[k for k in rows[0] if k not in special] + [
        "placement_decisions_json","class_tier_json","fallback_reason_json","path_mode_count_json"
    ]
    with (out/"v2_runs.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            x={k:v for k,v in r.items() if k not in special}
            x["placement_decisions_json"]=json.dumps(r["placement_decisions"],sort_keys=True)
            x["class_tier_json"]=json.dumps(r["class_tier"],sort_keys=True)
            x["fallback_reason_json"]=json.dumps(r.get("fallback_reason",{}),sort_keys=True)
            x["path_mode_count_json"]=json.dumps(r.get("path_mode_count",{}),sort_keys=True)
            w.writerow(x)

    summary={
        "meta":{"seeds":SEEDS,"load_scales":LOAD_SCALES,"candidates":CANDIDATES,"scenario_count":len(scenarios())},
        "aggregate":{c:aggregate(rows,c) for c in CANDIDATES},
        "domains":{c:domain_summary(rows,c) for c in CANDIDATES},
        "scenario_matrix":scenario_matrix(rows),
    }
    write_report(out/"dp1-v2-evaluation.md",summary)
    (out/"v2_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(summary["aggregate"],indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
