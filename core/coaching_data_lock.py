"""
core/coaching_data_lock.py - combined process-local + cross-process
lock for coaching_data.json read-modify-write cycles.

Shared across the writers of `coaching_data.json`:
  - SR coach integration (_write_fields)
  - dashboard._writers.set_pregame
  - dashboard /api/command "refresh"
  - aftergame_summary.write_to_client_coaching_data (may run out-of-process
    via supervisor)

The pattern each writer SHOULD follow:

    from core.coaching_data_lock import coaching_data_lock
    with coaching_data_lock():
        cur = load_json(path)
        cur.update(my_changes)
        atomic_write(path, cur)

This converts the dangerous read-modify-write into a serialized
critical section so concurrent writers can't lose each other's updates.

Locking strategy:
  1. Acquire the in-process `threading.Lock` first (fast path; serializes
     concurrent threads in the same RC process).
  2. Then acquire an OS-level file lock on `ops/runtime/coaching_data.lock`
     via `portalocker` (Tier 3 #14, 2026-05-01). portalocker wraps the
     stdlib msvcrt/fcntl primitives in a battle-tested cross-platform
     context manager; replaced the in-house msvcrt loop because the
     custom locking proved fragile across antivirus + OneDrive paths.

If the OS lock acquire fails (timeout or transient permission error),
the writer proceeds anyway - better to risk a lost update than block
the coach for an unbounded window. The in-process lock still applies.
"""
import threading
from pathlib import Path

import portalocker

# Single module-level Lock; all importers share the same instance.
_LOCK = threading.Lock()
_LOCK_FILE = Path(__file__).resolve().parent.parent / "ops" / "runtime" / "coaching_data.lock"
_LOCK_TIMEOUT_S = 2.0


class _CombinedLock:
    """Composes an in-process threading.Lock with an OS-level file lock.

    File-lock acquire is best-effort with a 2s timeout - we'd rather
    risk a rare lost update than block the coach indefinitely on a
    misbehaving lock holder."""

    def __init__(self) -> None:
        self._tl = _LOCK
        self._fl: portalocker.Lock | None = None
        self._has_file_lock = False

    def __enter__(self) -> "_CombinedLock":
        # 1. In-process lock - fast, serializes coach + dashboard threads.
        self._tl.acquire()
        # 2. OS file lock via portalocker. EXCLUSIVE | NON_BLOCKING is the
        #    default; we override timeout so it polls up to 2s before
        #    raising LockException.
        try:
            _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._fl = portalocker.Lock(
                str(_LOCK_FILE), mode="a+b", timeout=_LOCK_TIMEOUT_S,
            )
            self._fl.acquire()
            self._has_file_lock = True
        except portalocker.LockException:
            # Holder didn't release in time - fall through with TL only.
            self._has_file_lock = False
            self._fl = None
        except Exception:  # noqa: BLE001
            # Any other lock-infra failure (e.g. permissions, AV blocking
            # the lockfile) - also fall through. TL still serializes the
            # in-process callers.
            self._has_file_lock = False
            self._fl = None
        return self

    def __exit__(self, et: object, ev: object, tb: object) -> bool:
        # Release file lock first, then the in-process lock.
        if self._fl and self._has_file_lock:
            try:
                self._fl.release()
            except Exception:  # noqa: BLE001
                pass
        self._fl = None
        self._has_file_lock = False
        self._tl.release()
        return False


def coaching_data_lock() -> "_CombinedLock":
    """Context manager - see module docstring. Always release on exit
    even if the file-lock acquire failed; the threading.Lock guarantees
    in-process serialization regardless."""
    return _CombinedLock()
