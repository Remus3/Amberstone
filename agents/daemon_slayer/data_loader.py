"""Versioned snapshot loader for Daemon Slayer.

Reads `data/daemon_slayer/<patch>/{champions,items,scenarios,manifest}.json`
produced by `tools/daemon_slayer_extract.py`. Pointer file
`data/daemon_slayer/current.txt` selects the active patch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from typing import Any

from .abilities import AbilitiesSnapshot
from .mode_variants import canonical_champions, canonical_items
from .modifier_blocks import classify_modifier_kind

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


def _norm_augment_key(s: Any) -> str:
    """Normalize an Arena augment key for alias lookup: lowercase, keep
    only alphanumerics. "The Brutalizer", "the-brutalizer" and
    " TheBrutalizer! " all collapse to "thebrutalizer".

    This deliberately MIRRORS the existing ``_norm_name`` at
    ``core/augment_external_source.py:445`` (and the same
    ``name.lower().replace(" ", "")`` shape at
    ``coaches/arena_coach.py:264-272``) rather than inventing a third
    convention. It is re-implemented instead of imported because the
    ``agents/daemon_slayer`` package is deliberately standalone and must
    not depend on ``core``.
    """
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def canonical_mode(mode: Any) -> Any:
    """Fold a caller-supplied mode string to the engine's UPPERCASE spelling.

    RM-325: item 244 made the rank-layer mode FILTER case-insensitive
    (``MODE_MAP_ID.get(mode.upper())``) and left every SCORER gating on a
    bare ``mode == "ARAM"``. A lowercase ``mode="aram"`` therefore got an
    ARAM-legal item POOL scored through a non-ARAM multiplier path - and
    with ``apply_mode_modifiers=True`` it fell into the wiki-sidecar
    ``elif`` branch that ``dps.py``'s own comment forbids for ARAM.

    Every public scorer entry point folds its ``mode`` through this ONCE,
    before ``build_champion``, so the whole call tree below it - engine
    stat modifiers, item filters, per-scorer ARAM gates, provenance notes -
    sees one canonical spelling. That is deliberately the shape that cannot
    drift: a new ``mode == "ARAM"`` added anywhere downstream is correct by
    construction, whereas eight scattered ``.upper()`` calls would need a
    ninth added by hand.

    Non-str input (``None``, an enum) passes through UNTOUCHED so this
    cannot invent a mode where the caller supplied none.
    """
    return mode.upper() if isinstance(mode, str) else mode


class SnapshotNotFound(FileNotFoundError):
    """Raised when the requested patch directory is missing."""


def _extract_damage_reduction_pct(
    abilities,
) -> dict[str, dict[str, dict[str, tuple[float, ...]]]]:
    """Pure walk of an AbilitiesSnapshot for per-rank PERCENT damage reduction.

    Returns ``{champ_id: {slot_key: {attribute_label: per_rank_pct_tuple}}}``
    for every defensive ``modifier`` block whose magnitude is a TRUE percent.
    A block qualifies when ``attribute_kind == "modifier"``, the
    ``modifier_blocks`` classifier files it ``defensive_self`` (so PvE /
    target-shred / self-amp blocks are skipped), and its attribute name
    contains "damage reduction" (case-insensitive, to admit Braum's lowercased
    "Damage reduction").

    A single defensive_self block can carry several ``raw_modifiers`` entries -
    a flat sub-component (Amumu E, empty ``units``) or a resist-scaling one
    ("% per 100 AP", "% per 100 bonus health"). Only the FIRST raw_modifier
    whose ``values`` is non-empty AND whose every ``units`` entry equals the
    bare string ``"%"`` is the percent magnitude; the per-100 sub-modifiers
    share a ``"%"`` prefix but are NOT the bare token, so they are excluded.
    The first qualifying raw_modifier wins (one percent magnitude per label).
    """
    out: dict[str, dict[str, dict[str, tuple[float, ...]]]] = {}
    for champ_id, slot_key, form in abilities.iter_forms():
        for b in form.damage_blocks:
            if b.attribute_kind != "modifier":
                continue
            if classify_modifier_kind(b.attribute) != "defensive_self":
                continue
            if "damage reduction" not in b.attribute.lower():
                continue
            for rm in b.raw_modifiers:
                values = rm.get("values")
                units = rm.get("units")
                if not values or not isinstance(units, (list, tuple)):
                    continue
                if not units or any(u != "%" for u in units):
                    continue
                out.setdefault(champ_id, {}).setdefault(slot_key, {})[
                    b.attribute
                ] = tuple(float(v) for v in values)
                break
    return out


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
        # DDragon ships a THROWBACK-MODE registry beside the live one (16.15.1
        # added 60 Jade_<Champion> rows at base_key + 60000 and 162 items in
        # [770000, 780000), most of them flagged map-12 legal). They are
        # partitioned out here rather than at extract time - the snapshot on
        # disk stays a faithful record of the patch. See mode_variants.
        champions_data = canonical_champions(champions_data)
        items_data = canonical_items(
            _require_nonempty(items_doc, "data", "items.json")
        )
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

    def aa_missile_speed(self, champ_id: str) -> float | None:
        """Per-champ AUTO-ATTACK missile speed (units/s) from the wiki sidecar (item 344).

        Returns the basic-attack projectile travel speed for the champ, or None
        when the sidecar is absent / the champ has no entry / the value is a
        non-projectile sentinel. This is a DISTINCT axis from the per-spell
        cdragon ``spell_missile_speed`` (item 233, slot-keyed off
        ``cdragon_spell_stats``): the AA missile speed is CHAMP-keyed off
        ``wiki_stats`` and governs ranged auto-attack hit-delay / kiting windows.
        It was loaded into ``wiki_stats`` alongside ``attack_cast_time`` /
        ``mode_modifiers`` but no accessor ever surfaced it.

        The values are a MIX: a real projectile is ~400-4999 (Caitlyn 2500,
        Jinx 2750), >=5000 is effectively instant / global (Kayle 5000), 0.0 is
        the no-projectile / non-standard-AA sentinel (Azir / Senna / Thresh /
        Velkoz / Zeri), and melee champs carry null. Guard delta from
        ``spell_missile_speed``: same bool / non-numeric reject (a numeric string
        is NOT coerced), PLUS a ``<= 0`` guard so the 0.0 sentinel returns None
        rather than a nonsensical zero-speed projectile (mirrors the item-340
        cone-angle magnitude guard). FORWARD-MARKER: no consumer reads it at
        ship, so live DS output is byte-identical (ENGINE_VERSION does NOT bump).
        """
        ms = self.wiki_stats.get(str(champ_id), {}).get("missile_speed")
        if isinstance(ms, bool) or not isinstance(ms, (int, float)):
            return None
        ms = float(ms)
        if ms <= 0:
            return None
        return ms

    def wiki_attack_total_time(self, champ_id: str) -> float | None:
        """Per-champ TOTAL auto-attack cycle time (s) from the wiki sidecar (item 345).

        Returns the FULL basic-attack cycle duration - windup PLUS recovery, i.e.
        ``1 / attackSpeed`` at base - for the champ, or None when the sidecar is
        absent / the champ has no entry / the value is non-positive. This is a
        DISTINCT axis from ``wiki_attack_cast_time`` (item 221), which is the
        WINDUP-only portion (the point in the cycle the projectile / damage
        commits): the total time governs how OFTEN the auto fires, the cast time
        governs how long each one locks the champ. The two diverge for every
        champ that carries the datum (Jhin total 1.6 vs cast 0.25). It was loaded
        into ``wiki_stats`` alongside ``attack_cast_time`` / ``missile_speed`` /
        ``mode_modifiers`` but no accessor ever surfaced it (only 61 of the 171
        champs carry it - a coverage subset, not a melee/ranged split).

        Guard mirrors ``aa_missile_speed`` (item 344): reject bool / non-numeric
        (a numeric STRING is NOT coerced -> None) and a ``<= 0`` reject so a
        non-positive sentinel returns None rather than a nonsensical zero-length
        attack cycle (defensive - the live 16.11.1 data carries no non-positive
        value). FORWARD-MARKER: no consumer reads it at ship, so live DS output is
        byte-identical (ENGINE_VERSION does NOT bump).
        """
        t = self.wiki_stats.get(str(champ_id), {}).get("attack_total_time")
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            return None
        t = float(t)
        if t <= 0:
            return None
        return t

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

    def spell_sub_missile_speed(self, champ_id: str, slot: str) -> float | None:
        """Per-spell SECONDARY / sibling missile speed (units/s) from the CDragon sidecar (item 339).

        Returns the ``missile_sub_record`` float - the speed of a spell's SECOND
        missile phase (a return boomerang, a recast bolt, a split / follow-up
        projectile) - for the champ + slot, or None when the sidecar is absent /
        the spell carries no sibling missile. This is a DISTINCT axis from the
        item-233 ``spell_missile_speed`` (the resolved PRIMARY): the extractor
        surfaces ``missile_sub_record`` as the best sibling ``<Ability>/...Missile``
        record speed, but the resolver only ever consumed it as a
        placeholder-fallback to FILL the primary, so the sibling's own speed was
        structurally discarded. At patch 16.11.1, 91 spells carry a numeric value
        and 52 of those differ from their primary (e.g. Caitlyn R primary 1500 vs
        return 3200, Jinx W 1200 vs 3300). FORWARD-MARKER: no consumer reads it at
        ship, so live DS output is byte-identical (ENGINE_VERSION does NOT bump).
        Same bool / non-numeric guard as ``spell_missile_speed`` (a numeric string
        is NOT coerced - returns None - matching the primary accessor).
        """
        ms = (
            self.cdragon_spell_stats.get(str(champ_id), {})
            .get("spells", {})
            .get(str(slot), {})
            .get("missile_sub_record")
        )
        if isinstance(ms, bool) or not isinstance(ms, (int, float)):
            return None
        return float(ms)

    def spell_cc_tags(self, champ_id: str, slot: str) -> frozenset[str]:
        """Per-spell CC trait tags from the optional CDragon sidecar (item 343).

        Returns a ``frozenset`` of CDragon CC trait strings for the champ + slot
        (``"Q"`` / ``"W"`` / ``"E"`` / ``"R"``) - a MACHINE-VERIFIED hard-CC class
        flag pulled straight from the spell's CDragon bin, the direct sidecar
        complement to the hand-authored ``_per_spell_cc`` registry. Two trait
        strings appear at patch 16.11.1: ``"Trait_ImmobilizingCCSpell"`` (174
        spells - stun / root / knockup / suppress, e.g. Lux Q, Morgana Q, Leona E)
        and ``"Trait_SwapsIntoImmobilizingCCSpell"`` (12 spells - a form / charge
        that becomes immobilizing, e.g. Aphelios Q, Gnar W, Ornn R). The list was
        loaded into ``cdragon_spell_stats`` alongside ``ammo`` / ``geometry`` /
        ``missile_speed`` for every spell, but no accessor ever surfaced it.

        Returns an EMPTY frozenset (never None, never raises) when the sidecar is
        absent, has no entry for the champ / slot, or the spell carries no CC tag
        (slow-only / damage-only spells). The empty-set fallback is the deliberate
        delta from the float|None sibling accessors: a CC-tag query is a membership
        test, and an empty list and an absent record both mean "no CC tag", so
        collapsing both to ``frozenset()`` removes the None-vs-empty sentinel
        ambiguity - a caller writes ``"Trait_ImmobilizingCCSpell" in
        snap.spell_cc_tags(champ, slot)`` directly. A bare string is NOT treated as
        an iterable of chars, and non-string elements are filtered.

        FORWARD-MARKER: nothing reads it at ship, so live DS output is
        byte-identical (mirrors the item-233 / 339 sibling accessors reading the
        already-loaded sidecar; no data duplication, patch-refresh-safe) and
        ENGINE_VERSION does NOT bump.
        """
        tags = (
            self.cdragon_spell_stats.get(str(champ_id), {})
            .get("spells", {})
            .get(str(slot), {})
            .get("cc_tags")
        )
        if not isinstance(tags, (list, tuple)):
            return frozenset()
        return frozenset(t for t in tags if isinstance(t, str))

    def spell_damage_reduction_pct(
        self, champ_id: str, slot: str
    ) -> dict[str, tuple[float, ...]] | None:
        """Per-rank PERCENT damage-reduction magnitude from the ability modifier blocks (forward marker).

        Returns ``{attribute_label: per_rank_pct_tuple}`` for the champ + slot
        (``"Q"`` / ``"W"`` / ``"E"`` / ``"R"``) - the percent damage taken-
        reduction a defensive self-buff grants, surfaced as a first-class axis
        from the ``champion_abilities.json`` ``modifier`` blocks the
        ``modifier_blocks`` taxonomy already classifies ``defensive_self`` but
        that no accessor ever exposed numerically. A multi-label form returns
        every label: Galio W carries both ``"Magic Damage Reduction"`` and
        ``"Physical Damage Reduction"``.

        The pure-% filter is deliberate. A defensive_self "damage reduction"
        block frequently bundles a flat sub-component (Amumu E, empty ``units``)
        or a resist-scaling one ("% per 100 AP", "% per 100 bonus health")
        alongside (or instead of) the flat-percent value. Only a raw_modifier
        whose every ``units`` token is the bare ``"%"`` is a true percent
        reduction, so flat-only blocks (Amumu E, Leona W) and per-stat scaling
        sub-modifiers are excluded - the latter share a ``"%"`` prefix but never
        the bare token. The first qualifying raw_modifier per block supplies the
        magnitude.

        Returns None when the champ / slot has no pure-% damage-reduction block,
        the champ id is unknown, or the abilities snapshot is absent for this
        patch (older snapshots predate ``champion_abilities.json`` - returning {}
        from the builder then None keeps live output byte-identical).

        FORWARD-MARKER: nothing reads it at ship, so live DS output is
        byte-identical and ENGINE_VERSION does NOT bump (mirrors the item-339 /
        343 sibling forward-marker accessors). The map is built once on first
        call (lazy, the snapshot is ``frozen=True`` so it is stashed via
        ``object.__setattr__``) and reused.
        """
        if not hasattr(self, "_dr_pct_map"):
            object.__setattr__(
                self, "_dr_pct_map", self._build_damage_reduction_pct_map()
            )
        return self._dr_pct_map.get(str(champ_id), {}).get(str(slot))

    def _build_damage_reduction_pct_map(
        self,
    ) -> dict[str, dict[str, dict[str, tuple[float, ...]]]]:
        # Gate purely on file existence so an older snapshot without
        # champion_abilities.json yields {} (byte-identical) rather than raising
        # from AbilitiesSnapshot.load - no broad except masking a real parse bug.
        abil_path = Path(self.data_root) / self.patch / "champion_abilities.json"
        if not abil_path.exists():
            return {}
        abilities = AbilitiesSnapshot.load(patch=self.patch, data_root=self.data_root)
        return _extract_damage_reduction_pct(abilities)

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

    def _arena_augment_alias_index(self) -> dict[str, dict]:
        """RM-331: lazily built alnum-lowercase alias -> augment record.

        Built on first use and cached on the instance (frozen dataclass,
        so the write goes through ``object.__setattr__``). Lazy rather
        than a constructor field on purpose: every ``DataSnapshot``
        instance gets the index however it was constructed, including
        the direct ``DataSnapshot(...)`` calls in tests and tools that
        never go through ``load()``.

        TIE-BREAK, stated explicitly: ``apiName`` WINS. Pass 1 claims
        every normalized ``apiName``; pass 2 fills only keys pass 1 left
        free, so a display name can never shadow a different augment's
        apiName. Within a pass the FIRST row in snapshot order wins,
        matching the ``setdefault`` convention of ``_norm_name`` /
        ``_name_index`` in ``core/augment_external_source.py``.

        CENSUS (measured 2026-09-03 over all 6 shipped snapshots,
        16.10.1 through 16.15.1, 220-227 rows each): ZERO normalized
        apiName collisions, ZERO normalized name collisions, and ZERO
        cross collisions where a display name lands on another
        augment's apiName. The pass ordering above is therefore a
        forward-looking guarantee, not a fix for existing data, and
        ``test_arena_augment_name_alias_rm331.py`` guards it staying so.
        """
        cached = self.__dict__.get("_arena_augment_aliases")
        if cached is not None:
            return cached
        index: dict[str, dict] = {}
        # Pass 1: apiName is authoritative.
        for rec in self.arena_augments_by_api.values():
            alias = _norm_augment_key(rec.get("apiName"))
            if alias:
                index.setdefault(alias, rec)
        # Pass 2: display names fill only what pass 1 left unclaimed.
        # Iterate both indexes so a row carrying a name but no apiName
        # (present in by_id only) is still reachable.
        for rec in chain(
            self.arena_augments_by_id.values(), self.arena_augments_by_api.values()
        ):
            alias = _norm_augment_key(rec.get("name"))
            if alias:
                index.setdefault(alias, rec)
        object.__setattr__(self, "_arena_augment_aliases", index)
        return index

    def arena_augment(self, key: int | str) -> dict:
        """Resolve an Arena augment by numeric id, ``apiName`` or display
        ``name``.

        Resolution order, most-specific first: exact ``apiName``, then
        the numeric id (int, or an all-digit string), then the RM-331
        alnum-lowercase alias index over ``apiName`` AND ``name``. An
        unrecognized key still raises ``KeyError`` - the alias index is
        an exact match on a normalized key, NOT a fuzzy matcher, so the
        documented "unregistered augment is a no-op" contract is
        unchanged.
        """
        if isinstance(key, int):
            rec = self.arena_augments_by_id.get(key)
        else:
            text = str(key)
            rec = self.arena_augments_by_api.get(text)
            if rec is None and text.isdigit():
                rec = self.arena_augments_by_id.get(int(text))
            if rec is None:
                # RM-331: a DISPLAY name ("The Brutalizer") used to miss
                # here and be swallowed by augments.py's `except
                # (KeyError, AttributeError): continue`, scoring
                # byte-identically to passing no augment at all.
                rec = self._arena_augment_alias_index().get(_norm_augment_key(text))
        if rec is None:
            raise KeyError(f"Unknown arena augment: {key!r} (snapshot {self.patch})")
        return rec
