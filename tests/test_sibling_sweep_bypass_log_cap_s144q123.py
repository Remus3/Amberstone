"""S144-Q-123 (RM-718 residue), writer 2: the sibling sweep's bypass log is
size-capped.

`tools/sibling_name_sweep.py` `_append_bypass_log` appended every BYPASS
report to `ops/runtime/sibling_sweep_bypass.log` forever (measured
2026-11-08: 302,269 B, 159 reports, about 1.9 KB each, no reader in code).
It now rotates through core/log_rotation BEFORE the append, at the same
5 MiB x (1 + 2 backups) bound as the other RM-718 writers.

Two constraints shape the fix and are pinned here:
- the sweep runs from `.githooks/pre-push` as a SCRIPT (sys.path[0] is
  tools/, so `from core import ...` does not resolve), so core/log_rotation
  is loaded by FILE PATH; the end-to-end test runs the tool as a script from
  a cwd outside the checkout;
- a BYPASS report is an audit record: no failure of the cap (rotation
  refused, rotation module unavailable) may drop it or raise.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core import log_rotation  # noqa: E402
from tests.test_sibling_name_sweep import (  # noqa: E402
    _SYNTH_PARTICIPANTS,
    _SYNTH_REPOS,
    _write_config,
)
from tools import sibling_name_sweep as sweep  # noqa: E402


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "rt" / "bypass.log"
    monkeypatch.setenv(sweep.BYPASS_LOG_ENV, str(path))
    return path


@pytest.fixture
def small_cap(monkeypatch):
    monkeypatch.setattr(sweep, "BYPASS_LOG_MAX_BYTES", 100)
    return 100


def _backups(path: Path) -> list[Path]:
    return sorted(p for p in path.parent.iterdir() if p.name != path.name)


def test_cap_matches_the_shared_rm718_bound():
    assert sweep.BYPASS_LOG_MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert sweep.BYPASS_LOG_BACKUPS == log_rotation.DEFAULT_BACKUP_COUNT
    assert sweep.BYPASS_LOG_MAX_BYTES > 0


def test_rotation_module_is_loaded_by_file_path_from_the_tool_checkout():
    mod = sweep._log_rotation()
    assert mod is not None
    assert Path(mod.__file__).resolve() == (
        Path(sweep.__file__).resolve().parent.parent / "core" / "log_rotation.py"
    )
    assert callable(mod.try_rotate) and callable(mod.refusal_note)
    # Cached: the second call returns the same module object.
    assert sweep._log_rotation() is mod


def test_under_the_cap_the_report_is_a_plain_append(log, small_cap):
    sweep._append_bypass_log("one")
    sweep._append_bypass_log("two")
    assert log.read_bytes() == b"one\ntwo\n"
    assert _backups(log) == []


def test_at_the_cap_the_old_file_rotates_before_the_append(log, small_cap):
    log.parent.mkdir(parents=True)
    old = b"x" * small_cap
    log.write_bytes(old)
    sweep._append_bypass_log("new report")
    assert log.read_bytes() == b"new report\n"
    assert Path(str(log) + ".1").read_bytes() == old
    assert _backups(log) == [Path(str(log) + ".1")]


def test_just_under_the_cap_does_not_rotate(log, small_cap):
    log.parent.mkdir(parents=True)
    log.write_bytes(b"x" * (small_cap - 1))
    sweep._append_bypass_log("r")
    assert log.read_bytes() == b"x" * (small_cap - 1) + b"r\n"
    assert _backups(log) == []


def test_generations_are_bounded_and_the_oldest_drops(log, small_cap):
    log.parent.mkdir(parents=True)
    for i in range(6):
        # Each report alone reaches the cap, so every next append rotates.
        sweep._append_bypass_log(f"gen{i}-" + "y" * small_cap)
    names = [p.name for p in _backups(log)]
    assert names == [log.name + f".{i}" for i in range(1, sweep.BYPASS_LOG_BACKUPS + 1)]
    assert log.read_text(encoding="utf-8").startswith("gen5-")
    assert Path(str(log) + ".1").read_text(encoding="utf-8").startswith("gen4-")
    assert Path(str(log) + ".2").read_text(encoding="utf-8").startswith("gen3-")


def test_a_refused_rotation_still_appends_the_report_after_a_note(
        log, small_cap, monkeypatch):
    log.parent.mkdir(parents=True)
    old = b"z" * small_cap
    log.write_bytes(old)
    mod = sweep._log_rotation()
    refusal = PermissionError(32, "held by another process")
    monkeypatch.setattr(mod, "try_rotate", lambda *_a, **_k: refusal)
    sweep._append_bypass_log("kept")
    data = log.read_bytes()
    assert data.startswith(old)
    assert data.endswith(b"kept\n")
    # refusal_note carries a wall-clock stamp, so match its fixed part only.
    note = data[len(old):-len(b"kept\n")].decode("utf-8")
    assert note.endswith("\n") and note.count("\n") == 1
    assert ("WARNING log rotation refused for bypass.log (PermissionError"
            in note)
    assert _backups(log) == []


def test_a_rotation_that_raises_never_drops_the_report(
        log, small_cap, monkeypatch):
    log.parent.mkdir(parents=True)
    log.write_bytes(b"z" * small_cap)
    mod = sweep._log_rotation()

    def _boom(*_a, **_k):
        raise OSError("disk said no")

    monkeypatch.setattr(mod, "try_rotate", _boom)
    sweep._append_bypass_log("kept")
    assert log.read_bytes().endswith(b"kept\n")


def test_no_rotation_module_degrades_to_a_plain_append(
        log, small_cap, monkeypatch):
    monkeypatch.setattr(sweep, "_log_rotation", lambda: None)
    log.parent.mkdir(parents=True)
    log.write_bytes(b"z" * small_cap)
    sweep._append_bypass_log("kept")
    assert log.read_bytes() == b"z" * small_cap + b"kept\n"


def test_an_unloadable_rotation_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sweep, "_LOG_ROTATION_FILE", tmp_path / "absent.py")
    monkeypatch.setattr(sweep, "_LOG_ROTATION_CACHE", [])
    assert sweep._log_rotation() is None
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "_LOG_ROTATION_FILE", bad)
    monkeypatch.setattr(sweep, "_LOG_ROTATION_CACHE", [])
    assert sweep._log_rotation() is None
    # Any load-time error, not only an import or syntax one.
    raising = tmp_path / "raising.py"
    raising.write_text("raise RuntimeError('load failed')\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "_LOG_ROTATION_FILE", raising)
    monkeypatch.setattr(sweep, "_LOG_ROTATION_CACHE", [])
    assert sweep._log_rotation() is None


def test_the_hook_shaped_script_run_rotates_an_oversize_log(tmp_path):
    """End to end, the way .githooks/pre-push runs it: a script (sys.path[0]
    is tools/) from a cwd outside the checkout, BYPASS set, the log already
    at the real 5 MiB cap."""
    root = _write_config(
        tmp_path, {"repos": _SYNTH_REPOS, "participants": _SYNTH_PARTICIPANTS}
    )
    blob = tmp_path / "leak2.txt"
    blob.write_text("C:\\" + _SYNTH_REPOS[1].split("\\")[-1] + "\\x\n", "utf-8")
    log_path = tmp_path / "rt" / "bypass.log"
    log_path.parent.mkdir(parents=True)
    old = b"o" * sweep.BYPASS_LOG_MAX_BYTES
    log_path.write_bytes(old)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    env = dict(os.environ)
    env["RC_SIBLING_SWEEP_BYPASS"] = "1"
    env[sweep.BYPASS_LOG_ENV] = str(log_path)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "sibling_name_sweep.py"),
         "--scan-file", str(blob), "--config-root", str(root)],
        capture_output=True, text=True, env=env, cwd=str(cwd), timeout=120,
        check=False,
    )
    assert proc.returncode == sweep.EXIT_CLEAN, proc.stderr
    assert Path(str(log_path) + ".1").read_bytes() == old
    fresh = log_path.read_text(encoding="utf-8")
    assert "BYPASS" in fresh
    assert len(fresh.encode("utf-8")) < sweep.BYPASS_LOG_MAX_BYTES
