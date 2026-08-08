# arch: process-wide dedupe for the LCU lockfile notice | section=lcu | frozen=no
"""Process-wide dedupe for the "LCU lockfile not found" notice.

`lcu/lcu_client.py` already throttles that notice, but it does so in
PER-INSTANCE state (`_lockfile_missing_logged` + `_lockfile_missing_last_log`,
set in `LcuClient.__init__` at `lcu/lcu_client.py:73` and `:77`). Two
long-lived clients live in the RC process, so the throttle runs twice and the
line lands twice per window.

MEASURED on the daily logs (only `main.py:40` calls `core.log_setup.setup`, so
`logs/YYYY-MM-DD.log` has exactly ONE writer process and the pairing is
in-process, not cross-process):

  2026-08-06  2567 of 4924 lines (52.1 pct), 41.0 pct of them duplicates
  2026-08-07  2681 of 4756 lines (56.4 pct), 42.6 pct duplicates
  2026-08-08  1587 of 2651 lines (59.9 pct), 41.2 pct duplicates

The per-timestamp histogram is `{1: n, 2: m}` on every day sampled - never 3 -
and the paired records land 0-1 ms apart, which is what two clients polling the
same lockfile in the same process looks like. Dropping the duplicate half
removes 21-25 pct of the whole log with no loss of signal.

WHY A FILTER AND NOT SHARED STATE ON THE CLIENT
`lcu/lcu_client.py` is on the CLAUDE.md frozen list. A `logging.Filter` on the
`rc.lcu` logger reaches every emitter of the notice - including ones this
module has never heard of - without touching the frozen module, which is also
why it is robust to WHICH second client is doing the polling.

WHY THIS CANNOT SWALLOW A RE-OPENED GAP
The frozen client records a deliberate intent at `lcu/lcu_client.py:105-107`:
the first notice of each gap stays immediate, and "a re-opened gap must not be
swallowed by a still-running window". Hoisting the timestamp alone would
violate exactly that. So the unit of suppression here is the EPISODE, not the
window: an episode is a transition from lockfile-present to lockfile-missing,
and it is CLOSED by any of the three connection-state lines the frozen client
emits (`:96` connected, `:151` reconnected, `:160` lockfile gone). Once closed,
the very next missing-notice is passed through immediately no matter how young
the throttle window is. Only repeats INSIDE one still-open episode are rate
limited, and those are precisely the lines that carry nothing the first did not.
"""
from __future__ import annotations

import logging
import threading
import time

# The frozen client logs this notice from two branches, INFO at
# lcu/lcu_client.py:110 (first of a gap) and DEBUG at :114 (throttled repeat).
# Matched as a substring so the trailing advice text can be reworded without
# silently disabling the dedupe.
MISSING_NEEDLE = "LCU lockfile not found"

# Any of these means the client currently HAS credentials or has just observed
# the lockfile disappear, so whatever gap was being reported is over and the
# next missing-notice describes a new one: lcu/lcu_client.py:96, :151, :160.
EPISODE_END_NEEDLES = (
    "LCU connected:",
    "LCU reconnected:",
    "LCU lockfile gone",
)

# Mirrors lcu/lcu_client.py:44 _LOCKFILE_MISSING_REPEAT_S. Duplicated rather
# than imported because importing the client from the `lcu` package __init__
# would be circular; tests/test_lcu_lockfile_notice_dedupe.py pins the two
# together so the copy cannot drift.
REPEAT_S = 60.0

LOGGER_NAME = "rc.lcu"


class LockfileNoticeFilter(logging.Filter):
    """Pass one missing-notice per episode, then one per `repeat_s`.

    Stateful and shared by every emitter on the logger, so the state is guarded
    by a lock: the RC process reaches `connect()` from the auto-accept loop's
    worker thread and from the dashboard's request threads.
    """

    def __init__(self, repeat_s: float = REPEAT_S) -> None:
        super().__init__()
        self._repeat_s = repeat_s
        self._lock = threading.Lock()
        self._episode_open = False
        self._last_pass = 0.0

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(needle in message for needle in EPISODE_END_NEEDLES):
            with self._lock:
                self._episode_open = False
            return True
        if MISSING_NEEDLE not in message:
            return True
        # Monotonic for the same reason the frozen client uses it
        # (lcu/lcu_client.py:74-76): wall clock can step backwards over NTP or
        # DST and would then stall the notice for hours.
        now = time.monotonic()
        with self._lock:
            if not self._episode_open:
                self._episode_open = True
                self._last_pass = now
                return True
            if now - self._last_pass >= self._repeat_s:
                self._last_pass = now
                return True
            return False

    def reset(self) -> None:
        """Forget the current episode. For tests only - the filter is process
        global, so without this one test's episode leaks into the next."""
        with self._lock:
            self._episode_open = False
            self._last_pass = 0.0


def current(logger_name: str = LOGGER_NAME) -> LockfileNoticeFilter | None:
    """The filter already attached to `logger_name`, or None."""
    for existing in logging.getLogger(logger_name).filters:
        if isinstance(existing, LockfileNoticeFilter):
            return existing
    return None


def install(logger_name: str = LOGGER_NAME) -> LockfileNoticeFilter:
    """Attach the filter to `logger_name`, at most once. Returns the filter.

    Attached to the LOGGER rather than a handler so it applies whatever
    handlers `core/log_setup.py` (frozen) has configured, and so it is in place
    before any handler exists.
    """
    already = current(logger_name)
    if already is not None:
        return already
    installed = LockfileNoticeFilter()
    logging.getLogger(logger_name).addFilter(installed)
    return installed
