"""RC2 RM-03 E12 lever L3 - flag-ON parity for state.lcu.config + lcu_port.

G1-00 CHECK 2 measured live (2026-07-20, Practice Tool champ-select, queue
3140 / BAN_PICK): ``state.lcu.champ_select`` is byte-identical flag-ON vs
flag-OFF, but the flag-ON envelope OMITS ``config`` and ``lcu_port``. The
missing ``config`` breaks ``web/js/main.js`` ``_syncAutoAcceptFromConfig``
(main.js:5661-5672), which drives BOTH the lobby auto-accept pill and the
Settings checkbox ``#set-lobby-auto-accept`` off ``lcu.config.auto_accept``.

``lcu/snapshot_shape.shape_snapshot`` deliberately does not emit either key
(snapshot_shape.py:337-340 - they are caller/transport owned), so the fix
belongs in the CALLER. This suite pins it:

  * ``config`` is the AGENT's live CONFIG as observed off the relay
    snapshot, NOT a synthesized constant. The agent's CONFIG
    (tools/lcu_agent.py:120-125) lives only in the agent's process memory -
    it is never persisted - so the relay-posted copy is the only reachable
    source of the real value. The agent boot defaults are a LAST-RESORT
    fallback and are drift-guarded against the agent module here.
  * the relay read is TTL-throttled, so the flag-ON path stays strictly
    cheaper than the flag-OFF path (which calls ``lcu_summary()`` on EVERY
    build).
  * ``lcu_port`` is the lockfile-derived port off the dashboard-owned
    ``LcuClient``, emitted as a STRING to match the agent
    (tools/lcu_agent.py:298 stores ``read_lockfile()`` field 2 verbatim,
    never int-cast).
  * key order matches ``tools/lcu_agent.capture_state()``: config,
    lcu_port, then the shape_snapshot keys.

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import dashboard._lcu_inprocess as inp  # noqa: E402
from lcu.snapshot_shape import _reset_mastery_cache_for_tests  # noqa: E402

_PHASE_PATH = "/lol-gameflow/v1/gameflow-phase"
_SESSION_PATH = "/lol-champ-select/v1/session"

# The value MEASURED live at G1-00 CHECK 2 off the relay envelope. The
# operator's "Auto Accept ready-check by default" checkbox is genuinely
# UNCHECKED, so auto_accept is False - it is NOT always-on.
_LIVE_CONFIG = {
    "auto_accept": False,
    "summoner_override": False,
    "summoner_d": 4,
    "summoner_f": 32,
}
# A config the operator has since toggled ON - proves the reader tracks the
# agent's live value rather than re-emitting the boot defaults.
_TOGGLED_CONFIG = {
    "auto_accept": True,
    "summoner_override": True,
    "summoner_d": 4,
    "summoner_f": 14,
}


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
        return self._routes.get(endpoint)


def _champ_select_client(port=61234):
    session = {
        "localPlayerCellId": 0,
        "benchChampions": [{"championId": 21}],
        "timer": {"phase": "BAN_PICK"},
        "gameData": {"queue": {"id": 3140, "gameMode": "PRACTICETOOL"}},
        "myTeam": [{"cellId": 0, "championId": 43, "summonerId": 55,
                    "puuid": "p", "spell1Id": 4, "spell2Id": 32}],
        "theirTeam": [], "trades": [],
        "positionSwaps": [], "pickOrderSwaps": [], "actions": [],
    }
    return _StubClient(port=port, routes={
        _PHASE_PATH: "ChampSelect",
        _SESSION_PATH: session,
    })


class _ConfigParityBase(unittest.TestCase):
    def setUp(self):
        inp._reset_client_for_tests()
        _reset_mastery_cache_for_tests()

    def tearDown(self):
        inp._reset_client_for_tests()
        _reset_mastery_cache_for_tests()

    def _build(self, client, relay):
        """Run the reader with a stubbed client + stubbed relay read."""
        with mock.patch.object(inp, "_get_client", return_value=client), \
                mock.patch.object(inp, "_read_relay_snapshot", **relay) as spy:
            return inp.lcu_summary_inprocess(), spy


class TestConfigIsAgentTruth(_ConfigParityBase):
    def test_config_present_and_is_relay_observed_value(self):
        snap, _ = self._build(
            _champ_select_client(),
            {"return_value": {"config": dict(_TOGGLED_CONFIG)}})
        self.assertIsNotNone(snap)
        self.assertEqual(snap["config"], _TOGGLED_CONFIG)

    def test_config_tracks_a_later_agent_toggle(self):
        """A second observation must overwrite the first (not stick)."""
        client = _champ_select_client()
        snap, _ = self._build(client, {"return_value": {"config": dict(_LIVE_CONFIG)}})
        self.assertEqual(snap["config"], _LIVE_CONFIG)
        inp._expire_config_cache_for_tests()
        snap2, _ = self._build(client, {"return_value": {"config": dict(_TOGGLED_CONFIG)}})
        self.assertEqual(snap2["config"], _TOGGLED_CONFIG)

    def test_config_holds_last_observed_when_relay_goes_silent(self):
        client = _champ_select_client()
        snap, _ = self._build(client, {"return_value": {"config": dict(_TOGGLED_CONFIG)}})
        self.assertEqual(snap["config"], _TOGGLED_CONFIG)
        inp._expire_config_cache_for_tests()
        # Relay stale / down -> lcu_summary() contract is {}.
        snap2, _ = self._build(client, {"return_value": {}})
        self.assertEqual(snap2["config"], _TOGGLED_CONFIG)

    def test_config_falls_back_to_agent_boot_defaults_when_never_observed(self):
        snap, _ = self._build(_champ_select_client(), {"return_value": {}})
        self.assertEqual(snap["config"], inp._AGENT_CONFIG_DEFAULTS)
        self.assertEqual(snap["config"], _LIVE_CONFIG)

    def test_config_survives_a_raising_relay_read(self):
        snap, _ = self._build(_champ_select_client(),
                              {"side_effect": RuntimeError("relay down")})
        self.assertIsNotNone(snap, "a relay hiccup must not kill the snapshot")
        self.assertEqual(snap["config"], inp._AGENT_CONFIG_DEFAULTS)

    def test_config_ignores_a_non_dict_relay_config(self):
        snap, _ = self._build(_champ_select_client(),
                              {"return_value": {"config": "nope"}})
        self.assertEqual(snap["config"], inp._AGENT_CONFIG_DEFAULTS)

    def test_relay_read_is_ttl_throttled(self):
        """Flag-ON must stay cheaper than flag-OFF: at most ONE relay read
        across back-to-back builds inside the TTL window."""
        client = _champ_select_client()
        with mock.patch.object(inp, "_get_client", return_value=client), \
                mock.patch.object(
                    inp, "_read_relay_snapshot",
                    return_value={"config": dict(_LIVE_CONFIG)}) as spy:
            inp.lcu_summary_inprocess()
            inp.lcu_summary_inprocess()
            inp.lcu_summary_inprocess()
        self.assertEqual(spy.call_count, 1)

    def test_agent_boot_defaults_do_not_drift_from_the_agent(self):
        """Drift guard on the last-resort mirror of tools/lcu_agent.CONFIG."""
        import lcu_agent as agent
        self.assertEqual(inp._AGENT_CONFIG_DEFAULTS, agent.CONFIG)


class TestLcuPortParity(_ConfigParityBase):
    def test_lcu_port_present_as_string(self):
        snap, _ = self._build(_champ_select_client(port=61234),
                              {"return_value": {"config": dict(_LIVE_CONFIG)}})
        self.assertEqual(snap["lcu_port"], "61234")

    def test_key_order_matches_agent_capture_state(self):
        snap, _ = self._build(_champ_select_client(),
                              {"return_value": {"config": dict(_LIVE_CONFIG)}})
        self.assertEqual(list(snap)[:2], ["config", "lcu_port"])

    def test_champ_select_still_shaped(self):
        """The two new keys must not disturb the byte-identical half."""
        snap, _ = self._build(_champ_select_client(),
                              {"return_value": {"config": dict(_LIVE_CONFIG)}})
        self.assertEqual(snap["phase"], "ChampSelect")
        self.assertIn("champ_select", snap)
        self.assertIn("ts", snap)


if __name__ == "__main__":
    unittest.main()
