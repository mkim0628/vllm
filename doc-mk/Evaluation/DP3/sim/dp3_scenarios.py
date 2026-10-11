"""DP3 scenario set (single source; doc-mk/Evaluation/DP3/benchmark.md is generated from / mirrors this).

Common CB-1..3 realised for DP3 (8K ctx / 256 out, KV only, pressure knobs like DP1) + DP3 Stress + DP3 Dynamic.
Arrival rates are NOT set here: run_eval.py calibrates a nominal rate per (scenario, system) from the Baseline only (feasibility control).
"""
from dp3sim import Scenario

T = lambda *a: tuple(a)

COMMON = [
    Scenario("CB-1", "공통: 8K 문맥 재사용, HBM 압박 고정(KV 몫 12%)", "common", 8192, n_ctx=40, tier_frac=T(("hbm", 0.30), ("dram", 0.70)), kv_frac=0.12),
    Scenario("CB-2", "공통: CB-1과 같고 HBM 압박이 점진 증가", "common", 8192, n_ctx=40, tier_frac=T(("hbm", 0.30), ("dram", 0.70)), kv_frac=0.20, ramp=True),
    Scenario("CB-3", "공통: 다른 데이터가 HBM을 쓰는 혼합(KV 몫 50%)", "common", 8192, n_ctx=48, tier_frac=T(("hbm", 0.30), ("dram", 0.45), ("cxl_pnm", 0.25)), kv_frac=0.50),
]

STRESS = [
    Scenario("ST-01", "32K 문맥, DRAM에서 재사용", "stress", 32768, n_ctx=40, tier_frac=T(("hbm", 0.10), ("dram", 0.90))),
    Scenario("ST-02", "64K 문맥, DRAM에서 재사용", "stress", 65536, n_ctx=32, tier_frac=T(("hbm", 0.10), ("dram", 0.90))),
    Scenario("ST-03", "128K 문맥, DRAM에서 재사용", "stress", 131072, n_ctx=24, tier_frac=T(("hbm", 0.10), ("dram", 0.90))),
    Scenario("ST-04", "256K 문맥, CXL·DRAM 혼합", "stress", 262144, n_ctx=12, tier_frac=T(("hbm", 0.10), ("cxl_pnm", 0.30), ("dram", 0.60))),
    Scenario("ST-05", "128K 문맥이 SSD에 있는 차가운 재사용", "stress", 131072, n_ctx=24, tier_frac=T(("hbm", 0.10), ("dram", 0.20), ("ssd_pim", 0.70))),
    Scenario("ST-06", "128K 문맥이 HBF(GPU 직접 읽기)에 있음", "stress", 131072, n_ctx=24, tier_frac=T(("hbm", 0.10), ("hbf", 0.90))),
    Scenario("ST-07", "소수 문맥에 재사용 집중(hot set 작음)", "stress", 65536, n_ctx=40, zipf=1.4, tier_frac=T(("hbm", 0.25), ("dram", 0.75))),
    Scenario("ST-08", "재사용 분산(hot set 없음), 대부분 적재", "stress", 65536, n_ctx=40, zipf=0.0, tier_frac=T(("hbm", 0.10), ("dram", 0.90))),
    Scenario("ST-09", "긴 질의(2K) — prefill 비중이 큼", "stress", 65536, query_tokens=2048, n_ctx=32, tier_frac=T(("hbm", 0.10), ("dram", 0.90))),
    Scenario("ST-10", "짧은 질의(64) — 적재·attention 비중이 큼", "stress", 65536, query_tokens=64, n_ctx=32, tier_frac=T(("hbm", 0.10), ("dram", 0.90))),
    Scenario("ST-11", "128K 문맥 + HBM KV 몫 15%(동시성이 용량에 막힘)", "stress", 131072, n_ctx=24, tier_frac=T(("hbm", 0.10), ("dram", 0.90)), kv_frac=0.15),
    Scenario("ST-12", "대표 Query와 실제 Query가 멀다(정확도 조건)", "stress", 32768, n_ctx=40, mismatch=0.8, tier_frac=T(("hbm", 0.10), ("dram", 0.90))),
]

DYNAMIC = [
    Scenario("DY-01", "중간에 hot 문맥이 HBM에서 내려감", "dynamic", 65536, n_ctx=32, tier_frac=T(("hbm", 0.30), ("dram", 0.70)), shift_frac=T(("hbm", 0.0), ("dram", 1.0))),
    Scenario("DY-02", "도착률 burst(중간 1/3 구간 x2.5)", "dynamic", 65536, n_ctx=32, tier_frac=T(("hbm", 0.10), ("dram", 0.90)), burst=True),
    Scenario("DY-03", "128K 문맥 + HBM 압박이 점진 증가", "dynamic", 131072, n_ctx=24, tier_frac=T(("hbm", 0.10), ("dram", 0.90)), kv_frac=0.30, ramp=True),
]

ALL = COMMON + STRESS + DYNAMIC
BY_ID = {s.sid: s for s in ALL}
