"""Per-item GENERAL %DR ("Blessing" / "Safeguard") registry, keyed by item id.

The ITEM-SIDE lane of the champion-only R35 percent-mitigation axis
(``compute_ehp`` ``mit_phys`` / ``mit_mag`` / ``mit_true``, keyed by
``champion_id`` so no item can ever match it - Galio / Garen / Master Yi). An
item passive that reduces ALL incoming champion damage by a percent - UNTARGETED
and every damage type - earns ZERO EHP credit today: ``build_champion`` folds
only the item's flat stats (HP / AP / mana / AH), and no item-keyed general-DR
fold exists.

A genuinely NEW survivability axis, distinct from the three EXISTING item-keyed
DR lanes, which are all damage-TYPE-specific and PHYSICAL-ONLY:
  * R77 ``item_crit_dr_multiplier`` (Randuin's Omen - crit damage only),
  * R80 ``item_aa_dr_multiplier`` (Plated Steelcaps - basic-attack damage only),
  * R86 ``item_enemy_as_slow_multiplier`` (Frozen Heart - enemy AS rate only).
Those three multiply ONLY the physical denominator (``ehp.py`` lines ~1688 /
~1822). "Blessing" / "Safeguard" are UNTARGETED and reduce physical + magical +
TRUE, so this fold multiplies into ALL THREE per-type denominators - and the
true-damage credit is what NO R77 / R80 / R86 fold performs. A live probe (Braum
L13 with Celestial vs the same build without it, R108 / LEDGER) confirmed the
ONLY resolved-stat delta is the item's +200 flat HP and ``true_ehp`` rose by
EXACTLY that +200 (pure HP through the true denominator), so the 25-35% general
DR earns delta==0 on every denominator.

Why a NEW registry / seam (not the champion ``mit_*`` path or the R77/R80/R86
inline multipliers): ``mit_*`` is ``champion_id``-keyed so an item can never
match it - the exact structural gap the sibling ``_item_*`` registries fill. This
lane is applied ALONGSIDE ``mit_*`` (a strictly separate item-keyed multiplier),
so the reported champion ``passive_mitigation_*`` stays the pure champion value.

Mechanic (verbatim sources, patch 16.13.1):
  * Celestial Opposition 3869 "Blessing of the Mountain": "Become Blessed to
    reduce incoming champion damage by {{rd|35%|25%}}, lingering for 2 seconds
    after taking damage from a champion" (``items_meraki.json`` 3869). The
    ``{{rd|A|B}}`` wiki template is melee A / ranged B, so 35% melee / 25% ranged
    - resolved by wielder range.
  * Crown of the Shattered Queen 664644 "Safeguard": "You are Safeguarded,
    reducing incoming champion damage by 40%. Safeguard persists for 3 seconds
    after taking champion damage" (``items.json`` DDragon 16.13.1; range-agnostic;
    absent from Meraki, so DDragon is the authoritative magnitude - it matches the
    ``_effects_data`` note for this id).

AMORTIZED-MIDPOINT (NOT EXACT, unlike the R105/R107 stat conversions): the DR
MAGNITUDE is deterministic (35/25 by range, 40 flat) but its UPTIME is conditional
(the buff lingers after a champion hit then discharges into a long cooldown), so
the credited reduction is ``dr * _GENERAL_DR_UPTIME``. ``_GENERAL_DR_UPTIME`` is an
operator-tunable amortization midpoint, NOT a gap-existence question (mirrors
R106's at-max-stacks midpoint / R77/R80/R86's ``_ASSUMED_INCOMING_*_SHARE``).

Registered ids (each confirmed present + live in the DS item index
``data/daemon_slayer/16.13.1/items.json`` with a real map flag before adding):
  * 3869   - Celestial Opposition (SR, ``maps.11``; support-line quest item).
    Meraki-verified 35/25.
  * 664644 - Crown of the Shattered Queen (SR, ``maps.11``; premium mage item).
    DDragon-verified 40 (Meraki-absent).

DOCUMENTED EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class).
These are enumerated MACHINE-READABLY in ``_GENERAL_DR_UNSOURCED_MIRRORS`` below so
the R144 coverage guard can tell "knowingly excluded" apart from "silently missed":
  * 444644 - Crown of the Shattered Queen (Arena mirror, ``maps.30``): the source
    magnitude CONFLICTS unresolvably headless - ``items_meraki.json`` says 50% but
    ``items.json`` (DDragon) says a boosted 90% (an Arena-prismatic variant). With
    no way to confirm the true Arena value without a live Arena game, this mirror
    is EXCLUDED pending a live confirm (mirrors R107's exclusion of the absent
    223083/323083 mirrors - do not seed an unverifiable constant).
    RE-VERIFIED AT 16.14.1 (R144): the conflict is unchanged AND is worse than the
    original note recorded. Meraki carries exactly ONE Crown row in the whole feed,
    keyed 444644, and its text ("50%, lingering for 3 seconds") matches the linger
    of the SR row 664644 (40% / 3s) rather than DDragon's own 444644 (90% / 1.25s)
    - so the feeds disagree on WHICH ITEM the key names, not just on a magnitude.
    Three candidate values (40 / 50 / 90) across two feeds with mismatched keying
    is not a discrepancy a headless pass can adjudicate. The R144 guard re-derives
    this conflict from the shipped feeds every run, so if a future patch refresh
    makes them agree the test FAILS and the exclusion is revisited on evidence
    rather than left to rot.
  * 4644 / 224644 - Crown of the Shattered Queen ids present in the index but with
    NO live map flag (``maps`` all-False) - disabled this patch, never equippable.
    Both state a clean 40% (matching the SR row), so the exclusion is a
    REACHABILITY call, not a magnitude one; the guard asserts they stay map-dead.
    ``name_to_id`` returns 4644 under mode="aram" purely because no ARAM Crown
    exists and the lookup falls through to the legacy shortest-id index - a 0.0
    there is CORRECT, since the item cannot be owned on that map.
  * Anathema's Chains 228001/8001 "Vendetta" (30% reduced damage from a single
    Nemesis): source- AND target-conditional (one specific enemy), with no clean
    whole-fight fold point - a different (single-target) mechanic, not this
    untargeted all-comers credit.
  * Cloak of Starry Night 443059/663059: bundles an already-R106 +20%-total-resist
    term with a resist-ramped, cap-50%, basic-attack-EXCLUDING %DR - a two-seam,
    double-approximation fold, a separate (future) axis, not this clean registry.
  * Celestial's shockwave-SLOW half (unleashed when Blessed ends): a CC utility,
    not a survivability DR - only the damage-reduction half is this credit.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``assume_item_general_dr`` seam on
``compute_ehp`` defaults False; with it OFF the multiplier is the identity 1.0 and
every EHP denominator is unchanged. The live default-ON flip is operator-gated
(mirrors R77/R80/R86/R105/R106/R107).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from typing import Iterable


# Amortization midpoint: the fraction of a fight the general-DR buff is credited as
# active. Celestial's "Blessing" lingers 2s after each champion hit and REFRESHES on
# every hit (high real uptime in a sustained fight); Crown's "Safeguard" breaks on a
# hit then sits on a long cooldown (low real uptime). 0.4 is a conservative shared
# midpoint between the single-engage floor (~0.33 = 2s of a ~6s window) and 0.5,
# pending the live default-ON calibration (a REAL-SR eyeball). Operator-tunable; it
# only scales an ALREADY default-OFF seam, so it never touches the byte-identical
# baseline.
_GENERAL_DR_UPTIME: float = 0.4


# item_id -> (melee_dr, ranged_dr) fraction of incoming champion damage reduced by
# the item's UNTARGETED general-DR passive. "Safeguard" is range-agnostic (both
# equal); "Blessing" splits melee 35 / ranged 25.
_ITEM_GENERAL_DR: dict[str, tuple[float, float]] = {
    "3869":   (0.35, 0.25),  # Celestial Opposition - Blessing (Meraki 16.13.1 {{rd|35%|25%}}); SR maps.11
    "664644": (0.40, 0.40),  # Crown of the Shattered Queen - Safeguard 40% (DDragon 16.13.1, range-agnostic); SR maps.11
}


# Mode-mirror ids of a REGISTERED carrier that are deliberately NOT priced, so the
# R144 coverage guard can distinguish a knowing exclusion from the silent-0.0 defect
# class (a registry keyed on bare ids missing the mirror ``name_to_id`` actually
# returns). Membership here is a documented decision, NOT a magnitude: every id
# below scores the identity 1.0 exactly as an unknown id would. See the DOCUMENTED
# EXCLUSIONS block in the module docstring for the per-id reason and its evidence.
#
# Deliberately NOT a prefix-strip fallback. Resolving 444644 to the base 664644's
# 40% would be the tempting one-liner and would be wrong in the largest measured
# way in this repo: DDragon states the Arena mirror at 90%, and mode mirrors are
# retuned in both directions (R133 Jak'Sho 226665 40% vs base 30%; R143 Dawncore
# 326621 .20 vs base .16). Magnitudes are enumerated per id or they are excluded.
_GENERAL_DR_UNSOURCED_MIRRORS: frozenset[str] = frozenset({
    "444644",  # Arena mirror, maps.30 - LIVE-REACHABLE; feeds conflict 50 vs 90
    "4644",    # maps all-False - never equippable this patch (states 40%)
    "224644",  # maps all-False - never equippable this patch (states 40%)
})


def item_general_dr_multiplier(
    item_ids: Iterable[str | int],
    is_melee: bool,
    assume_item_general_dr: bool = False,
) -> float:
    """All-damage-type denominator multiplier from item-keyed general %DR.

    Returns ``1.0`` (identity) when ``assume_item_general_dr`` is False or no
    equipped item carries a registered general-DR passive - BYTE-IDENTICAL. When
    armed, picks the STRONGEST single registered DR (unique "reduce incoming
    damage" passives over a shared pool -> the MAX, never the product, so a
    synthetic build listing two carriers cannot double-count), resolved by wielder
    range (``is_melee`` picks the melee vs ranged value), and returns
    ``1 - max_dr * _GENERAL_DR_UPTIME``.

    A value ``< 1.0`` shrinks EVERY per-type denominator (physical, magical AND
    true) -> larger EHP across all damage types, the correct "takes less of all
    incoming champion damage -> survives more" direction. The true-damage reach is
    the axis's distinguishing feature vs the physical-only R77/R80/R86 lanes.

    Items not in the registry contribute nothing. The default-OFF gating lives in
    ``compute_ehp`` (this helper short-circuits to identity before any item is
    inspected when the flag is False).
    """
    if not assume_item_general_dr:
        return 1.0
    max_dr = 0.0
    for iid in item_ids:
        pair = _ITEM_GENERAL_DR.get(str(iid))
        if pair is None:
            continue
        dr = pair[0] if is_melee else pair[1]
        if dr > max_dr:
            max_dr = dr
    if max_dr <= 0.0:
        return 1.0
    return 1.0 - max_dr * _GENERAL_DR_UPTIME
