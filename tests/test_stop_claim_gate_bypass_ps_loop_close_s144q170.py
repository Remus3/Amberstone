"""S144-Q-170: a statement break inside a block hid the `while` / `until`
condition after it.

`do { echo a; echo b } until (git commit -n)` runs the commit, but
_STATEMENT_BREAK splits at the `;` (and at a `|`), so the condition sat in
the statement `echo b } until (..)`, which opens with a command, and the
S144-Q-164 / S144-Q-165 condition scan never reached it. The same held for
a block with no break at all (`do { echo a } until (..)`): the scan stops
at the first word of the block.

Measured with Windows PowerShell 5.1.19041 (`-File`, one script per shape,
S = `cmd /c "copy nul <marker> >nul & echo 1"` for `until` and the same
without the echo for `while`, so each loop ends; the marker checked after
the run). RUNS - `do { echo a; echo b } until (S)` and `while (S)`,
`do { echo a | Out-Null } until (S)` and `while (S)`,
`do { if ($x) { echo a; echo b } } until (S)`, `until ($(S))`,
`until ($x -eq (S))`, `}until(S)`, `Do { .. } UNTIL (S)`,
`do { echo a } until (S)`, `do { echo '}'; echo b } until (S)`,
`do { .. } until (S) ; echo c`, `do { do { .. } until (S) } until ($true)`,
`$(do { .. } until (S))`, `@(..)`, `$x = do ..`, `1 | do ..`,
`$(if ($x) { .. } until (S))`, `@(foreach (..) { .. } until (S))`,
`echo a; do ..`, `if ($x) { } do { .. } until (S)`; and after a block that
is no loop body (a `while` statement follows it, or a bare `until (S)`
command whose argument runs, S144-Q-169): `if ($true) { .. } until (S)`,
`if ($x) { } else { .. } until (S)`, `foreach (..) { .. } until (S)`,
`for (..;..;..) { .. } until (S)`, `while ($false) { .. } until (S)`,
`function f-g { .. } until (S)`, `FUNCTION F { .. } UNTIL (S)`,
`try { } catch { .. } until (S)`, `try { } catch [System.Exception] { .. }
until (S)`, `try { } finally { .. } until (S)`. Does NOT run (a parse
error, so the script runs nothing): a scriptblock or hash VALUE before the
keyword - `{ .. } until (S)`, `$x = { .. } until (S)`, `@{..} until (S)`,
`Write-Output ({ .. } until (S))`, `do { { .. } until (S) } until ($true)`,
`{ z } do { .. } until (S)`, and (the verifier's round 1, each measured)
`-not {..}`, `! {..}`, `, {..}`, `1 + {..}`, `1 -and {..}`, `[void] {..}`,
`[scriptblock] {..}`, `return {..}`, `throw {..}`, `exit {..}`,
`begin {..}`, `param() {..}`, `data {..}`, `${x} = {..}`,
`[int]$x = {..}`, `$x = [scriptblock]{..}`, `$x = 1 + {..}`,
`$x = -not {..}`, `$x = ,{..}`, `$x = (1) + {..}`, `$x = $y = {..}`,
`$x, $y = {..}`, `switch (1) { a; b } until (S)`, `do [a] { .. } until
(S)`, `function f [a] { .. } until (S)`; also
`try { .. } until (S)` (a try needs its catch) and `function { .. } until
(S)` (no name); nor a string condition or a quoted `}`. The verifier's
round 2 (each measured running nothing): a body-less `while (S)` after a
block other than `do` (`if ($true) { .. } while (S)`: a `while` statement
needs its `{ }`), `catch [A] [B] {`, a second untyped catch, a head word
in a hash literal, a class / enum / switch body, a method's or a param
list's parentheses, `||` (no such operator in PS 5.1), unbalanced
brackets and a backtick-escaped `}`.

Fix (EXTRA only, count-only): _brace_broken also breaks before a `}` that
a `while` / `until` and its `(` follow (_PS_LOOP_CLOSE), so the condition
opens its own statement (`} until (..)`, read since S144-Q-169), when the
block that `}` closes is a statement block _ps_block_kind knows (`do`,
`if` / `elseif` / `while` / `foreach` / `for (..)`, `else`, `catch` with
at most one `[Type]` and only after the try, `finally`, `function` /
`filter NAME`; not `try`), opened where PowerShell reads that statement
(_ps_statement_start: at the top level, in a `$( )` / `@( )` or a
statement block, or right after the block it belongs to), and a body-less
`while` follows only a `do` block. Text whose brackets do not balance
gets no break. A positive list: the verifier's round 1 refuted a list of
value positions, which missed 23 expression positions. The raw reading
stays and is walked first.

Still missed (measured running; filed S144-Q-172): a block that is a
command ARGUMENT - `echo { a; b } until (S)`, `echo @{a=1; b=2} until
(S)`, `1 | % { a; b } while (S)`, `echo do { a; b } until (S)`, a head
word PowerShell reads as a command (`else { a; b } until (S)` first in
a script, `if ($x) { }; else { .. } until (S)`), a switch clause block
(`switch (1) { 1 { a; b } } until (S)`), a `while` statement after a
block other than `do` (`if ($true) { a; b } while (S) { }`, `foreach`,
`function f`, `filter f`), `(do { a; b } until (S))`, a catch after a
typed catch, and a block inside an invoked scriptblock
(`& { a; do { b; c } until (S) }`).
"""
from __future__ import annotations

import time

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "do { echo a; echo b } until (git commit -n)",
    "do { echo a; echo b } while (git commit -n)",
    "do { echo a | Out-Null } until (git commit -n)",
    "do { echo a | Out-Null } while (git commit -n)",
    "do { if ($x) { echo a; echo b } } until (git commit -n)",
    "do { echo a; echo b } until ($(git commit -n))",
    "do { echo a; echo b } until ($x -eq (git commit -n))",
    "do { echo a; echo b }until(git commit -n)",
    "Do { echo a; echo b } UNTIL (git commit -n)",
    "do { echo a } until (git commit -n)",
    "do { echo '}'; echo b } until (git commit -n)",
    "do { echo a; echo b } until (git commit -n) ; echo c",
    "if ($true) { echo a; echo b } until (git commit -n)",
    "while ($false) { echo a; echo b } until (git commit -n)",
    "do { do { echo a; echo b } until (git commit -n) } until ($true)",
    "$(do { echo a; echo b } until (git commit -n))",
    "@(do { echo a; echo b } until (git commit -n))",
    "$(if ($x) { echo a; echo b } until (git commit -n))",
    "@(foreach ($i in 1) { echo a; echo b } until (git commit -n))",
    "$x = do { echo a; echo b } until (git commit -n)",
    "1 | do { echo a; echo b } until (git commit -n)",
    "echo a; do { echo a; echo b } until (git commit -n)",
    "echo a\ndo { echo a; echo b } until (git commit -n)",
    "if ($x) { } do { echo a; echo b } until (git commit -n)",
    "if ($x) { } else { echo a; echo b } until (git commit -n)",
    "for ($i=0; $i -lt 1; $i++) { echo a; echo b } until (git commit -n)",
    "foreach ($i in 1) { echo a; echo b } until (git commit -n)",
    "function f-g { echo a; echo b } until (git commit -n)",
    "filter f { echo a; echo b } until (git commit -n)",
    "if ($true) { echo a; echo b } until (git commit -n)\n",
    "do { echo a; echo b } while (git commit -n)\n",
    "try { } catch { } finally { echo a; echo b } until (git commit -n)",
    "FUNCTION F { echo a; echo b } UNTIL (git commit -n)",
    "try { } catch { echo a; echo b } until (git commit -n)",
    "try { } catch [System.Exception] { echo a; echo b } until (git commit -n)",
    "try { } finally { echo a; echo b } until (git commit -n)",
    "do { echo a; echo b } until (bash -c 'git commit -n')",
]
# HEAD already counts these; the fix must not lose them.
KEPT = [
    "do { } until (git commit -n)",
    "do { echo a; } until (git commit -n)",
    "do { } while (git commit -n)",
    "} until (git commit -n)",
    "} while (git commit -n)",
    "if ($x) { echo a; echo b } elseif ((git commit -n)) { }",
    "if ($x) { echo a; echo b } else { git commit -n }",
    "try { echo a; echo b } finally { } while (git commit -n) { }",
]
NOT_COUNTED = [
    "{ echo a; echo b } until (git commit -n)",
    "{ echo a } until (git commit -n)",
    "$x = { echo a; echo b } until (git commit -n)",
    "@{a=1; b=2} until (git commit -n)",
    "do { { echo a; echo b } until (git commit -n) } until ($true)",
    "do [a] { echo a; echo b } until (git commit -n)",
    "function f [a] { echo a; echo b } until (git commit -n)",
    # the verifier's round 2, each measured running nothing
    "if ($true) { echo a; echo b } while (git commit -n)",
    "if ($true) { echo a } while (git commit -n)",
    "foreach ($i in 1) { echo a; echo b } while (git commit -n)",
    "function f { echo a; echo b } while (git commit -n)",
    "try { } catch { echo a; echo b } while (git commit -n)",
    "do { if ($x) { echo a; echo b } while (git commit -n) } until ($true)",
    "try { } catch [A] [B] { echo a; echo b } until (git commit -n)",
    "try { } catch { } catch { echo a; echo b } until (git commit -n)",
    "$x = @{ a = 1; do { echo a; echo b } until (git commit -n) }",
    "@{ a = 1; if ($true) { echo a; echo b } until (git commit -n) }",
    "class C {\ndo { echo a; echo b } until (git commit -n)\n}",
    "enum E {\ndo { echo a; echo b } until (git commit -n)\n}",
    "switch (1) {\ndo { echo a; echo b } until (git commit -n)\n}",
    "echo 1 || do { echo a; echo b } until (git commit -n)",
    "$s.Equals(do { echo a; echo b } until (git commit -n))",
    "param($p = do { echo a; echo b } until (git commit -n))",
    "function f(do { echo a; echo b } until (git commit -n)) { }",
    "$(do { echo a; echo b } until (git commit -n)",
    "@(do { echo a; echo b } until (git commit -n)",
    "do { echo a; echo b } until (git commit -n) )",
    "do { echo a; echo b } until (git commit -n) {",
    "do { echo a; echo b `} until (git commit -n)",
    "-not { echo a; echo b } until (git commit -n)",
    "! { echo a; echo b } until (git commit -n)",
    ", { echo a; echo b } until (git commit -n)",
    "1 + { echo a; echo b } until (git commit -n)",
    "1 -and { echo a; echo b } until (git commit -n)",
    "[void] { echo a; echo b } until (git commit -n)",
    "[scriptblock] { echo a; echo b } until (git commit -n)",
    "return { echo a; echo b } until (git commit -n)",
    "throw { echo a; echo b } until (git commit -n)",
    "exit { echo a; echo b } until (git commit -n)",
    "begin { echo a; echo b } until (git commit -n)",
    "param() { echo a; echo b } until (git commit -n)",
    "data { echo a; echo b } until (git commit -n)",
    "${x} = { echo a; echo b } until (git commit -n)",
    "[int]$x = { echo a; echo b } until (git commit -n)",
    "$x = [scriptblock]{ echo a; echo b } until (git commit -n)",
    "$x = 1 + { echo a; echo b } until (git commit -n)",
    "$x = -not { echo a; echo b } until (git commit -n)",
    "$x = ,{ echo a; echo b } until (git commit -n)",
    "$x = (1) + { echo a; echo b } until (git commit -n)",
    "$x = $y = { echo a; echo b } until (git commit -n)",
    "$x, $y = { echo a; echo b } until (git commit -n)",
    "{ echo z } { echo a; echo b } until (git commit -n)",
    "switch (1) { echo a; echo b } until (git commit -n)",
    "try { echo a; echo b } until (git commit -n)",
    "function { echo a; echo b } until (git commit -n)",
    "{ z } do { echo a; echo b } until (git commit -n)",
    "Write-Output ({ echo a; echo b } until (git commit -n))",
    "do { echo a; echo b } until ('git commit -n')",
    "do { echo a; echo b } until (git log -n 3)",
    "echo 'a; b } until (git commit -n)'",
    "do { echo a; echo b } until (",
    "do { echo a; echo b } while",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="powershell"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


@pytest.mark.parametrize("command", COUNTED)
def test_the_old_rule_and_rm698_missed_the_shape(command, tmp_path):
    """Each shape is new, and extra=False still does not count or place it."""
    assert not gate._bypass_in_text(command)
    assert gate._has_bypass(command, extra=False) is False
    assert gate._placed(command, tmp_path.as_posix(), {}, 0, extra=False) == []


@pytest.mark.parametrize("command", COUNTED)
def test_has_bypass_counts_a_condition_after_a_broken_block(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_a_condition_after_a_broken_block(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_a_condition_after_a_broken_block(command):
    assert _noted(command) == [command]
    assert _noted(command, name="bash") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_a_condition_after_a_broken_block(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", KEPT)
def test_a_head_count_is_kept(command, tmp_path):
    assert gate._has_bypass(command) is True
    assert "hook_bypass" in _audit_checks(command)
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_has_bypass_does_not_count_a_twin(command):
    assert gate._has_bypass(command) is False


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_a_twin(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_for_a_twin(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_the_condition_is_placed_from_here(tmp_path):
    here = tmp_path.as_posix()
    (tmp_path / "sub").mkdir()

    def placed(command):
        return set(gate._bypass_targets(command, here))

    plain = placed("git commit -n")
    assert None not in plain
    assert placed("do { echo a; echo b } until (git commit -n)") == plain
    moved = placed("cd sub; git commit -n")
    assert None not in moved and moved != plain
    assert placed("cd sub; do { echo a; echo b } until (git commit -n)") == moved


@pytest.mark.parametrize(("text", "broken"), [
    ("do { a; b } until (c)", "do { a; b \n} until (c)"),
    ("do { a } while (c)", "do { a \n} while (c)"),
    ("do { a }until(c)", "do { a \n}until(c)"),
    ("do { a } While (c)", "do { a \n} While (c)"),
    ("do { if ($x) { a; b } } until (c)", "do { if ($x) { a; b } \n} until (c)"),
    ("x = do { a } until (c)", "x = do { a \n} until (c)"),
    ("if ($x) { } else { a } until (c)", "if ($x) { \n} else { a \n} until (c)"),
    ("try { } catch [A] { a } until (c)",
     "try { \n} catch [A] { a \n} until (c)"),
    ("if ($x) { a } until (c)", "if ($x) { a \n} until (c)"),
    # already at a statement start, quoted, or no `(` after the keyword
    ("do { a; } until (c)", "do { a; } until (c)"),
    ("echo '} until (c)'", "echo '} until (c)'"),
    ("do { a } until", "do { a } until"),
    ("do { a } untilx (c)", "do { a } untilx (c)"),
    # a scriptblock or hash value, a command argument or a try block
    # before the keyword: left alone
    ("echo { a } until (c)", "echo { a } until (c)"),
    ("echo @{a=1} until (c)", "echo @{a=1} until (c)"),
    ("try { a } until (c)", "try { a } until (c)"),
    ("try { } do { a } until (c)", "try { } do { a } until (c)"),
    ("-not { a } until (c)", "-not { a } until (c)"),
    # a `while` after a block other than `do` needs its own body
    ("if ($x) { a } while (c)", "if ($x) { a } while (c)"),
    ("if ($x) { a } while (c) { }", "if ($x) { a } while (c) { }"),
    # unbalanced brackets, or an escaped `}`: a parse error
    ("$(do { a } until (c)", "$(do { a } until (c)"),
    ("do { a } until (c) )", "do { a } until (c) )"),
    ("do { a `} until (c)", "do { a `} until (c)"),
    ("{ a } until (c)", "{ a } until (c)"),
    ("$x = { a } until (c)", "$x = { a } until (c)"),
    ("$x += @{a=1} until (c)", "$x += @{a=1} until (c)"),
    ("@{a=1} until (c)", "@{a=1} until (c)"),
    ("(@{a=1} until (c))", "(@{a=1} until (c))"),
    ("a; { b } until (c)", "a; { b } until (c)"),
    ("do { { a } until (c) } until (d)", "do { { a } until (c) \n} until (d)"),
    # the S144-Q-158 block keywords are broken as before
    ("if ($x) { a } else { b }", "if ($x) { a \n} else { b }"),
    ("do { a } until (c); if ($x) { a } else { b }",
     "do { a \n} until (c); if ($x) { a \n} else { b }"),
])
def test_brace_broken_breaks_before_a_loop_condition(text, broken):
    assert gate._brace_broken(text) == broken


@pytest.mark.parametrize(("masked", "nth"), [
    ("do { a }", [0]),
    ("if ($x) { a }", [0]),
    ("if ($x) { } elseif ($y) { a } else { b }", [0, 1, 2]),
    ("for ($i=0; $i -lt 1; $i++) { a }", [0]),
    ("function f { a }", [0]),
    ("filter f-g { a }", [0]),
    ("try { } catch { a } finally { b }", [1, 2]),
    ("try { } catch [B[C]] { a }", [1]),
    ("try { } catch [A] [B] { a }", []),
    ("try { } catch { } catch { a }", [1]),
    ("1 | do { a }", [0]),
    ("do { a `} }", [1]),
    ("if ($x) {\n} else {\n}", [0, 1]),
    ("$(do { a })", [0]),
    ("$(if ($x) { a })", [0]),
    ("@(foreach ($i in 1) { a })", [0]),
    ("x = do { a }", [0]),
    ("do { do { a } }", [0, 1]),
    ("if ($x) { } do { a }", [0, 1]),
    ("{ a }", []),
    ("$x = { a }", []),
    ("echo { a }", []),
    ("try { a }", []),
    ("try { } do { a }", []),
    ("{ do { a } }", []),
    ("catch [A] { a }", []),
    ("do [a] { b }", []),
    ("function f [a] { b }", []),
    ("[void] { a }", []),
    ("; else { a }", []),
    ("switch (1) { a }", []),
    ("function { a }", []),
    ("${x} = { a }", []),
    ("echo do { a }", []),
    ("}", []),
    ("do { a", []),
    ("$(do { a }", []),
    ("do { a } )", []),
    ("do { a `}", []),
    ("do { ( } )", []),
    ("(do { a })", []),
    ("$s.Equals(do { a })", []),
    ("echo 1 || do { a }", []),
    ("@{ a = 1; do { b } }", []),
    ("class C {\ndo { a }\n}", []),
    ("switch (1) {\ndo { a }\n}", []),
    ("$x = { a; do { b } }", []),
])
def test_ps_loop_block_closes(masked, nth):
    braces = [i for i, char in enumerate(masked) if char == "}"]
    assert set(gate._ps_loop_block_closes(masked)) == {braces[n] for n in nth}


def test_ps_loop_block_closes_names_the_kind():
    """Only a "do" block takes a body-less `while (..)` (_brace_broken)."""
    assert gate._ps_loop_block_closes("do { a }") == {7: "do"}
    assert gate._ps_loop_block_closes("if ($x) { a }") == {12: "if"}
    assert gate._ps_loop_block_closes("try { } catch { a }") == {18: "catch"}


def test_the_break_is_linear_on_a_long_input():
    """One forward pass: a long run of loops, nested blocks, long gaps,
    words and bracket chains before a `{` stays well under a second each."""
    for text in ("do { a } until (b) " * 1000,
                 "{" * 10000 + "}" * 9999 + " until (b)",
                 "x" + " " * 20000 + "{ a } until (b)",
                 "$" + "a" * 20000 + " { b } until (c)",
                 "function " + "a" * 20000 + " { b } until (c)",
                 "try { } catch " + "[a]" * 5000 + " { b } until (c)",
                 "(" * 10000 + ")" * 10000 + " { a } until (b)",
                 "if (" * 5000 + ")" * 5000 + " { a } until (b)"):
        started = time.perf_counter()
        gate._brace_broken(text)
        assert time.perf_counter() - started < 1.0
