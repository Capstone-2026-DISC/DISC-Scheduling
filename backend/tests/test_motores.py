"""Timetabling engines behind one port: model, verifier, CP-SAT, FET and the registry."""

import xml.etree.ElementTree as ET

import pytest
from app import motores
from app.motores import fet
from app.motores.model import Activity, InvalidProblem, Placement, Room, Status, TimetableProblem

FET_AVAILABLE = fet.locate() is not None
needs_fet = pytest.mark.skipif(not FET_AVAILABLE, reason="fet-cl no está instalado")

DAYS = ("Lunes", "Martes", "Miércoles")
BLOCKS = tuple("ABCDEFG")


def problem(**changes) -> TimetableProblem:
    base = dict(
        days=DAYS,
        blocks=BLOCKS,
        rooms=(Room("S1", 40), Room("S2", 20)),
        activities=(
            Activity(1, "Cálculo", 2, 35, teachers=("ana",), groups=("ICCI-1",)),
            Activity(2, "Álgebra", 2, 30, teachers=("ana",), groups=("ICCI-2",)),
            Activity(3, "Física", 2, 18, teachers=("luis",), groups=("ICCI-1",)),
            Activity(4, "Programación", 3, 15, teachers=("luis",), groups=("ICCI-2",)),
        ),
        no_cross=frozenset({2}),  # no session crosses from block C into D (lunch)
        late_from=5,
        late_weight=3,
    )
    base.update(changes)
    return TimetableProblem(**base)


# -- model ------------------------------------------------------------------------------------------------------------
def test_candidates_respect_lunch_availability_capacity_and_the_day_length():
    p = problem(teacher_unavailable={"ana": frozenset({(0, 0), (0, 1)})})
    starts = p.candidate_starts(p.activities[0])  # Cálculo: 2 blocks, ana
    assert (0, 0) not in starts and (0, 1) not in starts  # ana is busy on Monday A and B
    assert (0, 2) not in starts  # would cross the lunch cut between C and D
    assert (0, 6) not in starts  # does not fit in the day
    assert (0, 3) in starts and (1, 0) in starts
    assert p.candidate_rooms(p.activities[0]) == ["S1"]  # 35 students do not fit in S2 (20)
    assert p.candidate_rooms(p.activities[2]) == ["S1", "S2"]


def test_a_fixed_activity_has_a_single_start_or_none_if_it_does_not_fit():
    ok = Activity(9, "Fija", 2, 10, fixed=(1, 3))
    bad = Activity(10, "Mal fija", 2, 10, fixed=(1, 2))  # crosses lunch
    p = problem(activities=(ok, bad))
    assert p.candidate_starts(ok) == [(1, 3)] and p.candidate_starts(bad) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"activities": (Activity(1, "A", 1, 1), Activity(1, "B", 1, 1))},
        {"activities": (Activity(1, "A", 8, 1),)},
        {"activities": (Activity(1, "A", 1, 1, rooms=("no-existe",)),)},
        {"rooms": (Room("S1", 1), Room("S1", 2))},
    ],
)
def test_an_inconsistent_problem_is_rejected(changes):
    with pytest.raises(InvalidProblem):
        problem(**changes).validate()


# -- verifier -----------------------------------------------------------------------------------------------------------
def test_the_verifier_accepts_a_good_timetable_and_names_each_clash():
    p = problem()
    good = (Placement(1, 0, 0, "S1"), Placement(2, 1, 0, "S1"), Placement(3, 0, 3, "S2"), Placement(4, 1, 3, "S2"))
    assert motores.check(p, good) == []
    clash = (Placement(1, 0, 0, "S1"), Placement(2, 0, 1, "S1"), Placement(3, 0, 3, "S2"), Placement(4, 1, 3, "S2"))
    found = motores.check(p, clash)
    assert any("docente ana" in v for v in found) and any("sala S1" in v for v in found)
    assert any("no tiene horario" in v for v in motores.check(p, good[:3]))
    assert any("no le sirve" in v for v in motores.check(p, (Placement(1, 0, 0, "S2"), *good[1:])))


def test_the_common_cost_counts_only_the_late_sessions():
    p = problem()
    placements = (
        Placement(1, 0, 0, "S1"),
        Placement(2, 0, 5, "S1"),
        Placement(3, 1, 0, "S1"),
        Placement(4, 1, 4, "S1"),
    )
    assert motores.cost(p, placements) == 3  # only activity 2 starts at block F or later


# -- CP-SAT -------------------------------------------------------------------------------------------------------------
def test_cpsat_finds_the_best_timetable_and_it_passes_the_verifier():
    s = motores.create("cp-sat", workers=1).solve(problem(), time_limit_s=20)
    assert s.status == Status.OPTIMAL and s.valid and s.violations == ()
    assert s.cost == 0 and len(s.placements) == 4  # everything fits before the late blocks


def test_cpsat_pushes_a_session_to_a_late_block_only_when_it_has_to():
    crowded = tuple(Activity(i, f"Ramo {i}", 1, 10, teachers=("ana",), groups=("G",)) for i in range(1, 8))
    s = motores.create("cp-sat", workers=1).solve(problem(days=("Lunes",), activities=crowded, rooms=(Room("S1", 40),)))
    assert s.status == Status.OPTIMAL and s.valid
    assert s.cost == 3 * 2  # 7 sessions of one teacher in 7 blocks of one day: F and G are unavoidable


def test_cpsat_reports_a_problem_with_no_solution_and_why():
    two = (Activity(1, "A", 1, 5, teachers=("ana",)), Activity(2, "B", 1, 5, teachers=("ana",)))
    s = motores.create("cp-sat", workers=1).solve(problem(days=("Lunes",), blocks=("A",), activities=two))
    assert s.status == Status.INFEASIBLE and not s.valid and s.note


def test_a_session_nobody_can_host_is_reported_before_calling_the_solver():
    huge = (Activity(1, "Masivo", 1, 500),)
    s = motores.create("cp-sat").solve(problem(activities=huge))
    assert s.status == Status.INFEASIBLE and "1" in s.note


def test_a_failure_inside_an_engine_becomes_an_error_solution(monkeypatch):
    engine = motores.create("cp-sat")
    monkeypatch.setattr(type(engine), "_solve", lambda self, p, t: (_ for _ in ()).throw(RuntimeError("boom")))
    s = engine.solve(problem())
    assert s.status == Status.ERROR and "RuntimeError" in s.note and not s.valid


# -- FET ----------------------------------------------------------------------------------------------------------------
def test_the_fet_input_describes_the_problem_and_escapes_text():
    p = problem(activities=(Activity(1, "Cálculo & Álgebra <I>", 2, 10, teachers=("ana",), groups=("ICCI-1",)),))
    xml = fet.build_input(p)
    root = ET.fromstring(xml)  # well-formed, with the text escaped
    assert len(root.findall("Days_List/Day")) == 3 and len(root.findall("Hours_List/Hour")) == 7
    assert root.findtext("Activities_List/Activity/Subject") == "Cálculo & Álgebra <I>"
    assert root.findtext("Teachers_List/Teacher/Name") == "ana"
    assert root.findtext("Space_Constraints_List/ConstraintActivityPreferredRooms/Number_of_Preferred_Rooms") == "2"
    starts = root.findall("Time_Constraints_List/ConstraintActivityPreferredStartingTimes/Preferred_Starting_Time")
    assert ("Lunes", "C") not in {(s.findtext("Day"), s.findtext("Hour")) for s in starts}  # crossing the lunch cut
    assert ("Lunes", "D") in {(s.findtext("Day"), s.findtext("Hour")) for s in starts}


def test_fet_without_the_binary_says_so_instead_of_failing():
    s = motores.create("fet", binary="/no/existe/fet-cl").solve(problem())
    assert s.status == Status.UNAVAILABLE and "fet-cl" in s.note and not s.valid


@needs_fet
def test_fet_returns_a_timetable_that_passes_the_same_verifier():
    s = motores.create("fet").solve(problem(), time_limit_s=20)
    assert s.status == Status.FEASIBLE and s.valid, s.violations or s.note
    assert len(s.placements) == 4


@needs_fet
def test_both_engines_solve_the_same_problem_and_are_judged_by_the_same_cost():
    p = problem()
    results = {name: motores.create(name).solve(p, time_limit_s=20) for name in ("cp-sat", "fet")}
    assert all(r.valid for r in results.values()), {n: r.violations or r.note for n, r in results.items()}
    assert results["cp-sat"].cost <= results["fet"].cost  # the exact engine never does worse on the common cost


# -- registry -----------------------------------------------------------------------------------------------------------
def test_the_registry_creates_engines_by_name_and_lists_their_availability():
    assert motores.names() == ["cp-sat", "fet"]
    assert isinstance(motores.create("cp-sat"), motores.TimetableEngine)
    assert set(motores.availability()) == {"cp-sat", "fet"}
    assert motores.availability()["cp-sat"].ok
    with pytest.raises(KeyError, match="desconocido"):
        motores.create("gurobi")


def test_a_new_engine_is_one_class_and_one_registration():
    class Dummy(motores.TimetableEngine):
        name, family = "dummy", "test"

        def availability(self):
            return motores.Availability(True)

        def _solve(self, problem, time_limit_s):
            return motores.Solution(self.name, Status.FEASIBLE, ())

    motores.register(Dummy)
    try:
        assert (
            "dummy" in motores.names()
            and motores.create("dummy").solve(problem(activities=())).status == Status.FEASIBLE
        )
    finally:
        from app.motores import registry

        registry._ENGINES.pop("dummy")
