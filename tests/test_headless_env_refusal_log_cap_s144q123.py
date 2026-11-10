"""S144-Q-123 (RM-718 residue), writer ops/loop/headless_env.py: the headless
route refusal log is size-capped.

`ops/loop/headless_env.py` `_log_refusal` appended one JSON line to
`logs/headless_route.log` for every refused headless spawn, forever, with no
size cap (filed by the S144-Q-123 sweep at headless_env.py:116). The file is
absent live (measured 2026-11-09), but every lane worker, the loop executor,
the adjudicator, the CI watchdog and the ephemeral supervisor pass this gate,
so a proxy outage under a running loop appends one row per attempted spawn
for as long as it lasts. It now rotates through core/log_rotation BEFORE the
append, at the same 5 MiB x (1 + 2 backups) bound as the other RM-718 writers.

Constraints pinned here:
- the PowerShell runners call the file as a BARE SCRIPT from a worktree cwd
  (sys.path[0] is ops/loop, so `from core import ...` does not resolve), so
  core/log_rotation is loaded by FILE PATH, lazily, only when a refusal is
  logged; the end-to-end test runs the script from a cwd outside the
  checkout;
- a refusal row is an audit record: no failure of the cap (rotation refused,
  rotation raising, rotation module unavailable) may drop it or raise;
- the file stays JSON lines: a refused rotation is recorded as its own JSON
  row, never as the free-text note other RM-718 writers use.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import log_rotation  # noqa: E402

he = importlib.import_module("ops.loop.headless_env")


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "headless_route.log"
    monkeypatch.setattr(he, "REFUSAL_LOG", path)
    return path


@pytest.fixture
def small_cap(monkeypatch):
    monkeypatch.setattr(he, "REFUSAL_LOG_MAX_BYTES", 100)
    return 100


def _backups(path: Path) -> list[Path]:
    return sorted(p for p in path.parent.iterdir() if p.name != path.name)


def _rows(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines()]


def test_cap_matches_the_shared_rm718_bound():
    assert he.REFUSAL_LOG_MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert he.REFUSAL_LOG_BACKUPS == log_rotation.DEFAULT_BACKUP_COUNT
    assert he.REFUSAL_LOG_MAX_BYTES > 0


def test_rotation_module_is_loaded_by_file_path_from_this_checkout():
    mod = he._log_rotation()
    assert mod is not None
    assert Path(mod.__file__).resolve() == (
        Path(he.__file__).resolve().parents[2] / "core" / "log_rotation.py"
    )
    assert callable(mod.try_rotate) and callable(mod.recover_orphans)
    # Cached: the second call returns the same module object.
    assert he._log_rotation() is mod


def test_importing_the_module_loads_no_rotation_module(tmp_path):
    """The success path (a routed spawn) pays nothing: the load is lazy and
    happens only when a refusal is logged."""
    code = (
        "import runpy, sys\n"
        "ns = runpy.run_path(sys.argv[1], run_name='not_main')\n"
        "print(ns['_LOG_ROTATION_CACHE'])\n"
        "print(any('log_rotation' in m for m in sys.modules))\n"
    )
    p = subprocess.run(
        [sys.executable, "-c", code, str(REPO / "ops" / "loop" / "headless_env.py")],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
    )
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["[]", "False"]


def test_under_the_cap_the_row_is_a_plain_append(log, small_cap):
    he._log_refusal("a", "unset")
    he._log_refusal("b", "proxy_down")
    rows = _rows(log.read_bytes())
    assert [(r["caller"], r["reason"]) for r in rows] == [("a", "unset"), ("b", "proxy_down")]
    assert _backups(log) == []


def test_at_the_cap_the_old_file_rotates_before_the_append(log, small_cap):
    log.parent.mkdir(parents=True)
    old = b"x" * small_cap
    log.write_bytes(old)
    he._log_refusal("lane", "unset")
    rows = _rows(log.read_bytes())
    assert [(r["caller"], r["reason"]) for r in rows] == [("lane", "unset")]
    assert Path(str(log) + ".1").read_bytes() == old
    assert _backups(log) == [Path(str(log) + ".1")]


def test_just_under_the_cap_does_not_rotate(log, small_cap):
    log.parent.mkdir(parents=True)
    log.write_bytes(b"x" * (small_cap - 1))
    he._log_refusal("lane", "unset")
    data = log.read_bytes()
    assert data.startswith(b"x" * (small_cap - 1))
    assert json.loads(data[small_cap - 1:])["reason"] == "unset"
    assert _backups(log) == []


def test_generations_are_bounded_and_the_oldest_drops(log, monkeypatch):
    # A cap smaller than one row, so every next append rotates.
    monkeypatch.setattr(he, "REFUSAL_LOG_MAX_BYTES", 10)
    for i in range(6):
        he._log_refusal(f"gen{i}", "unset")
    names = [p.name for p in _backups(log)]
    assert names == [log.name + f".{i}" for i in range(1, he.REFUSAL_LOG_BACKUPS + 1)]
    assert _rows(log.read_bytes())[0]["caller"] == "gen5"
    assert _rows(Path(str(log) + ".1").read_bytes())[0]["caller"] == "gen4"
    assert _rows(Path(str(log) + ".2").read_bytes())[0]["caller"] == "gen3"


def test_a_refused_rotation_still_appends_the_row_after_a_json_note(
        log, small_cap, monkeypatch):
    log.parent.mkdir(parents=True)
    old = b'{"old": 1}\n' * 10
    log.write_bytes(old)
    mod = he._log_rotation()
    refusal = PermissionError(32, "held by another process")
    monkeypatch.setattr(mod, "try_rotate", lambda *_a, **_k: refusal)
    he._log_refusal("lane", "proxy_down")
    data = log.read_bytes()
    assert data.startswith(old)
    rows = _rows(data[len(old):])
    assert len(rows) == 2
    note, row = rows
    assert note["reason"] == "log_rotation_refused"
    assert note["error"] == "PermissionError"
    assert note["caller"] == "headless_env"
    assert (row["caller"], row["reason"]) == ("lane", "proxy_down")
    assert _backups(log) == []


def test_a_rotation_raced_by_another_writer_writes_no_refusal_note(
        log, small_cap, monkeypatch):
    """try_rotate returns FileNotFoundError when another process rotated the
    file between this writer's stat and its rename: nothing was refused."""
    log.parent.mkdir(parents=True)
    old = b'{"old": 1}\n' * 10
    log.write_bytes(old)
    mod = he._log_rotation()
    monkeypatch.setattr(mod, "try_rotate",
                        lambda *_a, **_k: FileNotFoundError(2, "rotated away"))
    he._log_refusal("lane", "unset")
    rows = _rows(log.read_bytes()[len(old):])
    assert [(r["caller"], r["reason"]) for r in rows] == [("lane", "unset")]


def test_a_rotation_that_raises_never_drops_the_row(log, small_cap, monkeypatch):
    log.parent.mkdir(parents=True)
    log.write_bytes(b"z" * small_cap)
    mod = he._log_rotation()

    def _boom(*_a, **_k):
        raise OSError("disk said no")

    monkeypatch.setattr(mod, "try_rotate", _boom)
    he._log_refusal("lane", "unset")
    assert json.loads(log.read_bytes()[small_cap:])["reason"] == "unset"


def test_a_non_oserror_from_the_cap_never_drops_the_row(log, small_cap, monkeypatch):
    log.parent.mkdir(parents=True)
    log.write_bytes(b"z" * small_cap)
    mod = he._log_rotation()

    def _boom(*_a, **_k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(mod, "recover_orphans", _boom)
    he._log_refusal("lane", "unset")
    assert json.loads(log.read_bytes()[small_cap:])["reason"] == "unset"


def test_no_rotation_module_degrades_to_a_plain_append(log, small_cap, monkeypatch):
    monkeypatch.setattr(he, "_log_rotation", lambda: None)
    log.parent.mkdir(parents=True)
    log.write_bytes(b"z" * small_cap)
    he._log_refusal("lane", "unset")
    data = log.read_bytes()
    assert data.startswith(b"z" * small_cap)
    assert json.loads(data[small_cap:])["reason"] == "unset"


def test_an_unloadable_rotation_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(he, "_LOG_ROTATION_FILE", tmp_path / "absent.py")
    monkeypatch.setattr(he, "_LOG_ROTATION_CACHE", [])
    assert he._log_rotation() is None
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setattr(he, "_LOG_ROTATION_FILE", bad)
    monkeypatch.setattr(he, "_LOG_ROTATION_CACHE", [])
    assert he._log_rotation() is None
    raising = tmp_path / "raising.py"
    raising.write_text("raise RuntimeError('load failed')\n", encoding="utf-8")
    monkeypatch.setattr(he, "_LOG_ROTATION_FILE", raising)
    monkeypatch.setattr(he, "_LOG_ROTATION_CACHE", [])
    assert he._log_rotation() is None


def test_a_failed_load_is_not_cached(monkeypatch, tmp_path):
    """One transient load failure must not switch the cap off for the life of
    a long-running parent: the next refusal loads again."""
    real = he._LOG_ROTATION_FILE
    monkeypatch.setattr(he, "_LOG_ROTATION_CACHE", [])
    monkeypatch.setattr(he, "_LOG_ROTATION_FILE", tmp_path / "absent.py")
    assert he._log_rotation() is None
    assert he._LOG_ROTATION_CACHE == []
    monkeypatch.setattr(he, "_LOG_ROTATION_FILE", real)
    mod = he._log_rotation()
    assert mod is not None and callable(mod.try_rotate)
    assert he._log_rotation() is mod


def test_the_bare_script_run_rotates_an_oversize_log(tmp_path):
    """End to end, the way the .ps1 runners call it: a bare script (sys.path[0]
    is ops/loop) from a cwd outside the checkout, the route unset, the log
    already at the real 5 MiB cap."""
    log_path = tmp_path / "logs" / "headless_route.log"
    log_path.parent.mkdir(parents=True)
    old = b"o" * he.REFUSAL_LOG_MAX_BYTES
    log_path.write_bytes(old)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    env = {k: v for k, v in os.environ.items() if k.upper() != he.ENV_VAR}
    env["RC_HEADLESS_ENV_FORCE_UNSET"] = "1"
    env["RC_HEADLESS_ENV_LOG"] = str(log_path)
    env.pop("PYTHONPATH", None)
    p = subprocess.run(
        [sys.executable, str(REPO / "ops" / "loop" / "headless_env.py"),
         "--url", "--caller", "e2e"],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=60,
    )
    assert p.returncode == he.EXIT_REFUSED, p.stderr
    assert Path(str(log_path) + ".1").read_bytes() == old
    rows = _rows(log_path.read_bytes())
    assert [(r["caller"], r["reason"]) for r in rows] == [("e2e", "unset")]
