"""S144-T-680 - /api/ds-relscore input trust (true-audit, lane 8).

Measured before the fix (2026-11-09, snapshot 16.22.1):

* An unknown champion (``NotAChamp``, a display name ``Kai'Sa``, the
  lower-case ``caitlyn``) or an unknown item id (``zzz``, ``999999``,
  ``3031.0``, ``-1``) reached ``DataSnapshot.champion`` / ``.item``, raised
  ``KeyError`` and landed on the catch-all: 503 "DS engine compute failed",
  a WARNING carrying the caller's value, and no cache entry - so the same
  caller mistake re-ran and re-logged on every poll, and read as an engine
  fault. It is a client error: the route now answers 400 with a fixed line
  (never the caller's value), logs nothing above DEBUG and never calls the
  ranker, the same discipline as the unsupported-mode 400 (RM-1330).
* Six junk ids (``a,b,c,d,e,f``) answered 200 ``reason=build_full`` and were
  cached under the junk key: the slot count was checked before the ids were
  known. Ids are now checked first.
* The item list was unbounded: every comma-separated entry went into the
  cache key. A raw list longer than ``_MAX_ITEM_PARAMS`` is now a 400.
* A non-finite ``delta_dps`` from the ranker (NaN / inf) reached
  ``json.dumps``, which emits the bare tokens ``NaN`` / ``Infinity``; the
  browser's ``JSON.parse`` rejects the whole body, so one bad row blanked the
  panel. A NaN top row also zeroed every ``score_pct``. Non-finite rows are
  now dropped and the bar is scaled to the MAX finite delta, as the module
  docstring always claimed.

The genuine-fault path (a RuntimeError inside the ranker) stays 503 + WARNING
+ uncached; that is pinned by test_routes_ds_relscore_full_build.py.
"""
from __future__ import annotations

import json
import logging
import math
import pathlib
import unittest
from types import SimpleNamespace

import agents.daemon_slayer.rank as rank_mod
from dashboard import routes_ds_relscore as rt

_CHAMP = "Caitlyn"
_SIX = ["3031", "3036", "3006", "3072", "3094", "3033"]


class StubHandler:
    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8"))


def _do(path: str) -> StubHandler:
    h = StubHandler(path=path)
    rt._serve_ds_relscore(h)
    return h


class _SpyRanker:
    """Swap rank.rank_items for a recorder; restore on exit."""

    def __init__(self, ranked=None):
        self.calls = 0
        self._ranked = ranked
        self._real = None

    def __enter__(self):
        self._real = rank_mod.rank_items

        def _fake(*a, **kw):
            self.calls += 1
            if self._ranked is None:
                return self._real(*a, **kw)
            return SimpleNamespace(ranked=list(self._ranked))

        rank_mod.rank_items = _fake
        return self

    def __exit__(self, *exc):
        rank_mod.rank_items = self._real
        return False


def _row(item_id, delta, gold=1000):
    return SimpleNamespace(item_id=item_id, item_name=f"Item {item_id}",
                           delta_dps=delta, gold=gold)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()

    def tearDown(self) -> None:
        rt._reset_caches()

    def assert_client_error(self, path: str, error: str) -> None:
        logger = logging.getLogger("rc.web_dashboard")
        with self.assertNoLogs(logger, level="INFO"), _SpyRanker() as spy:
            h = _do(path)
        self.assertEqual(h.last_status, 400, h.last_body)
        body = h.parsed()
        self.assertIs(body["ok"], False)
        self.assertEqual(body["error"], error)
        self.assertEqual(spy.calls, 0, "the ranker must not be called")
        self.assertEqual(rt._CACHE, {}, "a client error is never cached")


class UnknownChampionTests(_Base):
    def test_unknown_champion_is_a_400_not_a_503(self) -> None:
        for raw in ("NotAChamp", "Kai%27Sa", "caitlyn", "Bad%0Aline"):
            with self.subTest(raw=raw):
                rt._reset_caches()
                self.assert_client_error(
                    f"/api/ds-relscore?champion={raw}", "unknown champion")

    def test_reply_never_echoes_the_caller_value(self) -> None:
        h = _do("/api/ds-relscore?champion=ZZ%3Cscript%3EQQ")
        self.assertEqual(h.last_status, 400)
        self.assertNotIn(b"ZZ", h.last_body)
        self.assertNotIn(b"script", h.last_body)

    def test_known_champion_still_ranks(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_CHAMP}")
        self.assertEqual(h.last_status, 200)
        self.assertIs(h.parsed()["ok"], True)


class UnknownItemTests(_Base):
    def test_unknown_item_is_a_400_not_a_503(self) -> None:
        for raw in ("zzz", "999999", "3031.0", "-1", "3031,nope"):
            with self.subTest(raw=raw):
                rt._reset_caches()
                self.assert_client_error(
                    f"/api/ds-relscore?champion={_CHAMP}&items={raw}",
                    "unknown item")

    def test_six_junk_ids_are_not_a_cached_full_build(self) -> None:
        self.assert_client_error(
            f"/api/ds-relscore?champion={_CHAMP}&items=a,b,c,d,e,f",
            "unknown item")

    def test_six_real_ids_are_still_a_full_build(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_CHAMP}&items=" + ",".join(_SIX))
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed().get("reason"), "build_full")

    def test_trinket_still_dropped_before_validation(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_CHAMP}&items=3031,3340")
        self.assertEqual(h.last_status, 200)
        self.assertIs(h.parsed()["ok"], True)


class ItemListBoundTests(_Base):
    def test_overlong_item_list_is_a_400(self) -> None:
        n = rt._MAX_ITEM_PARAMS + 1
        self.assert_client_error(
            f"/api/ds-relscore?champion={_CHAMP}&items=" + ",".join(["3031"] * n),
            "too many items")

    def test_bound_admits_a_full_live_inventory(self) -> None:
        # Seven Live Client rows (six slots + trinket) plus consumables.
        self.assertGreaterEqual(rt._MAX_ITEM_PARAMS, 7)
        raw = ",".join(_SIX[:5] + ["3340", "2003"])
        h = _do(f"/api/ds-relscore?champion={_CHAMP}&items={raw}")
        self.assertEqual(h.last_status, 200)


class NonFiniteRowTests(_Base):
    def _serve(self, ranked) -> StubHandler:
        with _SpyRanker(ranked):
            return _do(f"/api/ds-relscore?champion={_CHAMP}")

    def test_nan_and_inf_rows_never_reach_the_json(self) -> None:
        h = self._serve([_row("1", float("nan")), _row("2", 50.0),
                         _row("3", float("inf")), _row("4", 25.0)])
        self.assertEqual(h.last_status, 200)
        text = h.last_body.decode("utf-8")
        for token in ("NaN", "Infinity"):
            self.assertNotIn(token, text)
        # Strict parse, as the browser does.
        body = json.loads(text, parse_constant=lambda c: self.fail(c))
        self.assertEqual([r["item_id"] for r in body["rows"]], ["2", "4"])
        self.assertEqual(body["count"], 2)

    def test_bar_scales_to_the_max_finite_delta(self) -> None:
        h = self._serve([_row("1", float("nan")), _row("2", 40.0),
                         _row("3", 80.0)])
        rows = {r["item_id"]: r["score_pct"] for r in h.parsed()["rows"]}
        self.assertEqual(rows, {"2": 50.0, "3": 100.0})

    def test_all_non_finite_is_no_rows(self) -> None:
        h = self._serve([_row("1", float("nan")), _row("2", float("-inf"))])
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertIs(body["ok"], False)
        self.assertEqual(body["reason"], "no_rows")

    def test_non_positive_top_still_reads_zero(self) -> None:
        h = self._serve([_row("1", -5.0), _row("2", -9.0)])
        self.assertTrue(all(r["score_pct"] == 0.0 for r in h.parsed()["rows"]))

    def test_every_emitted_number_is_finite(self) -> None:
        h = self._serve([_row("1", 70.0), _row("2", 35.0)])
        for r in h.parsed()["rows"]:
            self.assertTrue(math.isfinite(r["delta_dps"]))
            self.assertTrue(math.isfinite(r["score_pct"]))


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 128 for b in raw))
        self.assertNotIn(b"\r", raw)


if __name__ == "__main__":
    unittest.main()
