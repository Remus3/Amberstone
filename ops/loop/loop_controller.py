#!/usr/bin/env python
"""gemini-headless-upgrade loop controller (the BRAIN).

Headless. Never touches the GUI. Drives the cycle:
  gemini-director -> directive.md + gemini.ready -> (AHK types) -> claude.done
  -> meter budget -> gemini-auditor -> clean:advance | regress:FIX-first -> repeat

IPC = files in control_dir, atomic (tmp + os.replace), plain-text where AHK reads.
Both gemini and claude are stateless per cycle; continuity lives on disk
(git history + docs/LEDGER.md + the directive chain). See the Desktop BUILD LOG.
"""
import importlib.util
import json
import os
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

_CFG_ARG = (sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".json")
            else r"C:\Riot Commander\ops\loop\config.json")
try:
    CFG = json.loads(Path(_CFG_ARG).read_text(encoding="utf-8"))
except (FileNotFoundError, OSError):
    # Import-only fallback: a clean / non-Legion checkout (e.g. the Linux CI
    # nightly) has no config.json, and the pure helpers under unit test never
    # read CFG. A live launch always passes a real --config path, so production
    # never reaches this branch.
    CFG = {}
ROOT = Path(CFG.get("repo_root", Path(__file__).resolve().parents[2]))
CTL = Path(CFG.get("control_dir", Path(__file__).resolve().parent / "control"))
CTL.mkdir(parents=True, exist_ok=True)
DRY = bool(CFG.get("dry_run", False))
GEMINI_USD = 0.0  # cumulative estimated Gemini spend - THIS is the capped budget (not Claude)
RUN_ID = ""  # minted in main(); namespaces slot payloads across concurrent runs
# Adjudicator (external-brain) run state: which backend is live, whether the
# one-way exhaustion failover already fired, and per-backend estimated spend.
# Caller-owned so gemini() can rebuild the supervisor from the CURRENT module
# globals every call without resetting the sticky decision or the spend.
_ADJ_STATE = {"active": "", "failed_over": False, "usd": {}}

def log(m):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}"
    print(line, flush=True)
    with open(CTL / "controller.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")

def awrite(path, text):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

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
    operator override > cycle_command > fixed_directive > gemini director.

    cycle_command (e.g. a self-directing slash command like /RC2-Continue) is
    typed VERBATIM after /clear and SKIPS the gemini director - the command
    self-directs from its own living plan - but KEEPS the gemini auditor each
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
    """base..new_sha the gemini auditor scores each cycle (R61).

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
    # multi-KB single lines, so head-60 was 93KB) and gemini completed with an
    # EMPTY body -> misread as NO_WORK -> STOP with 5 OPEN queue rows. Doc
    # growth must never starve the director again: keep the HEAD (queue tables
    # / newest entries live at the top of both docs) and stamp a visible cut.
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[{label} truncated at {limit} bytes - full text in the repo file]"

# Hard byte budgets for the unbounded director-context components.
# 2026-07-02 re-tighten: gemini CLI silently returns EMPTY stdout above
# ~80KB stdin (80KB delivered fine, 160KB empty, no stderr error - measured
# live; the 01:56 outage killed cycles 9-100 of the prior run). The 2026-07-01
# caps (140K plan alone) still allowed a >160KB total, so every component cap
# now fits the WHOLE prompt inside GEMINI_STDIN_CAP with headroom.
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

# Auditor payload split. 2026-07-19 false-positive REGRESS #6: the whole budget
# went to the diff BODY, which git emits in path byte order - a commit touching
# the generated mirror (Share/, 'S' 0x53) and its true source (agents/, 'a'
# 0x61) spent every byte on mirror padding, so the auditor never saw the true
# source and called a complete, CI-green commit a regression. A complete file
# manifest is worth far more per byte than deeper diff context, so the body
# yields 15K to guarantee the manifest always fits under GEMINI_STDIN_CAP.
AUDIT_DIFF_CAP = 40_000
AUDIT_MANIFEST_CAP = 12_000

# Proven-safe gemini stdin ceiling (see above). cap_stdin() backstops EVERY
# gemini() call (director / auditor / stall) at this size.
GEMINI_STDIN_CAP = 60_000

def cap_stdin(body, limit=None):
    """Backstop: keep the HEAD (prompt template + instructions) and the TAIL
    (directive_suffix / escalation / final rules); cut the expendable middle."""
    lim = GEMINI_STDIN_CAP if limit is None else limit
    if len(body) <= lim:
        return body
    marker = "\n...[STDIN CAP: middle truncated to fit the gemini CLI stdin limit - head + tail preserved]...\n"
    keep = lim - len(marker)
    head = int(keep * 0.6)
    return body[:head] + marker + body[len(body) - (keep - head):]

# ---- directive-chain continuity (persisted; survives controller restarts) ---
def directive_title(body):
    """A compact one-line label for an issued directive (for the chain digest)."""
    if not body:
        return "(empty)"
    theme = scope = ""
    for line in body.splitlines():
        s = line.strip()
        u = s.upper()
        if u.startswith("THEME:") and not theme:
            theme = s.split(":", 1)[1].strip()
        elif u.startswith("SCOPE:") and not scope:
            scope = s.split(":", 1)[1].strip()
    if theme or scope:
        return (f"{theme} - {scope}".strip(" -"))[:160]
    for line in body.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
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

# ---- external brain (backends + failover live in ops/loop/adjudicator.py) ----
def _supervisor():
    """The failover supervisor, built from the CURRENT module globals.

    Rebuilt per call because CFG / CTL / log / awrite are module-scope and are
    swapped by the loop test-suite and by an operator hot-editing config.json;
    _ADJ_STATE carries the sticky failover decision and the accumulated
    per-backend spend across every rebuild.
    """
    return adjudicator.FailoverAdjudicator(CFG, CTL, log, awrite, state=_ADJ_STATE)

def gemini(prompt_body, instruction):
    """The loop's single external-brain call site, routed to the resolved
    adjudicator backend (gemini today; claude after a config flip or after the
    automatic credit-exhaustion failover fires).

    Kept under the historical name because director()/auditor() call it and it is
    the monkeypatch seam every existing loop test binds to. All vendor mechanics -
    the PowerShell invocation, the retry ladder, the UTF-16 stderr decode and the
    None-on-empty sentinel - now live in the backend classes; N3 semantics are
    unchanged: EMPTY output is NEVER a usable answer, so a completed-but-empty
    call returns None exactly like a timeout does.

    Serialized machine-wide on GEMINI_MUTEX: Gemini is ONE metered account shared
    with the Sibling-A loop. Two concurrent director calls burn quota in
    parallel and can trip RESOURCE_EXHAUSTED, which the failover logic would
    misread as real credit exhaustion and STICKILY swap the backend for the rest
    of the run. Director calls are seconds, so the serialization costs nothing.
    """
    with winmutex.hold(winmutex.GEMINI_MUTEX, log=log):
        return _gemini_call(prompt_body, instruction)


def _gemini_call(prompt_body, instruction):
    global GEMINI_USD
    sup = _supervisor()
    out = sup.ask(cap_stdin(prompt_body), instruction)
    sup.save_state(_ADJ_STATE)
    GEMINI_USD = _ADJ_STATE["usd"].get(adjudicator.GeminiAdjudicator.name, 0.0)
    return out

# ---- adjudicator roles -------------------------------------------------
def build_director_context(last_done, last_audit, *, root=None, ctl=None):
    """Pure: assemble the context appended after the director prompt template.

    Carries an explicit ALREADY-COMPLETED DIGEST (recent commits newest-first +
    the NEWEST docs/LEDGER.md items via head_lines, NOT the stale tail + the
    directive chain already issued this run) plus a BUILD-ON / de-dup rule, so
    the director cannot re-issue just-shipped work. root/ctl are injectable for
    tests; production calls use the module ROOT/CTL."""
    base = Path(root) if root is not None else ROOT
    plan = base / "docs/ORCHESTRATION_PLAN.md"
    plan_txt = plan.read_text(encoding="utf-8", errors="replace") if plan.exists() else "(no plan file)"
    plan_txt = cap_bytes(plan_txt, PLAN_CTX_CAP, "ORCHESTRATION_PLAN")
    chain = _format_directive_chain(read_directive_history(12, ctl=ctl))
    ctx = (
        f"\n\n=== ORCHESTRATION PLAN (PRIMARY work source; pick next OPEN session, skip EXCLUDED) ===\n{plan_txt}"
        "\n\n=== ALREADY-COMPLETED DIGEST - every item below is DONE. BUILD ON it; NEVER re-issue it ==="
        f"\n\n--- RECENT COMMITS (newest first) ---\n{git('log', '--oneline', '-n', '25')}"
        "\n\n--- docs/LEDGER.md NEWEST items (newest-first; each line is a COMPLETED item) ---\n"
        f"{cap_bytes(head_lines('docs/LEDGER.md', 60, root=root), LEDGER_CTX_CAP, 'LEDGER head')}"
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
    ask = (Path(ctl) if ctl is not None else CTL) / "gemini_ask.txt"
    if ask.exists():
        try:
            q = ask.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            q = ""
        if q:
            ctx += ("\n\n=== EXECUTOR ESCALATION (resolve FIRST; the directive MUST encode this "
                    "decision + instruct the scaffolding + any ROADMAP/BACKLOG reshape) ===\n" + q)
        ask.unlink(missing_ok=True)
    ctx += "\n\n" + CFG.get("directive_suffix", "")
    return ctx

def director(last_done, last_audit):
    tmpl = (ROOT / "ops/loop/director_prompt.md").read_text(encoding="utf-8")
    ctx = build_director_context(last_done, last_audit)
    return gemini(tmpl + ctx, "Output ONLY the directive markdown for the next cycle. No preamble.")

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
    verdict = gemini(body, "Audit. First line MUST be 'VERDICT: CLEAN' or 'VERDICT: REGRESS', then the reason.")
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

def stall_recovery_directive(cycle):
    """WP-I3: the one-shot recovery typed into the EXISTING (stalled) executor on the
    FIRST cycle-deadline breach, before any hard STOP. NO /clear - the wedged session's
    context is exactly what /diagnose must inspect. The instruction self-terminates by
    running the done_sentinel final step, so the controller gets its claude.done either
    way (recovered or blocked). Line 1 is the CYCLE header the AHK bridge skips. Pure +
    unit-testable; the main() wiring extends the deadline once around it."""
    py = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
    return (
        f"CYCLE={cycle}\n"
        "/diagnose the loop stall: run git status, read the newest pytest result file, read "
        "ops/runtime/health.json, and read the tail of ops/loop/control/controller.log; then "
        "either recover THIS cycle (finish the work package, commit + push + /done) OR write a "
        "one-line blocker to ops/loop/control/blocker.txt. Either way FINISH by running: "
        f"\"{py}\" ops/loop/done_sentinel.py --tests <pass_count> --regressions <0|1>"
    )

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
    log(f"loop start dry_run={DRY} ceiling={CFG['ceiling_usd']} head={prev_sha[:8]}")

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

    FIXED = CFG.get("fixed_directive")  # fixed-message mode: skip gemini director+auditor entirely
    CYCLE_CMD = CFG.get("cycle_command")  # self-directing slash command typed verbatim; director SKIPPED, auditor KEPT
    for cycle in range(1, CFG["max_cycles"] + 1):
        # STOP is otherwise only polled inside wait_for/wait_gone, which never
        # run while the director is erroring - a 2026-07-03 outage spun 20+
        # directive-less cycles where an operator STOP would have been ignored.
        if (CTL / "STOP").exists():
            log("external STOP seen (cycle top)")
            sys.exit(0)
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
        brain = _ADJ_STATE.get("active") or adjudicator.backend_name(CFG)
        brain_usd = sum(float(v or 0.0) for v in (_ADJ_STATE.get("usd") or {}).values())
        # gemini_usd stays for backward compatibility (dashboards + prior runs read it).
        budget_rec = {"gemini_usd": round(GEMINI_USD, 4), "gemini_ceiling": CFG["ceiling_usd"],
                      "adjudicator": brain, "adjudicator_usd": round(brain_usd, 4),
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
        # ceiling_usd is a runaway rail on the METERED vendor. claude adjudicator
        # spend is EXCLUDED unless claude_adjudicator.count_against_ceiling is
        # true, because operator policy is that Claude spend is uncapped - a swap
        # to the local adjudicator must not inherit the $200 gemini rail and then
        # silently stop an otherwise-free run.
        capped_usd = adjudicator.ceiling_spend(CFG, _ADJ_STATE.get("usd"))
        log(f"cycle {cycle}: adjudicator={brain} capped=${round(capped_usd, 4)}/{CFG['ceiling_usd']} "
            f"total=${round(brain_usd, 4)} claude_info(uncapped)=${claude_info}")
        if capped_usd >= CFG["ceiling_usd"]:
            stop(f"adjudicator budget ceiling hit: ${round(capped_usd, 4)} >= ${CFG['ceiling_usd']}")

        if not CFG.get("ignore_no_progress"):
            same_sha_streak = same_sha_streak + 1 if new_sha == prev_sha else 0
            if same_sha_streak >= 2:
                stop("no progress: same sha 2 cycles")

        verdict = "VERDICT: CLEAN\n(fixed-directive mode: gemini auditor disabled)" if src == "fixed" else auditor(prev_sha, new_sha, last_clean_sha)
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
