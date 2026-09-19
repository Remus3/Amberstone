"""Phase 3 (s176, 2026-05-12) - dashboard/routes_archetype.py tests.

Exercises the GET / POST handlers via a stub handler. Persistence is
patched to a tempdir so the real ``data/cs_archetype_picks.json`` stays
clean.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import archetype_picks
from dashboard import routes_archetype


class StubHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler. Captures the
    last ``_send`` call so tests can inspect status + body."""

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
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


class RoutesArchetypeBase(unittest.TestCase):
    """Common setUp/tearDown to patch persistence to a tempdir."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name) / "cs_archetype_picks.json"
        self._patch_path = mock.patch.object(
            archetype_picks, "_PICKS_PATH", self.tmp_path)
        self._patch_dir = mock.patch.object(
            archetype_picks, "_DATA_DIR", Path(self.tmpdir.name))
        self._patch_path.start()
        self._patch_dir.start()
        archetype_picks._invalidate_picks_cache()

    def tearDown(self):
        self._patch_path.stop()
        self._patch_dir.stop()
        archetype_picks._invalidate_picks_cache()
        self.tmpdir.cleanup()


class GetEndpointTests(RoutesArchetypeBase):
    def test_get_no_champion_returns_full_map(self):
        h = StubHandler(path="/api/cs-archetype-pick")
        routes_archetype._serve_archetype_get(h)
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertIn("picks", body)
        self.assertIn("archetypes", body)
        self.assertIn("implemented", body)
        self.assertIn("sources", body)
        self.assertEqual(body["picks"], {})  # empty tempdir

    def test_get_with_champion_returns_default_pick(self):
        h = StubHandler(path="/api/cs-archetype-pick?champion=Aatrox")
        routes_archetype._serve_archetype_get(h)
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], "Aatrox")
        self.assertEqual(body["pick"]["primary"], "bruiser")
        self.assertEqual(body["pick"]["source"], "default")

    def test_get_with_champion_returns_override_when_set(self):
        archetype_picks.save_archetype_pick("Aatrox", primary="tank", source="user_cs")
        h = StubHandler(path="/api/cs-archetype-pick?champion=Aatrox")
        routes_archetype._serve_archetype_get(h)
        body = h.parsed()
        self.assertEqual(body["pick"]["primary"], "tank")
        self.assertEqual(body["pick"]["source"], "user_cs")

    def test_get_response_lists_six_archetypes(self):
        h = StubHandler(path="/api/cs-archetype-pick")
        routes_archetype._serve_archetype_get(h)
        body = h.parsed()
        self.assertEqual(len(body["archetypes"]), 6)


class PostEndpointTests(RoutesArchetypeBase):
    def test_post_saves_pick(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "primary": "tank", "source": "user_cs",
        })
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["pick"]["primary"], "tank")
        # Verify it persisted
        loaded = archetype_picks.get_archetype_for("Aatrox")
        self.assertEqual(loaded["primary"], "tank")

    def test_post_clear_removes_override(self):
        archetype_picks.save_archetype_pick("Aatrox", primary="tank")
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "clear": True,
        })
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertTrue(body["cleared"])
        # Reads back as default now.
        loaded = archetype_picks.get_archetype_for("Aatrox")
        self.assertEqual(loaded["source"], "default")

    def test_post_clear_when_nothing_to_clear(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "clear": True,
        })
        self.assertEqual(h.last_status, 200)
        self.assertFalse(h.parsed()["cleared"])

    def test_post_clear_read_failure_500s_without_leak(self):
        # RM-444 caller check: clear_archetype_pick now raises instead of
        # overwriting the file; the route must degrade, not crash, and the
        # raw exception text (may carry a path) stays in the log.
        leak = "C:/secret/path/cs_archetype_picks.json"

        def _boom(champion):
            raise archetype_picks.PicksReadError(leak)

        h = StubHandler()
        with mock.patch.object(routes_archetype, "clear_archetype_pick", _boom):
            routes_archetype._serve_archetype_post(h, {
                "champion": "Aatrox", "clear": True,
            })
        self.assertEqual(h.last_status, 500)
        self.assertNotIn(leak, h.last_body.decode("utf-8"))

    def test_post_save_read_failure_500s_without_leak(self):
        leak = self.tmpdir.name
        self.tmp_path.write_text('{"Aatrox": {"primary": "ta', encoding="utf-8")
        before = self.tmp_path.read_bytes()
        h = StubHandler()
        with self.assertLogs("rc.web_dashboard", level="WARNING"):
            routes_archetype._serve_archetype_post(h, {
                "champion": "Lux", "primary": "mage",
            })
        self.assertEqual(h.last_status, 500)
        self.assertNotIn(leak, h.last_body.decode("utf-8"))
        self.assertEqual(self.tmp_path.read_bytes(), before)

    def test_post_missing_champion_400s(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {"primary": "tank"})
        self.assertEqual(h.last_status, 400)
        self.assertIn("champion", h.parsed()["error"])

    def test_post_missing_primary_400s(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {"champion": "Aatrox"})
        self.assertEqual(h.last_status, 400)
        self.assertIn("primary", h.parsed()["error"])

    def test_post_invalid_primary_400s(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "primary": "bogus",
        })
        self.assertEqual(h.last_status, 400)

    def test_post_invalid_source_400s(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "primary": "tank", "source": "bogus",
        })
        self.assertEqual(h.last_status, 400)

    def test_post_validation_400_does_not_leak_exception_text(self):
        """RM-239 / RM-242 SITE 1 - the ValueError arm around
        ``save_archetype_pick`` used to serialize ``str(exc)`` verbatim, so
        the raiser's message reached the wire. Post-fix the body is a
        curated generic line and the raw cause stays in the log only.

        Behavioural on purpose: this drives the handler and reads the
        response body. It deliberately does NOT extend the symbol-identity
        tuple in tests/test_dashboard_error_scrub_rm134.py - that guard
        asserts binding, never use, which is why this class of leak
        survived three sweeps.
        """
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "primary": "bogus",
        })
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertEqual(body["error"], "invalid pick - see logs")
        # No fragment of core.archetype_picks' raiser text may survive.
        raw = h.last_body.decode("utf-8")
        for fragment in ("must be one of", "bogus", "primary must"):
            self.assertNotIn(fragment, raw)

    def test_post_invalid_source_400_does_not_leak_exception_text(self):
        """Same arm, the source-validation raiser. Pinned separately so a
        partial fix that only covers one raiser cannot pass.
        """
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "primary": "tank", "source": "bogus",
        })
        self.assertEqual(h.last_status, 400)
        raw = h.last_body.decode("utf-8")
        self.assertEqual(h.parsed()["error"], "invalid pick - see logs")
        for fragment in ("must be one of", "bogus", "source must"):
            self.assertNotIn(fragment, raw)

    def test_post_non_object_body_400s(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, ["not", "a", "dict"])
        self.assertEqual(h.last_status, 400)

    def test_post_default_source_is_user_cs(self):
        h = StubHandler()
        routes_archetype._serve_archetype_post(h, {
            "champion": "Aatrox", "primary": "tank",
        })
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["pick"]["source"], "user_cs")


class RouteRegistrationTests(unittest.TestCase):
    """Pin the dispatcher wiring so a future refactor doesn't silently
    drop the routes."""

    def test_get_route_registered(self):
        from dashboard import _dispatch
        # Clear cache to force re-import path
        _dispatch._GET_CACHE = None
        routes = _dispatch._gather_get()
        # Find a matcher that matches /api/cs-archetype-pick
        matched = any(m("/api/cs-archetype-pick") for m, _fn in routes)
        self.assertTrue(matched, "GET /api/cs-archetype-pick not in dispatch table")

    def test_post_route_registered(self):
        from dashboard import _dispatch
        _dispatch._POST_CACHE = None
        routes = _dispatch._gather_post()
        matched = any(m("/api/cs-archetype-pick") for m, _fn in routes)
        self.assertTrue(matched, "POST /api/cs-archetype-pick not in dispatch table")


if __name__ == "__main__":
    unittest.main()
