"""s144 true-audit (S144-T-607) - core/archetype_mismatch.py hardening.

The first-purchase nudge runs on every /api/state build. These tests pin
the defects the audit measured on the pre-fix module:

* The synthetic per-game dedup token (Live Client's gameData carries no
  gameId, so this is the live path) was ``int((now - game_time_s) / 60)``.
  Poll-to-poll jitter across a minute boundary, or a game pause, changed
  the token mid-game, so a DISMISSED nudge was re-evaluated and fired
  again, and the dispatcher was re-called.
* A junk clock formed a token anyway: game_time_s 0 (the summary's
  missing default) gave a token that changes every wall-clock minute,
  True read as 1 s, and an infinite clock raised OverflowError.
* The Riot-compliance "second fence" in ``_engine_mode`` returned "" for
  a forbidden mode, but the caller still called the DS dispatcher with
  mode "" and served / cached a nudge.
* Wrong-typed fields raised (primary / source / game_mode / level /
  ranked rows), a string owned_item_ids was iterated per character, and
  a dict champion became its own repr.
* The served payload shared its expected_items list with the cache.
* The cache had no bound on distinct champion keys.
"""
from __future__ import annotations

import math
import unittest
from unittest import mock

from core import archetype_mismatch as am


def _pick(champion: object = "Nasus", primary: object = "tank",
          source: object = "user_cs") -> dict:
    return {"champion": champion, "primary": primary, "source": source}


def _lc(game_time_s: object = 600, **extra) -> dict:
    out = {
        "champion":       "Nasus",
        "game_id":        "",
        "game_time_s":    game_time_s,
        "owned_item_ids": [3047, 3031],
        "owned_items":    ["Plated Steelcaps", "Infinity Edge"],
        "level":          11,
        "game_mode":      "CLASSIC",
    }
    out.update(extra)
    return out


_FIRED = (True, ["Warmog's Armor", "Heartsteel", "Sunfire Aegis"])

# "3031" in Arabic-Indic digits: str.isdigit() is True for it, so it must be
# refused by the ASCII check. Built from code points to keep this file ASCII.
_ARABIC_INDIC_3031 = "".join(chr(c) for c in (0x0663, 0x0660, 0x0663, 0x0661))


class _Base(unittest.TestCase):
    def setUp(self):
        am.reset_nudge_state()

    def tearDown(self):
        am.reset_nudge_state()


class SyntheticSessionStabilityTests(_Base):
    """A game's synthetic token must not change while the game runs."""

    def test_minute_boundary_jitter_does_not_refire_a_dismissed_nudge(self):
        # Game started near wall 1020 s; the second poll reads a liveclient
        # sample about 1 s staler than the first. The floor of
        # (now - gt) / 60 flips from 16 (1019.9) to 17 (1021.0).
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev, \
                mock.patch.object(am.time, "time", return_value=1039.9):
            first = am.compute_nudge_payload({}, _lc(game_time_s=20), {}, _pick())
        self.assertEqual(first.get("phase"), "fired")
        self.assertTrue(am.dismiss_nudge("Nasus"))
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev, \
                mock.patch.object(am.time, "time", return_value=1041.0):
            second = am.compute_nudge_payload({}, _lc(game_time_s=20), {}, _pick())
        self.assertEqual(ev.call_count, 0, "same game must not re-call the dispatcher")
        self.assertEqual(second.get("phase"), "dismissed")
        self.assertFalse(second.get("fired"))
        self.assertEqual(second.get("session_token"), first.get("session_token"))

    def test_a_pause_followed_poll_by_poll_keeps_the_session(self):
        # The game clock freezes for 5 minutes while the wall clock runs;
        # every poll moves the derived start by a few seconds only.
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            with mock.patch.object(am.time, "time", return_value=10_000.0):
                am.compute_nudge_payload({}, _lc(game_time_s=900), {}, _pick())
            am.dismiss_nudge("Nasus")
            for step in range(1, 101):
                with mock.patch.object(am.time, "time", return_value=10_000.0 + 3 * step):
                    out = am.compute_nudge_payload({}, _lc(game_time_s=900), {}, _pick())
                self.assertEqual(out.get("phase"), "dismissed", step)
        self.assertEqual(ev.call_count, 1)

    def test_a_new_game_with_the_same_champion_re_evaluates(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            with mock.patch.object(am.time, "time", return_value=10_000.0):
                am.compute_nudge_payload({}, _lc(game_time_s=1500), {}, _pick())
            am.dismiss_nudge("Nasus")
            # Next game: 40 minutes later on the wall clock, 9 min in.
            with mock.patch.object(am.time, "time", return_value=12_400.0):
                out = am.compute_nudge_payload({}, _lc(game_time_s=540), {}, _pick())
        self.assertEqual(ev.call_count, 2)
        self.assertEqual(out.get("phase"), "fired")

    def test_a_new_game_at_a_higher_clock_is_still_a_new_game(self):
        # Polling stopped at 8:00 of game A; game B's first poll reads a
        # HIGHER clock (10:00), so only the start tolerance can tell them
        # apart (B started 15 minutes after A).
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            with mock.patch.object(am.time, "time", return_value=10_000.0):
                am.compute_nudge_payload({}, _lc(game_time_s=480), {}, _pick())
            am.dismiss_nudge("Nasus")
            with mock.patch.object(am.time, "time", return_value=11_020.0):
                out = am.compute_nudge_payload({}, _lc(game_time_s=600), {}, _pick())
        self.assertEqual(ev.call_count, 2)
        self.assertEqual(out.get("phase"), "fired")

    def test_game_clock_going_backwards_is_a_new_game(self):
        # Same derived start within tolerance, but the game clock fell
        # from 600 to 300: that is a different game, not jitter.
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            with mock.patch.object(am.time, "time", return_value=10_000.0):
                am.compute_nudge_payload({}, _lc(game_time_s=600), {}, _pick())
            with mock.patch.object(am.time, "time", return_value=9_760.0):
                am.compute_nudge_payload({}, _lc(game_time_s=300), {}, _pick())
        self.assertEqual(ev.call_count, 2)

    def test_game_id_path_is_unchanged_exact_match(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            am.compute_nudge_payload({}, _lc(game_id="111"), {}, _pick())
            am.compute_nudge_payload({}, _lc(game_id="111", game_time_s=0), {}, _pick())
            am.compute_nudge_payload({}, _lc(game_id="222"), {}, _pick())
        self.assertEqual(ev.call_count, 2)


class JunkClockTests(_Base):
    """No synthetic token from a clock that cannot be a real game time."""

    def test_session_token_refuses_junk_clocks(self):
        for gt in (0, -5, True, False, math.inf, -math.inf, math.nan, "600", [600], 0.0):
            with self.subTest(gt=gt):
                self.assertEqual(am._session_token({"game_time_s": gt}, "Nasus"), "")

    def test_session_token_accepts_a_real_clock(self):
        with mock.patch.object(am.time, "time", return_value=6_600.0):
            self.assertEqual(am._session_token({"game_time_s": 600}, "Nasus"), "Nasus@100")
            self.assertEqual(am._session_token({"game_time_s": 600.5}, "Nasus"), "Nasus@99")

    def test_infinite_clock_does_not_raise_from_compute(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            out = am.compute_nudge_payload({}, _lc(game_time_s=math.inf), {}, _pick())
        self.assertEqual(out, {})
        self.assertEqual(ev.call_count, 0)

    def test_zero_clock_with_a_completed_item_forms_no_token(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            out = am.compute_nudge_payload({}, _lc(game_time_s=0), {}, _pick())
        self.assertEqual(out, {})
        self.assertEqual(ev.call_count, 0)

    def test_game_id_must_be_a_string(self):
        # A non-string game_id is not a token (the summary emits str or "").
        for gid in (True, 5, {"a": 1}, ["x"]):
            with self.subTest(gid=gid):
                self.assertEqual(am._session_token({"game_id": gid}, "Nasus"), "")


class ForbiddenModeFenceTests(_Base):
    """A forbidden mode gets no nudge and no DS call, ever."""

    def test_forbidden_mode_never_calls_the_dispatcher(self):
        for gm in ("BRAWL", "brawl", "CLASSIC_LEAGUE", "LEAGUECLASSIC"):
            with self.subTest(gm=gm):
                am.reset_nudge_state()
                with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
                    out = am.compute_nudge_payload({}, _lc(game_mode=gm), {}, _pick())
                self.assertEqual(out, {})
                self.assertEqual(ev.call_count, 0)
                self.assertEqual(am.get_nudge_state_snapshot(), {})

    def test_forbidden_mode_gets_no_pending_payload(self):
        out = am.compute_nudge_payload(
            {}, _lc(game_mode="BRAWL", owned_item_ids=[3047]), {}, _pick())
        self.assertEqual(out, {})

    def test_allowed_modes_still_evaluate(self):
        for gm, engine in (("CLASSIC", "SR"), ("ARAM", "ARAM"), ("CHERRY", "ARENA"),
                           ("URF", "SR"), (None, "SR")):
            with self.subTest(gm=gm):
                am.reset_nudge_state()
                with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
                    out = am.compute_nudge_payload({}, _lc(game_mode=gm), {}, _pick())
                self.assertEqual(out.get("phase"), "fired")
                self.assertEqual(ev.call_args.kwargs["mode_engine"], engine)

    def test_engine_mode_on_a_non_string_does_not_raise(self):
        for gm in (5, ["ARAM"], {"x": 1}, True):
            with self.subTest(gm=gm):
                self.assertEqual(am._engine_mode({"game_mode": gm}), "SR")


class WrongShapeInputTests(_Base):
    """Merely wrong input degrades to no nudge (or the safe default)."""

    def _quiet(self, coach, lc, pick) -> dict:
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
            out = am.compute_nudge_payload(coach, lc, {}, pick)
        return out, ev.call_count

    def test_non_string_primary_or_source(self):
        for pick in (_pick(primary=["tank"]), _pick(primary=5), _pick(primary={"a": 1}),
                     _pick(source=["user_cs"]), _pick(source=7)):
            with self.subTest(pick=pick):
                am.reset_nudge_state()
                out, calls = self._quiet({}, _lc(), pick)
                if isinstance(pick["primary"], str):
                    # A junk source is not "default", so a str primary still runs.
                    self.assertEqual(out.get("phase"), "fired")
                else:
                    self.assertEqual(out, {})
                    self.assertEqual(calls, 0)

    def test_non_string_champion_is_never_its_repr(self):
        for champ in ({"name": "Nasus"}, ["Nasus"], 42, True):
            with self.subTest(champ=champ):
                am.reset_nudge_state()
                lc = _lc()
                lc["champion"] = champ
                out, calls = self._quiet({"champion": champ}, lc, _pick(champion=champ))
                self.assertEqual(out, {})
                self.assertEqual(calls, 0)

    def test_falls_through_a_bad_pick_champion_to_the_liveclient_one(self):
        out, calls = self._quiet({}, _lc(), _pick(champion=["junk"]))
        self.assertEqual(out.get("champion"), "Nasus")
        self.assertEqual(calls, 1)

    def test_owned_item_ids_string_is_not_iterated_per_character(self):
        for ids in ("3031", b"3031", {"3031": 1}, 3031, None):
            with self.subTest(ids=ids):
                am.reset_nudge_state()
                out, calls = self._quiet({}, _lc(owned_item_ids=ids), _pick())
                self.assertEqual(out.get("phase"), "pending")
                self.assertNotIn("first_item_id", out)
                self.assertEqual(calls, 0)

    def test_first_item_skips_non_id_entries(self):
        self.assertEqual(
            am._first_completed_item_id([True, 3.5, math.nan, "nan", "-5", -5, "x1",
                                         _ARABIC_INDIC_3031, {"id": 1}, " 3031 "]),
            "3031",
        )
        self.assertEqual(am._first_completed_item_id([6672]), "6672")

    def test_huge_int_item_id_never_raises(self):
        # str() of an int past 4300 digits raises ValueError on 3.11+.
        huge = 10 ** 5000
        self.assertEqual(am._first_completed_item_id([huge, 10 ** 9, 3031]), "3031")
        with mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        return_value={"ranked": [{"item_id": huge, "item_name": "x"},
                                                 {"item_id": 3068, "item_name": "Sunfire"}]}):
            self.assertEqual(am._evaluate_dispatcher("Nasus", "tank", "3031", 11, "SR"),
                             (True, ["x", "Sunfire"]))

    def test_level_junk_never_raises_and_is_clamped(self):
        for level, expected in (("abc", 1), (math.nan, 1), (math.inf, 1), (None, 1),
                                (True, 1), (-4, 1), (0, 1), (11, 11), (11.7, 11),
                                (99, 18), ([5], 1)):
            with self.subTest(level=level):
                am.reset_nudge_state()
                with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED) as ev:
                    out = am.compute_nudge_payload({}, _lc(level=level), {}, _pick())
                self.assertEqual(out.get("phase"), "fired")
                self.assertEqual(ev.call_args.kwargs["level"], expected)


class DispatcherShapeTests(unittest.TestCase):
    """``_evaluate_dispatcher`` tolerates a wrong-shaped DS reply."""

    def _run(self, out):
        with mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                        return_value=out):
            return am._evaluate_dispatcher("Nasus", "tank", "3031", 11, "SR")

    def test_non_list_ranked_is_no_signal(self):
        for ranked in ({"item_id": "3031"}, "3031", 5):
            with self.subTest(ranked=ranked):
                self.assertIsNone(self._run({"ranked": ranked}))

    def test_non_dict_rows_are_skipped(self):
        got = self._run({"ranked": ["3031", None, 7,
                                    {"item_id": 3068, "item_name": "Sunfire Aegis"}]})
        self.assertEqual(got, (True, ["Sunfire Aegis"]))

    def test_all_rows_junk_is_no_signal(self):
        self.assertIsNone(self._run({"ranked": ["3031", None]}))

    def test_rows_without_any_item_id_are_no_signal(self):
        # Against an empty id set every buy read as a mismatch (false fire).
        for rows in ([{"item_name": "Sunfire Aegis"}],
                     [{"item_id": "", "item_name": "x"}, {"item_id": None}],
                     [{"item_id": "nan"}, {"item_id": True}]):
            with self.subTest(rows=rows):
                self.assertIsNone(self._run({"ranked": rows}))

    def test_int_item_id_rows_match(self):
        got = self._run({"ranked": [{"item_id": 3031, "item_name": "Infinity Edge"}]})
        self.assertEqual(got, (False, ["Infinity Edge"]))


class CacheIsolationTests(_Base):
    def test_mutating_a_served_payload_does_not_touch_the_cache(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED):
            first = am.compute_nudge_payload({}, _lc(game_id="9"), {}, _pick())
            first["expected_items"].append("POISON")
            second = am.compute_nudge_payload({}, _lc(game_id="9"), {}, _pick())
        self.assertNotIn("POISON", second["expected_items"])
        second["expected_items"].append("POISON2")
        snap = am.get_nudge_state_snapshot()["Nasus"]
        self.assertNotIn("POISON2", snap["expected_items"])
        snap["expected_items"].append("POISON3")
        self.assertNotIn("POISON3", am.get_nudge_state_snapshot()["Nasus"]["expected_items"])

    def test_cache_is_bounded(self):
        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED):
            for i in range(am._MAX_CACHED_CHAMPIONS + 25):
                name = f"Champ{i}"
                lc = _lc(game_id=str(i + 1))
                lc["champion"] = name
                am.compute_nudge_payload({}, lc, {}, _pick(champion=name))
        snap = am.get_nudge_state_snapshot()
        self.assertEqual(len(snap), am._MAX_CACHED_CHAMPIONS)
        # Newest kept, oldest evicted.
        self.assertIn(f"Champ{am._MAX_CACHED_CHAMPIONS + 24}", snap)
        self.assertNotIn("Champ0", snap)

    def test_a_re_evaluated_champion_becomes_the_newest(self):
        def _eval(name: str, gid: str) -> None:
            lc = _lc(game_id=gid)
            lc["champion"] = name
            am.compute_nudge_payload({}, lc, {}, _pick(champion=name))

        with mock.patch.object(am, "_evaluate_dispatcher", return_value=_FIRED):
            _eval("Champ0", "1")
            for i in range(1, am._MAX_CACHED_CHAMPIONS):
                _eval(f"Champ{i}", str(i + 1))
            _eval("Champ0", "999")  # new game for the oldest key
            _eval("Overflow", "1000")
        snap = am.get_nudge_state_snapshot()
        self.assertIn("Champ0", snap)
        self.assertNotIn("Champ1", snap)
        self.assertEqual(len(am._SESSION_CLOCK), 0)


if __name__ == "__main__":
    unittest.main()
