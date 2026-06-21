# arch: champ-select snapshot retention across no-draft transition | section=dashboard | frozen=no
"""Champ-select snapshot retention across the fast no-draft transition.

ARAM (450) / ARAM Mayhem (KIWI, 2400) / Arena (1750) have no ban/pick
draft - champ-select is a short bench / reroll / augment window that
flips ChampSelect -> GameStart -> InProgress in well under the dashboard
snapshot path's latency budget:

    LCU agent (Legion-local)  --1s push-->  Legion vision cache
    Legion lcu_summary()  --drops the WHOLE snapshot if >5s stale-->
    dashboard/_state_builder.build_state()

The operator repeatedly saw the champ-select bench / quick-swap view
blank for these modes: by the time the dashboard polled, the fresh
snapshot's ``champ_select`` was already gone (game started -> the LCU
``/lol-champ-select/v1/session`` 404s; or the agent push went briefly
>5s stale so ``lcu_summary()`` returned ``{}``).

This keeps the last non-empty ``champ_select`` and re-splices it into
a snapshot that lost it, for a bounded retention window, so the view
survives the transition. Scope note: this is a robustness layer for
*transient loss* - the primary Mayhem functional fix is the queue-2400
mapping (``core.queue_modes`` + the agent's ``is_aram``). Retention's
clean win is the phase-still-ChampSelect-but-cs-momentarily-empty
agent-race case; when the LCU phase has genuinely advanced to
InProgress the phase-driven view router (s208/s209) governs which view
shows - that path is closed separately by the agent ``cs_debug``
breadcrumb's live evidence.

Pure function over an injected clock + module cache -> deterministic
and unit-testable. Wired into ``build_state()`` immediately after
``lcu_summary()`` so the s150 pre-flip mode also benefits.
"""
from __future__ import annotations

import copy
from typing import Optional

# A retained champ-select older than this is definitely stale - no
# no-draft champ-select + loading lasts anywhere near 2 minutes, and
# the explicit-phase clear below fires long before this in practice.
RETENTION_TTL_S = 120.0

# LCU gameflow-phase values that mean "we are NOT in the champ-select ->
# game transition": either pre-champ-select (operator dodged / next
# queue popped) or post-game. Any of these with no fresh champ_select
# means the retained snapshot is stale -> drop it.
#
# NB: the literal string ``"None"`` (gameflow-phase serializes the
# no-flow state to that) is a clear signal; a Python ``None`` phase
# means the snapshot is empty/stale (>5s agent push) which IS the
# transient window we want to bridge - so only the *string* is listed.
_CLEAR_PHASES = frozenset({
    "Lobby", "Matchmaking", "ReadyCheck", "None",
    "EndOfGame", "PreEndOfGame", "WaitingForStats", "TerminatedInError",
})

_STATE: dict = {"cs": None, "ts": 0.0}


def reset_cs_retention() -> None:
    """Drop the retained champ-select (test hook + explicit clear)."""
    _STATE["cs"] = None
    _STATE["ts"] = 0.0


def _clear() -> None:
    _STATE["cs"] = None
    _STATE["ts"] = 0.0


def apply_cs_retention(
    lcu_snapshot: Optional[dict],
    *,
    now: Optional[float] = None,
) -> Optional[dict]:
    """Return a snapshot with ``champ_select`` re-spliced if it was lost
    during the transient no-draft champ-select -> game transition.

    - Fresh non-empty ``champ_select`` present -> cache it, pass the
      input through unchanged.
    - No fresh ``champ_select`` -> re-splice the cached one (marked
      ``_retained: True``) when within the retention window and the
      fresh phase isn't an explicit pre/post-game phase; otherwise
      clear the cache and pass through unchanged.

    ``now`` is injectable for deterministic tests; defaults to wall
    clock. The return value is the input object (passthrough) or a
    shallow-copied dict with a deep-copied retained ``champ_select`` -
    never the cached object itself.
    """
    if now is None:
        import time
        now = time.time()

    snap = lcu_snapshot if isinstance(lcu_snapshot, dict) else None
    if snap is None:
        return lcu_snapshot

    cs = snap.get("champ_select")
    if isinstance(cs, dict) and cs:
        _STATE["cs"] = copy.deepcopy(cs)
        _STATE["ts"] = now
        return lcu_snapshot

    cached = _STATE["cs"]
    if not cached:
        return lcu_snapshot

    if (now - _STATE["ts"]) > RETENTION_TTL_S:
        _clear()
        return lcu_snapshot

    if snap.get("phase") in _CLEAR_PHASES:
        _clear()
        return lcu_snapshot

    retained = copy.deepcopy(cached)
    retained["_retained"] = True
    out = dict(snap)
    out["champ_select"] = retained
    return out
