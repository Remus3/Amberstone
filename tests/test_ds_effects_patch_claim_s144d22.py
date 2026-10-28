"""Guard (RM-997): the item-effect modules claim no stale table patch.

``agents/daemon_slayer/effects.py`` said "Numbers below are pinned to patch
16.9.1 (matches ``data/daemon_slayer/current.txt``)". Both halves rotted: the
s246 split moved every number into ``_effects_data.py``, so there is nothing
"below", and current.txt moved on (16.21.1 at 2026-10-27). The
``ITEM_EFFECTS`` header in ``_effects_data.py`` carried the same claim as a bare
``# Patch 16.9.1 - refresh on patch bump`` line.

A per-row "Meraki bulk items (patch 16.10.1)" comment is dated provenance and
stays legal; what this guard refuses is a WHOLE-TABLE patch claim that is not
the live current.txt patch. The live patch is read from current.txt, never
from a literal. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DS = _REPO_ROOT / "agents" / "daemon_slayer"
_EFFECTS = _DS / "effects.py"
_DATA = _DS / "_effects_data.py"
_CURRENT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"
_PATCH = re.compile(r"\b\d+\.\d+\.\d+\b")
_TABLE_ASSIGN = "ITEM_EFFECTS: dict[str, ItemEffect] = {"


def _live_patch() -> str:
    patch = _CURRENT.read_text(encoding="utf-8").strip()
    assert _PATCH.fullmatch(patch), f"current.txt is not a patch literal: {patch!r}"
    return patch


def _docstring(path: Path) -> str:
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    assert doc, f"{path.name} has no module docstring"
    return doc


def _table_header_comments() -> list[str]:
    lines = _DATA.read_text(encoding="utf-8").splitlines()
    idx = [i for i, ln in enumerate(lines) if ln.startswith(_TABLE_ASSIGN)]
    assert len(idx) == 1, f"expected one {_TABLE_ASSIGN!r} line, got {len(idx)}"
    header: list[str] = []
    i = idx[0] - 1
    while i >= 0 and lines[i].startswith("#"):
        header.append(lines[i])
        i -= 1
    return header


def test_effects_docstring_recites_no_stale_patch():
    stale = [p for p in _PATCH.findall(_docstring(_EFFECTS)) if p != _live_patch()]
    assert not stale, f"effects.py docstring recites patch literal(s) {stale}; current.txt is {_live_patch()}"


def test_effects_docstring_points_at_the_data_module():
    doc = _docstring(_EFFECTS)
    assert "_effects_data.py" in doc, "effects.py docstring must name _effects_data.py as the home of the numbers"
    assert "Numbers below" not in doc, "effects.py holds no numbers since the s246 split"


def test_item_effects_header_claims_no_stale_table_patch():
    header = _table_header_comments()
    claims = [ln for ln in header if re.match(r"#\s*Patch\s+\d+\.\d+\.\d+", ln)]
    stale = [ln for ln in claims if _live_patch() not in ln]
    assert not stale, f"ITEM_EFFECTS header claims a table patch that is not current.txt: {stale}"


def test_data_docstring_recites_no_stale_patch():
    stale = [p for p in _PATCH.findall(_docstring(_DATA)) if p != _live_patch()]
    assert not stale, f"_effects_data.py docstring recites patch literal(s) {stale}"


def test_patch_regex_anchor():
    # Anchor: a regex that matched nothing would let every check above pass.
    assert _PATCH.findall("pinned to patch 16.9.1") == ["16.9.1"]
    assert re.match(r"#\s*Patch\s+\d+\.\d+\.\d+", "# Patch 16.9.1 - refresh on patch bump")
