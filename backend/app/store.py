"""Data access (S13a): instance files committed under ``data/instances/<id>/``.

Each instance directory holds ``edge_list.json`` (edge_list_v1, S9 export) and may hold
``display.json`` (D41 sidecar), ``anomalies.json`` and ``solution.json`` (solution.v2).
shortcut: reads committed files, not the database (S13 did not move them; users, the audit
log and jobs are in the database); move these reads there before instances change at run time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
INSTANCES_DIR = REPO / "data" / "instances"


class InstanceStore:
    def __init__(self, root: Path = INSTANCES_DIR) -> None:
        self.root = root

    def ids(self) -> list[str]:
        """Every directory with an ``edge_list.json``, sorted."""
        return sorted(p.name for p in self.root.iterdir() if (p / "edge_list.json").is_file())

    def path(self, instance_id: str, name: str) -> Path | None:
        """The instance's ``<name>.json``; None when the instance or file is absent."""
        if instance_id not in self.ids():  # also keeps the id from naming a path outside root
            return None
        path = self.root / instance_id / f"{name}.json"
        return path if path.is_file() else None

    def read(self, instance_id: str, name: str) -> Any | None:
        """The parsed ``<name>.json`` of an instance; None when the instance or file is absent."""
        path = self.path(instance_id, name)
        return json.loads(path.read_text(encoding="utf-8")) if path else None
