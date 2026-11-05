"""BurstGPT(arXiv 2401.17644, Azure OpenAI 실트레이스, BurstGPT_1.csv: 61일, 1,429,737 요청)에서
'용량 대비 부하 ρ ≥ x인 구간'이 시간·요청 기준으로 얼마나 되는지 계산 (QA-02 고부하 빈도 근거).
용량 가정: 1분 요청률의 최대/p99.9/p99 중 하나에 맞춰 provision했다고 가정(=Baseline SLO 한계 처리량). [C]
사용: python burstgpt_load_stats.py <BurstGPT_1.csv>"""
import csv, json, sys
import numpy as np
ts = np.array([float(r["Timestamp"]) for r in csv.DictReader(open(sys.argv[1]))]); T = int(ts.max()) + 1
res = {}
for win in (60, 10):
    n = T // win + 1; c = np.bincount((ts // win).astype(int), minlength=n)[:n - 1] / win
    r_req = c[np.minimum((ts // win).astype(int), len(c) - 1)]
    d = dict(n=int(len(ts)), days=float(T / 86400), mean=float(c.mean()), median=float(np.median(c)), peak_to_mean=float(c.max() / c.mean()))
    for name, ref in (("max", c.max()), ("p99.9", np.percentile(c, 99.9)), ("p99", np.percentile(c, 99))):
        d[name] = {str(x): dict(time=float((c >= x * ref).mean()), req=float((r_req >= x * ref).mean())) for x in (0.5, 0.7, 0.9)}
    d["mu_mult"] = {str(k): dict(mu=float(k * c.mean()), time=float((c >= 0.7 * k * c.mean()).mean()), hours=float((c >= 0.7 * k * c.mean()).mean() * 24),
                                 req=float((r_req >= 0.7 * k * c.mean()).mean())) for k in (2, 3, 5, 10, 20, 50)}  # μ = 평균 요청률의 k배일 때 0.7μ 이상
    res[f"{win}s"] = d
json.dump(res, open(__file__.replace("burstgpt_load_stats.py", "burstgpt_load_stats.json"), "w"), indent=1)
print(json.dumps(res["60s"], indent=1)[:900])
