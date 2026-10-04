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
import json
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


def _fleet_route_module():
    """`ops/loop/fleet_route.py`, by package import or by file path.

    Same two-step bind as core/polled_json above. Resolved per call so a
    test's monkeypatch of the package module is the one used.
    """
    try:
        from ops.loop import fleet_route as mod
        return mod
    except ModuleNotFoundError:
        name = "rc_ops_loop_fleet_route"
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                name, Path(__file__).resolve().parent / "fleet_route.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        return sys.modules[name]

# The CLI binary is resolved by the fleet kit (`claude_exe`), not here: the
# `cmd` key of the `claude_adjudicator` config block is no longer read.
# RM-511: the kit runs this call on sonnet (writes_code=False), and the model
# here only prices the workload signal when the kit's usage line carries none,
# so the default names that tier as a current exact id.
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"
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


def _answer_of(stdout):
    """`(answer, error)` from the kit's `--output-format json` stdout.

    The kit always asks for JSON. A result record flagged `is_error` is an
    error, never an answer - returning its text would hand the controller an
    API error as a directive. Stdout that is not a JSON object is passed
    through as the answer, so a CLI that ignored the flag still answers.

    (The PowerShell `2>file` UTF-16 decoder that lived here went with the
    PowerShell wrapper: the kit captures stderr in-process as UTF-8.)
    """
    text = (stdout or "").strip()
    try:
        body = json.loads(text)
    except ValueError:
        return text, ""
    if not isinstance(body, dict):
        return text, ""
    result = body.get("result")
    result = result.strip() if isinstance(result, str) else ""
    if body.get("is_error"):
        return "", result or "is_error"
    return result, ""


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
        # The body is still written to the control dir: it is the audit copy of
        # what the brain was asked, read by the operator and the bridge.
        infile = self.ctl / "_claude_in.txt"
        self.awrite(infile, prompt_body)
        blk = self.cfg.get("claude_adjudicator") or {}
        # FLEET-KIT-v1: the kit picks the model (sonnet - this call writes no
        # code), so the configured model only prices the workload signal.
        model = blk.get("model") or DEFAULT_CLAUDE_MODEL
        timeout = int(blk.get("timeout_sec") or DEFAULT_CLAUDE_TIMEOUT_SEC)
        self.last_stderr = ""
        out = ""
        err = ""
        # FLEET-KIT-v1 (MAIN order 2026-10-03): the ONLY path that starts
        # `claude`. It fails closed - a refused route is no call at all, an
        # empty answer the controller already treats as "no adjudication this
        # time". Read-only: `--permission-mode plan`. The body rides stdin, never
        # the command line. bare=False: the director needs CLAUDE.md
        # auto-discovery, which --bare turns off.
        fr = _fleet_route_module()
        try:
            line, proc = fr.spawn(instruction, caller="loop_adjudicator", note="adjudicate",
                                  writes_code=False, bare=False,
                                  extra=["--permission-mode", "plan"],
                                  stdin=prompt_body, timeout=timeout)
        except fr.RouteRefused as exc:
            self.last_stderr = str(exc)
            self.log(f"claude adjudicator ({model}) spawn refused: {exc}")
            return None
        except Exception as e:  # noqa: BLE001
            line, proc = {}, None
            self.log(f"claude adjudicator ({model}) error: {e}")
        if proc is not None:
            out, err = _answer_of(proc.stdout or "")
            err = err or (proc.stderr or "")
        model = line.get("model") or model
        if not out:
            err = err_summary(err.strip())
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
