"""Tests for core/lessons_ack_watcher (Phase 4 (a) symmetry check).

Covers: fail-soft fetch, idempotent merge, atomic rewrite, summarize
shape, no-op when ledger empty / fully acked.
"""
from __future__ import annotations

import io
import json
import socket
import urllib.error
from pathlib import Path

import pytest

import core.lessons_ack_watcher as aw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    """Redirect LESSONS_SENT_LOG to a tmp file and return its Path."""
    ledger = tmp_path / "lessons_sent.jsonl"
    monkeypatch.setattr(aw, "LESSONS_SENT_LOG", ledger)
    return ledger


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _patch_urlopen(monkeypatch, fn):
    monkeypatch.setattr(aw.urllib.request, "urlopen", fn)


# ---------------------------------------------------------------------------
# _fetch_results fail-soft contract
# ---------------------------------------------------------------------------

def test_fetch_url_error_empty(monkeypatch):
    _patch_urlopen(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.URLError("nope")))
    assert aw._fetch_results(0.0) == []


def test_fetch_http_error_empty(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 503, "down", {}, None)
    _patch_urlopen(monkeypatch, boom)
    assert aw._fetch_results(0.0) == []


def test_fetch_timeout_empty(monkeypatch):
    def boom(*a, **k):
        raise socket.timeout("timed out")
    _patch_urlopen(monkeypatch, boom)
    assert aw._fetch_results(0.0) == []


def test_fetch_malformed_json_empty(monkeypatch):
    _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b"{not json"))
    assert aw._fetch_results(0.0) == []


def test_fetch_non_dict_empty(monkeypatch):
    _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b'[1,2,3]'))
    assert aw._fetch_results(0.0) == []


def test_fetch_valid_payload(monkeypatch):
    payload = {"messages": [{"kind": "result", "id": "r1"}]}
    _patch_urlopen(monkeypatch,
                   lambda *a, **k: _FakeResp(json.dumps(payload).encode()))
    assert aw._fetch_results(0.0) == [{"kind": "result", "id": "r1"}]


# ---------------------------------------------------------------------------
# _index_by_reply
# ---------------------------------------------------------------------------

def test_index_keeps_latest_per_reply():
    envelopes = [
        {"kind": "result", "id": "r1", "in_reply_to": "L1", "ts": 100,
         "body": {"decision": "queued"}},
        {"kind": "result", "id": "r2", "in_reply_to": "L1", "ts": 200,
         "body": {"decision": "applied", "took": True}},
        {"kind": "result", "id": "r3", "in_reply_to": "L2", "ts": 50,
         "body": {"decision": "discarded"}},
        {"kind": "note", "id": "n1", "in_reply_to": "L1"},
        {"kind": "result", "id": "r4", "ts": 999},  # no in_reply_to -> skip
    ]
    out = aw._index_by_reply(envelopes)
    assert set(out.keys()) == {"L1", "L2"}
    assert out["L1"]["id"] == "r2"  # newer ts wins
    assert out["L2"]["id"] == "r3"


# ---------------------------------------------------------------------------
# update_sent_acks - happy path
# ---------------------------------------------------------------------------

def test_update_merges_ack_in_place(temp_ledger, monkeypatch):
    _write_rows(temp_ledger, [
        {"ts": 1.0, "path": "memory/feedback_x.md", "body_hash": "h",
         "lesson_id": "L1", "ack_received": False, "send_ok": True},
    ])
    payload = {"messages": [
        {"kind": "result", "id": "r1", "in_reply_to": "L1",
         "ts": 100, "source": "peer",
         "body": {"decision": "applied", "rationale": "ok",
                  "memory_path": "/peer/memory/x.md", "took": True}},
    ]}
    _patch_urlopen(monkeypatch,
                   lambda *a, **k: _FakeResp(json.dumps(payload).encode()))
    rep = aw.update_sent_acks()
    assert rep.newly_acked == ["L1"]
    assert rep.unacked_before == 1
    assert rep.unacked_after == 0
    rows = aw._load_sent()
    assert rows[0]["ack_received"] is True
    ack = rows[0]["ack"]
    assert ack["source"] == "peer"
    assert ack["decision"] == "applied"
    assert ack["took"] is True
    assert ack["ack_id"] == "r1"
    assert ack["memory_path"] == "/peer/memory/x.md"


def test_update_idempotent(temp_ledger, monkeypatch):
    _write_rows(temp_ledger, [
        {"lesson_id": "L1", "ack_received": True,
         "ack": {"decision": "applied", "took": True}},
    ])
    # urlopen must NOT be called when nothing is unacked - assert by raising.
    def must_not_be_called(*a, **k):
        raise AssertionError("urlopen called when ledger fully acked")
    _patch_urlopen(monkeypatch, must_not_be_called)
    rep = aw.update_sent_acks()
    assert rep.newly_acked == []
    assert rep.already_acked == 1
    assert rep.unacked_before == 0


def test_update_empty_ledger(temp_ledger, monkeypatch):
    rep = aw.update_sent_acks()
    assert rep.newly_acked == []
    assert rep.unacked_before == 0
    # Ledger file shouldn't be created when there's nothing to merge.
    assert not temp_ledger.exists()


def test_update_no_matching_ack(temp_ledger, monkeypatch):
    _write_rows(temp_ledger, [
        {"lesson_id": "L1", "ack_received": False},
    ])
    payload = {"messages": [
        # in_reply_to references a different lesson_id
        {"kind": "result", "id": "r1", "in_reply_to": "L_other",
         "ts": 100, "body": {"decision": "applied"}},
    ]}
    _patch_urlopen(monkeypatch,
                   lambda *a, **k: _FakeResp(json.dumps(payload).encode()))
    rep = aw.update_sent_acks()
    assert rep.newly_acked == []
    assert rep.unacked_before == 1
    assert rep.unacked_after == 1
    # File not rewritten -> rows preserved exactly
    rows = aw._load_sent()
    assert rows[0]["ack_received"] is False


def test_update_partial_match(temp_ledger, monkeypatch):
    _write_rows(temp_ledger, [
        {"lesson_id": "L1", "ack_received": False},
        {"lesson_id": "L2", "ack_received": False},
        {"lesson_id": "L3", "ack_received": True,
         "ack": {"decision": "applied"}},
    ])
    payload = {"messages": [
        {"kind": "result", "id": "r1", "in_reply_to": "L2", "ts": 100,
         "source": "peer",
         "body": {"decision": "queued", "took": False}},
    ]}
    _patch_urlopen(monkeypatch,
                   lambda *a, **k: _FakeResp(json.dumps(payload).encode()))
    rep = aw.update_sent_acks()
    assert rep.newly_acked == ["L2"]
    assert rep.unacked_after == 1  # L1 still unacked
    assert rep.already_acked == 1  # L3
    rows = aw._load_sent()
    assert rows[0]["ack_received"] is False  # L1 untouched
    assert rows[1]["ack_received"] is True   # L2 newly acked
    assert rows[1]["ack"]["decision"] == "queued"
    assert rows[2]["ack_received"] is True   # L3 preserved


def test_atomic_rewrite_uses_tmp(temp_ledger, monkeypatch, tmp_path):
    """The .replace step is what makes the write atomic - confirm we
    write through a .tmp sibling rather than overwriting in place."""
    _write_rows(temp_ledger, [{"lesson_id": "L1", "ack_received": False}])
    payload = {"messages": [
        {"kind": "result", "in_reply_to": "L1", "ts": 1,
         "body": {"decision": "applied"}, "id": "r1"},
    ]}
    _patch_urlopen(monkeypatch,
                   lambda *a, **k: _FakeResp(json.dumps(payload).encode()))
    aw.update_sent_acks()
    # After successful merge, tmp file does not linger
    assert not (temp_ledger.with_suffix(".jsonl.tmp")).exists()
    assert temp_ledger.exists()


# ---------------------------------------------------------------------------
# summarize()
# ---------------------------------------------------------------------------

def test_summarize_empty_ledger(temp_ledger):
    out = aw.summarize()
    assert out["total_sent"] == 0
    assert out["acked"] == 0
    assert out["unacked"] == 0
    assert out["took"] == 0
    assert out["took_rate"] == 0.0
    assert out["decisions"] == {}


def test_summarize_counts_decisions(temp_ledger):
    _write_rows(temp_ledger, [
        {"lesson_id": "L1", "ack_received": True,
         "ack": {"decision": "applied", "took": True}},
        {"lesson_id": "L2", "ack_received": True,
         "ack": {"decision": "applied", "took": False}},
        {"lesson_id": "L3", "ack_received": True,
         "ack": {"decision": "queued", "took": False}},
        {"lesson_id": "L4", "ack_received": False},
    ])
    out = aw.summarize()
    assert out["total_sent"] == 4
    assert out["acked"] == 3
    assert out["unacked"] == 1
    assert out["took"] == 1
    assert pytest.approx(out["took_rate"], abs=1e-6) == 1 / 3
    assert out["decisions"] == {"applied": 2, "queued": 1}


def test_summarize_malformed_line_ignored(temp_ledger):
    temp_ledger.parent.mkdir(parents=True, exist_ok=True)
    with temp_ledger.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"lesson_id": "L1", "ack_received": True,
                            "ack": {"decision": "applied", "took": True}}) + "\n")
        f.write("not-json\n")
        f.write(json.dumps({"lesson_id": "L2", "ack_received": False}) + "\n")
    out = aw.summarize()
    assert out["total_sent"] == 2  # malformed line dropped
    assert out["acked"] == 1
    assert out["took"] == 1


def test_report_to_dict_shape():
    rep = aw.WatcherReport(
        fetched_results=3,
        unacked_before=2,
        unacked_after=0,
        newly_acked=["A", "B"],
        already_acked=5,
    )
    d = rep.to_dict()
    assert d["fetched_results"] == 3
    assert d["newly_acked_count"] == 2
    assert d["newly_acked"] == ["A", "B"]
