"""Tests for core/lessons_confidence (Phase 4 (b) confidence scoring).

Covers: ledger aggregation, smoothed rate composition, bucket key
derivation, totals, confidence_for empty-bucket fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.lessons_confidence as conf
from core.smoothed_rates import laplace_rate, shrink


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.fixture
def isolated_ledgers(tmp_path, monkeypatch):
    sent = tmp_path / "lessons_sent.jsonl"
    received = tmp_path / "lessons_received.jsonl"
    monkeypatch.setattr(conf, "LESSONS_SENT_LOG", sent)
    monkeypatch.setattr(conf, "LESSONS_RECEIVED_LOG", received)
    return (sent, received)


# ---------------------------------------------------------------------------
# Empty / sparse ledgers
# ---------------------------------------------------------------------------

def test_empty_ledgers(isolated_ledgers):
    out = conf.compute_confidence()
    assert out["buckets"] == {}
    assert out["totals"]["sent"] == 0
    assert out["totals"]["received"] == 0
    # Smoothed rate of zero successes / zero attempts is the neutral 0.5
    assert out["totals"]["apply_rate"] == 0.5
    assert out["totals"]["took_rate"] == 0.5
    # No evidence -> shrink is 0 -> confidence is 0
    assert out["totals"]["confidence"] == 0.0


def test_confidence_for_unknown_bucket(isolated_ledgers):
    assert conf.confidence_for("peer", "feedback") == 0.0


# ---------------------------------------------------------------------------
# Sender aggregation
# ---------------------------------------------------------------------------

def test_sent_bucket_derives_type_from_path(isolated_ledgers):
    sent, _ = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
        {"lesson_id": "L2", "path": "memory/reference_y.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": False}},
        {"lesson_id": "L3", "path": "memory/project_z.md",
         "ack_received": False},
    ])
    rep = conf.compute_confidence()
    assert set(rep["buckets"].keys()) == {
        "peer:feedback", "peer:reference", "peer:project"}
    fb = rep["buckets"]["peer:feedback"]
    assert fb["sent"] == 1 and fb["acked"] == 1 and fb["took"] == 1
    ref = rep["buckets"]["peer:reference"]
    assert ref["acked"] == 1 and ref["took"] == 0
    proj = rep["buckets"]["peer:project"]
    assert proj["sent"] == 1 and proj["acked"] == 0


def test_sent_unknown_type(isolated_ledgers):
    sent, _ = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": "L1", "path": "memory/weirdo.md",
         "ack_received": False},
    ])
    rep = conf.compute_confidence()
    assert "peer:unknown" in rep["buckets"]


# ---------------------------------------------------------------------------
# Receiver aggregation
# ---------------------------------------------------------------------------

def test_received_bucket_decisions(isolated_ledgers):
    _, received = isolated_ledgers
    _write_jsonl(received, [
        {"lesson_id": "L1", "from": "peer", "decision": "applied",
         "memory_path": "/m/feedback_synced_atx_abc.md"},
        {"lesson_id": "L2", "from": "peer", "decision": "discarded"},
        {"lesson_id": "L3", "from": "peer", "decision": "rejected"},
        {"lesson_id": "L4", "from": "peer", "decision": "skipped_neg_match"},
        {"lesson_id": "L5", "from": "peer", "decision": "queued",
         "memory_path": "/m/reference_synced_atx_xyz.md"},
    ])
    rep = conf.compute_confidence()
    # L1 type=feedback (from path), L5 type=reference
    fb = rep["buckets"]["peer:feedback"]
    assert fb["received"] == 1 and fb["applied"] == 1
    ref = rep["buckets"]["peer:reference"]
    assert ref["received"] == 1 and ref["queued"] == 1
    # discarded/rejected/skipped have no memory_path -> unknown bucket
    unk = rep["buckets"]["peer:unknown"]
    assert unk["received"] == 3
    assert unk["discarded"] == 1
    assert unk["rejected"] == 1
    assert unk["skipped_neg_match"] == 1


# ---------------------------------------------------------------------------
# Merge + rate composition
# ---------------------------------------------------------------------------

def test_merge_combines_sent_and_received(isolated_ledgers):
    sent, received = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_a.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
    ])
    _write_jsonl(received, [
        {"lesson_id": "L2", "from": "peer", "decision": "applied",
         "memory_path": "/m/feedback_synced_atx_xx.md"},
    ])
    rep = conf.compute_confidence()
    fb = rep["buckets"]["peer:feedback"]
    assert fb["sent"] == 1 and fb["received"] == 1
    assert fb["acked"] == 1 and fb["applied"] == 1
    assert fb["took"] == 1


def test_apply_rate_matches_laplace(isolated_ledgers):
    sent, received = isolated_ledgers
    _write_jsonl(received, [
        {"lesson_id": f"L{i}", "from": "peer", "decision": "applied",
         "memory_path": f"/m/feedback_synced_atx_{i:03x}.md"}
        for i in range(3)
    ] + [
        {"lesson_id": f"X{i}", "from": "peer", "decision": "discarded",
         "memory_path": f"/m/feedback_synced_atx_{i:03x}d.md"}
        for i in range(2)
    ])
    rep = conf.compute_confidence()
    fb = rep["buckets"]["peer:feedback"]
    assert fb["applied"] == 3 and fb["discarded"] == 2
    assert fb["decided"] == 5
    assert fb["apply_rate"] == pytest.approx(laplace_rate(3, 5))
    # took_rate over zero acked -> neutral 0.5
    assert fb["took_rate"] == pytest.approx(0.5)


def test_took_rate_uses_acked_denominator(isolated_ledgers):
    sent, _ = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": f"L{i}", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied",
                 "took": (i % 2 == 0)}}
        for i in range(4)
    ])
    rep = conf.compute_confidence()
    fb = rep["buckets"]["peer:feedback"]
    assert fb["acked"] == 4 and fb["took"] == 2
    assert fb["took_rate"] == pytest.approx(laplace_rate(2, 4))


def test_confidence_uses_shrink_weight(isolated_ledgers):
    sent, received = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
    ])
    _write_jsonl(received, [
        {"lesson_id": "L2", "from": "peer", "decision": "applied",
         "memory_path": "/m/feedback_synced_atx_xx.md"},
    ])
    rep = conf.compute_confidence()
    fb = rep["buckets"]["peer:feedback"]
    # decided=1, acked=1, evidence=2
    expected = shrink(2) * laplace_rate(1, 1) * laplace_rate(1, 1)
    assert fb["confidence"] == pytest.approx(expected)


def test_confidence_for_known_bucket(isolated_ledgers):
    sent, _ = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
    ])
    score = conf.confidence_for("peer", "feedback")
    assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------

def test_totals_sum_buckets(isolated_ledgers):
    sent, received = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
        {"lesson_id": "L2", "path": "memory/reference_y.md",
         "ack_received": False},
    ])
    _write_jsonl(received, [
        {"lesson_id": "L3", "from": "peer", "decision": "applied",
         "memory_path": "/m/feedback_synced_atx_xx.md"},
        {"lesson_id": "L4", "from": "peer", "decision": "queued",
         "memory_path": "/m/reference_synced_atx_yy.md"},
    ])
    rep = conf.compute_confidence()
    t = rep["totals"]
    assert t["sent"] == 2
    assert t["received"] == 2
    assert t["acked"] == 1
    assert t["took"] == 1
    assert t["applied"] == 1
    assert t["queued"] == 1
    assert t["decided"] == 2


def test_compute_alpha_k_passthrough(isolated_ledgers):
    sent, _ = isolated_ledgers
    _write_jsonl(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
    ])
    custom = conf.compute_confidence(alpha=2.0, k=10.0)
    assert custom["alpha"] == 2.0
    assert custom["k"] == 10.0
