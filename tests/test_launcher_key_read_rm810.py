"""RM-810: the launchers read the API key at run time, env first, then the file.

WHY THIS FILE EXISTS. At f349e3178 start.bat (lines 11-14),
scripts/restart.bat (13-16) and scripts/start_debug.bat (9-12) read the key
in one parenthesized block:

    if exist "%API_FILE%" (
        set /p ANTHROPIC_API_KEY=<"%API_FILE%"
        set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%
    )

cmd expands every %VAR% in a ( ... ) block once, when the whole block is
parsed, before set /p runs. Measured under cmd.exe 2026-10-23: with no
inherited variable the second line set the literal " =" (a batch file drops
the "%VAR:" of an undefined %VAR:x=y% and keeps the rest), so every launch
lost a good key file and start.bat refused to start; with an inherited
variable its parse-time value - junk included - replaced the key read from
the file. The Machine-scope variable on Legion hid this; once MAIN removes it,
these launchers lose the key.

The fix reads the key with delayed expansion and no block, in the order of
core/anthropic_key.py: an inherited ANTHROPIC_API_KEY first when it is usable
(starts with sk-ant- once its spaces are removed), else API-Key-Claude.txt,
else nothing. One deliberate difference: a candidate holding a double quote
is refused, because the value crosses endlocal through one percent expansion
and a quote there would end the quoted set and run the rest of the line as a
command (measured: a key file reading sk-ant-x"&... ran its tail).

Pinned here:
  (a) static: no tracked batch file reads a %VAR% (or %errorlevel%) set
      earlier in the same ( ... ) block, or earlier on the same line - the
      RM-764 install.bat errorlevel guard, widened to every batch file and
      every variable (it also caught install.bat step 1's PY_VER echo);
  (b) static: the three launchers share ONE key-read block;
  (c) behaviour: each launcher's REAL key read runs under cmd.exe in tmp_path.
      No launch: the cut stops before the launcher's `cd /d` and is refused if
      it holds a start / python / taskkill / wmic line. A child Python prints
      the ANTHROPIC_API_KEY the launched app would inherit, and it must match
      core.anthropic_key.read_anthropic_key for the same env and key file;
  (d) static: no tracked batch or PowerShell file sets a variable in pip's
      PIP_ namespace. pip reads PIP_<OPTION> as its own --<option> (measured:
      PIP_LOG made `pip list` write a 6 KB debug log), and install.bat:67 set
      PIP_LOG to the very file its pip stdout was redirected into.
Every key value here is fake.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from core import anthropic_key
from tests import _repo_walk

REPO = Path(__file__).resolve().parent.parent
KEY_FILE = "API-Key-Claude.txt"
ENV_VAR = "ANTHROPIC_API_KEY"
LAUNCHERS = ("start.bat", "scripts/restart.bat", "scripts/start_debug.bat")
FILE_KEY = "sk-ant-TESTONLY810file"  # rc-credential-scan: allow-fixture
ENV_KEY = "sk-ant-TESTONLY810env"  # rc-credential-scan: allow-fixture

# ---------------------------------------------------------------------------
# (a) parse-time reads in every tracked batch file.
# ---------------------------------------------------------------------------

_SET = re.compile(r'\bset\s+(?:/[ap]\s+)?"?([A-Za-z_]\w*)\s*[-+*/]?=', re.IGNORECASE)
_READ = re.compile(r"(?<!%)%([A-Za-z_]\w*)(?::[^%]*)?%")
_SEP = re.compile(r"(?<!\^)[&|]")


def _is_comment(stripped: str) -> bool:
    low = stripped.lower()
    return low.startswith("::") or low == "rem" or low.startswith(("rem ", "rem\t"))


def parse_time_reads(lines: list[str]) -> list[tuple[int, str, str]]:
    """(line number, variable, line) for each %VAR% read that cmd expands
    before the assignment it means to see has run.

    Two shapes: a read inside a ( ... ) block of a variable set earlier in
    that block (or in an inner block that has closed: the outer block is
    still one parse), and a read in a LATER command on the same line as its
    set (after an & or a |; `set X=%X: =%` reads the old value on purpose).
    Every %errorlevel% inside a block counts. Depth follows the layout of the
    tracked batch files: a code line ending in an unescaped `(` opens a
    block, a code line starting with `)` closes one (`) else (` does both).
    """
    stack: list[set[str]] = []
    hits = []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or _is_comment(s):
            continue
        if s.startswith(")") and stack:
            closed = stack.pop()
            if stack:
                stack[-1] |= closed
        in_block = set().union(*stack) if stack else set()
        sets_here = []  # (where the set command ends, variable)
        for m in _SET.finditer(s):
            sep = _SEP.search(s, m.end())
            sets_here.append((sep.start() if sep else len(s), m.group(1).upper()))
        for m in _READ.finditer(s):
            name = m.group(1).upper()
            same_line = any(end < m.start() and var == name for end, var in sets_here)
            if same_line or (stack and (name in in_block or name == "ERRORLEVEL")):
                hits.append((n, m.group(1), s))
        if stack:
            stack[-1].update(var for _, var in sets_here)
        if s.endswith("(") and not s.endswith("^("):
            stack.append(set())
    return hits


_OLD_KEY_READ = [  # the f349e3178 shape, verbatim
    'set API_FILE=%~dp0API-Key-Claude.txt',
    'if exist "%API_FILE%" (',
    '    set /p ANTHROPIC_API_KEY=<"%API_FILE%"',
    '    set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%',
    ')',
]


def test_scanner_catches_the_old_key_read_and_its_siblings():
    # Anchor: an empty result must not come from a scanner that sees nothing.
    assert [h[:2] for h in parse_time_reads(_OLD_KEY_READ)] == [(4, "ANTHROPIC_API_KEY")]
    nested = ['if a==a (', '    if b==b (', '        set X=1', '    )', '    echo %X%', ')']
    assert [h[:2] for h in parse_time_reads(nested)] == [(5, "X")]
    assert [h[:2] for h in parse_time_reads(['set Y=1 & echo %Y%'])] == [(1, "Y")]
    assert [h[:2] for h in parse_time_reads(['set Y=1|| echo %Y%'])] == [(1, "Y")]
    # Reading the old value inside the set itself is deliberate.
    assert parse_time_reads(['set API_KEY=%API_KEY: =%', 'set /a N=%N%+1']) == []
    assert [h[:2] for h in parse_time_reads(['if 1==1 (', '    cmd /c exit 3',
                                             '    set EC=%errorlevel%', ')'])] == [
        (3, "errorlevel")]
    # The delayed and the flat forms are fine.
    ok = ['setlocal enabledelayedexpansion', 'if a==a (', '    set X=1', '    echo !X!', ')',
          'set Z=1', 'echo %Z%', 'endlocal & set "OUT=%Z%"', ':: set Q=1 & echo %Q%']
    assert parse_time_reads(ok) == []


def _batch_files() -> list[Path]:
    files = _repo_walk.repo_files(REPO, ("*.bat", "*.cmd"))
    rels = {_repo_walk.relative_posix(p, REPO) for p in files}
    assert set(LAUNCHERS) | {"install.bat"} <= rels, (
        f"launchers not reached - the scan proves nothing about them: {sorted(rels)}")
    return files


def test_no_tracked_batch_file_reads_a_variable_at_parse_time():
    offenders = []
    for path in _batch_files():
        lines = path.read_text(encoding="latin-1").splitlines()
        for n, var, line in parse_time_reads(lines):
            offenders.append(f"{_repo_walk.relative_posix(path, REPO)}:{n} %{var}%: {line}")
    assert not offenders, (
        "cmd expands %VAR% once per ( ... ) block (and once per line) before any "
        "command in it runs - read it as !VAR! under delayed expansion, or move it "
        "out of the block: " + "; ".join(offenders))


# ---------------------------------------------------------------------------
# (b) one shared key-read block.
# ---------------------------------------------------------------------------

_TRANSFER = 'endlocal & set "ANTHROPIC_API_KEY=%RC_KEY%"'
_API_FILE_LINE = {
    "start.bat": "set API_FILE=%~dp0API-Key-Claude.txt",
    "scripts/restart.bat": "set API_FILE=%RC_ROOT%\\API-Key-Claude.txt",
    "scripts/start_debug.bat": "set API_FILE=%RC_ROOT%\\API-Key-Claude.txt",
}


def _lines(rel: str) -> list[str]:
    return (REPO / rel).read_text(encoding="ascii").splitlines()


def _key_read(rel: str) -> list[str]:
    """The launcher's key read: its API_FILE line through the endlocal hand-off."""
    lines = [ln.strip() for ln in _lines(rel)]
    start = lines.index(_API_FILE_LINE[rel])
    end = lines.index(_TRANSFER, start)
    return lines[start:end + 1]


def test_the_three_launchers_share_one_key_read():
    blocks = {rel: _key_read(rel)[1:] for rel in LAUNCHERS}
    first = blocks[LAUNCHERS[0]]
    assert first[0] == "setlocal enabledelayedexpansion"
    for rel, block in blocks.items():
        assert block == first, f"{rel} reads the key differently from {LAUNCHERS[0]}"
        assert not any(ln.endswith("(") or ln.startswith(")") for ln in block), (
            f"{rel}: the key read must not sit in a ( ... ) block")
        percent = [ln for ln in block if "%" in ln]
        assert percent == [_TRANSFER], f"{rel}: only the hand-off may expand with %: {percent}"
        assert sum(ln.lower().startswith("set /p ") or " set /p " in ln.lower()
                   for ln in block) == 1


# ---------------------------------------------------------------------------
# (c) the real key read under cmd.exe.
# ---------------------------------------------------------------------------

_LAUNCH = re.compile(r"^(?:start|python|pythonw|python\.exe|pythonw\.exe|taskkill|wmic)\b",
                     re.IGNORECASE)
_PROBE = ("\"{exe}\" -c \"import json,os;"
          "print('KEY=' + json.dumps(os.environ.get('ANTHROPIC_API_KEY')))\"")


def _harness(tmp_path: Path, rel: str) -> Path:
    lines = _lines(rel)
    stripped = [ln.strip() for ln in lines]
    start = stripped.index(_API_FILE_LINE[rel])
    end = next(i for i in range(start, len(lines)) if stripped[i].lower().startswith("cd /d"))
    cut = lines[start:end]
    launches = [ln for ln in stripped[start:end] if _LAUNCH.match(ln)]
    assert not launches, f"the {rel} cut would launch something: {launches}"
    head = ["@echo off", "setlocal"]
    # scripts\*.bat derive RC_ROOT from their own folder; run that real line too.
    head += [ln for ln in lines[:start] if 'set "RC_ROOT=' in ln]
    tail = [_PROBE.format(exe=sys.executable)]
    bat = tmp_path / Path(rel).parent / "key_read_harness.bat"
    bat.parent.mkdir(parents=True, exist_ok=True)
    bat.write_bytes(("\r\n".join(head + cut + tail) + "\r\n").encode("ascii"))
    return bat


def _run(tmp_path: Path, rel: str, env_value, file_bytes):
    if file_bytes is not None:
        (tmp_path / KEY_FILE).write_bytes(file_bytes)
    bat = _harness(tmp_path, rel)
    env = dict(os.environ)
    for name in (ENV_VAR, "RC_KEY", "RC_NOQ"):
        env.pop(name, None)
    if env_value is not None:
        env[ENV_VAR] = env_value
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat)], cwd=str(bat.parent), env=env,
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("ascii", "replace")
    got = [json.loads(ln[4:]) for ln in out.splitlines() if ln.startswith("KEY=")]
    return proc.returncode, out, got


def _line(key: str) -> bytes:
    return key.encode("ascii") + b"\r\n"


# (id, inherited env value or None, key file bytes or None, exported key or None,
#  matches core.anthropic_key)
_SCENARIOS = [
    ("file-only", None, _line(FILE_KEY), FILE_KEY, True),
    ("padded-file", None, b"  " + _line(FILE_KEY) + b"\r\n", FILE_KEY, True),
    ("file-no-newline", None, FILE_KEY.encode("ascii"), FILE_KEY, True),
    ("usable-env-wins", ENV_KEY, _line(FILE_KEY), ENV_KEY, True),
    ("padded-env-wins", "  " + ENV_KEY + " ", _line(FILE_KEY), ENV_KEY, True),
    ("env-only", ENV_KEY, None, ENV_KEY, True),
    ("junk-env-falls-through", "junk", _line(FILE_KEY), FILE_KEY, True),
    ("blank-env-falls-through", "   ", _line(FILE_KEY), FILE_KEY, True),
    ("no-key", None, None, None, True),
    ("junk-env-no-file", "junk", None, None, True),
    ("empty-file", None, b"", None, True),
    ("junk-file", None, b"not-a-key\r\n", None, True),
    ("special-chars-kept", None, b"sk-ant-a!b%PATH%c&d^e|f<g>h\r\n",  # rc-credential-scan: allow-fixture
     "sk-ant-a!b%PATH%c&d^e|f<g>h", True),  # rc-credential-scan: allow-fixture
    ("quote-file-refused", None,
     b'sk-ant-x"&echo.INJECTED>injected.txt&rem."\r\n', None, False),  # rc-credential-scan: allow-fixture
    ("quote-env-falls-through", 'sk-ant-q"&echo.INJECTED>injected.txt',  # rc-credential-scan: allow-fixture
     _line(FILE_KEY), FILE_KEY, False),
]

win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs the launchers under cmd.exe")


@win_only
@pytest.mark.parametrize("rel", LAUNCHERS)
@pytest.mark.parametrize("env_value,file_bytes,expected,parity",
                         [s[1:] for s in _SCENARIOS], ids=[s[0] for s in _SCENARIOS])
def test_launcher_exports_the_key_env_first_then_the_key_file(
        tmp_path, monkeypatch, rel, env_value, file_bytes, expected, parity):
    rc, out, got = _run(tmp_path, rel, env_value, file_bytes)
    assert "INJECTED" not in out and not list(tmp_path.rglob("injected.txt")), (
        f"key content ran as a command: {out!r}")
    if expected is None and rel == "start.bat":
        assert rc == 1, out
        assert "Anthropic API key missing or invalid." in out
        assert got == [], "start.bat must stop before the launch"
        return
    assert rc == 0, out
    assert got == [expected], out
    if parity:
        # The same order as the one lookup every Python reader uses.
        if env_value is None:
            monkeypatch.delenv(ENV_VAR, raising=False)
        else:
            monkeypatch.setenv(ENV_VAR, env_value)
        assert anthropic_key.read_anthropic_key(root=tmp_path) == (expected or "")


@win_only
def test_start_bat_starts_nothing_in_the_harness(tmp_path):
    # The cut stops before `cd /d`; prove the launch line really sits after it.
    lines = [ln.strip() for ln in _lines("start.bat")]
    cd = next(i for i, ln in enumerate(lines) if ln.lower().startswith("cd /d"))
    assert any(_LAUNCH.match(ln) for ln in lines[cd:]), "start.bat launches nothing?"
    assert not any(_LAUNCH.match(ln) for ln in lines[:cd])


# ---------------------------------------------------------------------------
# (d) nothing in pip's PIP_ namespace.
# ---------------------------------------------------------------------------

_PIP_SET = re.compile(
    r'\bset\s+(?:/[ap]\s+)?"?(PIP_\w+)\s*=|\$env:(PIP_\w+)\s*=(?!=)', re.IGNORECASE)


def test_pip_namespace_scanner_catches_the_old_install_bat_line():
    assert _PIP_SET.search(r"set PIP_LOG=%~dp0logs\_pip_install.tmp")
    assert _PIP_SET.search('$env:PIP_INDEX_URL = "x"')
    assert not _PIP_SET.search(r"set RC_PIP_LOG=%~dp0logs\_pip_install.tmp")
    assert not _PIP_SET.search('if ($env:PIP_X -eq "1") {}')


def test_no_tracked_script_sets_a_pip_option_variable():
    files = _repo_walk.repo_files(REPO, ("*.bat", "*.cmd", "*.ps1", "*.psm1"))
    assert any(_repo_walk.relative_posix(p, REPO) == "install.bat" for p in files)
    offenders = []
    for path in files:
        for n, raw in enumerate(path.read_text(encoding="latin-1").splitlines(), 1):
            s = raw.strip()
            if not s or _is_comment(s) or s.startswith("#"):
                continue
            if _PIP_SET.search(s):
                offenders.append(f"{_repo_walk.relative_posix(path, REPO)}:{n}: {s}")
    assert not offenders, (
        "pip reads every PIP_<OPTION> variable as its own --<option>; name a "
        "script variable outside that namespace (RC_PIP_*): " + "; ".join(offenders))


def test_install_bat_pip_log_keeps_its_file_under_the_new_name():
    text = (REPO / "install.bat").read_text(encoding="ascii")
    assert "%PIP_LOG%" not in text and "!PIP_LOG!" not in text
    assert "set RC_PIP_LOG=%~dp0logs\\_pip_install.tmp" in text
    assert text.count('>"%RC_PIP_LOG%" 2>&1') == 2, "both hashed installs log to it"
