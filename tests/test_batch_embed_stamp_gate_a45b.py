"""A45b (s146) sibling sweep: the batch launchers that START the app on
python-embed\\pythonw.exe use it only when tools/build_python_embed.py
stamped it.

The dev checkout carries a hand-made python-embed (Python 3.11.9 from April,
no EMBED_STAMP.json, half the lock missing). `start.bat` and
`scripts/restart_clean.bat` (what `tools/dev_cli.py start-clean` runs)
preferred it to the PATH pythonw.exe on the bare existence of
pythonw.exe, so a checkout launch ran main.py on that stale runtime. A built
bundle always carries the stamp (tools/build_portable.py refuses an embed
`verify_embed_dir` rejects; tools/run_packaged_smoke.py requires the stamp),
so the gate changes nothing there. An unstamped embed now gets a printed
line and the PATH pythonw.exe (Option A), never a silent pick.

The key-check pickers (`RC_KEY_EMBED` in start.bat, scripts/restart.bat,
scripts/start_debug.bat) are out of scope: they run only the stdlib
core/anthropic_key.py, which the 3.11 runtime runs correctly.

Each case runs the file's REAL launch block under cmd.exe with `start ""`
swapped for an echo, in a tmp tree - nothing is launched.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAUNCHERS = ("start.bat", "scripts/restart_clean.bat")

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe batch semantics")


def _lines(rel: str) -> list[str]:
    return (REPO / rel).read_text(encoding="ascii").splitlines()


def _launch_block(rel: str) -> list[str]:
    """From the first `if` that tests EMBED_PYW to the `)` closing the
    launch's if / else."""
    lines = _lines(rel)
    stripped = [ln.strip() for ln in lines]
    start = next(i for i, ln in enumerate(stripped)
                 if ln.lower().startswith("if ") and "EMBED_PYW" in ln)
    first_start = next(i for i in range(start, len(stripped))
                       if stripped[i].lower().startswith('start ""'))
    end = next(i for i in range(first_start, len(stripped)) if stripped[i] == ")")
    return lines[start:end + 1]


def _run(tmp_path: Path, rel: str, *, embed: bool, stamp: bool) -> str:
    emb = tmp_path / "python-embed"
    if embed:
        emb.mkdir()
        (emb / "pythonw.exe").write_bytes(b"")
        if stamp:
            (emb / "EMBED_STAMP.json").write_text("{}", encoding="ascii")
    set_embed = [ln for ln in _lines(rel) if ln.strip().lower().startswith("set embed_pyw=")]
    assert len(set_embed) == 1, (rel, set_embed)
    block = [ln.replace('start ""', "echo LAUNCH") for ln in _launch_block(rel)]
    head = ["@echo off", "setlocal", f'set "RC_ROOT={tmp_path}"', set_embed[0]]
    bat = tmp_path / "launch_block_harness.bat"
    bat.write_bytes(("\r\n".join(head + block) + "\r\n").encode("ascii"))
    cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    res = subprocess.run([str(cmd), "/d", "/c", str(bat)], capture_output=True, text=True,
                         cwd=str(tmp_path), timeout=30)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _launches(out: str) -> list[str]:
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("LAUNCH")]


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_an_unstamped_embed_is_not_launched_and_says_why(tmp_path, rel):
    out = _run(tmp_path, rel, embed=True, stamp=False)
    launches = _launches(out)
    assert len(launches) == 1, out
    assert "python-embed" not in launches[0], f"{rel} launched the unstamped runtime: {out}"
    assert launches[0].split()[1].lower() == "pythonw.exe", out
    assert "EMBED_STAMP.json" in out, f"{rel} switched interpreters silently: {out}"


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_stamped_embed_is_launched(tmp_path, rel):
    out = _run(tmp_path, rel, embed=True, stamp=True)
    launches = _launches(out)
    assert len(launches) == 1 and "python-embed\\pythonw.exe" in launches[0], out
    assert "EMBED_STAMP.json" not in out, out


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_no_embed_is_plain_option_a(tmp_path, rel):
    out = _run(tmp_path, rel, embed=False, stamp=False)
    launches = _launches(out)
    assert len(launches) == 1 and launches[0].split()[1].lower() == "pythonw.exe", out
    assert "EMBED_STAMP.json" not in out, out
