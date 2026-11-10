"""S144-Q-128: a long plain-rev range reaches the credential scan's git on stdin.

A first push or a rewrite push resolves to `<tip> ^a ^b ...`, one word per sha
the remote advertises (tools/sibling_name_sweep.py resolve_push_ranges), so a
remote with many refs can overrun the Windows command-line cap (32767 chars)
when the range goes on argv. `added_lines` (the pre-push path) already fed it
on stdin; `list_blobs` (reached through the public `run()`) did not. Both now
use the shared `stdin_revs`, and an option-carrying list (`--not`, `--all`)
stays on argv because git before 2.42 rejects options in --stdin mode.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import credential_history_scan as chs

_NW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
N_EXCLUDES = 2000  # 2000 x 41 chars is well past the 32767-char Windows cap


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True, creationflags=_NW).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "core.autocrlf", "false")
    (r / "a.py").write_text("x = 1\n", encoding="ascii")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    base = _git(r, "rev-parse", "HEAD")
    (r / "b.py").write_text("y = 2\n", encoding="ascii")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "tip")
    return r, base, _git(r, "rev-parse", "HEAD")


@pytest.fixture
def calls(monkeypatch):
    """Record every git call the scan makes, then run it for real."""
    seen: list[tuple[list[str], bytes | None]] = []
    real = chs._git

    def spy(args, stdin=None, root=chs.ROOT):
        seen.append((list(args), stdin))
        return real(args, stdin=stdin, root=root)

    monkeypatch.setattr(chs, "_git", spy)
    return seen


def _long_range(base: str, tip: str) -> list[str]:
    return [tip, *(["^" + base] * N_EXCLUDES)]


def _call(calls, verb: str) -> tuple[list[str], bytes | None]:
    hits = [c for c in calls if c[0] and c[0][0] == verb]
    assert len(hits) == 1, hits
    return hits[0]


def test_list_blobs_feeds_a_long_plain_range_on_stdin(repo, calls):
    r, base, tip = repo
    blobs = chs.list_blobs(_long_range(base, tip), root=r)
    args, stdin = _call(calls, "rev-list")
    assert args == ["rev-list", "--objects", "--stdin"]
    assert stdin is not None
    fed = stdin.decode().split()
    assert fed[0] == tip and fed.count("^" + base) == N_EXCLUDES
    # Only the tip's new blob: the base's a.py is excluded by the range.
    assert sorted(blobs.values()) == ["b.py"]


def test_run_scans_a_long_plain_range_without_a_fault(repo, calls, tmp_path):
    r, base, tip = repo
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"accepted": []}\n', encoding="ascii")
    assert chs.run([_long_range(base, tip)], root=r,
                   baseline_path=baseline) == chs.EXIT_CLEAN
    assert _call(calls, "rev-list")[0][-1] == "--stdin"


def test_list_blobs_keeps_an_option_carrying_range_on_argv(repo, calls):
    r, base, tip = repo
    blobs = chs.list_blobs([tip, "--not", base], root=r)
    args, stdin = _call(calls, "rev-list")
    assert args == ["rev-list", "--objects", tip, "--not", base]
    assert stdin is None
    assert sorted(blobs.values()) == ["b.py"]


def test_list_blobs_keeps_all_on_argv(repo, calls):
    r, _base, _tip = repo
    blobs = chs.list_blobs(["--all"], root=r)
    args, stdin = _call(calls, "rev-list")
    assert args == ["rev-list", "--objects", "--all"]
    assert stdin is None
    assert sorted(blobs.values()) == ["a.py", "b.py"]


def test_added_lines_feeds_a_long_plain_range_on_stdin(repo, calls):
    """The pre-push path (main -> run_push -> added_lines): pinned so the two
    rev consumers cannot drift apart again."""
    r, base, tip = repo
    found = chs.added_lines(_long_range(base, tip), root=r)
    args, stdin = _call(calls, "log")
    assert args[-1] == "--stdin" and tip not in args
    assert stdin is not None and stdin.decode().split().count("^" + base) == N_EXCLUDES
    assert list(found) == [(tip, "b.py")]


def test_added_lines_keeps_an_option_carrying_range_on_argv(repo, calls):
    r, base, tip = repo
    found = chs.added_lines([tip, "--not", base], root=r)
    args, stdin = _call(calls, "log")
    assert args[-3:] == [tip, "--not", base] and "--stdin" not in args
    assert stdin is None
    assert list(found) == [(tip, "b.py")]
