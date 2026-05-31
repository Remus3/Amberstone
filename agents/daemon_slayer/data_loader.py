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

# Engine mode string -> wiki_stats.mode_modifiers lowercase key (item 232).
# The wiki overlay keys modes as aram/urf/ofa/usb/nb (MULTIPLIER modes) +
# ar (Arena/CHERRY) / swift (Swiftplay) (ADDEND stat-override modes). The
# engine speaks SR/ARAM/ARENA/BRAWL/URF/etc; this bridges the two.
_WIKI_MODE_ALIASES = {
    "arena": "ar",
    "cherry": "ar",
    "swiftplay": "swift",
    "swift": "swift",
    "aram": "aram",
    "urf": "urf",
    "ofa": "ofa",
    "usb": "usb",
    "nb": "nb",
    "nexusblitz": "nb",
}


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
    # {"spells": {<Q|W|E|R>: {ammo, missile, geometry, ...}}}. Default empty
    # dict so an absent cdragon_spell_stats.json is byte-identical to pre-
    # sidecar behavior.
    cdragon_spell_stats: dict = field(default_factory=dict)
    # Optional wiki per-ability sidecar (item 225/232). Maps the wiki page
    # title "<Champion>/<AbilityName>" -> {recharge_ranks, static, ...}.
    # Default empty dict so an absent wiki_ability_stats.json is byte-identical
    # to pre-sidecar behavior.
    wiki_ability_stats: dict = field(default_factory=dict)

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

        # wiki_ability_stats.json is the optional wiki per-ability overlay
        # (item 225/232). Absent -> None -> {}. Present file is
        # {"abilities": {<Champion/Ability>: {recharge_ranks, static, ...}}};
        # pull the abilities map (keyed by wiki Template:Data page title).
        abil_doc = _read_optional("wiki_ability_stats.json")
        wiki_ability_stats = (
            abil_doc.get("abilities") if isinstance(abil_doc, dict) else None
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
            wiki_ability_stats=wiki_ability_stats,
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

    def spell_geometry(self, champ_id: str, slot: str) -> dict | None:
        """Per-spell cast geometry from the optional CDragon sidecar (item 232).

        Returns the ``{"cast_radius", "cast_radius_conflated", "cone_angle",
        "cone_distance", "line_width"}`` dict for the champ + slot
        (``"Q"``/``"W"``/``"E"``/``"R"``), or None when the sidecar is absent,
        has no entry, or the spell carries no geometry. The shape encodes the
        hit area: a non-null ``line_width`` is a line skillshot, a non-null
        ``cone_distance``/``cone_angle`` is a cone, a non-conflated
        ``cast_radius`` is a circle. ``cast_radius_conflated=True`` flags a
        boilerplate radial value that must not be trusted as a real hit area.
        """
        return (
            self.cdragon_spell_stats.get(str(champ_id), {})
            .get("spells", {})
            .get(str(slot), {})
            .get("geometry")
        )

    def spell_missile_speed(self, champ_id: str, slot: str) -> float | None:
        """Per-spell missile speed (units/s) from the optional CDragon sidecar (item 233).

        Returns the ``missile_speed`` float for the champ + slot, or None when
        the sidecar is absent / the spell has no missile. The values are a MIX:
        a real projectile is ~1000-3000, values below ~400 are dash / melee /
        on-hit artifacts, and very high values (>=5000, incl. a 1e9 instant
        sentinel) are effectively instant / global. The travel-time consumer
        (`missile.spell_travel_time`, geometry-paired) gates on those bands.
        """
        ms = (
            self.cdragon_spell_stats.get(str(champ_id), {})
            .get("spells", {})
            .get(str(slot), {})
            .get("missile_speed")
        )
        if isinstance(ms, bool) or not isinstance(ms, (int, float)):
            return None
        return float(ms)

    def ability_static_cd(self, champ_id: str, ability_name: str) -> str | None:
        """Per-ability static (haste-immune) cooldown from the optional wiki sidecar (item 233).

        The wiki overlay is keyed by ``"<Champion>/<AbilityName>"``. Returns the
        raw ``static`` value (a MIX: a plain number string like ``"3"`` / ``"240"``,
        a toggle marker ``"True"``, or a wiki formula string) or None when absent.
        DATA-STAGED: the live cooldown model carries no ability-haste layer to
        gate against, so this is a reachable cross-source, not yet a behavioral
        consumer (an honest no-consumer per the item 233 brief).
        """
        rec = self.wiki_ability_stats.get(f"{champ_id}/{ability_name}")
        if not isinstance(rec, dict):
            return None
        v = rec.get("static")
        return str(v) if v is not None else None

    def ability_recharge(self, champ_id: str, ability_name: str) -> list | None:
        """Per-ability charge-recharge ranks from the optional wiki sidecar (item 232).

        The wiki ability overlay is keyed by ``"<Champion>/<AbilityName>"``
        (the Template:Data page title). Returns the ``recharge_ranks`` list
        (seconds per charge by rank) or None when absent. Charge-bearing
        abilities (traps/turrets/shrooms/kegs) carry it. The CDragon
        ``spell_ammo`` recharge is the authoritative slot-keyed source; this
        name-keyed bucket is the supplementary wiki cross-source for abilities
        CDragon misses.
        """
        rec = self.wiki_ability_stats.get(f"{champ_id}/{ability_name}")
        if not isinstance(rec, dict):
            return None
        rr = rec.get("recharge_ranks")
        return rr if isinstance(rr, list) and rr else None

    def mode_modifier(self, champ_id: str, mode: str) -> dict | None:
        """Per-champ per-mode balance modifiers from the optional wiki sidecar (item 232).

        Returns the axis dict for the mode (``aram``/``urf``/``ofa``/``usb``/
        ``nb`` carry dmg_dealt/dmg_taken/... MULTIPLIERS; ``ar`` (Arena/CHERRY)
        / ``swift`` (Swiftplay) carry hp_lvl/dam_lvl/... ADDEND stat overrides),
        or None when the sidecar is absent or the champ has no entry for that
        mode. The engine mode string is bridged to the wiki's lowercase key via
        ``_WIKI_MODE_ALIASES`` (ARENA -> ar, etc). ARAM keeps its legacy lolmath
        path in the engine; this accessor is the source for the other modes.
        """
        mm = self.wiki_stats.get(str(champ_id), {}).get("mode_modifiers")
        if not isinstance(mm, dict):
            return None
        wiki_key = _WIKI_MODE_ALIASES.get(str(mode).lower(), str(mode).lower())
        val = mm.get(wiki_key)
        return val if isinstance(val, dict) else None

    def arena_augment(self, key: int | str) -> dict:
        if isinstance(key, int):
            rec = self.arena_augments_by_id.get(key)
        else:
            rec = self.arena_augments_by_api.get(key) or self.arena_augments_by_id.get(int(key)) if str(key).isdigit() else self.arena_augments_by_api.get(key)
        if rec is None:
            raise KeyError(f"Unknown arena augment: {key!r} (snapshot {self.patch})")
        return rec
