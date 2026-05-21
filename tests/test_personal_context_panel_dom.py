"""Grep-based smoke tests for the personal-context panel (item 124 follow-up).

Three concerns this guards:

1. The #personal-context-section block mounts inside the Right Now panel
   body so the operator sees death-pattern context adjacent to the live
   coach output.
2. web/js/panels/personal_context.js exports the helpers main.js wires
   into the home view (loadPersonalContext / renderPersonalContext /
   startPersonalContextPolling) and main.js actually starts the poll.
3. ASCII hygiene + CSS import + empty-state class are wired.

Mirrors the cheap text-search precedent in
``tests/test_replay_events_panel_dom.py`` +
``tests/test_last_match_score_card_dom.py``.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML    = ROOT / "web" / "index.html"
PANEL_JS      = ROOT / "web" / "js" / "panels" / "personal_context.js"
PANEL_CSS     = ROOT / "web" / "css" / "panels" / "personal_context.css"
MAIN_JS       = ROOT / "web" / "js" / "main.js"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class SectionMountTests(unittest.TestCase):
    """The personal-context section mounts inside the Right Now panel."""

    def test_section_id_mounted(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="personal-context-section"', html)
        self.assertIn('id="personal-context-list"', html)
        self.assertIn('id="personal-context-empty"', html)

    def test_section_starts_hidden(self):
        html = _read(INDEX_HTML)
        block = html.split('id="personal-context-section"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", block)

    def test_section_lives_inside_right_now_panel(self):
        html = _read(INDEX_HTML)
        # The Right Now section runs from the <section id="right-now"> tag
        # to its closing </section>. The personal-context section must
        # live inside that range so it sits next to the coach output.
        rn = html.split('id="right-now"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="personal-context-section"', rn,
                      "personal-context section must live inside #right-now")

    def test_section_header_present(self):
        html = _read(INDEX_HTML)
        self.assertIn("PERSONAL CONTEXT", html)


class PanelJsExportsTests(unittest.TestCase):
    """The panel module exports the helpers main.js consumes."""

    def test_load_function_exported(self):
        js = _read(PANEL_JS)
        self.assertIn("export async function loadPersonalContext", js)

    def test_render_function_exported(self):
        js = _read(PANEL_JS)
        self.assertIn("export function renderPersonalContext", js)

    def test_poll_starter_exported(self):
        js = _read(PANEL_JS)
        self.assertIn("export function startPersonalContextPolling", js)

    def test_fetches_personal_context_endpoint(self):
        js = _read(PANEL_JS)
        self.assertIn('"/api/personal-context"', js)

    def test_refresh_interval_is_60s(self):
        js = _read(PANEL_JS)
        self.assertIn("60 * 1000", js)


class MainJsWireTests(unittest.TestCase):
    """main.js imports the panel module + starts the poll on session start."""

    def test_main_imports_panel_helper(self):
        js = _read(MAIN_JS)
        self.assertIn("from './panels/personal_context.js'", js)
        self.assertIn("startPersonalContextPolling", js)

    def test_main_invokes_poll_starter(self):
        js = _read(MAIN_JS)
        # Catch the call site - look for the invocation form, not just
        # the imported identifier in the import statement.
        self.assertIn("startPersonalContextPolling()", js)


class CssWireTests(unittest.TestCase):
    """dashboard.css imports the panel CSS + the empty-state class
    exists in the panel sheet."""

    def test_dashboard_css_imports_panel(self):
        css = _read(DASHBOARD_CSS)
        self.assertIn("./panels/personal_context.css", css)

    def test_empty_state_class_present(self):
        css = _read(PANEL_CSS)
        self.assertIn(".personal-context-empty", css)

    def test_card_kind_variants_present(self):
        css = _read(PANEL_CSS)
        # 3 explicit kinds + the default fallback.
        self.assertIn('data-kind="warn"', css)
        self.assertIn('data-kind="info"', css)
        self.assertIn('data-kind="dim"', css)
        self.assertIn('data-kind="default"', css)


class EmptyStateTests(unittest.TestCase):
    """The empty state chip renders when the backend returns
    {ok: false, reason: 'no_data'}."""

    def test_empty_state_string_present(self):
        js = _read(PANEL_JS)
        # Specific phrasing the spec called for.
        self.assertIn("No personal context yet", js)
        self.assertIn("postmortem", js)


class AsciiHygieneTests(unittest.TestCase):
    """No em/en dashes, smart quotes, or arrows in the panel surface
    files. BAD glyphs built via chr() so this test file stays clean
    against its own scan."""

    def _bad_glyphs(self) -> dict[int, str]:
        return {
            0x2013: "EN DASH",
            0x2014: "EM DASH",
            0x2018: "LEFT SINGLE QUOTE",
            0x2019: "RIGHT SINGLE QUOTE",
            0x201C: "LEFT DOUBLE QUOTE",
            0x201D: "RIGHT DOUBLE QUOTE",
            0x2192: "RIGHT ARROW",
        }

    def _scan(self, path: Path) -> None:
        text = _read(path)
        bad = self._bad_glyphs()
        hits = []
        for cp, name in bad.items():
            ch = chr(cp)
            if ch in text:
                hits.append(f"U+{cp:04X} ({name})")
        self.assertEqual(
            hits, [], f"{path.name} contains banned glyphs: {hits}"
        )

    def test_panel_js_is_clean(self):
        self._scan(PANEL_JS)

    def test_panel_css_is_clean(self):
        self._scan(PANEL_CSS)

    def test_panel_js_is_pure_ascii(self):
        data = PANEL_JS.read_bytes()
        non_ascii = [b for b in data if b > 127]
        self.assertEqual(
            non_ascii, [],
            f"non-ASCII bytes in personal_context.js: {non_ascii[:8]}"
        )

    def test_panel_css_is_pure_ascii(self):
        data = PANEL_CSS.read_bytes()
        non_ascii = [b for b in data if b > 127]
        self.assertEqual(
            non_ascii, [],
            f"non-ASCII bytes in personal_context.css: {non_ascii[:8]}"
        )


if __name__ == "__main__":
    unittest.main()
