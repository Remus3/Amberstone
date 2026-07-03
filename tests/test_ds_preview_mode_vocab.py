"""A1 (QA 2026-07-03) - /api/ds-preview mode vocabulary tolerance.

Canonical mode vocabulary for the route is the
``agents.daemon_slayer.rank.MODE_MAP_ID`` key set: SR | ARAM | ARENA |
BRAWL. The champ-select capability-gap chip historically sent the raw
Live Client / LCU gameMode for event modes - queue 2400 (ARAM Mayhem)
ships ``mode="KIWI"``, Arena lobbies say ``CHERRY`` - which silently
fell through the per-mode item-legality filter (MODE_MAP_ID miss =
allow-all). The route now aliases those to their canonical equivalents
at the boundary.

Regression (ruling A1, docs/qa/CHAMP_SELECT_QA_2026-07-03.md): the
queue-2400 vocabulary is accepted BOTH ways - ``KIWI`` and ``ARAM``
land on the engine as the same canonical ``ARAM``.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard.routes_state import _serve_ds_preview_post


class _Handler:
    """Stub HTTP handler capturing ``_send`` (mirrors the harness in
    tests/test_ds_preview_capgap.py)."""

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


_ROWS = [
    {"item_id": "3031", "item_name": "Infinity Edge",
     "delta": 25.0, "gold": 3450},
]


def _dispatcher_response() -> dict:
    return {
        "ok":        True,
        "scorer":    "dps",
        "archetype": "carry",
        "ranked":    _ROWS,
        "fell_back": False,
    }


class DsPreviewModeAliasTests(unittest.TestCase):
    """Payload ``mode`` reaches the engine dispatcher canonicalized."""

    def _mode_seen_by_engine(self, payload: dict) -> str:
        with mock.patch(
            "core.daemon_slayer_client.rank_for_primary_archetype",
            return_value=_dispatcher_response(),
        ) as mock_disp:
            h = _Handler()
            _serve_ds_preview_post(h, payload)
            self.assertEqual(h.status, 200)
            self.assertTrue(h.json().get("ok"))
            self.assertTrue(mock_disp.called)
            return mock_disp.call_args.kwargs.get("mode")

    def test_kiwi_aliases_to_aram(self):
        # Queue 2400 (ARAM Mayhem): frontend historically sent KIWI.
        mode = self._mode_seen_by_engine(
            {"champion": "Ashe", "mode": "KIWI", "level": 6})
        self.assertEqual(mode, "ARAM")

    def test_kiwi_lowercase_aliases_to_aram(self):
        mode = self._mode_seen_by_engine(
            {"champion": "Ashe", "mode": "kiwi", "level": 6})
        self.assertEqual(mode, "ARAM")

    def test_canonical_aram_passes_through(self):
        # Both queue-2400 vocabularies accepted: ARAM lands identically.
        mode = self._mode_seen_by_engine(
            {"champion": "Ashe", "mode": "ARAM", "level": 6})
        self.assertEqual(mode, "ARAM")

    def test_cherry_aliases_to_arena(self):
        mode = self._mode_seen_by_engine(
            {"champion": "Ashe", "mode": "CHERRY", "level": 6})
        self.assertEqual(mode, "ARENA")

    def test_canonical_arena_passes_through(self):
        mode = self._mode_seen_by_engine(
            {"champion": "Ashe", "mode": "ARENA", "level": 6})
        self.assertEqual(mode, "ARENA")

    def test_missing_mode_defaults_sr(self):
        mode = self._mode_seen_by_engine(
            {"champion": "Ashe", "level": 6})
        self.assertEqual(mode, "SR")

    def test_unknown_mode_passes_through_tolerantly(self):
        # Unknown vocab is NOT rejected - the engine's own MODE_MAP_ID
        # miss handling (allow-all) stays the fallback for true unknowns.
        mode = self._mode_seen_by_engine(
            {"champion": "Ashe", "mode": "URFRIDER", "level": 6})
        self.assertEqual(mode, "URFRIDER")


class DsPreviewCapgapModeCanonicalTests(unittest.TestCase):
    """The capability-gap synthesizer also receives the canonical mode
    (the A1 mismatch was found on the capability-gap dispatch path)."""

    @mock.patch.dict("os.environ", {"RC_CAPGAP_SURFACE": "1"})
    def test_capgap_receives_canonical_aram_for_kiwi(self):
        cg_result = {
            "applies": True, "top_gap": "sustain", "verdict": "test",
            "my_champion": "Ashe", "mode": "ARAM",
        }
        with mock.patch(
            "core.daemon_slayer_client.rank_for_primary_archetype",
            return_value=_dispatcher_response(),
        ), mock.patch(
            "core.ds_capability_gap.build_capability_gap",
            return_value=cg_result,
        ) as mock_cg:
            h = _Handler()
            _serve_ds_preview_post(h, {
                "champion": "Ashe", "mode": "KIWI", "level": 6,
                "enemies": ["Vladimir", "Fiddlesticks", "Warwick"],
            })
        self.assertEqual(h.status, 200)
        self.assertTrue(mock_cg.called)
        # build_capability_gap(champion, enemies, mode) - positional mode.
        self.assertEqual(mock_cg.call_args.args[2], "ARAM")
        self.assertEqual(h.json().get("capability_gap"), cg_result)


if __name__ == "__main__":
    unittest.main()
