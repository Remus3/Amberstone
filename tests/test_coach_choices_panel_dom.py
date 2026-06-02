"""DOM-contract tests for the coach_choices panel (A/B tutoring).

Cheap grep-style smoke. Mirrors test_replay_events_panel_dom.py.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO / "web" / "index.html"
PANEL_JS = REPO / "web" / "js" / "panels" / "coach_choices.js"
PANEL_CSS = REPO / "web" / "css" / "panels" / "coach_choices.css"
DASHBOARD_CSS = REPO / "web" / "css" / "dashboard.css"
MAIN_JS = REPO / "web" / "js" / "main.js"


class MountTests(unittest.TestCase):
    """The mount div #rn-choices lives inside #right-now between
    #rn-immediate and the Watch kv row."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_mount_div_present(self):
        self.assertIn('id="rn-choices"', self.html)

    def test_mount_is_hidden_by_default(self):
        self.assertRegex(self.html, r'<div id="rn-choices"[^>]*hidden')

    def test_mount_lives_inside_panel_right_now(self):
        rn_section = re.search(
            r'<section id="right-now"(.*?)</section>',
            self.html, re.DOTALL,
        )
        self.assertIsNotNone(rn_section)
        self.assertIn('id="rn-choices"', rn_section.group(1))

    def test_mount_between_immediate_and_watch(self):
        imm = self.html.index('id="rn-immediate"')
        ch = self.html.index('id="rn-choices"')
        watch = self.html.index('id="rn-risk"')
        self.assertLess(imm, ch)
        self.assertLess(ch, watch)


class PanelJsTests(unittest.TestCase):
    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_exports_renderCoachChoices(self):
        self.assertIn("export function renderCoachChoices", self.js)

    def test_reads_coach_choices_from_state(self):
        self.assertIn("coach.choices", self.js)

    def test_posts_to_api_coach_choice(self):
        self.assertIn('"/api/coach-choice"', self.js)
        self.assertIn("POST", self.js)

    def test_handles_empty_choices(self):
        self.assertIn("choices.length === 0", self.js)

    def test_3_segment_band_dots(self):
        self.assertIn("rc-band-dot", self.js)
        self.assertIn('"high"', self.js)
        self.assertIn('"low"', self.js)

    def test_dedup_via_signature(self):
        self.assertIn("_lastSig", self.js)
        self.assertIn("_chipsSignature", self.js)


class MainJsWireTests(unittest.TestCase):
    def setUp(self):
        self.js = MAIN_JS.read_text(encoding="utf-8")

    def test_imports_renderCoachChoices(self):
        self.assertIn("import { renderCoachChoices }", self.js)
        self.assertIn("./panels/coach_choices.js", self.js)

    def test_wires_renderCoachChoices_after_renderRightNow(self):
        rn_idx = self.js.index("renderRightNow(p)")
        cc_idx = self.js.index("renderCoachChoices(")
        self.assertLess(rn_idx, cc_idx)
        # Within ~120 chars so they're adjacent in the same dispatcher.
        self.assertLess(cc_idx - rn_idx, 120)


class CssTests(unittest.TestCase):
    def setUp(self):
        self.css = PANEL_CSS.read_text(encoding="utf-8")
        self.dash = DASHBOARD_CSS.read_text(encoding="utf-8")

    def test_dashboard_imports_panel(self):
        self.assertIn("./panels/coach_choices.css", self.dash)

    def test_mount_id_styled(self):
        self.assertIn("#rn-choices", self.css)

    def test_hidden_attribute_honored(self):
        self.assertIn("#rn-choices[hidden]", self.css)

    def test_uses_tokens_for_colors(self):
        # Falls back to inherit; primary color refs are var(--signal-*).
        self.assertIn("var(--signal-good", self.css)
        self.assertIn("var(--signal-warn", self.css)

    def test_no_em_dash(self):
        BAD = {
            chr(0x2013): "en-dash",
            chr(0x2014): "em-dash",
            chr(0x2018): "left smart quote",
            chr(0x2019): "right smart quote",
            chr(0x201C): "left smart dq",
            chr(0x201D): "right smart dq",
        }
        for ch, name in BAD.items():
            self.assertNotIn(ch, self.css, f"{name} in coach_choices.css")


class StateBuilderWiresChoicesTests(unittest.TestCase):
    """The dashboard state builder must stamp coach.choices (even if []
    empty) so the frontend can branch on a present-but-empty field
    rather than null-checking. parse_choices is preferred; synthesizer
    is the fallback when no native choices arrive."""

    def test_state_builder_imports_coach_choices(self):
        # item 265 W3A (deterministic-FIRST coaching) moved the
        # core.coach_choices wiring out of _state_builder and into
        # dashboard/_deterministic_coaching.py. _state_builder now calls
        # compute_deterministic + resolve_choices and still stamps
        # coach["choices"]; the parse-preferred + synth-fallback
        # primitives live one indirection deeper in the resolver. Assert
        # the wiring at BOTH homes so the intent (state-build path stamps
        # choices via parse>synth) stays pinned after the refactor.
        sb = (REPO / "dashboard" / "_state_builder.py").read_text(encoding="utf-8")
        self.assertIn("compute_deterministic", sb)
        self.assertIn("resolve_choices", sb)
        self.assertIn('coach["choices"]', sb)
        det = (REPO / "dashboard" / "_deterministic_coaching.py").read_text(
            encoding="utf-8")
        self.assertIn("from core.coach_choices import", det)
        self.assertIn("parse_choices", det)
        self.assertIn("synthesize_simple_choices", det)


if __name__ == "__main__":
    unittest.main()
