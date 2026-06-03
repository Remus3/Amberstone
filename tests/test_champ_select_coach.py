"""
tests/test_champ_select_coach.py - prompt-cache marker contract tests.

Pins that coaches/champ_select_coach.py uses the explicit-block list
shape on messages.create(system=...) with cache_control=ephemeral on the
static system prompt. The string-form system=SYSTEM_PROMPT does NOT
trigger caching; the explicit block list does.

Mirrors the contract in coaches/aram_coach.py (gap-E fix 2026-04-29).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from coaches import champ_select_coach


_SOURCE = Path(champ_select_coach.__file__).read_text(encoding="utf-8")


class SystemPromptShapeTests(unittest.TestCase):
    """Source-level contracts on the prompt + call shape."""

    def test_system_prompt_constant_exists(self):
        # _SYSTEM_PROMPT module-level constant remains the prompt source
        # (the cache marker rides on this exact string per tick).
        self.assertTrue(hasattr(champ_select_coach, "_SYSTEM_PROMPT"))
        self.assertIsInstance(champ_select_coach._SYSTEM_PROMPT, str)
        self.assertGreater(len(champ_select_coach._SYSTEM_PROMPT), 100)

    def test_cache_control_marker_present(self):
        # The cache_control=ephemeral marker MUST appear in the call site
        # (this is the load-bearing test - drop it and Anthropic stops
        # caching the prefix, input-token cost goes back to 100%).
        self.assertIn('"cache_control": {"type": "ephemeral"}', _SOURCE)

    def test_system_uses_explicit_block_list_not_string(self):
        # Find the messages.create(...) call body. The system= argument
        # must use the [{"type": "text", "text": _SYSTEM_PROMPT, ...}]
        # shape, NOT the string-form system=_SYSTEM_PROMPT.
        # Permissive whitespace matcher because the block can wrap.
        block_pat = re.compile(
            r'system\s*=\s*\[\s*\{\s*"type"\s*:\s*"text"\s*,'
            r'\s*"text"\s*:\s*_SYSTEM_PROMPT\s*,'
            r'\s*"cache_control"\s*:\s*\{\s*"type"\s*:\s*"ephemeral"\s*\}',
            re.DOTALL,
        )
        self.assertRegex(_SOURCE, block_pat,
                         "system= must be a list with text+cache_control "
                         "block, not the string-form system=_SYSTEM_PROMPT "
                         "(string form does not get cached).")

    def test_no_legacy_string_system_arg(self):
        # Guard against drift back to system=_SYSTEM_PROMPT (string form).
        # The exact bare-string pattern indicates the marker was reverted.
        bare_pat = re.compile(r'system\s*=\s*_SYSTEM_PROMPT\s*,')
        self.assertNotRegex(_SOURCE, bare_pat,
                            "Bare system=_SYSTEM_PROMPT form indicates the "
                            "cache marker was reverted (string form does "
                            "not cache).")


class CallShapeTests(unittest.TestCase):
    """Runtime contract: actual messages.create(...) kwargs at call time."""

    def test_runtime_call_passes_block_with_cache_control(self):
        # Mock the anthropic client and capture messages.create kwargs.
        # The system kwarg must be a list, first item must carry
        # cache_control=ephemeral, and _SYSTEM_PROMPT must be the text.
        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text="Advice: stay\nSwap: none\n"
                                            "Summoners: Flash + Heal\n"
                                            "Watchout: Caitlyn")]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        fake_anthropic = MagicMock()
        fake_anthropic.Anthropic.return_value = fake_client

        # Hermetic spend-gate: coach_pick short-circuits when the local
        # config/coach_settings.json disables the "champ_select" coach
        # (operator's gitignored runtime preference). Force the gate OFF
        # so this call-shape contract is independent of the local config
        # - CI has no such config and passes, but a dev machine with the
        # gate enabled must not flip this test red.
        fake_tracker = MagicMock()
        fake_tracker.gate_disabled.return_value = False

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}), \
                patch("core.cost_tracker.get_tracker", return_value=fake_tracker):
            out = champ_select_coach.coach_pick(
                {"is_aram": False, "my_champion": "Ahri",
                 "my_team": ["Yuumi"], "their_team": ["Caitlyn"]},
                api_key="sk-test",
            )

        self.assertTrue(out["ok"])
        # Inspect the captured kwargs on the fake client.
        self.assertEqual(fake_client.messages.create.call_count, 1)
        kwargs = fake_client.messages.create.call_args.kwargs

        # system MUST be a list of blocks, not a bare string.
        self.assertIsInstance(kwargs["system"], list,
                              "system= must be a list of content blocks")
        self.assertEqual(len(kwargs["system"]), 1,
                         "expected exactly one system block")

        block = kwargs["system"][0]
        self.assertEqual(block["type"], "text")
        self.assertEqual(block["text"], champ_select_coach._SYSTEM_PROMPT)
        self.assertEqual(block["cache_control"], {"type": "ephemeral"},
                         "cache_control marker missing - prefix will not "
                         "be cached and input-token cost stays at 100%.")

        # User message goes uncached as a normal messages[] entry.
        self.assertIsInstance(kwargs["messages"], list)
        self.assertEqual(kwargs["messages"][0]["role"], "user")
        self.assertIn("Ahri", kwargs["messages"][0]["content"])


class ErrorDegradeTests(unittest.TestCase):
    """The advice field is user-facing - an API error must degrade to a
    friendly message, never leak the raw exception (CLAUDE.md error rule)."""

    def test_api_error_renders_friendly_no_leak(self):
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = RuntimeError(
            "Error code: 429 - rate_limit_error: credit balance exhausted")
        fake_anthropic = MagicMock()
        fake_anthropic.Anthropic.return_value = fake_client
        fake_tracker = MagicMock()
        fake_tracker.gate_disabled.return_value = False

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}), \
                patch("core.cost_tracker.get_tracker", return_value=fake_tracker):
            out = champ_select_coach.coach_pick(
                {"is_aram": False, "my_champion": "Ahri",
                 "my_team": ["Yuumi"], "their_team": ["Caitlyn"]},
                api_key="sk-test",
            )

        advice = out.get("advice", "")
        for leak in ("rate_limit", "429", "RuntimeError", "credit", "balance"):
            self.assertNotIn(leak, advice,
                             f"raw error token '{leak}' leaked into advice")
        self.assertIn("paused", advice)  # the friendly degrade marker


if __name__ == "__main__":
    unittest.main()
