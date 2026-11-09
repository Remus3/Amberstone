"""S144-Q-147: a bypass flag after `-S` / `-e` was not COUNTED.

`_GIT_DATA_OPTS` lists `-S` (the log / diff pickaxe string) and `-e` (the
grep pattern) as options whose NEXT word is a value, so _git_words_bypass
and _commit_no_verify read the word after them as data. But in `git
commit` (and merge, rebase, cherry-pick, revert, pull, am, commit-tree)
`-S` is `--gpg-sign[=<key-id>]`, which takes only an ATTACHED key id, and
`-e` is `--edit`, which takes none (measured `git <sub> -h`, git 2.53). So
`git commit -S -n` and `git commit -e '--no-verify'` run a hook-bypassing
commit the gate did not count. Found by the cycle 208 verifier as
`env -S 'git commit -S -n'`.

Fix: `_is_data_slot(prev, sub)` treats `-S` / `-e` as data only outside
the subcommands that read them as flags (`_GIT_FLAG_ONLY_IN`). Count-only:
the change only removes data slots, so nothing counted before is lost, and
it is judged only when `extra` is on (extra=False stays RM-698).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "git commit -S -n",
    "git commit -S '--no-verify'",
    "git commit -e -n",
    "git commit -e '--no-verify'",
    "git -C x commit -S -n",
    "git commit -m x -S -n",
    # `-S` here is the message; the `-n` after it is still an option
    "git commit -m -S -n",
    "git commit -S -e -n",
    "env -S 'git commit -S -n'",
    "git merge -S '--no-verify'",
    "git merge -e '--no-verify'",
    "git rebase -S '--no-verify'",
    "git cherry-pick -e '--no-gpg-sign'",
    "git revert -S '--no-gpg-sign'",
    "git am -S '--no-verify'",
    "git pull -S '--no-verify'",
    "git commit-tree -S '--no-gpg-sign'",
    "bash -c \"git commit -S -n\"",
]
NOT_COUNTED = [
    # the acceptance pin: in log, -S is the pickaxe and takes the next word
    "git log -S -n",
    "git log -S '--no-verify'",
    "git log -G '--no-verify'",
    "git diff -S '--no-verify'",
    "git grep -e '--no-verify'",
    "git grep -e -n",
    # push and pull have no -S / -e flag of that kind: unchanged (data)
    "git push -S '--no-verify'",
    "git pull -e '--no-verify'",
    "git commit -m -S",
    "git commit -S",
    "git commit -e -m x",
    # a cluster ending in S is a key id, never a data slot (unchanged)
    "git commit -Sn",
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
def test_has_bypass_counts_the_shape(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_the_shape(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_has_bypass_does_not_count_a_data_slot(command):
    assert gate._has_bypass(command) is False


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_a_data_slot(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_for_a_data_slot(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


@pytest.mark.parametrize(("prev", "sub", "data"), [
    ("-S", None, True),
    ("-S", "log", True),
    ("-S", "commit", False),
    ("-S", "merge", False),
    ("-S", "push", True),
    ("-e", "grep", True),
    ("-e", "commit", False),
    ("-e", "pull", True),
    ("-m", "commit", True),
    ("-am", "commit", True),
    ("-aS", "commit", False),
    (None, "commit", False),
])
def test_is_data_slot_reads_the_subcommand(prev, sub, data):
    assert gate._is_data_slot(prev, sub) is data


def test_the_subcommand_is_matched_case_insensitively_like_commit():
    """_git_words_bypass already lower-cases the subcommand for `commit`."""
    assert gate._has_bypass("git COMMIT -S -n") is True
