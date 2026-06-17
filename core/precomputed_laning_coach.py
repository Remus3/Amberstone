# arch: HZ-C1 precomputed A/B choice-coach over the laning + build tables | section=core | frozen=no
"""HZ-C1 - deterministic A/B choice-coach over the precomputed Lane A laning
table (+ next build item). PRIMARY north star: drive live Haiku usage to ZERO.

PURPOSE
    The live coach pays a Claude Haiku call to answer "trade / all-in / back
    off". HZ-A1/A2 (``core.laning_scenario_precompute``) already PRECOMPUTE that
    verdict offline into versioned JSON keyed on
    ``(my_champ x enemy x level-band x mana-state x cd-state)`` with an
    ``economy`` recall/spike block per cell. This module is the request-time
    READER that turns ONE precomputed cell into two grounded A/B ``CoachChoice``
    objects - the deterministic coaching surface that REPLACES the Haiku
    paragraph once validated.

    v1 is SHADOW ONLY (charter 4b "do not flip blind"): the choices are recorded
    alongside live Haiku (``core.hz_choice_shadow``) for offline validation
    against real games; NO live coach is flipped off its Haiku call in this
    slice. Unlike the item-265 ``dashboard._deterministic_coaching`` path (which
    calls the DS matchup engine LIVE over :8893 per request), this reader is a
    PURE static table read - no network, no engine import on the hot path.

KEY MAPPING (live game state -> the table's discrete keys)
    * level -> band  : nearest of L2 / L6 / L11 / L16 (``band_for_level``).
    * mana%  -> mana_state : >= ``_FULL_MANA_FRACTION`` -> "full" else "low".
    * ult-up -> cd_state   : ult ready -> "all_up" else "no_ult".

FAIL-SOFT
    A missing table, an uncovered ``(champ, enemy)`` pair, or any malformed cell
    yields ``[]`` - the caller degrades to "no precomputed choice" (it keeps its
    existing path). Never raises.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from core.archetype_picks import canonical_champion_id
from core.coach_choices import CoachChoice
from core.laning_scenario_precompute import (
    GEN_BANDS,
    LEVEL_BANDS,
    load_laning_scenarios,
    lookup,
)

# Above this fraction of the mana pool you can fire the full rotation (the
# table's "full" cell); below it you are on the affordable-prefix "low" cell.
# The table BUILDS the low cell at LOW_MANA_FRACTION (0.35) of the pool; the
# request-time split at half-pool is the honest live read of "can I full-combo".
_FULL_MANA_FRACTION: float = 0.5

# Source tag stamped on every emitted choice so the surface is distinguishable
# from haiku / synth / the item-265 ds-matchup choices in logs + the UI.
SOURCE_TAG: str = "ds-precompute"

# Verdict -> (recommended action label, prudent-alternative label). The verdict
# IS the recommendation (A); B is the safer alternative. Economy may override B
# with a recall directive (see _build_choices).
_VERDICT_LABELS: dict[str, Tuple[str, str]] = {
    "all_in": ("All-in {enemy}", "Hold - poke only"),
    "trade": ("Trade {enemy}", "Hold - poke only"),
    "back_off": ("Back off {enemy}", "Force a short trade"),
    "even": ("Even trade on your cd window", "Hold position"),
}

_RECALL_LABELS: dict[str, str] = {
    "recall_now": "Recall now",
    "back_soon": "Back soon",
}


def band_for_level(level: object) -> str:
    """Nearest level-band label for a live level (fail-soft to ``L2``).

    Bands partition the level axis at phase boundaries: 1-3 -> L2 (early
    skirmish), 4-8 -> L6 (first ult spike), 9-13 -> L11 (2-item mid),
    14-18 -> L16 (late lane / roam)."""
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        return "L2"
    if lvl < 4:
        return "L2"
    if lvl < 9:
        return "L6"
    if lvl < 14:
        return "L11"
    return "L16"


def mana_state_for(mana_fraction: Optional[float]) -> str:
    """``full`` when at/above half pool (or unknown), else ``low``.

    Unknown mana (None / non-numeric) defaults to ``full`` - the full-rotation
    cell is the honest baseline read when we cannot see the pool."""
    if mana_fraction is None:
        return "full"
    try:
        frac = float(mana_fraction)
    except (TypeError, ValueError):
        return "full"
    return "full" if frac >= _FULL_MANA_FRACTION else "low"


def cd_state_for(ult_up: Optional[bool]) -> str:
    """``all_up`` when the ult is ready (or unknown), else ``no_ult``."""
    if ult_up is None:
        return "all_up"
    return "all_up" if bool(ult_up) else "no_ult"


def _confidence_for(net_swing: object) -> str:
    """Confidence band from the absolute net swing magnitude.

    The verdict is deterministic; the confidence reflects how lopsided the
    trade math is. |swing| >= 0.20 -> high, >= 0.08 -> mid, else low."""
    try:
        mag = abs(float(net_swing))
    except (TypeError, ValueError):
        return "mid"
    if mag >= 0.20:
        return "high"
    if mag >= 0.08:
        return "mid"
    return "low"


def _pct(value: object) -> str:
    """Format a 0..1 fraction as a whole-percent string (fail-soft ``0%``)."""
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "0%"


def _combat_outcome(cell: dict, enemy: str) -> str:
    """DS-backed expected-outcome line for the combat choice."""
    swing = cell.get("net_swing")
    try:
        swing_s = f"{float(swing):+.2f}"
    except (TypeError, ValueError):
        swing_s = "+0.00"
    return (
        f"net swing {swing_s}; you remove "
        f"{_pct(cell.get('pct_enemy_removed'))} of {enemy}, "
        f"they remove {_pct(cell.get('pct_my_removed'))} of you"
    )


def _recall_outcome(economy: dict, next_item: Optional[Tuple[str, int]]) -> str:
    """DS-backed expected-outcome line for the economy/recall choice."""
    spike = str(economy.get("next_spike") or "spike")
    gold = economy.get("gold_at_band")
    try:
        gold_s = f"{int(round(float(gold)))}g"
    except (TypeError, ValueError):
        gold_s = "gold"
    if next_item and next_item[0]:
        return f"buy {next_item[0]} ({int(next_item[1])}g) toward {spike}"
    return f"{gold_s} banked; next spike {spike}"


def _build_choices(
    cell: dict,
    enemy: str,
    *,
    next_item: Optional[Tuple[str, int]] = None,
) -> list[CoachChoice]:
    """Two grounded A/B choices from one resolved laning cell.

    A = the combat verdict (the recommendation), confidence from the swing
    magnitude. B = the economy alternative when the cell's recall verdict is
    ``recall_now`` / ``back_soon`` (grounded in the spike + next build item),
    else the prudent combat alternative from ``_VERDICT_LABELS``."""
    verdict = str(cell.get("verdict") or "even")
    a_label_tpl, b_label_alt = _VERDICT_LABELS.get(
        verdict, _VERDICT_LABELS["even"]
    )
    a = CoachChoice(
        key="A",
        label=a_label_tpl.format(enemy=enemy),
        expected_outcome=_combat_outcome(cell, enemy),
        confidence=_confidence_for(cell.get("net_swing")),
        source_tag=SOURCE_TAG,
    )

    economy = cell.get("economy") if isinstance(cell.get("economy"), dict) else {}
    recall = str(economy.get("recall") or "")
    if recall in _RECALL_LABELS:
        b = CoachChoice(
            key="B",
            label=_RECALL_LABELS[recall],
            expected_outcome=_recall_outcome(economy, next_item),
            confidence="mid",
            source_tag=SOURCE_TAG,
        )
    else:
        b = CoachChoice(
            key="B",
            label=b_label_alt,
            expected_outcome="play safe; reassess next tick",
            confidence="low",
            source_tag=SOURCE_TAG,
        )
    return [a, b]


def resolve_enemy(
    my_champion: str,
    enemy_comp: Sequence[str],
    mode: str = "sr",
    *,
    payload: Optional[dict] = None,
) -> Optional[str]:
    """First enemy in ``enemy_comp`` the table covers for ``my_champion``.

    Coverage-first: the seed table holds a champion SAMPLE, so most live games
    will not be covered; this returns the first lane opponent that has a cell
    (any band), else None. ``payload`` overrides the loaded table (test seam)."""
    if not my_champion or not enemy_comp:
        return None
    data = payload if payload is not None else load_laning_scenarios(mode)
    scen = data.get("scenarios") if isinstance(data, dict) else None
    per_enemy = scen.get(canonical_champion_id(my_champion)) if isinstance(scen, dict) else None
    if not isinstance(per_enemy, dict):
        return None
    for enemy in enemy_comp:
        if enemy and canonical_champion_id(enemy) in per_enemy:
            return str(enemy)
    return None


def precomputed_choices(
    my_champion: str,
    enemy: str,
    level: object,
    *,
    mana_fraction: Optional[float] = None,
    ult_up: Optional[bool] = None,
    mode: str = "sr",
    payload: Optional[dict] = None,
    next_item: Optional[Tuple[str, int]] = None,
) -> list[CoachChoice]:
    """Two A/B choices for the live (champ vs enemy) laning cell, or ``[]``.

    Resolves the band / mana-state / cd-state from the live inputs, looks the
    cell up in the HZ-A table (``payload`` overrides for tests), and shapes the
    A/B choices. Returns ``[]`` fail-soft on a missing table or uncovered cell.
    """
    try:
        if not my_champion or not enemy:
            return []
        band = band_for_level(level)
        mana = mana_state_for(mana_fraction)
        cd = cd_state_for(ult_up)
        data = payload if payload is not None else load_laning_scenarios(mode)
        my_id = canonical_champion_id(my_champion)
        enemy_id = canonical_champion_id(enemy)
        cell = lookup(data, my_id, enemy_id, band, mana, cd)
        if not cell and band not in GEN_BANDS:
            # item 370 dropped L16 from the generated sweep to halve the
            # full-roster artifact; the documented lvl>=14 fail-soft now reads
            # the highest generated lane band (L11 / 2-item mid) rather than
            # yielding no coaching. ARAM shared-XP rockets champs to 14-18, so
            # without this nearest-band fallback most live ARAM laning ticks
            # land in the empty L16 and never accrue shadow coverage for the
            # flip gate. Descend-only: rescues the level axis, never the pair /
            # mana / cd axes (a genuinely uncovered cell still yields []).
            fallback_band = GEN_BANDS[-1] if GEN_BANDS else band
            cell = lookup(data, my_id, enemy_id, fallback_band, mana, cd)
        if not cell:
            return []
        return _build_choices(cell, enemy, next_item=next_item)
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return []


# Re-export so a caller never reaches past this module for the band set.
__all__ = [
    "LEVEL_BANDS",
    "SOURCE_TAG",
    "band_for_level",
    "mana_state_for",
    "cd_state_for",
    "resolve_enemy",
    "precomputed_choices",
]
