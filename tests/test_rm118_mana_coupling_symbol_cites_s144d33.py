"""Guard: the RM-118 mana-coupling seam cites by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Three line cites, all true at
c891a657b (RM-118, 2026-08-02), had rotted:
- ``agents/daemon_slayer/_mana_damage_coupling.py`` and
  ``agents/daemon_slayer/tests/test_mana_damage_coupling_rm118.py`` cited
  ``ability_dps.py:299-300`` for the ``caster_max_mp`` / ``caster_bonus_mp``
  derivation; at HEAD those two lines sit at 301-302 inside
  ``AbilityContext.from_build``.
- The ``BonusBasisTests`` docstring cited ``ehp.py:3603-3615`` for the mana
  lane's ``pct_base == "bonus"`` branch; at HEAD that branch starts near line
  3662 inside ``rank_items_by_ehp``.

The tests below pin the claims by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import ehp
from agents.daemon_slayer.ability_dps import AbilityContext

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGETS = (
    DS / "_mana_damage_coupling.py",
    DS / "tests" / "test_mana_damage_coupling_rm118.py",
)
_LINE_CITE = re.compile(r"(?<![\w.])(?:ability_dps|ehp)\.py:\d")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "# (ability_dps.py:299-300), so seeding",
        "derived at ``ability_dps.py:299-300``, so his R",
        'branch (``ehp.py:3603-3615``).',
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``ability_dps.AbilityContext.from_build``",
        "``ehp.rank_items_by_ehp``",
        "a dps.py:34 cite belongs to another guard",
        "a _item_ehp.py:12 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_rm118_files():
    hits = [
        f"{path.name}:{n}: {line.strip()}"
        for path in TARGETS
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_rm118_files_name_the_symbols():
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        assert "AbilityContext.from_build" in text, path.name
    test_text = TARGETS[1].read_text(encoding="utf-8")
    assert "``ehp.rank_items_by_ehp``" in test_text


def test_from_build_still_derives_both_mana_fields():
    src = inspect.getsource(AbilityContext.from_build)
    assert 'caster_max_mp = float(stats.get("mp", 0.0))' in src
    assert "caster_bonus_mp = max(0.0, caster_max_mp" in src
    assert "caster_max_mp=caster_max_mp," in src
    assert "caster_bonus_mp=caster_bonus_mp," in src


def test_rank_items_by_ehp_still_owns_the_mana_bonus_branch():
    src = inspect.getsource(ehp.rank_items_by_ehp)
    assert 'if _mana_coupling.pct_base == "bonus":' in src
    assert 'baseline.max_mana - float(_hcpl_resolved.base_stats.get("mp", 0.0))' in src
