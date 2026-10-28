"""Guard: the RM-90 enchanter-pool test cites hps.py by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_enchanter_pool_hsp_rm90.py`` carried one
``hps.py`` line cite, true at a8c3fd655 (RM-90, 2026-07-18):
- ``hps.py:871`` was the ``enchanter_only: bool = True,`` parameter of
  ``rank_items_by_hps``; at HEAD that parameter sits near line 919 and line
  871 is inside ``HpsResult.format_table``.

The tests below pin the claim by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import hps

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_enchanter_pool_hsp_rm90.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])hps\.py:\d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("(`enchanter_only=True`,\n`hps.py:871`); every")
    for sample in (
        "``hps.rank_items_by_hps``",
        "a dps.py:34 cite belongs to another guard",
        "a _item_hps.py:12 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_hps_line_cite_left_in_rm90():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_rm90_names_the_symbols():
    text = _target()
    assert "`hps.rank_items_by_hps`" in text
    assert "`hps.compute_hps`" in text


def test_rank_items_by_hps_still_defaults_to_the_enchanter_pool():
    param = inspect.signature(hps.rank_items_by_hps).parameters["enchanter_only"]
    assert param.default is True
    src = inspect.getsource(hps.rank_items_by_hps)
    assert "elif enchanter_only:" in src
    assert "registry_ids = set(snap_formulas.item_ids())" in src


def test_compute_hps_still_zeroes_non_registry_items():
    doc = inspect.getdoc(hps.compute_hps) or ""
    assert "contribute zero" in doc
    assert "non-enchanter items" in doc
