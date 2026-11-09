"""RM-638 (directive X-38, external reference C) - "mark this moment" store.

core/moment_marks.py is the pure-ish half of the in-game mark hotkey:
  - build_mark: one {game_id, game_time_s, wall_ts} row from a :2999
    /liveclientdata/gamestats payload (None when gameTime is unusable),
  - append_mark: one JSON line per mark through the FILE_APPEND_DATA helper
    core/operator_notify.py already owns,
  - attach_for_game: the post-game collector's call - pick the just-ended
    game's marks (exact game_id, or game_id null and wall_ts inside the
    game's wall window) and write one per-game pin file,
  - pins_for_match: what the PGR / Replay routes read back for a match_id.

All fixtures are synthetic. No live path is touched: every call passes an
explicit tmp path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import moment_marks as mm  # noqa: E402


# -- build_mark ---------------------------------------------------------------

def test_build_mark_shape_and_keys():
    m = mm.build_mark({"gameTime": 612.4567, "gameMode": "CLASSIC"},
                      game_id="7001", wall_ts=1_700_000_000.12345)
    assert list(m.keys()) == ["game_id", "game_time_s", "wall_ts"]
    assert m == {"game_id": "7001", "game_time_s": 612.457,
                 "wall_ts": 1_700_000_000.123}


def test_build_mark_null_game_id_when_unknown():
    for gid in (None, "", "0", 0):
        assert mm.build_mark({"gameTime": 5.0}, game_id=gid,
                             wall_ts=1.0)["game_id"] is None


def test_build_mark_rejects_unusable_game_time():
    for bad in ({}, {"gameTime": None}, {"gameTime": "x"},
                {"gameTime": float("nan")}, {"gameTime": -1.0}, [], None):
        assert mm.build_mark(bad, game_id="1", wall_ts=1.0) is None


# -- append format ------------------------------------------------------------

def test_append_writes_one_json_line_per_mark(tmp_path):
    p = tmp_path / "moment_marks.jsonl"
    mm.append_mark({"game_id": "7001", "game_time_s": 1.5, "wall_ts": 10.0}, p)
    mm.append_mark({"game_id": None, "game_time_s": 2.5, "wall_ts": 11.0}, p)
    raw = p.read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    lines = raw.decode("ascii").splitlines()
    assert [json.loads(x) for x in lines] == [
        {"game_id": "7001", "game_time_s": 1.5, "wall_ts": 10.0},
        {"game_id": None, "game_time_s": 2.5, "wall_ts": 11.0},
    ]


def test_append_uses_the_shared_file_append_data_helper(tmp_path, monkeypatch):
    calls = []
    from core import operator_notify
    monkeypatch.setattr(operator_notify, "_win32_append",
                        lambda path, data: calls.append((Path(path), data)))
    # Fake the host through operator_notify's seam, never os.name: patching the
    # global os.name to "nt" makes pathlib build WindowsPath on a Linux runner
    # ("cannot instantiate 'WindowsPath' on your system").
    monkeypatch.setattr(operator_notify, "_on_windows", lambda: True)
    p = tmp_path / "m.jsonl"
    mm.append_mark({"game_id": None, "game_time_s": 1.0, "wall_ts": 2.0}, p)
    assert calls == [(p, b'{"game_id": null, "game_time_s": 1.0, "wall_ts": 2.0}\n')]


def test_append_off_windows_uses_the_portable_o_append_helper(tmp_path, monkeypatch):
    calls = []
    from core import operator_notify
    monkeypatch.setattr(operator_notify, "_portable_append",
                        lambda path, data: calls.append((Path(path), data)))
    monkeypatch.setattr(operator_notify, "_win32_append",
                        lambda path, data: pytest.fail("win32 path off Windows"))
    monkeypatch.setattr(operator_notify, "_on_windows", lambda: False)
    p = tmp_path / "m.jsonl"
    mm.append_mark({"game_id": "1", "game_time_s": 1.0, "wall_ts": 2.0}, p)
    assert calls == [(p, b'{"game_id": "1", "game_time_s": 1.0, "wall_ts": 2.0}\n')]


def test_read_marks_skips_malformed_lines(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_bytes(b'{"game_id": "1", "game_time_s": 3.0, "wall_ts": 9.0}\n'
                  b'not json\n[1,2]\n{"game_id": "1"}\n\n')
    assert mm.read_marks(p) == [{"game_id": "1", "game_time_s": 3.0, "wall_ts": 9.0}]
    assert mm.read_marks(tmp_path / "missing.jsonl") == []


# -- attach-by-game -----------------------------------------------------------

def _seed(p: Path, rows):
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="ascii")


def test_attach_selects_exact_id_and_null_id_inside_window(tmp_path):
    marks = tmp_path / "m.jsonl"
    out = tmp_path / "by_game"
    ended = 10_000.0
    _seed(marks, [
        {"game_id": "7001", "game_time_s": 120.0, "wall_ts": 8_300.0},  # exact
        {"game_id": None, "game_time_s": 60.0, "wall_ts": 8_250.0},     # in window
        {"game_id": "6999", "game_time_s": 30.0, "wall_ts": 8_400.0},   # other game
        {"game_id": None, "game_time_s": 5.0, "wall_ts": 1_000.0},      # long before
        {"game_id": None, "game_time_s": 5.0, "wall_ts": 20_000.0},     # after end
    ])
    pins = mm.attach_for_game("7001", game_length_s=1_800, ended_at=ended,
                              marks_file=marks, out_dir=out)
    assert [p["game_time_s"] for p in pins] == [60.0, 120.0]   # clock-asc
    assert all(p["label"] == "you flagged" for p in pins)
    assert [p["clock_s"] for p in pins] == [60, 120]
    doc = json.loads((out / "7001.json").read_text(encoding="ascii"))
    assert doc["game_id"] == "7001" and doc["pins"] == pins


def test_attach_window_edges_use_the_slack(tmp_path):
    marks = tmp_path / "m.jsonl"
    ended, length = 10_000.0, 1_000
    start = ended - length - mm.ATTACH_SLACK_S
    _seed(marks, [
        {"game_id": None, "game_time_s": 1.0, "wall_ts": start},        # edge in
        {"game_id": None, "game_time_s": 2.0, "wall_ts": start - 1.0},  # out
    ])
    pins = mm.attach_for_game("7001", length, ended, marks_file=marks,
                              out_dir=tmp_path / "o")
    assert [p["game_time_s"] for p in pins] == [1.0]


def test_attach_with_no_marks_writes_nothing(tmp_path):
    out = tmp_path / "o"
    assert mm.attach_for_game("7001", 1_800, 10_000.0,
                              marks_file=tmp_path / "none.jsonl", out_dir=out) == []
    assert not out.exists()


def test_attach_refuses_a_non_numeric_game_id(tmp_path):
    marks = tmp_path / "m.jsonl"
    _seed(marks, [{"game_id": None, "game_time_s": 1.0, "wall_ts": 9_999.0}])
    for gid in ("", None, "0", "..\\x", "NA1_5"):
        assert mm.attach_for_game(gid, 100, 10_000.0, marks_file=marks,
                                  out_dir=tmp_path / "o") == []
    assert not (tmp_path / "o").exists()


# -- pins_for_match (route read side) -----------------------------------------

def test_pins_for_match_accepts_platform_prefixed_and_bare_ids(tmp_path):
    marks = tmp_path / "m.jsonl"
    _seed(marks, [{"game_id": "7001", "game_time_s": 42.0, "wall_ts": 1.0}])
    mm.attach_for_game("7001", 100, 50.0, marks_file=marks, out_dir=tmp_path)
    assert [p["clock_s"] for p in mm.pins_for_match("NA1_7001", tmp_path)] == [42]
    assert [p["clock_s"] for p in mm.pins_for_match("7001", tmp_path)] == [42]
    assert mm.pins_for_match("NA1_7002", tmp_path) == []


def test_pins_for_match_rejects_traversal_and_garbage(tmp_path):
    for mid in ("", "../7001", "NA1_..\\7001", "NA1_", "abc", None):
        assert mm.pins_for_match(mid, tmp_path) == []
    (tmp_path / "7001.json").write_text("{not json", encoding="ascii")
    assert mm.pins_for_match("7001", tmp_path) == []


# -- env defaults + RM-637 hook ----------------------------------------------

def test_default_paths_follow_env_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv(mm.MARKS_ENV, str(tmp_path / "a.jsonl"))
    monkeypatch.setenv(mm.ATTACHED_ENV, str(tmp_path / "b"))
    assert mm.marks_path() == tmp_path / "a.jsonl"
    assert mm.attached_dir() == tmp_path / "b"
    monkeypatch.delenv(mm.MARKS_ENV)
    assert mm.marks_path().as_posix().endswith("ops/runtime/moment_marks.jsonl")


def test_replay_buffer_hook_is_a_no_op_until_rm637():
    # Named hook for the future SaveReplayBuffer call; must not reach OBS now.
    assert mm.request_replay_buffer_save(
        {"game_id": None, "game_time_s": 1.0, "wall_ts": 2.0}) is False


# -- S144-T true-audit (cycle 239): rows the readers reject never get written --
#
# read_marks_strict raises MarksUnreadable on ANY line that is not a well-formed
# mark row, so one bad append poisons every later strict read for good (the
# RM-640 VOD retention then can never prove a zero mark count). These pin that
# the write side refuses exactly what the read side rejects.

def test_build_mark_rejects_an_unusable_wall_ts():
    # Before: None / "x" raised TypeError / ValueError out of build_mark, and
    # nan / inf produced a row json.dumps writes as NaN / Infinity.
    for bad in (None, "x", float("nan"), float("inf"), float("-inf"), True):
        assert mm.build_mark({"gameTime": 5.0}, game_id="7001", wall_ts=bad) is None


@pytest.mark.parametrize("bad", [
    {"game_id": "7001", "game_time_s": float("nan"), "wall_ts": 1.0},
    {"game_id": "7001", "game_time_s": 1.0, "wall_ts": float("inf")},
    {"game_id": "7001", "game_time_s": 1.0},
    {"game_id": "7001", "wall_ts": 1.0},
    {"game_id": "7001", "game_time_s": None, "wall_ts": 1.0},
    {"game_id": "7001", "game_time_s": True, "wall_ts": 1.0},
    ["7001", 1.0, 1.0],
    None,
])
def test_append_refuses_a_row_the_strict_reader_would_reject(tmp_path, bad):
    p = tmp_path / "m.jsonl"
    with pytest.raises(ValueError):
        mm.append_mark(bad, p)
    assert not p.exists()


def test_a_refused_append_leaves_the_strict_read_provable(tmp_path):
    p = tmp_path / "m.jsonl"
    mm.append_mark({"game_id": "7001", "game_time_s": 1.0, "wall_ts": 2.0}, p)
    with pytest.raises(ValueError):
        mm.append_mark({"game_id": "7001", "game_time_s": float("nan"),
                        "wall_ts": 3.0}, p)
    assert mm.read_marks_strict(p) == [
        {"game_id": "7001", "game_time_s": 1.0, "wall_ts": 2.0}]


def test_append_writes_the_canonical_row_only(tmp_path):
    p = tmp_path / "m.jsonl"
    mm.append_mark({"game_id": 7001, "game_time_s": 1, "wall_ts": 2.0,
                    "extra": float("nan")}, p)
    assert p.read_bytes() == b'{"game_id": "7001", "game_time_s": 1.0, "wall_ts": 2.0}\n'
    mm.append_mark({"game_id": "junk", "game_time_s": 1.0, "wall_ts": 2.0}, p)
    assert mm.read_marks_strict(p)[1]["game_id"] is None


# -- pins_for_match: a corrupt pin file cannot break the route's JSON ----------

def test_pins_for_match_drops_non_finite_and_malformed_pins(tmp_path):
    # json.loads accepts NaN / Infinity, and the Replay / PGR routes serialise
    # the pins with a default json.dumps, which writes them back as bare NaN -
    # invalid JSON that makes the browser's JSON.parse reject the whole payload.
    (tmp_path / "7001.json").write_text(
        '{"game_id": "7001", "pins": ['
        '{"clock_s": 1, "game_time_s": NaN, "wall_ts": 1.0, "label": "you flagged"},'
        '{"clock_s": 2, "game_time_s": 2.5, "wall_ts": Infinity, "label": "you flagged"},'
        '{"clock_s": 3, "game_time_s": "3", "wall_ts": 1.0},'
        '{"clock_s": 4, "game_time_s": 4.5, "wall_ts": 9.0, "label": "you flagged",'
        ' "extra": NaN}'
        ']}', encoding="ascii")
    pins = mm.pins_for_match("NA1_7001", tmp_path)
    # The numeric-string pin is kept, rebuilt as numbers (the same _finite rule
    # every reader here applies); the extra NaN key is dropped with the rebuild.
    assert pins == [{"clock_s": 3, "game_time_s": 3.0, "wall_ts": 1.0,
                     "label": "you flagged"},
                    {"clock_s": 4, "game_time_s": 4.5, "wall_ts": 9.0,
                     "label": "you flagged"}]
    json.dumps(pins, allow_nan=False)   # strict JSON round-trips


# -- attach window: an implausible game length is clamped ----------------------

def test_attach_clamps_an_implausible_game_length(tmp_path):
    # Match-V5 gameDuration was MILLISECONDS before patch 11.20; a length in ms
    # would open a window weeks wide and attach every null-gameId mark ever
    # pressed. The window's lower edge is capped at MAX_GAME_LENGTH_S.
    marks = tmp_path / "m.jsonl"
    ended = 10_000_000.0
    _seed(marks, [
        {"game_id": None, "game_time_s": 7.0, "wall_ts": ended - 600.0},
        {"game_id": None, "game_time_s": 8.0, "wall_ts": ended - 86_400.0 * 3},
    ])
    pins = mm.attach_for_game("7001", 1_800_000, ended, marks_file=marks,
                              out_dir=tmp_path / "o")
    assert [p["game_time_s"] for p in pins] == [7.0]
    edge = ended - mm.MAX_GAME_LENGTH_S - mm.ATTACH_SLACK_S
    _seed(marks, [{"game_id": None, "game_time_s": 9.0, "wall_ts": edge},
                  {"game_id": None, "game_time_s": 10.0, "wall_ts": edge - 1.0}])
    pins = mm.attach_for_game("7002", 1e9, ended, marks_file=marks,
                              out_dir=tmp_path / "o")
    assert [p["game_time_s"] for p in pins] == [9.0]


def test_select_marks_skips_rows_without_a_usable_wall_ts():
    rows = [{"game_id": None}, "junk", None, {"game_id": None, "wall_ts": "x"},
            {"game_id": None, "wall_ts": 5.0, "game_time_s": 1.0}]
    assert mm.select_marks_for_game(rows, "7001", 0.0, 10.0) == [rows[-1]]
