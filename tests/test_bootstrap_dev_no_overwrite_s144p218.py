"""scripts/bootstrap_dev.ps1 never overwrites a file the checkout already has.

The fresh-machine bootstrap used to pipe six here-strings into Set-Content with
no existence check. Four of its targets are TRACKED files (.gitignore,
ruff.toml, tools/preflight.cmd, tools/snapshot.cmd, tools/rollback_last.cmd), so
running it in a clone replaced the repo's real 495-line .gitignore and 93-line
ruff.toml with a stub and then ran `git add -A` plus a "checkpoint" commit over
the result. `-Encoding UTF8` is also a BOM on Windows PowerShell 5.1, and a BOM
on the first line of a .gitignore stops that pattern matching.

The fix is one helper, Write-FileIfAbsent, that keeps an existing file and
writes an absent one as BOM-free ASCII. This module pins both halves: a static
sweep (no bare Set-Content, no UTF8 encoding in the script) and a behaviour run
of the helper itself under Windows PowerShell 5.1 against a temp directory.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bootstrap_dev.ps1"
HELPER = "Write-FileIfAbsent"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _helper_text(src: str) -> str:
    m = re.search(r"^function " + HELPER + r"\b.*?^\}\s*$", src, re.S | re.M)
    assert m, f"{HELPER} is not defined in scripts/bootstrap_dev.ps1"
    return m.group(0)


def _code_lines(src: str) -> list[str]:
    """Source lines outside here-string bodies, comments dropped."""
    out, in_here = [], False
    for line in src.splitlines():
        if in_here:
            if line.startswith("'@"):
                in_here = False
                out.append(line)
            continue
        out.append(line.split("#", 1)[0] if line.lstrip().startswith("#") else line)
        if line.rstrip().endswith("@'"):
            in_here = True
    return out


def test_the_helper_exists_and_guards_on_the_target():
    helper = _helper_text(_source())
    assert "Test-Path" in helper and "-LiteralPath" in helper
    assert "return" in helper


def test_every_file_write_goes_through_the_helper():
    """Set-Content appears once, inside the helper; the six writes call it."""
    src = _source()
    helper = _helper_text(src)
    rest = src.replace(helper, "")
    code = "\n".join(_code_lines(rest))
    assert "Set-Content" not in code, "a file is written outside Write-FileIfAbsent"
    calls = re.findall(r"^\s*" + HELPER + r"\s", code, re.M)
    assert len(calls) == 6, f"expected the six bootstrap writes, found {len(calls)}"


def test_no_write_uses_the_bom_encoding():
    """PS 5.1 -Encoding UTF8 writes a BOM; every payload here is ASCII."""
    assert not re.search(r"-Encoding\s+UTF8", _source(), re.I)


def _powershell() -> str | None:
    return shutil.which("powershell.exe") if sys.platform == "win32" else None


@pytest.mark.skipif(_powershell() is None, reason="Windows PowerShell 5.1 absent")
def test_helper_keeps_an_existing_file_and_writes_an_absent_one_without_a_bom(tmp_path):
    keep = tmp_path / "keep.toml"
    keep.write_bytes(b"tracked = 1\n")
    new = tmp_path / "new.txt"
    script = tmp_path / "run.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        + _helper_text(_source()) + "\n"
        + f"{HELPER} -Path '{keep}' -Encoding ASCII -Content @'\nstub\n'@\n"
        + f"{HELPER} -Path '{new}' -Encoding ASCII -Content @'\nfresh\n'@\n",
        encoding="ascii", newline="\n")
    done = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-File", str(script)],
        capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert done.returncode == 0, done.stderr
    assert keep.read_bytes() == b"tracked = 1\n"
    data = new.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert data.startswith(b"fresh")
