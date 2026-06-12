"""Deep-audit cycle 8 P2 W1 dashboard slice E regression tests.

Covers the FIX-NOW findings on the post-game / WPA / builders surface:

  1. builders_last_match._build_last_match closed the SHARED per-thread
     cached ro_conn (dashboard/_context.py:38-47 cache contract), so the
     second same-thread call failed with "Cannot operate on a closed
     database" (proved live pre-fix).
  2. _build_last_match leaked the raw exception string into the payload
     "error" field rendered by the Post Game Review page.
  3. The 5 WPA routes cached dict(body) WITHOUT the model/model_version
     fields they add to fresh responses, so cached=True responses lost
     those keys (shape inconsistency between first and cached response).
  4. routes_ward_heat._CACHE had no size bound - distinct float window_s
     values grow it without limit (retention-less growth).
  5. routes_loadout._serve_lcu_cmd_result_get interpolated the decoded
     id query param into the outbound vision-server URL unescaped
     (param smuggling / malformed-URL 500s).
  6. WPA-family route module DB paths were CWD-relative Path("data")
     literals (routes_replay_events already used APP_DIR); a non-root
     CWD silently 503s. Pinned-path-literal class from the cycle 8
     charter.
  7. Generic 500 wrappers echoed str(exc) to the UI - same leak class
     dashboard/_handler.py:252-254 already documents must not happen.

No gitignored data is read - every DB is a throwaway temp file.
ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class _FakeHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler the routes use."""

    def __init__(self, path: str):
        self.path = path
        self.sent: list[tuple[int, bytes, str]] = []

    def _send(self, code: int, body: bytes, ctype: str, cache_control=None):
        self.sent.append((code, body, ctype))

    @property
    def last(self) -> tuple[int, dict]:
        code, body, _ = self.sent[-1]
        return code, json.loads(body.decode("utf-8"))


def _make_match_history_db(path: Path) -> None:
    """Schema mirror of tests/test_last_match_by_ts.py:_make_db."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  kda_str TEXT, game_time_s INTEGER, game_id INTEGER DEFAULT 0,"
        "  kills INTEGER, deaths INTEGER, assists INTEGER,"
        "  cs INTEGER, cs_per_min REAL, gold INTEGER, gold_per_min REAL,"
        "  kp_pct REAL, label TEXT, raw_data TEXT)"
    )
    conn.execute(
        "INSERT INTO matches (timestamp, mode, champion, grade, kda_str,"
        " game_time_s, kills, deaths, assists, cs, cs_per_min, gold,"
        " gold_per_min, kp_pct, label, raw_data)"
        " VALUES ('2026-06-01 12:00:00','SR','Jinx','A','10/2/8',1800,"
        " 10,2,8,200,6.7,14000,467,62,'','')"
    )
    conn.commit()
    conn.close()


def _make_empty_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE matches (match_id TEXT)")
    conn.commit()
    conn.close()


class BuildLastMatchSharedConnTests(unittest.TestCase):
    """Finding 1: closing the shared per-thread cached ro_conn."""

    def test_second_call_same_thread_succeeds(self):
        import dashboard.builders_last_match as blm
        from dashboard import _context
        with TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "data").mkdir()
            db_path = app_dir / "data" / "match_history.db"
            _make_match_history_db(db_path)
            try:
                with mock.patch.object(blm, "_APP_DIR", app_dir):
                    out1 = blm._build_last_match()
                    out2 = blm._build_last_match()
            finally:
                # The builder now (correctly) leaves the shared per-thread
                # conn OPEN in the cache; evict + close it here so Windows
                # lets TemporaryDirectory delete the db file.
                cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
                    str(db_path), None)
                if cached is not None:
                    cached.close()
        self.assertTrue(out1.get("found"), f"first call broken: {out1}")
        self.assertTrue(
            out2.get("found"),
            "second same-thread call failed - the shared ro_conn cache "
            f"was closed by the first call: {out2}",
        )
        self.assertNotIn("error", out2)


class BuildLastMatchErrorLeakTests(unittest.TestCase):
    """Finding 2: raw exception text must not reach the payload."""

    def test_error_payload_is_generic(self):
        import dashboard.builders_last_match as blm

        class _BoomConn:
            def execute(self, *a, **kw):
                raise sqlite3.OperationalError(
                    r"unable to open database file at C:\secret\leak.db")

            def close(self):
                pass

        with TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "data").mkdir()
            _make_match_history_db(app_dir / "data" / "match_history.db")
            with mock.patch.object(blm, "_APP_DIR", app_dir), \
                 mock.patch.object(blm, "_ro_conn",
                                   lambda p: _BoomConn()):
                out = blm._build_last_match()
        self.assertFalse(out.get("found"))
        err = out.get("error") or ""
        self.assertNotIn("secret", err,
                         f"raw exception text leaked to UI payload: {err!r}")
        self.assertEqual(err, "internal error - see logs")


class WpaFamilyCachedModelFieldTests(unittest.TestCase):
    """Finding 3: cached=True responses must keep the model field(s)."""

    def _family_modules(self):
        from dashboard import (routes_item_wpa, routes_rune_wpa,
                               routes_skill_wpa, routes_summspell_wpa)
        return [
            (routes_item_wpa, "compute_item_wpa",
             routes_item_wpa._serve_item_wpa, "/api/item-wpa"),
            (routes_rune_wpa, "compute_rune_wpa",
             routes_rune_wpa._serve_rune_wpa, "/api/rune-wpa"),
            (routes_skill_wpa, "compute_skill_wpa",
             routes_skill_wpa._serve_skill_wpa, "/api/skill-wpa"),
            (routes_summspell_wpa, "compute_summoner_spell_wpa",
             routes_summspell_wpa._serve_summspell_wpa,
             "/api/summspell-wpa"),
        ]

    def test_family_cached_response_keeps_model_field(self):
        def _stub(conn, min_n=None, queue_id=None, patch=None, model=None):
            return {"ok": True, "items": []}

        with TemporaryDirectory() as td:
            db = Path(td) / "rewind_history.db"
            _make_empty_db(db)
            absent_model = Path(td) / "absent_model.json"
            for mod, compute_name, serve, url in self._family_modules():
                with self.subTest(module=mod.__name__):
                    mod._CACHE.clear()
                    mod._MODEL_CACHE["mtime"] = None
                    mod._MODEL_CACHE["model"] = None
                    with mock.patch.object(mod, "_REWIND_DB", db), \
                         mock.patch.object(mod, "_MODEL_PATH", absent_model), \
                         mock.patch.object(mod, compute_name, _stub):
                        h1 = _FakeHandler(url)
                        serve(h1)
                        h2 = _FakeHandler(url)
                        serve(h2)
                    code1, p1 = h1.last
                    code2, p2 = h2.last
                    self.assertEqual(code1, 200)
                    self.assertEqual(code2, 200)
                    self.assertIn("model", p1)
                    self.assertTrue(p2.get("cached"),
                                    f"second hit not cached: {p2}")
                    self.assertIn(
                        "model", p2,
                        "cached response dropped the model field - "
                        "_cache_put stored body before enrichment")
                    self.assertEqual(p1["model"], p2["model"])

    def test_post_game_wpa_cached_response_keeps_model_fields(self):
        from dashboard import routes_post_game_wpa as rpgw

        def _stub(conn, match_id, model=None):
            return {"ok": True, "events": [], "top_phases": [],
                    "frame_count": 0, "event_count": 0}

        with TemporaryDirectory() as td:
            db = Path(td) / "rewind_history.db"
            _make_empty_db(db)
            absent_model = Path(td) / "absent_model.json"
            rpgw._CACHE.clear()
            rpgw._MODEL_CACHE["mtime"] = None
            rpgw._MODEL_CACHE["model"] = None
            url = "/api/post-game-wpa?match_id=M1"
            with mock.patch.object(rpgw, "_REWIND_DB", db), \
                 mock.patch.object(rpgw, "_MODEL_PATH", absent_model), \
                 mock.patch.object(rpgw, "_match_exists",
                                   lambda conn, mid: True), \
                 mock.patch.object(rpgw, "compute_match_wpa", _stub):
                h1 = _FakeHandler(url)
                rpgw._serve_post_game_wpa(h1)
                h2 = _FakeHandler(url)
                rpgw._serve_post_game_wpa(h2)
        _, p1 = h1.last
        code2, p2 = h2.last
        self.assertEqual(code2, 200)
        self.assertTrue(p2.get("cached"))
        self.assertIn("model", p2)
        self.assertIn("model_version", p2)
        self.assertEqual(p1["model"], p2["model"])


class WardHeatCacheBoundTests(unittest.TestCase):
    """Finding 4: response cache must be size-bounded."""

    def test_cache_bounded_under_distinct_windows(self):
        from dashboard import routes_ward_heat as rwh
        rwh._reset_caches()
        try:
            for i in range(80):
                h = _FakeHandler(f"/api/ward-heat?window_s={5 + i * 0.5}")
                rwh._serve_ward_heat(h)
                code, _ = h.last
                self.assertEqual(code, 200)
            with rwh._CACHE_LOCK:
                size = len(rwh._CACHE)
            self.assertLessEqual(
                size, 64,
                f"ward-heat cache grew unbounded: {size} entries after "
                "80 distinct window_s values")
        finally:
            rwh._reset_caches()


class LcuCmdResultQuoteTests(unittest.TestCase):
    """Finding 5: id query param must be percent-encoded outbound."""

    def test_id_is_percent_encoded(self):
        if "web_dashboard" not in sys.modules:
            stub = type(sys)("web_dashboard")
            stub._VISION_TOKEN = "test-token"
            sys.modules["web_dashboard"] = stub
        else:
            sys.modules["web_dashboard"]._VISION_TOKEN = "test-token"
        from dashboard import routes_loadout as rt

        class _Resp:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        um = mock.MagicMock(return_value=_Resp())
        h = _FakeHandler("/api/lcu-cmd-result?id=abc%20def%26x%3D1")
        with mock.patch("urllib.request.urlopen", um):
            rt._serve_lcu_cmd_result_get(h)
        self.assertTrue(um.called, f"urlopen never reached: {h.sent}")
        req = um.call_args[0][0]
        url = getattr(req, "full_url", str(req))
        self.assertIn(
            "id=abc%20def%26x%3D1", url,
            f"decoded id was interpolated unescaped into the outbound "
            f"URL: {url!r}")


class AbsoluteDbPathTests(unittest.TestCase):
    """Finding 6: module DB/model paths must not be CWD-relative."""

    def test_wpa_and_rubric_paths_are_absolute(self):
        from dashboard import (routes_item_wpa, routes_post_game_rubric,
                               routes_post_game_wpa, routes_rune_wpa,
                               routes_skill_wpa, routes_summspell_wpa)
        for mod in (routes_post_game_wpa, routes_item_wpa, routes_rune_wpa,
                    routes_skill_wpa, routes_summspell_wpa,
                    routes_post_game_rubric):
            with self.subTest(module=mod.__name__):
                self.assertTrue(
                    mod._REWIND_DB.is_absolute(),
                    f"{mod.__name__}._REWIND_DB is CWD-relative: "
                    f"{mod._REWIND_DB}")
        for mod in (routes_post_game_wpa, routes_item_wpa, routes_rune_wpa,
                    routes_skill_wpa, routes_summspell_wpa):
            with self.subTest(module=mod.__name__, attr="_MODEL_PATH"):
                self.assertTrue(mod._MODEL_PATH.is_absolute())
        from dashboard import routes_post_game_rubric as rrub
        self.assertTrue(rrub._STATE_JSON.is_absolute())


class Route500GenericErrorTests(unittest.TestCase):
    """Finding 7: generic 500 wrappers must not echo str(exc)."""

    def test_rubric_500_error_is_generic(self):
        from dashboard import routes_post_game_rubric as rrub
        with TemporaryDirectory() as td:
            db = Path(td) / "rewind_history.db"
            _make_empty_db(db)
            h = _FakeHandler("/api/post-game-rubric?match_id=M1")
            boom = RuntimeError(r"state parse blew up at C:\secret\leak")
            with mock.patch.object(rrub, "_REWIND_DB", db), \
                 mock.patch.object(rrub, "_load_operator_puuid",
                                   side_effect=boom):
                rrub._serve_post_game_rubric(h)
        code, payload = h.last
        self.assertEqual(code, 500)
        err = payload.get("error") or ""
        self.assertNotIn("secret", err,
                         f"raw exception leaked in 500 body: {err!r}")
        self.assertEqual(err, "internal error - see logs")

    def test_history_500_error_is_generic(self):
        from dashboard import routes_history as rh
        h = _FakeHandler("/api/history?scope=14d")
        boom = RuntimeError(r"db exploded at C:\secret\leak")
        with mock.patch.object(rh, "_build_history", side_effect=boom):
            rh._serve_history(h)
        code, payload = h.last
        self.assertEqual(code, 500)
        err = payload.get("error") or ""
        self.assertNotIn("secret", err)
        self.assertEqual(err, "internal error - see logs")


if __name__ == "__main__":
    unittest.main()
