"""Lane 8 (true-audit) session 134 cycle 4 - ops/rc_state_validator.py.

Characterization + regression tests for the low-rate StateValidator that
rc_self_monitor.py:327-334 runs when the self-monitor profile enables
screen validation (rc_supervisor.py:1508-1513 is its only constructor).

Ground truth cited before writing:
  - the TFT facade seeds data/tft_live_data.json with hp=0 and
    stage_round="" at every reset (coaches/tft_coach.py:264-268), and the
    live producer clamps an out-of-range hp to 0 (tft/tft_live_analysis.py
    _coerce_hp, :311-328). Measured live 2026-10-25 during a TFT game: the
    file held exactly that seed, 13 minutes old, with health.json
    has_game=True and tft_mode=True.
  - the engine's TFT coach artifact carries a "stage_round" string AND INT
    stage / round (tft/tft_coach_engine.py :820-825); a TftPayload-shaped
    writer (core/coaching_payload.py :187-188) carries only the ints. Check 4
    compared the strings EXACTLY although its own comment says the two "may
    be legitimately 1 round apart", so every round transition was a WARN.
  - SelfMonitor swallows any exception from maybe_run()
    (rc_self_monitor.py:329-334), and StateValidator.maybe_run() advances
    _last_run before it calls run_once(), so a raise inside run_once()
    silently skips every check for that cadence window.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OPS_DIR = _REPO_ROOT / "ops"
if str(_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(_OPS_DIR))

import rc_state_validator  # noqa: E402  (path-insert must precede import)


class _Log:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, **kwargs) -> dict:
        self.entries.append(kwargs)
        return kwargs


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _age(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


def _tft_root(tmp_path: Path, live=None, coach=None) -> Path:
    _write(tmp_path / "ops" / "runtime" / "health.json",
           {"mode": "game", "tft_mode": True, "has_game": True})
    if live is not None:
        _write(tmp_path / "data" / "tft_live_data.json", live)
    if coach is not None:
        _write(tmp_path / "data" / "tft_coaching_data.json", coach)
    return tmp_path


def _sv(root: Path, **kw) -> rc_state_validator.StateValidator:
    return rc_state_validator.StateValidator(project_root=root, incident_log=_Log(), **kw)


def _triggers(report) -> set:
    return {m["trigger"] for m in report["mismatches"]}


# -- characterization (behaviour that must survive the rewrite) --------------

def test_missing_health_reports_and_stops(tmp_path):
    report = _sv(tmp_path).run_once()
    assert report["checks"] == ["health_file_missing"]
    assert report["mismatches"] == []


def test_invalid_health_mode_flagged(tmp_path):
    _write(tmp_path / "ops" / "runtime" / "health.json", {"mode": "bogus"})
    report = _sv(tmp_path).run_once()
    assert "mode_invalid" in _triggers(report)
    assert report["ok"] is False


def test_sr_coaching_stale_flagged(tmp_path):
    _write(tmp_path / "ops" / "runtime" / "health.json",
           {"mode": "game", "tft_mode": False, "has_game": True})
    _age(_write(tmp_path / "coaching_data.json", {"mode": "game"}), 600)
    report = _sv(tmp_path).run_once()
    assert "coaching_stale" in _triggers(report)


def test_healthy_tft_tick_is_ok(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 64, "stage_round": "3-2"},
                     coach={"stage": 3, "round": 2})
    report = _sv(root).run_once()
    assert report["ok"] is True, report["mismatches"]
    assert report["mismatch_count"] == 0


def test_mismatch_reaches_incident_log(tmp_path):
    _write(tmp_path / "ops" / "runtime" / "health.json", {"mode": "bogus"})
    sv = _sv(tmp_path)
    sv.run_once()
    (entry,) = sv.incident_log.entries
    assert entry["subsystem"] == "validator"
    assert entry["trigger"] == "mode_invalid"


def test_maybe_run_respects_interval(tmp_path):
    sv = _sv(_tft_root(tmp_path, live={"hp": 50, "stage_round": "2-1"}))
    assert sv.maybe_run() is not None
    assert sv.maybe_run() is None


# -- F1: hp=0 is the producer's seed / clamp target, not out of range --------

def test_reset_seed_hp_zero_is_not_out_of_range(tmp_path):
    root = _tft_root(tmp_path, live={"mode": "tft_live", "stage_round": "", "level": 0, "hp": 0})
    report = _sv(root).run_once()
    assert "tft_hp_out_of_range" not in _triggers(report)


@pytest.mark.parametrize("hp", [101, -1, 150])
def test_hp_outside_zero_to_hundred_still_flagged(tmp_path, hp):
    root = _tft_root(tmp_path, live={"hp": hp, "stage_round": "3-2"})
    assert "tft_hp_out_of_range" in _triggers(_sv(root).run_once())


# -- F2: a stuck tft_live_data.json during a TFT game was never flagged ------

def test_stale_tft_live_file_flagged(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 0, "stage_round": ""})
    _age(root / "data" / "tft_live_data.json", 13 * 60)
    report = _sv(root).run_once()
    assert "tft_live_stale" in _triggers(report)
    assert any(c.startswith("tft_live_age=") for c in report["checks"])


def test_fresh_tft_live_file_not_stale(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 40, "stage_round": "4-1"})
    assert "tft_live_stale" not in _triggers(_sv(root).run_once())


def test_live_freshness_not_checked_outside_a_game(tmp_path):
    _write(tmp_path / "ops" / "runtime" / "health.json",
           {"mode": "client", "tft_mode": True, "has_game": False})
    _age(_write(tmp_path / "data" / "tft_live_data.json", {"hp": 0}), 3600)
    assert "tft_live_stale" not in _triggers(_sv(tmp_path).run_once())


# -- F3: coach-vs-live round check: one round apart is not a mismatch --------

def _engine_coach(stage: int, rnd: int) -> dict:
    # The shape tft/tft_coach_engine.py writes: string AND ints.
    return {"mode": "tft", "stage": stage, "round": rnd,
            "stage_round": f"{stage}-{rnd}"}


def test_engine_shaped_coach_one_round_behind_not_flagged(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "3-3"},
                     coach=_engine_coach(3, 2))
    assert "tft_round_mismatch" not in _triggers(_sv(root).run_once())


def test_engine_shaped_coach_far_behind_flagged(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "4-5"},
                     coach=_engine_coach(3, 2))
    assert "tft_round_mismatch" in _triggers(_sv(root).run_once())


def test_coach_string_wins_over_ints(tmp_path):
    coach = {"stage": 3, "round": 2, "stage_round": "4-5"}
    assert rc_state_validator._coach_stage_round(coach) == "4-5"


def test_coach_int_stage_round_compared_against_live(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "4-5"},
                     coach={"stage": 3, "round": 2})
    assert "tft_round_mismatch" in _triggers(_sv(root).run_once())


def test_coach_one_round_behind_is_tolerated(tmp_path):
    # The check's own comment: "they may be legitimately 1 round apart".
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "3-3"},
                     coach={"stage": 3, "round": 2})
    assert "tft_round_mismatch" not in _triggers(_sv(root).run_once())


def test_coach_zero_stage_means_unknown(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "4-5"},
                     coach={"stage": 0, "round": 0})
    assert "tft_round_mismatch" not in _triggers(_sv(root).run_once())


def test_coach_stage_round_string_only_compared(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "5-1"},
                     coach={"stage_round": "2-1"})
    assert "tft_round_mismatch" in _triggers(_sv(root).run_once())


# -- F4: round distance must not jump at a stage boundary --------------------

@pytest.mark.parametrize("a,b,expected", [
    ("2-7", "3-1", 1),
    ("1-4", "2-1", 1),
    ("3-2", "3-2", 0),
    ("3-1", "3-4", 3),
    ("2-1", "4-1", 14),
])
def test_round_distance_is_ordinal(a, b, expected):
    assert rc_state_validator._round_distance(a, b) == expected


@pytest.mark.parametrize("bad", ["", "-", "3", "3-x", None, 7, "1-2-3"])
def test_round_distance_unparseable_is_none(bad):
    assert rc_state_validator._round_distance(bad, "3-1") is None
    assert rc_state_validator._round_distance("3-1", bad) is None


class _FakeOcr:
    built = 0

    def __init__(self, sr="3-1", available=True):
        type(self).built += 1
        self._sr = sr
        self.available = available

    def read_stage_round_only(self):
        return self._sr


def _ocr_validator(root, monkeypatch, sr="3-1"):
    _FakeOcr.built = 0
    monkeypatch.setattr(rc_state_validator, "_HAS_OCR", True)
    monkeypatch.setattr(rc_state_validator, "_TftOcrReader",
                        lambda: _FakeOcr(sr=sr), raising=False)
    return _sv(root, ocr_enabled=True)


def test_ocr_one_round_across_stage_boundary_not_flagged(tmp_path, monkeypatch):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "2-7"})
    report = _ocr_validator(root, monkeypatch, sr="3-1").run_once()
    assert "ocr_round_mismatch" not in _triggers(report)
    assert "ocr_sr=3-1" in report["checks"]


def test_ocr_far_apart_flagged(tmp_path, monkeypatch):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "2-1"})
    report = _ocr_validator(root, monkeypatch, sr="4-1").run_once()
    assert "ocr_round_mismatch" in _triggers(report)


# -- F5 (RM-903): one OCR reader per validator, not one per check ---------

def test_ocr_reader_built_once_across_checks(tmp_path, monkeypatch):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "3-1"})
    sv = _ocr_validator(root, monkeypatch)
    sv.run_once()
    sv.run_once()
    sv.run_once()
    assert _FakeOcr.built == 1


def test_ocr_reader_construction_failure_disables_ocr(tmp_path, monkeypatch):
    calls = []

    def _boom():
        calls.append(1)
        raise RuntimeError("tesseract probe failed")

    monkeypatch.setattr(rc_state_validator, "_HAS_OCR", True)
    monkeypatch.setattr(rc_state_validator, "_TftOcrReader", _boom, raising=False)
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "3-1"})
    sv = _sv(root, ocr_enabled=True)
    sv.run_once()
    report = sv.run_once()
    assert len(calls) == 1
    assert report["ok"] is True


# -- F6: a JSON file that is not an object aborted the whole run -------------

@pytest.mark.parametrize("payload", [[1, 2], "text", 3])
def test_non_object_health_is_treated_as_missing(tmp_path, payload):
    _write(tmp_path / "ops" / "runtime" / "health.json", payload)
    report = _sv(tmp_path).run_once()
    assert report["checks"] == ["health_file_missing"]


def test_non_object_live_file_does_not_abort_later_checks(tmp_path):
    root = _tft_root(tmp_path, live=[{"hp": 50}], coach={"stage": 3, "round": 2})
    _age(root / "data" / "tft_coaching_data.json", 600)
    report = _sv(root).run_once()
    # check 5 (coach freshness) still ran after the list-shaped live file.
    assert "tft_coaching_stale" in _triggers(report)


def test_corrupt_json_reads_as_none(tmp_path):
    p = tmp_path / "x.json"
    p.write_bytes(b"{not json")
    assert rc_state_validator.StateValidator._read_json(p) is None


def test_deeply_nested_json_reads_as_none(tmp_path):
    p = tmp_path / "deep.json"
    p.write_bytes(b"[" * 200000 + b"]" * 200000)
    assert rc_state_validator.StateValidator._read_json(p) is None


def test_non_string_stage_round_does_not_abort(tmp_path):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": 32},
                     coach={"stage": 3, "round": 2})
    report = _sv(root).run_once()
    assert "tft_stage_round_invalid" in _triggers(report)
    assert "mismatch_count" in report


# -- F7: a file that vanishes between exists() and stat() aborted the run ----

def test_file_age_missing_is_none(tmp_path):
    assert rc_state_validator._file_age_s(tmp_path / "gone.json") is None


def test_coach_file_vanishing_mid_check_does_not_abort(tmp_path, monkeypatch):
    root = _tft_root(tmp_path, live={"hp": 50, "stage_round": "3-2"},
                     coach={"stage": 3, "round": 2})
    real_stat = Path.stat

    def _flaky_stat(self, *a, **kw):
        if self.name == "tft_coaching_data.json":
            raise FileNotFoundError(str(self))
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", _flaky_stat)
    report = _sv(root).run_once()
    assert "mismatch_count" in report


# -- F9: the module header must not deny what the module does ----------------

def test_module_docstring_matches_behaviour():
    doc = rc_state_validator.__doc__ or ""
    assert "run OCR" not in doc.split("Does NOT:")[-1]
    assert "1-100" not in doc
    # Check 1 validates the mode value; it never compares an overlay mode.
    assert "Overlay mode matches" not in doc
