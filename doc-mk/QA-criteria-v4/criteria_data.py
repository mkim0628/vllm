"""QA 평가 기준(B1 기준 5구간), DP 후보별 소유자 별, 이론 계산 기반 절대 예상값.

- 판정 Baseline = B1(정적 DRAM→SSD offload). B0(GPU-only)는 참고로 병기한다.
- 별: ☆(미충족) / ★1 / ★1.5 / ★2 / ★2.5 / ★3. ★1 = 시나리오 요구값(변경 용이성은 근거로 정한 값).
- 절대 예상값은 theory_model.py의 분석 모델 결과다(시뮬레이션 아님, 후보 파라미터는 [가정]).
"""
import math

import theory_model as tm

STAR_STEPS = [1.0, 1.5, 2.0, 2.5, 3.0]


def _stars(value, edges, higher_is_better=True):
    s = 0.0
    for star, e in zip(STAR_STEPS, edges):
        ok = value >= e - 1e-9 if higher_is_better else value <= e + 1e-9
        if ok:
            s = star
    return s


# ---- 구간 경계 (B1 대비) -----------------------------------------------------
EDGES = {
    "Q1": [1.2, 1.35, 1.5, 1.65, 1.8],           # R = 후보 ÷ B1
    "Q2": [20, 30, 40, 50, 60],                   # HBM 감소율 % (B1 대비)
    "Q3": [1.2, 1.35, 1.5, 1.65, 1.8],            # r = √(TTFT 개선 × TPOT 개선, P99)
    "Q4": [80, 85, 90, 92.5, 95],                 # SE(N=16) %
    "Q5_module": [5, 4, 3, 2.5, 2],
    "Q5_mm": [1.0, 0.875, 0.75, 0.625, 0.5],
}


def red_of_r(r):
    return (1 - 1 / r) * 100


BAND_TEXT = {
    "Q1": {1: "1.2 ≤ R < 1.35", 1.5: "1.35 ≤ R < 1.5", 2: "1.5 ≤ R < 1.65", 2.5: "1.65 ≤ R < 1.8", 3: "R ≥ 1.8", 0: "R < 1.2"},
    "Q2": {1: "20 ≤ 감소율 < 30%", 1.5: "30 ≤ 감소율 < 40%", 2: "40 ≤ 감소율 < 50%", 2.5: "50 ≤ 감소율 < 60%", 3: "감소율 ≥ 60%", 0: "감소율 < 20%"},
    "Q3": {1: "1.2 ≤ r < 1.35", 1.5: "1.35 ≤ r < 1.5", 2: "1.5 ≤ r < 1.65", 2.5: "1.65 ≤ r < 1.8", 3: "r ≥ 1.8", 0: "r < 1.2"},
    "Q4": {1: "80 ≤ SE < 85%", 1.5: "85 ≤ SE < 90%", 2: "90 ≤ SE < 92.5%", 2.5: "92.5 ≤ SE < 95%", 3: "SE ≥ 95%", 0: "SE < 80%"},
}
BAND_SHORT = {
    "Q1": {1: "1.2~1.35x", 1.5: "1.35~1.5x", 2: "1.5~1.65x", 2.5: "1.65~1.8x", 3: "≥1.8x"},
    "Q2": {1: "20~30%", 1.5: "30~40%", 2: "40~50%", 2.5: "50~60%", 3: "≥60%"},
    "Q3": {1: "r 1.2~1.35", 1.5: "r 1.35~1.5", 2: "r 1.5~1.65", 2.5: "r 1.65~1.8", 3: "r ≥1.8"},
    "Q4": {1: "80~85%", 1.5: "85~90%", 2: "90~92.5%", 2.5: "92.5~95%", 3: "≥95%"},
    "Q5": {1: "≤5모듈·≤1.0MM", 1.5: "≤4·≤0.875", 2: "≤3·≤0.75", 2.5: "≤2.5·≤0.625", 3: "≤2·≤0.5"},
}


def star_q1(r):
    return _stars(r, EDGES["Q1"])


def star_q2(pct):
    return _stars(pct, EDGES["Q2"])


def star_q3(r):
    return _stars(r, EDGES["Q3"])


def star_q4(se_pct):
    return _stars(se_pct, EDGES["Q4"])


def star_q5(modules, mm):
    return min(_stars(modules, EDGES["Q5_module"], False), _stars(mm, EDGES["Q5_mm"], False))


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

# 변경 용이성(Q5): DP1만 덱에 Q5가 있다. module·MM은 기존 구현 측정(qa4)을 쓴다.
Q5_VALUES = {("DP1", 1): (1.75, 0.38), ("DP1", 2): (2.5, 0.51)}


def _q(scope, b0, b1, c):
    """b0/b1/c = dict(tps, ttft, tpot, hbm). 지표별 값과 개선율."""
    out = {}
    out["Q1"] = dict(b0=b0["tps"], b1=b1["tps"], c=c["tps"], r1=c["tps"] / b1["tps"], r0=c["tps"] / b0["tps"])
    if b1["hbm"]:
        out["Q2"] = dict(b0=b0["hbm"], b1=b1["hbm"], c=c["hbm"], red=(1 - c["hbm"] / b1["hbm"]) * 100)
    r, red = tm.r_reduction(b1["ttft"], b1["tpot"], c["ttft"], c["tpot"])
    out["Q3"] = dict(b1_ttft=b1["ttft"], b1_tpot=b1["tpot"], c_ttft=c["ttft"], c_tpot=c["tpot"], r=r, red=red,
                     ttft_red=(1 - c["ttft"] / b1["ttft"]) * 100)
    return out


def _build():
    th = {}
    b0, b1 = _S["B0"], _S["B1"]
    for dp in ("DP1", "DP3"):
        for k in (1, 2):
            c = _S[(dp, k)]
            th[(dp, k)] = _q("single", b0, b1, c)
    # DP2 클러스터(P2+D2 고정 역할 Baseline)
    cb0, cb1 = _C2["B0"], dict(_C2["B1"])
    cb0 = dict(cb0, hbm=_C2["B1"]["hbm"], ttft=float("inf"), tpot=float("inf"))
    for k in (1, 2):
        th[("DP2", k)] = _q("cluster", cb0, cb1, _C2[("DP2", k)])
        se = _C2["SE16"]
        th[("DP2", k)]["Q4"] = dict(b1=se["B1"] * 100, c=se[("DP2", k)] * 100)
    # DP4 클러스터(노드 독립 B1, 교차 라우팅 25% 재계산)
    db0, db1 = dict(_C4["B0"], hbm=0.0, ttft=float("inf"), tpot=float("inf")), _C4["B1"]
    for k in (1, 2):
        c = _C4[("DP4", k)]
        t = _q("cluster", db0, dict(db1, hbm=0.0), dict(c, hbm=0.0))
        t["Q4"] = dict(b1=_C4["SE16"]["B1"] * 100, c=_C4["SE16"][("DP4", k)] * 100)
        th[("DP4", k)] = t
    for key, (m, mm) in Q5_VALUES.items():
        th[key]["Q5"] = dict(module=m, mm=mm)
    return th


THEORY = _build()


def theory_star(dp, k, q):
    t = THEORY.get((dp, k), {}).get(q)
    if t is None:
        return None
    if q == "Q1":
        return star_q1(t["r1"])
    if q == "Q2":
        return star_q2(t["red"])
    if q == "Q3":
        return star_q3(t["r"])
    if q == "Q4":
        return star_q4(t["c"])
    if q == "Q5":
        return star_q5(t["module"], t["mm"])


def _sg(x, fmt="%.0f"):
    s = fmt % abs(x)
    return ("+" if x >= 0 else "−") + s + "%"


def cell_text(dp, k, q):
    """DP 페이지 별 오른쪽에 쓰는 한 줄: B1 → 후보 (개선율)."""
    t = THEORY.get((dp, k), {}).get(q)
    if t is None:
        return "—"
    if q == "Q1":
        return "%s→%s tok/s (%s)" % (format(round(t["b1"]), ","), format(round(t["c"]), ","), _sg((t["r1"] - 1) * 100))
    if q == "Q2":
        return "%s→%s GiB (%s)" % (format(round(t["b1"]), ","), format(round(t["c"]), ","), _sg(-t["red"]))
    if q == "Q3":
        return "TTFT %.1f→%.1f s (%s)" % (t["b1_ttft"], t["c_ttft"], _sg(-t["ttft_red"]))
    if q == "Q4":
        return "SE %.0f→%.0f%%" % (t["b1"], t["c"])
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
    for key in sorted(OWNER):
        for q, o in OWNER[key].items():
            s = theory_star(*key, q)
            print(key, q, "owner", o, "| theory:", cell_text(*key, q), "->", None if s is None else fmt_star(s))
