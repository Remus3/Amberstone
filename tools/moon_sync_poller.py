#!/usr/bin/env python
r"""ONE machine-wide poller for the cross-repo inbox channel, with idle backoff.

WHY ONE AND NOT FIVE. Five repos share this channel and each already has a
session hook that reads its own inbox. Those hooks only fire when that repo has
a live session, so mail addressed to a repo nobody is sitting in goes unseen
until someone happens to open it. Five independent pollers would fix that and
cost five wakeups per interval for one shared question. This is a single
process holding a single timer that answers the question for all five.

THE LADDER. The interval is derived from how long the machine has been idle,
where "idle" is the later of (a) the last mouse or keyboard input anywhere on
the desktop, and (b) the last session prompt in ANY participating repo. Any
input, or any prompt, drops it straight back to the base rate.

    idle <  20m   ->  poll every  5 minutes   (at the keyboard)
    idle >= 20m   ->  poll every 30 minutes   (stepped away)
    idle >=  4h   ->  poll every  4 hours     (gone for the evening)
    idle >= 24h   ->  poll every 12 hours     (unattended for a day)

FOUR WIDE STEPS RATHER THAN FIVE NARROW ONES. The first sketch of this ladder
had a 10 minute tier that applied between 15 and 25 minutes of idle - a step
that existed for ten minutes and saved a single poll. A tier only earns its
place if the machine can plausibly sit in it for a while. The cost being
managed here is churn on an idle box, not compute: a poll is a few hundred
milliseconds over five small directories, so backing off aggressively buys
very little and costs responsiveness.

The tier is derived from the idle duration rather than tracked as state. A
stateful ladder has to be unwound correctly on every reset path and drifts the
moment one is missed; a pure function of idle time is self-correcting, and a
poller waking after the machine slept computes the right tier immediately
instead of walking back down one step at a time.

THE TIER DECIDES WHEN TO ACT, NEVER HOW LONG TO SLEEP. This is the defect that
matters, and the obvious implementation has it: `time.sleep(interval)` at the
12 hour tier means the operator returns in the morning, the ladder correctly
resets to 5 minutes, and then nothing consults it for another half a day. The
loop instead wakes every TICK_SECONDS, recomputes the tier, and acts only when
the interval has elapsed - so a reset is honoured within a minute at any tier
while an idle machine still does real work only on the slow cadence.

IT REPORTS, IT NEVER ACKNOWLEDGES. The poller keeps its OWN per-repo seen set
in shared state so it does not re-notify about the same mail. It never touches
any repo's own watcher state. A sibling repo measured the opposite design this
week: their session hook marked mail seen, the hook fires for every subagent
start, so their first subagent marked the operator's queue read and the
operator's own session then honestly reported "nothing new". Reporting and
acknowledging must stay separate acts, and this process only ever does the
first.

NO HARDCODED HOME PATH. Shared state lives under %LOCALAPPDATA%, resolved at
runtime. A sibling raised hardcoded account names and home paths as a hygiene
problem across all five trees this week; this module does not add another.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rc_facts import _entry_name, _inbox_entries  # noqa: E402

BASE_SECONDS = 5 * 60

# Wake this often regardless of tier. See run() - the tier sets when we ACT,
# never how long we are unconscious for.
TICK_SECONDS = 60

TIERS: tuple[tuple[float, int], ...] = (
    # (idle seconds at or above which this applies, poll interval seconds)
    (0, 5 * 60),            # at the keyboard
    (20 * 60, 30 * 60),     # stepped away
    (4 * 60 * 60, 4 * 60 * 60),    # gone for the evening
    (24 * 60 * 60, 12 * 60 * 60),  # machine unattended for a day
)

DEFAULT_REPOS: tuple[str, ...] = (
    r"C:\Riot Commander",
    r"C:\Sibling-A",
    r"C:\Sibling-B",
    r"C:\Sibling-E",
    r"C:\Sibling-D",
)

# Opaque by intent, matching the convention of the shared mutex module: a
# descriptive machine-wide name is both an invitation to squat it and a
# statement about what runs on this box.
_SINGLETON_MUTEX = "Global\\MS-7f3a1c04-poll"


def state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMP") or "."
    d = Path(base) / "moonsync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- idle probe


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def input_idle_seconds() -> float | None:
    """Seconds since the last mouse or keyboard input, desktop-wide.

    Returns None off Windows or if the call fails, which callers must treat as
    "unknown", never as "idle". Reporting unknown as idle would let a failed
    probe silently escalate the poller to a 12 hour interval.

    NOTE: GetLastInputInfo is per SESSION. A service running in session 0 sees
    no input and would always look idle, which is exactly why this ships as a
    logon task in the operator's own session rather than as a service.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount64()
        return max(0.0, (tick - info.dwTime) / 1000.0)
    except (AttributeError, OSError):
        return None


def last_prompt_epoch() -> float:
    """Newest session-prompt ping from any participating repo."""
    p = state_dir() / "activity.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0
    stamps = [v for v in d.get("repos", {}).values() if isinstance(v, (int, float))]
    return max(stamps) if stamps else 0.0


def effective_idle_seconds(now: float | None = None) -> float:
    """Idle time counted from the LATER of desktop input and any repo prompt.

    A prompt is activity even when it arrived through a pasted hand-off with
    no mouse movement, and desktop input is activity even when no session is
    open. Taking the later of the two is what makes one timer correct for five
    repos plus the human.
    """
    now = time.time() if now is None else now
    since_prompt = now - last_prompt_epoch() if last_prompt_epoch() else float("inf")
    since_input = input_idle_seconds()
    if since_input is None:
        return since_prompt  # unknown input: fall back to prompts alone
    return min(since_input, since_prompt)


def interval_for(idle_seconds: float) -> int:
    """Poll interval for an idle duration. Pure, so it is trivially testable."""
    chosen = TIERS[0][1]
    for threshold, seconds in TIERS:
        if idle_seconds >= threshold:
            chosen = seconds
    return chosen


# ------------------------------------------------------------------ scanning


def ping(repo: str) -> int:
    """Record a session prompt for `repo`, resetting the shared ladder."""
    p = state_dir() / "activity.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("repos", {})[repo] = time.time()
    d["updated"] = _utcnow()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(p)
    return 0


def _load_seen() -> dict[str, list[str]]:
    p = state_dir() / "poller_seen.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("repos", {})
    except (OSError, ValueError):
        return {}


def _save_seen(seen: dict[str, list[str]]) -> None:
    p = state_dir() / "poller_seen.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"updated": _utcnow(), "repos": seen}, indent=2), encoding="utf-8"
    )
    tmp.replace(p)


def scan_once(repos: tuple[str, ...] = DEFAULT_REPOS) -> dict[str, dict[str, list[str]]]:
    """Report new and withdrawn inbox entries per repo, against the POLLER's
    own seen set. Never reads or writes any repo's own watcher state."""
    seen_all = _load_seen()
    findings: dict[str, dict[str, list[str]]] = {}
    for repo in repos:
        inbox = Path(repo) / "moon_sync_inbox"
        if not inbox.is_dir():
            continue
        names = _inbox_entries(inbox)

        # FIRST SIGHT OF A REPO IS A BASELINE, NOT NEWS. Without this the very
        # first run reports every note the channel has ever carried - the real
        # first run emitted hundreds across five repos - and a report that long
        # is one nobody reads, which defeats the poller on the single occasion
        # it most needs to be trusted. The same applies to a repo joining the
        # channel later. A repo whose inbox legitimately empties keeps its
        # (empty) entry, so this cannot silently re-baseline an active one.
        if repo not in seen_all:
            seen_all[repo] = sorted(names)
            continue

        prev = set(seen_all[repo])
        live = {_entry_name(k) for k in names}
        new = sorted(names - prev)
        gone = sorted({_entry_name(k) for k in prev} - live)
        if new or gone:
            findings[repo] = {"new": new, "withdrawn": gone}
        seen_all[repo] = sorted(names)
    _save_seen(seen_all)
    return findings


def write_status(findings: dict, idle: float, interval: int) -> Path:
    lines = [
        "# moon_sync cross-repo poller",
        "",
        f"- checked: {_utcnow()}",
        f"- desktop+prompt idle: {int(idle)}s",
        f"- next interval: {interval}s",
        "",
    ]
    if not findings:
        lines.append("No new or withdrawn inbox entries in any participating repo.")
    else:
        for repo, d in sorted(findings.items()):
            lines.append(f"## {repo}")
            for n in d["new"]:
                lines.append(f"- NEW: {n}")
            for n in d["withdrawn"]:
                lines.append(f"- WITHDRAWN: {n}")
            lines.append("")
    p = state_dir() / "status.md"
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


_ERROR_ALREADY_EXISTS = 183

# Held for process lifetime. The mutex is released when the handle closes, so
# the handle must outlive the acquiring function - a local would be fine while
# the process lives, but keeping it at module scope makes the intent explicit
# and stops a future refactor from "tidying up" the only thing holding it.
_singleton_handle = None


def _acquire_singleton(name: str | None = None) -> bool:
    """One poller per machine. Deliberately NOT via the shared mutex module -
    that file is byte-pinned across repos and adding a name to it is a joint
    re-pin round with every loop stopped.

    THE ERROR CHECK MUST USE ctypes.get_last_error(), NOT
    ctypes.windll.kernel32.GetLastError(). The `windll` cache does not set
    `use_last_error`, and calling GetLastError as a separate FFI call reads a
    thread error code the ctypes machinery has already reset, so it reliably
    returns 0. The guard then reported "acquired" for every caller and the
    singleton admitted an unbounded number of pollers.

    That is not theory: it shipped for about ten minutes here and produced a
    genuinely confusing bug. Several pollers ran concurrently, each with its
    own poll clock, so the shared status file was rewritten by whichever
    process happened to be due - which presented as a task that was Running
    with a live pid while its status file went stale, and as a deleted status
    file that existed again a second later. The symptom looked like a
    scheduled-task environment problem and was a one-line FFI mistake.
    """
    global _singleton_handle
    if not sys.platform.startswith("win"):
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, True, name or _SINGLETON_MUTEX)
        err = ctypes.get_last_error()
        if not handle:
            return False
        if err == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _singleton_handle = handle
        return True
    except (AttributeError, OSError):
        # Never let a probe failure stop the poller from running at all; a
        # duplicate poller is a far smaller problem than no poller.
        return True


def run(repos: tuple[str, ...] = DEFAULT_REPOS, once: bool = False) -> int:
    if not once and not _acquire_singleton():
        print("another poller already holds the singleton; exiting")
        return 0
    log = state_dir() / "poller.log"

    # BOOT MARKER. A background daemon that says nothing on start is one you
    # cannot tell apart from a daemon that started and wedged - which is
    # exactly the state this hit during development: Task Scheduler reported
    # the task Running with a live pid while the status file went stale, and
    # a manually launched process with byte-identical arguments behaved fine.
    # Guessing at that costs more than one line of log per start.
    try:
        with log.open("a", encoding="utf-8") as fh:
            fh.write(
                f"{_utcnow()} BOOT pid={os.getpid()} state={state_dir()} "
                f"idle_probe={'ok' if input_idle_seconds() is not None else 'UNAVAILABLE'} "
                f"repos={len(repos)}\n"
            )
    except OSError:
        pass

    last_poll = 0.0
    while True:
        now = time.time()
        idle = effective_idle_seconds(now)
        interval = interval_for(idle)

        # ACT when due, rather than sleeping for the whole interval. A committed
        # time.sleep(12h) cannot notice that the operator came back: the ladder
        # would reset correctly and then not be consulted for half a day, so
        # mail arriving during an active morning stays invisible because the
        # machine happened to be idle overnight. Ticking short and recomputing
        # the tier every tick means a reset takes effect within TICK_SECONDS at
        # ANY tier, while an idle machine still only does real work on the slow
        # cadence. The tier decides when we act; it never decides how long we
        # are unconscious for.
        if now - last_poll >= interval:
            last_poll = now
            findings = scan_once(repos)
            write_status(findings, idle, interval)
            total = sum(len(d["new"]) + len(d["withdrawn"]) for d in findings.values())
            # Heartbeat EVERY poll, not only when something is found. A log
            # that is silent on a quiet channel cannot distinguish "nothing
            # arrived" from "the poller stopped polling", and those are the
            # two states it exists to tell apart.
            try:
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(f"{_utcnow()} poll idle={int(idle)}s next={interval}s "
                             f"findings={total}"
                             f"{' repos=' + str(sorted(findings)) if findings else ''}\n")
            except OSError:
                pass
        if once:
            return 0
        time.sleep(min(TICK_SECONDS, interval))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-repo inbox poller with idle backoff.")
    ap.add_argument("--ping", metavar="REPO",
                    help="record a session prompt for REPO and exit (resets the ladder)")
    ap.add_argument("--once", action="store_true", help="one scan, then exit")
    ap.add_argument("--status", action="store_true", help="print current tier and exit")
    ap.add_argument("--repo", action="append", default=None,
                    help="participating repo root (repeatable); defaults to all five")
    args = ap.parse_args(argv)

    if args.ping:
        return ping(args.ping)
    repos = tuple(args.repo) if args.repo else DEFAULT_REPOS
    if args.status:
        idle = effective_idle_seconds()
        print(f"idle={int(idle)}s interval={interval_for(idle)}s state={state_dir()}")
        return 0
    return run(repos, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
