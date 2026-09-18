from __future__ import annotations
import ast, json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CHARS_PER_TOKEN=3.6
AA=4; A_CONST=2.94; E_EXP=1.10
C1_CLASSES={"ResourceStateMonitor","CandidateBuilder","C1MemoryCentric"}
C2_CLASSES={"DataClassifier","RuntimeStateMonitor","DataCharacteristicInterpreter","MemoryTierAffinityEvaluator","C2DataCentric"}

TASKS={
 "T1_new_resource_type":{
  "what":"New Resource Type",
  "C1":dict(DM=0,CM=0,IM=15,why="Registry/config-driven; integration validation only."),
  "C2":dict(DM=0,CM=0,IM=20,why="Registry/config-driven but affinity normalization needs broader integration validation.")},
 "T2_new_workload_data_operation":{
  "what":"New Workload/Data/Operation Type",
  "C1":dict(DM=0,CM=0,IM=10,why="C1 does not characterize data; descriptor feasibility/test update only."),
  "C2":dict(DM=15,CM=12,IM=35,why="Classifier prior + characteristic/affinity interpretation must be extended.")},
 "T3_new_constraint_slo":{
  "what":"New Constraint/SLO",
  "C1":dict(DM=8,CM=8,IM=20,why="Candidate/resource planner gets one additional constraint."),
  "C2":dict(DM=10,CM=10,IM=25,why="Selector and affinity/characteristic interaction must be retested.")},
 "T4_new_execution_decision_mode":{
  "what":"New Execution/Decision Mode",
  "C1":dict(DM=18,CM=15,IM=30,why="Resource scoring and final selection path extended."),
  "C2":dict(DM=22,CM=20,IM=40,why="Affinity + selector + characteristic interaction extended.")},
}

def source_segments(path:Path,names:set[str]):
    s=path.read_text(); lines=s.splitlines(True); tree=ast.parse(s)
    seg=[]
    for n in tree.body:
        if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names:
            seg.append("".join(lines[n.lineno-1:n.end_lineno]))
    return "\n".join(seg)

def cyclomatic(src:str):
    tree=ast.parse(src); c=1
    for n in ast.walk(tree):
        if isinstance(n,(ast.If,ast.For,ast.While,ast.Try,ast.IfExp,ast.Match)): c+=1
        elif isinstance(n,ast.BoolOp): c+=max(0,len(n.values)-1)
    return c

def software_understanding(cc):
    return 20 if cc<=10 else 30 if cc<=20 else 40

def measure():
    pol=ROOT/"policies.py"; shared=(ROOT/"model.py").read_text()
    src={"C1":source_segments(pol,C1_CLASSES),"C2":source_segments(pol,C2_CLASSES)}
    out={"chars_per_token":CHARS_PER_TOKEN,"tasks":{},"candidate":{}}
    for k in ("C1","C2"):
        chars=len(src[k]); sloc=len([x for x in src[k].splitlines() if x.strip() and not x.lstrip().startswith("#")])
        cc=cyclomatic(src[k]); out["candidate"][k]={"chars":chars,"sloc":sloc,"cyclomatic":cc}
    for tn,t in TASKS.items():
        row={"what":t["what"],"per_candidate":{}}
        for k in ("C1","C2"):
            p=t[k]; chars=out["candidate"][k]["chars"]; sloc=out["candidate"][k]["sloc"]; cc=out["candidate"][k]["cyclomatic"]
            su=software_understanding(cc); dm,cm,im=p["DM"],p["CM"],p["IM"]
            aaf=.4*dm+.3*cm+.3*im
            esloc=sloc*(AA+aaf+su)/100
            pm=A_CONST*(max(esloc,1)/1000)**E_EXP if esloc else 0
            read_tokens=(len(shared)+chars)/CHARS_PER_TOKEN
            write_tokens=chars*(cm/100)/CHARS_PER_TOKEN
            row["per_candidate"][k]={"why":p["why"],"DM":dm,"CM":cm,"IM":im,"SU":su,"AAF":round(aaf,2),
                "ESLOC":round(esloc,1),"person_months":round(pm,4),
                "read_tokens":round(read_tokens),"write_tokens":round(write_tokens),
                "total_tokens":round(read_tokens+write_tokens)}
        out["tasks"][tn]=row
    out["totals"]={}
    for k in ("C1","C2"):
        pm=sum(out["tasks"][t]["per_candidate"][k]["person_months"] for t in TASKS)
        tok=sum(out["tasks"][t]["per_candidate"][k]["total_tokens"] for t in TASKS)
        pm_star=3 if pm<=.25 else 2 if pm<=1 else 1
        tok_star=3 if tok<=20000 else 2 if tok<=50000 else 1
        out["totals"][k]={"person_months":round(pm,4),"person_days":round(pm*19,2),"tokens":tok,
                          "pm_star":pm_star,"token_star":tok_star,"final_star":min(pm_star,tok_star)}
    return out

if __name__=="__main__":
    r=measure(); (ROOT/"modifiability_results.json").write_text(json.dumps(r,indent=2,ensure_ascii=False)); print(json.dumps(r["totals"],indent=2))
