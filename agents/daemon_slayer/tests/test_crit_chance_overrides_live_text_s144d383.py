"""S144-D-383 - the R212 crit-chance registry matches the live text it cites.

WHY. ``_crit_chance_overrides`` (R212) carries its own champion-prose drift
guard (``test_crit_chance_overrides_r212.py`` re-reads the Yasuo / Yone /
Senna / Jhin fragments at the ``current.txt`` patch), and every fragment still
holds at 16.22.1. Two claims outside that guard had drifted or were unpinned:

* "grep 0.86 across agents/daemon_slayer/*.py returns nothing outside this
  module": since RM-118 (ENGINE 1.271.0) the grep also hits ``dps.py`` (a
  docstring) and ``server.py`` (a comment). The claim's real content - no
  0.86 LITERAL in code anywhere else, so no second multiplicative crit-damage
  axis - still holds, and is now pinned by an AST walk instead of a grep.
* "the SHIPPED IE carries crit_damage_bonus=0.30": true, and the live DDragon
  16.22.1 Infinity Edge line says "30% Critical Strike Damage"; nothing pinned
  the two together.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Docstring
fixes only; no registry value or code path changes.
"""

from __future__ import annotations

import ast
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from agents.daemon_slayer import _crit_chance_overrides as cco
from agents.daemon_slayer._effects_data import ITEM_EFFECTS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_PKG = _REPO_ROOT / "agents" / "daemon_slayer"
_MODULE = "_crit_chance_overrides.py"


def _patch() -> str:
    return (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _items() -> dict[str, Any]:
    raw = json.loads(
        (_DATA / _patch() / "items.json").read_text(encoding="utf-8")
    )
    return raw["data"]


def _flat(text: str) -> str:
    return " ".join(text.split())


_DOC = _flat(cco.__doc__ or "")


def _modules() -> list[Path]:
    mods = sorted(_PKG.glob("*.py"))
    assert len(mods) > 50
    return mods


def _code_literal_hits(path: Path, value: float) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) is float
        and node.value == value
    ]


def test_doc_is_nonempty():
    assert len(_DOC) > 1000


def test_no_086_code_literal_outside_the_module():
    hits = {
        p.name: _code_literal_hits(p, 0.86)
        for p in _modules()
        if _code_literal_hits(p, 0.86)
    }
    assert set(hits) == {_MODULE}


def test_text_mentions_of_086_are_the_named_two():
    text_hits = sorted(
        p.name
        for p in _modules()
        if p.name != _MODULE
        and re.search(r"(?<![\d.])0\.86(?!\d)", p.read_text(encoding="utf-8"))
    )
    assert text_hits == ["dps.py", "server.py"]
    for name in text_hits:
        assert _code_literal_hits(_PKG / name, 0.86) == []
        assert f"``{name}``" in _DOC
    assert "returns nothing outside this module" not in _DOC


def test_infinity_edge_shipped_bonus_matches_live_ddragon():
    rec = _items()["3031"]
    assert rec["name"] == "Infinity Edge"
    desc = _flat(re.sub(r"<[^>]+>", " ", rec["description"]))
    assert "30% Critical Strike Damage" in desc
    assert ITEM_EFFECTS["3031"].crit_damage_bonus == 0.30
    assert f'live DDragon {_patch()} line "30% Critical Strike Damage"' in _DOC


def test_ground_truth_block_names_the_live_patch():
    assert f"re-read unchanged at {_patch()}" in _DOC
