# arch: P2 cycle-15 hw2 slice-E regression tests for scripts extractors/builders/audit/precommit | section=tests | frozen=no
"""Regression tests for DEEP_AUDIT_CHARTER P2 cycle 15 half-wave 2 slice E
(scripts/ extractors + builders + audit + precommit gates).

NO network, NO DB, NO loop/fetch execution, NO restart. Every helper under
test is a PURE function exercised in isolation - the network/DB accessors
(`_recent_rows`, `_bench`) are monkeypatched, and the precommit validators
are fed string/Path inputs directly.

FIX-NOW covered here:

  1. friction #1 NON-FINITE JSON TOKEN - scripts/champion_drift_alerts.py
     `compute_drifts()` folded raw DB float fields (`cs_per_min`,
     `gold_per_min`, `kp_pct`) straight into `_median` -> `pct_below` ->
     `atomic_write_json(drift_alerts.json)`. SQLite stores IEEE-754 doubles,
     so a corrupt/computed column can hold `inf`/`nan`; `round(inf,2)` stays
     `inf` and `json.dumps` (the shared core.polled_json primitive does NOT
     pass `allow_nan=False`) then emits a bare `Infinity`/`NaN` token that a
     strict `json.loads` rejects on the consumer side. The fix filters
     non-finite values in `_median` and skips a metric whose `recent_p50`
     or computed `pct_below` is non-finite, so the alerts payload is always
     JSON-finite.

  2. friction #6 ASCII-only HARD RULE - scripts/validate_build_data.py emitted
     a U+2713 CHECK MARK in its "clean" line. Repo rule is 7-bit ASCII in all
     authored output. Now plain ASCII "OK".
"""
from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


@pytest.fixture
def drift():
    """Import (or re-import) champion_drift_alerts. Top-level only defines
    module constants + Paths; import is side-effect-free (no DB/network)."""
    mod = importlib.import_module("champion_drift_alerts")
    return importlib.reload(mod)


# --------------------------------------------------------------------- #1 non-finite
class TestDriftNonFinite:
    """A non-finite DB float must never reach the JSON alerts payload as a
    bare Infinity/NaN token."""

    def _wire(self, drift, monkeypatch, rows, bench):
        monkeypatch.setattr(drift, "_recent_rows", lambda days, champ="": rows)
        monkeypatch.setattr(drift, "_bench", lambda: {"champions": bench})

    def test_infinite_recent_value_is_dropped(self, drift, monkeypatch):
        # 3 games (>= DEFAULT_MIN_GAMES) on Vayne, one with inf cs_per_min.
        rows = [
            {"champion": "Vayne", "cs_per_min": float("inf")},
            {"champion": "Vayne", "cs_per_min": float("inf")},
            {"champion": "Vayne", "cs_per_min": float("inf")},
        ]
        bench = {"Vayne": {"sr_ranked": {"cs_per_min": {"p50": 7.0}}}}
        self._wire(drift, monkeypatch, rows, bench)
        alerts = drift.compute_drifts()
        # Every emitted number must be JSON-finite.
        for a in alerts:
            assert math.isfinite(a["recent_p50"]), a
            assert math.isfinite(a["pct_below"]), a
        # And the whole payload round-trips through strict JSON.
        blob = json.dumps({"alerts": alerts}, allow_nan=False)
        assert "Infinity" not in blob and "NaN" not in blob

    def test_nan_recent_value_is_dropped(self, drift, monkeypatch):
        rows = [
            {"champion": "Vayne", "gold_per_min": float("nan")},
            {"champion": "Vayne", "gold_per_min": float("nan")},
            {"champion": "Vayne", "gold_per_min": float("nan")},
        ]
        bench = {"Vayne": {"sr_ranked": {"gold_per_min": {"p50": 400.0}}}}
        self._wire(drift, monkeypatch, rows, bench)
        alerts = drift.compute_drifts()
        # NaN comparisons are always False, so a NaN recent_p50 must not slip
        # through pct_below >= drop_pct either way; assert it is simply absent.
        assert all(math.isfinite(a["pct_below"]) for a in alerts)
        json.dumps({"alerts": alerts}, allow_nan=False)  # raises if a bare token leaked

    def test_finite_drift_still_reported(self, drift, monkeypatch):
        # Sanity: a genuine 20%-below drift on finite data is still flagged.
        rows = [
            {"champion": "Vayne", "cs_per_min": 5.6},
            {"champion": "Vayne", "cs_per_min": 5.6},
            {"champion": "Vayne", "cs_per_min": 5.6},
        ]
        bench = {"Vayne": {"sr_ranked": {"cs_per_min": {"p50": 7.0}}}}
        self._wire(drift, monkeypatch, rows, bench)
        alerts = drift.compute_drifts()
        assert any(a["champion"] == "Vayne" and a["metric"] == "cs_per_min"
                   for a in alerts)

    def test_median_filters_non_finite(self, drift):
        # _median must drop inf/nan alongside None so a single bad row does
        # not poison the median.
        med = drift._median([5.0, float("inf"), float("nan"), None, 5.0])
        assert math.isfinite(med)
        assert med == 5.0


# --------------------------------------------------------------------- #6 ASCII-only
class TestValidateBuildDataAscii:
    """scripts/validate_build_data.py must stay 7-bit ASCII (repo HARD RULE);
    it previously printed a U+2713 check mark on the clean path."""

    def test_source_is_pure_ascii(self):
        src = _SCRIPTS / "validate_build_data.py"
        raw = src.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:  # pragma: no cover - failure detail
            # Surface the offending byte/line for a fast fix.
            bad_at = exc.start
            line = raw[:bad_at].count(b"\n") + 1
            pytest.fail(f"non-ASCII byte {raw[bad_at]:#04x} at line {line}")


# --------------------------------------------------------------- #4 wakeup separator
@pytest.fixture
def wp():
    """Import wakeup_prune. Top-level only defines constants + Paths."""
    mod = importlib.import_module("wakeup_prune")
    return importlib.reload(mod)


class TestWakeupPruneSeparatorGotcha:
    """A /done entry that OMITS the `\\n---\\n\\n` separator before its heading
    must NOT hide that session from split_sessions' count - otherwise --check
    under-reports and WAKEUP_NOTES.md grows unbounded (the documented gotcha,
    memory reference_wakeup_prune_separator_gotcha)."""

    def test_missing_separator_still_counts_each_session(self, wp):
        # Two dated sessions where the 2nd's separator was omitted: the 2nd
        # heading sits in the SAME SEP-delimited block as the 1st.
        text = (
            "# WAKEUP\n"
            "\n---\n\n"
            "# 2026-06-13 wrap - newest\n"
            "did a thing\n"
            "# 2026-06-12 wrap - older (separator omitted by /done)\n"
            "did another thing\n"
        )
        _header, sessions = wp.split_sessions(text)
        # Both sessions must be visible as distinct blocks (2, not 1).
        assert len(sessions) == 2, sessions
        # Newest-first order preserved.
        assert sessions[0].lstrip("\n").startswith("# 2026-06-13")
        assert sessions[1].lstrip("\n").startswith("# 2026-06-12")

    def test_normal_separators_unchanged(self, wp):
        # Regression guard: the canonical well-formed shape still splits to 2.
        text = (
            "# WAKEUP\n"
            "\n---\n\n"
            "# 2026-06-13 wrap - newest\n"
            "body a\n"
            "\n---\n\n"
            "# 2026-06-12 wrap - older\n"
            "body b\n"
        )
        _header, sessions = wp.split_sessions(text)
        assert len(sessions) == 2
        assert sessions[0].lstrip("\n").startswith("# 2026-06-13")
