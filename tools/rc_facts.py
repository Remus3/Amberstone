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

Run manually any time:  C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/rc_facts.py
"""
from __future__ import annotations

import hashlib
import json
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

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


def main() -> int:
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
    try:
        inbox = _ROOT / "moon_sync_inbox"
        seen_path = _ROOT / "ops" / "runtime" / "sync_inbox_seen.json"
        if inbox.is_dir():
            names = _inbox_entries(inbox)
            try:
                seen = set(json.loads(seen_path.read_text(encoding="utf-8")).get("seen", []))
            except (OSError, ValueError):
                seen = set()
            unread = sorted(names - seen)
            withdrawn = _inbox_withdrawn(names, seen)
            if unread:
                anomalies.append(
                    f"moon_sync_inbox: {len(unread)} unread note(s) from sibling repos")
                out.append("")
                out.append(f"## Cross-repo inbox - {len(unread)} UNREAD")
                for n in unread[:10]:
                    out.append(f"- {n}")
                if len(unread) > 10:
                    out.append(f"- ... and {len(unread) - 10} more")
            if withdrawn:
                anomalies.append(
                    f"moon_sync_inbox: {len(withdrawn)} entry(s) WITHDRAWN by a sibling")
                out.append("")
                out.append(f"## Cross-repo inbox - {len(withdrawn)} WITHDRAWN since last ack")
                for n in withdrawn[:10]:
                    out.append(f"- {n}")
                if len(withdrawn) > 10:
                    out.append(f"- ... and {len(withdrawn) - 10} more")
            if unread or withdrawn:
                out.append("Read them, then record them as seen:")
                out.append("  python tools/rc_facts.py --mark-inbox-seen")
    except OSError:
        pass  # a hook must never fail the session start

    # -- Anomaly summary first if any ------------------------------------
    if anomalies:
        head = "## ! Anomalies\n\n" + "\n".join(f"- {a}" for a in anomalies) + "\n\n"
        sys.stdout.write(head)
    sys.stdout.write("\n".join(out) + "\n")
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
    """
    files = sorted((f for f in p.rglob("*") if f.is_file()), key=lambda f: f.as_posix())
    lines = [
        f"{f.relative_to(p).as_posix()}\0{_file_digest(f)}".encode("utf-8", "surrogateescape")
        for f in files
    ]
    digest = hashlib.sha256(b"\n".join(lines)).hexdigest()[:12]
    manifest = next(
        (n for n in ("MANIFEST.sha256", "MANIFEST.txt", "manifest.json") if (p / n).is_file()),
        None,
    )
    tail = f", {manifest} present" if manifest else ""
    return f"[{len(files)} files, content {digest}{tail}]"


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


def mark_inbox_seen() -> int:
    """Record every current inbox note as seen. Idempotent.

    Separate from the hook on purpose: the hook REPORTS, the operator (or the
    session, once it has actually read them) ACKNOWLEDGES. Advancing the
    watermark inside the hook is the failure this design avoids - see the note
    in main().
    """
    inbox = _ROOT / "moon_sync_inbox"
    seen_path = _ROOT / "ops" / "runtime" / "sync_inbox_seen.json"
    names = sorted(_inbox_entries(inbox)) if inbox.is_dir() else []
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = seen_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"seen": names}, indent=2), encoding="utf-8")
    tmp.replace(seen_path)
    print(f"recorded {len(names)} inbox note(s) as seen -> {seen_path}")
    return 0


def report_inbox_only() -> int:
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
    """
    try:
        inbox = _ROOT / "moon_sync_inbox"
        if not inbox.is_dir():
            return 0
        seen_path = _ROOT / "ops" / "runtime" / "sync_inbox_seen.json"
        names = _inbox_entries(inbox)
        try:
            seen = set(json.loads(seen_path.read_text(encoding="utf-8")).get("seen", []))
        except (OSError, ValueError):
            seen = set()
        unread = sorted(names - seen)
        withdrawn = _inbox_withdrawn(names, seen)
        if not unread and not withdrawn:
            return 0
        if unread:
            print(f"## Cross-repo inbox - {len(unread)} UNREAD (checked this message)")
            for n in unread[:10]:
                print(f"- {n}")
            if len(unread) > 10:
                print(f"- ... and {len(unread) - 10} more")
        if withdrawn:
            print(f"## Cross-repo inbox - {len(withdrawn)} WITHDRAWN since last ack")
            for n in withdrawn[:10]:
                print(f"- {n}")
            if len(withdrawn) > 10:
                print(f"- ... and {len(withdrawn) - 10} more")
        print("Read them, then: python tools/rc_facts.py --mark-inbox-seen")
    except OSError:
        pass  # a hook must never fail the turn
    return 0


if __name__ == "__main__":
    if "--mark-inbox-seen" in sys.argv:
        sys.exit(mark_inbox_seen())
    if "--inbox-only" in sys.argv:
        sys.exit(report_inbox_only())
    sys.exit(main())
