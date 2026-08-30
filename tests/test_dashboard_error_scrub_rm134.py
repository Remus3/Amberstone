"""RM-134: the shared dashboard/MC JSON error envelope must never carry raw exception text.

`dashboard/_errors.send_error` is the last-resort error path for BOTH surfaces:
`:8888` (the dashboard) and `:8895` (Mission Control, which imports the very
same handlers through `mc/routes.py`). It used to serialize `str(exc)[:200]`
verbatim, so a filesystem path, a module name or a secret-shaped traceback
fragment could reach an HTTP client.

CLAUDE.md Error Handling: render a friendly degraded-mode message and log the
raw error to `logs/`. `agents/_supervisor_http._send_error` already does this;
this file pins the same contract for the dashboard/MC envelope.

Both surfaces are asserted because the leak is in a module they SHARE - fixing
one without the other would be a half fix.
"""
from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import _errors  # noqa: E402
from dashboard._errors import send_error  # noqa: E402

# A raw exception string carrying every shape the envelope must not leak:
# an absolute Windows path, a filename, and a distinctive secret-ish token.
LEAKY = r"unable to open database file at C:\Riot Commander\data\rewind_history.db (ZORBLEAK)"
FORBIDDEN = ("ZORBLEAK", "rewind_history.db", "C:\\", "Riot Commander", "OperationalError")


class _FakeHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler subclass the routes use."""

    def __init__(self):
        self.sent = None

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)

    @property
    def body(self) -> dict:
        assert self.sent is not None, "_send was never called"
        return json.loads(self.sent[1].decode("utf-8"))


def _assert_scrubbed(case: unittest.TestCase, err: str) -> None:
    case.assertIsInstance(err, str)
    for needle in FORBIDDEN:
        case.assertNotIn(
            needle, err,
            f"raw exception text leaked into the wire error field: {err!r}")


class SendErrorScrubTests(unittest.TestCase):
    def test_error_field_is_generic_not_str_exc(self):
        h = _FakeHandler()
        send_error(h, OSError(LEAKY))
        self.assertEqual(h.sent[0], 500)
        self.assertEqual(h.sent[2], "application/json")
        _assert_scrubbed(self, h.body["error"])
        self.assertEqual(h.body["error"], _errors.GENERIC_ERROR)

    def test_status_is_still_honoured(self):
        h = _FakeHandler()
        send_error(h, ValueError(LEAKY), status=502)
        self.assertEqual(h.sent[0], 502)
        _assert_scrubbed(self, h.body["error"])

    def test_raw_cause_reaches_the_log_not_the_wire(self):
        h = _FakeHandler()
        with self.assertLogs(_errors.log, level=logging.WARNING) as cap:
            send_error(h, OSError(LEAKY))
        self.assertTrue(any("ZORBLEAK" in line for line in cap.output),
                        f"raw cause was dropped instead of logged: {cap.output}")
        _assert_scrubbed(self, h.body["error"])

    def test_curated_public_message_is_allowed_through(self):
        """A caller may still choose its own user-safe wording."""
        h = _FakeHandler()
        send_error(h, OSError(LEAKY), status=503,
                   public_msg="coaching paused - retrying")
        self.assertEqual(h.body["error"], "coaching paused - retrying")

    def test_function_body_never_serializes_the_exception(self):
        """Source guard on the FUNCTION only - the docstring may cite the old
        code, and scanning the whole module would fail on the explanation."""
        import ast
        import inspect
        import textwrap

        body = ast.parse(textwrap.dedent(inspect.getsource(send_error)))
        fn = body.body[0]
        if ast.get_docstring(fn):
            fn.body = fn.body[1:]
        code = ast.unparse(fn)
        self.assertNotIn("str(exc)", code)
        self.assertNotIn("format(exc)", code)


class MissionControlRouteScrubTests(unittest.TestCase):
    """:8895 serves the very handlers below - mc/routes.py splices their tables."""

    def _mc_handler(self, path, table):
        import mc.routes as mc_routes

        for matcher, fn in getattr(mc_routes, table):
            if matcher(path):
                return fn
        self.fail(f"{path} not in mc.routes.{table}")

    def test_mc_loop_status_last_resort_is_scrubbed(self):
        from unittest import mock

        import dashboard.routes_loop_status as rls

        fn = self._mc_handler("/api/loop-status", "GET_ROUTES")
        h = _FakeHandler()
        with mock.patch.object(rls, "build_loop_status",
                               side_effect=OSError(LEAKY)):
            fn(h)
        self.assertEqual(h.sent[0], 500)
        _assert_scrubbed(self, h.body["error"])

    def test_mc_loop_control_last_resort_is_scrubbed(self):
        from unittest import mock

        import dashboard.routes_loop_control as rlc

        fn = self._mc_handler("/api/loop-control", "POST_ROUTES")
        h = _FakeHandler()
        with mock.patch.object(rlc, "apply_action", side_effect=OSError(LEAKY)):
            fn(h, {"action": "pause"})
        self.assertEqual(h.sent[0], 500)
        _assert_scrubbed(self, h.body["error"])


class DashboardSurfaceScrubTests(unittest.TestCase):
    """:8888 imports the same helper - assert the fix covers it too, not just MC."""

    def test_every_dashboard_importer_gets_the_scrubbed_helper(self):
        import importlib

        modules = (
            "dashboard.routes_coach",
            "dashboard.routes_diag",
            "dashboard.routes_loop_control",
            "dashboard.routes_loop_monitor",
            "dashboard.routes_loop_status",
            "dashboard.routes_spike_curve",
            "dashboard.routes_sr_user_builds",
            "dashboard.routes_state",
        )
        for name in modules:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                self.assertIs(mod.send_error, send_error,
                              f"{name} does not share the scrubbed helper")


if __name__ == "__main__":
    unittest.main()
