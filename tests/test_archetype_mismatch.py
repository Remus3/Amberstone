"""Tests for `core.archetype_mismatch` — s184 first-purchase soft-nudge.

Covers the four entry points the dashboard touches:

* ``_first_completed_item_id`` — denylist filtering
* ``_session_token`` — game-session dedup key resolution
* ``compute_nudge_payload`` — full evaluator (12 cases — happy path,
  dedup, edge cases, engine-down)
* ``dismiss_nudge`` — operator dismissed the chip

Plus a tiny ``NudgeResult.to_dict`` shape test.

We mock ``rank_for_primary_archetype`` at the import boundary inside the
``_evaluate_dispatcher`` call so the tests don't need the DS server. The
module-level ``_NUDGE_STATE`` cache is reset between tests via setUp.
"""
from __future__ import annotations

import unittest
from unittest import mock

from core import archetype_mismatch as am


def _ranked_rows(*item_ids: str) -> list[dict]:
    """Convenience: build the dispatcher's ``ranked`` list shape."""
    return [
        {"item_id": iid, "item_name": f"Item{iid}", "delta_dps": 100.0, "gold": 3000}
        for iid in item_ids
    ]


def _dispatcher_out(item_ids: list[str]) -> dict:
    return {
        "ok":        True,
        "scorer":    "dps",
        "archetype": "carry",
        "ranked":    _ranked_rows(*item_ids),
        "fell_back": False,
    }


class FirstCompletedItemIdTests(unittest.TestCase):
    """``_first_completed_item_id`` should skip the denylist + return
    the first signal-bearing id."""

    def test_returns_first_signal_item(self):
        # 3047=boots (skip), 3031=IE (signal)
        self.assertEqual(
            am._first_completed_item_id(["3047", "3031", "3094"]),
            "3031",
        )

    def test_skips_all_boots_variants(self):
        # All-boots inventory: no signal
        self.assertEqual(am._first_completed_item_id(["3006", "3047", "3111"]), "")

    def test_skips_dorans(self):
        # 1054 Doran's Shield + 2003 potion = no signal yet
        self.assertEqual(am._first_completed_item_id(["1054", "2003"]), "")

    def test_skips_trinkets(self):
        self.assertEqual(am._first_completed_item_id(["3340", "3363"]), "")

    def test_skips_consumables_and_starters(self):
        # 2003 potion + 3850 spellthief starter
        self.assertEqual(am._first_completed_item_id(["2003", "3850", "3858"]), "")

    def test_empty_or_zero_entries_skipped(self):
        self.assertEqual(
            am._first_completed_item_id(["", 0, None, "0", "3031"]),
            "3031",
        )

    def test_int_and_str_both_accepted(self):
        # liveclient may give ints; we coerce
        self.assertEqual(am._first_completed_item_id([3047, 3031]), "3031")

    def test_empty_list(self):
        self.assertEqual(am._first_completed_item_id([]), "")

    def test_none_input(self):
        self.assertEqual(am._first_completed_item_id(None), "")


class SessionTokenTests(unittest.TestCase):
    """``_session_token`` prefers liveclient game_id, falls back to
    ``champion@start-floor`` synthetic."""

    def test_uses_game_id_when_present(self):
        self.assertEqual(
            am._session_token({"game_id": "NA1_123456"}, "Caitlyn"),
            "NA1_123456",
        )

    def test_falls_back_to_synthetic(self):
        # game_time_s present → synthetic "Caitlyn@<floor>"
        with mock.patch("core.archetype_mismatch.time.time", return_value=1_700_000_000):
            token = am._session_token({"game_time_s": 600}, "Caitlyn")
        self.assertTrue(token.startswith("Caitlyn@"))

    def test_empty_when_no_lc(self):
        self.assertEqual(am._session_token(None, "Caitlyn"), "")
        self.assertEqual(am._session_token({}, "Caitlyn"), "")

    def test_empty_when_no_game_time_or_id(self):
        # No game_id AND no game_time_s → can't form a token
        self.assertEqual(am._session_token({"level": 5}, "Caitlyn"), "")


class EngineModeTests(unittest.TestCase):

    def test_sr_default(self):
        self.assertEqual(am._engine_mode({"game_mode": "CLASSIC"}), "SR")
        self.assertEqual(am._engine_mode({}), "SR")
        self.assertEqual(am._engine_mode(None), "SR")

    def test_aram(self):
        self.assertEqual(am._engine_mode({"game_mode": "ARAM"}), "ARAM")

    def test_arena_via_cherry(self):
        self.assertEqual(am._engine_mode({"game_mode": "CHERRY"}), "ARENA")

    def test_brawl(self):
        self.assertEqual(am._engine_mode({"game_mode": "BRAWL"}), "BRAWL")


class ComputeNudgeNoSignalTests(unittest.TestCase):
    """Cases where ``compute_nudge_payload`` should return ``{}`` outright."""

    def setUp(self):
        am.reset_nudge_state()

    def test_empty_archetype_pick(self):
        self.assertEqual(
            am.compute_nudge_payload({}, {"champion": "C", "game_id": "g"}, {}, {}),
            {},
        )

    def test_archetype_pick_without_primary(self):
        self.assertEqual(
            am.compute_nudge_payload(
                {},
                {"champion": "C", "game_id": "g"},
                {},
                {"champion": "C", "source": "user_cs"},
            ),
            {},
        )

    def test_default_source_skipped(self):
        # DDragon-tag default isn't operator intent — no nudge
        self.assertEqual(
            am.compute_nudge_payload(
                {},
                {"champion": "C", "game_id": "g", "owned_item_ids": ["3031"]},
                {},
                {"champion": "C", "primary": "tank", "source": "default"},
            ),
            {},
        )

    def test_no_liveclient(self):
        self.assertEqual(
            am.compute_nudge_payload(
                {},
                None,
                {},
                {"champion": "C", "primary": "tank", "source": "user_cs"},
            ),
            {},
        )

    def test_no_champion_resolved(self):
        # Pick has no champion + no LC champion + no coach champion
        self.assertEqual(
            am.compute_nudge_payload(
                {},
                {"game_id": "g", "owned_item_ids": ["3031"]},
                {},
                {"primary": "tank", "source": "user_cs"},
            ),
            {},
        )


class ComputeNudgePendingTests(unittest.TestCase):
    """No first completed item yet → ``pending`` phase."""

    def setUp(self):
        am.reset_nudge_state()

    def test_pending_when_only_boots(self):
        result = am.compute_nudge_payload(
            {},
            {"champion": "Nasus", "game_id": "g1", "owned_item_ids": ["3047", "2003"]},
            {},
            {"champion": "Nasus", "primary": "tank", "source": "user_cs"},
        )
        self.assertEqual(result.get("phase"), "pending")
        self.assertFalse(result.get("fired"))

    def test_pending_no_items_at_all(self):
        result = am.compute_nudge_payload(
            {},
            {"champion": "Nasus", "game_id": "g1", "owned_item_ids": []},
            {},
            {"champion": "Nasus", "primary": "tank", "source": "user_cs"},
        )
        self.assertEqual(result.get("phase"), "pending")


class ComputeNudgeFiredTests(unittest.TestCase):
    """Happy path + dedup + engine-down."""

    def setUp(self):
        am.reset_nudge_state()

    def _lc(self, owned_ids: list[str]) -> dict:
        return {
            "champion":       "Nasus",
            "game_id":        "NA1_999",
            "owned_item_ids": owned_ids,
            "owned_items":    [f"Name_{i}" for i in owned_ids],
            "level":          11,
            "game_mode":      "CLASSIC",
        }

    def _pick(self) -> dict:
        return {"champion": "Nasus", "primary": "tank", "source": "user_cs"}

    def test_fires_when_first_item_not_in_top15(self):
        # Operator picked tank but bought IE (3031). Dispatcher returns
        # tank items (Warmog/Heartsteel/Sunfire/…) — IE not in top 15.
        with mock.patch.object(
            am, "_evaluate_dispatcher",
            return_value=(True, ["Warmog's Armor", "Heartsteel", "Sunfire"]),
        ):
            result = am.compute_nudge_payload({}, self._lc(["3047", "3031"]), {}, self._pick())
        self.assertTrue(result.get("fired"))
        self.assertEqual(result.get("phase"), "fired")
        self.assertEqual(result.get("first_item_id"), "3031")
        self.assertEqual(result.get("primary"), "tank")
        self.assertEqual(result.get("champion"), "Nasus")
        self.assertIn("Warmog", result.get("message", ""))

    def test_no_mismatch_when_first_item_in_top15(self):
        with mock.patch.object(
            am, "_evaluate_dispatcher",
            return_value=(False, ["Warmog's Armor", "Heartsteel"]),
        ):
            result = am.compute_nudge_payload({}, self._lc(["3047", "3094"]), {}, self._pick())
        self.assertFalse(result.get("fired"))
        self.assertEqual(result.get("phase"), "no_mismatch")
        self.assertEqual(result.get("first_item_id"), "3094")

    def test_dedup_same_session_reuses_cached(self):
        # First call evaluates + caches; second call must NOT re-call the
        # dispatcher even if we change the recommendation.
        with mock.patch.object(am, "_evaluate_dispatcher") as mock_eval:
            mock_eval.return_value = (True, ["Warmog's", "Heartsteel"])
            first = am.compute_nudge_payload({}, self._lc(["3047", "3031"]), {}, self._pick())
            self.assertEqual(mock_eval.call_count, 1)
            second = am.compute_nudge_payload({}, self._lc(["3047", "3031"]), {}, self._pick())
            self.assertEqual(mock_eval.call_count, 1, "dispatcher should NOT be re-invoked")
        self.assertEqual(first.get("session_token"), second.get("session_token"))

    def test_re_evaluates_when_session_changes(self):
        # Same champion, different game_id → fresh evaluation
        with mock.patch.object(am, "_evaluate_dispatcher") as mock_eval:
            mock_eval.return_value = (True, ["Warmog's", "Heartsteel"])
            lc1 = self._lc(["3047", "3031"])
            lc1["game_id"] = "NA1_111"
            am.compute_nudge_payload({}, lc1, {}, self._pick())

            lc2 = self._lc(["3047", "3031"])
            lc2["game_id"] = "NA1_222"
            am.compute_nudge_payload({}, lc2, {}, self._pick())

            self.assertEqual(mock_eval.call_count, 2)

    def test_engine_down_returns_empty(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=None):
            result = am.compute_nudge_payload({}, self._lc(["3047", "3031"]), {}, self._pick())
        self.assertEqual(result, {})
        # Crucially: no cache entry written (so next poll retries)
        self.assertEqual(am.get_nudge_state_snapshot(), {})

    def test_no_session_token_returns_empty(self):
        # liveclient has owned items but no game_id and no game_time_s
        lc = self._lc(["3047", "3031"])
        del lc["game_id"]
        # also remove fallback game_time_s — _session_token will return ""
        result = am.compute_nudge_payload({}, lc, {}, self._pick())
        self.assertEqual(result, {})


class DismissNudgeTests(unittest.TestCase):

    def setUp(self):
        am.reset_nudge_state()

    def test_dismiss_after_fire(self):
        # Seed a fired state
        with mock.patch.object(
            am, "_evaluate_dispatcher", return_value=(True, ["Warmog's"]),
        ):
            am.compute_nudge_payload(
                {},
                {
                    "champion":       "Nasus",
                    "game_id":        "g1",
                    "owned_item_ids": ["3047", "3031"],
                    "owned_items":    ["Boots", "IE"],
                    "level":          11,
                    "game_mode":      "CLASSIC",
                },
                {},
                {"champion": "Nasus", "primary": "tank", "source": "user_cs"},
            )
        self.assertTrue(am.dismiss_nudge("Nasus"))
        # State should now reflect dismissed
        snapshot = am.get_nudge_state_snapshot()
        self.assertEqual(snapshot["Nasus"]["phase"], "dismissed")
        self.assertFalse(snapshot["Nasus"]["fired"])

    def test_dismiss_no_entry(self):
        self.assertFalse(am.dismiss_nudge("Nasus"))

    def test_dismiss_empty_champion(self):
        self.assertFalse(am.dismiss_nudge(""))
        self.assertFalse(am.dismiss_nudge(None))

    def test_dismiss_idempotent(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=(True, [])):
            am.compute_nudge_payload(
                {},
                {
                    "champion":       "Nasus",
                    "game_id":        "g1",
                    "owned_item_ids": ["3047", "3031"],
                    "owned_items":    ["Boots", "IE"],
                    "level":          11,
                    "game_mode":      "CLASSIC",
                },
                {},
                {"champion": "Nasus", "primary": "tank", "source": "user_cs"},
            )
        self.assertTrue(am.dismiss_nudge("Nasus"))
        # Second call still returns True because entry exists (even if dismissed)
        self.assertTrue(am.dismiss_nudge("Nasus"))


class NudgeResultShapeTests(unittest.TestCase):

    def test_to_dict_shape(self):
        r = am.NudgeResult(
            fired=True,
            phase="fired",
            champion="C",
            primary="tank",
            first_item_id="3031",
            first_item_name="IE",
            message="msg",
            expected_items=["Warmog's"],
            session_token="t",
        )
        d = r.to_dict()
        self.assertEqual(d["fired"], True)
        self.assertEqual(d["phase"], "fired")
        self.assertEqual(d["champion"], "C")
        self.assertEqual(d["primary"], "tank")
        self.assertEqual(d["first_item_id"], "3031")
        self.assertEqual(d["first_item_name"], "IE")
        self.assertEqual(d["message"], "msg")
        self.assertEqual(d["expected_items"], ["Warmog's"])
        self.assertEqual(d["session_token"], "t")


class EvaluateDispatcherTests(unittest.TestCase):
    """The dispatcher caller boundary."""

    def test_returns_none_on_exception(self):
        # Function raises → _evaluate_dispatcher's broad except returns None
        with mock.patch(
            "core.daemon_slayer_client.rank_for_primary_archetype",
            side_effect=RuntimeError("boom"),
        ):
            result = am._evaluate_dispatcher("C", "tank", "3031", 11, "SR")
        self.assertIsNone(result)

    def test_returns_none_when_dispatcher_returns_none(self):
        with mock.patch(
            "core.daemon_slayer_client.rank_for_primary_archetype",
            return_value=None,
        ):
            result = am._evaluate_dispatcher("C", "tank", "3031", 11, "SR")
        self.assertIsNone(result)

    def test_returns_none_when_ranked_empty(self):
        with mock.patch(
            "core.daemon_slayer_client.rank_for_primary_archetype",
            return_value={"ok": True, "ranked": []},
        ):
            result = am._evaluate_dispatcher("C", "tank", "3031", 11, "SR")
        self.assertIsNone(result)

    def test_mismatch_when_item_not_in_top_n(self):
        with mock.patch(
            "core.daemon_slayer_client.rank_for_primary_archetype",
            return_value=_dispatcher_out(["3083", "7000", "3068"]),
        ):
            result = am._evaluate_dispatcher("C", "tank", "3031", 11, "SR")
        self.assertEqual(result, (True, ["Item3083", "Item7000", "Item3068"]))

    def test_no_mismatch_when_item_in_top_n(self):
        with mock.patch(
            "core.daemon_slayer_client.rank_for_primary_archetype",
            return_value=_dispatcher_out(["3031", "7000", "3068"]),
        ):
            result = am._evaluate_dispatcher("C", "carry", "3031", 11, "SR")
        # Second tuple value is top-3 names
        self.assertEqual(result, (False, ["Item3031", "Item7000", "Item3068"]))


if __name__ == "__main__":
    unittest.main()
