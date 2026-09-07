"""RM-354 - a 200-response bot wall must not destroy the good cached page.

`lib/scrapers/_base.py` `ScraperBase.fetch` had exactly one acceptance gate,
`resp.status >= 400`. Cloudflare's "Just a moment..." interstitial, site B's JS
challenge and every other bot wall are served as HTTP **200**, so the
interstitial passed that gate, was committed over the previously good HTML by
`_atomic_write_text`, and `_last_fetch.json` recorded `status="ok"` for any
health probe to read. `cache_path` is only ever a write target in that module -
there is no read-back fallback - so the good page was gone with no recovery.

The whole package was untested: `ScraperBase`, `lib.scrapers._base`,
`lib/scrapers/site_d.py` and `lib/scrapers/site_b.py` had ZERO references
under `tests/` when this file was written. That is why nothing caught it.

TARGET BEHAVIOUR these tests are written against:

  A  A 2xx body is checked BEFORE it reaches the cache. On rejection the
     existing cache file is byte-identical to what it was, `_last_fetch.json`
     records a non-"ok" status naming the reason, and `fetch` raises.
  B  The raise is a `RuntimeError` subclass, because the one production caller
     (`agents/agent2_backend/pipeline/orchestrator.py:149` and `:162`) already
     catches `RuntimeError` from `fetch` - an interstitial therefore takes the
     same per-source degradation path an HTTP 500 always did, with no caller
     change.
  C  A genuine page still writes the cache and still stamps "ok". The markers
     were measured against the six real cached pages on Legion
     (`data/meta_build/scraped/{site_b,site_d}/*.html`, 2.9M characters
     total): zero matched, whole-document, so the scan is whole-document
     rather than a head prefix.
  D  Both shipped subclasses inherit the guard - it lives in the base.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lib.http.client import Response
from lib.scrapers import SiteBScraper, SiteDScraper
from lib.scrapers import _base as scrapers_base
from lib.scrapers._base import ScraperBase

# A body long enough to clear any minimum-length floor, with no marker in it.
_GOOD_HTML = "<!DOCTYPE html><html><head><title>Ahri Build</title></head><body>" + (
    "<div class=\"item\">Ludens Companion</div>" * 200
) + "</body></html>"

# The literal shape the row filed: a Cloudflare interstitial served as 200.
_BOT_WALL = b"<html><title>Just a moment...</title></html>"

_PREVIOUS_GOOD = "<html><body>the previously good page</body></html>"


class _StubClient:
    """Stands in for `lib.http.get_client()`. Records what it was asked for."""

    def __init__(self, response: Response) -> None:
        self._response = response
        self.calls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> Response:
        self.calls.append(url)
        return self._response


class _FakeScraper(ScraperBase):
    site = "fakesite"
    base_url = "https://fake.example"


class _ScraperTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._orig_root = scrapers_base.SCRAPED_ROOT
        scrapers_base.SCRAPED_ROOT = self._root
        self.addCleanup(self._restore_root)
        self.addCleanup(self._tmp.cleanup)

    def _restore_root(self) -> None:
        scrapers_base.SCRAPED_ROOT = self._orig_root

    def _scraper(self, body: bytes, status: int = 200, cls=_FakeScraper):
        """Build a scraper wired to a stub client, with robots pre-resolved.

        `_robots_loaded = True` with `_robots = None` is the module's own
        permissive fallback (`_base.py:132-133`), so `can_fetch` answers True
        without a second network call - these tests are about the body gate,
        not about robots.
        """
        scraper = cls()
        scraper._client = _StubClient(
            Response(status=status, headers={}, body=body, url="https://fake.example/x")
        )
        scraper._robots_loaded = True
        scraper._robots = None
        return scraper

    def _seed_cache(self, scraper, key: str, text: str = _PREVIOUS_GOOD) -> Path:
        path = scraper.cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _stamp(self, scraper, key: str) -> dict:
        data = json.loads(scraper._last_fetch_path.read_text(encoding="utf-8"))
        return data[scraper.site][key]


class TestGoodPageContractIsPreserved(_ScraperTestCase):
    """C - the guard must not cost the happy path."""

    def test_a_genuine_page_is_cached_and_stamped_ok(self):
        scraper = self._scraper(_GOOD_HTML.encode("utf-8"))
        out = scraper.fetch("lol/ahri/build/", cache_key="ahri_sr")
        self.assertEqual(out, _GOOD_HTML)
        self.assertEqual(
            scraper.cache_path("ahri_sr").read_text(encoding="utf-8"), _GOOD_HTML
        )
        self.assertEqual(self._stamp(scraper, "ahri_sr")["status"], "ok")

    def test_a_genuine_page_overwrites_a_stale_cache_entry(self):
        scraper = self._scraper(_GOOD_HTML.encode("utf-8"))
        self._seed_cache(scraper, "ahri_sr")
        scraper.fetch("lol/ahri/build/", cache_key="ahri_sr")
        self.assertEqual(
            scraper.cache_path("ahri_sr").read_text(encoding="utf-8"), _GOOD_HTML
        )

    def test_a_large_marker_free_page_is_not_rejected(self):
        """Guards against a marker so generic it fires on real build HTML.

        Measured against the six real pages cached on Legion before these
        markers were chosen; none matched. This keeps that property pinned
        for anyone who adds a marker later.
        """
        big = "<html>" + ("<span>cloudflare cdn asset ray</span>" * 5000) + "</html>"
        scraper = self._scraper(big.encode("utf-8"))
        self.assertEqual(scraper.fetch("x", cache_key="big"), big)
        self.assertEqual(self._stamp(scraper, "big")["status"], "ok")


class TestBotWallDoesNotDestroyTheCache(_ScraperTestCase):
    """A + B - the row's filed acceptance."""

    def test_bot_wall_200_leaves_the_previous_page_untouched(self):
        scraper = self._scraper(_BOT_WALL)
        path = self._seed_cache(scraper, "annie_sr")
        before = path.read_bytes()
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertEqual(path.read_bytes(), before)

    def test_bot_wall_200_stamps_a_non_ok_status(self):
        scraper = self._scraper(_BOT_WALL)
        self._seed_cache(scraper, "annie_sr")
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        entry = self._stamp(scraper, "annie_sr")
        self.assertNotEqual(entry["status"], "ok")
        self.assertIn("bot_wall", entry["status"])

    def test_bot_wall_leaves_no_temp_file_behind(self):
        """`_atomic_write_text` writes `<name>.html.tmp` then replaces.

        A rejection that still wrote the temp file would leave a bot wall on
        disk beside the good page for the next reader to find.
        """
        scraper = self._scraper(_BOT_WALL)
        self._seed_cache(scraper, "annie_sr")
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertEqual(list(scraper._cache_dir.glob("*.tmp")), [])

    def test_bot_wall_with_no_previous_cache_writes_no_cache_at_all(self):
        scraper = self._scraper(_BOT_WALL)
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertFalse(scraper.cache_path("annie_sr").exists())

    def test_the_raise_is_a_runtimeerror_subclass_for_the_orchestrator(self):
        """B - `orchestrator.py:149` / `:162` catch RuntimeError, not Exception."""
        scraper = self._scraper(_BOT_WALL)
        with self.assertRaises(scrapers_base.UnacceptableBody) as ctx:
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertIsInstance(ctx.exception, RuntimeError)

    def test_every_marker_is_rejected(self):
        for marker in scrapers_base.BOT_WALL_MARKERS:
            with self.subTest(marker=marker):
                body = ("<html><head>" + marker + "</head><body>" + "x" * 4000
                        + "</body></html>").encode("utf-8")
                scraper = self._scraper(body)
                path = self._seed_cache(scraper, "annie_sr")
                with self.assertRaises(RuntimeError):
                    scraper.fetch("lol/annie/build/", cache_key="annie_sr")
                self.assertEqual(path.read_text(encoding="utf-8"), _PREVIOUS_GOOD)

    def test_a_short_bot_wall_is_diagnosed_as_a_bot_wall_not_a_truncation(self):
        """Pins marker-before-floor ordering.

        The row's own filed example is 44 bytes, so both predicates are true
        of it. The stamped token is a diagnosis a health probe reads, and
        "bot_wall" is actionable where "too_short" is not.
        """
        self.assertLess(len(_BOT_WALL), scrapers_base.MIN_BODY_BYTES)
        scraper = self._scraper(_BOT_WALL)
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertEqual(self._stamp(scraper, "annie_sr")["status"], "bot_wall")

    def test_marker_matching_is_case_insensitive(self):
        """The body is padded PAST the length floor on purpose.

        Written first without the padding, this test passed against a
        case-SENSITIVE matcher: the 44-byte example tripped the length floor
        instead, so the assertion proved nothing about casing. Caught by
        mutation-testing the matcher, which is the only reason it is padded.
        """
        body = ("<html><title>JUST A MOMENT...</title><body>" + "x" * 4000
                + "</body></html>").encode("utf-8")
        self.assertGreater(len(body), scrapers_base.MIN_BODY_BYTES)
        scraper = self._scraper(body)
        path = self._seed_cache(scraper, "annie_sr")
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertEqual(path.read_text(encoding="utf-8"), _PREVIOUS_GOOD)
        self.assertEqual(self._stamp(scraper, "annie_sr")["status"], "bot_wall")


class TestTruncatedAndEmptyBodies(_ScraperTestCase):
    """The other way a 200 is not the document that was asked for."""

    def test_an_empty_200_body_is_rejected_and_the_cache_survives(self):
        scraper = self._scraper(b"")
        path = self._seed_cache(scraper, "annie_sr")
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertEqual(path.read_text(encoding="utf-8"), _PREVIOUS_GOOD)
        self.assertIn("too_short", self._stamp(scraper, "annie_sr")["status"])

    def test_a_body_under_the_floor_is_rejected(self):
        scraper = self._scraper(b"<html>nope</html>")
        path = self._seed_cache(scraper, "annie_sr")
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertEqual(path.read_text(encoding="utf-8"), _PREVIOUS_GOOD)

    def test_a_body_exactly_at_the_floor_is_accepted(self):
        """Pins the boundary so the floor cannot drift into rejecting real data."""
        body = ("<html>" + "y" * (scrapers_base.MIN_BODY_BYTES - 13) + "</html>")
        self.assertEqual(len(body.encode("utf-8")), scrapers_base.MIN_BODY_BYTES)
        scraper = self._scraper(body.encode("utf-8"))
        self.assertEqual(scraper.fetch("x", cache_key="edge"), body)
        self.assertEqual(self._stamp(scraper, "edge")["status"], "ok")


class TestHttpErrorPathIsUnchanged(_ScraperTestCase):
    """Characterization - the pre-existing >=400 gate keeps its behaviour."""

    def test_a_500_still_stamps_http_500_and_leaves_the_cache(self):
        scraper = self._scraper(_GOOD_HTML.encode("utf-8"), status=500)
        path = self._seed_cache(scraper, "annie_sr")
        with self.assertRaises(RuntimeError):
            scraper.fetch("lol/annie/build/", cache_key="annie_sr")
        self.assertEqual(path.read_text(encoding="utf-8"), _PREVIOUS_GOOD)
        self.assertEqual(self._stamp(scraper, "annie_sr")["status"], "http_500")


class TestBothShippedSubclassesInheritTheGuard(_ScraperTestCase):
    """D - the guard is in the base, so neither subclass can miss it."""

    def test_site_d_and_site_b_both_reject_a_bot_wall(self):
        for cls in (SiteDScraper, SiteBScraper):
            with self.subTest(scraper=cls.__name__):
                scraper = self._scraper(_BOT_WALL, cls=cls)
                path = self._seed_cache(scraper, "annie_sr")
                with self.assertRaises(RuntimeError):
                    scraper.fetch_champion("annie", mode="sr")
                self.assertEqual(path.read_text(encoding="utf-8"), _PREVIOUS_GOOD)


if __name__ == "__main__":
    unittest.main()
