"""Guard: ``_rune_flat_mitigation.py`` cites by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0, after cycle 103 dropped its two
``_rune_health_grants.py`` cites:

- ``_rune_flat_mitigation.py`` cited ``ehp.py:1659-1661`` and
  ``ehp.py:1884-1886`` for the champion lane's ``flat_mit_*`` terms. Both had
  rotted (those lines now sit in the ``compute_ehp`` docstring and the
  crit-vamp call), and ``compute_ehp`` now folds the rune lane INTO those
  same ``flat_mit_*`` locals.
- It cited ``_passive_damage_overrides.py:215-220`` / ``:202-220`` for the
  ``_lerp_per_level`` rounding and its ``rank_at_level('P', level)``
  convention. Both had rotted (the primitive now starts some 8 lines lower).
- It also cited ``_rune_resist_grants.py:55-57`` / ``:86-97``,
  ``_passive_flat_mitigation_overrides.py:92`` / ``:119-120`` / ``:78-81``
  (nine line cites in all) and the champion sibling's "lines 28-35". Those
  still resolved, but a line cite rots with any insert above it.
- Twice it called the ``compute_ehp`` seam "eventual"; the
  ``apply_rune_flat_mitigation`` kwarg has been on ``compute_ehp`` since RM-101.
- Sibling sweep: ``tests/test_rune_flat_mitigation_rm101.py`` repeats three of
  the same cites (``:55-57``, ``:92``, ``:215-220``), and
  ``_rune_shield_grants.py`` cites ``_rune_resist_grants.py:52-57`` (the same
  allowlist paragraph) and ``:273-275`` twice (the percent-of-BONUS clamp of
  ``rune_resist_grants``). ``_rune_shield_grants.py`` carries one other line
  cite, out of this slice, so only these targets are pinned there.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import (
    _passive_damage_overrides,
    _passive_flat_mitigation_overrides,
    _rune_flat_mitigation,
    _rune_resist_grants,
    ehp,
)

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|``:\d|\blines \d")

TARGETS = {
    "_rune_flat_mitigation.py": (
        'the ``_rune_resist_grants`` module docstring (its "Only three ids are '
        'SEEDED" allowlist paragraph) names 8473 explicitly as REJECTED',
        "``_ASSUMED_FLAT_DR_INSTANCES = 6.0`` in "
        "``_passive_flat_mitigation_overrides``,",
        "the ``_rune_resist_grants._RUNE_ACTIVE_RESIST_PROB`` comment makes for "
        "Aftershock and Unflinching",
        'expected uptime midpoint", the '
        "``PassiveFlatMitigationEntry`` docstring)",
        "the ``compute_ehp`` ``apply_rune_flat_mitigation`` seam",
        "the champion lane's ``flat_mit_*`` locals of ``compute_ehp``",
        "(its PRE-VS-POST-MITIGATION SIMPLIFICATION paragraph)",
        "(``_passive_flat_mitigation_overrides.PHYS`` / ``MAG`` / ``TRUE`` / "
        "``ANY``)",
        "ROUNDS TO 6 PLACES (the ``round(..., 6)`` in "
        "``_passive_damage_overrides._lerp_per_level``)",
        "(the ``_passive_damage_overrides._lerp_per_level`` docstring)",
        "the ``physical_ehp`` / ``magical_ehp`` / ``true_ehp`` numerators of "
        "``compute_ehp``",
    ),
}

_SAME_TARGET = re.compile(
    r"(?:_rune_resist_grants|_passive_flat_mitigation_overrides"
    r"|_passive_damage_overrides|ehp)\.py:\d"
)
SIBLINGS = {
    "tests/test_rune_flat_mitigation_rm101.py": (
        'The ``_rune_resist_grants`` module docstring (its "Only three ids are '
        'SEEDED" allowlist paragraph) names 8473',
        "``_ASSUMED_FLAT_DR_INSTANCES = 6.0`` in "
        "``_passive_flat_mitigation_overrides``",
        "(the ``round(..., 6)`` in ``_passive_damage_overrides._lerp_per_level``)",
    ),
    "_rune_shield_grants.py": (
        'in the ``_rune_resist_grants`` module docstring (its "Only three ids '
        'are SEEDED" allowlist paragraph: "8465 Guardian ally shield")',
        "resist term of ``_rune_resist_grants.rune_resist_grants`` (its "
        '``pct_base == "bonus"`` branch)',
        "the percent-of-BONUS clamp of ``_rune_resist_grants.rune_resist_grants``",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "axis, and ``_rune_resist_grants.py:55-57`` names 8473 explicitly as",
        "``_ASSUMED_FLAT_DR_INSTANCES = 6.0`` "
        "(``_passive_flat_mitigation_overrides.py:92``),",
        "    This is the identical argument ``_rune_resist_grants.py:86-97`` makes",
        "``flat_mit_*`` terms (``ehp.py:1659-1661``), NOT the denominator - a flat",
        "simplification documented in the champion sibling's module docstring "
        "(lines 28-35)",
        "# (``_passive_flat_mitigation_overrides.py:78-81``) so the two lanes",
        "# ROUNDS TO 6 PLACES (``_passive_damage_overrides.py:215-220``), so",
        "    (``ehp.py:1884-1886``). More prevented damage = a larger numerator",
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
    text = (DS / name).read_text(encoding="utf-8")
    flat = _flat(text)
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"
    assert "eventual" not in text


def test_same_target_pattern_matches_the_old_shapes():
    for sample in (
        "explicitly READ AND REJECTED Guardian at ``_rune_resist_grants.py:52-57``",
        "resist term at ``_rune_resist_grants.py:273-275``, so a below-base build",
        "(``_passive_damage_overrides.py:215-220``), so the level-13 element is",
        "(``_passive_flat_mitigation_overrides.py:92``) - an operator-tunable",
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


def test_resist_registry_rejects_bone_plating_and_guardian():
    doc = _flat(_rune_resist_grants.__doc__ or "")
    assert "Only three ids are SEEDED" in doc
    assert "8473 Bone Plating is a flat per-instance damage BLOCK" in doc
    assert "8465 Guardian ally shield" in doc
    assert "8473" not in _rune_resist_grants._RUNE_RESIST_GRANTS
    assert "8465" not in _rune_resist_grants._RUNE_RESIST_GRANTS


def test_active_resist_prob_comment_argues_engagement_sync():
    src = inspect.getsource(_rune_resist_grants)
    head = src[: src.index("_RUNE_ACTIVE_RESIST_PROB: float = 0.3")]
    comment = _flat(head[head.rindex("# Operator-tunable amortization"):])
    assert "ENGAGEMENT-SYNCHRONIZED" in comment
    assert "Aftershock" in comment and "Unflinching" in comment


def test_resist_bonus_clamp_is_floored_at_zero():
    src = inspect.getsource(_rune_resist_grants.rune_resist_grants)
    assert 'if entry.pct_base == "bonus":' in src
    assert "res_a = max(0.0, total_armor - base_armor)" in src
    assert "res_m = max(0.0, total_mr - base_mr)" in src


def test_flat_sibling_symbols_hold():
    pfmo = _passive_flat_mitigation_overrides
    assert pfmo._ASSUMED_FLAT_DR_INSTANCES == 6.0
    assert (pfmo.PHYS, pfmo.MAG, pfmo.TRUE, pfmo.ANY) == (
        _rune_flat_mitigation.PHYS,
        _rune_flat_mitigation.MAG,
        _rune_flat_mitigation.TRUE,
        _rune_flat_mitigation.ANY,
    )
    entry_doc = _flat(pfmo.PassiveFlatMitigationEntry.__doc__ or "")
    assert "amortizes a cooldown-gated active by its expected uptime midpoint" in (
        entry_doc
    )
    assert "PRE-VS-POST-MITIGATION SIMPLIFICATION" in (pfmo.__doc__ or "")


def test_lerp_per_level_rounds_and_names_rank_at_level():
    lerp = _passive_damage_overrides._lerp_per_level
    assert "round(" in inspect.getsource(lerp) and ", 6)" in inspect.getsource(lerp)
    assert "rank_at_level('P', level)" in (lerp.__doc__ or "")
    assert lerp(30.0, 60.0)[12] == 51.176471


def test_compute_ehp_folds_the_rune_lane_into_flat_mit():
    assert "apply_rune_flat_mitigation" in inspect.signature(ehp.compute_ehp).parameters
    src = inspect.getsource(ehp.compute_ehp)
    for axis in ("phys", "mag", "true"):
        assert f"flat_mit_{axis} += rune_flat_mit_{axis}" in src
    for lhs, term in (
        ("physical_ehp = (", "+ flat_mit_phys +"),
        ("magical_ehp = (", "+ flat_mit_mag +"),
        ("true_ehp = (", "+ flat_mit_true +"),
    ):
        line = next(ln for ln in src.splitlines() if ln.strip().startswith(lhs))
        assert term in line, lhs
