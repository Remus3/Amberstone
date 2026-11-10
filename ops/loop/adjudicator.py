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
import math
import os
import sys
from collections.abc import Mapping
from pathlib import Path

# core/polled_json.py holds the repo's atomic-write contract - LANE 8 CYCLE 48,
# RM-250 sibling sweep. Plain import first so a repo-root process shares one
# module object; absolute-path bind as the fallback for the launcher context,
# where this module is loaded BY FILE PATH (loop_controller.py's _ADJ_MODNAME
# spec_from_file_location bind) and the repo root is not on sys.path.
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
# The last-resort price row when the configured table offers no usable one.
_FALLBACK_PRICE = {"input": 15.0, "output": 75.0}
# One adjudicator call longer than a day is a config typo, not a timeout.
_MAX_TIMEOUT_SEC = 86400
# A notional spend above this is junk, not a measurement; the ceiling also
# keeps a SUM of accepted entries finite (two 1.5e308 entries add up to inf).
_MAX_USD = 1e12


def _usd_ok(value):
    """`value` as a recordable spend (finite, 0..._MAX_USD), or None."""
    num = _finite_nonneg(value)
    return num if num is not None and num <= _MAX_USD else None

# S144-T-720. loop_controller.main() calls director() / auditor() with no try
# around them, so anything ask() raises ends the whole run. Every value below
# comes from a hot-editable config.json, a restored state dict or the kit's
# output, so each is read through a gate that answers a usable value or a
# default - never an exception, and never nan / inf into the spend signal.


def _finite_nonneg(value):
    """`value` as a finite float >= 0, or None. A bool is not a number here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        num = float(value)
    except OverflowError:
        return None
    return num if math.isfinite(num) and num >= 0.0 else None


def _timeout_of(raw, log):
    """A positive whole-second timeout from config, else the default.

    Accepts an int, a finite float or a decimal-digit string ("300", " 60 "),
    the shapes a hand-edited config.json carries. Anything else - "300s", a
    bool, inf / nan, zero, a negative, more than a day (a 1e300 timeout
    overflows the kit's wait), a list - is logged and replaced by the
    default rather than raised (int("300s") used to end the loop run) or handed
    to the kit as a timeout it cannot honour.
    """
    if raw is None or raw == "":
        return DEFAULT_CLAUDE_TIMEOUT_SEC
    value = None
    digits = raw.strip() if isinstance(raw, str) else ""
    if digits.isascii() and digits.isdigit():
        # Length first: int() refuses a digit string past 4300 characters
        # with ValueError, and anything past 9 digits is over the ceiling.
        value = int(digits) if len(digits) <= 9 else _MAX_TIMEOUT_SEC + 1
    else:
        num = _finite_nonneg(raw)
        if num is not None:
            value = int(num)
    if value is None or value <= 0 or value > _MAX_TIMEOUT_SEC:
        try:
            shown = repr(raw[:60] if isinstance(raw, str) else raw)[:60]
        except ValueError:  # repr of an int past 4300 digits refuses
            shown = f"<{type(raw).__name__}>"
        log(f"claude_adjudicator timeout_sec {shown} is not a number of "
            f"seconds in 1..{_MAX_TIMEOUT_SEC} - using {DEFAULT_CLAUDE_TIMEOUT_SEC}")
        return DEFAULT_CLAUDE_TIMEOUT_SEC
    return value


def _exc_text(exc):
    """`str(exc)` capped at 400, or `<TypeName>` when str() itself raises
    (an exception carrying an int past 4300 digits, a broken __str__)."""
    try:
        return str(exc)[:400]
    except Exception:  # noqa: BLE001 - any failure of a foreign __str__
        return f"<{type(exc).__name__}>"


def _clean_usd_map(raw):
    """A restored spend map keeping only str keys with values in 0..._MAX_USD.

    The map is caller-owned state (loop_controller's _ADJ_STATE, seeded from
    budget.json after a self-restart), so a wrong shape or a junk value is
    dropped here instead of raising in the constructor or turning every later
    total into nan / inf.
    """
    if not isinstance(raw, Mapping):
        return {}
    out = {}
    for key, val in raw.items():
        num = _usd_ok(val)
        if isinstance(key, str) and num is not None:
            out[key] = num
    return out


def _atomic_write(path, text):
    """The control dir is polled by the operator and the bridge mid-write.

    LANE 8 CYCLE 48 (RM-250 sibling sweep). This carried the same three defects
    as the three writers RM-250 named: a BARE os.replace (so a poller holding
    the destination open raises WinError 5 on Windows), a scratch name derived
    from the DESTINATION alone (shared by every writer of that file), and
    Path.write_text (LF rewritten as CRLF). It escaped cycle 48's first pass
    because loop_controller.py _supervisor() injects its own already-fixed
    `awrite` over this function - but that injection is an override, so the
    DEFAULT path any other caller takes was still the bare one. Delegating
    fixes the default.
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
    except (ValueError, RecursionError):
        # RecursionError: a deeply nested stdout overflows the decoder; it is
        # no result object either, so it passes through like any non-JSON.
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

    A row is usable only when it is a mapping whose `input` and `output` are
    finite numbers >= 0; an unusable model row falls back to `default`, then to
    the built-in row (S144-T-720: a row missing `output` used to raise KeyError
    AFTER the call was answered, losing the answer, and a nan price made the
    restored spend nan for the rest of the run).
    """
    tbl = table if isinstance(table, Mapping) else {}
    name = model.lower() if isinstance(model, str) else ""
    key = next((k for k in ("opus", "sonnet", "haiku") if k in name), "default")
    for row in (tbl.get(key), tbl.get("default")):
        if (isinstance(row, Mapping) and _finite_nonneg(row.get("input")) is not None
                and _finite_nonneg(row.get("output")) is not None):
            return row
    return dict(_FALLBACK_PRICE)


def _control_dir(cfg, ctl):
    """An explicit ctl wins; else `control_dir` by loop_controller's own rule
    (CTL = _cfg_path("control_dir", _HERE / "control")): an ABSOLUTE value is a
    per-host override, absent / empty / relative is ops/loop/control - never a
    path relative to the process CWD. The tracked config carries no
    control_dir since the 2026-10-09 leak removal (MAIN 2246 sec 3). A value
    that is not a path (a number, a list) is treated as absent (S144-T-720)."""
    if ctl is not None:
        return Path(ctl)
    raw = cfg.get("control_dir") if isinstance(cfg, Mapping) else None
    if isinstance(raw, os.PathLike):
        raw = os.fspath(raw)
    # A NUL makes every later path call raise ValueError, not OSError.
    p = Path(raw) if raw and isinstance(raw, str) and "\x00" not in raw else None
    return p if p is not None and p.is_absolute() else Path(__file__).resolve().parent / "control"


class ClaudeAdjudicator:
    """The local claude CLI as the loop's read-only external brain.

    Contract: `ask(prompt_body, instruction) -> str | None`.

    No key file and no metered account: the CLI authenticates from the
    operator's own session. The prompt body arrives on stdin rather than on the
    command line, so a multi-kilobyte prompt full of quotes and backslashes
    carries no quoting risk. The fleet kit starts the child and captures its
    stderr in-process as UTF-8; the error lines of that stream land in
    `last_stderr` and the log when the answer is empty. (The `read_err` UTF-16
    decoder this docstring used to name went with the PowerShell wrapper.)

    Contract hardened by S144-T-720: `ask` answers a string or None and never
    raises on a junk config value, a junk price row, a junk kit usage line or a
    failed audit-copy write.
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
        # The copy is not the call's input (the body rides stdin), so a failed
        # write - a reader holding the file past polled_json's bounded retry -
        # is logged and the call still runs (S144-T-720). OSError plus
        # ValueError: a path Windows refuses (NUL, past its length limit) and
        # a body that will not encode raise ValueError, not OSError. Anything
        # else - a TypeError bug in an injected writer - still surfaces.
        infile = self.ctl / "_claude_in.txt"
        try:
            self.awrite(infile, prompt_body)
        except (OSError, ValueError) as exc:
            self.log(f"claude adjudicator: audit copy {infile.name} not written "
                     f"({type(exc).__name__}: {_exc_text(exc)}); asking anyway")
        blk = self.cfg.get("claude_adjudicator")
        blk = blk if isinstance(blk, Mapping) else {}
        # FLEET-KIT-v1: the kit picks the model (sonnet - this call writes no
        # code), so the configured model only prices the workload signal.
        model = blk.get("model")
        model = model if isinstance(model, str) and model else DEFAULT_CLAUDE_MODEL
        timeout = _timeout_of(blk.get("timeout_sec"), self.log)
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
            self.last_stderr = _exc_text(exc)
            self.log(f"claude adjudicator ({model}) spawn refused: {self.last_stderr}")
            return None
        except Exception as e:  # noqa: BLE001
            line, proc = {}, None
            # last_stderr is the caller's only record of WHY the call came back
            # empty; a raised spawn used to leave it "" (S144-T-720).
            text = _exc_text(e)
            self.last_stderr = f"spawn error: {type(e).__name__}: {text}"[:400]
            self.log(f"claude adjudicator ({model}) error: {text}")
        if proc is not None:
            # The kit runs the child in text mode; anything else is no text.
            stdout = getattr(proc, "stdout", None)
            stderr = getattr(proc, "stderr", None)
            out, err = _answer_of(stdout if isinstance(stdout, str) else "")
            err = err or (stderr if isinstance(stderr, str) else "")
        # The usage line is the kit's; a non-mapping one or a non-string model
        # used to raise here, after the answer was already in hand.
        used = line.get("model") if isinstance(line, Mapping) else None
        model = used if isinstance(used, str) and used else model
        if not out:
            err = err_summary(err.strip())
            if err:
                self.last_stderr = err
                self.log(f"claude adjudicator ({model}) empty stdout; stderr: {err}")
        p = model_price(self.cfg.get("price_per_mtok"), model)
        # A finite but absurd price (1e308) still overflows the product to inf;
        # a spend that is not finite is not recorded (S144-T-720).
        base = _usd_ok(self.usd) or 0.0
        total = base + (len(prompt_body) / 4 * float(p["input"])
                            + len(out) / 4 * float(p["output"])) / 1_000_000
        if _usd_ok(total) is not None:
            self.usd = total
        else:
            self.usd = base  # never leave a junk attribute value in place
            self.log(f"claude adjudicator ({model}): spend estimate is not finite "
                     f"- price_per_mtok row unusable; spend not recorded")
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
    # A non-string value is named by its type, never str()-ed (an int past
    # 4300 digits refuses), and None reads as unset (S144-T-720).
    val = cfg.get("adjudicator") if isinstance(cfg, Mapping) else None
    raw = (val.strip().lower() if isinstance(val, str)
           else "" if val is None else f"<{type(val).__name__}>")
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
        # Spend is accounting, not routing, and is restored unconditionally -
        # but only its usable entries (S144-T-720: a wrong-shape state raised
        # in this constructor, and a nan / inf entry poisoned every total).
        raw = state.get("usd") if isinstance(state, Mapping) else None
        self.usd = _clean_usd_map(raw)
        return self

    def save_state(self, state):
        state["active"] = self.active_name
        state["usd"] = dict(self.usd)
        return state

    def total_usd(self):
        # `usd` is a public attribute; a junk value set after load is skipped.
        return sum(_clean_usd_map(self.usd).values())

    def ask(self, prompt_body, instruction):
        b = resolve(self.cfg, self.log, self.ctl, self.awrite)
        usd = _clean_usd_map(self.usd)
        b.usd = usd.get(b.name, 0.0)
        out = b.ask(prompt_body, instruction)
        if _usd_ok(b.usd) is not None:
            usd[b.name] = float(b.usd)
        self.usd = usd
        self.last_stderr = b.last_stderr
        return out
