"""Versioned snapshot loader for Daemon Slayer.

Reads `data/daemon_slayer/<patch>/{champions,items,scenarios,manifest}.json`
produced by `tools/daemon_slayer_extract.py`. Pointer file
`data/daemon_slayer/current.txt` selects the active patch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"


class SnapshotNotFound(FileNotFoundError):
    """Raised when the requested patch directory is missing."""


@dataclass(frozen=True)
class DataSnapshot:
    patch: str
    manifest: dict
    champions: dict[str, dict]
    items: dict[str, dict]
    scenarios_by_id: dict[str, list]
    scenarios_by_lolmath: dict[str, list]
    data_root: Path = field(repr=False)

    @classmethod
    def load(cls, patch: str | None = None, data_root: Path | None = None) -> "DataSnapshot":
        root = Path(data_root) if data_root else _DEFAULT_DATA_ROOT
        if patch is None:
            pointer = root / "current.txt"
            if not pointer.exists():
                raise SnapshotNotFound(f"Pointer file missing: {pointer}")
            patch = pointer.read_text(encoding="utf-8").strip()
            if not patch:
                raise SnapshotNotFound(f"Pointer file empty: {pointer}")

        snap_dir = root / patch
        if not snap_dir.is_dir():
            raise SnapshotNotFound(f"Snapshot directory missing: {snap_dir}")

        def _read(name: str) -> Any:
            p = snap_dir / name
            if not p.exists():
                raise SnapshotNotFound(f"Snapshot file missing: {p}")
            return json.loads(p.read_text(encoding="utf-8"))

        manifest = _read("manifest.json")
        champions_doc = _read("champions.json")
        items_doc = _read("items.json")
        scenarios_doc = _read("scenarios.json")

        return cls(
            patch=patch,
            manifest=manifest,
            champions=champions_doc.get("data", {}),
            items=items_doc.get("data", {}),
            scenarios_by_id=scenarios_doc.get("byDDragonId", {}),
            scenarios_by_lolmath=scenarios_doc.get("byLolmathKey", {}),
            data_root=root,
        )

    def champion(self, champ_id: str) -> dict:
        rec = self.champions.get(champ_id)
        if rec is None:
            raise KeyError(f"Unknown champion id: {champ_id!r} (snapshot {self.patch})")
        return rec

    def item(self, item_id: str | int) -> dict:
        key = str(item_id)
        rec = self.items.get(key)
        if rec is None:
            raise KeyError(f"Unknown item id: {item_id!r} (snapshot {self.patch})")
        return rec

    def scenarios(self, champ_id: str) -> list:
        return self.scenarios_by_id.get(champ_id, [])
