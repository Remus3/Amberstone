# arch: live RC health + topology probe | section=tools | frozen=no
"""rc_facts.py - print live ground truth for the RC stack.

Designed to be invoked as a Claude Code SessionStart hook on Legion.
Output (markdown to stdout) is injected as additional context, so the
session starts with current state instead of relying on possibly-stale
memory entries.

Probes (all should complete within ~3s total):
  - Legion: health.json (pid, alive, mode, rc_version), listener ports
    8888/8889, RC scheduled tasks state, last boot.
  - Legion-local agents: /api/state's lcu block freshness (proves the
    relocated LCU agent is posting) + the Live Client relay age.
  - Anomaly summary: anything unexpected, listed first.

Cheap and idempotent. Caller (the hook) gets stdout; non-zero exit just
means "couldn't probe" and is non-blocking.

Run manually any time:  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/rc_facts.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Captured at MODULE scope, deliberately. The import happens at process start,
# so this measures the same window the harness's hook timeout does, and a name
# defined only under `__main__` would raise NameError when `_save_reported` is
# reached from an IMPORTED copy of this module (the test path, and the poller
# path) - which the widened except would then swallow into an UNMEASURED line
# for a reason that has nothing to do with the inbox.
_T0 = time.monotonic()

# The SessionStart hook is killed at 8 s by the harness. A hook that prints at
# 7.9 s, records its block as reported, and is killed at 8.0 s has its stdout
# DROPPED - so the record would say "shown" for a block nobody ever saw, and
# every later prompt in that session would subtract it. That is the one
# whole-session suppression this design forbids, and the guard costs one clock
# read. Past the budget: print, record nothing, re-print next fire.
SESSIONSTART_RECORD_BUDGET_S = 6.0

# Newest N full names in the transcript; everything else goes to the report
# file the pointer line names. Capping the LIST, never the banner: the count is
# the part that says whether to go and look.
_INBOX_LIST_CAP = 10

# The ONE could-not-measure state that is recorded. A structurally absent
# directory can hide no mail, so showing it once per session id loses nothing.
# The transient faults (an unreadable seen store, a watcher failure) are NOT
# entries and are never recorded: a blind state that printed once and then went
# quiet reads exactly like a clean inbox.
_INBOX_ABSENT_KEY = "UNMEASURED:inbox-absent"

_REPORTED_MAX_SIDS = 64
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")

# os.walk budget for one subdirectory drop, and the Windows attribute bit that
# marks a junction / symlink / mount point.
_PAYLOAD_WALK_BUDGET = 5000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# SessionStart hook runs under windowless pythonw.exe; a powershell.exe child
# would otherwise get a fresh console allocated - an on-screen + taskbar flash.
# CREATE_NO_WINDOW suppresses it (Windows-only; 0 elsewhere).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_APP = Path(__file__).resolve().parent.parent
_HEALTH = _APP / "ops" / "runtime" / "health.json"
_LEGION_BASE = "https://legion-rc:8888"
_TIMEOUT = 2.5

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


def _http_get_json(url: str, headers: dict | None = None) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def _port_listening(port: int, host: str = "127.0.0.1", attempts: int = 3) -> bool:
    """TCP-connect probe. A bound port can still time out a fast connect when
    its accept loop is briefly busy (a single-threaded server mid-request), so a
    timeout is retried; only a refused connection counts as down immediately.

    Without the retry a busy-but-listening port (e.g. the single-threaded vision
    server on :8889 mid frame-upload) false-alarms as down.
    """
    for _ in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect((host, port))
            return True
        except socket.timeout:
            continue
        except OSError:
            return False
        finally:
            s.close()
    return False


def _legion_tasks() -> list[dict]:
    """Return [{name, state, last_result}, ...] for RC-* tasks via PowerShell."""
    cmd = (
        "Get-ScheduledTask | Where-Object TaskName -like 'RC-*' | "
        "ForEach-Object { $i = Get-ScheduledTaskInfo $_; "
        "@{ name = $_.TaskName; state = [string]$_.State; "
        "last_result = $i.LastTaskResult } } | ConvertTo-Json -Compress"
    )
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=4.0, text=True,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        if p.returncode != 0 or not p.stdout.strip():
            return []
        data = json.loads(p.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:  # noqa: BLE001
        return []


def _last_boot_iso() -> str | None:
    cmd = "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')"
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=2.0, text=True,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        if p.returncode == 0:
            return p.stdout.strip() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def _health_all() -> dict | None:
    return _http_get_json(f"{_LEGION_BASE}/api/health/all")


def main(session: str | None = None) -> int:
    out = []
    out.append("# RC live state (rc_facts.py)\n")
    out.append(f"_probed at {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")

    anomalies: list[str] = []

    # -- Legion ----------------------------------------------------------
    out.append("## Legion (legion-rc - 100.70.22.55 - 192.168.8.230)\n")
    health = {}
    try:
        health = json.loads(_HEALTH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        anomalies.append("Legion: ops/runtime/health.json unreadable")
    pid = health.get("pid")
    alive = bool(health.get("alive"))
    mode = health.get("mode") or "?"
    rc_version = health.get("rc_version") or "?"
    last_reload_ok = health.get("last_reload_ok")
    out.append(
        f"- RC: pid={pid} alive={alive} mode={mode} version={rc_version} "
        f"last_reload_ok={last_reload_ok}"
    )
    if not alive:
        anomalies.append(f"Legion: RC not alive (pid={pid})")
    if last_reload_ok is False:
        anomalies.append("Legion: last RC reload failed")

    # Listener ports
    p_dash = _port_listening(8888)
    p_vis = _port_listening(8889)
    out.append(f"- Listeners: :8888 dashboard={p_dash}  :8889 vision={p_vis}")
    if not p_dash:
        anomalies.append("Legion: dashboard :8888 not listening")
    if not p_vis:
        anomalies.append("Legion: vision server :8889 not listening")

    # Fetch /api/health/all once - used for DS health
    health_all = _health_all() or {}

    # DS alive check used to suppress RC-DaemonSlayer task false-positive
    ds_health = health_all.get("daemon_slayer") or {}
    ds_alive = bool(ds_health.get("alive"))

    # Scheduled tasks
    tasks = _legion_tasks()
    if tasks:
        running = [t for t in tasks if str(t.get("state")) in ("Running", "4", "Ready")]
        out.append(f"- Scheduled tasks ({len(tasks)} RC-*):")
        for t in tasks:
            n = t.get("name")
            s = t.get("state")
            r = t.get("last_result")
            # 267014 = shutdown-terminated (VisionServer in-process popen exit) - expected
            # RC-DaemonSlayer result=1: suppress if /api/health/all confirms ds alive
            # 2147946720 = 0x800710E0 "operator/admin refused the request": for an
            #   IgnoreNew singleton daemon (e.g. RC-Phase3-Supervisor) this is Task
            #   Scheduler correctly refusing a duplicate launch while the boot
            #   instance is still alive. state==Running proves the daemon is up, so
            #   the refused-duplicate code is benign, not a failure.
            running_now = str(s) in ("Running", "4")
            # RC-CostHealthWatchdog returns exit 1 BY DESIGN when it detects a
            # cost/health breach (tools/cost_health_watchdog.py: "return 1 if
            # breached else 0"). That is the watchdog doing its job, not a
            # failure - it fires whenever today's spend exceeds the trailing
            # baseline (i.e. after any coaching game). Suppress the "probably
            # failing" anomaly; the breach detail is in logs/cost_health_watchdog.log.
            # A Disabled task is not running, so its stale last_result is a
            # historical code, not a current-health signal - never flag it as
            # "probably failing" (e.g. RC-LiveFlipWatcher, intentionally off).
            suppress = (n == "RC-DaemonSlayer" and r == 1 and ds_alive) or (
                r == 2147946720 and running_now
            ) or (n == "RC-CostHealthWatchdog" and r == 1) or (str(s) == "Disabled")
            mark = "" if r in (0, 267009, 267011, 267014) or suppress else f"  ! result={r}"
            out.append(f"  - {n}: state={s}{mark}")
            if r not in (0, 267009, 267011, 267014, None) and not suppress:
                anomalies.append(
                    f"Legion: scheduled task {n} last_result={r} (probably failing)"
                )

    # Last boot
    lb = _last_boot_iso()
    if lb:
        out.append(f"- Last boot: {lb}")

    # DS server health line (after tasks so it groups with the port listeners block)
    if ds_health:
        ds_status = ds_health.get("status", "?")
        ds_patch = ds_health.get("patch", "?")
        out.append(f"- DS server :8860: {ds_status} patch={ds_patch} alive={ds_alive}")
        if not ds_alive or ds_status != "ok":
            anomalies.append(f"Legion: DS server not healthy (status={ds_status})")

    # -- Legion-local agents (relocated 2026-05-29, ADR-011) -------------
    out.append("\n## Legion-local agents (LCU + Live Client relay)\n")

    # LCU agent freshness via Legion's /api/state
    state = _http_get_json(f"{_LEGION_BASE}/api/state") or {}
    lcu = (state or {}).get("lcu") or {}
    lcu_ts = float(lcu.get("ts") or 0)
    lcu_age = int(time.time() - lcu_ts) if lcu_ts else None
    lcu_phase = lcu.get("phase") or "?"
    if lcu_age is not None:
        out.append(f"- LCU agent: phase={lcu_phase} age={lcu_age}s")
        if lcu_age > 30:
            anomalies.append(f"Legion: LCU agent stale ({lcu_age}s old)")
    else:
        out.append("- LCU agent: NO RECENT POST")
        anomalies.append("Legion: LCU agent not posting")

    # Liveclient block from /api/state
    lc = state.get("liveclient") or {}
    lc_ts = float(lc.get("ts") or 0) if isinstance(lc, dict) else 0
    if lc_ts:
        lc_age = int(time.time() - lc_ts)
        out.append(f"- Liveclient relay: age={lc_age}s")
    else:
        out.append("- Liveclient relay: empty (no game in progress)")

    # -- Unread cross-repo inbox notes -----------------------------------
    #
    # Design from Sibling-A 2026-09-06, adopted with one change. A note
    # written into moon_sync_inbox/ by a sibling repo used to be discovered
    # only when a human mentioned it - LW confirmed it has no watcher at all,
    # so a note could sit until someone happened to look. SessionStart is ONE
    # delivery point: it costs one directory listing, needs no daemon, cannot
    # flash a console, and survives /clear by construction, because a /clear IS
    # a session start.
    #
    # IT IS NOT SUFFICIENT ON ITS OWN, and an earlier version of this comment
    # called it "the right delivery point" full stop, which reads as an answer
    # to the next reader's question and is why the gap survived. SessionStart
    # fires ONCE. A note landing while a session is live is invisible until the
    # next start, which is the common case on this channel. That half is
    # covered by `report_inbox_only()` on UserPromptSubmit; see its docstring.
    #
    # THE CHANGE FROM LW'S DESIGN: they proposed an mtime WATERMARK. A
    # watermark advances on write, so if this hook runs and the session is
    # cleared or killed before anyone reads the output, the watermark has moved
    # past a note nobody saw - and it is unrecoverable, because "unread" was
    # never a property of the file. A seen SET has no such window: an entry
    # stays unread until its key is recorded, and re-listing a key is
    # idempotent. It also survives clock skew and a copy that preserves
    # timestamps, both of which silently defeat an mtime comparison. That
    # argument is unchanged and still load-bearing.
    #
    # The KEY is no longer the bare filename this comment used to describe. It
    # is (name, content digest) for notes and (name, contents digest) for
    # subdirectory drops, because a name-only key cannot see an edit in place
    # or a retraction. Sibling-E found a paragraph in their own watcher
    # DEFENDING the name key on the grounds that a content hash would hide an
    # edit - exactly inverted, since an edit changes the content and therefore
    # the hash. Their rule is worth carrying: a wrong rationale outlives a
    # wrong line of code, because it answers the question before it is asked.
    #
    # SUBTRACT NOTHING HERE. SessionStart always prints the full block, and
    # only records it. A resume, a compact or a /clear that keeps the same
    # session id therefore re-prints once, by design: the loud direction. The
    # alternative - subtracting the record at session start - delivers an EMPTY
    # block into a fresh context, which is the failure this whole design is
    # against.
    block, inbox_anomalies, inbox_keys = _inbox_section(_ROOT, session, subtract=False)
    anomalies.extend(inbox_anomalies)
    if block:
        out.append("")
        out.extend(block)

    # -- Anomaly summary first if any ------------------------------------
    #
    # ORDER: the report file is already written (inside _inbox_section, which
    # records nothing, so a kill after it suppresses nothing and the pointer
    # never names an absent file). Now stdout, then the flush, and only THEN
    # the record. A record written before delivery marks a block reported that
    # a killed hook never delivered.
    delivered = True
    try:
        if anomalies:
            head = "## ! Anomalies\n\n" + "\n".join(f"- {a}" for a in anomalies) + "\n\n"
            sys.stdout.write(head)
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - a hook must never fail the session start
        # NOT `except OSError`: under pythonw.exe sys.stdout can be None, and
        # print/write then raises AttributeError. Nothing is re-printed here
        # either, because when the failure IS stdout a second write raises
        # again and the process exits 1. The invocation log written before this
        # is the evidence the fire happened.
        delivered = False
    if delivered and session is not None and inbox_keys:
        _save_reported(session, inbox_keys)
    return 0


def _entry_name(key: str) -> str:
    """The stable identity inside a watcher key, without its digest.

    Keys are `<name> [<digest>]` for notes and `<name>/ [<n> files, ...]` for
    drops. Stripping the bracketed part is what lets an EDIT (same name, new
    digest) be told apart from a WITHDRAWAL (name gone entirely). Without the
    distinction an edited note would report as both unread and withdrawn.
    """
    return key.rsplit(" [", 1)[0]


def _inbox_withdrawn(names: set[str], seen: set[str]) -> list[str]:
    """Entries acknowledged earlier whose NAME is no longer in the inbox.

    Added 2026-09-07 on Sibling-D's finding, which they raised as a sixth
    property after RC deleted 50 files from four sibling inboxes in a PII
    pullback. Set subtraction the other way (`names - seen`) cannot see a
    deletion at all: a withdrawn note simply stops appearing, so the watcher
    goes quiet at exactly the moment a sibling retracted something.

    LL's sentence is the one worth keeping: on this channel a correction and a
    retraction are the two messages you least want silent.
    """
    live = {_entry_name(k) for k in names}
    return sorted({_entry_name(k) for k in seen} - live)


def _file_digest(p: Path) -> str:
    """sha256 of one file's bytes, or the exception class if unreadable.

    An unreadable file must MOVE the digest rather than vanish from it. If a
    read error contributed nothing, a payload that became unreadable would key
    identical to the one already acknowledged.
    """
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError as exc:
        return f"UNREADABLE:{type(exc).__name__}"


def _is_reparse_point(p: Path) -> bool:
    """True for a junction, a symlink or a mount point.

    `Path.is_symlink()` alone is not enough on Windows: a DIRECTORY JUNCTION is
    a reparse point that older Python builds do not report as a symlink, and a
    junction is exactly the cheap shape a sender could use to aim this walk
    outside the drop. The attribute bit is the authority; is_symlink is the
    portable half. An lstat failure is not treated as a refusal - the file is
    then handled by `_file_digest`, which records the error class.
    """
    try:
        if p.is_symlink():
            return True
        st = os.lstat(p)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _payload_key(p: Path) -> str:
    """Identify a subdirectory payload by a digest over its CONTENTS.

    Rewritten 2026-09-07 after an empirical probe showed both earlier keys
    were content-blind, each in its own way:

      * The original `(N files)` count let a sender REPLACE a file without
        moving the key, so the payload read as already-seen.
      * The MANIFEST key that replaced it only re-read the manifest FILE. A
        payload edited without regenerating its manifest keyed identical -
        measured, not theorised. Trusting a sender's manifest means trusting
        that they remembered to rebuild it, which is exactly the assumption a
        watcher exists to remove.

    So the digest is computed over what is actually on disk. Per Sibling-D's
    OPS-34 design, re-implemented from their prose rather than vendored: one
    line per contained file holding the drop-relative POSIX path, a NUL, then
    that file's sha256; sorted; joined with newlines; hashed once.

    The path is INSIDE each line deliberately. A digest over contents alone
    calls two files that swapped contents unchanged, and a rearranged drop is
    a changed drop.

    A manifest, when present, is reported for human context but is NOT the key.

    THE WALK REFUSES REPARSE POINTS (2026-09-15). `rglob("*")` follows a
    junction, so a sender could aim one at an arbitrary directory and this
    watcher would read and digest whatever is behind it, unbounded, inside a
    hook that must finish in seconds. A refusal is not silent: it contributes
    its own line so the digest MOVES, the same idiom `_file_digest` uses for an
    unreadable file. A payload that GAINS a junction is not equal to the one
    already acknowledged.

    BYTE-STABLE for a plain drop: with no reparse point and at most
    `_PAYLOAD_WALK_BUDGET` files, the lines and their order are identical to
    the previous `rglob` formula, so no already-recorded key shifts.
    """
    entries: list[tuple[str, bytes]] = []
    refused: list[tuple[str, bytes]] = []
    exceeded = False
    for dirpath, dirnames, filenames in os.walk(p):
        d = Path(dirpath)
        keep: list[str] = []
        for name in dirnames:
            child = d / name
            if _is_reparse_point(child):
                rel = child.relative_to(p).as_posix()
                refused.append((child.as_posix(), f"REFUSED:reparse:{rel}\0-".encode()))
            else:
                keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            f = d / name
            if _is_reparse_point(f):
                rel = f.relative_to(p).as_posix()
                refused.append((f.as_posix(), f"REFUSED:reparse:{rel}\0-".encode()))
                continue
            if len(entries) >= _PAYLOAD_WALK_BUDGET:
                exceeded = True
                break
            rel = f.relative_to(p).as_posix()
            entries.append((
                f.as_posix(),
                f"{rel}\0{_file_digest(f)}".encode("utf-8", "surrogateescape"),
            ))
        if exceeded:
            break
    lines = [line for _sort, line in sorted(entries + refused)]
    digest = hashlib.sha256(b"\n".join(lines)).hexdigest()[:12]
    manifest = next(
        (n for n in ("MANIFEST.sha256", "MANIFEST.txt", "manifest.json") if (p / n).is_file()),
        None,
    )
    tail = f", {manifest} present" if manifest else ""
    if exceeded:
        return f"[{_PAYLOAD_WALK_BUDGET}+ files, content {digest}, BUDGET-EXCEEDED{tail}]"
    return f"[{len(entries)} files, content {digest}{tail}]"


def _inbox_entries(inbox: Path) -> set[str]:
    """Every unit of inbound mail, INCLUDING subdirectory payloads.

    WIDENED 2026-09-06 (operator directive: review the inbox AND its
    subdirectories). The original scan was top-level `*.md` only, and it missed
    two whole classes:

      * SUBDIRECTORY payloads. Siblings send verbatim source under
        `from-<CODE>-verbatim/`, which is a convention RC itself introduced -
        and RC's own watcher could not see it. Sibling-E sent 70 files that way
        and RC never reported one of them. RC asked four repos to reciprocate in
        a shape its own watcher was blind to.
      * Top-level files that are not `.md`.

    A directory payload is ONE entry, not N. Listing 70 files as 70 unread notes
    buries the five real notes beside them, and the unit a reader acts on is the
    payload, not each file in it. The entry carries the file count so a payload
    that GROWS is not silently equal to the one already acknowledged.

    `_`-prefixed names stay excluded: those are drafts staged in the inbox.

    NOTES ARE KEYED ON (name, content digest), not on name alone. Measured
    2026-09-07: a name-only key meant a sibling who CORRECTED a note in place
    - which LW has done at least twice, under a "CORRECTION" heading - moved
    nothing the watcher could see, so the correction was never reported. The
    pair makes both edit paths visible: a rename surfaces it, an edit surfaces
    it. Sibling-D credited RC with this design before RC actually had it.
    """
    if not inbox.is_dir():
        return set()
    out: set[str] = set()
    for p in sorted(inbox.iterdir()):
        if p.name.startswith("_"):
            continue
        if p.is_dir():
            out.add(f"{p.name}/ {_payload_key(p)}")
        elif p.is_file():
            out.add(f"{p.name} [{_file_digest(p)[:12]}]")
    return out


def _probe_inbox_listable(inbox: Path) -> None:
    """Raise OSError when `inbox` cannot be listed. Returns None otherwise.

    The acknowledge path's readability check (`mark_inbox_seen`), lifted so the
    two NON-acknowledging readers can make the same check. Call it AFTER
    `_inbox_entries`, on an inbox already known to be a directory: an empty
    result from a listing that failed and an empty result from an inbox that is
    really empty look identical, and only this probe tells them apart.

    It exists because both the watcher's withdrawal count and the poller's
    watermark save were protected only by `_inbox_entries` happening to RAISE.
    If that listing ever swallows its error and returns an empty set, the
    watcher reports every acknowledged note WITHDRAWN and the poller saves an
    empty entry over its watermark. `tests/test_inbox_swallowed_listing.py`
    applies that mutant and demands both still refuse.
    """
    for _probe in inbox.iterdir():
        break


def mark_inbox_seen() -> int:
    """Record every current inbox note as seen. Idempotent.

    Separate from the hook on purpose: the hook REPORTS, the operator (or the
    session, once it has actually read them) ACKNOWLEDGES. Advancing the
    watermark inside the hook is the failure this design avoids - see the note
    in main().

    REFUSES RATHER THAN ERASES when the inbox cannot be enumerated (2026-09-16).
    Until this guard, the function computed `names = ... if inbox.is_dir() else
    []` and then wrote UNCONDITIONALLY, so an ABSENT `moon_sync_inbox/` wrote an
    empty seen set over the live watermark and printed a success line. Measured
    on an isolated copy of the real store: 22503 bytes holding 198 keys became
    18 bytes holding `{"seen": []}`, exit 0, stdout `recorded 0 inbox note(s) as
    seen`.

    THIS IS REACHABLE, NOT THEORETICAL. `moon_sync_inbox/` is GITIGNORED, so it
    is absent in a fresh clone, absent in every worktree, and removable by a
    `git clean -xdf`. RC keeps six long-lived lane worktrees plus agent
    worktrees. Any session that runs the acknowledge path with the directory
    missing destroys the watermark the whole watcher exists to keep.

    THE ASYMMETRY THIS CLOSES. RC's WATCHER (`_inbox_section`) treats an absent
    inbox as a RECORDED FAULT and prints an `UNMEASURED` line for it. The
    acknowledge path treated the IDENTICAL condition as "zero notes". One
    condition, two readings, and the destructive one was the silent one.

    BOTH refusal conditions are probed EXPLICITLY here - absent, and present but
    unlistable. The unlistable case used to be protected only by the fact that
    the unwrapped `iterdir()` in `_inbox_entries` raised before the write, which
    is luck rather than a guard: a later reader who wraps that call in a
    try/except returning an empty set - the shape a sibling tree actually has -
    would silently reintroduce the erasure. The probe below does not depend on
    `_inbox_entries` raising, and `tests/test_inbox_ack_refuses.py` applies that
    exact mutation and demands this function still refuse.

    EXIT 3 is deliberate. 1 is what an uncaught exception (a syntax error in
    this module included) produces and 2 is the conventional CLI-usage code, so
    neither is self-evidencing: a reader seeing 2 cannot tell a deliberate
    refusal from a module that failed to parse. Nothing in the interpreter or
    the stdlib returns 3 on its own, so a 3 from this entry point can only have
    come from the `return 3` below, and the `REFUSED` line on stdout corroborates
    it. An empty inbox that IS listable is still a normal, successful 0.
    """
    inbox = _ROOT / "moon_sync_inbox"
    seen_path = _ROOT / "ops" / "runtime" / "sync_inbox_seen.json"

    if not inbox.is_dir():
        print(
            "REFUSED: moon_sync_inbox/ is absent - not acknowledging anything. "
            f"The seen store at {seen_path} is UNCHANGED. An inbox that is not "
            "there is not an empty inbox, and overwriting the watermark here "
            "would lose every acknowledgement already recorded. The directory "
            "is gitignored, so this is the normal state of a fresh clone or a "
            "worktree - run this from the tree that actually holds the inbox."
        )
        return 3

    try:
        names = sorted(_inbox_entries(inbox))
        # Corroborate listability independently of _inbox_entries, so a future
        # try/except inside it cannot turn this refusal back into an erasure.
        for _probe in inbox.iterdir():
            break
    except OSError as exc:
        print(
            f"REFUSED: moon_sync_inbox/ could not be listed ({type(exc).__name__}"
            f": {exc}) - not acknowledging anything. The seen store at "
            f"{seen_path} is UNCHANGED. An inbox RC cannot read is not an empty "
            "inbox."
        )
        return 3

    seen_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = seen_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"seen": names}, indent=2), encoding="utf-8")
    tmp.replace(seen_path)
    print(f"recorded {len(names)} inbox note(s) as seen -> {seen_path}")
    return 0


# ---------------------------------------------------------------------------
# The per-session REPORTED record.
#
# REPORTED IS NOT SEEN, and the distinction is the whole point. `seen` is the
# operator's acknowledgement, written only by --mark-inbox-seen. `reported` is
# "this session has already had these lines put in front of it", written by the
# watcher itself. Collapsing the two is the defect a sibling repo measured in
# its own tree: a subagent's session start marked the operator's queue read.
#
# Keyed per hook-stdin session_id because two SessionStart fires can share a
# second (13 same-second pairs measured on this box since 2026-09-07) and only
# one of them goes on to serve prompts. A single-session file would let the
# twin's block suppress the live session's.
#
# EVICTION CAN ONLY CAUSE A RE-PRINT. The bound drops the oldest sids by "at";
# a dropped sid simply sees its block again. There is no path here that turns
# eviction into silence, and the test says so.


def _reported_path() -> Path:
    return _ROOT / "ops" / "runtime" / "sync_inbox_reported.json"


def _load_reported() -> dict:
    """The record, or {} for anything unreadable. Fail OPEN: an unreadable
    record means nothing is subtracted, so the block prints again."""
    try:
        data = json.loads(_reported_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _reported_keys(session: str | None) -> set[str]:
    if not session:
        return set()
    row = (_load_reported().get("sessions") or {}).get(session)
    keys = row.get("keys") if isinstance(row, dict) else None
    return set(keys) if isinstance(keys, list) else set()


def _save_reported(session: str, keys: set[str]) -> None:
    """Union `keys` into this session's row. Never raises, never blocks.

    Returns WITHOUT WRITING past `SESSIONSTART_RECORD_BUDGET_S`, so a hook the
    harness is about to kill cannot mark a block reported whose stdout is then
    dropped. Any OSError is swallowed: a failed write means the entries print
    again, which is the safe direction.
    """
    if time.monotonic() - _T0 > SESSIONSTART_RECORD_BUDGET_S:
        return
    try:
        data = _load_reported()
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        row = sessions.get(session)
        old = row.get("keys") if isinstance(row, dict) else None
        merged = set(old) if isinstance(old, list) else set()
        merged |= set(keys)
        sessions[session] = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "keys": sorted(merged),
        }
        if len(sessions) > _REPORTED_MAX_SIDS:
            # Stable on ties: sids written inside the same second evict in
            # insertion order, oldest first.
            ordered = sorted(sessions.items(), key=lambda kv: str((kv[1] or {}).get("at") or ""))
            for dead, _row in ordered[: len(sessions) - _REPORTED_MAX_SIDS]:
                sessions.pop(dead, None)
        path = _reported_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".json.tmp.{os.getpid()}")
        tmp.write_text(json.dumps({"schema": 1, "sessions": sessions}, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # fail open - the entries re-print next fire


def _ascii(s: str) -> str:
    """Printed names only. Free hardening, not an anti-injection claim: the
    harness sets PYTHONUTF8 already, so this is about the one remaining way a
    name could raise on write and cost the whole block."""
    return s.encode("ascii", "backslashreplace").decode()


def _write_inbox_report(unread: list[str], withdrawn: list[str]) -> bool:
    """Render EVERY unread key and withdrawn name to the gitignored report.

    Written BEFORE stdout on purpose. It records nothing, so a kill after it
    suppresses nothing - and the pointer line that names it is then never a
    pointer to an absent file.

    Rewritten, never appended, and skipped entirely when the bytes already
    match, so an idle session does not touch the file's mtime. Returns False on
    an OSError; the caller then prints an UNMEASURED pointer and does NOT treat
    the entries beyond the cap as shown.
    """
    path = _ROOT / "ops" / "runtime" / "sync_inbox_report.txt"
    body = "".join(f"{_ascii(n)}\n" for n in unread)
    body += "".join(f"WITHDRAWN:{_ascii(n)}\n" for n in withdrawn)
    data = body.encode("ascii")
    try:
        if path.is_file() and path.read_bytes() == data:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".txt.tmp.{os.getpid()}")
        # write_bytes, not write_text: text mode turns LF into CRLF on Windows,
        # which moves the bytes every run and defeats the unchanged check.
        tmp.write_bytes(data)
        tmp.replace(path)
        return True
    except OSError:
        return False


def _session_id(payload: dict | None) -> str | None:
    """The hook payload's session_id, or None unless it is plainly a session id.

    Validated before it is ever used as a dict key or a filename component.
    The same field `record_invocation` logs, read the same way.
    """
    sid = payload.get("session_id") if isinstance(payload, dict) else None
    if isinstance(sid, str) and _SESSION_ID_RE.match(sid):
        return sid
    return None


def report_inbox_only(session: str | None = None) -> int:
    """Inbox scan alone, cheap enough to run on EVERY operator message.

    Exists because `SessionStart` fires once and never again. A note that lands
    while a session is live was invisible until the next start, which is the
    common case here: the siblings write into this inbox continuously, and one
    of them measured a drop growing by two files eleven minutes apart inside a
    single session. A watcher that only looks at startup cannot see that, no
    matter how good its key is.

    Wired to `UserPromptSubmit`, so it also re-fires on the first message after
    a `/clear` - a `/clear` starts a fresh context but the operator's first
    message is usually a pasted hand-off prompt, and the inbox must be checked
    against THAT moment rather than against whenever the process happened to
    start.

    SILENT when nothing is unread. A hook that prints on every prompt trains
    the reader to skip it, and this one has to stay worth reading. It also
    never advances the seen watermark: acknowledgement stays a separate,
    deliberate act, which is what keeps a subagent's start from marking the
    operator's queue read (a defect a sibling repo measured in its own tree).

    SUBTRACTS the per-session reported record, which is what keeps it worth
    reading: a new name, a changed digest or a retraction shows once, and the
    same block does not re-print on every prompt for the life of the session.
    With no validated session id it fails OPEN - prints as before, records
    nothing.
    """
    lines, _anomalies, keys = _inbox_section(_ROOT, session)
    if not lines:
        return 0
    delivered = True
    try:
        for line in lines:
            print(line)
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - a hook must never fail the turn
        # See main(): not OSError, and nothing is re-printed from in here.
        delivered = False
    if delivered and session is not None and keys:
        _save_reported(session, keys)
    return 0


def _inbox_section(
    root: Path, session: str | None, *, subtract: bool = True
) -> tuple[list[str], list[str], set[str]]:
    """The whole watcher, once, for both entry points.

    Returns (block lines, anomaly lines, keys to record). ONE implementation
    because the two callers' copies were near-duplicates edited in lockstep,
    and a golden-output test can only be written against something that does
    not run live probes.

    `subtract=False` is SessionStart: it prints the full block and records it,
    never the other way round.

    WHAT IS AND IS NOT AN ENTRY. An unread note, a changed digest and a
    withdrawal are entries: each is shown once per validated session id. An
    absent moon_sync_inbox/ is the ONE recorded fault - with no directory there
    is nowhere for mail to land, so once per session loses nothing, and when
    the directory comes back its entries print because they were never
    recorded. An unreadable seen store and an unexpected failure are NOT
    entries and are never recorded: they re-print on every fire while the fault
    persists, because a blind state that goes quiet reads as a clean inbox.

    Nothing here executes at import - tools/moon_sync_poller.py and
    tools/inbox_responder_runner.py both import this module, and an import
    fault would take out a restart loop rather than one hook fire.
    """
    def unmeasured(reason: str) -> tuple[list[str], list[str], set[str]]:
        line = f"## Cross-repo inbox - UNMEASURED: {reason}"
        return [line], [f"moon_sync_inbox: UNMEASURED: {reason}"], set()

    try:
        reported = _reported_keys(session) if subtract else set()

        inbox = root / "moon_sync_inbox"
        if not inbox.is_dir():
            if _INBOX_ABSENT_KEY in reported:
                return [], [], set()
            lines, anomalies, _keys = unmeasured("moon_sync_inbox/ absent")
            return lines, anomalies, {_INBOX_ABSENT_KEY}

        seen_path = root / "ops" / "runtime" / "sync_inbox_seen.json"
        try:
            raw = seen_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # A store that never existed is "nothing acknowledged yet", not a
            # failure to look. Coercing THIS to UNMEASURED would hide a fresh
            # tree's whole inbox behind one line until someone ran the ack.
            seen: set[str] = set()
        except Exception as exc:  # noqa: BLE001
            return unmeasured(f"seen store unreadable ({type(exc).__name__})")
        else:
            try:
                seen = set(json.loads(raw).get("seen", []))
            except Exception as exc:  # noqa: BLE001
                # .get on a valid-JSON non-dict raises AttributeError and set()
                # on a non-iterable raises TypeError. Neither was caught
                # before, so the hook exited 1 and its stdout was dropped.
                return unmeasured(f"seen store unreadable ({type(exc).__name__})")

        try:
            names = _inbox_entries(inbox)
            # Not a recorded fault: an unlistable inbox re-prints every fire,
            # because a blind state that goes quiet reads as a clean inbox.
            _probe_inbox_listable(inbox)
        except OSError as exc:
            return unmeasured(f"moon_sync_inbox/ unlistable ({type(exc).__name__})")
        unread = [k for k in sorted(names - seen) if k not in reported]
        withdrawn = [
            n for n in _inbox_withdrawn(names, seen) if f"WITHDRAWN:{n}" not in reported
        ]
        if not unread and not withdrawn:
            return [], [], set()

        # The report file FIRST, and only under a validated session id: a
        # sid-less run prints today's plain pointer and writes nothing at all.
        report_ok = True
        report_exc = "OSError"
        if session is not None:
            try:
                report_ok = bool(_write_inbox_report(unread, withdrawn))
            except Exception as exc:  # noqa: BLE001
                report_ok = False
                report_exc = type(exc).__name__

        def pointer(total: int) -> str:
            over = total - _INBOX_LIST_CAP
            if session is None:
                return f"- ... and {over} more"
            if not report_ok:
                return f"- ... and {over} more - UNMEASURED: report file unwritable ({report_exc})"
            return f"- ... and {over} more - ops/runtime/sync_inbox_report.txt"

        lines: list[str] = []
        anomalies: list[str] = []
        if unread:
            anomalies.append(
                f"moon_sync_inbox: {len(unread)} unread note(s) from sibling repos")
            lines.append(f"## Cross-repo inbox - {len(unread)} UNREAD")
            lines.extend(f"- {_ascii(n)}" for n in unread[-_INBOX_LIST_CAP:])
            if len(unread) > _INBOX_LIST_CAP:
                lines.append(pointer(len(unread)))
        if withdrawn:
            anomalies.append(
                f"moon_sync_inbox: {len(withdrawn)} entry(s) WITHDRAWN by a sibling")
            lines.append(f"## Cross-repo inbox - {len(withdrawn)} WITHDRAWN since last ack")
            lines.extend(f"- {_ascii(n)}" for n in withdrawn[-_INBOX_LIST_CAP:])
            if len(withdrawn) > _INBOX_LIST_CAP:
                lines.append(pointer(len(withdrawn)))
        lines.append("Read them, then record them as seen:")
        lines.append("  python tools/rc_facts.py --mark-inbox-seen")

        # The pointer IS the showing of the entries beyond the cap - but only
        # when the file it names actually holds them. When the write failed,
        # they were never shown, so they are not recorded and print next fire.
        if report_ok:
            shown_unread, shown_withdrawn = unread, withdrawn
        else:
            shown_unread = unread[-_INBOX_LIST_CAP:]
            shown_withdrawn = withdrawn[-_INBOX_LIST_CAP:]
        keys = set(shown_unread) | {f"WITHDRAWN:{n}" for n in shown_withdrawn}
        return lines, anomalies, keys
    except Exception as exc:  # noqa: BLE001
        return unmeasured(f"watcher failed ({type(exc).__name__})")


# ---------------------------------------------------------------------------
# Hook invocation log
#
# WHY THIS EXISTS, and it is not RC's insight. CS measured on 2026-09-07 that
# its watcher "does not read the hook payload, does not read the `source`
# field, and writes no record of having been invoked", and downgraded its own
# /clear-survival status from UNVERIFIED to UNMEASURABLE AS BUILT. RSC measured
# the same. RC then measured the same about RC and refused a credit CS had
# extended to it: RC had a poller-side PROCESS log (moon_sync_poller.py, a
# different artifact) and no hook invocation record at all.
#
# The generalisation is CS's and it is the load-bearing part: all five repos on
# that channel had been reading hook CONFIGURATION as hook BEHAVIOUR. A
# watcher whose only output is a report to a human cannot be audited by anyone,
# its author included, because firing leaves nothing behind. This makes
# /clear survival a thing the operator MEASURES - clear once, read the file -
# rather than a property argued from a settings file.
#
# KNOWN LIMIT, stated rather than discovered later: the append is atomic (see
# _append_atomic) but the rotation is a read-then-replace, so an append racing
# a rotation can lose a line at the OLDEST end. The question this log answers -
# did it fire since the last /clear - is asked of the NEWEST lines, so the loss
# falls on the boundary that does not carry the answer. ops/loop/winmutex.py
# would close it; a per-prompt hook is the wrong place to take a dependency on
# a cross-repo pinned module, and a mutex wait is a hang risk this must not have.

_LOG_KEEP = 1000
_LOG_TRIM_BYTES = 32768
_FIELD_MAX = 64


def invocation_log_path() -> Path:
    """Where fires are recorded. `RC_HOOK_LOG` redirects it.

    The override exists because a test that spawns this file as a SUBPROCESS
    cannot pass `path=` - it gets the default, and the default was the live
    log. MEASURED: one polluted line per suite run, and those lines were
    indistinguishable from real fires until this was traced. An audit log its
    own test suite writes into is not an audit log.

    RSC reported the identical class an hour earlier, from a fixture that named
    three module defaults by hand and missed the fourth added later. The
    transferable half is theirs: a hand-maintained isolation list fails
    silently the moment someone adds the next default, so the arm below asserts
    the LIVE file is untouched rather than trusting a list.
    """
    override = os.environ.get("RC_HOOK_LOG")
    if override:
        return Path(override)
    return _ROOT / "ops" / "runtime" / "hook_invocations.jsonl"


def _hook_source(payload: dict | None) -> str:
    """The payload's `source` field, bounded, defaulting EXPLICITLY.

    Returns the string "unknown" rather than omitting the key, because an
    absent field and an unrecorded one read identically to anyone parsing the
    log later - which is the exact defect the log exists to remove.
    """
    if not isinstance(payload, dict):
        return "unknown"
    raw = payload.get("source")
    if not isinstance(raw, str) or not raw:
        return "unknown"
    return raw[:_FIELD_MAX]


def _read_hook_payload_with_reason(stream=None) -> tuple[dict, str]:
    """Payload plus WHY it is empty when it is.

    Added within an hour of shipping the log, because the log's first real
    fires recorded payload=false and there was no way to tell which of "no
    stdin under pythonw", "a tty", "an empty pipe" or "unparseable bytes"
    caused it. Guessing between those four would have been the identical error
    this log exists to stop - reading configuration as behaviour. The next real
    fire answers it instead.
    """
    try:
        if stream is None:
            stream = sys.stdin
            if stream is None:
                return {}, "none"
            if stream.isatty():
                return {}, "tty"
        raw = stream.read()
        if not raw:
            return {}, "empty"
        data = json.loads(raw)
        return (data, "json") if isinstance(data, dict) else ({}, "notdict")
    except Exception:  # noqa: BLE001 - stdin can fail in ways not worth enumerating
        return {}, "error"


def _read_hook_payload(stream=None) -> dict:
    """Hook payload JSON from stdin, or {} for anything else.

    Reading stdin is a hang risk the previous design did not carry, so every
    way it can go wrong returns {}: no stdin under pythonw.exe, a terminal
    (isatty, where a read would block forever), empty input, non-JSON, or JSON
    that is not an object.
    """
    try:
        if stream is None:
            stream = sys.stdin
            if stream is None or stream.isatty():
                return {}
        raw = stream.read()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - stdin can fail in ways not worth enumerating
        return {}


def _append_atomic(p: Path, data: bytes) -> None:
    """Append `data` as one indivisible write, safe across PROCESSES.

    MEASURED, not assumed: the obvious implementation - os.open with O_APPEND
    then os.write - lost 20 of 64 concurrent appends on this box. Windows' CRT
    implements O_APPEND as seek-to-end THEN write, which is two operations and
    races. POSIX O_APPEND is atomic; Windows' is not, and the difference is
    invisible until you count the lines.

    A thread lock would not have helped either way: every hook fire is its own
    pythonw.exe process, so the contention is cross-process by construction.

    Win32 documents the fix - a handle opened with FILE_APPEND_DATA and NOT
    FILE_WRITE_DATA always appends atomically - so that is the handle used
    here. Non-Windows keeps the POSIX path, where O_APPEND already holds.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        k32.WriteFile.argtypes = [
            wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
        ]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        _FILE_APPEND_DATA = 0x0004  # deliberately WITHOUT FILE_WRITE_DATA
        _SHARE_ALL = 0x0001 | 0x0002 | 0x0004
        _OPEN_ALWAYS = 4
        _ATTR_NORMAL = 0x80
        _INVALID = wintypes.HANDLE(-1).value

        h = k32.CreateFileW(
            str(p), _FILE_APPEND_DATA, _SHARE_ALL, None, _OPEN_ALWAYS, _ATTR_NORMAL, None
        )
        if not h or h == _INVALID:
            raise OSError(ctypes.get_last_error(), f"CreateFileW failed for {p}")
        try:
            written = wintypes.DWORD(0)
            if not k32.WriteFile(h, data, len(data), ctypes.byref(written), None):
                raise OSError(ctypes.get_last_error(), f"WriteFile failed for {p}")
        finally:
            k32.CloseHandle(h)
        return

    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _trim_invocation_log(p: Path) -> None:
    """Bound the file, dropping the OLDEST lines.

    Size is checked before the line count so the common case is one stat().
    Dropping the oldest is the point: a rotation keeping the oldest would
    answer "did it fire in April" instead of "did it fire since the /clear".
    """
    try:
        if p.stat().st_size < _LOG_TRIM_BYTES:
            return
        lines = [
            ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()
        ]
        if len(lines) <= _LOG_KEEP:
            return
        tmp = p.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(lines[-_LOG_KEEP:]) + "\n", encoding="utf-8", newline="\n")
        tmp.replace(p)
    except Exception:  # noqa: BLE001 - rotation is best-effort; never break a fire
        pass


def record_invocation(
    event: str,
    payload: dict | None = None,
    path: Path | None = None,
    stdin_state: str = "n/a",
) -> None:
    """Append exactly one line recording that this hook fired.

    Deliberately records NO prompt text and NO paths. The hook payload carries
    the operator's literal prompt and cwd, and this channel pulled a 48-file
    drop for operator PII on 2026-09-06; a log persisting either would be a new
    disclosure surface on every keystroke.

    Never raises. A logger that failed would convert a working hook into a
    broken one, which is strictly worse than having no log at all.
    """
    try:
        p = Path(path) if path is not None else invocation_log_path()
        has_payload = isinstance(payload, dict) and bool(payload)
        declared = payload.get("hook_event_name") if isinstance(payload, dict) else None
        sid = payload.get("session_id") if isinstance(payload, dict) else None
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": str(declared or event)[:_FIELD_MAX],
            "source": _hook_source(payload),
            # Distinguishes a real hook fire from an operator running this file
            # by hand. Both reach this function; only one answers the question.
            "payload": has_payload,
            # Which of none / tty / empty / json / notdict / error produced the
            # payload above. Turns "payload=false" from a dead end into a
            # diagnosis on the next real fire.
            "stdin": str(stdin_state)[:_FIELD_MAX],
            "session": str(sid)[:_FIELD_MAX] if isinstance(sid, str) else None,
            "pid": os.getpid(),
        }
        _append_atomic(p, (json.dumps(rec, separators=(",", ":")) + "\n").encode("utf-8"))
        _trim_invocation_log(p)
    except Exception:  # noqa: BLE001 - narrowing risks missing one and breaking a hook
        pass  # a hook must never fail the turn


if __name__ == "__main__":
    if "--mark-inbox-seen" in sys.argv:
        sys.exit(mark_inbox_seen())
    # Wired here rather than inside the probe functions so there is exactly one
    # place mapping an entrypoint to a hook event. --mark-inbox-seen records
    # nothing on purpose: it is a deliberate operator act, not a hook firing.
    _payload, _why = _read_hook_payload_with_reason()
    # No validated session id means fail OPEN: print exactly as before and
    # write nothing, neither the record nor the report file.
    _sid = _session_id(_payload)
    if "--inbox-only" in sys.argv:
        record_invocation("UserPromptSubmit", _payload, stdin_state=_why)
        sys.exit(report_inbox_only(session=_sid))
    record_invocation("SessionStart", _payload, stdin_state=_why)
    sys.exit(main(session=_sid))
