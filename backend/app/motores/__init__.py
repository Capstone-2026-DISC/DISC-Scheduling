"""Timetabling engines behind one port: FET and OR-Tools CP-SAT as interchangeable adapters."""

from .check import check
from .model import (
    Activity,
    Availability,
    InvalidProblem,
    Placement,
    Room,
    Solution,
    Status,
    TimetableProblem,
    cost,
)
from .port import EngineError, TimetableEngine
from .registry import availability, create, names, register

__all__ = [
    "Activity",
    "Availability",
    "EngineError",
    "InvalidProblem",
    "Placement",
    "Room",
    "Solution",
    "Status",
    "TimetableEngine",
    "TimetableProblem",
    "availability",
    "check",
    "cost",
    "create",
    "names",
    "register",
]
