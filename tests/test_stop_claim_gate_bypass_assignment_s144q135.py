"""S144-Q-135: a launcher on an assignment's right side hid a hook bypass.

tools/stop_claim_gate.py judges a quoted launcher script (`bash -c '...'`)
as a nested command (RM-698, S144-Q-127 part 2), but only when the launcher
is the statement's FIRST word. An assignment put something else first, so
the quoted script stripped to nothing and `git push --no-verify` was not
counted at any of the three call sites (the audit Stop-time scan,
`_note_bypass`, `_bypass_targets`):

- PowerShell runs a command on an assignment's right side:
  `$r = bash -c '...'`, `$r=bash -c`, `$r = (...)`, `$r = $(...)`,
  `$r = @(...)`, `$env:R = pwsh -Command ...`, `$r += ...`;
- a bash command substitution as the whole value: `r=$(bash -c '...')`,
  `` r=`...` ``, behind `export` / `local` / `readonly`;
- a bash environment prefix in front of the launcher:
  `FOO=1 bash -c '...'`;
- a substitution in DOUBLE quotes is still run by both shells:
  `r="$(bash -c '...')"`, and the same root cause hid the S144-Q-127
  shape `x="$(git push --no-verify)"`.

Additive only (the RM-698 decision): judged only when `extra` is on, so
`_has_bypass(extra=False)` and `_placed(extra=False)` are unchanged. A
single-quoted value is a literal in both shells and stays uncounted, and a
bash `r=(...)` is an array of words, not a command.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

ASSIGNED = [
    "$r = bash -c 'git push --no-verify'",
    "$r=bash -c 'git push --no-verify'",
    "$r = (bash -c 'git push --no-verify')",
    "$r = $(bash -c 'git push --no-verify')",
    "$r = @(sh -c 'git commit -n -m x')",
    "$env:R = pwsh -Command 'git push --no-verify'",
    "$r += bash -c 'git push --no-verify'",
    '$r = cmd /c "git push --no-verify"',
    "$x = \"$(bash -c 'git push --no-verify')\"",
    "r=$(bash -c 'git push --no-verify')",
    "r=`bash -c 'git push --no-verify'`",
    "export r=$(bash -c 'git push --no-verify')",
    "local r=$(sh -c 'git commit -n -m x')",
    "readonly r=$(zsh -c 'git push --no-verify')",
    "r=\"$(bash -c 'git push --no-verify')\"",
    "r=\"`bash -c 'git push --no-verify'`\"",
    "r=$(env bash -c 'git push --no-verify')",
    "FOO=1 bash -c 'git push --no-verify'",
    "FOO=1 BAR=2 sh -c 'git push --no-verify'",
    "FOO=1 env bash -c 'git commit -n -m x'",
    # The same root cause, S144-Q-127's "git call inside a quoted assignment".
    'x="$(git push --no-verify)"',
    '$x = "$(git push --no-verify)"',
]
NOT_COUNTED = [
    "x='$(git push --no-verify)'",
    "$r = 'bash -c \"git push --no-verify\"'",
    "r='bash -c \"git push --no-verify\"'",
    "r=(bash -c 'git push --no-verify')",
    "r=$(bash -c 'git status')",
    "$r = bash -c 'git status'",
    "FOO=1 bash -c 'git status'",
    "$r = git log --grep '--no-verify'",
    "r=\"$(git log --grep '--no-verify')\"",
    '$F = "--no-verify"; git status',
    # PowerShell string values, not commands: a single-quoted first word
    # (`'bash' -c ...` there is a parse error, never a run), and `(...)` / a
    # backtick inside double quotes are literal text.
    "$r = 'bash' -c 'git push --no-verify'",
    "$r = \"(bash -c 'git push --no-verify')\"",
    "$r = \"`bash -c 'git push --no-verify'`\"",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
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
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", ASSIGNED)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


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


def test_a_substituted_script_is_placed_by_its_own_cd(tmp_path):
    inner = (tmp_path / "inner").as_posix()
    command = f"r=$(bash -c 'cd {inner} && git push --no-verify')"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner]


def test_a_moved_prefixed_launcher_is_placed_none(tmp_path):
    """`env -C` behind an environment prefix still fails closed."""
    command = f"FOO=1 env -C {tmp_path.as_posix()} bash -c 'git push --no-verify'"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


def test_a_later_cd_is_not_moved_by_a_substitution(tmp_path):
    """The substituted script's `cd` does not leak into the caller's walk."""
    inner = (tmp_path / "inner").as_posix()
    command = (f"r=$(bash -c 'cd {inner} && git status'); "
               "bash -c 'git push --no-verify'")
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [tmp_path.as_posix()]


def test_a_bypass_targeting_rc_counts_and_one_outside_does_not(tmp_path):
    """The new placement feeds _bypass_hits_rc like any other statement."""
    (tmp_path / "rc" / ".git").mkdir(parents=True)
    (tmp_path / "other" / ".git").mkdir(parents=True)
    rc = (tmp_path / "rc").as_posix()
    other = (tmp_path / "other").as_posix()
    rc_common = gate._git_common_dir(rc)
    command = "$r = bash -c 'git push --no-verify'"
    assert gate._bypass_hits_rc(command, rc, rc_common) is True
    assert gate._bypass_hits_rc(command, other, rc_common) is False


def test_past_the_nest_limit_a_substitution_fails_closed(tmp_path):
    """Nesting past BYPASS_NEST_MAX still counts and places None."""
    command = "bash -c 'git push --no-verify'"
    for _ in range(gate.BYPASS_NEST_MAX + 2):
        command = f"r=$({command})"
    assert gate._has_bypass(command, extra=False) is False
    assert gate._has_bypass(command) is True
    assert None in gate._bypass_targets(command, tmp_path.as_posix())
