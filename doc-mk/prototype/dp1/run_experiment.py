"""DP1 후보 구조 비교 실험 — 문서 4.5절의 정량 지표를 실측으로 채운다.

사용:
    python -m dp1.run_experiment                # 전체 시나리오
    python -m dp1.run_experiment heterogeneous  # 하나만
"""

from __future__ import annotations

import sys

from .harness import run
from .model import TierTable
from .object_indexed import HeuristicClassifier, ObjectIndexedPlacer
from .tier_indexed import TierIndexedPlacer
from .workload import ALL_SCENARIOS

VARIANTS = {
    "C1 Tier-Indexed": lambda t: TierIndexedPlacer(t),
    "C1 + 보강(ctx)": lambda t: TierIndexedPlacer(t, context_length_term=True),
    "C1 예약 없음": lambda t: TierIndexedPlacer(t, reserve_within_step=False),
    "C2 Object-Indexed": lambda t: ObjectIndexedPlacer(t),
    "C2 단일 클래스": lambda t: ObjectIndexedPlacer(
        t, HeuristicClassifier(single_class=True)
    ),
    "C2가 C1 흉내": lambda t: ObjectIndexedPlacer(
        t, HeuristicClassifier(single_class=True), mimic_c1=True
    ),
}

COLUMNS = [
    ("placer", 19, "s"),
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


def main(argv: list[str]) -> int:
    names = argv[1:] or list(ALL_SCENARIOS)
    for name in names:
        if name not in ALL_SCENARIOS:
            print(f"알 수 없는 시나리오: {name}  (가능: {', '.join(ALL_SCENARIOS)})")
            return 2
        scenario = ALL_SCENARIOS[name]()
        print(f"\n=== {scenario.name}  —  {scenario.ref}")
        header = "".join(f"{c[0]:>{c[1]}}" for c in COLUMNS)
        print(header)
        print("-" * len(header))
        for label, make in VARIANTS.items():
            table = TierTable()
            m = run(make(table), table, scenario)
            row = m.as_row()
            row["placer"] = label
            print("".join(f"{_fmt(row[c[0]], c[2]):>{c[1]}}" for c in COLUMNS))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
