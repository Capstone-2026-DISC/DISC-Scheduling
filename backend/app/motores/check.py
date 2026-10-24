"""Independent verification of a solution against the problem. No engine is trusted: every solution passes through here."""

from collections import defaultdict

from .model import Placement, TimetableProblem


def check(problem: TimetableProblem, placements: tuple[Placement, ...]) -> list[str]:
    """Violations in Spanish, ready to show to a person. An empty list means the timetable is valid."""
    found: list[str] = []
    by_id = {a.id: a for a in problem.activities}
    placed: dict[int, Placement] = {}
    for p in placements:
        if p.activity_id not in by_id:
            found.append(f"Se ubicó la actividad {p.activity_id}, que no existe")
        elif p.activity_id in placed:
            found.append(f"La actividad {p.activity_id} está ubicada más de una vez")
        else:
            placed[p.activity_id] = p
    for a in problem.activities:
        p = placed.get(a.id)
        if p is None:
            found.append(f"La actividad {a.id} ({a.name}) no tiene horario")
            continue
        if (p.day, p.block) not in problem.candidate_starts(a):
            found.append(f"La actividad {a.id} ({a.name}) empieza en un bloque que no le corresponde")
        if p.room not in problem.candidate_rooms(a):
            found.append(f"La actividad {a.id} ({a.name}) está en la sala {p.room}, que no le sirve")

    busy: dict[tuple[str, str, int, int], list[int]] = defaultdict(list)
    for a in problem.activities:
        p = placed.get(a.id)
        if p is None:
            continue
        for i in range(p.block, p.block + a.duration):
            busy["sala", p.room, p.day, i].append(a.id)
            for t in a.teachers:
                busy["docente", t, p.day, i].append(a.id)
            for g in a.groups:
                busy["grupo", g, p.day, i].append(a.id)
    for (kind, who, day, block), ids in sorted(busy.items(), key=str):
        if len(ids) > 1:
            found.append(
                f"Choque de {kind} {who} el {problem.days[day]} en el bloque {problem.blocks[block]}: "
                f"actividades {', '.join(map(str, ids))}"
            )
    return found
