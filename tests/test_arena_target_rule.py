# Tests for core.arena_target_rule - the Stage 1 pure Arena kill-order line.
#
# target_priority applies the Arena coach's documented kill order
# (coaches/arena_coach.py:148 - carries first, tanks last) to an
# already-classified opponent list. The frontline classification itself
# happens in the wiring layer; these tests pass the sets directly.
from __future__ import annotations

from core.arena_target_rule import target_priority


def test_first_squishy_wins_even_when_listed_after_a_frontline() -> None:
    out = target_priority(["Malphite", "Jinx"], {"Malphite"})
    assert out.startswith("Kill Jinx first")
    assert "squishy threat" in out
    assert "tanks last" in out


def test_first_non_frontline_in_list_order() -> None:
    # Two squishies: list order decides, not alphabetical.
    out = target_priority(["Vayne", "Jinx"], set())
    assert out.startswith("Kill Vayne first")


def test_all_frontline_names_the_first() -> None:
    out = target_priority(["Ornn", "Malphite"], {"Ornn", "Malphite"})
    assert out.startswith("Kill Ornn first")
    assert "no squishy target" in out


def test_empty_and_none_inputs_return_empty() -> None:
    assert target_priority([], set()) == ""
    assert target_priority(None, {"Ornn"}) == ""
    # Entries that are not non-blank strings are skipped entirely; a list
    # with nothing usable degrades to "" like an empty one.
    assert target_priority([None, "", 42], set()) == ""


def test_non_str_entries_are_skipped() -> None:
    out = target_priority([42, None, {"champ": "Jinx"}, "Jinx"], set())
    assert out.startswith("Kill Jinx first")
    # A list with no usable names at all yields "".
    assert target_priority([42, None, 3.5], set()) == ""


def test_frontline_names_accepts_set_list_and_none() -> None:
    expected = "Kill Jinx first"
    assert target_priority(["Malphite", "Jinx"], {"Malphite"}).startswith(expected)
    assert target_priority(["Malphite", "Jinx"], ["Malphite"]).startswith(expected)
    # None frontline set -> nobody is classified frontline; first name wins
    # as the squishy pick.
    out = target_priority(["Malphite", "Jinx"], None)
    assert out.startswith("Kill Malphite first")
    assert "squishy threat" in out


def test_output_clamped_to_twelve_words() -> None:
    # Multi-word display names can push the template over budget; the
    # clamp keeps the line overlay-safe.
    out = target_priority(["Aurelion Sol The Star Forger Of Great Renown"], set())
    assert out != ""
    assert len(out.split()) <= 12
    out2 = target_priority(["Jinx"], set())
    assert len(out2.split()) <= 12


def test_never_raises_on_garbage() -> None:
    class _Nasty:
        def __iter__(self):
            raise RuntimeError("boom")

        def __bool__(self):
            raise RuntimeError("boom")

    for opponents in (None, "Jinx", 42, {"a": 1}, _Nasty(), ["Jinx"]):
        for frontline in (None, "Malphite", 42, _Nasty(), {"Malphite"}):
            out = target_priority(opponents, frontline)
            assert isinstance(out, str)
