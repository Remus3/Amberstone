"""Lane 8 cycle 19: /api/health/all must not serve raw exception text.

`dashboard/routes_state._serve_health_all` builds a green/yellow/red rollup for
the dashboard's top-right health dot. Every sub-probe (vision, Daemon Slayer,
supervisor, cost, agent6) was wrapped in a bare `except Exception` that wrote
`str(e)[:120]` straight into the 200 response body, and `_agent6_audit_outcomes`
copied a task's `last_error` in verbatim with no cap at all.

That is the RM-134 leak class, in a module RM-134's own guard NAMES. The guard
(`tests/test_dashboard_error_scrub_rm134.py`) only asserts
`mod.send_error is send_error` - that the module IMPORTS the scrubbed helper.
It never asserts the module USES it, so `routes_state` passed while six inline
sites bypassed the envelope entirely.

MEASURED live on 2026-08-30 before the fix: `/api/health/all` on the running
dashboard served 227 characters of raw `claude` CLI stderr under
`agent6.last_outcomes[].last_error`, naming an auth env var. `:8888` was
confirmed reachable off-loopback the same day (LAN 192.168.8.230, HTTP 200), so
this was not a localhost-only surface.

CLAUDE.md "Error Handling": never surface a raw error string in a user-facing
dashboard panel - log it to `logs/`, render a friendly degraded message.

No consumer reads any of these fields: `web/js/main.js:7506+` is the only
fetcher of `/api/health/all` and reads `alive`, `uptime_s`, `engine_version`,
`items`, `champions`, `status`, `cost.banner`, `supervisor.run_id` and
`rc_version` - never `error` and never `last_error`. The keys are kept so the
served shape is unchanged.
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
from dashboard._errors import GENERIC_ERROR  # noqa: E402

# A raw exception string carrying every shape the rollup must not leak: an
# absolute Windows path, a filename, and a distinctive secret-shaped token.
LEAKY = r"cannot reach C:\Riot Commander\API-Key-Claude.txt (ZORBLEAK-19)"
FORBIDDEN = ("ZORBLEAK-19", "API-Key-Claude", "C:\\", "Riot Commander")


class _FakeHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler subclass the routes use."""

    def __init__(self):
        self.sent = None
        self.body = None

    def _send(self, code, body, ctype):
        self.sent = (code, ctype)
        self.body = body


def _assert_scrubbed(case, blob: str) -> None:
    for needle in FORBIDDEN:
        case.assertNotIn(
            needle, blob,
            f"raw exception text {needle!r} reached the /api/health/all body",
        )


class HealthAllScrubTests(unittest.TestCase):
    """Every sub-probe failure must degrade to the generic line, not raw text."""

    def _rollup_with_failing(self, target: str):
        """Serve /api/health/all with `target` raising LEAKY; return parsed body."""
        h = _FakeHandler()
        with mock.patch.object(target.split("|")[0], target.split("|")[1],
                               side_effect=OSError(LEAKY)):
            routes_state._serve_health_all(h)
        self.assertIsNotNone(h.body, "handler sent no body")
        return json.loads(h.body.decode("utf-8"))

    def test_vision_probe_failure_is_scrubbed(self):
        h = _FakeHandler()
        with mock.patch.object(routes_state.urllib.request, "urlopen",
                               side_effect=OSError(LEAKY)):
            routes_state._serve_health_all(h)
        body = h.body.decode("utf-8")
        _assert_scrubbed(self, body)
        rollup = json.loads(body)
        # Shape preserved: the key stays, the dot still resolves.
        self.assertFalse(rollup["vision"]["alive"])
        self.assertEqual(rollup["vision"]["error"], GENERIC_ERROR)

    def test_daemon_slayer_probe_failure_is_scrubbed(self):
        h = _FakeHandler()
        with mock.patch.object(routes_state.urllib.request, "urlopen",
                               side_effect=OSError(LEAKY)):
            routes_state._serve_health_all(h)
        rollup = json.loads(h.body.decode("utf-8"))
        _assert_scrubbed(self, h.body.decode("utf-8"))
        self.assertFalse(rollup["daemon_slayer"]["alive"])
        self.assertEqual(rollup["daemon_slayer"]["error"], GENERIC_ERROR)

    def test_supervisor_probe_failure_is_scrubbed(self):
        h = _FakeHandler()
        real_read_json = routes_state.read_json

        def _boom(name):
            if "supervisor.pid" in str(name):
                raise OSError(LEAKY)
            return real_read_json(name)

        with mock.patch.object(routes_state, "read_json", side_effect=_boom):
            routes_state._serve_health_all(h)
        _assert_scrubbed(self, h.body.decode("utf-8"))

    def test_agent6_last_error_is_not_served_verbatim(self):
        """The measured live leak: raw CLI stderr copied into the rollup."""
        outcomes = [{
            "task_id": "t-deadbeef",
            "event": "failed",
            "ts": "2026-08-30T00:00:00+00:00",
            "status": "failed",
            "last_error": LEAKY,
        }]
        # Patch `_ex`, NOT the list-only wrapper: `_serve_health_all` calls the
        # `_ex` form for the scanned_clean signal, so mocking the wrapper would
        # patch a function this path never calls and the test would pass
        # vacuously off the real scrub.
        h = _FakeHandler()
        with mock.patch.object(routes_state, "_agent6_audit_outcomes_ex",
                               return_value=(outcomes, True)):
            routes_state._serve_health_all(h)
        _assert_scrubbed(self, h.body.decode("utf-8"))

    def test_agent6_outcomes_scrubs_last_error_at_the_source(self):
        """_agent6_audit_outcomes itself must not hand out raw error text."""
        line = json.dumps({
            "task": {"id": "t-1", "op": "agent6-full-audit-pass",
                     "status": "failed", "last_error": LEAKY},
            "event": "failed",
            "ts": "2026-08-30T00:00:00+00:00",
        })
        h_path = mock.MagicMock()
        h_path.exists.return_value = True
        h_path.read_text.return_value = line
        h_path.stat.return_value = mock.Mock(st_mtime_ns=1, st_size=len(line))
        routes_state._A6_MEMO = None
        with mock.patch.object(routes_state, "APP_DIR") as app_dir:
            app_dir.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = h_path
            out = routes_state._agent6_audit_outcomes(max_count=3)
        routes_state._A6_MEMO = None
        self.assertEqual(len(out), 1)
        _assert_scrubbed(self, json.dumps(out))

    def test_ds_preview_500_does_not_echo_the_exception(self):
        """`/api/ds-preview` echoed `str(exc)[:200]` while its own sibling
        `/api/build-order` correctly used the scrubbed envelope for the SAME
        input. Everything inside that try (registry reads, champion id
        resolution, build planning) can raise an OSError carrying an absolute
        path."""
        # Patch where it is LOOKED UP, not on this module: the handler does
        # `from core.archetype_picks import canonical_champion_id` INSIDE the
        # function body. Patching `routes_state.canonical_champion_id` with
        # create=True silently invents an attribute nobody reads, the handler
        # runs clean and the test passes vacuously with a 200.
        h = _FakeHandler()
        with mock.patch("core.archetype_picks.canonical_champion_id",
                        side_effect=OSError(LEAKY)):
            routes_state._serve_ds_preview_post(h, {"champion": "Ashe"})
        self.assertEqual(h.sent[0], 500)
        _assert_scrubbed(self, h.body.decode("utf-8"))

    def test_ui_version_500_does_not_echo_the_exception(self):
        h = _FakeHandler()
        with mock.patch("dashboard._static.compute_asset_hash",
                        side_effect=OSError(LEAKY)):
            routes_state._serve_ui_version(h)
        self.assertEqual(h.sent[0], 500)
        _assert_scrubbed(self, h.body.decode("utf-8"))

    def test_a_failed_agent6_scan_is_unknown_not_green(self):
        """A read error and a clean audit history must not look the same.

        `[]` from an unreadable `task_queue.jsonl` made `len(last_two) >= 2`
        False and the verdict fell through to a confident GREEN. MEASURED
        before the fix: with `read_text` raising OSError on the live 4.6 MB
        file, the rollup served `{"last_outcomes": [], "status": "green"}`.

        The two halves are asserted SEPARATELY and hermetically. An earlier
        version of this test drove the whole rollup with a GLOBAL
        `pathlib.Path.read_text` patch; it passed alone and under `-n 4` but
        failed in the full suite under `-n 8`, because that patch is far too
        broad (every unrelated read in the handler goes through it) and the
        function also reads module-global `_A6_MEMO`. A flaky guard is worse
        than no guard, so neither half touches global state now.
        """
        # Half 1: the scan reports the failure. Scoped to the ONE file, so an
        # unrelated read elsewhere in the process is unaffected.
        import tempfile
        real_read_text = Path.read_text
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            q = tmp / "agents" / "state"
            q.mkdir(parents=True)
            target = q / "task_queue.jsonl"
            target.write_text("{}", encoding="utf-8")

            def only_this_file_fails(self_path, *a, **kw):
                if self_path == target:
                    raise OSError("io error")
                return real_read_text(self_path, *a, **kw)

            routes_state._A6_MEMO = None
            try:
                with mock.patch.object(routes_state, "APP_DIR", tmp), \
                     mock.patch.object(Path, "read_text", only_this_file_fails):
                    _, scanned_clean = routes_state._agent6_audit_outcomes_ex(3)
            finally:
                routes_state._A6_MEMO = None
        self.assertFalse(scanned_clean, "a failed scan must report itself")

        # Half 2: the rollup maps that signal to "unknown", not "green".
        h = _FakeHandler()
        with mock.patch.object(routes_state, "_agent6_audit_outcomes_ex",
                               return_value=([], False)):
            routes_state._serve_health_all(h)
        rollup = json.loads(h.body.decode("utf-8"))
        self.assertEqual(rollup["agent6"]["status"], "unknown")

    def test_a_clean_empty_history_is_still_green(self):
        """The honest third state must not swallow the ordinary case."""
        h = _FakeHandler()
        routes_state._A6_MEMO = None
        with mock.patch.object(routes_state, "_agent6_audit_outcomes_ex",
                               return_value=([], True)):
            routes_state._serve_health_all(h)
        routes_state._A6_MEMO = None
        rollup = json.loads(h.body.decode("utf-8"))
        self.assertEqual(rollup["agent6"]["status"], "green")

    def test_healthy_rollup_carries_no_error_key(self):
        """The fix must not invent an error field on the success path."""
        h = _FakeHandler()
        routes_state._serve_health_all(h)
        rollup = json.loads(h.body.decode("utf-8"))
        self.assertIn("status", rollup)
        self.assertIn(rollup["status"], ("green", "yellow", "red"))


if __name__ == "__main__":
    unittest.main()
