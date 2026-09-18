from __future__ import annotations

import csv, json, math, statistics
from pathlib import Path
from model import load_system
from scenarios import scenarios
from simulator import run_sim

SEEDS=[11,23,37,51,71]
LOADS=[0.25,0.50,0.75,1.00,1.25]
CANDIDATES=['As-Is-HBM-first','C1-R2-emergency-resource','C2-R2-path-aware']

# Predefined before evaluation: two scenarios per architectural role.
GROUPS={
  'overall': {
    'kv_b16_c32k','kv_b1_c32k_cold_cxl',
    'hbm_pressure_ramp_b64','hbm_bw_shock_b256',
    'kv_b16_c32k_burst_chbm','rag_8tib_b64_ssd_pim',
  },
  'neutral_control': {'kv_b16_c32k','kv_b1_c32k_cold_cxl'},
  'c1_target': {'hbm_pressure_ramp_b64','hbm_bw_shock_b256'},
  'c2_target': {'kv_b16_c32k_burst_chbm','rag_8tib_b64_ssd_pim'},
}

def geom(xs):
    xs=[max(1e-12,float(x)) for x in xs]
    return math.exp(sum(math.log(x) for x in xs)/len(xs)) if xs else None

def ci95_log(xs):
    if not xs: return None
    ls=[math.log(max(1e-12,float(x))) for x in xs]
    if len(ls)<2:
        v=math.exp(ls[0]); return [v,v]
    m=statistics.mean(ls); h=1.96*statistics.stdev(ls)/math.sqrt(len(ls))
    return [math.exp(m-h),math.exp(m+h)]

def star_high(r,ci):
    if r is None or ci is None: return None
    lo,hi=ci
    if r>=1.10 and lo>=1.0: return 3
    if r<0.90 and hi<1.0: return 1
    return 2

def star_low(r,ci):
    if r is None or ci is None: return None
    lo,hi=ci
    if r<=0.90 and hi<=1.0: return 3
    if r>1.10 and lo>1.0: return 1
    return 2

def stars(n): return 'N/A' if n is None else '★'*n+'☆'*(3-n)

def paired_metric(rows,candidate,names,metric,higher):
    base={(r['scenario'],r['seed'],r['load_scale']):r for r in rows
          if r['candidate']=='As-Is-HBM-first' and r['scenario'] in names}
    cand={(r['scenario'],r['seed'],r['load_scale']):r for r in rows
          if r['candidate']==candidate and r['scenario'] in names}
    cell=[]
    for sc in sorted(names):
      for seed in SEEDS:
        vals=[]
        for load in LOADS:
          k=(sc,seed,load)
          if k in base and k in cand:
            vals.append(cand[k][metric]/max(1e-12,base[k][metric]))
        if vals: cell.append(geom(vals))
    r=geom(cell); ci=ci95_log(cell)
    return {'ratio':r,'ci95':ci,'star':(star_high if higher else star_low)(r,ci),'pairs':len(cell)}

def evaluate(rows,candidate,names):
    return {
      'throughput':paired_metric(rows,candidate,names,'token_throughput',True),
      'ttft':paired_metric(rows,candidate,names,'ttft_p99_ms',False),
      'tpot':paired_metric(rows,candidate,names,'tpot_p99_ms',False),
      'resource':paired_metric(rows,candidate,names,'resource_index',True),
    }

# Structural modifiability proxy, counted from the module view.
# Two common changes: add a memory tier/capability, add a new AI-data/operation class.
MODIFIABILITY={
  'C1-R2-emergency-resource': {
    'new_tier_modules':2,  # Memory Registry + Resource/Performance cost logic
    'new_data_class_modules':1,  # static capability/cost rule only
    'per_object_behavior_state_fields':0,
  },
  'C2-R2-path-aware': {
    'new_tier_modules':4,  # Registry + Path Builder + Cost Evaluator + Affinity
    'new_data_class_modules':4,  # Resolver/Interpreter + Path/Cost + Affinity
    'per_object_behavior_state_fields':5,  # rate, samples, last access, reuse EWMA, first seen
  },
}

def mod_score(x):
    avg=(x['new_tier_modules']+x['new_data_class_modules'])/2
    # Transparent architecture-change surface: <=2 small, <=3 medium, >3 large.
    return 3 if avg<=2 else 2 if avg<=3 else 1

def main():
    system=load_system(Path(__file__).resolve().parents[1]/'configs')
    scmap={s.name:s for s in scenarios()}
    selected=sorted(GROUPS['overall'])
    rows=[]
    for name in selected:
      sc=scmap[name]
      for seed in SEEDS:
        for cand in CANDIDATES:
          for load in LOADS:
            rows.append(run_sim(system,sc,seed,cand,load))

    summary={'meta':{'scenarios':selected,'seeds':SEEDS,'loads':LOADS,'cells':len(rows)},'groups':{}}
    for g,names in GROUPS.items():
      summary['groups'][g]={c:evaluate(rows,c,names) for c in CANDIDATES[1:]}
    summary['modifiability']={}
    for c,x in MODIFIABILITY.items():
      y=dict(x); y['star']=mod_score(x); y['avg_modules_changed']=(x['new_tier_modules']+x['new_data_class_modules'])/2
      summary['modifiability'][c]=y

    out=Path(__file__).resolve().parent/'out_v2_representative'; out.mkdir(exist_ok=True)
    with (out/'representative_runs.csv').open('w',newline='',encoding='utf-8') as f:
      w=csv.DictWriter(f,fieldnames=sorted(rows[0].keys()))
      w.writeheader(); w.writerows(rows)
    (out/'representative_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')

    def fm(v): return 'N/A' if v is None else f'{v:.3f}'
    def fci(v): return 'N/A' if not v else f'[{v[0]:.3f}, {v[1]:.3f}]'
    c1='C1-R2-emergency-resource'; c2='C2-R2-path-aware'
    lines=[
      '# DP1 Representative QA Evaluation',
      '',
      '> 6 representative scenarios, 5 seeds, 5 load points, 3 candidates = **450 cells**.',
      '> Serving SLO is not used. All stars are based on paired ratios vs As-Is.',
      '',
      '## Representative suite',
      '',
      '- Neutral/Control: `kv_b16_c32k`, `kv_b1_c32k_cold_cxl`',
      '- C1 Target / Resource Pressure: `hbm_pressure_ramp_b64`, `hbm_bw_shock_b256`',
      '- C2 Target / Data-Operation: `kv_b16_c32k_burst_chbm`, `rag_8tib_b64_ssd_pim`',
      '',
      '## QA table',
      '',
      '| QA | C1-R2 | C2-R2 | Quantitative basis |',
      '|---|:---:|:---:|---|',
    ]
    spec=[
      ('Performance Throughput — Overall','overall','throughput'),
      ('Performance Throughput — C1 Target','c1_target','throughput'),
      ('Performance Throughput — C2 Target','c2_target','throughput'),
      ('Performance Latency — TTFT — Overall','overall','ttft'),
      ('Performance Latency — TTFT — C1 Target','c1_target','ttft'),
      ('Performance Latency — TTFT — C2 Target','c2_target','ttft'),
      ('Performance Latency — TPOT — Overall','overall','tpot'),
      ('Performance Latency — TPOT — C1 Target','c1_target','tpot'),
      ('Performance Latency — TPOT — C2 Target','c2_target','tpot'),
      ('Resource Utilization — Overall','overall','resource'),
    ]
    for label,g,m in spec:
      a=summary['groups'][g][c1][m]; b=summary['groups'][g][c2][m]
      lines.append(f"| **{label}** | **{stars(a['star'])}** | **{stars(b['star'])}** | C1 {fm(a['ratio'])}x {fci(a['ci95'])}; C2 {fm(b['ratio'])}x {fci(b['ci95'])} |")
    ma=summary['modifiability'][c1]; mb=summary['modifiability'][c2]
    lines.append(f"| **Modifiability — Overall** | **{stars(ma['star'])}** | **{stars(mb['star'])}** | Avg modules changed: C1 {ma['avg_modules_changed']:.1f}, C2 {mb['avg_modules_changed']:.1f}; per-object behavior state fields: C1 {ma['per_object_behavior_state_fields']}, C2 {mb['per_object_behavior_state_fields']} |")
    lines += [
      '',
      '## Star thresholds',
      '',
      '- Throughput / Resource: >=1.10x with CI lower >=1 -> ★★★; 0.90~1.10 or CI includes 1 -> ★★☆; <0.90x with CI upper <1 -> ★☆☆',
      '- TTFT / TPOT: <=0.90x with CI upper <=1 -> ★★★; 0.90~1.10 or CI includes 1 -> ★★☆; >1.10x with CI lower >1 -> ★☆☆',
      '- Modifiability: average changed modules <=2 -> ★★★; <=3 -> ★★☆; >3 -> ★☆☆',
      '',
      '## Notes',
      '',
      '- `rag_8tib_b64_ssd_pim` is an architecture stress/reference for data-near GEMV, not a claim about realistic production vector-DB latency.',
      '- Representative scenarios are selected by mechanism coverage, not by post-hoc winner selection.',
    ]
    (out/'dp1-v2-representative-qa.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__': main()