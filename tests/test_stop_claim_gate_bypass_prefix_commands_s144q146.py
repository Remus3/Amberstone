"""S144-Q-146: a launcher behind a prefix command was not read.

`nohup bash -c 'git push --no-verify'` runs the quoted script, but the stop
gate's launcher reader (`_launcher_script` through `_unwrapped`) read only a
LEADING launcher, after `env` / `wsl` wrappers and bash `NAME=VALUE` words,
so the script was never walked and all three call sites (the audit
Stop-time scan, `_note_bypass`, `_bypass_targets`) missed it. The prefix
commands read now (EXTRA only): `nohup`, `time` (bash keyword and GNU
time), `nice`, `sudo`, `stdbuf`, `timeout`, and the same-root shell
builtins `exec` / `command`, plus `setsid`, each with its own options read
(a value option skips its value, `timeout` skips its DURATION).

Count-only (the RM-698 decision): `_has_bypass(extra=False)` is unchanged
and so is `_placed(extra=False)` for a prefixed launcher (only a moving
sudo before a plain git word turns a placement into None there, which
counts more), a prefix that runs nothing
(`command -v`, `sudo -l`, `sudo -e`) reads as no launcher, and a prefix
that moves the command (`sudo -D dir`, `sudo --chdir`, `sudo -i`,
`sudo -R`) places its statements None (fail closed), in a launcher script
and before a plain git word (`_wrapper_moves`) alike.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

# (command, the same command without its prefix, which S144-Q-127 counts)
PAIRS = [
    ("nohup bash -c 'git push --no-verify'", "bash -c 'git push --no-verify'"),
    ("nohup bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nohup -- bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nohup /usr/bin/bash -c 'git commit -n'", "/usr/bin/bash -c 'git commit -n'"),
    ("nohup pwsh -Command 'git commit -n'", "pwsh -Command 'git commit -n'"),
    ("time bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("time -p bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("/usr/bin/time -v bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("time -o out.txt bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("time -f %e bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("time FOO=1 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nice bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nice -n 5 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nice -n -5 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nice -n5 sh -c 'git commit -n'", "sh -c 'git commit -n'"),
    ("nice -10 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nice --adjustment=5 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nice --adjustment 5 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo -u root -E bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo -Eu root bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo --user=root bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo --user root bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo FOO=1 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo -- bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("sudo -c login -a pam bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("stdbuf -oL bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("stdbuf -o L -e 0 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("stdbuf --output=L bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("timeout 10 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("timeout -k 5 10 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("timeout --signal=KILL 10s bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("timeout --foreground -s TERM 1m bash -c 'git commit -n'",
     "bash -c 'git commit -n'"),
    ("exec bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("exec -a name bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("exec -cl bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("command bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("command -p bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("setsid -f bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    # chained prefixes, and prefixes mixed with env / NAME=VALUE
    ("nohup nice -n 5 timeout 9 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("FOO=1 nohup bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("nohup env FOO=1 bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("env nohup bash -c 'git commit -n'", "bash -c 'git commit -n'"),
    ("time env -S 'bash -c \"git push --no-verify\"'",
     "env -S 'bash -c \"git push --no-verify\"'"),
    ("sudo cmd /c 'git commit -n'", "cmd /c 'git commit -n'"),
    # through an assignment body, a launcher script and a later statement
    ("r=$(nohup bash -c 'git commit -n')", "r=$(bash -c 'git commit -n')"),
    ("bash -c \"nohup sh -c 'git commit -n'\"", "bash -c \"sh -c 'git commit -n'\""),
    ("echo hi; nohup bash -c 'git commit -n'", "echo hi; bash -c 'git commit -n'"),
]
COUNTED = [command for command, _twin in PAIRS]

# Prefixes that move the command: placed None, never at the caller's cwd.
MOVED = [
    "sudo -D /tmp bash -c 'git commit -n'",
    "sudo -D/tmp bash -c 'git commit -n'",
    "sudo --chdir=/tmp bash -c 'git commit -n'",
    "sudo --chdir /tmp bash -c 'git commit -n'",
    "sudo -i bash -c 'git commit -n'",
    "sudo --login bash -c 'git commit -n'",
    "sudo -R /jail bash -c 'git commit -n'",
    "nohup sudo -iu root bash -c 'git commit -n'",
]

# The same moving prefix in front of a plain git word (_wrapper_moves).
MOVED_DIRECT = [
    "sudo -D /tmp git commit -n",
    "sudo --chdir=/tmp git push --no-verify",
    "sudo -i git commit -n",
    "nohup sudo -D /tmp git commit -n",
]

NOT_COUNTED = [
    "nohup bash -c 'git status'",
    "nice -n 5 bash -c 'git status'",
    "timeout 10 bash -c 'git log -n 3'",
    "time bash -c 'git commit -m -n'",
    # these prefixes run nothing
    "command -v bash -c 'git commit -n'",
    "command -V bash -c 'git commit -n'",
    "sudo -l bash -c 'git commit -n'",
    "sudo -e bash -c 'git commit -n'",
    "sudo --list bash -c 'git commit -n'",
    # nohup runs a program literally named `FOO=1`
    "nohup FOO=1 bash -c 'git commit -n'",
]


def _audit_checks(command):
    ev = {"texts": [], "bash": [command], "edited": [], "runs": [],
          "agent_results": []}
    return {f["check"] for f in gate.audit(ev)}


def _noted(command, name="bash"):
    found = {"bypass": []}
    gate._note_bypass(found, ("toolu_x", name, {"command": command}), None)
    return [c for c, _cwd, _tid in found["bypass"]]


@pytest.mark.parametrize("command", COUNTED + MOVED)
def test_the_old_rule_and_rm698_missed_the_shape(command, tmp_path):
    """Each shape is new, and extra=False still does not count or place it."""
    assert not gate._bypass_in_text(command)
    assert gate._has_bypass(command, extra=False) is False
    assert gate._placed(command, tmp_path.as_posix(), {}, 0, extra=False) == []


@pytest.mark.parametrize("command", COUNTED + MOVED + MOVED_DIRECT)
def test_audit_counts_the_shape(command):
    assert gate._has_bypass(command) is True
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED + MOVED + MOVED_DIRECT)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize(("command", "twin"), PAIRS)
def test_a_prefixed_launcher_is_placed_like_its_twin(command, twin, tmp_path):
    """Compared as sets: `r=$(nohup bash -c ...)` is also read as a
    `NAME=VALUE` word in front of `bash`, so it is placed twice, at the
    same directory."""
    here = tmp_path.as_posix()
    assert gate._has_bypass(twin) is True
    assert set(gate._bypass_targets(command, here)) == \
        set(gate._bypass_targets(twin, here))
    away = (tmp_path / "away").as_posix()
    moved = f"cd {away} && {command}"
    assert set(gate._bypass_targets(moved, here)) == \
        set(gate._bypass_targets(f"cd {away} && {twin}", here))


@pytest.mark.parametrize("command", MOVED + MOVED_DIRECT)
def test_a_moving_prefix_is_placed_none(command, tmp_path):
    here = tmp_path.as_posix()
    assert set(gate._bypass_targets(command, here)) == {None}


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_count_without_a_run_bypass(command, tmp_path):
    assert gate._has_bypass(command) is False
    assert "hook_bypass" not in _audit_checks(command)
    assert _noted(command) == []
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_launcher_scripts_read_through_prefixes_with_extra_only():
    words = ["nohup", "nice", "-n", "5", "bash", "-c", "git commit -n"]
    assert gate._launcher_scripts(words) == ["git commit -n"]
    assert gate._launcher_scripts(words, extra=False) == []
    assert gate._launcher_scripts(["command", "-v", "bash", "-c", "x"]) == []
    assert gate._launcher_scripts(["timeout", "10"]) == []
    assert gate._launcher_scripts(["nohup"]) == []


def test_a_moving_prefix_marks_the_script_moved():
    scripts = gate._launcher_scripts(["sudo", "-D", "/x", "bash", "-c", "git status"])
    assert len(scripts) == 1
    assert scripts[0].startswith("cd ") and scripts[0].endswith("&& git status")
    plain = gate._launcher_scripts(["sudo", "-u", "x", "bash", "-c", "git status"])
    assert plain == ["git status"]


def test_wrapper_moves_reads_sudo_only_when_it_moves():
    assert gate._wrapper_moves(["sudo", "-D", "/x"]) is True
    assert gate._wrapper_moves(["sudo", "-i"]) is True
    assert gate._wrapper_moves(["sudo", "-u", "root"]) is False
    assert gate._wrapper_moves(["nohup", "nice"]) is False
