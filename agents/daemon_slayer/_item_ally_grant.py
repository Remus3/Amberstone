"""ENGINE 1.220.0 (Term A, 2026-07-18) - item-side ALLY-granted EHP helper.

Resolves the flat HP an ITEM confers on the buyer's TEAMMATES, in EHP units.
Reads the curated ``enchanter_items.json`` per-proc block - the SAME source
``hps.py`` scores ally throughput from and ``_hsp_amp.py`` reads the amp field
from. No new data file is authored here: the magnitudes, the per-level scaling
and the operator-set ally-reach count already ship in that snapshot.

Used by the DEFAULT-OFF ``score_by="team_blended"`` seam in ``ehp.py``. The seam
caller gates on that flag, so a 0.0 return keeps output byte-identical.

WHY THIS IS NOT A DOUBLE COUNT with the sibling readers of the same file:
  - ``_hsp_amp.sum_wielder_hsp_pct`` reads ONLY ``heal_shield_amp_pct`` (the amp
    percentage), never a per-proc magnitude, and it amplifies the WIELDER's own
    shields. Locket's amp field is 0.0.
  - ``hps.py`` scores ally throughput for the ENCHANTER route. A champion
    reaching ``ehp.py`` is routed to tank, so ``ds.hps`` never scores it.
  - ``_passive_ally_grant_overrides.ally_flat_hp_grant`` is the CHAMPION-ability
    side (Taric W / Braum W), and its consumer adds to the PROTECTED ALLY's EHP
    numerator. This module is the ITEM side and its consumer ranks an item for
    the BUYER. Different inputs, different consumers.

UNIT DISCIPLINE (load-bearing): use the per-proc STOCK
(``shield_per_proc_at`` / ``heal_per_proc_at``, HP) times
``*_targets_per_proc``. NEVER ``*_procs_per_second`` - that yields HP/s, a rate,
and Effective HP is a stock. Mixing the two is exactly the cross-unit mistake
``hybrid.py`` needed a whole normalization layer to paper over.

Documented EXCLUSIONS (deliberately NOT priced - with the reason class):
  - Knight's Vow (3109): "redirect 12% of the pre-mitigation damage they take to
    you" is an EHP MULTIPLIER ON THE PROTECTED ALLY, not a flat grant, and its
    magnitude depends on that ally's build - which this seam cannot see. Same
    doctrine that excludes Zilean R / Akshan W in
    ``_passive_ally_grant_overrides`` ("build-dependent on the PROTECTED ALLY,
    not a granter-side constant"). It carries no per-proc block today, so the
    exclusion is currently a no-op; it is pinned explicitly so a future patch
    that adds one cannot start silently pricing a build-dependent redirect.
  - Zeke's Convergence (3050): at 16.14.1 this grants the ally NOTHING. It is
    self ultimate haste plus a self-centered storm. Absent from the snapshot.
  - Bandlepipes (2524): grants nearby allies ATTACK SPEED, not durability. Not
    an EHP-bearing grant under any unit-honest model. Absent from the snapshot.
  - Solstice Sleigh (3876): hard-denied from the SR candidate pool by
    ``rank._SR_EXCLUDED_ITEM_IDS`` before scoring, so a row would be inert.

v1 LIMITATION: Arena / ARAM mode-mirror ids (the ``2231xx`` / ``3231xx`` family)
are NOT mapped onto their base rows. Term A ships SR-only and DEFAULT-OFF, so
this is unreachable today; map them when the flag is flipped outside SR.

The ``.hps`` import is LAZY (inside the function) so importing this module at
another module's top level is cycle-free - the ``_hsp_amp`` precedent.
"""
from __future__ import annotations

from typing import Iterable, Optional

# Item ids whose ally-facing value is real but deliberately unpriced in v1. See
# the "Documented EXCLUSIONS" block above for the reason class on each.
_ALLY_GRANT_EXCLUDED_ITEM_IDS = frozenset({
    "3109",   # Knight's Vow - ally-build-dependent EHP multiplier, not a stock
    "3050",   # Zeke's Convergence - no ally grant at 16.14.1
    "2524",   # Bandlepipes - ally attack speed, not durability
    "3876",   # Solstice Sleigh - SR-denied before scoring
})


def ally_grant_hp(
    item_id: str | int,
    level: int,
    ap: float = 0.0,
    patch: Optional[str] = None,
) -> float:
    """Return the flat HP one item confers on the buyer's allies, in EHP units.

    ``per-proc stock x targets-per-proc``, summed over the heal and shield
    lanes. The per-level scaling uses the snapshot's own
    ``heal_per_proc_at`` / ``shield_per_proc_at`` helpers, so this module never
    re-implements the level formula.

    A flat shield / heal sits at the TOP of the protected ally's damage stack
    exactly like base HP, so it rides the same armor/MR curve and adds RAW to
    the EHP numerator - the contract ``ehp.py`` already documents for the
    self-shield pool. Both sides of the Term A blend are therefore EHP and no
    cross-unit conversion is introduced.

    Fail-soft: unknown id, excluded id, empty inventory or any load failure ->
    0.0; never raises. ``patch`` defaults to the current-patch cached formulas.
    """
    iid = str(item_id or "")
    if not iid or iid in _ALLY_GRANT_EXCLUDED_ITEM_IDS:
        return 0.0
    try:
        from .hps import EnchanterFormulasSnapshot, load_default_formulas

        snap = (
            load_default_formulas()
            if patch is None
            else EnchanterFormulasSnapshot.load(patch)
        )
    except Exception:
        return 0.0
    formula = snap.formulas.get(iid)
    if formula is None:
        return 0.0
    lvl = int(level)
    amp = max(0.0, float(ap))
    shield = max(0.0, formula.shield_per_proc_at(lvl, amp))
    heal = max(0.0, formula.heal_per_proc_at(lvl, amp))
    shield_targets = max(0.0, float(formula.shield_targets_per_proc))
    heal_targets = max(0.0, float(formula.heal_targets_per_proc))
    return shield * shield_targets + heal * heal_targets


def total_item_ally_grant_hp(
    item_ids: Optional[Iterable[str | int]],
    level: int,
    ap: float = 0.0,
    patch: Optional[str] = None,
) -> float:
    """Sum ``ally_grant_hp`` across an inventory (additive, fail-soft).

    Returns 0.0 on an empty / None inventory. The seam caller gates on
    ``score_by == "team_blended"`` so a 0.0 return is byte-identical.
    """
    ids = [str(i) for i in (item_ids or []) if i is not None and str(i)]
    if not ids:
        return 0.0
    return sum(ally_grant_hp(iid, level, ap, patch) for iid in ids)
