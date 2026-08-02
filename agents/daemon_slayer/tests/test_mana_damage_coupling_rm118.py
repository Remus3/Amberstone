"""RM-118: the champion MANA -> DAMAGE coupling seam (DEFAULT-OFF).

THE DEFECT
----------
``ehp.py`` imports no abilities module and reads zero ``damage_blocks``, so a
champion whose OWN KIT spends its MANA as damage (Blitzcrank R "Static Field":
2 percent of maximum mana as magic damage) gets that second, genuinely-real
payment credited NOWHERE. The tank objective prices a mana item on the health
axis alone and under-ranks it for exactly the champion built to spend the mana.

This is the MANA-axis twin of the shipped RESIST-axis lever
(``_resist_damage_coupling`` / RM-87) and the HEALTH-axis lever
(``_health_damage_coupling`` / RM-91 T1). The three registries are DISJOINT -
zero champion overlap - and ride separate flags on purpose.

WHAT THIS SEAM DOES
-------------------
``rank_items_by_ehp(apply_mana_damage_coupling=True, mana_coupling_strength=X)``
folds a normalized, sort-ONLY credit into ``_base_key``, following the existing
``_conv_key`` / ``_coupling_key`` / ``_health_key`` precedent: no row VALUE is
ever mutated, only the ordering view. DEFAULT-OFF and byte-identical when off.

THE GUARDS HERE
---------------
1. The NAMED byte-identical control - the full ``rank_items_by_ehp`` payload with
   the flags OMITTED hashes to the digest captured from the PRE-CHANGE tree (the
   ``ehp.py`` edit stashed out), and three further arms match it: the flag sent
   explicitly False, the flag ON at strength 0.0, and the flag ON for an UNSEEDED
   champion.
2. The registry population is exactly ONE - Blitzcrank. A silent seed drift fails.
3. Kassadin and Ryze are pinned OUT with the routing reason in the message, so
   the exclusion is never re-widened from memory. They are the negative controls
   and their payloads are byte-identical even with the lane armed.
4. ``coupled_mana_points`` invariants: linear, probability-FREE, monotone, and
   negative inputs floor at zero.
5. The credit is SORT-ONLY - every row's numeric payload is identical armed vs
   off; only the ORDER moves. This is the anti-double-count guard.
6. The lane actually MOVES a mana item, so this is not a stranded seam.
7. A zero-mana candidate earns exactly zero credit even armed.
8. A non-positive mana pool disarms the lane instead of raising ZeroDivisionError.

OFFLINE ONLY: no live :8860, no network.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import unittest
from unittest import mock

from agents.daemon_slayer import ehp as ehp_mod
from agents.daemon_slayer._mana_damage_coupling import (
    _ABILITY_CAST_PROB,
    _CHAMPION_MANA_DAMAGE_COUPLING,
    _ULTIMATE_CAST_PROB,
    ManaDamageCouplingEntry,
    coupled_mana_points,
    mana_damage_coupling,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.engine import build_champion

_SNAP = None

# PIN THE DATA, NOT THE CODE (the RM-91 sibling's rule). The digests below are
# SHA-256 of a full ranking payload, so they are only meaningful against the
# snapshot they were captured on. 16.15.1 is the patch this registry's
# provenance cites, and pinning it explicitly keeps a later DDragon refresh from
# re-breaking controls for reasons that have nothing to do with this feature.
_DIGEST_PATCH = "16.15.1"


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load(patch=_DIGEST_PATCH)
    return _SNAP


# The ONE seeded champion. Tank-primary (champions.json tags ["Tank", "Support"])
# so he routes to /rank-tank and this scorer, and he genuinely buys mana.
_SEEDED = "Blitzcrank"

# The two documented rejects, excluded by ARCHETYPE ROUTE. Both already receive
# their mana term through AbilityContext.caster_max_mp / caster_bonus_mp
# (ability_dps.py:299-300), so seeding either here would double-count.
_REJECTS = {
    "Kassadin": "Assassin-primary (tags ['Assassin', 'Mage']) - routes to ds.burst, "
                "whose AbilityContext already carries caster_max_mp",
    "Ryze": "Mage-primary (tags ['Mage']) - routes to ds.ability, "
            "whose AbilityContext already carries caster_bonus_mp",
}

# An UNSEEDED tank, used as the arm-but-inert control. Malphite is seeded in the
# RM-87 RESIST registry and NOT here, which is exactly the cross-arming the
# separate-flag decision exists to prevent.
_UNSEEDED = "Malphite"

# A manaless champion, used to exercise the POOL guard. Verified on disk:
# compute_ehp(..., "Garen", ...).max_mana == 0.0 at this build.
_MANALESS = "Garen"

# Probe hygiene (reference_ds_probe_empty_build_artifact): NEVER an empty item
# list - an empty build under-ranks amp / complementary items and manufactures
# artifacts. Two real early-tank items, matching the RM-87 / RM-91 siblings.
_BUILD = ("3068", "3047")     # Sunfire Aegis + Plated Steelcaps

# NO truncation (top_n is applied AFTER the sort, so a finite cut changes WHICH
# rows survive and the OFF / ON row SETS stop being comparable).
_TOP_N = None
_LEVEL = 13

# Verified present in the SR candidate pool at this build (measured, not assumed).
_WINTERS_APPROACH = "3119"     # +500 mana, +550 HP
_FROZEN_HEART = "3110"         # +400 mana, +75 armor
_THORNMAIL = "3075"            # +150 HP, +75 armor, ZERO mana - the mutation guard
# Fimbulwinter 3121 and Seraph's Embrace 3040 are DELIBERATELY not used: both are
# gold.purchasable == False at 16.15.1 and are filtered out of the ranked pool, so
# an assertion on them would silently pass on an absent row.

# Operator-tunable lever magnitude. DEFAULT-OFF at 0.0; these runs engage it.
# Measured floor for a visible reorder on Winter's Approach, the largest mana
# grant in the pool - Frozen Heart moves at 1.0 already.
_STRENGTH = 8.0

# SHA-256 of the full ``rank_items_by_ehp(...).to_dict()`` payload captured from
# the PRE-CHANGE tree, with the ehp.py edit stashed OUT via
# ``git stash push -- agents/daemon_slayer/ehp.py`` so the capture ran against
# genuinely unmodified code rather than against this feature's own OFF path.
#
# ONE documented exclusion: the additive ``delta_max_mp`` observability key is
# popped from every row before hashing, because a new key in ``to_dict`` cannot
# by construction be present in a pre-change capture. Its OFF value is pinned
# separately at 0.0 for every row, so nothing is hidden by the exclusion - what
# the digest proves is that no VALUE and no ORDERING moved.
_PRE_CHANGE_DIGESTS = {
    "Blitzcrank": "2e1037ccc940055d7c79698e4b37d8403fef32044b34ae165e40e5b499de3245",
    "Malphite": "2fc0667eebdf2e695772ab522827e9447f3b7ca2943dd8f771c96483252af5fd",
    "Kassadin": "02804a83208d7ffaf980c3466a5b6ba1d65733d97a325b8120aaef2285641acd",
    "Ryze": "836afaf8f544fb1046c010483d507da925ac06502356d0a5bdbd83ea4013bd8d",
}


def _rank(champion: str, **kwargs):
    return rank_items_by_ehp(
        _snap(),
        champion_id=champion,
        level=_LEVEL,
        current_item_ids=list(_BUILD),
        mode="SR",
        enemy_ad_share=0.5,
        enemy_ap_share=0.4,
        top_n=_TOP_N,
        **kwargs,
    )


def _armed(champion: str, strength: float = _STRENGTH):
    return _rank(
        champion,
        apply_mana_damage_coupling=True,
        mana_coupling_strength=strength,
    )


def _order(result) -> tuple[str, ...]:
    return tuple(r.item_id for r in result.ranked)


def _rank_of(result, item_id: str) -> int:
    return _order(result).index(item_id)


def _digest(result, drop_notes: bool = False) -> str:
    payload = result.to_dict()
    for row in payload["ranked"]:
        row.pop("delta_max_mp", None)
    if drop_notes:
        # For an ARMED-but-inert run the ONLY legitimate payload difference is
        # the operator-facing "ON but inert" note, which is positive evidence the
        # lane ran and declined. Callers that drop it assert the note separately.
        payload.pop("notes", None)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RegistryPopulationTests(unittest.TestCase):
    """Exactly ONE champion, re-derived from the patch data."""

    def test_population_is_exactly_one(self) -> None:
        self.assertEqual(
            tuple(_CHAMPION_MANA_DAMAGE_COUPLING),
            (_SEEDED,),
            msg="the mana registry seeds Blitzcrank and nothing else",
        )

    def test_the_entry_is_shaped_and_sourced(self) -> None:
        entry = mana_damage_coupling(_SEEDED)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.max_mp_pct, 2.0)
        self.assertEqual(entry.bonus_mp_pct, 0.0)
        self.assertEqual(entry.pct_base, "total")
        self.assertEqual(entry.conditional_probability, _ULTIMATE_CAST_PROB)
        self.assertEqual(entry.attribute, "Static Field")
        self.assertTrue(entry.note, msg="the entry needs a sourced note")

    def test_one_value_on_the_basis_it_names(self) -> None:
        # The double-count trap: seeded on exactly ONE of the two mana bases, and
        # ``pct_base`` names that same basis, so the credit's numerator and its
        # normalizing pool always read the same pool.
        entry = mana_damage_coupling(_SEEDED)
        self.assertEqual(entry.pct_base, "total")
        self.assertGreater(entry.max_mp_pct, 0.0)
        self.assertEqual(entry.bonus_mp_pct, 0.0)

    def test_ultimate_cadence_sits_below_the_ability_midpoint(self) -> None:
        # Static Field is a 60/40/20s ultimate against the 12-14s cadence
        # ``_ABILITY_CAST_PROB`` was calibrated on, so crediting it at the basic-
        # ability rate would over-model it.
        self.assertLess(_ULTIMATE_CAST_PROB, _ABILITY_CAST_PROB)
        self.assertGreater(_ULTIMATE_CAST_PROB, 0.0)

    def test_fail_soft_on_unknown_and_empty(self) -> None:
        self.assertIsNone(mana_damage_coupling(""))
        self.assertIsNone(mana_damage_coupling("Nobody"))
        self.assertIsNone(mana_damage_coupling("NotAChampion"))

    def test_registries_are_disjoint_from_the_resist_and_health_levers(self) -> None:
        from agents.daemon_slayer._health_damage_coupling import (
            _CHAMPION_HEALTH_DAMAGE_COUPLING,
        )
        from agents.daemon_slayer._resist_damage_coupling import (
            _CHAMPION_RESIST_DAMAGE_COUPLING,
        )
        mana = set(_CHAMPION_MANA_DAMAGE_COUPLING)
        self.assertEqual(
            mana & set(_CHAMPION_RESIST_DAMAGE_COUPLING),
            set(),
            msg="the mana and resist levers must never overlap on a champion",
        )
        self.assertEqual(
            mana & set(_CHAMPION_HEALTH_DAMAGE_COUPLING),
            set(),
            msg="the mana and health levers must never overlap on a champion",
        )


class DocumentedRejectTests(unittest.TestCase):
    """Kassadin and Ryze are pinned OUT so the refutation is not re-widened."""

    def test_rejects_are_absent_from_the_registry(self) -> None:
        for champ, reason in _REJECTS.items():
            with self.subTest(champ=champ):
                self.assertNotIn(
                    champ,
                    _CHAMPION_MANA_DAMAGE_COUPLING,
                    msg=f"{champ} must NOT be seeded: {reason}",
                )
                self.assertIsNone(
                    mana_damage_coupling(champ),
                    msg=f"{champ} must resolve to None: {reason}",
                )

    def test_rejects_are_byte_identical_even_armed(self) -> None:
        # Positive proof the exclusion is real at the CONSUMER, not just in the
        # dict: arming the lane on either reject changes nothing but the note.
        for champ in _REJECTS:
            with self.subTest(champ=champ):
                off = _digest(_rank(champ), drop_notes=True)
                on = _digest(_armed(champ), drop_notes=True)
                self.assertEqual(on, off)

    def test_the_census_is_three_champions_and_only_one_is_seeded(self) -> None:
        # champion_abilities.json 16.15.1 carries caster_max_mp_pct /
        # caster_bonus_mp_pct blocks for exactly Blitzcrank, Kassadin and Ryze.
        census = {_SEEDED, *_REJECTS}
        self.assertEqual(len(census), 3)
        self.assertEqual(set(_CHAMPION_MANA_DAMAGE_COUPLING), {_SEEDED})


class CoupledManaPointsTests(unittest.TestCase):
    """Linear, probability-FREE, monotone, and floored at zero."""

    _ENTRY = ManaDamageCouplingEntry(
        max_mp_pct=2.0, bonus_mp_pct=4.0, pct_base="total",
        conditional_probability=0.35,
    )

    def test_linear_in_each_argument(self) -> None:
        for mp in (0.0, 100.0, 500.0, 1234.5):
            with self.subTest(mp=mp):
                self.assertAlmostEqual(
                    coupled_mana_points(self._ENTRY, mp, 0.0), 0.02 * mp
                )
                self.assertAlmostEqual(
                    coupled_mana_points(self._ENTRY, 0.0, mp), 0.04 * mp
                )

    def test_additive_across_the_two_axes(self) -> None:
        a = coupled_mana_points(self._ENTRY, 300.0, 0.0)
        b = coupled_mana_points(self._ENTRY, 0.0, 200.0)
        self.assertAlmostEqual(
            coupled_mana_points(self._ENTRY, 300.0, 200.0), a + b
        )

    def test_scales_by_two_when_both_inputs_double(self) -> None:
        one = coupled_mana_points(self._ENTRY, 250.0, 175.0)
        two = coupled_mana_points(self._ENTRY, 500.0, 350.0)
        self.assertAlmostEqual(two, 2.0 * one)

    def test_probability_free(self) -> None:
        # The caller applies conditional_probability ONCE, so it must not appear
        # here - otherwise it is applied twice.
        low = ManaDamageCouplingEntry(max_mp_pct=2.0, conditional_probability=0.05)
        high = ManaDamageCouplingEntry(max_mp_pct=2.0, conditional_probability=1.0)
        self.assertEqual(
            coupled_mana_points(low, 500.0, 0.0),
            coupled_mana_points(high, 500.0, 0.0),
        )

    def test_monotone_in_mana(self) -> None:
        prev = -1.0
        for mp in (0.0, 50.0, 100.0, 400.0, 500.0, 900.0):
            with self.subTest(mp=mp):
                cur = coupled_mana_points(self._ENTRY, mp, mp)
                self.assertGreaterEqual(cur, prev)
                prev = cur

    def test_negative_inputs_floor_at_zero(self) -> None:
        for pair in ((-500.0, -500.0), (-1.0, 0.0), (0.0, -1.0)):
            with self.subTest(pair=pair):
                self.assertEqual(coupled_mana_points(self._ENTRY, *pair), 0.0)
        # A negative axis must not cancel a positive one either.
        self.assertAlmostEqual(
            coupled_mana_points(self._ENTRY, 500.0, -500.0), 0.02 * 500.0
        )

    def test_scales_with_the_conversion_magnitude(self) -> None:
        small = ManaDamageCouplingEntry(max_mp_pct=2.0)
        large = ManaDamageCouplingEntry(max_mp_pct=6.0)
        self.assertAlmostEqual(
            coupled_mana_points(large, 500.0, 0.0),
            3.0 * coupled_mana_points(small, 500.0, 0.0),
        )


class ByteIdenticalControlTests(unittest.TestCase):
    """The standing contract: OFF is byte-identical to the pre-change tree."""

    def test_signature_pair_is_default_off_and_appended_at_the_end(self) -> None:
        params = list(inspect.signature(rank_items_by_ehp).parameters)
        self.assertEqual(params[-2:], ["apply_mana_damage_coupling", "mana_coupling_strength"])
        defaults = inspect.signature(rank_items_by_ehp).parameters
        self.assertIs(defaults["apply_mana_damage_coupling"].default, False)
        self.assertEqual(defaults["mana_coupling_strength"].default, 0.0)

    def test_default_call_matches_the_pre_change_digest(self) -> None:
        for champ, digest in _PRE_CHANGE_DIGESTS.items():
            with self.subTest(champ=champ):
                self.assertEqual(_digest(_rank(champ)), digest)

    def test_explicit_false_matches_the_pre_change_digest(self) -> None:
        for champ, digest in _PRE_CHANGE_DIGESTS.items():
            with self.subTest(champ=champ):
                self.assertEqual(
                    _digest(_rank(champ, apply_mana_damage_coupling=False)), digest
                )

    def test_flag_on_at_zero_strength_matches_the_pre_change_digest(self) -> None:
        # Flag ON, strength 0.0 - an exact no-op, note included (the note branch
        # requires strength > 0.0, so nothing is appended).
        for champ, digest in _PRE_CHANGE_DIGESTS.items():
            with self.subTest(champ=champ):
                self.assertEqual(_digest(_armed(champ, strength=0.0)), digest)

    def test_unseeded_champion_is_inert_when_armed(self) -> None:
        self.assertEqual(
            _digest(_armed(_UNSEEDED), drop_notes=True),
            _digest(_rank(_UNSEEDED), drop_notes=True),
        )
        notes = [n for n in _armed(_UNSEEDED).notes if "mana_damage_coupling" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("ON but inert", notes[0])

    def test_every_off_row_carries_a_zero_delta_max_mp(self) -> None:
        # The one key excluded from the digest is pinned here instead, so the
        # exclusion hides nothing.
        for champ in _PRE_CHANGE_DIGESTS:
            with self.subTest(champ=champ):
                for row in _rank(champ).ranked:
                    self.assertEqual(row.delta_max_mp, 0.0)

    def test_negative_strength_is_rejected_at_the_boundary(self) -> None:
        with self.assertRaises(ValueError):
            _armed(_SEEDED, strength=-1.0)


class SortOnlyCreditTests(unittest.TestCase):
    """The anti-double-count guard: values never move, only the ordering."""

    def test_every_numeric_row_value_is_unchanged_when_armed(self) -> None:
        off = {r.item_id: r for r in _rank(_SEEDED).ranked}
        on = {r.item_id: r for r in _armed(_SEEDED).ranked}
        self.assertEqual(set(off), set(on), msg="the candidate SET must not move")
        for item_id, row_on in on.items():
            with self.subTest(item_id=item_id):
                row_off = off[item_id]
                payload_on = row_on.to_dict()
                payload_off = row_off.to_dict()
                # delta_max_mp is the deliberate exception: it is the armed lane's
                # OBSERVABILITY field and is asserted separately below.
                payload_on.pop("delta_max_mp")
                payload_off.pop("delta_max_mp")
                self.assertEqual(payload_on, payload_off)

    def test_only_the_order_may_differ(self) -> None:
        off = _rank(_SEEDED)
        on = _armed(_SEEDED)
        self.assertEqual(sorted(_order(off)), sorted(_order(on)))
        self.assertNotEqual(
            _order(off), _order(on),
            msg="an armed lane that changes no order is a stranded seam",
        )

    def test_the_observability_field_reports_the_real_mana_gain(self) -> None:
        on = {r.item_id: r for r in _armed(_SEEDED).ranked}
        # Measured on disk, items.json 16.15.1 stats.FlatMPPoolMod.
        self.assertEqual(on[_WINTERS_APPROACH].delta_max_mp, 500.0)
        self.assertEqual(on[_FROZEN_HEART].delta_max_mp, 400.0)
        self.assertEqual(on[_THORNMAIL].delta_max_mp, 0.0)


class LaneActuallyMovesTests(unittest.TestCase):
    """Case 5: the seam is LIVE, not stranded."""

    def test_a_mana_item_ranks_strictly_higher_when_armed(self) -> None:
        off = _rank(_SEEDED)
        on = _armed(_SEEDED)
        for item_id in (_WINTERS_APPROACH, _FROZEN_HEART):
            with self.subTest(item_id=item_id):
                # A LOWER index is a HIGHER rank.
                self.assertLess(
                    _rank_of(on, item_id),
                    _rank_of(off, item_id),
                    msg=(
                        f"{item_id} did not rise for {_SEEDED} - if this fails the "
                        "mana seam is INERT and must be reported as such, never "
                        "deleted"
                    ),
                )

    def test_the_rise_grows_with_the_strength(self) -> None:
        off_rank = _rank_of(_rank(_SEEDED), _WINTERS_APPROACH)
        prev = off_rank
        for strength in (_STRENGTH, 20.0, 50.0):
            with self.subTest(strength=strength):
                cur = _rank_of(_armed(_SEEDED, strength=strength), _WINTERS_APPROACH)
                self.assertLessEqual(cur, prev)
                prev = cur
        self.assertLess(prev, off_rank)

    def test_the_armed_note_reports_the_lane(self) -> None:
        notes = [n for n in _armed(_SEEDED).notes if "mana_damage_coupling" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("Static Field", notes[0])
        self.assertIn("2.0% total mana", notes[0])
        self.assertNotIn("inert", notes[0])


class MutationGuardTests(unittest.TestCase):
    """A candidate that grants no mana earns exactly nothing."""

    def test_a_zero_mana_item_earns_zero_credit(self) -> None:
        on = {r.item_id: r for r in _armed(_SEEDED).ranked}
        row = on[_THORNMAIL]
        self.assertEqual(row.delta_max_mp, 0.0)
        entry = mana_damage_coupling(_SEEDED)
        self.assertEqual(
            coupled_mana_points(entry, row.delta_max_mp, row.delta_max_mp), 0.0
        )

    def test_a_zero_mana_item_never_overtakes_a_mana_item_it_trailed(self) -> None:
        # Thornmail may drift in ABSOLUTE index as mana items rise past it; what
        # must never happen is the zero-mana row GAINING on a mana row.
        off, on = _rank(_SEEDED), _armed(_SEEDED)
        for mana_item in (_WINTERS_APPROACH, _FROZEN_HEART):
            with self.subTest(mana_item=mana_item):
                gap_off = _rank_of(off, _THORNMAIL) - _rank_of(off, mana_item)
                gap_on = _rank_of(on, _THORNMAIL) - _rank_of(on, mana_item)
                self.assertGreaterEqual(gap_on, gap_off)

    def test_a_negative_delta_is_returned_unchanged(self) -> None:
        entry = mana_damage_coupling(_SEEDED)
        self.assertEqual(coupled_mana_points(entry, -400.0, -400.0), 0.0)


class PoolGuardTests(unittest.TestCase):
    """A non-positive mana pool disarms the lane, it does not divide by zero."""

    def test_the_manaless_champion_resolves_a_zero_pool(self) -> None:
        result = compute_ehp(
            _snap(), _MANALESS, _LEVEL, item_ids=list(_BUILD), mode="SR"
        )
        self.assertEqual(result.max_mana, 0.0)

    def test_a_seeded_manaless_champion_disarms_instead_of_raising(self) -> None:
        entry = ManaDamageCouplingEntry(
            max_mp_pct=2.0, pct_base="total",
            conditional_probability=_ULTIMATE_CAST_PROB, attribute="Probe",
        )
        with mock.patch.object(ehp_mod, "mana_damage_coupling", return_value=entry):
            armed = _armed(_MANALESS)
            plain = _rank(_MANALESS)
        self.assertEqual(_order(armed), _order(plain))
        notes = [n for n in armed.notes if "mana_damage_coupling" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("ON but inert", notes[0])

    def test_the_seeded_champion_resolves_a_positive_pool(self) -> None:
        result = compute_ehp(
            _snap(), _SEEDED, _LEVEL, item_ids=list(_BUILD), mode="SR"
        )
        self.assertGreater(result.max_mana, 0.0)
        notes = [n for n in _armed(_SEEDED).notes if "mana pool" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn(f"{result.max_mana:.1f}-point", notes[0])


class BonusBasisTests(unittest.TestCase):
    """The ``pct_base == "bonus"`` branch (``ehp.py:3603-3615``).

    No SEEDED entry reaches it - Blitzcrank is ``"total"`` - so without this
    class the branch ships with zero coverage and a future regression there
    would stay green (``feedback_guard_on_nondefault_call_path_is_untested``).
    The RM-87 resist and RM-91 health levers both have live ``"bonus"`` entries;
    this lane's is latent, and latent is not the same as unreachable.

    The branch is exercised through a SYNTHETIC bonus-basis entry rather than by
    re-seeding the registry, so the shipped population stays exactly one.
    """

    # Tear of the Goddess 3070 (+240 mana, purchasable at 16.15.1, and NOT one of
    # the probe candidates) is what makes the bonus pool non-zero. The default
    # _BUILD is Sunfire + Steelcaps, neither of which grants mana, so on that
    # build the bonus pool is legitimately 0.0 and the branch DISARMS - both
    # paths are covered below.
    _MANA_BUILD = ("3068", "3047", "3070")

    def _probe(self, pct_base: str, build: tuple[str, ...] = _BUILD):
        entry = ManaDamageCouplingEntry(
            max_mp_pct=2.0,
            pct_base=pct_base,
            conditional_probability=_ULTIMATE_CAST_PROB,
            attribute="Static Field",
        )
        with mock.patch.object(ehp_mod, "mana_damage_coupling", return_value=entry):
            return rank_items_by_ehp(
                _snap(),
                champion_id=_SEEDED,
                level=_LEVEL,
                current_item_ids=list(build),
                mode="SR",
                enemy_ad_share=0.5,
                enemy_ap_share=0.4,
                top_n=_TOP_N,
                apply_mana_damage_coupling=True,
                mana_coupling_strength=_STRENGTH,
            )

    def _plain(self, build: tuple[str, ...]):
        return rank_items_by_ehp(
            _snap(),
            champion_id=_SEEDED,
            level=_LEVEL,
            current_item_ids=list(build),
            mode="SR",
            enemy_ad_share=0.5,
            enemy_ap_share=0.4,
            top_n=_TOP_N,
        )

    def _bonus_pool(self, build: tuple[str, ...]) -> float:
        resolved = compute_ehp(
            _snap(), _SEEDED, _LEVEL, item_ids=list(build), mode="SR"
        )
        base_mp = float(
            build_champion(
                _snap(), _SEEDED, _LEVEL, item_ids=list(build), mode="SR"
            ).base_stats.get("mp", 0.0)
        )
        self.assertGreater(base_mp, 0.0, "Blitzcrank must have a base mana block")
        return resolved.max_mana - base_mp

    def test_a_manaless_build_gives_a_zero_bonus_pool_and_disarms(self) -> None:
        """The DISARM half of the branch - no item mana means no bonus pool."""
        self.assertEqual(self._bonus_pool(_BUILD), 0.0)
        armed = self._probe("bonus")
        self.assertEqual(_order(armed), _order(self._plain(_BUILD)))
        notes = [n for n in armed.notes if "mana_damage_coupling" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("ON but inert", notes[0])

    def test_the_bonus_branch_resolves_a_smaller_pool_than_total(self) -> None:
        """The LIVE half - a mana item makes the bonus pool positive."""
        resolved = compute_ehp(
            _snap(), _SEEDED, _LEVEL, item_ids=list(self._MANA_BUILD), mode="SR"
        )
        bonus_pool = self._bonus_pool(self._MANA_BUILD)
        self.assertGreater(bonus_pool, 0.0)
        self.assertLess(bonus_pool, resolved.max_mana)
        notes = [
            n for n in self._probe("bonus", self._MANA_BUILD).notes if "mana pool" in n
        ]
        self.assertEqual(len(notes), 1)
        self.assertIn(f"{bonus_pool:.1f}-point", notes[0])
        self.assertIn("bonus", notes[0])

    def test_the_smaller_pool_earns_a_larger_credit(self) -> None:
        """Same percent over a smaller denominator must credit at least as much.

        This is the invariant that makes ``pct_base`` load-bearing rather than
        decorative, and it is why the pool is percent-FREE.
        """
        total = _rank_of(self._probe("total", self._MANA_BUILD), _FROZEN_HEART)
        bonus = _rank_of(self._probe("bonus", self._MANA_BUILD), _FROZEN_HEART)
        off = _rank_of(self._plain(self._MANA_BUILD), _FROZEN_HEART)
        self.assertLess(total, off, "the total basis must already move it")
        self.assertLessEqual(bonus, total)

    def test_the_bonus_branch_is_still_sort_only(self) -> None:
        """Per-row comparison, keyed by item_id - a whole-payload digest would
        differ purely because the ORDER moved, which is the point of the lane."""
        off = {r.item_id: r for r in self._plain(self._MANA_BUILD).ranked}
        on = {r.item_id: r for r in self._probe("bonus", self._MANA_BUILD).ranked}
        self.assertEqual(set(off), set(on), msg="the candidate SET must not move")
        for item_id, row_on in on.items():
            with self.subTest(item_id=item_id):
                payload_on = row_on.to_dict()
                payload_off = off[item_id].to_dict()
                payload_on.pop("delta_max_mp")
                payload_off.pop("delta_max_mp")
                self.assertEqual(payload_on, payload_off)


if __name__ == "__main__":
    unittest.main()
