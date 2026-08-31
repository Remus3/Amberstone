"""
tests/test_replay_history.py - lane 8 Headless-True-Audit, cycle 32.

`core/replay_history.py` is reached live from two dashboard routes
(`dashboard/routes_coach.py:71` list_matches, `:89` match_detail) and had
NO dedicated test file - selection criterion 4 (load-bearing and
untested) plus criterion 1 (it parses a payload RC did not author).

THE HEADLINE THIS FILE PINS. Riot never sends `itemId` on an ITEM_UNDO
timeline event; it sends `beforeId` / `afterId`. `scripts/rewind_scraper.py:567`
maps only `ev.get("itemId")`, so `timeline_events.item_id` is NULL for
every ITEM_UNDO row - MEASURED 28405 of 28405 in the live
`data/rewind_history.db`. The fold in `_build_inventory_at` guarded its
ITEM_UNDO branch on `and item`, so the branch was structurally dead and
had never once fired in production, while the module docstring claimed
"UNDO reverses the most-recent matching purchase".

Both directions were wrong, not just one. Over all 28405 live rows:
25917 carry beforeId (undo of a PURCHASE -> the item must be REMOVED,
and was wrongly left in) and 2488 carry afterId (undo of a SELL -> the
item must be RESTORED, and was wrongly left out).

The events are fully recoverable because the scraper also stores the
verbatim Riot event in `raw_json` and that column is NULL for 0 of the
28405 rows, so reading the fold from `raw_json` repairs every historical
row with no migration of the 1.87 GB database.

Fixtures here build a REAL sqlite database in the production schema and
select genuine `sqlite3.Row` objects, rather than hand-rolling stub rows
that could be shaped to the bug (`feedback_subagent_fixture_shaped_to_bug`).
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import replay_history as X


# Verbatim column subset of data/rewind_history.db that this module reads.
_SCHEMA = """
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY, queue_id INTEGER, game_mode TEXT,
    game_duration_s INTEGER, game_creation_ts INTEGER, patch TEXT,
    tracked_champion_id INTEGER);
CREATE TABLE participants (
    match_id TEXT, participant_id INTEGER, team_id INTEGER,
    champion_id INTEGER, champion_name TEXT, riot_id_game_name TEXT,
    summoner_name TEXT, summoner_level INTEGER);
CREATE TABLE teams (match_id TEXT, team_id INTEGER, win INTEGER);
CREATE TABLE timeline_frames (
    match_id TEXT, timestamp_ms INTEGER, participant_id INTEGER,
    level INTEGER, total_gold INTEGER, minions_killed INTEGER,
    jungle_minions INTEGER, pos_x INTEGER, pos_y INTEGER,
    total_dmg_done INTEGER, total_dmg_taken INTEGER);
CREATE TABLE timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
    timestamp_ms INTEGER, event_type TEXT, participant_id INTEGER,
    item_id INTEGER, killer_id INTEGER, victim_id INTEGER,
    assisting_ids_json TEXT, kill_pos_x INTEGER, kill_pos_y INTEGER,
    raw_json TEXT);
"""


def _build_db(path, *, matches, events=(), frames=(), parts=(), teams=()):
    c = sqlite3.connect(str(path))
    c.executescript(_SCHEMA)
    c.executemany("INSERT INTO matches VALUES (?,?,?,?,?,?,?)", matches)
    c.executemany("INSERT INTO participants VALUES (?,?,?,?,?,?,?,?)", parts)
    c.executemany("INSERT INTO teams VALUES (?,?,?)", teams)
    c.executemany("INSERT INTO timeline_frames VALUES (?,?,?,?,?,?,?,?,?,?,?)", frames)
    for ts, et, pid, item, raw in events:
        c.execute(
            "INSERT INTO timeline_events (match_id, timestamp_ms, event_type,"
            " participant_id, item_id, raw_json) VALUES (?,?,?,?,?,?)",
            ("M1", ts, et, pid, item, raw))
    c.commit()
    c.close()


def _item_events(db_path, match_id="M1"):
    """Select the item events exactly as match_detail() does, so the rows
    handed to the fold are real sqlite3.Row objects in production shape."""
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    try:
        return c.execute(
            "SELECT timestamp_ms, event_type, participant_id, item_id, raw_json"
            " FROM timeline_events WHERE match_id = ?"
            "   AND event_type IN ('ITEM_PURCHASED','ITEM_SOLD',"
            "                      'ITEM_DESTROYED','ITEM_UNDO')"
            " ORDER BY timestamp_ms, id", (match_id,)).fetchall()
    finally:
        c.close()


class ReplayHistoryTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "rewind_history.db"
        self._orig_db = X._REWIND_DB
        X._REWIND_DB = self.db
        # Module-global caches. The cycle-29 lesson: process-global state with
        # no isolation lets one test replay another's answer.
        X._MATCH_DETAIL_CACHE.clear()
        X._id_to_champ.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        X._REWIND_DB = self._orig_db
        X._MATCH_DETAIL_CACHE.clear()
        X._id_to_champ.clear()
        self._tmp.cleanup()


class TestItemUndoFold(ReplayHistoryTestBase):
    """The headline defect: ITEM_UNDO carries beforeId/afterId, never itemId."""

    def _fold(self, events):
        _build_db(self.db, matches=[("M1", 450, "ARAM", 900, 1, "16.15", 1)],
                  events=events)
        rows = _item_events(self.db)
        # Fold to a timestamp past every event.
        return X._build_inventory_at(rows, 10 ** 9)

    def test_undo_of_a_purchase_removes_the_item(self):
        """25917 of 28405 live rows. beforeId set, afterId 0: the player
        bought the item and took it back, so it must NOT be in inventory."""
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_PURCHASED", 1, 3340, None),
            (2500, "ITEM_UNDO", 1, None,
             json.dumps({"beforeId": 3340, "afterId": 0, "goldGain": 450})),
        ])
        self.assertEqual(inv.get(1), [1055],
                         "an undone purchase must not survive the fold")

    def test_undo_of_a_sell_restores_the_item(self):
        """2488 of 28405 live rows. beforeId 0, afterId set: the player sold
        the item and took the sale back, so it MUST be in inventory."""
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 3340, None),
            (2000, "ITEM_SOLD", 1, 3340, None),
            (2500, "ITEM_UNDO", 1, None,
             json.dumps({"beforeId": 0, "afterId": 3340, "goldGain": 0})),
        ])
        self.assertEqual(inv.get(1), [3340],
                         "an undone sale must restore the item")

    def test_undo_does_not_depend_on_the_always_null_item_id_column(self):
        """Characterization of the production shape: the scraper stores NULL
        in item_id for every ITEM_UNDO (28405/28405 measured). A fold that
        reads item_id is therefore a no-op, which is what shipped."""
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_UNDO", 1, None,
             json.dumps({"beforeId": 1055, "afterId": 0})),
        ])
        self.assertEqual(inv.get(1, []), [],
                         "the fold must work with item_id NULL, as production has it")

    def test_undo_removes_only_one_of_a_duplicated_item(self):
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (1500, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_UNDO", 1, None, json.dumps({"beforeId": 1055})),
        ])
        self.assertEqual(inv.get(1), [1055])

    def test_undo_with_unparseable_raw_json_is_ignored_not_fatal(self):
        """raw_json is written by a scraper; a malformed row must degrade to
        'no undo applied', never take down the whole match view."""
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_UNDO", 1, None, "{not json"),
        ])
        self.assertEqual(inv.get(1), [1055])

    def test_undo_with_null_raw_json_is_ignored_not_fatal(self):
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_UNDO", 1, None, None),
        ])
        self.assertEqual(inv.get(1), [1055])

    def test_undo_of_an_item_never_owned_is_a_no_op(self):
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_UNDO", 1, None, json.dumps({"beforeId": 9999})),
        ])
        self.assertEqual(inv.get(1), [1055])

    def test_undo_is_scoped_to_its_own_participant(self):
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (1100, "ITEM_PURCHASED", 2, 1055, None),
            (2000, "ITEM_UNDO", 1, None, json.dumps({"beforeId": 1055})),
        ])
        self.assertEqual(inv.get(1, []), [])
        self.assertEqual(inv.get(2), [1055], "another player's undo must not touch pid 2")

    def test_undo_with_a_null_participant_is_ignored(self):
        """Defensive guard: the live database has 0 item events with a NULL
        participant_id (measured), so nothing in the corpus exercises it.
        An unexercised guard is an untested guard."""
        inv = self._fold([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_UNDO", None, None, json.dumps({"beforeId": 1055})),
        ])
        self.assertEqual(inv.get(1), [1055])
        # Not just "no None key" - no falsy participant key at all. Coercing
        # the missing id to 0 instead of skipping the row invents a phantom
        # participant, and that mutant survived a weaker assertion.
        self.assertEqual([p for p in inv if not p], [])

    def test_events_after_the_cutoff_are_not_folded(self):
        """The fold is a point-in-time view; an undo later in the game must
        not retroactively edit an earlier minute's inventory."""
        _build_db(self.db, matches=[("M1", 450, "ARAM", 900, 1, "16.15", 1)],
                  events=[(1000, "ITEM_PURCHASED", 1, 1055, None),
                          (5000, "ITEM_UNDO", 1, None,
                           json.dumps({"beforeId": 1055}))])
        rows = _item_events(self.db)
        self.assertEqual(X._build_inventory_at(rows, 3000).get(1), [1055])
        self.assertEqual(X._build_inventory_at(rows, 6000).get(1, []), [])


class TestUndoThroughMatchDetail(ReplayHistoryTestBase):
    """End-to-end through the REAL consumer path.

    Every test in TestItemUndoFold calls `_build_inventory_at` with rows
    selected by the test helper, so none of them exercises the SELECT that
    `match_detail` actually issues. A mutation that dropped `raw_json` from
    that production query survived the whole suite - the fold silently fell
    back to the old broken behaviour and nothing was red. These tests close
    that path (`feedback_guard_on_nondefault_call_path_is_untested`)."""

    def _match(self, events):
        _build_db(
            self.db,
            matches=[("M1", 450, "ARAM", 900, 1, "16.15", None)],
            parts=[("M1", 1, 100, 1, "Annie", "gn", "sn", 30)],
            teams=[("M1", 100, 1)],
            frames=[("M1", 600000, 1, 5, 2000, 40, 0, 1, 1, 0, 0)],
            events=events)
        d = X.match_detail("M1")
        self.assertIsNotNone(d)
        return d["snapshots"][-1]["entries"][0]["items"]

    def test_match_detail_applies_an_undone_purchase(self):
        items = self._match([
            (1000, "ITEM_PURCHASED", 1, 1055, None),
            (2000, "ITEM_PURCHASED", 1, 3006, None),
            (2500, "ITEM_UNDO", 1, None, json.dumps({"beforeId": 3006})),
        ])
        self.assertEqual(items, [1055],
                         "match_detail must select raw_json and fold the undo")

    def test_match_detail_applies_an_undone_sale(self):
        items = self._match([
            (1000, "ITEM_PURCHASED", 1, 3006, None),
            (2000, "ITEM_SOLD", 1, 3006, None),
            (2500, "ITEM_UNDO", 1, None,
             json.dumps({"beforeId": 0, "afterId": 3006})),
        ])
        self.assertEqual(items, [3006])


class TestQueueFilter(ReplayHistoryTestBase):
    def test_queue_filter_zero_is_honoured(self):
        """queue_id 0 is a REAL queue (custom game) and `if queue_filter:`
        treats it as absent, silently returning every match instead."""
        _build_db(self.db, matches=[
            ("M1", 0,   "CLASSIC", 900, 3, "16.15", None),
            ("M2", 450, "ARAM",    900, 2, "16.15", None),
        ])
        out = X.list_matches(limit=10, queue_filter=0)
        self.assertEqual([m["match_id"] for m in out], ["M1"],
                         "queue_filter=0 must filter, not fall through to all rows")

    def test_queue_filter_none_returns_every_queue(self):
        _build_db(self.db, matches=[
            ("M1", 0,   "CLASSIC", 900, 3, "16.15", None),
            ("M2", 450, "ARAM",    900, 2, "16.15", None),
        ])
        self.assertEqual(len(X.list_matches(limit=10, queue_filter=None)), 2)


class TestLimitValidation(ReplayHistoryTestBase):
    def test_negative_limit_does_not_dump_the_whole_table(self):
        """SQLite treats LIMIT -1 as UNLIMITED (measured). list_matches also
        runs one extra join per row, so a negative limit is both a full-table
        read and an N+1 amplifier."""
        _build_db(self.db, matches=[
            (f"M{i}", 450, "ARAM", 900, i, "16.15", None) for i in range(5)])
        self.assertEqual(X.list_matches(limit=-1), [],
                         "a negative limit must not become 'unlimited'")

    def test_zero_limit_returns_nothing(self):
        _build_db(self.db, matches=[
            (f"M{i}", 450, "ARAM", 900, i, "16.15", None) for i in range(5)])
        self.assertEqual(X.list_matches(limit=0), [])


class TestFrameSampling(ReplayHistoryTestBase):
    def _match_with_frames(self, n):
        _build_db(
            self.db,
            matches=[("M1", 450, "ARAM", 60 * n, 1, "16.15", None)],
            parts=[("M1", 1, 100, 1, "Annie", "gn", "sn", 30)],
            teams=[("M1", 100, 1)],
            frames=[("M1", i * 60000, 1, 1, 500, 10, 0, 1, 1, 0, 0)
                    for i in range(n)])

    def test_sampling_keeps_the_final_frame(self):
        """With 90 frames capped at 60 the old sampler kept index 88 and
        dropped 89 - the scrubber lost the end of the game, which is the
        single most-looked-at moment of a match."""
        self._match_with_frames(90)
        d = X.match_detail("M1", max_frames=60)
        self.assertIsNotNone(d)
        self.assertEqual(len(d["snapshots"]), 60)
        self.assertEqual(d["snapshots"][-1]["timestamp_ms"], 89 * 60000,
                         "the last frame of the match must survive sampling")
        self.assertEqual(d["snapshots"][0]["timestamp_ms"], 0)

    def test_sampled_timestamps_are_strictly_increasing(self):
        self._match_with_frames(90)
        ts = [s["timestamp_ms"] for s in X.match_detail("M1", max_frames=60)["snapshots"]]
        self.assertEqual(ts, sorted(set(ts)), "sampling must not repeat or reorder frames")

    def test_under_the_cap_every_frame_is_kept(self):
        self._match_with_frames(53)  # the live corpus maxes at 53
        d = X.match_detail("M1", max_frames=60)
        self.assertEqual(len(d["snapshots"]), 53)

    def test_max_frames_below_one_does_not_raise(self):
        """max_frames=0 divided by zero. The route never passes max_frames
        today, so this is a latent crash on the public signature."""
        self._match_with_frames(10)
        d = X.match_detail("M1", max_frames=0)
        self.assertIsNotNone(d, "max_frames=0 must degrade, not ZeroDivisionError")
        self.assertGreaterEqual(len(d["snapshots"]), 1)


class TestCharacterization(ReplayHistoryTestBase):
    """Behaviour that was already correct, pinned before the rewrite."""

    def test_missing_database_degrades_to_empty(self):
        self.assertEqual(X.list_matches(), [])
        self.assertIsNone(X.match_detail("M1"))

    def test_unknown_match_returns_none(self):
        _build_db(self.db, matches=[("M1", 450, "ARAM", 900, 1, "16.15", None)])
        self.assertIsNone(X.match_detail("NOPE"))

    def test_list_matches_is_newest_first(self):
        _build_db(self.db, matches=[
            ("OLD", 450, "ARAM", 900, 100, "16.15", None),
            ("NEW", 450, "ARAM", 900, 900, "16.15", None),
        ])
        self.assertEqual([m["match_id"] for m in X.list_matches()], ["NEW", "OLD"])

    def test_match_detail_is_cached_by_match_and_frame_cap(self):
        _build_db(self.db,
                  matches=[("M1", 450, "ARAM", 900, 1, "16.15", None)],
                  parts=[("M1", 1, 100, 1, "Annie", "gn", "sn", 30)],
                  teams=[("M1", 100, 1)],
                  frames=[("M1", 0, 1, 1, 500, 10, 0, 1, 1, 0, 0)])
        first = X.match_detail("M1")
        # Delete the database out from under the module: a second call that
        # still answers can only have come from the cache.
        self.db.unlink()
        self.assertIs(X.match_detail("M1"), first)

    def test_sql_is_parameterized_against_a_hostile_match_id(self):
        _build_db(self.db, matches=[("M1", 450, "ARAM", 900, 1, "16.15", None)])
        self.assertIsNone(X.match_detail("M1'; DROP TABLE matches;--"))
        c = sqlite3.connect(str(self.db))
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 1)
        finally:
            c.close()

    def test_item_purchase_and_destroy_fold(self):
        _build_db(self.db, matches=[("M1", 450, "ARAM", 900, 1, "16.15", None)],
                  events=[(1000, "ITEM_PURCHASED", 1, 1055, None),
                          (2000, "ITEM_PURCHASED", 1, 3006, None),
                          (2100, "ITEM_DESTROYED", 1, 1055, None)])
        self.assertEqual(X._build_inventory_at(_item_events(self.db), 10 ** 9).get(1),
                         [3006])


class TestResourceLifetime(ReplayHistoryTestBase):
    """Audit dimension 4d. Every acquired connection needs a deterministic
    release INCLUDING on the exception path. The dashboard process runs for
    days, so a per-request leak that a one-shot script would never notice is
    a real outage here. Proven by injecting a failure, not by reading the
    `finally` block."""

    def _tracked(self, fail_on_call):
        real = sqlite3.connect(str(self.db))
        real.row_factory = sqlite3.Row
        state = {"closed": False, "calls": 0}

        class _Proxy:
            def execute(_self, *a, **kw):
                state["calls"] += 1
                if state["calls"] == fail_on_call:
                    raise sqlite3.OperationalError("no such table: injected")
                return real.execute(*a, **kw)

            def close(_self):
                state["closed"] = True
                real.close()

        self._orig_open = X._open
        X._open = lambda: _Proxy()
        self.addCleanup(lambda: setattr(X, "_open", self._orig_open))
        return state

    def _seed(self):
        _build_db(self.db,
                  matches=[("M1", 450, "ARAM", 900, 1, "16.15", None)],
                  parts=[("M1", 1, 100, 1, "Annie", "gn", "sn", 30)],
                  teams=[("M1", 100, 1)],
                  frames=[("M1", 0, 1, 1, 500, 10, 0, 1, 1, 0, 0)])

    def test_list_matches_closes_the_connection_when_a_query_raises(self):
        self._seed()
        state = self._tracked(fail_on_call=1)
        with self.assertRaises(sqlite3.OperationalError):
            X.list_matches()
        self.assertTrue(state["closed"], "connection leaked on the exception path")

    def test_match_detail_closes_the_connection_when_a_query_raises(self):
        self._seed()
        state = self._tracked(fail_on_call=2)
        with self.assertRaises(sqlite3.OperationalError):
            X.match_detail("M1")
        self.assertTrue(state["closed"], "connection leaked on the exception path")

    def test_match_detail_closes_the_connection_on_the_not_found_path(self):
        """The early `return None` for an unknown match sits inside the try;
        a future edit that moves it out would leak one handle per 404."""
        self._seed()
        state = self._tracked(fail_on_call=0)
        self.assertIsNone(X.match_detail("NOPE"))
        self.assertTrue(state["closed"])

    def test_list_matches_closes_the_connection_on_the_happy_path(self):
        self._seed()
        state = self._tracked(fail_on_call=0)
        self.assertEqual(len(X.list_matches()), 1)
        self.assertTrue(state["closed"])


if __name__ == "__main__":
    unittest.main()
