"""Repo-root walkers in tools/ and scripts/ must PRUNE, never enumerate-then-filter.

Same defect family as the core/hot_reload.py fix (tests/test_hot_reload.py):
`ROOT.rglob(...)` never prunes, so every call enumerated every directory under
the repo root - including `.claude/worktrees` (~40 agent worktrees, ~197k
files) and `ops/runtime/responder_export` (~14k files) - before the
`SKIP_DIRS` post-filter ran. Two walkers of that shape:

  tools/gen_archmap.py        _collect + _collect_phase_markers
                              (wired into .githooks/pre-commit:55 via --check,
                              so it ran TWICE on every commit)
  scripts/audit_api_surface.py iter_source_files (manual CLI only)

These tests pin the ENUMERATED DIRECTORY SET of each walker on a fixture tree
that carries decoy trees nested 2+ levels deep, so a descent is observable.
The recording idiom (os.scandir instrumented, root-relative posix paths, ""
for the root, anchored on the root having been seen) is the one
tests/test_hot_reload.py:_record_enumerated_dirs established - one idiom, not
two. Both pathlib.rglob and os.walk route through os.scandir on this
interpreter (verified on Python 3.14.4), and the root anchor is what proves
the instrumentation has not silently gone blind.

ROOT is a module-level constant in both files (tools/gen_archmap.py:31
`ROOT = pathlib.Path(__file__).parent.parent`, scripts/audit_api_surface.py:42
`ROOT = Path(__file__).resolve().parent.parent`), read at call time by every
walker, so monkeypatching the attribute redirects the walk.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

import scripts.audit_api_surface as aas
import tools.gen_archmap as gam

# Decoy trees shared by both fixtures. Each decoy FILE below sits 2+ levels
# under one of these, so entering the tree is observable as an extra
# enumerated directory. Declared, not derived: "ops/runtime/..." lives under
# a legitimate top-level dir ("ops") for gen_archmap.
_DECOY_TREES: frozenset[str] = frozenset({
    ".claude",
    "ops/runtime",
    ".git",
    "node_modules",
    "docs/_archive",
})

_DECOY_FILES: frozenset[str] = frozenset({
    ".claude/worktrees/agent-x/core/z.py",
    "ops/runtime/responder_export/abcdef123456/core/z.py",
    ".git/hooks/z.py",
    "node_modules/pkg/z.py",
    "docs/_archive/old/z.py",
})

# Assembled at runtime so the literal marker never appears in THIS file's
# source: gen_archmap scans tests/ too, and a contiguous marker here would
# add a phantom row to the phase journal (the PHASE_SCAN_SKIP_FILES trap).
_MARK = "# " + "arch:"
_ARCH_HEADER = _MARK + " fixture role | section=core | frozen=no\n"
_PHASE_LINE = _MARK + " phase 9.9 (2026-09-19) - fixture marker\n"


def _record_enumerated_dirs(
    monkeypatch, root: Path, walker: Callable[[], object],
) -> list[str]:
    """Run ``walker()`` with os.scandir instrumented.

    Returns every directory passed to os.scandir during the call, as a
    root-relative posix path ("" for the root itself), in call order and
    WITH repeats, so a double walk is visible as a duplicate entry.
    """
    recorded: list[str] = []
    real_scandir = os.scandir
    root_norm = os.path.normcase(os.path.normpath(str(root)))

    def _wrapped(path=".", *args, **kwargs):
        p = os.path.normcase(os.path.normpath(os.fspath(path)))
        if p == root_norm or p.startswith(root_norm + os.sep):
            rel = os.path.relpath(p, root_norm)
            recorded.append("" if rel == "." else rel.replace("\\", "/"))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", _wrapped)
    try:
        walker()
    finally:
        monkeypatch.undo()
    assert "" in recorded, (
        "instrumentation went blind: os.scandir never saw the root; "
        "the walker no longer routes through os.scandir on this Python"
    )
    return recorded


def _build_tree(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def _assert_pruned(recorded: list[str], allowed: frozenset[str]) -> None:
    seen = set(recorded)
    # Anchor: an empty enumeration must NOT pass this test.
    assert seen, "walker enumerated nothing at all"
    assert allowed, "allowed set is empty - test is inert"
    for f in _DECOY_FILES:
        assert any(f.startswith(t + "/") for t in _DECOY_TREES), f
    descended = sorted(
        d for d in seen
        if d and any(d == t or d.startswith(t + "/") for t in _DECOY_TREES)
    )
    assert descended == [], f"walker DESCENDED into decoy trees: {descended}"
    assert seen == allowed, (
        f"unexpected enumeration: extra={sorted(seen - allowed)} "
        f"missing={sorted(allowed - seen)}"
    )


# -- tools/gen_archmap.py ---------------------------------------------------------

# Legit .py files at two levels plus a root-level one. Every legit file carries
# an arch header (first 8 lines) AND a phase marker so both collectors return it.
_GAM_LEGIT: frozenset[str] = frozenset({
    "top.py",
    "core/a.py",
    "core/sub/b.py",
    "tools/c.py",
    "ops/loop/d.py",
})

# "ops" is entered (only ops/runtime is a decoy there); "docs" is NOT, because
# gen_archmap's SKIP_DIRS skips "docs" wholesale, so docs/_archive is never
# even reached.
_GAM_ALLOWED: frozenset[str] = frozenset({
    "", "core", "core/sub", "tools", "ops", "ops/loop",
})


def _gam_tree(root: Path) -> None:
    body = _ARCH_HEADER + _PHASE_LINE
    _build_tree(root, {rel: body for rel in _GAM_LEGIT | _DECOY_FILES})


class TestGenArchmapPrunes:
    def test_collect_enumerates_exactly_the_allowed_set(self, tmp_path, monkeypatch):
        root = tmp_path.resolve()
        _gam_tree(root)
        monkeypatch.setattr(gam, "ROOT", root)
        recorded = _record_enumerated_dirs(monkeypatch, root, gam._collect)
        _assert_pruned(recorded, _GAM_ALLOWED)

    def test_collect_phase_markers_enumerates_exactly_the_allowed_set(
        self, tmp_path, monkeypatch,
    ):
        root = tmp_path.resolve()
        _gam_tree(root)
        monkeypatch.setattr(gam, "ROOT", root)
        recorded = _record_enumerated_dirs(
            monkeypatch, root, gam._collect_phase_markers,
        )
        _assert_pruned(recorded, _GAM_ALLOWED)

    def test_collect_returns_exactly_the_legit_set_sorted(self, tmp_path, monkeypatch):
        root = tmp_path.resolve()
        _gam_tree(root)
        monkeypatch.setattr(gam, "ROOT", root)
        data = gam._collect()
        rels = [rel for rel, _role, _frozen in data["core"]]
        assert rels, "collector returned no files"
        assert set(rels) == _GAM_LEGIT, (
            f"extra={sorted(set(rels) - _GAM_LEGIT)} "
            f"missing={sorted(_GAM_LEGIT - set(rels))}"
        )
        # Same ordering as the pre-fix sorted(rglob) walk: sorted by Path.
        assert rels == [
            p.relative_to(root).as_posix()
            for p in sorted(root / r for r in _GAM_LEGIT)
        ]
        assert all(section == "core" or not rows for section, rows in data.items())

    def test_phase_markers_return_exactly_the_legit_set(self, tmp_path, monkeypatch):
        root = tmp_path.resolve()
        _gam_tree(root)
        monkeypatch.setattr(gam, "ROOT", root)
        rows = gam._collect_phase_markers()
        rels = {rel for _pid, _date, rel, _lineno, _note in rows}
        assert rels, "phase collector returned no files"
        assert rels == _GAM_LEGIT, (
            f"extra={sorted(rels - _GAM_LEGIT)} missing={sorted(_GAM_LEGIT - rels)}"
        )


# -- scripts/audit_api_surface.py -------------------------------------------------

# Legit source files at two levels, across several SCAN_SUFFIXES. "ops" is in
# that file's SKIP_DIRS wholesale, so it is a decoy top there and must not be
# entered at all; "docs" is entered but "docs/_archive" (SKIP_PARTS) is not.
_AAS_LEGIT: frozenset[str] = frozenset({
    "top.py",
    "core/a.py",
    "core/sub/b.md",
    "tools/c.js",
    "docs/e.md",
})

_AAS_ALLOWED: frozenset[str] = frozenset({
    "", "core", "core/sub", "tools", "docs",
})


def _aas_tree(root: Path) -> None:
    _build_tree(root, {rel: "x = 1\n" for rel in _AAS_LEGIT | _DECOY_FILES})


class TestAuditApiSurfacePrunes:
    def test_iter_source_files_enumerates_exactly_the_allowed_set(
        self, tmp_path, monkeypatch,
    ):
        root = tmp_path.resolve()
        _aas_tree(root)
        monkeypatch.setattr(aas, "ROOT", root)
        recorded = _record_enumerated_dirs(monkeypatch, root, aas.iter_source_files)
        _assert_pruned(recorded, _AAS_ALLOWED)

    def test_iter_source_files_returns_exactly_the_legit_set(
        self, tmp_path, monkeypatch,
    ):
        root = tmp_path.resolve()
        _aas_tree(root)
        monkeypatch.setattr(aas, "ROOT", root)
        got = aas.iter_source_files()
        rels = {p.relative_to(root).as_posix() for p in got}
        assert rels, "walker returned no files"
        assert rels == _AAS_LEGIT, (
            f"extra={sorted(rels - _AAS_LEGIT)} missing={sorted(_AAS_LEGIT - rels)}"
        )
        assert all(p.is_absolute() for p in got), "paths must stay absolute"


@pytest.mark.parametrize("mod", [gam, aas])
def test_root_is_a_module_level_path_constant(mod):
    """Guard the monkeypatch target: ROOT must stay a module attribute."""
    assert isinstance(mod.ROOT, Path)
    assert mod.ROOT.name == "Riot Commander" or mod.ROOT.is_dir()
