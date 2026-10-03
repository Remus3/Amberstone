"""ROADMAP.md row ids must be unique.

WHY
---
The 2026-09-20c wrap filed RM-479 .. RM-488 while RM-486 / RM-487 / RM-488 were
already heading rows in the same file, so each of those three ids headed TWO
rows (one later shipped, so "RM-487 SHIPPED" was ambiguous). The second row of
each pair was renumbered to RM-513 / RM-514 / RM-515 on 2026-10-03. Nothing
guarded it: `tests/test_rm_id_registry_drift.py` checks that the pinned
next-free id is unallocated, not that an allocated id is used once.

SCOPE
-----
Only the id that HEADS a row is an allocation: a bullet whose bold opener is
`- **[marker] RM-NNN` or `- **RM-NNN`. Ids cited inside a row body (residuals,
"filed as the second RM-486") are references and may repeat freely.

ANCHOR
------
An empty enumeration would pass a bare uniqueness check, so the test also
requires a floor of headed rows and that a known row (RM-512) is among them.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from pathlib import Path

ROADMAP = Path(__file__).resolve().parent.parent / "ROADMAP.md"

ROW_HEAD = re.compile(r"^\s*- \*\*(?:\[[^\]]*\] )?RM-(\d+)\b", re.MULTILINE)

# Measured 2026-10-03: 79 headed rows. A floor well under that, so routine
# archiving does not trip it, but a regex that stops matching does.
MIN_HEADED_ROWS = 20


def headed_ids(text: str) -> list[int]:
    return [int(m.group(1)) for m in ROW_HEAD.finditer(text)]


class RoadmapRmIdsUnique(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = headed_ids(ROADMAP.read_text(encoding="utf-8"))

    def test_enumeration_is_not_empty(self) -> None:
        self.assertGreaterEqual(
            len(self.ids),
            MIN_HEADED_ROWS,
            f"only {len(self.ids)} RM-headed rows found in ROADMAP.md - "
            "the row-head regex has probably stopped matching",
        )
        self.assertIn(512, self.ids, "known row RM-512 not enumerated")

    def test_no_row_id_heads_two_rows(self) -> None:
        dups = sorted(i for i, n in Counter(self.ids).items() if n > 1)
        self.assertEqual(
            [],
            dups,
            "RM ids heading more than one ROADMAP.md row: "
            + ", ".join(f"RM-{i}" for i in dups)
            + ". Renumber the newer row to the next free id pinned in "
            "docs/DS_SWEEP_TRACKER.md and move the pin.",
        )

    def test_detector_catches_a_duplicate(self) -> None:
        text = (
            "- **[!] RM-486: one row** - body.\n"
            "- **[x] RM-487 SHIPPED: other** - cites RM-486.\n"
            "- **[!] RM-486: same id again** - body.\n"
        )
        ids = headed_ids(text)
        self.assertEqual([486, 487, 486], ids)
        self.assertEqual({486: 2, 487: 1}, dict(Counter(ids)))


if __name__ == "__main__":
    unittest.main()
