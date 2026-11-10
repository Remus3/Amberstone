"""S144-Q-157: a bypass flag held in a shell variable was not counted.

`F=--no-veri; git commit $F -m x` skips the pre-commit hook exactly like
`git commit --no-veri -m x`, but the stop gate's S144-Q-127 word walk read
the statement's RAW words (`$F`), so it saw no flag. `F=--no-verify; ...`
was counted only because the whole-text RM-698 rule sees `--no-verify`
and a git word anywhere in the command.

Measured with git 2.53.0 in Git Bash (a scratch repo whose pre-commit hook
prints and exits 1; "ran" = the commit succeeded, so the hook was skipped):

- ran: `F=--no-veri; git commit $F -m x`, `F=-n; git commit $F -m x`,
  `F=no-verify; git commit --$F -m x`, `C="commit -n"; git $C -m x`,
  `C="git commit -n -m x"; $C`, `F=--no-veri; git commit "$F" -m x`,
  `F=--no-veri; bash -c "git commit $F -m x"` (the parent expands it).
- blocked: `"$C"` (one word, no command of that name),
  `git commit '$F'` (single quotes do not expand), `F=--no-veri git commit
  $F` (bash expands `$F` before the prefix assignment applies),
  `F=--no-veri; F=x; git commit $F` (the later assignment wins), and
  `F=--no-veri; bash -c 'git commit $F'` (F is not exported, so the child
  shell sees it unset).
- bash splits an unquoted variable into words, PowerShell does not:
  `m='x --no-veri'; git commit -m $m` ran in bash (-m takes "x"), while
  PowerShell `$m = 'x --no-veri'; git commit -m $m` was blocked (one word,
  the message); PowerShell `$F = '--no-veri'; git commit $F -m y` and
  `git commit "$F" -m z` ran.

Fix: _has_bypass tracks each reading's assignments (_assigned, the same
reader _placed_reading uses) and, EXTRA only, also walks a statement's
words after expansion (_held_words: a PowerShell-assigned or `$env:`
variable stays one word, a bash one is split): _git_words_bypass when the
git word is the statement's own or its expanded head (a held string given
to `echo` is data), _env_split_bypass, and the launcher scripts those words
name. A child shell starts with no variables. The placement walk places
such a statement from its expanded words only for a command the walk
without expansion does not count, so every command counted on the base
keeps exactly the targets it had. Count-only and EXTRA-only: extra=False
stays RM-698.

Residual, filed S144-Q-160: an EXPORTED variable read by a single-quoted
child (`export F=--no-veri; bash -c 'git commit $F -m x'` ran) is not
counted, because the child walk starts with no variables.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "F=--no-veri; git commit $F -m x",
    "F=-n; git commit $F -m x",
    "F=no-verify; git commit --$F -m x",
    'C="commit -n"; git $C -m x',
    'C="git commit -n -m x"; $C',
    'F=--no-veri; git commit "$F" -m x',
    "F=--no-veri; git commit ${F} -m x",
    'F=--no-veri; bash -c "git commit $F -m x"',
    "F=--no-veri; git push $F",
    "F=--no-veri && git push $F origin HEAD",
    "export F=--no-veri; git push $F",
    "F=--no-g; git commit $F -m x",
    "A=--no; B=-veri; git push $A$B",
    "F=--no-veri\ngit push $F",
    "$F = '--no-veri'; git push $F",
    "$env:F = '--no-veri'; git push $env:F",
    "F=-n; cd sub && git commit $F -m x",
    "m='x --no-veri'; git commit -m $m",
    "c='git commit -n -m x'; bash -c \"$c\"",
    "$F = '--no-veri'; git commit \"$F\" -m z",
    "S='git commit -n -m x'; env -S \"$S\"",
    # PowerShell evaluates the right side with the OLD value first
    "$F = '-n'; $out = git commit $F -m x",
    "$F = '-n'; $F = git commit $F -m x",
]
NOT_COUNTED = [
    'C="git commit -n -m x"; "$C"',
    "F=--no-veri; git commit '$F' -m x",
    "F=--no-veri git commit $F -m x",
    "F=--no-veri; F=x; git commit $F -m x",
    "F=--no-veri; bash -c 'git commit $F -m x'",
    # an ambiguous or other-subcommand prefix stays uncounted when held
    "F=--no-ver; git commit $F -m x",
    "F=--no-v; git status $F",
    # a held flag used as an option's value is data
    "F=--no-veri; git commit -m $F",
    # no assignment: the name is unset
    "git push $F",
    "git commit $UNSET_NAME -m x",
    # PowerShell passes a variable as one word: here it is the message
    "$m = 'x --no-veri'; git commit -m $m",
    "$env:M = 'x --no-veri'; git commit -m $env:M",
    # a held string handed to another command is data
    "m='git commit -n -m x'; echo $m",
    "m='git push --no-veri'; printf '%s' $m",
    # bash quoting keeps it one word too
    "m='x --no-veri'; git commit -m \"$m\"",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
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
def test_has_bypass_counts_the_held_flag(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_the_held_flag(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_the_held_flag(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_the_held_flag(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_has_bypass_does_not_count_an_unexpanded_or_refused_hold(command):
    assert gate._has_bypass(command) is False


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_an_unexpanded_or_refused_hold(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_for_an_unexpanded_or_refused_hold(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_a_held_flag_is_placed_where_the_statement_runs(tmp_path):
    """The statement is placed from its expanded words, not failed closed."""
    sub = tmp_path / "sub"
    sub.mkdir()
    here = tmp_path.as_posix()
    assert gate._bypass_targets("F=-n; git commit $F -m x", here) == [here]
    targets = gate._bypass_targets("F=-n; cd sub && git commit $F -m x", here)
    assert targets == [gate._join(here, "sub")]
    absolute = sub.as_posix()
    assert gate._bypass_targets(f"F=-n; git -C {absolute} commit $F -m x",
                                None) == [absolute]


def test_an_unplaceable_held_flag_stays_fail_closed(tmp_path):
    """From an unknown directory the held-flag statement is placed None."""
    assert gate._bypass_targets("F=-n; cd $NOWHERE; git commit $F -m x",
                                tmp_path.as_posix()) == [None]


def test_a_child_shell_starts_with_no_variables():
    """A single-quoted child reads its own environment, not the parent's
    unexported assignments; a double-quoted one is expanded by the parent."""
    assert gate._has_bypass("F=-n; bash -c 'git commit $F -m x'") is False
    assert gate._has_bypass('F=-n; bash -c "git commit $F -m x"') is True


def test_the_hold_only_reaches_later_statements():
    """Expansion uses the assignments made BEFORE the statement."""
    assert gate._has_bypass("git push $F; F=--no-veri") is False
    assert gate._has_bypass("F=x; git push $F; F=--no-veri") is False
    assert gate._has_bypass("F=x; F=--no-veri; git push $F") is True


def test_a_base_count_is_never_placed_less(tmp_path):
    """The whole-text rule's fail-closed None survives the new placement:
    the base answer for this command was [None], and it stays in the list."""
    command = "F=--no-verify; git push $F"
    assert None in gate._bypass_targets(command, tmp_path.as_posix())
    command = "F=--no-verify; cd $NOWHERE; git push $F"
    assert set(gate._bypass_targets(command, tmp_path.as_posix())) == {None}
