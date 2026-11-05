"""Tests for tools/gated_g426_pgr_edge.py (G4-26 READY, read-only grader).

The tool replays a sampled /api/state stream through the Python mirror of the
page's view router (dashboard/view_router_state.py) to say whether the game-end
edge that auto-shows the Post Game Review reached /api/state. These tests pin
the verdict table on synthetic idle / in-game shapes; no game, no network.
Samples are 1 s apart (t = index).
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import gated_g426_pgr_edge as g  # noqa: E402

_LC = {"game_time_s": 600, "level": 11}


def _st(phase=None, mode="sr", live=True):
    lcu = {"phase": phase} if phase is not None else {}
    return {"lcu": lcu, "mode_key": mode, "liveclient": dict(_LC) if live else {}}


def _tail(phase=None):
    """A non-live tail long enough (past END_SPAN_S) to count as a game end."""
    return [_st(phase, "client", False)] * (int(g.END_SPAN_S) + 2)


def _stream(states):
    return [g.sample_from_state(s, None if s is not None else "down", float(i))
            for i, s in enumerate(states)]


def _grade(states):
    return g.grade_stream(_stream(states))


def test_phase_blind_game_then_end_of_game_fires_and_exercises_the_fix():
    # The 2026-07-20 case: lcu {} for the whole game (5 s TTL vs 8-11 s capture).
    res = _grade([_st(), _st(), _st()] + _tail("EndOfGame"))
    assert res["verdict"] == "EDGE_DELIVERED"
    assert res["edge_phase"] == "EndOfGame"
    assert res["pre_fix_would_fire"] is False
    assert res["fix_path_exercised"] is True
    assert res["null_phase_live_samples"] == 3
    assert res["last_in_game_to_edge_s"] == 1.0
    assert res["mid_game_edges"] == 0
    assert res["miss_cause"] is None


def test_explicit_in_progress_game_fires_without_needing_the_fix():
    res = _grade([_st("InProgress"), _st("InProgress")] + _tail("WaitingForStats"))
    assert res["verdict"] == "EDGE_DELIVERED"
    assert res["pre_fix_would_fire"] is True
    assert res["fix_path_exercised"] is False


def test_armed_game_end_with_no_postgame_phase_is_a_ttl_side_miss():
    res = _grade([_st(), _st()] + _tail())
    assert res["verdict"] == "EDGE_MISSED"
    assert res["game_ended_in_window"] is True
    assert res["miss_cause"] == "no_postgame_phase"


def test_unarmed_game_end_with_a_postgame_phase_is_an_arm_side_miss():
    # The post-game phase DID reach /api/state; the page was never armed (no
    # in-game mode_key), so this must not be filed against the TTL.
    for blank in ("client", None):
        res = _grade([_st(None, blank)] * 5 + _tail("EndOfGame"))
        assert res["verdict"] == "EDGE_MISSED", blank
        assert res["miss_cause"] == "not_armed_at_end", blank


def test_short_tail_or_stale_phase_at_the_window_end_is_not_a_game_end():
    assert _grade([_st(), _st(), _st(None, "sr", False)])["verdict"] == "NO_EVIDENCE"
    # A stale Lobby on the final live sample, game still running: no pass.
    res = _grade([_st(None, "aram")] * 20 + [_st("Lobby", "aram")])
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["game_ended_in_window"] is False
    res = _grade([_st(None, "aram")] * 20 + [_st("Lobby", "aram", False)] * 2)
    assert res["verdict"] == "NO_EVIDENCE"


def test_idle_window_is_no_evidence():
    res = _grade([_st(None, "client", False)] * 5)
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["live_samples"] == 0


def test_game_still_running_at_window_end_is_no_evidence():
    res = _grade([_st(), _st("InProgress"), _st()])
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["game_ended_in_window"] is False


def test_liveclient_blip_that_recovers_is_not_a_game_end():
    # liveclient_summary returns {} on any >5 s stale cache; a blip mid-game is
    # not an end, so a still-running game stays NO_EVIDENCE, never a false FAIL.
    res = _grade([_st(), _st(), _st(None, "sr", False), _st(), _st()])
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["game_ended_in_window"] is False
    # ... while a blip followed by a real end is still graded on that end.
    assert _grade([_st(), _st(None, "sr", False), _st()] + _tail())["verdict"] \
        == "EDGE_MISSED"


def test_stale_postgame_phase_blip_that_recovers_is_not_a_game_end():
    res = _grade([_st(None, "client"), _st(None, "client"), _st("Lobby", "client"),
                  _st(None, "client"), _st(None, "client")])
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["game_ended_in_window"] is False


def test_armed_mid_game_stale_lobby_edge_is_not_the_end_edge():
    # The page fires on a stale Lobby mid-game; the game runs on.
    res = _grade([_st(), _st("Lobby"), _st(), _st()])
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["mid_game_edges"] == 1
    # The real end after it is graded on its own edge (the sticky re-arms).
    res = _grade([_st(), _st("Lobby"), _st(), _st()] + _tail("EndOfGame"))
    assert res["verdict"] == "EDGE_DELIVERED"
    assert res["edge_phase"] == "EndOfGame"
    assert res["mid_game_edges"] == 1
    # And a real end with no edge after a mid-game one is a miss, not a pass.
    res = _grade([_st(), _st("Lobby"), _st(), _st()] + _tail())
    assert res["verdict"] == "EDGE_MISSED"
    assert res["mid_game_edges"] == 1


def test_end_of_game_while_liveclient_still_up_is_the_end_edge():
    res = _grade([_st(), _st(), _st("EndOfGame", "sr", True)] + _tail("EndOfGame"))
    assert res["verdict"] == "EDGE_DELIVERED"
    assert res["last_in_game_to_edge_s"] == 1.0
    # The cached liveclient can stay non-empty for several post-game samples
    # (up to 5 s): the edge on the FIRST of them is still the real end edge.
    res = _grade([_st(None, "aram")] * 10 + [_st("WaitingForStats", "aram")] * 2
                 + [_st("WaitingForStats", "client", False)] + _tail("EndOfGame"))
    assert res["verdict"] == "EDGE_DELIVERED"
    assert res["edge_phase"] == "WaitingForStats"
    assert res["mid_game_edges"] == 0
    assert res["miss_cause"] is None


def test_mode_keeps_the_last_in_game_tag_like_on_state():
    # onState calls setMode only for an in-game tag; a missing mode_key and
    # "client" both read as "client" there, so both keep the prior mode.
    for blank in (None, "client"):
        res = _grade([_st(None, "aram", False), _st(None, blank)] + _tail("EndOfGame"))
        assert res["verdict"] == "EDGE_DELIVERED", blank


def test_two_games_in_one_window_grade_only_the_last():
    game_a = [_st(), _st(), _st("EndOfGame", "client", False), _st("Lobby", "client", False),
              _st("ChampSelect", "client", False)]
    res = _grade(game_a + [_st("InProgress"), _st()])
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["mid_game_edges"] == 1


def test_matchmaking_blip_mid_game_is_not_an_edge():
    # s209: Matchmaking / ReadyCheck / "None" sit in the clear arm but are not edges.
    res = _grade([_st(), _st("Matchmaking"), _st("ReadyCheck"), _st()])
    assert res["verdict"] == "NO_EVIDENCE"
    assert res["edge_phase"] is None
    assert res["mid_game_edges"] == 0


def test_dash_down_samples_are_skipped_not_read_as_game_end():
    res = _grade([_st(), None, None, _st()])
    assert res["dash_down"] == 2
    assert res["verdict"] == "NO_EVIDENCE"
    assert _grade([_st(), None] + _tail("EndOfGame"))["verdict"] == "EDGE_DELIVERED"
    assert _grade([_st(), _st()] + [None] * 30)["verdict"] == "NO_EVIDENCE"


def test_stale_mode_flag_without_live_does_not_arm():
    # item 281: a stale in-game mode with an empty liveclient is not a game.
    res = _grade([_st(None, "aram", False)] + [_st("EndOfGame", "aram", False)] * 20)
    assert res["verdict"] == "NO_EVIDENCE"


def test_sample_shape_degrades_bad_fields():
    s = g.sample_from_state({"lcu": "x", "mode_key": 5, "liveclient": []}, None, 1.0)
    assert s == {"t": 1.0, "dash_down": False, "phase": None, "mode": None,
                 "live": False, "lcu_keys": 0}
    s = g.sample_from_state({"lcu": {"phase": ""}, "liveclient": {"source": "x"}}, None, 2.0)
    assert s["phase"] is None and s["live"] is True
    assert g.sample_from_state(None, "URLError", 3.0)["dash_down"] is True


def _run(states):
    feed = iter(_stream(states))
    args = g.build_parser().parse_args(["sample", "--samples", str(len(states)),
                                        "--interval", "0", "--json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = g.run(args, probe=lambda: next(feed), sleep=lambda _s: None)
    return rc, json.loads(buf.getvalue())


def test_run_exit_codes_and_output_carry_no_ids():
    rc, out = _run([_st()] + _tail("EndOfGame"))
    assert rc == 0
    assert out["verdict"] == "EDGE_DELIVERED"
    assert set(out["stream"][0]) == {"t", "dash_down", "phase", "mode", "live"}
    assert _run([_st()] + _tail())[0] == 3
    assert _run([_st(None, "client", False)] * 2)[0] == 4


def test_cli_refuses_out_of_range_arguments():
    assert g.main(["sample", "--samples", "0"]) == 2
    assert g.main(["sample", "--samples", "3601"]) == 2
    assert g.main(["sample", "--samples", "1", "--interval", "-1"]) == 2
    assert g.main(["sample", "--samples", "1", "--interval", "nan"]) == 2


def test_tool_reads_the_mirror_mode_set():
    from dashboard import view_router_state as v
    assert g.IN_GAME_MODES is v.IN_GAME_MODES
