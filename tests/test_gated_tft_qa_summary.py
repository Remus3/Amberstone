"""Tests for tools/gated_tft_qa_summary.py - the lane-9 read-only summary of a
tft_qa recorder match directory. Fixtures copy the record shapes the s134
recorder wrote (states.jsonl state.health.pid / mode_key / lcu.phase, events
ev=game_id with a queue dict, frames kind=dash|game).
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import gated_tft_qa_summary as g


def _state(iso, pid, mode_key, tft_mode, phase="InProgress", callouts=None, lc=None):
    return {"t": 0, "iso": iso, "gt": None, "state": {
        "mode_key": mode_key,
        "health": {"pid": pid, "has_game": False, "tft_mode": tft_mode},
        "coach": {"mode": mode_key},
        "liveclient": lc or {},
        "lcu": {"phase": phase},
        "callouts": callouts or [],
    }}


def _write_jsonl(path: Path, recs) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def _match(tmp_path: Path) -> Path:
    d = tmp_path / "20261025-070350"
    d.mkdir()
    (d / "MATCH_START.json").write_text(json.dumps(
        {"start_iso": "2026-10-25T12:03:50+00:00", "joined_late": True, "mode_key": "tft"}),
        encoding="utf-8")
    dragon = [{"tag": "dragon", "line": "Drake spawns 5:00"}, {"tag": "herald"}]
    _write_jsonl(d / "states.jsonl", [
        _state("t1", 100, "tft", True),
        _state("t2", 100, "tft", True),
        _state("t3", 200, "client", False, callouts=dragon),
        _state("t4", 300, "client", False, callouts=dragon),
        _state("t5", 300, "client", False, phase="EndOfGame"),
    ])
    _write_jsonl(d / "events.jsonl", [
        {"ev": "match_start"},
        {"ev": "game_id", "game_id": 1000000911,
         "queue": {"id": 1090, "gameMode": "TFT", "type": "NORMAL_TFT"}},
        {"ev": "stale_vision_frame", "status": 404},
        {"ev": "stale_vision_frame", "status": 404},
    ])
    _write_jsonl(d / "frames.jsonl", [{"kind": "dash"}, {"kind": "game"}, {"kind": "dash"}])
    return d


def test_pid_changes_count_as_restarts(tmp_path):
    s = g.summarize(_match(tmp_path))
    assert [p["pid"] for p in s["rc_pids"]] == [100, 200, 300]
    assert s["rc_restarts"] == 2


def test_in_progress_not_tft_counts_and_callout_tags(tmp_path):
    s = g.summarize(_match(tmp_path))
    assert s["in_progress_samples"] == 4
    assert s["in_progress_not_tft"] == 2
    assert s["callout_tags_while_not_tft"] == {"dragon": 2, "herald": 2}


def test_mode_timeline_rows_only_on_change(tmp_path):
    s = g.summarize(_match(tmp_path))
    assert [(m["iso"], m["mode_key"], m["lcu_phase"]) for m in s["mode_timeline"]] == [
        ("t1", "tft", "InProgress"),
        ("t3", "client", "InProgress"),
        ("t5", "client", "EndOfGame"),
    ]


def test_game_queue_events_and_frames(tmp_path):
    s = g.summarize(_match(tmp_path))
    assert s["game"]["game_id"] == 1000000911
    assert s["game"]["queue"]["id"] == 1090
    assert s["events"] == {"match_start": 1, "game_id": 1, "stale_vision_frame": 2}
    assert s["frames"] == {"dash": 2, "game": 1}
    assert s["joined_late"] is True


def test_missing_files_and_bad_lines_are_fail_soft(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    (d / "states.jsonl").write_text('{"iso": "t1", "state": {}}\nnot json\n[1]\n',
                                    encoding="utf-8")
    (d / "game_id.txt").write_text("42\n", encoding="utf-8")
    s = g.summarize(d)
    assert s["states"] == 1
    assert s["bad_lines"] == {"states.jsonl": 2}
    assert s["rc_restarts"] == 0
    assert s["game"] == {"game_id": "42"}
    assert s["events"] == {} and s["frames"] == {}


def test_hostile_shapes_and_bytes_are_fail_soft(tmp_path):
    # verifier REFUTED round 1: a non-list callouts, an invalid UTF-8 line and
    # a non-UTF-8 game_id.txt each raised.
    d = tmp_path / "hostile"
    d.mkdir()
    rec = _state("t1", 1, "client", False)
    rec["state"]["callouts"] = 5
    bad_rec = _state("t2", 1, "client", False)
    bad_rec["state"]["callouts"] = {"tag": "dragon"}
    (d / "states.jsonl").write_bytes(
        (json.dumps(rec) + "\n" + json.dumps(bad_rec) + "\n").encode("ascii")
        + b'{"iso": "\xff\xfe"}\n' + b"\xff\xfe{\n")
    (d / "game_id.txt").write_bytes(b"\xff\xfe9\n")
    s = g.summarize(d)
    assert s["in_progress_not_tft"] == 2
    assert s["callout_tags_while_not_tft"] == {}
    assert s["states"] == 3
    assert s["bad_lines"] == {"states.jsonl": 1}
    assert s["game"]["game_id"].endswith("9")
    assert g.render(s).isascii()


def test_deep_nesting_and_bom_are_fail_soft(tmp_path):
    # verifier REFUTED round 2: 200000-deep JSON raised RecursionError, and a
    # UTF-8 BOM silently dropped the first record.
    d = tmp_path / "deep"
    d.mkdir()
    (d / "MATCH_START.json").write_text("[" * 200000, encoding="ascii")
    rec = json.dumps(_state("t1", 7, "tft", True))
    (d / "states.jsonl").write_bytes(
        b"\xef\xbb\xbf" + rec.encode("ascii") + b"\n" + b"[" * 200000 + b"\n")
    s = g.summarize(d)
    assert s["start_iso"] is None
    assert s["states"] == 1
    assert s["rc_pids"] == [{"iso": "t1", "pid": 7}]
    assert s["bad_lines"] == {"states.jsonl": 1}


def test_match_start_bom_and_non_dict_callout_items(tmp_path):
    # verifier round 3: both branches were untested (a revert still passed).
    d = tmp_path / "bom"
    d.mkdir()
    (d / "MATCH_START.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"start_iso": "s0"}).encode("ascii"))
    rec = _state("t1", 1, "client", False, callouts=[5, "x", {"tag": "dragon"}, {}])
    _write_jsonl(d / "states.jsonl", [rec])
    s = g.summarize(d)
    assert s["start_iso"] == "s0"
    assert s["callout_tags_while_not_tft"] == {"dragon": 1}


def test_cli_json_too_deep_to_print_exits_3(tmp_path, monkeypatch, capsys):
    # verifier round 3: a value deep enough to load but not to re-emit made
    # json.dumps raise RecursionError in main().
    d = _match(tmp_path)
    real = g.summarize

    def deep(path):
        s = real(path)
        v: list = []
        for _ in range(100000):
            v = [v]
        s["start_iso"] = v
        return s

    monkeypatch.setattr(g, "summarize", deep)
    assert g.main([str(d), "--json"]) == 3
    assert "not printable" in capsys.readouterr().err


def test_render_is_ascii_and_cli_json(tmp_path, capsys):
    d = _match(tmp_path)
    assert g.render({"match_dir": "x \u00b7 y"}).isascii()
    assert "rc restarts 2" in g.render(g.summarize(d))
    assert g.main([str(d), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rc_restarts"] == 2


def test_cli_rejects_missing_dir(tmp_path):
    assert g.main([str(tmp_path / "nope")]) == 2


def test_summarize_does_not_write(tmp_path):
    d = _match(tmp_path)
    before = {p.name: p.stat().st_mtime_ns for p in d.iterdir()}
    g.summarize(d)
    after = {p.name: p.stat().st_mtime_ns for p in d.iterdir()}
    assert before == after
