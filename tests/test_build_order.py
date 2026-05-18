"""Headless tests for core/build_order.py (2026-05-17).

Proves the contextual, match-specific BUILD-ORDER planner:

  1. Produces a *sequenced* order (not a flat top-N), filling
     ``slots - owned`` positions by greedy forward selection.
  2. Is match-specific - flipping the enemy context reorders the build
     (this is the direct regression for "always the same items").
  3. Enforces the hard no-double rule across the whole sequence: the
     fake engine faithfully reproduces the real ``rank.py`` dedup
     (``filter_shared_uniques`` drops same-unique-passive candidates that
     collide with anything in ``item_ids``). A single flat call returns
     BOTH Trinity Force and Essence Reaver (the bug); the planner's
     iteration yields at most one spellblade item (the fix).
  4. Owned items + engine-down + build-full edge cases match the
     ``dispatch_for_coach`` contract.

No live DS server - ``rank_fn`` is injected with a fake engine.
"""
from __future__ import annotations

import unittest

from core.build_order import (
    BuildOrderResult,
    BuildStep,
    plan_build_order,
)


# --- Fake engine ----------------------------------------------------------
#
# Mirrors the real rank_for_primary_archetype contract closely enough that
# the tests exercise the *planner*, not the fake:
#   - excludes ids already in item_ids (like _filter_candidates)
#   - context-sensitive deltas (armor-pen item rises with target_armor,
#     AP item rises with target_mr) so order depends on the match
#   - unique-passive families; with filter_shared_uniques=True a candidate
#     colliding with a family already in item_ids is OMITTED entirely
#     (exactly rank.py:339 `if shares_dead_unique and filter: continue`);
#     with the filter off it is returned flagged.

_CATALOG = {
    # id: (name, base_delta, family, armor_w, mr_w)
    "3078": ("Trinity Force",  60.0, "spellblade", 0.0, 0.0),
    "3508": ("Essence Reaver", 55.0, "spellblade", 0.0, 0.0),
    "3100": ("Lich Bane",      52.0, "spellblade", 0.0, 0.0),
    "3053": ("Sterak's Gage",  40.0, "lifeline",   0.0, 0.0),
    "3156": ("Maw",            38.0, "lifeline",   0.0, 0.0),
    "3033": ("Mortal Reminder", 30.0, "",          0.6, 0.0),  # armor-pen
    "3036": ("Lord Dominik's",  28.0, "",          0.5, 0.0),  # armor-pen
    "3135": ("Void Staff",      26.0, "",          0.0, 0.7),  # mpen
    "3071": ("Black Cleaver",   45.0, "",          0.0, 0.0),
    "3074": ("Ravenous Hydra",  50.0, "",          0.0, 0.0),
}


class FakeEngine:
    """Records calls + emulates the engine. ``last_filter`` exposes the
    ``filter_shared_uniques`` the planner actually sent (for the override
    test). ``fail_after`` makes it return None from the Nth call on (for
    the mid-sequence-engine-death test). ``hard_down`` → always None."""

    def __init__(self, fail_after: int | None = None, hard_down: bool = False):
        self.calls: list[dict] = []
        self.fail_after = fail_after
        self.hard_down = hard_down

    def __call__(self, champion, archetype, **kw):
        self.calls.append(dict(champion=champion, archetype=archetype, **kw))
        if self.hard_down:
            return None
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            return None

        item_ids = [str(i) for i in (kw.get("item_ids") or [])]
        filt = bool(kw.get("filter_shared_uniques", True))
        armor = float(kw.get("target_armor", 0.0))
        mr = float(kw.get("target_mr", 0.0))

        owned_families = {
            _CATALOG[i][3 - 1] for i in item_ids if i in _CATALOG and _CATALOG[i][3 - 1]
        }
        # (index 3-1 == 2 == family; explicit to mirror the tuple shape)

        rows: list[dict] = []
        for iid, (name, base, family, aw, mw) in _CATALOG.items():
            if iid in item_ids:
                continue
            delta = base + aw * armor + mw * mr
            collides = bool(family and family in owned_families)
            if collides and filt:
                # Real engine drops these from `ranked` entirely.
                continue
            rows.append({
                "item_id": iid,
                "item_name": name,
                "delta": delta,
                "gold": 3000,
                "shares_dead_unique": collides,
                "dead_unique_key": family if collides else "",
            })
        rows.sort(key=lambda r: r["delta"], reverse=True)
        top = int(kw.get("top", 8) or 8)
        return {
            "ok": True,
            "scorer": "dps",
            "archetype": archetype,
            "ranked": rows[:top],
            "fell_back": False,
        }


def _families_in(result: BuildOrderResult) -> list[str]:
    return [_CATALOG[s.item_id][2] for s in result.order if s.item_id in _CATALOG]


# --- Tests ---------------------------------------------------------------

class PlanBasicsTests(unittest.TestCase):
    def test_returns_sequenced_order_of_remaining_slots(self):
        eng = FakeEngine()
        res = plan_build_order(
            "Ezreal", "carry", level=11, owned_item_ids=[],
            mode="SR", slots=6, rank_fn=eng,
        )
        self.assertIsInstance(res, BuildOrderResult)
        self.assertEqual(len(res.order), 6)
        self.assertEqual([s.slot for s in res.order], [1, 2, 3, 4, 5, 6])
        # one engine call per slot - this is a *plan*, not a flat top-N
        self.assertEqual(len(eng.calls), 6)
        for s in res.order:
            self.assertIsInstance(s, BuildStep)

    def test_owned_items_excluded_and_reduce_remaining_slots(self):
        eng = FakeEngine()
        res = plan_build_order(
            "Ezreal", "carry", level=13, owned_item_ids=["3074", "3071"],
            mode="SR", slots=6, rank_fn=eng,
        )
        self.assertEqual(res.owned, ["3074", "3071"])
        self.assertEqual(len(res.order), 4)            # 6 - 2 owned
        picked = {s.item_id for s in res.order}
        self.assertNotIn("3074", picked)
        self.assertNotIn("3071", picked)
        # first slot's call already carries the owned build
        self.assertEqual(eng.calls[0]["item_ids"], ["3074", "3071"])

    def test_accumulation_each_call_carries_prior_picks(self):
        eng = FakeEngine()
        res = plan_build_order(
            "Ezreal", "carry", level=11, owned_item_ids=[], slots=3, rank_fn=eng,
        )
        self.assertEqual(eng.calls[0]["item_ids"], [])
        self.assertEqual(eng.calls[1]["item_ids"], [res.order[0].item_id])
        self.assertEqual(
            eng.calls[2]["item_ids"],
            [res.order[0].item_id, res.order[1].item_id],
        )

    def test_order_str_and_to_dict_shape(self):
        eng = FakeEngine()
        res = plan_build_order("Ezreal", "carry", level=11,
                               owned_item_ids=[], slots=2, rank_fn=eng)
        self.assertRegex(res.order_str(), r".+\(\+\d+dps,3000g\) > .+")
        d = res.to_dict()
        self.assertEqual(d["champion"], "Ezreal")
        self.assertTrue(d["unique_passive_safe"])
        self.assertEqual(len(d["order"]), 2)
        self.assertIn("order_str", d)
        self.assertEqual(d["order"][0]["slot"], 1)


class MatchSpecificityTests(unittest.TestCase):
    """The direct regression for 'always the same items'."""

    def test_enemy_armor_reorders_the_build(self):
        eng = FakeEngine()
        low = plan_build_order("Ezreal", "carry", level=11, owned_item_ids=[],
                               slots=6, target_armor=0.0, target_mr=0.0,
                               rank_fn=eng)
        eng2 = FakeEngine()
        high = plan_build_order("Ezreal", "carry", level=11, owned_item_ids=[],
                                slots=6, target_armor=300.0, target_mr=0.0,
                                rank_fn=eng2)
        low_ids = [s.item_id for s in low.order]
        high_ids = [s.item_id for s in high.order]
        self.assertNotEqual(
            low_ids, high_ids,
            "order must change with enemy armor - else 'always the same items'",
        )
        # armor-pen items climb when the enemy stacks armor
        self.assertLess(high_ids.index("3033"), low_ids.index("3033"))

    def test_enemy_mr_reorders_the_build(self):
        eng = FakeEngine()
        base = plan_build_order("Ezreal", "carry", level=11, owned_item_ids=[],
                                slots=6, target_mr=0.0, rank_fn=eng)
        eng2 = FakeEngine()
        ap = plan_build_order("Ezreal", "carry", level=11, owned_item_ids=[],
                              slots=6, target_mr=400.0, rank_fn=eng2)

        def _rank(res, iid):
            ids = [s.item_id for s in res.order]
            return ids.index(iid) if iid in ids else len(ids)  # absent = last

        # vs no magic, mpen is dead weight and doesn't make the build;
        # vs a 400-MR comp it climbs to the top.
        self.assertEqual(_rank(base, "3135"), len(base.order))   # absent
        self.assertLess(_rank(ap, "3135"), _rank(base, "3135"))
        self.assertLess(_rank(ap, "3135"), 2)                    # near top

    def test_context_recorded_for_provenance(self):
        eng = FakeEngine()
        res = plan_build_order("Ezreal", "carry", level=11, owned_item_ids=[],
                               slots=2, target_armor=120.0, target_mr=55.0,
                               target_max_hp=2400.0, rank_fn=eng)
        self.assertEqual(res.context["target_armor"], 120.0)
        self.assertEqual(res.context["target_mr"], 55.0)
        self.assertEqual(res.context["target_max_hp"], 2400.0)


class UniquePassiveNoDoubleTests(unittest.TestCase):
    """The HARD RULE - no two items sharing a unique passive."""

    def test_flat_call_reproduces_the_bug_planner_must_fix(self):
        # Sanity: a SINGLE engine call with no spellblade owned returns
        # BOTH Trinity Force AND Essence Reaver - exactly the flat-list
        # double-pick the planner exists to prevent.
        eng = FakeEngine()
        out = eng("Ezreal", "carry", level=11, item_ids=[],
                  filter_shared_uniques=True, top=10)
        names = {r["item_name"] for r in out["ranked"]}
        self.assertIn("Trinity Force", names)
        self.assertIn("Essence Reaver", names)

    def test_planner_never_doubles_spellblade(self):
        eng = FakeEngine()
        res = plan_build_order("Ezreal", "carry", level=11, owned_item_ids=[],
                               slots=6, rank_fn=eng)
        fams = _families_in(res)
        self.assertLessEqual(
            fams.count("spellblade"), 1,
            f"two spellblade items in the order: "
            f"{[s.item_name for s in res.order]}",
        )
        self.assertLessEqual(fams.count("lifeline"), 1)
        self.assertTrue(res.unique_passive_safe)

    def test_once_spellblade_picked_family_locked_for_all_later_slots(self):
        eng = FakeEngine()
        res = plan_build_order("Ezreal", "carry", level=11, owned_item_ids=[],
                               slots=6, rank_fn=eng)
        ids = [s.item_id for s in res.order]
        spellblades = [i for i in ids if _CATALOG[i][2] == "spellblade"]
        self.assertEqual(len(spellblades), 1)
        # the one spellblade is the highest-base (Trinity Force) - greedy
        # took it first, then the family was locked
        self.assertEqual(spellblades[0], "3078")

    def test_owned_spellblade_excludes_all_others_from_slot_one(self):
        eng = FakeEngine()
        res = plan_build_order("Ezreal", "carry", level=11,
                               owned_item_ids=["3508"],  # Essence Reaver
                               slots=6, rank_fn=eng)
        ids = [s.item_id for s in res.order]
        for i in ids:
            self.assertNotEqual(_CATALOG[i][2], "spellblade")
        self.assertTrue(res.unique_passive_safe)

    def test_rank_kwargs_cannot_weaken_the_rule(self):
        # A caller trying to pass filter_shared_uniques=False must not be
        # able to defeat the no-double rule.
        eng = FakeEngine()
        res = plan_build_order(
            "Ezreal", "carry", level=11, owned_item_ids=[], slots=6,
            rank_kwargs={"filter_shared_uniques": False}, rank_fn=eng,
        )
        for c in eng.calls:
            self.assertTrue(
                c["filter_shared_uniques"],
                "planner must force filter_shared_uniques=True regardless "
                "of caller rank_kwargs",
            )
        self.assertLessEqual(_families_in(res).count("spellblade"), 1)


class EdgeCaseContractTests(unittest.TestCase):
    def test_engine_down_at_slot_one_returns_none(self):
        eng = FakeEngine(hard_down=True)
        res = plan_build_order("Ezreal", "carry", level=11,
                               owned_item_ids=[], slots=6, rank_fn=eng)
        self.assertIsNone(res)

    def test_engine_dies_mid_sequence_truncates_with_note(self):
        eng = FakeEngine(fail_after=3)   # calls 1,2 ok; 3rd → None
        res = plan_build_order("Ezreal", "carry", level=11,
                               owned_item_ids=[], slots=6, rank_fn=eng)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.order), 2)
        self.assertTrue(any("engine stopped responding" in n for n in res.notes))

    def test_blank_champion_returns_none(self):
        eng = FakeEngine()
        self.assertIsNone(
            plan_build_order("", "carry", level=11, owned_item_ids=[],
                             slots=6, rank_fn=eng)
        )
        self.assertIsNone(
            plan_build_order("   ", "carry", level=11, owned_item_ids=[],
                             slots=6, rank_fn=eng)
        )

    def test_build_already_full_returns_empty_order_not_none(self):
        eng = FakeEngine()
        res = plan_build_order(
            "Ezreal", "carry", level=18,
            owned_item_ids=["3074", "3071", "3033", "3036", "3135", "3053"],
            slots=6, rank_fn=eng,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.order, [])
        self.assertEqual(len(eng.calls), 0)            # nothing to plan
        self.assertTrue(any("already full" in n for n in res.notes))

    def test_engine_empty_ranked_stops_cleanly(self):
        class EmptyEngine(FakeEngine):
            def __call__(self, champion, archetype, **kw):
                self.calls.append({})
                return {"ok": True, "scorer": "dps", "archetype": archetype,
                        "ranked": [], "fell_back": False}
        eng = EmptyEngine()
        res = plan_build_order("Ezreal", "carry", level=11,
                               owned_item_ids=[], slots=6, rank_fn=eng)
        self.assertIsNotNone(res)
        self.assertEqual(res.order, [])
        self.assertTrue(any("no further legal items" in n for n in res.notes))

    def test_archetype_defaults_to_carry_when_blank(self):
        eng = FakeEngine()
        res = plan_build_order("Ezreal", "", level=11, owned_item_ids=[],
                               slots=1, rank_fn=eng)
        self.assertEqual(res.archetype, "carry")
        self.assertEqual(eng.calls[0]["archetype"], "carry")


class ScorerUnitTests(unittest.TestCase):
    def test_unit_follows_scorer(self):
        class HpsEngine(FakeEngine):
            def __call__(self, champion, archetype, **kw):
                self.calls.append({})
                return {
                    "ok": True, "scorer": "hps", "archetype": archetype,
                    "ranked": [{"item_id": "6617", "item_name": "Moonstone",
                                "delta": 25.0, "gold": 2200,
                                "shares_dead_unique": False,
                                "dead_unique_key": ""}],
                    "fell_back": False,
                }
        eng = HpsEngine()
        res = plan_build_order("Soraka", "enchanter", level=11,
                               owned_item_ids=[], slots=1, rank_fn=eng)
        self.assertEqual(res.scorer, "hps")
        self.assertEqual(res.order[0].unit, "hps")
        self.assertIn("hps", res.order_str())


class _Stats:
    """Duck-typed coach_integration.enemy_stats.EnemyStats stub."""
    def __init__(self, armor=80.0, mr=30.0, max_hp=2000.0, bonus_hp=500.0):
        self.armor = armor
        self.mr = mr
        self.max_hp = max_hp
        self.bonus_hp = bonus_hp


def _disp_response():
    return {
        "ok": True, "scorer": "dps", "archetype": "carry",
        "ranked": [
            {"item_id": "3078", "item_name": "Trinity Force", "delta": 60.0,
             "gold": 3333, "shares_dead_unique": False, "dead_unique_key": ""},
            {"item_id": "3074", "item_name": "Ravenous Hydra", "delta": 50.0,
             "gold": 3300, "shares_dead_unique": False, "dead_unique_key": ""},
        ],
        "fell_back": False,
    }


class DispatchIntegrationTests(unittest.TestCase):
    """Opt-in wiring in coach_integration.archetype_dispatch - the
    per-tick path must stay one engine call (build-order is opt-in)."""

    from unittest import mock as _m

    @_m.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @_m.patch("core.archetype_picks.get_archetype_for")
    def test_default_off_no_build_order_single_engine_call(self, m_arch, m_rk):
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _disp_response()
        res = dispatch_for_coach(
            "Ezreal", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIsNotNone(res)
        self.assertIsNone(res.build_order)            # opt-in, default off
        self.assertEqual(m_rk.call_count, 1)          # per-tick: ONE call

    @_m.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @_m.patch("core.archetype_picks.get_archetype_for")
    def test_opt_in_populates_ordered_build(self, m_arch, m_rk):
        from coach_integration.archetype_dispatch import dispatch_for_coach
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _disp_response()
        res = dispatch_for_coach(
            "Ezreal", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(), with_build_order=True, build_order_slots=6,
        )
        self.assertIsNotNone(res)
        self.assertIsInstance(res.build_order, BuildOrderResult)
        # 2-row static mock → planner takes both then stops (picked-id
        # filter drains it); flat dispatch + slot calls > 1.
        self.assertGreater(m_rk.call_count, 1)
        names = [s.item_name for s in res.build_order.order]
        self.assertEqual(names, ["Trinity Force", "Ravenous Hydra"])
        self.assertTrue(res.build_order.unique_passive_safe)
        # legacy consumers untouched
        self.assertTrue(res.picks_str.startswith("Trinity Force"))

    @_m.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @_m.patch("core.archetype_picks.get_archetype_for")
    def test_build_order_failure_does_not_sink_dispatch(self, m_arch, m_rk):
        from coach_integration import archetype_dispatch
        m_arch.return_value = {"primary": "carry"}
        m_rk.return_value = _disp_response()
        with self._m.patch.object(
            archetype_dispatch, "dispatch_for_coach",
            wraps=archetype_dispatch.dispatch_for_coach,
        ):
            with self._m.patch(
                "core.build_order.plan_build_order",
                side_effect=RuntimeError("boom"),
            ):
                res = archetype_dispatch.dispatch_for_coach(
                    "Ezreal", mode_engine="SR", level=11, item_ids=[],
                    enemy_stats=_Stats(), with_build_order=True,
                )
        self.assertIsNotNone(res)            # flat dispatch survives
        self.assertIsNone(res.build_order)   # order failed gracefully
        self.assertTrue(res.picks_str.startswith("Trinity Force"))


if __name__ == "__main__":
    unittest.main()
