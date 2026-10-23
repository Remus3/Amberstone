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
core/anthropic_key.py itself (runpy, by path, `python -I`) to decide: exit
10 = the inherited ANTHROPIC_API_KEY is usable (left as it is); 11 = it is
absent or unusable and API-Key-Claude.txt is usable; 12 = no usable key
(codes no interpreter emits on its own; anything else = the check could not
run). On 11 and 12 the inherited variable is cleared, so junk never shadows
the file in any reader (main.py included); the app then reads the file
itself. start.bat refuses to start on 12, and when the check cannot run. The
check runs after the launcher's `cd /d` to the repo root, with an absolute
interpreter (python-embed first, else python.exe found by the PATH search of
`for`, which never looks in the CALLER's folder): a bare `python` was looked
up in the caller's folder first (second verifier, N1). The PATH search does
not consult the current folder as such, but an empty, "." or leading ";"
PATH entry can still make it look in the repo root, where the launcher has
cd'd by then (fourth verifier).

Pinned here:
  (a) static, CONSERVATIVE AGAINST THE NAMED SHAPES ONLY - not a proof that
      no parse-time read exists: the scan flags a %VAR% read of a variable
      set earlier in the same ( ... ) block, or in an earlier command on the
      same line, or on the line that closes the block, and an %errorlevel%
      read inside a block, in every tracked batch file (the RM-764
      install.bat errorlevel guard, widened; it caught install.bat step 1's
      PY_VER echo). A block opens on a line ending in "(" or at an unmatched
      "(" mid-line; only the echo( idiom is skipped, and tracked text parens
      are allowlisted by exact line. KNOWN HOLES, accepted as residuals
      (third verifier, scratchpad s129-verify810c/holes2.py; all also in the
      6836f8afd scanner):
        - a phase-1 quote substitution such as %VAR:"=% flips the scan's
          quote parity and can hide a mid-line "(". The launchers' own
          `call set "RC_KEY_SP=%%PATH:"=%%"` line has this shape; it is
          harmless there, as the line holds no "(";
        - a trailing ^ continuation makes the next line's ")" literal, so
          the block the scan closes is still open in cmd. Tracked lines
          ending in ^ (ops/install_startup.bat:27-34,
          ops/run_deploy_test.bat:8, 12-13) sit outside any block, with no
          ")" after them;
        - %errorlevel% read later on the same line, outside any block
          (`cmd /c exit 3 & echo %errorlevel%`);
        - a ^^& separator (a literal caret, then a real &) is not a
          command boundary to the same-line check;
        - variable names with a dash (RC-X) are not read or set names;
        - only the first name of a multi-assign `set /a A=1, B=2` is seen.
      Measured 2026-10-23 over every tracked .bat / .cmd: no line other
      than the ones named above has any of these shapes;
  (b) static: the three launchers share ONE key check, run it after cd /d
      with an absolute interpreter, call names that exist in
      core/anthropic_key.py, never read, parse or set the key, run every
      system tool by its absolute System32 path and set no variable they do
      not use;
  (c) behaviour: each launcher's REAL key check runs under cmd.exe in
      tmp_path against a copy of core/anthropic_key.py, started from an
      unrelated folder (one test plants python.bat / python.cmd there, one
      quotes the Python folder on PATH). No launch: the cut runs from the
      launcher's `cd /d` to the end of its check and is refused if it holds
      a start / main.py / taskkill / wmic line. A child Python prints the
      environment the launched app would inherit, and read_anthropic_key over
      it must give what it gives over the original environment. Separately,
      restart.bat's system-tool lines run with planted taskkill / timeout /
      wmic scripts in the caller's folder (taskkill aimed at an image that
      does not exist; wmic is pinned statically only);
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


# The ONE "(" that is never a block open: the echo( / echo.( idiom, where
# echo is the command token at the very start of a command segment. Every
# other unquoted, unescaped "(" counts, text or not - the scan errs toward
# over-detection, and a tracked line that false-hits is allowlisted by its
# exact file and text (TEXT_PAREN_LINES), never by a broader skip.
_ECHO_PAREN = re.compile(r"^\s*@?echo\.?\($", re.IGNORECASE)


def _unmatched_opens(s: str) -> list[int]:
    """Positions of the "(" on a line that no ")" on it closes.

    Quotes toggle only when not caret-escaped (`^"` is a literal quote
    outside quotes); a caret outside quotes makes the next character literal,
    and inside quotes a caret is literal itself. A leading ")" (the close of
    `) else (`) is the caller's business.
    """
    opens: list[int] = []
    quoted = False
    seg = 0  # where the current command segment starts
    i = 0
    while i < len(s):
        ch = s[i]
        if quoted:
            quoted = ch != '"'
        elif ch == "^":
            i += 1  # the next character is literal
        elif ch == '"':
            quoted = True
        elif ch in "&|":
            seg = i + 1
        elif ch == "(":
            if not _ECHO_PAREN.match(s[seg:i + 1]):
                opens.append(i)
            seg = i + 1
        elif ch == ")" and opens:
            opens.pop()
        i += 1
    return opens


# Tracked lines whose mid-line "(" is text, not a block open, by exact file
# and stripped line. Each entry was read and confirmed by hand. Measured
# 2026-10-23: the only tracked line the mid-line opener counts beyond the
# old line-ends-in-"(" trigger is this one - the echo( idiom behind a
# leading redirection (install.bat step 4, the in-place key-file write).
TEXT_PAREN_LINES: dict[str, frozenset[str]] = {
    "install.bat": frozenset({'>"%API_FILE%" echo(!API_KEY!'}),
}


def parse_time_reads(lines: list[str],
                     text_paren: frozenset[str] = frozenset()) -> list[tuple[int, str, str]]:
    """(line number, variable, line) for each %VAR% read that cmd expands
    before the assignment it means to see has run.

    Two shapes: a read inside a ( ... ) block of a variable set earlier in
    that block (or in an inner block that has closed: the outer block is
    still one parse), and a read in a LATER command on the same line as its
    set (after an & or a |; `set X=%X: =%` reads the old value on purpose).
    Every %errorlevel% inside a block counts, and so does every read on the
    line that closes a block (`) & echo %A%` is still part of its parse).
    Depth follows the layout of the tracked batch files: a code line ending
    in an unescaped `(` opens a block, and so does each "(" a line leaves
    unmatched mid-line (`if x (set A=1`), except on a `text_paren` line; a
    code line starting with `)` closes one (`) else (` does both). Where it
    is unsure it flags (an else branch reading what its if branch set is
    flagged too), but it is conservative against the named shapes only: the
    module docstring lists the known holes it does NOT catch.
    """
    stack: list[set[str]] = []
    hits = []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or _is_comment(s):
            continue
        # Reads on a closing line are checked before the pop: they belong to
        # the same parse as the block they close.
        in_block = set().union(*stack) if stack else set()
        in_any = bool(stack)
        rest_at = 0
        if s.startswith(")") and stack:
            closed = stack.pop()
            if stack:
                stack[-1] |= closed
            rest_at = 1
        sets_here = []  # (where the set command starts, where it ends, variable)
        for m in _SET.finditer(s):
            sep = _SEP.search(s, m.end())
            sets_here.append((m.start(), sep.start() if sep else len(s), m.group(1).upper()))
        for m in _READ.finditer(s):
            name = m.group(1).upper()
            same_line = any(end < m.start() and var == name for _, end, var in sets_here)
            if same_line or (in_any and (name in in_block or name == "ERRORLEVEL")):
                hits.append((n, m.group(1), s))
        opens = ([] if s in text_paren
                 else [rest_at + i for i in _unmatched_opens(s[rest_at:])])
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
    # Over-detection by design: an else branch reading what its if branch set
    # is flagged too (it only ever sees the pre-statement value).
    assert _hits(['if x==x (set A=1', '    set B=%A%', ') else (echo %A%', ')']) == [
        (2, "A"), (3, "A")]
    assert _hits(['if x==x (', '    if y==y (set A=1', '    )', '    echo %A%', ')']) == [
        (4, "A")]
    assert _hits(['if x==x (', '    cmd /c exit 3 & (echo %errorlevel%', '    )', ')']) == [
        (2, "errorlevel")]
    # Still monotone: every old trigger opens a block as before.
    assert _hits(['if a==a (', '    set X=1', '    echo %X%', ')']) == [(3, "X")]
    # A set before a mid-line open belongs to the enclosing scope, not the block.
    assert _hits(['set C=1 & if x==x (echo %C%', ')']) == [(1, "C")]
    assert _hits(['if x==x (set "D=a(b" & echo !D!', ')']) == []


# The second verifier's repros (scratchpad s129-verify810b/scan_holes.py),
# verbatim, each with what cmd.exe printed: the read saw the stale value.
_REPROS = {
    "if_cond_has_set_word": (['if exist set.txt (set A=1', '    echo A=[%A%]', ')'],
                             [(2, "A")], "A=[]"),
    "if_cond_has_title_word": (['if /i "x"=="x" if exist title.txt (set "T=new"',
                                '    echo T=[%T%]', ')'], [(2, "T")], "T=[old]"),
    "escaped_quote_hides_open": (['echo ^" & if 1==1 (set A=1', '    echo A=[%A%]', ')'],
                                 [(2, "A")], "A=[]"),
    "read_after_close_paren": (['if 1==1 (', '    set A=1', ') & echo A=[%A%]'],
                               [(3, "A")], "A=[]"),
    "control_mid_line_open": (['if 1==1 (set A=1', '    echo A=[%A%]', ')'],
                              [(2, "A")], "A=[]"),
}


@pytest.mark.parametrize("name", sorted(_REPROS))
def test_scanner_catches_the_second_verifier_repros(name):
    body, expected, _ = _REPROS[name]
    assert _hits(body) == expected


@pytest.mark.skipif(sys.platform != "win32", reason="runs the repros under cmd.exe")
@pytest.mark.parametrize("name", sorted(_REPROS))
def test_the_repros_really_read_a_stale_value(tmp_path, name):
    body, _, stale = _REPROS[name]
    (tmp_path / "set.txt").write_text("x", encoding="ascii")
    (tmp_path / "title.txt").write_text("x", encoding="ascii")
    bat = tmp_path / "repro.bat"
    bat.write_bytes(("\r\n".join(["@echo off", "setlocal", 'set "A="', 'set "T=old"'] + body)
                     + "\r\n").encode("ascii"))
    proc = subprocess.run(["cmd.exe", "/d", "/v:off", "/c", str(bat)], cwd=str(tmp_path),
                          capture_output=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("ascii", "replace")
    assert stale in [ln.strip() for ln in out.splitlines()], out


def test_only_the_echo_paren_idiom_is_skipped():
    assert _unmatched_opens("echo(") == []
    assert _unmatched_opens("  @ECHO.(x") == []
    assert _unmatched_opens("x & echo(y") == []
    # Anything else counts: text, keywords elsewhere, redirection first.
    assert _unmatched_opens("echo a (b") == [7]
    assert _unmatched_opens("set E=a(b") == [7]
    assert _unmatched_opens('>"f" echo(x') == [9]
    assert _unmatched_opens("title (x") == [6]
    assert _unmatched_opens('echo "(" ^( (') == [12]
    assert _unmatched_opens('echo ^" (') == [8]
    assert _unmatched_opens("echo ^^(") == [7]
    assert _hits(['echo a (b', 'set G=1', 'echo %G%']) == [(3, "G")]
    # An allowlisted exact line opens nothing mid-line.
    assert parse_time_reads(['echo a (b', 'set G=1', 'echo %G%'],
                            text_paren=frozenset({"echo a (b"})) == []


def _batch_files() -> list[Path]:
    files = _repo_walk.repo_files(REPO, ("*.bat", "*.cmd"))
    rels = {_repo_walk.relative_posix(p, REPO) for p in files}
    assert set(LAUNCHERS) | {"install.bat"} <= rels, (
        f"launchers not reached - the scan proves nothing about them: {sorted(rels)}")
    return files


def test_no_tracked_batch_file_reads_a_variable_at_parse_time():
    offenders = []
    for path in _batch_files():
        rel = _repo_walk.relative_posix(path, REPO)
        lines = path.read_text(encoding="latin-1").splitlines()
        allowed = TEXT_PAREN_LINES.get(rel, frozenset())
        missing = allowed - {ln.strip() for ln in lines}
        assert not missing, f"{rel}: stale TEXT_PAREN_LINES entries {sorted(missing)}"
        for n, var, line in parse_time_reads(lines, allowed):
            offenders.append(f"{rel}:{n} %{var}%: {line}")
    assert not offenders, (
        "cmd expands %VAR% once per ( ... ) block (and once per line) before any "
        "command in it runs - read it as !VAR! under delayed expansion, or move it "
        "out of the block: " + "; ".join(offenders))


# ---------------------------------------------------------------------------
# (b) one shared key check that never touches the key itself.
# ---------------------------------------------------------------------------

_SHARED_START = 'set "RC_KEY_PY="'
_CHECK_PREFIX = 'if defined RC_KEY_PY "%RC_KEY_PY%" -I -c '
_CHECK_END = 'set "RC_KEY_MOD="'
_EC_END = 'set "RC_KEY_EC="'
_MARKER = ":: RM-810 key check"
_ROOT = {"start.bat": "%~dp0", "scripts/restart.bat": "%RC_ROOT%\\",
         "scripts/start_debug.bat": "%RC_ROOT%\\"}
_CD_LINE = {"start.bat": 'cd /d "%~dp0"', "scripts/restart.bat": 'cd /d "%RC_ROOT%"',
            "scripts/start_debug.bat": 'cd /d "%RC_ROOT%"'}


def _mod_line(rel: str) -> str:
    return f'set "RC_KEY_MOD={_ROOT[rel]}core\\anthropic_key.py"'


def _embed_line(rel: str) -> str:
    return f'set "RC_KEY_EMBED={_ROOT[rel]}python-embed\\python.exe"'


def _lines(rel: str) -> list[str]:
    return (REPO / rel).read_text(encoding="ascii").splitlines()


def _shared_check(rel: str) -> list[str]:
    lines = [ln.strip() for ln in _lines(rel)]
    start = lines.index(_SHARED_START)
    end = lines.index(_CHECK_END, start)
    return lines[start:end + 1]


def _check_line(rel: str) -> str:
    return next(ln for ln in _shared_check(rel) if ln.startswith(_CHECK_PREFIX))


def test_the_three_launchers_share_one_key_check():
    first = _shared_check(LAUNCHERS[0])
    for rel in LAUNCHERS:
        lines = [ln.strip() for ln in _lines(rel)]
        assert _shared_check(rel) == first, f"{rel} checks the key differently"
        assert sum(ln.startswith(_MARKER) for ln in lines) == 1, rel
        for own in (_mod_line(rel), _embed_line(rel)):
            assert own in lines, f"{rel} lacks {own}"
            assert lines.index(own) < lines.index(_SHARED_START)
    assert 'if defined RC_KEY_PY set RC_KEY_EC=%errorlevel%' in first


def test_the_check_runs_after_cd_to_the_repo_root():
    # Verifier N1: a bare `python` run before `cd /d` was looked up in the
    # caller's folder first.
    for rel in LAUNCHERS:
        lines = [ln.strip() for ln in _lines(rel)]
        cd = lines.index(_CD_LINE[rel])
        assert cd < lines.index(_SHARED_START), f"{rel}: the key check runs before cd /d"
        assert [ln for ln in lines if ln.lower().startswith("cd ")] == [_CD_LINE[rel]], rel


_EMBED_PICK = 'if exist "%RC_KEY_EMBED%" set "RC_KEY_PY=%RC_KEY_EMBED%"'
_ON_PATH = 'if not defined RC_KEY_PY for %%I in (python.exe) do set "RC_KEY_PY=%%~$PATH:I"'
# Only when python-embed is absent AND the PATH search missed: %%~$PATH:I
# finds nothing in a QUOTED entry ("C:\Windows\py";...), so a quote-stripped copy is
# searched (third verifier). The copy is built by `call`, so the line only
# expands PATH when it runs: a whole PATH of about 8176 to 8191 characters on
# one command line is "The input line is too long." and aborts the batch
# (fourth verifier), and the common path must never pay that.
_STRIP_COPY = 'if not defined RC_KEY_PY call set "RC_KEY_SP=%%PATH:"=%%"'
_ON_COPY = 'if not defined RC_KEY_PY for %%I in (python.exe) do set "RC_KEY_PY=%%~$RC_KEY_SP:I"'


def test_the_interpreter_is_an_absolute_path_embedded_first():
    shared = _shared_check(LAUNCHERS[0])
    order = [_SHARED_START, _EMBED_PICK, _ON_PATH, _STRIP_COPY, _ON_COPY, 'set "RC_KEY_SP="',
             _check_line(LAUNCHERS[0])]
    assert [shared.index(ln) for ln in order] == sorted(shared.index(ln) for ln in order)
    for rel in LAUNCHERS:
        values = set(re.findall(r'set "RC_KEY_PY=([^"]*)"', "\n".join(_lines(rel))))
        assert values == {"", "%RC_KEY_EMBED%", "%%~$PATH:I", "%%~$RC_KEY_SP:I"}, (
            f"{rel} sets the interpreter to something else: {values}")


def test_no_launcher_line_expands_path_on_the_common_path():
    # A plain %PATH...% read is expanded when its line is parsed, whether or
    # not the line runs. The one PATH read is the doubled %%PATH:"=%% under
    # `if not defined RC_KEY_PY call`, which expands only when it runs.
    for rel in LAUNCHERS:
        for n, raw in enumerate(_lines(rel), 1):
            s = raw.strip()
            if not s or _is_comment(s):
                continue
            assert not re.search(r"(?<!%)%PATH[%:]", s, re.IGNORECASE), (
                f"{rel}:{n} expands PATH whenever the line is parsed: {s}")
            if re.search(r"%%PATH", s, re.IGNORECASE):
                assert s == _STRIP_COPY, f"{rel}:{n}: {s}"


# External Windows tools a launcher might call. Each must be named by its
# absolute System32 path: a bare name is looked up in the caller's folder
# first, where a planted taskkill.bat / timeout.bat would run (third
# verifier; same root cause as N1).
_SYSTEM_TOOLS = {"wmic": "%SystemRoot%\\System32\\wbem\\wmic.exe"} | {
    tool: f"%SystemRoot%\\System32\\{tool}.exe"
    for tool in ("taskkill", "timeout", "tasklist", "where", "findstr", "reg", "schtasks",
                 "choice", "ping", "sc", "net", "powershell", "wscript", "cscript")}


# The command token of each command on a line: at its start, or after & | (
# or a for's `do`. A tool named only as an argument (wmic's `where`) is not
# a command.
_CMD_TOKEN = re.compile(r'(?:^|[&|(]|\bdo\s)\s*@?("[^"]*"|[^\s&|()]+)', re.IGNORECASE)


def test_launchers_name_every_system_tool_by_its_absolute_path():
    seen = set()
    for rel in LAUNCHERS:
        for n, raw in enumerate(_lines(rel), 1):
            s = raw.strip()
            if not s or _is_comment(s):
                continue
            for m in _CMD_TOKEN.finditer(s):
                token = m.group(1)
                name = re.split(r"[\\/]", token.strip('"'))[-1].lower()
                name = name[:-4] if name.endswith(".exe") else name
                if name in _SYSTEM_TOOLS:
                    seen.add(name)
                    assert token == f'"{_SYSTEM_TOOLS[name]}"', (
                        f"{rel}:{n} runs {name} as {token}, not by its System32 path: {s}")
    # Anchor: restart.bat's three tools must be found, or this proves nothing.
    assert {"wmic", "taskkill", "timeout"} <= seen, seen


def test_launchers_set_no_variable_they_do_not_use():
    # Third verifier nit 3: start.bat kept `set EMBED_PY=...` after the key
    # check stopped using it. RIOT_COMMANDER_DEBUG is read by the app.
    passed_to_the_app = {"RIOT_COMMANDER_DEBUG", "ANTHROPIC_API_KEY"}
    for rel in LAUNCHERS:
        code = [ln.strip() for ln in _lines(rel) if ln.strip() and not _is_comment(ln.strip())]
        text = "\n".join(code)
        for name in {m.group(1).upper() for m in _SET.finditer(text)} - passed_to_the_app:
            used = re.search(rf"%{name}[%:]|!{name}[!:]|\bdefined\s+{name}\b|%~\${name}:",
                             text, re.IGNORECASE)
            assert used, f"{rel} sets {name} but never reads it"


def test_the_check_exit_codes_are_ones_no_interpreter_emits():
    # Verifier N2: 2 is CPython's own usage-error exit. 10 / 11 / 12 are not
    # emitted by python on its own; any other code means "could not run".
    code = re.search(r'-c "([^"]*)"', _check_line(LAUNCHERS[0])).group(1)
    assert code.endswith("sys.exit(10 if k['usable_key'](e) else 11 if "
                         "k['read_anthropic_key']() else 12)"), code
    shared = _shared_check(LAUNCHERS[0])
    assert 'set "RC_KEY_EC=none"' in shared
    assert [ln for ln in shared if "ANTHROPIC_API_KEY" in ln] == [
        'if "%RC_KEY_EC%"=="11" set "ANTHROPIC_API_KEY="',
        'if "%RC_KEY_EC%"=="12" set "ANTHROPIC_API_KEY="']
    start = [ln.strip() for ln in _lines("start.bat")]
    assert 'if "%RC_KEY_EC%"=="12" (' in start
    assert 'if not "%RC_KEY_EC%"=="10" if not "%RC_KEY_EC%"=="11" (' in start


def test_the_key_check_calls_what_core_anthropic_key_defines():
    code = re.search(r'-c "([^"]*)"', _check_line(LAUNCHERS[0])).group(1)
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


_LAUNCH = re.compile(r"^(?:start|pythonw|taskkill|wmic)\b|main\.py|apply_patches",
                     re.IGNORECASE)


def _cut_bounds(rel: str) -> tuple[int, int]:
    """The harness cut: the launcher's `cd /d` to the repo root through the
    line that clears RC_KEY_EC (start.bat: after its two refusal blocks)."""
    stripped = [ln.strip() for ln in _lines(rel)]
    marker = next(i for i, ln in enumerate(stripped) if ln.startswith(_MARKER))
    start = stripped.index(_CD_LINE[rel])
    assert start < marker
    return start, stripped.index(_EC_END, marker) + 1


def test_no_harness_cut_starts_anything():
    # Reads files only, so it runs on every OS (verifier nit 6).
    for rel in LAUNCHERS:
        lines = [ln.strip() for ln in _lines(rel)]
        start, end = _cut_bounds(rel)
        assert not [ln for ln in lines[start:end] if _LAUNCH.search(ln)], rel
        assert any(_LAUNCH.search(ln) for ln in lines[end:]), f"{rel} launches nothing?"


# ---------------------------------------------------------------------------
# (c) the real key check under cmd.exe.
# ---------------------------------------------------------------------------

_PROBE = ("\"{exe}\" -c \"import json,os;"
          "print('ENV=' + json.dumps({{k: v for k, v in os.environ.items() "
          "if k.upper() == 'ANTHROPIC_API_KEY' or k.upper().startswith('RC_KEY')}}))\"")


def _harness(tmp_path: Path, rel: str, with_module: bool = True) -> Path:
    lines = _lines(rel)
    start, end = _cut_bounds(rel)
    cut = lines[start:end]
    launches = [ln.strip() for ln in cut if _LAUNCH.search(ln.strip())]
    assert not launches, f"the {rel} cut would launch something: {launches}"
    head = ["@echo off", "setlocal"]
    # The variables the launcher set before the cut (start.bat: EMBED_PYW;
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


# A planted interpreter: it leaves a marker next to itself and claims the
# inherited variable is usable.
_PLANT = b"@echo off\r\necho PLANTED>\"%~dp0planted.txt\"\r\nexit /b 10\r\n"


def _run(tmp_path: Path, rel: str, env_value, file_bytes, with_module: bool = True,
         plant: bool = False, path: str | None = None):
    if file_bytes is not None:
        (tmp_path / KEY_FILE).write_bytes(file_bytes)
    bat = _harness(tmp_path, rel, with_module)
    # The launcher is started from an unrelated folder, as from a shortcut or
    # another console; its own `cd /d` moves it to the repo root.
    caller = tmp_path / "caller"
    caller.mkdir(exist_ok=True)
    if plant:
        for where in (caller, tmp_path):
            (where / "python.bat").write_bytes(_PLANT)
            (where / "python.cmd").write_bytes(_PLANT)
    # NoDefaultCurrentDirectoryInExePath (set in agent shells) stops cmd from
    # searching the caller's folder for a command; a user's console or
    # Explorer launch does not have it, so neither does the harness.
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in (ENV_VAR, "NODEFAULTCURRENTDIRECTORYINEXEPATH")
           and not k.upper().startswith("RC_KEY")}
    if env_value is not None:
        env[ENV_VAR] = env_value
    # python.exe on PATH must be this interpreter: tmp_path has no python-embed.
    env["PATH"] = path if path is not None else (
        str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""))
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat)], cwd=str(caller), env=env,
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
@pytest.mark.parametrize("how", ["module-missing", "no-interpreter"])
def test_a_check_that_cannot_run_changes_nothing(tmp_path, rel, how):
    # module-missing: Python exits 1, not 10 / 11 / 12. no-interpreter: no
    # python-embed and no python.exe on PATH, so the check never starts.
    system32 = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    rc, out, seen = _run(tmp_path, rel, "junk", _line(FILE_KEY),
                         with_module=how != "module-missing",
                         path=system32 if how == "no-interpreter" else None)
    if rel == "start.bat":
        assert rc == 1, out
        assert "Could not check the Anthropic API key" in out
        assert seen == []
        return
    assert rc == 0, out
    assert seen == [{ENV_VAR: "junk"}], "a failed check must leave the variable alone"


@win_only
@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_planted_python_in_the_callers_folder_never_runs(tmp_path, rel):
    # Verifier N1: python.bat / python.cmd planted in the folder the launcher
    # is started from (and in the root itself) must not be the interpreter.
    rc, out, seen = _run(tmp_path, rel, "junk", _line(FILE_KEY), plant=True)
    assert not list(tmp_path.rglob("planted.txt")), f"a planted python ran: {out!r}"
    assert rc == 0, out
    assert seen == [{}], "the real check clears the unusable inherited value"


@win_only
@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_quoted_python_folder_on_path_is_still_found(tmp_path, rel):
    # Third verifier: %%~$PATH:I finds nothing in a QUOTED PATH entry, so
    # with no python-embed start.bat said Python was missing and refused,
    # where 5edd5bd88 (a bare `python`) started. Windows accepts the form.
    system32 = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    quoted = f'"{Path(sys.executable).parent}";{system32}'
    rc, out, seen = _run(tmp_path, rel, "junk", _line(FILE_KEY), path=quoted)
    assert rc == 0, out
    assert seen == [{}], f"the check did not run: {out!r}"
    rc, out, seen = _run(tmp_path, rel, ENV_KEY, None, path=quoted, plant=True)
    assert rc == 0, out
    assert seen == [{ENV_VAR: ENV_KEY}]
    assert not list(tmp_path.rglob("planted.txt"))


def _restart_tool_lines() -> list[str]:
    """restart.bat's system-tool lines, made harmless: taskkill and wmic aim
    at names no process has, so only WHICH executable runs is observed."""
    lines = [ln.strip() for ln in _lines("scripts/restart.bat")]
    start = next(i for i, ln in enumerate(lines) if ln.startswith("echo [Amberstone] Restarting"))
    end = lines.index("setlocal", start)
    tools = [ln for ln in lines[start + 1:end] if ln]
    assert len(tools) == 3, tools
    safe = [ln.replace("'%%main.py%%'", "'%%rc810-no-such-process%%'")
              .replace("/IM pythonw.exe", "/IM rc810-no-such-image.exe") for ln in tools]
    for ln in safe:
        assert "main.py" not in ln and "pythonw" not in ln.lower(), ln
    return safe


@pytest.fixture(scope="module")
def fake_embed(tmp_path_factory) -> Path:
    """A venv of this interpreter: its Scripts\\python.exe (the venv
    launcher), copied with pyvenv.cfg, is a working python-embed\\python.exe."""
    ve = tmp_path_factory.mktemp("rm810-venv") / "ve"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(ve)], check=True,
                   capture_output=True, timeout=300,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return ve


def _install_embed(root: Path, ve: Path) -> None:
    emb = root / "python-embed"
    emb.mkdir(exist_ok=True)
    shutil.copyfile(ve / "Scripts" / "python.exe", emb / "python.exe")
    for where in (emb, root):
        shutil.copyfile(ve / "pyvenv.cfg", where / "pyvenv.cfg")


@win_only
@pytest.mark.parametrize("rel", LAUNCHERS)
@pytest.mark.parametrize("length", [8180, 9000])
@pytest.mark.parametrize("embed", [True, False], ids=["embed-present", "unquoted-path-hit"])
def test_a_long_path_never_aborts_the_check(tmp_path, fake_embed, rel, length, embed):
    # Fourth verifier: 870fe070a copied the whole PATH into one command line on
    # every run; at 8176-8191 characters cmd said "The input line is too long."
    # and aborted the batch (exit 255) even with python-embed present, and at
    # 8192+ the copy came out empty. With python-embed present the PATH here
    # holds no Python at all, so only the embedded interpreter can pass.
    pad = "C:\\Windows\\rc810-pad-"
    if embed:
        _install_embed(tmp_path, fake_embed)
        path = pad
    else:
        path = f"{Path(sys.executable).parent};{pad}"
    path += "y" * (length - len(path))
    assert len(path) == length
    rc, out, seen = _run(tmp_path, rel, "junk", _line(FILE_KEY), path=path)
    assert rc == 0, out
    assert seen == [{}], f"the check did not run: {out!r}"


@win_only
def test_restart_bat_system_tools_never_resolve_from_the_callers_folder(tmp_path):
    # Third verifier: restart.bat ran wmic / taskkill / timeout by bare name
    # before its cd, so a timeout.bat in the caller's folder ran. wmic is
    # pinned statically only (test above); taskkill and timeout run here.
    caller = tmp_path / "caller"
    caller.mkdir()
    for tool in ("wmic", "taskkill", "timeout"):
        for ext in (".bat", ".cmd"):
            (caller / f"{tool}{ext}").write_bytes(_PLANT)
    body = [ln for ln in _restart_tool_lines() if "wmic" not in ln.lower()]
    bat = tmp_path / "tools_harness.bat"
    bat.write_bytes(("\r\n".join(["@echo off", "setlocal"] + body + ["echo TOOLS=DONE"])
                     + "\r\n").encode("ascii"))
    env = {k: v for k, v in os.environ.items()
           if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}
    proc = subprocess.run(["cmd.exe", "/d", "/c", str(bat)], cwd=str(caller), env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("ascii", "replace")
    assert "TOOLS=DONE" in out, out
    assert not list(tmp_path.rglob("planted.txt")), f"a planted system tool ran: {out!r}"


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
