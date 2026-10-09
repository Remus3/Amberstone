"""hotkey_listener.py - Legion-local global hotkeys for coach decisions.

Background process that watches Ctrl+Shift+1 / Ctrl+Shift+2 / Ctrl+Shift+A /
Ctrl+Shift+B / Ctrl+Shift+K via a WH_KEYBOARD_LL low-level keyboard hook.

Mechanism note: this used RegisterHotKey (the quiet registered-accelerator API)
specifically to AVOID a low-level hook, on the theory that hooks trip anti-cheat
watch patterns the way `pynput`/`keyboard` do. That theory cost us the in-game
case: RegisterHotKey global accelerators are SWALLOWED while League/Overlay Platform M
holds foreground focus, so Ctrl+Shift+A/B never reached the listener mid-game
(diagnosed 2026-06-27, panel_cycle.txt mtime frozen on every in-game press). A
WH_KEYBOARD_LL hook sits at the OS input queue ahead of the focused app, so it
DOES see the press in-game. Operator-directed switch 2026-06-27; the hook only
OBSERVES (always CallNextHookEx, never swallows the key) and Vanguard tolerates
global keyboard hooks from non-injected processes (Discord/OBS/AHK all use one).

When a hotkey fires:
  1. The most recently created pending decision is fetched from the
     local cache (refreshed every 2 s in a worker thread).
  2. Ctrl+Shift+1 -> POST the FIRST option in `options`.
     Ctrl+Shift+2 -> POST the SECOND option.
  3. Ctrl+Shift+A -> stamp the overlay ACTIVE-toggle signal file so rc-shell
     flips the overlay interactive. This combo is owned HERE, not by the
     Electron overlay: Electron's globalShortcut does NOT deliver while League
     holds foreground focus, and (as it turned out) neither does a Win32
     RegisterHotKey accelerator - only the WH_KEYBOARD_LL hook below does.
  4. If no pending decision (slots 1/2): silent no-op (no crash, no toast).
  5. Ctrl+Shift+K -> "mark this moment" (RM-638, directive X-38, external
     reference C): GET :2999 gamestats, append {game_id, game_time_s,
     wall_ts} to ops/runtime/moment_marks.jsonl (core/moment_marks.py). The
     post-game collector attaches the marks and PGR / Replay show them as
     "you flagged" pins. If :2999 is down (loading screen) the mark is dropped
     and logged. No OBS dependency.

This lets the player answer a coach decision OR move the overlay without
alt-tabbing out of League. The Edge dashboard updates from its own poll loop
within a second of the POST landing, so the banner clears whether the player
glances over or not.

Deploy:
  curl.exe -sk -o C:\\RC-Agent\\hotkey_listener.py \\
      https://127.0.0.1:8888/agent/hotkey_listener.py
  Start-Process -WindowStyle Hidden py -ArgumentList "C:\\RC-Agent\\hotkey_listener.py"

Or - preferred - let the logon boot script start it at logon (it's now
in the canonical agent list).

Stops on Ctrl+C (when run interactively) or when the process is killed
via taskkill /F. No state to flush - pending decisions live on Legion.
"""
from __future__ import annotations

import ctypes
import json
import logging
import queue
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Launched as ``pythonw tools/hotkey_listener.py`` (RC-HotkeyListener ONLOGON
# task), so sys.path[0] is tools/ and the repo's own packages are invisible.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.polled_json import atomic_write_text  # noqa: E402

# -- Config --------------------------------------------------------------------
# Loopback: RC and this listener share the box (1-PC, ADR-011). It was a
# hardcoded LAN address; host names and addresses are per-host config now.
LEGION_BASE   = "https://127.0.0.1:8888"
DECISIONS_URL = f"{LEGION_BASE}/api/decisions"
POLL_S        = 2.0
HTTP_TIMEOUT  = 3.0

# Overlay ACTIVE-toggle signal file. Ctrl+Shift+A (id 3) stamps this with the
# current epoch time on each press; rc-shell's main process polls it and flips
# the overlay ACTIVE (rc-shell/src/main.js startActiveToggleWatch). Hardcoded
# Legion-absolute, matching the LEGION_BASE convention above + the path
# rc-shell resolves (C:\Riot Commander\ops\runtime\).
TOGGLE_SIGNAL_FILE = r"C:\Riot Commander\ops\runtime\overlay_active_toggle.txt"

# Overlay panel-cycle signal file. Ctrl+Shift+B (id 4) stamps this with the
# current epoch on each press; rc-shell polls it and rotates the overlay panel
# set coach -> build -> threat (rc-shell/src/main.js startPanelCycleWatch). The
# in-game build panel was otherwise unreachable: its only switch (Electron
# Alt+Shift+C) is dead while League holds foreground focus, same as Ctrl+Shift+A.
PANEL_CYCLE_SIGNAL_FILE = r"C:\Riot Commander\ops\runtime\overlay_panel_cycle.txt"

def _setup_logging() -> logging.Logger:
    """Log to a durable file (always) plus the console when one exists.

    Under pythonw.exe (how the RC-HotkeyListener logon task launches us)
    sys.stderr is None, so a stderr-only logger silently drops every line and an
    unhandled exception's traceback vanishes - which is exactly why a boot-time
    failure here was historically invisible. The rotating file handler
    guarantees any future failure is diagnosable. The path is resolved from
    __file__, not cwd, so it is correct whatever working directory the scheduled
    task hands us (the task sets none)."""
    logger = logging.getLogger("rc.hotkey")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log_path = Path(__file__).resolve().parent.parent / "logs" / "hotkey_listener.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_path, maxBytes=512_000, backupCount=2, encoding="utf-8",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass  # never let logging setup crash the daemon
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


log = _setup_logging()

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# -- Decision cache ------------------------------------------------------------
class DecisionCache:
    """Thread-safe latest-pending cache. Worker refreshes; hotkey reads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[dict] = []
        self._last_fetch_ok = 0.0

    def topmost(self) -> dict | None:
        """Return the most recently CREATED pending decision (or None).
        Most recent = max created_at_unix; ties broken by id string."""
        with self._lock:
            if not self._pending:
                return None
            return max(self._pending, key=lambda d: (
                d.get("created_at_unix", 0), d.get("id", "")
            ))

    def refresh(self) -> None:
        try:
            req = urllib.request.Request(DECISIONS_URL)
            with urllib.request.urlopen(
                req, timeout=HTTP_TIMEOUT, context=_SSL_CTX
            ) as r:
                payload = json.loads(r.read())
        except (urllib.error.URLError, ValueError) as exc:
            log.debug("refresh: %s", exc)
            return
        items = payload.get("pending") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return
        with self._lock:
            self._pending = items
            self._last_fetch_ok = time.time()


def _refresh_loop(cache: DecisionCache, stop: threading.Event) -> None:
    while not stop.is_set():
        cache.refresh()
        stop.wait(POLL_S)


# -- POST a choice -------------------------------------------------------------
def post_choice(decision_id: str, choice: str) -> bool:
    url = f"{LEGION_BASE}/api/decisions/{decision_id}"
    body = json.dumps({"choice": choice, "note": "via hotkey"}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(
            req, timeout=HTTP_TIMEOUT, context=_SSL_CTX
        ) as r:
            ok = (200 <= r.status < 300)
            log.info("POST %s choice=%s -> %d", decision_id, choice, r.status)
            return ok
    except urllib.error.HTTPError as exc:
        log.warning("POST %s choice=%s -> HTTP %s", decision_id, choice, exc.code)
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("POST %s choice=%s -> %s", decision_id, choice, exc)
        return False


def signal_overlay_active_toggle() -> None:
    """Stamp the toggle-signal file (atomic tmp+replace) so rc-shell flips the
    overlay ACTIVE. Fire-and-forget: a write failure must never crash the loop."""
    try:
        atomic_write_text(Path(TOGGLE_SIGNAL_FILE), f"{time.time():.3f}")
        log.info("overlay ACTIVE toggle signaled")
    except Exception as exc:  # noqa: BLE001
        log.warning("overlay toggle signal failed: %s", exc)


def signal_overlay_panel_cycle() -> None:
    """Stamp the panel-cycle signal file (atomic tmp+replace) so rc-shell rotates
    the overlay panel set. Fire-and-forget: a write failure must never crash the
    loop."""
    try:
        atomic_write_text(Path(PANEL_CYCLE_SIGNAL_FILE), f"{time.time():.3f}")
        log.info("overlay panel-cycle signaled")
    except Exception as exc:  # noqa: BLE001
        log.warning("overlay panel-cycle signal failed: %s", exc)


# -- Mark this moment (RM-638) ---------------------------------------------------
# Short on purpose: a hung :2999 must not stall the dispatch worker behind it.
MARK_HTTP_TIMEOUT = 1.0
_GAMESTATS_PATH = "/liveclientdata/gamestats"
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_path() -> None:
    """The logon task runs this file as a script (sys.path[0] = tools/), so the
    repo root must be importable before the core helpers are."""
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _liveclient_base_url() -> str:
    _ensure_repo_on_path()
    from core.game_host import GAME_HOST  # noqa: PLC0415
    return f"https://{GAME_HOST}:2999"


def _default_game_id() -> str:
    """LCU gameId via the :8889 relay (core/live_session_recorder.py); '' when
    unknown, and then the collector attaches the mark by wall-time window."""
    _ensure_repo_on_path()
    from core.live_session_recorder import default_game_id_provider  # noqa: PLC0415
    return default_game_id_provider()


def handle_moment_mark(*, base_url: str | None = None, game_id_provider=None,
                       marks_file=None, now=time.time) -> dict | None:
    """Ctrl+Shift+K: read the game clock and append one mark. Returns the mark,
    or None when it was dropped (:2999 down / unusable body / write failed).
    Never raises - it runs on the dispatch worker."""
    try:
        wall_ts = now()
        url = (base_url or _liveclient_base_url()) + _GAMESTATS_PATH
        try:
            with urllib.request.urlopen(
                url, timeout=MARK_HTTP_TIMEOUT, context=_SSL_CTX
            ) as r:
                stats = json.loads(r.read())
        except (OSError, ValueError) as exc:
            log.info("moment mark dropped: :2999 gamestats unavailable (%s)", exc)
            return None
        try:
            gid = (game_id_provider or _default_game_id)()
        except Exception as exc:  # noqa: BLE001
            log.info("moment mark: game_id unknown (%s); recording null", exc)
            gid = None
        _ensure_repo_on_path()
        from core import moment_marks  # noqa: PLC0415
        mark = moment_marks.build_mark(stats, gid, wall_ts)
        if mark is None:
            log.info("moment mark dropped: gamestats carried no usable gameTime")
            return None
        moment_marks.append_mark(mark, marks_file)
        log.info("moment mark: game_id=%s game_time_s=%.1f",
                 mark["game_id"], mark["game_time_s"])
        try:
            moment_marks.request_replay_buffer_save(mark)   # RM-637 hook
        except Exception as exc:  # noqa: BLE001
            log.warning("moment mark: replay-buffer hook failed: %s", exc)
        return mark
    except Exception as exc:  # noqa: BLE001
        log.warning("moment mark dropped: %s", exc)
        return None


def handle_hotkey(cache: DecisionCache, slot: int) -> None:
    """slot=1 -> first option; slot=2 -> second option."""
    d = cache.topmost()
    if d is None:
        log.info("hotkey slot=%d but no pending decision", slot)
        return
    options = d.get("options") or []
    if not isinstance(options, list) or len(options) < slot:
        log.info("hotkey slot=%d but decision %s has %d options",
                 slot, d.get("id"), len(options))
        return
    choice = options[slot - 1]
    post_choice(d["id"], str(choice))


# -- Hotkey table + pure decoder -----------------------------------------------
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_VK_1        = 0x31
_VK_2        = 0x32
_VK_A        = 0x41
_VK_B        = 0x42
_VK_K        = 0x4B
_VK_CONTROL  = 0x11
_VK_SHIFT    = 0x10
_SLOT_OVERLAY_TOGGLE = 3
_SLOT_OVERLAY_PANEL_CYCLE = 4
_SLOT_MOMENT_MARK = 5

# Hotkeys we claim, as (slot, vk). Ctrl+Shift+1/2 = coach slots, A = overlay
# ACTIVE toggle, B = overlay panel-set cycle (coach/build/threat). (B not C:
# Ctrl+Shift+C is commonly bound by other apps - Discord / Overlay Platform M / browser
# DevTools - so B is the less-contended choice.) K = mark this moment
# (RM-638). Why K: every slot here is Ctrl+Shift+<key> and the hook OBSERVES,
# never swallows, so League sees the chord too. League's DEFAULT Ctrl chords
# are Ctrl+Q/W/E/R (level an ability), Ctrl+1..6 (emotes / mastery badge) and
# Ctrl+F (FPS readout); K is none of those in a normal match. NOT claimed:
# that League has no Ctrl+Shift binds - the Practice Tool binds many
# Ctrl+Shift / Shift chords, and Shift+K there spawns a drake, so a press in
# the Practice Tool may ALSO trigger that (League still sees the chord; the
# hook never swallows it). In a normal match K carries no default. M was
# rejected: Ctrl+Shift+M is a common chat-app mute toggle. RC carries no
# League keybind data to check against (no input.ini parser in the tree), so
# a player rebind onto Ctrl+Shift+K is the residual risk. This table
# is the source of truth; the decoder's vk->slot map is derived from it so the
# two cannot drift.
_HOTKEYS = (
    (1, _VK_1), (2, _VK_2),
    (_SLOT_OVERLAY_TOGGLE, _VK_A), (_SLOT_OVERLAY_PANEL_CYCLE, _VK_B),
    (_SLOT_MOMENT_MARK, _VK_K),
)
_VK_TO_SLOT = {vk: slot for slot, vk in _HOTKEYS}


class HotkeyDecoder:
    """Pure Ctrl+Shift+<trigger> decoder with press-edge debounce.

    The WH_KEYBOARD_LL hook delivers individual key events; this turns a keydown
    plus the live Ctrl/Shift state into the slot to fire, and suppresses the OS
    key-repeat that streams more WM_KEYDOWNs while a key is held - one fire per
    physical press, the NOREPEAT the old RegisterHotKey flag gave for free. No
    Win32 here, so it is unit-testable headlessly."""

    def __init__(self) -> None:
        self._fired: set[int] = set()

    def on_keydown(self, vk: int, ctrl: bool, shift: bool) -> int | None:
        slot = _VK_TO_SLOT.get(vk)
        if slot is None or not (ctrl and shift):
            return None
        if vk in self._fired:
            return None          # OS key-repeat while the key is still held
        self._fired.add(vk)
        return slot

    def on_keyup(self, vk: int) -> None:
        self._fired.discard(vk)


# -- WH_KEYBOARD_LL plumbing ---------------------------------------------------
# A low-level keyboard hook sees the press at the OS input queue ahead of the
# focused app, so it fires in-game where RegisterHotKey was swallowed. The hook
# proc MUST return fast (Windows silently drops a hook whose callback exceeds
# LowLevelHooksTimeout), so it only decodes + enqueues; the dispatch worker runs
# the slow handlers (post_choice does a ~3s HTTP call - never inline in the hook).
_WH_KEYBOARD_LL = 13
_HC_ACTION      = 0
_WM_KEYDOWN     = 0x0100
_WM_KEYUP       = 0x0101
_WM_SYSKEYDOWN  = 0x0104
_WM_SYSKEYUP    = 0x0105
_LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(
    _LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD,
]
_user32.CallNextHookEx.restype = _LRESULT
_user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
]
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

# Live singletons shared between the hook proc and the dispatch worker.
_decoder = HotkeyDecoder()
_dispatch_queue: "queue.Queue[int]" = queue.Queue()


def _modifiers_down() -> tuple[bool, bool]:
    """Live Ctrl / Shift state, read async at the instant a trigger key lands."""
    ctrl = bool(_user32.GetAsyncKeyState(_VK_CONTROL) & 0x8000)
    shift = bool(_user32.GetAsyncKeyState(_VK_SHIFT) & 0x8000)
    return ctrl, shift


def _ll_keyboard_proc(nCode, wParam, lParam):
    """WH_KEYBOARD_LL callback: decode Ctrl+Shift+<trigger>, enqueue, pass on.

    Stays cheap and ALWAYS chains CallNextHookEx so the keypress still reaches
    League (we observe, never swallow). Any error is logged, never raised - an
    exception escaping a ctypes callback would tear the hook down."""
    try:
        if nCode == _HC_ACTION:
            kb = _KBDLLHOOKSTRUCT.from_address(lParam)
            if wParam in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                ctrl, shift = _modifiers_down()
                slot = _decoder.on_keydown(kb.vkCode, ctrl, shift)
                if slot is not None:
                    _dispatch_queue.put_nowait(slot)
            elif wParam in (_WM_KEYUP, _WM_SYSKEYUP):
                _decoder.on_keyup(kb.vkCode)
    except Exception:  # noqa: BLE001 - a raise here would drop the hook
        log.exception("low-level hook proc error")
    return _user32.CallNextHookEx(None, nCode, wParam, lParam)


# Keep a module-level reference: a ctypes callback garbage-collected while still
# installed crashes the process the next time the OS invokes it.
_HOOK_PROC_REF = _HOOKPROC(_ll_keyboard_proc)


def _dispatch_one(cache: DecisionCache, slot: int) -> None:
    if slot == _SLOT_OVERLAY_TOGGLE:
        signal_overlay_active_toggle()
    elif slot == _SLOT_OVERLAY_PANEL_CYCLE:
        signal_overlay_panel_cycle()
    elif slot == _SLOT_MOMENT_MARK:
        handle_moment_mark()
    else:
        handle_hotkey(cache, slot)


def _dispatch_loop(cache: DecisionCache, stop: threading.Event) -> None:
    """Drain the slot queue off the hook thread, running the slow handlers
    (HTTP POST / signal-file write) where a stall is harmless."""
    while not stop.is_set():
        try:
            slot = _dispatch_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _dispatch_one(cache, slot)
        except Exception:  # noqa: BLE001
            log.exception("dispatch slot=%s crashed", slot)


def _install_hook() -> wintypes.HHOOK:
    hook = _user32.SetWindowsHookExW(
        _WH_KEYBOARD_LL, _HOOK_PROC_REF,
        _kernel32.GetModuleHandleW(None), 0,
    )
    if not hook:
        raise OSError(
            "SetWindowsHookExW(WH_KEYBOARD_LL) failed "
            f"(GetLastError={ctypes.get_last_error()})"
        )
    return hook


def message_loop() -> None:
    """Pump messages on the hook-owning thread. A WH_KEYBOARD_LL hook is invoked
    on the thread that installed it, and that thread MUST run a message loop or
    the callback never fires - so this loop is load-bearing even though no
    WM_HOTKEY arrives any more."""
    msg = wintypes.MSG()
    while True:
        rc = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if rc == 0:
            break               # WM_QUIT
        if rc == -1:
            log.error("GetMessageW failed (%d)", ctypes.get_last_error())
            break
        _user32.TranslateMessage(ctypes.byref(msg))
        _user32.DispatchMessageW(ctypes.byref(msg))


def main() -> int:
    log.info("hotkey_listener starting "
             "(Ctrl+Shift+1 / Ctrl+Shift+2 / Ctrl+Shift+A / Ctrl+Shift+B / "
             "Ctrl+Shift+K, "
             "WH_KEYBOARD_LL)")
    cache = DecisionCache()
    stop = threading.Event()
    worker = threading.Thread(
        target=_refresh_loop, args=(cache, stop),
        daemon=True, name="hotkey-refresh",
    )
    worker.start()
    dispatcher = threading.Thread(
        target=_dispatch_loop, args=(cache, stop),
        daemon=True, name="hotkey-dispatch",
    )
    dispatcher.start()

    try:
        hook = _install_hook()
    except OSError as exc:
        log.error("%s", exc)
        stop.set()
        return 2  # task RestartOnFailure will retry the whole process

    log.info("keyboard hook installed; entering message loop")
    try:
        message_loop()
    except KeyboardInterrupt:
        pass
    finally:
        _user32.UnhookWindowsHookEx(hook)
        stop.set()
        log.info("hotkey_listener shutting down")
    return 0


def _entrypoint() -> int:
    """Last-resort guard: under pythonw an unhandled exception's traceback is
    lost (stderr is None) and the process just exits 1 invisibly. Log it to the
    file first, then return 1 so the task's RestartOnFailure can recover."""
    try:
        return main()
    except Exception:  # noqa: BLE001
        log.exception("hotkey_listener crashed")
        return 1


if __name__ == "__main__":
    sys.exit(_entrypoint())
