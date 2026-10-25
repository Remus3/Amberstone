"""TFT-09 (docs/TFT_PROGRAM.md section 4.1): `/api/state.tft_context`, the ONE
server-side authority the TFT views read.

    tft_context = {"active": bool, "phase": "lobby" | "match" | "post" | null,
                   "queue_id": int | null,
                   "source": "mode_key" | "lcu_queue" | "standalone" | "last_match"}

  match - mode_key "tft" (P0 keeps it through a restart) or the P0 standalone
          verdict;
  lobby - the LCU lobby / champ-select queue id maps to tft (core/queue_modes);
  post  - EndOfGame / PreEndOfGame / WaitingForStats right after a TFT match,
          or the last finished match is a TFT match from the store.

`source` is null exactly when `active` is false (no TFT context to source).
The four measured extra TFT queues (1160, 1220, 1230, 6110) are mapped in
core/queue_modes.py by S134 N2 (pinned by
tests/test_tft_league_side_effect_gate_s134.py); the /api/state test below
proves a lobby in each reads as TFT context end to end.

The RM-616 record is built from the sanitised tracked fixture
tests/fixtures/tft_eog_stats_set18.json (placeholder game id 1000000001).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dashboard import routes_tft as rt
from tft import tft_placement as tp
from tft import tft_standalone

REPO = Path(__file__).resolve().parent.parent
EOG_DOC = json.loads((REPO / "tests" / "fixtures" / "tft_eog_stats_set18.json")
                     .read_text(encoding="utf-8"))
KEYS = {"active", "phase", "queue_id", "source"}
PHASES = {"lobby", "match", "post"}
SOURCES = {"mode_key", "lcu_queue", "standalone", "last_match"}
T = 1_800_000_000.0


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "_STORE_DIR", tmp_path / "tft_matches")
    rt._reset_for_tests()
    yield
    rt._reset_for_tests()


def _shape_ok(ctx):
    assert set(ctx) == KEYS
    assert isinstance(ctx["active"], bool)
    if ctx["active"]:
        assert ctx["phase"] in PHASES and ctx["source"] in SOURCES
    else:
        assert ctx["phase"] is None and ctx["source"] is None and ctx["queue_id"] is None
    assert ctx["queue_id"] is None or (isinstance(ctx["queue_id"], int) and ctx["queue_id"] > 0)
    return ctx


def ctx(mode_key, preflip=False, lcu=None, lc=None, now=T):
    return _shape_ok(rt.tft_context(mode_key, preflip, lcu, lc, now=now))


def _settle_store(now):
    """Run the throttled store check and wait for its background read."""
    rt._post_store_newest(now)
    t = rt._POST_STORE["thread"]
    if t is not None:
        t.join(5.0)


# ------------------------------------------------------------------ match


def test_match_from_the_live_mode_key():
    got = ctx("tft", lcu={"phase": "InProgress", "game_queue_id": 1100})
    assert got == {"active": True, "phase": "match", "queue_id": 1100, "source": "mode_key"}


def test_match_from_the_standalone_verdict():
    lc = {"game_mode": "TFT", "source": tft_standalone.SOURCE_TAG, "live_api": False}
    got = ctx("tft", lcu={"phase": "InProgress"}, lc=lc)
    assert got == {"active": True, "phase": "match", "queue_id": None, "source": "standalone"}


def test_match_keeps_the_queue_it_saw_when_a_tick_omits_it():
    ctx("tft", lcu={"phase": "InProgress", "game_queue_id": 1090})
    assert ctx("tft", lcu={"phase": "InProgress"}, now=T + 5)["queue_id"] == 1090


# ------------------------------------------------------------------ lobby


def test_lobby_from_the_lcu_queue_preflip():
    got = ctx("tft", preflip=True, lcu={"phase": "Lobby", "lobby": {"queue_id": 1090}})
    assert got == {"active": True, "phase": "lobby", "queue_id": 1090, "source": "lcu_queue"}
    cs = {"phase": "ChampSelect", "champ_select": {"queue_id": 1100},
          "lobby": {"queue_id": 1090}}
    assert ctx("tft", preflip=True, lcu=cs)["queue_id"] == 1100   # champ select wins


@pytest.mark.parametrize("mode_key,preflip,lcu", [
    ("sr", False, {"phase": "InProgress", "game_queue_id": 420}),
    ("sr", True, {"phase": "Lobby", "lobby": {"queue_id": 420}}),
    ("aram", True, {"phase": "ChampSelect", "champ_select": {"queue_id": 450}}),
    ("client", False, {"phase": "Lobby", "lobby": {"queue_id": 0}}),
    ("client", False, {"phase": "Matchmaking"}),
    ("client", False, {"phase": "InProgress"}),
    ("client", False, None),
])
def test_no_tft_context_outside_tft(mode_key, preflip, lcu):
    assert ctx(mode_key, preflip, lcu) == rt.INACTIVE_CONTEXT


# ------------------------------------------------------------------ post


@pytest.mark.parametrize("phase", ["PreEndOfGame", "EndOfGame", "WaitingForStats", "None", ""])
def test_post_right_after_a_tft_match(phase):
    ctx("tft", lcu={"phase": "InProgress", "game_queue_id": 1100})
    got = ctx("client", lcu={"phase": phase}, now=T + 30)
    assert got == {"active": True, "phase": "post", "queue_id": 1100, "source": "mode_key"}


@pytest.mark.parametrize("phase", ["PreEndOfGame", "EndOfGame", "WaitingForStats"])
def test_post_while_the_tft_flag_is_still_up(phase):
    """The live flag can outlast the match by a poll or two; a post-game client
    phase is post, not match, and keeps the queue the match was seen in."""
    ctx("tft", lcu={"phase": "InProgress", "game_queue_id": 1160})
    got = ctx("tft", lcu={"phase": phase}, now=T + 10)
    assert got == {"active": True, "phase": "post", "queue_id": 1160, "source": "mode_key"}
    assert ctx("client", lcu={"phase": "None"}, now=T + 20)["phase"] == "post"


def test_post_ends_on_a_new_queue_a_later_live_game_or_the_window():
    ctx("tft", lcu={"phase": "InProgress", "game_queue_id": 1100})
    assert ctx("client", lcu={"phase": "Matchmaking"}, now=T + 60) == rt.INACTIVE_CONTEXT
    assert ctx("client", lcu={"phase": "EndOfGame"}, now=T + rt.POST_WINDOW_S + 1) \
        == rt.INACTIVE_CONTEXT
    ctx("tft", lcu={"phase": "InProgress"}, now=T + 100)
    ctx("sr", lcu={"phase": "InProgress", "game_queue_id": 420}, now=T + 200)
    assert ctx("client", lcu={"phase": "EndOfGame"}, now=T + 300) == rt.INACTIVE_CONTEXT


def test_post_from_the_store_after_a_restart(tmp_path):
    rec = tp.parse_eog(EOG_DOC, now=T - 120.0)            # captured 2 minutes ago
    assert tp.persist(rec, store_dir=tmp_path / "tft_matches")
    lcu = {"phase": "None"}
    first = ctx("client", lcu=lcu)                          # the read runs in the background
    assert first == rt.INACTIVE_CONTEXT
    _settle_store(T)
    got = ctx("client", lcu=lcu, now=T + 1)
    assert got == {"active": True, "phase": "post", "queue_id": 1090, "source": "last_match"}
    # a non-TFT game seen after that match ends the post context
    ctx("aram", lcu={"phase": "InProgress", "game_queue_id": 450}, now=T + 10)
    assert ctx("client", lcu=lcu, now=T + 20) == rt.INACTIVE_CONTEXT


def test_an_old_store_match_is_not_post(tmp_path):
    rec = tp.parse_eog(EOG_DOC, now=T - rt.POST_WINDOW_S - 60.0)
    assert tp.persist(rec, store_dir=tmp_path / "tft_matches")
    _settle_store(T)
    assert ctx("client", lcu={"phase": "EndOfGame"}, now=T + 1) == rt.INACTIVE_CONTEXT


def test_the_store_dir_is_stated_at_most_once_per_throttle(monkeypatch):
    calls = []
    monkeypatch.setattr(tp, "store_marker", lambda store_dir=None: calls.append(1) or 0)
    for i in range(20):
        ctx("client", lcu={"phase": "None"}, now=T + i * 0.1)
    assert len(calls) == 1
    ctx("client", lcu={"phase": "None"}, now=T + rt.POST_STORE_CHECK_S + 0.1)
    assert len(calls) == 2


def test_tft_context_never_raises_on_junk():
    for args in ((None, False, "junk", 7), ("tft", True, {"lobby": "x"}, None),
                 ("tft", False, {"game_queue_id": "abc"}, {"source": None}),
                 (42, False, {"phase": 9}, None)):
        _shape_ok(rt.tft_context(*args, now=T))


# ------------------------------------------------------------------ /api/state


def _build(monkeypatch, *, health, lcu):
    from unittest import mock

    from dashboard import _state_builder as sb
    monkeypatch.setattr(tft_standalone, "standalone_client_running", lambda **kw: False)
    base = {"alive": True, "mode": "client", "has_game": False, "aram_mode": False,
            "arena_mode": False, "tft_mode": False, **health}

    def _read_json(p):
        return dict(base) if "health" in str(p) else {}

    with mock.patch.object(sb, "read_json", side_effect=_read_json), \
            mock.patch.object(sb, "lcu_summary", return_value=lcu), \
            mock.patch.object(sb, "liveclient_summary", return_value={}), \
            mock.patch.object(sb, "get_team_context", return_value=None), \
            mock.patch.object(sb, "validate_coaching_payload", lambda *_a, **_kw: None):
        return sb.build_state()


def test_api_state_carries_tft_context_for_a_match_and_a_lobby(monkeypatch):
    state = _build(monkeypatch, health={"tft_mode": True},
                   lcu={"phase": "InProgress", "game_queue_id": 1100})
    assert state["mode_key"] == "tft"
    assert _shape_ok(state["tft_context"]) == {"active": True, "phase": "match",
                                                "queue_id": 1100, "source": "mode_key"}
    rt._reset_for_tests()
    state = _build(monkeypatch, health={},
                   lcu={"phase": "Lobby", "lobby": {"queue_id": 1090, "is_custom": False}})
    assert state["tft_context"] == {"active": True, "phase": "lobby", "queue_id": 1090,
                                    "source": "lcu_queue"}


@pytest.mark.parametrize("queue_id", [1160, 1220, 1230, 6110])
def test_api_state_reads_the_measured_extra_tft_queues_as_a_tft_lobby(monkeypatch, queue_id):
    """docs/TFT_PROGRAM.md risk 10: a lobby in one of the four queues the client
    measurably offers (Double Up, two event queues, the Set 17 revival) reads
    as TFT through core/queue_modes - the only queue table (no JS copy)."""
    from core.queue_modes import mode_key_from_queue_id
    assert mode_key_from_queue_id(queue_id) == "tft"
    state = _build(monkeypatch, health={},
                   lcu={"phase": "Lobby", "lobby": {"queue_id": queue_id, "is_custom": False}})
    assert state["mode_key"] == "tft"
    assert state["tft_context"] == {"active": True, "phase": "lobby", "queue_id": queue_id,
                                    "source": "lcu_queue"}


def test_api_state_tft_context_is_inactive_for_a_rift_game(monkeypatch):
    state = _build(monkeypatch, health={"has_game": True},
                   lcu={"phase": "InProgress", "game_queue_id": 420})
    assert state["tft_context"] == rt.INACTIVE_CONTEXT


def test_api_state_survives_a_tft_context_failure(monkeypatch):
    def boom(*_a, **_kw):
        raise RuntimeError("context failed")

    monkeypatch.setattr(rt, "tft_context", boom)
    state = _build(monkeypatch, health={"tft_mode": True}, lcu={"phase": "InProgress"})
    assert state["mode_key"] == "tft"
    assert state["tft_context"] == rt.INACTIVE_CONTEXT


def test_tft_context_is_cheap_on_the_state_path():
    t0 = time.perf_counter()
    for i in range(2000):
        rt.tft_context("client", False, {"phase": "None"}, None, now=T + i * 0.001)
    assert time.perf_counter() - t0 < 1.0
