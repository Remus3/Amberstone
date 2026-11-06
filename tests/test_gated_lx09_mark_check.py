"""tests for tools/gated_lx09_mark_check.py (LX-09, RM-638 mark-this-moment drain grader).

Mark rows are written by the REAL core.moment_marks build_mark + append_mark and
the pin file by the REAL attach_for_game, all into tmp_path. Log lines are built
in the listener's own logging format, and the fragments the grader matches are
pinned against the text of tools/hotkey_listener.py. The game id is a
hand-written synthetic value (RM-906).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from core import moment_marks
from tools import gated_lx09_mark_check as lx

ROOT = Path(__file__).resolve().parent.parent
GID = "4242424242"
OTHER = "5151515151"
BASE = 1_790_000_000.0          # wall time of game clock zero in the fixtures
SINCE, UNTIL = BASE - 120.0, BASE + 1500.0


def _stamp(t: float) -> str:
    ms = round((t - int(t)) * 1000)
    return datetime.fromtimestamp(int(t)).strftime("%Y-%m-%d %H:%M:%S") + f",{ms:03d}"


def _rec_line(t: float, gid, gt: float) -> str:
    return f"{_stamp(t)} INFO moment mark: game_id={gid} game_time_s={gt:.1f}"


def _start_line(t: float, with_k: bool = True) -> str:
    keys = "Ctrl+Shift+1 / Ctrl+Shift+A / " + ("Ctrl+Shift+K / " if with_k else "") + "Ctrl+Shift+O"
    return f"{_stamp(t)} INFO hotkey_listener starting ({keys}, WH_KEYBOARD_LL)"


def _drop_line(t: float, reason: str = ":2999 gamestats unavailable (HTTP Error 404)") -> str:
    return f"{_stamp(t)} INFO moment mark dropped: {reason}"


def _game(tmp_path, gids=(GID, GID, GID), times=(65.0, 420.5, 1210.25), lag=0.2,
          drop_ts=(BASE - 30.0,), attach=True, start_k=True):
    marks = tmp_path / "moment_marks.jsonl"
    pins = tmp_path / "by_game"
    log = tmp_path / "hotkey_listener.log"
    lines = [_start_line(BASE - 3600.0, start_k)]
    lines += [_drop_line(t) for t in drop_ts]
    for gid, gt in zip(gids, times):
        wall = BASE + gt - lag
        mark = moment_marks.build_mark({"gameTime": gt}, gid, wall)
        moment_marks.append_mark(mark, marks)
        lines.append(_rec_line(wall + 0.05, mark["game_id"], gt))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if attach:
        moment_marks.attach_for_game(GID, 1300.0, BASE + 1310.0, marks_file=marks, out_dir=pins)
    return marks, pins, log


GAME_START = BASE - 90.0        # first InProgress: the loading screen runs from here


def _grade(marks, pins, log, gid=GID, expect=None, since=SINCE, until=UNTIL,
           game_start=GAME_START):
    logs = [str(log)] if log is not None else []
    return lx.grade(marks, pins, logs, since, until, gid, expect, game_start, "flag")


# -- the fragments are the listener's own text ----------------------------------------

def test_fragments_are_verbatim_in_the_listener_source():
    src = (ROOT / "tools" / "hotkey_listener.py").read_text(encoding="utf-8")
    # The start line is split over adjacent string literals; join them first.
    src = re.sub(r'"\s*\n\s*"', "", src)
    assert "hotkey_listener starting (Ctrl+Shift+1" in src
    for frag in (lx.START_FRAG, lx.CHORD_FRAG, *lx.DROP_KINDS.values()):
        assert frag in src, frag
    for frag in lx.OTHER_FRAGS.values():
        assert frag in src, frag
    fmt = "moment mark: game_id=%s game_time_s=%.1f"
    assert fmt in src
    m = lx.RECORDED_RE.search(fmt % (GID, 12.34))
    assert m and m.group(1) == GID and float(m.group(2)) == 12.3
    assert lx.RECORDED_RE.search(fmt % (None, 0.0)).group(1) == "None"


def test_log_format_matches_the_listener_formatter():
    src = (ROOT / "tools" / "hotkey_listener.py").read_text(encoding="utf-8")
    assert '"%(asctime)s %(levelname)s %(message)s"' in src
    assert lx._line_time(_rec_line(BASE + 1.5, GID, 1.0)) == pytest.approx(BASE + 1.5, abs=0.002)
    assert lx._line_time("no stamp here") is None


# -- a clean real-game shape -------------------------------------------------------------

def test_clean_game_grades_every_part(tmp_path):
    s = _grade(*_game(tmp_path), expect=4)
    m = s["marks"]
    assert m["verdict"] == "REAL_ID" and m["rows_in_window"] == 3
    assert m["id_roles"] == {"match": 3, "other": 0, "null": 0}
    assert m["clock_zero"] == pytest.approx(BASE - 0.2, abs=0.01)
    assert m["offset_consistent"] is True and m["near_zero"] == 0 and m["strict"] == "ok"
    lg = s["log"]
    assert lg["recorded"] == 3 and lg["dropped"]["gamestats_unavailable"] == 1
    assert lg["load_drop"] == "LOAD_DROP_SEEN"
    assert lg["drops"][0]["vs_clock_zero"] == "before"
    assert lg["drops"][0]["minus_clock_zero_s"] == pytest.approx(-29.8, abs=0.1)
    assert lg["listener_start_lists_chord"] is True and lg["listener_starts_in_window"] == 0
    assert s["rows_vs_log"] == "AGREE"
    assert s["presses"] == {"expected": 4, "seen": 4, "verdict": "MATCH"}
    a = s["attach"]
    assert a["verdict"] == "ATTACHED" and a["pins"] == 3 and a["expected"] == 3
    assert a["labels_ok"] and a["clock_s_ok"]
    assert a["attached_after_last_mark_s"] > 0


def test_null_id_rows_attach_by_wall_window(tmp_path):
    s = _grade(*_game(tmp_path, gids=(None, None, None)))
    assert s["marks"]["verdict"] == "NULL_ONLY"
    assert s["log"]["recorded_roles"]["null"] == 3
    assert s["attach"]["verdict"] == "ATTACHED"


def test_a_foreign_id_is_wrong_id_and_never_attached(tmp_path):
    s = _grade(*_game(tmp_path, gids=(GID, OTHER, GID)))
    assert s["marks"]["verdict"] == "WRONG_ID"
    assert s["marks"]["id_roles"]["other"] == 1
    a = s["attach"]
    assert a["verdict"] == "ATTACHED" and a["expected"] == 2 and a["pins"] == 2


def test_match_plus_null_is_mixed(tmp_path):
    s = _grade(*_game(tmp_path, gids=(GID, None, GID)))
    assert s["marks"]["verdict"] == "MIXED"


def test_without_game_id_the_id_check_is_coarse_and_attach_unknown(tmp_path):
    s = _grade(*_game(tmp_path), gid=None)
    assert s["marks"]["verdict"] == "ID_SET"
    assert s["attach"] == {"verdict": "NO_GAME_ID"}


# -- the load-screen question ----------------------------------------------------------

def test_a_load_press_that_was_recorded_reads_near_zero_and_no_load_drop(tmp_path):
    s = _grade(*_game(tmp_path, times=(0.3, 300.0), drop_ts=()))
    assert s["marks"]["near_zero"] == 1
    assert s["log"]["load_drop"] == "NO_LOAD_DROP"


def test_a_drop_after_clock_zero_is_not_a_load_drop(tmp_path):
    s = _grade(*_game(tmp_path, drop_ts=(BASE + 200.0,)))
    assert s["log"]["drops"][0]["vs_clock_zero"] == "after"
    assert s["log"]["load_drop"] == "NO_LOAD_DROP"


def test_a_champ_select_drop_is_not_a_load_drop(tmp_path):
    # Dropped the same way (:2999 down), but before the first game phase.
    s = _grade(*_game(tmp_path, drop_ts=(BASE - 600.0,)), since=BASE - 900.0)
    d = s["log"]["drops"][0]
    assert d["vs_clock_zero"] == "before" and d["before_game_start"] is True
    assert s["log"]["load_drop"] == "NO_LOAD_DROP"


def test_without_a_game_start_a_drop_before_clock_zero_is_unbounded(tmp_path):
    s = _grade(*_game(tmp_path), game_start=None)
    assert s["log"]["load_drop"] == "LOAD_DROP_UNBOUNDED"
    assert s["log"]["drops"][0]["before_game_start"] is None
    assert s["game_start"] is None and s["game_start_source"] == "none"


def test_no_marks_means_no_clock_zero(tmp_path):
    s = _grade(*_game(tmp_path, gids=(), times=(), attach=False))
    assert s["marks"]["verdict"] == "NONE" and s["marks"]["clock_zero"] is None
    assert s["log"]["load_drop"] == "UNKNOWN_NO_CLOCK_ZERO"
    assert s["log"]["presses_seen"] == 1
    assert s["attach"]["verdict"] == "NO_PIN_FILE"


def test_drop_kinds_are_told_apart(tmp_path):
    marks, pins, log = _game(tmp_path)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(_drop_line(BASE + 10.0, "gamestats carried no usable gameTime") + "\n")
        fh.write(_drop_line(BASE + 11.0, "disk full") + "\n")
        fh.write(f"{_stamp(BASE + 12.0)} WARNING moment mark: replay-buffer hook failed: x\n")
    s = _grade(marks, pins, log, expect=4)
    assert s["log"]["dropped"] == {"gamestats_unavailable": 1, "no_game_time": 1, "other": 1}
    assert s["log"]["other"]["replay_hook_failed"] == 1
    assert s["presses"]["verdict"] == "MISMATCH"


# -- the listener and the press ledger --------------------------------------------------

def test_a_listener_start_without_the_chord_and_a_restart_in_window(tmp_path):
    marks, pins, log = _game(tmp_path, start_k=False)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(_start_line(BASE + 600.0) + "\n")
    lg = _grade(marks, pins, log)["log"]
    assert lg["listener_start_lists_chord"] is False
    assert lg["listener_starts_in_window"] == 1


def test_lines_outside_the_window_are_not_counted(tmp_path):
    marks, pins, log = _game(tmp_path)
    s = _grade(marks, pins, log, since=BASE + 500.0, until=BASE + 1500.0, expect=1)
    assert s["log"]["recorded"] == 1 and s["marks"]["rows_in_window"] == 1
    assert s["marks"]["match_outside_window"] == 2
    assert s["presses"]["verdict"] == "MATCH"


def test_a_row_without_its_log_line_disagrees(tmp_path):
    marks, pins, log = _game(tmp_path)
    moment_marks.append_mark(moment_marks.build_mark({"gameTime": 700.0}, GID, BASE + 700.0), marks)
    assert _grade(marks, pins, log)["rows_vs_log"] == "DISAGREE"


def test_inconsistent_offsets_are_flagged(tmp_path):
    marks, pins, log = _game(tmp_path)
    moment_marks.append_mark(moment_marks.build_mark({"gameTime": 700.0}, GID, BASE + 760.0), marks)
    assert _grade(marks, pins, log, gid=GID)["marks"]["offset_consistent"] is False


def test_missing_log_is_a_reading(tmp_path):
    marks, pins, _ = _game(tmp_path)
    s = _grade(marks, pins, tmp_path / "nope.log", expect=4)
    assert s["log"]["files"] == [{"name": "nope.log", "missing": True}]
    assert s["presses"]["verdict"] == "MISMATCH"


# -- the attach half ---------------------------------------------------------------------

def test_a_pin_file_missing_a_mark_is_partial_and_a_stray_pin_is_extra(tmp_path):
    marks, pins, log = _game(tmp_path)
    target = pins / f"{GID}.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["pins"] = doc["pins"][:2]
    target.write_text(json.dumps(doc), encoding="utf-8")
    assert _grade(marks, pins, log)["attach"]["verdict"] == "PARTIAL"
    doc["pins"].append({"clock_s": 9, "game_time_s": 9.0, "wall_ts": 1.0, "label": "you flagged"})
    target.write_text(json.dumps(doc), encoding="utf-8")
    assert _grade(marks, pins, log)["attach"]["verdict"] == "EXTRA"


def test_junk_pin_values_never_raise(tmp_path):
    marks, pins, log = _game(tmp_path)
    target = pins / f"{GID}.json"
    target.write_text(json.dumps({"game_id": GID, "attached_at": "x",
                                  "pins": [{"game_time_s": "junk", "wall_ts": None}]}),
                      encoding="utf-8")
    a = _grade(marks, pins, log)["attach"]
    assert a["verdict"] == "EXTRA" and a["clock_s_ok"] is False
    assert a["attached_after_last_mark_s"] is None


def test_an_unreadable_pin_file(tmp_path):
    marks, pins, log = _game(tmp_path)
    (pins / f"{GID}.json").write_text("{not json", encoding="utf-8")
    assert _grade(marks, pins, log)["attach"] == {"verdict": "UNREADABLE"}


def test_a_corrupt_marks_line_is_named_by_category_and_line(tmp_path):
    marks, pins, log = _game(tmp_path)
    with marks.open("a", encoding="utf-8") as fh:
        fh.write("{torn\n")
    m = _grade(marks, pins, log)["marks"]
    assert m["strict"] == "not_json at line 4"
    assert m["rows_in_window"] == 3


# -- the CLI ------------------------------------------------------------------------------

def _argv(marks, pins, log, *extra):
    return ["--since", str(int(SINCE)), "--until", str(int(UNTIL)), "--game-id", GID,
            "--marks", str(marks), "--pins-dir", str(pins), "--log", str(log), *extra]


@pytest.mark.parametrize("fmt", [[], ["--json"]])
def test_cli_never_prints_a_game_id(tmp_path, capsys, fmt):
    marks, pins, log = _game(tmp_path, gids=(GID, OTHER, None))
    assert lx.main(_argv(marks, pins, log, "--expect-presses", "4", *fmt)) == 0
    out = capsys.readouterr().out
    assert GID not in out and OTHER not in out
    assert ("REAL_ID" in out) is False and "WRONG_ID" in out
    if fmt:
        assert json.loads(out)["presses"]["verdict"] == "MATCH"


def test_cli_glob_and_no_log(tmp_path, capsys):
    marks, pins, log = _game(tmp_path)
    assert lx.main(_argv(marks, pins, str(tmp_path / "hotkey_listener.log*"), "--json")) == 0
    assert json.loads(capsys.readouterr().out)["log"]["recorded"] == 3
    argv = _argv(marks, pins, log, "--json")
    argv = argv[: argv.index("--log")] + ["--no-log", "--json"]
    assert lx.main(argv) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["log"] is None and "rows_vs_log" not in s


@pytest.mark.parametrize("since,until", [("yesterday", "1790000000"), ("1790000100", "1790000000")])
def test_cli_bad_window_exits_2(since, until, capsys):
    assert lx.main(["--since", since, "--until", until]) == 2


def _tape(tmp_path, phases):
    path = tmp_path / "phase_1.jsonl"
    rows = [{"t": SINCE, "baseline": {"draft_log_rows": 0}}]
    rows += [{"t": t, "phase": ph} for t, ph in phases]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_cli_phase_tape_bounds_the_load_drop(tmp_path, capsys):
    marks, pins, log = _game(tmp_path)
    tape = _tape(tmp_path, [(BASE - 200.0, "ChampSelect"), (GAME_START, "InProgress"),
                            (BASE + 1400.0, "EndOfGame")])
    assert lx.main(_argv(marks, pins, log, "--phase-tape", str(tape), "--json")) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["game_start"] == pytest.approx(GAME_START) and s["game_start_source"] == "tape"
    assert s["log"]["load_drop"] == "LOAD_DROP_SEEN"


def test_cli_tape_without_a_game_phase_leaves_the_drop_unbounded(tmp_path, capsys):
    marks, pins, log = _game(tmp_path)
    tape = _tape(tmp_path, [(BASE - 200.0, "ChampSelect")])
    assert lx.main(_argv(marks, pins, log, "--phase-tape", str(tape), "--json")) == 0
    assert json.loads(capsys.readouterr().out)["log"]["load_drop"] == "LOAD_DROP_UNBOUNDED"


def test_cli_game_start_flag_and_its_errors(tmp_path, capsys):
    marks, pins, log = _game(tmp_path)
    assert lx.main(_argv(marks, pins, log, "--game-start", str(int(GAME_START)), "--json")) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["game_start_source"] == "flag" and s["log"]["load_drop"] == "LOAD_DROP_SEEN"
    assert lx.main(_argv(marks, pins, log, "--game-start", "soon")) == 2
    assert lx.main(_argv(marks, pins, log, "--phase-tape", str(tmp_path / "none.jsonl"))) == 2
    with pytest.raises(SystemExit):
        lx.main(_argv(marks, pins, log, "--phase-tape", "x", "--game-start", "1"))


def test_cli_iso_window(tmp_path, capsys):
    marks, pins, log = _game(tmp_path)
    iso = [datetime.fromtimestamp(SINCE).isoformat(), datetime.fromtimestamp(UNTIL).isoformat()]
    argv = _argv(marks, pins, log, "--json")
    argv[1], argv[3] = iso
    assert lx.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["marks"]["rows_in_window"] == 3


def test_tool_is_read_only(tmp_path):
    marks, pins, log = _game(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    lx.main(_argv(marks, pins, log, "--json"))
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
    src = (ROOT / "tools" / "gated_lx09_mark_check.py").read_text(encoding="utf-8")
    for banned in ("write_text", "append_mark", "attach_for_game(", "urlopen", "unlink", "replace("):
        assert banned not in src, banned
