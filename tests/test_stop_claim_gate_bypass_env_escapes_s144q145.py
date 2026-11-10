"""S144-Q-145: an `env -S` string was not split the way env splits it.

GNU `env -S STRING` reads backslash escapes and quotes in STRING before it
splits it (measured on env 8.32, the one on this box): outside quotes `\\_`
is an argument separator (a run of them is one), inside double quotes it is
a space, `\\t` / `\\n` / `\\f` / `\\r` / `\\v` are that character inside an
argument, `\\\\` `\\'` `\\"` `\\#` `\\$` are literal, a single-quoted string
reads only `\\\\` and `\\'` (other known escapes stay as written), `#` at the
start of a word ends the string, `\\c` truncates it, and env REFUSES (exit
125) an unknown escape (in single quotes too), a trailing
backslash, an unterminated quote and a `$` that is not `${NAME}`. So
`env -S 'git\\_commit\\_-n'` runs `git commit -n`, and the stop gate missed
it at all three call sites (the audit Stop-time scan, `_note_bypass`,
`_bypass_targets`): S144-Q-143's splice read the string with the plain
tokenizer, which keeps `\\_` inside one word. A bash `env -S git\\ commit\\ -n`
(`\\ ` keeps the string one argument) was missed too: the gate's tokenizer
splits at that space, so env's string was `git\\` alone.

Count-only (the RM-698 decision, monotone by construction): the escaped
reading is ADDED to the S144-Q-143 one (`_env_split_words` returns both),
a string env refuses falls back to the plain tokenizer, and only with
`extra` on, so `_has_bypass(extra=False)` and `_placed(extra=False)` are
unchanged.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

ESCAPED = [
    "env -S 'git\\_commit\\_-n'",
    'env -S "git\\_commit\\_-n"',
    "env -S 'git commit\\_-n'",
    "env -S 'git\\_\\_commit\\_\\_-n'",
    "env -S 'git\\_push\\_--no-verify'",
    "env -S 'git\\_commit\\_-am\\_x\\_-n'",
    "env -S'git\\_commit\\_-n'",
    "env --split-string='git\\_commit\\_-n'",
    "env --split-string 'git\\_push\\_--no-verify'",
    "env -iS 'git\\_commit\\_-n'",
    "nohup env -S 'git\\_commit\\_-n'",
    "env -S 'git\\_commit\\_\"-n\"'",
    # a bash `\\ ` keeps env's string one argument (`env -S git\\ push\\
    # --no-verify` was already counted by the whole-text rule)
    "env -S git\\ commit\\ -n",
    "env -S git\\ commit\\ -m\\ x\\ -n",
    # a git word behind `\\_` has no `\\b` boundary in front of it
    "env -S 'FOO=1\\_git\\_commit\\_-n'",
    # nested, and through an assignment body and a launcher script
    "env -S 'env\\_-S\\_git\\\\_commit\\\\_-n'",
    "r=$(env -S 'git\\_commit\\_-n')",
    "bash -c \"env -S 'git\\_commit\\_-n'\"",
]
NOT_COUNTED = [
    "env -S 'git\\_status\\_-s'",
    "env -S 'git\\_commit\\_-m\\_-n'",
    # `#` at the start of a word ends env's string
    "env -S 'git\\_commit\\_#-n'",
    # `\\c` ends env's string
    "env -S 'git\\_commit\\_\\c-n'",
    # `\\t` is a TAB inside one argument, not a separator: env runs a program
    # named `git<TAB>commit`
    "env -S 'git\\tcommit\\t-n'",
    # single quotes inside the string keep `\\_` literal
    "env -S \"git\\_commit '\\_-n'\"",
]


# Same root, the launcher reader (_launcher_script through _unwrapped): a
# `bash -c` env -S splits out only with env's escapes, or a script whose
# `\\_` env turns into a space. Each is paired with its plainly spelled twin,
# which S144-Q-127 part 2 already counts.
LAUNCHER = [
    ("env -S 'bash\\_-c\\_\"git commit -n\"'", "env -S 'bash -c \"git commit -n\"'"),
    ("env -S 'bash -c \"git\\_commit\\_-n\"'", "env -S 'bash -c \"git commit -n\"'"),
    ("env -S 'sh\\_-c\\_\"git push --no-verify\"'",
     "env -S 'sh -c \"git push --no-verify\"'"),
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


@pytest.mark.parametrize("command", ESCAPED)
def test_the_old_rule_and_rm698_missed_the_shape(command, tmp_path):
    """Each shape is new, and extra=False still does not count or place it."""
    assert not gate._bypass_in_text(command)
    assert gate._has_bypass(command, extra=False) is False
    assert gate._placed(command, tmp_path.as_posix(), {}, 0, extra=False) == []


@pytest.mark.parametrize("command", ESCAPED)
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", ESCAPED)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", ESCAPED)
def test_the_walk_places_the_shape_none(command, tmp_path):
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


@pytest.mark.parametrize(("command", "twin"), LAUNCHER)
def test_a_launcher_in_an_escaped_split_counts_like_its_twin(command, twin, tmp_path):
    here = tmp_path.as_posix()
    assert gate._has_bypass(twin) is True
    assert gate._has_bypass(command, extra=False) is False
    assert gate._has_bypass(command) is True
    assert "hook_bypass" in _audit_checks(command)
    assert _noted(command) == [command]
    assert gate._bypass_targets(command, here) == gate._bypass_targets(twin, here)
    assert gate._placed(command, here, {}, 0, extra=False) == []


def test_launcher_scripts_keep_the_plain_reading():
    words = ["env", "-S", 'bash\\_-c\\_"git commit -n"']
    assert gate._launcher_scripts(words) == ["git commit -n"]
    assert gate._launcher_scripts(words, extra=False) == []
    plain = ["env", "-S", "bash -c 'git\\_x'"]
    assert gate._launcher_scripts(plain) == ["git\\_x"]
    assert gate._launcher_scripts(["bash", "-c", "git status"]) == ["git status"]


@pytest.mark.parametrize(("text", "words"), [
    ("git\\_commit\\_-n", ["git", "commit", "-n"]),
    ("a\\_\\_b", ["a", "b"]),
    ("a\\tb", ["a\tb"]),
    ('"a\\_b" \'c\\_d\' \'e\\\\f\' \'g\\\'h\'', ["a b", "c\\_d", "e\\f", "g'h"]),
    ('"a\\"b" "x\\_y\\ty"', ['a"b', "x y\ty"]),
    ("x\\#y \\$z", ["x#y", "$z"]),
    ("'x\\ty' 'x\\cy' 'x\\\"y'", ["x\\ty", "x\\cy", 'x\\"y']),
    ("a #b c", ["a"]),
    ("a\\cb c", ["a"]),
    ("''", [""]),
    ("a ${HOME} b", ["a", "${HOME}", "b"]),
    ("", []),
])
def test_env_split_string_reads_what_env_8_32_measured(text, words):
    assert gate._env_split_string(text) == words


@pytest.mark.parametrize("text", [
    "a\\qb", "a\\ b", "a\\", '"abc', "'abc", "a$b", '"a\\cb"', "a${b",
    # an unknown escape is refused inside single quotes too
    "'x\\qy'", "'a\\ b'", "'x\\'",
])
def test_env_split_string_refuses_what_env_refuses(text):
    """env exits 125 on each; the caller falls back to the plain tokenizer."""
    assert gate._env_split_string(text) is None


def test_split_words_keep_the_plain_reading_beside_the_escaped_one():
    """Count-only: a string env would read differently keeps its S144-Q-143
    reading too, and a refused string keeps only that reading."""
    assert gate._env_split_words(["env", "-S", "git\\_commit\\_-n"]) == [
        ["git\\_commit\\_-n"], ["git", "commit", "-n"]]
    assert gate._env_split_words(["env", "-S", "git commit -n"]) == [
        ["git", "commit", "-n"]]
    assert gate._env_split_words(["env", "-S", "git\\q commit"]) == [
        ["git\\q", "commit"]]
    assert gate._env_split_words(["env", "git", "commit"]) == []
