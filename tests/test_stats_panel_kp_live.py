"""Overlay stats-panel KP row: the You cell must read the LIVE producer.

Bug (measured live 2026-07-20, SR game): web/js/panels/stats_panel.js painted
the You side of the KP row with a hardcoded "-" and the header comments
asserted "KP has no live producer", so the dash read as honest. The premise
was false - dashboard/_liveclient.py:250 emits
``out["kill_participation_pct"] = f"{pct}%"`` and it reaches the dashboard on
both /api/state paths (liveclient.kill_participation_pct and
coach.kill_participation_pct, both "43%" at probe time). The Avg side of the
same row already rendered the rank-tier number (kp avg 58 from
/api/rank-tier-bench), so the row showed a placeholder next to real data.

Format note: the producer emits a STRING WITH A PERCENT SIGN ("44%"); the
benchmark column is a bare number in percent points (58). The You cell must
normalize to the same shape for a like-for-like compare, and must still fall
back to the honest "-" when the key is absent - _liveclient.py omits it
entirely at 0 team kills (tests/test_liveclient_kp.py pins that).

Arena is unaffected: _ROWS_BY_MODE.ARENA is ["lvl", "kda"] - there is no kp
row to fill (pinned below so a future Arena row-set change re-reads this).

Two layers, mirroring tests/test_champ_select_ban_provenance_dom.py:
- StaticSourceGuards: grep-style contract on the .js source (the repo's
  page-JS test convention - pathlib read + substring asserts).
- KpValueBehaviorTests: extract the real _kpPct + _fmt helpers from the
  source and run them in node. Skipped when node is unavailable.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATS_JS = ROOT / "web" / "js" / "panels" / "stats_panel.js"
_NODE = shutil.which("node")


def _read_source() -> str:
    return STATS_JS.read_text(encoding="utf-8")


def _balanced_span(src: str, anchor: str,
                   opens: str = "{", closes: str = "}") -> str:
    """Source span from `anchor` through the balanced close of the first
    `opens` bracket at/after it. Defaults to braces so a function anchor
    captures its BODY (not just the parameter list)."""
    assert anchor in src, f"anchor not found in source: {anchor!r}"
    i = src.index(anchor)
    j = i
    while src[j] not in opens:
        j += 1
    depth = 0
    for k in range(j, len(src)):
        if src[k] in opens:
            depth += 1
        elif src[k] in closes:
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError(f"unbalanced span for anchor: {anchor!r}")


class StaticSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read_source()

    def test_you_kp_cell_is_not_a_hardcoded_dash(self) -> None:
        self.assertNotRegex(
            self.src,
            r'_setCell\(\s*mount,\s*"sp-you",\s*"kp",\s*"-"\s*\)',
            'the You KP cell must read the live producer, not paint "-"',
        )

    def test_you_kp_cell_reads_the_live_field(self) -> None:
        self.assertIn("kill_participation_pct", self.src)
        self.assertRegex(
            self.src,
            r'_setCell\(\s*mount,\s*"sp-you",\s*"kp",'
            r'.*_kpPct\(\s*lc\.kill_participation_pct\s*\)',
            "the KP You cell must pipe lc.kill_participation_pct through _kpPct",
        )

    def test_stale_no_live_producer_comments_are_gone(self) -> None:
        for stale in ("KP has no live producer",
                      "no live KP producer",
                      "no Live Client producer"):
            self.assertNotIn(
                stale, self.src,
                f"stale comment survived and would mislead the next reader: {stale!r}",
            )

    def test_arena_row_set_still_has_no_kp_row(self) -> None:
        # The Arena branch never asks for a KP cell (no seed, "no benchmark").
        self.assertRegex(
            self.src, r'ARENA:\s*\[\s*"lvl"\s*,\s*"kda"\s*\]')

    def test_source_is_ascii(self) -> None:
        self.assertEqual([b for b in STATS_JS.read_bytes() if b > 0x7F], [])


@unittest.skipUnless(_NODE, "node not on PATH")
class KpValueBehaviorTests(unittest.TestCase):
    """The real helpers, executed: percent-suffixed strings normalize to the
    benchmark column's bare-number shape; absent/garbage stays an honest "-"."""

    @classmethod
    def setUpClass(cls) -> None:
        src = _read_source()
        harness = (
            _balanced_span(src, "function _fmt(") + "\n"
            + _balanced_span(src, "function _kpPct(") + "\n"
            + "const cases = ["
            + '"44%", "125%", "0%", "43", 43, "", "  ", "n/a", null, undefined];\n'
            + "process.stdout.write(JSON.stringify("
            + "cases.map((c) => _fmt(_kpPct(c)))));\n"
        )
        cls._td = tempfile.mkdtemp()
        harness_path = Path(cls._td) / "kp_harness.mjs"
        harness_path.write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            [_NODE, str(harness_path)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"node harness failed ({proc.returncode}): {proc.stderr}")
        cls.out = json.loads(proc.stdout)

    def test_percent_string_renders_as_bare_number(self) -> None:
        # "44%" -> "44": same shape as the Avg cell (_fmt of 58 -> "58").
        self.assertEqual(self.out[0], "44")

    def test_over_hundred_percent_is_preserved(self) -> None:
        # KP can exceed 100% (tests/test_liveclient_kp.py pins "125%").
        self.assertEqual(self.out[1], "125")

    def test_zero_percent_is_a_real_value_not_a_dash(self) -> None:
        self.assertEqual(self.out[2], "0")

    def test_bare_number_forms_still_work(self) -> None:
        self.assertEqual(self.out[3], "43")
        self.assertEqual(self.out[4], "43")

    def test_absent_or_garbage_stays_an_honest_dash(self) -> None:
        # "", "  ", "n/a", null, undefined -> the reserved-slot dash.
        self.assertEqual(self.out[5:], ["-", "-", "-", "-", "-"])


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual([b for b in Path(__file__).read_bytes() if b > 0x7F], [])

    def test_no_dash_glyph_drift(self) -> None:
        # Repo hard rule: no em/en dashes, no smart quotes in authored text.
        banned = re.compile("[\\u2013\\u2014\\u2018\\u2019\\u201c\\u201d]")
        self.assertIsNone(banned.search(_read_source()))


if __name__ == "__main__":
    unittest.main()
