"""Regression guards for the s184.1 archetype-nudge chip wiring.

The chip itself is pure JS rendering over the s184 backend that is
already heavily covered (54 tests in test_archetype_mismatch +
test_routes_archetype_nudge + test_state_builder_archetype_nudge).
What's *not* covered by those is the four-file wiring that hooks the
chip into the live dashboard:

  - web/index.html declares the chip element + dismiss button
  - web/js/panels/archetype_nudge_chip.js exports renderArchetypeNudge
  - web/js/main.js imports the panel + calls renderArchetypeNudge(st)
    at every /api/state consumption path
  - web/css/panels/map_state.css carries the chip styles

A future refactor that accidentally drops one of these (e.g. an ESM
split that forgets to re-export, an index.html rebuild that misses the
chip block, a main.js cleanup that orphans the import) would silently
break the chip. These tests are grep-based smoke checks — cheap and
fast, but enough to catch a missing wire.
"""
from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "archetype_nudge_chip.js"
MAIN_JS = WEB / "js" / "main.js"
MAP_CSS = WEB / "css" / "panels" / "map_state.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class IndexHtmlTests(unittest.TestCase):
    """The chip element must be declared next to #ds-pill in row 2."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_chip_element_present(self) -> None:
        self.assertIn('id="archetype-nudge-chip"', self.text)
        self.assertIn('class="archetype-nudge-chip"', self.text)

    def test_chip_hidden_by_default(self) -> None:
        # The element ships with the `hidden` attribute so first paint is
        # collapsed; JS un-hides on phase=fired only.
        self.assertIn('id="archetype-nudge-chip" hidden', self.text)

    def test_chip_inner_text_span_present(self) -> None:
        self.assertIn('id="archetype-nudge-chip-text"', self.text)

    def test_chip_dismiss_button_present(self) -> None:
        self.assertIn('id="archetype-nudge-chip-x"', self.text)
        # Type=button so it doesn't submit any ancestor form.
        self.assertIn('type="button"', self.text)

    def test_chip_lives_in_header_row_two(self) -> None:
        # Sanity check: the chip must sit inside header-row-2 (next to
        # #ds-pill / #trigger-pill). A future refactor that ejects it
        # into a different region of the doc should trip this.
        row2_start = self.text.find('class="header-row header-row-2"')
        self.assertNotEqual(row2_start, -1, "header-row-2 marker missing")
        row2_end = self.text.find("</div>", row2_start + 1)
        chip_pos = self.text.find('id="archetype-nudge-chip"')
        self.assertTrue(row2_start < chip_pos < row2_end,
                        f"chip outside header-row-2: row2=[{row2_start},{row2_end}] chip={chip_pos}")


class PanelJsTests(unittest.TestCase):
    """The panel module must export renderArchetypeNudge."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_render_export_present(self) -> None:
        # ES module export — main.js imports by name.
        self.assertIn("export function renderArchetypeNudge", self.text)

    def test_dismiss_endpoint_hardcoded(self) -> None:
        # Path must match dashboard/routes_archetype.py:_serve_archetype_nudge_dismiss.
        self.assertIn("/api/archetype-nudge/dismiss", self.text)

    def test_fire_phase_gated(self) -> None:
        # Render must check phase == "fired" before un-hiding.
        # Dismissed / no_mismatch / pending all stay invisible.
        self.assertTrue('"fired"' in self.text or "'fired'" in self.text)

    def test_idempotent_signature_guard(self) -> None:
        # Avoid teardown/rebuild on every 2s state poll.
        self.assertIn("_lastSig", self.text)


class MainJsWiringTests(unittest.TestCase):
    """main.js must import the panel and call renderArchetypeNudge at every
    /api/state consumption path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAIN_JS)

    def test_import_present(self) -> None:
        self.assertIn("panels/archetype_nudge_chip.js", self.text)
        self.assertIn("renderArchetypeNudge", self.text)

    def test_callsite_count_matches_state_consumers(self) -> None:
        # SSE handler + HTTP fallback + LCU poller = 3 callsites.
        # Same count as renderTeamContext(st), which is the canonical
        # sibling pattern (top-level state-derived sidecar render).
        nudge_calls = self.text.count("renderArchetypeNudge(st)")
        team_calls = self.text.count("renderTeamContext(st)")
        self.assertEqual(nudge_calls, 3,
                         f"expected 3 renderArchetypeNudge callsites, got {nudge_calls}")
        self.assertEqual(team_calls, 3,
                         f"expected 3 renderTeamContext callsites, got {team_calls}")


class CssTests(unittest.TestCase):
    """Chip styles + mode-gating must remain in map_state.css."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAP_CSS)

    def test_chip_class_styled(self) -> None:
        self.assertIn(".archetype-nudge-chip {", self.text)

    def test_chip_dismiss_button_styled(self) -> None:
        self.assertIn(".archetype-nudge-chip-x", self.text)

    def test_mode_gated_like_ds_pill(self) -> None:
        # Same hide rules as .ds-pill — collapses in client / tft / no-mode.
        for selector in (
            'body[data-mode="client"] .archetype-nudge-chip',
            'body[data-mode="tft"]    .archetype-nudge-chip',
            "body:not([data-mode])    .archetype-nudge-chip",
        ):
            self.assertIn(selector, self.text, f"missing mode-gate selector: {selector}")

    def test_hidden_attr_respected(self) -> None:
        # Element-level [hidden] must collapse even when mode matches.
        self.assertIn(".archetype-nudge-chip[hidden]", self.text)


if __name__ == "__main__":
    unittest.main()
