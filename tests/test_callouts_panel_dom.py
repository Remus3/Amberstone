"""DOM-contract tests for the callouts panel (deterministic CALLOUTS + LEAD).

Cheap grep-style smoke. Mirrors test_coach_choices_panel_dom.py. Covers the
two mounts (#rn-lead, #rn-callouts), the two render exports + their wiring
into main.js's applyState path, the dashboard.css @import, and ASCII
hygiene on the new JS + CSS files (item 265 W3E).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO / "web" / "index.html"
PANEL_JS = REPO / "web" / "js" / "panels" / "callouts.js"
PANEL_CSS = REPO / "web" / "css" / "panels" / "callouts.css"
DASHBOARD_CSS = REPO / "web" / "css" / "dashboard.css"
MAIN_JS = REPO / "web" / "js" / "main.js"


class MountTests(unittest.TestCase):
    """#rn-lead sits between #rn-action and #rn-immediate; #rn-callouts
    sits after #rn-choices. Both inside #right-now, both hidden by default."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_lead_mount_present_and_hidden(self):
        self.assertRegex(self.html, r'<div id="rn-lead"[^>]*hidden')

    def test_callouts_mount_present_and_hidden(self):
        self.assertRegex(self.html, r'<div id="rn-callouts"[^>]*hidden')

    def test_both_mounts_inside_right_now(self):
        rn = re.search(
            r'<section id="right-now"(.*?)</section>', self.html, re.DOTALL,
        )
        self.assertIsNotNone(rn)
        self.assertIn('id="rn-lead"', rn.group(1))
        self.assertIn('id="rn-callouts"', rn.group(1))

    def test_lead_between_action_and_immediate(self):
        act = self.html.index('id="rn-action"')
        lead = self.html.index('id="rn-lead"')
        imm = self.html.index('id="rn-immediate"')
        self.assertLess(act, lead)
        self.assertLess(lead, imm)

    def test_callouts_after_choices(self):
        ch = self.html.index('id="rn-choices"')
        co = self.html.index('id="rn-callouts"')
        self.assertLess(ch, co)


class PanelJsTests(unittest.TestCase):
    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_exports_render_fns(self):
        self.assertIn("export function renderCallouts", self.js)
        self.assertIn("export function renderLead", self.js)

    def test_reads_top_level_state_keys(self):
        self.assertIn("state.callouts", self.js)
        self.assertIn("state.lead_projection", self.js)

    def test_eta_formatter_seam(self):
        self.assertIn("_fmtEta", self.js)
        self.assertIn('"NOW"', self.js)

    def test_dedup_via_signatures(self):
        self.assertIn("_lastLeadSig", self.js)
        self.assertIn("_lastCalloutsSig", self.js)

    def test_internals_seam_exported(self):
        self.assertIn("export const _internals", self.js)


class MainJsWireTests(unittest.TestCase):
    def setUp(self):
        self.js = MAIN_JS.read_text(encoding="utf-8")

    def test_imports_render_fns(self):
        self.assertIn("import { renderCallouts, renderLead }", self.js)
        self.assertIn("./panels/callouts.js", self.js)

    def test_wires_after_renderCoachChoices(self):
        cc_idx = self.js.index("renderCoachChoices(")
        lead_idx = self.js.index("renderLead(")
        co_idx = self.js.index("renderCallouts(")
        self.assertLess(cc_idx, lead_idx)
        self.assertLess(lead_idx, co_idx)
        # Same dispatcher block - adjacency.
        self.assertLess(co_idx - cc_idx, 160)


class CssTests(unittest.TestCase):
    def setUp(self):
        self.css = PANEL_CSS.read_text(encoding="utf-8")
        self.dash = DASHBOARD_CSS.read_text(encoding="utf-8")

    def test_dashboard_imports_panel(self):
        self.assertIn("./panels/callouts.css", self.dash)

    def test_mounts_styled(self):
        self.assertIn("#rn-callouts", self.css)
        self.assertIn(".rc-lead", self.css)

    def test_hidden_attribute_honored(self):
        self.assertIn("#rn-callouts[hidden]", self.css)
        self.assertIn(".rc-lead[hidden]", self.css)

    def test_uses_tokens_for_colors(self):
        self.assertIn("var(--signal-good", self.css)
        self.assertIn("var(--signal-warn", self.css)


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dash, no smart quotes in the new JS + CSS (hard rule)."""

    BAD = {
        chr(0x2013): "en-dash",
        chr(0x2014): "em-dash",
        chr(0x2018): "left smart quote",
        chr(0x2019): "right smart quote",
        chr(0x201C): "left smart dq",
        chr(0x201D): "right smart dq",
        chr(0x2026): "ellipsis",
    }

    def test_panel_js_ascii(self):
        text = PANEL_JS.read_text(encoding="utf-8")
        for ch, name in self.BAD.items():
            self.assertNotIn(ch, text, f"{name} in callouts.js")
        self.assertTrue(all(ord(c) < 128 for c in text), "non-ASCII in callouts.js")

    def test_panel_css_ascii(self):
        text = PANEL_CSS.read_text(encoding="utf-8")
        for ch, name in self.BAD.items():
            self.assertNotIn(ch, text, f"{name} in callouts.css")
        self.assertTrue(all(ord(c) < 128 for c in text), "non-ASCII in callouts.css")


if __name__ == "__main__":
    unittest.main()
