"""S144-Q-123 (RM-718 residue), writer 3: the loop controller's log is
size-capped.

`ops/loop/loop_controller.py` `log` appended every controller line to
`ops/loop/control/controller.log` forever (measured 2026-11-08: 565,110 B,
last written 2026-09-11; dashboard/routes_loop_status.py called it "an
append log that is never rotated"). It now rotates through core/log_rotation
BEFORE the append, at the same 5 MiB x (1 + 2 backups) bound as the other
RM-718 writers.

Constraints pinned here:
- the controller is launched by ABSOLUTE FILE PATH (ops/loop is not a
  package on sys.path then, and neither is the repo root), so core/log_rotation
  is reached with the same import-then-bind shape as core/polled_json; the
  end-to-end test loads the module by path in a subprocess whose cwd and
  sys.path exclude the checkout;
- its only reader (routes_loop_status) reads the newest LOG_READ_CAP_BYTES of
  the LIVE file, so the cap must stay above that read window;
- a controller line is the loop's audit trail: a refused or failing rotation
  never drops the line.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core import log_rotation  # noqa: E402

lc = importlib.import_module("ops.loop.loop_controller")


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    d = tmp_path / "control"
    d.mkdir()
    monkeypatch.setattr(lc, "CTL", d)
    return d


@pytest.fixture
def small_cap(monkeypatch):
    monkeypatch.setattr(lc, "CONTROLLER_LOG_MAX_BYTES", 100)
    return 100


def _log(ctl: Path) -> Path:
    return ctl / "controller.log"


def _others(ctl: Path) -> list[str]:
    return sorted(p.name for p in ctl.iterdir() if p.name != "controller.log")


def test_cap_matches_the_shared_rm718_bound():
    assert lc.CONTROLLER_LOG_MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert lc.CONTROLLER_LOG_BACKUPS == log_rotation.DEFAULT_BACKUP_COUNT


def test_cap_stays_above_the_dashboard_read_window():
    from dashboard import routes_loop_status as rls
    assert lc.CONTROLLER_LOG_MAX_BYTES > rls.LOG_READ_CAP_BYTES


def test_under_the_cap_lines_are_plain_appends(ctl, small_cap):
    lc.log("one")
    lc.log("two")
    lines = _log(ctl).read_text(encoding="utf-8").splitlines()
    assert [ln.split(" ", 1)[1] for ln in lines] == ["one", "two"]
    assert _others(ctl) == []


def test_at_the_cap_the_old_file_rotates_before_the_append(ctl, small_cap):
    old = b"x" * 99 + b"\n"  # exactly the cap: at, not over, rotates
    assert len(old) == small_cap
    _log(ctl).write_bytes(old)
    lc.log("fresh")
    assert (ctl / "controller.log.1").read_bytes() == old
    live = _log(ctl).read_text(encoding="utf-8")
    assert live.endswith(" fresh\n") and live.count("\n") == 1
    assert _others(ctl) == ["controller.log.1"]


def test_just_under_the_cap_does_not_rotate(ctl, small_cap):
    _log(ctl).write_bytes(b"y" * 99)
    lc.log("next")
    assert _others(ctl) == []
    assert _log(ctl).read_bytes().startswith(b"y" * 99)


def test_two_backups_kept_and_the_oldest_dropped(ctl, small_cap):
    for gen in ("a", "b", "c", "d"):
        _log(ctl).write_bytes(gen.encode() * 120)
        lc.log("line-" + gen)
    assert _others(ctl) == ["controller.log.1", "controller.log.2"]
    assert (ctl / "controller.log.1").read_bytes().startswith(b"d" * 120)
    assert (ctl / "controller.log.2").read_bytes().startswith(b"c" * 120)


def test_refused_rotation_notes_it_and_keeps_the_line(ctl, small_cap,
                                                       monkeypatch):
    _log(ctl).write_bytes(b"z" * 150)

    def refuse(path, backup_count=2):
        return PermissionError(13, "held by another process")

    monkeypatch.setattr(lc.log_rotation, "try_rotate", refuse)
    lc.log("kept")
    raw = _log(ctl).read_text(encoding="utf-8")
    assert raw.startswith("z" * 150)
    tail = raw[150:].splitlines()
    assert len(tail) == 2
    assert "log rotation refused for controller.log" in tail[0]
    assert "PermissionError" in tail[0]
    assert tail[1].endswith(" kept")
    assert _others(ctl) == []


@pytest.mark.parametrize("exc", [OSError(5, "boom"), ValueError("bad")])
def test_a_raising_rotation_never_drops_the_line(ctl, small_cap, monkeypatch,
                                                 exc):
    _log(ctl).write_bytes(b"q" * 150)

    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(lc.log_rotation, "try_rotate", boom)
    lc.log("survives")
    raw = _log(ctl).read_text(encoding="utf-8")
    assert raw.startswith("q" * 150)
    assert raw.endswith(" survives\n")


def test_a_failing_orphan_recovery_never_drops_the_line(ctl, small_cap,
                                                       monkeypatch):
    def boom(*_a, **_k):
        raise OSError(5, "recover refused")

    monkeypatch.setattr(lc.log_rotation, "recover_orphans", boom)
    lc.log("still here")
    assert _log(ctl).read_text(encoding="utf-8").endswith(" still here\n")


def test_missing_log_is_created_without_a_rotation_attempt(ctl, small_cap,
                                                           monkeypatch):
    calls = []
    monkeypatch.setattr(lc.log_rotation, "try_rotate",
                        lambda *a, **k: calls.append(a))
    lc.log("first ever")
    assert calls == []
    assert _log(ctl).read_text(encoding="utf-8").endswith(" first ever\n")


def test_crashed_rotation_scratch_is_recovered_under_the_cap(ctl, small_cap):
    # A hard kill mid-rotation leaves the staged base file under a scratch
    # name; the writer's open recovers it even though the live file is small.
    staged = ctl / "controller.log.rotating-deadbeef"
    staged.write_bytes(b"staged\n")
    lc.log("after crash")
    assert not staged.exists()
    assert (ctl / "controller.log.1").read_bytes() == b"staged\n"


def test_loaded_by_absolute_path_the_cap_still_works(tmp_path):
    """The launcher shape: no repo root on sys.path, cwd outside the checkout."""
    control = tmp_path / "ctl"
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"control_dir": str(control)}), encoding="utf-8")
    mod_path = REPO_ROOT / "ops" / "loop" / "loop_controller.py"
    script = textwrap.dedent(f"""
        import importlib.util, sys
        sys.path[:] = [p for p in sys.path
                       if p and not p.startswith({str(REPO_ROOT)!r})]
        spec = importlib.util.spec_from_file_location(
            "rc_loop_controller_pathload", {str(mod_path)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.log_rotation.__name__ != "core.log_rotation", \\
            mod.log_rotation.__name__
        mod.CONTROLLER_LOG_MAX_BYTES = 50
        log = mod.CTL / "controller.log"
        log.write_bytes(b"o" * 60)
        mod.log("by path")
        print("ROTATED", (mod.CTL / "controller.log.1").read_bytes() == b"o" * 60)
    """)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-c", script, str(cfg)], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=120, creationflags=flags)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "ROTATED True" in proc.stdout
    assert (control / "controller.log").read_text(
        encoding="utf-8").endswith(" by path\n")
