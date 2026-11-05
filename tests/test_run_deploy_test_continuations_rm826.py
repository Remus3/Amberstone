"""RM-826 (c): ops/run_deploy_test.bat has no trailing ^ continuation.

WHY THIS FILE EXISTS. The operator's manual deploy test ran two of its three
rc_transactional_deploy.py calls split over lines ending in ^:

    "%LOCALAPPDATA%\\...\\python.exe" ops\\rc_transactional_deploy.py ^
      --request "ops\\runtime\\deploy_requests\\...json" ^
      --result  "ops\\runtime\\deploy_results\\...json"

Valid where they sat (outside any ( ... ) block, no ")" after them), but a
trailing ^ is the shape the RM-810 parse-time scanner cannot follow
(tests/test_launcher_key_read_rm810.py, module docstring, the second accepted
hole: a ^ makes the next line's ")" literal, so the block the scan closes is
still open in cmd). These were the only tracked .bat / .cmd lines ending in
^ (measured 2026-10-27 over `git ls-files '*.bat' '*.cmd'`), so each call is
now one line and the shape is gone from the tree rather than relied on.

Pinned here:
  (a) static: no code line of ops/run_deploy_test.bat ends in an active ^
      (a ^ outside double quotes and not itself escaped as ^^). Controls
      show the check flags a real continuation and passes ^^ and a quoted ^;
  (b) behaviour (Windows, with the Python314 interpreter the batch names):
      the batch runs under cmd.exe from a tmp_path copy whose
      ops/rc_transactional_deploy.py is a stub that records its argv, and
      the three calls receive exactly the arguments the continued lines
      gave (--init-key; --sign <request>; --request <request> --result
      <result>). Nothing real runs: the batch cd's into the copy first.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BATCH = "ops/run_deploy_test.bat"
_REQ = r"ops\runtime\deploy_requests\deploy-hot-reload-test-001.json"
_RES = r"ops\runtime\deploy_results\deploy-hot-reload-test-001.json"
_EXPECTED = [["--init-key"], ["--sign", _REQ], ["--request", _REQ, "--result", _RES]]


def _ends_in_active_caret(line: str) -> bool:
    """True when cmd would join `line` with the next one: its last character
    is a ^ that sits outside double quotes and is not escaped by another ^.
    Trailing blanks are stripped first, so `x ^ ` is flagged too although cmd
    escapes the blank instead of joining: conservative, on purpose."""
    text = line.rstrip(" \t")
    quoted = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            quoted = not quoted
        elif ch == "^" and not quoted:
            if i == len(text) - 1:
                return True
            i += 1  # the next character is escaped
        i += 1
    return False


def _is_comment(line: str) -> bool:
    s = line.lstrip().lower()
    return s.startswith(("::", "rem ", "rem\t", "@rem")) or s == "rem"


@pytest.mark.parametrize(("line", "expected"), [
    ("python x.py ^", True),
    ("python x.py ^  ", True),  # conservative, see _ends_in_active_caret
    ("echo literal ^^", False),
    ('echo "inside ^"', False),
    ('echo "a" ^', True),
    ("echo plain", False),
])
def test_active_caret_check_controls(line: str, expected: bool) -> None:
    assert _ends_in_active_caret(line) is expected


def test_run_deploy_test_has_no_trailing_caret_continuation() -> None:
    lines = (REPO / BATCH).read_text(encoding="ascii").splitlines()
    hits = [(n, ln) for n, ln in enumerate(lines, 1)
            if not _is_comment(ln) and _ends_in_active_caret(ln)]
    assert hits == [], f"{BATCH} lines end in a ^ continuation: {hits}"


_STUB = (
    "import json, os, sys\n"
    "with open(os.environ['RC_TEST_ARGV_LOG'], 'a', encoding='utf-8') as f:\n"
    "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
)


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe harness")
def test_run_deploy_test_calls_receive_the_same_arguments(tmp_path: Path) -> None:
    local = os.environ.get("LOCALAPPDATA", "")
    py = Path(local) / "Programs" / "Python" / "Python314" / "python.exe"
    if not local or not py.is_file():
        pytest.skip("the interpreter the batch names is not installed")
    root = tmp_path / "root"
    (root / "ops").mkdir(parents=True)
    (root / BATCH).write_bytes((REPO / BATCH).read_bytes())
    (root / "ops" / "rc_transactional_deploy.py").write_text(_STUB, encoding="ascii")
    log = tmp_path / "argv.jsonl"
    env = dict(os.environ, RC_TEST_ARGV_LOG=str(log))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(root / BATCH)],
        cwd=elsewhere, env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert log.is_file(), f"stub never ran: {proc.stdout!r} {proc.stderr!r}"
    calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert calls == _EXPECTED, proc.stdout
