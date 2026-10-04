"""RM-610 (directive X-10, external reference A): cross-builder win-rate
denominator consistency guard.

Every builder that computes the OPERATOR'S personal win rate from game
rows is fed ONE synthetic fixture - a win, a loss, a remake and an
unknown-result game - and must report the identical resolved WR: 1 win
over 2 resolved games = 50 percent. The wrong denominators this fixture
exposes:

    total games (4) ............... 25
    decided incl. the remake (3) .. 33
    unknown read as a loss (3) .... 33
    remake or unknown read as win . 66 / 75
    zero-guard slip ............... NaN / ZeroDivisionError

The builder list is ANCHORED by a scan of the source:

  * the set of modules that call ``resolved_wr(`` must equal the set of
    modules registered in BUILDERS (an empty or stale list fails);
  * every hand-written division whose NUMERATOR mentions a win
    (``wins / n``, ``100.0 * wins / total``, ``sum(g["win"] ...) /
    len(rows)``, ``cell.wins_x / cell.n``) anywhere in core/, coaches/,
    dashboard/, lcu/ and app/ must sit in a module listed in EXEMPT with
    the reason it is not a personal row-based WR. The scan is an AST walk,
    so docstrings and comments never match and any expression shape does.
    A new unrouted site, or a stale exemption, fails. A planted
    ``sum(g["win"]) / len(rows)`` module is scanned every run to prove the
    anchor catches the shape that once escaped it.

POSITIVE CONTROL (runs every time): each routed module's ``resolved_wr``
name is monkeypatched with a variant that divides by TOTAL games. The
same assertion must then go RED for every builder. That also proves each
builder really computes through the helper - a builder that bypassed it
would stay at its own value and the control would fail.

Synthetic, name-scrubbed fixture only. ASCII-only authored content.
"""
from __future__ import annotations

import ast
import importlib
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
            tracked_assists INTEGER, has_stats INTEGER, map_id INTEGER);
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
            puuid TEXT, team_id INTEGER, champion_id INTEGER,
            champion_name TEXT, win INTEGER,
            game_ended_in_early_surrender INTEGER,
            total_minions_killed INTEGER, neutral_minions_killed INTEGER,
            vision_score INTEGER, gold_earned INTEGER,
            total_damage_dealt_to_champs INTEGER, deaths INTEGER,
            kills INTEGER, assists INTEGER, dragon_kills INTEGER,
            baron_kills INTEGER, turret_takedowns INTEGER,
            inhibitor_takedowns INTEGER);
        CREATE TABLE teams (match_id TEXT, team_id INTEGER, win INTEGER);
    """)
    part_sql = ("INSERT INTO participants (match_id, puuid, team_id,"
                " champion_id, champion_name, win,"
                " game_ended_in_early_surrender, total_minions_killed,"
                " neutral_minions_killed, vision_score, gold_earned,"
                " total_damage_dealt_to_champs, deaths, kills, assists,"
                " dragon_kills, baron_kills, turret_takedowns,"
                " inhibitor_takedowns)"
                " VALUES (?,?,?,?,?,?,0,150,10,20,10000,15000,3,5,7,1,0,1,0)")
    for i, (mid, win, dur) in enumerate(FIXTURE):
        enemy_win = None if win is None else 1 - win
        c.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,11)",
                  (mid, QUEUE, "CLASSIC", dur, _T0 + i, MY_CHAMP_ID,
                   MY_CHAMP, 100, win, 5, 3, 7))
        c.execute(part_sql, (mid, ME, 100, MY_CHAMP_ID, MY_CHAMP, win))
        c.execute(part_sql, (mid, f"SYNTH-PUUID-E{i}", 200, ENEMY_CHAMP_ID,
                             ENEMY_CHAMP, enemy_win))
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


def _run_player_gpi(td: Path) -> float:
    """Home snapshot winrate tile source (routes_player_snapshot reads
    compute_gpi()['win_rate'])."""
    from core import player_gpi as G
    db = td / "rewind_history.db"
    _make_rewind(db)
    c = sqlite3.connect(str(db))
    try:
        with mock.patch.object(G, "MIN_GAMES", 1):
            out = G.compute_gpi(mode="sr", conn=c)
    finally:
        c.close()
    return round(100.0 * float(out["win_rate"]), 1)


# module path -> {builder label: runner}. A module listed here MUST call
# resolved_wr( and every module that calls it MUST be listed here.
BUILDERS = {
    "coaches/champ_pool_recommender.py": {
        "champ_pool_recommender.recommend": _run_champ_pool},
    "core/player_gpi.py": {
        "player_gpi.compute_gpi.win_rate": _run_player_gpi},
    "dashboard/builders.py": {
        "builders._compute_last20": _run_last20,
        "builders._build_history.season_stats": _run_history_season},
    "dashboard/routes_personal_vs.py": {
        "routes_personal_vs._query_personal_vs": _run_personal_vs},
}

# Hand-written win divisions that are NOT a personal row-based WR, each
# with the probe reason (RM-610). A module here that no longer matches
# the scan is a stale exemption and fails.
EXEMPT = {
    "coaches/adaptation_hint_digest.py":
        "averages per-bucket win_rate values (a mean of rates), no rows",
    "coaches/adaptation_hint_session.py":
        "per-mode session DBs; already wins/(wins+losses) so unknown is "
        "excluded; body pinned byte-verbatim by the test_round suite; "
        "remakes NOT filtered (follow-up)",
    "coaches/adaptation_hint_temporal.py":
        "time-of-day / weekday / duration buckets over session DBs; "
        "already wins/(wins+losses); remakes NOT filtered (follow-up)",
    "core/aram_item_interaction.py":
        "population item-interaction cells, not a personal WR",
    "core/ds_calibration_agreement.py":
        "DS followed-vs-unfollowed calibration cells, an analysis metric "
        "not a displayed personal WR",
    "core/duration_winrate.py":
        "duration-bucket curve; already drops game_duration_s < 300",
    "core/lcu_ranked.py":
        "LCU ranked wins/losses counters, no per-game rows",
    "core/op_score_curve.py":
        "per-minute mean score of winning games (win_sum / win count), "
        "not a win rate",
    "core/perf_curve.py":
        "per-minute mean stat of winning games (win_sum / win count), "
        "not a win rate",
    "core/personal_build_wr.py":
        "per-build lift baseline; already drops game_duration_s < 300",
    "core/riot_api.py":
        "summarize_recent scouts OTHER roster players (team context), not "
        "the operator; counts unknown as loss (follow-up)",
    "core/smoothed_rates.py":
        "the Laplace smoothing primitive ((wins + alpha) / denom), takes "
        "counts not rows",
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
_SELF = "core/resolved_wr.py"
# Identifier parts that mean "a win": wins, n_wins, win_sum, tracked_win,
# won ... but not swing / window / winsorize.
_WIN_PART = re.compile(r"^(wins?|won|lw)$|^win(s)?_|_wins?$|^wins?\d", re.I)
_HELPERS = {"resolved_wr", "wr_pct", "display_pct"}
_HELPER_CALL = re.compile(r"\bresolved_wr\s*\(")


def _is_win_ident(name: str) -> bool:
    return any(_WIN_PART.search(part) for part in
               [name] + name.split("_"))


def _mentions_win(node: ast.AST) -> bool:
    """True when *node* reads a win: a win-named variable / attribute, or
    a subscript keyed by a win-named string (g["win"], r["tracked_win"]).
    Calls to the helper itself are skipped - their result is resolved."""
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name in _HELPERS:
                continue
        if isinstance(n, ast.Name) and _is_win_ident(n.id):
            return True
        if isinstance(n, ast.Attribute) and _is_win_ident(n.attr):
            return True
        if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and isinstance(n.slice.value, str)
                and _is_win_ident(n.slice.value)):
            return True
        stack.extend(ast.iter_child_nodes(n))
    return False


def _win_divisions(source: str) -> list[int]:
    """Line numbers of every ``a / b`` whose numerator reads a win."""
    out = []
    for n in ast.walk(ast.parse(source)):
        if (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
                and _mentions_win(n.left)):
            out.append(n.lineno)
    return out


def _source_files():
    for d in _SCAN_DIRS:
        for p in sorted((_PROJECT_ROOT / d).rglob("*.py")):
            yield p.relative_to(_PROJECT_ROOT).as_posix(), p


def _division_sites() -> set[str]:
    hits = set()
    for rel, p in _source_files():
        if rel == _SELF:
            continue
        if _win_divisions(p.read_text(encoding="utf-8")):
            hits.add(rel)
    return hits


def _helper_callers() -> set[str]:
    hits = set()
    for rel, p in _source_files():
        if rel == _SELF:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if _HELPER_CALL.search(line):
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


_PLANTED = (
    'def personal_wr(rows):\n'
    '    return sum(g["win"] for g in rows) / len(rows)\n'
)


class GrepAnchorTests(unittest.TestCase):

    def test_builder_list_not_empty(self):
        self.assertTrue(list(_all_runners()))

    def test_helper_callers_equal_builder_list(self):
        callers = _helper_callers()
        self.assertTrue(callers, "scan found no resolved_wr( caller")
        self.assertEqual(callers, set(BUILDERS),
                         "routed-module list is stale or a new caller is "
                         "unregistered")

    def test_raw_wr_divisions_are_all_exempted(self):
        hits = _division_sites()
        self.assertTrue(hits, "WR-division scan matched nothing - the "
                              "anchor is broken")
        unrouted = hits - set(EXEMPT)
        self.assertFalse(unrouted,
                         f"raw WR division outside the helper: {unrouted}")
        stale = set(EXEMPT) - hits
        self.assertFalse(stale, f"stale exemptions: {stale}")
        self.assertFalse(hits & set(BUILDERS),
                         "a routed module still divides by hand")

    def test_anchor_catches_planted_shapes(self):
        for src in (
                _PLANTED,
                "x = wins / total\n",
                "x = 100.0 * won / n\n",
                "x = sum(r['tracked_win'] for r in rows) / len(rows)\n",
                "x = round(cell.wins_followed / cell.n, 1)\n",
                "x = sum(1 for g in s if g['win']) / max(len(s), 1)\n"):
            with self.subTest(src=src):
                self.assertTrue(_win_divisions(src), src)
        for src in (
                "x = cell.sum_swing / cell.n_swing\n",
                "x = window / 2\n",
                "x = (wr_pct(wins, n, None) or 0.0) / 100.0\n",
                '"""wins / total in prose"""\n',
                "# wins / total\n"):
            with self.subTest(clean=src):
                self.assertFalse(_win_divisions(src), src)

    def test_planted_scratch_module_fails_the_anchor(self):
        """A module carrying the shape that once escaped the anchor is
        written to a scratch tree and scanned like the real one."""
        with TemporaryDirectory() as td:
            scratch = Path(td) / "core"
            scratch.mkdir()
            (scratch / "planted_wr.py").write_text(_PLANTED, encoding="utf-8")
            hits = set()
            for p in scratch.rglob("*.py"):
                if _win_divisions(p.read_text(encoding="utf-8")):
                    hits.add("core/" + p.name)
        self.assertEqual(hits, {"core/planted_wr.py"})
        self.assertFalse(hits <= set(EXEMPT))


class ConsistencyTests(unittest.TestCase):

    def test_every_builder_reports_identical_resolved_wr(self):
        results = {label: _measure(fn) for _m, label, fn in _all_runners()}
        self.assertEqual(len(results), 5, results)
        self.assertEqual(_inconsistent(results), [], results)
        self.assertEqual(len(set(results.values())), 1, results)

    def test_positive_control_total_games_goes_red(self):
        """Every builder, with its module's resolved_wr swapped for a
        divide-by-total variant, must move off 50 and fail the check (25
        over all four games; 33.3 where the builder's SQL never selects
        the unknown-result row or already drops the remake)."""
        for mod, label, fn in _all_runners():
            module = importlib.import_module(mod[:-3].replace("/", "."))
            with self.subTest(builder=label):
                clean = _measure(fn)
                with mock.patch.object(module, "resolved_wr",
                                       _total_games_variant):
                    got = _measure(fn)
                # The swap must MOVE the number: a builder whose reported
                # rate does not depend on the helper bypasses it, even if
                # it happens to call it somewhere.
                self.assertNotEqual(got, clean,
                                    f"{label} bypasses the helper")
                self.assertIn(got, (25.0, 33.3), label)
                self.assertEqual(len(_inconsistent({label: got})), 1)


if __name__ == "__main__":
    unittest.main()
