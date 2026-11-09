"""s156 S5 (C7): ONE authoritative Summoner's Rift objective schedule.

Before s156 core/event_callouts.py (Herald 14:00) and
game_reader/snapshot_normalizer.py (Herald 8:00, Baron == Atakhan == 20:00)
disagreed and neither cited a patch. core/sr_schedule.py is now the single
source; these tests pin that every consumer reads it, that every row carries a
status + source, and that the web gauge mirror matches.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import core.decision_detector as dd
import core.event_callouts as ec
import core.macro_context as mc
import core.sr_schedule as sched
from game_reader import snapshot_normalizer as sn

ROOT = Path(__file__).resolve().parent.parent
GAUGES_JS = ROOT / "web" / "js" / "panels" / "objective_gauges.js"


def _sr_rows(gt, events=None):
    out = ec.next_callouts("sr", gt, 1, 0, max_n=None, objective_events=events)
    return {c["tag"]: c for c in out if c.get("kind") == "objective"}


class ScheduleSourcesTests(unittest.TestCase):
    def test_every_row_has_status_and_source(self):
        for key, row in sched.SCHEDULE.items():
            self.assertIn(row.status, sched.STATUSES, key)
            self.assertTrue(row.source.strip(), key)

    def test_removed_rows_have_no_value(self):
        self.assertIsNone(sched.value("atakhan_first"))
        self.assertIsNone(sched.value("plates_fall"))
        self.assertIsNone(sched.value("voidgrubs_respawn"))
        self.assertEqual(sched.SCHEDULE["atakhan_first"].status,
                         sched.STATUS_REMOVED)

    def test_required_value_of_a_removed_row_raises_a_real_error(self):
        # s156 C9: a real exception, not an assert that python -O strips.
        with self.assertRaises(ValueError):
            sched._req("atakhan_first")

    def test_official_rows_cite_a_patch(self):
        for key, row in sched.SCHEDULE.items():
            if row.status == sched.STATUS_OFFICIAL:
                self.assertRegex(row.source, r"P25|P26|D26", key)

    def test_unverified_rows_say_so(self):
        # Honest marking: a guess is never labelled official / recorded.
        for key in ("herald_despawn", "elder_after_soul", "baron_buff",
                    "inhib_respawn", "voidgrubs_window_end"):
            self.assertEqual(sched.SCHEDULE[key].status,
                             sched.STATUS_UNVERIFIED, key)

    def test_current_values(self):
        self.assertEqual(sched.DRAGON_FIRST_S, 300.0)
        self.assertEqual(sched.VOIDGRUBS_FIRST_S, 480.0)
        self.assertEqual(sched.HERALD_FIRST_S, 900.0)
        self.assertEqual(sched.BARON_FIRST_S, 1200.0)
        self.assertEqual(sched.BARON_RESPAWN_S, 360.0)

    def test_legacy_herald_despawn_refuted(self):
        # A recorded 16.x herald kill at 1186.1s refutes the 19:45 (1185s) cut.
        self.assertGreater(sched.HERALD_DESPAWN_S, 1186.1)


class ConsumersAgreeTests(unittest.TestCase):
    def test_event_callouts_reads_schedule(self):
        self.assertEqual(ec.SR_DRAGON_FIRST_S, sched.DRAGON_FIRST_S)
        self.assertEqual(ec.SR_DRAGON_RESPAWN_S, sched.DRAGON_RESPAWN_S)
        self.assertEqual(ec.SR_BARON_FIRST_S, sched.BARON_FIRST_S)
        self.assertEqual(ec.SR_BARON_RESPAWN_S, sched.BARON_RESPAWN_S)
        self.assertEqual(ec._SR_RIFT_HERALD_S, sched.HERALD_FIRST_S)
        self.assertEqual(ec._SR_HERALD_DESPAWN_S, sched.HERALD_DESPAWN_S)
        self.assertEqual(ec._SR_ELDER_AFTER_SOUL_S, sched.ELDER_AFTER_SOUL_S)
        self.assertEqual(ec._SR_ELDER_RESPAWN_S, sched.ELDER_RESPAWN_S)
        self.assertEqual(ec._INHIB_RESPAWN_S, sched.INHIB_RESPAWN_S)
        self.assertEqual(ec._BARON_BUFF_S, sched.BARON_BUFF_S)
        self.assertEqual(ec._ELDER_BUFF_S, sched.ELDER_BUFF_S)

    def test_normalizer_reads_schedule(self):
        self.assertEqual(sn.FIRST_DRAGON, sched.DRAGON_FIRST_S)
        self.assertEqual(sn.DRAGON_RESPAWN, sched.DRAGON_RESPAWN_S)
        self.assertEqual(sn.FIRST_BARON, sched.BARON_FIRST_S)
        self.assertEqual(sn.BARON_RESPAWN, sched.BARON_RESPAWN_S)
        self.assertEqual(sn.FIRST_RIFT_HERALD, sched.HERALD_FIRST_S)
        self.assertEqual(sn.FIRST_VOIDGRUBS, sched.VOIDGRUBS_FIRST_S)

    def test_normalizer_and_callouts_agree(self):
        # The two consumers that used to disagree.
        self.assertEqual(sn.FIRST_RIFT_HERALD, ec._SR_RIFT_HERALD_S)
        self.assertEqual(sn.FIRST_BARON, ec.SR_BARON_FIRST_S)
        self.assertEqual(sn.FIRST_DRAGON, ec.SR_DRAGON_FIRST_S)
        self.assertEqual(sn.DRAGON_RESPAWN, ec.SR_DRAGON_RESPAWN_S)
        self.assertEqual(sn.BARON_RESPAWN, ec.SR_BARON_RESPAWN_S)

    def test_atakhan_gone_from_both(self):
        self.assertIsNone(sn.FIRST_ATAKHAN)
        self.assertNotIn("atakhan", ec.milestone_line("atakhan").lower())
        self.assertEqual(ec.milestone_line("atakhan"), "")

    def test_decision_detector_and_macro_context_read_schedule(self):
        self.assertEqual(dd._BARON_FIRST_S, sched.BARON_FIRST_S)
        self.assertEqual(dd._DRAGON_FIRST_S, sched.DRAGON_FIRST_S)
        self.assertEqual(mc.SR_BARON_FIRST_S, sched.BARON_FIRST_S)

    def test_normalizer_timer_dict_matches_callout_eta(self):
        # Same clock, same answer: normalizer's dragon/baron countdown ==
        # the callout row's eta at the same game time.
        class _R(sn._NormalizerMixin):
            pass
        r = _R()
        for gt in (0.0, 200.0, 299.0, 1000.0, 1199.0):
            d = r._calc_obj_dict([], gt)
            rows = _sr_rows(gt, [])
            if gt < sched.DRAGON_FIRST_S:
                self.assertEqual(d["dragon"], int(rows["dragon"]["eta_s"]))
            if gt < sched.BARON_FIRST_S:
                self.assertEqual(d["baron"], int(rows["baron"]["eta_s"]))


class CalloutScheduleTests(unittest.TestCase):
    def test_herald_at_900_not_840(self):
        rows = _sr_rows(0.0, None)
        self.assertAlmostEqual(rows["herald"]["eta_s"], 900.0, delta=0.01)

    def test_voidgrubs_row_at_480(self):
        rows = _sr_rows(0.0, None)
        self.assertIn("grubs", rows)
        self.assertAlmostEqual(rows["grubs"]["eta_s"], 480.0, delta=0.01)

    def test_voidgrubs_up_until_window_end_then_gone(self):
        self.assertLessEqual(_sr_rows(600.0, [])["grubs"]["eta_s"], 0)
        self.assertNotIn("grubs",
                         _sr_rows(sched.VOIDGRUBS_WINDOW_END_S + 1, []))

    def test_three_grub_takes_retire_the_row(self):
        ev = [{"name": "voidgrub", "killer_team": "ally",
               "down_at_s": 500.0 + i} for i in range(3)]
        self.assertNotIn("grubs", _sr_rows(560.0, ev))
        # one grub taken: two remain, row stays.
        self.assertIn("grubs", _sr_rows(560.0, ev[:1]))

    def test_no_plates_fall_row(self):
        # Plates are permanent since 26.1; no 14:00 callout at any time.
        for gt in (0.0, 800.0, 840.0, 850.0, 900.0):
            self.assertNotIn("plates", _sr_rows(gt, []))
        self.assertEqual(ec.milestone_line("plates"), "")

    def test_no_atakhan_row(self):
        for gt in (0.0, 1100.0, 1200.0, 1210.0):
            self.assertNotIn("atakhan", _sr_rows(gt, []))

    def test_herald_up_then_retired_by_despawn(self):
        self.assertLessEqual(_sr_rows(950.0, [])["herald"]["eta_s"], 0)
        self.assertNotIn("herald", _sr_rows(sched.HERALD_DESPAWN_S + 1, []))

    def test_herald_still_up_at_recorded_kill_time(self):
        # 1186.1s is a recorded 16.x herald kill: the row must not be gone.
        self.assertIn("herald", _sr_rows(1186.0, []))


class GaugeMirrorTests(unittest.TestCase):
    """web/js/panels/objective_gauges.js literals == core/sr_schedule.py."""

    @classmethod
    def setUpClass(cls):
        cls.js = GAUGES_JS.read_text(encoding="utf-8")

    def _num(self, key):
        m = re.search(rf"{key}:\s*(\d+)", self.js)
        self.assertIsNotNone(m, key)
        return int(m.group(1))

    def test_mirror_values(self):
        self.assertEqual(self._num("drakeFirstS"), int(sched.DRAGON_FIRST_S))
        self.assertEqual(self._num("drakeRespawnS"),
                         int(sched.DRAGON_RESPAWN_S))
        self.assertEqual(self._num("baronFirstS"), int(sched.BARON_FIRST_S))
        self.assertEqual(self._num("baronRespawnS"),
                         int(sched.BARON_RESPAWN_S))
        self.assertEqual(self._num("elderAfterSoulS"),
                         int(sched.ELDER_AFTER_SOUL_S))
        self.assertEqual(self._num("elderRespawnS"),
                         int(sched.ELDER_RESPAWN_S))
        self.assertEqual(self._num("soulSecuredStacks"),
                         sched.SOUL_SECURED_STACKS)

    def test_no_nominal_elder_marker(self):
        # The 35:00 nominal Elder marker was invented (RM-518); gone.
        self.assertNotIn("elderNominalS", self.js)
        self.assertNotIn("2100", self.js)


if __name__ == "__main__":
    unittest.main()
