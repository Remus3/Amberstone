"""S144-Q-156: a word an option CONSUMED as its value was then read as an option.

`_git_words_bypass` and `_commit_no_verify` judge each word by the word
before it (`_is_data_slot(prev, sub)`), and set `prev = word` even when the
word was itself a value. So in `git commit -m -am '--no-verify'` the `-m`
takes "-am" as its message, but the walk then judged "-am" as a short cluster
ending in `m` and read `--no-verify` as a message too. git does not: its
parse-options hands a required-value option the next argv word whatever it
looks like, so the word after a consumed value is an option again.

Measured with git 2.53 (a scratch repo whose pre-commit hook prints and
exits 1): `git commit -m -am --no-verify`, `git commit -m -am -n`,
`git commit -m -m -n`, `git commit --message --file --no-verify` and
`git commit -m -- -n` each COMMIT with the hook skipped (the message is
"-am" / "-m" / "--file" / "--"), while `git commit -m x -am y` runs the hook
(rc 1): there `x` is the value and `-am` is a real cluster whose `m` takes
"y". Found by the cycle 214 verifier (round 1).

Same-root sibling: `_commit_no_verify` stopped at a "--" word before asking
whether "--" was a value, so `git commit -m -- -n` (the message "--") was not
counted either. A "--" that is not a value still ends the options.

Fix: both walks clear `prev` after a word that was a value, so the next word
is judged as an option (the S144-Q-149 `_am_no_verify` walk already skipped
a consumed word). Count-only: this only removes data slots, so nothing
counted before is lost, and it is judged only when `extra` is on
(extra=False stays RM-698).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "git commit -m -am '--no-verify'",
    "git commit -m -am '--no-gpg-sign'",
    "git commit -m '-am' '--no-verify'",
    "git commit -m -m '--no-verify'",
    "git commit --message --file '--no-verify'",
    "git merge -m -F '--no-verify'",
    "git commit -m -am -n",
    "git commit -m -m -n",
    "git commit --message -m -n",
    "git commit -m x -am y -m -am -n",
    # same-root sibling: a "--" that is a value does not end the options
    "git commit -m -- -n",
    "env -S 'git commit -m -am --no-verify'",
    "bash -c \"git commit -m -am '--no-verify'\"",
]
# Counted before by the raw-text rule (unquoted flag); must stay counted.
STILL_COUNTED = [
    "git commit -m -am --no-verify",
]
NOT_COUNTED = [
    # the acceptance pin: `x` is the value, `-am` a cluster whose m takes the flag
    "git commit -m x -am '--no-verify'",
    "git commit -m '--no-verify'",
    "git commit -am '--no-verify'",
    "git commit -m x -m '--no-verify'",
    # a consumed word resets once: the next -m takes the flag again
    "git commit -m -am -m '--no-verify'",
    "git commit -m -am -m -n",
    "git commit -m -- -m -n",
    # a "--" that is not a value still ends the options
    "git commit -- -n",
    "git commit -m x -- -n",
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


@pytest.mark.parametrize("command", COUNTED + STILL_COUNTED)
def test_has_bypass_counts_the_shape(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED + STILL_COUNTED)
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED + STILL_COUNTED)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", COUNTED + STILL_COUNTED)
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


@pytest.mark.parametrize(("words", "hit"), [
    (["-m", "-am", "-n"], True),
    (["-m", "--", "-n"], True),
    (["--message", "-m", "-n"], True),
    (["-m", "x", "-am", "-n"], False),
    (["-m", "-am", "-m", "-n"], False),
    (["--", "-n"], False),
])
def test_commit_no_verify_skips_a_consumed_word(words, hit):
    assert gate._commit_no_verify(words) is hit


@pytest.mark.parametrize(("words", "hit"), [
    (["git", "commit", "-m", "-am", "--no-verify"], True),
    (["git", "commit", "--message", "--file", "--no-gpg-sign"], True),
    (["git", "commit", "-m", "x", "-am", "--no-verify"], False),
    (["git", "commit", "-m", "-am", "-m", "--no-verify"], False),
])
def test_git_words_bypass_skips_a_consumed_word(words, hit):
    assert gate._git_words_bypass(words) is hit
