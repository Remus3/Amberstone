"""RM-705 bytecode half: tools/bytecode_hygiene.py lists, then removes, the
regenerable bytecode and cache residue that no tracked step prunes.

Classes (BACKLOG.md RM-705, REFRESHED 2026-10-24 acceptance):
- ``pyc_temp``: ``*.pyc.<digits>`` write-temp leftovers;
- ``orphan_pyc``: a ``__pycache__`` .pyc whose source .py is gone (the rule
  ``ops/loop/repo_review.py`` already counts);
- ``inbox_pyc``: any .pyc under ``moon_sync_inbox/`` (sibling payloads must
  never be imported here, RM-732);
- ``nested_pytest_cache``: every ``.pytest_cache`` dir but the root one.

The walk skips ``.git``, ``.claude/worktrees`` and any nested checkout (a
directory holding its own ``.git``), and never touches a tracked path. Every
test builds its own tree under tmp_path; nothing here reads the live checkout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import bytecode_hygiene as bh

try:
    import _winapi  # Windows only: CreateJunction needs no symlink privilege
except ImportError:
    _winapi = None

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _git(*args: str) -> None:
    flags = {"creationflags": _NO_WINDOW} if _NO_WINDOW else {}
    subprocess.run(["git", *args], check=True, capture_output=True, **flags)


def _touch(root: Path, rel: str, data: bytes = b"x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    # A real (empty) repository, so main() can read its index: nothing tracked.
    _git("init", "-q", str(root))
    # A live module and its bytecode: must survive.
    _touch(root, "pkg/live.py")
    _touch(root, "pkg/__pycache__/live.cpython-314.pyc")
    # Class 1: a write-temp leftover beside the live module's bytecode.
    _touch(root, "pkg/__pycache__/live.cpython-314.pyc.2081234567", b"tmp12")
    # Class 2: an orphan - its source is gone.
    _touch(root, "pkg/__pycache__/gone.cpython-314.pyc", b"orph")
    # Class 3: inbox bytecode, even though its source is present.
    _touch(root, "moon_sync_inbox/from-X-verbatim/tests/t.py")
    _touch(root, "moon_sync_inbox/from-X-verbatim/tests/__pycache__/t.cpython-314.pyc")
    # Class 4: a nested pytest cache; the root one stays.
    _touch(root, "web/icons/positions/.pytest_cache/v/cache/lastfailed", b"{}")
    # Inside a cache the walk never descends: this is removed WITH its cache,
    # never listed on its own.
    _touch(root, "web/icons/positions/.pytest_cache/__pycache__/z.cpython-314.pyc", b"")
    _touch(root, ".pytest_cache/v/cache/lastfailed", b"{}")
    # Skipped trees: .git, .claude/worktrees, a nested checkout.
    _touch(root, ".git/objects/__pycache__/x.cpython-314.pyc")
    _touch(root, ".claude/worktrees/w/pkg/__pycache__/dead.cpython-314.pyc")
    _touch(root, ".claude/worktrees/w/.pytest_cache/v/x")
    _touch(root, "nested/.git", b"gitdir: elsewhere\n")
    _touch(root, "nested/__pycache__/dead.cpython-314.pyc.99")
    return root


def _by_class(cands):
    out: dict[str, list[str]] = {}
    for c in cands:
        out.setdefault(c.cls, []).append(c.rel)
    return {k: sorted(v) for k, v in out.items()}


def test_each_class_is_found_and_nothing_else(tree: Path) -> None:
    got = _by_class(bh.find_candidates(tree, tracked=set()))
    assert got == {
        "pyc_temp": ["pkg/__pycache__/live.cpython-314.pyc.2081234567"],
        "orphan_pyc": ["pkg/__pycache__/gone.cpython-314.pyc"],
        "inbox_pyc": ["moon_sync_inbox/from-X-verbatim/tests/__pycache__/t.cpython-314.pyc"],
        "nested_pytest_cache": ["web/icons/positions/.pytest_cache"],
    }


def test_bytes_are_reported(tree: Path) -> None:
    sizes = {c.rel: c.size for c in bh.find_candidates(tree, tracked=set())}
    assert sizes["pkg/__pycache__/live.cpython-314.pyc.2081234567"] == 5
    assert sizes["pkg/__pycache__/gone.cpython-314.pyc"] == 4
    # A directory candidate reports the bytes of the files under it.
    assert sizes["web/icons/positions/.pytest_cache"] == 2


def test_dry_run_is_the_default_and_removes_nothing(tree: Path, capsys) -> None:
    before = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*"))
    rc = bh.main(["--root", str(tree)])
    after = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*"))
    assert rc == 0
    assert before == after
    out = capsys.readouterr().out
    assert "pkg/__pycache__/gone.cpython-314.pyc" in out
    assert "dry run" in out


def test_apply_removes_every_candidate_and_keeps_live_files(tree: Path, capsys) -> None:
    rc = bh.main(["--root", str(tree), "--apply"])
    assert rc == 0
    for rel in ("pkg/__pycache__/live.cpython-314.pyc.2081234567",
                "pkg/__pycache__/gone.cpython-314.pyc",
                "moon_sync_inbox/from-X-verbatim/tests/__pycache__/t.cpython-314.pyc",
                "web/icons/positions/.pytest_cache"):
        assert not (tree / rel).exists(), rel
    # Survivors: the live module's bytecode, the root cache, every skipped tree.
    for rel in ("pkg/live.py",
                "pkg/__pycache__/live.cpython-314.pyc",
                "moon_sync_inbox/from-X-verbatim/tests/t.py",
                ".pytest_cache/v/cache/lastfailed",
                ".git/objects/__pycache__/x.cpython-314.pyc",
                ".claude/worktrees/w/pkg/__pycache__/dead.cpython-314.pyc",
                ".claude/worktrees/w/.pytest_cache/v/x",
                "nested/__pycache__/dead.cpython-314.pyc.99"):
        assert (tree / rel).exists(), rel
    # A second pass finds nothing left.
    assert bh.find_candidates(tree, tracked=set()) == []
    assert "removed 4" in capsys.readouterr().out


def test_apply_drops_a_pycache_dir_it_emptied_only(tree: Path) -> None:
    bh.main(["--root", str(tree), "--apply"])
    assert not (tree / "moon_sync_inbox/from-X-verbatim/tests/__pycache__").exists()
    assert (tree / "pkg/__pycache__").is_dir()


def test_a_pyc_beside_its_source_outside_pycache_is_out_of_scope(tmp_path: Path) -> None:
    _touch(tmp_path, "legacy.pyc")
    _touch(tmp_path, "other/__pycache__/m.cpython-314.opt-1.pyc")
    _touch(tmp_path, "other/m.py")
    assert bh.find_candidates(tmp_path, tracked=set()) == []


def test_an_optimized_orphan_is_still_an_orphan(tmp_path: Path) -> None:
    _touch(tmp_path, "other/__pycache__/m.cpython-314.opt-2.pyc")
    got = _by_class(bh.find_candidates(tmp_path, tracked=set()))
    assert got == {"orphan_pyc": ["other/__pycache__/m.cpython-314.opt-2.pyc"]}


def test_a_digit_suffix_on_a_non_pyc_name_is_not_a_temp(tmp_path: Path) -> None:
    _touch(tmp_path, "a/__pycache__/m.py.123")
    _touch(tmp_path, "a/__pycache__/m.cpython-314.pyc.12a")
    _touch(tmp_path, "a/m.py")
    assert bh.find_candidates(tmp_path, tracked=set()) == []


def test_a_tracked_path_is_refused_not_removed(tree: Path) -> None:
    tracked = {"pkg/__pycache__/gone.cpython-314.pyc",
               "web/icons/positions/.pytest_cache/v/cache/lastfailed"}
    cands = bh.find_candidates(tree, tracked=tracked)
    rels = {c.rel for c in cands}
    assert "pkg/__pycache__/gone.cpython-314.pyc" not in rels
    assert "web/icons/positions/.pytest_cache" not in rels


def test_a_caller_tracked_set_is_matched_case_insensitively(tree: Path) -> None:
    tracked = {"PKG/__pycache__/GONE.cpython-314.pyc",
               "Web/Icons/Positions/.pytest_cache/v/cache/lastfailed"}
    rels = {c.rel for c in bh.find_candidates(tree, tracked=tracked)}
    assert "pkg/__pycache__/gone.cpython-314.pyc" not in rels
    assert "web/icons/positions/.pytest_cache" not in rels


def test_tracked_set_is_read_from_git(tmp_path: Path) -> None:
    root = tmp_path / "g"
    root.mkdir()
    _git("init", "-q", str(root))
    _touch(root, "a/__pycache__/gone.cpython-314.pyc")
    _touch(root, "b/__pycache__/gone.cpython-314.pyc")
    _git("-C", str(root), "add", "-f", "a/__pycache__/gone.cpython-314.pyc")
    rc = bh.main(["--root", str(root), "--apply"])
    assert rc == 0
    assert (root / "a/__pycache__/gone.cpython-314.pyc").exists()
    assert not (root / "b/__pycache__/gone.cpython-314.pyc").exists()


def _link_dir(link: Path, target: Path) -> None:
    """A directory junction on Windows (no privilege needed), else a symlink."""
    if _winapi is None:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"cannot create a directory link: {exc}")
        return
    _winapi.CreateJunction(str(target), str(link))


def test_the_walk_never_follows_a_link_out_of_the_tree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    _touch(outside, "pkg/__pycache__/gone.cpython-314.pyc")
    _touch(outside, "pkg/.pytest_cache/v/x")
    root.mkdir()
    _link_dir(root / "linked", outside)
    assert (root / "linked/pkg/__pycache__/gone.cpython-314.pyc").exists()
    assert bh.find_candidates(root, tracked=set()) == []


def test_an_unreadable_git_index_refuses_and_removes_nothing(tmp_path: Path, capsys) -> None:
    # A .git that is not a repository: "tracked" cannot be known, so refuse.
    _touch(tmp_path, ".git/junk")
    _touch(tmp_path, "a/__pycache__/gone.cpython-314.pyc")
    rc = bh.main(["--root", str(tmp_path), "--apply"])
    assert rc == 2
    assert (tmp_path / "a/__pycache__/gone.cpython-314.pyc").exists()
    assert "git ls-files failed" in capsys.readouterr().err


def test_a_corrupt_index_refuses_and_removes_nothing(tmp_path: Path, capsys) -> None:
    # The repository is found, but its index cannot be read.
    root = tmp_path / "g"
    root.mkdir()
    _git("init", "-q", str(root))
    (root / ".git" / "index").write_bytes(b"not an index")
    _touch(root, "a/__pycache__/gone.cpython-314.pyc")
    rc = bh.main(["--root", str(root), "--apply"])
    assert rc == 2
    assert (root / "a/__pycache__/gone.cpython-314.pyc").exists()
    assert "git ls-files failed" in capsys.readouterr().err


def test_a_subfolder_root_still_protects_tracked_files(tmp_path: Path) -> None:
    # --root below the checkout top: git discovery must still find the index.
    outer = tmp_path / "outer"
    outer.mkdir()
    _git("init", "-q", str(outer))
    _touch(outer, "sub/a/__pycache__/gone.cpython-314.pyc")
    _touch(outer, "sub/b/__pycache__/gone.cpython-314.pyc")
    _git("-C", str(outer), "add", "-f", "sub/a/__pycache__/gone.cpython-314.pyc")
    rc = bh.main(["--root", str(outer / "sub"), "--apply"])
    assert rc == 0
    assert (outer / "sub/a/__pycache__/gone.cpython-314.pyc").exists()
    assert not (outer / "sub/b/__pycache__/gone.cpython-314.pyc").exists()


def test_a_broken_git_inside_a_parent_repo_refuses(tmp_path: Path, capsys) -> None:
    # git skips a broken .git and finds the parent; the tool must not accept that.
    outer = tmp_path / "outer"
    outer.mkdir()
    _git("init", "-q", str(outer))
    _touch(outer, "inner/.git/junk")
    _touch(outer, "inner/a/__pycache__/gone.cpython-314.pyc")
    rc = bh.main(["--root", str(outer / "inner"), "--apply"])
    assert rc == 2
    assert (outer / "inner/a/__pycache__/gone.cpython-314.pyc").exists()
    assert "not its repository's top" in capsys.readouterr().err


def test_an_inherited_git_dir_cannot_redirect_the_index(tmp_path: Path, monkeypatch) -> None:
    # Inside a git hook GIT_DIR / GIT_INDEX_FILE point at ANOTHER repository.
    root = tmp_path / "g"
    other = tmp_path / "other"
    for d in (root, other):
        d.mkdir()
        _git("init", "-q", str(d))
    _touch(root, "a/__pycache__/gone.cpython-314.pyc")
    _git("-C", str(root), "add", "-f", "a/__pycache__/gone.cpython-314.pyc")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    assert "a/__pycache__/gone.cpython-314.pyc" in bh.tracked_paths(root)


def test_an_inherited_ceiling_cannot_hide_the_repository(tmp_path: Path, monkeypatch) -> None:
    # A ceiling at the checkout top stops discovery from a subfolder; dropped.
    outer = tmp_path / "outer"
    outer.mkdir()
    _git("init", "-q", str(outer))
    _touch(outer, "sub/a/__pycache__/gone.cpython-314.pyc")
    _git("-C", str(outer), "add", "-f", "sub/a/__pycache__/gone.cpython-314.pyc")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(outer))
    rc = bh.main(["--root", str(outer / "sub"), "--apply"])
    assert rc == 0
    assert (outer / "sub/a/__pycache__/gone.cpython-314.pyc").exists()


def test_a_failing_git_inside_a_repository_refuses(tmp_path: Path, monkeypatch, capsys) -> None:
    # Any git failure while a .git exists above the root is a refusal, never
    # "nothing tracked" (here: an unparsable global config breaks every call).
    outer = tmp_path / "outer"
    outer.mkdir()
    _git("init", "-q", str(outer))
    _touch(outer, "sub/a/__pycache__/gone.cpython-314.pyc")
    _git("-C", str(outer), "add", "-f", "sub/a/__pycache__/gone.cpython-314.pyc")
    bad = _touch(tmp_path, "bad.gitconfig", b"[[[ not a config\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(bad))
    rc = bh.main(["--root", str(outer / "sub"), "--apply"])
    assert rc == 2
    assert (outer / "sub/a/__pycache__/gone.cpython-314.pyc").exists()
    assert "git ls-files failed" in capsys.readouterr().err


def test_a_tracked_path_matches_whatever_its_case_on_disk(tmp_path: Path) -> None:
    root = tmp_path / "g"
    root.mkdir()
    _git("init", "-q", str(root))
    _touch(root, "Pkg/__pycache__/gone.cpython-314.pyc")
    _git("-C", str(root), "add", "-f", "Pkg/__pycache__/gone.cpython-314.pyc")
    (root / "Pkg").rename(root / "tmpname")
    (root / "tmpname").rename(root / "pkg")
    assert bh.find_candidates(root) == []


def test_a_root_inside_a_git_directory_is_refused(tmp_path: Path, capsys) -> None:
    root = tmp_path / "g"
    root.mkdir()
    _git("init", "-q", str(root))
    _touch(root, ".git/hooks/__pycache__/gone.cpython-314.pyc")
    for sub in (".git", ".git/hooks"):
        rc = bh.main(["--root", str(root / sub), "--apply"])
        assert rc == 2, sub
        assert "inside a .git directory" in capsys.readouterr().err
    assert (root / ".git/hooks/__pycache__/gone.cpython-314.pyc").exists()


def test_a_root_inside_a_bare_repository_is_refused(tmp_path: Path, capsys) -> None:
    # No path part is named .git, but git reports the root inside a git dir.
    bare = tmp_path / "b.git"
    _git("init", "-q", "--bare", str(bare))
    _touch(bare, "hooks/__pycache__/gone.cpython-314.pyc")
    rc = bh.main(["--root", str(bare / "hooks"), "--apply"])
    assert rc == 2
    assert "inside a git directory" in capsys.readouterr().err
    assert (bare / "hooks/__pycache__/gone.cpython-314.pyc").exists()


def test_a_root_in_no_repository_is_cleaned(tmp_path: Path, capsys) -> None:
    plain = tmp_path / "plain"
    if any((d / ".git").exists() for d in (plain, *plain.parents)):
        pytest.skip("the temp dir sits inside a git checkout")
    _touch(plain, "a/__pycache__/gone.cpython-314.pyc")
    assert bh.tracked_paths(plain) == set()
    rc = bh.main(["--root", str(plain), "--apply"])
    assert rc == 0
    assert not (plain / "a/__pycache__/gone.cpython-314.pyc").exists()
    assert "removed 1 of 1" in capsys.readouterr().out


def test_a_root_that_is_not_a_directory_is_refused(tmp_path: Path, capsys) -> None:
    rc = bh.main(["--root", str(tmp_path / "absent")])
    assert rc == 2
    assert "not a directory" in capsys.readouterr().err
