"""docs/faculty-mapping-even-2025-26.md is generated from the EVEN instance, never by hand."""

from __future__ import annotations

from ingestion.emit_v2 import build
from ingestion.faculty_mapping import DEFAULT_DOC, render


def test_committed_mapping_is_current() -> None:
    text = render(build())
    assert DEFAULT_DOC.read_text(encoding="utf-8") == text, (
        "stale: run `python -m ingestion.faculty_mapping`"
    )
    # Every manual resolution names its decision.
    manual = [line for line in text.splitlines() if "| manual (" in line]
    assert len(manual) == 9  # SRD (D25) and the eight D38 initials
    assert all(line.split(" | ")[7] in ("D25", "D38") for line in manual)
