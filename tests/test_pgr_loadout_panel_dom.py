"""Regression guards for the PGR S5 descriptive loadout panel
(docs/PGR_REFRAME_S2.md staging S5).

Mode-aware "augment-vs-rune variant": SR / ARAM render the rune page
(keystone + minors + secondary) + summoner spells; Arena renders the 6
picked augments + spells INSTEAD of runes. Descriptive only - runes /
augments / summoner spells have no purchase-frame so the card carries NO
WPA residual (item 275). The panel renders straight from the loaded
/api/last-match payload (or its ARAM/Arena mock), so it has no separate
fixture; instead this file pins that the committed ARAM/Arena last_match
mocks carry the loadout data the panel needs.

Mirrors test_pgr_lane_compare_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "pgr_loadout.js"
PANEL_CSS = WEB / "css" / "panels" / "pgr_loadout.css"
LAST_MATCH_JS = WEB / "js" / "panels" / "last_match.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"
ARAM_MOCK = WEB / "data" / "ui_mock" / "last_match_aram.json"
ARENA_MOCK = WEB / "data" / "ui_mock" / "last_match_arena.json"

MOUNT_ID = "pgr-loadout-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")


class IndexHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_present(self) -> None:
        self.assertIn(f'id="{MOUNT_ID}"', self.text)

    def test_mount_inside_last_match_view(self) -> None:
        sec = self.text.index('id="view-last-match"')
        mount = self.text.index(f'id="{MOUNT_ID}"')
        self.assertLess(sec, mount, "mount before the last-match section")

    def test_mount_after_build_wpa(self) -> None:
        # Sits directly below the career-WPA strip.
        wpa = self.text.index('id="pgr-build-wpa-mount"')
        mount = self.text.index(f'id="{MOUNT_ID}"')
        self.assertLess(wpa, mount, "loadout mount must follow build-wpa mount")


class LastMatchWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(LAST_MATCH_JS)

    def test_imports_panel(self) -> None:
        self.assertIn("renderPgrLoadout", self.text)
        self.assertIn("./pgr_loadout.js", self.text)

    def test_dispatches_panel_in_render(self) -> None:
        self.assertIn("renderPgrLoadout(", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        self.assertIn("panels/pgr_loadout.css", _read(DASHBOARD_CSS))

    def test_import_is_in_pgr_cluster(self) -> None:
        # Must sit in the PGR cluster after pgr_lane_compare.css.
        text = _read(DASHBOARD_CSS)
        lc = text.index("panels/pgr_lane_compare.css")
        ld = text.index("panels/pgr_loadout.css")
        self.assertLess(lc, ld, "loadout import must follow lane_compare")


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderPgrLoadout", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_mode_aware_augment_vs_rune(self) -> None:
        # The defining S5 split: augments (Arena) vs runes (SR/ARAM).
        self.assertIn("_isAugmentMode", self.text)
        self.assertIn("arena_augments", self.text)

    def test_renders_runes_and_spells(self) -> None:
        self.assertIn("_runeRowHtml", self.text)
        self.assertIn("_spellRowHtml", self.text)

    def test_reuses_existing_dicts(self) -> None:
        # No new route: rune + augment dictionaries + the spell icon lib.
        self.assertIn("/api/dictionary/runes", self.text)
        self.assertIn("/api/dictionary/augments", self.text)
        self.assertIn("summoner_spells.js", self.text)

    def test_descriptive_no_wpa(self) -> None:
        # Honest framing: descriptive, not a WPA residual.
        self.assertIn("descriptive", self.text.lower())


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_hidden_mount_rule(self) -> None:
        self.assertIn(f"#{MOUNT_ID}[hidden]", self.text)

    def test_card_class_present(self) -> None:
        self.assertIn(".pld-card", self.text)

    def test_rune_and_aug_classes(self) -> None:
        self.assertIn(".pld-rune", self.text)
        self.assertIn(".pld-aug", self.text)
        self.assertIn(".pld-spell", self.text)

    def test_rarity_tints_present(self) -> None:
        self.assertIn('data-rarity="prismatic"', self.text)

    def test_responsive_media_query(self) -> None:
        self.assertIn("@media", self.text)

    def test_uses_fs_token(self) -> None:
        self.assertIn("var(--fs-", self.text)


class ModeFixtureDataTests(unittest.TestCase):
    """The panel renders from the loaded last_match mock; pin that the
    committed ARAM/Arena fixtures carry the loadout fields it consumes."""

    def test_aram_mock_has_runes_and_spells(self) -> None:
        en = json.loads(_read(ARAM_MOCK))["match"]["enriched"]
        runes = en.get("runes") or {}
        self.assertTrue(runes.get("keystone"), "ARAM mock needs a keystone")
        self.assertTrue(en.get("spell1_id"), "ARAM mock needs spell1_id")

    def test_arena_mock_has_augments(self) -> None:
        en = json.loads(_read(ARENA_MOCK))["match"]["enriched"]
        augs = en.get("arena_augments") or []
        self.assertTrue(
            any(int(x) > 0 for x in augs),
            "Arena mock needs non-zero arena_augments",
        )

    def test_aram_mock_has_no_augments(self) -> None:
        # ARAM has no augments -> rune mode, not augment mode.
        en = json.loads(_read(ARAM_MOCK))["match"]["enriched"]
        augs = en.get("arena_augments") or []
        self.assertFalse(
            any(int(x) > 0 for x in augs),
            "ARAM mock must not carry augments",
        )


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list:
        return [(i, b) for i, b in enumerate(path.read_bytes()) if b > 0x7F]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
