"""Pin the prompt-cache marker on aram_team_analyzer.

The lobby-side team analyzer is called once per champ-select picked
champion (sometimes multiple times as picks resolve), so the static
system prompt is a high-value cache target. Mirrors the marker shape
shipped on champ_select_coach.py + aram_coach.py.
"""

from __future__ import annotations

import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / "coaches" / "aram_team_analyzer.py"


class CacheMarkerPinTests(unittest.TestCase):
    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_uses_explicit_block_system(self):
        # The string-form `system=_SYSTEM_PROMPT,` is NOT cached by the
        # Anthropic API; the explicit-block list with cache_control is.
        self.assertNotIn('system=_SYSTEM_PROMPT,', self.src)

    def test_cache_control_ephemeral_marker_present(self):
        self.assertIn('"cache_control": {"type": "ephemeral"}', self.src)

    def test_system_prompt_text_carried_in_block(self):
        self.assertIn('"text": _SYSTEM_PROMPT', self.src)

    def test_block_shape_before_messages(self):
        # System block must come before the user messages list so the
        # cache prefix is hit first.
        sys_idx = self.src.index('"cache_control"')
        msg_idx = self.src.index('"role": "user"')
        self.assertLess(sys_idx, msg_idx)


if __name__ == "__main__":
    unittest.main()
