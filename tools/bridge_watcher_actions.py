"""bridge_watcher_actions.py — Phase 2 auto-action handlers.

Spawns headless `claude --print` with restricted tool allowlist + system prompt.
Captures structured JSON output. Returns a tagged result the watcher uses to
decide whether to post a result OR demote to the escalation lane.

Hard rules (per BRIDGE_WATCHER_PLAN.md §7):
  - Edit + Write tools are NEVER in the allowlist (MVP through Phase 2).
  - Frozen-file intent-verb gate runs BEFORE invoking claude --print.
  - 16 KB body cap; overflow writes to <data_dir>/bridge_action_artifacts/<task_id>.json.
  - Per-call --max-budget-usd hard cap (from per-node config).
  - Daily $/USD cap tracked in state file; over-cap → escalate.

Import-safe: pure functions + one dispatch entry point. The watcher is
responsible for calling `run_action(envelope, lane, node_config, ...)` only
when the classifier returned auto-read or auto-ops.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

_log = logging.getLogger("rc.bridge_watcher.actions")

# Tools that are NEVER allowed in any auto-action invocation. Hard rule per
# BRIDGE_WATCHER_PLAN.md §7 (Peer strong ask). Even if a node config tries to
# include these, the watcher strips them before passing to --allowed-tools.
_NEVER_ALLOWED = frozenset({"Edit", "Write", "NotebookEdit"})

# Tools auto-read lane gets (read-only by intent).
_AUTO_READ_TOOLS = ("Read", "Grep", "Glob")

# Tools auto-ops lane gets in addition to read tools (Bash for restricted ops
# verbs only). The Bash regex restriction comes from node_config's
# bash_restricted list, surfaced via --allowed-tools "Bash(<pattern>)".
_AUTO_OPS_BASE_TOOLS = ("Read", "Grep", "Glob")

# Intent verbs that, when paired with a frozen-file mention, trip the gate.
# The gate is intentionally broad — "modify" alone shouldn't trip; only
# verbs near a path token. See _has_frozen_intent below.
_WRITE_VERBS = frozenset({
    "edit", "write", "replace", "modify", "patch", "delete", "remove",
    "alter", "change", "fix", "rewrite", "rename", "swap", "overwrite",
    "rm", "remove-item", "set-content", "out-file",
})

# How many chars of context around a frozen-file mention count as "near".
_INTENT_PROXIMITY = 80

# Per-call max budget defaults if node config lacks one (USD).
_DEFAULT_PER_CALL_BUDGET_USD = 0.25


# ── Frozen-file intent-verb gate ───────────────────────────────────────


def _has_frozen_intent(prompt: str, frozen_files: list[str]) -> Optional[str]:
    """Return reason string if prompt suggests writing a frozen file, else None.

    Strategy: for each frozen file path in the list, check if the prompt
    mentions it (case-insensitive substring match on the basename and full
    path). If yes, scan a window of ±_INTENT_PROXIMITY chars around the
    mention for any write verb. Hit → escalate.

    Examples:
      "explain main.py last error"               → no intent (read)
      "edit main.py line 42"                     → INTENT (edit verb near path)
      "show me what's wrong with app/__init__"   → no intent (no verb)
      "rewrite the auth in core/log_setup.py"    → INTENT
    """
    if not prompt or not frozen_files:
        return None
    p_lower = prompt.lower()
    for path in frozen_files:
        path_lower = path.lower()
        basename = os.path.basename(path_lower)
        # Try full path first (less ambiguous), then basename.
        for needle in (path_lower, basename):
            idx = 0
            while True:
                pos = p_lower.find(needle, idx)
                if pos == -1:
                    break
                window_start = max(0, pos - _INTENT_PROXIMITY)
                window_end = min(len(p_lower), pos + len(needle) + _INTENT_PROXIMITY)
                window = p_lower[window_start:window_end]
                # Word-boundary verb match
                for verb in _WRITE_VERBS:
                    if re.search(rf"\b{re.escape(verb)}\b", window):
                        return (f"frozen-file write intent: '{verb}' near '{path}' "
                                f"(window: ...{window[:120]}...)")
                idx = pos + len(needle)
    return None


# ── Pattern matching for auto-read / auto-ops classification ───────────


def _matches_any_pattern(prompt: str, patterns: list[str]) -> Optional[str]:
    """Return the matching pattern (for logging), else None.

    Patterns are POSIX-ish glob-style (`tail .* log`, `cat .*`). Matched as
    case-insensitive regex anchored only by the patterns themselves (no
    implicit ^ or $).
    """
    if not prompt or not patterns:
        return None
    p_lower = prompt.lower()
    for pat in patterns:
        try:
            if re.search(pat.lower(), p_lower):
                return pat
        except re.error as exc:
            _log.warning("invalid pattern %r: %s — skipping", pat, exc)
    return None


# ── Token cap ───────────────────────────────────────────────────────────


def is_over_daily_cap(state: dict, cap_usd: float) -> bool:
    """True if today's spend has hit/exceeded the per-node cap."""
    if cap_usd <= 0:
        return True  # cap of 0 = effectively disabled
    spent = float(state.get("tokens_used_today_usd", 0.0))
    return spent >= cap_usd


def reset_daily_spend_if_new_day(state: dict, *, now_local: Optional[time.struct_time] = None) -> None:
    """Mutate `state` in place: reset tokens_used_today_usd at local midnight."""
    if now_local is None:
        now_local = time.localtime()
    today = time.strftime("%Y-%m-%d", now_local)
    if state.get("tokens_day") != today:
        state["tokens_day"] = today
        state["tokens_used_today_usd"] = 0.0


# ── Body cap + artifact overflow ───────────────────────────────────────


def _maybe_offload_body(body: dict, task_id: str, artifacts_dir: Path,
                       cap_bytes: int = 16 * 1024) -> dict:
    """If body serializes >cap_bytes, write to artifact file + return preview body."""
    raw = json.dumps(body, ensure_ascii=False)
    if len(raw.encode("utf-8")) <= cap_bytes:
        return body
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    art_path = artifacts_dir / f"{task_id}.json"
    art_path.write_text(raw, encoding="utf-8")
    preview = raw[:1024]
    return {
        "body_path": str(art_path),
        "truncated": True,
        "full_size_bytes": len(raw.encode("utf-8")),
        "preview": preview,
    }


# ── claude --print invocation ───────────────────────────────────────────


def _resolve_claude_executable() -> str:
    """Find the claude CLI binary. On Windows it's typically claude.cmd (npm shim);
    subprocess.run won't auto-add .cmd, so probe candidates."""
    # First check ANTHROPIC_CLAUDE_PATH override
    override = os.environ.get("ANTHROPIC_CLAUDE_PATH")
    if override and os.path.exists(override):
        return override
    # Probe common locations on Windows + POSIX
    appdata = os.environ.get("APPDATA", "")
    candidates = [
        os.path.join(appdata, "npm", "claude.cmd") if appdata else None,
        os.path.join(appdata, "npm", "claude.exe") if appdata else None,
        "claude.cmd",
        "claude.exe",
        "claude",
    ]
    for c in candidates:
        if not c:
            continue
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        else:
            # Try via PATH using shutil.which
            import shutil as _shutil
            found = _shutil.which(c)
            if found:
                return found
    return "claude"  # last-ditch; subprocess will fail with WinError 2 if not found


def _build_claude_argv(*, task_prompt: str,
                       allowed_tools: list,
                       project_root: Path,
                       prompt_file: Path,
                       max_turns: int,
                       per_call_budget_usd: float,
                       api_key_path: Optional[Path]) -> list:
    """Construct argv for claude --print invocation. Pure; no exec."""
    # Strip never-allowed tools defensively (config could include them)
    safe_tools = [t for t in allowed_tools if t not in _NEVER_ALLOWED]

    # Use comma-separated for nargs+ flags (--allowed-tools, --disallowed-tools,
    # --add-dir) so they don't greedily slurp later positional args.
    argv = [
        _resolve_claude_executable(),
        "--print",
        "--bare",                              # no plugins/hooks/MCP/CLAUDE.md
        "--no-session-persistence",            # don't pollute session list
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--max-budget-usd", str(per_call_budget_usd),
        # bypassPermissions skips Claude Code's interactive approval gate.
        # The watcher's --allowed-tools / --disallowed-tools allowlist + the
        # frozen-file intent gate already enforce safety, so the per-tool
        # approval prompt would just hang the headless invocation.
        "--permission-mode", "bypassPermissions",
        "--allowed-tools",    ",".join(safe_tools),
        "--disallowed-tools", ",".join(sorted(_NEVER_ALLOWED)),
        "--add-dir",          str(project_root),
        "--append-system-prompt-file", str(prompt_file),
        task_prompt,           # MUST be last positional
    ]
    return argv


def _run_subprocess(argv: list[str], *, timeout_s: int,
                    env_extra: Optional[dict] = None) -> Tuple[int, str, str]:
    """Run subprocess, capture stdout/stderr/rc. Never raises."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=timeout_s, env=env, encoding="utf-8", errors="replace",
            check=False,
        )
        return (proc.returncode, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        return (124, "", f"timeout after {timeout_s}s")
    except (OSError, FileNotFoundError) as exc:
        return (127, "", f"spawn failed: {exc}")


def _parse_claude_json(stdout: str) -> Tuple[Optional[dict], Optional[float], Optional[str]]:
    """Parse claude --print --output-format json output.

    Returns (action_payload, cost_usd, error_string).
    `action_payload` is the sub-Claude's structured output (parsed).
    `cost_usd` is the call cost (from result envelope, if present).
    """
    if not stdout.strip():
        return (None, None, "empty stdout from claude")
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return (None, None, f"claude output not JSON: {exc} (head: {stdout[:200]!r})")
    # Claude --print --output-format json typically wraps in {type:"result",result:"...",...}.
    # Cost is total_cost_usd at top level.
    cost = None
    if isinstance(envelope, dict):
        try:
            cost = float(envelope.get("total_cost_usd") or envelope.get("cost_usd") or 0.0) or None
        except (TypeError, ValueError):
            cost = None
    # Handle is_error envelopes (max-turns exceeded, budget hit, etc.) — surface as error result
    if isinstance(envelope, dict) and envelope.get("is_error"):
        errs = envelope.get("errors") or []
        err_text = "; ".join(str(e)[:200] for e in errs) if errs else (envelope.get("stop_reason") or "unknown error")
        return ({"status": "error",
                 "summary": f"sub-Claude error: {err_text[:80]}",
                 "body": {"error": err_text,
                          "stop_reason": envelope.get("stop_reason"),
                          "duration_ms": envelope.get("duration_ms"),
                          "num_turns": envelope.get("num_turns"),
                          "claude_envelope_is_error": True}},
                cost, None)
    # Sub-Claude's actual response is in envelope["result"] (a string)
    raw_result = envelope.get("result") if isinstance(envelope, dict) else None
    if not isinstance(raw_result, str):
        return (None, cost, f"missing 'result' field; envelope keys: {list(envelope) if isinstance(envelope, dict) else type(envelope)}")
    # Strip Markdown fences if Claude added them
    cleaned = raw_result.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\s*\n?", "", cleaned, count=1)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned, count=1)
    try:
        action = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Last-resort: treat the raw result as a textual answer (status=ok, body.text).
        # Better to surface the answer than fail entirely on prose-shaped output.
        return ({"status": "ok", "summary": "sub-Claude returned non-JSON; wrapped as text",
                 "body": {"text": cleaned[:8000], "auto_wrapped": True,
                          "_parse_error": str(exc)[:200]}},
                cost, None)
    if not isinstance(action, dict):
        # Result was JSON but not a dict (list/string/number) — wrap it.
        return ({"status": "ok", "summary": "sub-Claude returned non-dict JSON; wrapped",
                 "body": {"value": action, "auto_wrapped": True}},
                cost, None)
    # If result is a dict but lacks the {status, summary, body} wrapper, infer status=ok
    # and stash the dict as body. Sub-Claude often follows user-prompt's "reply with X"
    # over the system prompt's wrapper rule.
    if "status" not in action:
        return ({"status": "ok", "summary": "sub-Claude returned dict without wrapper; auto-wrapped",
                 "body": {**action, "auto_wrapped": True}},
                cost, None)
    return (action, cost, None)


# ── Main entry point ───────────────────────────────────────────────────


def run_action(*, envelope: dict, lane: str, node_config: dict,
               state: dict, action_prompt_path: Path,
               artifacts_dir: Path, project_root: Path,
               api_key_path: Optional[Path] = None,
               ) -> Tuple[str, dict, float]:
    """Run one auto-action. Returns (status, body, cost_usd).

    status:
      "ok"       — task completed; caller should bridge_post_result with --exit-code 0
      "error"    — task failed; caller should bridge_post_result with --exit-code 1
      "escalate" — caller should NOT post; demote to escalation lane

    body: dict to JSON-encode for the bridge_post_result --body argument
          (or for the pending file if escalating)

    cost_usd: float to add to state["tokens_used_today_usd"]
    """
    task_id = envelope.get("id", "unknown")
    prompt = ""
    body_field = envelope.get("body")
    if isinstance(body_field, dict):
        prompt = str(body_field.get("prompt") or "")

    # 1. Frozen-file intent gate (before spawning claude — saves tokens)
    frozen = node_config.get("escalate_always") or []
    intent_reason = _has_frozen_intent(prompt, frozen)
    if intent_reason:
        return ("escalate",
                {"reason": intent_reason,
                 "suggested_action": "operator review via /process-bridge-tasks; re-issue with allow_frozen_writes:true if approved",
                 "lane": lane},
                0.0)

    # 2. Daily cap check
    cap = float(node_config.get("daily_token_cap_usd") or 0.0)
    if is_over_daily_cap(state, cap):
        return ("escalate",
                {"reason": f"daily token cap reached ({state.get('tokens_used_today_usd',0.0):.2f}/{cap:.2f} USD)",
                 "suggested_action": "operator drains manually OR raises daily_token_cap_usd in bridge_watcher_config.json",
                 "lane": lane},
                0.0)

    # 3. Build allowlist for the lane
    if lane == "auto-read":
        allowed = list(_AUTO_READ_TOOLS)
    elif lane == "auto-ops":
        allowed = list(_AUTO_OPS_BASE_TOOLS)
        # Bash with regex restriction(s) from config
        for pat in (node_config.get("bash_restricted") or []):
            allowed.append(f"Bash({pat})")
    else:
        return ("error",
                {"error": f"unknown lane {lane!r}", "details": "expected auto-read or auto-ops"},
                0.0)

    # 4. Per-call budget — min of (config per-call) and (remaining daily)
    per_call_budget = float(node_config.get("per_call_budget_usd") or _DEFAULT_PER_CALL_BUDGET_USD)
    remaining = cap - float(state.get("tokens_used_today_usd", 0.0))
    per_call_budget = max(0.05, min(per_call_budget, remaining))

    # 5. Spawn claude --print
    timeout_s = int(node_config.get("timeout_s") or 60)
    max_turns = int(node_config.get("max_turns") or 4)
    env_extra = {}
    if api_key_path and api_key_path.exists():
        try:
            env_extra["ANTHROPIC_API_KEY"] = api_key_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    argv = _build_claude_argv(
        task_prompt=prompt,
        allowed_tools=allowed,
        project_root=project_root,
        prompt_file=action_prompt_path,
        max_turns=max_turns,
        per_call_budget_usd=per_call_budget,
        api_key_path=api_key_path,
    )
    _log.info("auto-action lane=%s task_id=%s budget=$%.2f tools=%s",
              lane, task_id, per_call_budget, allowed)

    rc, stdout, stderr = _run_subprocess(argv, timeout_s=timeout_s, env_extra=env_extra)

    # 6. Parse + dispatch
    action, cost, parse_err = _parse_claude_json(stdout)
    cost = cost or 0.0

    if parse_err:
        return ("error",
                {"error": "claude subprocess output unparseable",
                 "details": parse_err,
                 "rc": rc,
                 "stderr_head": stderr[:1000],
                 "lane": lane},
                cost)

    status = action.get("status")
    summary = action.get("summary", "")[:240]
    body = action.get("body") or {}

    if status not in ("ok", "error", "escalate"):
        return ("error",
                {"error": f"invalid status from sub-Claude: {status!r}",
                 "details": "expected one of: ok, error, escalate",
                 "raw_action": action,
                 "lane": lane},
                cost)

    # 7. Body cap / overflow
    if isinstance(body, dict):
        body = _maybe_offload_body(body, task_id, artifacts_dir)
    body["_lane"] = lane
    if summary:
        body["_summary"] = summary

    return (status, body, cost)


# ── Self-tests ─────────────────────────────────────────────────────────


def _test() -> None:
    # Test frozen-file intent gate
    frozen = ["main.py", "core/log_setup.py", "app/__init__.py"]

    cases = [
        ("explain main.py last error", None, "read query — no intent"),
        ("edit main.py line 42", "edit", "write verb near path"),
        ("show me what's wrong with app/__init__.py", None, "no verb"),
        ("rewrite the auth in core/log_setup.py", "rewrite", "verb near path"),
        ("change main.py to handle KIWI mode", "change", "verb near path"),
        ("tell me about edit main.py", "edit", "even a meta question hits"),  # conservative
        ("look at file structure", None, "no path"),
        ("delete the build cache from main directory", None, "no frozen path"),
    ]
    fails = 0
    for prompt, expected_verb, label in cases:
        reason = _has_frozen_intent(prompt, frozen)
        hit = reason is not None
        ok = (hit == (expected_verb is not None))
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] '{prompt[:60]}' -> {('HIT: ' + str(reason)[:80]) if hit else 'no-intent'} ({label})")
        if not ok:
            fails += 1

    # Test pattern match
    patterns = ["tail .* log", "show .* state", "what is .*pid"]
    pcases = [
        ("tail today's log", "tail .* log"),
        ("show me the state", "show .* state"),
        ("what is the watcher pid", "what is .*pid"),
        ("delete everything", None),
    ]
    for prompt, expected in pcases:
        got = _matches_any_pattern(prompt, patterns)
        ok = (got == expected) if expected else (got is None)
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] match '{prompt}' -> {got} (expected {expected})")
        if not ok:
            fails += 1

    # Test daily-cap check
    state = {"tokens_used_today_usd": 0.0}
    print(f"  [{'OK ' if not is_over_daily_cap(state, 5.0) else 'FAIL'}] cap not hit at 0/5")
    state["tokens_used_today_usd"] = 5.0
    print(f"  [{'OK ' if is_over_daily_cap(state, 5.0) else 'FAIL'}] cap hit at 5/5")
    state["tokens_used_today_usd"] = 4.99
    print(f"  [{'OK ' if not is_over_daily_cap(state, 5.0) else 'FAIL'}] cap not hit at 4.99/5")

    # Test daily reset
    state = {"tokens_day": "2025-01-01", "tokens_used_today_usd": 4.5}
    reset_daily_spend_if_new_day(state)
    print(f"  [{'OK ' if state['tokens_used_today_usd'] == 0.0 else 'FAIL'}] reset on day change")

    print(f"\n{fails} failures" if fails else "\nall tests passed")
    raise SystemExit(0 if fails == 0 else 1)


if __name__ == "__main__":
    _test()
