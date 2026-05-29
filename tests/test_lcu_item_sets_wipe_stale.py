"""Drift guards + offline-stub tests for the delete_stale_rc_item_sets handler.

Item 188 Slice B (2026-05-25): operator reported the in-game item-shop dropdown
accumulating 20+ stale RC- item-sets during champ-select. Root cause: each
``_csvMaybePushBuildsToLCU`` call (web/js/panels/champ_select.js) pushes up to
4 RC- sets via ``apply_item_sets_batch`` with set_uid
``RC-<champion>-<mode>-<path>``; both ``apply_item_set`` (replace-by-uid,
item 164) and ``apply_item_sets_batch`` deliberately preserve OTHER RC- sets.
Per item 178 + item 179 (SR + ARAM + Arena collapse), each champion can yield
up to 4 paths * 3 modes = 12 sets; a session cycling 2-3 picks accumulates
24-36 stale entries.

The new ``delete_stale_rc_item_sets`` handler is wired as the PRE-PUSH step in
``_csvMaybePushBuildsToLCU`` so the dropdown only carries the current scope's
sets going forward.

Wipe scope:
  - DELETE every set whose uid starts with ``RC-`` AND does NOT start with
    ``RC-<active_champion>-<active_mode>-``.
  - PRESERVE operator's own custom (non-RC-) sets ALWAYS.
  - PRESERVE current-champion-current-mode-* RC- sets (idempotent with the
    apply_item_sets_batch that fires immediately after).

Pattern mirrors ``tests/test_set_augment_intent_handler.py`` (item 188 Slice C):
both share the ``execute_command(cmd)`` module-level entry point + the
lcu_request stub fixture.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
_AGENT_PATH = _REPO / "tools" / "gamepc_lcu_agent.py"


def _load_agent_module():
    """Load ``tools/gamepc_lcu_agent.py`` as a library so unit tests can call
    ``execute_command`` directly without invoking the polling loop under
    ``if __name__ == '__main__'``.
    """
    spec = importlib.util.spec_from_file_location(
        "_gamepc_lcu_agent_under_test_wipe", _AGENT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _summoner_ok():
    return {"summonerId": 12345, "accountId": 99999}


def _make_set(uid, title=None):
    """Build a minimal LCU itemSet dict matching the shape PUT to
    /lol-item-sets/v1/item-sets/{sid}/sets."""
    return {
        "uid": uid,
        "title": title or uid,
        "type": "custom",
        "map": "any",
        "mode": "any",
        "associatedChampions": [],
        "associatedMaps": [],
        "preferredItemSlots": [],
        "blocks": [{"type": "Build", "items": [{"id": "3074", "count": 1}]}],
        "sortrank": 0,
    }


# ---------------------------------------------------------------------------
# HandlerShapeTests: cover the request-shape contract.
# ---------------------------------------------------------------------------


class HandlerShapeTests(unittest.TestCase):
    """Bad inputs short-circuit before any LCU call."""

    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()

    def test_missing_active_champion_short_circuits(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "delete_stale_rc_item_sets",
                "active_mode": "sr",
            })
        self.assertFalse(out["ok"])
        self.assertIn("active_champion", out["err"])
        mock_req.assert_not_called()

    def test_missing_active_mode_short_circuits(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "delete_stale_rc_item_sets",
                "active_champion": "Jinx",
            })
        self.assertFalse(out["ok"])
        self.assertIn("active_mode", out["err"])
        mock_req.assert_not_called()

    def test_empty_string_inputs_short_circuit(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "delete_stale_rc_item_sets",
                "active_champion": "",
                "active_mode": "",
            })
        self.assertFalse(out["ok"])
        mock_req.assert_not_called()

    def test_whitespace_inputs_short_circuit(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "delete_stale_rc_item_sets",
                "active_champion": "   ",
                "active_mode": "sr",
            })
        self.assertFalse(out["ok"])
        mock_req.assert_not_called()


# ---------------------------------------------------------------------------
# WipeScopeTests: prove what gets wiped vs preserved.
# ---------------------------------------------------------------------------


class WipeScopeTests(unittest.TestCase):
    """The handler must preserve operator's custom sets AND the current
    {champion, mode} RC- sets, while deleting all other RC- sets.
    """

    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()

    def _run_with_existing_sets(self, existing_sets, active_champion, active_mode):
        """Drive execute_command with a stubbed LCU. Returns
        (response, put_payload, last_put_body)."""
        calls = []

        def fake_lcu_request(method, path, body=None):
            calls.append((method, path, body))
            if method == "GET" and path == "/lol-summoner/v1/current-summoner":
                return (_summoner_ok(), None)
            if method == "GET" and path.startswith("/lol-item-sets/v1/item-sets/"):
                return ({"accountId": 99999, "itemSets": list(existing_sets)}, None)
            if method == "PUT" and path.startswith("/lol-item-sets/v1/item-sets/"):
                return (None, None)
            return (None, "unmocked")

        with patch.object(self.agent, "lcu_request", side_effect=fake_lcu_request):
            resp = self.agent.execute_command({
                "cmd": "delete_stale_rc_item_sets",
                "active_champion": active_champion,
                "active_mode": active_mode,
            })
        return resp, calls

    def test_preserves_operator_custom_sets(self):
        """Sets without RC- prefix MUST always survive (operator's own
        builds in the in-game shop dropdown)."""
        existing = [
            _make_set("My-Jinx-On-Hit-Crit-Lifesteal"),
            _make_set("Personal-Aatrox-Bruiser"),
            _make_set("RC-Aatrox-sr-bruiser"),  # stale RC entry (different champ)
        ]
        resp, calls = self._run_with_existing_sets(existing, "Jinx", "sr")
        self.assertTrue(resp["ok"])
        # PUT body should carry both operator custom sets.
        put_calls = [c for c in calls if c[0] == "PUT"]
        self.assertEqual(len(put_calls), 1)
        put_body = put_calls[0][2]
        kept_uids = {s.get("uid") for s in put_body["itemSets"]}
        self.assertIn("My-Jinx-On-Hit-Crit-Lifesteal", kept_uids)
        self.assertIn("Personal-Aatrox-Bruiser", kept_uids)
        # The Aatrox RC- entry must be wiped (different champ).
        self.assertNotIn("RC-Aatrox-sr-bruiser", kept_uids)

    def test_only_current_scope_rc_sets_survive(self):
        """RC- sets matching `RC-<active>-<mode>-*` keep; everything else
        in the RC- namespace wipes."""
        existing = [
            # Current scope -> keep these
            _make_set("RC-Jinx-sr-carry"),
            _make_set("RC-Jinx-sr-on-hit"),
            _make_set("RC-Jinx-sr-lethality"),
            _make_set("RC-Jinx-sr-bruiser"),
            # Same champ, different mode -> wipe
            _make_set("RC-Jinx-aram-carry"),
            _make_set("RC-Jinx-arena-crit-primary"),
            # Different champ entirely -> wipe
            _make_set("RC-Aatrox-sr-bruiser"),
            _make_set("RC-Caitlyn-aram-lethality"),
            # Operator's own -> always keep
            _make_set("MyCustomBuild"),
        ]
        resp, calls = self._run_with_existing_sets(existing, "Jinx", "sr")
        self.assertTrue(resp["ok"])
        put_body = [c for c in calls if c[0] == "PUT"][0][2]
        kept_uids = {s.get("uid") for s in put_body["itemSets"]}
        # 4 current-scope RC- + 1 operator custom = 5 kept
        self.assertEqual(kept_uids, {
            "RC-Jinx-sr-carry",
            "RC-Jinx-sr-on-hit",
            "RC-Jinx-sr-lethality",
            "RC-Jinx-sr-bruiser",
            "MyCustomBuild",
        })
        self.assertEqual(resp["wiped_count"], 4)
        self.assertEqual(set(resp["wiped_uids"]), {
            "RC-Jinx-aram-carry",
            "RC-Jinx-arena-crit-primary",
            "RC-Aatrox-sr-bruiser",
            "RC-Caitlyn-aram-lethality",
        })

    def test_active_scope_with_only_other_champs_wipes_all_rc(self):
        """If active champion has no current RC- sets and others do, those
        others all wipe (the wipe handler doesn't gate on 'has current scope
        anything' - it gates on the active scope filter)."""
        existing = [
            _make_set("RC-Aatrox-sr-bruiser"),
            _make_set("RC-Caitlyn-aram-lethality"),
            _make_set("MyCustomBuild"),
        ]
        resp, calls = self._run_with_existing_sets(existing, "Jinx", "sr")
        self.assertTrue(resp["ok"])
        put_body = [c for c in calls if c[0] == "PUT"][0][2]
        kept_uids = {s.get("uid") for s in put_body["itemSets"]}
        self.assertEqual(kept_uids, {"MyCustomBuild"})
        self.assertEqual(resp["wiped_count"], 2)

    def test_no_rc_sets_short_circuits_put(self):
        """If there's nothing to wipe, the handler MUST NOT issue a PUT
        (saves a round-trip + avoids spurious LCU writes)."""
        existing = [
            _make_set("MyCustomBuild"),
            _make_set("Another-Custom"),
        ]
        resp, calls = self._run_with_existing_sets(existing, "Jinx", "sr")
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["wiped_count"], 0)
        self.assertEqual(resp["wiped_uids"], [])
        self.assertEqual(resp["kept_count"], 2)
        put_calls = [c for c in calls if c[0] == "PUT"]
        self.assertEqual(len(put_calls), 0, "should short-circuit PUT")

    def test_prefix_match_is_anchored_not_substring(self):
        """A set like `RC-JinxJunior-sr-*` MUST be wiped when active is
        `Jinx` (the prefix must be `RC-Jinx-sr-`, not `RC-Jinx`). Guards
        against substring false-keeps on similarly-named champions."""
        existing = [
            _make_set("RC-Jinx-sr-carry"),       # current scope: keep
            _make_set("RC-JinxJunior-sr-carry"), # different champ: wipe
        ]
        resp, calls = self._run_with_existing_sets(existing, "Jinx", "sr")
        self.assertTrue(resp["ok"])
        put_body = [c for c in calls if c[0] == "PUT"][0][2]
        kept_uids = {s.get("uid") for s in put_body["itemSets"]}
        self.assertEqual(kept_uids, {"RC-Jinx-sr-carry"})

    def test_mode_prefix_is_anchored_not_substring(self):
        """`RC-Jinx-sr-*` must NOT match `RC-Jinx-srtest-*` if a future
        mode key were to share a prefix with `sr`. Belt-and-suspenders for
        the same anchor logic."""
        existing = [
            _make_set("RC-Jinx-sr-carry"),
            _make_set("RC-Jinx-srtest-carry"),  # not the active mode
        ]
        resp, calls = self._run_with_existing_sets(existing, "Jinx", "sr")
        self.assertTrue(resp["ok"])
        put_body = [c for c in calls if c[0] == "PUT"][0][2]
        kept_uids = {s.get("uid") for s in put_body["itemSets"]}
        # RC-Jinx-sr-carry kept; RC-Jinx-srtest-carry wiped because the
        # required prefix is `RC-Jinx-sr-` (trailing hyphen anchors).
        self.assertEqual(kept_uids, {"RC-Jinx-sr-carry"})


# ---------------------------------------------------------------------------
# AllowlistDriftGuardTests: assert the dashboard edge surfaces the cmd.
# ---------------------------------------------------------------------------


class AllowlistDriftGuardTests(unittest.TestCase):
    """The /api/lcu-cmd allowlist in dashboard/routes_loadout.py MUST
    include ``delete_stale_rc_item_sets`` or the dashboard edge rejects
    the wipe call with 400 before it reaches the vision server."""

    def test_handler_is_in_allowlist(self):
        from dashboard.routes_loadout import _LCU_ALLOWED_CMDS
        self.assertIn("delete_stale_rc_item_sets", _LCU_ALLOWED_CMDS)


# ---------------------------------------------------------------------------
# JsWireDriftGuardTests: assert the JS push site fires the wipe PRE-PUSH.
# ---------------------------------------------------------------------------


class JsWireDriftGuardTests(unittest.TestCase):
    """If the wire-in disappears from ``_csvMaybePushBuildsToLCU`` the live
    push regrows the 20+ stale-set accumulation; this drift guard catches
    that before it lands."""

    def test_pre_push_wipe_call_is_present(self):
        js_path = _REPO / "web" / "js" / "panels" / "champ_select.js"
        src = js_path.read_text(encoding="utf-8")
        # Item 213: a second apply_item_sets_batch site exists (the
        # DS-vs-enemy-comp save+push button, a single distinct-uid set whose
        # cross-champ stale accumulation is handled by this same render-time
        # wipe). Scope the ordering assertion to the _csvMaybePushBuildsToLCU
        # body so the global first-occurrence find does not latch the other
        # push site.
        fn_idx = src.find("function _csvMaybePushBuildsToLCU")
        self.assertGreater(fn_idx, 0,
            "_csvMaybePushBuildsToLCU function missing from champ_select.js")
        body = src[fn_idx:]
        wipe_idx = body.find('cmd: "delete_stale_rc_item_sets"')
        batch_idx = body.find('cmd: "apply_item_sets_batch"')
        self.assertGreater(wipe_idx, 0,
            "delete_stale_rc_item_sets call missing from _csvMaybePushBuildsToLCU")
        self.assertGreater(batch_idx, wipe_idx,
            "wipe must precede apply_item_sets_batch in _csvMaybePushBuildsToLCU")

    def test_wipe_carries_active_champion_and_mode(self):
        js_path = _REPO / "web" / "js" / "panels" / "champ_select.js"
        src = js_path.read_text(encoding="utf-8")
        self.assertIn("active_champion: champion", src)
        self.assertIn('active_mode: mode || "sr"', src)


# ---------------------------------------------------------------------------
# AsciiHygieneTests: per CLAUDE.md no-em-dash + no-smart-quote rule.
# ---------------------------------------------------------------------------


class AsciiHygieneTests(unittest.TestCase):
    def test_new_test_file_is_ascii(self):
        src = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b >= 0x80]
        self.assertEqual(bad, [],
            f"non-ASCII bytes at offsets: {bad[:8]}")


if __name__ == "__main__":
    unittest.main()
