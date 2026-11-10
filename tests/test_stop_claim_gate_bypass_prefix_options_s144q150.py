"""S144-Q-150: prefix-command option gaps left after S144-Q-146.

S144-Q-146 read a launcher behind a prefix command (`nohup`, `nice`,
`sudo`, `timeout`, ...) with each tool's options, but only as written in
full: GNU getopt_long also takes any unambiguous ABBREVIATION of a long
option (`nice --adj 5`, `timeout --sig KILL 5`), and the value of such an
abbreviated option was read as the command, so `nice --adj 5 bash -c 'git
commit -n'` was not counted (measured on the base). `sudo -h host` (sudo
reads a bare word after `-h` as a remote host) was read as a flag, sudo's
`--auth-type` / `--login-class` were missing from its value options, and
three commands that run a command were not read at all: `eval` (runs its
joined words as a shell script), `xargs` (runs the command after its
options) and `doas` (OpenBSD's sudo).

The fix is EXTRA only and count-only (the RM-698 decision): the S144-Q-146
reading is kept as it was and a second, full getopt reading
(_prefix_unwrapped FULL: abbreviations with exact-match-first, sudo's
extra long value options, `sudo -h host`) is walked beside it, so nothing
counted before can stop counting. `xargs`, `doas` and `builtin` are new
prefix commands, `eval` a new launcher; `sudo -h host` / `--host` place
their statements None (the command runs on another host, fail closed).
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

TWIN = "bash -c 'git commit -n'"

# (command, the same command without its prefix, which S144-Q-127 counts)
PAIRS = [
    # GNU long-option abbreviations without `=`
    ("nice --adj 5 bash -c 'git commit -n'", TWIN),
    ("nice --a 5 bash -c 'git commit -n'", TWIN),
    ("timeout --sig KILL 5 bash -c 'git commit -n'", TWIN),
    ("timeout --kill 3 5 bash -c 'git commit -n'", TWIN),
    ("timeout --k 3 --s TERM 5 bash -c 'git commit -n'", TWIN),
    ("stdbuf --out L bash -c 'git commit -n'", TWIN),
    ("stdbuf --o L --e 0 bash -c 'git commit -n'", TWIN),
    ("time --out f.txt bash -c 'git commit -n'", TWIN),
    ("time --form %e bash -c 'git commit -n'", TWIN),
    ("sudo --us root bash -c 'git commit -n'", TWIN),
    ("sudo --gr wheel bash -c 'git commit -n'", TWIN),
    ("sudo --prom x bash -c 'git commit -n'", TWIN),
    # sudo value options S144-Q-146 did not list
    ("sudo --auth-type pam bash -c 'git commit -n'", TWIN),
    ("sudo --login-class staff bash -c 'git commit -n'", TWIN),
    ("sudo --auth pam bash -c 'git commit -n'", TWIN),
    # xargs and its options
    ("xargs bash -c 'git commit -n'", TWIN),
    ("xargs -0 bash -c 'git commit -n'", TWIN),
    ("xargs -0r -n 1 bash -c 'git commit -n'", TWIN),
    ("xargs -I {} bash -c 'git commit -n'", TWIN),
    ("xargs -d , -P 4 bash -c 'git commit -n'", TWIN),
    ("xargs -a list.txt bash -c 'git commit -n'", TWIN),
    ("xargs --max-args=1 bash -c 'git commit -n'", TWIN),
    ("xargs --max-args 1 bash -c 'git commit -n'", TWIN),
    ("xargs --delim , bash -c 'git commit -n'", TWIN),
    ("xargs -i bash -c 'git commit -n'", TWIN),
    # -e / -i / -l take an OPTIONAL attached value that ends the cluster
    # (verifier round 2: `n` / `d` here are values, not -n / -d)
    ("xargs -en bash -c 'git commit -n'", TWIN),
    ("xargs -es bash -c 'git commit -n'", TWIN),
    ("xargs -id bash -c 'git commit -n'", TWIN),
    ("xargs -iI bash -c 'git commit -n'", TWIN),
    ("xargs -0l1 bash -c 'git commit -n'", TWIN),
    ("echo a | xargs -en bash -c 'git commit -n'", "echo a | " + TWIN),
    ("xargs -- bash -c 'git commit -n'", TWIN),
    ("echo a | xargs -0 bash -c 'git commit -n'", "echo a | " + TWIN),
    # doas and its options
    ("doas bash -c 'git commit -n'", TWIN),
    ("doas -u root bash -c 'git commit -n'", TWIN),
    ("doas -n -a bsdauth bash -c 'git commit -n'", TWIN),
    ("doas -nu root bash -c 'git commit -n'", TWIN),
    # bash's builtin in front of a builtin that runs a command
    ("builtin exec bash -c 'git commit -n'", TWIN),
    # chained with the S144-Q-146 prefixes
    ("nohup xargs -0 nice --adj 5 bash -c 'git commit -n'", TWIN),
    ("doas nice --adj 5 bash -c 'git commit -n'", TWIN),
]

# eval runs its joined words as a script in the same shell (same directory)
EVAL_PAIRS = [
    ("eval 'git commit -n'", "git commit -n"),
    ('eval "git push --no-verify"', "git push --no-verify"),
    # already counted by HEAD through its git word (extra=True): kept for
    # the placement check only; so are `sudo --host remote` / `--host=` and
    # MOVED_DIRECT, which HEAD counted but placed at the caller's cwd
    ("eval 'git' 'commit' '-n'", "git commit -n"),
    ("eval -- 'git commit -n'", "git commit -n"),
    ("eval \"bash -c 'git commit -n'\"", TWIN),
    ("eval -- \"bash -c 'git commit -n'\"", TWIN),
    ("builtin eval 'git commit -n'", "git commit -n"),
]

# A remote host: placed None (fail closed), never at the caller's cwd.
MOVED = [
    "sudo -h host bash -c 'git commit -n'",
    "sudo -Eh host bash -c 'git commit -n'",
    # sudo declares -h with an OPTIONAL attached argument (verifier round 1)
    "sudo -hhost bash -c 'git commit -n'",
    "sudo -hlocalhost bash -c 'git commit -n'",
    "sudo -uroot -hhost bash -c 'git commit -n'",
    "sudo -h=host bash -c 'git commit -n'",
    "sudo --host remote bash -c 'git commit -n'",
    "sudo --host=remote bash -c 'git commit -n'",
    "sudo --ho remote bash -c 'git commit -n'",
    # an abbreviated moving option
    "sudo --chd /tmp bash -c 'git commit -n'",
    "sudo --chr /jail bash -c 'git commit -n'",
]

MOVED_DIRECT = [
    "sudo --chd /tmp git commit -n",
    "sudo -h host git commit -n",
]

COUNTED = [command for command, _twin in PAIRS + EVAL_PAIRS]

NOT_COUNTED = [
    "nice --adj 5 bash -c 'git status'",
    "timeout --sig KILL 5 bash -c 'git log -n 3'",
    "xargs -0 bash -c 'git status'",
    "xargs -n 1 git log",
    "doas -u root bash -c 'git status'",
    "eval 'git status'",
    "eval 'git log -n 3'",
    'eval "git commit -m -n"',
    "sudo -h host bash -c 'git status'",
    # these run nothing
    "xargs --help bash -c 'git commit -n'",
    "xargs --version bash -c 'git commit -n'",
    "doas -C /etc/doas.conf bash -c 'git commit -n'",
    "doas -L bash -c 'git commit -n'",
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


@pytest.mark.parametrize(("command", "twin"), PAIRS + EVAL_PAIRS)
def test_a_prefixed_launcher_is_placed_like_its_twin(command, twin, tmp_path):
    here = tmp_path.as_posix()
    assert gate._has_bypass(twin) is True
    assert set(gate._bypass_targets(command, here)) == \
        set(gate._bypass_targets(twin, here))
    away = (tmp_path / "away").as_posix()
    assert set(gate._bypass_targets(f"cd {away} && {command}", here)) == \
        set(gate._bypass_targets(f"cd {away} && {twin}", here))


@pytest.mark.parametrize("command", MOVED + MOVED_DIRECT)
def test_a_remote_or_moving_prefix_is_placed_none(command, tmp_path):
    assert set(gate._bypass_targets(command, tmp_path.as_posix())) == {None}


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_count_without_a_run_bypass(command, tmp_path):
    assert gate._has_bypass(command) is False
    assert "hook_bypass" not in _audit_checks(command)
    assert _noted(command) == []
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


def test_the_full_reading_is_extra_only_and_keeps_the_plain_one():
    words = ["nice", "--adj", "5", "bash", "-c", "git commit -n"]
    assert gate._launcher_scripts(words) == ["git commit -n"]
    assert gate._launcher_scripts(words, extra=False) == []
    # an exact long flag that is also a prefix of a value option: the plain
    # reading (login, no value) is kept beside the full one
    login = ["sudo", "--login", "bash", "-c", "git status"]
    scripts = gate._launcher_scripts(login)
    assert len(scripts) == 1 and scripts[0].endswith("&& git status")


def test_prefix_unwrapped_full_reading():
    rest = ["--sig", "KILL", "5", "bash", "-c", "x"]
    assert gate._prefix_unwrapped("timeout", rest)[0] == ["5", "bash", "-c", "x"]
    assert gate._prefix_unwrapped("timeout", rest, full=True) == (["bash", "-c", "x"], False)
    # exact match first: `--login` is sudo's login flag, not login-class
    assert gate._prefix_unwrapped("sudo", ["--login", "bash"], full=True) == (["bash"], True)
    assert gate._prefix_unwrapped("sudo", ["-h", "host", "bash"], full=True) == (["bash"], True)
    # a dash word or an assignment after -h is not a host
    assert gate._prefix_unwrapped("sudo", ["-h", "-u", "x", "bash"], full=True)[0] == ["bash"]
    assert gate._prefix_unwrapped("sudo", ["-h", "A=1", "bash"], full=True)[0] == ["bash"]
    assert gate._prefix_unwrapped("xargs", ["--help", "bash"]) == ([], False)
    assert gate._prefix_unwrapped("doas", ["-C", "f", "bash"]) == ([], False)


def test_wrapper_moves_reads_the_full_reading():
    assert gate._wrapper_moves(["sudo", "--chd", "/x"]) is True
    assert gate._wrapper_moves(["sudo", "-h", "host"]) is True
    assert gate._wrapper_moves(["sudo", "--us", "root"]) is False
    assert gate._wrapper_moves(["xargs", "-0"]) is False
