"""S144-Q-127: hook-bypass shapes that both the pre-RM-698 rule and RM-698 missed.

tools/stop_claim_gate.py counts a hook bypass with `_has_bypass`, which runs
EV_BYPASS plus a git word over the noise-stripped command, or judges a quoted
launcher script (RM-698). Two shapes still slipped through, and this file pins
the addition that counts them at all three call sites (the audit Stop-time
scan, `_note_bypass`, `_bypass_targets`):

(1) a QUOTED flag that is a git argument of its own: `git push '--no-verify'`,
    `git -c 'core.hooksPath=/dev/null' commit` - the stripper blanks the
    quoted span, so the flag vanished before EV_BYPASS saw it;
(2) `git commit -n`, the short spelling of `--no-verify`, which EV_BYPASS
    never matched in any form.

Additive only (the RM-698 decision): the old rule still decides first, so a
command it counted is still counted; the new rule only ever adds counts.
The remaining S144-Q-127 shapes (a flag from a QUOTED assignment, a git call
inside a quoted assignment, `& 'git'`, `cmd /c`, `iex`, `Start-Process`,
`env bash -c`, `wsl -e`, `bash --rcfile x -c`, `-EncodedCommand`, an escaped
quote inside a launcher body) are not covered here.
"""
from __future__ import annotations

import shlex

import pytest

from tools import stop_claim_gate as gate

QUOTED_FLAG = [
    "git push '--no-verify'",
    'git push "--no-verify"',
    "git push origin main '--no-verify'",
    "git commit '--no-gpg-sign' -m x",
    "git -c 'core.hooksPath=/dev/null' commit -m x",
    'git -c "core.hooksPath=" commit -m x',
    "git -c 'core.hooksPath'=/dev/null commit -m x",
    'cd sub && git push "--no-verify" origin',
    "$out = git push '--no-verify'",
    "(git push '--no-verify')",
    "python ops/fleet_kit/fleet_gitlock.py run --owner x -- git push '--no-verify'",
    "bash -c \"git push '--no-verify'\"",
    "pwsh -Command \"git commit '--no-verify' -m x\"",
    '"tools/Git Portable/cmd/git.exe" push "--no-verify"',
]
COMMIT_N = [
    "git commit -n -m x",
    "git commit -nm x",
    "git commit -an -m x",
    "git commit -m x -n",
    "git commit -m '-n' -n",
    "git commit --amend -n --no-edit",
    "git commit --message x -n",
    "git -C sub commit -n -m x",
    "git -c user.name=x commit -n -m x",
    "git --git-dir=.git commit -n",
    "cd sub; git commit -n -m x",
    "$r = git commit -n -m x",
    "bash -c 'git commit -n -m x'",
    'pwsh -Command "git commit -n -m x"',
    "git.exe commit -n -m x",
]
NOT_COUNTED = [
    # A quoted bypass flag that is an option's VALUE is data.
    "git commit -m '--no-verify'",
    'git commit -m "--no-verify"',
    "git commit --message '--no-gpg-sign'",
    "git commit -am '--no-verify'",
    "git log --grep '--no-verify'",
    'git log -S "--no-verify"',
    "git commit -m 'mention --no-verify here'",
    # A bypass flag in a statement with no git word.
    "printf '%s' '--no-verify'; git status",
    "$m = 'git commit --no-verify'; Write-Output $m",
    # -n that is not `git commit`'s no-verify.
    "git commit -mn",
    "git commit -m -n",
    "git commit -m '-n'",
    'git commit -F -n',
    "git commit -C HEAD",
    "git commit --no-edit",
    "git commit -- -n",
    "git log -n 5",
    "git push -n",
    "git revert -n HEAD",
    "git cherry-pick -n abc123",
    "git merge -n topic",
    "echo -n git",
    "echo -n x; git status",
    "git commit-tree -n",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


@pytest.mark.parametrize("command", QUOTED_FLAG + COMMIT_N)
def test_the_old_rule_missed_the_shape(command):
    """Each shape is new: the pre-RM-698 whole-command rule did not count it."""
    assert not gate._bypass_in_text(command)


@pytest.mark.parametrize("command", QUOTED_FLAG + COMMIT_N)
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", QUOTED_FLAG + COMMIT_N)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", QUOTED_FLAG + COMMIT_N)
def test_the_shape_has_a_target(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_data_or_another_meaning(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_note_bypass_does_not_record_data_or_another_meaning(command):
    assert _noted(command) == []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_without_a_bypass(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_a_quoted_flag_is_placed_by_the_cd_before_it(tmp_path):
    inner = tmp_path / "inner"
    command = f'cd "{inner.as_posix()}" && git push \'--no-verify\''
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner.as_posix()]


def test_a_commit_n_is_placed_by_its_own_dash_c(tmp_path):
    inner = tmp_path / "inner"
    command = f'git -C "{inner.as_posix()}" commit -n -m x'
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner.as_posix()]


def test_a_commit_n_inside_a_launcher_is_placed_by_its_cd(tmp_path):
    inner = tmp_path / "inner"
    command = f"bash -c 'cd {inner.as_posix()} && git commit -n -m x'"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner.as_posix()]


@pytest.mark.parametrize("command", QUOTED_FLAG + COMMIT_N)
def test_the_rm698_predicate_alone_missed_the_shape(command):
    """extra=False is the RM-698 predicate exactly: it did not count these."""
    assert gate._has_bypass(command, extra=False) is False


def test_a_new_placement_outside_rc_does_not_hide_an_unplaced_rm698_bypass(tmp_path):
    """RM-698 counted the launcher and placed nothing ([None], so it hit RC);
    the quoted-flag statement now placed outside RC must not take that away."""
    out = (tmp_path / "out").as_posix()
    root = gate.ROOT.as_posix()
    rc = gate._git_common_dir(gate.ROOT)
    assert rc is not None
    command = (f"cd {out} && git push '--no-verify' && "
               "bash -c 'F=--no-verify; git push $F'")
    assert gate._has_bypass(command, extra=False)
    assert gate._bypass_targets(command, root) == [out, None]
    assert gate._bypass_hits_rc(command, root, rc)


def test_a_new_only_bypass_outside_rc_is_placed_outside(tmp_path):
    """No RM-698 count to keep, so the new statement alone places it."""
    out = (tmp_path / "out").as_posix()
    rc = gate._git_common_dir(gate.ROOT)
    command = f"cd {out} && git commit -n -m x"
    assert gate._bypass_targets(command, gate.ROOT.as_posix()) == [out]
    assert not gate._bypass_hits_rc(command, gate.ROOT.as_posix(), rc)


def test_the_old_rule_still_decides_first():
    """A command the old rule counted is counted whatever the new rule says."""
    command = "git commit -m '--no-verify' --no-verify"
    assert gate._bypass_in_text(command)
    assert _noted(command) == [command]


def test_a_commit_n_past_the_nesting_cap_is_not_failed_closed():
    """Past BYPASS_NEST_MAX only an EV_BYPASS flag fails closed: a bare `-n`
    and a git word in raw text is too common (`echo -n`) to count blind."""
    command = "git commit -n -m x"
    for _ in range(gate.BYPASS_NEST_MAX + 2):
        command = "bash -c " + shlex.quote(command)
    assert _noted(command) == []


def test_an_over_long_commit_n_keeps_the_old_rule():
    """Past COMMAND_PARSE_MAX only the old whole-command rule counts."""
    command = "git commit -n -m x; " + "echo x; " * gate.COMMAND_PARSE_MAX
    assert _noted(command) == []
