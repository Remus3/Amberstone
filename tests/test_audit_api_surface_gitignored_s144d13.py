"""RM-988 - scripts/audit_api_surface.py never reads a gitignored file.

The walker pruned only the name-based ``SKIP_DIRS`` / ``SKIP_PARTS``, so every
gitignored tree not named there was walked and greped. Measured 2026-10-27 in
the main checkout: 2924 of the 6613 files it returned were gitignored (1856
under ``python-embed/``, 963 under ``moon_sync_inbox/``, the rest under
``.superpowers/``, ``.obsidian/``, ``docs/`` and ``agents/``), and one report
row came from a sibling's note in ``moon_sync_inbox/`` - an endpoint RC does
not call, reported as if it did.

The fix asks git once (``git ls-files -o -i --exclude-standard --directory``):
an ignored directory is pruned from the walk, and an ignored file outside one
(a file-pattern ignore such as ``*.local.md``) is skipped. Outside a git work
tree, or when git fails, the walk falls back to the name lists alone, which is
what the fixture trees in ``tests/test_root_walkers_prune.py`` exercise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import scripts.audit_api_surface as aas
from tests._module_view import bind_subprocess

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")

_GITIGNORE = "python-embed/\nmoon_sync_inbox/\nscratch-copy/\n*.local.md\n"

_LEGIT = frozenset({
    "core/a.py",
    "docs/b.md",
    # Untracked but NOT ignored: a brand-new source file is still scanned.
    "core/new_untracked.py",
})

_IGNORED = frozenset({
    "python-embed/Lib/x.py",
    "moon_sync_inbox/2026-10-27-note.md",
    "scratch-copy/core/y.py",
    # File-pattern ignores, at the root and inside a scanned directory.
    "notes.local.md",
    "core/draft.local.md",
})

_PHANTOM = "/api/phantom-endpoint"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    for rel in _LEGIT:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('URL = "/api/real-endpoint"\n', encoding="utf-8")
    for rel in _IGNORED:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'URL = "{_PHANTOM}"\n', encoding="utf-8")
    (root / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", "core/a.py", "docs/b.md")
    monkeypatch.setattr(aas, "ROOT", root)
    return root


def _rels(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in aas.iter_source_files()}


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


def test_report_has_no_row_from_a_gitignored_file(repo):
    rows = []
    for path in aas.iter_source_files():
        rows.extend(aas.scan_file(path, ["internal"]))
    endpoints = {r["endpoint"] for r in rows}
    assert "/api/real-endpoint" in endpoints, "scan went blind: no legit row"
    assert _PHANTOM not in endpoints


def test_walk_never_enters_a_gitignored_directory(repo, monkeypatch):
    entered: list[str] = []
    real_walk = os.walk

    def _spy(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            entered.append(Path(dirpath).relative_to(repo).as_posix())
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(aas.os, "walk", _spy)
    aas.iter_source_files()
    assert "." in entered, "spy went blind: the root was never walked"
    assert "core" in entered
    leaked = sorted(
        d for d in entered
        if d.split("/")[0] in {"python-embed", "moon_sync_inbox", "scratch-copy"}
    )
    assert leaked == []


def test_outside_a_git_work_tree_the_walk_falls_back_to_the_name_lists(
    tmp_path, monkeypatch,
):
    # No repo at all: git fails, nothing is pruned beyond SKIP_DIRS, nothing raises.
    root = tmp_path.resolve() / "plain"
    for rel in ("core/a.py", "python-embed/b.py", "logs/c.py"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(aas, "ROOT", root)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    assert _rels(root) == {"core/a.py", "python-embed/b.py"}


def test_a_git_failure_falls_back_to_the_name_lists(repo, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise OSError("git missing")

    # audit_api_surface's OWN subprocess only (RM-801): patching
    # aas.subprocess.run would replace subprocess.run for every module in this
    # xdist worker.
    bind_subprocess(monkeypatch, aas, run=_boom)
    got = _rels(repo)
    assert set(_LEGIT) <= got
    assert "python-embed/Lib/x.py" in got
