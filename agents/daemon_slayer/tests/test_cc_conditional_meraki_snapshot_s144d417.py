"""S144-D-417..419 - the DS conditional-CC registry (``cc_conditional_registry.json``,
both its ``primary`` and ``forms`` lists) checked against the shipped Meraki ability
snapshot ``data/daemon_slayer/<current.txt>/champion_abilities.json``.

READERS. The block reader (``cc_blocks``) and the prose reader
(``prose_seconds``) are imported unchanged from the S144-D-415 guard, whose
docstring states what each one reads. A ``primary`` row
(``form_index`` None) is read over every form of its spell slot. A ``forms``
row is read over only the snapshot forms whose ``form_index`` equals its own.

S144-D-417 PIN. ``_VALUES`` holds every registry row's ``durations_s`` and
``_MEASURED`` both readers' output for every row; each is compared exactly,
AGREE rows included. The classification rule is
the S144-D-415 one (``block_agrees`` on the blocks, else the prose figures).
The worklist is a separate pin, checked twice with the registry's
``durations_s``: once from the live readings and once from ``_MEASURED``.
A DIVERGE or UNQUOTED
row is a re-derivation worklist entry, not a verdict that the registry is
wrong; changing a registry value is a Tier-2 DS batch, not a lane edit.

S144-D-418. Every non-null ``durations_floor_s`` (the set is pinned in
``_FLOORS``) is among its row's live prose figures.

S144-D-419. Each quote listed in ``_NOTE_QUOTES`` is in the registry row's
``notes`` verbatim, and its parts (split on " ... ") occur in order in one snapshot
string of the row: the listed ``effects_descriptions`` index, else any
``effects_descriptions`` entry or the ``notes`` field. Whitespace runs in the
snapshot string and the quote are collapsed to one space before matching.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest

from agents.daemon_slayer.tests.test_per_spell_cc_meraki_divergence_s144d415 import (
    _abilities,
    block_agrees,
    cc_blocks,
    prose_seconds,
)

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "cc_conditional_registry.json"

Row = tuple[str, str, Optional[int]]
Blocks = tuple[tuple[str, tuple[float, ...]], ...]
Measured = tuple[Blocks, tuple[float, ...]]


def _records() -> list[Mapping[str, Any]]:
    data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    return list(data["primary"]) + list(data["forms"])


def _row(rec: Mapping[str, Any]) -> Row:
    return (rec["champion"], rec["spell"], rec["form_index"])


def _forms_for(data: Mapping[str, Any], row: Row) -> list[Mapping[str, Any]]:
    champ, spell, form_index = row
    forms = list((data.get(champ) or {}).get(spell) or [])
    if form_index is None:
        return forms
    return [f for f in forms if f.get("form_index") == form_index]


def measure(records: list[Mapping[str, Any]], data: Mapping[str, Any]) -> dict[Row, Measured]:
    """Every registry row -> (block reader output, prose reader output)."""
    out: dict[Row, Measured] = {}
    for rec in records:
        forms = _forms_for(data, _row(rec))
        out[_row(rec)] = (cc_blocks(forms), prose_seconds(forms))
    return out


def classify(
    records: list[Mapping[str, Any]], measured: Mapping[Row, Measured]
) -> tuple[set[Row], set[Row], set[Row], set[Row]]:
    """Return (block_diverge, prose_diverge, unquoted, agree) row sets."""
    values = {_row(rec): tuple(rec["durations_s"]) for rec in records}
    block_div: set[Row] = set()
    prose_div: set[Row] = set()
    unquoted: set[Row] = set()
    agree: set[Row] = set()
    for row, (blocks, nums) in measured.items():
        if blocks:
            (agree if block_agrees(values[row], blocks) else block_div).add(row)
        elif not nums:
            unquoted.add(row)
        elif set(values[row]) <= set(nums):
            agree.add(row)
        else:
            prose_div.add(row)
    return block_div, prose_div, unquoted, agree


# MEASURED 2026-11-10 at 16.22.1: the output of ``measure`` for every registry
# row, as (block reader output, prose reader output).
_MEASURED: dict[Row, Measured] = {
    ("Aatrox", "Q", None): ((), (0.25, 0.5)),
    ("Aatrox", "W", None): ((), ()),
    ("Alistar", "E", None): ((), (1.0, 6.0)),
    ("Aphelios", "Q", 3): ((), (1.0,)),
    ("Ashe", "R", None): ((), (1.0, 3.5)),
    ("Bard", "Q", None): ((("Disable Duration", (1.0, 1.2, 1.4, 1.6, 1.8)),), ()),
    ("Brand", "Q", None): ((), (1.5,)),
    ("Brand", "R", None): ((), ()),
    ("Briar", "E", None): ((), (0.5, 1.5)),
    ("Briar", "Q", None): ((), (0.85, 5.0)),
    ("Briar", "R", None): ((), (1.5,)),
    ("Evelynn", "W", None): ((("Disable Duration", (1.25, 1.5, 1.75, 2.0, 2.25)),), (2.0, 2.5)),
    ("Fiora", "W", None): ((), ()),
    ("Fizz", "R", None): ((), (1.0, 2.0)),
    ("Garen", "Q", None): ((), (1.5, 4.5)),
    ("Gnar", "W", 1): ((), (1.25,)),
    ("Hecarim", "R", None): ((), (0.75, 1.5)),
    ("Hwei", "E", None): (
        (
            ("Disable Duration", (1.0, 1.125, 1.25, 1.375, 1.5)),
            ("Root Duration", (1.2, 1.4, 1.6, 1.8, 2.0)),
        ),
        (0.3, 2.5),
    ),
    ("Hwei", "E", 2): ((("Root Duration", (1.2, 1.4, 1.6, 1.8, 2.0)),), (0.3, 2.5)),
    ("JarvanIV", "E", None): ((), ()),
    ("Jayce", "E", 0): ((), ()),
    ("KSante", "Q", None): ((), (0.65, 0.8)),
    ("KSante", "W", None): ((), (0.5, 0.9, 1.75)),
    ("Karma", "W", None): (
        (
            ("Root Duration", (1.6, 1.7, 1.8, 1.9, 2.0)),
            ("Total Root Duration", (1.6, 1.7, 1.8, 1.9, 2.0)),
            ("Total Root Duration", (0.5, 0.75, 1.0, 1.25)),
        ),
        (),
    ),
    ("Karma", "W", 1): (
        (
            ("Total Root Duration", (1.6, 1.7, 1.8, 1.9, 2.0)),
            ("Total Root Duration", (0.5, 0.75, 1.0, 1.25)),
        ),
        (),
    ),
    ("Kennen", "E", None): ((), ()),
    ("Leblanc", "E", None): ((), (1.5,)),
    ("Maokai", "Q", None): ((), (0.5,)),
    ("Maokai", "R", None): ((), (0.75, 2.25)),
    ("Mordekaiser", "R", None): ((), ()),
    ("Morgana", "R", None): ((("Stun Duration", (1.5, 1.75, 2.0)),), ()),
    ("Neeko", "E", None): (
        (
            ("Root Duration", (0.7, 0.9, 1.1, 1.3, 1.5)),
            ("Empowered Root Duration", (1.8, 2.1, 2.4, 2.7, 3.0)),
        ),
        (),
    ),
    ("Nunu", "R", None): ((), ()),
    ("Ornn", "E", None): ((), (1.25,)),
    ("Ornn", "Q", None): ((), (4.0,)),
    ("Pantheon", "Q", None): ((), ()),
    ("Pyke", "E", None): ((), (1.0, 1.25)),
    ("Rell", "W", 0): ((), (0.4, 0.8)),
    ("Rell", "W", 1): ((), (0.4, 0.6)),
    ("Renata", "Q", None): ((), (0.5, 1.0)),
    ("Renekton", "W", None): ((), (0.75, 1.5, 7.0)),
    ("Riven", "Q", None): ((), (0.5,)),
    ("Sejuani", "E", None): ((), (1.0,)),
    ("Seraphine", "E", None): ((("Disable Duration", (1.1, 1.2, 1.3, 1.4, 1.5)),), ()),
    ("Sett", "E", None): ((), (1.0,)),
    ("Shaco", "R", None): ((), (0.3, 0.5, 0.6, 1.0, 2.2)),
    ("Singed", "E", None): ((("Root Duration", (1.0, 1.25, 1.5, 1.75, 2.0)),), ()),
    ("Sion", "R", None): ((), (0.25, 0.5, 1.75)),
    ("Skarner", "Q", None): ((), ()),
    ("Swain", "E", None): ((), (1.5,)),
    ("Sylas", "E", 1): ((), (0.5,)),
    ("Syndra", "E", None): ((), (1.25,)),
    ("TahmKench", "Q", None): ((), (1.5,)),
    ("TahmKench", "R", None): ((), ()),
    ("TahmKench", "W", None): ((), (1.0,)),
    ("Taliyah", "E", None): ((), (0.75, 2.0)),
    ("Taliyah", "W", None): ((), (0.792, 1.0)),
    ("TwistedFate", "W", None): ((("Stun Duration", (1.0, 1.25, 1.5, 1.75, 2.0)),), ()),
    ("Udyr", "E", None): ((), (0.75,)),
    ("Vayne", "E", None): ((), (1.5,)),
    ("Vex", "E", None): ((), ()),
    ("Viktor", "W", None): ((), (1.5,)),
    ("Volibear", "Q", None): ((), (1.0,)),
    ("Warwick", "E", None): ((), (1.0,)),
    ("Warwick", "R", None): ((), (0.25, 1.5)),
    ("Xayah", "E", None): ((), (1.25,)),
    ("XinZhao", "Q", None): ((), (0.75,)),
    ("XinZhao", "R", None): ((), (0.75,)),
    ("Yasuo", "Q", None): ((), (0.75, 0.9)),
    ("Yone", "Q", None): ((), (0.75,)),
    ("Yuumi", "Q", None): ((), ()),
    ("Zac", "Q", None): ((), (0.25, 0.5)),
    ("Zilean", "Q", None): ((("Stun Duration", (1.1, 1.2, 1.3, 1.4, 1.5)),), ()),
}

# Every registry row's ``durations_s`` as shipped.
_VALUES: dict[Row, tuple[float, ...]] = {
    ("Aatrox", "Q", None): (0.5,),
    ("Aatrox", "W", None): (1.75,),
    ("Alistar", "E", None): (1.0,),
    ("Aphelios", "Q", 3): (1.0,),
    ("Ashe", "R", None): (3.5,),
    ("Bard", "Q", None): (1.5, 1.75, 2.0, 2.25, 2.5),
    ("Brand", "Q", None): (1.25,),
    ("Brand", "R", None): (2.0,),
    ("Briar", "E", None): (1.0,),
    ("Briar", "Q", None): (1.0,),
    ("Briar", "R", None): (1.5,),
    ("Evelynn", "W", None): (1.25, 1.5, 1.75, 2.0, 2.25),
    ("Fiora", "W", None): (1.5,),
    ("Fizz", "R", None): (1.0,),
    ("Garen", "Q", None): (1.5,),
    ("Gnar", "W", 1): (1.25,),
    ("Hecarim", "R", None): (1.5, 1.5, 1.5),
    ("Hwei", "E", None): (1.0, 1.125, 1.25, 1.375, 1.5),
    ("Hwei", "E", 2): (1.2, 1.4, 1.6, 1.8, 2.0),
    ("JarvanIV", "E", None): (1.0,),
    ("Jayce", "E", 0): (0.25,),
    ("KSante", "Q", None): (0.75,),
    ("KSante", "W", None): (1.0,),
    ("Karma", "W", None): (1.5, 1.625, 1.75, 1.875, 2.0),
    ("Karma", "W", 1): (2.35, 2.45, 2.55, 2.65, 2.75),
    ("Kennen", "E", None): (1.25,),
    ("Leblanc", "E", None): (1.5,),
    ("Maokai", "Q", None): (1.0,),
    ("Maokai", "R", None): (2.25,),
    ("Mordekaiser", "R", None): (7.0,),
    ("Morgana", "R", None): (1.5, 1.75, 2.0),
    ("Neeko", "E", None): (1.8, 2.1, 2.4, 2.7, 3.0),
    ("Nunu", "R", None): (0.5,),
    ("Ornn", "E", None): (1.25,),
    ("Ornn", "Q", None): (1.5,),
    ("Pantheon", "Q", None): (1.0,),
    ("Pyke", "E", None): (1.25,),
    ("Rell", "W", 0): (0.8,),
    ("Rell", "W", 1): (0.6,),
    ("Renata", "Q", None): (0.5,),
    ("Renekton", "W", None): (1.5,),
    ("Riven", "Q", None): (0.75,),
    ("Sejuani", "E", None): (1.0,),
    ("Seraphine", "E", None): (1.1, 1.2, 1.3, 1.4, 1.5),
    ("Sett", "E", None): (1.0,),
    ("Shaco", "R", None): (1.0,),
    ("Singed", "E", None): (1.0, 1.25, 1.5, 1.75, 2.0),
    ("Sion", "R", None): (1.0,),
    ("Skarner", "Q", None): (0.75,),
    ("Swain", "E", None): (1.5, 1.625, 1.75, 1.875, 2.0),
    ("Sylas", "E", 1): (0.5,),
    ("Syndra", "E", None): (1.25,),
    ("TahmKench", "Q", None): (1.5,),
    ("TahmKench", "R", None): (1.0,),
    ("TahmKench", "W", None): (1.0,),
    ("Taliyah", "E", None): (0.75,),
    ("Taliyah", "W", None): (0.75,),
    ("TwistedFate", "W", None): (1.5,),
    ("Udyr", "E", None): (0.75,),
    ("Vayne", "E", None): (1.5, 1.5, 1.5, 1.5, 1.5),
    ("Vex", "E", None): (1.0, 1.125, 1.25, 1.375, 1.5),
    ("Viktor", "W", None): (1.5,),
    ("Volibear", "Q", None): (0.75,),
    ("Warwick", "E", None): (1.0,),
    ("Warwick", "R", None): (1.5, 1.75, 2.0),
    ("Xayah", "E", None): (1.25,),
    ("XinZhao", "Q", None): (0.75, 0.75, 0.75, 0.75, 0.75),
    ("XinZhao", "R", None): (0.75, 0.75, 0.75),
    ("Yasuo", "Q", None): (1.0,),
    ("Yone", "Q", None): (0.75,),
    ("Yuumi", "Q", None): (1.75,),
    ("Zac", "Q", None): (0.5,),
    ("Zilean", "Q", None): (2.0,),
}

_BLOCK_DIVERGE: frozenset[Row] = frozenset(
    {
        ("Bard", "Q", None),
        ("Karma", "W", None),
        ("Karma", "W", 1),
        ("TwistedFate", "W", None),
        ("Zilean", "Q", None),
    }
)

_PROSE_DIVERGE: frozenset[Row] = frozenset(
    {
        ("Brand", "Q", None),
        ("Briar", "E", None),
        ("Briar", "Q", None),
        ("KSante", "Q", None),
        ("KSante", "W", None),
        ("Maokai", "Q", None),
        ("Ornn", "Q", None),
        ("Riven", "Q", None),
        ("Sion", "R", None),
        ("Swain", "E", None),
        ("Taliyah", "W", None),
        ("Volibear", "Q", None),
        ("Warwick", "R", None),
        ("Yasuo", "Q", None),
    }
)

_UNQUOTED: frozenset[Row] = frozenset(
    {
        ("Aatrox", "W", None),
        ("Brand", "R", None),
        ("Fiora", "W", None),
        ("JarvanIV", "E", None),
        ("Jayce", "E", 0),
        ("Kennen", "E", None),
        ("Mordekaiser", "R", None),
        ("Nunu", "R", None),
        ("Pantheon", "Q", None),
        ("Skarner", "Q", None),
        ("TahmKench", "R", None),
        ("Vex", "E", None),
        ("Yuumi", "Q", None),
    }
)

_FLOORS: dict[Row, float] = {
    ("Ashe", "R", None): 1.0,
    ("Hecarim", "R", None): 0.75,
    ("KSante", "W", None): 0.5,
    ("Maokai", "R", None): 0.75,
    ("Sion", "R", None): 0.25,
}

# (row, quote as written in the row's notes, the effects_descriptions index
# that holds it, or None to search every effects_descriptions entry and the
# notes field of the row's snapshot forms). The Karma W form-1 note quotes
# "Mantra Bonus: Focused Resolve's root duration is increased ... Renewal
# scales with Mantra's rank" as effects_descriptions[0]; the snapshot holds
# the two parts in entries 0 and 1, so they are listed as two quotes.
_NOTE_QUOTES: tuple[tuple[Row, str, Optional[int]], ...] = (
    (("Ashe", "R", None), "stunning them for 1 : 3.5 (based on distance traveled) seconds", None),
    (("Briar", "R", None), "fears all non-marked targets for 1.5 seconds", None),
    (("Fizz", "R", None), "knocked up for 1 second instead of knocked back", None),
    (("Hecarim", "R", None), "fears nearby enemies for 0.75 : 1.5 (based on distance traveled) seconds", 1),
    (("Renekton", "W", None), "Reign of Anger Bonus: ... increasing the stun duration to 1.5 seconds", 2),
    (("Shaco", "R", None), "fearing nearby enemies for 1 second", None),
    (("TahmKench", "W", None), "knock up and stun them for 1 second", None),
    (("Vayne", "E", None), "become stunned for 1.5 seconds", None),
    (
        ("Vayne", "E", None),
        "they can be immobilized for up to 2 seconds depending on displacement duration based on distance traveled",
        None,
    ),
    (("Warwick", "E", None), "fearing nearby enemies for 1 second", None),
    (("XinZhao", "Q", None), "The third attack knocks up the target for 0.75 seconds", 1),
    (("XinZhao", "Q", None), "Spell shield will only block the knock up", None),
    (
        ("XinZhao", "R", None),
        "Active: Xin Zhao sweeps his spear around him ... knocking back all non-Challenged targets hit up-to 700"
        " units over 0.75 seconds, as well as stunning them for the same duration",
        1,
    ),
    (("XinZhao", "R", None), "Displacement immunity will also resist the application of the stun", None),
    (("Aphelios", "Q", 3), "rooting them for 1 second", None),
    (("Karma", "W", 1), "Mantra Bonus: Focused Resolve's root duration is increased", 0),
    (("Karma", "W", 1), "Renewal scales with Mantra's rank", 1),
)


@pytest.fixture(scope="module")
def live_data() -> Mapping[str, Any]:
    return _abilities()


def test_every_row_carries_exactly_the_pinned_values() -> None:
    values = {_row(r): tuple(r["durations_s"]) for r in _records()}
    assert len(values) == len(_VALUES) == 73
    assert values == _VALUES
    assert set(_VALUES) == set(_MEASURED)


def test_every_row_extracts_exactly_the_pinned_inputs(live_data: Mapping[str, Any]) -> None:
    records = _records()
    measured = measure(records, live_data)
    assert len(records) == len(measured) == len(_MEASURED) == 73
    assert set(measured) == set(_MEASURED)
    for row, pinned in _MEASURED.items():
        assert measured[row] == pinned, row


def test_classification_is_exactly_the_pinned_worklist(live_data: Mapping[str, Any]) -> None:
    records = _records()
    block_div, prose_div, unquoted, agree = classify(records, measure(records, live_data))
    assert block_div == _BLOCK_DIVERGE
    assert prose_div == _PROSE_DIVERGE
    assert unquoted == _UNQUOTED
    assert agree == set(_MEASURED) - _BLOCK_DIVERGE - _PROSE_DIVERGE - _UNQUOTED
    assert len(agree) == 41


def test_the_pinned_worklist_follows_from_the_pinned_inputs() -> None:
    block_div, prose_div, unquoted, agree = classify(_records(), _MEASURED)
    assert (block_div, prose_div, unquoted) == (set(_BLOCK_DIVERGE), set(_PROSE_DIVERGE), set(_UNQUOTED))
    classes = [block_div, prose_div, unquoted, agree]
    assert sum(len(c) for c in classes) == len(_MEASURED)
    assert set().union(*classes) == set(_MEASURED)
    assert all(classes)


def test_a_forms_row_reads_only_its_own_form(live_data: Mapping[str, Any]) -> None:
    # Hwei E: the primary row reads all four forms, the form-2 row only form 2.
    assert len(_forms_for(live_data, ("Hwei", "E", None))) == 4
    assert [f.get("form_index") for f in _forms_for(live_data, ("Hwei", "E", 2))] == [2]
    assert len(_MEASURED[("Hwei", "E", None)][0]) == 2
    assert _MEASURED[("Hwei", "E", 2)][0] == (("Root Duration", (1.2, 1.4, 1.6, 1.8, 2.0)),)


def test_a_planted_move_in_a_forms_row_second_block_is_caught(live_data: Mapping[str, Any]) -> None:
    data = dict(live_data)
    data["Karma"] = copy.deepcopy(live_data["Karma"])
    (form1,) = _forms_for(data, ("Karma", "W", 1))
    # One block, two raw modifiers: the base root and the Mantra bonus.
    (block,) = [b for b in form1["damage_blocks"] if b.get("attribute") == "Total Root Duration"]
    bonus = block["raw_modifiers"][1]
    bonus["values"] = [v + 0.25 for v in bonus["values"]]
    rec = [r for r in _records() if _row(r) == ("Karma", "W", 1)]
    after = measure(rec, data)[("Karma", "W", 1)]
    assert after[0][0] == _MEASURED[("Karma", "W", 1)][0][0]
    assert after != _MEASURED[("Karma", "W", 1)]


def test_every_floor_is_a_snapshot_prose_figure(live_data: Mapping[str, Any]) -> None:
    records = _records()
    floors = {_row(r): r["durations_floor_s"] for r in records if r["durations_floor_s"] is not None}
    assert floors == _FLOORS
    measured = measure(records, live_data)
    for row, floor in _FLOORS.items():
        assert floor in measured[row][1], row


def _snapshot_strings(forms: list[Mapping[str, Any]], index: Optional[int]) -> list[str]:
    if index is not None:
        return [str(f["effects_descriptions"][index]) for f in forms if len(f.get("effects_descriptions") or []) > index]
    out: list[str] = []
    for f in forms:
        out.extend(str(t) for t in f.get("effects_descriptions") or [])
        out.append(str(f.get("notes") or ""))
    return out


def _squash(text: str) -> str:
    return " ".join(text.split())


def _parts_in_order(text: str, parts: list[str]) -> bool:
    text = _squash(text)
    pos = 0
    for part in parts:
        found = text.find(part, pos)
        if found < 0:
            return False
        pos = found + len(part)
    return True


@pytest.mark.parametrize(
    ("row", "quote", "index"),
    _NOTE_QUOTES,
    ids=[f"{r[0]}-{r[1]}-{r[2]}-{n}" for n, (r, _q, _i) in enumerate(_NOTE_QUOTES)],
)
def test_note_quote_is_in_the_snapshot(live_data: Mapping[str, Any], row: Row, quote: str, index: Optional[int]) -> None:
    (rec,) = [r for r in _records() if _row(r) == row]
    assert quote in rec["notes"]
    parts = [_squash(p) for p in quote.split(" ... ")]
    texts = _snapshot_strings(_forms_for(live_data, row), index)
    assert texts
    assert any(_parts_in_order(text, parts) for text in texts)


def test_parts_in_order_rejects_a_reordered_or_missing_part() -> None:
    assert _parts_in_order("a b c d", ["a", "c"])
    assert not _parts_in_order("a b c d", ["c", "a"])
    assert not _parts_in_order("a b c d", ["a", "e"])
    assert _parts_in_order("a  b\nc", ["a b c"])
