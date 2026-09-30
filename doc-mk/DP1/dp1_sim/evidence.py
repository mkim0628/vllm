"""A/B/C evidence bookkeeping (qa-evaluation-criteria.md §2).

Every numeric input of the DP1 serving simulation is an ``Evidenced`` value.
Every QA output carries the union of its inputs' evidence levels plus ``C``
whenever an analytical/simulation model produced it.

  A : actual measurement on the user's A100/H100 + vLLM
  B : literature / vendor spec (B1 same-HW benchmark, B2 other workload,
      B3 spec sheet). ``ASSUMED`` values are tagged B with
      ``assumed=True`` so they surface in the uncertainty list.
  C : projection / analytical argument
"""

from __future__ import annotations

from dataclasses import dataclass, field

_ORDER = {"A": 0, "B": 1, "C": 2}


@dataclass(frozen=True)
class Evidenced:
    value: float
    level: str  # "A" | "B1" | "B2" | "B3" | "C"
    source: str = ""
    condition: str = ""
    rel_uncertainty: float = 0.0  # +-fraction, used for sensitivity bands
    assumed: bool = False

    @property
    def base_level(self) -> str:
        return self.level[0]

    def with_value(self, v: float, **kw) -> Evidenced:
        d = dict(
            value=v,
            level=self.level,
            source=self.source,
            condition=self.condition,
            rel_uncertainty=self.rel_uncertainty,
            assumed=self.assumed,
        )
        d.update(kw)
        return Evidenced(**d)

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "level": self.level,
            "source": self.source,
            "condition": self.condition,
            "rel_uncertainty": self.rel_uncertainty,
            "assumed": self.assumed,
        }


def ev(d: dict | float | int | None, default_level: str = "B3") -> Evidenced | None:
    """Parse a catalog entry: either a bare number or {value, level, ...}."""
    if d is None:
        return None
    if isinstance(d, (int, float)):
        return Evidenced(float(d), default_level)
    if d.get("value") is None:
        return None
    return Evidenced(
        float(d["value"]),
        d.get("level", default_level),
        d.get("source", ""),
        d.get("condition", ""),
        float(d.get("rel_uncertainty", 0.0)),
        bool(d.get("assumed", False)),
    )


@dataclass
class EvidenceTrail:
    """Collects which evidenced inputs influenced a result."""

    used: dict[str, Evidenced] = field(default_factory=dict)
    modeled: bool = False

    def use(self, name: str, e: Evidenced | None) -> float | None:
        if e is None:
            return None
        self.used[name] = e
        return e.value

    def label(self) -> str:
        levels = {e.base_level for e in self.used.values()}
        if self.modeled:
            levels.add("C")
        return "[" + "+".join(sorted(levels, key=_ORDER.get)) + "]" if levels else "[?]"

    def uncertainty(self) -> float:
        """Root-sum-square of relative input uncertainties (first-order)."""
        return sum(e.rel_uncertainty**2 for e in self.used.values()) ** 0.5

    def assumptions(self) -> list[str]:
        return sorted(k for k, e in self.used.items() if e.assumed)

    def merge(self, other: EvidenceTrail) -> EvidenceTrail:
        out = EvidenceTrail(dict(self.used), self.modeled or other.modeled)
        out.used.update(other.used)
        return out
