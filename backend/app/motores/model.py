"""Engine-neutral description of a timetabling problem and of its solution.

Nothing here knows about FET or OR-Tools: the adapters translate this model to their own formats. The candidate
starts and rooms are derived here once, so every engine receives the same reduced problem.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum


class InvalidProblem(ValueError):
    """The problem description is inconsistent (duplicate ids, unknown rooms, a session longer than the day...)."""


@dataclass(frozen=True, slots=True)
class Room:
    id: str
    capacity: int


@dataclass(frozen=True, slots=True)
class Activity:
    """One session that must be placed once. `duration` is in blocks; `size` is the number of students."""

    id: int
    name: str
    duration: int
    size: int
    teachers: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    rooms: tuple[str, ...] | None = None  # None: any room with enough capacity
    fixed: tuple[int, int] | None = None  # (day, block) already decided


@dataclass(frozen=True, slots=True, eq=False)
class TimetableProblem:
    days: tuple[str, ...]
    blocks: tuple[str, ...]
    rooms: tuple[Room, ...]
    activities: tuple[Activity, ...]
    teacher_unavailable: Mapping[str, frozenset[tuple[int, int]]] = field(
        default_factory=dict
    )  # teacher -> {(day, block)}
    no_cross: frozenset[int] = frozenset()  # a session cannot continue from block i into block i + 1 (lunch)
    late_from: int | None = None  # sessions starting at this block or later are "late"
    late_weight: int = 1  # cost of each late session

    def validate(self) -> None:
        ids = [a.id for a in self.activities]
        if len(set(ids)) != len(ids):
            raise InvalidProblem("Hay actividades con el mismo id")
        room_ids = {r.id for r in self.rooms}
        if len(room_ids) != len(self.rooms):
            raise InvalidProblem("Hay salas con el mismo id")
        if len(set(self.blocks)) != len(self.blocks) or len(set(self.days)) != len(self.days):
            raise InvalidProblem("Los días y los bloques deben tener nombres distintos")
        for a in self.activities:
            if a.duration < 1 or a.duration > len(self.blocks):
                raise InvalidProblem(f"La actividad {a.id} dura {a.duration} bloques y el día tiene {len(self.blocks)}")
            unknown = set(a.rooms or ()) - room_ids
            if unknown:
                raise InvalidProblem(f"La actividad {a.id} nombra salas que no existen: {', '.join(sorted(unknown))}")

    def starts_fit(self, a: Activity, day: int, block: int) -> bool:
        """Whether a session of `a` can start at (day, block): it fits the day, skips the lunch cut and keeps teachers free."""
        if not (0 <= day < len(self.days)) or block < 0 or block + a.duration > len(self.blocks):
            return False
        covered = range(block, block + a.duration)
        if any(i in self.no_cross for i in covered[:-1]):
            return False
        return all((day, i) not in self.teacher_unavailable.get(t, frozenset()) for t in a.teachers for i in covered)

    def candidate_starts(self, a: Activity) -> list[tuple[int, int]]:
        if a.fixed is not None:
            return [a.fixed] if self.starts_fit(a, *a.fixed) else []
        return [(d, b) for d in range(len(self.days)) for b in range(len(self.blocks)) if self.starts_fit(a, d, b)]

    def candidate_rooms(self, a: Activity) -> list[str]:
        allowed = set(a.rooms) if a.rooms is not None else None
        return [r.id for r in self.rooms if r.capacity >= a.size and (allowed is None or r.id in allowed)]

    def is_late(self, block: int) -> bool:
        return self.late_from is not None and block >= self.late_from


class Status(StrEnum):
    OPTIMAL = "optimal"  # proven best for the common cost
    FEASIBLE = "feasible"  # valid, with no proof of being the best
    INFEASIBLE = "infeasible"  # no timetable exists, or none was found in the time given
    UNAVAILABLE = "unavailable"  # the engine is not installed here
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Placement:
    activity_id: int
    day: int
    block: int
    room: str


@dataclass(frozen=True, slots=True)
class Availability:
    ok: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Solution:
    engine: str
    status: Status
    placements: tuple[Placement, ...] = ()
    cost: float | None = None  # common metric, measured outside the engine
    bound: float | None = None  # best lower bound the engine proved, if it reports one
    seconds: float = 0.0
    note: str = ""
    violations: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.status in (Status.OPTIMAL, Status.FEASIBLE) and not self.violations

    def with_(self, **changes) -> "Solution":
        return replace(self, **changes)


def cost(problem: TimetableProblem, placements: tuple[Placement, ...]) -> float:
    """The common metric: every late session costs `late_weight`. Engines are compared on this, not on their own objective."""
    return float(problem.late_weight * sum(1 for p in placements if problem.is_late(p.block)))
