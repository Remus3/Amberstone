"""RC2 RM-03 E12 lever L3 - dashboard in-process LCU reader + DEFAULT-OFF flag.

Two guards:

  * ``dashboard/_state_builder._read_lcu_snapshot`` must use the relay
    ``lcu_summary()`` when ``RC_LCU_INPROCESS`` is unset (the live path is
    byte-identical to today), use the in-process reader only when the flag is
    "1" AND it returns a non-None snapshot, and fall back to the relay when the
    in-process reader returns None.

  * ``dashboard/_lcu_inprocess.lcu_summary_inprocess`` returns None (never
    raises) when the dashboard-owned client is not connected or anything
    throws, and builds the snapshot via shape_snapshot when it IS connected.

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import dashboard._lcu_inprocess as inp  # noqa: E402
import dashboard._state_builder as sb  # noqa: E402
from lcu.snapshot_shape import _reset_mastery_cache_for_tests  # noqa: E402

_PHASE_PATH = "/lol-gameflow/v1/gameflow-phase"
_SESSION_PATH = "/lol-champ-select/v1/session"


class _StubClient:
    """Stand-in LcuClient exposing only what the reader touches."""

    def __init__(self, port, routes=None):
        self._port = port
        self._routes = routes or {}

    def connect(self):
        return bool(self._port)

    def _refresh_conn_if_changed(self):
        pass

    def _request(self, method, endpoint, data=None, _retry=True):
        # LcuClient._request returns payload | None (NOT a tuple).
        return self._routes.get(endpoint)


class TestReadLcuSnapshotFlag(unittest.TestCase):
    """The flag gate in build_state's snapshot source."""

    def _run(self, env, *, relay, inprocess):
        patch_env = mock.patch.dict(os.environ, {}, clear=False)
        with patch_env:
            os.environ.pop("RC_LCU_INPROCESS", None)
            if env is not None:
                os.environ["RC_LCU_INPROCESS"] = env
            with mock.patch.object(sb, "lcu_summary", **relay), \
                    mock.patch.object(inp, "lcu_summary_inprocess", **inprocess):
                return sb._read_lcu_snapshot()

    def test_flag_unset_uses_relay(self):
        out = self._run(
            None,
            relay={"return_value": {"src": "relay"}},
            inprocess={"side_effect": AssertionError(
                "in-process reader must not run when the flag is off")},
        )
        self.assertEqual(out, {"src": "relay"})

    def test_flag_zero_uses_relay(self):
        out = self._run(
            "0",
            relay={"return_value": {"src": "relay"}},
            inprocess={"side_effect": AssertionError(
                "in-process reader must not run when the flag is not '1'")},
        )
        self.assertEqual(out, {"src": "relay"})

    def test_flag_on_uses_inprocess_when_nonnull(self):
        out = self._run(
            "1",
            relay={"side_effect": AssertionError(
                "relay must not run when the in-process reader returns data")},
            inprocess={"return_value": {"src": "inprocess"}},
        )
        self.assertEqual(out, {"src": "inprocess"})

    def test_flag_on_falls_back_to_relay_when_inprocess_none(self):
        out = self._run(
            "1",
            relay={"return_value": {"src": "relay"}},
            inprocess={"return_value": None},
        )
        self.assertEqual(out, {"src": "relay"})


class TestLcuSummaryInprocess(unittest.TestCase):
    def setUp(self):
        inp._reset_client_for_tests()
        _reset_mastery_cache_for_tests()

    def tearDown(self):
        inp._reset_client_for_tests()
        _reset_mastery_cache_for_tests()

    def test_returns_none_when_client_unconnected(self):
        # _port None -> not connected -> None (no crash, caller falls back).
        with mock.patch.object(inp, "_get_client",
                               return_value=_StubClient(port=None)):
            self.assertIsNone(inp.lcu_summary_inprocess())

    def test_returns_none_on_exception(self):
        with mock.patch.object(inp, "_get_client",
                               side_effect=RuntimeError("boom")):
            self.assertIsNone(inp.lcu_summary_inprocess())

    def test_connected_builds_snapshot_via_shape(self):
        session = {
            "localPlayerCellId": 0,
            "benchChampions": [{"championId": 21}],
            "timer": {"phase": "GAME_STARTING"},
            "gameData": {"queue": {"id": 2400, "gameMode": "KIWI"}},
            "myTeam": [{"cellId": 0, "championId": 43, "summonerId": 55,
                        "puuid": "p", "spell1Id": 4, "spell2Id": 32}],
            "theirTeam": [], "trades": [],
            "positionSwaps": [], "pickOrderSwaps": [], "actions": [],
        }
        client = _StubClient(port=1234, routes={
            _PHASE_PATH: "ChampSelect",
            _SESSION_PATH: session,
        })
        with mock.patch.object(inp, "_get_client", return_value=client):
            snap = inp.lcu_summary_inprocess()
        self.assertIsNotNone(snap)
        self.assertEqual(snap["phase"], "ChampSelect")
        self.assertIn("champ_select", snap)
        self.assertTrue(snap["champ_select"]["is_aram"])
        # config is caller-owned - shape_snapshot must not emit it (the
        # ACCEPTED, documented flag-ON divergence vs the relay payload).
        self.assertNotIn("config", snap)


if __name__ == "__main__":
    unittest.main()
