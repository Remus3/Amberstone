"""Lane 8 cycle 19: field-level typing at the /api/input + /api/command boundary.

TWO defects, both measured against the real handlers on 2026-08-30.

1. A TRUTHY wrong-typed field killed the handler with NO HTTP RESPONSE AT ALL.
   `_serve_input_post` and `_serve_command_post` both call `.strip()` on a
   payload field OUTSIDE their try/except, so `{"text": 123}` or
   `{"command": {"a": 1}}` raised an uncaught `AttributeError`, the thread died
   and the connection closed empty. The browser sees a network error, not a 400.
   Only FALSY wrong types were safe (`[]`, `0`, `null`, `{}` all fall through
   `or ""`), which is why this survived.

   It survived LEDGER 1181 because that fix is a CONTAINER check
   (`_handler.py` `if not isinstance(payload, dict)`) and `{"text": 123}` IS a
   dict. Its test parametrizes only whole-body shapes (`[1,2,3]`, `"hello"`,
   `7`, `null`) and never a field type - the guard is named for the trust
   boundary but covers one axis of it.

   The schema DOES catch it and then throws the verdict away:
   `dashboard/api_schema.InputRequest` declares `text: str`, pydantic 2.13.2
   rejects `text=123`, and `_dispatch._validate_request_body` LOGS
   "Input should be a valid string" and dispatches the unchanged body anyway.
   Making that validator reject is the durable fix and is filed as RM-243,
   because it changes the contract of every POST route at once. This file pins
   the handler-local fix: a wrong type is a 400, never a dead thread.

2. ONE malformed line in `agents/state/task_queue.jsonl` flipped the dashboard
   health dot from yellow to GREEN while agent6 was failing. `json.loads` on a
   bare scalar line such as `123` succeeds, then `ev.get("task")` raises
   `AttributeError`, which aborted the WHOLE scan and discarded every outcome.
   The loop validated JSON syntax but never JSON SHAPE.

   The docstring claimed "Returns [] on any error"; the inline comment said the
   opposite ("yields a TRUNCATED list"). The comment was right. Both are now
   accurate because a malformed line is skipped like an unparseable one.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import routes_state  # noqa: E402


class _FakeHandler:
    def __init__(self):
        self.sent = None
        self.body = None

    def _send(self, code, body, ctype):
        self.sent = (code, ctype)
        self.body = body


# Every truthy non-string shape a client can put in a JSON field.
TRUTHY_WRONG = (123, 1.5, True, ["a"], {"a": 1})


class InputFieldTypingTests(unittest.TestCase):

    def test_truthy_wrong_typed_text_is_a_400_not_a_dead_thread(self):
        for bad in TRUTHY_WRONG:
            with self.subTest(text=bad):
                h = _FakeHandler()
                routes_state._serve_input_post(h, {"text": bad})
                self.assertIsNotNone(
                    h.sent, f"{bad!r} produced NO response at all")
                self.assertEqual(h.sent[0], 400)

    def test_truthy_wrong_typed_command_is_a_400_not_a_dead_thread(self):
        for bad in TRUTHY_WRONG:
            with self.subTest(command=bad):
                h = _FakeHandler()
                routes_state._serve_command_post(h, {"command": bad})
                self.assertIsNotNone(
                    h.sent, f"{bad!r} produced NO response at all")
                self.assertEqual(h.sent[0], 400)

    def test_falsy_wrong_types_still_400(self):
        """The pre-existing safe path must not regress."""
        for bad in ([], 0, None, {}):
            with self.subTest(text=bad):
                h = _FakeHandler()
                routes_state._serve_input_post(h, {"text": bad})
                self.assertEqual(h.sent[0], 400)

    def test_text_over_the_cap_is_rejected(self):
        """Nothing on the path bounded the length: `_writers.set_pregame` and
        `core.coaching_payload.pregame` are both uncapped, so one ~1 MiB POST
        (the only bound was `_handler._MAX_POST_BYTES`) inflated EVERY
        /api/state response and SSE frame at 2 Hz across up to 8 subscribers,
        and survived restart because it lands on disk.

        Lengths here are ABSOLUTE, not `_MAX_PREGAME_CHARS +/- 1`. A test
        written relative to the constant moves with it, so raising the cap to
        a billion would keep such a test green - it would assert only that the
        code agrees with itself. Mutation-testing caught exactly that.
        """
        h = _FakeHandler()
        with mock.patch.object(routes_state, "set_pregame") as sp:
            routes_state._serve_input_post(h, {"text": "x" * 50_000})
        self.assertEqual(h.sent[0], 400)
        sp.assert_not_called()

    def test_the_cap_is_a_sane_size(self):
        """Pin the magnitude, so the cap cannot be quietly raised to no cap."""
        self.assertLessEqual(routes_state._MAX_PREGAME_CHARS, 20_000)
        self.assertGreaterEqual(routes_state._MAX_PREGAME_CHARS, 500)

    def test_ordinary_length_text_is_accepted(self):
        """The cap must not reject legitimate operator input."""
        h = _FakeHandler()
        with mock.patch.object(routes_state, "set_pregame"):
            routes_state._serve_input_post(h, {"text": "x" * 400})
        self.assertEqual(h.sent[0], 200)

    def test_a_real_string_still_reaches_the_writer(self):
        """The fix must not break the happy path."""
        h = _FakeHandler()
        with mock.patch.object(routes_state, "set_pregame") as sp:
            routes_state._serve_input_post(h, {"text": "  hello  "})
        self.assertEqual(h.sent[0], 200)
        sp.assert_called_once_with("hello")

    def test_a_real_command_still_dispatches(self):
        h = _FakeHandler()
        with mock.patch.object(routes_state, "force_vision_scan") as fv:
            routes_state._serve_command_post(h, {"command": "FORCE_VISION"})
        self.assertEqual(h.sent[0], 200)
        fv.assert_called_once()


class ConsoleErrorLogInjectionTests(unittest.TestCase):
    """`/api/console-error` wrote six request-controlled strings into
    `logs/YYYY-MM-DD.log` with no control-character escaping.

    `dashboard/_handler.py:71` already defines `_scrub_log` for exactly this,
    and its own comment names the sink: "the sink is logs/YYYY-MM-DD.log, which
    the operator reads in a terminal." Cycle 13 fixed the `log_message`
    override; the fix was never swept to this handler.

    The payload below is the measured one: `\\x1b[2J\\x1b[1;1H` clears the
    operator's terminal and homes the cursor, so the forged line that follows
    reads as a genuine log record.
    """

    FORGED = ("benign\x1b[2J\x1b[1;1H2026-08-30 00:00:00 WARNING "
              "FORGED: supervisor healthy, no action needed")

    def _emit(self, payload):
        import logging as _logging
        records = []

        class _Cap(_logging.Handler):
            def emit(self, rec):
                records.append(rec.getMessage())

        h = _FakeHandler()
        h.headers = {"User-Agent": "probe"}
        logger = _logging.getLogger("rc.web_dashboard")
        cap = _Cap()
        logger.addHandler(cap)
        try:
            routes_state._CE_LAST_TS = 0.0
            routes_state._serve_console_error_post(h, payload)
        finally:
            logger.removeHandler(cap)
        return "\n".join(records)

    def test_escape_sequences_do_not_reach_the_log_record(self):
        blob = self._emit({"message": self.FORGED, "kind": "error"})
        self.assertNotIn("\x1b", blob, "raw ESC reached the log record")
        self.assertNotIn("\x1b[2J", blob)

    def test_other_control_characters_are_escaped_too(self):
        blob = self._emit({
            "message": "a\x07b",          # BEL
            "stack":   "at x\x08\x08",    # backspace
            "source":  "s\rc",            # CR
            "url":     "u\nv",            # LF - a forged newline is a forged line
        })
        self.assertNotIn("\x07", blob)
        self.assertNotIn("\x08", blob)
        self.assertNotIn("\r", blob)

    def test_ordinary_text_is_still_readable(self):
        """The scrub must not mangle a normal error into unreadability."""
        blob = self._emit({"message": "TypeError: x is not a function",
                           "source": "https://legion-rc:8888/js/main.js"})
        self.assertIn("TypeError: x is not a function", blob)
        self.assertIn("https://legion-rc:8888/js/main.js", blob)


class Agent6MalformedLineTests(unittest.TestCase):
    """A bad line must be skipped, never abort the scan."""

    def _queue(self, tmp: Path, lines: list[str]) -> Path:
        q = tmp / "agents" / "state"
        q.mkdir(parents=True, exist_ok=True)
        f = q / "task_queue.jsonl"
        f.write_text("\n".join(lines), encoding="utf-8")
        return f

    def _event(self, tid: str, event: str) -> str:
        return json.dumps({
            "task": {"id": tid, "op": "agent6-full-audit-pass",
                     "status": event, "last_error": None},
            "event": event,
            "ts": "2026-08-30T00:00:00+00:00",
        })

    def test_a_bare_scalar_line_does_not_discard_the_real_outcomes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # A valid-JSON but wrong-SHAPE line, first, exactly as measured.
            self._queue(tmp, ["123",
                              self._event("t1", "completed"),
                              self._event("t2", "failed"),
                              self._event("t3", "failed")])
            routes_state._A6_MEMO = None
            with mock.patch.object(routes_state, "APP_DIR", tmp):
                out = routes_state._agent6_audit_outcomes(max_count=3)
            routes_state._A6_MEMO = None
        self.assertEqual([o["task_id"] for o in out], ["t1", "t2", "t3"],
                         "one malformed line discarded the real outcomes")

    def test_the_health_dot_still_reads_yellow_behind_a_malformed_line(self):
        """The consequence that made this HIGH: green while agent6 is failing."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._queue(tmp, ["123",
                              self._event("t1", "completed"),
                              self._event("t2", "failed"),
                              self._event("t3", "failed")])
            routes_state._A6_MEMO = None
            with mock.patch.object(routes_state, "APP_DIR", tmp):
                out = routes_state._agent6_audit_outcomes(max_count=3)
            routes_state._A6_MEMO = None
        last_two = out[-2:]
        consecutive_fails = (len(last_two) >= 2
                             and all(o.get("event") == "failed" for o in last_two))
        self.assertTrue(consecutive_fails,
                        "two consecutive failures must still be visible")

    def test_other_malformed_shapes_are_skipped_too(self):
        import tempfile
        for bad in ('"a string"', "123", "null", "[1,2,3]", "true"):
            with self.subTest(line=bad), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                self._queue(tmp, [bad, self._event("t9", "completed")])
                routes_state._A6_MEMO = None
                with mock.patch.object(routes_state, "APP_DIR", tmp):
                    out = routes_state._agent6_audit_outcomes(max_count=3)
                routes_state._A6_MEMO = None
                self.assertEqual([o["task_id"] for o in out], ["t9"])


if __name__ == "__main__":
    unittest.main()
