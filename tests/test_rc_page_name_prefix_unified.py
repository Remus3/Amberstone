"""OPEN1 (ROADMAP item 210): unified RC LCU page-name prefix guard.

Every NON-frozen RC rune-page / item-set producer must emit the single
canonical "RC: " prefix. The convergence itself shipped earlier:
  - coaches/loadout_resolver.py  (item 178 baked the identity string)
  - dashboard/routes_loadout.py  (item 213 removed the "RC Experimental - " path)
  - dashboard/routes_sr_draft.py (born "RC: ")
  - lcu/lcu_rune_writer.RuneWriter.PAGE_PREFIX
  - tools/lcu_agent.py           (apply_runes default "RC: Auto")
This module pins that contract so a future edit cannot silently re-diverge.

EXCLUDED: lcu/lcu_client.py is FROZEN (CLAUDE.md frozen-file list) and still
carries the legacy _RC_PAGE_PREFIX = "RC - ". It is a self-contained internal
constant with no non-frozen seam to route around, so OPEN1 skips it per the
directive. It is functionally harmless: the agent-side delete filter in
tools/lcu_agent.py matches all three historical 3-char prefixes
("RC ", "RC:", "RC-"), so an "RC - " page is still reclaimed (the item-210
max-owned-pages incident fix). test_wipe_filter_covers_all_legacy_prefixes
guards that the filter is never narrowed back to "RC: " only.
"""

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_NON_FROZEN_PRODUCERS = (
    "coaches/loadout_resolver.py",
    "dashboard/routes_loadout.py",
    "dashboard/routes_sr_draft.py",
)

# Legacy / divergent prefixes that must NEVER appear in a non-frozen producer.
_LEGACY_PREFIXES = ("RC Experimental", "RC - ")


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


class TestUnifiedRcPagePrefix(unittest.TestCase):

    def test_sr_draft_build_page_name_rc_colon(self) -> None:
        from dashboard.routes_sr_draft import _build_page_name
        name = _build_page_name("Tristana", "primary")
        self.assertTrue(name.startswith("RC: "), name)
        self.assertEqual(name, "RC: Tristana primary (SR)")

    def test_rune_writer_page_prefix_constant(self) -> None:
        from lcu.lcu_rune_writer import RuneWriter
        self.assertEqual(RuneWriter.PAGE_PREFIX, "RC: ")

    def test_non_frozen_producers_use_rc_colon_only(self) -> None:
        for rel in _NON_FROZEN_PRODUCERS:
            src = _read(rel)
            self.assertIn('RC: ', src, f"{rel} lost the canonical 'RC: ' prefix")
            for bad in _LEGACY_PREFIXES:
                self.assertNotIn(
                    bad, src,
                    f"{rel} re-introduced divergent page-name prefix {bad!r}")

    def test_agent_default_page_name_rc_colon(self) -> None:
        # apply_runes default + item-set defaults all flow through "RC: Auto".
        src = _read("tools/lcu_agent.py")
        self.assertIn('cmd.get("page_name", "RC: Auto")', src)

    def test_wipe_filter_covers_all_legacy_prefixes(self) -> None:
        # The frozen lcu_client.py "RC - " holdout is only harmless because the
        # delete filter still reclaims every RC-authored prefix. Item-210 fix:
        # never narrow this back to "RC: " only or the operator's 3-slot account
        # fills up and POST /lol-perks/v1/pages 4xx-fails the whole rune push.
        src = _read("tools/lcu_agent.py")
        for literal in ('"RC "', '"RC:"', '"RC-"'):
            self.assertIn(literal, src,
                          f"wipe filter dropped prefix {literal}")

    def test_lcu_client_is_frozen_holdout(self) -> None:
        # Documents the known, intentionally-skipped divergence so this guard
        # tells the next editor exactly where the lone remaining "RC - " lives.
        src = _read("lcu/lcu_client.py")
        self.assertIn('_RC_PAGE_PREFIX = "RC - "', src)


if __name__ == "__main__":
    unittest.main()
