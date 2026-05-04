"""SR Draft Theatre routes.

Phase 8 step 1 (2026-05-04): POST /api/sr-draft/profile thin slice.
Calls `coaches.sr_draft_profile.build_profile()` and returns the
result as JSON. The body is the LCU `champ_select` shape excerpt the
dashboard already has from `/api/state`:

  POST /api/sr-draft/profile
  {
    "champion":  "Tristana",
    "role":      "BOTTOM",        # optional
    "my_team":   [{cellId, championId, ...}, ...],   # optional
    "their_team":[{...}, ...],    # optional
    "queue_id":  420              # optional
  }

  → 200 {
       "champion": "Tristana", "role": "BOTTOM", "queue_id": 420,
       "sr_draft": true, "engine_version": null, "profiles": []
     }

Errors map to:
  400 — body missing `champion`
  500 — anything unexpected

P8-2 will route through the engine; the route shape is stable so the
JS panel can be wired against this slice today.
"""
import json
import logging

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_sr_draft_profile_post(h, payload) -> None:
    try:
        from coaches.sr_draft_profile import build_profile
        champ = (payload.get("champion") or "").strip()
        if not champ:
            h._send(400, b'{"error":"champion required"}', "application/json")
            return
        role       = payload.get("role")
        my_team    = payload.get("my_team")
        their_team = payload.get("their_team")
        queue_id   = payload.get("queue_id")
        result = build_profile(
            champion=champ,
            role=role if isinstance(role, str) else None,
            my_team=my_team if isinstance(my_team, list) else None,
            their_team=their_team if isinstance(their_team, list) else None,
            queue_id=queue_id if isinstance(queue_id, int) else None,
        )
        h._send(200, json.dumps(result).encode(), "application/json")
    except Exception as exc:
        log.warning("api/sr-draft/profile: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


# ── route table ──────────────────────────────────────────────────────

GET_ROUTES: list = []

POST_ROUTES = [
    (equals("/api/sr-draft/profile"), _serve_sr_draft_profile_post),
]
