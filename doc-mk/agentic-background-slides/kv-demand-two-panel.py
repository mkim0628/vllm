import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter, FixedLocator
import numpy as np

plt.rcParams["font.family"] = "WenQuanYi Zen Hei"
plt.rcParams["axes.unicode_minus"] = False

MB_PER_TOKEN = 0.33          # Llama-3.1-70B, BF16
SESSIONS = 100               # 가정
ASTRA_AGENTS, ASTRA_CTX = 10_000, 1e6
GPUS = [("H100", 80), ("B200", 192), ("B300", 288)]     # GPU 1개 HBM 총량 (GB)
C_LINE, C_RED, C_BLUE, C_ORG = "#1f3b73", "#c0392b", "#2f6db5", "#d35400"
TOP = GPUS[-1][1]

def kv_gb(tokens, n=1):
    return tokens * MB_PER_TOKEN / 1000 * n

def fmt_size(gb):
    gb = float(f"{gb:.2g}")
    for unit, f in (("PB", 1e6), ("TB", 1e3), ("GB", 1)):
        if gb >= f:
            return f"{gb / f:g} {unit}"
    return f"{gb:g} GB"

# (이름, 문맥 길이, 근거)
workloads = [("채팅 1×", 19e3, "가정 [3]"),
             ("에이전트 ≈4×", 75e3, "SWE-bench Pro 실측 [1]"),
             ("멀티에이전트 ≈15×", 281e3, "가정 [3]")]
bb = dict(fc="white", ec="none", alpha=0.88, pad=1.2)

fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.8), dpi=220, gridspec_kw={"width_ratios": [1, 1]})

# ---------- 좌: 단일 세션, 문맥 길이 ↑ → KV ↑ ----------
x = np.linspace(0, 1e6, 300)
ax.set_xlim(0, 1.03e6); ax.set_ylim(0, 365)
ax.axhspan(TOP, 365, color="#f6d9d6", alpha=0.6, zorder=0)
for i, (name, gb) in enumerate(GPUS):
    ax.axhline(gb, color=C_RED, ls="--", lw=1.1, alpha=0.55 + 0.45 * i / (len(GPUS) - 1), zorder=1)
    ax.text(1.5e4, gb + 4, f"{name} {gb} GB", color=C_RED, fontsize=8.5, va="bottom", bbox=bb)
ax.plot(x, kv_gb(x), color=C_LINE, lw=2.4, zorder=3)
label_pos = [(6.2e5, 24), (6.2e5, 84), (6.2e5, 144)]      # 선 아래쪽 빈 영역에 라벨을 쌓고 화살표로 연결
for (name, tok, basis), (lx, ly) in zip(workloads, label_pos):
    y = kv_gb(tok)
    ax.plot(tok, y, "o", color=C_BLUE, ms=7.5, zorder=5)
    ax.annotate(f"{name}\n{tok/1e3:.0f}K · ≈{fmt_size(y)}\n({basis})", (tok, y), xytext=(lx, ly),
                textcoords="data", fontsize=8, color=C_BLUE, ha="left", va="center", bbox=bb, zorder=6,
                arrowprops=dict(arrowstyle="-", color="#999", lw=0.9, shrinkA=2, shrinkB=4))
y1m = kv_gb(1e6)
ax.plot(1e6, y1m, "*", color=C_ORG, ms=15, zorder=6, clip_on=False)
ax.annotate(f"1M · ≈{fmt_size(y1m)}\n단일 세션이 B300 1개 초과", (1e6, y1m), xytext=(-10, -2),
            textcoords="offset points", fontsize=8.5, color=C_ORG, ha="right", va="center",
            fontweight="bold", bbox=bb, zorder=6)
ax.set_xticks([0, 2e5, 4e5, 6e5, 8e5, 1e6]); ax.set_xticklabels(["0", "200K", "400K", "600K", "800K", "1M"])
ax.set_xlabel("누적 문맥 길이 (tokens)")
ax.set_ylabel("KV cache 크기 (GB)")
ax.set_title("① 단일 세션: 문맥이 길어질수록 KV cache 증가", fontsize=11, loc="left")
ax.grid(True, which="major", alpha=0.25)

# ---------- 우: 에이전트·세션 ↑ → 총 KV ↑ ----------
names = [f"채팅\n×{SESSIONS}세션", f"에이전트\n×{SESSIONS}세션", f"멀티에이전트\n×{SESSIONS}세션",
         f"ASTRA 설정 [4]\n1M × {ASTRA_AGENTS:,}\nagents"]
totals = [kv_gb(t, SESSIONS) for _, t, _ in workloads] + [kv_gb(ASTRA_CTX, ASTRA_AGENTS)]   # GB
ax2.set_yscale("log"); ax2.set_ylim(40, 3e7)
ax2.axhspan(TOP, 3e7, color="#f6d9d6", alpha=0.6, zorder=0)
bars = ax2.bar(range(4), totals, color=[C_BLUE, C_BLUE, C_BLUE, C_ORG], width=0.6, zorder=3)
for i, (name, gb) in enumerate(GPUS):
    ax2.axhline(gb, color=C_RED, ls="--", lw=1.1, alpha=0.55 + 0.45 * i / (len(GPUS) - 1), zorder=4)
    if name != "B200":
        ax2.text(1.01, gb, f"{name} {gb} GB", transform=ax2.get_yaxis_transform(), color=C_RED, fontsize=8.5,
                 va="bottom" if name == "B300" else "top")
for b, t in zip(bars, totals):
    mult = t / TOP
    m = f"≈{mult:,.0f}×" if mult < 1e3 else f"≈{round(mult, -2):,.0f}×"
    ax2.text(b.get_x() + b.get_width() / 2, t * 1.25, f"{fmt_size(t)}\n(B300 1개 대비 {m})",
             ha="center", fontsize=8.5, bbox=bb, zorder=6)
ax2.set_xlim(-0.55, 3.55)
ax2.set_xticks(range(4)); ax2.set_xticklabels(names, fontsize=9)
yt = [100, 1e3, 1e4, 1e5, 1e6, 1e7]
ax2.set_yticks(yt); ax2.set_yticklabels([fmt_size(v) for v in yt])
ax2.yaxis.set_minor_formatter(NullFormatter())
ax2.set_ylabel("총 KV cache 크기 (log)")
ax2.set_title("② 에이전트·동시 세션이 늘어나면 총 KV는 수 자릿수 증가", fontsize=11, loc="left")
ax2.grid(True, axis="y", which="major", alpha=0.25, zorder=0)

fig.text(0.008, 0.01,
         "출처: [1] arXiv:2605.26297  [2] arXiv:2608.15127  [3] Anthropic Eng. Blog  [4] ASTRA  [10] Conceptual illustration based on Continuum (Li et al., 2025), arXiv:2511.02230\n"
         "KV cache 0.33MB/token (Llama-3.1-70B, BF16). 문맥 길이: 에이전트 ≈75K [1] (SWE-bench Pro 평균 누적 문맥 69–80K), 채팅·멀티에이전트는 [3]의 토큰 사용량 배수(≈4×/≈15×)를 적용한 가정.\n"
         "점선 = GPU 1개 HBM 총량 H100 80 / B200 192 / B300 288 GB (가중치 미차감). 동시 세션 수·ASTRA 설정은 전부 KV 상주 가정의 상한 (prefix 공유·압축·양자화 미반영).",
         fontsize=6.5, color="#555", va="bottom", linespacing=1.35)
fig.tight_layout(rect=(0, 0.09, 0.985, 1))
out = "kv-demand-two-panel.png"   # 스크립트와 같은 폴더에서 실행
fig.savefig(out); print(out)
