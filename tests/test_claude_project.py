"""Direct tests for core/claude_project.py (added by wave-3 slice W-D).

The module resolves Claude Code's per-project directory at run time so no
tracked file bakes in a checkout-path slug. Its three public functions are
pinned here against the behaviour their docstrings promise:

* ``project_slug`` (core/claude_project.py:29) - every character outside
  [A-Za-z0-9] becomes one ``-`` (``_NON_ALNUM``, line 26), length preserved.
* ``main_checkout`` (line 34) - a linked worktree's ``.git`` FILE
  (``gitdir: <main>/.git/worktrees/<name>``, lines 46-61) resolves to the main
  checkout; a ``.git`` directory, a missing ``.git``, a link that cannot be
  read or is not UTF-8 (line 50), a link without the ``gitdir:`` prefix
  (line 54) or one that does not point into ``.git/worktrees`` (line 59, e.g.
  a submodule) returns the root unchanged and never raises - its callers
  resolve at import time with no handler (dashboard/routes_loop_monitor.py:55,
  tools/drift_guard.py:79, tools/perseus_sync.py:62); a relative ``gitdir``
  resolves against the root (lines 57-58).
* ``project_dir`` (line 64) - ``<home>/.claude/projects/<slug of the main
  checkout>``, with ``home`` defaulting to ``Path.home()``.

Every case builds its own tree under tmp_path; nothing here reads or writes
the real Claude home.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import claude_project as cp


def _linked_worktree(tmp_path: Path, link: str, name: str = "wt") -> Path:
    wt = tmp_path / name
    wt.mkdir()
    (wt / ".git").write_text(link, encoding="utf-8")
    return wt


# --------------------------------------------------------------------------
# project_slug
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, slug",
    [
        ("E:\\Riot Commander", "E--Riot-Commander"),
        ("C:\\Users\\me\\repo.v2", "C--Users-me-repo-v2"),
        ("/home/me/My Repo", "-home-me-My-Repo"),
        ("abcXYZ019", "abcXYZ019"),
        ("a_b-c.d", "a-b-c-d"),
        ("", ""),
    ],
)
def test_project_slug_maps_every_non_alnum_char_to_a_dash(path: str, slug: str) -> None:
    assert cp.project_slug(path) == slug


def test_project_slug_preserves_length_and_treats_non_ascii_letters_as_non_alnum(
        tmp_path: Path) -> None:
    # A real (drive-rooted on Windows) path with a non-ASCII leaf, built under
    # tmp_path rather than written as a drive-root literal: the pre-push
    # sibling-name sweep's structural arm rightly halts on an unknown drive
    # root, and this test needs only the non-ASCII characters. The mapping is
    # per character, so the expected slug is the parent's slug, one dash for
    # the separator, then the leaf mapped by hand.
    raw = str(tmp_path / "Caf\u00e9 \u00fcber")
    out = cp.project_slug(raw)
    assert out == cp.project_slug(str(tmp_path)) + "-Caf---ber"
    assert len(out) == len(raw)
    assert out.isascii()


def test_project_slug_accepts_a_path_object(tmp_path: Path) -> None:
    assert cp.project_slug(tmp_path) == cp.project_slug(str(tmp_path))


# --------------------------------------------------------------------------
# main_checkout
# --------------------------------------------------------------------------

def test_main_checkout_returns_a_main_checkout_unchanged(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert cp.main_checkout(tmp_path) == tmp_path


def test_main_checkout_returns_a_tree_without_git_unchanged(tmp_path: Path) -> None:
    assert cp.main_checkout(tmp_path) == tmp_path


def test_main_checkout_resolves_a_linked_worktree_to_its_main(tmp_path: Path) -> None:
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "agent-1").mkdir(parents=True)
    wt = _linked_worktree(
        tmp_path, f"gitdir: {main / '.git' / 'worktrees' / 'agent-1'}\n")
    assert cp.main_checkout(wt) == main


def test_main_checkout_accepts_a_crlf_link_and_a_str_root(tmp_path: Path) -> None:
    main = tmp_path / "main"
    wt = _linked_worktree(
        tmp_path, f"gitdir: {main / '.git' / 'worktrees' / 'x'}\r\n")
    assert cp.main_checkout(str(wt)) == main


def test_main_checkout_resolves_a_relative_gitdir_against_the_root(tmp_path: Path) -> None:
    (tmp_path / "main" / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = _linked_worktree(tmp_path, "gitdir: ../main/.git/worktrees/wt\n")
    got = cp.main_checkout(wt)
    assert got.resolve() == (tmp_path / "main").resolve()


@pytest.mark.parametrize(
    "link",
    [
        "gitdir: ../.git/modules/sub\n",        # a submodule, not a worktree
        "gitdir: /elsewhere/repo.git\n",        # a bare or separate git dir
        "gitdir: /x/notgit/worktrees/wt\n",     # 'worktrees' not under .git
        "something else entirely\n",            # no gitdir: prefix
        "gitdir:\n",                            # empty target
        "",                                     # empty file
    ],
)
def test_main_checkout_returns_the_root_for_any_other_link(tmp_path: Path, link: str) -> None:
    wt = _linked_worktree(tmp_path, link)
    assert cp.main_checkout(wt) == wt


def test_main_checkout_returns_the_root_when_the_link_cannot_be_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wt = _linked_worktree(tmp_path, "gitdir: /m/.git/worktrees/wt\n")
    real = Path.read_text

    def boom(self: Path, *args, **kwargs):
        if self.name == ".git":
            raise PermissionError("denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)
    assert cp.main_checkout(wt) == wt


@pytest.mark.parametrize("raw", [
    b"gitdir: /m/.git/worktrees/\xff\xfe\n",     # invalid UTF-8 inside the path
    b"\xff\xfegitdir: /m/.git/worktrees/wt\n",   # a stray UTF-16 BOM
    b"gitdir: /m/.git/worktrees/\xc3\n",         # truncated multi-byte sequence
])
def test_main_checkout_returns_the_root_for_a_non_utf8_link(tmp_path: Path, raw: bytes) -> None:
    # Was a crash (UnicodeDecodeError escaped the OSError-only handler); the
    # callers import-time-resolve with no handler, so it must fall back.
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_bytes(raw)
    assert cp.main_checkout(wt) == wt
    home = tmp_path / "home"
    assert cp.project_dir(wt, home) == home / ".claude" / "projects" / cp.project_slug(wt)


def test_main_checkout_defaults_to_this_checkout() -> None:
    got = cp.main_checkout()
    assert got == cp.main_checkout(cp.REPO_ROOT)
    # From the main checkout or from a linked worktree alike, the answer is a
    # tree whose .git is the real repository directory.
    assert (got / ".git").is_dir(), got


# --------------------------------------------------------------------------
# project_dir
# --------------------------------------------------------------------------

def test_project_dir_is_home_claude_projects_slug(tmp_path: Path) -> None:
    root = tmp_path / "My Repo"
    root.mkdir()
    home = tmp_path / "home"
    expected = home / ".claude" / "projects" / cp.project_slug(root)
    assert cp.project_dir(root, home) == expected
    assert cp.project_dir(str(root), str(home)) == expected


def test_project_dir_from_a_worktree_uses_the_main_checkout_slug(tmp_path: Path) -> None:
    main = tmp_path / "main"
    wt = _linked_worktree(
        tmp_path, f"gitdir: {main / '.git' / 'worktrees' / 'agent-9'}\n")
    home = tmp_path / "home"
    assert cp.project_dir(wt, home) == home / ".claude" / "projects" / cp.project_slug(main)
    assert cp.project_dir(wt, home) != home / ".claude" / "projects" / cp.project_slug(wt)


def test_project_dir_defaults_home_to_path_home(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    root = tmp_path / "r"
    root.mkdir()
    assert cp.project_dir(root) == fake_home / ".claude" / "projects" / cp.project_slug(root)


def test_project_dir_defaults_root_to_this_checkout(tmp_path: Path) -> None:
    home = tmp_path / "h"
    assert cp.project_dir(home=home) == (
        home / ".claude" / "projects" / cp.project_slug(cp.main_checkout()))
