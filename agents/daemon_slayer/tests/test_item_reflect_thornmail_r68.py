"""R68 (2026-07-03) - ITEM-keyed Thorns reflect under the R49 reflect seam.

Meraki 16.13.1 item 3075 Thornmail passive "Thorns": "When struck by a
basic attack [[on-hit]], deal {{as|20 {{as|(+ 10% '''bonus''' armor)}}
magic damage|magic damage}} to the attacker and, if they are a champion,
inflict them with {{tip|Grievous Wounds}} for 3 seconds." Item 3076
Bramble Vest carries the same trigger at a flat 10 magic damage.

The reflect rides the EXISTING default-OFF R49 ``assume_passive_reflect``
seam (champion-keyed Rammus W since 1.161.0); R68 adds an ITEM-keyed
registry (``_ITEM_REFLECT_OVERRIDES``) + a dedup accessor. Thorns is a
UNIQUE passive (Bramble Vest is Thornmail's component), so owning both
credits the reflect ONCE - the strongest per-proc at the given stats.
Grievous Wounds is NOT modeled: it is a healing debuff, outside this
damage lane (documented in the registry notes).

Mirror ids: the DS 16.13.1 item pool carries Thornmail mirrors 223075
(Arena map-30) + 323075 (SR-flagged mirror id); Bramble mirrors
223076/323076 do NOT exist in the pool and are NOT registered.

Default-OFF is byte-identical: the item registry is never read when
``assume_passive_reflect`` is False.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._passive_reflect_overrides import (
    _ITEM_REFLECT_OVERRIDES,
    PassiveReflectEntry,
    item_reflect_entry,
    reflect_entry,
    reflect_per_proc,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)
_ITEMS_POOL_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"
)

# Caitlyn has NO champion reflect entry -> any reflect credit she gains
# must come from the ITEM path, isolating it from the Rammus W stream.
_NO_THORN_BUILD = ["3047"]  # Plated Steelcaps - armor, no reflect passive.
_THORNMAIL_BUILD = ["3047", "3075"]
_BOTH_THORNS_BUILD = ["3047", "3075", "3076"]


class EngineVersion(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.226.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.226.0")


class ItemRegistryPins(unittest.TestCase):
    """(a) Hand-authored pins against the Meraki 16.13.1 verbatim text."""

    def test_thornmail_3075_pins(self) -> None:
        e = _ITEM_REFLECT_OVERRIDES.get("3075")
        self.assertIsNotNone(e)
        self.assertIsInstance(e, PassiveReflectEntry)
        self.assertEqual(e.base, (20.0,))
        self.assertEqual(e.damage_type, "MAGIC")
        # Thorns scales the caster's BONUS armor only - never total
        # armor / total MR (those are the Rammus W axes).
        self.assertAlmostEqual(e.caster_bonus_armor_pct, 10.0)
        self.assertAlmostEqual(e.caster_armor_pct, 0.0)
        self.assertAlmostEqual(e.caster_mr_pct, 0.0)
        self.assertGreater(e.reflect_cadence_s, 0.0)
        self.assertEqual(e.attribute, "Thorns")
        self.assertIn("Grievous Wounds", e.note)

    def test_bramble_3076_pins(self) -> None:
        e = _ITEM_REFLECT_OVERRIDES.get("3076")
        self.assertIsNotNone(e)
        self.assertEqual(e.base, (10.0,))
        self.assertEqual(e.damage_type, "MAGIC")
        self.assertAlmostEqual(e.caster_bonus_armor_pct, 0.0)
        self.assertAlmostEqual(e.caster_armor_pct, 0.0)
        self.assertAlmostEqual(e.caster_mr_pct, 0.0)
        self.assertEqual(e.attribute, "Thorns")
        self.assertIn("Grievous Wounds", e.note)

    def test_thornmail_mirror_ids_registered(self) -> None:
        # 223075 (Arena map-30) + 323075 exist in the DS pool -> registered
        # with values identical to the base 3075 entry.
        base = _ITEM_REFLECT_OVERRIDES["3075"]
        for mirror in ("223075", "323075"):
            e = _ITEM_REFLECT_OVERRIDES.get(mirror)
            self.assertIsNotNone(e, msg=mirror)
            self.assertEqual(e.base, base.base, msg=mirror)
            self.assertAlmostEqual(
                e.caster_bonus_armor_pct, base.caster_bonus_armor_pct,
                msg=mirror,
            )
            self.assertEqual(e.damage_type, base.damage_type, msg=mirror)

    def test_absent_bramble_mirrors_not_registered(self) -> None:
        # 223076 / 323076 are NOT in the 16.13.1 DS item pool - registering
        # them would be a phantom id the ranker can never see.
        self.assertNotIn("223076", _ITEM_REFLECT_OVERRIDES)
        self.assertNotIn("323076", _ITEM_REFLECT_OVERRIDES)

    def test_every_registered_id_exists_in_ds_pool(self) -> None:
        pool = json.loads(_ITEMS_POOL_PATH.read_text(encoding="utf-8"))["data"]
        for iid in _ITEM_REFLECT_OVERRIDES:
            self.assertIn(iid, pool)


class MerakiTruth(unittest.TestCase):
    """(b) Hermetic drift guard: the registry values derive from the
    vendored Meraki 16.13.1 snapshot text, so a patch changing the Thorns
    numbers fails HERE instead of silently drifting."""

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        cls.texts = {}
        for iid in ("3075", "3076"):
            passives = doc["items"][iid]["passives"]
            thorns = next(
                (p for p in passives if p.get("name") == "Thorns"), None
            )
            assert thorns is not None, f"Meraki {iid} has no 'Thorns' passive"
            cls.texts[iid] = thorns["effects"]

    def test_thornmail_flat_and_bonus_armor_pct(self) -> None:
        # Meraki wiki-markup shape: "deal {{as|20 {{as|(+ 10% '''bonus'''
        # armor)}} magic damage|magic damage}}".
        m = re.search(
            r"deal \{\{as\|(\d+) \{\{as\|\(\+ (\d+)% '''bonus''' armor\)\}\} "
            r"magic damage",
            self.texts["3075"],
        )
        self.assertIsNotNone(
            m, f"Thornmail formula not found in: {self.texts['3075']!r}"
        )
        self.assertEqual(int(m.group(1)), 20)
        self.assertEqual(int(m.group(2)), 10)

    def test_bramble_flat(self) -> None:
        m = re.search(
            r"deal \{\{as\|(\d+) magic damage\}\}", self.texts["3076"]
        )
        self.assertIsNotNone(
            m, f"Bramble formula not found in: {self.texts['3076']!r}"
        )
        self.assertEqual(int(m.group(1)), 10)

    def test_both_trigger_on_basic_attack_and_apply_gw(self) -> None:
        for iid, text in self.texts.items():
            self.assertIn("When struck by a basic attack", text, msg=iid)
            self.assertIn("Grievous Wounds", text, msg=iid)

    def test_registry_matches_meraki_values(self) -> None:
        m = re.search(
            r"deal \{\{as\|(\d+) \{\{as\|\(\+ (\d+)% '''bonus''' armor\)\}\}",
            self.texts["3075"],
        )
        flat, pct = int(m.group(1)), int(m.group(2))
        for iid in ("3075", "223075", "323075"):
            e = _ITEM_REFLECT_OVERRIDES[iid]
            self.assertEqual(e.base[0], float(flat), msg=iid)
            self.assertAlmostEqual(
                e.caster_bonus_armor_pct, float(pct), msg=iid
            )
        b = re.search(
            r"deal \{\{as\|(\d+) magic damage\}\}", self.texts["3076"]
        )
        self.assertEqual(
            _ITEM_REFLECT_OVERRIDES["3076"].base[0], float(b.group(1))
        )


class PerProcMath(unittest.TestCase):
    """(c) reflect_per_proc folds the new caster BONUS armor term."""

    def test_thornmail_per_proc_with_bonus_armor(self) -> None:
        e = _ITEM_REFLECT_OVERRIDES["3075"]
        # 20 + 10% of 150 bonus armor = 35. Total armor / MR contribute 0
        # (caster_armor_pct == caster_mr_pct == 0 on the item entry).
        self.assertAlmostEqual(
            reflect_per_proc(
                e, caster_total_armor=999.0, caster_total_mr=999.0,
                caster_bonus_armor=150.0,
            ),
            35.0,
        )
        # Flat-only at zero bonus armor (the no-build lower bound).
        self.assertAlmostEqual(
            reflect_per_proc(
                e, caster_total_armor=999.0, caster_total_mr=999.0,
                caster_bonus_armor=0.0,
            ),
            20.0,
        )

    def test_bramble_per_proc_flat_only(self) -> None:
        e = _ITEM_REFLECT_OVERRIDES["3076"]
        self.assertAlmostEqual(
            reflect_per_proc(
                e, caster_total_armor=0.0, caster_total_mr=0.0,
                caster_bonus_armor=500.0,
            ),
            10.0,
        )

    def test_negative_bonus_armor_clamps_to_zero(self) -> None:
        e = _ITEM_REFLECT_OVERRIDES["3075"]
        self.assertAlmostEqual(
            reflect_per_proc(
                e, caster_total_armor=0.0, caster_total_mr=0.0,
                caster_bonus_armor=-40.0,
            ),
            20.0,
        )

    def test_rammus_per_proc_unchanged_by_new_kwarg(self) -> None:
        # (g) sibling guard: the champion entry ignores bonus armor
        # (caster_bonus_armor_pct defaults 0.0) - the R49 pin holds with
        # and without the new kwarg.
        e = reflect_entry("Rammus")
        self.assertAlmostEqual(
            reflect_per_proc(e, caster_total_armor=200.0,
                             caster_total_mr=100.0),
            45.0,
        )
        self.assertAlmostEqual(
            reflect_per_proc(e, caster_total_armor=200.0,
                             caster_total_mr=100.0,
                             caster_bonus_armor=500.0),
            45.0,
        )


class DedupAccessor(unittest.TestCase):
    """(f) Thorns is a unique passive - multiple thorn items count ONCE."""

    def test_both_owned_returns_thornmail(self) -> None:
        got = item_reflect_entry(["3075", "3076"], caster_bonus_armor=100.0)
        self.assertIsNotNone(got)
        iid, entry = got
        self.assertEqual(iid, "3075")
        self.assertEqual(entry.base, (20.0,))

    def test_both_owned_thornmail_wins_even_at_zero_bonus_armor(self) -> None:
        # 20 flat > 10 flat: Thornmail is the stronger proc at ANY stats.
        iid, _ = item_reflect_entry(["3076", "3075"], caster_bonus_armor=0.0)
        self.assertEqual(iid, "3075")

    def test_bramble_only(self) -> None:
        iid, entry = item_reflect_entry(["3076"], caster_bonus_armor=0.0)
        self.assertEqual(iid, "3076")
        self.assertEqual(entry.base, (10.0,))

    def test_mirror_ids_resolve(self) -> None:
        for mirror in ("223075", "323075"):
            got = item_reflect_entry([mirror])
            self.assertIsNotNone(got, msg=mirror)
            self.assertEqual(got[0], mirror)

    def test_no_thorn_items_returns_none(self) -> None:
        self.assertIsNone(item_reflect_entry(_NO_THORN_BUILD))
        self.assertIsNone(item_reflect_entry([]))
        self.assertIsNone(item_reflect_entry(None))

    def test_int_ids_normalized(self) -> None:
        got = item_reflect_entry([3075])
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "3075")


class ComputeDpsSeam(unittest.TestCase):
    """(d) DPS consumer: OFF byte-identical; ON folds the item reflect."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_flag_off_byte_identical_with_thorn_items(self) -> None:
        base = compute_dps(self.snap, "Caitlyn", level=11,
                           item_ids=_THORNMAIL_BUILD,
                           target_armor=60, target_mr=40)
        off = compute_dps(self.snap, "Caitlyn", level=11,
                          item_ids=_THORNMAIL_BUILD,
                          target_armor=60, target_mr=40,
                          assume_passive_reflect=False)
        self.assertEqual(base.weighted_dps, off.weighted_dps)
        self.assertEqual(base.phase_dps, off.phase_dps)
        # No SEAM note with the flag off (the build resolver's own notes
        # may still name the Thornmail item - those are not the seam's).
        self.assertFalse(
            any("assume_passive_reflect" in n for n in off.notes)
        )

    def test_flag_on_thornmail_adds_reflect_dps(self) -> None:
        off = compute_dps(self.snap, "Caitlyn", level=11,
                          item_ids=_THORNMAIL_BUILD,
                          target_armor=60, target_mr=40)
        on = compute_dps(self.snap, "Caitlyn", level=11,
                         item_ids=_THORNMAIL_BUILD,
                         target_armor=60, target_mr=40,
                         assume_passive_reflect=True)
        self.assertGreater(on.weighted_dps, off.weighted_dps)
        self.assertTrue(
            any("assume_passive_reflect" in n and "Thorn" in n
                for n in on.notes)
        )

    def test_flag_on_no_thorn_build_byte_identical(self) -> None:
        off = compute_dps(self.snap, "Caitlyn", level=11,
                          item_ids=_NO_THORN_BUILD,
                          target_armor=60, target_mr=40)
        on = compute_dps(self.snap, "Caitlyn", level=11,
                         item_ids=_NO_THORN_BUILD,
                         target_armor=60, target_mr=40,
                         assume_passive_reflect=True)
        self.assertEqual(off.weighted_dps, on.weighted_dps)
        self.assertEqual(off.phase_dps, on.phase_dps)

    def test_dedup_single_note_with_both_thorn_items(self) -> None:
        on = compute_dps(self.snap, "Caitlyn", level=11,
                         item_ids=_BOTH_THORNS_BUILD,
                         target_armor=60, target_mr=40,
                         assume_passive_reflect=True)
        # Filter to the SEAM's reflect notes (build-resolver notes may also
        # name the items) - exactly one, despite two thorn items owned.
        thorn_notes = [
            n for n in on.notes
            if "assume_passive_reflect" in n and "Thorn" in n
        ]
        self.assertEqual(len(thorn_notes), 1)
        # The stronger (unique-passive winner) is Thornmail.
        self.assertIn("Thornmail", thorn_notes[0])

    def test_item_reflect_not_in_per_attack_on_hit(self) -> None:
        # The reflect is an incoming-triggered stream - it must NOT inflate
        # the outgoing per-attack on-hit display.
        off = compute_dps(self.snap, "Caitlyn", level=11,
                          item_ids=_THORNMAIL_BUILD,
                          target_armor=60, target_mr=40)
        on = compute_dps(self.snap, "Caitlyn", level=11,
                         item_ids=_THORNMAIL_BUILD,
                         target_armor=60, target_mr=40,
                         assume_passive_reflect=True)
        self.assertEqual(
            off.per_attack_on_hit_damage, on.per_attack_on_hit_damage
        )

    def test_rammus_champion_path_unchanged_and_stacks_with_item(self) -> None:
        # (g) Rammus W keeps its own stream: with no thorn items the ON
        # delta is the champion reflect alone (a champion-reflect note,
        # no item note); adding Thornmail folds a SECOND, independent
        # stream on top (W reflect and item Thorns stack in game).
        on_no_item = compute_dps(self.snap, "Rammus", level=11,
                                 item_ids=_NO_THORN_BUILD,
                                 target_armor=60, target_mr=40,
                                 assume_passive_reflect=True)
        champ_notes = [
            n for n in on_no_item.notes if "on-being-hit reflect" in n
        ]
        self.assertEqual(len(champ_notes), 1)
        self.assertFalse(any("Thornmail" in n for n in on_no_item.notes))
        on_item = compute_dps(self.snap, "Rammus", level=11,
                              item_ids=_THORNMAIL_BUILD,
                              target_armor=60, target_mr=40,
                              assume_passive_reflect=True)
        self.assertTrue(
            any("assume_passive_reflect" in n and "Thornmail" in n
                for n in on_item.notes)
        )
        self.assertTrue(
            any("on-being-hit reflect" in n for n in on_item.notes)
        )


class ComputeBurstSeam(unittest.TestCase):
    """(e) Burst mirror over _ASSUMED_REFLECT_BURST_WINDOW_S."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_flag_off_byte_identical_with_thorn_items(self) -> None:
        base = compute_burst_damage(self.snap, "Caitlyn", level=11,
                                    item_ids=_THORNMAIL_BUILD,
                                    target_armor=60, target_mr=40)
        off = compute_burst_damage(self.snap, "Caitlyn", level=11,
                                   item_ids=_THORNMAIL_BUILD,
                                   target_armor=60, target_mr=40,
                                   assume_passive_reflect=False)
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_flag_on_thornmail_adds_burst(self) -> None:
        off = compute_burst_damage(self.snap, "Caitlyn", level=11,
                                   item_ids=_THORNMAIL_BUILD,
                                   target_armor=60, target_mr=40)
        on = compute_burst_damage(self.snap, "Caitlyn", level=11,
                                  item_ids=_THORNMAIL_BUILD,
                                  target_armor=60, target_mr=40,
                                  assume_passive_reflect=True)
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)
        self.assertTrue(
            any("assume_passive_reflect" in n and "Thorn" in n
                for n in on.notes)
        )

    def test_flag_on_no_thorn_build_byte_identical(self) -> None:
        off = compute_burst_damage(self.snap, "Caitlyn", level=11,
                                   item_ids=_NO_THORN_BUILD,
                                   target_armor=60, target_mr=40)
        on = compute_burst_damage(self.snap, "Caitlyn", level=11,
                                  item_ids=_NO_THORN_BUILD,
                                  target_armor=60, target_mr=40,
                                  assume_passive_reflect=True)
        self.assertEqual(off.total_burst_damage, on.total_burst_damage)

    def test_dedup_single_thorn_note_in_burst(self) -> None:
        on = compute_burst_damage(self.snap, "Caitlyn", level=11,
                                  item_ids=_BOTH_THORNS_BUILD,
                                  target_armor=60, target_mr=40,
                                  assume_passive_reflect=True)
        thorn_notes = [
            n for n in on.notes
            if "assume_passive_reflect" in n and "Thorn" in n
        ]
        self.assertEqual(len(thorn_notes), 1)
        self.assertIn("Thornmail", thorn_notes[0])

    def test_rammus_burst_keeps_champion_stream(self) -> None:
        on = compute_burst_damage(self.snap, "Rammus", level=11,
                                  item_ids=_THORNMAIL_BUILD,
                                  target_armor=60, target_mr=40,
                                  assume_passive_reflect=True)
        self.assertTrue(
            any("on-being-hit reflect" in n for n in on.notes)
        )
        self.assertTrue(
            any("assume_passive_reflect" in n and "Thornmail" in n
                for n in on.notes)
        )


if __name__ == "__main__":
    unittest.main()
