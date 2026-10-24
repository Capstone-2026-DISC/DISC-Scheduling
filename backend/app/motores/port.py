"""The port every timetabling engine implements, and the template method that makes them behave alike."""

import time
from abc import ABC, abstractmethod
from typing import ClassVar

from .check import check
from .model import Availability, Solution, Status, TimetableProblem, cost


class EngineError(Exception):
    """An engine failed in a way worth reporting to the person (bad binary output, missing result file...)."""


class TimetableEngine(ABC):
    """Adapter contract. Subclasses translate `TimetableProblem` to one solver and return its raw placements.

    `solve` is the template method: it validates the problem, reports engines that are not installed, rejects problems
    with no candidate at all, times the run, turns exceptions into an `ERROR` solution and verifies the result with
    `check`. Subclasses implement only `availability` and `_solve`.
    """

    name: ClassVar[str]
    family: ClassVar[str]  # "cp", "heuristic"...

    @abstractmethod
    def availability(self) -> Availability: ...

    @abstractmethod
    def _solve(self, problem: TimetableProblem, time_limit_s: float) -> Solution:
        """Raw result of the engine: status, placements and (optionally) its bound. No cost, no verification."""

    def solve(self, problem: TimetableProblem, time_limit_s: float = 30) -> Solution:
        problem.validate()
        available = self.availability()
        if not available.ok:
            return Solution(self.name, Status.UNAVAILABLE, note=available.reason)
        stuck = [a.id for a in problem.activities if not problem.candidate_starts(a) or not problem.candidate_rooms(a)]
        if stuck:
            ids = ", ".join(map(str, stuck))
            return Solution(self.name, Status.INFEASIBLE, note=f"Sin horario o sala posible para las actividades {ids}")
        started = time.perf_counter()
        try:
            solution = self._solve(problem, time_limit_s)
        except EngineError as e:
            return Solution(self.name, Status.ERROR, note=str(e), seconds=round(time.perf_counter() - started, 3))
        except Exception as e:  # a solver can fail for licence, memory or API reasons: report it and keep going
            note = f"{type(e).__name__}: {str(e)[:160]}"
            return Solution(self.name, Status.ERROR, note=note, seconds=round(time.perf_counter() - started, 3))
        changes = {"seconds": round(time.perf_counter() - started, 3)}
        if solution.placements:
            changes["cost"] = cost(problem, solution.placements)
            changes["violations"] = tuple(check(problem, solution.placements))
        return solution.with_(**changes)
