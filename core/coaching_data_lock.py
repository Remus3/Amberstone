"""
core/coaching_data_lock.py - combined process-local + cross-process
lock for coaching_data.json read-modify-write cycles.

MEASURED HOLDERS (2026-08-30, lane 8 cycle 28 - grep for `coaching_data_lock`
outside tests/ and you get exactly these four, all THREADS OF ONE PROCESS):
  - coach_integration/_coach.py:117   (reset_state)
  - coach_integration/_coach.py:678   (_write_fields read-modify-write)
  - dashboard/_writers.py:73          (set_pregame)
  - dashboard/routes_state.py:637     (/api/command "refresh")

The pattern each writer SHOULD follow:

    from core.coaching_data_lock import coaching_data_lock
    with coaching_data_lock():
        cur = load_json(path)
        cur.update(my_changes)
        atomic_write(path, cur)

This converts the dangerous read-modify-write into a serialized
critical section so concurrent writers can't lose each other's updates.

SCOPE - READ THIS BEFORE TRUSTING THE LOCK (measured, cycle 28):
  1. There is currently NO cross-process WRITER of coaching_data.json.
     RC runs as a single process (`pythonw.exe main.py`) with the dashboard
     in-process, so all four holders above are threads inside it. A second
     process, `agents.supervisor`, only READS the file
     (agents/supervisor.py:774) and is protected by atomic replace, not by
     this lock. The file-lock half is therefore defence in depth today,
     not an active serializer. Do not delete it on that basis - it is the
     only thing that would work if a writer ever moves out of process -
     but do not assume it is carrying load either.
  2. The lock does NOT cover every writer. `app/__init__.py` `_write_data()`
     writes root coaching_data.json WITHOUT this lock, reached from
     app/_overlay_manager.py and app/_game_lifecycle.py. That gap is filed
     as RM-277; `app/__init__.py` is a FROZEN file, so closing it needs an
     adjudicating agent. Until then the docstring claim that concurrent
     writers "can't lose each other's updates" holds only among the four
     holders listed above.

A PRIOR VERSION OF THIS DOCSTRING NAMED
`aftergame_summary.write_to_client_coaching_data (may run out-of-process via
supervisor)` as a sharer of this lock. That was false in three independent
ways and is recorded here so it is not reintroduced: core/aftergame_summary.py
has ZERO production importers (it is reachable only through its own
`if __name__ == "__main__"` block), it never calls this lock, and it targets
`data/coaching_data.json` while the SR file is root `coaching_data.json`
(app/__init__.py:42).

Locking strategy:
  1. Acquire the in-process `threading.Lock` first, bounded by
     `_TL_TIMEOUT_S` (see the note on that constant).
  2. Then acquire an OS-level file lock on `ops/runtime/coaching_data.lock`
     via `portalocker` (Tier 3 #14, 2026-05-01). `ops/runtime/` is
     gitignored and nothing under it is tracked, so the directory does not
     exist in a fresh clone and the mkdir below is load-bearing on first
     run, not defensive boilerplate.

DEGRADATION IS NOW OBSERVABLE (RM-199). Both halves still fail open - a
lost update is preferred to a blocked coach - but a degraded lock is no
longer indistinguishable from a healthy one. `coaching_data_lock_stats()`
exposes the counts for tests and for ops, and the suppression described
below is a LOGGING suppressor only - it never gates whether a lock is
attempted or taken.

Be precise about which half suppresses what, because the two differ:
  - FILE lock: the first failure of an episode is logged at WARNING and
    repeats within that episode are counted rather than logged. Across
    episodes the first `_MAX_EPISODES_LOGGED` are a burst allowance, after
    which at most one episode per `_LOG_REOPEN_AFTER_S` is logged. That
    bounds a stuck lock and a flapping one WITHOUT ever going permanently
    silent, which a bare cap would do - and permanent silence is the exact
    RM-199 condition this module was opened to fix.
  - IN-PROCESS lock: every timeout is logged, with no suppression. It
    needs none - a timeout costs `_TL_TIMEOUT_S` seconds, so the path is
    self-rate-limiting - but do not read the file-lock wording as covering
    it.

TWO HONEST LIMITS ON THIS FIX, both measured rather than assumed:
  1. Bounding the in-process acquire converts an INFINITE hang into a
     30-second one. On a sub-second coach poll cadence a 30 s block is
     still a visibly dead coach. "The unbounded acquire is fixed" must not
     be read as "the coach can no longer stall".
  2. The fail-open path is not purely lossy in the worst case.
     `coach_integration/_coach.py:713` derives its scratch name from the
     destination (`.tmp`), so two coach writers proceeding concurrently
     could collide on one scratch file and tear it, rather than merely
     losing an update. Reaching that needs a holder wedged past
     `_TL_TIMEOUT_S`, where the previous behaviour was a permanently dead
     coach thread with no diagnostic at all - so the trade still favours
     this design - but the worst case is recorded here rather than hidden.
     The scratch-name half belongs to RM-261.
"""
import logging
import threading
import time
from pathlib import Path

import portalocker

_log = logging.getLogger(__name__)

# Single module-level Lock; all importers share the same instance.
_LOCK = threading.Lock()
_LOCK_FILE = Path(__file__).resolve().parent.parent / "ops" / "runtime" / "coaching_data.lock"
_LOCK_TIMEOUT_S = 2.0

# Bound on the IN-PROCESS acquire. Chosen deliberately large rather than
# snug: a legitimate holder can occupy the critical section for seconds,
# not milliseconds. Measured worst case is roughly 6.2s - portalocker polls
# for up to _LOCK_TIMEOUT_S (2.0s) while holding this lock, and
# coach_integration/_coach.py:675-734 wraps its whole `with` block in a
# 3-attempt retry with sleeps. A snug timeout would therefore fire during
# ordinary contention and make the fail-open path routine, which would
# trade a rare hang for frequent lost updates - a strictly worse deal. At
# 30s this fires only when a holder is genuinely wedged, and at that point
# proceeding without mutual exclusion beats a permanently dead coach
# thread. tests/test_p2w1_app_b.py:359 holds this lock for 0.25s (in
# test_reset_state_holds_coaching_data_lock, which starts at :338) and
# asserts the writer still blocks, so any value at or below 0.25 breaks it.
_TL_TIMEOUT_S = 30.0

# Degradation bookkeeping. Guarded by its own lock so it can be updated
# while _LOCK is NOT held (the timeout path).
_stats_lock = threading.Lock()
_stats = {
    "file_lock_failures": 0,
    "file_lock_release_failures": 0,
    "thread_lock_timeouts": 0,
    "degradation_episodes": 0,
}
_file_lock_degraded = False
_episode_logged = False
_lock_dir_ready = False
# Bumped whenever the lock directory is implicated in a failure, so a mkdir
# already in flight cannot publish a stale memo. See `_ensure_lock_dir`.
_dir_epoch = 0

# A transition-based suppressor bounds a STUCK lock but not a FLAPPING one:
# a lock that alternates fail / succeed opens a new episode every cycle and
# would emit a DEGRADED + RECOVERED pair each time, flooding
# `logs/YYYY-MM-DD.log` at exactly the rate the suppression was added to
# prevent. So the first `_MAX_EPISODES_LOGGED` episodes are logged as a
# burst allowance - a rapid-onset problem should be visible immediately -
# and past that the wall-clock floor below takes over.
_MAX_EPISODES_LOGGED = 5

# A bare cap re-creates the RM-199 condition it was added to avoid: after
# five episodes a long-lived RC goes permanently silent again, and
# `coaching_data_lock_stats()` has ZERO production callers, so the counters
# are not a substitute channel.
#
# The floor is WALL-CLOCK, deliberately. An earlier revision re-opened
# logging after a streak of N successful ACQUIRES, which measures the wrong
# axis: the four holders take this lock on a poll cadence, so 50 successes
# is seconds rather than days - a lock failing once an hour would re-open
# before every outage and log all of them (the flood the cap exists to
# stop), while a lock failing once per 50 acquires would stay silent
# forever. A time floor is correct in both directions.
#
# `time.monotonic` rather than `time.time`, and get the DIRECTION right:
# it is a FORWARD wall-clock jump - an NTP correction, a DST change, a VM
# resume - that makes the last logged episode look arbitrarily old and so
# wrongly re-opens the gate. A BACKWARD step makes the elapsed time
# negative, which suppresses rather than re-opens. Monotonic is immune to
# both, but a test written from the backward case alone would not
# discriminate the two clocks. Same family as RM-269.
_LOG_REOPEN_AFTER_S = 1800.0
_episodes_logged_window = 0
_last_episode_logged_at: float | None = None


def coaching_data_lock_stats() -> dict:
    """Snapshot of the degradation counters. Read-only copy - mutating the
    result does not affect the module. Exists because nothing in this repo
    scrapes WARNING lines out of `logs/`, so the log alone cannot be
    asserted on by a test or polled by ops."""
    with _stats_lock:
        return dict(_stats)


def _reset_state_for_tests() -> None:
    """Clear the degradation counters, the transition flag and the mkdir
    memo. Test hook only - production never calls this. It exists because
    the transition flag deliberately suppresses repeat WARNINGs, which
    would otherwise make a second test in the same process unable to
    observe the log it is asserting on."""
    global _file_lock_degraded, _episode_logged, _lock_dir_ready
    global _episodes_logged_window, _last_episode_logged_at, _dir_epoch
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0
        _file_lock_degraded = False
        _episode_logged = False
        _lock_dir_ready = False
        _episodes_logged_window = 0
        _last_episode_logged_at = None
        _dir_epoch = 0


def _implicates_lock_dir(exc: BaseException) -> bool:
    """True when a failure suggests `ops/runtime/` itself is missing or is
    not a directory, which is the only case in which the mkdir memo needs
    re-arming. portalocker re-raises some errors wrapped, so walk a bounded
    stretch of the cause chain rather than only inspecting the top."""
    seen = 0
    cur: BaseException | None = exc
    while cur is not None and seen < 4:
        if isinstance(cur, (FileNotFoundError, NotADirectoryError)):
            return True
        cur = cur.__cause__
        seen += 1
    return False


def _note_file_lock_failure(reason: str, exc: BaseException) -> None:
    global _file_lock_degraded, _episode_logged, _lock_dir_ready
    global _episodes_logged_window, _last_episode_logged_at, _dir_epoch
    # Re-arm the mkdir ONLY when the failure implicates the DIRECTORY. An
    # unconditional re-arm defeats the memo in precisely the state the memo
    # exists for: under a persistent antivirus block on the lock FILE, every
    # acquire would re-run mkdir inside the process-wide lock - the state in
    # which acquires are both most frequent and slowest.
    #
    # The cause-chain walk is a HEURISTIC and it can fail in the worse
    # direction: portalocker's timeout branch re-raises a saved
    # `LockException` that carries NO `__cause__`, so a directory-missing
    # failure surfacing through it would look file-only and the memo would
    # never be re-armed - permanent degradation, strictly worse than the
    # extra syscalls the narrowing was avoiding. So confirm with an exact
    # check. It costs one `stat` per FAILED acquire, never on the hot path,
    # and it is immune to an unchained exception.
    now = time.monotonic()
    dir_implicated = _implicates_lock_dir(exc)
    if not dir_implicated:
        try:
            dir_implicated = not _LOCK_FILE.parent.is_dir()
        except OSError:
            dir_implicated = True
    with _stats_lock:
        _stats["file_lock_failures"] += 1
        n = _stats["file_lock_failures"]
        first = not _file_lock_degraded
        if first:
            _stats["degradation_episodes"] += 1
            episodes = _stats["degradation_episodes"]
            # Burst allowance first, so a rapid-onset problem is visible at
            # once; then a wall-clock floor, so the rate is bounded forever
            # without ever going permanently silent.
            if _episodes_logged_window < _MAX_EPISODES_LOGGED:
                should_log = True
                _episodes_logged_window += 1
            elif (_last_episode_logged_at is None
                  or (now - _last_episode_logged_at) >= _LOG_REOPEN_AFTER_S):
                # A re-open grants a FRESH BURST, not a single line: setting
                # the window to 1 leaves it below the allowance, so the next
                # few episodes log too. That is deliberate - a new problem
                # after a quiet stretch deserves the same diagnostic burst
                # the first one got. The ceiling is therefore
                # _MAX_EPISODES_LOGGED lines per _LOG_REOPEN_AFTER_S (5 per
                # 30 min, ~240/day worst case against a log that already
                # runs 285-450 KB/day), not one line per interval. To make
                # it one line, set this to _MAX_EPISODES_LOGGED instead.
                should_log = True
                _episodes_logged_window = 1
            else:
                should_log = False
            if should_log:
                _last_episode_logged_at = now
            _episode_logged = should_log
        else:
            should_log = False
        _file_lock_degraded = True
        if dir_implicated:
            _lock_dir_ready = False
            # Invalidate any mkdir in flight - see _ensure_lock_dir.
            _dir_epoch += 1
    if should_log:
        _log.warning(
            "coaching_data_lock: cross-process file lock NOT acquired (%s: %s) - "
            "DEGRADED to in-process locking only. Repeats within this episode are "
            "counted, not logged, and only the first %d episodes are logged at all; "
            "read coaching_data_lock_stats() for the running totals (failures now "
            "%d, episode %d).",
            reason, exc, _MAX_EPISODES_LOGGED, n, episodes,
        )


def _note_file_lock_ok() -> None:
    global _file_lock_degraded, _episode_logged
    with _stats_lock:
        was_degraded = _file_lock_degraded
        logged = _episode_logged
        n = _stats["file_lock_failures"]
        _file_lock_degraded = False
        _episode_logged = False
    # Only close an episode that was actually opened in the log, so the
    # episode cap bounds BOTH halves of the pair and a flapping lock cannot
    # emit unpaired RECOVERED lines forever.
    if was_degraded and logged:
        # WARNING rather than INFO so one `grep WARNING` shows the whole
        # episode - start and end - instead of only its opening.
        _log.warning(
            "coaching_data_lock: cross-process file lock RECOVERED after %d "
            "cumulative failure(s); no longer degraded.", n,
        )


def _note_thread_lock_timeout() -> None:
    with _stats_lock:
        _stats["thread_lock_timeouts"] += 1
        n = _stats["thread_lock_timeouts"]
    _log.warning(
        "coaching_data_lock: in-process lock NOT acquired within %.1fs - proceeding "
        "DEGRADED with no mutual exclusion, so a concurrent read-modify-write may "
        "lose this update. A holder this slow is wedged, not merely busy. "
        "Timeout count now %d.",
        _TL_TIMEOUT_S, n,
    )


def _ensure_lock_dir() -> None:
    """mkdir the lockfile's parent once per process rather than on every
    acquire. The mkdir is a filesystem syscall executed while holding the
    process-wide lock, on exactly the antivirus / OneDrive path this module
    adopted portalocker to survive, so doing it per-entry put an unbounded
    call inside the critical section. A failure that implicates the
    directory re-arms it (see `_implicates_lock_dir`); a failure that
    implicates only the lock FILE deliberately does not, because re-arming
    on those would defeat the memo exactly under a persistent block.

    The epoch guard closes a small lost-re-arm race: this runs the mkdir
    OUTSIDE `_stats_lock` (it is a filesystem call), so a concurrent
    `_note_file_lock_failure` could clear the memo while this mkdir is in
    flight and then have this function set it straight back to True,
    silently swallowing the re-arm and delaying recovery by a cycle. Taking
    the epoch before the mkdir and only publishing the memo if it has not
    moved makes the lost update impossible without holding a lock across
    the syscall."""
    global _lock_dir_ready
    if _lock_dir_ready:
        return
    with _stats_lock:
        epoch = _dir_epoch
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _stats_lock:
        if epoch == _dir_epoch:
            _lock_dir_ready = True


class _CombinedLock:
    """Composes an in-process threading.Lock with an OS-level file lock.

    BOTH halves are best-effort and BOTH fail open - the module would
    rather risk a lost update than block the coach indefinitely. What is
    new since RM-199 is that neither half fails SILENTLY: a degraded lock
    emits a WARNING and increments a counter, so a permanently dead lock
    is distinguishable from a healthy one.

    The file-lock acquire is bounded by `_LOCK_TIMEOUT_S` (2s); the
    in-process acquire by `_TL_TIMEOUT_S`. Note that portalocker's own
    `open()` of the lockfile happens BEFORE its timeout loop starts, so
    the 2s bounds the lock POLL, not the whole acquire."""

    def __init__(self) -> None:
        self._tl = _LOCK
        self._fl: portalocker.Lock | None = None
        self._has_file_lock = False
        self._has_thread_lock = False

    def __enter__(self) -> "_CombinedLock":
        # 1. In-process lock - serializes coach + dashboard threads. Bounded:
        #    an unbounded acquire here was the one path that could block a
        #    coach thread forever, which is the exact outcome this module's
        #    stated policy exists to avoid.
        self._has_thread_lock = self._tl.acquire(timeout=_TL_TIMEOUT_S)
        if not self._has_thread_lock:
            _note_thread_lock_timeout()
        # 2. OS file lock via portalocker. Everything from here on must not
        #    be able to leave the process-wide lock orphaned: if __enter__
        #    raises, Python never calls __exit__.
        try:
            self._acquire_file_lock()
        except BaseException:
            self._release_thread_lock()
            raise
        return self

    def _acquire_file_lock(self) -> None:
        try:
            _ensure_lock_dir()
            # EXCLUSIVE | NON_BLOCKING is portalocker's default flag set, so
            # the timeout is honoured (it polls at check_interval until it
            # expires). In blocking mode a timeout would be silently inert.
            fl = portalocker.Lock(
                str(_LOCK_FILE), mode="a+b", timeout=_LOCK_TIMEOUT_S,
            )
            fl.acquire()
        except portalocker.LockException as exc:
            # A holder did not release in time - OR portalocker wrapped an
            # infrastructure failure of its own (it re-raises non-lock errors
            # as LockException). The two are not distinguishable here, which
            # is why the count matters: a transient collision is occasional,
            # a broken install is every single call.
            self._fl = None
            self._has_file_lock = False
            _note_file_lock_failure("lock unavailable", exc)
        except Exception as exc:  # noqa: BLE001
            # Raw errors from opening the lockfile reach us unwrapped, because
            # portalocker opens the handle outside its own try. Read-only
            # ops/runtime, a file where the directory should be, AV blocking
            # the path: all permanent, all land here.
            self._fl = None
            self._has_file_lock = False
            _note_file_lock_failure("lock infrastructure failure", exc)
        else:
            self._fl = fl
            self._has_file_lock = True
            _note_file_lock_ok()

    def _release_file_lock(self) -> None:
        fl, self._fl = self._fl, None
        had, self._has_file_lock = self._has_file_lock, False
        if fl is None or not had:
            return
        try:
            fl.release()
        except Exception as exc:  # noqa: BLE001
            with _stats_lock:
                _stats["file_lock_release_failures"] += 1
                n = _stats["file_lock_release_failures"]
            _log.warning(
                "coaching_data_lock: cross-process file lock release FAILED (%s) - "
                "force-closing the handle so the OS lock is not stranded. "
                "Release-failure count now %d.", exc, n,
            )
            # portalocker.Lock.release() unlocks BEFORE it closes, so a
            # raising unlock leaves the handle OPEN and the byte range still
            # locked - and portalocker.Lock has no finalizer to reclaim it.
            # Dropping the last reference would strand the OS lock until the
            # process exits, after which every later acquire burns the full
            # poll. Closing the handle releases the lock on win32 and POSIX
            # alike.
            try:
                fh = getattr(fl, "fh", None)
                if fh is not None:
                    fh.close()
                    fl.fh = None
            except Exception:  # noqa: BLE001
                _log.warning(
                    "coaching_data_lock: force-close of the lock handle also "
                    "failed; the OS lock stays held until process exit",
                    exc_info=True,
                )

    def _release_thread_lock(self) -> None:
        # Only ever release what this instance actually took. Releasing an
        # unheld threading.Lock raises RuntimeError, and releasing one held
        # by ANOTHER thread would silently hand that thread's critical
        # section away - threading.Lock has no owner check.
        if self._has_thread_lock:
            self._has_thread_lock = False
            self._tl.release()

    def __exit__(self, et: object, ev: object, tb: object) -> bool:
        # Release file lock first, then the in-process lock - and release the
        # in-process one from a `finally` so no failure above can orphan it.
        try:
            self._release_file_lock()
        finally:
            self._release_thread_lock()
        return False


def coaching_data_lock() -> "_CombinedLock":
    """Context manager - see module docstring. Always releases on exit even
    if the file-lock acquire failed, and never releases an in-process lock
    it did not take."""
    return _CombinedLock()
