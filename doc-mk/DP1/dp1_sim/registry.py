from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class C1ObjectRecord:
    """Type-agnostic placement bookkeeping.

    Deliberately has no data_type/class field. C1 knows only where an object is,
    how large it is, and whether it is movable.
    """

    object_id: int
    size_bytes: float
    tier: str
    location: str
    movable: bool = True


class C1DataObjectRegistry:
    def __init__(self):
        self._records: dict[int, C1ObjectRecord] = {}

    def add(self, object_id: int, size_bytes: float, tier: str, movable: bool = True) -> None:
        self._records[object_id] = C1ObjectRecord(
            object_id=object_id,
            size_bytes=float(size_bytes),
            tier=tier,
            location=tier,
            movable=movable,
        )

    def remove(self, object_id: int) -> None:
        self._records.pop(object_id, None)

    def get(self, object_id: int) -> C1ObjectRecord | None:
        return self._records.get(object_id)

    def objects_in_tier(self, tier: str) -> list[C1ObjectRecord]:
        return [r for r in self._records.values() if r.tier == tier and r.movable]

    def move(self, object_id: int, tier: str) -> None:
        r = self._records[object_id]
        r.tier = tier
        r.location = tier

    def __iter__(self):
        return iter(self._records.values())


@dataclass
class C2ObjectRecord:
    """Type-aware AI Data metadata used by C2 behavior analysis."""

    object_id: int
    data_type: str
    size_bytes: float
    tier: str
    location: str
    class_metadata: dict[str, float | str] = field(default_factory=dict)
    behavior_metadata: dict[str, float] = field(default_factory=dict)
    movable: bool = True


class C2DataObjectRegistry:
    def __init__(self):
        self._records: dict[int, C2ObjectRecord] = {}

    def add(
        self,
        object_id: int,
        data_type: str,
        size_bytes: float,
        tier: str,
        class_metadata: dict | None = None,
        movable: bool = True,
    ) -> None:
        self._records[object_id] = C2ObjectRecord(
            object_id=object_id,
            data_type=data_type,
            size_bytes=float(size_bytes),
            tier=tier,
            location=tier,
            class_metadata=dict(class_metadata or {}),
            movable=movable,
        )

    def remove(self, object_id: int) -> None:
        self._records.pop(object_id, None)

    def get(self, object_id: int) -> C2ObjectRecord | None:
        return self._records.get(object_id)

    def objects_in_tier(self, tier: str) -> list[C2ObjectRecord]:
        return [r for r in self._records.values() if r.tier == tier and r.movable]

    def by_type(self, data_type: str) -> list[C2ObjectRecord]:
        return [r for r in self._records.values() if r.data_type == data_type]

    def move(self, object_id: int, tier: str) -> None:
        r = self._records[object_id]
        r.tier = tier
        r.location = tier

    def __iter__(self):
        return iter(self._records.values())
