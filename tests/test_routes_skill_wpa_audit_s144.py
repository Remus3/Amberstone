"""s144 true-audit cycle 89: dashboard/routes_skill_wpa.py hardening.

The same defect class the cycle-87 / 88 audits fixed in routes_item_wpa.py
and routes_rune_wpa.py, re-measured on this route (live :8888 before the
fix: ``queue_id=abc&min_n=1`` answered 200 with the whole 442-row corpus
under ``queue_id: null``, ``min_n=-5`` answered 200 as min_n 0, and a
24-digit queue_id answered 500). One test (or one small group) per
finding, each written RED against the pre-audit route and
mutation-checked against the fix:

  F1  min_n, queue_id and patch are validated: a malformed value is a 400
      (a typo dropped the filter and served and cached the whole corpus;
      an over-long queue_id reached SQLite as an OverflowError and was a
      500; int() accepted a sign, "_" separators and non-ASCII digits),
      each given at most once; a negative min_n is a 400, not clamped.
  F2  a model file load_model does not catch (list- or string-shaped JSON,
      an overflowing n_samples) no longer 500s every request until the
      file changes.
  F3  a model whose weights are non-finite or the wrong length is not
      served as "trained"; every response body is strict JSON and an
      unserialisable payload is never cached.
  F4  a retrained model with the same version + n_samples invalidates the
      response cache.
  F5  the response cache is read and written only under its lock.
  F6  the cache TTL runs on the monotonic clock.
  F7  a SQLite failure is a retryable 503, not a generic 500.
  F8  an unexpected failure is logged WITH its traceback, and a failed
      500 send is logged instead of swallowed.
  F9  the read-only DB URI survives a '#', '%' or space in the repo path.
  F10 a transient stat failure on the model file keeps the loaded model
      instead of silently switching to the fallback estimator.
  F11 the module docstring states the real failure contract and the real
      row shape (model).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from core import post_game_score as pgs
from dashboard import routes_skill_wpa as rsw
from tests.test_skill_wpa import AHRI, _add_match

_SCHEMA = """
CREATE TABLE matches (
    match_id TEXT, queue_id INTEGER, patch TEXT, has_timeline INTEGER
);
CREATE TABLE timeline_frames (
    match_id TEXT, timestamp_ms INTEGER, participant_id INTEGER,
    total_gold INTEGER, xp INTEGER
);
CREATE TABLE timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT, timestamp_ms INTEGER, event_type TEXT,
    participant_id INTEGER, skill_slot INTEGER
);
CREATE TABLE participants (
    match_id TEXT, participant_id INTEGER, team_id INTEGER,
    win INTEGER, champion_id INTEGER
);
"""


def _seed(path: Path) -> Path:
    # Both max-Q Ahri players are on the gold-ahead team (participant 7 is
    # team 200), so the expected winrate is not the symmetric 0.5 a
    # constant model would also produce. Synthetic match ids only.
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    _add_match(conn, "TEST_SKILL_201", team100_gold=5000, team200_gold=0,
               team100_win=1, maxes=[(1, AHRI, 1, 300_000)],
               queue_id=420, patch="14.24")
    _add_match(conn, "TEST_SKILL_202", team100_gold=0, team200_gold=5000,
               team100_win=0, maxes=[(7, AHRI, 1, 300_000)],
               queue_id=450, patch="15.13")
    conn.close()
    return path


class _StubHandler:
    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status, body, content_type="application/json",
              cache_control=None):
        self.responses.append((status, body, content_type))


@pytest.fixture(autouse=True)
def _reset_module_state():
    def _reset():
        rsw._CACHE.clear()
        rsw._MODEL_CACHE["mtime"] = None
        rsw._MODEL_CACHE["model"] = None
    _reset()
    yield
    _reset()


@pytest.fixture
def db(tmp_path):
    return _seed(tmp_path / "rh.db")


def _serve(path: str, db: Path, model_path: Path | None = None):
    with mock.patch.object(rsw, "_REWIND_DB", db), \
         mock.patch.object(rsw, "_MODEL_PATH",
                           model_path or db.parent / "absent_model.json"):
        h = _StubHandler(path)
        rsw._serve_skill_wpa(h)
        return h.responses


def _refuse_constant(name):
    raise AssertionError(f"non-strict JSON constant in response: {name}")


def _one(responses):
    assert len(responses) == 1, responses
    status, body, _ct = responses[0]
    return status, json.loads(body, parse_constant=_refuse_constant)


def _max_q_ahri_n(payload) -> int:
    return sum(it["n"] for it in payload["items"]
               if it["champion_id"] == AHRI and it["skill_slot"] == 1)


# -- F1: query validation ------------------------------------------------

@pytest.mark.parametrize("query", [
    "queue_id=abc",            # was: filter dropped, whole corpus served
    "queue_id=4_20",           # int() accepts "_" separators
    "queue_id=%2B420",         # int() accepts a sign
    "queue_id=-420",
    "queue_id=%20420",         # .strip() hid padding
    "queue_id=%D9%A4%D9%A2%D9%A0",  # Arabic-Indic digits 420
    "queue_id=" + "9" * 30,    # OverflowError at the SQLite bind
    "queue_id=1234567",        # 7 digits
    "queue_id=420&queue_id=450",
    "min_n=abc",
    "min_n=-5",                # was: clamped to 0, every row shown
    "min_n=%2B20",
    "min_n=2_0",
    "min_n=1234567",
    "min_n=20&min_n=1",
    "patch=14.24%0A",          # newline
    "patch=" + "1" * 200,
    "patch=14.24%3B%20DROP",
    "patch=%C2%B9%C2%B9.1",    # superscript digits
    "patch=14.24&patch=15.13",
])
def test_f1_malformed_query_is_400(db, query):
    status, payload = _one(_serve(f"/api/skill-wpa?{query}", db))
    assert status == 400, payload
    assert payload["ok"] is False
    assert isinstance(payload["error"], str)
    # A rejected value is never reflected back in full.
    assert "1" * 200 not in payload["error"]
    assert "9" * 30 not in payload["error"]
    assert not rsw._CACHE


def test_f1_bad_queue_id_does_not_fall_back_to_the_whole_corpus(db):
    status, _payload = _one(_serve("/api/skill-wpa?queue_id=abc&min_n=1", db))
    assert status == 400


@pytest.mark.parametrize("query,expect_n,expect_q,expect_patch", [
    ("min_n=1", 2, None, None),
    ("min_n=1&queue_id=420", 1, 420, None),
    ("min_n=1&queue_id=0", 0, 0, None),
    ("min_n=1&patch=15.13", 1, None, "15.13"),
    ("min_n=1&patch=16.11.1", 0, None, "16.11.1"),
    ("min_n=1&queue_id=&patch=", 2, None, None),
    ("min_n=000001", 2, None, None),
])
def test_f1_well_formed_query_still_served(db, query, expect_n, expect_q,
                                           expect_patch):
    status, payload = _one(_serve(f"/api/skill-wpa?{query}", db))
    assert status == 200, payload
    assert payload["ok"] is True
    assert payload["queue_id"] == expect_q
    assert payload["patch"] == expect_patch
    assert payload["min_n"] == 1
    assert _max_q_ahri_n(payload) == expect_n


def test_f1_absent_min_n_defaults_to_20(db):
    status, payload = _one(_serve("/api/skill-wpa", db))
    assert status == 200
    assert payload["min_n"] == 20


def test_f1_min_n_zero_is_accepted(db):
    status, payload = _one(_serve("/api/skill-wpa?min_n=0", db))
    assert status == 200
    assert payload["min_n"] == 0


# -- F2: a model file load_model does not catch ----------------------------

@pytest.mark.parametrize("doc", [
    pytest.param("[1, 2, 3]", id="list-AttributeError"),
    pytest.param('"just a string"', id="string-AttributeError"),
    pytest.param('{"weights": [], "n_samples": 1e999}',
                 id="n_samples-OverflowError"),
])
def test_f2_unloadable_model_falls_back_instead_of_500(db, tmp_path, doc):
    model_path = tmp_path / "model.json"
    model_path.write_text(doc, encoding="utf-8")
    for _ in range(2):
        status, payload = _one(_serve("/api/skill-wpa?min_n=1", db,
                                      model_path))
        assert status == 200
        assert payload["ok"] is True
        assert payload["model"] == "fallback"


def test_f2_bad_model_is_logged_once_per_file_version(db, tmp_path, caplog):
    model_path = tmp_path / "model.json"
    model_path.write_text("[1]", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        for q in ("min_n=1", "min_n=2", "min_n=3"):
            _serve(f"/api/skill-wpa?{q}", db, model_path)
    hits = [r for r in caplog.records if r.name == "rc.web_dashboard"
            and "model" in r.getMessage().lower()]
    assert len(hits) == 1, [r.getMessage() for r in hits]


# -- F3: an unusable model is not "trained"; strict JSON always ------------

def _write_model(path: Path, weights, n_samples=50):
    path.write_text(json.dumps({
        "version": pgs.WPA_MODEL_VERSION,
        "n_samples": n_samples,
        "feature_names": list(pgs.FEATURE_NAMES),
        "weights": list(weights),
    }), encoding="utf-8")


def test_f3_nan_model_is_fallback_and_strict_json(db, tmp_path):
    model_path = tmp_path / "model.json"
    # json.dumps writes NaN as a bare token that json.load reads back.
    _write_model(model_path, [float("nan")] * pgs.WPA_FEATURE_COUNT)
    status, payload = _one(_serve("/api/skill-wpa?min_n=1", db, model_path))
    assert status == 200
    assert payload["model"] == "fallback"
    assert payload["items"]


@pytest.mark.parametrize("n", [0, 3, pgs.WPA_FEATURE_COUNT + 1])
def test_f3_wrong_length_model_is_fallback(db, tmp_path, n):
    # predict_prob answers a constant 0.5 on a length mismatch, so every
    # expected_winrate read 0.5 while the payload claimed "trained".
    model_path = tmp_path / "model.json"
    _write_model(model_path, [0.3] * n)
    status, payload = _one(_serve("/api/skill-wpa?min_n=1", db, model_path))
    assert status == 200
    assert payload["model"] == "fallback"
    assert any(it["expected_winrate"] != 0.5 for it in payload["items"])


def test_f3_good_model_is_still_trained(db, tmp_path):
    model_path = tmp_path / "model.json"
    _write_model(model_path, [0.2] * pgs.WPA_FEATURE_COUNT)
    status, payload = _one(_serve("/api/skill-wpa?min_n=1", db, model_path))
    assert status == 200
    assert payload["model"] == "trained"


def test_f3_non_finite_payload_is_500_and_not_cached(db):
    def _nan_body(conn, min_n=20, queue_id=None, patch=None, model=None):
        return {"ok": True, "patch": None, "queue_id": None, "min_n": min_n,
                "items": [{"champion_id": AHRI, "wpa": float("nan")}]}
    with mock.patch.object(rsw, "compute_skill_wpa", _nan_body):
        status, payload = _one(_serve("/api/skill-wpa?min_n=1", db))
    assert status == 500
    assert payload["ok"] is False
    assert not rsw._CACHE


def test_f3_not_ok_payload_is_served_but_not_cached(db):
    def _not_ok(conn, min_n=20, queue_id=None, patch=None, model=None):
        return {"ok": False, "error": "no corpus"}
    with mock.patch.object(rsw, "compute_skill_wpa", _not_ok):
        status, payload = _one(_serve("/api/skill-wpa", db))
    assert status == 200
    assert payload["ok"] is False
    assert not rsw._CACHE


# -- F4: a retrain with the same signature invalidates the cache -----------

def test_f4_retrained_model_same_n_samples_is_a_cache_miss(db, tmp_path):
    model_path = tmp_path / "model.json"

    def _train(weights):
        pgs.save_model(pgs.WpaModel(weights=tuple(weights),
                                    feature_names=pgs.FEATURE_NAMES,
                                    n_samples=40), model_path)

    url = "/api/skill-wpa?min_n=1"
    _train([0.0] * pgs.WPA_FEATURE_COUNT)
    _s, first = _one(_serve(url, db, model_path))
    assert first["model"] == "trained"
    assert all(it["expected_winrate"] == 0.5 for it in first["items"])

    w = [0.0] * pgs.WPA_FEATURE_COUNT
    w[0] = 1.0  # gold_diff weight: the gold lead now moves the probability
    _train(w)
    _s, second = _one(_serve(url, db, model_path))
    assert second["cached"] is False
    assert any(it["expected_winrate"] != 0.5 for it in second["items"])


# -- F5: cache reads and writes hold the lock -------------------------------

class _LockCheckingDict(dict):
    def __setitem__(self, key, value):
        assert rsw._CACHE_LOCK.locked(), "cache written without its lock"
        super().__setitem__(key, value)

    def get(self, *a):
        assert rsw._CACHE_LOCK.locked(), "cache read without its lock"
        return super().get(*a)

    def pop(self, *a):
        assert rsw._CACHE_LOCK.locked(), "cache evicted without its lock"
        return super().pop(*a)


def test_f5_cache_put_get_and_evict_hold_the_lock():
    guarded = _LockCheckingDict()
    with mock.patch.object(rsw, "_CACHE", guarded):
        for i in range(300):
            rsw._cache_put((i, None, None, "fallback", 0), {"ok": True})
        assert len(guarded) <= 128
        assert rsw._cache_get((299, None, None, "fallback", 0)) == {"ok": True}


# -- F6: monotonic TTL ------------------------------------------------------

def test_f6_ttl_uses_the_monotonic_clock():
    key = (20, None, None, "fallback", 0)
    with mock.patch.object(rsw.time, "monotonic", return_value=1000.0), \
         mock.patch.object(rsw.time, "time", return_value=5_000_000.0):
        rsw._cache_put(key, {"ok": True})
    # Wall clock jumps backwards; the monotonic clock moves past the TTL.
    with mock.patch.object(rsw.time, "monotonic",
                           return_value=1000.0 + rsw._CACHE_TTL_S + 1), \
         mock.patch.object(rsw.time, "time", return_value=0.0):
        assert rsw._cache_get(key) is None


# -- F7: SQLite failure is a retryable 503 ----------------------------------

def test_f7_db_without_tables_is_503(tmp_path):
    p = tmp_path / "rh.db"
    sqlite3.connect(str(p)).close()  # exists, but no matches table
    status, payload = _one(_serve("/api/skill-wpa", p))
    assert status == 503
    assert payload["ok"] is False
    assert "no such table" not in payload["error"]
    assert not rsw._CACHE


def test_f7_locked_db_is_503(db):
    def _locked(conn, **kw):
        raise sqlite3.OperationalError("database is locked")
    with mock.patch.object(rsw, "compute_skill_wpa", _locked):
        status, payload = _one(_serve("/api/skill-wpa", db))
    assert status == 503
    assert "locked" not in payload["error"]


# -- F8: tracebacks logged, failed 500 send logged --------------------------

def test_f8_unexpected_failure_logs_traceback(db, caplog):
    def _boom(conn, **kw):
        raise KeyError("secret-shaped-fragment")
    with mock.patch.object(rsw, "compute_skill_wpa", _boom), \
         caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        status, payload = _one(_serve("/api/skill-wpa", db))
    assert status == 500
    assert "secret-shaped-fragment" not in json.dumps(payload)
    assert any(r.exc_info for r in caplog.records), \
        "unexpected failure logged without a traceback"


def test_f8_failed_500_send_is_logged(db, caplog):
    class _BrokenHandler(_StubHandler):
        def _send(self, status, body, content_type="application/json",
                  cache_control=None):
            raise ConnectionResetError("client went away")

    def _boom(conn, **kw):
        raise KeyError("x")
    with mock.patch.object(rsw, "_REWIND_DB", db), \
         mock.patch.object(rsw, "_MODEL_PATH", db.parent / "absent.json"), \
         mock.patch.object(rsw, "compute_skill_wpa", _boom), \
         caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        rsw._serve_skill_wpa(_BrokenHandler("/api/skill-wpa"))
    assert any("500" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]


# -- F9: DB URI survives URI-special characters in the path ------------------

@pytest.mark.parametrize("dirname", ["a#b", "pct%41dir", "sp ace"])
def test_f9_db_path_with_uri_special_chars(tmp_path, dirname):
    d = tmp_path / dirname
    d.mkdir()
    p = _seed(d / "rh.db")
    status, payload = _one(_serve("/api/skill-wpa?min_n=1", p))
    assert status == 200, payload
    assert payload["ok"] is True
    assert payload["items"]


def test_f9_db_is_opened_read_only(db):
    def _try_write(conn, **kw):
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE should_fail(x)")
        return {"ok": True, "items": []}
    with mock.patch.object(rsw, "compute_skill_wpa", _try_write):
        status, _payload = _one(_serve("/api/skill-wpa", db))
    assert status == 200


# -- F10: a transient stat failure keeps the loaded model --------------------

def test_f10_transient_stat_failure_keeps_the_trained_model(db, tmp_path):
    model_path = tmp_path / "model.json"
    _write_model(model_path, [0.2] * pgs.WPA_FEATURE_COUNT)
    _s, first = _one(_serve("/api/skill-wpa?min_n=1", db, model_path))
    assert first["model"] == "trained"

    real_stat = Path.stat

    def _flaky_stat(self, *a, **kw):
        if self == model_path:
            raise PermissionError(13, "sharing violation")
        return real_stat(self, *a, **kw)
    with mock.patch.object(Path, "stat", _flaky_stat):
        _s, second = _one(_serve("/api/skill-wpa?min_n=2", db, model_path))
    assert second["model"] == "trained"


# -- F11: the docstring states the real contract ------------------------------

def test_f11_docstring_failure_contract():
    doc = rsw.__doc__ or ""
    assert "400" in doc and "503" in doc and "500" in doc
    # The pre-audit docstring promised "ok=false (200) - compute raised";
    # a raise was really a 500.
    assert "compute raised" not in doc


def test_f11_docstring_names_every_row_field(db):
    doc = rsw.__doc__ or ""
    status, payload = _one(_serve("/api/skill-wpa?min_n=1", db))
    assert status == 200 and payload["items"]
    for field in list(payload["items"][0]) + ["model"]:
        assert f'"{field}"' in doc, f"docstring omits {field!r}"
