"""Grep-based smoke tests for OQ12 slice B - PGR normalized carry-metric
benchmark sub-lines.

The /api/last-match payload (backend slice A) gains
``match["carry_normalized"]`` with per-metric percentile objects
(kp_pct / gold_share_pct / dmg_share_pct, each {value,p25,p50,p75,n,band}).
Slice B renders a small benchmark sub-line under the Gold% / KP% / Damage
stat cells in the live PGR hero grid, and under KP% / Damage in the
detached historical PGR grid (hpgr has NO gold cell - that stays FUTURE).

Old payloads may LACK carry_normalized entirely - the sub-lines must
degrade silently (stay hidden).

Mirrors the cheap text-search precedent set by
``tests/test_last_match_tabs_reframe_dom.py``.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS   = ROOT / "web" / "js" / "panels" / "last_match.js"
HPGR_JS    = ROOT / "web" / "js" / "panels" / "historical_pgr.js"
PANEL_CSS  = ROOT / "web" / "css" / "panels" / "last_match.css"
INDEX_HTML = ROOT / "web" / "index.html"

# (anchor value-span id, bench span id) pairs. The bench span must sit
# INSIDE the same .lm-hero-stat cell div, after the value span.
LIVE_PAIRS = (
    ("lm-gold-share", "lm-gold-share-bench"),
    ("lm-kp",         "lm-kp-bench"),
    ("lm-damage",     "lm-dmg-bench"),
)
HPGR_PAIRS = (
    ("hpgr-kp",     "hpgr-kp-bench"),
    ("hpgr-damage", "hpgr-dmg-bench"),
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _cell_after(html: str, anchor_id: str) -> str:
    """Slice of the stat cell from the anchor value span to the cell's
    closing </div>. The bench span must land inside this window."""
    tail = html.split(f'id="{anchor_id}"', 1)[1]
    return tail.split("</div>", 1)[0]


class HtmlBenchSpanTests(unittest.TestCase):
    """The 5 bench spans exist, each inside its correct stat cell."""

    def test_live_grid_bench_spans_inside_cells(self):
        html = _read(INDEX_HTML)
        for anchor, bench in LIVE_PAIRS:
            cell = _cell_after(html, anchor)
            self.assertIn(f'id="{bench}"', cell,
                          f"{bench} not inside the {anchor} stat cell")

    def test_hpgr_grid_bench_spans_inside_cells(self):
        html = _read(INDEX_HTML)
        for anchor, bench in HPGR_PAIRS:
            cell = _cell_after(html, anchor)
            self.assertIn(f'id="{bench}"', cell,
                          f"{bench} not inside the {anchor} stat cell")

    def test_bench_spans_start_hidden_with_shared_classes(self):
        html = _read(INDEX_HTML)
        for _, bench in LIVE_PAIRS + HPGR_PAIRS:
            span = html.split(f'id="{bench}"', 1)[0].rsplit("<span", 1)[1]
            span += html.split(f'id="{bench}"', 1)[1].split(">", 1)[0]
            self.assertIn("lm-hero-stat-sub", span,
                          f"{bench} missing lm-hero-stat-sub class")
            self.assertIn("lm-bench-sub", span,
                          f"{bench} missing lm-bench-sub class")
            self.assertIn("hidden", span, f"{bench} must start hidden")

    def test_hpgr_grid_has_no_gold_bench(self):
        """hpgr has no Gold% cell - the gold bench stays FUTURE."""
        html = _read(INDEX_HTML)
        self.assertNotIn('id="hpgr-gold-share-bench"', html)


class LastMatchJsTests(unittest.TestCase):
    """last_match.js reads carry_normalized, wires the 3 live bench ids,
    and hides the sub-line when value/p50 are null (old-payload safe)."""

    def test_reads_carry_normalized(self):
        js = _read(PANEL_JS)
        self.assertIn("carry_normalized", js)

    def test_defines_set_bench_sub_helper(self):
        js = _read(PANEL_JS)
        self.assertIn("function _setBenchSub(", js)

    def test_helper_gates_on_value_and_p50_and_hides_on_null(self):
        js = _read(PANEL_JS)
        body = js.split("function _setBenchSub(", 1)[1].split("\n}", 1)[0]
        self.assertIn("metricObj.value != null", body)
        self.assertIn("metricObj.p50 != null", body)
        self.assertIn("hidden = true", body)
        # Idempotent re-render: band classes stripped up front.
        self.assertIn('classList.remove("lm-bench-high", "lm-bench-low")',
                      body)

    def test_wires_three_live_bench_ids(self):
        js = _read(PANEL_JS)
        for _, bench in LIVE_PAIRS:
            self.assertIn(f'"{bench}"', js, f"{bench} not wired in JS")

    def test_tooltip_extended_with_bench_key(self):
        js = _read(PANEL_JS)
        self.assertIn("bench_key", js)
        self.assertIn("ttBase", js)


class HistoricalPgrJsTests(unittest.TestCase):
    """historical_pgr.js duplicates the helper locally (hpgr namespace)
    and wires the 2 hpgr bench ids."""

    def test_reads_carry_normalized(self):
        js = _read(HPGR_JS)
        self.assertIn("carry_normalized", js)

    def test_defines_local_helper(self):
        js = _read(HPGR_JS)
        self.assertIn("function _setBenchSub(", js)

    def test_wires_two_hpgr_bench_ids(self):
        js = _read(HPGR_JS)
        for _, bench in HPGR_PAIRS:
            self.assertIn(f'"{bench}"', js, f"{bench} not wired in JS")


class CssBenchBandTests(unittest.TestCase):
    """.lm-bench-high / .lm-bench-low use the semantic signal tokens and
    introduce NO new font sizes (the sub-line inherits lm-hero-stat-sub)."""

    @staticmethod
    def _rule(css: str, selector: str) -> str:
        tail = css.split(selector, 1)[1]
        return tail.split("{", 1)[1].split("}", 1)[0]

    def test_bench_high_uses_signal_good(self):
        css = _read(PANEL_CSS)
        rule = self._rule(css, ".lm-bench-high")
        self.assertIn("var(--signal-good)", rule)
        self.assertNotIn("font-size", rule)

    def test_bench_low_uses_signal_bad(self):
        css = _read(PANEL_CSS)
        rule = self._rule(css, ".lm-bench-low")
        self.assertIn("var(--signal-bad)", rule)
        self.assertNotIn("font-size", rule)


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes or smart quotes slipped into the touched files.
    BAD dict built via chr() so this file stays clean against its own
    scan."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def _scan(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [name for ch, name in self.BAD.items() if ch in text]

    def test_touched_files_are_ascii_clean(self):
        for p in (PANEL_JS, HPGR_JS, PANEL_CSS):
            self.assertEqual([], self._scan(p), f"non-ASCII glyphs in {p}")
