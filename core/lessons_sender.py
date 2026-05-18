"""Phase 2 sender - scans the memory dir for cross_project: true memories,
builds kind=lesson envelopes per the Phase 1 schema, dedupes against
ops/runtime/lessons_sent.jsonl, and POSTs each via core.bridge.send().

Entry points (thin CLI wrappers in tools/):
  dry_run()   - scan + categorise without sending; writes would_send.jsonl
  send_now()  - fire new eligible lessons; appends to lessons_sent.jsonl

Schema reference: docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = Path.home() / ".claude" / "projects" / "C--Riot-Commander" / "memory"
LESSONS_SENT_LOG = ROOT / "ops" / "runtime" / "lessons_sent.jsonl"
WOULD_SEND_LOG = ROOT / "ops" / "runtime" / "would_send_lessons.jsonl"

SCHEMA_VERSION = 1
ORIGIN = "rc"
MAX_FULL_MD_BYTES = 64 * 1024
ELIGIBLE_TYPES = frozenset({"feedback", "reference", "project"})
DO_NOT_SYNC_MARKER = "# DO NOT SYNC"

_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class Lesson:
    path: Path
    fm: dict
    body: str
    skip_reason: str | None  # None = eligible


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML-ish frontmatter as a flat dict + body. Minimal parser
    sufficient for memory-file shapes: scalar `key: value` lines and
    list-valued keys with `  - item` continuations."""
    m = _FM_RE.match(text.lstrip("﻿"))
    if not m:
        return ({}, text)
    fm_text, body = m.group(1), m.group(2)
    fm: dict = {}
    cur_list: list | None = None
    for raw in fm_text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - "):
            if cur_list is not None:
                cur_list.append(line[4:].strip())
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                cur_list = []
                fm[key] = cur_list
            else:
                if val.lower() in ("true", "false"):
                    fm[key] = (val.lower() == "true")
                else:
                    fm[key] = val
                cur_list = None
    return (fm, body)


def is_eligible(fm: dict, body: str) -> tuple[bool, str]:
    """Return (eligible, reason). Per §3 of Phase 1 schema."""
    mtype = fm.get("type")
    if mtype not in ELIGIBLE_TYPES:
        return (False, f"ineligible type ({mtype!r})")
    if not fm.get("cross_project"):
        return (False, "cross_project flag not set")
    if not fm.get("applies_when"):
        return (False, "missing applies_when")
    if body.lstrip().startswith(DO_NOT_SYNC_MARKER):
        return (False, "DO NOT SYNC marker")
    if len(body.encode("utf-8")) > MAX_FULL_MD_BYTES:
        return (False, "body exceeds size cap")
    return (True, "")


def body_hash(body: str) -> str:
    """sha256 of whitespace-normalized body. Used for the deterministic
    id prefix and for dedupe against lessons_sent.jsonl."""
    norm = "\n".join(line.rstrip() for line in body.strip().splitlines())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def lesson_id(origin: str, mem_type: str, title: str, bhash: str,
              ts: float | None = None) -> str:
    """Per §2: lesson-<sha256[:12]>-<unix_ts>. Prefix is deterministic on
    body; ts suffix lets receiver tell re-send (same prefix) from update
    (different prefix)."""
    seed = f"{origin}|{mem_type}|{title}|{bhash}".encode()
    prefix = hashlib.sha256(seed).hexdigest()[:12]
    suffix = int(ts if ts is not None else time.time())
    return f"lesson-{prefix}-{suffix}"


def build_envelope(path: Path, fm: dict, body: str,
                   ts: float | None = None) -> dict:
    """kind=lesson envelope per §2. `full_md` re-renders the frontmatter
    so the receiver can reconstruct a valid memory file by prepending
    its own provenance frontmatter (per §4)."""
    bhash = body_hash(body)
    lid = lesson_id(ORIGIN, fm["type"], fm["name"], bhash, ts=ts)
    full_md = f"---\n{_render_fm(fm)}---\n{body}"
    desc = fm.get("description") or fm.get("name") or ""
    return {
        "source": ORIGIN,
        "summary": desc[:100],
        "kind": "lesson",
        "id": lid,
        "target": "peer",
        "body": {
            "schema_version": SCHEMA_VERSION,
            "origin": ORIGIN,
            "mem_type": fm["type"],
            "title": fm["name"],
            "description": fm.get("description", ""),
            "applies_when": fm.get("applies_when", ""),
            "does_not_apply_when": fm.get("does_not_apply_when") or [],
            "summary": desc[:140],
            "full_md": full_md,
            "source_path": str(path),
            "origin_session": fm.get("originSessionId"),
        },
    }


_FM_KEY_ORDER = ("name", "description", "type", "cross_project",
                 "applies_when", "does_not_apply_when", "originSessionId")


def _render_fm(fm: dict) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for k in _FM_KEY_ORDER:
        if k in fm:
            out.append(_emit_kv(k, fm[k]))
            seen.add(k)
    for k, v in fm.items():
        if k not in seen:
            out.append(_emit_kv(k, v))
    return "\n".join(out) + "\n"


def _emit_kv(k: str, v) -> str:
    if isinstance(v, bool):
        return f"{k}: {str(v).lower()}"
    if isinstance(v, list):
        if not v:
            return f"{k}: []"
        return f"{k}:\n" + "\n".join(f"  - {item}" for item in v)
    return f"{k}: {v}"


def iter_eligible(memory_dir: Path = MEMORY_DIR) -> Iterator[Lesson]:
    for p in sorted(memory_dir.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, body = parse_frontmatter(text)
        ok, reason = is_eligible(fm, body)
        yield Lesson(path=p, fm=fm, body=body,
                     skip_reason=None if ok else reason)


def load_sent_ledger() -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    if not LESSONS_SENT_LOG.exists():
        return out
    for line in LESSONS_SENT_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        key = (entry.get("path", ""), entry.get("body_hash", ""))
        out[key] = entry
    return out


def dry_run(memory_dir: Path = MEMORY_DIR) -> dict:
    """Scan + categorize. Writes ops/runtime/would_send_lessons.jsonl with
    only the records that would be NEW sends (i.e., not already in
    lessons_sent.jsonl). Returns a summary report."""
    ledger = load_sent_ledger()
    scanned = 0
    eligible: list[Lesson] = []
    skipped: list[tuple[str, str]] = []
    for lesson in iter_eligible(memory_dir):
        scanned += 1
        if lesson.skip_reason is None:
            eligible.append(lesson)
        else:
            skipped.append((lesson.path.name, lesson.skip_reason))

    new_records: list[dict] = []
    already_sent: list[dict] = []
    for lesson in eligible:
        bhash = body_hash(lesson.body)
        rel_path = f"memory/{lesson.path.name}"
        env = build_envelope(lesson.path, lesson.fm, lesson.body)
        rec = {"path": rel_path, "body_hash": bhash, "envelope": env}
        if (rel_path, bhash) in ledger:
            already_sent.append(rec)
        else:
            new_records.append(rec)

    WOULD_SEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = WOULD_SEND_LOG.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in new_records:
            f.write(json.dumps(rec, ensure_ascii=False))
            f.write("\n")
    tmp.replace(WOULD_SEND_LOG)

    return {
        "scanned": scanned,
        "eligible": len(eligible),
        "would_send_new": len(new_records),
        "already_sent": len(already_sent),
        "skipped_by_reason": _bucket_reasons(skipped),
        "would_send_log": str(WOULD_SEND_LOG),
        "ledger_entries": len(ledger),
    }


def _bucket_reasons(skipped: list[tuple[str, str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for _name, reason in skipped:
        out[reason] = out.get(reason, 0) + 1
    return out


def _append_sent_ledger(entry: dict) -> None:
    LESSONS_SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LESSONS_SENT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def send_now(memory_dir: Path = MEMORY_DIR,
             only_path: str | None = None) -> dict:
    """Fire kind=lesson envelopes for every eligible memory not already in
    lessons_sent.jsonl. Appends to the sent-ledger with ack_received=False
    on each successful POST.

    `only_path` (optional): when set, restrict to a single memory path
    (basename match against memory_dir). Useful for first-lesson smoke.
    Returns a per-memory result list.
    """
    from core import bridge  # lazy - keeps dry-run path import-light

    if not bridge.is_configured():
        return {"ok": False, "reason": "bridge_not_configured", "results": []}

    ledger = load_sent_ledger()
    results: list[dict] = []
    for lesson in iter_eligible(memory_dir):
        if lesson.skip_reason is not None:
            continue
        if only_path and lesson.path.name != only_path:
            continue
        bhash = body_hash(lesson.body)
        rel_path = f"memory/{lesson.path.name}"
        if (rel_path, bhash) in ledger:
            results.append({"path": rel_path, "skipped": "already_sent"})
            continue
        env = build_envelope(lesson.path, lesson.fm, lesson.body)
        ok, detail = bridge.send(
            source=ORIGIN,
            summary=env["summary"],
            kind="lesson",
            entry_id=env["id"],
            target=env["target"],
            body=env["body"],
        )
        entry = {
            "ts": time.time(),
            "path": rel_path,
            "body_hash": bhash,
            "lesson_id": env["id"],
            "ack_received": False,
            "send_ok": ok,
            "send_detail": detail,
        }
        _append_sent_ledger(entry)
        results.append({"path": rel_path, "lesson_id": env["id"],
                        "send_ok": ok, "send_detail": detail})
    return {"ok": True, "results": results, "ledger_path": str(LESSONS_SENT_LOG)}


if __name__ == "__main__":
    import pprint
    pprint.pprint(dry_run())
