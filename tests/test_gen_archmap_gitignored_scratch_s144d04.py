"""RM-985 - tools/gen_archmap.py never walks a gitignored directory.

The pre-commit hook runs ``tools/gen_archmap.py --check``. Its walker pruned
only the name-based ``SKIP_DIRS``, so every gitignored scratch tree that is not
named there was read in full on every commit. Measured 2026-10-27 in the main
checkout: 2125 gitignored ``.py`` files outside ``SKIP_DIRS`` (1838 under
``python-embed/``, the rest under ``moon_sync_inbox/`` and
``ops/loop/control/``). The phase-journal collector reads each one whole.

It is also a correctness bug. A verifier's scratch copy of the tree under the
gitignored ``logs/`` (``logs/_fakeroot/coaches/*.py``) put 4 phantom rows into
the ``docs/ARCHITECTURE.md`` archmap, so ``--check`` refused an unrelated
commit (s144 ds cycle 4).

The fix asks git for the ignored directories once (``git ls-files -o -i
--exclude-standard --directory``) and prunes them in the walk. Outside a git
work tree it falls back to ``SKIP_DIRS`` alone, which is what the fixture trees
in ``tests/test_root_walkers_prune.py`` exercise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import tools.gen_archmap as gam

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")

# Assembled at runtime so the literal marker never appears in THIS file's
# source: gen_archmap scans tests/ too (the PHASE_SCAN_SKIP_FILES trap).
_MARK = "# " + "arch:"
_ARCH_HEADER = _MARK + " fixture role | section=core | frozen=no\n"
_PHASE_LINE = _MARK + " phase 9.9 (2026-09-19) - fixture marker\n"

_GITIGNORE = "logs/\nscratch-copy/\nops/loop/control/\n"

_LEGIT = frozenset({
    "core/a.py",
    "ops/loop/d.py",
    # Untracked but NOT ignored: a brand-new source file must still be mapped
    # before it is staged, exactly as before the fix.
    "core/new_untracked.py",
})

_IGNORED = frozenset({
    "logs/_fakeroot/coaches/x.py",
    "scratch-copy/core/y.py",
    "ops/loop/control/lane_prompts/z.py",
})


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _repo(root: Path) -> None:
    for rel in _LEGIT | _IGNORED:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_ARCH_HEADER + _PHASE_LINE, encoding="utf-8")
    (root / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", "core/a.py", "ops/loop/d.py")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    _repo(root)
    monkeypatch.setattr(gam, "ROOT", root)
    return root


def _rels(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in gam._iter_source_py()}


def test_fixture_really_ignores_the_decoys(repo):
    # Anchor: if git did not ignore the decoys, the tests below prove nothing.
    out = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", *sorted(_IGNORED)],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert sorted(out.stdout.split()) == sorted(_IGNORED)


def test_walk_skips_every_gitignored_file_and_keeps_the_rest(repo):
    assert _rels(repo) == set(_LEGIT)


def test_archmap_has_no_row_from_a_gitignored_copy(repo):
    rows = {rel for rel, _role, _frozen in gam._collect()["core"]}
    assert rows == set(_LEGIT)


def test_phase_journal_has_no_row_from_a_gitignored_copy(repo):
    rows = {rel for _pid, _date, rel, _line, _note in gam._collect_phase_markers()}
    assert rows == set(_LEGIT)


def test_walk_never_enters_a_gitignored_directory(repo, monkeypatch):
    entered: list[str] = []
    real_walk = os.walk

    def _spy(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            entered.append(Path(dirpath).relative_to(repo).as_posix())
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(gam.os, "walk", _spy)
    gam._iter_source_py()
    assert "." in entered, "spy went blind: the root was never walked"
    assert "ops/loop" in entered
    leaked = sorted(
        d for d in entered
        if d.split("/")[0] in {"logs", "scratch-copy"} or d.startswith("ops/loop/control")
    )
    assert leaked == []


def test_outside_a_git_work_tree_the_walk_falls_back_to_skip_dirs(tmp_path, monkeypatch):
    # No repo at all: git fails, nothing is pruned beyond SKIP_DIRS, nothing raises.
    root = tmp_path.resolve() / "plain"
    for rel in ("core/a.py", "logs/b.py", "runtime/c.py"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_ARCH_HEADER, encoding="utf-8")
    monkeypatch.setattr(gam, "ROOT", root)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    assert _rels(root) == {"core/a.py", "logs/b.py"}
