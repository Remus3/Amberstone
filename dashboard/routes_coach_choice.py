"""POST /api/coach-choice - log the user's A/B tutoring selection.

The dashboard's coach_choices.js panel POSTs a small JSON body whenever
the operator clicks one of the A/B/C chips surfaced by the coach. The
choice is appended to ``data/decisions_log.jsonl`` via the shared
DecisionStore so post-game review can replay the timeline with the
coach context the operator saw at decision time.

Read-only behavior: no game state is modified, no coach output is
changed, no remediation is triggered. Logging only.
"""
from __future__ import annotations

import json
import logging

from core.decision_detector import DecisionStore

log = logging.getLogger("rc.web_dashboard")

_VALID_BANDS = {"low", "mid", "high"}
_MAX_LABEL = 80
_MAX_SOURCE = 32

_STORE: DecisionStore | None = None


def _store() -> DecisionStore:
    global _STORE
    if _STORE is None:
        _STORE = DecisionStore()
    return _STORE


def _coerce_str(v, limit: int) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "..."
    return s


def _serve_coach_choice(h, body) -> None:
    """POST /api/coach-choice
    Body: {choice_key, choice_label, confidence, source_tag, game_context?}
    """
    if not isinstance(body, dict):
        h._send(400, b'{"error":"body must be a JSON object"}', "application/json")
        return
    choice_key = _coerce_str(body.get("choice_key"), 4).upper()[:1]
    if not choice_key:
        h._send(400, b'{"error":"choice_key required"}', "application/json")
        return
    choice_label = _coerce_str(body.get("choice_label"), _MAX_LABEL)
    if not choice_label:
        h._send(400, b'{"error":"choice_label required"}', "application/json")
        return
    band = _coerce_str(body.get("confidence"), 8).lower()
    if band not in _VALID_BANDS:
        band = "mid"
    source = _coerce_str(body.get("source_tag"), _MAX_SOURCE)
    game_ctx = body.get("game_context")
    if not isinstance(game_ctx, dict):
        game_ctx = {}
    try:
        entry = _store().record_coach_choice(
            choice_key=choice_key,
            choice_label=choice_label,
            confidence=band,
            source_tag=source,
            game_context=game_ctx,
        )
        h._send(200, json.dumps({"ok": True, "logged_ts": entry["ts_unix"]}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("coach-choice POST failed: %s", exc)
        h._send(500, b'{"error":"log_append_failed"}', "application/json")


def _equals(p: str):
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES: list = []
POST_ROUTES = [
    (_equals("/api/coach-choice"), _serve_coach_choice),
]
