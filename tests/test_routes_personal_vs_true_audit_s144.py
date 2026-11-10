"""True-audit (s144 lane 8, S144-T-771..776) of dashboard/routes_personal_vs.py.

GET /api/personal-vs?champ_id=X[&days=N][&queue=a,b] feeds the champ-select
enemy WR slots (web/js/panels/champ_select.js ``_csvWrSlotFetch``: five
parallel fetches per LCU tick). The route takes its query from the request
line, so every value is untrusted. Measured at HEAD before this slice:

- S144-T-771 champ_id went through bare ``int()``, which takes Arabic-Indic /
  fullwidth digits, ``_`` separators and a sign, and a value past the SQLite
  INTEGER range raised OverflowError inside the query - a 500 for what is a
  bad request (now 1-10 ASCII digits, 1 .. 2**31 - 1, else the 400).
- S144-T-772 ``days`` took the same non-ASCII / underscore forms (now ASCII
  digits with an optional sign, else the documented default of 30).
- S144-T-773 ``queue`` took the same forms, accepted negative ids, any count
  of ids and ids past the SQLite INTEGER range: 32767+ ids raised
  "too many SQL variables" and a 20-digit id raised OverflowError, both a
  500 (now each id 1-9 ASCII digits, duplicates dropped in order, at most
  32 ids, else the documented default SR set).
- S144-T-774 the module-level TTL cache was read, written and evicted with no
  lock on a ThreadingHTTPServer; the eviction sorts ``_CACHE.items()``,
  which raises "dictionary changed size during iteration" when another
  request thread inserts meanwhile.
- S144-T-775 the 200 was written inside the catch-all, so a failure while
  writing it (the client went away) wrote a SECOND status line (the 500
  envelope) onto the same response, and the inner ``except Exception: pass``
  hid a failing error send from the dispatcher; the raw exception text was
  logged unscrubbed with no type name (now dashboard._errors.send_error,
  the same body, and the reply is written outside the catch-all).
- S144-T-776 the read-only DB URI was built as ``f"file:{path}?mode=ro"``,
  so a checkout path holding ``#`` or ``%`` opened the wrong file (a 500);
  a non-numeric or non-finite ``game_creation_ts`` row raised TypeError /
  OverflowError while building ``recent`` (a 500 for the whole reply); and
  ``elapsed_ms`` was measured on the wall clock (a clock step made it
  negative).

Every route test drives the real route function through a stub handler
against a real SQLite file.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from dashboard import routes_personal_vs as rpv
from tests.test_routes_personal_vs import _build_test_db
from tests._timing_budget import fleet_test_guard

_ENEMY = 64


class _H:
    """Stub request handler recording every _send call."""

    def __init__(self, path: str, fail_first: BaseException | None = None):
        self.path = path
        self.calls: list[tuple[int, bytes, str]] = []
        self._fail_first = fail_first

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.calls.append((status, body, ctype))
        if self._fail_first is not None:
            exc, self._fail_first = self._fail_first, None
            raise exc


@pytest.fixture(autouse=True)
def _clean_cache():
    rpv._CACHE.clear()
    yield
    rpv._CACHE.clear()


def _db(tmp_path: Path, n: int = 6, name: str = "rh.db") -> Path:
    now_ms = int(time.time() * 1000)
    db = tmp_path / name
    _build_test_db(db, [
        {"match_id": f"M{i}", "ts_ms": now_ms - i * 1000, "op_win": i % 2,
         "enemy_champs": [_ENEMY]}
        for i in range(n)
    ])
    return db


def _serve(db: Path, path: str, monkeypatch, handler: _H | None = None):
    monkeypatch.setattr(rpv, "_REWIND_DB", db)
    h = handler or _H(path)
    rpv._serve_personal_vs(h)
    assert len(h.calls) == 1, h.calls
    status, body, ctype = h.calls[0]
    assert ctype == "application/json"
    return status, json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------- S144-T-771

@pytest.mark.parametrize("raw", [
    "\u0666\u0664",            # Arabic-Indic 64
    "\uff16\uff14",            # fullwidth 64
    "6_4",
    "%2B64",                   # an encoded plus sign (a bare + is a space)
    "-64",
    "64.0",
    "0",
    "00",
    "9" * 11,
    str(2**31),
    "9" * 25,                  # past the SQLite INTEGER range
])
def test_champ_id_outside_the_canonical_form_is_a_400(tmp_path, monkeypatch, raw):
    status, payload = _serve(_db(tmp_path), "/api/personal-vs?champ_id=" + raw,
                             monkeypatch)
    assert status == 400
    assert payload == {"ok": False, "error": "champ_id required (positive int)"}


@pytest.mark.parametrize(("raw", "want"), [
    ("64", 64), ("064", 64), (" 64 ", 64), (str(2**31 - 1), 2**31 - 1),
])
def test_canonical_champ_id_is_accepted(tmp_path, monkeypatch, raw, want):
    status, payload = _serve(_db(tmp_path), "/api/personal-vs?champ_id=" + raw,
                             monkeypatch)
    assert status == 200
    assert payload["champ_id"] == want


def test_champ_id_alias_still_accepted(tmp_path, monkeypatch):
    status, payload = _serve(_db(tmp_path), "/api/personal-vs?champId=64", monkeypatch)
    assert status == 200 and payload["sample_n"] == 6


# ---------------------------------------------------------------- S144-T-772

@pytest.mark.parametrize("raw", ["\u0667", "\uff17", "1_0", "7.5", "9" * 10, "", "x"])
def test_junk_days_reads_as_the_default(tmp_path, monkeypatch, raw):
    status, payload = _serve(_db(tmp_path),
                             "/api/personal-vs?champ_id=64&days=" + raw, monkeypatch)
    assert status == 200
    assert payload["days"] == 30


@pytest.mark.parametrize(("raw", "want"), [
    ("7", 7), ("+7", 7), ("-5", 0), ("0", 0), ("99999", 3650), ("007", 7),
])
def test_canonical_days_parse_and_clamp(tmp_path, monkeypatch, raw, want):
    status, payload = _serve(_db(tmp_path),
                             "/api/personal-vs?champ_id=64&days=" + raw, monkeypatch)
    assert status == 200
    assert payload["days"] == want


# ---------------------------------------------------------------- S144-T-773

@pytest.mark.parametrize("raw", [
    "4\u0662\u0660",           # Arabic-Indic digits
    "\uff14\uff12\uff10",      # fullwidth
    "4_20",
    "+420",
    "-1",
    "420,-1",
    "1" * 10,
    "9" * 20,                  # past the SQLite INTEGER range
    "420,x",
])
def test_junk_queue_filter_falls_back_to_the_default(raw):
    assert rpv._parse_queue_filter(raw) == rpv._DEFAULT_SR_QUEUES


def test_too_many_queue_ids_fall_back_to_the_default():
    raw = ",".join(str(i) for i in range(1, rpv._MAX_QUEUE_IDS + 2))
    assert rpv._parse_queue_filter(raw) == rpv._DEFAULT_SR_QUEUES
    ok = ",".join(str(i) for i in range(1, rpv._MAX_QUEUE_IDS + 1))
    assert len(rpv._parse_queue_filter(ok)) == rpv._MAX_QUEUE_IDS


def test_duplicate_queue_ids_are_dropped_in_order():
    assert rpv._parse_queue_filter("420,400,420, 400 ,0") == (420, 400, 0)


def test_valid_queue_forms_unchanged():
    assert rpv._parse_queue_filter("420") == (420,)
    assert rpv._parse_queue_filter("400,420,490") == (400, 420, 490)
    assert rpv._parse_queue_filter(" 420 , ,400,") == (420, 400)
    assert rpv._parse_queue_filter(",,") == rpv._DEFAULT_SR_QUEUES


@pytest.mark.parametrize("raw", [
    ",".join(str(i) for i in range(40000)),  # was "too many SQL variables" -> 500
    "9" * 20,                  # was OverflowError -> 500
])
def test_hostile_queue_param_is_a_200_on_the_default_set(tmp_path, monkeypatch, raw):
    status, payload = _serve(_db(tmp_path),
                             "/api/personal-vs?champ_id=64&queue=" + raw, monkeypatch)
    assert status == 200
    assert payload["queue_ids"] == list(rpv._DEFAULT_SR_QUEUES)
    assert payload["sample_n"] == 6


def test_forty_thousand_copies_of_one_queue_id_are_one_variable(tmp_path, monkeypatch):
    # was "too many SQL variables" -> 500
    status, payload = _serve(_db(tmp_path),
                             "/api/personal-vs?champ_id=64&queue=" + ",".join(["420"] * 40000),
                             monkeypatch)
    assert status == 200
    assert payload["queue_ids"] == [420]
    assert payload["sample_n"] == 6


def test_queue_order_and_duplicates_share_one_cache_entry(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _serve(db, "/api/personal-vs?champ_id=64&queue=420,420", monkeypatch)
    assert len(rpv._CACHE) == 1
    _, second = _serve(db, "/api/personal-vs?champ_id=64&queue=420", monkeypatch)
    assert second["cached"] is True and len(rpv._CACHE) == 1


# ---------------------------------------------------------------- S144-T-774

class _LockCheckedDict(dict):
    """A dict that fails any access made without the module's cache lock."""

    def _check(self):
        assert rpv._CACHE_LOCK.locked(), "cache touched without _CACHE_LOCK"

    def get(self, *a, **k):
        self._check()
        return super().get(*a, **k)

    def pop(self, *a, **k):
        self._check()
        return super().pop(*a, **k)

    def items(self):
        self._check()
        return super().items()

    def __setitem__(self, k, v):
        self._check()
        super().__setitem__(k, v)

    def __len__(self):
        self._check()
        return super().__len__()


def test_every_cache_access_holds_the_lock(monkeypatch):
    monkeypatch.setattr(rpv, "_CACHE", _LockCheckedDict())
    rpv._cache_put(("k",), {"v": 1})
    assert rpv._cache_get(("k",)) == {"v": 1}
    for i in range(rpv._CACHE_MAX + 1):
        rpv._cache_put(("n", i), {"v": i})
    assert rpv._cache_get(("missing",)) is None
    assert not rpv._CACHE_LOCK.locked()


def test_eviction_keeps_the_cache_bounded(monkeypatch):
    for i in range(rpv._CACHE_MAX + 1):
        rpv._cache_put(("n", i), {"v": i})
    assert len(rpv._CACHE) <= rpv._CACHE_MAX
    # The newest entry survives an eviction.
    assert rpv._cache_get(("n", rpv._CACHE_MAX)) == {"v": rpv._CACHE_MAX}


def test_concurrent_puts_never_raise():
    errors: list[BaseException] = []

    def worker(base: int) -> None:
        try:
            for i in range(3000):
                rpv._cache_put((base, i), {"v": i})
                rpv._cache_get((base, i - 1))
        except BaseException as exc:  # noqa: BLE001 - collected for the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(b,), name=f"pv-{b}") for b in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    assert len(rpv._CACHE) <= rpv._CACHE_MAX


# ---------------------------------------------------------------- S144-T-775

def test_a_failed_200_write_is_not_followed_by_a_second_status_line(tmp_path, monkeypatch):
    monkeypatch.setattr(rpv, "_REWIND_DB", _db(tmp_path))
    h = _H("/api/personal-vs?champ_id=64", fail_first=ConnectionAbortedError("gone"))
    with pytest.raises(ConnectionAbortedError):
        rpv._serve_personal_vs(h)
    assert [c[0] for c in h.calls] == [200]


def test_a_failed_cached_200_write_is_not_followed_by_a_second_status_line(tmp_path, monkeypatch):
    db = _db(tmp_path)
    _serve(db, "/api/personal-vs?champ_id=64", monkeypatch)
    h = _H("/api/personal-vs?champ_id=64", fail_first=BrokenPipeError("gone"))
    with pytest.raises(BrokenPipeError):
        rpv._serve_personal_vs(h)
    assert [c[0] for c in h.calls] == [200]


def test_a_failed_400_write_propagates(tmp_path, monkeypatch):
    monkeypatch.setattr(rpv, "_REWIND_DB", _db(tmp_path))
    h = _H("/api/personal-vs?champ_id=x", fail_first=ConnectionResetError("gone"))
    with pytest.raises(ConnectionResetError):
        rpv._serve_personal_vs(h)
    assert [c[0] for c in h.calls] == [400]


def test_a_failing_error_send_reaches_the_dispatcher(tmp_path, monkeypatch):
    monkeypatch.setattr(rpv, "_REWIND_DB", _db(tmp_path))

    def boom(*_a, **_k):
        raise RuntimeError("SECRET_DETAIL")

    monkeypatch.setattr(rpv, "_query_personal_vs", boom)
    h = _H("/api/personal-vs?champ_id=64", fail_first=ConnectionAbortedError("gone"))
    with pytest.raises(ConnectionAbortedError):
        rpv._serve_personal_vs(h)
    assert [c[0] for c in h.calls] == [500]


def test_an_internal_failure_is_the_fixed_500_and_a_scrubbed_typed_log(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(rpv, "_REWIND_DB", _db(tmp_path))

    def boom(*_a, **_k):
        raise RuntimeError("SECRET_DETAIL\x1b[31m")

    monkeypatch.setattr(rpv, "_query_personal_vs", boom)
    with caplog.at_level(logging.WARNING):
        status, payload = _serve(rpv._REWIND_DB, "/api/personal-vs?champ_id=64", monkeypatch)
    assert status == 500
    assert payload == {"ok": False, "error": "internal error - see logs"}
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in text
    assert "\x1b" not in text


# ---------------------------------------------------------------- S144-T-776

@pytest.mark.parametrize("dirname", ["a#b", "a%41b", "a%20b", "a b"])
def test_db_path_with_uri_metacharacters_opens_the_right_file(tmp_path, monkeypatch, dirname):
    d = tmp_path / dirname
    d.mkdir()
    status, payload = _serve(_db(d), "/api/personal-vs?champ_id=64", monkeypatch)
    assert status == 200
    assert payload["sample_n"] == 6


def test_db_is_opened_read_only(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(rpv, "_REWIND_DB", db)
    conn = rpv._open_ro()
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE x (a)")
    finally:
        conn.close()


def _set_ts(db: Path, match_id: str, value) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("UPDATE matches SET game_creation_ts = ? WHERE match_id = ?",
                     (value, match_id))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("value", ["not-a-time", float("inf"), float("-inf"), b"\x00\x01",
                                   -5000, 10**18, 5e17])
def test_a_junk_game_creation_ts_reads_as_zero_not_a_500(tmp_path, monkeypatch, value):
    db = _db(tmp_path)
    _set_ts(db, "M0", value)
    status, payload = _serve(db, "/api/personal-vs?champ_id=64&days=0", monkeypatch)
    assert status == 200
    by_id = {r["match_id"]: r["ts"] for r in payload["recent"]}
    if "M0" in by_id:
        assert by_id["M0"] == 0
    assert all(isinstance(r["ts"], int) and r["ts"] >= 0 for r in payload["recent"])


def test_valid_game_creation_ts_unchanged(tmp_path, monkeypatch):
    db = _db(tmp_path, n=1)
    _set_ts(db, "M0", 1_746_000_000_123)
    # the operator must still be the most frequent puuid: one match only, so
    # call the query directly.
    conn = sqlite3.connect(str(db))
    try:
        out = rpv._query_personal_vs(conn, "OPERATOR_PUUID_FIXTURE", _ENEMY, 0, (420,))
    finally:
        conn.close()
    # _db(n=1): match M0 has op_win 0.
    assert out["recent"] == [{"match_id": "M0", "ts": 1_746_000_000, "result": "LOSS"}]


def test_elapsed_ms_never_negative_on_a_wall_clock_step(tmp_path, monkeypatch):
    db = _db(tmp_path)
    real = time.time
    calls = {"n": 0}

    def stepping():
        calls["n"] += 1
        # every later read is an hour earlier than the first
        return real() - (3600.0 if calls["n"] > 1 else 0.0)

    monkeypatch.setattr(rpv.time, "time", stepping)
    status, payload = _serve(db, "/api/personal-vs?champ_id=64&days=0", monkeypatch)
    assert status == 200
    assert 0 <= payload["elapsed_ms"] < fleet_test_guard.budget(60) * 1000
