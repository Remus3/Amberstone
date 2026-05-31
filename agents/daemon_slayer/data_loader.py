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
    arena_augments_by_id: dict[int, dict]
    arena_augments_by_api: dict[str, dict]
    data_root: Path = field(repr=False)
    # Optional lolmath-wiki stat sidecar (item 221). Maps champ id ->
    # {attack_cast_time, missile_speed, ...}. Default empty dict so an
    # absent wiki_stats.json is byte-identical to pre-sidecar behavior.
    wiki_stats: dict = field(default_factory=dict)
    # Optional CDragon per-spell sidecar (item 225). Maps champ id ->
    # {"spells": {<Q|W|E|R>: {ammo, missile, ...}}}. Default empty dict so an
    # absent cdragon_spell_stats.json is byte-identical to pre-sidecar behavior.
    cdragon_spell_stats: dict = field(default_factory=dict)

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

        def _read_optional(name: str) -> Any | None:
            p = snap_dir / name
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))

        manifest = _read("manifest.json")
        champions_doc = _read("champions.json")
        items_doc = _read("items.json")
        scenarios_doc = _read("scenarios.json")

        # Integrity gate: a vendored file can be valid JSON yet
        # structurally wrong (truncated atomic-write, partial re-extract,
        # upstream schema change). Without this, ``.get("data", {})``
        # below would yield a degenerate ZERO-champion / ZERO-item /
        # ZERO-scenario snapshot silently - every downstream KeyError
        # would then masquerade as "unknown champion" instead of
        # "corrupt snapshot". Fail LOUDLY with the module's defined error
        # (a real 16.10.1 snapshot always has populated containers).
        def _require_nonempty(doc: Any, key: str, fname: str) -> dict:
            container = doc.get(key) if isinstance(doc, dict) else None
            if not isinstance(container, dict) or not container:
                raise SnapshotNotFound(
                    f"Snapshot file {fname} missing/empty {key!r} container "
                    f"(snapshot {patch}) - corrupt or partially written"
                )
            return container

        champions_data = _require_nonempty(
            champions_doc, "data", "champions.json"
        )
        items_data = _require_nonempty(items_doc, "data", "items.json")
        scenarios_by_id = _require_nonempty(
            scenarios_doc, "byDDragonId", "scenarios.json"
        )
        scenarios_by_lolmath = _require_nonempty(
            scenarios_doc, "byLolmathKey", "scenarios.json"
        )

        # arena_augments.json is Phase 6 - older snapshots predate it; tolerate absence.
        augments_doc = _read_optional("arena_augments.json") or {"augments": []}
        augs = augments_doc.get("augments") or []
        augs_by_id = {int(a["id"]): a for a in augs if isinstance(a.get("id"), int)}
        augs_by_api = {a["apiName"]: a for a in augs if a.get("apiName")}

        # wiki_stats.json is the optional lolmath-wiki stat sidecar (item
        # 221). Absent file -> _read_optional returns None -> {}. A present
        # file is {"champions": {<id>: {...}}, ...}; pull the champions map.
        wiki_doc = _read_optional("wiki_stats.json")
        wiki_stats = (
            wiki_doc.get("champions") if isinstance(wiki_doc, dict) else None
        ) or {}

        # cdragon_spell_stats.json is the optional CDragon per-spell sidecar
        # (item 225). Absent -> _read_optional returns None -> {}. A present
        # file is {"champions": {<id>: {"spells": {...}}}, ...}; pull champions.
        spell_doc = _read_optional("cdragon_spell_stats.json")
        cdragon_spell_stats = (
            spell_doc.get("champions") if isinstance(spell_doc, dict) else None
        ) or {}

        return cls(
            patch=patch,
            manifest=manifest,
            champions=champions_data,
            items=items_data,
            scenarios_by_id=scenarios_by_id,
            scenarios_by_lolmath=scenarios_by_lolmath,
            arena_augments_by_id=augs_by_id,
            arena_augments_by_api=augs_by_api,
            data_root=root,
            wiki_stats=wiki_stats,
            cdragon_spell_stats=cdragon_spell_stats,
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

    def wiki_attack_cast_time(self, champ_id: str) -> float | None:
        """Per-champ AA windup (s) from the optional wiki_stats sidecar.

        Returns None when the sidecar is absent, has no entry for the
        champ, or the entry's attack_cast_time is null - the combo clock
        falls back to its fixed default in that case (byte-identical to
        pre-sidecar behavior).
        """
        return self.wiki_stats.get(str(champ_id), {}).get("attack_cast_time")

    def spell_ammo(self, champ_id: str, slot: str) -> dict | None:
        """Per-spell ammo (charge) model from the optional CDragon sidecar.

        Returns the ``{"max": [...], "recharge": [...]}`` dict for the given
        champion + slot (``"Q"`` / ``"W"`` / ``"E"`` / ``"R"``), or None when
        the sidecar is absent, has no entry for the champ/slot, or that spell
        carries no charge model. A None return is the byte-identical fallback
        (the consumer reverts to mana-only gating).
        """
        return (
            self.cdragon_spell_stats.get(str(champ_id), {})
            .get("spells", {})
            .get(str(slot), {})
            .get("ammo")
        )

    def arena_augment(self, key: int | str) -> dict:
        if isinstance(key, int):
            rec = self.arena_augments_by_id.get(key)
        else:
            rec = self.arena_augments_by_api.get(key) or self.arena_augments_by_id.get(int(key)) if str(key).isdigit() else self.arena_augments_by_api.get(key)
        if rec is None:
            raise KeyError(f"Unknown arena augment: {key!r} (snapshot {self.patch})")
        return rec
