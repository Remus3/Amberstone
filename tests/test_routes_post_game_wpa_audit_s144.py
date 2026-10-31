"""s144 true-audit cycle 86: dashboard/routes_post_game_wpa.py hardening.

One test (or one small group) per finding, each written RED against the
pre-audit route and mutation-checked against the fix:

  F1  match_id is validated: 1-64 chars of [A-Za-z0-9_-], given once.
  F2  a model file load_model does not catch (list-shaped JSON, an
      overflowing n_samples, a too-deep document) no longer turns every
      request into a 500 until the file changes.
  F3  a model whose weights are non-finite or the wrong length is not
      served as "trained" (it made NaN / constant-0.5 output); the
      response body is always strict JSON.
  F4  a retrained model with the same version + n_samples invalidates the
      response cache (the signature alone did not change).
  F5  the response cache is written only under its lock.
  F6  the cache TTL runs on the monotonic clock.
  F7  a SQLite failure is a retryable 503, not a generic 500.
  F8  an unexpected failure is logged WITH its traceback, and a failed
      500 send is logged instead of swallowed.
  F9  the read-only DB URI survives a '#', '%' or '?' in the repo path.
  F10 _wpa_totals skips a non-finite wpa instead of poisoning the sums.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from core import post_game_score as pgs
from dashboard import routes_post_game_wpa as rpgw
from tests.test_routes_post_game_wpa import _seed_db, _StubHandler


@pytest.fixture(autouse=True)
def _reset_module_state():
    rpgw._CACHE.clear()
    rpgw._MODEL_CACHE["mtime"] = None
    rpgw._MODEL_CACHE["model"] = None
    yield
    rpgw._CACHE.clear()
    rpgw._MODEL_CACHE["mtime"] = None
    rpgw._MODEL_CACHE["model"] = None


def _serve(path: str, db: Path, model_path: Path | None = None):
    with mock.patch.object(rpgw, "_REWIND_DB", db), \
         mock.patch.object(rpgw, "_MODEL_PATH",
                           model_path or db.parent / "absent_model.json"):
        h = _StubHandler(path)
        rpgw._serve_post_game_wpa(h)
        return h.responses


def _one(responses):
    assert len(responses) == 1, responses
    status, body, _ct = responses[0]
    # Strict JSON: a NaN / Infinity token must never reach the browser.
    payload = json.loads(body, parse_constant=_refuse_constant)
    return status, payload


def _refuse_constant(name):
    raise AssertionError(f"non-strict JSON constant in response: {name}")


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "rh.db"
    _seed_db(p, "NA1_1000000001")
    return p


# -- F1: match_id validation ---------------------------------------------

@pytest.mark.parametrize("raw", [
    pytest.param("x" * 65, id="65-chars"),
    "NA1_1%00",               # control character
    "NA1_1%0A",               # newline
    "NA1%201",                # space inside
    "NA1_%C2%B9",             # non-ASCII digit
    "NA1_1%3B--",             # punctuation
    "_NA1_1",                 # must start alphanumeric
    "..%2F..%2Fetc",
])
def test_f1_malformed_match_id_is_400_without_echo(db, raw):
    status, payload = _one(_serve(f"/api/post-game-wpa?match_id={raw}", db))
    assert status == 400
    assert payload["ok"] is False
    assert "match_id" in payload["error"]
    # The rejected value is not reflected back.
    assert "match_id" not in {k for k in payload if k != "error"}
    assert "x" * 65 not in payload["error"]


def test_f1_repeated_match_id_is_400(db):
    status, payload = _one(_serve(
        "/api/post-game-wpa?match_id=NA1_1000000001&match_id=NA1_2", db))
    assert status == 400
    assert payload["ok"] is False


@pytest.mark.parametrize("ok_id", ["NA1_1000000001", "EUW1_7", "7001",
                                   "TEST_M1", "a-b_c"])
def test_f1_well_formed_ids_still_reach_the_db(tmp_path, ok_id):
    p = tmp_path / "rh.db"
    _seed_db(p, ok_id)
    status, payload = _one(_serve(f"/api/post-game-wpa?match_id={ok_id}", p))
    assert status == 200
    assert payload["ok"] is True
    assert payload["match_id"] == ok_id


def test_f1_64_char_id_is_accepted(tmp_path):
    mid = "A" * 64
    p = tmp_path / "rh.db"
    _seed_db(p, mid)
    status, _payload = _one(_serve(f"/api/post-game-wpa?match_id={mid}", p))
    assert status == 200


# -- F2: a model file load_model does not catch ----------------------------

@pytest.mark.parametrize("doc", [
    pytest.param("[1, 2, 3]", id="list-AttributeError"),
    pytest.param('"just a string"', id="string-AttributeError"),
    pytest.param('{"weights": [], "n_samples": 1e999}',
                 id="n_samples-OverflowError"),
    pytest.param("[" * 100000 + "]" * 100000, id="deep-RecursionError"),
])
def test_f2_unloadable_model_falls_back_instead_of_500(db, tmp_path, doc):
    model_path = tmp_path / "model.json"
    model_path.write_text(doc, encoding="utf-8")
    for _ in range(2):
        status, payload = _one(_serve(
            "/api/post-game-wpa?match_id=NA1_1000000001", db, model_path))
        assert status == 200
        assert payload["ok"] is True
        assert payload["model"] == "fallback"


def test_f2_bad_model_is_logged_once_per_file_version(db, tmp_path, caplog):
    model_path = tmp_path / "model.json"
    model_path.write_text("[1]", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        for _ in range(3):
            _serve("/api/post-game-wpa?match_id=NA1_1000000001", db,
                   model_path)
    hits = [r for r in caplog.records if "model" in r.getMessage().lower()
            and r.levelno >= logging.WARNING]
    assert len(hits) == 1, [r.getMessage() for r in hits]


# -- F3: an unusable model is not "trained"; strict JSON always ------------

def _write_model(path: Path, weights, n_samples=50):
    path.write_text(json.dumps({
        "version": pgs.WPA_MODEL_VERSION,
        "n_samples": n_samples,
        "feature_names": list(pgs.FEATURE_NAMES),
        "weights": list(weights),
    }), encoding="utf-8")


@pytest.mark.parametrize("weights", [
    [float("nan")] * pgs.WPA_FEATURE_COUNT,
])
def test_f3_model_output_is_strict_json(db, tmp_path, weights):
    model_path = tmp_path / "model.json"
    # json.dumps writes NaN as a bare token, which json.load reads back:
    # exactly what a bad trainer would leave on disk.
    model_path.write_text(json.dumps({
        "version": pgs.WPA_MODEL_VERSION, "n_samples": 5,
        "feature_names": list(pgs.FEATURE_NAMES), "weights": weights,
    }), encoding="utf-8")
    status, payload = _one(_serve(
        "/api/post-game-wpa?match_id=NA1_1000000001", db, model_path))
    assert status == 200
    for ev in payload["events"]:
        assert math.isfinite(ev["wpa"])


def test_f3_non_finite_model_is_fallback(db, tmp_path):
    model_path = tmp_path / "model.json"
    w = [0.0] * pgs.WPA_FEATURE_COUNT
    w[0] = float("inf")
    model_path.write_text(json.dumps({
        "version": pgs.WPA_MODEL_VERSION, "n_samples": 5,
        "feature_names": list(pgs.FEATURE_NAMES), "weights": w,
    }), encoding="utf-8")
    status, payload = _one(_serve(
        "/api/post-game-wpa?match_id=NA1_1000000001", db, model_path))
    assert status == 200
    assert payload["model"] == "fallback"


@pytest.mark.parametrize("n", [0, 3, pgs.WPA_FEATURE_COUNT + 1])
def test_f3_wrong_length_model_is_fallback(db, tmp_path, n):
    # predict_prob answers a constant 0.5 on a length mismatch, so every
    # event read wpa 0.0 while the payload claimed "trained".
    model_path = tmp_path / "model.json"
    _write_model(model_path, [0.3] * n)
    status, payload = _one(_serve(
        "/api/post-game-wpa?match_id=NA1_1000000001", db, model_path))
    assert status == 200
    assert payload["model"] == "fallback"
    assert any(ev["wpa"] != 0.0 for ev in payload["events"])


def test_f3_good_model_is_still_trained(db, tmp_path):
    model_path = tmp_path / "model.json"
    _write_model(model_path, [0.2] * pgs.WPA_FEATURE_COUNT)
    status, payload = _one(_serve(
        "/api/post-game-wpa?match_id=NA1_1000000001", db, model_path))
    assert status == 200
    assert payload["model"] == "trained"


def test_f3_non_finite_payload_is_500_not_invalid_json(db):
    def _nan_body(conn, match_id, model=None):
        return {"ok": True, "match_id": match_id,
                "events": [{"game_time": 1, "wpa": float("nan")}],
                "top_phases": [], "frame_count": 1, "event_count": 1}
    with mock.patch.object(rpgw, "compute_match_wpa", _nan_body):
        status, payload = _one(_serve(
            "/api/post-game-wpa?match_id=NA1_1000000001", db))
    assert status == 500
    assert payload["ok"] is False
    # ...and the unserialisable payload was not cached.
    assert not rpgw._CACHE


# -- F4: a retrain with the same signature invalidates the cache -----------

def test_f4_retrained_model_same_n_samples_is_a_cache_miss(db, tmp_path):
    # The trainer writes through pgs.save_model (atomic tmp + replace), so
    # a retrain lands as a NEW file even when it is the same size and the
    # clock tick (about 15 ms on Windows) has not moved.
    model_path = tmp_path / "model.json"

    def _train(weights):
        pgs.save_model(pgs.WpaModel(weights=tuple(weights),
                                    feature_names=pgs.FEATURE_NAMES,
                                    n_samples=40), model_path)

    url = "/api/post-game-wpa?match_id=NA1_1000000001"
    _train([0.0] * pgs.WPA_FEATURE_COUNT)
    _s, first = _one(_serve(url, db, model_path))
    assert first["model"] == "trained"
    assert all(ev["wpa"] == 0.0 for ev in first["events"])

    w = [0.0] * pgs.WPA_FEATURE_COUNT
    w[2] = 1.0  # kill_diff weight: a kill now moves the probability
    _train(w)
    _s, second = _one(_serve(url, db, model_path))
    assert second["cached"] is False
    assert any(ev["wpa"] != 0.0 for ev in second["events"])


# -- F5: cache writes hold the lock -----------------------------------------

class _LockCheckingDict(dict):
    def __setitem__(self, key, value):
        assert rpgw._CACHE_LOCK.locked(), "cache written without its lock"
        super().__setitem__(key, value)

    def pop(self, *a):
        assert rpgw._CACHE_LOCK.locked(), "cache evicted without its lock"
        return super().pop(*a)


def test_f5_cache_put_and_evict_hold_the_lock():
    guarded = _LockCheckingDict()
    with mock.patch.object(rpgw, "_CACHE", guarded):
        for i in range(300):
            rpgw._cache_put((f"M{i}", "fallback", 0), {"ok": True})
        assert len(guarded) <= 256
        assert rpgw._cache_get(("M299", "fallback", 0)) == {"ok": True}


# -- F6: monotonic TTL --------------------------------------------------------

def test_f6_ttl_uses_the_monotonic_clock():
    key = ("M1", "fallback", 0)
    with mock.patch.object(rpgw.time, "monotonic", return_value=1000.0):
        rpgw._cache_put(key, {"ok": True})
    # Wall clock jumps backwards a day; the monotonic clock moves on.
    with mock.patch.object(rpgw.time, "monotonic",
                           return_value=1000.0 + rpgw._CACHE_TTL_S + 1), \
         mock.patch.object(rpgw.time, "time", return_value=0.0):
        assert rpgw._cache_get(key) is None


# -- F7: SQLite failure is a retryable 503 -----------------------------------

def test_f7_db_without_tables_is_503(tmp_path):
    p = tmp_path / "rh.db"
    sqlite3.connect(str(p)).close()  # exists, but no matches table
    status, payload = _one(_serve("/api/post-game-wpa?match_id=NA1_1", p))
    assert status == 503
    assert payload["ok"] is False
    assert "no such table" not in payload["error"]


def test_f7_locked_db_is_503(db):
    def _locked(conn, match_id):
        raise sqlite3.OperationalError("database is locked")
    with mock.patch.object(rpgw, "_match_exists", _locked):
        status, payload = _one(_serve(
            "/api/post-game-wpa?match_id=NA1_1000000001", db))
    assert status == 503
    assert "locked" not in payload["error"]


# -- F8: tracebacks logged, failed 500 send logged ---------------------------

def test_f8_unexpected_failure_logs_traceback(db, caplog):
    def _boom(conn, match_id, model=None):
        raise KeyError("secret-shaped-fragment")
    with mock.patch.object(rpgw, "compute_match_wpa", _boom), \
         caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        status, payload = _one(_serve(
            "/api/post-game-wpa?match_id=NA1_1000000001", db))
    assert status == 500
    assert "secret-shaped-fragment" not in json.dumps(payload)
    assert any(r.exc_info for r in caplog.records), \
        "unexpected failure logged without a traceback"


def test_f8_failed_500_send_is_logged(db, caplog):
    class _BrokenHandler(_StubHandler):
        def _send(self, status, body, content_type="application/json"):
            raise ConnectionResetError("client went away")

    def _boom(conn, match_id, model=None):
        raise KeyError("x")
    with mock.patch.object(rpgw, "_REWIND_DB", db), \
         mock.patch.object(rpgw, "_MODEL_PATH", db.parent / "absent.json"), \
         mock.patch.object(rpgw, "compute_match_wpa", _boom), \
         caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        rpgw._serve_post_game_wpa(
            _BrokenHandler("/api/post-game-wpa?match_id=NA1_1000000001"))
    assert any("500" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]


# -- F9: DB URI survives URI-special characters in the path -------------------

@pytest.mark.parametrize("dirname", ["a#b", "pct%41dir", "sp ace"])
def test_f9_db_path_with_uri_special_chars(tmp_path, dirname):
    d = tmp_path / dirname
    d.mkdir()
    p = d / "rh.db"
    _seed_db(p, "NA1_1000000001")
    status, payload = _one(_serve(
        "/api/post-game-wpa?match_id=NA1_1000000001", p))
    assert status == 200
    assert payload["ok"] is True


def test_f9_db_is_opened_read_only(db):
    seen = {}
    real_connect = sqlite3.connect

    def _spy(*a, **kw):
        conn = real_connect(*a, **kw)
        seen["conn"] = conn
        return conn

    def _try_write(conn, match_id):
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE should_fail(x)")
        return False
    with mock.patch.object(rpgw.sqlite3, "connect", _spy), \
         mock.patch.object(rpgw, "_match_exists", _try_write):
        status, _payload = _one(_serve(
            "/api/post-game-wpa?match_id=NA1_1000000001", db))
    assert status == 404
    assert "conn" in seen


# -- F10: non-finite wpa is skipped in the totals -----------------------------

def test_f10_totals_skip_non_finite_wpa():
    t = rpgw._wpa_totals([
        {"game_time": 10, "wpa": float("nan")},
        {"game_time": 20, "wpa": float("inf")},
        {"game_time": 30, "wpa": 0.05},
    ])
    assert t["full"]["events"] == 1
    assert t["full"]["net_wpa"] == 0.05
    assert math.isfinite(t["lane_share"])
