"""QA-02 고부하 재정의: 고부하 = 서버 이용률 ρ = λ / λ_sat = 70% (λ_sat = 1/평균 서비스시간, SLO 무관).
이전 정의(Baseline SLO 한계 처리량 G_base의 70%)는 이 모델에서 ρ≈0.34에 불과해 큐잉 이론의 70% 꺾임과 같은 지점이 아니었다
(G_base ↔ ρ≈0.48). 평가 정의 오류 수정(룰 H16(i))이며 이전 값은 qa_evidence_out.json(qa2, 'superseded')에 보존.
출력: qa2_load_rho.json  (1) 곡선: Baseline P99 큐 대기 ÷ 평균 서비스시간 vs ρ  (2) 12 시나리오의 ρ=70% P99 감소율"""
import json
import numpy as np
src = open(__file__.replace("qa2_load_rho.py", "qa_evidence_models.py")).read().split("out={}")[0]
exec(src)

def run_full(tiers, overlap, n_sess, S, alpha, rate, seed, n_req=6000):
    rng = np.random.default_rng(seed)
    hit = lru_cache_sim(tiers, n_sess, S, alpha, n_req, rng)
    sz = S * B_KV; base = N_NEW / PREFILL_TPS; dec = N_OUT / DECODE_TPS_SHARE
    work = np.empty(n_req); busy = np.empty(n_req)
    for i, h in enumerate(hit):
        if h == -1: pre = (S + N_NEW) / PREFILL_TPS; vis = 0.0
        else:
            pre = base; bw = tiers[h][2]; vis = 0.0 if (bw is None or h == 0) else sz / bw * (1 - overlap)
        work[i] = pre + vis; busy[i] = pre + vis + dec
    arr = np.cumsum(rng.exponential(1 / rate, n_req)); t_free = 0.0
    wait = np.empty(n_req)
    for i in range(n_req):
        st = max(arr[i], t_free); wait[i] = st - arr[i]; t_free = st + busy[i]
    ttft = wait + work
    return wait[1000:], ttft[1000:], ttft[1000:] + N_OUT * TPOT, float(busy.mean())

def smean(tiers, ov, ns, S, sd):  # 평균 서비스시간은 도착률과 무관
    return run_full(tiers, ov, ns, S, 0.8, 1.0, sd)[3]

seeds = (11, 23, 37, 53, 71); alpha = 0.8
# (1) 곡선
rhos = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]; curve = []
for r in rhos:
    v = []
    for sd in seeds:
        sm = smean(TIERS_BASE, 0.0, 600, 16384, sd)
        w, *_ = run_full(TIERS_BASE, 0.0, 600, 16384, alpha, r / sm, sd); v.append(np.percentile(w, 99) / sm)
    curve.append(dict(rho=r, p99_wait_over_service=float(np.mean(v))))
mm1 = [dict(rho=float(r), p99=float(np.log(100 * r) / (1 - r))) for r in np.arange(0.30, 0.951, 0.01)]
# (2) 12 시나리오, ρ_base = 0.7
rows = []
for S in (16384, 32768, 65536):
    for ns in (150, 300, 600, 1200):
        e, t, ct = [], [], []
        for sd in seeds:
            sm = smean(TIERS_BASE, 0.0, ns, S, sd); lam = 0.7 / sm
            _, tb, eb, _ = run_full(TIERS_BASE, 0.0, ns, S, alpha, lam, sd)
            _, tc, ec, scand = run_full(TIERS_TIER, 0.7, ns, S, alpha, lam, sd)
            e.append(1 - np.percentile(ec, 99) / np.percentile(eb, 99)); t.append(1 - np.percentile(tc, 99) / np.percentile(tb, 99))
            ct.append(np.percentile(tc, 99))
        rows.append(dict(n_sess=ns, S=S, red_e2e=float(np.mean(e)), red_ttft=float(np.mean(t)), cand_p99_ttft=float(np.mean(ct))))
json.dump(dict(definition="rho=lambda/lambda_sat=0.7", curve=curve, mm1=mm1, scenarios=rows), open(__file__.replace(".py", ".json"), "w"), indent=1)
print([(c["rho"], round(c["p99_wait_over_service"], 2)) for c in curve])
for r in rows: print(r["S"], r["n_sess"], round(r["red_e2e"], 3), round(r["red_ttft"], 3), round(r["cand_p99_ttft"], 2))
