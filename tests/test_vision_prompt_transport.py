"""RM-144 residual: a bespoke-PROMPT reader must not use the promptless relay.

`GameVisionReader._extract()` prefers `core.moon_proxy.extract_vision(img, model)`,
whose transport carries NO prompt - the relay (`vision_server/_inference.py`) runs
its own fixed `_VISION_PROMPT` (TFT extraction schema) for every caller. Only the
DIRECT Anthropic fallback in `_extract` actually sends `self.PROMPT`.

So any subclass whose PROMPT asks for a field the relay schema does not emit gets
a well-formed dict back that silently never contains that field. That is exactly
how SCREEN READ wedged on `empty_note`: `ScreenReadVision.PROMPT` asks for
`{"note": ...}`, the relay answered with TFT fields, `note` was never present, and
the pill reported an error forever while every layer beneath it was healthy.

The `USE_RELAY` class flag is the fix: readers whose PROMPT is load-bearing opt out
of the relay so their prompt actually reaches the model.
"""
from __future__ import annotations

import unittest
from unittest import mock

from dashboard._screen_read import ScreenReadVision
from modes.shared_vision import GameVisionReader


class _Reader(GameVisionReader):
    """Bypasses __init__ so no anthropic client / api key is needed."""

    PROMPT = 'return ONLY {"note": "..."}'

    def __init__(self, use_relay: bool):  # noqa: D107 - test seam
        self.USE_RELAY = use_relay
        self._client = mock.MagicMock()
        self._model = "test-model"
        self._last = {}
        self._last_state_summary = None
        self._last_result = None


class RelayOptOutTests(unittest.TestCase):

    def test_relay_reader_uses_moon_proxy(self):
        """Baseline: the default (mode coaches) still prefers the relay."""
        proxy = mock.MagicMock()
        proxy.extract_vision.return_value = {"gold": 1200}
        with mock.patch.dict("sys.modules", {"core.moon_proxy": mock.MagicMock(moon_proxy=proxy)}):
            out = _Reader(use_relay=True)._extract("/9j/abc")
        self.assertEqual(out, {"gold": 1200})
        proxy.extract_vision.assert_called_once()

    def test_optout_reader_never_calls_the_promptless_relay(self):
        """USE_RELAY=False must reach the direct path, which sends PROMPT."""
        proxy = mock.MagicMock()
        proxy.extract_vision.return_value = {"gold": 1200}  # would win if consulted
        reader = _Reader(use_relay=False)
        resp = mock.MagicMock()
        resp.content = [mock.MagicMock(text='{"note": "ward the pit"}')]
        resp.usage = None
        reader._client.messages.create.return_value = resp
        with mock.patch.dict("sys.modules", {"core.moon_proxy": mock.MagicMock(moon_proxy=proxy)}):
            out = reader._extract("/9j/abc")
        proxy.extract_vision.assert_not_called()
        self.assertEqual(out, {"note": "ward the pit"})
        sent = reader._client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(sent[1]["text"], _Reader.PROMPT)

    def test_screen_read_reader_opts_out(self):
        """The concrete regression: SCREEN READ asks for a field the relay
        schema does not emit, so it must not go through the relay."""
        self.assertFalse(ScreenReadVision.USE_RELAY)
        self.assertTrue(GameVisionReader.USE_RELAY,
                        "default must stay relay-first for the mode coaches")


if __name__ == "__main__":
    unittest.main()
