"""Regression: one match written 11-12 times into rewind_history.db.

Measured 2026-09-20 (read-only) on data/rewind_history.db: three matches
carry EXACT duplicate child rows - NA1_5597856321 (198 participant rows for 18
players, 11 copies), NA1_5605680438 (216 / 18, 12 copies), NA1_5605705803
(120 / 10, 12 copies); teams duplicated the same way, timeline frames up to 6x.
Each match's copies sit in ONE contiguous participants.id block, and two of
the three have has_timeline=0 while holding frame rows.

Root cause: scripts/rewind_catchup.write_match is not idempotent. The
``matches`` insert is INSERT OR IGNORE on a PRIMARY KEY, but participants /
teams / timeline_* have no natural unique key, so every call appends a full
copy. lib/rewind_live_writer probes "already present?" BEFORE fetching and
outside _WRITE_LOCK, so concurrent Timers (several schedule_live_insert calls
for one game end) all pass the probe and all write. The first writer lost
the timeline (the burst itself trips 429s), which is why the kept matches row
says has_timeline=0 while later copies inserted frames.

Fix: write_match only inserts children when IT inserted the matches row; on
an existing row it only attaches a timeline the row lacks (replace, not
append). Recovery: scripts/rewind_dedup_children.py removes exact duplicate
participant / team rows (dry run by default) and queues a canonical timeline
re-fetch for matches with duplicated frames.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import riot_api as RA  # noqa: E402
from lib import rewind_live_writer as rlw  # noqa: E402
from scripts import rewind_catchup as rc  # noqa: E402
from scripts import rewind_dedup_children as dd  # noqa: E402
from scripts import rewind_scraper as rs  # noqa: E402

NO_SLEEP = (lambda _s: None)


def _detail() -> dict:
    return {"info": {
        "queueId": 400, "gameMode": "CLASSIC", "gameDuration": 1800,
        "gameCreation": 1_700_000_000_000, "platformId": "NA1",
        "gameVersion": "16.14.1",
        "participants": [
            {"participantId": i, "puuid": f"P{i}", "teamId": 100 if i <= 5 else 200,
             "championName": f"C{i}", "kills": i}
            for i in range(1, 11)
        ],
        "teams": [{"teamId": 100, "win": True}, {"teamId": 200, "win": False}],
    }}


_EV = {"type": "ITEM_PURCHASED", "timestamp": 5, "participantId": 1,
       "itemId": 2003}


def _timeline() -> dict:
    """3 frames x 10 participants = 30 frame rows; 4 event rows, TWO of
    which are identical in every column (a potion bought twice in the same
    tick). Measured 2026-09-20: 2952 clean matches in the production DB
    carry such legitimately identical event rows, so identity alone never
    proves a duplicate write."""
    return {"info": {"frames": [
        {"timestamp": t,
         "participantFrames": {str(i): {"participantId": i, "totalGold": t + i}
                               for i in range(1, 11)},
         "events": ([dict(_EV), dict(_EV)] if t == 0 else
                    [{"type": "ITEM_PURCHASED", "timestamp": t + 5,
                      "participantId": 1, "itemId": 1055}])}
        for t in (0, 60000, 120000)
    ]}}


EV_PER_TIMELINE = 4


class _DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "rewind_history.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(rs.SCHEMA)
        conn.commit()
        conn.close()
        self._patches = [
            mock.patch.object(rc, "STATE_PATH", self.tmp / "state.json"),
            mock.patch.object(rc, "DB_PATH", self.db_path),
            mock.patch.object(rlw, "DB_PATH", self.db_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def conn(self):
        return sqlite3.connect(str(self.db_path))

    def count(self, table: str, mid: str = "NA1_1") -> int:
        c = self.conn()
        try:
            return c.execute(f"SELECT COUNT(*) FROM {table} WHERE match_id=?",
                             (mid,)).fetchone()[0]
        finally:
            c.close()

    def has_timeline(self, mid: str = "NA1_1") -> int:
        c = self.conn()
        try:
            return c.execute("SELECT has_timeline FROM matches WHERE match_id=?",
                             (mid,)).fetchone()[0]
        finally:
            c.close()

    def write(self, timeline):
        c = self.conn()
        rc.write_match(c, "NA1_1", _detail(), timeline)
        c.commit()
        c.close()


class WriteMatchIdempotencyTests(_DbCase):
    def test_second_write_does_not_append_participants_or_teams(self):
        self.write(None)
        self.write(None)
        self.assertEqual(self.count("participants"), 10)
        self.assertEqual(self.count("teams"), 2)

    def test_second_write_with_timeline_attaches_it_once(self):
        # The observed production shape: first writer had no timeline.
        self.write(None)
        self.write(_timeline())
        self.write(_timeline())
        self.assertEqual(self.has_timeline(), 1)
        self.assertEqual(self.count("timeline_frames"), 30)
        self.assertEqual(self.count("timeline_events"), EV_PER_TIMELINE)
        self.assertEqual(self.count("participants"), 10)

    def test_rewrite_of_complete_match_changes_nothing(self):
        self.write(_timeline())
        self.write(_timeline())
        self.assertEqual(self.count("timeline_frames"), 30)
        self.assertEqual(self.count("timeline_events"), EV_PER_TIMELINE)
        self.assertEqual(self.count("teams"), 2)


class LiveWriterConcurrencyTests(_DbCase):
    """The production path: N Timers pass the pre-lock presence probe."""

    def test_concurrent_live_writes_leave_one_copy(self):
        state = self.tmp / "live_state.json"
        state.write_text(json.dumps({"puuid": "abc"}), encoding="utf-8")
        # The production DB is already WAL. Switching a fresh file needs an
        # exclusive lock, which concurrent _open_db calls would contend for.
        c = self.conn()
        c.execute("PRAGMA journal_mode=WAL")
        c.close()
        n = 4
        barrier = threading.Barrier(n, timeout=10)

        def _get_match(*_a, **_k):
            barrier.wait()   # every thread is past the presence probe
            RA._record_outcome("ok")
            return _detail()

        def _get_tl(*_a, **_k):
            RA._record_outcome("ok")
            return _timeline()

        results: list[dict] = []

        def _run():
            results.append(rlw._do_live_fetch_and_insert(
                is_retry=True, backoff_s=(0.0,), sleep=NO_SLEEP))

        with mock.patch.object(rlw, "STATE_PATH", state), \
             mock.patch.object(RA, "is_configured", lambda: True), \
             mock.patch.object(RA, "get_recent_matches",
                               lambda *a, **k: ["NA1_1"]), \
             mock.patch.object(RA, "get_match", _get_match), \
             mock.patch.object(RA, "get_match_timeline", _get_tl):
            threads = [threading.Thread(target=_run) for _ in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(20)
        self.assertEqual(len(results), n)
        self.assertEqual(self.count("participants"), 10)
        self.assertEqual(self.count("teams"), 2)
        self.assertEqual(self.count("timeline_frames"), 30)
        self.assertEqual(self.has_timeline(), 1)


class DedupScriptTests(_DbCase):
    def _seed_polluted(self, mid: str, copies: int, has_timeline: int) -> None:
        """Reproduce the production shape with raw inserts (the fixed
        write_match can no longer produce it)."""
        c = self.conn()
        rc.write_match(c, mid, _detail(), _timeline() if has_timeline else None)
        info = _detail()["info"]
        tl = _timeline()
        for _ in range(copies - 1):
            rs.insert_rows(c, "participants",
                           [rs.parse_participant(p, mid) for p in info["participants"]])
            rs.insert_rows(c, "teams", [rs.parse_team(t, mid) for t in info["teams"]])
            rc._insert_timeline_rows(c, mid, tl)
        c.commit()
        c.close()

    def test_scan_finds_duplicated_matches(self):
        self._seed_polluted("NA1_DUP", 3, has_timeline=0)
        self.write(_timeline())  # a clean match
        c = self.conn()
        report = dd.scan(c)
        c.close()
        self.assertEqual([r["match_id"] for r in report], ["NA1_DUP"])
        r = report[0]
        self.assertEqual(r["participants"], (30, 10))
        self.assertEqual(r["teams"], (6, 2))
        # First write had no timeline; the 2 later copies each added one.
        # events = (rows, rows after copy-aware dedup)
        self.assertEqual(r["frames"], (60, 30))
        self.assertEqual(r["events"], (8, 4))

    def test_dry_run_is_default_and_writes_nothing(self):
        self._seed_polluted("NA1_DUP", 3, has_timeline=1)
        before = self.db_path.read_bytes()
        self.assertEqual(dd.main(["--db", str(self.db_path)]), 0)
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_scan_reports_frame_and_event_distinct_counts(self):
        self._seed_polluted("NA1_DUP", 3, has_timeline=1)
        c = self.conn()
        r = dd.scan(c)[0]
        c.close()
        self.assertEqual(r["frames"], (90, 30))
        self.assertEqual(r["events"], (12, 4))

    def test_clean_match_with_identical_events_is_not_touched(self):
        self.write(_timeline())
        c = self.conn()
        report = dd.scan(c)
        c.close()
        self.assertEqual(report, [])
        dd.main(["--db", str(self.db_path), "--apply"])
        self.assertEqual(self.count("timeline_events"), EV_PER_TIMELINE)

    def _seed_frames_only_dup(self, mid: str, frame_copies: int,
                              extra_event_copies: int = 0) -> None:
        """Production shape (measured 2026-09-20): participants and frames
        copied, events present once (their extra copies already gone)."""
        c = self.conn()
        rc.write_match(c, mid, _detail(), _timeline())
        info = _detail()["info"]
        frames = [row for f in _timeline()["info"]["frames"]
                  for row in rs.parse_frame(f, mid)]
        events = [rs.parse_event(ev, mid) for f in _timeline()["info"]["frames"]
                  for ev in f["events"]]
        for _ in range(frame_copies - 1):
            rs.insert_rows(c, "participants",
                           [rs.parse_participant(p, mid) for p in info["participants"]])
            rs.insert_rows(c, "timeline_frames", frames)
        for _ in range(extra_event_copies):
            rs.insert_rows(c, "timeline_events", events)
        c.commit()
        c.close()

    def test_frames_duplicated_events_single_copy_events_untouched(self):
        self._seed_frames_only_dup("NA1_DUP", 6)
        c = self.conn()
        r = dd.scan(c)[0]
        c.close()
        self.assertEqual(r["events"], (EV_PER_TIMELINE, EV_PER_TIMELINE))
        self.assertFalse(r["events_skipped"])
        dd.main(["--db", str(self.db_path), "--apply"])
        self.assertEqual(self.count("timeline_frames", "NA1_DUP"), 30)
        self.assertEqual(self.count("timeline_events", "NA1_DUP"), EV_PER_TIMELINE)
        self.assertEqual(self.count("participants", "NA1_DUP"), 10)

    def test_ambiguous_event_copy_count_is_skipped_not_guessed(self):
        # frames 3 copies, events 2 copies: gcd 2 != 3.
        self._seed_frames_only_dup("NA1_DUP", 3, extra_event_copies=1)
        c = self.conn()
        r = dd.scan(c)[0]
        c.close()
        self.assertTrue(r["events_skipped"])
        dd.main(["--db", str(self.db_path), "--apply"])
        self.assertEqual(self.count("timeline_events", "NA1_DUP"),
                         2 * EV_PER_TIMELINE)
        self.assertEqual(self.count("timeline_frames", "NA1_DUP"), 30)

    def test_polluted_match_keeps_legit_identical_events(self):
        # Blind exact-row dedup would collapse the potion pair to 1 -> 3.
        self._seed_polluted("NA1_DUP", 3, has_timeline=1)
        dd.main(["--db", str(self.db_path), "--apply"])
        c = self.conn()
        n = c.execute("SELECT COUNT(*) FROM timeline_events WHERE match_id='NA1_DUP' "
                      "AND item_id=2003").fetchone()[0]
        c.close()
        self.assertEqual(n, 2)

    def test_apply_dedups_timeline_rows_even_if_refetch_never_succeeds(self):
        # Readers (routes_replay_events, post_game_score) read every event
        # row with no DISTINCT, so the DB must be right without the refetch.
        self._seed_polluted("NA1_DUP", 3, has_timeline=0)
        self.assertEqual(dd.main(["--db", str(self.db_path), "--apply"]), 0)
        self.assertEqual(self.count("timeline_frames", "NA1_DUP"), 30)
        self.assertEqual(self.count("timeline_events", "NA1_DUP"), EV_PER_TIMELINE)
        c = self.conn()
        with mock.patch.object(RA, "get_match_timeline",
                               lambda *a, **k: (RA._record_outcome("404"), None)[1]):
            counts = rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(counts["permanent"], 1)
        self.assertEqual(self.count("timeline_frames", "NA1_DUP"), 30)
        self.assertEqual(self.count("timeline_events", "NA1_DUP"), EV_PER_TIMELINE)

    def test_apply_dedups_and_queues_timeline_refetch(self):
        self._seed_polluted("NA1_DUP", 3, has_timeline=1)
        self.assertEqual(dd.main(["--db", str(self.db_path), "--apply"]), 0)
        self.assertEqual(self.count("participants", "NA1_DUP"), 10)
        self.assertEqual(self.count("teams", "NA1_DUP"), 2)
        self.assertEqual(self.count("timeline_frames", "NA1_DUP"), 30)
        self.assertEqual(self.count("timeline_events", "NA1_DUP"), EV_PER_TIMELINE)
        c = self.conn()
        q = c.execute("SELECT match_id, kind FROM fetch_retry").fetchall()
        with mock.patch.object(RA, "get_match_timeline",
                               lambda *a, **k: (RA._record_outcome("ok"), _timeline())[1]):
            rc.drain_retry_queue(c, backoff_s=(), sleep=NO_SLEEP)
        c.close()
        self.assertEqual(q, [("NA1_DUP", "timeline")])
        self.assertEqual(self.count("timeline_frames", "NA1_DUP"), 30)
        self.assertEqual(self.count("timeline_events", "NA1_DUP"), EV_PER_TIMELINE)
        self.assertEqual(self.has_timeline("NA1_DUP"), 1)

    def test_apply_is_idempotent(self):
        self._seed_polluted("NA1_DUP", 2, has_timeline=0)
        dd.main(["--db", str(self.db_path), "--apply"])
        dd.main(["--db", str(self.db_path), "--apply"])
        self.assertEqual(self.count("participants", "NA1_DUP"), 10)

    def test_non_identical_copies_are_left_alone(self):
        self._seed_polluted("NA1_DUP", 2, has_timeline=0)
        c = self.conn()
        c.execute("UPDATE participants SET kills=99 WHERE id=(SELECT MAX(id) "
                  "FROM participants WHERE match_id='NA1_DUP')")
        c.commit()
        c.close()
        dd.main(["--db", str(self.db_path), "--apply"])
        # 10 originals + 9 exact copies removed + 1 divergent copy kept.
        self.assertEqual(self.count("participants", "NA1_DUP"), 11)


if __name__ == "__main__":
    unittest.main()
