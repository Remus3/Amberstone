"""S136 T11: an UNKNOWN TFT HP / gold / level is null in the coach payload,
never a placeholder the overlay paints as fact.

Defect (pre-existing, measured by the s136 verifier): with the TFT OCR silent
and no per-round file that is positively this game's, the coach payload
data/tft_coaching_data.json still carried numbers, and /api/state served them:

  tft/tft_coach_engine.py ``_write_fields``: ``"health": _out_hp`` where
      ``_resolve_hp(state)`` falls back to ``default=100``; ``"level":
      state.get("level", 1)``; ``"gold": state.get("gold", 0)``. The reader's
      level 1 / gold 0 are its own defaults until the Live Client or OCR reads
      one (tft/tft_state_reader.py ``_parse``: ``level_known`` / ``gold_known``
      False, s136 T9).
  tft/tft_coach_engine.py ``reset_state`` writes ``tft_blank_payload()``,
      core/coaching_payload.py ``TftPayload`` defaults ``health: int = 100``,
      ``gold: int = 0`` (the same placeholders at game start).
  web/js/lib/overlay_tft.js ``tftOverlayModel``: ``firstIn([lc.hp, c.hp,
      c.health], 1, 100)``, ``firstIn([c.level, lc.level], 1, 10)``,
      ``firstIn([c.gold, lc.gold], 0, 999)`` - a placeholder number is a valid
      value there, so the vitals read "HP 100 / LEVEL 1 / GOLD 0" and the board
      count "7/1". null already renders the "-" sentinel.

The coach PROMPT already says "unknown" for these (s136 T9,
tests/test_tft_coach_prompt_sources_s136.py); the payload now uses the same
signals: null = unknown, a known 0 gold stays 0.

Consumer that misbehaved on null (performance_tracker.py
``_legacy_tft_placement``): a null ``health`` with others alive fell through
to a placement from ``alive_others`` - a fabricated result where the old 100
placeholder had (by accident) read as "still alive".

UI audit MUST-FIX (same slice): with no per-round file the reader's no-read
``board_str`` "unavailable" reached the overlay's board_str fallback as a unit
chip; the payload now carries "" for it.
"""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import performance_tracker as pt
from core.coaching_payload import validate_coaching_payload
from tft import tft_coach_engine as tce
from tft.tft_coach_engine import TftCoachEngine

_ADVICE = "Action: ROLL\nBoard: Jinx D7\nEcon: hold 50\n"

# tft/tft_state_reader.py _parse output for a standalone-client match with the
# OCR silent and no per-round file that is positively this game's: level 1 /
# gold 0 are the reader's defaults (level_known / gold_known False), health
# its OCR fallback (None).
_UNKNOWN = {
    "game_mode": "TFT", "game_time_s": 205.0, "level": 1, "gold": 0,
    "gold_known": False, "level_known": False, "health": None,
    "is_dead": False, "kills": 0, "deaths": 0, "stage": 2, "round": 1,
    "stage_round": "2-1", "alive_others": 7, "dead_others": 0,
    "items_str": "none", "board_str": "unavailable", "variant": "standard",
    "data_source": "tft_standalone", "eog_match": False,
}

# The same reader with every value read (Live Client level, OCR gold, health).
_KNOWN = dict(_UNKNOWN, level=6, gold=34, gold_known=True, level_known=True,
              health=61, data_source="live_client", eog_match=None)


def _engine(tmp: Path) -> TftCoachEngine:
    """An engine with no key and no vision HP (the vision file is live state)."""
    with patch("core.anthropic_key.read_anthropic_key", return_value=""):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            eng = TftCoachEngine(tmp / "tft_coaching_data.json")
    eng._vision_hp = lambda loader=None: None
    return eng


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td_obj = tempfile.TemporaryDirectory()
        self.td = Path(self._td_obj.name)
        for p in (patch("core.coaching_timestamps.write_coaching_ts"),
                  patch.object(tce, "_live_data", return_value={})):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._td_obj.cleanup)

    def write(self, state: dict) -> dict:
        eng = _engine(self.td)
        eng._write_fields(_ADVICE, dict(state))
        return _read(eng._data_file)


class TestPayloadVitals(_Tmp):
    def test_unknown_hp_level_gold_are_null(self):
        out = self.write(_UNKNOWN)
        self.assertEqual(out["action"], "ROLL", "precondition: the advice landed")
        for k in ("health", "level", "gold"):
            self.assertIn(k, out, k)
            self.assertIsNone(out[k], f"{k}={out[k]!r} is a placeholder, not a read")

    def test_known_values_are_carried(self):
        out = self.write(_KNOWN)
        self.assertEqual((out["health"], out["level"], out["gold"]), (61, 6, 34))

    def test_known_zero_gold_stays_zero(self):
        """gold_known True: the 0 is a READ (spent out), not the default."""
        out = self.write(dict(_KNOWN, gold=0))
        self.assertEqual(out["gold"], 0)
        self.assertIsNotNone(out["gold"])

    def test_unread_gold_with_a_known_level_is_null_alone(self):
        out = self.write(dict(_KNOWN, gold=0, gold_known=False))
        self.assertIsNone(out["gold"])
        self.assertEqual((out["health"], out["level"]), (61, 6))

    def test_stale_per_round_hp_is_null_not_100(self):
        """A per-round file that is not positively this game's (s136 T9
        ``_stale_standalone``): its HP is withheld, and withheld is null."""
        out = self.write(dict(_UNKNOWN, health=37))
        self.assertIsNone(out["health"])

    def test_unread_board_str_is_empty_not_a_unit(self):
        """UI audit MUST-FIX: the reader's no-read "unavailable" board_str
        reached the overlay's board_str fallback (overlay_tft.js
        parseBoardStr) as a unit chip named "unavailable", board count 1."""
        self.assertEqual(self.write(_UNKNOWN)["board_str"], "")
        out = self.write(dict(_KNOWN, board_str="Yorick*1, Xayah*2"))
        self.assertEqual(out["board_str"], "Yorick*1, Xayah*2")

    def test_unknown_payload_validates_silently(self):
        out = self.write(_UNKNOWN)
        with self.assertNoLogs("rc.coaching_payload", level=logging.WARNING):
            self.assertTrue(validate_coaching_payload(out))

    def test_reset_blank_carries_no_vitals_placeholder(self):
        eng = _engine(self.td)
        eng.reset_state()
        out = _read(eng._data_file)
        for k in ("health", "level", "gold"):
            self.assertIsNone(out.get(k), f"reset {k}={out.get(k)!r}")
        with self.assertNoLogs("rc.coaching_payload", level=logging.WARNING):
            self.assertTrue(validate_coaching_payload(out))

    def test_urgency_gate_keeps_unknown_hp_non_urgent(self):
        """submit()'s HP-critical gate still reads an unknown HP as not
        critical (the payload default changed, not the gate's)."""
        eng = _engine(self.td)
        self.assertEqual(eng._resolve_hp(dict(_UNKNOWN)), 100)
        self.assertIsNone(eng._resolve_hp(dict(_UNKNOWN), default=None))


class TestStateBuilderServesNull(_Tmp):
    def test_api_state_coach_carries_null_vitals(self):
        """End to end through dashboard/_state_builder.py build_state: the
        engine's unknown write reaches /api/state.coach as null."""
        from dashboard import _state_builder as sb
        coach = self.write(_UNKNOWN)
        health = {"alive": True, "pid": 1, "mode": "tft", "has_game": True,
                  "tft_mode": True, "ui_pulse_age_s": 0.1,
                  "game_poll_worker_age_s": 0.1}

        def _read_json(path: str) -> dict:
            if path.endswith("health.json"):
                return dict(health)
            if path.endswith("tft_coaching_data.json"):
                return dict(coach)
            return {}

        with patch.object(sb, "liveclient_summary", return_value={}), \
             patch.object(sb, "get_team_context", return_value=None), \
             patch.object(sb, "lcu_summary", return_value={}), \
             patch.object(sb, "read_json", side_effect=_read_json):
            state = sb.build_state()
        self.assertEqual(state["mode_key"], "tft")
        for k in ("health", "level", "gold"):
            self.assertIsNone(state["coach"].get(k), k)


class TestRatingOnUnknownHp(unittest.TestCase):
    """performance_tracker.py ``_legacy_tft_placement``: a null HP is unknown,
    not "out", so others alive is a mid-game snapshot, never a placement."""

    def test_null_hp_with_others_alive_is_no_placement(self):
        tc = {"mode": "tft", "health": None, "alive_others": 5}
        self.assertEqual(pt._legacy_tft_placement({}, tc, False), (0, ""))

    def test_measured_elimination_still_places(self):
        tc = {"mode": "tft", "health": 0, "alive_others": 4}
        self.assertEqual(pt._legacy_tft_placement({}, tc, False)[0], 5)

    def test_is_dead_with_null_hp_still_places(self):
        tc = {"mode": "tft", "health": None, "is_dead": True, "alive_others": 2}
        self.assertEqual(pt._legacy_tft_placement({}, tc, False)[0], 3)

    def test_nobody_else_alive_is_first_with_null_hp(self):
        tc = {"mode": "tft", "health": None, "alive_others": 0}
        self.assertEqual(pt._legacy_tft_placement({}, tc, False)[0], 1)


if __name__ == "__main__":
    unittest.main()
