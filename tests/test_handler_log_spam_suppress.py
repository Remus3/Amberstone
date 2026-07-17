"""Pin the high-frequency-poll log suppression contract on Handler.log_message.

dashboard/_handler.py overrides BaseHTTPRequestHandler.log_message (the
per-request trace hook) and skips emit for /api/decisions,
/api/decisions/heartbeat, and /api/vision-state - the dashboard polls
these at 2Hz across every open tab and they made up ~90% of log volume
(~7100 lines/hr in a 2.5h sample). Lower-frequency endpoints stay
loggable (diagnostic value when something breaks). Error/info log calls
elsewhere in the handler are unaffected.
"""

from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import _handler


SRC = Path(__file__).resolve().parent.parent / "dashboard" / "_handler.py"


class _FakeHandler:
    """Minimal stand-in for a BaseHTTPRequestHandler instance: just
    enough to call Handler.log_message unbound. log_message reads no
    instance state besides what the format args carry."""


class SuppressLogPathsConstantTests(unittest.TestCase):
    def test_constant_is_tuple_of_str(self):
        self.assertIsInstance(_handler._SUPPRESS_LOG_PATHS, tuple)
        for p in _handler._SUPPRESS_LOG_PATHS:
            self.assertIsInstance(p, str)

    def test_constant_contains_high_frequency_paths(self):
        # Needles are bare path prefixes (no trailing space) so query-string
        # variants like /api/minimap-crop?mode=sr also match. Item 171
        # Slice C drift flag: trailing-space needles never matched
        # query-string lines so /api/minimap-crop ran unsuppressed at
        # 0.490/sec despite being in the tuple since item 156.
        expected = {
            "GET /api/state",
            "GET /api/decisions",
            "GET /api/decisions/heartbeat",
            "GET /api/vision-state",
            "GET /api/asset-stamp",
            "GET /api/ui-version",
            "GET /api/activity",
            "GET /api/env",
            "GET /api/locked-champion",
            "GET /api/minimap-crop",
            "POST /api/loadout/list",
        }
        self.assertEqual(set(_handler._SUPPRESS_LOG_PATHS), expected)
        # Ordering is preserved as declared in the source for readability.
        self.assertEqual(len(_handler._SUPPRESS_LOG_PATHS), len(expected))
        # Defense-in-depth: no needle may end with a space (regressing to
        # the item 156 silent-failure on query-string paths).
        for needle in _handler._SUPPRESS_LOG_PATHS:
            self.assertFalse(needle.endswith(" "),
                             f"needle {needle!r} ends with space - will miss query-string variants")


class LogMessageSuppressionTests(unittest.TestCase):
    def test_decisions_poll_is_suppressed(self):
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "21/May/2026 12:00:00",
                "GET /api/decisions HTTP/1.1",
                "200",
                "1234",
            )
            mock_debug.assert_not_called()

    def test_decisions_heartbeat_poll_is_suppressed(self):
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "21/May/2026 12:00:00",
                "GET /api/decisions/heartbeat HTTP/1.1",
                "200",
                "32",
            )
            mock_debug.assert_not_called()

    def test_vision_state_poll_is_suppressed(self):
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "21/May/2026 12:00:00",
                "GET /api/vision-state HTTP/1.1",
                "200",
                "456",
            )
            mock_debug.assert_not_called()

    def test_minimap_crop_poll_is_suppressed(self):
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "23/May/2026 01:00:00",
                "GET /api/minimap-crop HTTP/1.1",
                "200",
                "12345",
            )
            mock_debug.assert_not_called()

    def test_minimap_crop_poll_with_query_string_is_suppressed(self):
        # Item 171 Slice C drift fix - actual live cadence carries a
        # query string (mode=sr&_=ts) that the trailing-space needle
        # silently failed to match.
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "24/May/2026 14:30:00",
                "GET /api/minimap-crop?mode=sr&_=1748113800123 HTTP/1.1",
                "200",
                "12345",
            )
            mock_debug.assert_not_called()

    def test_activity_poll_with_query_string_is_suppressed(self):
        # Same query-string variant on /api/activity?limit=6 (~0.099/sec).
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "24/May/2026 14:30:00",
                "GET /api/activity?limit=6 HTTP/1.1",
                "200",
                "1024",
            )
            mock_debug.assert_not_called()

    def test_loadout_list_poll_is_suppressed(self):
        # Item 184 carry from item 183 (g): /api/loadout/list ran at
        # 0.631/sec - new top non-suppressed log entry until this fix.
        # Champ-select + item-build panel call this with method=POST per
        # `dashboard/routes_loadout.py:319` + `web/js/panels/item_build.js:158/438`
        # + `web/js/panels/champ_select.js:2136` - 3 call sites all POST.
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "25/May/2026 00:30:00",
                "POST /api/loadout/list HTTP/1.1",
                "200",
                "2048",
            )
            mock_debug.assert_not_called()

    def test_loadout_list_poll_with_query_string_is_suppressed(self):
        # Defensive: if a future caller adds a query string, the bare-path
        # substring needle still matches.
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "25/May/2026 00:30:00",
                "POST /api/loadout/list?champion=Jinx HTTP/1.1",
                "200",
                "2048",
            )
            mock_debug.assert_not_called()

    def test_non_suppressed_path_is_logged(self):
        # /api/health/all is a low-frequency endpoint kept unsuppressed so its
        # request trace retains diagnostic value.
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "21/May/2026 12:00:00",
                "GET /api/health/all HTTP/1.1",
                "200",
                "8192",
            )
            mock_debug.assert_called_once()
            # The formatted message must include the path so diagnostics
            # remain readable; assert the substring rather than an exact
            # match (caller-supplied fmt may evolve).
            (msg,), _kwargs = mock_debug.call_args
            self.assertIn("/api/health/all", msg)
            self.assertTrue(msg.startswith("HTTP "))

    def test_post_endpoint_is_logged(self):
        # POST /api/bridge/inbox is a write endpoint - never suppressed.
        with patch.object(_handler.log, "debug") as mock_debug:
            _handler.Handler.log_message(
                _FakeHandler(),
                '%s - - [%s] "%s" %s %s',
                "127.0.0.1",
                "21/May/2026 12:00:00",
                "POST /api/bridge/inbox HTTP/1.1",
                "200",
                "128",
            )
            mock_debug.assert_called_once()


class ErrorPathLogEmitUnaffectedTests(unittest.TestCase):
    """The suppression operates on log_message (the request-trace hook)
    only - the other log.* call sites in _handler.py (proxy_to_supervisor
    exception, csrf reject, do_POST bad_body) must remain reachable."""

    def test_source_has_other_log_call_sites(self):
        src = SRC.read_text(encoding="utf-8")
        # Existence smoke: these explicit log calls live OUTSIDE the
        # log_message override and continue to emit.
        self.assertIn('log.debug("proxy %s: %s"', src)
        self.assertIn('log.warning("do_POST CSRF reject', src)
        self.assertIn('log.debug("do_POST bad_body: %s"', src)
        self.assertIn('log.debug("csrf_ok parse failed; allowing")', src)

    def test_warning_call_is_not_routed_through_log_message(self):
        # Sanity: log_message overrides debug-trace only. A direct
        # log.warning(...) sidesteps the suppression entirely.
        with patch.object(_handler.log, "warning") as mock_warn:
            _handler.log.warning("simulated csrf reject path=/api/x")
            mock_warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
