"""Tests for tools/gated_lx03_session_check.py - the lane-9 read-only reader of
one live-session recording (LX-03, RM-605). One fixture is written by the real
core.live_session_recorder writer thread so the shapes cannot drift from the
recorder; the rest are hand-built lines in the documented file format. Every
game id here is synthetic (RM-906).
"""
from __future__ import annotations

import json
from pathlib import Path

from core import live_session_recorder as lsr
from tools import gated_lx03_session_check as g

_HDR = {"kind": "header", "schema": 1, "config_key": "1920x1080|a=1",
        "patch": "25.21", "ENGINE_VERSION": "9.9", "mode_key": "sr"}


def _frame(seq, gt, cap, vision=False, snap=None):
    f = {"kind": "frame", "seq": seq, "captured_at": cap, "game_time": gt,
         "snapshot": {"gameData": {"gameTime": gt}} if snap is None else snap}
    if vision:
        f["vision_state"] = {"ok": True}
    return f


def _write(path: Path, header, frames) -> Path:
    path.write_text("".join(json.dumps(x) + "\n" for x in [header, *frames]),
                    encoding="utf-8")
    return path


def test_recorder_written_file_round_trips(tmp_path):
    rec = lsr.LiveSessionRecorder(
        tmp_path,
        header_fields=lambda snap: {"config_key": "1920x1080|a=1", "patch": "25.21",
                                    "ENGINE_VERSION": "9.9", "mode_key": "sr"},
        game_id_provider=lambda: "9000000001",
        vision_provider=lambda: {"ok": True},
    )
    try:
        for t in (10.0, 10.5, 11.0):
            rec.record({"gameData": {"gameTime": t}}, ts=1000.0 + t)
        assert rec.flush()
    finally:
        rec.close()
    p = tmp_path / "9000000001.jsonl"
    s = g.check(p, expect_game_id="9000000001", expect_config_key="1920x1080|a=1")
    assert s["stem_kind"] == "gameid"
    assert s["game_id_match"] is True
    assert s["header"]["config_key"] == "1920x1080|a=1"
    assert s["config_key_match"] is True and s["config_key_unknown"] is False
    assert s["frames"] == 3 and s["seq_contiguous"] is True
    assert s["game_time_first"] == 10.0 and s["game_time_last"] == 11.0
    assert s["game_time_backsteps"] == 0 and s["game_time_null"] == 0
    assert s["frames_with_snapshot"] == 3 and s["frames_with_vision_state"] == 3


def test_nogameid_stem_and_unknown_config_key(tmp_path):
    hdr = dict(_HDR, config_key="unknown")
    p = _write(tmp_path / "nogameid-1700000000.jsonl", hdr, [_frame(0, 5.0, 1.0)])
    s = g.check(p, expect_game_id="9000000001", expect_config_key="1920x1080|a=1")
    assert s["stem_kind"] == "nogameid"
    assert s["game_id_match"] is False
    assert s["config_key_unknown"] is True
    assert s["config_key_match"] is False


def test_seq_gap_backstep_null_and_missing_vision(tmp_path):
    frames = [_frame(0, 10.0, 1.0, vision=True), _frame(2, 9.0, 3.0),
              _frame(3, None, 4.0, snap={}), _frame(4, float("nan"), 2.0)]
    p = _write(tmp_path / "9000000002.jsonl", _HDR, frames)
    s = g.check(p)
    assert s["game_id_match"] is None and s["config_key_match"] is None
    assert s["seq_contiguous"] is False
    assert s["game_time_backsteps"] == 1
    assert s["game_time_null"] == 2  # None and NaN
    assert s["captured_span_s"] == 3.0
    assert s["frames_with_snapshot"] == 3
    assert s["frames_with_vision_state"] == 1


def test_main_hides_the_stem_unless_show_id(tmp_path, capsys):
    p = _write(tmp_path / "9000000003.jsonl", _HDR, [_frame(0, 1.0, 1.0)])
    assert g.main([str(p), "--json"]) == 0
    out = capsys.readouterr().out
    assert "9000000003" not in out
    assert json.loads(out)["stem"] is None
    assert g.main([str(p)]) == 0
    assert "9000000003" not in capsys.readouterr().out
    assert g.main([str(p), "--show-id"]) == 0
    assert "stem=9000000003" in capsys.readouterr().out


def test_main_live_config_key_uses_hud_settings(tmp_path, monkeypatch, capsys):
    p = _write(tmp_path / "9000000004.jsonl", _HDR, [_frame(0, 1.0, 1.0)])
    monkeypatch.setattr(g, "live_config_key", lambda: "1920x1080|a=1")
    assert g.main([str(p), "--live-config-key", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["config_key_expected"] == "1920x1080|a=1"
    assert s["config_key_match"] is True


def test_main_refuses_bad_files(tmp_path, capsys):
    assert g.main([str(tmp_path / "missing.jsonl")]) == 2
    bad = tmp_path / "9000000005.jsonl"
    bad.write_text('{"kind":"frame"}\n', encoding="utf-8")
    assert g.main([str(bad)]) == 2
    newer = _write(tmp_path / "9000000006.jsonl", dict(_HDR, schema=99), [])
    assert g.main([str(newer)]) == 2
    err = capsys.readouterr().err
    assert "SchemaTooNewError" in err


def test_output_is_ascii(tmp_path, capsys):
    hdr = dict(_HDR, mode_key="sr" + chr(0xE9))
    p = _write(tmp_path / "9000000007.jsonl", hdr, [_frame(0, 1.0, 1.0)])
    assert g.main([str(p)]) == 0
    capsys.readouterr().out.encode("ascii")


def test_stderr_never_echoes_the_stem(tmp_path, capsys):
    assert g.main([str(tmp_path / "9000000008.jsonl")]) == 2
    assert "9000000008" not in capsys.readouterr().err
