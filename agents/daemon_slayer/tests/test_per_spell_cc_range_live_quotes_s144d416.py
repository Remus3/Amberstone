"""S144-D-416 - every ``_PER_SPELL_CC_RANGE`` row matches the snapshot text its
comment quotes.

Each row's comment in ``_build_per_spell_cc_range`` quotes one sentence part
of the spell's ``effects_descriptions`` ("... for A : B (based on ...)
seconds") and names the row's flat ``_PER_SPELL_CC_DURATIONS`` tuple. For
every row this test checks:

* the quoted text appears, whitespace-normalised, in that spell's
  ``effects_descriptions`` in the shipped snapshot
  (``data/daemon_slayer/<current.txt>/champion_abilities.json``);
* the quote's ``A : B`` pair equals the row's (min, max);
* the flat tuple the comment names equals the row in ``_PER_SPELL_CC_DURATIONS``
  (written either as ``R=(a, b, c)`` or as ``(lo..hi)``, the first and last
  rank values).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import pytest

from agents.daemon_slayer._per_spell_cc import _PER_SPELL_CC_DURATIONS, _PER_SPELL_CC_RANGE

_REPO = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO / "data" / "daemon_slayer"
_MODULE = _REPO / "agents" / "daemon_slayer" / "_per_spell_cc.py"

_ASSIGN = re.compile(r'^\s*registry\.setdefault\("(\w+)", \{\}\)\["([QWER])"\] = ')
_RANGE_PAIR = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
_FLAT_TUPLE = re.compile(r"R=\(([^)]*)\)")
_FLAT_SPAN = re.compile(r"\((\d+(?:\.\d+)?)\.\.(\d+(?:\.\d+)?)\)")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _abilities() -> Mapping[str, Any]:
    patch = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    path = _DS_DATA / patch / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def range_row_comments(src: str) -> dict[tuple[str, str], str]:
    """(champion, key) -> the joined ``#`` comment block above each range-row assignment."""
    lines = src.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("def _build_per_spell_cc_range"))
    out: dict[tuple[str, str], str] = {}
    for i in range(start + 1, len(lines)):
        if not lines[i].startswith((" ", "\t")) and lines[i].strip():
            break
        m = _ASSIGN.match(lines[i])
        if not m:
            continue
        block: list[str] = []
        j = i - 1
        while lines[j].strip().startswith("#"):
            block.insert(0, lines[j].strip().lstrip("#").strip())
            j -= 1
        out[(m.group(1), m.group(2))] = _norm(" ".join(block))
    return out


def row_defects(
    comments: Mapping[tuple[str, str], str],
    ranges: Mapping[str, Mapping[str, tuple[float, float]]],
    flat: Mapping[str, Mapping[str, tuple[float, ...]]],
    data: Mapping[str, Any],
) -> list[str]:
    defects: list[str] = []
    rows = {(c, k) for c, spells in ranges.items() for k in spells}
    if set(comments) != rows:
        defects.append(f"comment rows {sorted(comments)} != registry rows {sorted(rows)}")
    for (champ, key), comment in sorted(comments.items()):
        if (champ, key) not in rows:
            continue
        quotes = re.findall(r'"([^"]+)"', comment)
        if len(quotes) != 1:
            defects.append(f"{champ} {key}: expected one quote, found {len(quotes)}")
            continue
        quote = quotes[0]
        texts = [
            _norm(str(t))
            for form in (data.get(champ) or {}).get(key) or []
            for t in form.get("effects_descriptions") or []
        ]
        if not any(quote in t for t in texts):
            defects.append(f"{champ} {key}: quote not in the snapshot text: {quote!r}")
        pair = _RANGE_PAIR.search(quote)
        if pair is None or (float(pair.group(1)), float(pair.group(2))) != tuple(ranges[champ][key]):
            defects.append(f"{champ} {key}: quoted range != row {ranges[champ][key]}")
        values = tuple(flat.get(champ, {}).get(key, ()))
        tup = _FLAT_TUPLE.search(comment)
        span = _FLAT_SPAN.search(comment)
        if tup is not None:
            named = tuple(float(v) for v in tup.group(1).split(","))
            if named != values:
                defects.append(f"{champ} {key}: comment flat {named} != registry {values}")
        elif span is not None:
            if not values or (float(span.group(1)), float(span.group(2))) != (values[0], values[-1]):
                defects.append(f"{champ} {key}: comment flat span != registry {values}")
        else:
            defects.append(f"{champ} {key}: comment names no flat tuple")
    return defects


@pytest.fixture(scope="module")
def live_data() -> Mapping[str, Any]:
    return _abilities()


@pytest.fixture(scope="module")
def comments() -> dict[tuple[str, str], str]:
    return range_row_comments(_MODULE.read_text(encoding="utf-8"))


def test_every_range_row_matches_its_quoted_snapshot_text(
    comments: dict[tuple[str, str], str], live_data: Mapping[str, Any]
) -> None:
    assert len(comments) == 4
    assert row_defects(comments, _PER_SPELL_CC_RANGE, _PER_SPELL_CC_DURATIONS, live_data) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        ("range", "quoted range != row"),
        ("quote", "quote not in the snapshot text"),
        ("flat", "comment flat"),
        ("span", "comment flat span"),
        ("row", "comment rows"),
    ],
)
def test_planted_defects_are_caught(
    comments: dict[tuple[str, str], str], live_data: Mapping[str, Any], mutate: str, expected: str
) -> None:
    ranges = {c: dict(s) for c, s in _PER_SPELL_CC_RANGE.items()}
    flat = {c: dict(s) for c, s in _PER_SPELL_CC_DURATIONS.items()}
    planted = dict(comments)
    if mutate == "range":
        ranges["Hecarim"]["R"] = (0.75, 0.9)
    elif mutate == "quote":
        planted[("Ashe", "R")] = planted[("Ashe", "R")].replace("1 : 3.5", "1 : 3.75")
    elif mutate == "flat":
        flat["Maokai"]["R"] = (1.2, 1.6, 2.1)
    elif mutate == "span":
        flat["Xerath"]["E"] = (1.0, 1.25, 1.5, 1.75, 2.25)
    else:
        ranges["Zoe"] = {"E": (1.0, 2.0)}
    defects = row_defects(planted, ranges, flat, live_data)
    assert any(expected in d for d in defects), defects
