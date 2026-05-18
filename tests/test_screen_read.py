"""s240 - on-demand VLM coach (AUTONOMOUS_AUDIT opportunity #3).

The "SCREEN READ" feature: operator clicks once -> RC reads the latest
relay frame it already holds -> ONE Sonnet pass -> a single tactical
coach one-liner surfaced on a dedicated pill (independent of the coach
loop's auto `immediate`, so it isn't clobbered on the next ~2s tick).

Backend under test: dashboard/_screen_read.py
  - run_screen_read()    : capture -> Sonnet -> normalized result dict
  - trigger_screen_read(): write a pending marker synchronously, spawn
                           the worker thread, in-flight dedupe
  - the /api/command "screen_read" case in routes_state
  - the state-builder stamping state["screen_read"]

Reader boundary (_build_reader) is mocked so no Anthropic / no relay /
no live game is needed - it reuses the audited GameVisionReader path.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashboard import _screen_read


class RunScreenReadTests(unittest.TestCase):
    """run_screen_read() normalizes every reader outcome into the
    {status,text,error,ts,requested_ts,model} contract."""

    def _reader(self, read_return=None, read_raises=None):
        r = mock.MagicMock()
        if read_raises is not None:
            r.read.side_effect = read_raises
        else:
            r.read.return_value = read_return
        return r

    def test_ok_path_strips_and_caps(self):
        with mock.patch.object(_screen_read, "_build_reader",
                               return_value=self._reader({"note": "  Back off - jungler bot-side  "})):
            out = _screen_read.run_screen_read()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["text"], "Back off - jungler bot-side")
        self.assertIsNone(out["error"])
        self.assertEqual(out["model"], _screen_read.SONNET_MODEL)
        self.assertIn("ts", out)

    def test_none_is_no_fresh_frame(self):
        with mock.patch.object(_screen_read, "_build_reader",
                               return_value=self._reader(None)):
            out = _screen_read.run_screen_read()
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "no_fresh_frame")
        self.assertEqual(out["text"], "")

    def test_missing_note_is_empty_note(self):
        with mock.patch.object(_screen_read, "_build_reader",
                               return_value=self._reader({})):
            out = _screen_read.run_screen_read()
        self.assertEqual(out["error"], "empty_note")

    def test_blank_note_is_empty_note(self):
        with mock.patch.object(_screen_read, "_build_reader",
                               return_value=self._reader({"note": "   "})):
            out = _screen_read.run_screen_read()
        self.assertEqual(out["error"], "empty_note")

    def test_reader_exception_is_vision_failed(self):
        with mock.patch.object(_screen_read, "_build_reader",
                               return_value=self._reader(read_raises=RuntimeError("boom"))):
            out = _screen_read.run_screen_read()
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "vision_failed")

    def test_build_reader_failure_is_no_api_key(self):
        with mock.patch.object(_screen_read, "_build_reader",
                               side_effect=FileNotFoundError("API-Key-Claude.txt")):
            out = _screen_read.run_screen_read()
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "no_api_key")

    def test_non_dict_reader_result_is_handled(self):
        with mock.patch.object(_screen_read, "_build_reader",
                               return_value=self._reader("a bare string")):
            out = _screen_read.run_screen_read()
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "empty_note")


class TriggerScreenReadTests(unittest.TestCase):
    """trigger_screen_read() writes a pending marker synchronously and
    dedupes concurrent triggers via the in-flight flag."""

    def setUp(self):
        _screen_read._reset_inflight_for_test()

    def tearDown(self):
        _screen_read._reset_inflight_for_test()

    def test_writes_pending_then_spawns(self):
        writes = []
        # Fake Thread: capture target, never auto-run, never clear flag -
        # simulates a still-running worker so the dedupe test is stable.
        fake_thread = mock.MagicMock()
        with mock.patch.object(_screen_read, "_write", side_effect=lambda d: writes.append(d)), \
             mock.patch.object(_screen_read.threading, "Thread", return_value=fake_thread) as T:
            ok = _screen_read.trigger_screen_read()
        self.assertTrue(ok)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["status"], "pending")
        self.assertIn("requested_ts", writes[0])
        T.assert_called_once()
        fake_thread.start.assert_called_once()

    def test_inflight_dedupes_second_trigger(self):
        writes = []
        fake_thread = mock.MagicMock()
        with mock.patch.object(_screen_read, "_write", side_effect=lambda d: writes.append(d)), \
             mock.patch.object(_screen_read.threading, "Thread", return_value=fake_thread):
            first = _screen_read.trigger_screen_read()
            second = _screen_read.trigger_screen_read()
        self.assertTrue(first)
        self.assertFalse(second)             # deduped while in-flight
        self.assertEqual(len(writes), 1)     # only the first pending write

    def test_worker_writes_result_and_clears_inflight(self):
        writes = []
        with mock.patch.object(_screen_read, "_write", side_effect=lambda d: writes.append(d)), \
             mock.patch.object(_screen_read, "run_screen_read",
                               return_value={"status": "ok", "text": "ward river",
                                             "error": None, "ts": 1.0,
                                             "requested_ts": 0.0,
                                             "model": _screen_read.SONNET_MODEL}):
            _screen_read._worker(requested_ts=42.0)
        self.assertEqual(writes[-1]["status"], "ok")
        self.assertEqual(writes[-1]["text"], "ward river")
        self.assertEqual(writes[-1]["requested_ts"], 42.0)
        # in-flight cleared so a subsequent trigger is accepted.
        fake_thread = mock.MagicMock()
        with mock.patch.object(_screen_read, "_write", side_effect=lambda d: writes.append(d)), \
             mock.patch.object(_screen_read.threading, "Thread", return_value=fake_thread):
            self.assertTrue(_screen_read.trigger_screen_read())


class PromptComplianceTests(unittest.TestCase):
    """ADR-006 / Riot 'no decision-simulation': the prompt must ask for
    strategic judgement + JSON output, never input automation."""

    def test_prompt_requests_json_note(self):
        self.assertIn('"note"', _screen_read.ScreenReadVision.PROMPT)

    def test_prompt_forbids_input_automation(self):
        p = _screen_read.ScreenReadVision.PROMPT.lower()
        self.assertTrue("do not" in p or "don't" in p)
        # mentions it's advisory judgement, not key/macro automation
        self.assertIn("key", p)


class CommandDispatchTests(unittest.TestCase):
    """POST /api/command {command:'screen_read'} routes to the trigger."""

    def test_screen_read_command_triggers(self):
        from dashboard import routes_state
        h = mock.MagicMock()
        with mock.patch("dashboard._screen_read.trigger_screen_read",
                        return_value=True) as trig:
            routes_state._serve_command_post(h, {"command": "screen_read"})
        trig.assert_called_once()
        code = h._send.call_args[0][0]
        self.assertEqual(code, 200)

    def test_unknown_command_still_400(self):
        from dashboard import routes_state
        h = mock.MagicMock()
        routes_state._serve_command_post(h, {"command": "definitely_not_a_cmd"})
        self.assertEqual(h._send.call_args[0][0], 400)


class StateBuilderStampTests(unittest.TestCase):
    """build_state() surfaces state['screen_read'] from data/screen_read.json,
    defaulting to {} and never breaking /api/state (mirrors the s184
    archetype_nudge stamping pattern)."""

    def _patches(self, screen_read_doc):
        from dashboard import _state_builder
        health = {"alive": True, "pid": 1, "mode": "client", "ui_pulse_age_s": 0}

        def _rj(p):
            if p == "ops/runtime/health.json":
                return health
            if p == "data/screen_read.json":
                return screen_read_doc
            return {}

        return _state_builder, [
            mock.patch.object(_state_builder, "read_json", side_effect=_rj),
            mock.patch.object(_state_builder, "lcu_summary", return_value={}),
            mock.patch.object(_state_builder, "liveclient_summary", return_value={}),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda *_a, **_k: None),
            mock.patch("core.archetype_mismatch.compute_nudge_payload",
                       return_value={}),
        ]

    def test_screen_read_surfaced(self):
        doc = {"status": "ok", "text": "contest dragon now", "ts": 1.0}
        sb, patches = self._patches(doc)
        for p in patches:
            p.start()
        try:
            st = sb.build_state()
        finally:
            for p in patches:
                p.stop()
        self.assertIn("screen_read", st)
        self.assertEqual(st["screen_read"]["text"], "contest dragon now")

    def test_screen_read_defaults_empty(self):
        sb, patches = self._patches({})
        for p in patches:
            p.start()
        try:
            st = sb.build_state()
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(st.get("screen_read"), {})


class EndToEndFileContractTests(unittest.TestCase):
    """The worker actually writes the JSON file via the dashboard atomic
    writer, in the {status,text,...} shape the frontend reads."""

    def test_worker_writes_valid_json_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "data" / "screen_read.json"
            with mock.patch("dashboard._writers.APP_DIR", Path(td)), \
                 mock.patch.object(_screen_read, "run_screen_read",
                                   return_value={"status": "ok",
                                                 "text": "recall - low HP",
                                                 "error": None, "ts": 2.0,
                                                 "requested_ts": 1.0,
                                                 "model": _screen_read.SONNET_MODEL}):
                _screen_read._reset_inflight_for_test()
                _screen_read._worker(requested_ts=1.0)
            doc = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(doc["status"], "ok")
            self.assertEqual(doc["text"], "recall - low HP")
            self.assertEqual(doc["requested_ts"], 1.0)


if __name__ == "__main__":
    unittest.main()
