"""Guard: every scheduled-task command embedded in a module docstring is
well-formed for the shell it asks the operator to paste it into.

WHY
---
RM-404. RC ships copy-paste scheduled-task registration commands inside module
docstrings (``tools/screen_agent.py``, ``tools/keybind_listener.py``, ...) for
an operator to run by hand. No test had ever executed or parsed one, and four
of the five continued across lines with a **cmd.exe caret** (``^``).

PowerShell does not continue on a caret - it continues on a BACKTICK. MEASURED
2026-09-11 with ``[System.Management.Automation.Language.Parser]::ParseInput``
under Windows PowerShell 5.1: a caret-continued block reports **zero parse
errors** and splits into **two** top-level statements - ``schtasks /Create ...``
without its ``/TR`` payload, then a second bogus command named ``/TR``. The
failure is therefore SILENT at parse time, which is exactly why reading the
text never caught it. Four of the five blocks also interpolated
``$env:LOCALAPPDATA``, which is PowerShell-only syntax, so those blocks could
not be re-labelled as cmd.exe-only either - they were PowerShell-targeted and
PowerShell-broken.

The repair was NOT to hand-fix the caret escaping. ``Register-ScheduledTask``
takes the executable and its arguments as separate parameters, so the
quoting/continuation question does not arise; that is the form the docstrings
now carry.

WHAT IS ASSERTED
----------------
1. No embedded block continues a line with a cmd.exe caret outside a quoted
   string (pure Python, never skipped).
2. Every embedded block parses under the real PowerShell parser with zero
   errors AND exactly one top-level statement - i.e. it is ONE command, not
   two (gated on a PowerShell interpreter being present; SKIPPED by name when
   it is not, never ERRORed).

Nothing here RUNS a command. Registering a scheduled task is an operator act;
this guard only parses text.

ANTI-VACUITY
------------
A silently-empty extractor would make every assertion above pass forever, so
the extractor is pinned in both directions:

* POSITIVE CONTROL - ``test_the_extractor_finds_the_known_embedded_task_command
  _sites`` asserts it reaches the real, named modules in the real tree, on top
  of ``tests/_repo_walk.self_check`` (ADR-015) proving the walk itself is not
  empty.
* NEGATIVE CONTROL - ``test_the_caret_continuation_detector_fires_on_a_known
  _bad_block`` feeds a synthetic caret-continued command to the same detector
  and asserts it is flagged, proving arm 1 can still fail.

Together these keep CHECKED-AND-FOUND-NOTHING distinguishable from
COULD-NOT-CHECK: arm 1 always runs, arm 2 skips with the missing interpreter
named, and the controls prove the corpus is non-empty either way.

ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests import _repo_walk

_REPO_ROOT = Path(__file__).resolve().parents[1]

# A scheduled-task REGISTRATION command. Two deliberate narrowings:
#
#   * ``schtasks /Run`` (ops/rc_supervisor) is out of scope - it is issued by
#     code, not pasted by a human, and tests/test_rc_supervisor_phase3_watcher
#     already covers it.
#   * the command must NAME its task on the same line (``/TN`` or
#     ``-TaskName``). MEASURED 2026-09-11: without that lookahead the extractor
#     also swept up ordinary PROSE mentioning the cmdlets - the repair notes in
#     these very docstrings - and graded English sentences as if they were
#     commands, taking the corpus from 5 real blocks to 11. A registration
#     command always names its task; a sentence about one does not.
_TASK_CMD = re.compile(
    r"schtasks\s+/Create\b(?=.*\s/TN\b)|Register-ScheduledTask\b(?=.*\s-TaskName\b)",
    re.IGNORECASE,
)
_TASK_NAME = re.compile(r"(?:/TN|-TaskName)\s+\"([^\"]+)\"", re.IGNORECASE)

# Every task RC asks an operator to register from a docstring, by name. Names
# survive line moves and reformatting, so this pins the corpus semantically
# rather than by a line number or a raw count. Adding a sixth paste-me task is
# expected to add its name here; prose can never satisfy it.
_KNOWN_TASKS = frozenset({
    "RC-DS-MatchDB-MCP",
    "RC-KeybindListener",
    "RC-LiveClientRelay",
    "RC-ScreenAgent-League",
    "RC-ScreenAgent-UI",
})
_KNOWN_SITES = (
    "tools/ds_matchdb_mcp_server.py",
    "tools/keybind_listener.py",
    "tools/liveclient_relay.py",
    "tools/screen_agent.py",
)


@dataclass(frozen=True)
class _Block:
    """One embedded command, as an operator would paste it."""

    relpath: str
    line: int  # 1-based line in the FILE, not in the docstring
    text: str

    @property
    def ident(self) -> str:
        return f"{self.relpath}:{self.line}"

    @property
    def task_name(self) -> str:
        match = _TASK_NAME.search(self.text)
        return match.group(1) if match else ""


def _trailing_continuation(line: str) -> str:
    """Return the line's trailing shell continuation char, or ``""``.

    Quote-aware: a caret INSIDE a quoted string is a literal caret and is not a
    continuation, which is the trap this whole guard exists to avoid tripping
    over. Quote tracking is deliberately simple (no backslash escapes) because
    the corpus is short operator-facing text, not arbitrary script.
    """
    stripped = line.rstrip()
    if not stripped or stripped[-1] not in "^`":
        return ""
    in_single = in_double = False
    for char in stripped:
        if char == '"' and not in_single:
            in_double = not in_double
        elif char == "'" and not in_double:
            in_single = not in_single
    if in_single or in_double:
        # The trailing char never closed its string, so it sits inside one.
        return ""
    return stripped[-1]


def _blocks_in_docstring(doc: str, relpath: str, doc_lineno: int) -> list[_Block]:
    """Every task command in ``doc``, joined across its continuation lines."""
    lines = doc.splitlines()
    found: list[_Block] = []
    index = 0
    while index < len(lines):
        match = _TASK_CMD.search(lines[index])
        if match is None:
            index += 1
            continue
        start = index
        # Drop any prose lead-in ("3. (optional task) schtasks /Create ...").
        chunk = [lines[index][match.start():]]
        while _trailing_continuation(chunk[-1]) and index + 1 < len(lines):
            index += 1
            chunk.append(lines[index])
        found.append(
            _Block(
                relpath=relpath,
                line=doc_lineno + start,
                # Continuation lines are indented for readability inside the
                # docstring; strip that indent so the parser sees paste-shape.
                text="\n".join([chunk[0]] + [c.strip() for c in chunk[1:]]),
            )
        )
        index += 1
    return found


def _embedded_task_commands() -> list[_Block]:
    """Every paste-me scheduled-task command in a tracked module docstring."""
    _repo_walk.self_check(_REPO_ROOT)
    blocks: list[_Block] = []
    for path in _repo_walk.repo_files(_REPO_ROOT, ("*.py",)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        doc = ast.get_docstring(tree, clean=False)
        if not doc or not _TASK_CMD.search(doc):
            continue
        blocks.extend(
            _blocks_in_docstring(
                doc,
                _repo_walk.relative_posix(path, _REPO_ROOT),
                tree.body[0].lineno,
            )
        )
    return blocks


_PS_PARSE_SCRIPT = """param([string]$Json)
$sites = Get-Content -Raw -LiteralPath $Json | ConvertFrom-Json
$out = @()
foreach ($s in $sites) {
    $errors = $null
    $tokens = $null
    $parsed = [System.Management.Automation.Language.Parser]::ParseInput(
        $s.text, [ref]$tokens, [ref]$errors)
    $out += [pscustomobject]@{
        ident = $s.ident
        errors = @($errors).Count
        statements = @($parsed.EndBlock.Statements).Count
        messages = @(@($errors) | ForEach-Object { $_.Message })
    }
}
[pscustomobject]@{ results = @($out) } | ConvertTo-Json -Depth 6
"""


def _powershell() -> str | None:
    """Windows PowerShell 5.1 for preference - it is the documented target."""
    return shutil.which("powershell") or shutil.which("pwsh")


def _powershell_parse(blocks: list[_Block], tmp_path: Path) -> dict[str, dict]:
    """Parse each block with the REAL PowerShell parser. Never executes it."""
    exe = _powershell()
    assert exe is not None, "caller must gate on _powershell()"
    payload = tmp_path / "blocks.json"
    payload.write_text(
        json.dumps([{"ident": b.ident, "text": b.text} for b in blocks]),
        encoding="utf-8",
    )
    script = tmp_path / "parse.ps1"
    script.write_text(_PS_PARSE_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), "-Json", str(payload)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"PowerShell parse probe failed (rc={proc.returncode}): {proc.stderr}"
    )
    results = json.loads(proc.stdout)["results"]
    if isinstance(results, dict):  # ConvertTo-Json collapses a 1-element array
        results = [results]
    return {row["ident"]: row for row in results}


def test_the_extractor_finds_the_known_embedded_task_command_sites() -> None:
    """ANTI-VACUITY: a silently-empty extractor passes every other assertion."""
    blocks = _embedded_task_commands()
    assert blocks, (
        "extracted ZERO embedded scheduled-task commands from the tree. That "
        "makes every other assertion in this module vacuous - fix the "
        "extractor, do not relax it."
    )
    modules = {b.relpath for b in blocks}
    missing = [site for site in _KNOWN_SITES if site not in modules]
    assert not missing, (
        f"extractor no longer reaches known task-command sites {missing}. "
        f"It found {sorted(modules)}. Either the docstrings moved or the "
        "extractor regressed."
    )
    found_tasks = {b.task_name for b in blocks}
    assert found_tasks == _KNOWN_TASKS, (
        "the extracted corpus is not the known set of paste-me tasks.\n"
        f"  missing: {sorted(_KNOWN_TASKS - found_tasks)}\n"
        f"  unexpected: {sorted(found_tasks - _KNOWN_TASKS)}\n"
        "An empty string among the unexpected means a block matched with no "
        "task name - almost always PROSE swept in by a too-loose pattern, "
        "which would grade English sentences as commands."
    )
    assert len(blocks) == len(_KNOWN_TASKS), (
        f"expected one block per known task ({len(_KNOWN_TASKS)}), got "
        f"{len(blocks)}: {[b.ident for b in blocks]}"
    )


def test_the_caret_continuation_detector_fires_on_a_known_bad_block() -> None:
    """ANTI-VACUITY: the detector must still be able to FAIL."""
    bad = 'schtasks /Create /TN "X" /SC ONLOGON /F ^'
    assert _trailing_continuation(bad) == "^", (
        "the caret detector no longer flags a caret-continued line; arm 1 "
        "would pass for every input"
    )
    # ...and the quoted-caret trap must NOT be flagged.
    quoted = 'schtasks /Create /TN "X" /TR "run.exe --glyph ^'
    assert _trailing_continuation(quoted) == "", (
        "a caret inside an unterminated quoted string is literal, not a "
        "continuation; flagging it would produce a false MUST-FIX"
    )
    assert _trailing_continuation("Register-ScheduledTask -TaskName `") == "`"
    assert _trailing_continuation("Register-ScheduledTask -TaskName X") == ""


def test_prose_mentioning_the_cmdlets_is_not_graded_as_a_command() -> None:
    """The discriminator that keeps the corpus honest, pinned directly.

    MEASURED 2026-09-11: a pattern without the task-name lookahead extracted
    11 blocks from 5 real commands, the extra 6 being the repair notes written
    into those same docstrings. Sweeping prose into a command corpus is how a
    guard ends up reporting on itself.
    """
    prose = (
        "RM-404: this was a caret-continued `schtasks /Create`, which\n"
        "PowerShell splits into two commands. Register-ScheduledTask takes\n"
        "the executable and its arguments as SEPARATE parameters.\n"
    )
    assert _blocks_in_docstring(prose, "fake.py", 1) == []

    real = 'Register-ScheduledTask -TaskName "RC-Example" -Force\n'
    extracted = _blocks_in_docstring(real, "fake.py", 1)
    assert len(extracted) == 1, "the tightened pattern must still find a real command"
    assert extracted[0].task_name == "RC-Example"


def test_no_embedded_task_command_continues_a_line_with_a_cmd_caret() -> None:
    """PowerShell continues on a backtick; a caret silently ends the command."""
    offenders = []
    for block in _embedded_task_commands():
        for line in block.text.splitlines():
            if _trailing_continuation(line) == "^":
                offenders.append(f"{block.ident}: {line.strip()}")
    assert not offenders, (
        "cmd.exe caret continuation in a paste-me scheduled-task command "
        "(RM-404). PowerShell continues on a BACKTICK, so each of these "
        "parses as two commands with ZERO parse errors - the /TR payload is "
        "silently dropped. Emit a single-statement Register-ScheduledTask "
        "form instead of escaping the caret:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.skipif(
    _powershell() is None,
    reason="COULD-NOT-CHECK: no PowerShell interpreter on PATH "
    "(looked for 'powershell' then 'pwsh'); this arm parses command text with "
    "the real PowerShell parser and has no honest pure-Python substitute",
)
def test_every_embedded_task_command_parses_as_exactly_one_powershell_command(
    tmp_path: Path,
) -> None:
    """Parsed, never run - registering a task stays an operator act."""
    blocks = _embedded_task_commands()
    assert blocks, "anti-vacuity: nothing to parse"
    parsed = _powershell_parse(blocks, tmp_path)
    offenders = []
    for block in blocks:
        row = parsed.get(block.ident)
        if row is None:
            offenders.append(f"{block.ident}: PowerShell returned no verdict")
            continue
        if row["errors"]:
            offenders.append(f"{block.ident}: {row['errors']} parse error(s): "
                             f"{row['messages']}")
        elif row["statements"] != 1:
            offenders.append(
                f"{block.ident}: parses as {row['statements']} top-level "
                "statements, not 1 - the operator would run a truncated "
                "command followed by a bogus one"
            )
    assert not offenders, (
        "embedded scheduled-task command is not a single well-formed "
        "PowerShell command (RM-404):\n  " + "\n  ".join(offenders)
    )
