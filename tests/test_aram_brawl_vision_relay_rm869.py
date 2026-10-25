"""RM-869: the ARAM and Brawl vision readers bypass the promptless TFT relay.

`modes/shared_vision.py` `GameVisionReader._extract` prefers
`core.moon_proxy.extract_vision(img, model)` while `USE_RELAY` is True (the
class default). That transport carries NO prompt: the relay
(`vision_server/_inference.py` `_VISION_PROMPT`) answers every caller with the
TFT extraction schema. Only the direct-Anthropic fallback in `_extract` sends
`self.PROMPT`. RM-144 (`dashboard/_screen_read.py` ScreenReadVision) set
`USE_RELAY = False` for a reader whose PROMPT is load-bearing.

`coaches/aram_coach.py` and `coaches/brawl_coach.py` build their readers via
`GameVisionReader.__new__` and never set the flag, so the fields only their
own PROMPT asks for never arrive. Measured read-only 2026-10-25 on the main
checkout's `data/vision_merge_shadow.jsonl` (230 ARAM tiered reads): the
ARAM PROMPT fields `my_tower_hp`, `enemy_tower_hp`, `wave_pct`, `hp_packs`,
`fight_state` and `augment_select` were requested 230 times and returned 0
times; the relay answered with TFT keys (`board_units`, `shop_units`,
`traits_active`, `last_round_result`, ...). No Brawl read is logged at all,
and none of the ten Brawl PROMPT fields is a relay schema key.

Going direct must not blank the Sonnet side of an OCR shadow row the relay
used to answer, so every `_ARAM_SHADOW_FIELDS` key that IS a relay schema key
(`gold`, `level`) must now be asked for by the ARAM PROMPT itself.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import aram_coach  # noqa: E402
from coaches.brawl_coach import BrawlVisionReader  # noqa: E402
from modes.shared_vision import GameVisionReader  # noqa: E402

_INFERENCE = _PROJECT_ROOT / "vision_server" / "_inference.py"


def _relay_schema_keys() -> set[str]:
    """Keys of the relay's fixed TFT JSON example, read from source text so
    the test never imports the vision server (it builds an SDK client)."""
    src = _INFERENCE.read_text(encoding="utf-8")
    m = re.search(r'_VISION_PROMPT = """(.*?)"""', src, re.S)
    assert m, "relay _VISION_PROMPT not found"
    return set(re.findall(r'"([a-z_]+)"\s*:', m.group(1)))


def _prompt_keys(prompt: str) -> set[str]:
    """Keys of a reader PROMPT's JSON example block."""
    body = prompt[prompt.index("{"): prompt.rindex("}") + 1]
    return set(json.loads(body))


def _aram_reader() -> GameVisionReader:
    c = aram_coach.Coach.__new__(aram_coach.Coach)
    c._api_key = "sk-ant-test"
    return c._build_vision_reader()


def _assert_direct(test: unittest.TestCase, reader: GameVisionReader) -> None:
    """`_extract` must skip moon_proxy and send this reader's own PROMPT."""
    proxy = mock.MagicMock()
    proxy.extract_vision.return_value = {"gold": 1200}  # would win if consulted
    reader._client = mock.MagicMock()
    resp = mock.MagicMock()
    resp.content = [mock.MagicMock(text='{"ok": true}')]
    resp.usage = None
    reader._client.messages.create.return_value = resp
    with mock.patch.dict(
        "sys.modules", {"core.moon_proxy": mock.MagicMock(moon_proxy=proxy)}
    ), mock.patch("core.cost_tracker.get_tracker") as gt:
        gt.return_value.allow_call.return_value = True
        out = reader._extract("/9j/abc")
    proxy.extract_vision.assert_not_called()
    test.assertEqual(out, {"ok": True})
    sent = reader._client.messages.create.call_args.kwargs["messages"][0]["content"]
    test.assertEqual(sent[1]["text"], reader.PROMPT)


class RelaySchemaPremise(unittest.TestCase):

    def test_relay_schema_is_the_tft_one(self) -> None:
        keys = _relay_schema_keys()
        self.assertIn("board_units", keys)
        self.assertIn("is_augment_select", keys)
        self.assertNotIn("my_tower_hp", keys)

    def test_default_stays_relay_first(self) -> None:
        self.assertTrue(GameVisionReader.USE_RELAY,
                        "the class default must not change (shared_vision is out of scope)")


class AramReaderTests(unittest.TestCase):

    def test_reader_carries_the_aram_prompt_and_tiered_config(self) -> None:
        r = _aram_reader()
        self.assertEqual(r.PROMPT, aram_coach._VISION_PROMPT)
        self.assertEqual(r.TIERED_FIELDS, aram_coach.Coach._ARAM_TIERED_FIELDS)
        self.assertEqual(r.SHADOW_FIELDS, aram_coach.Coach._ARAM_SHADOW_FIELDS)

    def test_reader_bypasses_the_relay(self) -> None:
        self.assertIs(_aram_reader().USE_RELAY, False)

    def test_extract_sends_the_aram_prompt_direct(self) -> None:
        _assert_direct(self, _aram_reader())

    def test_prompt_asks_for_its_own_fields(self) -> None:
        keys = _prompt_keys(aram_coach._VISION_PROMPT)
        for f in ("my_tower_hp", "enemy_tower_hp", "wave_pct", "hp_packs",
                  "fight_state", "augments", "augment_select", "augment_choices"):
            self.assertIn(f, keys)

    def test_prompt_keeps_every_shadow_field_the_relay_answered(self) -> None:
        relay = _relay_schema_keys()
        keys = _prompt_keys(aram_coach._VISION_PROMPT)
        lost = [f for f in aram_coach.Coach._ARAM_SHADOW_FIELDS
                if f in relay and f not in keys]
        self.assertEqual(lost, [], "going direct would blank these OCR shadow rows")
        self.assertTrue({"gold", "level"} <= keys)

    def test_run_vision_uses_the_builder(self) -> None:
        """The live tick must read through the same reader the tests pin."""
        seen = {}

        def _fake_read_tiered(self_, *a, **k):
            seen["use_relay"] = self_.USE_RELAY
            seen["prompt"] = self_.PROMPT
            return None

        c = aram_coach.Coach.__new__(aram_coach.Coach)
        c._api_key = "sk-ant-test"
        c._overlay = {}
        c._last_state = {}
        c._init_extra()
        with (
            mock.patch.object(GameVisionReader, "read_tiered", _fake_read_tiered),
            mock.patch.object(aram_coach.Coach, "_fetch_game_data",
                              lambda _self: {}),
        ):
            c._run_vision()
        self.assertIs(seen.get("use_relay"), False)
        self.assertEqual(seen.get("prompt"), aram_coach._VISION_PROMPT)


class BrawlReaderTests(unittest.TestCase):

    def test_nexus_blitz_reader_bypasses_the_relay(self) -> None:
        r = BrawlVisionReader("sk-ant-test", "NEXUSBLITZ")._reader
        self.assertEqual(r.PROMPT, BrawlVisionReader._NB_PROMPT)
        self.assertIs(r.USE_RELAY, False)
        _assert_direct(self, r)

    def test_urf_reader_bypasses_the_relay(self) -> None:
        for mode in ("URF", "ULTBOOK", "ARURF"):
            r = BrawlVisionReader("sk-ant-test", mode)._reader
            self.assertEqual(r.PROMPT, BrawlVisionReader._URF_PROMPT, mode)
            self.assertIs(r.USE_RELAY, False, mode)
        _assert_direct(self, BrawlVisionReader("sk-ant-test", "URF")._reader)

    def test_no_brawl_prompt_field_is_a_relay_key(self) -> None:
        """The premise: on the relay none of these could ever arrive."""
        relay = _relay_schema_keys()
        for prompt in (BrawlVisionReader._NB_PROMPT, BrawlVisionReader._URF_PROMPT):
            self.assertFalse(_prompt_keys(prompt) & relay)


if __name__ == "__main__":
    unittest.main()
