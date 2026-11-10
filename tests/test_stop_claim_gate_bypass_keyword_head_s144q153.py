"""S144-Q-153: a launcher behind a shell keyword head was not counted.

bash runs the command after a reserved word that opens a statement: `then`,
`do`, `else`, `elif`, `if`, `while`, `until`, `!` (pipeline negation), `{`
(a group) and `(` (a subshell), and after `time` it may also read `!`. So
`if true; then bash -c 'git commit -n'; fi` runs a hook-bypassing commit.
The stop gate split the statement `then bash -c '...'` and read its first
word, `then`, as the command: no launcher, no count. A bare git statement
behind a keyword WAS counted (its git word is found anywhere), so only the
launcher, assignment and cd readings missed it.

Measured with GNU bash 5.2.37 (each echo below ran):
`if true; then bash -c "echo A"; fi`, `while true; do sh -c ...; break;
done`, `else bash -c ...`, `elif bash -c ...; then`, `until bash -c ...`,
`! bash -c ...`, `then { bash -c ...; }`, `time ! bash -c ...`,
`then (bash -c ...)`, `then r=$(bash -c ...)`, `then ! time bash -c ...`,
`then X=1 bash -c ...`, `then eval ...`.

Fix: `_keyword_unwrapped` drops those heads before the launcher read
(EXTRA only, so extra=False stays RM-698), `_assignment_command` reads an
assignment behind them, and a `cd` behind one is placed None (fail closed:
the branch may not run, so the directory is unknown). Count-only: a
statement that counted before still counts, and `git status` twins and an
echoed launcher stay uncounted.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

COUNTED = [
    "if true; then bash -c 'git commit -n'; fi",
    "while x; do sh -c 'git commit -n'; done",
    "if x; then :; else bash -c 'git push --no-verify'; fi",
    "if x; then :; elif bash -c 'git commit -n'; then :; fi",
    "if bash -c 'git commit -n'; then :; fi",
    "until bash -c 'git commit -n'; do :; done",
    "! bash -c 'git commit -n'",
    "if x; then ! bash -c 'git commit -n'; fi",
    "if x; then { bash -c 'git commit -n'; }; fi",
    "if x; then (bash -c 'git commit -n'); fi",
    "if x; then ( bash -c 'git commit -n' ); fi",
    "time ! bash -c 'git commit -n'",
    "if x; then ! time bash -c 'git commit -n'; fi",
    "if x; then X=1 bash -c 'git commit -n'; fi",
    "if x; then eval 'git commit -n'; fi",
    "if x; then nohup bash -c 'git commit -n'; fi",
    "if x; then r=$(bash -c 'git commit -n'); fi",
    "if x; then pwsh -Command 'git commit -n'; fi",
    "if x; then cmd /c 'git commit -n'; fi",
    "for f in a; do bash -c 'git commit --no-veri'; done",
    "if x; then env -C sub bash -c 'git commit -n'; fi",
    "do { bash -c 'git commit -n' } while ($x)",
    "Do { bash -c 'git commit -n' } Until ($x)",
]
NOT_COUNTED = [
    "if true; then bash -c 'git status -n'; fi",
    "while x; do sh -c 'git log -n 3'; done",
    "if x; then echo bash -c 'git commit -n'; fi",
    "if x; then r=$(bash -c 'git status'); fi",
    "if x; then nohup then bash -c 'git status -n'; fi",
    "then then",
    "! !",
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
def test_has_bypass_counts_a_launcher_behind_a_keyword(command):
    assert gate._has_bypass(command) is True


@pytest.mark.parametrize("command", COUNTED)
def test_audit_counts_a_launcher_behind_a_keyword(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED)
def test_note_bypass_records_a_launcher_behind_a_keyword(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", COUNTED)
def test_the_walk_places_a_launcher_behind_a_keyword(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_has_bypass_does_not_count_a_twin(command):
    assert gate._has_bypass(command) is False


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_a_twin(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_for_a_twin(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_a_launcher_behind_a_keyword_is_placed_in_the_cwd(tmp_path):
    """`then bash -c '...'` from the cwd is placed in the cwd, like the same
    launcher with no keyword in front of it."""
    here = tmp_path.as_posix()
    plain = gate._bypass_targets("bash -c 'git commit -n'", here)
    assert gate._bypass_targets("if x; then bash -c 'git commit -n'; fi", here) == plain
    assert None not in plain


@pytest.mark.parametrize("command", [
    "if x; then cd elsewhere; fi; git commit -n",
    "if x; then cd elsewhere; fi; bash -c 'git commit -n'",
    "while x; do pushd elsewhere; done; git commit -n",
    "if x; then ! cd elsewhere; fi; git commit -n",
    "if x; then popd; fi; git commit -n",
])
def test_a_cd_behind_a_keyword_places_later_statements_none(command, tmp_path):
    """The branch may or may not run, so the directory after it is unknown:
    fail closed (None), never the cwd and never the cd target."""
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


@pytest.mark.parametrize("head", [
    "if true; then cd $(git commit --no-verify -m x); fi",
    "if true; then popd $(git commit --no-verify); fi",
])
def test_a_bypass_inside_a_keyword_cd_is_never_dropped(head, tmp_path):
    """Verifier round 1: the substitution in `then cd $(...)` runs, and the
    statement used to be placed in the cwd; it must stay counted (None),
    not vanish behind the absolute `-C` target of the next statement."""
    other = (tmp_path / "other").as_posix()
    command = f"{head}; git -C {other} push --no-verify"
    targets = gate._bypass_targets(command, (tmp_path / "rc").as_posix())
    assert other in targets
    assert None in targets


def test_a_cd_with_no_keyword_still_moves(tmp_path):
    """Control: an unconditional cd is still followed (not made None)."""
    here = tmp_path.as_posix()
    targets = gate._bypass_targets("cd elsewhere; git commit -n", here)
    assert targets != [None] and None not in targets


@pytest.mark.parametrize(("words", "expected"), [
    (["then", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["if", "!", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["do", "{", "(", "bash", "-c", "x"], ["bash", "-c", "x"]),
    (["(bash", "-c", "x"], ["bash", "-c", "x"]),
    (["((bash", "-c", "x"], ["bash", "-c", "x"]),
    (["else", "(", "sh", "-c", "x"], ["sh", "-c", "x"]),
    (["bash", "-c", "then"], ["bash", "-c", "then"]),
    (["then"], []),
    (["git", "commit"], ["git", "commit"]),
])
def test_keyword_unwrapped(words, expected):
    assert gate._keyword_unwrapped(words) == expected


def test_only_a_bang_is_read_after_time():
    """`time ! cmd` is bash grammar; `nohup then cmd` runs a program named
    `then`, so no keyword other than `!` is dropped behind a prefix."""
    assert gate._unwrapped(["time", "!", "bash", "-c", "x"])[0] == ["bash", "-c", "x"]
    assert gate._unwrapped(["nohup", "then", "bash", "-c", "x"])[0] == \
        ["then", "bash", "-c", "x"]
