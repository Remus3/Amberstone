# arch: tests for the deterministic Arena augment play-line | section=tests | frozen=no
"""Property tests for core.arena_augment_playline + its build_block wiring.

The module fills the ONE column that was hardcoded empty in the deterministic
Arena block (core/arena_deterministic_coach.py augment_advice). It answers the
"Else: play your current augment this way" half of the live prompt line at
coaches/arena_coach.py:171 from data already on disk, with NO LLM call.

Assertions are invariants over the WHOLE live augment set rather than pins on
individual augment names, so a patch re-extract does not falsify the suite.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core import arena_augment_playline as apl
from core.arena_deterministic_coach import build_block

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clear_cache():
    apl.reset_cache()
    yield
    apl.reset_cache()


def _index() -> dict:
    return apl._load_index()


def test_index_loads_and_is_non_trivial() -> None:
    idx = _index()
    assert len(idx) > 100, "live arena_augments.json should resolve many rows"


def test_every_augment_resolves_by_api_name() -> None:
    """Every apiName in the live file produces a usable, name-bearing line."""
    seen = 0
    for row in apl._rows():
        api = row.get("apiName") or ""
        name = str(row.get("name") or "").strip()
        if not api or not name:
            continue
        seen += 1
        line = apl.play_line([api])
        assert line, f"{api} produced an empty play line"
        assert name in line, f"{api} line omits its display name: {line!r}"
    assert seen > 100


@pytest.mark.parametrize("bad", ["<", ">", "@"])
def test_no_markup_or_placeholder_ever_leaks(bad: str) -> None:
    """Riot markup tags and unresolved @Var@ placeholders never reach output."""
    for row in apl._rows():
        api = row.get("apiName") or ""
        if not api:
            continue
        line = apl.play_line([api])
        assert bad not in line, f"{api} leaked {bad!r}: {line!r}"


def test_no_space_before_punctuation() -> None:
    """Tag stripping must not leave ' .' / ' ,' artifacts."""
    for row in apl._rows():
        api = row.get("apiName") or ""
        if not api:
            continue
        line = apl.play_line([api])
        assert not re.search(r"\s+[.,;:!?]", line), f"{api}: {line!r}"


def test_display_name_resolves_same_as_api_name() -> None:
    """Vision may hand back display names; both routes must agree."""
    for row in apl._rows():
        api = row.get("apiName") or ""
        name = str(row.get("name") or "").strip()
        if not api or not name:
            continue
        assert apl.play_line([name]) == apl.play_line([api])


@pytest.mark.parametrize(
    "empty",
    [None, [], (), "", set(), 0, 123, object(), {"a": 1}, [None], ["", "  "]],
)
def test_empty_or_garbage_yields_empty_string(empty: object) -> None:
    assert apl.play_line(empty) == ""


@pytest.mark.parametrize(
    "fuzz",
    [
        ["NotARealAugment"],
        ["NotARealAugment", "AlsoFake"],
        [{"nested": "dict"}],
        [["nested", "list"]],
        [3.14, None, b"bytes"],
        float("nan"),
    ],
)
def test_never_raises_on_fuzz(fuzz: object) -> None:
    out = apl.play_line(fuzz)
    assert isinstance(out, str)


def test_unresolvable_names_are_skipped_not_invented() -> None:
    assert apl.play_line(["DefinitelyNotAnAugment"]) == ""


def test_bare_string_is_one_augment_not_characters() -> None:
    """A bare str must not be iterated per-character."""
    row = next(r for r in apl._rows() if r.get("apiName") and r.get("name"))
    api = row["apiName"]
    assert apl.play_line(api) == apl.play_line([api])


def test_max_augments_cap_is_respected() -> None:
    apis = [r["apiName"] for r in apl._rows() if r.get("apiName")][:6]
    assert len(apis) == 6
    capped = apl.play_line(apis, max_augments=2)
    full = apl.play_line(apis, max_augments=6)
    assert capped.count(apl.SEPARATOR) == 1
    assert full.count(apl.SEPARATOR) == 5
    assert len(capped) < len(full)


def test_output_is_deterministic() -> None:
    apis = [r["apiName"] for r in apl._rows() if r.get("apiName")][:3]
    first = apl.play_line(apis)
    apl.reset_cache()
    assert apl.play_line(apis) == first


def test_order_is_preserved_from_input() -> None:
    rows = [r for r in apl._rows() if r.get("apiName") and r.get("name")][:3]
    apis = [r["apiName"] for r in rows]
    line = apl.play_line(apis)
    positions = [line.index(str(r["name"])) for r in rows]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    "module",
    ["core/arena_augment_playline.py", "core/arena_deterministic_coach.py"],
)
@pytest.mark.parametrize(
    "forbidden", ["anthropic", "messages.create", "claude-haiku", "api_key"]
)
def test_deterministic_path_makes_no_llm_call(module: str, forbidden: str) -> None:
    """The deterministic path must never construct a client or call the API."""
    src = (_REPO / module).read_text(encoding="utf-8")
    assert forbidden not in src, f"{module} references {forbidden!r}"


def test_no_network_module_imported_by_playline() -> None:
    src = (_REPO / "core/arena_augment_playline.py").read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "urllib.request", "socket"):
        assert banned not in src, f"playline imports {banned}"


def test_build_block_fills_augment_advice_from_owned_augments() -> None:
    api = next(r["apiName"] for r in apl._rows() if r.get("apiName"))
    block = build_block(owned_augments=[api])
    assert block["augment_advice"], "owned augments must populate augment_advice"
    assert block["augment_advice"] == apl.play_line([api])


def test_build_block_augment_advice_empty_without_owned_augments() -> None:
    """No owned-augment signal stays honestly empty rather than guessing."""
    for kwargs in ({}, {"hp_pct": 90}, {"owned_augments": []},
                   {"owned_augments": None}, {"owned_augments": ["Fake"]}):
        assert build_block(**kwargs)["augment_advice"] == ""


def test_build_block_still_never_raises_with_bad_owned_augments() -> None:
    for bad in (object(), 5, {"x": 1}, [object()], float("nan")):
        block = build_block(owned_augments=bad)
        assert isinstance(block["augment_advice"], str)


def test_build_block_key_set_is_unchanged() -> None:
    """Wiring a field must not add or drop a column."""
    expected = {
        "action", "round_strategy", "fight_rule", "augment_advice",
        "anvil_advice", "target_priority", "risk", "choices",
    }
    assert set(build_block().keys()) == expected
    assert set(build_block(owned_augments=["x"]).keys()) == expected
