# arch: edge-triggered per-target state watcher (startup state and reconnects never fire) | section=core | frozen=no
"""core/edge_watcher.py - act when a state APPEARS, never because it is there.

P2-4. A poller that does ``if present and not was_present: act()`` with
``was_present = False`` at start-up treats "the state was already there when I
started looking" as an event: start RC mid-game and it announces a game start,
restart a worker mid-game and it announces another. The same mistake shows up
after a link outage: the poller loses sight of the target, sees it again and
calls that an appearance.

``EdgeWatcher`` keeps, per target, the last observed state and an explicit
``primed`` flag:

  * the first observation of a target only PRIMES it - it never fires, whatever
    it sees;
  * ``ABSENT -> PRESENT`` fires (once; ``PRESENT -> PRESENT`` never re-fires,
    ``PRESENT -> ABSENT -> PRESENT`` fires again - a genuine new occurrence);
  * ``UNREACHABLE`` un-primes the target, so the next good read re-primes
    silently - a reconnect is not an event;
  * a probe that raises, or returns anything that is not a ``ProbeState``
    (or a ``poll`` with no probe at all), counts as ``UNREACHABLE``; such a
    failure never escapes ``poll`` and is WARNED once per failure streak per
    target (any ``ProbeState`` return ends the streak), so a probe that can
    never read its target is not silent at the default log level;
  * an ``on_appear`` that raises is logged with its traceback and recorded,
    never re-raised.

Caller errors are loud instead: a non-callable ``probe`` / ``on_appear``
raises ``TypeError`` at construction, and an unhashable target raises
``TypeError`` from ``poll`` / ``observe`` before the probe runs.

Dry-run mode builds the same record but does not call ``on_appear``. Every
fire / would-fire comes back as a JSON-serialisable dict, provided the target
itself is JSON-serialisable (use str / int targets).

Pure: no I/O, no threads, no clock other than ``time.time()`` for the record
stamp. Not thread-safe; give each polling thread its own watcher.
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, Hashable, Optional, Set

_log = logging.getLogger("rc.edge_watcher")


class ProbeState(str, Enum):
    """Explicit tri-state probe result. Never compare by truthiness."""

    PRESENT = "present"
    ABSENT = "absent"
    UNREACHABLE = "unreachable"


PRESENT = ProbeState.PRESENT
ABSENT = ProbeState.ABSENT
UNREACHABLE = ProbeState.UNREACHABLE


class EdgeWatcher:
    """Per-target ABSENT -> PRESENT edge detector with a priming read.

    ``probe(target)`` returns a ``ProbeState`` (only needed for ``poll``;
    callers that already hold the state use ``observe``). ``on_appear(target)``
    is the action; it may be None when the caller only wants the record.
    """

    def __init__(
        self,
        probe: Optional[Callable[[Any], ProbeState]],
        on_appear: Optional[Callable[[Any], Any]],
        dry_run: bool = False,
    ) -> None:
        if probe is not None and not callable(probe):
            raise TypeError(f"edge_watcher: probe must be callable or None, got {type(probe).__name__}")
        if on_appear is not None and not callable(on_appear):
            raise TypeError(
                f"edge_watcher: on_appear must be callable or None, got {type(on_appear).__name__}"
            )
        self._probe = probe
        self._on_appear = on_appear
        self.dry_run = bool(dry_run)
        self._primed: Dict[Hashable, bool] = {}
        self._last: Dict[Hashable, ProbeState] = {}
        # Targets inside a probe-failure streak (already warned once).
        self._failing: Set[Hashable] = set()

    # -- queries -------------------------------------------------------------

    def is_primed(self, target: Hashable) -> bool:
        return self._primed.get(target, False)

    def last_state(self, target: Hashable) -> Optional[ProbeState]:
        """Last REACHABLE state seen (PRESENT / ABSENT), or None if never."""
        return self._last.get(target)

    # -- driving -------------------------------------------------------------

    def poll(self, target: Hashable) -> Optional[Dict[str, Any]]:
        """Probe ``target`` and observe the result.

        A probe failure (raises, returns a non-``ProbeState``, or no probe is
        configured) is ``UNREACHABLE`` and never escapes; it is warned once
        per failure streak. An unhashable ``target`` is a caller error and
        raises ``TypeError`` before the probe runs.
        """
        _require_hashable(target)
        if self._probe is None:
            self._probe_failed(target, "no probe configured", exc_info=False)
            return self.observe(target, UNREACHABLE)
        try:
            state = self._probe(target)
        except Exception as exc:  # noqa: BLE001 - a failing probe is an unreachable target
            self._probe_failed(target, f"probe raised {_describe(exc)}", exc_info=True)
            return self.observe(target, UNREACHABLE)
        if not isinstance(state, ProbeState):
            self._probe_failed(
                target, f"probe returned {type(state).__name__}, not a ProbeState", exc_info=False
            )
            return self.observe(target, UNREACHABLE)
        self._failing.discard(target)
        return self.observe(target, state)

    def _probe_failed(self, target: Hashable, why: str, exc_info: bool) -> None:
        if target in self._failing:
            _log.debug("edge_watcher: %r unreachable (%s)", target, why, exc_info=exc_info)
            return
        self._failing.add(target)
        _log.warning(
            "edge_watcher: %r treated as unreachable: %s (warned once until a good read)",
            target, why, exc_info=exc_info,
        )

    def observe(self, target: Hashable, state: ProbeState) -> Optional[Dict[str, Any]]:
        """Feed one observation. Returns a fire / would_fire record on an
        ABSENT -> PRESENT edge of a primed target, else None. Raises
        ``TypeError`` for an unhashable target and ``ValueError`` for a
        ``state`` that is not a ``ProbeState``."""
        _require_hashable(target)
        if not isinstance(state, ProbeState):
            raise ValueError(f"edge_watcher: state must be a ProbeState, got {state!r}")
        if state is UNREACHABLE:
            # Keep the last REACHABLE state for reporting; the cleared primed
            # flag alone is what stops the next good read from firing.
            self._primed[target] = False
            return None
        self._failing.discard(target)  # a reachable read ends a failure streak
        prev = self._last.get(target)
        self._last[target] = state
        if not self._primed.get(target, False):
            self._primed[target] = True  # priming read: never an event
            return None
        if not (prev is ABSENT and state is PRESENT):
            return None
        return self._act(target, prev)

    def _act(self, target: Hashable, prev: ProbeState) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "target": target,
            "action": "would_fire" if self.dry_run else "fire",
            "dry_run": self.dry_run,
            "prev": prev.value,
            "state": PRESENT.value,
            "ts": time.time(),
        }
        if self.dry_run:
            _log.info("edge_watcher: DRY-RUN would fire on_appear(%r)", target)
            return record
        if self._on_appear is not None:
            try:
                self._on_appear(target)
            except Exception as exc:  # noqa: BLE001 - the watcher must keep polling
                error = _describe(exc)
                _log.warning("edge_watcher: on_appear(%r) raised %s", target, error, exc_info=True)
                record["error"] = error
        return record


def _require_hashable(target: Any) -> None:
    try:
        hash(target)
    except TypeError:
        raise TypeError(
            f"edge_watcher: target must be hashable, got {type(target).__name__}"
        ) from None


def _describe(exc: BaseException) -> str:
    """``"Type: message"`` that never raises, even when ``str(exc)`` does."""
    name = type(exc).__name__
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001 - a broken __str__ must not escape poll
        return f"{name}: <unprintable>"
    return f"{name}: {text}" if text else name
