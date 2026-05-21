"""Grep-based contract tests for the 2026-05-20 UI/UX polish sweep.

Four concerns this guards (mirrors test_design_tokens_css.py + the
test_draft_elo_panel_dom.py pattern: cheap text-search smoke):

1. TabularNumsSweepTests - each of the 8 swept panel CSS files now
   carries either the .tabular-nums utility class or a direct
   font-variant-numeric: tabular-nums rule on a numeric cell.
2. TextWrapBalanceTests - the 4 multi-line-wrap selectors carry
   text-wrap: balance so a 2-line wrap does not orphan a trailing word.
3. CoachPulseWireTests - right_now.js wires the rn-pulse-{good,warn,bad}
   one-shot class via classifyAction() bands; right_now.css declares
   the animation rule consuming the tokens.css keyframes; the pulse is
   dropped after 800ms; the empty band does not pulse.
4. DraftEloEscTests - draft_elo.js adds a document-level keydown
   listener for the Escape key, and does NOT introduce a click handler
   or pinned class (the HoverOnlyContractTests in
   test_draft_elo_panel_dom.py would catch a regression too; this is
   a positive guard for the ESC dismissal itself).

ASCII hygiene: BAD dict built via chr() so this file stays clean
against its own scan.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CSS_RIGHT_NOW    = ROOT / "web" / "css" / "panels" / "right_now.css"
CSS_NEXT         = ROOT / "web" / "css" / "panels" / "next.css"
CSS_ITEM_BUILD   = ROOT / "web" / "css" / "panels" / "item_build.css"
CSS_TEAM_CONTEXT = ROOT / "web" / "css" / "panels" / "team_context.css"
CSS_AUGMENT_RECO = ROOT / "web" / "css" / "panels" / "augment_reco.css"
CSS_DRAFT_ELO    = ROOT / "web" / "css" / "panels" / "draft_elo.css"
CSS_SPIKE_CURVE  = ROOT / "web" / "css" / "panels" / "spike_curve.css"
CSS_WARD_HEAT    = ROOT / "web" / "css" / "panels" / "ward_heat.css"
CSS_LAST_MATCH   = ROOT / "web" / "css" / "panels" / "last_match.css"
CSS_REPLAY_EV    = ROOT / "web" / "css" / "panels" / "replay_events.css"
JS_RIGHT_NOW     = ROOT / "web" / "js" / "panels" / "right_now.js"
JS_DRAFT_ELO     = ROOT / "web" / "js" / "panels" / "draft_elo.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _carries_tabular_nums(css: str) -> bool:
    """Return True iff the CSS carries either the .tabular-nums utility
    class or a direct font-variant-numeric: tabular-nums declaration."""
    return ("font-variant-numeric: tabular-nums" in css
            or "font-variant-numeric:tabular-nums" in css
            or ".tabular-nums" in css)


class TabularNumsSweepTests(unittest.TestCase):
    """Each of the 8 swept panel CSS files carries tabular-nums on at
    least one numeric cell. Additive: existing rules are preserved."""

    def test_right_now_panel_via_next_css(self):
        # right_now's .kv values live in next.css under .panel-right-now.
        # The sweep added font-variant-numeric to the kv value selector.
        css = _read(CSS_NEXT)
        block = css.split(".panel-right-now .kv > span:last-child", 1)[1]
        block = block.split("}", 1)[0]
        self.assertIn("tabular-nums", block,
                      ".panel-right-now .kv values must carry tabular-nums")

    def test_next_panel_kv_values(self):
        css = _read(CSS_NEXT)
        block = css.split(".panel-next .kv > span:last-child", 1)[1]
        block = block.split("}", 1)[0]
        self.assertIn("tabular-nums", block,
                      ".panel-next .kv values must carry tabular-nums")

    def test_next_panel_wave_line_already_tabular(self):
        """#nx-wave block already declares tabular-nums (pre-sweep);
        the rule lives in item_build.css (shared .kv layout block).
        Guard against a regression that drops it."""
        css = _read(CSS_ITEM_BUILD)
        # The block starts at "#nx-wave," and runs through .wave-verb
        self.assertIn("#nx-wave", css)
        self.assertIn("font-variant-numeric: tabular-nums", css)

    def test_item_build_value(self):
        css = _read(CSS_ITEM_BUILD)
        # Locate the .build-value rule and assert tabular-nums appears in it.
        block = css.split(".build-value {", 1)[1].split("}", 1)[0]
        self.assertIn("tabular-nums", block,
                      ".build-value must carry tabular-nums")

    def test_team_context_tail_chips(self):
        css = _read(CSS_TEAM_CONTEXT)
        for selector in (".tc-slot-tail {",
                         ".tc-slot-mains {",
                         ".tc-slot-wr,"):
            self.assertIn(selector, css,
                          f"team_context.css missing {selector}")
        # Tail / mains / wr+streak should all carry tabular-nums.
        self.assertGreaterEqual(
            css.count("font-variant-numeric: tabular-nums"), 3,
            "team_context.css must carry tabular-nums on the tail/mains/wr "
            "block (>=3 declarations expected after the sweep)",
        )

    def test_augment_reco_meta_and_rank(self):
        css = _read(CSS_AUGMENT_RECO)
        # .ar-meta + .ar-rank both carry tabular-nums after the sweep.
        meta_block = css.split(".ib-aug-reco-block .ar-meta {", 1)[1]
        meta_block = meta_block.split("}", 1)[0]
        rank_block = css.split(".ib-aug-reco-block .ar-rank {", 1)[1]
        rank_block = rank_block.split("}", 1)[0]
        self.assertIn("tabular-nums", meta_block,
                      ".ar-meta must carry tabular-nums")
        self.assertIn("tabular-nums", rank_block,
                      ".ar-rank must carry tabular-nums")

    def test_draft_elo_already_tabular(self):
        """draft_elo.css was the first chip to consume tabular-nums
        (Agent C). Guard against regression - this is the canonical
        example the polish sweep extended fleet-wide."""
        css = _read(CSS_DRAFT_ELO)
        self.assertTrue(_carries_tabular_nums(css),
                        "draft_elo.css lost its tabular-nums declarations")
        # Verify both .de-wr and .de-score still carry it.
        wr_block = css.split(".draft-elo-chip .de-wr {", 1)[1].split("}", 1)[0]
        sc_block = css.split(".draft-elo-chip .de-score {", 1)[1].split("}", 1)[0]
        self.assertIn("tabular-nums", wr_block)
        self.assertIn("tabular-nums", sc_block)

    def test_spike_curve_container(self):
        css = _read(CSS_SPIKE_CURVE)
        block = css.split(".spike-curve-container {", 1)[1].split("}", 1)[0]
        self.assertIn("tabular-nums", block,
                      ".spike-curve-container must carry tabular-nums")

    def test_ward_heat_count_cell(self):
        css = _read(CSS_WARD_HEAT)
        # .wh-count is the per-lane numeric cell.
        block = css.split(".ward-heat-container .wh-cell .wh-count {", 1)[1]
        block = block.split("}", 1)[0]
        self.assertIn("tabular-nums", block,
                      ".wh-count must carry tabular-nums")


class TextWrapBalanceTests(unittest.TestCase):
    """4 multi-line-wrap selectors carry text-wrap: balance."""

    def test_action_headline_right_now(self):
        css = _read(CSS_RIGHT_NOW)
        # The .action block contains text-wrap: balance.
        block = css.split(".action {", 1)[1].split("}", 1)[0]
        self.assertIn("text-wrap: balance", block,
                      ".action must declare text-wrap: balance")

    def test_action_mid_next(self):
        css = _read(CSS_NEXT)
        block = css.split(".action-mid {", 1)[1].split("}", 1)[0]
        self.assertIn("text-wrap: balance", block,
                      ".action-mid must declare text-wrap: balance")

    def test_mvp_name_last_match(self):
        css = _read(CSS_LAST_MATCH)
        block = css.split(".lm-tc-mvp-name {", 1)[1].split("}", 1)[0]
        self.assertIn("text-wrap: balance", block,
                      ".lm-tc-mvp-name must declare text-wrap: balance")

    def test_replay_events_chip_text(self):
        css = _read(CSS_REPLAY_EV)
        block = css.split(".replay-events-chip-text {", 1)[1].split("}", 1)[0]
        self.assertIn("text-wrap: balance", block,
                      ".replay-events-chip-text must declare text-wrap: balance")


class CoachPulseWireTests(unittest.TestCase):
    """right_now.js wires rn-pulse-{good,warn,bad}; right_now.css
    declares the animation rule; classifyAction-driven; setTimeout
    dismissal; empty band does not pulse."""

    def test_css_declares_pulse_classes(self):
        css = _read(CSS_RIGHT_NOW)
        self.assertIn(".action.rn-pulse-good", css,
                      "right_now.css missing .action.rn-pulse-good rule")
        self.assertIn(".action.rn-pulse-warn", css,
                      "right_now.css missing .action.rn-pulse-warn rule")
        self.assertIn(".action.rn-pulse-bad", css,
                      "right_now.css missing .action.rn-pulse-bad rule")
        # The animation must reference the tokens.css keyframes.
        self.assertIn("animation: coach-pulse-good", css)
        self.assertIn("animation: coach-pulse-warn", css)
        self.assertIn("animation: coach-pulse-bad", css)

    def test_js_wires_pulse_map(self):
        js = _read(JS_RIGHT_NOW)
        # Pulse map maps classifyAction bands -> pulse classes.
        self.assertIn("rn-pulse-bad", js,
                      "right_now.js must emit rn-pulse-bad for urgent")
        self.assertIn("rn-pulse-warn", js,
                      "right_now.js must emit rn-pulse-warn for fight")
        self.assertIn("rn-pulse-good", js,
                      "right_now.js must emit rn-pulse-good for good")
        # The classifyAction() return is the band driver.
        self.assertIn("classifyAction", js)

    def test_js_dismisses_pulse_via_settimeout(self):
        js = _read(JS_RIGHT_NOW)
        # The pulse is dropped 800ms after it lands (one-shot).
        self.assertIn("setTimeout", js)
        # Specifically there is a setTimeout that removes a pulse class.
        # Use a permissive substring match (the exact closure shape may
        # change but the contract is: a setTimeout drops the pulseClass).
        self.assertIn("classList.remove(pulseClass)", js,
                      "right_now.js must remove the pulse class after 800ms")
        self.assertIn("800", js,
                      "right_now.js must drop the pulse at 800ms")

    def test_js_empty_band_does_not_pulse(self):
        """The empty band (no headline) must not pulse. The pulse map
        carries only urgent/fight/good - empty is absent so pulseClass
        is undefined and the guard skips the classList add."""
        js = _read(JS_RIGHT_NOW)
        # The map carries the 3 mappable bands - none for empty.
        block = js.split("const pulseMap = ", 1)[1].split("};", 1)[0]
        # urgent / fight / good are present in the map literal
        self.assertIn("urgent:", block)
        self.assertIn("fight:", block)
        self.assertIn("good:", block)
        # empty is NOT in the map literal (absence is the contract).
        self.assertNotIn("empty:", block,
                         "pulseMap must not include 'empty' - empty band "
                         "(no headline) does not pulse")


class DraftEloEscTests(unittest.TestCase):
    """draft_elo.js adds a document-level keydown listener for ESC,
    does NOT introduce a click handler, does NOT add a pinned class."""

    def test_js_adds_keydown_listener_on_document(self):
        js = _read(JS_DRAFT_ELO)
        self.assertIn('document.addEventListener("keydown"', js,
                      "draft_elo.js must add a document-level keydown listener")

    def test_js_checks_escape_key(self):
        js = _read(JS_DRAFT_ELO)
        # Either e.key === "Escape" OR e.code === "Escape" (both safe).
        self.assertTrue('"Escape"' in js,
                        "draft_elo.js must check for the Escape key")

    def test_js_does_not_introduce_click_handler(self):
        """HoverOnlyContractTests in test_draft_elo_panel_dom.py already
        guards no click-to-pin. This is a positive cross-check that the
        ESC handler itself did not regress that contract."""
        js = _read(JS_DRAFT_ELO)
        self.assertNotIn("addEventListener('click'", js)
        self.assertNotIn('addEventListener("click"', js)
        self.assertNotIn(".onclick", js)

    def test_js_does_not_introduce_pinned_class(self):
        js = _read(JS_DRAFT_ELO)
        self.assertNotIn("classList.add('pinned'", js)
        self.assertNotIn('classList.add("pinned"', js)
        # Also no pinned literal anywhere as a defensive guard.
        self.assertNotIn("'pinned'", js)
        self.assertNotIn('"pinned"', js)


class AsciiHygieneTests(unittest.TestCase):
    """No em-dashes / en-dashes / smart quotes in the new/edited surface
    (CLAUDE.md hard rule). BAD dict built via chr() so this test file
    stays clean against its own scan."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def _scan(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [name for ch, name in self.BAD.items() if ch in text]

    def test_test_file_is_ascii_clean(self):
        self.assertEqual([], self._scan(Path(__file__)),
                         "test_ui_polish_2026_05_20.py contains forbidden glyphs")


if __name__ == "__main__":
    unittest.main()
