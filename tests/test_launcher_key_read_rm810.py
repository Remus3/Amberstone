"""RM-810: the launchers leave the API key lookup to core/anthropic_key.py.

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

6836f8afd moved that read to delayed expansion, but a batch parse of the key
still differed from read_anthropic_key (verifier nits): a key file opening
with a blank line was refused, and an inherited "sk-ant-AB CD" was squashed
to "sk-ant-ABCD" and exported, so it beat a good key file in every Python
reader. So no launcher parses, prints or sets the key any more. Each runs
core/anthropic_key.py itself (runpy, by path, `python -I`) to decide: exit 0
= the inherited ANTHROPIC_API_KEY is usable (left as it is); 2 = it is
absent or unusable and API-Key-Claude.txt is usable; 3 = no usable key. On 2
and 3 the inherited variable is cleared, so junk never shadows the file in
any reader (main.py included); the app then reads the file itself.
start.bat refuses to start on 3, and when the check cannot run at all.

Pinned here:
  (a) static: no tracked batch file reads a %VAR% (or %errorlevel%) set
      earlier in the same ( ... ) block, or in an earlier command on the same
      line - the RM-764 install.bat errorlevel guard, widened to every batch
      file and every variable (it also caught install.bat step 1's PY_VER
      echo). A block opens on a line ending in "(" or holding an unmatched
      "(" mid-line;
  (b) static: the three launchers share ONE key check, call names that exist
      in core/anthropic_key.py, and never read, parse or set the key;
  (c) behaviour: each launcher's REAL key check runs under cmd.exe in
      tmp_path against a copy of core/anthropic_key.py. No launch: the cut
      stops before the launcher's `cd /d` and is refused if it holds a start /
      main.py / taskkill / wmic line. A child Python prints the environment
      the launched app would inherit, and read_anthropic_key over it must give
      what it gives over the original environment;
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
import shutil
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


# A command whose arguments are text, so a "(" in them opens nothing
# (`echo(`, `echo a (b`, `set X=a(b`), behind any leading redirection.
_TEXT_CMD = re.compile(
    r'^@?(?:\d?>>?\s*(?:"[^"]*"|\S+)\s*)*(?:echo|set|title|rem|prompt)'
    r'(?:$|[\s.(:;,=/\\+\[\]])', re.IGNORECASE)
_IF_TEXT_CMD = re.compile(r"^if\b.*\b(?:echo|set|title)\b", re.IGNORECASE)


def _unmatched_opens(s: str) -> list[int]:
    """Positions of the block-opening "(" on a line that no ")" on it closes.

    A "(" opens a block only where a command may start: not inside double
    quotes, not caret-escaped, and not in the text of an echo / set / title.
    A leading ")" (the close of `) else (`) is the caller's business.
    """
    opens: list[int] = []
    quoted = False
    seg = 0  # where the current command starts
    for i, ch in enumerate(s):
        if ch == '"':
            quoted = not quoted
        elif quoted or (i and s[i - 1] == "^"):
            continue
        elif ch in "&|":
            seg = i + 1
        elif ch == "(":
            pre = s[seg:i].strip()
            if _TEXT_CMD.match(pre) or _IF_TEXT_CMD.match(pre):
                continue
            opens.append(i)
            seg = i + 1
        elif ch == ")" and opens:
            opens.pop()
    return opens


def parse_time_reads(lines: list[str]) -> list[tuple[int, str, str]]:
    """(line number, variable, line) for each %VAR% read that cmd expands
    before the assignment it means to see has run.

    Two shapes: a read inside a ( ... ) block of a variable set earlier in
    that block (or in an inner block that has closed: the outer block is
    still one parse), and a read in a LATER command on the same line as its
    set (after an & or a |; `set X=%X: =%` reads the old value on purpose).
    Every %errorlevel% inside a block counts. Depth follows the layout of the
    tracked batch files: a code line ending in an unescaped `(` opens a
    block, and so does each "(" a line leaves unmatched mid-line
    (`if x (set A=1`); a code line starting with `)` closes one (`) else (`
    does both).
    """
    stack: list[set[str]] = []
    hits = []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or _is_comment(s):
            continue
        rest_at = 0
        if s.startswith(")") and stack:
            closed = stack.pop()
            if stack:
                stack[-1] |= closed
            rest_at = 1
        in_block = set().union(*stack) if stack else set()
        sets_here = []  # (where the set command starts, where it ends, variable)
        for m in _SET.finditer(s):
            sep = _SEP.search(s, m.end())
            sets_here.append((m.start(), sep.start() if sep else len(s), m.group(1).upper()))
        for m in _READ.finditer(s):
            name = m.group(1).upper()
            same_line = any(end < m.start() and var == name for _, end, var in sets_here)
            if same_line or (stack and (name in in_block or name == "ERRORLEVEL")):
                hits.append((n, m.group(1), s))
        opens = [rest_at + i for i in _unmatched_opens(s[rest_at:])]
        pushes = max(len(opens), 1 if (s.endswith("(") and not s.endswith("^(")) else 0)
        first_open = opens[0] if opens else len(s)
        if stack:
            stack[-1].update(var for start, _, var in sets_here if start < first_open)
        for _ in range(pushes):
            stack.append(set())
        if pushes:
            stack[-1].update(var for start, _, var in sets_here if start > first_open)
    return hits


_OLD_KEY_READ = [  # the f349e3178 shape, verbatim
    'set API_FILE=%~dp0API-Key-Claude.txt',
    'if exist "%API_FILE%" (',
    '    set /p ANTHROPIC_API_KEY=<"%API_FILE%"',
    '    set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%',
    ')',
]


def _hits(lines: list[str]) -> list[tuple[int, str]]:
    return [h[:2] for h in parse_time_reads(lines)]


def test_scanner_catches_the_old_key_read_and_its_siblings():
    # Anchor: an empty result must not come from a scanner that sees nothing.
    assert _hits(_OLD_KEY_READ) == [(4, "ANTHROPIC_API_KEY")]
    nested = ['if a==a (', '    if b==b (', '        set X=1', '    )', '    echo %X%', ')']
    assert _hits(nested) == [(5, "X")]
    assert _hits(['set Y=1 & echo %Y%']) == [(1, "Y")]
    assert _hits(['set Y=1|| echo %Y%']) == [(1, "Y")]
    assert _hits(['if 1==1 (', '    cmd /c exit 3', '    set EC=%errorlevel%', ')']) == [
        (3, "errorlevel")]
    # Reading the old value inside the set itself is deliberate.
    assert parse_time_reads(['set API_KEY=%API_KEY: =%', 'set /a N=%N%+1']) == []
    # The delayed and the flat forms are fine.
    ok = ['setlocal enabledelayedexpansion', 'if a==a (', '    set X=1', '    echo !X!', ')',
          'set Z=1', 'echo %Z%', 'endlocal & set "OUT=%Z%"', ':: set Q=1 & echo %Q%',
          'for %%I in ("%~dp0..") do set "R=%%~fI"', 'echo  [OK]   done ^(x^)',
          'python -c "print(1)" & echo (balanced)']
    assert parse_time_reads(ok) == []


def test_scanner_catches_a_block_opened_mid_line():
    # Verifier nit 7: a block opened mid-line used to escape the scan.
    assert _hits(['if x==x (set A=1', '    echo %A%', ')']) == [(2, "A")]
    # The else branch runs only when the if branch did not, so its read of the
    # pre-statement value is right and stays unflagged.
    assert _hits(['if x==x (set A=1', '    set B=%A%', ') else (echo %A%', ')']) == [
        (2, "A")]
    assert _hits(['if x==x (', '    if y==y (set A=1', '    )', '    echo %A%', ')']) == [
        (4, "A")]
    assert _hits(['if x==x (', '    cmd /c exit 3 & (echo %errorlevel%', '    )', ')']) == [
        (2, "errorlevel")]
    # Still monotone: every old trigger opens a block as before.
    assert _hits(['if a==a (', '    set X=1', '    echo %X%', ')']) == [(3, "X")]
    # A set before a mid-line open belongs to the enclosing scope, not the block.
    assert _hits(['set C=1 & if x==x (echo %C%', ')']) == [(1, "C")]
    assert _hits(['if x==x (set "D=a(b" & echo !D!', ')']) == []
    # Text parens open nothing, so the depth after them is unchanged.
    text = ['>"%F%" echo(!K!', 'echo a (b', 'set E=a(b', 'if defined E set E=(x',
            'set G=1', 'echo %G%']
    assert _unmatched_opens('>"%F%" echo(!K!') == []
    assert parse_time_reads(text) == []


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
# (b) one shared key check that never touches the key itself.
# ---------------------------------------------------------------------------

_CHECK_PREFIX = '"%RC_KEY_PY%" -I -c '
_CHECK_END = 'set "RC_KEY_MOD="'
_MARKER = ":: RM-810 key check"
_MOD_LINE = {
    "start.bat": 'set "RC_KEY_MOD=%~dp0core\\anthropic_key.py"',
    "scripts/restart.bat": 'set "RC_KEY_MOD=%RC_ROOT%\\core\\anthropic_key.py"',
    "scripts/start_debug.bat": 'set "RC_KEY_MOD=%RC_ROOT%\\core\\anthropic_key.py"',
}


def _lines(rel: str) -> list[str]:
    return (REPO / rel).read_text(encoding="ascii").splitlines()


def _shared_check(rel: str) -> list[str]:
    lines = [ln.strip() for ln in _lines(rel)]
    start = next(i for i, ln in enumerate(lines) if ln.startswith(_CHECK_PREFIX))
    end = lines.index(_CHECK_END, start)
    return lines[start:end + 1]


def test_the_three_launchers_share_one_key_check():
    first = _shared_check(LAUNCHERS[0])
    for rel in LAUNCHERS:
        lines = [ln.strip() for ln in _lines(rel)]
        assert _shared_check(rel) == first, f"{rel} checks the key differently"
        assert sum(ln.startswith(_MARKER) for ln in lines) == 1, rel
        assert _MOD_LINE[rel] in lines, f"{rel} does not name its own core/anthropic_key.py"
        assert lines.index(_MOD_LINE[rel]) < lines.index(first[0])
    assert first[1] == "set RC_KEY_EC=%errorlevel%"


def test_the_key_check_calls_what_core_anthropic_key_defines():
    code = re.search(r'-c "([^"]*)"', _shared_check(LAUNCHERS[0])[0]).group(1)
    names = set(re.findall(r"k\['(\w+)'\]", code))
    assert names == {"ENV_VAR", "usable_key", "read_anthropic_key"}, names
    for name in names:
        assert hasattr(anthropic_key, name), f"core/anthropic_key.py lost {name}"
    assert anthropic_key.ENV_VAR == ENV_VAR
    assert (REPO / "core" / "anthropic_key.py").is_file()


def test_no_launcher_reads_parses_or_sets_the_key():
    for rel in LAUNCHERS:
        for n, raw in enumerate(_lines(rel), 1):
            s = raw.strip()
            if not s or _is_comment(s):
                continue
            where = f"{rel}:{n}: {s}"
            assert not re.search(r"[%!]ANTHROPIC_API_KEY", s, re.IGNORECASE), (
                "the launcher expands the key: " + where)
            assert not re.search(r"\bset\s+/p\b", s, re.IGNORECASE), where
            if not s.lower().startswith("echo"):
                assert not re.search(r"API-Key-Claude", s, re.IGNORECASE), (
                    "the launcher reads the key file itself: " + where)
            for m in re.finditer(r'\bset\s+"?ANTHROPIC_API_KEY=([^"]*)"?', s, re.IGNORECASE):
                assert m.group(1) == "", "the launcher sets the key: " + where


def test_start_bat_prefers_the_embedded_interpreter_for_the_check():
    lines = [ln.strip() for ln in _lines("start.bat")]
    assert "set EMBED_PY=%~dp0python-embed\\python.exe" in lines
    assert 'set "RC_KEY_PY=python"' in lines
    assert lines.index('set "RC_KEY_PY=python"') < lines.index(
        'if exist "%EMBED_PY%" set "RC_KEY_PY=%EMBED_PY%"') < lines.index(
        _shared_check("start.bat")[0])


_LAUNCH = re.compile(r"^(?:start|pythonw|taskkill|wmic)\b|main\.py|apply_patches",
                     re.IGNORECASE)


def test_start_bat_starts_nothing_in_the_harness():
    # The cut stops before `cd /d`; prove the launch line really sits after it.
    # Reads files only, so it runs on every OS (verifier nit 6).
    lines = [ln.strip() for ln in _lines("start.bat")]
    cd = next(i for i, ln in enumerate(lines) if ln.lower().startswith("cd /d"))
    assert any(_LAUNCH.search(ln) for ln in lines[cd:]), "start.bat launches nothing?"
    assert not any(_LAUNCH.search(ln) for ln in lines[:cd])


# ---------------------------------------------------------------------------
# (c) the real key check under cmd.exe.
# ---------------------------------------------------------------------------

_PROBE = ("\"{exe}\" -c \"import json,os;"
          "print('ENV=' + json.dumps({{k: v for k, v in os.environ.items() "
          "if k.upper() == 'ANTHROPIC_API_KEY' or k.upper().startswith('RC_KEY')}}))\"")


def _harness(tmp_path: Path, rel: str, with_module: bool = True) -> Path:
    lines = _lines(rel)
    stripped = [ln.strip() for ln in lines]
    start = next(i for i, ln in enumerate(stripped) if ln.startswith(_MARKER))
    end = next(i for i in range(start, len(lines)) if stripped[i].lower().startswith("cd /d"))
    cut = lines[start:end]
    launches = [ln for ln in stripped[start:end] if _LAUNCH.search(ln)]
    assert not launches, f"the {rel} cut would launch something: {launches}"
    head = ["@echo off", "setlocal"]
    # The variables the launcher set before the cut (start.bat: EMBED_PY;
    # scripts\*.bat: RC_ROOT, derived from their own folder by the real line).
    head += [ln for ln in lines[:start]
             if ln.strip().lower().startswith("set ") or 'set "RC_ROOT=' in ln]
    tail = [_PROBE.format(exe=sys.executable)]
    bat = tmp_path / Path(rel).parent / "key_check_harness.bat"
    bat.parent.mkdir(parents=True, exist_ok=True)
    bat.write_bytes(("\r\n".join(head + cut + tail) + "\r\n").encode("ascii"))
    if with_module:
        (tmp_path / "core").mkdir(exist_ok=True)
        shutil.copyfile(REPO / "core" / "anthropic_key.py", tmp_path / "core" / "anthropic_key.py")
    return bat


def _run(tmp_path: Path, rel: str, env_value, file_bytes, with_module: bool = True):
    if file_bytes is not None:
        (tmp_path / KEY_FILE).write_bytes(file_bytes)
    bat = _harness(tmp_path, rel, with_module)
    env = {k: v for k, v in os.environ.items()
           if k.upper() != ENV_VAR and not k.upper().startswith("RC_KEY")}
    if env_value is not None:
        env[ENV_VAR] = env_value
    # `python` from PATH must be this interpreter (start.bat finds no
    # python-embed in tmp_path; the scripts use PATH python anyway).
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat)], cwd=str(bat.parent), env=env,
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("ascii", "replace")
    seen = [json.loads(ln[4:]) for ln in out.splitlines() if ln.startswith("ENV=")]
    return proc.returncode, out, seen


def _line(key: str) -> bytes:
    return key.encode("ascii") + b"\r\n"


_QUOTE_FILE = 'sk-ant-x"&echo.INJECTED>injected.txt&rem."'  # rc-credential-scan: allow-fixture
_QUOTE_ENV = 'sk-ant-q"&echo.INJECTED>injected.txt'  # rc-credential-scan: allow-fixture
_SPECIAL = "sk-ant-a!b%PATH%c&d^e|f<g>h"  # rc-credential-scan: allow-fixture

# (id, inherited env value or None, key file bytes or None,
#  what read_anthropic_key returns for them)
_SCENARIOS = [
    ("file-only", None, _line(FILE_KEY), FILE_KEY),
    ("padded-file", None, b"  " + _line(FILE_KEY) + b"\r\n", FILE_KEY),
    ("file-no-newline", None, FILE_KEY.encode("ascii"), FILE_KEY),
    ("blank-line-first", None, b"\r\n" + _line(FILE_KEY), FILE_KEY),  # nit 1
    ("blank-lines-around", None, b"\r\n  \r\n\t" + _line(FILE_KEY) + b"\r\n", FILE_KEY),
    ("bom-file", None, b"\xef\xbb\xbf" + _line(FILE_KEY), FILE_KEY),
    ("usable-env-wins", ENV_KEY, _line(FILE_KEY), ENV_KEY),
    ("padded-env-wins", "  " + ENV_KEY + " ", _line(FILE_KEY), ENV_KEY),
    ("env-only", ENV_KEY, None, ENV_KEY),
    ("junk-env-falls-through", "junk", _line(FILE_KEY), FILE_KEY),
    ("blank-env-falls-through", "   ", _line(FILE_KEY), FILE_KEY),
    ("inner-space-env-falls-through", "sk-ant-AB CD", _line(FILE_KEY), FILE_KEY),  # nit 2
    ("inner-tab-env-falls-through", "sk-ant-AB\tCD", _line(FILE_KEY), FILE_KEY),
    ("no-key", None, None, ""),
    ("junk-env-no-file", "junk", None, ""),
    ("inner-space-env-no-file", "sk-ant-AB CD", None, ""),
    ("empty-file", None, b"", ""),
    ("junk-file", None, b"not-a-key\r\n", ""),
    ("inner-space-file", None, b"sk-ant-AB CD\r\n", ""),  # nit 2, the file value
    ("two-line-file", None, _line(FILE_KEY) + _line(ENV_KEY), ""),
    ("special-chars-file", None, _line(_SPECIAL), _SPECIAL),
    ("quote-file", None, _line(_QUOTE_FILE), _QUOTE_FILE),
    ("quote-env", _QUOTE_ENV, _line(FILE_KEY), _QUOTE_ENV),
]

win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs the launchers under cmd.exe")


def _python_lookup(monkeypatch, root: Path, env_value) -> str:
    if env_value is None:
        monkeypatch.delenv(ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(ENV_VAR, env_value)
    return anthropic_key.read_anthropic_key(root=root)


@win_only
@pytest.mark.parametrize("rel", LAUNCHERS)
@pytest.mark.parametrize("env_value,file_bytes,expected",
                         [s[1:] for s in _SCENARIOS], ids=[s[0] for s in _SCENARIOS])
def test_launcher_leaves_the_app_the_key_core_anthropic_key_picks(
        tmp_path, monkeypatch, rel, env_value, file_bytes, expected):
    rc, out, seen = _run(tmp_path, rel, env_value, file_bytes)
    # The table itself is checked against the one Python lookup.
    assert _python_lookup(monkeypatch, tmp_path, env_value) == expected
    # The quote payloads run `echo.INJECTED>injected.txt` if cmd ever parses
    # them (the probe line may print the value itself, so look for the file).
    assert not list(tmp_path.rglob("injected.txt")), f"key content ran as a command: {out!r}"
    assert "INJECTED" not in out.splitlines(), out
    if expected == "" and rel == "start.bat":
        assert rc == 1, out
        assert "Anthropic API key missing or invalid." in out
        assert seen == [], "start.bat must stop before the launch"
        return
    assert rc == 0, out
    assert len(seen) == 1, out
    app_env = seen[0]
    # Nothing but the inherited value, kept as-is when usable, else cleared.
    usable = env_value is not None and anthropic_key.usable_key(env_value.strip())
    assert app_env == ({ENV_VAR: env_value} if usable else {}), app_env
    # And the app's own lookup lands where Python would have from the start.
    assert _python_lookup(monkeypatch, tmp_path, app_env.get(ENV_VAR)) == expected


@win_only
@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_root_with_a_space_and_a_bang_still_checks(tmp_path, rel):
    # The real checkout path holds a space; "!" would break delayed expansion.
    root = tmp_path / "a b!c"
    root.mkdir()
    rc, out, seen = _run(root, rel, "sk-ant-AB CD", _line(FILE_KEY))
    assert rc == 0, out
    assert seen == [{}], "the unusable inherited value must be cleared"
    rc, out, seen = _run(root, rel, ENV_KEY, None)
    assert rc == 0, out
    assert seen == [{ENV_VAR: ENV_KEY}]


@win_only
@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_check_that_cannot_run_changes_nothing(tmp_path, rel):
    # No core/anthropic_key.py under the root: Python exits 1, not 0 / 2 / 3.
    rc, out, seen = _run(tmp_path, rel, "junk", _line(FILE_KEY), with_module=False)
    if rel == "start.bat":
        assert rc == 1, out
        assert "Could not check the Anthropic API key" in out
        assert seen == []
        return
    assert rc == 0, out
    assert seen == [{ENV_VAR: "junk"}], "a failed check must leave the variable alone"


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
