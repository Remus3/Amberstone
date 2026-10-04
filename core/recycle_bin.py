# arch: checked send-to-Recycle-Bin (refuses a silent permanent delete) | section=core | frozen=no
"""core/recycle_bin.py - a CHECKED send-to-Recycle-Bin (RM-640, fleet rule 9).

WHY "CHECKED"
-------------
SHFileOperationW with FOF_ALLOWUNDO is the documented way to recycle a file,
but Windows PERMANENTLY deletes instead of recycling - with no error and, when
FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI are set, with no prompt - in
three cases: the file is larger than the volume's bin capacity, the volume's
bin is set to "remove files immediately" (NukeOnDelete), or the volume has no
bin at all (network shares, some removable media). A VOD is multi-GB, so the
first case is not hypothetical.

FOF_WANTNUKEWARNING would turn that into a prompt, but a prompt blocks an
unattended caller, so this module does not rely on it. Instead it:

  1. PREFLIGHT - refuses unless it can READ the volume's bin policy and that
     policy proves the bin will take the file: NukeOnDelete == 0, no
     NoRecycleFiles group policy, and size < MaxCapacity. A volume with no
     readable policy (no BitBucket key, a network path) is refused: no proof
     means no delete. Refusal happens BEFORE any shell call.
  2. SHELL CALL - SHFileOperationW(FO_DELETE, FOF_ALLOWUNDO | FOF_NOCONFIRMATION
     | FOF_SILENT | FOF_NOERRORUI).
  3. CONFIRM - the path must be gone AND the bin's own index must hold an
     $I record whose original path is ours AND whose deletion FILETIME is no
     earlier than the clock read taken just before the shell call (minus
     LANDED_SLACK_S), so an OLDER recycle of the same path cannot pass. If the file is gone but no record
     exists, the result is nuked=True and callers must halt (vod_retention
     does).

There was no recycle helper in the tree before this module (probe 2026-10-04:
grep for SHFileOperation / FOF_ALLOWUNDO / send2trash found none;
core/data_retention.py only states the rule in prose and its apply() unlinks).

Every OS touch goes through an API object so tests inject a fake and never
recycle a real file.
"""
from __future__ import annotations

import os
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

METHOD_RECYCLE_BIN = "recycle_bin"

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
SHFILEOP_FLAGS = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

# Seconds between 1601-01-01 (FILETIME epoch) and 1970-01-01.
_FILETIME_EPOCH_OFFSET_S = 11644473600
# Our own constant: tolerance between the time.time() taken just before the
# shell call and the FILETIME the shell stamps into $I. Clock reads are the
# same system clock; 2 s covers FILETIME vs time.time() rounding only.
LANDED_SLACK_S = 2.0

_BITBUCKET =r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"
_POLICIES = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"


@dataclass(frozen=True)
class RecycleResult:
    ok: bool
    path: str
    method: str
    detail: str
    nuked: bool = False


# -- $I index records ----------------------------------------------------


def parse_index_file(data: bytes) -> Optional[str]:
    """Original path from a $Recycle.Bin `$I` record, or None."""
    rec = parse_index_record(data)
    return rec[0] if rec else None


def parse_index_record(data: bytes) -> Optional[tuple]:
    """(original_path, deleted_at_epoch) from a `$I` record, or None.

    Layout (measured on Windows 10): int64 version, int64 size, int64
    deletion FILETIME, then v1 = fixed 520-byte UTF-16LE path; v2 = int32
    char count (including the NUL) followed by the UTF-16LE path.
    """
    if len(data) < 24:
        return None
    version, _size, filetime = struct.unpack_from("<qqq", data, 0)
    deleted_at = filetime / 1e7 - _FILETIME_EPOCH_OFFSET_S
    path = _index_path(data, version)
    return (path, deleted_at) if path else None


def _index_path(data: bytes, version: int) -> Optional[str]:
    try:
        if version == 1:
            raw = data[24:24 + 520]
        elif version == 2:
            if len(data) < 28:
                return None
            n = struct.unpack_from("<i", data, 24)[0]
            if n <= 0:
                return None
            raw = data[28:28 + 2 * n]
        else:
            return None
        text = raw.decode("utf-16-le", errors="strict")
    except (UnicodeDecodeError, struct.error):
        return None
    text = text.split("\0", 1)[0]
    return text or None


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def index_dirs_contain(dirs: Iterable[Path], original: str,
                       since: Optional[float] = None) -> bool:
    """True if a `$I` record for `original` exists - and, with `since`, was
    deleted no earlier than since - LANDED_SLACK_S. Without the time bound an
    OLDER recycle of the same path would read as "landed" after a nuke."""
    want = _norm(original)
    for d in dirs:
        try:
            entries = list(Path(d).iterdir())
        except OSError:
            continue
        for f in entries:
            if not f.name.startswith("$I"):
                continue
            try:
                rec = parse_index_record(f.read_bytes())
            except OSError:
                continue
            if rec is None or _norm(rec[0]) != want:
                continue
            if since is None or rec[1] >= since - LANDED_SLACK_S:
                return True
    return False


# -- the real Windows API ----------------------------------------------------


class WindowsShellApi:
    """Real OS layer. Only used on win32; tests never instantiate it."""

    def kind(self, path) -> Optional[str]:
        try:
            st = os.lstat(path)
        except OSError:
            return None
        attrs = getattr(st, "st_file_attributes", 0)
        if stat.S_ISLNK(st.st_mode) or attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return "link"
        if stat.S_ISDIR(st.st_mode):
            return "dir"
        if stat.S_ISREG(st.st_mode):
            return "file"
        return None

    def size(self, path) -> int:
        return os.lstat(path).st_size

    def exists(self, path) -> bool:
        return os.path.lexists(path)

    def _mount_point(self, path) -> Optional[str]:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.GetVolumePathNameW(
                str(Path(path).resolve()), buf, 1024):
            return None
        return buf.value

    def _volume_guid(self, mount: str) -> Optional[str]:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(
                mount, buf, 1024):
            return None
        name = buf.value  # \\?\Volume{guid}\
        i, j = name.find("{"), name.find("}")
        return name[i:j + 1] if 0 <= i < j else None

    def bin_policy(self, path):
        """(max_capacity_bytes, nuke_on_delete) or None when unprovable."""
        import winreg
        mount = self._mount_point(path)
        if not mount or mount.startswith("\\\\"):
            return None  # UNC / network: no bin
        guid = self._volume_guid(mount)
        if not guid:
            return None
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, _POLICIES) as k:
                    if int(winreg.QueryValueEx(k, "NoRecycleFiles")[0]) == 1:
                        return (0, True)
            except OSError:
                pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                _BITBUCKET + "\\" + guid) as k:
                cap_mb = int(winreg.QueryValueEx(k, "MaxCapacity")[0])
                nuke = int(winreg.QueryValueEx(k, "NukeOnDelete")[0])
        except OSError:
            return None
        return (cap_mb * 1024 * 1024, bool(nuke))

    def delete_allow_undo(self, path) -> int:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        # pFrom must be double-NUL terminated and absolute.
        src = str(Path(path).resolve()) + "\0\0"
        op = SHFILEOPSTRUCTW(None, FO_DELETE, src, None, SHFILEOP_FLAGS,
                             False, None, None)
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc == 0 and op.fAnyOperationsAborted:
            return -1
        return int(rc)

    def now(self) -> float:
        import time
        return time.time()

    def bin_contains(self, path, since: Optional[float] = None) -> bool:
        mount = self._mount_point(path)
        if not mount:
            return False
        root = Path(mount) / "$Recycle.Bin"
        try:
            dirs = [d for d in root.iterdir() if d.is_dir()]
        except OSError:
            return False
        return index_dirs_contain(dirs, str(Path(path).resolve()), since)


# -- the checked operation -----------------------------------------------------


def recycle_checked(path, *, api=None) -> RecycleResult:
    """Send ONE file to the Recycle Bin, or refuse. Never unlinks."""
    p = str(path)
    if api is None:
        if sys.platform != "win32":
            return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                                 "refused: Recycle Bin only exists on Windows")
        api = WindowsShellApi()

    kind = api.kind(p)
    if kind != "file":
        return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                             f"refused: not a regular file (kind={kind})")
    size = int(api.size(p))
    policy = api.bin_policy(p)
    if policy is None:
        return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                             "refused: bin policy unreadable for this volume;"
                             " cannot prove the file would not be nuked")
    cap, nuke = policy
    if nuke:
        return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                             "refused: the volume's bin deletes immediately")
    if cap is None or size >= cap:
        return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                             f"refused: too large for the bin ({size} >= {cap}"
                             " bytes); Windows would delete it permanently")

    since = float(api.now())
    rc = api.delete_allow_undo(p)
    if rc != 0:
        return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                             f"shell delete failed rc={rc:#x}"
                             if rc >= 0 else "shell delete aborted")
    if api.exists(p):
        return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                             "shell call returned 0 but the file is still present")
    if not api.bin_contains(p, since):
        return RecycleResult(False, p, METHOD_RECYCLE_BIN,
                             "file is gone but NOT found in the Recycle Bin"
                             " index - treat as a permanent delete",
                             nuked=True)
    return RecycleResult(True, p, METHOD_RECYCLE_BIN,
                         f"landed in the Recycle Bin ({size} bytes)")
