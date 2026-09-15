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

THE WRITTEN INTERVAL IS A PROMISE. status.md publishes "next interval" and an
absolute "expect next poll by", and a reader grades the poller against them.
Recomputing the tier every tick means a climb between two polls (the operator
stepping away) would legitimately push the next poll out to the NEW interval
while the file still promised the OLD one, so a perfectly healthy poller reads
OVERDUE and then STALE for as long as the climb lasts. The loop therefore polls
at min(recomputed interval, the interval it last PROMISED). The cost is at most
one extra scan per tier climb; the benefit is that a loud state stays rare
enough to be believed.

IT REPORTS, IT NEVER ACKNOWLEDGES. The poller keeps its OWN per-repo seen set
in shared state so it does not re-notify about the same mail. It never touches
any repo's own watcher state. A sibling repo measured the opposite design this
week: their session hook marked mail seen, the hook fires for every subagent
start, so their first subagent marked the operator's queue read and the
operator's own session then honestly reported "nothing new". Reporting and
acknowledging must stay separate acts, and this process only ever does the
first.

WHAT status.md ANSWERS, AND WHAT IT DOES NOT. It answers: what arrived and what
was withdrawn in each participating repo since THIS poller's own baseline, per
participant CODE, with the newest few names and a pointer to findings.json for
the rest; and whether the poller itself is alive, via the poll stamp, the pid
and the absolute "expect next poll by". It does NOT answer per-repo ACK DEBT -
how much of a repo's inbox that repo's own watcher has not acknowledged. That
would mean reading four private, unpinned runtime stores, which is a separate
decision with its own gate; the promise above stays true precisely because this
file never opens one.

CODES, NEVER PATHS. Every rendered surface names a participant by its short
code from the gitignored host config. A sibling checkout path is per-host
configuration that names a private project, and a rendered path is one copy
away from a public tree.

NO HARDCODED HOME PATH. Shared state lives under %LOCALAPPDATA%, resolved at
runtime, with RC_MOON_SYNC_STATE as an explicit override. A sibling raised
hardcoded account names and home paths as a hygiene problem across all five
trees this week; this module does not add another.

THE PING WRITES UNDER THE REPO ROOT. It used to write into the shared state
dir, which is fine for a process launched by the scheduler and wrong for one
launched by a packaged desktop app: such a process carries MSIX package
identity, and its AppData writes land in the package's LocalCache twin, which
then shadows the real file for every later read from that harness. Repo roots
are not virtualised, so the ping goes there and the ladder's prompt half is
true again for every launcher.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
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
    (0, 5 * 60),  # at the keyboard
    (20 * 60, 30 * 60),  # stepped away
    (4 * 60 * 60, 4 * 60 * 60),  # gone for the evening
    (24 * 60 * 60, 12 * 60 * 60),  # machine unattended for a day
)

# The participating repos are HOST CONFIGURATION, not code. Which sibling
# checkouts exist, and where, differs per machine and names private projects
# that have no business in a public tree - so the list is read from a
# gitignored config beside the other per-host values, with this repo as the
# only built-in. An absent or unreadable config degrades to "poll myself",
# which is exactly what a fresh clone should do.
_REPO_CONFIG = Path(__file__).parent.parent / "ops" / "moon_sync_repos.json"
_SELF_REPO = str(Path(__file__).parent.parent)

# Rendering bounds. rc_facts carries no display constant this module may reuse
# (its MAX_DISPLAY_CHARS belongs to a different surface), so the poller defines
# its own and a test pins the cap.
STATUS_NAME_MAX = 120
STATUS_NAMES_PER_CODE = 3
STATUS_MAX_BYTES = 4096

# The findings ledger is a bounded window, never an append log.
FINDINGS_WINDOW_SECONDS = 7 * 24 * 60 * 60
FINDINGS_PER_CODE = 200

_RUNTIME_REL = ("ops", "runtime")
_PING_NAME = "moon_sync_activity.json"
_INVOCATION_LOG = "hook_invocations.jsonl"

_DIGEST12_RE = re.compile(r"\[([0-9a-fA-F]{12})\]\s*$")


def _load_repo_roots() -> tuple[str, ...]:
    roots: list[str] = [_SELF_REPO]
    raw = os.environ.get("RC_MOON_SYNC_REPOS")
    if raw:
        extra = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    else:
        try:
            blob = json.loads(_REPO_CONFIG.read_text(encoding="utf-8"))
            extra = [str(p) for p in (blob.get("repos") or []) if str(p).strip()]
        except (OSError, ValueError, AttributeError):
            extra = []
    for p in extra:
        if p not in roots:
            roots.append(p)
    return tuple(roots)


def _norm_root(path: str) -> str:
    """The comparison form of a repo root. Case and separators differ freely
    between the config, the hook argument and a Path round trip."""
    return os.path.normcase(os.path.normpath(str(path)))


def _load_participants() -> dict[str, str]:
    """{normalised root -> CODE} from the gitignored host config.

    The `participants` key already exists for the inbox responder; this reads
    it so nothing rendered has to name a path. This repo maps to RC unless the
    config says otherwise.
    """
    raw: object = {}
    try:
        blob = json.loads(_REPO_CONFIG.read_text(encoding="utf-8"))
        raw = blob.get("participants") or {}
    except (OSError, ValueError, AttributeError):
        raw = {}
    mapping: dict[str, str] = {}
    if isinstance(raw, dict):
        for code, path in raw.items():
            if isinstance(path, str) and path.strip():
                mapping[_norm_root(path)] = str(code)
    mapping.setdefault(_norm_root(_SELF_REPO), "RC")
    return mapping


DEFAULT_REPOS: tuple[str, ...] = _load_repo_roots()
DEFAULT_PARTICIPANTS: dict[str, str] = _load_participants()

# Roots with no code get a stable placeholder for the life of the process. The
# leaf name is NEVER used: a checkout directory name is exactly the thing that
# must not reach a rendered surface.
_UNMAPPED_INDEX: dict[str, int] = {}


def code_for(root: str, participants: dict[str, str] | None = None) -> str:
    participants = _load_participants() if participants is None else participants
    key = _norm_root(root)
    code = participants.get(key)
    if code:
        return str(code)
    if key not in _UNMAPPED_INDEX:
        _UNMAPPED_INDEX[key] = len(_UNMAPPED_INDEX) + 1
    return f"UNMAPPED-{_UNMAPPED_INDEX[key]}"


# Opaque by intent, matching the convention of the shared mutex module: a
# descriptive machine-wide name is both an invitation to squat it and a
# statement about what runs on this box.
_SINGLETON_MUTEX = "Global\\MS-7f3a1c04-poll"


def _state_dir_path() -> Path:
    """Where shared state LIVES. Creates nothing.

    Readers use this form so that a command run from a harness shell - which
    may carry package identity - never performs a directory write under
    AppData. Writers call state_dir(), which is this plus the mkdir.
    """
    override = os.environ.get("RC_MOON_SYNC_STATE")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMP") or "."
    return Path(base) / "moonsync"


def state_dir() -> Path:
    d = _state_dir_path()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _parse_iso(text: str) -> float | None:
    try:
        return datetime.fromisoformat(str(text).strip()).timestamp()
    except (ValueError, TypeError):
        return None


def _exc_label(exc: BaseException) -> str:
    """The BASE exception name a reader can act on.

    json.JSONDecodeError is a ValueError, and a status line naming the concrete
    subclass makes two spellings of the same condition. Report the family.
    """
    for base in (ValueError, OSError, KeyError, TypeError):
        if isinstance(exc, base) and type(exc) is not base:
            return base.__name__
    return type(exc).__name__


# os.replace raises PermissionError (WinError 5) on Windows while any reader
# holds the target open, and this module now has readers: the --status command
# and the dashboard route both open exactly these files. The bounded backoff is
# copied from core/polled_json.py rather than imported - nothing from core/ may
# join this file's import path, because an import-time fault there would kill
# every poller restart and this process is the only one watching the channel.
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


def _atomic_write(target: Path, text: str) -> None:
    """tmp then replace, with LF held.

    newline="\\n" is load-bearing, not hygiene: the default translates every LF
    to CRLF on Windows, so the bytes on disk are larger than the bytes the size
    cap measured and a render that fits in memory can overflow the file bound.
    """
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    _replace_with_retry(tmp, target)


def _log_line(text: str) -> None:
    try:
        with (state_dir() / "poller.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{_utcnow()} {text}\n")
    except OSError:
        pass


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


def _ping_path(root: str) -> Path:
    return Path(root).joinpath(*_RUNTIME_REL) / _PING_NAME


def _legacy_prompt_epoch() -> float:
    """The pre-move shared activity.json. READ ONLY.

    It still carries the last stamp any non-repo-root pinger wrote, so dropping
    it would reset the ladder's history to zero on the day the ping moved.
    """
    p = _state_dir_path() / "activity.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        stamps = [v for v in (d.get("repos") or {}).values() if isinstance(v, (int, float))]
    except (OSError, ValueError, AttributeError):
        return 0.0
    return float(max(stamps)) if stamps else 0.0


def _self_prompt_epoch(self_root: str) -> float:
    try:
        d = json.loads(_ping_path(self_root).read_text(encoding="utf-8"))
        stamp = d.get("stamp")
    except (OSError, ValueError, AttributeError):
        return 0.0
    return float(stamp) if isinstance(stamp, (int, float)) else 0.0


def last_prompt_epoch(self_root: str | None = None) -> float:
    """Newest session-prompt ping visible to this process.

    The max over the legacy shared file and THIS repo's own root ping. No
    sibling root is read: a sibling's ops/runtime is its private gitignored
    state, and reading one to make a claim about it is the boundary this
    channel already declined to cross.

    `self_root` resolves at CALL time on purpose. A default bound at def time
    is invisible to a monkeypatch, and effective_idle_seconds calls this bare -
    so a test fixture patching the module constant would silently measure the
    real machine instead of its own fixture.
    """
    root = _SELF_REPO if self_root is None else self_root
    stamps = [_legacy_prompt_epoch(), _self_prompt_epoch(root)]
    best = max(stamps)
    return best if best > 0 else 0.0


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


def _newest_prompt_invocation(self_root: str) -> float | None:
    """Newest UserPromptSubmit hook fire that carried a real payload.

    The filter matters. record_invocation writes SessionStart and every other
    hook fire into the same log, so an unfiltered read reports a dead prompt
    half for any session that started and has not yet prompted. The log's `ts`
    is naive LOCAL time, so it is parsed against the local clock; the autumn
    fall-back hour is one hour of slack in a detector whose threshold is a
    minute, which is acceptable and is why this is a tell and not a gate.
    """
    p = Path(self_root).joinpath(*_RUNTIME_REL) / _INVOCATION_LOG
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    best: float | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("event") != "UserPromptSubmit" or rec.get("payload") is not True:
            continue
        try:
            epoch = time.mktime(time.strptime(str(rec.get("ts")), "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, OverflowError):
            continue
        if best is None or epoch > best:
            best = epoch
    return best


def prompt_half(now: float | None = None, self_root: str | None = None) -> tuple[str, bool]:
    """(rendered text, dead) for the prompt arm of the ladder.

    DEAD means the hook log records a prompt newer than every ping stamp by
    more than one tick: something is telling the ladder about prompts it cannot
    see. Computed on EVERY poll rather than only in --status, because a
    detector that lives only in a command nobody runs leaves the ladder reading
    healthy on both surfaces while it climbs to the 12 hour tier.
    """
    now = time.time() if now is None else now
    root = _SELF_REPO if self_root is None else self_root
    repo_stamp = _self_prompt_epoch(root)
    legacy_stamp = _legacy_prompt_epoch()
    best = max(repo_stamp, legacy_stamp)
    if best <= 0:
        source = "none"
        text = "last ping never via none"
    else:
        source = "repo-root" if repo_stamp >= legacy_stamp else "legacy"
        text = f"last ping {int(now - best)}s via {source}"
    newest = _newest_prompt_invocation(root)
    dead = newest is not None and newest > best + TICK_SECONDS
    return (text + " DEAD") if dead else text, dead


# ------------------------------------------------------------------ scanning


def ping(repo: str) -> int:
    """Record a session prompt for `repo`, resetting the shared ladder.

    Writes under the REPO ROOT, never the shared state dir - see the module
    docstring. Fails open in every direction: an absent root writes nothing
    rather than creating an arbitrary directory, and any OSError is swallowed,
    because this runs as a UserPromptSubmit hook and a non-zero exit there is
    a broken turn in exchange for a stamp nobody is waiting on.
    """
    try:
        root = Path(repo)
        if not root.is_dir():
            return 0
        target = _ping_path(repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"stamp": time.time(), "updated": _utcnow()}, indent=2)
        tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
        tmp.write_text(payload, encoding="utf-8")
        _replace_with_retry(tmp, target)
    except OSError:
        return 0
    return 0


def _load_seen() -> dict[str, list[str]]:
    p = _state_dir_path() / "poller_seen.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("repos", {})
    except (OSError, ValueError, AttributeError):
        return {}


def _save_seen(seen: dict[str, list[str]]) -> None:
    p = state_dir() / "poller_seen.json"
    _atomic_write(p, json.dumps({"updated": _utcnow(), "repos": seen}, indent=2))


def _fleet_row(
    code: str, status: str, entries: int = 0, new: list[str] | None = None, withdrawn: list[str] | None = None
) -> dict:
    return {
        "code": code,
        "status": status,
        "entries": entries,
        "new": list(new or []),
        "withdrawn": list(withdrawn or []),
    }


def scan_fleet(repos: tuple[str, ...] | None = None, participants: dict[str, str] | None = None) -> dict:
    """One pass over the fleet: per-repo findings plus a renderable row each.

    Every repo is scanned inside its own try/except. A single unreadable tree
    used to take the whole poll down with it, and the loop that called it wraps
    nothing - so one junction in one inbox froze status.md on a reassuring line.
    An absent inbox is a LOUD row, not the silent skip it used to be: "nothing
    to say" and "there is nothing there" are the two states worth telling apart.
    """
    repos = DEFAULT_REPOS if repos is None else repos
    participants = _load_participants() if participants is None else participants
    seen_all = _load_seen()
    findings: dict[str, dict[str, list[str]]] = {}
    rows: list[dict] = []
    for repo in repos:
        code = code_for(repo, participants)
        try:
            inbox = Path(repo) / "moon_sync_inbox"
            if not inbox.is_dir():
                rows.append(_fleet_row(code, "INBOX ABSENT"))
                continue
            names = _inbox_entries(inbox)

            # FIRST SIGHT OF A REPO IS A BASELINE, NOT NEWS. Without this the
            # very first run reports every note the channel has ever carried -
            # the real first run emitted hundreds across five repos - and a
            # report that long is one nobody reads, which defeats the poller on
            # the single occasion it most needs to be trusted. The same applies
            # to a repo joining the channel later. A repo whose inbox
            # legitimately empties keeps its (empty) entry, so this cannot
            # silently re-baseline an active one.
            if repo not in seen_all:
                seen_all[repo] = sorted(names)
                rows.append(_fleet_row(code, "OK", len(names)))
                continue

            prev = set(seen_all[repo])
            live = {_entry_name(k) for k in names}
            new = sorted(names - prev)
            gone = sorted({_entry_name(k) for k in prev} - live)
            if new or gone:
                findings[repo] = {"new": new, "withdrawn": gone}
            seen_all[repo] = sorted(names)
            rows.append(_fleet_row(code, "OK", len(names), new, gone))
        except Exception as exc:  # noqa: BLE001 - one bad tree must not end the poll
            rows.append(_fleet_row(code, f"SCAN FAULT {type(exc).__name__}"))
    _save_seen(seen_all)
    return {"findings": findings, "rows": rows}


def scan_once(repos: tuple[str, ...] = DEFAULT_REPOS) -> dict[str, dict[str, list[str]]]:
    """Report new and withdrawn inbox entries per repo, against the POLLER's
    own seen set. Never reads or writes any repo's own watcher state.

    The legacy shape, kept byte-for-byte: a thin wrapper over scan_fleet.
    """
    return scan_fleet(repos)["findings"]


def _boot_rebaseline(
    now: float | None = None, repos: tuple[str, ...] | None = None, participants: dict[str, str] | None = None
) -> str | None:
    """Silence a restart against a store old enough to be meaningless.

    A poller restarting against a week-old seen set reports every note that
    arrived in the meantime, which is hundreds of lines nobody reads on exactly
    the run that most needs to be trusted. The threshold is TWICE the widest
    tier: the deep tier legitimately leaves a store 12 hours old, and a crash
    restart lands 5 minutes later, so 12 hours would re-baseline a routine
    restart and silently drop a real window.

    What it would have said is counted BEFORE the reset and carried in the one
    line, so the operator learns a window was dropped and how big it was. An
    unreadable store gets the same line with UNMEASURED - never the silent {}
    that _load_seen would otherwise hand the first scan, which is the same
    re-baseline through a quieter door.
    """
    now = time.time() if now is None else now
    repos = DEFAULT_REPOS if repos is None else repos
    participants = _load_participants() if participants is None else participants
    p = _state_dir_path() / "poller_seen.json"
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
        updated = _parse_iso(blob["updated"])
        if updated is None:
            raise ValueError("unparseable updated stamp")
        seen = blob.get("repos") or {}
    except FileNotFoundError:
        return None  # a fresh install is a legitimate silent baseline
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _save_seen({})
        return f"baseline reset at boot; persisted seen unreadable ({_exc_label(exc)}); would have reported: UNMEASURED"

    age = now - updated
    if age <= 2 * TIERS[-1][1]:
        return None

    per_code: list[str] = []
    total = 0
    for repo in repos:
        prev = seen.get(repo)
        if prev is None:
            continue
        try:
            inbox = Path(repo) / "moon_sync_inbox"
            names = _inbox_entries(inbox) if inbox.is_dir() else set()
        except Exception:  # noqa: BLE001 - the count is advisory, never fatal
            continue
        n = len(names - set(prev))
        if n:
            total += n
            per_code.append(f"{code_for(repo, participants)}:{n}")
    _save_seen({})
    detail = ", ".join(per_code) if per_code else "none"
    return (
        f"baseline reset at boot; persisted seen was {age / 86400.0:.1f} days old; "
        f"would have reported: {total} NEW per code {detail}; not itemised"
    )


# ---------------------------------------------------------- findings ledger


def _clip(name: str) -> str:
    if len(name) <= STATUS_NAME_MAX:
        return name
    return name[: STATUS_NAME_MAX - 3] + "..."


def _digest12(key: str) -> str | None:
    """The 12 hex digest inside a watcher key, or None for a directory payload.

    A directory entry carries a file count and a content digest in the same
    bracket, and the two are not comparable, so it renders as null rather than
    as a digest that means something else.
    """
    if _entry_name(key).endswith("/"):
        return None
    m = _DIGEST12_RE.search(key)
    return m.group(1) if m else None


def _entries_from_rows(rows: list[dict] | None, at_utc: str) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        code = row.get("code", "UNMAPPED")
        for kind, keys in (("NEW", row.get("new") or []), ("WITHDRAWN", row.get("withdrawn") or [])):
            for key in keys:
                out.append(
                    {
                        "code": code,
                        "name": _clip(_entry_name(key)),
                        "digest12": _digest12(key),
                        "kind": kind,
                        "at_utc": at_utc,
                    }
                )
    return out


def _read_findings() -> tuple[list[dict], str | None]:
    """(entries, failure label). An absent ledger is not a failure."""
    p = _state_dir_path() / "findings.json"
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
        rows = blob["findings"]
        if not isinstance(rows, list):
            raise TypeError("findings is not a list")
    except FileNotFoundError:
        return [], None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [], _exc_label(exc)
    return [r for r in rows if isinstance(r, dict)], None


def _bound(entries: list[dict], now: float) -> list[dict]:
    """Newest first, inside the window, at most FINDINGS_PER_CODE per code."""

    def key(row: dict) -> float:
        return _parse_iso(row.get("at_utc", "")) or 0.0

    ordered = sorted(entries, key=key, reverse=True)
    kept: list[dict] = []
    per_code: dict[str, int] = {}
    for row in ordered:
        if now - key(row) > FINDINGS_WINDOW_SECONDS:
            continue
        code = str(row.get("code", ""))
        if per_code.get(code, 0) >= FINDINGS_PER_CODE:
            continue
        per_code[code] = per_code.get(code, 0) + 1
        kept.append(row)
    return kept


def _record_findings(rows: list[dict] | None, now: float | None = None) -> None:
    """Rewrite the bounded ledger with this poll's rows folded in.

    REWRITTEN, never appended: O_APPEND is not atomic on Windows, and two
    writers interleaving inside one record is a corrupt line that the next read
    turns into an UNMEASURED window.
    """
    now = time.time() if now is None else now
    existing, _ = _read_findings()
    merged = _bound(_entries_from_rows(rows, _iso(now)) + existing, now)
    _atomic_write(state_dir() / "findings.json", json.dumps({"schema": 1, "findings": merged}, indent=2))


# -------------------------------------------------------------- status file


def _window_view(rows: list[dict] | None, now: float) -> tuple[dict, str | None]:
    """Per-code arrivals, withdrawals and newest names over the ledger window.

    This poll's rows are folded in before rendering, because _record_findings
    runs after the status write and the operator must not have to wait a poll
    to see what just arrived.
    """
    existing, failure = _read_findings()
    merged = _bound(_entries_from_rows(rows, _iso(now)) + existing, now)
    view: dict[str, dict] = {}
    for row in merged:
        code = str(row.get("code", ""))
        slot = view.setdefault(code, {"new": 0, "withdrawn": 0, "names": []})
        if row.get("kind") == "WITHDRAWN":
            slot["withdrawn"] += 1
        else:
            slot["new"] += 1
        slot["names"].append(str(row.get("name", "")))
    return view, failure


def _render_status(
    findings: dict,
    idle: float,
    interval: int,
    rows: list[dict] | None,
    boot_note: str | None,
    names_per_code: int,
    now: float,
    participants_absent: int,
    window: dict,
    window_failure: str | None,
    checked: str,
) -> str:
    half_text, _dead = prompt_half(now)
    lines = [
        "# moon_sync cross-repo poller",
        "",
        f"- checked: {checked}",
        f"- desktop+prompt idle: {int(idle)}s",
        f"- next interval: {interval}s",
        f"- pid: {os.getpid()}",
        f"- expect next poll by: {_iso(now + interval + 60)}",
    ]
    if boot_note:
        lines.append(f"- boot: {boot_note}")
    if participants_absent:
        lines.append(f"- participants map absent: {participants_absent} roots UNMAPPED")
    lines.append(f"- prompt half: {half_text}")
    if window_failure:
        lines.append(f"- findings: UNMEASURED ({window_failure})")
    lines.append("")

    lines.append("## Fleet")
    for row in rows or []:
        code = row["code"]
        status = row["status"]
        if status != "OK":
            lines.append(f"- {code}: {status}")
            continue
        slot = window.get(code, {"new": 0, "withdrawn": 0, "names": []})
        names = [_clip(n) for n in slot["names"][:names_per_code]]
        more = len(slot["names"]) - len(names)
        parts = [f"- {code}: {row['entries']} entries", f"+{slot['new']} -{slot['withdrawn']}"]
        if names:
            parts.append("newest: " + ", ".join(names))
        parts.append(f"+{more} more - findings.json")
        lines.append(", ".join(parts))
    lines.append("")

    if not findings:
        lines.append("No new or withdrawn inbox entries in any participating repo.")
    else:
        by_code: dict[str, dict] = {}
        for repo, d in findings.items():
            by_code.setdefault(code_for(repo), {"new": [], "withdrawn": []})
            by_code[code_for(repo)]["new"].extend(d["new"])
            by_code[code_for(repo)]["withdrawn"].extend(d["withdrawn"])
        for code, d in sorted(by_code.items()):
            lines.append(f"## {code}")
            shown = 0
            for kind in ("new", "withdrawn"):
                for n in d[kind][:names_per_code]:
                    lines.append(f"- {kind.upper()}: {_clip(_entry_name(n))}")
                    shown += 1
            hidden = len(d["new"]) + len(d["withdrawn"]) - shown
            if hidden > 0:
                lines.append(f"- +{hidden} more - findings.json")
            lines.append("")
    return "\n".join(lines) + "\n"


def _minimal_status_text(exc: BaseException) -> str:
    return (
        "\n".join(
            [
                "# moon_sync cross-repo poller",
                "",
                f"- checked: {_utcnow()}",
                f"- pid: {os.getpid()}",
                f"- fault: {type(exc).__name__}",
                "",
            ]
        )
        + "\n"
    )


def _write_minimal_status(exc: BaseException) -> Path:
    """The file must ALWAYS advance. A frozen reassuring line is the one state
    a liveness surface may never present."""
    p = state_dir() / "status.md"
    try:
        _atomic_write(p, _minimal_status_text(exc))
    except OSError as err:
        _log_line(f"FAULT {type(err).__name__}")
    return p


def write_status(
    findings: dict, idle: float, interval: int, rows: list[dict] | None = None, boot_note: str | None = None
) -> Path:
    """Render the persistent fleet view. The 3-arg call shape is load-bearing."""
    p = state_dir() / "status.md"
    try:
        now = time.time()
        # checked and "expect next poll by" MUST come from the same clock, or a
        # reader comparing the two grades a healthy poller OVERDUE forever.
        checked = _iso(now)
        window, failure = _window_view(rows, now)
        absent = sum(1 for r in (rows or []) if str(r.get("code", "")).startswith("UNMAPPED-"))
        text = ""
        for names_per_code in range(STATUS_NAMES_PER_CODE, -1, -1):
            text = _render_status(
                findings, idle, interval, rows, boot_note, names_per_code, now, absent, window, failure, checked
            )
            if len(text.encode("utf-8")) <= STATUS_MAX_BYTES:
                break
    except Exception as exc:  # noqa: BLE001 - a render fault still owes a file
        return _write_minimal_status(exc)
    try:
        _atomic_write(p, text)
    except OSError as exc:
        _log_line(f"FAULT {type(exc).__name__}")
    return p


def parse_status_header(text: str) -> dict:
    """Every header fact the writer emits, so no fault can hide behind LIVE."""
    h: dict = {
        "checked": None,
        "interval": None,
        "pid": None,
        "expect_next_poll_by": None,
        "fleet_view": False,
        "fault": None,
        "boot": None,
        "unmapped_roots": 0,
        "prompt_half": None,
        "prompt_half_dead": False,
    }
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        if body.startswith("checked: "):
            h["checked"] = _parse_iso(body[9:])
        elif body.startswith("next interval: "):
            try:
                h["interval"] = int(body[15:].strip().rstrip("s"))
            except ValueError:
                h["interval"] = None
        elif body.startswith("pid: "):
            h["fleet_view"] = True
            try:
                h["pid"] = int(body[5:].strip())
            except ValueError:
                h["pid"] = None
        elif body.startswith("expect next poll by: "):
            h["expect_next_poll_by"] = _parse_iso(body[21:])
        elif body.startswith("fault: "):
            h["fault"] = body[7:].strip()
        elif body.startswith("boot: "):
            h["boot"] = body[6:].strip()
        elif body.startswith("participants map absent: "):
            try:
                h["unmapped_roots"] = int(body[25:].split()[0])
            except (ValueError, IndexError):
                h["unmapped_roots"] = 0
        elif body.startswith("prompt half: "):
            h["prompt_half"] = body[13:].strip()
            h["prompt_half_dead"] = h["prompt_half"].endswith("DEAD")
    if h["expect_next_poll_by"] is None and h["checked"] is not None and h["interval"]:
        h["expect_next_poll_by"] = h["checked"] + h["interval"] + 60
    return h


def status_verdict(header: dict, now: float, pid_alive: bool | None) -> str:
    """The ONE grading rule, shared by every reader of status.md.

    FAULT comes FIRST. A file carrying a fault line has a fresh stamp and a
    live pid by construction - the fault is exactly what stopped it saying
    anything else - so any time-first rule grades a broken poller LIVE with an
    empty fleet. pid_alive None means "could not be determined", never dead:
    the poller runs under the scheduler and a reader may simply lack the right
    to query it, and fabricating DEAD from a permissions answer is worse than
    falling back to the time rule.
    """
    if header.get("fault"):
        return "FAULT"
    if pid_alive is False:
        return "DEAD"
    checked = header.get("checked")
    expect = header.get("expect_next_poll_by")
    interval = header.get("interval") or 0
    if expect is None or checked is None:
        return "STALE"
    if now <= expect:
        return "LIVE"
    if now - checked > 2 * interval + 60:
        return "STALE"
    return "OVERDUE"


# ------------------------------------------------------------ process probe


_ERROR_ALREADY_EXISTS = 183
_ERROR_INVALID_PARAMETER = 87
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Held for process lifetime. The mutex is released when the handle closes, so
# the handle must outlive the acquiring function - a local would be fine while
# the process lives, but keeping it at module scope makes the intent explicit
# and stops a future refactor from "tidying up" the only thing holding it.
_singleton_handle = None


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _open_process(pid: int) -> tuple[int, int]:
    """(handle, last error). handle 0 means the open failed."""
    k32 = _kernel32()
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    return int(handle or 0), ctypes.get_last_error()


def _process_exit_code(handle: int) -> int | None:
    k32 = _kernel32()
    code = wintypes.DWORD()
    if not k32.GetExitCodeProcess(wintypes.HANDLE(handle), ctypes.byref(code)):
        return None
    return int(code.value)


def _close_handle(handle: int) -> None:
    try:
        _kernel32().CloseHandle(wintypes.HANDLE(handle))
    except (AttributeError, OSError, ValueError):
        pass


def _pid_alive_detail(pid: int | None) -> tuple[bool | None, str]:
    if pid is None or not sys.platform.startswith("win"):
        return None, "unknown"
    try:
        handle, err = _open_process(int(pid))
        if not handle:
            if err == _ERROR_INVALID_PARAMETER:
                return False, "no"
            if err == _ERROR_ACCESS_DENIED:
                return None, "unknown (access denied)"
            return None, "unknown"
        code = _process_exit_code(handle)
        _close_handle(handle)
        if code is None:
            return None, "unknown"
        return (True, "yes") if code == _STILL_ACTIVE else (False, "no")
    except (AttributeError, OSError, ValueError):
        return None, "unknown"


def _pid_alive(pid: int | None) -> bool | None:
    return _pid_alive_detail(pid)[0]


def _final_path(path: Path) -> str | None:
    """The physical path the OS resolves an OPEN handle to.

    A packaged process reads its own copy-on-write twin of an AppData file
    while believing it read the real one. Nothing errors, nothing warns, and
    the two paths differ only in the middle - so the only honest way to know
    which file a shell just read is to ask the handle.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        k32 = _kernel32()
        with open(path, "rb"):
            import msvcrt

            with open(path, "rb") as fh:
                handle = msvcrt.get_osfhandle(fh.fileno())
                buf = ctypes.create_unicode_buffer(32768)
                n = k32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buf, 32768, 0)
                return buf.value if n else None
    except (AttributeError, OSError, ValueError, ImportError):
        return None


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
        kernel32 = _kernel32()
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


# -------------------------------------------------------------- status view


def status_report(
    now: float | None = None,
    state_path: Path | None = None,
    repos: tuple[str, ...] | None = None,
    self_root: str | None = None,
) -> list[str]:
    """The computed view. Reads only, creates nothing, takes no singleton.

    The FILE is storage; the DISPLAY computes freshness. Every default resolves
    at call time so a fixture that patches the module can actually redirect it.
    """
    now = time.time() if now is None else now
    state = _state_dir_path() if state_path is None else Path(state_path)
    repos = DEFAULT_REPOS if repos is None else repos
    root = _SELF_REPO if self_root is None else self_root

    idle = effective_idle_seconds(now)
    out = [f"idle={int(idle)}s interval={interval_for(idle)}s state={state}"]

    status_md = state / "status.md"
    try:
        text = status_md.read_text(encoding="utf-8")
    except OSError:
        text = None

    if text is None:
        out.append("status.md ABSENT")
        out.append("fleet view no")
        out.append("pid none alive unknown")
        out.append("verdict UNMEASURED")
        unmapped = sum(1 for r in repos if code_for(r).startswith("UNMAPPED-"))
    else:
        header = parse_status_header(text)
        checked = header.get("checked")
        out.append(f"status.md age {int(now - checked)}s" if checked else "status.md age UNMEASURED")
        out.append("fleet view yes" if header["fleet_view"] else "fleet view no")
        alive, label = _pid_alive_detail(header.get("pid"))
        out.append(f"pid {header.get('pid') if header.get('pid') is not None else 'none'} alive {label}")
        out.append(f"verdict {status_verdict(header, now, alive)}")
        if header.get("fault"):
            out.append(f"fault: {header['fault']}")
        # The poller already resolved the roster this poll; re-deriving it here
        # from THIS process's import-time DEFAULT_REPOS would answer a different
        # question and disagree with the file on any roster change.
        unmapped = int(header.get("unmapped_roots") or 0)

    half_text, dead = prompt_half(now, root)
    out.append(f"prompt half: {half_text.replace(' DEAD', '')}")
    if dead:
        out.append("prompt half DEAD")

    seen_p = state / "poller_seen.json"
    try:
        blob = json.loads(seen_p.read_text(encoding="utf-8"))
        stamp = str(blob.get("updated"))
        epoch = _parse_iso(stamp)
        age = int(now - epoch) if epoch else -1
        out.append(f"seen store: updated {stamp} (age {age}s, {seen_p.stat().st_size} B)")
    except (OSError, ValueError, AttributeError):
        out.append("seen store: UNMEASURED")

    if unmapped:
        out.append(f"participants map absent: {unmapped} roots UNMAPPED")

    for name in ("status.md", "poller_seen.json", "activity.json"):
        p = state / name
        if not p.exists():
            continue
        final = _final_path(p)
        if final and "\\Packages\\" in final and "\\LocalCache\\" in final:
            out.append(f"VIRTUALIZED VIEW: {name} resolves under a package LocalCache")
    return out


# ----------------------------------------------------------------- run loop


def run(repos: tuple[str, ...] = DEFAULT_REPOS, once: bool = False) -> int:
    if not once and not _acquire_singleton():
        print("another poller already holds the singleton; exiting")
        return 0

    # BOOT MARKER. A background daemon that says nothing on start is one you
    # cannot tell apart from a daemon that started and wedged - which is
    # exactly the state this hit during development: Task Scheduler reported
    # the task Running with a live pid while the status file went stale, and
    # a manually launched process with byte-identical arguments behaved fine.
    # Guessing at that costs more than one line of log per start.
    _log_line(
        f"BOOT pid={os.getpid()} state={_state_dir_path()} "
        f"idle_probe={'ok' if input_idle_seconds() is not None else 'UNAVAILABLE'} "
        f"repos={len(repos)}"
    )

    try:
        boot_note = _boot_rebaseline(time.time(), repos)
    except Exception as exc:  # noqa: BLE001 - a boot check must not block the loop
        boot_note = None
        _log_line(f"FAULT {type(exc).__name__}")
    if boot_note:
        _log_line(boot_note)

    last_poll = 0.0
    promised = TIERS[0][1]
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
        #
        # min(interval, promised) HONOURS THE FILE. See the module docstring.
        if now - last_poll >= min(interval, promised):
            last_poll = now
            promised = interval
            total = 0
            try:
                out = scan_fleet(repos)
                findings = out["findings"]
                write_status(findings, idle, interval, rows=out["rows"], boot_note=boot_note)
                _record_findings(out["rows"])
                boot_note = None
                total = sum(len(d["new"]) + len(d["withdrawn"]) for d in findings.values())
                found = sorted(code_for(r) for r in findings)
                # Heartbeat EVERY poll, not only when something is found. A log
                # that is silent on a quiet channel cannot distinguish "nothing
                # arrived" from "the poller stopped polling", and those are the
                # two states it exists to tell apart.
                _log_line(
                    f"poll idle={int(idle)}s next={interval}s findings={total}{' codes=' + str(found) if found else ''}"
                )
            except Exception as exc:  # noqa: BLE001 - the poller outlives any one poll
                _log_line(f"FAULT {type(exc).__name__}")
                _write_minimal_status(exc)
        if once:
            return 0
        time.sleep(min(TICK_SECONDS, interval))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-repo inbox poller with idle backoff.")
    ap.add_argument("--ping", metavar="REPO", help="record a session prompt for REPO and exit (resets the ladder)")
    ap.add_argument("--once", action="store_true", help="one scan, then exit")
    ap.add_argument("--status", action="store_true", help="print the computed liveness view and exit (writes nothing)")
    ap.add_argument(
        "--repo", action="append", default=None, help="participating repo root (repeatable); defaults to all five"
    )
    args = ap.parse_args(argv)

    if args.ping:
        return ping(args.ping)
    repos = tuple(args.repo) if args.repo else DEFAULT_REPOS
    if args.status:
        for line in status_report(repos=repos):
            print(line)
        return 0
    return run(repos, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
