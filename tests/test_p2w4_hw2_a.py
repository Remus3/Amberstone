"""P2 cycle-15 half-wave-2 slice-A regression tests - ops runtime spine.

Each test pins a defect the slice-A audit found and fixed in
``ops/rc_state_validator.py``:

  1. Non-numeric TFT hp aborts the whole validation run.
     ``run_once()`` does ``float(hp)`` on the live-vision ``hp`` field with no
     guard. The vision/OCR writer (tft/tft_live_analysis.py:354 -> vs.get("hp"))
     can emit a non-numeric token (stale OCR garbage, a "-" no-data sentinel,
     an empty-ish string). ``float("-")`` raises ValueError, which unwinds out
     of run_once past checks 4/5/6; the SelfMonitor caller swallows it
     (rc_self_monitor.py:331 try/except pass) AND _last_run was already advanced
     at maybe_run(), so EVERY validator tick silently skips for the cadence
     window. The fix coerces hp through a guarded float and only range-checks a
     finite numeric value.

API surface verified before writing (cited file:line):
  - StateValidator.__init__(project_root, incident_log, interval_s=,
    staleness_threshold_s=, ocr_enabled=)  -> rc_state_validator.py:38-45
  - reads project_root/"data"/"tft_live_data.json" -> rc_state_validator.py:53
  - reads project_root/"ops"/"runtime"/"health.json" -> rc_state_validator.py:55
  - run_once() returns dict with key "checks" -> rc_state_validator.py:70-77
  - hp read via live.get("hp"); float(hp) at -> rc_state_validator.py:107-108
  - _mismatch -> incident_log.record(severity=, subsystem=, trigger=,
    action=, result=, detail=) -> rc_state_validator.py:170-177
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OPS_DIR = _REPO_ROOT / "ops"
if str(_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(_OPS_DIR))

import rc_state_validator  # noqa: E402  (path-insert must precede import)


class _RecordingIncidentLog:
    """Minimal IncidentLog double - only .record() is exercised."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, **kwargs) -> dict:
        self.entries.append(kwargs)
        return kwargs


def _seed(project_root: Path, hp_value) -> None:
    """Write a health.json that puts the validator in the TFT-live branch and a
    tft_live_data.json carrying the given hp value."""
    runtime = project_root / "ops" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "health.json").write_text(
        json.dumps({"mode": "game", "tft_mode": True, "has_game": True}),
        encoding="utf-8",
    )
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "tft_live_data.json").write_text(
        json.dumps({"hp": hp_value, "stage_round": "3-6"}),
        encoding="utf-8",
    )


def test_non_numeric_hp_does_not_abort_run(tmp_path: Path) -> None:
    """A non-numeric hp ('-') must NOT raise out of run_once(): the downstream
    checks (stage_round, freshness) have to keep running."""
    _seed(tmp_path, "-")
    sv = rc_state_validator.StateValidator(
        project_root=tmp_path,
        incident_log=_RecordingIncidentLog(),
    )
    # Before the fix this raised ValueError: could not convert string to float.
    report = sv.run_once()
    # run completed far enough to evaluate stage_round (proves no early abort).
    assert any("tft_hp=" in c for c in report["checks"])


def test_numeric_out_of_range_hp_still_flagged(tmp_path: Path) -> None:
    """The guard must not silence the real check: a numeric hp above 100 is
    still reported as tft_hp_out_of_range."""
    _seed(tmp_path, 150)
    log = _RecordingIncidentLog()
    sv = rc_state_validator.StateValidator(project_root=tmp_path, incident_log=log)
    report = sv.run_once()
    triggers = {m["trigger"] for m in report["mismatches"]}
    assert "tft_hp_out_of_range" in triggers
