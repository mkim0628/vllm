"""Maintainability 대리 지표 (M-M1~M-M4) — 실제 구현 코드에서 센다.

**이 넷은 모두 대리 지표(proxy)다.** 변경 비용과 상관은 있지만 그것을
직접 측정하지 않는다. 논증의 방향으로 읽어야 하고 결론으로 읽으면 안 된다.

대조군으로 As-Is를 함께 센다 — C1-C2 간 격차보다 "정책이 있는가 없는가"의
격차가 더 클 수 있고, 그 경우 이 QA에서 의미 있는 대비가 무엇인지가
결과로 드러난다 (설계 문서 §11.4).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: 각 정책이 자기 결정 경로에서 실제로 쓰는 모듈.
#: 공통 인프라(core/policy/engine)는 셋 다 쓰므로 제외하고,
#: **그 정책 때문에 존재하는 코드**만 센다.
POLICY_FILES = {
    "as-is": ["policies/as_is.py"],
    "C1": ["policies/c1_memory_centric.py"],
    "C2": ["policies/c2_data_centric.py", "analyzer.py"],
}


def _strip(src: str) -> list[str]:
    """주석과 docstring을 뺀 유효 LoC."""
    tree = ast.parse(src)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d is not None and node.body:
                first = node.body[0]
                for ln in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                    doc_lines.add(ln)
    out = []
    for i, line in enumerate(src.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#") or i in doc_lines:
            continue
        out.append(line)
    return out


def analyze(files: list[str]) -> dict:
    branches = loops = methods = classes = state_fields = 0
    knobs = 0
    loc = 0
    tunable_names: list[str] = []

    for rel in files:
        src = (ROOT / rel).read_text()
        loc += len(_strip(src))
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                branches += 1
            elif isinstance(node, (ast.For, ast.While, ast.comprehension)):
                loops += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods += 1
            elif isinstance(node, ast.ClassDef):
                classes += 1
                # Enum 멤버는 타입의 값이지 Tuning Knob이 아니다.
                is_enum = any(
                    (isinstance(b, ast.Name) and b.id.endswith("Enum"))
                    or (isinstance(b, ast.Attribute) and b.attr.endswith("Enum"))
                    for b in node.bases)
                if is_enum:
                    continue
                # 클래스 수준 대문자 상수 = 동작을 바꾸는 Threshold
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for tgt in stmt.targets:
                            if isinstance(tgt, ast.Name) and tgt.id.isupper():
                                knobs += 1
                                tunable_names.append(f"{node.name}.{tgt.id}")
            elif isinstance(node, ast.BoolOp):
                # and/or 하나가 분기 하나를 더한다
                branches += len(node.values) - 1
            # self.x = ... 는 정책 내부 state
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, ast.Attribute)
                            and isinstance(tgt.value, ast.Name)
                            and tgt.value.id == "self"):
                        state_fields += 1

    return {
        "files": files,
        "loc": loc,
        "branches": branches,
        "loops": loops,
        "methods": methods,
        "classes": classes,
        "state_fields": state_fields,
        "tuning_knobs": knobs,
        "tunable_names": sorted(set(tunable_names)),
        # M-M1 정책 결정 경로 복잡도 — 분기+루프+state+method의 합
        "M_M1_decision_path_complexity": branches + loops + state_fields + methods,
        # M-M4 결정 분기 커버리지 비용 — 모든 분기를 한 번씩 밟는 데 필요한
        # 최소 테스트 수의 하한. 순차 분기는 분기 수 + 1이 하한이다.
        "M_M4_branch_coverage_cases": branches + 1,
    }


def m_m2_change_points() -> dict:
    """M-M2 — 신규 메모리 하나를 추가할 때 수정이 필요한 파일/지점 수.

    구현이 Configuration 단일 경로를 지키는지 코드로 확인한다: 정책 코드가
    메모리 **이름이나 Medium 값을 열거**하면 그만큼 변경 지점이 늘어난다.
    """
    from .core import Medium

    medium_names = {m.name for m in Medium}
    out = {}
    for kind, files in POLICY_FILES.items():
        hits = []
        for rel in files:
            src = (ROOT / rel).read_text()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                # 문자열 리터럴로 메모리 이름을 열거하는가
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    v = node.value
                    if v in {"hbm", "custom_hbm", "cxl_pnm", "dram", "hbf", "ssd_pim"}:
                        hits.append(f"{rel}:{node.lineno} literal '{v}'")
                # Medium.X 를 참조하는가
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "Medium"
                        and node.attr in medium_names):
                    hits.append(f"{rel}:{node.lineno} Medium.{node.attr}")
        out[kind] = {
            # Configuration(JSON) 1곳은 어느 정책이든 공통으로 고쳐야 한다
            "config_change_points": 1,
            "code_change_points": len(hits),
            "total": 1 + len(hits),
            "hits": hits,
        }
    return out


def main() -> None:
    res = {
        "per_policy": {k: analyze(v) for k, v in POLICY_FILES.items()},
        "M_M2": m_m2_change_points(),
        # C1과 C2가 **함께** 쓰는 산술의 knob. 어느 한쪽 고유가 아니므로
        # 정책별 M-M3에서 빼고 따로 센다.
        "shared_knobs": analyze(["policy.py"])["tunable_names"],
    }
    out = ROOT / "static_metrics.json"
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False))

    print(f"{'':8s} {'LoC':>5s} {'분기':>5s} {'메서드':>6s} {'state':>6s} "
          f"{'M-M1':>6s} {'M-M3':>6s} {'M-M4':>6s} {'M-M2':>6s}")
    for k in ["as-is", "C1", "C2"]:
        a = res["per_policy"][k]
        m2 = res["M_M2"][k]["total"]
        print(f"{k:8s} {a['loc']:5d} {a['branches']:5d} {a['methods']:6d} "
              f"{a['state_fields']:6d} {a['M_M1_decision_path_complexity']:6d} "
              f"{a['tuning_knobs']:6d} {a['M_M4_branch_coverage_cases']:6d} {m2:6d}")
    print(f"\n공유 knob (C1/C2 공통, TierScorer): {res['shared_knobs']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
