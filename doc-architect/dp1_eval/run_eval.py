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
from modifiability import measure as measure_modifiability

SEEDS=[11,23,37,51,71]
CANDIDATES=("As-Is-HBM-first","C1-memory-centric","C2-data-centric")
LOAD_SCALES=(0.25,0.50,0.75,1.00,1.25)
ROBUSTNESS={
    "classifier_error":"fault injection: wrong DataDescriptor type hints",
    "six_tier_capacity_stress":"coverage stress: force all six tiers",
}

def ci95(vals):
    if not vals: return [0.0,0.0]
    if len(vals)<2: return [vals[0],vals[0]]
    m=statistics.mean(vals); sd=statistics.stdev(vals)
    h=1.96*sd/math.sqrt(len(vals))
    return [m-h,m+h]

def star_goodput(ratio,ci):
    lo,hi=ci
    if ratio>=1.10 and lo>=1.0: return 3
    if ratio<.90 and hi<1.0: return 1
    return 2

def star_first_response(ms):
    return 3 if ms<=2000 else 2 if ms<=4000 else 1

def star_tpot(ms):
    return 3 if ms<=25 else 2 if ms<=50 else 1

def star_resource(x):
    return 3 if x>=.85 else 2 if x>=.65 else 1

def geom_mean(vals):
    xs=[max(1e-9,x) for x in vals]
    return math.exp(sum(math.log(x) for x in xs)/len(xs)) if xs else 0.0

def heavy_score_names():
    # Large-batch OR long-context cells; cells with zero SLO-goodput for all policies
    # are removed later as SLO-infeasible stress points.
    return {s.name for s in scenarios()
            if s.name not in ROBUSTNESS and (s.batch_size>=64 or s.context_tokens>=131072)}

def normal_score_names():
    return {s.name for s in scenarios() if s.name not in ROBUSTNESS}

def best_goodput_rows(rows,candidate,names):
    best={}
    for r in rows:
        if r["candidate"]!=candidate or r["scenario"] not in names:
            continue
        k=(r["scenario"],r["seed"])
        if k not in best or r["slo_goodput"]>best[k]["slo_goodput"]:
            best[k]=r
    return best

def paired_goodput_ratios(rows,candidate,names):
    base=best_goodput_rows(rows,"As-Is-HBM-first",names)
    cand=best_goodput_rows(rows,candidate,names)
    vals=[]; infeasible=[]
    for k,b in base.items():
        c=cand[k]
        if b["slo_goodput"]<=0 and c["slo_goodput"]<=0:
            infeasible.append(k)
            continue
        if b["slo_goodput"]<=0 and c["slo_goodput"]>0:
            vals.append(10.0)
        else:
            vals.append(c["slo_goodput"]/b["slo_goodput"])
    return vals,infeasible

def aggregate(rows,candidate,mod):
    normal=normal_score_names(); heavy=heavy_score_names()
    rs=[r for r in rows if r["candidate"]==candidate and r["scenario"] in normal]
    nominal=[r for r in rs if abs(r["load_scale"]-1.0)<1e-9]
    hrs=[r for r in rs if r["scenario"] in heavy]

    if candidate=="As-Is-HBM-first":
        ratio=1.0; ratio_ci=[1.0,1.0]; throughput_star=2; infeasible=[]
    else:
        ratios,infeasible=paired_goodput_ratios(rows,candidate,heavy)
        ratio=geom_mean(ratios) if ratios else 1.0
        logs=[math.log(max(1e-9,x)) for x in ratios]
        lci=ci95(logs) if logs else [0.0,0.0]
        ratio_ci=[math.exp(lci[0]),math.exp(lci[1])]
        throughput_star=star_goodput(ratio,ratio_ci)

    # Latency stars are taken at each candidate's max-sustainable-goodput point,
    # excluding cells where every policy has zero SLO-goodput (stress-only boundary).
    best_maps={c:best_goodput_rows(rows,c,normal) for c in CANDIDATES}
    all_keys=set().union(*(m.keys() for m in best_maps.values()))
    feasible_keys={
        k for k in all_keys
        if any(best_maps[c].get(k,{}).get("slo_goodput",0)>0 for c in CANDIDATES)
    }
    lat_rows=[best_maps[candidate][k] for k in feasible_keys if k in best_maps[candidate]]
    ttft=max((r["ttft_p99_ms"] for r in lat_rows),default=0.0)
    tpot=max((r["tpot_p99_ms"] for r in lat_rows),default=0.0)

    stress_keys=all_keys-feasible_keys
    stress_rows=[best_maps[candidate][k] for k in stress_keys if k in best_maps[candidate]]
    stress_ttft=max((r["ttft_p99_ms"] for r in stress_rows),default=0.0)
    stress_tpot=max((r["tpot_p99_ms"] for r in stress_rows),default=0.0)

    rui=statistics.mean(r["resource_index"] for r in nominal) if nominal else 0.0
    key="C1" if candidate.startswith("C1") else "C2" if candidate.startswith("C2") else None
    mod_star=mod["totals"][key]["final_star"] if key else None

    return {
      "normal_runs":len(rs),"heavy_runs":len(hrs),"infeasible_heavy_cells":len(infeasible),
      "token_throughput_mean":statistics.mean(r["token_throughput"] for r in nominal),
      "slo_goodput_mean":statistics.mean(r["slo_goodput"] for r in nominal),
      "goodput_ratio_vs_as_is_heavy":ratio,
      "goodput_ratio_ci95":ratio_ci,
      "ttft_p99_worst_scored_ms":ttft,
      "tpot_p99_worst_scored_ms":tpot,
      "ttft_p99_worst_stress_ms":stress_ttft,
      "tpot_p99_worst_stress_ms":stress_tpot,
      "e2e_p99_mean_ms":statistics.mean(r["e2e_p99_ms"] for r in nominal),
      "resource_utilization_index":rui,
      "hbm_pressure_violation_rate":statistics.mean(r["hbm_pressure_violation_rate"] for r in nominal),
      "bw_saturation_rate":statistics.mean(r["bw_saturation_rate"] for r in nominal),
      "migration_count_mean":statistics.mean(r["migration_count"] for r in nominal),
      "decision_us_avg":statistics.mean(r["decision_us_avg"] for r in nominal),
      "fallback_count_mean":statistics.mean(r.get("fallback_count",0) for r in nominal),
      "stars":{
        "performance_throughput":throughput_star,
        "latency_first_response":star_first_response(ttft),
        "latency_tpot":star_tpot(tpot),
        "resource_utilization":star_resource(rui),
        "modifiability":mod_star,
      }
    }

def scenario_comparison(rows):
    out=[]
    for sc in scenarios():
        best={c:best_goodput_rows(rows,c,{sc.name}) for c in CANDIDATES}
        keys=sorted(best["As-Is-HBM-first"])
        base=[best["As-Is-HBM-first"][k] for k in keys]
        c1=[best["C1-memory-centric"][k] for k in keys]
        c2=[best["C2-data-centric"][k] for k in keys]
        nominal={c:sorted([r for r in rows if r["scenario"]==sc.name and r["candidate"]==c and abs(r["load_scale"]-1.0)<1e-9],
                          key=lambda x:x["seed"]) for c in CANDIDATES}
        c1b=[]; c2b=[]; d12=[]
        for a,b,z in zip(c1,c2,base):
            if z["slo_goodput"]<=0 and a["slo_goodput"]<=0 and b["slo_goodput"]<=0:
                continue
            c1b.append(10.0 if z["slo_goodput"]<=0<a["slo_goodput"] else a["slo_goodput"]/max(1e-9,z["slo_goodput"]))
            c2b.append(10.0 if z["slo_goodput"]<=0<b["slo_goodput"] else b["slo_goodput"]/max(1e-9,z["slo_goodput"]))
            d12.append(10.0 if a["slo_goodput"]<=0<b["slo_goodput"] else b["slo_goodput"]/max(1e-9,a["slo_goodput"]))
        out.append({
          "scenario":sc.name,
          "role":"robustness/coverage" if sc.name in ROBUSTNESS else "QA-score",
          "batch":sc.batch_size,"context":sc.context_tokens,
          "as_is_goodput":statistics.mean(r["slo_goodput"] for r in base),
          "slo_feasible":any(r["slo_goodput"]>0 for r in base+c1+c2),
          "c1_goodput":statistics.mean(r["slo_goodput"] for r in c1),
          "c2_goodput":statistics.mean(r["slo_goodput"] for r in c2),
          "c1_vs_as_is":geom_mean(c1b) if c1b else None,"c2_vs_as_is":geom_mean(c2b) if c2b else None,
          "c2_vs_c1":geom_mean(d12) if d12 else None,"c2_vs_c1_ci95":ci95(d12) if d12 else None,
          "c1_ttft_p99_ms":statistics.mean(r["ttft_p99_ms"] for r in nominal["C1-memory-centric"]),
          "c2_ttft_p99_ms":statistics.mean(r["ttft_p99_ms"] for r in nominal["C2-data-centric"]),
          "c1_tpot_p99_ms":statistics.mean(r["tpot_p99_ms"] for r in nominal["C1-memory-centric"]),
          "c2_tpot_p99_ms":statistics.mean(r["tpot_p99_ms"] for r in nominal["C2-data-centric"]),
          "c1_resource_index":statistics.mean(r["resource_index"] for r in nominal["C1-memory-centric"]),
          "c2_resource_index":statistics.mean(r["resource_index"] for r in nominal["C2-data-centric"]),
          "c2_fallback_mean":statistics.mean(r.get("fallback_count",0) for r in nominal["C2-data-centric"]),
        })
    return out

def placement_coverage(rows,candidate):
    pc=Counter(); ct=Counter(); fb=Counter()
    for r in rows:
        if r["candidate"]!=candidate: continue
        pc.update(r["placement_decisions"])
        ct.update(r["class_tier"])
        fb.update(r.get("fallback_reason",{}))
    return {
      "placement_decisions_by_tier":dict(pc),
      "class_tier_decisions":dict(ct),
      "tiers_exercised":sorted([k for k,v in pc.items() if v>0]),
      "fallback_reasons":dict(fb),
    }

def stars(n):
    if n is None: return "N/A"
    return "★"*n+"☆"*(3-n)

def fmt_ratio(v):
    return "N/A" if v is None else f"{v:.3f}"

def write_report(path,summary):
    a=summary["aggregate"]; mod=summary["modifiability"]["totals"]
    lines=[
      "# DP1 C1/C2 QA Evaluation — Operation-aware, Large-batch/Long-context",
      "",
      "> First-response metric은 network transport를 모델링하지 않으므로 literal TTFB가 아니라 **TTFT**다. Latency QA는 TTFT와 TPOT을 별도로 평가하며 하나의 별점으로 합치지 않는다.",
      "",
      "## 1. Final QA score","",
      "| QA | C1 | C2 | 공통 기준 |",
      "|---|---:|---:|---|",
      f"| Performance Throughput | {stars(a['C1-memory-centric']['stars']['performance_throughput'])} | {stars(a['C2-data-centric']['stars']['performance_throughput'])} | Heavy-cell SLO Goodput / As-Is |",
      f"| Performance Latency — TTFT | {stars(a['C1-memory-centric']['stars']['latency_first_response'])} | {stars(a['C2-data-centric']['stars']['latency_first_response'])} | p99 ≤2s / 2~4s / >4s |",
      f"| Performance Latency — TPOT | {stars(a['C1-memory-centric']['stars']['latency_tpot'])} | {stars(a['C2-data-centric']['stars']['latency_tpot'])} | p99 ≤25ms / 25~50ms / >50ms |",
      f"| Resource Utilization | {stars(a['C1-memory-centric']['stars']['resource_utilization'])} | {stars(a['C2-data-centric']['stars']['resource_utilization'])} | RUI ≥0.85 / 0.65~0.85 / <0.65 |",
      f"| Modifiability | {stars(a['C1-memory-centric']['stars']['modifiability'])} | {stars(a['C2-data-centric']['stars']['modifiability'])} | DP1~DP4 common 4 change archetypes |",
      "",
      "## 2. Aggregate","",
      "| Metric | As-Is | C1 | C2 |","|---|---:|---:|---:|",
    ]
    for key,label in [
      ("slo_goodput_mean","SLO Goodput mean [tok/s]"),
      ("goodput_ratio_vs_as_is_heavy","Heavy Goodput ratio vs As-Is"),
      ("ttft_p99_worst_scored_ms","Worst scored TTFT p99 [ms]"),
      ("tpot_p99_worst_scored_ms","Worst scored TPOT p99 [ms]"),
      ("ttft_p99_worst_stress_ms","Worst stress TTFT p99 [ms]"),
      ("tpot_p99_worst_stress_ms","Worst stress TPOT p99 [ms]"),
      ("resource_utilization_index","Resource Utilization Index"),
      ("migration_count_mean","Migration decisions/run"),
      ("decision_us_avg","Placement decision proxy [us]"),
      ("fallback_count_mean","Fallback count/run"),
    ]:
        lines.append(f"| {label} | {a['As-Is-HBM-first'][key]:.4f} | {a['C1-memory-centric'][key]:.4f} | {a['C2-data-centric'][key]:.4f} |")

    lines += [
      "","## 3. Workload coverage","",
      "명시적 batch/concurrency와 context를 사용한다. Heavy throughput score는 large-batch 또는 long-context 정상 시나리오를 사용하고, 모든 정책의 SLO-goodput이 0인 cell은 throughput ratio에서 제외한다.","",
      "| Scenario | Batch | Context | Data mix | Target tiers |","|---|---:|---:|---|---|",
    ]
    for sc in scenarios():
        mix=", ".join(f"{k}:{v:.0%}" for k,v in sc.data_mix.items())
        lines.append(f"| `{sc.name}` | {sc.batch_size} | {sc.context_tokens//1024}K | {mix} | {', '.join(sc.target_tiers)} |")

    lines += [
      "","## 4. Operation-aware cases","",
      "- **KV on CXL-PNM / Custom HBM:** Attention(QK/Softmax/AV/Causal Mask)은 memory-side에서 수행하고 FFN/model-weight path는 GPU에 남긴다. 매 token/layer activation round-trip과 external-link contention을 포함한다.",
      "- **RAG on SSD-PIM:** 현재 registry의 `QK_GEMM`은 local dot-product에만 사용한다. `TOPK` primitive가 없으므로 full in-storage search로 과대 가정하지 않고 score-result transfer를 포함한다.",
      "- **C2 fallback:** low classifier confidence, low affinity margin, unsupported operation, predicted latency violation, runtime-behavior mismatch에서 SafeFallbackSelector로 전환한다.",
      "","## 5. Scenario trade-offs","",
      "| Scenario | B | Ctx | C1/As-Is | C2/As-Is | C2/C1 | C1 TTFT | C2 TTFT | C1 TPOT | C2 TPOT |",
      "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for x in summary["scenario_comparison"]:
        lines.append(f"| `{x['scenario']}` | {x['batch']} | {x['context']//1024}K | {fmt_ratio(x['c1_vs_as_is'])} | {fmt_ratio(x['c2_vs_as_is'])} | {fmt_ratio(x['c2_vs_c1'])} | {x['c1_ttft_p99_ms']:.1f} | {x['c2_ttft_p99_ms']:.1f} | {x['c1_tpot_p99_ms']:.1f} | {x['c2_tpot_p99_ms']:.1f} |")

    lines += [
      "","## 6. Modifiability","",
      "| Candidate | Person-month | Static token estimate | Final |","|---|---:|---:|---:|",
    ]
    for k in ("C1","C2"):
        d=mod[k]
        lines.append(f"| {k} | {d['person_months']:.4f} | {d['tokens']:,} | {stars(d['final_star'])} |")

    lines += [
      "","## 7. Modeling boundary / limitations","",
      "- TTFT는 model/runtime first-token readiness이며 literal network TTFB가 아니다.",
      "- DP1은 compute placement 자체를 결정하지 않는다. 다만 memory-side operation capability가 data placement cost/feasibility에 미치는 효과를 모델링한다.",
      "- 실제 migration algorithm/path scheduling은 DP4 범위이며, 여기서는 이동 path cost proxy만 반영한다.",
      "- SSD-PIM에 TOPK가 없으므로 RAG retrieval은 dot-product local + score transfer로 계산한다. TOPK capability가 config에 추가되면 별도 sweep이 필요하다.",
    ]
    path.write_text("\n".join(lines),encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config-dir",type=Path,default=Path(__file__).resolve().parents[1]/"configs")
    ap.add_argument("--seeds",default=",".join(map(str,SEEDS)))
    ap.add_argument("--output-dir",type=Path,default=Path(__file__).resolve().parent/"out")
    args=ap.parse_args()
    seeds=[int(x) for x in args.seeds.split(",") if x]
    system=load_system(args.config_dir)
    out=args.output_dir; out.mkdir(parents=True,exist_ok=True)

    rows=[]
    for sc in scenarios():
        for seed in seeds:
            for c in CANDIDATES:
                for load_scale in LOAD_SCALES:
                    rows.append(run_sim(system,sc,seed,c,load_scale))

    special={"placement_decisions","class_tier","fallback_reason"}
    fields=[k for k in rows[0] if k not in special]+["placement_decisions_json","class_tier_json","fallback_reason_json"]
    with (out/"results_runs.csv").open("w",newline="",encoding="utf-8") as fcsv:
        w=csv.DictWriter(fcsv,fieldnames=fields); w.writeheader()
        for r in rows:
            x={k:v for k,v in r.items() if k not in special}
            x["placement_decisions_json"]=json.dumps(r["placement_decisions"],sort_keys=True)
            x["class_tier_json"]=json.dumps(r["class_tier"],sort_keys=True)
            x["fallback_reason_json"]=json.dumps(r.get("fallback_reason",{}),sort_keys=True)
            w.writerow(x)

    mod=measure_modifiability()
    agg={c:aggregate(rows,c,mod) for c in CANDIDATES}
    summary={
      "meta":{
        "seeds":seeds,"scenario_count":len(scenarios()),"load_scales":LOAD_SCALES,
        "heavy_score_scenarios":sorted(heavy_score_names()),
        "robustness_excluded_from_star":ROBUSTNESS,
        "cluster":"b200_8gpu","model":"llama_3_1_70b",
      },
      "aggregate":agg,
      "modifiability":mod,
      "scenario_comparison":scenario_comparison(rows),
      "placement_coverage":{c:placement_coverage(rows,c) for c in CANDIDATES},
    }
    (out/"results_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")

    manifest=[{
      "name":s.name,
      "role":"robustness/coverage" if s.name in ROBUSTNESS else "QA-score",
      "description":s.description,"data_mix":s.data_mix,
      "batch_size":s.batch_size,"context_tokens":s.context_tokens,
      "rag_index_total_gib":s.rag_index_total_gib,
      "target_tiers":s.target_tiers,
    } for s in scenarios()]
    (out/"scenario_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    write_report(out/"dp1-qa-evaluation.md",summary)
    print(json.dumps(agg,indent=2,ensure_ascii=False))
    print("wrote",out)

if __name__=="__main__":
    main()
