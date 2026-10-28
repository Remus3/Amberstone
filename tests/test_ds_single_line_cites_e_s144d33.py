"""Guard: four rune / omnivamp DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Each file below carried exactly one
line cite:

- ``test_route_omnivamp_seam_r193.py`` cited ``ehp.py:1251, consumed
  :1517-1521`` for ``compute_ehp``'s ``assume_max_stacks_omnivamp`` kwarg;
  both are stale (the kwarg is declared ~200 lines lower and consumed ~270
  lines lower).
- ``test_rune_health_seam_r136.py`` cited ``rune_procs.py:606`` for the Grasp
  8437 formula's "(heal + permanent-HP sides not modeled)" admission; it
  still resolves, but a line cite rots on the next edit above it.
- ``test_rune_hsp_amp_r136.py`` cited ``_hsp_amp.py:23`` for the item-only
  HSP sum; :23 is now the first parameter of ``sum_wielder_hsp_pct``, one
  line under its def.
- ``test_rune_offense_grants_r145.py`` cited ``rune_procs.py:212`` for the
  "caller multiplies by the live stack count (max 12)" comment; that comment
  now sits on :213, inside ``_conqueror_adaptive``.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _hsp_amp, ehp, rune_procs

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "test_route_omnivamp_seam_r193.py": ("``ehp.compute_ehp``",),
    "test_rune_health_seam_r136.py": ("``rune_procs.RUNE_PROCS[8437].formula``",),
    "test_rune_hsp_amp_r136.py": ("``_hsp_amp.sum_wielder_hsp_pct`` sums",),
    "test_rune_offense_grants_r145.py": ("``rune_procs._conqueror_adaptive``",),
}


def test_pattern_matches_the_old_shapes():
    for sample in (
        "since 2026-07-10 (ehp.py:1251, consumed :1517-1521) that credits the",
        "Grasp 8437's SELF side (heal + permanent health). ``rune_procs.py:606``",
        "``_hsp_amp.py:23`` sums ``heal_shield_amp_pct`` across EQUIPPED ITEMS",
        "``rune_procs.py:212`` assigns the live stack count to the CALLER",
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    for symbol in TARGETS[name]:
        assert symbol in text, f"{name}: {symbol}"


def test_compute_ehp_declares_and_consumes_the_omnivamp_kwarg():
    param = inspect.signature(ehp.compute_ehp).parameters[
        "assume_max_stacks_omnivamp"
    ]
    assert param.default is False
    src = inspect.getsource(ehp.compute_ehp)
    assert "if assume_max_stacks_omnivamp:" in src
    assert "item_omnivamp_fraction(" in src


def test_grasp_formula_admits_the_self_side_is_unmodeled():
    grasp = rune_procs.RUNE_PROCS[8437]
    assert grasp.rune_id == 8437
    assert "(heal + permanent-HP sides not modeled)" in grasp.formula


def test_sum_wielder_hsp_pct_reads_items_only():
    params = list(inspect.signature(_hsp_amp.sum_wielder_hsp_pct).parameters)
    assert params[0] == "item_ids"
    assert not any("rune" in p for p in params)
    src = inspect.getsource(_hsp_amp.sum_wielder_hsp_pct)
    assert "formula.heal_shield_amp_pct" in src


def test_conqueror_adaptive_leaves_stacks_to_the_caller():
    src = inspect.getsource(rune_procs._conqueror_adaptive)
    assert "the caller multiplies by the live stack count (max 12)" in src
