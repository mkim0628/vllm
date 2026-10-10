#!/usr/bin/env python3
"""DP2 architecture-style result document (node-internal, A Dispatcher vs B Blackboard) from results/data/arch.

    python tools/gen_dp2_arch_result.py --out doc-mk/Evaluation/DP2/results/2026-10-10_dp2-arch-styles.md

Every number comes from this module's functions (qa_result.json, qa4_modifiability*.json, SYS-H100/sens_result.json, control data);
the prose is typed by hand in PROSE below and quotes numbers only through the format helpers.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
D2 = HERE.parent / "DP2"
DATA = D2 / "results" / "data" / "arch"
B, A, BB, R = "Baseline-GPU-local", "A-Dispatcher", "B-Blackboard", "Ref-Dispatcher-with-board-rules"
NAME = {B: "Baseline-GPU-local", A: "A 중앙 Dispatcher", BB: "B Blackboard", R: "참고: Dispatcher + Blackboard 규칙"}
QA = json.loads((DATA / "qa_result.json").read_text())
QA4 = json.loads((DATA / "qa4_modifiability.json").read_text())
QA4F = json.loads((DATA / "qa4_modifiability_S2full.json").read_text()) if (DATA / "qa4_modifiability_S2full.json").exists() else None
_p = DATA / "SYS-H100" / "sens_result.json"
SENS = json.loads(_p.read_text()) if _p.exists() else None
T = QA["tables"]["combined"]
PS = QA["per_scenario"]
LAB = QA["labels"]
SETS = {"common": "Common", "stress": "DP2 Stress", "dynamic": "DP2 Dynamic"}
KEY4 = {A: "C1", BB: "C2"}          # candidate keys of tools/qa4_modifiability.py


def n_star(s):
    return s.count("★")


def x(v, d=2):
    return f"x{v:.{d}f}"


def ms(s):
    return f"{s * 1000:.1f}"


def git_rev():
    try:
        rev = subprocess.check_output(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(HERE), "status", "--porcelain", "--", str(D2)], text=True).strip()
        return rev + (" (dirty)" if dirty else "")
    except Exception:
        return "unknown"


def qa4_stars(c):
    return QA4["qa4_stars"][KEY4[c]]


def stars_total(c):
    t = T[c]
    return n_star(t["star_qa1"]) + n_star(t["star_qa2"]) + n_star(t["star_qa3"]) + n_star(qa4_stars(c))


def qa_table(tab=None):
    """§10 format table (Baseline column + A + B + reference)."""
    tab = tab or T
    b, a, bb, r = tab[B], tab[A], tab[BB], tab.get(R)
    base_gp = a["qa1_abs"] / a["qa1_ratio"]            # geometric-mean Baseline goodput (so that value = ratio x Baseline)
    base_gp_b = bb["qa1_abs"] / bb["qa1_ratio"]
    rows = ["| QA | 평가 metric | Baseline-GPU-local | A 중앙 Dispatcher | B Blackboard | 참고 (별 미부여) |", "|---|---|---:|---|---|---|"]

    def cell(c, f):
        return f(tab[c]) if c in tab else "—"
    rows.append(f"| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | {base_gp:,.0f} | {a['star_qa1']}  {a['qa1_abs']:,.0f} ({x(a['qa1_ratio'])}) | {bb['star_qa1']}  {bb['qa1_abs']:,.0f} ({x(bb['qa1_ratio'])}) | "
                + (f"{r['qa1_abs']:,.0f} ({x(r['qa1_ratio'])})" if r else "—") + " |")
    bt99, bt50 = b["ttft_p99"], b["ttft_p50"]
    bp99, bp50 = b["tpot_p99"], b["tpot_p50"]
    rows.append(f"| **QA2 Latency — TTFT** | P99 · P50 (ms) ↓ | P99 {bt99 * 1000:,.0f} · P50 {bt50 * 1000:,.0f} | "
                f"P99 {a['ttft_p99'] * 1000:,.0f} ({x(a['ttft_p99'] / bt99)}) · P50 {a['ttft_p50'] * 1000:,.0f} ({x(a['ttft_p50'] / bt50)}) | "
                f"P99 {bb['ttft_p99'] * 1000:,.0f} ({x(bb['ttft_p99'] / bt99)}) · P50 {bb['ttft_p50'] * 1000:,.0f} ({x(bb['ttft_p50'] / bt50)}) | "
                + (f"P99 {r['ttft_p99'] * 1000:,.0f} ({x(r['ttft_p99'] / bt99)})" if r else "—") + " |")
    rows.append(f"| **QA2 Latency — TPOT** | P99 · P50 (ms) ↓ | P99 {ms(bp99)} · P50 {ms(bp50)} | "
                f"P99 {ms(a['tpot_p99'])} ({x(a['tpot_p99'] / bp99)}) · P50 {ms(a['tpot_p50'])} ({x(a['tpot_p50'] / bp50)}) | "
                f"P99 {ms(bb['tpot_p99'])} ({x(bb['tpot_p99'] / bp99)}) · P50 {ms(bb['tpot_p50'])} ({x(bb['tpot_p50'] / bp50)}) | "
                + (f"P99 {ms(r['tpot_p99'])} ({x(r['tpot_p99'] / bp99)})" if r else "—") + " |")
    rows.append(f"| **QA2 별점** | 6개 지표 개선 배수(Baseline÷후보) geomean | x1.00 | {a['star_qa2']}  {x(a['qa2_impr'])} (TTFT {x(a['ttft_impr'])} · TPOT {x(a['tpot_impr'])}) | "
                f"{bb['star_qa2']}  {x(bb['qa2_impr'])} (TTFT {x(bb['ttft_impr'])} · TPOT {x(bb['tpot_impr'])}) | " + (f"{x(r['qa2_impr'])}" if r else "—") + " |")

    def q3(c):
        c_ = tab[c]
        if c_["hbm_ratio"] is None:
            return "n/a"
        return f"{c_['star_qa3']}  {c_['hbm_abs_gib']:,.0f} GiB ({x(c_['hbm_ratio'])}) [{c_['hbm_n_eq']}쌍]"
    rows.append(f"| **QA3 HBM KV 점유** | 시간 평균 점유 (GiB, 노드 합) ↓ , iso-load | {a['hbm_base_gib']:,.0f} | {q3(A)} | {q3(BB)} | " + (q3(R).split(' [')[0] if r else "—") + " |")
    rows.append(f"| **QA4 Modifiability** | module · 공수(MM) · 에이전트 비용(T1) ↓ | — | {qa4_stars(A)}  {QA4['mean_over_scenarios']['C1']['modules']:.2f} · {QA4['mean_over_scenarios']['C1']['man_months']:.2f} · ${QA4['mean_over_scenarios']['C1']['usd_T1']:.2f} [B+C] | "
                f"{qa4_stars(BB)}  {QA4['mean_over_scenarios']['C2']['modules']:.2f} · {QA4['mean_over_scenarios']['C2']['man_months']:.2f} · ${QA4['mean_over_scenarios']['C2']['usd_T1']:.2f} [B+C] | — |")
    rows.append(f"| **별 합계 (QA1~QA4)** | | — | {stars_total(A)} | {stars_total(BB)} | — |")
    return "\n".join(rows)


def set_table(name):
    t = QA["tables"][name]
    rows = ["| 후보 | 쌍 | QA1 goodput | TTFT P99 | TPOT P99 | QA2 개선 | HBM 점유 비 |", "|---|---:|---|---|---|---|---|"]
    for c in (A, BB, R):
        if c not in t or not t[c].get("n"):
            continue
        d = t[c]
        hb = x(d["hbm_ratio"]) if d.get("hbm_ratio") else "n/a"
        rows.append(f"| {NAME[c]} | {d['n']} | {x(d['qa1_ratio'])} | {x(d['ttft_p99_x'] ** -1)} | {x(d['tpot_p99_x'] ** -1)} | {x(d['qa2_impr'])} | {hb} |")
    return "\n".join(rows)


def scen_rows(scn_set=None):
    rows = ["| 시나리오 | 시스템 | fit | Baseline goodput (부하) | A goodput (부하) | B goodput (부하) | A TTFT/TPOT P99 비 | B TTFT/TPOT P99 비 | HBM 점유 비 A / B |",
            "|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(PS, key=lambda k: (k.split("|")[1], k.split("|")[0])):
        sysid, scn = key.split("|")
        v = PS[key]
        b, a, bb = v[B], v[A], v[BB]
        iso_b, iso_a, iso_bb = b["iso"], a["iso"], bb["iso"]

        def r(i, f):
            return x(i[f] / iso_b[f]) if iso_b[f] > 0 else "—"
        rows.append(f"| `{scn}` | {sysid[4:]} | {LAB[key]['fit']} | {b['goodput']:,.0f} ({b['load']:g}) | {a['goodput']:,.0f} ({a['load']:g}) | {bb['goodput']:,.0f} ({bb['load']:g}) | "
                    f"{r(iso_a, 'ttft_p99')} / {r(iso_a, 'tpot_p99')} | {r(iso_bb, 'ttft_p99')} / {r(iso_bb, 'tpot_p99')} | "
                    f"{x(iso_a['hbm_avg'] / iso_b['hbm_avg'])} / {x(iso_bb['hbm_avg'] / iso_b['hbm_avg'])} |")
    return "\n".join(rows)


def losses():
    """(key, cand, metric) where the candidate is worse than the Baseline beyond noise (paired verdicts)."""
    out = []
    for key, lab in LAB.items():
        for c in (A, BB):
            vs = lab["vs"].get(c)
            if vs and (vs["goodput"] == "loss" or vs["ttft"] == "loss" or vs["tpot"] == "loss"):
                out.append((key, c, {k: vs[k] for k in ("goodput", "ttft", "tpot")}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    if a.print:
        print(qa_table())
        for s in SETS:
            print("\n" + SETS[s]); print(set_table(s))
        print(scen_rows())
        print(len(losses()), "paired losses")
        return
    raise SystemExit("document body is added after the data is final (see PROSE)")


if __name__ == "__main__":
    main()
