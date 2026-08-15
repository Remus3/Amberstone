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


# The characters that occur in real English prose. Deliberately spelled out
# here rather than imported from the module: the test states the PROPERTY the
# player-facing string must have, and the module has to satisfy it on its own
# terms. Anything outside this set is a template sigil, not prose.
_PROSE_CHARS = frozenset(
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " .,;:!?'\"()/%+-"
)

# Riot's desc field is a template language, and enumerating the token shapes it
# ships today is exactly the trap that let 17 of them through. These families
# are the reader's-side statement of the same property: a served string holds
# no bracketed construct of ANY kind. Families Riot does not currently use are
# listed on purpose, so a future patch shipping one is caught by this suite
# rather than by a player.
_TOKEN_FAMILIES = {
    "riot-placeholder": r"@[^@]*@",
    "double-brace": r"\{\{.*?\}\}",
    "single-brace": r"\{[^{}]*\}",
    "icon-ref": r"%[A-Za-z][^%]*%",
    "html-tag": r"<[^>]*>",
    "square-bracket": r"\[[^\]]*\]",
    "dollar-brace": r"\$\{[^}]*\}",
    "double-square": r"\[\[.*?\]\]",
    "double-percent": r"%%[^%]*%%",
    "angle-double": r"<<.*?>>",
}


def _served_lines() -> list[tuple[str, str]]:
    """Every (apiName, served string) pair the live augment set can produce."""
    out = []
    for row in apl._rows():
        api = row.get("apiName") or ""
        if not api:
            continue
        out.append((api, apl.play_line([api])))
    assert len(out) > 100, "live augment set should yield many served lines"
    return out


def _served_effects() -> list[tuple[str, str, str]]:
    """(apiName, line, effect) - effect is '' for a name-only line.

    The name is stripped by the row's OWN name rather than by splitting on
    ': ', because augment names contain colons ("Transmute: Chaos") and a
    naive split reads such a name as if it were an effect.
    """
    out = []
    for row in apl._rows():
        api = row.get("apiName") or ""
        name = str(row.get("name") or "").strip()
        if not api or not name:
            continue
        line = apl.play_line([api])
        if line == f"Playing {name}.":
            out.append((api, line, ""))
            continue
        prefix = f"Playing {name}: "
        assert line.startswith(prefix), f"{api} unexpected line shape: {line!r}"
        out.append((api, line, line[len(prefix):]))
    assert len(out) > 100
    return out


def test_served_output_is_plain_prose_only() -> None:
    """No template sigil of any shape reaches the player.

    This is the general form of the rule. A sigil-delimited token cannot exist
    without its delimiter, so forbidding every non-prose character forbids the
    whole family - including shapes nobody has seen yet.
    """
    for api, line in _served_lines():
        bad = sorted(set(line) - _PROSE_CHARS)
        assert not bad, f"{api} served non-prose {bad!r}: {line!r}"


@pytest.mark.parametrize("family", sorted(_TOKEN_FAMILIES))
def test_no_unresolved_token_family_survives(family: str) -> None:
    """No bracketed template construct survives into served output."""
    pattern = re.compile(_TOKEN_FAMILIES[family])
    for api, line in _served_lines():
        found = pattern.search(line)
        assert not found, f"{api} leaked {family} {found.group(0)!r}: {line!r}"


def test_percent_is_only_ever_a_percent_sign() -> None:
    """'%' reuses a prose character, so position is what separates the uses.

    A percent SIGN always follows its number ("40%"). A '%' used as a template
    delimiter ("%i:StatAnvil%") does not - that is the discriminator, and it
    holds without knowing which icon names Riot ships this patch.
    """
    for api, line in _served_lines():
        for match in re.finditer("%", line):
            prefix = line[:match.start()]
            assert prefix[-1:].isdigit(), (
                f"{api} served a non-numeric '%' at {match.start()}: {line!r}"
            )


def test_served_output_is_seven_bit_ascii() -> None:
    """Repo-wide ASCII rule holds for data-derived output too."""
    for api, line in _served_lines():
        assert line.isascii(), f"{api} served non-ASCII: {line!r}"


def test_no_content_free_effect_is_served() -> None:
    """A row whose desc carries no real content degrades to name-only.

    Riot ships sentinel rows (NullAugment's desc is the literal string "Null").
    Restating a sentinel as advice is noise, so an effect has to be at least a
    couple of real words before it earns a place next to the augment name.
    """
    for api, line, effect in _served_effects():
        assert line, f"{api} produced no line at all"
        if not effect:
            continue
        assert len(re.findall(r"[A-Za-z]{2,}", effect)) >= 2, (
            f"{api} served a content-free effect: {line!r}"
        )


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
