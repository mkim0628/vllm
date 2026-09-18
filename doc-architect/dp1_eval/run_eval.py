from __future__ import annotations
import argparse, csv, json, math, statistics
from collections import Counter, defaultdict
from pathlib import Path
from model import load_system, DATA_CLASSES
from scenarios import scenarios
from simulator import run_sim
from modifiability import measure as measure_modifiability

SEEDS=[11,23,37,51,71]
ROBUSTNESS={"classifier_error":"fault injection: wrong DataDescriptor type hints",
            "capacity_crunch":"infeasible/near-infeasible capacity stress",
            "six_tier_stress":"coverage stress: force meaningful roles for all 6 tiers"}

def star_throughput(x): return 3 if x>=.85 else 2 if x>=.50 else 1
def star_ttft(ms): return 3 if ms<=2000 else 2 if ms<=4000 else 1
def star_tpot(ms): return 3 if ms<=25 else 2 if ms<=50 else 1
def star_resource(x): return 3 if x>=.85 else 2 if x>=.65 else 1

def ci95(vals):
    if len(vals)<2:return [vals[0],vals[0]]
    m=statistics.mean(vals); sd=statistics.stdev(vals); h=1.96*sd/math.sqrt(len(vals))
    return [m-h,m+h]

def aggregate(rows,candidate,score_names):
    rs=[r for r in rows if r["candidate"]==candidate and r["scenario"] in score_names]
    ratio=statistics.mean(r["throughput_ratio"] for r in rs)
    rui=statistics.mean(r["resource_index"] for r in rs)
    ttft=max(r["ttft_p99_ms"] for r in rs); tpot=max(r["tpot_p99_ms"] for r in rs)
    lat_star=min(star_ttft(ttft),star_tpot(tpot))
    return {
      "scored_runs":len(rs),
      "token_throughput_mean":statistics.mean(r["token_throughput"] for r in rs),
      "request_throughput_mean":statistics.mean(r["request_throughput"] for r in rs),
      "throughput_reference_ratio":ratio,
      "ttft_p99_worst_scored_ms":ttft,
      "tpot_p99_worst_scored_ms":tpot,
      "e2e_p99_mean_ms":statistics.mean(r["e2e_p99_ms"] for r in rs),
      "resource_utilization_index":rui,
      "hbm_pressure_violation_rate":statistics.mean(r["hbm_pressure_violation_rate"] for r in rs),
      "bw_saturation_rate":statistics.mean(r["bw_saturation_rate"] for r in rs),
      "migration_count_mean":statistics.mean(r["migration_count"] for r in rs),
      "decision_us_avg":statistics.mean(r["decision_us_avg"] for r in rs),
      "stars":{"performance_throughput":star_throughput(ratio),
               "performance_latency":lat_star,
               "resource_utilization":star_resource(rui)}
    }

def scenario_comparison(rows):
    out=[]
    for sc in scenarios():
        c1=sorted([r for r in rows if r["scenario"]==sc.name and r["candidate"]=="C1-memory-centric"],key=lambda x:x["seed"])
        c2=sorted([r for r in rows if r["scenario"]==sc.name and r["candidate"]=="C2-data-centric"],key=lambda x:x["seed"])
        diffs=[100*(b["throughput_ratio"]-a["throughput_ratio"])/max(1e-9,a["throughput_ratio"]) for a,b in zip(c1,c2)]
        out.append({
          "scenario":sc.name,"role":"robustness/coverage" if sc.name in ROBUSTNESS else "QA-score",
          "c1_throughput_ratio":statistics.mean(r["throughput_ratio"] for r in c1),
          "c2_throughput_ratio":statistics.mean(r["throughput_ratio"] for r in c2),
          "c2_minus_c1_pct":statistics.mean(diffs),"ci95_pct":ci95(diffs),
          "c1_ttft_p99_ms":statistics.mean(r["ttft_p99_ms"] for r in c1),
          "c2_ttft_p99_ms":statistics.mean(r["ttft_p99_ms"] for r in c2),
          "c1_tpot_p99_ms":statistics.mean(r["tpot_p99_ms"] for r in c1),
          "c2_tpot_p99_ms":statistics.mean(r["tpot_p99_ms"] for r in c2),
          "c1_resource_index":statistics.mean(r["resource_index"] for r in c1),
          "c2_resource_index":statistics.mean(r["resource_index"] for r in c2)})
    return out

def placement_coverage(rows,candidate):
    pc=Counter(); ct=Counter()
    for r in rows:
        if r["candidate"]!=candidate: continue
        pc.update(r["placement_decisions"]); ct.update(r["class_tier"])
    return {"placement_decisions_by_tier":dict(pc),"class_tier_decisions":dict(ct),
            "tiers_exercised":sorted([k for k,v in pc.items() if v>0])}

def stars(n): return "★"*n+"☆"*(3-n)

def write_report(path,summary):
    a=summary["aggregate"]; mod=summary["modifiability"]["totals"]; comp=summary["scenario_comparison"]
    lines=[]
    lines.append("# DP1 C1/C2 QA Evaluation — Multi-AI-Data Simulation\n")
    lines.append("> QA 별점 기준은 `evaluation-criteria.md`의 **DP1~DP4 공통 기준**만 사용한다. Fault-injection/coverage stress 3종은 trade-off 분석에는 포함하되 최종 QA 별점 산정에서는 제외했다.\n")
    lines.append("## 1. Final QA score\n")
    lines.append("| QA | C1 Memory-centric | C2 Data-centric | 공통 정량 기준 |\n|---|---:|---:|---|")
    for qa,label in [("performance_throughput","Performance Throughput"),("performance_latency","Performance Latency"),("resource_utilization","Resource Utilization")]:
        c1=a["C1-memory-centric"]["stars"][qa]; c2=a["C2-data-centric"]["stars"][qa]
        if qa=="performance_throughput": basis="Reference TPS 대비: ★★★ ≥0.85, ★★☆ 0.50~0.85"
        elif qa=="performance_latency": basis="min(TTFT, TPOT): TTFT ≤2s, TPOT ≤25ms이면 ★★★"
        else: basis="RUI: ★★★ ≥0.85, ★★☆ 0.65~0.85"
        lines.append(f"| **{label}** | {stars(c1)} | {stars(c2)} | {basis} |")
    lines.append(f"| **Modifiability** | {stars(mod['C1']['final_star'])} | {stars(mod['C2']['final_star'])} | PM/Token 중 낮은 별점; ★★★ ≤0.25PM and ≤20K token |")
    lines.append("\n## 2. Scored aggregate\n")
    lines.append("| Metric | C1 | C2 |\n|---|---:|---:|")
    keys=[("throughput_reference_ratio","Throughput / physical reference"),("token_throughput_mean","Token throughput mean [tok/s]"),
          ("request_throughput_mean","Request throughput mean [req/s]"),("ttft_p99_worst_scored_ms","Worst scored TTFT p99 [ms]"),
          ("tpot_p99_worst_scored_ms","Worst scored TPOT p99 [ms]"),("resource_utilization_index","Resource Utilization Index"),
          ("hbm_pressure_violation_rate","HBM pressure violation rate"),("bw_saturation_rate","BW saturation rate"),
          ("migration_count_mean","Migration decisions/run"),("decision_us_avg","Placement decision proxy [us]")]
    for k,l in keys: lines.append(f"| {l} | {a['C1-memory-centric'][k]:.4f} | {a['C2-data-centric'][k]:.4f} |")
    lines.append("\n## 3. Scenario design — AI Data coverage\n")
    lines.append("`write_heavy_logs`라는 모호한 이름은 제거하고 **`runtime_log_append`**로 명시했다. 이 시나리오는 SST/SSTable이 아니라 DP1 범위의 **AI Runtime / Agent execution log**다. SSTable 자체는 storage-engine 내부 구조이므로 AI Runtime Data로 보지 않는다.\n")
    lines.append("| Scenario | AI Data | 의도 | Target tier coverage |\n|---|---|---|---|")
    for sc in scenarios():
        mix=", ".join(f"{k}:{v:.0%}" for k,v in sc.data_mix.items())
        role=("robustness/coverage" if sc.name in ROBUSTNESS else "QA-score")
        lines.append(f"| `{sc.name}` ({role}) | {mix} | {sc.description} | {', '.join(sc.target_tiers)} |")
    lines.append("\n## 4. Six-memory actual coverage\n")
    for cand in ("C1-memory-centric","C2-data-centric"):
        cov=summary["placement_coverage"][cand]
        lines.append(f"\n### {cand}\n")
        lines.append(f"- Exercised tiers: **{', '.join(cov['tiers_exercised'])}**")
        lines.append("- Placement decisions: "+", ".join(f"`{k}`={v}" for k,v in sorted(cov["placement_decisions_by_tier"].items())))
    lines.append("\n### Data class × tier coverage\n")
    lines.append("다음은 단순히 시나리오 이름에 tier를 적은 것이 아니라 실제 placement decision에서 관찰된 조합이다.\n")
    for cand in ("C1-memory-centric","C2-data-centric"):
        lines.append(f"**{cand}**")
        ct=summary["placement_coverage"][cand]["class_tier_decisions"]; by=defaultdict(list)
        for k,v in ct.items():
            cls,tier=k.split("@"); by[cls].append((tier,v))
        for cls in DATA_CLASSES:
            cells=", ".join(f"{t}:{v}" for t,v in sorted(by.get(cls,[])))
            lines.append(f"- `{cls}` → {cells or 'no placement'}")
        lines.append("")
    lines.append("\n## 5. Scenario-level trade-offs\n")
    lines.append("| Scenario | C1 thr/ref | C2 thr/ref | C2-C1 | 95% CI | C1 RUI | C2 RUI |\n|---|---:|---:|---:|---:|---:|---:|")
    for x in comp:
        lo,hi=x["ci95_pct"]
        lines.append(f"| `{x['scenario']}` | {x['c1_throughput_ratio']:.3f} | {x['c2_throughput_ratio']:.3f} | {x['c2_minus_c1_pct']:+.1f}% | [{lo:+.1f}, {hi:+.1f}]% | {x['c1_resource_index']:.3f} | {x['c2_resource_index']:.3f} |")
    lines.append("\n## 6. Modifiability — common DP1~DP4 basis\n")
    lines.append("| Candidate | Person-month | Person-days | Static AI token estimate | PM star | Token star | Final |\n|---|---:|---:|---:|---:|---:|---:|")
    for k in ("C1","C2"):
        d=mod[k]; lines.append(f"| {k} | {d['person_months']:.4f} | {d['person_days']:.2f} | {d['tokens']:,} | {stars(d['pm_star'])} | {stars(d['token_star'])} | {stars(d['final_star'])} |")
    lines.append("\nAI token은 실제 agent usage telemetry가 아니라 공통 기준 문서의 **read/write source chars ÷ 3.6 char/token 정적 추정**이다. 실제 API usage를 가장한 값이 아니다.\n")
    lines.append("## 7. Interpretation and limits\n")
    lines.append("- **C1**은 Data class semantics를 사용하지 않아 classifier 오류에 구조적으로 영향받지 않고, 신규 Data Type 변경 비용이 작다.")
    lines.append("- **C2**는 RAG/Agent/Log/LoRA/MoE 등 class/runtime behavior를 Tier affinity로 변환하므로 전체 suite의 RUI가 높다. 대신 잘못된 type hint를 주입한 `classifier_error`에서 failure mode가 드러난다.")
    lines.append("- `capacity_crunch`와 `six_tier_stress`는 정상 SLO 운용점이 아니라 spill/coverage를 확인하는 stress test이므로 최종 별점에서는 제외했다.")
    lines.append("- 실제 migration mechanism은 DP4 범위다. 본 simulator는 tier 변경 시 idealized path cost의 20%만 다음 access critical path에 반영한다.")
    lines.append("- 실제 vLLM 실측이 아니라 architecture-level simulation이다. Config의 ASSUMED 값 때문에 절대값보다 **동일 trace의 후보 간 차이와 failure mode**를 더 신뢰해야 한다.")
    path.write_text("\n".join(lines),encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config-dir",type=Path,default=Path(__file__).resolve().parents[1]/"configs")
    ap.add_argument("--seeds",default=",".join(map(str,SEEDS)))
    ap.add_argument("--output-dir",type=Path,default=Path(__file__).resolve().parent/"out")
    args=ap.parse_args(); seeds=[int(x) for x in args.seeds.split(",") if x]
    system=load_system(args.config_dir); out=args.output_dir; out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for sc in scenarios():
        for seed in seeds:
            for c in ("C1-memory-centric","C2-data-centric"):
                rows.append(run_sim(system,sc,seed,c))
    csv_path=out/"results_runs.csv"
    fields=[k for k in rows[0] if k not in ("placement_decisions","placement_bytes","class_tier")]+["placement_decisions_json","placement_bytes_json","class_tier_json"]
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            x={k:v for k,v in r.items() if k not in ("placement_decisions","placement_bytes","class_tier")}
            x["placement_decisions_json"]=json.dumps(r["placement_decisions"],sort_keys=True)
            x["placement_bytes_json"]=json.dumps(r["placement_bytes"],sort_keys=True)
            x["class_tier_json"]=json.dumps(r["class_tier"],sort_keys=True); w.writerow(x)
    score_names={s.name for s in scenarios()}-set(ROBUSTNESS)
    mod=measure_modifiability()
    agg={c:aggregate(rows,c,score_names) for c in ("C1-memory-centric","C2-data-centric")}
    agg["C1-memory-centric"]["stars"]["modifiability"]=mod["totals"]["C1"]["final_star"]
    agg["C2-data-centric"]["stars"]["modifiability"]=mod["totals"]["C2"]["final_star"]
    summary={
      "meta":{"seeds":seeds,"scenarios_total":len(scenarios()),"scenarios_scored":len(score_names),
              "robustness_excluded_from_star":ROBUSTNESS,"cluster":"b200_8gpu","model":"llama_3_1_70b",
              "config_files":["configs/memories_default.json","configs/clusters.json","configs/models.json"]},
      "common_star_thresholds":{
        "performance_throughput":"reference ratio: <0.50=1, 0.50~0.85=2, >=0.85=3",
        "performance_latency":"min(TTFT,TPOT); TTFT <=2s and TPOT <=25ms => 3",
        "resource_utilization":"RUI <0.65=1, 0.65~0.85=2, >=0.85=3",
        "modifiability":"min(PM star, token star); 3 if <=0.25PM and <=20K tokens"},
      "aggregate":agg,"modifiability":mod,
      "scenario_comparison":scenario_comparison(rows),
      "placement_coverage":{c:placement_coverage(rows,c) for c in ("C1-memory-centric","C2-data-centric")}
    }
    (out/"results_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    manifest=[]
    for s in scenarios():
        manifest.append({"name":s.name,"role":"robustness/coverage" if s.name in ROBUSTNESS else "QA-score",
                         "description":s.description,"data_mix":s.data_mix,"target_tiers":s.target_tiers,
                         "context_tokens":s.context_tokens,"output_tokens":s.output_tokens})
    (out/"scenario_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    write_report(out/"dp1-qa-evaluation.md",summary)
    print(json.dumps({c:summary["aggregate"][c] for c in summary["aggregate"]},indent=2))
    print("wrote",out)

if __name__=="__main__": main()
