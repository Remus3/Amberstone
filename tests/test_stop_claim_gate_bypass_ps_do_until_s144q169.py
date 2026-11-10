"""S144-Q-169 (do-until shape): `do { } until (...)` was not read.

PowerShell evaluates the condition of `do { } until (...)` exactly as it
does `do { } while (...)`, so `do { } until (git commit -n)` runs a
hook-bypassing commit. S144-Q-164 / S144-Q-165 read the condition of
`if`, `elseif`, `while`, `foreach`, `for` and `switch` (_PS_HEAD_STEP),
but `until` was not a condition head there, so the scan stopped at it.

Measured with Windows PowerShell 5.1.19041 (`-File`, one script per shape,
S = `cmd /c "copy nul <marker> >nul & echo 1"`, the marker checked after
the run; the echo ends the loop): RUNS - `do { } until (S)`,
`do { } until ($(S))`, `do { } until ((S))`, `do { } until ($x -eq (S))`,
`Do { } Until (S)`, `do { } UNTIL (S)`, `do {} until(S)`,
`do { } until (Write-Output 'a' (S))`, `do { } until (-not (S))`,
`do { } until ([int](S))`, `do { } until ($r = S)` (HEAD already counts
it as an assignment), `do {` / `} until (S)` on two lines, and a bare
`until (S)`: `until` alone is no statement, PowerShell reads it as a
command name and evaluates its `( ... )` argument before the lookup fails
("The term 'until' is not recognized"). So `if (until (S)) { }`,
`if ((until (S))) { }` and `if ($x -eq (until (S))) { }` run S too, and
HEAD counts them because a pipeline opening with `until (` is read in
command mode; that reading must stay. Does NOT run - `do { } until ('S')`
(a string), `do { } until ($x -eq S)` (a bare command in an expression:
parse error) and `do { } until ({ S })` (a scriptblock value). HEAD
already over-counts the last two through an older reading, exactly as it
does `do { } while ($x -eq S)` and `x ({ S })`, so they are filed, not
pinned here.

Fix (EXTRA only, count-only): `until` is a condition head for the scan
(_PS_HEAD_STEP), and the statement test that decides a pipeline's mode
and drops a statement pipeline (_PS_STATEMENT_HEAD) keeps the old heads,
so a pipeline opening with `until (` is still a command.

Still missed, a different root, filed: a statement break inside the
block before the condition (`do { echo a; echo b } until (S)` runs S, and
so does the same with `while`; _STATEMENT_BREAK splits at the `;`, so the
condition sits in a statement that opens with a command; S144-Q-170).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "do { } until (git commit -n)",
    "do { } until ($(git commit -n))",
    "do { } until ((git commit -n))",
    "do { } until ($x -eq (git commit -n))",
    "Do { } Until (git commit -n)",
    "do { } UNTIL (git commit -n)",
    "do {} until(git commit -n)",
    "do { } until (Write-Output 'a' (git commit -n))",
    "do { } until (-not (git commit -n))",
    "do { } until ([int](git commit -n))",
    "do { } until (bash -c 'git commit -n')",
    "} until (git commit -n)",
    "until (git commit -n)",
]
# HEAD already counts these (a pipeline opening with `until (` is a
# command, measured running); the fix must not lose them.
KEPT = [
    "if (until (git commit -n)) { }",
    "if ((until (git commit -n))) { }",
    "if ($x -eq (until (git commit -n))) { }",
    "do { } until ($r = git commit -n)",
    "do { } while (git commit -n)",
]
NOT_COUNTED = [
    "do { } until ('git commit -n')",
    "do { } until (git log -n 3)",
    "do { } until ($x -eq 'git commit -n')",
    "echo 'do { } until (git commit -n)'",
    "do { } until (",
    "do { } until (git",
    "until (",
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
def test_has_bypass_counts_a_do_until_condition(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_a_do_until_condition(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_a_do_until_condition(command):
    assert _noted(command) == [command]
    assert _noted(command, name="bash") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_a_do_until_condition(command, tmp_path):
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


def test_a_do_until_condition_is_placed_from_here(tmp_path):
    here = tmp_path.as_posix()
    (tmp_path / "sub").mkdir()

    def placed(command):
        return set(gate._bypass_targets(command, here))

    plain = placed("git commit -n")
    assert None not in plain
    assert placed("do { } until (git commit -n)") == plain
    moved = placed("cd sub; git commit -n")
    assert None not in moved and moved != plain
    assert placed("cd sub; do { } until (git commit -n)") == moved


@pytest.mark.parametrize(("statement", "pipelines"), [
    ("do { } until (a b)", ["a b"]),
    ("do { } until ($x -eq (a b))", ["a b"]),
    ("} until (a b)", ["a b"]),
    ("until (a b)", ["a b"]),
    ("do { } until ('a b')", []),
    ("if (until (a b)) { }", ["until (a b)", "a b"]),
])
def test_ps_condition_pipelines(statement, pipelines):
    assert gate._ps_condition_pipelines(statement) == pipelines


def test_ps_condition_bodies_reads_a_do_until_substitution():
    assert gate._ps_condition_bodies("do { } until ($(a b))") == ["a b"]


@pytest.mark.parametrize("text", ["until (a)", "Until(a)", "UNTIL (a b)"])
def test_a_pipeline_opening_with_until_is_a_command(text):
    assert gate._ps_pipeline_mode(text, 0) == "command"


@pytest.mark.parametrize("text", ["if (a)", "while (a)", "do { a", "{ a"])
def test_the_statement_heads_are_unchanged(text):
    assert gate._ps_pipeline_mode(text, 0) == "statement"
