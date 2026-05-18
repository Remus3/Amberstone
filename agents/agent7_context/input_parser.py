"""Agent 7 - Natural-language input parser.

Takes a string from the user (typed into the iPad dashboard or a CLI
tool) and translates it into zero, one, or more tasks filed via
Agent 1's scheduler.

Two-stage approach:

  1. **Rule-based fast path.** Regex + keyword matching for the common
     commands. No API cost, no latency. Covers ~80% of inputs.

  2. **LLM fallback.** If no rule matches, spawn a Haiku session with
     the Agent 7 charter and let the model decide. Returns the same
     ``ParseResult`` shape regardless of path.

The parser never dispatches other agents directly - it only files
tasks. Routing is Agent 1's job. User overrides (``user_override=True``
on the task) flow through for direct orders like ``Agent 6 audit now``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agents.agent1_lead import Scheduler

logger = logging.getLogger("agent7.input_parser")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class ParseResult:
    """Result of parsing one NL message.

    - ``filed``: task ids that were filed in response.
    - ``reply``: short prose to show the user (may be empty if the task
      itself is the response).
    - ``intent``: semantic tag - "audit" / "note" / "status" / "clarify" /
      "chitchat" / "fallback_llm".
    - ``used_llm``: True if we fell back to the ephemeral spawn.
    """
    filed: list[str] = field(default_factory=list)
    reply: str = ""
    intent: str = ""
    used_llm: bool = False


# ── rule-based patterns ─────────────────────────────────────────────
#
# Each rule returns (ParseResult, tasks_to_file) where tasks_to_file is
# a list of kwargs dicts for Scheduler.file_task(). The parser actually
# files them after dry-run, so rules stay side-effect-free.

_RE_AGENT_DIRECT = re.compile(
    r"^\s*agent\s*(?P<n>[0-7])\s*(?:,|:|-)?\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_RE_AUDIT = re.compile(r"\baudit\b.*\b(now|full|pass)\b|\bfull\s+audit\b", re.IGNORECASE)
_RE_STATUS = re.compile(r"\b(status|queue|what'?s\s+(in\s+)?(the\s+)?queue|what\s+is\s+pending)\b", re.IGNORECASE)
_RE_NOTE = re.compile(r"^\s*(?:note|remember|remind\s+me)\s*[:,]?\s*(?P<body>.+)$", re.IGNORECASE)
_RE_RESTART_RC = re.compile(r"^\s*(?:please\s+)?restart\s+(?:rc|the\s+app|riot\s*commander)\s*$", re.IGNORECASE)
_RE_DESTRUCTIVE = re.compile(r"\b(?:rm\s+-rf|drop\s+table|delete\s+all|wipe\b|truncate\b|nuke\b)", re.IGNORECASE)


# Round 43: constrained vocabulary of op names the LLM fallback is
# allowed to produce. Anything outside this set gets coerced to
# ``user-unparsed`` so we never file a task to a deterministic agent
# that has no handler for the fabricated op (which used to complete
# silently as a no-op - bug reported 2026-04-23).
LLM_ALLOWED_OPS: frozenset[str] = frozenset({
    # Deterministic handled ops
    "game-summary",
    "ui-proposal",
    # User-intent / record-keeping ops
    "user-note",
    "user-direct-order",
    "user-destructive-request",
    "user-unparsed",
    # Agent-specific entry points
    "agent6-full-audit-pass",
    # Ephemeral LLM ops (agent 2/4/5/6 consumers)
    "analyze-now",
    "coach-propose",
})


class InputParser:
    def __init__(
        self,
        scheduler: Scheduler | None = None,
        llm_spawn: Callable[[str, str, str, dict], dict] | None = None,
    ) -> None:
        self._scheduler = scheduler or Scheduler()
        self._llm_spawn = llm_spawn  # optional - falls back to prose-only if not wired

    # ---- public entry point ----------------------------------------
    def parse(self, text: str) -> ParseResult:
        text = (text or "").strip()
        if not text:
            return ParseResult(reply="(empty input)", intent="chitchat")

        # Destructive phrases always go to hard gate.
        if _RE_DESTRUCTIVE.search(text):
            tid = self._scheduler.file_task(
                op="user-destructive-request",
                owner_agent="1",
                priority=5,
                categories=[1],   # hard gate → needs_explicit_approval
                payload={"user_text": text, "intent": "destructive"},
            ).id
            return ParseResult(
                filed=[tid],
                reply=("Destructive request detected; filed for explicit "
                       "approval. Check the queue and approve via the UI "
                       "if you meant it."),
                intent="destructive",
            )

        # Audit now.
        if _RE_AUDIT.search(text):
            tid = self._scheduler.file_task(
                op="agent6-full-audit-pass",
                owner_agent="6",
                priority=0,
                categories=[],
                payload={
                    "scope": "full-phase3-repo-audit",
                    "blocks_all_subsequent": True,
                    "user_text": text,
                    "filed_by": "agent7",
                },
                user_override=True,
            ).id
            return ParseResult(
                filed=[tid],
                reply="Audit queued at priority 0.",
                intent="audit",
            )

        # Status / queue summary - no task, just prose.
        if _RE_STATUS.search(text):
            snap = self._scheduler.snapshot()
            summary = ", ".join(f"{k}={v}" for k, v in sorted(snap["by_status"].items()))
            return ParseResult(
                reply=f"Queue: {snap['total']} total - {summary or '(empty)'}.",
                intent="status",
            )

        # Direct agent command: "Agent 6, audit this file"
        m = _RE_AGENT_DIRECT.match(text)
        if m:
            n = m.group("n")
            rest = m.group("rest").strip()
            tid = self._scheduler.file_task(
                op="user-direct-order",
                owner_agent=n,
                priority=20,
                categories=[],
                payload={
                    "user_text": text,
                    "instruction": rest,
                    "filed_by": "agent7",
                },
                user_override=True,
            ).id
            return ParseResult(
                filed=[tid],
                reply=f"Direct order filed for agent{n}.",
                intent=f"direct_agent{n}",
            )

        # Restart RC.
        if _RE_RESTART_RC.match(text):
            # AUDIT 2026-04-28 (4.3): atomic-write so the supervisor's poll
            # loop never reads a half-written trigger.
            from core.polled_json import atomic_write_text
            trigger = _PROJECT_ROOT / "restart_trigger.txt"
            atomic_write_text(
                trigger,
                f"user-request-{__import__('time').strftime('%Y%m%dT%H%M%SZ', __import__('time').gmtime())}",
            )
            return ParseResult(
                reply="RC restart trigger written. The existing RC supervisor will pick it up within ~1s.",
                intent="restart_rc",
            )

        # Generic note → Agent 4 for later.
        m = _RE_NOTE.match(text)
        if m:
            body = m.group("body").strip()
            tid = self._scheduler.file_task(
                op="user-note",
                owner_agent="4",
                priority=50,
                categories=[],
                payload={"body": body, "user_text": text, "filed_by": "agent7"},
            ).id
            return ParseResult(
                filed=[tid],
                reply="Noted - Agent 4 will consider it on the next idle pass.",
                intent="note",
            )

        # --- LLM fallback --------------------------------------------
        if self._llm_spawn is not None:
            allowed = sorted(LLM_ALLOWED_OPS)
            try:
                result = self._llm_spawn(
                    "7", "t-nl-parse", "nl-parse",
                    {
                        "message": text,
                        "instruction": (
                            "Parse this user message into either a task "
                            "for the scheduler or a conversational reply. "
                            "Return ONE JSON object.\n\n"
                            "Conversational reply: "
                            "{\"reply\":\"...\"}\n\n"
                            "Task (must use one of the allowed ops):\n"
                            "{\"task\":{\"op\":\"<one-of-allowed>\","
                            "\"owner_agent\":\"<0-7>\","
                            "\"priority\":50,\"payload\":{...}},"
                            "\"reply\":\"<short confirmation>\"}\n\n"
                            f"Allowed op values: {allowed}. If no "
                            "allowed op fits, return either a "
                            "conversational reply OR "
                            "{\"task\":{\"op\":\"user-unparsed\","
                            "\"owner_agent\":\"7\",\"priority\":80,"
                            "\"payload\":{\"reason\":\"...\"}}}. "
                            "DO NOT invent op names. Do not use tools."
                        ),
                        "allowed_ops": allowed,
                        "spawn_budget_usd": 0.10,
                        "spawn_timeout_sec": 60,
                    },
                )
                return self._consume_llm_result(text, result)
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM fallback failed: %s", e)

        # Neither rules nor LLM - file a no-op task so the input isn't lost.
        tid = self._scheduler.file_task(
            op="user-unparsed",
            owner_agent="7",
            priority=80,
            payload={"user_text": text},
        ).id
        return ParseResult(
            filed=[tid],
            reply=("I wasn't sure what to do with that. Filed it as "
                   f"`user-unparsed` (task {tid}) - rephrase or try "
                   "`Agent <N> <instruction>`."),
            intent="fallback_unparsed",
        )

    # ---- LLM result consumer ---------------------------------------
    def _consume_llm_result(self, user_text: str, llm_envelope: dict[str, Any]) -> ParseResult:
        """Interpret the JSON envelope returned by an ephemeral Haiku call."""
        import json
        raw = llm_envelope.get("result", {})
        if isinstance(raw, dict):
            # claude --output-format json wraps the model output in {"result": "..."}
            text_out = raw.get("result") or raw.get("raw_stdout") or ""
        else:
            text_out = str(raw)

        # Try to find a JSON block in the output.
        match = re.search(r"\{.*\}", text_out, re.DOTALL)
        parsed: dict | None = None
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None

        if parsed and "task" in parsed and isinstance(parsed["task"], dict):
            t = parsed["task"]
            raw_op = str(t.get("op", "user-llm-task"))
            # Round 43: coerce fabricated ops. Anything outside the
            # allowed vocabulary lands as ``user-unparsed`` so it can't
            # reach a deterministic agent that lacks a handler.
            if raw_op in LLM_ALLOWED_OPS:
                op = raw_op
                owner = str(t.get("owner_agent", "7"))
                priority = int(t.get("priority", 50))
                fabricated = False
            else:
                logger.warning(
                    "LLM fabricated op %r not in allowed vocabulary - "
                    "coercing to user-unparsed",
                    raw_op,
                )
                op = "user-unparsed"
                owner = "7"
                priority = 80
                fabricated = True
            tid = self._scheduler.file_task(
                op=op,
                owner_agent=owner,
                priority=priority,
                categories=list(t.get("categories", []) or []),
                payload={
                    "user_text": user_text,
                    "llm_derived": True,
                    "llm_proposed_op": raw_op,
                    "op_coerced": fabricated,
                    **(t.get("payload") or {}),
                },
            ).id
            reply = parsed.get("reply", "Filed via LLM parse.")
            if fabricated:
                reply = (
                    f"LLM proposed op `{raw_op}` which isn't in the "
                    f"allowed vocabulary; filed as `user-unparsed` "
                    f"instead (task {tid}). Rephrase or use "
                    f"`Agent <N> <instruction>`."
                )
            return ParseResult(
                filed=[tid],
                reply=reply,
                intent="fallback_llm_coerced" if fabricated else "fallback_llm",
                used_llm=True,
            )
        if parsed and "reply" in parsed:
            return ParseResult(
                reply=str(parsed["reply"]),
                intent="chitchat",
                used_llm=True,
            )

        # LLM gave prose - surface it as the reply.
        return ParseResult(
            reply=text_out.strip() or "(no reply)",
            intent="chitchat",
            used_llm=True,
        )
