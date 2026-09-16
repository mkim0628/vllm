"""Modifiability (ISO/IEC 25010 Maintainability의 하위 특성) 측정.

기존 Maintainability 지표(순환복잡도·LoC·knob 수)는 전부 **대리 지표**라
"변경 비용과 상관은 있지만 그것을 직접 측정하지 않는다"는 한계가 있었다.
여기서는 변경 비용을 두 단위로 직접 추정한다.

  (1) Man-month  — COCOMO II **Reuse/Reengineering** 모델
      기존 코드를 고치는 비용을 다루는 모델이므로 "처음부터 만드는 비용"을
      재는 일반 COCOMO보다 이 용도에 맞다. LoC에서 노력을 바로 환산하지
      않고 **변경 비율(DM/CM/IM)** 을 입력으로 받으므로 순환 논리가 아니다.

  (2) 토큰      — AI가 코드를 쓰는 비중을 감안한 단위.
      변경을 하려면 **읽어야 하는 코드의 양**(변경 표면)과 **써야 하는
      코드의 양**(변경 크기)을 센다.

두 단위 모두 **변경 과제 집합**을 먼저 고정하고, 과제마다 후보별로 잰다.
과제 집합은 실행 전에 정하고 사후에 바꾸지 않는다.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: 코드의 문자→토큰 환산. tiktoken의 BPE 파일을 이 환경에서 받을 수 없어
#: 근사치를 쓴다. Python 소스는 대략 3.6 char/token이다.
#: **후보 간 비교에서는 이 계수가 약분되므로 상대 비교는 영향받지 않는다.**
CHARS_PER_TOKEN = 3.6

#: 각 후보의 고유 코드 (공통 인프라 제외 — 셋 다 쓰므로 변경 비용이 같다)
POLICY_FILES = {
    "as-is": ["policies/as_is.py"],
    "C1": ["policies/c1_memory_centric.py"],
    "C2": ["policies/c2_data_centric.py", "analyzer.py"],
}
#: 변경할 때 **읽어야** 하는 공통 인프라. 후보와 무관하게 같다.
SHARED_READ = ["core.py", "policy.py"]


# ── 변경 과제 (실행 전 고정)
#
# DM = 설계를 바꾸는 비율 [%]      CM = 코드를 바꾸는 비율 [%]
# IM = 통합·시험에 드는 비율 [%]
# 판단 근거를 과제마다 적는다. 추정이므로 근거 없이는 쓸 수 없다.
TASKS = {
    "T1_new_memory": {
        "what": "신규 메모리 1종 추가",
        "reads_shared": ["core.py"],
        "per_policy": {
            # as-is는 SPILL_ORDER에 이름을 열거하므로 설계까지 손댄다
            "as-is": dict(DM=30, CM=25, IM=40,
                          why="SPILL_ORDER에 이름을 넣어야 하고 순서를 다시 정해야 한다"),
            "C1":    dict(DM=0, CM=0, IM=10,
                          why="Configuration 한 곳. 코드 변경 0 (M-M2 측정으로 확인)"),
            "C2":    dict(DM=0, CM=0, IM=20,
                          why="Configuration 한 곳. 다만 7개 Threshold가 새 메모리에서 "
                              "옳게 동작하는지 확인해야 하므로 통합 비용이 더 든다"),
        },
    },
    "T2_step_budget_filter": {
        "what": "후보 형성에 Decode step 예산 조건 추가 (Layer 0)",
        "reads_shared": ["core.py", "policy.py"],
        "per_policy": {
            "as-is": dict(DM=0, CM=0, IM=0,
                          why="후보 형성 개념이 없다. 해당 없음"),
            "C1":    dict(DM=5, CM=5, IM=20,
                          why="FeasibilityFilter 분기 하나. 점수 함수는 그대로"),
            "C2":    dict(DM=15, CM=10, IM=45,
                          why="PlacementPolicyTable의 HOT/WARM/COLD 판정이 이미 "
                              "대역폭 임계를 쓰므로 새 조건과 중복·충돌한다. "
                              "7개 Threshold를 함께 다시 봐야 한다"),
        },
    },
    "T3_migration_budget": {
        "what": "결정점 B에 이동 예산 상한 추가",
        "reads_shared": ["core.py", "policy.py"],
        "per_policy": {
            "as-is": dict(DM=20, CM=20, IM=30,
                          why="결정점 B가 고정 순서라 예산 개념을 새로 넣어야 한다"),
            "C1":    dict(DM=10, CM=15, IM=25,
                          why="Planner가 결정 직후 예산을 보고 제자리 유지로 되돌리면 된다"),
            "C2":    dict(DM=25, CM=25, IM=50,
                          why="분류(Analyze→Classify→Refine) 세 단계 모두가 이동을 "
                              "전제하므로 되돌림이 각 단계에 전파된다"),
        },
    },
    "T4_new_reactivation_mode": {
        "what": "새 재활성 모드 1종 추가 (Mode D)",
        "reads_shared": ["core.py", "policy.py"],
        "per_policy": {
            "as-is": dict(DM=40, CM=35, IM=40,
                          why="모드 선택 로직이 없어 새로 만들어야 한다"),
            "C1":    dict(DM=20, CM=20, IM=30,
                          why="argmax는 그대로 두고 모드 판정만 확장"),
            "C2":    dict(DM=40, CM=35, IM=60,
                          why="KVClass 3종 x 모드의 조합이 늘어난다. "
                              "PlacementPolicyTable이 곱으로 커진다"),
        },
    },
}

#: COCOMO II Reuse 모델 상수
AA = 4          # Assessment & Assimilation [0~8]. 문서화된 코드이므로 중간
A_CONST = 2.94  # COCOMO II Post-Architecture 계수
E_EXP = 1.10    # 규모 지수 (nominal scale factors)


def software_understanding(cyclomatic: int) -> int:
    """SU [10~50] — 코드를 이해하는 데 드는 추가 비용.

    COCOMO II는 구조·명료성·자기문서화로 SU를 정한다. 여기서는
    **측정된 순환복잡도**에서 유도한다 (McCabe 1976 / NIST SP 500-235의
    구간과 같은 경계를 쓴다).
        CC <= 10  구조가 단순      -> SU 20
        CC 11~20  보통             -> SU 30
        CC >  20  복잡·위험 구간   -> SU 40
    """
    if cyclomatic <= 10:
        return 20
    if cyclomatic <= 20:
        return 30
    return 40


def _chars_and_sloc(files: list[str]) -> tuple[int, int]:
    """주석·docstring을 뺀 유효 문자 수와 SLOC."""
    from .static_metrics import _strip
    chars = sloc = 0
    for rel in files:
        lines = _strip((ROOT / rel).read_text())
        sloc += len(lines)
        chars += sum(len(l) for l in lines)
    return chars, sloc


def measure() -> dict:
    from .static_metrics import analyze

    cc = {k: analyze(v)["M_M4_branch_coverage_cases"] for k, v in POLICY_FILES.items()}
    own = {k: _chars_and_sloc(v) for k, v in POLICY_FILES.items()}
    shared_chars = {f: _chars_and_sloc([f])[0] for f in SHARED_READ}

    out: dict = {"cyclomatic": cc, "chars_per_token": CHARS_PER_TOKEN,
                 "own_code": {k: {"chars": c, "sloc": s} for k, (c, s) in own.items()},
                 "tasks": {}}

    for tname, t in TASKS.items():
        row = {"what": t["what"], "per_policy": {}}
        read_shared = sum(shared_chars[f] for f in t["reads_shared"])
        for kind, p in t["per_policy"].items():
            chars, sloc = own[kind]
            su = software_understanding(cc[kind])
            dm, cm, im = p["DM"], p["CM"], p["IM"]
            aaf = 0.4 * dm + 0.3 * cm + 0.3 * im
            # COCOMO II Reuse: ESLOC = ASLOC x (AA + AAF + SU x (1 - AT/100)) / 100
            # 자동변환(AT)은 없으므로 0.
            esloc = sloc * (AA + aaf + su) / 100.0
            pm = A_CONST * (max(esloc, 1.0) / 1000.0) ** E_EXP if esloc > 0 else 0.0
            # 토큰: 읽어야 하는 것(공통 + 고유) + 써야 하는 것(변경 비율 x 고유)
            read_tokens = (read_shared + chars) / CHARS_PER_TOKEN
            write_tokens = chars * (cm / 100.0) / CHARS_PER_TOKEN
            row["per_policy"][kind] = {
                "why": p["why"], "DM": dm, "CM": cm, "IM": im,
                "SU": su, "AAF": round(aaf, 2), "ESLOC": round(esloc, 1),
                "person_months": round(pm, 4),
                "read_tokens": round(read_tokens),
                "write_tokens": round(write_tokens),
                "total_tokens": round(read_tokens + write_tokens),
            }
        out["tasks"][tname] = row

    # 과제 합계
    out["totals"] = {}
    for kind in POLICY_FILES:
        pms = sum(out["tasks"][t]["per_policy"][kind]["person_months"] for t in TASKS)
        tks = sum(out["tasks"][t]["per_policy"][kind]["total_tokens"] for t in TASKS)
        out["totals"][kind] = {"person_months": round(pms, 4), "tokens": tks,
                               "person_days": round(pms * 19, 2)}
    return out


def main() -> None:
    r = measure()
    p = ROOT / "modifiability.json"
    p.write_text(json.dumps(r, indent=2, ensure_ascii=False))
    print(f"{'과제':26s}{'as-is':>22s}{'C1':>22s}{'C2':>22s}")
    print(f"{'':26s}" + "".join(f"{'PM / 토큰':>22s}" for _ in range(3)))
    for t, v in r["tasks"].items():
        cells = []
        for k in ("as-is", "C1", "C2"):
            d = v["per_policy"][k]
            cells.append(f"{d['person_months']:.3f} / {d['total_tokens']//1000}K")
        print(f"{t:26s}" + "".join(f"{c:>22s}" for c in cells))
    print(f"\n{'합계':26s}" + "".join(
        f"{r['totals'][k]['person_months']:.3f}PM({r['totals'][k]['person_days']:.1f}일) / "
        f"{r['totals'][k]['tokens']//1000}K".rjust(22) for k in ("as-is", "C1", "C2")))
    print(f"\n순환복잡도(SU 유도): {r['cyclomatic']}")
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
