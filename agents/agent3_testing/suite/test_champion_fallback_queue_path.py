"""champion_fallback must read the real scheduler queue log (audit m01)."""
from __future__ import annotations

import json

from agents.agent1_lead import scheduler
from agents.agent5_ui import champion_fallback as cf


def test_queue_path_matches_scheduler():
    assert cf._QUEUE_LOG_PATH == scheduler.QUEUE_LOG


def test_user_note_reads_tmp_queue(tmp_path, monkeypatch):
    q = tmp_path / "task_queue.jsonl"
    rec = {"task": {"payload": {"user_text": "playing Jinx"}}}
    q.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    monkeypatch.setattr(cf, "_QUEUE_LOG_PATH", q)
    assert cf._try_recent_user_note() == "Jinx"


def test_user_note_tail_read_skips_truncated_head(tmp_path, monkeypatch):
    q = tmp_path / "task_queue.jsonl"
    filler = json.dumps({"task": {"payload": {"x": "a" * 200}}}) + "\n"
    rec = json.dumps({"task": {"payload": {"user_text": "playing Vayne"}}}) + "\n"
    q.write_text(filler * 600 + rec, encoding="utf-8")
    monkeypatch.setattr(cf, "_QUEUE_LOG_PATH", q)
    assert cf._try_recent_user_note() == "Vayne"
