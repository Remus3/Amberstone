"""S144-Q-158: a launcher behind a PowerShell brace keyword head was not counted.

PowerShell runs the block after `if (...) {`, `elseif (...) {`, `else {`,
`foreach (...) {`, `while (...) {`, `try {`, `finally {` and
`catch [Type] {`, and a statement can open with the `}` that closes the
block before it (`} else {`). So `if ($x) { bash -c 'git commit -n' }` runs
a hook-bypassing commit. S144-Q-153 dropped shell keyword heads, so a
statement that STARTS `else {` or `do {` already read; but `if` was dropped
alone, leaving the condition `($x)` as the head, and the leading `}` was
never a head: no launcher, no count. A bare git statement behind the head
WAS counted (its git word is found anywhere), so only the launcher,
assignment and cd readings missed it.

Measured with Windows PowerShell 5.1 (`-File`, each `bash -c 'echo ..'`
below printed): `if ($x) { .. }`, `} else { .. }` (one line and after a
newline), `} elseif ($x) { .. }`, `foreach ($f in $list) { .. }`,
`while ($x) { ..; break }`, `if ($x) {bash ..}`, `if ($x){ .. }`,
`if (($x) -and $true) { .. }`, `try { .. } finally { }`,
`catch [System.Exception] { .. }`, `if ($x) { $r = bash -c '..' }`,
`If ($x) { .. }`.

Fix: `_keyword_unwrapped(braces=True)` is a SECOND reading that also drops
a leading `}`, a PowerShell block head (`else`, `do`, `try`, `finally`,
`catch` with its `[Type]` words) with its `{`, and a condition head (`if`,
`elseif`, `while`, `foreach`) with its balanced `( ... )` and `{`, a `{`
glued to the next word included. It is walked BESIDE the S144-Q-153
reading, never instead (verifier round 1: PowerShell runs the condition
too, so `if (bash -c 'git commit -n') { ... }` must stay counted). The
launcher read (`_launcher_scripts`), the assignment read
(`_assignment_commands`, `_PS_BRACE_HEAD_TEXT`), the held head
(`_held_bypass`) and the cd placement all take both readings; a `cd`
behind a brace head is placed None (the S144-Q-153 rule: the block may not
run). `_readings(extra=True)` adds a reading with a statement break before
a `}` that `else` / `elseif` / `catch` / `finally` follows, so a block later
in the same statement reads too. EXTRA only, count-only: a statement that
counted before still counts, and `git status` twins and an echoed launcher
stay uncounted.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "if ($x) { bash -c 'git commit -n' }",
    "If ($x) { bash -c 'git commit -n' }",
    "} else { bash -c 'git commit -n' }",
    "if ($y) { echo } else { bash -c 'git commit -n' }",
    "elseif ($y) { bash -c 'git commit -n' }",
    "} elseif ($y) { bash -c 'git commit -n' }",
    "foreach ($f in $list) { bash -c 'git commit -n' }",
    "while ($true) { bash -c 'git commit -n' }",
    "if ($x) {bash -c 'git commit -n'}",
    "if ($x){ bash -c 'git commit -n' }",
    "if ($x){bash -c 'git commit -n'}",
    "if (($x) -and $y) { bash -c 'git commit -n' }",
    "if ((Test-Path x) -and $y) { bash -c 'git commit -n' }",
    "if ($x -eq 1) { sh -c 'git push --no-verify' }",
    "try { bash -c 'git commit -n' } finally { }",
    "} finally { bash -c 'git commit -n' }",
    "} catch [System.Exception] { bash -c 'git commit -n' }",
    "} catch { bash -c 'git commit -n' }",
    "if ($x) { pwsh -Command 'git commit -n' }",
    "if ($x) { cmd /c 'git commit -n' }",
    "if ($x) { iex 'git commit -n' }",
    "if ($x) { env X=1 bash -c 'git commit -n' }",
    "if ($x) { $r = bash -c 'git commit -n' }",
    "} else { $r = bash -c 'git commit -n' }",
    "if ($x) { bash -c 'git commit --no-veri' }",
    "if ($y) {\n} else { bash -c 'git commit -n' }",
    # one statement: the block after `}` is broken out (_brace_broken)
    "if ($x) { bash -c 'git status' } else { bash -c 'git commit -n' }",
    "if ($x) { a } elseif ($y) { b } else { bash -c 'git commit -n' }",
    "try { a } catch [IO.IOException] { b } finally { bash -c 'git commit -n' }",
    "try { a } Catch { bash -c 'git commit -n' }",
]
NOT_COUNTED = [
    "if ($x) { bash -c 'git status -n' }",
    "} else { bash -c 'git log -n 3' }",
    "foreach ($f in $list) { echo bash -c 'git commit -n' }",
    "if ($x) { $r = bash -c 'git status' }",
    "if ($x) { $r = 'bash -c git commit -n' }",
    "if ($x) { }",
    "} else { }",
    "}",
    "if (",
    "if ($x",
    "if ($x) { echo '} else { bash -c git commit -n' }",
    "if ($x) { bash -c 'git status' } else { bash -c 'git log -n 1' }",
    "do { bash -c 'git status -n' } while ($x)",
    "m='git commit -n'; if x; then echo $m; fi",
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
def test_has_bypass_counts_a_launcher_behind_a_brace_head(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_a_launcher_behind_a_brace_head(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_a_launcher_behind_a_brace_head(command):
    assert _noted(command) == [command]
    assert _noted(command, name="bash") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_a_launcher_behind_a_brace_head(command, tmp_path):
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


def test_a_launcher_behind_a_brace_head_is_placed_in_the_cwd(tmp_path):
    """`if ($x) { bash -c '...' }` from the cwd is placed in the cwd, like
    the same launcher with no head in front of it."""
    here = tmp_path.as_posix()
    plain = gate._bypass_targets("bash -c 'git commit -n'", here)
    assert gate._bypass_targets("if ($x) { bash -c 'git commit -n' }", here) == plain
    assert gate._bypass_targets("} else { bash -c 'git commit -n' }", here) == plain
    assert None not in plain


@pytest.mark.parametrize("command", [
    "if ($x) { cd elsewhere }; git commit -n",
    "if ($x) { cd elsewhere }; bash -c 'git commit -n'",
    "} else { Set-Location elsewhere }; git commit -n",
    "foreach ($f in $list) { Push-Location elsewhere }; git commit -n",
    "if ($x) {cd elsewhere}; git commit -n",
    "if ($x) { Pop-Location }; git commit -n",
])
def test_a_cd_behind_a_brace_head_places_later_statements_none(command, tmp_path):
    """The block may or may not run, so the directory after it is unknown:
    fail closed (None), never the cwd and never the cd target."""
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


def test_an_absolute_git_c_after_a_brace_cd_is_still_placed(tmp_path):
    """Control: an absolute `git -C` places its statement even when the cd
    behind the head made the directory unknown."""
    other = (tmp_path / "other").as_posix()
    command = f"if ($x) {{ cd elsewhere }}; git -C {other} push --no-verify"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [other]


@pytest.mark.parametrize(("words", "expected"), [
    (["if", "($x)", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["IF", "($x)", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["}", "else", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["}", "elseif", "($a", "-eq", "1)", "{", "sh", "-c", "x"], ["sh", "-c", "x"]),
    (["foreach", "($f", "in", "$list)", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["while", "((a)", "-and", "b)", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["if", "($x)", "{bash", "-c", "x"], ["bash", "-c", "x"]),
    (["if", "($x){", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["if", "($x){bash", "-c", "x"], ["bash", "-c", "x"]),
    (["else", "{bash", "-c", "x"], ["bash", "-c", "x"]),
    (["try", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["}", "finally", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["}", "catch", "[System.Exception]", "{", "bash", "-c", "x"],
     ["bash", "-c", "x"]),
    (["}", "catch", "[A]", "[B]", "{", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["}"], []),
    (["if", "($x)", "{"], []),
    # a condition not closed by `{` keeps the S144-Q-153 bash reading
    (["if", "(bash", "-c", "x)"], ["bash", "-c", "x)"]),
    (["if", "($x"], ["$x"]),
    (["if", "($x)", "bash", "-c", "x"], ["$x)", "bash", "-c", "x"]),
    (["if", "($x)x", "{", "bash", "-c", "x"], ["$x)x", "{", "bash", "-c", "x"]),
    (["try", "bash", "-c", "x"], ["try", "bash", "-c", "x"]),
    (["catch", "[A]", "bash"], ["catch", "[A]", "bash"]),
    # a brace head is never read behind a launcher or a plain command
    (["bash", "-c", "if"], ["bash", "-c", "if"]),
    (["echo", "}", "else", "{", "bash"], ["echo", "}", "else", "{", "bash"]),
    (["git", "commit"], ["git", "commit"]),
])
def test_keyword_unwrapped_reads_powershell_brace_heads(words, expected):
    assert gate._keyword_unwrapped(words, braces=True) == expected


@pytest.mark.parametrize("words", [
    ["if", "($x)", "{", "bash", "-c", "x"],
    ["}", "else", "{", "bash", "-c", "x"],
    ["try", "{", "bash", "-c", "x"],
    ["if", "(bash", "-c", "x)", "{", "echo", "}"],
])
def test_the_plain_keyword_reading_is_unchanged(words):
    """The default reading is S144-Q-153's exactly; the brace reading is an
    extra one (_keyword_readings), plain first."""
    i = 0
    while i < len(words) and words[i].lower() in gate._SH_KEYWORD_HEADS:
        i += 1
    plain = list(words[i:])
    if plain and plain[0].startswith("(") and plain[0].lstrip("("):
        plain[0] = plain[0].lstrip("(")
    assert gate._keyword_unwrapped(words) == plain
    readings = gate._keyword_readings(words)
    assert readings[0] == plain
    assert readings[-1] == gate._keyword_unwrapped(words, braces=True)


# Verifier round 1: counted before the fix through the S144-Q-153 reading
# of the condition; a reading that skipped the condition lost them.
CONDITION_RUNS = [
    "if (bash -c 'git commit -n') { echo hi }",
    "if (bash -c 'git commit -n') {}",
    "if ((bash -c 'git commit -n')) { echo hi }",
    "while (bash -c 'git push --no-verify') { }",
    "if ($r = bash -c 'git commit -n') { echo hi }",
    "if (bash -c 'git commit -n') { cd elsewhere }",
    "if ($r = bash -c 'git commit -n') { $s = bash -c 'git status' }",
]


@pytest.mark.parametrize("command", CONDITION_RUNS)
def test_a_launcher_in_the_condition_still_counts(command, tmp_path):
    here = tmp_path.as_posix()
    assert gate._has_bypass(command) is True
    targets = gate._bypass_targets(command, here)
    assert here in targets or None in targets


def test_a_launcher_in_the_condition_and_the_block_both_count(tmp_path):
    here = tmp_path.as_posix()
    other = (tmp_path / "other").as_posix()
    command = (f"if (bash -c 'git -C {other} commit -n') "
               f"{{ bash -c 'git commit -n' }}")
    targets = gate._bypass_targets(command, here)
    assert other in targets and here in targets


@pytest.mark.parametrize(("statement", "body"), [
    ("if ($x) { $r = bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("} else { $r = bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("} elseif (($a) -or $b) { $r = $(git commit -n)", "git commit -n"),
    ("foreach ($f in $l) {$r = bash -c 'x'", "bash -c 'x'"),
    ("then r=$(bash -c 'x')", "bash -c 'x'"),
    ("if ($x) { $r = 'literal'", None),
])
def test_assignment_command_reads_behind_a_brace_head(statement, body):
    assert gate._assignment_command(statement, braces=True) == body
    assert gate._assignment_commands(statement) == ([body] if body else [])


def test_assignment_commands_keep_the_plain_body_first():
    statement = "if ($r = bash -c 'a') { $s = bash -c 'b'"
    plain = gate._assignment_command(statement)
    assert plain is not None and plain.startswith("bash -c 'a'")
    assert gate._assignment_commands(statement) == [plain, "bash -c 'b'"]


@pytest.mark.parametrize(("text", "broken"), [
    ("if ($x) { a } else { b }", "if ($x) { a \n} else { b }"),
    ("try { a } catch { b } finally { c }",
     "try { a \n} catch { b \n} finally { c }"),
    ("if ($x) { a }ElseIf ($y) { b }", "if ($x) { a \n}ElseIf ($y) { b }"),
    # already at a statement start: nothing to break
    ("} else { b }", "} else { b }"),
    ("a; } else { b }", "a; } else { b }"),
    # inside quotes, or not followed by a block keyword: left alone
    ("echo '} else {'", "echo '} else {'"),
    ("do { a } while ($x)", "do { a } while ($x)"),
    ("if ($x) { a } elsewhere", "if ($x) { a } elsewhere"),
])
def test_brace_broken(text, broken):
    assert gate._brace_broken(text) == broken


def test_readings_add_the_brace_broken_reading_only_with_extra():
    """The raw reading stays first and is never replaced; extra=False is
    the reading list it always was."""
    command = "if ($x) { a } else { b }"
    assert gate._readings(command) == [command]
    assert gate._readings(command, extra=False) == [command]
    assert gate._readings(command, extra=True) == [
        command, "if ($x) { a \n} else { b }"]
    assert gate._readings("git status", extra=True) == ["git status"]


@pytest.mark.parametrize("command", [
    "C='git commit -n -m x'; if true; then $C; fi",
    "C='git commit -n'; while x; do $C; done",
    "C='git push --no-veri'; if x; then ! $C; fi",
])
def test_a_held_git_command_behind_a_keyword_head_counts(command, tmp_path):
    """Sibling (same root, the S144-Q-157 expanded head): bash splits `$C`
    behind a keyword head and runs git; measured with GNU bash 5.2.37 (the
    first command made a commit past a pre-commit hook that exits 1)."""
    assert gate._has_bypass(command, expand=False) is False
    assert gate._has_bypass(command) is True
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


def test_a_launcher_in_the_condition_of_a_brace_cd_is_still_placed(tmp_path):
    """Verifier round 1: when only the brace reading is a cd
    (`if (bash -c '...') { cd x }`), the launcher the plain reading names is
    still walked and placed from the directory before the cd."""
    other = (tmp_path / "other").as_posix()
    command = f"if (bash -c 'git -C {other} commit -n') {{ cd elsewhere }}"
    targets = gate._bypass_targets(command, tmp_path.as_posix())
    assert other in targets


@pytest.mark.parametrize("template", [
    "F=-n; git commit $F; if ($x) {{ bash -c 'git -C {other} commit -n' }}",
    "C='git commit -n'; if ($x) {{ bash -c 'git -C {other} commit -n' }}; $C",
    "F=-n; git commit $F; }} else {{ bash -c 'git -C {other} commit -n' }}",
    "F=-n; git commit $F; if ($x) {{ $r = bash -c 'git -C {other} commit -n' }}",
    # the same loss on the gate before this fix, with no brace head at all
    "F=-n; git commit $F; bash -c 'git -C {other} commit -n'",
    "F=-n; git commit $F; git -C {other} push --no-verify",
    "C='git commit -n'; git -C {other} commit -n; $C",
])
def test_a_held_bypass_is_still_placed_beside_a_counted_one(template, tmp_path):
    """Verifier round 2: when another statement counts without expansion,
    _bypass_targets used to skip the S144-Q-157 expanded walk, so the held
    `git commit $F` in the cwd was dropped and only `<other>` was placed.
    Both are placed now (the expanded walk's targets are added)."""
    here = (tmp_path / "rc").as_posix()
    other = (tmp_path / "other").as_posix()
    targets = gate._bypass_targets(template.format(other=other), here)
    assert other in targets
    assert here in targets
