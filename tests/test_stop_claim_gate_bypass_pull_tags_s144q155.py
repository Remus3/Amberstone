"""S144-Q-155: a bypass flag after `git pull -t` was not COUNTED.

`_GIT_DATA_OPTS` lists `-t` (`git commit --template <file>`) as an option
whose NEXT word is a value, and `_DATA_SHORTS` reads a short cluster ending
in `t` the same way, so _git_words_bypass read the word after it as data.
But in `git pull` `-t` is `--tags`, a flag that takes no value (measured
`git pull -h`, git 2.53: `-t, --[no-]tags  fetch all tags and associated
objects`). So `git pull -t '--no-verify'` runs a pull whose merge skips the
pre-merge-commit and commit-msg hooks, and the gate did not count it.
Found by the cycle 214 verifier (round 1).

Measured `git <sub> -h` (git 2.53) for `-t` / `-F` / `-m` over every
subcommand the gate lists (commit, merge, rebase, cherry-pick, revert, pull,
push, am, commit-tree, tag):
- `-t`: a value in commit (`--template <file>`), a flag in pull (`--tags`);
  absent elsewhere.
- `-F`: a value wherever present (commit, merge, commit-tree, tag).
- `-m`: a value in commit, merge, commit-tree, tag (message) and in
  cherry-pick / revert (`--mainline <parent-number>`); a flag in am
  (`--message-id`) and rebase (`--merge`), already in _GIT_FLAG_ONLY_IN.
So the one flag-only spelling not yet listed is pull `-t`. fetch also reads
`-t` / `-m` as flags (`--tags` / `--multiple`) but has no hook-bypass option
(`git fetch -h` lists no --verify / --gpg-sign), so it is not listed.

Same-root sibling sweep over the LONG _GIT_DATA_OPTS (same `git <sub> -h`
read): `--squash` is a flag in merge and pull (`--[no-]squash  create a
single commit instead of doing a merge`) but `--squash <commit>` in commit,
so `git merge --squash '--no-verify'` was uncounted too. Every other long
data option is a value wherever these subcommands spell it in full
(abbreviations are S144-Q-151's).

Fix: `_GIT_FLAG_ONLY_IN["-t"] = {"pull"}` and
`_GIT_FLAG_ONLY_IN["--squash"] = {"merge", "pull"}`. Count-only: the change only
removes data slots, so nothing counted before is lost, and it is judged
only when `extra` is on (extra=False stays RM-698).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "git pull -t '--no-verify'",
    "git pull -t '--no-gpg-sign'",
    "git pull -t \"--no-verify\"",
    # a cluster ending in t: -q is a flag, so the t is --tags
    "git pull -qt '--no-verify'",
    "git pull -at '--no-gpg-sign'",
    "git -C x pull -t '--no-verify'",
    "git PULL -t '--no-verify'",
    "git pull -t -t '--no-verify'",
    "git pull origin main -t '--no-verify'",
    "env -S 'git pull -t --no-verify'",
    "bash -c \"git pull -t '--no-verify'\"",
    # same-root sibling: --squash is a flag in merge / pull
    "git merge --squash '--no-verify'",
    "git merge --squash '--no-gpg-sign'",
    "git pull --squash '--no-verify'",
    "env -S 'git merge --squash --no-verify'",
]
NOT_COUNTED = [
    # the acceptance pin: in commit, -t is --template and takes the next word
    "git commit -t '--no-verify'",
    "git commit -at '--no-verify'",
    "git commit -t '--no-gpg-sign'",
    # pull reads -t as a flag, but a bare -t / -m / -F elsewhere is unchanged
    "git merge -m '--no-verify'",
    "git merge -F '--no-verify'",
    "git tag -m '--no-verify'",
    "git commit-tree -F '--no-verify'",
    # before the subcommand there is no pull to read it by
    "git -t pull",
    # fetch is deliberately unlisted (no hook-bypass option to count)
    "git fetch -t '--no-verify'",
    # --tags alone is no bypass
    "git pull -t",
    # in commit, --squash takes the next word (a commit)
    "git commit --squash '--no-verify'",
    "git merge --squash",
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
    ("-t", "pull", False),
    ("-qt", "pull", False),
    ("-t", "commit", True),
    ("-at", "commit", True),
    ("-t", None, True),
    ("-t", "fetch", True),
    ("-t", "merge", True),
    # -r takes the rest of the cluster in pull (S144-Q-152), unchanged
    ("-rt", "pull", False),
    ("--squash", "merge", False),
    ("--squash", "pull", False),
    ("--squash", "commit", True),
    ("--squash", None, True),
])
def test_is_data_slot_reads_pull_t_as_a_flag(prev, sub, data):
    assert gate._is_data_slot(prev, sub) is data


def test_only_pull_reads_t_as_a_flag():
    """Pin the measured set: adding a subcommand needs a `git <sub> -h`
    measurement, not a guess (commit -t must stay a template value)."""
    assert gate._GIT_FLAG_ONLY_IN["-t"] == frozenset({"pull"})
    assert gate._GIT_FLAG_ONLY_IN["--squash"] == frozenset({"merge", "pull"})
