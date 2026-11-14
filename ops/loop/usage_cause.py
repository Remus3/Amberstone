"""The rc-not-0-but-success cause line for a headless run's usage row (MAIN ORDER
2026-11-14 0930 section 3, Fleet Insights W46: 19 of 22 failed rows read only "rc 1").

When a child exits with a non-zero rc while its claude result says subtype "success",
cause() names the first line of the final result text and the last tool the run used:
  rc-cause: rc 1 with result subtype success; result: <first line>; last tool: <name>
The kit's usage writer (ops/fleet_kit/fleet_headless, vendored and byte-pinned) is never
edited. Since kit v27 a failed run's usage "error" field is the tail of the child's
stderr (fleet_headless.stderr_tail, the last 20 non-empty lines), so annotate() appends
the cause as ONE line to the CompletedProcess's stderr inside RC's own `run` seam
(ops/loop/fleet_route.spawn), before the kit builds the row. The run's outcome, rc and
result are untouched.

LAST TOOL. A stream-json run (fleet_route spawn log_path=) records every tool_use, so the
last one is read from the log. The default json output carries only the final result
record, which names a tool only in "permission_denials"; with neither, the line says
"unknown (json result names no tool)".

Stdlib only, ASCII only; loaded by fleet_route by file path or as ops.loop.usage_cause.
"""
from __future__ import annotations

import json
from pathlib import Path

PREFIX = "rc-cause"
LINE_CAP = 200
NO_TOOL = "unknown (json result names no tool)"


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def first_line(text) -> str:
    if not isinstance(text, str):
        return ""
    for ln in text.splitlines():
        if ln.strip():
            return _ascii(" ".join(ln.split()))[:LINE_CAP]
    return ""


def parse_result(stdout):
    """The claude result record from a json-mode stdout: a dict, or the last
    {"type": "result"} entry of a list; None otherwise."""
    if not isinstance(stdout, str) or not stdout.strip():
        return None
    try:
        doc = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(doc, dict):
        return doc
    if isinstance(doc, list):
        for ev in reversed(doc):
            if isinstance(ev, dict) and ev.get("type") == "result":
                return ev
    return None


def _events(log_path):
    try:
        with Path(log_path).open(encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    ev = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    yield ev
    except OSError:
        return


def result_from_log(log_path):
    found = None
    for ev in _events(log_path):
        if ev.get("type") == "result":
            found = ev
    return found


def last_tool_from_log(log_path):
    """The name of the last tool_use block in a stream-json log, or None."""
    last = None
    for ev in _events(log_path):
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and \
                    isinstance(block.get("name"), str):
                last = block["name"]
    return last


def last_tool(result):
    """The last tool named in a json result record (its permission_denials), or None."""
    if not isinstance(result, dict):
        return None
    denials = result.get("permission_denials")
    if isinstance(denials, list):
        for d in reversed(denials):
            if isinstance(d, dict) and isinstance(d.get("tool_name"), str):
                return d["tool_name"]
    return None


def cause(rc, result, tool):
    """The cause line, or None unless rc is a non-zero int and the result says success."""
    if type(rc) is not int or rc == 0:
        return None
    if not isinstance(result, dict) or result.get("subtype") != "success":
        return None
    text = first_line(result.get("result")) or "(empty)"
    name = _ascii(" ".join(str(tool).split()))[:80] if tool else NO_TOOL
    return f"{PREFIX}: rc {rc} with result subtype success; result: {text}; last tool: {name}"


def annotate(proc, log_path=None):
    """Append the cause line to proc.stderr (one line, newline-ended) and return it;
    None and no change when there is no cause."""
    rc = getattr(proc, "returncode", None)
    if type(rc) is not int or rc == 0:
        return None
    if log_path:
        result = result_from_log(log_path)
        tool = last_tool_from_log(log_path) or last_tool(result)
    else:
        result = parse_result(getattr(proc, "stdout", None))
        tool = last_tool(result)
    line = cause(rc, result, tool)
    if line is None:
        return None
    err = getattr(proc, "stderr", None)
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    if not isinstance(err, str):
        err = ""
    if err and not err.endswith("\n"):
        err += "\n"
    proc.stderr = err + line + "\n"
    return line
