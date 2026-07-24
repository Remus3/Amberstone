"""Tests for tools/ds_calibration_report.py (RM-32 / D-01 entry point).

Drives the CLI over a temp db + temp jsonl, never the gitignored real data.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TOOL = _ROOT / "tools" / "ds_calibration_report.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("ds_calibration_report", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_GCT_MS = 1778377395498


def _make_db(path: Path, games=3) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER, "
        "map_id INTEGER, game_creation_ts INTEGER, game_duration_s INTEGER, "
        "tracked_champion_id INTEGER, tracked_team_id INTEGER, "
        "tracked_win INTEGER, has_timeline INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, "
        "team_id INTEGER, champion_id INTEGER, item0 INTEGER, item1 INTEGER, "
        "item2 INTEGER, item3 INTEGER, item4 INTEGER, item5 INTEGER, "
        "item6 INTEGER)"
    )
    conn.execute(
        "CREATE TABLE timeline_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "match_id TEXT, timestamp_ms INTEGER, event_type TEXT, "
        "participant_id INTEGER, item_id INTEGER)"
    )
    for i in range(games):
        mid = f"NA1_{1000 + i}"
        conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)",
                     (mid, 420, 11, _GCT_MS, 1800, 222, 100, i % 2, 1))
        conn.execute("INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (mid, 4, 100, 222, 0, 0, 0, 0, 0, 0, 0))
        conn.execute(
            "INSERT INTO timeline_events (match_id, timestamp_ms, event_type, "
            "participant_id, item_id) VALUES (?,?,?,?,?)",
            (mid, 600_000, "ITEM_PURCHASED", 4, 3036))
    conn.commit()
    conn.close()


def _make_log(path: Path, games=3) -> None:
    lines = []
    for i in range(games):
        lines.append(json.dumps({
            "ts": _GCT_MS / 1000.0 + 120,
            "champion": "Vayne",
            "mode": "SR",
            "level": 9,
            "owned_items": [],
            "ds_picks": [{"item_id": "3036", "item_name": "LDR",
                          "delta_dps": 12.0, "gold": 3300, "scorer": "dps"}],
            "game_id": str(1000 + i),
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_main_writes_report_atomically(tmp_path):
    tool = _load_tool()
    db = tmp_path / "rewind_history.db"
    logp = tmp_path / "cal.jsonl"
    out = tmp_path / "sub" / "report.json"
    _make_db(db)
    _make_log(logp)
    rc = tool.main(["--db", str(db), "--log", str(logp), "--out", str(out),
                    "--min-n", "1"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == tool.SCHEMA
    assert payload["observations"] == 3
    assert payload["cells"]
    # tmp sidecar must not survive an atomic write
    assert not list(out.parent.glob("*.tmp"))


def test_report_is_reproducible_no_wall_clock(tmp_path):
    tool = _load_tool()
    db = tmp_path / "rewind_history.db"
    logp = tmp_path / "cal.jsonl"
    _make_db(db)
    _make_log(logp)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    tool.main(["--db", str(db), "--log", str(logp), "--out", str(a),
               "--min-n", "1"])
    tool.main(["--db", str(db), "--log", str(logp), "--out", str(b),
               "--min-n", "1"])
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_missing_db_exits_non_zero(tmp_path, capsys):
    tool = _load_tool()
    rc = tool.main(["--db", str(tmp_path / "nope.db"),
                    "--log", str(tmp_path / "nope.jsonl"),
                    "--out", str(tmp_path / "o.json")])
    assert rc != 0


def test_missing_log_exits_non_zero(tmp_path):
    tool = _load_tool()
    db = tmp_path / "rewind_history.db"
    _make_db(db)
    rc = tool.main(["--db", str(db), "--log", str(tmp_path / "nope.jsonl"),
                    "--out", str(tmp_path / "o.json")])
    assert rc != 0


def test_payload_carries_the_descriptive_only_note(tmp_path):
    tool = _load_tool()
    db = tmp_path / "rewind_history.db"
    logp = tmp_path / "cal.jsonl"
    _make_db(db)
    _make_log(logp)
    out = tmp_path / "r.json"
    tool.main(["--db", str(db), "--log", str(logp), "--out", str(out),
               "--min-n", "1"])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "daemon_slayer" in payload["generated_note"]
    assert "descriptive" in payload["generated_note"].lower()


def test_tool_never_imports_daemon_slayer():
    text = _TOOL.read_text(encoding="utf-8")
    assert "from agents" not in text
    assert "import agents" not in text
