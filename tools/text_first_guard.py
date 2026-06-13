#!/usr/bin/env python3
"""PreToolUse text-first backstop (R1-R3, CLAUDE.md "Execution Efficiency").

Denies vision / desktop tools that READ TEXT OR STATE off the screen when a
text path always exists in RC: file content -> Read / Grep; dashboard or
runtime state -> curl https://127.0.0.1:8888/api/... or Read
ops/runtime/health.json.

Scope is deliberately NARROW so the guard never wedges a sanctioned visual
ritual: ONLY the pure screen-text / clipboard readers are denied. Pixel
screenshots, live game capture (capture_monitor), preview_* DOM checks, and
clicks / typing are all ALLOWED (legit per R3 - the UI-audit ritual and
game-monitor). The escape-hatch file ops/runtime/allow_visual.flag, when
present, allows everything (rare case where no text path exists).

PreToolUse JSON contract: permissionDecision "deny" feeds the reason back to
the model and blocks the call, so the model retries with the text tool. The
guard never raises - a crashing guard must not block tools.
"""
import json
import sys
from pathlib import Path

# Pure screen-text / clipboard readers that ALWAYS have a text alternative.
_DENY = {
    "mcp__Windows-MCP__Scrape",
    "mcp__computer-use__read_clipboard",
}

_FLAG = Path(r"C:\Riot Commander\ops\runtime\allow_visual.flag")

_REASON = (
    "Text-first (CLAUDE.md R1-R2): do not read text/state off the screen. "
    "File content -> Read/Grep. Dashboard/runtime state -> "
    "curl -k https://127.0.0.1:8888/api/state or Read ops/runtime/health.json. "
    "Override only when no text path exists: create ops/runtime/allow_visual.flag."
)


def main() -> int:
    try:
        raw = sys.stdin.read().lstrip("\\ufeff")
        payload = json.loads(raw) if raw.strip() else {}
        tool = payload.get("tool_name", "")
        if tool in _DENY and not _FLAG.exists():
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _REASON,
                }
            }
            sys.stdout.write(json.dumps(out))
    except (ValueError, TypeError, OSError):
        # Never block on guard failure.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
