"""Drift guard: every tracked .ps1 is EITHER UTF-8-BOM OR pure 7-bit ASCII.

Background (DEEP-AUDIT P3, cycle 18, item 413, 2026-06-14): the standing
no-em-dash / ASCII rule exists because Windows PowerShell 5.1 ParseFile
ANSI-decodes a *no-BOM* .ps1 - any UTF-8 multibyte glyph in such a file is
re-interpreted as cp1252 mojibake. When that glyph lands inside a
double-quoted string (e.g. a UTF-8 em-dash -> U+201D smart-quote) the
tokenizer sees a premature string terminator and the whole script fails to
parse (the 2026-05-18 gamepc_boot.ps1 incident).

Two postures remove the hazard entirely:
  * a UTF-8 BOM (EF BB BF) - PS5.1 then decodes the file as UTF-8, so the
    glyph survives intact (PROTECTIVE - never strip a .ps1 BOM); OR
  * the file is pure 7-bit ASCII - there is no multibyte byte to mangle.

This guard asserts NO tracked .ps1 is the dangerous third state
(no-BOM AND non-ASCII). Cycle 18 swept the last two offenders clean
(ops/rc_league_watcher.ps1, tools/bridge_watcher_update_check.ps1 - 501
box-draw + 3 arrow glyphs in comment dividers -> ASCII '-' / '->').

To repair a future violation, pick one:
  * make the file pure ASCII (sweep box-draw -> '-', arrows -> '->'); or
  * prepend a UTF-8 BOM if the non-ASCII content is intentional.

Scope mirrors tools/p3_ascii_census.py (the P3 slicer).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_UTF8_BOM = b"\xef\xbb\xbf"


def _tracked_ps1() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.ps1"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _first_non_ascii_offset(raw: bytes) -> int:
    for i, b in enumerate(raw):
        if b > 127:
            return i
    return -1


def test_no_ps1_is_nobom_and_nonascii() -> None:
    """No tracked .ps1 may be both BOM-less and non-ASCII (PS5.1 mojibake risk)."""
    violations: list[tuple[str, int]] = []
    seen = 0
    for rel in _tracked_ps1():
        p = _REPO_ROOT / rel
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        seen += 1
        if raw.startswith(_UTF8_BOM):
            continue  # BOM is protective
        off = _first_non_ascii_offset(raw)
        if off >= 0:
            violations.append((rel, off))
    assert seen > 0, "no .ps1 files discovered - guard would be vacuous"
    if violations:
        lines = [
            f"  {rel}: first non-ASCII byte at offset {off} (no BOM)"
            for rel, off in sorted(violations)
        ]
        pytest.fail(
            "PS5.1 ANSI-decode mojibake hazard: .ps1 files are BOM-less AND "
            "non-ASCII. Make them pure ASCII (box-draw -> '-', arrows -> '->') "
            "or prepend a UTF-8 BOM. Violations:\n" + "\n".join(lines)
        )


def test_this_drift_guard_is_ascii() -> None:
    """This test file MUST be 7-bit ASCII."""
    raw = Path(__file__).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not non_ascii, (
        f"tests/test_ps1_encoding_hygiene.py has {len(non_ascii)} non-ASCII "
        f"bytes; first at offset {non_ascii[0][0]}"
    )
