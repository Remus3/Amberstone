"""S144-D-225..229 - the per-spell CC registries in ``_per_spell_cc.py`` name
only live champions and spells, carry sane per-rank values, never clobber a
slot, keep each flat row inside its distance range, and say in their own
comments the values they ship.

WHY. ``_PER_SPELL_CC_DURATIONS`` (read at runtime by ``cc_pressure`` and,
through it, ``compute_ehp``, by ``cc_pairing``, the pick-ban route and the
laning precompute; ``cc_output`` copies it at generation time through
``tools/ds_cc_output_build.py``; the ``cooldown_watch`` reader named in older
comments was deleted in 538c61e4b) and its sibling
``_PER_SPELL_CC_RANGE`` are hand-authored dicts built by
``registry.setdefault(champ, {})[spell] = tuple`` statements and read with a
plain ``.get``. The wave tests pin each row's VALUE and the seed test pins
5 / 3 tuple lengths and non-negative values, but several authoring mistakes
stay SILENT:

* S144-D-225. A champion key off the DDragon roster, or a spell key the
  champion's Meraki kit does not carry, is never looked up: the row is inert
  and every value pin on it stays green.
* S144-D-226. A NaN, an infinity, a zero or a bool passes "non-negative" or
  "is a float" and poisons (or silently zeroes) the cc_pressure sum. A tuple
  whose length disagrees with the per-rank list Meraki states for the served
  form reads the wrong rank slot. (Range rows get the same value check
  inside the S144-D-228 checker.)
* S144-D-227. ``setdefault(...)[spell] = ...`` keeps only the LAST
  assignment to a slot: the exact clobber the ENGINE 1.36.0 builder lift was
  written to stop (Lulu R / Sejuani Q / Thresh E were held out of wave 5
  because of it), now with
  no error at all. The guard walks the builder ASTs, so it also proves the
  enumeration is complete (every statement parsed, the parsed rows equal the
  built registries).
* S144-D-228. A ``_PER_SPELL_CC_RANGE`` row is the (min, max) interval of a
  distance-scaled CC whose flat ``_PER_SPELL_CC_DURATIONS`` row pins one
  representative value per rank. A flat value outside its interval, or a
  range row with no flat row, means one of the two is wrong.
* S144-D-229. Every assignment is preceded by a comment quoting the tooltip
  values it encodes (for example "Ahri E - Charm: charm 1.0/1.25/1.5/1.75/
  2.0"). A value the comment does not name is an edit that drifted from its
  stated source. This is a presence check only: a value changed to another
  number the same comment block already names (including numbers in a wave
  header above the first row of a wave) still passes.

MEASURED 2026-11-09 (patch 16.22.1 from ``data/daemon_slayer/current.txt``,
ENGINE 1.291.0): 108 flat rows over 89 champions plus 4 range rows, all
clean, so these guards are preventive. Every checker is a pure function and
each has a planted-defect test, so an empty enumeration cannot pass it.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from agents.daemon_slayer import _per_spell_cc
from agents.daemon_slayer import _registries as registries
from agents.daemon_slayer._per_spell_cc import (
    _PER_SPELL_CC_DURATIONS,
    _PER_SPELL_CC_RANGE,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.data_loader import DataSnapshot

SRC_PATH = Path(_per_spell_cc.__file__).resolve()
DURATIONS_BUILDER = "_build_per_spell_cc_durations"
RANGE_BUILDER = "_build_per_spell_cc_range"
SPELL_KEYS = frozenset({"Q", "W", "E", "R"})

Registry = dict[str, dict[str, tuple[float, ...]]]
Slot = tuple[str, str]


@dataclass(frozen=True)
class Assignment:
    builder: str
    champion: str
    spell: str
    lineno: int
    values: tuple[Any, ...]
    comment: str


# ---------------------------------------------------------------------------
# Source walk
# ---------------------------------------------------------------------------


def _setdefault_slot(target: ast.expr) -> Optional[Slot]:
    """``registry.setdefault("Champ", {})["K"]`` -> ("Champ", "K"), else None."""
    if not isinstance(target, ast.Subscript):
        return None
    call = target.value
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "setdefault"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "registry"
        and len(call.args) == 2
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
        and isinstance(call.args[1], ast.Dict)
        and not call.args[1].keys
    ):
        return None
    key = target.slice
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
        return None
    return call.args[0].value, key.value


def _leading_comment(lines: list[str], lineno: int) -> str:
    """The contiguous ``#`` comment block directly above 1-based ``lineno``."""
    out: list[str] = []
    i = lineno - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        out.insert(0, lines[i].strip().lstrip("#").strip())
        i -= 1
    return " ".join(out)


def walk_builders(src: str, builders: tuple[str, ...]) -> tuple[list[Assignment], list[str]]:
    """Return every slot assignment in the named builders, and every builder
    statement the walk could not read as one (so a new statement shape fails
    the completeness check instead of being skipped)."""
    tree = ast.parse(src)
    lines = src.splitlines()
    found: list[Assignment] = []
    unparsed: list[str] = []
    seen_builders: set[str] = set()
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name in builders):
            continue
        seen_builders.add(node.name)
        body = list(node.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # docstring
        for stmt in body:
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == "registry"
                and isinstance(stmt.value, ast.Dict)
                and not stmt.value.keys
            ):
                continue
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Name) and stmt.value.id == "registry":
                continue
            slot = (
                _setdefault_slot(stmt.targets[0]) if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None
            )
            if slot is None:
                unparsed.append(f"{node.name}:{stmt.lineno}")
                continue
            try:
                values = ast.literal_eval(stmt.value)
            except ValueError:
                unparsed.append(f"{node.name}:{stmt.lineno}")
                continue
            if not isinstance(values, tuple):
                unparsed.append(f"{node.name}:{stmt.lineno}")
                continue
            found.append(
                Assignment(node.name, slot[0], slot[1], stmt.lineno, values, _leading_comment(lines, stmt.lineno))
            )
    unparsed.extend(f"missing builder {b}" for b in builders if b not in seen_builders)
    return found, unparsed


def rebuild(assignments: list[Assignment], builder: str) -> Registry:
    out: Registry = {}
    for a in assignments:
        if a.builder == builder:
            out.setdefault(a.champion, {})[a.spell] = a.values
    return out


# ---------------------------------------------------------------------------
# Pure checkers
# ---------------------------------------------------------------------------


def off_roster(reg: Registry, roster: frozenset[str]) -> list[str]:
    return sorted(c for c in reg if c not in roster)


def missing_spells(reg: Registry, ab: AbilitiesSnapshot) -> list[Slot]:
    out: list[Slot] = []
    for champ, spells in reg.items():
        for spell in spells:
            if spell not in SPELL_KEYS or not ab.has_champion(champ) or not ab.get_abilities(champ).get(spell):
                out.append((champ, spell))
    return sorted(out)


def _sane(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def bad_values(reg: Registry) -> list[Slot]:
    return sorted(
        (champ, spell)
        for champ, spells in reg.items()
        for spell, tup in spells.items()
        if not isinstance(tup, tuple) or not tup or not all(_sane(v) for v in tup)
    )


def served_rank_count(ab: AbilitiesSnapshot, champ: str, spell: str) -> Optional[int]:
    """Length of the per-rank cooldown list Meraki states for the served form
    of ``champ``'s ``spell``; None when it states no per-rank list (a missing
    cooldown, or one flat value such as Heimerdinger E's 11s)."""
    forms = ab.get_abilities(champ).get(spell) or ()
    served = registries.get_form_index_for(champ)[0].get(spell, 0)
    if not 0 <= served < len(forms):
        return None
    cd = forms[served].cooldown
    if not cd or len(cd) < 2:
        return None
    return len(cd)


def rank_mismatches(reg: Registry, ab: AbilitiesSnapshot) -> list[tuple[str, str, int, int]]:
    out: list[tuple[str, str, int, int]] = []
    for champ, spells in reg.items():
        for spell, tup in spells.items():
            n = served_rank_count(ab, champ, spell)
            if n is not None and len(tup) not in (1, n):
                out.append((champ, spell, len(tup), n))
    return sorted(out)


def duplicate_slots(assignments: list[Assignment]) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str, str]] = set()
    dups: list[tuple[str, str, str]] = []
    for a in assignments:
        key = (a.builder, a.champion, a.spell)
        if key in seen:
            dups.append(key)
        seen.add(key)
    return sorted(dups)


def range_defects(flat: Registry, ranges: Registry) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for champ, spells in ranges.items():
        for spell, rng in spells.items():
            if not (isinstance(rng, tuple) and len(rng) == 2 and all(_sane(v) for v in rng) and rng[0] <= rng[1]):
                out.append((champ, spell, "malformed range"))
                continue
            lo, hi = rng
            row = flat.get(champ, {}).get(spell)
            if not row:
                out.append((champ, spell, "no flat row"))
            elif any(not lo <= v <= hi for v in row):
                out.append((champ, spell, "flat value outside range"))
    return sorted(out)


_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def comment_drift(assignments: list[Assignment]) -> list[tuple[str, str, str, float]]:
    out: list[tuple[str, str, str, float]] = []
    for a in assignments:
        named = {float(x) for x in _NUMBER.findall(a.comment)}
        for v in sorted(set(a.values)):
            if float(v) not in named:
                out.append((a.builder, a.champion, a.spell, float(v)))
    return sorted(out)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def walked() -> tuple[list[Assignment], list[str]]:
    return walk_builders(SRC_PATH.read_text(encoding="utf-8"), (DURATIONS_BUILDER, RANGE_BUILDER))


@pytest.fixture(scope="module")
def assignments(walked: tuple[list[Assignment], list[str]]) -> list[Assignment]:
    return walked[0]


@pytest.fixture(scope="module")
def roster() -> frozenset[str]:
    return frozenset(DataSnapshot.load().champions)


@pytest.fixture(scope="module")
def ab() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load()


# ---------------------------------------------------------------------------
# Completeness anchor - the walk sees exactly what the module builds.
# ---------------------------------------------------------------------------


def test_builder_walk_is_complete(walked: tuple[list[Assignment], list[str]]) -> None:
    found, unparsed = walked
    assert unparsed == []
    assert found, "builder walk found no assignments"


def test_walked_rows_equal_the_built_registries(assignments: list[Assignment]) -> None:
    assert rebuild(assignments, DURATIONS_BUILDER) == _PER_SPELL_CC_DURATIONS
    assert rebuild(assignments, RANGE_BUILDER) == _PER_SPELL_CC_RANGE
    assert _PER_SPELL_CC_DURATIONS and _PER_SPELL_CC_RANGE


def test_planted_unreadable_builder_statement_is_reported() -> None:
    src = (
        "def _build_per_spell_cc_durations():\n"
        "    registry: dict = {}\n"
        "    for c in ('Ahri',):\n"
        "        registry.setdefault(c, {})['E'] = (1.0,)\n"
        "    registry.setdefault('Annie', {})['R'] = make()\n"
        "    return registry\n"
    )
    found, unparsed = walk_builders(src, (DURATIONS_BUILDER, RANGE_BUILDER))
    assert found == []
    assert unparsed == [f"{DURATIONS_BUILDER}:3", f"{DURATIONS_BUILDER}:5", f"missing builder {RANGE_BUILDER}"]


# ---------------------------------------------------------------------------
# S144-D-225 - live champions, live spells.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reg_name", ["durations", "range"])
def test_every_champion_key_is_a_roster_id(reg_name: str, roster: frozenset[str]) -> None:
    reg = _PER_SPELL_CC_DURATIONS if reg_name == "durations" else _PER_SPELL_CC_RANGE
    assert off_roster(reg, roster) == []


@pytest.mark.parametrize("reg_name", ["durations", "range"])
def test_every_spell_key_is_a_spell_the_champion_has(reg_name: str, ab: AbilitiesSnapshot) -> None:
    reg = _PER_SPELL_CC_DURATIONS if reg_name == "durations" else _PER_SPELL_CC_RANGE
    assert missing_spells(reg, ab) == []


def test_planted_off_roster_and_missing_spell_are_caught(roster: frozenset[str], ab: AbilitiesSnapshot) -> None:
    planted: Registry = {"Wukong": {"R": (1.0,)}, "Ahri": {"P": (1.0,), "E": (1.0,)}, "NotAChampion": {"Q": (1.0,)}}
    assert off_roster(planted, roster) == ["NotAChampion", "Wukong"]
    assert missing_spells(planted, ab) == [("Ahri", "P"), ("NotAChampion", "Q"), ("Wukong", "R")]


# ---------------------------------------------------------------------------
# S144-D-226 - sane values, rank count agrees with Meraki.
# ---------------------------------------------------------------------------


def test_every_value_is_a_finite_positive_real() -> None:
    assert bad_values(_PER_SPELL_CC_DURATIONS) == []


def test_tuple_length_agrees_with_the_served_forms_rank_list(ab: AbilitiesSnapshot) -> None:
    assert rank_mismatches(_PER_SPELL_CC_DURATIONS, ab) == []


def test_rank_check_is_not_vacuous(ab: AbilitiesSnapshot) -> None:
    checked = sum(
        1
        for champ, spells in _PER_SPELL_CC_DURATIONS.items()
        for spell in spells
        if served_rank_count(ab, champ, spell) is not None
    )
    total = sum(len(s) for s in _PER_SPELL_CC_DURATIONS.values())
    # MEASURED 2026-11-09: 105 of 108 rows have a per-rank Meraki list (the
    # three without: AurelionSol R served form 1, Heimerdinger E, Shyvana R).
    assert checked >= total - 3


@pytest.mark.parametrize(
    "bad",
    [(float("nan"),), (float("inf"),), (0.0,), (-1.0,), (True,), ("1.0",), (), [1.0]],
)
def test_planted_bad_values_are_caught(bad: Any) -> None:
    assert bad_values({"Ahri": {"E": bad}}) == [("Ahri", "E")]


def test_planted_rank_mismatch_is_caught(ab: AbilitiesSnapshot) -> None:
    assert served_rank_count(ab, "Ahri", "E") == 5
    assert rank_mismatches({"Ahri": {"E": (1.0, 1.25, 1.5)}}, ab) == [("Ahri", "E", 3, 5)]
    assert rank_mismatches({"Ahri": {"E": (1.0,)}}, ab) == []


# ---------------------------------------------------------------------------
# S144-D-227 - no slot is assigned twice (setdefault keeps the last).
# ---------------------------------------------------------------------------


def test_no_slot_is_assigned_twice(assignments: list[Assignment]) -> None:
    assert duplicate_slots(assignments) == []


def test_planted_clobber_is_caught() -> None:
    src = (
        "def _build_per_spell_cc_durations():\n"
        "    registry: dict = {}\n"
        "    # Lulu R 1.0s\n"
        "    registry.setdefault('Lulu', {})['R'] = (1.0,)\n"
        "    # Lulu R 1.5s\n"
        "    registry.setdefault('Lulu', {})['R'] = (1.5,)\n"
        "    return registry\n"
        "def _build_per_spell_cc_range():\n"
        "    registry: dict = {}\n"
        "    # Lulu R 1.0 : 1.5\n"
        "    registry.setdefault('Lulu', {})['R'] = (1.0, 1.5)\n"
        "    return registry\n"
    )
    found, unparsed = walk_builders(src, (DURATIONS_BUILDER, RANGE_BUILDER))
    assert unparsed == []
    assert duplicate_slots(found) == [(DURATIONS_BUILDER, "Lulu", "R")]
    assert rebuild(found, DURATIONS_BUILDER) == {"Lulu": {"R": (1.5,)}}


# ---------------------------------------------------------------------------
# S144-D-228 - each flat row sits inside its distance range.
# ---------------------------------------------------------------------------


def test_every_range_row_contains_its_flat_row() -> None:
    assert range_defects(_PER_SPELL_CC_DURATIONS, _PER_SPELL_CC_RANGE) == []


def test_planted_range_defects_are_caught() -> None:
    flat: Registry = {"Ashe": {"R": (1.5, 1.5, 4.0)}, "Xerath": {"E": (1.0,)}}
    ranges: Registry = {
        "Ashe": {"R": (1.0, 3.5)},
        "Hecarim": {"R": (0.75, 1.5)},
        "Xerath": {"E": (2.25, 0.75)},
        "Maokai": {"R": (float("nan"), 2.25)},
    }
    assert range_defects(flat, ranges) == [
        ("Ashe", "R", "flat value outside range"),
        ("Hecarim", "R", "no flat row"),
        ("Maokai", "R", "malformed range"),
        ("Xerath", "E", "malformed range"),
    ]


# ---------------------------------------------------------------------------
# S144-D-229 - every shipped value is named by the comment above it.
# ---------------------------------------------------------------------------


def test_every_value_is_named_by_its_comment(assignments: list[Assignment]) -> None:
    assert comment_drift(assignments) == []


def test_every_assignment_has_a_comment(assignments: list[Assignment]) -> None:
    assert [(a.builder, a.champion, a.spell) for a in assignments if not a.comment] == []


def test_planted_comment_drift_is_caught() -> None:
    src = (
        "def _build_per_spell_cc_durations():\n"
        "    registry: dict = {}\n"
        "    # Ahri E - Charm: charm 1.0/1.25/1.5/1.75/2.0\n"
        "    registry.setdefault('Ahri', {})['E'] = (1.0, 1.25, 1.5, 1.75, 2.5)\n"
        "    # Annie R - Summon: Tibbers: stun on summon 1.5s all ranks\n"
        "    registry.setdefault('Annie', {})['R'] = (1.5, 1.5, 1.5)\n"
        "    return registry\n"
        "def _build_per_spell_cc_range():\n"
        "    registry: dict = {}\n"
        "    return registry\n"
    )
    found, unparsed = walk_builders(src, (DURATIONS_BUILDER, RANGE_BUILDER))
    assert unparsed == []
    assert comment_drift(found) == [(DURATIONS_BUILDER, "Ahri", "E", 2.5)]
