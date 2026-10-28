"""Guard: the R193 crit-vamp test cites the crit cap by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring and the
``CritCapTests`` class docstring of
``agents/daemon_slayer/tests/test_ehp_crit_weighted_vamp_r193.py`` cited the
engine's 1.0 crit cap as ``engine.py:185``, written by c69a575df (R193 slice
B), when that line was the "Crit capped at 1.0" docstring line of
``engine._combine_items``. At HEAD line 185 is the docstring's "Special cases"
line and the clamp itself sits about 37 lines lower, so both cites rotted.
ehp.py's own copy of the cite was already moved to ``engine._combine_items``
by the sibling guard ``test_ehp_crit_vamp_symbol_cites_s144d33.py``.

The tests below pin the cite and the claim by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import ehp, engine

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_ehp_crit_weighted_vamp_r193.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("the engine's 1.0 crit cap (engine.py:185)")
    for sample in (
        "the engine's 1.0 crit cap (``engine._combine_items``)",
        "no live :8860, no network",
        "HEAD e2f6e599",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_the_r193_test():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_r193_test_names_the_crit_cap_symbol_twice():
    assert _target().count("``engine._combine_items``") >= 2


def test_combine_items_caps_crit_at_one():
    src = inspect.getsource(engine._combine_items)
    assert 'if out.get("crit", 0.0) > 1.0:' in src
    assert 'out["crit"] = 1.0' in src


def test_multiplier_clamps_crit_at_one_like_the_engine():
    src = inspect.getsource(ehp._crit_weighted_vamp_multiplier)
    assert "crit_total = min(max(0.0, crit_chance) + max(0.0, crit_from_effects), 1.0)" in src
    capped = ehp._crit_weighted_vamp_multiplier([], 1.0, assume_crit_weighted_vamp=True)
    over = ehp._crit_weighted_vamp_multiplier([], 1.5, assume_crit_weighted_vamp=True)
    assert over == capped
