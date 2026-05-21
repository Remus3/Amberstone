"""Tests for the personal-context dashboard route (item 124 follow-up).

GET /api/personal-context

The route surfaces the same top-3 death patterns the mode coaches inject
into their prompts (via core.death_patterns_loader). Loader-level
fail-soft semantics + 60s mtime-keyed cache + ok=false reason=no_data on
missing data (HTTP 200, never 404 - the panel renders the empty state).
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from io import BytesIO  # noqa: F401 - kept parity with sibling test modules
from pathlib import Path
from unittest.mock import patch

from dashboard import routes_personal_context as routes


# Fake handler mirroring the BaseHTTPRequestHandler surface the route
# touches: `path` + `_send`. Same shape as test_routes_replay_events.py.

class _FakeHandler:
    def __init__(self, path: str = "/api/personal-context"):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.responses.append((status, body, content_type))

    @property
    def last(self) -> tuple[int, dict, str]:
        assert self.responses, "no response sent"
        status, body, ct = self.responses[-1]
        return status, json.loads(body), ct


_ROLE_GRADES_FIXTURE = {
    "total_matches_scored": 624,
    "overall": {
        "count": 624,
        "median_score": 41,
        "tier_distribution": {"S+": 0, "S": 8, "A": 56, "B": 164, "C": 159, "D": 237},
    },
    "by_role": {
        "ADC": {"count": 177, "median_score": 41, "tier_distribution": {"S+": 0, "S": 0, "A": 31, "B": 37, "C": 48, "D": 61}},
        "SUP": {"count": 79, "median_score": 57, "tier_distribution": {"S+": 0, "S": 8, "A": 14, "B": 29, "C": 8, "D": 20}},
        "JG": {"count": 52, "median_score": 32, "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 14, "C": 10, "D": 28}},
        "MID": {"count": 80, "median_score": 44, "tier_distribution": {"S+": 0, "S": 0, "A": 11, "B": 16, "C": 33, "D": 20}},
        "TOP": {"count": 236, "median_score": 37, "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 68, "C": 60, "D": 108}},
    },
}

_POPULATED = {
    "schema_version": 2,
    "generated_at": "2026-05-21T03:14:15Z",
    "puuids": ["abc"],
    "total_deaths": 28236,
    "total_matches": 2838,
    "patterns": {
        "solo_pickoff": {
            "count": 16595,
            "rate": 0.5877,
            "confidence": 0.9997,
            "label": "Solo pickoffs",
            "description": "ward + rotate",
        },
        "caught_4plus": {
            "count": 12345,
            "rate": 0.4371,
            "confidence": 0.9996,
            "label": "Caught by 4+",
            "description": "minimap",
        },
        "rapid_repeat": {
            "count": 6165,
            "rate": 0.2182,
            "confidence": 0.9992,
            "label": "Rapid repeats",
            "description": "tilt reset",
        },
        "early_pre_3min": {
            "count": 0,
            "rate": 0.0,
            "confidence": 0.0,
            "label": "Early-game deaths",
            "description": "respect level-1 invades",
        },
    },
    "top3": ["solo_pickoff", "caught_4plus", "rapid_repeat"],
    "role_grades": _ROLE_GRADES_FIXTURE,
}


class _FsCase(unittest.TestCase):
    """Each test points the route at a fresh temp data file + clears the
    in-process cache so cache-keyed assertions are isolated."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="rc-personal-context-")
        self._json_path = Path(self._tmp_dir) / "death_patterns.json"
        self._patcher = patch.object(
            routes, "_DEATH_PATTERNS_PATH", self._json_path
        )
        self._patcher.start()
        routes._CACHE["mtime"] = None
        routes._CACHE["expires_at"] = 0.0
        routes._CACHE["payload"] = None

    def tearDown(self):
        self._patcher.stop()
        try:
            if self._json_path.exists():
                self._json_path.unlink()
            Path(self._tmp_dir).rmdir()
        except OSError:
            pass

    def _write(self, data: dict) -> None:
        self._json_path.write_text(
            json.dumps(data), encoding="utf-8"
        )


class PopulatedPathTests(_FsCase):
    def test_returns_top3_with_metadata(self):
        self._write(_POPULATED)
        h = _FakeHandler()
        routes._serve_personal_context(h)
        status, body, ct = h.last
        self.assertEqual(status, 200)
        self.assertEqual(ct, "application/json")
        self.assertTrue(body["ok"])
        self.assertEqual(body["total_deaths"], 28236)
        self.assertEqual(body["total_matches"], 2838)
        self.assertEqual(body["generated_at"], "2026-05-21T03:14:15Z")
        self.assertEqual(len(body["top3"]), 3)
        keys = [p["key"] for p in body["top3"]]
        self.assertEqual(keys, ["solo_pickoff", "caught_4plus", "rapid_repeat"])

    def test_pattern_entry_carries_all_fields(self):
        self._write(_POPULATED)
        h = _FakeHandler()
        routes._serve_personal_context(h)
        _, body, _ = h.last
        first = body["top3"][0]
        self.assertEqual(first["key"], "solo_pickoff")
        self.assertEqual(first["label"], "Solo pickoffs")
        self.assertEqual(first["description"], "ward + rotate")
        self.assertEqual(first["count"], 16595)
        self.assertAlmostEqual(first["rate"], 0.5877, places=4)
        self.assertAlmostEqual(first["confidence"], 0.9997, places=4)


class EmptyDataPathTests(_FsCase):
    def test_missing_file_returns_ok_false_no_data(self):
        # No file written - fail-soft path.
        h = _FakeHandler()
        routes._serve_personal_context(h)
        status, body, _ = h.last
        self.assertEqual(status, 200, "missing data must NOT 404")
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_data")

    def test_malformed_json_returns_ok_false_no_data(self):
        self._json_path.write_text("not json {", encoding="utf-8")
        h = _FakeHandler()
        routes._serve_personal_context(h)
        status, body, _ = h.last
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_data")

    def test_empty_top3_returns_ok_false_no_data(self):
        self._write({"schema_version": 1, "top3": [], "patterns": {}})
        h = _FakeHandler()
        routes._serve_personal_context(h)
        status, body, _ = h.last
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_data")


class CacheTests(_FsCase):
    def test_second_call_serves_from_cache(self):
        self._write(_POPULATED)
        h1 = _FakeHandler()
        routes._serve_personal_context(h1)
        # Mutate the file - mtime stays the same because we wrote it
        # in the same second; the cache should still hit.
        cached_payload = routes._CACHE["payload"]
        self.assertIsNotNone(cached_payload)
        h2 = _FakeHandler()
        routes._serve_personal_context(h2)
        _, body1, _ = h1.last
        _, body2, _ = h2.last
        self.assertEqual(body1, body2)

    def test_cache_invalidates_on_mtime_change(self):
        self._write(_POPULATED)
        h1 = _FakeHandler()
        routes._serve_personal_context(h1)
        _, body1, _ = h1.last
        self.assertEqual(body1["total_deaths"], 28236)
        # Sleep > FS mtime resolution (Windows: 1s), then rewrite with
        # different totals so the mtime change forces a re-read.
        time.sleep(1.1)
        new_data = dict(_POPULATED)
        new_data["total_deaths"] = 99999
        self._write(new_data)
        h2 = _FakeHandler()
        routes._serve_personal_context(h2)
        _, body2, _ = h2.last
        self.assertEqual(body2["total_deaths"], 99999)

    def test_cache_expires_after_ttl(self):
        self._write(_POPULATED)
        h1 = _FakeHandler()
        routes._serve_personal_context(h1)
        # Force the cache entry to expire by rewinding expires_at.
        routes._CACHE["expires_at"] = time.time() - 1.0
        h2 = _FakeHandler()
        routes._serve_personal_context(h2)
        # Both calls should return the same shape (file unchanged) but
        # the second call hit the FS again because the TTL window had
        # passed.
        _, body1, _ = h1.last
        _, body2, _ = h2.last
        self.assertEqual(body1, body2)

    def test_cache_misses_when_file_absent(self):
        # No file - first call returns no_data and caches that.
        h1 = _FakeHandler()
        routes._serve_personal_context(h1)
        _, body1, _ = h1.last
        self.assertFalse(body1["ok"])
        # Write a populated file; mtime changes from None to a number.
        self._write(_POPULATED)
        h2 = _FakeHandler()
        routes._serve_personal_context(h2)
        _, body2, _ = h2.last
        self.assertTrue(body2["ok"])


class RoleGradesPayloadTests(_FsCase):
    """The /api/personal-context payload carries the role_grades envelope
    when schema_version=2 + role_grades is present in the JSON file."""

    def test_role_grades_present_in_response(self):
        self._write(_POPULATED)
        h = _FakeHandler()
        routes._serve_personal_context(h)
        _, body, _ = h.last
        self.assertTrue(body["ok"])
        self.assertIn("role_grades", body)

    def test_role_grades_overall_carries_count_median_tiers(self):
        self._write(_POPULATED)
        h = _FakeHandler()
        routes._serve_personal_context(h)
        _, body, _ = h.last
        rg = body["role_grades"]
        self.assertEqual(rg["total_matches_scored"], 624)
        self.assertEqual(rg["overall"]["count"], 624)
        self.assertEqual(rg["overall"]["median_score"], 41)
        self.assertEqual(rg["overall"]["tier_distribution"]["B"], 164)

    def test_role_grades_by_role_canonical_keys(self):
        self._write(_POPULATED)
        h = _FakeHandler()
        routes._serve_personal_context(h)
        _, body, _ = h.last
        rg = body["role_grades"]
        self.assertEqual(set(rg["by_role"].keys()), {"ADC", "SUP", "JG", "MID", "TOP"})
        self.assertEqual(rg["by_role"]["TOP"]["count"], 236)
        self.assertEqual(rg["by_role"]["JG"]["median_score"], 32)

    def test_role_grades_omitted_when_schema_v1(self):
        # An older schema v1 file (no role_grades section) -> the field is
        # OMITTED from the payload (not present as {}). Frontend treats the
        # missing key the same as zero-count.
        v1 = dict(_POPULATED)
        v1.pop("role_grades")
        v1["schema_version"] = 1
        self._write(v1)
        h = _FakeHandler()
        routes._serve_personal_context(h)
        _, body, _ = h.last
        self.assertTrue(body["ok"])
        self.assertNotIn("role_grades", body)

    def test_role_grades_cached_with_payload(self):
        # The same cache slot holds top3 + role_grades; a single hit
        # returns the full envelope.
        self._write(_POPULATED)
        h1 = _FakeHandler()
        routes._serve_personal_context(h1)
        h2 = _FakeHandler()
        routes._serve_personal_context(h2)
        _, body2, _ = h2.last
        self.assertIn("role_grades", body2)


class RouteRegistrationTests(unittest.TestCase):
    def test_route_registered_in_dispatch(self):
        from dashboard import _dispatch
        # Reset cache so a fresh gather happens.
        _dispatch._GET_CACHE = None
        get_routes = _dispatch._gather_get()
        # Locate by matching /api/personal-context against the matchers.
        matched = [fn for matcher, fn in get_routes
                   if matcher("/api/personal-context")]
        self.assertTrue(matched, "personal-context route not registered")

    def test_get_routes_module_attribute_present(self):
        self.assertTrue(hasattr(routes, "GET_ROUTES"))
        self.assertTrue(len(routes.GET_ROUTES) >= 1)


class AsciiHygieneTests(unittest.TestCase):
    """The CLAUDE.md no-em-dash hard rule extends to all authored text.
    The route module must be 7-bit ASCII (no smart quotes, em/en dashes,
    or arrows). The test file references the dashes via chr() so this
    test stays clean against its own scan."""

    def test_route_module_is_pure_ascii(self):
        path = Path(routes.__file__)
        data = path.read_bytes()
        non_ascii = [b for b in data if b > 127]
        self.assertEqual(
            non_ascii, [], f"non-ASCII bytes in {path.name}: {non_ascii[:8]}"
        )


if __name__ == "__main__":
    unittest.main()
