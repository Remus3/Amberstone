"""RM-639 (directive X-39): death reel / highlight clips.

Pure window math (bookmarks -> merged video windows) plus a thin ffmpeg runner.
The runner is exercised ONLY against a fake ffmpeg (a monkeypatched subprocess
runner); real ffmpeg is never run on real video here. Every fixture is
synthetic: no Riot IDs, no summoner names, no captured payloads.

Sidecar shape consumed = the RM-637 recorder writer (core/obs_recorder.py
_write_sidecar): schema, status, match_id, owner, obs_output_path,
game_time_offset_s, alignment.anchors[{game_time, offset_s}], death_count,
bookmarks[{event_id, name, game_time, video_time, provisional, own_death}].
The record written back = the RM-640 retention reader's death_reel.path
(core/vod_retention.py rows_from_sidecar).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from core import highlight_reel as hr


def _sidecar(bookmarks, offset=5.0, anchors=None, status="final",
             video="obs/out/match.mkv", deaths=None, match_id="NA1_1001"):
    if anchors is None:
        anchors = [{"game_time": 1.0, "offset_s": offset}]
    return {
        "schema": 1, "status": status, "match_id": match_id,
        "owner": "rc", "obs_output_path": video,
        "game_time_offset_s": offset,
        "alignment": {"proven": True, "method": "x", "anchors": anchors},
        "death_count": (sum(1 for b in bookmarks if isinstance(b, dict) and b.get("own_death"))
                        if deaths is None else deaths),
        "bookmarks": bookmarks,
    }


def _death(t, own=True, eid=None):
    return {"event_id": eid if eid is not None else int(t), "name": "ChampionKill",
            "game_time": float(t), "video_time": 0.0, "provisional": False,
            "own_death": own}


# -- pure: windows ---------------------------------------------------------------


def test_zero_death_path_yields_no_windows():
    side = _sidecar([_death(300, own=False),
                     {"event_id": 7, "name": "DragonKill", "game_time": 600.0,
                      "video_time": 605.0, "provisional": False}])
    assert hr.build_windows(side) == []


def test_offset_mapping_game_time_to_video_time():
    # video_time = game_time + offset (core/vod_alignment.py convention)
    side = _sidecar([_death(300)], offset=12.5)
    (w,) = hr.build_windows(side)
    assert w.start_s == pytest.approx(300 - 20 + 12.5)
    assert w.end_s == pytest.approx(300 + 3 + 12.5)
    assert w.game_start_s == pytest.approx(280.0)
    assert w.game_end_s == pytest.approx(303.0)


def test_offset_uses_anchor_in_force_at_the_death():
    # a pause re-anchors: a death after the second anchor uses its offset
    anchors = [{"game_time": 1.0, "offset_s": 5.0},
               {"game_time": 500.0, "offset_s": 40.0}]
    side = _sidecar([_death(200), _death(900)], anchors=anchors)
    w1, w2 = hr.build_windows(side)
    assert w1.start_s == pytest.approx(185.0)
    assert w2.start_s == pytest.approx(920.0)


def test_offset_falls_back_to_game_time_offset_s_without_anchors():
    side = _sidecar([_death(300)], offset=7.0, anchors=[])
    (w,) = hr.build_windows(side)
    assert w.start_s == pytest.approx(287.0)


def test_clamp_start_at_zero():
    side = _sidecar([_death(10)], offset=2.0)
    (w,) = hr.build_windows(side)
    assert w.start_s == 0.0
    assert w.end_s == pytest.approx(15.0)


def test_window_entirely_before_recording_is_dropped():
    side = _sidecar([_death(10)], offset=-100.0,
                    anchors=[{"game_time": 0.0, "offset_s": -100.0}])
    assert hr.build_windows(side) == []


def test_padding_settings_extend_both_sides():
    s = hr.ReelSettings(pad_before_s=2.0, pad_after_s=4.0)
    (w,) = hr.build_windows(_sidecar([_death(300)], offset=0.0), s)
    assert w.start_s == pytest.approx(278.0)
    assert w.end_s == pytest.approx(307.0)


def test_merge_overlapping_windows():
    # 300 -> [280, 303]; 310 -> [290, 313]: overlap -> one [280, 313]
    side = _sidecar([_death(300), _death(310), _death(600)], offset=0.0)
    ws = hr.build_windows(side)
    assert [(w.start_s, w.end_s) for w in ws] == [(280.0, 313.0), (580.0, 603.0)]
    assert [len(w.events) for w in ws] == [2, 1]


def test_merge_touching_windows_and_unsorted_input():
    a = hr.Window(10.0, 20.0, 10.0, 20.0)
    b = hr.Window(20.0, 30.0, 20.0, 30.0)
    c = hr.Window(0.0, 5.0, 0.0, 5.0)
    out = hr.merge_windows([b, a, c])
    assert [(w.start_s, w.end_s) for w in out] == [(0.0, 5.0), (10.0, 30.0)]


def test_merge_keeps_contained_window_end():
    a = hr.Window(0.0, 100.0, 0.0, 100.0)
    b = hr.Window(10.0, 20.0, 10.0, 20.0)
    (w,) = hr.merge_windows([a, b])
    assert w.end_s == 100.0


def test_non_own_and_non_kill_bookmarks_ignored():
    bms = [_death(300), _death(400, own=False),
           {"event_id": 9, "name": "ChampionKill", "game_time": 500.0,
            "video_time": 0.0, "provisional": False}]
    assert len(hr.build_windows(_sidecar(bms, offset=0.0))) == 1


def test_malformed_bookmarks_fail_soft():
    bms = [None, "x", {"name": "ChampionKill", "own_death": True,
                       "game_time": "nope"}, _death(300)]
    assert len(hr.build_windows(_sidecar(bms, offset=0.0))) == 1


# -- pure: PGR annotation ----------------------------------------------------------


def _pgr(lines):
    return {"participant_id": 1, "view": "cost", "lines": lines}


def test_annotation_attaches_pgr_line_inside_window():
    rep = _pgr([{"criterion": "death_cost", "t_ms": 301_000, "magnitude_gold": 300},
                {"criterion": "death_cost", "t_ms": 900_000, "magnitude_gold": 150}])
    (w,) = hr.build_windows(_sidecar([_death(300)], offset=0.0), pgr_report=rep)
    assert [a["t_ms"] for a in w.annotations] == [301_000]
    assert w.annotations[0]["criterion"] == "death_cost"


def test_annotation_absent_is_empty_not_invented():
    (w,) = hr.build_windows(_sidecar([_death(300)], offset=0.0),
                            pgr_report=_pgr([]))
    assert w.annotations == ()
    (w2,) = hr.build_windows(_sidecar([_death(300)], offset=0.0))
    assert w2.annotations == ()


def test_annotation_union_on_merge_sorted_and_deduped():
    line = {"criterion": "death_cost", "t_ms": 305_000, "magnitude_gold": 1}
    rep = _pgr([{"criterion": "death_cost", "t_ms": 311_000, "magnitude_gold": 2},
                line])
    side = _sidecar([_death(300), _death(310)], offset=0.0)
    (w,) = hr.build_windows(side, pgr_report=rep)
    assert [a["t_ms"] for a in w.annotations] == [305_000, 311_000]


def test_annotation_is_a_copy():
    line = {"criterion": "death_cost", "t_ms": 300_000, "magnitude_gold": 1}
    (w,) = hr.build_windows(_sidecar([_death(300)], offset=0.0),
                            pgr_report=_pgr([line]))
    w.annotations[0]["criterion"] = "changed"
    assert line["criterion"] == "death_cost"


def test_video_time_for_seeks_a_pgr_row():
    side = _sidecar([], offset=4.0)
    assert hr.video_time_for(side, 120.0) == pytest.approx(124.0)
    assert hr.video_time_for(_sidecar([], offset=-50.0,
                                      anchors=[{"game_time": 0, "offset_s": -50.0}]),
                             10.0) == 0.0


def test_replay_buffer_hook_is_descriptor_only():
    d = hr.replay_buffer_request(_death(300))
    assert d == {"request": "SaveReplayBuffer", "game_time": 300.0,
                 "after_s": hr.REPLAY_BUFFER_DELAY_S}
    assert hr.replay_buffer_request(_death(300, own=False)) is None


# -- thin IO: runner with a FAKE ffmpeg ---------------------------------------------


class FakeFF:
    """Stands in for subprocess.run. Writes the output file the real tool would."""

    def __init__(self, fail_on=None, probe_out="23.000000\n", seg_bytes=b"seg"):
        self.calls = []
        self.fail_on = fail_on
        self.probe_out = probe_out
        self.seg_bytes = seg_bytes

    def __call__(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        exe = Path(cmd[0]).stem.lower()
        if exe == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, self.probe_out.encode(), b"")
        is_concat = "concat" in cmd
        if self.fail_on == ("concat" if is_concat else "cut"):
            return subprocess.CompletedProcess(cmd, 1, b"", b"boom")
        out = Path(cmd[-1])
        out.write_bytes(self.seg_bytes * (3 if is_concat else 1))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")


def _write_side(tmp_path, side):
    rec = tmp_path / "recordings"
    rec.mkdir(exist_ok=True)
    src = tmp_path / "match.mkv"
    src.write_bytes(b"video")
    side["obs_output_path"] = str(src)
    p = rec / f"{side['match_id']}.json"
    p.write_text(json.dumps(side), encoding="ascii")
    return p


def _tools(tmp_path):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    ff = d / "ffmpeg.exe"
    fp = d / "ffprobe.exe"
    ff.write_bytes(b"")
    fp.write_bytes(b"")
    return str(ff), str(fp)


def test_runner_ffmpeg_missing_does_nothing(tmp_path, monkeypatch):
    p = _write_side(tmp_path, _sidecar([_death(300)]))
    before = p.read_bytes()
    monkeypatch.setattr(hr, "locate_ffmpeg", lambda *a, **k: None)
    fake = FakeFF()
    prog = []
    res = hr.build_reel(p, runner=fake, progress=prog.append)
    assert res.status == "ffmpeg_missing"
    assert fake.calls == []
    assert p.read_bytes() == before
    assert not (p.parent / "NA1_1001").exists()


def test_runner_two_segments_concat_faststart_and_sidecar_record(tmp_path):
    side = _sidecar([_death(300), _death(600)], offset=0.0)
    p = _write_side(tmp_path, side)
    ff, fp = _tools(tmp_path)
    fake = FakeFF()
    prog = []
    res = hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=fake, progress=prog.append)
    assert res.status == "ok", res
    out = p.parent / "NA1_1001" / "deaths.mp4"
    assert Path(res.path) == out and out.stat().st_size > 0
    cuts = [c for c, _ in fake.calls if Path(c[0]).stem == "ffmpeg" and "concat" not in c]
    concats = [c for c, _ in fake.calls if "concat" in c]
    assert len(cuts) == 2 and len(concats) == 1
    for c in cuts + concats:
        assert c[c.index("-c") + 1] == "copy"            # stream copy
    assert "+faststart" in concats[0]
    assert cuts[0][cuts[0].index("-ss") + 1] == "280.000"
    assert cuts[0][cuts[0].index("-t") + 1] == "23.000"
    for _, kw in fake.calls:
        assert kw.get("creationflags") == hr.CREATE_NO_WINDOW
    # temp files cleaned in finally
    assert sorted(x.name for x in out.parent.iterdir()) == ["deaths.mp4"]
    doc = json.loads(p.read_text(encoding="ascii"))
    reel = doc["death_reel"]
    assert reel["path"] == str(out)
    assert reel["size_bytes"] == out.stat().st_size
    assert reel["duration_s"] == pytest.approx(23.0)
    assert reel["read_back_ok"] is True
    assert reel["segments"] == 2
    assert doc["bookmarks"] == side["bookmarks"]       # recorder keys untouched
    assert prog[-1] == 100 and -1 not in prog


def test_runner_single_segment_moved_not_concatenated(tmp_path):
    p = _write_side(tmp_path, _sidecar([_death(300)], offset=0.0))
    ff, fp = _tools(tmp_path)
    fake = FakeFF()
    res = hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=fake)
    assert res.status == "ok"
    assert not any("concat" in c for c, _ in fake.calls)
    cut = next(c for c, _ in fake.calls if Path(c[0]).stem == "ffmpeg")
    assert "+faststart" in cut
    out = p.parent / "NA1_1001" / "deaths.mp4"
    assert out.read_bytes() == b"seg"
    assert sorted(x.name for x in out.parent.iterdir()) == ["deaths.mp4"]


def test_runner_zero_deaths_records_status_and_runs_nothing(tmp_path):
    p = _write_side(tmp_path, _sidecar([], deaths=0))
    ff, fp = _tools(tmp_path)
    fake = FakeFF()
    res = hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=fake)
    assert res.status == "no_deaths"
    assert fake.calls == []
    doc = json.loads(p.read_text(encoding="ascii"))
    assert doc["death_reel"]["status"] == "no_deaths"
    assert doc["death_reel"].get("path") is None


def test_runner_error_progress_minus_one_and_temp_cleaned(tmp_path):
    p = _write_side(tmp_path, _sidecar([_death(300), _death(600)], offset=0.0))
    before = p.read_bytes()
    ff, fp = _tools(tmp_path)
    prog = []
    res = hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=FakeFF(fail_on="concat"),
                        progress=prog.append)
    assert res.status == "error"
    assert prog[-1] == -1
    d = p.parent / "NA1_1001"
    assert not d.exists() or list(d.iterdir()) == []
    assert p.read_bytes() == before


def test_runner_empty_output_fails_read_back(tmp_path):
    p = _write_side(tmp_path, _sidecar([_death(300)], offset=0.0))
    before = p.read_bytes()
    ff, fp = _tools(tmp_path)
    res = hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=FakeFF(seg_bytes=b""))
    assert res.status == "read_back_failed"
    assert p.read_bytes() == before
    assert not (p.parent / "NA1_1001" / "deaths.mp4").exists()


def test_runner_without_ffprobe_records_size_only(tmp_path):
    p = _write_side(tmp_path, _sidecar([_death(300)], offset=0.0))
    ff, _ = _tools(tmp_path)
    res = hr.build_reel(p, ffmpeg=ff, ffprobe=None, runner=FakeFF())
    assert res.status == "ok"
    reel = json.loads(p.read_text(encoding="ascii"))["death_reel"]
    assert reel["duration_s"] is None and reel["size_bytes"] > 0


def test_runner_refuses_non_final_and_missing_source(tmp_path):
    ff, fp = _tools(tmp_path)
    p = _write_side(tmp_path, _sidecar([_death(300)], status="recording"))
    assert hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=FakeFF()).status == "not_final"
    side = _sidecar([_death(300)], match_id="NA1_2")
    p2 = _write_side(tmp_path, side)
    doc = json.loads(p2.read_text(encoding="ascii"))
    doc["obs_output_path"] = None                      # operator-owned
    p2.write_text(json.dumps(doc), encoding="ascii")
    assert hr.build_reel(p2, ffmpeg=ff, ffprobe=fp, runner=FakeFF()).status == "no_source"
    doc["obs_output_path"] = str(tmp_path / "gone.mkv")
    p2.write_text(json.dumps(doc), encoding="ascii")
    assert hr.build_reel(p2, ffmpeg=ff, ffprobe=fp,
                         runner=FakeFF()).status == "source_missing"


def test_runner_match_id_is_sanitised(tmp_path):
    side = _sidecar([_death(300)], offset=0.0, match_id="..\\..\\evil")
    p = _write_side(tmp_path, dict(side, match_id="safe"))
    doc = json.loads(p.read_text(encoding="ascii"))
    doc["match_id"] = "..\\..\\evil"
    p.write_text(json.dumps(doc), encoding="ascii")
    ff, fp = _tools(tmp_path)
    res = hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=FakeFF())
    assert res.status == "ok"
    assert Path(res.path).parent.parent == p.parent
    assert Path(res.path).parent.name == "evil"


def test_record_is_what_retention_reads_back(tmp_path):
    """The written record satisfies the RM-640 reader's check: death_reel.path
    stats to a size > 0 (core/vod_retention.py rows_from_sidecar)."""
    p = _write_side(tmp_path, _sidecar([_death(300)], offset=0.0))
    ff, fp = _tools(tmp_path)
    hr.build_reel(p, ffmpeg=ff, ffprobe=fp, runner=FakeFF())
    doc = json.loads(p.read_text(encoding="ascii"))
    reel = doc.get("death_reel")
    reel_path = reel.get("path") if isinstance(reel, dict) else None
    size = os.stat(str(reel_path)).st_size if reel_path else None
    assert bool(size) and size > 0


# -- locate ----------------------------------------------------------------------------


def test_locate_prefers_config_path_then_path(tmp_path):
    ff, _ = _tools(tmp_path)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"obs": {"record": {"ffmpeg_path": ff}}}), encoding="ascii")
    assert hr.locate_ffmpeg(cfg, which=lambda n: None) == ff
    assert hr.locate_ffmpeg(tmp_path / "none.json",
                            which=lambda n: "onpath/ffmpeg.exe") == "onpath/ffmpeg.exe"
    assert hr.locate_ffmpeg(tmp_path / "none.json", which=lambda n: None) is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"obs": {"record": {"ffmpeg_path": str(tmp_path / "no.exe")}}}),
                   encoding="ascii")
    assert hr.locate_ffmpeg(bad, which=lambda n: None) is None


def test_locate_ffprobe_sibling_of_ffmpeg(tmp_path):
    ff, fp = _tools(tmp_path)
    assert hr.locate_ffprobe(ff, which=lambda n: None) == fp
    assert hr.locate_ffprobe(None, which=lambda n: None) is None
