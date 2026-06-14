"""Round 18 - frozen-file guardrail + insight_card helper."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents.agent1_lead import Scheduler, TaskStatus


# -- Frozen-file guardrail -------------------------------------------

def test_frozen_file_in_payload_gates_to_approval(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    t = s.file_task(
        op="edit-main-py",
        owner_agent="2",
        priority=50,
        payload={"target_file": "main.py", "diff": "some change"},
    )
    assert t.status == TaskStatus.NEEDS_APPROVAL
    assert 1 in t.categories
    assert t.payload.get("_frozen_file_hits") == ["main.py"]


def test_frozen_file_with_user_override_passes(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    t = s.file_task(
        op="edit-main-py",
        owner_agent="2",
        priority=50,
        payload={"target_file": "main.py"},
        user_override=True,
    )
    assert t.status == TaskStatus.READY
    # Still annotated with the hit so audits can see what was approved.
    assert t.payload.get("_frozen_file_hits") == ["main.py"]


def test_frozen_file_detected_in_nested_payload(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    t = s.file_task(
        op="audit-fix",
        owner_agent="2",
        priority=50,
        payload={
            "fix_snippet": "modify app/__init__.py and lcu/lcu_client.py",
            "metadata": {"files": ["core/moon_proxy.py"]},
        },
    )
    assert t.status == TaskStatus.NEEDS_APPROVAL
    hits = set(t.payload.get("_frozen_file_hits", []))
    assert "app/__init__.py" in hits
    assert "lcu/lcu_client.py" in hits
    assert "core/moon_proxy.py" in hits


def test_non_frozen_file_reference_still_ready(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    t = s.file_task(
        op="edit-web",
        owner_agent="5",
        priority=30,
        payload={"target_file": "web/index.html"},
    )
    assert t.status == TaskStatus.READY
    assert "_frozen_file_hits" not in t.payload


def test_frozen_file_with_backslashes(tmp_path: Path) -> None:
    """Path separator normalization - Windows-style paths should match."""
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    t = s.file_task(
        op="edit-app",
        owner_agent="2",
        priority=50,
        payload={"path": r"app\_health_monitor.py"},
    )
    assert t.status == TaskStatus.NEEDS_APPROVAL
    assert "app/_health_monitor.py" in t.payload.get("_frozen_file_hits", [])


# -- insight_card helper ---------------------------------------------

@pytest.fixture()
def seeded_ahri(tmp_path: Path, monkeypatch):
    from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    import coaches.adaptation_hint as hint_mod
    monkeypatch.setattr(analyzer_mod, "DB_DIR", db_dir)
    monkeypatch.setattr(hint_mod, "DB_DIR", db_dir)

    # Stub item metadata so "itemA" passes the legendary filter
    fake_meta = {3000: {"name": "Riftmaker", "gold_total": 3000, "maps": {}}}
    monkeypatch.setattr(analyzer_mod, "_load_item_metadata", lambda: fake_meta)

    conn = sqlite3.connect(db_dir / "aram.db")
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        now = datetime.now(timezone.utc).isoformat()
        # 9 matches: 5 wins against Xerath (-> matchup), 4 losses against Morgana
        for i, (win, enemy) in enumerate([
            (1, "Xerath"), (1, "Xerath"), (1, "Xerath"),
            (1, "Xerath"), (1, "Xerath"),
            (0, "Morgana"), (0, "Morgana"), (0, "Morgana"),
            (0, "Morgana"),
        ]):
            cur = conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, 'Ahri', '[]', ?, 1200, ?, NULL, 'test')
                """,
                (now, now,
                 json.dumps([enemy, "Jinx", "Garen", "Rakan", "Lux"]),
                 win),
            )
            mid = cur.lastrowid
            # Add ITEM_PURCHASED for first-legendary tracking in wins only
            if win == 1:
                conn.execute(
                    """
                    INSERT INTO match_events
                      (match_id, ts_game_sec, event_type, state_json,
                       coach_output_json, outcome_30s_json)
                    VALUES (?, 300.0, 'ITEM_PURCHASED', ?, NULL, NULL)
                    """,
                    (mid, json.dumps({"item_id": 3000})),
                )
        conn.commit()
    finally:
        conn.close()

    from agents.agent4_coach_mentor import analyze_mode
    analyze_mode("aram")
    return db_dir


def test_insight_card_includes_champion_and_wr(seeded_ahri: Path) -> None:
    from coaches.adaptation_hint import insight_card
    card = insight_card("Ahri", "aram")
    assert card
    assert "Ahri" in card
    assert "ARAM" in card
    assert "56%" in card or "55%" in card     # 5/9 = 55.56%
    assert "n=9" in card


def test_insight_card_surfaces_first_leg_signal(seeded_ahri: Path) -> None:
    from coaches.adaptation_hint import insight_card
    card = insight_card("Ahri", "aram")
    # Won 5/5 games with Riftmaker as first leg -> +44% delta -> "rush Riftmaker"
    assert "Riftmaker" in card
    assert "rush" in card


def test_insight_card_mentions_enemy_counter_when_present(seeded_ahri: Path) -> None:
    from coaches.adaptation_hint import insight_card
    card = insight_card("Ahri", "aram", enemies=["Xerath", "Jinx"])
    assert "Xerath" in card     # activated counter from seed data


def test_insight_card_empty_for_unknown_champion(seeded_ahri: Path) -> None:
    from coaches.adaptation_hint import insight_card
    assert insight_card("Yasuo", "aram") == ""


def test_insight_card_respects_max_chars(seeded_ahri: Path) -> None:
    from coaches.adaptation_hint import insight_card
    card = insight_card("Ahri", "aram", max_chars=50)
    assert len(card) <= 50
    # Must not end with a mid-word fragment (bullet boundary preserved).
    assert not card.endswith(",")
