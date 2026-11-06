"""Guard: augment_formula_eval and data_loader cite by symbol (t).

Measured 2026-10-30 at ENGINE 1.290.0. Four line cites in two DS modules had
all rotted:

- ``augment_formula_eval.py`` cited ``ability_dps.py:1113`` for where item
  AH lands (now a docstring line of another flag; the lane is
  ``compute_ability_dps`` passing ``total_item_ability_haste`` into
  ``_total_ability_haste``), and its own history note restated an older
  rotted cite ``ability_dps.py:49``.
- ``data_loader.py`` cited ``core/augment_external_source.py:445`` for
  ``_norm_name`` (now :514) and ``coaches/arena_coach.py:264-272`` for the
  ``name.lower().replace(" ", "")`` shape (now in ``_augment_name_map`` and
  ``_resolve_augment_apiname``).

The tests below pin the cites, and the facts they restated, by symbol.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import ability_dps, data_loader
from coaches import arena_coach
from core import augment_external_source

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b")

TARGETS = {
    "augment_formula_eval.py": (
        "``_item_ability_haste.total_item_ability_haste``, which "
        "``ability_dps.compute_ability_dps`` adds into "
        "``ability_dps._total_ability_haste``.",
        "(An older comment here cited a line of ``ability_dps.py`` for",
    ),
    "data_loader.py": (
        "``_norm_name`` in ``core/augment_external_source.py`` (and the "
        'same ``name.lower().replace(" ", "")`` shape in '
        "``coaches/arena_coach.py`` ``_augment_name_map`` and "
        "``_resolve_augment_apiname``)",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "#    via ``_item_ability_haste`` into ``ability_dps.py:1113``.",
        '#    comment here cited `ability_dps.py:49` for "the engine',
        "``core/augment_external_source.py:445`` (and the same",
        "``coaches/arena_coach.py:264-272``) rather than inventing",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_compute_ability_dps_feeds_item_ah_into_total_ability_haste():
    src = inspect.getsource(ability_dps.compute_ability_dps)
    assert re.search(
        r"base_ah = total_item_ability_haste\(resolved\.item_ids\)", src)
    assert re.search(
        r"_total_ability_haste\(resolved\.stats, mode, base_ah=base_ah\)",
        src)


@pytest.mark.parametrize("raw", [
    "The Brutalizer", "the-brutalizer", " TheBrutalizer! ", "BREAD AND",
    "", None,
])
def test_norm_augment_key_mirrors_norm_name(raw):
    assert data_loader._norm_augment_key(raw) == (
        augment_external_source._norm_name(raw or ""))


def test_arena_coach_hosts_the_lower_replace_shape():
    for fn in (arena_coach._augment_name_map,
               arena_coach._resolve_augment_apiname):
        assert '.lower().replace(" ", "")' in inspect.getsource(fn), (
            fn.__name__)
