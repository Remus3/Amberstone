"""Guard: ``_rune_health_grants.py`` cites by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0, after cycle 102 dropped its eleven
rune_procs.py / enemy_runes.py cites:

- ``_rune_health_grants.py`` still cited ``ehp.py:1411`` twice for
  ``is_ranged = _is_ranged(base)``, ``ehp.py:1791-1793`` for the per-type EHP
  numerators and ``ehp.py:1477`` for the ``heal_total`` line. All three had
  rotted (those lines of ``compute_ehp`` now sit some 370-550 lines lower),
  and the quoted ``heal_total`` expression had lost two terms since.
- It also cited ``_passive_health_overrides.py:33-38`` / ``:69-94`` (twice) /
  ``:107-109`` / ``:207-213`` (twice) and ``_rune_resist_grants.py:52-57``
  (eleven line cites in all). Those still resolved, but a line cite rots with
  any insert above it.
- Sibling sweep: ``_rune_self_heal.py`` cites ``_passive_health_overrides.py:33-38``
  twice, and ``_rune_flat_mitigation.py`` cites ``_rune_health_grants.py:441-445``
  for the flag paragraph and ``:312-324`` for ``stacks_at_level``. Both had
  rotted by 3 lines when cycle 102 grew the module docstring. Both siblings
  carry other line cites (out of this slice), so only these targets are
  pinned there.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import (
    _passive_health_overrides,
    _rune_health_grants,
    _rune_resist_grants,
    ehp,
)

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|``:\d")

TARGETS = {
    "_rune_health_grants.py": (
        'the ``_rune_resist_grants`` module docstring (its "Only three ids are '
        'SEEDED" allowlist paragraph)',
        "``_passive_health_overrides._SION_STACKS`` / ``_SWAIN_STACKS`` / "
        "``_CHO_STACKS`` for the curves, "
        "``_passive_health_overrides._stacks_at_level`` for the reader",
        "(the ``PassiveHealthEntry`` docstring and ``passive_health_stack_hp``)",
        "(the ``_passive_health_overrides`` module docstring)",
        "``compute_ehp`` already computes it as ``is_ranged = _is_ranged(base)``",
        "Convention copied verbatim from the _passive_health_overrides stack curves "
        "(_SION_STACKS / _SWAIN_STACKS / _CHO_STACKS):",
        "Identical semantics to ``_passive_health_overrides._stacks_at_level``; "
        "duplicated",
        "(the ``physical_ehp`` / ``magical_ehp`` / ``true_ehp`` numerators of "
        "``compute_ehp``, as ``rune_perm_hp``)",
        "(the ``heal_total`` line of ``compute_ehp``, ``heal_total = "
        "(heal_item_total + heal_lifesteal + rune_heal_hp + rune_self_heal_hp) * "
        "heal_amp_mult``, as ``rune_heal_hp``)",
        "``compute_ehp`` already has it as ``is_ranged = _is_ranged(base)``",
    ),
}

_SAME_TARGET = re.compile(
    r"(?:_passive_health_overrides|_rune_health_grants)\.py:\d"
)
SIBLINGS = {
    "_rune_self_heal.py": (
        "(the ``_passive_health_overrides`` module docstring: under-credit on "
        "purpose",
        "Conservative by construction, per the _passive_health_overrides "
        "module-docstring calibration rule",
    ),
    "_rune_flat_mitigation.py": (
        "mirroring ``_rune_health_grants.rune_health_grants`` (its own "
        "``apply_rune_health_grants`` gate):",
        "the same clamping semantics as ``_rune_health_grants.stacks_at_level``. "
        "A non-level-scaled",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "(8451) was modelled NOWHERE - ``_rune_resist_grants.py:52-57`` explicitly",
        "    tuple bounds (``_passive_health_overrides.py:69-94`` for the curves,",
        "    ``:207-213`` for the ``_stacks_at_level`` reader);",
        "``is_ranged``; ``compute_ehp`` already computes it at ``ehp.py:1411`` via",
        "# Convention copied verbatim from _passive_health_overrides.py:69-94: an",
        "      ``ext_flat_hp`` (``ehp.py:1791-1793``), so it lifts physical,",
        "      into the heal lane BEFORE ``heal_amp_mult`` (``ehp.py:1477``,",
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
        "(``_passive_health_overrides.py:33-38``: under-credit on purpose so a",
        "# Conservative by construction, per the _passive_health_overrides.py:33-38",
        "(``_rune_health_grants.py:441-445``): a caller that forgets the outer",
        "``_rune_health_grants.stacks_at_level`` (``_rune_health_grants.py:312-324``).",
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


def test_resist_registry_reads_and_rejects_overgrowth():
    doc = _flat(_rune_resist_grants.__doc__ or "")
    assert "Only three ids are SEEDED" in doc
    assert "8451 Overgrowth max health" in doc
    assert "8451" not in _rune_resist_grants._RUNE_RESIST_GRANTS


def test_passive_health_curves_are_18_entry_monotonic():
    for curve in (
        _passive_health_overrides._SION_STACKS,
        _passive_health_overrides._SWAIN_STACKS,
        _passive_health_overrides._CHO_STACKS,
    ):
        assert len(curve) == 18
        assert all(a <= b for a, b in zip(curve, curve[1:]))


def test_stacks_at_level_matches_its_source_reader():
    curve = _passive_health_overrides._SION_STACKS
    for level in (-3, 0, 1, 7, 18, 25):
        assert _rune_health_grants.stacks_at_level(curve, level) == (
            _passive_health_overrides._stacks_at_level(curve, level)
        )
    assert _rune_health_grants.stacks_at_level((), 5) == 0.0
    assert _passive_health_overrides._stacks_at_level((), 5) == 0.0


def test_passive_health_arithmetic_and_calibration_rule():
    entry_doc = _flat(_passive_health_overrides.PassiveHealthEntry.__doc__ or "")
    assert (
        "The credited bonus HP is ``hp_per_stack(level) * "
        "assumed_stacks_by_level[level-1]``"
    ) in entry_doc
    src = inspect.getsource(_passive_health_overrides.passive_health_stack_hp)
    assert "bonus = hp * stacks" in src
    module_doc = _flat(_passive_health_overrides.__doc__ or "")
    assert "midpoint under-credits on purpose" in module_doc


def test_compute_ehp_is_ranged_heal_total_and_numerators():
    src = inspect.getsource(ehp.compute_ehp)
    assert "is_ranged = _is_ranged(base)" in src
    assert (
        "heal_total = ( heal_item_total + heal_lifesteal + rune_heal_hp + "
        "rune_self_heal_hp ) * heal_amp_mult"
    ) in " ".join(src.split())
    assert "rune_perm_hp, rune_heal_hp = _rune_health_fn(" in src
    for lhs in ("physical_ehp = (", "magical_ehp = (", "true_ehp = ("):
        line = next(ln for ln in src.splitlines() if ln.strip().startswith(lhs))
        assert "+ rune_perm_hp +" in line, lhs


def test_rune_health_grants_carries_its_own_flag_gate():
    src = inspect.getsource(_rune_health_grants.rune_health_grants)
    assert "if not apply_rune_health_grants:\n        return 0.0, 0.0" in src
    assert _rune_health_grants.rune_health_grants(
        ["8437", "8451"], level=18, max_hp=3000.0
    ) == (0.0, 0.0)
