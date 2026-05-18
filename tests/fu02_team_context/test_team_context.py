"""FU02 panel-stub tests - `routes_team_context` + payload schema +
state-builder splice + dispatch registry.

The panel stub ships ahead of `core/riot_api.py`; these tests pin the
contract so the eventual fan-out can fill in the cache without changing
shapes the dashboard depends on.

Coverage:
  - TeamContext / TeamContextEntry pydantic models accept the full +
    minimal shapes from the FU02 ticket.
  - SrPayload accepts an optional team_context block.
  - validate_coaching_payload soft-validates with team_context populated.
  - dispatch._REQUEST_MODELS includes /api/team-context/refresh.
  - GET /api/team-context returns null on cold cache, populated dict
    after a refresh post.
  - POST /api/team-context/refresh: 503 when bridge unconfigured,
    401 on missing/wrong bearer, 400 on non-dict body, 400 on
    >10-row roster, 200 on happy path that segments into allies/enemies.
  - state-builder splice: build_state stamps coach.team_context = None
    by default, returns latest cache after a refresh.
"""
from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.coaching_payload import (   # noqa: E402
    SrPayload, TeamContext, TeamContextEntry, validate_coaching_payload,
)
from dashboard import routes_team_context as RTC   # noqa: E402
from dashboard._dispatch import _REQUEST_MODELS    # noqa: E402
from dashboard.api_schema import (                 # noqa: E402
    TeamContextRefreshRequest, TeamContextRosterSlot,
)


def _full_entry() -> dict:
    return {
        "puuid":             "abcd-puuid-1",
        "summoner_name":     "TestSummoner#NA1",
        "team_id":           100,
        "locked_champion":   "Camille",
        "rank":              "PLATINUM IV 47 LP",
        "mastery_on_locked": 287_000,
        "w_l_streak_7":      [4, 3],
        "mains":             ["Camille", "Jax", "Fiora"],
        "win_rate_recent":   0.55,
    }


def _full_roster_slot() -> dict:
    return {
        "puuid":             "abcd-puuid-1",
        "summoner_name":     "TestSummoner#NA1",
        "team_id":           100,
        "locked_champion":   "Camille",
    }


class _FakeHandler:
    """Minimal _send-capturing stub used for direct route tests."""
    def __init__(self, headers: dict | None = None,
                 client_addr: tuple = ("127.0.0.1", 0)):
        self.headers = headers or {}
        self.client_address = client_addr
        self.captured: dict = {}

    def _send(self, code, body, ctype):
        self.captured["code"]  = code
        self.captured["body"]  = body
        self.captured["ctype"] = ctype


class TestModels(unittest.TestCase):
    def test_team_context_entry_full_shape(self):
        m = TeamContextEntry.model_validate(_full_entry())
        self.assertEqual(m.locked_champion, "Camille")
        self.assertEqual(m.w_l_streak_7, [4, 3])
        self.assertEqual(m.mains, ["Camille", "Jax", "Fiora"])

    def test_team_context_entry_minimal_shape(self):
        # Empty-defaults must be valid (skeleton row).
        m = TeamContextEntry.model_validate({})
        self.assertEqual(m.summoner_name, "")
        self.assertEqual(m.mastery_on_locked, 0)
        self.assertEqual(m.w_l_streak_7, [0, 0])
        self.assertEqual(m.win_rate_recent, 0.0)

    def test_team_context_full_shape(self):
        payload = {
            "allies":  [_full_entry()],
            "enemies": [],
            "refreshed_at": "2026-05-09T16:30:00Z",
            "partial":      False,
            "queue_id":     420,
        }
        m = TeamContext.model_validate(payload)
        self.assertEqual(len(m.allies), 1)
        self.assertEqual(m.queue_id, 420)
        self.assertFalse(m.partial)

    def test_sr_payload_accepts_team_context(self):
        sr = SrPayload.model_validate({
            "mode":   "sr",
            "action": "lane",
            "team_context": {
                "allies":  [_full_entry()],
                "enemies": [],
                "refreshed_at": "2026-05-09T16:30:00Z",
                "partial":      True,
                "queue_id":     420,
            },
        })
        assert sr.team_context is not None  # type: ignore[union-attr]
        self.assertEqual(len(sr.team_context.allies), 1)

    def test_sr_payload_team_context_optional(self):
        sr = SrPayload.model_validate({"mode": "sr"})
        self.assertIsNone(sr.team_context)

    def test_validate_coaching_payload_with_team_context(self, ):
        # validate_coaching_payload should not warn on a valid SR payload
        # carrying a team_context - proves the splice survives the soft
        # validator that wraps build_state().
        payload = {
            "mode":   "sr",
            "action": "lane",
            "team_context": {
                "allies":  [],
                "enemies": [],
                "refreshed_at": "",
                "partial":      True,
                "queue_id":     0,
            },
        }
        with self.assertLogs("rc.coaching_payload", level="WARNING") as logs:
            ok = validate_coaching_payload(payload)
            # No warning records should land for a valid shape; emit a
            # dummy warning so assertLogs doesn't blow up on empty.
            logging.getLogger("rc.coaching_payload").warning("__sentinel__")
        self.assertTrue(ok)
        self.assertEqual(
            [r for r in logs.output if "__sentinel__" not in r],
            [],
            "no validation warnings expected for valid team_context payload",
        )


class TestApiSchema(unittest.TestCase):
    def test_request_model_accepts_full_body(self):
        req = TeamContextRefreshRequest.model_validate({
            "queue_id": 420,
            "roster":   [_full_roster_slot()],
        })
        self.assertEqual(req.queue_id, 420)
        self.assertEqual(req.roster[0].team_id, 100)

    def test_request_model_accepts_empty_roster(self):
        req = TeamContextRefreshRequest.model_validate({})
        self.assertEqual(req.queue_id, 0)
        self.assertEqual(req.roster, [])

    def test_roster_slot_uses_allow_extra(self):
        # Allow-extra so future LCU-agent fields (assignedPosition etc.)
        # don't break the body.
        slot = TeamContextRosterSlot.model_validate({
            **_full_roster_slot(),
            "assignedPosition": "TOP",
        })
        self.assertEqual(slot.locked_champion, "Camille")


class TestDispatchRegistry(unittest.TestCase):
    def test_team_context_refresh_in_request_models(self):
        self.assertIn("/api/team-context/refresh", _REQUEST_MODELS)
        self.assertIs(_REQUEST_MODELS["/api/team-context/refresh"],
                      TeamContextRefreshRequest)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        RTC._clear()
        # Pretend the bridge is configured; tests that override this can
        # patch is_configured directly. shared_secret() returns a known
        # token so we can exercise auth.
        self._is_cfg = mock.patch.object(
            RTC._bridge, "is_configured", return_value=True)
        self._secret = mock.patch.object(
            RTC._bridge, "shared_secret", return_value="test-secret")
        # Replace the fan-out dispatcher with a recording no-op so the
        # POST handler doesn't kick off a real Riot-API worker thread
        # when the test machine has API-Key-Riot.txt staged.
        self._dispatch_calls: list = []
        self._orig_dispatcher = RTC._FANOUT_DISPATCHER
        RTC._FANOUT_DISPATCHER = self._record_dispatch
        self._is_cfg.start()
        self._secret.start()

    def _record_dispatch(self, allies, enemies, queue_id):
        self._dispatch_calls.append({
            "allies": list(allies),
            "enemies": list(enemies),
            "queue_id": int(queue_id),
        })

    def tearDown(self):
        self._is_cfg.stop()
        self._secret.stop()
        RTC._FANOUT_DISPATCHER = self._orig_dispatcher
        RTC._clear()

    def test_get_team_context_cold_returns_null(self):
        h = _FakeHandler()
        RTC._serve_get(h)
        self.assertEqual(h.captured["code"], 200)
        body = json.loads(h.captured["body"])
        self.assertIsNone(body["team_context"])
        self.assertIsNone(body["age_s"])

    def test_post_refresh_503_when_bridge_unconfigured(self):
        with mock.patch.object(RTC._bridge, "is_configured",
                               return_value=False):
            h = _FakeHandler()
            RTC._serve_refresh_post(h, {"queue_id": 420, "roster": []})
        self.assertEqual(h.captured["code"], 503)
        self.assertIn(b"bridge_not_configured", h.captured["body"])

    def test_post_refresh_401_on_missing_auth(self):
        h = _FakeHandler(headers={})
        RTC._serve_refresh_post(h, {"queue_id": 420, "roster": []})
        self.assertEqual(h.captured["code"], 401)

    def test_post_refresh_401_on_wrong_bearer(self):
        h = _FakeHandler(headers={"Authorization": "Bearer wrong-token"})
        RTC._serve_refresh_post(h, {"queue_id": 420, "roster": []})
        self.assertEqual(h.captured["code"], 401)

    def test_post_refresh_400_on_non_dict_body(self):
        h = _FakeHandler(headers={"Authorization": "Bearer test-secret"})
        RTC._serve_refresh_post(h, ["not", "a", "dict"])
        self.assertEqual(h.captured["code"], 400)
        self.assertIn(b"body_must_be_object", h.captured["body"])

    def test_post_refresh_400_on_roster_too_large(self):
        h = _FakeHandler(headers={"Authorization": "Bearer test-secret"})
        # 11 slots - over the 10-player champ-select cap.
        roster = [_full_roster_slot() for _ in range(11)]
        RTC._serve_refresh_post(h, {"queue_id": 420, "roster": roster})
        self.assertEqual(h.captured["code"], 400)
        body = json.loads(h.captured["body"])
        self.assertEqual(body["error"], "roster_too_large")
        self.assertEqual(body["max"], 10)
        self.assertEqual(body["got"], 11)

    def test_post_refresh_happy_path_segments_teams(self):
        h = _FakeHandler(headers={"Authorization": "Bearer test-secret"})
        roster = [
            {**_full_roster_slot(), "team_id": 100},  # ally
            {**_full_roster_slot(), "team_id": 100, "locked_champion": "Jax"},
            {**_full_roster_slot(), "team_id": 200, "locked_champion": "Yasuo"},
            {**_full_roster_slot(), "team_id": 200, "locked_champion": "Lux"},
        ]
        RTC._serve_refresh_post(h, {"queue_id": 420, "roster": roster})
        self.assertEqual(h.captured["code"], 200)
        body = json.loads(h.captured["body"])
        self.assertTrue(body["ok"])
        self.assertEqual(body["stored"]["allies"], 2)
        self.assertEqual(body["stored"]["enemies"], 2)
        # Cache is now hot - get should return the same payload shape.
        cache = RTC.get_team_context()
        self.assertIsNotNone(cache)
        assert cache is not None  # mypy/type-narrow
        self.assertEqual(cache["queue_id"], 420)
        self.assertEqual(len(cache["allies"]), 2)
        self.assertEqual(len(cache["enemies"]), 2)
        self.assertTrue(cache["partial"])
        # Each entry has the FU02-ticket shape - empty enrichment fields
        # set to soft-fail defaults.
        ally = cache["allies"][0]
        self.assertEqual(ally["locked_champion"], "Camille")
        self.assertEqual(ally["rank"], "")
        self.assertEqual(ally["mastery_on_locked"], 0)
        self.assertEqual(ally["w_l_streak_7"], [0, 0])
        self.assertEqual(ally["mains"], [])

    def test_get_after_refresh_includes_age(self):
        h = _FakeHandler(headers={"Authorization": "Bearer test-secret"})
        RTC._serve_refresh_post(h, {"queue_id": 400,
                                    "roster": [_full_roster_slot()]})
        h2 = _FakeHandler()
        RTC._serve_get(h2)
        body = json.loads(h2.captured["body"])
        self.assertIsNotNone(body["team_context"])
        self.assertEqual(body["team_context"]["queue_id"], 400)
        self.assertIsNotNone(body["age_s"])
        self.assertGreaterEqual(body["age_s"], 0.0)


class TestStateBuilderSplice(unittest.TestCase):
    """Verify _state_builder.build_state() splices coach.team_context."""

    def setUp(self):
        RTC._clear()

    def tearDown(self):
        RTC._clear()

    def test_state_carries_none_when_cache_empty(self):
        from dashboard._state_builder import build_state
        st = build_state()
        # team_context key should exist even when cache is cold.
        self.assertIn("team_context", st["coach"])
        self.assertIsNone(st["coach"]["team_context"])

    def test_state_carries_payload_after_refresh(self):
        # Push a payload directly through the storage helper so the test
        # doesn't depend on auth.
        RTC._store({
            "allies":       [_full_entry()],
            "enemies":      [],
            "refreshed_at": "2026-05-09T16:30:00Z",
            "partial":      True,
            "queue_id":     420,
        })
        from dashboard._state_builder import build_state
        st = build_state()
        tc = st["coach"]["team_context"]
        self.assertIsNotNone(tc)
        self.assertEqual(tc["queue_id"], 420)
        self.assertEqual(len(tc["allies"]), 1)
        self.assertTrue(tc["partial"])


if __name__ == "__main__":
    unittest.main()
