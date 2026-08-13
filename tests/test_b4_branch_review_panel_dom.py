"""B4-e (RM-189): the DECISION BRANCHES card - web/js/panels/branch_review.js.

Post-game replay of the branch set RC captured silently during the game. The
module is driven for real through a stub DOM in node (the
test_b4_client_directive_gate.py idiom) rather than grepped, so these pin
rendered output and not the presence of a call.

Skips cleanly when node is unavailable.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = REPO_ROOT / "web" / "js" / "panels" / "branch_review.js"
INDEX_HTML = REPO_ROOT / "web" / "index.html"
PANEL_CSS = REPO_ROOT / "web" / "css" / "panels" / "branch_review.css"
DASHBOARD_CSS = REPO_ROOT / "web" / "css" / "dashboard.css"
NODE = shutil.which("node")

_MOUNT_IDS = ["lm-branch-review", "lm-br-list", "lm-br-meta", "lm-br-note",
              "lm-br-empty"]

_DOM_STUB = f"""
const mounts = {{}};
function makeMount(id) {{
  return {{ id, innerHTML: "", textContent: "", hidden: true }};
}}
for (const id of {json.dumps(_MOUNT_IDS)}) {{ mounts[id] = makeMount(id); }}
globalThis.document = {{ getElementById: (id) => mounts[id] || null }};
"""


def _payload(**kw):
    base = {
        "game_run_id": "run-one", "game_id": "7412995551", "mode": "aram",
        "my_champion": "Annie", "enemy": "Caitlyn",
        "branches": [
            {"game_time_s": 125.0, "band": "L6", "level": 6, "item_count": 1,
             "choices": [
                 {"key": "A", "label": "Force a short trade",
                  "expected_outcome": "net swing +0.25", "confidence": "high"},
                 {"key": "B", "label": "Back off Caitlyn",
                  "expected_outcome": "play safe", "confidence": "low"}],
             "native_action": "POKE PHASE", "cv_override": None,
             "covered": True, "precompute_excluded": False},
        ],
        "branch_count": 1, "ticks_total": 3, "legacy_rows_skipped": 0,
        "precompute_excluded": False, "truncated": False, "reason": None,
    }
    base.update(kw)
    return base


@unittest.skipIf(NODE is None, "node not available")
class RenderTests(unittest.TestCase):
    def _render(self, data, state=None) -> dict:
        program = (
            _DOM_STUB
            + "(async () => {\n"
            + f"  const m = await import({json.dumps(PANEL_JS.as_uri())});\n"
            + f"  m.renderBranchReview({json.dumps(data)},"
              f" {json.dumps(state)});\n"
            + "  console.log(JSON.stringify({\n"
            + "    html: mounts['lm-br-list'].innerHTML,\n"
            + "    meta: mounts['lm-br-meta'].textContent,\n"
            + "    note: mounts['lm-br-note'].textContent,\n"
            + "    noteHidden: mounts['lm-br-note'].hidden,\n"
            + "    wrapHidden: mounts['lm-branch-review'].hidden,\n"
            + "    emptyHidden: mounts['lm-br-empty'].hidden,\n"
            + "  }));\n"
            + "})();\n"
        )
        proc = subprocess.run([NODE, "-e", program], capture_output=True,
                              text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError(f"node exited {proc.returncode}\n"
                                 f"{proc.stdout}\n{proc.stderr}")
        return json.loads(proc.stdout.strip())

    def test_renders_a_branch_with_clock_paths_and_outcomes(self):
        r = self._render(_payload())
        self.assertFalse(r["wrapHidden"])
        self.assertTrue(r["emptyHidden"])
        self.assertIn("2:05", r["html"], "125s must render as M:SS")
        self.assertIn("Force a short trade", r["html"])
        self.assertIn("net swing +0.25", r["html"])
        self.assertIn("Back off Caitlyn", r["html"])
        self.assertIn("POKE PHASE", r["html"])

    def test_meta_names_the_matchup_and_count(self):
        r = self._render(_payload())
        self.assertIn("ARAM", r["meta"])
        self.assertIn("Annie vs Caitlyn", r["meta"])
        self.assertIn("1 branches", r["meta"])

    def test_confidence_is_colour_coded(self):
        """A low-confidence path must not read like a high one."""
        r = self._render(_payload())
        self.assertIn("is-high", r["html"])
        self.assertIn("is-low", r["html"])

    def test_excluded_row_explains_itself_instead_of_showing_a_gap(self):
        """RM-158: the paths are withheld, and the reader is told why rather
        than seeing a moment with no content."""
        p = _payload(precompute_excluded=True)
        p["branches"][0]["precompute_excluded"] = True
        p["branches"][0]["choices"] = []
        r = self._render(p)
        self.assertIn("withheld", r["html"])
        self.assertIn("RM-158", r["html"])
        self.assertNotIn("Force a short trade", r["html"])
        self.assertFalse(r["noteHidden"])

    def test_truncation_is_disclosed(self):
        r = self._render(_payload(truncated=True))
        self.assertFalse(r["noteHidden"])
        self.assertIn("clipped", r["note"])

    def test_legacy_row_count_is_disclosed(self):
        r = self._render(_payload(legacy_rows_skipped=1200))
        self.assertIn("1200", r["note"])

    def test_no_note_when_the_data_is_clean(self):
        r = self._render(_payload())
        self.assertTrue(r["noteHidden"])

    def test_empty_series_shows_the_empty_state(self):
        r = self._render(_payload(branches=[], reason="run-not-found"))
        self.assertFalse(r["emptyHidden"])
        self.assertEqual(r["html"], "")

    def test_null_payload_hides_the_card(self):
        r = self._render(None)
        self.assertTrue(r["wrapHidden"])

    def test_live_game_state_renders_nothing(self):
        """Self-gate. This card can only appear on a view the overlay never
        shows, but the compliance question is about the in-game surface, so
        the module refuses a live envelope on its own."""
        live = {"mode_key": "aram", "liveclient": {"champion": "Annie"}}
        r = self._render(_payload(), live)
        self.assertTrue(r["wrapHidden"])
        self.assertEqual(r["html"], "")

    def test_markup_in_a_label_is_escaped(self):
        p = _payload()
        p["branches"][0]["choices"][0]["label"] = '<img src=x onerror=alert(1)>'
        r = self._render(p)
        self.assertNotIn("<img", r["html"])
        self.assertIn("&lt;img", r["html"])


class MountAndWiringTests(unittest.TestCase):
    """Static contract: the mounts exist, live on the post-game view, and the
    stylesheet is actually imported - an unimported panel CSS file greps fine
    and styles nothing."""

    def setUp(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_every_mount_exists(self):
        for mount_id in _MOUNT_IDS:
            with self.subTest(mount=mount_id):
                self.assertIn(f'id="{mount_id}"', self.html)

    def test_card_is_hidden_by_default(self):
        self.assertRegex(self.html,
                         r'<div class="lm-br-wrap" id="lm-branch-review"[^>]*hidden')

    def test_card_lives_inside_the_post_game_view(self):
        start = self.html.index('<section id="view-last-match"')
        end = self.html.index('<section id="view-historical-pgr"')
        self.assertIn('id="lm-branch-review"', self.html[start:end])

    def test_css_is_imported(self):
        self.assertIn("@import './panels/branch_review.css';",
                      DASHBOARD_CSS.read_text(encoding="utf-8"))

    def test_every_css_var_used_is_defined_somewhere(self):
        """An undefined CSS var fails SILENTLY - it inherits instead of
        erroring - so each token this panel uses is checked against the
        stylesheet tree."""
        import re
        css = PANEL_CSS.read_text(encoding="utf-8")
        used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css))
        self.assertTrue(used, "expected this panel to use design tokens")
        defined: set[str] = set()
        for path in (REPO_ROOT / "web" / "css").rglob("*.css"):
            defined |= set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:",
                                      path.read_text(encoding="utf-8"),
                                      re.MULTILINE))
        self.assertEqual(used - defined, set())


if __name__ == "__main__":
    unittest.main()
