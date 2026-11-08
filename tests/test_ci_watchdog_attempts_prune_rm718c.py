"""RM-718 (c): the CI watchdog's per-run attempt counters are pruned by age.

`tools/ci_watchdog.py` `bump_attempts` writes one `<run_id>.txt` per run into
`ops/runtime/ci_watchdog/attempts/` and nothing ever removed one (117 files
measured 2026-10-26, s134 research cycle 16). A counter is only read again for
a run newer than the sentinel, and `main()` advances the sentinel past a run in
the same armed branch that bumps its counter, so an old counter at or below the
sentinel is dead weight.

`prune_attempts` removes a counter only when BOTH hold: its mtime is older than
the age cap, and its run id is at or below the sentinel (a counter that can
still be read is never removed, whatever its age). A missing dir or a refused
stat / unlink is skipped. An age cap of zero or below raises ValueError (the
RM-161 class: an age cap that erases everything it can reach); `main()`
swallows any prune failure and returns 0 always.
"""
from __future__ import annotations

import os

import pytest

from tools import ci_watchdog as cw

_NOW = 1_800_000_000.0
_DAY = 24 * 3600


def _counter(d, run_id, age_days, value="1"):
    p = d / f"{run_id}.txt"
    p.write_text(value, encoding="utf-8")
    ts = _NOW - age_days * _DAY
    os.utime(p, (ts, ts))
    return p


def test_default_age_cap_is_positive_and_at_least_a_week():
    assert cw.ATTEMPTS_MAX_AGE_S >= 7 * _DAY


def test_prune_removes_old_counters_at_or_below_the_sentinel(tmp_path):
    d = tmp_path / "attempts"
    d.mkdir()
    old_a = _counter(d, 100, age_days=60)
    old_b = _counter(d, 200, age_days=60)
    fresh = _counter(d, 150, age_days=1)
    removed = cw.prune_attempts(_NOW, 200, d, max_age_s=14 * _DAY)
    assert sorted(p.name for p in removed) == ["100.txt", "200.txt"]
    assert not old_a.exists()
    assert not old_b.exists()
    assert fresh.exists()


def test_prune_keeps_an_old_counter_above_the_sentinel(tmp_path):
    """A run newer than the sentinel is still processed, so its counter is
    still read by should_escalate: never prune it, however old."""
    d = tmp_path / "attempts"
    d.mkdir()
    live = _counter(d, 300, age_days=365, value="2")
    removed = cw.prune_attempts(_NOW, 299, d, max_age_s=14 * _DAY)
    assert removed == []
    assert live.exists()
    assert cw.attempts_for(300, d) == 2


def test_prune_with_no_sentinel_removes_nothing(tmp_path):
    """read_sentinel() returns 0 when the sentinel is lost; every counter may
    then be read again, so none is removed."""
    d = tmp_path / "attempts"
    d.mkdir()
    keep = _counter(d, 5, age_days=365)
    assert cw.prune_attempts(_NOW, 0, d, max_age_s=14 * _DAY) == []
    assert keep.exists()


def test_prune_leaves_non_counter_files_alone(tmp_path):
    d = tmp_path / "attempts"
    d.mkdir()
    for name in ("notes.txt", "12.txt.tmp", "12.json", "-3.txt", "README"):
        p = d / name
        p.write_text("x", encoding="utf-8")
        ts = _NOW - 365 * _DAY
        os.utime(p, (ts, ts))
    sub = d / "77.txt"
    sub.mkdir()
    assert cw.prune_attempts(_NOW, 10**12, d, max_age_s=14 * _DAY) == []
    assert sorted(p.name for p in d.iterdir()) == sorted(
        ["notes.txt", "12.txt.tmp", "12.json", "-3.txt", "README", "77.txt"])


def test_prune_age_boundary_is_strictly_older(tmp_path):
    d = tmp_path / "attempts"
    d.mkdir()
    at_cap = _counter(d, 1, age_days=14)
    past_cap = _counter(d, 2, age_days=14.01)
    removed = cw.prune_attempts(_NOW, 10, d, max_age_s=14 * _DAY)
    assert [p.name for p in removed] == ["2.txt"]
    assert at_cap.exists()
    assert not past_cap.exists()


def test_prune_keeps_a_future_dated_counter(tmp_path):
    d = tmp_path / "attempts"
    d.mkdir()
    future = _counter(d, 1, age_days=-30)
    assert cw.prune_attempts(_NOW, 10, d, max_age_s=14 * _DAY) == []
    assert future.exists()


@pytest.mark.parametrize("bad", [0, -1, -14 * _DAY])
def test_prune_refuses_a_non_positive_age_cap(tmp_path, bad):
    d = tmp_path / "attempts"
    d.mkdir()
    keep = _counter(d, 1, age_days=365)
    with pytest.raises(ValueError):
        cw.prune_attempts(_NOW, 10, d, max_age_s=bad)
    assert keep.exists()


def test_prune_missing_dir_is_a_no_op(tmp_path):
    assert cw.prune_attempts(_NOW, 10, tmp_path / "absent", max_age_s=_DAY) == []


def test_prune_survives_an_unlink_refusal(tmp_path, monkeypatch):
    d = tmp_path / "attempts"
    d.mkdir()
    held = _counter(d, 1, age_days=60)
    other = _counter(d, 2, age_days=60)
    real_unlink = type(held).unlink

    def flaky_unlink(self, *a, **kw):
        if self.name == "1.txt":
            raise PermissionError(32, "held")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(type(held), "unlink", flaky_unlink)
    removed = cw.prune_attempts(_NOW, 10, d, max_age_s=_DAY)
    assert [p.name for p in removed] == ["2.txt"]
    assert held.exists()
    assert not other.exists()


def _wire_main(monkeypatch, tmp_path, sentinel_value):
    runtime = tmp_path / "ci_watchdog"
    attempts = runtime / "attempts"
    attempts.mkdir(parents=True)
    sentinel = runtime / "last_seen_run_id.txt"
    sentinel.write_text(str(sentinel_value), encoding="utf-8")
    monkeypatch.setattr(cw, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(cw, "ATTEMPTS_DIR", attempts)
    monkeypatch.setattr(cw, "SENTINEL", sentinel)
    monkeypatch.setattr(cw, "is_halted", lambda *a, **k: False)
    monkeypatch.setattr(cw, "_list_runs", lambda: [])
    monkeypatch.setattr(cw.time, "time", lambda: _NOW)
    return attempts


def test_armed_main_prunes_old_counters_even_with_no_runs(tmp_path, monkeypatch):
    attempts = _wire_main(monkeypatch, tmp_path, 500)
    old = _counter(attempts, 400, age_days=cw.ATTEMPTS_MAX_AGE_S / _DAY + 1)
    fresh = _counter(attempts, 450, age_days=0)
    assert cw.main(arm=True) == 0
    assert not old.exists()
    assert fresh.exists()


def test_dry_run_main_prunes_nothing(tmp_path, monkeypatch):
    """arm=False mutates no persistent state (main()'s own contract)."""
    attempts = _wire_main(monkeypatch, tmp_path, 500)
    old = _counter(attempts, 400, age_days=cw.ATTEMPTS_MAX_AGE_S / _DAY + 1)
    assert cw.main(arm=False) == 0
    assert old.exists()


def test_armed_main_survives_a_prune_failure(tmp_path, monkeypatch):
    _wire_main(monkeypatch, tmp_path, 500)

    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(cw, "prune_attempts", boom)
    assert cw.main(arm=True) == 0
