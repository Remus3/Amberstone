"""Tests for dashboard/routes_ds_matchup.py - DS 1v1 matchup wire.

Sibling of test_routes_ds_profile.py; mirrors its StubHandler pattern. The
route is a thin read-only wire over the EXISTING 1v1 matchup engine (POST
/v2/matchup on the DS server), surfaced through the already-shipped
core.daemon_slayer_client.matchup client. These tests pin the HTTP contract:
param validation, payload shape, computed-field relationships, numeric key
resolution, engine-down + malformed branches, mode normalization, cache.

Hermetic: core.daemon_slayer_client.matchup is monkeypatched to a canned
dict - NO live :8893 dependency. Assertions are STRUCTURAL (types / shape /
enums / computed-quantity relationships) rather than brittle exact magnitudes,
per the project rule preferring assertions on computed quantities.

Covers:
  * RouteContractTests - missing champ_a 400, missing champ_b 400, blank 400,
    json content type.
  * ContentTests       - ok top-level keys, verdict passthrough, swing_pct
    bounds, favored consistent with net_swing band, malformed -> no_matchup.
  * ParamTests         - numeric champ key -> slug, mode uppercased.
  * EngineTests        - None -> 503.
  * CacheTests         - TTL hit (cached flag), both champs part of key.
  * AsciiHygieneTests  - no em-dashes / smart quotes in route + test file.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from core import daemon_slayer_client
from dashboard import routes_ds_matchup as rt


def _canned(**over) -> dict:
    """A representative MatchupResult dict; override any field per-test."""
    base = {
        "verdict": "trade",
        "net_swing": 0.2,
        "pct_a_removed": 0.35,
        "pct_b_removed": 0.55,
        "dmg_a_to_b": 412.7,
        "dmg_b_to_a": 268.3,
        "a_can_full_combo": True,
        "b_can_full_combo": False,
        "a_casts_allowed": 3,
        "b_casts_allowed": 2,
        "champ_a": "Vayne",
        "champ_b": "Lux",
        "level_a": 1,
        "level_b": 1,
        "notes": ["mana-gated"],
    }
    base.update(over)
    return base


class StubHandler:
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
    rt._serve_ds_matchup(h)
    return h


class _Base(unittest.TestCase):
    """Resets the response cache and installs a canned matchup() stub so no
    test reaches the live :8893 engine."""

    def setUp(self) -> None:
        rt._reset_caches()
        self._orig = daemon_slayer_client.matchup
        daemon_slayer_client.matchup = self._stub_matchup

    def tearDown(self) -> None:
        daemon_slayer_client.matchup = self._orig

    def _stub_matchup(self, champ_a, champ_b, **kwargs):
        # Echo the resolved slugs so resolution can be asserted.
        return _canned(champ_a=champ_a, champ_b=champ_b)


class RouteContractTests(_Base):
    def test_missing_champ_a_returns_400(self) -> None:
        h = _do("/api/ds-matchup?champ_b=Lux")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_missing_champ_b_returns_400(self) -> None:
        h = _do("/api/ds-matchup?champ_a=Vayne")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champ_returns_400(self) -> None:
        h = _do("/api/ds-matchup?champ_a=&champ_b=Lux")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_response_is_json(self) -> None:
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_ok_payload_top_level(self) -> None:
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["champ_a"], "Vayne")
        self.assertEqual(body["champ_b"], "Lux")
        self.assertEqual(body["mode"], "SR")
        for key in ("ok", "champ_a", "champ_b", "level_a", "level_b", "mode",
                    "verdict", "net_swing", "swing_pct", "favored",
                    "pct_a_removed", "pct_b_removed", "dmg_a_to_b",
                    "dmg_b_to_a", "a_can_full_combo", "b_can_full_combo",
                    "notes", "elapsed_ms", "cached"):
            self.assertIn(key, body)

    def test_verdict_passthrough(self) -> None:
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        self.assertEqual(h.parsed()["verdict"], "trade")

    def test_field_types(self) -> None:
        body = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux").parsed()
        self.assertIsInstance(body["net_swing"], float)
        self.assertIsInstance(body["swing_pct"], int)
        self.assertIsInstance(body["a_can_full_combo"], bool)
        self.assertIsInstance(body["b_can_full_combo"], bool)
        self.assertIsInstance(body["notes"], list)

    def test_swing_pct_in_bounds(self) -> None:
        body = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux").parsed()
        self.assertGreaterEqual(body["swing_pct"], 0)
        self.assertLessEqual(body["swing_pct"], 100)

    def test_favored_a_when_swing_positive(self) -> None:
        # net_swing 0.2 (>= 0.05) -> A favored.
        body = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux").parsed()
        self.assertEqual(body["favored"], "A")

    def test_favored_consistent_with_net_swing(self) -> None:
        # favored is a pure function of net_swing vs the 0.05 band - verify
        # the computed relationship across the three branches.
        for swing, expect in ((0.4, "A"), (-0.4, "B"), (0.0, "even"),
                              (0.05, "A"), (-0.05, "B")):
            daemon_slayer_client.matchup = (
                lambda a, b, _s=swing, **kw: _canned(
                    champ_a=a, champ_b=b, net_swing=_s))
            rt._reset_caches()
            body = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux").parsed()
            self.assertEqual(body["favored"], expect, f"swing={swing}")

    def test_malformed_result_no_matchup(self) -> None:
        # A dict without a "verdict" key -> ok=false reason=no_matchup, 200.
        daemon_slayer_client.matchup = lambda a, b, **kw: {"junk": 1}
        rt._reset_caches()
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_matchup")
        self.assertEqual(body["champ_a"], "Vayne")
        self.assertEqual(body["champ_b"], "Lux")

    def test_non_dict_result_no_matchup(self) -> None:
        daemon_slayer_client.matchup = lambda a, b, **kw: "not-a-dict"
        rt._reset_caches()
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["reason"], "no_matchup")


class ParamTests(_Base):
    def test_numeric_champ_key_resolves(self) -> None:
        # 67 = Vayne's DDragon key; the route resolves numerics to slug.
        h = _do("/api/ds-matchup?champ_a=67&champ_b=Lux")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["champ_a"], "Vayne")

    def test_mode_uppercased(self) -> None:
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux&mode=aram")
        self.assertEqual(h.parsed()["mode"], "ARAM")

    def test_levels_clamped(self) -> None:
        # Out-of-range levels clamp to [1, 18].
        h = _do(
            "/api/ds-matchup?champ_a=Vayne&champ_b=Lux&level_a=99&level_b=0")
        body = h.parsed()
        self.assertEqual(body["level_a"], 18)
        self.assertEqual(body["level_b"], 1)


class EngineTests(_Base):
    def test_engine_down_returns_503(self) -> None:
        daemon_slayer_client.matchup = lambda a, b, **kw: None
        rt._reset_caches()
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        self.assertEqual(h.last_status, 503)
        self.assertFalse(h.parsed()["ok"])


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        self.assertTrue(h2.parsed()["cached"])

    def test_cache_key_includes_both_champs(self) -> None:
        _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        # Swapping champ_b is a distinct key -> fresh (not cached).
        h = _do("/api/ds-matchup?champ_a=Vayne&champ_b=Ahri")
        self.assertFalse(h.parsed()["cached"])

    def test_cache_key_includes_champ_a(self) -> None:
        _do("/api/ds-matchup?champ_a=Vayne&champ_b=Lux")
        h = _do("/api/ds-matchup?champ_a=Ahri&champ_b=Lux")
        self.assertFalse(h.parsed()["cached"])


class AsciiHygieneTests(unittest.TestCase):
    def _assert_ascii(self, path: pathlib.Path) -> None:
        src = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII in {path.name}: {bad[:5]}")

    def test_route_module_is_ascii(self) -> None:
        self._assert_ascii(pathlib.Path(rt.__file__))

    def test_this_test_file_is_ascii(self) -> None:
        self._assert_ascii(pathlib.Path(__file__))


if __name__ == "__main__":
    unittest.main()
