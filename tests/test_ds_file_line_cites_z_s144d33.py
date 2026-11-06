"""Guard: the RM-04 carry pool widen test cites rank.py by symbol (z).

Measured 2026-10-30 at ENGINE 1.290.0, re-deriving the RM-1053 "DS test
lines" residue with guard v's pattern over agents/daemon_slayer/tests. The
``test_rank_carry_pool_widen_rm04.py`` docstring cited four ``rank.py``
spans, and every one had drifted:

- ``OFFCLASS_MARKSMAN_ITEM_NAMES`` was cited at 83-127 (it now opens
  further down);
- the ``exclude_names`` hand-off was cited at 1044 (now the
  ``_filter_candidates`` call just after the ranged-marksman gate of
  ``rank_items``) and the name skip at 711-712
  (now further down ``_filter_candidates``);
- ``_SR_EXCLUDED_ITEM_IDS`` was cited at 170-188 (it now opens further
  down).

The tests below pin the cites, and the facts they restate, by symbol.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import rank

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_rank_carry_pool_widen_rm04.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%|-lines? (?=\d)")

SYMBOLS = (
    "``rank.OFFCLASS_MARKSMAN_ITEM_NAMES``, applied via "
    "``_filter_candidates(exclude_names=...)`` from the ranged-marksman "
    "gate in ``rank_items`` (the ``rec.get(\"name\") in exclude_names`` "
    "skip in ``_filter_candidates``)",
    "``rank._SR_EXCLUDED_ITEM_IDS``, the RM-93 support-quest deny",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "(rank.py:83-127), applied via ``_filter_candidates(exclude_names=...)``",
        "at rank.py:1044 / rank.py:711-712.",
        "``rank._SR_EXCLUDED_ITEM_IDS`` (rank.py:170-188), the RM-93",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for sample in SYMBOLS:
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    text = TARGET.read_text(encoding="utf-8")
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_names_the_symbols():
    flat = _flat(TARGET.read_text(encoding="utf-8"))
    for symbol in SYMBOLS:
        assert symbol in flat, symbol


def test_rank_items_hands_the_marksman_deny_to_the_filter():
    src = _flat(inspect.getsource(rank.rank_items))
    for clause in (
        "if champ_rec is not None and _is_ranged_marksman(champ_rec): "
        "exclude_names = OFFCLASS_MARKSMAN_ITEM_NAMES",
        "exclude_names = exclude_names - CARRY_POOL_WIDEN_ITEM_NAMES",
        "exclude_names=exclude_names,",
    ):
        assert clause in src, clause


def test_the_filter_skips_by_name():
    src = _flat(inspect.getsource(rank._filter_candidates))
    assert 'if exclude_names and rec.get("name") in exclude_names: continue' in src


def test_the_restated_deny_sets():
    assert frozenset({
        "Black Cleaver", "Spear of Shojin", "Stridebreaker", "Sterak's Gage",
    }) == rank.CARRY_POOL_WIDEN_ITEM_NAMES
    assert rank.CARRY_POOL_WIDEN_ITEM_NAMES <= rank.OFFCLASS_MARKSMAN_ITEM_NAMES
    assert "3877" in rank._SR_EXCLUDED_ITEM_IDS
