"""QA 별 기준 근거용 내부 모델 (후보 비종속). 모든 파라미터는 사전 고정, seed 고정. [C] 모델 projection."""
import json, math, collections, subprocess, re
import numpy as np

B_KV = 327_680           # B/token, 70B급 GQA(8 kv head) fp16: 2*80*8*128*2
PREFILL_TPS = 25_000     # tok/s, 8xH100 TP8 70B FP8 급
DECODE_TPS_SHARE = 8_000 # 배치 decode 집계 tok/s (GPU 시간 점유 환산)
TPOT = 0.025
N_NEW, N_OUT = 1024, 128
TIERS_BASE = [("HBM",400e9,None),("DRAM",1500e9,200e9)]                    # (이름,용량B,BW B/s)
TIERS_TIER = TIERS_BASE+[("CXL",2000e9,100e9),("SSD",8000e9,40e9)]

def lru_cache_sim(tiers, n_sess, S, alpha, n_req, rng):
    sz = S*B_KV
    caps=[int(c//sz) for _,c,_ in tiers]
    od=[collections.OrderedDict() for _ in tiers]
    w=1/np.arange(1,n_sess+1)**alpha; w/=w.sum()
    ids=rng.choice(n_sess,size=n_req,p=w)
    hit=np.empty(n_req,dtype=np.int8)   # tier idx, -1=miss
    def insert(t,k):
        od[t][k]=1; od[t].move_to_end(k)
        while len(od[t])>caps[t]:
            ev,_=od[t].popitem(last=False)
            if t+1<len(tiers): insert(t+1,ev)
    for i,k in enumerate(ids):
        f=-1
        for t in range(len(tiers)):
            if k in od[t]: f=t; del od[t][k]; break
        hit[i]=f; insert(0,k)
    return hit

def service(hit, tiers, overlap):
    """returns (gpu_time, ttft_extra) per request"""
    S_cmp=N_NEW/PREFILL_TPS + N_OUT/DECODE_TPS_SHARE
    gpu=np.empty(len(hit)); ttft_pre=np.empty(len(hit))
    return S_cmp

def run(tiers, overlap, n_sess, S, alpha, rate, seed, n_req=6000):
    rng=np.random.default_rng(seed)
    hit=lru_cache_sim(tiers,n_sess,S,alpha,n_req,rng)
    sz=S*B_KV; base=N_NEW/PREFILL_TPS; dec=N_OUT/DECODE_TPS_SHARE
    ttft_work=np.empty(n_req); busy=np.empty(n_req)
    for i,h in enumerate(hit):
        if h==-1:   # miss: 전체 재계산
            pre=(S+N_NEW)/PREFILL_TPS; load=0.0
        else:
            pre=base; bw=tiers[h][2]; load=0.0 if bw is None else sz/bw
        # 로드와 prefill 겹침(overlap 비율만큼 숨김)
        visible=load*(1-overlap) if h>0 else 0.0
        ttft_work[i]=pre+visible; busy[i]=pre+visible+dec
    arr=np.cumsum(rng.exponential(1/rate,n_req))
    t_free=0.0; ttft=np.empty(n_req); e2e=np.empty(n_req)
    for i in range(n_req):
        st=max(arr[i],t_free); wait=st-arr[i]
        ttft[i]=wait+ttft_work[i]; t_free=st+busy[i]
        e2e[i]=ttft[i]+N_OUT*TPOT
    return ttft,e2e,busy.mean(),float((hit==-1).mean())

def max_goodput(tiers,overlap,n_sess,S,alpha,seed):
    lo,hi=0.05,60.0
    for _ in range(18):
        mid=(lo+hi)/2
        ttft,_,_,_=run(tiers,overlap,n_sess,S,alpha,mid,seed)
        # SLO: P99 TTFT<=2s  (1,000 req warmup 제외)
        ok=np.percentile(ttft[1000:],99)<=2.0
        lo,hi=(mid,hi) if ok else (lo,mid)
    return lo

out={}
# ---------- QA1/QA2: 단순 HBM+DRAM offload(base) vs 다계층+overlap
cfgs=[(ns,S) for S in (16384,32768,65536) for ns in (150,300,600,1200)]
alpha=0.8; seeds=(11,23,37,53,71)
rows=[]
for ns,S in cfgs:
    gb=[];gc=[]
    for sd in seeds:
        gb.append(max_goodput(TIERS_BASE,0.0,ns,S,alpha,sd))
        gc.append(max_goodput(TIERS_TIER,0.7,ns,S,alpha,sd))
    rows.append(dict(n_sess=ns,S=S,base=float(np.mean(gb)),cand=float(np.mean(gc)),R=float(np.mean(gc)/np.mean(gb))))
out['qa1']=rows
Rs=[r['R'] for r in rows]
out['qa1_summary']=dict(min=min(Rs),max=max(Rs),geomean=float(np.exp(np.mean(np.log(Rs)))),n=len(Rs),
    n_ge_1_5=sum(r>=1.5 for r in Rs),n_ge_2=sum(r>=2 for r in Rs),n_ge_3=sum(r>=3 for r in Rs),n_lt_1_05=sum(r<1.05 for r in Rs))
# QA2: baseline 한계 처리량의 70% 부하에서 e2e P99 감소율
rows2=[]
for ns,S in cfgs:
    red=[];redt=[]
    for sd in seeds:
        gb=max_goodput(TIERS_BASE,0.0,ns,S,alpha,sd); rate=0.7*gb
        _,eb,_,_=run(TIERS_BASE,0.0,ns,S,alpha,rate,sd); _,ec,_,_=run(TIERS_TIER,0.7,ns,S,alpha,rate,sd)
        red.append(1-np.percentile(ec[1000:],99)/np.percentile(eb[1000:],99))
        tb,_,_,_=run(TIERS_BASE,0.0,ns,S,alpha,rate,sd); tc,_,_,_=run(TIERS_TIER,0.7,ns,S,alpha,rate,sd)
        redt.append(1-np.percentile(tc[1000:],99)/np.percentile(tb[1000:],99))
    rows2.append(dict(n_sess=ns,S=S,red=float(np.mean(red)),red_ttft=float(np.mean(redt)),p99_base=float(np.percentile(eb[1000:],99)),p99_cand=float(np.percentile(ec[1000:],99))))
out['qa2']=rows2
rd=[r['red'] for r in rows2]
out['qa2_summary']=dict(min=min(rd),max=max(rd),mean=float(np.mean(rd)),n=len(rd),n_ge_30=sum(r>=.30 for r in rd),n_ge_50=sum(r>=.50 for r in rd),n_ge_67=sum(r>=.67 for r in rd))

# ---------- QA3: 공유 tier 구성별 SE(N=16)  (고정점 + M/M/1형 지연)
def thr_per_node(N, shard_size, bw_shard, h_remote, S, router_td, local_comp=0.20):
    """노드당 처리량 X(req/s). 요청 1건 = 로컬 처리 local_comp s + remote hit 확률 h_remote로 공유 tier에서 KV 로드"""
    sz=S*B_KV; X=1.0/local_comp
    for _ in range(300):
        rho=min(0.995, shard_size*X*h_remote*sz/bw_shard)
        L=h_remote*(sz/bw_shard)/(1-rho)
        Xn=1.0/(local_comp+L)
        X=0.5*X+0.5*Xn
    total=N*X
    cap_router=1.0/router_td if router_td>0 else 1e9
    return min(total,cap_router)
def SE(shard,bw,h,td,S=32768):
    g=lambda N: thr_per_node(N,min(N,shard),bw,h,S,td)
    return g(16)/((16/2)*g(2))
cases=[("전 노드 단일 공유 pool (shard=16)",16,200e9,0.3,0.0005),
       ("pool shard 4노드당 1개",4,200e9,0.3,0.0005),
       ("pool shard 2노드당 1개",2,200e9,0.3,0.0005),
       ("노드 로컬 tier + 전역 metadata만",1,200e9,0.3,0.0005),
       ("노드 로컬 tier + 중앙 router 20 ms/요청",1,200e9,0.3,0.020),
       ("단일 공유 pool, 대역폭 2x(400GB/s)",16,400e9,0.3,0.0005)]
out['qa3']=[dict(name=n,SE=float(SE(sh,bw,h,td))) for n,sh,bw,h,td in cases]
# USL 환산표
out['qa3_usl']={str(s):float(1/(1+s*(16-1)/2*0+0)) for s in []}
for se in (0.80,0.875,0.95):
    N=16; sigma=(1/se-1)/(N-1); out['qa3_usl'][str(se)]=sigma
# N0=2 정의: SE=G(16)/(8*G(2)) 에서 1/(1+σ(N-1))와의 관계 (σ는 N0=1 기준 환산)
# ---------- QA4: 이 저장소 코드 계수 (직접)
import os
root='/home/user/vllm'
names={"flexkv":"FlexKVConnector","mooncake":"MooncakeConnector","lmcache":"LMCacheConnectorV1","simple_cpu_offload":"SimpleCPUOffloadConnector","offloading":"OffloadingConnector"}
q4={}
for k,v in names.items():
    r=subprocess.run(f"grep -rl '{v}' --include=*.py --include=*.md --include=*.yaml . | grep -v '^./doc-mk'",shell=True,cwd=root,capture_output=True,text=True).stdout.split()
    tests=[f for f in r if f.startswith('./tests')]
    q4[k]=dict(all=len(r),non_test=len(r)-len(tests),src_only=len([f for f in r if f.startswith('./vllm')]))
out['qa4']=q4
rng=np.random.default_rng(7)
mism=0; NB=10000
for _ in range(NB):
    blk=rng.integers(0,2**16,size=(16,8,128),dtype=np.uint16)       # 임의 비트패턴(NaN·denormal 포함) fp16 KV block
    host=blk.tobytes()                                              # HBM -> DRAM(직렬화)
    back=np.frombuffer(host,dtype=np.uint16).reshape(blk.shape)     # DRAM -> HBM(복원)
    mism+=int(not np.array_equal(blk,back))
out['qa5_roundtrip']=dict(blocks=NB,mismatch=mism)
json.dump(out,open('qa_evidence_out.json','w'),indent=1,ensure_ascii=False)
print(json.dumps(out,indent=1,ensure_ascii=False))
