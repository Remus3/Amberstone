"""A6 (OVERLAY_BUILD_MASTER_PLAN WP-A6): strip the specified per-panel name
headers from the static overlay panes.

Per the plan's named set (CALL / BUILD / FIGHT MODEL / MAP / CDS):
  - CALL, FIGHT MODEL, MAP: their `<div class="am-pane-head">TITLE</div>` is
    removed outright (pure decorative titles, no JS consumer).
  - CDS: only the `<span>CDS</span>` name label is dropped; the `cd-ledger-head`
    collapse head + its `cd-chev` chevron STAY (cd_ledger.js wires the collapse
    click + updates the chevron on that head - removing it would break collapse).
  - BUILD: NOT touched here - its header carries the `am-draft-elo` chip and is
    folded into Section B (WP-B1).

Grep-style contract test, mirroring tests/test_overlay_a5_enemy_spells_unname_widen
+ a2/a3: pathlib reads + substring asserts on the index.html SOURCE (no jsdom/node
harness for page code). index.html carries a pre-existing non-ASCII dashboard-glyph
tail (see test_overlay_a2_no_enemy_summs), out of this WP's scope - so no full-file
ASCII assert here; this WP only removes ASCII title divs.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO / "web" / "index.html"


class NameHeadersRemoved(unittest.TestCase):
    """CALL / FIGHT MODEL / MAP title divs + the CDS label are gone."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_call_header_removed(self):
        self.assertNotIn('<div class="am-pane-head">CALL</div>', self.html)

    def test_fight_model_header_removed(self):
        self.assertNotIn('<div class="am-pane-head">FIGHT MODEL</div>', self.html)

    def test_map_header_removed(self):
        self.assertNotIn('<div class="am-pane-head">MAP</div>', self.html)

    def test_cds_name_label_removed(self):
        self.assertNotIn("<span>CDS</span>", self.html)


class FunctionalHeadersPreserved(unittest.TestCase):
    """BUILD (B1's job + draft-elo chip) and the CDS collapse control stay."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_build_header_kept_for_section_b(self):
        # BUILD header is folded into WP-B1, not A6 - it must survive here.
        self.assertIn('am-pane-head">BUILD', self.html)

    def test_draft_elo_chip_survives(self):
        # The draft-elo chip lives inside the BUILD header.
        self.assertIn('id="am-draft-elo"', self.html)

    # Riot compliance 2026-08-11: the CDS collapse head + chevron cases were
    # removed with the cooldown ledger (banned enemy summ-spell cooldowns +
    # ultimate timers). They must stay gone, which the case below asserts.
    def test_cds_ledger_mounts_stay_removed(self):
        for gone in ('id="cd-ledger-head"', 'id="cd-ledger-body"', "cd-chev"):
            self.assertNotIn(gone, self.html, f"{gone} must stay removed")


class PaneBodiesIntact(unittest.TestCase):
    """Removing the title bands must not touch the pane body mounts."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_all_pane_bodies_present(self):
        for mount in ('id="am-call-body"', 'id="ovds-body"',
                      'id="am-map-body"'):
            self.assertIn(mount, self.html, f"{mount} pane body must survive")


if __name__ == "__main__":
    unittest.main()
