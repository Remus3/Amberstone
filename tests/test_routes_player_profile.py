"""Tests for ``dashboard.routes_player_profile`` GET /api/player-profile.

The route reads the LOCAL rewind_history.db via ``core.player_gpi`` ->
``core.draft_elo_db.open_ro`` (honors RC_REWIND_DB). The live DB is
gitignored, so these tests build a temp disk SQLite with the exact rewind
schema ``compute_gpi`` needs (reusing the ``_Builder`` from
``tests.test_player_gpi``) and point RC_REWIND_DB at it - deterministic +
clean-checkout safe.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import routes_player_profile
from tests.test_player_gpi import _Builder


class _RouteHarness:
    def __init__(self, qs: str):
        self.path = "/api/player-profile" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


def _build_db(path: Path, sr_games: int = 12, champ: int = 22,
              extra_champ_games: int = 0, extra_champ: int = 64) -> None:
    """Write a disk rewind DB with ``sr_games`` SR games on ``champ`` (plus
    optional games on a second champ) and commit it. Mirrors the start/stop
    env dance from tests/_draft_elo_fixture.py at call sites."""
    b = _Builder(path=str(path))
    for _ in range(sr_games):
        b.add(champ=champ)
    for _ in range(extra_champ_games):
        b.add(champ=extra_champ)
    b.conn.commit()
    b.close()


class _RewindDbFixture:
    """Build a disk rewind DB in a temp dir + point RC_REWIND_DB at it.

    Restores the prior RC_REWIND_DB on stop (preserve any outer override).
    """

    def __init__(self, **build_kw) -> None:
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._prev_env: str | None = None
        self._build_kw = build_kw
        self.path: Path | None = None

    def start(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory(prefix="rc_player_profile_")
        self.path = Path(self._tmp.name) / "rewind_history.db"
        _build_db(self.path, **self._build_kw)
        self._prev_env = os.environ.get("RC_REWIND_DB")
        os.environ["RC_REWIND_DB"] = str(self.path)
        return self.path

    def stop(self) -> None:
        if self._prev_env is None:
            os.environ.pop("RC_REWIND_DB", None)
        else:
            os.environ["RC_REWIND_DB"] = self._prev_env
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


class PopulatedDbTests(unittest.TestCase):
    """12 SR games on champ 22 + 8 on champ 64 (enough for all 8 axes)."""

    @classmethod
    def setUpClass(cls):
        cls._fix = _RewindDbFixture(sr_games=12, champ=22,
                                    extra_champ_games=8, extra_champ=64)
        cls._fix.start()

    @classmethod
    def tearDownClass(cls):
        cls._fix.stop()

    def setUp(self):
        routes_player_profile._reset_caches()

    def test_full_round_trip_eight_axes(self):
        h = _RouteHarness("")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["axes"]), 8)
        self.assertIn("overall", payload)
        self.assertIn("confidence", payload)
        self.assertFalse(payload["cached"])
        self.assertIsInstance(payload["elapsed_ms"], int)

    def test_mode_defaults_to_sr(self):
        h = _RouteHarness("")
        routes_player_profile._serve_player_profile(h)
        payload = json.loads(h.sent_body)
        self.assertEqual(payload["mode"], "sr")

    def test_champion_filter_passes_through(self):
        h = _RouteHarness("champion=64")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertEqual(payload["champion"], 64)
        self.assertEqual(payload["n_games"], 8)

    def test_champion_omitted_is_null(self):
        h = _RouteHarness("")
        routes_player_profile._serve_player_profile(h)
        payload = json.loads(h.sent_body)
        self.assertIsNone(payload["champion"])

    def test_champions_pool_present(self):
        # The drilldown selector source: every ok payload carries the operator's
        # played-champion pool for the mode (12 on champ 22, 8 on champ 64).
        h = _RouteHarness("")
        routes_player_profile._serve_player_profile(h)
        payload = json.loads(h.sent_body)
        self.assertEqual(payload["champions"], [
            {"champion_id": 22, "n_games": 12},
            {"champion_id": 64, "n_games": 8},
        ])

    def test_champions_pool_is_mode_wide_not_champion_filtered(self):
        # A champion-filtered request still returns the FULL pool (so the
        # selector keeps every option after a drilldown).
        h = _RouteHarness("champion=64")
        routes_player_profile._serve_player_profile(h)
        payload = json.loads(h.sent_body)
        self.assertEqual([c["champion_id"] for c in payload["champions"]],
                         [22, 64])
        self.assertEqual(payload["champion"], 64)

    def test_cache_hit_second_call(self):
        h1 = _RouteHarness("")
        routes_player_profile._serve_player_profile(h1)
        self.assertFalse(json.loads(h1.sent_body)["cached"])
        h2 = _RouteHarness("")
        routes_player_profile._serve_player_profile(h2)
        self.assertEqual(h2.sent_status, 200)
        self.assertTrue(json.loads(h2.sent_body)["cached"])


class InsufficientDbTests(unittest.TestCase):
    """Below MIN_GAMES -> ok payload, confidence insufficient, empty axes."""

    @classmethod
    def setUpClass(cls):
        cls._fix = _RewindDbFixture(sr_games=5, champ=22)
        cls._fix.start()

    @classmethod
    def tearDownClass(cls):
        cls._fix.stop()

    def setUp(self):
        routes_player_profile._reset_caches()

    def test_insufficient_history(self):
        h = _RouteHarness("")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["confidence"], "insufficient")
        self.assertEqual(payload["axes"], [])
        self.assertIsNone(payload["overall"])


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        routes_player_profile._reset_caches()

    def test_bad_mode_400(self):
        h = _RouteHarness("mode=urf")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(json.loads(h.sent_body)["ok"])

    def test_bad_window_non_int_400(self):
        h = _RouteHarness("window=lots")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 400)

    def test_bad_window_out_of_range_400(self):
        h = _RouteHarness("window=999")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 400)

    def test_bad_champion_non_int_400(self):
        h = _RouteHarness("champion=ashe")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 400)


class DegradedDbTests(unittest.TestCase):
    def setUp(self):
        routes_player_profile._reset_caches()

    def test_compute_failure_returns_503(self):
        with patch("dashboard.routes_player_profile._compute",
                   side_effect=RuntimeError("db missing")):
            h = _RouteHarness("")
            routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 503)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["ok"])
        # Raw exception text must not leak.
        self.assertNotIn("db missing", payload["error"])


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        path = "/api/player-profile"
        matched = any(
            _safe_match(pred, path) for pred, _handler in routes
        )
        self.assertTrue(matched,
                        "/api/player-profile not registered with dispatch")


def _safe_match(pred, path: str) -> bool:
    try:
        return bool(pred(path))
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    unittest.main()
