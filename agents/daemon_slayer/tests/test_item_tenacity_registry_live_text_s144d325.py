"""S144-D-325..328 - the DS item tenacity registry matches the live text it cites.

WHY. ``_item_tenacity`` copies a tenacity percent out of each item's DDragon
description, labels every row with the map flags it read, names the items it
leaves out on purpose, says which rows carry a gated (conditional) tenacity,
and documents the scan that regenerates it on a patch bump. Its magnitude
guard (``test_r144_mirror_slice_b.py``) pins each percent to its own text;
nothing pinned the labels, the exclusion list, the conditional caveat or the
recipe, and all four had drifted from the live snapshot.

* S144-D-325: every row's ``maps ...`` comment names exactly the map flags its
  live ``items.json`` row sets. Thirteen comments still named the 16.11.1
  flags (``11/12/21/35``, ``SR only``) after the throwback map 453 replaced
  maps 21 / 35.
* S144-D-326: the description rows that mention Tenacity but sit outside the
  registry are exactly the documented five exclusions, each still carrying the
  live phrase it was excluded for, and the docstring states that one count
  (its regeneration line said "drop the 3 excluded ids").
* S144-D-327: the docstring named Wit's End / Sterak's as the gated rows, but
  both carry their tenacity as an unconditional ``<stats>`` line at 16.22.1.
  The only rows whose tenacity lies outside ``<stats>`` are Protoplasm Harness
  (2525 / 222525), gated to its Lifeline window. Docstring corrected; the
  modeling change is a Tier-2 follow-up, not made here.
* S144-D-328: the documented regeneration scan reproduces the registry exactly,
  ids and values. The old recipe matched only ``<attention>N%</attention>``
  and would have dropped Protoplasm Harness, whose 25% is untagged. The
  docstring also cited its magnitude guard as ``tests/test_r144_...``, a path
  that does not exist (the file lives under ``agents/daemon_slayer/tests/``).

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Guards plus
docstring / comment fixes; no registry value changes, so the scorer output is
byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _item_tenacity as ten_mod
from agents.daemon_slayer._item_tenacity import _ITEM_TENACITY

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_DOC = ten_mod.__doc__ or ""
_SOURCE = inspect.getsource(ten_mod)

# The documented exclusions: id -> a phrase its live text must still carry.
_EXCLUDED: dict[str, str] = {
    "6035": "Quicksilver",
    "226035": "Quicksilver",
    "8001": "reduced Tenacity",
    "228001": "reduced Tenacity",
    "2138": "Consume",
}
_CONDITIONAL = frozenset({"2525", "222525"})

_ROW_RE = re.compile(r'^\s*"(\d{4,6})"\s*:\s*[\d.]+\s*,\s*#\s*(.+?)\s*$')
_MAPS_RE = re.compile(r"\bmaps (none|\d+(?:/\d+)*)\b")
_NUMBER_WORDS = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _items() -> dict[str, Any]:
    raw = json.loads((_patch_dir() / "items.json").read_text(encoding="utf-8"))
    return raw["data"]


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _live_maps(item_id: str) -> set[str]:
    return {m for m, on in (_items()[item_id].get("maps") or {}).items() if on}


def comment_rows(source: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for line in source.splitlines() if (m := _ROW_RE.match(line))}


def map_problems(rows: dict[str, str], items: dict[str, Any]) -> list[str]:
    problems = []
    for iid, comment in sorted(rows.items()):
        found = _MAPS_RE.findall(comment)
        if len(found) != 1:
            problems.append(f"{iid}: comment carries {len(found)} maps labels: {comment!r}")
            continue
        claimed = set() if found[0] == "none" else set(found[0].split("/"))
        live = {m for m, on in (items[iid].get("maps") or {}).items() if on}
        if claimed != live:
            problems.append(f"{iid}: comment says maps {sorted(claimed)}, live {sorted(live)}")
    return problems


def regen_scan(items: dict[str, Any], excluded: frozenset[str]) -> dict[str, float]:
    """The regeneration scan the module docstring documents."""
    out = {}
    for iid, row in items.items():
        if iid in excluded:
            continue
        found = re.findall(r"(\d+(?:\.\d+)?)% Tenacity", _plain(row.get("description", "")))
        if found:
            assert len(found) == 1, (iid, found)
            out[iid] = float(found[0])
    return out


# ---------------------------------------------------------------- S144-D-325


def test_every_row_has_a_comment() -> None:
    assert set(comment_rows(_SOURCE)) == set(_ITEM_TENACITY)


def test_row_map_comments_match_live_flags() -> None:
    assert map_problems(comment_rows(_SOURCE), _items()) == []


def test_map_checker_catches_planted_defects() -> None:
    rows = comment_rows(_SOURCE)
    planted = dict(rows)
    planted["3111"] = "Mercury's Treads - maps 11/12/21/35"
    planted["4012"] = "Sin Eater - not equippable this patch"
    problems = map_problems(planted, _items())
    assert any(p.startswith("3111:") for p in problems)
    assert any(p.startswith("4012:") for p in problems)


def test_silvermere_rows_are_map_dead_as_the_docstring_says() -> None:
    assert "map-dead this patch" in _DOC
    for iid in ("6035", "226035"):
        assert _live_maps(iid) == set(), iid


# ---------------------------------------------------------------- S144-D-326


def test_out_of_registry_tenacity_mentions_are_exactly_the_exclusions() -> None:
    mentions = {
        iid
        for iid, row in _items().items()
        if "Tenacity" in _plain(row.get("description", ""))
    }
    assert mentions - set(_ITEM_TENACITY) == set(_EXCLUDED)


@pytest.mark.parametrize("item_id", sorted(_EXCLUDED))
def test_each_exclusion_keeps_its_live_reason(item_id: str) -> None:
    assert _EXCLUDED[item_id] in _plain(_items()[item_id]["description"])
    assert item_id in _DOC


def test_elixir_exclusion_is_a_consumable() -> None:
    assert _items()["2138"].get("consumed") is True


def test_docstring_states_one_exclusion_count() -> None:
    counts = set()
    for word in re.findall(r"\b(\w+) excluded ids\b|\bthese (\w+) ids\b", _DOC):
        token = next(w for w in word if w)
        counts.add(int(token) if token.isdigit() else _NUMBER_WORDS[token])
    assert counts == {len(_EXCLUDED)}


def test_gunmetal_greaves_grants_no_tenacity() -> None:
    assert "3172" not in _ITEM_TENACITY
    assert "% Tenacity" not in _plain(_items()["3172"]["description"])


# ---------------------------------------------------------------- S144-D-327


def _stats_block(item_id: str) -> str:
    m = re.search(r"<stats>(.*?)</stats>", _items()[item_id]["description"], re.S)
    return m.group(1) if m else ""


def test_only_protoplasm_rows_carry_tenacity_outside_stats() -> None:
    outside = {iid for iid in _ITEM_TENACITY if "Tenacity" not in _stats_block(iid)}
    assert outside == _CONDITIONAL


@pytest.mark.parametrize("item_id", sorted(_CONDITIONAL))
def test_protoplasm_tenacity_is_gated_to_lifeline(item_id: str) -> None:
    text = _plain(_items()[item_id]["description"])
    assert "Lifeline" in text
    assert "While regenerating Health" in text
    assert "25% Tenacity" in text


def test_docstring_names_the_live_conditional_rows() -> None:
    flat = re.sub(r"\s+", " ", _DOC)
    assert "Wit's End / Sterak's tenacity has" not in flat
    assert "Protoplasm Harness" in flat
    assert "Lifeline" in flat


# ---------------------------------------------------------------- S144-D-328


def test_documented_regen_scan_reproduces_the_registry() -> None:
    assert regen_scan(_items(), frozenset(_EXCLUDED)) == _ITEM_TENACITY


def test_attention_only_scan_would_drop_the_conditional_rows() -> None:
    tagged = {
        iid
        for iid in _ITEM_TENACITY
        if re.search(r"<attention>\d+%</attention>\s*Tenacity", _items()[iid]["description"])
    }
    assert set(_ITEM_TENACITY) - tagged == _CONDITIONAL


def test_docstring_cited_test_paths_exist() -> None:
    cited = re.findall(r"``([\w/]+\.py)``", _DOC)
    tests = [c for c in cited if "/tests/" in f"/{c}"]
    assert tests
    for rel in tests:
        assert (_REPO_ROOT / rel).is_file(), rel


def test_docstring_recipe_is_the_tag_stripped_scan() -> None:
    flat = re.sub(r"\s+", " ", _DOC)
    assert "parse ``<attention>N%</attention>`` adjacent" not in flat
    assert "N% Tenacity" in flat
