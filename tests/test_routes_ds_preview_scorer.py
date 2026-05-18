"""s183 - /api/ds-preview per-row scorer stamp.

After s182 the response carries a top-level ``scorer`` field but each row
in ``ranked`` did not. The champ-select Build Chooser caches just the
rows (not the response envelope), so without per-row scorer it couldn't
map the row's delta to the correct unit suffix. s183 mirrors the
``display_rows`` shape from ``coach_integration.archetype_dispatch`` by
stamping ``scorer`` on each row of the ``ranked`` array.

These tests mock the dispatcher boundary so no live DS server is needed.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard.routes_state import _serve_ds_preview_post


class _Handler:
    """Stub HTTP handler that captures ``_send`` calls.

    The real handler is an http.server.BaseHTTPRequestHandler subclass;
    routes only touch ``self._send(status, body, content_type)``.
    """
    def __init__(self) -> None:
        self.status: int = 0
        self.body: bytes = b""
        self.content_type: str = ""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type

    def json(self) -> dict:
        return json.loads(self.body.decode())


def _dispatcher_response(scorer: str, rows: list[dict]) -> dict:
    return {
        "ok":        True,
        "scorer":    scorer,
        "archetype": "carry" if scorer == "dps" else scorer,
        "ranked":    rows,
        "fell_back": False,
    }


class DsPreviewPerRowScorerStampTests(unittest.TestCase):
    """Each row in `ranked` carries `scorer` matching the top-level field."""

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_carry_stamps_dps_scorer_on_every_row(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _dispatcher_response("dps", [
            {"item_id": "3094", "item_name": "Rapid Firecannon",
             "delta": 54.0, "gold": 2900},
            {"item_id": "3031", "item_name": "Infinity Edge",
             "delta": 48.0, "gold": 3500},
        ])
        h = _Handler()
        _serve_ds_preview_post(h, {"champion": "Caitlyn", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertTrue(resp.get("ok"))
        self.assertEqual(resp.get("scorer"), "dps")
        self.assertGreaterEqual(len(resp.get("ranked", [])), 2)
        for r in resp["ranked"]:
            self.assertEqual(r.get("scorer"), "dps")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_tank_stamps_ehp_scorer_on_every_row(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "tank"}
        mock_disp.return_value = _dispatcher_response("ehp", [
            {"item_id": "3083", "item_name": "Warmog's Armor",
             "delta": 1690.0, "gold": 3100},
            {"item_id": "7019", "item_name": "Heartsteel",
             "delta": 1521.0, "gold": 3000},
        ])
        h = _Handler()
        _serve_ds_preview_post(h, {"champion": "Malphite", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertEqual(resp.get("scorer"), "ehp")
        for r in resp["ranked"]:
            self.assertEqual(r.get("scorer"), "ehp")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_enchanter_stamps_hps_scorer_on_every_row(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "enchanter"}
        mock_disp.return_value = _dispatcher_response("hps", [
            {"item_id": "6620", "item_name": "Echoes of Helia",
             "delta": 25.14, "gold": 2200},
            {"item_id": "3504", "item_name": "Ardent Censer",
             "delta": 15.0, "gold": 2200},
        ])
        h = _Handler()
        _serve_ds_preview_post(h, {"champion": "Soraka", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertEqual(resp.get("scorer"), "hps")
        for r in resp["ranked"]:
            self.assertEqual(r.get("scorer"), "hps")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_hybrid_pct_scoring_stamps_hybrid(self, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": "bruiser"}
        # hybrid rows carry hybrid_delta_pct instead of delta - the route's
        # _delta() helper scales by 100; that's tested elsewhere. Here we
        # only assert the per-row stamp.
        mock_disp.return_value = _dispatcher_response("hybrid", [
            {"item_id": "3078", "item_name": "Trinity Force",
             "hybrid_delta_pct": 0.08, "gold": 3333},
        ])
        h = _Handler()
        _serve_ds_preview_post(h, {"champion": "Jarvan IV", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertEqual(resp.get("scorer"), "hybrid")
        for r in resp["ranked"]:
            self.assertEqual(r.get("scorer"), "hybrid")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_archetype_override_propagates(self, mock_arch, mock_disp):
        """Payload override skips the persisted pick and the response
        echoes both the override and the resulting scorer."""
        # get_archetype_for would say bruiser, but caller asked for mage.
        mock_arch.return_value = {"primary": "bruiser"}
        mock_disp.return_value = _dispatcher_response("ability", [
            {"item_id": "3089", "item_name": "Rabadon's Deathcap",
             "delta": 11.0, "gold": 3500},
        ])
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Veigar", "mode": "SR", "level": 11,
            "archetype": "mage",
        })
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertEqual(resp.get("archetype"), "mage")
        self.assertEqual(resp.get("scorer"), "ability")
        for r in resp["ranked"]:
            self.assertEqual(r.get("scorer"), "ability")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_empty_ranked_still_returns_scorer(self, mock_arch, mock_disp):
        """Engine returns empty ranked list -> response is well-formed
        with scorer + archetype siblings + ranked=[]."""
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _dispatcher_response("dps", [])
        h = _Handler()
        _serve_ds_preview_post(h, {"champion": "Caitlyn", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertTrue(resp.get("ok"))
        self.assertEqual(resp.get("scorer"), "dps")
        self.assertEqual(resp.get("ranked"), [])

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_engine_down_returns_503(self, mock_arch, mock_disp):
        """Dispatcher None (engine unreachable) -> 503 with explicit
        error message, not 200 with empty rows."""
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = None
        h = _Handler()
        _serve_ds_preview_post(h, {"champion": "Caitlyn", "mode": "SR", "level": 11})
        self.assertEqual(h.status, 503)
        resp = h.json()
        self.assertFalse(resp.get("ok"))


if __name__ == "__main__":
    unittest.main()
