"""RM-346 - champ-select session parsing must survive JSON nulls and junk.

The three `LcuPregame` session readers all document total contracts
("0 if none", "(0, 0)", a list of ids) but implemented them with
`int(d.get(key, 0))`. `dict.get(key, default)` returns the DEFAULT only
when the key is ABSENT - when the key is PRESENT carrying a JSON `null`
it returns `None`, and `int(None)` raises TypeError. The LCU sends
exactly that shape in the pre-hover window of champ select, before the
local player has hovered a champion:

    {"cellId": 0, "championId": null, "championPickIntent": null,
     "spell1Id": null, "spell2Id": null}

Three holes, one root cause plus one type variant:

  1. `get_my_current_champion` - both ids null -> `int(None)` TypeError.
     There is no try/except in the method, so the crash escapes to
     whatever calls it.

REACHABILITY, measured 2026-09-05 and deliberately recorded here: these
three methods have ZERO in-repo callers. `LcuPregame` is mixed into
`LcuClient`, so they are public surface an external caller can reach,
but no path in this tree invokes them (`tools/lcu_agent.py` dispatches
`bench_swap` only, and there is no getattr dispatch table). The row that
filed this defect described them as sitting on the champ-select poll and
the spell auto-push path; that reachability was inherited, not proven,
and it does not hold here. The fix is still correct - a documented total
contract that raises is a defect regardless of current call count - but
it is a latent one, not a live crash.
  2. `get_my_summoner_spells` - ONE null id is enough to raise.
  3. `get_bench_champion_ids` - the trailing `if b.get("championId")`
     already filters the null case, so this site is the ELEMENT-TYPE
     hole only: a non-dict bench element (the LCU sends bare ints in
     some payload versions) raises AttributeError on `b.get`.

These tests pin the documented contracts, the coercion contract for
non-numeric junk (coerce to 0 / skip, never raise), and the pre-existing
happy paths so the fix cannot silently change them.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from lcu.lcu_pregame import LcuPregame  # noqa: E402

_FLASH = 4
_SNOWBALL = 32


def _pregame() -> LcuPregame:
    """LcuPregame is a mixin with no __init__; the three session parsers
    touch no transport state, so a bare instance is a faithful subject."""
    return LcuPregame()


def _session(**player_fields) -> dict:
    """A champ-select session whose single myTeam entry is my cell."""
    player = {"cellId": 0}
    player.update(player_fields)
    return {"localPlayerCellId": 0, "myTeam": [player]}


# -- get_my_current_champion ---------------------------------------------------

def test_current_champion_both_ids_null_returns_zero():
    """The row's stated acceptance: pre-hover window, both ids null."""
    session = {
        "localPlayerCellId": 0,
        "myTeam": [{"cellId": 0, "championId": None, "championPickIntent": None}],
    }
    assert _pregame().get_my_current_champion(session) == 0


def test_current_champion_null_id_falls_through_to_pick_intent():
    session = _session(championId=None, championPickIntent=266)
    assert _pregame().get_my_current_champion(session) == 266


def test_current_champion_zero_id_falls_through_to_pick_intent():
    """Pre-existing `or` semantics: a 0 championId defers to the intent."""
    session = _session(championId=0, championPickIntent=266)
    assert _pregame().get_my_current_champion(session) == 266


def test_current_champion_junk_string_does_not_raise():
    """Contract: unparseable -> 0, never an exception."""
    session = _session(championId="abc", championPickIntent=None)
    assert _pregame().get_my_current_champion(session) == 0


def test_current_champion_junk_string_falls_through_to_pick_intent():
    session = _session(championId="abc", championPickIntent=157)
    assert _pregame().get_my_current_champion(session) == 157


def test_current_champion_null_my_team_returns_zero():
    """`myTeam: null` is the same root cause one .get() away."""
    session = {"localPlayerCellId": 0, "myTeam": None}
    assert _pregame().get_my_current_champion(session) == 0


def test_current_champion_non_dict_team_entry_is_skipped():
    session = {"localPlayerCellId": 0, "myTeam": [42, {"cellId": 0, "championId": 103}]}
    assert _pregame().get_my_current_champion(session) == 103


# -- get_my_current_champion happy paths (pre-existing behavior) ---------------

def test_current_champion_happy_path_unchanged():
    session = _session(championId=103, championPickIntent=0)
    assert _pregame().get_my_current_champion(session) == 103


def test_current_champion_numeric_string_still_coerces():
    """`int("103")` worked before the fix; keep it working."""
    session = _session(championId="103")
    assert _pregame().get_my_current_champion(session) == 103


def test_current_champion_string_zero_falls_through_to_pick_intent():
    """DELIBERATE behavior change, pinned so it cannot drift back.

    The `or` fallthrough now runs on the COERCED value, not the raw one.
    Pre-fix, championId="0" was a truthy string so the intent was never
    consulted and the method returned 0 while an intent was sitting
    right there. Post-fix it coerces to 0 and falls through.
    """
    session = _session(championId="0", championPickIntent=266)
    assert _pregame().get_my_current_champion(session) == 266


def test_current_champion_float_string_coerces_to_zero_not_raise():
    """"3.9" raised ValueError pre-fix; the total contract makes it 0.

    Only INTEGER-formatted strings round-trip - see
    test_current_champion_numeric_string_still_coerces.
    """
    session = _session(championId="3.9", championPickIntent=None)
    assert _pregame().get_my_current_champion(session) == 0


def test_current_champion_no_matching_cell_returns_zero():
    session = {"localPlayerCellId": 9, "myTeam": [{"cellId": 0, "championId": 103}]}
    assert _pregame().get_my_current_champion(session) == 0


def test_current_champion_empty_session_returns_zero():
    assert _pregame().get_my_current_champion({}) == 0


# -- get_my_summoner_spells ----------------------------------------------------

def test_spells_both_null_returns_zero_pair():
    """The row's stated acceptance: null spell ids on the auto-push path."""
    session = _session(spell1Id=None, spell2Id=None)
    assert _pregame().get_my_summoner_spells(session) == (0, 0)


def test_spells_single_null_returns_zero_for_that_slot():
    """One null is enough to raise pre-fix; the other slot must survive."""
    session = _session(spell1Id=_FLASH, spell2Id=None)
    assert _pregame().get_my_summoner_spells(session) == (_FLASH, 0)


def test_spells_junk_string_does_not_raise():
    session = _session(spell1Id="abc", spell2Id=_SNOWBALL)
    assert _pregame().get_my_summoner_spells(session) == (0, _SNOWBALL)


def test_spells_null_my_team_returns_zero_pair():
    session = {"localPlayerCellId": 0, "myTeam": None}
    assert _pregame().get_my_summoner_spells(session) == (0, 0)


def test_spells_non_dict_team_entry_is_skipped():
    session = {
        "localPlayerCellId": 0,
        "myTeam": ["junk", {"cellId": 0, "spell1Id": _FLASH, "spell2Id": _SNOWBALL}],
    }
    assert _pregame().get_my_summoner_spells(session) == (_FLASH, _SNOWBALL)


def test_spells_happy_path_unchanged():
    session = _session(spell1Id=_FLASH, spell2Id=_SNOWBALL)
    assert _pregame().get_my_summoner_spells(session) == (_FLASH, _SNOWBALL)


def test_spells_numeric_string_still_coerces():
    session = _session(spell1Id="4", spell2Id="32")
    assert _pregame().get_my_summoner_spells(session) == (_FLASH, _SNOWBALL)


def test_spells_no_matching_cell_returns_zero_pair():
    session = {"localPlayerCellId": 9, "myTeam": [{"cellId": 0, "spell1Id": _FLASH}]}
    assert _pregame().get_my_summoner_spells(session) == (0, 0)


def test_spells_empty_session_returns_zero_pair():
    assert _pregame().get_my_summoner_spells({}) == (0, 0)


# -- get_bench_champion_ids ----------------------------------------------------

def test_bench_bare_int_elements_return_empty_list():
    """The row's stated acceptance: a non-dict element must not raise."""
    assert _pregame().get_bench_champion_ids({"benchChampions": [42]}) == []


def test_bench_mixed_elements_keeps_the_dict_ones():
    session = {"benchChampions": [42, {"championId": 103}, None, {"championId": 266}]}
    assert _pregame().get_bench_champion_ids(session) == [103, 266]


def test_bench_junk_string_id_is_skipped_not_raised():
    session = {"benchChampions": [{"championId": "abc"}, {"championId": 103}]}
    assert _pregame().get_bench_champion_ids(session) == [103]


def test_bench_null_id_still_filtered():
    """Pre-existing behavior - the trailing `if` already dropped these."""
    session = {"benchChampions": [{"championId": None}, {"championId": 103}]}
    assert _pregame().get_bench_champion_ids(session) == [103]


def test_bench_string_zero_id_is_dropped():
    """DELIBERATE behavior change, pinned so it cannot drift back.

    Filtering moved from pre-coercion raw truthiness to post-coercion
    int truthiness. Pre-fix, championId="0" passed the truthy-string
    guard and the method emitted a literal 0 into the id list - a bogus
    champion id a bench-swap caller would then act on. Now it is dropped.
    """
    session = {"benchChampions": [{"championId": "0"}, {"championId": 266}]}
    assert _pregame().get_bench_champion_ids(session) == [266]


def test_bench_order_is_preserved():
    session = {"benchChampions": [{"championId": 266}, {"championId": 103},
                                  {"championId": 42}]}
    assert _pregame().get_bench_champion_ids(session) == [266, 103, 42]


def test_bench_happy_path_unchanged():
    session = {"benchChampions": [{"championId": 103}, {"championId": 266}]}
    assert _pregame().get_bench_champion_ids(session) == [103, 266]


def test_bench_numeric_string_still_coerces():
    session = {"benchChampions": [{"championId": "103"}]}
    assert _pregame().get_bench_champion_ids(session) == [103]


def test_bench_null_bench_returns_empty_list():
    assert _pregame().get_bench_champion_ids({"benchChampions": None}) == []


def test_bench_absent_key_returns_empty_list():
    assert _pregame().get_bench_champion_ids({}) == []
