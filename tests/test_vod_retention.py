"""core/vod_retention.py - keep-on-condition VOD retention (RM-640, ADR-016).

Pure-decision tests pin every ADR-016 "Retention" bullet:
  keep if ANY of manual pin / mark pressed / ranked loss / PGR below threshold;
  kept unpinned files age out at 14 days; over the 60 GB cap the oldest
  unpinned file goes first; pinned never touched; owner=operator never a
  candidate; a non-kept recording becomes a candidate only after its death
  reel is read back non-empty OR the sidecar records zero deaths.
Unknowns fail SAFE: unknown marks / unknown ranked result -> KEEP; no wall
time -> UNDATED (never a candidate).

Sidecar fixtures are built from the RM-637 recorder's own writer shape
(core/obs_recorder.py `_write_sidecar`), and a parity test parses the recorder
source so a writer change reds here. IO tests use tmp sidecars and a FAKE
recycler - nothing here deletes or recycles a real file.
"""
import ast
import json
import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import core.vod_retention as vr

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400.0
GB = 10**9
NOW = 1_800_000_000.0


def row(mid, *, age_days=1.0, size=5 * GB, **kw):
    base = dict(match_id=mid, path=f"vods/{mid}.mp4", size_bytes=size,
                created_at=NOW - age_days * DAY, deaths=3, death_reel_ok=True,
                marks=0, queue_id=400, win=True)
    base.update(kw)
    return vr.VodRow(**base)


def decide(rows, **pol):
    return vr.select_for_deletion(rows, vr.Policy(**pol), NOW)


def action(res, mid, kind=vr.KIND_RECORDING):
    for d in res.decisions:
        if d.row.match_id == mid and d.row.kind == kind:
            return d.action
    raise KeyError(mid)


# -- ownership and pin fences ------------------------------------------------


def test_operator_owned_is_never_a_candidate():
    r = row("op", owner="operator", age_days=90, size=100 * GB)
    res = decide([r])
    assert action(res, "op") == vr.ACTION_PROTECTED
    assert res.candidates == []


def test_unknown_owner_fails_closed():
    res = decide([row("x", owner="", age_days=90)])
    assert action(res, "x") == vr.ACTION_PROTECTED


def test_pinned_never_touched_even_over_cap():
    rows = [row(f"p{i}", pinned=True, age_days=60, size=30 * GB)
            for i in range(3)]
    res = decide(rows)
    assert all(d.action == vr.ACTION_PROTECTED for d in res.decisions)
    assert res.pinned_fill_cap is True
    assert res.over_cap_after is True


# -- keep conditions -----------------------------------------------------------


def test_plain_unkept_recording_is_candidate():
    res = decide([row("a")])
    assert action(res, "a") == vr.ACTION_CANDIDATE


def test_mark_pressed_keeps():
    assert action(decide([row("a", marks=1)]), "a") == vr.ACTION_KEEP


def test_unknown_mark_count_keeps_fail_safe():
    assert action(decide([row("a", marks=None)]), "a") == vr.ACTION_KEEP


def test_ranked_loss_keeps_ranked_win_and_normal_loss_do_not():
    res = decide([row("rl", queue_id=420, win=False),
                  row("rw", queue_id=420, win=True),
                  row("nl", queue_id=400, win=False)])
    assert action(res, "rl") == vr.ACTION_KEEP
    assert action(res, "rw") == vr.ACTION_CANDIDATE
    assert action(res, "nl") == vr.ACTION_CANDIDATE


def test_unknown_result_keeps_on_ranked_or_unknown_queue_only():
    res = decide([row("rq", queue_id=440, win=None),
                  row("uq", queue_id=None, win=None),
                  row("nq", queue_id=400, win=None)])
    assert action(res, "rq") == vr.ACTION_KEEP
    assert action(res, "uq") == vr.ACTION_KEEP
    assert action(res, "nq") == vr.ACTION_CANDIDATE


def test_pgr_below_threshold_keeps():
    res = decide([row("lo", pgr_score=10.0), row("hi", pgr_score=90.0),
                  row("na", pgr_score=None)], pgr_keep_below=40.0)
    assert action(res, "lo") == vr.ACTION_KEEP
    assert action(res, "hi") == vr.ACTION_CANDIDATE
    assert action(res, "na") == vr.ACTION_CANDIDATE


def test_kept_unpinned_ages_out_at_14_days():
    res = decide([row("young", marks=1, age_days=13.9),
                  row("old", marks=1, age_days=14.1)])
    assert action(res, "young") == vr.ACTION_KEEP
    assert action(res, "old") == vr.ACTION_CANDIDATE


def test_undated_is_never_a_candidate_nor_evicted():
    rows = [row("u", created_at=None, size=70 * GB),
            row("k", marks=1, size=1 * GB)]
    res = decide(rows, cap_bytes=60 * GB)
    assert action(res, "u") == vr.ACTION_UNDATED
    assert all(d.row.match_id != "u" for d in res.candidates)


def test_unfinalized_recording_is_held():
    assert action(decide([row("a", final=False)]), "a") == vr.ACTION_HELD


# -- death-reel gate -----------------------------------------------------------


def test_unkept_held_until_death_reel_read_back():
    res = decide([row("a", death_reel_ok=False, deaths=4)])
    assert action(res, "a") == vr.ACTION_HELD


def test_zero_death_match_is_candidate_without_a_reel():
    res = decide([row("a", death_reel_ok=False, deaths=0)])
    assert action(res, "a") == vr.ACTION_CANDIDATE


def test_unknown_death_count_without_reel_is_held():
    res = decide([row("a", death_reel_ok=False, deaths=None)])
    assert action(res, "a") == vr.ACTION_HELD


# -- cap -------------------------------------------------------------------------


def test_over_cap_evicts_oldest_unpinned_first():
    rows = [row("k1", marks=1, age_days=5, size=25 * GB),
            row("k2", marks=1, age_days=3, size=25 * GB),
            row("k3", marks=1, age_days=1, size=25 * GB),
            row("pin", pinned=True, age_days=9, size=5 * GB)]
    res = decide(rows, cap_bytes=60 * GB)
    assert action(res, "k1") == vr.ACTION_CANDIDATE
    assert action(res, "k2") == vr.ACTION_KEEP
    assert action(res, "k3") == vr.ACTION_KEEP
    assert action(res, "pin") == vr.ACTION_PROTECTED
    assert res.bytes_after == 55 * GB
    assert res.over_cap_after is False


def test_cap_never_evicts_held_or_operator_files():
    rows = [row("held", age_days=9, size=50 * GB, death_reel_ok=False),
            row("op", owner="operator", age_days=9, size=50 * GB),
            row("k", marks=1, age_days=1, size=20 * GB)]
    res = decide(rows, cap_bytes=60 * GB)
    assert action(res, "held") == vr.ACTION_HELD
    assert action(res, "op") == vr.ACTION_PROTECTED
    assert action(res, "k") == vr.ACTION_CANDIDATE
    assert res.bytes_after == 50 * GB


def test_cap_counts_only_rc_bytes():
    rows = [row("op", owner="operator", size=100 * GB),
            row("k", marks=1, size=10 * GB)]
    res = decide(rows, cap_bytes=60 * GB)
    assert action(res, "k") == vr.ACTION_KEEP
    assert res.total_bytes == 10 * GB


def test_clips_are_kept_age_out_and_count_toward_cap():
    rows = [row("c1", kind=vr.KIND_CLIP, age_days=2, size=1 * GB),
            row("c2", kind=vr.KIND_CLIP, age_days=20, size=1 * GB)]
    res = decide(rows)
    assert action(res, "c1", vr.KIND_CLIP) == vr.ACTION_KEEP
    assert action(res, "c2", vr.KIND_CLIP) == vr.ACTION_CANDIDATE


def test_absent_file_is_reported_not_counted():
    res = decide([row("gone", size=None)])
    assert action(res, "gone") == vr.ACTION_ABSENT
    assert res.total_bytes == 0 and res.candidates == []


@pytest.mark.parametrize("bad", [dict(cap_bytes=0), dict(keep_days=0),
                                 dict(cap_bytes=-1), dict(keep_days=-3)])
def test_policy_rejects_inverting_values(bad):
    with pytest.raises(ValueError):
        decide([row("a")], **bad)


# -- the recorder's sidecar shape --------------------------------------------------


def recorder_sidecar(match_id="7001", **over):
    """A sidecar shaped exactly like core/obs_recorder.py `_write_sidecar`."""
    body = {
        "schema": 1,
        "status": "final",
        "match_id": match_id,
        "queue_id": 420,
        "game_mode": "CLASSIC",
        "mode": "sr",
        "owner": "rc",
        "obs_output_path": f"vods/{match_id}.mp4",
        "ownership_token": f"vods/{match_id}.mp4",
        "game_time_offset_s": 12.5,
        "alignment": {"proven": True, "method": "advance", "anchors": []},
        "start_game_time_s": 0.0,
        "wall": {"attach": NOW - 2 * DAY - 2000, "record_start": NOW - 2 * DAY - 1900,
                 "record_stop": NOW - 2 * DAY, "game_end": NOW - 2 * DAY - 5},
        "stop_reason": "end_of_game",
        "death_count": 2,
        "bookmarks": [{"event_id": 7, "name": "ChampionKill", "game_time": 300.0,
                       "video_time": 287.5, "provisional": False,
                       "own_death": True}],
        "diagnostics": {"stall_count": 0},
    }
    assert tuple(body) == vr.RECORDER_SIDECAR_KEYS
    assert tuple(body["wall"]) == vr.RECORDER_WALL_KEYS
    for k, v in over.items():
        if k == "wall":
            body["wall"] = {**body["wall"], **v}
        else:
            body[k] = v
    return body


def _writer_keys(source: str):
    """Keys of the `body` dict literal and its `wall` dict in _write_sidecar."""
    tree = ast.parse(source)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "_write_sidecar":
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and getattr(node.targets[0], "id", None) == "body"
                        and isinstance(node.value, ast.Dict)):
                    keys = tuple(k.value for k in node.value.keys)
                    wall = node.value.values[keys.index("wall")]
                    return keys, tuple(k.value for k in wall.keys)
    raise AssertionError("_write_sidecar body dict not found")


def test_reader_contract_matches_recorder_writer():
    src = ROOT / "core" / "obs_recorder.py"
    if not src.exists():
        pytest.skip("RM-637 recorder not merged yet; parity runs once it is")
    keys, wall = _writer_keys(src.read_text(encoding="utf-8"))
    assert keys == vr.RECORDER_SIDECAR_KEYS
    assert wall == vr.RECORDER_WALL_KEYS


def _sizes(**extra):
    base = {"vods/7001.mp4": 6 * GB}
    base.update(extra)
    return base.get


def test_created_at_precedence_record_stop_game_end_record_start():
    wall = {"attach": 1.0, "record_start": 3.0, "record_stop": 4.0, "game_end": 2.0}
    assert vr.created_at_from_wall({"wall": wall}) == 4.0
    wall["record_stop"] = None
    assert vr.created_at_from_wall({"wall": wall}) == 2.0
    wall["game_end"] = None
    assert vr.created_at_from_wall({"wall": wall}) == 3.0
    wall["record_start"] = None
    assert vr.created_at_from_wall({"wall": wall}) is None, "attach is not a time"
    assert vr.created_at_from_wall({"wall": {"record_stop": 0}}) is None


def test_recorder_sidecar_with_no_wall_times_is_undated():
    doc = recorder_sidecar(wall={"record_start": None, "record_stop": None,
                                 "game_end": None})
    rows = vr.rows_from_sidecar(doc, "s.json", _sizes(), lambda m, w=None: 0,
                                lambda m: True)
    res = decide(rows)
    assert action(res, "7001") == vr.ACTION_UNDATED


def test_event_bookmarks_are_not_marks_marks_come_from_reader():
    doc = recorder_sidecar(death_count=0)
    rows = vr.rows_from_sidecar(doc, "s.json", _sizes(), lambda m, w=None: 0,
                                lambda m: True)
    assert rows[0].marks == 0
    assert action(decide(rows), "7001") == vr.ACTION_CANDIDATE
    rows = vr.rows_from_sidecar(doc, "s.json", _sizes(), lambda m, w=None: 2,
                                lambda m: True)
    assert action(decide(rows), "7001") == vr.ACTION_KEEP


def test_ranked_loss_from_result_lookup_keeps():
    doc = recorder_sidecar(death_count=0)
    lost = vr.rows_from_sidecar(doc, "s.json", _sizes(), lambda m, w=None: 0,
                                lambda m: False)
    unknown = vr.rows_from_sidecar(doc, "s.json", _sizes(), lambda m, w=None: 0, None)
    assert action(decide(lost), "7001") == vr.ACTION_KEEP
    assert action(decide(unknown), "7001") == vr.ACTION_KEEP


def test_reader_exceptions_mean_unknown_not_crash():
    def boom(*_):
        raise RuntimeError("x")
    rows = vr.rows_from_sidecar(recorder_sidecar(), "s.json", _sizes(), boom, boom)
    assert rows[0].marks is None and rows[0].win is None


def test_death_reel_read_back_and_zero_size_reel():
    reel = "vods/7001-deaths.mp4"
    doc = recorder_sidecar(death_reel={"path": reel})
    ok = vr.rows_from_sidecar(doc, "s.json", _sizes(**{reel: 10**6}),
                              lambda m, w=None: 0, lambda m: True)
    empty = vr.rows_from_sidecar(doc, "s.json", _sizes(**{reel: 0}),
                                 lambda m, w=None: 0, lambda m: True)
    assert ok[0].death_reel_ok is True
    assert [r.path for r in ok if r.kind == vr.KIND_CLIP] == [reel]
    assert empty[0].death_reel_ok is False
    assert action(decide(empty), "7001") == vr.ACTION_HELD


def test_operator_owned_sidecar_yields_no_recording_row():
    doc = recorder_sidecar(owner="operator", obs_output_path=None)
    rows = vr.rows_from_sidecar(doc, "s.json", _sizes(), None, None)
    assert [r for r in rows if r.kind == vr.KIND_RECORDING] == []


def test_in_progress_sidecar_is_held():
    doc = recorder_sidecar(status="recording", death_count=0)
    rows = vr.rows_from_sidecar(doc, "s.json", _sizes(), lambda m, w=None: 0,
                                lambda m: True)
    assert action(decide(rows), "7001") == vr.ACTION_HELD


# -- outside-the-sidecar readers ------------------------------------------------


def test_game_id_from_match_id():
    assert vr.game_id_from_match_id("7001") == "7001"
    assert vr.game_id_from_match_id("NA1_7001") == "7001"
    assert vr.game_id_from_match_id("unknown-1800000000") is None
    assert vr.game_id_from_match_id("0") is None


def _rewind_db(path: Path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY,"
                 " queue_id INTEGER, tracked_win INTEGER)")
    conn.executemany("INSERT INTO matches VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()


def test_rewind_lookup_reads_tracked_win_by_game_id(tmp_path):
    db = tmp_path / "rewind_history.db"
    _rewind_db(db, [("NA1_7001", 420, 0), ("NA1_7002", 420, 1),
                    ("NA1_7003", 420, None)])
    look = vr.RewindResultLookup(db)
    assert look("7001") is False
    assert look("7002") is True
    assert look("7003") is None
    assert look("9999") is None
    assert vr.RewindResultLookup(tmp_path / "missing.db")("7001") is None


def test_rewind_lookup_is_read_only(tmp_path, monkeypatch):
    db = tmp_path / "rewind_history.db"
    _rewind_db(db, [("NA1_7001", 420, 0)])
    before = db.read_bytes()
    seen = []
    real_connect = sqlite3.connect

    def spy(target, *a, **kw):
        seen.append((str(target), kw.get("uri")))
        return real_connect(target, *a, **kw)

    monkeypatch.setattr(sqlite3, "connect", spy)
    assert vr.RewindResultLookup(db)("7001") is False
    # Every open is a URI open with mode=ro: a writable open fails here even
    # if the query itself never writes.
    assert seen and all(uri is True and target.startswith("file:")
                        and target.endswith("?mode=ro") for target, uri in seen)
    assert db.read_bytes() == before


# -- marks: only a PROVEN count; everything else is unknown (KEEP) -------------

import core.moment_marks as mm  # noqa: E402  (RM-638, on origin/main)

WIN = (NOW - 3000.0, NOW - 1000.0)


@pytest.fixture
def marks_env(tmp_path, monkeypatch):
    pins = tmp_path / "by_game"
    pins.mkdir()
    jsonl = tmp_path / "moment_marks.jsonl"
    monkeypatch.setenv(mm.ATTACHED_ENV, str(pins))
    monkeypatch.setenv(mm.MARKS_ENV, str(jsonl))
    return pins, jsonl


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_marks_pin_file_count_is_proven(marks_env):
    pins, _ = marks_env
    (pins / "7001.json").write_text(json.dumps(
        {"game_id": "7001", "pins": [{"clock_s": 5}, {"clock_s": 9}]}),
        encoding="utf-8")
    (pins / "7002.json").write_text(json.dumps(
        {"game_id": "7002", "pins": []}), encoding="utf-8")
    assert vr.moment_marks_count("7001", WIN) == 2
    assert vr.moment_marks_count("7002", WIN) == 0


def test_marks_corrupt_pin_file_is_unknown(marks_env):
    pins, _ = marks_env
    (pins / "7001.json").write_text("{not json", encoding="utf-8")
    (pins / "7002.json").write_text(json.dumps({"pins": "x"}), encoding="utf-8")
    assert vr.moment_marks_count("7001", WIN) is None
    assert vr.moment_marks_count("7002", WIN) is None


def test_marks_unknown_match_id_is_unknown(marks_env):
    assert vr.moment_marks_count("unknown-1800000000", WIN) is None


def test_strict_pin_reader_rejects_a_non_game_id(marks_env):
    with pytest.raises(mm.MarksUnreadable):
        mm.pins_for_match_strict("unknown-1800000000")


def test_vod_guards_non_game_id_even_if_reader_is_lenient(monkeypatch):
    # Each layer refuses an `unknown-*` id on its own: a lenient reader that
    # says "no pin file, no raw marks" must still not yield a proven zero.
    fake = types.ModuleType("core.moment_marks")
    fake.ATTACH_SLACK_S = 0.0
    fake.MarksUnreadable = mm.MarksUnreadable
    fake.pins_for_match_strict = lambda mid: None
    fake.read_marks_strict = lambda: []
    monkeypatch.setitem(sys.modules, "core.moment_marks", fake)
    assert vr.moment_marks_count("unknown-1800000000", WIN) is None
    assert vr.moment_marks_count("7001", WIN) == 0


def test_marks_no_pin_file_falls_back_to_raw_jsonl(marks_env):
    _, jsonl = marks_env
    # attach never ran: the marks only live in the raw jsonl
    _jsonl(jsonl, [
        {"game_id": "7001", "game_time_s": 10.0, "wall_ts": 1.0},
        {"game_id": None, "game_time_s": 20.0, "wall_ts": WIN[0] + 5},
        {"game_id": "9999", "game_time_s": 30.0, "wall_ts": 2.0},
    ])
    assert vr.moment_marks_count("7001", WIN) == 2
    assert vr.moment_marks_count("7002", (10_000.0, 10_001.0)) == 0
    # a mark inside the slack-widened window counts even with another gameId
    assert vr.moment_marks_count("7002", (300.0, 301.0)) == 2


def test_marks_no_pin_file_and_no_jsonl_is_proven_zero(marks_env):
    assert vr.moment_marks_count("7001", WIN) == 0


def test_marks_unreadable_jsonl_is_unknown(marks_env):
    _, jsonl = marks_env
    jsonl.write_text('{"game_id": "1", "game_time_s": 1, "wall_ts": 2}\n'
                     "garbage\n", encoding="utf-8")
    assert vr.moment_marks_count("7001", WIN) is None
    jsonl.unlink()
    jsonl.mkdir()  # a directory where the file should be: unreadable
    assert vr.moment_marks_count("7001", WIN) is None


def test_marks_without_a_recording_window_are_unknown(marks_env):
    assert vr.moment_marks_count("7001", None) is None


def test_marks_reader_missing_is_unknown(monkeypatch):
    monkeypatch.setitem(sys.modules, "core.moment_marks", None)
    assert vr.moment_marks_count("7001", WIN) is None


def test_mark_window_from_recorder_wall():
    doc = recorder_sidecar()
    assert vr.mark_window(doc) == (doc["wall"]["record_start"],
                                   doc["wall"]["record_stop"])
    assert vr.mark_window(recorder_sidecar(wall={"record_stop": None})) is None


def test_plan_counts_raw_marks_when_attach_failed(tmp_path, marks_env):
    _, jsonl = marks_env
    vids, side = _layout(tmp_path)
    _jsonl(jsonl, [{"game_id": "7001", "game_time_s": 1.0, "wall_ts": 1.0}])
    res = vr.plan(side, vr.Policy(), now=NOW, result_for=lambda m: True)
    assert action(res, "7001") == vr.ACTION_KEEP
    assert action(res, "7002") == vr.ACTION_CANDIDATE


# -- IO: plan + apply ------------------------------------------------------------


def _layout(tmp_path):
    vids = tmp_path / "obs"
    vids.mkdir()
    side = tmp_path / "recordings"
    side.mkdir()
    for gid in ("7001", "7002"):
        (vids / f"{gid}.mp4").write_bytes(b"v" * 100)
        (vids / f"{gid}-deaths.mp4").write_bytes(b"r" * 10)
        doc = recorder_sidecar(
            gid, queue_id=400, death_count=1,
            obs_output_path=str(vids / f"{gid}.mp4"),
            wall={"record_start": NOW - 3 * DAY - 1800,
                  "record_stop": NOW - 3 * DAY},
            death_reel={"path": str(vids / f"{gid}-deaths.mp4")})
        (side / f"{gid}.json").write_text(json.dumps(doc), encoding="utf-8")
    # an unrelated operator file in the same OBS folder: never in scope
    (vids / "operator-stream.mp4").write_bytes(b"o" * 1000)
    return vids, side


def _plan(side):
    return vr.plan(side, vr.Policy(), now=NOW, marks_for=lambda m, w=None: 0,
                   result_for=lambda m: True)


def test_plan_only_sees_sidecar_recorded_paths(tmp_path):
    vids, side = _layout(tmp_path)
    res = _plan(side)
    paths = {d.row.path for d in res.decisions}
    assert str(vids / "operator-stream.mp4") not in paths
    assert {Path(p).name for p in paths} == {
        "7001.mp4", "7002.mp4", "7001-deaths.mp4", "7002-deaths.mp4"}
    assert {Path(d.row.path).name for d in res.candidates} == {
        "7001.mp4", "7002.mp4"}


def test_plan_default_readers_fail_safe(tmp_path, monkeypatch):
    vids, side = _layout(tmp_path)
    monkeypatch.setitem(sys.modules, "core.moment_marks", None)
    monkeypatch.setattr(vr, "DEFAULT_REWIND_DB", tmp_path / "absent.db")
    res = vr.plan(side, vr.Policy(), now=NOW)
    assert res.candidates == []


class FakeRecycler:
    def __init__(self, nuke_on=None):
        self.calls = []
        self.nuke_on = nuke_on

    def __call__(self, path):
        from core.recycle_bin import RecycleResult, METHOD_RECYCLE_BIN
        self.calls.append(str(path))
        if self.nuke_on and Path(path).name == self.nuke_on:
            return RecycleResult(False, str(path), METHOD_RECYCLE_BIN,
                                 "gone but NOT found in the Recycle Bin",
                                 nuked=True)
        return RecycleResult(True, str(path), METHOD_RECYCLE_BIN, "landed")


def _snapshot(d: Path):
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


def test_apply_is_dry_run_by_default(tmp_path):
    vids, side = _layout(tmp_path)
    fake = FakeRecycler()
    out = vr.apply(_plan(side), recycler=fake)
    assert out["dry_run"] is True
    assert fake.calls == []
    assert len(out["would_recycle"]) == 2


def test_apply_real_needs_confirm_token(tmp_path):
    vids, side = _layout(tmp_path)
    fake = FakeRecycler()
    out = vr.apply(_plan(side), dry_run=False, confirm="yes", recycler=fake)
    assert fake.calls == [] and out["recycled"] == []


def test_apply_real_recycles_only_candidates_and_sidecar_survives(tmp_path):
    vids, side = _layout(tmp_path)
    before = _snapshot(side)
    fake = FakeRecycler()
    out = vr.apply(_plan(side), dry_run=False, confirm=vr.CONFIRM_TOKEN,
                   recycler=fake)
    assert sorted(Path(c).name for c in fake.calls) == ["7001.mp4", "7002.mp4"]
    assert len(out["recycled"]) == 2 and out["failed"] == []
    assert _snapshot(side) == before, "sidecars must survive untouched"
    assert (vids / "operator-stream.mp4").exists()


def test_apply_halts_after_a_detected_nuke(tmp_path):
    vids, side = _layout(tmp_path)
    res = _plan(side)
    first = sorted(d.row.path for d in res.candidates)[0]
    fake = FakeRecycler(nuke_on=Path(first).name)
    out = vr.apply(res, dry_run=False, confirm=vr.CONFIRM_TOKEN,
                   recycler=fake)
    assert len(fake.calls) == 1
    assert out["halted"] is True


def test_apply_rechecks_fences_on_tampered_decision():
    # Defence in depth: decisions forged as CANDIDATE are refused by apply().
    bad = [vr.Decision(row("op", owner="operator"), vr.ACTION_CANDIDATE, ()),
           vr.Decision(row("pin", pinned=True), vr.ACTION_CANDIDATE, ()),
           vr.Decision(row("u", created_at=None), vr.ACTION_CANDIDATE, ()),
           vr.Decision(row("r", final=False), vr.ACTION_CANDIDATE, ())]
    res = vr.RetentionDecisions(decisions=bad, cap_bytes=60 * GB)
    fake = FakeRecycler()
    out = vr.apply(res, dry_run=False, confirm=vr.CONFIRM_TOKEN,
                   recycler=fake)
    assert fake.calls == []
    assert len(out["refused"]) == 4


def test_render_report_is_ascii(tmp_path):
    vids, side = _layout(tmp_path)
    text = vr.render_report(_plan(side))
    text.encode("ascii")
    assert "dry-run" in text
