"""tests/test_pickban_systems_p1l2.py - P1 audit lane L2.

Pick/Ban logic validated AGAINST ITSELF and against every system it
touches: core.smoothed_rates (the shared Laplace/Beta primitive),
dashboard.routes_pickban (the recommender), and the champ-select coach
path (coaches.champ_select_coach + dashboard._champ_select).

This is a correctness + consistency audit. Expected values are derived
from the smoothing formulas, never hardcoded magic numbers, and there
are no fragile cross-pick comparison asserts - every check is on the
computed score/probability/ordering invariant itself.

Audit areas:
  1. smoothed_rates self-consistency (monotone / bounded / symmetric /
     n=0 stable - property-style).
  2. pick/ban vs smoothed_rates (synergy ranks on the smoothed rate;
     the displayed wr_pct stays the raw observed rate).
  3. pick/ban vs itself (determinism, disjoint ban/pick, exclude is
     honored, STABLE tie-breaking).
  4. pick/ban vs the coach path (no divergent duplicate WR math; the
     coach is name-only and computes no rate that would contradict the
     route).
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import smoothed_rates as S
from dashboard import routes_pickban as RP


# ---------------------------------------------------------------------------
# 1. smoothed_rates self-consistency  (property-style invariants)
# ---------------------------------------------------------------------------
class SmoothedRatesInvariants(unittest.TestCase):
    """The shared primitive must be monotone, bounded in [0,1],
    win/loss symmetric, and stable (no div-by-zero, returns the prior)
    at n=0. Derived from the (w+a)/(g+2a) and n/(n+k) definitions."""

    def test_laplace_bounded_unit_interval(self):
        # 0 <= wins <= games  =>  rate in [a/(g+2a), (g+a)/(g+2a)]
        # which is a strict sub-interval of [0,1] for finite g.
        for games in range(0, 60):
            for wins in range(0, games + 1):
                r = S.laplace_rate(wins, games)
                self.assertGreaterEqual(r, 0.0)
                self.assertLessEqual(r, 1.0)

    def test_laplace_monotone_more_samples_closer_to_raw(self):
        # Fix a raw rate of 1.0 (all wins). The smoothed value is
        # (n+1)/(n+2): strictly increasing in n and -> 1.0. So a larger
        # all-wins sample is always rated higher than a smaller one
        # (the whole point of the s238 synergy change).
        prev = -1.0
        for n in range(0, 200):
            cur = S.laplace_rate(n, n)            # n wins / n games
            self.assertGreater(cur, prev)
            prev = cur
        # And the limit is the raw rate.
        self.assertAlmostEqual(S.laplace_rate(5000, 5000), 1.0, places=3)

    def test_laplace_monotone_for_zero_rate(self):
        # All losses: (0+1)/(n+2) is strictly DECREASING toward 0 - a
        # larger all-loss sample is rated lower (symmetric to all-wins).
        prev = 2.0
        for n in range(0, 200):
            cur = S.laplace_rate(0, n)
            self.assertLess(cur, prev)
            prev = cur

    def test_laplace_win_loss_symmetry(self):
        # laplace(w, g) and laplace(g-w, g) must be mirror images about
        # 0.5: r + r' == 1 exactly, for the default alpha. (Beta(a,a)
        # prior is symmetric.)
        for games in range(0, 50):
            for wins in range(0, games + 1):
                r = S.laplace_rate(wins, games)
                r_mirror = S.laplace_rate(games - wins, games)
                self.assertAlmostEqual(r + r_mirror, 1.0)

    def test_laplace_n0_returns_prior_no_zero_div(self):
        # games=0 -> exactly the 0.5 neutral prior, never a ZeroDivision.
        self.assertEqual(S.laplace_rate(0, 0), 0.5)
        # Larger symmetric alpha still lands on the prior at n=0.
        self.assertEqual(S.laplace_rate(0, 0, 7.5), 0.5)

    def test_laplace_shrinks_toward_half(self):
        # The smoothed rate is always strictly between the raw rate and
        # 0.5 (for 0 < raw < 1, games > 0) - i.e. it pulls toward 0.5.
        for wins, games in [(2, 2), (7, 8), (1, 4), (9, 11), (49, 50)]:
            raw = wins / games
            r = S.laplace_rate(wins, games)
            lo, hi = sorted((raw, 0.5))
            self.assertGreaterEqual(r, lo)
            self.assertLessEqual(r, hi)
            self.assertAlmostEqual(r, (wins + 1.0) / (games + 2.0))

    def test_laplace_alpha_strength_monotone(self):
        # Bigger alpha => stronger pull toward 0.5 => for a winning
        # record the rate is non-increasing in alpha.
        prev = 1.0
        for a in (0.25, 0.5, 1.0, 2.0, 5.0, 20.0):
            cur = S.laplace_rate(8, 10, a)
            self.assertLessEqual(cur, prev + 1e-12)
            prev = cur

    def test_shrink_bounded_and_monotone(self):
        prev = -1.0
        for n in range(0, 500):
            w = S.shrink(n)
            self.assertGreaterEqual(w, 0.0)
            self.assertLess(w, 1.0)               # n/(n+k) < 1 for k>0
            self.assertGreaterEqual(w, prev)
            prev = w

    def test_shrink_n0_is_zero_no_zero_div(self):
        self.assertEqual(S.shrink(0), 0.0)
        self.assertEqual(S.shrink(0, 0), 0.0)     # degenerate denom -> 0

    def test_blend_is_convex_bounded(self):
        # weight in [0,1] (shrink output) => blend stays within
        # [min(own,prior), max(own,prior)].
        for n in range(0, 80):
            w = S.shrink(n)
            v = S.blend(0.83, 0.21, w)
            self.assertGreaterEqual(v, 0.21 - 1e-12)
            self.assertLessEqual(v, 0.83 + 1e-12)

    def test_blend_endpoints_exact(self):
        self.assertAlmostEqual(S.blend(0.9, 0.4, 0.0), 0.4)
        self.assertAlmostEqual(S.blend(0.9, 0.4, 1.0), 0.9)


# ---------------------------------------------------------------------------
# Shared in-memory rewind_history.db builder for the route tests.
# ---------------------------------------------------------------------------
def _build_db(path: Path, rows: list[dict], with_ts: bool = False) -> None:
    conn = sqlite3.connect(str(path))
    if with_ts:
        conn.executescript("""
            CREATE TABLE matches (match_id TEXT PRIMARY KEY,
                                  queue_id INTEGER,
                                  game_creation_ts INTEGER);
            CREATE TABLE participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT, puuid TEXT, team_id INTEGER,
                team_position TEXT, champion_id INTEGER,
                champion_name TEXT, win INTEGER);
        """)
    else:
        conn.executescript("""
            CREATE TABLE matches (match_id TEXT PRIMARY KEY,
                                  queue_id INTEGER);
            CREATE TABLE participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT, puuid TEXT, team_id INTEGER,
                team_position TEXT, champion_id INTEGER,
                champion_name TEXT, win INTEGER);
        """)
    seen = set()
    for r in rows:
        mid = r["match_id"]
        if mid not in seen:
            if with_ts:
                conn.execute(
                    "INSERT INTO matches(match_id,queue_id,game_creation_ts)"
                    " VALUES (?,?,?)",
                    (mid, r.get("queue_id", 420), r.get("ts", 0)))
            else:
                conn.execute(
                    "INSERT INTO matches(match_id,queue_id) VALUES (?,?)",
                    (mid, r.get("queue_id", 420)))
            seen.add(mid)
        conn.execute(
            "INSERT INTO participants(match_id,puuid,team_id,team_position,"
            "champion_id,champion_name,win) VALUES (?,?,?,?,?,?,?)",
            (mid, r["puuid"], r.get("team_id", 100), r["team_position"],
             r["champion_id"], r["champion_name"], r["win"]))
    conn.commit()
    conn.close()


class _DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = Path(self._tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 2. pick/ban  vs  smoothed_rates
# ---------------------------------------------------------------------------
class PickBanConsumesSmoothedRate(_DbCase):
    """The synergy mood (the CLAUDE.md #90 locked example of a raw
    recent-form proxy) must rank on core.smoothed_rates.laplace_rate,
    not the raw ratio. The displayed wr_pct stays RAW."""

    def test_rank_helper_matches_laplace_formula_exactly(self):
        # Two records; the ranking key must be exactly laplace_rate, so
        # a smaller perfect record can lose to a larger strong one.
        rows = [(99, "Lux", 2, 2), (81, "Ezreal", 8, 7)]
        ranked = RP._rank_by_smoothed_wr(rows, "x", top=5)
        # Derive expectation purely from the primitive.
        lux_s = S.laplace_rate(2, 2)        # 0.75
        ez_s = S.laplace_rate(7, 8)         # 0.80
        self.assertGreater(ez_s, lux_s)
        self.assertEqual([r["champName"] for r in ranked], ["Ezreal", "Lux"])
        # Displayed wr_pct is the RAW observed rate, not the smoothed one.
        self.assertEqual(ranked[0]["wr_pct"], round(100 * 7 / 8))
        self.assertEqual(ranked[1]["wr_pct"], 100)

    def test_synergy_allies_path_orders_by_smoothed(self):
        # Operator BOT alongside Lulu(117). Raw would rank the 2-0 Lux
        # over the 7-1 Ezreal; smoothed must invert that.
        rows = []
        for i in range(2):
            rows += [
                {"match_id": f"x{i}", "puuid": "me", "team_id": 100,
                 "team_position": "BOTTOM", "champion_id": 99,
                 "champion_name": "Lux", "win": 1},
                {"match_id": f"x{i}", "puuid": "lp", "team_id": 100,
                 "team_position": "UTILITY", "champion_id": 117,
                 "champion_name": "Lulu", "win": 1}]
        for i in range(8):
            w = 1 if i < 7 else 0
            rows += [
                {"match_id": f"e{i}", "puuid": "me", "team_id": 100,
                 "team_position": "BOTTOM", "champion_id": 81,
                 "champion_name": "Ezreal", "win": w},
                {"match_id": f"e{i}", "puuid": "lp", "team_id": 100,
                 "team_position": "UTILITY", "champion_id": 117,
                 "champion_name": "Lulu", "win": w}]
        _build_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            picks = RP._query_performance(conn, "me", "BOTTOM", (420,),
                                          mood="synergy", top=3,
                                          ally_ids=(117,))
        finally:
            conn.close()
        self.assertEqual(picks[0]["champName"], "Ezreal")
        self.assertEqual(picks[0]["wr_pct"], round(100 * 7 / 8))  # raw
        self.assertIn("smoothed", picks[0]["reason"])


# ---------------------------------------------------------------------------
# 3. pick/ban  vs  itself  (determinism, disjointness, exclude, ties)
# ---------------------------------------------------------------------------
class PickBanSelfConsistency(_DbCase):

    def _bot_rows(self):
        # Vayne 5/5, Caitlyn 6/8, Jinx 4/6 at BOT; plus an enemy Darius
        # the operator loses to (for the ban side).
        rows = []
        for i in range(5):
            rows.append({"match_id": f"v{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne",
                         "win": 1})
        for i in range(8):
            rows.append({"match_id": f"c{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 51, "champion_name": "Caitlyn",
                         "win": 1 if i < 6 else 0})
        for i in range(6):
            rows.append({"match_id": f"j{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 222, "champion_name": "Jinx",
                         "win": 1 if i < 4 else 0})
        # Enemy Darius BOT, operator loses 3/3 (ban candidate).
        for i in range(3):
            rows.append({"match_id": f"d{i}", "puuid": "me",
                         "team_id": 100, "team_position": "BOTTOM",
                         "champion_id": 67, "champion_name": "Vayne",
                         "win": 0})
            rows.append({"match_id": f"d{i}", "puuid": "en",
                         "team_id": 200, "team_position": "BOTTOM",
                         "champion_id": 122, "champion_name": "Darius",
                         "win": 1})
        return rows

    def test_repeated_calls_are_deterministic(self):
        _build_db(self.db_path, self._bot_rows())
        conn = sqlite3.connect(str(self.db_path))
        try:
            runs = [
                [p["champId"] for p in RP._query_performance(
                    conn, "me", "BOTTOM", (420,), mood="comfort", top=5)]
                for _ in range(8)]
            bans = [
                [b["champId"] for b in RP._query_bans(
                    conn, "me", "BOTTOM", (420,))]
                for _ in range(8)]
        finally:
            conn.close()
        self.assertTrue(all(r == runs[0] for r in runs), runs)
        self.assertTrue(all(b == bans[0] for b in bans), bans)

    def test_tie_breaking_is_stable_by_champ_id(self):
        # Three champs with IDENTICAL raw WR and IDENTICAL game count:
        # the only thing that can order them deterministically is a
        # champion_id tertiary key. Build with reversed champ_id vs
        # name so an unstable sort would surface.
        rows = []
        for cid, nm in [(300, "Cassiopeia"), (100, "Annie"),
                        (200, "Brand")]:
            for i in range(4):
                rows.append({"match_id": f"{cid}-{i}", "puuid": "me",
                             "team_id": 100, "team_position": "MIDDLE",
                             "champion_id": cid, "champion_name": nm,
                             "win": 1 if i < 3 else 0})  # all 3/4 = 75%
        _build_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ids = [p["champId"] for p in RP._query_performance(
                conn, "me", "MIDDLE", (420,), mood="comfort", top=5)]
        finally:
            conn.close()
        # All tied on (wr, games); a stable contract orders by champ_id
        # ascending (matches the deliberate _rank_by_smoothed_wr
        # tertiary). Without it SQLite ORDER BY ties are undefined.
        self.assertEqual(ids, sorted(ids),
                         "comfort tie order is not champ_id-stable")

    def test_bans_tie_breaking_is_stable_by_champ_id(self):
        # Two enemies, identical loss-rate (100%) and identical
        # encounter count -> must order by enemy champion_id ascending.
        rows = []
        for cid in (500, 300):       # reversed vs ascending
            for i in range(3):
                rows.append({"match_id": f"{cid}-{i}", "puuid": "me",
                             "team_id": 100, "team_position": "TOP",
                             "champion_id": 86, "champion_name": "Garen",
                             "win": 0})
                rows.append({"match_id": f"{cid}-{i}", "puuid": "en",
                             "team_id": 200, "team_position": "TOP",
                             "champion_id": cid, "champion_name": f"E{cid}",
                             "win": 1})
        _build_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ids = [b["champId"] for b in RP._query_bans(
                conn, "me", "TOP", (420,))]
        finally:
            conn.close()
        self.assertEqual(ids, sorted(ids),
                         "ban tie order is not champ_id-stable")

    def test_new_mood_tie_breaking_is_stable(self):
        # Two never-played champs with identical pool_games -> must be
        # champ_id-stable too.
        rows = []
        for cid in (700, 400):
            for i in range(4):
                rows.append({"match_id": f"{cid}-{i}", "puuid": "other",
                             "team_id": 100, "team_position": "JUNGLE",
                             "champion_id": cid, "champion_name": f"P{cid}",
                             "win": 1})
        # operator has played a different champ at JUNGLE so the
        # NOT-IN exclusion does not blank the pool.
        rows.append({"match_id": "op", "puuid": "me", "team_id": 100,
                     "team_position": "JUNGLE", "champion_id": 64,
                     "champion_name": "LeeSin", "win": 1})
        _build_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ids = [p["champId"] for p in RP._query_performance(
                conn, "me", "JUNGLE", (420,), mood="new", top=5)]
        finally:
            conn.close()
        self.assertEqual(ids, sorted(ids),
                         "new-mood tie order is not champ_id-stable")

    def test_pick_and_ban_lists_are_disjoint_for_excluded(self):
        # Caller passes the already-banned set as exclude_ids; the pick
        # list must never re-suggest a banned champion. (The route does
        # this; we assert the contract at the query layer.)
        _build_db(self.db_path, self._bot_rows())
        conn = sqlite3.connect(str(self.db_path))
        try:
            # Ban Vayne(67); picks must exclude it.
            picks = RP._query_performance(conn, "me", "BOTTOM", (420,),
                                          mood="comfort",
                                          exclude_ids=(67,), top=5)
        finally:
            conn.close()
        pick_ids = {p["champId"] for p in picks}
        self.assertNotIn(67, pick_ids)
        self.assertTrue(pick_ids)               # other champs remain

    def test_excluded_champion_never_resuggested_any_mood(self):
        # with_ts=True: the synergy ally_ids=() branch joins on
        # matches.game_creation_ts, which the real rewind_history.db
        # schema has. Build it so all four moods are exercised.
        rows = self._bot_rows()
        for r in rows:
            r["ts"] = 1  # any non-zero ts; recency not under test here
        _build_db(self.db_path, rows, with_ts=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            for mood in ("comfort", "limit", "new", "synergy"):
                picks = RP._query_performance(
                    conn, "me", "BOTTOM", (420,), mood=mood,
                    exclude_ids=(67, 51, 222), top=5, ally_ids=())
                ids = {p["champId"] for p in picks}
                self.assertFalse(ids & {67, 51, 222},
                                 f"{mood} leaked an excluded id: {ids}")
        finally:
            conn.close()

    def test_empty_history_no_zero_division(self):
        # Empty DB - every query must return [] (or a 0-game entry for
        # the personal-record helpers), never raise ZeroDivision.
        # with_ts=True so the synergy fallback's game_creation_ts JOIN
        # resolves against the real schema even with zero rows.
        _build_db(self.db_path, [], with_ts=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            for mood in ("comfort", "limit", "new", "synergy"):
                self.assertEqual(
                    RP._query_performance(conn, "nobody", "TOP", (420,),
                                          mood=mood, ally_ids=()), [])
            self.assertEqual(RP._query_bans(conn, "nobody", "TOP",
                                            (420,)), [])
            self.assertIsNone(RP._query_champ_record(
                conn, "nobody", 1, (420,)))
            wa = RP._query_with_ally(conn, "nobody", 1, (420,))
            self.assertEqual(wa["games"], 0)
            self.assertEqual(wa["wr_pct"], 0)        # no /0
            ve = RP._query_vs_enemy(conn, "nobody", 1, (420,))
            self.assertEqual(ve["games"], 0)
            self.assertEqual(ve["wr_pct"], 0)
        finally:
            conn.close()

    def test_exclude_clause_is_noop_when_empty(self):
        frag, params = RP._exclude_clause(())
        self.assertEqual(params, ())
        self.assertNotIn("champion_id", frag)        # safe to .replace()
        frag2, params2 = RP._exclude_clause((1, 2))
        self.assertIn("champion_id NOT IN", frag2)
        self.assertEqual(params2, (1, 2))


# ---------------------------------------------------------------------------
# 4. pick/ban  vs  the coach path
# ---------------------------------------------------------------------------
class CoachPathAgreement(unittest.TestCase):
    """The champ-select coach is a name-only Haiku call; it must NOT
    compute its own win-rate that could contradict the route's smoothed
    numbers. This pins that separation so a future edit that adds a
    divergent WR calc to the coach trips the test."""

    def test_coach_pick_computes_no_winrate(self):
        import inspect
        from coaches import champ_select_coach as C
        src = inspect.getsource(C)
        # The coach must not import or call the rate primitive, nor open
        # rewind_history.db - it is purely the LLM situational layer.
        self.assertNotIn("smoothed_rates", src)
        self.assertNotIn("laplace_rate", src)
        self.assertNotIn("rewind_history", src)

    def test_coach_pick_safe_without_champion_or_key(self):
        from coaches.champ_select_coach import coach_pick
        out = coach_pick({}, "sk-ant-fake")
        self.assertFalse(out["ok"])
        self.assertIn("no champion", out["advice"].lower())
        out2 = coach_pick({"my_champion": "Ahri"}, None)
        self.assertFalse(out2["ok"])
        self.assertIn("api key", out2["advice"].lower())

    def test_brief_via_coach_has_no_divergent_rate_math(self):
        import inspect
        from dashboard import _champ_select as CS
        src = inspect.getsource(CS)
        self.assertNotIn("laplace_rate", src)
        self.assertNotIn("rewind_history", src)


if __name__ == "__main__":
    unittest.main()
