from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

from model import load_system
from scenarios import scenarios
from simulator import run_sim

SEEDS=[11,23,37,51,71]
LOAD_SCALES=(0.25,0.50,0.75,1.00,1.25)
CANDIDATES=(
    'As-Is-HBM-first',
    'C1-memory-centric',
    'C1-R-stable-resource',
    'C1-R2-emergency-resource',
    'C2-data-centric',
    'C2-R-feasibility-stable',
    'C2-R2-path-aware',
)
ROBUSTNESS={'classifier_error','six_tier_capacity_stress'}
C1_CASES={
    'hbm_pressure_ramp_b64','hbm_bw_shock_b256','host_path_pressure_b64',
    'data_mix_shift_b64','mixed_all_ai_data_b64',
}
C2_CASES={
    'rag_8tib_b64_ssd_pim','rag_8tib_b256_ssd_pim',
    'kv_b16_c32k_burst_chbm','kv_b1_c32k_cold_cxl',
    'kv_mispredict_dram_wait','agent_memory_long_lived',
}

def geom(vals):
    xs=[max(1e-12,float(v)) for v in vals]
    return math.exp(sum(math.log(x) for x in xs)/len(xs)) if xs else None

def ci95_log(vals):
    if not vals: return None
    logs=[math.log(max(1e-12,float(x))) for x in vals]
    if len(logs)<2:
        v=math.exp(logs[0]); return [v,v]
    m=statistics.mean(logs)
    h=1.96*statistics.stdev(logs)/math.sqrt(len(logs))
    return [math.exp(m-h),math.exp(m+h)]

def star_high(ratio,ci):
    if ratio is None or ci is None: return None
    lo,hi=ci
    if ratio>=1.10 and lo>=1.0: return 3
    if ratio<0.90 and hi<1.0: return 1
    return 2

def star_low(ratio,ci):
    if ratio is None or ci is None: return None
    lo,hi=ci
    if ratio<=0.90 and hi<=1.0: return 3
    if ratio>1.10 and lo>1.0: return 1
    return 2

def stars(n):
    return 'N/A' if n is None else '★'*n+'☆'*(3-n)

def paired_group(rows,candidate,names):
    base={(r['scenario'],r['seed'],r['load_scale']):r for r in rows
          if r['candidate']=='As-Is-HBM-first' and r['scenario'] in names}
    cand={(r['scenario'],r['seed'],r['load_scale']):r for r in rows
          if r['candidate']==candidate and r['scenario'] in names}
    cells=sorted({(sc,seed) for sc,seed,_ in base})
    defs={
        'throughput':('token_throughput',star_high),
        'ttft':('ttft_p99_ms',star_low),
        'tpot':('tpot_p99_ms',star_low),
    }
    out={}
    for label,(metric,star_fn) in defs.items():
        cell_ratios=[]
        for sc,seed in cells:
            load_ratios=[]
            for load in LOAD_SCALES:
                k=(sc,seed,load)
                if k not in base or k not in cand: continue
                load_ratios.append(cand[k][metric]/max(1e-12,base[k][metric]))
            if load_ratios:
                cell_ratios.append(geom(load_ratios))
        ratio=geom(cell_ratios)
        ci=ci95_log(cell_ratios)
        out[label]={
            'ratio':ratio,'ci95':ci,'star':star_fn(ratio,ci),
            'paired_scenario_seeds':len(cell_ratios)
        }
    return out

def resource_mean(rows,candidate,names):
    rs=[r for r in rows if r['candidate']==candidate and r['scenario'] in names]
    return statistics.mean(r['resource_index'] for r in rs)

def write_report(path,summary):
    p=summary['performance']
    def fmt(x): return 'N/A' if x is None else f'{x:.3f}'
    def fci(x): return 'N/A' if x is None else f'[{x[0]:.3f}, {x[1]:.3f}]'
    lines=[
        '# DP1 V2 Evaluation — Pure System Performance',
        '',
        '> Performance QA does not use serving SLO. Same HW / trace / offered load are compared directly against As-Is.',
        '> Throughput: higher is better. TTFT/TPOT: lower is better.',
        '> Load sweep is collapsed per (scenario, seed), then aggregated across scenario-seed pairs.',
        '',
        '## 1. QA 평가표',
        '',
        '| QA | C1-R2 | C2-R2 | As-Is 대비 ratio |',
        '|---|:---:|:---:|---|',
    ]
    spec=[
        ('Performance Throughput — Overall','overall','throughput'),
        ('Performance Throughput — C1 유리 Case','c1','throughput'),
        ('Performance Throughput — C2 유리 Case','c2','throughput'),
        ('Performance Latency — TTFT — Overall','overall','ttft'),
        ('Performance Latency — TTFT — C1 유리 Case','c1','ttft'),
        ('Performance Latency — TTFT — C2 유리 Case','c2','ttft'),
        ('Performance Latency — TPOT — Overall','overall','tpot'),
        ('Performance Latency — TPOT — C1 유리 Case','c1','tpot'),
        ('Performance Latency — TPOT — C2 유리 Case','c2','tpot'),
    ]
    for label,g,m in spec:
        a=p[g]['C1-R2-emergency-resource'][m]
        b=p[g]['C2-R2-path-aware'][m]
        lines.append(f"| **{label}** | **{stars(a['star'])}** | **{stars(b['star'])}** | C1 {fmt(a['ratio'])}x {fci(a['ci95'])}; C2 {fmt(b['ratio'])}x {fci(b['ci95'])} |")
    lines += [
        f"| **Resource Utilization — Overall** | **{stars(summary['resource_star']['C1-R2-emergency-resource'])}** | **{stars(summary['resource_star']['C2-R2-path-aware'])}** | RUI C1 {summary['resource']['C1-R2-emergency-resource']:.3f}; C2 {summary['resource']['C2-R2-path-aware']:.3f} |",
        '| **Modifiability — Overall** | 재산정 필요 | 재산정 필요 | R2 구조 기준 별도 측정 필요 |',
        '',
        '### 별점 기준',
        '',
        '- Throughput: >=1.10x and CI lower >=1.0 => ★★★; 0.90~1.10 or CI includes 1 => ★★☆; <0.90x and CI upper <1.0 => ★☆☆',
        '- TTFT/TPOT: <=0.90x and CI upper <=1.0 => ★★★; 0.90~1.10 or CI includes 1 => ★★☆; >1.10x and CI lower >1.0 => ★☆☆',
        '',
        '## 2. Case Group',
        '',
        '**C1 유리 Case — Resource-pressure 중심**',
        '',
        '- `hbm_pressure_ramp_b64`',
        '- `hbm_bw_shock_b256`',
        '- `host_path_pressure_b64`',
        '- `data_mix_shift_b64`',
        '- `mixed_all_ai_data_b64`',
        '',
        '**C2 유리 Case — Data-aware / Data-near / Lifecycle 중심**',
        '',
        '- `kv_b16_c32k_burst_chbm`',
        '- `kv_b1_c32k_cold_cxl`',
        '- `kv_mispredict_dram_wait`',
        '- `agent_memory_long_lived`',
        '- `rag_8tib_b64_ssd_pim`',
        '- `rag_8tib_b256_ssd_pim`',
        '',
        '## 3. C1 case에서 C2 Performance가 더 좋을 수 있는 이유',
        '',
        'C1-case는 C1이 실제 winner라는 뜻이 아니라 resource-pressure mechanism이 필요해지는 workload group이다.',
        'C1-R2 Emergency Pressure Policy는 HBM pressure relief를 우선해 KV를 remote/restore path로 이동할 수 있다. 그 결과 HBM pressure/RUI는 좋아져도 remote Attention, activation round-trip, restore cost가 TPOT critical path에 들어가 Throughput/TPOT가 악화될 수 있다.',
        'C2-R2는 Data/Operation cost와 Performance Guard를 사용하므로 offload가 end-to-end performance에 손해면 HBM/As-Is path를 유지한다. 그래서 resource 분산은 덜 적극적이어도 Throughput/TPOT를 더 잘 보존할 수 있다.',
        '',
        '## 4. Measurement boundary',
        '',
        '- SLO/Admission/Autoscaling policy는 serving layer 책임이며 DP1 Performance QA에는 사용하지 않는다.',
        '- TTFT는 network/HTTP가 아니라 model/runtime first-token readiness다.',
        '- Migration execution 자체는 DP4 범위이며 여기서는 path-cost proxy를 포함한다.',
    ]
    path.write_text('\n'.join(lines),encoding='utf-8')

def main():
    system=load_system(Path(__file__).resolve().parents[1]/'configs')
    out=Path(__file__).resolve().parent/'out_v2_pure'
    out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for sc in scenarios():
        for seed in SEEDS:
            for c in CANDIDATES:
                for load in LOAD_SCALES:
                    rows.append(run_sim(system,sc,seed,c,load))
    normal={s.name for s in scenarios() if s.name not in ROBUSTNESS}
    perf={
        'overall':{c:paired_group(rows,c,normal) for c in CANDIDATES},
        'c1':{c:paired_group(rows,c,C1_CASES) for c in CANDIDATES},
        'c2':{c:paired_group(rows,c,C2_CASES) for c in CANDIDATES},
    }
    resource={c:resource_mean(rows,c,normal) for c in CANDIDATES}
    resource_star={c:(3 if resource[c]>=.85 else 2 if resource[c]>=.65 else 1) for c in CANDIDATES}
    summary={'meta':{'seeds':SEEDS,'load_scales':LOAD_SCALES,'scenario_count':len(scenarios())},
             'performance':perf,'resource':resource,'resource_star':resource_star}
    (out/'pure_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    write_report(out/'dp1-v2-pure-performance.md',summary)
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__':
    main()