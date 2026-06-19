"""SR user-curated builds CRUD routes (Phase 8 step 3).

  GET    /api/sr-draft/user-builds?champion=Tristana
       -> 200 {"champion": "...", "builds": [...]}

  POST   /api/sr-draft/user-builds
       body: {"champion": "Tristana", "build": {label, items, runes, ...}}
       -> 200 {"ok": true, "id": "<8hex>"}
       -> 400 if champion or build.label missing
       -> 422 if engine rejects shape

  DELETE /api/sr-draft/user-builds?champion=Tristana&id=abc123ef
       (sent as POST with cmd:"delete" since the dashboard handler
        only routes GET/POST today - single endpoint, action-keyed)

To stay consistent with the existing dashboard handler shape (only
GET + POST in `_dispatch`), the destructive ops live as POST sub-actions:
  {"action": "list",   "champion": "..."}            (also via GET ?champion=)
  {"action": "add",    "champion": "...", "build": {...}}
  {"action": "update", "champion": "...", "id": "...", "patch": {...}}
  {"action": "delete", "champion": "...", "id": "..."}

Defaults to `add` when `action` is missing on POST and a `build` key
is present - keeps the simplest case ergonomic.
"""
import json
import logging
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_user_builds_get(h) -> None:
    try:
        from coaches.sr_user_builds import list_for
        qs = parse_qs(urlparse(h.path).query)
        champion = (qs.get("champion") or [""])[0].strip()
        if not champion:
            h._send(400, b'{"error":"champion query param required"}',
                    "application/json")
            return
        builds = list_for(champion)
        h._send(200, json.dumps({
            "champion": champion,
            "builds":   builds,
        }).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/sr-draft/user-builds GET: %s", exc)
        # Raw exception text stays in the log only (was untruncated here).
        h._send(500, json.dumps({"error": "internal error - see logs"}).encode(),
                "application/json")


def _serve_user_builds_post(h, payload) -> None:
    try:
        from coaches.sr_user_builds import add, delete, list_for, update
        action = (payload.get("action") or "").strip().lower()
        # Default action: if a build is included, treat as add.
        if not action:
            action = "add" if payload.get("build") else "list"
        champion = (payload.get("champion") or "").strip()
        if not champion:
            h._send(400, b'{"error":"champion required"}', "application/json")
            return

        if action == "list":
            builds = list_for(champion)
            h._send(200, json.dumps({"champion": champion, "builds": builds}).encode(),
                    "application/json")
            return

        if action == "add":
            build = payload.get("build")
            if not isinstance(build, dict):
                h._send(400, b'{"error":"build object required"}', "application/json")
                return
            try:
                new_id = add(champion, build)
            except ValueError as exc:
                h._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            h._send(200, json.dumps({"ok": True, "id": new_id}).encode(),
                    "application/json")
            return

        if action == "update":
            build_id = (payload.get("id") or "").strip()
            patch    = payload.get("patch") or payload.get("build")
            if not build_id or not isinstance(patch, dict):
                h._send(400, b'{"error":"id + patch required"}', "application/json")
                return
            ok = update(champion, build_id, patch)
            if not ok:
                h._send(404, b'{"error":"build not found"}', "application/json")
                return
            h._send(200, json.dumps({"ok": True}).encode(), "application/json")
            return

        if action == "delete":
            build_id = (payload.get("id") or "").strip()
            if not build_id:
                h._send(400, b'{"error":"id required"}', "application/json")
                return
            ok = delete(champion, build_id)
            if not ok:
                h._send(404, b'{"error":"build not found"}', "application/json")
                return
            h._send(200, json.dumps({"ok": True}).encode(), "application/json")
            return

        h._send(400,
                json.dumps({"error": f"unknown action: {action}"}).encode(),
                "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/sr-draft/user-builds POST: %s", exc)
        # Raw exception text stays in the log only (was untruncated here).
        h._send(500, json.dumps({"error": "internal error - see logs"}).encode(),
                "application/json")


# -- route table ------------------------------------------------------

GET_ROUTES = [
    (equals("/api/sr-draft/user-builds"), _serve_user_builds_get),
]

POST_ROUTES = [
    (equals("/api/sr-draft/user-builds"), _serve_user_builds_post),
]
