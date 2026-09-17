"""RM-462 (2): web/legacy_index.html must not send the operator to a retired box.

ADR-011 retired the Game-PC on 2026-05-29 (1-PC Legion). The legacy page -
served at ``?ui=legacy`` and as the index fallback - still told a relay-down
operator to "Run gamepc_lcu_agent.py on Game-PC": a script that no longer
exists, on a machine that is no longer in the pipeline. The agent is now
tools/lcu_agent.py, run locally by the RC-LCUAgent ONLOGON task.

Two arms:
  * a whole-file census: no Game-PC / gamepc spelling survives anywhere in the
    served page (comments included - they ship to the browser too);
  * the rendered relay-down text, driven in node through the RM-382 harness,
    names a script that EXISTS on disk and the task that runs it.

All authored content here is 7-bit ASCII.
"""

from __future__ import annotations

import re
import unittest

from tests.test_legacy_lcu_panel_phase_rm382 import LEGACY_HTML, NODE, REPO_ROOT, render_cases

_RETIRED = re.compile(r"game[\s_-]?pc", re.I)


class LegacyIndexRetiredWordingTest(unittest.TestCase):
    def test_no_retired_game_pc_spelling_in_served_page(self):
        text = LEGACY_HTML.read_text(encoding="utf-8")
        hits = [ln for ln in text.splitlines() if _RETIRED.search(ln)]
        self.assertEqual(hits, [])

    def test_census_pattern_catches_the_retired_spellings(self):
        """Positive control: an empty census must not pass by a dead regex."""
        for s in ("Game-PC", "gamepc_lcu_agent.py", "Game PC", "game_pc"):
            with self.subTest(s=s):
                self.assertIsNotNone(_RETIRED.search(s))

    @unittest.skipIf(NODE is None, "node not available")
    def test_relay_down_text_names_a_real_agent_and_its_task(self):
        html = render_cases(LEGACY_HTML.read_text(encoding="utf-8"))["relay_down"]
        self.assertIn("Relay offline", html)
        self.assertIn("RC-LCUAgent", html)
        self.assertIn("tools/lcu_agent.py", html)
        self.assertTrue((REPO_ROOT / "tools" / "lcu_agent.py").is_file())
        self.assertTrue(html.isascii())


if __name__ == "__main__":
    unittest.main()
