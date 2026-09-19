from __future__ import annotations

import csv, json, math, statistics
from pathlib import Path
from model import load_system
from scenarios import scenarios
from simulator import run_sim

SEEDS=[11,23,37,51,71]
LOADS=[0.25,0.50,0.75,1.00,1.25]
CANDIDATES=['As-Is-HBM-first','C1-R2-emergency-resource','C2-R2-path-aware']
SCENARIOS={
  'kv_b16_c32k',
  'kv_b1_c32k_cold_cxl',
  'host_path_pressure_b64',
  'data_mix_shift_b64',
  'rag_8tib_b64_ssd_pim',
  'mixed_all_ai_data_b64',
  'kv_mispredict_dram_wait',
  'moe_expert_skew_b256',
}

MODIFIABILITY={
  'C1-R2-emergency-resource': {
    'new_tier_modules':3,
    'new_data_class_modules':2,
    'per_object_behavior_state_fields':0,
  },
  'C2-R2-path-aware': {
    'new_tier_modules':4,
    'new_data_class_modules':4,
    'per_object_behavior_state_fields':5,
  },
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

def cell_ratios(rows,num,den,metric):
    a={(r['scenario'],r['seed'],r['load_scale']):r for r in rows if r['candidate']==num}
    b={(r['scenario'],r['seed'],r['load_scale']):r for r in rows if r['candidate']==den}
    cells=[]
    for sc in sorted(SCENARIOS):
      for seed in SEEDS:
        vals=[]
        for load in LOADS:
          k=(sc,seed,load)
          if k in a and k in b:
            vals.append(a[k][metric]/max(1e-12,b[k][metric]))
        if vals: cells.append(geom(vals))
    return cells

def metric_summary(rows,candidate,metric):
    xs=cell_ratios(rows,candidate,'As-Is-HBM-first',metric)
    return {'ratio':geom(xs),'ci95':ci95_log(xs),'pairs':len(xs)}

def severe_loss(summary,higher):
    r=summary['ratio']; lo,hi=summary['ci95']
    if higher:
        return r<.90 and hi<1.0
    return r>1.10 and lo>1.0

def comparative_stars(c1,c2,higher):
    # Architecture-comparison star: use a 1% deadband so small but real
    # differences are visible. The better candidate gets 3 stars; the other
    # gets 2 unless it also has a severe As-Is regression, in which case 1.
    r1=c1['ratio']; r2=c2['ratio']
    rel=(r2/r1) if higher else (r1/r2)  # >1 means C2 is better
    if abs(rel-1.0)<=.01:
        return 2,2,rel
    c2_better=rel>1.0
    if c2_better:
        s2=3
        s1=1 if severe_loss(c1,higher) else 2
    else:
        s1=3
        s2=1 if severe_loss(c2,higher) else 2
    return s1,s2,rel

def stars(n): return '★'*n+'☆'*(3-n)

def main():
    system=load_system(Path(__file__).resolve().parents[1]/'configs')
    scmap={s.name:s for s in scenarios()}
    rows=[]
    for name in sorted(SCENARIOS):
      for seed in SEEDS:
        for cand in CANDIDATES:
          for load in LOADS:
            rows.append(run_sim(system,scmap[name],seed,cand,load))

    c1='C1-R2-emergency-resource'; c2='C2-R2-path-aware'
    metrics={
      'throughput':('token_throughput',True),
      'ttft':('ttft_p99_ms',False),
      'tpot':('tpot_p99_ms',False),
      'resource_utilization':('resource_index',True),
    }
    summary={'meta':{'scenarios':sorted(SCENARIOS),'seeds':SEEDS,'loads':LOADS,'cells':len(rows)},'metrics':{}}
    for name,(field,higher) in metrics.items():
      a=metric_summary(rows,c1,field); b=metric_summary(rows,c2,field)
      s1,s2,rel=comparative_stars(a,b,higher)
      summary['metrics'][name]={'C1':a,'C2':b,'C1_star':s1,'C2_star':s2,'C2_vs_C1_benefit_ratio':rel}

    summary['modifiability']={}
    for cand,x in MODIFIABILITY.items():
      y=dict(x)
      y['avg_modules_changed']=(x['new_tier_modules']+x['new_data_class_modules'])/2
      summary['modifiability'][cand]=y
    m1=summary['modifiability'][c1]['avg_modules_changed']
    m2=summary['modifiability'][c2]['avg_modules_changed']
    summary['modifiability']['C1_star']=3 if m1<m2 else 2
    summary['modifiability']['C2_star']=1 if m2/m1>=1.25 else 2

    out=Path(__file__).resolve().parent/'out_v2_tradeoff'; out.mkdir(exist_ok=True)
    with (out/'tradeoff_runs.csv').open('w',newline='',encoding='utf-8') as f:
      w=csv.DictWriter(f,fieldnames=sorted(rows[0].keys())); w.writeheader(); w.writerows(rows)
    (out/'tradeoff_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')

    def fm(v): return f'{v:.3f}'
    def fci(v): return f'[{v[0]:.3f}, {v[1]:.3f}]'
    lines=[
      '# DP1 C1 vs C2 Overall Trade-off QA',
      '',
      '> 8 representative scenarios × 5 seeds × 5 loads × 3 candidates = **600 cells**.',
      '> Overall only. No C1-favorable / C2-favorable subgroup scoring.',
      '> Architecture-level simulation; not a real B200/vLLM hardware benchmark.',
      '',
      '## Comparative star rule',
      '',
      '- C1/C2 차이가 1% 이내면 둘 다 ★★☆.',
      '- 1%를 넘으면 더 좋은 후보는 ★★★, 다른 후보는 ★★☆.',
      '- 단, 뒤지는 후보가 As-Is 대비 severe regression까지 보이면 ★☆☆.',
      '- Modifiability는 average changed modules가 작은 쪽 ★★★; 25% 이상 큰 쪽은 ★☆☆.',
      '',
      '## Overall QA',
      '',
      '| QA | C1 Resource-centric | C2 Data-centric | As-Is 대비 / 후보 간 차이 |',
      '|---|:---:|:---:|---|',
    ]
    labels={'throughput':'Performance Throughput','ttft':'Performance TTFT','tpot':'Performance TPOT','resource_utilization':'Resource Utilization'}
    for k in ('throughput','ttft','tpot','resource_utilization'):
      m=summary['metrics'][k]; a=m['C1']; b=m['C2']; rel=m['C2_vs_C1_benefit_ratio']
      direction='C2 benefit' if rel>1 else 'C1 benefit'
      delta=abs(rel-1)*100
      lines.append(f"| **{labels[k]}** | **{stars(m['C1_star'])}** | **{stars(m['C2_star'])}** | C1 {fm(a['ratio'])}x {fci(a['ci95'])}; C2 {fm(b['ratio'])}x {fci(b['ci95'])}; {direction} **{delta:.1f}%** |")
    mod=summary['modifiability']
    lines.append(f"| **Modifiability** | **{stars(mod['C1_star'])}** | **{stars(mod['C2_star'])}** | Avg changed modules C1 **{m1:.1f}**, C2 **{m2:.1f}**; object behavior state fields C1 **0**, C2 **5** |")
    lines += ['', '## Interpretation boundary', '',
      '- C1 decode placement is part of deterministic Data-Memory Affinity: context/batch + Attention capability + static decode cost are available without runtime data monitoring.',
      '- Therefore any remaining C2 performance advantage must come from object-level Data behavior handling or avoiding resource-centric placement trade-offs, not from simply knowing where KV decode is faster.',
      '- C1 monitors Memory Resource Capacity/BW/Pressure trends; C2 monitors Data-object Access/Reuse/Idle/Lifetime. C2 is not implemented as a superset of C1 Resource State Monitoring.',
    ]
    (out/'dp1-v2-overall-tradeoff-qa.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__': main()