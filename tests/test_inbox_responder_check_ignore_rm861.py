"""RM-861 (tools/inbox_responder_runner.py site): the dry report's export check reads paths as themselves.

`_export_ignored_paths` is the dry-cycle report's one-process form of the
`export_is_clean` oracle: it feeds every exported path to
`git check-ignore --stdin` and reports the ignored ones. It ran without `-z`,
so under git's default core.quotePath:

- an ignored non-ASCII path came back C-quoted (`"d\\303\\251.log"`), and the
  report's `ignored_paths=` detail named an escape string, not the file;
- the input was newline-separated, so a path carrying a newline was checked
  as two paths (one of which may not exist), and a path opening with `"` was
  read as a C-quoted line (git 2.53: `fatal: line is badly quoted`, which
  ends the whole batch) - neither is the question `export_is_clean` asks with
  `check-ignore -q -- <path>`.

Fix: `check-ignore -z --stdin`, NUL-separated both ways, output decoded UTF-8.

Checked and NOT affected (the measure path, `tools/inbox_responder_exec.py`):
measure stdout is bytes run through `scrub_output`, which escapes every byte
above 0x7E as `\\xNN` before any decode, so a quoted and an unquoted path both
reach the note as deterministic 7-bit ASCII; no locale decode, no path parse.
Pinned below so a later decode-first change reopens it.

Every repo here is a throwaway under tmp_path with git's global config pinned
to an empty file, the system config off and `GIT_CONFIG_COUNT` cleared, so no
host-wide setting decides the result. Source stays ASCII: every non-ASCII probe
is built with chr().
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.inbox_responder_exec as exec_mod  # noqa: E402
import tools.inbox_responder_runner as runner  # noqa: E402
from tools.inbox_responder_procs import ProcResult  # noqa: E402

_NAME = "rm861-d" + chr(0x00E9) + chr(0x0101) + ".log"


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in list(os.environ):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)
    return dict(os.environ)


def _repo(tmp_path: Path, env: dict) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "."], ["config", "core.quotepath", "true"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
    (repo / ".gitignore").write_bytes(b"*.log\n")
    return repo


def _export(tmp_path: Path, names) -> Path:
    export = tmp_path / "export"
    export.mkdir()
    for name in names:
        (export / name).write_bytes(b"x\n")
    return export


def _ignored(repo: Path, export: Path, env: dict) -> list:
    config = runner.RunnerConfig()
    config.git_exe = "git"
    return runner._export_ignored_paths(config, export, repo, runner._dry_proc_runner(env))


def test_git_really_quotes_a_non_ascii_check_ignore_path_here(tmp_path, git_env):
    """Control: without `-z`, this repo's git C-quotes the name the fix must read raw."""
    repo = _repo(tmp_path, git_env)
    out = subprocess.run(["git", "check-ignore", "--stdin"], cwd=repo, env=git_env,
                         input=(_NAME + "\n").encode("utf-8"), capture_output=True, check=True)
    assert out.stdout.startswith(b'"'), out.stdout


def test_a_non_ascii_ignored_export_path_reads_as_itself(tmp_path, git_env):
    repo = _repo(tmp_path, git_env)
    export = _export(tmp_path, [_NAME, "keep.txt"])
    assert _ignored(repo, export, git_env) == [_NAME]


def test_ascii_ignored_paths_are_all_reported_and_a_clean_export_is_empty(tmp_path, git_env):
    repo = _repo(tmp_path, git_env)
    export = _export(tmp_path, ["a.log", "b.log", "keep.txt"])
    assert _ignored(repo, export, git_env) == ["a.log", "b.log"]
    (export / "a.log").unlink()
    (export / "b.log").unlink()
    assert _ignored(repo, export, git_env) == []


@pytest.mark.skipif(os.name == "nt", reason="NTFS refuses a newline or a quote in a file name")
@pytest.mark.parametrize("name", ["two\nlines.log", '"quoted.log'])
def test_a_name_git_would_split_or_unquote_is_checked_whole(tmp_path, git_env, name):
    repo = _repo(tmp_path, git_env)
    export = _export(tmp_path, [name])
    assert _ignored(repo, export, git_env) == [name]


def test_the_check_ignore_argv_is_nul_separated_both_ways(tmp_path):
    seen = []

    def fake(argv, *, cwd, stdin_bytes, timeout_s):
        seen.append((list(argv), stdin_bytes))
        return ProcResult(exit_code=1, stdout=b"", stderr=b"", timed_out=False,
                          survived_kill=False, kill_skipped=False, wall_ms=1, exc=None)

    export = _export(tmp_path, ["a.txt", "b.txt"])
    config = runner.RunnerConfig()
    config.git_exe = "git"
    assert runner._export_ignored_paths(config, export, tmp_path, fake) == []
    (argv, stdin_bytes), = seen
    assert argv[1:] == ["check-ignore", "-z", "--stdin"]
    assert stdin_bytes == b"a.txt\0b.txt\0"


def test_measure_output_with_a_quoted_or_raw_path_is_ascii_either_way():
    """Not-affected pin for the measure path: no decode precedes the byte escape."""
    raw = _NAME.encode("utf-8")
    quoted = b'"rm861-d\\303\\251\\304\\201.log"'
    text_raw, n_raw = exec_mod.scrub_output(raw + b"\n")
    text_quoted, n_quoted = exec_mod.scrub_output(quoted + b"\n")
    assert text_raw.isascii() and text_quoted.isascii()
    assert text_raw == "rm861-d\\xc3\\xa9\\xc4\\x81.log\n"
    assert text_quoted == quoted.decode("ascii") + "\n"
    assert (n_raw, n_quoted) == (4, 0)
