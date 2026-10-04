"""RM-259 - a failed rating write must not be reported as a success, and a
stale rating file must not enrich the next post-game summary.

(1) performance_tracker.save_rating / save_tft_rating swallow their own
    rating-file write failure; app/_game_lifecycle.py then logged
    "Performance rating saved" (and "<mode> rating saved: <g>") regardless.
    The functions now fill an optional ``report`` dict ({"rated",
    "file_written"}) - an out-of-band channel, because :201 unpacks
    ``g, n = save_rating(...)`` and a third return value would break it.
(2) the stale file keeps its stale mtime, so _latest_rating_file still picks
    it and agents/supervisor.py copied rating/label/stats/notes/mode_category
    from a PRIOR game (possibly another mode) into THIS game's summary.
    The supervisor now refuses a rating file whose mtime predates the match
    being summarised.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import types

import pytest

import performance_tracker as pt


# ------------------------------------------------------------- save_rating

def _valid_sr_state():
    return {"game_mode": "CLASSIC", "game_seconds": 1500, "gold": 12000,
            "cs_per_min": 7.1, "kills": 5, "deaths": 2, "assists": 7,
            "kda": "5/2/7", "game_time": "25:00"}


@pytest.fixture
def _no_side_effects(monkeypatch):
    monkeypatch.setattr(pt, "_get_db", lambda sd: None)
    fake_fb = types.ModuleType("coaches.feedback")
    fake_fb.apply_grade = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "coaches.feedback", fake_fb)
    fake_eb = types.ModuleType("coaches.experimental_builder")
    fake_eb.consume_active = lambda: None
    monkeypatch.setitem(sys.modules, "coaches.experimental_builder", fake_eb)


def test_save_rating_reports_written(tmp_path, _no_side_effects):
    rep = {}
    g, n = pt.save_rating(str(tmp_path), "Ahri", _valid_sr_state(), 15, report=rep)
    assert g
    assert rep == {"rated": True, "file_written": True}


def test_save_rating_reports_failed_write(tmp_path, monkeypatch, _no_side_effects):
    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(pt, "_atomic_write_json", _boom)
    rep = {}
    g, n = pt.save_rating(str(tmp_path), "Ahri", _valid_sr_state(), 15, report=rep)
    assert g, "the grade is still computed (DB row path unchanged)"
    assert rep == {"rated": True, "file_written": False}


def test_save_rating_reports_unrated(tmp_path, _no_side_effects):
    rep = {}
    st = _valid_sr_state()
    st["game_seconds"] = 60  # below the 180 s validity floor
    assert pt.save_rating(str(tmp_path), "Ahri", st, 15, report=rep) == ("", [])
    assert rep == {"rated": False, "file_written": False}


def test_save_rating_positional_contract_unchanged(tmp_path, _no_side_effects):
    g, n = pt.save_rating(str(tmp_path), "Ahri", _valid_sr_state(), 15)
    assert g and isinstance(n, list)


# ---------------------------------------------------------- lifecycle logs

class _App:
    def __init__(self, state, **modes):
        self._game_state = state
        self._tft_mode = modes.get("tft", False)
        self._arena_mode = False
        self._brawl_mode = False
        self._aram_mode = modes.get("aram", False)
        self._tft_coach = None
        self._tft_worker = None
        self._sr_aram_worker = None
        self._coach = None
        self.data = {}
        import queue
        self._tft_q = queue.Queue()

    def _write_data(self, fields=None):
        pass

    def _update_envelope(self, *a, **k):
        pass


def _run_game_end(monkeypatch, app, written):
    from app import _game_lifecycle as gl
    monkeypatch.setattr(gl, "HAS_POSTGAME", False)
    fake_rlw = types.ModuleType("lib.rewind_live_writer")
    fake_rlw.schedule_live_insert = lambda app: None
    monkeypatch.setitem(sys.modules, "lib.rewind_live_writer", fake_rlw)

    def _fake_save(*a, report=None, **k):
        if report is not None:
            report.update(rated=True, file_written=written)
        return ("A", ["note"])

    monkeypatch.setattr(gl, "save_rating", _fake_save, raising=False)
    monkeypatch.setattr(gl, "save_tft_rating", _fake_save, raising=False)
    monkeypatch.setattr(gl, "HAS_TRACKER", True)
    gl.GameLifecycleManager(app).on_game_end()


def _msgs(caplog):
    return [(r.levelno, r.getMessage()) for r in caplog.records
            if r.name == "rc.app.lifecycle"]


def test_sr_failed_write_is_not_logged_as_saved(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="rc.app.lifecycle")
    _run_game_end(monkeypatch, _App({"game_mode": "CLASSIC", "champion": "Ahri"}), False)
    msgs = _msgs(caplog)
    assert not any("rating saved" in m.lower() for _, m in msgs), msgs
    assert any(lv >= logging.WARNING and "not saved" in m.lower() for lv, m in msgs), msgs


def test_sr_good_write_still_logs_saved(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="rc.app.lifecycle")
    _run_game_end(monkeypatch, _App({"game_mode": "CLASSIC", "champion": "Ahri"}), True)
    assert any("performance rating saved" in m.lower() for _, m in _msgs(caplog))


def test_tft_failed_write_is_not_logged_as_saved(monkeypatch, caplog, tmp_path):
    caplog.set_level(logging.INFO, logger="rc.app.lifecycle")
    _run_game_end(monkeypatch, _App({}, tft=True), False)
    msgs = _msgs(caplog)
    assert not any("rating saved" in m.lower() for _, m in msgs), msgs
    assert any(lv >= logging.WARNING and "not saved" in m.lower() for lv, m in msgs), msgs


def test_special_mode_failed_write_is_not_logged_as_saved(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="rc.app.lifecycle")
    _run_game_end(monkeypatch, _App({"game_mode": "ARAM", "champion": "Ahri"},
                                    aram=True), False)
    msgs = _msgs(caplog)
    assert not any("rating saved" in m.lower() for _, m in msgs), msgs
    assert any(lv >= logging.WARNING and "not saved" in m.lower() for lv, m in msgs), msgs


# ------------------------------------------------------ supervisor summary

class _Sched:
    def __init__(self):
        self.calls = []

    def file_task(self, **kw):
        self.calls.append(kw)
        return "t"


def _summary(monkeypatch, tmp_path, rating_age_s, game_time_s):
    import agents.supervisor as sup_mod
    monkeypatch.setattr(sup_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pt, "_ratings_dir", lambda sd: tmp_path / "ratings")
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "ratings").mkdir(exist_ok=True)
    cd = {"mode": "game", "game_mode": "ARAM", "champion": "Ahri"}
    if game_time_s is not None:
        cd["game_time_s"] = game_time_s
    (tmp_path / "data" / "aram_coaching_data.json").write_text(
        json.dumps(cd), encoding="utf-8")
    rf = tmp_path / "ratings" / "last_sr.json"
    rf.write_text(json.dumps({"rating": "S", "label": "old", "mode_category": "SR",
                              "stats": {}, "notes": ["prior game"]}), encoding="utf-8")
    t = time.time() - rating_age_s
    os.utime(rf, (t, t))
    sup = object.__new__(sup_mod.Supervisor)
    sup._scheduler = _Sched()
    sup._file_post_game_summary("game", "post_game")
    assert sup._scheduler.calls, "summary should still be filed"
    return sup._scheduler.calls[0]["payload"]


def test_prior_game_rating_does_not_enrich_summary(monkeypatch, tmp_path):
    # 20-minute game just ended; rating file is 45 minutes old -> prior game.
    p = _summary(monkeypatch, tmp_path, rating_age_s=45 * 60, game_time_s=1200)
    assert "rating" not in p and "mode_category" not in p, p
    assert p.get("rating_stale") is True


def test_stale_rating_rejected_without_game_time(monkeypatch, tmp_path):
    p = _summary(monkeypatch, tmp_path, rating_age_s=3 * 3600, game_time_s=None)
    assert "rating" not in p, p


def test_fresh_rating_still_enriches_summary(monkeypatch, tmp_path):
    p = _summary(monkeypatch, tmp_path, rating_age_s=5, game_time_s=1200)
    assert p.get("rating") == "S"
    assert "rating_stale" not in p
