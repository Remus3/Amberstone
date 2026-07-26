"""R194 slice B - Sundered Sky 6610 overheal-to-bonus-health: MEASURED REFUTE.

ROADMAP RM-116 part (b) filed Sundered Sky's overheal half as
"Meraki-cited and UNMODELLED", with the proposed fix being a copy of
Bloodthirster 3072's ``ItemShield`` Ichorshield shape.

PREMISE CHECK - the Meraki clause is REAL. Meraki bulk 16.14.1, item
6610 "Lightshield Strike", verbatim tail:

    "Excess healing beyond maximum health is converted to bonus health
     for 8 seconds."

So the mechanic exists. What does NOT follow is the proposed model. Two
independent findings, both machine-checked below, say an additive
``ItemShield`` on 6610 would be WRONG:

(1) DOUBLE COUNT. ``ehp.compute_ehp`` puts ``heal_total`` and
    ``shield_any_amped`` in the SAME EHP numerator (``ehp.py`` physical /
    magical / true ehp expressions), so one point of healing and one
    point of bonus health are the same one point of EHP to the scorer.
    ``ehp._collect_heals`` credits ``ItemHeal.resolve_magnitude`` in
    FULL, with no clamp against missing HP - it already assumes zero
    healing is wasted, which is exactly the guarantee the overheal
    conversion provides. Crediting the converted excess a second time as
    a shield would count the same HP twice.

(2) PROVABLY INERT ANYWAY. A correctly clamped overheal term is
    ``max(0, heal_magnitude - missing_hp)``. Under the shipped
    ``ehp._MISSING_HP_SHARE_FOR_HEALS = 0.5`` mid-fight convention,
    ``missing_hp = hp * 0.5`` while Sundered Sky's per-trigger heal is
    ``base_ad + 0.06 * missing_hp``. Swept over the full 173-champion
    roster the worst heal-to-missing-HP ratio is 0.22 (Kled, level 1) -
    the heal never reaches even a quarter of the missing pool, so the
    clamped overheal is identically 0.0 everywhere. A DEFAULT-OFF seam
    that resolves to zero even when switched ON is not a model.

The asymmetry with Bloodthirster is real and is why BT's shape does NOT
transfer. BT's Ichorshield accrues from LIFESTEAL, which ticks on
minions and jungle camps out of combat at full HP - a genuine
pre-fight accrual lane that is disjoint from the in-fight lifesteal
heal pool, which is what ``_effects_data.py`` cites when it justifies
the "full-cap steady-state" assumption. Sundered Sky's heal fires only
off "your next basic attack against a champion" (Meraki), so it has NO
out-of-combat accrual lane - its overheal and its healing are the same
single trigger, mutually exclusive by construction.

VERDICT: no engine change. This file is the guard that pins the
refutation so a later pass cannot silently re-add the double count.
DENY-SWEEP by ID suffix (never by name) found exactly two ids ending in
6610 - SR 6610 and Arena mirror 226610 - and both are covered here.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import (
    _MISSING_HP_SHARE_FOR_HEALS,
    _collect_heals,
    compute_ehp,
)

# SR Sundered Sky plus its Arena mirror. Sourced from an ID-SUFFIX sweep
# of ITEM_EFFECTS and of the DDragon items table, not from a name match -
# DDragon ships one item under several ids with renamed variants.
SUNDERED_SKY_IDS = ("6610", "226610")

# Bloodthirster and its Arena mirror - the shape RM-116 proposed copying.
# Present here only as the untouched-neighbour control.
BLOODTHIRSTER_IDS = ("3072", "223072")

_DS_DATA = Path(__file__).resolve().parents[3] / "data" / "daemon_slayer"


def _meraki_items() -> dict:
    patch = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    blob = json.loads(
        (_DS_DATA / patch / "items_meraki.json").read_text(encoding="utf-8")
    )
    return blob["items"]


class MerakiPremiseTests(unittest.TestCase):
    """The overheal clause is real - the premise CONFIRMS at the data."""

    def test_meraki_6610_states_overheal_converts_to_bonus_health(self) -> None:
        entry = _meraki_items()["6610"]
        self.assertEqual(entry["name"], "Sundered Sky")
        effects = " ".join(p["effects"] for p in entry["passives"])
        self.assertIn("Excess healing beyond", effects)
        self.assertIn("bonus", effects)
        self.assertIn("health", effects)
        self.assertIn("for 8 seconds", effects)

    def test_meraki_6610_heal_half_is_base_ad_plus_missing_health(self) -> None:
        # The half the engine ALREADY models - pinned so the refutation
        # below cannot be read as "nothing about 6610 is modelled".
        effects = " ".join(
            p["effects"] for p in _meraki_items()["6610"]["passives"]
        )
        self.assertIn("heal", effects)
        self.assertIn("missing", effects)

    def test_meraki_3072_overheal_is_a_capped_lifesteal_shield(self) -> None:
        # The asymmetry: BT converts LIFESTEAL overheal into a CAPPED
        # shield. Sundered Sky converts a champion-gated proc heal into
        # an UNCAPPED bonus-health buff. Different accrual lane, so the
        # "full-cap steady-state" justification does not carry over.
        effects = " ".join(
            p["effects"] for p in _meraki_items()["3072"]["passives"]
        )
        self.assertIn("life steal", effects)
        self.assertIn("shield", effects)


class NoOverhealShieldGuardTests(unittest.TestCase):
    """The refutation itself - 6610 must NOT grow an ItemShield."""

    def test_sundered_sky_carries_no_item_shield(self) -> None:
        for item_id in SUNDERED_SKY_IDS:
            with self.subTest(item_id=item_id):
                eff = ITEM_EFFECTS[item_id]
                self.assertIsNone(
                    eff.shield,
                    f"{item_id} grew an ItemShield - Sundered Sky's overheal "
                    f"is already credited in full by its ItemHeal (same EHP "
                    f"numerator), so a shield double counts it. See this "
                    f"module docstring before re-adding.",
                )

    def test_sundered_sky_keeps_its_modelled_heal_half(self) -> None:
        for item_id in SUNDERED_SKY_IDS:
            with self.subTest(item_id=item_id):
                heal = ITEM_EFFECTS[item_id].heal
                self.assertIsNotNone(heal)
                self.assertEqual(heal.base_ad_scaling, 1.0)
                self.assertEqual(heal.missing_hp_pct, 0.06)
                self.assertEqual(heal.ranged_modifier, 0.5)
                self.assertFalse(heal.takedown_gated)

    def test_heal_pool_is_credited_unclamped(self) -> None:
        # The double-count proof: _collect_heals returns the FULL
        # per-trigger magnitude. It never subtracts what would have been
        # wasted at full HP, so the overheal conversion's entire value is
        # already inside heal_total.
        total, sources = _collect_heals(
            ["6610"],
            base_ad=120.0,
            bonus_hp=0.0,
            bonus_ad=0.0,
            is_ranged=False,
            missing_hp=10.0,
        )
        # missing_hp of only 10 means 120 + 0.6 = 120.6 of heal against a
        # 10 HP hole - 110.6 of it is overheal, and the engine credits
        # every point of it regardless.
        self.assertAlmostEqual(total, 120.6)
        self.assertEqual(sources, (("6610", 120.6),))


class OverhealIsInertUnderShippedConventionTests(unittest.TestCase):
    """Even a CORRECTLY clamped overheal term resolves to zero."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _worst_ratio(self, level: int) -> tuple[float, str]:
        worst = (0.0, "")
        for champion in sorted(self.snap.champions):
            result = compute_ehp(
                self.snap, champion, level, item_ids=["6610"], mode="SR"
            )
            payload = result.to_dict()
            heal = sum(
                float(src["heal_hp"])
                for src in payload["heal_sources"]
                if str(src["item_id"]) == "6610"
            )
            missing = float(payload["hp"]) * _MISSING_HP_SHARE_FOR_HEALS
            self.assertGreater(missing, 0.0)
            ratio = heal / missing
            if ratio > worst[0]:
                worst = (ratio, champion)
        return worst

    def test_clamped_overheal_is_zero_across_the_whole_roster(self) -> None:
        # Level 1 is the worst case - base AD is the only level-flat term
        # in the heal while max HP climbs with level, so the heal shrinks
        # relative to the missing pool as the game goes on.
        for level in (1, 18):
            with self.subTest(level=level):
                ratio, champion = self._worst_ratio(level)
                self.assertLess(
                    ratio,
                    1.0,
                    f"level {level}: {champion} reached heal/missing_hp "
                    f"{ratio:.3f} - if this ever crosses 1.0 the clamped "
                    f"overheal term stops being identically zero and RM-116 "
                    f"part (b) is worth re-opening.",
                )

    def test_level_one_worst_case_stays_far_below_the_threshold(self) -> None:
        # Measured 2026-07-26 at ENGINE 1.255.0 / patch 16.14.1: Kled is
        # the roster maximum at 0.220. A generous 0.5 ceiling keeps this
        # from flapping on champion base-stat patches while still failing
        # loudly if the convention or the heal coefficients move a lot.
        ratio, _ = self._worst_ratio(1)
        self.assertLess(ratio, 0.5)

    def test_shipped_missing_hp_share_is_the_assumption_in_play(self) -> None:
        # The whole inertness argument hangs off this constant. If it is
        # retuned downward the refutation needs a re-measure.
        self.assertEqual(_MISSING_HP_SHARE_FOR_HEALS, 0.5)


class UnrelatedEffectsUntouchedTests(unittest.TestCase):
    """Narrowing guard - the refutation must not disturb its neighbours."""

    def test_bloodthirster_shield_lane_is_intact(self) -> None:
        for item_id in BLOODTHIRSTER_IDS:
            with self.subTest(item_id=item_id):
                eff = ITEM_EFFECTS[item_id]
                self.assertIsNotNone(eff.shield)
                self.assertEqual(eff.shield.flat, 165.0)
                self.assertEqual(eff.shield.level_lerp_high_value, 315.0)
                self.assertFalse(eff.shield.default_off)
                # BT's overheal is a shield and NOT an ItemHeal - the
                # mirror image of Sundered Sky, and the reason the shapes
                # are not interchangeable.
                self.assertIsNone(eff.heal)

    def test_deny_sweep_by_id_suffix_finds_exactly_the_two_sundered_skies(
        self,
    ) -> None:
        # By SUFFIX, never by name.
        found = sorted(k for k in ITEM_EFFECTS if k.endswith("6610"))
        self.assertEqual(found, sorted(SUNDERED_SKY_IDS))

    def test_no_other_item_gained_an_overheal_shield(self) -> None:
        # Every ItemEffect that carries BOTH a heal and a shield would be
        # a candidate double count of this exact kind. There are none
        # today; this fails loudly the moment one appears.
        both = sorted(
            k
            for k, e in ITEM_EFFECTS.items()
            if e.heal is not None and e.shield is not None
        )
        self.assertEqual(
            both,
            [],
            f"items carrying both an ItemHeal and an ItemShield: {both} - "
            f"check for the RM-116 part (b) double count before shipping.",
        )
