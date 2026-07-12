"""LCU push watcher - auto-validate gated item A1 while the operator plays.

A1 (docs/LIVE_GAME_GATED_SYNC.md line 90 / LEDGER item 779): after a mid-session
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

Log anchors VERIFIED in-repo (grep, 2026-07-11 - cite file:line):
  lcu/lcu_client.py:77    'LCU connected: port %d (from %s)'
  lcu/lcu_client.py:81    'LCU lockfile not found - client may not be running'
  lcu/lcu_client.py:117   'LCU reconnected: port %d (lockfile rotated, from %s)'
  lcu/lcu_rune_writer.py:624   'RuneWriter: champ select ended - re-armed for next pick'
  lcu/lcu_rune_writer.py:639   'RuneWriter: champ select entered'
  lcu/lcu_rune_writer.py:665   'RuneWriter: champion=%s mode=%s - applying runes'  (push FIRED)
  lcu/lcu_rune_writer.py:1023  'RuneWriter: wrote [%s] id=%s  perks=%s'            (page-write SUCCESS)
  lcu/lcu_rune_writer.py:671   'RuneWriter: rune write failed for %s/%s'           (FAIL)
  lcu/lcu_rune_writer.py:1036  'RuneWriter: gave up after %d attempts for [%s]: %s' (FAIL)

SCOPE = the RUNE push only. There is NO distinguishable champ-select SPELL-push
or ITEM/loadout-push pass/fail log line to key on:
  * SPELL push goes through lcu_client.set_summoner_spells(), which logs NOTHING
    on success or failure (grep: no info/warning). The only spell log lines are
    local-preference-save failures (lcu_rune_writer.py:363 save_spell_pref,
    lcu_rune_writer.py:481 save_champ_spell_pref) and a manual-override-detected
    info (lcu_rune_writer.py:838) - none is a champ-select spell PUSH signal.
  * There is NO champ-select ITEM/loadout push; the only item log lines are
    post-game item-event capture (lcu_postgame_collector.py:551/800).
So the A1 verdict is keyed on the rune push, which is exactly what A1 covers.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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


def classify_events(lines: Iterable[str]) -> list[dict]:
    """Classify a stream of log lines into A1 verdict records (PURE).

    A restart = a connect on a DIFFERENT port than last seen, OR a 'lockfile
    rotated' reconnect, OR a 'lockfile not found' gap followed by any connect.
    The FIRST 'champ select entered' after a restart is the A1 test case; a
    champ-select with no preceding restart is NOT a test case (stays quiet).

    Returns one record per test case, in order. Record keys: verdict
    (PASS/FAIL/PENDING), restart_reason, port_before, port_after, champion,
    mode, matched (list of the log lines that drove the verdict).
    """
    last_port: int | None = None
    gap_pending = False
    restart: dict | None = None   # armed restart, not yet consumed by a CS-enter
    window: dict | None = None    # currently-open A1 test-case window
    verdicts: list[dict] = []

    for raw in lines:
        line = raw.rstrip("\r\n")

        # --- restart signals ---
        m = _RE_RECONNECT_ROTATED.search(line)
        if m:
            port_after = int(m.group(1))
            restart = {"reason": "lockfile_rotated",
                       "port_before": last_port, "port_after": port_after}
            last_port = port_after
            gap_pending = False
            continue
        m = _RE_CONNECT.search(line)
        if m:
            port_after = int(m.group(1))
            if gap_pending:
                restart = {"reason": "lockfile_gap",
                           "port_before": last_port, "port_after": port_after}
            elif last_port is not None and port_after != last_port:
                restart = {"reason": "port_change",
                           "port_before": last_port, "port_after": port_after}
            # else: first connect (initial arm) or same-port RC reconnect -> not a restart
            last_port = port_after
            gap_pending = False
            continue
        if _RE_LOCKFILE_GAP.search(line):
            gap_pending = True
            continue

        # --- champ select enter (opens a test-case window IF a restart is armed) ---
        if _RE_CS_ENTER.search(line):
            if window is not None:
                _finalize(window, verdicts, close="reopened")
                window = None
            if restart is not None:
                window = {**restart, "champion": None, "mode": None,
                          "applied": False, "wrote": False, "failed": False,
                          "matched": [line]}
                restart = None  # consume it - only the FIRST enter after a restart counts
            continue

        # --- everything below only matters inside an open window ---
        if window is None:
            continue
        m = _RE_APPLYING.search(line)
        if m:
            window["applied"] = True
            window["champion"] = m.group(1)
            window["mode"] = m.group(2)
            window["matched"].append(line)
            continue
        if _RE_WROTE.search(line):
            window["wrote"] = True
            window["matched"].append(line)
            continue
        m = _RE_FAIL.search(line)
        if m:
            window["failed"] = True
            if not window["champion"]:
                window["champion"] = m.group(1)
                window["mode"] = m.group(2)
            window["matched"].append(line)
            _finalize(window, verdicts, close="failure")
            window = None
            continue
        if _RE_GAVEUP.search(line):
            window["failed"] = True
            window["matched"].append(line)
            _finalize(window, verdicts, close="failure")
            window = None
            continue
        if _RE_CS_END.search(line):
            window["matched"].append(line)
            _finalize(window, verdicts, close="cs_end")
            window = None
            continue

    if window is not None:  # still open at end of input -> PENDING
        _finalize(window, verdicts, close="eof")
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
# THIN WRAPPERS - side-effecting (tail / toast / network / disk). Not unit-tested.
# =============================================================================
def _fetch_state() -> dict | None:
    """Best-effort read of /api/state for champ/mode context (READ-ONLY)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(_STATE_URL, timeout=5, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - dashboard down / mid-restart -> no context
        return None


def _toast(title: str, body: str) -> None:
    """Fire a native Windows toast via hidden PowerShell WinRT (no console flash).

    Mirrors tools/live_flip_watcher.py._toast. Best-effort: the verdict file
    always lands even if the toast fails.
    """
    ps = f"""$ErrorActionPreference='SilentlyContinue'
[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null
[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null
$t=@'
<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual></toast>
'@
$x=New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml($t)
$n=New-Object Windows.UI.Notifications.ToastNotification $x
$app='{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($n)
"""
    tmp = _RUNTIME / "_lcu_push_toast.ps1"
    try:
        tmp.write_text(ps, encoding="ascii")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", str(tmp)],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception:  # noqa: BLE001 - toast is best-effort; the file always lands
        pass


def _emit(record: dict) -> None:
    """Toast + append jsonl + overwrite md for one finalized verdict record."""
    record.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S"))
    if not record.get("champion"):  # best-effort context fill (read-only)
        state = _fetch_state()
        if state:
            coach = state.get("coach") or {}
            record.setdefault("mode", state.get("mode_key"))
            if coach.get("champion"):
                record["champion"] = coach.get("champion")

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
    _toast(title, body)

    try:
        with _VERDICT_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _VERDICT_MD.write_text(render_verdict_md(record), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[lcu-push-watcher] verdict-file write failed: {exc}")
    print(f"[lcu-push-watcher] {v}: champ={champ} "
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
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY)  # the fd owns the handle now
    return os.fdopen(fd, "r", encoding="utf-8", errors="replace")


def _open_shared(path: Path, seek_end: bool):
    """Open the day-log for reading WITHOUT blocking RC's log rotation.

    Windows: via CreateFileW with FILE_SHARE_DELETE so the rotating handler can
    still rename the live log while we tail it (else WinError 32 freezes RC's
    logging - the 'share-lock' this watcher hit before re-arming). POSIX allows
    rename/unlink of an open file by default, so a plain open is share-safe there.
    Returns None on any open error (the poll loop retries), never raises."""
    try:
        if sys.platform == "win32":
            handle = _win_open_shared_delete(path)
        else:
            handle = path.open("r", encoding="utf-8", errors="replace")
        if seek_end:
            handle.seek(0, 2)  # SEEK_END - ignore pre-existing history
        return handle
    except OSError:
        return None


def main() -> int:
    _RUNTIME.mkdir(parents=True, exist_ok=True)
    if _STOP.exists():
        try:
            _STOP.unlink()
        except Exception:  # noqa: BLE001
            pass
    print(f"[lcu-push-watcher] armed (READ-ONLY); tailing {_LOG_DIR}\\<today>.log "
          f"every {_POLL_S:g}s. Stop: drop {_STOP.name}")

    cur_path = _log_path_for_today()
    fh = None
    partial = ""
    buffer: list[str] = []       # only NEW lines since start (seek-to-end)
    emitted = 0                  # count of finalized verdicts already toasted
    pending_since: float | None = None

    if cur_path.exists():
        fh = _open_shared(cur_path, seek_end=True)

    while not _STOP.exists():
        # midnight rollover: switch to the new day's file (read from its start)
        today = _log_path_for_today()
        if today != cur_path:
            if fh is not None:
                fh.close()
            cur_path = today
            fh = _open_shared(cur_path, seek_end=False) if cur_path.exists() else None
            partial = ""
        if fh is None and cur_path.exists():
            fh = _open_shared(cur_path, seek_end=True)

        if fh is not None:
            data = fh.read()
            if data:
                combined = partial + data
                parts = combined.split("\n")
                partial = parts[-1]
                buffer.extend(parts[:-1])

        verdicts = classify_events(buffer)
        now = time.monotonic()
        i = emitted
        while i < len(verdicts):
            rec = verdicts[i]
            is_last = i == len(verdicts) - 1
            if rec["verdict"] == "PENDING" and is_last:
                if pending_since is None:
                    pending_since = now
                if now - pending_since >= _WINDOW_TIMEOUT_S:
                    rec["verdict"] = "FAIL"
                    rec["timeout"] = True
                    _emit(rec)
                    emitted = i + 1
                    pending_since = None
                break  # nothing can follow a trailing PENDING
            _emit(rec)
            emitted = i + 1
            if is_last:
                pending_since = None
            i += 1

        time.sleep(_POLL_S)

    if fh is not None:
        fh.close()
    print("[lcu-push-watcher] STOP file seen; exiting")
    try:
        _STOP.unlink()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
