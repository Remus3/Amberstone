"""L-03: FAILED-stub writer honours AGENT6_REPORTS_DIR and sanitises task_id."""
from __future__ import annotations

from agents import _supervisor_ephemeral as se


def test_stub_goes_to_patched_dir_with_sanitised_name(tmp_path, monkeypatch):
    target = tmp_path / "reports"
    monkeypatch.setattr(se, "AGENT6_REPORTS_DIR", target)
    se._write_agent6_failure_stub("../x:y", "demo", {}, 1, tmp_path / "s.log", "ts")
    files = list(target.iterdir())
    assert len(files) == 1
    assert files[0].name.endswith("-FAILED-.._x_y.md")
    assert files[0].parent == target


def test_live_reports_dir_untouched_by_default_fixture():
    live = se._PROJECT_ROOT / "agents" / "agent6_auditor" / "reports"
    assert se.AGENT6_REPORTS_DIR != live
