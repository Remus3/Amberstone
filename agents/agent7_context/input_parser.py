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

Rule order (true-audit s144). A destructive phrase always goes to the hard
gate first. The two ANCHORED commands that carry the operator's own words - a
note (``note:`` / ``remember`` / ``remind me``) and a direct order
(``Agent <N> ...``) - are matched before the keyword SEARCHES for status, so
"remind me to check the queue" files a note instead of answering with a queue
summary and losing the input. A note is also matched before the full-audit
search, so "note: run a full audit next week" is a note, not a blocking
priority-0 audit; a direct order is still matched AFTER it, so
``Agent 6 audit now`` stays the audit.

The LLM reply is untrusted model output. ``_consume_llm_result`` validates
every field before filing: op from ``LLM_ALLOWED_OPS``, owner one of the
agents 0-7, a bounded integer priority, integer categories, a hard-gate
category on a destructive request, and a payload that can neither overwrite
the provenance keys nor carry the dispatcher's spawn-control keys. An error
envelope is never shown to the operator: it is logged and the input is filed
as ``user-unparsed`` with a friendly reply.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agents.agent1_lead import Scheduler
from core.log_scrub import redact_secrets, scrub_log

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


# -- rule-based patterns ---------------------------------------------
#
# Each rule returns (ParseResult, tasks_to_file) where tasks_to_file is
# a list of kwargs dicts for Scheduler.file_task(). The parser actually
# files them after dry-run, so rules stay side-effect-free.

# _RE_AGENT_DIRECT and _RE_NOTE were `KEYWORD\s*SEP?\s*(?P<x>.+)$`. CodeQL
# py/polynomial-redos (alerts 38 / 39, 2026-10-15): all three quantifiers can
# take the same run of spaces and `$` fails on an interior newline, so
# "agent0" + 1600 spaces + "x\ny" took 5.8 s (cubic; /api/input takes 256 KiB).
# The old engine tried the start of the captured text at every position from
# the greedy end of the separator run DOWN to the keyword, so its answer is the
# largest start that works: the greedy end itself, or - only when the
# separators run to the very end - the last char before the end (and before
# a final newline). Each form below tries exactly those two: the greedy run is
# taken atomically (lookahead capture + backreference), the fallback asserts
# the separators reach the end and lands on that last char. Same matches and
# groups as before, pinned by tests/test_input_parser_redos_codeql.py.
_RE_AGENT_DIRECT = re.compile(
    r"^\s*agent\s*(?P<n>[0-7])"
    r"(?:(?=(\s*(?:(?:,|:|-)\s*)?))\2"
    r"|(?=\s*(?:(?:,|:|-)\s*)?\Z)[\s\S]*(?=[^\n]\n?\Z))"
    r"(?P<rest>.+)$",
    re.IGNORECASE,
)
_RE_AUDIT = re.compile(r"\baudit\b.*\b(now|full|pass)\b|\bfull\s+audit\b", re.IGNORECASE)
_RE_STATUS = re.compile(r"\b(status|queue|what'?s\s+(in\s+)?(the\s+)?queue|what\s+is\s+pending)\b", re.IGNORECASE)
_RE_NOTE = re.compile(
    r"^\s*(?:note|remember|remind\s+me)"
    r"(?:(?=(\s*(?:[:,]\s*)?))\1"
    r"|(?=\s*(?:[:,]\s*)?\Z)[\s\S]*(?=[^\n]\n?\Z))"
    r"(?P<body>.+)$",
    re.IGNORECASE,
)
_RE_RESTART_RC = re.compile(r"^\s*(?:please\s+)?restart\s+(?:rc|the\s+app|riot\s*commander)\s*$", re.IGNORECASE)
_RE_DESTRUCTIVE = re.compile(r"\b(?:rm\s+-rf|drop\s+table|delete\s+all|wipe\b|truncate\b|nuke\b)", re.IGNORECASE)

# The two anchored patterns above stay exactly what the ReDoS oracle pins.
# On their own they take a keyword glued to a longer word ("notebook is low"
# filed the note "book is low") and the first digit of a multi-digit agent
# number ("Agent 10, ..." became an order to agent 1). These word-boundary
# pre-checks reject both before the capturing pattern runs.
_RE_AGENT_WORD = re.compile(r"^\s*agent\s*[0-7](?!\d)", re.IGNORECASE)
_RE_NOTE_WORD = re.compile(r"^\s*(?:note|remember|remind\s+me)\b", re.IGNORECASE)


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

# -- LLM reply validation (true-audit s144) ----------------------------

# The agents the scheduler can route to.
_AGENT_IDS: frozenset[str] = frozenset("01234567")
_LLM_DEFAULT_PRIORITY = 50
# Lower is more urgent. The rule path files the operator's own explicit
# orders at 0 (audit), 5 (destructive) and 20 (direct order); a model's
# guess never outranks them.
_LLM_PRIORITY_MIN = 20
_LLM_PRIORITY_MAX = 100
# Hard-gate category: the scheduler parks the task in NEEDS_APPROVAL.
_HARD_GATE_CATEGORY = 1
# Payload keys the ephemeral dispatcher reads as spawn controls
# (agents/_supervisor_ephemeral.py spawn_ephemeral_llm: the budget cap, the
# timeout and extra --add-dir roots of a --dangerously-skip-permissions run).
# A "_"-prefixed key is scheduler-owned (``_frozen_file_hits`` is written with
# setdefault, so a pre-set empty list would hide the frozen-file evidence).
_RESERVED_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "spawn_budget_usd", "spawn_timeout_sec", "additional_dirs",
})
_DEFAULT_TASK_REPLY = "Filed via LLM parse."
# A raw stdout scan never looks for more JSON objects than this.
_MAX_JSON_CANDIDATES = 64


class _UnusableLLMReply(Exception):
    """The LLM envelope is an error or carries nothing usable; ``parse``
    logs the reason and files the input as ``user-unparsed``."""


def _llm_owner(value: Any) -> str:
    """A single agent digit 0-7 (int or str), else ``"7"``. A bool lands
    on "7" too: ``str(True)`` is not an agent id."""
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str) and value in _AGENT_IDS:
        return value
    return "7"


def _llm_priority(value: Any) -> int:
    """An integral number (never bool or str), clamped to the LLM band;
    anything else is the default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _LLM_DEFAULT_PRIORITY
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return _LLM_DEFAULT_PRIORITY
        value = int(value)
    return max(_LLM_PRIORITY_MIN, min(_LLM_PRIORITY_MAX, value))


def _llm_categories(value: Any) -> list[int]:
    """Integer categories from a list (never bool), first occurrence kept."""
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        if isinstance(item, int) and not isinstance(item, bool) and item not in out:
            out.append(item)
    return out


def _llm_payload(value: Any) -> dict[str, Any]:
    """The model's payload minus spawn-control and scheduler-owned keys."""
    if not isinstance(value, dict):
        return {}
    return {
        k: v for k, v in value.items()
        if isinstance(k, str)
        and k not in _RESERVED_PAYLOAD_KEYS
        and not k.startswith("_")
    }


def _envelope_text(envelope: Any) -> str:
    """The model text out of a spawn envelope, or ``_UnusableLLMReply``.

    Shapes: ``{"ok": ..., "result": {"result": "<model text>", "is_error":
    ...}}`` from both the ephemeral CLI and the warm session; the ephemeral
    path substitutes ``{"raw_stdout": ...}`` when stdout was not JSON.
    """
    if not isinstance(envelope, dict):
        raise _UnusableLLMReply(f"envelope is {type(envelope).__name__}")
    if envelope.get("ok") is False:
        raise _UnusableLLMReply("envelope ok=false")
    raw = envelope.get("result")
    if isinstance(raw, dict):
        if raw.get("is_error") is True:
            raise _UnusableLLMReply("envelope is_error=true")
        if "result" in raw:
            text = raw["result"]
        elif "raw_stdout" in raw:
            # `--output-format json` always prints JSON, so non-JSON stdout is
            # the CLI talking (an error, a banner), not the model. Only a JSON
            # object inside it is used.
            text = raw["raw_stdout"]
            if not isinstance(text, str) or _first_json_object(text) is None:
                raise _UnusableLLMReply("non-JSON stdout")
        else:
            raise _UnusableLLMReply("envelope result has no text")
    else:
        # A bare string result is the old pre-envelope shape: the model's
        # text could equally be the CLI's error line, so it is not shown.
        raise _UnusableLLMReply(f"envelope result is {type(raw).__name__}")
    if not isinstance(text, str):
        raise _UnusableLLMReply(f"model text is {type(text).__name__}")
    return text


def _first_json_object(text: str) -> dict[str, Any] | None:
    """The first ``{...}`` in ``text`` that decodes as a JSON object.

    The old ``\\{.*\\}`` DOTALL search spanned from the FIRST brace to the
    LAST, so prose braces on either side of the model's object made it
    undecodable and the raw JSON was shown as prose.
    """
    decoder = json.JSONDecoder()
    pos = text.find("{")
    tries = 0
    while pos != -1 and tries < _MAX_JSON_CANDIDATES:
        tries += 1
        try:
            obj, _end = decoder.raw_decode(text, pos)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            return obj
        pos = text.find("{", pos + 1)
    return None


def _log_cause(prefix: str, exc: BaseException) -> None:
    """Log an LLM-path failure: type name plus redacted, control-escaped
    text, so neither a secret nor a forged log line reaches the log."""
    try:
        detail = scrub_log(redact_secrets(str(exc)))
    except Exception:  # noqa: BLE001 - an unprintable cause never costs the reply
        detail = "<unprintable>"
    logger.warning("%s: %s: %s", prefix, type(exc).__name__, detail)


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
        # /api/input passes a str; any other type is treated as no input
        # rather than raising AttributeError on .strip().
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            return ParseResult(reply="(empty input)", intent="chitchat")

        # Destructive phrases always go to hard gate.
        if _RE_DESTRUCTIVE.search(text):
            tid = self._scheduler.file_task(
                op="user-destructive-request",
                owner_agent="1",
                priority=5,
                categories=[_HARD_GATE_CATEGORY],   # -> needs_explicit_approval
                payload={"user_text": text, "intent": "destructive"},
            ).id
            return ParseResult(
                filed=[tid],
                reply=("Destructive request detected; filed for explicit "
                       "approval. Check the queue and approve via the UI "
                       "if you meant it."),
                intent="destructive",
            )

        # Generic note -> Agent 4 for later. Anchored, so it wins over the
        # keyword searches below (a note that mentions "audit" or "queue").
        m = _RE_NOTE.match(text) if _RE_NOTE_WORD.match(text) else None
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

        # Direct agent command: "Agent 6, audit this file". Anchored, so it
        # wins over the status search (an order that mentions "status").
        m = _RE_AGENT_DIRECT.match(text) if _RE_AGENT_WORD.match(text) else None
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

        # Status / queue summary - no task, just prose.
        if _RE_STATUS.search(text):
            snap = self._scheduler.snapshot()
            summary = ", ".join(f"{k}={v}" for k, v in sorted(snap["by_status"].items()))
            return ParseResult(
                reply=f"Queue: {snap['total']} total - {summary or '(empty)'}.",
                intent="status",
            )

        # Restart RC.
        if _RE_RESTART_RC.match(text):
            # AUDIT 2026-04-28 (4.3): atomic-write so the supervisor's poll
            # loop never reads a half-written trigger.
            from core.polled_json import atomic_write_text
            trigger = _PROJECT_ROOT / "restart_trigger.txt"
            atomic_write_text(
                trigger,
                f"user-request-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
            )
            return ParseResult(
                reply="RC restart trigger written. The existing RC supervisor will pick it up within ~1s.",
                intent="restart_rc",
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
                            '{"reply":"..."}\n\n'
                            "Task (must use one of the allowed ops):\n"
                            '{"task":{"op":"<one-of-allowed>",'
                            '"owner_agent":"<0-7>",'
                            '"priority":50,"payload":{...}},'
                            '"reply":"<short confirmation>"}\n\n'
                            f"Allowed op values: {allowed}. If no "
                            "allowed op fits, return either a "
                            "conversational reply OR "
                            '{"task":{"op":"user-unparsed",'
                            '"owner_agent":"7","priority":80,'
                            '"payload":{"reason":"..."}}}. '
                            "DO NOT invent op names. Do not use tools."
                        ),
                        "allowed_ops": allowed,
                        "spawn_budget_usd": 0.10,
                        "spawn_timeout_sec": 60,
                    },
                )
                return self._consume_llm_result(text, result)
            except _UnusableLLMReply as e:
                logger.warning("LLM fallback unusable: %s", scrub_log(str(e)))
            except Exception as e:  # noqa: BLE001 - any spawn failure files the input
                _log_cause("LLM fallback failed", e)

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
    def _consume_llm_result(self, user_text: str, llm_envelope: Any) -> ParseResult:
        """Interpret the JSON envelope returned by an ephemeral Haiku call.

        Raises ``_UnusableLLMReply`` for an error envelope or a reply with
        nothing usable; ``parse`` then files the input as ``user-unparsed``.
        Validation happens before ``file_task``, so nothing is filed twice.
        """
        text_out = _envelope_text(llm_envelope)
        parsed = _first_json_object(text_out)

        if parsed is None:
            # LLM gave prose - surface it as the reply.
            prose = text_out.strip()
            if not prose:
                raise _UnusableLLMReply("empty model text")
            return ParseResult(reply=prose, intent="chitchat", used_llm=True)

        task = parsed.get("task")
        if isinstance(task, dict):
            raw_op = task.get("op", "user-llm-task")
            raw_op = raw_op if isinstance(raw_op, str) else repr(raw_op)
            # Round 43: coerce fabricated ops. Anything outside the
            # allowed vocabulary lands as ``user-unparsed`` so it can't
            # reach a deterministic agent that lacks a handler.
            if raw_op in LLM_ALLOWED_OPS:
                op = raw_op
                owner = _llm_owner(task.get("owner_agent", "7"))
                priority = _llm_priority(task.get("priority", _LLM_DEFAULT_PRIORITY))
                fabricated = False
            else:
                logger.warning(
                    "LLM fabricated op %s not in allowed vocabulary - "
                    "coercing to user-unparsed",
                    scrub_log(repr(raw_op)[:200]),
                )
                op = "user-unparsed"
                owner = "7"
                priority = 80
                fabricated = True
            categories = _llm_categories(task.get("categories"))
            if op == "user-destructive-request" and _HARD_GATE_CATEGORY not in categories:
                categories.append(_HARD_GATE_CATEGORY)
            # Provenance keys are written LAST so the model cannot overwrite them.
            payload = {
                **_llm_payload(task.get("payload")),
                "user_text": user_text,
                "llm_derived": True,
                "llm_proposed_op": raw_op,
                "op_coerced": fabricated,
            }
            tid = self._scheduler.file_task(
                op=op,
                owner_agent=owner,
                priority=priority,
                categories=categories,
                payload=payload,
            ).id
            reply = parsed.get("reply")
            if not isinstance(reply, str) or not reply.strip():
                reply = _DEFAULT_TASK_REPLY
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

        reply = parsed.get("reply")
        if isinstance(reply, str) and reply.strip():
            return ParseResult(reply=reply, intent="chitchat", used_llm=True)

        # A JSON object with neither a task object nor a usable reply: the
        # raw JSON is not prose for the operator; the input gets filed.
        raise _UnusableLLMReply("JSON reply has no task object and no reply")
