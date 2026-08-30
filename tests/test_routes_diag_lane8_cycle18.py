"""Lane 8 cycle 18: dashboard/routes_diag.py must not put raw exception text on the wire.

CLAUDE.md "Error Handling" is absolute: never surface a raw API/exception string
in any user-facing dashboard panel - catch it, render a friendly degraded-mode
message, log the raw error to `logs/`.

`dashboard/_errors.send_error` is the helper that implements exactly that, and
`routes_diag.py` IMPORTS it on line 20 and CALLS it correctly in two handlers
(`_serve_decisions_heartbeat`, `_serve_decisions_respond_active_post`). Three
other handlers in the same module hand-rolled `json.dumps({"error": str(exc)})`
instead, so the module was internally inconsistent and the leaking half won on
the most-reached endpoint of the three.

WHY THE EXISTING GUARD DID NOT CATCH IT. `tests/test_dashboard_error_scrub_rm134.py`
has `DashboardSurfaceScrubTests.test_every_dashboard_importer_gets_the_scrubbed_helper`,
which names `dashboard.routes_diag` explicitly - but its only assertion is
`self.assertIs(mod.send_error, send_error)`. That asserts the module IMPORTS the
scrubbed helper. It stays green while the module never CALLS it. The guard's
domain was narrower than its name. These tests assert BEHAVIOUR at each handler
instead, which is what the contract actually is.

REACH, measured this run rather than assumed: `dashboard/server.py:35` binds
`HOST = "::"`, and `Get-NetTCPConnection -LocalPort 8888 -State Listen` reports
`::` on live pid 23644 - so `/api/diagnostics` is reachable from the LAN and the
tailnet, not loopback only.
"""
from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import _errors  # noqa: E402
import dashboard.routes_diag as rd  # noqa: E402

# One raw exception string carrying every shape the envelope must not leak: an
# absolute Windows path, a filename, and a distinctive secret-shaped token.
LEAKY = r"unable to open database file at C:\Riot Commander\data\rewind_history.db (ZORBLEAK)"
FORBIDDEN = ("ZORBLEAK", "rewind_history.db", "C:\\", "Riot Commander")



def guard_offenders(source: str) -> list[int]:
    """Line numbers of `except` blocks that answer 5xx without `send_error`.

    Shared by the module-wide guard and by GuardDomainTests, so the rule the
    real module is held to is EXACTLY the rule the domain tests exercise. When
    those were two separate implementations, the module guard silently had a
    narrower domain than the docstring describing it.
    """
    import ast
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
        uses_send_error = any(
            isinstance(c.func, ast.Name) and c.func.id == "send_error"
            for c in calls)
        hand_rolled_5xx = [
            c.lineno for c in calls
            if isinstance(c.func, ast.Attribute) and c.func.attr == "_send"
            and c.args and isinstance(c.args[0], ast.Constant)
            and isinstance(c.args[0].value, int) and c.args[0].value >= 500]
        if hand_rolled_5xx and not uses_send_error:
            offenders.extend(hand_rolled_5xx)
    return sorted(offenders)


class _FakeHandler:
    """Stand-in for the BaseHTTPRequestHandler subclass the routes are handed."""

    def __init__(self, path: str = "/"):
        self.sent = None
        self.path = path

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)

    @property
    def status(self) -> int:
        assert self.sent is not None, "_send was never called"
        return self.sent[0]

    @property
    def body(self) -> dict:
        assert self.sent is not None, "_send was never called"
        return json.loads(self.sent[1].decode("utf-8"))


def _assert_scrubbed(case: unittest.TestCase, err) -> None:
    case.assertIsInstance(err, str)
    for needle in FORBIDDEN:
        case.assertNotIn(
            needle, err,
            f"raw exception text leaked onto the wire: {err!r}")
    # Not merely "the needle is absent" - pin the positive content too, so a
    # handler that degenerates to an empty string cannot pass this check
    # (feedback_negative_assertion_rules_out_without_pinning_down).
    case.assertEqual(err, _errors.GENERIC_ERROR)


class DiagnosticsLeakTests(unittest.TestCase):
    """The endpoint with the widest reach of the three."""

    def test_diagnostics_500_is_scrubbed(self):
        h = _FakeHandler("/api/diagnostics")
        with mock.patch.object(rd, "diagnostics_cached",
                               side_effect=OSError(LEAKY)):
            rd._serve_diagnostics(h)
        self.assertEqual(h.status, 500)
        _assert_scrubbed(self, h.body["error"])

    def test_diagnostics_raw_cause_reaches_the_log(self):
        h = _FakeHandler("/api/diagnostics")
        with self.assertLogs(rd.log, level=logging.WARNING) as cap:
            with mock.patch.object(rd, "diagnostics_cached",
                                   side_effect=OSError(LEAKY)):
                rd._serve_diagnostics(h)
        self.assertTrue(any("ZORBLEAK" in line for line in cap.output),
                        f"raw cause was dropped instead of logged: {cap.output}")


class OcrLeakTests(unittest.TestCase):

    def test_ocr_500_is_scrubbed(self):
        h = _FakeHandler("/api/ocr")
        with mock.patch("urllib.request.urlopen", side_effect=OSError(LEAKY)):
            rd._serve_ocr(h)
        self.assertEqual(h.status, 500)
        _assert_scrubbed(self, h.body["error"])

    def test_ocr_relay_probe_failure_is_logged_not_silently_swallowed(self):
        """The relay-freshness probe sat behind a bare `except Exception: pass`.

        A silent catch is the other half of the CLAUDE.md error rule and the
        more common failure: when the relay is down, every OCR call silently
        stops dropping the fields the Live Client authoritatively provides, and
        nothing anywhere records why.
        """
        h = _FakeHandler("/api/ocr")
        with self.assertLogs(rd.log, level=logging.DEBUG) as cap:
            with mock.patch("urllib.request.urlopen", side_effect=OSError(LEAKY)):
                rd._serve_ocr(h)
        self.assertTrue(
            any("relay" in line.lower() for line in cap.output),
            f"the relay-freshness probe failed silently: {cap.output}")


class DecisionChoicePostTests(unittest.TestCase):

    def test_choice_post_500_is_scrubbed(self):
        h = _FakeHandler("/api/decisions/abc123")
        with mock.patch("core.decision_detector.DecisionStore",
                        side_effect=OSError(LEAKY)):
            rd._serve_decision_choice_post(h, {"choice": "safe"})
        self.assertEqual(h.status, 500)
        _assert_scrubbed(self, h.body["error"])

    def test_non_string_choice_is_a_400_not_a_leaking_500(self):
        """Merely WRONG input, distinct from abuse (audit dimension 4f).

        `(payload.get("choice") or "").strip()` assumes a string. A JSON number
        reached `.strip()` and raised, so a wrong-typed field produced a 500
        carrying the internal type name instead of the 400 the handler already
        knows how to send for a bad choice.
        """
        h = _FakeHandler("/api/decisions/abc123")
        rd._serve_decision_choice_post(h, {"choice": 123})
        self.assertEqual(h.status, 400,
                         f"wrong-typed choice should be rejected, got {h.sent}")
        self.assertNotIn("strip", json.dumps(h.body),
                         f"internal type/attribute detail leaked: {h.body}")

    def test_non_string_note_does_not_raise(self):
        """`note` is already coerced with str(); pin it so the coercion stays."""
        h = _FakeHandler("/api/decisions/abc123")
        with mock.patch("core.decision_detector.DecisionStore") as store_cls:
            store_cls.return_value.list_pending.return_value = [
                {"id": "abc123", "options": ["safe", "punish"]}]
            store_cls.return_value.record_choice.return_value = {
                "id": "abc123", "choice": "safe"}
            rd._serve_decision_choice_post(
                h, {"choice": "safe", "note": {"not": "a string"}})
        self.assertEqual(h.status, 200, f"unexpected: {h.sent}")


class AlreadyCorrectHandlersAreControls(unittest.TestCase):
    """Declared POSITIVE CONTROLS - green before the fix and after it.

    These two handlers already routed through `send_error`. If either of these
    ever goes red, the change under test broke a handler that was correct, which
    is a different and worse failure than the one this file exists to catch.
    """

    def test_heartbeat_last_resort_was_already_scrubbed(self):
        h = _FakeHandler("/api/decisions/heartbeat")
        with mock.patch("core.decision_detector.read_heartbeat",
                        side_effect=OSError(LEAKY)):
            rd._serve_decisions_heartbeat(h)
        self.assertEqual(h.status, 500)
        _assert_scrubbed(self, h.body["error"])

    def test_respond_active_last_resort_was_already_scrubbed(self):
        h = _FakeHandler("/api/decisions/respond_active")
        with mock.patch("core.decision_detector.DecisionStore",
                        side_effect=OSError(LEAKY)):
            rd._serve_decisions_respond_active_post(h, {"choice_index": 0})
        self.assertEqual(h.status, 500)
        _assert_scrubbed(self, h.body["error"])


class ModuleWideContractTests(unittest.TestCase):
    """Closes the RM-134 vacuity for this module.

    The RM-134 guard asserted the IMPORT. This asserts the module body, so a
    future handler that hand-rolls the envelope again fails here rather than
    passing an identity check that was never about the leak.
    """

    def test_module_source_never_serializes_an_exception(self):
        src = Path(rd.__file__).read_text(encoding="utf-8")
        # Strip the module docstring so prose describing the old code cannot
        # fail the guard (the same carve-out the RM-134 source guard uses).
        import ast
        tree = ast.parse(src)
        if ast.get_docstring(tree):
            tree.body = tree.body[1:]
        code = ast.unparse(tree)
        for bad in ("str(exc)", "format(exc)", "{exc}"):
            self.assertNotIn(
                bad, code,
                f"{bad} in routes_diag body puts raw exception text on the wire")

    def test_every_five_hundred_in_this_module_routes_through_send_error(self):
        """Positive complement to the negative assertion above.

        Uses the SHARED `guard_offenders` walker that GuardDomainTests pins,
        so the module can never be held to a laxer rule than the one whose
        behaviour is under test.
        """
        offenders = guard_offenders(Path(rd.__file__).read_text(encoding="utf-8"))
        self.assertEqual(
            offenders, [],
            f"except blocks at lines {offenders} send a 5xx without send_error")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# SECOND ROUND. Everything below was found by an independent adversarial pass
# run against the fix above, not by the pass that produced the fix. Two of the
# four are defects IN THAT FIX, which is the argument for running one.
# ---------------------------------------------------------------------------


class OcrGlobalStateTests(unittest.TestCase):
    """A diagnostic GET must not degrade the coach's OCR.

    `core/vision_tesseract.py:539` holds `_DROP_FIELDS` as a MODULE GLOBAL,
    `configure_drop_fields` rebinds it (`:552`), and `read_fast_fields` honours
    it at `:650` regardless of an explicit `fields=` argument. The coach path
    `core/vision_routing.py:97` calls `read_fast_fields` in the SAME process,
    so `_serve_ocr` setting that global left nine fields disabled for the coach
    until the next `/api/ocr` call happened to reset them.
    """

    def test_ocr_restores_the_drop_field_global_it_mutates(self):
        from core import vision_tesseract as vt

        before = set(vt._DROP_FIELDS)
        try:
            vt.configure_drop_fields({"sentinel_field"})
            h = _FakeHandler("/api/ocr")
            with mock.patch("urllib.request.urlopen", side_effect=OSError(LEAKY)):
                rd._serve_ocr(h)
            self.assertEqual(
                set(vt._DROP_FIELDS), {"sentinel_field"},
                "a diagnostic /api/ocr call permanently changed which fields "
                "the coach's OCR path reads")
        finally:
            vt.configure_drop_fields(before)


class RespondActiveInputValidationTests(unittest.TestCase):
    """`dismiss` was `bool()`-coerced, so any non-empty string dismissed.

    A client sending {"dismiss": "false", "choice_index": 1} had its real choice
    discarded and a dismissal journalled - and `record_choice` is irreversible.
    This is the same wrong-type class already fixed for `choice` in the sibling
    handler; the sibling got the guard and this one did not.
    """

    def _store(self, cls):
        cls.return_value.list_pending.return_value = [
            {"id": "abc123", "options": ["safe", "punish"]}]
        cls.return_value.record_choice.return_value = {
            "id": "abc123", "choice": "recorded"}
        return cls

    def test_string_false_does_not_dismiss(self):
        h = _FakeHandler("/api/decisions/respond_active")
        with mock.patch("core.decision_detector.DecisionStore") as cls:
            self._store(cls)
            rd._serve_decisions_respond_active_post(
                h, {"dismiss": "false", "choice_index": 1})
        self.assertEqual(h.status, 400,
                         f"a non-bool dismiss must be rejected, got {h.sent}")

    def test_real_bool_still_dismisses(self):
        """Control - the documented shape must keep working."""
        h = _FakeHandler("/api/decisions/respond_active")
        with mock.patch("core.decision_detector.DecisionStore") as cls:
            self._store(cls)
            rd._serve_decisions_respond_active_post(h, {"dismiss": True})
            cls.return_value.record_choice.assert_called_once()
            self.assertEqual(cls.return_value.record_choice.call_args[0][1],
                             "skip")
        self.assertEqual(h.status, 200)

    def test_float_choice_index_is_not_silently_truncated(self):
        h = _FakeHandler("/api/decisions/respond_active")
        with mock.patch("core.decision_detector.DecisionStore") as cls:
            self._store(cls)
            rd._serve_decisions_respond_active_post(h, {"choice_index": 1.9})
        self.assertEqual(h.status, 400,
                         f"1.9 must not silently become options[1]: {h.sent}")


class DecisionsLogCompletenessTests(unittest.TestCase):
    """The fixed `+4` over-fetch under-delivers when the tail is torn.

    Measured before the fix: 30 good rows plus 10 torn trailing lines returned
    14 entries for limit=20, silently short by 6.
    """

    def _write_log(self, tmp, good, junk_lines):
        rows = [json.dumps({"id": f"d{i}", "choice": "safe"}) for i in range(good)]
        rows.extend(junk_lines)
        tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def _get(self, tmp, limit):
        h = _FakeHandler(f"/api/decisions/log?limit={limit}")
        with mock.patch.object(rd, "_LOG_PATH", tmp):
            rd._serve_decisions_log(h)
        return h

    def test_torn_tail_does_not_shrink_the_result(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "decisions_log.jsonl"
            self._write_log(tmp, 30, ["{not json" for _ in range(10)])
            h = self._get(tmp, 20)
            self.assertEqual(h.status, 200)
            self.assertEqual(
                len(h.body["entries"]), 20,
                "a torn tail silently shortened the response below the "
                "requested limit")

    def test_blank_trailing_lines_do_not_shrink_the_result(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "decisions_log.jsonl"
            self._write_log(tmp, 30, ["" for _ in range(5)])
            h = self._get(tmp, 20)
            self.assertEqual(len(h.body["entries"]), 20)

    def test_newest_first_ordering_is_preserved(self):
        """Control - the fix must not reorder the entries."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "decisions_log.jsonl"
            self._write_log(tmp, 30, [])
            h = self._get(tmp, 3)
            self.assertEqual([e["id"] for e in h.body["entries"]],
                             ["d29", "d28", "d27"])


class GuardDomainTests(unittest.TestCase):
    """The guard's domain must match what the module docstring promises.

    The first version of this slice's docstring told the next author "do not
    hand-roll `h._send(5xx, ...)` here - the test fails on it". An adversarial
    pass showed that was FALSE: the guard walked only `ast.ExceptHandler`, so
    the two curated `h._send(503, ...)` calls in normal control flow were
    invisible to it. Guard narrower than its name - reintroduced by the very
    fix that closed the previous instance of that class.

    THE RESOLUTION IS NOT TO BAN THOSE 503s. They are legitimate: a constant
    literal body in normal flow carries no exception text, which is the thing
    the contract actually protects. So the DOCSTRING was corrected to state the
    enforced rule exactly, and these tests pin all three halves of it - the
    allowance included, so it stays deliberate rather than becoming an accident
    of how the walker happens to recurse.
    """

    def test_guard_flags_an_except_five_hundred_that_skips_send_error(self):
        sample = """
def f(h):
    try:
        g()
    except Exception as exc:
        h._send(500, json.dumps({'error': str(exc)}), 'j')
"""
        self.assertEqual(guard_offenders(sample), [6])

    def test_guard_allows_an_except_five_hundred_that_uses_send_error(self):
        sample = """
def f(h):
    try:
        g()
    except Exception as exc:
        send_error(h, exc)
"""
        self.assertEqual(guard_offenders(sample), [])

    def test_guard_deliberately_allows_a_constant_five_hundred_in_normal_flow(self):
        """The two curated 503s. Allowed BY DECISION, and pinned as such."""
        sample = """
def f(h):
    if entry is None:
        h._send(503, b'retry', 'j')
"""
        self.assertEqual(guard_offenders(sample), [])
    def test_the_real_module_has_exactly_the_two_known_constant_five_hundreds(self):
        """Pins the allowance to a COUNT, so a third one cannot appear unnoticed."""
        import ast
        tree = ast.parse(Path(rd.__file__).read_text(encoding="utf-8"))
        in_except = {id(n) for h in ast.walk(tree)
                     if isinstance(h, ast.ExceptHandler) for n in ast.walk(h)}
        consts = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "_send"
                  and n.args and isinstance(n.args[0], ast.Constant)
                  and isinstance(n.args[0].value, int) and n.args[0].value >= 500
                  and id(n) not in in_except]
        self.assertEqual(
            len(consts), 2,
            f"expected exactly the two curated 503s, found {len(consts)} at "
            f"{consts} - a new hand-rolled 5xx appeared in normal flow")
