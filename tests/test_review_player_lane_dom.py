# arch: RM-641 S5 Replay video lane wiring + render-once + token guards | section=tests | frozen=no
"""RM-641 (directive X-41, ADR-016): the S5 Replay video lane.

Source checks on the thin DOM layer (the logic is node-tested in
web/js/panels/review_player_model.test.mjs):
  * the lane mounts inside the Replay main pane, HIDDEN by default (it is
    revealed only when GET /api/recordings/<id> reports a servable video);
  * dev.js hands the selected match (and the tracked team) to it;
  * markers render ONCE per match (signature guard) and are only
    class-toggled afterwards, never repainted through innerHTML;
  * every CSS custom property the new stylesheet reads is defined in the
    shared token sheets (an undefined var() fails silently);
  * the stylesheet is imported.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "web" / "index.html"
PLAYER_JS = ROOT / "web" / "js" / "panels" / "review_player.js"
DEV_JS = ROOT / "web" / "js" / "panels" / "dev.js"
PLAYER_CSS = ROOT / "web" / "css" / "panels" / "review_player.css"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
TOKEN_SHEETS = (ROOT / "web" / "css" / "tokens.css", ROOT / "web" / "css" / "themes.css",
                ROOT / "web" / "css" / "base.css")


def _read(p: Path) -> str:
    assert p.is_file(), f"missing {p}"
    return p.read_text(encoding="utf-8")


def _section(html: str) -> str:
    # The lane container is a div (a nested <section> would end the naive
    # view-replay slice in tests/test_replay_events_panel_dom.py early); it
    # runs up to the timeline ribbon's comment that follows it.
    start = html.index('id="replay-video-section"')
    return html[start:html.index("<!-- s220 PGR S5: Match-V5 timeline", start)]


class MountTests(unittest.TestCase):
    def test_lane_inside_replay_main_pane_and_hidden_by_default(self):
        html = _read(INDEX_HTML)
        pane_at = html.index('<main class="replay-main-pane">')
        pane_end = html.index("</main>", pane_at)
        sec_at = html.index('id="replay-video-section"')
        self.assertTrue(pane_at < sec_at < pane_end, "lane is outside the Replay main pane")
        open_tag = re.search(r'<div[^>]*id="replay-video-section"[^>]*>', html).group(0)
        self.assertIn(" hidden", open_tag)
        sec = _section(html)
        for ident in ("replay-video", "replay-video-lane", "replay-video-cost"):
            self.assertIn(f'id="{ident}"', sec)
        cost_tag = re.search(r'<div[^>]*id="replay-video-cost"[^>]*>', sec).group(0)
        self.assertIn(" hidden", cost_tag)

    def test_dev_js_hands_the_match_to_the_lane(self):
        js = _read(DEV_JS)
        self.assertIn("import { loadReviewPlayer } from './review_player.js';", js)
        self.assertEqual(len(re.findall(r"loadReviewPlayer\(matchId,", js)), 2)

    def test_stylesheet_imported(self):
        self.assertIn("@import './panels/review_player.css';", _read(DASHBOARD_CSS))


class RenderDisciplineTests(unittest.TestCase):
    def test_no_innerhtml_anywhere_in_the_lane(self):
        self.assertNotRegex(_read(PLAYER_JS), r"\.(innerHTML|outerHTML)\s*\+?=")

    def test_markers_render_once_per_signature(self):
        js = _read(PLAYER_JS)
        self.assertRegex(js, r"if \(_RP\.renderedKey === key\) return;")
        self.assertRegex(js, r"if \(_RP\.costKey === key\) return;")

    def test_playhead_only_toggles_classes(self):
        js = _read(PLAYER_JS)
        body = js[js.index("function _syncPlayhead"):js.index("function _onKeydown")]
        self.assertIn("classList.toggle", body)
        self.assertNotIn("replaceChildren", body)
        self.assertNotIn("createElement", body)

    def test_hidden_without_a_servable_video(self):
        js = _read(PLAYER_JS)
        self.assertIn("!d.has_video", js)
        self.assertIn("sec.hidden = false", js)

    def test_logic_comes_from_the_tested_model(self):
        js = _read(PLAYER_JS)
        for name in ("clusterMarkers", "hotkeyAction", "seekTarget", "openTimeS",
                     "costMoments", "markersFromSidecar"):
            self.assertIn(name, js)


class TokenTests(unittest.TestCase):
    def test_every_var_used_is_defined(self):
        css = _read(PLAYER_CSS)
        used = set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", css))
        self.assertTrue(used, "no tokens read - the regex is broken")
        defined: set[str] = set()
        for sheet in TOKEN_SHEETS:
            if sheet.is_file():
                defined |= set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", sheet.read_text(encoding="utf-8")))
        self.assertEqual(sorted(used - defined), [])

    def test_marker_width_matches_the_cluster_radius(self):
        css = _read(PLAYER_CSS)
        model = _read(ROOT / "web" / "js" / "panels" / "review_player_model.js")
        r = int(re.search(r"CLUSTER_RADIUS_PX = (\d+);", model).group(1))
        block = css[css.index(".replay-video-marker {"):]
        w = int(re.search(r"width:\s*(\d+)px;", block).group(1))
        self.assertEqual(w, r, "marker width and cluster radius drifted; markers overlap")


if __name__ == "__main__":
    unittest.main()
