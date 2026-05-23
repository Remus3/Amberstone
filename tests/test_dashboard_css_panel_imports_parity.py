"""Guard: every web/css/panels/*.css has a matching @import in dashboard.css.

Closes the carries from CLAUDE.md items 146/147/148:
  (a) `web/css/dashboard.css:27` orphan `@import './panels/loading_view.css'`
      (file did NOT exist; browser silently 404'd)
  (b) `web/css/panels/build_order.css` (175 LOC live stylesheet for the
      s214 build-order card used by item_build.js + champ_select.js) was
      MISSING from the @import block, so the browser never loaded it.

Both fixed in the same commit; this test pins parity so the inverse
problems do NOT regress: an orphan @import would 404 (cheap noise +
console warning every cold load), an orphan FILE would be dead-code OR
a missing wire (more important to flag).

The test enumerates both directions:
  - every file in web/css/panels/ MUST have a matching @import
  - every @import in dashboard.css MUST point at an existing file

Failure modes are precise so future-author can act on the diff:
  - "panel CSS file <foo> is not @imported in dashboard.css"
  - "dashboard.css imports <foo> but no file at web/css/panels/<foo>"
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
PANELS_DIR = ROOT / "web" / "css" / "panels"

_IMPORT_RE = re.compile(r"@import\s+['\"]\./panels/([^'\"]+\.css)['\"]")


def _imported_panels() -> set[str]:
    text = DASHBOARD_CSS.read_text(encoding="utf-8")
    return set(_IMPORT_RE.findall(text))


def _panel_files() -> set[str]:
    return {p.name for p in PANELS_DIR.glob("*.css")}


class PanelImportParityTests(unittest.TestCase):

    def test_every_panel_css_file_is_imported(self) -> None:
        files = _panel_files()
        imported = _imported_panels()
        orphan_files = sorted(files - imported)
        self.assertEqual(
            orphan_files, [],
            f"panel CSS file(s) not @imported in dashboard.css: {orphan_files}"
        )

    def test_every_imported_panel_file_exists(self) -> None:
        files = _panel_files()
        imported = _imported_panels()
        orphan_imports = sorted(imported - files)
        self.assertEqual(
            orphan_imports, [],
            f"dashboard.css @imports missing panel file(s): {orphan_imports}"
        )

    def test_build_order_css_is_imported(self) -> None:
        # Specific pin (item 147+148 carry (b)): build_order.css IS a
        # live stylesheet for the s214 build-order card; do NOT regress.
        self.assertIn("build_order.css", _imported_panels())

    def test_loading_view_css_not_imported(self) -> None:
        # Specific pin (item 146+147+148 carry (a)): loading_view.css
        # does NOT exist; the orphan @import was removed; do NOT re-add
        # without first creating the file.
        self.assertNotIn("loading_view.css", _imported_panels())


if __name__ == "__main__":
    unittest.main()
