"""RM-610 (directive X-10, external reference A): cross-builder win-rate
denominator consistency guard.

Every builder that computes the OPERATOR'S personal win rate from game
rows is fed ONE synthetic fixture - a win, a loss, a remake and an
unknown-result game - and must report the identical resolved WR: 1 win
over 2 resolved games = 50 percent. The wrong denominators this fixture
exposes:

    total games (4) ............... 25
    decided incl. the remake (3) .. 33
    remake or unknown read as win . 66 / 75
    zero-guard slip ............... NaN / ZeroDivisionError

The builder list is ANCHORED by a grep over the source:

  * the set of modules that call ``resolved_wr(`` must equal the set of
    modules registered in BUILDERS (an empty or stale list fails);
  * every raw win-rate division left in core/, coaches/, dashboard/,
    lcu/ and app/ must be listed in EXEMPT with the reason it is not a
    personal row-based WR (a new unrouted site, or a stale exemption,
    fails).

POSITIVE CONTROL (runs every time): each routed module's ``resolved_wr``
name is monkeypatched with a variant that divides by TOTAL games. The
same assertion must then go RED for every builder. That also proves each
builder really computes through the helper - a builder that bypassed it
would stay at its own value and the control would fail.

Synthetic, name-scrubbed fixture only. ASCII-only authored content.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import resolved_wr as RW  # noqa: E402

EXPECTED_WR = 50.0

ME = "SYNTH-PUUID-ME"
MY_CHAMP_ID, MY_CHAMP = 1, "Annie"
ENEMY_CHAMP_ID, ENEMY_CHAMP = 2, "Olaf"
QUEUE = 420
_T0 = 1_900_000_000_000  # epoch ms, far future so any day window keeps it

# (match_id, win, game_duration_s). Remake is a LOSS on purpose: with a
# win flag a total-games mutation would read 2/4 = 50 and hide.
FIXTURE = (
    ("SYN_1", 1, 1800),     # win
    ("SYN_2", 0, 1700),     # loss
    ("SYN_3", 0, 200),      # remake (< REMAKE_MAX_SECONDS)
    ("SYN_4", None, 1600),  # unknown result
)


def _make_rewind(path: Path) -> None:
    """A rewind_history.db subset carrying every column the routed
    builders read. The operator plays MY_CHAMP on team 100 against
    ENEMY_CHAMP on team 200 in all four games."""
    c = sqlite3.connect(str(path))
    c.executescript("""
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY, queue_id INTEGER, game_mode TEXT,
            game_duration_s INTEGER, game_creation_ts INTEGER,
            tracked_champion_id INTEGER, tracked_champion_name TEXT,
            tracked_team_id INTEGER, tracked_win INTEGER,
            tracked_kills INTEGER, tracked_deaths INTEGER,
            tracked_assists INTEGER);
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
            puuid TEXT, team_id INTEGER, champion_id INTEGER,
            champion_name TEXT, win INTEGER,
            game_ended_in_early_surrender INTEGER);
        CREATE TABLE teams (match_id TEXT, team_id INTEGER, win INTEGER);
    """)
    for i, (mid, win, dur) in enumerate(FIXTURE):
        enemy_win = None if win is None else 1 - win
        c.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, QUEUE, "CLASSIC", dur, _T0 + i, MY_CHAMP_ID,
                   MY_CHAMP, 100, win, 5, 3, 7))
        c.execute("INSERT INTO participants (match_id, puuid, team_id,"
                  " champion_id, champion_name, win,"
                  " game_ended_in_early_surrender) VALUES (?,?,?,?,?,?,?)",
                  (mid, ME, 100, MY_CHAMP_ID, MY_CHAMP, win, 0))
        c.execute("INSERT INTO participants (match_id, puuid, team_id,"
                  " champion_id, champion_name, win,"
                  " game_ended_in_early_surrender) VALUES (?,?,?,?,?,?,?)",
                  (mid, f"SYNTH-PUUID-E{i}", 200, ENEMY_CHAMP_ID,
                   ENEMY_CHAMP, enemy_win, 0))
        c.execute("INSERT INTO teams VALUES (?,?,?)", (mid, 100, win))
        c.execute("INSERT INTO teams VALUES (?,?,?)", (mid, 200, enemy_win))
    c.commit()
    c.close()


def _make_match_history(path: Path) -> None:
    c = sqlite3.connect(str(path))
    c.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  game_time_s INTEGER, kills INTEGER, deaths INTEGER,"
        "  assists INTEGER, cs INTEGER, cs_per_min REAL,"
        "  gold INTEGER, gold_per_min REAL, kda_str TEXT, kp_pct REAL,"
        "  label TEXT, raw_data TEXT, game_id INTEGER DEFAULT 0)")
    c.commit()
    c.close()


def _evict(*paths: Path) -> None:
    from dashboard import _context
    conns = getattr(_context.DB_CONN_LOCAL, "conns", {})
    for p in paths:
        cached = conns.pop(str(p), None)
        if cached is not None:
            cached.close()


# -- builder runners: each returns the WR percent the builder reports ----

def _run_champ_pool(td: Path) -> float:
    from coaches import champ_pool_recommender as M
    db = td / "rewind_history.db"
    _make_rewind(db)
    with mock.patch.object(M, "_REWIND_DB", db), \
            mock.patch.object(M, "_user_puuid", None), \
            mock.patch.object(M, "_name_to_id", {MY_CHAMP.lower(): MY_CHAMP_ID}), \
            mock.patch.object(M, "_id_to_name", {MY_CHAMP_ID: MY_CHAMP}), \
            mock.patch.object(M, "_kda_for", lambda *a: (0, 0, 0, 0)):
        out = M.recommend([MY_CHAMP], [ENEMY_CHAMP], min_games=99)
    assert len(out) == 1, out
    return float(out[0]["win_pct"])


def _run_last20(td: Path) -> float:
    from dashboard import builders as B
    db = td / "rewind_history.db"
    _make_rewind(db)
    c = sqlite3.connect(str(db))
    try:
        out = B._compute_last20(c)
    finally:
        c.close()
    return float(out["win_rate"])


def _run_history_season(td: Path) -> float:
    from dashboard import builders as B
    (td / "data").mkdir()
    rw = td / "data" / "rewind_history.db"
    mh = td / "data" / "match_history.db"
    _make_rewind(rw)
    _make_match_history(mh)
    try:
        with mock.patch.object(B, "_APP_DIR", td):
            out = B._build_history("all")
    finally:
        _evict(rw, mh)
    return float(out["season_stats"]["win_rate"])


def _run_personal_vs(td: Path) -> float:
    from dashboard import routes_personal_vs as P
    db = td / "rewind_history.db"
    _make_rewind(db)
    c = sqlite3.connect(str(db))
    try:
        out = P._query_personal_vs(c, ME, ENEMY_CHAMP_ID, 0, (QUEUE,))
    finally:
        c.close()
    return float(out["wr_pct"])


# module path -> {builder label: runner}. A module listed here MUST call
# resolved_wr( and every module that calls it MUST be listed here.
BUILDERS = {
    "coaches/champ_pool_recommender.py": {
        "champ_pool_recommender.recommend": _run_champ_pool},
    "dashboard/builders.py": {
        "builders._compute_last20": _run_last20,
        "builders._build_history.season_stats": _run_history_season},
    "dashboard/routes_personal_vs.py": {
        "routes_personal_vs._query_personal_vs": _run_personal_vs},
}

# Raw win-rate divisions that are NOT a personal row-based WR, each with
# the probe reason (RM-610). A file here that no longer matches the grep
# is a stale exemption and fails.
EXEMPT = {
    "coaches/adaptation_hint_session.py":
        "per-mode session DBs; already wins/(wins+losses) so unknown is "
        "excluded; body pinned byte-verbatim by the test_round suite; "
        "remakes NOT filtered (follow-up)",
    "coaches/adaptation_hint_temporal.py":
        "time-of-day / weekday / duration buckets over session DBs; "
        "already wins/(wins+losses); remakes NOT filtered (follow-up)",
    "core/aram_item_interaction.py":
        "population item-interaction cells, not a personal WR",
    "core/draft_elo_db.py":
        "docstring only; solo/pair/matchup are population priors over all "
        "participants (Laplace-smoothed), not the operator's WR",
    "core/duration_winrate.py":
        "duration-bucket curve; already drops game_duration_s < 300",
    "core/lcu_ranked.py":
        "LCU ranked wins/losses counters, no per-game rows",
    "core/meta_crawl.py":
        "docstring only; meta crawl per-champion population rates",
    "core/personal_build_wr.py":
        "per-build lift baseline; already drops game_duration_s < 300",
    "core/riot_api.py":
        "summarize_recent scouts OTHER roster players (team context), not "
        "the operator; counts unknown as loss (follow-up)",
    "core/snowball_elasticity.py":
        "gold-diff checkpoint buckets; a remake never reaches the 10/15 "
        "min checkpoints",
    "dashboard/routes_adaptive_summoners.py":
        "spell-pair WR per champion over the player_stats table, not a "
        "personal WR",
    "dashboard/routes_scouting.py":
        "ranked entry wins/losses counters for scouted players",
}

_SCAN_DIRS = ("core", "coaches", "dashboard", "lcu", "app")
_WR_DIVISION = re.compile(
    r"\b(wins|lw|n_wins)\b\s*(\*\s*100(\.0)?\s*)?/(?!/)"
    r"|100(\.0)?\s*\*\s*(wins|lw|n_wins)\s*/"
    r"|\[\"wins\"\]\s*/")
_HELPER_CALL = re.compile(r"\bresolved_wr\s*\(")


def _source_files():
    for d in _SCAN_DIRS:
        for p in sorted((_PROJECT_ROOT / d).rglob("*.py")):
            yield p.relative_to(_PROJECT_ROOT).as_posix(), p


def _grep(pattern) -> set[str]:
    hits = set()
    for rel, p in _source_files():
        if rel == "core/resolved_wr.py":
            continue
        text = p.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                hits.add(rel)
                break
    return hits


def _all_runners():
    for mod, runners in BUILDERS.items():
        for label, fn in runners.items():
            yield mod, label, fn


def _measure(fn) -> float:
    with TemporaryDirectory() as td:
        return fn(Path(td))


def _inconsistent(results: dict) -> list[str]:
    """Builders whose WR is not exactly EXPECTED_WR (NaN included)."""
    return [f"{k}={v}" for k, v in results.items()
            if not (v == v) or abs(v - EXPECTED_WR) > 1e-9]


def _total_games_variant(rows):
    """Mutated helper: divides by TOTAL games instead of resolved."""
    rows = list(rows)
    wins, _resolved, _ = RW.resolved_wr(rows)
    total = len(rows)
    return wins, total, RW.display_pct(wins, total)


class GrepAnchorTests(unittest.TestCase):

    def test_builder_list_not_empty(self):
        self.assertTrue(list(_all_runners()))

    def test_helper_callers_equal_builder_list(self):
        callers = _grep(_HELPER_CALL)
        self.assertTrue(callers, "grep found no resolved_wr( caller")
        self.assertEqual(callers, set(BUILDERS),
                         "routed-module list is stale or a new caller is "
                         "unregistered")

    def test_raw_wr_divisions_are_all_exempted(self):
        hits = _grep(_WR_DIVISION)
        self.assertTrue(hits, "WR-division grep matched nothing - the "
                              "anchor regex is broken")
        unrouted = hits - set(EXEMPT)
        self.assertFalse(unrouted,
                         f"raw WR division outside the helper: {unrouted}")
        stale = set(EXEMPT) - hits
        self.assertFalse(stale, f"stale exemptions: {stale}")
        self.assertFalse(hits & set(BUILDERS),
                         "a routed module still divides by hand")


class ConsistencyTests(unittest.TestCase):

    def test_every_builder_reports_identical_resolved_wr(self):
        results = {label: _measure(fn) for _m, label, fn in _all_runners()}
        self.assertEqual(len(results), 4, results)
        self.assertEqual(_inconsistent(results), [], results)
        self.assertEqual(len(set(results.values())), 1, results)

    def test_positive_control_total_games_goes_red(self):
        """Every builder, with its module's resolved_wr swapped for a
        divide-by-total variant, must move off 50 and fail the check (25
        over all four games; 33.3 for the last-20 window, whose SQL never
        selects the unknown-result row)."""
        import importlib
        for mod, label, fn in _all_runners():
            module = importlib.import_module(
                mod[:-3].replace("/", "."))
            with self.subTest(builder=label):
                with mock.patch.object(module, "resolved_wr",
                                       _total_games_variant):
                    got = _measure(fn)
                self.assertIn(got, (25.0, 33.3),
                              f"{label} bypasses the helper")
                self.assertEqual(len(_inconsistent({label: got})), 1)


if __name__ == "__main__":
    unittest.main()
