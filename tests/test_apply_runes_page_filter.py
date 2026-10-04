"""Drift guard: tools/lcu_agent.py::apply_runes DELETE filter MUST reclaim
every RC-authored page (item 210) and - since RM-297a - must NOT match user
pages on a 3-char stem ("RC ", "RC:", "RC-"), which deleted "RC Main" etc.

Item 210 (2026-05-27): operator-reported "runes not pushing during champ
select for the selected champ". Root cause = the prior filter only
matched "RC: " (colon+space). The stuck LCU page on the operator's
account was named "RC Experimental - Vayne" (legacy em-dash + "RC "
prefix from dashboard/routes_loadout.py:120). With the account's
3-slot limit + all 3 slots full + the DELETE filter missing the legacy
name, POST /lol-perks/v1/pages 4xx'd silently for every rune apply.

This test pins the broader filter so a future refactor cannot regress
the same class of bug.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_AGENT = _ROOT / "tools" / "lcu_agent.py"


class ApplyRunesPageFilterTests(unittest.TestCase):
    def test_apply_runes_block_present(self) -> None:
        src = _AGENT.read_text(encoding="utf-8")
        self.assertIn('if name == "apply_runes":', src,
                      "apply_runes handler MUST exist in the agent")

    def test_filter_reclaims_every_rc_authored_prefix(self) -> None:
        # Item 210's stuck page was "RC Experimental - Vayne". RM-297a
        # (2026-10-03) replaced the 3-char stem filter - which ALSO deleted
        # user pages named "RC Main" / "RC-smurf" / "RC:test" - with the
        # shared whole-prefix rule; this keeps item 210's guarantee
        # BEHAVIOURALLY instead of by grepping literals.
        import sys
        sys.path.insert(0, str(_ROOT))
        from lcu.lcu_rune_writer import is_rc_owned_page
        for name in ("RC Experimental - Vayne", "RC: Lulu (ARAM)",
                     "RC - Ashe (SR)"):
            self.assertTrue(is_rc_owned_page(
                {"id": 1, "name": name, "isDeletable": True}), name)

    def test_filter_no_longer_matches_user_pages_on_a_3_char_stem(self) -> None:
        # The old shape pinned here (`nm[:3] in (...)`) IS the RM-297a bug.
        src = _AGENT.read_text(encoding="utf-8")
        start = src.index('if name == "apply_runes":')
        end = src.index('if name == "reroll":')
        block = src[start:end]
        self.assertIn("is_rc_owned_page(pg)", block)
        self.assertNotIn("nm[:3] in (", block)


class AsciiHygieneTests(unittest.TestCase):
    def test_no_non_ascii_in_test_file(self) -> None:
        src = pathlib.Path(__file__).read_bytes()
        for i, b in enumerate(src):
            if b > 0x7F:
                self.fail(f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
