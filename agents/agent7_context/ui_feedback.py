"""Round 42 - Agent 7 UI-feedback intent.

Sim-mode dashboard chat: the iPad's input bar, when the page loaded
with ``?sim=<fixture>``, routes here instead of the general
:class:`InputParser`. Scope is strictly *dashboard UI* - CSS, HTML,
layout, colors, and dashboard JS behavior. Coach output, analyzer
logic, agent framework code, secrets: all out of scope (refused with
a pointer to normal flow).

Every proposed edit is whitelist-guarded against
``agent4_coach_mentor.ui_applier.ALLOWED_PATHS``. Any path outside
that list causes an immediate refusal, *even if the user explicitly
asks for it*. Bypass flow: ``bypass dev: <text>`` on the user side
sets ``user_override=True`` on the filed task so it dispatches without
approval - but the whitelist still applies.

Two-stage parse, mirroring :class:`InputParser`:
  1. Fast rule-based handlers for common requests (font size, color
     token swaps on the CSS palette, CSS-variable tweaks).
  2. LLM fallback (same ``llm_spawn`` callable the regular parser
     uses) for nuanced or novel changes.

Both return the same :class:`UIProposalResult` shape so the supervisor
can serialize one envelope regardless of path.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agents.agent1_lead import Scheduler
from agents.agent4_coach_mentor.ui_applier import (
    ALLOWED_DIR_PREFIXES,
    ALLOWED_PATHS,
    _is_path_allowed,
)

logger = logging.getLogger("agent7.ui_feedback")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Messages clearly outside UI scope - refuse with pointer.
_RE_OFF_TOPIC = re.compile(
    r"\b(analyzer|kda\s+threshold|coach\s+prompt|ingest|reconcile|"
    r"scheduler|agent\s*[024567]|claude|llm|haiku|sonnet|supervisor|"
    r"systemd|cron|api\s+key|secret|credential)\b",
    re.IGNORECASE,
)

# Direct-apply bypass token - stripped from text; caller notified via
# ``bypass_dev=True`` in the result.
_RE_BYPASS = re.compile(r"^\s*bypass\s+dev\s*[:\-]?\s*", re.IGNORECASE)

# Rule-based handlers - each returns (reply, changes or []) if it can
# handle the text, or (None, []) to pass through.

_RE_FONT_BUMP = re.compile(
    r"\b(bigger|larger|increase|bump|raise|grow)\b.*\b(font|text|type)\b"
    r"|\b(font|text|type).*\b(bigger|larger|increase)\b",
    re.IGNORECASE,
)
_RE_FONT_SHRINK = re.compile(
    r"\b(smaller|shrink|decrease|reduce|tighten)\b.*\b(font|text|type)\b"
    r"|\b(font|text|type).*\b(smaller|shrink|decrease)\b",
    re.IGNORECASE,
)
_RE_PCT = re.compile(r"(\d{1,2})\s*(?:%|percent|pct)")


@dataclass
class UIProposalResult:
    """Return type for every parse path, including refusals."""
    filed: list[str] = field(default_factory=list)
    reply: str = ""
    intent: str = "ui_feedback"
    proposed_changes: list[dict] = field(default_factory=list)
    refused: bool = False
    refused_reason: str = ""
    bypass_dev: bool = False
    used_llm: bool = False


def _refusal(reason: str) -> UIProposalResult:
    return UIProposalResult(
        refused=True,
        refused_reason=reason,
        reply=(
            f"I'm scoped to dashboard UI only while you're in sim mode "
            f"({reason}). Exit sim mode and re-send for the normal flow, "
            f"or restate the ask in UI-design terms."
        ),
        intent="ui_feedback_refused",
    )


class UIFeedbackParser:
    def __init__(
        self,
        scheduler: Scheduler | None = None,
        llm_spawn: Callable[[str, str, str, dict], dict] | None = None,
    ) -> None:
        self._scheduler = scheduler or Scheduler()
        self._llm_spawn = llm_spawn

    # ---- public entry point ----------------------------------------
    def parse(
        self,
        text: str,
        history: list[dict] | None = None,
        sim_fixture: str | None = None,
    ) -> UIProposalResult:
        text = (text or "").strip()
        if not text:
            return UIProposalResult(
                reply="(empty input)", intent="ui_feedback_empty",
            )

        # Bypass-dev prefix - strip and flag.
        bypass = False
        m_bypass = _RE_BYPASS.match(text)
        if m_bypass:
            text = text[m_bypass.end():].strip()
            bypass = True
            if not text:
                return UIProposalResult(
                    reply="(bypass dev prefix with no request - nothing to do)",
                    intent="ui_feedback_empty",
                    bypass_dev=True,
                )

        # Off-topic guard - refuse before any rule tries to match.
        off = _RE_OFF_TOPIC.search(text)
        if off:
            r = _refusal(f"detected non-UI scope keyword {off.group(0)!r}")
            r.bypass_dev = bypass
            return r

        # Rule-based handlers.
        result = (
            self._try_font_size(text)
            or self._try_explicit_color(text)
        )
        if result is None:
            # LLM fallback.
            result = self._try_llm_fallback(text, history or [], sim_fixture)

        if result is None:
            # Couldn't produce a proposal - file a diagnostic task so we
            # see what's missing in the rule set, but don't apply anything.
            tid = self._scheduler.file_task(
                op="ui-feedback-unhandled",
                owner_agent="7",
                priority=80,
                payload={
                    "user_text": text,
                    "sim_fixture": sim_fixture,
                    "history_len": len(history or []),
                },
            ).id
            return UIProposalResult(
                filed=[tid],
                reply=(
                    "I heard you but I don't have a rule that fits that yet. "
                    "Filed as ui-feedback-unhandled for review."
                ),
                intent="ui_feedback_unhandled",
                bypass_dev=bypass,
            )

        # Pre-flight whitelist - should already be clean from the rules,
        # but double-check so a bad LLM answer never slips through.
        bad = [c for c in result.proposed_changes
               if not _is_path_allowed(c.get("file", ""))]
        if bad:
            logger.warning("ui_feedback produced off-whitelist change: %s", bad)
            return _refusal("proposed file outside the UI whitelist")

        # File the proposal. Without bypass, this is a standard ready
        # task (deterministic ui-proposal) that the supervisor auto-
        # dispatches because ui-proposal is in DETERMINISTIC_OPS -
        # BUT without ``user_override`` the scheduler may still gate
        # on category=1/frozen-file. With bypass_dev, we set the
        # override so the task ships straight through.
        tid = self._scheduler.file_task(
            op="ui-proposal",
            owner_agent="5",          # agent 5 owns UI substrate
            priority=40,
            categories=[],
            payload={
                "changes": result.proposed_changes,
                "user_text": text,
                "sim_fixture": sim_fixture,
                "bypass_dev": bypass,
                "filed_by": "agent7",
            },
            user_override=bypass,
        ).id
        result.filed = [tid]
        result.bypass_dev = bypass
        return result

    # ---- rule: font size bumps / shrinks ---------------------------
    def _try_font_size(self, text: str) -> UIProposalResult | None:
        bump = bool(_RE_FONT_BUMP.search(text))
        shrink = bool(_RE_FONT_SHRINK.search(text))
        if not (bump or shrink):
            return None
        pct_m = _RE_PCT.search(text)
        pct = int(pct_m.group(1)) if pct_m else (25 if bump else 15)
        # Direction multiplier.
        mult = 1.0 + (pct / 100.0) if bump else 1.0 - (pct / 100.0)
        mult = max(0.5, min(2.0, mult))     # clamp

        css_path = _PROJECT_ROOT / "web" / "css" / "panels" / "base.css"
        try:
            css = css_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("couldn't read base.css: %s", e)
            return None

        # Live base font lives in a bare `body { ... font-size: Npx }`
        # rule (panels/base.css); the legacy dead dashboard.css used
        # `html, body { ... }`. Accept either form.
        old_base_match = re.search(
            r"(?:html\s*,\s*)?body\s*\{[^}]*?font-size:\s*(\d+(?:\.\d+)?)px",
            css, re.DOTALL,
        )
        if not old_base_match:
            return None
        old_base = float(old_base_match.group(1))
        new_base = max(10.0, min(40.0, round(old_base * mult)))
        if abs(new_base - old_base) < 0.5:
            return UIProposalResult(
                reply=(
                    f"Font base is already ~{old_base:.0f}px - {pct}% change "
                    f"lands within 0.5 px. No-op."
                ),
                intent="ui_feedback_noop",
            )

        # Rewrite every ``font-size: Npx`` occurrence proportionally.
        ratio = new_base / old_base

        def _rescale(m: re.Match) -> str:
            num = float(m.group(1))
            scaled = max(8.0, round(num * ratio))
            return f"font-size: {int(scaled)}px"

        new_css = re.sub(r"font-size:\s*(\d+(?:\.\d+)?)px", _rescale, css)
        verb = "up" if bump else "down"
        return UIProposalResult(
            reply=(
                f"Scaling every font-size token {verb} by {pct}% "
                f"(base {old_base:.0f}px → {int(new_base)}px). Proposed - "
                f"review + approve to apply."
            ),
            proposed_changes=[{
                "file": "web/css/panels/base.css",
                "content": new_css,
                "summary": f"font-size tokens × {ratio:.3f}",
            }],
            intent="ui_feedback_font_scale",
        )

    # ---- rule: explicit color var swap -----------------------------
    _RE_SET_VAR = re.compile(
        r"(?:set|change|make)\s+(?:the\s+)?--(?P<var>[a-z\-]+)\s+"
        r"(?:to\s+)?(?P<val>#[0-9a-fA-F]{3,8}|rgb[a]?\([^)]+\))",
        re.IGNORECASE,
    )

    def _try_explicit_color(self, text: str) -> UIProposalResult | None:
        m = self._RE_SET_VAR.search(text)
        if not m:
            return None
        var = m.group("var").lower()
        val = m.group("val")
        css_path = _PROJECT_ROOT / "web" / "css" / "panels" / "base.css"
        try:
            css = css_path.read_text(encoding="utf-8")
        except OSError:
            return None
        # Pattern inside :root block only - avoid touching media-query overrides.
        new_css, n = re.subn(
            rf"(--{re.escape(var)}\s*:\s*)[^;]+;",
            rf"\g<1>{val};",
            css,
            count=1,
        )
        if n == 0:
            return UIProposalResult(
                reply=f"No CSS var `--{var}` found in base.css - check the name.",
                intent="ui_feedback_noop",
            )
        return UIProposalResult(
            reply=(
                f"Changing `--{var}` → `{val}` in base.css. Proposed - "
                f"review + approve to apply."
            ),
            proposed_changes=[{
                "file": "web/css/panels/base.css",
                "content": new_css,
                "summary": f"--{var} = {val}",
            }],
            intent="ui_feedback_color_var",
        )

    # ---- LLM fallback ----------------------------------------------
    def _try_llm_fallback(
        self,
        text: str,
        history: list[dict],
        sim_fixture: str | None,
    ) -> UIProposalResult | None:
        if self._llm_spawn is None:
            return None
        allow_list = ", ".join(
            sorted(ALLOWED_PATHS)
            + [f"{p}<name>{sfx}" for p, sfx in ALLOWED_DIR_PREFIXES]
        )
        prompt_data = {
            "message": text,
            "sim_fixture": sim_fixture,
            "history": history[-5:],
            "allowed_files": sorted(ALLOWED_PATHS),
            "instruction": (
                "You are the UI-feedback channel for a dashboard. Scope is "
                "CSS/HTML/layout/color + dashboard JS behavior ONLY. Return "
                "JSON with either:\n"
                "  {\"reply\": \"prose\"}  - conversational answer\n"
                "  or {\"reply\": \"...\", \"changes\": [{\"file\": \"<path>\", "
                "\"content\": \"<FULL new file content>\", \"summary\": \"...\"}]}\n"
                f"Only these files may be proposed: {allow_list}.\n"
                "Never modify coach logic, analyzer, scheduler, API keys, or "
                "anything outside the whitelist - refuse with reply only."
            ),
            "spawn_budget_usd": 0.15,
            "spawn_timeout_sec": 60,
        }
        try:
            env = self._llm_spawn("7", "t-ui-feedback", "ui-feedback", prompt_data)
        except Exception as e:        # noqa: BLE001
            logger.warning("ui_feedback LLM fallback failed: %s", e)
            return None
        return self._consume_llm_result(env)

    def _consume_llm_result(self, env: dict[str, Any]) -> UIProposalResult | None:
        raw = env.get("result", {})
        text_out = (
            raw.get("result") if isinstance(raw, dict) else str(raw)
        ) or ""
        m = re.search(r"\{.*\}", text_out, re.DOTALL)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        reply = str(parsed.get("reply") or "")
        changes = parsed.get("changes") or []
        if not isinstance(changes, list):
            changes = []
        cleaned_changes: list[dict] = []
        for c in changes:
            if not isinstance(c, dict):
                continue
            file = str(c.get("file") or "").strip()
            content = c.get("content")
            if not file or not isinstance(content, str):
                continue
            cleaned_changes.append({
                "file": file,
                "content": content,
                "summary": str(c.get("summary") or ""),
            })
        return UIProposalResult(
            reply=reply or "(LLM returned empty reply)",
            proposed_changes=cleaned_changes,
            intent="ui_feedback_llm",
            used_llm=True,
        )
