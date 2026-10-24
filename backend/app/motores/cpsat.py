"""Adapter for OR-Tools CP-SAT: the problem becomes a binary model with one variable per (activity, start, room)."""

import importlib.util
import os
from collections import defaultdict

from .model import Availability, Placement, Solution, Status, TimetableProblem
from .port import TimetableEngine


class CpSatEngine(TimetableEngine):
    name = "cp-sat"
    family = "cp"

    def __init__(self, workers: int | None = None, seed: int = 2026):
        self.workers = workers or min(os.cpu_count() or 1, 8)
        self.seed = seed

    def availability(self) -> Availability:
        if importlib.util.find_spec("ortools") is None:
            return Availability(False, "Falta la biblioteca ortools (pip install ortools)")
        return Availability(True)

    def _solve(self, problem: TimetableProblem, time_limit_s: float) -> Solution:
        from ortools.sat.python import cp_model  # imported here so the API starts even without the dependency

        model = cp_model.CpModel()
        chosen: dict[tuple[int, int, int, str], cp_model.IntVar] = {}
        busy: dict[tuple[str, str, int, int], list] = defaultdict(list)
        late = []
        for a in problem.activities:
            options = []
            for day, block in problem.candidate_starts(a):
                for room in problem.candidate_rooms(a):
                    var = model.NewBoolVar(f"x_{a.id}_{day}_{block}_{room}")
                    chosen[a.id, day, block, room] = var
                    options.append(var)
                    if problem.is_late(block):
                        late.append(var)
                    for i in range(block, block + a.duration):
                        resources = [
                            ("room", room),
                            *[("teacher", t) for t in a.teachers],
                            *[("group", g) for g in a.groups],
                        ]
                        for kind, who in resources:
                            busy[kind, who, day, i].append(var)
            model.AddExactlyOne(options)
        for variables in busy.values():
            if len(variables) > 1:
                model.AddAtMostOne(variables)
        model.Minimize(problem.late_weight * sum(late))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_s)
        solver.parameters.num_workers = self.workers
        solver.parameters.random_seed = self.seed
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            note = (
                "No existe un horario con estas reglas"
                if status == cp_model.INFEASIBLE
                else "Sin solución en el tiempo dado"
            )
            return Solution(self.name, Status.INFEASIBLE, note=note)
        placements = tuple(
            Placement(a_id, day, block, room) for (a_id, day, block, room), var in chosen.items() if solver.Value(var)
        )
        return Solution(
            self.name,
            Status.OPTIMAL if status == cp_model.OPTIMAL else Status.FEASIBLE,
            placements,
            bound=solver.BestObjectiveBound(),
        )
