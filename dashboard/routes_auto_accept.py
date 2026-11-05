# arch: GET/POST /api/lcu/auto-accept (ready-check auto-accept on/off) | section=dashboard | frozen=no
"""GET / POST /api/lcu/auto-accept - the LIFT 5 ready-check auto-accept switch.

Reads + writes the NON-frozen ``core.auto_accept_pref`` flag, which the frozen
``lcu/lcu_client.py`` ``_auto_accept_tick`` consults right before it calls
``accept_queue()`` and which the LCU agent's CONFIG follows (RM-1222). Its
browser caller is the dashboard "Auto Accept" control (``web/js/main.js``
``_setAutoAccept``), which posts here FIRST and sends the agent a
``set_config`` only after a 200; on any other answer it puts the control back
and shows a notice. The control DISPLAYS the agent's CONFIG, which carries
this flag's value (see the "two gates" note in core/auto_accept_pref.py).
Nothing in the dashboard GETs this route today; it is the read-back for
probes and tests. With no stored choice the flag is OFF (s144 true-audit
cycle 83; it used to be ON).

Routes:
  GET  /api/lcu/auto-accept  -> 200 {"ok": true, "enabled": <is_enabled()>}
  POST /api/lcu/auto-accept   body exactly {"enabled": <bool>}
       -> 200 {"ok": true, "enabled": <stored>}
       -> 400 {"ok": false, "error": ...} for a non-object body, a missing or
          non-bool "enabled", or any other key (nothing is written)
       -> 503 {"ok": false, "error": ...} when the save failed (an OSError
          after the writer's bounded replace retry); safe to retry
       -> 500 generic error for anything unexpected, traceback logged
  Raw exception text stays in the log only (CLAUDE.md error rule).

Trust model: a control endpoint (``dashboard/_handler.py``
``_CONTROL_ENDPOINTS``) behind the RC_DASH_TOKEN gate - it drives the client
exactly like a queue writer, because the flag decides whether a ready check
is accepted. The route itself only flips that flag; it executes nothing.
"""
from __future__ import annotations

import json
import logging

from core import auto_accept_pref

log = logging.getLogger("rc.web_dashboard")

_GENERIC_ERR = "internal error - see logs"
_SAVE_ERR = "could not save the auto-accept preference - retry"


def _send_json(h, code: int, payload: dict) -> None:
    """Send a JSON body with the standard content type + encoding."""
    h._send(code, json.dumps(payload).encode("utf-8"), "application/json")


def _serve_get(h) -> None:
    """GET /api/lcu/auto-accept - report the current flag."""
    try:
        enabled = auto_accept_pref.is_enabled()
    except Exception:  # is_enabled never raises; last resort
        log.exception("api/lcu/auto-accept GET failed")
        _send_json(h, 500, {"ok": False, "error": _GENERIC_ERR})
        return
    _send_json(h, 200, {"ok": True, "enabled": enabled})


def _serve_post(h, body) -> None:
    """POST /api/lcu/auto-accept - body {"enabled": bool} -> persist + echo."""
    if not isinstance(body, dict):
        _send_json(h, 400, {"ok": False, "error": "expected a JSON object body"})
        return
    if "enabled" not in body:
        _send_json(h, 400, {"ok": False, "error": "'enabled' (bool) required"})
        return
    if len(body) != 1:
        # Caller-chosen key names are never echoed back.
        _send_json(h, 400, {"ok": False,
                            "error": "only the 'enabled' field is accepted"})
        return
    enabled = body["enabled"]
    if not isinstance(enabled, bool):
        _send_json(h, 400, {"ok": False, "error": "'enabled' must be a bool"})
        return
    try:
        stored = auto_accept_pref.set_enabled(enabled)
    except OSError:
        log.warning("api/lcu/auto-accept POST: save failed", exc_info=True)
        _send_json(h, 503, {"ok": False, "error": _SAVE_ERR})
        return
    except Exception:  # last-resort guard, never drop the reply
        log.exception("api/lcu/auto-accept POST failed")
        _send_json(h, 500, {"ok": False, "error": _GENERIC_ERR})
        return
    _send_json(h, 200, {"ok": True, "enabled": stored})


def _equals(p: str):
    """Local copy of routes_pickban._equals to avoid the cross-import."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [(_equals("/api/lcu/auto-accept"), _serve_get)]
POST_ROUTES = [(_equals("/api/lcu/auto-accept"), _serve_post)]
