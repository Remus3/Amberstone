"""LBAND1 - core.live_benchmark_band_shadow + the state-builder wrapper tests.

Pins the writer gate (champion required, only actual band firings logged), the
coarse-state dedup, the record shape + engine stamp, the never-raises contract,
and the wrapper gates (live-game lc.champion required, SR-only). Writes to a tmp
path (the test seam), never the live data/live_benchmark_band_shadow.jsonl.
"""
from __future__ import annotations

import json

from core import live_benchmark_band_shadow as lbs

_BAND = {
    "checkpoint": "10", "metric": "cs_at_10", "display": "CS",
    "value": 90.0, "band": "above-p75", "p50": 70.0,
    "line": "CS at 10: top quartile on Tristana.", "source_tag": "live-bench",
}


def _read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --- writer-level -----------------------------------------------------------

def test_writes_record_on_band_firing(tmp_path):
    p = tmp_path / "shadow.jsonl"
    rec = lbs.log_live_bands(
        "sr", "Tristana", bands=[_BAND],
        game_time_s=600.0, cs=90, level=9,
        native_action="Push to tower", path=p,
    )
    assert rec is not None
    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["champion"] == "Tristana"
    assert r["mode"] == "sr"
    assert r["cs"] == 90
    assert r["level"] == 9
    assert r["native_action"] == "Push to tower"
    assert r["bands"][0]["band"] == "above-p75"
    assert r["engine_version"]  # stamped


def test_no_champion_is_gate_miss(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert lbs.log_live_bands("sr", "", bands=[_BAND], path=p) is None
    assert not p.exists()


def test_empty_bands_not_logged(tmp_path):
    # LBAND1 only records actual firings; an off-checkpoint tick (no bands) is
    # expected and must NOT be logged (would be pure noise).
    p = tmp_path / "shadow.jsonl"
    assert lbs.log_live_bands("sr", "Tristana", bands=[], path=p) is None
    assert lbs.log_live_bands("sr", "Tristana", bands=None, path=p) is None
    assert not p.exists()


def test_coarse_state_dedup(tmp_path):
    p = tmp_path / "shadow.jsonl"
    first = lbs.log_live_bands("sr", "Tristana", bands=[_BAND], cs=90, level=9,
                               game_time_s=600.0, path=p)
    dup = lbs.log_live_bands("sr", "Tristana", bands=[_BAND], cs=90, level=9,
                             game_time_s=601.0, path=p)  # same 5s bucket
    assert first is not None
    assert dup is None
    # A changed live value is a fresh signal -> written.
    changed = lbs.log_live_bands("sr", "Tristana", bands=[_BAND], cs=120, level=10,
                                 game_time_s=600.0, path=p)
    assert changed is not None
    assert len(_read(p)) == 2


def test_never_raises_on_junk(tmp_path):
    p = tmp_path / "shadow.jsonl"
    # Non-str champion, junk band entries - fail-soft, no exception, no row.
    assert lbs.log_live_bands("sr", 123, bands=[_BAND], path=p) is None  # type: ignore[arg-type]
    assert lbs.log_live_bands("sr", "Tristana", bands=["junk", 5], cs=90, path=p) is not None


# --- wrapper-level (state-builder seam) -------------------------------------

def _wrapper():
    from dashboard._deterministic_coaching import shadow_log_live_benchmark_band
    return shadow_log_live_benchmark_band


def test_wrapper_fires_on_live_sr_tick(tmp_path, monkeypatch):
    import core.live_benchmark_band as lbb
    monkeypatch.setattr(lbb, "band_metrics", lambda *a, **k: [_BAND])
    p = tmp_path / "shadow.jsonl"
    coach = {"champion": "Tristana", "cs": 90, "level": 9, "action": "Push to tower"}
    lc = {"champion": "Tristana"}  # live-game gate: lc.champion present
    _wrapper()(coach, lc, "sr", path=p)
    rows = _read(p)
    assert len(rows) == 1
    assert rows[0]["champion"] == "Tristana"
    assert rows[0]["native_action"] == "Push to tower"


def test_wrapper_skips_when_not_live_tick(tmp_path, monkeypatch):
    import core.live_benchmark_band as lbb
    monkeypatch.setattr(lbb, "band_metrics", lambda *a, **k: [_BAND])
    p = tmp_path / "shadow.jsonl"
    coach = {"champion": "Tristana", "cs": 90, "level": 9}
    # lc lacks champion -> stale post-game tick -> no log.
    _wrapper()(coach, {}, "sr", path=p)
    assert not p.exists()


def test_wrapper_sr_only(tmp_path, monkeypatch):
    import core.live_benchmark_band as lbb
    monkeypatch.setattr(lbb, "band_metrics", lambda *a, **k: [_BAND])
    p = tmp_path / "shadow.jsonl"
    coach = {"champion": "Tristana", "cs": 90, "level": 9}
    lc = {"champion": "Tristana"}
    _wrapper()(coach, lc, "aram", path=p)  # non-SR -> LBAND1 does not apply
    assert not p.exists()
