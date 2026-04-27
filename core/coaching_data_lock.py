"""
core/coaching_data_lock.py — combined process-local + cross-process
lock for coaching_data.json read-modify-write cycles.

Shared across the writers of `coaching_data.json`:
  - SR coach integration (_write_fields)
  - web_dashboard._set_pregame
  - web_dashboard /api/command "refresh"
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
     via msvcrt.locking (Windows). This serializes across processes.
  3. On non-Windows hosts, the file-lock step degrades to a no-op (RC
     deploys to Windows only today).

If the OS lock acquire fails (e.g., another process holds it for >2s),
the writer proceeds anyway — better to risk a lost update than block
the coach for an unbounded window. The in-process lock still applies.
"""
import os
import threading
from pathlib import Path

# Single module-level Lock; all importers share the same instance.
_LOCK = threading.Lock()
_LOCK_FILE = Path(__file__).resolve().parent.parent / "ops" / "runtime" / "coaching_data.lock"


class _CombinedLock:
    """Composes an in-process threading.Lock with an OS-level file lock.

    File-lock acquire is best-effort with a short timeout — we'd rather
    risk a rare lost update than block the coach indefinitely on a
    misbehaving lock holder."""

    def __init__(self) -> None:
        self._tl = _LOCK
        self._fh = None
        self._has_file_lock = False

    def __enter__(self):
        # 1. In-process lock — fast, serializes coach + dashboard threads.
        self._tl.acquire()
        # 2. OS file lock — Windows-only via msvcrt.
        if os.name == "nt":
            try:
                _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
                # Open in a+ so the file is created if missing and we
                # can lock the first byte.
                self._fh = open(_LOCK_FILE, "a+b")
                import msvcrt as _ms
                # Try non-blocking acquire with retries up to ~2s. Each
                # locking call locks the next byte from the current pos,
                # so seek to 0 first.
                self._fh.seek(0)
                deadline = __import__("time").monotonic() + 2.0
                while True:
                    try:
                        _ms.locking(self._fh.fileno(), _ms.LK_NBLCK, 1)
                        self._has_file_lock = True
                        break
                    except OSError:
                        if __import__("time").monotonic() >= deadline:
                            break
                        __import__("time").sleep(0.05)
            except Exception:
                # Lock infrastructure failed — fall through with TL only.
                self._has_file_lock = False
                if self._fh:
                    try: self._fh.close()
                    except Exception: pass
                    self._fh = None
        return self

    def __exit__(self, et, ev, tb):
        # Release file lock first, then the in-process lock.
        if self._fh and self._has_file_lock:
            try:
                import msvcrt as _ms
                self._fh.seek(0)
                _ms.locking(self._fh.fileno(), _ms.LK_UNLCK, 1)
            except Exception:
                pass
        if self._fh:
            try: self._fh.close()
            except Exception: pass
        self._tl.release()
        return False


def coaching_data_lock():
    """Context manager — see module docstring. Always release on exit
    even if the file-lock acquire failed; the threading.Lock guarantees
    in-process serialization regardless."""
    return _CombinedLock()
