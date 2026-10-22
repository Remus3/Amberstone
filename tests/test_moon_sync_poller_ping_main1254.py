"""MAIN FIX 2026-10-21 1254 item #17 (poller half): `moon_sync_poller.py --ping`
runs as a UserPromptSubmit hook, so it must fail open and write LF only.

Measured at main 915300765 before the fix:
  - the module imported tools.rc_facts and tools.sibling_name_sweep at module
    scope with no guard, so a copy of the hook without those helpers died with
    ImportError (exit 1) before the ping, which needs neither, could run;
  - ping() wrote its JSON with write_text() and no newline argument, so on
    Windows the indented JSON landed with CRLF line ends;
  - ping() swallowed only OSError, so any other fault escaped as exit 1. It
    still does (so a test tripwire stays visible); the --ping entry in main()
    now swallows the rest.
The scan modes (--once, --status, the loop) still fail LOUDLY on a missing
helper: they are not a Claude hook and must not report a blind scan as clean.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tools import moon_sync_poller as P

ROOT = Path(__file__).resolve().parent.parent
POLLER = ROOT / "tools" / "moon_sync_poller.py"


def _ping_file(root: Path) -> Path:
    return root / "ops" / "runtime" / "moon_sync_activity.json"


def test_the_ping_is_written_with_lf_only(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert P.ping(str(root)) == 0
    raw = _ping_file(root).read_bytes()
    assert b"\r" not in raw, raw
    assert json.loads(raw.decode("utf-8"))["stamp"] > 0


def test_a_non_oserror_fault_in_the_ping_hook_still_exits_zero(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    root.mkdir()

    def boom(_repo):
        raise ValueError("synthetic")

    monkeypatch.setattr(P, "_ping_path", boom)
    assert P.main(["--ping", str(root)]) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def _isolated_copy(tmp_path: Path) -> Path:
    """The poller alone in a package with none of its RC helper modules."""
    pkg = tmp_path / "pkg" / "tools"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    copy = pkg / "moon_sync_poller.py"
    shutil.copyfile(POLLER, copy)
    return copy


def test_ping_survives_missing_helper_modules(tmp_path):
    copy = _isolated_copy(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    proc = subprocess.run([sys.executable, "-I", str(copy), "--ping", str(root)],
                          capture_output=True, text=True, cwd=str(tmp_path),
                          check=False, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == "", (proc.stdout, proc.stderr)
    assert b"\r" not in _ping_file(root).read_bytes()


def test_a_scan_mode_still_fails_loudly_without_its_helpers(tmp_path):
    copy = _isolated_copy(tmp_path)
    proc = subprocess.run([sys.executable, "-I", str(copy), "--status",
                           "--repo", str(tmp_path)],
                          capture_output=True, text=True, cwd=str(tmp_path),
                          check=False, timeout=60)
    assert proc.returncode != 0
    assert "import" in proc.stderr.lower(), proc.stderr
