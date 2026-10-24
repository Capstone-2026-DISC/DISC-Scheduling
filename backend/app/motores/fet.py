"""Adapter for FET (fet-cl): the problem becomes a .fet file, the binary runs in a child process, its XML is read back.

FET is a heuristic engine: it finds a valid timetable fast but does not prove it is the best, so its status is FEASIBLE.
The derived candidate starts and rooms go in as preferred-time and preferred-room constraints, which also carry the lunch
cut and the teachers' availability.
"""

import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from .model import Activity, Availability, Placement, Solution, Status, TimetableProblem
from .port import EngineError, TimetableEngine

FET_VERSION = "7.10.5"
DEFAULT_PATH = "/opt/fet/bin/fet-cl"


def locate(binary: str | None = None) -> str | None:
    """An explicit path wins and is not second-guessed; otherwise FET_CL, the image's /opt/fet, then PATH."""
    candidates = [binary] if binary else [os.environ.get("FET_CL"), DEFAULT_PATH, shutil.which("fet-cl")]
    return next((c for c in candidates if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def _tag(name: str, value, indent: str = "\t") -> str:
    return f"{indent}<{name}>{escape(str(value))}</{name}>\n"


def _weight(percent: int = 100) -> str:
    return f"\t<Weight_Percentage>{percent}</Weight_Percentage>\n"


_TAIL = "\t<Active>true</Active>\n\t<Comments></Comments>\n"


def build_input(problem: TimetableProblem, seed_label: str = "DISC") -> str:
    """The .fet document for the problem. Pure function: easy to test without the binary."""
    teachers = sorted({t for a in problem.activities for t in a.teachers})
    groups = sorted({g for a in problem.activities for g in a.groups})
    subjects = sorted({a.name for a in problem.activities})
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<fet version="{FET_VERSION}">\n<Mode>Official</Mode>\n']
    out.append(f"<Institution_Name>{escape(seed_label)}</Institution_Name>\n<Comments></Comments>\n")
    out.append(f"<Days_List>\n<Number_of_Days>{len(problem.days)}</Number_of_Days>\n")
    out += [f"<Day>\n{_tag('Name', d)}</Day>\n" for d in problem.days] + ["</Days_List>\n"]
    out.append(f"<Hours_List>\n<Number_of_Hours>{len(problem.blocks)}</Number_of_Hours>\n")
    out += [f"<Hour>\n{_tag('Name', b)}</Hour>\n" for b in problem.blocks] + ["</Hours_List>\n"]
    out.append(
        "<Subjects_List>\n"
        + "".join(f"<Subject>\n{_tag('Name', s)}</Subject>\n" for s in subjects)
        + "</Subjects_List>\n"
    )
    out.append("<Activity_Tags_List>\n</Activity_Tags_List>\n<Buildings_List>\n</Buildings_List>\n<Teachers_List>\n")
    out += [
        f"<Teacher>\n{_tag('Name', t)}\t<Target_Number_of_Hours>0</Target_Number_of_Hours>\n"
        "\t<Qualified_Subjects>\n\t</Qualified_Subjects>\n</Teacher>\n"
        for t in teachers
    ]
    out.append("</Teachers_List>\n<Rooms_List>\n")
    out += [
        f"<Room>\n{_tag('Name', r.id)}\t<Building></Building>\n{_tag('Capacity', r.capacity)}\t<Virtual>false</Virtual>\n</Room>\n"
        for r in problem.rooms
    ]
    out.append("</Rooms_List>\n<Students_List>\n")
    out += [
        f"<Year>\n{_tag('Name', g)}\t<Number_of_Students>0</Number_of_Students>\n"
        "\t<Number_of_Categories>0</Number_of_Categories>\n\t<Separator> </Separator>\n</Year>\n"
        for g in groups
    ]
    out.append("</Students_List>\n<Activities_List>\n")
    for a in problem.activities:
        out.append(
            "<Activity>\n"
            + "".join(_tag("Teacher", t) for t in a.teachers)
            + _tag("Subject", a.name)
            + "".join(_tag("Students", g) for g in a.groups)
            + _tag("Duration", a.duration)
            + _tag("Total_Duration", a.duration)
            + _tag("Id", a.id)
            + _tag("Activity_Group_Id", 0)
            + "\t<Active>true</Active>\n</Activity>\n"
        )
    out.append("</Activities_List>\n<Time_Constraints_List>\n")
    out.append(f"<ConstraintBasicCompulsoryTime>\n{_weight()}{_TAIL}</ConstraintBasicCompulsoryTime>\n")
    for a in problem.activities:
        out.append(_start_constraint(problem, a))
    out.append("</Time_Constraints_List>\n<Space_Constraints_List>\n")
    out.append(f"<ConstraintBasicCompulsorySpace>\n{_weight()}{_TAIL}</ConstraintBasicCompulsorySpace>\n")
    for a in problem.activities:
        rooms = problem.candidate_rooms(a)
        out.append(
            f"<ConstraintActivityPreferredRooms>\n{_weight()}{_tag('Activity_Id', a.id)}"
            f"{_tag('Number_of_Preferred_Rooms', len(rooms))}"
            + "".join(_tag("Preferred_Room", r) for r in rooms)
            + f"{_TAIL}</ConstraintActivityPreferredRooms>\n"
        )
    out.append("</Space_Constraints_List>\n</fet>\n")
    return "".join(out)


def _start_constraint(problem: TimetableProblem, a: Activity) -> str:
    starts = problem.candidate_starts(a)
    if a.fixed is not None:
        day, block = a.fixed
        return (
            f"<ConstraintActivityPreferredStartingTime>\n{_weight()}{_tag('Activity_Id', a.id)}"
            f"{_tag('Day', problem.days[day])}{_tag('Hour', problem.blocks[block])}"
            f"\t<Permanently_Locked>false</Permanently_Locked>\n{_TAIL}</ConstraintActivityPreferredStartingTime>\n"
        )
    times = "".join(
        f"\t<Preferred_Starting_Time>\n{_tag('Day', problem.days[d], chr(9) * 2)}"
        f"{_tag('Hour', problem.blocks[b], chr(9) * 2)}\t</Preferred_Starting_Time>\n"
        for d, b in starts
    )
    return (
        f"<ConstraintActivityPreferredStartingTimes>\n{_weight()}{_tag('Activity_Id', a.id)}"
        f"{_tag('Number_of_Preferred_Starting_Times', len(starts))}{times}{_TAIL}</ConstraintActivityPreferredStartingTimes>\n"
    )


def read_output(problem: TimetableProblem, activities_xml: Path) -> tuple[Placement, ...]:
    days = {d: i for i, d in enumerate(problem.days)}
    blocks = {b: i for i, b in enumerate(problem.blocks)}
    placements = []
    for node in ET.parse(activities_xml).getroot().findall("Activity"):
        room = node.find("Room")
        placements.append(
            Placement(
                int(node.findtext("Id")),
                days[node.findtext("Day")],
                blocks[node.findtext("Hour")],
                room.text if room is not None and room.text else "",
            )
        )
    return tuple(placements)


class FetEngine(TimetableEngine):
    name = "fet"
    family = "heuristic"

    def __init__(self, binary: str | None = None, seed: int = 2026):
        self.binary = binary
        self.seed = seed

    def availability(self) -> Availability:
        if locate(self.binary) is None:
            return Availability(False, "No se encontró fet-cl (variable FET_CL o /opt/fet/bin/fet-cl)")
        return Availability(True)

    def _seeds(self) -> list[str]:
        """Six reproducible seeds derived from the one the caller gives."""
        state = self.seed or 1
        seeds = []
        for _ in range(6):
            state = (state * 1103515245 + 12345) % 2**31
            seeds.append(f"{state + 1}")
        return seeds

    def _solve(self, problem: TimetableProblem, time_limit_s: float) -> Solution:
        binary = locate(self.binary)
        with tempfile.TemporaryDirectory(prefix="fet-") as tmp:
            workdir = Path(tmp)
            source = workdir / "problem.fet"
            source.write_text(build_input(problem), encoding="utf-8")
            command = [
                binary,
                f"--inputfile={source}",
                f"--outputdir={workdir / 'out'}",
                f"--timelimitseconds={max(1, int(time_limit_s))}",
                "--writetimetablesxml=true",
                "--writetimetablesactivities=true",
                "--htmllevel=0",
                *[
                    f"--randomseeds{n}={s}"
                    for n, s in zip(("10", "11", "12", "20", "21", "22"), self._seeds(), strict=True)
                ],
            ]
            try:
                run = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=time_limit_s + 30,
                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                )
            except subprocess.TimeoutExpired as e:
                raise EngineError("fet-cl no terminó en el tiempo permitido") from e
            found = list(workdir.glob("out/timetables/*/*_activities.xml"))
            if "Generation successful" not in run.stdout or not found:
                tail = (run.stdout[-200:] + run.stderr[-200:]).strip()
                return Solution(self.name, Status.INFEASIBLE, note=f"FET no encontró un horario. {tail}")
            return Solution(self.name, Status.FEASIBLE, read_output(problem, found[0]))
