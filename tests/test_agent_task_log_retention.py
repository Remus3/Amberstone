"""Per-task agent log retention (deep-audit P1c, item 398).

logs/agents/ accreted 1848 task-<id>.log files (~235/day from periodic-audit
ephemeral spawns) with no retention. prune_task_logs deletes task logs older
than the age cap; agent<N>.log rollups and non-task files are never touched.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents._supervisor_ephemeral import prune_task_logs


def _aged(path: Path, days: float) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_prune_removes_only_old_task_logs(tmp_path):
    old = tmp_path / "task-t-aaaa.log"; old.write_text("x", encoding="utf-8")
    young = tmp_path / "task-t-bbbb.log"; young.write_text("x", encoding="utf-8")
    rollup = tmp_path / "agent6.log"; rollup.write_text("x", encoding="utf-8")
    other = tmp_path / "supervisor.log.1"; other.write_text("x", encoding="utf-8")
    _aged(old, 30); _aged(rollup, 30); _aged(other, 30)

    removed = prune_task_logs(log_root=tmp_path, max_age_days=7)

    assert removed == 1
    assert not old.exists()
    assert young.exists() and rollup.exists() and other.exists()


def test_prune_missing_dir_is_noop(tmp_path):
    assert prune_task_logs(log_root=tmp_path / "absent", max_age_days=7) == 0


def test_prune_tolerates_locked_file(tmp_path, monkeypatch):
    f = tmp_path / "task-t-cccc.log"; f.write_text("x", encoding="utf-8")
    _aged(f, 30)
    real_unlink = Path.unlink
    def boom(self, *a, **k):
        raise PermissionError("locked")
    monkeypatch.setattr(Path, "unlink", boom)
    assert prune_task_logs(log_root=tmp_path, max_age_days=7) == 0
    monkeypatch.setattr(Path, "unlink", real_unlink)
