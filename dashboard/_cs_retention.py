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
import logging
import math
import threading
import time
from typing import Optional

_log = logging.getLogger(__name__)

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
# Any other non-str phase (the relay JSON can carry a list or a dict)
# names no phase either and is treated like ``None``: it holds.
_CLEAR_PHASES = frozenset({
    "Lobby", "Matchmaking", "ReadyCheck", "None",
    "EndOfGame", "PreEndOfGame", "WaitingForStats", "TerminatedInError",
})

# The window is measured on the monotonic clock: a wall-clock step back
# would otherwise hold a stale champ-select past RETENTION_TTL_S, and a
# step forward would drop a live one early. Module-level so tests can
# drive it.
_clock = time.monotonic

# ``cs`` and ``ts`` are one entry: build_state runs on several
# ThreadingHTTPServer threads at once, so every read and write of the
# pair happens under _LOCK (an unlocked reader could pair a fresh
# champ_select with the previous stamp and clear it).
_LOCK = threading.Lock()
_STATE: dict = {"cs": None, "ts": 0.0}
# One warning per streak of uncopyable champ_select payloads.
_COPY_WARNED = [False]


def _clear() -> None:
    _STATE["cs"] = None
    _STATE["ts"] = 0.0


def reset_cs_retention() -> None:
    """Drop the retained champ-select (test hook + explicit clear)."""
    with _LOCK:
        _clear()
        _COPY_WARNED[0] = False


def _copy(obj):
    return copy.deepcopy(obj)


def _now(now) -> float:
    """``now`` as a finite float, else the module clock.

    A NaN stamp never expires (every comparison with it is False) and a
    str or a bool is not a time, so anything that is not a finite real
    number falls back to the clock instead of reaching the cache.
    """
    if isinstance(now, (int, float)) and not isinstance(now, bool):
        try:
            value = float(now)
        except OverflowError:
            value = math.nan
        if math.isfinite(value):
            return value
    return float(_clock())


def apply_cs_retention(
    lcu_snapshot: Optional[dict],
    *,
    now: Optional[float] = None,
) -> Optional[dict]:
    """Return a snapshot with ``champ_select`` re-spliced if it was lost
    during the transient no-draft champ-select -> game transition.

    - Fresh non-empty ``champ_select`` present -> cache it, pass the
      input through unchanged. If it cannot be deep-copied (nesting
      past the recursion limit), the older cache is dropped as stale,
      a warning names the exception type once per streak, and the
      input still passes through unchanged.
    - No fresh ``champ_select`` -> re-splice the cached one (marked
      ``_retained: True``) when within the retention window and the
      fresh phase isn't an explicit pre/post-game phase; otherwise
      clear the cache and pass through unchanged. A ``now`` earlier
      than the cached stamp is outside the window.

    ``now`` is injectable for deterministic tests; defaults to the
    monotonic clock (as does any non-finite or non-number ``now``).
    The return value is the input object (passthrough) or a
    shallow-copied dict with a deep-copied retained ``champ_select`` -
    never the cached object itself. Never raises on a JSON-shaped
    snapshot (the relay and in-process payloads are plain data).
    """
    snap = lcu_snapshot if isinstance(lcu_snapshot, dict) else None
    if snap is None:
        return lcu_snapshot
    stamp = _now(now)

    with _LOCK:
        cs = snap.get("champ_select")
        if isinstance(cs, dict) and cs:
            try:
                cached = _copy(cs)
            except (RecursionError, TypeError, copy.Error) as exc:
                _clear()
                if not _COPY_WARNED[0]:
                    _COPY_WARNED[0] = True
                    _log.warning(
                        "champ_select retention: payload not copyable "
                        "(%s); retention cleared", type(exc).__name__)
                return lcu_snapshot
            _COPY_WARNED[0] = False
            _STATE["cs"] = cached
            _STATE["ts"] = stamp
            return lcu_snapshot

        cached = _STATE["cs"]
        if not cached:
            return lcu_snapshot

        elapsed = stamp - _STATE["ts"]
        if elapsed < 0 or elapsed > RETENTION_TTL_S:
            _clear()
            return lcu_snapshot

        phase = snap.get("phase")
        if isinstance(phase, str) and phase in _CLEAR_PHASES:
            _clear()
            return lcu_snapshot

        retained = _copy(cached)
    retained["_retained"] = True
    out = dict(snap)
    out["champ_select"] = retained
    return out
