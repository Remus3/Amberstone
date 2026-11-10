"""S144-Q-149: `git am -n` was not COUNTED.

`git am -n` is `--no-verify` ("bypass pre-applypatch and applypatch-msg
hooks", measured `git am -h`, git 2.53), but _git_words_bypass read a short
`-n` cluster only after `commit` (_commit_no_verify). A porcelain sweep of
`git <sub> -h` found `-n` = `--no-verify` in `commit` and `am` only: it is
`--no-commit` in cherry-pick / revert, `--dry-run` in push / add / clean /
mv / rm, `--no-stat` in rebase, a count in log.

`am` clusters differ from `commit`: `-3` (--3way) is a digit flag, `-m` is
`--message-id` and `-c` `--scissors` (flags, no value), while `-C <n>` and
`-p <num>` take a value (the rest of the cluster, or the next word) and
`-S` only an attached key id.

Same-root sibling (the S144-Q-147 data-slot table): `-m` was read as a
message option everywhere, so the word after it was data. In `am` it is
`--message-id` and in `rebase` `--merge`, both flags, so `git am -m -n`,
`git am -m '--no-verify'` and `git rebase -m '--no-verify'` were missed.
The verifier added `git am --message` / `--committer`: git reads them as
abbreviations of the am flags `--message-id` /
`--committer-date-is-author-date` (measured, `git am --message --abort`
runs --abort), and rebase reads `--committer` the same way (measured,
`git rebase --committer --no-verify` skips the pre-rebase hook).

Count-only: the change only adds `am` clusters and removes data slots, so
nothing counted before is lost, and it is judged only when `extra` is on
(extra=False stays RM-698).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "git am -n",
    "git am -3n",
    "git am -n x.mbox",
    "git am -3 -n",
    "git am -n3",
    "git am -kn",
    "git am -sqn x.mbox",
    "git AM -n",
    "git -C x am -n",
    "git am --verify -n",
    "git am -C 3 -n",
    "git am -p 1 -n",
    "git am -C3 -n",
    "git am --whitespace fix -n",
    "git am --whitespace=fix -n",
    "bash -c 'git am -n'",
    "env -S 'git am -3n'",
    # S144-Q-147 sibling: `-m` is a flag in am (--message-id) and rebase
    # (--merge), so the word after it is an option
    "git am -m -n",
    "git am -km -n",
    "git am -m '--no-verify'",
    "git rebase -m '--no-verify'",
    "git rebase -km '--no-verify'",
    # verifier find: git reads these as abbreviations of am FLAGS
    # (--message-id, --committer-date-is-author-date)
    "git am --message '--no-verify'",
    "git am --committer '--no-verify'",
    # second verifier find: rebase reads --committer as a flag too
    # (measured: `git rebase --committer --no-verify` skips pre-rebase)
    "git rebase --committer '--no-verify'",
]
NOT_COUNTED = [
    # the acceptance pins: -n is --no-commit / a count elsewhere
    "git cherry-pick -n x",
    "git revert -n x",
    "git log -n 3",
    "git push -n",
    "git rebase -n",
    # am value slots: the -n is the value
    "git am -C -n",
    "git am -p -n",
    "git am -C3n",
    "git am -p1n",
    "git am -Sn",
    "git am --whitespace -n",
    "git am --directory -n x",
    "git am --exclude=-n",
    "git am -- -n",
    "git am",
    "git am --continue",
    # -m still takes a message where it is one
    "git commit -m '--no-verify'",
    "git merge -m '--no-verify'",
    "git tag -m '--no-verify' v1",
    "git cherry-pick -m '--no-verify'",
    "git commit --message '--no-verify'",
    "git commit --committer '--no-verify'",
    "git log -n 3 --grep am",
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
def test_has_bypass_does_not_count(command):
    assert gate._has_bypass(command) is False


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


@pytest.mark.parametrize(("words", "expected"), [
    (["-n"], True),
    (["-3n"], True),
    (["-i3sn"], True),
    (["-C", "1", "-n"], True),
    (["-C"], False),
    (["-C", "-n"], False),
    (["-Cn"], False),
    (["-p0n"], False),
    (["-S"], False),
    (["-Sn"], False),
    (["--", "-n"], False),
    (["--patch-format", "-n"], False),
    (["--patch-format=mbox", "-n"], True),
    ([], False),
])
def test_am_no_verify_reads_am_clusters(words, expected):
    assert gate._am_no_verify(words) is expected


@pytest.mark.parametrize(("prev", "sub", "data"), [
    ("-m", "am", False),
    ("-m", "rebase", False),
    ("-km", "am", False),
    ("-m", "commit", True),
    ("-m", "merge", True),
    ("-m", None, True),
    ("-am", "commit", True),
    ("--message", "am", False),
    ("--message", "commit", True),
    ("--committer", "am", False),
    ("--committer", "rebase", False),
    ("--committer", "log", True),
    ("--message", "rebase", True),
    # unchanged S144-Q-147 rows
    ("-S", "commit", False),
    ("-e", "grep", True),
])
def test_is_data_slot_reads_m_by_subcommand(prev, sub, data):
    assert gate._is_data_slot(prev, sub) is data
