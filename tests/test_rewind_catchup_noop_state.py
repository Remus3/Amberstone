"""Regression: a healthy no-op catch-up run is indistinguishable from a dead one.

The weekly ``RC-RewindCatchup`` task runs ``pythonw.exe
scripts/rewind_catchup.py`` with no redirection. The script is NOT broken - a
live probe resolved Account-V1, paged Match-V5 and correctly reported 0 new.
Three defects nonetheless made a healthy no-op look exactly like a dead task:

1. ``last_run_at`` only advanced on the HYDRATE path. ``save_state`` has two
   callers; only the post-hydrate one set the run fields, and the no-op path
   (``if not new_ids: return _drain_and_report(conn)``) returned without
   touching them. The live sentinel's mtime advanced weekly while its
   ``last_run_at`` stayed 16 weeks stale, which fooled a reviewer into
   declaring the task dead.

2. "API dead" was byte-identical to "up to date". Inside pagination,
   ``get_recent_matches`` returning None on 403/401/transport printed and
   BROKE, falling straight into the no-op path and exiting 0. An expired Riot
   key would have read green forever. The genuine empty window is a returned
   EMPTY LIST (``core/riot_api.py:799-806`` returns ``[]`` for a 200 with no
   ids and None only on a wire/auth failure), so the two are distinguishable
   and were simply being collapsed.

3. No logging output existed - a module logger with no handler anywhere in
   the import chain, and every real message a bare ``print()``, all of which
   ``pythonw.exe`` discards.

Offline: the whole ``riot_api`` surface is faked, the DB is a tmp_path sqlite
file with the two tables these paths read, and the state sentinel + log path
are redirected into tmp_path. No live Riot call, no touch of the real 1.87 GB
``data/rewind_history.db`` or the real ``data/rewind_catchup.state.json``.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import time

import pytest

from core import riot_api
from scripts import rewind_catchup as rc

_OP_PUUID = "PUUID_OPERATOR_FIXTURE"


# --- fixtures ---------------------------------------------------------

def _make_db(path: pathlib.Path, matches=()) -> None:
    """Minimal DB carrying only the two tables the catch-up paths read.

    ``riot_id_game_name`` is blank on purpose: that makes
    ``operator_riot_id_from_db`` return None so ``resolve_current_puuid``
    settles on the DB puuid without any Account-V1 call.
    """
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, "
                 "game_creation_ts INTEGER)")
    conn.execute("CREATE TABLE participants (id INTEGER PRIMARY KEY "
                 "AUTOINCREMENT, puuid TEXT, riot_id_game_name TEXT, "
                 "riot_id_tagline TEXT)")
    for mid, ts in matches:
        conn.execute("INSERT INTO matches VALUES (?,?)", (mid, ts))
    for _ in range(3):
        conn.execute("INSERT INTO participants (puuid, riot_id_game_name, "
                     "riot_id_tagline) VALUES (?,'','')", (_OP_PUUID,))
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect every durable path this script writes, and neuter backoff."""
    db = tmp_path / "rewind_history.db"
    state = tmp_path / "rewind_catchup.state.json"
    log = tmp_path / "logs" / "rewind_catchup.log"
    _make_db(db, matches=[("NA1_OLD", 1_700_000_000_000)])
    monkeypatch.setattr(rc, "DB_PATH", db)
    monkeypatch.setattr(rc, "STATE_PATH", state)
    # raising=True (the default) on purpose: if LOG_PATH is ever renamed away
    # these tests must go RED, not quietly start writing the real logs/ dir.
    monkeypatch.setattr(rc, "LOG_PATH", log)
    # Empty backoff => one attempt, no sleep. main() must read this constant
    # at CALL time, not bind it as a def-time default, for this to bite.
    monkeypatch.setattr(rc, "DEFAULT_BACKOFF_S", ())
    monkeypatch.setattr(riot_api, "is_configured", lambda: True)
    monkeypatch.setattr(riot_api, "bucket_snapshot", lambda: {"fake": True})

    # setup_file_logging mutates the MODULE logger, which outlives the test.
    # Snapshot and restore so handlers pointing at a deleted tmp_path cannot
    # leak into the rest of the suite, and so propagate stays as it was.
    prior_handlers = list(rc._log.handlers)
    prior_propagate = rc._log.propagate
    prior_level = rc._log.level
    try:
        yield type("Env", (), {"db": db, "state": state, "log": log,
                               "tmp": tmp_path})
    finally:
        for handler in list(rc._log.handlers):
            if handler not in prior_handlers:
                rc._log.removeHandler(handler)
                handler.close()
        rc._log.propagate = prior_propagate
        rc._log.setLevel(prior_level)


def _ids_returning(value, outcome=None):
    """Fake get_recent_matches. ``outcome`` is published through the REAL
    ``riot_api`` outcome recorder, which is the mechanism the script's
    ``track_outcomes()`` scope reads - so the fake exercises the true seam."""
    def _fake(puuid, count=100, region="americas", start=0,
              start_time_unix_s=None, **kw):
        if outcome is not None:
            riot_api._record_outcome(outcome)
        return value
    return _fake


# --- 1. no-op run records that it RAN -------------------------------------

def test_noop_run_writes_fresh_last_run_at_and_outcome(env, monkeypatch):
    """A run that finds nothing must still say it ran, and must not clobber
    the existing hydrate-only fields."""
    rc.save_state({
        "puuid": _OP_PUUID,
        "last_run_at": "2026-06-09T00:01:29Z",
        "last_run_done": 7,
        "last_run_errors": 0,
        "newest_creation_ts_ms": 1_700_000_000_000,
    })
    monkeypatch.setattr(riot_api, "get_recent_matches", _ids_returning([]))

    before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    assert rc.main([]) == 0

    state = json.loads(env.state.read_text(encoding="utf-8"))
    assert state["last_run_at"] >= before, "last_run_at did not advance"
    assert state["last_run_at"] != "2026-06-09T00:01:29Z"
    assert state["last_run_outcome"] == "no_new_matches"
    assert state["last_run_rc"] == 0
    # Backward compatibility: the hydrate-only fields keep their old meaning.
    assert state["last_run_done"] == 7
    assert state["newest_creation_ts_ms"] == 1_700_000_000_000


# --- 2. hydrate run keeps the whole existing field set --------------------

def test_hydrate_run_still_writes_the_full_existing_field_set(env, monkeypatch):
    monkeypatch.setattr(riot_api, "get_recent_matches",
                        _ids_returning(["NA1_NEW"]))
    monkeypatch.setattr(rc, "hydrate_match",
                        lambda mid, tl, **kw: ({"info": {}}, None,
                                               rc.FETCH_OK, rc.FETCH_ABSENT))

    def _fake_record(conn, mid, detail, timeline, t_status):
        conn.execute("INSERT OR IGNORE INTO matches VALUES (?,?)",
                     (mid, 1_800_000_000_000))
    monkeypatch.setattr(rc, "record_hydrated", _fake_record)

    assert rc.main([]) == 0

    state = json.loads(env.state.read_text(encoding="utf-8"))
    for field in ("last_run_at", "last_run_done", "last_run_errors",
                  "newest_creation_ts_ms"):
        assert field in state, f"hydrate path dropped {field}"
    assert state["last_run_done"] == 1
    assert state["last_run_errors"] == 0
    assert state["newest_creation_ts_ms"] == 1_800_000_000_000
    assert state["last_run_outcome"] == "hydrated"


# --- 3. an API failure is NOT an empty window -----------------------------

@pytest.mark.parametrize("outcome", ["forbidden", "error", "not_found"])
def test_api_failure_during_pagination_exits_nonzero(env, monkeypatch, outcome):
    """403 / 401 / transport must never read as 'DB is up to date'."""
    monkeypatch.setattr(riot_api, "get_recent_matches",
                        _ids_returning(None, outcome=outcome))

    code = rc.main([])
    assert code != 0, "an API failure exited 0 - reads as a healthy no-op"
    assert code == 4

    state = json.loads(env.state.read_text(encoding="utf-8"))
    assert state["last_run_outcome"] == "api_failure"
    assert state["last_run_rc"] == 4
    assert state.get("last_run_error") == outcome
    assert "last_run_at" in state


def test_genuine_empty_window_is_still_a_clean_zero(env, monkeypatch):
    """The discriminator must not over-fire: an empty LIST is a real window."""
    monkeypatch.setattr(riot_api, "get_recent_matches", _ids_returning([]))
    assert rc.main([]) == 0
    state = json.loads(env.state.read_text(encoding="utf-8"))
    assert state["last_run_outcome"] == "no_new_matches"


# --- 4. 429 behaviour is unchanged ----------------------------------------

def test_pagination_429_still_returns_rc_3(env, monkeypatch):
    monkeypatch.setattr(riot_api, "get_recent_matches",
                        _ids_returning(None, outcome="429"))
    assert rc.main([]) == 3
    state = json.loads(env.state.read_text(encoding="utf-8"))
    assert state["last_run_outcome"] == "pagination_rate_limited"
    assert state["last_run_rc"] == 3


def test_detail_429_still_parks_the_match_in_fetch_retry(env, monkeypatch):
    monkeypatch.setattr(riot_api, "get_recent_matches",
                        _ids_returning(["NA1_PARKED"]))
    monkeypatch.setattr(rc, "hydrate_match",
                        lambda mid, tl, **kw: (None, None,
                                               rc.FETCH_RATE_LIMITED,
                                               rc.FETCH_ABSENT))
    # Keep the drain from immediately un-parking it.
    monkeypatch.setattr(rc, "drain_retry_queue",
                        lambda conn, **kw: {"recovered": 0, "permanent": 0,
                                            "deferred": 1, "abandoned": 0})

    assert rc.main([]) == 1

    conn = sqlite3.connect(str(env.db))
    parked = conn.execute(
        "SELECT match_id, kind FROM fetch_retry").fetchall()
    conn.close()
    assert parked == [("NA1_PARKED", "match")]


# --- 5. --retry-only records that it ran ----------------------------------

def test_retry_only_records_a_run(env, monkeypatch):
    assert rc.main(["--retry-only"]) == 0
    state = json.loads(env.state.read_text(encoding="utf-8"))
    assert state["last_run_outcome"] == "retry_only"
    assert "last_run_at" in state


def test_dry_run_still_writes_nothing(env, monkeypatch):
    monkeypatch.setattr(riot_api, "get_recent_matches", _ids_returning([]))
    assert rc.main(["--dry-run"]) == 0
    assert not env.state.exists(), "--dry-run wrote the state sentinel"


# --- 6. the state write is atomic -----------------------------------------

def test_state_write_is_atomic(env, monkeypatch):
    """No partial file is ever observable: the target holds the COMPLETE old
    document right up to the rename, and the rename source is a fully-written
    sibling tmp file."""
    old = {"puuid": _OP_PUUID, "marker": "OLD"}
    env.state.write_text(json.dumps(old), encoding="utf-8")

    seen = []
    real_replace = pathlib.Path.replace

    def _spy_replace(self, target):
        target = pathlib.Path(target)
        if target == env.state:
            # The tmp source must already be complete and parseable.
            json.loads(self.read_text(encoding="utf-8"))
            # The target must still be the COMPLETE previous document.
            assert json.loads(target.read_text(encoding="utf-8")) == old
            seen.append(self.name)
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", _spy_replace)
    monkeypatch.setattr(riot_api, "get_recent_matches", _ids_returning([]))

    assert rc.main([]) == 0
    assert seen, "state was written without a tmp-then-replace rename"
    assert all(n.endswith(".tmp") for n in seen), seen
    assert not list(env.tmp.glob("*.tmp")), "tmp file survived the rename"
    assert json.loads(env.state.read_text(encoding="utf-8"))["last_run_rc"] == 0


# --- 7. logging is attached, and its failure is survivable ----------------

def test_run_writes_a_log_file(env, monkeypatch):
    monkeypatch.setattr(riot_api, "get_recent_matches", _ids_returning([]))
    assert rc.main([]) == 0
    assert env.log.exists(), "no log file - pythonw discards every print()"
    assert env.log.read_text(encoding="utf-8").strip(), "log file is empty"


def test_logging_failure_does_not_abort_the_run(env, monkeypatch):
    def _boom(*a, **kw):
        raise OSError("logs/ is read-only")
    monkeypatch.setattr(rc, "RotatingFileHandler", _boom)
    monkeypatch.setattr(riot_api, "get_recent_matches", _ids_returning([]))

    assert rc.main([]) == 0
    state = json.loads(env.state.read_text(encoding="utf-8"))
    assert state["last_run_outcome"] == "no_new_matches"
