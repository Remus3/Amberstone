"""SR Draft Theatre routes.

Phase 8 step 1 (2026-05-04): POST /api/sr-draft/profile thin slice.
Phase 8 step 2 (2026-05-04): engine-backed body landed in
`coaches.sr_draft_profile.build_profile()`.
Phase 8 step 3 (2026-05-04): merges user-curated builds AT THE ROUTE
LAYER so `sr_draft_profile.py` stays engine-only (operator-additive
invariant).
Phase 8 step 5 (2026-05-04): POST /api/sr-draft/apply pushes a chosen
profile to the LCU via the same vision-server `/lcu-cmd` proxy as
`/api/loadout/apply`. Each variant gets a unique rune-page name
(`RC: <Champ> <key> (SR)`) so concurrent variants don't clobber each
other through `lcu_rune_writer._write_page`'s delete-all-RC-pages step.

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

  POST /api/sr-draft/apply
  {
    "champion":  "Tristana",
    "key":       "primary",                 # profile key — used in page name
    "label":     "Primary",                 # optional, surfaces in response
    "kind":      "engine"|"user",           # optional, response only
    "runes": {                              # optional — skipped if missing
      "keystone":  "Press the Attack",
      "primary":   "Precision",
      "secondary": "Domination"
    },
    "summoner_spells": [4, 12],             # optional — [d, f] LCU IDs
    "item_ids":  ["6675", "3094", ...],     # optional — pre-resolved
    "push_runes": true,                     # default true
    "push_items": true,                     # default true
    "push_summoners": true                  # default true
  }

  → 200 {
       "ok": true,
       "champion": "Tristana", "key": "primary", "label": "Primary",
       "queued": ["apply_runes", "apply_item_set", "set_summoners"],
       "page_name": "RC: Tristana primary (SR)",
       "item_ids": ["6675", "3094", ...]
     }

Errors:
  400 — body missing `champion` or `key`
  500 — anything unexpected
"""
import json
import logging

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _build_page_name(champion: str, key: str) -> str:
    """Unique rune-page name per (champion, profile-key) pair.

    Truncated to 75 chars (LCU page-name cap). Per s51 plan: each variant
    gets its own page so concurrent saves don't clobber via the rune
    writer's delete-all-RC-pages step.
    """
    return f"RC: {champion} {key} (SR)"[:75]


def _build_item_set(champion: str, key: str, item_ids: list) -> dict:
    """Wrap pre-resolved item ids in the LCU `apply_item_set` shape.

    Mirrors `coaches.loadout_resolver.resolve`'s item_cmd shape so the
    gamepc_lcu_agent receives an identical command structure. `set_uid`
    is variant-keyed so each profile gets its own slot in the client.
    """
    norm_champ = "".join(ch for ch in champion.lower() if ch.isalnum())
    norm_key   = "".join(ch for ch in key.lower()      if ch.isalnum())
    items = [{"id": str(i), "count": 1} for i in (item_ids or []) if i]
    return {
        "cmd":      "apply_item_set",
        "set_uid":  f"RC-{norm_champ}-sr-{norm_key}",
        "title":    f"RC: {champion} {key} (SR)"[:50],
        # champion_id is best-effort — the LCU agent tolerates 0 (item
        # set still applies; just isn't auto-equipped on champion lock).
        "champion_id": 0,
        "blocks": [{
            "type":  "Build (RC SR-draft)",
            "items": items,
        }],
    }


def _build_rune_cmd(champion: str, key: str, runes: dict) -> "dict | None":
    """Translate a profile's runes dict → `apply_runes` LCU command.

    Returns None when the keystone or trees aren't recognised by the
    frozen `lcu.lcu_rune_writer.build_perk_ids` resolver — in that case
    the caller skips the rune push and surfaces a note. The shard3=5002
    SR bug in the rune writer is documented in
    `project_rune_writer_shard3_not_applied.md`; SR-draft variants ride
    this path knowingly (engine work, not Phase 8 scope).
    """
    if not isinstance(runes, dict):
        return None
    keystone  = runes.get("keystone")  or ""
    primary   = runes.get("primary")   or runes.get("primary_tree")   or ""
    secondary = runes.get("secondary") or runes.get("secondary_tree") or ""
    if not (keystone and primary and secondary):
        return None
    try:
        from lcu.lcu_rune_writer import _TREES, build_perk_ids
    except Exception as exc:
        log.warning("api/sr-draft/apply rune import: %s", exc)
        return None
    perk_ids = build_perk_ids(keystone, primary, secondary, is_aram=False)
    primary_id = _TREES.get(primary, 0)
    sub_id     = _TREES.get(secondary, 0)
    if not (perk_ids and primary_id and sub_id):
        return None
    return {
        "cmd":        "apply_runes",
        "page_name":  _build_page_name(champion, key),
        "primary_id": primary_id,
        "sub_id":     sub_id,
        "perk_ids":   perk_ids,
    }


def _serve_sr_draft_apply_post(h, payload) -> None:
    try:
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        champ = (payload.get("champion") or "").strip()
        key   = (payload.get("key")      or "").strip()
        if not champ or not key:
            h._send(400, b'{"error":"champion+key required"}', "application/json")
            return
        push_runes = payload.get("push_runes",     True)
        push_items = payload.get("push_items",     True)
        push_summ  = payload.get("push_summoners", True)

        runes    = payload.get("runes")           or {}
        spells   = payload.get("summoner_spells") or []
        item_ids = payload.get("item_ids")        or []
        label    = payload.get("label") or key
        kind     = payload.get("kind")  or ""

        rune_cmd = _build_rune_cmd(champ, key, runes) if push_runes else None
        item_cmd = _build_item_set(champ, key, item_ids) if (push_items and item_ids) else None
        summ_cmd: "dict | None" = None
        if push_summ and isinstance(spells, list) and len(spells) >= 2:
            try:
                summ_cmd = {"cmd": "set_summoners", "d": int(spells[0]), "f": int(spells[1])}
            except (ValueError, TypeError):
                summ_cmd = None

        queued: list[str] = []
        notes:  list[str] = []

        def _enqueue(cmd_obj):
            if not cmd_obj:
                return
            try:
                req = _ur.Request(
                    "http://127.0.0.1:8889/lcu-cmd",
                    data=json.dumps(cmd_obj).encode(),
                    method="POST",
                    headers={"X-RC-Token": _VISION_TOKEN,
                             "Content-Type": "application/json"},
                )
                with _ur.urlopen(req, timeout=2) as r:
                    r.read()
                queued.append(cmd_obj.get("cmd"))
            except Exception as exc:
                log.warning("sr-draft enqueue %s: %s", cmd_obj.get("cmd"), exc)
                notes.append(f"{cmd_obj.get('cmd')}: {exc}")

        if push_runes and rune_cmd is None and isinstance(runes, dict) and runes:
            notes.append("runes: keystone/tree unrecognised — skipped")
        if push_items and item_cmd is None and item_ids:
            notes.append("items: empty after coercion — skipped")

        _enqueue(rune_cmd)
        _enqueue(item_cmd)
        _enqueue(summ_cmd)

        h._send(200, json.dumps({
            "ok":         True,
            "champion":   champ,
            "key":        key,
            "kind":       kind,
            "label":      label,
            "queued":     queued,
            "page_name":  _build_page_name(champ, key),
            "item_ids":   [str(i) for i in (item_ids or [])],
            "notes":      notes,
        }).encode(), "application/json")
    except Exception as exc:
        log.warning("api/sr-draft/apply: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


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
    (equals("/api/sr-draft/apply"),   _serve_sr_draft_apply_post),
]
