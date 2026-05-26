"""Regression tests for the item-189 coach refactor (2026-05-25):

  1. The 4 in-game coach prompts no longer emit `Immediate:` / `Next:`
     prose - the Choices JSON array is the primary actionable surface.
  2. `web/js/panels/coach_choices.js` adds an `Alt+N` chip pill + a
     window-level Alt+1/Alt+2/Alt+3 keydown handler that activates the
     A/B/C chip respectively (same logic as click).
  3. `web/js/panels/right_now.js` hides #rn-immediate when
     `state.coach.choices.length > 0` so the chips visually occupy the
     primary slot under #rn-action.
  4. `coaches/brawl_coach.py` `_*_OUTPUT_KEYS` arrays no longer contain
     `"immediate"`.
  5. The CSS adds an `.rc-hotkey` pill rule + an `.rc-ack-bubble` toast
     rule (visible-feedback for keyboard-driven picks).

Grep-style smoke. Mirrors test_coach_choices_panel_dom.py + the
recently-added test_coach_prompt_format_safe.py.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL_JS = REPO / "web" / "js" / "panels" / "coach_choices.js"
PANEL_CSS = REPO / "web" / "css" / "panels" / "coach_choices.css"
RIGHT_NOW_JS = REPO / "web" / "js" / "panels" / "right_now.js"

SR_PROMPT = REPO / "coach_integration" / "_sr_prompt.py"
ARAM_COACH = REPO / "coaches" / "aram_coach.py"
ARENA_COACH = REPO / "coaches" / "arena_coach.py"
BRAWL_COACH = REPO / "coaches" / "brawl_coach.py"


class CoachPromptImmediateDroppedTests(unittest.TestCase):
    """The 4 in-game system prompts must not request the LLM emit a
    free-form `Immediate:` or `Next:` field anymore. Reduces token spend
    AND avoids the previously-truncated/blank prose slot that the chips
    now replace."""

    def test_sr_prompt_no_immediate_emit_instruction(self):
        src = SR_PROMPT.read_text(encoding="utf-8")
        # Pull out only the SR_SYSTEM_PROMPT block (ends at the
        # ARAM_SYSTEM_PROMPT marker).
        sr_block = src.split("ARAM_SYSTEM_PROMPT")[0]
        self.assertNotRegex(
            sr_block,
            r"^Immediate: <",
            "SR_SYSTEM_PROMPT still emits an `Immediate:` instruction "
            "to the LLM; drop it - choices is the primary slot now.",
        )
        self.assertNotRegex(
            sr_block, r"^Next: <",
            "SR_SYSTEM_PROMPT still emits a `Next:` instruction; drop it."
        )
        # Choices must be REQUIRED, not OPTIONAL.
        self.assertIn("Choices: <REQUIRED", sr_block)

    def test_aram_prompt_no_immediate_emit_instruction(self):
        src = ARAM_COACH.read_text(encoding="utf-8")
        # `_SYSTEM = """\n...OUTPUT FORMAT...Choices: <REQUIRED..."""` block.
        # Easier to scan the file for any line that LITERALLY starts
        # with `Immediate: <` (the prompt-instruction shape, not a code
        # comment).
        for line in src.splitlines():
            self.assertFalse(
                line.startswith("Immediate: <"),
                f"aram_coach.py has a leftover `Immediate: <...>` "
                f"prompt instruction: {line!r}",
            )

    def test_brawl_prompts_no_immediate_emit_instruction(self):
        src = BRAWL_COACH.read_text(encoding="utf-8")
        for line in src.splitlines():
            self.assertFalse(
                line.startswith("Immediate: <"),
                f"brawl_coach.py has a leftover `Immediate: <...>` "
                f"prompt instruction (likely in NB/URF/OFA prompt block): "
                f"{line!r}",
            )

    def test_arena_prompt_already_no_immediate(self):
        # Arena was already Choices-first (no Immediate). Pin so a future
        # refactor doesn't re-introduce a prose field by mistake.
        src = ARENA_COACH.read_text(encoding="utf-8")
        for line in src.splitlines():
            self.assertFalse(
                line.startswith("Immediate: <"),
                f"arena_coach.py somehow gained an `Immediate: <...>` "
                f"prompt instruction: {line!r}",
            )


class BrawlOutputKeysImmediateDroppedTests(unittest.TestCase):
    """`coaches/brawl_coach.py` `_*_OUTPUT_KEYS` arrays drive the
    `parse_fields(raw, output_keys)` parser. With `"immediate"` removed
    from the prompt, the parser key list MUST also drop it - otherwise
    the parser silently looks for a field the LLM no longer emits."""

    def test_output_keys_have_no_immediate(self):
        src = BRAWL_COACH.read_text(encoding="utf-8")
        # Three arrays:
        for name in ("_NB_OUTPUT_KEYS", "_URF_OUTPUT_KEYS", "_OFA_OUTPUT_KEYS"):
            self.assertIn(name, src, f"{name} declaration missing")
        # Slice the file around each definition and assert "immediate"
        # is not in the literal list.
        for name in ("_NB_OUTPUT_KEYS", "_URF_OUTPUT_KEYS", "_OFA_OUTPUT_KEYS"):
            idx = src.index(name)
            line_end = src.index("\n", idx)
            line = src[idx:line_end]
            self.assertNotIn(
                '"immediate"', line,
                f"{name} still lists `\"immediate\"` - drop it; the "
                f"prompt no longer emits that field.",
            )


class CoachChoicesAltHotkeyJsTests(unittest.TestCase):
    """ALT+1/2/3 wiring lives in coach_choices.js. The keydown handler
    must be bound at module load + check ev.altKey + map digit -> key
    A/B/C + call _postSelection (same as click)."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_kebab_to_digit_table(self):
        self.assertIn("_KEY_TO_DIGIT", self.js)
        # Map keys A->1, B->2, C->3 (object-literal substring match;
        # double-quote chars aren't word chars so \b won't fire there).
        for entry in ('A: "1"', 'B: "2"', 'C: "3"'):
            self.assertIn(
                entry, self.js,
                f"_KEY_TO_DIGIT entry `{entry}` missing",
            )

    def test_chip_renders_alt_hotkey_pill(self):
        # Each chip HTML includes an `Alt+N` pill so the operator can
        # see the binding without hovering.
        self.assertIn("rc-hotkey", self.js)
        self.assertIn('"Press Alt+', self.js)

    def test_keydown_listener_bound_on_window(self):
        self.assertIn("window.addEventListener", self.js)
        self.assertIn('"keydown"', self.js)

    def test_keydown_handler_checks_altkey(self):
        self.assertIn("ev.altKey", self.js)
        # Reject when ctrl/meta/shift also held.
        self.assertIn("ev.metaKey", self.js)
        self.assertIn("ev.ctrlKey", self.js)
        self.assertIn("ev.shiftKey", self.js)

    def test_keydown_handler_recognises_digit_1_2_3(self):
        for code in ("Digit1", "Digit2", "Digit3"):
            self.assertIn(code, self.js, f"{code} branch missing")

    def test_keydown_handler_calls_preventdefault(self):
        # Avoid hijacking by other browser/OS Alt+digit bindings.
        self.assertIn("preventDefault", self.js)

    def test_activate_chip_helper_shared_between_click_and_hotkey(self):
        # Refactor: both click + hotkey paths funnel through _activateChip.
        self.assertIn("_activateChip", self.js)

    def test_internal_exports_seam(self):
        # Test seam exposes the new handlers for direct unit tests if any
        # future jsdom harness wants to drive a synthetic Alt+1 event.
        self.assertIn("_onAltDigitKeydown", self.js)
        self.assertIn("_activateChip", self.js)
        self.assertIn("_KEY_TO_DIGIT", self.js)


class CoachChoicesCssAltHotkeyTests(unittest.TestCase):
    def setUp(self):
        self.css = PANEL_CSS.read_text(encoding="utf-8")

    def test_hotkey_pill_styled(self):
        self.assertIn(".rc-hotkey", self.css)

    def test_ack_toast_styled(self):
        self.assertIn(".rc-ack-bubble", self.css)
        self.assertIn(".rc-ack-bubble.show", self.css)

    def test_chips_stack_vertically_now(self):
        # Old layout was horizontal flex-wrap (gap:6px). The new layout
        # is a vertical column so chips occupy the immediate slot.
        self.assertIn("flex-direction: column", self.css)

    def test_chip_meets_hit_min_floor(self):
        self.assertIn("var(--hit-min", self.css)

    def test_chip_label_at_md_token(self):
        # Bumped from 13px hardcoded to --fs-md (18px v2.1 floor).
        self.assertIn("var(--fs-md", self.css)


class RightNowSuppressionTests(unittest.TestCase):
    """When state.coach.choices.length > 0, right_now.js must hide
    #rn-immediate so the chip mount (#rn-choices) visually occupies
    the slot directly under #rn-action."""

    def setUp(self):
        self.js = RIGHT_NOW_JS.read_text(encoding="utf-8")

    def test_hides_immediate_when_choices_present(self):
        self.assertIn("hasChoices", self.js)
        self.assertIn("RN.immediate.hidden", self.js)

    def test_choices_branch_short_circuits_arena_pregame(self):
        # The hasChoices guard must run BEFORE the arena/sr fallbacks
        # so a populated choices array always wins. Cheap order check.
        idx_hasc = self.js.index("hasChoices")
        idx_arena = self.js.index("if (arena)")
        # The new branch is inserted just before the arena guard.
        self.assertLess(idx_hasc, idx_arena)


if __name__ == "__main__":
    unittest.main()
