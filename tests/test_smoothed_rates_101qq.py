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
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import smoothed_rates_101qq as S101  # noqa: E402

import os  # noqa: E402

# item 277: these tests assert the committed STATIC May-25 seed values
# (exact iranks etc). Pin the live Tencent fetch OFF so they stay
# deterministic + offline; the live path is covered by
# test_synergy_external_source.py + test_smoothed_rates_101qq_live.py.
_PRIOR_LIVE_ENV: str | None = None


def setUpModule() -> None:
    global _PRIOR_LIVE_ENV
    _PRIOR_LIVE_ENV = os.environ.get("RC_DUO_SYNERGY_LIVE")
    os.environ["RC_DUO_SYNERGY_LIVE"] = "0"
    S101._reset_cache()


def tearDownModule() -> None:
    if _PRIOR_LIVE_ENV is None:
        os.environ.pop("RC_DUO_SYNERGY_LIVE", None)
    else:
        os.environ["RC_DUO_SYNERGY_LIVE"] = _PRIOR_LIVE_ENV
    S101._reset_cache()


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
        # The static seed is TRACKED and the live fetch falls back to it, so
        # Smolder always resolves a full page (MEASURED 2026-07-27: 10). Fewer
        # than 2 means the loader or the seed regressed and the sort assertion
        # below would otherwise pass vacuously.
        self.assertGreaterEqual(len(recs), 2, "Smolder resolved too few pairings to order")
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
        # Tracked seed - see the bot-side sibling above (MEASURED: 10).
        self.assertGreaterEqual(len(recs), 2, "Brand resolved too few pairings to order")
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
        # Tracked seed - see TopDuosForBotTests (MEASURED: 20 solo bot picks).
        self.assertGreaterEqual(len(recs), 2, "too few solo bot picks to order")
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


def _live_rows(pairs: list) -> list:
    """Rows in the Tencent `data` schema the indexer consumes.

    Same shape as the helper in tests/test_smoothed_rates_101qq_lock.py -
    duplicated rather than imported so this file stays standalone.
    """
    return [
        {
            "championid1": str(c1), "championid2": str(c2),
            "doublewinrate": wr, "iwinrate1": 0.5, "iwinrate2": 0.5,
            "itemp1": pick, "irank": i + 1,
            "lane1": "bottom", "lane2": "support",
        }
        for i, (c1, c2, wr, pick) in enumerate(pairs)
    ]


class StalenessSignalTests(unittest.TestCase):
    """RM-295a: a persistently failing refresh must be VISIBLE.

    `_publish` deliberately KEEPS the previous snapshot when a rebuild
    yields nothing, and that behaviour is CORRECT - these tests assert it
    survives. The defect is the SILENCE around it: `_SOURCE` kept naming
    the seed that built the original snapshot, so `source()` handed back
    "live" or "static" unqualified and nothing downstream could tell a
    snapshot frozen for hours from one fetched a second ago.
    """

    def setUp(self):
        self._prior_env = os.environ.get("RC_DUO_SYNERGY_LIVE")
        os.environ["RC_DUO_SYNERGY_LIVE"] = "1"
        self._orig_live_rows = S101._live_data_rows
        self._orig_clock = S101._clock
        self._orig_records_path = S101._RECORDS_PATH
        S101._reset_cache()

    def tearDown(self):
        self._join()
        S101._live_data_rows = self._orig_live_rows
        S101._clock = self._orig_clock
        S101._RECORDS_PATH = self._orig_records_path
        if self._prior_env is None:
            os.environ.pop("RC_DUO_SYNERGY_LIVE", None)
        else:
            os.environ["RC_DUO_SYNERGY_LIVE"] = self._prior_env
        S101._reset_cache()

    # -- helpers ----------------------------------------------------

    def _join(self, timeout: float = 15.0) -> None:
        t = getattr(S101, "_REFRESH_THREAD", None)
        if t is not None:
            t.join(timeout)

    def _prime(self, wr: float = 0.61) -> None:
        """Cold-start a good snapshot from a synthetic live row."""
        S101._live_data_rows = lambda: _live_rows([(22, 147, wr, "4.00%")])
        S101._reset_cache()
        self.assertEqual(S101.source(), "live")

    def _break_every_source(self) -> None:
        """Live endpoint down AND the static seed unreadable, persistently.

        Every rebuild from here yields zero records, so `_publish` takes
        the keep-the-previous-snapshot branch on every attempt.
        """
        def _boom() -> list:
            raise RuntimeError("CN endpoint down")
        S101._live_data_rows = _boom
        S101._RECORDS_PATH = (
            self._orig_records_path.parent / "does_not_exist_rm295a.json")

    def _advance_clock(self, multiple: float) -> None:
        base = time.monotonic()
        S101._clock = lambda: base + (S101._LIVE_TTL_S * multiple)

    def _drive_refresh(self, multiple: float) -> None:
        """Expire the TTL, then read through a PRODUCTION accessor so the
        background refresh is kicked the way live traffic kicks it."""
        self._advance_clock(multiple)
        S101.top_duos_for_bot("Ashe")
        self._join()

    # -- tests ------------------------------------------------------

    def test_health_is_exposed_and_machine_readable(self):
        self._prime()
        h = S101.health()
        self.assertIsInstance(h, dict)
        json.dumps(h)           # must survive the dashboard JSON encoder
        for key in ("source", "seed", "loaded", "degraded", "age_s",
                    "age_hours", "degraded_for_s", "failed_refreshes",
                    "last_refresh_ok", "stale_for_s", "coverage"):
            self.assertIn(key, h)
        self.assertIs(h["degraded"], False)
        self.assertEqual(h["seed"], "live")
        self.assertEqual(h["source"], "live")
        self.assertIsInstance(h["age_s"], float)
        self.assertEqual(h["failed_refreshes"], 0)
        self.assertGreater(h["coverage"]["total_records"], 0)

    def test_persistent_failure_marks_degraded_and_reports_frozen_age(self):
        self._prime()
        before = S101.coverage()["total_records"]
        self.assertGreater(before, 0)
        self._break_every_source()
        self._drive_refresh(4.0)

        h = S101.health()
        self.assertIs(h["degraded"], True,
                      "a refresh that did not land left no machine-readable "
                      "trace - the whole RM-295a defect")
        self.assertGreaterEqual(h["age_s"], S101._LIVE_TTL_S)
        self.assertGreaterEqual(h["age_hours"], 6.0)
        self.assertGreaterEqual(h["failed_refreshes"], 1)
        # degraded_for_s is measured from the FIRST failed refresh, so under
        # a frozen test clock it is exactly 0.0 at that instant. It must grow
        # as the outage continues, which is the half a consumer alerts on.
        self.assertGreaterEqual(h["degraded_for_s"], 0.0)
        # The KEEP behaviour is correct and must not be undone by the fix.
        self.assertEqual(h["coverage"]["total_records"], before)
        self.assertIsNotNone(S101.pair_synergy("Ashe", "Seraphine"))

        self._drive_refresh(8.0)
        h2 = S101.health()
        self.assertGreater(h2["degraded_for_s"], 0.0)
        self.assertGreater(h2["failed_refreshes"], h["failed_refreshes"])
        self.assertGreater(h2["age_s"], h["age_s"])
        self.assertEqual(h2["coverage"]["total_records"], before)
        # RM-295a acceptance, in the row's own key names: a snapshot kept
        # across TWO consecutive failed refreshes reports last_refresh_ok
        # False with a non-zero stale_for_s.
        self.assertGreaterEqual(h2["failed_refreshes"], 2)
        self.assertIs(h2["last_refresh_ok"], False)
        self.assertGreater(h2["stale_for_s"], 0.0)

    def test_source_stays_bare_and_freshness_lives_on_health(self):
        """A `stale:` prefix on `source()` was built, measured and REFUSED
        at merge (2026-09-12). This pins the refusal from the other side.

        `source()` answers provenance and keeps its three values; the
        freshness answer the prefix was reaching for is on `health()`,
        which is where a consumer must look. The sibling guard
        `test_source_stays_in_the_declared_domain`
        (tests/test_smoothed_rates_101qq_lock.py:375) pins the domain and
        was deliberately NOT widened - it stays green unmodified, which is
        the proof the contract is intact.
        """
        self._prime()
        self._break_every_source()
        self._drive_refresh(4.0)

        # Frozen for 24h, and source() still reports bare provenance.
        self.assertEqual(S101.source(), "live")
        self.assertIn(S101.source(), ("live", "static", "none"))
        self.assertNotIn(S101._STALE_PREFIX, S101.source())

        # The freshness that source() deliberately does not carry.
        h = S101.health()
        self.assertIs(h["degraded"], True)
        self.assertIs(h["last_refresh_ok"], False)
        self.assertGreater(h["stale_for_s"], 0.0)
        self.assertTrue(h["source"].startswith(S101._STALE_PREFIX))
        # The seed that built the frozen data stays recoverable there.
        self.assertEqual(h["seed"], "live")

    def test_a_successful_refresh_clears_the_degraded_flag(self):
        self._prime()
        self._break_every_source()
        self._drive_refresh(4.0)
        self.assertIs(S101.health()["degraded"], True)

        S101._RECORDS_PATH = self._orig_records_path
        S101._live_data_rows = lambda: _live_rows([(22, 147, 0.62, "4.00%")])
        self._drive_refresh(8.0)

        h = S101.health()
        self.assertIs(h["degraded"], False)
        self.assertEqual(h["failed_refreshes"], 0)
        self.assertEqual(h["degraded_for_s"], 0.0)
        self.assertEqual(S101.source(), "live")
        self.assertLess(h["age_s"], 1.0)

    def test_coverage_is_reachable_through_health(self):
        # RM-295b ADOPT-not-delete. Being honest about what this proves:
        # coverage() STILL has zero production consumers after this slice,
        # because the consuming route is deliberately not touched here
        # (another slice owns dashboard/). What it proves is that coverage()
        # is now carried BY health(), so the single route wiring that lands
        # health() adopts coverage() with it and no second wiring is needed.
        self._prime()
        h = S101.health()
        self.assertEqual(h["coverage"], S101.coverage())
        for key in ("unique_champions", "total_records",
                    "unique_bot_ids", "unique_sup_ids"):
            self.assertIn(key, h["coverage"])


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
