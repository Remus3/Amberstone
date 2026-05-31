"""recharge_ledger.py - time-step charge-availability ledger (item 232).

Answers: "how many casts of a charge-bearing ability are available over a
window of T seconds" using a greedy model.

Greedy model: enter the fight with a full charge pool (max_charges). As the
fight progresses each recharge_s seconds restores one charge. You cast
immediately whenever charges are available, so over window T you accumulate
charges_at_start + floor(T / recharge_s) total casts. The simultaneous-burst
cap (max_charges) binds only on a single instant, not on the running total.

Source resolution priority:
  1. CDragon spell_ammo (slot-keyed, authoritative ~22 ammo champs).
  2. Wiki ability_recharge (name-keyed, supplementary 19 abilities CDragon misses).
  3. "none" when neither source provides data for the given champion/slot.

The module is self-contained. Do NOT edit __init__.py or ENGINE_VERSION when
adding this file.
"""
from __future__ import annotations

from dataclasses import dataclass

# _DEFAULT_RANK_IS_MAX = True
# When rank is None or exceeds the array length, _clamp_rank returns the last
# index (fully-leveled max rank). This is the conservative model: max-rank
# gives the fastest recharge cadence and highest max charges, producing the
# most-favourable cast estimate. Callers can pass an explicit rank to get a
# rank-specific ledger.


def _clamp_rank(rank: int | None, length: int) -> int:
    """Clamp rank to a valid array index.

    rank=None or rank >= length -> last index (max rank, fully leveled).
    rank < 0 -> also last index (sentinel for fully-leveled).
    rank in [0, length-1] -> rank unchanged.
    Mirrors mana_sim._clamp_rank semantics (item 231).
    """
    if length <= 0:
        return 0
    if rank is None or rank < 0:
        return length - 1
    return max(0, min(rank, length - 1))


@dataclass(frozen=True)
class RechargeLedger:
    """Charge-availability ledger for one champion/slot over a fight window."""

    champion: str
    slot: str
    source: str           # "cdragon" | "wiki" | "none"
    recharge_s: float     # seconds per charge at the resolved rank
    max_charges: float    # maximum simultaneous charges at resolved rank
    charges_at_start: float  # charges entering the fight (== max_charges)
    window_s: float       # fight window in seconds
    recharges_in_window: int  # floor(window_s / recharge_s)
    total_casts_available: float  # charges_at_start + recharges_in_window


def _none_ledger(champion: str, slot: str, window_s: float) -> RechargeLedger:
    """Return a zero ledger for when no charge data is available."""
    return RechargeLedger(
        champion=champion,
        slot=slot,
        source="none",
        recharge_s=0.0,
        max_charges=0.0,
        charges_at_start=0.0,
        window_s=round(float(window_s), 3),
        recharges_in_window=0,
        total_casts_available=0.0,
    )


def compute_recharge_ledger(
    snapshot,
    champion: str,
    slot: str,
    window_s: float,
    rank: int | None = None,
    ability_name: str | None = None,
) -> RechargeLedger:
    """Compute a charge-availability ledger for champion/slot over window_s.

    Parameters
    ----------
    snapshot : DataSnapshot
        Live data snapshot (provides spell_ammo and ability_recharge).
    champion : str
        Champion ID (DDragon key, e.g. "Vi", "Caitlyn").
    slot : str
        Ability slot: "Q", "W", "E", or "R".
    window_s : float
        Fight window in seconds. Must be >= 0.
    rank : int | None
        0-based ability rank. None -> last index (max rank, fully leveled).
        Negative -> also last index.
    ability_name : str | None
        Wiki ability name fragment (the part after "Champion/" in the page
        title key). Used only as a fallback when CDragon has no ammo data for
        this slot. Example: "Void Rift" for Vel'Koz E.

    Returns
    -------
    RechargeLedger
        Frozen dataclass with the resolved ledger. Returns a "none" ledger
        (source="none", all zeros) if no charge data is found or on any error.
    """
    try:
        window_s = float(window_s)
        if window_s < 0:
            window_s = 0.0

        source: str = "none"
        recharge_arr: list | None = None
        max_charges: float = 0.0

        # Priority 1: CDragon spell_ammo (slot-keyed, authoritative).
        ammo = snapshot.spell_ammo(champion, slot)
        if ammo is not None:
            raw_recharge = ammo.get("recharge")
            if raw_recharge and isinstance(raw_recharge, list) and any(raw_recharge):
                source = "cdragon"
                recharge_arr = raw_recharge
                raw_max = ammo.get("max")
                if raw_max and isinstance(raw_max, list) and raw_max:
                    idx_m = _clamp_rank(rank, len(raw_max))
                    try:
                        max_charges = float(raw_max[idx_m])
                    except (TypeError, ValueError, IndexError):
                        max_charges = 1.0
                else:
                    max_charges = 1.0

        # Priority 2: wiki ability_recharge (name-keyed, supplementary).
        if source == "none" and ability_name is not None:
            wiki_rr = snapshot.ability_recharge(champion, ability_name)
            if wiki_rr and isinstance(wiki_rr, list):
                source = "wiki"
                recharge_arr = wiki_rr
                max_charges = 1.0  # wiki has no max field

        if source == "none" or recharge_arr is None:
            return _none_ledger(champion, slot, window_s)

        # Resolve rank index into the chosen recharge array.
        idx = _clamp_rank(rank, len(recharge_arr))
        try:
            recharge_s = float(recharge_arr[idx])
        except (TypeError, ValueError, IndexError):
            return _none_ledger(champion, slot, window_s)

        if recharge_s <= 0:
            return _none_ledger(champion, slot, window_s)

        recharge_s = round(recharge_s, 3)
        max_charges = round(max_charges, 2)
        charges_at_start = max_charges

        recharges_in_window: int = int(window_s // recharge_s)
        total_casts_available: float = round(
            charges_at_start + float(recharges_in_window), 2
        )

        return RechargeLedger(
            champion=champion,
            slot=slot,
            source=source,
            recharge_s=recharge_s,
            max_charges=max_charges,
            charges_at_start=charges_at_start,
            window_s=round(window_s, 3),
            recharges_in_window=recharges_in_window,
            total_casts_available=total_casts_available,
        )

    except Exception:  # fail-soft: any error returns a zero ledger
        return _none_ledger(champion, slot, window_s)
