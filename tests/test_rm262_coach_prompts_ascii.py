"""RM-262: live Haiku prompt strings are 7-bit ASCII.

Filed for four U+2192 arrows in ``coaches/arena_coach.py`` _SYSTEM_PROMPT
(augment framework lines) plus the U+2550 box-drawing section rules in the
same block. The sibling sweep found the same two classes in the ARAM and
Brawl system prompts. Every module-level prompt constant of the three live
mode coaches is checked here (enumerated by name pattern, anchored so an
empty enumeration cannot pass).
"""
from __future__ import annotations

import re
import unittest

from coaches import aram_coach, arena_coach, brawl_coach

_NAME = re.compile(r"^_[A-Z_]*(PROMPT|SYSTEM|TMPL|TEMPLATE)$")


def _prompts():
    out = {}
    for mod in (arena_coach, aram_coach, brawl_coach):
        for name, val in vars(mod).items():
            if _NAME.match(name) and isinstance(val, str):
                out[f"{mod.__name__}.{name}"] = val
    return out


class CoachPromptsAscii(unittest.TestCase):

    def test_enumeration_anchored(self):
        names = set(_prompts())
        for must in ("coaches.arena_coach._SYSTEM_PROMPT",
                     "coaches.aram_coach._SYSTEM",
                     "coaches.brawl_coach._URF_SYSTEM_PROMPT"):
            self.assertIn(must, names)

    def test_every_prompt_is_ascii(self):
        bad = {k: sorted({hex(ord(c)) for c in v if ord(c) > 127})
               for k, v in _prompts().items()
               if any(ord(c) > 127 for c in v)}
        self.assertEqual(bad, {})

    def test_arena_augment_framing_kept(self):
        p = arena_coach._SYSTEM_PROMPT
        self.assertIn("dash -> Sudden Impact; CC -> Glacial Augment", p)
        self.assertIn("AD items -> Conqueror; AP -> Luden's", p)
        self.assertIn("=== AUGMENT SELECTION FRAMEWORK ===", p)


if __name__ == "__main__":
    unittest.main()
