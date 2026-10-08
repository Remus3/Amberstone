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
requires a floor of headed rows and that the regex enumerates EXACTLY the rows
an independent, regex-free line parser finds. (The anchor used to be one named
row, RM-512; the 2026-10-04e wave archived RM-512 to docs/ROADMAP_HISTORY.md,
which is routine, and the stale anchor went red on CI. A cross-check against a
second parser covers every row and cannot go stale on an archive.)
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


def headed_ids_by_lines(text: str) -> list[int]:
    """Independent of ROW_HEAD: plain string ops on each line."""
    out = []
    for line in text.splitlines():
        rest = line.lstrip()
        if not rest.startswith("- **"):
            continue
        rest = rest[4:]
        if rest.startswith("["):
            close = rest.find("] ")
            if close < 0:
                continue
            rest = rest[close + 2:]
        if not rest.startswith("RM-"):
            continue
        digits = ""
        for ch in rest[3:]:
            if not ch.isdigit():
                break
            digits += ch
        if digits and not (rest[3 + len(digits):3 + len(digits) + 1].isalnum()
                           or rest[3 + len(digits):3 + len(digits) + 1] == "_"):
            out.append(int(digits))
    return out


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
        self.assertEqual(
            headed_ids_by_lines(ROADMAP.read_text(encoding="utf-8")),
            self.ids,
            "ROW_HEAD disagrees with the independent line parser - a row head "
            "is being missed (or invented) by the regex",
        )

    def test_line_parser_agrees_on_planted_heads(self) -> None:
        text = (
            "- **[!] RM-486: one row** - body.\n"
            "  - **RM-12 nested** - body.\n"
            "- **[x] RM-487 SHIPPED: other** - cites RM-486.\n"
            "- **Not a row** - cites RM-9.\n"
            "- **[x] RM-48x junk**\n"
        )
        self.assertEqual([486, 12, 487], headed_ids_by_lines(text))
        self.assertEqual(headed_ids(text), headed_ids_by_lines(text))

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
