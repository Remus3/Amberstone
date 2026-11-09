"""S144-Q-152: a bypass after a short cluster whose value letter ate the
rest was not COUNTED.

`_is_data_slot` judged a short cluster only by its LAST letter: a cluster
ending in `m` / `F` / `t` (`_DATA_SHORTS`) took the next word as its value.
But git's parse-options gives the rest of a cluster to the FIRST letter
that takes a value (required or optional), so in `git commit -Cm x` the
`-C` (`--reuse-message <commit>`) takes "m" and `x` is a free word. So
`git commit -Cm '--no-verify'` and `git commit -Cm -n` run a hook-bypassing
commit the gate did not count. Found by the cycle 212 verifier.

Fix: `_is_data_slot(prev, sub)` walks the cluster and, for a subcommand
whose value-taking shorts are measured (`git <sub> -h`, git 2.53), a value
letter before the last letter ends the cluster: the next word is not data.
Count-only: the change only removes data slots, so nothing counted before
is lost, and it is judged only when `extra` is on (extra=False stays
RM-698). A subcommand without a measured set reads as before.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    # the filed shape: -C takes "m", so the flag is an option of commit
    "git commit -Cm '--no-verify'",
    "git commit -Cm -n",
    "git commit -cm '--no-verify'",
    "git commit -Sm '--no-verify'",
    "git commit -Sm -n",
    "git commit -um '--no-gpg-sign'",
    "git commit -tm '--no-verify'",
    "git commit -Fm '--no-verify'",
    "git commit -aCm '--no-gpg-sign'",
    # -m takes "m"; the next word is not a second message
    "git commit -mm '--no-verify'",
    "git commit -mm -n",
    "git commit -Ct '--no-verify'",
    "git -C x commit -Cm -n",
    "git merge -Sm '--no-verify'",
    "git merge -Fm '--no-verify'",
    "git merge -Xm '--no-verify'",
    "git merge -mF '--no-verify'",
    "git cherry-pick -Sm '--no-gpg-sign'",
    "git revert -Sm '--no-gpg-sign'",
    "git commit-tree -pm '--no-gpg-sign'",
    "git commit-tree -Sm '--no-gpg-sign'",
    "git commit-tree -mF '--no-gpg-sign'",
    "git commit-tree -Fm '--no-gpg-sign'",
    "git cherry-pick -Xt '--no-gpg-sign'",
    # same-root siblings: rebase -x / -s / -X, pull -r / -s / -o, push -o
    # and am -S / -p / -C take the rest of the cluster (measured, git 2.53)
    "git rebase -xt '--no-verify'",
    "git rebase -st '--no-verify'",
    "git rebase -XF '--no-gpg-sign'",
    "git rebase -St '--no-verify'",
    "git pull -St '--no-verify'",
    "git pull -st '--no-verify'",
    "git pull -ot '--no-verify'",
    "git pull -Xm '--no-verify'",
    # pull -r takes an abbreviated mode: -rm = merges (measured)
    "git pull -rm '--no-gpg-sign'",
    "git pull -vrm '--no-gpg-sign'",
    "git push -ot '--no-verify'",
    "git push -oF '--no-verify'",
    "git am -St '--no-verify'",
    # am hands -p to git apply, which accepts a letter (measured: applies,
    # and the hooks are skipped)
    "git am -pt '--no-verify'",
    "git am -pF '--no-verify'",
    # --no-verify skips applypatch-msg before git apply refuses -Ct, so a
    # later `git am --continue` can land the patch without that hook
    # (pre-applypatch still runs; measured)
    "git am -Ct '--no-verify'",
    "env -S 'git commit -Cm -n'",
    "bash -c \"git commit -Cm '--no-verify'\"",
]
NOT_COUNTED = [
    # the acceptance pin: a cluster ending in a data letter with no value
    # letter before it still takes the next word as its message
    "git commit -am '--no-verify'",
    "git commit -am -n",
    "git commit -aqm '--no-verify'",
    "git commit -vF '--no-verify'",
    "git commit -st '--no-verify'",
    "git merge -em '--no-verify'",
    # a subcommand without a measured value set reads as before (data)
    "git status -Cm '--no-verify'",
    "git log -Sm '--no-verify'",
    # integer-only shorts never take a letter value: unchanged (data)
    "git rebase -Ct '--no-verify'",
    "git pull -jt '--no-verify'",
    "git cherry-pick -mt '--no-gpg-sign'",
    # push -u is a flag (--set-upstream): the last letter decides (data)
    "git push -ut '--no-verify'",
    # push -n is --dry-run, never a bypass
    "git push -oF -n",
    "git commit -Cm",
    "git commit -m '--no-verify'",
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
    ("-Cm", "commit", False),
    ("-cm", "commit", False),
    ("-Sm", "commit", False),
    ("-um", "commit", False),
    ("-tm", "commit", False),
    ("-mm", "commit", False),
    ("-mF", "commit", False),
    ("-am", "commit", True),
    ("-aqm", "commit", True),
    ("-vF", "commit", True),
    ("-m", "commit", True),
    ("-Sm", "merge", False),
    ("-sm", "merge", False),
    ("-em", "merge", True),
    ("-mF", "merge", False),
    ("-Sm", "cherry-pick", False),
    # cherry-pick / revert -m is the integer mainline, not a value letter
    ("-mt", "cherry-pick", True),
    ("-mt", "revert", True),
    ("-em", "cherry-pick", True),
    ("-Xm", "revert", False),
    ("-pm", "commit-tree", False),
    ("-mF", "commit-tree", False),
    ("-Fm", "commit-tree", False),
    ("-Xt", "cherry-pick", False),
    ("-St", "rebase", False),
    ("-St", "pull", False),
    # integer-only shorts are not value letters here: git refuses `-Um`
    ("-Um", "commit", True),
    # tag has no hook-bypass option: not listed, last letter decides
    ("-um", "tag", True),
    # no measured value set: unchanged (last letter decides)
    ("-Cm", "status", True),
    ("-Cm", None, True),
    ("-Sm", "log", True),
    ("-xt", "rebase", False),
    ("-Ct", "rebase", True),
    ("-st", "pull", False),
    ("-ot", "pull", False),
    ("-rt", "pull", False),
    ("-rm", "pull", False),
    ("-jt", "pull", True),
    ("-ot", "push", False),
    ("-ut", "push", True),
    ("-St", "am", False),
    ("-pt", "am", False),
    ("-Ct", "am", False),
    # S144-Q-147 still binds: -m is a flag in am / rebase
    ("-Cm", "am", False),
    ("-Sm", "rebase", False),
])
def test_is_data_slot_stops_at_the_first_value_letter(prev, sub, data):
    assert gate._is_data_slot(prev, sub) is data


def test_the_commit_value_set_is_the_one_commit_no_verify_uses():
    """The data slot and _commit_no_verify stop at the same commit letters,
    so the two walks agree on where a commit cluster ends."""
    assert gate._SUB_VALUE_SHORTS["commit"] == gate._COMMIT_VALUE_SHORTS


def test_the_am_value_set_covers_the_letters_am_no_verify_uses():
    """_am_no_verify ends a cluster at -C / -p (and -S): the data slot
    reads an am cluster the same way."""
    assert gate._AM_VALUE_SHORTS | {"S"} == gate._SUB_VALUE_SHORTS["am"]
