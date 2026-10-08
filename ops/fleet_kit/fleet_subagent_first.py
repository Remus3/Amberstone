# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v10+ - SUB-AGENT FIRST enforcement (FLEET-COMMON banner).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: the main session is the operator's console. Session 7 broke the doctrine
through the old "quick read or one-line fix" exception and the operator saw
Bash and Edit rows in the main pane. This hook makes the rule mechanical.

    python fleet_subagent_first.py        (a PreToolUse command hook)

Wiring (v11, ruling R3), in the tree's tracked project .claude/settings.json,
never the account settings: PreToolUse, matcher
Bash|PowerShell|Read|Edit|Write|Grep|Glob|NotebookEdit|MultiEdit, timeout 10,
command ANCHORED to the project dir so a session cd cannot break it:
    python "$CLAUDE_PROJECT_DIR/ops/fleet_kit/fleet_subagent_first.py"
The same string followed by ` || true` is also conformant. The v10
cwd-relative form exits 2 from any other cwd, which blocks every tool.

Reads the PreToolUse input on stdin. The Claude Code hooks reference
(https://code.claude.com/docs/en/hooks, "Agent-specific fields") says
`agent_id` is "Present only when the hook fires inside a subagent call. Use
this to distinguish subagent hook calls from main-thread calls." So:

  * tool in GUARDED and no agent_id (main thread) -> deny, one-line reason;
  * inside a sub-agent (agent_id present), or any tool not in GUARDED
    (Agent, SendMessage, TaskStop, ToolSearch, Skill, AskUserQuestion,
    ScheduleWakeup, ReadNotifications, MCP tools, ...) -> no decision: the call
    goes through the normal permission flow untouched.

`agent_type` alone is NOT a sub-agent signal: a session started with --agent
carries it in its main thread.

Mode (first match wins):
  env FLEET_SUBAGENT_FIRST = off | log | deny
  file <project>/ops/loop/control/subagent_first.mode, first word off|log|deny
  default deny
`off` and `log` never deny; `off` also skips the log line.

Each decision (mode log or deny) appends one JSONL line to
<project>/ops/loop/control/subagent_first.jsonl:
  {"at", "tool", "thread": main|sub, "agent_type", "decision": deny|would-deny|allow, "mode"}
<project> = env CLAUDE_PROJECT_DIR, else the input's cwd, else the process cwd.

Stdout carries only the JSON decision (deny), else nothing. No ANSI. Never
fails closed: any exception -> exit 0 with no output (the call proceeds).

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import datetime as _dt
import json
import os
import sys
from pathlib import Path

GUARDED = frozenset(("Bash", "PowerShell", "Read", "Edit", "Write", "Grep",
                     "Glob", "NotebookEdit", "MultiEdit"))
REASON = "SUBAGENT-FIRST: dispatch this to a sub-agent"
ENV_MODE = "FLEET_SUBAGENT_FIRST"
MODE_REL = Path("ops/loop/control/subagent_first.mode")
LOG_REL = Path("ops/loop/control/subagent_first.jsonl")
MODES = ("off", "log", "deny")


def project_root(payload, env):
    root = env.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return Path(root)


def mode(root, env):
    v = (env.get(ENV_MODE) or "").strip().lower()
    if v in MODES:
        return v
    try:
        words = (root / MODE_REL).read_text(encoding="ascii", errors="replace").split()
    except OSError:
        words = []
    if words and words[0].lower() in MODES:
        return words[0].lower()
    return "deny"


def decide(payload, mode_value):
    """(decision, thread). decision: deny | would-deny | allow."""
    tool = payload.get("tool_name") or ""
    sub = bool(payload.get("agent_id"))
    thread = "sub" if sub else "main"
    if sub or tool not in GUARDED:
        return "allow", thread
    return ("deny" if mode_value == "deny" else "would-deny"), thread


def deny_output():
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": REASON}}


def log(root, row):
    try:
        path = root / LOG_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="ascii", errors="replace", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
    except OSError:
        pass


def run(stdin_text, env=None, clock=None):
    """The hook body. Returns the stdout text ('' = no decision)."""
    env = os.environ if env is None else env
    payload = json.loads(stdin_text or "{}")
    if not isinstance(payload, dict):
        return ""
    root = project_root(payload, env)
    m = mode(root, env)
    if m == "off":
        return ""
    decision, thread = decide(payload, m)
    now = (clock or (lambda: _dt.datetime.now().astimezone()))()
    log(root, {"at": now.isoformat(timespec="seconds"),
               "tool": str(payload.get("tool_name") or ""),
               "thread": thread,
               "agent_type": payload.get("agent_type") or None,
               "decision": decision, "mode": m})
    if decision == "deny":
        return json.dumps(deny_output())
    return ""


def main():
    try:
        out = run(sys.stdin.read())
    except Exception:  # never fail closed
        return 0
    if out:
        sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
