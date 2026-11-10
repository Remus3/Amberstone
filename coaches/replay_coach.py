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
        Returns {ok, match_id, summary, key_moments[], suggestions[], raw,
        elapsed_ms}. Never raises; a failure returns ok=False with a
        friendly summary line and logs the raw error.

Caller hooks:
    - Postgame flow (after a real match ends, look up match_id in
      rewind history and call analyze_match)
    - Manual replay browse (UI button: "coach this match" given a
      match_id from the dashboard's session-games list)
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("rc.replay_coach")

_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"

# Upper bound on timeline rows pulled per match, to keep the blob (and the
# prompt built from it) bounded. See _load_match for why the ORDER BY matters
# more than the number.
_EVENT_ROW_CAP = 600
_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 800

# A match id is an opaque lookup key (Riot ids look like "NA1_1234567890").
# Anything outside this shape cannot be a rewind row, so it is refused at the
# public entry and never echoed back into a user-facing line.
_MATCH_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Per-label body caps. The summary is a paragraph; moments and suggestions are
# single lines (the prompt asks for under 220 chars each).
_SUMMARY_CAP = 600
_LINE_CAP = 300

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


def _as_int(value: Any) -> int:
    """SQLite columns are dynamically typed, so a numeric column can hold TEXT,
    REAL or NULL. Anything that does not read as a finite number is 0; never
    raises."""
    if isinstance(value, int):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _connect_read_only(path: Path) -> sqlite3.Connection:
    """Open the rewind store read-only. A plain connect() creates an empty
    database when the file is missing - here, when it vanishes between the
    exists() check and the open - and would leave it at the live path."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _load_match(match_id: str) -> dict[str, Any] | None:
    if not _REWIND_DB.exists():
        return None
    conn = None
    try:
        conn = _connect_read_only(_REWIND_DB)
        conn.row_factory = sqlite3.Row
        m = conn.execute(
            "SELECT * FROM matches WHERE match_id = ?", (match_id,)
        ).fetchone()
        if not m:
            return None
        participants = [dict(r) for r in conn.execute(
            "SELECT * FROM participants WHERE match_id = ?", (match_id,)
        ).fetchall()]
        # Match-SHAPING events first, then everything else, and only then the
        # row cap. A flat `ORDER BY timestamp_ms LIMIT 600` looks harmless and
        # is not: median events per match is 879 and 2677 of 2961 matches
        # exceed the cap, so it silently truncated the timeline at roughly the
        # midpoint. Measured on one clean 22-minute game it stopped at 11
        # minutes, leaving 2 of 9 BUILDING_KILL events visible - baron, late
        # objectives and inhibitors could not appear in the narrative at all.
        # The cap still exists to bound the prompt; it now spends its budget on
        # the events that matter instead of on early item purchases.
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM timeline_events WHERE match_id = ? "
            "ORDER BY CASE WHEN event_type IN "
            "  ('CHAMPION_KILL','ELITE_MONSTER_KILL','BUILDING_KILL',"
            "   'CHAMPION_SPECIAL_KILL','TURRET_PLATE_DESTROYED') "
            "  THEN 0 ELSE 1 END, timestamp_ms LIMIT ?",
            (match_id, _EVENT_ROW_CAP)
        ).fetchall()]
        # Restore chronology - the priority ordering above is a selection
        # device, and every consumer downstream assumes time order. The key is
        # coerced: a TEXT timestamp beside an INTEGER one made sort() raise.
        events.sort(key=lambda e: _as_int(e.get("timestamp_ms")))
        return {"match": dict(m), "participants": participants, "events": events}
    except (sqlite3.Error, OSError) as exc:
        logger.warning("rewind read failed match=%s: %s", match_id, exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error as exc:
                logger.debug("rewind close failed: %s", exc)


def _format_for_prompt(blob: dict[str, Any]) -> str:
    """Compact text representation - keep within Haiku context budget.
    Numeric columns are coerced, so a junk value renders as 0, not a raise."""
    m = blob["match"]
    parts = blob["participants"]
    events = blob["events"]
    tracked = m.get("tracked_champion_name") or "?"
    win = "WIN" if _as_int(m.get("tracked_win")) else "LOSS"
    dur = max(0, _as_int(m.get("game_duration_s"))) // 60
    kda = "/".join(str(max(0, _as_int(m.get(k))))
                   for k in ("tracked_kills", "tracked_deaths", "tracked_assists"))
    header = (f"{tracked} {kda} ({win}, {dur} min) on patch "
              f"{m.get('patch') or '?'} mode {m.get('game_mode') or '?'}")
    team_lines = []
    for p in parts:
        cn = p.get("champion_name") or "?"
        lvl = max(0, _as_int(p.get("champ_level")))
        team_lines.append(
            f"  team{_as_int(p.get('team_id'))} {cn} {p.get('lane') or '?'} {lvl}L")
    # Sample early/mid/late events
    sample = events[:50] + events[len(events)//2:len(events)//2 + 50] + events[-50:]
    seen = set()
    ev_lines = []
    for e in sample:
        et = e.get("event_type") or "?"
        ts = max(0, _as_int(e.get("timestamp_ms"))) // 1000
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
    skips horizontal rules (---) and h1 headings. The summary keeps up to
    _SUMMARY_CAP chars; each moment and suggestion up to _LINE_CAP."""
    out: dict[str, Any] = {"summary": "", "key_moments": [], "suggestions": []}
    # Strip markdown bold/italic wrappers around the whole line.
    raw_lines = (raw or "").splitlines()
    lines: list[str] = []
    for line in raw_lines:
        s = line.rstrip()
        # Strip leading/trailing **, *, _, # so labels & content normalize.
        s = re.sub(r"^\s*[#*_\s]+", "", s)
        s = re.sub(r"[*_]+$", "", s)
        s = s.replace("**", "").replace("__", "")
        # Drop horizontal rules.
        if re.match(r"^[-=*]{3,}$", s):
            continue
        lines.append(s)
    cur_key: str | None = None
    cur_buf: list[str] = []

    def _flush() -> None:
        if cur_key is None:
            return
        body = " ".join(b.strip() for b in cur_buf if b.strip())
        if not body:
            return
        if cur_key == "summary":
            out["summary"] = body[:_SUMMARY_CAP]
        elif cur_key.startswith("moment"):
            out["key_moments"].append(body[:_LINE_CAP])
        elif cur_key.startswith("suggestion"):
            out["suggestions"].append(body[:_LINE_CAP])

    for line in lines:
        s = line.strip()
        if not s:
            continue
        # Match label patterns at start of line (case-insensitive).
        low = s.lower()
        new_key: str | None = None
        inline_body = ""
        if low.startswith("summary:"):
            new_key = "summary"
            inline_body = s.split(":", 1)[1].strip()
        elif low.startswith("moment "):
            new_key = "moment"
            inline_body = s.split(":", 1)[1].strip() if ":" in s else ""
        elif low.startswith("suggestion "):
            new_key = "suggestion"
            inline_body = s.split(":", 1)[1].strip() if ":" in s else ""
        if new_key is not None:
            _flush()
            cur_key = new_key
            cur_buf = [inline_body] if inline_body else []
        else:
            cur_buf.append(s)
    _flush()
    return out


def _usable_key(api_key: object) -> str:
    """The key to send, or "" when it cannot authenticate (not a string, or
    blank once stripped)."""
    return api_key.strip() if isinstance(api_key, str) else ""


def _valid_match_id(match_id: object) -> bool:
    return isinstance(match_id, str) and _MATCH_ID_RE.fullmatch(match_id) is not None


def _reply_text(resp: Any) -> str:
    """Join every text block. Reading content[0] alone missed a reply whose
    first block is not text (a thinking block, for one)."""
    parts = []
    for block in getattr(resp, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def analyze_match(match_id: str, *, api_key: str | None) -> dict[str, Any]:
    """Generate a postgame writeup for a match in `rewind_history.db`.

    Never raises: every failure returns the dict with ok=False and a friendly
    summary line; the raw error goes to the log only."""
    out: dict[str, Any] = {
        "ok": False, "match_id": match_id, "summary": "",
        "key_moments": [], "suggestions": [], "raw": "", "elapsed_ms": 0,
    }
    key = _usable_key(api_key)
    if not key:
        out["summary"] = "(API key missing - coach disabled)"
        return out
    if not _valid_match_id(match_id):
        out["match_id"] = ""
        out["summary"] = "(invalid match id)"
        return out
    blob = _load_match(match_id)
    if blob is None:
        out["summary"] = "(match not in rewind history)"
        return out
    t0 = time.perf_counter()
    client = None
    try:
        prompt = _format_for_prompt(blob)
        import anthropic
        # max_retries=0: the SDK default of 2 retries a timeout, so one call
        # could block for three timeouts plus backoff and bill attempts
        # cost_tracker never sees.
        client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=0)
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
        raw = _reply_text(resp)
    except Exception as exc:  # noqa: BLE001
        # summary is user-facing - never leak the exception type/message. Log
        # the raw error, render a friendly degraded line.
        out["summary"] = "(coaching unavailable - try again)"
        out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.warning("replay coach: %s", exc)
        return out
    finally:
        # Release the connection pool on every path. The call is over (and may
        # have been billed), so a failed close must not cost the answer.
        if client is not None:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("replay coach: client close: %s", type(exc).__name__)
    fields = _parse_response(raw)
    out.update({
        "ok": bool(fields["summary"] or fields["key_moments"]),
        "summary":     fields["summary"],
        "key_moments": fields["key_moments"][:5],
        "suggestions": fields["suggestions"][:3],
        "raw":         raw[:2000],
        "elapsed_ms":  int((time.perf_counter() - t0) * 1000),
    })
    return out
