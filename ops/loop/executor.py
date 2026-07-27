#!/usr/bin/env python
"""Pluggable EXECUTOR channel for the headless loop (the thing that does the work).

Companion seam to the adjudicator (the read-only BRAIN). The loop needs exactly
one thing from an executor: hand it a directive, get back what happened. That
was hard-wired to the AutoHotkey GUI bridge - a machine-wide singleton keyed on
a window title, which is why two loops could never run at once.

This module is the seam: one contract, `run(cycle, body, src) -> DoneRecord`,
with the AHK bridge lifted verbatim as today's default, plus a headless
`claude -p` channel that holds no machine-wide resource.

Ported from the Sibling-A F1 spec (LW head 8a7d61a, 2026-07-26). Unlike
ops/loop/slots.py and ops/loop/winmutex.py this file is NOT byte-identical
across the two repos by contract: it lifts each repo's own controller code, so
RC's copy carries RC's directive opener, RC's watch_bridge deadline wait and
RC's commit-gate installer path.

The extraction is a REFACTOR ONLY. Every string the AHK path writes, every
deadline, every log line and every stop() reason is byte-preserved from
loop_controller.py - the acceptance test is that a hermetic 2-cycle dry run
produces identical control/ artifacts before and after. Nothing here is new
behavior on the ahk channel.

The controller owns the artifacts both channels share (directive.md, cycle.txt,
budget.json, the metering); the executor owns only what is channel-specific -
for AHK that is the gemini.ready typing handshake and the claude.done sentinel.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DoneRecord:
    """What one executed cycle produced.

    `raw` is the parsed claude.done payload, carried through untouched because
    the director prompt is built from it - reshaping it would change directive
    text and make this refactor a behavior change.

    cost_usd / session_id are 0.0 / None on the AHK channel: that channel returns
    no receipt, which is why the controller still scrapes transcripts for cost.
    The SDK channel fills both from the `claude -p` result JSON, which is what
    retires the scraper - see the three independent ways the transcript meter is
    wrong, measured on LW's P4 run (repeated usage records per message id,
    dedup undercounting subagent transcripts, and auto-pinning the operator's
    INTERACTIVE session instead of the executor's).
    """

    cycle: int
    sha: str = ""
    tests_pass: str = "?"
    regressions: bool = False
    cost_usd: float = 0.0
    session_id: str | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)


DIRECTIVE_OPENER = (
    "/gemini-headless-upgrade and Read the file ops/loop/control/directive.md and fully execute it now. "
    "No questions; auto-pick the recommended option and proceed."
)


def directive_payload(cycle: int, body: str, src: str, clear_each_cycle: bool = True) -> str:
    """The exact text the bridge types. Lifted verbatim from loop_controller.

    Byte-exactness matters more than it looks: line 1 is the CYCLE header the AHK
    bridge skips, and the leading `/clear` is what gives each cycle a fresh
    context. Change the shape and the bridge silently types a slash command as
    prose (the `/clear` -> `clear/` race this channel already has a scar from).
    """
    clear_line = "/clear\n" if clear_each_cycle else ""
    if src in ("cycle_command", "fixed"):
        # a literal single-line task, typed as-is after /clear
        return f"CYCLE={cycle}\n{clear_line}{body}"
    return f"CYCLE={cycle}\n{clear_line}{DIRECTIVE_OPENER}"


class AhkExecutor:
    """The legacy GUI channel: write gemini.ready, wait for AHK to type it, wait
    for the done sentinel. Verbatim lift - see the module docstring.

    Machine-wide singleton by construction (it targets a window title), so this
    channel can never satisfy the concurrent-run requirement. That is the whole
    reason the SDK channel exists.
    """

    name = "ahk"

    def __init__(self, cfg, ctl, *, log, stop, awrite, wait_for, wait_gone, rjson,
                 stall_action, stall_recovery_directive):
        self.cfg = cfg
        self.ctl = ctl
        self.log = log
        self.stop = stop
        self.awrite = awrite
        self.wait_for = wait_for
        self.wait_gone = wait_gone
        self.rjson = rjson
        self.stall_action = stall_action
        self.stall_recovery_directive = stall_recovery_directive

    def run(self, cycle: int, body: str, src: str) -> DoneRecord:
        ctl = self.ctl
        self.awrite(ctl / "gemini.ready",
                    directive_payload(cycle, body, src,
                                      self.cfg.get("clear_each_cycle", True)))
        self.log(f"cycle {cycle}: directive written ({len(body)} chars), gemini.ready set")

        # AHK/stub deletes gemini.ready after typing; its disappearance IS the typed signal
        if not self.wait_gone(ctl / "gemini.ready", time.time() + 120):
            self.stop(f"cycle {cycle}: AHK never typed (gemini.ready not consumed in 120s)")
        deadline = time.time() + self.cfg["cycle_deadline_sec"]
        self.log(f"cycle {cycle}: typed (ready consumed); deadline in {self.cfg['cycle_deadline_sec']}s")

        # WP-I3: one-shot stall recovery before a hard STOP. On the FIRST cycle-deadline
        # breach, inject a /diagnose recovery directive into the existing (stalled) session
        # and extend the deadline ONCE (decision = stall_action, pure + tested); hard-STOP
        # only on a SECOND breach. The no-progress and AHK-never-typed guards remain the
        # runaway backstops so a truly wedged run still stops cleanly after exactly one
        # recovery attempt.
        breach = 0
        while not self.wait_for(ctl / "claude.done", deadline, watch_bridge=True):
            breach += 1
            if self.stall_action(breach) == "stop":
                self.stop(f"cycle {cycle}: claude.done not seen after stall recovery (hard hang)")
            self.log(f"cycle {cycle}: deadline breach {breach} - injecting stall recovery, extending once")
            self.awrite(ctl / "gemini.ready", self.stall_recovery_directive(cycle))
            if not self.wait_gone(ctl / "gemini.ready", time.time() + 120):
                self.stop(f"cycle {cycle}: AHK never typed the stall-recovery directive")
            deadline = time.time() + self.cfg["cycle_deadline_sec"]

        done = self.rjson(ctl / "claude.done", {})
        (ctl / "claude.done").unlink(missing_ok=True)
        return DoneRecord(
            cycle=cycle,
            sha=done.get("sha") or "",
            tests_pass=done.get("tests_pass", "?"),
            regressions=bool(done.get("regressions")),
            raw=done,
        )


DONE_SCHEMA = {
    "type": "object",
    "properties": {
        "sha": {"type": "string"},
        "tests_pass": {"type": "string"},
        "regressions": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": ["sha", "tests_pass", "regressions", "summary"],
}

FINAL_STEP = (
    "FINAL STEP: do NOT run ops/loop/done_sentinel.py. Instead return the JSON object "
    "required by the output schema: sha (the live git HEAD after your commit), "
    "tests_pass (the count you observed THIS run, as a string), regressions (true only "
    "if you could not reach green), summary (one line)."
)


def sdk_prompt(cycle: int, body: str, src: str) -> str:
    """The prompt piped to `claude -p` on stdin.

    Deliberately NOT directive_payload(): that one carries a CYCLE header the AHK
    bridge skips and a leading `/clear`, both of which are artifacts of typing
    into a live window. A `-p` call is already a fresh process, so `/clear` is
    meaningless and the header would just be prose in the prompt.
    """
    head = body if src in ("cycle_command", "fixed") else DIRECTIVE_OPENER
    return f"{head}\n\n{FINAL_STEP}\n"


class SdkExecutor:
    """Headless `claude -p` channel. No window, no window title, no typing.

    This is the channel that makes concurrent LW+RC runs possible: it holds no
    machine-wide resource, so two loops collide only on things the slot governor
    and the named mutexes already bound.

    It also returns a receipt the AHK channel never could - total_cost_usd and a
    schema-validated structured_output - which is what retires the transcript
    meter and done_sentinel.py once this channel is the default.
    """

    name = "sdk"

    def __init__(self, cfg, ctl, *, log, stop, awrite, **_ignored):
        self.cfg = cfg
        self.ctl = ctl
        self.log = log
        self.stop = stop
        self.awrite = awrite
        self.session_id: str | None = None

    def _argv_prefix(self) -> list:
        """`executor_cmd` may be a string or an argv list (tests inject a shim)."""
        cmd = self.cfg.get("executor_cmd")
        if isinstance(cmd, list):
            return list(cmd)
        if isinstance(cmd, str) and cmd:
            return [cmd]
        import shutil
        return [shutil.which("claude.cmd") or shutil.which("claude") or "claude"]

    def build_argv(self, cycle: int) -> list:
        import json as _json
        argv = self._argv_prefix() + [
            "-p",
            "--output-format", "json",
            "--input-format", "text",
            "--permission-mode", self.cfg.get("permission_mode", "bypassPermissions"),
            "--json-schema", _json.dumps(DONE_SCHEMA),
            "--add-dir", str(self.cfg.get("repo_root", ".")),
        ]
        model = self.cfg.get("executor_model")
        if model:
            argv += ["--model", str(model)]
        budget = self.cfg.get("cycle_budget_usd")
        if budget:
            argv += ["--max-budget-usd", str(budget)]
        # clear_each_cycle True reproduces the AHK channel's /clear exactly: a
        # brand new session per cycle. False keeps continuity via --resume, which
        # is cheaper (no cold re-read of CLAUDE.md + living docs each cycle).
        if self.cfg.get("clear_each_cycle", True) or not self.session_id:
            import uuid
            argv += ["--session-id", str(uuid.uuid4())]
        else:
            argv += ["--resume", self.session_id]
        return argv

    def run(self, cycle: int, body: str, src: str) -> DoneRecord:
        import json as _json

        argv = self.build_argv(cycle)
        prompt = sdk_prompt(cycle, body, src)
        timeout = float(self.cfg.get("cycle_deadline_sec", 5400))
        self.log(f"cycle {cycle}: sdk executor starting ({len(body)} chars, timeout {timeout:.0f}s)")

        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", cwd=str(self.cfg.get("repo_root", ".")),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            out, err = proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            # NEVER Stop-Process (CLAUDE.md hard rule); taskkill /T so the whole
            # tree dies - a `claude -p` that wedged has child tool processes.
            self.log(f"cycle {cycle}: sdk timeout after {timeout:.0f}s - taskkill /F /T")
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.SubprocessError):
                pass
            proc.wait(timeout=30)
            return DoneRecord(cycle=cycle, error=f"timeout after {timeout:.0f}s")

        try:
            res = _json.loads(out.strip() or "{}")
        except ValueError:
            head = (out or err or "").strip().replace("\n", " ")[:200]
            self.log(f"cycle {cycle}: sdk returned unparseable stdout: {head}")
            return DoneRecord(cycle=cycle, error=f"unparseable result: {head}")

        cost = float(res.get("total_cost_usd") or 0.0)
        sid = res.get("session_id")
        if sid:
            self.session_id = sid

        if res.get("is_error") or proc.returncode != 0:
            detail = str(res.get("result") or err or "").strip().replace("\n", " ")[:200]
            self.log(f"cycle {cycle}: sdk reported error (rc={proc.returncode}): {detail}")
            return DoneRecord(cycle=cycle, cost_usd=cost, session_id=sid,
                              error=detail or f"exit {proc.returncode}")

        so = res.get("structured_output")
        if not isinstance(so, dict) or not all(k in so for k in DONE_SCHEMA["required"]):
            # The CLI validates against --json-schema, so this means the run ended
            # without producing one (hit a limit, refused, wandered off). Treat it
            # as a failed cycle rather than inventing fields - a fabricated sha
            # would defeat the controller's same-sha no-progress guard.
            self.log(f"cycle {cycle}: sdk returned no valid structured_output")
            return DoneRecord(cycle=cycle, cost_usd=cost, session_id=sid,
                              error="missing or incomplete structured_output")

        self.log(f"cycle {cycle}: sdk done cost=${round(cost, 4)} "
                 f"sha={str(so.get('sha'))[:8]} tests={so.get('tests_pass')}")
        return DoneRecord(
            cycle=cycle,
            sha=str(so.get("sha") or ""),
            tests_pass=str(so.get("tests_pass", "?")),
            regressions=bool(so.get("regressions")),
            cost_usd=cost,
            session_id=sid,
            raw=dict(so),
        )


HOOK_NAMES = ("pre-commit", "commit-msg")


def gate_inactive_reason(repo_root) -> str | None:
    """Why the commit gate is not active, or None if it looks active.

    `core.hooksPath` is LOCAL config and is NOT cloned. A fresh clone therefore
    has the tracked `.githooks/` on disk and NO hooks running - the tracked dir
    buys nothing until someone runs `python scripts/install_hooks.py`. An
    unattended headless run in that state commits and pushes with no glyph /
    ruff / trailer gate at all, and nobody is watching a session-start report.
    So the loop refuses to start rather than run ungated: this is the one place
    where failing loud beats degrading quietly.

    HONEST LIMIT, per the CLAUDE.md hard rule: this is a PRESENCE check, and a
    hook's presence is never proof it fires. It catches the fresh-clone case
    (the one that actually bites) and nothing subtler. The end-to-end test -
    stage a banned glyph, attempt a real commit, assert HEAD unchanged - stays
    the only real proof and is not something a loop start can run.
    """
    root = Path(repo_root)
    if not (root / ".githooks").is_dir():
        return None  # not this repo's convention - do not invent a blocker
    try:
        r = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"],
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        return f"could not verify the commit gate: {e}"
    configured = (r.stdout or "").strip()
    if not configured:
        return "core.hooksPath is unset, so this clone runs ZERO git hooks"
    hooks = Path(configured)
    if not hooks.is_absolute():
        hooks = root / hooks
    if not hooks.is_dir():
        return f"core.hooksPath points at a missing directory: {hooks}"
    missing = [n for n in HOOK_NAMES if not (hooks / n).is_file()]
    if missing:
        return f"hooks missing from {hooks}: {', '.join(missing)}"
    return None


def build(cfg, ctl, **deps):
    """Return the executor the config selects. `channel` defaults to ahk.

    Unknown values fail LOUD rather than silently falling back: a typo in
    `channel` must not quietly run the legacy singleton channel during a
    concurrent run, which is exactly the failure this seam exists to prevent.
    """
    channel = str(cfg.get("channel", "ahk")).strip().lower()
    if channel == "ahk":
        return AhkExecutor(cfg, ctl, **deps)
    if channel == "sdk":
        return SdkExecutor(cfg, ctl, **deps)
    raise ValueError(
        f"unknown executor channel {channel!r} (known: 'ahk', 'sdk')")
