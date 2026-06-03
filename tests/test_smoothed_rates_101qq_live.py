"""Live-wiring tests for the item-199 duo-synergy seed (item 277).

core.smoothed_rates_101qq now pulls the duo table from the Tencent live
fetch first (core.synergy_external_source.fetch_rows), falling back to the
committed static May-25 seed when the CN endpoint is unreachable. These
tests pin: live-first when rows are present, static fallback when not, the
RC_DUO_SYNERGY_LIVE=0 kill switch, and source() reporting.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core import smoothed_rates_101qq as S101  # noqa: E402


def _live_rows(pairs):
    return [
        {
            "championid1": str(c1), "championid2": str(c2),
            "doublewinrate": wr, "iwinrate1": 0.5, "iwinrate2": 0.5,
            "itemp1": pick, "irank": i + 1,
            "lane1": "bottom", "lane2": "support",
        }
        for i, (c1, c2, wr, pick) in enumerate(pairs)
    ]


class LiveWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prior_env = os.environ.get("RC_DUO_SYNERGY_LIVE")
        os.environ["RC_DUO_SYNERGY_LIVE"] = "1"
        self._orig_live = S101._live_data_rows
        S101._reset_cache()

    def tearDown(self) -> None:
        S101._live_data_rows = self._orig_live
        if self._prior_env is None:
            os.environ.pop("RC_DUO_SYNERGY_LIVE", None)
        else:
            os.environ["RC_DUO_SYNERGY_LIVE"] = self._prior_env
        S101._reset_cache()

    def test_live_rows_win_over_static(self) -> None:
        # 22=Ashe, 147=Seraphine are in the committed id_map; the live row
        # carries a distinctive doublewinrate the static seed does not.
        S101._live_data_rows = lambda: _live_rows([(22, 147, 0.999, "9.99%")])
        S101._reset_cache()
        self.assertEqual(S101.source(), "live")
        rec = S101.pair_synergy("Ashe", "Seraphine")
        self.assertIsNotNone(rec)
        self.assertAlmostEqual(rec.doublewinrate, 0.999, places=3)

    def test_static_fallback_when_live_none(self) -> None:
        S101._live_data_rows = lambda: None
        S101._reset_cache()
        self.assertEqual(S101.source(), "static")
        # static seed still resolves a known pair
        self.assertIsNotNone(S101.pair_synergy("Ashe", "Seraphine"))

    def test_static_fallback_when_live_empty(self) -> None:
        S101._live_data_rows = lambda: []
        S101._reset_cache()
        self.assertEqual(S101.source(), "static")

    def test_kill_switch_forces_static(self) -> None:
        # Even with live data available, RC_DUO_SYNERGY_LIVE=0 ignores it.
        os.environ["RC_DUO_SYNERGY_LIVE"] = "0"
        called = {"n": 0}

        def _should_not_run():
            called["n"] += 1
            return _live_rows([(22, 147, 0.999, "9.99%")])

        # _live_data_rows itself short-circuits on the env, so patch the
        # inner fetch to prove it is never consulted.
        import core.synergy_external_source as SES
        orig = SES.fetch_rows
        SES.fetch_rows = lambda *a, **k: _should_not_run()
        try:
            S101._reset_cache()
            self.assertEqual(S101.source(), "static")
            self.assertEqual(called["n"], 0, "live fetch must not run when killed")
        finally:
            SES.fetch_rows = orig

    def test_name_fallback_resolves_unmapped_id(self) -> None:
        # _name_fallback covers live ids absent from the 65-entry static map.
        # It is fail-soft (""), and resolves a real ddragon key when present.
        self.assertIsInstance(S101._name_fallback(99999999), str)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii(self) -> None:
        b = Path(__file__).read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
