"""Drift guard: assert that the U+2500 box-drawing horizontal rule does NOT
re-appear in the two FROZEN files swept by item 176.

Background (item 176, 2026-05-24): operator authorized a one-time sweep of
U+2500 BOX DRAWINGS LIGHT HORIZONTAL (UTF-8 bytes e2 94 80) on two frozen
files via tools/strip_u2500.py:
    ops/rc_supervisor.py     pre=58  -> post=0
    ops/rc_self_monitor.py   pre=484 -> post=0

The horizontal rules in docstring section-headers (e.g.
"# === Section ============") were normalized from the box-drawing glyph
to plain ASCII '-'. The visual width is identical (1:1 char replacement)
and the semantic intent of a horizontal rule is preserved.

This drift guard locks the post-sweep state of those two specific files:
if a future edit reintroduces U+2500 into either file, the guard fails
CI immediately so the regression can be caught before it lands.

SCOPE NOTE: U+2500 is NOT a banned codepoint globally (unlike smart
quotes / em-dashes which are CLAUDE.md hard-rule). It appears intentionally
in many non-frozen authored files across the repo (test fixtures,
docstrings, ASCII-art separators in 207+ tracked files). This guard
deliberately ASSERTS ONLY on the two operator-granted frozen files;
it does NOT do a repo-wide ban on U+2500. To sweep additional files
in the future, the operator must grant explicit permission and add
them to the _ASSERTED_CLEAN frozenset below.

If this test fails on a re-introduction, run:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen ops/rc_supervisor.py --dry-run
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen ops/rc_supervisor.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# UTF-8 byte sequence for U+2500 BOX DRAWINGS LIGHT HORIZONTAL.
# Constructed via \xNN escapes so this test file stays 7-bit ASCII.
_U2500_BYTES = b"\xe2\x94\x80"

# Files swept by item 176 (frozen) + item 187 (candidates: archived code +
# data payload). These specific paths must remain U+2500-free. To extend
# coverage, get operator grant + run the sweep tool, then add the path
# here.
_ASSERTED_CLEAN: frozenset[str] = frozenset({
    # item 176 frozen-file sweep (2026-05-24):
    "ops/rc_supervisor.py",
    "ops/rc_self_monitor.py",
    # item 187 candidate sweep (2026-05-25) - data payload + dead fallback:
    "web/legacy_index.html",
    "ops/rc_config.json",
})


def _count_u2500(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    return raw.count(_U2500_BYTES)


def test_no_u2500_in_rc_supervisor() -> None:
    """ops/rc_supervisor.py must NOT contain U+2500 (item 176 swept it clean)."""
    p = _REPO_ROOT / "ops" / "rc_supervisor.py"
    assert p.is_file(), f"target frozen file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"ops/rc_supervisor.py contains {n} U+2500 BOX DRAWINGS LIGHT "
        f"HORIZONTAL chars. Item 176 swept this file clean (58 -> 0). "
        f"Regression detected. Run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py "
        f"--allow-frozen ops/rc_supervisor.py` to repair."
    )


def test_no_u2500_in_rc_self_monitor() -> None:
    """ops/rc_self_monitor.py must NOT contain U+2500 (item 176 swept it clean)."""
    p = _REPO_ROOT / "ops" / "rc_self_monitor.py"
    assert p.is_file(), f"target frozen file missing at {p}"
    n = _count_u2500(p)
    assert n == 0, (
        f"ops/rc_self_monitor.py contains {n} U+2500 BOX DRAWINGS LIGHT "
        f"HORIZONTAL chars. Item 176 swept this file clean (484 -> 0). "
        f"Regression detected. Run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py "
        f"--allow-frozen ops/rc_self_monitor.py` to repair."
    )


def test_asserted_clean_set_pins_both_swept_files() -> None:
    """Defensive pin: the _ASSERTED_CLEAN set covers both item-176-swept files."""
    assert "ops/rc_supervisor.py" in _ASSERTED_CLEAN
    assert "ops/rc_self_monitor.py" in _ASSERTED_CLEAN


def test_all_asserted_clean_files_are_u2500_free() -> None:
    """Walk the _ASSERTED_CLEAN frozenset and verify every entry is clean.

    Parallels the per-file tests above but iterates the frozenset so any
    future extension to the set is automatically covered.
    """
    violations: list[tuple[str, int]] = []
    for rel_posix in sorted(_ASSERTED_CLEAN):
        p = _REPO_ROOT / rel_posix
        if not p.is_file():
            pytest.fail(f"asserted-clean file missing: {rel_posix}")
        n = _count_u2500(p)
        if n > 0:
            violations.append((rel_posix, n))
    if violations:
        lines = [f"  {rel}: U+2500 x{n}" for rel, n in violations]
        msg = (
            "U+2500 drift detected in operator-asserted-clean files. "
            "Run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen <path>` to "
            "repair. Violations:\n" + "\n".join(lines)
        )
        pytest.fail(msg)


def test_strip_u2500_tool_is_ascii() -> None:
    """The strip tool itself MUST be 7-bit ASCII (no literal U+2500 glyph)."""
    p = _REPO_ROOT / "tools" / "strip_u2500.py"
    assert p.is_file(), f"strip tool missing at {p}"
    raw = p.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tools/strip_u2500.py has {len(non_ascii)} non-ASCII bytes; "
        f"first at offset {non_ascii[0][0]}"
    )


def test_this_drift_guard_is_ascii() -> None:
    """This test file MUST be 7-bit ASCII."""
    raw = Path(__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tests/test_u2500_hygiene.py has {len(non_ascii)} non-ASCII "
        f"bytes; first at offset {non_ascii[0][0]}"
    )
