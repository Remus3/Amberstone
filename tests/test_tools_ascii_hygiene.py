"""Drift guard: the two host tools swept by R217-U2 must stay 7-bit ASCII.

R217-U2 (2026-07-28) swept the non-ASCII residue out of two host-only tools:

    tools/extract_panels.py   pre=189 bytes -> post=0
    tools/rc_facts.py         pre=10  bytes -> post=0

Replacement doctrine is the item-176 one: 1:1 character substitution that
preserves visual width and semantic intent (U+2500 box rule -> '-',
U+25B6 -> '>', U+2022 -> '*', U+00B7 -> '-', U+26A0 -> '!'), never a
re-flow of the surrounding text.

tools/p3_ascii_sweep.py is EXEMPT and is pinned as such below: its
non-ASCII bytes ARE the sweeper's own inventory of the glyphs it hunts,
so "cleaning" that file disarms the tool. The exemption test fails if a
future sweep strips it, which is the failure mode worth catching.

Scope note: this guard is a per-file pin, not a repo-wide ASCII ban.
U+2500 in particular is still intentional in many authored files
(web/js/main.js alone carries 1310). Extend the pin only alongside an
actual sweep of the file being added.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Swept by R217-U2. Every entry must hold zero bytes > 0x7F.
_SWEPT: frozenset[str] = frozenset({
    "tools/extract_panels.py",
    "tools/rc_facts.py",
})

# Deliberately NOT swept - see the module docstring.
_EXEMPT = "tools/p3_ascii_sweep.py"


def _non_ascii(path: Path) -> list[tuple[int, int]]:
    return [(i, b) for i, b in enumerate(path.read_bytes()) if b > 127]


@pytest.mark.parametrize("rel_posix", sorted(_SWEPT))
def test_swept_tool_is_pure_ascii(rel_posix: str) -> None:
    p = _REPO_ROOT / rel_posix
    assert p.is_file(), f"swept tool missing at {p}"
    bad = _non_ascii(p)
    assert not bad, (
        f"{rel_posix} has {len(bad)} non-ASCII bytes (first at offset "
        f"{bad[0][0]}). R217-U2 swept this file clean; replace the glyph "
        f"with its 1:1 ASCII equivalent rather than reverting the sweep."
    )


def test_p3_ascii_sweep_exemption_is_intact() -> None:
    """The sweeper keeps its glyph inventory - do not 'clean' it."""
    p = _REPO_ROOT / _EXEMPT
    assert p.is_file(), f"exempt tool missing at {p}"
    assert _non_ascii(p), (
        f"{_EXEMPT} is now pure ASCII. Those bytes were the sweeper's own "
        f"catalogue of the glyphs it detects; stripping them disarms the "
        f"tool. Restore them and keep the file on the exemption list."
    )


def test_panel_import_rule_keeps_the_generated_width() -> None:
    """The ASCII rule the extractor emits must match the width it replaced.

    Read via ast rather than import: tools/extract_panels.py is a spent
    one-shot that rewrites web/js/main.js at module scope, so importing it
    would destroy the file this test reads.
    """
    src = (_REPO_ROOT / "tools" / "extract_panels.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    emitted = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PANEL_IMPORTS" for t in node.targets
        ):
            emitted = ast.literal_eval(node.value)
    assert emitted is not None, "PANEL_IMPORTS assignment not found"

    rule_line = next(
        ln for ln in emitted.splitlines() if "Panel modules" in ln
    )
    on_disk = next(
        ln
        for ln in (_REPO_ROOT / "web" / "js" / "main.js")
        .read_text(encoding="utf-8")
        .splitlines()
        if "Panel modules" in ln
    )
    assert rule_line.isascii(), f"emitted rule is not ASCII: {rule_line!r}"
    assert len(rule_line) == len(on_disk), (
        f"emitted rule width {len(rule_line)} != generated width "
        f"{len(on_disk)}; the sweep must be a 1:1 character substitution."
    )


def test_this_drift_guard_is_ascii() -> None:
    bad = _non_ascii(Path(__file__))
    assert not bad, (
        f"tests/test_tools_ascii_hygiene.py has {len(bad)} non-ASCII bytes; "
        f"first at offset {bad[0][0]}"
    )
