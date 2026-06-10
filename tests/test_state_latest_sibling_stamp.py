"""Regression: every /api/state ingest site stamps the deterministic-coaching
siblings onto state.latest (chip task_8a4ebe04, item-378 tail).

renderCoachChoices/renderLead/renderCallouts are called from onState with
``state.latest`` and read ``state.latest.coach`` / ``.lead_projection`` /
``.callouts`` - but the item-201 sibling stamp only copied ``liveclient`` +
``summoner_cooldowns``, so all three mounts stayed permanently dark (the keys
exist top-level on /api/state, verified live, yet never reached state.latest).

Grep-style contract pin, mirroring test_callouts_panel_dom.py: the three
ingest sites (state-http fallback, state-sse, the independent LCU poller)
must each stamp all five siblings.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAIN_JS = REPO / "web" / "js" / "main.js"

_SIBLINGS = (
    "liveclient",
    "summoner_cooldowns",
    "coach",
    "lead_projection",
    "callouts",
)


def _stamp_count(js: str, key: str) -> int:
    return len(re.findall(rf"state\.latest\.{key}\s*=\s*st\.{key}", js))


class SiblingStampTests(unittest.TestCase):
    def setUp(self):
        self.js = MAIN_JS.read_text(encoding="utf-8")

    def test_each_sibling_stamped_at_all_three_ingest_sites(self):
        for key in _SIBLINGS:
            self.assertGreaterEqual(
                _stamp_count(self.js, key), 3,
                f"state.latest.{key} must be stamped from st.{key} at the "
                f"state-http, state-sse, and lcu-poller ingest sites",
            )

    def test_renderers_receive_state_latest(self):
        """The onState render calls read state.latest (the stamped object)."""
        for fn in ("renderCoachChoices", "renderLead", "renderCallouts"):
            self.assertRegex(
                self.js, rf"{fn}\(state\.latest",
                f"{fn} must be fed state.latest in onState",
            )

    def test_ascii(self):
        self.assertTrue(all(b < 128 for b in Path(__file__).read_bytes()))


if __name__ == "__main__":
    unittest.main()
