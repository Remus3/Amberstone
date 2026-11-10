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
  - Knight's Vow (3109): "take 14% of the damage they receive" (live DDragon
    since 16.11.1; Meraki, frozen at content patch 25.15, still prints "redirect
    12%") is an EHP MULTIPLIER ON THE PROTECTED ALLY, not a flat grant, and its
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

Each exclusion is pinned for EVERY id in its family that the catalog actually
contains (re-read at 16.14.1 and still at 16.22.1), not just the bare 4-digit id
(R144). Knight's Vow and Zeke's
each carry two mirrors (``223109`` / ``323109``, ``223050`` / ``323050``) and
Bandlepipes one (``222524``); all were re-read per id and none changed its reason
class - the Vow mirrors still redirect a percentage of the ally's incoming damage,
the Zeke's mirrors still grant the ally nothing, the Bandlepipes mirror still
grants attack speed. Solstice Sleigh has NO mirror in the catalog and correctly
gained none. This matters because ``223109`` IS in the Arena candidate pool and
IS present in ``enchanter_items.json``, so a bare-id-only exclusion was one
patch-data change away from silently pricing a build-dependent redirect.

R144 - MODE-MIRROR COVERAGE (closes the v1 limitation for the SR family).
``core.daemon_slayer_resolver.name_to_id`` hands the engine MIRROR ids, and this
module keyed only bare ids, so a mirror fell through to a silent 0.0. It was not
even a missing-key miss: R143 added the mirror rows to ``enchanter_items.json``
with their per-proc fields deliberately left at 0.0 ("not measured this pass"),
so the lookup SUCCEEDED and returned a zero grant. Measured live at 16.14.1:
``name_to_id("Echoes of Helia", mode="sr")`` returns ``326620``, which priced
0.0 against 61.12 for the bare ``6620``. At 16.22.1 the resolver's per-mode index
is lowest-numeric-id-wins, so the same call now returns the bare ``6620``; the
table below still prices a 32xxxx id that a caller hands over directly.

Fixed by ENUMERATING the mirrors in ``_ALLY_GRANT_MIRROR_SOURCE``, one id at a
time, each admitted only because its OWN catalog description states the identical
grant magnitude as its source (the substrings are machine-guarded in
``tests/test_r144_mirror_slice_a.py`` so a patch that retunes one side fails loudly).
A prefix-strip or an id-normalizing helper would be the natural one-line fix and it
is WRONG here for the same reason R143 recorded: these mirrors are not
magnitude-identical as a family and diverge in both directions on other axes
(Mikael's amp is .12 bare / .15 at 323222 / .12 at Arena 223222).

HELD - the Arena ``22xxxx`` ally-grant mirrors are NOT priced (223107 Redemption,
223190 Locket, 223222 Mikael's, 226620 Helia). Their descriptions confirm the
grant exists in prose ("restore Health to allies", "Grant nearby allies a Shield")
but state NO magnitude, on any of them, in DDragon, and their ``effect`` blocks
carry only cooldowns. Inheriting the base number is not available as a safe
default here the way it was for the ``_item_health_stack`` 223084 COEFFICIENT:
Riot demonstrably retuned the absolute numbers on these exact mirrors (Locket 400
Health vs 200, Mikael's 400 vs 250, Helia 300 vs 200, all still live at 16.22.1),
so a base-nominal carry would be an invented magnitude on an axis with in-hand
evidence of divergence - the RM-102 failure mode. Redemption's Arena amp was a
fourth example (12% vs 10%) from 16.11.1 through 16.15.1; since 16.18.1 the
223107 line reads 10% like the base, and ``enchanter_items.json`` already
carries 0.1. Its heal
still states no number, so the hold stands for it too. Term A ships SR-only and
DEFAULT-OFF, so these stay a measured 0.0 until a live Arena magnitude is sourced.

The ``.hps`` import is LAZY (inside the function) so importing this module at
another module's top level is cycle-free - the ``_hsp_amp`` precedent.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

# Item ids whose ally-facing value is real but deliberately unpriced in v1. See
# the "Documented EXCLUSIONS" block above for the reason class on each.
_ALLY_GRANT_EXCLUDED_ITEM_IDS = frozenset({
    "3109",   # Knight's Vow - ally-build-dependent EHP multiplier, not a stock
    "223109",  # Knight's Vow (Arena mirror) - "take 12% of the damage they receive"
    "323109",  # Knight's Vow (SR mirror)    - "take 14% of the damage they receive"
    "3050",   # Zeke's Convergence - no ally grant at 16.14.1
    "223050",  # Zeke's (Arena mirror) - self Frostfire Tempest only, no ally grant
    "323050",  # Zeke's (SR mirror)    - self Frostfire Tempest only, no ally grant
    "2524",   # Bandlepipes - ally attack speed, not durability
    "222524",  # Bandlepipes (Arena mirror) - still ally attack speed, not durability
    "3876",   # Solstice Sleigh - SR-denied before scoring (no mirror in the catalog)
})

# R144 mode-mirror id -> the SOURCE row whose per-proc formula prices it.
#
# ENUMERATED, never derived. Do NOT replace this with a prefix-strip or an
# id-normalizing helper: mode mirrors are not magnitude-identical as a family and
# the Arena half of these very items is deliberately absent below (see the HELD
# block in the module docstring). Each entry is admitted ONLY because the mirror's
# own 16.14.1 description states the identical grant magnitude as its source; the
# quoted substrings are re-read from the catalog and asserted in
# ``tests/test_r144_mirror_slice_a.py``, so a patch that retunes one side fails
# loudly instead of silently mispricing an ally grant.
_ALLY_GRANT_MIRROR_SOURCE: dict[str, str] = {
    # Redemption - mirror reads "Restore 150 - 350 Health to allied units", verbatim
    # the base line. Same 2.5s beam, same AoE wording.
    "323107": "3107",
    # Locket of the Iron Solari - mirror reads "290 - 360 Shield ... decays over
    # 2.5 seconds", verbatim the base line.
    "323190": "3190",
    # Mikael's Blessing - mirror reads "restore 100 - 250 Health", verbatim the base
    # line, single ally. (Its heal_shield_amp_pct DOES diverge, .15 vs .12 - that
    # field belongs to _hsp_amp and is untouched here; only the per-proc heal is
    # mirrored. Exactly why this table is enumerated and not derived.)
    "323222": "3222",
    # Echoes of Helia - neither side states a number (the base row's 40 + 1.76/level
    # came from a curated source, not this description), but the mirror repeats the
    # defining passive sentence verbatim: "Gain 30% of pre-mitigation damage dealt
    # to champions as Soul Charges. Healing or Shielding an ally consumes all Soul
    # Charges to restore Health." Same model, same magnitude source.
    "326620": "6620",
}


def _coerce_ap(ap: object) -> float:
    """``max(0.0, float(ap))``, with an unusable AP read as 0.0 AP.

    NaN already read 0.0 through the bare clamp (``max`` keeps its first
    argument); +-inf, None and a non-numeric value now do the same instead of
    crediting an infinite AP-scaled grant or raising (S144-D-109).
    """
    try:
        value = float(ap)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(0.0, value)


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

    A mode-mirror id enumerated in ``_ALLY_GRANT_MIRROR_SOURCE`` is priced off its
    SOURCE row (R144). The exclusion set is checked FIRST, on the id as given, so an
    excluded family can never be re-admitted through the mirror table.

    Fail-soft: unknown id, excluded id, empty inventory or any load failure ->
    0.0; never raises. ``patch`` defaults to the current-patch cached formulas.
    A level ``int()`` cannot convert (NaN, +-inf, None, garbage) -> 0.0; an
    unusable ``ap`` reads as 0.0 AP; a non-finite total -> 0.0 (S144-D-109).
    The level clamp itself is the formula's and is untouched (RM-848 family).
    An ``item_id`` whose ``str()`` raises (an int past
    ``sys.get_int_max_str_digits()``, a hostile ``__str__``) is unknown -> 0.0
    (S144-D-131).
    """
    try:
        iid = str(item_id or "")
    except Exception:  # noqa: BLE001 - documented never-raises contract
        return 0.0
    if not iid or iid in _ALLY_GRANT_EXCLUDED_ITEM_IDS:
        return 0.0
    iid = _ALLY_GRANT_MIRROR_SOURCE.get(iid, iid)
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
    try:
        lvl = int(level)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    amp = _coerce_ap(ap)
    shield = max(0.0, formula.shield_per_proc_at(lvl, amp))
    heal = max(0.0, formula.heal_per_proc_at(lvl, amp))
    shield_targets = max(0.0, float(formula.shield_targets_per_proc))
    heal_targets = max(0.0, float(formula.heal_targets_per_proc))
    total = shield * shield_targets + heal * heal_targets
    return total if math.isfinite(total) else 0.0


def total_item_ally_grant_hp(
    item_ids: Optional[Iterable[str | int]],
    level: int,
    ap: float = 0.0,
    patch: Optional[str] = None,
) -> float:
    """Sum ``ally_grant_hp`` across an inventory (additive, fail-soft).

    Returns 0.0 on an empty / None inventory. The seam caller gates on
    ``score_by == "team_blended"`` so a 0.0 return is byte-identical.

    Fail-soft on the inventory shape (S144-D-132): a bare ``str`` / ``int`` id
    is ONE item (a bare ``"3107"`` was read character by character and lost
    its grant); any other non-iterable, or an iterable that raises while
    being read, -> 0.0; an entry whose ``str()`` raises is dropped and the
    rest still count.
    """
    if item_ids is None:
        return 0.0
    if isinstance(item_ids, str) or (
        isinstance(item_ids, int) and not isinstance(item_ids, bool)
    ):
        item_ids = (item_ids,)
    try:
        raw = list(item_ids)
    except Exception:  # noqa: BLE001 - caller iterables are untrusted
        return 0.0
    ids: list[str] = []
    for i in raw:
        if i is None:
            continue
        try:
            s = str(i)
        except Exception:  # noqa: BLE001 - drop the entry, keep the rest
            continue
        if s:
            ids.append(s)
    if not ids:
        return 0.0
    return sum(ally_grant_hp(iid, level, ap, patch) for iid in ids)
