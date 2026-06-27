"""L4 Phase-D - /api/ds-preview capability_gap surface (RC_CAPGAP_SURFACE).

The route gained an additive ``capability_gap`` field that surfaces the
in-process multi-axis capability-gap synthesizer
(``core.ds_capability_gap.build_capability_gap``) behind a default-OFF
flip flag ``RC_CAPGAP_SURFACE``. These tests prove:
  - flag ON + a real gap (Lux self-sustain vs a heavy-sustain comp) ->
    the field is populated and passed through faithfully.
  - flag OFF (default) -> the field is None.
  - no resolvable enemies -> the field is None.
  - flag ON but the synthesizer reports applies=False (Aatrox out-sustains
    the same comp) -> the field is None.

Only the dispatcher boundary is mocked (no live DS server). The
synthesizer runs against REAL scorer data, so ``archetype`` is passed
explicitly in the payload to avoid mocking ``get_archetype_for``.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard.routes_state import _serve_ds_preview_post


class _Handler:
    """Stub HTTP handler that captures ``_send`` calls.

    Mirrors the harness in tests/test_routes_ds_preview_scorer.py - routes
    only touch ``self._send(status, body, content_type)``.
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


# A normal ranked response - the capability_gap surface is independent of
# the ranked rows, so a single mage-shaped stub is reused across cases.
_MAGE_ROWS = [
    {"item_id": "3089", "item_name": "Rabadon's Deathcap",
     "delta": 11.0, "gold": 3500},
    {"item_id": "3157", "item_name": "Zhonya's Hourglass",
     "delta": 6.0, "gold": 2600},
]


class DsPreviewCapabilityGapTests(unittest.TestCase):
    """capability_gap is surfaced only behind RC_CAPGAP_SURFACE and only
    when the synthesizer reports applies=True."""

    @mock.patch.dict("os.environ", {"RC_CAPGAP_SURFACE": "1"})
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_capgap_present_when_flag_on_and_gap_fires(self, mock_disp):
        mock_disp.return_value = _dispatcher_response("mage", _MAGE_ROWS)
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Lux", "mode": "SR", "level": 6,
            "archetype": "mage",
            "enemies": ["Vladimir", "Fiddlesticks", "Warwick"],
        })
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertTrue(resp.get("ok"))
        cg = resp.get("capability_gap")
        self.assertIsNotNone(cg)
        self.assertTrue(cg.get("applies"))
        self.assertEqual(cg.get("top_gap"), "sustain")
        self.assertEqual(cg.get("my_champion"), "Lux")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_capgap_absent_when_flag_off(self, mock_disp):
        # No env patch -> RC_CAPGAP_SURFACE defaults OFF.
        mock_disp.return_value = _dispatcher_response("mage", _MAGE_ROWS)
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Lux", "mode": "SR", "level": 6,
            "archetype": "mage",
            "enemies": ["Vladimir", "Fiddlesticks", "Warwick"],
        })
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertIsNone(resp.get("capability_gap"))

    @mock.patch.dict("os.environ", {"RC_CAPGAP_SURFACE": "1"})
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_capgap_none_when_no_enemies(self, mock_disp):
        # Explicit empty enemies list -> _resolve_enemy_champions returns []
        # (no live game in the test env, so no relay fallback either).
        mock_disp.return_value = _dispatcher_response("mage", _MAGE_ROWS)
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Lux", "mode": "SR", "level": 6,
            "archetype": "mage",
            "enemies": [],
        })
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertIsNone(resp.get("capability_gap"))

    @mock.patch.dict("os.environ", {"RC_CAPGAP_SURFACE": "1"})
    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    def test_capgap_none_when_no_gap(self, mock_disp):
        # Aatrox out-sustains the same heavy-sustain comp in kind, and no
        # other axis fires -> build_capability_gap reports applies=False, so
        # the route faithfully passes through None (verified live:
        # build_capability_gap('Aatrox', [...], 'SR')["applies"] is False).
        mock_disp.return_value = _dispatcher_response("hybrid", [
            {"item_id": "3078", "item_name": "Trinity Force",
             "hybrid_delta_pct": 0.08, "gold": 3333},
        ])
        h = _Handler()
        _serve_ds_preview_post(h, {
            "champion": "Aatrox", "mode": "SR", "level": 6,
            "archetype": "bruiser",
            "enemies": ["Vladimir", "Fiddlesticks", "Warwick"],
        })
        self.assertEqual(h.status, 200)
        resp = h.json()
        self.assertIsNone(resp.get("capability_gap"))


if __name__ == "__main__":
    unittest.main()
