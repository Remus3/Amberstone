"""win32_atomic_io - atomic write / tolerant read for polled files on Windows.

Public surface:

    atomic_write_json(path, payload, *, indent=2)
    atomic_write_bytes(path, data)
    atomic_write_text(path, content)
    read_json_dict(path, default=None) -> dict

Every writer creates parent directories on demand, writes to a per-writer
scratch file that is a sibling of the destination, and renames it into place
with a bounded retry on the Windows PermissionError (WinError 5) that a
concurrent reader provokes. `read_json_dict` never raises on a degraded file:
missing, a directory, non-UTF-8, malformed JSON, or valid JSON that is not an
object all yield a fresh deep copy of the caller's default.

Stdlib only. See _atomic.py for the reasoning behind each detail.
"""
from __future__ import annotations

from ._atomic import atomic_write_bytes, atomic_write_json, atomic_write_text, read_json_dict

__version__ = "0.1.0"

__all__ = [
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "read_json_dict",
    "__version__",
]
