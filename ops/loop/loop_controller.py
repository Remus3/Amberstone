#!/usr/bin/env python
"""Headless upgrade-loop controller (the BRAIN).

Headless. Never touches the GUI. Drives the cycle:
  director -> directive.md + gemini.ready -> (bridge types) -> claude.done
  -> meter -> auditor -> clean:advance | regress:FIX-first -> repeat

The `gemini.ready` handshake file KEEPS its name after the vendor removal, and
that is deliberate rather than an oversight. It is polled by the legacy AHK GUI
bridge, which the operator held back from deletion as the rollback channel;
renaming the file in one of the two places is how a rollback silently stops
working. It is now just a filename - nothing behind it is Gemini.

The director and the auditor are read-only adjudicator calls; the executor is
the only writer. All three are Claude since 2026-08-01 - the loop
self-adjudicates and the read-only guarantee is `--permission-mode plan`, not a
different vendor. See ops/loop/adjudicator.py and
docs/CONCURRENT_HEADLESS_CONTRACT.md section 9.

IPC = files in control_dir, atomic (tmp + os.replace), plain-text where the
bridge reads. Every stage is stateless per cycle; continuity lives on disk
(git history + docs/LEDGER.md + the directive chain).
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

# The controller is loaded by absolute file path (launcher + tests), so ops/loop
# is never on sys.path; bind the sibling adjudicator module explicitly.
_ADJ_MODNAME = "rc_loop_adjudicator"
if _ADJ_MODNAME in sys.modules:
    adjudicator = sys.modules[_ADJ_MODNAME]
else:
    _adj_spec = importlib.util.spec_from_file_location(
        _ADJ_MODNAME, Path(__file__).resolve().parent / "adjudicator.py")
    adjudicator = importlib.util.module_from_spec(_adj_spec)
    sys.modules[_ADJ_MODNAME] = adjudicator
    _adj_spec.loader.exec_module(adjudicator)


def _bind(modname, filename):
    """Same absolute-path bind as the adjudicator above, for the shared modules."""
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(
        modname, Path(__file__).resolve().parent / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# slots.py + winmutex.py are BYTE-IDENTICAL across LW and RC by contract - they
# coordinate the two repos' runs with each other through ProgramData and the OS
# mutex namespace, so a divergence is a silent concurrency bug, not a conflict.
# tests/test_loop_concurrency.py hashes both against the LW copies.
slots = _bind("rc_loop_slots", "slots.py")
winmutex = _bind("rc_loop_winmutex", "winmutex.py")
# The EXECUTOR seam (the thing that does the work), companion to the adjudicator
# (the read-only brain). NOT a shared byte-identical file - it lifts THIS repo's
# controller code and carries RC's directive opener and watch_bridge wait.
executor = _bind("rc_loop_executor", "executor.py")


def _bind_path(modname, path):
    """The same absolute-path bind as _bind, for a module OUTSIDE ops/loop."""
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# core/polled_json.py holds the repo's atomic-write contract - LANE 8 CYCLE 48,
# RM-250. Two properties this module needs and cannot hand-roll correctly:
# a PER-WRITER scratch name (STOP has a second independent writer in
# dashboard/routes_loop_control.py:344,587, and a scratch derived from the
# destination alone is shared, so the two interleave), and a bounded
# PermissionError backoff (~275 ms) for the Windows share-lock a poller holding
# the destination open produces.
#
# It cannot be reached with a plain `from core.polled_json import ...`: this
# module is loaded by ABSOLUTE FILE PATH (see the adjudicator comment above), so
# the repo root is not on sys.path either and that import raises
# ModuleNotFoundError - measured, and guarded by
# tests/test_loop_control_sibling_writers_lane8_cycle48.py. The normal import is
# tried FIRST so the dashboard and the test suite keep sharing one module
# object; the bind is the launcher's fallback, not the primary path.
try:
    from core.polled_json import atomic_write_bytes as _atomic_write_bytes
except ModuleNotFoundError:
    _atomic_write_bytes = _bind_path(
        "rc_core_polled_json",
        Path(__file__).resolve().parents[2] / "core" / "polled_json.py",
    ).atomic_write_bytes

_HERE = Path(__file__).resolve().parent
# The default config is a REPO ASSET, not a machine location. This literal used
# to be an absolute C: path, which resolves on exactly ONE host: every other
# checkout took the not-found branch and ran the module against CFG={}. The
# failure is silent until something asserts on a CFG value, and then it is
# platform-split - measured 2026-07-27, the directive_suffix guard was green on
# Legion and red on the ubuntu nightly for this reason alone. ops/loop/config.json
# is tracked and sits next to this module, so resolving it from __file__ finds
# the same bytes in a worktree, a fresh clone and CI.
_CFG_ARG = (Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].endswith(".json")
            else _HERE / "config.json")
try:
    CFG = json.loads(Path(_CFG_ARG).read_text(encoding="utf-8"))
except (FileNotFoundError, OSError):
    # Still possible when the controller is vendored without its config; the
    # pure helpers under unit test never read CFG, and a live launch always
    # passes a real --config path.
    CFG = {}


def _cfg_path(key, default):
    """A CFG path key addresses the HOST that authored it, nothing more.

    config.json carries Legion drive-letter paths, and on POSIX such a string
    parses as a RELATIVE single-component name - so adopting it verbatim would
    mint a literal drive-letter DIRECTORY inside the checkout at the CTL.mkdir
    below, and point ROOT at a repo that is not the one under test. Absoluteness
    is the platform-agnostic test for "this value means what it says here";
    anything else falls back to the checkout-relative location, which is what
    every non-Legion run resolved to before the config became readable at all.
    """
    raw = CFG.get(key)
    p = Path(raw) if raw else None
    return p if p is not None and p.is_absolute() else default


ROOT = _cfg_path("repo_root", _HERE.parents[1])
CTL = _cfg_path("control_dir", _HERE / "control")
CTL.mkdir(parents=True, exist_ok=True)
DRY = bool(CFG.get("dry_run", False))
ADJ_USD = 0.0  # cumulative ESTIMATED adjudicator spend - a workload signal, NOT a cap
RUN_ID = ""  # minted in main(); namespaces slot payloads across concurrent runs
# Adjudicator (external-brain) run state: the live backend name and its
# estimated spend. Caller-owned so adjudicate() can rebuild the wrapper from the
# CURRENT module globals every call without resetting the accumulated spend.
# `failed_over` was dropped with the vendor failover on 2026-08-01.
_ADJ_STATE = {"active": "", "usd": {}}

def log(m):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}"
    print(line, flush=True)
    with open(CTL / "controller.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")

def awrite(path, text):
    """Atomic write of a polled control file - STOP (:174), cycle.txt.

    LANE 8 CYCLE 48 (RM-250). This used to hand-roll `tmp.write_text` + a BARE
    `os.replace`, which carried three defects that cycle 21 had already closed
    in the dashboard's copy of this same writer:

      * No PermissionError retry. STOP is read from three poll loops - this
        module at :772/:786 every 5 s, ops/loop/claude_gui_bridge.ahk:299 every
        1 s, and dashboard/routes_loop_status.py:450 on every browser poll of
        GET /api/loop-status. On Windows a reader holding the destination open
        share-locks it and the replace raises WinError 5, so the controller's
        own halt could lose a coin-flip against its own poller.
      * A scratch name of `str(path) + ".tmp"`, a function of the DESTINATION
        alone. dashboard/routes_loop_control.py:344,587 also writes STOP, so
        both writers opened the same scratch file and could interleave.
      * `Path.write_text`, which rewrites LF as CRLF on Windows and makes every
        downstream byte count disagree with the file
        (reference_windows_write_text_crlf_byte_count).

    All three are properties of core/polled_json, so this delegates rather than
    re-deriving them. Bytes, not text, for the same reason the siblings in
    intents.py and steer.py already wrote bytes.
    """
    _atomic_write_bytes(Path(path), text.encode("utf-8"))

def consume_directive_override(ctl=None):
    """One-shot operator directive override (written by POST /api/loop-control).

    Returns the override text and removes the file so it applies to exactly one
    cycle, or None when absent / empty. Default-absent => byte-identical loop.
    """
    base = Path(ctl) if ctl is not None else CTL
    p = base / "directive_override.md"
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        text = ""
    p.unlink(missing_ok=True)
    return text or None

def cycle_source(cfg, override):
    """Pure: which directive source feeds this cycle. Precedence:
    operator override > cycle_command > fixed_directive > director.

    cycle_command (e.g. a self-directing slash command like /RC2-Continue) is
    typed VERBATIM after /clear and SKIPS the director - the command
    self-directs from its own living plan - but KEEPS the auditor each
    cycle. fixed_directive skips BOTH director and auditor. Default-absent both
    => 'director' (byte-identical to the historical loop)."""
    if override:
        return "override"
    if cfg.get("cycle_command"):
        return "cycle_command"
    if cfg.get("fixed_directive"):
        return "fixed"
    return "director"

def rjson(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default

def stop(reason):
    awrite(CTL / "STOP", reason)
    log(f"STOP written: {reason}")
    sys.exit(0)

# ---- git helpers -------------------------------------------------------
def git(*args):
    # Bound every git call: the headless loop has NO deadline around these
    # synchronous reads (wait_for/wait_gone only cover the AHK handshake), so a
    # wedged git (stale index.lock, hung hook) would strand the unattended run.
    # Degrade a timeout / failure to "" - callers already tolerate empty
    # (prev_sha[:8] of "" is "", auditor guards `if not new_sha`).
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args],
                              capture_output=True, text=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except (subprocess.SubprocessError, OSError) as e:
        log(f"git {args[0] if args else ''} failed: {e}")
        return ""

def head():
    return git("rev-parse", "HEAD")

def _rev_parse(ref):
    """Resolve a git ref to a sha, or '' when it does not exist (e.g. HEAD~2 in a
    young repo). git() already degrades a bad ref / failure to '' (rev-parse
    --verify -q prints nothing + exits non-zero), so this never raises."""
    return git("rev-parse", "--verify", "-q", ref)

def _is_ancestor(a, b):
    """True iff commit a is an ancestor of (or identical to) commit b. Uses a
    direct call because the answer is the EXIT CODE, not stdout, and the
    stdout-only git() helper cannot express it."""
    if not a or not b:
        return False
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", a, b],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False

def _is_merge(sha):
    """True iff sha is a merge commit (2+ parents). `rev-list --parents -n 1`
    prints '<sha> <p1> <p2> ...', so >2 tokens means a merge."""
    if not sha:
        return False
    return len(git("rev-list", "--parents", "-n", "1", sha).split()) > 2

def _audit_floor(new_sha):
    """The 2-commit context floor, made MERGE-AWARE.

    `new_sha~2` walks FIRST parents only. A feature landed via `git merge --no-ff`
    is the merge's SECOND parent, so whenever a docs/test/finalize commit sits on
    top of the merge, a plain `~2` floor stops at (or just past) the merge and the
    two-dot `base..new_sha` window EXCLUDES the merged code. The auditor then sees
    docs asserting an engine change with no code in range -> false-positive
    REGRESS (#5). Fix: if either of the last two first-parent commits is a merge,
    lower the floor to that merge's FIRST parent (the pre-feature main tip, an
    ancestor of the merged branch), so the second-parent feature commits come back
    into the window. Fallbacks stay '' for a young repo (audit_range degrades)."""
    floor = _rev_parse(f"{new_sha}~2")
    for step in (f"{new_sha}~1", f"{new_sha}~2"):
        sha = _rev_parse(step)
        if sha and _is_merge(sha):
            fp = _rev_parse(f"{sha}~1")
            if fp and (not floor or _is_ancestor(fp, floor)):
                floor = fp
    return floor

def audit_range(clean_sha, new_sha):
    """base..new_sha the auditor scores each cycle (R61).

    ROOT CAUSE (false-positive REGRESS recursion): the old window was the single
    cycle's commits (prev_sha..new_sha). A /done docs-sync commit that lands in
    its OWN cycle was audited in isolation - the auditor saw docs asserting an
    engine/logic change whose code was committed a cycle earlier and lay OUTSIDE
    the window, so the lone docs commit read as a regression. That fed a
    FIX-FIRST directive with nothing to fix, which shipped another docs commit,
    audited alone again: an infinite REGRESS loop.

    Fix: never audit a lone commit. base = the OLDER of the last-CLEAN anchor and
    new_sha~2, so (a) a docs commit always carries the commit(s) it documents,
    and (b) an unresolved REGRESS chain keeps its full context back to the last
    known-good state. Fallbacks for a young repo: new_sha~2 -> new_sha~1 ->
    new_sha (a bare sha = a valid whole-tree diff).

    The floor is merge-aware (see _audit_floor): a feature merged via a `--no-ff`
    merge's SECOND parent stays inside the window even when docs/test commits sit
    on top of the merge (false-positive REGRESS #5)."""
    floor = _audit_floor(new_sha)
    if clean_sha and floor:
        # keep the clean anchor only while it is OLDER than the 2-commit floor;
        # otherwise widen to the floor so the window is never a single commit.
        base = clean_sha if _is_ancestor(clean_sha, floor) else floor
    else:
        base = clean_sha or floor
    base = base or _rev_parse(f"{new_sha}~1")
    return f"{base}..{new_sha}" if base else new_sha

def tail(rel, n, root=None):
    base = Path(root) if root is not None else ROOT
    p = base / rel
    if not p.exists():
        return ""
    return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])

def head_lines(rel, n, root=None):
    # The HEAD n lines. For a newest-first append-at-top ledger (docs/LEDGER.md)
    # this is the NEWEST n entries. Using tail() here was the continuity bug:
    # it fed the director the OLDEST ledger items, so just-completed work was
    # invisible and the director re-proposed already-shipped items.
    base = Path(root) if root is not None else ROOT
    p = base / rel
    if not p.exists():
        return ""
    return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:n])

def cap_bytes(text, limit, label):
    # 2026-07-01 NO_WORK-starvation fix: the director prompt went out at 572KB
    # (ORCHESTRATION_PLAN grew a 289KB findings log; modern LEDGER items are
    # multi-KB single lines, so head-60 was 93KB) and the adjudicator completed with an
    # EMPTY body -> misread as NO_WORK -> STOP with 5 OPEN queue rows. Doc
    # growth must never starve the director again: keep the HEAD (queue tables
    # / newest entries live at the top of both docs) and stamp a visible cut.
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[{label} truncated at {limit} bytes - full text in the repo file]"

# Hard byte budgets for the unbounded director-context components.
# 2026-07-02 re-tighten (gemini-era, kept as the rail's provenance): that CLI
# silently returned EMPTY stdout above
# ~80KB stdin (80KB delivered fine, 160KB empty, no stderr error - measured
# live; the 01:56 outage killed cycles 9-100 of the prior run). The 2026-07-01
# caps (140K plan alone) still allowed a >160KB total, so every component cap
# now fits the WHOLE prompt inside ADJ_STDIN_CAP with headroom.
# 2026-07-03 re-tighten AGAIN: the threshold DRIFTS - a 79,911-byte director
# payload (cap_stdin-trimmed to the old 80,000 ceiling) returned silent EMPTY
# every try (both pro + flash), burning cycles 10-32 directive-less; the SAME
# payload truncated to 70,000 and 60,000 bytes both delivered (measured live).
# Treat the ceiling as weather, not physics: sit well under the worst
# measurement. Component caps compose to ~56KB with the ~16KB template/digest/
# chain overhead, so a normal prompt never even hits the cap_stdin backstop.
PLAN_CTX_CAP = 24_000
LEDGER_CTX_CAP = 8_000
ROADMAP_CTX_CAP = 8_000

# 2026-07-27 duplicate-directive fix. The 2026-07-01 cap bounded the SIZE and
# silently inverted the CONTENT for the plan: closure rows are APPENDED, so the
# 271,142-byte ORCHESTRATION_PLAN keeps its newest rows in the last ~9KB
# (measured: R199 at offset 262,042, R200 at 265,191) while a pure-head 24,000
# cap stopped at 24,000. "f1-phase6" occurred twice in the document and ZERO
# times in the slice the director received, so cycle 11 re-issued work cycle 9
# had already closed and recorded. The plan therefore keeps a head slice - the
# doc's own framing and the curated pick-these-first list live at the top - AND
# a tail slice. The split is a REALLOCATION inside the unchanged 24,000: the
# The empty-stdout ceiling is why this budget exists, so raising it to buy
# the tail would trade one starvation mode for the other.
PLAN_CTX_HEAD = 8_000

# 2026-07-27 digest-starvation fix. Every cap above bounds one COMPONENT, and
# nothing bounded their SUM plus the prompt template plus the operator brief.
# Measured live: a 63,192-byte body against ADJ_STDIN_CAP 60,000, so
# cap_stdin's blind 60/40 middle cut fired on EVERY cycle - and the bytes it
# discarded were exactly the ALREADY-COMPLETED DIGEST header and the whole
# RECENT COMMITS block, i.e. the literal refutation of the duplicate directive
# the director kept re-emitting. An overflow is therefore repaid out of the
# plan, the one genuinely expendable component: the plan is a work MENU that
# degrades gracefully, while the digest is the de-dup EVIDENCE and degrades
# into the exact failure this loop keeps hitting. The floor sits above
# PLAN_CTX_HEAD so repayment can never silently delete the plan's TAIL, where
# the newest queue rows live. Raising ADJ_STDIN_CAP is not the alternative:
# a 79,911-byte payload returns silent EMPTY from the CLI (measured).
PLAN_CTX_MIN = 12_000
# Repay slightly more than the overflow: the rebuilt context is re-measured by
# nobody, so landing exactly ON the cap leaves no room for the marker text the
# smaller budget stamps.
PLAN_CTX_SLACK = 512

# 2026-07-27. The operator brief is 5,273 bytes of STATIC prose appended after
# the LAST AUDIT body. Joined with a bare blank line and no header it read as
# the tail of that audit - so the director treated standing background policy
# as this cycle's work order, and prose written before the last N cycles
# shipped outranked the digest that says they did. The header restores the
# section boundary and states the precedence in the one place the director
# cannot miss it.
DIRECTIVE_SUFFIX_HEADER = (
    "=== OPERATOR STANDING BRIEF (background policy, NOT this cycle's work order. "
    "It is STATIC and does not know what has shipped since it was written - the "
    "ALREADY-COMPLETED DIGEST OVERRIDES it) ===")

# The ledger needs the opposite treatment. It IS newest-first, so head-keeping
# was already right, but a modern item is one 5-10KB LINE (item 1074 alone is
# 10,749 bytes), so an 8,000-byte cap over whole items delivered ONE partial id
# and cut item 1073 - the row naming this very closure. De-dup only needs each
# item's opening clause, so the budget is spent per ITEM: 300 chars x ~26 items
# inside the same 8,000 bytes (measured against the live 3MB file).
LEDGER_ITEM_HEAD = 300
LEDGER_HEAD_LINES = 240

_LEDGER_ITEM_RE = re.compile(r"^\d{3,4}\. ")


def cap_bytes_head_tail(text, limit, label, head):
    """cap_bytes for a doc whose NEWEST content is appended at the END."""
    if len(text) <= limit:
        return text
    marker = (f"\n...[{label} truncated at {limit} bytes - HEAD + TAIL kept, "
              "middle cut; full text in the repo file]...\n")
    keep = max(limit - len(marker), 0)
    h = min(head, keep)
    tail = keep - h
    return text[:h] + marker + (text[len(text) - tail:] if tail else "")


def ledger_digest(text, per_item, limit, label):
    """Newest-first ledger -> as many item HEADLINES as the budget allows."""
    marker = (f"...[{label} truncated at {limit} bytes - "
              "older items omitted; full text in the repo file]")
    out, used = [], 0
    for line in text.splitlines():
        if not _LEDGER_ITEM_RE.match(line):
            continue
        s = line[:per_item] + (" ..." if len(line) > per_item else "")
        # The marker is RESERVED before the last item is admitted. Charging it
        # only on the way out returns limit + len(marker) - measured at 8,020
        # against LEDGER_CTX_CAP 8,000 - and a cap its own constant does not
        # bound is the always-green shape this module exists to remove.
        if used + len(s) + 1 + len(marker) > limit:
            out.append(marker)
            break
        out.append(s)
        used += len(s) + 1
    # A ledger that carries no recognisable item lines is a shape change, not an
    # empty ledger - fall back rather than hand the director nothing at all.
    return "\n".join(out) if out else cap_bytes(text, limit, label)

# Auditor payload split. 2026-07-19 false-positive REGRESS #6: the whole budget
# went to the diff BODY, which git emits in PATH BYTE ORDER - a commit whose
# early-sorting paths are bulky spent every byte before the auditor ever
# reached the files that actually mattered, so it never saw the true source and
# called a complete, CI-green commit a regression. A complete file
# manifest is worth far more per byte than deeper diff context, so the body
# yields 15K to guarantee the manifest always fits under ADJ_STDIN_CAP.
AUDIT_DIFF_CAP = 40_000
AUDIT_MANIFEST_CAP = 12_000

# The prompt-size backstop. cap_stdin() applies it to EVERY adjudicate() call
# (director / auditor / stall).
#
# HONEST PROVENANCE, because the number outlived its evidence. 60,000 was
# MEASURED against the gemini CLI, which silently returned empty stdout above
# roughly that size - see the 2026-07-02 notes above. That vendor is gone as of
# 2026-08-01 and NO equivalent limit has been measured for the claude CLI, so
# this is no longer a proven-safe ceiling; it is an unproven-but-conservative
# rail retained deliberately. Removing a size guard because its original
# justification lapsed would be trading a known-safe behaviour for an unmeasured
# one, and an oversized prompt fails in the worst way here (a silent empty
# answer reads as NO_WORK). Re-measure against the current CLI before raising
# it, and do not raise it merely to fit more context - the callers above already
# budget their sections against this constant.
ADJ_STDIN_CAP = 60_000

def cap_stdin(body, limit=None):
    """Backstop: keep the HEAD (prompt template + instructions) and the TAIL
    (directive_suffix / escalation / final rules); cut the expendable middle."""
    lim = ADJ_STDIN_CAP if limit is None else limit
    if len(body) <= lim:
        return body
    marker = "\n...[STDIN CAP: middle truncated to fit the adjudicator stdin cap - head + tail preserved]...\n"
    keep = lim - len(marker)
    head = int(keep * 0.6)
    return body[:head] + marker + body[len(body) - (keep - head):]

# ---- directive-chain continuity (persisted; survives controller restarts) ---
# director_prompt.md:16-18 mandates these as the directive's FIRST three lines
# and ENGINE-IMPACT as a mandatory body line. They are machine-readable grounding
# metadata, never the name of a unit of work, so the first-non-empty-line
# fallback titled 181 of the 199 live history records "GROUNDED-AGAINST: ..." -
# a de-dup chain that named nothing and could not refute a duplicate directive.
DIRECTIVE_METADATA_PREFIXES = (
    "GROUNDED-AGAINST:", "NOT-A-DUPLICATE-OF:", "PREMISE-CHECK:", "ENGINE-IMPACT:",
)


def directive_title(body):
    """A compact one-line label for an issued directive (for the chain digest)."""
    if not body:
        return "(empty)"
    theme = scope = directive = ""
    for line in body.splitlines():
        s = line.strip()
        u = s.upper()
        # The emitted shape carries the unit on its own `DIRECTIVE:` line, so it
        # outranks the legacy THEME/SCOPE pair and the surrounding qualifiers.
        if u.startswith("DIRECTIVE:") and not directive:
            directive = s.split(":", 1)[1].strip()
        elif u.startswith("THEME:") and not theme:
            theme = s.split(":", 1)[1].strip()
        elif u.startswith("SCOPE:") and not scope:
            scope = s.split(":", 1)[1].strip()
    if directive:
        return directive[:160]
    if theme or scope:
        return (f"{theme} - {scope}".strip(" -"))[:160]
    for line in body.splitlines():
        s = line.strip().lstrip("#").strip()
        if s and not s.upper().startswith(DIRECTIVE_METADATA_PREFIXES):
            return s[:160]
    return "(empty)"

def record_directive_outcome(cycle, body, sha_before, sha_after, done, verdict, ctl=None):
    """Append one resolved-cycle record to control/directive_history.jsonl.

    The controller is the single writer; the file is gitignored runtime state and
    is NEVER cleared (newest-first read via read_directive_history), so the
    directive chain persists across the frequent mid-run controller restarts."""
    base = Path(ctl) if ctl is not None else CTL
    d = done or {}
    rec = {"cycle": cycle, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "title": directive_title(body),
           "sha_before": (sha_before or "")[:8], "sha_after": (sha_after or "")[:8],
           "tests": d.get("tests_pass"), "regress": bool(d.get("regressions")),
           "verdict": ((verdict or "").strip().splitlines() or [""])[0]}
    try:
        with open(base / "directive_history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        log(f"directive_history append failed: {e}")
    return rec

def read_directive_history(n, ctl=None):
    base = Path(ctl) if ctl is not None else CTL
    p = base / "directive_history.jsonl"
    if not p.exists():
        return []
    recs = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return recs[-n:]

def _format_directive_chain(recs):
    if not recs:
        return "(none issued yet this run)"
    out = []
    for r in reversed(recs):  # newest first
        out.append(f"- cycle {r.get('cycle')}: {r.get('title', '')} "
                   f"-> {r.get('sha_after', '')} [{r.get('verdict', '')}]")
    return "\n".join(out)

# ---- external brain (the adjudicator lives in ops/loop/adjudicator.py) ----
def _supervisor():
    """The adjudicator wrapper, built from the CURRENT module globals.

    Rebuilt per call because CFG / CTL / log / awrite are module-scope and are
    swapped by the loop test-suite and by an operator hot-editing config.json;
    _ADJ_STATE carries the accumulated spend across every rebuild.
    """
    return adjudicator.Adjudicator(CFG, CTL, log, awrite, state=_ADJ_STATE)

def adjudicate(prompt_body, instruction):
    """The loop's single external-brain call site (director + auditor).

    N3 semantics: EMPTY output is NEVER a usable answer, so a completed-but-empty
    call returns None exactly like a timeout does.

    NO MUTEX. This call used to be serialized machine-wide on GEMINI_MUTEX
    because Gemini was ONE metered account shared with the sibling loop, and two
    concurrent director calls could trip RESOURCE_EXHAUSTED that the failover
    logic would misread as real credit exhaustion. With one unmetered vendor
    there is no quota to burn in parallel and nothing to misread, so serializing
    here would only make two sibling loops wait on each other for no benefit.
    Total concurrent executor calls are still governed - by ops/loop/slots.py,
    which is the right layer for it.
    """
    return _adjudicate_call(prompt_body, instruction)


def _adjudicate_call(prompt_body, instruction):
    global ADJ_USD
    sup = _supervisor()
    out = sup.ask(cap_stdin(prompt_body), instruction)
    sup.save_state(_ADJ_STATE)
    ADJ_USD = sup.total_usd()
    return out

# ---- adjudicator roles -------------------------------------------------
def build_director_context(last_done, last_audit, *, root=None, ctl=None,
                           plan_cap=None, escalation=""):
    """Pure: assemble the context appended after the director prompt template.

    Carries an explicit ALREADY-COMPLETED DIGEST (recent commits newest-first +
    the NEWEST docs/LEDGER.md items via head_lines, NOT the stale tail + the
    directive chain already issued this run) plus a BUILD-ON / de-dup rule, so
    the director cannot re-issue just-shipped work. root/ctl are injectable for
    tests; production calls use the module ROOT/CTL."""
    base = Path(root) if root is not None else ROOT
    plan = base / "docs/ORCHESTRATION_PLAN.md"
    plan_txt = plan.read_text(encoding="utf-8", errors="replace") if plan.exists() else "(no plan file)"
    plan_txt = cap_bytes_head_tail(plan_txt, PLAN_CTX_CAP if plan_cap is None else plan_cap,
                                   "ORCHESTRATION_PLAN", PLAN_CTX_HEAD)
    chain = _format_directive_chain(read_directive_history(12, ctl=ctl))
    ctx = (
        f"\n\n=== ORCHESTRATION PLAN (PRIMARY work source; pick next OPEN session, skip EXCLUDED) ===\n{plan_txt}"
        "\n\n=== ALREADY-COMPLETED DIGEST - every item below is DONE. BUILD ON it; NEVER re-issue it ==="
        f"\n\n--- RECENT COMMITS (newest first) ---\n{git('log', '--oneline', '-n', '25')}"
        "\n\n--- docs/LEDGER.md NEWEST items (newest-first; each line is a COMPLETED item) ---\n"
        f"{ledger_digest(head_lines('docs/LEDGER.md', LEDGER_HEAD_LINES, root=root), LEDGER_ITEM_HEAD, LEDGER_CTX_CAP, 'LEDGER head')}"
        "\n\n--- DIRECTIVES ALREADY ISSUED THIS RUN (do NOT re-issue any unit below) ---\n"
        f"{chain}"
        "\n\nDE-DUP RULE: before emitting the directive, cross-check your chosen unit against the "
        "ALREADY-COMPLETED DIGEST above (recent commits + newest LEDGER items + issued directives). "
        "If it duplicates a DONE ledger item, a recent commit, or a directive already issued, DISCARD "
        "it and synthesize the next NON-duplicate unit. BUILD ON completed work; never re-narrate or "
        "re-do it."
        f"\n\n=== ROADMAP.md (open items - high priority at TOP; head read) ===\n"
        f"{cap_bytes(head_lines('ROADMAP.md', 120, root=root), ROADMAP_CTX_CAP, 'ROADMAP head')}"
        f"\n\n=== LAST claude.done ===\n{json.dumps(last_done)}"
        f"\n\n=== LAST AUDIT (if REGRESS, the directive MUST fix it first) ===\n{last_audit or '(none)'}")
    if escalation:
        ctx += ("\n\n=== EXECUTOR ESCALATION (resolve FIRST; the directive MUST encode this "
                "decision + instruct the scaffolding + any ROADMAP/BACKLOG reshape) ===\n" + escalation)
    suffix = CFG.get("directive_suffix", "")
    if suffix:
        ctx += "\n\n" + DIRECTIVE_SUFFIX_HEADER + "\n" + suffix
    return ctx


def pop_executor_escalation(ctl=None):
    """Read and CONSUME the executor's escalation question.

    Consumed by the body assembler rather than by build_director_context so a
    context REBUILD cannot swallow it: the file is unlinked on read, so a second
    build would find nothing and the question would vanish from the very prompt
    it was raised for.
    """
    ask = (Path(ctl) if ctl is not None else CTL) / "gemini_ask.txt"
    if not ask.exists():
        return ""
    try:
        q = ask.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        q = ""
    ask.unlink(missing_ok=True)
    return q


def build_director_body(last_done, last_audit, *, root=None, ctl=None):
    """Assemble the exact stdin a director cycle sends: template + context.

    Sizing the WHOLE body is the point. The component caps cannot see the
    template or the operator brief, so only here is the real stdin known; an
    overflow is repaid out of the plan slice, which keeps the digest whole and
    keeps cap_stdin - whose blind middle cut lands squarely on that digest -
    from firing at all.
    """
    # Resolved next to this module, not under ROOT. The template is CODE that
    # ships with the controller, while ROOT is a configured repo_root pointing
    # at the checkout whose DOCS are read. In a worktree those differ, and
    # measuring a template other than the one actually sent is the same
    # wrong-component mistake this budget exists to stop.
    tmpl = (Path(__file__).resolve().parent / "director_prompt.md").read_text(encoding="utf-8")
    # The completion step is CHANNEL-SPECIFIC and the director must not invent it:
    # ahk blocks on control/claude.done (so the directive carries the sentinel
    # command), sdk returns a schema-validated structured_output (so it must NOT).
    # Substituted here because only the controller knows which channel is live.
    tmpl = tmpl.replace("{{FINAL_STEP}}", executor.final_step_instruction(CFG.get("channel")))
    escalation = pop_executor_escalation(ctl)
    ctx = build_director_context(last_done, last_audit, root=root, ctl=ctl,
                                 escalation=escalation)
    overflow = len(tmpl) + len(ctx) - ADJ_STDIN_CAP
    if overflow > 0:
        plan_cap = max(PLAN_CTX_CAP - overflow - PLAN_CTX_SLACK, PLAN_CTX_MIN)
        ctx = build_director_context(last_done, last_audit, root=root, ctl=ctl,
                                     plan_cap=plan_cap, escalation=escalation)
    return tmpl + ctx


def director(last_done, last_audit):
    return adjudicate(build_director_body(last_done, last_audit),
                  "Output ONLY the directive markdown for the next cycle. No preamble.")

def auditor(prev_sha, new_sha, clean_sha=None):
    if not new_sha or prev_sha == new_sha:
        return "VERDICT: CLEAN\n(no new commit this cycle)"
    rng = audit_range(clean_sha, new_sha)
    # The manifest is complete and authoritative; the diff body is head-truncated
    # in git path order. Naming every changed file BEFORE the body is what stops
    # "past the truncation cut" from reading as "absent from the commit" - the
    # false-positive REGRESS #6 failure mode (see AUDIT_DIFF_CAP).
    names = [ln for ln in git("diff", "--name-only", rng).splitlines() if ln.strip()]
    manifest = cap_bytes(git("diff", "--name-status", rng), AUDIT_MANIFEST_CAP, "manifest")
    diff = git("diff", rng)
    if len(diff) > AUDIT_DIFF_CAP:
        diff = diff[:AUDIT_DIFF_CAP] + (
            f"\n...[DIFF BODY truncated at {AUDIT_DIFF_CAP} bytes. git emits paths in byte "
            "order, so later-sorting paths are cut FIRST. Absence of a path below is NOT "
            "evidence it is unchanged - the FILES CHANGED manifest above is the complete list.]")
    tmpl = (ROOT / "ops/loop/auditor_prompt.md").read_text(encoding="utf-8")
    body = (f"{tmpl}\n\n=== RANGE {rng} ===\n{git('log','--oneline',rng)}"
            f"\n\n=== FILES CHANGED ({len(names)} total; complete + authoritative) ===\n{manifest}"
            f"\n\n=== DIFF (may be truncated; see manifest above for the full file list) ===\n{diff}")
    verdict = adjudicate(body, "Audit. First line MUST be 'VERDICT: CLEAN' or 'VERDICT: REGRESS', then the reason.")
    if verdict is None:
        # N3: the adjudicator errored (timeout / CLI) - an un-auditable cycle is NOT a
        # regression. Return a safe CLEAN so the controller's string ops never hit the
        # None sentinel and a flaky auditor never falsely blocks a clean cycle.
        return "VERDICT: CLEAN\n(auditor adjudicator error - could not audit this cycle; treated as non-regress)"
    return verdict

# ---- budget meter: sum active-session JSONL usage since start_ts -------
def _price(model, usage):
    t = CFG["price_per_mtok"]
    key = next((k for k in ("opus", "sonnet", "haiku") if k in (model or "").lower()), "default")
    p = t[key]
    return (usage.get("input_tokens", 0) * p["input"]
            + usage.get("output_tokens", 0) * p["output"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
            + usage.get("cache_read_input_tokens", 0) * p["cache_read"]) / 1_000_000

def _iso(ts):
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:  # noqa: BLE001
        return 0.0

def session_files():
    d = Path(CFG["transcript_dir"])
    pin = CFG.get("session_jsonl")
    if pin:
        p = Path(pin)
        return [p, *list((d / p.stem / "subagents").glob("*.jsonl"))]
    tops = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not tops:
        return []
    active = tops[0]
    return [active, *list((d / active.stem / "subagents").glob("*.jsonl"))]

def meter(start_ts):
    spent = 0.0
    for f in session_files():
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    o = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                msg = o.get("message", {})
                usage = msg.get("usage")
                if not usage:
                    continue
                ts = _iso(o.get("timestamp", ""))
                if ts and ts < start_ts:
                    continue
                spent += _price(msg.get("model", ""), usage)
        except Exception:  # noqa: BLE001
            continue
    return round(spent, 4)

# ---- AHK bridge liveness ------------------------------------------------
# The AHK bridge rewrites control/ahk_heartbeat.txt with an integer unix-epoch
# timestamp about once a second while it is alive. Without a liveness read a
# dead bridge is indistinguishable from a slow executor, so the controller sat
# out the whole cycle_deadline_sec (5400s = 90 minutes of dead air per hang)
# before saying anything.
AHK_HEARTBEAT_STALE_SEC = 60

def heartbeat_age(ctl=None, now=None):
    """Seconds since the AHK bridge last stamped its heartbeat, or None when the
    file is missing / unparseable / not yet written. Pure; ctl+now injectable."""
    base = Path(ctl) if ctl is not None else CTL
    p = base / "ahk_heartbeat.txt"
    try:
        stamp = int(float(p.read_text(encoding="utf-8", errors="replace").strip()))
    except (OSError, ValueError):
        return None
    return int((time.time() if now is None else now) - stamp)

def bridge_stale_message(age, limit=AHK_HEARTBEAT_STALE_SEC):
    """The loud one-liner for a dead bridge, or None while it is healthy. A
    future stamp (clock skew) is healthy, not stale. Advisory only - the caller
    logs it and lets the existing deadline logic decide whether to stop."""
    if age is None:
        return "AHK BRIDGE STALE (missing)"
    if age > limit:
        return f"AHK BRIDGE STALE ({age}s)"
    return None

# ---- main loop ---------------------------------------------------------
def wait_for(path, deadline_ts, watch_bridge=False):
    warned = False
    while time.time() < deadline_ts:
        if (CTL / "STOP").exists():
            log("external STOP seen"); sys.exit(0)
        if Path(path).exists():
            return True
        if watch_bridge and not warned:
            msg = bridge_stale_message(heartbeat_age())
            if msg:
                log(msg)
                warned = True
        time.sleep(CFG["poll_sec"])
    return False

def wait_gone(path, deadline_ts):
    while time.time() < deadline_ts:
        if (CTL / "STOP").exists():
            log("external STOP seen"); sys.exit(0)
        if not Path(path).exists():
            return True
        time.sleep(CFG["poll_sec"])
    return False

def stall_action(breach_n):
    """WP-I3 pure decision: how to answer the Nth consecutive cycle-deadline breach.
    The FIRST breach earns a one-shot recovery (inject /diagnose + extend the deadline
    once); a SECOND breach is a genuine hang -> hard STOP. Pure + unit-testable headless
    (no CFG / IO). main() wires this to the actual recover/stop side effects."""
    return "recover" if breach_n <= 1 else "stop"

def _canonical_interpreter():
    """Absolute path to the project interpreter, RESOLVED, never baked in.

    The pin stays ABSOLUTE - a bare ``py`` resolves to the dep-less pymanager
    runtime and zeroes the suite (tests/test_bare_py_ban.py) - but the account
    prefix is read from the environment. A directive naming one account's home
    is a directive that silently does not run under another, and a recovery step
    that does not run reports nothing.
    """
    local = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    candidate = Path(local) / "Programs" / "Python" / "Python314" / "python.exe"
    return str(candidate if candidate.exists() else Path(sys.executable))


def stall_recovery_directive(cycle):
    """WP-I3: the one-shot recovery typed into the EXISTING (stalled) executor on the
    FIRST cycle-deadline breach, before any hard STOP. NO /clear - the wedged session's
    context is exactly what /diagnose must inspect. The instruction self-terminates by
    running the done_sentinel final step, so the controller gets its claude.done either
    way (recovered or blocked). Line 1 is the CYCLE header the AHK bridge skips. Pure +
    unit-testable; the main() wiring extends the deadline once around it."""
    py = _canonical_interpreter()
    return (
        f"CYCLE={cycle}\n"
        "/diagnose the loop stall: run git status, read the newest pytest result file, read "
        "ops/runtime/health.json, and read the tail of ops/loop/control/controller.log; then "
        "either recover THIS cycle (finish the work package, commit + push + /done) OR write a "
        "one-line blocker to ops/loop/control/blocker.txt. Either way FINISH by running: "
        f"\"{py}\" ops/loop/done_sentinel.py --tests <pass_count> --regressions <0|1>"
    )

# ---- the running image vs the source on disk --------------------------------
# MEASURED 2026-07-27: three consecutive cycles shipped a fix to the director
# prompt assembler and NONE took effect. Controller pid 18300 started 00:37:50;
# 1f880bb1 / 7e0e8b80 / d3eb3b3a landed 05:03 / 05:24 / 05:34. Python imports a
# module ONCE, so the running image predated all three, and the live stdin at
# 05:45 (the control-dir prompt file) still carried the pre-fix ledger section while
# the identical call measured off disk carried the fixed one. The director then
# re-emitted a unit closed at f173ce39 for the second time - so the loop spent
# three cycles repairing the de-dup evidence of a process that would never load
# the repair. That is this repo's "present but does nothing" class, one layer
# above where R201 looked: not a guard reading the wrong side, but a FIX THAT IS
# NOT RUNNING. The controller therefore watches its own source and re-execs.
#
# director_prompt.md is deliberately EXCLUDED: build_director_body re-reads that
# template from disk every cycle, so a template edit is already live and
# re-execing for it would be a restart that buys nothing.
CODE_FILES = ("loop_controller.py", "executor.py", "adjudicator.py",
              "slots.py", "winmutex.py")


def code_file_digests(src_dir=None) -> dict:
    """Per-file sha256 of the controller's own imported source.

    Per FILE and not one lump digest, because the log line has to name what
    moved: "something changed" sends the operator diffing five files, and this
    check exists precisely for the case where nobody is watching.
    """
    base = Path(src_dir) if src_dir is not None else Path(__file__).resolve().parent
    out = {}
    for name in CODE_FILES:
        p = base / name
        try:
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            # An absent module is a CHANGED image, not an unknown one. Mapping it
            # to a sentinel keeps the comparison total - "no digest" must never
            # read as "no change".
            out[name] = "-absent-"
    return out


def controller_code_digest(src_dir=None) -> str:
    d = code_file_digests(src_dir)
    return hashlib.sha256(
        "".join(f"{k}:{d[k]}\n" for k in sorted(d)).encode("utf-8")).hexdigest()


CODE_DIGESTS_AT_IMPORT = code_file_digests()


def stale_code_reason(baseline=None, src_dir=None):
    """Which of the controller's own source files changed since it started."""
    base = CODE_DIGESTS_AT_IMPORT if baseline is None else baseline
    now = code_file_digests(src_dir)
    moved = [n for n in CODE_FILES if base.get(n) != now.get(n)]
    if not moved:
        return None
    return (f"controller source changed on disk since this process started: "
            f"{', '.join(moved)} - the running image predates the fix")


def resume_cycle(ctl=None, default=1) -> int:
    """The cycle a re-exec was taken at, consumed once.

    Consume-once is load-bearing: a leftover offset would make the operator's
    NEXT manual relaunch silently skip cycles it never ran.
    """
    p = (Path(ctl) if ctl is not None else CTL) / "resume_cycle.txt"
    if not p.exists():
        return default
    try:
        n = int((p.read_text(encoding="utf-8", errors="replace") or "").strip())
    except (OSError, ValueError):
        n = default
    p.unlink(missing_ok=True)
    return n if n >= 1 else default


def seed_spend_from_budget(ctl=None, state=None):
    """Restore adjudicator spend accounting after a self-restart.

    _ADJ_STATE lives in memory, so EVERY restart path already forgets spend.
    That was tolerable while a human typed the relaunch; it is not once the
    controller can relaunch itself on any code edit, because ceiling_usd would
    then never be reached. Restored spend is a FLOOR - a stale file must not
    hand back money the run already spent.
    """
    st = _ADJ_STATE if state is None else state
    rec = rjson((Path(ctl) if ctl is not None else CTL) / "budget.json", {}) or {}
    name = str(rec.get("adjudicator") or "").strip()
    try:
        usd = float(rec.get("adjudicator_usd") or 0.0)
    except (TypeError, ValueError):
        usd = 0.0
    if not name or usd <= 0:
        return st
    usd_map = st.setdefault("usd", {})
    if usd > float(usd_map.get(name, 0.0) or 0.0):
        usd_map[name] = usd
    return st


def restart_for_new_code(cycle, reason, *, execv=None, ctl=None, argv=None) -> bool:
    """Re-exec this controller so the new code actually runs.

    os.execv REPLACES the image and keeps the PID, which is what makes this safe
    against claim_repo: the lock holder is compared to os.getpid() and matches,
    so the fresh image reclaims its own repo instead of refusing to start.

    Called only from a cycle TOP, never mid-handshake - an exec between a typed
    directive and the claude.done it waits for would abandon a live executor.

    Returns False if the exec failed: a stale image emits duplicate directives,
    a dead controller emits nothing at all, and the operator is asleep. It never
    returns on success.
    """
    ex = os.execv if execv is None else execv
    args = list(sys.argv if argv is None else argv)
    base = Path(ctl) if ctl is not None else CTL
    log(f"RELOAD: {reason}; re-exec at cycle {cycle}")
    try:
        awrite(base / "resume_cycle.txt", str(int(cycle)))
    except OSError as e:
        log(f"RELOAD: could not record the resume cycle ({e}) - continuing stale")
        return False
    try:
        ex(sys.executable, [sys.executable, *args])
    except OSError as e:
        log(f"RELOAD FAILED: {e} - continuing on the stale image")
        return False
    return False


def cycle_top_code_guard(cycle):
    reason = stale_code_reason()
    if reason:
        restart_for_new_code(cycle, reason)


def claim_repo():
    """One controller per repo. Concurrency ACROSS repos (LW + RC) is the goal;
    two controllers inside THIS repo is corruption, because the control_dir
    handshake files are not namespaced and each would consume the other's
    gemini.ready and claude.done.

    Returns the run_id. Exits nonzero if another live controller holds the repo.
    """
    lock = CTL / "RUNNING.lock"
    if lock.exists():
        rec = rjson(lock, {})
        holder = int(rec.get("pid", 0) or 0)
        if holder and holder != os.getpid() and slots.pid_alive(holder):
            sys.stderr.write(
                f"another controller is already running in this repo "
                f"(pid={holder} run_id={rec.get('run_id')} since {rec.get('ts')}). "
                f"Stop it first, or delete {lock} if it is a stale leftover.\n")
            sys.exit(2)
        log(f"reclaiming stale RUNNING.lock (pid={holder} not alive)")
    run_id = uuid.uuid4().hex[:8]
    awrite(lock, json.dumps({"pid": os.getpid(), "run_id": run_id,
                             "ts": time.time(), "repo": str(ROOT)}))
    awrite(CTL / "run_id.txt", run_id)
    return run_id


def main():
    global RUN_ID
    RUN_ID = claim_repo()
    for f in ("STOP", "gemini.ready", "typed.flag", "claude.done", "cycle.txt"):
        (CTL / f).unlink(missing_ok=True)
    # A self-restart for new code resumes where it left off: starting over at 1
    # would let a code edit reset the cycle budget, and max_cycles is the real
    # limiter of this loop - there is no spend ceiling. Spend is restored for
    # the same reason - see seed_spend_from_budget.
    start_cycle = resume_cycle()
    if start_cycle > 1:
        seed_spend_from_budget()
        log(f"resumed after a code reload at cycle {start_cycle} "
            f"(code {controller_code_digest()[:12]})")
    start_ts = time.time()
    # persistent-session model: pin the session active at launch (the executor being
    # driven via /clear) so the meter bills it for the whole run, not whatever is newest.
    if not CFG.get("session_jsonl"):
        d = Path(CFG["transcript_dir"])
        tops = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if tops:
            CFG["session_jsonl"] = str(tops[0])
            log(f"pinned executor session jsonl: {tops[0].name}")
    prev_sha = head()
    last_clean_sha = prev_sha  # R61: auditor diff base = last known-good sha (loop start is clean)
    last_done, last_audit = {}, ""
    same_sha_streak = 0
    log(f"loop start dry_run={DRY} max_cycles={CFG.get('max_cycles')} head={prev_sha[:8]}")

    # core.hooksPath is LOCAL config and is not cloned, so a fresh clone runs with
    # NO commit gate while the tracked .githooks sits there looking installed. An
    # unattended run in that state pushes ungated and no one reads a session
    # report, so refuse to start instead.
    gate_gap = executor.gate_inactive_reason(ROOT)
    if gate_gap:
        stop(f"commit gate not active - refusing to run ungated: {gate_gap} "
             f"(fix: python scripts/install_hooks.py)")
    EXEC = executor.build(
        CFG, CTL, log=log, stop=stop, awrite=awrite, wait_for=wait_for,
        wait_gone=wait_gone, rjson=rjson, stall_action=stall_action,
        stall_recovery_directive=stall_recovery_directive)

    FIXED = CFG.get("fixed_directive")  # fixed-message mode: skip director+auditor entirely
    CYCLE_CMD = CFG.get("cycle_command")  # self-directing slash command typed verbatim; director SKIPPED, auditor KEPT
    for cycle in range(start_cycle, CFG["max_cycles"] + 1):
        # STOP is otherwise only polled inside wait_for/wait_gone, which never
        # run while the director is erroring - a 2026-07-03 outage spun 20+
        # directive-less cycles where an operator STOP would have been ignored.
        if (CTL / "STOP").exists():
            log("external STOP seen (cycle top)")
            sys.exit(0)
        # Beside the STOP poll deliberately: this is the only point in the cycle
        # where no handshake is in flight, so a re-exec cannot abandon an
        # executor waiting on claude.done.
        cycle_top_code_guard(cycle)
        override = consume_directive_override()
        src = cycle_source(CFG, override)
        if src == "override":
            body = override
            log(f"cycle {cycle}: operator directive override applied ({len(body)} chars)")
        elif src == "cycle_command":
            body = CYCLE_CMD
        elif src == "fixed":
            body = FIXED
        else:
            body = director(last_done, last_audit)
            if body is None:
                # N3: adjudicator retries exhausted (timeout / CLI error) - NOT a real
                # NO_WORK signal. Advance to the next cycle instead of terminating the whole
                # run; the no-progress (same-sha) guard still stops a persistent outage.
                log(f"cycle {cycle}: director adjudicator error (retries exhausted) - advancing, NOT terminating")
                continue
            if body[:40].upper().find("NO_WORK") >= 0:
                stop("director returned NO_WORK")
        awrite(CTL / "directive.md", body)
        awrite(CTL / "cycle.txt", str(cycle))
        # The channel-specific half of a cycle (the AHK typing handshake + done
        # sentinel; one `claude -p` call on the sdk channel) lives behind the
        # executor seam. Artifacts both channels share stay here: directive.md,
        # cycle.txt, budget.json and the metering below.
        # Slot held ONLY around the executor call - never around git, the director
        # or the auditor, so a long merge in this repo cannot starve the other one.
        with slots.hold(int(CFG.get("max_concurrent_lanes", 2)),
                        repo=str(ROOT), run_id=RUN_ID, cycle=cycle, log=log):
            rec = EXEC.run(cycle, body, src)
        done = rec.raw
        last_done = done
        new_sha = rec.sha or head()
        log(f"cycle {cycle}: claude.done sha={new_sha[:8]} tests={done.get('tests_pass')} regress={done.get('regressions')}")

        claude_info = meter(start_ts)  # informational only - NO cap on Claude (operator directive)
        brain = _ADJ_STATE.get("active") or adjudicator.ClaudeAdjudicator.name
        brain_usd = sum(float(v or 0.0) for v in (_ADJ_STATE.get("usd") or {}).values())
        budget_rec = {"adjudicator": brain, "adjudicator_usd": round(brain_usd, 4),
                      "claude_usd_info": claude_info, "cycle": cycle}
        # The sdk channel returns an authoritative per-cycle receipt (the CLI's own
        # total_cost_usd). Recorded ONLY when the channel actually produced one, so
        # the ahk channel's budget.json stays byte-identical to the pre-seam shape.
        # This is the number to trust: claude_usd_info comes from transcript
        # scraping, which LW measured wrong in three independent directions
        # (repeated usage records, dedup undercounting subagents, and pinning the
        # operator's interactive session instead of the executor's).
        if rec.cost_usd:
            budget_rec["executor_usd"] = round(rec.cost_usd, 4)
        awrite(CTL / "budget.json", json.dumps(budget_rec))
        # NO SPEND CEILING, and removing it was REQUIRED rather than tidy.
        # ceiling_usd was a runaway rail on the METERED vendor, and the claude
        # adjudicator was explicitly EXCLUDED from it because operator policy is
        # that Claude spend is uncapped. Once gemini went away on 2026-08-01 the
        # only spend left in _ADJ_STATE was claude's - so leaving the check in
        # place would have inverted it into a $200 cap on exactly the vendor
        # policy says must never be capped, and stopped a long run partway on a
        # notional subscription price that is not money billed.
        # max_cycles and cycle_deadline_sec are this loop's real limiters.
        log(f"cycle {cycle}: adjudicator={brain} est=${round(brain_usd, 4)} "
            f"executor_info=${claude_info} (both estimates, uncapped)")

        if not CFG.get("ignore_no_progress"):
            same_sha_streak = same_sha_streak + 1 if new_sha == prev_sha else 0
            if same_sha_streak >= 2:
                stop("no progress: same sha 2 cycles")

        verdict = "VERDICT: CLEAN\n(fixed-directive mode: auditor disabled)" if src == "fixed" else auditor(prev_sha, new_sha, last_clean_sha)
        if done.get("regressions"):
            verdict = ("VERDICT: REGRESS\nClaude self-reported it could NOT reach green this "
                       "cycle (regressions flag). Fix this before any new work.\n\n" + verdict)
        last_audit = verdict
        regress = verdict.strip().upper().startswith("VERDICT: REGRESS")
        # R61: advance the clean anchor only on a CLEAN verdict; a REGRESS keeps
        # the window open back to the last known-good sha so the eventual fix is
        # audited WITH the commits it repairs (never a lone docs-sync commit).
        if not regress:
            last_clean_sha = new_sha
        log(f"cycle {cycle}: audit -> {'REGRESS' if regress else 'CLEAN'}")
        # Persist the resolved directive to the chain so the NEXT director cycle
        # sees what was already issued + shipped and builds on it (continuity fix).
        record_directive_outcome(cycle, body, prev_sha, new_sha, done, verdict)
        prev_sha = new_sha

    stop(f"max_cycles {CFG['max_cycles']} reached")

if __name__ == "__main__":
    main()
