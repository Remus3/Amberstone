"""Phase 5 overlay-surface drift-guard smoke (HZ-D1).

The Electron shell (rc-shell/src/overlay_state.js) and the dashboard web
surface (web/css/overlay.css + web/js/main.js) share an IMPLICIT contract:
the shell loads the dashboard at ?overlay=1[&panelset=NAME] and the page
must render the compact in-game HUD subset for exactly the panel sets the
shell's Alt+Shift+C cycle can request. The two sides deploy independently -
the shell is a packaged Electron app that cannot hot-pick-up web/ changes -
and the contract has already drifted once (item-378 dark mounts: panel sets
cycled shell-side with no matching overlay.css gates). These grep-style
characterization tests pin both sides so a one-sided change goes red in CI
instead of going dark in-game.

Contract areas, each one TestCase below:
  1. PANEL_SETS source of truth in overlay_state.js (frozen member list).
  2. overlay.css gates widget visibility PER-WIDGET (.ovx-hidden), NOT by
     panel set - the coach/build/threat CSS gates were retired 2026-06-28
     (commit bf205ad0, OVERLAY_DOCTRINE.md sec 4); body[data-panelset]
     stamping is now inert. Pin the replacement contract so a re-added gate
     (which would silently hide an always-reachable panel) goes red.
  3. main.js stamps data-shell/data-panelset from the URL and pins the
     view router to active-match in overlay mode.
  4. index.html actually loads overlay.css (a dead stylesheet renders the
     full 1920 grid over the game).
  5. overlay_pulse.js change-pulse hook exists and is wired in main.js.
  6. overlay_state.js URL builder normalizes panelset against PANEL_SETS.
  7. GPU-light discipline: no blur, no looping animation over the game.
  8. ASCII hygiene on the three overlay-surface files (repo hard rule).

Style mirrors tests/test_coach_choices_panel_dom.py: pathlib reads plus
regex assertions only - no DOM emulation, no network, no server spawn.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OVERLAY_STATE_JS = REPO / "rc-shell" / "src" / "overlay_state.js"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"
MAIN_JS = REPO / "web" / "js" / "main.js"
INDEX_HTML = REPO / "web" / "index.html"
OVERLAY_PULSE_JS = REPO / "web" / "js" / "overlay_pulse.js"


def _shell_panel_sets() -> list[str]:
    """Parse the PANEL_SETS literal out of overlay_state.js source.

    Parsed (not hardcoded) so the web-side assertions below track the
    shell's real member list - the whole point is catching a member
    added or renamed on ONE side only.
    """
    src = OVERLAY_STATE_JS.read_text(encoding="utf-8")
    m = re.search(r"const PANEL_SETS = Object\.freeze\(\[([^\]]*)\]\)", src)
    if m is None:
        return []
    return re.findall(r'"([a-z]+)"', m.group(1))


class ShellPanelSetsSourceTests(unittest.TestCase):
    """overlay_state.js PANEL_SETS is the single source of truth for the
    Alt+Shift+C cycle; everything web-side derives from it."""

    def test_panel_sets_parses_from_shell_source(self):
        self.assertTrue(
            _shell_panel_sets(),
            "PANEL_SETS Object.freeze([...]) literal not found in "
            "overlay_state.js - the drift guard lost its anchor",
        )

    def test_panel_sets_members_are_coach_build_threat(self):
        # Order matters: index 0 is the landing set for unknown state and
        # the list order IS the hotkey cycle order.
        self.assertEqual(["coach", "build", "threat"], _shell_panel_sets())


class OverlayCssVisibilityGateTests(unittest.TestCase):
    """Panel-set CSS gating was RETIRED 2026-06-28 (commit bf205ad0; overlay.css
    section 4d + OVERLAY_DOCTRINE.md section 4): the coach/build/threat quick-swap
    no longer narrows the field. Every widget shows by default and the operator
    hides one from the launcher menu, so the item-378 "every panel set needs a CSS
    gate" contract is gone - body[data-panelset] stamping (still emitted by main.js
    + the shell, harmless) is now INERT. These tests pin the REPLACEMENT contract:
    a re-introduced [data-panelset] gate (which would silently hide a panel the
    doctrine says is always reachable) goes red, and the per-widget hide + the two
    unconditional at-rest reveals stay wired."""

    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")
        self.sets = _shell_panel_sets()
        self.assertTrue(self.sets)

    def test_no_shell_panel_set_has_a_css_gate(self):
        # The inverse of the retired item-378 contract: NO shell PANEL_SETS
        # member may carry a valued [data-panelset="<name>"] gate in overlay.css.
        # (The section-4d comment mentions a bare `body[data-panelset]` to note
        # the stamp is inert; the valued-selector check ignores that prose.)
        for name in self.sets:
            with self.subTest(panelset=name):
                self.assertNotIn(
                    f'[data-panelset="{name}"]', self.css,
                    f"overlay.css still gates panelset '{name}' - panel sets "
                    "were retired 2026-06-28; per-widget .ovx-hidden is the gate",
                )

    def test_per_widget_hide_is_the_visibility_gate(self):
        # The launcher menu's per-widget toggle adds .ovx-hidden; that is now
        # the single visibility gate (doctrine section 4).
        self.assertRegex(
            self.css,
            r'body\[data-shell="overlay"\] \.ovx-hidden\s*\{[^}]*'
            r'display:\s*none\s*!important',
        )

    def test_at_rest_panes_revealed_when_not_hidden(self):
        # The two panes that ship display:none in their own renderer CSS - the
        # CDS ledger (w-threat / .am-pane-cd) and the fight-model knobs
        # (w-ovds / #am-pane-ovds) - are shown UNCONDITIONALLY here unless
        # per-widget-hidden, so they are reachable with no panel set.
        for sel in (
            r'\.am-pane-cd\.ovx-widget:not\(\.ovx-hidden\)',
            r'#am-pane-ovds\.ovx-widget:not\(\[hidden\]\):not\(\.ovx-hidden\)',
        ):
            with self.subTest(reveal=sel):
                self.assertRegex(
                    self.css,
                    sel + r'\s*\{[^}]*display:\s*block\s*!important',
                )


class MainJsOverlayRouteTests(unittest.TestCase):
    """main.js owns the web half of the route contract: stamp the body
    flags from the URL, then keep the router off every non-HUD view."""

    def setUp(self):
        self.js = MAIN_JS.read_text(encoding="utf-8")

    def test_stamps_shell_overlay_under_query_flag(self):
        flag_idx = self.js.index("/[?&]overlay=1/.test(location.search)")
        stamp_idx = self.js.index('document.body.dataset.shell = "overlay"')
        self.assertLess(flag_idx, stamp_idx)
        # Adjacency pins the stamp INSIDE the ?overlay=1 branch - stamping
        # unconditionally would flip the normal dashboard into HUD mode.
        self.assertLess(stamp_idx - flag_idx, 200)

    def test_view_router_pinned_to_active_match_in_overlay_mode(self):
        # The overlay window has no nav chrome: any other view would
        # strand the HUD on a surface overlay.css hides anyway. The guard
        # must sit at the head of the resolver, before the first
        # active-match application.
        m = re.search(
            r"function _viewResolveAndApply\b(.*?)applyView\(\"active-match\"\)",
            self.js, re.DOTALL,
        )
        self.assertIsNotNone(
            m, "_viewResolveAndApply no longer applies active-match")
        self.assertIn('dataset.shell === "overlay"', m.group(1))

    def test_panelset_stamp_alternation_matches_shell_panel_sets(self):
        self.assertIn("document.body.dataset.panelset", self.js)
        # main.js hardcodes the canonical alternation rather than reading
        # PANEL_SETS (different runtime); this equality IS the cross-repo
        # drift guard for the panelset names.
        m = re.search(r"panelset=\(([a-z|]+)\)", self.js)
        self.assertIsNotNone(
            m, "main.js lost its [?&]panelset=(...) canonical-name match")
        self.assertEqual(set(_shell_panel_sets()), set(m.group(1).split("|")))


class IndexHtmlLoadsOverlayCssTests(unittest.TestCase):
    """overlay.css only works if it is actually loaded; an orphaned
    stylesheet means the overlay window paints the full 1920 grid over
    the game."""

    def test_index_html_links_overlay_css(self):
        # This tree loads it via a direct <link> in index.html (checked:
        # dashboard.css carries no @import of overlay.css). Tolerate the
        # cache-bust ?v= query, which changes per asset edit.
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertRegex(
            html,
            r'<link[^>]*href="/css/overlay\.css(?:\?[^"]*)?"',
        )


class OverlayPulseHookTests(unittest.TestCase):
    """The change-pulse hook is the 'didn't notice mid-game' fix: a panel
    content change must draw peripheral vision exactly once."""

    def test_overlay_pulse_module_exists(self):
        self.assertTrue(OVERLAY_PULSE_JS.is_file())

    def test_exports_initOverlayPulse(self):
        js = OVERLAY_PULSE_JS.read_text(encoding="utf-8")
        self.assertIn("export function initOverlayPulse", js)

    def test_main_imports_initOverlayPulse(self):
        js = MAIN_JS.read_text(encoding="utf-8")
        self.assertIn("import { initOverlayPulse }", js)
        self.assertIn("./overlay_pulse.js", js)

    def test_main_wires_pulse_only_on_overlay_shell(self):
        # Gated call: observers on the normal dashboard would burn cycles
        # on a page nobody glances at peripherally.
        js = MAIN_JS.read_text(encoding="utf-8")
        self.assertRegex(
            js, r'dataset\.shell === "overlay"\) initOverlayPulse\(\)')

    def test_pulse_targets_the_css_keyframe_class(self):
        # The JS class literal and the CSS one-shot rule must agree or
        # the pulse silently does nothing.
        js = OVERLAY_PULSE_JS.read_text(encoding="utf-8")
        css = OVERLAY_CSS.read_text(encoding="utf-8")
        self.assertIn('PULSE_CLASS = "ov-pulse"', js)
        self.assertIn(".ov-pulse", css)
        self.assertIn("@keyframes ov-pulse-edge", css)


class ShellOverlayUrlTests(unittest.TestCase):
    """The shell-side URL builder (overlayUrl) must only ever emit
    ?panelset= values main.js will accept - the normalizer funnels every
    candidate through PANEL_SETS."""

    def setUp(self):
        self.js = OVERLAY_STATE_JS.read_text(encoding="utf-8")

    def test_canonical_normalizer_references_panel_sets(self):
        fn_idx = self.js.index("function normPanelSet")
        inc_idx = self.js.index("PANEL_SETS.includes")
        self.assertLess(fn_idx, inc_idx)
        # Adjacency keeps the membership check INSIDE the normalizer.
        self.assertLess(inc_idx - fn_idx, 300)

    def test_overlay_url_sets_flag_and_normalized_panelset(self):
        m = re.search(
            r"function overlayUrl\b(.*?)\nfunction ", self.js, re.DOTALL)
        self.assertIsNotNone(m, "overlayUrl builder missing")
        body = m.group(1)
        self.assertIn('searchParams.set("overlay", "1")', body)
        self.assertIn("normPanelSet(panelSet)", body)
        self.assertIn('searchParams.set("panelset", p)', body)

    def test_cycle_hotkey_walks_panel_sets(self):
        self.assertIn("PANEL_SETS.indexOf", self.js)
        self.assertIn("% PANEL_SETS.length", self.js)


class GpuLightDisciplineTests(unittest.TestCase):
    """The overlay composites over a live game at frame rate; blur and
    looping animation are the two banned GPU taxes (spec sec 6+7). The
    only motion allowed is the one-shot pulse keyframe."""

    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_no_blur_in_overlay_css(self):
        self.assertNotIn("blur(", self.css)

    def test_no_infinite_animation_in_overlay_css(self):
        self.assertNotIn("infinite", self.css)


class AsciiHygieneTests(unittest.TestCase):
    """Repo hard rule (CLAUDE.md): authored source stays 7-bit ASCII.
    Byte-level check so smart quotes / dashes cannot ride in via any
    encoding."""

    def test_overlay_surface_files_are_pure_ascii(self):
        for path in (OVERLAY_CSS, OVERLAY_PULSE_JS, OVERLAY_STATE_JS):
            with self.subTest(file=path.name):
                data = path.read_bytes()
                bad = next(
                    ((i, b) for i, b in enumerate(data) if b > 0x7F), None)
                self.assertIsNone(
                    bad,
                    f"non-ASCII byte in {path.name}: "
                    f"0x{bad[1]:02X} at offset {bad[0]}" if bad else None,
                )


if __name__ == "__main__":
    unittest.main()
