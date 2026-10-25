"""S134 N2 / N3: no League-only side effect may fire for a TFT queue.

Measured 2026-10-25 (post-match QA, both TFT matches): during the brief TFT
champ-select phase (queue 1090, lobby gameMode "TFT") the RuneWriter wrote a
League rune page ("RC: Kai'Sa SR") and PATCHed summoner spells into the
account, then did it AGAIN as mode=CLASSIC once the lobby read stopped
answering (logs 07:02:57 and 08:12:28). Root cause: RuneWriter._poll acted on
ANY champ-select session - there was no queue / mode gate at all, and the
lobby-mode fallback is "CLASSIC" (fail-open). The recorded TFT session shape
carries "queueId" (ops/runtime/tft_qa/lcu_events.jsonl, 08:12:28).

Every sibling League-only side effect is pinned here with the same predicate
(core.queue_modes.is_tft_context): the RuneWriter rune + spell writes, the LCU
agent's auto summoner override and its loadout commands (rune page, item
sets, spells), the team-context Riot fan-out (League-V4 + Match-V5 ids, which
answered 400 for queue 1090), the Match-V5 timeline attach, the rewind live
writer's Match-V5 chain, and the League performance rating. Each gate has a
League positive control so an always-refusing gate cannot pass.

Every LCU / Riot call is a fake. Nothing here can reach a live client.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import queue_modes  # noqa: E402
from lcu.lcu_rune_writer import RuneWriter  # noqa: E402

TFT_QUEUES_ADDED = (1160, 1220, 1230, 6110)


# ---------------------------------------------------------------- queue map


@pytest.mark.parametrize("qid", TFT_QUEUES_ADDED)
def test_measured_tft_queues_map_to_tft(qid):
    assert queue_modes.mode_key_from_queue_id(qid) == "tft"
    assert queue_modes.is_tft_queue(qid)


@pytest.mark.parametrize("qid", (1090, 1100, 1130))
def test_existing_tft_queues_still_tft(qid):
    assert queue_modes.is_tft_queue(qid)


@pytest.mark.parametrize("qid", (420, 450, 2400, 1750, 0, None, "x"))
def test_league_and_unknown_queues_are_not_tft(qid):
    assert not queue_modes.is_tft_queue(qid)


def test_tft_context_reads_every_signal():
    assert queue_modes.is_tft_context(queue_id=1090)
    assert queue_modes.is_tft_context(game_mode="TFT")
    assert queue_modes.is_tft_context(game_mode="tft")
    assert queue_modes.is_tft_context(map_id=22)
    assert queue_modes.is_tft_context(queue_id=0, game_mode="", map_id="22")
    assert not queue_modes.is_tft_context()
    assert not queue_modes.is_tft_context(queue_id=420, game_mode="CLASSIC",
                                          map_id=11)
    assert not queue_modes.is_tft_context(game_mode="CHERRY", map_id=30)
    assert not queue_modes.is_tft_context(game_mode="KIWI", queue_id=2400)


# ---------------------------------------------------------------- RuneWriter


class _FakeLcu:
    """Champ-select LCU stand-in that records every mutating call."""

    def __init__(self, session, lobby_mode, gameflow=None):
        self.session = session
        self.lobby_mode = lobby_mode
        self.gameflow = gameflow
        self.gameflow_gets = 0
        self.writes: list[tuple] = []

    def get_champ_select(self):
        return self.session

    def _request(self, method, path, data=None):
        if method == "GET" and path == "/lol-lobby/v2/lobby":
            if self.lobby_mode is None:
                return None  # lobby gone (the CLASSIC-fallback poll)
            return {"gameConfig": {"gameMode": self.lobby_mode}}
        if method == "GET" and path == "/lol-gameflow/v1/session":
            self.gameflow_gets += 1
            return self.gameflow
        if method == "GET":
            return None
        self.writes.append((method, path))
        if method == "POST":
            return {"id": 77}
        return {}

    def get_all_rune_pages(self):
        return []

    def set_summoner_spells(self, d, f, current_pair=None):
        self.writes.append(("SPELLS", d, f))
        return True


def _session(queue_id):
    # Shape keys from the recorded TFT session (lcu_events.jsonl 08:12:28):
    # queueId at top level, my cell carries championId 145 and spells.
    return {"queueId": queue_id, "localPlayerCellId": 0, "actions": [],
            "myTeam": [{"cellId": 0, "championId": 145,
                        "championPickIntent": 0, "assignedPosition": "",
                        "spell1Id": 4, "spell2Id": 7}],
            "theirTeam": []}


def _gameflow(queue_id, game_mode, map_id):
    return {"gameData": {"queue": {"id": queue_id, "gameMode": game_mode,
                                   "mapId": map_id}},
            "map": {"id": map_id}}


def test_runewriter_gates_on_gameflow_queue_when_session_has_none():
    # Match 3 (2026-10-25 08:53:47): mode=CLASSIC from the first poll. With
    # no queue id on the session, the gameflow queue (1090) must decide -
    # read once per champ select, never per poll.
    fake = _FakeLcu(_session(0), None, gameflow=_gameflow(1090, "TFT", 22))
    rw = _writer(fake)
    with mock.patch.object(rw, "_write_page",
                           side_effect=AssertionError("rune write")):
        rw._poll()
        rw._poll()
    assert fake.writes == []
    assert fake.gameflow_gets == 1


def test_runewriter_gameflow_league_queue_positive_control():
    fake = _FakeLcu(_session(0), "CLASSIC", gameflow=_gameflow(420, "CLASSIC",
                                                               11))
    rw = _writer(fake)
    with mock.patch.object(rw, "_write_page", return_value=True) as wp:
        rw._poll()
    assert wp.call_count == 1
    assert any(w[0] == "SPELLS" for w in fake.writes)


def test_runewriter_session_queue_skips_the_gameflow_read():
    fake = _FakeLcu(_session(420), "CLASSIC", gameflow=_gameflow(1090, "TFT",
                                                                 22))
    rw = _writer(fake)
    with mock.patch.object(rw, "_write_page", return_value=True):
        rw._poll()
    assert fake.gameflow_gets == 0


def _writer(fake):
    rw = RuneWriter(fake)
    rw._champ_id_map = {145: "Kai'Sa"}
    return rw


def test_runewriter_writes_nothing_in_a_tft_champ_select():
    fake = _FakeLcu(_session(1090), "TFT")
    rw = _writer(fake)
    with mock.patch.object(rw, "_write_page",
                           side_effect=AssertionError("rune write")) as wp:
        rw._poll()
        # Second poll: the lobby stopped answering, so _detect_game_mode
        # falls back to "CLASSIC" - the exact path of the measured second
        # write. The session queue id must still hold the gate.
        fake.lobby_mode = None
        rw._cached_lobby_mode = None
        rw._poll()
    assert fake.writes == []
    assert wp.call_count == 0


def test_runewriter_gates_on_queue_id_alone():
    # Lobby unreadable from the first poll (fallback CLASSIC): the session's
    # own queueId is enough.
    fake = _FakeLcu(_session(6110), None)
    rw = _writer(fake)
    with mock.patch.object(rw, "_write_page",
                           side_effect=AssertionError("rune write")):
        rw._poll()
    assert fake.writes == []


def test_runewriter_gates_on_lobby_mode_alone():
    # An unmapped TFT queue id still carries gameMode "TFT" in the lobby.
    fake = _FakeLcu(_session(0), "TFT")
    rw = _writer(fake)
    with mock.patch.object(rw, "_write_page",
                           side_effect=AssertionError("rune write")):
        rw._poll()
    assert fake.writes == []


def test_runewriter_rearms_after_a_tft_champ_select():
    fake = _FakeLcu(_session(1090), "TFT")
    rw = _writer(fake)
    rw._poll()
    fake.session = None          # champ select ended
    rw._poll()
    fake.session = _session(420)  # next champ select is ranked SR
    fake.lobby_mode = "CLASSIC"
    with mock.patch.object(rw, "_write_page", return_value=True) as wp:
        rw._poll()
    assert wp.call_count == 1
    assert any(w[0] == "SPELLS" for w in fake.writes)


def test_runewriter_league_positive_control():
    fake = _FakeLcu(_session(420), "CLASSIC")
    rw = _writer(fake)
    with mock.patch.object(rw, "_write_page", return_value=True) as wp:
        rw._poll()
    assert wp.call_count == 1
    assert any(w[0] == "SPELLS" for w in fake.writes)


# ---------------------------------------------------------------- LCU agent


@pytest.fixture
def agent():
    import lcu_agent
    saved_cfg = dict(lcu_agent.CONFIG)
    saved_ss = dict(lcu_agent._session_state)
    saved_port = lcu_agent._lcu.get("port")
    yield lcu_agent
    lcu_agent.CONFIG.clear()
    lcu_agent.CONFIG.update(saved_cfg)
    lcu_agent._session_state.clear()
    lcu_agent._session_state.update(saved_ss)
    lcu_agent._lcu["port"] = saved_port


def _agent_fake(session):
    calls: list[tuple] = []

    def fake(method, path, body=None, *a, **kw):
        calls.append((method, path))
        if method == "GET" and path == "/lol-champ-select/v1/session":
            return session, None
        if method == "GET":
            return None, "404"
        if method == "POST":
            return {"id": 9}, None
        return {}, None
    return fake, calls


def _mutations(calls):
    return [c for c in calls if c[0] != "GET"]


def test_agent_auto_summoner_override_skips_tft(agent):
    agent._lcu["port"] = 1
    agent.CONFIG.update({"auto_accept": False, "summoner_override": True,
                         "summoner_d": 4, "summoner_f": 14})
    agent._session_state["last_summoner_set_for"] = None
    fake, calls = _agent_fake(_session(1090))
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        agent.auto_features()
    assert _mutations(calls) == []


def test_agent_auto_summoner_override_uses_snapshot_queue(agent):
    # Session carries no queue id; the snapshot's (gameflow-fallback) queue
    # says TFT, so no PATCH.
    agent._lcu["port"] = 1
    agent.CONFIG.update({"auto_accept": False, "summoner_override": True,
                         "summoner_d": 4, "summoner_f": 14})
    agent._session_state["last_summoner_set_for"] = None
    agent._note_live_queue({"phase": "ChampSelect",
                            "champ_select": {"queue_id": 1090}})
    fake, calls = _agent_fake(_session(0))
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        agent.auto_features()
    assert _mutations(calls) == []


def test_agent_auto_summoner_override_league_positive_control(agent):
    agent._lcu["port"] = 1
    agent.CONFIG.update({"auto_accept": False, "summoner_override": True,
                         "summoner_d": 4, "summoner_f": 14})
    agent._session_state["last_summoner_set_for"] = None
    fake, calls = _agent_fake(_session(420))
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        agent.auto_features()
    assert ("PATCH", "/lol-champ-select/v1/session/my-selection") in calls


_LOADOUT_CMDS = (
    {"cmd": "apply_runes", "page_name": "RC: Kai'Sa (SR)",
     "primary_id": 8000, "sub_id": 8100, "perk_ids": list(range(9))},
    {"cmd": "apply_item_set", "champion": "Kai'Sa", "mode": "sr",
     "blocks": []},
    {"cmd": "apply_item_sets_batch", "champion": "Kai'Sa", "sets": []},
    {"cmd": "delete_stale_rc_item_sets"},
    {"cmd": "set_summoners", "d": 4, "f": 7},
    {"cmd": "set_summoner_spell", "slot": 1, "spellId": 4},
)


@pytest.mark.parametrize("cmd", _LOADOUT_CMDS, ids=lambda c: c["cmd"])
@pytest.mark.parametrize("state", (
    {"phase": "ChampSelect", "champ_select": {"queue_id": 1090}},
    {"phase": "Lobby", "lobby": {"queue_id": 0, "game_mode": "TFT"}},
    {"phase": "InProgress", "game_queue_id": 6110},
), ids=("cs-queue", "lobby-mode", "in-game-queue"))
def test_agent_refuses_league_loadout_commands_in_tft(agent, cmd, state):
    agent._note_live_queue(state)
    fake, calls = _agent_fake(_session(1090))
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        res = agent.execute_command(dict(cmd))
    assert res.get("ok") is False
    assert "tft" in str(res.get("err", "")).lower()
    assert calls == []


def test_agent_loadout_command_league_positive_control(agent):
    agent._note_live_queue({"phase": "ChampSelect",
                            "champ_select": {"queue_id": 420}})
    fake, calls = _agent_fake(_session(420))
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        res = agent.execute_command(dict(_LOADOUT_CMDS[0]))
    assert res.get("ok") is True, res
    assert ("POST", "/lol-perks/v1/pages") in calls


def test_agent_live_queue_clears_when_client_leaves_tft(agent):
    agent._note_live_queue({"phase": "ChampSelect",
                            "champ_select": {"queue_id": 1090}})
    agent._note_live_queue({"phase": None})
    fake, calls = _agent_fake(_session(420))
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        res = agent.execute_command({"cmd": "set_summoners", "d": 4, "f": 7})
    assert res.get("ok") is True, res


def test_agent_non_loadout_commands_are_not_gated(agent):
    agent._note_live_queue({"phase": "Lobby",
                            "lobby": {"queue_id": 1090, "game_mode": "TFT"}})
    fake, calls = _agent_fake(None)
    with mock.patch.object(agent, "lcu_request", side_effect=fake):
        res = agent.execute_command({"cmd": "accept_ready"})
    assert res.get("ok") is True, res
    assert ("POST", "/lol-matchmaking/v1/ready-check/accept") in calls


# ------------------------------------------------- team-context fan-out


class _StubHandler:
    def __init__(self):
        self.responses: list[tuple] = []

    def _send(self, code, body, ctype="application/json"):
        self.responses.append((code, body, ctype))


def _post_team_context(queue_id):
    from dashboard import routes_team_context as rtc
    rtc._clear()
    seen: list[int] = []
    body = {"queue_id": queue_id, "roster": [
        {"puuid": "p1", "summoner_name": "X", "team_id": 100,
         "locked_champion": ""}]}
    h = _StubHandler()
    try:
        with mock.patch.object(rtc, "_FANOUT_DISPATCHER",
                               lambda a, e, q: seen.append(q)):
            rtc._serve_refresh_post(h, body)
    finally:
        rtc._clear()
    return h, seen


def test_team_context_skips_riot_fanout_for_tft():
    h, seen = _post_team_context(1090)
    assert h.responses[-1][0] == 200
    assert seen == []


def test_team_context_league_positive_control():
    h, seen = _post_team_context(420)
    assert h.responses[-1][0] == 200
    assert seen == [420]


# ------------------------------------------------- Match-V5 timeline attach


@pytest.mark.parametrize("detail", (
    {"platformId": "NA1", "gameId": 1, "gameMode": "TFT", "queueId": 1090},
    {"platformId": "NA1", "gameId": 1, "queueId": 1160},
    {"platformId": "NA1", "gameId": 1, "mapId": 22},
))
def test_timeline_attach_never_asks_match_v5_for_tft(detail):
    from core import riot_api
    from dashboard import builders_lcu_enrich as ble
    with mock.patch.object(riot_api, "get_match_timeline",
                           side_effect=AssertionError("match-v5")) as gm:
        enriched: dict = {}
        ble._attach_match_timeline(enriched, detail)
    assert gm.call_count == 0
    assert "timeline" not in enriched


def test_timeline_attach_league_positive_control():
    from core import riot_api
    from dashboard import builders_lcu_enrich as ble
    detail = {"platformId": "NA1", "gameId": 1, "gameMode": "CLASSIC",
              "queueId": 420, "mapId": 11}
    with mock.patch.object(riot_api, "get_match_timeline",
                           return_value=None) as gm:
        ble._attach_match_timeline({}, detail)
    assert gm.call_count == 1


# ------------------------------------------------- rewind live writer


def _staged(pin):
    from core import riot_api
    from lib import rewind_live_writer as rlw
    rlw._reset_staging_for_tests()
    with mock.patch.object(riot_api, "get_recent_matches",
                           side_effect=AssertionError("match-v5 ids")), \
         mock.patch.object(rlw.threading, "Timer",
                           side_effect=AssertionError("staged retry")):
        try:
            return rlw._staged_attempt(
                scheduled_at=0.0, chain="c-tft", attempt=0, pin=pin,
                retry_after_s=1.0, fetch_kw={})
        finally:
            rlw._reset_staging_for_tests()


@pytest.mark.parametrize("pin", (
    {"target_id": "NA1_5", "queue_id": 1090, "game_mode": "TFT",
     "riot_id": None},
    {"target_id": "NA1_5", "queue_id": 6110, "game_mode": "",
     "riot_id": None},
    {"target_id": "NA1_5", "queue_id": None, "game_mode": "TFT",
     "riot_id": None},
))
def test_rewind_writer_excludes_tft_without_any_riot_call(pin):
    res = _staged(pin)
    assert res["status"] == "tft_excluded", res
    assert res["match_id"] == "NA1_5"


def test_rewind_writer_league_pin_is_not_tft_excluded():
    from lib import rewind_live_writer as rlw
    assert not rlw._is_tft_pin({"queue_id": 450, "game_mode": "ARAM"})
    assert rlw._is_tft_pin({"queue_id": 1100, "game_mode": ""})


def test_rewind_writer_league_pin_passes_the_tft_gate():
    # Positive control through _staged_attempt itself: a League pin gets past
    # the TFT gate (and stops at the unconfigured key, before any Riot call).
    from core import riot_api
    with mock.patch.object(riot_api, "is_configured", return_value=False):
        res = _staged({"target_id": "NA1_5", "queue_id": 450,
                       "game_mode": "ARAM", "riot_id": None})
    assert res["status"] == "no_api_key", res


def test_tft_excluded_is_an_excluded_receipt():
    from lib import ingest_receipt
    assert ingest_receipt.classify("tft_excluded") == ingest_receipt.CLASS_EXCLUDED


def _ingest_lag_state(tmp_path, queue_id, game_mode):
    import json
    import time

    from core import ops_panels
    pin = tmp_path / "last_game_end.json"
    pin.write_text(json.dumps({"game_id": "5", "queue_id": queue_id,
                               "game_mode": game_mode,
                               "written_at": time.time()}), encoding="utf-8")
    return ops_panels._ingest_lag(pin, tmp_path / "absent.db",
                                  time.time())["state"]


def test_ops_panel_reads_a_tft_pin_as_excluded(tmp_path):
    assert _ingest_lag_state(tmp_path, 1090, "TFT") == "excluded"


def test_ops_panel_league_pin_is_not_excluded(tmp_path):
    assert _ingest_lag_state(tmp_path, 420, "CLASSIC") != "excluded"


# ------------------------------------------------- League performance rating


@pytest.fixture
def _no_rating_side_effects(monkeypatch):
    import performance_tracker as pt
    monkeypatch.setattr(pt, "_get_db", lambda sd: None)
    fake_fb = types.ModuleType("coaches.feedback")
    fake_fb.apply_grade = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "coaches.feedback", fake_fb)
    fake_eb = types.ModuleType("coaches.experimental_builder")
    fake_eb.consume_active = lambda: None
    monkeypatch.setitem(sys.modules, "coaches.experimental_builder", fake_eb)
    return pt


def _state(game_mode):
    return {"game_mode": game_mode, "game_seconds": 1800, "gold": 12000,
            "cs_per_min": 7.0, "kills": 5, "deaths": 2, "assists": 7,
            "kda": "5/2/7", "game_time": "30:00"}


def test_league_rating_refuses_a_tft_game(tmp_path, _no_rating_side_effects):
    pt = _no_rating_side_effects
    rep: dict = {}
    assert pt.save_rating(str(tmp_path), "Kai'Sa", _state("TFT"), 1,
                          report=rep) == ("", [])
    assert rep == {"rated": False, "file_written": False}
    assert not list(tmp_path.rglob("last_tft.json"))


def test_league_rating_positive_control(tmp_path, _no_rating_side_effects):
    pt = _no_rating_side_effects
    rep: dict = {}
    g, _n = pt.save_rating(str(tmp_path), "Kai'Sa", _state("CLASSIC"), 15,
                           report=rep)
    assert g
    assert rep == {"rated": True, "file_written": True}


# ------------------------------------------------- game end (frozen lifecycle)
#
# app/_game_lifecycle.py (FROZEN; operator approved the edit, chat 2026-10-25).
# A TFT end must run save_tft_rating, never the League save_rating, and never
# schedule the League rewind live-writer (Match-V5). The envelope's _tft_mode
# can be lost mid-match (QA N1), so the last game state's own TFT marks count.


class _LifecycleApp:
    def __init__(self, state, tft=False):
        import queue
        self._game_state = state
        self._tft_mode = tft
        self._arena_mode = False
        self._brawl_mode = False
        self._aram_mode = False
        self._tft_coach = None
        self._tft_worker = None
        self._sr_aram_worker = None
        self._coach = None
        self.data = {}
        self._tft_q = queue.Queue()

    def _write_data(self, fields=None):
        pass

    def _update_envelope(self, *a, **k):
        pass


def _game_end(monkeypatch, tmp_path, app):
    from app import _game_lifecycle as gl
    calls = {"rewind": 0, "league": 0, "tft": 0}
    monkeypatch.setattr(gl, "HAS_POSTGAME", False)
    monkeypatch.setattr(gl, "SCRIPT_DIR", tmp_path)
    fake_rlw = types.ModuleType("lib.rewind_live_writer")

    def _sched(_app):
        calls["rewind"] += 1
    fake_rlw.schedule_live_insert = _sched
    monkeypatch.setitem(sys.modules, "lib.rewind_live_writer", fake_rlw)

    def _league(*a, report=None, **k):
        calls["league"] += 1
        return ("B", [])

    def _tft(*a, report=None, **k):
        calls["tft"] += 1
        return ("A", [])
    monkeypatch.setattr(gl, "save_rating", _league, raising=False)
    monkeypatch.setattr(gl, "save_tft_rating", _tft, raising=False)
    monkeypatch.setattr(gl, "HAS_TRACKER", True)
    gl.GameLifecycleManager(app).on_game_end()
    return calls


@pytest.mark.parametrize("app_args", (
    ({}, True),
    ({"game_mode": "TFT", "data_source": "tft_standalone"}, False),
    ({"data_source": "tft_standalone"}, False),
    ({"game_mode": "TFT"}, False),
), ids=("tft-mode", "state-tft-standalone", "standalone-tag", "state-tft"))
def test_tft_game_end_rates_tft_and_skips_league_work(monkeypatch, tmp_path,
                                                      app_args):
    state, tft = app_args
    calls = _game_end(monkeypatch, tmp_path, _LifecycleApp(state, tft=tft))
    assert calls == {"rewind": 0, "league": 0, "tft": 1}


def test_league_game_end_positive_control(monkeypatch, tmp_path):
    calls = _game_end(monkeypatch, tmp_path, _LifecycleApp(
        {"game_mode": "CLASSIC", "champion": "Ahri",
         "data_source": "live_client"}))
    assert calls == {"rewind": 1, "league": 1, "tft": 0}


class _StartApp(_LifecycleApp):
    """on_game_start needs the envelope flag flip and a scheduler."""

    def __init__(self):
        super().__init__({})
        self.scheduler = types.SimpleNamespace(schedule=lambda *a, **k: None)

    def _update_envelope(self, mode, payload=None):
        from core.game_snapshot import MODE_TFT
        self._tft_mode = (mode == MODE_TFT)


def _tft_game_start(monkeypatch, tmp_path, base=object):
    """Run on_game_start(MODE_TFT) with a recording TftWorker; its kwargs.
    base = a real worker class to build too (its start() never runs)."""
    from app import _game_lifecycle as gl
    from core import feature_policy
    from core.game_snapshot import MODE_TFT
    made: list[dict] = []

    class _RecWorker(base):
        def __init__(self, **kw):
            if base is not object:
                super().__init__(**kw)
            made.append(dict(kw, _worker=self))

        def start(self):
            pass

    class _Coach:
        def __init__(self, *a, **k):
            pass

        def set_worker(self, w):
            pass

    fake_coach = types.ModuleType("coaches.tft_coach")
    fake_coach.Coach = _Coach
    monkeypatch.setitem(sys.modules, "coaches.tft_coach", fake_coach)
    monkeypatch.setattr(feature_policy, "is_allowed", lambda *a, **k: True)
    monkeypatch.setattr(gl, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(gl, "HAS_TFT_WORKER", True)
    monkeypatch.setattr(gl, "TftWorker", _RecWorker, raising=False)
    gl.GameLifecycleManager(_StartApp()).on_game_start(MODE_TFT)
    assert len(made) == 1
    return made[0]


def test_tft_game_start_hands_the_worker_an_lcu_reader(monkeypatch, tmp_path):
    # S18-COACH: TftWorker(..., lcu_request=make_lcu_request()) lets
    # tft_set.set_from_lcu read mDefaultSet. Never a real LCU here.
    import core.tft_worker as tw
    sentinel = object()
    monkeypatch.setattr(tw, "make_lcu_request", lambda: sentinel,
                        raising=False)
    kw = _tft_game_start(monkeypatch, tmp_path)
    assert kw["lcu_request"] is sentinel


def test_tft_game_start_guarded_without_make_lcu_request(monkeypatch,
                                                         tmp_path):
    # A core.tft_worker that predates make_lcu_request gets no kwarg, so the
    # older TftWorker signature is never handed one it cannot take.
    import core.tft_worker as tw
    monkeypatch.delattr(tw, "make_lcu_request", raising=False)
    kw = _tft_game_start(monkeypatch, tmp_path)
    assert "lcu_request" not in kw
    assert kw["result_queue"] is not None


def test_tft_game_start_real_worker_gets_the_real_lcu_reader(monkeypatch,
                                                             tmp_path):
    # S134 M1d: S18-COACH landed core.tft_worker.make_lcu_request, so the
    # guarded call in app/_game_lifecycle.py resolves with NOTHING patched on
    # core.tft_worker, and the REAL TftWorker keeps the reader. The reader is
    # lazy: building it and the worker never constructs an LcuClient.
    import core.tft_worker as tw
    import lcu.lcu_client as lc
    from app import _game_lifecycle as gl
    assert callable(getattr(tw, "make_lcu_request", None))
    assert callable(gl._tft_lcu_kwargs().get("lcu_request"))
    clients: list = []

    class _NoClient:
        def __init__(self, *a, **k):
            clients.append(self)
    monkeypatch.setattr(lc, "LcuClient", _NoClient)
    kw = _tft_game_start(monkeypatch, tmp_path, base=tw.TftWorker)
    req = kw["lcu_request"]
    assert req.__qualname__ == "make_lcu_request.<locals>._request"
    assert kw["_worker"]._lcu_request is req
    assert isinstance(kw["_worker"], tw.TftWorker)
    assert clients == []


def test_tft_game_ended_never_raises_on_odd_state():
    from app import _game_lifecycle as gl
    assert gl._tft_game_ended(_LifecycleApp(None)) is False
    assert gl._tft_game_ended(_LifecycleApp(["x"])) is False
    assert gl._tft_game_ended(_LifecycleApp({"game_mode": None})) is False
