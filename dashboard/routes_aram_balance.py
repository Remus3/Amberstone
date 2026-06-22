"""GET /api/aram-balance - per-champion ARAM balance modifiers.

Surfaces the seven Riot ARAM modifiers RC already loads into the DS
snapshot but never displays:

  aramDamageDealt / aramDamageTaken / aramHealing / aramShielding /
  aramTenacity / aramAttackSpeed   (MULTIPLIERS, neutral = 1.0)
  aramAbilityHaste                 (ADDITIVE FLAT, neutral = 0)

Only NON-NEUTRAL fields are emitted per champion; fully-neutral champs
are omitted entirely (see core.aram_balance_context.balance_grid_map).

Output (JSON 200):

  {
    "ok": true,
    "patch": "16.12.1",
    "champions": {
      "Aatrox": {"aramDamageDealt": 1.05},
      ...
    }
  }

The map is memoized at module scope (the snapshot is immutable per
patch); a process restart picks up a new patch. Broad fail-soft -> 500
with a truncated error string so a malformed snapshot never crashes the
dashboard.
"""
from __future__ import annotations

import json
import logging
import threading

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# The balance grid is immutable per patch - build once + reuse across
# requests (mirrors routes_damage_mix._get_snapshot memoization).
_GRID = None
_PATCH = None
_LOCK = threading.Lock()


def _get_grid():
    """Lazy-load + memoize (patch, champions-map). Fail-soft to ("", {})."""
    global _GRID, _PATCH
    with _LOCK:
        if _GRID is None:
            from pathlib import Path

            from core.aram_balance_context import balance_grid_map

            try:
                data_dir = (
                    Path(__file__).resolve().parent.parent
                    / "data" / "daemon_slayer"
                )
                _PATCH = (data_dir / "current.txt").read_text(
                    encoding="utf-8"
                ).strip()
            except (OSError, UnicodeDecodeError):
                _PATCH = ""
            _GRID = balance_grid_map()
        return _PATCH, _GRID


def _reset_caches() -> None:
    """Test-only: clear the memoized grid + patch."""
    global _GRID, _PATCH
    with _LOCK:
        _GRID = None
        _PATCH = None


def _serve_aram_balance(h) -> None:
    """GET /api/aram-balance -> {ok, patch, champions}."""
    try:
        patch, grid = _get_grid()
        payload = {
            "ok": True,
            "patch": patch,
            "champions": grid,
        }
        body = json.dumps(payload).encode("utf-8")
        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("aram-balance failed: %s", exc, exc_info=True)
        try:
            body = json.dumps(
                {"ok": False, "error": str(exc)[:200]}
            ).encode("utf-8")
            h._send(500, body, "application/json")
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/aram-balance"), _serve_aram_balance),
]

POST_ROUTES: list = []
