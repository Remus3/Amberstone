"""RM-516 guard: live coach / vision model pins are current, and priced.

RM-511 refreshed the loop / supervisor / charter pins but deliberately left
the live coaching path: three coaches overrode the vision reader with a
literal ``claude-sonnet-4-6`` and ``modes/shared_vision.SONNET_MODEL`` carried
the same id, while ``core/cost_tracker.MODEL_PRICING`` had no row for the
current Opus / Sonnet ids, so any call on them was priced at DEFAULT_PRICING.

Assertions:
- every ``claude-*`` literal in coaches/, modes/ and vision_server/ is in the
  CURRENT set (a retired or previous-generation id fails by name);
- the three coach vision overrides reuse ``SONNET_MODEL`` instead of a
  literal, so the next refresh is a one-line edit;
- every pinned id has a MODEL_PRICING row (no silent DEFAULT_PRICING);
- the loop meter's opus / sonnet price rows match the current list prices.
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Current ids (claude-api skill model table, cached 2026-09-25). The dated
# Haiku id is the one the price table and warm_session key on.
CURRENT_IDS = {
    "claude-haiku-4-5-20251001",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
}

_ID_RE = re.compile(r"claude-(?:opus|sonnet|haiku|fable|mythos)-[0-9][0-9a-z-]*")
_SCAN_DIRS = ("coaches", "modes", "vision_server")


def _pins() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for d in _SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            text = p.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                for m in _ID_RE.findall(line):
                    found.setdefault(m, []).append(
                        f"{p.relative_to(ROOT).as_posix()}:{i}")
    return found


class CoachVisionPinsCurrent(unittest.TestCase):

    def test_scan_is_not_empty(self):
        # Anchor: an empty scan would pass the stale-id check vacuously.
        self.assertIn("claude-haiku-4-5-20251001", _pins())

    def test_no_stale_ids(self):
        stale = {k: v for k, v in _pins().items() if k not in CURRENT_IDS}
        self.assertEqual(stale, {}, f"stale model ids pinned: {stale}")

    def test_sonnet_model_is_current(self):
        from modes import shared_vision
        self.assertEqual(shared_vision.SONNET_MODEL, "claude-sonnet-5-5")

    def test_coach_overrides_reuse_sonnet_model(self):
        for rel in ("coaches/aram_coach.py", "coaches/arena_coach.py",
                    "coaches/brawl_coach.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'r\._model\s*=\s*"', rel)
            self.assertRegex(text, r"r\._model\s*=\s*SONNET_MODEL", rel)


class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Tracker:
    def allow_call(self):
        return True

    def record_call(self, **_kw):
        pass


class DirectVisionPathOnCurrentSonnet(unittest.TestCase):
    """The direct fallback read resp.content[0].text; on SONNET_MODEL's
    default adaptive thinking content[0] is a thinking block (no .text)."""

    def _reader(self, create):
        from modes.shared_vision import GameVisionReader
        r = GameVisionReader.__new__(GameVisionReader)
        r._client = _Blk(messages=_Blk(create=create))
        r._model = "claude-sonnet-5-5"
        r._last = {}
        r.USE_RELAY = False
        r.PROMPT = "p"
        return r

    def _extract(self, create):
        from unittest import mock
        with mock.patch("core.cost_tracker.get_tracker", return_value=_Tracker()):
            return self._reader(create)._extract("iVBORw0KGgo=")

    def test_leading_thinking_block_is_skipped(self):
        resp = _Blk(content=[_Blk(type="thinking", thinking=""),
                             _Blk(type="text", text='{"gold": 5}')],
                    usage=None)
        self.assertEqual(self._extract(lambda **kw: resp), {"gold": 5})

    def test_no_text_block_degrades_to_none(self):
        resp = _Blk(content=[_Blk(type="thinking", thinking="")], usage=None)
        self.assertIsNone(self._extract(lambda **kw: resp))

    def test_api_error_degrades_to_none(self):
        def boom(**kw):
            raise RuntimeError("400 model not found")
        self.assertIsNone(self._extract(boom))


class PinsArePriced(unittest.TestCase):

    def test_every_pin_has_a_price_row(self):
        from core.cost_tracker import MODEL_PRICING
        missing = sorted(set(_pins()) - set(MODEL_PRICING))
        self.assertEqual(missing, [])

    def test_current_list_prices(self):
        from core.cost_tracker import MODEL_PRICING
        self.assertEqual(
            (MODEL_PRICING["claude-opus-5-5"]["input"],
             MODEL_PRICING["claude-opus-5-5"]["output"]), (4.0, 20.0))
        self.assertEqual(
            (MODEL_PRICING["claude-sonnet-5-5"]["input"],
             MODEL_PRICING["claude-sonnet-5-5"]["output"]), (2.0, 10.0))

    def test_cost_estimate_uses_row_not_default(self):
        from core import cost_tracker as ct
        price = ct.MODEL_PRICING["claude-sonnet-5-5"]
        self.assertIsNot(price, ct.DEFAULT_PRICING)
        self.assertNotEqual(price["input"], ct.DEFAULT_PRICING["input"])


class LoopMeterPrices(unittest.TestCase):

    def test_tracked_loop_configs_price_current_opus_sonnet(self):
        out = subprocess.run(
            ["git", "ls-files", "ops/loop/config*.json"], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout.split()
        cfgs = [ROOT / rel for rel in out]
        self.assertTrue(cfgs)
        for p in cfgs:
            t = json.loads(p.read_text(encoding="utf-8")).get("price_per_mtok")
            if t is None:
                continue
            self.assertEqual((t["opus"]["input"], t["opus"]["output"]),
                             (4.0, 20.0), p.name)
            self.assertEqual((t["sonnet"]["input"], t["sonnet"]["output"]),
                             (2.0, 10.0), p.name)


if __name__ == "__main__":
    unittest.main()
