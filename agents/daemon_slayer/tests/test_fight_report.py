"""Tests for the unified V2 fight-report compose layer (DS V2 S2).

Uses the real ``DataSnapshot.load()`` (mirrors the other substrate tests).
No ENGINE_VERSION / version-string assertions - the report is additive and
carries no engine version.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.fight_report import FightReport, compute_fight_report

_SNAP = DataSnapshot.load()

# A representative crit/AP Lux-ish mana build (items just need to exist).
_LUX_ITEMS = ["3020", "3157", "3089"]


class FightReportComposeTests(unittest.TestCase):
    def test_lux_composes_all_sections(self):
        r = compute_fight_report(
            "Lux", 11, item_ids=_LUX_ITEMS, runes=[8229, 8112],
            mode="SR", target_armor=80, target_mr=60, target_max_hp=2000,
            snapshot=_SNAP,
        )
        self.assertIsInstance(r, FightReport)
        # rune layer: 2 entries, positive burst total.
        self.assertEqual(len(r.rune_entries), 2)
        self.assertGreater(r.rune_burst_total, 0.0)
        # scenario sweep: 2 levels x 1 item set x 3 target profiles = 6 cells.
        self.assertEqual(r.scenario_cells, 6)
        # invariant_violations is a tuple; a normal mage build is clean
        # (physical DPS must be non-increasing in armor).
        self.assertIsInstance(r.invariant_violations, tuple)
        self.assertEqual(len(r.invariant_violations), 0)
        # bounded dps is a non-negative real.
        self.assertGreaterEqual(r.bounded_dps, 0.0)

    def test_lux_to_dict_round_trips_json(self):
        r = compute_fight_report(
            "Lux", 11, item_ids=_LUX_ITEMS, runes=[8229, 8112],
            mode="SR", target_armor=80, target_mr=60, target_max_hp=2000,
            snapshot=_SNAP,
        )
        d = r.to_dict()
        # json.dumps must succeed (no NaN/Inf/non-serializable values).
        s = json.dumps(d, allow_nan=False)
        self.assertIn("rune_entries", s)
        back = json.loads(s)
        # every FightReport field is present in the dict.
        for key in (
            "champion", "champion_name", "level", "mode", "item_ids",
            "runes", "sequence", "resource_type", "mana_pool",
            "mana_regen_per_s", "casts_allowed", "casts_requested",
            "oom_at_t", "bounded_dps", "unbounded_dps", "rune_entries",
            "rune_burst_total", "keystone_amp_mult", "ability_heal_hps",
            "ability_shield_hps", "ability_hps_total", "shred_ability",
            "shred_uplift_pct", "shred_dps_gain", "scenario_cells",
            "invariant_violations", "notes",
        ):
            self.assertIn(key, back, key)
        # invariant_violations serialized as a list of {invariant, detail}.
        self.assertIsInstance(back["invariant_violations"], list)


class ManaResourceTests(unittest.TestCase):
    def test_mana_champ_reports_mana_resource_and_requests_casts(self):
        r = compute_fight_report(
            "Lux", 11, item_ids=_LUX_ITEMS, mode="SR",
            target_armor=80, target_mr=60, target_max_hp=2000, snapshot=_SNAP,
        )
        # partype string is "Mana" (compare case-insensitively).
        self.assertEqual(r.resource_type.lower(), "mana")
        self.assertGreater(r.casts_requested, 0)

    def test_manaless_champ_bounded_equals_unbounded(self):
        # mana_sim ungates non-mana champs: bounded_dps == unbounded_dps
        # byte-for-byte. Garen has no mana resource (partype "None").
        r = compute_fight_report(
            "Garen", 11, item_ids=[], mode="SR",
            target_armor=80, target_mr=60, snapshot=_SNAP,
        )
        self.assertNotEqual(r.resource_type.lower(), "mana")
        self.assertEqual(r.bounded_dps, r.unbounded_dps)


class RuneSectionTests(unittest.TestCase):
    def test_no_runes_zeroes_rune_section(self):
        r = compute_fight_report(
            "Lux", 6, item_ids=[], runes=None, mode="SR", snapshot=_SNAP,
        )
        self.assertEqual(len(r.rune_entries), 0)
        self.assertEqual(r.rune_burst_total, 0.0)
        self.assertEqual(r.keystone_amp_mult, 1.0)

    def test_pta_stacking_amp_multiplier_applied(self):
        # Press the Attack (8005) is a stacking_amp rune -> keystone_amp_mult
        # picks up its 1.08 flat multiplier.
        r = compute_fight_report(
            "Caitlyn", 11, item_ids=[], runes=[8005], mode="SR",
            snapshot=_SNAP,
        )
        self.assertEqual(len(r.rune_entries), 1)
        self.assertEqual(r.rune_entries[0]["proc_type"], "stacking_amp")
        self.assertAlmostEqual(r.keystone_amp_mult, 1.08, places=4)


class AbilityHpsSectionTests(unittest.TestCase):
    def test_enchanter_reports_positive_ability_hps(self):
        # Soraka has active heal blocks (Q + W) -> total ability hps > 0.
        r = compute_fight_report(
            "Soraka", 11, item_ids=[], mode="SR",
            target_armor=80, target_mr=60, snapshot=_SNAP,
        )
        self.assertGreater(r.ability_hps_total, 0.0)


class RechargeSectionTests(unittest.TestCase):
    def test_charge_champ_reports_recharge_slots(self):
        # Caitlyn W (Yordle Snap Trap) is a cdragon charge ability -> the
        # recharge section surfaces it with source="cdragon" + casts > 0.
        r = compute_fight_report(
            "Caitlyn", 13, item_ids=[], mode="SR",
            snapshot=_SNAP, recharge_window_s=10.0,
        )
        self.assertEqual(r.recharge_window_s, 10.0)
        self.assertTrue(r.recharge_slots)
        slot = r.recharge_slots[0]
        self.assertEqual(slot["source"], "cdragon")
        self.assertGreater(slot["total_casts_available"], 0.0)
        # round-trips in to_dict
        self.assertIn("recharge_slots", r.to_dict())

    def test_non_charge_champ_has_empty_recharge_slots(self):
        # Aatrox has no charge-bearing slots -> the section is empty (no raise).
        r = compute_fight_report("Aatrox", 11, item_ids=[], snapshot=_SNAP)
        self.assertEqual(r.recharge_slots, ())


class MissileSectionTests(unittest.TestCase):
    def test_projectile_champ_reports_missile_slots(self):
        # Lux has projectile spells (Q/E speed >= 400) -> missile section
        # surfaces travel-time slots.
        r = compute_fight_report("Lux", 11, item_ids=[], snapshot=_SNAP)
        self.assertTrue(r.missile_slots)
        slot = r.missile_slots[0]
        self.assertIn("travel_time_s", slot)
        self.assertGreaterEqual(slot["travel_time_s"], 0.0)
        self.assertIn("missile_slots", r.to_dict())

    def test_non_projectile_slots_excluded(self):
        # Aatrox Q has no missile (None) and E is a 20 u/s dash artifact -
        # both are NON-projectiles and MUST be absent from missile_slots
        # (only is_projectile slots like R 779.9 are reported).
        r = compute_fight_report("Aatrox", 11, item_ids=[], snapshot=_SNAP)
        reported = {s["slot"] for s in r.missile_slots}
        self.assertNotIn("Q", reported)
        self.assertNotIn("E", reported)


class FailSoftTests(unittest.TestCase):
    def test_unknown_champion_does_not_raise(self):
        # compute_fight_report is fail-soft: an unknown champion is caught
        # per-section and surfaced as notes; it NEVER raises.
        r = compute_fight_report("ZzzNotAChamp", 5, snapshot=_SNAP)
        self.assertIsInstance(r, FightReport)
        self.assertGreater(len(r.notes), 0)
        # the mana section needs the champion to resolve - it is zeroed and
        # records a note (the scenario sweep is fail-soft PER CELL, so it
        # still returns 6 NaN cells rather than zeroing the section count).
        self.assertEqual(r.bounded_dps, 0.0)
        self.assertEqual(r.unbounded_dps, 0.0)
        self.assertTrue(any("mana" in n for n in r.notes))


class AsciiHygieneTests(unittest.TestCase):
    def test_fight_report_source_is_ascii(self):
        src = Path(
            __file__
        ).resolve().parent.parent / "fight_report.py"
        data = src.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 127]
        self.assertEqual(bad, [], f"non-ASCII bytes in fight_report.py: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
