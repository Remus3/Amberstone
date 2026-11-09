"""RM-718 (e): tools/rc_facts.py sweeps its OWN stale scratch files at start.

WHY THIS EXISTS. RM-718 (e) filed two rc_facts temp leaks: the per-session
reported record left `sync_inbox_reported.json.tmp.<pid>` behind when its
replace failed (`except OSError: pass`), and `--mark-inbox-seen` wrote a
fixed `sync_inbox_seen.json.tmp`. The WRITE half closed with RM-258
(rc_facts): every writer now goes through core.polled_json, which removes its
own scratch on failure. The filed acceptance has a second half that nothing
shipped: "a stale-temp sweep runs at start". A hard kill between the scratch
write and the rename (the case no `except` can catch) still orphans a file,
and the legacy-named leftovers from before RM-258 never age out. MEASURED
(read-only, 2026-11-08): the live ops/runtime held two
`sync_inbox_reported.json.tmp.<pid>` orphans.

SCOPE IS OWN-FILES ONLY. The sweep removes scratch whose name derives from a
file rc_facts itself writes (the inbox seen store, the reported record, the
inbox report file, the hook-invocation log) and leaves every other writer's
scratch alone: `health.json.<pid>.<hex>.tmp` is the supervisor's (RM-718 (f),
frozen), and a sibling module's scratch is that module's to sweep. A young
scratch file is kept, since a concurrent writer may be between its write and
its rename.

Every test points `_ROOT` and `RC_HOOK_LOG` at tmp_path, so no live file is
touched.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from tools import rc_facts  # noqa: E402

_OLD = 10 * 24 * 3600.0  # ten days: far past any sane cap


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(rc_facts, "_ROOT", tmp_path)
    monkeypatch.delenv("RC_HOOK_LOG", raising=False)
    runtime = tmp_path / "ops" / "runtime"
    runtime.mkdir(parents=True)
    return runtime


def _make(path: Path, age_s: float, now: float) -> Path:
    path.write_bytes(b"{}")
    os.utime(path, (now - age_s, now - age_s))
    return path


# Every scratch name rc_facts has ever produced for its own files:
# the legacy Path.with_suffix forms removed by RM-258, and the current
# core.polled_json per-writer form `<name>.<pid>.<8 hex>.tmp`.
_OWN_STALE = [
    "sync_inbox_reported.json.tmp.24848",
    "sync_inbox_seen.json.tmp",
    "sync_inbox_report.txt.tmp.37752",
    "hook_invocations.jsonl.tmp",
    "sync_inbox_reported.json.13484.fe80e953.tmp",
    "sync_inbox_seen.json.7.0a1b2c3d.tmp",
    "sync_inbox_report.txt.99999.deadbeef.tmp",
    "hook_invocations.jsonl.4242.00ff00ff.tmp",
]

# Never ours, or not scratch at all: each must survive the sweep at any age.
_FOREIGN = [
    "health.json.14968.55bc23af.tmp",
    "monitor_state.json.13484.fe80e953.tmp",
    "sync_inbox_seen.json",
    "sync_inbox_reported.json",
    "sync_inbox_report.txt",
    "hook_invocations.jsonl",
    "hook_invocations.skipped.jsonl",
    "sync_inbox_reported.json.tmp.notapid",
    "sync_inbox_reported.json.13484.FE80E953.tmp",
    "sync_inbox_reported.json.13484.fe80e95.tmp",
    "xsync_inbox_seen.json.tmp",
    "sync_inbox_seen.json.tmp.bak",
    "sync_inbox_seen.jsonXtmp",
]


def test_stale_own_scratch_is_removed_and_counted(tree):
    now = time.time()
    for name in _OWN_STALE:
        _make(tree / name, _OLD, now)
    assert rc_facts.sweep_stale_scratch(now=now) == len(_OWN_STALE)
    assert sorted(p.name for p in tree.iterdir()) == []


@pytest.mark.parametrize("name", _FOREIGN)
def test_foreign_or_live_files_survive_at_any_age(tree, name):
    now = time.time()
    target = _make(tree / name, _OLD, now)
    assert rc_facts.sweep_stale_scratch(now=now) == 0
    assert target.is_file()


def test_young_scratch_survives_and_the_cap_is_strict(tree):
    now = time.time()
    cap = rc_facts.SCRATCH_MAX_AGE_S
    assert 60 <= cap <= 24 * 3600, cap
    young = _make(tree / "sync_inbox_seen.json.tmp", 5.0, now)
    at_cap = _make(tree / "sync_inbox_reported.json.tmp.1", cap, now)
    past = _make(tree / "sync_inbox_reported.json.tmp.2", cap + 1.0, now)
    assert rc_facts.sweep_stale_scratch(now=now) == 1
    assert young.is_file() and at_cap.is_file()
    assert not past.exists()


def test_a_directory_with_a_scratch_name_is_left_alone(tree, monkeypatch):
    """Not even attempted: an unlink refused by the OS would hide the check."""
    now = time.time()
    d = tree / "sync_inbox_seen.json.tmp"
    d.mkdir()
    os.utime(d, (now - _OLD, now - _OLD))
    tried: list[str] = []
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        tried.append(self.name)
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert rc_facts.sweep_stale_scratch(now=now) == 0
    assert d.is_dir()
    assert tried == []


def test_the_hook_log_override_moves_its_scratch_with_it(tree, tmp_path, monkeypatch):
    now = time.time()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("RC_HOOK_LOG", str(elsewhere / "fires.jsonl"))
    moved = _make(elsewhere / "fires.jsonl.4242.00ff00ff.tmp", _OLD, now)
    # The default-named log scratch is no longer ours once the log moved.
    default = _make(tree / "hook_invocations.jsonl.tmp", _OLD, now)
    assert rc_facts.sweep_stale_scratch(now=now) == 1
    assert not moved.exists()
    assert default.is_file()


def test_a_missing_runtime_dir_is_a_quiet_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(rc_facts, "_ROOT", tmp_path / "absent")
    monkeypatch.delenv("RC_HOOK_LOG", raising=False)
    assert rc_facts.sweep_stale_scratch() == 0


def test_an_unlink_failure_never_raises_and_the_rest_still_go(tree, monkeypatch):
    """A hook must never fail the turn: a held file is skipped, not fatal."""
    now = time.time()
    # Held is the first entry in name order, so an abort on it would leave
    # every later candidate behind.
    held = _make(tree / "hook_invocations.jsonl.tmp", _OLD, now)
    other = _make(tree / "sync_inbox_reported.json.tmp.3", _OLD, now)
    third = _make(tree / "sync_inbox_seen.json.tmp", _OLD, now)
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name == held.name:
            raise PermissionError(32, "held")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert rc_facts.sweep_stale_scratch(now=now) == 2
    assert held.is_file()
    assert not other.exists() and not third.exists()


def test_an_unexpected_error_is_swallowed(tree, monkeypatch):
    def boom():
        raise RuntimeError("probe")

    monkeypatch.setattr(rc_facts, "_own_scratch_targets", boom)
    assert rc_facts.sweep_stale_scratch() == 0


def test_sessionstart_runs_the_sweep_before_main(tree, monkeypatch):
    """The acceptance says the sweep runs AT START: the SessionStart arm of
    `_cli`, not the per-prompt `--inbox-only` arm or the operator's
    `--mark-inbox-seen` act (both stubbed here, so nothing is probed)."""
    now = time.time()
    stale = _make(tree / "sync_inbox_reported.json.tmp.24848", _OLD, now)
    seen: list[str] = []
    monkeypatch.setattr(rc_facts, "_read_hook_payload_with_reason", lambda stream=None: ({}, "empty"))
    monkeypatch.setattr(rc_facts, "record_invocation", lambda *a, **k: seen.append("record"))
    monkeypatch.setattr(rc_facts, "report_inbox_only", lambda session=None: seen.append("report") or 0)
    monkeypatch.setattr(rc_facts, "mark_inbox_seen", lambda: seen.append("mark") or 0)

    def fake_main(session=None):
        seen.append("main:" + ("gone" if not stale.exists() else "present"))
        return 0

    monkeypatch.setattr(rc_facts, "main", fake_main)
    rc_facts._cli(["rc_facts.py", "--inbox-only"])
    rc_facts._cli(["rc_facts.py", "--mark-inbox-seen"])
    assert stale.is_file(), "only SessionStart sweeps"
    assert rc_facts._cli(["rc_facts.py"]) == 0
    assert seen[-1] == "main:gone", seen
