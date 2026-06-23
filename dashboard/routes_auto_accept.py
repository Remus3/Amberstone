# arch: GET/POST /api/lcu/auto-accept (ready-check auto-accept on/off) | section=dashboard | frozen=no
"""GET / POST /api/lcu/auto-accept - the LIFT 5 ready-check auto-accept switch.

The dashboard lobby card carries an Auto-accept ready check toggle. It reads +
writes the NON-frozen ``core.auto_accept_pref`` flag, which the frozen
``lcu/lcu_client.py`` ``_auto_accept_tick`` consults right before it calls
``accept_queue()``. Turning the flag OFF stops the auto-accept without touching
the frozen loop's logic; the default is ON so the historical always-on behavior
is preserved until the operator explicitly flips it.

Routes:
  GET  /api/lcu/auto-accept  -> {"ok": true, "enabled": <is_enabled()>}
  POST /api/lcu/auto-accept   body {"enabled": <bool>}
       -> {"ok": true, "enabled": <stored>} ; on a missing / non-bool "enabled"
       field a 400 {"ok": false, "error": ...}. Never crashes; the raw
       exception text stays in the log only (CLAUDE.md error rule).

Trust model: same as every other dashboard POST (/api/command, /api/loop-control)
- the :8888 surface is local / Tailscale-tailnet only, single-operator. This
route only flips a tiny preference flag; it never executes anything itself.
"""
from __future__ import annotations

import json
import logging

from core import auto_accept_pref

log = logging.getLogger("rc.web_dashboard")


def _send_json(h, code: int, payload: dict) -> None:
    """Send a JSON body with the standard content type + encoding."""
    h._send(code, json.dumps(payload).encode("utf-8"), "application/json")


def _serve_get(h) -> None:
    """GET /api/lcu/auto-accept - report the current flag."""
    try:
        _send_json(h, 200, {"ok": True, "enabled": auto_accept_pref.is_enabled()})
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never 500 the server
        log.warning("api/lcu/auto-accept GET: %s", exc)
        # Raw exception text stays in the log only (CLAUDE.md error rule).
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _serve_post(h, body) -> None:
    """POST /api/lcu/auto-accept - body {"enabled": bool} -> persist + echo."""
    try:
        if not isinstance(body, dict):
            _send_json(h, 400, {"ok": False, "error": "expected a JSON object body"})
            return
        if "enabled" not in body:
            _send_json(h, 400, {"ok": False, "error": "'enabled' (bool) required"})
            return
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            _send_json(h, 400, {"ok": False, "error": "'enabled' must be a bool"})
            return
        stored = auto_accept_pref.set_enabled(enabled)
        _send_json(h, 200, {"ok": True, "enabled": stored})
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never 500 the server
        log.warning("api/lcu/auto-accept POST: %s", exc)
        # Raw exception text stays in the log only (CLAUDE.md error rule).
        _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})


def _equals(p: str):
    """Local copy of routes_pickban._equals to avoid the cross-import."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [(_equals("/api/lcu/auto-accept"), _serve_get)]
POST_ROUTES = [(_equals("/api/lcu/auto-accept"), _serve_post)]
