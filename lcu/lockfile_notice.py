# arch: process-wide dedupe for the LCU lockfile notice | section=lcu | frozen=no
"""Process-wide dedupe for the "LCU lockfile not found" notice.

Citations below name SYMBOLS, not line numbers: the frozen client's line
numbers drifted by 20-plus lines after this module was written (re-measured
s144 true-audit cycle 71), while the symbols and the log literals did not.
`tests/test_lcu_lockfile_notice_dedupe.py` pins the literals off disk.

`lcu/lcu_client.py` already throttles that notice, but the throttle state
(`_lockfile_missing_logged` + `_lockfile_missing_last_log`, set in
`LcuClient.__init__`) is shared by every caller of `LcuClient.connect()`, and
there are TWO of them at 1 Hz on the SAME instance:

  * the frozen auto-accept tick, `LcuClient._auto_accept_tick`;
  * the rune writer's poll, `RuneWriter._poll` in `lcu/lcu_rune_writer.py`
    (`POLL_INTERVAL`, default 1.0 s), spawned onto the SAME AppLoop. It holds
    the same object: `main.py` builds the one `LcuClient()` and hands it to
    `RuneWriter` (imported there as `_RuneWriter`).

Both loops run their body through `asyncio.to_thread`, so the two callers land
in DIFFERENT worker threads dispatched from the same loop iteration and the
throttle's read-compare-write inside `connect()`

    now = time.monotonic()
    elif now - self._lockfile_missing_last_log >= _LOCKFILE_MISSING_REPEAT_S:
        _log.debug(...); self._lockfile_missing_last_log = now

is unsynchronized. Both threads read the old timestamp, both pass the
comparison, both log. That is why the duplicate is exactly 2 and never 3 (there
are exactly two callers), why it appears only on the 60 s boundary, and why the
pair shares a millisecond. Serialised callers would self-suppress; this is a
race, not merely shared state - which is why `self._lock` below is load-bearing
and must not be simplified away.

The rune writer's `connect()` is deliberate, documented and idempotent (added
after the 2026-07-04 pid-6440 silent death so the writer survives a dead
auto-accept loop). It is not a leak and must not be removed - the duplicate
line is the bug, not the second caller.

MEASURED on the daily logs (only `main.py` calls `core.log_setup.setup`, so
`logs/YYYY-MM-DD.log` has exactly ONE writer process and the pairing is
in-process, not cross-process):

  2026-08-06  2567 of 4924 lines (52.1 pct), 41.0 pct of them duplicates
  2026-08-07  2681 of 4756 lines (56.4 pct), 42.6 pct duplicates
  2026-08-08  1587 of 2651 lines (59.9 pct), 41.2 pct duplicates

The per-timestamp histogram is `{1: n, 2: m}` on every day sampled - never 3 -
and the paired records land 0-1 ms apart.

That there is ONE client and not two is measured, not assumed. On 2026-08-07
the first-of-gap INFO line appears 19 times and is NEVER paired, while the
throttled DEBUG repeat is 1143 pairs and never a triple. Two independent
clients would each own `_lockfile_missing_logged` and both would announce the
gap; one shared instance emits exactly one first-of-gap line per boot, and that
day had exactly 19 boots (`Auto-accept started`, `Overlay running` and
`LCU auto-accept ARMED` are 19 apiece). A duplicate log handler is ruled out
too: the adjacent-identical-line count is 1143 for `rc.lcu` and 0 for every
other logger.

WHY A FILTER AND NOT SHARED STATE ON THE CLIENT
`lcu/lcu_client.py` is on the CLAUDE.md frozen list. A `logging.Filter` on the
`rc.lcu` logger drops the second of two identical emissions whoever makes them,
so it is deliberately agnostic to WHICH caller emits and stays correct if a
third `connect()` caller is ever added.

WHY THIS CANNOT SWALLOW A RE-OPENED GAP
The frozen client records a deliberate intent in `connect()`: the first notice
of each gap stays immediate, and "a re-opened gap must not be swallowed by a
still-running window". Hoisting the timestamp alone would violate exactly that.
So the unit of suppression here is the EPISODE, not the window: an episode is a
transition from lockfile-present to lockfile-missing, and it is CLOSED by any
of the three connection-state lines the frozen client emits (connected,
reconnected, lockfile gone - `EPISODE_END_NEEDLES`). Once closed, the very next
missing-notice is passed through immediately no matter how young the throttle
window is. Only repeats INSIDE one still-open episode are rate limited, and
those are precisely the lines that carry nothing the first did not.

WHY THE FILTER NEVER RAISES (s144 true-audit cycle 71)
A logger-level filter runs inside `Logger.handle()` with no guard around it, so
an exception from `record.getMessage()` (a `%d` given a str, too few or too many
args, a message object whose `__str__` raises) would escape from the CALLER's
`_log.info(...)` - inside the frozen client's `connect()`. Without the filter
the stdlib reports the same slip through `Handler.handleError` and carries on.
So an unformattable record is passed through untouched (the handler then
reports it the stdlib way) and never touches the episode state.
"""
from __future__ import annotations

import logging
import math
import threading
import time

# The frozen client logs this notice from two branches of `connect()`, INFO
# for the first of a gap and DEBUG for the throttled repeat.
# Matched as a substring so the trailing advice text can be reworded without
# silently disabling the dedupe.
MISSING_NEEDLE = "LCU lockfile not found"

# Any of these means the client currently HAS credentials or has just observed
# the lockfile disappear, so whatever gap was being reported is over and the
# next missing-notice describes a new one (all three are `connect()` lines).
EPISODE_END_NEEDLES = (
    "LCU connected:",
    "LCU reconnected:",
    "LCU lockfile gone",
)

# Mirrors lcu/lcu_client.py _LOCKFILE_MISSING_REPEAT_S. Duplicated rather
# than imported because importing the client from the `lcu` package __init__
# would be circular; tests/test_lcu_lockfile_notice_dedupe.py pins the two
# together so the copy cannot drift.
REPEAT_S = 60.0

LOGGER_NAME = "rc.lcu"

# Serialises install()'s check-then-attach, so two racing callers can never
# attach two independent filters (each with its own episode state, of which
# `current()` - and so the test reset - would only ever see the first).
_INSTALL_LOCK = threading.Lock()


class LockfileNoticeFilter(logging.Filter):
    """Pass one missing-notice per episode, then one per `repeat_s`.

    Stateful and shared by every emitter on the logger, so the state is guarded
    by a lock: the RC process reaches `connect()` from the auto-accept tick and
    the rune writer's poll, each in its own `asyncio.to_thread` worker.

    `repeat_s` must be a finite real >= 0. NaN would make every comparison
    False and silence the repeat for the rest of the episode; a negative,
    infinite or non-number value is a caller bug, refused at construction.
    """

    def __init__(self, repeat_s: float = REPEAT_S) -> None:
        super().__init__()
        if isinstance(repeat_s, bool) or not isinstance(repeat_s, (int, float)):
            raise TypeError(
                f"repeat_s must be a real number, not {type(repeat_s).__name__}")
        if not math.isfinite(repeat_s) or repeat_s < 0:
            raise ValueError(f"repeat_s must be finite and >= 0, got {repeat_s!r}")
        self._repeat_s = float(repeat_s)
        self._lock = threading.Lock()
        self._episode_open = False
        self._last_pass = 0.0

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - str(record.msg) runs an arbitrary __str__
            # %-format slips raise TypeError / ValueError / KeyError /
            # IndexError, but the set is open. Pass the record on untouched:
            # the handler's own format() raises the same error inside emit()
            # and reports it through handleError, exactly as with no filter
            # attached. The episode state is not touched.
            return True
        if any(needle in message for needle in EPISODE_END_NEEDLES):
            with self._lock:
                self._episode_open = False
            return True
        if MISSING_NEEDLE not in message:
            return True
        # Monotonic for the same reason the frozen client uses it (see
        # `LcuClient.__init__`): wall clock can step backwards over NTP or
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
    before any handler exists. The check-then-attach runs under
    `_INSTALL_LOCK`, so concurrent callers all get the one filter.
    """
    with _INSTALL_LOCK:
        already = current(logger_name)
        if already is not None:
            return already
        installed = LockfileNoticeFilter()
        logging.getLogger(logger_name).addFilter(installed)
        return installed
