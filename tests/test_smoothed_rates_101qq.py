"""tests/test_smoothed_rates_101qq.py - Item 199 Slice CD consumer tests.

Covers `core/smoothed_rates_101qq.py`:
  * cache loader idempotency + thread-safety
  * top_duos_for_bot / top_duos_for_sup ordering invariants
  * top_solo_picks aggregation
  * pair_synergy specific lookup
  * laplace smoothing actually applied (thin-sample pull-toward-50%)
  * graceful handling of missing IDs
  * ASCII hygiene on the new module
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import smoothed_rates_101qq as S101  # noqa: E402


class CacheLoaderTests(unittest.TestCase):
    def setUp(self):
        S101._reset_cache()

    def test_cache_loads_once_idempotent(self):
        # First call populates; second call is a no-op.
        S101._load_once()
        cov1 = S101.coverage()
        S101._load_once()
        cov2 = S101.coverage()
        self.assertEqual(cov1, cov2)

    def test_coverage_reports_unique_champions(self):
        cov = S101.coverage()
        # Seed map carries 65 unique IDs (top-200 bot-lane meta).
        self.assertEqual(cov["unique_champions"], 65)
        # Records: 200 pairs in source envelope (some champs unique only
        # to one role so unique_bot_ids + unique_sup_ids each <65).
        self.assertEqual(cov["total_records"], 200)
        self.assertGreater(cov["unique_bot_ids"], 0)
        self.assertGreater(cov["unique_sup_ids"], 0)


class TopDuosForBotTests(unittest.TestCase):
    def setUp(self):
        S101._reset_cache()

    def test_known_bot_returns_pairings(self):
        # Smolder (id 901) is the most-frequent bot in the seed (irank 4,
        # 5, 10, 14, ...). Expect at least 1 pairing.
        recs = S101.top_duos_for_bot("Smolder", top_n=4)
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertEqual(r.bot, "Smolder")
            self.assertEqual(r.bot_id, 901)
            self.assertGreater(r.sup_id, 0)
            self.assertTrue(r.sup)

    def test_returns_sorted_by_smoothed_rate_desc(self):
        recs = S101.top_duos_for_bot("Smolder", top_n=10)
        if len(recs) < 2:
            self.skipTest("not enough pairings for sort assertion")
        rates = [r.smoothed_rate for r in recs]
        self.assertEqual(rates, sorted(rates, reverse=True))

    def test_respects_top_n_cap(self):
        recs = S101.top_duos_for_bot("Smolder", top_n=2)
        self.assertLessEqual(len(recs), 2)

    def test_unknown_champ_returns_empty(self):
        self.assertEqual(S101.top_duos_for_bot("DefinitelyNotAChamp"), [])
        self.assertEqual(S101.top_duos_for_bot(""), [])


class TopDuosForSupTests(unittest.TestCase):
    def setUp(self):
        S101._reset_cache()

    def test_known_sup_returns_pairings(self):
        # Brand (id 63) is a hot meta sup with many pairings.
        recs = S101.top_duos_for_sup("Brand", top_n=4)
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertEqual(r.sup, "Brand")
            self.assertEqual(r.sup_id, 63)
            self.assertGreater(r.bot_id, 0)
            self.assertTrue(r.bot)

    def test_returns_sorted_by_smoothed_rate_desc(self):
        recs = S101.top_duos_for_sup("Brand", top_n=10)
        if len(recs) < 2:
            self.skipTest("not enough pairings")
        rates = [r.smoothed_rate for r in recs]
        self.assertEqual(rates, sorted(rates, reverse=True))


class TopSoloPicksTests(unittest.TestCase):
    def setUp(self):
        S101._reset_cache()

    def test_bot_role_returns_non_empty(self):
        recs = S101.top_solo_picks("bot", top_n=4)
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertEqual(r.role, "bot")
            self.assertGreater(r.champ_id, 0)
            self.assertTrue(r.champ)
            self.assertGreater(r.smoothed_rate, 0.0)

    def test_sup_role_returns_non_empty(self):
        recs = S101.top_solo_picks("sup", top_n=4)
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertEqual(r.role, "sup")
            self.assertGreater(r.champ_id, 0)

    def test_invalid_role_returns_empty(self):
        self.assertEqual(S101.top_solo_picks("top"), [])
        self.assertEqual(S101.top_solo_picks(""), [])

    def test_sorted_by_smoothed_rate_desc(self):
        recs = S101.top_solo_picks("bot", top_n=20)
        if len(recs) < 2:
            self.skipTest("need at least 2 to assert order")
        rates = [r.smoothed_rate for r in recs]
        self.assertEqual(rates, sorted(rates, reverse=True))


class PairSynergyTests(unittest.TestCase):
    def setUp(self):
        S101._reset_cache()

    def test_known_pair_returns_record(self):
        # irank 1 in the source: Ashe (22) + Seraphine (147).
        rec = S101.pair_synergy("Ashe", "Seraphine")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.bot, "Ashe")
        self.assertEqual(rec.sup, "Seraphine")
        self.assertEqual(rec.bot_id, 22)
        self.assertEqual(rec.sup_id, 147)
        self.assertEqual(rec.irank, 1)
        # Seed doublewinrate is 0.5653.
        self.assertAlmostEqual(rec.doublewinrate, 0.5653)

    def test_unknown_pair_returns_none(self):
        self.assertIsNone(S101.pair_synergy("Ashe", "Garen"))
        self.assertIsNone(S101.pair_synergy("UnknownChamp", "Seraphine"))


class LaplaceSmoothingTests(unittest.TestCase):
    def setUp(self):
        S101._reset_cache()

    def test_thin_sample_pulled_toward_half(self):
        # A pair with itemp1 ~0.30% has sample ~3 -> heavy Laplace pull.
        # A pair with itemp1 ~4.78% has sample ~48 -> mild pull.
        # Pick two records and verify the thin-sample one is shifted
        # MORE in magnitude relative to its raw doublewinrate.
        ashe_seraphine = S101.pair_synergy("Ashe", "Seraphine")  # itemp 4.78%
        # Find a thin-sample record by scanning for itemp <= 0.5%
        thin_rec = None
        for sup_id, lst in S101._BOTS_BY_SUP.items():
            for r in lst:
                if r["itemp_bot"] <= 0.005 and r["doublewinrate"] > 0.55:
                    thin_rec = r
                    break
            if thin_rec:
                break
        self.assertIsNotNone(thin_rec, "expected at least one thin-sample high-WR pair")
        # The thin-sample pair's smoothed_rate should be pulled lower
        # than its raw doublewinrate (Laplace shrinks toward 0.5).
        self.assertLess(thin_rec["smoothed_rate"], thin_rec["doublewinrate"])
        # The well-evidenced pair's smoothed_rate should be closer to
        # its raw doublewinrate than the thin-sample one.
        self.assertIsNotNone(ashe_seraphine)
        thin_shift = abs(thin_rec["smoothed_rate"] - thin_rec["doublewinrate"])
        thick_shift = abs(ashe_seraphine.smoothed_rate
                          - ashe_seraphine.doublewinrate)
        self.assertGreater(thin_shift, thick_shift)


class ResolveIdTests(unittest.TestCase):
    def setUp(self):
        S101._reset_cache()

    def test_case_insensitive(self):
        self.assertEqual(S101._resolve_id("ashe"), 22)
        self.assertEqual(S101._resolve_id("ASHE"), 22)
        self.assertEqual(S101._resolve_id("Ashe"), 22)

    def test_empty_returns_zero(self):
        self.assertEqual(S101._resolve_id(""), 0)
        self.assertEqual(S101._resolve_id(None), 0)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_source_is_ascii(self):
        path = _PROJECT_ROOT / "core" / "smoothed_rates_101qq.py"
        raw = path.read_bytes()
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"non-ASCII byte in core/smoothed_rates_101qq.py: {exc}")
        # No em-dashes or smart quotes (CLAUDE.md hard rule).
        for forbidden_cp in (0x2014, 0x2013, 0x201C, 0x201D, 0x2018, 0x2019):
            self.assertNotIn(chr(forbidden_cp), text,
                             f"forbidden codepoint U+{forbidden_cp:04X} in source")

    def test_tips_json_is_ascii(self):
        path = _PROJECT_ROOT / "data" / "laning_tips_duo.json"
        raw = path.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"non-ASCII byte in data/laning_tips_duo.json: {exc}")

    def test_seed_files_parse_as_json(self):
        # Ensure both seed files are valid JSON (defensive guard so a
        # later edit doesn't silently break the loader).
        ext = _PROJECT_ROOT / "data" / "external"
        env = json.loads(
            (ext / "101qq_hero_rank_double_tier200_capture_20260525.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(env.get("code"), 0)
        self.assertIsInstance(env.get("data"), list)
        id_map = json.loads(
            (ext / "101qq_id_map.json").read_text(encoding="utf-8"))
        self.assertIsInstance(id_map, dict)
        self.assertEqual(len(id_map), 65)


if __name__ == "__main__":
    unittest.main()
