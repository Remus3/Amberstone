"""Per-champion kit-weight derivation (core.build_planner.champ_kit_data).

Expands the WP-C1 kit-synergy model from ~6 hand-curated champions to a
genuinely PER-CHAMPION weight vector derived from champions.json ground truth
(damage_distribution + roles/tags + attackrange + attackspeedperlevel +
healing/shielding ratings). The headline guarantee: every one of the 173
champions gets a DISTINCT vector (the WP-C1 fallback collapsed all champs of an
archetype onto a single flat vector).

Ordinal / structural assertions only, per the operator's data-fragile-comparison
rule - never a fragile exact float. ASCII only - use " - " for a clause break.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from core.archetype_picks import get_archetype_for  # noqa: F401 - parity import
from core.build_planner import champ_kit_data as ckd
from core.build_planner.champ_kit_data import (
    _AP_HYBRID_ITEM_IDS,
    _AP_HYBRID_MARKSMAN,
    _AXES,
    derive_kit_weights,
    is_ap_hybrid_marksman,
    is_caster_marksman,
)
from core.build_planner.kit_synergy import AXES as SYN_AXES
from core.build_planner.kit_synergy import kit_weights

REPO = Path(__file__).resolve().parent.parent
_DS = REPO / "data" / "daemon_slayer"


def _roster():
    patch = (_DS / "current.txt").read_text(encoding="utf-8").strip()
    data = json.loads(
        (_DS / patch / "champions.json").read_text(encoding="utf-8")
    ).get("data", {})
    return [(c.get("name") or cid) for cid, c in data.items()]


class AxisContract(unittest.TestCase):
    def test_axes_match_kit_synergy(self):
        # Anti-drift: the leaf module's axis order MUST equal kit_synergy.AXES so
        # the derived vector is a valid kit_weights base.
        self.assertEqual(_AXES, SYN_AXES)

    def test_dense_over_axes(self):
        w = derive_kit_weights("Miss Fortune")
        self.assertIsNotNone(w)
        self.assertEqual(set(w.keys()), set(_AXES))

    def test_blank_and_unknown_return_none(self):
        # None lets kit_synergy fall back to the archetype base (empty/unknown).
        self.assertIsNone(derive_kit_weights(""))
        self.assertIsNone(derive_kit_weights("NotARealChampion"))


class PerChampionDistinct(unittest.TestCase):
    """The headline guarantee - every champion gets a distinct weight vector."""

    def setUp(self):
        self.roster = _roster()

    def test_full_roster_present(self):
        # Guards a clean-checkout stub silently making the distinctness vacuous.
        self.assertGreater(len(self.roster), 150)

    def test_all_champions_distinct(self):
        sigs = {}
        for nm in self.roster:
            w = derive_kit_weights(nm)
            self.assertIsNotNone(w, nm)
            sigs[nm] = tuple(round(w[a], 4) for a in _AXES)
        distinct = len(set(sigs.values()))
        # Effectively all distinct - allow a tiny slack for two champs with a
        # genuinely identical ground-truth profile.
        self.assertGreaterEqual(
            distinct, len(self.roster) - 3,
            f"only {distinct}/{len(self.roster)} distinct per-champ vectors")

    def test_within_archetype_variation(self):
        # Two carries with different magical share / attack range differ - the
        # WP-C1 model gave both the identical flat carry vector.
        mf = derive_kit_weights("Miss Fortune")
        cait = derive_kit_weights("Caitlyn")
        self.assertNotEqual([mf[a] for a in _AXES], [cait[a] for a in _AXES])


class KnownProfiles(unittest.TestCase):
    """Ordinal sanity of the derived weights for archetype exemplars."""

    def test_crit_marksman(self):
        w = derive_kit_weights("Jinx")  # pure-physical ranged marksman
        self.assertGreater(w["crit"], 0.9)
        self.assertGreater(w["AD"], 0.9)
        self.assertLess(w["AP"], 0.2)

    def test_onhit_marksman(self):
        w = derive_kit_weights("Kog'Maw")  # magical-share marksman -> on-hit
        self.assertGreater(w["on-hit"], w["crit"])
        self.assertGreater(w["AS"], 0.7)

    def test_burst_mage(self):
        w = derive_kit_weights("Annie")
        self.assertGreater(w["AP"], 0.9)
        self.assertLess(w["AD"], 0.2)
        self.assertEqual(w["crit"], 0.0)

    def test_assassin_bonus_ad(self):
        w = derive_kit_weights("Zed")
        self.assertGreaterEqual(w["bonusAD"], 0.6)
        self.assertGreater(w["AD"], 0.8)
        self.assertLess(w["AP"], 0.3)

    def test_tank_hp_offense(self):
        w = derive_kit_weights("Malphite")
        self.assertGreater(w["HP-scaling"], 0.9)

    def test_enchanter_ah(self):
        w = derive_kit_weights("Soraka")
        self.assertGreater(w["AH"], 0.7)
        self.assertLess(w["crit"], 0.1)


class WiredIntoKitWeights(unittest.TestCase):
    """The derived base flows through kit_weights for a non-curated champ."""

    def test_noncurated_champ_uses_derived(self):
        # Annie is NOT in _KIT_TRAITS, so kit_weights == derived (no override,
        # and no gate touches her axes; the >=0 clamp is identity here).
        derived = derive_kit_weights("Annie")
        kw = kit_weights("Annie")
        for a in _AXES:
            self.assertAlmostEqual(kw[a], derived[a], places=6, msg=a)


class CasterMarksmanGate(unittest.TestCase):
    """is_caster_marksman gates the carry-coherence dock exemption. The broad
    "Marksman + Mage tag" rule over-included crit / on-hit ADCs that merely carry
    an INCIDENTAL secondary Mage tag (Jhin / Kai'Sa / Varus / Miss Fortune), so
    the coherence dock wrongly spared their Essence Reaver / Eclipse artifacts
    (docs/specs/2026-07-13-ds-build-coherence-refactor.md KNOWN GAP, live-
    confirmed 2026-07-13). Tightened with an ability-AP-scaling floor: a genuine
    ability-caster (Ezreal / Corki / Smolder) scales heavily off AP on its
    spells; a crit auto-attacker does not.
    """

    def test_hybrid_ability_casters_are_caster_marksmen(self):
        # Genuine spellblade / mana caster-marksmen - protected (dock-exempt).
        for champ in ("Ezreal", "Corki", "Smolder"):
            self.assertTrue(is_caster_marksman(champ), champ)

    def test_crit_onhit_mage_tagged_adcs_are_not_caster_marksmen(self):
        # Crit / on-hit ADCs with an incidental secondary Mage tag - NOT exempt;
        # the coherence dock must reach them to strip the ER / Eclipse artifact.
        for champ in ("Jhin", "Kai'Sa", "Varus", "Miss Fortune"):
            self.assertFalse(is_caster_marksman(champ), champ)

    def test_non_mage_marksmen_are_not_caster_marksmen(self):
        # No Mage tag at all - never exempt (unchanged behavior).
        for champ in ("Jinx", "Caitlyn", "Twitch", "Ashe"):
            self.assertFalse(is_caster_marksman(champ), champ)

    def test_unknown_champ_fail_soft(self):
        self.assertFalse(is_caster_marksman(""))
        self.assertFalse(is_caster_marksman("NotARealChampion"))


class ApHybridMarksmanClass(unittest.TestCase):
    """LEAP-07 DD1 - the AP-on-AD-marksman coherence class (the "Zeri class").

    A DISTINCT class from is_caster_marksman: a carry-archetype Marksman whose
    kit genuinely converts ability AP into sim DPS, so the AP-hybrid item set
    (Lich Bane 3100 / Liandry's 6653 + their Arena mirrors) is ON-AXIS rather
    than wasted stat. Explicit per-champion allow-map, membership earned ONLY by
    a measured engine-credit test against a pure-AD-marksman control.

    See docs/specs/leap/LEAP-07-build-coherence-calibration-r2.md "DD1". The
    allow-map ships EMPTY (the measured verdict, re-run at engine 1.245.0 - see
    test_measured_membership_rule_keeps_zeri_out), so the class is a wired-but-
    unpopulated seam and production behavior is byte-identical. These tests
    therefore prove the seam is CONSULTED and REACHABLE, not merely inert.
    """

    def test_item_set_is_the_spec_set(self):
        self.assertEqual(
            _AP_HYBRID_ITEM_IDS,
            frozenset({"3100", "223100", "6653", "226653"}),
            "AP-hybrid item set must stay the spec's Lich Bane / Liandry's pair "
            "plus their Arena mirrors",
        )

    def test_allow_map_ships_empty_and_zeri_is_not_a_member(self):
        # The DD1 decision pin: NO champion qualifies at ship, so every carry
        # marksman keeps the standard dock (byte-identical production behavior).
        self.assertEqual(_AP_HYBRID_MARKSMAN, frozenset())
        for champ in ("Zeri", "Jinx", "Caitlyn", "Ashe", "Ezreal", "Kog'Maw"):
            self.assertFalse(is_ap_hybrid_marksman(champ), champ)

    def test_allow_map_is_consulted_and_name_normalized(self):
        # REACHABILITY, not inertness: seed the allow-map and prove the predicate
        # actually reads it, through the same name normalization the sibling
        # fight-length allow-map uses (case / spacing / apostrophe insensitive).
        with mock.patch.object(ckd, "_AP_HYBRID_MARKSMAN", frozenset({"zeri"})):
            for spelling in ("Zeri", "ZERI", "zeri", " Zeri "):
                self.assertTrue(is_ap_hybrid_marksman(spelling), spelling)
            self.assertFalse(is_ap_hybrid_marksman("Caitlyn"))
        with mock.patch.object(ckd, "_AP_HYBRID_MARKSMAN", frozenset({"kogmaw"})):
            self.assertTrue(is_ap_hybrid_marksman("Kog'Maw"))

    def test_fail_soft_on_blank_and_unknown(self):
        self.assertFalse(is_ap_hybrid_marksman(""))
        self.assertFalse(is_ap_hybrid_marksman(None))
        self.assertFalse(is_ap_hybrid_marksman("NotARealChampion"))

    def test_member_lifts_the_generic_marksman_ap_discount(self):
        """The CLASS BEHAVIOR half wired into the derivation: a member is scored
        on its own kit weights, NOT the generic marksman AP discount (mag*0.3
        at champ_kit_data.derive_kit_weights). Proven by seeding the allow-map
        and observing the AP axis rise - so the seam is live the moment a
        champion qualifies."""
        base = derive_kit_weights("Zeri")
        cait_base = derive_kit_weights("Caitlyn")
        self.assertGreater(base["AP"], 0.0, "control needs a nonzero magic share")
        with mock.patch.object(ckd, "_AP_HYBRID_MARKSMAN", frozenset({"zeri"})):
            member = derive_kit_weights("Zeri")
            cait = derive_kit_weights("Caitlyn")
        self.assertGreater(
            member["AP"], base["AP"],
            "an AP-hybrid member must NOT take the marksman AP discount",
        )
        # Scoped: only the AP axis moves for the member.
        for axis in _AXES:
            if axis != "AP":
                self.assertAlmostEqual(member[axis], base[axis], places=9, msg=axis)
        # Blast-radius guard: a NON-member marksman is untouched by the class.
        self.assertEqual(
            [cait[a] for a in _AXES], [cait_base[a] for a in _AXES],
            "a non-member marksman must not move when the allow-map is seeded",
        )


if __name__ == "__main__":
    unittest.main()
