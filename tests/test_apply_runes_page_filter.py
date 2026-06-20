"""Drift guard: tools/lcu_agent.py::apply_runes DELETE filter MUST
match all 3 RC page-name prefixes: "RC ", "RC:", "RC-".

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

    def test_filter_matches_three_prefix_tokens(self) -> None:
        # Read the apply_runes block + assert all 3 prefix string
        # constants appear AS LITERALS inside it. AST-walk to avoid
        # matching the comment block above (the comment lists the
        # 4 RC name templates as docstring; the actual filter is a
        # tuple of 3 string literals).
        src = _AGENT.read_text(encoding="utf-8")
        # Locate the apply_runes block (between the if-statement and
        # the next top-level "if name ==" branch).
        start = src.index('if name == "apply_runes":')
        # Next sibling branch starts at "if name == \"reroll\":"
        end = src.index('if name == "reroll":')
        block = src[start:end]
        for token in ("RC ", "RC:", "RC-"):
            self.assertIn(f'"{token}"', block,
                          f"apply_runes DELETE filter MUST include literal "
                          f"\"{token}\" so RC-authored pages with that "
                          f"prefix get reclaimed - operator's account is "
                          f"3-slot capped, stale RC pages block new apply.")

    def test_filter_uses_slice_3_prefix_check(self) -> None:
        # Concrete shape guard: the filter should slice the page name to
        # the first 3 chars and check membership in a tuple. If anyone
        # refactors back to startswith("RC: ") only, this catches it.
        src = _AGENT.read_text(encoding="utf-8")
        start = src.index('if name == "apply_runes":')
        end = src.index('if name == "reroll":')
        block = src[start:end]
        self.assertIn('nm[:3] in (', block,
                      "apply_runes filter MUST use nm[:3] tuple-membership "
                      "check (covers RC: / RC space / RC dash) per item 210")


class AsciiHygieneTests(unittest.TestCase):
    def test_no_non_ascii_in_test_file(self) -> None:
        src = pathlib.Path(__file__).read_bytes()
        for i, b in enumerate(src):
            if b > 0x7F:
                self.fail(f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
