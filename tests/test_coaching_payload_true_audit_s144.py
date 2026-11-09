"""s144 true-audit of core/coaching_payload.py (lane 8, cycle 244).

``validate_coaching_payload`` is called on EVERY /api/state build
(dashboard/_state_builder.py, ``validate_coaching_payload(coach)`` right
after the coach-file read), and the build runs about every
``_STATE_CADENCE_S`` (0.5 s) for as long as RC is up. Its module header
promises it "logs warnings ... but never raises". Findings pinned here:

  F1  a coach file whose ``mode`` is a list / dict made ``_MODE_TO_MODEL
      .get(mode)`` raise TypeError (unhashable), so build_state raised and
      /api/state served 500 (SSE: no event) for as long as the file held
      it. A non-string mode is malformed: False plus one WARNING, never a
      raise. ``None`` / absent stays "no mode" (True), as documented.
  F2  NaN / Infinity in a declared float validated as VALID. Python's json
      reads them, ``json.dumps`` writes them back as bare NaN / Infinity,
      which the browser's JSON.parse rejects - the validator is the one
      place that could have said so.
  F3  one WARNING per error with no cap: a single payload with 30 bad
      team_context rows logged 30 lines per build.
  F4  the SAME warnings were re-logged on every build: one stuck bad field
      is ~2 WARNING lines a second, all day. An unchanged error set now
      logs once (then DEBUG) until it changes or a valid payload resets it.
"""
from __future__ import annotations

import logging
import threading
import unittest

import core.coaching_payload as cp
from core.coaching_payload import validate_coaching_payload

_LOGGER = "rc.coaching_payload"


def _warnings(records):
    return [r for r in records if r.levelno >= logging.WARNING]


class _Base(unittest.TestCase):
    def setUp(self):
        cp._reset_repeat_memo()

    def tearDown(self):
        cp._reset_repeat_memo()


class TestCharacterization(_Base):
    """Behaviour that was already right and must stay so."""

    def test_valid_sr_payload_true_and_silent(self):
        with self.assertNoLogs(_LOGGER, level=logging.WARNING):
            self.assertTrue(validate_coaching_payload(
                {"mode": "sr", "action": "farm", "gold": 1200, "hp_pct": 55.0}))

    def test_wrong_type_field_false_and_names_field(self):
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            self.assertFalse(validate_coaching_payload(
                {"mode": "aram", "level": "high"}))
        self.assertTrue(any("level" in line for line in cm.output))

    def test_missing_mode_is_true(self):
        self.assertTrue(validate_coaching_payload({"action": "x"}))

    def test_none_mode_is_true(self):
        self.assertTrue(validate_coaching_payload({"mode": None}))

    def test_unknown_string_mode_is_true(self):
        self.assertTrue(validate_coaching_payload({"mode": "lobby", "x": 1}))

    def test_non_dict_false_and_warns(self):
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload(["mode", "sr"]))


class TestF1NonStringMode(_Base):
    def test_list_mode_never_raises(self):
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            self.assertFalse(validate_coaching_payload({"mode": ["tft"]}))
        self.assertTrue(any("mode" in line for line in cm.output))

    def test_dict_mode_never_raises(self):
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload({"mode": {"a": 1}}))

    def test_int_mode_is_malformed(self):
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload({"mode": 7}))

    def test_bool_mode_is_malformed(self):
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload({"mode": True}))


class TestF2NonFiniteFloats(_Base):
    def test_nan_hp_pct_invalid(self):
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            self.assertFalse(validate_coaching_payload(
                {"mode": "sr", "hp_pct": float("nan")}))
        self.assertTrue(any("hp_pct" in line for line in cm.output))

    def test_inf_game_time_invalid(self):
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload(
                {"mode": "aram", "game_time_s": float("inf")}))

    def test_negative_inf_tft_invalid(self):
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload(
                {"mode": "tft", "game_time_s": float("-inf")}))

    def test_nan_optional_win_pct_invalid(self):
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload(
                {"mode": "arena", "win_pct": float("nan")}))

    def test_nan_nested_team_context_invalid(self):
        payload = {"mode": "sr", "team_context": {
            "allies": [{"win_rate_recent": float("nan")}]}}
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload(payload))

    def test_finite_float_still_valid(self):
        with self.assertNoLogs(_LOGGER, level=logging.WARNING):
            self.assertTrue(validate_coaching_payload(
                {"mode": "sr", "hp_pct": 0.0, "game_time_s": 1e9}))


def _many_error_payload(n: int) -> dict:
    return {"mode": "sr",
            "team_context": {"allies": [{"team_id": "x"}] * n}}


class TestF3PerCallCap(_Base):
    def test_thirty_errors_logged_as_capped_lines_plus_summary(self):
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            self.assertFalse(validate_coaching_payload(_many_error_payload(30)))
        warns = _warnings(cm.records)
        self.assertEqual(len(warns), cp._MAX_FIELD_WARNINGS + 1)
        self.assertIn("22 more", warns[-1].getMessage())

    def test_at_cap_has_no_summary_line(self):
        n = cp._MAX_FIELD_WARNINGS
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            validate_coaching_payload(_many_error_payload(n))
        warns = _warnings(cm.records)
        self.assertEqual(len(warns), n)
        self.assertFalse(any("more" in w.getMessage() for w in warns))


class TestF4RepeatSuppression(_Base):
    def test_identical_bad_payload_warns_once(self):
        bad = {"mode": "sr", "gold": "lots"}
        with self.assertLogs(_LOGGER, level="WARNING"):
            self.assertFalse(validate_coaching_payload(bad))
        with self.assertNoLogs(_LOGGER, level=logging.WARNING):
            self.assertFalse(validate_coaching_payload(dict(bad)))
            self.assertFalse(validate_coaching_payload(dict(bad)))

    def test_repeat_still_logged_at_debug(self):
        bad = {"mode": "sr", "gold": "lots"}
        validate_coaching_payload(bad)
        with self.assertLogs(_LOGGER, level="DEBUG") as cm:
            validate_coaching_payload(bad)
        self.assertTrue(all(r.levelno == logging.DEBUG for r in cm.records))

    def test_changed_error_set_warns_again(self):
        validate_coaching_payload({"mode": "sr", "gold": "lots"})
        with self.assertLogs(_LOGGER, level="WARNING"):
            validate_coaching_payload({"mode": "sr", "level": "lots"})

    def test_same_fields_other_mode_warns_again(self):
        validate_coaching_payload({"mode": "sr", "gold": "lots"})
        with self.assertLogs(_LOGGER, level="WARNING"):
            validate_coaching_payload({"mode": "aram", "gold": "lots"})

    def test_valid_payload_resets_memo(self):
        bad = {"mode": "sr", "gold": "lots"}
        validate_coaching_payload(bad)
        self.assertTrue(validate_coaching_payload({"mode": "sr"}))
        with self.assertLogs(_LOGGER, level="WARNING"):
            validate_coaching_payload(bad)

    def test_idle_payload_between_games_resets_memo(self):
        # Verifier finding: an absent / None / unknown mode (idle, lobby)
        # returned True without clearing the memo, so a bug recurring game
        # after game warned once per process.
        bad = {"mode": "sr", "gold": "lots"}
        for idle in ({}, {"mode": None}, {"mode": "lobby"}):
            validate_coaching_payload(bad)
            self.assertTrue(validate_coaching_payload(idle))
            with self.assertLogs(_LOGGER, level="WARNING"):
                validate_coaching_payload(bad)

    def test_non_dict_repeat_warns_once(self):
        validate_coaching_payload([1])
        with self.assertNoLogs(_LOGGER, level=logging.WARNING):
            self.assertFalse(validate_coaching_payload([2]))

    def test_non_string_mode_repeat_warns_once(self):
        validate_coaching_payload({"mode": ["tft"]})
        with self.assertNoLogs(_LOGGER, level=logging.WARNING):
            self.assertFalse(validate_coaching_payload({"mode": ["tft"]}))

    def test_concurrent_calls_never_raise(self):
        # A raise anywhere ends that worker early, so its count stays short.
        done: list[int] = []

        def worker(i: int) -> None:
            for j in range(50):
                validate_coaching_payload(
                    {"mode": "sr", "gold": "x" if (i + j) % 2 else 1})
            done.append(i)

        threads = [threading.Thread(target=worker, args=(i,), name=f"cp-{i}")
                   for i in range(4)]
        logging.getLogger(_LOGGER).disabled = True
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        finally:
            logging.getLogger(_LOGGER).disabled = False
        self.assertEqual(sorted(done), [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
