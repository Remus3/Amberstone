"""RM-292 (d): the TFT coaching artifact's declared shape agrees with its
live writer, and the in-tree default sites seed from that one declaration.

Ground truth this module is built on (cited file:line, measured at
4023fa2a3 before the fix):

  core/coaching_payload.py:163 ``TftPayload`` declared ``stage: str`` and
      ``round: str`` (:173-174); ``validate_coaching_payload`` (:191)
      dispatches on ``mode`` and logs one WARNING per field error.
  tft/tft_state_reader.py:213 the producer emits ``stage`` / ``round`` as
      INTS (``_estimate_round`` or the OCR ``int()`` at :170).
  tft/tft_coach_engine.py:791 ``_write_fields`` copies them through as ints
      (:819-820) beside 11 keys TftPayload never declared; ``reset_state``
      (:712) writes int ``stage`` / ``round`` too; ``_write_status`` (:859)
      wrote only the advice strings although its docstring said its keys
      "mirror the reset payload".
  dashboard/_state_builder.py:548 validates the coach file on EVERY
      /api/state build, so each poll after an engine write logged two
      WARNINGs ("stage: Input should be a valid string", "round: ...").
  dashboard/_state_builder.py:570-573 fills a coach key from the Live
      Client summary only while the coach value is in (None, "", 0);
      web/js/main.js:1107 renders the top-bar level from ``p.level``. So a
      blank seed carrying ``level: 1`` would shadow the live level.
  core/feature_policy.py:435 ``write_disabled_placeholder(mode, feature,
      artifact_root)`` writes the disabled TFT artifact.
  performance_tracker.py:333 / :339 / :357 read ``variant``,
      ``alive_others`` and the ``stage`` fallback off the coaching file.
"""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.coaching_payload import validate_coaching_payload
from tft.tft_coach_engine import TftCoachEngine

# A state dict shaped like tft/tft_state_reader.py:204-221 `_parse` output.
_LIVE_STATE = {
    "game_mode": "TFT", "game_time_s": 912.4, "level": 6, "gold": 34,
    "health": 61, "is_dead": False, "interest": 0, "streak": -1,
    "kills": 2, "deaths": 3, "stage": 3, "round": 2, "stage_round": "3-2",
    "round_event": "pvp", "is_pve": False, "is_carousel": False,
    "items": ["B.F. Sword"], "items_str": "B.F. Sword",
    "alive_others": 5, "dead_others": 2, "total_players": 8,
    "board_str": "unavailable", "bench_str": "unavailable",
    "shop_str": "unavailable", "traits_str": "unavailable",
    "variant": "standard",
}

_ADVICE = "Action: ROLL\nBoard: Jinx D7\nEcon: hold 50\n"

# The overlay-fill rule at dashboard/_state_builder.py:572.
_OVERLAY_BLANK = (None, "", 0)
# Live Client summary keys a TFT coach file could shadow
# (dashboard/_liveclient.py:211-230).
_LIVE_OVERLAY_KEYS = ("game_time_s", "level", "gold", "hp", "mana")


def _engine(tmp: Path) -> TftCoachEngine:
    """An engine with no key, no vision HP and no coaching-ts side write."""
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
        p = patch("core.coaching_timestamps.write_coaching_ts")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._td_obj.cleanup)

    def assertValidSilently(self, payload: dict):
        """validate_coaching_payload returns True AND logs nothing."""
        with self.assertNoLogs("rc.coaching_payload", level=logging.WARNING):
            ok = validate_coaching_payload(payload)
        self.assertTrue(ok, payload)


class TestEngineArtifactsValidate(_Tmp):
    """Every artifact the live engine writes passes its own schema."""

    def test_written_payload_validates_clean(self):
        eng = _engine(self.td)
        eng._write_fields(_ADVICE, dict(_LIVE_STATE))
        out = _read(eng._data_file)
        self.assertEqual((out["stage"], out["round"]), (3, 2))
        self.assertValidSilently(out)

    def test_written_payload_with_no_live_source_validates_clean(self):
        """No :2999 / OCR source at all (standalone TFT client, s134): the
        writer falls back to its own defaults and must still validate."""
        eng = _engine(self.td)
        eng._write_fields(_ADVICE, {})
        self.assertValidSilently(_read(eng._data_file))

    def test_reset_payload_validates_clean(self):
        eng = _engine(self.td)
        eng.reset_state()
        self.assertValidSilently(_read(eng._data_file))

    def test_status_payload_validates_clean(self):
        eng = _engine(self.td)
        eng._write_status("Coaching paused - retrying")
        out = _read(eng._data_file)
        self.assertEqual(out["risk"], "Coaching paused - retrying")
        self.assertValidSilently(out)

    def test_disabled_payload_validates_clean(self):
        from core.feature_policy import write_disabled_placeholder
        write_disabled_placeholder("tft", "live_coaching", artifact_root=self.td)
        out = _read(self.td / "data" / "tft_coaching_data.json")
        self.assertEqual(out["action"], "COACHING DISABLED")
        self.assertValidSilently(out)


class TestBlankSeedsDoNotShadowLiveFields(_Tmp):
    """A degraded or disabled write mid-game must not pin a live overlay key
    (dashboard/_state_builder.py:572) to a seed value."""

    def _assert_no_shadow(self, out: dict):
        for k in _LIVE_OVERLAY_KEYS:
            self.assertIn(out.get(k), _OVERLAY_BLANK,
                          f"{k}={out.get(k)!r} would shadow the live value")

    def test_status_payload(self):
        eng = _engine(self.td)
        eng._write_status("Coaching paused - retrying")
        self._assert_no_shadow(_read(eng._data_file))

    def test_disabled_payload(self):
        from core.feature_policy import write_disabled_placeholder
        write_disabled_placeholder("tft", "live_coaching", artifact_root=self.td)
        self._assert_no_shadow(_read(self.td / "data" / "tft_coaching_data.json"))

    def test_reset_payload(self):
        eng = _engine(self.td)
        eng.reset_state()
        out = _read(eng._data_file)
        self._assert_no_shadow(out)
        for k in ("stage", "round"):
            self.assertIn(out.get(k), _OVERLAY_BLANK, k)

    def test_reset_payload_lets_the_live_level_through_the_state_builder(self):
        """End to end through dashboard/_state_builder.py build_state: the
        reset artifact under a live level 6 renders level 6, not the seed."""
        from dashboard import _state_builder as sb
        eng = _engine(self.td)
        eng.reset_state()
        coach = _read(eng._data_file)
        health = {"alive": True, "pid": 1, "mode": "tft", "has_game": True,
                  "tft_mode": True, "ui_pulse_age_s": 0.1,
                  "game_poll_worker_age_s": 0.1}

        def _read_json(path: str) -> dict:
            if path.endswith("health.json"):
                return dict(health)
            if path.endswith("tft_coaching_data.json"):
                return dict(coach)
            return {}

        live = {"level": 6, "gold": 31, "game_time_s": 905.0}
        with patch.object(sb, "liveclient_summary", return_value=dict(live)), \
             patch.object(sb, "get_team_context", return_value=None), \
             patch.object(sb, "lcu_summary", return_value={}), \
             patch.object(sb, "read_json", side_effect=_read_json):
            state = sb.build_state()
        self.assertEqual(state["mode_key"], "tft")
        for k, v in live.items():
            self.assertEqual(state["coach"].get(k), v, k)


# The advice shape: mode, action and core.coaching_payload.TFT_ADVICE_FIELDS.
_ADVICE_KEYS = {"mode", "action", "board", "econ", "rolldown", "items",
                "god_pick", "placement", "upgrade", "risk"}


class TestOneShapeAuthority(_Tmp):
    """The in-tree default sites seed from core/coaching_payload.py."""

    def test_status_and_disabled_carry_the_advice_shape_only(self):
        from core.feature_policy import write_disabled_placeholder
        eng = _engine(self.td)
        eng._write_status("Coaching paused - retrying")
        status = _read(eng._data_file)
        write_disabled_placeholder("tft", "live_coaching", artifact_root=self.td)
        disabled = _read(self.td / "data" / "tft_coaching_data.json")
        for name, out in (("status", status), ("disabled", disabled)):
            self.assertEqual(set(out), _ADVICE_KEYS, name)
            self.assertEqual(out["mode"], "tft", name)
            numeric = [k for k, v in out.items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)]
            self.assertEqual(numeric, [], name)
        self.assertEqual(status["action"], "ERROR")
        self.assertEqual(disabled["risk"], "")

    def test_reset_is_the_declared_shape_without_sr_family_keys(self):
        from core.coaching_payload import TftPayload
        eng = _engine(self.td)
        eng.reset_state()
        out = _read(eng._data_file)
        declared = set(TftPayload.model_fields) - {"combat_stats", "stat_shards"}
        self.assertEqual(set(out), declared)
        self.assertEqual(out["mode"], "tft")
        # S136 T11: unknown HP is null, not a placeholder 100 the overlay paints
        self.assertIsNone(out["health"])

    def test_helpers_return_a_new_dict_every_call(self):
        from core.coaching_payload import tft_advice_payload, tft_blank_payload
        for fn in (tft_advice_payload, tft_blank_payload):
            a = fn()
            a["risk"] = "mutated"
            self.assertEqual(fn()["risk"], "", fn.__name__)
            self.assertIsNot(fn(), fn(), fn.__name__)

    def test_facade_seed_equals_the_advice_payload(self):
        """coaches/tft_coach.py:249 `_default_payloads` (the fourth site, not
        edited by RM-292 d) must stay identical to the advice shape."""
        from types import SimpleNamespace

        from coaches.tft_coach import Coach
        from core.coaching_payload import tft_advice_payload
        fake = SimpleNamespace(_tft_data_file=self.td / "c.json",
                               _live_data_file=self.td / "l.json")
        seeds = dict(Coach._default_payloads(fake))
        self.assertEqual(seeds[fake._tft_data_file], tft_advice_payload())

    def test_generated_js_schema_is_in_sync(self):
        """web/js/lib/state_schema.js is generated from TftPayload."""
        import tools.gen_state_schema as gss
        js = gss.OUTPUT.read_text(encoding="utf-8")
        self.assertEqual(js, gss._generate())
        block = js[js.index("@typedef {Object} TftPayload"):]
        block = block[:block.index("*/")]
        self.assertIn("@property {number} stage", block)
        self.assertIn("@property {number} round", block)


# The literals the three sites carried at 4023fa2a3 (before RM-292 d).
_PRE_RESET = {
    "mode": "tft", "action": "", "board": "", "econ": "", "rolldown": "",
    "items": "", "god_pick": "", "placement": "", "upgrade": "", "risk": "",
    "stage": 1, "round": 1, "level": 1, "gold": 0, "health": 100,
    "alive_others": 7,
}
_PRE_STATUS = {
    "mode": "tft", "action": "ERROR", "board": "", "econ": "", "rolldown": "",
    "items": "", "god_pick": "", "placement": "", "upgrade": "",
    "risk": "Coaching paused - retrying",
}
_PRE_DISABLED = dict(_PRE_STATUS, action="COACHING DISABLED", risk="")


class TestPerformanceTrackerReadsAreUnchanged(_Tmp):
    """performance_tracker.save_tft_rating reads variant / alive_others /
    stage / level / game_time_s off the coaching file (:333-:360)."""

    def setUp(self):
        super().setUp()
        import performance_tracker as pt
        self.pt = pt
        # No match_history.db and no repo-tree heatmap write: only the
        # returned (grade, notes) is under test.
        for target in (patch.object(pt, "_get_db", return_value=None),
                       patch("tft.placement_aggregator.update_heatmap")):
            target.start()
            self.addCleanup(target.stop)

    def _rate(self, live: dict, coach: dict):
        out = self.td / f"r{len(list(self.td.iterdir()))}"
        out.mkdir()
        return self.pt.save_tft_rating(out, dict(live), dict(coach))

    # s134 N8: the placement now has to come from a real source. These tests
    # used the coaching file's alive_others DEFAULT of 7 (an 8th nobody
    # measured - exactly the N8 defect); a vision last-round placement keeps
    # them on the stage / grade reads they are about.
    _LIVE = {"last_round_result": "6th", "stage_round": "4-2", "level": 8,
             "traits_active": [], "board_units": [], "augments": []}

    def _new_files(self):
        from core.feature_policy import write_disabled_placeholder
        eng = _engine(self.td)
        eng.reset_state()
        reset = _read(eng._data_file)
        eng._write_status("Coaching paused - retrying")
        status = _read(eng._data_file)
        write_disabled_placeholder("tft", "live_coaching", artifact_root=self.td)
        disabled = _read(self.td / "data" / "tft_coaching_data.json")
        return reset, status, disabled

    def test_same_grade_and_notes_as_the_old_literals(self):
        reset, status, disabled = self._new_files()
        for name, old, new in (("reset", _PRE_RESET, reset),
                               ("status", _PRE_STATUS, status),
                               ("disabled", _PRE_DISABLED, disabled)):
            self.assertEqual(self._rate(self._LIVE, new),
                             self._rate(self._LIVE, old), name)

    def test_reset_no_longer_fabricates_a_stage_one_elimination(self):
        """On the stage fallback path (no parseable stage_round) the old
        reset literal's stage 1 produced "Eliminated Stage 1"; the declared
        blank's stage 0 means unknown, so no stage note is invented."""
        reset, _status, _disabled = self._new_files()
        live = dict(self._LIVE, stage_round="")
        _g_old, old_notes = self._rate(live, _PRE_RESET)
        self.assertIn("Eliminated Stage 1 - stabilize earlier", old_notes)
        _g_new, new_notes = self._rate(live, reset)
        self.assertFalse([n for n in new_notes if "Eliminated Stage" in n])

    def test_int_stage_from_the_writer_reads_back_as_an_int(self):
        eng = _engine(self.td)
        eng._write_fields(_ADVICE, dict(_LIVE_STATE, stage=3, round=4))
        written = _read(eng._data_file)
        _g, notes = self._rate(dict(self._LIVE, stage_round=""), written)
        self.assertIn("Eliminated Stage 3 - stabilize earlier", notes)


if __name__ == "__main__":
    unittest.main()
