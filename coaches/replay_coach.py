"""
coaches/replay_coach.py - postgame coaching from rewind_history.db.

Bridges the gap between "I just finished a match" and "what should I
have done differently". Pulls the participant + timeline rows for a
given match_id from `rewind_history.db` (2846 matches indexed) and
asks Haiku for a structured writeup.

This is a scaled-down version of the speculative "replay coaching"
roadmap item - proper .rofl parsing requires Riot's encrypted replay
format, which is non-public. We use the timeline_events table instead,
which is rich enough for "what happened and why" analysis.

Public API:
    analyze_match(match_id: str, *, api_key: str) -> dict
        Returns {ok, summary, key_moments[], suggestions[], elapsed_ms}.

Caller hooks:
    - Postgame flow (after a real match ends, look up match_id in
      rewind history and call analyze_match)
    - Manual replay browse (UI button: "coach this match" given a
      match_id from the dashboard's session-games list)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("rc.replay_coach")

_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"
_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 800

_PROMPT = """You are a postgame coach analyzing a finished League match
from the player's perspective. The data is RAW timeline + participant
data (no live vision, no real-time advice). Produce structured insight.

Format your reply as:
Summary: <one-paragraph result + key story of the match>
Moment 1: <minute:sec> - <what happened, why it mattered>
Moment 2: <minute:sec> - <what happened, why it mattered>
Moment 3: <minute:sec> - <what happened, why it mattered>
Suggestion 1: <one specific lesson the player should take away>
Suggestion 2: <one specific lesson the player should take away>

Keep each line under 220 chars. Be concrete - reference times, names,
items where relevant. Don't fabricate details not in the data."""


def _load_match(match_id: str) -> dict[str, Any] | None:
    if not _REWIND_DB.exists():
        return None
    conn = None
    try:
        conn = sqlite3.connect(_REWIND_DB)
        conn.row_factory = sqlite3.Row
        m = conn.execute(
            "SELECT * FROM matches WHERE match_id = ?", (match_id,)
        ).fetchone()
        if not m:
            return None
        participants = [dict(r) for r in conn.execute(
            "SELECT * FROM participants WHERE match_id = ?", (match_id,)
        ).fetchall()]
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM timeline_events WHERE match_id = ? "
            "ORDER BY timestamp_ms LIMIT 600", (match_id,)
        ).fetchall()]
        return {"match": dict(m), "participants": participants, "events": events}
    except Exception as exc:  # noqa: BLE001
        logger.warning("rewind read failed match=%s: %s", match_id, exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _format_for_prompt(blob: dict[str, Any]) -> str:
    """Compact text representation - keep within Haiku context budget."""
    m = blob["match"]
    parts = blob["participants"]
    events = blob["events"]
    tracked = m.get("tracked_champion_name") or "?"
    win = "WIN" if m.get("tracked_win") else "LOSS"
    dur = (m.get("game_duration_s") or 0) // 60
    kda = f"{m.get('tracked_kills',0)}/{m.get('tracked_deaths',0)}/{m.get('tracked_assists',0)}"
    header = f"{tracked} {kda} ({win}, {dur} min) on patch {m.get('patch','?')} mode {m.get('game_mode','?')}"
    team_lines = []
    for p in parts:
        cn = p.get("champion_name") or "?"
        kp = f"{p.get('champion_name','?')} {p.get('champ_level',0)}L"
        team_lines.append(f"  team{p.get('team_id')} {cn} {p.get('lane','?')} {kp}")
    # Sample early/mid/late events
    sample = events[:50] + events[len(events)//2:len(events)//2 + 50] + events[-50:]
    seen = set()
    ev_lines = []
    for e in sample:
        et = e.get("event_type") or "?"
        ts = (e.get("timestamp_ms") or 0) // 1000
        key = (et, ts // 30)  # dedupe within a 30 s window
        if key in seen:
            continue
        seen.add(key)
        ev_lines.append(f"  {ts//60}:{ts%60:02d} {et}")
    return (
        f"{header}\n\nParticipants:\n" + "\n".join(team_lines) +
        "\n\nTimeline samples:\n" + "\n".join(ev_lines[:80])
    )


def _parse_response(raw: str) -> dict[str, Any]:
    """Parse Haiku output. Labels may be inline ("Summary: text...") OR on
    their own line with the body following on subsequent lines until the
    next label. Handles markdown wrapping (**Summary:**, *Moment 1:*) +
    skips horizontal rules (---) and h1 headings."""
    import re as _re
    out: dict[str, Any] = {"summary": "", "key_moments": [], "suggestions": []}
    # Strip markdown bold/italic wrappers around the whole line.
    raw_lines = (raw or "").splitlines()
    lines: list[str] = []
    for l in raw_lines:
        s = l.rstrip()
        # Strip leading/trailing **, *, _, # so labels & content normalize.
        s = _re.sub(r"^\s*[#*_\s]+", "", s)
        s = _re.sub(r"[*_]+$", "", s)
        s = s.replace("**", "").replace("__", "")
        # Drop horizontal rules.
        if _re.match(r"^[-=*]{3,}$", s):
            continue
        lines.append(s)
    cur_key: str | None = None
    cur_buf: list[str] = []

    def _flush() -> None:
        if cur_key is None:
            return
        body = " ".join(b.strip() for b in cur_buf if b.strip())[:300]
        if not body:
            return
        if cur_key == "summary":
            out["summary"] = body[:600]
        elif cur_key.startswith("moment"):
            out["key_moments"].append(body)
        elif cur_key.startswith("suggestion"):
            out["suggestions"].append(body)

    for line in lines:
        s = line.strip()
        if not s:
            continue
        # Match label patterns at start of line (case-insensitive).
        low = s.lower()
        new_key: str | None = None
        inline_body = ""
        if low.startswith("summary:"):
            new_key = "summary"; inline_body = s.split(":", 1)[1].strip()
        elif low.startswith("moment "):
            new_key = "moment"; inline_body = s.split(":", 1)[1].strip() if ":" in s else ""
        elif low.startswith("suggestion "):
            new_key = "suggestion"; inline_body = s.split(":", 1)[1].strip() if ":" in s else ""
        if new_key is not None:
            _flush()
            cur_key = new_key
            cur_buf = [inline_body] if inline_body else []
        else:
            cur_buf.append(s)
    _flush()
    return out


def analyze_match(match_id: str, *, api_key: str | None) -> dict[str, Any]:
    """Generate a postgame writeup for a match in `rewind_history.db`."""
    out: dict[str, Any] = {
        "ok": False, "match_id": match_id, "summary": "",
        "key_moments": [], "suggestions": [], "raw": "", "elapsed_ms": 0,
    }
    if not api_key:
        out["summary"] = "(API key missing - coach disabled)"
        return out
    blob = _load_match(match_id)
    if blob is None:
        out["summary"] = f"(match {match_id} not in rewind_history.db)"
        return out
    prompt = _format_for_prompt(blob)
    t0 = time.time()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=_MAX_TOKENS,
            system=[
                {"type": "text", "text": _PROMPT,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": prompt}],
            timeout=20,
        )
        # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker.
        try:
            from core.cost_tracker import record_anthropic_response
            record_anthropic_response(resp, model=_MODEL, purpose="replay_coach")
        except Exception as exc:  # noqa: BLE001
            logger.debug("cost_tracker record: %s", exc)
        raw = resp.content[0].text if resp.content else ""
    except Exception as exc:  # noqa: BLE001
        # summary is user-facing - never leak the exception type/message. Log
        # the raw error, render a friendly degraded line.
        out["summary"] = "(coaching unavailable - try again)"
        logger.warning("replay coach: %s", exc)
        return out
    fields = _parse_response(raw)
    out.update({
        "ok": bool(fields["summary"] or fields["key_moments"]),
        "summary":     fields["summary"],
        "key_moments": fields["key_moments"][:5],
        "suggestions": fields["suggestions"][:3],
        "raw":         raw[:2000],
        "elapsed_ms":  int((time.time() - t0) * 1000),
    })
    return out
