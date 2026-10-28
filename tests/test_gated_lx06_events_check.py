"""Tests for tools/gated_lx06_events_check.py - the lane-9 /api/events client and
grader for the LX-06 drain (RM-604). The record tests run the REAL route
(dashboard/routes_events._serve_events) over a loopback HTTP server fed by a
real core.live_event_hub.LiveEventHub, so the wire format cannot drift from the
server; the grader tests use hand-built capture rows. Every name and id here is
synthetic (RM-906).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest

from core import live_event_hub as hub_mod
from dashboard import routes_events as rev
from tools import gated_lx06_events_check as g

LEG = frozenset({"3031"})


def _snap(t, zed_dead=False, lux_level=3):
    return {
        "activePlayer": {"summonerName": "SynthLux#T1"},
        "allPlayers": [
            {"championName": "Lux", "summonerName": "SynthLux#T1", "team": "ORDER",
             "isDead": False, "level": lux_level, "items": []},
            {"championName": "Zed", "summonerName": "SynthZed#T2", "team": "CHAOS",
             "isDead": zed_dead, "level": 4, "items": []},
        ],
        "gameData": {"gameMode": "CLASSIC", "gameTime": t},
        "events": {"Events": []},
    }


def _hub(seed=1000):
    return hub_mod.LiveEventHub(ring_max=1024, id_seed=seed, completed_ids=lambda: LEG)


# ------------------------------------------------------------------ parser

def test_parser_follows_the_sse_id_and_comment_rules():
    p = g.SseParser()
    assert p.feed("retry: 2000") == [("retry", 2000)]
    assert p.feed("") == []
    assert p.feed("id: 7") == []
    assert p.feed('data: {"a":') == []
    assert p.feed("data: 1}") == []
    # WHATWG: the reconnect id moves only when the frame is dispatched, so a
    # connection cut here would resume from the id before frame 7
    assert p.last_id is None
    assert p.feed("") == [("frame", "7", '{"a":\n1}')]
    assert p.last_id == "7"
    assert p.feed(": hb") == [("comment", "hb")]
    # a frame with no id line keeps the persisted last id but carries none itself
    p.feed("data: {}")
    assert p.feed("") == [("frame", None, "{}")]
    assert p.last_id == "7"


# ------------------------------------------------------- record (real route)

class _Server:
    """Loopback HTTP server whose /api/events is the real route."""

    def __init__(self, holder):
        self.holder = holder
        self.state_hits = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, payload, ctype):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                if self.path.startswith("/api/events"):
                    rev._serve_events(self)
                elif self.path == "/api/state":
                    outer.state_hits += 1
                    self._send(200, b'{"mode_key": "client"}', "application/json")
                else:
                    self._send(404, b"{}", "application/json")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._patches = [
            mock.patch.object(rev, "_get_hub", side_effect=lambda: self.holder[0]),
            mock.patch.object(rev, "_SSE_MAX_DURATION_S", 0.8),
            mock.patch.object(rev, "_WAIT_SLICE_S", 0.02),
        ]
        for p in self._patches:
            p.start()
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        for p in self._patches:
            p.stop()


def _feeder(holder, steps, every=0.12, t0=100.0, swap_at=None, new_hub=None):
    def run():
        holder[0].observe(_snap(t0))
        for i in range(steps):
            time.sleep(every)
            if swap_at is not None and i == swap_at:
                holder[0] = new_hub
                holder[0].observe(_snap(t0 + i))
            holder[0].observe(_snap(t0 + 1 + i, zed_dead=(i % 2 == 0)))
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _record(tmp_path, srv, secs, **kw):
    out = tmp_path / "lx06.jsonl"
    g.record(out, base=srv.base, minutes=secs / 60.0,
             sleep=lambda s: time.sleep(0.05), **kw)
    return g.load_capture(out)


def test_record_resumes_across_the_server_cap_without_a_hole(tmp_path):
    holder = [_hub()]
    with _Server(holder) as srv:
        feed = _feeder(holder, 14)
        rows = _record(tmp_path, srv, 2.4)
        feed.join()
    s = g.check(rows)
    assert s["connections"] >= 2
    assert s["holes"] == [] and s["bad_gaps"] == []
    assert s["reconnect_hello"] == [] and s["last_event_id_mismatch"] == []
    assert s["stream_ok"] is True
    assert s["kinds"].get("death", 0) >= 3 and s["kinds"].get("respawn", 0) >= 3
    conns = [r for r in rows if r["t"] == "conn"]
    assert s["bases"] == [srv.base] and s["replay_conns"] == [] and s["non_sse_conns"] == []
    assert conns[0]["last_event_id"] is None
    assert all(c["last_event_id"] is not None for c in conns[1:])
    # every connection after the first was closed by the server cap (EOF), not a client error
    assert {r["reason"] for r in rows if r["t"] == "end"} <= {"eof", "deadline"}


def test_record_reads_a_restart_as_a_gap_then_rereads_state(tmp_path):
    holder = [_hub(seed=1000)]
    with _Server(holder) as srv:
        feed = _feeder(holder, 12, swap_at=6, new_hub=_hub(seed=5_000_000))
        rows = _record(tmp_path, srv, 2.4)
        feed.join()
    s = g.check(rows)
    assert s["restart_resumes"], s
    assert s["state_reread_after_restart"] and set(s["state_reread_after_restart"]) == {200}
    assert srv.state_hits >= 1
    assert s["holes"] == [] and s["bad_gaps"] == [] and s["stream_ok"] is True


def test_drop_after_closes_the_first_connection_and_resumes(tmp_path):
    holder = [_hub()]
    # the deadline is checked between lines, so a short heartbeat ends the idle tail fast
    with _Server(holder) as srv, mock.patch.object(rev, "_SSE_MAX_DURATION_S", 30.0),             mock.patch.object(rev, "_HEARTBEAT_S", 0.2):
        feed = _feeder(holder, 8, every=0.08)
        rows = _record(tmp_path, srv, 1.6, drop_after=2)
        feed.join()
    ends = [r for r in rows if r["t"] == "end"]
    assert ends[0]["reason"] == "drop"
    s = g.check(rows)
    assert s["connections"] >= 2 and s["holes"] == [] and s["stream_ok"] is True


def test_record_keeps_the_last_nonempty_final_snapshot(tmp_path):
    holder = [_hub()]
    calls = []

    def fake_get(url, timeout=5.0):
        if url.endswith("/api/state"):
            return 200, {"mode_key": "client"}
        calls.append(url)
        return (200, {"allPlayers": [{"championName": "Lux"}], "n": len(calls)}) \
            if len(calls) < 3 else (200, {"allPlayers": []})
    with _Server(holder) as srv:
        out = tmp_path / "cap.jsonl"
        g.record(out, base=srv.base, minutes=1.0 / 60.0, final_url="http://x/allgamedata",
                 final_every=0.1, sleep=lambda s: time.sleep(0.05), get_json=fake_get)
    final = json.loads((tmp_path / "cap.jsonl.final.json").read_text(encoding="utf-8"))
    assert final["n"] == 2 and len(calls) >= 3   # the empty body never replaced it
    assert not (tmp_path / "cap.jsonl.final.json.tmp").exists()


def test_record_logs_a_connect_failure_as_its_own_connection(tmp_path):
    def refuse(url, headers, timeout):
        raise ConnectionRefusedError("down")
    out = tmp_path / "c.jsonl"
    g.record(out, minutes=0.3 / 60.0, connect=refuse, sleep=lambda s: time.sleep(0.05))
    rows = g.load_capture(out)
    conns = [r for r in rows if r["t"] == "conn"]
    ends = [r for r in rows if r["t"] == "end"]
    assert conns and len(conns) == len(ends)
    assert all(c["status"] is None for c in conns)
    assert all(e["reason"] == "error:ConnectionRefusedError" for e in ends)


# ------------------------------------------------------- check (hand rows)

def _conn(n, sent, **kw):
    return dict({"t": "conn", "conn": n, "last_event_id": sent, "status": 200,
                 "ctype": "text/event-stream", "replay": None}, **kw)


def _ev(n, i, kind="death", **kw):
    return {"t": "frame", "conn": n, "id": i, "data": dict({"kind": kind, "id": i}, **kw)}


def _end(n, reason="eof", dur=1.0):
    return {"t": "end", "conn": n, "reason": reason, "dur_s": dur}


def _hello(n, head):
    return {"t": "frame", "conn": n, "id": head, "data": {"kind": "hello", "head": head}}


def test_check_counts_a_cap_resume_and_flags_a_skip():
    rows = [_conn(1, None), _hello(1, 10), _ev(1, 11), _end(1, "eof", 600.2),
            _conn(2, "11"), _ev(2, 12), _ev(2, 14, kind="level_up"), _end(2, "deadline")]
    s = g.check(rows)
    assert s["cap_resumes"] == []  # the successor had a hole, so the cap resume does not count
    assert s["holes"] == [{"conn": 2, "why": "skip", "expected": 13, "got": 14}]
    assert s["stream_ok"] is False
    good = rows[:6] + [_ev(2, 13, kind="level_up"), _end(2, "deadline")]
    s = g.check(good)
    assert s["cap_resumes"] == [1] and s["stream_ok"] is True


def test_check_flags_hello_on_reconnect_and_a_wrong_last_event_id():
    rows = [_conn(1, None), _hello(1, 10), _ev(1, 11), _end(1),
            _conn(2, "10"), _hello(2, 11), _end(2)]
    s = g.check(rows)
    assert s["reconnect_hello"] == [2]
    assert s["last_event_id_mismatch"] == [2]
    assert s["stream_ok"] is False


def test_a_ring_overflow_gap_is_not_a_restart():
    small = [_conn(1, None), _hello(1, 10), _ev(1, 11), _end(1),
             _conn(2, "11"), {"t": "frame", "conn": 2, "id": 50,
                              "data": {"kind": "gap", "from": 12, "to": 50}},
             _ev(2, 51), _end(2)]
    s = g.check(small)
    assert s["restart_resumes"] == [] and s["bad_gaps"] == []
    assert s["lost_gaps"] == [{"conn": 2, "from": 12, "to": 50}] and s["stream_ok"] is False
    big = small[:5] + [{"t": "frame", "conn": 2, "id": 99_999,
                        "data": {"kind": "gap", "from": 12, "to": 99_999}},
                       {"t": "state", "conn": 2, "status": 200}, _end(2)]
    s = g.check(big)
    assert s["restart_resumes"] == [2] and s["state_reread_after_restart"] == [200]
    bad = small[:5] + [{"t": "frame", "conn": 2, "id": 60,
                        "data": {"kind": "gap", "from": 30, "to": 60}}, _end(2)]
    assert g.check(bad)["bad_gaps"]


def test_missing_kinds_and_stolen_count():
    rows = [_conn(1, None), _hello(1, 0), _ev(1, 1, kind="objective_taken", stolen=True,
                                              event_id=3), _end(1)]
    s = g.check(rows)
    assert s["missing_kinds"] == ["death", "item_completed", "level_up"]
    assert s["stolen_objectives"] == 1


# ------------------------------------------------------------- cross-check

def _final(events, lux_level=6):
    return {
        "allPlayers": [
            {"championName": "Lux", "summonerName": "SynthLux#T1", "riotIdGameName": "SynthLux",
             "level": lux_level},
            {"championName": "Zed", "summonerName": "SynthZed#T2", "riotIdGameName": "SynthZed",
             "level": 4},
        ],
        "events": {"Events": events},
    }


def _game_rows():
    return [_conn(1, None), _hello(1, 0),
            _ev(1, 1, kind="level_up", champion="Lux", game_time=100.0, **{"from": 3, "to": 4}),
            _ev(1, 2, kind="death", champion="Zed", game_time=121.0),
            _ev(1, 3, kind="objective_taken", game_time=150.0, event_id=9, stolen=True),
            _ev(1, 4, kind="level_up", champion="Lux", game_time=160.0, **{"from": 4, "to": 6}),
            _ev(1, 5, kind="death", champion="Lux", game_time=170.0),
            _ev(1, 6, kind="item_completed", champion="Lux", game_time=200.0, item_id=3031),
            _end(1, "deadline")]


def test_cross_check_passes_a_consistent_game_and_reads_both_name_forms():
    ev = [{"EventName": "ChampionKill", "EventID": 5, "EventTime": 120.4, "VictimName": "SynthZed"},
          {"EventName": "DragonKill", "EventID": 9, "EventTime": 149.6, "Stolen": "True"},
          {"EventName": "ChampionKill", "EventID": 11, "EventTime": 169.2, "VictimName": "Lux"},
          # before the capture window: neither graded nor missing
          {"EventName": "HordeKill", "EventID": 2, "EventTime": 40.0, "Stolen": "False"},
          {"EventName": "ChampionKill", "EventID": 1, "EventTime": 50.0, "VictimName": "Zed"}]
    f = g.check(_game_rows(), _final(ev))["final"]
    assert f["ok"] is True, f
    assert f["objectives_in_window"] == 1
    assert f["victim_name_form"] == {"player": 1, "champion": 2}


def test_cross_check_flags_a_missed_objective_a_stolen_mismatch_and_an_unmatched_death():
    ev = [{"EventName": "DragonKill", "EventID": 9, "EventTime": 149.6, "Stolen": "False"},
          {"EventName": "BaronKill", "EventID": 10, "EventTime": 155.0, "Stolen": "False"},
          {"EventName": "ChampionKill", "EventID": 11, "EventTime": 169.2, "VictimName": "Lux"},
          {"EventName": "ChampionKill", "EventID": 12, "EventTime": 180.0, "VictimName": "Zed"},
          {"EventName": "ChampionKill", "EventID": 13, "EventTime": 181.0, "VictimName": "Nobody"}]
    f = g.check(_game_rows(), _final(ev, lux_level=7))["final"]
    assert f["ok"] is False
    assert f["objectives_missing"] == [{"event_id": 10, "objective": "baron"}]
    assert f["objectives_stolen_mismatch"] == [9]
    # Zed's death at 121 has no kill; the kill at 180 has no death event
    assert f["death_mismatch"] == {"Zed": {"unmatched_deaths": 1, "unmatched_kills": 1}}
    assert f["victim_name_form"]["unmapped"] == 1
    assert f["level_final_mismatch"] == {"Lux": {"last_to": 6, "final": 7}}


def test_cross_check_skips_kills_at_the_window_edges():
    rows = _game_rows()
    ev = [{"EventName": "ChampionKill", "EventID": 5, "EventTime": 120.4, "VictimName": "Zed"},
          {"EventName": "ChampionKill", "EventID": 11, "EventTime": 169.2, "VictimName": "Lux"},
          {"EventName": "ChampionKill", "EventID": 20, "EventTime": 198.0, "VictimName": "Zed"},
          {"EventName": "ChampionKill", "EventID": 21, "EventTime": 101.0, "VictimName": "Lux"},
          {"EventName": "DragonKill", "EventID": 9, "EventTime": 149.6, "Stolen": "True"}]
    f = g.check(rows, _final(ev))["final"]
    assert f["death_mismatch"] == {} and f["ok"] is True


def test_cross_check_flags_a_broken_level_chain():
    rows = _game_rows()
    rows[5] = _ev(1, 4, kind="level_up", champion="Lux", game_time=160.0, **{"from": 5, "to": 6})
    f = g.check(rows, _final([]))["final"]
    assert f["level_chain_breaks"] == ["Lux"]


# -------------------------------------------------------------------- main

def test_main_refuses_an_existing_capture(tmp_path, capsys):
    out = tmp_path / "x.jsonl"
    out.write_text("", encoding="utf-8")
    assert g.main(["record", "--out", str(out), "--minutes", "1"]) == 2
    assert out.read_text(encoding="utf-8") == ""


def test_main_check_prints_champions_never_player_names(tmp_path, capsys):
    cap = tmp_path / "cap.jsonl"
    cap.write_text("".join(json.dumps(r) + "\n" for r in _game_rows()), encoding="utf-8")
    ev = [{"EventName": "ChampionKill", "EventID": 5, "EventTime": 120.4, "VictimName": "SynthZed"}]
    (tmp_path / "cap.jsonl.final.json").write_text(json.dumps(_final(ev)), encoding="utf-8")
    for argv in (["check", str(cap)], ["check", str(cap), "--json"]):
        assert g.main(argv) == 0
        text = capsys.readouterr().out
        assert "final" in text
        assert "SynthZed" not in text and "SynthLux" not in text


@pytest.mark.parametrize("body", ["not json\n", '{"no_t": 1}\n'])
def test_main_check_exit_2_on_an_unreadable_capture(tmp_path, capsys, body):
    cap = tmp_path / "bad.jsonl"
    cap.write_text(body, encoding="utf-8")
    assert g.main(["check", str(cap)]) == 2


def test_check_on_an_empty_capture_is_not_ok():
    assert g.check([])["stream_ok"] is False


def test_constants_track_the_route():
    assert g.CAP_S == rev._SSE_MAX_DURATION_S
    assert g.RESTART_GAP_MIN > hub_mod.RING_MAX


def test_tool_never_imports_a_writer(tmp_path):
    src = Path(g.__file__).read_text(encoding="utf-8")
    for bad in ("restart_trigger", "taskkill", "schtasks", ".unlink(", "shutil"):
        assert bad not in src


def test_a_replay_marked_or_json_connection_fails_the_stream():
    rows = [_conn(1, None, replay="1"), _hello(1, 0), _end(1)]
    s = g.check(rows)
    assert s["replay_conns"] == [1] and s["stream_ok"] is False
    rows = [_conn(1, None, ctype="application/json"), _end(1)]
    s = g.check(rows)
    assert s["non_sse_conns"] == [1] and s["stream_ok"] is False


def test_cross_check_window_stops_at_the_final_snapshot_time():
    # the final poll was taken at 175 s: the kill behind Lux's 170 s death is in it,
    # but a death at 190 s is past what the final file can show and is not graded
    rows = _game_rows()
    rows.insert(-1, _ev(1, 7, kind="death", champion="Zed", game_time=190.0))
    ev = [{"EventName": "ChampionKill", "EventID": 5, "EventTime": 120.4, "VictimName": "Zed"},
          {"EventName": "DragonKill", "EventID": 9, "EventTime": 149.6, "Stolen": "True"},
          {"EventName": "ChampionKill", "EventID": 11, "EventTime": 169.2, "VictimName": "Lux"}]
    fin = dict(_final(ev), gameData={"gameTime": 175.0})
    f = g.check(rows, fin)["final"]
    assert f["window"] == [100.0, 175.0]
    assert f["death_mismatch"] == {} and f["ok"] is True
    f = g.check(rows, _final(ev))["final"]   # no gameData: the 190 s death is graded
    assert f["death_mismatch"] == {"Zed": {"unmatched_deaths": 1, "unmatched_kills": 0}}


# ------------------------------------------------- verifier round-1 regressions

def test_nothing_received_is_not_stream_ok():
    refused = [_conn(1, None, status=None), _end(1, "error:ConnectionRefusedError")]
    full = [_conn(1, None, status=503, ctype="application/json"), _end(1, "status:503")]
    for rows in (refused, full):
        s = g.check(rows)
        assert s["answered_conns"] == [] and s["stream_ok"] is False


def test_a_ring_overflow_gap_is_a_lost_gap_and_fails_the_stream():
    rows = [_conn(1, None), _hello(1, 100), _ev(1, 101),
            {"t": "frame", "conn": 1, "id": 104, "data": {"kind": "gap", "from": 102, "to": 104}},
            _ev(1, 105), _end(1)]
    s = g.check(rows)
    assert s["lost_gaps"] == [{"conn": 1, "from": 102, "to": 104}]
    assert s["restart_resumes"] == [] and s["stream_ok"] is False


def test_an_ahead_gap_mid_connection_is_a_bad_gap():
    rows = [_conn(1, None), _hello(1, 100), _ev(1, 101), _ev(1, 102),
            {"t": "frame", "conn": 1, "id": 90, "data": {"kind": "gap", "from": 80, "to": 90}},
            _end(1)]
    s = g.check(rows)
    assert s["bad_gaps"] and s["restart_resumes"] == [] and s["stream_ok"] is False
    # the same frame as a reconnect's FIRST frame is a restart (the new seed ran behind)
    rows = [_conn(1, None), _hello(1, 100), _ev(1, 101), _end(1),
            _conn(2, "101"),
            {"t": "frame", "conn": 2, "id": 90, "data": {"kind": "gap", "from": 91, "to": 90}},
            {"t": "state", "conn": 2, "status": 200}, _end(2)]
    s = g.check(rows)
    assert s["restart_resumes"] == [2] and s["bad_gaps"] == []


def test_a_superscript_id_line_does_not_crash_record(tmp_path):
    class Resp:
        status = 200

        def __init__(self):
            self.fp = iter_lines([b"id: \xc2\xb2\n", b'data: {"kind":"death","id":1}\n', b"\n"])

        def getheader(self, name):
            return "text/event-stream" if name == "Content-Type" else None

    class Conn:
        def close(self):
            pass

    def iter_lines(lines):
        class F:
            def __init__(self):
                self.lines = list(lines)

            def readline(self):
                return self.lines.pop(0) if self.lines else b""
        return F()

    out = tmp_path / "s.jsonl"
    g.record(out, minutes=0.2 / 60.0, connect=lambda u, h, t: (Conn(), Resp()),
             sleep=lambda s: time.sleep(0.05))
    frames = [r for r in g.load_capture(out) if r["t"] == "frame"]
    assert frames and frames[0]["id"] is None


def test_level_final_compares_the_chain_as_of_the_final_poll():
    rows = [_conn(1, None), _hello(1, 0),
            _ev(1, 1, kind="level_up", champion="Lux", game_time=90.0, **{"from": 5, "to": 6}),
            _ev(1, 2, kind="level_up", champion="Lux", game_time=115.0, **{"from": 6, "to": 7}),
            _end(1, "deadline")]
    # final polled at 105 s shows level 6: the 115 s level-up came after it
    f = g.check(rows, dict(_final([], lux_level=6), gameData={"gameTime": 105.0}))["final"]
    assert f["level_final_mismatch"] == {}
    # a level-up within POLL_LAG_S of the poll is skipped, not graded either way
    f = g.check(rows, dict(_final([], lux_level=7), gameData={"gameTime": 114.0}))["final"]
    assert f["level_final_skipped"] == ["Lux"] and f["level_final_mismatch"] == {}
    # a real miss as of the poll is still caught
    f = g.check(rows, dict(_final([], lux_level=8), gameData={"gameTime": 105.0}))["final"]
    assert f["level_final_mismatch"] == {"Lux": {"last_to": 6, "final": 8}}


# ------------------------------------------------- verifier round-2 regressions

def test_a_cap_close_with_a_dead_successor_is_not_a_cap_resume():
    for nxt in ([_conn(2, "11", status=None), _end(2, "error:ConnectionRefusedError")],
                [_conn(2, "11", status=503, ctype="application/json"), _end(2, "status:503")]):
        rows = [_conn(1, None), _hello(1, 10), _ev(1, 11), _end(1, "eof", 600.2)] + nxt
        assert g.check(rows)["cap_resumes"] == []


def test_a_fresh_hello_after_a_refused_first_connect_is_not_a_resume_failure():
    rows = [_conn(1, None, status=None), _end(1, "error:ConnectionRefusedError"),
            _conn(2, None), _hello(2, 10), _ev(2, 11), _end(2, "deadline")]
    s = g.check(rows)
    assert s["reconnect_hello"] == [] and s["last_event_id_mismatch"] == []
    assert s["stream_ok"] is True


def test_a_repeated_objective_fails_the_stream_and_an_unlogged_one_fails_final():
    rows = _game_rows()
    rows.insert(-1, _ev(1, 7, kind="objective_taken", game_time=160.0, event_id=9, stolen=True))
    s = g.check(rows)
    assert s["duplicate_objective_ids"] == [9] and s["stream_ok"] is False
    rows = _game_rows()
    rows.insert(-1, _ev(1, 7, kind="objective_taken", game_time=180.0, event_id=77, stolen=False))
    ev = [{"EventName": "ChampionKill", "EventID": 5, "EventTime": 120.4, "VictimName": "Zed"},
          {"EventName": "DragonKill", "EventID": 9, "EventTime": 149.6, "Stolen": "True"},
          {"EventName": "ChampionKill", "EventID": 11, "EventTime": 169.2, "VictimName": "Lux"}]
    f = g.check(rows, _final(ev))["final"]
    assert f["objectives_unexpected"] == [77] and f["ok"] is False
    # one that landed after the final poll cannot be judged
    f = g.check(rows, dict(_final(ev), gameData={"gameTime": 181.0}))["final"]
    assert f["objectives_unexpected"] == []
