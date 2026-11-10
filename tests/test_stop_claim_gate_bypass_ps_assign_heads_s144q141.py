"""S144-Q-141: PowerShell assignment heads S144-Q-135 did not read.

tools/stop_claim_gate.py reads the command on a PowerShell assignment's
right side (S144-Q-135, `_assignment_command`), but its head pattern only
knew `$name =`, `$env:NAME =` and `$name +=`. These heads are also
PowerShell assignments that RUN the right side, and each one hid
`git push --no-verify` from all three call sites (the audit Stop-time scan,
`_note_bypass`, `_bypass_targets`):

- a typed target: `[string]$r = ...`, `[string] $r = ...`, nested and
  stacked type literals (`[List[string]]$r`, `[ValidateNotNull()][string]$r`);
- a scoped name: `$global:r`, `$script:r`, `$local:r`, `$private:r`;
- a braced name: `${r}`, `${global:r}`, `${my var}`;
- same-root siblings found by the sweep: the compound operators `-=`,
  `*=`, `/=`, `%=`, `??=`; a chained assignment `$a = $b = ...`; a
  multiple-target `$a, $b = ...`; an index or member target `$r[0] = ...`,
  `$o.p = ...`.

Additive only (the RM-698 decision): judged only when `extra` is on, so
`_has_bypass(extra=False)` and `_placed(extra=False)` are unchanged. A
single-quoted value is still a literal, and a comparison is not an
assignment.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

ASSIGNED = [
    # typed targets
    "[string]$r = bash -c 'git push --no-verify'",
    "[string] $r = bash -c 'git push --no-verify'",
    "[object[]]$r = (bash -c 'git push --no-verify')",
    "[System.Collections.Generic.List[string]]$r = sh -c 'git commit -n -m x'",
    "[ValidateNotNull()][string]$r = bash -c 'git push --no-verify'",
    # scoped names
    "$global:r = bash -c 'git push --no-verify'",
    "$script:r = $(bash -c 'git push --no-verify')",
    "$local:r = @(bash -c 'git push --no-verify')",
    "$private:r=bash -c 'git push --no-verify'",
    "[string]$script:r = pwsh -Command 'git push --no-verify'",
    # braced names
    "${r} = bash -c 'git push --no-verify'",
    "${global:r} = bash -c 'git push --no-verify'",
    "${my var} = bash -c 'git push --no-verify'",
    '${env:R} = cmd /c "git push --no-verify"',
    "${r} = \"$(bash -c 'git push --no-verify')\"",
    # same-root siblings: compound operators
    "$r -= bash -c 'git push --no-verify'",
    "$r *= bash -c 'git push --no-verify'",
    "$r /= bash -c 'git push --no-verify'",
    "$r %= bash -c 'git push --no-verify'",
    "$r ??= bash -c 'git push --no-verify'",
    # same-root siblings: chained, multiple, index and member targets
    "$a = $b = bash -c 'git push --no-verify'",
    "$a, $b = bash -c 'git push --no-verify'",
    "$r[0] = bash -c 'git push --no-verify'",
    "$o.p = bash -c 'git push --no-verify'",
    "$global:a = ${b} = bash -c 'git push --no-verify'",
]
NOT_COUNTED = [
    "[string]$r = 'bash -c \"git push --no-verify\"'",
    "$global:r = 'git push --no-verify'",
    "${r} = '$(bash -c \"git push --no-verify\")'",
    "[string]$r = bash -c 'git status'",
    "$script:r = git log --grep '--no-verify'",
    "$r ??= 'bash -c \"git push --no-verify\"'",
    "$a = $b = 'bash -c \"git push --no-verify\"'",
    # a value that is a variable reference runs nothing
    "$a = $b",
    "[string]$a = ${b}",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="powershell"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


@pytest.mark.parametrize("command", ASSIGNED)
def test_the_old_rule_and_rm698_missed_the_shape(command, tmp_path):
    """Each shape is new, and extra=False still does not count or place it."""
    assert not gate._bypass_in_text(command)
    assert gate._has_bypass(command, extra=False) is False
    assert gate._placed(command, tmp_path.as_posix(), {}, 0, extra=False) == []


@pytest.mark.parametrize("command", ASSIGNED)
def test_the_head_is_read(command):
    body = gate._assignment_command(command)
    assert body is not None
    assert "git" in body


@pytest.mark.parametrize("command", ASSIGNED)
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", ASSIGNED)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="bash") == [command]


@pytest.mark.parametrize("command", ASSIGNED)
def test_the_shape_is_placed_where_it_runs(command, tmp_path):
    here = tmp_path.as_posix()
    targets = gate._bypass_targets(command, here)
    assert targets
    assert set(targets) == {here}


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_an_assignment_without_a_bypass(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_note_bypass_does_not_record_an_assignment_without_a_bypass(command):
    assert _noted(command) == []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_without_a_bypass(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


@pytest.mark.parametrize("command", [
    "[ $r = x ]",
    "[[ $r == x ]]",
    "$r == bash",
    "$r -eq 1",
])
def test_a_comparison_is_not_an_assignment(command):
    assert gate._assignment_command(command) is None


def test_a_typed_head_bypass_targeting_rc_counts_and_one_outside_does_not(tmp_path):
    """The new heads feed _bypass_hits_rc like any other statement."""
    (tmp_path / "rc" / ".git").mkdir(parents=True)
    (tmp_path / "other" / ".git").mkdir(parents=True)
    rc = (tmp_path / "rc").as_posix()
    other = (tmp_path / "other").as_posix()
    rc_common = gate._git_common_dir(rc)
    command = "[string]$global:r = bash -c 'git push --no-verify'"
    assert gate._bypass_hits_rc(command, rc, rc_common) is True
    assert gate._bypass_hits_rc(command, other, rc_common) is False
