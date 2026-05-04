"""SR Draft Theatre routes.

Phase 8 step 1 (2026-05-04): POST /api/sr-draft/profile thin slice.
Phase 8 step 2 (2026-05-04): engine-backed body landed in
`coaches.sr_draft_profile.build_profile()`.
Phase 8 step 3 (2026-05-04): merges user-curated builds AT THE ROUTE
LAYER so `sr_draft_profile.py` stays engine-only (operator-additive
invariant).

Body shape mirrors the LCU `champ_select` excerpt the dashboard
already has from `/api/state`:

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
       "sr_draft": true, "engine_version": "0.9.3",
       "profiles": [
         {kind:"engine", key:"primary", ...},
         {kind:"engine", key:"alt", ...},
         {kind:"engine", key:"experimental", ...},
         {kind:"user",   key:"<id>", label:"my off-meta lethality", ...}
       ],
       "notes": []
     }

Errors:
  400 — body missing `champion`
  500 — anything unexpected
"""
import json
import logging

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_sr_draft_profile_post(h, payload) -> None:
    try:
        from coaches.sr_draft_profile import build_profile
        from coaches.sr_user_builds import format_for_display, list_for
        champ = (payload.get("champion") or "").strip()
        if not champ:
            h._send(400, b'{"error":"champion required"}', "application/json")
            return
        role       = payload.get("role")
        my_team    = payload.get("my_team")
        their_team = payload.get("their_team")
        queue_id   = payload.get("queue_id")
        envelope = build_profile(
            champion=champ,
            role=role if isinstance(role, str) else None,
            my_team=my_team if isinstance(my_team, list) else None,
            their_team=their_team if isinstance(their_team, list) else None,
            queue_id=queue_id if isinstance(queue_id, int) else None,
        )
        # P8-3: append user-curated builds AFTER the engine ones.
        # Operator-additive invariant: user builds never replace engine
        # output, only extend it.
        try:
            user_records = list_for(champ)
            user_profiles = []
            for rec in user_records:
                rec["_champion"] = champ
                shaped = format_for_display(rec)
                if shaped is not None:
                    user_profiles.append(shaped)
            envelope["profiles"] = list(envelope.get("profiles") or []) + user_profiles
        except Exception as exc:
            log.warning("api/sr-draft/profile user-build merge: %s", exc)
            # Non-fatal: engine profiles still ship.
            envelope.setdefault("notes", []).append(f"user-build merge failed: {exc}")

        h._send(200, json.dumps(envelope).encode(), "application/json")
    except Exception as exc:
        log.warning("api/sr-draft/profile: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


# ── route table ──────────────────────────────────────────────────────

GET_ROUTES: list = []

POST_ROUTES = [
    (equals("/api/sr-draft/profile"), _serve_sr_draft_profile_post),
]
