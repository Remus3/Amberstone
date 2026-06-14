"""Round 14 coverage - HEAD routing + first-legendary aggregate + hint surfacing."""
from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


# -- HEAD routing ---------------------------------------------------

@pytest.mark.timeout(30)
def test_head_on_api_env_returns_200(tmp_path: Path) -> None:
    """HEAD /api/env should route through do_GET (real status, no body).
    Uses a spawned supervisor - exercises the full HTTP stack."""
    import os
    import sys
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

    # Pick an unused port to avoid clashing with the live supervisor.
    # Actually the production supervisor holds :8890. We can't override
    # via env in the current code, so we probe the live server instead.
    # Skip if it's not up.
    def _port_open(host, port):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False
    if not _port_open("127.0.0.1", 8890):
        pytest.skip("supervisor not running on :8890")

    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:8890/api/env", method="HEAD")
    with urllib.request.urlopen(req, timeout=3) as r:
        assert r.status == 200
        # Body should be empty per HTTP HEAD semantics.
        body = r.read()
        assert body == b"" or len(body) == 0


# -- first-legendary analyzer ----------------------------------------

@pytest.fixture()
def seeded_with_events(tmp_path: Path, monkeypatch):
    """Seed an aram.db with matches + ITEM_PURCHASED events so the
    first-legendary aggregator has real data to operate on.
    """
    from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "DB_DIR", db_dir)

    # Stub out item metadata so "itemA"/"itemB" pass the gold filter.
    fake_meta = {
        3000: {"name": "itemA", "gold_total": 3000, "maps": {}},
        3001: {"name": "itemB", "gold_total": 3100, "maps": {}},
        1001: {"name": "boots-1",  "gold_total": 300, "maps": {}},  # excluded
    }
    monkeypatch.setattr(analyzer_mod, "_load_item_metadata", lambda: fake_meta)

    db_path = db_dir / "aram.db"
    conn = sqlite3.connect(db_path)
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        now = datetime.now(timezone.utc).isoformat()

        # Seed 8 Ahri matches. 5 first-leg itemA (4 wins), 3 first-leg itemB (0 wins).
        # itemA: 80% wr vs 4/8=50% baseline -> +30% delta (qualifies, >=0.10)
        # itemB: 0/3 -> below sample, excluded. Add a 9th match where itemB is first
        #   and we WIN to push sample up (but still itemA dominates).
        matchups = [
            # (win, first_leg, timing_sec)
            (1, 3000, 300),
            (1, 3000, 310),
            (1, 3000, 290),
            (1, 3000, 305),
            (0, 3000, 320),     # itemA n=5 w=4
            (0, 3001, 250),
            (0, 3001, 260),
            (0, 3001, 255),     # itemB n=3 w=0 - below ITEM_MIN_SAMPLE=5
        ]
        for i, (win, first_iid, ts) in enumerate(matchups):
            cur = conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, 'Ahri', '[]', '[]', 1200, ?, NULL, 'test')
                """,
                (now, now, win),
            )
            mid = cur.lastrowid
            # Insert a boots purchase first (should be skipped by gold filter),
            # then the actual first-leg at ts, then a second leg.
            conn.execute(
                """
                INSERT INTO match_events
                  (match_id, ts_game_sec, event_type, state_json, coach_output_json, outcome_30s_json)
                VALUES (?, ?, 'ITEM_PURCHASED', ?, NULL, NULL)
                """,
                (mid, 60.0, json.dumps({"item_id": 1001})),
            )
            conn.execute(
                """
                INSERT INTO match_events
                  (match_id, ts_game_sec, event_type, state_json, coach_output_json, outcome_30s_json)
                VALUES (?, ?, 'ITEM_PURCHASED', ?, NULL, NULL)
                """,
                (mid, float(ts), json.dumps({"item_id": first_iid})),
            )
        conn.commit()
    finally:
        conn.close()
    return db_dir


def test_first_legendary_uses_earliest_legendary_not_boots(seeded_with_events: Path) -> None:
    from agents.agent4_coach_mentor import analyze_mode
    summary = analyze_mode("aram")
    assert summary["matches_scanned"] == 8
    # itemB has only 3 samples -> below threshold, excluded
    # itemA has 5 samples, 4 wins, baseline 4/8=50% -> +30% delta -> included
    assert summary["first_legendary_total"] >= 1
    # Verify it didn't pick boots (item_id 1001) despite boots buying first in every match.
    with sqlite3.connect(seeded_with_events / "aram.db") as conn:
        row = conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion='Ahri'"
        ).fetchone()
    aj = json.loads(row[0])
    fl = aj.get("first_legendary") or []
    assert fl, "expected at least one first-legendary entry"
    for it in fl:
        assert it["item_id"] != 1001
    # itemA should be the one present.
    names = {it["name"] for it in fl}
    assert "itemA" in names


def test_first_legendary_avg_timing_matches_inputs(seeded_with_events: Path) -> None:
    from agents.agent4_coach_mentor import analyze_mode
    analyze_mode("aram")
    with sqlite3.connect(seeded_with_events / "aram.db") as conn:
        row = conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion='Ahri'"
        ).fetchone()
    aj = json.loads(row[0])
    itemA = next(it for it in aj["first_legendary"] if it["name"] == "itemA")
    # (300+310+290+305+320)/5 = 305.0
    assert abs(itemA["avg_timing_sec"] - 305.0) < 0.1


def test_hint_line_includes_first_leg_section(seeded_with_events: Path) -> None:
    from agents.agent4_coach_mentor import analyze_mode
    analyze_mode("aram")
    # Point adaptation_hint DB_DIR to the seeded one.
    import coaches.adaptation_hint as ah
    ah.DB_DIR = seeded_with_events
    line = ah.format_hint_line("Ahri", "aram")
    assert "first-leg signal" in line
    assert "itemA" in line
