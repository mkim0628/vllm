from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class EventType(Enum):
    ALLOCATED = auto()
    ACCESSED = auto()
    FREED = auto()
    TELEMETRY = auto()
    PHASE_CHANGE = auto()


@dataclass(frozen=True)
class MigrationEvent:
    type: EventType
    now_s: float
    object_id: int | None = None
    resource_id: str | None = None
    count: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SchedulerStats:
    pushed: int = 0
    dispatched: int = 0
    coalesced: int = 0
    decision_cycles: int = 0
    decision_overhead_us: float = 0.0


class MigrationScheduler:
    """Event-driven DP1 entry point.

    This scheduler starts a *decision* cycle. It is intentionally distinct from
    an execution-side migration queue that orders already-created migration jobs.
    """

    def __init__(self, coalesce_telemetry: bool = True):
        self._q: deque[MigrationEvent] = deque()
        self.coalesce_telemetry = coalesce_telemetry
        self.stats = SchedulerStats()

    def push(self, event: MigrationEvent) -> None:
        if self.coalesce_telemetry and event.type is EventType.TELEMETRY:
            for i in range(len(self._q) - 1, -1, -1):
                if self._q[i].type is EventType.TELEMETRY:
                    del self._q[i]
                    self.stats.coalesced += 1
                    break
        self._q.append(event)
        self.stats.pushed += 1

    def drain(self, policy, ctx) -> list:
        decisions = []
        while self._q:
            ev = self._q.popleft()
            self.stats.dispatched += 1
            out, cost_us = policy.on_event(ev, ctx)
            self.stats.decision_overhead_us += float(cost_us)
            if out:
                self.stats.decision_cycles += 1
                decisions.extend(out)
        return decisions
