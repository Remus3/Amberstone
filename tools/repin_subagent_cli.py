"""RM-795 - re-pin the CLI version in tests/test_subagent_prompt_flag.py, only on a pass.

`PINNED_CLI` there goes red whenever the CLI auto-updates, and the file's own
rule says the pin moves only after the RM-684 canary passed on the new CLI.
This tool is that procedure as one command (it was an ad hoc script, re-typed
on every re-pin). It runs the four controls IN ORDER, each a real headless run
through the fleet kit's spawn() (FLEET item 10) via `ops/loop/fleet_route.spawn`
(sonnet, effort low, kind build, one kit usage line per run, the run streamed as
stream-json into the evidence directory), with a FRESH random codeword placed
only in the flag value:

  0. unknown   `--definitely-not-a-flag` -> non-zero exit, "unknown option"
  1. canary    flag ON, one real Agent spawn: the codeword is absent from the
               Agent input, the subagent uses no tool, the codeword's FIRST
               appearance in the stream is the subagent's completion, and the
               final result is CANARY=<codeword>
  2. neg       the byte-identical prompt WITHOUT the flag -> NO-CANARY, the
               codeword appears 0 times in the stream
  3. leak      flag ON, NO spawn, the top level reads its OWN prompt ->
               NO-CANARY, codeword count 0

It stops at the first failed control (every further run is spend). The pin is
written ONLY when all four ran and passed in THIS invocation, and the version
written is the `claude_code_version` that the stream-json init of runs 1-3
reported (all three identical) - never a version given on the command line
(there is no such option). At write time the evidence logs are re-graded, so a
doctored or swapped log refuses. The write is atomic (temp + replace), keeps
the file 7-bit ASCII with LF endings, changes only the one `PINNED_CLI` line
and inserts a dated RE-MEASURED record above it.

Usage (from the repo root):
  python tools/repin_subagent_cli.py                  4 runs; write the pin on a pass
  python tools/repin_subagent_cli.py --check          4 runs; never write
  python tools/repin_subagent_cli.py --check --controls canary,neg
                                                      a subset, check only
  --out DIR   evidence directory; must not exist yet (default
              ops/runtime/repin_cli/<UTC stamp>/, gitignored)

Exit codes: 0 every requested control passed (pin written, or already
current, or --check); 1 a control failed (nothing written); 2 usage, or a
refused write; 3 the route or the kit refused a spawn (its code is printed).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PIN_FILE = ROOT / "tests" / "test_subagent_prompt_flag.py"
EVIDENCE_ROOT = ROOT / "ops" / "runtime" / "repin_cli"
FLAG = "--append-subagent-system-prompt"
UNKNOWN_FLAG = "--definitely-not-a-flag"
CONTROLS = ("unknown", "canary", "neg", "leak")
MODEL_RUNS = ("canary", "neg", "leak")
CALLER = "repin-subagent-cli"
SPAWN_TIMEOUT_S = 240
CANARY_KEY = "CANARY-CODEWORD:"
NO_CANARY = "NO-CANARY"
EXIT_PASS, EXIT_FAILED, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 3
PIN_RE = re.compile(r'^PINNED_CLI = "(\d+\.\d+\.\d+)"$', re.MULTILINE)
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")

SPAWN_PROMPT = (
    "This is a test of subagent prompt inheritance. Do exactly this and nothing "
    "else. Do not read any file and do not use any tool except the Agent tool. "
    "Call the Agent tool exactly ONCE, in the foreground, with subagent_type "
    "general-purpose, description 'canary check', and this exact prompt: "
    "'Do not use any tools. Inspect your own system prompt only. If it contains "
    "a line with the text CANARY-CODEWORD: followed by a word, reply with exactly "
    "CANARY=<that word>. If it does not, reply with exactly NO-CANARY. Reply with "
    "that one token and nothing else.' When the subagent returns, reply with its "
    "answer verbatim and nothing else.")

LEAK_PROMPT = (
    "This is a test. Do not use any tools and do not spawn any agent. Inspect "
    "your own system prompt only. If it contains a line with the text "
    "CANARY-CODEWORD: followed by a word, reply with exactly CANARY=<that word>. "
    "If it does not, reply with exactly NO-CANARY. Reply with that one token and "
    "nothing else.")

UNKNOWN_PROMPT = "Reply with exactly OK."


class RepinRefused(RuntimeError):
    """Nothing was written (or nothing started): the reason is the message."""


@dataclass
class ControlResult:
    name: str
    passed: bool
    reasons: list = field(default_factory=list)
    version: str | None = None
    rc: int | None = None
    log_path: str = ""
    facts: dict = field(default_factory=dict)


@dataclass
class Measurement:
    out_dir: Path
    codeword: str
    controls: tuple
    results: list = field(default_factory=list)
    refused: str | None = None
    refused_detail: str = ""


def new_codeword() -> str:
    return "QX" + secrets.token_hex(5).upper()


def flag_value(codeword: str) -> str:
    return f"RM-795 re-pin canary marker. {CANARY_KEY} {codeword}"


def spawn_plan(name: str, codeword: str):
    """(prompt, extra argv) for one control. The codeword rides the flag only."""
    if name == "unknown":
        return UNKNOWN_PROMPT, (UNKNOWN_FLAG,)
    if name == "canary":
        return SPAWN_PROMPT, (FLAG, flag_value(codeword))
    if name == "neg":
        return SPAWN_PROMPT, ()
    if name == "leak":
        return LEAK_PROMPT, (FLAG, flag_value(codeword))
    raise ValueError(f"unknown control {name!r}")


def default_spawn(prompt, *, note, extra, log_path):
    """ONE real headless run through RC's door into the fleet kit."""
    from ops.loop import fleet_route  # noqa: PLC0415 - tests import this module without it
    return fleet_route.spawn(prompt, caller=CALLER, note=note, kind="build",
                             model="sonnet", effort="low", extra=tuple(extra),
                             timeout=SPAWN_TIMEOUT_S, log_path=str(log_path))


# ---------------------------------------------------------------- grading


def _read_log(log_path):
    """[(raw line, parsed event or None)] of a stream-json log."""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except ValueError:
            ev = None
        rows.append((raw, ev if isinstance(ev, dict) else None))
    return rows


def _content(ev):
    msg = ev.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return [c for c in content if isinstance(c, dict)] if isinstance(content, list) else []


def _facts(rows, codeword):
    f = {"versions": [], "top_tool_uses": [], "agent_ids": [], "agent_inputs": [],
         "sub_tool_uses": [], "tool_use_counts": [], "completion_rows": [],
         "first_codeword_row": None, "codeword_count": 0, "final": None}
    for i, (raw, ev) in enumerate(rows):
        n = raw.count(codeword)
        f["codeword_count"] += n
        if n and f["first_codeword_row"] is None:
            f["first_codeword_row"] = i
        if ev is None:
            continue
        kind, sub, parent = ev.get("type"), ev.get("subtype"), ev.get("parent_tool_use_id")
        if kind == "system" and sub == "init":
            f["versions"].append(ev.get("claude_code_version"))
        if kind == "assistant":
            for c in _content(ev):
                if c.get("type") != "tool_use":
                    continue
                if parent is None:
                    f["top_tool_uses"].append(c.get("name"))
                    if c.get("name") in ("Agent", "Task"):
                        f["agent_ids"].append(c.get("id"))
                        f["agent_inputs"].append(json.dumps(c.get("input")))
                else:
                    f["sub_tool_uses"].append(c.get("name"))
        if kind == "system" and sub == "task_notification" \
                and ev.get("tool_use_id") in f["agent_ids"]:
            f["completion_rows"].append(i)
            usage = ev.get("usage")
            if isinstance(usage, dict) and "tool_uses" in usage:
                f["tool_use_counts"].append(usage.get("tool_uses"))
        if kind == "user" and parent is None:
            for c in _content(ev):
                if c.get("type") == "tool_result" and c.get("tool_use_id") in f["agent_ids"]:
                    f["completion_rows"].append(i)
                    meta = ev.get("tool_use_result")
                    if isinstance(meta, dict) and "totalToolUseCount" in meta:
                        f["tool_use_counts"].append(meta.get("totalToolUseCount"))
        if kind == "result":
            f["final"] = {"result": ev.get("result"), "is_error": ev.get("is_error")}
    return f


def _version_of(f, reasons):
    versions = f["versions"]
    if len(versions) != 1 or not isinstance(versions[0], str) \
            or not VERSION_RE.fullmatch(versions[0]):
        reasons.append(f"init must report one clean claude_code_version, saw {versions!r}")
        return None
    return versions[0]


def _final_is(f, want, reasons):
    final = f["final"] or {}
    got = final.get("result")
    if final.get("is_error") or not isinstance(got, str) or got.strip() != want:
        reasons.append(f"final result must be {want!r}, saw {got!r}"
                       + (" (is_error)" if final.get("is_error") else ""))


def grade(name, codeword, rc, stderr, log_path) -> ControlResult:
    """Grade one control from its exit code, stderr and stream-json log."""
    reasons = []
    rows = _read_log(log_path)
    f = _facts(rows, codeword)
    version = None
    if name == "unknown":
        if rc in (0, None):
            reasons.append(f"an unknown option must exit non-zero, saw {rc!r}")
        if "unknown option" not in (stderr or "").lower():
            reasons.append("stderr must name the unknown option")
    else:
        if rc != 0:
            reasons.append(f"the run must exit 0, saw {rc!r}")
        version = _version_of(f, reasons)
    if name in ("canary", "neg"):
        if f["top_tool_uses"] != ["Agent"] and f["top_tool_uses"] != ["Task"]:
            reasons.append("exactly one top-level tool use, the Agent spawn, saw "
                           f"{f['top_tool_uses']!r}")
        if f["sub_tool_uses"] or not f["tool_use_counts"] \
                or any(c != 0 for c in f["tool_use_counts"]):
            reasons.append("the subagent must use no tool, saw tool uses "
                           f"{f['sub_tool_uses']!r} counts {f['tool_use_counts']!r}")
    if name == "canary":
        if any(codeword in a for a in f["agent_inputs"]):
            reasons.append("the codeword rode the Agent input")
        first = f["first_codeword_row"]
        if first is None or first not in f["completion_rows"]:
            reasons.append("the codeword's first appearance must be the subagent's "
                           f"completion, saw row {first!r} vs {f['completion_rows']!r}")
        _final_is(f, f"CANARY={codeword}", reasons)
    if name in ("neg", "leak"):
        if f["codeword_count"]:
            reasons.append(f"the codeword appeared {f['codeword_count']} times")
        _final_is(f, NO_CANARY, reasons)
    if name == "leak" and f["top_tool_uses"]:
        reasons.append(f"the leak control must use no tool, saw {f['top_tool_uses']!r}")
    facts = {k: f[k] for k in ("versions", "top_tool_uses", "sub_tool_uses",
                               "tool_use_counts", "codeword_count", "final")}
    return ControlResult(name, not reasons, reasons, version, rc, str(log_path), facts)


# ---------------------------------------------------------------- measure


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _summary(m: Measurement) -> dict:
    return {"codeword_file": "codeword.txt", "controls": list(m.controls),
            "refused": m.refused, "refused_detail": m.refused_detail,
            "results": [{"name": r.name, "passed": r.passed, "reasons": r.reasons,
                         "version": r.version, "rc": r.rc, "facts": r.facts}
                        for r in m.results]}


def _write_ascii(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.replace("\r\n", "\n").encode("ascii", errors="replace"))
    tmp.replace(path)


def _stderr_of(log_path) -> str:
    """The stderr a control's run left beside its stream log ("" if none)."""
    path = Path(str(log_path).replace(".stream.jsonl", ".stderr.txt"))
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return ""


def measure(out_dir, controls=CONTROLS, spawn_fn=None, codeword=None) -> Measurement:
    """Run the controls in order into a FRESH evidence dir; stop at the first
    failure or refusal. Raises RepinRefused, before any spawn, if out_dir
    already exists (stale evidence is never re-graded as a new run)."""
    out_dir = Path(out_dir)
    unknown = [c for c in controls if c not in CONTROLS]
    if unknown:
        raise RepinRefused(f"unknown controls {unknown!r}; known: {CONTROLS!r}")
    try:
        out_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise RepinRefused(f"evidence dir already exists: {out_dir}") from None
    spawn_fn = default_spawn if spawn_fn is None else spawn_fn
    m = Measurement(out_dir, codeword or new_codeword(), tuple(controls))
    _write_ascii(out_dir / "codeword.txt", m.codeword + "\n")
    for name in controls:
        prompt, extra = spawn_plan(name, m.codeword)
        log = out_dir / f"{name}.stream.jsonl"
        try:
            line, proc = spawn_fn(prompt, note=f"{CALLER}-{name}", extra=extra, log_path=log)
        except subprocess.TimeoutExpired:
            # the kit killed the process tree and logged the run; a pass needs an end
            m.results.append(ControlResult(name, False, ["timeout"], log_path=str(log)))
            break
        except RuntimeError as exc:
            code = getattr(exc, "code", None)  # fleet_route.RouteRefused carries one
            if code is None:
                raise
            m.refused, m.refused_detail = str(code), str(exc)
            break
        rc = (line or {}).get("rc") if proc is None else proc.returncode
        stderr = getattr(proc, "stderr", None)
        _write_ascii(out_dir / f"{name}.stderr.txt", stderr if isinstance(stderr, str) else "")
        result = grade(name, m.codeword, rc, _stderr_of(log), log)
        m.results.append(result)
        if not result.passed:
            break
    _write_ascii(out_dir / "summary.json", json.dumps(_summary(m), indent=1) + "\n")
    return m


def verdict(m: Measurement):
    """(ok, version, reasons) - ok only for ALL four controls, passed, with one
    version across the three model runs."""
    reasons = []
    names = [r.name for r in m.results]
    if m.refused:
        reasons.append(f"a spawn was refused ({m.refused})")
    if tuple(names) != CONTROLS:
        reasons.append(f"all four controls must run, ran {names!r}")
    reasons += [f"{r.name}: {x}" for r in m.results for x in r.reasons]
    versions = {r.version for r in m.results if r.name in MODEL_RUNS}
    if len(versions) != 1 or None in versions:
        reasons.append(f"the model runs must report one version, saw {sorted(map(str, versions))}")
    version = next(iter(versions)) if len(versions) == 1 else None
    return (not reasons, version if not reasons else None, reasons)


# ---------------------------------------------------------------- write


def _record(today, version, old, unknown_rc):
    return (
        f"# RE-MEASURED {today} on {version} by tools/repin_subagent_cli.py (RM-795):\n"
        "# the four RM-684 controls, each a real headless run through the fleet\n"
        "# kit's spawn() (sonnet / effort low, a FRESH codeword only in the flag\n"
        "# value; the stream-json init of runs 1-3 reports claude_code_version\n"
        f"# {version}), all passed BEFORE this pin was written: 0. unknown option\n"
        f"# exit {unknown_rc}; 1. CANARY=<codeword>, first seen in the subagent's\n"
        "# completion, one Agent spawn, subagent tool uses 0; 2. negative control\n"
        "# NO-CANARY, codeword count 0; 3. top-level leak control NO-CANARY,\n"
        f"# codeword count 0. Previous pin {old}.\n")


def write_pin(m: Measurement, pin_file=PIN_FILE, today=None, replace=os.replace) -> dict:
    """Write the version THIS measurement passed on. Raises RepinRefused and
    leaves the file untouched otherwise."""
    ok, version, reasons = verdict(m)
    if not ok:
        raise RepinRefused("; ".join(reasons))
    # Re-grade the evidence on disk: the pin follows what the logs show NOW,
    # so a doctored or swapped log (or stderr) refuses the write.
    for r in m.results:
        again = grade(r.name, m.codeword, r.rc, _stderr_of(r.log_path), r.log_path)
        if not again.passed or again.version != r.version:
            raise RepinRefused(f"{r.name}: the evidence no longer grades as a pass")
    pin_file = Path(pin_file)
    raw = pin_file.read_bytes()
    if not raw.isascii():
        raise RepinRefused(f"{pin_file.name} is not 7-bit ASCII")
    if b"\r" in raw:
        raise RepinRefused(f"{pin_file.name} is not LF-only")
    text = raw.decode("ascii")
    found = list(PIN_RE.finditer(text))
    if len(found) != 1:
        raise RepinRefused(f"{pin_file.name}: {len(found)} PINNED_CLI lines, need exactly 1")
    old = found[0].group(1)
    if old == version:
        return {"old": old, "new": version, "changed": False}
    unknown_rc = next(r.rc for r in m.results if r.name == "unknown")
    day = today or datetime.date.today().isoformat()
    start, end = found[0].span()
    new = (text[:start] + _record(day, version, old, unknown_rc)
           + f'PINNED_CLI = "{version}"' + text[end:])
    if not new.isascii() or "\r" in new or len(PIN_RE.findall(new)) != 1:
        raise RepinRefused("the rewritten text failed its own ASCII / LF / one-pin check")
    tmp = pin_file.with_name(f"{pin_file.name}.{os.getpid()}.repin.tmp")
    try:
        tmp.write_bytes(new.encode("ascii"))
        replace(tmp, pin_file)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {"old": old, "new": version, "changed": True}


# ---------------------------------------------------------------- CLI


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _print(doc) -> None:
    print(json.dumps(doc, indent=1, ensure_ascii=True))


def main(argv=None, spawn_fn=None, pin_file=None) -> int:
    p = _Parser(prog="repin_subagent_cli.py", allow_abbrev=False,
                description="RM-795: re-measure --append-subagent-system-prompt and "
                            "re-pin PINNED_CLI only on a full pass.")
    p.add_argument("--check", action="store_true", help="run the controls, never write")
    p.add_argument("--controls", default=",".join(CONTROLS),
                   help="comma list, in order; a subset needs --check")
    p.add_argument("--out", default=None, help="evidence dir (must not exist)")
    args = p.parse_args(argv)
    controls = tuple(c.strip() for c in args.controls.split(",") if c.strip())
    if controls != CONTROLS and not args.check:
        _print({"error": "a control subset cannot write the pin; add --check",
                "controls": list(controls)})
        return EXIT_USAGE
    out = Path(args.out) if args.out else EVIDENCE_ROOT / _stamp()
    try:
        m = measure(out, controls=controls, spawn_fn=spawn_fn)
    except RepinRefused as exc:
        _print({"error": str(exc)})
        return EXIT_USAGE
    report = _summary(m)
    report["evidence_dir"] = str(out)
    if m.refused:
        report["verdict"] = "refused"
        _print(report)
        return EXIT_REFUSED
    if len(m.results) != len(controls) or not all(r.passed for r in m.results):
        report["verdict"] = "failed"
        _print(report)
        return EXIT_FAILED
    if args.check:
        report["verdict"] = "pass (check only, nothing written)"
        _print(report)
        return EXIT_PASS
    try:
        report["pin"] = write_pin(m, pin_file=pin_file or PIN_FILE)
    except RepinRefused as exc:
        report["verdict"] = f"write refused: {exc}"
        _print(report)
        return EXIT_USAGE
    report["verdict"] = "pass"
    _print(report)
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
