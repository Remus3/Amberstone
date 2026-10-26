# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit - the ONLY path that starts a headless `claude` in any repo here.

Vendored byte-for-byte into every repo at ops/fleet_kit/ and pinned by
MANIFEST.json. Do NOT edit a vendored copy: report the defect to MAIN, which
ships a new kit version to every repo at once.

What it enforces (FLEET-COMMON item 10):
- the second-account proxy, read from the user variable CLAUDE_HEADLESS_BASE_URL
  (registry first, so deleting the variable stops even a long-lived process),
- fail closed: unset / non-loopback / unpinned / unreachable -> Refused, never a
  fallback; any --fallback-model or auto-fallback flag is refused at the door,
- at most RUNS_CAP runs started per rolling WINDOW_S, counted under a lock; an
  unreadable budget file refuses (fail closed) and is never reset,
- never spawn on this repo's own notes, or on notes marked TERMINAL / no-reply
  (marker LINES and whole name tokens only; ORDER / FIX / RULING never damped),
- lean flags (strict MCP + project settings, or --bare - refused when the caller
  says its floors live in hooks), sonnet unless the work writes code, effort low
  for acknowledgements,
- no visible console window, the claude executable never taken from the working
  directory, and a timeout kills the whole process tree,
- one usage line per run, and the live status file the lane widget reads, never
  left reading "running" after the run ends however it ends.

v4 adds OPTIONAL keyword parameters to spawn() (v3 behaviour when omitted):
cwd, stdin, return_stderr, persist / session_id / resume, model, effort,
setting_sources, floors_in_hooks, pin, log_path (streamed stream-json log),
halt_file; plus write_progress() for ops/loop/control/progress/<task>.json.

v5 adds sibling kit files (this file's API is unchanged by them):
fleet_watch.py (watcher primitive), fleet_secrets.py (secret references) and
tokens.json + tokens.css (shared dashboard design tokens).

v6 adds fleet_lanes.py (per-repo lanes, one worktree each, under the 3-slot
machine governor) and OPTIONAL spawn(governor=...): None (default) takes no
slot, exactly as v5; "queued" or "interactive" holds one governor slot for the
run, waiting in the fair queue (status "backoff" while it waits) and refusing
on governor_timeout. One slot per executor call: never also hold slots.hold()
around a governed spawn. Ruling: inbox acknowledgements stay outside the slots.

v7 adds fleet_checklist.py (FLEET-COMMON item 13, the session checklist) and
an OPTIONAL write_progress(..., checklist=[{id, task, state, eta_s}]) field;
without it the progress file is byte-for-byte the v6 shape.

v8 adds fleet_inbox.py (FLEET-COMMON item 14, inbox cost discipline: triage on
sonnet/low, mechanical acks, an outbound cap, a hop limit, the build-vs-inbox
cost split) and an OPTIONAL spawn(kind=build|inbox|triage). The usage line
gains "kind": the explicit value, else inferred by run_kind() (a channel-note
name is inbox, an empty note unattributed, any other label build).
Kind "inbox" is a run that DOES the work a note orders (an ORDER / FIX /
RULING lane); "triage" is the cheap classification look; "build" is the rest.

v10 (backward compatible; every new parameter is optional):
- a block-quoted line (`> TERMINAL`) is never a marker: quoting a note is not
  marking this one (RSC 1540 gap 1);
- the usage line carries "is_error" and "subtype" from the claude result, and
  spawn's return adds "receipt", the full result event (RSC gap 2, LW 1258 A);
- the run budget lock is an OS byte-range lock on a file that is never
  unlinked, so a dead holder frees it at once (RSC gap 3);
- halt_file halts on ANY entry at the path, a dangling symlink included
  (RSC gap 4);
- a POSIX timeout kills the child's whole process group (RC 1915);
- _run passes a literal creationflags= to Popen (LW 1258 B), and launch() is
  its public name (RC 2220 d);
- spawn(stdin_data=...) keeps the prompt in argv and feeds stdin_data on
  stdin (RC 2220 e); a custom run= that accepts on_start gets it, and the
  usage line records "child_marked" (RSC 0523 item 6);
- an OSError before the run starts is a Refused, never a raw escape;
- _atomic_write retries a briefly locked target and never orphans its tmp
  (RSC 0523 item 2);
- status task names are the MAIN 0915 basic set only (TASKS; CS 1234);
- a command-line entry: `python fleet_headless.py spawn ...` (CS 0224).

v11:
- the command line gains ONE pass-through, `--permission-mode MODE`, its
  value limited to the CLI's own modes (PERMISSION_MODES), mapped to
  extra=("--permission-mode", MODE) and screened by check_door like any
  extra (ruling R2). There is no generic --extra on the command line;
- a governor SlotTimeout is reported as a fixed kit message built from
  numbers, never str(exc) (CS 1623 item 6).

v12 (race guards, FLEET-COMMON 16; ruling 2026-10-08 lane-progress-location):
- main_checkout(path): the tree's MAIN working tree for path, resolved
  file-only from a linked worktree's .git file (identical to
  fleet_lanes.main_tree, kept import-free of it);
- write_progress() always writes to main_checkout(root)/ops/loop/control/
  progress/<task>.json, so a caller passing its worktree cwd lands in the main
  checkout; the returned doc carries "path" (the file written; not on disk);
- sibling kit files fleet_gitlock.py, fleet_claims.py, fleet_suite_gate.py and
  fleet_test_guard.py (this file's other API is unchanged by them).

v13 (KIT-13 defects; GH-HYGIENE ruling 2026-10-08):
- write_progress() is atomic per call AND per task: every write goes to its
  own temp file (<task>.json.<pid>.<thread>.<random>.tmp, never shared by two
  writers, even two threads of one process), is moved over <task>.json with
  os.replace, then READ BACK; a lost or torn write is retried, and a write
  that cannot be confirmed raises instead of passing silently;
- `python fleet_headless.py progress --root R --task T --pct P --step S
  --eta-s E --status running|done|failed` writes one progress file from the
  command line, so an agent never needs a helper script of its own (two
  agents sharing one helper script lost intermediate writes);
- sibling kit files fleet_identity.py (FLEET-COMMON 17) and
  fleet_rewrite.py (the operator-gated history rewrite helper).

v14 (KIT-14; every change backward compatible):
- state "blocked" (STATES, PROGRESS_STATES, tokens.json states): a start that
  cannot run for an OUTSIDE reason - today an unreachable proxy - writes
  state "blocked" with a "reason" field to inbox_status.json instead of
  "refused" (SS 0025). It still raises Refused (subclass Blocked) and still
  logs the same message text, so substring matchers keep working;
- distinct refusal codes: every Refused carries .code - "refused",
  "blocked", "proxy-unreachable", "budget-unreadable", "budget-lock-unopenable",
  "budget-lock-busy", "budget-write-failed", "budget-spent" (RSC 1925);
- write_progress(..., reason=None) and `progress --status blocked --reason R`;
- conformance() also requires each FLEET-COMMON marker ALONE on its own line
  (SS 2239 c: a splice with the bare BEGIN string welds the first heading onto
  the marker line while the block hash still passes).

v15 (KIT-15; every change backward compatible):
- child_env() sets CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 (BG_OFF_ENV): a
  `-p` child that dispatched a background sub-agent and ended its turn
  exited and killed the sub-agent mid-work (LW 1020 item 7, seen twice).
  With background tasks off in the child, every sub-agent and command it
  starts runs in the foreground and finishes inside the turn. The rule for
  a child prompt is the same: foreground only.
- A non-UTF-8 .git link file no longer crashes main_checkout (and
  fleet_claims._gitdir_of, fleet_identity._main_checkout,
  fleet_lanes.main_tree): UnicodeError is caught beside OSError and the
  existing fallback answers (RC 1925 a).
- fleet_suite_gate.resolve_exe: a bare suite command whose PATH hit is a
  .cmd/.bat shim (npm) runs by that full path on Windows (EW 1955).

v18 = the KIT-16 batch (built as "v16"; the FIX versions v16 and v17 took
those numbers, so every "v16 (KIT-16)" note in the kit ships in v18)
(Fleet Insights 2026-10-09 R1, KIT-15 adjudication c9836ae):
- kind "order" (KINDS): a run doing the work of a MAIN ORDER / FIX / RULING
  note. run_kind() maps such a note to "order" when no kind is given AND
  when the caller passes kind="inbox" (the v8-v15 lanes logged ORDER work as
  inbox, so the inbox share counted build work as chatter); "build" and
  "triage" given explicitly stay as given. The class is read with
  note_class() (name, else the `# From XX - CLASS` title in head=);
- spawn() refuses an EMPTY or blank note label before anything starts
  (Refused code "empty-note"; status file "refused" with the reason): a
  usage row with no label cannot be attributed (179.65 USD unattributed in
  the 2026-10-09 report). usage_line() still writes "kind" on every row;
- every usage row carries "slot": the caller's lane / slot id
  (spawn(slot_id=...), CLI --slot), else the governor slot's name, else
  null. "governor_slot" is kept unchanged beside it;
- sibling kit changes: fleet_done.py (hand-off size warning, `archive`),
  fleet_test_guard.budget(), fleet_suite_gate (PATH-only resolve_exe, a
  path-free pytest refused when no testpaths config), fleet_gitlock
  (merge / reset / revert lock-only), tokens.json chart = the validated
  tree palette.
- stale progress rows (ruling docs/rulings/2026-10-10-stale-progress-rows.md):
  write_progress() records the row's OWNER {"pid", "start"} - an explicit
  owner=, else env FLEET_PROGRESS_OWNER (a pid; "none" = no owner), else the
  nearest ancestor process named claude / claude.exe (the agent session whose
  tool call wrote the row), else no owner field. owner_alive() answers
  True / False / None (pid gone, or reused: start time differs -> False);
  progress_abandoned(doc) is True for a running/blocked row whose owner is
  dead, or that has been silent over ABANDON_S (2 h). close_progress() turns a
  still-running row into "failed" (pct, step, checklist kept, a "reason"
  added); close_owned_progress() does it for every row a given pid owns.
  spawn() closes, in a finally, every row the child process owned and the
  optional progress_task= row (CLI --progress-task); fleet_lanes.run_lane
  closes progress/lane-<i>.json when the block ends. `progress --owner PID`
  on the command line (0 = no owner).
- also in v18: fleet_suite_gate commit-aware admission + peak_commit_mb
  (RM737-GATE), lane thresholds 130 / 200 s (KIT-15-REPICK), bare words
  resolved on the CHILD's PATH (CS 1840); fleet_inbox ledger lock (RSC 1852
  a); fleet_claims quoted-redirect parser (V18-PARSER) and the bare commit /
  push denial scoped to guarded repos (CLAIMS-SCOPE).
- strict attribution (Fleet Insights 2026-10-16 item 2): spawn() refuses a
  missing / None kind (Refused code "no-kind") as it refuses an empty note
  label, before anything starts; CLI `spawn --kind` is required. run_kind()
  no longer guesses a spawn's kind - it still classifies legacy usage rows
  (kind absent) and re-attributes inbox -> order for ORDER / FIX / RULING.

v19 = STATUS BOARD (FLEET-COMMON 18, operator order 2026-10-18, one-off
train + nightly waiver docs/rulings/2026-10-18-kit-v19-waiver.md):
- fleet_board.py joins the kit: renders the per-tree claude.ai board feed
  (status.json) from the item-13 checklist; `calls` prints the two tool
  calls an interactive session makes to push it; headless never pushes.
- STOP SENTINELS (CS FIX 2026-10-18-1213 item 1): spawn() refuses, code
  "halted", before anything starts, while a path the TARGET tree declares in
  ops/stop_sentinels.json {"paths": [...]} exists; an unreadable file or a
  path outside the tree refuses too (fail closed). No file = no sentinels,
  no default names. The inbox status file's own "halted" is not a trigger
  (spawn writes it itself; it would never clear).
- fleet_identity pre-push: a NEW ref is scanned against the remote's real
  ls-remote advertisement, not local tracking refs (CS 1213 item 2).

v19.1 = EXPLICIT HEADLESS ROUTE (operator order 2026-10-18 "v19.1" B; ruling
MAIN docs/rulings/2026-10-18-headless-route.md; same one-off waiver as v19):
- spawn() reads ~/.fleet/headless_route.json FRESH on every spawn, first in its
  checks: {"version": 1, "mode": "split"} = exactly the v19 proxy path;
  {"version": 1, "mode": "single", "config_dir": <abs dir holding the account
  credentials file>} = the child runs on that account directly (CLAUDE_CONFIG_DIR
  set, no base URL, no probe; --bare refuses, code "route-bare"). Missing =
  Refused "route-missing", anything else wrong = "route-invalid". No default, no
  fallback, no automatic mode change.
- CLAUDE_HEADLESS_BASE_URL stays REQUIRED (check_url) in BOTH modes: deleting it
  is still the one machine-wide kill switch.
- the usage line gains "route" and "kit_patch"; the status file "route".
- CLI: `route show` (mode only, never the path; exit 1 when not valid) and
  `route set split` / `route set single --config-dir DIR` (validated first,
  atomic ASCII + LF write; invalid input leaves the file untouched).
- KIT_PATCH = 1: the manifest version stays 19 (the waiver and rollout key on
  it); the release reads v19.1.

v20 (v19.1 folded in; train waiver docs/rulings/2026-10-18-kit-v20-waiver.md;
KIT_PATCH = 0, no "v19 patch 1" manifest is ever queued):
- ACCT-FALLBACK (ruling docs/rulings/2026-10-18-acct-fallback.md, FLEET-COMMON
  10 new text): the route file may carry {"fallback": {"armed": true, "mode":
  <the other mode>[, "config_dir": ...]}}; it is validated like a primary and an
  invalid block refuses the whole route. Missing or disarmed = no fallback.
  Written only by `route set ... --fallback split|single` / `--no-fallback`.
  ONE trigger: a failed run's own message that classify_limit() reads as the
  7-day window with a parsed reset inside 7 days. The run ends "limit" (no
  in-run retry); ~/.fleet/headless_fallback.json {"since","until","from","to"}
  moves the NEXT spawns to the fallback until "until". A limit on the fallback
  halts (Refused "fallback-halted", status "limit") until the earlier reset;
  never a third route. Proxy / auth / network failures, a 5-hour limit, an
  unknown window and any percentage never trigger. No quota percentage is read.
  Any `route set` or deleting the state ends it. Start / halt / end write one
  line to ~/.fleet/headless_fallback.jsonl; usage lines carry "fallback" and
  "limit", the status file "fallback": true (statusline FALLBK, tokens state
  "fallback"). The rollout writes no fallback block.
- CHECKLIST-ETA-CLOCK: write_progress(..., started=) (see fleet_checklist.py).

v20.1 (operator order 2026-10-18, ruling
docs/rulings/2026-10-18-kit-v20-1-outbound-cap.md): fleet_inbox.OUTBOUND_CAP
6 -> 12 per tree per local day (FLEET-COMMON 14c); ORDER / FIX / RULING stay
exempt. KIT_PATCH = 1: the manifest version stays 20; the release reads v20.1.

v21 (kit train; built on branch kit-v21): KIT-ETA-REMAIN (fleet_checklist
run_clock, statusline runClock: `started h:mm - <pct>% ~<rem> of <total>
Remain [h:mm]`), KIT-GATE-WHO and GATE-SLOTS-2 (fleet_suite_gate), the
FLEET-COMMON 13a / 16c text. KIT-CS-FIX (CS FIX 2026-10-21-0420, CS-1231):
_run starts the child SUSPENDED inside a Windows job object (kill-on-close,
breakaway allowed only when a child asks for it) and resumes it, so a timeout
kills the whole tree, an orphaned grandchild included; it holds NO pipes
(captured stdout / stderr and input are spooled through temp files), so an
escaped descendant can never block the return; a timeout returns after at
most timeout + kill + PIPE_GRACE seconds. spawn's two bare Refused re-raise
sites are distinct (CS 2356 item 5).

v22 (daily kit train, ruling MAIN docs/rulings/2026-10-25-kit-train-daily.md;
cumulative: a tree on v20.1 adopts v21 and v22 at once):
- KIT-V22-SIDECAR: child_env(code=) sets CLAUDE_CODE_TMPDIR to
  <sidecar root>/<CODE>/Temp/claude when that sidecar exists (the usage
  line records it as "tmpdir") (fleet_lanes v22 default
  root E:/Sidecars when FLEET_SIDECAR_ROOT is named nowhere); a parent value
  wins; missing sidecar = unchanged.
- KIT-V22-BARE: a bare spawn on the single route is no longer refused
  ("route-bare"): it runs the lean non-bare form (strict MCP + project
  settings, the rules file appended), usage line "bare": false plus
  "bare_degraded": true. Split is unchanged.
- KIT-V22-REAP: fleet_done.py reap (see that file).
- CS-1345: fleet_identity pre-push excludes already-published commits from an
  existing-branch range too.

v23 (daily kit train; cumulative: a tree on v20.1 adopts v21, v22 and v23
at once): KIT-V23-BOARD-LOCAL (operator order 2026-10-25): the status board
is local only - fleet_board.py renders status.json and board.html under
ops/loop/control/board/ and prints no Artifact / ArtifactData call;
FLEET-COMMON 18 rewritten; fleet_test_guard IGNORE adds board.html.

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

KIT_VERSION = 23
KIT_PATCH = 0
TMPDIR_ENV = "CLAUDE_CODE_TMPDIR"  # v22: headless child temp root (sidecar)
VAR = "CLAUDE_HEADLESS_BASE_URL"
RUNS_CAP = 120
WINDOW_S = 86400
STATUS_REL = Path("ops/loop/control/inbox_status.json")
BUDGET_REL = Path("ops/loop/control/headless_budget.json")
USAGE_REL = Path("ops/loop/control/headless_usage.jsonl")
PROGRESS_REL = Path("ops/loop/control/progress")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
PLACEHOLDER_KEY = "fleet-proxy-placeholder"
STRIP_EXACT = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
STRIP_PREFIX = ("CLAUDE_CODE_USE_",)
KEEP_EXACT = {"CLAUDE_CODE_USE_POWERSHELL_TOOL"}
BG_OFF_ENV = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
ACK_MARKERS = ("INFORMATION", "ACK", "TERMINAL", "CORRECTION-ACCEPTED",
               "POLL-ANSWER", "RECEIVED", "NO-REPLY", "NOREPLY")
NEVER_DAMP = ("ORDER", "FIX", "RULING")
STATES = ("idle", "running", "limit", "halted", "backoff", "refused", "blocked")
PROGRESS_STATES = ("running", "done", "failed", "blocked")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
SOURCES = ("user", "project", "local")
DEFAULT_SOURCES = "project,local"
ARGV_PROMPT_MAX = 30000
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_SENDER = re.compile(r"(?:^|[-_])(?i:from)-([A-Z]+)-")
_TITLE = re.compile(r"^#+\s*(?i:from)\s+([A-Z]+)\b(?:\s*-\s*([A-Z]+))?")
_CLASS = re.compile(r"(?:^|[-_])(?i:from)-[A-Z]+-([A-Za-z]+)")
_MARK = r"(?:TERMINAL|NO[-_ ]?REPLY)"
_MARKER_LINE = re.compile(r"^(?:CLASS\s+)?" + _MARK + r"(?:\s*[-.,:;/]?\s*" + _MARK +
                          r")*\s*[.!]?$")
_MODEL = re.compile(r"^(?:opus|sonnet|haiku|claude-[a-z0-9][a-z0-9.-]*)(?:\[1m\])?$")
_TOKEN_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CHECK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$")
CHECKLIST_MAX = 20
ABANDON_S = 7200  # v16: a running row silent this long is abandoned
OWNER_ENV = "FLEET_PROGRESS_OWNER"
OWNER_NAMES = ("claude.exe", "claude")
_START_SLACK_S = 2.0
ATOMIC_TRIES = 8
KINDS = ("build", "inbox", "triage", "order")
# MAIN 0915 section 1: the BASIC status task names, the operator's words.
TASKS = ("Idle", "Checking Inbox", "Waiting for Slot", "Running Session",
         "Delivering Notes", "Committing", "Backing Off", "Halted", "Turn Limit Reached")
REFUSED_TASK = "Idle"  # a refused start runs nothing; state "refused" says why
_NOTE_SENDER = re.compile(r"(?:^|[-_])(?i:from)-[A-Z]+-")
_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone(_dt.timedelta(0)))


SLOT_TIMEOUT_CODE = "slot-timeout"  # v21 KIT-ROLLOUT-DEFER: a governor SlotTimeout


class Refused(Exception):
    """A spawn the kit will not start. str() is the logged reason; .code is a
    stable machine-readable class (v14, RSC 1925)."""
    code = "refused"

    def __init__(self, *args, code=None):
        super().__init__(*args)
        if code:
            self.code = code


class Blocked(Refused):
    """v14: a start an OUTSIDE condition stops (proxy down). The status file
    says "blocked", not "refused"; still fail closed, never a fallback."""
    code = "blocked"


class BudgetUnreadable(Refused):
    """The budget file exists but cannot be read or parsed: fail closed."""
    code = "budget-unreadable"


# ---------------------------------------------------------------- proxy URL

def _registry_value():
    """(found, value). found=False only when the user store cannot be opened."""
    try:
        import winreg
    except ImportError:
        return False, None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                value, _ = winreg.QueryValueEx(key, VAR)
                return True, str(value)
            except FileNotFoundError:
                return True, None
    except OSError:
        return False, None


def base_url(registry=_registry_value, environ=None):
    """The pinned proxy URL, or None. A readable registry WITHOUT the value wins
    over a stale inherited environment copy: that is the fleet kill switch."""
    found, value = registry()
    if found:
        return value or None
    env = os.environ if environ is None else environ
    return env.get(VAR) or None


def _parse_pin(pin):
    if isinstance(pin, (tuple, list)) and len(pin) == 2:
        host, port = str(pin[0]), pin[1]
    else:
        host, _, port = str(pin).rpartition(":")
    host = host.strip("[]")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise Refused("proxy pin has no valid port") from None
    if host not in LOOPBACK or not 0 < port < 65536:
        raise Refused("proxy pin is not a loopback host:port")
    return host, port


def check_url(url, pin=None):
    """Raise Refused unless url is plain http to a loopback host:port - and,
    when pin ("host:port" or (host, port)) is given, to exactly that one."""
    if not url:
        raise Refused(VAR + " is unset")
    if any(c in url for c in "@\\ \t\r\n"):
        raise Refused("proxy URL has a forbidden character")
    parts = urlsplit(url)
    if parts.scheme != "http":
        raise Refused("proxy URL is not plain http")
    if parts.hostname not in LOOPBACK:
        raise Refused("proxy URL host is not loopback")
    try:
        port = parts.port
    except ValueError:
        raise Refused("proxy URL port is invalid") from None
    if not port:
        raise Refused("proxy URL has no port")
    if pin is not None and (parts.hostname, port) != _parse_pin(pin):
        raise Refused("proxy URL is not the pinned host:port")
    return parts.hostname, port


def probe(host, port, timeout=2.0, connect=socket.create_connection):
    try:
        connect((host, port), timeout=timeout).close()
    except OSError as exc:
        raise Blocked(f"proxy unreachable: {exc.__class__.__name__}",
                      code="proxy-unreachable") from None


def child_env(url, bare=False, parent=None, route=None, code=None):
    """The child's environment: provider switches and credentials removed, the
    proxy URL set. CLAUDE_CODE_USE_POWERSHELL_TOOL is a tool switch, not a
    provider switch, and is kept. --bare reads no OAuth, so it gets a
    placeholder key that the proxy replaces with the pinned account.
    v22 (KIT-V22-SIDECAR): with code given and no CLAUDE_CODE_TMPDIR in the
    parent, the child's temp root is <sidecar root>/<CODE>/Temp/claude when
    <sidecar root>/<CODE> exists (fleet_lanes.sidecar_dir); otherwise nothing
    is set (the v21 behaviour, never a failure)."""
    env = dict(os.environ if parent is None else parent)
    for k in list(env):
        if k in KEEP_EXACT:
            continue
        if k in STRIP_EXACT or k.startswith(STRIP_PREFIX) or (
                k.startswith("ANTHROPIC_") and k.endswith("BASE_URL")):
            del env[k]
    if route and route.get("mode") == "single":
        # v19.1 single route: the named main-account config dir, no proxy (every
        # base URL was stripped above).
        env["CLAUDE_CONFIG_DIR"] = route["config_dir"]
    else:
        env["ANTHROPIC_BASE_URL"] = url
    # v10: SUBAGENT-FIRST guards an operator's interactive main thread; a
    # headless run has no agent_id and no operator, so it is always exempt.
    env["FLEET_SUBAGENT_FIRST"] = "off"
    # KIT-15 (LW 1020 item 7): a -p child exits when its turn ends, killing any
    # background sub-agent it left running; the child runs foreground only.
    env[BG_OFF_ENV] = "1"
    if bare:
        env["ANTHROPIC_API_KEY"] = PLACEHOLDER_KEY
    if code and not env.get(TMPDIR_ENV):
        tmp = None
        with contextlib.suppress(Exception):  # a sidecar problem never blocks a run
            tmp = _lanes().sidecar_dir(code, "Temp")
            if tmp is not None:
                tmp = tmp / "claude"
                tmp.mkdir(parents=True, exist_ok=True)
        if tmp is not None and tmp.is_dir():
            env[TMPDIR_ENV] = str(tmp)
    return env


# ---------------------------------------------------------------- route (v19.1)
# Ruling docs/rulings/2026-10-18-headless-route.md (MAIN). An EXPLICIT route file,
# read fresh on every spawn; missing or invalid refuses before anything starts. No
# default, no fallback, no automatic mode change. The kit is its only writer.

ROUTE_VERSION = 1
ROUTE_MODES = ("split", "single")
ROUTE_CREDENTIALS = ".credentials.json"
_ROUTE_KEYS = {"split": {"version", "mode"}, "single": {"version", "mode", "config_dir"}}


# V191-ALIAS: the ONE test-only redirect. fleet_test_guard sets it per test so
# every load of this file, under any module name, reads a tmp route. Honoured
# only while pytest runs a test (PYTEST_CURRENT_TEST); production ignores it.
TEST_ROUTE_ENV = "FLEET_TEST_HEADLESS_ROUTE"


def route_path():
    """~/.fleet/headless_route.json - fixed; nothing (CLI, env, config) moves it
    outside a pytest test (see TEST_ROUTE_ENV)."""
    t = os.environ.get(TEST_ROUTE_ENV)
    if t and os.environ.get("PYTEST_CURRENT_TEST"):
        return Path(t)
    return Path.home() / ".fleet" / "headless_route.json"


def _route_invalid(why):
    return Refused("headless route invalid: " + why, code="route-invalid")


def check_route(doc):
    """A parsed route document -> {"mode", ["config_dir"]}, else Refused
    route-invalid. The config dir is checked statically (absolute, ASCII, an
    existing directory holding the account credentials file); no secret is read
    and no message names the path."""
    if not isinstance(doc, dict):
        raise _route_invalid("not an object")
    v = doc.get("version")
    if type(v) is not int or v != ROUTE_VERSION:
        raise _route_invalid(f"version must be {ROUTE_VERSION}")
    mode = doc.get("mode")
    if mode not in ROUTE_MODES:
        raise _route_invalid("mode must be split or single")
    if set(doc) - {"fallback"} != _ROUTE_KEYS[mode]:
        raise _route_invalid("keys must be exactly " + ", ".join(sorted(_ROUTE_KEYS[mode]))
                             + " (+ optional fallback)")
    fb = _check_fallback(doc["fallback"], mode) if "fallback" in doc else None
    out = _check_primary(doc, mode)
    if fb is not None:
        out["fallback"] = fb
    return out


def _check_fallback(fb, primary_mode):
    """v20 ACCT-FALLBACK condition 1: the block is validated in full whether
    armed or not; an invalid block refuses the whole route, never ignored.
    Armed -> {"mode", ["config_dir"]}, validated exactly like a primary of that
    mode; disarmed -> None."""
    if not isinstance(fb, dict):
        raise _route_invalid("fallback must be an object")
    if type(fb.get("armed")) is not bool:
        raise _route_invalid("fallback.armed must be true or false")
    m = fb.get("mode")
    if m not in ROUTE_MODES:
        raise _route_invalid("fallback.mode must be split or single")
    if m == primary_mode:
        raise _route_invalid("fallback.mode must be the other route")
    want = {"armed"} | (_ROUTE_KEYS[m] - {"version"})
    if set(fb) != want:
        raise _route_invalid("fallback keys must be exactly " + ", ".join(sorted(want)))
    target = dict(fb, version=ROUTE_VERSION)
    del target["armed"]
    try:
        checked = _check_primary(target, m)
    except Refused as exc:
        raise _route_invalid("fallback " + str(exc).split(": ", 1)[-1]) from None
    return checked if fb["armed"] else None


def _check_primary(doc, mode):
    if mode == "split":
        return {"mode": "split"}
    cd = doc.get("config_dir")
    if not isinstance(cd, str) or not cd or any(ord(c) > 127 or ord(c) < 32 for c in cd):
        raise _route_invalid("config_dir must be a non-empty ASCII path")
    if not Path(cd).is_absolute():
        raise _route_invalid("config_dir must be absolute")
    if not Path(cd).is_dir():
        raise _route_invalid("config_dir is not an existing directory")
    if not (Path(cd) / ROUTE_CREDENTIALS).is_file():
        raise _route_invalid("config_dir holds no account credentials file")
    return {"mode": "single", "config_dir": cd}


def read_route(path=None):
    """The route, read fresh. Missing -> Refused route-missing; anything else
    wrong -> Refused route-invalid."""
    p = route_path() if path is None else Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        raise Refused("headless route file missing - run `fleet_headless.py route set`",
                      code="route-missing") from None
    except OSError as exc:
        raise _route_invalid(f"unreadable ({exc.__class__.__name__})") from None
    if any(b > 127 for b in raw) or b"\r" in raw:
        raise _route_invalid("not ASCII + LF")
    try:
        doc = json.loads(raw.decode("ascii"))
    except ValueError:
        raise _route_invalid("not JSON") from None
    return check_route(doc)


def write_route(mode, config_dir=None, path=None, fallback=None, fallback_config_dir=None):
    """`route set`: validate FIRST, then an atomic ASCII + LF write. An invalid
    request raises Refused and leaves the existing file untouched. v20:
    fallback= arms a fallback to the other route (fallback_config_dir names
    its account dir when it is single); none = no block (--no-fallback). Any
    route set ends an active fallback at once (ruling condition 5)."""
    doc = {"version": ROUTE_VERSION, "mode": mode}
    if mode == "single":
        doc["config_dir"] = config_dir
    elif config_dir is not None:
        raise _route_invalid("split takes no config_dir")
    if fallback is not None:
        doc["fallback"] = {"armed": True, "mode": fallback}
        if fallback == "single":
            doc["fallback"]["config_dir"] = fallback_config_dir
        elif fallback_config_dir is not None:
            raise _route_invalid("a split fallback takes no config_dir")
    elif fallback_config_dir is not None:
        raise _route_invalid("fallback config_dir without a fallback")
    check_route(doc)
    p = route_path() if path is None else Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, json.dumps(doc, sort_keys=True) + "\n", verify=True)
    if os.path.lexists(fallback_state_path(p)):
        _end_fallback("route set", p)
    return read_route(p)


def route_show(path=None):
    """{"mode", "valid", "reason"} - the mode only, never the path. v20: an
    armed route adds "fallback" (its mode), "fallback_active" and
    "fallback_until"; a route without an armed block reads exactly as v19.1."""
    try:
        r = read_route(path)
    except Refused as exc:
        return {"mode": None, "valid": False, "reason": str(exc)[:200], "code": exc.code}
    doc = {"mode": r["mode"], "valid": True, "reason": None}
    if r.get("fallback"):
        doc["fallback"] = r["fallback"]["mode"]
        doc["fallback_active"], doc["fallback_until"] = False, None
        try:
            st = _read_fallback_state(fallback_state_path(path))
        except Refused:
            st = None
        if st and (st["from"], st["to"]) == (r["mode"], r["fallback"]["mode"]) \
                and _now() < st["until"]:
            doc["fallback_active"], doc["fallback_until"] = True, _iso(st["until"])
    return doc


# ---------------------------------------------------------------- fallback (v20)
# Ruling MAIN docs/rulings/2026-10-18-acct-fallback.md. ARMED only by the route
# file's block; the ONE trigger is a confirmed 7-day usage-limit refusal of the
# primary route with a parsed reset; the run that hit it ends ("limit", no in-run
# retry) and the NEXT spawns use the other route until that reset; a limit on the
# fallback halts until the earlier reset; never a third route. No usage
# percentage is read anywhere. Every start, halt and end writes one ledger line.

FALLBACK_STATE = "headless_fallback.json"
FALLBACK_LEDGER = "headless_fallback.jsonl"
_STATE_KEYS = {"since", "until", "from", "to"}
LIMIT_LINE_MAX = 240
WEEK_S = 7 * 86400
_now = time.time  # the one clock of the fallback code; tests patch it
_LIMIT_HIT = re.compile(
    r"\blimit\s+(?:(?:has|have)\s+been\s+|was\s+|is\s+)?(?:reached|hit|exceeded)\b"
    r"|\b(?:reached|hit|exceeded)\s+(?:your|the)\s+(?:[\w-]+\s+){0,2}limit\b", re.I)
_WIN_7D = re.compile(r"\b(?:weekly|7-day|seven-day|7 day)\b", re.I)
_WIN_5H = re.compile(r"\b(?:5-hour|five-hour|5 hour|session)\b", re.I)
_WIN_MODEL = re.compile(r"\b(?:opus|sonnet|haiku)\b", re.I)
_NOT_LIMIT = re.compile(r"proxy|invalid_grant|unauthori[sz]ed|authenticat|\b40[134]\b"
                        r"|unknown pin|econn|network|timed? ?out", re.I)
_EPOCH_RESET = re.compile(r"\|\s*(\d{10})\b")
_ISO_RESET = re.compile(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"
                        r"(?:Z|[+-]\d{2}:?\d{2})?)")
_HUMAN_RESET = re.compile(
    r"\bresets?\s+(?:on\s+)?(?:(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})"
    r"(?:st|nd|rd|th)?,?\s+(?:at\s+)?)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[ap]m)\b"
    r"(?:\s*\((?P<tz>[^)]{1,40})\))?", re.I)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def fallback_state_path(route_file=None):
    """The kit-owned state file beside the route file (no path or account id
    inside it)."""
    return Path(route_path() if route_file is None else route_file).with_name(FALLBACK_STATE)


def fallback_ledger_path(route_file=None):
    """One JSON line per fallback start / halt / end, beside the route file."""
    return Path(route_path() if route_file is None else route_file).with_name(FALLBACK_LEDGER)


def _ledger(event, route_file=None, **fields):
    line = dict({"ts": _iso(_now()), "event": event}, **fields)
    p = fallback_ledger_path(route_file)
    with contextlib.suppress(OSError):
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="ascii", newline="\n") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")


def _epoch_of(value):
    d = _dt.datetime.fromisoformat(value)
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


def _read_fallback_state(path=None):
    """The state with epoch times, None when absent; an unreadable or malformed
    file refuses (route-invalid, fail closed)."""
    p = fallback_state_path() if path is None else Path(path)
    if not os.path.lexists(p):
        return None
    try:
        doc = json.loads(p.read_text(encoding="ascii"))
        if not isinstance(doc, dict) or not (
                _STATE_KEYS <= set(doc) <= _STATE_KEYS | {"halt_until"}):
            raise ValueError("keys")
        if doc["from"] not in ROUTE_MODES or doc["to"] not in ROUTE_MODES:
            raise ValueError("modes")
        out = {"from": doc["from"], "to": doc["to"], "since": _epoch_of(doc["since"]),
               "until": _epoch_of(doc["until"])}
        if "halt_until" in doc:
            out["halt_until"] = _epoch_of(doc["halt_until"])
        return out
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise _route_invalid("fallback state unreadable - `route set` or delete it") from None


def _write_fallback_state(st, route_file=None):
    doc = {"since": _iso(st["since"]), "until": _iso(st["until"]),
           "from": st["from"], "to": st["to"]}
    if st.get("halt_until"):
        doc["halt_until"] = _iso(st["halt_until"])
    _atomic_write(fallback_state_path(route_file), json.dumps(doc, sort_keys=True) + "\n",
                  verify=True)


def _end_fallback(reason, route_file=None):
    p = fallback_state_path(route_file)
    with contextlib.suppress(OSError, Refused):
        st = _read_fallback_state(p)
        if st:
            _ledger("end", route_file, reason=reason, **{"from": st["from"], "to": st["to"]})
    with contextlib.suppress(FileNotFoundError):
        p.unlink()


def start_fallback(route, until, route_file=None):
    """Move the NEXT spawns to the armed fallback until `until` (epoch)."""
    fb = route.get("fallback")
    if not fb:
        raise Refused("no armed fallback in the route", code="route-invalid")
    st = {"since": _now(), "until": float(until), "from": route["mode"], "to": fb["mode"]}
    _write_fallback_state(st, route_file)
    _ledger("start", route_file, until=_iso(until), **{"from": st["from"], "to": st["to"]})
    return st


def effective_route(route, route_file=None):
    """(route to run on, falling_back), the state read fresh. Ends a fallback
    whose reset passed or that no longer matches the route; refuses
    "fallback-halted" while a limit on the fallback route holds."""
    p = fallback_state_path(route_file)
    if not os.path.lexists(p):
        return route, False
    fb = route.get("fallback")
    if fb is None:
        _end_fallback("disarmed", route_file)
        return route, False
    st = _read_fallback_state(p)
    if (st["from"], st["to"]) != (route["mode"], fb["mode"]):
        _end_fallback("route changed", route_file)
        return route, False
    now = _now()
    if now >= st["until"]:
        _end_fallback("reset", route_file)
        return route, False
    if st.get("halt_until") and now < st["halt_until"]:
        raise Refused("usage limit on the fallback route too - halted until "
                      + str(_iso(st["halt_until"])), code="fallback-halted")
    return dict(fb), True


def _zone(name):
    """None = local time; False = a zone the kit cannot resolve (no reset)."""
    if name is None:
        return None
    n = name.strip()
    if n.upper() in ("UTC", "GMT", "Z"):
        return _dt.UTC
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(n)
    except Exception:  # unknown zone or no tz database: cannot tell
        return False


def _parse_reset(line, now):
    m = _EPOCH_RESET.search(line)
    if m:
        return float(m.group(1))
    m = _ISO_RESET.search(line)
    if m:
        try:
            return _epoch_of(m.group(1))
        except ValueError:
            return None
    m = _HUMAN_RESET.search(line)
    if not m:
        return None
    tz = _zone(m.group("tz"))
    if tz is False:
        return None
    h, mi = int(m.group("h")), int(m.group("m") or 0)
    if not 1 <= h <= 12 or mi > 59:
        return None
    h = h % 12 + (12 if m.group("ap").lower() == "pm" else 0)
    base = (_dt.datetime.fromtimestamp(now, tz) if tz
            else _dt.datetime.fromtimestamp(now).astimezone())
    if m.group("mon"):
        mon = m.group("mon")[:3].lower()
        if mon not in _MONTHS:
            return None
        for year in (base.year, base.year + 1):
            try:
                cand = base.replace(year=year, month=_MONTHS.index(mon) + 1,
                                    day=int(m.group("day")), hour=h, minute=mi, second=0,
                                    microsecond=0)
            except ValueError:
                return None
            if cand.timestamp() > now - 86400:
                return cand.timestamp()
        return None
    cand = base.replace(hour=h, minute=mi, second=0, microsecond=0)
    if cand.timestamp() <= now:
        cand = cand + _dt.timedelta(days=1)
    return cand.timestamp()


def classify_limit(text, now=None):
    """A failed run's own message -> None (no usage-limit refusal seen) or
    {"window": "7d" | "5h" | None, "until": epoch | None}. window None = a
    limit whose window the kit cannot tell (never a trigger). Only a short line
    saying a limit was REACHED counts - a percentage or a warning never does; a
    line naming a proxy / auth / network cause, or a model-scoped weekly limit
    (Opus ...), is window None; "until" is kept only inside (now, now + 7 d]."""
    now = _now() if now is None else now
    found = None
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or len(line) > LIMIT_LINE_MAX or not _LIMIT_HIT.search(line):
            continue
        w7, w5 = bool(_WIN_7D.search(line)), bool(_WIN_5H.search(line))
        window = "7d" if w7 and not w5 else "5h" if w5 and not w7 else None
        if _NOT_LIMIT.search(line) or (window == "7d" and _WIN_MODEL.search(line)):
            window = None
        until = _parse_reset(line, now)
        if until is not None and not now < until <= now + WEEK_S + 3600:
            until = None
        c = {"window": window, "until": until}
        if found is None or (c["window"] == "7d" and found["window"] != "7d"):
            found = c
    return found


def _limit_after_run(route, falling_back, cls, route_file=None):
    """After a run whose own message classify_limit() read as a limit: on the
    fallback route, halt until the earlier reset; on the primary, start the
    fallback only for an armed route, a 7-day window and a parsed reset."""
    if falling_back:
        st = _read_fallback_state(fallback_state_path(route_file))
        if not st:
            return
        halt = st["until"]
        if cls.get("until") and cls["until"] < halt:
            halt = cls["until"]
        st["halt_until"] = halt
        _write_fallback_state(st, route_file)
        _ledger("halt", route_file, until=_iso(halt), window=cls["window"] or "unknown",
                **{"from": st["from"], "to": st["to"]})
    elif route and route.get("fallback") and cls["window"] == "7d" and cls.get("until"):
        start_fallback(route, cls["until"], route_file)


# ---------------------------------------------------------------- note rules

def _base(name):
    return Path(str(name or "")).name


def _tokens(text):
    return [t for t in re.split(r"[^A-Z0-9]+", text.upper()) if t]


def _has_marker(tokens, marker):
    joined = "-" + "-".join(tokens) + "-"
    return "-" + marker + "-" in joined


def _title(head):
    for line in (head or "").splitlines():
        if line.strip():
            return _TITLE.match(line.strip())
    return None


def note_sender(name, head=""):
    """Sender code from the name (`...-from-XX-...` or `from-XX-...`), else from
    the title line (`# From XX - ...`), else None."""
    m = _SENDER.search(_base(name))
    if m:
        return m.group(1)
    t = _title(head)
    return t.group(1) if t else None


def note_class(name, head=""):
    """The word after the sender (ORDER, FIX, ANSWER, ...), upper-cased, or None."""
    m = _CLASS.search(_base(name))
    if m:
        return m.group(1).upper()
    t = _title(head)
    return t.group(2).upper() if t and t.group(2) else None


def _never_damped(name, head):
    cls = note_class(name, head)
    t = _title(head)
    title_cls = t.group(2).upper() if t and t.group(2) else None
    return cls in NEVER_DAMP or title_cls in NEVER_DAMP


def _marked_terminal(name, head):
    tokens = _tokens(_base(name))
    if "TERMINAL" in tokens or "NOREPLY" in tokens or _has_marker(tokens, "NO-REPLY"):
        return True
    for line in (head or "").splitlines():
        if line.lstrip().startswith(">"):
            continue  # a quoted marker belongs to the quoted note, not this one
        text = line.strip().lstrip("#*- \t").rstrip("* \t").upper()
        if text and _MARKER_LINE.match(text):
            return True
    return False


def should_skip(name, own_code, head=""):
    """'self', 'terminal' or None. head = the note's first few hundred chars.
    Terminal means a whole TERMINAL / NOREPLY / NO-REPLY token in the name or a
    line that is only such a marker; a body sentence that mentions the rule is
    not a marker. ORDER, FIX and RULING notes are never damped."""
    if note_sender(name, head) == own_code:
        return "self"
    if _never_damped(name, head):
        return None
    return "terminal" if _marked_terminal(name, head) else None


def pick_effort(name, effort=None):
    """Explicit effort (low|medium|high) wins; else low for acknowledgement
    tokens (whole tokens only - TRACK and BACKOFF are not ACK), medium otherwise,
    and never low for ORDER / FIX / RULING."""
    if effort is not None:
        if effort not in EFFORTS:
            raise Refused(f"effort {effort!r} not in {EFFORTS}")
        return effort
    if note_class(name) in NEVER_DAMP:
        return "medium"
    tokens = _tokens(_base(name))
    return "low" if any(_has_marker(tokens, m) for m in ACK_MARKERS) else "medium"


def pick_model(writes_code, model=None):
    """Explicit model alias or exact id wins; else opus for code, sonnet otherwise."""
    if model is not None:
        if not isinstance(model, str) or not _MODEL.match(model):
            raise Refused(f"model {model!r} is not an alias or a claude-* id")
        return model
    return "opus" if writes_code else "sonnet"


# ---------------------------------------------------------------- argv

def _norm(path):
    return os.path.normcase(os.path.realpath(path))


def _find_on_path(name, environ=None, cwd=None):
    """Like shutil.which, but never answers from the working directory: empty,
    relative and cwd-equal PATH entries are skipped."""
    env = os.environ if environ is None else environ
    here = _norm(cwd or Path.cwd())
    exts = [""]
    if sys.platform == "win32":
        exts = [e for e in env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for entry in env.get("PATH", "").split(os.pathsep):
        d = entry.strip().strip('"')
        if not d or not Path(d).is_absolute() or _norm(d) == here:
            continue
        for ext in exts:
            p = Path(d) / (name + ext)
            if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)):
                return str(p)
    return None


def claude_exe(which=None, environ=None, cwd=None):
    """The real claude executable, never one in the working directory. The npm
    shim claude.CMD would run under cmd.exe; prefer the binary it wraps so no
    console host is involved."""
    path = which("claude") if which else _find_on_path("claude", environ, cwd)
    if not path:
        raise Refused("claude not found on PATH (working directory excluded)")
    if not Path(path).is_absolute() or _norm(Path(path).parent) == _norm(cwd or Path.cwd()):
        raise Refused("claude resolved from the working directory")
    if path.lower().endswith(".cmd"):
        real = (Path(path).parent / "node_modules" / "@anthropic-ai" /
                "claude-code" / "bin" / "claude.exe")
        if real.exists():
            return str(real)
    return path


def _check_sources(sources):
    parts = [s.strip() for s in str(sources or "").split(",")]
    if not parts or any(p not in SOURCES for p in parts) or len(set(parts)) != len(parts):
        raise Refused(f"setting sources {sources!r} not a subset of {SOURCES}")
    return ",".join(parts)


def _flag(arg):
    return str(arg).split("=", 1)[0].lower()


def build_argv(exe, prompt, model, effort, bare=False, rules_file=None,
               extra=(), stdin=False, persist=False, setting_sources=DEFAULT_SOURCES,
               output_format="json", session_id=None, resume=None):
    argv = [exe, "-p"]
    if not stdin:
        argv.append(prompt)
    argv += ["--output-format", output_format]
    if output_format == "stream-json":
        argv.append("--verbose")
    resuming = any(_flag(a) in ("--session-id", "--resume", "--continue") for a in extra)
    if not (persist or session_id or resume or resuming):
        argv.append("--no-session-persistence")
    for flag, value in (("--session-id", session_id), ("--resume", resume)):
        if value is not None:
            if not _TOKEN_ID.match(str(value)):
                raise Refused(f"{flag} value is not a plain id")
            argv += [flag, str(value)]
    argv += ["--model", model, "--effort", effort]
    if bare:
        argv.append("--bare")
        if rules_file:
            argv += ["--append-system-prompt-file", str(rules_file)]
    else:
        argv += ["--strict-mcp-config", "--setting-sources", _check_sources(setting_sources)]
    return argv + list(extra)


def check_door(bare=False, extra=(), floors_in_hooks=False):
    """Refuse what must never reach the CLI: any fallback flag, ever; --bare
    smuggled through extra (use bare=); --bare when floors live in hooks."""
    flags = [_flag(a) for a in extra]
    if any("fallback" in f for f in flags):
        raise Refused("fallback flags are refused - fail closed, no fallback ever")
    if "--bare" in flags:
        raise Refused("--bare goes through bare=, not extra")
    if bare and floors_in_hooks:
        raise Refused("--bare refused: this tree's floors live in hooks, which --bare skips")


# ---------------------------------------------------------------- budget

def _try_os_lock(fd):
    """Non-blocking exclusive lock on byte 0 of fd. True = held."""
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _os_unlock(fd):
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


class RunBudget:
    """Runs started per rolling window, persisted as epoch seconds. A missing
    file is zero runs; a file that exists but cannot be read or parsed REFUSES
    every start until a person repairs or removes it (fail closed). Starts are
    counted under an exclusive lock file next to the budget file."""

    def __init__(self, path, cap=RUNS_CAP, window=WINDOW_S, clock=time.time,
                 lock_wait=10.0, lock_stale=120.0):
        self.path, self.cap, self.window, self.clock = Path(path), cap, window, clock
        self.lock_wait, self.lock_stale = lock_wait, lock_stale

    def _load(self):
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise BudgetUnreadable(f"budget file unreadable: {exc.__class__.__name__}") from None
        try:
            starts = json.loads(text)["starts"]
        except (ValueError, KeyError, TypeError):
            raise BudgetUnreadable("budget file corrupt - repair or remove it") from None
        if not isinstance(starts, list):
            raise BudgetUnreadable("budget file corrupt - repair or remove it")
        floor = self.clock() - self.window
        return sorted(s for s in starts if isinstance(s, (int, float))
                      and not isinstance(s, bool) and s > floor)

    def readable(self):
        try:
            self._load()
        except BudgetUnreadable:
            return False
        return True

    def used(self):
        try:
            return len(self._load())
        except BudgetUnreadable:
            return self.cap

    def can_start(self):
        try:
            return len(self._load()) < self.cap
        except BudgetUnreadable:
            return False

    def frees_at(self):
        """Epoch when the count next drops, or None when nothing is counted."""
        try:
            starts = self._load()
        except BudgetUnreadable:
            return None
        return starts[0] + self.window if starts else None

    @contextlib.contextmanager
    def _lock(self):
        """v10: an OS byte-range lock on <budget>.lock, a file that is never
        unlinked. The OS frees the lock when its holder's handle closes, so a
        dead holder frees it at once; no stale timer, no unlink race (RSC 1540
        gap 3). lock_stale is kept for the signature and is unused."""
        lock = self.path.with_name(self.path.name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_wait
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            raise Refused(f"budget lock unopenable: {exc.__class__.__name__}",
                          code="budget-lock-unopenable") from None
        try:
            while not _try_os_lock(fd):
                if time.monotonic() >= deadline:
                    raise Refused("budget lock busy", code="budget-lock-busy")
                time.sleep(0.05)
            try:
                yield
            finally:
                _os_unlock(fd)
        finally:
            os.close(fd)

    def start(self):
        """Count one start under the lock. True = counted; False = cap reached.
        Raises Refused (BudgetUnreadable, or lock busy) - fail closed."""
        with self._lock():
            starts = self._load()
            if len(starts) >= self.cap:
                return False
            _atomic_write(self.path, json.dumps({"starts": [*starts, self.clock()]}))
            return True

    def try_start(self):
        try:
            return self.start()
        except Refused:
            return False

    def record(self):
        """v3 name: count a start unconditionally (still under the lock, and
        still refusing on an unreadable file)."""
        with self._lock():
            starts = [*self._load(), self.clock()]
            _atomic_write(self.path, json.dumps({"starts": starts}))


# ---------------------------------------------------------------- status/usage

def _tmp_name(path):
    """A temp name no other writer (process or thread) can share (v13)."""
    import threading
    return path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}."
                          f"{os.urandom(4).hex()}.tmp")


def _atomic_write(path, text, verify=False):
    """temp + os.replace; with verify=True the target is read back and the
    write retried until it holds `text` (v13, progress files)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    want = text.encode("ascii")
    for _round in range(ATOMIC_TRIES if verify else 1):
        tmp = _tmp_name(path)
        try:
            tmp.write_text(text, encoding="ascii", newline="\n")
            for attempt in range(ATOMIC_TRIES):
                try:
                    tmp.replace(path)
                    break
                except PermissionError:  # Windows: a reader holds the target briefly
                    if attempt == ATOMIC_TRIES - 1:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        if not verify:
            return
        try:
            if path.read_bytes() == want:
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise OSError(f"progress write to {path.name} could not be confirmed")


def _iso(epoch):
    if not epoch or epoch <= 0:
        return None
    try:
        return _dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return (_EPOCH + _dt.timedelta(seconds=epoch)).isoformat(timespec="seconds")


def write_status(root, code, state, task, task_started, budget, task_eta_s=None,
                 next_tick=None, clock=time.time, reason=None, route=None, fallback=False):
    """Schema 1 of ops/loop/control/inbox_status.json (MAIN 0915 section 1).
    state is one of STATES. v14: an optional "reason" (one line, at most 80
    chars) says why a run is blocked or refused; absent otherwise."""
    doc = {
        "schema": 1, "kit": KIT_VERSION, "code": code,
        "updated": _iso(clock()), "state": state, "task": task[:24],
        "task_started": _iso(task_started), "task_eta_s": task_eta_s,
        "next_tick": _iso(next_tick), "runs_in_window": budget.used(),
        "runs_cap": budget.cap, "window_s": budget.window,
        "cap_frees_at": _iso(budget.frees_at()),
    }
    if reason:
        doc["reason"] = " ".join(str(reason).split())[:80]
    if route in ROUTE_MODES:
        doc["route"] = route
    if fallback:  # v20: the ACCT-FALLBACK marker, only while falling back
        doc["fallback"] = True
    _atomic_write(Path(root) / STATUS_REL, json.dumps(doc, indent=1))
    return doc


def _status_quietly(root, code, state, task, budget, started=None, reason=None, route=None,
                    fallback=False):
    with contextlib.suppress(OSError):
        write_status(root, code, state, task, started, budget, reason=reason, route=route,
                     fallback=fallback)


def _refused_status(root, code, budget, exc):
    """v14: "blocked" for an outside cause (Blocked), else "refused"."""
    state = "blocked" if isinstance(exc, Blocked) else "refused"
    if getattr(exc, "code", None) == "fallback-halted":  # v20: a limit, both routes
        _status_quietly(root, code, "limit", "Turn Limit Reached", budget, reason=str(exc))
        return
    _status_quietly(root, code, state, REFUSED_TASK, budget, reason=str(exc))


def _checklist_rows(checklist):
    """FLEET-COMMON item 13 d: the remaining tasks as [{id, task, state, eta_s}]."""
    if not isinstance(checklist, (list, tuple)):
        raise ValueError("checklist must be a list of {id, task, state, eta_s}")
    rows = []
    for r in checklist[:CHECKLIST_MAX]:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) \
                or not _CHECK_ID.match(r["id"]) or not isinstance(r.get("task"), str) \
                or not r["task"].strip():
            raise ValueError(f"bad checklist row {r!r}")
        state, eta = r.get("state"), r.get("eta_s")
        if state is not None and not isinstance(state, str):
            raise ValueError(f"bad checklist state {state!r}")
        row = {"id": r["id"], "task": " ".join(r["task"].split())[:120],
               "state": None if state is None else " ".join(state.split())[:40],
               "eta_s": None if eta is None else max(0, int(eta))}
        # v20 (CHECKLIST-ETA-CLOCK): optional pct and started (epoch seconds).
        if isinstance(r.get("pct"), (int, float)) and not isinstance(r["pct"], bool):
            row["pct"] = max(0, min(100, int(r["pct"])))
        if isinstance(r.get("started"), (int, float)) and not isinstance(r["started"], bool) \
                and r["started"] > 0:
            row["started"] = float(r["started"])
        rows.append(row)
    return rows


def _started_iso(value):
    """v20: a "started" value (epoch seconds or ISO text) as _iso text, or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return _iso(value)
    try:
        return _iso(_dt.datetime.fromisoformat(str(value).strip()).timestamp())
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def main_checkout(path):
    """The MAIN working tree for path, even when path is a linked worktree: its
    .git is then a FILE `gitdir: <main>/.git/worktrees/<name>` (absolute, or
    relative to path). Anything else answers path itself. File-only."""
    path = Path(path).resolve()
    dotgit = path / ".git"
    try:
        raw = dotgit.read_text(encoding="utf-8").strip() if dotgit.is_file() else ""
    except (OSError, UnicodeError):  # v15 (RC 1925 a): non-UTF-8 link file
        raw = ""
    if raw.startswith("gitdir:"):
        gitdir = Path(raw.split(":", 1)[1].strip())
        gitdir = (gitdir if gitdir.is_absolute() else path / gitdir).resolve()
        if gitdir.parent.name == "worktrees":
            return gitdir.parents[2]
    return path


def write_progress(root, task, pct, step, eta_s, status, clock=time.time, checklist=None,
                   reason=None, owner=None, started=None):
    """FLEET-COMMON item 12: ops/loop/control/progress/<task>.json with
    {task, pct, step, eta_s, status: running|done|failed, updated}, plus
    "checklist" (item 13 d, remaining tasks) when one is passed. v12: in the
    MAIN checkout of root even when root is a linked worktree; the returned
    doc adds "path", the file written (the file itself does not carry it).
    v16: "owner" {"pid", "start"} - owner= a pid (0 = none), else
    default_owner(); omitted when there is none.
    v20 (CHECKLIST-ETA-CLOCK): "started" (ISO, like "updated") - started=
    epoch or ISO; else carried from the file's last write unless that run
    ended (done/failed) and this one is running again; else now. Readers
    treat it as optional: older files lack it."""
    if not isinstance(task, str) or not _TASK.match(task):
        raise ValueError(f"task name {task!r} must be a plain file stem")
    if status not in PROGRESS_STATES:
        raise ValueError(f"status {status!r} not in {PROGRESS_STATES}")
    doc = {"task": task, "pct": max(0, min(100, int(pct))), "step": str(step)[:200],
           "eta_s": None if eta_s is None else max(0, int(eta_s)),
           "status": status, "updated": _iso(clock())}
    if checklist is not None:
        doc["checklist"] = _checklist_rows(checklist)
    if reason:
        doc["reason"] = " ".join(str(reason).split())[:120]
    who = default_owner() if owner is None else (_owner_doc(owner) if int(owner) > 0 else None)
    if who:
        doc["owner"] = who
    path = main_checkout(root) / PROGRESS_REL / (task + ".json")
    begun = _started_iso(started)
    if begun is None:
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            prev = None
        if isinstance(prev, dict) and not (status == "running"
                                           and prev.get("status") in ("done", "failed")):
            begun = _started_iso(prev.get("started"))
    doc["started"] = begun or doc["updated"]
    _atomic_write(path, json.dumps(doc), verify=True)
    return dict(doc, path=str(path))


# ---------------------------------------------------------------- owners (v16)

def _win_procs():
    """{pid: (ppid, exe name lower)} from a toolhelp snapshot; {} on failure."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    out = {}
    try:
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            out[pe.th32ProcessID] = (pe.th32ParentProcessID, pe.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return out


def _posix_parent(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        name = raw[raw.index("(") + 1:raw.rindex(")")]
        return int(raw[raw.rindex(")") + 2:].split()[1]), name.lower()
    except (OSError, ValueError, IndexError):
        return None


def proc_start(pid):
    """Creation time of pid (epoch seconds), or None when unknown."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            ft = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
                return None
            ticks = (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
            return round(ticks / 1e7 - 11644473600.0, 3)
        finally:
            k32.CloseHandle(h)
    try:
        boot = None
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                boot = int(line.split()[1])
        raw = Path(f"/proc/{pid}/stat").read_text()
        ticks = int(raw[raw.rindex(")") + 2:].split()[19])
        return None if boot is None else round(boot + ticks / os.sysconf("SC_CLK_TCK"), 3)
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def owner_alive(owner):
    """True / False / None (unknown) for a progress row's owner
    {"pid", "start"}. A pid whose creation time differs from "start" by more
    than _START_SLACK_S was reused: False."""
    if not isinstance(owner, dict):
        return None
    pid = owner.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            err = ctypes.get_last_error()
            return False if err == 87 else None  # ERROR_INVALID_PARAMETER: no such pid
        try:
            code = wintypes.DWORD()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:
                return False  # exited (STILL_ACTIVE is 259)
        finally:
            k32.CloseHandle(h)
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            pass
    want, have = owner.get("start"), proc_start(pid)
    if isinstance(want, (int, float)) and not isinstance(want, bool) and have is not None:
        return abs(have - want) <= _START_SLACK_S
    return True


def _owner_doc(pid):
    return {"pid": int(pid), "start": proc_start(pid)}


def default_owner(env=None, procs=None, me=None):
    """The owner write_progress records when none is passed: env
    FLEET_PROGRESS_OWNER (a pid, or "none"), else the nearest ancestor named
    in OWNER_NAMES, else None."""
    env = os.environ if env is None else env
    raw = (env.get(OWNER_ENV) or "").strip()
    if raw.lower() in ("none", "0", "off"):
        return None
    if raw.isdigit():
        return _owner_doc(int(raw))
    me = os.getpid() if me is None else me
    if procs is None:
        procs = _win_procs() if sys.platform == "win32" else None
    seen, pid = set(), me
    for _ in range(32):
        if procs is not None:
            if pid not in procs:
                return None
            ppid, _name = procs[pid]
        else:
            got = _posix_parent(pid)
            if not got:
                return None
            ppid = got[0]
        if not ppid or ppid in seen or ppid == pid:
            return None
        seen.add(pid)
        name = procs[ppid][1] if procs is not None and ppid in procs else \
            ((_posix_parent(ppid) or (0, ""))[1] if procs is None else "")
        if name in OWNER_NAMES:
            return _owner_doc(ppid)
        pid = ppid
    return None


def _age_s(doc, now):
    when = doc.get("updated") if isinstance(doc, dict) else None
    try:
        then = _dt.datetime.fromisoformat(when).timestamp()
    except (TypeError, ValueError):
        return None
    return now - then


def progress_abandoned(doc, now=None, alive=owner_alive):
    """v16: a running/blocked row whose owner is dead, or that has been
    silent over ABANDON_S, belongs to no live run."""
    if not isinstance(doc, dict) or doc.get("status") not in ("running", "blocked"):
        return False
    if alive(doc.get("owner")) is False:
        return True
    age = _age_s(doc, time.time() if now is None else now)
    return age is not None and age > ABANDON_S


def _read_progress(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def close_progress(root, task, reason="run ended without a final status", clock=time.time):
    """v16: when progress/<task>.json still says running (or blocked), write
    it as failed, keeping pct, step, eta and checklist and adding reason.
    Returns the doc written, or None (no file, or already final)."""
    if not isinstance(task, str) or not _TASK.match(task):
        return None
    path = main_checkout(root) / PROGRESS_REL / (task + ".json")
    doc = _read_progress(path)
    if not doc or doc.get("status") not in ("running", "blocked"):
        return None
    doc.update(status="failed", updated=_iso(clock()),
               reason=" ".join(str(reason).split())[:120])
    _atomic_write(path, json.dumps(doc), verify=True)
    return doc


def close_owned_progress(root, pid, reason="owner process ended without a final status",
                         clock=time.time):
    """v16: close_progress() for every row in root's progress folder whose
    owner pid is pid. Returns the task names closed."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return []
    folder = main_checkout(root) / PROGRESS_REL
    try:
        names = sorted(f for f in folder.iterdir() if f.suffix == ".json")
    except OSError:
        return []
    closed = []
    for f in names:
        doc = _read_progress(f)
        owner = doc.get("owner") if doc else None
        if isinstance(owner, dict) and owner.get("pid") == pid and \
                close_progress(root, f.stem, reason, clock):
            closed.append(f.stem)
    return closed


def run_kind(note, kind=None, head=""):
    """build | inbox | triage | order as given; else inbox for a channel-note
    name, unattributed for an empty note, build for any other label (v8).
    v16: a note whose class (note_class: name, else the title in head) is
    ORDER / FIX / RULING is "order" when kind is None or "inbox"."""
    if kind is not None and kind not in KINDS:
        raise Refused(f"kind {kind!r} not in {KINDS}")
    if kind in (None, "inbox") and note_class(note, head) in NEVER_DAMP:
        return "order"
    if kind is not None:
        return kind
    base = _base(note)
    if not base:
        return "unattributed"
    return "inbox" if _NOTE_SENDER.search(base) else "build"


def usage_line(result, code, note, model, effort, bare, rc, duration_s, error=None,
               kind=None, slot=None, route=None, fallback=False, unit=None):
    r = result if isinstance(result, dict) else {}
    u = r.get("usage") if isinstance(r.get("usage"), dict) else {}
    return {
        "ts": _iso(time.time()), "kit": KIT_VERSION, "code": code, "note": note,
        "model": model, "effort": effort, "bare": bare, "rc": rc,
        "duration_s": round(duration_s, 1),
        "input_tokens": u.get("input_tokens"),
        "cache_creation": u.get("cache_creation_input_tokens"),
        "cache_read": u.get("cache_read_input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "cost_usd": r.get("total_cost_usd"),
        "num_turns": r.get("num_turns"),
        "is_error": r.get("is_error") if isinstance(r.get("is_error"), bool) else None,
        "subtype": r.get("subtype") if isinstance(r.get("subtype"), str) else None,
        "error": error,
        "kind": run_kind(note, kind),
        "slot": str(slot) if slot not in (None, "") else None,
        "route": route if route in ROUTE_MODES else None,
        "kit_patch": KIT_PATCH,
        "fallback": bool(fallback),
        "limit": None,
        "unit": str(unit)[:64] if unit not in (None, "") else None,
    }


# ---------------------------------------------------------------- provenance

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(top, *args, git=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    exe = git or _find_on_path("git")
    if not exe:
        raise OSError("git not found on PATH (working directory excluded)")
    return subprocess.run([exe, "--no-replace-objects", "-C", str(top), *args],
                          capture_output=True, check=True, timeout=60, env=env,
                          creationflags=_NO_WINDOW).stdout


def verify_main(note_path, main_outbox, rel=None, git=None):
    """True only when MAIN's COMMITTED copy of this note is byte-identical:
    the HEAD blob at <outbox>/<rel> (replace refs ignored) hashes to the note's
    SHA-256 and MAIN's index names the same object. A working-tree copy alone
    proves nothing (assume-unchanged, skip-worktree, restored mtimes). rel is
    the path inside the outbox (default: the note's file name; a bundle file is
    "<bundle dir>/<file>"). Any git error = False (fail closed)."""
    note = Path(note_path)
    rel = Path(rel) if rel else Path(note.name)
    if not note.is_file() or rel.is_absolute() or ".." in rel.parts:
        return False
    try:
        top = Path(_git(main_outbox, "rev-parse", "--show-toplevel", git=git)
                   .decode("utf-8").strip())
        path = (Path(main_outbox).resolve() / rel).relative_to(top.resolve()).as_posix()
        blob = _git(top, "cat-file", "blob", "HEAD:" + path, git=git)
        head_oid = _git(top, "rev-parse", "--verify", "HEAD:" + path, git=git).split()
        staged = _git(top, "ls-files", "-s", "--", path, git=git).split()
        want = sha256_file(note)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    if len(head_oid) != 1 or len(staged) < 2 or staged[1] != head_oid[0]:
        return False
    return hashlib.sha256(blob).hexdigest() == want


# ---------------------------------------------------------------- conformance

KIT_REL = Path("ops/fleet_kit")
BEGIN, END = "<!-- FLEET-COMMON BEGIN -->\n", "<!-- FLEET-COMMON END -->"


def conformance(root):
    """Problems with this repo's copy of the kit; [] = conforms. Every repo runs
    `assert conformance(repo_root) == []` in its own suite, so a local edit to a
    kit file, or to the FLEET-COMMON block in CLAUDE.md, fails that repo's CI.
    (Editing a file AND the manifest together passes here; MAIN's drift sweep
    compares the manifest against MAIN's and catches that.)"""
    root = Path(root)
    kit = root / KIT_REL
    try:
        man = json.loads((kit / "MANIFEST.json").read_text(encoding="ascii"))
    except (OSError, ValueError):
        return ["kit manifest missing or unreadable"]
    problems = []
    if man.get("version") != KIT_VERSION:
        problems.append(f"manifest v{man.get('version')} != kit v{KIT_VERSION}")
    for name, want in sorted(man.get("files", {}).items()):
        f = kit / name
        if not f.is_file() or sha256_file(f) != want:
            problems.append(f"kit file missing or edited: {name}")
    try:
        text = (root / "CLAUDE.md").read_bytes().decode("ascii")
    except (OSError, UnicodeDecodeError):
        return [*problems, "CLAUDE.md missing or not ASCII"]
    i, j = text.find(BEGIN), text.find(END)
    if "\r\n" in text:
        problems.append("CLAUDE.md is CRLF; the fleet rule is LF")
    elif i < 0 or j < i:
        problems.append("CLAUDE.md lacks the FLEET-COMMON markers")
    elif hashlib.sha256(text[i + len(BEGIN):j].encode("ascii")).hexdigest() != \
            man.get("common_block_sha256"):
        problems.append("CLAUDE.md FLEET-COMMON block edited")
    else:
        lines = text.split("\n")
        for word, mark in (("BEGIN", BEGIN.rstrip("\n")), ("END", END)):
            hits = [ln for ln in lines if mark in ln]
            if len(hits) != 1 or hits[0] != mark:
                problems.append(f"CLAUDE.md FLEET-COMMON {word} marker is not alone on one line")
    return problems


# ---------------------------------------------------------------- spawn

# v21 (CS-1231): seconds a timed-out run waits for its killed direct child.
PIPE_GRACE = 30.0
_JOB_KILL_ON_CLOSE = 0x2000
_JOB_BREAKAWAY_OK = 0x0800
_CREATE_SUSPENDED = 0x00000004


class _WinJob:
    """v21 (CS FIX 2026-10-21-0420): a Windows job object holding the child's
    whole tree. Membership is inherited at creation and survives the parent's
    exit, so an orphaned grandchild (re-parented, missed by taskkill /T) is
    still in the job. Kill-on-close: if this process dies first, the OS ends
    the tree. A child that asks for breakaway may leave (BREAKAWAY_OK); none is
    forced out. close(kill=False) clears kill-on-close first, so a run that
    ended normally leaves its descendants as before. create() returns None
    when any call fails; the caller then falls back to taskkill only."""

    def __init__(self, k32, handle, info):
        self._k32, self.handle, self._info = k32, handle, info

    @classmethod
    def create(cls):
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class _Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                            ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class _Ext(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io),
                            ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                    ctypes.c_void_p, wintypes.DWORD)
            k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
            k32.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = k32.CreateJobObjectW(None, None)
            if not handle:
                return None
            job = cls(k32, handle, _Ext())
            if not job._limits(_JOB_KILL_ON_CLOSE | _JOB_BREAKAWAY_OK):
                job.close(kill=False)
                return None
            return job
        except (OSError, AttributeError, ValueError):
            return None

    def _limits(self, flags):
        import ctypes
        self._info.BasicLimitInformation.LimitFlags = flags
        return bool(self._k32.SetInformationJobObject(
            self.handle, 9, ctypes.byref(self._info), ctypes.sizeof(self._info)))

    def adopt(self, ph):
        """Assign the SUSPENDED child (its Popen process handle) to the job,
        then resume it. Returns True when it is in the job. A failed resume
        raises OSError (the caller kills the child): a child left suspended
        would hang the run. Never called with a pid: only the handle of the
        process this _run created, so no other process can enter the job."""
        import ctypes
        inside = bool(self._k32.AssignProcessToJobObject(self.handle, int(ph)))
        nt = ctypes.WinDLL("ntdll")
        nt.NtResumeProcess.argtypes = (ctypes.c_void_p,)
        if nt.NtResumeProcess(ctypes.c_void_p(int(ph))) != 0:
            raise OSError("NtResumeProcess failed")
        return inside

    def kill(self):
        with contextlib.suppress(OSError):
            self._k32.TerminateJobObject(self.handle, 1)

    def close(self, kill):
        if not self.handle:
            return
        with contextlib.suppress(OSError):
            if kill:
                self.kill()
            else:
                self._limits(_JOB_BREAKAWAY_OK)  # survivors of a normal end stay
            self._k32.CloseHandle(self.handle)
        self.handle = None


def _kill_tree(proc, grace=5.0, job=None):
    """Kill the child and everything it started. Windows: v21 (CS-1231) the
    run's job object first (it reaches an orphaned grandchild that taskkill /T
    misses), then taskkill /T /F as before.
    POSIX (v10, RC 1915): the child leads its own session (launch() starts it
    with start_new_session=True), so SIGTERM its process group, wait `grace`
    seconds, then SIGKILL the group. proc.kill() stays the last resort."""
    if job is not None:
        job.kill()
    if sys.platform == "win32":
        sysroot = os.environ.get("SYSTEMROOT")
        tk = str(Path(sysroot) / "System32" / "taskkill.exe") if sysroot else \
            _find_on_path("taskkill")
        if tk:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run([tk, "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                               timeout=30, creationflags=_NO_WINDOW)
    else:
        import signal
        with contextlib.suppress(OSError):
            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid:  # only a group the child leads, never ours
                with contextlib.suppress(OSError):
                    os.killpg(pgid, signal.SIGTERM)
                with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                    proc.wait(timeout=grace)
                with contextlib.suppress(OSError):
                    os.killpg(pgid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _decode(data, text, encoding, errors):
    if data is None or not text:
        return data
    import locale
    out = data.decode(encoding or locale.getpreferredencoding(False), errors or "strict")
    return out.replace("\r\n", "\n").replace("\r", "\n")


def _run(argv, input=None, timeout=None, capture_output=False, stdin=None, on_start=None,
         creationflags=_NO_WINDOW, **kw):
    """subprocess.run, except stdin defaults to DEVNULL, no console window opens
    (a literal creationflags= at Popen, v10) and a timeout kills the whole
    process tree (claude's own children included) before re-raising.
    on_start(pid) is called once the child exists (v6: the governor slot).
    v21 (CS-1231): no pipe is ever held - a PIPE for stdout / stderr and any
    input go through temp files, read once the child ends - so a descendant
    that outlives the child cannot block the return; on Windows the child runs
    in a job object (see _WinJob). A timeout re-raises after at most timeout +
    the kill + PIPE_GRACE seconds; any other exception also kills the tree
    before it propagates."""
    text = bool(kw.pop("text", None)) | bool(kw.pop("universal_newlines", None))
    encoding, errors = kw.pop("encoding", None), kw.pop("errors", None)
    text = text or bool(encoding or errors)
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if sys.platform != "win32":
        kw.setdefault("start_new_session", True)
    with contextlib.ExitStack() as files:
        spools = {}
        for name in ("stdout", "stderr"):
            if kw.get(name) is subprocess.PIPE:
                kw[name] = spools[name] = files.enter_context(tempfile.TemporaryFile())
        if input is not None:
            fin = files.enter_context(tempfile.TemporaryFile())
            if isinstance(input, str):
                import locale
                input = input.encode(encoding or locale.getpreferredencoding(False),
                                     errors or "strict")
            fin.write(input)
            fin.flush()
            fin.seek(0)
            stdin = fin
        elif stdin is None or stdin is subprocess.PIPE:
            stdin = subprocess.DEVNULL
        job = _WinJob.create()
        suspend = _CREATE_SUSPENDED if job is not None else 0
        try:
            proc = subprocess.Popen(argv, stdin=stdin,
                                    creationflags=creationflags | suspend, **kw)
        except BaseException:
            if job is not None:
                job.close(kill=False)
            raise
        clean = False
        ph = getattr(proc, "_handle", None)  # only a real Popen has one
        if job is not None and ph is None:
            job.close(kill=False)  # a stand-in Popen (tests): no job, nothing to resume
            job = None
        try:
            if job is not None:
                try:
                    job.adopt(ph)
                except OSError:
                    _kill_tree(proc, job=job)
                    raise
            if on_start is not None:
                with contextlib.suppress(Exception):
                    on_start(proc.pid)
            try:
                # No pipes are open, so communicate() is wait(); a stand-in
                # Popen may still hand back its own (out, err).
                got = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc, job=job)
                with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
                    proc.communicate(timeout=PIPE_GRACE)
                raise
            except BaseException:
                _kill_tree(proc, job=job)
                raise
            clean = True
        finally:
            if job is not None:
                job.close(kill=not clean)
        out, err = got if isinstance(got, tuple) and len(got) == 2 else (None, None)
        if "stdout" in spools and out is None:
            spools["stdout"].seek(0)
            out = _decode(spools["stdout"].read(), text, encoding, errors)
        if "stderr" in spools and err is None:
            spools["stderr"].seek(0)
            err = _decode(spools["stderr"].read(), text, encoding, errors)
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


launch = _run  # v10 public name (RC 2220 d); same object, same behaviour


def _accepts_on_start(fn):
    import inspect
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "on_start" or p.kind is p.VAR_KEYWORD for p in params)


def _json_or_none(text):
    try:
        return json.loads(text) if text else None
    except (ValueError, TypeError):
        return None


def _result_from_log(log_path):
    """The last {"type": "result"} event of a stream-json log, or None."""
    found = None
    with contextlib.suppress(OSError), Path(log_path).open(encoding="utf-8",
                                                          errors="replace") as fh:
        for line in fh:
            ev = _json_or_none(line.strip())
            if isinstance(ev, dict) and ev.get("type") == "result":
                found = ev
    return found


def _lanes():
    """The sibling kit module fleet_lanes.py, loaded by path (ops/fleet_kit is
    not a package in every tree)."""
    name = f"fleet_kit_lanes_v{KIT_VERSION}"
    if name in sys.modules:
        return sys.modules[name]
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("fleet_lanes.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _governor(root, code, governor, governor_timeout, governor_root, budget, note,
              since=None):
    """The slot context for one run: a no-op when governor is None."""
    if governor is None:
        return contextlib.nullcontext(None)
    lanes = _lanes()
    if governor not in lanes.PRIORITIES:
        raise Refused(f"governor {governor!r} not None or one of {lanes.PRIORITIES}")
    return lanes.governor_slot(
        code, note or "spawn", governor, governor_root, timeout=governor_timeout,
        since=since,
        on_wait=lambda: _status_quietly(root, code, "backoff", "Waiting for Slot", budget))


def _finish(root, code, budget, line, limit=False):
    log = Path(root) / USAGE_REL
    with contextlib.suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="ascii", newline="\n") as fh:
            fh.write(json.dumps(line) + "\n")
    fb = bool(line.get("fallback"))
    if limit:  # v20: the run that hit a usage limit ends "limit" (no in-run retry)
        _status_quietly(root, code, "limit", "Turn Limit Reached", budget, time.time(),
                        reason="usage limit (%s)" % (line.get("limit") or "unknown"),
                        route=line.get("route"), fallback=fb)
    else:
        _status_quietly(root, code, "idle", "Idle", budget, time.time(),
                        route=line.get("route") if fb else None, fallback=fb)


def _secs(value):
    """A timeout rendered from numbers only for a Refused message; anything
    that is not a number reads 'the default wait'."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "the default wait"
    return f"{value:g}s"


SENTINELS_REL = Path("ops") / "stop_sentinels.json"


def stop_sentinel_hit(root):
    """v19 (CS FIX 2026-10-18-1213 item 1): the first stop sentinel the tree
    declares in ops/stop_sentinels.json {"paths": [rel, ...]} that exists
    (any entry, dangling links too), else None. No file = no sentinels. An
    unreadable file or a path outside the tree raises Refused (fail closed)."""
    path = Path(root) / SENTINELS_REL
    if not os.path.lexists(path):
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        rels = doc["paths"]
        if not isinstance(rels, list) or not all(isinstance(r, str) and r for r in rels):
            raise ValueError("paths")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        raise Refused(f"{SENTINELS_REL.as_posix()} unreadable - fail closed",
                      code="halted") from None
    for rel in rels:
        rp = Path(rel)
        if rp.is_absolute() or rp.drive or ".." in rp.parts:
            raise Refused(f"stop sentinel path outside the tree: {rel}", code="halted")
        if os.path.lexists(Path(root) / rp):
            return rel
    return None


def spawn(root, code, prompt, note="", writes_code=False, bare=False,
          rules_file=None, timeout=3600, extra=(), run=None,
          url_source=base_url, connect=socket.create_connection,
          exe_source=claude_exe, cwd=None, stdin=False, return_stderr=False,
          persist=False, session_id=None, resume=None, model=None, effort=None,
          setting_sources=DEFAULT_SOURCES, floors_in_hooks=False, pin=None,
          log_path=None, halt_file=None, governor=None, governor_timeout=None,
          governor_root=None, governor_since=None, kind=None, stdin_data=None,
          slot_id=None, progress_task=None, route_source=None, unit_id=None):
    """Start ONE headless run and wait for it. Returns the usage line (dict)
    plus "result" (and "stderr" when return_stderr). Raises Refused, before
    anything starts, when the fleet rules forbid it; the status file then reads
    refused / halted / limit. A timeout returns a line with error "timeout" and
    rc None after the process tree is killed. Budget, status and usage files
    live under root; the child runs in cwd (default root). governor="queued" or
    "interactive" holds one machine-wide slot for the run (v6); a slot not won
    within governor_timeout seconds raises Refused and nothing starts; a caller
    that retries passes governor_since (its first ask) so it keeps its age. A
    lane run inside fleet_lanes.run_lane takes its ONE slot here, nowhere else.
    kind (v8) labels the run build / inbox / triage in the usage line.
    stdin_data (v10) keeps the prompt in argv and feeds this text on stdin
    (it cannot be combined with stdin=True). An OSError before the run starts
    (unreadable registry, unwritable status dir, ...) is raised as Refused.
    v16: an empty or blank note label refuses (code "empty-note") before
    anything starts (v18: so does a missing kind, code "no-kind"); slot_id
    (a lane / slot id) is the usage row's "slot",
    else the governor slot's name, else null. When the run ends, however it
    ends, every progress row the child process owned and the progress_task
    row (when given) that still say running are written as failed.
    v19.1: the route file is read first, fresh, on every call (route_source is
    a tests-only hook; the CLI never passes it). v20 (LANE-95): unit_id names
    the resumable unit the run works on; the usage line records it as "unit"."""
    root = Path(root)
    route_source = read_route if route_source is None else route_source
    budget = RunBudget(root / BUDGET_REL)
    run = _run if run is None else run
    if halt_file and os.path.lexists(halt_file):  # any entry halts, dangling links too
        _status_quietly(root, code, "halted", "Halted", budget)
        raise Refused("halt file present")
    try:
        hit = stop_sentinel_hit(root)
    except Refused as sentinel_exc:  # v21 (CS 2356 item 5): its own shape
        _status_quietly(root, code, "halted", "Halted", budget)
        raise Refused(str(sentinel_exc), code="halted") from None
    if hit:
        _status_quietly(root, code, "halted", "Halted", budget)
        raise Refused(f"stop sentinel present: {hit}", code="halted")
    try:
        primary = route_source()
        # v20 ACCT-FALLBACK: the state is read fresh too; an armed fallback whose
        # 7-day trigger fired moves this spawn to the other route until the reset.
        route, falling_back = effective_route(primary)
        if not str(note or "").strip():
            raise Refused("empty note label - every run names its note or task",
                          code="empty-note")
        if kind is None:
            raise Refused(f"no kind - every run names its kind, one of {KINDS}",
                          code="no-kind")
        check_door(bare, extra, floors_in_hooks)
        run_kind(note, kind)  # an unknown kind refuses before anything starts
        model, effort = pick_model(writes_code, model), pick_effort(note, effort)
        if stdin and stdin_data is not None:
            raise Refused("stdin=True and stdin_data both feed stdin - pick one")
        if not stdin and len(prompt) > ARGV_PROMPT_MAX:
            raise Refused(f"prompt over {ARGV_PROMPT_MAX} chars in argv - pass stdin=True")
        url = url_source()
        host, port = check_url(url, pin)  # both routes: the variable is the kill switch
        degraded = False
        if route["mode"] == "single":
            if bare:
                # v22 (KIT-V22-BARE): --bare reads no OAuth and the single route
                # has no proxy to swap in the pinned key, so a bare child could
                # not authenticate. It is DEGRADED to the other lean form of
                # FLEET-COMMON 10 (strict MCP + project settings), which loads
                # the tree's hooks too - never fewer floors than --bare. The
                # rules file still reaches the child; the usage line says so.
                bare, degraded = False, True
                if rules_file:
                    extra = [*extra, "--append-system-prompt-file", str(rules_file)]
        else:
            probe(host, port, connect=connect)
        argv = build_argv(exe_source(), prompt, model, effort, bare, rules_file, extra,
                          stdin=stdin, persist=persist, setting_sources=setting_sources,
                          output_format="stream-json" if log_path else "json",
                          session_id=session_id, resume=resume)
        slot_cm = _governor(root, code, governor, governor_timeout, governor_root,
                            budget, note, governor_since)
    except Refused as exc:
        _refused_status(root, code, budget, exc)
        raise
    except OSError as exc:
        _status_quietly(root, code, "refused", REFUSED_TASK, budget)
        raise Refused(f"start failed: {exc.__class__.__name__}") from None
    with contextlib.ExitStack() as slot_stack:
        try:
            slot = slot_stack.enter_context(slot_cm)
        except _lanes().SlotTimeout:
            _status_quietly(root, code, "backoff", "Backing Off", budget)
            raise Refused(f"no governor slot within {_secs(governor_timeout)}",
                          code=SLOT_TIMEOUT_CODE) from None
        return _spawn_slotted(root, code, prompt, note, bare, budget, run, url, argv,
                              model, effort, cwd, stdin, timeout, log_path,
                              return_stderr, slot, kind, stdin_data, slot_id,
                              progress_task, route, (primary, falling_back), unit_id,
                              degraded)


def _spawn_slotted(root, code, prompt, note, bare, budget, run, url, argv, model,
                   effort, cwd, stdin, timeout, log_path, return_stderr, slot,
                   kind=None, stdin_data=None, slot_id=None, progress_task=None,
                   route=None, fb=(None, False), unit_id=None, degraded=False):
    """The v5 run body, entered only once a governor slot (if any) is held."""
    try:
        counted = budget.start()
    except Refused:
        _status_quietly(root, code, "refused", REFUSED_TASK, budget)
        raise
    except OSError as exc:
        _status_quietly(root, code, "refused", REFUSED_TASK, budget)
        raise Refused(f"budget write failed: {exc.__class__.__name__}",
                      code="budget-write-failed") from None
    if not counted:
        _status_quietly(root, code, "limit", "Turn Limit Reached", budget)
        raise Refused(f"run budget exhausted ({budget.used()}/{budget.cap})",
                      code="budget-spent")
    started = time.time()
    mode = route["mode"] if route else None
    _status_quietly(root, code, "running", "Running Session", budget, started, route=mode,
                    fallback=fb[1])
    kw = {"cwd": str(Path(cwd) if cwd else root),
          "env": child_env(url, bare, route=route, code=code),
          "text": True, "encoding": "utf-8", "errors": "replace", "timeout": timeout,
          "creationflags": _NO_WINDOW}
    if stdin:
        kw["input"] = prompt
    elif stdin_data is not None:
        kw["input"] = stdin_data
    slot_name = slot_id if slot_id not in (None, "") else (Path(slot).name if slot else None)
    marked = {"ok": None}
    child = {"pid": None}
    if run is _run or _accepts_on_start(run):
        if slot:
            marked["ok"] = False

        def _mark(pid):
            child["pid"] = pid
            if slot:
                _lanes().mark_child(slot, pid)
                marked["ok"] = True
        kw["on_start"] = _mark
    try:
        return _spawn_body(root, code, note, bare, budget, run, argv, model, effort,
                           log_path, return_stderr, slot, kind, slot_name, kw, marked,
                           started, mode, fb, unit_id, degraded)
    finally:
        _close_child_rows(root, cwd, child["pid"], progress_task)


def _close_child_rows(root, cwd, pid, progress_task):
    """v16: never leave a finished run's progress rows saying running."""
    tops = []
    for top in (root, cwd):
        if top:
            with contextlib.suppress(OSError):
                m = main_checkout(top)
                if m not in tops:
                    tops.append(m)
    for top in tops:
        with contextlib.suppress(OSError, ValueError):
            if pid:
                close_owned_progress(top, pid)
    if progress_task and tops:
        with contextlib.suppress(OSError, ValueError):
            close_progress(tops[-1] if cwd else tops[0], progress_task)


def _spawn_body(root, code, note, bare, budget, run, argv, model, effort, log_path,
                return_stderr, slot, kind, slot_name, kw, marked, started, route=None,
                fb=(None, False), unit_id=None, degraded=False):
    proc, error = None, None
    try:
        with contextlib.ExitStack() as stack:
            if log_path:
                Path(log_path).parent.mkdir(parents=True, exist_ok=True)
                kw["stdout"] = stack.enter_context(
                    Path(log_path).open("w", encoding="utf-8", newline="\n"))
                kw["stderr"] = subprocess.PIPE
            else:
                kw["capture_output"] = True
            proc = run(argv, **kw)
    except subprocess.TimeoutExpired:
        error = "timeout"
    except BaseException as exc:
        _finish(root, code, budget, usage_line(None, code, note, model, effort, bare, None,
                                               time.time() - started, type(exc).__name__,
                                               kind, slot_name, route, fb[1], unit_id))
        raise
    if log_path:
        result = _result_from_log(log_path)
    else:
        result = _json_or_none(getattr(proc, "stdout", None))
    rc = getattr(proc, "returncode", None) if proc is not None else None
    line = usage_line(result, code, note, model, effort, bare, rc,
                      time.time() - started, error, kind, slot_name, route, fb[1], unit_id)
    line["governor_slot"] = Path(slot).name if slot else None
    if degraded:
        line["bare_degraded"] = True  # v22: asked --bare, ran lean on single
    if kw.get("env", {}).get(TMPDIR_ENV):
        line["tmpdir"] = kw["env"][TMPDIR_ENV]  # v22: the child's temp root
    line["child_marked"] = marked["ok"]
    cls = None
    if error is None and proc is not None and (rc not in (0, None) or line["is_error"]):
        # v20: the child's OWN limit message (result text, then stderr) - only of
        # a failed run; a timeout or a successful run's text is never read.
        res = result.get("result") if isinstance(result, dict) else None
        err = getattr(proc, "stderr", None)
        cls = classify_limit("\n".join(x for x in (res, err) if isinstance(x, str)))
    if cls:
        line["limit"] = cls["window"] or "unknown"
        with contextlib.suppress(OSError, Refused):
            _limit_after_run(fb[0], fb[1], cls)
    _finish(root, code, budget, line, limit=bool(cls))
    line["result"] = result.get("result") if isinstance(result, dict) else None
    line["receipt"] = result if isinstance(result, dict) else None
    if return_stderr:
        line["stderr"] = getattr(proc, "stderr", None) if proc is not None else None
    return line


# ---------------------------------------------------------------- CLI (v10)

CLI_OK, CLI_USAGE, CLI_REFUSED, CLI_TIMEOUT = 0, 2, 3, 4
PERMISSION_MODES = ("acceptEdits", "bypassPermissions", "default", "dontAsk", "plan")


def main(argv=None, spawn_fn=None, stdin=None, stdout=None):
    """`python fleet_headless.py spawn --root R --code C --note N [options]`
    for callers that are not Python (CS 0224). v11: --permission-mode MODE
    (one of PERMISSION_MODES) is the only pass-through flag. The prompt comes from
    --prompt-file, else stdin. Prints the usage line as one JSON line. Exit
    0 ran, 2 bad arguments, 3 Refused, 4 timeout. Every fleet rule applies
    exactly as for spawn(); no flag or variable bypasses the proxy or the door."""
    import argparse
    ap = argparse.ArgumentParser(prog="fleet_headless.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("spawn")
    sp.add_argument("--root", required=True)
    sp.add_argument("--code", required=True)
    sp.add_argument("--note", required=True)
    sp.add_argument("--kind", choices=KINDS, required=True)
    sp.add_argument("--effort", choices=EFFORTS)
    sp.add_argument("--model")
    sp.add_argument("--writes-code", action="store_true")
    sp.add_argument("--timeout", type=int, default=3600)
    sp.add_argument("--cwd")
    sp.add_argument("--floors-in-hooks", action="store_true")
    sp.add_argument("--prompt-file")
    sp.add_argument("--permission-mode", choices=PERMISSION_MODES)
    sp.add_argument("--slot")
    sp.add_argument("--progress-task")
    sp.add_argument("--unit")
    rp = sub.add_parser("route")
    rsub = rp.add_subparsers(dest="rcmd", required=True)
    rsub.add_parser("show")
    rs = rsub.add_parser("set")
    rs.add_argument("mode", choices=ROUTE_MODES)
    rs.add_argument("--config-dir")
    rs.add_argument("--fallback", choices=ROUTE_MODES)
    rs.add_argument("--no-fallback", action="store_true")
    pp = sub.add_parser("progress")
    pp.add_argument("--root", required=True)
    pp.add_argument("--task", required=True)
    pp.add_argument("--pct", type=int, required=True)
    pp.add_argument("--step", required=True)
    pp.add_argument("--eta-s", type=int)
    pp.add_argument("--status", choices=PROGRESS_STATES, required=True)
    pp.add_argument("--reason")
    pp.add_argument("--owner", type=int)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return CLI_USAGE
    out = stdout or sys.stdout
    if args.cmd == "route":
        # v19.1: the only writer of the route file. Never prints the path.
        if args.rcmd == "set":
            try:
                if args.fallback and args.no_fallback:
                    raise _route_invalid("--fallback and --no-fallback together")
                # v20: --config-dir names the account dir of whichever route is
                # single (the primary, else an armed single fallback).
                single_fb = args.fallback == "single" and args.mode == "split"
                write_route(args.mode, None if single_fb else args.config_dir,
                            fallback=args.fallback,
                            fallback_config_dir=args.config_dir if single_fb else None)
            except Refused as exc:
                print(json.dumps({"error": str(exc)[:200], "code": exc.code}), file=out)
                return CLI_USAGE
            except OSError as exc:
                print(json.dumps({"error": "route write failed: " + exc.__class__.__name__}),
                      file=out)
                return CLI_USAGE
        doc = route_show()
        print(json.dumps(doc), file=out)
        return CLI_OK if doc["valid"] else 1
    if args.cmd == "progress":
        try:
            doc = write_progress(args.root, args.task, args.pct, args.step, args.eta_s,
                                 args.status, reason=args.reason, owner=args.owner)
        except (ValueError, OSError) as exc:
            print(json.dumps({"error": exc.__class__.__name__}), file=out)
            return CLI_USAGE
        print(json.dumps(doc), file=out)
        return CLI_OK
    if not args.note.strip():
        print(json.dumps({"error": "empty --note"}), file=out)
        return CLI_USAGE
    try:
        if args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        else:
            prompt = (stdin or sys.stdin).read()
    except (OSError, UnicodeDecodeError) as exc:
        print(json.dumps({"error": f"prompt unreadable: {exc.__class__.__name__}"}), file=out)
        return CLI_USAGE
    if not prompt.strip():
        print(json.dumps({"error": "empty prompt"}), file=out)
        return CLI_USAGE
    try:
        line = (spawn_fn or spawn)(
            args.root, args.code, prompt, note=args.note, writes_code=args.writes_code,
            timeout=args.timeout, cwd=args.cwd, stdin=len(prompt) > ARGV_PROMPT_MAX,
            model=args.model, effort=args.effort, floors_in_hooks=args.floors_in_hooks,
            kind=args.kind, **({"slot_id": args.slot} if args.slot else {}),
            **({"progress_task": args.progress_task} if args.progress_task else {}),
            **({"unit_id": args.unit} if args.unit else {}),
            extra=("--permission-mode", args.permission_mode) if args.permission_mode else ())
    except Refused as exc:
        print(json.dumps({"refused": str(exc), "code": getattr(exc, "code", "refused")}),
              file=out)
        return CLI_REFUSED
    print(json.dumps(line), file=out)
    return CLI_TIMEOUT if line.get("error") == "timeout" else CLI_OK


if __name__ == "__main__":
    sys.exit(main())
