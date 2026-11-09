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
approval - but the whitelist still applies. ``dev`` must be a whole
word: ``bypass devtools ...`` is an ordinary request, not a bypass.

Two-stage parse, mirroring :class:`InputParser`:
  1. Fast rule-based handlers for common requests (font size, color
     token swaps on the CSS palette, CSS-variable tweaks).
  2. LLM fallback (same ``llm_spawn`` callable the regular parser
     uses) for nuanced or novel changes.

Both return the same :class:`UIProposalResult` shape so the supervisor
can serialize one envelope regardless of path. Only a result that
carries at least one change files a ``ui-proposal`` task: a no-op or a
conversational reply files nothing (the applier rejects an empty
proposal, so such a task could only fail at dispatch). A proposal is
validated as a whole before it is filed - whitelist, at most
``MAX_CHANGES`` entries, no duplicate file, each content within
``MAX_FILE_BYTES`` - and one bad entry refuses all of it.

Hardened in true-audit s144 cycle 182
(tests/test_ui_feedback_true_audit_s144t182.py).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agents.agent1_lead import Scheduler
from agents.agent4_coach_mentor.ui_applier import (
    ALLOWED_DIR_PREFIXES,
    ALLOWED_PATHS,
    MAX_CHANGES,
    UIApplyError,
    _is_path_allowed,
    _validate_content,
)
from agents.agent7_context.input_parser import (
    _envelope_text,
    _first_json_object,
    _UnusableLLMReplyError,
)
from core.log_scrub import redact_secrets, scrub_log

logger = logging.getLogger("agent7.ui_feedback")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_BASE_CSS_REL = "web/css/panels/base.css"

# Bounds on client-sent context. The history and fixture name come from
# the POST body unchecked (agents/_supervisor_http.py _handle_input) and
# are copied into the LLM prompt and the filed task payload.
_MAX_HISTORY_TURNS = 5
_MAX_HISTORY_KEYS = 8
_MAX_HISTORY_FIELD = 2000
_MAX_FIXTURE_CHARS = 128
_MAX_REPLY_CHARS = 4000
_MAX_SUMMARY_CHARS = 200
# A UI request is a sentence or two. The rule regexes use ".*" between
# two word sets, which is quadratic in the text length: at the 256 KiB
# body cap one request held the handler for minutes. Longer text is
# answered without running any rule or the LLM.
_MAX_TEXT_CHARS = 4000

# Smallest font size the rescale rule will shrink a token to. A token
# already below it is left where it is (never enlarged by a shrink).
_MIN_FONT_PX = 8.0

# Messages clearly outside UI scope - refuse with pointer.
_RE_OFF_TOPIC = re.compile(
    r"\b(analyzer|kda\s+threshold|coach\s+prompt|ingest|reconcile|"
    r"scheduler|agent\s*[024567]|claude|llm|haiku|sonnet|supervisor|"
    r"systemd|cron|api\s+key|secret|credential)\b",
    re.IGNORECASE,
)

# Direct-apply bypass token - stripped from text; caller notified via
# ``bypass_dev=True`` in the result. ``dev`` is a whole word: the
# override skips approval, so "bypass devtools" must not trigger it.
_RE_BYPASS = re.compile(
    r"^\s*bypass\s+dev(?![\w-])\s*(?:[:\-]\s*)?", re.IGNORECASE,
)

# Rule-based handlers - each returns a result if it can handle the
# text, or None to pass through.

# The noun is a whole word: font / text / type, optionally joined to
# "size" or "face" by nothing, "-" or "_" ("fontsize", "font-size",
# "font_size", "textsize", "typeface"), optionally plural. "context",
# "textbox" and "textual" are deliberately NOT font requests (the
# original pattern had no trailing word boundary and matched them).
_FONT_NOUN = r"\b(?:font|text|type)(?:[-_]?(?:size|face))?s?\b"
_RE_FONT_BUMP = re.compile(
    rf"\b(?:bigger|larger|increase|bump|raise|grow)\b.*{_FONT_NOUN}"
    rf"|{_FONT_NOUN}.*\b(?:bigger|larger|increase)\b",
    re.IGNORECASE,
)
_RE_FONT_SHRINK = re.compile(
    rf"\b(?:smaller|shrink|decrease|reduce|tighten)\b.*{_FONT_NOUN}"
    rf"|{_FONT_NOUN}.*\b(?:smaller|shrink|decrease)\b",
    re.IGNORECASE,
)
# A whole number, not the tail of a longer one: "150%" is 150, never
# 50; "100%" is 100, never 0; "1.5%" is 1.5, never 5.
_RE_PCT = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percents?\b|pct\b)", re.IGNORECASE,
)
# Any larger request is clamped by the x0.5 - x2.0 multiplier anyway.
_MAX_PCT = 1000

# The live base font is a bare ``body { ... font-size: Npx }`` rule;
# the legacy dashboard.css used ``html, body { ... }``. The lookbehind
# keeps ``tbody {`` and ``.somebody {`` from passing as the base.
_RE_BASE_FONT = re.compile(
    r"(?<![\w.#-])(?:html\s*,\s*)?body\s*\{[^}]*?font-size:\s*(\d+(?:\.\d+)?)px",
    re.DOTALL,
)
_RE_FONT_TOKEN = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px")

# A colour value the rule will write into CSS. Strict on purpose: the
# value is spliced into a stylesheet, so nothing that can close a
# declaration or a block (";", "}") and no backslash gets through.
_HEX_COLOR = r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z])"
_RGB_COLOR = r"rgba?\(\s*[0-9.%\s,/+-]+\)"


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


def _log_warning(prefix: str, detail: Any) -> None:
    """Log ``detail`` redacted and control-escaped, so neither a secret
    nor a forged log line reaches the log."""
    try:
        text = scrub_log(redact_secrets(str(detail)))
    except Exception:  # noqa: BLE001 - an unprintable detail never costs the reply
        text = "<unprintable>"
    logger.warning("%s: %s", prefix, text)


def _clean_history(history: Any) -> list[dict]:
    """The last few client-sent turns, as small flat dicts.

    Non-dict turns are dropped; each kept turn keeps at most
    ``_MAX_HISTORY_KEYS`` str-keyed scalar fields, strings clipped to
    ``_MAX_HISTORY_FIELD`` characters.
    """
    if not isinstance(history, list):
        return []
    turns = [h for h in history if isinstance(h, dict)][-_MAX_HISTORY_TURNS:]
    out: list[dict] = []
    for turn in turns:
        clean: dict[str, Any] = {}
        for key, value in turn.items():
            if len(clean) >= _MAX_HISTORY_KEYS:
                break
            if not isinstance(key, str):
                continue
            if isinstance(value, str):
                clean[key[:64]] = value[:_MAX_HISTORY_FIELD]
            elif value is None or isinstance(value, (bool, int, float)):
                clean[key[:64]] = value
        out.append(clean)
    return out


def _clean_fixture(sim_fixture: Any) -> str | None:
    if not isinstance(sim_fixture, str):
        return None
    sim_fixture = sim_fixture.strip()[:_MAX_FIXTURE_CHARS]
    return sim_fixture or None


def _proposal_problem(changes: list[dict]) -> str | None:
    """Why ``changes`` cannot be filed, or None when it can.

    Runs the applier's own pre-write checks (count, whitelist, the
    per-file ``_validate_content`` - NUL, UTF-8, size, the .js sanity
    gates - and its case-folded duplicate rule) so a proposal it would
    reject is never written into the queue log. Only the filesystem
    checks (symlink containment, prior-bytes read) are left to apply time.
    """
    if len(changes) > MAX_CHANGES:
        return f"proposal carries {len(changes)} changes (max {MAX_CHANGES})"
    seen: set[str] = set()
    for change in changes:
        rel = change.get("file")
        if not _is_path_allowed(rel):
            return "proposed file outside the UI whitelist"
        # The applier keys on os.path.normcase of the target: on Windows
        # "A.css" and "a.css" are one file.
        key = os.path.normcase(rel)
        if key in seen:
            return "proposal names the same file twice"
        seen.add(key)
        try:
            _validate_content(rel, change["content"])
        except UIApplyError as exc:
            return f"proposed content rejected: {exc}"
    return None


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
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            return UIProposalResult(
                reply="(empty input)", intent="ui_feedback_empty",
            )
        if len(text) > _MAX_TEXT_CHARS:
            return UIProposalResult(
                reply=(
                    f"That message is too long for a UI request (over "
                    f"{_MAX_TEXT_CHARS} characters) - send a shorter ask."
                ),
                intent="ui_feedback_too_long",
            )
        history_len = len(history) if isinstance(history, list) else 0
        clean_history = _clean_history(history)
        sim_fixture = _clean_fixture(sim_fixture)

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
            result = self._try_llm_fallback(text, clean_history, sim_fixture)

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
                    "history_len": history_len,
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

        result.bypass_dev = bypass
        # A refusal, a no-op or a conversational reply carries no
        # change: there is nothing to file.
        if result.refused or not result.proposed_changes:
            return result

        # Pre-flight: whitelist, count, duplicates, size - should already
        # be clean from the rules, but checked so a bad LLM answer never
        # reaches the queue. Only file names are logged, never content.
        problem = _proposal_problem(result.proposed_changes)
        if problem:
            _log_warning(
                "ui_feedback refused a proposal",
                f"{problem}; files="
                f"{[c.get('file') for c in result.proposed_changes]!r}",
            )
            refused = _refusal(problem)
            refused.bypass_dev = bypass
            refused.used_llm = result.used_llm
            return refused

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
        return result

    # ---- rule: font size bumps / shrinks ---------------------------
    def _read_base_css(self) -> str | None:
        css_path = _PROJECT_ROOT / _BASE_CSS_REL
        try:
            return css_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            _log_warning("couldn't read base.css", f"{type(e).__name__}: {e}")
            return None

    def _try_font_size(self, text: str) -> UIProposalResult | None:
        bump = bool(_RE_FONT_BUMP.search(text))
        shrink = bool(_RE_FONT_SHRINK.search(text))
        if not (bump or shrink):
            return None
        pct_m = _RE_PCT.search(text)
        if pct_m:
            # An integer part longer than _MAX_PCT's is clamped without
            # float(): a huge one is still a request, not an error.
            whole = pct_m.group(1).split(".")[0]
            pct = (
                float(_MAX_PCT) if len(whole) > 4
                else min(float(pct_m.group(1)[:16]), float(_MAX_PCT))
            )
        else:
            pct = 25.0 if bump else 15.0
        # Direction multiplier.
        mult = 1.0 + (pct / 100.0) if bump else 1.0 - (pct / 100.0)
        mult = max(0.5, min(2.0, mult))     # clamp

        css = self._read_base_css()
        if css is None:
            return None
        old_base_match = _RE_BASE_FONT.search(css)
        if not old_base_match:
            return None
        old_base = float(old_base_match.group(1))
        if old_base <= 0:
            # No proportional rescale exists from a 0px base.
            return None
        new_base = max(10.0, min(40.0, round(old_base * mult)))
        if abs(new_base - old_base) < 0.5:
            return UIProposalResult(
                reply=(
                    f"Font base is already ~{old_base:.0f}px - {pct:g}% change "
                    f"lands within 0.5 px. No-op."
                ),
                intent="ui_feedback_noop",
            )

        # Rewrite every ``font-size: Npx`` occurrence proportionally.
        ratio = new_base / old_base

        def _rescale(m: re.Match) -> str:
            num = float(m.group(1))
            # A token below the floor stays where it is: a shrink never
            # enlarges it and a 0px (hidden) token stays 0px.
            scaled = max(min(num, _MIN_FONT_PX), round(num * ratio))
            return f"font-size: {scaled:g}px"

        new_css = _RE_FONT_TOKEN.sub(_rescale, css)
        verb = "up" if bump else "down"
        return UIProposalResult(
            reply=(
                # The effective change, after rounding and the 10-40px base
                # clamp - not the requested pct, which may be far larger.
                f"Scaling every font-size token {verb} by "
                f"{round(abs(ratio - 1.0) * 100)}% "
                f"(base {old_base:.0f}px -> {int(new_base)}px). Proposed - "
                f"review + approve to apply."
            ),
            proposed_changes=[{
                "file": _BASE_CSS_REL,
                "content": new_css,
                "summary": f"font-size tokens x {ratio:.3f}",
            }],
            intent="ui_feedback_font_scale",
        )

    # ---- rule: explicit color var swap -----------------------------
    _RE_SET_VAR = re.compile(
        # No leading \b: "reset --x to #fff" is a set request too.
        r"(?:set|change|make)\s+(?:the\s+)?--(?P<var>[a-z0-9_\-]+)\s+"
        rf"(?:to\s+)?(?P<val>{_HEX_COLOR}|{_RGB_COLOR})",
        # ASCII: without it IGNORECASE folds U+017F and U+212A into s / k.
        re.IGNORECASE | re.ASCII,
    )

    def _try_explicit_color(self, text: str) -> UIProposalResult | None:
        m = self._RE_SET_VAR.search(text)
        if not m:
            return None
        var = m.group("var").lower()
        val = m.group("val")
        css = self._read_base_css()
        if css is None:
            return None
        # The FIRST declaration of the var in the file (base.css declares
        # its palette in :root before any media query). The value stops at
        # ";" or at the end of the block, so a last declaration without a
        # ";" cannot swallow the next rule; the lookbehind keeps
        # "--text" from matching inside "--hud--text". A function
        # replacement, so the value is never read as a re template.
        decl = re.compile(
            rf"(?<![\w-])(--{re.escape(var)}\s*:\s*)([^;{{}}]*?)(\s*)(?=[;}}]|$)"
        )
        new_css, n = decl.subn(
            lambda d: f"{d.group(1)}{val}{d.group(3)}", css, count=1,
        )
        if n == 0:
            return UIProposalResult(
                reply=f"No CSS var `--{var}` found in base.css - check the name.",
                intent="ui_feedback_noop",
            )
        return UIProposalResult(
            reply=(
                f"Changing `--{var}` -> `{val}` in base.css. Proposed - "
                f"review + approve to apply."
            ),
            proposed_changes=[{
                "file": _BASE_CSS_REL,
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
            "history": history[-_MAX_HISTORY_TURNS:],
            "allowed_files": sorted(ALLOWED_PATHS),
            "instruction": (
                "You are the UI-feedback channel for a dashboard. Scope is "
                "CSS/HTML/layout/color + dashboard JS behavior ONLY. Return "
                "JSON with either:\n"
                '  {"reply": "prose"}  - conversational answer\n'
                '  or {"reply": "...", "changes": [{"file": "<path>", '
                '"content": "<FULL new file content>", "summary": "..."}]}\n'
                f"Only these files may be proposed: {allow_list}.\n"
                "Never modify coach logic, analyzer, scheduler, API keys, or "
                "anything outside the whitelist - refuse with reply only."
            ),
            "spawn_budget_usd": 0.15,
            "spawn_timeout_sec": 60,
        }
        try:
            env = self._llm_spawn("7", "t-ui-feedback", "ui-feedback", prompt_data)
        except Exception as e:        # noqa: BLE001 - any spawn failure degrades to unhandled
            _log_warning("ui_feedback LLM fallback failed", f"{type(e).__name__}: {e}")
            return None
        return self._consume_llm_result(env)

    def _consume_llm_result(self, env: Any) -> UIProposalResult | None:
        """The model's reply as a result, or None when nothing is usable.

        An error envelope (``ok`` false, ``is_error`` true, a non-dict or
        a bare-string result) is never shown: it may be the CLI's raw API
        error. A malformed change entry refuses the whole proposal rather
        than filing the well-formed rest of it.
        """
        try:
            text_out = _envelope_text(env)
        except _UnusableLLMReplyError as exc:
            _log_warning("ui_feedback LLM reply unusable", exc)
            return None
        parsed = _first_json_object(text_out)
        if parsed is None:
            return None
        reply = parsed.get("reply")
        reply = reply.strip()[:_MAX_REPLY_CHARS] if isinstance(reply, str) else ""
        changes = parsed.get("changes")
        if changes is None:
            changes = []
        if not isinstance(changes, list):
            return self._llm_refusal("LLM proposed a malformed change list")
        cleaned_changes: list[dict] = []
        for c in changes:
            file = c.get("file") if isinstance(c, dict) else None
            content = c.get("content") if isinstance(c, dict) else None
            if not isinstance(file, str) or not file.strip() \
                    or not isinstance(content, str):
                return self._llm_refusal("LLM proposed a malformed change")
            summary = c.get("summary")
            cleaned_changes.append({
                "file": file.strip(),
                "content": content,
                "summary": (
                    summary[:_MAX_SUMMARY_CHARS] if isinstance(summary, str) else ""
                ),
            })
        if not reply and not cleaned_changes:
            return None
        return UIProposalResult(
            reply=reply or "(LLM returned empty reply)",
            proposed_changes=cleaned_changes,
            intent="ui_feedback_llm",
            used_llm=True,
        )

    @staticmethod
    def _llm_refusal(reason: str) -> UIProposalResult:
        _log_warning("ui_feedback refused an LLM reply", reason)
        r = _refusal(reason)
        r.used_llm = True
        return r
