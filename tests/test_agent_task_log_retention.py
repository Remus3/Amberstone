"""Per-task agent log retention (deep-audit P1c, item 398).

logs/agents/ accreted 1848 task-<id>.log files (~235/day from periodic-audit
ephemeral spawns) with no retention. prune_task_logs deletes task logs older
than the age cap; agent<N>.log rollups and non-task files are never touched.

RM-161 (lane 8, cycle 10) added the age-cap guard below. The cutoff is
`time.time() - max_age_days * 86400`, so at `max_age_days <= 0` the cutoff
sits at or after now and EVERY file the `task-*.log` glob matches is older
than it - the knob that exists to bound the corpus erases it instead. The
knob was a plain default parameter with no validation, and the function runs
on every ephemeral spawn. It now rejects a non-positive cap rather than
sweeping on it, matching `core/log_retention._validate_policy` (LEDGER 1200).
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents._supervisor_ephemeral import TASK_LOG_MAX_AGE_DAYS, prune_task_logs


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


# - RM-161: the age cap must not be able to erase the corpus ---------------

@pytest.mark.parametrize("bad_cap", [0, 0.0, -1, -7, -0.5])
def test_prune_rejects_non_positive_age_cap(tmp_path, bad_cap):
    """A cap of zero or less puts the cutoff at or after now: every file is
    'older' than it. Reject the policy instead of sweeping on it."""
    fresh = tmp_path / "task-t-dddd.log"; fresh.write_text("x", encoding="utf-8")
    old = tmp_path / "task-t-eeee.log"; old.write_text("x", encoding="utf-8")
    _aged(old, 30)

    with pytest.raises(ValueError) as exc:
        prune_task_logs(log_root=tmp_path, max_age_days=bad_cap)

    assert "max_age_days" in str(exc.value)
    # The guard must refuse BEFORE deleting anything, including files the
    # sweep would legitimately have taken under a sane cap.
    assert fresh.exists(), "a rejected policy still deleted a fresh log"
    assert old.exists(), "a rejected policy still deleted an aged log"


def test_prune_rejects_before_touching_the_filesystem(tmp_path, monkeypatch):
    """The guard runs ahead of the is_dir()/glob work, so a bad cap is
    rejected even when the log root does not exist - the missing-dir early
    return must not be able to mask the policy error."""
    def boom(*a, **k):
        raise AssertionError("filesystem touched before the policy check")
    monkeypatch.setattr(Path, "glob", boom)
    with pytest.raises(ValueError):
        prune_task_logs(log_root=tmp_path / "absent", max_age_days=0)


def test_prune_accepts_the_shipped_default_and_the_boundary(tmp_path):
    """The value the live call site actually uses must still pass, and so
    must the smallest legal cap - a guard that rejects 1 would be a
    behaviour change, not a hardening."""
    assert TASK_LOG_MAX_AGE_DAYS == 7
    victim = tmp_path / "task-t-ffff.log"; victim.write_text("x", encoding="utf-8")
    _aged(victim, 30)
    assert prune_task_logs(log_root=tmp_path, max_age_days=TASK_LOG_MAX_AGE_DAYS) == 1

    survivor = tmp_path / "task-t-gggg.log"; survivor.write_text("x", encoding="utf-8")
    _aged(survivor, 30)
    assert prune_task_logs(log_root=tmp_path, max_age_days=1) == 1
