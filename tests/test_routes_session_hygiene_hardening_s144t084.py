"""Hardening tests for ``dashboard.routes_session_hygiene`` (s144 true-audit cycle 84).

One test (or test group) per audited weakness of GET /api/session-hygiene:

F1 queue tokens: only ASCII decimal digits of bounded length are ids.
   ``int()`` alone accepted a sign (``-1``, ``+450``), ``_`` separators and
   non-ASCII digits, and an over-long id reached SQLite as an OverflowError
   (not a sqlite3.Error, so it escaped the core's "never raises" catch) and
   came back as a 500 for what is a client error.
F2 a value that holds no id (``queue=,``) is a 400. It used to become an
   EMPTY filter, which the core answers with an empty corpus - a 200 that
   reads as "you have played no games" and was cached for 5 minutes.
F3 the queue count is capped, so a long list can no longer reach SQLite's
   bound-variable limit (a sqlite3.Error the core turns into a silent empty
   corpus, served and cached as a 200).
F4 a duplicate queue id is a 400, and the cache key is the canonical
   (sorted) queue set, so ``450,420`` and ``420,450`` share one entry.
F5 a rejected token is clipped before it is echoed in the error body.
F6 no response is written while the module cache lock is held.
F7 the cache TTL runs on a monotonic clock, not the wall clock.
F8 an unexpected failure is logged WITH a traceback (it was logged as a
   bare ``%s`` of the exception), the body stays generic, and a failed 500
   send is logged instead of being silently swallowed.
F9 the 200 payload passes the compute result through untouched (Y-04:
   readiness.score null survives) and the stored cache entry is never
   mutated by a later hit.
"""
from __future__ import annotations

import json
import logging
import sqlite3

import pytest

from dashboard import routes_session_hygiene as route

_LOG = "rc.web_dashboard"


class _Harness:
    def __init__(self, qs: str = "", *, check_lock: bool = False,
                 fail_send: bool = False):
        self.path = "/api/session-hygiene" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = b""
        self.check_lock = check_lock
        self.lock_held_at_send = None
        self.fail_send = fail_send
        self.sends = 0

    def _send(self, status, body, content_type):
        self.sends += 1
        if self.check_lock:
            self.lock_held_at_send = route._CACHE_LOCK.locked()
        if self.fail_send:
            raise ConnectionResetError("client went away")
        self.sent_status = status
        self.sent_body = body

    def json(self) -> dict:
        return json.loads(self.sent_body)


def _serve(qs: str = "", **kw) -> _Harness:
    h = _Harness(qs, **kw)
    route._serve_session_hygiene(h)
    return h


@pytest.fixture(autouse=True)
def _clean_cache():
    route._reset_caches()
    yield
    route._reset_caches()


@pytest.fixture
def calls(monkeypatch):
    """Stub compute; records the queue_ids each call received."""
    seen: list = []

    def fake(queue_ids=None):
        seen.append(queue_ids)
        return {"ok": True, "n": 3,
                "readiness": {"score": None, "state": "unknown",
                              "flags": [], "basis": []}}

    monkeypatch.setattr(route.session_hygiene, "compute_session_hygiene", fake)
    return seen


def _real_db(tmp_path):
    db = tmp_path / "hygiene_route.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE matches ("
        "game_creation_ts INTEGER, game_end_ts INTEGER, game_duration_s INTEGER,"
        "tracked_win INTEGER, tracked_champion_id INTEGER,"
        "tracked_champion_name TEXT, queue_id INTEGER, game_mode TEXT)")
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)",
                 (1_000_000, 2_200_000, 1200, 1, 7, "Champ", 450, "ARAM"))
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------- baseline

def test_omitted_queue_means_all_games(calls):
    h = _serve()
    assert h.sent_status == 200
    assert calls == [None]
    body = h.json()
    assert body["cached"] is False
    assert isinstance(body["elapsed_ms"], int)


def test_valid_queue_list_is_parsed_in_order(calls):
    h = _serve("queue=450,420")
    assert h.sent_status == 200
    assert calls == [(450, 420)]


def test_blank_queue_value_is_all_games(calls):
    # parse_qs drops a blank value, so ``queue=`` is the omitted case.
    h = _serve("queue=")
    assert h.sent_status == 200
    assert calls == [None]


def test_spaces_around_tokens_are_tolerated(calls):
    h = _serve("queue=%20450%20,%20420")
    assert h.sent_status == 200
    assert calls == [(450, 420)]


# ---------------------------------------------------------------- F1

@pytest.mark.parametrize("token", [
    "-1", "+450", "4_50", "\u0664\u0665\u0660", "abc", "1.5", "0x1c2",
    "1234567",
])
def test_f1_non_id_token_is_400_and_never_computes(calls, token):
    from urllib.parse import quote
    h = _serve("queue=" + quote(token))
    assert h.sent_status == 400, token
    body = h.json()
    assert body["ok"] is False
    assert body["error"].startswith("queue:")
    assert calls == []


def test_f1_over_long_id_is_400_not_500_with_the_real_core(
        tmp_path, monkeypatch):
    db = _real_db(tmp_path)
    real = route.session_hygiene.compute_session_hygiene
    monkeypatch.setattr(
        route.session_hygiene, "compute_session_hygiene",
        lambda queue_ids=None: real(db_path=db, now_ms=3_000_000,
                                    queue_ids=queue_ids))
    h = _serve("queue=" + "9" * 20)
    assert h.sent_status == 400
    assert h.json()["ok"] is False


def test_f1_zero_is_a_valid_queue_id(calls):
    # Queue 0 is Riot's custom-game queue id.
    h = _serve("queue=0")
    assert h.sent_status == 200
    assert calls == [(0,)]


def test_f1_six_digit_id_is_accepted(calls):
    h = _serve("queue=999999")
    assert h.sent_status == 200
    assert calls == [(999999,)]


# ---------------------------------------------------------------- F2

@pytest.mark.parametrize("qs", ["queue=,", "queue=%20,%20,", "queue=,,,"])
def test_f2_value_without_any_id_is_400(calls, qs):
    h = _serve(qs)
    assert h.sent_status == 400
    assert calls == []


def test_f2_whitespace_only_value_is_the_omitted_case(calls):
    # parse_qs keeps " "; the route strips it, so it means "all games",
    # exactly like an omitted or blank parameter.
    h = _serve("queue=%20")
    assert h.sent_status == 200
    assert calls == [None]


def test_f2_empty_filter_never_reaches_the_cache(calls):
    _serve("queue=,")
    assert route._CACHE == {}


# ---------------------------------------------------------------- F3

def test_f3_queue_count_is_capped(calls):
    many = ",".join(str(i) for i in range(1, route._MAX_QUEUE_IDS + 2))
    h = _serve("queue=" + many)
    assert h.sent_status == 400
    assert calls == []


def test_f3_queue_count_at_the_cap_is_accepted(calls):
    ids = ",".join(str(i) for i in range(1, route._MAX_QUEUE_IDS + 1))
    h = _serve("queue=" + ids)
    assert h.sent_status == 200
    assert len(calls[0]) == route._MAX_QUEUE_IDS


# ---------------------------------------------------------------- F4

def test_f4_duplicate_queue_id_is_400(calls):
    h = _serve("queue=450,420,450")
    assert h.sent_status == 400
    assert "duplicate" in h.json()["error"]
    assert calls == []


def test_f4_queue_order_does_not_split_the_cache(calls):
    first = _serve("queue=450,420")
    second = _serve("queue=420,450")
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert len(calls) == 1
    assert len(route._CACHE) == 1


# ---------------------------------------------------------------- F5

def test_f5_rejected_token_is_clipped_in_the_error(calls):
    h = _serve("queue=" + "x" * 5000)
    assert h.sent_status == 400
    err = h.json()["error"]
    assert len(err) < 80
    assert "..." in err


# ---------------------------------------------------------------- F6

def test_f6_cache_hit_is_sent_outside_the_lock(calls):
    _serve("queue=450")
    h = _serve("queue=450", check_lock=True)
    assert h.json()["cached"] is True
    assert h.lock_held_at_send is False


def test_f6_cache_miss_is_sent_outside_the_lock(calls):
    h = _serve("queue=450", check_lock=True)
    assert h.json()["cached"] is False
    assert h.lock_held_at_send is False


# ---------------------------------------------------------------- F7

def test_f7_ttl_ignores_a_wall_clock_step_backwards(calls, monkeypatch):
    clock = {"mono": 1000.0, "wall": 5_000_000.0}
    monkeypatch.setattr(route.time, "monotonic", lambda: clock["mono"])
    monkeypatch.setattr(route.time, "time", lambda: clock["wall"])
    _serve("queue=450")
    # Wall clock steps back a day; monotonic advances past the TTL.
    clock["wall"] -= 86_400.0
    clock["mono"] += route._CACHE_TTL_S + 1.0
    h = _serve("queue=450")
    assert h.json()["cached"] is False
    assert len(calls) == 2


def test_f7_entry_within_ttl_is_served_from_cache(calls, monkeypatch):
    clock = {"mono": 1000.0}
    monkeypatch.setattr(route.time, "monotonic", lambda: clock["mono"])
    _serve("queue=450")
    clock["mono"] += route._CACHE_TTL_S - 1.0
    assert _serve("queue=450").json()["cached"] is True
    assert len(calls) == 1


# ---------------------------------------------------------------- F8

def test_f8_unexpected_failure_logs_a_traceback(monkeypatch, caplog):
    def boom(queue_ids=None):
        raise RuntimeError("secret detail <repo>/x/y")

    monkeypatch.setattr(route.session_hygiene, "compute_session_hygiene", boom)
    with caplog.at_level(logging.DEBUG, logger=_LOG):
        h = _serve("queue=450")
    assert h.sent_status == 500
    assert h.json() == {"ok": False, "error": "internal error - see logs"}
    assert b"secret" not in h.sent_body
    recs = [r for r in caplog.records if r.name == _LOG
            and r.levelno >= logging.WARNING]
    assert recs and recs[0].exc_info is not None
    assert route._CACHE == {}


def test_f8_failed_500_send_is_logged_not_swallowed(calls, caplog):
    # The 200 send fails (client gone), the 500 fallback send fails too.
    with caplog.at_level(logging.DEBUG, logger=_LOG):
        h = _Harness("queue=450", fail_send=True)
        route._serve_session_hygiene(h)   # must not raise
    assert h.sends == 2
    assert any("500 send failed" in r.getMessage() for r in caplog.records
               if r.name == _LOG)


# ---------------------------------------------------------------- F9

def _stored() -> str:
    return json.dumps([[repr(k), v[1]] for k, v in route._CACHE.items()],
                      sort_keys=True)


def test_f9_null_score_and_stored_entry_survive_hits(calls):
    first = _serve("queue=450")
    assert b'"score": null' in first.sent_body
    stored_before = _stored()
    second = _serve("queue=450")
    third = _serve("queue=450")
    assert second.json()["readiness"]["score"] is None
    assert third.json()["cached"] is True
    assert _stored() == stored_before
    for entry in route._CACHE.values():
        assert "cached" not in entry[1]
        assert "elapsed_ms" not in entry[1]
