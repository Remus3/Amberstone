"""S144-Q-164: a substitution inside a PowerShell condition was not read.

PowerShell evaluates the condition of `if (...)`, `elseif (...)`,
`while (...)`, `foreach (... in ...)` and `do { } while (...)`, so a
`$( ... )` or `@( ... )` inside those parentheses RUNS its command:
`foreach ($f in $(bash -c 'git commit -n')) { echo }` runs a
hook-bypassing commit. No reading reached it: the S144-Q-153 reading keeps
`foreach` (not a shell keyword) or leaves `($x -eq $(...))` as the head, and
the S144-Q-158 brace reading drops the whole condition to read the block.
Uncounted on HEAD and after S144-Q-158 (its verifier round 1 probe).

Measured with Windows PowerShell 5.1.19041 (`-File`, each substitution a
`Set-Content <marker>` and the marker checked after the run): RUNS -
`foreach ($f in $(..))`, `if ($(..))`, `} elseif ($x -eq $(..))`,
`while ($i -lt 1 -and $(..))`, `foreach ($f in @(..))`,
`if ($m -eq "a $(..)")` (double quotes), `if (-not ($(..)))`,
`do { } while ($(..))`, `if ($m -eq "x""$(..)")`, and in the sibling
sweep `switch ($(..))`, `switch -regex ($(..))`, `for ($i = $(..); ..)`
and `for ($i = 0; $i -lt $(..); ..)`; does NOT run -
`if ($m -eq 'a $(..)')` (single quotes) and `if ($m -eq "a `$(..)")`
(backtick escape).

Fix (EXTRA only, count-only): `_ps_condition_bodies` walks the PowerShell
brace heads at the start of a statement (a `}`, a block head with its
`{`, a condition head with its balanced `( ... )`; `switch [-option ..]`
and `for` are condition heads too), and returns the body of
each `$( ... )` / `@( ... )` in a condition, quote-aware (a single-quoted
span is literal; inside double quotes `$(` still runs, a backtick escapes).
Each body is walked like an assignment body: counted by _raw_words_bypass
and placed from HERE by _placed_reading. A substitution cut off by a
statement break inside it (`$(a | b)`) reads to the end of the statement.
Still missed, filed as S144-Q-165: a bare `( ... )` group in a condition
(`foreach ($f in (bash -c '..'))`) and foreach's bare pipeline
(`foreach ($f in bash -c '..')`), both measured running. A substitution in
a later `for` clause sits past the `;` statement break (the S144-Q-162
cause) and stays with S144-Q-162.
"""
from __future__ import annotations

import time

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "foreach ($f in $(bash -c 'git commit -n')) { echo }",
    "if ($(bash -c 'git commit -n')) { echo }",
    "If ($(bash -c 'git commit -n')) { echo }",
    "if($(bash -c 'git commit -n')){ echo }",
    "elseif ($(bash -c 'git commit -n')) { echo }",
    "} elseif ($x -eq $(bash -c 'git commit -n')) { echo }",
    "if ($y) { echo } elseif ($(bash -c 'git commit -n')) { echo }",
    "while ($x -eq $(bash -c 'git commit -n')) { echo }",
    "do { } while ($(bash -c 'git commit -n'))",
    "if ($x -eq $(git commit -n)) { echo }",
    "foreach ($f in $(git commit -n)) { echo }",
    "foreach ($f in @(bash -c 'git commit -n')) { echo }",
    "if ($m -eq \"a $(bash -c 'git commit -n')\") { echo }",
    'if ($m -eq "x""$(git commit -n)") { }',
    "if (-not ($(bash -c 'git commit -n'))) { echo }",
    "while (($(git commit -n))) { }",
    "if ($x) { if ($(bash -c 'git commit -n')) { echo } }",
    "if ($(bash -c 'git push --no-verify')) { }",
    "if ($(bash -c 'git commit -n' | Out-Null)) { }",
    "if ($(pwsh -Command 'git commit -n')) { }",
    "if ($(git commit --no-veri)) { }",
    # same-root siblings (sweep): switch's value and for's init clause
    "switch ($(bash -c 'git commit -n')) { default { } }",
    "switch -regex ($(git commit -n)) { default { } }",
    "Switch -Wildcard -CaseSensitive ($(git commit -n)) { }",
    "for ($i = $(bash -c 'git commit -n'); $i -lt 1; $i++) { }",
]
NOT_COUNTED = [
    "if ($m -eq 'a $(git commit -n)') { }",
    'if ($m -eq "a `$(git commit -n)") { }',
    "foreach ($f in $(git log -n 3)) { }",
    "if ($(bash -c 'git status -n')) { }",
    "if ($(echo bash -c 'git commit -n')) { }",
    "if ($x) { echo }; foreach ($f in $(git log -n 1)) { echo }",
    "echo 'if ($(git commit -n)) { }'",
    "if ($(",
    "if ($(bash",
    "foreach ($f in $(",
    "if ($x -eq ')' -and $(git log -n 1)) { }",
    "switch -file x.txt { default { git log -n 1 } }",
    "format ($(git log -n 1))",
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
def test_has_bypass_counts_a_substitution_in_a_condition(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_a_substitution_in_a_condition(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_a_substitution_in_a_condition(command):
    assert _noted(command) == [command]
    assert _noted(command, name="bash") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_a_substitution_in_a_condition(command, tmp_path):
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


def test_a_condition_substitution_is_placed_from_here(tmp_path):
    """The body runs where the statement runs: the cwd, or the directory a
    cd before it moved to, like the same command with no head around it."""
    here = tmp_path.as_posix()
    (tmp_path / "sub").mkdir()
    plain = gate._bypass_targets("git commit -n", here)
    assert None not in plain
    assert gate._bypass_targets("if ($(git commit -n)) { }", here) == plain
    assert gate._bypass_targets(
        "foreach ($f in $(bash -c 'git commit -n')) { }", here) == plain
    moved = gate._bypass_targets("cd sub; git commit -n", here)
    assert None not in moved and moved != plain
    assert gate._bypass_targets("cd sub; if ($(git commit -n)) { }", here) == moved


def test_an_absolute_git_c_in_a_condition_is_placed_there(tmp_path):
    other = (tmp_path / "other").as_posix()
    command = f"if ($(git -C {other} commit -n)) {{ }}"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == \
        gate._bypass_targets(f"git -C {other} commit -n", tmp_path.as_posix())


@pytest.mark.parametrize(("statement", "bodies"), [
    ("if ($(a b)) { }", ["a b"]),
    ("foreach ($f in $(a) + @(b)) { c }", ["a", "b"]),
    ("} elseif ($x -eq $(a)) {", ["a"]),
    ("if ($x) { if ($(a)) { } }", ["a"]),
    ("do { } while ($(a))", ["a"]),
    ("try { } finally { }", []),
    ('if ($m -eq "p $(a) q") { }', ["a"]),
    ('if ($m -eq "p @(a) q") { }', []),
    ("if ($m -eq 'p $(a) q') { }", []),
    ('if ($m -eq "p `$(a) q") { }', []),
    ('if ($m -eq "p""$(a)") { }', ["a"]),
    # measured: `"x""'$(..)"` runs, `"x""@(..)"` does not (`""` stays quoted)
    ("if ($m -eq \"p\"\"'$(a)\") { }", ["a"]),
    ('if ($m -eq "p""@(a)") { }', []),
    ("if ($m -eq 'it''s' -and $(a)) { }", ["a"]),
    ("if (($(a)) -and ($(b))) { }", ["a", "b"]),
    ("if ($(a $(b))) { }", ["a $(b)"]),
    ("if ($(a ')' b)) { }", ["a ')' b"]),
    ("if ($(a", ["a"]),
    ("if ($x) { }", []),
    ("echo $(a)", []),
    ("ifx ($(a))", []),
    ("$r = $(a)", []),
    ("if ($x) { echo $(a) }", []),
    ("if ($x -eq ')' -and $(a)) { }", ["a"]),
    ("switch -regex ($(a)) { default { $(b) } }", ["a"]),
    ("for ($i = $(a)", ["a"]),
    ("foreach-object ($(a))", []),
    ("format ($(a))", []),
])
def test_ps_condition_bodies(statement, bodies):
    assert gate._ps_condition_bodies(statement) == bodies


def test_deep_nesting_neither_raises_nor_reads_past_the_cap():
    """A condition nested past the group cap stops the scan (count-only:
    nothing is read there) instead of recursing until RecursionError."""
    deep = "if (" + "(" * 5000 + "$(git commit -n)" + ")" * 5000 + ") { }"
    assert len(deep) < gate.COMMAND_PARSE_MAX
    assert gate._ps_condition_bodies(deep) == []
    assert gate._has_bypass(deep) in (True, False)
    shallow = "if (" + "(" * 8 + "$(git commit -n)" + ")" * 8 + ") { }"
    assert gate._ps_condition_bodies(shallow) == ["git commit -n"]
    assert gate._has_bypass(shallow) is True


def test_a_long_condition_stays_cheap():
    """A condition just under COMMAND_PARSE_MAX full of substitutions is
    scanned once per reading (linear), well inside the RM-829 budget."""
    unit = "$(git log -n 1) -and "
    command = "if (" + unit * ((gate.COMMAND_PARSE_MAX - 40) // len(unit)) + "$x) { }"
    assert len(command) <= gate.COMMAND_PARSE_MAX
    start = time.perf_counter()
    assert gate._has_bypass(command) is False
    assert gate._bypass_targets(command, ".") == []
    assert time.perf_counter() - start < 2.0
