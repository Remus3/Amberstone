"""Item 8 Phase 2: upstream_drift_check.trigger_refresh() also refreshes the
rank-tier ingest.

RC-UpstreamDriftCheck runs daily; on mid-week upstream drift it calls
trigger_refresh(), which historically kicked only the DDragon mirror refresh.
Phase 2 folds in a `scripts/data_pipeline.py rank_tiers` run so the rank-tier
artifact re-stamps on a mid-week patch drift too. Both sub-runs stay fail-soft:
trigger_refresh never raises and returns ok whenever every sub-run exits 0/1.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import upstream_drift_check as M  # noqa: E402


class _FakeProc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_trigger_refresh_runs_both_ddragon_and_rank_tiers(monkeypatch):
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProc(0)

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    ok, detail = M.trigger_refresh()
    assert ok is True
    joined = [" ".join(str(x) for x in c) for c in calls]
    assert any("ddragon_mirror_refresh.py" in c for c in joined), joined
    assert any("data_pipeline.py" in c and "rank_tiers" in c for c in joined), joined


def test_trigger_refresh_fail_soft_on_exception(monkeypatch):
    def _boom(cmd, **kwargs):
        raise RuntimeError("subprocess exploded")

    monkeypatch.setattr(M.subprocess, "run", _boom)
    ok, detail = M.trigger_refresh()      # must not raise
    assert ok is False
    assert isinstance(detail, str)


def test_trigger_refresh_ok_on_rc1(monkeypatch):
    # rc=1 is a benign "changed / no-op" exit for these refreshers, still ok.
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **k: _FakeProc(1))
    ok, _detail = M.trigger_refresh()
    assert ok is True


def test_trigger_refresh_not_ok_on_rc2(monkeypatch):
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **k: _FakeProc(2))
    ok, _detail = M.trigger_refresh()
    assert ok is False
