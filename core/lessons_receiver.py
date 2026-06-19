"""Phase 2 receiver - consumes kind=lesson envelopes from the bridge log,
runs the auto-gates, and either auto-handles (reject / skipped_neg_match)
or surfaces the lesson to Claude for triage (apply / queue / discard).

Schema reference: docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md

Two entry points (the CLI wrappers live in tools/):
  - pull(): query the bridge, run schema + neg-match gates, append the
    auto-handled outcomes to ops/runtime/lessons_received.jsonl + send
    acks. Returns the remaining lessons that need Claude triage.
  - post_decision(): finalize one lesson with a Claude-decided outcome
    (applied | queued | discarded). Writes the provenance memory + a
    MEMORY.md index pointer + ack to peer.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Project root: <root>/core/lessons_receiver.py
ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = Path.home() / ".claude" / "projects" / "C--Riot-Commander" / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
LESSONS_RECEIVED_LOG = ROOT / "ops" / "runtime" / "lessons_received.jsonl"
CLAUDE_MD = ROOT / "CLAUDE.md"

LEGION_BRIDGE = "https://legion-rc:8888/api/bridge"
LOOKBACK_S = 86400  # last 24h
TIMEOUT = 4.0
SUPPORTED_SCHEMA_VERSION = 1
THIS_TARGET = "rc"

VALID_DECISIONS = frozenset({"applied", "queued", "discarded"})
DECISION_TO_STATUS = {
    "applied": "applied",
    "queued": "pending_apply",
    "discarded": "discarded",
}

# Transport auth is delegated to Tailscale WireGuard; optional cert-pin later.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

logger = logging.getLogger("rc.core.lessons_receiver")


# ---------------------------------------------------------------------------
# Bridge fetch
# ---------------------------------------------------------------------------

def _fetch_bridge(since: float) -> list[dict]:
    """Query the bridge log. Returns [] on any network/parse failure.

    Callers (``pull`` / ``_find_lesson_envelope``) treat [] as "no
    lessons", so a bridge outage degrades gracefully instead of
    crashing the ``/process-incoming-lessons`` skill. Mirrors the
    fail-soft pattern in ``core.daemon_slayer_client._post_json``.
    """
    url = f"{LEGION_BRIDGE}?since={since}&limit=100"
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
# Ledger
# ---------------------------------------------------------------------------

def _load_ledger() -> dict[str, dict]:
    """lesson_id -> ledger entry. Lessons appear at most once."""
    out: dict[str, dict] = {}
    if not LESSONS_RECEIVED_LOG.exists():
        return out
    for line in LESSONS_RECEIVED_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        lid = entry.get("lesson_id")
        if lid:
            out[lid] = entry
    return out


def _append_ledger(entry: dict) -> None:
    LESSONS_RECEIVED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LESSONS_RECEIVED_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Negative-match probe (pre-triage filter)
# ---------------------------------------------------------------------------

_LOCAL_CONTEXT_CACHE: Optional[str] = None


def _local_context_blob() -> str:
    """Concatenated lower-cased text the receiver substring-searches for
    negative-trigger matches. Built lazily, cached for the process."""
    global _LOCAL_CONTEXT_CACHE
    if _LOCAL_CONTEXT_CACHE is not None:
        return _LOCAL_CONTEXT_CACHE
    parts: list[str] = [
        platform.system().lower(),
        platform.platform().lower(),
        socket.gethostname().lower(),
        ROOT.name.lower(),
        str(ROOT).lower(),
    ]
    try:
        if CLAUDE_MD.exists():
            text = CLAUDE_MD.read_text(encoding="utf-8", errors="replace")
            parts.append(text.lower()[:64 * 1024])
    except OSError:
        pass
    try:
        if MEMORY_DIR.exists():
            parts.extend(p.name.lower() for p in MEMORY_DIR.glob("*.md"))
    except OSError:
        pass
    _LOCAL_CONTEXT_CACHE = "\n".join(parts)
    return _LOCAL_CONTEXT_CACHE


def _neg_match(trigger: str) -> bool:
    """True if the negative trigger substring-matches the local context."""
    if not trigger:
        return False
    return trigger.lower() in _local_context_blob()


def find_neg_match(triggers: Iterable[str]) -> Optional[str]:
    for t in triggers:
        if _neg_match(t):
            return t
    return None


# ---------------------------------------------------------------------------
# Ack to peer
# ---------------------------------------------------------------------------

def _ack(lesson_id: str, decision: str, rationale: str,
         memory_path: Optional[str] = None,
         took: bool = False, peer: str = "peer") -> tuple[bool, str]:
    """POST a kind=result ack to the peer per section 5 of the schema."""
    try:
        from core import bridge
    except Exception as exc:  # noqa: BLE001
        return (False, f"bridge import failed: {exc}")
    body: dict = {"decision": decision, "rationale": rationale, "took": took}
    if memory_path:
        body["memory_path"] = memory_path
    return bridge.send(
        source=THIS_TARGET,
        summary=f"lesson {lesson_id} {decision}",
        kind="result",
        target=peer,
        body=body,
        in_reply_to=lesson_id,
    )


# ---------------------------------------------------------------------------
# Pull - finds new lessons, runs cheap gates, returns triage queue
# ---------------------------------------------------------------------------

@dataclass
class PullReport:
    auto_handled: list[dict]   # rejected + skipped_neg_match (with ack outcome)
    pending: list[dict]        # full lesson envelopes for Claude triage
    skipped_already_handled: int
    fetched_total: int


def _is_inbound_lesson(msg: dict) -> bool:
    return (
        msg.get("kind") == "lesson"
        and msg.get("target") == THIS_TARGET
        and bool(msg.get("id"))
        and msg.get("source") != THIS_TARGET
    )


def pull() -> PullReport:
    msgs = _fetch_bridge(time.time() - LOOKBACK_S)
    fetched_total = len(msgs)
    candidates = [m for m in msgs if _is_inbound_lesson(m)]

    ledger = _load_ledger()
    auto_handled: list[dict] = []
    pending: list[dict] = []
    skipped_already_handled = 0

    candidates.sort(key=lambda m: m.get("ts", 0))
    for env in candidates:
        lid = env["id"]
        if lid in ledger:
            skipped_already_handled += 1
            continue

        body = env.get("body") or {}
        peer = env.get("source") or "peer"

        # Gate 1: schema_version
        sv = body.get("schema_version")
        if sv != SUPPORTED_SCHEMA_VERSION:
            rationale = f"unsupported schema_version={sv!r}"
            ok, ack_detail = _ack(lid, "rejected", rationale, peer=peer)
            entry = {
                "ts": time.time(), "lesson_id": lid, "from": peer,
                "decision": "rejected", "memory_path": None,
                "rationale": rationale, "ack_ok": ok, "ack_detail": ack_detail,
            }
            _append_ledger(entry)
            auto_handled.append(entry)
            continue

        # Gate 2: does_not_apply_when (pre-triage filter, per section 4)
        neg = body.get("does_not_apply_when") or []
        match = find_neg_match(neg) if isinstance(neg, list) else None
        if match:
            rationale = f"matched does_not_apply_when: {match!r}"
            ok, ack_detail = _ack(lid, "skipped_neg_match", rationale,
                                  peer=peer)
            entry = {
                "ts": time.time(), "lesson_id": lid, "from": peer,
                "decision": "skipped_neg_match", "memory_path": None,
                "rationale": rationale, "ack_ok": ok, "ack_detail": ack_detail,
            }
            _append_ledger(entry)
            auto_handled.append(entry)
            continue

        pending.append(env)

    return PullReport(
        auto_handled=auto_handled,
        pending=pending,
        skipped_already_handled=skipped_already_handled,
        fetched_total=fetched_total,
    )


# ---------------------------------------------------------------------------
# Post-decision - finalize one lesson with Claude's triage outcome
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _strip_origin_frontmatter(full_md: str) -> str:
    """Return the body of the lesson, dropping the origin's frontmatter
    block. Receiver prepends its own provenance frontmatter."""
    m = _FM_RE.match(full_md.lstrip("\ufeff"))
    if not m:
        return full_md
    return m.group(2)


def _short_id(lesson_id: str) -> str:
    """Last 6 hex chars of the deterministic prefix - enough for filename
    disambiguation without dragging the unix-ts suffix in."""
    parts = lesson_id.split("-")
    if len(parts) >= 2 and re.fullmatch(r"[0-9a-f]+", parts[1]):
        return parts[1][-6:]
    return re.sub(r"[^0-9a-z]", "", lesson_id.lower())[-6:] or "000000"


def _safe_peer(peer: str) -> str:
    """Filesystem-safe peer token. The envelope `source` is remote-authored;
    never let it carry path separators, dots, or newlines into a filename
    or frontmatter line (path-traversal / injection surface)."""
    return re.sub(r"[^a-z0-9]", "", (peer or "").lower())[:32] or "peer"


def _fm_scalar(value: str) -> str:
    """Collapse remote-authored text to a single frontmatter-safe line.
    Newlines in title/description would otherwise inject frontmatter keys."""
    return " ".join(str(value).split())


def _provenance_filename(mem_type: str, peer: str, lesson_id: str) -> str:
    safe_type = re.sub(r"[^a-z]", "", (mem_type or "lesson").lower()) or "lesson"
    return f"{safe_type}_synced_{_safe_peer(peer)}_{_short_id(lesson_id)}.md"


def _build_memory_file(envelope: dict, decision: str,
                       receiver_notes: str) -> tuple[Path, str, str]:
    """Compute the provenance memory filename + the file content. Returns
    (path, frontmatter_name, file_text)."""
    body = envelope.get("body") or {}
    peer = envelope.get("source") or "peer"
    safe_peer = _safe_peer(peer)
    lesson_id = envelope["id"]
    mem_type = body.get("mem_type") or "reference"
    safe_type = re.sub(r"[^a-z]", "", mem_type.lower()) or "reference"
    title = _fm_scalar(body.get("title") or lesson_id)
    description = _fm_scalar(body.get("description") or title)
    full_md = body.get("full_md") or ""
    origin_body = _strip_origin_frontmatter(full_md)

    fm_name = f"{title} (synced from {safe_peer})"
    status = DECISION_TO_STATUS[decision]

    fm_lines = [
        "---",
        f"name: {fm_name}",
        f"description: {description}",
        f"type: {safe_type}",
        "cross_project: false",
        f"synced_from: {safe_peer}",
        f"synced_at: {int(time.time())}",
        f"synced_lesson_id: {_fm_scalar(lesson_id)}",
        f"status: {status}",
        "---",
        "",
    ]
    body_lines = [
        origin_body.rstrip(),
        "",
        "## Receiver notes",
        "",
        receiver_notes.strip(),
        "",
    ]
    text = "\n".join(fm_lines) + "\n".join(body_lines)
    fname = _provenance_filename(mem_type, peer, lesson_id)
    return (MEMORY_DIR / fname, fm_name, text)


def _index_pointer(filename: str, fm_name: str, description: str) -> str:
    """One-line MEMORY.md entry per CLAUDE.md format: '- [Title](file.md) - hook'."""
    hook = description.strip().splitlines()[0] if description else fm_name
    if len(hook) > 110:
        hook = hook[:107] + "..."
    return f"- [{fm_name}]({filename}) - {hook}\n"


def _append_to_memory_index(line: str) -> bool:
    if not MEMORY_INDEX.exists():
        return False
    text = MEMORY_INDEX.read_text(encoding="utf-8")
    if line.strip() in text:
        return True  # idempotent
    if not text.endswith("\n"):
        text += "\n"
    text += line
    # Atomic write (project rule) - an interrupted plain write_text would
    # truncate the operator's MEMORY.md index.
    tmp = MEMORY_INDEX.with_suffix(MEMORY_INDEX.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(MEMORY_INDEX)
    return True


def post_decision(lesson_id: str, decision: str, rationale: str,
                  receiver_notes: str = "") -> dict:
    """Finalize a lesson with a Claude-decided outcome. Writes the
    provenance memory (when applied/queued), updates MEMORY.md, appends
    the ledger entry, and sends the ack to the peer."""
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"decision must be one of {sorted(VALID_DECISIONS)}; got {decision!r}"
        )

    # Re-fetch the lesson envelope from the bridge so we don't have to
    # round-trip the full body through the CLI.
    envelope = _find_lesson_envelope(lesson_id)
    if envelope is None:
        raise LookupError(
            f"lesson {lesson_id} not found in last {LOOKBACK_S}s of bridge log"
        )

    peer = envelope.get("source") or "peer"
    memory_path: Optional[str] = None
    wrote_index = False

    if decision in ("applied", "queued"):
        path, fm_name, text = _build_memory_file(
            envelope, decision, receiver_notes or rationale)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write (project rule): tmp + replace.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        memory_path = str(path)
        body = envelope.get("body") or {}
        line = _index_pointer(path.name, fm_name, body.get("description") or fm_name)
        wrote_index = _append_to_memory_index(line)

    took = (decision == "applied")
    ok, ack_detail = _ack(lesson_id, decision, rationale,
                          memory_path=memory_path, took=took, peer=peer)

    entry = {
        "ts": time.time(),
        "lesson_id": lesson_id,
        "from": peer,
        "decision": decision,
        "memory_path": memory_path,
        "rationale": rationale,
        "ack_ok": ok,
        "ack_detail": ack_detail,
        "wrote_index": wrote_index,
    }
    _append_ledger(entry)
    return entry


def _find_lesson_envelope(lesson_id: str) -> Optional[dict]:
    msgs = _fetch_bridge(time.time() - LOOKBACK_S)
    for m in msgs:
        if m.get("kind") == "lesson" and m.get("id") == lesson_id:
            return m
    return None


# ---------------------------------------------------------------------------
# CLI used by tools/lessons_pull.py and tools/lessons_post.py
# ---------------------------------------------------------------------------

def _report_to_dict(rep: PullReport) -> dict:
    return {
        "now": time.time(),
        "fetched_total": rep.fetched_total,
        "auto_handled_count": len(rep.auto_handled),
        "auto_handled": rep.auto_handled,
        "pending_count": len(rep.pending),
        "pending": rep.pending,
        "skipped_already_handled": rep.skipped_already_handled,
        "ledger_path": str(LESSONS_RECEIVED_LOG),
    }


if __name__ == "__main__":
    sys.exit("Use tools/lessons_pull.py or tools/lessons_post.py")
