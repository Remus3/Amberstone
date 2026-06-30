"""Phase 5 (s180, 2026-05-13) - Assassin burst-window scorer.

Sibling of ``ability_dps.py``. ``compute_burst_damage()`` returns the
caster's total damage dealt during a single combo rotation
(``Q->W->E->AA->R->AA`` by default - operator-overridable via
``combo_sequence``). ``rank_items_by_burst()`` drives the
``/rank-assassin`` route - same candidate-filtering pipeline as the
DPS / EHP / hybrid / ability scorers, but each candidate is scored by
total burst-damage gain over the baseline.

Assassins delete one target in a 1.5-2s window. Auto-attack DPS
(``ds.dps``) amortizes long-cooldown procs over sustained fights, which
underweights burst-proc items (Duskblade Nightstalker, Eclipse Ever
Rising Moon, lethality items) the way an assassin actually uses them.
Per-cast scoring within the window correctly values lethality, true
damage, and one-shot ability bonuses.

Combo template
~~~~~~~~~~~~~~

Default: ``("Q", "W", "E", "AA", "R", "AA")``. Caller can pass a
custom template via ``combo_sequence`` - e.g. Zed's full rotation
``("W", "E", "Q", "AA", "R", "Q2", "AA", "AA", "AA")`` or Talon's
``("W", "Q", "AA", "R", "AA")``. Tokens:

* ``"AA"`` - one auto-attack hit; uses the build's per-hit
  ``avg_attack_dmg`` from ``compute_dps`` (post-armor + mode).
* ``"P"`` / ``"Q"`` / ``"W"`` / ``"E"`` / ``"R"`` - one cast of that
  ability at its level-resolved rank.
* ``"Q2"`` / ``"W2"`` / ``"E2"`` / ``"R2"`` - a repeat cast of the
  same ability at the SAME rank (the combo window is too short for a
  level-up). The trailing digit is treated as a "second instance"
  marker; Zed's R-shadow re-cast Q is the canonical case.
* Anything else raises ``ValueError`` at validation time.

Phase 5 deliberate omissions (Phase 5.5 / future):
* Real cooldown sequencing - every spell modeled as ready at combo
  start; CDR doesn't affect a single-combo window.
* Mana economy - assassins typically run energy / manaless / one-rotation
  buffer; not a meaningful burst constraint.
* On-attack periodic procs (Wit's End, Sundered Sky Lightshield Strike,
  BotRK Mist's Edge) - captured in ``avg_attack_dmg`` as ZERO. Phase 5
  models AA damage as raw post-armor AD x crit, no on-hit procs.
  Phase 5.5 adds an inline ``per_attack_proc_damage`` walker.
* Champion-specific combo templates (Kha'Zix isolation Q bonus, Akali
  R2 after R1, Zed shadow R+Q2) - Phase 5.5 with a per-champion
  combo-template JSON. v1 caller passes ``combo_sequence`` explicitly.
* Conditional damage amps (Ahri R->Q amp, Zoe E->Q amp) - single
  per-cast scoring with no combo-multiplier; same omission as Phase 4b.

Phase 5 ALSO models the burst window with the SAME amp pipeline as
Phase 4b - Rabadon's, Liandry's, Demonic Embrace, Riftmaker HP->AP, all
flow through correctly so a Diana or Akali build registers their AP
amplification.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .abilities import (
    AbilitiesNotFound,
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
)
from .ability_dps import (
    AbilityContext,
    _classify_primary_scaling,
    _evaluate_block,
    _form_cooldown_at_rank,
    _form_cost_at_rank,
    _mitigation_factor,
    _resolve_block_index_overrides,
    _resolve_form_index_overrides,
    _resolve_max_priority,
    _select_blocks,
    rank_at_level,
)
from .data_loader import DataSnapshot
from .dps import (
    _ASSUMED_ABILITY_AMP_STACKS,
    _ASSUMED_TAKEDOWN_STACKS,
    compute_dps,
)
from .effects import (
    ITEM_EFFECTS,
    collect_effects,
    effective_target_armor,
    effective_target_mr,
    total_ability_damage_amp,
    total_ap_amp_multiplier,
    total_bonus_ap_from_hp,
    total_caster_hp_scaled_ap_amp,
    total_damage_amp_multiplier,
    total_execute_max_hp_pct,
    total_giant_slayer_multiplier,
    total_magic_amp_multiplier,
    total_magic_burst_damage,
    total_stacked_ap,
    total_takedown_bonus_ad,
    total_target_bonus_hp_amp_multiplier,
)
from .engine import build_champion
from .geometry import spell_aoe_multiplier
from .kit_axis_credit import kit_axis_item_ids
from .rune_procs import (
    COMPLETION_RUNE_IDS,
    RUNE_PROCS,
    compute_rune_proc_damage,
    keystone_amp,
)

# item 233 - melee/ranged split for per_attack rune scaling (Lethal Tempo melee
# 9-30 vs ranged 6-24). No champion sits between melee (~125-175) and ranged
# (~450+), so 350 cleanly separates the two.
_RANGED_ATTACK_RANGE = 350.0
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level

# Default combo template - Q W E AA R AA. Most AD/AP assassins fit the
# ability-then-AA-then-R cadence; channel/burst ults (Akali R, Kassadin
# R, Diana R, Zed R) plus shadow/blink R execute with one AA before and
# one AA after the ult lands.
DEFAULT_COMBO_SEQUENCE: tuple[str, ...] = ("Q", "W", "E", "AA", "R", "AA")

# Phase 5.5 (s186, 2026-05-13) - per-champion combo override registry.
# Same lazy-cache pattern as ability_dps._load_max_priority_table; ships
# next to the engine rather than next to the patch snapshot, since combo
# overrides reflect a champion's kit identity not a patch-time stat tweak.
_COMBO_PATH = Path(__file__).resolve().parent / "champion_combo_sequences.json"
_COMBO_LOCK = threading.Lock()
_COMBO_CACHE: Optional[dict] = None


def _load_combo_table() -> dict:
    """Load the per-champion combo_sequence override table from disk.

    Singleton cache. Tests can call ``reset_combo_cache()`` to force a
    re-read after mutating the on-disk file.
    """
    global _COMBO_CACHE
    with _COMBO_LOCK:
        if _COMBO_CACHE is None:
            _COMBO_CACHE = json.loads(_COMBO_PATH.read_text(encoding="utf-8"))
        return _COMBO_CACHE


def reset_combo_cache() -> None:
    """Clear the singleton cache - for tests that mutate the on-disk file."""
    global _COMBO_CACHE
    with _COMBO_LOCK:
        _COMBO_CACHE = None


def get_combo_for(champion_id: str) -> tuple[tuple[str, ...], str]:
    """Return ``(combo_tuple, source)`` for ``champion_id``.

    ``champion_id`` is the DDragon canonical id (``"Khazix"``, ``"Leblanc"``,
    not apostrophes). Source is ``"champion"`` for an explicit override or
    ``"default"`` for the table fallback. The returned combo is already
    token-validated via ``_validate_combo_sequence``.
    """
    table = _load_combo_table()
    overrides = table.get("champions") or {}
    if champion_id in overrides:
        seq = overrides[champion_id]
        return (_validate_combo_sequence(seq), "champion")
    default_seq = table.get("default") or list(DEFAULT_COMBO_SEQUENCE)
    return (_validate_combo_sequence(default_seq), "default")


def _resolve_combo_sequence(
    champion_id: str,
    explicit: Optional[Sequence[str]],
) -> tuple[tuple[str, ...], str]:
    """Resolve combo_sequence from caller input + override registry.

    Returns ``(combo_tuple, source)`` where source is:
      * ``"override"`` - caller passed an explicit value
      * ``"champion"`` - override table had an entry for the champion
      * ``"default"`` - fell back to the table default (Q-W-E-AA-R-AA)
    """
    if explicit is not None:
        return (_validate_combo_sequence(explicit), "override")
    return get_combo_for(champion_id)

# Spell key set - passive included so combos like Akali's P-on-hit can
# (in a future version) be inserted explicitly. Phase 5 v1 only fires P
# when the operator includes it in combo_sequence.
_SPELL_KEYS: frozenset[str] = frozenset({"P", "Q", "W", "E", "R"})

# Token markers - strip the trailing digit if present to find the ability
# key; the digit just signals a repeat cast at the same rank.
_REPEAT_SUFFIXES: frozenset[str] = frozenset({"2", "3", "4"})


def _normalize_combo_token(token: str) -> tuple[str, str, bool]:
    """Return ``(canonical_token, ability_key, is_ability)``.

    ``canonical_token`` is what shows up in the per-cast result; useful for
    distinguishing Q from Q2 in operator-readable output. ``ability_key``
    is the underlying P/Q/W/E/R for evaluation (empty for AA).

    Raises ``ValueError`` on unrecognized tokens - callers should validate
    the full sequence up front.
    """
    t = (token or "").strip().upper()
    if not t:
        raise ValueError("combo token cannot be empty")
    if t == "AA":
        return ("AA", "", False)
    if t in _SPELL_KEYS:
        return (t, t, True)
    if len(t) == 2 and t[0] in _SPELL_KEYS and t[1] in _REPEAT_SUFFIXES:
        return (t, t[0], True)
    raise ValueError(
        f"unknown combo token {token!r}; expected one of AA / P / Q / W / E / R "
        f"or a repeat variant (Q2, W2, E2, R2)"
    )


def _validate_combo_sequence(sequence: Sequence[str]) -> tuple[str, ...]:
    """Validate every token in the sequence; return a normalized tuple."""
    if not sequence:
        raise ValueError("combo_sequence cannot be empty")
    norm: list[str] = []
    for tok in sequence:
        canonical, _, _ = _normalize_combo_token(tok)
        norm.append(canonical)
    return tuple(norm)


# --- per-cast result row -----------------------------------------------------


@dataclass(frozen=True)
class ComboCast:
    """One step in the resolved combo sequence.

    ``raw_damage`` is the un-amped, pre-mitigation damage. The "post_*"
    fields apply mode multiplier, build-wide amps, and mitigation in
    order. ``final_damage`` is the contribution to ``total_burst_damage``.

    For ``token == "AA"``, ``ability_key`` is empty, ``form_name`` is
    ``"Auto"``, ``rank`` is ``-1``, and the damage carries the
    per-hit ``avg_attack_dmg`` from ``compute_dps`` (already
    post-armor + mode).
    """
    token: str                          # "Q" | "AA" | "Q2" | etc.
    is_ability: bool
    ability_key: str                    # "P" | "Q" | "W" | "E" | "R" | ""
    form_name: str
    form_index: int
    rank: int                           # -1 for AA or locked spells
    cooldown: float
    cost: float
    damage_type: str | None
    raw_damage: float                   # pre-mode, pre-amps, pre-mit
    post_mode_damage: float             # x mode_multiplier
    post_amps_damage: float             # x build_amp x magic_amp
    final_damage: float                 # x mitigation_factor (contributes to total)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "is_ability": self.is_ability,
            "ability_key": self.ability_key,
            "form_name": self.form_name,
            "form_index": self.form_index,
            "rank": self.rank,
            "cooldown": self.cooldown,
            "cost": self.cost,
            "damage_type": self.damage_type,
            "raw_damage": self.raw_damage,
            "post_mode_damage": self.post_mode_damage,
            "post_amps_damage": self.post_amps_damage,
            "final_damage": self.final_damage,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class BurstResult:
    """Top-level result from ``compute_burst_damage``.

    ``total_burst_damage`` is the sum of ``per_cast[].final_damage``.
    ``ability_damage`` and ``auto_attack_damage`` partition that total
    for at-a-glance ratio inspection (assassin ranking decisions often
    pivot on ability:AA balance).
    """
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    target_current_hp_pct: float
    mode_multiplier: float                          # aramDamageDealt; 1.0 outside ARAM
    combo_sequence: tuple[str, ...]
    per_cast: tuple[ComboCast, ...]
    total_burst_damage: float
    ability_damage: float
    auto_attack_damage: float
    primary_scaling: str                            # "AP" | "AD" | "HP" | "MIXED" | "TRUE"
    max_priority: tuple[str, str, str]
    block_strategy: str
    target_armor_after_pen: float
    target_mr_after_pen: float
    max_priority_source: str = "default"            # "override" | "champion" | "default"
    combo_sequence_source: str = "default"          # "override" | "champion" | "default"
    form_index_source: str = "default"              # "override" | "champion" | "default"
    form_index_resolved: dict[str, int] = field(default_factory=dict)
    block_index_source: str = "default"             # "override" | "champion" | "default"
    block_index_resolved: "dict[str, int | list[int] | dict[str, int | list[int]]]" = field(default_factory=dict)
    # Phase 5.7 (s189, 2026-05-13) - Spellblade contribution within the
    # combo. ``spellblade_procs`` counts how many ability-then-AA
    # transitions actually fired a Spellblade proc; ``spellblade_damage``
    # is the cumulative damage from those procs (already in
    # ``auto_attack_damage`` / ``total_burst_damage`` for the AA rows
    # that consumed them). ``spellblade_item_name`` is the build's active
    # Spellblade item (informational; "" when no Spellblade in build).
    spellblade_procs: int = 0
    spellblade_damage: float = 0.0
    spellblade_item_name: str = ""
    # Phase 5.8 (s190, 2026-05-13) - Lightshield Strike (Sundered Sky)
    # contribution within the combo. Capped at 1 proc per combo because
    # the 8s real CD doesn't allow re-arming in a typical burst window.
    # ``lightshield_strike_damage`` is already folded into
    # ``auto_attack_damage`` / ``total_burst_damage``.
    lightshield_strike_procs: int = 0
    lightshield_strike_damage: float = 0.0
    lightshield_strike_item_name: str = ""
    # DS V2 S3 (2026-05-31) - net rune-proc burst from the optional
    # ``runes`` param (on_proc_burst + per_attack + stacking_amp burst
    # pieces; Conqueror adaptive force is EXCLUDED). Already folded into
    # ``total_burst_damage`` when runes were supplied; 0.0 by default so
    # the no-runes path is byte-identical.
    rune_proc_damage: float = 0.0
    # DSV2 (2026-06-15) - takedown / kill-state OFFENSE seam (assume_takedown).
    # ``takedown_bonus_ad`` is the Hubris Eminence bonus AD folded into the
    # build's bonus AD (already reflected in ability_damage + auto_attack_damage
    # when > 0). ``execute_finisher_damage`` is the Collector kill-state execute
    # credit (5% target max HP true damage), already folded into
    # ``total_burst_damage``. Both 0.0 by default so the assume_takedown=False
    # path is byte-identical - same convention as ``rune_proc_damage``.
    takedown_bonus_ad: float = 0.0
    execute_finisher_damage: float = 0.0
    stats: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "target_current_hp_pct": self.target_current_hp_pct,
            "mode_multiplier": self.mode_multiplier,
            "combo_sequence": list(self.combo_sequence),
            "per_cast": [c.to_dict() for c in self.per_cast],
            "total_burst_damage": self.total_burst_damage,
            "ability_damage": self.ability_damage,
            "auto_attack_damage": self.auto_attack_damage,
            "primary_scaling": self.primary_scaling,
            "max_priority": list(self.max_priority),
            "max_priority_source": self.max_priority_source,
            "block_strategy": self.block_strategy,
            "target_armor_after_pen": self.target_armor_after_pen,
            "target_mr_after_pen": self.target_mr_after_pen,
            "combo_sequence_source": self.combo_sequence_source,
            "form_index_source": self.form_index_source,
            "form_index_resolved": dict(self.form_index_resolved),
            "block_index_source": self.block_index_source,
            "block_index_resolved": dict(self.block_index_resolved),
            "spellblade_procs": self.spellblade_procs,
            "spellblade_damage": self.spellblade_damage,
            "spellblade_item_name": self.spellblade_item_name,
            "lightshield_strike_procs": self.lightshield_strike_procs,
            "lightshield_strike_damage": self.lightshield_strike_damage,
            "lightshield_strike_item_name": self.lightshield_strike_item_name,
            "rune_proc_damage": self.rune_proc_damage,
            "takedown_bonus_ad": self.takedown_bonus_ad,
            "execute_finisher_damage": self.execute_finisher_damage,
            "stats": dict(self.stats),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [ASSASSIN]"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}({self.target_armor_after_pen:.0f} eff)"
            f"  mr={self.target_mr:.0f}({self.target_mr_after_pen:.0f} eff)"
            f"  max_hp={self.target_max_hp:.0f}"
            f"  current_hp_pct={self.target_current_hp_pct * 100:.0f}%"
        )
        rows.append(
            f"priority: {'>'.join(self.max_priority)}  "
            f"block: {self.block_strategy}  primary_scaling: {self.primary_scaling}"
        )
        rows.append(f"combo: {' -> '.join(self.combo_sequence)}")
        rows.append("")
        rows.append(
            f"  {'step':<6}  {'rank':>4}  {'type':>8}  {'raw':>7}  "
            f"{'+mode':>7}  {'+amps':>7}  {'final':>7}"
        )
        rows.append("  " + "-" * 60)
        for c in self.per_cast:
            rank_label = f"{c.rank}" if c.rank >= 0 else "-"
            dt_label = (c.damage_type or "-")[:8]
            rows.append(
                f"  {c.token:<6}  {rank_label:>4}  {dt_label:>8}  "
                f"{c.raw_damage:>7.1f}  {c.post_mode_damage:>7.1f}  "
                f"{c.post_amps_damage:>7.1f}  {c.final_damage:>7.1f}"
            )
        rows.append("")
        rows.append(f"  ability_damage     {self.ability_damage:.2f}")
        rows.append(f"  auto_attack_damage {self.auto_attack_damage:.2f}")
        rows.append(f"  total_burst_damage {self.total_burst_damage:.2f}")
        if self.target_max_hp > 0:
            kill_pct = 100.0 * self.total_burst_damage / self.target_max_hp
            rows.append(f"  target_kill_pct    {kill_pct:.1f}%  (vs {self.target_max_hp:.0f} max HP)")
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


# --- top-level compute -------------------------------------------------------


def compute_burst_damage(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    augments: Optional[Iterable] = None,
    abilities_snapshot: Optional[AbilitiesSnapshot] = None,
    max_priority: Optional[Sequence[str]] = None,
    block_strategy: str = "first",
    form_index_overrides: Optional[dict[str, int]] = None,
    block_index_overrides: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
    combo_sequence: Optional[Sequence[str]] = None,
    runes: Optional[Sequence[int]] = None,
    caster_hp_pct: float = 1.0,
    game_time_s: float = 0.0,
    aoe_targets_hit: int = 1,
    assume_takedown: bool = False,
    assume_ability_amp: bool = False,
    assume_magic_burst: bool = False,
    score_completion_runes: bool = False,
    assume_ally_detonation: bool = False,
    assume_passive_reflect: bool = False,
) -> BurstResult:
    """Compute one-combo total burst damage for the resolved build.

    Mirror of ``compute_ability_dps``'s contract - same ``snapshot``,
    ``mode``, ``target_*``, ``augments``, and ability-resolution plumbing -
    but the result decomposes by combo step (one row per token in
    ``combo_sequence``) instead of by spell key. ``target_current_hp_pct``
    pin lets the caller assume the cast lands at a specific HP-band, which
    drives ``target_missing_hp_pct`` / ``target_current_hp_pct`` scaling
    fields (Zed R execute, Kha'Zix isolated Q bonus when modeled later).

    ``max_priority`` defaults to the per-champion override from
    ``champion_max_priority.json`` via ``_resolve_max_priority`` - Phase 4d
    (s185). Operator can override explicitly per call.

    ``combo_sequence`` defaults to the per-champion override from
    ``champion_combo_sequences.json`` via ``_resolve_combo_sequence`` -
    Phase 5.5 (s186). Zed's shadow Q2, Yone's Q1-Q2-Q3 chain, and Akali's
    R-recast all live in the registry so /rank-assassin scores their burst
    accurately by default.

    Auto-attack hits in the combo contribute the build's per-hit
    ``avg_attack_dmg`` from ``compute_dps`` - that's post-armor and
    post-mode-multiplier, no on-hit periodic procs (see module docstring
    "Phase 5 deliberate omissions"). For 14 of 15 canonical assassins
    (Zed/Talon/Akali/Kha'Zix/Rengar/Fizz/Diana/Kassadin/Katarina/LeBlanc/
    Qiyana/Pyke/Naafiri/Briar/Yone), this captures the lethality-driven
    burst correctly because lethality flows through ``effective_target_armor``
    for both the ability and the AA hits.

    ``assume_takedown`` (DSV2, 2026-06-15): the takedown / kill-state OFFENSE
    seam. Default False -> byte-identical. When True: (1) Hubris Eminence bonus
    AD (15 + 2 * ``_ASSUMED_TAKEDOWN_STACKS``) raises both the AA per-hit and the
    AD-ratio ability damage; (2) the Collector execute is credited as a
    kill-state finisher of 5% target max HP TRUE damage (``execute_finisher_damage``,
    folded into ``total_burst_damage``) when a ``target_max_hp`` is supplied.
    Death's Dance contributes nothing on this axis - its takedown payoff is the
    Defy heal, valued on the survivability axis (ehp.py, ENGINE 1.57.0).

    ``score_completion_runes`` (DSP4, 1.130.0): the self-rune completion seam.
    Default False -> byte-identical. The completion runes (``COMPLETION_RUNE_IDS``,
    e.g. Shield Bash 8401) are in RUNE_PROCS but SKIPPED by the rune layer unless
    this is True, so a supplied ``runes`` set that includes a completion rune
    stays byte-identical to the pre-DSP4 engine. When True they contribute
    (Shield Bash's 5-30 + 2.5% bonus HP shield-proc floor). The live default-ON
    flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.
    """
    if block_strategy not in {"first", "sum", "max"}:
        raise ValueError(
            f"block_strategy must be one of first|sum|max, got {block_strategy!r}"
        )
    max_priority, max_priority_source = _resolve_max_priority(champion_id, max_priority)
    form_index_overrides, form_index_source = _resolve_form_index_overrides(
        champion_id, form_index_overrides,
    )
    block_index_overrides, block_index_source = _resolve_block_index_overrides(
        champion_id, block_index_overrides,
    )
    if not 0.0 <= target_current_hp_pct <= 1.0:
        raise ValueError(
            f"target_current_hp_pct must be in [0,1], got {target_current_hp_pct}"
        )
    combo_norm, combo_source = _resolve_combo_sequence(champion_id, combo_sequence)

    level = clamp_level(level)

    # Load abilities snapshot lazily - same pattern as compute_ability_dps.
    abil_snap = abilities_snapshot
    if abil_snap is None:
        from .abilities import load_default  # noqa: PLC0415 - local import keeps tests fast
        try:
            abil_snap = load_default()
        except AbilitiesNotFound as e:
            return _empty_burst(
                snapshot, champion_id, level, item_ids, mode,
                target_armor, target_mr, target_max_hp, target_bonus_hp,
                target_current_hp_pct, combo_norm,
                max_priority, block_strategy,
                max_priority_source=max_priority_source,
                combo_sequence_source=combo_source,
                form_index_source=form_index_source,
                form_index_resolved=form_index_overrides,
                block_index_source=block_index_source,
                block_index_resolved=block_index_overrides,
                note=f"abilities snapshot missing: {e}",
            )

    # Resolve the build once. Reused for ability stats AND the AA per-hit
    # damage probe via compute_dps below. Two engine passes per call - same
    # cost shape as Phase 4b's compute_ability_dps.
    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments,
    )

    champ_rec = snapshot.champion(resolved.champion_id)
    aram = ((champ_rec.get("lolmath") or {}).get("aram_modifiers") or {})
    mode_mult = 1.0
    if mode == "ARAM":
        mode_mult = float(aram.get("aramDamageDealt", 1.0))

    # Auto-attack per-hit probe. Calling compute_dps with the same build
    # gives us the canonical ``avg_attack_dmg`` (per-hit, post-armor +
    # mode) that the rest of the engine treats as the AA contribution.
    # Note: this picks up the same effective_target_armor (lethality
    # included) as the ability mitigation pipeline below - assassin
    # rankings stay internally consistent.
    aa_probe = compute_dps(
        snapshot, champion_id=resolved.champion_id, level=level,
        item_ids=resolved.item_ids, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        augments=augments,
        # DSV2: the AA per-hit (avg_attack_dmg) picks up Hubris Eminence's
        # bonus AD when the kill-state seam is ON. Byte-identical when OFF.
        assume_takedown=assume_takedown,
    )
    aa_base_per_hit = max(0.0, float(aa_probe.avg_attack_dmg))
    # Phase 5.6 (s188, 2026-05-13): on-hit proc contribution per AA -
    # Wit's End +magic, BotRK Mist's Edge HP%, Statikk Shiv stacks etc.
    # Amortized per-AA from compute_dps so the burst scorer doesn't need
    # to re-derive call_ctx / item_effects.
    aa_on_hit_per_hit = max(0.0, float(aa_probe.per_attack_on_hit_damage))
    aa_per_hit = aa_base_per_hit + aa_on_hit_per_hit
    # Phase 5.7 (s189, 2026-05-13): Spellblade per-proc damage. Spellblade
    # is the canonical "next basic after spell cast" mechanic shared by
    # eight items (Trinity Force / Lich Bane / Essence Reaver / Iceborn
    # Gauntlet / Dusk+Dawn / Divine Sunderer / Sheen / Bloodsong). Unlike
    # per_attack on-hit, Spellblade fires per ability-then-AA transition,
    # not per AA. The combo walker below tracks ``spellblade_armed`` and
    # consumes the proc on each AA that follows an ability cast. In-game
    # 1.5s internal CD is irrelevant in a single burst window because
    # the "armed by new spell cast" gate is the binding constraint.
    aa_spellblade_per_proc = max(0.0, float(aa_probe.spellblade_per_proc_damage))
    aa_spellblade_name = aa_probe.spellblade_item_name or ""
    # Phase 5.8 (s190, 2026-05-13): Lightshield Strike per-proc damage -
    # Sundered Sky's distinct arm-consume proc (own ``unique_passive_key``-
    # less family, 8s CD, no dedup with spellblade). Same arm-on-cast /
    # consume-on-AA model as Spellblade but capped at 1 proc per combo
    # because the 8s real CD greatly exceeds typical burst window. A build
    # with both Sundered Sky + a Spellblade item gets BOTH procs on the
    # same AA (independent state machines).
    aa_lightshield_per_proc = max(0.0, float(aa_probe.lightshield_strike_per_proc_damage))
    aa_lightshield_name = aa_probe.lightshield_strike_item_name or ""

    # Build ability context (post-AP-amp). Same precedence as
    # compute_ability_dps: ap += hp + stacked; ap *= rab; ap *= demonic.
    ctx = AbilityContext.from_build(
        stats=resolved.stats,
        base_stats=resolved.base_stats,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
    )

    item_effects = collect_effects(resolved.item_ids)
    ap_from_hp = total_bonus_ap_from_hp(item_effects, ctx.caster_bonus_hp)
    stacked_ap = total_stacked_ap(item_effects)
    ap_total = ctx.ap + ap_from_hp + stacked_ap
    ap_amp = total_ap_amp_multiplier(item_effects)
    if ap_amp != 1.0:
        ap_total *= ap_amp
    hp_ap_amp = total_caster_hp_scaled_ap_amp(item_effects, ctx.caster_max_hp)
    if hp_ap_amp != 1.0:
        ap_total *= hp_ap_amp
    ctx = replace(ctx, ap=ap_total)

    # DSV2 (1.125.0): takedown / kill-state OFFENSE seam. assume_takedown=False
    # -> takedown_bonus_ad stays 0.0, ctx unchanged, every line below is
    # byte-identical. When True, Hubris Eminence's bonus AD folds into the
    # ability scaling context so AD-ratio abilities (Talon/Zed/Pyke) reflect
    # the post-takedown power; the AA per-hit already picked it up via aa_probe.
    takedown_bonus_ad = 0.0
    if assume_takedown:
        takedown_bonus_ad = total_takedown_bonus_ad(
            item_effects, _ASSUMED_TAKEDOWN_STACKS
        )
        if takedown_bonus_ad:
            ctx = replace(ctx, bonus_ad=ctx.bonus_ad + takedown_bonus_ad)

    # Build-wide damage amps and target-conditional amps.
    damage_amp = total_damage_amp_multiplier(item_effects)
    damage_amp *= total_target_bonus_hp_amp_multiplier(item_effects, target_bonus_hp)
    damage_amp *= total_giant_slayer_multiplier(
        item_effects, target_max_hp, ctx.caster_max_hp,
    )
    magic_amp = total_magic_amp_multiplier(item_effects)

    # Effective resists - lethality flows through here.
    target_armor_eff = effective_target_armor(target_armor, item_effects, level)
    target_mr_eff = effective_target_mr(target_mr, item_effects)

    # Resolve forms.
    if not abil_snap.has_champion(resolved.champion_id):
        return _empty_burst(
            snapshot, resolved.champion_id, level, item_ids, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp,
            target_current_hp_pct, combo_norm,
            max_priority, block_strategy,
            max_priority_source=max_priority_source,
            combo_sequence_source=combo_source,
            form_index_source=form_index_source,
            form_index_resolved=form_index_overrides,
            block_index_source=block_index_source,
            block_index_resolved=block_index_overrides,
            champion_name=resolved.champion_name,
            note=f"champion {resolved.champion_id!r} absent from abilities snapshot",
        )
    per_key_forms = abil_snap.get_abilities(resolved.champion_id)
    overrides = form_index_overrides or {}
    block_overrides = block_index_overrides or {}

    per_cast: list[ComboCast] = []
    forms_for_classification: list[AbilityForm] = []
    seen_keys: set[str] = set()
    # Phase 5.7 (s189, 2026-05-13) - Spellblade arming state. Set True by
    # any ability cast (P/Q/W/E/R or repeat variant); consumed by the
    # next AA which adds the proc damage and resets to False. Tracked
    # separately so the BurstResult can surface the total proc count.
    spellblade_armed = False
    spellblade_procs_fired = 0
    spellblade_damage_total = 0.0
    # Phase 5.8 (s190, 2026-05-13) - Lightshield Strike arming state.
    # Same arm-consume pattern as Spellblade but capped at 1 proc per
    # combo (Sundered Sky's 8s real CD vs typical 2-3s combo window).
    # Re-arming guarded by ``lightshield_procs_fired == 0`` so once the
    # proc lands, subsequent ability casts can't re-arm within the same
    # combo. Independent of Spellblade state - a build with Sundered Sky
    # + Trinity Force lands BOTH procs on the AA following the first
    # ability cast.
    lightshield_armed = False
    lightshield_procs_fired = 0
    lightshield_damage_total = 0.0
    for token in combo_norm:
        canonical, ability_key, is_ability = _normalize_combo_token(token)
        if not is_ability:
            # AA contributes raw per-hit damage from compute_dps. The
            # avg_attack_dmg is already post-armor+mode; classify as
            # PHYSICAL for the per-cast row. Don't re-apply mode_mult
            # or armor_factor - compute_dps did that already. Spellblade
            # (Phase 5.7, s189) fires once per ability-then-AA transition.
            # Lightshield Strike (Phase 5.8, s190) fires once per combo
            # max - both procs can stack on the same AA when the build
            # carries both items.
            aa_spellblade_added = 0.0
            if spellblade_armed and aa_spellblade_per_proc > 0:
                aa_spellblade_added = aa_spellblade_per_proc
                spellblade_armed = False
                spellblade_procs_fired += 1
                spellblade_damage_total += aa_spellblade_added
            aa_lightshield_added = 0.0
            if lightshield_armed and aa_lightshield_per_proc > 0:
                aa_lightshield_added = aa_lightshield_per_proc
                lightshield_armed = False
                lightshield_procs_fired += 1
                lightshield_damage_total += aa_lightshield_added
            aa_total_damage = aa_per_hit + aa_spellblade_added + aa_lightshield_added
            note_parts: list[str] = [
                f"auto-attack: base {aa_base_per_hit:.1f} + on-hit "
                f"{aa_on_hit_per_hit:.1f}"
            ]
            if aa_spellblade_added > 0:
                note_parts.append(
                    f"+ Spellblade ({aa_spellblade_name}) "
                    f"{aa_spellblade_added:.1f}"
                )
            if aa_lightshield_added > 0:
                note_parts.append(
                    f"+ Lightshield Strike ({aa_lightshield_name}) "
                    f"{aa_lightshield_added:.1f}"
                )
            note_parts.append(f"= {aa_total_damage:.1f}")
            aa_note = " ".join(note_parts)
            per_cast.append(ComboCast(
                token=canonical,
                is_ability=False,
                ability_key="",
                form_name="Auto",
                form_index=-1,
                rank=-1,
                cooldown=0.0,
                cost=0.0,
                damage_type="PHYSICAL",
                raw_damage=aa_total_damage,
                post_mode_damage=aa_total_damage,
                post_amps_damage=aa_total_damage,
                final_damage=aa_total_damage,
                notes=(aa_note,),
            ))
            continue

        # Ability cast - arm Spellblade for the next AA. Subsequent
        # ability casts before the next AA leave it armed (still True).
        spellblade_armed = True
        # Arm Lightshield Strike only if it hasn't fired yet in the
        # combo - the 8s real CD doesn't permit re-arming within a
        # single burst window.
        if lightshield_procs_fired == 0:
            lightshield_armed = True

        forms = per_key_forms.get(ability_key, ())
        if not forms:
            per_cast.append(_zero_cast(
                canonical, ability_key, "missing", -1,
                notes=(f"no {ability_key} ability recorded for "
                       f"{resolved.champion_id} - skipped",),
            ))
            continue
        form_idx = overrides.get(ability_key, 0)
        if form_idx < 0 or form_idx >= len(forms):
            form_idx = 0
        form = forms[form_idx]
        if ability_key not in seen_keys:
            forms_for_classification.append(form)
            seen_keys.add(ability_key)
        rank = rank_at_level(ability_key, level, max_priority=max_priority)
        if rank < 0:
            per_cast.append(_zero_cast(
                canonical, ability_key, form.name, form_idx,
                notes=(f"{ability_key} locked at level {level}",),
            ))
            continue
        # Phase 5.9.19 (s206): inherit form 0 CD when non-form-0 has None.
        fallback = forms[0] if form_idx != 0 else None
        cooldown = _form_cooldown_at_rank(form, rank, fallback_form=fallback)
        cost = _form_cost_at_rank(form, rank)
        # Phase 5.9 (s191) + Phase 5.9.5 (s192): per-(champion, key)
        # block_index override switches to "indexed" strategy for this key;
        # otherwise honor the global block_strategy. Token-canonical lookup
        # (e.g. "R2") wins over base-key lookup (e.g. "R"), so a champion
        # like Akali can model R1 -> block 0 (base) and R2 -> block 2
        # (max-execute scaling) within the same combo.
        if canonical in block_overrides:
            raw = _select_blocks(
                form.damage_blocks, rank, ctx, "indexed",
                block_index=block_overrides[canonical],
            )
        elif ability_key in block_overrides:
            raw = _select_blocks(
                form.damage_blocks, rank, ctx, "indexed",
                block_index=block_overrides[ability_key],
            )
        else:
            raw = _select_blocks(form.damage_blocks, rank, ctx, block_strategy)
        post_mode = raw * mode_mult
        dt = (form.damage_type or "MAGIC").upper()
        spell_magic_amp = magic_amp if dt == "MAGIC" else 1.0
        post_amps = post_mode * damage_amp * spell_magic_amp
        mit = _mitigation_factor(form.damage_type, target_armor_eff, target_mr_eff)
        final = post_amps * mit
        # item 232 - geometry-aware AoE scaling. Byte-identical at the default
        # single-target aoe_targets_hit=1 (the guard skips the call entirely;
        # spell_aoe_multiplier would also return 1.0). An AoE-shaped ability
        # (line/cone/circle per the cdragon geometry sidecar) hitting N targets
        # in a teamfight deals ~N x its single-target damage, capped at the
        # team size; point/self-cast spells stay x1.
        if aoe_targets_hit > 1:
            final *= spell_aoe_multiplier(
                snapshot, champion_id, ability_key, aoe_targets_hit
            )
        per_cast.append(ComboCast(
            token=canonical,
            is_ability=True,
            ability_key=ability_key,
            form_name=form.name,
            form_index=form_idx,
            rank=rank,
            cooldown=cooldown,
            cost=cost,
            damage_type=form.damage_type,
            raw_damage=raw,
            post_mode_damage=post_mode,
            post_amps_damage=post_amps,
            final_damage=final,
        ))

    ability_total = sum(c.final_damage for c in per_cast if c.is_ability)
    aa_total = sum(c.final_damage for c in per_cast if not c.is_ability)
    # DSV4 (1.127.0): Spear of Shojin Focused Will ability/passive amp seam.
    # assume_ability_amp=False -> ability_amp_bonus stays 0.0, total_burst is the
    # plain sum (byte-identical). When True, Focused Will's per-stack amp (3%/
    # stack, 4 stacks = 12%) multiplies ONLY ability_total (Focused Will amps
    # abilities/passives, never auto-attacks - aa_total is untouched). Applied
    # before the rune + execute layers so they build on the amped base; the
    # result's ``ability_damage`` mirrors the amped value.
    if assume_ability_amp:
        ability_amp_bonus = total_ability_damage_amp(
            item_effects, _ASSUMED_ABILITY_AMP_STACKS
        )
        if ability_amp_bonus > 0.0:
            ability_total *= 1.0 + ability_amp_bonus
    total_burst = ability_total + aa_total

    # DS V2 S3 - optional rune-proc layer. Byte-identical when ``runes`` is
    # falsy (rune_proc_damage stays 0.0, total_burst is the line above). On
    # supplied runes: (1) sum the per-proc burst piece across on_proc_burst /
    # per_attack / stacking_amp runes (Conqueror's adaptive STAT force is
    # excluded - it is not a flat damage); (2) apply each rune's keystone amp
    # to the ability+AA base (PtA 1.08; non-amp runes pass through unchanged);
    # (3) total = amped base + proc burst. Caster scaling: adaptive AD on
    # rune_procs is BONUS AD (ctx.bonus_ad); AP is the final amplified AP.
    rune_proc_damage = 0.0
    # DSP4 (1.130.0) self-rune completion seam. score_completion_runes default
    # False filters the completion runes (COMPLETION_RUNE_IDS, e.g. Shield Bash
    # 8401) OUT of the scored set -> byte-identical to the pre-DSP4 engine for
    # any supplied rune set. ON -> they are scored. The pre-DSP4 runes are never
    # members, so they are always consumed. The live default-ON flip is
    # operator-gated (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.
    _scored_runes: list = []
    if runes:
        _scored_runes = [
            _rid for _rid in runes
            if score_completion_runes or _rid not in COMPLETION_RUNE_IDS
        ]
    if _scored_runes:
        # item 233 - role from attackrange feeds per_attack rune scaling (Lethal
        # Tempo melee 9-30 vs ranged 6-24). Only changes an explicit runes=[8008]
        # call on a ranged champ; the live default passes no runes so /rank is
        # unaffected. target_current_hp_pct threads through for forward-compat
        # (the amp registry's target_hp tags are metadata - keystone_amp applies
        # them unconditionally for the burst-window approximation).
        _attack_range = float(
            snapshot.champion(champion_id).get("stats", {}).get("attackrange", 0.0)
        )
        _caster_role = "ranged" if _attack_range > _RANGED_ATTACK_RANGE else "melee"
        for _rid in _scored_runes:
            proc = RUNE_PROCS.get(_rid)
            if proc is None or proc.proc_type == "adaptive":
                continue
            rune_proc_damage += compute_rune_proc_damage(
                _rid,
                level,
                ad=ctx.bonus_ad,
                ap=ap_total,
                bonus_hp=ctx.caster_bonus_hp,
                target_max_hp=target_max_hp,
                mode=mode,
                caster_hp_pct=caster_hp_pct,
                game_time_s=game_time_s,
                role=_caster_role,
                target_hp_pct=target_current_hp_pct,
            )
        amped_base = total_burst
        for _rid in _scored_runes:
            amped_base = keystone_amp(
                _rid, amped_base,
                caster_hp_pct=caster_hp_pct, game_time_s=game_time_s,
                role=_caster_role, target_hp_pct=target_current_hp_pct,
            )
        total_burst = amped_base + rune_proc_damage

    # DSV2 (1.125.0): Collector kill-state execute finisher. assume_takedown=
    # False -> execute_finisher_damage stays 0.0, total_burst unchanged. When
    # True AND a target max HP is supplied, credit the execute (5% target max
    # HP, TRUE damage - the execute ignores resists) as the finisher's worth in
    # its trigger window. Needs target_max_hp to size the 5%; with no HP signal
    # the execute can't be valued. Applied on top of the rune layer (a finisher
    # after the combo + rune procs). compute_dps deliberately does NOT credit
    # this - a one-shot execute is not sustained DPS.
    execute_finisher_damage = 0.0
    if assume_takedown and target_max_hp > 0:
        execute_pct = total_execute_max_hp_pct(item_effects)
        if execute_pct > 0:
            execute_finisher_damage = execute_pct * target_max_hp
            total_burst += execute_finisher_damage

    # DSV6 (1.152.0): on-cast magic-burst seam. assume_magic_burst=False ->
    # magic_burst_damage stays 0.0, total_burst unchanged (byte-identical). When
    # True, the item on-cast magic procs the per-cast combo loop never credited
    # (Luden's Echo, Stormsurge Squall, Malignance Hatefog) land once in the
    # burst window: pre-mit magic = sum(base + ap_ratio * ap_total) across items,
    # MR-mitigated (magic routing) + mode_mult + magic_amp - same mitigation +
    # amp shape the periodic layer applies to these exact procs in the DPS
    # scorer. Added after the rune + execute layers so keystone amps don't
    # double-amp an item proc. compute_ability_dps already counts these via
    # their PeriodicProc, so this seam only lifts the BURST scorer.
    magic_burst_damage = 0.0
    if assume_magic_burst:
        magic_burst_raw = total_magic_burst_damage(item_effects, ap_total)
        if magic_burst_raw > 0.0:
            magic_burst_mit = _mitigation_factor(
                "MAGIC", target_armor_eff, target_mr_eff
            )
            magic_burst_damage = magic_burst_raw * mode_mult * magic_amp * magic_burst_mit
            total_burst += magic_burst_damage

    # R41 (1.156.0): ally mark-detonation seam. assume_ally_detonation=False ->
    # ally_detonation_damage stays 0.0, total_burst unchanged (byte-identical).
    # When True, a champion whose mark an ALLY consumes for bonus damage (Leona P
    # Sunlight) is credited one detonation event landing in the burst window:
    # pre-mit per-event magic (ally_detonation_burst_raw), MR-mitigated (magic
    # routing) + mode_mult + magic_amp, x the assumed ally proc rate. An unmarked
    # champion contributes 0 even with the flag on. compute_dps's AA-probe call
    # above leaves the seam OFF, so the detonation is credited once here (no
    # double-count). The live default-ON flip is operator-gated
    # (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.
    ally_detonation_damage = 0.0
    if assume_ally_detonation:
        from ._ally_detonation_overrides import (
            _ASSUMED_ALLY_DETONATION_PROB,
            ally_detonation_burst_raw,
        )

        det_target_current_hp = target_max_hp * target_current_hp_pct
        det_raw = ally_detonation_burst_raw(
            resolved.champion_id, level, resolved.item_ids, det_target_current_hp
        )
        if det_raw > 0.0:
            det_mit = _mitigation_factor("MAGIC", target_armor_eff, target_mr_eff)
            ally_detonation_damage = (
                det_raw * mode_mult * magic_amp * det_mit
                * _ASSUMED_ALLY_DETONATION_PROB
            )
            total_burst += ally_detonation_damage

    # R49 (1.161.0): Rammus-style on-being-hit reflect seam (burst).
    # assume_passive_reflect=False -> reflect_burst_damage stays 0.0, total_burst
    # unchanged (byte-identical). When True, a champion with a registered reflect
    # (Rammus W Defensive Ball Curl) is credited the reflect procs landing in the
    # burst exposure window: per-proc magnitude (flat + % of the caster's TOTAL
    # armor + % of TOTAL MR), MR-mitigated (MAGIC routing) + mode_mult + magic_amp,
    # x the assumed incoming-attack count over the window
    # (_ASSUMED_REFLECT_BURST_WINDOW_S / reflect_cadence_s). compute_dps's AA-probe
    # call above leaves the seam OFF, so the reflect is credited once here (no
    # double-count). Live default-ON flip operator-gated (docs/LIVE_GAME_GATED_SYNC.md).
    reflect_burst_damage = 0.0
    if assume_passive_reflect:
        from ._passive_reflect_overrides import (
            _ASSUMED_REFLECT_BURST_WINDOW_S,
            reflect_entry,
            reflect_per_proc,
        )

        _rentry = reflect_entry(resolved.champion_id)
        if _rentry is not None:
            _rproc = reflect_per_proc(
                _rentry,
                caster_total_armor=float(resolved.stats.get("armor", 0.0)),
                caster_total_mr=float(resolved.stats.get("mr", 0.0)),
            )
            if _rproc > 0.0:
                _rmit = _mitigation_factor(
                    _rentry.damage_type, target_armor_eff, target_mr_eff
                )
                _ramp = magic_amp if _rentry.damage_type == "MAGIC" else 1.0
                _rcad = (
                    _rentry.reflect_cadence_s
                    if _rentry.reflect_cadence_s > 0.0
                    else 1.0
                )
                _rhits = _ASSUMED_REFLECT_BURST_WINDOW_S / _rcad
                reflect_burst_damage = _rproc * mode_mult * _ramp * _rmit * _rhits
                total_burst += reflect_burst_damage

    primary = _classify_primary_scaling(per_cast, forms_for_classification)

    notes: list[str] = list(resolved.notes)
    if ally_detonation_damage > 0.0:
        notes.append(
            f"ally-detonation +{ally_detonation_damage:.1f} burst "
            f"({resolved.champion_name} mark consumed by allies at "
            f"{_ASSUMED_ALLY_DETONATION_PROB:.0%} assumed proc rate; "
            "assume_ally_detonation seam)"
        )
    if reflect_burst_damage > 0.0:
        notes.append(
            f"on-being-hit reflect +{reflect_burst_damage:.1f} burst "
            f"({resolved.champion_name} returns magic to attackers over the "
            "assumed burst exposure window; assume_passive_reflect seam)"
        )
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(f"ARAM aramDamageDealt={mode_mult:.3f} on per-cast damage")
    if ap_amp != 1.0:
        notes.append(
            f"AP amplified x{ap_amp:.3f} by item amp (effective AP for ability "
            f"scaling: {ap_total:.1f})"
        )
    if hp_ap_amp != 1.0:
        notes.append(
            f"AP HP-scaled amp x{hp_ap_amp:.3f} (Demonic Embrace at "
            f"{ctx.caster_max_hp:.0f} HP)"
        )
    if ap_from_hp > 0:
        notes.append(
            f"AP cross-derived from bonus HP: +{ap_from_hp:.1f} "
            "(Riftmaker Void Infusion)"
        )
    if stacked_ap > 0:
        notes.append(f"Mejai's stacked AP: +{stacked_ap:.0f}")
    if damage_amp != 1.0:
        notes.append(
            f"build damage amp x{damage_amp:.3f} "
            f"(+{(damage_amp - 1.0) * 100:.1f}% to all ability damage)"
        )
    if magic_amp != 1.0:
        notes.append(
            f"magic damage amp x{magic_amp:.3f} on magic-typed spells "
            "(Abyssal Mask Unmake)"
        )
    if target_armor_eff != target_armor:
        notes.append(
            f"effective target armor {target_armor:.1f} -> {target_armor_eff:.1f} "
            "after reduction + lethality + % pen"
        )
    if target_mr_eff != target_mr:
        notes.append(
            f"effective target MR {target_mr:.1f} -> {target_mr_eff:.1f} "
            "after flat + % magic pen"
        )
    if aa_total > 0 and combo_norm.count("AA") > 0:
        breakdown = (
            f" (base {aa_base_per_hit:.1f} + on-hit {aa_on_hit_per_hit:.1f})"
            if aa_on_hit_per_hit > 0 else ""
        )
        notes.append(
            f"auto-attack contribution {aa_total:.1f} from "
            f"{combo_norm.count('AA')} AA x {aa_per_hit:.1f}/hit{breakdown}"
        )
    if spellblade_procs_fired > 0:
        notes.append(
            f"Spellblade ({aa_spellblade_name}) fired {spellblade_procs_fired}x "
            f"in combo for +{spellblade_damage_total:.1f} damage "
            f"(armed by spell-cast, consumed by next AA; "
            f"per-proc {aa_spellblade_per_proc:.1f})"
        )
    elif aa_spellblade_per_proc > 0:
        # Build has Spellblade but no AA followed a spell - surface so
        # operator can spot when the combo template doesn't exercise the
        # passive (e.g. a pure-AA sequence or AAs before any spell).
        notes.append(
            f"Spellblade ({aa_spellblade_name}) idle in combo - no AA "
            "followed an ability cast (per-proc value "
            f"{aa_spellblade_per_proc:.1f} unused)"
        )
    if lightshield_procs_fired > 0:
        notes.append(
            f"Lightshield Strike ({aa_lightshield_name}) fired "
            f"{lightshield_procs_fired}x in combo for "
            f"+{lightshield_damage_total:.1f} damage (Sundered Sky 8s "
            "CD - capped at 1 proc per combo; per-proc "
            f"{aa_lightshield_per_proc:.1f})"
        )
    elif aa_lightshield_per_proc > 0:
        notes.append(
            f"Lightshield Strike ({aa_lightshield_name}) idle in combo - "
            f"no AA followed an ability cast (per-proc value "
            f"{aa_lightshield_per_proc:.1f} unused)"
        )

    if block_overrides:
        notes.append(
            "block_index overrides applied: "
            + ", ".join(f"{k}={block_overrides[k]}" for k in sorted(block_overrides))
        )

    if runes:
        # Gate on `runes` (supplied?) not `_scored_runes` (post-filter): the
        # note fires byte-identically to the pre-DSP4 engine whenever a rune set
        # is supplied, even one wholly filtered to completion runes. _n still
        # counts over _scored_runes so a default-OFF completion rune reads as
        # "0 known rune(s)" with +0.0 - the exact pre-DSP4 string for a
        # then-unknown id. Scoring stays gated on _scored_runes above.
        _n = sum(1 for _r in _scored_runes if RUNE_PROCS.get(_r) is not None)
        notes.append(
            f"rune procs +{rune_proc_damage:.1f} ({_n} known rune(s)); "
            "keystone amp applied to ability+AA base"
        )

    if takedown_bonus_ad > 0:
        notes.append(
            f"takedown bonus AD +{takedown_bonus_ad:.0f} "
            f"(Hubris Eminence at {_ASSUMED_TAKEDOWN_STACKS} assumed stack(s)) "
            "raised ability+AA damage (assume_takedown kill-state seam)"
        )
    if execute_finisher_damage > 0:
        notes.append(
            f"Collector execute finisher +{execute_finisher_damage:.0f} true "
            f"(5% of {target_max_hp:.0f} target max HP, kill-state seam)"
        )
    if magic_burst_damage > 0:
        notes.append(
            f"magic on-cast burst +{magic_burst_damage:.0f} "
            f"(Luden's/Stormsurge/Malignance class item proc, assume_magic_burst seam)"
        )

    return BurstResult(
        champion_id=resolved.champion_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        mode_multiplier=mode_mult,
        combo_sequence=combo_norm,
        per_cast=tuple(per_cast),
        total_burst_damage=total_burst,
        ability_damage=ability_total,
        auto_attack_damage=aa_total,
        primary_scaling=primary,
        max_priority=tuple(max_priority),
        block_strategy=block_strategy,
        target_armor_after_pen=target_armor_eff,
        target_mr_after_pen=target_mr_eff,
        max_priority_source=max_priority_source,
        combo_sequence_source=combo_source,
        form_index_source=form_index_source,
        form_index_resolved=dict(form_index_overrides),
        block_index_source=block_index_source,
        block_index_resolved=dict(block_index_overrides),
        spellblade_procs=spellblade_procs_fired,
        spellblade_damage=spellblade_damage_total,
        spellblade_item_name=aa_spellblade_name,
        lightshield_strike_procs=lightshield_procs_fired,
        lightshield_strike_damage=lightshield_damage_total,
        lightshield_strike_item_name=aa_lightshield_name,
        rune_proc_damage=rune_proc_damage,
        takedown_bonus_ad=takedown_bonus_ad,
        execute_finisher_damage=execute_finisher_damage,
        stats=dict(resolved.stats),
        notes=tuple(notes),
    )


# --- helpers for empty / zero results ----------------------------------------


def _zero_cast(
    token: str,
    ability_key: str,
    form_name: str,
    form_index: int,
    notes: tuple[str, ...] = (),
) -> ComboCast:
    return ComboCast(
        token=token,
        is_ability=bool(ability_key),
        ability_key=ability_key,
        form_name=form_name,
        form_index=form_index,
        rank=-1,
        cooldown=0.0,
        cost=0.0,
        damage_type=None,
        raw_damage=0.0,
        post_mode_damage=0.0,
        post_amps_damage=0.0,
        final_damage=0.0,
        notes=notes,
    )


def _empty_burst(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]],
    mode: str,
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    target_current_hp_pct: float,
    combo_sequence: tuple[str, ...],
    max_priority: tuple[str, str, str],
    block_strategy: str,
    *,
    max_priority_source: str = "default",
    combo_sequence_source: str = "default",
    form_index_source: str = "default",
    form_index_resolved: Optional[dict[str, int]] = None,
    block_index_source: str = "default",
    block_index_resolved: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
    champion_name: str | None = None,
    note: str = "",
) -> BurstResult:
    name = champion_name or champion_id
    items = tuple(str(i) for i in (item_ids or ()))
    per_cast = tuple(
        _zero_cast(t, t if t != "AA" else "", "missing", -1,
                   notes=("ability data unavailable",))
        for t in combo_sequence
    )
    return BurstResult(
        champion_id=champion_id, champion_name=name, level=level,
        item_ids=items, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        mode_multiplier=1.0,
        combo_sequence=combo_sequence,
        per_cast=per_cast,
        total_burst_damage=0.0,
        ability_damage=0.0,
        auto_attack_damage=0.0,
        primary_scaling="MIXED",
        max_priority=tuple(max_priority),
        block_strategy=block_strategy,
        target_armor_after_pen=target_armor,
        target_mr_after_pen=target_mr,
        max_priority_source=max_priority_source,
        combo_sequence_source=combo_sequence_source,
        form_index_source=form_index_source,
        form_index_resolved=dict(form_index_resolved or {}),
        block_index_source=block_index_source,
        block_index_resolved=dict(block_index_resolved or {}),
        stats={},
        notes=(note,) if note else (),
    )


# --- ranker ------------------------------------------------------------------


@dataclass(frozen=True)
class BurstRankedItem:
    """Phase 5 sibling of ``RankedItem`` / ``EhpRankedItem`` /
    ``HybridRankedItem`` / ``AbilityDpsRankedItem``.

    ``delta_burst`` is the raw total-burst-damage gain over the baseline.
    ``burst_per_1k_gold`` zeroes out on regressions so the efficiency
    column doesn't mislead.
    """
    item_id: str
    item_name: str
    gold: int
    delta_burst: float
    new_burst: float
    burst_per_1k_gold: float
    is_terminal: bool
    tags: tuple[str, ...]
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): candidate's own unique-passive family key, always set
    # (collision-independent) - the positive "locks <family>" signal.
    unique_passive_key: str = ""
    # DSP11 Cluster-B2 kit-axis credit marker (1.135.0). 0.0 on the default path
    # (``prefer_kit_axis_by_win=False``) so the rows + sort stay byte-identical;
    # 1.0 on a surfaced (positive-delta) WIN-anchored kit-axis item when engaged.
    kit_axis_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_burst": self.delta_burst,
            "new_burst": self.new_burst,
            "burst_per_1k_gold": self.burst_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
            "kit_axis_score": self.kit_axis_score,
        }


@dataclass(frozen=True)
class BurstRankResult:
    """Phase 5 - output of ``rank_items_by_burst``."""
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_burst: float
    primary_scaling: str
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    target_current_hp_pct: float
    combo_sequence: tuple[str, ...]
    max_priority: tuple[str, str, str]
    max_priority_source: str              # "override" | "champion" | "default"
    combo_sequence_source: str            # "override" | "champion" | "default"
    form_index_source: str                # "override" | "champion" | "default"
    form_index_resolved: dict[str, int]   # merged map actually used
    block_index_source: str               # "override" | "champion" | "default"
    block_index_resolved: "dict[str, int | list[int] | dict[str, int | list[int]]]"  # merged (champion, key) -> block_index map
    block_strategy: str
    mode_multiplier: float
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int
    candidates_evaluated: int
    ranked: tuple[BurstRankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_burst": self.baseline_burst,
            "primary_scaling": self.primary_scaling,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "target_current_hp_pct": self.target_current_hp_pct,
            "combo_sequence": list(self.combo_sequence),
            "max_priority": list(self.max_priority),
            "max_priority_source": self.max_priority_source,
            "combo_sequence_source": self.combo_sequence_source,
            "form_index_source": self.form_index_source,
            "form_index_resolved": dict(self.form_index_resolved),
            "block_index_source": self.block_index_source,
            "block_index_resolved": dict(self.block_index_resolved),
            "block_strategy": self.block_strategy,
            "mode_multiplier": self.mode_multiplier,
            "budget": self.budget,
            "slot_count": self.slot_count,
            "sort_by": self.sort_by,
            "candidates_considered": self.candidates_considered,
            "candidates_evaluated": self.candidates_evaluated,
            "ranked": [r.to_dict() for r in self.ranked],
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [ASSASSIN]"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}  bonus_hp={self.target_bonus_hp:.0f}"
            f"  current_hp_pct={self.target_current_hp_pct * 100:.0f}%"
        )
        rows.append(
            f"priority: {'>'.join(self.max_priority)}  "
            f"block: {self.block_strategy}  primary_scaling: {self.primary_scaling}"
        )
        rows.append(f"combo: {' -> '.join(self.combo_sequence)}")
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline_burst: {self.baseline_burst:.2f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(
            f"  {'#':>3}  {'id':>6}  {'name':<28}  "
            f"{'gold':>5}  {'+burst':>7}  {'new':>7}  {'b/1k':>7}"
        )
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_burst:>7.2f}  "
                f"{r.new_burst:>7.2f}  {r.burst_per_1k_gold:>7.2f}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


# DSV3 (1.126.0): burst-archetype squishy-target armor assumption.
# rank_items_by_burst defaults target_armor=0.0, and against zero armor
# effective_target_armor floors its penetration tail at zero - so lethality
# (flat armor pen, Riot V14.1 1:1) contributes NOTHING to a ranked item's
# delta and an equal-cost raw-AD item out-ranks a lethality item. That
# under-values the lethality-vs-sustained-AD tradeoff a burst assassin
# actually faces: the target is a squishy carry WITH armor, against which
# flat pen bites. These model a representative squishy carry's armor curve
# (~22 base, +4.5 per level - a mage / ADC) so lethality flows through
# effective_target_armor and out-values raw AD. Opt-in via
# assume_squishy_target (default False -> byte-identical to today).
_SQUISHY_TARGET_BASE_ARMOR = 22.0
_SQUISHY_TARGET_ARMOR_PER_LEVEL = 4.5


def _assumed_squishy_target_armor(level: int) -> float:
    """Representative squishy-carry armor at ``level`` (DSV3 burst seam).

    Models a mage / ADC armor curve (~22 base, +4.5 per level above 1) so the
    burst ranker's lethality penetration has real armor to bite into. ``level``
    is clamped to the engine's valid range; the result is positive and
    monotonically increasing in level. The burst ranker substitutes this for a
    zero / absent ``target_armor`` when ``assume_squishy_target=True``.
    """
    lvl = clamp_level(level)
    return _SQUISHY_TARGET_BASE_ARMOR + _SQUISHY_TARGET_ARMOR_PER_LEVEL * (lvl - 1)


# DSP8 (1.134.0): enemy-comp target-preset seam. Generalizes the DSV3
# assume_squishy_target armor assumption into four representative enemy-comp
# defensive profiles - (armor, MR), each ``base + per_level * (level - 1)`` like
# the DSV3 squishy armor curve. The burst ranker substitutes a preset's resists
# for an absent / zero target so item valuation reflects the comp it is bursting:
# lethality / flat pen bites a tank's armor, magic pen bites a high-CC
# enchanter's MR. The squishy preset REUSES the DSV3 armor constants so
# target_preset="squishy" and assume_squishy_target=True agree on armor; the
# preset adds the MR the binary seam omitted. Values model a typical mid-game
# comp (role-norm base resists + 1-2 representative defensive items), not a
# fully-itemized target. Opt-in via target_preset (default None -> byte-
# identical); assume_squishy_target stays the DSV3 armor-only alias. The live
# default flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md) - do not wire
# a scorer to a preset blind.
_TARGET_PRESETS: dict[str, tuple[float, float, float, float]] = {
    # preset -> (armor_base, armor_per_level, mr_base, mr_per_level)
    "squishy": (_SQUISHY_TARGET_BASE_ARMOR, _SQUISHY_TARGET_ARMOR_PER_LEVEL, 30.0, 0.5),
    "bruiser": (35.0, 5.5, 30.0, 2.5),
    "tank": (50.0, 13.0, 40.0, 7.0),
    "high_cc": (30.0, 4.5, 35.0, 3.5),
}


def _assumed_target_resists(preset: str, level: int) -> tuple[float, float]:
    """Representative ``(armor, MR)`` for a named enemy-comp ``preset`` at ``level``.

    DSP8 burst seam. ``preset`` is one of ``_TARGET_PRESETS`` (squishy / bruiser
    / tank / high_cc). Both resists follow ``base + per_level * (level - 1)``;
    ``level`` is validated via ``clamp_level`` (raises outside the engine range,
    the same contract as ``_assumed_squishy_target_armor``). The squishy preset's
    armor is identical to ``_assumed_squishy_target_armor`` by construction.
    Raises ``ValueError`` on an unknown preset.
    """
    try:
        armor_base, armor_per, mr_base, mr_per = _TARGET_PRESETS[preset]
    except KeyError:
        raise ValueError(
            f"unknown target_preset {preset!r}; expected one of "
            f"{sorted(_TARGET_PRESETS)}"
        ) from None
    lvl = clamp_level(level)
    return (
        armor_base + armor_per * (lvl - 1),
        mr_base + mr_per * (lvl - 1),
    )


def _resolve_target_preset(
    target_preset: Optional[str],
    assume_squishy_target: bool,
) -> Optional[str]:
    """Resolve the active preset name (or None) from the two opt-in inputs.

    ``target_preset`` (DSP8) wins when supplied and is validated against
    ``_TARGET_PRESETS``. Otherwise ``assume_squishy_target=True`` (DSV3) maps to
    the ``"squishy"`` preset for ARMOR substitution only (the caller-side MR
    guard keeps that path byte-identical to DSV3). None when neither is set.
    """
    if target_preset is not None:
        if target_preset not in _TARGET_PRESETS:
            raise ValueError(
                f"unknown target_preset {target_preset!r}; expected one of "
                f"{sorted(_TARGET_PRESETS)}"
            )
        return target_preset
    if assume_squishy_target:
        return "squishy"
    return None


def rank_items_by_burst(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    abilities_snapshot: Optional[AbilitiesSnapshot] = None,
    max_priority: Optional[Sequence[str]] = None,
    block_strategy: str = "first",
    form_index_overrides: Optional[dict[str, int]] = None,
    block_index_overrides: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
    combo_sequence: Optional[Sequence[str]] = None,
    filter_shared_uniques: bool = True,
    runes: Optional[Sequence[int]] = None,
    aoe_targets_hit: int = 1,
    assume_takedown: bool = False,
    assume_squishy_target: bool = False,
    assume_ability_amp: bool = False,
    target_preset: Optional[str] = None,
    prefer_kit_axis_by_win: bool = False,
) -> BurstRankResult:
    """Rank items by total-burst-damage gain when added to ``current_item_ids``.

    Phase 5 sibling of ``rank_items`` (DPS), ``rank_items_by_ehp`` (EHP),
    ``rank_items_by_hybrid`` (bruiser), and ``rank_items_by_ability_dps``
    (mage). Same candidate-filtering pipeline - purchasable + mode-legal +
    optional whitelist + budget + terminal-only + dead-unique dedup. Only
    the scoring function changes: each candidate's combo total via
    ``compute_burst_damage`` is compared to the baseline.

    Sort keys:
      * ``delta``       - absolute burst-damage gain (default)
      * ``efficiency``  - burst-damage gain per 1000 gold

    ``filter_shared_uniques=True`` drops candidates whose unique passive
    key collides with one already in ``current_item_ids`` - matches the
    other scorers' behavior so the assassin ranker stays consistent.

    ``runes`` (DS V2 S3, optional Riot perk ids) is threaded into BOTH the
    baseline and per-candidate ``compute_burst_damage`` calls. When None or
    empty the ranking is BYTE-IDENTICAL to today (the None path of
    ``compute_burst_damage`` is unchanged). When supplied, each build's
    burst gains the rune-proc layer (on_proc_burst / per_attack /
    stacking_amp + keystone_amp; Conqueror adaptive excluded), so the
    delta still isolates the item's marginal gain over a rune-equipped
    baseline.

    ``assume_squishy_target`` (DSV3, default False) refines the
    lethality-vs-sustained-AD tradeoff. With the default zero ``target_armor``
    lethality penetrates nothing, so a raw-AD item out-ranks an equal-cost
    lethality item. When True and the caller did not pin a positive
    ``target_armor``, the ranker substitutes ``_assumed_squishy_target_armor``
    (a representative squishy carry) for BOTH the baseline and every candidate,
    so lethality flows through ``effective_target_armor`` and out-values raw AD
    for burst archetypes. OFF or with an explicit ``target_armor>0`` the
    ranking is byte-identical.

    ``target_preset`` (DSP8, default None) generalizes that binary seam into a
    named enemy-comp profile - ``"squishy"`` / ``"bruiser"`` / ``"tank"`` /
    ``"high_cc"`` - each substituting a representative ``(armor, MR)`` (see
    ``_assumed_target_resists``) for an absent / zero target, so item valuation
    reflects the comp being burst (lethality bites a tank's armor, magic pen
    bites a high-CC enchanter's MR). ``target_preset`` wins over
    ``assume_squishy_target`` and is the only path that also substitutes MR; the
    legacy ``assume_squishy_target`` stays armor-only. None -> byte-identical.

    ``prefer_kit_axis_by_win`` is the OPTIONAL DSP11 Cluster-B2 seam (DEFAULT-OFF).
    The single-combo burst model ranks a generic AD template (Sundered Sky / IE /
    Trinity / Essence Reaver) for every assassin because it cannot encode a kit's
    win-axis (Pyke R executes scale with lethality), so the lethality items the
    player base WINS on (the DSP10 buried winners) sink below it. When ``False``
    (default) the output is byte-identical - ``kit_axis_score`` stays 0.0 and the
    sort is unchanged. When ``True`` and the champ has a WIN-anchored
    ``kit_axis_item_credit`` entry, every positive-delta kit-axis item is floated
    above the generic template (model order preserved within each tier). Champs
    absent from the table are a no-op. The live default-ON flip is EXCLUDED ->
    docs/LIVE_GAME_GATED_SYNC.md.
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    level = clamp_level(level)
    # DSP11 (DEFAULT-OFF): resolve the champ's WIN-anchored kit-axis item ids.
    # Empty unless the seam is on AND the champ is tabled -> byte-identical no-op.
    # The burst ranker applies no off-class strip, so the seam is float-only here.
    kit_axis_ids: frozenset[str] = (
        kit_axis_item_ids(str(champion_id)) if prefer_kit_axis_by_win else frozenset()
    )
    kit_axis_active = bool(kit_axis_ids)
    # DSV3 (1.126.0) + DSP8 (1.134.0): enemy-comp target-preset resist
    # assumption. _resolve_target_preset maps target_preset (DSP8) or the legacy
    # assume_squishy_target (DSV3 -> "squishy") to an active preset, or None.
    # When a preset is active and the caller did not pin a positive resist, the
    # preset's representative (armor, MR) is substituted for BOTH the baseline
    # and every candidate, so item valuation reflects the comp being burst
    # (lethality bites armor, magic pen bites MR). BACK-COMPAT: the
    # assume_squishy_target path substitutes ARMOR only (the MR guard requires an
    # explicit target_preset), so the DSV3 ranking stays byte-identical. OFF
    # (default) -> ranking resists == caller resists, so the ranking is
    # byte-identical.
    ranking_target_armor = target_armor
    ranking_target_mr = target_mr
    _active_preset = _resolve_target_preset(target_preset, assume_squishy_target)
    if _active_preset is not None:
        _preset_armor, _preset_mr = _assumed_target_resists(_active_preset, level)
        if ranking_target_armor <= 0.0:
            ranking_target_armor = _preset_armor
        if target_preset is not None and ranking_target_mr <= 0.0:
            ranking_target_mr = _preset_mr
    # Normalize once so baseline + every candidate share the same rune list.
    # None when absent/empty -> compute_burst_damage stays byte-identical.
    runes_norm = list(runes) if runes else None

    # Resolve once so baseline + every candidate share priority + combo +
    # form_index + block_index.
    resolved_priority, priority_source = _resolve_max_priority(champion_id, max_priority)
    combo_norm, combo_source = _resolve_combo_sequence(champion_id, combo_sequence)
    resolved_form_index, form_index_source = _resolve_form_index_overrides(
        champion_id, form_index_overrides,
    )
    resolved_block_index, block_index_source = _resolve_block_index_overrides(
        champion_id, block_index_overrides,
    )

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    current_set = set(current_ids)
    current_unique_keys: set[str] = set()
    for iid in current_ids:
        eff = ITEM_EFFECTS.get(iid)
        if eff is not None and eff.unique_passive_key:
            current_unique_keys.add(eff.unique_passive_key)

    if len(current_ids) >= slot_count:
        raise ValueError(
            f"current_item_ids has {len(current_ids)} items; slot_count={slot_count} "
            f"leaves no room for a new item"
        )

    only_ids: Optional[set[str]] = None
    if only_item_ids is not None:
        only_ids = {str(i) for i in only_item_ids}

    baseline = compute_burst_damage(
        snapshot,
        champion_id=champion_id, level=level,
        item_ids=current_ids, mode=mode,
        target_armor=ranking_target_armor, target_mr=ranking_target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        augments=augments,
        abilities_snapshot=abilities_snapshot,
        max_priority=resolved_priority,
        block_strategy=block_strategy,
        form_index_overrides=resolved_form_index,
        block_index_overrides=resolved_block_index,
        combo_sequence=combo_norm,
        runes=runes_norm,
        aoe_targets_hit=aoe_targets_hit,
        assume_takedown=assume_takedown,
        assume_ability_amp=assume_ability_amp,
    )

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
    )

    ranked: list[BurstRankedItem] = []
    for item_id, rec in candidates:
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            scored = compute_burst_damage(
                snapshot,
                champion_id=champion_id, level=level,
                item_ids=new_build, mode=mode,
                target_armor=ranking_target_armor, target_mr=ranking_target_mr,
                target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
                target_current_hp_pct=target_current_hp_pct,
                augments=augments,
                abilities_snapshot=abilities_snapshot,
                max_priority=resolved_priority,
                block_strategy=block_strategy,
                form_index_overrides=resolved_form_index,
                block_index_overrides=resolved_block_index,
                combo_sequence=combo_norm,
                runes=runes_norm,
                aoe_targets_hit=aoe_targets_hit,
                assume_takedown=assume_takedown,
                assume_ability_amp=assume_ability_amp,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.total_burst_damage - baseline.total_burst_damage
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        # DSP11 kit-axis credit marker: 1.0 on a surfaced (positive-delta)
        # WIN-anchored kit-axis item when engaged, else 0.0. A non-positive
        # delta is a regression and is NOT floated.
        kit_axis_score = 1.0 if (
            kit_axis_active and item_id in kit_axis_ids and delta > 0.0
        ) else 0.0
        ranked.append(BurstRankedItem(
            item_id=item_id,
            item_name=str(rec.get("name", item_id)),
            gold=gold,
            delta_burst=delta,
            new_burst=scored.total_burst_damage,
            burst_per_1k_gold=eff,
            is_terminal=_is_terminal(rec),
            tags=tuple(rec.get("tags") or ()),
            shares_dead_unique=shares_dead_unique,
            dead_unique_key=cand_key if shares_dead_unique else "",
            unique_passive_key=cand_key,
            kit_axis_score=kit_axis_score,
        ))

    def _base_key(r: BurstRankedItem) -> tuple:
        if sort_by == "efficiency":
            return (r.burst_per_1k_gold, r.delta_burst)
        return (r.delta_burst, r.burst_per_1k_gold)

    if kit_axis_active:
        # DSP11: float surfaced kit-axis items above the generic template,
        # preserving the model order within each tier. Byte-identical when off.
        ranked.sort(key=lambda r: (r.kit_axis_score,) + _base_key(r), reverse=True)
    else:
        ranked.sort(key=_base_key, reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    notes.append(
        f"max_priority={'>'.join(resolved_priority)} (source={priority_source})  "
        f"block_strategy={block_strategy}"
    )
    notes.append(f"combo={' -> '.join(combo_norm)} (source={combo_source})")
    notes.append(f"primary_scaling={baseline.primary_scaling}")
    if (
        assume_squishy_target and target_preset is None
        and ranking_target_armor != target_armor
    ):
        notes.append(
            f"assume_squishy_target=True - ranked vs assumed squishy armor "
            f"{ranking_target_armor:.0f} (level {level}); lethality valued over raw AD"
        )
    if target_preset is not None and _active_preset is not None:
        notes.append(
            f"target_preset={_active_preset!r} - ranked vs assumed enemy-comp "
            f"resists armor {ranking_target_armor:.0f} / MR "
            f"{ranking_target_mr:.0f} (level {level})"
        )
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA - stripped trinket(s) {list(stripped_trinkets)} "
            f"from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True - non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g - items over budget filtered")
    if only_ids is not None:
        notes.append(f"only_item_ids restricted to {len(only_ids)} whitelisted ids")
    if baseline.mode_multiplier != 1.0:
        notes.append(
            f"mode_multiplier={baseline.mode_multiplier:.3f} on per-cast damage"
        )
    if baseline.total_burst_damage == 0.0:
        notes.append(
            "baseline burst damage is 0 - champion may be missing from the "
            "abilities snapshot, or all spells locked at this level"
        )

    if resolved_block_index:
        notes.append(
            f"block_index source={block_index_source}: "
            + ", ".join(f"{k}={resolved_block_index[k]}" for k in sorted(resolved_block_index))
        )

    return BurstRankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_burst=baseline.total_burst_damage,
        primary_scaling=baseline.primary_scaling,
        target_armor=ranking_target_armor,
        target_mr=ranking_target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        combo_sequence=combo_norm,
        max_priority=tuple(resolved_priority),
        max_priority_source=priority_source,
        combo_sequence_source=combo_source,
        form_index_source=form_index_source,
        form_index_resolved=dict(resolved_form_index),
        block_index_source=block_index_source,
        block_index_resolved=dict(resolved_block_index),
        block_strategy=block_strategy,
        mode_multiplier=baseline.mode_multiplier,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
    )
