#!/usr/bin/env python
"""Pluggable external-brain backend for the headless loop (the ADJUDICATOR).

The loop's director and auditor both ask ONE question of an external, read-only
brain and get back one text answer. That vendor was hard-coded to the Gemini CLI.
This module is the seam: one contract, `ask(prompt_body, instruction) -> str|None`,
with a Gemini backend (today's live default, lifted verbatim) and a local Claude
CLI backend, plus a supervisor that swaps to the fallback automatically the moment
the metered vendor reports credit / quota exhaustion.

None (never "") is the failure sentinel: the director prompt mandates a directive
or the literal NO_WORK token and the auditor prompt mandates a VERDICT line, so a
completed-but-empty call is a swallowed CLI/API error, not an answer.

Read-only is a hard requirement for both backends - the adjudicator DIRECTS, the
executor writes. Gemini gets that from `--approval-mode plan`; the claude CLI's
documented equivalent is `--permission-mode plan` (choices include "plan"),
paired with `-p/--print` for a non-interactive one-shot run.
"""
import os
import subprocess
import time
from pathlib import Path

DEFAULT_CLAUDE_CMD = r"C:\Users\Administrator\AppData\Roaming\npm\claude.cmd"
DEFAULT_CLAUDE_MODEL = "opus"
DEFAULT_CLAUDE_TIMEOUT_SEC = 300

# Ordered most-specific first so the logged failover reason names the real cause
# rather than a substring of it. Matched case-insensitively against the captured
# stderr. Deliberately EXCLUDES 503 / UNAVAILABLE / overload: a transient
# capacity rejection is what the in-backend retry ladder and the cheaper
# fallback model already handle, and swapping vendors on it would abandon the
# metered brain for the rest of a run over a blip.
EXHAUSTION_SIGNATURES = (
    "resource_exhausted",
    "insufficient credit",
    "out of credit",
    "top up",
    "billing",
    "quota",
    "exhausted",
    "429",
)


def _atomic_write(path, text):
    """The control dir is polled by the AHK bridge and the operator mid-write."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_err(errfile):
    # PS 5.1 `2>'file'` writes the error stream UTF-16 LE (Out-File default);
    # a utf-8 read mojibakes it, which masked the real API error behind
    # NUL-interleaved node warnings for the whole 2026-07-02 01:56-11:17 outage.
    try:
        raw = Path(errfile).read_bytes()
    except OSError:
        return ""
    enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    return raw.decode(enc, errors="replace").strip()


def err_summary(txt, cap=400):
    # Surface the ERROR lines (503 overload / 429 quota) - the node/terminal
    # warnings that open the stream otherwise crowd them out of a head read.
    hits = [ln.strip() for ln in txt.splitlines()
            if any(k in ln.lower() for k in ("error", "unavailable", "exhausted", "quota", "429", "503"))]
    return (" | ".join(hits) if hits else txt)[:cap]


def match_exhaustion(text):
    """The matched credit/quota-exhaustion signature, or None.

    None for a transient overload (503) so a capacity blip never burns the
    one-way failover.
    """
    low = (text or "").lower()
    for sig in EXHAUSTION_SIGNATURES:
        if sig in low:
            return sig
    return None


def model_price(table, model):
    """Per-Mtok price row for a claude model alias, mirroring the loop meter's
    opus/sonnet/haiku keying so one price table serves both."""
    tbl = table or {}
    key = next((k for k in ("opus", "sonnet", "haiku") if k in (model or "").lower()), "default")
    return tbl.get(key) or tbl.get("default") or {"input": 15.0, "output": 75.0}


def _control_dir(cfg, ctl):
    if ctl is not None:
        return Path(ctl)
    return Path((cfg or {}).get("control_dir", Path(__file__).resolve().parent / "control"))


class _Backend:
    """Contract: ask(prompt_body, instruction) -> str | None."""

    name = "backend"

    def __init__(self, cfg=None, ctl=None, log=None, awrite=None):
        self.cfg = cfg or {}
        self.ctl = _control_dir(cfg, ctl)
        self.log = log or (lambda _m: None)
        self.awrite = awrite or _atomic_write
        self.usd = 0.0
        # The decoded + error-line-filtered stderr of the LAST ask, so the
        # supervisor can classify a failure without re-reading the file.
        self.last_stderr = ""

    def ask(self, prompt_body, instruction):
        raise NotImplementedError


class GeminiAdjudicator(_Backend):
    """The live default. The PowerShell invocation, the 3+2 model retry ladder,
    the escalating sleep and the UTF-16 stderr decode are lifted verbatim from
    the pre-seam loop_controller.gemini() - this backend must stay byte-for-byte
    what runs today."""

    name = "gemini"

    def ask(self, prompt_body, instruction):
        infile = self.ctl / "_gemini_in.txt"
        errfile = self.ctl / "_gemini_err.txt"
        self.awrite(infile, prompt_body)
        model = self.cfg.get("gemini_model", "gemini-3-pro-preview")
        # 2026-07-02 outage fix: gemini-3-pro-preview 503-overloads for hours at
        # a time (big prompts rejected, small ones admitted); 3 empty tries then
        # advancing burned 92 directive-less cycles. After the primary tries
        # exhaust, retry on the cheaper fallback model - a flash directive beats
        # an empty cycle.
        fallback = self.cfg.get("gemini_fallback_model", "gemini-2.5-flash")
        attempts = [model] * 3 + ([fallback] * 2 if fallback and fallback != model else [])
        inst = instruction.replace("'", "''")
        out = ""
        self.last_stderr = ""
        for tryn, m in enumerate(attempts, start=1):
            ps = ("$ErrorActionPreference='Continue';"
                  "$env:GEMINI_API_KEY=[Environment]::GetEnvironmentVariable('GEMINI_API_KEY','User');"
                  f"Get-Content -Raw '{infile}' | "
                  f"{self.cfg.get('gemini_cmd', 'gemini')} -p '{inst}' -m '{m}' --approval-mode plan --skip-trust 2>'{errfile}' | Out-String")
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                                   capture_output=True, text=True, timeout=300,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                out = (r.stdout or "").strip()
            except Exception as e:  # noqa: BLE001
                out = ""
                self.log(f"gemini try {tryn} ({m}) error: {e}")
            if out:
                break
            # Empty stdout: surface WHY (decoded + error-line filtered stderr).
            err = err_summary(read_err(errfile))
            if err:
                self.last_stderr = err
                self.log(f"gemini try {tryn} ({m}) empty stdout; stderr: {err}")
            time.sleep(8 * tryn)
        gp = self.cfg.get("gemini_price_per_mtok", {"input": 2.0, "output": 12.0})
        self.usd += (len(prompt_body) / 4 * gp["input"] + len(out) / 4 * gp["output"]) / 1_000_000
        if not out:
            return None
        return out


class ClaudeAdjudicator(_Backend):
    """The local claude CLI as the external brain - no metered vendor, no key.

    `--permission-mode plan` is the documented read-only equivalent of gemini's
    `--approval-mode plan`; `-p/--print` makes it a non-interactive one-shot that
    prints and exits. The prompt body arrives on stdin exactly like the gemini
    path, and stderr is redirected to a file and decoded the same way so a
    PowerShell 5.1 UTF-16 error stream is never mojibaked.
    """

    name = "claude"

    def ask(self, prompt_body, instruction):
        infile = self.ctl / "_claude_in.txt"
        errfile = self.ctl / "_claude_err.txt"
        self.awrite(infile, prompt_body)
        blk = self.cfg.get("claude_adjudicator") or {}
        cmd = blk.get("cmd") or DEFAULT_CLAUDE_CMD
        model = blk.get("model") or DEFAULT_CLAUDE_MODEL
        timeout = int(blk.get("timeout_sec") or DEFAULT_CLAUDE_TIMEOUT_SEC)
        inst = instruction.replace("'", "''")
        self.last_stderr = ""
        out = ""
        ps = ("$ErrorActionPreference='Continue';"
              f"Get-Content -Raw '{infile}' | "
              f"& '{cmd}' -p '{inst}' --model '{model}' --permission-mode plan "
              f"--output-format text 2>'{errfile}' | Out-String")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                               capture_output=True, text=True, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = (r.stdout or "").strip()
        except Exception as e:  # noqa: BLE001
            out = ""
            self.log(f"claude adjudicator ({model}) error: {e}")
        if not out:
            err = err_summary(read_err(errfile))
            if err:
                self.last_stderr = err
                self.log(f"claude adjudicator ({model}) empty stdout; stderr: {err}")
        p = model_price(self.cfg.get("price_per_mtok"), model)
        self.usd += (len(prompt_body) / 4 * p["input"] + len(out) / 4 * p["output"]) / 1_000_000
        if not out:
            return None
        return out


BACKENDS = {GeminiAdjudicator.name: GeminiAdjudicator,
            ClaudeAdjudicator.name: ClaudeAdjudicator}

# CLAUDE IS THE DEFAULT AND THE ONLY VENDOR THE LOOP IS MEANT TO USE
# (operator decision 2026-08-01). The loop self-adjudicates: the same vendor
# that executes a cycle also directs and audits it, with the read-only
# guarantee coming from `--permission-mode plan` rather than from vendor
# diversity.
#
# WHY THE GEMINI BACKEND IS STILL IN THIS FILE. Flipping the default is a
# one-line, instantly reversible change; deleting the backend is a decommission
# sweep across the controller's stdin cap, the ceiling accounting, the failover
# ladder, a scheduled task and a shared-by-contract mutex name that cannot be
# edited unilaterally. Those are separate acts and the second one is filed, not
# forgotten. Leaving a reachable-but-unselected backend here is deliberate: it
# is what makes this flip reversible while the sweep is planned.
#
# The practical point of the change is that a second vendor cost real overhead
# for no adjudication benefit - quota checks, exhaustion-signature matching, a
# sticky failover that could misread a parallel-call RESOURCE_EXHAUSTED as
# genuine credit exhaustion, a metered-spend ceiling, and a CLI stdin limit the
# controller had to cap every call against.
DEFAULT_BACKEND = ClaudeAdjudicator.name


def backend_name(cfg):
    """The configured backend name, defaulting to gemini for absent / unknown."""
    name = str((cfg or {}).get("adjudicator", DEFAULT_BACKEND)).strip().lower()
    return name if name in BACKENDS else DEFAULT_BACKEND


def make_backend(name, cfg=None, ctl=None, log=None, awrite=None):
    cls = BACKENDS.get(str(name).strip().lower(), BACKENDS[DEFAULT_BACKEND])
    return cls(cfg, ctl, log, awrite)


def resolve(cfg, log=None, ctl=None, awrite=None):
    """The active backend named by cfg['adjudicator'] ('gemini' | 'claude')."""
    name = backend_name(cfg)
    raw = str((cfg or {}).get("adjudicator", DEFAULT_BACKEND)).strip().lower()
    if log and raw and raw != name:
        log(f"unknown adjudicator '{raw}' in config - falling back to {name}")
    return make_backend(name, cfg, ctl, log, awrite)


def ceiling_spend(cfg, usd_by_name):
    """Adjudicator spend measured against cfg ceiling_usd.

    claude_adjudicator.count_against_ceiling defaults to FALSE on purpose:
    ceiling_usd is a runaway rail on the METERED vendor (gemini), and operator
    policy is that Claude spend is uncapped. A swap to the local claude
    adjudicator must not inherit the gemini rail and then silently stop an
    otherwise-free run the moment the estimate crosses it.
    """
    count_claude = bool(((cfg or {}).get("claude_adjudicator") or {}).get("count_against_ceiling", False))
    total = 0.0
    for name, usd in (usd_by_name or {}).items():
        if name == ClaudeAdjudicator.name and not count_claude:
            continue
        total += float(usd or 0.0)
    return total


class FailoverAdjudicator:
    """Supervising wrapper: one ask, plus an automatic one-way vendor swap.

    When the active backend returns the None sentinel AND its captured stderr
    carries a credit/quota-exhaustion signature, this logs a loud single line,
    records the new backend in control/adjudicator_active.txt (atomically, so a
    controller restart and a glancing operator both see it), immediately RETRIES
    the same call on the fallback so the cycle is not lost, and stays sticky on
    the fallback for the rest of the run.
    """

    def __init__(self, cfg=None, ctl=None, log=None, awrite=None, state=None):
        self.cfg = cfg or {}
        self.ctl = _control_dir(cfg, ctl)
        self.log = log or (lambda _m: None)
        self.awrite = awrite or _atomic_write
        self.primary_name = backend_name(self.cfg)
        # WHY the code default is empty rather than "claude": a loop relaunched
        # against a PRE-SEAM config.json (no adjudicator keys at all) must behave
        # EXACTLY as it does today, and silently changing vendor on a 429 is not
        # "exactly". The shipped config.json carries "adjudicator_fallback":
        # "claude", so the capability is armed for every real launch and stays
        # opt-in for an old config or an ad-hoc lane config.
        self.fallback_name = str(self.cfg.get("adjudicator_fallback", "")).strip().lower()
        self.active_name = self.primary_name
        self.failed_over = False
        self.usd = {}
        self.last_stderr = ""
        if state:
            self.load_state(state)

    # -- state is caller-owned so the controller can rebuild this object per
    # -- call (CFG / CTL / log / awrite are module-scope and monkeypatched)
    # -- without ever resetting the sticky decision or the accumulated spend.
    def failover_armed(self):
        """True when the CURRENT cfg both enables failover and names a fallback
        backend that actually resolves."""
        return (bool(self.cfg.get("adjudicator_failover", True))
                and self.fallback_name in BACKENDS)

    def load_state(self, state):
        # Spend is accounting, not routing: it is restored unconditionally so the
        # ceiling never loses sight of money already spent.
        self.usd = dict(state.get("usd") or {})
        # WHY the arming gate: a sticky failover decision is honoured only while
        # the CURRENT cfg still arms failover. Without it, a decision taken under
        # one config routes a later call whose config never authorized that
        # backend - and because the fallback is then asked instead of the
        # primary, the gemini 3+2 retry ladder silently stops running (that
        # ladder is the 2026-07-02 9-hour-outage guard). Production cfg is fixed
        # for a whole run, so this gate is a no-op for every real launch.
        active = str(state.get("active") or "").strip().lower()
        if active in BACKENDS and self.failover_armed():
            self.active_name = active
            self.failed_over = bool(state.get("failed_over"))
        return self

    def save_state(self, state):
        state["active"] = self.active_name
        state["failed_over"] = self.failed_over
        state["usd"] = dict(self.usd)
        return state

    def total_usd(self):
        return sum(float(v or 0.0) for v in self.usd.values())

    def _backend(self, name):
        b = make_backend(name, self.cfg, self.ctl, self.log, self.awrite)
        b.usd = float(self.usd.get(b.name, 0.0))
        return b

    def _failover_reason(self, backend):
        if self.failed_over:
            return None
        if not self.failover_armed() or self.fallback_name == backend.name:
            return None
        return match_exhaustion(backend.last_stderr)

    def ask(self, prompt_body, instruction):
        b = self._backend(self.active_name)
        out = b.ask(prompt_body, instruction)
        self.usd[b.name] = b.usd
        self.last_stderr = b.last_stderr
        if out is not None:
            return out
        reason = self._failover_reason(b)
        if reason is None:
            return None
        fb = self._backend(self.fallback_name)
        self.log(f"ADJUDICATOR FAILOVER: {b.name} -> {fb.name} (reason: {reason})")
        self.awrite(self.ctl / "adjudicator_active.txt", fb.name + "\n")
        self.active_name = fb.name
        self.failed_over = True
        out = fb.ask(prompt_body, instruction)
        self.usd[fb.name] = fb.usd
        self.last_stderr = fb.last_stderr
        return out
