"""RM-638 (directive X-38, external reference C) - post-game attach + routes.

The post-game collector attaches the just-ended game's moment marks (its own
try-block, separate from _publish_game_end_pin, so a failure there never costs
the capture), and the Replay / PGR routes expose them as an ADDITIVE
``you_flagged`` field. Synthetic ids only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import lcu.lcu_postgame_collector as pgc  # noqa: E402
from core import moment_marks as mm  # noqa: E402


@pytest.fixture
def mark_paths(tmp_path, monkeypatch):
    marks = tmp_path / "moment_marks.jsonl"
    out = tmp_path / "by_game"
    monkeypatch.setenv(mm.MARKS_ENV, str(marks))
    monkeypatch.setenv(mm.ATTACHED_ENV, str(out))
    return marks, out


def _collector():
    c = pgc.PostgameCollector.__new__(pgc.PostgameCollector)
    c._trigger_at = 10_000.0
    return c


def _seed(marks: Path, rows):
    marks.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="ascii")


# -- collector ----------------------------------------------------------------

def _stub_capture(monkeypatch, eog):
    c = _collector()
    monkeypatch.setattr(c, "_fetch_eog_stats_block", lambda: eog, raising=False)
    monkeypatch.setattr(c, "_publish_game_end_pin", lambda *a, **k: None,
                        raising=False)
    monkeypatch.setattr(c, "_try_fetch_timeline", lambda *a, **k: None,
                        raising=False)
    monkeypatch.setattr(pgc, "_save_eog", lambda *a, **k: None)
    monkeypatch.setattr(pgc, "_save_raw_document", lambda *a, **k: None)
    return c


def test_capture_attaches_marks_for_the_ended_game(monkeypatch, mark_paths):
    marks, out = mark_paths
    _seed(marks, [
        {"game_id": "7001", "game_time_s": 300.0, "wall_ts": 9_000.0},
        {"game_id": None, "game_time_s": 100.0, "wall_ts": 8_500.0},
        {"game_id": "6999", "game_time_s": 50.0, "wall_ts": 8_000.0},
    ])
    c = _stub_capture(monkeypatch, {"gameId": 7001, "gameLength": 1_500})
    assert c._capture("CLASSIC") is True
    doc = json.loads((out / "7001.json").read_text(encoding="ascii"))
    assert [p["game_time_s"] for p in doc["pins"]] == [100.0, 300.0]


def test_attach_failure_never_costs_the_capture(monkeypatch, mark_paths):
    saved = []
    c = _stub_capture(monkeypatch, {"gameId": 7001, "gameLength": 1_500})
    monkeypatch.setattr(pgc, "_save_eog", lambda *a, **k: saved.append(1))

    def boom(*a, **k):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(mm, "attach_for_game", boom)
    assert c._capture("CLASSIC") is True
    assert saved == [1], "EOG save must still run after a failed attach"


def test_attach_seam_is_its_own_method_not_inside_the_pin(monkeypatch, mark_paths):
    # The game-end pin is being extended by another slice; the mark attach
    # must not ride inside it, so stubbing the pin out must not skip it.
    marks, out = mark_paths
    _seed(marks, [{"game_id": "7001", "game_time_s": 1.0, "wall_ts": 9_999.0}])
    c = _stub_capture(monkeypatch, {"gameId": 7001, "gameLength": 100})
    c._capture("CLASSIC")
    assert (out / "7001.json").exists()


# -- routes (additive field) ----------------------------------------------------

class _H:
    def __init__(self, path):
        self.path = path
        self.responses = []

    def _send(self, status, body, ct):
        self.responses.append((status, json.loads(body)))


def _seed_rewind(path: Path, match_id: str):
    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER, "
        "duration_s INTEGER);"
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, "
        "team_id INTEGER, summoner_name TEXT, champion_name TEXT);"
        "CREATE TABLE timeline_events (id INTEGER PRIMARY KEY, match_id TEXT, "
        "timestamp_ms INTEGER, event_type TEXT, participant_id INTEGER, "
        "killer_id INTEGER, victim_id INTEGER, assisting_ids_json TEXT, "
        "kill_pos_x INTEGER, kill_pos_y INTEGER, building_type TEXT, "
        "lane_type TEXT, tower_type TEXT, team_id INTEGER, monster_type TEXT, "
        "monster_subtype TEXT, ward_type TEXT);")
    conn.execute("INSERT INTO matches VALUES (?, 420, 1800)", (match_id,))
    conn.commit()
    conn.close()


def test_replay_events_carries_you_flagged(tmp_path, monkeypatch, mark_paths):
    marks, out = mark_paths
    from dashboard import routes_replay_events as r
    db = tmp_path / "rewind_history.db"
    _seed_rewind(db, "NA1_7001")
    monkeypatch.setattr(r, "_REWIND_DB", db)
    r._CACHE.clear()
    _seed(marks, [{"game_id": "7001", "game_time_s": 61.5, "wall_ts": 9_999.0}])
    mm.attach_for_game("7001", 1_800, 10_000.0)

    h = _H("/api/replay/events?match_id=NA1_7001")
    r._serve_replay_events(h)
    status, body = h.responses[-1]
    assert status == 200 and body["ok"] is True
    assert [p["clock_s"] for p in body["you_flagged"]] == [61]
    assert "events" in body and "count" in body   # existing shape untouched

    h2 = _H("/api/replay/events?match_id=NA1_7001")   # cached path too
    r._serve_replay_events(h2)
    assert h2.responses[-1][1]["cached"] is True
    assert [p["clock_s"] for p in h2.responses[-1][1]["you_flagged"]] == [61]


def test_replay_events_you_flagged_empty_without_marks(tmp_path, monkeypatch,
                                                       mark_paths):
    from dashboard import routes_replay_events as r
    db = tmp_path / "rewind_history.db"
    _seed_rewind(db, "NA1_7002")
    monkeypatch.setattr(r, "_REWIND_DB", db)
    r._CACHE.clear()
    h = _H("/api/replay/events?match_id=NA1_7002")
    r._serve_replay_events(h)
    assert h.responses[-1][1]["you_flagged"] == []


def test_post_game_wpa_carries_you_flagged(tmp_path, monkeypatch, mark_paths):
    marks, out = mark_paths
    from dashboard import routes_post_game_wpa as w
    db = tmp_path / "rewind_history.db"
    _seed_rewind(db, "NA1_7001")
    monkeypatch.setattr(w, "_REWIND_DB", db)
    w._CACHE.clear()
    monkeypatch.setattr(w, "compute_match_wpa",
                        lambda conn, mid, model=None: {"ok": True, "events": []})
    _seed(marks, [{"game_id": "7001", "game_time_s": 200.0, "wall_ts": 9_999.0}])
    mm.attach_for_game("7001", 1_800, 10_000.0)

    h = _H("/api/post-game-wpa?match_id=NA1_7001")
    w._serve_post_game_wpa(h)
    status, body = h.responses[-1]
    assert status == 200
    assert [p["clock_s"] for p in body["you_flagged"]] == [200]
    h2 = _H("/api/post-game-wpa?match_id=NA1_7001")
    w._serve_post_game_wpa(h2)
    assert h2.responses[-1][1]["cached"] is True
    assert [p["clock_s"] for p in h2.responses[-1][1]["you_flagged"]] == [200]
