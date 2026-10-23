"""QA 평가 기준(5구간), 문헌 근거 점, DP 후보별 owner 별과 기존 중립 벤치마크 실측값.

이 파일이 덱(build_deck.py)과 요약 문서(qa-criteria-v4.md)의 단일 소스다.
- 별 구간: ☆(미충족) / ★1 / ★1.5 / ★2 / ★2.5 / ★3. ★1 = 품질 시나리오 요구값(변경 용이성은 근거로 정한 값).
- 문헌 수치는 모두 보고값("up to")이고 논문 버전·baseline·workload가 서로 달라 직접 비교가 아니다.
  confirmed = 이번 세션에서 검색 요약으로 확인, user = 사용자 슬라이드의 인용(원문 대조 필요).
"""
import math

STAR_STEPS = [1.0, 1.5, 2.0, 2.5, 3.0]


def _stars(value, edges, higher_is_better=True):
    """edges: ★1, ★1.5, ★2, ★2.5, ★3 경계(오름차순 = 좋아지는 방향의 임계값)."""
    s = 0.0
    for star, e in zip(STAR_STEPS, edges):
        ok = value >= e if higher_is_better else value <= e
        if ok:
            s = star
    return s


# ---- 구간 경계 ------------------------------------------------------------
EDGES = {
    "Q1": [2.0, 2.8, 4.0, 5.7, 8.0],            # R (배), log 등간격(★ 1단계 = 2배)
    "Q2": [20, 30, 40, 50, 60],                  # HBM 감소율 %
    "Q3": [30, 40, 50, 62.5, 75],                # P99 개선 r 환산 감소율 % (r = 1.43, 1.67, 2.0, 2.67, 4.0)
    "Q4": [80, 85, 90, 92.5, 95],                # SE(N=16) %
    "Q5_module": [5, 4, 3, 2.5, 2],              # 시나리오 평균 변경 module 수 (작을수록 좋음)
    "Q5_mm": [1.0, 0.875, 0.75, 0.625, 0.5],     # 시나리오 평균 개발 공수 M/M (작을수록 좋음)
}

BAND_TEXT = {
    "Q1": {1: "2 ≤ R < 2.8", 1.5: "2.8 ≤ R < 4", 2: "4 ≤ R < 5.7", 2.5: "5.7 ≤ R < 8", 3: "R ≥ 8", 0: "R < 2"},
    "Q2": {1: "20 ≤ 감소율 < 30%", 1.5: "30 ≤ 감소율 < 40%", 2: "40 ≤ 감소율 < 50%", 2.5: "50 ≤ 감소율 < 60%", 3: "감소율 ≥ 60%", 0: "감소율 < 20%"},
    "Q3": {1: "30 ≤ 감소율 < 40%", 1.5: "40 ≤ 감소율 < 50%", 2: "50 ≤ 감소율 < 62.5%", 2.5: "62.5 ≤ 감소율 < 75%", 3: "감소율 ≥ 75%", 0: "감소율 < 30%"},
    "Q4": {1: "80 ≤ SE < 85%", 1.5: "85 ≤ SE < 90%", 2: "90 ≤ SE < 92.5%", 2.5: "92.5 ≤ SE < 95%", 3: "SE ≥ 95%", 0: "SE < 80%"},
}
BAND_SHORT = {
    "Q1": {1: "2~2.8x", 1.5: "2.8~4x", 2: "4~5.7x", 2.5: "5.7~8x", 3: "≥8x"},
    "Q2": {1: "20~30%", 1.5: "30~40%", 2: "40~50%", 2.5: "50~60%", 3: "≥60%"},
    "Q3": {1: "30~40%", 1.5: "40~50%", 2: "50~62.5%", 2.5: "62.5~75%", 3: "≥75%"},
    "Q4": {1: "80~85%", 1.5: "85~90%", 2: "90~92.5%", 2.5: "92.5~95%", 3: "≥95%"},
    "Q5": {1: "≤5모듈·≤1.0MM", 1.5: "≤4·≤0.875", 2: "≤3·≤0.75", 2.5: "≤2.5·≤0.625", 3: "≤2·≤0.5"},
}


def star_q1(r):
    return _stars(r, EDGES["Q1"])


def star_q2(pct):
    return _stars(pct, EDGES["Q2"])


def star_q3(pct):
    return _stars(pct, EDGES["Q3"])


def star_q4(se_pct):
    return _stars(se_pct, EDGES["Q4"])


def star_q5(modules, mm):
    return min(_stars(modules, EDGES["Q5_module"], False), _stars(mm, EDGES["Q5_mm"], False))


def fmt_star(s):
    if s == 0:
        return "☆"
    return "★" + ("%g" % s)


# ---- DP 후보별 owner 별(첨부 덱 trade-off 표)과 실측 --------------------------
# owner: 첨부 덱의 ●◐○ → 1 / 1.5 / 2 / 2.5 / 3
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


def _sg(t):
    return t.replace("-", "−")


def _r_reduction(base_ttft, base_tpot, ttft, tpot):
    r = math.sqrt((base_ttft / ttft) * (base_tpot / tpot))
    return (1 - 1 / r) * 100, r


# 출처: DP1 = Evaluation/DP1 결과(21쌍, H100+B200), DP2 = Evaluation/DP2 결과 §0.1(38쌍)과
#       tools/unified_inputs의 HBM, DP4 = Evaluation/DP4 결과 §0.1(CXL 공유 풀, Common 6쌍 / 공통 부하).
# 모두 시뮬레이션 [B+C]이고 이번 새 시나리오가 아니라 기존 중립 벤치마크의 값이다.
def _dp1():
    base = dict(tps=336, ttft=1084, tpot=17.1, hbm=146.6)
    c = {1: dict(tps=436, ttft=1128, tpot=18.3, hbm=142.7, module=1.75, mm=0.38),
         2: dict(tps=478, ttft=785, tpot=16.0, hbm=178.0, module=2.50, mm=0.51)}
    out = {}
    for k, v in c.items():
        red, r = _r_reduction(base["ttft"], base["tpot"], v["ttft"], v["tpot"])
        out[("DP1", k)] = {
            "Q1": dict(value=v["tps"] / base["tps"], disp="×%.2f" % (v["tps"] / base["tps"])),
            "Q2": dict(value=(base["hbm"] - v["hbm"]) / base["hbm"] * 100,
                       disp=_sg("%+.0f%%" % ((base["hbm"] - v["hbm"]) / base["hbm"] * 100))),
            "Q3": dict(value=red, disp=_sg("%+.0f%%" % red), r=r),
            "Q5": dict(value=(v["module"], v["mm"]), disp="%gm/%.2fMM" % (v["module"], v["mm"])),
        }
    return out


def _dp2():
    base = dict(tps=575, ttft=2461, tpot=8.9)
    c = {1: dict(tps=954, ttft=984, tpot=12.0, hbm_red=6.0, eta=0.00),
         2: dict(tps=956, ttft=1015, tpot=12.0, hbm_red=-5.0, eta=0.56)}
    out = {}
    for k, v in c.items():
        red, r = _r_reduction(base["ttft"], base["tpot"], v["ttft"], v["tpot"])
        out[("DP2", k)] = {
            "Q1": dict(value=v["tps"] / base["tps"], disp="×%.2f" % (v["tps"] / base["tps"])),
            "Q2": dict(value=v["hbm_red"], disp=_sg("%+.0f%%" % v["hbm_red"])),
            "Q3": dict(value=red, disp=_sg("%+.0f%%" % red), r=r),
            "Q4": dict(value=v["eta"] * 100, disp="η%.2f" % v["eta"]),
        }
    return out


def _dp4():
    base = dict(tps=589, ttft=6283, tpot=4.07)
    cand = dict(tps=415, ttft=4205, tpot=4.04)
    red, r = _r_reduction(base["ttft"], base["tpot"], cand["ttft"], cand["tpot"])
    red_common, r_common = _r_reduction(6283, 4.07, 31271, 4.04)  # 공통(Baseline peak) 부하
    out = {}
    for k in (1, 2):
        out[("DP4", k)] = {
            "Q1": dict(value=cand["tps"] / base["tps"], disp="×%.2f" % (cand["tps"] / base["tps"])),
            "Q3": dict(value=red, disp=_sg("%+.0f%%" % red), r=r, common=red_common),
            "Q4": dict(value=126.1, disp="SE%.2f" % 1.261),
        }
    return out


ACTUAL = {}
ACTUAL.update(_dp1())
ACTUAL.update(_dp2())
ACTUAL.update(_dp4())
# DP3: 기존 시뮬은 압축 기반 오프라인/온라인 후보라 새 Pipe-and-Filter / Shared Repository와 대응하지 않는다 → 실측 없음.


def actual_star(dp, cand, q):
    a = ACTUAL.get((dp, cand), {}).get(q)
    if a is None:
        return None
    v = a["value"]
    if q == "Q1":
        return star_q1(v)
    if q == "Q2":
        return star_q2(v)
    if q == "Q3":
        return star_q3(v)
    if q == "Q4":
        return star_q4(v)
    if q == "Q5":
        return star_q5(*v)
    return None


if __name__ == "__main__":
    for key in sorted(OWNER):
        for q, o in OWNER[key].items():
            a = ACTUAL.get(key, {}).get(q)
            s = actual_star(*key, q)
            print(key, q, "owner", o, "actual", a and a["disp"], "->", None if s is None else fmt_star(s))
