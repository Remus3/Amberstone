"""S144-D-415 - for every ``_PER_SPELL_CC_DURATIONS`` row, pin what two readers
extract from the shipped Meraki ability snapshot
(``data/daemon_slayer/<current.txt>/champion_abilities.json``), and pin which
rows' registry values that output does not contain.

A DIVERGE row is a re-derivation worklist entry, not a verdict that the
registry is wrong. Re-deriving a row changes scorer input, so it is a Tier-2
DS batch, never a lane edit (filed as S144-D-413 in the s144 ds lane cycle
reports).

THE TWO READERS, and exactly what they see:

* BLOCK reader (``cc_blocks``). Every ``damage_blocks`` entry of every form of
  the row with ``attribute_kind == "duration"`` whose ``attribute`` contains a
  CC word (a case-insensitive ``_CC_WORD`` match anywhere in it; the prose
  reader uses the same pattern), read from each raw
  modifier that has values and whose units are all seconds or blank. All such
  blocks are kept, in data order, not only the first.
* PROSE reader (``prose_seconds``). The text of every form's
  ``effects_descriptions`` is split into sentences after each period followed
  by whitespace. Every sentence that contains a CC word contributes each number
  followed by optional whitespace and "second" or "seconds" (an optional
  parenthetical may sit in between), including both ends of an ``A : B`` range
  and every value of an ``A / B / C`` list. The result is the sorted distinct
  figures. Figures of non-CC times in the same sentence are read too.

Nothing else is seen: a block whose attribute names no CC word or whose units
are not seconds or blank, a hyphenated "N-second" figure, a figure in a
sentence without a CC word, and any other field.

THE PINS. ``_MEASURED`` holds both readers' output for every registry row and
is compared EXACTLY, AGREE rows included, so any change to what either reader
extracts for any row, or a row added to or removed from the registry, turns it
red. The classification is a separate pin and is also derived from
``_MEASURED`` alone.

CLASSIFICATION, per row. A row with at least one CC block is decided on its
blocks: AGREE when one block equals the registry tuple, or is constant and
equals a constant registry tuple; otherwise BLOCK-DIVERGE. A row with no CC
block is decided on its prose figures: no figure is UNQUOTED; AGREE when every
registry value is among the figures; otherwise PROSE-DIVERGE. A prose AGREE is
weak evidence, because a non-CC figure of the same sentence can satisfy it.
The fix for a red pin is a re-measure, never a loosened guard.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping

import pytest

from agents.daemon_slayer._per_spell_cc import _PER_SPELL_CC_DURATIONS

_REPO = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO / "data" / "daemon_slayer"

_CC_WORD = re.compile(
    r"stun|root|fear|taunt|charm|sleep|suppress|suspend|knock|airborne|polymorph|silence|disable",
    re.IGNORECASE,
)
# An optional parenthetical may sit between the figure and "seconds":
# "stuns them for 0.75 : 2.25 (based on orb travel distance) seconds".
_SECONDS = re.compile(r"((?:\d+(?:\.\d+)?\s*[/:]\s*)*\d+(?:\.\d+)?)\s*(?:\([^)]*\)\s*)?seconds?\b")
_SENTENCE_SPLIT = re.compile(r"(?<=\.)\s+")
# Meraki writes " seconds" on most blocks and "" on some (Gnar R Disable Duration).
_SECOND_UNITS = frozenset({"seconds", "second", ""})

Row = tuple[str, str]
Blocks = tuple[tuple[str, tuple[float, ...]], ...]


def _abilities() -> Mapping[str, Any]:
    patch = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    path = _DS_DATA / patch / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def cc_blocks(forms: list[Mapping[str, Any]]) -> Blocks:
    """(attribute, per-rank seconds) for every CC-named duration block, in data order."""
    out: list[tuple[str, tuple[float, ...]]] = []
    for form in forms:
        for block in form.get("damage_blocks") or []:
            attr = str(block.get("attribute") or "")
            if block.get("attribute_kind") != "duration" or not _CC_WORD.search(attr):
                continue
            for mod in block.get("raw_modifiers") or []:
                units = {str(u).strip() for u in mod.get("units") or []}
                if mod.get("values") and units <= _SECOND_UNITS:
                    out.append((attr, tuple(float(v) for v in mod["values"])))
    return tuple(out)


def prose_seconds(forms: list[Mapping[str, Any]]) -> tuple[float, ...]:
    """Sorted distinct seconds figures written in the row's CC sentences."""
    nums: set[float] = set()
    for form in forms:
        for desc in form.get("effects_descriptions") or []:
            for sentence in _SENTENCE_SPLIT.split(str(desc)):
                if not _CC_WORD.search(sentence):
                    continue
                for m in _SECONDS.finditer(sentence):
                    for part in re.split(r"\s*[/:]\s*", m.group(1)):
                        nums.add(float(part))
    return tuple(sorted(nums))


def measure(
    registry: Mapping[str, Mapping[str, tuple[float, ...]]],
    data: Mapping[str, Any],
) -> dict[Row, tuple[Blocks, tuple[float, ...]]]:
    """Every registry row -> (block reader output, prose reader output)."""
    out: dict[Row, tuple[Blocks, tuple[float, ...]]] = {}
    for champ, spells in registry.items():
        for key in spells:
            forms = list((data.get(champ) or {}).get(key) or [])
            out[(champ, key)] = (cc_blocks(forms), prose_seconds(forms))
    return out


def block_agrees(values: tuple[float, ...], blocks: Blocks) -> bool:
    for _attr, live in blocks:
        if live == tuple(values):
            return True
        if len(set(live)) == 1 and set(live) == set(values):
            return True
    return False


def classify(
    registry: Mapping[str, Mapping[str, tuple[float, ...]]],
    measured: Mapping[Row, tuple[Blocks, tuple[float, ...]]],
) -> tuple[set[Row], set[Row], set[Row], set[Row]]:
    """Return (block_diverge, prose_diverge, unquoted, agree) row sets."""
    block_div: set[Row] = set()
    prose_div: set[Row] = set()
    unquoted: set[Row] = set()
    agree: set[Row] = set()
    for (champ, key), (blocks, nums) in measured.items():
        values = registry[champ][key]
        if blocks:
            (agree if block_agrees(values, blocks) else block_div).add((champ, key))
        elif not nums:
            unquoted.add((champ, key))
        elif set(values) <= set(nums):
            agree.add((champ, key))
        else:
            prose_div.add((champ, key))
    return block_div, prose_div, unquoted, agree


# MEASURED 2026-11-10 at 16.22.1: the output of ``measure`` for every registry
# row, as (block reader output, prose reader output).
_MEASURED: dict[Row, tuple[Blocks, tuple[float, ...]]] = {
    ("Ahri", "E"): ((("Disable Duration", (1.2, 1.35, 1.5, 1.65, 1.8)),), ()),
    ("Alistar", "Q"): ((), (1.0,)),
    ("Alistar", "W"): ((), (0.5, 0.75)),
    ("Amumu", "Q"): ((), (1.0,)),
    ("Amumu", "R"): ((), (1.5,)),
    ("Anivia", "Q"): ((("Stun Duration", (1.1, 1.2, 1.3, 1.4, 1.5)),), ()),
    ("Annie", "R"): ((), ()),
    ("Ashe", "R"): ((), (1.0, 3.5)),
    ("AurelionSol", "R"): ((), (1.0, 1.25, 2.0)),
    ("Bard", "R"): ((), (2.5,)),
    ("Blitzcrank", "Q"): ((), (0.65,)),
    ("Braum", "R"): ((("Maximum Knockup Duration", (1.0, 1.5, 2.0)),), (0.6,)),
    ("Caitlyn", "W"): ((), (1.5, 3.0)),
    ("Camille", "E"): ((), (0.75, 5.0)),
    ("Cassiopeia", "R"): ((), ()),
    ("Chogath", "Q"): ((), (0.627, 1.0, 1.5)),
    ("Chogath", "W"): ((("Silence Duration", (1.6, 1.7, 1.8, 1.9, 2.0)),), ()),
    ("Diana", "R"): ((), ()),
    ("Draven", "E"): ((), (2.0,)),
    ("Ekko", "W"): ((), (2.0, 2.25)),
    ("Elise", "E"): ((("Stun Duration", (1.6, 1.8, 2.0, 2.2, 2.4)),), ()),
    ("Fiddlesticks", "Q"): (
        (("Fear Duration", (1.2, 1.4, 1.6, 1.8, 2.0)), ("Fear Duration", (1.2, 1.4, 1.6, 1.8, 2.0))),
        (0.35, 2.5),
    ),
    ("Galio", "E"): ((), (0.75,)),
    ("Galio", "R"): ((), (0.5, 0.75)),
    ("Galio", "W"): ((), (0.5, 1.25, 1.5, 2.0)),
    ("Gnar", "R"): ((("Disable Duration", (1.25, 1.5, 1.75)),), ()),
    ("Gragas", "E"): ((), (1.0,)),
    ("Hecarim", "E"): ((), (0.25,)),
    ("Hecarim", "R"): ((), (0.75, 1.5)),
    ("Heimerdinger", "E"): ((), (1.5,)),
    ("Irelia", "E"): ((), (0.25, 0.75)),
    ("Ivern", "Q"): ((("Root Duration", (1.6, 1.7, 1.8, 1.9, 2.0)),), ()),
    ("Janna", "Q"): ((), (0.5, 1.25, 3.0)),
    ("Jax", "E"): ((), (1.0,)),
    ("Jhin", "W"): ((("Root Duration", (1.25, 1.5, 1.75, 2.0, 2.25)),), ()),
    ("Jinx", "E"): ((), (1.5,)),
    ("KSante", "R"): ((), (0.132, 0.264, 0.3, 0.5)),
    ("Kalista", "R"): ((("Airborne Duration", (1.0, 1.5, 2.0)),), ()),
    ("Leona", "E"): ((), (0.5,)),
    ("Leona", "Q"): ((), (1.0, 6.0)),
    ("Leona", "R"): ((), (1.75,)),
    ("Lillia", "R"): ((), (2.0,)),
    ("Lissandra", "R"): ((), (1.5,)),
    ("Lissandra", "W"): ((("Root Duration", (1.25, 1.35, 1.45, 1.55, 1.65)),), ()),
    ("Lulu", "R"): ((), (1.0,)),
    ("Lulu", "W"): ((("Disable Duration", (1.2, 1.4, 1.6, 1.8, 2.0)),), ()),
    ("Lux", "Q"): ((), (2.0,)),
    ("Malphite", "R"): ((), (1.5,)),
    ("Malzahar", "Q"): ((("Silence Duration", (1.0, 1.25, 1.5, 1.75, 2.0)),), (0.4,)),
    ("Malzahar", "R"): ((), (0.25, 2.5)),
    ("Maokai", "R"): ((), (0.75, 2.25)),
    ("Maokai", "W"): ((("Root Duration", (1.0, 1.1, 1.2, 1.3, 1.4)),), ()),
    ("Mel", "E"): ((("Orb Root Duration", (1.25, 1.5, 1.75, 2.0, 2.25)),), ()),
    ("MonkeyKing", "R"): ((), (0.25, 0.6)),
    ("Mordekaiser", "E"): ((), ()),
    ("Morgana", "Q"): ((("Root Duration", (2.0, 2.25, 2.5, 2.75, 3.0)),), ()),
    ("Nami", "Q"): ((), (0.726, 1.5)),
    ("Nautilus", "Q"): ((), (0.9, 1.0, 1.15)),
    ("Nautilus", "R"): ((("Stun Duration", (1.0, 1.5, 2.0)), ("Knock Up Duration", (1.0, 1.5, 2.0))), (1.0,)),
    ("Neeko", "E"): (
        (("Root Duration", (0.7, 0.9, 1.1, 1.3, 1.5)), ("Empowered Root Duration", (1.8, 2.1, 2.4, 2.7, 3.0))),
        (),
    ),
    ("Neeko", "R"): ((), (0.6, 0.75)),
    ("Nocturne", "E"): ((("Disable Duration", (1.25, 1.5, 1.75, 2.0, 2.25)),), ()),
    ("Orianna", "R"): ((), (0.75,)),
    ("Ornn", "R"): ((), (0.5, 1.0)),
    ("Pantheon", "W"): ((), (1.0,)),
    ("Poppy", "E"): ((("Stun Duration", (1.6, 1.7, 1.8, 1.9, 2.0)),), ()),
    ("Pyke", "Q"): ((), ()),
    ("Quinn", "E"): ((), (0.5, 1.5)),
    ("Rakan", "R"): ((("Disable Duration", (1.0, 1.25, 1.5)),), ()),
    ("Rakan", "W"): ((), (1.0,)),
    ("Rammus", "E"): ((("Taunt Duration", (1.2, 1.4, 1.6, 1.8, 2.0)),), ()),
    ("Rell", "Q"): ((), (0.65,)),
    ("Renekton", "W"): ((), (0.75, 1.5, 7.0)),
    ("Riven", "W"): ((), (0.75,)),
    ("Ryze", "W"): ((), ()),
    ("Sejuani", "Q"): ((), (0.5,)),
    ("Sejuani", "R"): ((), (1.0, 1.5)),
    ("Senna", "W"): ((("Root Duration", (1.25, 1.5, 1.75, 2.0, 2.25)),), ()),
    ("Seraphine", "R"): ((("Disable Duration", (1.25, 1.5, 1.75)),), (0.25,)),
    ("Shaco", "W"): (
        (("Fear Duration", (0.5, 0.75, 1.0, 1.25, 1.5)), ("Root Duration", (0.5, 0.75, 1.0, 1.0, 1.0))),
        (0.3, 1.0, 2.2),
    ),
    ("Shen", "E"): ((), (1.5,)),
    ("Shyvana", "R"): ((), ()),
    ("Singed", "E"): ((("Root Duration", (1.0, 1.25, 1.5, 1.75, 2.0)),), ()),
    ("Sion", "Q"): ((), (0.25, 0.5, 1.0, 1.25, 2.0, 2.25)),
    ("Skarner", "R"): ((), (1.5,)),
    ("Smolder", "R"): ((), ()),
    ("Sona", "R"): ((), (1.5,)),
    ("Soraka", "E"): ((("Root Duration", (1.0, 1.25, 1.5, 1.75, 2.0)),), (1.5,)),
    ("Thresh", "E"): ((), (1.0,)),
    ("Thresh", "Q"): ((), (0.4, 0.6, 1.5, 2.0)),
    ("Tristana", "R"): ((("Stun Duration", (0.4, 0.55, 0.7)),), ()),
    ("Urgot", "E"): ((), (0.25, 1.0, 1.5)),
    ("Varus", "R"): ((), (1.5, 2.0)),
    ("Vayne", "E"): ((), (1.5,)),
    ("Veigar", "E"): ((("Stun Duration", (1.5, 1.75, 2.0, 2.25, 2.5)),), ()),
    ("Vi", "Q"): ((), (0.75,)),
    ("Vi", "R"): ((), (0.25, 0.75, 1.05, 1.3)),
    ("Viego", "W"): ((), (0.25, 1.25, 3.0)),
    ("Volibear", "E"): ((), ()),
    ("Xerath", "E"): ((), (0.75, 2.25)),
    ("XinZhao", "W"): ((), ()),
    ("Yasuo", "R"): ((), (1.0,)),
    ("Yone", "R"): ((), (0.3, 0.75, 1.0)),
    ("Zac", "E"): ((), (0.5, 1.0)),
    ("Zac", "R"): ((), (1.0,)),
    ("Ziggs", "W"): ((), (0.5,)),
    ("Zoe", "E"): ((), (1.4, 2.25)),
    ("Zyra", "E"): ((("Root Duration", (1.0, 1.25, 1.5, 1.75, 2.0)),), (8.0,)),
}

# MEASURED 2026-11-10 at 16.22.1: rows with a CC block, none of which agrees.
_BLOCK_DIVERGE: frozenset[Row] = frozenset(
    {
        ("Ahri", "E"),
        ("Anivia", "Q"),
        ("Braum", "R"),
        ("Elise", "E"),
        ("Fiddlesticks", "Q"),
        ("Gnar", "R"),
        ("Ivern", "Q"),
        ("Jhin", "W"),
        ("Kalista", "R"),
        ("Lulu", "W"),
        ("Neeko", "E"),
        ("Poppy", "E"),
        ("Singed", "E"),
        ("Tristana", "R"),
        ("Veigar", "E"),
    }
)

# MEASURED 2026-11-10 at 16.22.1: rows with no CC block whose CC sentences
# quote seconds figures that miss at least one registry value.
_PROSE_DIVERGE: frozenset[Row] = frozenset(
    {
        ("Amumu", "Q"),
        ("Amumu", "R"),
        ("Ashe", "R"),
        ("AurelionSol", "R"),
        ("Blitzcrank", "Q"),
        ("Draven", "E"),
        ("Galio", "E"),
        ("Galio", "W"),
        ("Hecarim", "E"),
        ("Hecarim", "R"),
        ("Heimerdinger", "E"),
        ("Irelia", "E"),
        ("Janna", "Q"),
        ("KSante", "R"),
        ("Leona", "Q"),
        ("Leona", "R"),
        ("Lux", "Q"),
        ("Malphite", "R"),
        ("Maokai", "R"),
        ("MonkeyKing", "R"),
        ("Nautilus", "Q"),
        ("Neeko", "R"),
        ("Orianna", "R"),
        ("Quinn", "E"),
        ("Rell", "Q"),
        ("Sejuani", "Q"),
        ("Sejuani", "R"),
        ("Sion", "Q"),
        ("Skarner", "R"),
        ("Thresh", "E"),
        ("Urgot", "E"),
        ("Vayne", "E"),
        ("Vi", "R"),
        ("Viego", "W"),
        ("Xerath", "E"),
        ("Zoe", "E"),
    }
)

# MEASURED 2026-11-10 at 16.22.1: rows with no CC block and no seconds figure
# in any CC sentence. Nothing to compare against.
_UNQUOTED: frozenset[Row] = frozenset(
    {
        ("Annie", "R"),
        ("Cassiopeia", "R"),
        ("Diana", "R"),
        ("Mordekaiser", "E"),
        ("Pyke", "Q"),
        ("Ryze", "W"),
        ("Shyvana", "R"),
        ("Smolder", "R"),
        ("Volibear", "E"),
        ("XinZhao", "W"),
    }
)


@pytest.fixture(scope="module")
def live_data() -> Mapping[str, Any]:
    return _abilities()


def _registry_rows() -> set[Row]:
    return {(c, k) for c, spells in _PER_SPELL_CC_DURATIONS.items() for k in spells}


def test_every_row_extracts_exactly_the_pinned_inputs(live_data: Mapping[str, Any]) -> None:
    measured = measure(_PER_SPELL_CC_DURATIONS, live_data)
    assert set(measured) == _registry_rows() == set(_MEASURED)
    assert len(_MEASURED) == 108
    for row, pinned in _MEASURED.items():
        assert measured[row] == pinned, row


def test_classification_is_exactly_the_pinned_worklist(live_data: Mapping[str, Any]) -> None:
    measured = measure(_PER_SPELL_CC_DURATIONS, live_data)
    block_div, prose_div, unquoted, agree = classify(_PER_SPELL_CC_DURATIONS, measured)
    assert block_div == _BLOCK_DIVERGE
    assert prose_div == _PROSE_DIVERGE
    assert unquoted == _UNQUOTED
    assert agree == _registry_rows() - _BLOCK_DIVERGE - _PROSE_DIVERGE - _UNQUOTED
    assert len(agree) == 47


def test_the_pinned_worklist_follows_from_the_pinned_inputs() -> None:
    # Derived from _MEASURED alone, so the worklist cannot drift from the pin.
    block_div, prose_div, unquoted, agree = classify(_PER_SPELL_CC_DURATIONS, _MEASURED)
    assert (block_div, prose_div, unquoted) == (set(_BLOCK_DIVERGE), set(_PROSE_DIVERGE), set(_UNQUOTED))
    classes = [block_div, prose_div, unquoted, agree]
    assert sum(len(c) for c in classes) == len(_MEASURED)
    assert set().union(*classes) == set(_MEASURED)
    assert all(classes)
    # A block row diverges per rank: Braum R 1.0 flat against 1.0/1.5/2.0 is
    # BLOCK-DIVERGE although 1.0 is one of its values.
    assert ("Braum", "R") in block_div
    assert 1.0 in _MEASURED[("Braum", "R")][0][0][1]


def _with_champion_copy(live: Mapping[str, Any], champ: str) -> dict[str, Any]:
    data = dict(live)
    data[champ] = copy.deepcopy(live[champ])
    return data


@pytest.mark.parametrize(
    ("champ", "key", "attr", "occurrence"),
    [
        ("Shaco", "W", "Root Duration", 0),
        ("Neeko", "E", "Empowered Root Duration", 0),
        ("Fiddlesticks", "Q", "Fear Duration", 1),
    ],
)
def test_a_planted_move_in_a_later_cc_block_is_caught(
    live_data: Mapping[str, Any], champ: str, key: str, attr: str, occurrence: int
) -> None:
    data = _with_champion_copy(live_data, champ)
    hits = [
        block
        for form in data[champ][key]
        for block in form.get("damage_blocks") or []
        if block.get("attribute") == attr and block.get("attribute_kind") == "duration"
    ]
    target = hits[occurrence]
    first = cc_blocks(data[champ][key])[0]
    target["raw_modifiers"][0]["values"] = [v + 0.25 for v in target["raw_modifiers"][0]["values"]]
    after = measure({champ: {key: _PER_SPELL_CC_DURATIONS[champ][key]}}, data)[(champ, key)]
    # The planted block is not the first one, so a first-block-only pin would stay green.
    assert len(after[0]) >= 2
    assert after[0][0] == first
    assert after != _MEASURED[(champ, key)]


def test_a_planted_alistar_w_stun_move_is_caught_although_the_row_still_agrees(
    live_data: Mapping[str, Any],
) -> None:
    data = _with_champion_copy(live_data, "Alistar")
    form = data["Alistar"]["W"][0]
    texts = form["effects_descriptions"]
    old, new = "stunning them for 0.75 seconds", "stunning them for 1.25 seconds"
    assert any(old in t for t in texts)
    form["effects_descriptions"] = [t.replace(old, new) for t in texts]
    measured = measure({"Alistar": {"W": _PER_SPELL_CC_DURATIONS["Alistar"]["W"]}}, data)
    assert measured[("Alistar", "W")] != _MEASURED[("Alistar", "W")]
    agree = classify(_PER_SPELL_CC_DURATIONS, measured)[3]
    assert agree == {("Alistar", "W")}


def test_non_cc_duration_blocks_are_excluded() -> None:
    forms = [
        {
            "damage_blocks": [
                {
                    "attribute": "Trap Duration",
                    "attribute_kind": "duration",
                    "raw_modifiers": [{"values": [30, 35], "units": [" seconds", " seconds"]}],
                },
                {
                    "attribute": "Maximum Range Channel Duration",
                    "attribute_kind": "duration",
                    "raw_modifiers": [{"values": [0.9, 1.0], "units": [" seconds", " seconds"]}],
                },
                {
                    "attribute": "Root Duration",
                    "attribute_kind": "duration",
                    "raw_modifiers": [{"values": [1.0, 1.5], "units": [" seconds", " seconds"]}],
                },
                {
                    "attribute": "Stun Damage",
                    "attribute_kind": "damage",
                    "raw_modifiers": [{"values": [9, 9], "units": [" seconds", " seconds"]}],
                },
                {
                    "attribute": "Fear Duration",
                    "attribute_kind": "duration",
                    "raw_modifiers": [{"values": [2.0, 2.5], "units": [" seconds", " seconds"]}],
                },
            ]
        }
    ]
    assert cc_blocks(forms) == (("Root Duration", (1.0, 1.5)), ("Fear Duration", (2.0, 2.5)))


def test_prose_reader_takes_ranges_lists_and_only_cc_sentences() -> None:
    forms = [
        {
            "effects_descriptions": [
                "Grants sight for 9 seconds. Enemies hit are stunned for 0.75 : 2.25 (based on distance) seconds.",
                "Roots them for 1 / 1.5 / 2 seconds. Slows by 30% for 4 seconds.",
            ]
        }
    ]
    assert prose_seconds(forms) == (0.75, 1.0, 1.5, 2.0, 2.25)
    # The documented blind spot: a hyphenated "N-second" figure is not read.
    assert prose_seconds([{"effects_descriptions": ["Stuns them after a 0.4-second delay."]}]) == ()


def test_planted_registry_drift_is_classified() -> None:
    data = {
        "A": {
            "Q": [
                {
                    "damage_blocks": [
                        {
                            "attribute": "Stun Duration",
                            "attribute_kind": "duration",
                            "raw_modifiers": [{"values": [1, 1, 1], "units": ["seconds"] * 3}],
                        }
                    ]
                }
            ]
        },
        "B": {"W": [{"effects_descriptions": ["Knocks them up for 0.5 seconds."]}]},
        "C": {"E": [{"effects_descriptions": ["Stuns them for a duration."]}]},
        "D": {"R": [{"effects_descriptions": ["Roots them for 2 seconds."]}]},
    }
    registry = {"A": {"Q": (1.5, 1.5, 1.5)}, "B": {"W": (0.75,)}, "C": {"E": (1.0,)}, "D": {"R": (2.0, 2.0, 2.0)}}
    block_div, prose_div, unquoted, agree = classify(registry, measure(registry, data))
    assert block_div == {("A", "Q")}
    assert prose_div == {("B", "W")}
    assert unquoted == {("C", "E")}
    assert agree == {("D", "R")}


# ----- S144-D-415b: comment-only module edits -----

_MODULE_SRC = (_REPO / "agents" / "daemon_slayer" / "_per_spell_cc.py").read_text(encoding="utf-8")


def _comment_block_before(assignment: str) -> str:
    lines = _MODULE_SRC.splitlines()
    idx = next(i for i, line in enumerate(lines) if assignment in line)
    block: list[str] = []
    for line in reversed(lines[:idx]):
        if not line.strip().startswith("#"):
            break
        block.append(line.strip().lstrip("#").strip())
    return " ".join(reversed(block))


def test_poppy_e_comment_quotes_the_snapshot_wall_stun() -> None:
    # The comment had said the terrain stun is 1.5s. The 16.10.1 and the
    # 16.22.1 snapshot both give Poppy E Stun Duration 1.6/1.7/1.8/1.9/2.0 and
    # state no time for the contact carry. The row's values are unchanged.
    comment = _comment_block_before('registry.setdefault("Poppy", {})["E"]')
    assert "1.6/1.7/1.8/1.9/2.0" in comment
    assert "1.5s" not in comment
    assert "stun 0.5s" not in comment
    assert "0.5s modeled for the contact carry" in comment
    assert "terrain stun" in comment
    assert _PER_SPELL_CC_DURATIONS["Poppy"]["E"] == (0.5, 0.5, 0.5, 0.5, 0.5)


def test_registry_comment_points_at_the_divergence_pin() -> None:
    # The note sits below the builder because two docs/specs files cite this
    # module's lines 284, 618 and 700 by number, so no line at or above line
    # 700 may move.
    note = _comment_block_before("_PER_SPELL_CC_DURATIONS: dict[")
    assert "agents/daemon_slayer/tests/test_per_spell_cc_meraki_divergence_s144d415.py" in note


def test_the_spec_cited_lines_did_not_move() -> None:
    lines = _MODULE_SRC.splitlines()
    assert "data/daemon_slayer/16.10.1/champion_abilities.json" in lines[284 - 1]
    assert "data/daemon_slayer/16.10.1/champion_abilities.json + cross-checked" in lines[618 - 1]
    assert "walked every UNREGISTERED spell" in lines[700 - 1]
