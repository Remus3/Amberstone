"""Guard: the ARAM/TFT augment + live-analysis Haiku prompts are below the
Claude Haiku prompt-cache floor, so a static/data cache_control restructure
yields ZERO cost benefit and must NOT be re-attempted (item 286).

Background
----------
Items 273 / 280 / 283 / 284 repeatedly re-surfaced a "cost prompt-restructure
for aram_aug_select / tft_live_analysis (data interleaved -> needs a static/data
split)" as a NEXT/deferred lane. Item 286 measured it to a decision and found
THREE independent blockers that make it a verified dead end:

1. BELOW THE HAIKU CACHE FLOOR (decisive). The minimum cacheable prompt prefix
   for ``claude-haiku-4-5-20251001`` is 2048 tokens (vs 1024 for Sonnet/Opus;
   corroborated by item 273's tft_pbe note "2450-tok > 2048 haiku floor"). The
   STATIC portion of each target prompt is far below that floor:
       aram_aug_select      static ~62 tok   (full template 279 chars)
       arena_aug_select     static ~80 tok   (315 static chars)
       tft_live_analysis    static ~669 tok  (full template 2605 chars)
       tft_live_aug_select  static ~51 tok   (full template 242 chars)
   ``cache_control`` markers below the floor are inert (the API does not cache
   them), so even a perfect static-first restructure caches nothing.

2. PRIMARY PATH IS A FROZEN SINGLE-STRING CALL. ``tft_live_analysis`` issues its
   primary call via ``core.moon_proxy.moon_proxy.get_coaching(prompt: str, ...)``
   - a FROZEN module that forwards ONE prompt string to the vision server. A
   system/user cache split cannot flow through it without editing a frozen file.

3. FIDELITY-GATED ON A LIVE GAME. Moving instructions from the user message into
   a cached ``system`` block shifts Haiku positioning; behavioural equivalence
   needs a live TFT/ARAM game, which is unrunnable headless.

This test pins blocker #1 as a durable CI tripwire. The char->token bound is
deliberately PESSIMISTIC (2.0 chars/token; real English averages ~3.7) so the
assertion proves "static < 2048 tokens" even under an adversarial tokenisation.
If a future edit grows one of these templates past the floor, this test fails
LOUDLY - which is the signal that caching may finally be worth implementing for
that site (re-derive the math, then update this guard).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# Claude Haiku minimum cacheable prompt prefix (tokens). Sonnet/Opus = 1024.
HAIKU_CACHE_FLOOR_TOKENS = 2048
# Pessimistic lower bound on chars-per-token: real text is ~3.5-4.0; using 2.0
# upper-bounds the token count, so passing proves sub-floor under any realistic
# tokenisation.
CONSERVATIVE_CHARS_PER_TOKEN = 2.0
_FLOOR_CHARS = HAIKU_CACHE_FLOOR_TOKENS * CONSERVATIVE_CHARS_PER_TOKEN  # 4096


def _extract_block(src: str, marker: str) -> str:
    """Return the body of the first ``marker = \"\"\"...\"\"\"`` assignment."""
    i = src.index(marker)
    start = src.index('"""', i) + 3
    end = src.index('"""', start)
    return src[start:end]


def _static_chars(template: str) -> int:
    """Char length of the template with ``{placeholder}`` runtime data removed."""
    return len(re.sub(r"\{[^}]+\}", "", template))


# (label, source file, module-level template constant)
_TARGETS = [
    ("aram_aug_select", "coaches/aram_coach.py", "_AUG_SELECT_PROMPT"),
    ("arena_aug_select", "coaches/arena_coach.py", "_AUGMENT_SELECT_PROMPT"),
    ("tft_live_analysis", "tft/tft_live_analysis.py", "_ANALYSIS_PROMPT_TEMPLATE"),
    ("tft_live_aug_select", "tft/tft_live_analysis.py", "_AUGMENT_SELECT_PROMPT"),
]


class HaikuCacheFloorGuardTests(unittest.TestCase):
    def test_static_portions_below_haiku_cache_floor(self) -> None:
        for label, relpath, marker in _TARGETS:
            with self.subTest(prompt=label):
                src = (_REPO / relpath).read_text(encoding="utf-8")
                static = _static_chars(_extract_block(src, marker))
                self.assertLess(
                    static,
                    _FLOOR_CHARS,
                    msg=(
                        f"{label} static portion grew to {static} chars "
                        f"(>= {_FLOOR_CHARS:.0f} = the Haiku 2048-tok floor at a "
                        f"pessimistic 2.0 chars/tok). It may now clear the cache "
                        f"floor - re-derive the token math; if it genuinely clears "
                        f"2048 tokens, prompt caching is finally worth implementing "
                        f"for this site (and update this guard). See item 286."
                    ),
                )

    def test_tft_live_analysis_primary_path_is_frozen_single_string(self) -> None:
        # Blocker #2: the primary call cannot carry a cache_control system block
        # because it routes through the FROZEN single-string moon_proxy helper.
        src = (_REPO / "tft/tft_live_analysis.py").read_text(encoding="utf-8")
        self.assertIn("moon_proxy.get_coaching(p", src)
        proxy = (_REPO / "core/moon_proxy.py").read_text(encoding="utf-8")
        self.assertRegex(proxy, r"def get_coaching\(self, prompt: str")


if __name__ == "__main__":
    unittest.main()
