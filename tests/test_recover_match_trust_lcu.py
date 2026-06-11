"""Item 211 carry: --trust-lcu / --match-id recovery for off-by-one
misattribution chain rows (db.champion wrong, lcu champion right).

Pure-logic tests - no network, no DB, no live dashboard.
API surface confirmed: tools/recover_match_via_match_v5.py main() filters
candidates via info.participants[].puuid/.championName (lines 158-163).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.recover_match_via_match_v5 import (
    build_parser,
    find_by_champion,
    verify_participant,
)


def _detail(champ, puuid="P1", game_id=123):
    return {
        "info": {
            "gameId": game_id,
            "participants": [
                {"participantId": 1, "puuid": puuid, "championName": champ},
                {"participantId": 2, "puuid": "OTHER", "championName": "Lux"},
            ],
        }
    }


# --- find_by_champion ---

def test_find_by_champion_matches_db_champ():
    details = {"NA1_1": _detail("Ashe"), "NA1_2": _detail("Jinx")}
    got = find_by_champion(["NA1_1", "NA1_2"], "P1", "Jinx", details.get)
    assert got is not None
    assert got[0] == "NA1_2"


def test_find_by_champion_refuses_chain_row_wrong_db_champ():
    # Chain row: db.champion says Ashe, but the real game was Jinx.
    details = {"NA1_2": _detail("Jinx")}
    assert find_by_champion(["NA1_2"], "P1", "Ashe", details.get) is None


def test_find_by_champion_trust_lcu_override_recovers_chain_row():
    # --trust-lcu supplies the LCU-truth champion (next row's db_champ).
    details = {"NA1_2": _detail("Jinx")}
    got = find_by_champion(["NA1_2"], "P1", "Jinx", details.get)
    assert got is not None and got[0] == "NA1_2"


def test_find_by_champion_case_insensitive():
    details = {"NA1_1": _detail("KaiSa")}
    got = find_by_champion(["NA1_1"], "P1", "kaisa", details.get)
    assert got is not None


def test_find_by_champion_skips_unfetchable_detail():
    details = {"NA1_1": None, "NA1_2": _detail("Jinx")}
    got = find_by_champion(["NA1_1", "NA1_2"], "P1", "Jinx", details.get)
    assert got is not None and got[0] == "NA1_2"


# --- verify_participant (explicit --match-id path) ---

def test_verify_participant_returns_champion_name():
    assert verify_participant(_detail("Jinx"), "P1") == "Jinx"


def test_verify_participant_none_when_puuid_absent():
    assert verify_participant(_detail("Jinx", puuid="SOMEONE"), "P1") is None


# --- build_parser flags ---

def test_parser_trust_lcu_and_match_id_flags():
    p = build_parser()
    a = p.parse_args(["--row-id", "1640", "--riot-name", "x", "--riot-tag",
                      "y", "--trust-lcu", "Jinx", "--match-id", "NA1_55"])
    assert a.trust_lcu == "Jinx"
    assert a.match_id == "NA1_55"


def test_parser_defaults_keep_legacy_behavior():
    p = build_parser()
    a = p.parse_args(["--row-id", "1", "--riot-name", "x", "--riot-tag", "y"])
    assert a.trust_lcu is None
    assert a.match_id is None
