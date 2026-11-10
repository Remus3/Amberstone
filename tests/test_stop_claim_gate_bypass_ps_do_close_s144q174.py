"""S144-Q-174 (a): the `}` of a top-level `do` block is no statement start.

PowerShell needs a `while` or `until` right after a `do` block, so in
`do { } if (1) { echo a; echo b } until (git commit -n)` the `if` is no
statement: the script is a parse error (MissingWhileOrUntilInDoWhile) and
runs nothing. S144-Q-170's _ps_statement_start took the `}` of every "do"
block as a statement start (it excluded only "try"), so the `if` block
read as a statement block, the `until (..)` after it was broken out as a
loop condition, and the commit was counted as a hook bypass.

Shapes measured by cycle 227 (S144-Q-173, Windows PowerShell 5.1.19041,
`-File`, one script per shape, S = `cmd /c "copy nul <marker> >nul & echo
1"`, the marker checked after the run; quoted in the S144-Q-173 test held
in stash s144-leftover-s144q228-a3df7e). PARSE ERROR, nothing runs:
`do { } if ($x) { a; b } until (S)`, `do { } function f { a; b } until
(S)`, `do { } foreach ($i in 1) { a; b } until (S)`, `do { } try { } catch
{ a; b } until (S)`, `do { } do { a; b } until (S)`, `do { } while
($false) { a; b } until (S)` (UnexpectedToken: that `while` is the
do-loop condition, not a `while` statement), `do { a } | if ($x) { a; b }
until (S)`, `echo [a; do { } if ($x) { a; b } until (S) ]`. Each NOT_COUNTED
shape below was re-checked this cycle with PowerShell 5.1's own parser
(System.Management.Automation.Language.Parser.ParseInput): every one
reports a parse error.

Fix (slice (a) of the S144-Q-174 split, EXTRA only, count-only): a `do`
block is "top-do" when its `do` is CERTAINLY a do statement, and a
"top-do" block's `}` is no statement start (_ps_statement_start, beside
"try"). Every other `do` block keeps kind "do" and the S144-Q-170 reading.
Certainly a do statement (_ps_top_do), all three:
- the text is TRUSTED: the tool call's own command as written (_readings
  top=True: depth 0, no heredoc span cut, no continuation joined; never a
  launcher's unwrapped argument, which drops PowerShell's `''` escapes) and
  _ps_trusted: no `#`, backtick, `$`, backslash, `--%`, `@"` / `@'`, nor a
  character but printable ASCII, tab, LF and CR (the scan reads no comment,
  escape, stop-parsing token, here-string or expansion; cycle 227's
  verifier rounds 1 to 7);
- the `do` is in no bracket at all (CONTEXT empty), so a `$( )` the scan
  takes for a subexpression (`echo $$(do ..)`, `echo x@(do ..)`) and a
  scriptblock argument (`echo {a; do ..}`) are out;
- the `do` is first in the text, or right after a `;`, or first on a line
  whose previous non-blank character is a `)`, `}` or `;`, so `1 | do`,
  `x = do`, `x=do`, `}` + `do` on one line, and a `do` after a line ending
  in `|`, `,`, `=`, any other operator or a WORD are out. A word is out
  because a keyword that takes a name reads the `do` on the next line as
  that name (this cycle's verifier round 1, measured with PS 5.1 and pwsh
  7: `data` + line break + `do { } if (1) { a; b } until (S)` parses as a
  data statement, an `if` and an `until` command, and runs S; `function`
  ran S too; `filter`, `workflow`, `configuration`, `class`, `enum` parse
  clean the same way).
A narrower set than PowerShell's on purpose: a missed parse error stays
counted (the safe direction); a dropped count must be a parse error.

Not this slice (still counted though each runs nothing; filed remainder of
S144-Q-174): a do block with no condition before a `;` or a line break
(`do { a; b }; if (..) { a; b } until (S)`), a statement inside a do block
(`do { if (..) { a; b } until (S) }`), every untrusted or nested shape
above. Still missed (runs, not counted): `do { a } until ($true) if ($x) {
a; b } until (S)` (S144-Q-174 (c) family).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

C = "git commit -n"

# Each a PowerShell parse error (Parser.ParseInput, measured this cycle).
NOT_COUNTED = [
    f"do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"do {{ }} function f {{ echo a; echo b }} until ({C})",
    f"do {{ }} for (;;) {{ echo a; echo b }} until ({C})",
    f"do {{ }} foreach (i in 1) {{ echo a; echo b }} until ({C})",
    f"do {{ }} try {{ }} catch {{ echo a; echo b }} until ({C})",
    f"do {{ }} do {{ echo a; echo b }} until ({C})",
    f"do {{ }} while (0) {{ echo a; echo b }} until ({C})",
    f"do {{ }} if (1) {{ }} else {{ echo a; echo b }} until ({C})",
    f"echo a; do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo a;\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo a;\n\n  do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo a;\r\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo (1)\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo {{}}\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"\n\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo [a; do {{ }} if (1) {{ echo a; echo b }} until ({C}) ]",
    f"DO {{ }} IF (1) {{ echo a; echo b }} UNTIL ({C})",
]

# Each measured running the commit (cycle 227, PS 5.1), or a shape this
# slice must not read (untrusted, nested, not first in its statement);
# counted before the fix and after it.
KEPT = [
    f"do {{ echo a; echo b }} until ({C})",
    f"do {{ echo a; echo b }} while ({C})",
    f"do {{ do {{ echo a; echo b }} until ({C}) }} until (1)",
    f"do {{ echo a }}\nuntil ({C})",
    f"do {{ echo a; echo b }}\n\n  until ({C})",
    f"do {{ echo a }} until (1) ; if (1) {{ echo a; echo b }} until ({C})",
    f"do {{ echo a }} until (1)\nif (1) {{ echo a; echo b }} until ({C})",
    f"if (1) {{ }} if (2) {{ echo a; echo b }} until ({C})",
    f"if (1) {{ }} do {{ echo a; echo b }} until ({C})",
    # `do` a command or an argument word: after `|`, `=`, `,`, or a `}`
    f"1 | do {{ }} if ({C})",
    f"1 | do {{ echo a; echo b }} while ({C})",
    f"1 | do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"1 |\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo a,\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo x=do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo x =\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo x=do {{ }} do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo x=do {{ }} if (2) {{ }} do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    # a keyword that takes a name reads the `do` on the next line as it
    # (verifier round 1: `data` and `function` measured running S)
    f"data\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"DATA\r\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"data\n\n  do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"data\ndo {{ }} try {{ }} finally {{ echo a; echo b }} until ({C})",
    f"function\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"filter\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"workflow\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"configuration\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"class\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"enum\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo a\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    # a `do` the scan cannot read: comment, escape, expansion, stop-parsing
    f"#; do {{ a }}\ndo {{ echo a; echo b }} until ({C})",
    f"echo a`;do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo a `\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"echo $x\ndo {{ }} if (1) {{ echo a; echo b }} until ({C})",
    f"cmd /c echo --% ; do {{ }} if (1) {{ echo a; echo b }} until ({C})",
    # in a bracket
    f"echo $$(do {{ }} if (1) {{ echo a; echo b }} until ({C}))",
    f"echo x@(do {{ }} if (1) {{ echo a; echo b }} until ({C}))",
]

# Parse errors this slice leaves counted (the filed remainder): pinned so
# the slice is exactly as narrow as the docstring says. A later slice that
# drops one moves it to NOT_COUNTED.
STILL_COUNTED = [
    f"do {{ if (1) {{ echo a; echo b }} until ({C}) }}",
    f"do {{ echo a; echo b }}; if (2) {{ echo a; echo b }} until ({C})",
    f"do {{ echo a }}\n\nif (1) {{ echo a; echo b }} until ({C})",
    f"do {{ }} if ($x) {{ echo a; echo b }} until ({C})",
    f"powershell -Command 'do {{ }} if (1) {{ echo a; echo b }} until ({C})'",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_has_bypass_skips_a_statement_after_a_top_do_block(command):
    assert gate._has_bypass(command) is False


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_skips_a_statement_after_a_top_do_block(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_after_a_top_do_block(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


@pytest.mark.parametrize("command", KEPT + STILL_COUNTED)
def test_a_running_or_unread_shape_stays_counted(command, tmp_path):
    assert gate._has_bypass(command) is True
    assert "hook_bypass" in _audit_checks(command)
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED + KEPT + STILL_COUNTED)
def test_extra_false_is_untouched(command, tmp_path):
    """The fix is EXTRA only: the old rule and RM-698 never counted these."""
    assert gate._has_bypass(command, extra=False) is False
    assert gate._placed(command, tmp_path.as_posix(), {}, 0, extra=False) == []


@pytest.mark.parametrize(("masked", "k", "top"), [
    ("do { a }", 0, True),
    ("  do { a }", 2, True),
    ("echo a; do { a }", 8, True),
    ("echo a ;\tdo { a }", 9, True),
    ("echo a\ndo { a }", 7, False),
    ("echo a\n\n  do { a }", 10, False),
    ("data\ndo { a }", 5, False),
    ("function\ndo { a }", 9, False),
    ("x_\ndo { a }", 3, False),
    ("echo a;\n\n  do { a }", 11, True),
    ("\n\ndo { a }", 2, True),
    ("echo (1)\ndo { a }", 9, True),
    ("echo {}\ndo { a }", 8, True),
    ("echo a;\ndo { a }", 8, True),
    ("1 | do { a }", 4, False),
    ("1 |\ndo { a }", 4, False),
    ("x = do { a }", 4, False),
    ("x =\ndo { a }", 4, False),
    ("x=do { a }", 2, False),
    ("echo a,\ndo { a }", 8, False),
    ("echo a +\ndo { a }", 9, False),
    ("echo [a]\ndo { a }", 9, False),
    ("echo a &\ndo { a }", 9, False),
    ("if (1) { } do { a }", 11, False),
    ("x.do { a }", 2, False),
    ("echo a\r\ndo { a }", 8, False),
    ("echo a;\r\ndo { a }", 9, True),
])
def test_ps_top_do(masked, k, top):
    assert gate._ps_top_do(masked, k, []) is top


def test_ps_top_do_needs_the_top_level():
    assert gate._ps_top_do("do { a }", 0, [("(", True, 0)]) is False
    assert gate._ps_top_do("do { a }", 0, [("{", True, 0)]) is False


def test_ps_statement_start_skips_a_top_do_block_close():
    masked = "do { } if (1) { }"
    assert gate._ps_statement_start(masked, 7, {5: "top-do"}, []) is False
    assert gate._ps_statement_start(masked, 7, {5: "do"}, []) is True
    assert gate._ps_statement_start(masked, 7, {5: "if"}, []) is True
    assert gate._ps_statement_start(masked, 7, {5: "try"}, []) is False


def test_loop_block_closes_names_a_top_do_only_when_trusted():
    assert gate._ps_loop_block_closes("do { a }") == {7: "do"}
    assert gate._ps_loop_block_closes("do { a }", trusted=False) == {7: "do"}
    assert gate._ps_loop_block_closes("do { a }", trusted=True) == {7: "top-do"}
    assert gate._ps_loop_block_closes("1 | do { a }", trusted=True) == {11: "do"}
    assert gate._ps_loop_block_closes("$(do { a })", trusted=True) == {9: "do"}
    text = "do { } if (1) { a }"
    assert gate._ps_loop_block_closes(text, trusted=True) == {5: "top-do"}
    assert gate._ps_loop_block_closes(text) == {5: "do", 18: "if"}


def test_brace_broken_reads_a_top_do_only_when_trusted():
    text = f"do {{ }} if (1) {{ echo a; echo b }} until ({C})"
    assert gate._brace_broken(text, trusted=True) == text
    assert gate._brace_broken(text) != text  # the S144-Q-170 reading
    loop = f"do {{ echo a; echo b }} until ({C})"
    assert gate._brace_broken(loop, trusted=True) == gate._brace_broken(loop)
    assert gate._brace_broken(loop, trusted=True) != loop
    cond = f"do {{ echo a }} while ({C})"
    assert gate._brace_broken(cond, trusted=True) == gate._brace_broken(cond)
    assert gate._brace_broken(cond, trusted=True) != cond


def test_brace_broken_untrusted_text_keeps_the_old_reading():
    text = f"echo $x; do {{ }} if (1) {{ echo a; echo b }} until ({C})"
    assert gate._brace_broken(text, trusted=True) == gate._brace_broken(text)
    assert gate._brace_broken(text) != text


def test_readings_trust_only_the_top_command_as_written():
    text = f"do {{ }} if (1) {{ echo a; echo b }} until ({C})"
    assert gate._readings(text, True, top=True) == [text]
    assert gate._readings(text, True) == [text, gate._brace_broken(text)]
    assert gate._readings(text, True, top=False) == gate._readings(text, True)


def test_readings_do_not_trust_a_heredoc_cut():
    """A cut heredoc span is no longer the command as written."""
    command = f"cat <<EOF\nz\nEOF\necho a; do {{ }} if (1) {{ echo a; echo b }} until ({C})"
    raw = "cat  \n" + command.split("EOF\n", 2)[2]
    assert gate._readings(command, True, top=True) == [raw, gate._brace_broken(raw)]
    assert gate._brace_broken(raw) != gate._brace_broken(raw, trusted=True)
