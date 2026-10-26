"""s134 true-audit: tft/local_player.py junk input, id kinds and the alive rule.

The module's header promises "Pure and fail-soft (junk in -> (None, reason))",
and every live TFT surface calls it with bytes RC did not write: the standalone
client's per-round TFTEoGStats.json (tft/tft_standalone.py synth path), the
gameclient EoG block (tft/tft_placement.py), the scouting round file and the
LCU snapshot. Measured before the fix (s134t008):

- L1: ``real_id`` raised ValueError on a non-ASCII digit string ("\\u00b2"
  passes str.isdigit() but int() refuses it) and on a digit string past
  Python's 4300-digit int-conversion limit. It ran under
  ``local_player_index`` and ``summoner_id_of``, so one junk ``playerId`` or
  ``summoner_id`` raised out of the selector instead of (None, reason).
- L2: ``_num`` raised OverflowError on a JSON integer too large for a float
  (``health`` or ``ffaStanding``), out of ``player_status`` / ``count_alive``
  / ``lobby_counts``.
- L3: rule 1 fell to rule 2 only when the file carried NO id at all. A
  summoner-id-only LCU (the live source and the final board pass only that)
  against a file whose entries carry only PUUIDs cannot be compared either -
  the header's own reason for the fallback - yet it returned "matches no
  entry" and dropped the single-flag bot-lobby answer.
- L4: ``lobby_counts`` took ``True`` as list position 1 (bool is an int).
- L5: ``player_status`` truncated a fractional health toward 0, so a scored
  entry on 0.5 HP read ELIMINATED.
"""
from __future__ import annotations

import pytest

from tft import local_player as lp

LOCAL_SID = 900004


def _row(i, *, pid=True, puuid=True, flagged=False, health=50, standing=-1):
    p = {"isInteractable": flagged, "health": health, "ffaStanding": standing}
    if pid:
        p["playerId"] = 900000 + i
    if puuid:
        p["PUUID"] = f"00000000-0000-4000-8000-00000000000{i}"
    return p


# -- L1: real_id is fail-soft on every string ----------------------------------------

# Source stays ASCII: the junk digits are built with chr().
SUP2, SUP3 = chr(0xB2), chr(0xB3)
ARABIC_12 = chr(0x661) + chr(0x662)


@pytest.mark.parametrize("junk", [SUP2, "1" + SUP2, ARABIC_12, "1" * 5000,
                                  "9" * 4301, " " + SUP3 + " "],
                         ids=["superscript", "digit-superscript", "arabic-indic",
                              "5000-digits", "4301-digits", "padded-superscript"])
def test_real_id_never_raises_on_junk_digit_strings(junk):
    assert lp.real_id(junk) == 0


def test_real_id_still_reads_ascii_digit_strings():
    assert lp.real_id("900004") == 900004
    assert lp.real_id(" 900004 ") == 900004
    assert lp.real_id("0") == 0
    assert lp.real_id(900004.0) == 900004
    assert lp.real_id(True) == 0


def test_selector_fail_soft_on_a_junk_entry_id_and_a_junk_lcu_id():
    rows = [_row(1), _row(2)]
    rows[0]["playerId"] = SUP2
    assert lp.local_player_index(rows, summoner_id=900002) == (1, lp.BASIS_SUMMONER_ID)
    idx, why = lp.local_player_index([_row(1)], summoner_id="1" * 5000)
    assert idx is None and isinstance(why, str)
    assert lp.summoner_id_of({"summoner_id": SUP2}) is None


# -- L2: the alive rule is fail-soft on huge numbers ---------------------------------

def test_player_status_never_raises_on_a_huge_json_int():
    assert lp.player_status({"health": 10 ** 400, "ffaStanding": 1}) is None
    assert lp.player_status({"health": 5, "ffaStanding": 10 ** 400}) == lp.ALIVE
    assert lp.player_status({"health": -3, "ffaStanding": 10 ** 400}) is None


def test_counts_never_raise_on_a_huge_json_int():
    rows = [_row(1, health=10 ** 400, standing=1), _row(2, health=40, standing=2)]
    assert lp.count_alive(rows) is None
    assert lp.lobby_counts(rows, 1) == {
        "players_alive": None, "alive_others": None, "dead_others": None}


# -- L3: an id of a kind the file does not carry cannot be compared --------------------

def test_summoner_id_only_vs_puuid_only_file_falls_to_the_single_flag():
    rows = [_row(i, pid=False, flagged=(i == 2)) for i in range(1, 5)]
    assert lp.local_player_index(rows, summoner_id=LOCAL_SID) == (1, lp.BASIS_INTERACTABLE)


def test_puuid_only_vs_player_id_only_file_falls_to_the_single_flag():
    rows = [_row(i, puuid=False, flagged=(i == 3)) for i in range(1, 5)]
    me = "00000000-0000-4000-8000-0000000000ff"
    assert lp.local_player_index(rows, puuid=me) == (2, lp.BASIS_INTERACTABLE)


def test_a_comparable_id_that_matches_nobody_is_still_unknown():
    # the file carries playerIds and the LCU names none of them: never the flag
    rows = [_row(i, puuid=False, flagged=(i == 3)) for i in range(1, 5)]
    idx, why = lp.local_player_index(rows, summoner_id=LOCAL_SID + 99)
    assert idx is None and "matches no entry" in why
    # either kind comparable is enough: a puuid that matches nobody in a file
    # that carries puuids stays unknown even though playerIds are absent
    rows = [_row(i, pid=False, flagged=(i == 3)) for i in range(1, 5)]
    idx, why = lp.local_player_index(rows, summoner_id=LOCAL_SID,
                                     puuid="00000000-0000-4000-8000-0000000000ff")
    assert idx is None and "matches no entry" in why


def test_incomparable_ids_never_take_a_flag_on_an_id_less_entry():
    # verifier s134t008: only entry 0 carries a (PUUID) id, the others are
    # zeroed, and a DIFFERENT entry is flagged - the flag is contradicted
    rows = [_row(1, pid=False)] + [_row(i, pid=False, puuid=False, flagged=(i == 5))
                                   for i in range(2, 9)]
    idx, why = lp.local_player_index(rows, summoner_id=LOCAL_SID)
    assert idx is None and "carries no id" in why
    # the flag on the one id carrier is still taken
    rows[0]["isInteractable"], rows[4]["isInteractable"] = True, False
    assert lp.local_player_index(rows, summoner_id=LOCAL_SID) == (0, lp.BASIS_INTERACTABLE)


def test_incomparable_ids_in_an_all_flagged_lobby_stay_unknown():
    rows = [_row(i, pid=False, flagged=True) for i in range(1, 9)]
    idx, why = lp.local_player_index(rows, summoner_id=LOCAL_SID)
    assert idx is None and "8 entries" in why


# -- L4: a bool is not a list position --------------------------------------------------

def test_lobby_counts_ignores_a_bool_local_index():
    rows = [_row(1, health=5, standing=1), _row(2, health=0, standing=2)]
    lobby_wide = {"players_alive": 1, "alive_others": 0, "dead_others": 1}
    assert lp.lobby_counts(rows, None) == lobby_wide
    assert lp.lobby_counts(rows, True) == lobby_wide
    assert lp.lobby_counts(rows, 1) == {
        "players_alive": 1, "alive_others": 1, "dead_others": 0}


# -- L5: fractional health is compared, not truncated ------------------------------------

@pytest.mark.parametrize("hp", [0.5, "0.5", 0.01])
def test_fractional_positive_health_is_alive(hp):
    assert lp.player_status({"health": hp, "ffaStanding": 3}) == lp.ALIVE


def test_fractional_standing_below_one_is_not_scored():
    assert lp.player_status({"health": 0, "ffaStanding": 0.5}) is None
    assert lp.player_status({"health": -0.5, "ffaStanding": 2}) == lp.ELIMINATED
