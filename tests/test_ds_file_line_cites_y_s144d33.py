"""Guard: the four geometry accessor tests cite the shape classifier by
symbol (y).

Measured 2026-10-30 at ENGINE 1.290.0, re-deriving the RM-1053 "DS test
lines" residue with guard v's pattern over agents/daemon_slayer/tests. Each
of the four schema-lift docstrings below cited one ``geometry.py`` line for
the ``classify_spell_shape`` branch that reads its datum as a presence flag:

- ``test_missile_width_item338.py`` cited line 84 (the ``line_width`` test
  now sits further down);
- ``test_cone_angle_item340.py`` cited line 90 and
  ``test_cone_distance_item341.py`` cited line 89 (the cone test moved);
- ``test_cast_radius_item342.py`` cited line 102 (still the circle branch
  comment, cited by symbol for the same reason).

The tests below pin the cites, and the facts they restate, by symbol.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import geometry, missile

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%|-lines? (?=\d)")

TARGETS = {
    "test_missile_width_item338.py": (
        "(the line branch of ``classify_spell_shape``)",
    ),
    "test_cone_angle_item340.py": (
        "(the cone branch of ``classify_spell_shape``: "
        '``geometry.get("cone_angle") is not None``)',
    ),
    "test_cone_distance_item341.py": (
        "(the cone branch of ``classify_spell_shape``: "
        '``geometry.get("cone_distance") is not None``)',
    ),
    "test_cast_radius_item342.py": (
        "(the circle branch of ``classify_spell_shape``: "
        "``cast_radius is not None AND NOT conflated AND not a sentinel``)",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "line 84) and ``missile._distance_from_geometry`` explicitly",
        'classifier, line 90 ``geometry.get("cone_angle") is not None``) and',
        'classifier, line 89 ``geometry.get("cone_distance") is not None``)',
        'presence flag (geometry.py line 102,',
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((TESTS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_the_classifier_reads_each_datum_as_a_presence_flag():
    src = _flat(inspect.getsource(geometry.classify_spell_shape))
    for clause in (
        'geometry.get("line_width") is not None',
        'geometry.get("cone_distance") is not None',
        'geometry.get("cone_angle") is not None',
        "cast_radius is not None and not cast_radius_conflated and "
        "cast_radius not in _CONFLATED_RADIUS_SENTINELS",
    ):
        assert clause in src, clause


@pytest.mark.parametrize(
    ("geo", "shape"),
    [
        ({"line_width": 70.0}, "line"),
        ({"cone_angle": 20.0}, "cone"),
        ({"cone_distance": 700.0}, "cone"),
        ({"cast_radius": 275.0, "cast_radius_conflated": False}, "circle"),
        ({"cast_radius": 275.0, "cast_radius_conflated": True}, "point"),
        ({"cast_radius": 210.0, "cast_radius_conflated": False}, "point"),
    ],
)
def test_the_branches_classify_as_cited(geo, shape):
    assert geometry.classify_spell_shape(geo) == shape


def test_travel_distance_rejects_line_width():
    doc = _flat(missile._distance_from_geometry.__doc__ or "")
    assert "a perpendicular width, not a travel length, so it is never used here" in doc
    assert missile._distance_from_geometry({"line_width": 900.0}) is None
