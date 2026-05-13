# arch: cs archetype pick rest endpoints | section=dashboard | frozen=no
"""Phase 3 (s176, 2026-05-12) — REST endpoints for the CS archetype picker.

Mirror of ``routes_lobby_aux`` shape: GET reads, POST writes, with atomic
file persistence under the hood via ``core.archetype_picks``. The picker
UI in ``web/js/panels/champ_select.js`` calls these to set the operator's
preferred archetype per champion; the dashboard's localStorage mirror
provides instant first-paint after page reload.

Routes:

* ``GET  /api/cs-archetype-pick?champion=<id>``
    Returns the merged pick (explicit override OR DDragon-tag default).
    No champion param returns the full persisted map under "picks" +
    the archetype enum metadata under "archetypes".

* ``POST /api/cs-archetype-pick``
    Body: ``{ champion, primary, secondary?, source? }``.
    Returns the canonicalized entry.

* ``DELETE`` via POST with ``{ champion, clear: true }`` — falls back
    to default. No separate DELETE method to keep the dispatch table
    simple; the picker UI calls POST+clear when the operator resets.
"""
import json
import logging
from urllib.parse import urlparse, parse_qs

from core.archetype_mismatch import (
    dismiss_nudge,
    get_nudge_state_snapshot,
)
from core.archetype_picks import (
    ARCHETYPES,
    IMPLEMENTED_SCORERS,
    VALID_SOURCES,
    clear_archetype_pick,
    get_archetype_for,
    list_archetype_picks,
    save_archetype_pick,
)
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_archetype_get(h) -> None:
    qs = parse_qs(urlparse(h.path).query or "")
    champion_list = qs.get("champion") or []
    champion = (champion_list[0] if champion_list else "").strip()
    if champion:
        entry = get_archetype_for(champion)
        payload = {
            "ok":         True,
            "champion":   champion,
            "pick":       entry,
            "archetypes": list(ARCHETYPES),
            "implemented": sorted(IMPLEMENTED_SCORERS),
        }
    else:
        payload = {
            "ok":          True,
            "picks":       list_archetype_picks(),
            "archetypes":  list(ARCHETYPES),
            "implemented": sorted(IMPLEMENTED_SCORERS),
            "sources":     sorted(VALID_SOURCES),
        }
    h._send(200, json.dumps(payload).encode(), "application/json")


def _serve_archetype_post(h, payload) -> None:
    """Save or clear a per-champion pick.

    On ``{champion, clear: true}`` clears the override. Otherwise
    requires ``primary``; ``secondary`` and ``source`` are optional.
    """
    if not isinstance(payload, dict):
        h._send(400, json.dumps({"error": "JSON object required"}).encode(),
                "application/json")
        return
    champion = str(payload.get("champion") or "").strip()
    if not champion:
        h._send(400, json.dumps({"error": "champion required"}).encode(),
                "application/json")
        return

    # Clear path
    if payload.get("clear"):
        cleared = clear_archetype_pick(champion)
        entry = get_archetype_for(champion)
        h._send(200, json.dumps({
            "ok":      True,
            "cleared": cleared,
            "pick":    entry,
        }).encode(), "application/json")
        return

    primary = str(payload.get("primary") or "").strip()
    if not primary:
        h._send(400, json.dumps({"error": "primary required"}).encode(),
                "application/json")
        return

    secondary_raw = payload.get("secondary")
    secondary = str(secondary_raw).strip() if secondary_raw else None

    source = str(payload.get("source") or "user_cs").strip()

    try:
        entry = save_archetype_pick(
            champion=champion,
            primary=primary,
            secondary=secondary,
            source=source,
        )
    except ValueError as exc:
        h._send(400, json.dumps({"error": str(exc)}).encode(),
                "application/json")
        return
    except Exception as exc:
        log.warning("cs-archetype-pick save: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")
        return

    h._send(200, json.dumps({
        "ok":   True,
        "pick": entry,
    }).encode(), "application/json")


def _serve_archetype_nudge_get(h) -> None:
    """Diagnostic GET — returns the current in-memory nudge state.

    Not security-sensitive (already exposed via /api/state); the dedicated
    endpoint just makes manual probing easier. Operator can curl it to
    see why a nudge isn't firing.
    """
    snapshot = get_nudge_state_snapshot()
    h._send(200, json.dumps({
        "ok": True,
        "state": snapshot,
    }).encode(), "application/json")


def _serve_archetype_nudge_dismiss(h, payload) -> None:
    """POST /api/archetype-nudge/dismiss — operator clicked the chip's X.

    Body: ``{ champion: "<name>" }``. Idempotent — re-dismissing an
    already-dismissed nudge is fine. Returns ``{ok, dismissed: bool}``.
    """
    if not isinstance(payload, dict):
        h._send(400, json.dumps({"error": "JSON object required"}).encode(),
                "application/json")
        return
    champion = str(payload.get("champion") or "").strip()
    if not champion:
        h._send(400, json.dumps({"error": "champion required"}).encode(),
                "application/json")
        return
    dismissed = dismiss_nudge(champion)
    h._send(200, json.dumps({
        "ok":        True,
        "dismissed": dismissed,
        "champion":  champion,
    }).encode(), "application/json")


GET_ROUTES = [
    (equals("/api/cs-archetype-pick"), _serve_archetype_get),
    (equals("/api/archetype-nudge"),   _serve_archetype_nudge_get),
]

POST_ROUTES = [
    (equals("/api/cs-archetype-pick"),         _serve_archetype_post),
    (equals("/api/archetype-nudge/dismiss"),   _serve_archetype_nudge_dismiss),
]
