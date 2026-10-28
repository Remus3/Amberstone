"""RM-989 - tools/gen_archmap.py skips a gitignored FILE, not only a gitignored dir.

RM-985 taught the walker to prune every directory git reports as ignored,
but it kept only the "dir/" entries of ``git ls-files -o -i --exclude-standard
--directory``. Two kinds of ignored file come back as bare file entries and
were still read and mapped:

1. a file-pattern ignore (``*.local.py``) in a source directory;
2. an untracked file in an ignored directory that also holds a tracked file
   (git cannot collapse that directory to one "dir/" entry).

Measured 2026-10-27 in the main checkout: 0 such ``.py`` files today, so this
is a latent defect, not a live one. scripts/audit_api_surface.py already
skips both (RM-988 ``_git_ignored``); this pins the same shape here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import tools.gen_archmap as gam
from tests._module_view import bind_subprocess

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")

# Assembled at runtime so the literal marker never appears in THIS file's
# source: gen_archmap scans tests/ too (the PHASE_SCAN_SKIP_FILES trap).
_MARK = "# " + "arch:"
_ARCH_HEADER = _MARK + " fixture role | section=core | frozen=no\n"
_PHASE_LINE = _MARK + " phase 9.9 (2026-09-19) - fixture marker\n"

_GITIGNORE = "*.local.py\nvendor/\n"

_TRACKED = frozenset({
    "core/a.py",
    # Force-added under an ignored dir: tracked, so it is source and stays mapped.
    "vendor/keep.py",
})

_LEGIT = _TRACKED | {"core/new_untracked.py"}

_IGNORED_FILES = frozenset({
    "core/secret.local.py",
    "vendor/scratch.py",
})


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
    for rel in _LEGIT | _IGNORED_FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_ARCH_HEADER + _PHASE_LINE, encoding="utf-8")
    (root / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", "core/a.py")
    _git(root, "add", "-f", "vendor/keep.py")
    monkeypatch.setattr(gam, "ROOT", root)
    return root


def test_git_reports_the_decoys_as_bare_ignored_file_entries(repo):
    # Anchor: if git collapsed either decoy into a "dir/" entry, the dir-only
    # prune would already skip it and the tests below would prove nothing.
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--others", "--ignored",
         "--exclude-standard", "--directory"],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    entries = {e for e in out.stdout.decode("utf-8").split("\0") if e}
    assert entries == set(_IGNORED_FILES)


def _rels(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in gam._iter_source_py()}


def test_walk_skips_every_gitignored_file_and_keeps_the_rest(repo):
    assert _rels(repo) == set(_LEGIT)


def test_archmap_has_no_row_from_a_gitignored_file(repo):
    rows = {rel for rel, _role, _frozen in gam._collect()["core"]}
    assert rows == set(_LEGIT)


def test_phase_journal_has_no_row_from_a_gitignored_file(repo):
    rows = {rel for _pid, _date, rel, _line, _note in gam._collect_phase_markers()}
    assert rows == set(_LEGIT)


def test_a_failed_git_call_ignores_nothing(repo, monkeypatch):
    # Fail-open to the name lists: a git error never drops a tracked file.
    def _boom(*_a, **_k):
        raise OSError("git missing")

    # gen_archmap's OWN subprocess only (RM-801): patching gam.subprocess.run
    # would replace subprocess.run for every module in this xdist worker.
    bind_subprocess(monkeypatch, gam, run=_boom)
    assert _rels(repo) == set(_LEGIT) | set(_IGNORED_FILES)
