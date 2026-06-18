"""Phase 4 (a) - symmetry check / ack watcher.

Polls the local bridge for kind=result envelopes whose `in_reply_to`
matches an unacked entry in `ops/runtime/lessons_sent.jsonl`, then
merges the ack body in-place. After this runs:

  ledger entry gains:
    ack_received: true
    ack: {ts, source, decision, rationale, memory_path, took, ack_id}

The peer's "did this lesson take?" signal (per section 5 of the
Phase 1 schema) becomes operator-visible via `tools/lessons_status.py` /
`/api/lessons/status` rather than requiring a manual grep of the
bridge log.

Schema reference: docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md
Vision Phase 4 reference: docs/_archive/2026-05-02-rc-peer/CROSS_CLAUDE_LEARNING_SYNC_VISION_2026-05-02.md section 5

Designed read-only w.r.t. the bridge (HTTP GET only; the ack itself
was already posted by the peer's receiver). Fail-soft: bridge down
yields a zero-work result, never raises.
"""
from __future__ import annotations

import json
import logging
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
LESSONS_SENT_LOG = ROOT / "ops" / "runtime" / "lessons_sent.jsonl"

LEGION_BRIDGE = "https://legion-rc:8888/api/bridge"
LOOKBACK_S = 7 * 24 * 3600  # last 7 days - acks arrive shortly after sends
TIMEOUT = 4.0

# Transport auth is delegated to Tailscale WireGuard; optional cert-pin later.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

logger = logging.getLogger("rc.core.lessons_ack_watcher")


# ---------------------------------------------------------------------------
# Bridge fetch (mirrors lessons_receiver._fetch_bridge fail-soft contract)
# ---------------------------------------------------------------------------

def _fetch_results(since: float) -> list[dict]:
    """GET kind=result envelopes from the local bridge. [] on any failure."""
    url = f"{LEGION_BRIDGE}?since={since}&limit=500&kind=result"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=_SSL_CTX) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, socket.timeout, TimeoutError,
            ConnectionError, OSError, ssl.SSLError) as e:
        logger.debug("bridge unreachable (%s): %s", url, e)
        return []
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("bridge returned malformed JSON: %s", e)
        return []
    if not isinstance(data, dict):
        logger.warning("bridge payload not a dict: %s", type(data).__name__)
        return []
    return data.get("messages") or []


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------

def _load_sent() -> list[dict]:
    """Return the full sent ledger as a list of dict rows (preserves order)."""
    if not LESSONS_SENT_LOG.exists():
        return []
    out: list[dict] = []
    for line in LESSONS_SENT_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _rewrite_sent(rows: list[dict]) -> None:
    """Atomic rewrite of the sent ledger (tmp + replace, the project rule)."""
    LESSONS_SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = LESSONS_SENT_LOG.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(LESSONS_SENT_LOG)


# ---------------------------------------------------------------------------
# Ack merge
# ---------------------------------------------------------------------------

def _ack_payload(result_env: dict) -> dict:
    """Extract the audit-relevant fields from a kind=result envelope."""
    body = result_env.get("body") or {}
    return {
        "ts": float(result_env.get("ts") or 0.0),
        "source": result_env.get("source") or "",
        "decision": str(body.get("decision") or ""),
        "rationale": str(body.get("rationale") or ""),
        "memory_path": body.get("memory_path"),
        "took": bool(body.get("took") or False),
        "ack_id": str(result_env.get("id") or ""),
    }


def _index_by_reply(envelopes: list[dict]) -> dict[str, dict]:
    """lesson_id -> latest result envelope referencing it.

    Multiple acks for the same lesson are possible (e.g. an auto-revert
    sends a follow-up). We keep the newest by ts so the latest decision
    wins; older ones stay reconstructable from the bridge log.
    """
    by_reply: dict[str, dict] = {}
    for env in envelopes:
        if env.get("kind") != "result":
            continue
        lid = env.get("in_reply_to")
        if not lid or not isinstance(lid, str):
            continue
        existing = by_reply.get(lid)
        if existing is None or float(env.get("ts") or 0) > float(existing.get("ts") or 0):
            by_reply[lid] = env
    return by_reply


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@dataclass
class WatcherReport:
    fetched_results: int
    unacked_before: int
    unacked_after: int
    newly_acked: list[str]
    already_acked: int

    def to_dict(self) -> dict:
        return {
            "fetched_results": self.fetched_results,
            "unacked_before": self.unacked_before,
            "unacked_after": self.unacked_after,
            "newly_acked": list(self.newly_acked),
            "newly_acked_count": len(self.newly_acked),
            "already_acked": self.already_acked,
        }


def update_sent_acks(*, since: Optional[float] = None) -> WatcherReport:
    """Merge any new bridge acks into lessons_sent.jsonl.

    Idempotent: rows already carrying ack_received=true are skipped
    (the body is preserved as-is). Returns a structured report so the
    CLI / dashboard can surface what changed without re-reading the
    ledger.

    `since` defaults to (now - LOOKBACK_S). Caller can override for a
    deeper backfill on first run.
    """
    rows = _load_sent()
    already_acked = sum(1 for r in rows if r.get("ack_received"))
    unacked_before = len(rows) - already_acked

    if unacked_before == 0:
        return WatcherReport(
            fetched_results=0,
            unacked_before=0,
            unacked_after=0,
            newly_acked=[],
            already_acked=already_acked,
        )

    if since is None:
        since = time.time() - LOOKBACK_S
    results = _fetch_results(since)
    by_reply = _index_by_reply(results)

    newly_acked: list[str] = []
    for row in rows:
        if row.get("ack_received"):
            continue
        lid = row.get("lesson_id")
        if not lid:
            continue
        env = by_reply.get(lid)
        if env is None:
            continue
        row["ack_received"] = True
        row["ack"] = _ack_payload(env)
        newly_acked.append(lid)

    if newly_acked:
        _rewrite_sent(rows)

    unacked_after = unacked_before - len(newly_acked)
    return WatcherReport(
        fetched_results=len(results),
        unacked_before=unacked_before,
        unacked_after=unacked_after,
        newly_acked=newly_acked,
        already_acked=already_acked,
    )


def summarize() -> dict:
    """Snapshot of the sent ledger without touching the bridge.

    Used by the read-only dashboard route + the CLI's first paint
    (before / after a refresh).
    """
    rows = _load_sent()
    n = len(rows)
    acked = [r for r in rows if r.get("ack_received")]
    took = sum(1 for r in acked if (r.get("ack") or {}).get("took"))
    decisions: dict[str, int] = {}
    for r in acked:
        d = ((r.get("ack") or {}).get("decision") or "unknown").lower()
        decisions[d] = decisions.get(d, 0) + 1
    return {
        "ledger_path": str(LESSONS_SENT_LOG),
        "total_sent": n,
        "acked": len(acked),
        "unacked": n - len(acked),
        "took": took,
        "took_rate": (took / len(acked)) if acked else 0.0,
        "decisions": decisions,
    }
