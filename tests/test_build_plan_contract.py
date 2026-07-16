"""WP-C5 contract tests for dashboard/routes_build_plan.py (/api/build-plan).

The data-contract SEAM: DS (/api/ds-preview + /api/build-order, read-only over
HTTP) -> the core.build_planner module (ReplanLoop) -> the active_match Row1
panel. This file pins:

  1. /api/build-plan returns the EXACT contract keys + the 5-value ``state``
     enum (owned | next | swap | partial | future).
  2. The route COMPOSES the ds-preview ``ranked`` + build-order ``order`` +
     module output - proven by injecting a fake seed at the HTTP boundary
     (the route's ``_seed_fn_factory`` is monkeypatched so no live :8893 / no
     live game is needed) and asserting owned ids land as ``owned`` while
     ranked/order ids flow into the planned tail.
  3. Fail-soft: a blank champion -> ok=false; a seedless boundary -> ok=true
     with an empty live[] (never a 5xx, never a raise).
  4. The route reaches DS ONLY over the seed_fn HTTP boundary - it imports no
     ``agents.daemon_slayer`` symbol (mirrors the build_planner split-brain
     guard) and itself contains no ``compute_target_stats_from_items`` needle
     (live target-stats is routed THROUGH the module, keeping the P1L4 caller
     guard at situational.py + routes_state.py only).

Shape / ordinal assertions only - never a data-fragile exact item-number
ranking (the seed is a fixed fake, so ids are asserted by membership/role).

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from dashboard import routes_build_plan

_ROOT = Path(__file__).resolve().parent.parent

# The 5-value state enum the contract locks (master plan WP-C5, line 220).
_STATES = {"owned", "next", "swap", "partial", "future"}


# --------------------------------------------------------------------------- #
# Test doubles - mirror tests/test_ds_preview_e2e_p1l21.py:108 (_Handler) and
# tests/test_planner_beam_search.py:79 (the {ranked[], order[]} fake seed).
# --------------------------------------------------------------------------- #
class _Handler:
    """Stub HTTP handler capturing ``_send`` - the BaseHTTPRequestHandler
    surface the route touches. ``path``/``headers`` are read by no route here,
    but provided so the handler matches the real shape."""

    def __init__(self, path: str = "/api/build-plan") -> None:
        self.path = path
        self.status = 0
        self.body = b""
        self.content_type = ""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type

    def json(self) -> dict:
        return json.loads(self.body.decode())


# id -> (name, delta_dps, gold, unique_passive_key)
_FAKE_CATALOG = {
    "3031": ("Infinity Edge", 95.0, 3450, ""),
    "6672": ("Kraken Slayer", 85.0, 3000, ""),
    "3072": ("Bloodthirster", 80.0, 3400, ""),
    "3094": ("Rapid Firecannon", 70.0, 2500, "energized"),
    "3036": ("Lord Dominik's", 62.0, 3000, ""),
}

_FAKE_ORDER = [
    {"slot": 1, "item_id": "6672", "item_name": "Kraken Slayer",
     "delta": 85.0, "gold": 3000, "scorer": "dps", "unit": "dps",
     "locked_family": ""},
    {"slot": 2, "item_id": "3031", "item_name": "Infinity Edge",
     "delta": 95.0, "gold": 3450, "scorer": "dps", "unit": "dps",
     "locked_family": ""},
]


def _fake_seed_fn(champion, owned_ids=None, **kw):
    """Deterministic {ranked[], order[], target_stats, scorer} envelope -
    the SAME shape the real seed_fn assembles from /api/ds-preview +
    /api/build-order. Owned ids are filtered out of ranked (mirrors the real
    ds-preview, which the planner also re-filters)."""
    owned = {str(i) for i in (owned_ids or ())}
    ranked = []
    for iid, (name, delta, gold, fam) in _FAKE_CATALOG.items():
        if iid in owned:
            continue
        ranked.append({
            "item_id": iid, "item_name": name,
            "delta_dps": delta, "gold": gold,
            "unique_passive_key": fam,
        })
    ranked.sort(key=lambda r: r["delta_dps"], reverse=True)
    return {
        "ok": True,
        "ranked": ranked,
        "order": list(_FAKE_ORDER),
        "scorer": "dps",
        "target_stats": {"target_armor": 80.0, "target_mr": 40.0,
                         "target_max_hp": 2000.0, "target_bonus_hp": 1200.0,
                         "source": "live-items", "n_enemies": 2},
        "threat": {"summary": "AD-heavy", "ad_threat": 8.0, "ap_threat": 2.0},
        "defensive": [],
    }


def _post(payload: dict, seed_fn=_fake_seed_fn) -> dict:
    """Invoke the route handler with the seed boundary monkeypatched to the
    fake. Returns the decoded JSON response."""
    orig = routes_build_plan._seed_fn_factory
    routes_build_plan._seed_fn_factory = lambda **_kw: seed_fn
    try:
        h = _Handler()
        routes_build_plan._serve_build_plan(h, payload)
        return h.json()
    finally:
        routes_build_plan._seed_fn_factory = orig


# --------------------------------------------------------------------------- #
# Contract shape
# --------------------------------------------------------------------------- #
class ContractShapeTests(unittest.TestCase):
    def test_top_level_keys(self):
        resp = _post({"champion": "Miss Fortune", "items": []})
        for key in ("ok", "live", "meta", "knobs", "plan_meta"):
            self.assertIn(key, resp, f"missing top-level key {key!r}")
        self.assertTrue(resp["ok"])
        self.assertIsInstance(resp["live"], list)
        self.assertIsInstance(resp["meta"], list)

    def test_live_item_fields_and_state_enum(self):
        resp = _post({"champion": "Miss Fortune", "items": []})
        self.assertTrue(resp["live"], "live[] should be non-empty for a seeded plan")
        for row in resp["live"]:
            for key in ("item_id", "item_name", "state", "order_idx",
                        "component_pips"):
                self.assertIn(key, row, f"live row missing {key!r}")
            self.assertIn(row["state"], _STATES,
                          f"state {row['state']!r} not in the locked enum")
            self.assertIsInstance(row["order_idx"], int)
            self.assertIsInstance(row["component_pips"], int)

    def test_knobs_shape(self):
        resp = _post({"champion": "Miss Fortune", "items": [],
                      "knobs": {"armor": 90, "mr": 50, "budget": 8000,
                                "fight_length": 4.0}})
        knobs = resp["knobs"]
        for key in ("armor", "mr", "budget", "fight_length"):
            self.assertIn(key, knobs, f"knobs missing {key!r}")
        # caller-supplied knobs echo back.
        self.assertEqual(knobs["armor"], 90)
        self.assertEqual(knobs["budget"], 8000)

    def test_plan_meta_shape(self):
        resp = _post({"champion": "Miss Fortune", "items": []})
        pm = resp["plan_meta"]
        for key in ("stage", "clock", "scorer", "target_stats"):
            self.assertIn(key, pm, f"plan_meta missing {key!r}")
        # target_stats flows through from the seed envelope (ds-preview).
        self.assertEqual(pm["target_stats"].get("source"), "live-items")
        self.assertEqual(pm["scorer"], "dps")

    def test_meta_alt_fields(self):
        resp = _post({"champion": "Miss Fortune", "items": []})
        for row in resp["meta"]:
            for key in ("item_id", "alt_index", "n_alts"):
                self.assertIn(key, row, f"meta row missing {key!r}")

    def test_counter_hints_key_always_a_list(self):
        # R102: the counter_hints projection is ALWAYS present as a list. With
        # no enemies supplied there is no enemy profile -> honest empty [].
        resp = _post({"champion": "Miss Fortune", "items": []})
        self.assertIn("counter_hints", resp, "missing counter_hints key")
        self.assertIsInstance(resp["counter_hints"], list)
        self.assertEqual(resp["counter_hints"], [])


# --------------------------------------------------------------------------- #
# Composition: ds-preview ranked + build-order order + module output
# --------------------------------------------------------------------------- #
class CompositionTests(unittest.TestCase):
    def test_owned_ids_render_as_owned_state(self):
        # 6672 owned -> appears in live[] with state == owned, as the prefix.
        resp = _post({"champion": "Miss Fortune", "items": ["6672"]})
        owned_rows = [r for r in resp["live"] if r["state"] == "owned"]
        self.assertEqual([r["item_id"] for r in owned_rows], ["6672"],
                         "owned id must be the fixed owned-state prefix")

    def test_ranked_and_order_flow_into_planned_tail(self):
        # With nothing owned, the planned tail (non-owned states) must be
        # drawn from the fake seed's ranked[]/order[] id universe - proving
        # the route composed both DS sources through the module.
        resp = _post({"champion": "Miss Fortune", "items": []})
        planned = [r for r in resp["live"] if r["state"] != "owned"]
        self.assertTrue(planned, "planned tail should be non-empty")
        universe = set(_FAKE_CATALOG)  # ranked ids; order ids are a subset
        for r in planned:
            self.assertIn(r["item_id"], universe,
                          "planned id must originate from ds-preview/build-order")

    def test_exactly_one_next_state(self):
        # The replan loop emits a single next_item_id -> exactly one row is
        # tagged ``next`` when a planned tail exists.
        resp = _post({"champion": "Miss Fortune", "items": []})
        nexts = [r for r in resp["live"] if r["state"] == "next"]
        self.assertEqual(len(nexts), 1, "exactly one next-state row expected")

    def test_order_idx_is_monotone_over_planned_tail(self):
        resp = _post({"champion": "Miss Fortune", "items": []})
        planned = [r for r in resp["live"] if r["state"] != "owned"]
        idxs = [r["order_idx"] for r in planned]
        self.assertEqual(idxs, sorted(idxs),
                         "planned order_idx must be non-decreasing")


# --------------------------------------------------------------------------- #
# Fail-soft
# --------------------------------------------------------------------------- #
class FailSoftTests(unittest.TestCase):
    def test_blank_champion_is_ok_false_not_5xx(self):
        h = _Handler()
        routes_build_plan._serve_build_plan(h, {"champion": ""})
        self.assertEqual(h.status, 200)
        self.assertFalse(h.json()["ok"])

    def test_seedless_boundary_yields_empty_live(self):
        # seed_fn returns None (DS unreachable) -> ok=true, empty live[],
        # never a raise.
        resp = _post({"champion": "Miss Fortune", "items": []},
                     seed_fn=lambda *a, **k: None)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["live"], [])

    def test_seed_fn_raise_is_swallowed(self):
        def boom(*a, **k):
            raise RuntimeError("boundary down")

        resp = _post({"champion": "Miss Fortune", "items": []}, seed_fn=boom)
        self.assertTrue(resp["ok"])
        self.assertIsInstance(resp["live"], list)


# --------------------------------------------------------------------------- #
# Structural guards - split-brain + P1L4 caller-needle isolation
# --------------------------------------------------------------------------- #
class StructuralGuardTests(unittest.TestCase):
    _SRC = _ROOT / "dashboard" / "routes_build_plan.py"

    def test_route_imports_no_in_process_engine(self):
        tree = ast.parse(self._SRC.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [n.name for n in node.names
                              if n.name.startswith("agents.daemon_slayer")]
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("agents.daemon_slayer"):
                    offenders.append(node.module)
        self.assertEqual(offenders, [], f"in-process engine import: {offenders!r}")

    def test_route_does_not_call_target_stats_from_items(self):
        # Live target-stats is routed THROUGH the module (situational /
        # ds-preview), so the route itself does NOT contain the P1L4 needle -
        # keeping the guard's expected caller list to situational.py +
        # routes_state.py only.
        needle = "compute_target_stats" + "_from_items("
        self.assertNotIn(needle, self._SRC.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# R103 enemy_items enrichment - counter_hints ONLY; the DS-scored plan stays
# byte-identical whether or not enemy_items is present (the champion-only
# profile that feeds loop.tick is never enriched). All ids VERIFIED present in
# data/meta/ddragon_items.json (3075 Thornmail armor, 3036 Lord Dominik's +
# 6694 Serylda's pct-armor-pen). These call the REAL situational profile
# builder (the seed_fn fake only stubs the DS half).
# --------------------------------------------------------------------------- #
class EnemyItemsCounterHintTests(unittest.TestCase):
    def test_enemy_items_do_not_move_the_ds_plan(self):
        # enemies=[Garen] makes the champion-only profile non-None so
        # situational_fit engages IDENTICALLY with and without enemy_items -
        # live[]/meta[] must be byte-identical; only counter_hints reacts.
        base = {"champion": "Miss Fortune", "items": ["3075"],
                "enemies": ["Garen"]}
        resp_a = _post(dict(base))
        resp_b = _post({**base, "enemy_items": [["3036", "6694"]]})
        # ENGINE INVARIANCE - the DS plan is untouched by enemy_items.
        self.assertEqual(resp_a["live"], resp_b["live"])
        self.assertEqual(resp_a["meta"], resp_b["meta"])
        # The enemy pen items add the C4 hp_vs_pen chip the no-items response
        # lacks - proving the enrichment reached counter_hints and nothing else.
        crit_a = {h["criterion"] for h in resp_a["counter_hints"]}
        crit_b = {h["criterion"] for h in resp_b["counter_hints"]}
        self.assertNotIn("hp_vs_pen", crit_a)
        self.assertIn("hp_vs_pen", crit_b)
        self.assertTrue(resp_b["counter_hints"])

    def test_enemy_items_surface_positive_counter_hint(self):
        # Enemy stacks penetration + we own a resist -> a hp_vs_pen (C4) chip;
        # the chips are plain dicts carrying the ``criterion`` field.
        resp = _post({"champion": "Miss Fortune", "items": ["3075"],
                      "enemies": ["Garen"],
                      "enemy_items": [["3036", "6694"]]})
        self.assertTrue(resp["ok"])
        crits = {h["criterion"] for h in resp["counter_hints"]}
        self.assertIn("hp_vs_pen", crits)


class CounterHintAntihealTests(unittest.TestCase):
    """C2 antiheal (2026-07-16): heal_sources (enemy comp + items) + AllyState
    de-dup, populated on the HINT profile ONLY - the DS plan stays untouched."""

    _HEALERS = ["Soraka", "Aatrox", "Ashe"]   # Soraka + Aatrox curated -> 2 sources

    def test_healer_comp_fires_antiheal_chip(self):
        resp = _post({"champion": "Miss Fortune", "items": [],
                      "enemies": self._HEALERS})
        crits = {h["criterion"] for h in resp["counter_hints"]}
        self.assertIn("antiheal", crits)

    def test_ally_antiheal_suppresses_chip(self):
        # Ally owns Thornmail (3075, applies Grievous) -> the chip de-dupes away.
        resp = _post({"champion": "Miss Fortune", "items": [],
                      "enemies": self._HEALERS, "ally_items": ["3075"]})
        crits = {h["criterion"] for h in resp["counter_hints"]}
        self.assertNotIn("antiheal", crits)

    def test_lone_healer_does_not_fire(self):
        # 1 curated sustain champ = 1 source < HEAL_THRESHOLD (2) - literal count.
        resp = _post({"champion": "Miss Fortune", "items": [],
                      "enemies": ["Soraka", "Ashe", "Jinx"]})
        crits = {h["criterion"] for h in resp["counter_hints"]}
        self.assertNotIn("antiheal", crits)

    def test_ally_items_do_not_move_the_ds_plan(self):
        # ally_items only feed the AllyState de-dup -> live[]/meta[] byte-identical.
        base = {"champion": "Miss Fortune", "items": [], "enemies": self._HEALERS}
        resp_a = _post(dict(base))
        resp_b = _post({**base, "ally_items": ["3075"]})
        self.assertEqual(resp_a["live"], resp_b["live"])
        self.assertEqual(resp_a["meta"], resp_b["meta"])
        # Only the antiheal chip reacts: present without an ally counter, gone with.
        self.assertIn("antiheal", {h["criterion"] for h in resp_a["counter_hints"]})
        self.assertNotIn("antiheal", {h["criterion"] for h in resp_b["counter_hints"]})


if __name__ == "__main__":
    unittest.main()
