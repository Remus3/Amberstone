"""S144-Q-136: `env -C dir git ...` was placed at the caller's directory.

tools/stop_claim_gate.py places each hook-bypassing git statement at the
directory it acts on (`_bypass_targets`, read by `_bypass_hits_rc`).
`_git_target` honoured `git -C` but read nothing BEFORE the git word, so a
GNU `env -C dir` / `--chdir dir` wrapper that moves the git run was placed at
the caller's directory: `env -C <rc> git push --no-verify` run from outside
RC was not counted.

Now a leading wrapper that moves - `env -C` in any spelling, `env -S`, a
`wsl --cd` / `wsl ~` - places the statement None (fail closed), the row's
first acceptance option. Placing it at the `-C` directory (the second
option) was built and withdrawn after verifier rounds 1-2, and a narrower
git-word search after round 3: a repo can be named in more ways than the
walk reads (an earlier `export GIT_DIR=<rc>`, `env -C W nohup env
GIT_DIR=<rc> git ...`), and each such command was counted at HEAD and
missed. A placement here only moves to None; the walk counts less than
before only for commands no shell runs as a git bypass (verifier round 4).

Same root cause, two siblings:
- env's options are read as getopt reads them (`-iC dir`, `-Cdir`,
  `--ch dir`, and a `-S` string split into more arguments); `_env_unwrapped`
  read `-iC dir` / `--ch dir` as no move with `dir` as the command word and
  gave up on `-S`, so `env -iC dir bash -c 'git push --no-verify'` and
  `env -S "bash -c '...'"` were not counted at all;
- a GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR word before the git word points
  git at another repo, so `GIT_DIR=<rc>/.git git -C W commit --no-verify`
  is None, not W.
"""
from __future__ import annotations

import pytest

from tools import stop_claim_gate as gate

MOVED = [
    "env -C {d} git push --no-verify",
    "env -C{d} git push --no-verify",
    "env --chdir={d} git push --no-verify",
    "env --chdir {d} git push --no-verify",
    "env --ch {d} git push --no-verify",
    "env -i -C {d} git push --no-verify",
    "env -iC {d} git push --no-verify",
    "env -u X -C {d} git push --no-verify",
    "env -C {d} FOO=1 git push --no-verify",
    "FOO=1 env -C {d} git push --no-verify",
    "env env -C {d} git push --no-verify",
    "env -C {d} git commit -n -m x",
    "env -C {d} git -c core.hooksPath=/dev/null commit -m x",
    "env -C {d} git -C {d} push --no-verify",
    "env -C $D git push --no-verify",
    "env -C sub git push --no-verify",
    "env -S git push --no-verify",
    "env --split-string git push --no-verify",
    "wsl --cd {d} git push --no-verify",
    "wsl ~ git push --no-verify",
]
UNMOVED = [
    "env git push --no-verify",
    "env FOO=1 git push --no-verify",
    "env -i git push --no-verify",
    "env -u X git push --no-verify",
    "env -- git push --no-verify",
    "wsl git push --no-verify",
    "wsl -e git push --no-verify",
    "FOO=1 git push --no-verify",
]


@pytest.mark.parametrize("shape", MOVED)
def test_a_moving_wrapper_places_the_git_statement_none(shape, tmp_path):
    command = shape.format(d=(tmp_path / "other").as_posix())
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


@pytest.mark.parametrize("shape", UNMOVED)
def test_a_wrapper_that_does_not_move_keeps_the_callers_directory(shape, tmp_path):
    assert gate._bypass_targets(shape, tmp_path.as_posix()) == [tmp_path.as_posix()]


def test_env_chdir_into_rc_from_outside_counts(tmp_path):
    """The row's failure: run from outside RC, `env -C <rc>` committed to RC
    uncounted."""
    (tmp_path / "rc" / ".git").mkdir(parents=True)
    (tmp_path / "other" / ".git").mkdir(parents=True)
    rc = (tmp_path / "rc").as_posix()
    other = (tmp_path / "other").as_posix()
    rc_common = gate._git_common_dir(rc)
    assert rc_common is not None
    command = f"env -C {rc} git push --no-verify"
    assert gate._bypass_hits_rc(command, other, rc_common) is True
    assert gate._bypass_hits_rc("env git push --no-verify", other, rc_common) is False


@pytest.mark.parametrize("command", [
    "export GIT_DIR={rc}/.git; env -C {d} git commit --no-verify -m x",
    "$env:GIT_DIR='{rc}/.git'; env -C {d} git commit --no-verify -m x",
    "env -C {d} nohup env GIT_DIR={rc}/.git git commit --no-verify -m x",
    "env -C {d} -u git -C . git commit --no-verify",
    "export GIT_DIR={rc}/.git; env -u git git -C {d} commit --no-verify -m x",
    "export GIT_DIR={rc}/.git; X=/usr/bin/git git -C {d} commit --no-verify",
    "$env:GIT_DIR='{rc}/.git'; env -u git git -C {d} commit --no-verify -m x",
])
def test_verifier_found_rc_commits_still_count(command, tmp_path):
    """Verifier rounds 1-3: each runs git against RC in a real shell, and a
    placement at the `-C` directory (rounds 1-2) or a git-word search that
    skipped an option value (round 3) stopped counting it."""
    (tmp_path / "rc" / ".git").mkdir(parents=True)
    rc = (tmp_path / "rc").as_posix()
    rc_common = gate._git_common_dir(rc)
    command = command.format(rc=rc, d=(tmp_path / "away").as_posix())
    assert gate._bypass_hits_rc(command, rc, rc_common) is True


@pytest.mark.parametrize("shape", [
    "nohup env -C {rc} git push --no-verify",
    "time env -C {rc} git push --no-verify",
    "exec env -C {rc} git push --no-verify",
    "command env -C {rc} git push --no-verify",
    "! env -C {rc} git push --no-verify",
    "nice env -C {rc} git push --no-verify",
    "timeout 5 env -C {rc} git push --no-verify",
    "if env -C {rc} git push --no-verify; then :; fi",
    "for i in 1; do env -C {rc} git push --no-verify; done",
    "r=$(env -C {rc} git push --no-verify)",
    "r=`env -C {rc} git push --no-verify`",
    "echo $(env -C {rc} git push --no-verify)",
    "nohup /usr/bin/env.exe --chdir={rc} git push --no-verify",
    "nohup wsl --cd {rc} git push --no-verify",
])
def test_a_moving_env_after_another_word_still_counts(shape, tmp_path):
    """Verifier round 5: an `env -C` that is not the statement's first word
    was still placed at the caller's directory (outside RC here)."""
    (tmp_path / "rc" / ".git").mkdir(parents=True)
    (tmp_path / "other" / ".git").mkdir(parents=True)
    rc = (tmp_path / "rc").as_posix()
    rc_common = gate._git_common_dir(rc)
    command = shape.format(rc=rc)
    assert gate._bypass_hits_rc(command, (tmp_path / "other").as_posix(), rc_common) is True


def test_words_after_the_git_word_are_not_read_as_a_wrapper(tmp_path):
    away = (tmp_path / "away").as_posix()
    command = f"git -C {away} push --no-verify env -C x"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [away]


@pytest.mark.parametrize("shape", [
    "GIT_DIR={rc}/.git git -C {d} commit --no-verify",
    "GIT_WORK_TREE={rc} git -C {d} commit --no-verify",
    "git_dir={rc}/.git git -C {d} commit --no-verify",
    "env GIT_COMMON_DIR={rc}/.git git -C {d} commit --no-verify",
    "nohup env GIT_DIR={rc}/.git git -C {d} commit --no-verify",
])
def test_a_git_location_word_before_the_git_word_fails_closed(shape, tmp_path):
    """A GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR word before the git word
    points git at another repo, so `git -C` alone cannot place it."""
    command = shape.format(d=(tmp_path / "away").as_posix(),
                           rc=(tmp_path / "rc").as_posix())
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


def test_an_unrelated_variable_keeps_the_placement(tmp_path):
    away = (tmp_path / "away").as_posix()
    command = f"GIT_TRACE=1 env GIT_PAGER=cat git -C {away} push --no-verify"
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [away]


@pytest.mark.parametrize("shape", [
    "env -iC {d} bash -c 'git push --no-verify'",
    "env --ch {d} bash -c 'git push --no-verify'",
    "env -vC{d} sh -c 'git push --no-verify'",
])
def test_a_clustered_or_abbreviated_chdir_before_a_launcher_fails_closed(shape, tmp_path):
    """Sibling: the launcher path read `dir` as the command word and missed
    the script entirely; it is now counted and placed None (moved)."""
    command = shape.format(d=(tmp_path / "other").as_posix())
    assert gate._has_bypass(command)
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


@pytest.mark.parametrize("command", [
    "env -S \"bash -c 'git push --no-verify'\"",
    "env --split-string=\"sh -c 'git push --no-verify'\"",
    "env --s bash -c 'git push --no-verify'",
    "env -iS bash -c 'git push --no-verify'",
])
def test_a_split_string_launcher_is_counted(command, tmp_path):
    """Sibling: `_env_unwrapped` gave up on `-S`, so a launcher it splits
    was never read (and `--s`, an abbreviation, was read as a plain flag).
    With no `-C` the split script runs in the caller's directory."""
    assert gate._has_bypass(command)
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [tmp_path.as_posix()]


def test_a_chdir_inside_a_split_string_moves_the_launcher(tmp_path):
    away = (tmp_path / "away").as_posix()
    command = f"env -S \"-C {away} bash -c 'git push --no-verify'\""
    assert gate._has_bypass(command)
    assert gate._bypass_targets(command, tmp_path.as_posix()) == [None]


@pytest.mark.parametrize("rest, command, dirs, split", [
    (["git"], ["git"], [], False),
    (["-i", "git"], ["git"], [], False),
    (["-", "git"], ["git"], [], False),
    (["-C", "d", "git"], ["git"], ["d"], False),
    (["-Cd", "git"], ["git"], ["d"], False),
    (["-iC", "d", "git"], ["git"], ["d"], False),
    (["-iCd", "git"], ["git"], ["d"], False),
    (["--chdir=d", "git"], ["git"], ["d"], False),
    (["--chdir", "d", "git"], ["git"], ["d"], False),
    (["--ch", "d", "git"], ["git"], ["d"], False),
    (["-u", "X", "git"], ["git"], [], False),
    (["--unset=X", "git"], ["git"], [], False),
    (["--", "-C", "d"], ["-C", "d"], [], False),
    (["A=1", "git"], ["git"], [], False),
    (["-C", "a", "-C", "b", "B=2", "git"], ["git"], ["a", "b"], False),
    (["-S", "git push", "x"], ["git", "push", "x"], [], True),
    (["-iS", "git push"], ["git", "push"], [], True),
    (["--split-string=git push"], ["git", "push"], [], True),
    (["--sp", "git push"], ["git", "push"], [], True),
    (["-S", "-C d git"], ["git"], ["d"], True),
    (["-S"], [], [], True),
    # `-a` / `--argv0` takes no value here (env 8.32 rejects it; reading it
    # as argv0 would hide `bash`, which the older walk counted).
    (["-a", "bash", "-c", "s"], ["bash", "-c", "s"], [], False),
    (["--argv0", "bash"], ["bash"], [], False),
])
def test_env_options_are_read_as_getopt_reads_them(rest, command, dirs, split):
    assert gate._env_options(rest) == (command, dirs, split)
