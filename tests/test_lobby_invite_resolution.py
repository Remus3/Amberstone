"""Regression: Top 8 / friends-list lobby invites silently failed.

LOBBY1 (2026-06-08). Operator report: "Invite from my top 8 does not
work". Root cause: ``lobby.invite_player`` resolved a Riot ID
("Name#TAG") to an LCU ``summonerId`` *exclusively* via
``/lol-summoner/v1/summoners/by-name/<name>``. Riot removed that
endpoint in the Riot ID migration - it 404s on current clients - so the
lookup returned None, ``sid`` stayed unset, and every Top 8 / friends
invite returned ``{"ok": False, "err": "could not resolve summoner: ..."}``.
The Top 8 add-flow never captures a summonerId/puuid (only Name#TAG), so
the dead by-name path was the *only* resolution route -> 100% failure.

Fix (``tools/gamepc_lcu_agent.py``): resolve via a layered chain, most
reliable first - explicit summonerId, then puuid ->
``/lol-summoner/v1/summoners-by-puuid-cached/{puuid}``, then a scan of
``/lol-chat/v1/friends`` (the invite targets ARE friends, and that
resource carries gameName/gameTag/summonerId on current builds), then the
legacy by-name path last for ancient clients.

These tests stub ``lcu_request`` so they run offline. The live end-to-end
invite is gated on a real lobby (``RC_LIVE_LOBBY=1``).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
_AGENT_PATH = _REPO / "tools" / "gamepc_lcu_agent.py"

_BY_NAME = "/lol-summoner/v1/summoners/by-name/"
_FRIENDS = "/lol-chat/v1/friends"
_PUUID_CACHED = "/lol-summoner/v1/summoners-by-puuid-cached/"
_INVITATIONS = "/lol-lobby/v2/lobby/invitations"


def _load_agent_module():
    """Import ``tools/gamepc_lcu_agent.py`` as a library (skip the boot
    loop under ``__main__``) so we can call ``execute_command`` directly.
    Mirrors tests/test_set_augment_intent_handler.py."""
    spec = importlib.util.spec_from_file_location(
        "_gamepc_lcu_agent_invite_under_test", _AGENT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Recorder:
    """Records (method, path, body) and replays scripted responses keyed
    by an exact path or a path prefix."""

    def __init__(self, exact=None, prefix=None, default=(None, "unexpected")):
        self.exact = exact or {}
        self.prefix = prefix or []
        self.default = default
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path in self.exact:
            return self.exact[path]
        for pre, resp in self.prefix:
            if path.startswith(pre):
                return resp
        return self.default

    def gets(self):
        return [c for c in self.calls if c[0] == "GET"]

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


class ResolutionOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()

    def test_explicit_summoner_id_short_circuits_no_resolution_get(self):
        rec = _Recorder(exact={_INVITATIONS: ({}, None)})
        with patch.object(self.agent, "lcu_request", side_effect=rec):
            out = self.agent.execute_command({
                "cmd": "lobby.invite_player",
                "riot_id": "Someone#NA1", "summoner_id": 999,
            })
        self.assertTrue(out["ok"])
        self.assertEqual(out["summoner_id"], 999)
        self.assertEqual(out["resolved_via"], "summoner_id")
        # No resolution lookups when the id is already known.
        self.assertEqual(rec.gets(), [])
        self.assertEqual(
            rec.posts(), [("POST", _INVITATIONS, [{"toSummonerId": 999}])])

    def test_puuid_resolves_via_cached_endpoint(self):
        rec = _Recorder(
            exact={
                _PUUID_CACHED + "PU-123": ({"summonerId": 555}, None),
                _INVITATIONS: ({}, None),
            },
        )
        with patch.object(self.agent, "lcu_request", side_effect=rec):
            out = self.agent.execute_command({
                "cmd": "lobby.invite_player",
                "riot_id": "Someone#NA1", "puuid": "PU-123",
            })
        self.assertTrue(out["ok"])
        self.assertEqual(out["summoner_id"], 555)
        self.assertEqual(out["resolved_via"], "puuid")
        # puuid wins before friends-scan / by-name are ever tried.
        self.assertFalse(
            any(_FRIENDS in c[1] or _BY_NAME in c[1] for c in rec.calls))
        self.assertEqual(
            rec.posts(), [("POST", _INVITATIONS, [{"toSummonerId": 555}])])

    def test_riot_id_resolves_via_friends_scan_when_by_name_dead(self):
        """The core regression: by-name 404s, friends-scan resolves."""
        friends = [
            {"gameName": "Ally", "gameTag": "NA1", "summonerId": 4242,
             "name": "Ally", "puuid": "p-ally"},
            {"gameName": "SamplePlayer", "gameTag": "Trist", "summonerId": 777,
             "name": "SamplePlayer", "puuid": "p-moon"},
        ]
        rec = _Recorder(
            exact={_FRIENDS: (friends, None), _INVITATIONS: ({}, None)},
            prefix=[(_BY_NAME, (None, "http 404"))],
        )
        with patch.object(self.agent, "lcu_request", side_effect=rec):
            out = self.agent.execute_command({
                "cmd": "lobby.invite_player", "riot_id": "SamplePlayer#Trist",
            })
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["summoner_id"], 777)
        self.assertEqual(out["resolved_via"], "friends")
        self.assertEqual(
            rec.posts(), [("POST", _INVITATIONS, [{"toSummonerId": 777}])])
        # Friends resolved first; the dead by-name path is never reached.
        self.assertFalse(any(c[1].startswith(_BY_NAME) for c in rec.calls))

    def test_friends_scan_matches_legacy_name_without_tag(self):
        friends = [
            {"gameName": "", "gameTag": "", "summonerId": 8080,
             "name": "OldSchool"},
        ]
        rec = _Recorder(
            exact={_FRIENDS: (friends, None), _INVITATIONS: ({}, None)},
            prefix=[(_BY_NAME, (None, "http 404"))],
        )
        with patch.object(self.agent, "lcu_request", side_effect=rec):
            out = self.agent.execute_command({
                "cmd": "lobby.invite_player", "riot_id": "OldSchool",
            })
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["summoner_id"], 8080)
        self.assertEqual(out["resolved_via"], "friends")

    def test_falls_back_to_by_name_when_not_a_friend(self):
        rec = _Recorder(
            exact={
                _FRIENDS: ([], None),
                _BY_NAME + "Stranger-NA1": ({"summonerId": 222}, None),
                _INVITATIONS: ({}, None),
            },
        )
        with patch.object(self.agent, "lcu_request", side_effect=rec):
            out = self.agent.execute_command({
                "cmd": "lobby.invite_player", "riot_id": "Stranger#NA1",
            })
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["summoner_id"], 222)
        self.assertEqual(out["resolved_via"], "by_name")

    def test_unresolvable_returns_error_and_posts_no_invitation(self):
        rec = _Recorder(
            exact={_FRIENDS: ([], None)},
            prefix=[(_BY_NAME, (None, "http 404"))],
        )
        with patch.object(self.agent, "lcu_request", side_effect=rec):
            out = self.agent.execute_command({
                "cmd": "lobby.invite_player", "riot_id": "Ghost#NA1",
            })
        self.assertFalse(out["ok"])
        self.assertIn("could not resolve", out["err"])
        self.assertEqual(rec.posts(), [])

    def test_missing_all_identifiers_returns_error_no_lcu_call(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({"cmd": "lobby.invite_player"})
        self.assertFalse(out["ok"])
        self.assertIn("required", out["err"])
        mock_req.assert_not_called()

    def test_invitation_body_is_array_of_to_summoner_id(self):
        rec = _Recorder(exact={_INVITATIONS: ({}, None)})
        with patch.object(self.agent, "lcu_request", side_effect=rec):
            self.agent.execute_command({
                "cmd": "lobby.invite_player", "summoner_id": 42,
            })
        method, path, body = rec.posts()[0]
        self.assertEqual((method, path), ("POST", _INVITATIONS))
        self.assertEqual(body, [{"toSummonerId": 42}])


class AllowlistGuardTests(unittest.TestCase):
    """The command must stay in the dashboard edge allowlist or the
    POST /api/lcu-cmd -> Game-PC agent dispatch chain rejects it."""

    def test_lobby_invite_player_in_dashboard_allowlist(self):
        from dashboard.routes_loadout import _LCU_ALLOWED_CMDS
        self.assertIn("lobby.invite_player", _LCU_ALLOWED_CMDS)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii_clean(self):
        data = Path(__file__).resolve().read_bytes()
        bad = [i for i, b in enumerate(data) if b > 127]
        self.assertEqual(bad, [], f"non-ASCII bytes at offsets {bad[:8]}")


@unittest.skipUnless(
    os.environ.get("RC_LIVE_LOBBY"),
    "needs a live League lobby; set RC_LIVE_LOBBY=1 to run",
)
class LiveInviteIntegrationTests(unittest.TestCase):
    """End-to-end against a real lobby. The operator must have a lobby open
    and a friend (Riot ID in RC_LIVE_INVITE_RID) online to receive it."""

    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()
        if hasattr(cls.agent, "ensure_lcu_conn"):
            cls.agent.ensure_lcu_conn()

    def test_live_invite_resolves_and_posts(self):
        rid = os.environ.get("RC_LIVE_INVITE_RID", "")
        out = self.agent.execute_command({
            "cmd": "lobby.invite_player", "riot_id": rid,
        })
        print(f"\nLIVE lobby.invite_player verdict: {out}")
        self.assertIn("ok", out)


if __name__ == "__main__":
    unittest.main()
