#!/usr/bin/env python3
"""PreToolUse text-first backstop (R1-R3, CLAUDE.md "Execution Efficiency").

Denies vision / desktop tools that READ TEXT OR STATE off the screen when a
text path always exists in RC: file content -> Read / Grep; dashboard or
runtime state -> the STATE_HINT below (RC: the :8888 state API or
ops/runtime/health.json).

Scope is deliberately NARROW so the guard never wedges a sanctioned visual
ritual: ONLY the pure screen-text / clipboard readers are denied. Pixel
screenshots, live game capture (capture_monitor), preview_* DOM checks, and
clicks / typing are all ALLOWED (legit per R3 - the UI-audit ritual and
game-monitor). The escape-hatch flag file (FLAG_REL below), when present,
allows everything (rare case where no text path exists).

Portability (MAIN FIX 2026-10-21 1254 item 15): every RC-specific value is a
constant at the top - DENY_TOOLS, STATE_HINT, FLAG_REL, FLAG_DIR - and a host
without RC's dashboard overrides the hint and the flag through the environment:
  TEXT_FIRST_STATE_HINT  replaces the state hint ("" drops that clause);
  TEXT_FIRST_FLAG        the escape flag path (absolute, or relative to the
                         repo root). It counts only as a regular file strictly
                         inside FLAG_DIR (`ops/runtime/`, gitignored runtime
                         state, where the default flag lives); an override
                         anywhere else (or naming FLAG_DIR itself) is ignored
                         and the default FLAG_REL applies, so no system file
                         (RM-784) and no tracked repo file - this guard's own
                         source, README.md (RM-818) - can switch the guard off.
                         Reverses if: a host adopting the guard needs its flag
                         outside `ops/runtime/` (name that host's directory,
                         never the whole repo root again).
On a host where the two MCP readers are not installed the settings matcher
never fires, so the hook is a no-op by construction. An interpreter that
never starts is reported by the shell tail on the hook line in
ops/claude_settings.example.json, not here (RM-782).

PreToolUse JSON contract: permissionDecision "deny" feeds the reason back to
the model and blocks the call, so the model retries with the text tool. The
guard never raises and always exits 0: any payload it does not recognise
(unparseable, not a JSON object, a non-string tool name) is a silent no-op,
because a crashing guard must not block or noise tools.
"""
import json
import os
import sys
from pathlib import Path

# ---- RC configuration block (the only RC-specific values in this file) ----
#: Pure screen-text / clipboard readers that ALWAYS have a text alternative.
DENY_TOOLS = (
    "mcp__Windows-MCP__Scrape",
    "mcp__computer-use__read_clipboard",
)
#: Where runtime state is read as text instead.
STATE_HINT = (
    "curl -k https://127.0.0.1:8888/api/state or Read ops/runtime/health.json"
)
#: Escape-hatch flag, relative to the repo root.
FLAG_REL = "ops/runtime/allow_visual.flag"
#: The only directory a TEXT_FIRST_FLAG override may point into (RM-818).
FLAG_DIR = "ops/runtime"
ENV_STATE_HINT = "TEXT_FIRST_STATE_HINT"
ENV_FLAG = "TEXT_FIRST_FLAG"
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent


def _override() -> "Path | None":
    """The TEXT_FIRST_FLAG path when it resolves strictly inside FLAG_DIR,
    else None (RM-784 outside the root, RM-818 elsewhere in the repo)."""
    raw = os.environ.get(ENV_FLAG, "").strip()
    if not raw:
        return None
    path = Path(raw)
    try:
        flag_dir = (ROOT / FLAG_DIR).resolve()
        resolved = (path if path.is_absolute() else ROOT / path).resolve()
        if resolved == flag_dir or not resolved.is_relative_to(flag_dir):
            return None
    except (OSError, ValueError, RuntimeError):
        return None
    return resolved


def flag_path() -> Path:
    return _override() or ROOT / FLAG_REL


def flag_set() -> bool:
    """The escape hatch is a regular FILE; a directory never counts."""
    try:
        return flag_path().is_file()
    except OSError:
        return False


def reason() -> str:
    hint = os.environ.get(ENV_STATE_HINT, STATE_HINT).strip()
    flag = os.environ.get(ENV_FLAG, "").strip() if _override() else FLAG_REL
    parts = [
        "Text-first (CLAUDE.md R1-R2): do not read text/state off the screen.",
        "File content -> Read/Grep.",
    ]
    if hint:
        parts.append(f"Runtime state -> {hint}.")
    parts.append(f"Override only when no text path exists: create {flag}.")
    return " ".join(" ".join(parts).split())


def decide(payload: object) -> "dict | None":
    """The hook output for one payload, or None for a silent allow."""
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or tool not in DENY_TOOLS:
        return None
    if flag_set():
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason(),
        }
    }


def read_stdin() -> str:
    """stdin as BYTES, the UTF-8 BOM stripped there, decoded UTF-8 (RM-784):
    a text read plus a U+FEFF strip worked only when the console decoded
    UTF-8; under cp1252 the BOM arrived as three other characters."""
    stream = sys.stdin
    layer = getattr(stream, "buffer", None) or stream
    data = layer.read()
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).removeprefix(b"\xef\xbb\xbf").decode("utf-8", errors="replace")
    return (data or "").lstrip(chr(0xFEFF))


def main() -> int:
    try:
        raw = read_stdin()
        payload = json.loads(raw) if raw.strip() else None
        out = decide(payload)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
    except Exception:  # noqa: BLE001 - a guard failure must never block a tool
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
