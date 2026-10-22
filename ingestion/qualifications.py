"""Write data/instances/even-2025-26/qualifications.json from SPIT's faculty-subject sheets (S14f).

ROADMAP D53: a substitute teacher must be listed for the subject (and lecture or
practical, where the sheet says) in Faculty___Subjects.xlsx and
Subject-wise_faculty.xlsx. This sidecar (not a contract) gives, for each subject of
the instance, the faculty ids those sheets list for it.

- Faculty___Subjects.xlsx is the source; Subject-wise_faculty.xlsx is the cross-check
  (``ingestion.seed_reference.cross_check``): every disagreement on an instance
  subject is listed, never resolved here.
- A sheet code maps to a scheme code only through ``ingestion.class_tt.SUBJECT_ALIASES``
  (``OS`` -> ``CE206``, ``Devop`` -> ``CE308``, ...), the map the class timetable
  already uses. A code with no alias is listed as not in the instance.
- A sheet name maps to a faculty id only by exact equality with the instance's
  ``display.json`` name (D45: the Faculty___Subjects.xlsx spelling is the canonical
  name). Every name that does not match is listed; nothing is guessed.
- ``session_type`` is ``lab`` for a sheet code naming a Lab, ``theory`` for one naming
  Theory, and null where the sheet does not say (either).

Run from the repo root::

    python -m ingestion.qualifications
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from ingestion.class_tt import SUBJECT_ALIASES, subject_key
from ingestion.seed_reference import (
    FACULTY_SUBJECTS_XLSX,
    REPO_ROOT,
    SUBJECT_WISE_XLSX,
    cross_check,
    parse_faculty_subjects,
)

INSTANCE_DIR = REPO_ROOT / "data" / "instances" / "even-2025-26"
DEFAULT_OUT = INSTANCE_DIR / "qualifications.json"

_KIND = ((re.compile(r"\bLab\b", re.IGNORECASE), "lab"),
         (re.compile(r"\bTheory\b", re.IGNORECASE), "theory"))


def session_type(sheet_code: str) -> str | None:
    """``lab`` / ``theory`` when the sheet code says so, else None."""
    return next((kind for pattern, kind in _KIND if pattern.search(sheet_code)), None)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def build(display: dict[str, Any] | None = None) -> dict[str, Any]:
    """The qualifications sidecar for the instance whose ``display.json`` is *display*."""
    if display is None:
        display = json.loads((INSTANCE_DIR / "display.json").read_text(encoding="utf-8"))
    fid_of = {name: fid for fid, name in display["faculty"].items()}
    sid_of = {s["code"]: sid for sid, s in display["subjects"].items()}

    def instance_subject(sheet_code: str) -> str | None:
        return sid_of.get(SUBJECT_ALIASES.get(subject_key(sheet_code), ""))

    sheet = parse_faculty_subjects()
    listed: dict[str, dict[str, str | None]] = {sid: {} for sid in sid_of.values()}
    sheet_codes: dict[str, list[str]] = {sid: [] for sid in sid_of.values()}
    not_in_instance: set[str] = set()
    unmatched: list[dict[str, Any]] = []
    for row in sheet:
        fid = fid_of.get(row.full_name)
        if fid is None:
            unmatched.append({"name": row.full_name, "sheet_codes": list(row.subject_codes)})
        for code in row.subject_codes:
            sid = instance_subject(code)
            if sid is None:
                not_in_instance.add(code)
                continue
            if code not in sheet_codes[sid]:
                sheet_codes[sid].append(code)
            if fid is not None:
                listed[sid][fid] = session_type(code)

    check = cross_check(faculty=sheet)
    disagreements = sorted(
        [{"name": n, "sheet_code": c, "only_in": FACULTY_SUBJECTS_XLSX.name}
         for n, c in check.forward_only if instance_subject(c)]
        + [{"name": n, "sheet_code": c, "only_in": SUBJECT_WISE_XLSX.name}
           for n, c in check.inverted_only if instance_subject(c)],
        key=lambda d: (d["sheet_code"], d["name"], d["only_in"]),
    )

    subjects = {
        sid: {
            "code": display["subjects"][sid]["code"],
            "sheet_codes": sorted(sheet_codes[sid]),
            "faculty": [{"faculty_id": fid, "session_type": listed[sid][fid]}
                        for fid in sorted(listed[sid])],
        }
        for sid in sorted(listed)
    }
    return {
        "note": "D53 sidecar for edge_list.json, not a contract: per subject, the faculty "
                "Faculty___Subjects.xlsx lists for it (session_type null where the sheet does "
                "not say lecture or practical). Chronos suggests; a coordinator decides.",
        "generated_by": "python -m ingestion.qualifications",
        "sources": [_relative(FACULTY_SUBJECTS_XLSX), _relative(SUBJECT_WISE_XLSX),
                    _relative(INSTANCE_DIR / "display.json"),
                    "ingestion.class_tt.SUBJECT_ALIASES"],
        "subjects": subjects,
        "subjects_without_qualified_faculty": [s for s in subjects if not subjects[s]["faculty"]],
        "unmatched_names": unmatched,
        "sheet_codes_not_in_instance": sorted(not_in_instance),
        "cross_check_disagreements": disagreements,
    }


def dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON path")
    args = parser.parse_args(argv)
    data = build()
    args.out.write_text(dumps(data), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}: {len(data['subjects'])} subjects, "
          f"{len(data['subjects_without_qualified_faculty'])} without qualified faculty, "
          f"{len(data['unmatched_names'])} unmatched names")


if __name__ == "__main__":
    main()
