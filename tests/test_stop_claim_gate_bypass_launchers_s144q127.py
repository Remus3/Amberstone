"""S144-Q-127 part 2: launcher shapes that hid a hook bypass from the stop gate.

tools/stop_claim_gate.py judges a quoted launcher script (`bash -c '...'`,
`pwsh -Command "..."`) as a nested command (RM-698), but `_launcher_script`
knew only a bare bash / sh / zsh / dash / pwsh / powershell head with short
options before `-c`. Each shape below runs `git push --no-verify` (or
`git commit -n`) through a launcher it did not recognise, so the quoted
script stripped to nothing and the bypass was not counted at any of the three
call sites (the audit Stop-time scan, `_note_bypass`, `_bypass_targets`):

- a wrapper in front of the shell: `env [NAME=x] bash -c`, `wsl -e bash -c`,
  `wsl --cd /x bash -c`, `env -C dir bash -c`;
- a bash long option that takes a value: `bash --rcfile x -c`,
  `bash --init-file x -c`;
- cmd.exe: `cmd /c "..."`, `cmd /s /c "..."`, `cmd //c "..."` (Git Bash);
- PowerShell `iex '...'` / `Invoke-Expression -Command "..."`.

Additive only (the RM-698 decision): the new launchers are judged only when
`extra` is on, so `_has_bypass(extra=False)` is still RM-698 exactly. A
wrapper that changes directory (`env -C`, `wsl --cd`, `wsl ~`) leaves the
script's directory unknown, so its statements are placed None (fail closed).
Still missed, filed under the same id: a flag from a QUOTED assignment, a git
call inside a quoted assignment, `Start-Process -ArgumentList`,
`-EncodedCommand`, an escaped quote inside a launcher body.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

LAUNCHED = [
    "env bash -c 'git push --no-verify'",
    "env FOO=1 BAR=2 bash -c 'git push --no-verify'",
    "env -i bash -c 'git push --no-verify'",
    "env -u HOME bash -c 'git push --no-verify'",
    "/usr/bin/env -- sh -c 'git push --no-verify'",
    "env pwsh -Command 'git push --no-verify'",
    "wsl -e bash -c 'git push --no-verify'",
    "wsl --exec bash -c 'git push --no-verify'",
    "wsl.exe -d Ubuntu -u root bash -c 'git push --no-verify'",
    "wsl -- bash -c 'git push --no-verify'",
    "wsl bash -c 'git commit -n -m x'",
    "env FOO=1 wsl -e bash -c 'git push --no-verify'",
    "bash --rcfile x -c 'git push --no-verify'",
    "bash --init-file x -c 'git push --no-verify'",
    "bash --norc --rcfile x -lc 'git push --no-verify'",
    'cmd /c "git push --no-verify"',
    'cmd /C "git push --no-verify"',
    'cmd.exe /s /c "git push --no-verify"',
    'cmd //c "git push --no-verify"',
    'cmd /k "git push --no-verify"',
    'cmd /c "cd sub && git commit -n -m x"',
    "iex 'git push --no-verify'",
    'Invoke-Expression "git push --no-verify"',
    "Invoke-Expression -Command 'git push --no-verify'",
    "iex -C 'git commit -n -m x'",
    "bash -c \"cmd /c 'git push --no-verify'\"",
]
MOVED = [
    "env -C {d} bash -c 'git push --no-verify'",
    "env --chdir={d} bash -c 'git push --no-verify'",
    "env --chdir {d} bash -c 'git push --no-verify'",
    "wsl --cd {d} bash -c 'git push --no-verify'",
    "wsl ~ -e bash -c 'git push --no-verify'",
]
NOT_COUNTED = [
    "env bash -c 'git status'",
    "env FOO=--no-verify bash -c 'git status'",
    "wsl -e bash -c 'echo --no-verify'; git status",
    "bash --rcfile x -c 'git push'",
    'cmd /c "git push"',
    'cmd /c "echo --no-verify" && git status',
    "iex 'git commit -m x'",
    "iex 'echo --no-verify'; git status",
    "Invoke-Expression 'git log -n 5'",
    "env bash -c 'echo -n x'; git status",
    # A single-quoted `$(...)` is a literal string in bash and PowerShell.
    "x='$(git push --no-verify)'",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


@pytest.mark.parametrize("command", LAUNCHED)
def test_the_old_rule_and_rm698_missed_the_shape(command):
    """Each shape is new: neither the old rule nor RM-698 counted it."""
    assert not gate._bypass_in_text(command)
    assert gate._has_bypass(command, extra=False) is False


@pytest.mark.parametrize("command", LAUNCHED)
def test_audit_counts_the_shape(command):
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", LAUNCHED)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize("command", LAUNCHED)
def test_the_shape_has_a_target(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_audit_does_not_count_a_launcher_without_a_bypass(command):
    assert "hook_bypass" not in _audit_checks(command)


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_note_bypass_does_not_record_a_launcher_without_a_bypass(command):
    assert _noted(command) == []


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_target_without_a_bypass(command, tmp_path):
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_a_wrapped_launcher_is_placed_where_it_runs(tmp_path):
    command = "env FOO=1 bash -c 'git push --no-verify'"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [tmp_path.as_posix()]


def test_a_cmd_script_is_placed_by_its_own_cd(tmp_path):
    inner = (tmp_path / "inner").as_posix()
    command = f'cmd /c "cd {inner} && git push --no-verify"'
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner]


def test_an_iex_script_is_placed_by_the_cd_before_it(tmp_path):
    inner = (tmp_path / "inner").as_posix()
    command = f"cd {inner}; iex 'git push --no-verify'"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [inner]


@pytest.mark.parametrize("shape", MOVED)
def test_a_wrapper_that_moves_leaves_the_script_unplaced(shape, tmp_path):
    """`env -C`, `wsl --cd` and `wsl ~` run the script somewhere this walk
    cannot place, so the statement fails closed (None hits RC)."""
    command = shape.format(d=(tmp_path / "elsewhere").as_posix())
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]
    assert gate._bypass_hits_rc(command, tmp_path.as_posix(),
                                gate._git_common_dir(gate.ROOT))


def test_a_wrapped_bypass_outside_rc_is_placed_outside(tmp_path):
    """No RM-698 count to keep, so the wrapped statement alone places it."""
    out = (tmp_path / "out").as_posix()
    rc = gate._git_common_dir(gate.ROOT)
    assert rc is not None
    command = f"cd {out} && env bash -c 'git push --no-verify'"
    assert gate._bypass_targets(command, gate.ROOT.as_posix()) == [out]
    assert not gate._bypass_hits_rc(command, gate.ROOT.as_posix(), rc)


def test_a_rcfile_value_that_looks_like_an_option_keeps_the_old_reading():
    """`bash --rcfile -c 'x'` was read as `-c 'x'` before; reading `-c` as
    the rcfile value would count LESS, so a dash word is never a value."""
    command = "bash --rcfile -c 'git push --no-verify'"
    assert gate._has_bypass(command, extra=False)
    assert gate._has_bypass(command)


@pytest.mark.parametrize("words, script", [
    (["env", "FOO=1", "bash", "-c", "s"], "s"),
    (["wsl", "-e", "sh", "-c", "s"], "s"),
    (["bash", "--rcfile", "x", "-c", "s"], "s"),
    (["cmd", "/s", "/c", "a", "b"], "a b"),
    (["iex", "a b"], "a b"),
    (["Invoke-Expression", "-Command", "a"], "a"),
    (["cmd"], None),
    (["cmd", "/q"], None),
    (["iex"], None),
    (["env"], None),
    (["env", "FOO=1"], None),
    (["wsl"], None),
    (["env", "git", "push"], None),
])
def test_launcher_script_reads_the_new_heads(words, script):
    assert gate._launcher_script(words) == script


@pytest.mark.parametrize("words", [
    ["env", "bash", "-c", "s"],
    ["wsl", "-e", "bash", "-c", "s"],
    ["bash", "--rcfile", "x", "-c", "s"],
    ["cmd", "/c", "s"],
    ["iex", "s"],
])
def test_launcher_script_without_extra_is_rm698_exactly(words):
    assert gate._launcher_script(words, extra=False) is None
