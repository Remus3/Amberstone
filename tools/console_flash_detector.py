"""Event-driven console-window detector. Run under pythonw, join with the attributor.

WHY EVENT-DRIVEN AND NOT A POLL. A console flash on this box lives about 20-40
ms. A 250 ms EnumWindows poll came back CLEAN while the flash was real (measured
2026-08-01); polling had to drop to 8 ms to catch it, and at that cadence a
single ``Get-CimInstance`` lookup inside the loop - about 65 ms, measured
2026-09-14 - blinds the sampler for longer than a window exists, exactly when
one exists. So this detector does no lookup inside its hot path at all: it
subscribes to SetWinEventHook for EVENT_OBJECT_CREATE..EVENT_OBJECT_SHOW,
out-of-context, all processes, and STAMPS EVERY LINE AT RECEIPT BEFORE ANY
LOOKUP. The pid / class / image-name resolution happens after the stamp, so a
slow resolve can lose a detail but can never move a timestamp.

WHAT IT PROVES ABOUT ITSELF. Absence of events is only evidence if the detector
was alive, and on 2026-09-14 a 63-byte sampler log with no END was read as a
quiet machine. So this one writes START, a HEARTBEAT every 30 s carrying the
message-pump counter and the measured pumps per second, ``HOOK LOST`` if
SetWinEventHook returns 0 or the pump stalls between heartbeats, and END. The
attributor turns a heartbeat gap over 90 s into a DEAD-WINDOW span rather than
into silence.

EXPECT TWO EVENTS PER CONSOLE SPAWN, not one. Measured 2026-09-15: one
unflagged cmd.exe produced EVENT_OBJECT_CREATE against the conhost pid and
EVENT_OBJECT_SHOW against the console program's own pid, on the same hwnd,
about 17 ms apart. A 40 ms poll sees one of them. That is the same source at
higher resolution, not two sources - do not read the count as a flash rate.

The log is an APPEND STREAM, deliberately not an atomic whole-file write: a
capture that is killed mid-run must still carry everything it saw up to the
kill, and a session-launched capture dies with the session (measured, run 3 on
2026-09-14). Output lands under the gitignored ops/runtime/console_flash/
(.gitignore:178) and carries basenames only - never a command line, which would
publish the account home directory and neighbouring project names.

Usage:
  pythonw.exe tools/console_flash_detector.py --seconds 90
  python.exe  tools/console_flash_detector.py --seconds 90 --out capture.log
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "ops" / "runtime" / "console_flash"

EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
PM_REMOVE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

#: The two window classes a flashing console can wear on Windows 10/11: the
#: classic conhost window and the Windows Terminal hosting window.
CONSOLE_CLASSES = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")

HEARTBEAT_SECONDS = 30.0
PUMP_SLEEP_SECONDS = 0.005


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _Stream:
    """Append-only line writer. Flushed per line so a kill loses nothing."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._fh = path.open("a", encoding="ascii", errors="replace", newline="\n")

    def write(self, line: str) -> None:
        self._fh.write(line.rstrip("\n") + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class _Win32:
    """The handful of user32/kernel32 entry points this needs, typed."""

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self.user32.SetWinEventHook.restype = wintypes.HANDLE
        self.user32.SetWinEventHook.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ]
        self.user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        self.user32.GetClassNameW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]

    def class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
        return buf.value

    def pid_of(self, hwnd: int) -> int:
        pid = wintypes.DWORD(0)
        self.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)

    def image_basename(self, pid: int) -> str:
        if not pid:
            return "?"
        handle = self.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return "?"
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)):
                return "?"
            # BASENAME ONLY. The full image path names the account home
            # directory on this box, and a capture is a tracked-file hazard.
            return os.path.basename(buf.value) or "?"
        finally:
            self.kernel32.CloseHandle(handle)


_WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
) if sys.platform == "win32" else None


def run(seconds: float, out_path: Path) -> int:
    """Capture for `seconds`, writing the event stream to `out_path`."""
    if sys.platform != "win32":
        sys.stderr.write("console_flash_detector runs on Windows only\n")
        return 2

    stream = _Stream(out_path)
    api = _Win32()
    counters = {"events": 0, "pumps": 0}

    def _on_event(_hook, event, hwnd, id_object, _id_child, _thread, _ms):
        # STAMP FIRST. Everything below this line is a lookup that can be slow.
        stamp = _now()
        if id_object != OBJID_WINDOW or not hwnd:
            return
        handle = int(hwnd)
        try:
            cls = api.class_name(handle)
        except OSError:
            return
        if cls not in CONSOLE_CLASSES:
            return
        pid = api.pid_of(handle)
        exe = api.image_basename(pid)
        counters["events"] += 1
        stream.write(
            f"EVENT ts={stamp} event=0x{event:04x} hwnd=0x{handle:08x} pid={pid} exe={exe} cls={cls}")

    callback = _WINEVENTPROC(_on_event)
    hook = api.user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW, None,
        ctypes.cast(callback, ctypes.c_void_p), 0, 0,
        WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)

    stream.write(f"START ts={_now()} seconds={seconds:.0f} pid={os.getpid()} out={out_path.name}")
    if not hook:
        stream.write(f"HOOK LOST ts={_now()} reason=SetWinEventHook-returned-0")
        stream.write(f"END ts={_now()} events=0 pumps=0")
        stream.close()
        return 1

    msg = wintypes.MSG()
    started = time.monotonic()
    deadline = started + seconds
    next_beat = started + HEARTBEAT_SECONDS
    last_beat_at = started
    last_beat_pumps = 0
    try:
        while time.monotonic() < deadline:
            while api.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                api.user32.TranslateMessage(ctypes.byref(msg))
                api.user32.DispatchMessageW(ctypes.byref(msg))
            counters["pumps"] += 1
            time.sleep(PUMP_SLEEP_SECONDS)
            now = time.monotonic()
            if now >= next_beat:
                turned = counters["pumps"] - last_beat_pumps
                rate = turned / max(now - last_beat_at, 1e-6)
                stream.write(
                    "HEARTBEAT ts={} pumps={} pumps_per_second={:.1f} events={}".format(
                        _now(), counters["pumps"], rate, counters["events"]))
                if turned == 0:
                    stream.write(
                        f"HOOK LOST ts={_now()} reason=message-pump-stalled")
                last_beat_at = now
                last_beat_pumps = counters["pumps"]
                next_beat = now + HEARTBEAT_SECONDS
    except KeyboardInterrupt:
        stream.write(f"HOOK LOST ts={_now()} reason=interrupted")
    finally:
        api.user32.UnhookWinEvent(hook)
        stream.write("END ts={} events={} pumps={}".format(
            _now(), counters["events"], counters["pumps"]))
        stream.close()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="log every console window that appears, stamped at receipt")
    parser.add_argument("--seconds", type=float, default=90.0,
                        help="capture duration (default 90)")
    parser.add_argument("--out", type=Path, default=None,
                        help="capture log path (default ops/runtime/console_flash/)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    out = args.out or (DEFAULT_DIR / "console_flash_detector.log")
    return run(args.seconds, out)


if __name__ == "__main__":
    raise SystemExit(main())
