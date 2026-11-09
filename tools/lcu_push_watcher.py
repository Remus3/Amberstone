"""LCU push watcher - auto-validate gated item A1 while the operator plays.

A1 (docs/LIVE_GAME_GATED_SYNC.md gated item A1 / LEDGER item 779): after a mid-session
League restart, confirm the LCU rune push STILL fires on the FIRST champ-select
enter. The 2026-07-04 regression was: NO push after a restart.

This watcher tails the current-day log, tracks the last-seen LCU port, marks the
FIRST 'champ select entered' AFTER a restart as the A1 test case, and within a
bounded window decides PASS (the push fired) / FAIL (A1 regression reproduced) /
PENDING. It fires ONE Windows toast + writes a compact verdict file. It is
READ-ONLY: it never imports or calls any LCU connect/push/write path, never
touches game/LCU state, and NEVER flips A1 - it only tells the operator whether
the push survived the restart.

Run (background):   python tools/lcu_push_watcher.py
Abort:              drop ops/runtime/LCU_PUSH_WATCHER_STOP   (or Ctrl-C)

Log anchors (matched on the MESSAGE text, never on a file:line; the producing
function is named so a rename is greppable, and
tests/test_lcu_push_watcher.py::test_log_anchor_is_still_emitted_and_matched
fails when a producer stops logging one):
  lcu/lcu_client.py LcuClient.connect
      'LCU connected: port %d (from %s)'
      'LCU lockfile not found - client may not be running'
  lcu/lcu_client.py LcuClient._refresh_conn_if_changed
      'LCU reconnected: port %d (lockfile rotated, from %s)'
  lcu/lcu_rune_writer.py RuneWriter._poll
      'RuneWriter: champ select ended - re-armed for next pick'
      'RuneWriter: champ select entered'
      'RuneWriter: champion=%s mode=%s - applying runes'  (push FIRED)
      'RuneWriter: rune write failed for %s/%s'           (FAIL)
  lcu/lcu_rune_writer.py RuneWriter._write_page
      'RuneWriter: wrote [%s] id=%s  perks=%s'            (page-write SUCCESS)
      'RuneWriter: gave up after %d attempts for [%s]: %s' (FAIL)

SCOPE = the RUNE push only. A1 covers the rune push, so the watcher keys on it:
  * The SPELL push (lcu_pregame.set_summoner_spells, inherited by LcuClient)
    DOES log a pass / fail pair - info 'set_summoner_spells: %d + %d' on a
    PATCH that succeeded, warning 'set_summoner_spells: failed %d + %d' - but
    it also logs 'refused' and a debug 'idempotent skip', and nothing here
    ties it to a restart, so it is not an anchor. The local-preference saves
    (lcu_rune_writer.save_spell_pref and save_champ_spell_pref) and the
    manual-spell-change info (RuneWriter._sync_spells) are not push signals.
  * There is NO champ-select ITEM/loadout push; the only item log line is the
    post-game item-event capture (lcu_postgame_collector "postgame: saved %d
    item events").
So the A1 verdict is keyed on the rune push, which is exactly what A1 covers.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from collections.abc import Iterable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import operator_notify  # noqa: E402 - needs the repo root on sys.path
from core.polled_json import atomic_write_text  # noqa: E402 - same

_LOG_DIR = _ROOT / "logs"
_RUNTIME = _ROOT / "ops" / "runtime"
_STOP = _RUNTIME / "LCU_PUSH_WATCHER_STOP"
_VERDICT_MD = _RUNTIME / "lcu_push_verdict.md"
_VERDICT_JSONL = _RUNTIME / "lcu_push_verdict.jsonl"
_STATE_URL = "https://127.0.0.1:8888/api/state"
_POLL_S = 2.0
_WINDOW_TIMEOUT_S = 20.0  # wall-clock: a restart-preceded enter with no push -> FAIL

# --- log-line anchors (substring/regex over the message tail) -----------------
_RE_CONNECT = re.compile(r"LCU connected: port (\d+)")
_RE_RECONNECT_ROTATED = re.compile(r"LCU reconnected: port (\d+) \(lockfile rotated")
_RE_LOCKFILE_GAP = re.compile(r"LCU lockfile not found")
_RE_CS_ENTER = re.compile(r"RuneWriter: champ select entered")
_RE_CS_END = re.compile(r"RuneWriter: champ select ended - re-armed")
_RE_APPLYING = re.compile(r"RuneWriter: champion=(\S+) mode=(\S+) - applying runes")
_RE_WROTE = re.compile(r"RuneWriter: wrote \[")
_RE_FAIL = re.compile(r"RuneWriter: rune write failed for (\S+)/(\S+)")
_RE_GAVEUP = re.compile(r"RuneWriter: gave up after (\d+) attempts")


# =============================================================================
# PURE CORE - no I/O, no toast, no network. Fully unit-tested.
# =============================================================================
def _finalize(window: dict, verdicts: list, close: str) -> None:
    """Decide the A1 verdict for a closed test-case window and append it.

    failure line anywhere in the window            -> FAIL
    push fired ('applying runes') / page written   -> PASS
    champ select ended (or reopened) with no push  -> FAIL  (A1 regression)
    end-of-input with nothing yet                  -> PENDING (live: timeout -> FAIL)
    """
    if window["failed"]:
        verdict = "FAIL"
    elif window["applied"] or window["wrote"]:
        verdict = "PASS"
    elif close in ("cs_end", "reopened"):
        verdict = "FAIL"
    else:  # eof - inconclusive within the provided lines
        verdict = "PENDING"
    verdicts.append({
        "verdict": verdict,
        "restart_reason": window["reason"],
        "port_before": window["port_before"],
        "port_after": window["port_after"],
        "champion": window["champion"],
        "mode": window["mode"],
        "matched": window["matched"],
    })


class A1Classifier:
    """Incremental A1 classifier: feed one log line at a time (PURE, no I/O).

    A restart = a connect on a DIFFERENT port than last seen, OR a 'lockfile
    rotated' reconnect, OR a 'lockfile not found' gap followed by any connect.
    The FIRST 'champ select entered' after a restart is the A1 test case; a
    champ-select with no preceding restart is NOT a test case (stays quiet).

    S144-T-705: the live loop used to keep EVERY line read since start and
    re-run the whole classification over that buffer on every 2 s poll -
    memory and CPU without bound for a watcher meant to run for days. State is
    now O(1) between lines (the open window's matched lines aside), and each
    line is classified exactly once.
    """

    def __init__(self) -> None:
        self._last_port: int | None = None
        self._gap_pending = False
        self._restart: dict | None = None  # armed restart, not yet consumed by a CS-enter
        self._window: dict | None = None   # currently-open A1 test-case window
        self.window_seq = 0                # bumps each time a window opens

    def has_open_window(self) -> bool:
        return self._window is not None

    def _close(self, close: str) -> list[dict]:
        out: list[dict] = []
        if self._window is not None:
            _finalize(self._window, out, close=close)
            self._window = None
        return out

    def flush(self) -> list[dict]:
        """End of input: the open window (if any) as a PENDING record, closed."""
        return self._close("eof")

    def expire(self) -> list[dict]:
        """Live window timeout: close the open window as FAIL (timeout=True).

        A push logged after this belongs to a closed window and is ignored."""
        out = self._close("eof")
        for rec in out:
            if rec["verdict"] == "PENDING":
                rec["verdict"] = "FAIL"
                rec["timeout"] = True
        return out

    def feed(self, raw: str) -> list[dict]:
        """Classify one line; return the records it finalized (usually none)."""
        line = raw.rstrip("\r\n")

        # --- restart signals ---
        m = _RE_RECONNECT_ROTATED.search(line)
        if m:
            port_after = int(m.group(1))
            self._restart = {"reason": "lockfile_rotated",
                             "port_before": self._last_port, "port_after": port_after}
            self._last_port = port_after
            self._gap_pending = False
            return []
        m = _RE_CONNECT.search(line)
        if m:
            port_after = int(m.group(1))
            if self._gap_pending:
                self._restart = {"reason": "lockfile_gap",
                                 "port_before": self._last_port, "port_after": port_after}
            elif self._last_port is not None and port_after != self._last_port:
                self._restart = {"reason": "port_change",
                                 "port_before": self._last_port, "port_after": port_after}
            # else: first connect (initial arm) or same-port RC reconnect -> not a restart
            self._last_port = port_after
            self._gap_pending = False
            return []
        if _RE_LOCKFILE_GAP.search(line):
            self._gap_pending = True
            return []

        # --- champ select enter (opens a test-case window IF a restart is armed) ---
        if _RE_CS_ENTER.search(line):
            out = self._close("reopened")
            if self._restart is not None:
                self._window = {**self._restart, "champion": None, "mode": None,
                                "applied": False, "wrote": False, "failed": False,
                                "matched": [line]}
                self._restart = None  # consume it - only the FIRST enter after a restart counts
                self.window_seq += 1
            return out

        # --- everything below only matters inside an open window ---
        window = self._window
        if window is None:
            return []
        m = _RE_APPLYING.search(line)
        if m:
            window["applied"] = True
            window["champion"] = m.group(1)
            window["mode"] = m.group(2)
            window["matched"].append(line)
            return []
        if _RE_WROTE.search(line):
            window["wrote"] = True
            window["matched"].append(line)
            return []
        m = _RE_FAIL.search(line)
        if m:
            window["failed"] = True
            if not window["champion"]:
                window["champion"] = m.group(1)
                window["mode"] = m.group(2)
            window["matched"].append(line)
            return self._close("failure")
        if _RE_GAVEUP.search(line):
            window["failed"] = True
            window["matched"].append(line)
            return self._close("failure")
        if _RE_CS_END.search(line):
            window["matched"].append(line)
            return self._close("cs_end")
        return []


def classify_events(lines: Iterable[str]) -> list[dict]:
    """Classify a stream of log lines into A1 verdict records (PURE).

    See A1Classifier for the restart / test-case rules. Returns one record per
    test case, in order; a window still open at end of input is PENDING.
    Record keys: verdict (PASS/FAIL/PENDING), restart_reason, port_before,
    port_after, champion, mode, matched (the log lines that drove the verdict).
    """
    clf = A1Classifier()
    verdicts: list[dict] = []
    for raw in lines:
        verdicts.extend(clf.feed(raw))
    verdicts.extend(clf.flush())
    return verdicts


def render_verdict_md(record: dict) -> str:
    """Render one verdict record as the overwrite-in-place markdown file (PURE)."""
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "PENDING": "[PENDING]"}.get(
        record.get("verdict", "?"), "[?]")
    lines = [
        f"# LCU push watcher - gated item A1 verdict: {icon} {record.get('verdict')}",
        "",
        f"- when: {record.get('timestamp', '-')}",
        f"- restart: {record.get('restart_reason', '-')} "
        f"(port {record.get('port_before')} -> {record.get('port_after')})",
        f"- champion: {record.get('champion') or '-'}   mode: {record.get('mode') or '-'}",
        "",
        "A1 = after a mid-session League restart, the rune push must fire on the",
        "FIRST champ-select enter (2026-07-04 regression: no push after restart).",
        "This watcher is READ-ONLY and never flips A1.",
        "",
        "## matched log lines",
    ]
    for ln in record.get("matched", []):
        lines.append(f"- {ln}")
    if record.get("timeout"):
        lines.append("")
        lines.append(f"(FAIL by {int(_WINDOW_TIMEOUT_S)}s window timeout - push never fired)")
    return "\n".join(lines) + "\n"


# =============================================================================
# THIN WRAPPERS - side-effecting (tail / toast / network / disk). Tested with
# tmp files and stubs in tests/test_lcu_push_watcher_true_audit_s144t705.py.
# =============================================================================
def _say(msg: str) -> None:
    """Console line that never raises on an unencodable character.

    S144-T-705: a cp1252 console raised UnicodeEncodeError on a non-ASCII notify
    detail, and the print sat BEFORE the verdict-file writes, so both files
    were skipped (the LEDGER 1564 residual). Retry ASCII-escaped instead."""
    try:
        print(msg)
    except (UnicodeEncodeError, ValueError, OSError):
        try:
            print(msg.encode("ascii", "backslashreplace").decode("ascii"))
        except (UnicodeEncodeError, ValueError, OSError):
            pass  # no usable console (closed stream); the files carry the verdict


def _fetch_state() -> dict | None:
    """Best-effort read of /api/state for champ/mode context (READ-ONLY).

    None when the dashboard is down or mid-restart, or the body is not a JSON
    object. S144-T-705: a list body used to crash _emit (list.get), and the
    old bare `except Exception` also hid programming errors - only network,
    HTTP and decode failures are expected here."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(_STATE_URL, timeout=5, context=ctx) as r:
            doc = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return doc if isinstance(doc, dict) else None


def _str_or_none(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _emit(record: dict) -> None:
    """Toast + append jsonl + overwrite md for one finalized verdict record."""
    record.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S"))
    if not record.get("champion") or not record.get("mode"):
        state = _fetch_state()  # best-effort context fill (read-only)
        if state:
            # S144-T-705: this was record.setdefault("mode", ...), a no-op -
            # _finalize always sets the key (to None), so the mode was never
            # filled. Only a non-empty string is taken from the payload.
            if not record.get("mode"):
                record["mode"] = _str_or_none(state.get("mode_key"))
            coach = state.get("coach")
            if not record.get("champion") and isinstance(coach, dict):
                record["champion"] = _str_or_none(coach.get("champion"))

    v = record["verdict"]
    champ = record.get("champion") or "?"
    title = f"RC A1 {v}: rune push after restart ({champ})"
    if v == "PASS":
        body = (f"Push FIRED on first champ-select after restart "
                f"(port {record.get('port_before')}->{record.get('port_after')}). A1 holds.")
    elif v == "FAIL":
        body = ("NO rune push on first champ-select after restart - A1 regression "
                "reproduced. Check RuneWriter LCU view.")
    else:
        body = "Restart + champ-select seen; awaiting push."
    # Y-02: one notify path (escaped toast, jsonl floor); never raises.
    _ok, detail = operator_notify.notify(title, body, tags=("lcu-push", v))

    # The verdict files land BEFORE any console output, each on its own, so a
    # failure of one never costs the other. The markdown is overwritten
    # atomically (S144-T-705: it was an in-place write_text, so a reader could
    # see it torn); the jsonl is an append-only history.
    try:
        with _VERDICT_JSONL.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        _say(f"[lcu-push-watcher] verdict jsonl write failed: {exc}")
    try:
        atomic_write_text(_VERDICT_MD, render_verdict_md(record))
    except OSError as exc:
        _say(f"[lcu-push-watcher] verdict md write failed: {exc}")
    _say(f"[lcu-push-watcher] notify: {detail}")
    _say(f"[lcu-push-watcher] {v}: champ={champ} "
         f"restart={record.get('restart_reason')} "
         f"port {record.get('port_before')}->{record.get('port_after')}")


def _log_path_for_today() -> Path:
    return _LOG_DIR / f"{time.strftime('%Y-%m-%d')}.log"


def _win_open_shared_delete(path: Path):
    """Windows: open ``path`` for reading with FILE_SHARE_DELETE so another
    process can rename/delete it while we hold it open. RC's rotating log handler
    (core/log_setup.py DailyRotatingFileHandler, 3 MB size rotation) renames the
    live day-log mid-day; a plain open("r") lacks FILE_SHARE_DELETE so that rename
    fails with WinError 32. Returns a text-mode file object."""
    import ctypes  # noqa: PLC0415 - Windows-only, imported lazily
    from ctypes import wintypes  # noqa: PLC0415
    import msvcrt  # noqa: PLC0415 - Windows-only
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ, FILE_SHARE_WRITE, FILE_SHARE_DELETE = 0x1, 0x2, 0x4
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    invalid = ctypes.c_void_p(-1).value
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.restype = wintypes.HANDLE
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                       wintypes.HANDLE]
    h = create(str(path), GENERIC_READ,
               FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
               None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if not h or h == invalid:
        raise OSError(ctypes.get_last_error(), f"CreateFileW failed: {path}")
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY)  # the fd owns the handle now
    except OSError:
        kernel32.CloseHandle(wintypes.HANDLE(h))    # no fd exists to own it
        raise
    return os.fdopen(fd, "r", encoding="utf-8", errors="replace")


def _open_shared(path: Path, seek_end: bool):
    """Open the day-log for reading WITHOUT blocking RC's log rotation.

    Windows: via CreateFileW with FILE_SHARE_DELETE so the rotating handler can
    still rename the live log while we tail it (else WinError 32 freezes RC's
    logging - the 'share-lock' this watcher hit before re-arming). POSIX allows
    rename/unlink of an open file by default, so a plain open is share-safe there.
    Returns None on any open error (the poll loop retries), never raises. A
    handle opened but not positioned (the seek raised) is closed here, so a
    refused return never leaves it for the garbage collector."""
    handle = None
    try:
        if sys.platform == "win32":
            handle = _win_open_shared_delete(path)
        else:
            handle = path.open("r", encoding="utf-8", errors="replace")
        if seek_end:
            handle.seek(0, 2)  # SEEK_END - ignore pre-existing history
        return handle
    except OSError:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        return None


def _close_quietly(handle) -> None:
    try:
        handle.close()
    except OSError:
        pass


class DayLogTailer:
    """Follow RC's day-log across size rotations and midnight rollovers.

    ``poll()`` returns the complete lines written since the last poll. The
    first open after arm starts at the END (pre-existing history is ignored);
    every later open - a file created after arm, the new day's file, the fresh
    file after a size rotation - starts at its beginning, because all of its
    content is new.

    S144-T-705, three defects of the old inline loop:
      * size rotation: core/log_setup.py DailyRotatingFileHandler renames the
        live YYYY-MM-DD.log to .log.1 at 3 MB and opens a fresh
        YYYY-MM-DD.log. The loop kept reading the renamed file forever, so it
        went deaf after the day's first rotation (the 2026-10-25 day-log
        rotated three times). Now the open handle's identity is compared with
        the path's on every poll; on a change the old handle is drained to its
        end, closed, and the new file read from its start.
      * midnight: the old day's unread tail was dropped (closed without a
        final read), and a new day's file first seen after the switch was
        opened at its END. Both fixed: drain, then read the new file from 0.
      * a read error raised out of the loop and killed the watcher; now the
        handle is closed and reopened at the end on the next poll (lines are
        lost rather than duplicated - a replayed 'champ select entered' could
        manufacture a false FAIL).
    """

    def __init__(self, path_for_today=None, opener=None) -> None:
        self._path_for_today = path_for_today or _log_path_for_today
        self._opener = opener or _open_shared
        self._path = self._path_for_today()
        self._fh = None
        self._partial = ""
        self._seek_end_next = True  # only the very first open skips history
        self._open()                # arm now: history before this point is ignored

    def close(self) -> None:
        if self._fh is not None:
            _close_quietly(self._fh)
            self._fh = None

    def _split(self, data: str) -> list[str]:
        parts = (self._partial + data).split("\n")
        self._partial = parts[-1]
        return parts[:-1]

    def _read(self) -> list[str]:
        try:
            data = self._fh.read()
        except OSError:
            self.close()
            self._seek_end_next = True
            self._open()  # at the end now, so the next poll sees what follows
            return []
        return self._split(data) if data else []

    def _drain_and_close(self) -> list[str]:
        """Read what is left of a FINISHED file, flush its last partial line."""
        lines = self._read() if self._fh is not None else []
        self.close()
        if self._partial:
            lines.append(self._partial)
            self._partial = ""
        return lines

    def _replaced(self) -> bool:
        """True when the path now names a different file than the open handle."""
        try:
            held = os.fstat(self._fh.fileno())
            now = os.stat(self._path)
        except FileNotFoundError:
            return True  # renamed away, fresh file not created yet
        except OSError:
            return False  # cannot tell; a broken handle surfaces in _read
        return not os.path.samestat(held, now)

    def _open(self) -> None:
        if not self._path.exists():
            self._seek_end_next = False  # whatever appears later is all new
            return
        self._fh = self._opener(self._path, seek_end=self._seek_end_next)
        if self._fh is not None:
            self._seek_end_next = False

    def poll(self) -> list[str]:
        lines: list[str] = []
        today = self._path_for_today()
        if today != self._path:            # midnight rollover
            lines.extend(self._drain_and_close())
            self._path = today
            self._seek_end_next = False
        elif self._fh is not None and self._replaced():  # size rotation
            lines.extend(self._drain_and_close())
            self._seek_end_next = False
        if self._fh is None:
            self._open()
        if self._fh is not None:
            lines.extend(self._read())
        return lines


class Watcher:
    """One poll tick: new lines -> classifier -> emitted verdicts, plus the
    wall-clock window timeout (a restart-preceded enter with no push for
    _WINDOW_TIMEOUT_S becomes FAIL)."""

    def __init__(self, tailer: DayLogTailer, emit=None) -> None:
        self._tailer = tailer
        self._emit = emit or _emit
        self._clf = A1Classifier()
        self._pending: tuple[int, float] | None = None  # (window_seq, first seen)

    def close(self) -> None:
        self._tailer.close()

    def tick(self, now: float) -> None:
        for line in self._tailer.poll():
            for rec in self._clf.feed(line):
                self._emit(rec)
        if not self._clf.has_open_window():
            self._pending = None
            return
        seq = self._clf.window_seq
        if self._pending is None or self._pending[0] != seq:
            self._pending = (seq, now)  # a new window: its own clock
        if now - self._pending[1] >= _WINDOW_TIMEOUT_S:
            for rec in self._clf.expire():
                self._emit(rec)
            self._pending = None


def main() -> int:
    _RUNTIME.mkdir(parents=True, exist_ok=True)
    if _STOP.exists():
        try:
            _STOP.unlink()
        except OSError:
            pass
    _say(f"[lcu-push-watcher] armed (READ-ONLY); tailing {_LOG_DIR}\\<today>.log "
         f"every {_POLL_S:g}s. Stop: drop {_STOP.name}")

    watcher = Watcher(DayLogTailer())
    try:
        while not _STOP.exists():
            watcher.tick(time.monotonic())
            time.sleep(_POLL_S)
    finally:
        watcher.close()
    _say("[lcu-push-watcher] STOP file seen; exiting")
    try:
        _STOP.unlink()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
