"""True-audit (lane 8, S144-T-743) pins for dashboard/routes_adaptive_summoners.py.

Each test names the defect it pins. A valid Flash-on-D base with a full
five-enemy roster gets the same recommendation as before; these cover the
partial-roster, Flash-on-F, malformed-input and loader-failure paths.
"""
from __future__ import annotations

import itertools
import json
import logging
import sqlite3
from unittest import mock

import pytest

import dashboard.routes_adaptive_summoners as ras

_CHAMPS = {
    "type": "champion",
    "data": {
        "Thresh": {"key": "412", "name": "Thresh"},
        "Leona": {"key": "89", "name": "Leona"},
        "Zed": {"key": "238", "name": "Zed"},
        "Ahri": {"key": "103", "name": "Ahri"},
        "Garen": {"key": "86", "name": "Garen"},
        "Jinx": {"key": "222", "name": "Jinx"},
    },
}


@pytest.fixture(autouse=True)
def _fresh_id_cache():
    """Every test starts with an unloaded id map and leaves none behind."""
    ras._ID_TO_NAME = None
    ras._ID_TO_NAME_RETRY_AT = 0.0
    yield
    ras._ID_TO_NAME = None
    ras._ID_TO_NAME_RETRY_AT = 0.0


class _StubHandler:
    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, code, body, ctype="application/json"):
        self.responses.append((code, body, ctype))

    @property
    def code(self) -> int:
        return self.responses[-1][0]

    @property
    def body(self) -> dict:
        return json.loads(self.responses[-1][1])


def _champ_file(tmp_path, payload: bytes):
    path = tmp_path / "ddragon_champions.json"
    path.write_bytes(payload)
    return path


# --- query parsing ---------------------------------------------------------

def test_parse_int_csv_keeps_only_plain_positive_ascii_ids_in_order():
    """int() accepted a sign, an underscore, zero, a negative and non-ASCII
    digits, so `base=-1,0` came back as the summoner pair [-1, 0] and
    `base=+4,1_1` as [4, 11]. Only plain ASCII digits, value > 0, survive;
    order and duplicates (One for All) are kept."""
    raw = "86, 64 ,abc,-3,0,+5,1_000,,7.0," + chr(0x665) + ",,99999999999,86"
    assert ras._parse_int_csv(raw) == [86, 64, 86]


def test_parse_int_csv_is_bounded():
    """An unbounded comma list was parsed, resolved and echoed whole."""
    raw = ",".join(str(i) for i in range(1, 500))
    assert len(ras._parse_int_csv(raw)) == ras._MAX_IDS


# --- CC score --------------------------------------------------------------

def test_one_locked_hard_cc_enemy_does_not_reach_the_cleanse_threshold():
    """The score was hits / locked-so-far, so ONE Thresh locked with the rest
    of the enemy team still picking scored 10/10 and swapped Heal to Cleanse,
    against the docstring's '>=2 hard-CC enemies are locked'."""
    assert ras._compute_cc_score(["Thresh"]) < ras._CC_SWAP_THRESHOLD


def test_two_locked_hard_cc_enemies_reach_the_cleanse_threshold():
    assert ras._compute_cc_score(["Thresh", "Leona"]) >= ras._CC_SWAP_THRESHOLD
    assert ras._compute_cc_score(
        ["Thresh", "Leona", "Zed", "Ahri", "Garen"]) == 4.0


def test_unresolved_slots_do_not_dilute_the_cc_score():
    """Unresolved ids came back as "" and counted in the denominator."""
    names = ["Thresh", "Leona", "Zed", "", "", "", "", ""]
    assert ras._compute_cc_score(names) == 4.0


# --- the recommendation ----------------------------------------------------

_CC = {"cc_threat": 8.0, "burst_threat": 0.0}
_BURST = {"cc_threat": 0.0, "burst_threat": 8.0}


def test_flash_on_f_is_never_swapped_away():
    """base=[Heal, Flash] (Flash keybound on F) put Flash in the 'secondary'
    slot, so a CC swap replaced FLASH with Cleanse - the docstring promises
    Flash always stays."""
    rec = ras._recommend([7, 4], "BOT", _CC)
    assert rec["summoners"] == [1, 4]
    assert rec["swap_from_id"] == 7
    assert rec["swap_to_id"] == 1


def test_swap_target_already_in_base_never_duplicates_a_spell():
    """base=[Barrier, Flash] under burst swapped Flash to Barrier and returned
    the pair [21, 21], which the client rejects."""
    rec = ras._recommend([21, 4], "MID", _BURST)
    assert rec["summoners"] == [21, 4]
    assert rec["swapped"] is False
    rec = ras._recommend([1, 7], "BOT", _CC)
    assert rec["summoners"] == [1, 7]
    assert rec["swapped"] is False


@pytest.mark.parametrize("base", [[7], [4, 4], [7, 7], [12], []])
def test_short_or_duplicate_base_never_yields_a_duplicate_pair(base):
    """base=[7] filled the missing slot with Heal -> [7, 7]; base=[4, 4]
    passed through as a duplicate pair."""
    rec = ras._recommend(base, "TOP", {})
    first, second = rec["summoners"]
    assert first != second
    assert 4 in rec["summoners"]


def test_non_numeric_threat_values_do_not_raise():
    """float('high') raised ValueError out of _recommend -> a 500 for a bad
    profile value; NaN / inf are not scores either."""
    for threat in ({"cc_threat": "high", "burst_threat": None},
                   {"cc_threat": float("nan"), "burst_threat": float("inf")},
                   {"cc_threat": True, "burst_threat": [9]},
                   {"cc_threat": 10 ** 400, "burst_threat": -(10 ** 400)}):
        rec = ras._recommend([4, 7], "BOT", threat)
        assert rec["summoners"] == [4, 7]
        assert rec["swapped"] is False


def test_recommendation_is_always_two_distinct_positive_ids():
    bases = [[], [4], [7], [4, 7], [7, 4], [21, 4], [4, 21], [1, 4], [4, 1],
             [4, 4], [6, 14], [14, 6], [12, 4], [4, 11], [11, 4]]
    roles = ["BOT", "MID", "TOP", "JUNGLE", "UTILITY", ""]
    threats = [{}, _CC, _BURST, {"cc_threat": 9, "burst_threat": 9}]
    for base, role, threat in itertools.product(bases, roles, threats):
        pair = ras._recommend(list(base), role, threat)["summoners"]
        assert len(pair) == 2 and pair[0] != pair[1], (base, role, threat)
        assert all(isinstance(x, int) and x > 0 for x in pair)
        if 4 in base:
            assert 4 in pair, (base, role, threat)


def test_valid_flash_on_d_base_is_unchanged():
    assert ras._recommend([4, 7], "BOT", _CC)["summoners"] == [4, 1]
    assert ras._recommend([4, 7], "MID", _BURST)["summoners"] == [4, 21]
    assert ras._recommend([4, 12], "TOP", _CC)["summoners"] == [4, 12]
    assert ras._recommend([4, 7], "BOT", {})["swapped"] is False


# --- the id -> name map ----------------------------------------------------

def test_id_map_reads_a_utf8_bom_file(tmp_path):
    """read_text(encoding='utf-8') kept the BOM, json.loads raised, and the
    map came back empty: every enemy resolved to "" and cc_threat read 0."""
    path = _champ_file(tmp_path, b"\xef\xbb\xbf" + json.dumps(_CHAMPS).encode())
    with mock.patch.object(ras, "_champions_path", return_value=path):
        assert ras._load_id_to_name()[412] == "Thresh"


def test_id_map_skips_malformed_entries(tmp_path):
    data = {"data": {
        "Ok": {"key": "412", "name": "Thresh"},
        "Bool": {"key": True, "name": "Cleanse"},
        "Neg": {"key": "-5", "name": "Neg"},
        "Word": {"key": "abc", "name": "Word"},
        "Blank": {"key": "77", "name": "  "},
        "NotText": {"key": "78", "name": ["x"]},
        "NotDict": "junk",
    }}
    path = _champ_file(tmp_path, json.dumps(data).encode())
    with mock.patch.object(ras, "_champions_path", return_value=path):
        assert ras._load_id_to_name() == {412: "Thresh"}


@pytest.mark.parametrize("payload", [b"[1, 2]", b'{"data": [1]}', b"null"])
def test_id_map_non_object_root_fails_soft(tmp_path, payload):
    path = _champ_file(tmp_path, payload)
    with mock.patch.object(ras, "_champions_path", return_value=path):
        assert ras._load_id_to_name() == {}


def test_failed_first_load_is_retried_not_pinned_forever(tmp_path):
    """A failed first read cached {} for the life of the process, so every
    later recommendation saw no enemy names until RC restarted."""
    path = tmp_path / "ddragon_champions.json"
    clock = [1000.0]
    with mock.patch.object(ras, "_champions_path", return_value=path), \
            mock.patch.object(ras, "_monotonic", side_effect=lambda: clock[0]):
        assert ras._load_id_to_name() == {}
        path.write_bytes(json.dumps(_CHAMPS).encode())
        clock[0] += 10.0
        assert ras._load_id_to_name() == {}       # inside the retry window
        clock[0] += ras._EMPTY_RETRY_S
        assert ras._load_id_to_name()[412] == "Thresh"
        path.unlink()
        clock[0] += 10 * ras._EMPTY_RETRY_S
        assert ras._load_id_to_name()[412] == "Thresh"   # good map cached


# --- threat profile --------------------------------------------------------

def test_threat_profile_failure_is_logged_not_silent(caplog):
    """`except Exception: profile = {}` swallowed the failure with no log."""
    with mock.patch("core.defensive_picks.compute_threat_profile",
                    side_effect=RuntimeError("boom")), \
            caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        out = ras._compute_threat(["Thresh"])
    assert out["cc_threat"] == 2.0
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


def test_threat_profile_non_dict_return_does_not_raise():
    """A non-dict profile raised TypeError on the cc_threat assignment."""
    with mock.patch("core.defensive_picks.compute_threat_profile",
                    return_value=["not", "a", "dict"]):
        out = ras._compute_threat(["Thresh"])
    assert out == {"cc_threat": 2.0}


def test_threat_profile_returned_dict_is_not_mutated():
    shared = {"burst_threat": 3.0}
    with mock.patch("core.defensive_picks.compute_threat_profile",
                    return_value=shared):
        out = ras._compute_threat(["Thresh"])
    assert shared == {"burst_threat": 3.0}
    assert out == {"burst_threat": 3.0, "cc_threat": 2.0}


# --- spell win rates -------------------------------------------------------

def _make_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sr_player_stats (champion_name TEXT, "
                 "spell1_id INT, spell2_id INT, team_result TEXT)")
    conn.executemany("INSERT INTO sr_player_stats VALUES (?, ?, ?, ?)", [
        ("Jinx", 4, 7, "WIN"), ("Jinx", 7, 4, "LOSS"), ("Jinx", 4, 21, "WIN"),
    ])
    conn.commit()
    conn.close()


def test_spell_winrates_opens_a_db_whose_path_holds_uri_characters(tmp_path):
    """The read-only open built `file:{path}?mode=ro` by hand: a '#' in the
    path started a URI fragment and a '%41' was percent-decoded, so a
    different file was opened and the route answered 200 with no pairs
    (measured before the fix: best None)."""
    db = tmp_path / "a#b%41c" / "postgame_stats.db"
    _make_db(db)
    h = _StubHandler("/api/champ-select/spell-winrates?champion=Jinx")
    with mock.patch.object(ras, "_postgame_db_path", return_value=db):
        ras._serve_spell_winrates(h)
    assert h.code == 200, h.responses
    assert h.body["best"] == [4, 21]
    assert [p["n"] for p in h.body["pairs"]] == [1, 2]


def test_spell_winrates_db_open_is_read_only(tmp_path):
    db = tmp_path / "postgame_stats.db"
    _make_db(db)
    conn = sqlite3.connect(ras._postgame_db_uri(db), uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM sr_player_stats")
    finally:
        conn.close()


def test_spell_winrates_missing_table_is_empty_but_a_bug_surfaces():
    """`except Exception` turned a programming error into a silent []."""
    conn = sqlite3.connect(":memory:")
    try:
        assert ras.compute_champ_spell_winrates(conn, "Jinx", "SR") == []
    finally:
        conn.close()
    broken = mock.Mock()
    broken.execute.side_effect = RuntimeError("bug")
    with pytest.raises(RuntimeError):
        ras.compute_champ_spell_winrates(broken, "Jinx", "SR")


# --- the adaptive route ----------------------------------------------------

def test_route_echoes_the_sanitised_base_and_a_distinct_pair(tmp_path):
    path = _champ_file(tmp_path, json.dumps(_CHAMPS).encode())
    h = _StubHandler("/api/champ-select/adaptive-summoners?champion=Jinx"
                     "&role=bot&enemy_ids=412,89,0,-1,abc&base=7,-1,4,21")
    with mock.patch.object(ras, "_champions_path", return_value=path):
        ras._serve_adaptive_summoners(h)
    body = h.body
    assert h.code == 200
    assert body["base"] == [7, 4]
    assert body["enemy_count"] == 2
    assert body["enemy_names"] == ["Thresh", "Leona"]
    assert body["summoners"] == [1, 4]
    assert body["swap_to"] == "Cleanse"


def test_route_failure_logs_the_exception_type_not_its_text(caplog):
    """The catch-all logged str(exc), so request-derived or secret text in an
    exception message reached logs/; only the type is logged now."""
    h = _StubHandler("/api/champ-select/adaptive-summoners?champion=Jinx")
    with mock.patch.object(ras, "_resolve_enemy_names",
                           side_effect=RuntimeError("SECRET-TEXT")), \
            caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        ras._serve_adaptive_summoners(h)
    assert h.code == 500
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in messages
    assert "SECRET-TEXT" not in messages
