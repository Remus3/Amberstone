"""S144-Q-154: prefix commands the stop gate did not read.

S144-Q-146 / S144-Q-150 read a launcher behind `nohup`, `nice`, `sudo`,
`timeout`, `xargs`, `doas`, ... with each tool's own options. Eight more
commands run a command and were not read at all, so `ionice -c 3 bash -c
'git commit -n'` was not counted (measured on the base, e5e8cbc4f; a bare
`ionice -c 3 git commit -n` WAS counted through its git word):

- util-linux `ionice [-c class] [-n level] [-t] command` (getopt
  `+n:c:p:P:u:tVh`; `-p` / `-P` / `-u` act on running processes and run
  nothing);
- util-linux `chrt [options] priority command` (getopt `+abdD:fiphmoP:T:rRvV`;
  a numeric priority word is skipped, `-p` / `-m` run nothing);
- util-linux `taskset [options] mask command` (getopt `+apchV`, no value
  options; the mask or cpu-list word is skipped, `-p` runs nothing);
- util-linux `flock [options] file command` and `flock [options] file -c
  string` (getopt `+sexnoFuw:E:hV?`; after the lock file, an exact `-c` /
  `--command` runs the next word through `$SHELL -c`);
- procps-ng `watch [options] command` (getopt `+bCced::ghq:n:prs:tvwx`):
  without `-x` it joins its words with spaces and runs them through `sh -c`
  (so `watch 'git commit -n'` runs a commit, and `watch bash -c 'git commit
  -n'` runs `bash -c git`, which commits nothing); with `-x` / `--exec` it
  runs the words as given;
- expect's `unbuffer [-p] program [args]`;
- util-linux `su [options] [-] [user]` (getopt `c:fg:G:lmpPs:hVw:`, which
  PERMUTES, so `su root -c '...'` is read too): `-c` / `--command` /
  `-C` / `--session-command` run a string through the target user's
  shell; `-`, `-l`, `--login` start in that user's home (placed None);
- util-linux `script [options] [file]` (getopt `ac:B:eE:fI:O:o:qm:T:t::Vh`,
  permuting): `-c` / `--command` runs a string through `sh -c`; the BSD
  form `script [-adkpqr] [-t time] [file [command ...]]` runs the words
  after the file;
- BSD xargs value options `-J replstr`, `-R replacements`, `-S replsize`
  (GNU xargs has none of the three, so reading them as value options only
  changes a command GNU xargs rejects).

Read from each tool's upstream usage / getopt string (util-linux 2.39,
procps-ng 4.0, expect 5.45, FreeBSD / macOS xargs and script): none of
these tools is installed on this box (Git Bash), so the readings are not
an execution measurement. The fix is EXTRA only and count-only: a command
counted before is still counted, the `git status` twins are not.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

TWIN = "bash -c 'git commit -n'"
SCRIPT_TWIN = "git commit -n"

# (command, the same command without its prefix, which HEAD counts)
PAIRS = [
    # ionice
    ("ionice -c 3 bash -c 'git commit -n'", TWIN),
    ("ionice -c3 -n7 bash -c 'git commit -n'", TWIN),
    ("ionice -c 2 -n 0 -t bash -c 'git commit -n'", TWIN),
    ("ionice --class 3 bash -c 'git commit -n'", TWIN),
    ("ionice --classdata=4 -c2 bash -c 'git commit -n'", TWIN),
    ("ionice -t bash -c 'git commit -n'", TWIN),
    ("ionice bash -c 'git commit -n'", TWIN),
    # chrt
    ("chrt 0 bash -c 'git commit -n'", TWIN),
    ("chrt -b 0 bash -c 'git commit -n'", TWIN),
    ("chrt -f 10 bash -c 'git commit -n'", TWIN),
    ("chrt -r -R 5 bash -c 'git commit -n'", TWIN),
    ("chrt --idle 0 bash -c 'git commit -n'", TWIN),
    ("chrt -d -T 1000 -P 2000 -D 2000 0 bash -c 'git commit -n'", TWIN),
    ("chrt --sched-runtime 1000 -d 0 bash -c 'git commit -n'", TWIN),
    ("chrt -o bash -c 'git commit -n'", TWIN),
    # taskset
    ("taskset 0x3 bash -c 'git commit -n'", TWIN),
    ("taskset -c 0-2 bash -c 'git commit -n'", TWIN),
    ("taskset --cpu-list 1,3 bash -c 'git commit -n'", TWIN),
    ("taskset -a 1 bash -c 'git commit -n'", TWIN),
    # flock, command words after the lock file
    ("flock /tmp/l bash -c 'git commit -n'", TWIN),
    ("flock -x /tmp/l bash -c 'git commit -n'", TWIN),
    ("flock -w 5 /tmp/l bash -c 'git commit -n'", TWIN),
    ("flock -nE 3 /tmp/l bash -c 'git commit -n'", TWIN),
    ("flock --timeout 5 /tmp/l bash -c 'git commit -n'", TWIN),
    ("flock --conflict-exit-code=9 -o /tmp/l bash -c 'git commit -n'", TWIN),
    ("flock 9 bash -c 'git commit -n'", TWIN),
    # unbuffer
    ("unbuffer bash -c 'git commit -n'", TWIN),
    ("unbuffer -p bash -c 'git commit -n'", TWIN),
    # watch -x runs the words as given
    ("watch -x bash -c 'git commit -n'", TWIN),
    ("watch -n 5 -x bash -c 'git commit -n'", TWIN),
    ("watch --exec bash -c 'git commit -n'", TWIN),
    ("watch -tx bash -c 'git commit -n'", TWIN),
    # BSD script: command words after the file
    ("script log.txt bash -c 'git commit -n'", TWIN),
    ("script -q /dev/null bash -c 'git commit -n'", TWIN),
    ("script -a -t 0 log.txt bash -c 'git commit -n'", TWIN),
    # BSD xargs value options
    ("xargs -J % bash -c 'git commit -n'", TWIN),
    ("xargs -R 2 -I {} bash -c 'git commit -n'", TWIN),
    ("xargs -S 255 -I {} bash -c 'git commit -n'", TWIN),
    ("xargs -0J % bash -c 'git commit -n'", TWIN),
    # chained with the earlier prefixes
    ("nice -n 5 ionice -c3 taskset 1 bash -c 'git commit -n'", TWIN),
    ("sudo -u root flock /tmp/l chrt 0 bash -c 'git commit -n'", TWIN),
]

# A string run through a shell (same directory)
SCRIPT_PAIRS = [
    ("flock /tmp/l -c 'git commit -n'", SCRIPT_TWIN),
    ("flock -x /tmp/l --command 'git push --no-verify'", "git push --no-verify"),
    ("flock -w 5 /tmp/l -c \"bash -c 'git commit -n'\"", TWIN),
    ("watch 'git commit -n'", SCRIPT_TWIN),
    ("watch -n 5 'git commit -n'", SCRIPT_TWIN),
    ("watch -d -n 1 'git commit -n'", SCRIPT_TWIN),
    ("watch --interval=2 \"git push --no-verify\"", "git push --no-verify"),
    ("watch 'git commit' '-n'", SCRIPT_TWIN),
    ("su -c 'git commit -n'", SCRIPT_TWIN),
    ("su root -c 'git commit -n'", SCRIPT_TWIN),
    ("su -c 'git commit -n' root", SCRIPT_TWIN),
    ("su --command='git commit -n' root", SCRIPT_TWIN),
    ("su --command 'git commit -n'", SCRIPT_TWIN),
    ("su -m -s /bin/bash -c 'git commit -n' root", SCRIPT_TWIN),
    ("su -C 'git commit -n' root", SCRIPT_TWIN),
    ("su --session-command='git commit -n' root", SCRIPT_TWIN),
    ("su -fc 'git commit -n'", SCRIPT_TWIN),
    ("script -c 'git commit -n' log.txt", SCRIPT_TWIN),
    ("script -q -c 'git commit -n' /dev/null", SCRIPT_TWIN),
    ("script --command 'git commit -n'", SCRIPT_TWIN),
    ("script log.txt -c 'git commit -n'", SCRIPT_TWIN),
    ("script -qc 'git commit -n' /dev/null", SCRIPT_TWIN),
    ("script --command='git push --no-verify'", "git push --no-verify"),
]

# su started as a login shell runs in the target user's home: placed None
MOVED = [
    "su - root -c 'git commit -n'",
    "su -l root -c 'git commit -n'",
    "su --login -c 'git commit -n' root",
    "su -lc 'git commit -n'",
    "su -c 'git commit -n' - root",
]

COUNTED = [command for command, _twin in PAIRS + SCRIPT_PAIRS]

NOT_COUNTED = [
    "ionice -c 3 bash -c 'git status'",
    "chrt 0 bash -c 'git log -n 3'",
    "taskset 1 bash -c 'git status -n'",
    "flock /tmp/l bash -c 'git status'",
    "flock /tmp/l -c 'git status'",
    "watch 'git status'",
    "watch -n 5 'git log -n 3'",
    "unbuffer bash -c 'git status'",
    "su -c 'git status' root",
    "su - root -c 'git log -n 3'",
    "script -c 'git status' /dev/null",
    "xargs -J % bash -c 'git status'",
    "watch bash -c 'git status'",
    # these run no command
    "ionice -p 42 bash -c 'git commit -n'",
    "ionice -c 3 -P 7 bash -c 'git commit -n'",
    "ionice --pid 42 bash -c 'git commit -n'",
    "chrt -p 0 42 bash -c 'git commit -n'",
    "chrt -m bash -c 'git commit -n'",
    "taskset -p 1 42 bash -c 'git commit -n'",
    "taskset --pid 1 42 bash -c 'git commit -n'",
    "flock --help /tmp/l bash -c 'git commit -n'",
    "su root",
    "su -l root",
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


@pytest.mark.parametrize("command", COUNTED + MOVED)
def test_audit_counts_the_shape(command):
    assert gate._has_bypass(command) is True
    assert "hook_bypass" in _audit_checks(command)


@pytest.mark.parametrize("command", COUNTED + MOVED)
def test_note_bypass_records_the_shape(command):
    assert _noted(command) == [command]
    assert _noted(command, name="powershell") == [command]


@pytest.mark.parametrize(("command", "twin"), PAIRS + SCRIPT_PAIRS)
def test_a_prefixed_launcher_is_placed_like_its_twin(command, twin, tmp_path):
    here = tmp_path.as_posix()
    assert gate._has_bypass(twin) is True
    assert set(gate._bypass_targets(command, here)) == \
        set(gate._bypass_targets(twin, here))
    away = (tmp_path / "away").as_posix()
    assert set(gate._bypass_targets(f"cd {away} && {command}", here)) == \
        set(gate._bypass_targets(f"cd {away} && {twin}", here))


@pytest.mark.parametrize("command", MOVED)
def test_a_login_su_is_placed_none(command, tmp_path):
    assert set(gate._bypass_targets(command, tmp_path.as_posix())) == {None}


@pytest.mark.parametrize("command", NOT_COUNTED)
def test_no_count_without_a_run_bypass(command, tmp_path):
    assert gate._has_bypass(command) is False
    assert "hook_bypass" not in _audit_checks(command)
    assert _noted(command) == []
    assert gate._bypass_targets(command, tmp_path.as_posix()) == []


@pytest.mark.parametrize(("command", "joined"), [
    ("watch bash -c 'git commit -n'", "bash -c git commit -n"),
    ("watch -n 5 bash -c 'git push --no-verify'", "bash -c git push --no-verify"),
])
def test_watch_without_exec_is_read_as_its_joined_text(command, joined):
    """Without -x watch runs `sh -c "bash -c git commit -n"` (its words
    joined with spaces), which is `bash -c git`: no commit. The gate reads
    exactly that joined text, and its git-word reading counts the same
    text typed directly (an over-count, the fail-closed direction), so the
    watch statement answers like the joined text, no more and no less."""
    assert gate._launcher_scripts(gate._tokens(command)) == [joined]
    assert gate._has_bypass(command) is gate._has_bypass(joined)


@pytest.mark.parametrize(("words", "expected"), [
    (["-c", "3", "bash"], (["bash"], False)),
    (["-p", "42"], ([], False)),
])
def test_prefix_unwrapped_ionice(words, expected):
    assert gate._prefix_unwrapped("ionice", words) == expected


@pytest.mark.parametrize(("name", "words", "expected"), [
    ("chrt", ["-f", "10", "bash"], ["bash"]),
    ("chrt", ["-o", "bash"], ["bash"]),
    ("taskset", ["-c", "0-2", "bash"], ["bash"]),
    ("flock", ["-w", "5", "/tmp/l", "bash"], ["bash"]),
    ("flock", ["/tmp/l", "-c", "git x"], ["sh", "-c", "git x"]),
    ("flock", ["/tmp/l", "-c"], []),
    ("flock", ["9"], []),
    ("watch", ["-n", "5", "git", "commit"], ["sh", "-c", "git commit"]),
    ("watch", ["-x", "git", "commit"], ["git", "commit"]),
    ("watch", ["-n", "5"], []),
    ("watch", ["--exec", "git", "commit"], ["git", "commit"]),
    ("watch", ["-n", "1", "--ex", "git", "commit"], ["git", "commit"]),
    ("watch", ["--differences=permanent", "x"], ["sh", "-c", "x"]),
    ("script", ["-t", "0", "log", "git", "x"], ["git", "x"]),
    ("script", ["-at0", "log", "git", "x"], ["git", "x"]),
    ("su", ["root", "-c", "git x"], ["sh", "-c", "git x"]),
    ("su", ["root"], []),
    ("script", ["-c", "git x", "log"], ["sh", "-c", "git x"]),
    ("script", ["log", "git", "x"], ["git", "x"]),
    ("script", ["log"], []),
    ("unbuffer", ["-p", "bash"], ["bash"]),
])
def test_prefix_unwrapped_words(name, words, expected):
    for full in (False, True):
        assert gate._prefix_unwrapped(name, words, full)[0] == expected


def test_watch_d_takes_an_optional_attached_value():
    """`watch -d::`: in `-dn` the `n` is -d's value, not -n (the FULL
    reading, as for xargs -e / -i); the plain reading is walked beside it."""
    assert gate._prefix_unwrapped("watch", ["-dn", "x", "y"], True)[0] == \
        ["sh", "-c", "x y"]
    assert gate._prefix_unwrapped("watch", ["-dn", "x", "y"])[0] == \
        ["sh", "-c", "y"]


@pytest.mark.parametrize("command", [
    "xargs -R bash -c 'git commit -n'",
    "xargs -J bash -c 'git push --no-verify'",
    "xargs -S bash -c 'git commit -n'",
    "xargs -0R sh -c 'git commit -n'",
    # verifier round 2: HEAD found these only through its FULL reading
    "xargs -R nice --adj 5 bash -c 'git commit -n -m x'",
    "xargs -J nice --adj 5 bash -c 'git commit -n -m x'",
    "xargs -S timeout --sig KILL 5 bash -c 'git commit -n -m x'",
    "xargs -J sudo -h host bash -c 'git push --no-verify origin main'",
    "xargs -J sudo --chd d bash -c 'git commit -n -m x'",
    "xargs -R sudo --login-class x bash -c 'git commit -n -m x'",
])
def test_a_bsd_xargs_value_letter_never_drops_a_count(command, tmp_path):
    """Verifier rounds 1-2: read in the plain reading, `-R` took `bash` as
    its value; read in the full one it took `nice` / `sudo`; either way a
    statement HEAD counted stopped counting. -J / -R / -S are values only
    in a THIRD reading (FULL_BSD), walked beside both (count-only)."""
    assert gate._has_bypass(command) is True
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


def test_only_the_third_reading_takes_a_bsd_xargs_value():
    words = ["-R", "2", "bash"]
    assert gate._prefix_unwrapped("xargs", words)[0] == ["2", "bash"]
    assert gate._prefix_unwrapped("xargs", words, True)[0] == ["2", "bash"]
    assert gate._prefix_unwrapped("xargs", words, gate.FULL_BSD)[0] == ["bash"]


@pytest.mark.parametrize("command", [
    "su -- root -lc 'git commit -n'",
    "su root -- -c 'git commit -n'",
    "su - root -- -xc 'git push --no-verify'",
])
def test_a_shell_cluster_after_the_su_user_is_read(command, tmp_path):
    """The words after the user go to the target user's shell, so a short
    cluster holding `c` there runs the next word (verifier round 1)."""
    assert gate._has_bypass(command) is True
    assert gate._bypass_targets(command, tmp_path.as_posix()) != []


def test_the_last_su_command_wins():
    """getopt keeps the last `-c` value; su runs that one."""
    words = ["-c", "git status", "-c", "git commit -n"]
    assert gate._prefix_unwrapped("su", words)[0] == ["sh", "-c", "git commit -n"]


def test_the_readings_are_extra_only():
    words = ["flock", "/tmp/l", "-c", "git commit -n"]
    assert gate._launcher_scripts(words) == ["git commit -n"]
    assert gate._launcher_scripts(words, extra=False) == []
