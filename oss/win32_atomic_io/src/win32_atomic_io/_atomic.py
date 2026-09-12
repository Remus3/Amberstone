"""Atomic write / tolerant read primitives for files that other processes poll.

The problem this solves: a file that is written by one process and repeatedly
read (mtime + parse) by others. A naive `open(path, "w")` truncates in place,
so a reader that arrives mid-write parses a half-written file. The fix is
write-to-scratch-then-rename, plus a reader that treats every degraded input
as "no data yet" instead of raising.

Windows makes three details load-bearing, and all three are easy to get wrong:

  1. `os.replace` transiently raises PermissionError (WinError 5) when a
     concurrent reader holds the destination open - the share-lock window is
     usually well under 100 ms. On a polled file that contention is routine,
     not exceptional, so a bounded retry-with-backoff is the correct handling
     rather than a crash.
  2. The scratch name must be per-writer. A name derived from the destination
     alone gives every writer the same scratch file, and concurrent writers
     then interleave inside it and publish torn bytes.
  3. `Path.write_text` rewrites LF as CRLF, so the byte count on disk diverges
     from what the caller serialized. Everything here encodes to bytes first
     and writes bytes.

Stdlib only. No dependencies, no configuration, no global state.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("win32_atomic_io")

# os.replace can transiently raise PermissionError (WinError 5) on Windows
# when a concurrent reader holds the destination open (share-lock during the
# read; window is usually <100 ms). These files are polled by design, so the
# contention is routine. Brief retry-with-backoff clears it.
_REPLACE_RETRY_DELAYS_S = (0.025, 0.05, 0.2)


def _replace_with_retry(src: Path, dst: Path) -> None:
    """os.replace with bounded backoff (~275 ms worst case, then re-raise)."""
    for i in range(len(_REPLACE_RETRY_DELAYS_S) + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i >= len(_REPLACE_RETRY_DELAYS_S):
                raise
            time.sleep(_REPLACE_RETRY_DELAYS_S[i])


def _scratch_path(path: Path) -> Path:
    """A PER-WRITER scratch name, as a sibling of the destination.

    The obvious name - `path.with_suffix(path.suffix + ".tmp")` - is derived
    from the destination ALONE, so every writer of a given file opens the SAME
    scratch file. Two concurrent writers then interleave: B truncates and
    renames the scratch file while A is still filling it, and A's remaining
    bytes land in the published destination. That is measurable: two threads
    writing one file produced torn, unparseable reads - precisely the failure
    a tmp+rename writer is supposed to make impossible.

    Note the DETECTION is probabilistic even though the defect is not: the
    same two-thread experiment that produced a handful of torn reads across a
    few hundred writes may produce none on the next run. So this package tests
    the STRUCTURAL property instead - two calls yield distinct sibling names -
    and deliberately ships no contention run at all. A contention run that
    comes back clean is evidence of nothing, and a green one sitting in the
    suite would invite exactly that misreading.

    The pid is part of the name because the writers can be separate PROCESSES,
    which is exactly the case no in-process lock can serialize; the random
    suffix covers multiple writers inside one process. It stays a SIBLING of
    the destination because os.replace is only atomic within one filesystem -
    a scratch file in the system temp directory may be on another volume, and
    the rename then degrades to a copy that is not atomic at all.
    """
    return path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")


def _write_then_replace(path: Path, data: bytes) -> None:
    """Shared body for every public writer: scratch file -> rename, and NEVER
    leave the scratch file behind.

    The naive version re-raises an exhausted retry and orphans the scratch
    file. That is survivable while the scratch name is fixed (the next write
    reuses it); with a per-writer name it would be unbounded litter, so the
    cleanup and the per-writer name belong together. The handler catches
    BaseException, not Exception, so a KeyboardInterrupt mid-write does not
    leave a stray file either.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _scratch_path(path)
    try:
        tmp.write_bytes(data)
        _replace_with_retry(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    """Atomic JSON write via tmp + rename. Safe for files polled by other
    processes - readers see either the old content or the new, never a
    partial write. Creates parent directories on demand.

    Encodes to bytes here rather than handing the str to Path.write_text: on
    Windows write_text rewrites LF as CRLF, so an indented payload put more
    bytes on disk than the caller serialized.
    """
    body = json.dumps(payload, indent=indent, ensure_ascii=False)
    _write_then_replace(Path(path), body.encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic byte write via tmp + rename, with the same PermissionError retry.

    Use this whenever the BYTE COUNT matters - a size cap, a digest, or a
    reader that compares lengths. Callers hold the encoding decision; UTF-8 is
    the usual choice.
    """
    _write_then_replace(Path(path), data)


def atomic_write_text(path: Path, content: str) -> None:
    """Atomic text write via tmp + rename. Use this for any small trigger or
    sentinel file another process watches, so the watcher never sees a
    half-written value. A shell caller should mirror the same pattern: write
    the scratch file, then force-move it over the destination.

    Writes UTF-8 bytes verbatim - see atomic_write_json on why this is not
    Path.write_text."""
    _write_then_replace(Path(path), content.encode("utf-8"))


def read_json_dict(path: Path, default: Optional[dict] = None) -> dict:
    """Read JSON expected to be a dict. Returns a fresh DEEP copy of `default`
    (or {}) when the file is missing, unreadable, or stores something
    other than a dict.

    The copy is deep because a shallow dict(default) shares any nested mutable
    with the caller's own default object AND with every later call, so
    appending to a returned `{"log": []}` poisons every subsequent read. That
    is a latent trap rather than a loud one: it only bites once some caller
    passes a default with a nested container in it.

    One consequence worth knowing: deepcopy raises TypeError on a default
    holding an uncopyable value (a lock, a socket), where the old shallow copy
    silently succeeded. That is deliberate - this is a JSON module, such a
    default is a programming error, and surfacing it beats copying a live
    handle into what callers treat as inert data.
    """
    fallback = copy.deepcopy(dict(default)) if default else {}
    try:
        raw = Path(path).read_bytes().decode("utf-8")
    except OSError:
        # FileNotFoundError is an OSError; so is a directory or a locked file.
        return fallback
    except UnicodeDecodeError as exc:
        # This needs its own handler. Decoding raises UnicodeDecodeError (a
        # ValueError, NOT an OSError) on a non-UTF-8 file, so without this
        # clause a corrupt polled file crashes the caller instead of yielding
        # the default this docstring promises.
        _log.warning("win32_atomic_io: %s decode failed (not utf-8): %s", path, exc)
        return fallback
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.warning("win32_atomic_io: %s decode failed: %s", path, exc)
        return fallback
    if not isinstance(data, dict):
        _log.warning("win32_atomic_io: %s is not a dict (got %s)", path, type(data).__name__)
        return fallback
    return data
