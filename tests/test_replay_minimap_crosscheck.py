# arch: replay-scrubber minimap (RM-612 / X-12) - death-timer port, node suite, wiring | section=tests | frozen=no
"""RM-612 (directive X-12, external reference I): the past-match minimap layer
on the replay scrubber.

Three things are pinned here, because the pure logic lives in JS:

1. CROSS-CHECK. ``web/js/panels/replay_minimap.js`` ports
   ``core.post_game_score.calculate_death_timer``. The shared table
   ``tests/fixtures/replay_minimap_death_timer.json`` is re-derived from the
   Python function here and asserted against the JS port by the node suite, so
   a change on either side breaks one of the two. The JS base-respawn table is
   also compared to ``DEATH_BRW_SECONDS`` directly.

2. THE NODE SUITE IS EXECUTED, NOT SOURCE-GREPPED. No existing guard runs
   ``web/js/panels/*.test.mjs`` (the panel wrappers pin them by text because
   "CI does not execute node" - tests/test_stats_panel_default_role.py), so a
   new .mjs there would run nowhere. This module runs
   ``replay_minimap.test.mjs`` itself. It ASSERTS that node is on PATH rather
   than skipping, the same posture as tests/test_lane_widget_node_suite.py: a
   guard that excuses itself when its runner is missing is green over its own
   blind spot.

3. WIRING. dev.js imports the module, the scrubber markup carries the canvas and
   the "sampled every 60 s" label, the ring colours resolve from tokens that
   exist (an undefined CSS var fails silently), and the minimap draw path does
   not repaint DOM with innerHTML.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from core.post_game_score import DEATH_BRW_SECONDS, calculate_death_timer

ROOT = Path(__file__).resolve().parent.parent
MODULE_JS = ROOT / "web" / "js" / "panels" / "replay_minimap.js"
MODULE_MJS = ROOT / "web" / "js" / "panels" / "replay_minimap.test.mjs"
DEV_JS = ROOT / "web" / "js" / "panels" / "dev.js"
INDEX_HTML = ROOT / "web" / "index.html"
TOKENS_CSS = ROOT / "web" / "css" / "tokens.css"
PRIMITIVES_CSS = ROOT / "web" / "css" / "panels" / "primitives.css"
FIXTURE = ROOT / "tests" / "fixtures" / "replay_minimap_death_timer.json"
NODE = shutil.which("node")

# Same tally shape as tests/test_lane_widget_node_suite.py (TAP "# pass N" or the
# spec reporter's glyph-prefixed "pass N").
_TALLY = re.compile(
    r"^\s*(?:#\s*|\S\s+)?(tests|pass|fail)[ \t]+(\d+)[ \t]*$", re.M)
# Measured 2026-10-04: the suite reports 18 passing tests. 15 leaves room to
# delete or merge a test without tripping; a runner that loaded nothing lands at 0.
_MIN_PASS = 15


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class DeathTimerCrossCheck(unittest.TestCase):
    def test_fixture_rows_match_python(self):
        cases = json.loads(_read(FIXTURE))["cases"]
        self.assertGreaterEqual(len(cases), 15, "cross-check table is vacuous")
        for c in cases:
            self.assertAlmostEqual(
                calculate_death_timer(c["level"], c["time_ms"]), c["seconds"],
                places=9, msg=f"python drifted from the fixture at {c}")

    def test_fixture_spans_every_tif_band_and_the_clamp(self):
        cases = json.loads(_read(FIXTURE))["cases"]
        minutes = {c["time_ms"] / 60000.0 for c in cases}
        self.assertTrue(any(m < 15 for m in minutes))
        self.assertTrue(any(15 <= m < 30 for m in minutes))
        self.assertTrue(any(30 <= m < 45 for m in minutes))
        self.assertTrue(any(45 <= m < 55 for m in minutes))
        self.assertTrue(any(m >= 55 for m in minutes))
        levels = {c["level"] for c in cases}
        self.assertTrue(levels & {0}, "below-range level pins the clamp")
        self.assertTrue(any(lv > 18 for lv in levels), "above-range level pins the clamp")

    def test_js_brw_table_equals_python(self):
        src = _read(MODULE_JS)
        m = re.search(r"DEATH_BRW_SECONDS\s*=\s*Object\.freeze\(\[(.*?)\]\)", src, re.S)
        self.assertIsNotNone(m, "JS DEATH_BRW_SECONDS table not found")
        js = tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(1)))
        self.assertEqual(js, tuple(DEATH_BRW_SECONDS))


class NodeSuiteRuns(unittest.TestCase):
    def test_node_is_on_path(self):
        self.assertIsNotNone(
            NODE, "node is not on PATH, so replay_minimap.test.mjs cannot run. "
                  "This guard asserts rather than skips; install node.")

    def test_node_suite_passes(self):
        self.assertIsNotNone(NODE, "node missing (see test_node_is_on_path)")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [NODE, "--test", str(MODULE_MJS.relative_to(ROOT))],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300, **kwargs)
        out = proc.stdout + proc.stderr
        tally = {k: int(v) for k, v in _TALLY.findall(out)}
        self.assertEqual(proc.returncode, 0, out[-3000:])
        self.assertEqual(tally.get("fail"), 0, out[-3000:])
        self.assertGreaterEqual(tally.get("pass", 0), _MIN_PASS, out[-3000:])


class ScrubberWiring(unittest.TestCase):
    def test_dev_js_imports_the_module(self):
        self.assertRegex(_read(DEV_JS), r"from\s+['\"]\./replay_minimap\.js['\"]")

    def test_markup_has_canvas_and_honest_label(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="replay-map-canvas"', html)
        self.assertIn("sampled every 60 s", html)

    def test_ring_tokens_exist(self):
        dev = _read(DEV_JS)
        used = set(re.findall(r"_replayMapToken\(\s*['\"](--[a-z0-9-]+)['\"]", dev))
        self.assertTrue(used, "minimap resolves no CSS tokens - ring colours would be literals")
        css = _read(TOKENS_CSS) + _read(ROOT / "web" / "css" / "panels" / "base.css")
        for tok in used:
            self.assertRegex(css, re.escape(tok) + r"\s*:", f"{tok} is not defined")

    def test_map_css_uses_defined_tokens_only(self):
        css_all = "".join(_read(p) for p in (ROOT / "web" / "css").rglob("*.css"))
        defined = set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", css_all))
        block = re.search(r"/\* RM-612 replay minimap \*/(.*?)/\* /RM-612 \*/",
                          _read(PRIMITIVES_CSS), re.S)
        self.assertIsNotNone(block, "RM-612 CSS block markers missing")
        used = set(re.findall(r"var\((--[a-zA-Z0-9-]+)", block.group(1)))
        self.assertTrue(used)
        self.assertEqual(used - defined, set(), "undefined CSS vars fail silently")

    def test_draw_path_is_canvas_only(self):
        dev = _read(DEV_JS)
        m = re.search(r"function _replayMapDraw\(.*?\n}\n", dev, re.S)
        self.assertIsNotNone(m, "_replayMapDraw not found")
        self.assertNotIn("innerHTML", m.group(0))

    def test_queue_2400_hides_the_map(self):
        dev = _read(DEV_JS)
        self.assertIn("buildModel(", dev)
        self.assertRegex(dev, r"model\.hidden")


if __name__ == "__main__":
    unittest.main()
