"""S144-Q-165: a bare group or pipeline in a PowerShell condition was not read.

PowerShell evaluates the condition of `if (...)`, `elseif (...)`,
`while (...)`, `do { } while (...)` and `switch (...)` as a PIPELINE, the
part of `foreach (... in ...)` after `in` as a pipeline and the init clause
of `for (...;` as a statement, and a bare `( ... )` group inside a condition
runs its pipeline too: `if (git commit -n) { }` and
`foreach ($f in (bash -c 'git commit -n')) { }` run a hook-bypassing commit.
S144-Q-164 read only a `$( ... )` / `@( ... )` there; the S144-Q-158 brace
reading drops the whole condition, so no reading reached these.

Measured with Windows PowerShell 5.1.19041 (`-File`, one script per shape,
the command `cmd /c 'copy nul <marker> >nul'` and the marker checked after
the run): RUNS - `if (S)`, `foreach ($f in (S))`, `foreach ($f in S)`,
`foreach ($f in(S))`, `foreach ($f in S | Out-Null)`, `if ($x -eq (S))`,
`if (-not(S))`, `if (-not (S))`, `if ([int](S))`, `if ($s.Contains((S)))`,
`if (Write-Output(S))`, `while ((S))`, `while (S)`, `do { } while (S)`,
`switch ((S))`, `switch (S)`, `for ($i = (S); $false; )`,
`for ($i = S; $false; )`, `if ($false) { } elseif (S)`,
`if ((S) -and $true)`, `if ($null -eq ((S)))`, `if (1 + (S))`,
`[string]::IsNullOrEmpty((S))` in a condition; does NOT run -
`if ($s.Contains(S))` (a method's argument list is not a group: parse
error, nothing runs) and `if ("S")` (a string).

Fix (EXTRA only, count-only): `_ps_condition_pipelines` returns, for each
condition head `_ps_condition_bodies` walks, the condition's own pipeline
when it is a command or an assignment (after `in` for foreach; read to the
end of the statement when a statement break cuts it, as for the `for` init
clause; an expression-mode condition such as `$x -eq ..` runs only its
groups, since a bare command in it does not parse) and the body of every
bare `( ... )` group in it, quote-aware. Which
`(` is a group follows the pipeline's mode (_ps_pipeline_mode,
_ps_paren_kind; verifier rounds 1-2, each shape measured): in command mode
(`Write-Output ...`) every `(` is a group; in expression mode a `(` first
in its group or after an operator, cast or opening is a group, a glued
`.Name(` / `::Name(` is a method's argument list (its contents read in
expression mode, not itself), and a `(` after a value (a variable, number,
word, string, `)`, `-1`, `$x++`) or a spaced one after a member is a parse
error (nothing inside it read); an operator is `-` and letters after a
space or an opening (verifier round 3). Nothing is read inside a scriptblock, a
statement in a group, or a foreach with no `in`; a hash literal is read.
Each body is walked like an assignment body by `_statement_bodies`: counted
by _raw_words_bypass and placed from HERE by _placed_reading. A group and
the pipeline holding it may place the same directory twice;
_bypass_hits_rc reads the targets with any().

Accepted under-count: a command-valued hash entry (`@{a = foo (..)}` runs,
but a hash literal is read in expression mode).

Accepted over-counts (count-only; recorded, not pinned): `$a[0] (..)` (an
index `]` reads like the cast `[int] (..)`, which runs), a group BEFORE a
parse error in the same script (`if ((..) -and $a (x))`), and a group in a
`#` / `<# #>` comment inside a condition (S144-Q-168, an older gap: the
S144-Q-164 substitution reading counts `if (# $(..)` too); and from
verifier round 4, each a script PS 5.1 refuses to run: a `(` glued after
`word-` (`$x -eq a-(..)`), `[void](..)` alone (a runtime error), and an
empty `switch (..) { }` body (the parse error comes after the pipeline).

Still missed, both measured running with PS 5.1 and filed: the call
operator in a condition (`if ($x -eq (& git commit -n))`,
`if ($(& git commit -n))`: _STATEMENT_BREAK splits at the bare `&`,
S144-Q-166) and a group or substitution in a command's ARGUMENTS
(`Write-Output (git commit -n)`, `Write-Output $(git commit -n)`,
S144-Q-167).
"""
from __future__ import annotations

import time

import pytest

from tools import stop_claim_gate as gate
from tests._timing_budget import fleet_test_guard

COUNTED = [
    "foreach ($f in (bash -c 'git commit -n')) { echo }",
    "if ($x -eq (git commit -n)) { }",
    "foreach ($f in bash -c 'git commit -n') { }",
    "foreach ($f in git commit -n) { }",
    "ForEach ($f IN git commit -n) { }",
    "foreach ($f in(git commit -n)) { }",
    "foreach (${f} in git commit -n) { }",
    "foreach ($f in git commit -n | Out-Null) { }",
    "if (-not (git commit -n)) { }",
    "if (-not(git commit -n)) { }",
    "if ([int](git commit -n)) { }",
    "if ($s.Contains((git commit -n))) { }",
    "if (Write-Output(git commit -n)) { }",
    "if (git commit -n) { }",
    "if(git commit -n){ }",
    "if (git commit -nm x) { }",
    "if (git commit --no-veri) { }",
    "while ((git commit -n)) { }",
    "while (git commit -n) { }",
    "do { } while (git commit -n)",
    "switch ((git commit -n)) { default { } }",
    "switch (git commit -n) { default { } }",
    "switch -regex (git commit -n) { default { } }",
    "for ($i = (git commit -n); $false; ) { }",
    "for ($i = git commit -n; $false; ) { }",
    "if ((git commit -n) -and $true) { }",
    "} elseif ((git commit -n)) { }",
    "if ($false) { } elseif (git commit -n) { }",
    "if ($null -eq ((git commit -n))) { }",
    "if (1 + (git commit -n)) { }",
    "if ([string]::IsNullOrEmpty((git commit -n))) { }",
    "if ($x) { if (git commit -n) { } }",
    "if ($x -eq (pwsh -Command 'git commit -n')) { }",
    # verifier round 2, each measured running with PS 5.1: a spaced cast, a
    # command's arguments (command mode: every `(` is a group, a member
    # one too) and a hash literal's value
    "if ([int] (git commit -n)) { }",
    "if (Write-Output 'a' (git commit -n)) { }",
    "if (Write-Output a.b(git commit -n)) { }",
    "if (Write-Output a.b (git commit -n)) { }",
    "if (@{a=(git commit -n)}) { }",
    # verifier round 3 controls, each measured running with PS 5.1, and an
    # assignment condition (measured)
    "if ($x -is [int] (git commit -n)) { }",
    "if (1, (git commit -n)) { }",
    "if ($x -f (git commit -n)) { }",
    "if (!(git commit -n)) { }",
    "if ($s.Contains($x, (git commit -n))) { }",
    "if ($x -replace 'a', (git commit -n)) { }",
    "if (git log -n 1 -and (git commit -n)) { }",
    "if (nosuchcmd (git commit -n)) { }",
    "if ($r = git commit -n) { }",
    "if ($r = (git commit -n)) { }",
    # verifier round 4 controls (measured running): operators, a unary
    # operator after a binary one, a command's method-call argument
    "if ($x -ceq (git commit -n)) { }",
    "if ($x -inotin (git commit -n)) { }",
    "if ($x -eq -not (git commit -n)) { }",
    "if (Write-Output $s.Contains((git commit -n))) { }",
]
NOT_COUNTED = [
    "if ($s.Contains(git commit -n)) { }",
    "if ([string]::Concat(git commit -n)) { }",
    # verifier round 1, each measured running nothing with PS 5.1: a space
    # before a method's paren (a parse error) and a group in a scriptblock
    # value. (`if ((if ($true) { git commit -n }))` runs nothing either but
    # HEAD's brace reading already counts it; _ps_condition_pipelines adds
    # nothing for it, pinned below.)
    "if ($s.Contains ((git commit -n))) { }",
    "if ({ (git commit -n) }) { }",
    # verifier round 2, each measured running nothing with PS 5.1 (a parse
    # error): a `(` after a value in expression mode, and foreach with no
    # `in`
    "if ($a (git commit -n)) { }",
    "if (5 (git commit -n)) { }",
    "if ('a' (git commit -n)) { }",
    "if ($true (git commit -n)) { }",
    "if ($if (git commit -n)) { }",
    "if ((1)(git commit -n)) { }",
    "if ($x -eq foo (git commit -n)) { }",
    "if (-not $x (git commit -n)) { }",
    "if ($x -eq @(1) (git commit -n)) { }",
    "foreach ($x inn (git commit -n)) { }",
    "foreach ($x (git commit -n)) { }",
    # verifier round 3, each measured running nothing with PS 5.1 (a parse
    # error): `-` glued to a number or a word is not an operator, a postfix
    # `++`, a method's arguments and a hash literal's values are
    # expressions, `$env:` is a variable scope, and an expression-mode
    # condition holding a bare command
    "if ($x -eq -1 (git commit -n)) { }",
    "if (-1 (git commit -n)) { }",
    "if ($n -gt 5-1 (git commit -n)) { }",
    "if ($x -eq $y-1 (git commit -n)) { }",
    "if ($x -eq foo-bar (git commit -n)) { }",
    "if ($a-b (git commit -n)) { }",
    "if ([int]-1 (git commit -n)) { }",
    "foreach ($f in -1 (git commit -n)) { }",
    "if ($x) { } elseif ($y -eq -2 (git commit -n)) { }",
    "if ($x++ (git commit -n)) { }",
    "if (@{a = 5 (git commit -n)}) { }",
    "if (@{a = $b (git commit -n)}) { }",
    "if ($s.Contains(a (git commit -n))) { }",
    "if ($s.Contains(Get-Date (git commit -n))) { }",
    "if ($s.Substring(x (git commit -n))) { }",
    "if ($env:Path((git commit -n))) { }",
    "if ($x -eq git commit -n) { }",
    "if ($x -and git commit -n) { }",
    # verifier round 4 (measured, parse errors): a command's variable
    # method paren, a `-word` that is no operator, a unary operator after
    # a value
    "if (Write-Output $s.Contains(git commit -n)) { }",
    "if (Write-Output $s.Substring(git commit -n)) { }",
    "if ($x -eq -foo (git commit -n)) { }",
    "if ($x -Path (git commit -n)) { }",
    "if ($x -eq -Path (git commit -n)) { }",
    "if ($x -eq $x -bnot (git commit -n)) { }",
    "if ($x -and Test-Path -Path (git commit -n)) { }",
    'if ("git commit -n") { }',
    "if ('git commit -n') { }",
    "foreach ($c in 'git commit -n', 'x') { }",
    "if ($x -eq 'git commit -n') { }",
    "if ($m -match '(git commit -n)') { }",
    'if ($m -eq "(git commit -n)") { }',
    "foreach ($f in (git log -n 3)) { }",
    "foreach ($f in git log -n 3) { }",
    "if (git log -n 1) { }",
    "if (Test-Path x) { }",
    "echo 'if (git commit -n) { }'",
    "if ($x) { echo (git log -n 1) }",
    "if (",
    "if (git",
    "foreach ($f in",
    "foreach ($f in (",
    "foreach ($f) { }",
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
def test_has_bypass_counts_a_group_or_pipeline_in_a_condition(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_a_group_or_pipeline_in_a_condition(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_a_group_or_pipeline_in_a_condition(command):
    assert _noted(command) == [command]
    assert _noted(command, name="bash") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_a_group_or_pipeline_in_a_condition(command, tmp_path):
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


def test_a_condition_pipeline_is_placed_from_here(tmp_path):
    """The pipeline runs where the statement runs: the cwd, or the directory
    a cd before it moved to, like the same command with no head around it."""
    here = tmp_path.as_posix()
    (tmp_path / "sub").mkdir()

    def placed(command):
        # a group and the pipeline holding it may both place the same
        # directory; _bypass_hits_rc reads the targets with any()
        return set(gate._bypass_targets(command, here))

    plain = placed("git commit -n")
    assert None not in plain
    assert placed("if (git commit -n) { }") == plain
    assert placed("foreach ($f in (bash -c 'git commit -n')) { }") == plain
    moved = placed("cd sub; git commit -n")
    assert None not in moved and moved != plain
    assert placed("cd sub; if (git commit -n) { }") == moved
    assert placed("cd sub; foreach ($f in git commit -n) { }") == moved


def test_an_absolute_git_c_in_a_condition_group_is_placed_there(tmp_path):
    other = (tmp_path / "other").as_posix()
    command = f"if ($x -eq (git -C {other} commit -n)) {{ }}"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == \
        gate._bypass_targets(f"git -C {other} commit -n", tmp_path.as_posix())


@pytest.mark.parametrize(("statement", "pipelines"), [
    ("if (a b) { }", ["a b"]),
    ("if ($x -eq (a b)) { }", ["a b"]),
    ("foreach ($f in a b) { c }", ["a b"]),
    ("foreach ($f in (a)) { }", ["a"]),
    ("foreach ($f in(a)) { }", ["a"]),
    ("FOREACH (${f} IN a) { }", ["a"]),
    ("foreach ($f) { }", []),
    ("foreach ($f in a ", ["a "]),
    ("} elseif ((a)) {", ["a"]),
    ("while ( (a) ) { }", ["a"]),
    ("if ((a)(b)) { }", ["a"]),
    ("if ($a (b)) { }", []),
    ("if ([int] (a)) { }", ["a"]),
    ("if (Write-Output a.b (c)) { }", ["Write-Output a.b (c)", "c"]),
    ("if (@{k=(a)}) { }", ["a"]),
    ("foreach ($x (a)) { }", []),
    ("if ((if ($x) { (a) })) { }", []),
    ("if ((switch -regex (a) { })) { }", []),
    ("foreach ($x -eq (a)) { }", []),
    ("if ($x) { if (a) { } }", ["a"]),
    ("do { } while (a)", ["a"]),
    ("switch -regex (a) { default { (b) } }", ["a"]),
    ("for ($i = (a)", ["$i = (a)", "a"]),
    ("if ((a) -and ((b))) { }", ["a", "()", "b"]),
    ("if ($x -eq (a (b (c)))) { }", ["a ()", "b ()", "c"]),
    ("if (-not(a)) { }", ["a"]),
    ("if ([int](a)) { }", ["a"]),
    ("if (Write-Output(a)) { }", ["Write-Output(a)", "a"]),
    ("if ($s.Contains(a)) { }", []),
    ("if ($s.Contains((a))) { }", ["a"]),
    ("if ($s.Contains ((a))) { }", []),
    ("if ({ (a) }) { }", []),
    ("if ((if ($x) { a })) { }", []),
    ("if ($x -or (foreach ($f in a) { })) { }", []),
    ("if (Write-Output (a)) { }", ["Write-Output (a)", "a"]),
    ("if (-not (a)) { }", ["a"]),
    ("if ([string]::Concat(a)) { }", []),
    ("if ($m -eq '(a)') { }", []),
    ('if ($m -eq "(a)") { }', []),
    ("if ($(a (b))) { }", []),
    ("if ($x) { }", []),
    ("if ($r = a) { }", ["$r = a"]),
    ("if (a -and (b)) { }", ["a -and (b)", "b"]),
    ("if ($x -eq -1 (a)) { }", []),
    ("if ($env:Path((a))) { }", []),
    ("if ($s.Contains(b (a))) { }", []),
    ("if (@{k = 5 (a)}) { }", []),
    ("echo (a)", []),
    ("ifx ((a))", []),
    ("try { } finally { }", []),
])
def test_ps_condition_pipelines(statement, pipelines):
    assert gate._ps_condition_pipelines(statement) == pipelines


def test_the_substitution_reading_is_unchanged():
    """S144-Q-164's helper still returns only the substitutions."""
    assert gate._ps_condition_bodies("if ((a) -and $(b)) { }") == ["b"]
    assert gate._ps_condition_bodies("if (a) { }") == []


def test_deep_group_nesting_neither_raises_nor_reads_past_the_cap():
    deep = "if (" + "(" * 5000 + "git commit -n" + ")" * 5000 + ") { }"
    assert len(deep) < gate.COMMAND_PARSE_MAX
    assert gate._has_bypass(deep) in (True, False)
    shallow = "if ($x -eq " + "(" * 8 + "git commit -n" + ")" * 8 + ") { }"
    assert "git commit -n" in gate._ps_condition_pipelines(shallow)
    assert gate._has_bypass(shallow) is True


def test_a_long_condition_full_of_groups_stays_cheap():
    """A condition just under COMMAND_PARSE_MAX full of bare groups is
    scanned once per reading, well inside the RM-829 budget."""
    unit = "(git log -n 1) -and "
    command = "if (" + unit * ((gate.COMMAND_PARSE_MAX - 40) // len(unit)) + "$x) { }"
    assert len(command) <= gate.COMMAND_PARSE_MAX
    start = time.perf_counter()
    assert gate._has_bypass(command) is False
    assert gate._bypass_targets(command, ".") == []
    assert time.perf_counter() - start < fleet_test_guard.budget(5.0)


@pytest.mark.parametrize("head", ["if (", "foreach ($f in "])
def test_nested_condition_heads_stay_cheap(head):
    """Verifier round 1: a pipeline that opens with a statement keyword runs
    nothing and is not read, so condition heads nested 32 deep with a long
    tail are not re-walked at every level (2 s before that, 0.02 s on HEAD)."""
    command = head * 32 + "git log -n 1 " + "x" * 17000 + ")" * 32
    assert len(command) <= gate.COMMAND_PARSE_MAX
    start = time.perf_counter()
    assert gate._has_bypass(command) is False
    assert gate._bypass_targets(command, ".") == []
    assert time.perf_counter() - start < fleet_test_guard.budget(1.0)


def _nested(head, tail, depth):
    unit = "git log -n 1 "
    core = 19900 - len(head) - len(tail) - 2 * depth
    return head + "(" * depth + (unit * (core // len(unit) + 1))[:core] + ")" * depth + tail


@pytest.mark.parametrize("head", ["if (", "foreach ($f in ", "if ($r = "])
def test_nested_group_bodies_stay_linear(head):
    """Verifier round 5: each group body is walked with its nested groups
    emptied, so the text handed to the walker stays linear in the command
    (30 levels walked whole were 547k chars for a 19.9k-char command)."""
    command = _nested(head, ") { }", 30)
    total = sum(len(body) for body in gate._ps_condition_pipelines(command))
    assert total <= 2 * len(command)


@pytest.mark.parametrize("head", [
    'if (powershell -Command "if (', 'if ($r = powershell -Command "if (',
    'foreach ($f in powershell -Command "foreach ($g in '])
def test_nested_groups_in_a_launcher_stay_cheap(head):
    """Verifier round 5: 30 nested groups inside a launcher's script took
    1.1-1.4 s (HEAD 0.04 s) before the bodies were emptied."""
    command = _nested(head, ')") { }', 30)
    assert len(command) <= gate.COMMAND_PARSE_MAX
    start = time.perf_counter()
    assert gate._has_bypass(command) is False
    assert gate._bypass_targets(command, ".") == []
    assert time.perf_counter() - start < fleet_test_guard.budget(1.0)
