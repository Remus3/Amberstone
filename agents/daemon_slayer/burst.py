"""Phase 5 (s180, 2026-05-13) — Assassin burst-window scorer.

Sibling of ``ability_dps.py``. ``compute_burst_damage()`` returns the
caster's total damage dealt during a single combo rotation
(``Q→W→E→AA→R→AA`` by default — operator-overridable via
``combo_sequence``). ``rank_items_by_burst()`` drives the
``/rank-assassin`` route — same candidate-filtering pipeline as the
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
custom template via ``combo_sequence`` — e.g. Zed's full rotation
``("W", "E", "Q", "AA", "R", "Q2", "AA", "AA", "AA")`` or Talon's
``("W", "Q", "AA", "R", "AA")``. Tokens:

* ``"AA"`` — one auto-attack hit; uses the build's per-hit
  ``avg_attack_dmg`` from ``compute_dps`` (post-armor + mode).
* ``"P"`` / ``"Q"`` / ``"W"`` / ``"E"`` / ``"R"`` — one cast of that
  ability at its level-resolved rank.
* ``"Q2"`` / ``"W2"`` / ``"E2"`` / ``"R2"`` — a repeat cast of the
  same ability at the SAME rank (the combo window is too short for a
  level-up). The trailing digit is treated as a "second instance"
  marker; Zed's R-shadow re-cast Q is the canonical case.
* Anything else raises ``ValueError`` at validation time.

Phase 5 deliberate omissions (Phase 5.5 / future):
* Real cooldown sequencing — every spell modeled as ready at combo
  start; CDR doesn't affect a single-combo window.
* Mana economy — assassins typically run energy / manaless / one-rotation
  buffer; not a meaningful burst constraint.
* On-attack periodic procs (Wit's End, Sundered Sky Lightshield Strike,
  BotRK Mist's Edge) — captured in ``avg_attack_dmg`` as ZERO. Phase 5
  models AA damage as raw post-armor AD × crit, no on-hit procs.
  Phase 5.5 adds an inline ``per_attack_proc_damage`` walker.
* Champion-specific combo templates (Kha'Zix isolation Q bonus, Akali
  R2 after R1, Zed shadow R+Q2) — Phase 5.5 with a per-champion
  combo-template JSON. v1 caller passes ``combo_sequence`` explicitly.
* Conditional damage amps (Ahri R→Q amp, Zoe E→Q amp) — single
  per-cast scoring with no combo-multiplier; same omission as Phase 4b.

Phase 5 ALSO models the burst window with the SAME amp pipeline as
Phase 4b — Rabadon's, Liandry's, Demonic Embrace, Riftmaker HP→AP, all
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
    _resolve_form_index_overrides,
    _resolve_max_priority,
    _select_blocks,
    rank_at_level,
)
from .data_loader import DataSnapshot
from .dps import compute_dps
from .effects import (
    ITEM_EFFECTS,
    collect_effects,
    effective_target_armor,
    effective_target_mr,
    total_ap_amp_multiplier,
    total_bonus_ap_from_hp,
    total_caster_hp_scaled_ap_amp,
    total_damage_amp_multiplier,
    total_giant_slayer_multiplier,
    total_magic_amp_multiplier,
    total_stacked_ap,
    total_target_bonus_hp_amp_multiplier,
)
from .engine import build_champion
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level

# Default combo template — Q W E AA R AA. Most AD/AP assassins fit the
# ability-then-AA-then-R cadence; channel/burst ults (Akali R, Kassadin
# R, Diana R, Zed R) plus shadow/blink R execute with one AA before and
# one AA after the ult lands.
DEFAULT_COMBO_SEQUENCE: tuple[str, ...] = ("Q", "W", "E", "AA", "R", "AA")

# Phase 5.5 (s186, 2026-05-13) — per-champion combo override registry.
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
    """Clear the singleton cache — for tests that mutate the on-disk file."""
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
      * ``"override"`` — caller passed an explicit value
      * ``"champion"`` — override table had an entry for the champion
      * ``"default"`` — fell back to the table default (Q-W-E-AA-R-AA)
    """
    if explicit is not None:
        return (_validate_combo_sequence(explicit), "override")
    return get_combo_for(champion_id)

# Spell key set — passive included so combos like Akali's P-on-hit can
# (in a future version) be inserted explicitly. Phase 5 v1 only fires P
# when the operator includes it in combo_sequence.
_SPELL_KEYS: frozenset[str] = frozenset({"P", "Q", "W", "E", "R"})

# Token markers — strip the trailing digit if present to find the ability
# key; the digit just signals a repeat cast at the same rank.
_REPEAT_SUFFIXES: frozenset[str] = frozenset({"2", "3", "4"})


def _normalize_combo_token(token: str) -> tuple[str, str, bool]:
    """Return ``(canonical_token, ability_key, is_ability)``.

    ``canonical_token`` is what shows up in the per-cast result; useful for
    distinguishing Q from Q2 in operator-readable output. ``ability_key``
    is the underlying P/Q/W/E/R for evaluation (empty for AA).

    Raises ``ValueError`` on unrecognized tokens — callers should validate
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


# ─── per-cast result row ─────────────────────────────────────────────────────


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
    post_mode_damage: float             # × mode_multiplier
    post_amps_damage: float             # × build_amp × magic_amp
    final_damage: float                 # × mitigation_factor (contributes to total)
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
    # Phase 5.7 (s189, 2026-05-13) — Spellblade contribution within the
    # combo. ``spellblade_procs`` counts how many ability-then-AA
    # transitions actually fired a Spellblade proc; ``spellblade_damage``
    # is the cumulative damage from those procs (already in
    # ``auto_attack_damage`` / ``total_burst_damage`` for the AA rows
    # that consumed them). ``spellblade_item_name`` is the build's active
    # Spellblade item (informational; "" when no Spellblade in build).
    spellblade_procs: int = 0
    spellblade_damage: float = 0.0
    spellblade_item_name: str = ""
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
            "spellblade_procs": self.spellblade_procs,
            "spellblade_damage": self.spellblade_damage,
            "spellblade_item_name": self.spellblade_item_name,
            "stats": dict(self.stats),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode}  [ASSASSIN]"
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
        rows.append(f"combo: {' → '.join(self.combo_sequence)}")
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


# ─── top-level compute ───────────────────────────────────────────────────────


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
    combo_sequence: Optional[Sequence[str]] = None,
) -> BurstResult:
    """Compute one-combo total burst damage for the resolved build.

    Mirror of ``compute_ability_dps``'s contract — same ``snapshot``,
    ``mode``, ``target_*``, ``augments``, and ability-resolution plumbing —
    but the result decomposes by combo step (one row per token in
    ``combo_sequence``) instead of by spell key. ``target_current_hp_pct``
    pin lets the caller assume the cast lands at a specific HP-band, which
    drives ``target_missing_hp_pct`` / ``target_current_hp_pct`` scaling
    fields (Zed R execute, Kha'Zix isolated Q bonus when modeled later).

    ``max_priority`` defaults to the per-champion override from
    ``champion_max_priority.json`` via ``_resolve_max_priority`` — Phase 4d
    (s185). Operator can override explicitly per call.

    ``combo_sequence`` defaults to the per-champion override from
    ``champion_combo_sequences.json`` via ``_resolve_combo_sequence`` —
    Phase 5.5 (s186). Zed's shadow Q2, Yone's Q1-Q2-Q3 chain, and Akali's
    R-recast all live in the registry so /rank-assassin scores their burst
    accurately by default.

    Auto-attack hits in the combo contribute the build's per-hit
    ``avg_attack_dmg`` from ``compute_dps`` — that's post-armor and
    post-mode-multiplier, no on-hit periodic procs (see module docstring
    "Phase 5 deliberate omissions"). For 14 of 15 canonical assassins
    (Zed/Talon/Akali/Kha'Zix/Rengar/Fizz/Diana/Kassadin/Katarina/LeBlanc/
    Qiyana/Pyke/Naafiri/Briar/Yone), this captures the lethality-driven
    burst correctly because lethality flows through ``effective_target_armor``
    for both the ability and the AA hits.
    """
    if block_strategy not in {"first", "sum", "max"}:
        raise ValueError(
            f"block_strategy must be one of first|sum|max, got {block_strategy!r}"
        )
    max_priority, max_priority_source = _resolve_max_priority(champion_id, max_priority)
    form_index_overrides, form_index_source = _resolve_form_index_overrides(
        champion_id, form_index_overrides,
    )
    if not 0.0 <= target_current_hp_pct <= 1.0:
        raise ValueError(
            f"target_current_hp_pct must be in [0,1], got {target_current_hp_pct}"
        )
    combo_norm, combo_source = _resolve_combo_sequence(champion_id, combo_sequence)

    level = clamp_level(level)

    # Load abilities snapshot lazily — same pattern as compute_ability_dps.
    abil_snap = abilities_snapshot
    if abil_snap is None:
        from .abilities import load_default  # noqa: PLC0415 — local import keeps tests fast
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
                note=f"abilities snapshot missing: {e}",
            )

    # Resolve the build once. Reused for ability stats AND the AA per-hit
    # damage probe via compute_dps below. Two engine passes per call — same
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
    # included) as the ability mitigation pipeline below — assassin
    # rankings stay internally consistent.
    aa_probe = compute_dps(
        snapshot, champion_id=resolved.champion_id, level=level,
        item_ids=resolved.item_ids, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        augments=augments,
    )
    aa_base_per_hit = max(0.0, float(aa_probe.avg_attack_dmg))
    # Phase 5.6 (s188, 2026-05-13): on-hit proc contribution per AA —
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

    # Build-wide damage amps and target-conditional amps.
    damage_amp = total_damage_amp_multiplier(item_effects)
    damage_amp *= total_target_bonus_hp_amp_multiplier(item_effects, target_bonus_hp)
    damage_amp *= total_giant_slayer_multiplier(
        item_effects, target_max_hp, ctx.caster_max_hp,
    )
    magic_amp = total_magic_amp_multiplier(item_effects)

    # Effective resists — lethality flows through here.
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
            champion_name=resolved.champion_name,
            note=f"champion {resolved.champion_id!r} absent from abilities snapshot",
        )
    per_key_forms = abil_snap.get_abilities(resolved.champion_id)
    overrides = form_index_overrides or {}

    per_cast: list[ComboCast] = []
    forms_for_classification: list[AbilityForm] = []
    seen_keys: set[str] = set()
    # Phase 5.7 (s189, 2026-05-13) — Spellblade arming state. Set True by
    # any ability cast (P/Q/W/E/R or repeat variant); consumed by the
    # next AA which adds the proc damage and resets to False. Tracked
    # separately so the BurstResult can surface the total proc count.
    spellblade_armed = False
    spellblade_procs_fired = 0
    spellblade_damage_total = 0.0
    for token in combo_norm:
        canonical, ability_key, is_ability = _normalize_combo_token(token)
        if not is_ability:
            # AA contributes raw per-hit damage from compute_dps. The
            # avg_attack_dmg is already post-armor+mode; classify as
            # PHYSICAL for the per-cast row. Don't re-apply mode_mult
            # or armor_factor — compute_dps did that already. Spellblade
            # (Phase 5.7, s189) fires once per ability-then-AA transition:
            # if armed AND a Spellblade item is in the build, this AA
            # consumes the proc.
            aa_spellblade_added = 0.0
            if spellblade_armed and aa_spellblade_per_proc > 0:
                aa_spellblade_added = aa_spellblade_per_proc
                spellblade_armed = False
                spellblade_procs_fired += 1
                spellblade_damage_total += aa_spellblade_added
            aa_total_damage = aa_per_hit + aa_spellblade_added
            if aa_spellblade_added > 0:
                aa_note = (
                    f"auto-attack: base {aa_base_per_hit:.1f} + on-hit "
                    f"{aa_on_hit_per_hit:.1f} + Spellblade ({aa_spellblade_name}) "
                    f"{aa_spellblade_added:.1f} = {aa_total_damage:.1f}"
                )
            else:
                aa_note = (
                    f"auto-attack: base {aa_base_per_hit:.1f} + on-hit "
                    f"{aa_on_hit_per_hit:.1f} = {aa_total_damage:.1f} (post-armor "
                    "+ mode + on-hit procs amortized per AA)"
                )
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

        # Ability cast — arm Spellblade for the next AA. Subsequent
        # ability casts before the next AA leave it armed (still True).
        spellblade_armed = True

        forms = per_key_forms.get(ability_key, ())
        if not forms:
            per_cast.append(_zero_cast(
                canonical, ability_key, "missing", -1,
                notes=(f"no {ability_key} ability recorded for "
                       f"{resolved.champion_id} — skipped",),
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
        cooldown = _form_cooldown_at_rank(form, rank)
        cost = _form_cost_at_rank(form, rank)
        raw = _select_blocks(form.damage_blocks, rank, ctx, block_strategy)
        post_mode = raw * mode_mult
        dt = (form.damage_type or "MAGIC").upper()
        spell_magic_amp = magic_amp if dt == "MAGIC" else 1.0
        post_amps = post_mode * damage_amp * spell_magic_amp
        mit = _mitigation_factor(form.damage_type, target_armor_eff, target_mr_eff)
        final = post_amps * mit
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
    total_burst = ability_total + aa_total
    primary = _classify_primary_scaling(per_cast, forms_for_classification)

    notes: list[str] = list(resolved.notes)
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(f"ARAM aramDamageDealt={mode_mult:.3f} on per-cast damage")
    if ap_amp != 1.0:
        notes.append(
            f"AP amplified ×{ap_amp:.3f} by item amp (effective AP for ability "
            f"scaling: {ap_total:.1f})"
        )
    if hp_ap_amp != 1.0:
        notes.append(
            f"AP HP-scaled amp ×{hp_ap_amp:.3f} (Demonic Embrace at "
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
            f"build damage amp ×{damage_amp:.3f} "
            f"(+{(damage_amp - 1.0) * 100:.1f}% to all ability damage)"
        )
    if magic_amp != 1.0:
        notes.append(
            f"magic damage amp ×{magic_amp:.3f} on magic-typed spells "
            "(Abyssal Mask Unmake)"
        )
    if target_armor_eff != target_armor:
        notes.append(
            f"effective target armor {target_armor:.1f} → {target_armor_eff:.1f} "
            "after reduction + lethality + % pen"
        )
    if target_mr_eff != target_mr:
        notes.append(
            f"effective target MR {target_mr:.1f} → {target_mr_eff:.1f} "
            "after flat + % magic pen"
        )
    if aa_total > 0 and combo_norm.count("AA") > 0:
        breakdown = (
            f" (base {aa_base_per_hit:.1f} + on-hit {aa_on_hit_per_hit:.1f})"
            if aa_on_hit_per_hit > 0 else ""
        )
        notes.append(
            f"auto-attack contribution {aa_total:.1f} from "
            f"{combo_norm.count('AA')} AA × {aa_per_hit:.1f}/hit{breakdown}"
        )
    if spellblade_procs_fired > 0:
        notes.append(
            f"Spellblade ({aa_spellblade_name}) fired {spellblade_procs_fired}× "
            f"in combo for +{spellblade_damage_total:.1f} damage "
            f"(armed by spell-cast, consumed by next AA; "
            f"per-proc {aa_spellblade_per_proc:.1f})"
        )
    elif aa_spellblade_per_proc > 0:
        # Build has Spellblade but no AA followed a spell — surface so
        # operator can spot when the combo template doesn't exercise the
        # passive (e.g. a pure-AA sequence or AAs before any spell).
        notes.append(
            f"Spellblade ({aa_spellblade_name}) idle in combo — no AA "
            "followed an ability cast (per-proc value "
            f"{aa_spellblade_per_proc:.1f} unused)"
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
        spellblade_procs=spellblade_procs_fired,
        spellblade_damage=spellblade_damage_total,
        spellblade_item_name=aa_spellblade_name,
        stats=dict(resolved.stats),
        notes=tuple(notes),
    )


# ─── helpers for empty / zero results ────────────────────────────────────────


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
        stats={},
        notes=(note,) if note else (),
    )


# ─── ranker ──────────────────────────────────────────────────────────────────


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
        }


@dataclass(frozen=True)
class BurstRankResult:
    """Phase 5 — output of ``rank_items_by_burst``."""
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
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode}  [ASSASSIN]"
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
        rows.append(f"combo: {' → '.join(self.combo_sequence)}")
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
    combo_sequence: Optional[Sequence[str]] = None,
    filter_shared_uniques: bool = True,
) -> BurstRankResult:
    """Rank items by total-burst-damage gain when added to ``current_item_ids``.

    Phase 5 sibling of ``rank_items`` (DPS), ``rank_items_by_ehp`` (EHP),
    ``rank_items_by_hybrid`` (bruiser), and ``rank_items_by_ability_dps``
    (mage). Same candidate-filtering pipeline — purchasable + mode-legal +
    optional whitelist + budget + terminal-only + dead-unique dedup. Only
    the scoring function changes: each candidate's combo total via
    ``compute_burst_damage`` is compared to the baseline.

    Sort keys:
      * ``delta``       — absolute burst-damage gain (default)
      * ``efficiency``  — burst-damage gain per 1000 gold

    ``filter_shared_uniques=True`` drops candidates whose unique passive
    key collides with one already in ``current_item_ids`` — matches the
    other scorers' behavior so the assassin ranker stays consistent.
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    level = clamp_level(level)

    # Resolve once so baseline + every candidate share priority + combo +
    # form_index.
    resolved_priority, priority_source = _resolve_max_priority(champion_id, max_priority)
    combo_norm, combo_source = _resolve_combo_sequence(champion_id, combo_sequence)
    resolved_form_index, form_index_source = _resolve_form_index_overrides(
        champion_id, form_index_overrides,
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
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        augments=augments,
        abilities_snapshot=abilities_snapshot,
        max_priority=resolved_priority,
        block_strategy=block_strategy,
        form_index_overrides=resolved_form_index,
        combo_sequence=combo_norm,
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
                target_armor=target_armor, target_mr=target_mr,
                target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
                target_current_hp_pct=target_current_hp_pct,
                augments=augments,
                abilities_snapshot=abilities_snapshot,
                max_priority=max_priority,
                block_strategy=block_strategy,
                form_index_overrides=form_index_overrides,
                combo_sequence=combo_norm,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.total_burst_damage - baseline.total_burst_damage
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
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
        ))

    if sort_by == "efficiency":
        ranked.sort(key=lambda r: (r.burst_per_1k_gold, r.delta_burst), reverse=True)
    else:
        ranked.sort(key=lambda r: (r.delta_burst, r.burst_per_1k_gold), reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    notes.append(
        f"max_priority={'>'.join(resolved_priority)} (source={priority_source})  "
        f"block_strategy={block_strategy}"
    )
    notes.append(f"combo={' → '.join(combo_norm)} (source={combo_source})")
    notes.append(f"primary_scaling={baseline.primary_scaling}")
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA — stripped trinket(s) {list(stripped_trinkets)} "
            f"from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True — non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g — items over budget filtered")
    if only_ids is not None:
        notes.append(f"only_item_ids restricted to {len(only_ids)} whitelisted ids")
    if baseline.mode_multiplier != 1.0:
        notes.append(
            f"mode_multiplier={baseline.mode_multiplier:.3f} on per-cast damage"
        )
    if baseline.total_burst_damage == 0.0:
        notes.append(
            "baseline burst damage is 0 — champion may be missing from the "
            "abilities snapshot, or all spells locked at this level"
        )

    return BurstRankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_burst=baseline.total_burst_damage,
        primary_scaling=baseline.primary_scaling,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        combo_sequence=combo_norm,
        max_priority=tuple(resolved_priority),
        max_priority_source=priority_source,
        combo_sequence_source=combo_source,
        form_index_source=form_index_source,
        form_index_resolved=dict(resolved_form_index),
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
