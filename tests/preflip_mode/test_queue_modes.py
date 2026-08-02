"""Unit tests for core.queue_modes.mode_key_from_queue_id.

Pins the LCU queue_id -> dashboard mode_key map so a future map edit
can't silently break the dashboard pre-flip path or the per-mode
coaching-data file selection in dashboard._state_builder.MODE_TO_FILE.
"""
from __future__ import annotations

import unittest

from core.queue_modes import (
    QUEUE_ID_TO_MODE_KEY,
    mode_key_from_queue_id,
)


class TestModeKeyFromQueueId(unittest.TestCase):
    def test_arena_queues_return_arena(self):
        self.assertEqual(mode_key_from_queue_id(1700), "arena")
        self.assertEqual(mode_key_from_queue_id(1710), "arena")

    def test_aram_queues_return_aram(self):
        self.assertEqual(mode_key_from_queue_id(450), "aram")
        self.assertEqual(mode_key_from_queue_id(720), "aram")
        self.assertEqual(mode_key_from_queue_id(920), "aram")

    def test_aram_mayhem_kiwi_queue_returns_aram(self):
        # ARAM Mayhem (KIWI gameMode) reports queueId 2400 - confirmed
        # s220 from the operator's stashed post-game LCU match payload.
        # Pre-fix this was unmapped -> mode_key stayed "client" -> the
        # champ-select bench / quick-swap UI never rendered for Mayhem.
        self.assertEqual(mode_key_from_queue_id(2400), "aram")
        self.assertEqual(mode_key_from_queue_id("2400"), "aram")

    def test_sr_ranked_and_draft_return_sr(self):
        for qid in (400, 420, 430, 440, 480):
            self.assertEqual(mode_key_from_queue_id(qid), "sr",
                             f"queue_id={qid} should map to sr")

    def test_client_visible_tft_queues_return_tft(self):
        # RM-140, operator-directed 2026-08-02: the three TFT queues the
        # client actually shows now pre-flip the dashboard to the TFT panel.
        # Before this they fell through to "client".
        for qid in (1090, 1100, 1130):
            self.assertEqual(mode_key_from_queue_id(qid), "tft",
                             f"queue_id={qid} should map to tft")

    def test_unknown_queue_returns_none(self):
        # kJade "Classic" - deliberately unmapped pending RM-141.
        self.assertIsNone(mode_key_from_queue_id(4300))
        # Brawl - retired from champ-select in s214.
        self.assertIsNone(mode_key_from_queue_id(2300))
        # Random unknown id.
        self.assertIsNone(mode_key_from_queue_id(99999))

    def test_zero_and_negative_return_none(self):
        # LCU reports queueId=0 for custom games + Practice Tool. We
        # don't want to flip to "client" via accident - None signals
        # caller to fall back.
        self.assertIsNone(mode_key_from_queue_id(0))
        self.assertIsNone(mode_key_from_queue_id(-1))

    def test_none_input_returns_none(self):
        self.assertIsNone(mode_key_from_queue_id(None))

    def test_string_input_coerces(self):
        # `champ_select.queue_id` is sourced from `gameData.queue.id`
        # which is sometimes serialized as a string when it round-trips
        # through JSON in older client builds.
        self.assertEqual(mode_key_from_queue_id("1700"), "arena")
        self.assertEqual(mode_key_from_queue_id("450"), "aram")

    def test_invalid_string_returns_none(self):
        self.assertIsNone(mode_key_from_queue_id("not-a-number"))

    def test_all_mapped_values_match_dashboard_mode_to_file(self):
        # Every value in the map must be a key that
        # dashboard._state_builder.MODE_TO_FILE knows how to resolve to
        # a real coaching-data file. Otherwise pre-flip would route the
        # dashboard to a coach_file path that doesn't exist.
        from dashboard._state_builder import MODE_TO_FILE
        for qid, mode_key in QUEUE_ID_TO_MODE_KEY.items():
            self.assertIn(mode_key, MODE_TO_FILE,
                          f"queue_id {qid} maps to unknown mode_key "
                          f"{mode_key!r}")


if __name__ == "__main__":
    unittest.main()
