"""S144-Q-143: a git command inside an `env -S` string was not COUNTED.

GNU `env -S STRING` / `--split-string=STRING` splits STRING into more
arguments and runs them, so `env -S "git commit --no-verify"` runs a
hook-bypassing git commit. tools/stop_claim_gate.py missed it at all three
call sites (the audit Stop-time scan, `_note_bypass`, `_bypass_targets`):
`strip_command_noise` blanks the quoted string, so the old whole-command rule
saw no flag, and `_git_words_bypass` reads one token `git commit --no-verify`
whose basename is not `git`. `_env_options` (S144-Q-136) already splices a
split string into env's arguments; `_has_bypass` and `_placed_reading` now
read the spliced command words of every `env` word in a statement
(`_env_split_bypass`), recursively for a nested `env -S`.

Additive only (the RM-698 decision): judged only when `extra` is on, so
`_has_bypass(extra=False)` and `_placed(extra=False)` are unchanged. Every
`env` word counts, not only a leading one (`nohup env -S ...`), the way
`_wrapper_moves` reads them; a false hit costs one advisory line. A split
statement is placed None (fail closed), the S144-Q-136 decision for a git
statement behind `env -S`.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

SPLIT = [
    'env -S "git commit --no-verify"',
    "env -S 'git commit -n'",
    "env -S 'git push --no-gpg-sign'",
    "env -S 'git -c core.hooksPath=/dev/null commit -m x'",
    "env -S 'FOO=1 git commit -n'",
    "env -S'git push --no-verify'",
    "env --split-string='git push --no-verify'",
    "env --split-string 'git push --no-verify'",
    "env --split 'git push --no-verify'",
    "env -iS 'git commit -n'",
    "env -C /x -S 'git commit -n'",
    "env -S '-C /x git commit -n'",
    "/usr/bin/env -S 'git push --no-verify'",
    "env.exe -S 'git push --no-verify'",
    "nohup env -S 'git push --no-verify'",
    # a git word before env (S144-Q-142 class) does not place the split one
    "sudo -u git env -S 'git commit -n'",
    "env -S 'env -S \"git commit -n\"'",
    # through the other readers: an assignment body and a launcher script
    "r=$(env -S 'git push --no-verify')",
    "$r = env -S 'git push --no-verify'",
    "bash -c \"env -S 'git commit -n'\"",
]
NOT_COUNTED = [
    "env -S 'git status'",
    "env -S 'git log --grep --no-verify'",
    "env -S 'git commit -m -n'",
    "env -S 'echo -n git'",
    # without -S env runs a program NAMED `git commit -n`; nothing is split
    "env 'git commit -n'",
    # the string is printf's argument, not env's
    "printf '%s' \"env -S 'git commit -n'\"",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


@pytest.mark.parametrize("command", SPLIT)
def test_the_old_rule_and_rm698_missed_the_shape(command, tmp_path):
    """Each shape is new, and extra=False still does not count or place it."""
    assert not gate._bypass_in_text(command)
    assert gate._has_bypass(command, extra=False) is False
    assert gate._placed(command, tmp_path.as_posix(), {}, 0, extra=False) == []


@pytest.mark.parametrize("command", SPLIT)
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", SPLIT)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", SPLIT)
def test_the_walk_places_the_shape_none(command, tmp_path):
    """The walk itself places the split statement (fail closed, None), not
    only the `targets or [None]` fallback of _bypass_targets."""
    here = tmp_path.as_posix()
    assert None in gate._placed(command, here, {}, 0)
    assert set(gate._bypass_targets(command, here)) == {None}


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_a_split_without_a_bypass(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_note_bypass_does_not_record_a_split_without_a_bypass(command):
    assert _noted(command) == []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_without_a_bypass(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_a_split_bypass_is_not_hidden_by_a_statement_placed_outside_rc(tmp_path):
    """`env -S '...'` beside a bypass placed outside RC still counts: the
    split statement adds its own fail-closed None to the targets."""
    (tmp_path / "rc" / ".git").mkdir(parents=True)
    (tmp_path / "other" / ".git").mkdir(parents=True)
    rc = (tmp_path / "rc").as_posix()
    other = (tmp_path / "other").as_posix()
    rc_common = gate._git_common_dir(rc)
    command = f"env -S 'git commit -n'; git -C {other} push --no-verify"
    assert None in gate._bypass_targets(command, other)
    assert gate._bypass_hits_rc(command, other, rc_common) is True
    assert gate._bypass_hits_rc(f"git -C {other} push --no-verify", other,
                                rc_common) is False


def test_split_words_are_env_options_command():
    assert gate._env_split_words(["env", "-S", "git commit -n"]) == [
        ["git", "commit", "-n"]]
    assert gate._env_split_words(["nohup", "env", "-iS", "git push"]) == [
        ["git", "push"]]
    assert gate._env_split_words(["env", "git", "commit"]) == []
    assert gate._env_split_words(["env", "-C", "/x", "git", "commit"]) == []
