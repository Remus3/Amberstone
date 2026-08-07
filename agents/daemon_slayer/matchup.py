"""Lane A 1v1 head-to-head matchup engine (DS Lane A, 2026-06-02).

Deterministic substitute for an LLM's "who wins this trade" judgment, so live
coaching can stop round-tripping the laning-trade question through Claude Haiku.

Pure + deterministic: composes ONLY the existing pure scorers
(``burst.compute_burst_damage`` for post-mitigation damage, ``engine.build_champion``
for the defensive stat block, ``mana_sim.compute_mana_bounded_combo`` for the
full-combo kill gate). No LLM, no network. Purely additive - a new module + a new
route; it changes no existing scorer's output.

The core idea: resolve each champion's defensive stats (armor / MR / max HP /
bonus HP) at their level + items, then fire each champion's burst combo INTO the
other's resolved defences. ``compute_burst_damage`` already mitigates against
``target_armor`` / ``target_mr``, so ``total_burst_damage`` IS post-mitigation
damage into the target - do not re-apply armor. The percent of the target's HP
removed by one combo is the trade primitive; ``net_swing`` (A's removal minus B's
removal) is the single who-wins scalar in [-1, 1] (positive = A favored).

MODE (RM-169, measured 2026-08-06 at ENGINE 1.275.0 / patch 16.15.1). ``mode`` is
threaded into every scorer this module composes, yet the result is IDENTICAL for
SR and ARENA at fixed inputs. That is deliberate, not a dropped argument:

* ``engine._apply_mode_modifiers`` early-returns for ``mode != "ARAM"``.
* ``burst``'s only mode term is ``aramDamageDealt``, ARAM-gated, so the
  multiplier is 1.0 for every other mode.
* The ARENA stat-ADDEND axis (45 of 173 champions carry a wiki ``ar`` axis) is
  reachable only via ``build_champion(apply_mode_modifiers=True)``, which
  defaults False and is not exposed by ``compute_burst_damage`` or by this
  module. Default-OFF by DS doctrine.

``ability_dps.compute_ability_dps`` DOES differ by mode (142 of 173 champions at
level 2 itemless) for one reason only: it reads a per-mode MEASURED cast-rate
table (``ult_rates.get_spell_casts_per_sec(name, key, mode)``). Per-cast raw
damage and the resolved stat line are byte-identical between the two modes. This
module is a per-COMBO model with no casts-per-second term, so it has nothing to
read there. The two paths answer different questions; do NOT "fix" one to match
the other. Pinned by ``tests/test_rm169_matchup_mode_characterization.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .burst import compute_burst_damage
from .data_loader import DataSnapshot
from .engine import build_champion

# Operator-tunable verdict thresholds. A combo that removes the target's whole
# HP pool (>= _ALL_IN_KILL_THRESHOLD) and can be fully cast is the all-in line;
# _TRADE_MARGIN is the swing magnitude that turns "even" into a favored trade;
# _EVEN_BAND is the dead-zone where the swing is too small to call.
_ALL_IN_KILL_THRESHOLD = 1.0
_TRADE_MARGIN = 0.10
_EVEN_BAND = 0.05


@dataclass(frozen=True)
class MatchupResult:
    """Resolved 1v1 head-to-head between champ A and champ B.

    ``net_swing`` is the who-wins scalar in [-1, 1] (positive = A favored): the
    fraction of B's effective HP A removes in one combo minus the fraction of A's
    effective HP B removes. ``verdict`` is one of "all_in" / "back_off" / "trade"
    / "even" from the operator-tunable thresholds.
    """

    champ_a: str
    champ_b: str
    level_a: int
    level_b: int
    dmg_a_to_b: float
    dmg_b_to_a: float
    a_hp_eff: float
    b_hp_eff: float
    pct_a_removed: float
    pct_b_removed: float
    net_swing: float
    verdict: str
    a_can_full_combo: bool
    b_can_full_combo: bool
    a_casts_allowed: int
    b_casts_allowed: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champ_a": self.champ_a,
            "champ_b": self.champ_b,
            "level_a": self.level_a,
            "level_b": self.level_b,
            "dmg_a_to_b": self.dmg_a_to_b,
            "dmg_b_to_a": self.dmg_b_to_a,
            "a_hp_eff": self.a_hp_eff,
            "b_hp_eff": self.b_hp_eff,
            "pct_a_removed": self.pct_a_removed,
            "pct_b_removed": self.pct_b_removed,
            "net_swing": self.net_swing,
            "verdict": self.verdict,
            "a_can_full_combo": self.a_can_full_combo,
            "b_can_full_combo": self.b_can_full_combo,
            "a_casts_allowed": self.a_casts_allowed,
            "b_casts_allowed": self.b_casts_allowed,
            "notes": list(self.notes),
        }


def _defensive_stats(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Sequence[str | int]],
    mode: str,
) -> tuple[float, float, float, float]:
    """Resolve (armor, mr, max_hp, bonus_hp) the SAME way the EHP scorer does.

    ``bonus_hp = max(0, hp - base_hp)`` mirrors ``ehp.compute_ehp`` exactly so the
    value fed into the opposing burst's ``target_bonus_hp`` matches what every
    other consumer expects.
    """
    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
    )
    stats = resolved.stats
    base = resolved.base_stats
    armor = float(stats.get("armor", 0.0))
    mr = float(stats.get("mr", 0.0))
    max_hp = float(stats.get("hp", 0.0))
    bonus_hp = max(0.0, max_hp - float(base.get("hp", 0.0)))
    return armor, mr, max_hp, bonus_hp


def _combo_into(
    snapshot: DataSnapshot,
    attacker_id: str,
    level: int,
    item_ids: Optional[Sequence[str | int]],
    mode: str,
    sequence: Optional[Sequence[str]],
    hp_pct: float,
    tgt_armor: float,
    tgt_mr: float,
    tgt_max_hp: float,
    tgt_bonus_hp: float,
):
    """Fire the attacker's burst into the resolved target defences.

    Returns the ``BurstResult`` (``.total_burst_damage`` is post-mitigation into
    the target) plus the resolved combo sequence (so the mana gate walks the SAME
    rotation the burst scored).
    """
    burst = compute_burst_damage(
        snapshot,
        attacker_id,
        level,
        item_ids=item_ids,
        mode=mode,
        target_armor=tgt_armor,
        target_mr=tgt_mr,
        target_max_hp=tgt_max_hp,
        target_bonus_hp=tgt_bonus_hp,
        target_current_hp_pct=hp_pct,
        combo_sequence=sequence,
    )
    return burst


def _can_full_combo(
    attacker_id: str,
    level: int,
    item_ids: Optional[Sequence[str | int]],
    mode: str,
    resolved_sequence: Sequence[str],
    snapshot: DataSnapshot,
) -> tuple[bool, int]:
    """Mana gate: does the attacker have the mana to cast every combo token?

    Walks ``mana_sim.compute_mana_bounded_combo`` over the EXACT sequence the
    burst scored (passed in so the two agree 1:1). A manaless / energy champion
    is never gated, so ``casts_allowed == casts_requested`` and the combo is
    always full. Imported function-level to avoid a module import cycle.
    """
    from .mana_sim import compute_mana_bounded_combo  # noqa: PLC0415 - cycle break

    seq = list(resolved_sequence)
    if not seq:
        return True, 0
    mana = compute_mana_bounded_combo(
        attacker_id,
        level,
        item_ids=item_ids,
        sequence=seq,
        mode=mode,
        snapshot=snapshot,
    )
    # A 0-requested walk means the rotation had no resolvable casts; treat as
    # full (nothing to gate) rather than a false "out of mana".
    if mana.casts_requested <= 0:
        return True, int(mana.casts_allowed)
    return mana.casts_allowed >= mana.casts_requested, int(mana.casts_allowed)


def _classify(
    net_swing: float,
    pct_a_removed: float,
    pct_b_removed: float,
    a_can_full_combo: bool,
) -> str:
    """Map the trade scalars to one of the 4 verdict strings.

    Precedence: all_in (A kills B with a full combo and survives) > back_off (A
    is the one who dies, or the swing is firmly negative) > trade (swing firmly
    positive) > even.
    """
    if (
        pct_b_removed >= _ALL_IN_KILL_THRESHOLD
        and a_can_full_combo
        and pct_a_removed < 1.0
    ):
        return "all_in"
    if net_swing <= -_TRADE_MARGIN or (pct_a_removed >= 1.0 and pct_b_removed < 1.0):
        return "back_off"
    if net_swing >= _TRADE_MARGIN:
        return "trade"
    return "even"


def compute_matchup(
    snapshot: DataSnapshot,
    champ_a_id: str,
    champ_b_id: str,
    level_a: int,
    level_b: int,
    item_ids_a: Optional[Sequence[str | int]] = None,
    item_ids_b: Optional[Sequence[str | int]] = None,
    mode: str = "SR",
    hp_a_pct: float = 1.0,
    hp_b_pct: float = 1.0,
    sequence_a: Optional[Sequence[str]] = None,
    sequence_b: Optional[Sequence[str]] = None,
) -> MatchupResult:
    """Resolve the 1v1 trade between champ A and champ B.

    Composition (all pure, all existing scorers):
      1. Resolve each champion's defensive stats (armor / MR / max HP / bonus HP).
      2. Fire A's burst into B's defences -> ``dmg_a_to_b`` (post-mitigation);
         symmetric for ``dmg_b_to_a``.
      3. Effective HP = max HP scaled by the current-HP-pct assumption.
      4. ``pct_*_removed`` = capped fraction of the target's effective HP removed.
      5. ``net_swing`` = ``pct_b_removed - pct_a_removed`` (positive = A favored).
      6. Mana gate each side's full combo for the kill check.
      7. Verdict from the operator-tunable thresholds.
    """
    notes: list[str] = []

    a_armor, a_mr, a_max_hp, a_bonus_hp = _defensive_stats(
        snapshot, champ_a_id, level_a, item_ids_a, mode,
    )
    b_armor, b_mr, b_max_hp, b_bonus_hp = _defensive_stats(
        snapshot, champ_b_id, level_b, item_ids_b, mode,
    )

    burst_a = _combo_into(
        snapshot, champ_a_id, level_a, item_ids_a, mode, sequence_a,
        hp_b_pct, b_armor, b_mr, b_max_hp, b_bonus_hp,
    )
    burst_b = _combo_into(
        snapshot, champ_b_id, level_b, item_ids_b, mode, sequence_b,
        hp_a_pct, a_armor, a_mr, a_max_hp, a_bonus_hp,
    )
    dmg_a_to_b = float(burst_a.total_burst_damage)
    dmg_b_to_a = float(burst_b.total_burst_damage)

    a_hp_eff = a_max_hp * float(hp_a_pct)
    b_hp_eff = b_max_hp * float(hp_b_pct)

    # Guard a zero / unresolvable HP pool so the ratio never divides by zero;
    # a 0-HP target is treated as fully removed.
    pct_b_removed = 1.0 if b_hp_eff <= 0 else min(1.0, dmg_a_to_b / b_hp_eff)
    pct_a_removed = 1.0 if a_hp_eff <= 0 else min(1.0, dmg_b_to_a / a_hp_eff)
    net_swing = pct_b_removed - pct_a_removed

    a_can_full_combo, a_casts_allowed = _can_full_combo(
        champ_a_id, level_a, item_ids_a, mode, burst_a.combo_sequence, snapshot,
    )
    b_can_full_combo, b_casts_allowed = _can_full_combo(
        champ_b_id, level_b, item_ids_b, mode, burst_b.combo_sequence, snapshot,
    )

    verdict = _classify(net_swing, pct_a_removed, pct_b_removed, a_can_full_combo)

    if not a_can_full_combo:
        notes.append(
            f"{burst_a.champion_name} cannot afford its full combo "
            f"({a_casts_allowed} of {len(burst_a.combo_sequence)} casts)"
        )
    if not b_can_full_combo:
        notes.append(
            f"{burst_b.champion_name} cannot afford its full combo "
            f"({b_casts_allowed} of {len(burst_b.combo_sequence)} casts)"
        )

    return MatchupResult(
        champ_a=burst_a.champion_name,
        champ_b=burst_b.champion_name,
        level_a=burst_a.level,
        level_b=burst_b.level,
        dmg_a_to_b=dmg_a_to_b,
        dmg_b_to_a=dmg_b_to_a,
        a_hp_eff=a_hp_eff,
        b_hp_eff=b_hp_eff,
        pct_a_removed=pct_a_removed,
        pct_b_removed=pct_b_removed,
        net_swing=net_swing,
        verdict=verdict,
        a_can_full_combo=a_can_full_combo,
        b_can_full_combo=b_can_full_combo,
        a_casts_allowed=a_casts_allowed,
        b_casts_allowed=b_casts_allowed,
        notes=tuple(notes),
    )
