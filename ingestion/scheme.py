"""Load and validate ``data/reference/teaching_scheme.yaml`` (ROADMAP D4).

The scheme is the authority for weekly L/T/P hours per course; the class
timetable is checked against it, never the other way round. Loading fails
with :class:`SchemeError` listing *every* problem, rather than stopping at
the first one or quietly coercing a value.

Rules checked:

- course codes are unique across the whole file;
- ``L``, ``T`` and ``P`` are non-negative integers (a YAML ``true`` is not an
  hour count, even though Python's ``bool`` is an ``int``);
- ``include`` is ``true``, ``false`` or ``if_ce_faculty`` (D3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

SCHEME_YAML = Path(__file__).resolve().parents[1] / "data" / "reference" / "teaching_scheme.yaml"

Include = bool | Literal["if_ce_faculty"]
INCLUDE_VALUES: tuple[Include, ...] = (True, False, "if_ce_faculty")
HOUR_KEYS = ("L", "T", "P")
COURSE_KEYS = ("code", "name", "category", *HOUR_KEYS, "include")


class SchemeError(ValueError):
    """The scheme file breaks a validation rule. The message lists every problem."""


@dataclass(frozen=True)
class Course:
    code: str
    name: str
    category: str
    #: Weekly hours. L is per division; T and P are per batch (D7, D9).
    L: int
    T: int
    P: int
    include: Include
    semester: int
    year: str
    pdf_page: int | None = None
    exclude_reason: str | None = None


@dataclass(frozen=True)
class SchemeSemester:
    semester: int
    year: str
    courses: tuple[Course, ...]
    note: str | None = None


@dataclass(frozen=True)
class TeachingScheme:
    version: int
    source: str
    semesters: tuple[SchemeSemester, ...]

    def courses(self) -> list[Course]:
        return [c for s in self.semesters for c in s.courses]

    def semester(self, number: int) -> SchemeSemester:
        return next(s for s in self.semesters if s.semester == number)


def _is_hours(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_include(value: Any) -> bool:
    # ``1 == True`` in Python, so compare by type as well as value.
    return any(type(value) is type(ok) and value == ok for ok in INCLUDE_VALUES)


def parse_scheme(data: dict[str, Any]) -> TeachingScheme:
    """Validate an already-loaded scheme mapping and build typed records."""
    problems: list[str] = []
    semesters: list[SchemeSemester] = []
    seen: dict[str, str] = {}
    for s_index, raw_sem in enumerate(data.get("semesters") or []):
        where_sem = f"semesters[{s_index}]"
        number, year = raw_sem.get("semester"), raw_sem.get("year")
        if not isinstance(number, int) or not isinstance(year, str):
            problems.append(f"{where_sem}: needs an integer 'semester' and a string 'year'")
            continue
        courses: list[Course] = []
        for c_index, raw in enumerate(raw_sem.get("courses") or []):
            where = f"{where_sem}.courses[{c_index}] ({raw.get('code', '?')})"
            missing = [k for k in COURSE_KEYS if k not in raw]
            if missing:
                problems.append(f"{where}: missing {missing}")
                continue
            code = raw["code"]
            if code in seen:
                problems.append(f"{where}: duplicate code {code!r} (also at {seen[code]})")
            seen.setdefault(code, where)
            bad_hours = [k for k in HOUR_KEYS if not _is_hours(raw[k])]
            if bad_hours:
                problems.append(
                    f"{where}: {', '.join(f'{k}={raw[k]!r}' for k in bad_hours)} "
                    "- hours must be non-negative integers"
                )
            if not _is_include(raw["include"]):
                problems.append(
                    f"{where}: include={raw['include']!r} - must be true, false or if_ce_faculty"
                )
            if bad_hours or not _is_include(raw["include"]):
                continue
            courses.append(
                Course(
                    code=code,
                    name=raw["name"],
                    category=raw["category"],
                    L=raw["L"],
                    T=raw["T"],
                    P=raw["P"],
                    include=raw["include"],
                    semester=number,
                    year=year,
                    pdf_page=raw.get("pdf_page"),
                    exclude_reason=raw.get("exclude_reason"),
                )
            )
        semesters.append(SchemeSemester(number, year, tuple(courses), raw_sem.get("note")))
    if not semesters:
        problems.append("no semesters")
    if problems:
        raise SchemeError("teaching scheme is invalid:\n  " + "\n  ".join(problems))
    return TeachingScheme(
        version=data.get("version", 0), source=data.get("source", ""), semesters=tuple(semesters)
    )


def load_scheme(path: Path = SCHEME_YAML) -> TeachingScheme:
    with path.open(encoding="utf-8") as handle:
        return parse_scheme(yaml.safe_load(handle))
