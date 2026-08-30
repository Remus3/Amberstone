"""
core/polled_json.py - single source of truth for "polled JSON file" semantics.

AUDIT 2026-04-28 (proposal 1.3): coaching_data.json, all
data/<mode>_coaching_data.json files, and ops/runtime/health.json are
written by RC and polled (mtime + read) by overlays, web_dashboard, and
the supervisor. Every site re-implements the same tmp+replace + read +
isinstance(dict) dance, with subtle variations. This module centralises:

  - atomic_write_json(path, payload): write-then-rename
  - read_json_dict(path, default): always returns a dict; corrupt/non-dict
    files yield the default
  - PolledJsonFile: thread-safe wrapper for read/write/write_field/update

Migration target: any new polled-JSON site should use these helpers; legacy
sites are migrated opportunistically as they are touched.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

_log = logging.getLogger("rc.polled_json")

# os.replace can transiently raise PermissionError (WinError 5) on Windows
# when a concurrent reader holds the destination open (share-lock during the
# read; window is usually <100 ms). These files are polled by design, so the
# contention is routine. Brief retry-with-backoff clears it - same pattern
# already applied to ops/rc_supervisor.atomic_write_json (2026-05-02);
# see reference_os_replace_winerror5.
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


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    """Atomic JSON write via tmp + rename. Safe for files polled by other
    processes - readers see either the old content or the new, never a
    partial write. Creates parent directories on demand."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=indent, ensure_ascii=False),
                   encoding="utf-8")
    _replace_with_retry(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic byte write via tmp + rename, with the same PermissionError retry.

    Use this instead of atomic_write_text whenever the BYTE COUNT matters - a
    size cap, a digest, or a reader that compares lengths. Path.write_text
    rewrites LF as CRLF on Windows and read_text hides it on the way back, so a
    text write silently puts more bytes on disk than the caller counted
    (reference_windows_write_text_crlf_byte_count). Callers hold the encoding
    decision; UTF-8 is the repo default.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    _replace_with_retry(tmp, path)


def atomic_write_text(path: Path, content: str) -> None:
    """Atomic text write via tmp + rename. AUDIT 2026-04-28 (proposal 4.3):
    use this for restart_trigger.txt writers so the supervisor never sees
    a half-written trigger. PowerShell callers should mirror the pattern:
    `Set-Content $tmp; Move-Item -Force $tmp restart_trigger.txt`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    _replace_with_retry(tmp, path)


def read_json_dict(path: Path, default: Optional[dict] = None) -> dict:
    """Read JSON expected to be a dict. Returns a fresh copy of `default`
    (or {}) when the file is missing, unreadable, or stores something
    other than a dict."""
    if default is None:
        default = {}
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return dict(default)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.warning("polled_json: %s decode failed: %s", path, exc)
        return dict(default)
    if not isinstance(data, dict):
        _log.warning("polled_json: %s is not a dict (got %s)", path, type(data).__name__)
        return dict(default)
    return data


class PolledJsonFile:
    """Thread-safe wrapper around a polled JSON file.

    The lock serializes read-modify-write inside this process; cross-process
    ordering still relies on tmp+rename atomicity. `default` is returned
    when the file is missing or corrupt; never None.

    Typical usage:
        pf = PolledJsonFile(Path("coaching_data.json"), default={"mode": "client"})
        cur = pf.read()
        pf.write_field("immediate", "All-In")
        pf.update(mode="aram", win_pct=42)
    """

    def __init__(self, path: Path, default: Optional[Mapping[str, Any]] = None) -> None:
        self.path = Path(path)
        self._default: dict = dict(default) if default else {}
        self._lock = threading.Lock()

    def read(self) -> dict:
        return read_json_dict(self.path, self._default)

    def write(self, payload: Mapping[str, Any]) -> None:
        with self._lock:
            atomic_write_json(self.path, dict(payload))

    def write_field(self, key: str, value: Any) -> dict:
        """Read-modify-write a single field. Returns the new full dict."""
        with self._lock:
            cur = read_json_dict(self.path, self._default)
            cur[key] = value
            atomic_write_json(self.path, cur)
            return cur

    def update(self, **fields: Any) -> dict:
        """Read-modify-write multiple fields at once. Returns new full dict."""
        with self._lock:
            cur = read_json_dict(self.path, self._default)
            cur.update(fields)
            atomic_write_json(self.path, cur)
            return cur
