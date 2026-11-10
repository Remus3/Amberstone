"""S144-Q-151: an abbreviated `--no-verify` / `--no-gpg-sign` was not counted.

git's parse-options takes any UNAMBIGUOUS prefix of a long option, so
`git commit --no-veri` skips the pre-commit hook exactly like
`git commit --no-verify`. The stop gate's bypass rule only knew the full
spellings (EV_BYPASS, `_BYPASS_FLAG_WORD`), and `_PARSE_HINT` did not even
send such a command to the word walk, so the abbreviation went uncounted.

Measured with git 2.53.0 (scratch repos whose hooks print and exit 1, and
`commit.gpgSign=true` with `gpg.program=false` for the signing half):

- `--no-verify`: commit / push / rebase accept `--no-veri` and longer
  (`--no-ver` and shorter are ambiguous with `--no-verbose`, rc 129); am
  accepts `--no-v` and longer (`--no-` is ambiguous); merge / pull accept
  only the full `--no-verify` (every shorter prefix is ambiguous with
  `--no-verify-signatures`).
- `--no-gpg-sign`: commit / merge / rebase / am / pull / commit-tree accept
  `--no-g` and longer (`--no-` is ambiguous); cherry-pick / revert accept
  only the full spelling (any prefix prints usage, rc 129).
- git is case-sensitive (`--NO-VERI` is an unknown option), a prefix with
  `=value` is refused ("takes no value"), and after a `--` the word is a
  pathspec, so none of those is counted.

Fix: `_BYPASS_LONG_MIN` names, per subcommand, the shortest prefix git
accepts; `_long_abbrev_bypass` counts a word after the subcommand that is
such a prefix and is not an option's value. Count-only and EXTRA-only:
extra=False stays RM-698, and `git status --no-v` (= `--no-verbose`) stays
uncounted. Residual, recorded in the cycle report: another git version may
accept a shorter prefix (a new option can only lengthen the minimum).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "git commit --no-veri",
    "git commit -am x --no-verif",
    "git push --no-veri origin HEAD",
    "git push origin HEAD --no-verif",
    "git rebase --no-veri main",
    "git am --no-v 0001.patch",
    "git am --no-ver 0001.patch",
    "git commit --no-g -m x",
    "git commit --no-gpg-sig -m x",
    "git merge --no-g topic",
    "git rebase --no-gp main",
    "git am --no-g 0001.patch",
    "git pull --no-gpg origin main",
    "git commit-tree --no-g -m x 4b825dc",
    "git -C sub commit --no-veri -m x",
    "git -c user.name=x push --no-veri",
    "bash -c 'git push --no-veri'",
    "env -S 'git commit --no-veri'",
    "cd sub && git commit --no-veri -m x",
]
NOT_COUNTED = [
    # ambiguous to git (rc 129), so nothing ran
    "git commit --no-ver",
    "git commit --no-v",
    "git push --no-ver",
    "git rebase --no-ve main",
    "git am --no- 0001.patch",
    "git merge --no-verif topic",
    "git pull --no-veri origin main",
    "git commit --no- -m x",
    # cherry-pick / revert take only the full spelling
    "git cherry-pick --no-g topic",
    "git revert --no-gpg-sig HEAD",
    # other subcommands: a different option, or none
    "git status --no-v",
    "git fetch --no-veri",
    "git log --no-g",
    # case-sensitive, `=value` refused, a value, a pathspec, a git option
    "git commit --NO-VERI",
    "git commit --no-veri=1",
    "git commit -m --no-veri",
    "git commit -m x -- --no-veri",
    "git --no-veri commit",
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
def test_has_bypass_counts_the_abbreviation(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_the_abbreviation(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_the_abbreviation(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_the_abbreviation(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_has_bypass_does_not_count_a_refused_or_other_prefix(command):
    assert gate._has_bypass(command) is False


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_a_refused_or_other_prefix(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_for_a_refused_or_other_prefix(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


@pytest.mark.parametrize(("sub", "flag", "shortest"), [
    ("commit", "--no-verify", "--no-veri"),
    ("push", "--no-verify", "--no-veri"),
    ("rebase", "--no-verify", "--no-veri"),
    ("am", "--no-verify", "--no-v"),
    ("merge", "--no-verify", "--no-verify"),
    ("pull", "--no-verify", "--no-verify"),
    ("commit", "--no-gpg-sign", "--no-g"),
    ("merge", "--no-gpg-sign", "--no-g"),
    ("rebase", "--no-gpg-sign", "--no-g"),
    ("am", "--no-gpg-sign", "--no-g"),
    ("pull", "--no-gpg-sign", "--no-g"),
    ("commit-tree", "--no-gpg-sign", "--no-g"),
])
def test_every_prefix_from_the_measured_minimum_counts(sub, flag, shortest):
    """The table boundary, both sides: every prefix from the shortest one git
    accepted up to the full flag counts, the one just below it does not."""
    for end in range(len(shortest), len(flag) + 1):
        assert gate._git_words_bypass(["git", sub, flag[:end]]) is True, flag[:end]
    below = flag[:len(shortest) - 1]
    assert gate._git_words_bypass(["git", sub, below]) is False, below


@pytest.mark.parametrize("sub", ["cherry-pick", "revert"])
def test_full_only_subcommands_count_only_the_full_flag(sub):
    assert gate._git_words_bypass(["git", sub, "--no-gpg-sign"]) is True
    assert gate._git_words_bypass(["git", sub, "--no-gpg-sig"]) is False
