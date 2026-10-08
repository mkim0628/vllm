#!/usr/bin/env python3
"""DP0 Q3(Modifiability) 예상치 모델 + SLO 산술. 모든 입력은 '가정'이며 결과는 예상치(미실행)다.

실행: python3 modifiability_model.py
세 지표(토큰 cost > 공수 > 모듈 수)는 같은 시나리오 사실(M, L, E, B, U)에서 파생되므로
시나리오별 우열 방향이 서로 모순되지 않는다.
"""
import json

# ---- 시나리오 사실 (후보별): M 변경 module 수, L 변경 LOC, E OSS 탐색 토큰(1안만), B 빌드·배포 횟수, U upstream 재검증 횟수
SC = {
    "S1": dict(name="새 tier 추가",    w=1, c1=dict(M=1, L=10,   E=0,      B=0, U=0), c2=dict(M=2, L=60,   E=0, B=1, U=0)),
    "S2": dict(name="비용 함수 교체",  w=2, c1=dict(M=3, L=250,  E=40_000, B=1, U=1), c2=dict(M=1, L=120,  E=0, B=1, U=0)),
    "S3": dict(name="P/D 정책 교체",   w=2, c1=dict(M=4, L=300,  E=60_000, B=1, U=1), c2=dict(M=1, L=120,  E=0, B=1, U=0)),
    "S4": dict(name="노드 지시 추가",  w=2, c1=dict(M=5, L=420,  E=80_000, B=2, U=1), c2=dict(M=1, L=80,   E=0, B=1, U=0)),
    "S5": dict(name="vLLM 계약 변경",  w=1, c1=dict(M=2, L=60,   E=10_000, B=1, U=1), c2=dict(M=3, L=300,  E=0, B=1, U=0)),
    "S6": dict(name="신규 기능",       w=1, c1=dict(M=1, L=15,   E=0,      B=0, U=0), c2=dict(M=6, L=1500, E=0, B=1, U=0)),
}

# ---- 가정 상수
MOD_TOK = 8_000       # module 1개 읽기 토큰 (약 600 LOC x 13 tok/LOC)
TOK_PER_LOC = 13      # 코드 1줄 토큰
REWORK = 2            # 출력 = 최초 작성 + 수정 1회
TURNS = 6             # 입력 유효 재과금 배수 (캐시 적중 후 가정)
P_IN, P_OUT = 3.0, 15.0   # $ / MTok  (Sonnet급 list price 가정, 공식 페이지 확인 필요)
D_REVIEW = 0.5        # man-day / module : 사람 리뷰·수정 반영
LOC_PER_DAY = 400     # LOC/man-day : 검증·테스트 보강 속도
D_BUILD = 1.0         # man-day / 빌드·배포 1회
D_UPSTREAM = 1.0      # man-day / upstream 호환 재검증 1회


def token_cost(f, e_scale=1.0):
    tin = (f["M"] * MOD_TOK + f["E"] * e_scale) * TURNS
    tout = f["L"] * TOK_PER_LOC * REWORK
    return (tin * P_IN + tout * P_OUT) / 1e6


def man_day(f):
    return D_REVIEW * f["M"] + f["L"] / LOC_PER_DAY + D_BUILD * f["B"] + D_UPSTREAM * f["U"]


def agg(metric, cand, weighted=True, **kw):
    num = den = 0.0
    for s in SC.values():
        w = s["w"] if weighted else 1
        num += w * metric(s[cand], **kw)
        den += w
    return num / den


def table(weighted=True, e_scale=1.0):
    out = {}
    for cand in ("c1", "c2"):
        out[cand] = dict(
            cost=agg(lambda f: token_cost(f, e_scale), cand, weighted),
            days=agg(man_day, cand, weighted),
            mods=agg(lambda f: f["M"], cand, weighted),
        )
    return out


def per_scenario(e_scale=1.0):
    rows = []
    for k, s in SC.items():
        r = dict(id=k, name=s["name"], w=s["w"])
        for cand in ("c1", "c2"):
            f = s[cand]
            r[cand] = dict(M=f["M"], L=f["L"], cost=token_cost(f, e_scale), days=man_day(f))
        rows.append(r)
    return rows


def sub_star_cost(x):  return 3 if x <= 0.5 else (2 if x <= 2.0 else 1)
def sub_star_days(x):  return 3 if x <= 3.0 else (2 if x <= 7.0 else 1)
def sub_star_mods(x):  return 3 if x <= 2.0 else (2 if x < 6 else 1)


def slo_arithmetic():
    """Llama-3.1-70B BF16, 8 x H100 SXM(80GB, 3.35 TB/s, 989 TFLOPS BF16 dense) TP8 한 노드 기준 하한."""
    P, bytes_w = 70.6e9, 2
    hbm_bw, flops = 3.35e12, 989e12
    gpus = 8
    eff_bw = gpus * hbm_bw * 0.7          # 지속 대역폭 70%
    eff_fl = gpus * flops * 0.45          # MFU 45%
    prefill_s = 2 * P * 8192 / eff_fl     # 8K prefill
    kv_per_tok = 80 * 2 * 8 * 128 * 2     # layers x K/V x kv_heads x head_dim x bytes
    kv_req = kv_per_tok * 8448            # 8K in + 256 out
    free = gpus * 80e9 * 0.9 - P * bytes_w   # 90% 사용 가능 - 가중치
    bmax = int(free // kv_req)
    tpot_b1 = (P * bytes_w) / eff_bw
    tpot_bmax = (P * bytes_w + bmax * kv_req) / eff_bw
    xfer_ms = kv_req / 50e9 * 1e3         # 400Gb/s ~ 50 GB/s
    return dict(prefill_s=prefill_s, kv_per_tok_B=kv_per_tok, kv_req_GB=kv_req / 1e9, b_max=bmax,
                tpot_b1_ms=tpot_b1 * 1e3, tpot_bmax_ms=tpot_bmax * 1e3, kv_xfer_ms=xfer_ms)


if __name__ == "__main__":
    res = dict(
        weighted=table(True), equal=table(False),
        weighted_E0=table(True, 0.0), equal_E0=table(False, 0.0), weighted_E2=table(True, 2.0),
        scen=per_scenario(), slo=slo_arithmetic(),
    )
    # 시나리오별 방향 일관성 검사
    for r in res["scen"]:
        d = [r["c1"]["cost"] < r["c2"]["cost"], r["c1"]["days"] < r["c2"]["days"], r["c1"]["M"] < r["c2"]["M"]]
        eq = r["c1"]["M"] == r["c2"]["M"]
        r["consistent"] = (all(d) or not any(d)) if not eq else (d[0] == d[1])
    print(json.dumps(res, ensure_ascii=False, indent=1, default=lambda x: round(x, 3)))
    w = res["weighted"]
    print("STARS weighted: cost", sub_star_cost(w["c1"]["cost"]), sub_star_cost(w["c2"]["cost"]),
          "days", sub_star_days(w["c1"]["days"]), sub_star_days(w["c2"]["days"]),
          "mods", sub_star_mods(w["c1"]["mods"]), sub_star_mods(w["c2"]["mods"]))
    e = res["equal"]
    print("STARS equal   : cost", sub_star_cost(e["c1"]["cost"]), sub_star_cost(e["c2"]["cost"]),
          "days", sub_star_days(e["c1"]["days"]), sub_star_days(e["c2"]["days"]),
          "mods", sub_star_mods(e["c1"]["mods"]), sub_star_mods(e["c2"]["mods"]))
