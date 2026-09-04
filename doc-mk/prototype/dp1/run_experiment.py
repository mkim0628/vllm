"""DP1 후보 비교 실험 — 문서 4.5절의 정량 지표를 실측으로 채운다.

사용:
    python -m dp1.run_experiment                    # 전체 케이스 × 전체 정책
    python -m dp1.run_experiment heterogeneous      # 케이스 하나
    python -m dp1.run_experiment --steelman         # 두 후보의 최선 형태만 비교
    python -m dp1.run_experiment --policies c1,c2-steelman  burst
    python -m dp1.run_experiment --list             # 케이스·정책 목록

케이스 설명은 `python -m dp1.cases`.
"""

from __future__ import annotations

import sys

from .cases import CASES
from .harness import run
from .model import TierTable
from .policies import POLICIES, steelman_pair

COLUMNS = [
    ("policy", 24, "s"),
    ("decisions", 10, "d"),
    ("msg/decision", 13, ".2f"),
    ("object_reads", 13, "d"),
    ("branches", 9, "d"),
    ("grades", 7, "d"),
    ("herding_1st", 12, ".2f"),
    ("overcommit", 11, "d"),
    ("separation", 11, ".2f"),
    ("bw_match", 9, ".3f"),
    ("evictions", 10, "d"),
    ("shared_viol", 12, "d"),
]


def _fmt(v, spec):
    if spec == "s":
        return str(v)
    try:
        return format(v, spec)
    except (TypeError, ValueError):
        return str(v)


def _print_case(case_key: str, policy_keys: list[str]) -> None:
    case = CASES[case_key]
    scenario = case.build()
    print(f"\n=== {case.key}   —   {case.doc_ref}")
    print(f"    {case.reproduces}")
    print(f"    볼 지표: {case.watch}")
    header = "".join(f"{c[0]:>{c[1]}}" for c in COLUMNS)
    print(header)
    print("-" * len(header))
    for key in policy_keys:
        table = TierTable()
        metrics = run(POLICIES[key].build(table), table, scenario)
        row = metrics.as_row()
        row["policy"] = POLICIES[key].label
        print("".join(f"{_fmt(row[c[0]], c[2]):>{c[1]}}" for c in COLUMNS))
        if case.key == "invariant_conflict":
            tier = metrics.placement_log.get("hot_arrival")
            print(f"{'':>24}    └ hot_arrival → {tier}, 축출 {metrics.evictions}건")


def main(argv: list[str]) -> int:
    args = argv[1:]
    policy_keys = list(POLICIES)

    if "--list" in args:
        print("\n케이스:")
        for c in CASES.values():
            print(f"  {c.key:22s} {c.doc_ref}")
        print("\n정책:")
        for p in POLICIES.values():
            mark = " ★ steelman" if p.steelman else ""
            print(f"  {p.key:20s} [{p.candidate}] {p.label}{mark}")
            print(f"  {'':20s} {p.note}")
        print("\n케이스 상세: python -m dp1.cases")
        return 0

    if "--steelman" in args:
        args = [a for a in args if a != "--steelman"]
        policy_keys = list(steelman_pair())

    for a in list(args):
        if a.startswith("--policies"):
            args.remove(a)
            spec = a.split("=", 1)[1] if "=" in a else args.pop(0)
            policy_keys = [k.strip() for k in spec.split(",")]

    unknown = [k for k in policy_keys if k not in POLICIES]
    if unknown:
        print(f"알 수 없는 정책: {', '.join(unknown)}")
        return 2

    case_keys = args or list(CASES)
    for key in case_keys:
        if key not in CASES:
            print(f"알 수 없는 케이스: {key}  (가능: {', '.join(CASES)})")
            return 2
        _print_case(key, policy_keys)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
