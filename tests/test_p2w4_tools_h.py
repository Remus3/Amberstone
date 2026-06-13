"""P2 cycle-14 slice H regression tests (live-utility / cost / drift / dev tooling).

Covers FIX-NOW defects found auditing the slice-H tool surface:

  1. tools/cost_health_watchdog.py coerced spend-ledger USD/call values with a
     bare ``float(...)`` and never guarded non-finite inputs. A poisoned
     ``total_usd: NaN`` (or ``Infinity``) in any ``data/spend/<date>.json`` then
     (a) propagated through the breach math - NaN compares False against every
     threshold, so a corrupt ledger SILENTLY DISABLED breach detection - and
     (b) serialized straight into both the stdout report and the
     atomically-written ``cost_health_watchdog_state.json`` as a bare ``NaN`` /
     ``Infinity`` token. That token is invalid JSON per RFC 8259, so any strict
     downstream parser (JS ``JSON.parse``, a Go/Rust cron wrapper, or
     ``json.loads(..., parse_constant=...)`` that rejects) chokes on the
     watchdog's own output. The fix coerces every ledger numeric through an
     isfinite guard (non-finite -> 0.0) so a corrupt ledger can never emit a
     non-finite JSON token nor mask a real cost breach.
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WD_PATH = _REPO_ROOT / "tools" / "cost_health_watchdog.py"


def _load_watchdog():
    """Import tools/cost_health_watchdog.py as a module (hyphen-free name)."""
    spec = importlib.util.spec_from_file_location("rc_cost_health_wd", _WD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_watchdog_module_imports():
    assert _WD_PATH.is_file(), f"missing: {_WD_PATH}"
    _load_watchdog()


def test_spend_baseline_nan_today_is_sanitized(tmp_path: Path):
    """A NaN today total must not survive into the baseline dict."""
    wd = _load_watchdog()
    _write(tmp_path / "2026-06-13.json", {"total_usd": float("nan")})
    out = wd.spend_baseline(tmp_path, "2026-06-13")
    assert math.isfinite(out["today_usd"]), out["today_usd"]
    # JSON round-trip must be strict-parseable (no bare NaN token).
    json.loads(json.dumps(out["today_usd"]))


def test_spend_baseline_inf_prior_day_does_not_poison_median(tmp_path: Path):
    """An Infinity in a prior day's ledger must be dropped, not become the
    median baseline (which would make every future day look in-budget)."""
    wd = _load_watchdog()
    _write(tmp_path / "2026-06-13.json", {"total_usd": 1.0})
    _write(tmp_path / "2026-06-10.json", {"total_usd": float("inf")})
    _write(tmp_path / "2026-06-11.json", {"total_usd": 2.0})
    _write(tmp_path / "2026-06-12.json", {"total_usd": 3.0})
    out = wd.spend_baseline(tmp_path, "2026-06-13")
    assert math.isfinite(out["baseline_usd"]), out["baseline_usd"]


def test_lane_cost_signals_nan_is_finite(tmp_path: Path):
    """A non-finite per-lane usd/calls must not emit a NaN cost-per-call."""
    wd = _load_watchdog()
    _write(tmp_path / "2026-06-13.json",
           {"by_purpose": {"aram_coach": {"usd": float("nan"), "calls": 5}}})
    out = wd.lane_cost_signals(tmp_path, "2026-06-13")
    for lane in out["lanes"].values():
        assert math.isfinite(lane["today_cost_per_call"]), lane
        assert math.isfinite(lane["baseline_cost_per_call"]), lane
    # Whole structure must be strict-JSON-serializable.
    json.loads(json.dumps(out))


def test_main_emits_strict_json_with_poisoned_ledger(tmp_path: Path, capsys):
    """End-to-end: a poisoned spend ledger must still yield strict-parseable
    stdout AND a strict-parseable state file (no bare NaN/Infinity)."""
    wd = _load_watchdog()
    spend_dir = tmp_path / "spend"
    spend_dir.mkdir()
    _write(spend_dir / "2026-06-13.json",
           {"total_usd": float("inf"),
            "by_purpose": {"sr_coach": {"usd": float("nan"), "calls": 30}}})
    state_path = tmp_path / "state.json"
    rc = wd.main(["--spend-dir", str(spend_dir), "--state", str(state_path)])
    assert rc in (0, 1)
    captured = capsys.readouterr().out
    # The printed report must be strict JSON (rejects NaN/Infinity).
    json.loads(captured, parse_constant=_reject)
    # The persisted state file must be strict JSON too.
    json.loads(state_path.read_text(encoding="utf-8"), parse_constant=_reject)


def _reject(token):  # pragma: no cover - only fires on the bug
    raise AssertionError(f"non-finite JSON token leaked: {token!r}")
