"""Phase 4 (b) - lesson confidence scoring.

Reads both ledgers (the sender's `lessons_sent.jsonl` and the receiver's
`lessons_received.jsonl`) and computes per-(peer, mem_type) confidence
buckets:

  apply_rate  = laplace_rate(applied, decided)
                  - own evidence that lessons of (peer, mem_type) are
                    worth applying when this side is the receiver
  took_rate   = laplace_rate(took, applied)
                  - peer evidence that lessons WE sent of (peer, mem_type)
                    "took" (didn't get auto-reverted, no test failure)
  confidence  = shrink(decided) * apply_rate * took_rate
                  - a single combined score in [0, 1] usable as a tuning
                    signal for "should auto-apply be widened for this
                    bucket?"

The section-4 decision matrix in Phase 1 is static ("tooling/infra/config only");
this module exposes the empirical evidence for tuning it without flipping
it. Phase 4 ships the surface; whether to actually shift the gate is an
operator decision (the matrix lives in lessons_receiver._is_inbound_lesson
+ post_decision; no automatic gate-flip from this module).

Vision section 5 Phase 4 reference: docs/_archive/2026-05-02-rc-peer/CROSS_CLAUDE_LEARNING_SYNC_VISION_2026-05-02.md
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.smoothed_rates import laplace_rate, shrink, DEFAULT_ALPHA, DEFAULT_K

ROOT = Path(__file__).resolve().parent.parent
LESSONS_SENT_LOG = ROOT / "ops" / "runtime" / "lessons_sent.jsonl"
LESSONS_RECEIVED_LOG = ROOT / "ops" / "runtime" / "lessons_received.jsonl"

ELIGIBLE_TYPES = ("feedback", "reference", "project")

logger = logging.getLogger("rc.core.lessons_confidence")


# ---------------------------------------------------------------------------
# Ledger I/O (read-only)
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _empty_bucket() -> dict[str, Any]:
    return {
        "sent": 0,
        "acked": 0,
        "took": 0,
        "received": 0,
        "applied": 0,
        "queued": 0,
        "discarded": 0,
        "rejected": 0,
        "skipped_neg_match": 0,
    }


def _bucket_key(peer: str, mem_type: str) -> str:
    return f"{peer or 'unknown'}:{mem_type or 'unknown'}"


def _mem_type_from_lesson_id(lid: str, received: list[dict]) -> str:
    """Receiver ledger rows don't carry mem_type directly - the peer's
    envelope did, but the receiver only logged the decision. We try to
    recover it from any provenance memory_path that names the type prefix.
    Falls back to 'unknown'."""
    for row in received:
        if row.get("lesson_id") != lid:
            continue
        mp = row.get("memory_path")
        if not mp:
            return "unknown"
        name = Path(mp).name.lower()
        for t in ELIGIBLE_TYPES:
            if name.startswith(f"{t}_synced") or name.startswith(f"{t}_"):
                return t
        return "unknown"
    return "unknown"


def _sent_bucket(rows: list[dict]) -> dict[str, dict[str, Any]]:
    """Aggregate sender ledger rows by (peer=target, mem_type=from path basename).

    The sent ledger doesn't store mem_type or target explicitly - the path
    is `memory/<type_basename>.md`, and the target is always the peer
    (RC -> peer for v1). We derive type from the filename prefix.
    """
    out: defaultdict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    for row in rows:
        # Path looks like "memory/feedback_x.md" or "memory/reference_y.md"
        path = row.get("path") or ""
        basename = Path(path).name.lower()
        mem_type = "unknown"
        for t in ELIGIBLE_TYPES:
            if basename.startswith(f"{t}_"):
                mem_type = t
                break
        # peer = the side we sent to. v1 senders target 'peer' but the
        # ack carries the responder's source string which is the real
        # peer identity (gracefully tolerates a hypothetical 3-way bridge).
        ack = row.get("ack") or {}
        peer = ack.get("source") or "peer"
        key = _bucket_key(peer, mem_type)
        b = out[key]
        b["sent"] += 1
        if row.get("ack_received"):
            b["acked"] += 1
            if ack.get("took"):
                b["took"] += 1
    return dict(out)


def _received_bucket(rows: list[dict]) -> dict[str, dict[str, Any]]:
    """Aggregate receiver ledger rows by (peer=from, mem_type=derived).

    Receiver rows don't carry mem_type for the rejected/skipped paths
    (where no memory was written). We treat those as type=unknown so
    the schema-gate signal stays visible in aggregates without inflating
    the eligible-type buckets.
    """
    out: defaultdict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    for row in rows:
        peer = row.get("from") or "unknown"
        mem_type = _mem_type_from_lesson_id(row.get("lesson_id") or "", rows)
        key = _bucket_key(peer, mem_type)
        b = out[key]
        b["received"] += 1
        decision = (row.get("decision") or "").lower()
        if decision in b:
            b[decision] += 1
    return dict(out)


def _merge(sent: dict[str, dict[str, Any]],
           received: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key in set(sent) | set(received):
        b = _empty_bucket()
        for src in (sent.get(key, {}), received.get(key, {})):
            for k, v in src.items():
                b[k] = b.get(k, 0) + v
        out[key] = b
    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def compute_confidence(*, alpha: float = DEFAULT_ALPHA,
                       k: float = DEFAULT_K) -> dict[str, Any]:
    """Return a per-bucket confidence report.

    Output shape:
        {
            "alpha": float,
            "k": float,
            "buckets": {
                "<peer>:<mem_type>": {
                    "sent": int, "acked": int, "took": int,
                    "received": int, "applied": int, "queued": int,
                    "discarded": int, "rejected": int, "skipped_neg_match": int,
                    "apply_rate": float,    # smoothed
                    "took_rate": float,     # smoothed
                    "confidence": float,    # shrink-weighted combined
                },
                ...
            },
            "totals": {<bucket fields summed>},
        }

    All rates use the shared smoothed_rates primitives so they compose
    cleanly with the augment/pickban surfaces (CLAUDE.md #90 decision).
    """
    sent = _sent_bucket(_read_jsonl(LESSONS_SENT_LOG))
    received = _received_bucket(_read_jsonl(LESSONS_RECEIVED_LOG))
    merged = _merge(sent, received)

    totals = _empty_bucket()
    for b in merged.values():
        for k_field, v in b.items():
            totals[k_field] = totals.get(k_field, 0) + v

    out_buckets: dict[str, dict[str, Any]] = {}
    for key, b in merged.items():
        decided = b["applied"] + b["queued"] + b["discarded"]
        apply_rate = laplace_rate(b["applied"], decided, alpha=alpha)
        took_rate = laplace_rate(b["took"], b["acked"], alpha=alpha)
        confidence = shrink(decided + b["acked"], k=k) * apply_rate * took_rate
        out_buckets[key] = {
            **b,
            "decided": decided,
            "apply_rate": apply_rate,
            "took_rate": took_rate,
            "confidence": confidence,
        }

    decided_total = totals["applied"] + totals["queued"] + totals["discarded"]
    totals_view = {
        **totals,
        "decided": decided_total,
        "apply_rate": laplace_rate(totals["applied"], decided_total, alpha=alpha),
        "took_rate": laplace_rate(totals["took"], totals["acked"], alpha=alpha),
        "confidence": shrink(decided_total + totals["acked"], k=k) *
                      laplace_rate(totals["applied"], decided_total, alpha=alpha) *
                      laplace_rate(totals["took"], totals["acked"], alpha=alpha),
    }

    return {
        "alpha": alpha,
        "k": k,
        "buckets": out_buckets,
        "totals": totals_view,
    }


def confidence_for(peer: str, mem_type: str,
                   *, alpha: float = DEFAULT_ALPHA,
                   k: float = DEFAULT_K) -> float:
    """Single-number score for a (peer, mem_type) bucket. Returns 0.0
    on an unknown bucket (no data -> no confidence)."""
    report = compute_confidence(alpha=alpha, k=k)
    bucket = report["buckets"].get(_bucket_key(peer, mem_type))
    if bucket is None:
        return 0.0
    return float(bucket["confidence"])
