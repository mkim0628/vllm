"""Agent KV Fleet 시나리오의 이론 계산 기반 예상값 (분석 모델, 시뮬레이션이 아니다).

구조
  1) 물리 상수(H100×8 노드)와 시나리오 파라미터로 B0(GPU-only), B1(정적 offload)의 절대값을 계산한다.
  2) 후보는 B1과 같은 식을 쓰되 설계 파라미터(θ, w, π, ω, 오버헤드, watermark)만 다르다.
     파라미터는 첨부 덱의 장단점에서 방향만 가져온 [가정]이며 시뮬레이션으로 교체될 값이다.
  3) 출력: Q1 goodput(query/s, query = 요청 1건 = 1 turn, 출력 256 token), Q2 HBM 사용(GiB), Q3 TTFT·TPOT P99와 개선 r, Q4 SE(N=16).

요청 모델: open-loop. 세션 idle 시간은 지수분포(평균 Z). LRU stack distance 근사로 반환 세션이
HBM/DRAM/SSD에서 발견될 확률을 계산한다. Max SLO goodput = TTFT P99 ≤ 2 s 그리고 TPOT P99 ≤ 50 ms를 이 모델의 대기열식으로
실제로 만족하는 최대 처리율(slo_max)이다(2026-10-27 정정: 이전에는 처리 한계의 0.8배를 썼고 SLO 만족을 확인하지 않았다).

컨텍스트: 세션은 8K에서 시작해 턴당 +1.25K(입력 1K + 출력 256), 12턴(종료 약 22K, 평균 약 15K). 이론 모델은 평균을 올린 대표 컨텍스트 16K로 계산한다.
"""
import math

GiB = 1024 ** 3
# ---- 물리·시스템 상수 (SYS-H100, system-specs.md) ----
KV_TOK = 327_680                    # B/token (80 layer × 8 KV head × 128 dim × K,V × BF16)
CTX = 16_384
KV_S = KV_TOK * CTX                 # 5.0 GiB / 세션
HBM_POOL = 425 * GiB                # 640×0.9 − 가중치 131 − 활성값 20
DRAM_POOL = 922 * GiB               # 1 TiB × 0.9
BW_D = 64e9 * 0.8                   # DRAM→HBM 호스트 링크(노드), 사용 가능 0.8
BW_S = 16e9 * 0.8                   # NVMe PCIe5 x4, 사용 가능 0.8
PREFILL_TPS = 25_200                # 70B, H100×8, MFU 0.45
T_NEW = 1_024 / PREFILL_TPS         # 턴당 새 입력 1K token prefill (s)
T_REC = CTX / PREFILL_TPS           # 16K 재계산 (s) = 0.65
W_TIME = 5.3e-3                     # decode step 가중치 읽기 하한 (s)
KV_STEP = 0.2e-3                    # 세션당 KV 읽기 (s/step, 16K)
B_DEC = 64                          # 대표 decode batch
OUT = 256
TTFT_SLO, TPOT_SLO = 2.0, 50.0      # s, ms
TURNS = 12                          # 세션당 턴 수(시작 8K, 턴당 +1.25K)
Z_MEAN = 60.0                       # idle(tool 대기+사용자) 평균 s [가정]
N_HBM = HBM_POOL / KV_S             # 85 세션분
N_DRAM = DRAM_POOL / KV_S           # 184 세션분


def tau(b=B_DEC):
    return W_TIME + b * KV_STEP


G0 = T_NEW + OUT * tau() / B_DEC    # 턴당 GPU 시간 (miss 없음) ≈ 0.113 s


def hit_rates(lam, theta=1.0, fprime=1.0, n_hbm=None):
    """LRU stack distance: idle T~Exp(Z), 그 사이 서로 다른 세션 λT개 접근. 반환 세션이 각 tier에서 발견될 확률.
    theta = 배치 효율(효과 용량 배수), fprime = 세션당 이동·보관 크기 비율(dedup 등)."""
    nh = N_HBM if n_hbm is None else n_hbm
    cap_h = theta * nh / fprime
    cap_hd = theta * (nh + N_DRAM) / fprime
    f_h = 1 - math.exp(-cap_h / (lam * Z_MEAN))
    f_hd = 1 - math.exp(-cap_hd / (lam * Z_MEAN))
    return f_h, f_hd - f_h, 1 - f_hd          # hbm, dram, ssd(+없음)


class Cfg:
    def __init__(self, name, tiers=True, theta=1.0, w=1.0, pi=0.0, omega=0.0, extra_gpu=0.0, d_crit=0.0,
                 fprime=1.0, wm=1.0, pool=False, pool_bw=None, tail_gpu_chain=0.0):
        self.name, self.tiers, self.theta, self.w, self.pi, self.omega = name, tiers, theta, w, pi, omega
        self.extra_gpu, self.d_crit, self.fprime, self.wm = extra_gpu, d_crit, fprime, wm
        self.pool, self.pool_bw = pool, pool_bw
        self.tail_gpu_chain = tail_gpu_chain


def caps(c, lam, n_hbm=None):
    """λ에서의 용량(turn/s): (GPU, DRAM link, 하위 tier link)"""
    h_h, h_d, h_s = hit_rates(lam, c.theta, c.fprime, n_hbm)
    miss = 1 - h_h
    if not c.tiers:                                         # B0: HBM만, 나머지는 재계산
        g = G0 + miss * T_REC
        return 1 / g, math.inf, math.inf
    g = G0 + c.extra_gpu
    kv = KV_S * c.fprime
    units_d = miss * (1 - c.pi) + miss * c.pi * (1 + c.omega) + c.w * miss
    cap_d = BW_D / (units_d * kv)
    low_bw = c.pool_bw if c.pool else BW_S
    units_s = h_s * (1 + c.omega * c.pi) + c.w * h_s
    cap_s = low_bw / (units_s * kv) if units_s > 0 else math.inf
    return 1 / g, cap_d, cap_s


def max_lambda(c, n_hbm=None):
    lo, hi = 0.05, 40.0
    for _ in range(80):
        mid = (lo + hi) / 2
        g, d, s = caps(c, mid, n_hbm)
        if mid <= min(g, d, s):
            lo = mid
        else:
            hi = mid
    return lo


def slo_max(c, lam_cap=None, ttft_extra=0.0, ttft_fn=None):
    """Max SLO goodput(query/s, 1 query = 1 turn): TTFT P99 ≤ TTFT_SLO 그리고 TPOT P99 ≤ TPOT_SLO를 만족하는 최대 λ.
    lam_cap = 처리 한계(링크·GPU). ttft_fn(λ)이 있으면 TTFT를 그것으로 계산한다."""
    cap = max_lambda(c) if lam_cap is None else lam_cap
    lo, hi = 0.001, cap
    for _ in range(80):
        mid = (lo + hi) / 2
        tt, tp, _ = latencies(c, mid, cap)
        if ttft_fn is not None:
            tt = ttft_fn(mid)
        if tt + ttft_extra <= TTFT_SLO and tp <= TPOT_SLO:
            lo = mid
        else:
            hi = mid
    return lo


def latencies(c, lam_test, lam_cap, n_hbm=None):
    """P99 TTFT(s), TPOT(ms). 링크 이용률 ρ에 대해 복원 시간이 1/(1−ρ)로 늘어난다(processor sharing 근사)."""
    rho = min(lam_test / lam_cap, 0.95)
    h_h, h_d, h_s = hit_rates(lam_test, c.theta, c.fprime, n_hbm)
    kv = KV_S * c.fprime
    if not c.tiers:                                         # B0: 재계산이 critical path
        ttft = T_NEW + (1 - h_h) * T_REC / max(1 - rho, 0.05) if (1 - h_h) > 0.01 else T_NEW
        return ttft, tau() * 1e3 * (1 + 0.5 * rho), rho
    t_d = kv / BW_D
    t_s = kv / (c.pool_bw if c.pool else BW_S) + t_d
    crit_s = h_s * (1 - c.pi)
    crit_d = (h_d + h_s) * (1 - c.pi)
    if crit_s > 0.01:
        rest = t_s
    elif crit_d > 0.01:
        rest = t_d
    else:
        rest = 0.0
    rho_gpu = min(lam_test * (G0 + c.extra_gpu), 0.95)
    ttft = T_NEW + c.d_crit + rest / (1 - rho) + c.tail_gpu_chain / (1 - rho_gpu)
    return ttft, tau() * 1e3 * (1 + 0.5 * rho), rho


# ---- 설정 ---------------------------------------------------------------
B0 = Cfg("B0 GPU-only", tiers=False)
# B1: 단순 offload = 턴 종료 시 증분(≈1.25K/16K)만 하위 tier에 기록하는 write-through, 축출은 복사 없이 삭제,
#     요청 시 동기 복원, prefetch·예측·배치 정책 없음 (θ=1, π=0)
B1 = Cfg("B1 정적 offload", w=0.1)
CFG = {
    ("DP1", 1): Cfg("DP1 1안", theta=1.1, w=0.1, pi=0.0, omega=0.0, d_crit=0.003, wm=0.80),
    ("DP1", 2): Cfg("DP1 2안", theta=1.3, w=0.1, pi=0.6, omega=0.3, d_crit=0.0, wm=0.95),
    # DP3: 공유 문서 30%를 1회만 보관(dedup) → 세션당 이동·보관 크기 0.70, 선택 재계산 비용 amortized 2 ms
    ("DP3", 1): Cfg("DP3 1안", w=0.1, fprime=0.70, extra_gpu=0.025 + 0.002, tail_gpu_chain=0.025, wm=0.60),
    ("DP3", 2): Cfg("DP3 2안", w=0.1, fprime=0.70, extra_gpu=0.001 + 0.002, wm=0.75),
}


def capacity_sessions(c):
    """Capacity: KV를 보존한 채(HBM·DRAM, SSD 제외) 재개 가능한 최대 동시 세션 수. HBM을 가득 채운 상태 기준(watermark 무관).
    효과 용량 θ(배치 효율)와 세션당 크기 비 f′(dedup)만 반영. 신규 메모리(ScHBM·CXL-PNM·HBF)는 아직 미반영 [잠정]."""
    if not c.tiers:
        return float(N_HBM)
    return c.theta * (N_HBM + N_DRAM) / c.fprime


def single_node():
    out = {}
    lam0 = slo_max(B0)
    lam_test = 0.9 * lam0                                    # 고부하 = B0(GPU-only) Max SLO goodput의 90%
    for key, c in [("B0", B0), ("B1", B1)] + [(k, v) for k, v in CFG.items()]:
        lam = max_lambda(c)
        ttft, tpot, rho = latencies(c, lam_test, lam)
        hbm = HBM_POOL / GiB * (1.0 if key in ("B0", "B1") else c.wm)   # 정적 LRU offload는 HBM을 캐시로 채운다
        out[key] = dict(lam=lam, qps=slo_max(c, lam), ttft=ttft, tpot=tpot, rho=rho, hbm=hbm, cfg=c)
    return out, lam_test


# ---- 클러스터(DP2, DP4) ---------------------------------------------------
N4 = 4
D_NODES = 2                                                 # B1-PD: P 2대 + D 2대 고정 역할


DP2_UP = {1: 0.20, 2: 0.50}                                # 유휴 P 노드 tier 활용 비율 [가정]


def capacity_dp2(k=None):
    """DP2 4노드(P2+D2) Capacity: 고정 역할에서는 D 노드 2대만 세션 KV를 보존한다(P 노드 HBM은 prefill용).
    B0 = D 2대 HBM만, B1 = D 2대 HBM+DRAM, 후보 = D 2대 + 유휴 P 노드 tier를 u_p만큼 추가 사용."""
    per_b0, per_b1 = float(N_HBM), float(N_HBM + N_DRAM)
    if k is None:
        return D_NODES * per_b0, D_NODES * per_b1
    return (D_NODES + DP2_UP[k] * (N4 - D_NODES)) * per_b1


def cluster_dp2(single):
    """DP2: 고정 역할(B1-PD)에서는 KV tier를 가진 D 노드 2대만 복원·decode를 수행하고 P 노드 2대의 tier·링크는 놀고 있다.
    동적 배치는 유휴 P 노드의 tier·링크를 u_P 만큼 쓴다. 결정 지연·Re-plan은 TTFT에 반영한다."""
    base = single["B1"]
    b0 = single["B0"]
    res = {}
    res["B0"] = dict(qps=D_NODES * b0["qps"], note="P/D 고정 + GPU-only")
    res["B1"] = dict(qps=D_NODES * base["qps"], ttft=base["ttft"], tpot=base["tpot"], hbm=D_NODES * 425.0)
    params = {1: dict(u_p=DP2_UP[1], d=0.008, replan=0.0, a=0.10, wm=0.85),   # 스케줄링 시점 결정: N=4에서 결정 8 ms(2 ms×N), 실시간 상태
              2: dict(u_p=DP2_UP[2], d=0.0, replan=0.040, a=0.05, wm=0.92)}    # 사전 계획: 결정 0, Re-plan(31%) P99 +40 ms, plan 예약으로 HBM 여유 필요
    for k, p in params.items():
        n_eff = D_NODES + p["u_p"] * (N4 - D_NODES)
        qps = n_eff * base["qps"] * (1 + p["a"] * 0.5)
        # tail: 복원 stall을 피하는 배치 a, 링크 이용률은 n_eff 증가만큼 낮아짐
        rho = min(base["rho"] * D_NODES / n_eff, 0.95)
        ttft = T_NEW + p["d"] + p["replan"] + (1 - p["a"]) * (base["ttft"] - T_NEW) * (1 - base["rho"]) / (1 - rho)
        tpot = tau() * 1e3 * (1 + 0.5 * rho)
        res[("DP2", k)] = dict(qps=qps, ttft=ttft, tpot=tpot, hbm=D_NODES * 425.0 * p["wm"])
    # SE(N=16): 단일 scheduler 결정 용량 vs 요구 (결정 비용 2 ms × N, 후보 수 선형 [repo ASSUMED])
    lam_node = single["B1"]["qps"]
    demand = 16 * lam_node
    cap_c1 = 1 / (0.002 * 16)
    cap_c2 = 4 / (0.002 * 16)                                # worker 4
    res["SE16"] = {"B1": 0.98, ("DP2", 1): min(1.0, cap_c1 / demand), ("DP2", 2): min(1.0, cap_c2 / demand) * 0.97}
    return res


def cluster_dp4(single, lam_test_node):
    """DP4: CXL 공유 풀이 SSD를 대체하는 하위 tier(노드 유효 63 GB/s ×0.8)가 되고 노드 간 hit를 허용한다.
    B1은 노드 독립이라 반환 세션이 다른 노드로 라우팅되면(25%) 재계산한다."""
    x_cross = 0.25
    b1 = single["B1"]
    c_b1 = B1
    g, d, s = caps(c_b1, b1["lam"])
    lam_b1_cluster = N4 * min(1 / (G0 + x_cross * T_REC), d, s)
    pool_bw = 63e9 * 0.8
    ctl = {1: 0.00003, 2: 0.0032}                            # 4 op/turn: 중앙 RPC ≈7 µs, 분산 락 P99 ≈804 µs
    res = {}
    # B0도 교차 라우팅(25%)이면 자기 노드 HBM에 KV가 없어 항상 재계산한다
    lo, hi = 0.05, 20.0
    for _ in range(60):
        mid = (lo + hi) / 2
        m = 1 - (1 - x_cross) * hit_rates(mid)[0]
        if mid * (G0 + m * T_REC) <= 1:
            lo = mid
        else:
            hi = mid
    lam_b0_cap = lo

    def ttft_b0(lam):
        m = 1 - (1 - x_cross) * hit_rates(lam)[0]
        rho = min(lam / lam_b0_cap, 0.95)
        return T_NEW + m * T_REC / max(1 - rho, 0.05)

    lam_b0 = slo_max(B0, lam_b0_cap, ttft_fn=ttft_b0)
    res["B0"] = dict(qps=N4 * lam_b0)
    cb1 = Cfg("B1 cross", w=1.0)
    lam_b1_node = lam_b1_cluster / N4
    lam_b1 = slo_max(cb1, lam_b1_node, ttft_extra=x_cross * T_REC)      # P99는 교차 라우팅 재계산 경로가 더해진다
    res["B1"] = dict(qps=N4 * lam_b1, lam=lam_b1_cluster)
    lam_test = lam_test_node                                  # 노드당 시험 부하 = B0 Max SLO goodput의 90%
    for k in (1, 2):
        c = Cfg("DP4 %d안" % k, pool=True, pool_bw=pool_bw, extra_gpu=0.0, d_crit=ctl[k])
        lam = max_lambda(c)
        ttft, tpot, rho = latencies(c, lam_test, lam)
        res[("DP4", k)] = dict(qps=N4 * slo_max(c, lam), ttft=ttft, tpot=tpot, rho=rho)
    ttft_b1, tpot_b1, _ = latencies(cb1, lam_test, lam_b1_node)
    ttft_b1 += x_cross * T_REC                               # P99는 교차 라우팅 재계산 경로
    res["B1"].update(ttft=ttft_b1, tpot=tpot_b1)
    lam_node = res[("DP4", 1)]["qps"] / N4
    demand = 16 * lam_node * 4                               # 16노드 × 4 op/turn
    res["SE16"] = {"B1": 0.98, ("DP4", 1): min(1.0, 204_800 / demand) * 0.99, ("DP4", 2): min(1.0, 102_400 / demand) * 0.99}
    return res


def r_reduction(b_ttft, b_tpot, ttft, tpot):
    r = math.sqrt((b_ttft / ttft) * (b_tpot / tpot))
    return r, (1 - 1 / r) * 100


def all_results():
    single, lam_test = single_node()
    c2 = cluster_dp2(single)
    c4 = cluster_dp4(single, lam_test)
    R = {"single": single, "dp2": c2, "dp4": c4, "lam_test": lam_test}
    return R


if __name__ == "__main__":
    R = all_results()
    s = R["single"]
    print("G0 %.3f s  ceiling %.2f turn/s  λ_test %.2f" % (G0, 1 / G0, R["lam_test"]))
    for k, v in s.items():
        print(k, "λ=%.2f qps=%.0f TTFT=%.2fs TPOT=%.1fms HBM=%.0f ρ=%.2f" % (v["lam"], v["qps"], v["ttft"], v["tpot"], v["hbm"], v["rho"]))
    print("DP2", {k: {a: round(b, 3) for a, b in v.items() if isinstance(b, float)} for k, v in R["dp2"].items()})
    print("DP4", {k: {a: round(b, 3) for a, b in v.items() if isinstance(b, float)} for k, v in R["dp4"].items() if k != "SE16"}, R["dp4"]["SE16"])
