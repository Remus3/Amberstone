"""Self-contained rewind_history.db fixture for the draft-elo tests.

The live ``data/rewind_history.db`` is gitignored, so it is ABSENT on a
clean checkout / CI - the draft-elo + ban-suggest tests used to error
(setUpClass open_ro) + fail (route 503) there while passing only on a
developer machine that happened to have the live DB. This module builds a
temp SQLite carrying just the schema ``core.draft_elo_db`` queries
(``matches`` + ``participants``) plus a small deterministic seed, and
points ``core.draft_elo_db`` at it via the ``RC_REWIND_DB`` env override.
That makes the tests deterministic + portable (the smoke tests pin no
specific WR values, so a fixture loses no coverage and gains a clean-
checkout guarantee).

Seed (champ 64 = Lee Sin, 22 = Ashe):
  m1 q420: 64 (team100, win) + 22 (team100, win)   -> ally pair 64+22
  m2 q420: 64 (team100, loss) + 22 (team200, win)  -> matchup 64 vs 22
  m3 q400: 64 (team200, win)                        -> solo, non-420 queue
So solo(64) = 3 games (q420 subset = 2), pair(64,22 ally) = 1 game,
matchup(64 vs 22) = 1 game, self-pair(64,64) = 0 games. Laplace smoothing
keeps every rate strictly inside (0, 1).
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

_SCHEMA = (
    "CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER)",
    "CREATE TABLE participants ("
    "id INTEGER PRIMARY KEY, match_id TEXT, champion_id INTEGER, "
    "win INTEGER, team_id INTEGER)",
)

# (match_id, queue_id, ((champion_id, team_id, win), ...))
_SEED = (
    ("m1", 420, ((64, 100, 1), (22, 100, 1))),
    ("m2", 420, ((64, 100, 0), (22, 200, 1))),
    ("m3", 400, ((64, 200, 1),)),
)


def build_fixture_db(path: Path) -> None:
    """Create the matches + participants schema and the deterministic seed."""
    conn = sqlite3.connect(str(path))
    try:
        for stmt in _SCHEMA:
            conn.execute(stmt)
        pid = 1
        for match_id, queue_id, parts in _SEED:
            conn.execute(
                "INSERT INTO matches (match_id, queue_id) VALUES (?, ?)",
                (match_id, queue_id),
            )
            for champ, team, win in parts:
                conn.execute(
                    "INSERT INTO participants "
                    "(id, match_id, champion_id, win, team_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (pid, match_id, champ, win, team),
                )
                pid += 1
        conn.commit()
    finally:
        conn.close()


class DraftEloFixture:
    """Build the fixture DB in a temp dir + point RC_REWIND_DB at it.

    Call ``start()`` from setUpClass and ``stop()`` from tearDownClass.
    ``stop()`` restores the prior RC_REWIND_DB value (so a nested or
    outer override is preserved) and removes the temp dir.
    """

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._prev_env: str | None = None
        self.path: Path | None = None

    def start(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory(prefix="rc_draft_elo_")
        self.path = Path(self._tmp.name) / "rewind_history.db"
        build_fixture_db(self.path)
        self._prev_env = os.environ.get("RC_REWIND_DB")
        os.environ["RC_REWIND_DB"] = str(self.path)
        return self.path

    def stop(self) -> None:
        if self._prev_env is None:
            os.environ.pop("RC_REWIND_DB", None)
        else:
            os.environ["RC_REWIND_DB"] = self._prev_env
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


class DraftEloFixtureMixin:
    """Mixin: start a DraftEloFixture for the whole TestCase class.

    Compose BEFORE unittest.TestCase so the class-level fixture wraps the
    per-test setUp (which the route tests use for _reset_caches()).
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._draft_fix = DraftEloFixture()
        cls._draft_fix.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._draft_fix.stop()
        super().tearDownClass()
