"""RM-764: install.bat step 2 brings the embedded runtime up to the pins.

WHY THIS FILE EXISTS. Measured 2026-10-23 at adbd2c93f in the main checkout's
gitignored `python-embed/` (Python 3.11.9, dist-info read only): anthropic
0.94.1 against the `anthropic==1.11.0` pin in requirements.in /
requirements.txt, pydantic 2.13.0 against 2.13.5, and json5 / opencv-python /
portalocker / psutil / websockets / numpy not installed at all; `import
anthropic, PIL` still succeeds there. Step 2's Option B branch ran the hashed
install only when that import FAILED, so any importable runtime, however old,
skipped pip. Worse, the branch read `%errorlevel%` INSIDE its parenthesized
block, where cmd expands it once, when the whole block is parsed: the install
test and `IMPORT_EC` both saw the errorlevel from BEFORE the block, so a
failing import neither triggered the install nor failed the step (the Option A
branch's `IMPORT_EC` had the same parse-time read).

What is pinned here:
  (a) static: install.bat reads no `%errorlevel%` inside a parenthesized block;
  (b) static: the Option B branch compares the installed versions with the
      requirements.txt pins offline (`pip install -r requirements.txt
      --dry-run --no-index`, measured: exit 0 only when every pin that applies
      to the interpreter is installed at exactly that version) and installs
      the hashed lock without `--no-index` / `--dry-run` / `--no-deps`;
  (c) behaviour: the REAL step-2 block (cut from install.bat between its
      STEP 2 and STEP 3 headers) runs under cmd.exe in tmp_path with a FAKE
      `pip` / `anthropic` / `PIL` shadowing the interpreter's own on
      PYTHONPATH. The real installer never runs (RM-681), real pip never
      runs (a shadow-proof check comes first, PIP_NO_INDEX=1 is the
      backstop), and `%~dp0requirements.txt` is a comment-only file in
      tmp_path.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BAT = REPO / "install.bat"


def _lines() -> list[str]:
    return BAT.read_text(encoding="ascii").splitlines()


def _block(first: str, stop: str) -> list[str]:
    lines = _lines()
    start = next(i for i, ln in enumerate(lines) if first in ln)
    end = next(i for i, ln in enumerate(lines) if stop in ln)
    assert start < end, f"{first!r} must precede {stop!r}"
    return lines[start:end]


def _step2() -> list[str]:
    return _block("STEP 2 -- pip packages", "STEP 3 -- API Key")


def _is_comment(stripped: str) -> bool:
    low = stripped.lower()
    return low.startswith("::") or low == "rem" or low.startswith(("rem ", "rem\t"))


def _parse_time_errorlevel_reads(lines: list[str]) -> list[tuple[int, str]]:
    """(line number, line) of each %errorlevel% read inside a ( ... ) block.

    Depth follows install.bat's own layout: a code line ending in an unescaped
    `(` opens a block, a code line starting with `)` closes one (`) else (`
    does both). A comment line never changes depth.
    """
    depth, hits = 0, []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or _is_comment(s):
            continue
        if s.startswith(")"):
            depth -= 1
        if depth > 0 and re.search(r"%errorlevel%", s, re.IGNORECASE):
            hits.append((n, s))
        if s.endswith("(") and not s.endswith("^("):
            depth += 1
    assert depth == 0, f"unbalanced block depth {depth} - the scan is unreliable"
    return hits


def test_block_scanner_catches_a_parse_time_read():
    # Anchor: an empty result must not come from a scanner that sees nothing.
    sample = ['if "x"=="x" (', '    cmd /c exit 3', '    set EC=%errorlevel%', ')',
              'if %errorlevel% neq 0 (', '    echo ok', ')']
    assert _parse_time_errorlevel_reads(sample) == [(3, "set EC=%errorlevel%")]


def test_install_bat_reads_no_errorlevel_at_block_parse_time():
    hits = _parse_time_errorlevel_reads(_lines())
    assert not hits, (
        "%errorlevel% inside a ( ... ) block expands when the block is parsed, "
        f"before any command in it runs - use !errorlevel!: {hits}")


def _option_b_branch() -> list[str]:
    block = _step2()
    start = next(i for i, ln in enumerate(block)
                 if ln.strip().startswith('if "%OPTION_B%"=="1" ('))
    end = next(i for i in range(start + 1, len(block))
               if block[i].strip().startswith(") else ("))
    return [ln.strip() for ln in block[start + 1:end]]


def test_option_b_compares_installed_versions_with_the_pins_offline():
    branch = _option_b_branch()
    pip_lines = [ln for ln in branch
                 if ln.startswith('"%EMBED_PY%" -m pip install -r "%~dp0requirements.txt"')]
    compares = [ln for ln in pip_lines if "%RC_PIP_CMP%" in ln]
    installs = [ln for ln in pip_lines if "%RC_PIP_CMP%" not in ln]
    cmp_def = [ln for ln in _step2() if ln.strip().startswith("set RC_PIP_CMP=")]
    assert len(cmp_def) == 1, "one offline comparator definition"
    for flag in ("--dry-run", "--no-index"):
        assert flag in cmp_def[0], f"the comparator must run {flag}"
    assert compares, "Option B never compares the runtime with the pins"
    assert branch.index(compares[0]) < branch.index(installs[0]), (
        "the comparison must come before the install it gates")
    assert len(installs) == 1, installs
    for flag in ("--no-index", "--dry-run", "--no-deps", "%RC_PIP_CMP%"):
        assert flag not in installs[0], f"the hashed install must not run {flag}"
    assert any(ln.startswith('"%EMBED_PY%" -c "import anthropic, PIL"') for ln in branch)


# ---------------------------------------------------------------------------
# (c) the real step-2 block under cmd.exe, against a fake pip.
# ---------------------------------------------------------------------------

_FAKE_PIP_MAIN = r'''
import json, os, sys
from pathlib import Path
state_path = Path(os.environ["RC_FAKE_PIP_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]
with open(os.environ["RC_FAKE_PIP_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
if args[:1] != ["install"] or "--upgrade" in args:
    sys.exit(0)
if "--dry-run" in args:
    sys.exit(0 if state["pins_ok"] else 1)
if state["pins_ok"]:
    sys.exit(0)
if state["install_fixes"]:
    state["pins_ok"] = True
    state["importable"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")
    sys.exit(0)
sys.exit(1)
'''

_FAKE_ANTHROPIC = r'''
import json, os
if not json.loads(open(os.environ["RC_FAKE_PIP_STATE"], encoding="utf-8").read())["importable"]:
    raise ImportError("fake anthropic: not importable in this scenario")
'''


def _fake_env(tmp_path: Path, state: dict) -> dict:
    fake = tmp_path / "fake"
    (fake / "pip").mkdir(parents=True)
    (fake / "pip" / "__init__.py").write_text("", encoding="ascii")
    (fake / "pip" / "__main__.py").write_text(_FAKE_PIP_MAIN, encoding="ascii")
    (fake / "anthropic.py").write_text(_FAKE_ANTHROPIC, encoding="ascii")
    (fake / "PIL").mkdir()
    (fake / "PIL" / "__init__.py").write_text("", encoding="ascii")
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(fake),
        PYTHONDONTWRITEBYTECODE="1",
        RC_FAKE_PIP_STATE=str(tmp_path / "state.json"),
        RC_FAKE_PIP_LOG=str(tmp_path / "pip_calls.jsonl"),
        PIP_NO_INDEX="1",
        PIP_CONFIG_FILE=os.devnull,
    )
    # Option A runs `python` from PATH; put this interpreter first on it.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def _pip_calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "pip_calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln]


def _assert_shadowed(tmp_path: Path, env: dict) -> None:
    """Prove `-m pip` resolves to the fake BEFORE any batch line runs."""
    subprocess.run([sys.executable, "-m", "pip", "shadow-probe"], cwd=str(tmp_path),
                   env=env, capture_output=True, timeout=60, check=False,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    calls = _pip_calls(tmp_path)
    assert calls == [["shadow-probe"]], "the fake pip does not shadow the real one"
    (tmp_path / "pip_calls.jsonl").unlink()


def _run_step2(tmp_path: Path, option_b: bool, **state) -> tuple[str, str, list]:
    env = _fake_env(tmp_path, state)
    _assert_shadowed(tmp_path, env)
    (tmp_path / "logs").mkdir()
    (tmp_path / "requirements.txt").write_text(
        "# comment-only stand-in: %~dp0 points at this tmp folder\n", encoding="ascii")
    head = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "set OPTION_B=" + ("1" if option_b else "0"),
        'set "EMBED_PY=' + sys.executable + '"',
        "set LOG_FILE=%~dp0setup.log",
        "set ERRORS=0",
    ]
    tail = ["echo STEP2=PASS", "goto :EOF", ":SUMMARY", "echo STEP2=FAIL"]
    bat = tmp_path / "step2_harness.bat"
    bat.write_bytes(("\r\n".join(head + _step2() + tail) + "\r\n").encode("ascii"))
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat)], cwd=str(tmp_path), env=env,
        capture_output=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("ascii", "replace")
    log = tmp_path / "setup.log"
    log_text = log.read_text(encoding="ascii", errors="replace") if log.exists() else ""
    return out, log_text, _pip_calls(tmp_path)


def _installs(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c[:1] == ["install"]
            and "--dry-run" not in c and "--upgrade" not in c]


def _requirements_arg(call: list[str]) -> str:
    return call[call.index("-r") + 1]


win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs install.bat under cmd.exe")


@win_only
def test_embedded_runtime_at_the_pins_skips_the_install(tmp_path):
    out, _, calls = _run_step2(tmp_path, True, pins_ok=True, importable=True,
                               install_fixes=False)
    assert "STEP2=PASS" in out
    assert _installs(calls) == []


@win_only
def test_embedded_runtime_behind_the_pins_installs_the_hashed_lock(tmp_path):
    # The measured RM-764 case: an importable but stale runtime.
    out, _, calls = _run_step2(tmp_path, True, pins_ok=False, importable=True,
                               install_fixes=True)
    installs = _installs(calls)
    assert len(installs) == 1, f"expected one hashed install, got {calls}"
    assert Path(_requirements_arg(installs[0])) == tmp_path / "requirements.txt"
    assert "STEP2=PASS" in out
    assert "[WARN]" not in out


@win_only
def test_embedded_runtime_that_cannot_import_fails_the_step(tmp_path):
    out, log, calls = _run_step2(tmp_path, True, pins_ok=False, importable=False,
                                 install_fixes=False)
    assert _installs(calls), "a failing import must trigger the install"
    assert "STEP2=FAIL" in out and "STEP2=PASS" not in out
    assert "[FAIL] Step 2" in log


@win_only
def test_embedded_runtime_still_behind_after_the_install_warns(tmp_path):
    # Offline: the install cannot fix the runtime, but the old one imports.
    out, log, calls = _run_step2(tmp_path, True, pins_ok=False, importable=True,
                                 install_fixes=False)
    assert _installs(calls)
    assert "STEP2=PASS" in out
    assert "[WARN]" in out
    assert "[WARN] " in log and "requirements.txt pins" in log
    assert (tmp_path / "logs" / "_pip_install.tmp").exists(), (
        "the WARN names the pip log, so the log must be kept")


@win_only
def test_path_python_that_cannot_import_fails_the_step(tmp_path):
    # The Option A sibling: its IMPORT_EC had the same parse-time read.
    out, log, _ = _run_step2(tmp_path, False, pins_ok=False, importable=False,
                             install_fixes=False)
    assert "STEP2=FAIL" in out and "STEP2=PASS" not in out
    assert "[FAIL] Step 2" in log


@win_only
def test_path_python_that_imports_passes_the_step(tmp_path):
    out, _, calls = _run_step2(tmp_path, False, pins_ok=True, importable=True,
                               install_fixes=False)
    assert "STEP2=PASS" in out
    assert len(_installs(calls)) == 1, "Option A always installs the hashed lock"
