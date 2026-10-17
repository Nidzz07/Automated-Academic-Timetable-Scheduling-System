"""Write docs/faculty-mapping-even-2025-26.md from the EVEN instance (ROADMAP S9).

One row per (initials, person, source): the canonical name (Faculty___Subjects.xlsx
spelling, D45), the legend spellings that are aliases, the divisions the mapping
holds in, the subjects and session types it is used for in the instance, where
it comes from (a division legend, or a manual decision) and the decision id of
each manual resolution (D25, D38). The BE and M.Tech legends are listed too:
their initials name the teachers of the out-of-scope sessions D35 freezes.
Nothing here is typed by hand; a test fails when the committed file is stale.

Run from the repo root::

    python -m ingestion.faculty_mapping
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ingestion.class_tt import EVEN_CLASS_FILE
from ingestion.emit_v2 import Instance, build
from ingestion.initials_legend import extract_legends
from ingestion.lab_tt import division_key
from ingestion.seed_legends import legend_scope
from ingestion.seed_reference import REPO_ROOT

DEFAULT_DOC = REPO_ROOT / "docs" / "faculty-mapping-even-2025-26.md"


def _cell(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def rows(inst: Instance) -> list[list[str]]:
    p = inst.payload
    name = {f["id"]: f["full_name"] for f in p["faculty"]}
    meta = {f["id"]: f for f in inst.faculty_meta}
    label = {d["id"]: d["label"] for d in p["divisions"]}
    subject = {s["id"]: s for s in p["subjects"]}
    ce = inst.sources.ce_faculty

    groups: dict[tuple[str, str, str], list[str | None]] = {}
    for r in p["faculty_initials"]:
        key = (r["initials"], r["faculty_id"], r["source"])
        groups.setdefault(key, []).append(r["division_id"])

    out = []
    for (initials, fid, source), divs in groups.items():
        scoped = {d for d in divs if d}
        sessions = [
            row for row in p["observed_sessions"]
            if row["faculty_id"] == fid and row["faculty_initials_raw"] == initials
            and inst.resolved_by[row["id"]][0] == source
            and inst.resolved_by[row["id"]][1] in divs
        ]
        subjects = list(dict.fromkeys(
            f"{subject[row['subject_id']]['code']} {subject[row['subject_id']]['name']}"
            if subject[row["subject_id"]]["code"] != subject[row["subject_id"]]["name"]
            else subject[row["subject_id"]]["code"] for row in sessions))
        kinds = list(dict.fromkeys(inst.kinds[row["id"]] for row in sessions))
        decision = "-" if source == "legend" else "D25" if initials == "SRD" else "D38"
        out.append([
            initials, name[fid], _cell([a["alias"] for a in meta[fid]["aliases"]]),
            _cell([label[d] for d in divs if d]) if scoped else "no division printed",
            _cell(subjects), _cell(kinds),
            f"{source} ({meta[fid]['source']})", decision, "yes" if name[fid] in ce else "no",
        ])

    # BE and M.Tech legends: the teachers of the D35 blocks read through them.
    fid_of = {f["full_name"]: f["id"] for f in p["faculty"]}
    for legend in extract_legends(EVEN_CLASS_FILE):
        scope = legend_scope(legend)
        if division_key(scope.division):
            continue
        programme = "M.Tech" if scope.programme == "M.Tech" else "BE"
        for entry in legend.entries:
            taught = list(dict.fromkeys(
                ln.subject for blk in inst.sources.blocks if blk.resolution == "D35"
                for ln in blk.lines if ln.initials == entry.initials
                and ln.programme == programme and not ln.id.startswith("oos-fac-")))
            kinds = ["out_of_scope (D35)"] if taught else []
            for person in inst.sources.faculty.by_scope[scope].get(entry.initials, []):
                fid = fid_of[person]
                frozen = [row for row in p["observed_sessions"]
                          if row["faculty_id"] == fid
                          and row["faculty_initials_raw"] == entry.initials
                          and inst.resolved_by.get(row["id"]) == ("legend", programme)]
                out.append([
                    entry.initials, person, _cell([a["alias"] for a in meta[fid]["aliases"]]),
                    scope.division,
                    _cell(taught + [subject[row["subject_id"]]["code"] for row in frozen]),
                    _cell(kinds + (["frozen"] if frozen else [])),
                    f"legend ({meta[fid]['source']})", "-", "yes" if person in ce else "no",
                ])
    return out


def render(inst: Instance) -> str:
    header = ["Initials", "Canonical name", "Aliases (D45)", "Divisions", "Subjects",
              "Session types", "Source", "Decision", "CE faculty (D44)"]
    table = [header, ["---"] * len(header), *rows(inst)]
    mapped = {r[1] for r in table[2:]}
    meta = {f["full_name"]: f for f in inst.faculty_meta}
    rest = [n for n in (f["full_name"] for f in inst.payload["faculty"]) if n not in mapped]
    lines = [
        "# Faculty initials mapping, EVEN 2025-26 (SE, TE)",
        "",
        "Generated by `python -m ingestion.faculty_mapping` from the EVEN instance",
        "(`ingestion.emit_v2`); do not edit by hand. `ingestion/tests/test_faculty_mapping.py`",
        "fails when this file is stale.",
        "",
        "- Canonical name: the Faculty___Subjects.xlsx spelling (D45); people in no",
        "  spreadsheet keep their legend or manual spelling. Aliases are the other",
        "  spellings the EVEN legends (and D25) use.",
        "- Source: `legend` = the division's own initials legend; `manual` = a decision",
        "  (D25 for SRD, D38 for initials missing from their division's legend). The",
        "  bracket gives where the person's row comes from (spreadsheet, legend, manual).",
        "- Subjects and session types: the observed sessions these initials resolve in",
        "  (scheme code and name; electives and other non-scheme items as printed).",
        "  `frozen` = frozen at its slot (D24, D26, D44).",
        "- CE faculty (D44): in Faculty___Subjects.xlsx. Sessions of anyone else are frozen.",
        "",
        *("| " + " | ".join(row) + " |" for row in table),
        "",
        "## Faculty with no initials in any EVEN legend",
        "",
        *(f"- {n} ({meta[n]['source']})" for n in rest),
        *([] if rest else ["- none"]),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_DOC, help="markdown path")
    args = parser.parse_args(argv)
    args.out.write_text(render(build()), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
