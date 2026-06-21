"""Drift guards + offline-stub tests for the Cherry set_augment_intent handler.

Item 188 Slice C: replaces item 187 Slice E's no-op stub with a real PATCH
chain at ``tools/lcu_agent.py:1179``. The endpoint chain is research-
grade (Cherry's REST surface is undocumented) so this suite covers the
request-shape contract + the slot-range guard + the error-envelope shape +
the 4-endpoint fallback priority order. Any live-LCU test is gated on
``RC_LIVE_ARENA`` env var since it needs an actual Arena 1750 augment-phase
session to reach the LCU endpoint (see ``docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md``
for the recipe).

Pattern mirrors ``tests/test_set_summoner_spell_handler.py`` if/when that file
lands; both share the ``execute_command(cmd)`` module-level entry point and
the lcu_request stub fixture.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
_AGENT_PATH = _REPO / "tools" / "lcu_agent.py"


def _load_agent_module():
    """Load ``tools/lcu_agent.py`` as a module without invoking the
    boot sequence under ``if __name__ == '__main__'`` (it ends with a long
    polling loop). We import-as-library so the unit tests can call
    ``execute_command`` directly.
    """
    spec = importlib.util.spec_from_file_location(
        "_lcu_agent_under_test", _AGENT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class HandlerShapeTests(unittest.TestCase):
    """Cover the request shape contract: bad inputs short-circuit before
    any LCU call; good inputs build the right body payload.
    """

    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()

    def test_missing_augment_id_returns_no_augment_id(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({"cmd": "set_augment_intent"})
        self.assertEqual(out, {"ok": False, "err": "no augment_id"})
        mock_req.assert_not_called()

    def test_zero_augment_id_returns_no_augment_id(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 0,
            })
        self.assertEqual(out, {"ok": False, "err": "no augment_id"})
        mock_req.assert_not_called()

    def test_negative_augment_id_returns_no_augment_id(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": -7,
            })
        self.assertEqual(out, {"ok": False, "err": "no augment_id"})
        mock_req.assert_not_called()


class SlotRangeGuardTests(unittest.TestCase):
    """Arena has 4 augment slots per game (rounds 1-4 = silver/gold/prismatic).
    Guard ensures slot in 0..3 inclusive; out-of-range returns a fast error
    envelope before any LCU call.
    """

    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()

    def test_slot_default_zero_is_accepted(self):
        with patch.object(self.agent, "lcu_request", return_value=({}, None)):
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 1234,
            })
        self.assertTrue(out["ok"])
        self.assertEqual(out["slot"], 0)

    def test_slot_3_is_accepted(self):
        with patch.object(self.agent, "lcu_request", return_value=({}, None)):
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 1234, "slot": 3,
            })
        self.assertTrue(out["ok"])
        self.assertEqual(out["slot"], 3)

    def test_slot_4_is_rejected(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 1234, "slot": 4,
            })
        self.assertFalse(out["ok"])
        self.assertIn("bad slot 4", out["err"])
        mock_req.assert_not_called()

    def test_slot_negative_is_rejected(self):
        with patch.object(self.agent, "lcu_request") as mock_req:
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 1234, "slot": -1,
            })
        self.assertFalse(out["ok"])
        self.assertIn("bad slot -1", out["err"])
        mock_req.assert_not_called()


class FallbackChainPriorityTests(unittest.TestCase):
    """The 4-endpoint chain must be tried in priority order; first 2xx wins;
    all-fail returns the per-attempt error list so a live operator can see
    which surface the LCU actually exposes this patch.
    """

    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()

    def test_first_endpoint_2xx_wins_no_fallback_attempted(self):
        calls = []

        def _fake(method, path, body=None):
            calls.append((method, path))
            return ({"applied": True}, None)

        with patch.object(self.agent, "lcu_request", side_effect=_fake):
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 1234, "slot": 0,
            })
        self.assertTrue(out["ok"])
        self.assertEqual(len(calls), 1)
        method, path = calls[0]
        self.assertEqual(method, "PATCH")
        self.assertEqual(path, "/lol-cherry-game-intra-event/v1/augment-select")
        self.assertEqual(out["endpoint"], f"{method} {path}")

    def test_first_two_fail_third_succeeds(self):
        calls = []
        responses = [
            (None, "http 404"),
            (None, "http 404"),
            ({"applied": True}, None),
            ({"never": "reached"}, None),
        ]

        def _fake(method, path, body=None):
            calls.append((method, path))
            return responses[len(calls) - 1]

        with patch.object(self.agent, "lcu_request", side_effect=_fake):
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 1234, "slot": 1,
            })
        self.assertTrue(out["ok"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2][1], "/lol-cherry-summoner/v1/augments")

    def test_all_four_fail_returns_envelope_with_each_attempt(self):
        calls = []

        def _fake(method, path, body=None):
            calls.append((method, path))
            return (None, "http 404")

        with patch.object(self.agent, "lcu_request", side_effect=_fake):
            out = self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 1234, "slot": 2,
            })
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "augment_intent_all_endpoints_failed")
        self.assertEqual(out["augment_id"], 1234)
        self.assertEqual(out["slot"], 2)
        self.assertEqual(len(out["tried"]), 4)
        for line in out["tried"]:
            self.assertIn("http 404", line)
        # Priority order pin: each "tried" entry begins with the corresponding
        # METHOD + PATH from the canonical chain. Re-ordering the chain in
        # the handler MUST update this test pin too.
        self.assertTrue(out["tried"][0].startswith(
            "PATCH /lol-cherry-game-intra-event/v1/augment-select"))
        self.assertTrue(out["tried"][1].startswith(
            "PATCH /lol-cherry/v1/augment-select"))
        self.assertTrue(out["tried"][2].startswith(
            "PATCH /lol-cherry-summoner/v1/augments"))
        self.assertTrue(out["tried"][3].startswith(
            "POST /lol-cherry-game-intra-event/v1/augment-select"))

    def test_body_payload_shape_includes_augmentId_and_slotIndex(self):
        captured = {}

        def _fake(method, path, body=None):
            captured["body"] = body
            return ({}, None)

        with patch.object(self.agent, "lcu_request", side_effect=_fake):
            self.agent.execute_command({
                "cmd": "set_augment_intent", "augment_id": 5678, "slot": 2,
            })
        self.assertEqual(captured["body"], {"augmentId": 5678, "slotIndex": 2})


class AllowlistGuardTests(unittest.TestCase):
    """Item 164 baseline: ``set_augment_intent`` MUST stay in the dashboard
    ``_LCU_ALLOWED_CMDS`` allowlist so the POST /api/lcu-cmd -> :8889 vision
    -> LCU agent dispatch chain accepts the command. This test pins the
    surface; if a future refactor drops it, this fails BEFORE any live
    operator click silently routes to nowhere.
    """

    def test_set_augment_intent_in_dashboard_allowlist(self):
        from dashboard.routes_loadout import _LCU_ALLOWED_CMDS
        self.assertIn("set_augment_intent", _LCU_ALLOWED_CMDS)


class AsciiHygieneTests(unittest.TestCase):
    """ASCII-only hard rule per CLAUDE.md; this file MUST stay clean."""

    def test_this_file_is_ascii_clean(self):
        path = Path(__file__).resolve()
        data = path.read_bytes()
        bad = [i for i, b in enumerate(data) if b > 127]
        self.assertEqual(
            bad, [],
            f"non-ASCII bytes in {path.name} at byte offsets {bad[:8]}",
        )

    def test_handler_block_in_agent_is_ascii_clean(self):
        # Scope to the immediate handler block (start marker -> next handler
        # marker). Pre-existing non-ASCII carry elsewhere in the file is per
        # item 165 ledger carry-forward; this test only locks the new block.
        src = _AGENT_PATH.read_text(encoding="utf-8")
        start = src.find('if name == "set_augment_intent":')
        end = src.find('if name == "trade_request":', start)
        self.assertGreater(start, 0)
        self.assertGreater(end, start)
        block = src[start:end]
        bad = [(i, ord(c)) for i, c in enumerate(block) if ord(c) > 127]
        self.assertEqual(
            bad, [],
            f"non-ASCII chars in set_augment_intent handler block: {bad[:8]}",
        )


@unittest.skipUnless(
    os.environ.get("RC_LIVE_ARENA"),
    "needs live Arena 1750 augment-phase session; set RC_LIVE_ARENA=1 to run",
)
class LiveAugmentSelectIntegrationTests(unittest.TestCase):
    """Live-LCU integration tests. Skipped unless ``RC_LIVE_ARENA=1`` is set
    AND the agent is connected to a live Arena 1750 augment-select session.
    Runs the actual PATCH chain end-to-end; first 2xx wins; logs which
    endpoint the live LCU exposes this patch (output is the canonical record
    that updates docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md once verified).
    """

    @classmethod
    def setUpClass(cls):
        cls.agent = _load_agent_module()
        # Live ensure_lcu_conn is a sibling helper that reads the lockfile
        # + initializes _lcu state. Mirrors how the agent's main loop boots.
        if hasattr(cls.agent, "ensure_lcu_conn"):
            cls.agent.ensure_lcu_conn()

    def test_live_augment_select_priority_chain(self):
        """Operator must commit to an augment + verify the LCU client shows
        it lit; output's ``endpoint`` field is the live truth. Use a benign
        but real Arena augment_id (e.g. 1 = Frenetic Flurry; consult the
        live Arena augment-set for this patch via the dashboard).
        """
        AUG = int(os.environ.get("RC_LIVE_AUG_ID", "1"))
        SLOT = int(os.environ.get("RC_LIVE_AUG_SLOT", "0"))
        out = self.agent.execute_command({
            "cmd": "set_augment_intent", "augment_id": AUG, "slot": SLOT,
        })
        print(f"\nLIVE set_augment_intent verdict: {out}")
        self.assertIn("ok", out)


if __name__ == "__main__":
    unittest.main()
