"""Phase 4a (s177, 2026-05-12) - champion ability data loader.

Reads the versioned ``champion_abilities.json`` snapshot produced by
``tools/daemon_slayer_abilities_extract.py`` and exposes typed dataclasses
for downstream consumers. Phase 4a is data-ingest only - formula evaluation
ships in Phase 4b's ``ability_dps.py``.

The loader mirrors ``ult_rates.py``'s lazy-singleton pattern: ``load()``
caches per patch label, ``get_abilities(champion_id)`` returns a list of
``AbilityForm`` records ordered ``P, Q, W, E, R``, and ``get_ability()``
indexes a specific form within a key. Champion IDs are DDragon-style
(``Aatrox``, ``MonkeyKing``, ``KSante``) matching the bulk Meraki top-level
keys.

Snapshot layout::

    data/daemon_slayer/<patch>/champion_abilities.json
        {
          "version": "16.9.1",
          "fetched_at": "...",
          "source": "https://cdn.merakianalytics.com/.../champions.json",
          "engine_phase": "4a",
          "count": 171,
          "coverage": { "total_forms": 927, "ok_rate": 0.984, ... },
          "data": {
            "Aatrox": {
              "Q": [ { "key": "Q", "name": "The Darkin Blade", "cooldown": [...],
                       "damage_blocks": [ { "attribute": "First Cast Damage",
                                            "base": [10, 25, 40, 55, 70],
                                            "total_ad_pct": [60, 67.5, 75, 82.5, 90],
                                            ... }, ... ], ... } ],
              ...
            },
            ...
          }
        }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from ._ability_overrides import DAMAGE_TYPE_OVERRIDES, NON_DAMAGE_BLOCKS
from ._passive_damage_overrides import _PASSIVE_DAMAGE_OVERRIDES, to_damage_block
from ._passive_heal_overrides import _PASSIVE_HEAL_OVERRIDES, to_heal_block

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# Ability keys in canonical order - match Meraki schema.
_KEY_ORDER: tuple[str, ...] = ("P", "Q", "W", "E", "R")

# Damage scaling field names (Phase 4b's evaluator walks these).
_SCALING_FIELDS: tuple[str, ...] = (
    "base",
    "total_ad_pct",
    "bonus_ad_pct",
    "ap_pct",
    "caster_max_hp_pct",
    "caster_bonus_hp_pct",
    "target_max_hp_pct",
    "target_missing_hp_pct",
    "target_current_hp_pct",
    "target_bonus_hp_pct",
    "target_armor_pct",
    "bonus_armor_pct",
    "bonus_mr_pct",
    "caster_max_mp_pct",
    "caster_armor_pct",
    "caster_bonus_mp_pct",
    "caster_bonus_ms_pct",
)


class AbilitiesNotFound(FileNotFoundError):
    """Raised when the requested abilities snapshot is missing."""


@dataclass(frozen=True)
class DamageBlock:
    """One leveling sub-component of an ability - e.g. Aatrox Q "First Cast
    Damage" with per-rank base + AD scaling.

    ``attribute_kind`` is one of ``"damage"`` / ``"heal"`` / ``"shield"`` /
    ``"slow"`` / ``"duration"`` / ``"modifier"`` / ``"other"``. Phase 4b only
    evaluates ``"damage"`` blocks; the others are preserved for future
    scorer expansion (Phase 6 enchanter HPS will consume ``"heal"`` /
    ``"shield"``).

    Per-rank scaling fields (``base``, ``total_ad_pct``, etc.) are lists of
    floats; length is either the ability's rank count (5 for normal abilities,
    3 for ults, 1-4 for passives or Nidalee cougar form) or a single
    value when the scaling is constant across ranks. Phase 4b's evaluator
    treats a 1-element list as that value at every rank.
    """

    attribute: str
    attribute_kind: str
    base: tuple[float, ...] | None = None
    total_ad_pct: tuple[float, ...] | None = None
    bonus_ad_pct: tuple[float, ...] | None = None
    ap_pct: tuple[float, ...] | None = None
    caster_max_hp_pct: tuple[float, ...] | None = None
    caster_bonus_hp_pct: tuple[float, ...] | None = None
    target_max_hp_pct: tuple[float, ...] | None = None
    target_missing_hp_pct: tuple[float, ...] | None = None
    target_current_hp_pct: tuple[float, ...] | None = None
    target_bonus_hp_pct: tuple[float, ...] | None = None
    target_armor_pct: tuple[float, ...] | None = None
    bonus_armor_pct: tuple[float, ...] | None = None
    bonus_mr_pct: tuple[float, ...] | None = None
    caster_max_mp_pct: tuple[float, ...] | None = None
    caster_armor_pct: tuple[float, ...] | None = None
    caster_bonus_mp_pct: tuple[float, ...] | None = None
    caster_bonus_ms_pct: tuple[float, ...] | None = None
    unparsed_modifiers: tuple[dict, ...] = field(default_factory=tuple)
    raw_modifiers: tuple[dict, ...] = field(default_factory=tuple)
    # Bilinear product terms (item 248 schema lift): each
    # ``(factor, ctx_attr_a, ctx_attr_b)`` contributes
    # ``factor * ctx[attr_a] * ctx[attr_b]`` in ``ability_dps._evaluate_block``
    # - the one damage form a single linear ``_SCALING_TARGETS`` field cannot
    # express (a PRODUCT of two ctx stats, e.g. Gwen P "0.55% per 100 AP of
    # target max HP" = AP * target_max_hp). The factor is flat (NOT per-rank):
    # the bilinear AP-on-HP coefficient is level-flat by Riot convention.
    # Synthetic-only (built by ``_passive_damage_overrides.to_damage_block``);
    # no live snapshot carries this key so ``from_dict`` does not parse it.
    bilinear_terms: tuple[tuple[float, str, str], ...] = ()

    @classmethod
    def from_dict(cls, payload: dict) -> "DamageBlock":
        kwargs: dict[str, Any] = {
            "attribute": payload.get("attribute") or "",
            "attribute_kind": payload.get("attribute_kind") or "other",
        }
        for f in _SCALING_FIELDS:
            v = payload.get(f)
            if isinstance(v, list):
                kwargs[f] = tuple(float(x) for x in v)
        if payload.get("unparsed_modifiers"):
            kwargs["unparsed_modifiers"] = tuple(payload["unparsed_modifiers"])
        if payload.get("raw_modifiers"):
            kwargs["raw_modifiers"] = tuple(payload["raw_modifiers"])
        return cls(**kwargs)

    def has_damage_scaling(self) -> bool:
        """True when at least one scaling field (or a bilinear term) is set."""
        return any(getattr(self, f) is not None for f in _SCALING_FIELDS) or bool(
            self.bilinear_terms
        )

    def value_at(self, field_name: str, rank: int) -> float:
        """Return the scaling value for ``field_name`` at 0-indexed ``rank``.

        Lists shorter than ``rank+1`` are clamped to the last element (so a
        1-element list returns that value for every rank). Missing fields
        return 0.0 - Phase 4b can sum across fields without None-guards.
        """
        vals = getattr(self, field_name, None)
        if vals is None:
            return 0.0
        if not vals:
            return 0.0
        if rank < 0:
            rank = 0
        if rank >= len(vals):
            return float(vals[-1])
        return float(vals[rank])


@dataclass(frozen=True)
class AbilityForm:
    """One stance / variant of one ability key for one champion.

    Most abilities ship a single form per key. Exceptions: Aphelios weapon
    stances (6 forms per P/Q), Jayce/Elise/Karma/LeeSin/Nidalee/Sylas
    transformations (2 forms per affected key), Sylas E re-target (2 forms).

    Cooldown / cost are per-rank lists or ``None``. Damage type is
    ``"PHYSICAL"`` / ``"MAGIC"`` / ``"TRUE"`` / ``"MIXED"`` / ``None``.
    """

    key: str
    name: str
    form_index: int
    icon: str | None
    cooldown: tuple[float, ...] | None
    cost: tuple[float, ...] | None
    damage_type: str | None
    targeting: str | None
    affects: str | None
    resource: str | None
    is_aoe: bool
    damage_blocks: tuple[DamageBlock, ...]
    raw_effects_count: int
    raw_leveling_count: int
    parse_status: str
    parse_notes: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict) -> "AbilityForm":
        def _opt_tuple(v: Any) -> tuple[float, ...] | None:
            if not isinstance(v, list):
                return None
            return tuple(float(x) for x in v)

        return cls(
            key=payload.get("key") or "",
            name=payload.get("name") or "",
            form_index=int(payload.get("form_index") or 0),
            icon=payload.get("icon"),
            cooldown=_opt_tuple(payload.get("cooldown")),
            cost=_opt_tuple(payload.get("cost")),
            damage_type=payload.get("damage_type"),
            targeting=payload.get("targeting"),
            affects=payload.get("affects"),
            resource=payload.get("resource"),
            is_aoe=bool(payload.get("is_aoe")),
            damage_blocks=tuple(
                DamageBlock.from_dict(b) for b in (payload.get("damage_blocks") or [])
            ),
            raw_effects_count=int(payload.get("raw_effects_count") or 0),
            raw_leveling_count=int(payload.get("raw_leveling_count") or 0),
            parse_status=payload.get("parse_status") or "unparsed",
            parse_notes=tuple(payload.get("parse_notes") or ()),
        )

    def damage_blocks_only(self) -> tuple[DamageBlock, ...]:
        """Return only the ``attribute_kind == "damage"`` blocks."""
        return tuple(b for b in self.damage_blocks if b.attribute_kind == "damage")


def _apply_ability_overrides(cid: str, key: str, form: AbilityForm) -> AbilityForm:
    """Apply the item-238 null-damage-type corrections at load time.

    Returns ``form`` unchanged when no override is registered for
    ``(cid, key, form.form_index)``. Otherwise returns a copy with the
    corrected ``damage_type`` (mis-mitigated null-type abilities) and/or with
    phantom self-buff / shield blocks re-labeled ``attribute_kind="other"`` so
    no damage consumer sums them. See ``_ability_overrides`` for the registry.
    """
    k = (cid, key, form.form_index)
    new_dtype = DAMAGE_TYPE_OVERRIDES.get(k)
    drop_attrs = NON_DAMAGE_BLOCKS.get(k)
    if not new_dtype and not drop_attrs:
        return form
    changes: dict[str, Any] = {}
    if new_dtype:
        changes["damage_type"] = new_dtype
    if drop_attrs:
        changes["damage_blocks"] = tuple(
            replace(b, attribute_kind="other")
            if (b.attribute_kind == "damage" and b.attribute in drop_attrs)
            else b
            for b in form.damage_blocks
        )
    return replace(form, **changes)


def _apply_passive_damage_overrides(cid: str, key: str, form: AbilityForm) -> AbilityForm:
    """Inject the GAP-2 effects-text-only passive damage block at load time.

    OPT-IN: this runs only when ``AbilitiesSnapshot.load`` is called with
    ``apply_passive_damage=True``. When it runs, it appends a synthetic
    ``attribute_kind="damage"`` block to a form ONLY when:
      * the form has ``parse_status == "no_damage"`` (the Meraki pipeline
        could not structure a damage block), AND
      * ``(cid, key, form.form_index)`` has a registered
        ``PassiveDamageEntry``.

    The synthetic block routes through the existing
    ``ability_dps._evaluate_block`` / ``_select_blocks`` machinery with zero
    new math. ``form.damage_type`` is set from the entry ONLY when the form's
    current type is null (the seeded P forms already carry a sensible
    ``damage_type`` - Lux MAGIC, Qiyana PHYSICAL, Vel'Koz TRUE - so this
    almost never fires; it is a safety net for a future entry on a null-type
    form). Returns ``form`` unchanged when the gate is not met.

    See ``_passive_damage_overrides`` for the registry + the staged-candidate
    list. The default (flag OFF) path never calls this, so forms are
    byte-identical to the no-override behavior.
    """
    if form.parse_status != "no_damage":
        return form
    entry = _PASSIVE_DAMAGE_OVERRIDES.get((cid, key, form.form_index))
    if entry is None:
        return form
    changes: dict[str, Any] = {
        "damage_blocks": form.damage_blocks + (to_damage_block(entry),),
    }
    if not form.damage_type:
        changes["damage_type"] = entry.damage_type
    return replace(form, **changes)


def _apply_passive_heal_overrides(cid: str, key: str, form: AbilityForm) -> AbilityForm:
    """Inject the GAP-2 effects-text-only HEAL block at load time.

    OPT-IN: runs only when ``AbilitiesSnapshot.load`` is called with
    ``apply_passive_heal=True``. Appends a synthetic ``attribute_kind="heal"``
    block to a form ONLY when:
      * the form has NO existing ``attribute_kind == "heal"`` block (so a
        snapshot heal is never double-counted), AND
      * ``(cid, key, form.form_index)`` has a registered ``PassiveHealEntry``.

    The synthetic heal block routes through the existing
    ``ability_hps._select_kind_blocks`` / ``_eval_heal_shield_block`` machinery
    (raw_modifiers for the linear %-of-HP terms + bilinear_terms for the
    products). Returns ``form`` unchanged when the gate is not met. The default
    (flag OFF) path never calls this, so forms are byte-identical to the
    no-override behavior. See ``_passive_heal_overrides`` for the registry +
    the exhaustive scan / documented exclusions.
    """
    if any(b.attribute_kind == "heal" for b in form.damage_blocks):
        return form
    entry = _PASSIVE_HEAL_OVERRIDES.get((cid, key, form.form_index))
    if entry is None:
        return form
    return replace(
        form, damage_blocks=form.damage_blocks + (to_heal_block(entry),),
    )


@dataclass(frozen=True)
class AbilitiesSnapshot:
    """Versioned snapshot of all champion ability records.

    Construct via :meth:`load`. Backed by
    ``data/daemon_slayer/<patch>/champion_abilities.json``.
    """

    patch: str
    fetched_at: str
    source: str
    coverage: dict
    champions: dict[str, dict[str, tuple[AbilityForm, ...]]]
    data_root: Path = field(repr=False, default=_DEFAULT_DATA_ROOT)

    @classmethod
    def load(
        cls,
        patch: str | None = None,
        data_root: Path | None = None,
        apply_passive_damage: bool = False,
        apply_passive_heal: bool = False,
    ) -> "AbilitiesSnapshot":
        """Load the abilities snapshot for ``patch`` (or current.txt).

        ``apply_passive_damage`` (GAP 2, default False / OFF) is opt-in. When
        True, ``_apply_passive_damage_overrides`` appends a synthetic damage
        block to each seeded ``parse_status == "no_damage"`` P-slot passive
        (Ziggs Short Fuse, Lux Illumination, etc.) so its effects-text-only
        damage formula scores through the existing evaluator. When False (the
        default) NO synthetic block is appended and forms are byte-identical
        to the no-override behavior - the full DS suite passes unchanged.
        The item-238 ``_apply_ability_overrides`` step runs first + always.

        ``apply_passive_heal`` (GAP 2, default False / OFF) is the HEAL sibling:
        when True, ``_apply_passive_heal_overrides`` appends a synthetic
        ``attribute_kind="heal"`` block to each registered form that has NO
        existing heal block (Viego P / Karma W f1 / Kayn R - effects-text-only
        bilinear self-heals) so ``compute_ability_hps`` can score them under
        ``resolve_target_relative``. Default OFF = byte-identical.
        """
        root = Path(data_root) if data_root else _DEFAULT_DATA_ROOT
        if patch is None:
            pointer = root / "current.txt"
            if not pointer.exists():
                raise AbilitiesNotFound(f"Pointer file missing: {pointer}")
            patch = pointer.read_text(encoding="utf-8").strip()
            if not patch:
                raise AbilitiesNotFound(f"Pointer file empty: {pointer}")

        path = root / patch / "champion_abilities.json"
        if not path.exists():
            raise AbilitiesNotFound(f"Abilities snapshot missing: {path}")

        doc = json.loads(path.read_text(encoding="utf-8"))
        # Integrity gate (mirrors data_loader): valid JSON with a
        # missing/empty 'data' container is a corrupt or partially
        # written snapshot, not a champion-less game. Fail LOUDLY rather
        # than returning a zero-champion AbilitiesSnapshot that would
        # surface downstream as spurious "unknown champion" KeyErrors.
        data_block = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(data_block, dict) or not data_block:
            raise AbilitiesNotFound(
                f"Abilities snapshot {path} missing/empty 'data' container "
                f"(snapshot {patch}) - corrupt or partially written"
            )
        champions: dict[str, dict[str, tuple[AbilityForm, ...]]] = {}
        for cid, keymap in data_block.items():
            if not isinstance(keymap, dict):
                continue
            per_key: dict[str, tuple[AbilityForm, ...]] = {}
            for key in _KEY_ORDER:
                forms = keymap.get(key) or []
                built: list[AbilityForm] = []
                for f in forms:
                    if not isinstance(f, dict):
                        continue
                    # item 238 null-damage-type corrections run FIRST + always.
                    fm = _apply_ability_overrides(cid, key, AbilityForm.from_dict(f))
                    # GAP 2 effects-text-only passive damage: opt-in, default OFF.
                    if apply_passive_damage:
                        fm = _apply_passive_damage_overrides(cid, key, fm)
                    # GAP 2 effects-text-only HEAL: opt-in, default OFF.
                    if apply_passive_heal:
                        fm = _apply_passive_heal_overrides(cid, key, fm)
                    built.append(fm)
                per_key[key] = tuple(built)
            champions[cid] = per_key
        return cls(
            patch=patch,
            fetched_at=doc.get("fetched_at") or "",
            source=doc.get("source") or "",
            coverage=doc.get("coverage") or {},
            champions=champions,
            data_root=root,
        )

    def champion_ids(self) -> tuple[str, ...]:
        """Return all champion IDs in the snapshot, sorted."""
        return tuple(sorted(self.champions.keys()))

    def has_champion(self, champion_id: str) -> bool:
        return champion_id in self.champions

    def get_abilities(self, champion_id: str) -> dict[str, tuple[AbilityForm, ...]]:
        """Return ``{key: (form, ...), ...}`` for the champion.

        Raises ``KeyError`` when the champion is not in the snapshot. Keys
        always include P/Q/W/E/R (empty tuple if the champion has no entry
        for that key - common for passives that Meraki ships as utility).
        """
        if champion_id not in self.champions:
            raise KeyError(
                f"Unknown champion id: {champion_id!r} (abilities snapshot {self.patch})"
            )
        return self.champions[champion_id]

    def get_ability(
        self, champion_id: str, key: str, form_index: int = 0
    ) -> AbilityForm:
        """Return the specific ability form for ``key`` (``P/Q/W/E/R``).

        Raises ``KeyError`` if the champion / key / form_index doesn't exist.
        """
        per_key = self.get_abilities(champion_id)
        if key not in per_key:
            raise KeyError(
                f"Unknown ability key: {key!r} for {champion_id!r} "
                f"(expected one of {_KEY_ORDER})"
            )
        forms = per_key[key]
        if not forms:
            raise KeyError(
                f"No {key!r} ability recorded for {champion_id!r} "
                f"(abilities snapshot {self.patch})"
            )
        if form_index < 0 or form_index >= len(forms):
            raise KeyError(
                f"form_index {form_index} out of range for {champion_id!r}.{key} "
                f"({len(forms)} form(s) available)"
            )
        return forms[form_index]

    def iter_forms(self) -> Iterable[tuple[str, str, AbilityForm]]:
        """Yield ``(champion_id, key, form)`` for every form in the snapshot."""
        for cid in sorted(self.champions.keys()):
            per_key = self.champions[cid]
            for key in _KEY_ORDER:
                for form in per_key.get(key, ()):
                    yield cid, key, form

    def parse_status_counts(self) -> dict[str, int]:
        """Return per-status counts across all forms (matches coverage['status_counts'])."""
        counts: dict[str, int] = {"ok": 0, "partial": 0, "unparsed": 0, "no_damage": 0}
        for _cid, _key, form in self.iter_forms():
            status = form.parse_status
            counts[status] = counts.get(status, 0) + 1
        return counts


# ─── Singleton-style helpers (mirrors ult_rates.py pattern) ──────────────────

_cache: AbilitiesSnapshot | None = None


def load_default() -> AbilitiesSnapshot:
    """Load the current-patch snapshot, caching the result process-wide.

    Equivalent to ``AbilitiesSnapshot.load()`` plus a module-level cache so
    Phase 4b's evaluator can call ``get_ability`` thousands of times per
    coach tick without re-reading disk.
    """
    global _cache
    if _cache is None:
        _cache = AbilitiesSnapshot.load()
    return _cache


def reset_default_cache() -> None:
    """Drop the cached snapshot so the next ``load_default`` reads disk again.

    Test fixtures call this between patches when redirecting ``data_root``.
    """
    global _cache
    _cache = None
