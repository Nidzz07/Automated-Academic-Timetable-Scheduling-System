"""data/reference/time_grid.yaml must say exactly what ROADMAP section 5 says."""

from __future__ import annotations

import re

from ingestion.class_tt import COFFEE_PERIOD, DAYS, LUNCH_PERIOD, PERIOD_TIMES
from ingestion.seed_reference import REPO_ROOT

#: ROADMAP prints the time ranges with an en dash (U+2013).
_ROW = re.compile(r"^\| P(\d) \| (\d\d:\d\d)\u2013(\d\d:\d\d) \| (\w+) \| (\w+) \|$")


def _section_5() -> list[tuple[int, str, str, str, str]]:
    text = (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    section = text.split("## 5. Time grid", 1)[1].split("\n## ", 1)[0]
    return [
        (int(m[1]), m[2], m[3], m[4], m[5])
        for m in (_ROW.match(line) for line in section.splitlines())
        if m
    ]


def test_periods_match_roadmap_section_5() -> None:
    rows = _section_5()
    assert len(rows) == 10
    assert {p: (start, end) for p, start, end, _, _ in rows} == PERIOD_TIMES


def test_coffee_and_lunch_match_roadmap_section_5() -> None:
    rows = _section_5()
    assert [p for p, _, _, se, te in rows if se == te == "coffee"] == [COFFEE_PERIOD]
    assert LUNCH_PERIOD == {
        "SE": next(p for p, _, _, se, _ in rows if se == "LUNCH"),
        "TE": next(p for p, _, _, _, te in rows if te == "LUNCH"),
    }
    teaching = {year: [p for p, _, _, se, te in rows if (se, te)[i] == "teach"]
                for i, year in enumerate(("SE", "TE"))}
    assert all(len(periods) == 8 for periods in teaching.values())


def test_days_match_roadmap_section_5() -> None:
    text = (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert "Days: Mon\N{EN DASH}Fri." in text
    assert DAYS == ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
