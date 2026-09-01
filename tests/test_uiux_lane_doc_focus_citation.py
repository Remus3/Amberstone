"""Anti-drift guard for the lane-4 (uiux) doctrine's focus-preservation trap.

`tools/headless-uiux.md` section 6 trap 2 states the rule "any repainting host
preserves document.activeElement across the repaint" and names the pattern a
slice should copy. On 2026-09-01 that citation was measured FALSE: it pointed at
`web/js/panels/dev.js:512-513` + `:573-574`, and `dev.js` contains no
focus-preservation code whatsoever. A build slice sent to copy those lines found
nothing and had to re-derive the pattern mid-flight.

That is the expensive failure mode this file exists to stop: a doctrine doc that
tells the next agent to copy code which is not there. A doc is not a source of
truth unless something fails when it drifts (CLAUDE.md: "a spec edited without
the guard that enforces it is a wish, not a guideline").

So this pins three things, all cheap and all falsifiable:
  1. the canonical-pattern file the doc names really does implement it;
  2. the guard test the doc names really exists;
  3. the refuted `dev.js` citation does not creep back in.

Deliberately NOT pinned: line numbers inside the pattern file. Those churn on
every edit and pinning them would make this guard a maintenance tax that gets
deleted rather than a signal. Symbol names are the stable contract.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LANE_DOC = REPO / "tools" / "headless-uiux.md"
PATTERN_SRC = REPO / "web" / "js" / "lib" / "overlay_layout.js"
OTHER_HALF = REPO / "web" / "js" / "panels" / "overlay_ds_controls.js"
GUARD_TEST = REPO / "tests" / "snapshot_panels" / "test_overlay_launcher_menu.py"

# The capture/restore pair the doc points a slice at.
PATTERN_SYMBOLS = ("_captureMenuFocus", "_restoreMenuFocus")


class LaneDocFocusCitation(unittest.TestCase):
    """The doctrine's trap-2 citation must resolve to code that exists."""

    def setUp(self) -> None:
        self.assertTrue(LANE_DOC.is_file(), f"missing lane doc: {LANE_DOC}")
        self.doc = LANE_DOC.read_text(encoding="utf-8")

    def test_canonical_pattern_file_is_cited_and_implements_the_pattern(self) -> None:
        self.assertIn(
            "web/js/lib/overlay_layout.js",
            self.doc,
            "trap 2 must name the canonical focus-preservation pattern file",
        )
        self.assertTrue(PATTERN_SRC.is_file(), f"missing {PATTERN_SRC}")
        src = PATTERN_SRC.read_text(encoding="utf-8")
        for sym in PATTERN_SYMBOLS:
            self.assertIn(
                sym,
                src,
                f"{PATTERN_SRC.name} must define {sym} - the doc sends slices here to copy it",
            )
            self.assertIn(
                sym, self.doc, f"trap 2 must name {sym} so a slice can find it"
            )
        self.assertIn(
            "document.activeElement",
            src,
            "the canonical pattern must actually read document.activeElement",
        )

    def test_the_other_half_citation_resolves(self) -> None:
        """The 'never clobber a control the operator is in' half is real."""
        self.assertIn("web/js/panels/overlay_ds_controls.js", self.doc)
        self.assertTrue(OTHER_HALF.is_file(), f"missing {OTHER_HALF}")
        self.assertIn(
            "document.activeElement",
            OTHER_HALF.read_text(encoding="utf-8"),
            "overlay_ds_controls.js is cited as the value-clobber guard; it must read activeElement",
        )

    def test_named_guard_test_exists(self) -> None:
        self.assertIn("tests/snapshot_panels/test_overlay_launcher_menu.py", self.doc)
        self.assertTrue(
            GUARD_TEST.is_file(),
            "trap 2 names this guard; a doc citing a nonexistent test is the defect this file stops",
        )

    def test_refuted_dev_js_citation_does_not_return(self) -> None:
        """dev.js has no focus code - it is an OPEN instance of the defect.

        Measured 2026-09-01: a repo-wide grep for activeElement across web/js/
        returns only overlay_ds_controls.js and overlay_layout.js. If someone
        re-adds dev.js as the pattern to copy, this fails loudly.
        """
        dev = REPO / "web" / "js" / "panels" / "dev.js"
        if dev.is_file():
            self.assertNotIn(
                "activeElement",
                dev.read_text(encoding="utf-8"),
                "dev.js gained focus-preservation code - update the lane doc, then this guard",
            )
        # The doc may DISCUSS dev.js as a counter-example (it does), but must not
        # present it as the pattern to copy.
        self.assertNotIn(
            "Pattern: `web/js/panels/dev.js",
            self.doc,
            "the refuted dev.js pattern citation is back - it names code that does not exist",
        )


if __name__ == "__main__":
    unittest.main()
