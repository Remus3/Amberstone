"""gated_b29_window_parity.py - facts for the (was B29) QA6 + QA13 row in GATE 2.

The row reads "QA6 fullscreen-detect switch-to-Borderless hint + QA13 UIPI
elevation-parity detect final validation ... build headless first". Neither
feature exists, so there is nothing to validate yet (`build_gate` reports that).
What a game CAN settle before anyone builds them is the design question: which
signal tells this box's window state, and can UIPI bite here at all.

Four read-only sections:

1. ``build``: ``git grep`` of tracked source (tests and these gated tools
   excluded) for a reader or a hint. A hit is a CANDIDATE for a human to read,
   never proof the feature works; a git failure is UNKNOWN, never NOT_BUILT. An
   empty grep is a claim about these patterns only.
2. ``cfg``: ``[General] WindowMode`` from League's game.cfg, through the same
   path resolution and decoding as ``core.league_settings``. Labels are the
   operator-corrected encoding (docs/history_notes.md, RM-147 close): 0 =
   Fullscreen, 1 = Windowed, 2 = Borderless. The file says what League last
   saved; ``grade_window`` tests whether that predicts the live window.
3. ``window``: the game's own top-level window, from window-manager calls only
   (style bits, rect, monitor rect, foreground). ``SHQueryUserNotificationState``
   describes the FOREGROUND app, so a game that is not foreground is NO_RESULT.
4. ``elevation``: ``TokenElevation`` of this process, the shell and the rc-shell
   overlay, plus the UAC policy values. QA13's filed concern is the OVERLAY
   matching the game (docs/_archive/RC2_TODO_QA.md item 13). UIPI compares
   integrity levels and blocks lower from higher; TokenElevation is the proxy
   read here for "at High integrity".

A process handle opens ONLY for an image in ``OPENABLE_IMAGES``, on a pid
``tasklist`` just listed under that image. There is no pid argument and no denylist:
this tool never targets a League, Riot or Vanguard image, and a failed ``tasklist``
opens nothing. One gap remains: a listed pid recycled in the moment before the open
would get a limited-query handle. The game's own token stays unread on purpose, and
a non-elevated overlay grades GAME_TOKEN_NEEDED, not a pass.

READ-ONLY: no file, registry or window write, no process signal, no capture, no
network. It never ticks a row: every verdict here is pre-build design evidence.

USAGE
    python tools/gated_b29_window_parity.py

Prints JSON, without the game.cfg path. Exit 0 = sampled.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.league_settings import _cfg_path, _parse_ini, _read_cfg  # noqa: E402

GAME_IMAGE = "League of Legends.exe"
SHELL_IMAGE = "explorer.exe"
PACKAGED_OVERLAY_IMAGE = "Amberstone Shell.exe"  # rc-shell/package.json productName
DEV_OVERLAY_IMAGE = "electron.exe"  # shared with any other Electron app
OPENABLE_IMAGES = (SHELL_IMAGE, PACKAGED_OVERLAY_IMAGE, DEV_OVERLAY_IMAGE)
WINDOW_MODE_LABELS = {"0": "fullscreen", "1": "windowed", "2": "borderless"}

BUILD_PATHSPEC = ("*.py", "*.js", "*.mjs", "*.ps1",
                  ":(exclude)tests/*", ":(exclude)**/tests/**",
                  ":(exclude)**/test/**", ":(exclude)tools/gated_*")
BUILD_PATTERNS = {
    "qa6": r"\bWindowMode\b|\bwindow_mode\b|GWL_STYLE|GetWindowLong|WS_POPUP"
           r"|SHQueryUserNotificationState"
           r"|([Ss]witch to|[Gg]o|[Uu]se) [Bb]orderless",
    "qa13": r"TokenElevation|TOKEN_ELEVATION|IsUserAnAdmin|\bUIPI\b",
}

_GWL_STYLE = -16
_WS_POPUP = 0x80000000
_WS_CAPTION = 0x00C00000
_QUNS_D3D_FULLSCREEN = 3
_ERROR_INVALID_PARAMETER = 87  # OpenProcess on a pid that is not running
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION_CLASS = 20
_MONITOR_DEFAULTTONEAREST = 2


def _flags() -> int:
    """CREATE_NO_WINDOW on Windows; any other platform refuses creationflags."""
    return 0x08000000 if sys.platform == "win32" else 0


def build_gate(repo: Path, git: str = "git") -> dict:
    """{qa6, qa13}: NOT_BUILT, CANDIDATE (with file names) or UNKNOWN."""
    out: dict = {}
    for key, pattern in BUILD_PATTERNS.items():
        try:
            proc = subprocess.run(
                [git, "grep", "-l", "-E", pattern, "--", *BUILD_PATHSPEC],
                cwd=str(repo), capture_output=True, text=True, timeout=60,
                creationflags=_flags())
        except (OSError, subprocess.SubprocessError):
            out[key] = {"state": "UNKNOWN", "files": []}
            continue
        if proc.returncode == 0:
            out[key] = {"state": "CANDIDATE", "files": sorted(proc.stdout.splitlines())}
        elif proc.returncode == 1 and not proc.stderr.strip():
            out[key] = {"state": "NOT_BUILT", "files": []}
        else:
            out[key] = {"state": "UNKNOWN", "files": []}
    return out


def read_cfg(path=None) -> dict:
    """WindowMode facts from game.cfg, fail soft. Never carries the path."""
    facts = {"exists": False, "window_mode": None, "label": None,
             "width_present": False, "height_present": False, "mtime": None}
    p = _cfg_path(path)
    if p is None:
        return facts
    try:
        raw = _read_cfg(p)
        stamp = Path(p).stat().st_mtime
    except (OSError, ValueError):
        return facts
    general = _parse_ini(raw).get("General", {})
    mode = general.get("WindowMode")
    facts.update(
        exists=True, window_mode=mode, label=WINDOW_MODE_LABELS.get(mode or ""),
        width_present="Width" in general, height_present="Height" in general,
        mtime=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stamp)))
    return facts


def observed_state(window: dict) -> str:
    """exclusive / windowed / popup_full / unknown from one foreground sample.

    popup_full is deliberately not called borderless: a borderless window and a
    fullscreen one under flip-model optimizations can both show these bits.
    """
    if window.get("quns") == _QUNS_D3D_FULLSCREEN:
        return "exclusive"
    style = window.get("style")
    if style is None:
        return "unknown"
    if style & _WS_CAPTION == _WS_CAPTION and not window.get("covers_monitor"):
        return "windowed"
    if style & _WS_POPUP and window.get("covers_monitor"):
        return "popup_full"
    return "unknown"


def grade_window(cfg_mode, window) -> dict:
    """Is game.cfg WindowMode consistent with the live window? Stated before any game.

    NO_RESULT: no game window, not foreground, a missing or unlabelled cfg mode,
    or an unknown state. AGREE: mode 2 + popup_full, 1 + windowed, 0 + exclusive;
    for mode 2 that is consistency only, since popup_full cannot exclude a
    flip-model fullscreen. AMBIGUOUS: mode 0 + popup_full (flip-model fullscreen
    and a stale cfg look alike). DISAGREE: any other pairing.
    """
    if not window:
        return {"verdict": "NO_RESULT", "why": "no game window"}
    if not window.get("foreground"):
        return {"verdict": "NO_RESULT", "why": "game not foreground"}
    state = observed_state(window)
    want = {"0": "exclusive", "1": "windowed", "2": "popup_full"}.get(cfg_mode)
    if want is None:
        return {"verdict": "NO_RESULT", "why": "no labelled cfg WindowMode", "state": state}
    if state == "unknown":
        return {"verdict": "NO_RESULT", "why": "unknown window state", "state": state}
    if cfg_mode == "0" and state == "popup_full":
        return {"verdict": "AMBIGUOUS", "state": state}
    return {"verdict": "AGREE" if want == state else "DISAGREE", "state": state}


def grade_uipi(overlay: list) -> str:
    """OVERLAY_DOWN / NO_BLOCK_POSSIBLE / GAME_TOKEN_NEEDED / UNKNOWN.

    A single non-elevated overlay process is enough to need the game's token; an
    unreadable one makes the set UNKNOWN unless that already decided it.
    """
    if not overlay:
        return "OVERLAY_DOWN"
    states = [row.get("elevated") for row in overlay]
    if False in states:
        return "GAME_TOKEN_NEEDED"
    return "NO_BLOCK_POSSIBLE" if all(s is True for s in states) else "UNKNOWN"


def pids_of(image: str, run=subprocess.run) -> list[int]:
    """Pids by exact image name from ``tasklist``; this tool opens no handle here."""
    try:
        proc = run(["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {image}"],
                   capture_output=True, text=True, timeout=30, creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for row in csv.reader(io.StringIO(proc.stdout or "")):
        if len(row) >= 2 and row[0].lower() == image.lower() and row[1].isdigit():
            out.append(int(row[1]))
    return out


def _open_process(pid: int):
    """(kernel32, handle, error code) for a limited query handle on ``pid``."""
    import ctypes
    from ctypes import wintypes as w

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = w.HANDLE
    kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel32.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    return kernel32, handle, (0 if handle else ctypes.get_last_error())


def _read_elevation(pid: int) -> dict:
    """TokenElevation of ``pid``. Reach it through ``tokens_of_image`` or for self."""
    if sys.platform != "win32":
        return {"elevated": None, "reason": "not_windows"}
    import ctypes
    from ctypes import wintypes as w

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [
        w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel32, proc, code = _open_process(pid)
    if not proc:
        reason = "not_running" if code == _ERROR_INVALID_PARAMETER else f"open_error_{code}"
        return {"elevated": None, "reason": reason}
    token = w.HANDLE()
    try:
        if not advapi32.OpenProcessToken(proc, _TOKEN_QUERY, ctypes.byref(token)):
            return {"elevated": None, "reason": f"token_error_{ctypes.get_last_error()}"}
        try:
            value, size = w.DWORD(), w.DWORD()
            ok = advapi32.GetTokenInformation(
                token, _TOKEN_ELEVATION_CLASS, ctypes.byref(value),
                ctypes.sizeof(value), ctypes.byref(size))
            if not ok:
                return {"elevated": None, "reason": f"info_error_{ctypes.get_last_error()}"}
            return {"elevated": bool(value.value), "reason": None}
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(proc)


def _exe_path(pid: int) -> str:
    """Image path of an allowlisted pid, "" on any failure. Never printed."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes as w

    kernel32, proc, _code = _open_process(pid)
    if not proc:
        return ""
    kernel32.QueryFullProcessImageNameW.argtypes = [
        w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(len(buf))
        ok = kernel32.QueryFullProcessImageNameW(proc, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        kernel32.CloseHandle(proc)


def is_rc_shell_exe(path: str) -> bool:
    """True for an Electron binary under an ``rc-shell`` directory (a dev run keeps
    it in rc-shell/node_modules); another Electron app must not stand in for it."""
    return "rc-shell" in [part.lower() for part in re.split(r"[\\/]", path or "")]


def tokens_of_image(image: str, keep=None) -> list[dict]:
    """Elevation of every pid under ``image``; an unlisted image opens nothing."""
    if image not in OPENABLE_IMAGES:
        return [{"elevated": None, "reason": "refused_image"}]
    return [_read_elevation(pid) for pid in pids_of(image) if keep is None or keep(pid)]


def overlay_tokens() -> list[dict]:
    """Elevation of the rc-shell overlay, packaged or dev; [] when it is not up."""
    rows = tokens_of_image(PACKAGED_OVERLAY_IMAGE)
    rows += tokens_of_image(DEV_OVERLAY_IMAGE,
                            keep=lambda pid: is_rc_shell_exe(_exe_path(pid)))
    return rows


def pick_window(rows: list, pid: int):
    """(hwnd, box) of the largest visible window owned by ``pid``, else None.

    ``rows`` holds (owner pid, visible, hwnd, (left, top, right, bottom)).
    """
    best = None
    best_area = -1
    for owner, visible, hwnd, box in rows:
        if owner != pid or not visible:
            continue
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area > best_area:
            best, best_area = (hwnd, box), area
    return best


def game_window_facts(pid: int) -> dict | None:
    """The game's window facts, or None. Window-manager reads only: the process
    itself is not opened."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes as w

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32.GetForegroundWindow.restype = w.HWND
    user32.MonitorFromWindow.restype = w.HANDLE
    user32.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user32.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = w.LONG
    user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user32.IsWindowVisible.argtypes = [w.HWND]
    user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT),
                    ("rcWork", w.RECT), ("dwFlags", w.DWORD)]

    user32.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(MonitorInfo)]
    rows: list = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def visit(hwnd, _param):
        owner = w.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        rect = w.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            rows.append((owner.value, bool(user32.IsWindowVisible(hwnd)), hwnd,
                         (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(visit, 0)
    picked = pick_window(rows, pid)
    if picked is None:
        return None
    hwnd, box = picked
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    monitor = None
    handle = user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        mon = info.rcMonitor
        monitor = (mon.left, mon.top, mon.right, mon.bottom)
    quns = w.DWORD()
    quns_ok = shell32.SHQueryUserNotificationState(ctypes.byref(quns)) == 0
    return {
        "style": user32.GetWindowLongW(hwnd, _GWL_STYLE) & 0xFFFFFFFF,
        "rect": box, "monitor": monitor,
        "covers_monitor": monitor is not None and box == monitor,
        "foreground": user32.GetForegroundWindow() == hwnd,
        "quns": quns.value if quns_ok else None,
    }


def uac_policy() -> dict:
    """The three UAC policy values, read-only; an absent value is None."""
    out: dict = {"EnableLUA": None, "ConsentPromptBehaviorAdmin": None,
                 "FilterAdministratorToken": None}
    try:
        import winreg

        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System") as key:
            for name in out:
                try:
                    out[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return out


def collect() -> dict:
    """The whole read-only sample as one JSON-ready dict."""
    game_pids = pids_of(GAME_IMAGE)
    window = None
    for pid in game_pids:
        window = game_window_facts(pid) or window
    cfg = read_cfg()
    overlay = overlay_tokens()
    return {
        "build": build_gate(_REPO),
        "cfg": cfg,
        "game_running": bool(game_pids),
        "window": window,
        "window_grade": grade_window(cfg.get("window_mode"), window),
        "elevation": {
            "self": _read_elevation(os.getpid()),
            "shell": tokens_of_image(SHELL_IMAGE),
            "overlay": overlay,
            "uipi": grade_uipi(overlay),
            "uac": uac_policy(),
        },
        "note": "design evidence only; never ticks the row",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    print(json.dumps(collect(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
