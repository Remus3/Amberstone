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

import copy
import json
import logging
import os
import secrets
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


def _scratch_path(path: Path) -> Path:
    """A PER-WRITER scratch name, as a sibling of the destination.

    LANE 8 CYCLE 24 (W5): this used to be `path.with_suffix(path.suffix +
    ".tmp")` - derived from the destination ALONE, so every writer of a given
    file opened the SAME scratch file. Two concurrent writers then interleave:
    B truncates and renames the scratch file while A is still filling it, and
    A's remaining bytes land in the published destination. Measured on win32
    with two threads writing one file, 240 writes: 5 reads came back torn and
    unparseable - precisely the failure this module's docstring promises cannot
    happen. Note the DETECTION is probabilistic even though the defect is not:
    the same experiment run again may see zero torn reads, which is why the
    guards in tests/test_polled_json_lane8_cycle24.py are the STRUCTURAL ones
    (distinct scratch names) and the contention tests there are labelled smoke
    tests rather than guards.

    Reachability is not hypothetical: data/force_scan.json has FOUR
    independent writers - core/hotkeys.py:103, dashboard/_writers.py:68,
    coaches/arena_coach.py:481, and tools/lcu_agent.py:1372, which runs in its
    OWN PROCESS (the RC-LCUAgent ONLOGON task) and is the motivating case for
    the pid below. coaching_data.json has at least THREE: app/__init__.py:253
    and :272, dashboard/_writers.py:63 (set_pregame), and
    coach_integration/_coach.py:713, which still hand-rolls
    `data_file.with_suffix(".tmp")` and is NOT converted - see RM-261.

    The pid is part of the name because the writers can be separate processes
    (RC-HotkeyListener and RC-LCUAgent are their own ONLOGON tasks), which is
    exactly the case no in-process lock can serialize. It stays a SIBLING of
    the destination because os.replace is only atomic within one filesystem.

    coaches/sr_user_builds.py:513 already carries this same fix, applied to a
    single consumer in cycle 22 while the contract module kept the defect -
    feedback_resolver_fix_is_not_a_consumer_fix.
    """
    return path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")


def _write_then_replace(path: Path, data: bytes) -> None:
    """Shared body for every public writer: scratch file -> rename, and NEVER
    leave the scratch file behind.

    LANE 8 CYCLE 24 (W4): the pre-fix writers re-raised an exhausted retry and
    orphaned the scratch file. That was survivable while the name was fixed
    (the next write reused it); with a per-writer name it would be unbounded
    litter, so the two fixes ship together.
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
    bytes on disk than the caller serialized
    (reference_windows_write_text_crlf_byte_count).
    """
    body = json.dumps(payload, indent=indent, ensure_ascii=False)
    _write_then_replace(Path(path), body.encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic byte write via tmp + rename, with the same PermissionError retry.

    Use this whenever the BYTE COUNT matters - a size cap, a digest, or a
    reader that compares lengths. Callers hold the encoding decision; UTF-8 is
    the repo default.
    """
    _write_then_replace(Path(path), data)


def atomic_write_text(path: Path, content: str) -> None:
    """Atomic text write via tmp + rename. AUDIT 2026-04-28 (proposal 4.3):
    use this for restart_trigger.txt writers so the supervisor never sees
    a half-written trigger. PowerShell callers should mirror the pattern:
    `Set-Content $tmp; Move-Item -Force $tmp restart_trigger.txt`.

    Writes UTF-8 bytes verbatim - see atomic_write_json on why this is not
    Path.write_text."""
    _write_then_replace(Path(path), content.encode("utf-8"))


def read_json_dict(path: Path, default: Optional[dict] = None) -> dict:
    """Read JSON expected to be a dict. Returns a fresh DEEP copy of `default`
    (or {}) when the file is missing, unreadable, or stores something
    other than a dict.

    LANE 8 CYCLE 24 (W2): the copy is deep because a shallow dict(default)
    shares any nested mutable with the caller's own default object AND with
    every later call, so appending to a returned `{"log": []}` poisons every
    subsequent read. SEVERITY, stated honestly: this was demonstrated with a
    probe, NOT observed in production - every current caller passes `{}` or a
    freshly-built dict, so the exposure is latent. It is fixed because this
    module is the contract every new polled-JSON site is pointed at.

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
        # LANE 8 CYCLE 24 (W1): this used to escape. read_text raises
        # UnicodeDecodeError (a ValueError, NOT an OSError) on a non-UTF-8
        # file, so a corrupt polled file crashed the caller instead of
        # yielding the default this docstring promises. Three downstream sites
        # had already widened their own handlers to absorb it rather than
        # fixing it here - core/cost_tracker.py:490 and
        # coaches/_base_coach.py:502 / :539 all name it in prose.
        _log.warning("polled_json: %s decode failed (not utf-8): %s", path, exc)
        return fallback
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.warning("polled_json: %s decode failed: %s", path, exc)
        return fallback
    if not isinstance(data, dict):
        _log.warning("polled_json: %s is not a dict (got %s)", path, type(data).__name__)
        return fallback
    return data


class PolledJsonFile:
    """Thread-safe wrapper around a polled JSON file.

    The lock serializes read-modify-write between users of ONE INSTANCE;
    cross-process ordering still relies on tmp+rename atomicity. Two instances
    built for the same path do NOT serialize against each other - the lock is
    per-instance, not per-path - so share the instance rather than constructing
    a second one. `default` is returned when the file is missing or corrupt;
    never None, and it is a deep copy (see read_json_dict).

    LANE 8 CYCLE 24 - REACHABILITY: this class has ZERO production
    instantiations. Measured by grep over every tracked `.py`: outside
    `tests/test_polled_json_lane8_cycle24.py` nothing constructs it, so the
    module's advertised wrapper is currently unadopted while the three
    module-level helpers carry all real traffic. It is NOT deleted, because it
    is the documented migration target above rather than accidental dead code
    (RM-264 holds the adopt-or-remove decision). Treat the per-instance lock
    caveat as latent, not live.

    Typical usage:
        pf = PolledJsonFile(Path("coaching_data.json"), default={"mode": "client"})
        cur = pf.read()
        pf.write_field("immediate", "All-In")
        pf.update(mode="aram", win_pct=42)
    """

    def __init__(self, path: Path, default: Optional[Mapping[str, Any]] = None) -> None:
        self.path = Path(path)
        # LANE 8 CYCLE 24 (W3): deep, so the instance does not alias a nested
        # mutable inside the caller's default (and read() cannot hand it out).
        self._default: dict = copy.deepcopy(dict(default)) if default else {}
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
