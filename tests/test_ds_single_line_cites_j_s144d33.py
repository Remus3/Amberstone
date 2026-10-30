"""Guard: ``ehp.py`` cites by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0:

- ``ehp.py`` cited ``ehp.py:1725`` for the ``max_mana = float(stats.get("mp",
  0.0))`` line of ``compute_ehp`` (rotted: that line now sits some 50 lines
  lower, and 1725 is inside the input-validation block).
- ``ehp.py`` cited ``ehp.py:30`` twice for the "Caster-side enemy
  pen/reduction" bullet of its own module docstring, ``rune_procs.py:606`` for
  the Grasp formula admission "(heal + permanent-HP sides not modeled)" and
  ``enemy_runes.py:213/:215/:216`` for the Grasp ``poke_heal_pct`` /
  ``perm_hp`` / ``ranged_factor`` fields. Those four still resolved, but a
  line cite rots with any insert above it.
- Sibling sweep: ``_rune_health_grants.py`` cites the same targets
  (``rune_procs.py:606`` / ``:597-610`` and ``enemy_runes.py:213`` / ``:215`` /
  ``:216`` / ``:130-133`` / ``:201-217``) on eleven lines. It still carries other
  line cites (out of this slice), so only these targets are pinned there.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import ehp, enemy_runes, rune_procs

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "ehp.py": (
        '(the ``max_mana = float(stats.get("mp", 0.0))`` line of '
        "``compute_ehp``)",
        "the ``RUNE_PROCS[8437]`` formula in rune_procs.py scores Grasp's "
        "DAMAGE and admits verbatim",
        'the long-standing "Caster-side enemy pen/reduction" deliberate '
        "omission in the module docstring",
        "on the ``ENEMY_RUNE_THREATS[8437]`` entry in enemy_runes.py "
        "(poke_heal_pct / perm_hp / ranged_factor)",
        'closes the module docstring\'s deliberate Phase-1 omission "Caster-side '
        "enemy pen/reduction",
    ),
}

_SAME_TARGET = re.compile(
    r"(?:rune_procs\.py:(?:606|597-610)\b"
    r"|enemy_runes\.py:(?:213|215|216|130-133|201-217)\b"
    r"|ehp\.py:(?:30|1725)\b)"
)
SIBLINGS = {
    "_rune_health_grants.py": (
        "its own formula string admits the gap verbatim in the "
        "``RUNE_PROCS[8437]`` entry:",
        "``ENEMY_RUNE_THREATS[8437].poke_heal_pct`` ``poke_heal_pct=0.013``",
        "``ENEMY_RUNE_THREATS[8437].perm_hp`` ``perm_hp=5.0``",
        "``ENEMY_RUNE_THREATS[8437].ranged_factor`` ``ranged_factor=0.40``",
        "(fields declared on the ``EnemyRuneThreat`` dataclass; the whole entry is "
        "``ENEMY_RUNE_THREATS[8437]``)",
        "(ENEMY_RUNE_THREATS[8437].poke_heal_pct)",
        "(ENEMY_RUNE_THREATS[8437].perm_hp)",
        "(ENEMY_RUNE_THREATS[8437].ranged_factor)",
        "is ALREADY scored by the RUNE_PROCS[8437] entry in rune_procs.py",
        "This entry closes that entry's own formula admission,",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        '# (``ehp.py:1725``, ``float(stats.get("mp", 0.0))``) and merely forwarded',
        "#     self-side heal/permanent-HP (rune_procs.py:606 scores Grasp's DAMAGE",
        "standing ehp.py:30 deliberate omission). ARMOR order: % shred (clamped",
        "# at enemy_runes.py:213/:215/:216, restated so the two sides cannot drift.",
        "# pre-seam EHP math (closes the ehp.py:30 deliberate Phase-1 omission",
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_same_target_pattern_matches_the_old_shapes():
    for sample in (
        '``rune_procs.py:606``: "(heal + permanent-HP sides not modeled)". Overgrowth',
        "* ``enemy_runes.py:213``  ``poke_heal_pct=0.013``   -> ``_GRASP_HEAL_PCT_MAX_HP``",
        "* ``enemy_runes.py:215``  ``perm_hp=5.0``           -> ``_GRASP_PERM_HP_PER_PROC``",
        "* ``enemy_runes.py:216``  ``ranged_factor=0.40``    -> ``_GRASP_RANGED_FACTOR``",
        "(field declarations at ``enemy_runes.py:130-133``; the whole 8437 entry spans",
        "``enemy_runes.py:201-217``). They are RESTATED here rather than imported: an",
        "# DAMAGE side (3.5% max health) is ALREADY scored by rune_procs.py:597-610",
        "# This entry closes that module's own admission at rune_procs.py:606,",
    ):
        assert _SAME_TARGET.search(sample), sample
    for symbols in SIBLINGS.values():
        for sample in symbols:
            assert not _SAME_TARGET.search(sample), sample


@pytest.mark.parametrize("name", sorted(SIBLINGS))
def test_siblings_drop_the_same_targets(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _SAME_TARGET.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)
    flat = _flat(text)
    for symbol in SIBLINGS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_compute_ehp_reads_total_mana_into_max_mana():
    src = inspect.getsource(ehp.compute_ehp)
    assert 'max_mana = float(stats.get("mp", 0.0))' in src
    assert "max_mana=max_mana" in src


def test_ehp_docstring_carries_the_caster_side_pen_bullet():
    doc = ehp.__doc__ or ""
    _head, sep, tail = doc.partition("Phase 1 deliberate omissions:")
    assert sep, "ehp module docstring lost its omissions list"
    bullets = [ln for ln in tail.splitlines() if ln.startswith("* ")]
    assert any(
        b.startswith("* Caster-side enemy pen/reduction") for b in bullets
    ), bullets


def test_grasp_rune_proc_formula_admits_the_self_side_gap():
    assert "(heal + permanent-HP sides not modeled)" in (
        rune_procs.RUNE_PROCS[8437].formula
    )


def test_enemy_grasp_entry_carries_the_restated_magnitudes():
    grasp = enemy_runes.ENEMY_RUNE_THREATS[8437]
    assert grasp.poke_heal_pct == pytest.approx(0.013)
    assert grasp.perm_hp == pytest.approx(5.0)
    assert grasp.ranged_factor == pytest.approx(0.40)
