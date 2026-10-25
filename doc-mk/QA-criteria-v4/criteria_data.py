"""QA 평가 기준(GPU-only 대비 5구간), DP 후보별 소유자 별, 이론 계산 기반 절대 예상값.

기준 체계 (사용자 확정 2026-10-24)
- Baseline = B0(GPU-only). 모든 수치는 B0 대비 변화량으로 쓴다.
- ★1 = Stakeholder 요구(B0 대비). QA마다 값이 다르다. 변경 용이성은 근거로 정한 값.
- ★2 = 경쟁 기술(KV offload·재사용 시스템)이 B0 대비 보고한 대표 수준. 여러 문헌의 headline 개선의 중앙값(Q1) 등으로 정한다.
- ★3 = 경쟁 기술 위에서 우리가 목표하는 수준. Q2·Q3는 ★2 × 1.5(offload baseline 대비 문헌 개선 1.2x~1.83x의 중간),
  Q1은 문헌 상위권(비극단 최고 7.8x)에 맞춘 8x = ★2의 2배.
- ★1.5, ★2.5는 인접 앵커의 중점(비율 지표는 기하 중점).
B1(단순 offload)은 우리가 정의한 경쟁 기술 대리(theory_model.B1)이고, 그 이론값이 ★2 근처에 놓이는지 확인용으로 병기한다.
"""
import theory_model as tm

STAR_STEPS = [1.0, 1.5, 2.0, 2.5, 3.0]


def _stars(value, edges, higher_is_better=True):
    s = 0.0
    for star, e in zip(STAR_STEPS, edges):
        ok = value >= e - 1e-9 if higher_is_better else value <= e + 1e-9
        if ok:
            s = star
    return s


# ---- 구간 경계 (B0 대비) -----------------------------------------------------
COMP_FACTOR = 1.5                                  # Q2·Q3: ★3 = ★2 × 1.5, Q1: ★3 = ★2 × 2
# Q1 근거 표본: KV offload·재사용·상태 보존 시스템의 headline 개선(GPU-only/stateless baseline 대비, 처리량 계열)
Q1_LIT = [("Mooncake 실트래픽 +75% 요청", 1.75), ("InferCept 1.6~2x(상단)", 2.0), ("LMCache 단일 노드 CPU offload 하한", 2.3),
          ("Pensieve 1.14~3.0x(상단)", 3.0), ("LMCache 실서비스 QPS 확장 4~6x(중간)", 5.0), ("Mooncake 시뮬 +525%", 6.25),
          ("AttentionStore prefill 처리량 7.8x", 7.8), ("LMCache 최대 14x", 14.0)]
EDGES = {
    "Q1": [2.0, 2.8, 4.0, 5.7, 8.0],                # R = 후보 ÷ B0 (★2 4x = 문헌 8건 중앙값, ★3 8x = 문헌 상위권, ★ 1단계 = 2배)
    "Q2": [20, 30, 40, 50, 60],                    # HBM 사용량 감소율 % (B0 대비, ★2 40% = 오프로딩 문헌, ★3 = 잔여 60%/1.5)
    "Q3": [1.43, 1.7, 2.0, 2.45, 3.0],             # r = √(TTFT 개선 × TPOT 개선, P99) vs B0 (★1 감소율 30%, ★2 50%, ★3 = 2.0×1.5)
    "Q4": [80, 85, 90, 92.5, 95],                  # SE(N=16) %
    "Q5_module": [5, 4, 3, 2.5, 2],                # 판정은 module 수만. M/M은 아래 상수로 환산한 값(별 조건 아님)
}
# module 수 → M/M 환산: module 1개 = 고정 3일 + 24 LOC ÷ 40 LOC/일 × 오버헤드 2.0 = 4.2일 = 0.2 MM (21일/MM)
Q5_FIXED_DAYS, Q5_LOC_PER_MODULE, Q5_PROD, Q5_OVH, Q5_DAYS_PER_MM = 3.0, 24, 40.0, 2.0, 21.0
MM_PER_MODULE = (Q5_FIXED_DAYS + Q5_LOC_PER_MODULE / Q5_PROD * Q5_OVH) / Q5_DAYS_PER_MM      # 0.2


def mm_of_modules(n):
    return n * MM_PER_MODULE


# 에이전트(Claude Sonnet 5.5) 토큰 비용 — 참고 지표(별점 아님). 산식·상수는 DP1/qa4-preregistration.md M3를 실제 LOC 기준으로 옮긴 것
SONNET55 = dict(p_in=2.0, p_cache=0.2, p_out=10.0)         # $/MTok (Anthropic 공개 가격표, 2026-10 확인)
TOK = dict(tpl=12, S_mod=356, a_read=1.5, C0=25_000, n0=10, n_m=5, n_iter=2, o_turn=300)


def token_cost(n, price=SONNET55):
    """module n개 변경 시 에이전트 1세션 비용. 반환 (총 토큰, 달러)."""
    t = TOK
    c_bar = t["C0"] + t["a_read"] * t["tpl"] * t["S_mod"] * n
    turns = t["n0"] + t["n_m"] * n
    t_out = t["tpl"] * Q5_LOC_PER_MODULE * n * t["n_iter"] + t["o_turn"] * turns
    usd = (c_bar * price["p_in"] + turns * c_bar * price["p_cache"] + t_out * price["p_out"]) / 1e6
    return c_bar + turns * c_bar + t_out, usd


def fmt_q(x):
    """query/s 표기: 10 미만은 소수 2자리, 이상은 소수 1자리."""
    return format(x, ",.2f") if x < 10 else format(x, ",.1f")


def red_of_r(r):
    return (1 - 1 / r) * 100


BAND_TEXT = {
    "Q1": {1: "2.0 ≤ R < 2.8", 1.5: "2.8 ≤ R < 4.0", 2: "4.0 ≤ R < 5.7", 2.5: "5.7 ≤ R < 8.0", 3: "R ≥ 8.0", 0: "R < 2.0"},
    "Q2": {1: "20 ≤ 감소율 < 30%", 1.5: "30 ≤ 감소율 < 40%", 2: "40 ≤ 감소율 < 50%", 2.5: "50 ≤ 감소율 < 60%", 3: "감소율 ≥ 60%", 0: "감소율 < 20%"},
    "Q3": {1: "1.43 ≤ r < 1.7", 1.5: "1.7 ≤ r < 2.0", 2: "2.0 ≤ r < 2.45", 2.5: "2.45 ≤ r < 3.0", 3: "r ≥ 3.0", 0: "r < 1.43"},
    "Q4": {1: "80 ≤ SE < 85%", 1.5: "85 ≤ SE < 90%", 2: "90 ≤ SE < 92.5%", 2.5: "92.5 ≤ SE < 95%", 3: "SE ≥ 95%", 0: "SE < 80%"},
}
BAND_SHORT = {
    "Q1": {1: "2.0~2.8x", 1.5: "2.8~4.0x", 2: "4.0~5.7x", 2.5: "5.7~8.0x", 3: "≥8.0x"},
    "Q2": {1: "20~30%", 1.5: "30~40%", 2: "40~50%", 2.5: "50~60%", 3: "≥60%"},
    "Q3": {1: "r 1.43~1.7", 1.5: "r 1.7~2.0", 2: "r 2.0~2.45", 2.5: "r 2.45~3.0", 3: "r ≥3.0"},
    "Q4": {1: "80~85%", 1.5: "85~90%", 2: "90~92.5%", 2.5: "92.5~95%", 3: "≥95%"},
    "Q5": {1: "≤5모듈(≈1.0MM)", 1.5: "≤4(≈0.8)", 2: "≤3(≈0.6)", 2.5: "≤2.5(≈0.5)", 3: "≤2(≈0.4)"},
}


def star_q1(r):
    return _stars(r, EDGES["Q1"])


def star_q2(pct):
    return _stars(pct, EDGES["Q2"])


def star_q3(r):
    return _stars(r, EDGES["Q3"])


def star_q4(se_pct):
    return _stars(se_pct, EDGES["Q4"])


def star_q5(modules, mm=None):
    return _stars(modules, EDGES["Q5_module"], False)


def fmt_star(s):
    return "☆" if s == 0 else "★" + ("%g" % s)


OWNER = {
    ("DP1", 1): {"Q1": 1.5, "Q2": 2, "Q3": 1, "Q5": 2},
    ("DP1", 2): {"Q1": 2, "Q2": 1, "Q3": 2, "Q5": 2},
    ("DP2", 1): {"Q1": 1, "Q2": 2, "Q3": 2, "Q4": 2},
    ("DP2", 2): {"Q1": 2, "Q2": 1.5, "Q3": 1, "Q4": 3},
    ("DP3", 1): {"Q1": 2, "Q2": 3, "Q3": 1},
    ("DP3", 2): {"Q1": 2.5, "Q2": 2, "Q3": 2.5},
    ("DP4", 1): {"Q1": 2.5, "Q3": 2, "Q4": 2},
    ("DP4", 2): {"Q1": 2, "Q3": 1.5, "Q4": 3},
}

# ---- 이론 예상값 ---------------------------------------------------------------
_R = tm.all_results()
_S, _C2, _C4 = _R["single"], _R["dp2"], _R["dp4"]
LAM_TEST = _R["lam_test"]

# 변경 용이성(Q5): DP1만 덱에 Q5가 있다. module·MM은 기존 구현 측정(qa4)을 쓴다.
Q5_VALUES = {("DP1", 1): (1.75, 0.38), ("DP1", 2): (2.5, 0.51)}


def _q(b0, b1, c, hbm=True):
    """b0/b1/c = dict(tps, ttft, tpot, hbm). 지표별 값. 주 지표는 B0 대비, B1(경쟁 기술) 대비는 참고."""
    out = {}
    out["Q1"] = dict(b0=b0["qps"], b1=b1["qps"], c=c["qps"], r0=c["qps"] / b0["qps"], r1=c["qps"] / b1["qps"])
    if hbm:
        out["Q2"] = dict(b0=b0["hbm"], b1=b1["hbm"], c=c["hbm"], red0=(1 - c["hbm"] / b0["hbm"]) * 100,
                         red1=(1 - c["hbm"] / b1["hbm"]) * 100)
    r0, red0 = tm.r_reduction(b0["ttft"], b0["tpot"], c["ttft"], c["tpot"])
    r1, red1 = tm.r_reduction(b1["ttft"], b1["tpot"], c["ttft"], c["tpot"])
    out["Q3"] = dict(b0_ttft=b0["ttft"], b0_tpot=b0["tpot"], b1_ttft=b1["ttft"], b1_tpot=b1["tpot"],
                     c_ttft=c["ttft"], c_tpot=c["tpot"], r0=r0, red0=red0, r1=r1, red1=red1,
                     ttft_red0=(1 - c["ttft"] / b0["ttft"]) * 100, ttft_red1=(1 - c["ttft"] / b1["ttft"]) * 100)
    return out


def _build():
    th = {}
    b0, b1 = _S["B0"], _S["B1"]
    for dp in ("DP1", "DP3"):
        for k in (1, 2):
            th[(dp, k)] = _q(b0, b1, _S[(dp, k)])
    cb0 = dict(_C2["B0"], hbm=_C2["B1"]["hbm"], ttft=b0["ttft"], tpot=b0["tpot"])
    cb1 = dict(_C2["B1"])
    for k in (1, 2):
        th[("DP2", k)] = _q(cb0, cb1, _C2[("DP2", k)])
        th[("DP2", k)]["Q4"] = dict(b0=_C2["SE16"]["B1"] * 100, b1=_C2["SE16"]["B1"] * 100, c=_C2["SE16"][("DP2", k)] * 100)
    db0 = dict(_C4["B0"], hbm=0.0, ttft=b0["ttft"], tpot=b0["tpot"])
    db1 = dict(_C4["B1"], hbm=0.0)
    for k in (1, 2):
        c = dict(_C4[("DP4", k)], hbm=0.0)
        th[("DP4", k)] = _q(db0, db1, c, hbm=False)
        th[("DP4", k)]["Q4"] = dict(b0=_C4["SE16"]["B1"] * 100, b1=_C4["SE16"]["B1"] * 100, c=_C4["SE16"][("DP4", k)] * 100)
    for key, (m, mm) in Q5_VALUES.items():
        th[key]["Q5"] = dict(module=m, mm=mm)
    return th


THEORY = _build()


def theory_star(dp, k, q):
    t = THEORY.get((dp, k), {}).get(q)
    if t is None:
        return None
    if q == "Q1":
        return star_q1(t["r0"])
    if q == "Q2":
        return star_q2(t["red0"])
    if q == "Q3":
        return star_q3(t["r0"])
    if q == "Q4":
        return star_q4(t["c"])
    if q == "Q5":
        return star_q5(t["module"], t["mm"])


# 경쟁 기술(B1 단순 offload)의 이론값이 어느 별에 놓이는지 (범위별)
def competitor_stars():
    b0, b1 = _S["B0"], _S["B1"]
    r3, _ = tm.r_reduction(b0["ttft"], b0["tpot"], b1["ttft"], b1["tpot"])
    return {"Q1": (b1["qps"] / b0["qps"], star_q1(b1["qps"] / b0["qps"])),
            "Q2": ((1 - b1["hbm"] / b0["hbm"]) * 100, star_q2((1 - b1["hbm"] / b0["hbm"]) * 100)),
            "Q3": (r3, star_q3(r3)),
            "Q4": (_C2["SE16"]["B1"] * 100, star_q4(_C2["SE16"]["B1"] * 100))}


def _sg(x, fmt="%.0f"):
    s = fmt % abs(x)
    return ("+" if x >= 0 else "−") + s + "%"


def cell_text(dp, k, q):
    """DP 페이지 별 오른쪽에 쓰는 한 줄: B0 → 후보 (B0 대비 개선)."""
    t = THEORY.get((dp, k), {}).get(q)
    if t is None:
        return "—"
    if q == "Q1":
        return "%s→%s query/s (×%.2f)" % (fmt_q(t["b0"]), fmt_q(t["c"]), t["r0"])
    if q == "Q2":
        return "%s→%s GiB (%s)" % (format(round(t["b0"]), ","), format(round(t["c"]), ","), _sg(-t["red0"]))
    if q == "Q3":
        return "TTFT %.1f→%.1f s (r %.2f)" % (t["b0_ttft"], t["c_ttft"], t["r0"])
    if q == "Q4":
        return "SE %.0f→%.0f%%" % (t["b0"], t["c"])
    if q == "Q5":
        return "%gm·%.2fMM" % (t["module"], t["mm"])


def band_for_owner(q, o):
    return BAND_SHORT[q][o]


# ---- 기존 중립 벤치마크 시뮬레이션 값(참고, 새 시나리오 아님) ----------------------
OLD_SIM = {
    ("DP1", 1): "R ×1.30 · HBM +3% · P99 r 0.95 · 1.75m/0.38MM",
    ("DP1", 2): "R ×1.42 · HBM −21% · P99 r 1.22 · 2.5m/0.51MM",
    ("DP2", 1): "R ×1.66 · HBM +6% · TTFT 984 ms · η(32) 0.00",
    ("DP2", 2): "R ×1.66 · HBM −5% · TTFT 1,015 ms · η(32) 0.56",
    ("DP4", 1): "R ×0.70(RDMA 대비) · TTFT 4,205 ms(own-peak) · SE(16) 1.26",
    ("DP4", 2): "R ×0.70 · TTFT 4,205 ms · SE(16) 1.26",
}

if __name__ == "__main__":
    cs = competitor_stars()
    print("경쟁 기술(B1) 이론 위치:", {k: (round(v[0], 2), fmt_star(v[1])) for k, v in cs.items()})
    for key in sorted(OWNER):
        for q, o in OWNER[key].items():
            s = theory_star(*key, q)
            print(key, q, "owner", o, "| theory:", cell_text(*key, q), "->", None if s is None else fmt_star(s))
