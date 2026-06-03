"""tests/test_routes_duo_synergy.py - Item 199 Slice CD route tests.

Covers `dashboard/routes_duo_synergy.py`:
  * mode resolution priority (lock > hover, both_locked covers both)
  * top_row + bottom_row shape per mode
  * both_locked surfaces a laning tip
  * none mode default fallback uses my_role
  * top_n cap (max 4)
  * TTL cache hit/miss lifecycle
  * cache keys split per query tuple
  * 500 on unexpected internal exception (fail-soft envelope)
  * Route registered in the dispatcher
  * ASCII hygiene on the route module
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import smoothed_rates_101qq as S101  # noqa: E402
from dashboard import routes_duo_synergy as RDS  # noqa: E402

import os  # noqa: E402

# item 277: pin the live Tencent fetch OFF so the route tests assert the
# deterministic committed STATIC seed (the live path is covered separately).
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


class StubHandler:
    """Same shape as test_routes_ward_heat.StubHandler."""

    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None
        self.last_ct: str | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        if not self.last_body:
            return {}
        return json.loads(self.last_body.decode("utf-8"))


def _do(path: str) -> StubHandler:
    h = StubHandler(path=path)
    RDS._serve_duo_synergy(h)
    return h


class DuoSynergyBase(unittest.TestCase):
    def setUp(self):
        RDS._reset_caches()
        S101._reset_cache()


class ModeResolutionTests(DuoSynergyBase):
    def test_both_locked_priority(self):
        mode = RDS._resolve_mode("Ashe", "OtherBot", "Seraphine", "OtherSup")
        self.assertEqual(mode, "both_locked")

    def test_bot_locked_wins_over_sup_hover(self):
        # Lock on bot side is firm; sup hover may swap. Lock should win.
        mode = RDS._resolve_mode("Ashe", "", "", "Lulu")
        self.assertEqual(mode, "bot_locked")

    def test_sup_locked_when_bot_empty(self):
        mode = RDS._resolve_mode("", "", "Senna", "")
        self.assertEqual(mode, "sup_locked")

    def test_bot_hover_when_no_locks(self):
        mode = RDS._resolve_mode("", "Jinx", "", "")
        self.assertEqual(mode, "bot_hover")

    def test_sup_hover_when_no_locks_or_bot(self):
        mode = RDS._resolve_mode("", "", "", "Thresh")
        self.assertEqual(mode, "sup_hover")

    def test_none_when_all_empty(self):
        mode = RDS._resolve_mode("", "", "", "")
        self.assertEqual(mode, "none")


class NoneModeDefaultTests(DuoSynergyBase):
    def test_none_returns_both_rows_populated(self):
        h = _do("/api/duo-synergy?my_role=bot&top_n=4")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.last_ct, "application/json")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "none")
        self.assertEqual(body["my_role"], "bot")
        self.assertEqual(len(body["top_row"]), 4)
        self.assertEqual(len(body["bottom_row"]), 4)
        # Top row champs are aggregated bot picks; sample one cell shape.
        cell = body["top_row"][0]
        for field in ("champ", "champ_key", "icon_id", "rank", "iwinrate",
                      "itemp", "pair_with", "pair_with_key",
                      "doublewinrate", "smoothed_rate"):
            self.assertIn(field, cell)
        # In 'none' mode there is no pair context.
        self.assertIsNone(cell["pair_with"])
        self.assertIsNone(cell["doublewinrate"])
        # Laning tips only surface in both_locked.
        self.assertIsNone(body["laning_tips"])


class BotLockedTests(DuoSynergyBase):
    def test_bot_locked_top_row_singleton_bottom_row_topn(self):
        h = _do("/api/duo-synergy?ally_bot_lock=Smolder&top_n=4")
        body = h.parsed()
        self.assertEqual(body["mode"], "bot_locked")
        self.assertEqual(len(body["top_row"]), 1)
        self.assertEqual(body["top_row"][0]["champ"], "Smolder")
        # Bottom row should have up to 4 sup recs paired with Smolder.
        self.assertGreater(len(body["bottom_row"]), 0)
        self.assertLessEqual(len(body["bottom_row"]), 4)
        for c in body["bottom_row"]:
            self.assertEqual(c["pair_with"], "Smolder")
            self.assertIsNotNone(c["doublewinrate"])


class SupLockedTests(DuoSynergyBase):
    def test_sup_locked_bottom_row_singleton_top_row_topn(self):
        h = _do("/api/duo-synergy?ally_sup_lock=Brand&top_n=4")
        body = h.parsed()
        self.assertEqual(body["mode"], "sup_locked")
        self.assertEqual(len(body["bottom_row"]), 1)
        self.assertEqual(body["bottom_row"][0]["champ"], "Brand")
        self.assertGreater(len(body["top_row"]), 0)
        for c in body["top_row"]:
            self.assertEqual(c["pair_with"], "Brand")


class BothLockedTests(DuoSynergyBase):
    def test_both_locked_surfaces_laning_tips(self):
        # Use a pair that's in the laning_tips_duo.json data.
        h = _do("/api/duo-synergy?ally_bot_lock=Jinx&ally_sup_lock=Senna")
        body = h.parsed()
        self.assertEqual(body["mode"], "both_locked")
        # Both rows are 1-cell shows.
        self.assertEqual(len(body["top_row"]), 1)
        self.assertEqual(len(body["bottom_row"]), 1)
        self.assertEqual(body["top_row"][0]["champ"], "Jinx")
        self.assertEqual(body["bottom_row"][0]["champ"], "Senna")
        # Laning tips should be populated (specific or default).
        self.assertIsNotNone(body["laning_tips"])
        self.assertIsInstance(body["laning_tips"], str)
        self.assertGreater(len(body["laning_tips"]), 0)


class TopNCapTests(DuoSynergyBase):
    def test_top_n_cap_at_4(self):
        h = _do("/api/duo-synergy?my_role=bot&top_n=99")
        body = h.parsed()
        # UI grid is fixed at 4 cols; cap enforced server-side.
        self.assertLessEqual(len(body["top_row"]), 4)
        self.assertLessEqual(len(body["bottom_row"]), 4)

    def test_top_n_min_at_1(self):
        h = _do("/api/duo-synergy?my_role=bot&top_n=0")
        body = h.parsed()
        # 0 input is clamped to >= 1 (top_n=1).
        self.assertGreaterEqual(len(body["top_row"]), 1)


class CacheLifecycleTests(DuoSynergyBase):
    def test_cache_hit_on_second_call(self):
        # 1st call populates the cache; 2nd call (same params) hits it.
        h1 = _do("/api/duo-synergy?my_role=bot")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do("/api/duo-synergy?my_role=bot")
        self.assertTrue(h2.parsed()["cached"])

    def test_cache_keys_split_per_query(self):
        # Different my_role -> different cache slot -> miss on switch.
        _ = _do("/api/duo-synergy?my_role=bot")
        h2 = _do("/api/duo-synergy?my_role=sup")
        self.assertFalse(h2.parsed()["cached"])

    def test_cache_keys_split_per_lock(self):
        _ = _do("/api/duo-synergy?ally_bot_lock=Smolder")
        h2 = _do("/api/duo-synergy?ally_bot_lock=Jinx")
        self.assertFalse(h2.parsed()["cached"])


class FailSoftEnvelopeTests(DuoSynergyBase):
    def test_internal_exception_returns_500_json(self):
        # Force an exception inside _build_payload by patching it.
        original = RDS._build_payload

        def boom(*args, **kwargs):
            raise RuntimeError("forced for test")

        RDS._build_payload = boom
        try:
            h = _do("/api/duo-synergy?my_role=bot&ally_bot_lock=Ashe")
            self.assertEqual(h.last_status, 500)
            body = h.parsed()
            self.assertFalse(body["ok"])
            self.assertIn("forced for test", body["error"])
        finally:
            RDS._build_payload = original


class RouteRegistrationTests(DuoSynergyBase):
    def test_route_registered_in_dispatcher(self):
        from dashboard import _dispatch
        _dispatch._GET_CACHE = None  # force rebuild
        routes = _dispatch._gather_get()
        # The matcher closures don't carry the pattern as text; assert
        # by probing them with the path.
        matched = any(matcher("/api/duo-synergy") for matcher, _ in routes)
        self.assertTrue(matched, "/api/duo-synergy not registered")

    def test_route_module_exports_GET_ROUTES(self):
        self.assertTrue(hasattr(RDS, "GET_ROUTES"))
        self.assertEqual(len(RDS.GET_ROUTES), 1)


class AsciiHygieneTests(unittest.TestCase):
    def test_route_module_source_is_ascii(self):
        path = _PROJECT_ROOT / "dashboard" / "routes_duo_synergy.py"
        raw = path.read_bytes()
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"non-ASCII byte in routes_duo_synergy.py: {exc}")
        for forbidden_cp in (0x2014, 0x2013, 0x201C, 0x201D, 0x2018, 0x2019):
            self.assertNotIn(chr(forbidden_cp), text,
                             f"forbidden codepoint U+{forbidden_cp:04X} in route module")

    def test_mock_fixture_is_ascii(self):
        path = _PROJECT_ROOT / "web" / "data" / "ui_mock" / "duo_synergy.json"
        raw = path.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"non-ASCII byte in duo_synergy.json: {exc}")


class DuoSynergyFrontendRemovalDriftGuard(unittest.TestCase):
    """item 213 (2026-05-28): the champ-select bottom/support panel was
    reoriented from the 101.qq.com duo-synergy SUGGESTION grid to a LIVE
    ally-picks-by-role mirror (_csvRenderAllyRolesHtml). The duo-synergy
    frontend wiring (_csvFetchDuoSynergy + _csvRenderDuoSynergyHtml +
    _csvAllyBotSupState + the body.dataset.uiMock fixture branch) was
    removed from champ_select.js. The /api/duo-synergy ROUTE + the
    duo_synergy.json fixture are RETAINED (tested above) for any future
    re-use, but nothing in champ-select calls them now. This guard pins
    that removal so a stale re-wire fails CI before shipping.
    """

    @classmethod
    def setUpClass(cls):
        cls._js_path = _PROJECT_ROOT / "web" / "js" / "panels" / "champ_select.js"
        cls._js_text = cls._js_path.read_text(encoding="utf-8")

    def test_duo_synergy_fetcher_removed_from_frontend(self):
        self.assertNotIn("_csvFetchDuoSynergy", self._js_text,
                         "duo-synergy fetcher must stay removed (item 213)")
        self.assertNotIn("_csvRenderDuoSynergyHtml", self._js_text)

    def test_no_qq_source_ui_string_in_frontend(self):
        # The "101.qq.com tier-200" / "(101.qq.com)" UI strings were
        # removed. Surviving "101.qq" mentions are comments only.
        self.assertNotIn("source: 101.qq.com", self._js_text)
        self.assertNotIn("DUO SYNERGY (101.qq.com)", self._js_text)

    def test_ally_roles_panel_present(self):
        self.assertIn("_csvRenderAllyRolesHtml", self._js_text,
                      "ally-picks-by-role panel must replace duo synergy")
        self.assertIn("ALLY PICKS BY ROLE", self._js_text)

    def test_champ_name_helper_retained(self):
        # _csvChampNameFromId is reused by the ally-roles panel.
        self.assertIn("function _csvChampNameFromId", self._js_text)


if __name__ == "__main__":
    unittest.main()
