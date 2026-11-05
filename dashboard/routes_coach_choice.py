"""POST /api/coach-choice - log the user's A/B tutoring selection.

The dashboard's coach_choices.js panel POSTs a small JSON body whenever
the operator clicks one of the A/B/C chips surfaced by the coach. The
choice is appended to ``data/decisions_log.jsonl`` via the shared
DecisionStore so post-game review can replay the timeline with the
coach context the operator saw at decision time.

Read-only behavior: no game state is modified, no coach output is
changed, no remediation is triggered. Logging only.

Body contract (s144 true-audit cycle 82 - the route used to ``str()`` any
JSON value it was handed and store ``game_context`` whole):
  choice_key    string; its first character, upper-cased, must be A / B / C
                (the only keys core.coach_choices ever puts on a chip). 400
                otherwise.
  choice_label  string, control characters dropped, whitespace collapsed,
                capped at _MAX_LABEL characters INCLUDING the "..." marker.
                400 when absent, not a string, or empty after the scrub.
  confidence    "low" / "mid" / "high"; anything else is logged as "mid".
  source_tag    optional string, scrubbed and capped at _MAX_SOURCE; 400
                when present and not a string.
  game_context  optional object; ONLY the keys the dashboard snapshot sends
                (web/js/panels/coach_choices.js _gameContextSnapshot) are
                kept - strings scrubbed and capped, numbers finite, non-bool
                and in range. Everything else is dropped, so a click logs a
                bounded line into an append-only file nothing rotates.

Responses: 200 {"ok": true, "logged_ts": <float>}; 400 on a bad body; 503
{"ok": false, "error": ...} when the store could not write the line (safe
to retry); 500 on an unexpected failure, logged with its traceback.
"""
from __future__ import annotations

import json
import logging
import unicodedata

from core.decision_detector import DecisionStore
from dashboard._matchers import equals

log = logging.getLogger("rc.web_dashboard")

_VALID_BANDS = {"low", "mid", "high"}
_VALID_KEYS = "ABC"
_MAX_LABEL = 80
_MAX_SOURCE = 32
_MAX_CTX_STR = 40
_MAX_CTX_NUM = 1_000_000
_ELLIPSIS = "..."

# The exact keys _gameContextSnapshot() sends, split by the type it sends.
_CTX_STR_KEYS = ("mode_key", "champion", "kda")
_CTX_NUM_KEYS = ("level", "game_time_s", "cs")

_NOT_LOGGED = json.dumps({
    "ok": False,
    "error": "choice not logged - the decision log is unavailable, retry",
}).encode("utf-8")

_STORE: DecisionStore | None = None


def _store() -> DecisionStore:
    global _STORE
    if _STORE is None:
        _STORE = DecisionStore()
    return _STORE


def _scrub(s: str) -> str:
    """Collapse whitespace runs to one space; drop other controls + surrogates.

    Same rule core.coach_choices applies to the chip text this echoes."""
    kept = []
    for ch in s:
        if ch.isspace():
            kept.append(" ")
        elif unicodedata.category(ch) in ("Cc", "Cs"):
            continue
        else:
            kept.append(ch)
    return " ".join("".join(kept).split())


def _cap(s: str, limit: int) -> str:
    """``s`` cut to at most ``limit`` characters, the marker included."""
    if len(s) > limit:
        s = s[: max(0, limit - len(_ELLIPSIS))].rstrip() + _ELLIPSIS
    return s


def _text(v: object, limit: int) -> str | None:
    """Scrubbed + capped text for a str, "" for None, None for anything else."""
    if v is None:
        return ""
    if not isinstance(v, str):
        return None
    return _cap(_scrub(v), limit)


def _context(raw: object) -> dict:
    """The allow-listed, bounded subset of a caller's game_context."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k in _CTX_STR_KEYS:
        v = raw.get(k)
        if isinstance(v, str):
            s = _cap(_scrub(v), _MAX_CTX_STR)
            if s:
                out[k] = s
    for k in _CTX_NUM_KEYS:
        v = raw.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        # The range test also drops NaN (every comparison is False) and
        # +/-Infinity, so no non-finite float reaches the strict store.
        if 0 <= v <= _MAX_CTX_NUM:
            out[k] = v
    return out


def _bad(h, msg: str) -> None:
    h._send(400, json.dumps({"error": msg}).encode("utf-8"), "application/json")


def _serve_coach_choice(h, body) -> None:
    """POST /api/coach-choice
    Body: {choice_key, choice_label, confidence, source_tag, game_context?}
    """
    if not isinstance(body, dict):
        _bad(h, "body must be a JSON object")
        return
    raw_key = body.get("choice_key")
    key = _text(raw_key, 4) if raw_key is not None else None
    choice_key = (key or "")[:1].upper()
    if not choice_key:
        _bad(h, "choice_key required")
        return
    if choice_key not in _VALID_KEYS:
        _bad(h, "choice_key must be A, B or C")
        return
    choice_label = _text(body.get("choice_label"), _MAX_LABEL)
    if not choice_label:
        _bad(h, "choice_label required")
        return
    source = _text(body.get("source_tag"), _MAX_SOURCE)
    if source is None:
        _bad(h, "source_tag must be a string")
        return
    band = _text(body.get("confidence"), 8)
    band = band.lower() if band else ""
    if band not in _VALID_BANDS:
        band = "mid"
    try:
        entry = _store().record_coach_choice(
            choice_key=choice_key,
            choice_label=choice_label,
            confidence=band,
            source_tag=source,
            game_context=_context(body.get("game_context")),
        )
    except Exception:  # last-resort 500, traceback logged
        log.exception("coach-choice POST failed")
        h._send(500, b'{"ok":false,"error":"log_append_failed"}',
                "application/json")
        return
    if entry is None:
        # The store logged the cause; nothing was written, so a retry is safe.
        h._send(503, _NOT_LOGGED, "application/json")
        return
    h._send(200, json.dumps({"ok": True, "logged_ts": entry["ts_unix"]}).encode("utf-8"),
            "application/json")


GET_ROUTES: list = []
POST_ROUTES = [
    (equals("/api/coach-choice"), _serve_coach_choice),
]
