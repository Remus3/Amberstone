"""RM-616 - TFT placement + final boards from LCU post-game data.

GROUND TRUTH. Two sanitised fixtures of the SAME game (s134 TFT Set 18
normal, queue 1090, placement 1 at 100 HP):

  tests/fixtures/tft_eog_stats_set18.json
      GET /lol-end-of-game/v1/tft-eog-stats, captured in PreEndOfGame by the
      s134 post-match QA recorder.
  tests/fixtures/tft_match_history_set18.json
      GET /lol-match-history/v1/products/tft/{puuid}/matches?begin=0&count=1,
      measured passively in Lobby the same day (the EOG route 404s there).

Shape traps pinned here (QA_REPORT.md section 4 and LCU_TFT_INVENTORY.md
section 2, both gitignored under ops/runtime/tft_qa/), cited by fixture line:

  - EOG placement is `ffaStanding` (eog :298 localPlayer, :609 players[0]);
    there is no `placement` key. History: `placement` (hist :30).
  - EOG `setCoreName` is "" on localPlayer (eog :313) but "TFTSet18" on the
    players[] entry whose isLocalPlayer is true (eog :613, :624).
  - EOG `items[].id` is 0 for every item: items are keyed by `nameId`.
  - EOG `health` is HP for the local player only (eog :299 = 100); the other
    players read 247 / 247 / 238 / 239 / 253 / 0 / 252 (eog :851 .. :2108).
  - `augments` is [] for all eight EOG players (eog :12, :323 ...) and the
    history participant has no `augments` key at all.
  - non-local players carry riot ids in both documents (placeholders
    `playerN` / `TAG` here); history zeroes non-local puuids (hist :248) and
    keeps the local one (hist :32). Nothing identifying may be stored.
  - EOG unit `traits[]` omit emblem-granted traits. The QA HUD read at 6-1
    (QA_REPORT.md section 5) was Flora Fatalis 2, Spellweaver 3, Blossom 3,
    Lunar 2, Juggernaut 2, Vanguard 2, Bounty Seeker 1, Emerald Aspect 1 -
    the same eight traits the history route marks tier_current > 0.
  - history unit `name` is "" and `rarity` + 1 is the cost (Draven 5 =
    rarity 4, Aphelios 4 = rarity 3, Diana 3 = rarity 2).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tft import tft_placement as tp

FIX = Path(__file__).resolve().parent / "fixtures"
EOG_FIXTURE = FIX / "tft_eog_stats_set18.json"
HIST_FIXTURE = FIX / "tft_match_history_set18.json"
LOCAL_PUUID = "11111111-1111-1111-1111-111111111111"   # hist :32 placeholder

# The QA HUD active-trait read at 6-1 (QA_REPORT.md section 5).
HUD_ACTIVE = {"Flora Fatalis": 2, "Bounty Seeker": 1, "Emerald Aspect": 1,
              "Spellweaver": 3, "Blossom": 3, "Lunar": 2, "Juggernaut": 2,
              "Vanguard": 2}

# LCU player keys that identify a person. None may reach a stored record.
_IDENTITY_KEYS = ("puuid", "summonerId", "riotIdGameName", "riotIdTagLine",
                  "riotIdTagline", "summonerName", "iconId", "companion",
                  "active_puuid", "matchId", "match_id")


def _eog() -> dict:
    return json.loads(EOG_FIXTURE.read_text(encoding="utf-8"))


def _hist() -> dict:
    return json.loads(HIST_FIXTURE.read_text(encoding="utf-8"))


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def _assert_anonymous(rec) -> None:
    keys = set(_walk_keys(rec))
    for k in _IDENTITY_KEYS:
        assert k not in keys, k
    blob = json.dumps(rec)
    for i in range(8):
        assert f"player{i}" not in blob
    assert "-0000-0000-0000-" not in blob and LOCAL_PUUID not in blob
    assert "TAG" not in blob


# -- Fixture sanitisation (the repo is PUBLIC) ---------------------------------

@pytest.mark.parametrize("path", [EOG_FIXTURE, HIST_FIXTURE])
def test_fixture_bytes_are_ascii_lf(path):
    raw = path.read_bytes()
    assert all(b < 128 for b in raw), "fixture must stay 7-bit ASCII"
    assert b"\r\n" not in raw, "fixture must stay LF-only"


def test_eog_fixture_carries_only_placeholder_identities():
    d = _eog()
    for p in [d["localPlayer"]] + d["players"]:
        assert p["puuid"].startswith("00000000-0000-0000-0000-"), p["puuid"]
        assert p["summonerId"] == 0
        assert p["riotIdGameName"].startswith("player")
        assert p["riotIdTagLine"] == "TAG"
        assert p["summonerName"] == p["riotIdGameName"]
        assert p["iconId"] == 0
        assert p["companion"] == {"colorName": "", "icon": "", "speciesName": ""}
    assert d["gameId"] == 1000000001


def test_history_fixture_carries_only_placeholder_identities():
    d = _hist()
    assert d["active_puuid"] == ""
    g = d["games"][0]
    assert g["metadata"]["participants"] == [LOCAL_PUUID]
    assert g["metadata"]["match_id"] == "XX1_1000000001"
    assert g["json"]["game_id"] == g["json"]["gameId"] == 1000000001
    assert g["json"]["gameCreation"] == 1700000000000
    for p in g["json"]["participants"]:
        assert p["puuid"] in (LOCAL_PUUID, "00000000-0000-0000-0000-000000000000")
        assert p["riotIdGameName"] == f"player{p['placement'] - 1}"
        assert p["riotIdTagline"] == "TAG"
        assert p["companion"] == {"content_ID": "", "item_ID": 0,
                                  "skin_ID": 0, "species": ""}


# -- parse_eog -----------------------------------------------------------------

def test_eog_header():
    rec = tp.parse_eog(_eog(), now=1_800_000_000.0)
    assert rec["schema"] == tp.SCHEMA_VERSION
    assert rec["source"] == tp.SOURCE_EOG
    assert rec["game_id"] == 1000000001          # eog :8
    assert rec["game_length_s"] == 2097          # eog :9
    assert rec["queue_id"] == 1090               # eog :2127
    assert rec["queue_type"] == "NORMAL_TFT"
    assert rec["is_ranked"] is False             # eog :10
    assert rec["captured_at_unix"] == 1_800_000_000.0
    assert len(rec["captured_at"]) == 19         # "YYYY-MM-DD HH:MM:SS"
    assert rec["ended_at"] is None               # EOG carries no clock


def test_eog_set_core_name_from_the_local_players_entry():
    d = _eog()
    assert d["localPlayer"]["setCoreName"] == ""  # the trap (eog :313)
    assert tp.parse_eog(d)["set_core_name"] == "TFTSet18"   # eog :624


def test_eog_local_placement_and_hp():
    rec = tp.parse_eog(_eog())
    assert rec["local_placement"] == 1            # eog :298 / :609
    assert rec["local_hp"] == 100                 # eog :299
    assert rec["lobby_size"] == 8


def test_eog_all_eight_players_sorted_with_one_local():
    rec = tp.parse_eog(_eog())
    assert [p["placement"] for p in rec["players"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [p["is_local"] for p in rec["players"]] == [True] + [False] * 7
    assert [len(p["board"]) for p in rec["players"]] == [9, 6, 6, 6, 6, 6, 6, 5]
    for p in rec["players"]:
        assert "health" not in p and "hp" not in p


def test_eog_local_board_items_keyed_by_name_id():
    rec = tp.parse_eog(_eog())
    draven = rec["players"][0]["board"][0]
    assert draven["character_id"] == "DA_Draven18"
    assert draven["name"] == "Draven"
    assert draven["star"] == 2                    # boardPieces[0].level
    assert draven["cost"] == 5                    # boardPieces[0].price
    assert [i["name_id"] for i in draven["items"]] == [
        "DA_ThiefsGloves", "DA_SteraksGage", "DA_KrakensFury"]
    assert [i["name"] for i in draven["items"]] == [
        "Thief's Gloves", "Sterak's Gage", "Kraken's Fury"]
    for p in rec["players"]:
        for u in p["board"]:
            for it in u["items"]:
                assert set(it) == {"name_id", "name"} and it["name_id"]


def test_eog_trait_counts_match_the_hud_including_emblems():
    traits = tp.parse_eog(_eog())["players"][0]["traits"]
    counts = {t["name"]: t["units"] for t in traits}
    for name, n in HUD_ACTIVE.items():
        assert counts.get(name) == n, (name, counts.get(name))
    assert counts.get("Defender") == 1            # on the board, inactive
    ns = [t["units"] for t in traits]
    assert ns == sorted(ns, reverse=True)


def test_eog_augments_empty_and_flagged_unrecorded():
    rec = tp.parse_eog(_eog())
    assert all(p["augments"] == [] for p in rec["players"])
    assert rec["augments_recorded"] is False


def test_eog_record_is_anonymous():
    _assert_anonymous(tp.parse_eog(_eog()))


@pytest.mark.parametrize("bad", [
    None, [], "x", {}, {"gameId": 0, "players": []},
    {"gameId": 5, "players": "no"},
    {"gameId": 5, "teams": [{"players": []}], "gameMode": "CLASSIC"},
    {"gameId": True, "players": [{"ffaStanding": 1, "boardPieces": []}]},
])
def test_eog_rejects_non_tft_documents(bad):
    assert tp.parse_eog(bad) is None


def test_eog_tolerates_junk_members_and_bad_placements():
    d = _eog()
    d["players"] = d["players"][:2] + ["junk", 7, None]
    d["players"][0]["boardPieces"] = d["players"][0]["boardPieces"][:1] + ["x"]
    d["players"][0]["boardPieces"][0]["items"] = ["y", {"name": "No Id"}]
    d["players"][1]["ffaStanding"] = d["players"][1]["rank"] = 99
    rec = tp.parse_eog(d)
    assert [p["placement"] for p in rec["players"]] == [1, None]
    assert len(rec["players"][0]["board"]) == 1
    assert rec["players"][0]["board"][0]["items"] == []


# -- parse_history (measured shape) --------------------------------------------

def test_history_header_and_local_player():
    recs = tp.parse_history(_hist(), LOCAL_PUUID, now=5.0)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["source"] == tp.SOURCE_HISTORY
    assert rec["game_id"] == 1000000001           # hist :11
    assert rec["game_length_s"] == 2097           # hist :12
    assert rec["queue_id"] == 1090                # hist :1367
    assert rec["set_core_name"] == "TFTSet18"     # hist :1369
    assert rec["set_number"] == 18
    assert rec["ended_at_unix"] == 1700002099.924  # hist :10 game_datetime ms
    assert rec["local_placement"] == 1
    assert rec["local_hp"] is None
    me = rec["players"][0]
    assert me["is_local"] is True
    assert (me["level"], me["gold_left"], me["last_round"]) == (9, 32, 33)  # hist :24-26
    assert me["time_eliminated_s"] == 2096        # hist :35
    assert [p["level"] for p in rec["players"]] == [9, 6, 6, 6, 6, 6, 6, 5]
    assert [p["last_round"] for p in rec["players"]] == [33, 33, 33, 31, 30, 27, 24, 21]


def test_history_units_cost_from_rarity_and_items_by_name_id():
    me = tp.parse_history(_hist(), LOCAL_PUUID)[0]["players"][0]
    by_id = {u["character_id"]: u for u in me["board"]}
    assert len(by_id) == 9
    assert by_id["DA_Draven18"]["cost"] == 5
    assert by_id["DA_18_Aphelios"]["cost"] == 4
    assert by_id["DA_18_Diana"]["cost"] == 3
    assert by_id["DA_18_Yorick"]["name"] == "Yorick"      # name "" on the route
    assert [i["name_id"] for i in by_id["DA_Draven18"]["items"]] == [
        "DA_ThiefsGloves", "DA_SteraksGage", "DA_KrakensFury"]


def test_history_active_tiers_are_the_hud_traits():
    rec = tp.merge(None, tp.parse_history(_hist(), LOCAL_PUUID)[0])
    active = {t["name"]: t["units"] for t in rec["players"][0]["traits"] if t["active"]}
    assert set(active) == {"Flora Fatalis", "Draven Unique Trait", "Emerald",
                           "Spellweaver", "Blossom", "Lunar", "Juggernaut",
                           "Vanguard"}
    assert active["Flora Fatalis"] == 2 and active["Spellweaver"] == 3


def test_history_record_is_anonymous():
    _assert_anonymous(tp.parse_history(_hist(), LOCAL_PUUID)[0])


def test_history_without_the_local_puuid_has_no_local_player():
    rec = tp.parse_history(_hist(), "")[0]
    assert rec["local_placement"] is None
    assert not any(p["is_local"] for p in rec["players"])


@pytest.mark.parametrize("bad", [None, {}, {"games": "x"}, {"games": [None, {}]},
                                 {"games": [{"json": {"game_id": 0,
                                                      "participants": []}}]}])
def test_history_rejects_junk(bad):
    assert tp.parse_history(bad, LOCAL_PUUID) == []


def test_history_path_quotes_the_puuid_and_bounds_count():
    assert tp.history_path("a/b", 999).endswith("/products/tft/a%2Fb/matches?begin=0&count=20")
    assert tp.history_path("x", 0).endswith("count=1")


# -- merge: EOG fast path + history durable path of the same game ---------------

def test_merge_combines_both_sources():
    eog = tp.parse_eog(_eog(), now=1_700_002_200.0)
    hist = tp.parse_history(_hist(), LOCAL_PUUID, now=1_700_003_000.0)[0]
    rec = tp.merge(eog, hist)
    assert rec["sources"] == ["eog", "history"]
    assert rec["local_hp"] == 100                 # EOG only
    assert rec["set_number"] == 18                # history only
    assert rec["ended_at_unix"] == 1700002099.924
    assert rec["ended_at_effective_unix"] == 1700002099.924
    me = rec["players"][0]
    assert me["board"][0]["name"] == "Draven"     # EOG board (display names)
    assert me["level"] == 9 and me["gold_left"] == 32
    names = {t["name"]: t for t in me["traits"]}
    # history tiers, EOG display names through the shared trait id
    assert names["Bounty Seeker"]["active"] is True
    assert names["Bounty Seeker"]["id"] == "DA_DravenUniqueTrait18"
    assert names["Defender"]["active"] is False
    assert {n for n, t in names.items() if t["active"]} == set(HUD_ACTIVE)
    # inputs are not mutated
    assert "active" not in eog["players"][0]["traits"][0]
    _assert_anonymous(rec)


def test_merge_eog_only_has_unknown_activity():
    rec = tp.merge(tp.parse_eog(_eog(), now=10.0), None)
    assert rec["sources"] == ["eog"]
    assert all(t["active"] is None for t in rec["players"][0]["traits"])
    assert rec["ended_at_effective_unix"] == 10.0
    assert tp.merge(None, None) is None


# -- session freshness ---------------------------------------------------------

def test_session_helpers():
    s = {"phase": "PreEndOfGame",
         "gameData": {"gameId": 1000000001,
                      "queue": {"id": 1090, "gameMode": "TFT"}},
         "map": {"gameMode": "TFT"}}
    assert tp.session_game_id(s) == 1000000001
    assert tp.session_is_tft(s) is True
    assert tp.session_is_tft({"gameData": {"queue": {"gameMode": "CLASSIC"}},
                              "map": {"gameMode": "CLASSIC"}}) is False
    assert tp.session_is_tft({"map": {"gameMode": "TFT"}}) is True
    # No mode string: the shared queue table decides (core/queue_modes.py 1090).
    assert tp.session_is_tft({"gameData": {"queue": {"id": 1090}}}) is True
    assert tp.session_is_tft({"gameData": {"queue": {"id": 420}}}) is False
    for junk in (None, [], {}, {"gameData": "x"}, {"gameData": {"gameId": "a"}}):
        assert tp.session_game_id(junk) is None
        assert tp.session_is_tft(junk) is False


# -- the store: append-only, atomic, joinable on game_id -----------------------

def test_persist_is_append_only_per_source(tmp_path):
    eog = tp.parse_eog(_eog())
    assert tp.persist(eog, store_dir=tmp_path) is True
    path = tmp_path / "1000000001.eog.json"
    first = path.read_bytes()
    assert tp.persist(dict(eog, local_placement=8), store_dir=tmp_path) is False
    assert path.read_bytes() == first, "an existing record is never overwritten"
    hist = tp.parse_history(_hist(), LOCAL_PUUID)[0]
    assert tp.persist(hist, store_dir=tmp_path) is True
    assert sorted(os.listdir(tmp_path)) == ["1000000001.eog.json",
                                            "1000000001.history.json"], "no tmp left"
    assert tp.has_record(1000000001, store_dir=tmp_path) is True
    assert tp.has_record(1000000001, tp.SOURCE_HISTORY, store_dir=tmp_path) is True
    assert tp.has_record(5, store_dir=tmp_path) is False
    rec = tp.load(1000000001, store_dir=tmp_path)
    assert rec["sources"] == ["eog", "history"] and rec["local_placement"] == 1
    assert tp.load(5, store_dir=tmp_path) is None
    _assert_anonymous(json.loads(first))


def test_persist_refuses_junk(tmp_path):
    for bad in (None, {"game_id": 0, "source": "eog"}, {"game_id": 5},
                {"game_id": "../x", "source": "eog"},
                {"game_id": 5, "source": "other"}):
        assert tp.persist(bad, store_dir=tmp_path) is False
    assert os.listdir(tmp_path) == []


def test_latest_orders_by_end_time_and_skips_junk(tmp_path):
    old_hist = dict(tp.parse_history(_hist(), LOCAL_PUUID)[0], game_id=1000000002)
    new_eog = tp.parse_eog(_eog(), now=1_800_000_000.0)       # later wall clock
    tp.persist(new_eog, store_dir=tmp_path)
    tp.persist(old_hist, store_dir=tmp_path)
    (tmp_path / "1000000003.eog.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert tp.latest(store_dir=tmp_path)["game_id"] == 1000000001
    assert tp.latest(store_dir=tmp_path / "missing") is None


def test_store_marker_changes_when_a_record_lands(tmp_path):
    store = tmp_path / "s"
    before = tp.store_marker(store_dir=store)
    tp.persist(tp.parse_eog(_eog()), store_dir=store)
    assert tp.store_marker(store_dir=store) != before


def test_default_store_is_a_gitignored_data_dir():
    assert tp.DEFAULT_STORE_REL == "data/tft_matches"
    gi = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
        encoding="utf-8").splitlines()
    assert "data/tft_matches/" in gi


def test_scrub_raw_drops_every_identity_and_keeps_the_boards():
    for doc in (_eog(), _hist()):
        out = tp.scrub_raw(doc)
        assert not set(_walk_keys(out)) & set(tp.IDENTITY_KEYS)
        blob = json.dumps(out)
        assert "player1" not in blob and LOCAL_PUUID not in blob
        assert "DA_Draven18" in blob
    hist = tp.scrub_raw(_hist())
    assert "participants" not in hist["games"][0]["metadata"]
    assert len(hist["games"][0]["json"]["participants"]) == 8
    raw = _eog()
    tp.scrub_raw(raw)
    assert raw["players"][0]["puuid"], "the input is not mutated"


# -- N4: the gameclient EOG block (same document as TFTEoGStats.json) ----------

def _block():
    from tests.test_postgame_tft_capture_rm616 import gameclient_block
    return gameclient_block()


def test_gameclient_block_parses_with_the_interactable_player_as_local():
    rec = tp.parse_gameclient_eog(_block(), now=7.0)
    assert rec["source"] == tp.SOURCE_EOG
    assert rec["source_route"] == tp.GAMECLIENT_EOG_PATH
    assert rec["game_id"] == 1000000001
    assert rec["game_length_s"] == 2050
    assert rec["set_core_name"] == "TFTSet18" and rec["queue_id"] == 1090
    assert rec["local_placement"] == 1 and rec["local_hp"] == 96
    assert [p["placement"] for p in rec["players"]] == [1, 2]
    assert [p["is_local"] for p in rec["players"]] == [True, False]
    draven = rec["players"][0]["board"][0]
    assert (draven["character_id"], draven["name"], draven["star"], draven["cost"]) == (
        "DA_Draven18", "Draven", 2, 5)
    assert [i["name_id"] for i in draven["items"]] == [
        "DA_ThiefsGloves", "DA_18_EmblemFloraFatalis"]
    assert draven["items"][1]["name"] == "Flora Fatalis Emblem"
    # Units carry no traits in this document: no partial counts are invented.
    assert rec["players"][0]["traits"] == []
    assert "health" not in rec["players"][1]
    _assert_anonymous(rec)


def test_gameclient_block_without_a_local_flag_has_no_local_player():
    b = _block()
    for p in b["statsBlock"]["players"]:
        p["isInteractable"] = False
    rec = tp.parse_gameclient_eog(b)
    assert rec["local_placement"] is None and rec["local_hp"] is None


@pytest.mark.parametrize("bad", [None, {}, {"gameId": 5, "statsBlock": 5},
                                 {"gameId": 5, "gameMode": "TFT",
                                  "statsBlock": {"players": []}},
                                 {"gameId": 0, "statsBlock": {"players": [{}]}}])
def test_gameclient_block_rejects_junk(bad):
    assert tp.parse_gameclient_eog(bad) is None


def test_is_tft_doc():
    assert tp.is_tft_doc(_block()) is True
    assert tp.is_tft_doc(_eog()) is True                    # queueType NORMAL_TFT
    assert tp.is_tft_doc({"gameId": 1, "gameMode": "CLASSIC", "teams": []}) is False
    assert tp.is_tft_doc(None) is False


def test_scrub_raw_covers_the_gameclient_identity_keys():
    out = tp.scrub_raw(_block())
    assert not set(_walk_keys(out)) & set(tp.IDENTITY_KEYS)
    for k in ("PUUID", "summonerIconID", "companionContentId", "companionName",
              "companionSkinId", "playerId"):
        assert k in tp.IDENTITY_KEYS
    blob = json.dumps(out)
    assert LOCAL_PUUID not in blob and "player0" not in blob
    assert "DA_Draven18" in blob


def test_display_from_id():
    assert tp.display_from_id("DA_18_EmblemFloraFatalis") == "Flora Fatalis Emblem"
    assert tp.display_from_id("DA_18_Yorick") == "Yorick"
    assert tp.display_from_id("DA_Gromp18_AP") == "Gromp"
    assert tp.display_from_id("DA_FloraFatalis18") == "Flora Fatalis"
    assert tp.display_from_id("TFT18_Draven") == "Draven"
    assert tp.display_from_id(None) == ""
