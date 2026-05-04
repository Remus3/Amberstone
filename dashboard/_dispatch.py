"""Route dispatcher for the dashboard HTTP server.

Slice 2C (2026-05-01): replaces the giant `if/elif self.path == …`
chain in web_dashboard._Handler.do_GET / do_POST. Each routes_*
module exposes:

  GET_ROUTES  : list[tuple[matcher, handler]]    handler(h)
  POST_ROUTES : list[tuple[matcher, handler]]    handler(h, body)

`matcher` is `(path: str) -> bool`. `handler` is called with the
BaseHTTPRequestHandler (so it can use `self._send` etc.) and, for
POST, the parsed JSON body (already validated upstream for size).

Routes are tried in registration order; first match wins. Unmatched
falls back to the legacy elif chains in web_dashboard while the
migration is in progress.
"""
from typing import Callable

# ── matcher factories ────────────────────────────────────────────────

def equals(path: str) -> Callable[[str], bool]:
    """Match exactly `path`, or `path?…` (path with a query string)."""
    return lambda p: p == path or p.startswith(path + "?")


def prefix(p: str) -> Callable[[str], bool]:
    """Match anything starting with prefix `p`."""
    return lambda x: x.startswith(p)


# ── registry (cached so each request doesn't rebuild the list) ───────

_GET_CACHE: list | None = None
_POST_CACHE: list | None = None


def _gather_get() -> list:
    global _GET_CACHE
    if _GET_CACHE is None:
        from dashboard import (routes_static, routes_state, routes_history,
                               routes_diag, routes_coach, routes_bridge,
                               routes_bridge_pending,
                               routes_health_peer,
                               routes_loadout, routes_metrics,
                               routes_sr_draft)
        _GET_CACHE = (list(routes_static.GET_ROUTES)
                      + list(routes_state.GET_ROUTES)
                      + list(routes_history.GET_ROUTES)
                      + list(routes_diag.GET_ROUTES)
                      + list(routes_coach.GET_ROUTES)
                      + list(routes_bridge.GET_ROUTES)
                      + list(routes_bridge_pending.GET_ROUTES)
                      + list(routes_health_peer.GET_ROUTES)
                      + list(routes_loadout.GET_ROUTES)
                      + list(routes_metrics.GET_ROUTES)
                      + list(routes_sr_draft.GET_ROUTES))
    return _GET_CACHE


def _gather_post() -> list:
    global _POST_CACHE
    if _POST_CACHE is None:
        from dashboard import (routes_static, routes_state, routes_history,
                               routes_diag, routes_coach, routes_bridge,
                               routes_bridge_pending,
                               routes_bridge_pending_actions,
                               routes_health_peer,
                               routes_loadout, routes_metrics,
                               routes_sr_draft)
        _POST_CACHE = (list(routes_static.POST_ROUTES)
                       + list(routes_state.POST_ROUTES)
                       + list(routes_history.POST_ROUTES)
                       + list(routes_diag.POST_ROUTES)
                       + list(routes_coach.POST_ROUTES)
                       + list(routes_bridge.POST_ROUTES)
                       + list(routes_bridge_pending.POST_ROUTES)
                       + list(routes_bridge_pending_actions.POST_ROUTES)
                       + list(routes_health_peer.POST_ROUTES)
                       + list(routes_loadout.POST_ROUTES)
                       + list(routes_metrics.POST_ROUTES)
                       + list(routes_sr_draft.POST_ROUTES))
    return _POST_CACHE


def dispatch_get(handler) -> bool:
    """Try each registered GET route in order. Returns True if one
    matched and handled the request (the handler is responsible for
    writing a response). Returns False if no route matched."""
    path = handler.path
    for matcher, fn in _gather_get():
        if matcher(path):
            fn(handler)
            return True
    return False


def dispatch_post(handler, body) -> bool:
    """Same as dispatch_get but for POST. `body` is the parsed JSON
    payload (dict) extracted upstream."""
    path = handler.path
    for matcher, fn in _gather_post():
        if matcher(path):
            fn(handler, body)
            return True
    return False
