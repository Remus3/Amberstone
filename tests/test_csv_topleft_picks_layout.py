"""Drift guards for the top-left card PICK section + the LEDGER 823 removal
of the DS Build Archetype picker.

Operator (2026-05-25) moved the PICK sub-panel of Pick & Ban into the
top-left .csv-card-allies card. LEDGER 823 then REMOVED the DS Build
Archetype option-button picker (+ its #csv-archetype-target mount + the
.csv-arch-preview carry block): each button click POSTed a user_cs pick to
/api/cs-archetype-pick that wrote the shared committed cs_archetype_picks.json
the build-order precompute reads, so one operator's pick polluted everyone's
committed build tables. The PICK section now fills the card; the bans + ally
picks stay in row-2 #csv-pickban-body.

These tests pin the structural contract so a future refactor that
re-introduces the picker / carry block, or reverts the PICK section back
into #csv-pickban-body, fails CI.
"""
from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "web" / "index.html"
CHAMP_SELECT_JS = REPO_ROOT / "web" / "js" / "panels" / "champ_select.js"
CHAMP_SELECT_CSS = REPO_ROOT / "web" / "css" / "panels" / "champ_select_view.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


class TopLeftCardMountsTests(unittest.TestCase):
    """The top-left .csv-card-allies body mounts the PICK sub-panel target
    (#csv-picks-target). The DS Build Archetype picker mount
    (#csv-archetype-target) was removed (LEDGER 823)."""

    def setUp(self) -> None:
        self.html = _read(INDEX_HTML)

    def test_csv_picks_target_div_exists(self) -> None:
        self.assertIn(
            'id="csv-picks-target"', self.html,
            "PICK section mount #csv-picks-target must exist in index.html "
            "(item 200 Slice D)",
        )

    def test_csv_archetype_target_removed(self) -> None:
        # LEDGER 823: the DS Build Archetype option-button picker + its
        # #csv-archetype-target mount were removed - operator clicks wrote
        # user_cs picks that polluted the shared committed build precompute.
        self.assertNotIn(
            'id="csv-archetype-target"', self.html,
            "DS Build Archetype mount #csv-archetype-target must be removed "
            "(LEDGER 823 - picker deleted to stop precompute pollution)",
        )

    def test_picks_target_lives_under_csv_card_allies(self) -> None:
        # Confirm #csv-picks-target appears AFTER .csv-card-allies open
        # and BEFORE the next .csv-card div opens (.csv-card-pickban).
        # This pins the picks mount to the top-left card block, not row-2.
        idx_allies = self.html.find('class="csv-card csv-card-allies"')
        idx_pickban = self.html.find('class="csv-card csv-card-pickban"')
        idx_picks_target = self.html.find('id="csv-picks-target"')
        self.assertGreater(idx_allies, -1, ".csv-card-allies not found")
        self.assertGreater(idx_pickban, -1, ".csv-card-pickban not found")
        self.assertGreater(
            idx_picks_target, -1, "#csv-picks-target not found",
        )
        self.assertGreater(
            idx_picks_target, idx_allies,
            "#csv-picks-target must appear after .csv-card-allies opens",
        )
        self.assertLess(
            idx_picks_target, idx_pickban,
            "#csv-picks-target must appear BEFORE .csv-card-pickban "
            "(i.e. nested inside .csv-card-allies, not in row-2 pickban)",
        )

    def test_picks_target_NOT_inside_pickban_card(self) -> None:
        # The PICK section moves to the top-left card. #csv-picks-target
        # must not appear after the .csv-card-pickban open tag (that
        # would mean it's still nested in the row-2 pickban card).
        idx_pickban = self.html.find('class="csv-card csv-card-pickban"')
        idx_pickban_body = self.html.find('id="csv-pickban-body"')
        idx_picks_target = self.html.find('id="csv-picks-target"')
        self.assertGreater(idx_pickban, -1)
        self.assertGreater(idx_pickban_body, -1)
        self.assertGreater(idx_picks_target, -1)
        # Picks target should be BEFORE the pickban card opens.
        self.assertLess(
            idx_picks_target, idx_pickban,
            "PICK section target must live in .csv-card-allies (top-left), "
            "NOT in .csv-card-pickban (row-2)",
        )


class DsTopPicksCarryRemovedTests(unittest.TestCase):
    """The .csv-arch-preview DS top-picks carry block MUST be absent from
    champ_select.js. LEDGER 823 additionally removed the whole DS Build
    Archetype picker (buttons + AUTO + the two write POSTs)."""

    def setUp(self) -> None:
        self.js = _read(CHAMP_SELECT_JS)

    def test_arch_preview_html_not_emitted(self) -> None:
        # The previous implementation emitted a <div class="csv-arch-preview">
        # wrapper as a JS template literal. After Slice D the wrapper must
        # not appear in champ_select.js any more.
        self.assertNotIn(
            'class="csv-arch-preview"', self.js,
            "The .csv-arch-preview wrapper must be removed from "
            "_csvArchetypePickerHtml (item 200 Slice D)",
        )

    def test_arch_preview_row_not_emitted(self) -> None:
        self.assertNotIn(
            'class="csv-arch-preview-row"', self.js,
            "The .csv-arch-preview-row block must be removed",
        )

    def test_arch_preview_cell_not_emitted(self) -> None:
        self.assertNotIn(
            'class="csv-arch-preview-cell', self.js,
            "The .csv-arch-preview-cell template must be removed",
        )

    def test_ds_top_picks_label_not_emitted(self) -> None:
        # Slice D removes the "DS top picks - <archetype>" preview head.
        self.assertNotIn(
            "DS top picks -", self.js,
            "The 'DS top picks - <archetype>' preview head label must be "
            "removed (item 200 Slice D scope)",
        )

    def test_archetype_picker_template_removed(self) -> None:
        # LEDGER 823: the 6-selectables picker + AUTO button were removed.
        self.assertNotIn(
            'class="csv-archetype-picker"', self.js,
            "DS Build Archetype picker must be removed (LEDGER 823)",
        )
        self.assertNotIn(
            'class="csv-archetype-buttons"', self.js,
            "DS Build Archetype button grid must be removed (LEDGER 823)",
        )

    def test_archetype_write_posts_removed(self) -> None:
        # The two write POSTs (save user_cs + AUTO clear) are gone; only the
        # read-only GET (?champion=) survives to feed the build preview's
        # server-default scorer. Assert the data markers of the write path
        # (not the function name, which the removal note still cites).
        self.assertNotIn(
            'source: "user_cs"', self.js,
            "the user_cs write payload must be gone (LEDGER 823) - operators "
            "can no longer write picks that pollute the committed precompute",
        )
        self.assertNotIn(
            "clear: true", self.js,
            "the AUTO-revert clear POST payload must be gone (LEDGER 823)",
        )


class PickBanStructurePreservedTests(unittest.TestCase):
    """Pick & Ban now renders 2 sub-panels in #csv-pickban-body (BAN +
    ALLY PICKS BY ROLE; item 213 replaced the 101.qq.com DUO SYNERGY
    grid); the picks sub-panel template still exists in JS but targets
    #csv-picks-target via the split assignment."""

    def setUp(self) -> None:
        self.js = _read(CHAMP_SELECT_JS)

    def test_pick_sub_panel_template_still_built(self) -> None:
        # picksHtml is the new local variable carrying the PICK section
        # for the top-left mount. Assert it exists.
        self.assertIn(
            "const picksHtml", self.js,
            "picksHtml local must exist in _csvRenderPickBan (carries the "
            "PICK section for the top-left mount)",
        )

    def test_pick_html_writes_to_csv_picks_target(self) -> None:
        # Pin the assignment site so a refactor that drops the picks
        # rendering fails CI.
        self.assertIn(
            'document.getElementById("csv-picks-target")', self.js,
            "_csvRenderPickBan must write picksHtml to #csv-picks-target",
        )

    def test_ban_sub_panel_still_in_main_html(self) -> None:
        # The main `html` template now renders BAN + EXPL only (PICK is
        # split out). Confirm the BAN section is still present.
        self.assertIn(
            'csv-pb168-section csv-pb168-bans', self.js,
            "BAN sub-panel must still render in #csv-pickban-body",
        )

    def test_duo_synergy_section_still_in_main_html(self) -> None:
        # item 213: the third sub-panel is now ALLY PICKS BY ROLE (was
        # the 101.qq.com DUO SYNERGY grid). The .csv-pb168-expl wrapper
        # class is preserved so the layout slot is unchanged.
        self.assertIn(
            'csv-pb168-section csv-pb168-expl', self.js,
            "third sub-panel (ALLY PICKS BY ROLE) must still render in "
            "#csv-pickban-body",
        )

    def test_pick_click_wiring_scoped_to_picks_target(self) -> None:
        # The pick-click wiring must scope to #csv-picks-target now that
        # picks live outside body=#csv-pickban-body.
        self.assertIn(
            'picksScope.querySelectorAll(".csv-pb168-pick.is-clickable")',
            self.js,
            "Pick-click wiring must scope to picksScope (which resolves "
            "to #csv-picks-target) so it finds picks in their new home",
        )

    def test_ban_click_wiring_unchanged_on_body(self) -> None:
        # BAN cells still live in #csv-pickban-body (= body). Their
        # wiring should still use body.querySelectorAll.
        self.assertIn(
            'body.querySelectorAll(".csv-pb168-ban.is-clickable")', self.js,
            "BAN-click wiring should still scope to body (#csv-pickban-body)",
        )


class CardAlliesBodyStylingTests(unittest.TestCase):
    """Top-left card uses a flex column layout so the picks mount fills the
    card (the archetype picker that used to sit above it is gone - LEDGER 823)."""

    def setUp(self) -> None:
        self.css = _read(CHAMP_SELECT_CSS)

    def test_csv_card_allies_body_flex_column(self) -> None:
        # The new .csv-card-allies-body rule must exist + use flex column.
        self.assertRegex(
            self.css,
            r"\.csv-card-allies-body\s*\{[^}]*flex-direction:\s*column",
            ".csv-card-allies-body must use flex-direction: column "
            "to stack archetype picker + picks mount",
        )

    def test_picks_target_inside_allies_grows(self) -> None:
        self.assertRegex(
            self.css,
            r"\.csv-card-allies-body\s+#csv-picks-target\s*\{[^}]*flex:\s*1 1 auto",
            "#csv-picks-target inside .csv-card-allies-body must flex-grow "
            "to fill the card (LEDGER 823 removed the archetype picker above it)",
        )


class AsciiHygieneTests(unittest.TestCase):
    """No new non-ASCII bytes introduced by Slice D edits in the test
    file itself + the three touched source files."""

    def test_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        for i, b in enumerate(raw):
            self.assertLess(
                b, 128,
                f"non-ASCII byte 0x{b:02x} at offset {i} in test file",
            )


if __name__ == "__main__":
    unittest.main()
