"""Guard: the iter-3 hydra-cleave test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. test_hydra_cleave_unique_iter3.py
named the comment its fix replaced as ``_effects_data.py:609-612``. That
comment is gone, and the iter-3 note that replaced it now sits above the
Profane Hydra ``"6698"`` row, about 280 lines lower. A cite that resolves
today rots on the next insert above it, so it goes.

The tests below pin the claims instead: the iter-3 note sits directly
above the ``"6698"`` row, and ``rank._filter_candidates`` still has no
Tiamat-tree check of its own (the dedup is ``unique_passive_key`` only).
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import rank

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_hydra_cleave_unique_iter3.py"
EFFECTS_DATA = DS / "_effects_data.py"
# ``_effects_data.py:609-612``. Not the port shape ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|\bat line \d")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("``_effects_data.py:609-612`` claimed Tiamat-tree")
    for sample in (
        'the comment above the Profane Hydra ``"6698"`` row claimed',
        "DS ``:8860`` serves the main checkout",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_source(TARGET).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_target_names_the_profane_hydra_row():
    assert 'Profane Hydra ``"6698"`` row' in _source(TARGET)


def test_iter3_note_sits_directly_above_the_6698_row():
    lines = _source(EFFECTS_DATA).splitlines()
    row = next(i for i, line in enumerate(lines) if line.strip() == '"6698": ItemEffect(')
    block = []
    for line in reversed(lines[:row]):
        if not line.strip().startswith("#"):
            break
        block.append(line)
    note = " ".join(line.strip().lstrip("#").strip() for line in reversed(block))
    assert "Iter 3 (2026-05-19)" in note, note
    assert 'unique_passive_key="hydra_cleave"' in note, note
    assert "build legality" in note, note


def test_filter_candidates_has_no_tiamat_tree_check():
    src = inspect.getsource(rank._filter_candidates).lower()
    for word in ("hydra", "tiamat", "cleave"):
        assert word not in src, word
