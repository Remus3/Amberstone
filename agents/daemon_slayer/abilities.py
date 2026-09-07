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

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ._ability_base_overrides import apply_base_overrides as _apply_base_overrides
from ._ability_overrides import DAMAGE_TYPE_OVERRIDES, NON_DAMAGE_BLOCKS
from ._ability_wiki_damage_registry import (
    inject_missing_champions as _inject_wiki_damage_champions,
)
from ._ability_wiki_form_damage import (
    apply_wiki_form_damage as _apply_wiki_form_damage,
)
from ._passive_damage_overrides import (
    _ALL_OUT_BONUS_OVERRIDES,
    _PASSIVE_DAMAGE_OVERRIDES,
    to_damage_block,
)
from ._passive_heal_overrides import _PASSIVE_HEAL_OVERRIDES, to_heal_block
from ._passive_shield_overrides import _PASSIVE_SHIELD_OVERRIDES, to_shield_block

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

_LOG = logging.getLogger(__name__)

# CDragon mechanical-ratio sidecar (prefer-CDragon re-source, default ON since
# item 320 / ENGINE 1.119.0 - see ``AbilitiesSnapshot.load``).
# Produced by ``tools/daemon_slayer_cdragon_ratio_extract.py`` next to the Meraki
# snapshot: ``data/daemon_slayer/<patch>/cdragon_ability_ratios.json``.
_CDRAGON_RATIO_SIDECAR = "cdragon_ability_ratios.json"

# Scaling fields the CDragon resolver can emit (subset of ``_SCALING_FIELDS``).
# Only these are re-sourced when ``prefer_cdragon_ratios=True``; any field the
# CDragon block left None keeps the Meraki value (per-field fall-back).
_CDRAGON_RATIO_FIELDS: tuple[str, ...] = (
    "base",
    "total_ad_pct",
    "bonus_ad_pct",
    "ap_pct",
    "caster_max_hp_pct",
    "target_max_hp_pct",
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
    # When True, this synthetic HEAL block's ``raw_modifiers`` per-rank
    # ``values`` lists are indexed by champion LEVEL (level-1) rather than the
    # spell rank - for a SPELL-slot (Q/W/E/R) effects-text heal whose magnitude
    # scales "based on level" (Rakan Q / Talon Q): an 18-element per-level tuple
    # indexed by the spell rank (0-4) would mis-read. P-slot heals already see
    # ``rank == rank_at_level("P", level) == level-1`` so they leave this False.
    # Synthetic-only (built by ``_passive_heal_overrides.to_heal_block``); no
    # live snapshot sets it so ``from_dict`` leaves it False (byte-identical).
    level_scaled: bool = False

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


def _apply_all_out_bonus_overrides(cid: str, key: str, form: AbilityForm) -> AbilityForm:
    """Inject the R50 K'Sante All Out Bonus block at load time.

    OPT-IN: runs only when ``AbilitiesSnapshot.load`` is called with
    ``apply_all_out_bonus=True``. Appends a SECOND synthetic
    ``attribute_kind="damage"`` block - the R-empowered All Out Bonus (a
    bilinear caster bonus-resist x target-max-HP term, amortized by its
    All-Out-uptime firing probability) - onto a form that has a registered
    ``_ALL_OUT_BONUS_OVERRIDES`` entry and ``parse_status == "no_damage"``.

    Kept OUT of the base ``_PASSIVE_DAMAGE_OVERRIDES`` seam so the item-255 base
    mark-consume block stays byte-identical (and its prior-entry invariants are
    untouched); a consumer wanting K'Sante's full empowered-in-All-Out damage
    sets BOTH ``apply_passive_damage`` and ``apply_all_out_bonus`` (the two
    blocks then coexist on the P form). Returns ``form`` unchanged when the gate
    is not met; the default (flag OFF) path never calls this, so forms are
    byte-identical to the no-override behavior.
    """
    if form.parse_status != "no_damage":
        return form
    entry = _ALL_OUT_BONUS_OVERRIDES.get((cid, key, form.form_index))
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


def _apply_passive_shield_overrides(cid: str, key: str, form: AbilityForm) -> AbilityForm:
    """Inject the GAP-2 effects-text-only SHIELD block at load time.

    OPT-IN: runs only when ``AbilitiesSnapshot.load`` is called with
    ``apply_passive_shield=True``. Appends a synthetic ``attribute_kind="shield"``
    block to a form ONLY when:
      * the form has NO existing ``attribute_kind == "shield"`` block (so a
        snapshot shield is never double-counted), AND
      * ``(cid, key, form.form_index)`` has a registered ``PassiveShieldEntry``.

    The synthetic shield block routes through the existing
    ``ability_hps._select_kind_blocks`` / ``_eval_heal_shield_block`` machinery
    (the same evaluator that already scores the 56 snapshot shield blocks).
    Adding a shield block never touches the form's damage blocks, so
    ``compute_ability_dps`` is unaffected even with the flag on. Returns ``form``
    unchanged when the gate is not met. The default (flag OFF) path never calls
    this. See ``_passive_shield_overrides`` for the registry + the exhaustive
    scan / documented exclusions.
    """
    if any(b.attribute_kind == "shield" for b in form.damage_blocks):
        return form
    entry = _PASSIVE_SHIELD_OVERRIDES.get((cid, key, form.form_index))
    if entry is None:
        return form
    return replace(
        form, damage_blocks=form.damage_blocks + (to_shield_block(entry),),
    )


def _read_artifact_doc(root: Path, patch: str, artifact: str) -> dict | None:
    """Parse ``<root>/<patch>/<artifact>``; None if absent, unreadable, or not a dict."""
    path = root / patch / artifact
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


def _read_cdragon_sidecar_doc(root: Path, patch: str) -> dict | None:
    """Parse ``<root>/<patch>/cdragon_ability_ratios.json``; None if unusable."""
    return _read_artifact_doc(root, patch, _CDRAGON_RATIO_SIDECAR)


# Patch-marker key spellings actually present under data/daemon_slayer/, in
# PRECEDENCE order. Measured 2026-07-24 across all five shipped dirs (16.10.1
# .. 16.14.1, 87 feed rows):
#
#   patch            cdragon_ability_ratios, cdragon_ratio_drift, pickban_targets
#   _patch           ability_staleness, cdragon_spell_stats, wiki_ability_stats,
#                    wiki_stats
#   rc_patch         the two authored event-mode augment feeds
#                    (tools/ds_feed_index.KNOWN_STAMP_LAG names them; that
#                    registry is the one place the pair is spelled out, rather
#                    than a second copy of the filenames here)
#   ddragon_version  manifest
#   version          items, champions, scenarios, champion_abilities,
#                    build_orders_{sr,aram,arena}
#
# ``patch`` is canonical - it is what the RM-81 reference guard
# (``cdragon_sidecar_patch``) reads and what every NEW stamp must use. The rest
# are pre-existing divergence: they are READ tolerantly so the guard works on
# artifacts that already carry a marker, and are never re-spelled on disk.
#
# ``version`` sits LAST because it is the ambiguous spelling (a schema version
# would collide). It still counts as a patch marker: RC's patch identity IS the
# DDragon version - manifest.json's ``ddragon_version`` equals current.txt and
# equals the directory name in every shipped dir - so the two are the same
# string by construction, not by coincidence.
_PATCH_MARKER_KEYS: tuple[str, ...] = (
    "patch",
    "_patch",
    "rc_patch",
    "ddragon_version",
    "version",
)

# One level of nesting is also searched: enchanter_items.json carries its stamp
# at ``_meta.patch``. Mirrors the same reach as tools/ds_feed_index.extract_stamp.
_PATCH_MARKER_PARENTS: tuple[str, ...] = ("_meta", "meta")


def artifact_patch_marker(doc: object) -> tuple[str | None, str | None]:
    """The ``(key, value)`` of ``doc``'s own patch marker, or ``(None, None)``.

    Tolerant across every spelling shipped under ``data/daemon_slayer/`` (see
    ``_PATCH_MARKER_KEYS``) plus the nested ``_meta.patch`` form, so the RM-81
    stale-copy guard works on artifacts that ALREADY carry a marker without
    anything being rewritten on disk.

    ``(None, None)`` for a non-dict, an absent marker, or a non-string / empty
    value - an unprovable vintage, which callers treat exactly like a mismatch
    (the contract ``cdragon_sidecar_patch`` established).
    """
    if not isinstance(doc, dict):
        return None, None
    for key in _PATCH_MARKER_KEYS:
        val = doc.get(key)
        if isinstance(val, str) and val:
            return key, val
    for parent in _PATCH_MARKER_PARENTS:
        nested = doc.get(parent)
        if not isinstance(nested, dict):
            continue
        for key in _PATCH_MARKER_KEYS:
            val = nested.get(key)
            if isinstance(val, str) and val:
                return f"{parent}.{key}", val
    return None, None


def artifact_patch(root: Path, patch: str, artifact: str) -> str | None:
    """The patch ``<root>/<patch>/<artifact>`` was actually GENERATED at.

    The generalized sibling of :func:`cdragon_sidecar_patch`: reads the
    payload's OWN marker, which is what a patch-refresh commit does NOT update
    when it copies an artifact forward. ``None`` when the artifact is absent,
    unreadable, or carries no marker.
    """
    return artifact_patch_marker(_read_artifact_doc(root, patch, artifact))[1]


def check_artifact_patch(
    root: Path, patch: str, artifact: str, *, strict: bool = False
) -> bool:
    """Verify ``<root>/<patch>/<artifact>`` declares the patch it sits under.

    Returns True only when the artifact's own marker equals ``patch``. Any
    mismatch - INCLUDING an absent marker - is logged at WARNING and returns
    False.

    ``strict`` (default False / OFF) additionally raises ``ValueError``.
    Enforcement ships OFF because it is measurably NOT a no-op on the CURRENT
    shipped dir (``data/daemon_slayer/current.txt``, 16.15.1 when this was last
    re-measured on 2026-08-15), which is the bar RM-81's
    ``strict_cdragon_patch`` cleared and this guard cannot:

    * The two authored event-mode augment feeds declare ``rc_patch`` 16.10.1 ON
      PURPOSE - their body has not moved. They are named once, in
      ``tools/ds_feed_index.KNOWN_STAMP_LAG``, rather than repeated here.
      Enforcing stamp-equals-directory on them would be a false positive.

    The OTHER historical reason is GONE and the old wording here was measurably
    wrong: this docstring used to claim ``arena_augments.json`` and
    ``items_meraki.json`` "carry no marker at all". Re-measured 2026-08-15 over
    the current dir, ZERO of its 20 artifacts lack a marker - both of those now
    declare ``patch`` equal to their directory, backfilled in place plus stamped
    by ``tools/daemon_slayer_extract.py`` for every future extract.

    That correction is not housekeeping, it is the RM-213 defect: a MATCHING
    marker is not evidence of a refresh. The marker is exactly the field a
    copy-forward commit rewrites, so this guard goes green on an artifact whose
    body never moved. :func:`check_artifact_refresh` is the second axis - pair
    them, and never read a green from this one alone as "regenerated".

    Detection is therefore always on and enforcement is opt-in. Flip ``strict``
    per-call once an artifact is known clean; do NOT flip the default until the
    lag list is handled explicitly.
    """
    key, got = artifact_patch_marker(_read_artifact_doc(root, patch, artifact))
    if got == patch:
        return True
    if got is None:
        msg = (
            f"DS artifact {patch}/{artifact} carries no patch marker - its "
            f"vintage is unprovable, so a copy-forward is undetectable "
            f"(RM-81 class). Re-generate it so the payload stamps its own patch."
        )
    else:
        msg = (
            f"DS artifact {patch}/{artifact} was generated at patch {got!r} "
            f"(marker {key!r}), not {patch!r} - stale copy carried forward."
        )
    _LOG.warning("%s", msg)
    if strict:
        raise ValueError(msg)
    return False


# --- RM-213: the SECOND axis - did the artifact actually get re-generated? ----
#
# check_artifact_patch above answers "does the payload declare the dir it sits
# in". That is necessary and NOT sufficient, and the reason is structural
# rather than incidental: a copy-forward commit rewrites exactly that marker,
# so the patch-marker guard is green over every relabelled artifact BY
# CONSTRUCTION. The marker is evidence about the commit, never about the body.
#
# Two independent signals separate a real refresh from a relabel, and neither
# is sufficient alone:
#
#   BODY     the canonical fingerprint below - every marker / wall-clock /
#            prose key stripped. Answers "did the content move".
#   VINTAGE  the payload's own GENERATION stamp. Answers "did a run happen".
#
# BODY alone over-reports. Measured across all six shipped dirs: items_meraki
# and champion_abilities each carry a canonically-identical body in every one
# of them while their ``fetched_at`` moved on every extract. Both are genuinely
# re-fetched each time and genuinely return the same bytes, so a body-only
# check reports them red forever and the red means nothing.
#
# VINTAGE alone under-reports, and the founding RM-213 instance is why:
# tools/ds_wiki_staleness_check.py:454-455 writes ``_patch`` and
# ``_generated_at`` into the SAME dict literal, so a genuine run cannot emit
# one without the other - yet ability_staleness.json once sat in the current
# dir declaring the current patch over a ``_generated_at`` byte-identical to
# the previous dir's. A generator that ALWAYS stamps, showing a frozen stamp,
# is positive proof of a copy-forward rather than mere absence of proof. (That
# artifact has since been regenerated - it is recorded here as the shape this
# guard exists to catch, not as a live finding.)
#
# So the verdict below reads body AND vintage together. That is what lets it
# tell "re-run, returned identical bytes" (innocent) from "relabelled" (the
# defect) from "carries no stamp at all, so unknowable either way" (a
# remediable gap in the generator, not an accusation against the payload).
#
# Wall-clock GENERATION keys, in precedence order. Same key NAMES as
# tools/ds_feed_index._WALL_CLOCK, deliberately DUPLICATED rather than imported:
# the engine package must not import from tools/. The duplication is paid for by
# a parity test that loads ds_feed_index by path and asserts the subset.
_VINTAGE_KEYS: tuple[str, ...] = (
    "_generated_at",
    "generated_at",
    "extracted_at",
    "source_generated_at",
    "fetched_at",
    "timestamp",
)

# Keys dropped before hashing a body, BY NAME and at EVERY depth. Mirrors
# tools/ds_feed_index._STRIP (wall-clock + prose + stamp) so a fingerprint
# computed here is comparable with a body_md5 computed there. Never a
# value-shape regex: wiki_ability_stats carries bare numeric strings
# (speed_raw='1800') that a "looks like a version" matcher would eat.
_BODY_PROSE_KEYS: tuple[str, ...] = ("generated_note", "_note")
_BODY_STAMP_KEYS: tuple[str, ...] = (
    "version",
    "patch",
    "_patch",
    "rc_patch",
    "source_patch",
    "ddragon_version",
    "patch_segment",
    "_patch_segment",
    "meraki_content_patch",
    "_meraki_content_patch",
    "content_patch",
)
_BODY_STRIP_KEYS: frozenset[str] = frozenset(
    _VINTAGE_KEYS + _BODY_PROSE_KEYS + _BODY_STAMP_KEYS
)


def artifact_vintage(doc: object) -> tuple[str | None, str | None]:
    """The ``(key, ISO-8601 value)`` of ``doc``'s own GENERATION stamp.

    ``(None, None)`` for a non-dict, an absent stamp, or a value that is not a
    parseable timestamp - the same unprovable-vintage contract
    :func:`artifact_patch_marker` uses for the patch marker.

    Parsed with ``datetime.fromisoformat`` and NOT with a fixed ``strptime``
    format: all six shapes on disk (trailing ``Z``, ``-0500``, ``+00:00``, each
    with and without microseconds) round-trip through ``fromisoformat`` with
    tzinfo attached, and any single ``strptime`` format rejects three of them.
    """
    if not isinstance(doc, dict):
        return None, None
    for key in _VINTAGE_KEYS:
        val = doc.get(key)
        if not isinstance(val, str) or not val:
            continue
        try:
            datetime.fromisoformat(val)
        except ValueError:
            continue
        return key, val
    return None, None


def _canonical_body(obj):
    """Recursively drop marker, wall-clock and prose keys by NAME."""
    if isinstance(obj, dict):
        return {
            k: _canonical_body(v)
            for k, v in obj.items()
            if k not in _BODY_STRIP_KEYS
        }
    if isinstance(obj, list):
        return [_canonical_body(v) for v in obj]
    return obj


def artifact_body_fingerprint(doc: object) -> str:
    """8-hex digest of ``doc`` with every marker / wall-clock / prose key gone.

    Content-addressed, so it answers "did the CONTENT move" independently of
    what the payload claims about itself. Same canonicalisation and same digest
    width as ``tools/ds_feed_index.body_md5``, so the two are comparable and a
    caller may pass a stored index row straight in as ``prior_body``.
    """
    blob = json.dumps(
        _canonical_body(doc), sort_keys=True, separators=(",", ":")
    )
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:8]


def artifact_refresh_verdict(
    doc: object, *, prior_body: str | None, prior_vintage: str | None
) -> str:
    """Classify ``doc`` against the PREVIOUS patch dir's body + vintage.

    One of five strings, so a caller can pin WHICH condition fired rather than
    only that nothing raised:

    ``no-baseline``   no ``prior_body`` was supplied. An explicit PASS, never a
                      skip - "there is no previous dir" is the CALLER's answer.
    ``body-moved``    the content itself changed. Refreshed, provably.
    ``vintage-moved`` body identical, generation stamp moved. A genuine re-run
                      that returned identical bytes (the items_meraki shape).
    ``frozen``        body identical AND the generation stamp is byte-identical.
                      No re-run happened; a matching patch marker on top of this
                      is a relabel (the ability_staleness shape - RM-213).
    ``unprovable``    body identical and the payload carries NO generation stamp
                      at all, so re-run cannot be confirmed either way (the
                      scenarios / wiki_* shape).

    The baseline is INJECTED, never read from disk: "there is no previous dir"
    is the CALLER's answer (see ``no-baseline`` above), so a helper that went
    looking for the previous dir itself would be a permanent silent skip
    wherever only one patch dir is present.
    """
    if prior_body is None:
        return "no-baseline"
    if artifact_body_fingerprint(doc) != prior_body:
        return "body-moved"
    _, vintage = artifact_vintage(doc)
    if vintage is not None and vintage != prior_vintage:
        return "vintage-moved"
    if vintage is not None:
        return "frozen"
    return "unprovable"


def check_artifact_refresh(
    root: Path,
    patch: str,
    artifact: str,
    *,
    prior_body: str | None,
    prior_vintage: str | None,
    strict: bool = False,
) -> bool:
    """Verify ``<root>/<patch>/<artifact>`` was REGENERATED, not relabelled.

    The sibling of :func:`check_artifact_patch` on the other axis. That one asks
    whether the payload declares its own directory; this one asks whether
    anything about the payload actually moved since ``prior_body`` /
    ``prior_vintage`` (the previous dir's, supplied BY THE CALLER - see
    :func:`artifact_refresh_verdict`).

    Returns False, logging at WARNING with the artifact name and the verdict,
    for ``frozen`` and ``unprovable``. True for ``no-baseline``, ``body-moved``
    and ``vintage-moved``.

    ``strict`` (default False / OFF) additionally raises ``ValueError``.
    Enforcement ships OFF for the same reason ``check_artifact_patch`` does: it
    is measurably not a no-op over the shipped dirs. The load-bearing point is
    that a False here is NOT automatically a defect - both failing verdicts
    have a legitimate reading:

    * ``frozen`` is the CORRECT result for a feed whose upstream genuinely has
      not moved. The two authored event-mode augment feeds named in
      ``tools/ds_feed_index.KNOWN_STAMP_LAG`` read ``frozen`` precisely BECAUSE
      their vintage is honestly frozen - there is no newer upstream to fetch,
      so an actual re-run would reproduce the same stamp. Those two are
      referred to by their registry and never by filename on purpose, for the
      same registry-over-prose reason the closing paragraph below gives.
    * ``unprovable`` is a gap in the GENERATOR, not an accusation against the
      payload: the body did not move and nothing in it records a run, so this
      guard has nothing to read either way. The remedy is a vintage key at the
      write site. A hand-authored feed with no generator at all can never
      acquire one, and for it an unchanged body is the normal, correct state.

    WHICH artifacts currently read which verdict is deliberately NOT recited
    here. A census in prose is unguarded, goes stale on the next regen or patch
    bump, and the one that used to sit in this paragraph went stale inside a
    single session. The durable pair is a registry plus a machine check:
    ``tools/ds_feed_index.KNOWN_STATIC_BODY`` is the reasoned-innocent set,
    one written reason per feed, and the live-dir group in
    ``tests/test_ds_feed_index.py`` enforces the invariant that actually
    matters - every artifact reading ``frozen`` or ``unprovable`` against the
    previous dir must carry an entry there, so an unexplained one fails CI
    instead of sitting uncontradicted in a comment. To re-derive the live
    picture rather than trust prose::

        # recomputes each verdict off disk and NAMES any feed lacking a
        # reasoned exemption; this is the invariant, not a printout
        python -m pytest tests/test_ds_feed_index.py -q

        # recomputes every stored body hash off disk; exit 1 on any drift,
        # which is what keeps the baseline above honest
        python tools/ds_feed_index.py --check

    Scope note: an ABSENT artifact is not this guard's job. It fingerprints as
    the empty document, which differs from any real ``prior_body`` and so reads
    ``body-moved``; :func:`check_artifact_patch` is what reports a missing or
    unreadable file.
    """
    doc = _read_artifact_doc(root, patch, artifact)
    verdict = artifact_refresh_verdict(
        doc, prior_body=prior_body, prior_vintage=prior_vintage
    )
    if verdict == "no-baseline":
        _LOG.debug(
            "DS artifact %s/%s: verdict 'no-baseline' - no prior body supplied, "
            "so the refresh check PASSES by contract (not a skip).",
            patch,
            artifact,
        )
        return True
    if verdict in ("body-moved", "vintage-moved"):
        _LOG.debug(
            "DS artifact %s/%s: verdict %r - re-generation evidence present.",
            patch,
            artifact,
            verdict,
        )
        return True
    if verdict == "frozen":
        detail = (
            f"body is byte-identical to the previous dir's AND its generation "
            f"stamp is unchanged at {prior_vintage!r} - it was copied forward "
            f"and relabelled, not regenerated (RM-213 class)"
        )
    else:
        detail = (
            "body is byte-identical to the previous dir's and the payload "
            "carries no generation stamp, so a re-run cannot be confirmed - "
            "add one at the write site (RM-213 class)"
        )
    msg = (
        f"DS artifact {patch}/{artifact} refresh verdict {verdict!r}: {detail}."
    )
    _LOG.warning("%s", msg)
    if strict:
        raise ValueError(msg)
    return False


def cdragon_sidecar_patch(root: Path, patch: str) -> str | None:
    """The patch the sidecar under ``<root>/<patch>/`` was actually EXTRACTED at.

    Reads the payload's own ``patch`` field, which is what the patch-refresh
    ritual does NOT update when it copies a sidecar forward. ``None`` when the
    sidecar is absent, unreadable, or carries no ``patch`` field (an unprovable
    vintage, which the loader treats exactly like a mismatch).
    """
    doc = _read_cdragon_sidecar_doc(root, patch)
    if doc is None:
        return None
    got = doc.get("patch")
    return got if isinstance(got, str) and got else None


def _load_cdragon_ratio_sidecar(
    root: Path, patch: str, *, strict: bool = False
) -> dict[str, dict[str, list]]:
    """Read the CDragon mechanical-ratio sidecar for ``patch``; fail-soft to {}.

    The sidecar (``<root>/<patch>/cdragon_ability_ratios.json`` from
    ``tools/daemon_slayer_cdragon_ratio_extract.py``) re-sources per-ability
    damage ratios from the LIVE CommunityDragon character bins. A missing /
    unreadable / malformed sidecar returns ``{}`` so the caller falls back to the
    Meraki ``champion_abilities.json`` ratios unchanged - the CDragon source is a
    PREFERENCE, never a hard dependency.

    STALE-COPY GUARD: the sidecar used to be resolved by DIRECTORY alone, so a
    patch-refresh commit that copied the previous patch's file forward silently
    re-armed stale ratios as authoritative. That was live for three patches -
    the 16.11.1 / 16.12.1 / 16.13.1 sidecars are still byte-identical copies
    whose payload reads ``"patch": "16.11.1"``. The 16.14 re-extract fixed the
    CURRENT directory, so 16.14.1 carries its own matching payload patch and the
    guard is a no-op on shipped data; it only bites if a future patch-refresh
    copies a sidecar forward again, or if an older directory is loaded.

    The payload's own ``patch`` is now compared against the requested one and any
    mismatch - including an absent ``patch`` field - is logged at WARNING. With
    ``strict=True`` the stale sidecar is DROPPED and Meraki stays authoritative,
    which is what the fail-soft contract above already promises. This helper
    keeps ``strict=False`` as its own default so a direct caller gets pure
    detection; the LIVE path is ``AbilitiesSnapshot.load``, whose
    ``strict_cdragon_patch`` defaults True and passes enforcement in.

    Returns ``{champion_id: {slot: [block, ...]}}`` where each block is the raw
    resolver dict (``{name, base, ap_pct, ..., resolution, calc_type}``).
    """
    doc = _read_cdragon_sidecar_doc(root, patch)
    if doc is None:
        return {}
    payload_patch = doc.get("patch")
    if payload_patch != patch:
        _LOG.warning(
            "CDragon ratio sidecar under %s/ was extracted at patch %r, not %r - "
            "stale ratios would override Meraki. %s",
            patch,
            payload_patch,
            patch,
            "DROPPED (strict); Meraki authoritative."
            if strict
            else "APPLIED (non-strict); re-extract at the live patch.",
        )
        if strict:
            return {}
    champs = doc.get("champions")
    if not isinstance(champs, dict):
        return {}
    return champs


# CDragon AD / HP stat families - a damage block must never carry two fields
# from one family (that silently double-counts the stat). The matcher routes a
# CDragon ratio onto whichever same-family field the Meraki block already uses.
_CDRAGON_AD_FIELDS: tuple[str, ...] = ("total_ad_pct", "bonus_ad_pct")
_CDRAGON_HP_FIELDS: tuple[str, ...] = ("caster_max_hp_pct", "target_max_hp_pct")

# (champion_id, key) forms whose Meraki damage block is a baked full-channel
# TOTAL while their only CDragon mechanical block is a per-instance atomic
# (PerWave / PerTick / PerShot). The direct-pair re-source would overwrite the
# total with the atomic (MissFortune R "Bullet Time": Meraki 1050/1200/1350%
# total AD vs CDragon PhysicalDamagePerWave 60% AD -> ~17.7x undercount).
# Consulted ONLY when ``apply_cdragon_resource_guard=True``; default-OFF keeps
# the snapshot byte-identical to the current live cutover behavior.
_CDRAGON_RESOURCE_EXCLUSIONS: frozenset[tuple[str, str]] = frozenset(
    {("MissFortune", "R")}
)

# A-29 / BACKLOG R129 - the CDragon SURPLUS-block allowlist.
#
# ``_apply_cdragon_ratio_preference`` is overwrite-only: it never changes the
# damage-block count, and any Meraki-vs-CDragon cardinality mismatch falls the
# WHOLE form back to Meraki. Viego R is that case - Meraki carries ONE damage
# block (the 12/16/20 percent missing-HP strike) while the sidecar resolves TWO
# mechanical blocks, and the surplus one is the 120 percent total-AD primary hit
# ("All targets hit are dealt 120% : 240% (based on critical strike chance) AD
# physical damage"). Dropping it makes ``compute_ability_dps("Viego")`` credit
# 0.0 for R at full target HP, because BOTH of the surviving block's
# coefficients scale on MISSING HP (measured 2026-07-24 at patch 16.14.1).
#
# Each entry maps ``(champion_id, spell_key)`` to
# ``(cdragon_block_name, meraki_damage_block_ordinal)``: the sidecar block to
# read the coefficient from, and which of the form's ``attribute_kind ==
# "damage"`` blocks (0-based among damage blocks only) receives it. Consulted
# ONLY when ``AbilitiesSnapshot.load(apply_cdragon_surplus_ad=True)``.
#
# MERGE, not append. ``compute_ability_dps`` defaults to
# ``block_strategy="first"``, which evaluates ``damage_blocks[0]`` and nothing
# else (``ability_dps._select_blocks``), and Viego has no
# ``champion_block_index.json`` override to widen that - so a block APPENDED at
# index 1 would never be read and the credit would stay 0.0. Merging the surplus
# ratio into the target block credits it under every strategy, keeps the
# block-count invariant that ``test_cdragon_ratio_matcher`` pins, and disturbs no
# block index. Only stat FAMILIES the target does not already carry are merged,
# so the family router can never double-count.
#
# Deliberately NOT a general "append every surplus CDragon block" seam. That was
# measured over the live sidecar: 329 surplus blocks across 220 (champion, spell)
# pairs, 65 of which already carry at least as many Meraki damage blocks as the
# sidecar resolves, and 8 of 8 spot-checks were outright duplicates (Teemo E
# ImpactCalculatedDamage == "Magic Damage On-Hit" coefficient for coefficient;
# Pantheon Q HoldDamageCalc == "Hurl Physical Damage"; Jax E TotalDamage ==
# "Minimum Magic Damage"; Yone W WDamage == "Total Mixed Damage" plus a second
# anonymous 100 percent-AD block) or not damage at all (Shyvana W Calc_Shield is
# a shield, Ornn W TotalMonsterDamageCap is a cap). The general seam is REFUTED.
#
# The five filed siblings are all v1-EXCLUDED on their own effects text, and each
# additionally has ZERO Meraki damage blocks for the slot, so the merge seam
# cannot reach them even if the semantics passed:
#   Pyke   R - the 80 percent bonus AD is an execute HEALTH THRESHOLD, not damage.
#   Rengar R - "next basic attack ... 100% AD bonus": an auto empower compute_dps
#              already counts.
#   Quinn  R - the 35 percent block is Skystrike (form_index 1); the sidecar is
#              form-indexless and only form 0 (the damage-less channel) is seen.
#   Yorick R - YorickBigGhoulDamage is the Maiden PET's damage, another cadence.
#   Jinx   Q - "Basic attacks with Fishbones ... 110% AD": an auto modifier.
# Widen this registry only on per-champion evidence, with an exclusion test for
# every neighbour left out.
_CDRAGON_SURPLUS_AD_MERGES: dict[tuple[str, str], tuple[str, int]] = {
    ("Viego", "R"): ("TotalDamage", 0),
}


def _cdragon_family(field_name: str) -> str:
    """Collapse a scaling field to its stat FAMILY (AD / HP) or itself."""
    if field_name in _CDRAGON_AD_FIELDS:
        return "AD"
    if field_name in _CDRAGON_HP_FIELDS:
        return "HP"
    return field_name


def _meraki_block_signature(block: DamageBlock) -> frozenset:
    """The set of stat FAMILIES a Meraki damage block carries (base + ratios)."""
    sig: set[str] = set()
    if block.base is not None:
        sig.add("base")
    for fld in _CDRAGON_RATIO_FIELDS:
        if fld == "base":
            continue
        if getattr(block, fld, None) is not None:
            sig.add(_cdragon_family(fld))
    return frozenset(sig)


def _cdragon_block_signature(cd: dict) -> frozenset:
    """The set of stat FAMILIES a CDragon mechanical block resolved (non-empty lists)."""
    sig: set[str] = set()
    for fld in _CDRAGON_RATIO_FIELDS:
        v = cd.get(fld)
        if isinstance(v, list) and v:
            sig.add("base" if fld == "base" else _cdragon_family(fld))
    return frozenset(sig)


def _apply_cdragon_block(block: DamageBlock, cd: dict) -> DamageBlock:
    """Re-source one Meraki ``block`` from one matched CDragon block ``cd``.

    Per-field: every scaling field the CDragon block resolved (a non-empty list in
    ``_CDRAGON_RATIO_FIELDS``) overrides the Meraki value, BUT an AD/HP ratio is
    ROUTED onto whichever same-family field the Meraki block already carries
    (CDragon ``total_ad_pct`` onto a Meraki ``bonus_ad_pct``) so the block never
    ends up with two fields from one family (a silent double-count). The first
    CDragon field to claim a target wins; a CDragon array longer than the Meraki
    field it replaces is trimmed to keep per-block rank lengths stable. Fields the
    CDragon block left None keep the Meraki value (per-field fall-back).
    """
    overrides: dict[str, Any] = {}
    for fld in _CDRAGON_RATIO_FIELDS:
        v = cd.get(fld)
        if not (isinstance(v, list) and v):
            continue
        if fld == "base":
            target = "base"
        elif fld in _CDRAGON_AD_FIELDS:
            existing = [f for f in _CDRAGON_AD_FIELDS if getattr(block, f) is not None]
            target = existing[0] if existing else fld
        elif fld in _CDRAGON_HP_FIELDS:
            existing = [f for f in _CDRAGON_HP_FIELDS if getattr(block, f) is not None]
            target = existing[0] if existing else fld
        else:
            target = fld
        if target in overrides:
            continue  # family already claimed (first CDragon field wins)
        arr = tuple(float(x) for x in v)
        cur = getattr(block, target, None)
        if cur is not None and len(cur) < len(arr):
            arr = arr[: len(cur)]
        overrides[target] = arr
    if not overrides:
        return block
    return replace(block, **overrides)


def _apply_cdragon_ratio_preference(form: AbilityForm, cd_blocks: list) -> AbilityForm:
    """Re-source ``form``'s damage-block ratios from the CDragon sidecar slot list.

    Runs whenever ``AbilitiesSnapshot.load`` is called with
    ``prefer_cdragon_ratios=True`` (the default since the item 320 cutover; pass
    False for the legacy Meraki-only path). Only ``resolution == "mechanical"``
    CDragon blocks that resolved at least one usable field are eligible.

    The pairing is SEMANTIC, not positional (the old ``zip`` mis-paired multi-block
    abilities - a transform form's calc landing on the wrong block, or a tooltip
    aggregate onto a per-instance block - and double-counted AD by appending
    CDragon ``total_ad_pct`` beside Meraki ``bonus_ad_pct``):

      * A single Meraki damage block + a single mechanical CDragon block pair
        directly (unambiguous), per-field override.
      * Otherwise the two block sets are matched by stat-FAMILY signature: the
        re-source applies ONLY when the multiset of Meraki damage-block signatures
        equals the multiset of CDragon mechanical-block signatures AND every
        signature is unique (a clean bijection). Any cardinality mismatch (Meraki
        tooltip-expanded into more blocks than CDragon resolved) or a repeated
        signature (two blocks the data cannot tell apart) makes the WHOLE form fall
        back to Meraki - structure preserved, never mis-paired.

    The damage-block COUNT is never changed and no block ever carries two fields
    from one stat family. Returns ``form`` unchanged when nothing applies.
    """
    mech = [
        b
        for b in cd_blocks
        if isinstance(b, dict)
        and b.get("resolution") == "mechanical"
        and _cdragon_block_signature(b)
    ]
    if not mech:
        return form
    dmg_idx = [
        i for i, b in enumerate(form.damage_blocks) if b.attribute_kind == "damage"
    ]
    if not dmg_idx:
        return form

    pairs: dict[int, dict] = {}
    if len(dmg_idx) == 1 and len(mech) == 1:
        pairs[dmg_idx[0]] = mech[0]
    else:
        msig = [_meraki_block_signature(form.damage_blocks[i]) for i in dmg_idx]
        csig = [_cdragon_block_signature(c) for c in mech]
        m_counts = Counter(msig)
        if m_counts != Counter(csig) or any(v > 1 for v in m_counts.values()):
            return form  # ambiguous structure - whole-form fall back to Meraki
        by_sig = {s: c for s, c in zip(csig, mech)}
        for i, s in zip(dmg_idx, msig):
            pairs[i] = by_sig[s]

    new_blocks = list(form.damage_blocks)
    changed = False
    for i, cd in pairs.items():
        replaced = _apply_cdragon_block(new_blocks[i], cd)
        if replaced is not new_blocks[i]:
            new_blocks[i] = replaced
            changed = True
    if not changed:
        return form
    return replace(form, damage_blocks=tuple(new_blocks))


def _apply_cdragon_surplus_ad_merge(
    cid: str, key: str, form: AbilityForm, cd_blocks: list
) -> AbilityForm:
    """Merge an allowlisted SURPLUS CDragon ratio into its Meraki damage block.

    A-29 / BACKLOG R129. ``_apply_cdragon_ratio_preference`` re-sources only when
    the two block sets form a clean bijection; a form whose sidecar resolves MORE
    mechanical blocks than Meraki carries falls back whole and its extra
    coefficient is lost. For the narrow hand-audited set in
    ``_CDRAGON_SURPLUS_AD_MERGES`` this reads the named sidecar block and merges
    the stat families the target block does NOT already carry into it, through the
    same ``_apply_cdragon_block`` field-router the bijection path uses.

    Only the SURPLUS families are applied: a family the target already carries is
    left to (and was already declined by) the bijection path, so this can never
    double-count a stat, and the damage-block COUNT never changes. Ratio arrays
    are trimmed to the target block's existing per-rank length to keep block rank
    lengths stable.

    Returns ``form`` unchanged when the pair is not allowlisted, the named sidecar
    block is absent / unresolved, the target ordinal does not exist, or every
    family the sidecar offers is already present. The default (flag OFF) path in
    ``AbilitiesSnapshot.load`` never calls this, so it is byte-identical.
    """
    entry = _CDRAGON_SURPLUS_AD_MERGES.get((cid, key))
    if entry is None:
        return form
    block_name, ordinal = entry
    cd = next(
        (
            b
            for b in cd_blocks
            if isinstance(b, dict)
            and b.get("resolution") == "mechanical"
            and b.get("name") == block_name
            and _cdragon_block_signature(b)
        ),
        None,
    )
    if cd is None:
        return form
    dmg_idx = [
        i for i, b in enumerate(form.damage_blocks) if b.attribute_kind == "damage"
    ]
    if not 0 <= ordinal < len(dmg_idx):
        return form
    idx = dmg_idx[ordinal]
    target = form.damage_blocks[idx]
    surplus = _cdragon_block_signature(cd) - _meraki_block_signature(target)
    if not surplus:
        return form
    lengths = [
        len(getattr(target, f))
        for f in _SCALING_FIELDS
        if getattr(target, f) is not None
    ]
    rank_len = max(lengths) if lengths else None
    filtered: dict[str, Any] = {}
    for fld in _CDRAGON_RATIO_FIELDS:
        v = cd.get(fld)
        if not (isinstance(v, list) and v):
            continue
        family = "base" if fld == "base" else _cdragon_family(fld)
        if family not in surplus:
            continue
        filtered[fld] = v[:rank_len] if rank_len else v
    if not filtered:
        return form
    merged = _apply_cdragon_block(target, filtered)
    if merged is target:
        return form
    new_blocks = list(form.damage_blocks)
    new_blocks[idx] = merged
    return replace(form, damage_blocks=tuple(new_blocks))


def _coverage_with_injected(
    coverage: dict,
    data_block: dict,
    injected: tuple[str, ...],
) -> dict:
    """Return ``coverage`` reconciled with the hand-authored injected forms.

    ``coverage`` is the EXTRACTOR's own tally of the file on disk, and
    ``test_abilities.CoverageThresholdTests`` asserts it describes what the
    loaded snapshot actually contains (``iter_forms`` count and
    ``parse_status_counts`` must both match). Injecting champions the file does
    not carry would drift both, so the counts are folded forward additively
    here. Purely derived - every number comes from the injected payloads, and
    with no injection the input dict is returned unchanged (same object).

    ``ok_rate`` / ``parsed_rate`` are recomputed the way the extractor defines
    them: over ``damage_eligible`` (= forms that are not ``no_damage``),
    rounded to 4 places.
    """
    if not injected:
        return coverage
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in coverage.items()}
    status_counts = {k: int(v) for k, v in (out.get("status_counts") or {}).items()}
    by_key_src = out.get("by_key") or {}
    by_key = {k: {kk: int(vv) for kk, vv in (v or {}).items()}
              for k, v in by_key_src.items()}
    total_forms = int(out.get("total_forms") or 0)
    damage_eligible = int(out.get("damage_eligible") or 0)
    for cid in injected:
        for key, forms in (data_block.get(cid) or {}).items():
            for f in forms:
                if not isinstance(f, dict):
                    continue
                status = f.get("parse_status") or "unparsed"
                total_forms += 1
                status_counts[status] = status_counts.get(status, 0) + 1
                if key in by_key:
                    by_key[key][status] = by_key[key].get(status, 0) + 1
                if status != "no_damage":
                    damage_eligible += 1
    out["total_forms"] = total_forms
    out["status_counts"] = status_counts
    if by_key:
        out["by_key"] = by_key
    if "damage_eligible" in out or damage_eligible:
        out["damage_eligible"] = damage_eligible
    if damage_eligible:
        ok = status_counts.get("ok", 0)
        partial = status_counts.get("partial", 0)
        out["ok_rate"] = round(ok / damage_eligible, 4)
        out["parsed_rate"] = round((ok + partial) / damage_eligible, 4)
    return out


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
        apply_passive_shield: bool = False,
        apply_all_out_bonus: bool = False,
        prefer_cdragon_ratios: bool = True,
        apply_cdragon_resource_guard: bool = False,
        cdragon_root: Path | None = None,
        strict_cdragon_patch: bool = True,
        apply_cdragon_surplus_ad: bool = False,
        apply_ability_base_overrides: bool = False,
        apply_wiki_ability_damage: bool = True,
        apply_wiki_form_damage: bool = False,
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

        ``apply_passive_shield`` (GAP 2, item 260, default False / OFF) is the
        SHIELD sibling: when True, ``_apply_passive_shield_overrides`` appends a
        synthetic ``attribute_kind="shield"`` block to each registered form that
        has NO existing shield block (Malphite Granite Shield, Blitzcrank Mana
        Barrier, Vi/Shen/Rakan/Yasuo P, Skarner W, Volibear E, Viktor Q, Camille
        P - effects-text-only self-shields) so ``compute_ability_hps`` scores
        them in ``total_shield_per_sec``. Default OFF = byte-identical.

        ``apply_all_out_bonus`` (R50, default False / OFF) is the K'Sante All Out
        Bonus seam: when True, ``_apply_all_out_bonus_overrides`` appends a
        SECOND synthetic damage block (the R-empowered bilinear caster
        bonus-resist x target-max-HP term, gated by its All-Out-uptime
        probability) onto K'Sante's P form. Independent of
        ``apply_passive_damage`` - both flags ON coexist (base mark consume +
        All Out bonus); it is kept out of the base registry so the item-255
        magnitude stays byte-identical. Default OFF = byte-identical.

        ``prefer_cdragon_ratios`` (default True / ON since item 320 / ENGINE
        1.119.0 cutover) re-sources per-ability damage RATIOS from the live
        CommunityDragon mechanical sidecar
        (``cdragon_ability_ratios.json``, ``tools/daemon_slayer_cdragon_ratio_extract.py``)
        in preference to the frozen Meraki ``champion_abilities.json``. When True
        (the default), each primary form's damage-block scaling fields are
        overridden per-field by the matching ``resolution == "mechanical"`` CDragon
        block; any field / block the resolver could not mechanically resolve falls
        back to Meraki, as does a missing sidecar. ``cdragon_root`` overrides where
        the sidecar is read from (defaults to ``data_root``). Set False to force the
        legacy Meraki-only path - the sidecar is never read and forms are
        byte-identical to the pre-cutover behavior.

        ``strict_cdragon_patch`` (default True / ON since the 16.14 re-extract)
        enforces the stale-copy guard in ``_load_cdragon_ratio_sidecar``: a
        sidecar whose own ``patch`` field does not match ``patch`` is DROPPED and
        Meraki stays authoritative. The mismatch is logged at WARNING either way
        - only the enforcement is gated. It shipped OFF for exactly one commit
        (the detector, LEDGER 935) because the then-live 16.14.1 sidecar was a
        verbatim 16.11.1 copy overriding Meraki on 49 of 171 champions (55 blocks
        / 75 fields); re-extracting at 16.14 made the payload patch match the
        directory, so enforcement is now a no-op on the shipped data and only
        bites if a future patch-refresh copies a sidecar forward again. Pass
        False only to reproduce pre-guard behavior in a test.

        ``apply_cdragon_surplus_ad`` (A-29 / BACKLOG R129, default False / OFF) is
        the SURPLUS-block seam. ``prefer_cdragon_ratios`` above is overwrite-only
        - it never changes a form's damage-block count, and a form whose sidecar
        resolves MORE mechanical blocks than Meraki carries falls back whole, so
        the extra coefficient is silently lost. When True, each pair in
        ``_CDRAGON_SURPLUS_AD_MERGES`` has that surplus ratio MERGED into its
        Meraki damage block (see ``_apply_cdragon_surplus_ad_merge``); v1 seeds
        only Viego R, whose 120 percent total-AD primary hit is otherwise
        uncredited so ``compute_ability_dps("Viego")`` scores R as 0.0 at full
        target HP. Requires the sidecar (it is where the coefficient comes from),
        so it is inert when ``prefer_cdragon_ratios=False`` or the sidecar is
        missing / rejected by the patch guard. Default OFF = byte-identical, and
        even ON the damage-block COUNT is invariant.

        ``apply_ability_base_overrides`` (A-03 / RM-81, default False / OFF)
        corrects the six STALE ability base-damage series that the 2026-07-18
        RM-81 characterization measured as the only ones that change a ranked
        item order (Mordekaiser Q / Naafiri R / Heimerdinger W / Azir W /
        Malzahar W / Ahri R). The extractor cannot re-source them - it is pinned
        to Meraki content patch 25.15 and a ``--force`` re-extract is a standing
        repo hazard - so the corrections are hand-authored in
        ``_ability_base_overrides`` and spliced over the stale rank HEAD of the
        block's ``base`` at load time, after the CDragon re-source so the
        registry is the final authority. Each entry is guarded on the stale
        series still being present, so a repaired upstream can never be
        double-corrected. Default OFF = byte-identical: not one form is touched.

        ``apply_wiki_ability_damage`` (default True / ON) closes the 173-vs-171
        keyspace hole. The Meraki bulk snapshot never shipped ``Locke`` or
        ``Zaahen`` - they are the entire set difference against
        ``champions.json``, and the loop below constructs nothing for a
        champion absent from ``data``, so both fall through to
        ``total_burst_damage == 0.0`` with every cast noted "ability data
        unavailable" and every ranked candidate at ``delta_burst 0.0``. When
        True, ``_ability_wiki_damage_registry.inject_missing_champions`` adds
        the two hand-authored, wiki-sourced payloads to ``data_block`` BEFORE
        the loop, so they are built through the identical
        ``AbilityForm.from_dict`` + override + CDragon path as every Meraki
        champion.

        ``apply_wiki_form_damage`` (RM-95b residual, default False / OFF) is
        the sibling of that injection for a form Meraki DOES ship but shipped
        with no ``attribute_kind == "damage"`` block. The measured population
        is ONE - Quinn R, whose served form (``Behind Enemy Lines``) carries
        only a movement-speed modifier while the Skystrike form carries no
        block at all, so her ultimate contributes 0.0 to her own ability lane.
        The two siblings the RM-95b row named alongside it are refuted in
        ``_ability_wiki_form_damage``: Jayce W Hyper Charge is an auto-attack
        rider whose numbers are already on disk, and Mel W Rebuttal is a
        percentage of an incoming projectile no registry can price. This seam
        MUTATES a served form, so it ships DEFAULT-OFF and OFF is
        byte-identical.

        This is the ONE seam in this loader that ships DEFAULT-ON, and
        deliberately: every other flag MUTATES a form the engine already
        serves, so OFF is their byte-identical contract, whereas a champion the
        snapshot does not contain has no prior behavior to preserve and
        therefore no regression surface. The injection is
        KEYS-NOT-PRESENT-ONLY, so it can never overwrite a champion Meraki
        does ship - which also makes it silently inert the day a re-extract
        supplies them for real. Pass False to reproduce the pre-registry
        171-champion keyspace.
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
        # Prefer-CDragon re-source: read the mechanical-ratio sidecar once
        # (default ON since the item-320 cutover). Empty map = no sidecar, or a
        # stale sidecar rejected by the patch guard -> Meraki stays authoritative.
        cd_map = (
            _load_cdragon_ratio_sidecar(
                Path(cdragon_root) if cdragon_root else root,
                patch,
                strict=strict_cdragon_patch,
            )
            if prefer_cdragon_ratios
            else {}
        )
        # Wiki-sourced injection for champions the Meraki bulk snapshot never
        # shipped (Locke / Zaahen). MUST run before the loop below: that loop
        # iterates ``data_block`` and constructs NOTHING for an absent
        # champion. Keys-not-present-only, so a champion Meraki does ship is
        # never overwritten and the other 171 stay byte-identical.
        injected: tuple[str, ...] = ()
        if apply_wiki_ability_damage:
            injected = _inject_wiki_damage_champions(data_block)
            if injected:
                _LOG.debug(
                    "abilities: injected hand-authored wiki payloads for %s "
                    "(snapshot %s carried %d champions)",
                    ", ".join(injected), patch, len(data_block) - len(injected),
                )
        # RM-95b residual: authored damage blocks for forms Meraki DOES ship but
        # shipped with no damage block at all (population 1: Quinn R Skystrike).
        # Runs after the injection above and before the build loop, so the block
        # is built through the identical AbilityForm path. DEFAULT-OFF: unlike
        # the injection this MUTATES a served form.
        if apply_wiki_form_damage:
            patched = _apply_wiki_form_damage(data_block)
            if patched:
                _LOG.debug(
                    "abilities: applied hand-authored wiki form damage to %s",
                    ", ".join(patched),
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
                    # GAP 2 effects-text-only SHIELD: opt-in, default OFF.
                    if apply_passive_shield:
                        fm = _apply_passive_shield_overrides(cid, key, fm)
                    # R50 K'Sante All Out Bonus (bilinear caster-resist): opt-in,
                    # default OFF. Independent of apply_passive_damage - both flags
                    # ON coexist (base mark consume + All Out bonus). Byte-identical OFF.
                    if apply_all_out_bonus:
                        fm = _apply_all_out_bonus_overrides(cid, key, fm)
                    # Prefer-CDragon mechanical ratios: default-ON since the
                    # item-320 cutover. Primary form only (the sidecar emits one
                    # block list per slot, no form_index) - transform forms keep
                    # Meraki. ``apply_cdragon_resource_guard`` (default-OFF) skips
                    # the re-source for forms whose CDragon block is a per-instance
                    # atomic that would clobber a Meraki full-channel total.
                    if cd_map and fm.form_index == 0 and not (
                        apply_cdragon_resource_guard
                        and (cid, key) in _CDRAGON_RESOURCE_EXCLUSIONS
                    ):
                        cd_slot = (cd_map.get(cid) or {}).get(key)
                        if cd_slot:
                            fm = _apply_cdragon_ratio_preference(fm, cd_slot)
                            # A-29 surplus-block merge (Viego R 120% total AD):
                            # allowlist-gated, opt-in, default OFF. Runs AFTER the
                            # bijection re-source so it only ever adds a stat
                            # family that path declined to supply.
                            if apply_cdragon_surplus_ad:
                                fm = _apply_cdragon_surplus_ad_merge(
                                    cid, key, fm, cd_slot
                                )
                    # A-03 / RM-81 stale base-damage corrections: opt-in,
                    # default OFF. Runs LAST so the hand-authored wiki value is
                    # the final authority over both Meraki and the CDragon
                    # re-source (and so its stale-guard sees exactly what the
                    # consumer would otherwise have got).
                    if apply_ability_base_overrides:
                        fm = _apply_base_overrides(cid, key, fm)
                    built.append(fm)
                per_key[key] = tuple(built)
            champions[cid] = per_key
        return cls(
            patch=patch,
            fetched_at=doc.get("fetched_at") or "",
            source=doc.get("source") or "",
            coverage=_coverage_with_injected(
                doc.get("coverage") or {}, data_block, injected
            ),
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


# --- Singleton-style helpers (mirrors ult_rates.py pattern) ------------------

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
