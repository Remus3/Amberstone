"""S136 T14: the TFT coach prompt renders a unit's STAR LEVEL so it cannot be
read as a copy count, and states how many units are on the board.

Live game 5667197548 (ops/runtime/tft_qa/20261025-162857 LIVE_NOTES_s136_g2):
tft/tft_coach_engine.py _fmt_board rendered the per-round board as
``Yunara*2, Yorick*2`` with no legend, so the model read ``*2`` as two copies
- 55 of 102 coach outputs gave a 2-star unit two board slots ("Yunara2 A1/A5,
Yorick2 B2/B6": 11 slots for 7 units) and upgrade lines said "collect third
copy" for a unit already 2-star.

Contract:
- a 2-star unit renders as ``Name (2-star)``; a 1-star unit is untagged;
- the prompt never carries a ``Name*N`` form;
- a ``Units on board: N`` line states the count, one slot per unit, and that
  ``N-star`` is a star level, not copies;
- two 1-star copies are two listed units (the count says 2), never a
  multiplier;
- the system prompt's Board field asks for each listed unit once.
"""
from __future__ import annotations

import re

import pytest

from tft import tft_coach_engine as eng
from tft import tft_prompt

_NAME_STAR_N = re.compile(r"[A-Za-z'.]\*\d")


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    """Set 18, no vision file, no verified meta (no comp / augment section)."""
    monkeypatch.setattr(eng, "_resolved_set", lambda: 18)
    monkeypatch.setattr(eng, "_set_has_gods", lambda: False)
    monkeypatch.setattr(eng, "_meta_verified", lambda: False)
    vision = {"doc": {}}
    monkeypatch.setattr(eng, "_live_data", lambda: vision["doc"])
    return vision


def _u(name, star, items=()):
    return {"name": name, "star": star, "items": list(items)}


# The 4-2 board of the live game (LIVE_NOTES_s136_g2 sample 16:51:48).
_BOARD_42 = [_u("Yunara", 2, ["Guinsoos Rageblade"]), _u("Yorick", 2), _u("Karma", 2),
             _u("Diana", 2, ["Bramble Vest"]), _u("Fiddlesticks", 2), _u("Soraka", 1),
             _u("Draven", 1)]


def _prompt(board, **kw) -> str:
    state = {"stage": 4, "round": 2, "level": 7, "gold": 44, "health": 69,
             "board": board, "items_str": "none"}
    state.update(kw)
    return eng._build_prompt(state)


def _line(prompt: str, prefix: str) -> str:
    rows = [ln for ln in prompt.splitlines() if ln.startswith(prefix)]
    assert len(rows) <= 1, rows
    return rows[0] if rows else ""


def test_two_star_unit_renders_its_star_level_not_a_multiplier():
    prompt = _prompt(_BOARD_42)
    board = _line(prompt, "Board units:")
    assert board == ("Board units: Yunara (2-star) [Guinsoos Rageblade], "
                     "Yorick (2-star), Karma (2-star), Diana (2-star) [Bramble Vest], "
                     "Fiddlesticks (2-star), Soraka, Draven"), board


def test_prompt_never_carries_a_name_star_n_form():
    prompt = _prompt(_BOARD_42)
    assert not _NAME_STAR_N.search(prompt), _NAME_STAR_N.findall(prompt)


def test_board_count_line_states_the_unit_count_and_the_legend():
    prompt = _prompt(_BOARD_42)
    count = _line(prompt, "Units on board:")
    assert count.startswith("Units on board: 7 "), count
    assert "one slot each" in count
    assert '"2-star" = star level, not copies' in count
    assert "untagged = 1-star" in count
    # the count sits next to the list it counts
    rows = prompt.splitlines()
    assert rows.index(count) == rows.index(_line(prompt, "Board units:")) + 1


def test_two_one_star_copies_are_two_listed_units_never_a_multiplier():
    prompt = _prompt([_u("Yorick", 1), _u("Yorick", 1), _u("Rakan", 3)])
    assert _line(prompt, "Board units:") == "Board units: Yorick, Yorick, Rakan (3-star)"
    assert _line(prompt, "Units on board:").startswith("Units on board: 3 ")
    assert not _NAME_STAR_N.search(prompt)


@pytest.mark.parametrize("star", [None, "x", 0, -2, True, 2.5])
def test_missing_or_bad_star_renders_the_bare_name(star):
    prompt = _prompt([{"name": "Karma", "star": star, "items": []}, {"name": "Diana"}])
    assert _line(prompt, "Board units:") == "Board units: Karma, Diana"
    assert "None" not in _line(prompt, "Board units:")
    assert not _NAME_STAR_N.search(prompt)


def test_vision_board_gets_the_count_but_no_one_star_claim(_pin):
    _pin["doc"] = {"board_units": ["Krug 3-star", "Leona (2)", "unknown"]}
    prompt = eng._build_prompt({"stage": 2, "round": 2, "level": 4, "board": []})
    assert _line(prompt, "Board units:") == "Board units: Krug 3-star, Leona (2)"
    count = _line(prompt, "Units on board:")
    assert count.startswith("Units on board: 2 "), count
    assert '"2-star" = star level, not copies' in count
    # vision leaves an unread star untagged: no 1-star claim for it
    assert "untagged" not in count


def test_no_board_no_count_line():
    prompt = _prompt([])
    assert not _line(prompt, "Board units:")
    assert not _line(prompt, "Units on board:")


def test_system_prompt_board_field_asks_for_each_listed_unit_once():
    text = tft_prompt.build_system_prompt(18)
    board = [ln for ln in text.splitlines() if ln.startswith("Board:")]
    assert board == ["Board: each listed unit once + its grid slot "
                     "(tanks A wide, carries D6-7)"], board
    assert len(text) <= tft_prompt.MAX_PROMPT_CHARS
