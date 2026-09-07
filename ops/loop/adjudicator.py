#!/usr/bin/env python
"""The headless loop's external-brain call (the ADJUDICATOR).

The loop's director and auditor both ask ONE question of a read-only brain and
get back one text answer. This module is that call.

**One vendor, self-adjudicating (operator decision 2026-08-01).** The same
vendor that executes a cycle also directs and audits it. The read-only guarantee
comes from the CLI's own `--permission-mode plan` (paired with `-p/--print` for
a non-interactive one-shot), NOT from using a different vendor for the
adjudicating half. The adjudicator DIRECTS; the executor writes.

None (never "") is the failure sentinel: the director prompt mandates a
directive or the literal NO_WORK token and the auditor prompt mandates a VERDICT
line, so a completed-but-empty call is a swallowed CLI error, not an answer.

WHAT WAS REMOVED, so it is not rebuilt by someone reading a stale doc. Until
2026-08-01 this module carried a second, metered vendor plus the machinery a
second vendor needs: a backend registry, an exhaustion-signature matcher over
stderr, a sticky one-way failover, and a spend ceiling that governed one vendor
and had to explicitly EXCLUDE the other. None of that was adjudication; all of
it was vendor management. See `docs/CONCURRENT_HEADLESS_CONTRACT.md` section 9
for the reasoning, and do not re-add a second vendor for "independent review" -
independence comes from the producer not grading its own work, which is a
prompt-level property, not a vendor-level one.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# core/polled_json.py holds the repo's atomic-write contract - LANE 8 CYCLE 48,
# RM-250 sibling sweep. Plain import first so a repo-root process shares one
# module object; absolute-path bind as the fallback for the launcher context,
# where this module is loaded BY FILE PATH (loop_controller.py:41) and the repo
# root is not on sys.path.
try:
    from core.polled_json import atomic_write_bytes as _atomic_write_bytes
except ModuleNotFoundError:
    _pj_name = "rc_core_polled_json"
    if _pj_name in sys.modules:
        _atomic_write_bytes = sys.modules[_pj_name].atomic_write_bytes
    else:
        try:
            _pj_spec = importlib.util.spec_from_file_location(
                _pj_name,
                Path(__file__).resolve().parents[2] / "core" / "polled_json.py")
            _pj = importlib.util.module_from_spec(_pj_spec)
            sys.modules[_pj_name] = _pj
            _pj_spec.loader.exec_module(_pj)
        except OSError as _exc:
            sys.modules.pop(_pj_name, None)
            raise ModuleNotFoundError(
                "core/polled_json.py could not be loaded by absolute path"
            ) from _exc
        _atomic_write_bytes = _pj.atomic_write_bytes

# The Claude CLI shim really does live under an account-specific home, so there
# is no repo-relative answer for it (tests/test_loop_module_root_resolution.py
# records why this is deliberately outside that guard's scope). Resolve it under
# THIS account's roaming profile rather than baking one in: a command naming
# another account's home silently does not run, and an adjudicator that does not
# run reports nothing.
DEFAULT_CLAUDE_CMD = str(
    Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    / "npm" / "claude.cmd"
)
DEFAULT_CLAUDE_MODEL = "opus"
DEFAULT_CLAUDE_TIMEOUT_SEC = 300


def _atomic_write(path, text):
    """The control dir is polled by the operator and the bridge mid-write.

    LANE 8 CYCLE 48 (RM-250 sibling sweep). This carried the same three defects
    as the three writers RM-250 named: a BARE os.replace (so a poller holding
    the destination open raises WinError 5 on Windows), a scratch name derived
    from the DESTINATION alone (shared by every writer of that file), and
    Path.write_text (LF rewritten as CRLF). It escaped cycle 48's first pass
    because loop_controller.py:594 injects its own already-fixed `awrite` over
    this function - but that injection is an override, so the DEFAULT path any
    other caller takes was still the bare one. Delegating fixes the default.
    """
    _atomic_write_bytes(Path(path), text.encode("utf-8"))


def read_err(errfile):
    """Decode a PowerShell-redirected stderr file.

    PS 5.1 `2>'file'` writes the error stream UTF-16 LE (Out-File default); a
    utf-8 read mojibakes it, which once masked a real API error behind
    NUL-interleaved node warnings for a nine-hour outage. Kept after the vendor
    change because the redirect, and therefore the encoding trap, is identical
    on the claude path.
    """
    try:
        raw = Path(errfile).read_bytes()
    except OSError:
        return ""
    enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    return raw.decode(enc, errors="replace").strip()


def err_summary(txt, cap=400):
    # Surface the ERROR lines - the node/terminal warnings that open the stream
    # otherwise crowd them out of a head read.
    hits = [ln.strip() for ln in txt.splitlines()
            if any(k in ln.lower() for k in ("error", "unavailable", "exhausted", "quota", "429", "503"))]
    return (" | ".join(hits) if hits else txt)[:cap]


def model_price(table, model):
    """Per-Mtok price row for a claude model alias, mirroring the loop meter's
    opus/sonnet/haiku keying so one price table serves both.

    Estimated spend is a WORKLOAD-SIZE signal, never a budget. On a Max
    subscription the CLI's cost figure is a notional API-equivalent price, not
    money billed, which is why nothing in this module stops a run on it.
    """
    tbl = table or {}
    key = next((k for k in ("opus", "sonnet", "haiku") if k in (model or "").lower()), "default")
    return tbl.get(key) or tbl.get("default") or {"input": 15.0, "output": 75.0}


def _control_dir(cfg, ctl):
    if ctl is not None:
        return Path(ctl)
    return Path((cfg or {}).get("control_dir", Path(__file__).resolve().parent / "control"))


class ClaudeAdjudicator:
    """The local claude CLI as the loop's read-only external brain.

    Contract: `ask(prompt_body, instruction) -> str | None`.

    No key file and no metered account: the CLI authenticates from the
    operator's own session. The prompt body arrives on stdin rather than on the
    command line, so a multi-kilobyte prompt full of quotes and backslashes
    carries no quoting risk, and stderr is redirected to a file and decoded via
    `read_err` so a PowerShell 5.1 UTF-16 error stream is never mojibaked.
    """

    name = "claude"

    def __init__(self, cfg=None, ctl=None, log=None, awrite=None):
        self.cfg = cfg or {}
        self.ctl = _control_dir(cfg, ctl)
        self.log = log or (lambda _m: None)
        self.awrite = awrite or _atomic_write
        self.usd = 0.0
        # Decoded + error-line-filtered stderr of the LAST ask, so a caller can
        # report WHY a call came back empty without re-reading the file.
        self.last_stderr = ""

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


def resolve(cfg, log=None, ctl=None, awrite=None):
    """The adjudicator backend.

    There is one. The function survives the vendor removal because it is the
    controller's construction seam and every loop test binds to it, and because
    a call site reading `resolve(CFG)` states the intent - "give me the
    configured brain" - better than a bare constructor would.

    An `adjudicator` key naming anything other than claude is IGNORED rather
    than honoured, and says so in the log. Silently accepting a vendor name that
    no longer resolves is how a stale lane config quietly gets a brain nobody
    configured.
    """
    raw = str((cfg or {}).get("adjudicator", ClaudeAdjudicator.name)).strip().lower()
    if log and raw and raw != ClaudeAdjudicator.name:
        log(f"adjudicator '{raw}' in config is not available - "
            f"the loop is claude-only since 2026-08-01; using claude")
    return ClaudeAdjudicator(cfg, ctl, log, awrite)


class Adjudicator:
    """Thin state-carrying wrapper around one `ask`.

    It exists for ONE reason: `usd` accumulation has to survive the controller
    rebuilding this object on every call. The controller's CFG / CTL / log /
    awrite are module globals that the test suite and an operator hot-editing
    config.json both swap, so the object is rebuilt per call and the state is
    caller-owned.

    Until 2026-08-01 this class was `FailoverAdjudicator` and its real job was
    an automatic one-way vendor swap on credit exhaustion. With one vendor there
    is nothing to swap TO: a failover would replace claude with claude, log a
    misleading line, and stick for the rest of the run on a fault it did not
    fix. The swap is gone; only the accounting remains.
    """

    def __init__(self, cfg=None, ctl=None, log=None, awrite=None, state=None):
        self.cfg = cfg or {}
        self.ctl = _control_dir(cfg, ctl)
        self.log = log or (lambda _m: None)
        self.awrite = awrite or _atomic_write
        self.active_name = ClaudeAdjudicator.name
        self.usd = {}
        self.last_stderr = ""
        if state:
            self.load_state(state)

    def load_state(self, state):
        # Spend is accounting, not routing, and is restored unconditionally.
        self.usd = dict(state.get("usd") or {})
        return self

    def save_state(self, state):
        state["active"] = self.active_name
        state["usd"] = dict(self.usd)
        return state

    def total_usd(self):
        return sum(float(v or 0.0) for v in self.usd.values())

    def ask(self, prompt_body, instruction):
        b = resolve(self.cfg, self.log, self.ctl, self.awrite)
        b.usd = float(self.usd.get(b.name, 0.0))
        out = b.ask(prompt_body, instruction)
        self.usd[b.name] = b.usd
        self.last_stderr = b.last_stderr
        return out
