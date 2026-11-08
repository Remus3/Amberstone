"""Tests for tools/gated_g316_shadow_game_id.py (G3-16 PREP, read-only).

Rows come from the REAL writer core.hz_choice_shadow.log_precomputed_choices
into tmp_path, so a writer schema change (key names, local- prefix) shows up
here. Game ids are synthetic (RM-906).
"""

from __future__ import annotations

from datetime import datetime, timezone

from core import hz_choice_shadow as hcs
from tools import gated_g316_shadow_game_id as g

SINCE = "2026-08-12T20:00:00Z"
GID = "7000000001"


def _log(path, gt, game_id=None, minute=0):
    return hcs.log_precomputed_choices(
        mode="aram", my_champion="Annie", enemy="Caitlyn",
        choices=[{"key": "A", "label": "Trade"}], covered=True,
        game_time_s=gt, level=1 + int(gt // 60),
        now_iso=f"2026-08-12T20:{minute:02d}:00+00:00",
        game_id=game_id, path=path)


def _grade(path, since=SINCE, phase=None):
    with path.open(encoding="utf-8") as fh:
        return g.grade(g.rows_since(fh, g.parse_ts(since)), phase)


def test_all_real_rows_pass(tmp_path):
    p = tmp_path / "hz.jsonl"
    for i, gt in enumerate((30.0, 90.0, 150.0)):
        _log(p, gt, GID, minute=i + 1)
    res = _grade(p)
    assert res["verdict"] == "PASS"
    assert res["counts"]["real"] == 3
    assert res["counts"]["distinct_real_ids"] == 1


def test_leading_local_rows_then_real_id_pass(tmp_path):
    """The writer's own mid-game takeover: local- first, then the real id."""
    p = tmp_path / "hz.jsonl"
    first = _log(p, 30.0, None, minute=1)
    assert first["game_run_id"].startswith(g.LOCAL_PREFIX)
    _log(p, 90.0, GID, minute=2)
    res = _grade(p)
    assert res["verdict"] == "PASS"
    assert res["counts"]["lead_local"] == 1
    assert res["counts"]["local_after_real"] == 0


def test_local_row_after_real_row_fails(tmp_path):
    p = tmp_path / "hz.jsonl"
    _log(p, 30.0, GID, minute=1)
    _log(p, 90.0, None, minute=2)
    res = _grade(p)
    assert res["verdict"] == "FAIL"
    assert res["counts"]["local_after_real"] == 1


def test_all_local_fails_only_with_in_game_phase(tmp_path):
    p = tmp_path / "hz.jsonl"
    _log(p, 30.0, None, minute=1)
    _log(p, 90.0, None, minute=2)
    assert _grade(p)["verdict"] == "NO_RESULT"
    assert _grade(p, phase="ChampSelect")["verdict"] == "NO_RESULT"
    for phase in ("GameStart", "InProgress", "Reconnect"):
        assert _grade(p, phase=phase)["verdict"] == "FAIL"


def test_in_game_phases_mirror_state_builder():
    from dashboard import _state_builder as sb
    assert tuple(sb._IN_GAME_PHASES) == g.IN_GAME_PHASES


def test_two_real_ids_is_no_result(tmp_path):
    p = tmp_path / "hz.jsonl"
    _log(p, 30.0, GID, minute=1)
    _log(p, 20.0, "7000000002", minute=40)
    res = _grade(p)
    assert res["verdict"] == "NO_RESULT"
    assert res["counts"]["distinct_real_ids"] == 2


def test_since_excludes_older_rows(tmp_path):
    p = tmp_path / "hz.jsonl"
    _log(p, 30.0, None, minute=1)
    _log(p, 90.0, GID, minute=30)
    res = _grade(p, since="2026-08-12T20:10:00+00:00")
    assert res["verdict"] == "PASS"
    assert res["counts"]["rows"] == 1


def test_empty_window_is_no_result(tmp_path):
    p = tmp_path / "hz.jsonl"
    _log(p, 30.0, GID, minute=1)
    assert _grade(p, since="2026-08-13T00:00:00Z")["verdict"] == "NO_RESULT"


def test_pre_b4d_rows_are_no_result():
    rows = [{"ts": "2026-08-02T22:34:15+00:00", "mode": "aram"}]
    assert g.grade(rows)["verdict"] == "NO_RESULT"


def test_mismatch_and_non_numeric_fail():
    ts = "2026-08-12T20:01:00+00:00"
    bad_run = [{"ts": ts, "game_id": GID, "game_run_id": "local-aram-x"}]
    assert g.grade(bad_run)["verdict"] == "FAIL"
    bad_id = [{"ts": ts, "game_id": "abc", "game_run_id": "abc"}]
    assert g.grade(bad_id)["verdict"] == "FAIL"
    no_run = [{"ts": ts, "game_id": None, "game_run_id": None}]
    assert g.grade(no_run)["verdict"] == "FAIL"


def test_parse_ts_forms():
    want = datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)
    assert g.parse_ts("2026-08-12T20:00:00Z") == want
    assert g.parse_ts("2026-08-12T15:00:00-05:00") == want
    assert g.parse_ts("2026-08-12T20:00:00") == want
    assert g.parse_ts("nope") is None
    assert g.parse_ts(None) is None


def test_rows_since_skips_garbage():
    lines = ["", "not json", "[1, 2]", '{"ts": "bad"}',
             '{"ts": "2026-08-12T20:05:00+00:00", "game_id": null}']
    out = g.rows_since(lines, g.parse_ts(SINCE))
    assert len(out) == 1


def test_main_prints_counts_not_ids(tmp_path, capsys):
    p = tmp_path / "hz.jsonl"
    _log(p, 30.0, GID, minute=1)
    rc = g.main(["--since", SINCE, "--path", str(p)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("PASS:")
    assert GID not in out


def test_main_missing_file_and_bad_since(tmp_path, capsys):
    assert g.main(["--since", SINCE, "--path",
                   str(tmp_path / "absent.jsonl")]) == 0
    assert capsys.readouterr().out.startswith("NO_RESULT:")
    assert g.main(["--since", "garbage", "--path", str(tmp_path)]) == 2


def test_tool_never_writes(tmp_path, monkeypatch):
    p = tmp_path / "hz.jsonl"
    _log(p, 30.0, GID, minute=1)
    before = p.read_bytes()
    import builtins
    import io
    real_open = io.open
    calls = []

    def guarded(file, mode="r", *a, **kw):
        calls.append(mode)
        assert not any(c in mode for c in "wax+"), mode
        return real_open(file, mode, *a, **kw)

    # Path.open goes through io.open, plain open() through builtins.open.
    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(io, "open", guarded)
    g.main(["--since", SINCE, "--path", str(p)])
    monkeypatch.undo()
    assert calls, "the guard never saw the tool's read"
    assert p.read_bytes() == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["hz.jsonl"]
