"""OQ11 (QA69, ENGINE 1.166.0) - static-CD ability-haste consumer.

The wiki sidecar ``static`` bucket (item 233 ``ability_static_cd`` accessor,
name-keyed) finally gets its behavioral consumer: the per-spell DPS path
bridges the priced spell's form NAME to the accessor and, for the
genuinely-static abilities, keeps the engine's own base cooldown instead of
dividing by total ability haste.

HONEST COVERAGE ONLY - an ability is haste-immune iff ALL THREE hold:

  * the raw ``static`` value parses as a single plain positive number
    ("5", "240"); "True" toggle markers + wiki formula strings do not;
  * the ability carries NO wiki ``recharge_ranks`` (a charge ability's
    plain-number static is only the between-cast lockout - the real cadence
    is the haste-affected recharge timer; Amumu Q "Bandage Toss" static "3"
    + recharge 16..12 is the canonical trap and must stay ungated);
  * the parsed value agrees with the engine's own base cooldown at the
    priced rank (Heimerdinger R "UPGRADE!!!" carries static "3" describing
    a different mechanic than its 100/92.5/85/77.5/70 cooldown - disagree
    -> ungated).

Coverage:

  * ``StaticCdParserTests`` - the pure plain-positive-number parser.
  * ``StaticCdGateTests`` - Samira R gated (no haste reduction) while
    sibling Q on the same champ + build is haste-reduced; Amumu Q ungated;
    Heimerdinger R ungated; Swain R form-1 Demonflare gated through the
    form-name bridge.
  * ``AbsentSidecarTests`` - an empty wiki sidecar leaves every spell on
    the pre-gate haste path (byte-identical fallback).
  * ``MarkerFieldTests`` - the ``static_cd`` marker rides ``to_dict`` and
    the haste SUM stays honestly reported on gated spells.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from agents.daemon_slayer.ability_dps import (
    _wiki_static_cd_value,
    compute_ability_dps,
)
from agents.daemon_slayer.data_loader import DataSnapshot

# Black Cleaver (20 AH) + Cosmic Drive (25 AH) = 45 total item AH.
_AH_ITEMS = ["3071", "4629"]
_AH_DIVISOR = 1.45


class StaticCdParserTests(unittest.TestCase):
    """Plain positive number or nothing - the honest-coverage parser."""

    def test_plain_int_string(self) -> None:
        self.assertEqual(_wiki_static_cd_value("3"), 3.0)
        self.assertEqual(_wiki_static_cd_value("240"), 240.0)

    def test_plain_float_string(self) -> None:
        self.assertEqual(_wiki_static_cd_value("5.5"), 5.5)

    def test_toggle_marker_rejected(self) -> None:
        self.assertIsNone(_wiki_static_cd_value("True"))

    def test_wiki_formula_rejected(self) -> None:
        self.assertIsNone(_wiki_static_cd_value("{{pp|22 - (22-10)/17*(x-1)|1 to 20 by 1}}"))
        self.assertIsNone(_wiki_static_cd_value("{{fd|0.5}}"))

    def test_non_positive_rejected(self) -> None:
        self.assertIsNone(_wiki_static_cd_value("0"))
        self.assertIsNone(_wiki_static_cd_value("-5"))

    def test_none_and_empty_rejected(self) -> None:
        self.assertIsNone(_wiki_static_cd_value(None))
        self.assertIsNone(_wiki_static_cd_value(""))
        self.assertIsNone(_wiki_static_cd_value("   "))


class StaticCdGateTests(unittest.TestCase):
    """End-to-end on the live snapshot: gated spells ignore ability haste."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _spell(self, champ: str, key: str, **kw):
        out = compute_ability_dps(
            self.snap, champ, level=18, item_ids=_AH_ITEMS, mode="SR", **kw,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_samira_r_static_ignores_item_haste(self) -> None:
        # Samira R "Inferno Trigger": wiki static "5", no recharge, engine
        # cd (5, 5, 5) - genuinely haste-immune.
        r = self._spell("Samira", "R")
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.base_cooldown, 5.0, places=4)
        self.assertAlmostEqual(r.cooldown, 5.0, places=4)
        self.assertTrue(r.static_cd)

    def test_samira_sibling_q_still_haste_reduced(self) -> None:
        # Sibling non-static spell on the SAME champ + build takes the
        # normal haste division.
        q = self._spell("Samira", "Q")
        self.assertIsNotNone(q)
        self.assertGreater(q.base_cooldown, 0.0)
        self.assertAlmostEqual(q.cooldown, q.base_cooldown / _AH_DIVISOR, places=4)
        self.assertFalse(q.static_cd)

    def test_amumu_q_charge_trap_stays_ungated(self) -> None:
        # Amumu Q "Bandage Toss": wiki static "3" EXISTS and matches the
        # engine's flat 3.0 cd, but recharge_ranks (16..12) mark it a
        # charge ability whose real cadence scales - it must NOT be gated.
        q = self._spell("Amumu", "Q")
        self.assertIsNotNone(q)
        self.assertAlmostEqual(q.base_cooldown, 3.0, places=4)
        self.assertAlmostEqual(q.cooldown, 3.0 / _AH_DIVISOR, places=4)
        self.assertFalse(q.static_cd)

    def test_heimerdinger_r_mismatched_static_stays_ungated(self) -> None:
        # Heimerdinger R "UPGRADE!!!": wiki static "3" describes a different
        # mechanic than the 100/92.5/85/77.5/70 R cooldown - the
        # cross-source agreement clause keeps it on the haste path.
        r = self._spell("Heimerdinger", "R")
        self.assertIsNotNone(r)
        self.assertGreater(r.base_cooldown, 3.0)
        self.assertAlmostEqual(r.cooldown, r.base_cooldown / _AH_DIVISOR, places=4)
        self.assertFalse(r.static_cd)

    def test_swain_demonflare_gated_via_form_name_bridge(self) -> None:
        # The bridge keys on the PRICED FORM's name: Swain R form 1
        # "Demonflare" (static "8", engine cd 8/8/8) gates when the priced
        # form is Demonflare - which the champion_form_index registry
        # selects by DEFAULT for Swain R, so this is live output.
        r = self._spell("Swain", "R", form_index_overrides={"R": 1})
        self.assertIsNotNone(r)
        self.assertEqual(r.form_name, "Demonflare")
        self.assertAlmostEqual(r.base_cooldown, 8.0, places=4)
        self.assertAlmostEqual(r.cooldown, 8.0, places=4)
        self.assertTrue(r.static_cd)

    def test_swain_form0_demonic_ascension_stays_haste_reduced(self) -> None:
        # Form 0 "Demonic Ascension" has no plain-number static row - the
        # name bridge follows the priced form, so it stays haste-reduced.
        r = self._spell("Swain", "R", form_index_overrides={"R": 0})
        self.assertIsNotNone(r)
        self.assertEqual(r.form_name, "Demonic Ascension")
        self.assertAlmostEqual(r.cooldown, r.base_cooldown / _AH_DIVISOR, places=4)
        self.assertFalse(r.static_cd)


class AbsentSidecarTests(unittest.TestCase):
    """No wiki sidecar -> no gate -> the pre-OQ11 haste path, unchanged."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_empty_sidecar_leaves_samira_r_on_haste_path(self) -> None:
        bare = replace(self.snap, wiki_ability_stats={})
        out = compute_ability_dps(
            bare, "Samira", level=18, item_ids=_AH_ITEMS, mode="SR",
        )
        r = next((s for s in out.per_spell if s.key == "R"), None)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.cooldown, 5.0 / _AH_DIVISOR, places=4)
        self.assertFalse(r.static_cd)


class MarkerFieldTests(unittest.TestCase):
    """The marker is appended at the dataclass END with a default and rides
    to_dict; the haste SUM stays honestly reported on gated spells (the gate
    sits on the APPLICATION, after the sum)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_gated_spell_keeps_honest_haste_sum(self) -> None:
        out = compute_ability_dps(
            self.snap, "Samira", level=18, item_ids=_AH_ITEMS, mode="SR",
        )
        r = next((s for s in out.per_spell if s.key == "R"), None)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.total_ability_haste, 45.0, places=4)
        self.assertTrue(r.static_cd)

    def test_to_dict_carries_static_cd(self) -> None:
        out = compute_ability_dps(
            self.snap, "Samira", level=18, item_ids=_AH_ITEMS, mode="SR",
        )
        d = out.to_dict()
        r = next((s for s in d["per_spell"] if s["key"] == "R"), None)
        self.assertIsNotNone(r)
        self.assertIn("static_cd", r)
        self.assertTrue(r["static_cd"])
        q = next((s for s in d["per_spell"] if s["key"] == "Q"), None)
        self.assertFalse(q["static_cd"])


if __name__ == "__main__":
    unittest.main()
