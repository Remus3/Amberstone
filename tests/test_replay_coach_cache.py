"""Pin the prompt-cache marker on replay_coach.

The postgame replay coach is called once per finished match the
operator opens for review; the static `_PROMPT` system text is the
high-value cache target. Mirrors the marker shape shipped on
champ_select_coach.py + aram_team_analyzer.py + aram_coach.py.

Note: the system-prompt constant is `_PROMPT` (not `_SYSTEM_PROMPT`)
in this module - the contracts below match that name.
"""

from __future__ import annotations

import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / "coaches" / "replay_coach.py"


class CacheMarkerPinTests(unittest.TestCase):
    def setUp(self):
        self.src = SRC.read_text(encoding="utf-8")

    def test_uses_explicit_block_system(self):
        # The string-form `system=_PROMPT,` is NOT cached by the
        # Anthropic API; the explicit-block list with cache_control is.
        self.assertNotIn('system=_PROMPT,', self.src)

    def test_cache_control_ephemeral_marker_present(self):
        self.assertIn('"cache_control": {"type": "ephemeral"}', self.src)

    def test_system_prompt_text_carried_in_block(self):
        self.assertIn('"text": _PROMPT', self.src)

    def test_block_shape_before_messages(self):
        # System block must come before the user messages list so the
        # cache prefix is hit first.
        sys_idx = self.src.index('"cache_control"')
        msg_idx = self.src.index('"role": "user"')
        self.assertLess(sys_idx, msg_idx)


if __name__ == "__main__":
    unittest.main()
