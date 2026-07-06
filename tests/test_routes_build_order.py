"""Headless tests for /api/build-order (2026-05-17).

The route (dashboard/routes_state._serve_build_order_post) wraps
core.build_order.plan_build_order, which iterates the per-archetype DS
scorer. Mock the engine boundary
(core.daemon_slayer_client.rank_for_primary_archetype - what
plan_build_order's default rank_fn imports) so no live DS server is
needed. A family-aware fake proves the unique-passive no-double rule
survives end-to-end through the HTTP route, not just the unit layer.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard.routes_state import _serve_build_order_post


class _Handler:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""
        self.content_type = ""
        self.headers = {}

    def _send(self, status, body, content_type):
        self.status = status
        self.body = body
        self.content_type = content_type

    def json(self) -> dict:
        return json.loads(self.body.decode())


# Family-aware fake engine - mirrors the real rank.py contract: excludes
# owned ids, and with filter_shared_uniques=True omits any candidate whose
# unique-passive family is already in item_ids (rank.py:339).
_CAT = {
    "3078": ("Trinity Force",  60.0, "spellblade"),
    "3508": ("Essence Reaver", 55.0, "spellblade"),
    "3100": ("Lich Bane",      52.0, "spellblade"),
    "3053": ("Sterak's Gage",  40.0, "lifeline"),
    "3156": ("Maw",            38.0, "lifeline"),
    "3071": ("Black Cleaver",  45.0, ""),
    "3074": ("Ravenous Hydra", 50.0, ""),
    "3036": ("Lord Dominik's", 30.0, ""),
}


def _fake_engine(champion, archetype, **kw):
    item_ids = [str(i) for i in (kw.get("item_ids") or [])]
    filt = bool(kw.get("filter_shared_uniques", True))
    fams = {_CAT[i][2] for i in item_ids if i in _CAT and _CAT[i][2]}
    rows = []
    for iid, (name, base, fam) in _CAT.items():
        if iid in item_ids:
            continue
        if fam and fam in fams and filt:
            continue
        rows.append({"item_id": iid, "item_name": name, "delta": base,
                     "gold": 3000, "shares_dead_unique": False,
                     "dead_unique_key": ""})
    rows.sort(key=lambda r: r["delta"], reverse=True)
    return {"ok": True, "scorer": "dps", "archetype": archetype,
            "ranked": rows[: int(kw.get("top", 8) or 8)], "fell_back": False}


class BuildOrderRouteTests(unittest.TestCase):

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                side_effect=_fake_engine)
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_happy_path_returns_ordered_build(self, m_arch, m_rk):
        m_arch.return_value = {"primary": "carry"}
        h = _Handler()
        _serve_build_order_post(h, {"champion": "Ezreal", "mode": "SR",
                                    "level": 13, "slots": 6})
        self.assertEqual(h.status, 200)
        r = h.json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["champion"], "Ezreal")
        self.assertEqual(r["scorer"], "dps")
        self.assertTrue(r["unique_passive_safe"])
        self.assertIsInstance(r["order"], list)
        self.assertGreaterEqual(len(r["order"]), 1)
        self.assertIn("order_str", r)
        self.assertIn("target_stats", r)
        self.assertEqual(r["order"][0]["slot"], 1)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                side_effect=_fake_engine)
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_no_double_unique_passive_through_route(self, m_arch, m_rk):
        m_arch.return_value = {"primary": "carry"}
        h = _Handler()
        _serve_build_order_post(h, {"champion": "Ezreal", "level": 13,
                                    "slots": 6})
        order = h.json()["order"]
        fams = [_CAT[s["item_id"]][2] for s in order if s["item_id"] in _CAT]
        self.assertLessEqual(fams.count("spellblade"), 1)
        self.assertLessEqual(fams.count("lifeline"), 1)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                side_effect=_fake_engine)
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_owned_spellblade_excludes_family(self, m_arch, m_rk):
        m_arch.return_value = {"primary": "carry"}
        h = _Handler()
        _serve_build_order_post(h, {"champion": "Ezreal", "level": 13,
                                    "items": ["3078"], "slots": 6})
        r = h.json()
        self.assertIn("3078", r["owned"])
        for s in r["order"]:
            self.assertNotEqual(_CAT.get(s["item_id"], ("", 0, ""))[2],
                                "spellblade")

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_engine_unavailable_returns_503(self, m_arch, m_rk):
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = None                     # engine down
        h = _Handler()
        _serve_build_order_post(h, {"champion": "Ezreal", "level": 11})
        self.assertEqual(h.status, 503)
        self.assertFalse(h.json()["ok"])

    def test_missing_champion_returns_400(self):
        h = _Handler()
        _serve_build_order_post(h, {"mode": "SR"})
        self.assertEqual(h.status, 400)
        self.assertIn("champion", h.json()["error"])

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                side_effect=_fake_engine)
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_slots_clamped_and_archetype_override(self, m_arch, m_rk):
        # archetype in payload overrides the persisted pick (get_archetype_for
        # must not even be consulted); slots clamps to 1..6.
        h = _Handler()
        _serve_build_order_post(h, {"champion": "Ezreal", "level": 11,
                                    "archetype": "bruiser", "slots": 99})
        r = h.json()
        self.assertEqual(h.status, 200)
        self.assertEqual(r["archetype"], "bruiser")
        self.assertLessEqual(len(r["order"]), 6)
        m_arch.assert_not_called()

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                side_effect=_fake_engine)
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_registered_in_route_table_and_schema(self, m_arch, m_rk):
        from dashboard.routes_state import POST_ROUTES
        from dashboard._dispatch import _REQUEST_MODELS
        paths = [m.__self__.args[0] if hasattr(m, "__self__") else None
                 for m, _ in POST_ROUTES]
        # matcher is equals("/api/build-order"); just assert the handler is wired
        handlers = [fn.__name__ for _, fn in POST_ROUTES]
        self.assertIn("_serve_build_order_post", handlers)
        self.assertIn("/api/build-order", _REQUEST_MODELS)


class IncumbentPassthroughTests(unittest.TestCase):
    """The route forwards the panel's echoed `incumbent` to plan_build_order
    (2026-07-06 incumbent-hysteresis opt-in)."""

    def test_route_forwards_incumbent_to_planner(self):
        captured: dict = {}

        def _capture(champion, archetype, **kw):
            captured.update(kw)
            return None  # the route is fail-soft on a None plan

        with mock.patch("core.build_order.plan_build_order", _capture):
            h = _Handler()
            _serve_build_order_post(h, {
                "champion": "Ezreal", "mode": "SR", "level": 13,
                "items": [], "incumbent": ["3078", "3508"],
            })
        self.assertEqual(captured.get("incumbent"), ["3078", "3508"])

    def test_route_defaults_incumbent_to_empty_when_absent(self):
        captured: dict = {}

        def _capture(champion, archetype, **kw):
            captured.update(kw)
            return None

        with mock.patch("core.build_order.plan_build_order", _capture):
            h = _Handler()
            _serve_build_order_post(h, {
                "champion": "Ezreal", "mode": "SR", "level": 13, "items": [],
            })
        # Absent -> [] -> plan_build_order treats it as no incumbent (byte-identical).
        self.assertEqual(captured.get("incumbent"), [])


if __name__ == "__main__":
    unittest.main()
