"""s134: tft/tft_scouting.py - TFT opponent scouting digest.

Fixtures under tests/fixtures/tft_scouting/ are RECORDED shapes (one real
2026-10-25 TFT match: the end-of-game stats block, the local account's LCU TFT
history page and its ranked-stats) SANITISED: every name / riot id / puuid /
summoner id / game id / timestamp replaced with synthetic values. The ZEROED
puuid form the LCU uses for non-local players is preserved on purpose - it is
the measured behaviour the parser must not mistake for an identity. Riot Web
API bodies are synthesised from the same recorded participant rows (the LoL
product key 403s every /tft/* route, so none could be recorded). No real
network: LCU reads are a recording fake, Riot HTTP is a spy on
core.riot_api._http_get.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core import riot_api as RA
from core import riot_api_cache as RIC
from tft import tft_scouting as TS

FIX = Path(__file__).parent / "fixtures" / "tft_scouting"
SELF_LCU = "00000000-0000-4000-8000-000000000001"
ZERO = "00000000-0000-0000-0000-000000000000"
MAIN_KEY = "RGAPI-scout-test-key-000000000000000000000"  # rc-credential-scan: allow-fixture


def _load(name):
    return json.loads((FIX / name).read_text(encoding="ascii"))


EOG = _load("lcu_eog_tft_stats.json")
HIST = _load("lcu_tft_history_page.json")
RANKED = _load("lcu_ranked_stats.json")
TEMPLATE_GAME = HIST["games"][0]
TEMPLATE_ROW = next(p for p in TEMPLATE_GAME["json"]["participants"] if p["puuid"] == SELF_LCU)


def lcu_page(puuid, name, tag, placements, *, set_number=18, game_type="standard"):
    """A history page for one player built from the recorded game, newest first."""
    games = []
    for i, pl in enumerate(placements):
        g = copy.deepcopy(TEMPLATE_GAME)
        j = g["json"]
        j["game_datetime"] = str(1790000000000 - i * 3_600_000)
        j["tft_set_number"] = set_number if not isinstance(set_number, list) else set_number[i]
        j["tft_game_type"] = game_type if not isinstance(game_type, list) else game_type[i]
        g["metadata"]["match_id"] = f"NA1_{2000 + i}"
        for p in j["participants"]:
            if p["puuid"] == SELF_LCU:
                p.update(puuid=puuid, riotIdGameName=name, riotIdTagline=tag, placement=pl)
            else:
                p["puuid"] = ZERO
        games.append(g)
    return {"active_puuid": "", "games": games}


def riot_match(match_id, api_puuid, name, tag, placement, ts_ms):
    row = copy.deepcopy(TEMPLATE_ROW)
    row.update(puuid=api_puuid, riotIdGameName=name, riotIdTagline=tag, placement=placement)
    info = {k: v for k, v in TEMPLATE_GAME["json"].items() if k != "participants"}
    info.update(game_datetime=ts_ms, participants=[row], queue_id=1100)
    return {"metadata": {"match_id": match_id, "participants": [api_puuid]}, "info": info}


class FakeLcu:
    """Recording GET-only LCU reader: endpoint -> response."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls: list[str] = []

    def __call__(self, endpoint):
        self.calls.append(endpoint)
        for prefix, resp in self.routes.items():
            if endpoint.startswith(prefix):
                return resp(endpoint) if callable(resp) else copy.deepcopy(resp)
        return None


def ingame_session(entries, *, game_mode="TFT", game_id=5000000001):
    return {"phase": "InProgress",
            "gameData": {"gameId": game_id, "queue": {"gameMode": game_mode, "id": 1100},
                         "teamOne": entries, "teamTwo": []},
            "map": {"gameMode": game_mode}}


def entry(puuid, sid, name=""):
    """teamOne entry, keys as in the measured lobby session (summonerName empty)."""
    return {"championId": 0, "lastSelectedSkinIndex": 0, "profileIconId": 1, "puuid": puuid,
            "selectedPosition": "NONE", "selectedRole": "NONE.NONE.NONE.UNSELECTED",
            "summonerId": sid, "summonerInternalName": "", "summonerName": name,
            "teamOwner": False, "teamParticipantId": 1}


def opp_puuid(i):
    return f"00000000-0000-4000-8000-0000000001{i:02d}"


@pytest.fixture()
def riot_env(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "_KEY_CACHE", MAIN_KEY)
    monkeypatch.setattr(RA, "_TFT_KEY_CACHE", None)
    monkeypatch.setattr(RA, "_TFT_API_KEY_FILE", tmp_path / "API-Key-Riot-TFT.txt")
    RA._KEY_OVERRIDE_TLS.key = None
    RA._reset_bucket_for_tests()
    RIC._reset_for_tests(db_path=tmp_path / "cache.db")
    yield tmp_path
    RA._reset_bucket_for_tests()
    RIC._reset_for_tests(db_path=None)


def make_scouter(tmp_path, lcu=None, *, sleeps=None, clock=None, **kw):
    sleeps = sleeps if sleeps is not None else []
    clk = clock or (lambda: 1_800_000_000.0)
    return TS.Scouter(lcu_get=lcu, artifact_path=tmp_path / "data" / "tft_scouting.json",
                      cache=TS.DigestCache(tmp_path / "data" / "cache.json", clock=clk),
                      sleep=sleeps.append, clock=clk, **kw)


def artifact(tmp_path):
    return json.loads((tmp_path / "data" / "tft_scouting.json").read_text(encoding="ascii"))


# -- identities --------------------------------------------------------------------

def test_eog_recorded_identities_are_riot_ids_with_zeroed_puuids():
    ids = TS.identities_from_eog(EOG)
    assert [i.riot_id for i in ids] == [f"TestPlayer{n}#TST{n}" for n in range(2, 9)]
    assert all(i.lcu_puuid == "" for i in ids), "zeroed puuid must not become an identity"
    assert [i.slot for i in ids] == list(range(7))


def test_session_identities_exclude_self_dedupe_and_cap():
    entries = [entry(SELF_LCU, 900001)] + [entry(opp_puuid(i), 100 + i) for i in range(8)]
    entries.append(entry(opp_puuid(0), 100))          # duplicate
    entries.append(entry(ZERO, 0))                     # hidden: no puuid, no name
    ids = TS.identities_from_session(ingame_session(entries), SELF_LCU, 900001)
    assert len(ids) == TS.MAX_OPPONENTS
    assert [i.lcu_puuid for i in ids] == [opp_puuid(i) for i in range(7)]
    by_sid = TS.identities_from_session(ingame_session(entries), "", 900001)
    assert SELF_LCU not in [i.lcu_puuid for i in by_sid]


def test_session_identity_reads_riot_id_spellings():
    entries = [{"puuid": ZERO, "gameName": "A", "tagLine": "T1"},
               {"puuid": ZERO, "summonerName": "B#T2"},
               {"puuid": ZERO, "riotIdGameName": "C", "riotIdTagline": "#T3"}]
    ids = TS.identities_from_session(ingame_session(entries))
    assert [i.riot_id for i in ids] == ["A#T1", "B#T2", "C#T3"]


def test_lobby_session_shape_lists_no_opponents():
    """Measured Lobby shape: teamOne holds the party (here only self)."""
    lobby = ingame_session([entry(SELF_LCU, 900001)])
    assert TS.identities_from_session(lobby, SELF_LCU, 900001) == []


def test_tft_session_and_game_id():
    assert TS.is_tft_session(ingame_session([]))
    assert not TS.is_tft_session(ingame_session([], game_mode="CLASSIC"))
    assert TS.session_game_id(ingame_session([], game_id=0)) == ""
    assert TS.session_game_id(ingame_session([])) == "5000000001"


@pytest.mark.parametrize("value,expected", [
    (ZERO, ""), ("0", ""), ("", ""), (None, ""), ("abc", ""), (SELF_LCU, SELF_LCU)])
def test_real_puuid(value, expected):
    assert TS.real_puuid(value) == expected


# -- normalisation -----------------------------------------------------------------

def test_match_row_from_recorded_lcu_page():
    row = TS.match_row(TEMPLATE_GAME, puuid=SELF_LCU)
    assert row["placement"] == 1 and row["set"] == 18 and row["game_type"] == "standard"
    assert len(row["traits"]) == 15 and len(row["units"]) == 9
    assert row["ts_s"] == 1790000000
    assert TS.match_row(TEMPLATE_GAME, puuid=ZERO) is None
    assert TS.match_row(TEMPLATE_GAME, riot_id="testplayer2#tst2")["placement"] == 2


def test_match_row_from_riot_shape():
    api = "API-PUUID-" + "b" * 68
    m = riot_match("NA1_1", api, "Opp", "TST", 6, 1790000000000)
    assert TS.match_row(m, puuid=api)["placement"] == 6
    assert TS.match_row(m, puuid="short") is None, "a junk puuid never matches"
    assert TS.match_row({"info": {"participants": [{"puuid": api, "placement": 9}]}},
                        puuid=api) is None


@pytest.mark.parametrize("raw,expected", [
    ("DA_18_Blossom", "Blossom"), ("DA_Karma18", "Karma"), ("TFT13_Jinx", "Jinx"),
    ("TFT_Item_InfinityEdge", "Infinity Edge"), ("DA_FloraFatalis18", "Flora Fatalis"),
    ("DA_18_EmblemSpellweaver", "Emblem Spellweaver")])
def test_clean_name(raw, expected):
    assert TS.clean_name(raw) == expected


def test_rank_from_recorded_lcu_unranked():
    r = TS.rank_from_lcu_ranked(RANKED)
    assert r["ranked"] is False and r["display"] == "Unranked"


def test_rank_from_riot_entries():
    gold = [{"queueType": "RANKED_TFT_TURBO", "ratedTier": "BLUE"},
            {"queueType": "RANKED_TFT", "tier": "GOLD", "rank": "II", "leaguePoints": 40,
             "wins": 3, "losses": 27}]
    r = TS.rank_from_riot_entries(gold)
    assert r["display"] == "GOLD II 40 LP" and r["games"] == 30
    apex = TS.rank_from_riot_entries([{"queueType": "RANKED_TFT", "tier": "MASTER",
                                       "rank": "I", "leaguePoints": 210}])
    assert apex["display"] == "MASTER 210 LP" and apex["division"] is None
    assert TS.rank_from_riot_entries([])["ranked"] is False
    assert TS.rank_from_riot_entries(None) is None


# -- digest -------------------------------------------------------------------------

def _rows(placements, **kw):
    page = lcu_page(opp_puuid(1), "Opp", "TST", placements, **kw)
    return [TS.match_row(g, puuid=opp_puuid(1)) for g in page["games"]]


def test_digest_stats_streak_and_last_match():
    ident = TS.Identity("Opp", "TST", opp_puuid(1), slot=3)
    rows = _rows([1, 2, 3, 5, 6, 2, 4, 8, 1, 3, 7, 7])
    rank = TS.rank_from_riot_entries([{"queueType": "RANKED_TFT", "tier": "DIAMOND",
                                       "rank": "II", "leaguePoints": 45, "wins": 9,
                                       "losses": 41}])
    d = TS.build_digest(ident, rank, rows, n=10, source="lcu")
    s = d["sample"]
    assert s["n"] == 10
    assert s["avg_placement"] == 3.5
    assert s["top4_rate"] == 0.7 and s["first_rate"] == 0.2
    assert d["streak"] == {"kind": "top4", "length": 3}
    assert d["games_this_set"] == 50
    assert d["slot"] == 3 and d["riot_id"] == "Opp#TST"
    assert {"name": "Flora Fatalis", "count": 10} in d["top_traits"]
    assert d["top_carries"][0]["count"] == 10
    lm = d["last_match"]
    assert lm["placement"] == 1 and lm["set"] == 18 and lm["level"] == 9
    assert all(isinstance(c["items"], list) for c in lm["carries"])
    assert d["threat"]["level"] in ("high", "medium")
    assert d["threat"]["summary"].startswith("DIAMOND II 45 LP - avg 3.5, top4 70% (last 10)")
    assert "Opp" not in d["threat"]["summary"]


def test_double_up_is_excluded_and_set_games_counted():
    rows = _rows([1, 8, 2, 3], game_type=["standard", "pairs", "standard", "standard"],
                 set_number=[18, 18, 17, 18])
    d = TS.build_digest(TS.Identity("Opp", "TST"), None, rows)
    assert d["sample"]["n"] == 3 and d["sample"]["avg_placement"] == 2.0
    assert d["sample"]["set_counts"] == {"18": 2, "17": 1}
    assert d["sample"]["set_games"] == 2
    TS.apply_current_set(d, 17)
    assert d["sample"]["set_games"] == 1


def test_threat_levels():
    strong = TS.build_digest(TS.Identity("S", "T"), TS.rank_from_riot_entries(
        [{"queueType": "RANKED_TFT", "tier": "CHALLENGER", "leaguePoints": 900}]),
        _rows([1, 1, 2, 3, 1, 2, 4, 1, 2, 3]))
    weak = TS.build_digest(TS.Identity("W", "T"), TS.rank_from_riot_entries(
        [{"queueType": "RANKED_TFT", "tier": "IRON", "rank": "IV", "leaguePoints": 0}]),
        _rows([8, 7, 6, 8, 5, 7, 8, 6, 4, 7]))
    thin = TS.build_digest(TS.Identity("N", "T"), TS.rank_from_lcu_ranked(RANKED), _rows([2]))
    assert strong["threat"]["level"] == "high" and strong["threat"]["score"] >= 65
    assert weak["threat"]["level"] == "low" and "bottom-4 in a row" in weak["threat"]["summary"]
    assert thin["threat"] == {"level": "unknown", "score": None,
                              "summary": "Unranked - only 1 recent game"}


# -- scouter: LCU path ---------------------------------------------------------------

def _lcu_for(players):
    """players: {riot_id: (lcu_puuid, placements)} -> FakeLcu answering alias lookup,
    TFT history and ranked-stats."""
    by_name = {}
    routes = {}
    for rid, (puuid, placements) in players.items():
        name, tag = rid.split("#")
        by_name[(name, tag)] = puuid
        routes[f"/lol-match-history/v1/products/tft/{puuid}/"] = lcu_page(puuid, name, tag,
                                                                          placements)
        routes[f"/lol-ranked/v1/ranked-stats/{puuid}"] = RANKED

    def alias(ep):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(ep).query)
        p = by_name.get((q["gameName"][0], q["tagLine"][0]))
        return {"alias": {}, "puuid": p} if p else {}

    routes["/lol-summoner/v1/alias/lookup"] = alias
    return FakeLcu(routes)


def test_lcu_path_scouts_eog_identities_and_publishes_atomically(tmp_path):
    players = {f"TestPlayer{n}#TST{n}": (opp_puuid(n), [n % 8 + 1, 3, 4]) for n in range(2, 9)}
    lcu = _lcu_for(players)
    sc = make_scouter(tmp_path, lcu, sources=("lcu",))
    doc = sc.scout(TS.identities_from_eog(EOG), game_id="1000000001",
                   identity_source="lcu_eog", phase="EndOfGame")
    assert doc["status"] == "ready" and doc["counts"]["ready"] == 7
    assert doc == artifact(tmp_path)
    assert doc["sources"]["lcu"] == "ok" and doc["current_set"] == 18
    assert {o["source"] for o in doc["opponents"]} == {"lcu"}
    text = (tmp_path / "data" / "tft_scouting.json").read_text(encoding="ascii")
    assert all(opp_puuid(n) not in text for n in range(2, 9)), "no puuid in the artifact"
    assert not list((tmp_path / "data").glob("*.tmp"))
    assert all(ep.startswith("/lol-") for ep in lcu.calls)


def test_lcu_not_found_is_friendly(tmp_path):
    lcu = _lcu_for({})
    sc = make_scouter(tmp_path, lcu, sources=("lcu",))
    doc = sc.scout([TS.Identity("Bot", "TST", slot=0)])
    card = doc["opponents"][0]
    assert doc["status"] == "unavailable" and card["status"] == "unavailable"
    assert card["reason"] == "not_found"
    assert card["message"] == TS._MESSAGES["not_found"]


def test_one_failing_card_does_not_sink_the_run(tmp_path, monkeypatch):
    lcu = _lcu_for({"A#T": (opp_puuid(1), [2, 3, 4]), "B#T": (opp_puuid(2), [5, 6, 7])})
    sc = make_scouter(tmp_path, lcu, sources=("lcu",))
    real = TS.build_digest

    def flaky(ident, *a, **k):
        if ident.game_name == "A":
            raise ValueError("unexpected shape")
        return real(ident, *a, **k)
    monkeypatch.setattr(TS, "build_digest", flaky)
    doc = sc.scout([TS.Identity("A", "T", slot=0), TS.Identity("B", "T", slot=1)])
    assert doc["status"] == "partial"
    assert [o["status"] for o in doc["opponents"]] == ["unavailable", "ready"]
    assert "unexpected shape" not in json.dumps(doc), "raw error stays in the log"


def test_no_identities_is_no_opponents(tmp_path):
    sc = make_scouter(tmp_path, FakeLcu())
    doc = sc.scout([])
    assert doc["status"] == "no_opponents" and doc["message"]
    assert artifact(tmp_path)["status"] == "no_opponents"


def test_digest_cache_hit_inside_ttl_and_miss_after(tmp_path):
    now = [1_800_000_000.0]
    lcu = _lcu_for({"Opp#TST": (opp_puuid(1), [2, 2, 2])})
    sc = make_scouter(tmp_path, lcu, sources=("lcu",), clock=lambda: now[0])
    ident = [TS.Identity("Opp", "TST")]
    sc.scout(ident)
    first = len(lcu.calls)
    doc = sc.scout(ident)
    assert len(lcu.calls) == first and doc["opponents"][0]["cached"] is True
    now[0] += TS.DIGEST_TTL_S + 1
    sc.scout(ident)
    assert len(lcu.calls) > first


# -- scouter: Riot Web API path (real core.riot_api, HTTP spy) --------------------------

class RiotSpy:
    def __init__(self, handler):
        self.handler = handler
        self.urls: list[str] = []

    def __call__(self, url, api_key, timeout_s=None):
        self.urls.append(url)
        status, body, headers = self.handler(url, len(self.urls))
        return RA._HttpResp(status, json.dumps(body).encode("utf-8"), headers or {})


def _riot_ok(url, _n):
    if "/riot/account/v1/" in url:
        name = url.rsplit("/", 2)[-2]
        return 200, {"puuid": "API-" + name, "gameName": name, "tagLine": "TST"}, None
    if "/tft/league/v1/by-puuid/" in url:
        return 200, [{"queueType": "RANKED_TFT", "tier": "PLATINUM", "rank": "I",
                      "leaguePoints": 12, "wins": 4, "losses": 30}], None
    if url.split("?")[0].endswith("/ids"):
        name = url.split("/by-puuid/API-")[1].split("/")[0]
        return 200, [f"NA1_{name}_{i}" for i in range(3)], None
    if "/tft/match/v1/matches/" in url:
        mid = url.rsplit("/", 1)[-1]
        name, i = mid.split("_")[1], int(mid.split("_")[2])
        return 200, riot_match(mid, "API-" + name, name, "TST", [2, 4, 6][i],
                               1790000000000 - i * 3_600_000), None
    return 404, {}, None


def test_riot_path_success_uses_no_lcu(riot_env, monkeypatch):
    spy = RiotSpy(_riot_ok)
    monkeypatch.setattr(RA, "_http_get", spy)
    lcu = FakeLcu()
    sc = make_scouter(riot_env, lcu, riot=RA)
    doc = sc.scout([TS.Identity("Alpha", "TST", slot=0), TS.Identity("Beta", "TST", slot=1)])
    assert doc["status"] == "ready" and doc["sources"]["riot_api"] == "ok"
    card = doc["opponents"][0]
    assert card["source"] == "riot_api" and card["rank"]["display"] == "PLATINUM I 12 LP"
    assert card["sample"]["avg_placement"] == 4.0 and card["games_this_set"] == 34
    assert lcu.calls == []
    assert any("americas.api.riotgames.com/tft/match/v1/matches/by-puuid/" in u for u in spy.urls)
    assert any("na1.api.riotgames.com/tft/league/v1/by-puuid/" in u for u in spy.urls)


def test_riot_403_turns_path_off_once_and_falls_back_to_lcu(riot_env, monkeypatch):
    """The MEASURED live behaviour: product key -> 403 on every /tft/* route."""
    def handler(url, _n):
        if "/riot/account/v1/" in url:
            return 200, {"puuid": "API-x"}, None
        return 403, {"status": {"message": "Forbidden", "status_code": 403}}, None
    spy = RiotSpy(handler)
    monkeypatch.setattr(RA, "_http_get", spy)
    players = {f"P{i}#TST": (opp_puuid(i), [3, 3, 3]) for i in range(3)}
    sc = make_scouter(riot_env, _lcu_for(players), riot=RA)
    doc = sc.scout([TS.Identity(f"P{i}", "TST", slot=i) for i in range(3)])
    assert doc["status"] == "ready"
    assert doc["sources"] == {"riot_api": "not_enabled", "lcu": "ok"}
    assert {o["source"] for o in doc["opponents"]} == {"lcu"}
    tft_urls = [u for u in spy.urls if "/tft/" in u]
    assert len(tft_urls) == 1, "one 403 must switch the Riot path off for the run"
    text = json.dumps(doc)
    assert "403" not in text and "Forbidden" not in text


def test_riot_429_honours_retry_after_then_succeeds(riot_env, monkeypatch):
    state = {"ids_calls": 0}

    def handler(url, n):
        if url.split("?")[0].endswith("/ids"):
            state["ids_calls"] += 1
            if state["ids_calls"] == 1:
                return 429, {}, {"Retry-After": "1"}
        return _riot_ok(url, n)
    monkeypatch.setattr(RA, "_http_get", RiotSpy(handler))
    sleeps: list = []
    sc = make_scouter(riot_env, FakeLcu(), riot=RA, sleeps=sleeps)
    doc = sc.scout([TS.Identity("Alpha", "TST")])
    assert doc["status"] == "ready" and doc["opponents"][0]["source"] == "riot_api"
    assert len(sleeps) == 1 and 1.0 <= sleeps[0] <= 1.3, "waits out Retry-After"
    assert state["ids_calls"] == 2


def test_riot_429_persisting_degrades_to_rate_limited(riot_env, monkeypatch):
    def handler(url, n):
        if "/riot/account/v1/" in url:
            return _riot_ok(url, n)
        return 429, {}, {"Retry-After": "0"}
    monkeypatch.setattr(RA, "_http_get", RiotSpy(handler))
    sleeps: list = []
    sc = make_scouter(riot_env, None, riot=RA, sleeps=sleeps, sources=("riot_api",))
    doc = sc.scout([TS.Identity("Alpha", "TST")])
    card = doc["opponents"][0]
    assert card["status"] == "unavailable" and card["reason"] == "rate_limited"
    assert card["message"] == TS._MESSAGES["rate_limited"]
    assert len(sleeps) == TS.RETRY_ATTEMPTS - 1, "no wait after the last attempt"
    assert "429" not in json.dumps(doc)


def test_riot_match_loop_stops_when_still_rate_limited(riot_env, monkeypatch):
    """Verifier s134 (low): a persistent 429 on match detail must not be paid
    once per match id."""
    def handler(url, n):
        if "/tft/match/v1/matches/NA1_" in url:
            return 429, {}, {"Retry-After": "0"}
        return _riot_ok(url, n)
    spy = RiotSpy(handler)
    monkeypatch.setattr(RA, "_http_get", spy)
    sc = make_scouter(riot_env, None, riot=RA, sources=("riot_api",))
    card = sc.scout([TS.Identity("Alpha", "TST")])["opponents"][0]
    detail = [u for u in spy.urls if "/tft/match/v1/matches/NA1_" in u]
    assert len(detail) == TS.RETRY_ATTEMPTS, "first id retried, the rest skipped"
    assert card["reason"] == "rate_limited"


def test_riot_path_skipped_past_the_run_deadline(riot_env, monkeypatch):
    spy = RiotSpy(_riot_ok)
    monkeypatch.setattr(RA, "_http_get", spy)
    sc = make_scouter(riot_env, _lcu_for({"Alpha#TST": (opp_puuid(1), [2, 3, 4])}),
                      riot=RA, deadline_s=0.0)
    card = sc.scout([TS.Identity("Alpha", "TST")])["opponents"][0]
    assert spy.urls == [] and card["source"] == "lcu"


def _deadline_mid_run(trigger):
    """Riot handler that jumps the fake clock past the run deadline on the
    first request whose URL contains ``trigger``."""
    now = [1_800_000_000.0]

    def handler(url, n):
        if trigger in url and now[0] < 1_900_000_000.0:
            now[0] = 1_900_000_000.0
        return _riot_ok(url, n)
    return now, handler


def test_deadline_truncated_sample_is_shown_but_never_cached(riot_env, monkeypatch):
    """Verifier s134 re-check (low): a run that ran out of time must not cache
    a thin card as 'ready' for 15 minutes."""
    now, handler = _deadline_mid_run("/tft/match/v1/matches/NA1_")
    monkeypatch.setattr(RA, "_http_get", RiotSpy(handler))
    cache = TS.DigestCache(riot_env / "c.json", clock=lambda: now[0])
    sc = TS.Scouter(lcu_get=None, riot=RA, artifact_path=riot_env / "a.json", cache=cache,
                    sources=("riot_api",), sleep=lambda s: None, clock=lambda: now[0],
                    deadline_s=60.0)
    ident = TS.Identity("Alpha", "TST")
    card = sc.scout([ident])["opponents"][0]
    assert card["status"] == "ready" and card["partial"] is True
    assert card["sample"]["n"] == 1
    assert cache.get(ident) is None


def test_deadline_before_any_match_is_reported_as_deadline(riot_env, monkeypatch):
    now, handler = _deadline_mid_run("/ids?")
    monkeypatch.setattr(RA, "_http_get", RiotSpy(handler))
    sc = TS.Scouter(lcu_get=None, riot=RA, artifact_path=riot_env / "a.json",
                    cache=TS.DigestCache(riot_env / "c.json", clock=lambda: now[0]),
                    sources=("riot_api",), sleep=lambda s: None, clock=lambda: now[0],
                    deadline_s=60.0)
    card = sc.scout([TS.Identity("Alpha", "TST")])["opponents"][0]
    assert card["status"] == "unavailable" and card["reason"] == "deadline"
    assert card["message"] == TS._MESSAGES["deadline"]


def test_digest_cache_survives_a_damaged_row(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text(json.dumps({"junk": {"at": "not-a-time", "digest": {}}}), encoding="ascii")
    cache = TS.DigestCache(p, clock=lambda: 1_800_000_000.0)
    ident = TS.Identity("Opp", "TST")
    cache.put(ident, {"status": "ready"})
    assert cache.get(ident) == {"status": "ready"}
    assert "junk" not in json.loads(p.read_text(encoding="ascii"))


def test_riot_account_404_then_lcu_not_found(riot_env, monkeypatch):
    monkeypatch.setattr(RA, "_http_get", RiotSpy(lambda url, n: (404, {}, None)))
    sc = make_scouter(riot_env, _lcu_for({}), riot=RA)
    card = sc.scout([TS.Identity("Ghost", "TST")])["opponents"][0]
    assert card["reason"] == "not_found"


def test_kill_switch_writes_disabled_and_does_not_start(tmp_path, monkeypatch):
    monkeypatch.setenv(TS.ENV_KILL, "0")
    sc = make_scouter(tmp_path, FakeLcu())
    assert sc.start([TS.Identity("A", "T")], game_id="1") is False
    assert artifact(tmp_path)["status"] == "disabled"
    assert TS.start_scouting_watcher() is None


def test_superseded_token_cannot_overwrite(tmp_path):
    sc = make_scouter(tmp_path, FakeLcu())
    sc.write_status("no_opponents", game_id="2")
    stale = sc._token - 1
    sc._write({"schema": TS.SCHEMA, "status": "ready", "game_id": "1"}, stale)
    assert artifact(tmp_path)["game_id"] == "2"


# -- watcher -------------------------------------------------------------------------

class SpyScouter:
    def __init__(self):
        self.starts: list = []
        self.statuses: list = []

    def start(self, ids, **kw):
        self.starts.append((ids, kw))
        return True

    def write_status(self, status, **kw):
        self.statuses.append((status, kw))


def _watch_lcu(phase, session=None, eog=None):
    return FakeLcu({
        "/lol-gameflow/v1/gameflow-phase": lambda ep: phase[0],
        "/lol-gameflow/v1/session": lambda ep: session[0] if session else None,
        "/lol-end-of-game/v1/tft-eog-stats": eog,
        "/lol-summoner/v1/current-summoner": {"puuid": SELF_LCU, "summonerId": 900001},
    })


def test_watcher_lobby_does_nothing():
    lcu = _watch_lcu(["Lobby"])
    sp = SpyScouter()
    assert TS.ScoutingWatcher(sp, lcu).tick() == "idle"
    assert lcu.calls == ["/lol-gameflow/v1/gameflow-phase"] and sp.starts == []


def test_watcher_fires_once_per_game_at_game_start():
    entries = [entry(SELF_LCU, 900001)] + [entry(opp_puuid(i), 100 + i) for i in range(7)]
    lcu = _watch_lcu(["InProgress"], [ingame_session(entries)])
    sp = SpyScouter()
    w = TS.ScoutingWatcher(sp, lcu)
    assert w.tick() == "started"
    assert w.tick() == "idle"
    assert len(sp.starts) == 1
    ids, kw = sp.starts[0]
    assert len(ids) == 7 and kw["identity_source"] == "lcu_gameflow_session"
    assert kw["game_id"] == "5000000001"


def test_watcher_degrades_then_falls_back_to_eog_post_game():
    """The UNVERIFIED case: the in-game session lists only self."""
    phase = ["InProgress"]
    eog = copy.deepcopy(EOG)
    eog["gameId"] = 5000000001
    lcu = _watch_lcu(phase, [ingame_session([entry(SELF_LCU, 900001)])], eog)
    sp = SpyScouter()
    w = TS.ScoutingWatcher(sp, lcu)
    assert w.tick() == "no_opponents"
    assert w.tick() == "no_opponents"
    assert [s for s, _ in sp.statuses] == ["no_opponents"], "status written once"
    phase[0] = "PreEndOfGame"
    assert w.tick() == "started_post_game"
    ids, kw = sp.starts[0]
    assert len(ids) == 7 and kw["identity_source"] == "lcu_eog"
    assert w.tick() == "idle"


def test_watcher_waits_when_self_is_unknown():
    """Without our own puuid self would be scouted as an opponent."""
    entries = [entry(SELF_LCU, 900001)] + [entry(opp_puuid(i), 100 + i) for i in range(7)]
    lcu = _watch_lcu(["InProgress"], [ingame_session(entries)])
    del lcu.routes["/lol-summoner/v1/current-summoner"]
    sp = SpyScouter()
    w = TS.ScoutingWatcher(sp, lcu)
    assert w.tick() == "no_self" and sp.starts == []
    lcu.routes["/lol-summoner/v1/current-summoner"] = {"puuid": SELF_LCU, "summonerId": 900001}
    assert w.tick() == "started"
    assert SELF_LCU not in [i.lcu_puuid for i in sp.starts[0][0]]


def test_watcher_rereads_self_each_game_after_an_account_switch():
    """Verifier s134 (medium): a self cached forever scouts the local player
    after a client re-login as another account."""
    acct_a, acct_b = opp_puuid(50), opp_puuid(51)
    me = [{"puuid": acct_a, "summonerId": 1}]
    sess = [ingame_session([entry(acct_a, 1)] + [entry(opp_puuid(i), 100 + i)
                                                 for i in range(7)], game_id=1)]
    lcu = _watch_lcu(["InProgress"], sess)
    lcu.routes["/lol-summoner/v1/current-summoner"] = lambda ep: me[0]
    sp = SpyScouter()
    w = TS.ScoutingWatcher(sp, lcu)
    assert w.tick() == "started"
    me[0] = {"puuid": acct_b, "summonerId": 2}
    sess[0] = ingame_session([entry(acct_b, 2), entry(acct_a, 1)]
                             + [entry(opp_puuid(i), 100 + i) for i in range(6)], game_id=2)
    assert w.tick() == "started"
    second = [i.lcu_puuid for i in sp.starts[1][0]]
    assert acct_b not in second and acct_a in second


def test_watcher_ignores_non_tft_games():
    lcu = _watch_lcu(["InProgress"], [ingame_session([], game_mode="CLASSIC")])
    sp = SpyScouter()
    assert TS.ScoutingWatcher(sp, lcu).tick() == "not_tft"
    assert sp.starts == [] and sp.statuses == []


def test_default_lcu_get_only_ever_sends_get(monkeypatch):
    import lcu.lcu_client as LC
    sent = []

    class FakeClient:
        _port = 1234

        def _refresh_conn_if_changed(self):
            return False

        def connect(self):
            pass

        def _request(self, method, endpoint, data=None, _retry=True):
            sent.append((method, endpoint, data))
            return {"ok": True}

    monkeypatch.setattr(LC, "LcuClient", FakeClient)
    get = TS.default_lcu_get()
    assert get("/lol-gameflow/v1/session") == {"ok": True}
    assert sent == [("GET", "/lol-gameflow/v1/session", None)]
