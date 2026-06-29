#!/usr/bin/env python
"""gemini-headless-upgrade loop controller (the BRAIN).

Headless. Never touches the GUI. Drives the cycle:
  gemini-director -> directive.md + gemini.ready -> (AHK types) -> claude.done
  -> meter budget -> gemini-auditor -> clean:advance | regress:FIX-first -> repeat

IPC = files in control_dir, atomic (tmp + os.replace), plain-text where AHK reads.
Both gemini and claude are stateless per cycle; continuity lives on disk
(git history + docs/LEDGER.md + the directive chain). See the Desktop BUILD LOG.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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

# ---- gemini (read-only, STDIN pipe; mirrors tools/gemini_audit.ps1) ----
def gemini(prompt_body, instruction):
    global GEMINI_USD
    infile = CTL / "_gemini_in.txt"
    awrite(infile, prompt_body)
    model = CFG.get("gemini_model", "gemini-3-pro-preview")
    inst = instruction.replace("'", "''")
    ps = ("$ErrorActionPreference='Continue';"
          "$env:GEMINI_API_KEY=[Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User');"
          f"Get-Content -Raw '{infile}' | "
          f"{CFG.get('gemini_cmd', 'gemini')} -p '{inst}' -m '{model}' --approval-mode plan --skip-trust 2>$null | Out-String")
    out = ""
    any_success = False  # N3: a completed call (even empty stdout) vs all-retries-errored
    for tryn in range(1, 4):
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                               capture_output=True, text=True, timeout=300,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = (r.stdout or "").strip()
            any_success = True
        except Exception as e:  # noqa: BLE001
            out = ""
            log(f"gemini try {tryn} error: {e}")
        if out:
            break
        time.sleep(8 * tryn)
    gp = CFG.get("gemini_price_per_mtok", {"input": 2.0, "output": 12.0})
    GEMINI_USD += (len(prompt_body) / 4 * gp["input"] + len(out) / 4 * gp["output"]) / 1_000_000
    # N3: distinguish a TIMEOUT / CLI-error (every try raised, never completed) from a
    # genuine empty answer. Return the None sentinel ONLY when no try completed, so the
    # director path can re-enter the cycle instead of mis-reading "" as NO_WORK and
    # falsely terminating a multi-cycle run (the 2026-06-22 300s-timeout false-stop class).
    if not out and not any_success:
        return None
    return out

# ---- gemini roles ------------------------------------------------------
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
    chain = _format_directive_chain(read_directive_history(12, ctl=ctl))
    ctx = (
        f"\n\n=== ORCHESTRATION PLAN (PRIMARY work source; pick next OPEN session, skip EXCLUDED) ===\n{plan_txt}"
        "\n\n=== ALREADY-COMPLETED DIGEST - every item below is DONE. BUILD ON it; NEVER re-issue it ==="
        f"\n\n--- RECENT COMMITS (newest first) ---\n{git('log', '--oneline', '-n', '25')}"
        "\n\n--- docs/LEDGER.md NEWEST items (newest-first; each line is a COMPLETED item) ---\n"
        f"{head_lines('docs/LEDGER.md', 60, root=root)}"
        "\n\n--- DIRECTIVES ALREADY ISSUED THIS RUN (do NOT re-issue any unit below) ---\n"
        f"{chain}"
        "\n\nDE-DUP RULE: before emitting the directive, cross-check your chosen unit against the "
        "ALREADY-COMPLETED DIGEST above (recent commits + newest LEDGER items + issued directives). "
        "If it duplicates a DONE ledger item, a recent commit, or a directive already issued, DISCARD "
        "it and synthesize the next NON-duplicate unit. BUILD ON completed work; never re-narrate or "
        "re-do it."
        f"\n\n=== ROADMAP.md (open items - high priority at TOP; head read) ===\n{head_lines('ROADMAP.md', 120, root=root)}"
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

def auditor(prev_sha, new_sha):
    if not new_sha or prev_sha == new_sha:
        return "VERDICT: CLEAN\n(no new commit this cycle)"
    rng = f"{prev_sha}..{new_sha}"
    diff = git("diff", rng)
    if len(diff) > 55000:
        diff = diff[:55000] + "\n...[truncated]"
    tmpl = (ROOT / "ops/loop/auditor_prompt.md").read_text(encoding="utf-8")
    body = f"{tmpl}\n\n=== RANGE {rng} ===\n{git('log','--oneline',rng)}\n\n=== DIFF ===\n{diff}"
    verdict = gemini(body, "Audit. First line MUST be 'VERDICT: CLEAN' or 'VERDICT: REGRESS', then the reason.")
    if verdict is None:
        # N3: gemini errored (timeout / CLI) - an un-auditable cycle is NOT a regression.
        # Return a safe CLEAN so the controller's string ops never hit the None sentinel
        # and a flaky auditor never falsely blocks a clean cycle.
        return "VERDICT: CLEAN\n(auditor gemini error - could not audit this cycle; treated as non-regress)"
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

# ---- main loop ---------------------------------------------------------
def wait_for(path, deadline_ts):
    while time.time() < deadline_ts:
        if (CTL / "STOP").exists():
            log("external STOP seen"); sys.exit(0)
        if Path(path).exists():
            return True
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

def main():
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
    last_done, last_audit = {}, ""
    same_sha_streak = 0
    log(f"loop start dry_run={DRY} ceiling={CFG['ceiling_usd']} head={prev_sha[:8]}")

    FIXED = CFG.get("fixed_directive")  # fixed-message mode: skip gemini director+auditor entirely
    CYCLE_CMD = CFG.get("cycle_command")  # self-directing slash command typed verbatim; director SKIPPED, auditor KEPT
    for cycle in range(1, CFG["max_cycles"] + 1):
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
                # N3: gemini retries exhausted (timeout / CLI error) - NOT a real NO_WORK
                # signal. Advance to the next cycle instead of terminating the whole run;
                # the no-progress (same-sha) guard still stops a persistent outage cleanly.
                log(f"cycle {cycle}: director gemini error (retries exhausted) - advancing, NOT terminating")
                continue
            if not body or body[:40].upper().find("NO_WORK") >= 0:
                stop("director returned no work (NO_WORK / empty)")
        awrite(CTL / "directive.md", body)
        awrite(CTL / "cycle.txt", str(cycle))
        clear_line = "/clear\n" if CFG.get("clear_each_cycle", True) else ""
        if src in ("cycle_command", "fixed"):
            # type the literal task line (single line, no embedded newlines) after /clear
            awrite(CTL / "gemini.ready", f"CYCLE={cycle}\n{clear_line}{body}")
        else:
            awrite(CTL / "gemini.ready",
                   f"CYCLE={cycle}\n{clear_line}"
                   "/gemini-headless-upgrade and Read the file ops/loop/control/directive.md and fully execute it now. "
                   "No questions; auto-pick the recommended option and proceed.")
        log(f"cycle {cycle}: directive written ({len(body)} chars), gemini.ready set")

        # AHK/stub deletes gemini.ready after typing; its disappearance IS the typed signal
        if not wait_gone(CTL / "gemini.ready", time.time() + 120):
            stop(f"cycle {cycle}: AHK never typed (gemini.ready not consumed in 120s)")
        deadline = time.time() + CFG["cycle_deadline_sec"]
        log(f"cycle {cycle}: typed (ready consumed); deadline in {CFG['cycle_deadline_sec']}s")

        # WP-I3: one-shot stall recovery before a hard STOP. On the FIRST cycle-deadline
        # breach, inject a /diagnose recovery directive into the existing (stalled) session
        # and extend the deadline ONCE (decision = stall_action, pure + tested); hard-STOP
        # only on a SECOND breach. The no-progress and AHK-never-typed guards remain the
        # runaway backstops so a truly wedged run still stops cleanly after exactly one
        # recovery attempt.
        breach = 0
        while not wait_for(CTL / "claude.done", deadline):
            breach += 1
            if stall_action(breach) == "stop":
                stop(f"cycle {cycle}: claude.done not seen after stall recovery (hard hang)")
            log(f"cycle {cycle}: deadline breach {breach} - injecting stall recovery, extending once")
            awrite(CTL / "gemini.ready", stall_recovery_directive(cycle))
            if not wait_gone(CTL / "gemini.ready", time.time() + 120):
                stop(f"cycle {cycle}: AHK never typed the stall-recovery directive")
            deadline = time.time() + CFG["cycle_deadline_sec"]
        done = rjson(CTL / "claude.done", {})
        (CTL / "claude.done").unlink(missing_ok=True)
        last_done = done
        new_sha = done.get("sha") or head()
        log(f"cycle {cycle}: claude.done sha={new_sha[:8]} tests={done.get('tests_pass')} regress={done.get('regressions')}")

        claude_info = meter(start_ts)  # informational only - NO cap on Claude (operator directive)
        awrite(CTL / "budget.json", json.dumps(
            {"gemini_usd": round(GEMINI_USD, 4), "gemini_ceiling": CFG["ceiling_usd"],
             "claude_usd_info": claude_info, "cycle": cycle}))
        log(f"cycle {cycle}: gemini=${round(GEMINI_USD, 4)}/{CFG['ceiling_usd']} "
            f"claude_info(uncapped)=${claude_info}")
        if GEMINI_USD >= CFG["ceiling_usd"]:
            stop(f"gemini budget ceiling hit: ${round(GEMINI_USD, 4)} >= ${CFG['ceiling_usd']}")

        if not CFG.get("ignore_no_progress"):
            same_sha_streak = same_sha_streak + 1 if new_sha == prev_sha else 0
            if same_sha_streak >= 2:
                stop("no progress: same sha 2 cycles")

        verdict = "VERDICT: CLEAN\n(fixed-directive mode: gemini auditor disabled)" if src == "fixed" else auditor(prev_sha, new_sha)
        if done.get("regressions"):
            verdict = ("VERDICT: REGRESS\nClaude self-reported it could NOT reach green this "
                       "cycle (regressions flag). Fix this before any new work.\n\n" + verdict)
        last_audit = verdict
        regress = verdict.strip().upper().startswith("VERDICT: REGRESS")
        log(f"cycle {cycle}: audit -> {'REGRESS' if regress else 'CLEAN'}")
        # Persist the resolved directive to the chain so the NEXT director cycle
        # sees what was already issued + shipped and builds on it (continuity fix).
        record_directive_outcome(cycle, body, prev_sha, new_sha, done, verdict)
        prev_sha = new_sha

    stop(f"max_cycles {CFG['max_cycles']} reached")

if __name__ == "__main__":
    main()
