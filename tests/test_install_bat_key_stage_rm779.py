"""RM-779: install.bat step 4 stages no key byte outside the repo.

WHY THIS FILE EXISTS. Step 4 (`install.bat`, between its STEP 4 and STEP 5
headers, at adbd2c93f lines 198-218) set
`KEY_TMP=%TEMP%\\rc-install-key-%RANDOM%%RANDOM%.tmp`, echoed the validated key
into it, compared it with `fc /b` against API-Key-Claude.txt, copied it over
the key file and deleted it last: the key sat in a shared temp dir for the
life of the step and survived a crash between the write and the delete. The
acceptance allows staging inside the repo root (gitignored, owner-only) or
comparing in memory; the fix compares in memory (the Python found in step 1
reads the key file and the key from the console's own environment, which
every child of the console already inherits) and writes the key file in
place, so no stage file exists at all.

What is pinned here:
  (a) static: the step-4 block names no temp location and redirects only to
      the key file, the setup log or nul;
  (b) behaviour: the REAL step-4 block runs under cmd.exe in tmp_path (the
      installer itself never runs, RM-681) with TEMP / TMP pointed at a path
      that does not exist, so any temp stage fails the step; the key file is
      rewritten in place (same file id, so its ACL is kept), skipped when it
      already holds exactly the key, and nothing else is left behind.
Every key value here is fake.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BAT = REPO / "install.bat"
KEY_FILE = "API-Key-Claude.txt"
FAKE_KEY = "sk-ant-TESTONLY779stage"  # rc-credential-scan: allow-fixture


def _step4() -> list[str]:
    lines = BAT.read_text(encoding="ascii").splitlines()
    start = next(i for i, ln in enumerate(lines) if "STEP 4 --" in ln)
    end = next(i for i, ln in enumerate(lines) if "STEP 5 --" in ln)
    assert start < end
    return lines[start:end]


def _code(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if not s or low.startswith("::") or low == "rem" or low.startswith(("rem ", "rem\t")):
            continue
        out.append(s)
    return out


def test_step4_names_no_temp_location():
    code = _code(_step4())
    assert code, "the step-4 cut is empty - this guard would pass vacuously"
    offenders = [ln for ln in code
                 if re.search(r"[%!](?:TEMP|TMP)[%!:]|KEY_TMP|GetTempPath|tempfile", ln,
                              re.IGNORECASE)]
    assert not offenders, f"step 4 stages outside the repo: {offenders}"


_REDIRECT = re.compile(r'(?<![0-9&])>>?\s*("[^"]*"|\S+)')


def test_step4_redirects_only_to_the_key_file_the_log_or_nul():
    targets = set()
    for ln in _code(_step4()):
        for m in _REDIRECT.finditer(ln):
            targets.add(m.group(1))
    assert '"%API_FILE%"' in targets, f"no in-place key-file write found: {targets}"
    allowed = {'"%API_FILE%"', '"%LOG_FILE%"', "nul"}
    assert targets <= allowed, f"step 4 writes somewhere else: {targets - allowed}"


# ---------------------------------------------------------------------------
# (b) the real step-4 block under cmd.exe.
# ---------------------------------------------------------------------------

def _harness(tmp_path: Path) -> Path:
    head = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        f'set "PY_EXE={sys.executable}"',
        "set API_FILE=%~dp0" + KEY_FILE,
        f'set "API_KEY={FAKE_KEY}"',
        "set LOG_FILE=%~dp0setup.log",
        "set ERRORS=0",
    ]
    tail = ["echo STEP4=PASS", "goto :EOF", ":SUMMARY", "echo STEP4=FAIL"]
    bat = tmp_path / "step4_harness.bat"
    bat.write_bytes(("\r\n".join(head + _step4() + tail) + "\r\n").encode("ascii"))
    return bat


def _run_step4(tmp_path: Path) -> str:
    bat = _harness(tmp_path)
    missing = tmp_path / "no-such-temp-dir"
    env = dict(os.environ, TEMP=str(missing), TMP=str(missing))
    env.pop("API_KEY", None)
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat)], cwd=str(tmp_path), env=env,
        capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert not missing.exists(), "step 4 created the temp location"
    return proc.stdout.decode("ascii", "replace")


def _left_behind(tmp_path: Path) -> set[str]:
    return {p.name for p in tmp_path.iterdir()} - {
        KEY_FILE, "step4_harness.bat", "setup.log"}


win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs install.bat under cmd.exe")
_EXACT = FAKE_KEY.encode("ascii") + b"\r\n"


@win_only
@pytest.mark.parametrize("raw", [
    pytest.param(b"\xef\xbb\xbf" + FAKE_KEY.encode("ascii") + b"\r\n", id="bom"),
    pytest.param(FAKE_KEY.encode("ascii"), id="no-newline"),
    pytest.param(FAKE_KEY.encode("ascii") + b"  \r\n\r\n", id="padded"),
])
def test_step4_rewrites_the_key_file_in_place_with_no_temp_stage(tmp_path, raw):
    key = tmp_path / KEY_FILE
    key.write_bytes(raw)
    file_id = os.stat(key).st_ino
    out = _run_step4(tmp_path)
    assert "STEP4=PASS" in out, out
    assert "rewritten as one line" in out
    assert key.read_bytes() == _EXACT
    assert os.stat(key).st_ino == file_id, "a replaced key file loses its ACL"
    assert _left_behind(tmp_path) == set()


@win_only
def test_step4_leaves_an_exact_key_file_untouched(tmp_path):
    key = tmp_path / KEY_FILE
    key.write_bytes(_EXACT)
    os.utime(key, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    out = _run_step4(tmp_path)
    assert "STEP4=PASS" in out, out
    assert "already holds the key - unchanged" in out
    assert key.read_bytes() == _EXACT
    assert os.stat(key).st_mtime_ns == 1_000_000_000_000_000_000
    assert _left_behind(tmp_path) == set()


@win_only
def test_step4_fails_when_the_key_file_cannot_be_written(tmp_path):
    key = tmp_path / KEY_FILE
    key.write_bytes(b"sk-ant-OLD  \r\n")  # rc-credential-scan: allow-fixture
    os.chmod(key, stat.S_IREAD)
    try:
        out = _run_step4(tmp_path)
    finally:
        os.chmod(key, stat.S_IREAD | stat.S_IWRITE)
    assert "STEP4=FAIL" in out and "STEP4=PASS" not in out
    assert "[FAIL] Step 4" in (tmp_path / "setup.log").read_text(encoding="ascii")
    assert _left_behind(tmp_path) == set()
