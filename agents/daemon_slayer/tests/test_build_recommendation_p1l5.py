"""P1-L5 regression hardening - the build RECOMMENDATION layer driven by
the REAL DS scorers against the REAL Meraki snapshot (2026-05-19).

Audit finding: the build recommendation layer (``core.build_order.
plan_build_order`` + ``rank_for_primary_archetype`` routing + the six
per-archetype scorers) is correct. Existing coverage
(``tests/test_build_order*.py``) exercises the planner ORCHESTRATION
with a hand-written fake engine. NOTHING drove ``plan_build_order``
through the real ``rank_items*`` scorers on the real ``DataSnapshot``.

This file closes that gap with INVARIANT / PROPERTY assertions (no
hardcoded magic numbers, no fragile cross-item comparison asserts -
every assertion is on a computed quantity or a structural invariant):

  1. Build sanity invariants per archetype (carry/tank/bruiser/mage/
     assassin/enchanter): no duplicate items, no two same-unique-passive-
     family items, no recommended component whose completed item is also
     present, stable order for identical input, item count bounded by
     the slot budget.
  2. Phase coherence: the level axis is honored (a recommendation is
     produced at level 1 and level 18), and the planner never emits a
     component whose completed item is also in the build even when
     ``include_components`` is forced on through the ``rank_kwargs``
     splat (the only reachable way that double could occur).
  3. Scorer<->build_order contract: each archetype reaches its scorer
     (carry->dps, tank->ehp, bruiser->hybrid, mage->ability,
     assassin->burst, enchanter->hps) with NO fallback, and the
     planner's slot-1 pick is exactly the engine's top legal candidate
     (the scorer's #1 is never silently dropped).

The adapter below is the in-process equivalent of
``core.daemon_slayer_client.rank_for_primary_archetype`` - same routing
table, same response envelope - so the planner is exercised against the
genuine engine math with no live :8893 server.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.ability_dps import rank_items_by_ability_dps
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.hps import rank_items_by_hps
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.rank import rank_items
from core.build_order import plan_build_order

# (champion, archetype, expected_scorer) - one representative champion
# per archetype branch of rank_for_primary_archetype. Champions chosen
# from the scorer-coverage lists in agents/daemon_slayer/__init__.py.
_ARCH_CASES = [
    ("Jinx", "carry", "dps"),
    ("Malphite", "tank", "ehp"),
    ("Garen", "bruiser", "hybrid"),
    ("Lux", "mage", "ability"),
    ("Zed", "assassin", "burst"),
    ("Soraka", "enchanter", "hps"),
]

# Default match context used across the structural-invariant tests. Mid
# enemy resists / hp so every scorer's value function is exercised
# non-trivially. Values are arbitrary-but-fixed test context, not engine
# constants - no correctness claim rides on the exact numbers.
_CTX = dict(
    target_armor=80.0,
    target_mr=40.0,
    target_max_hp=2000.0,
    target_bonus_hp=500.0,
)


def _make_adapter(snapshot: DataSnapshot):
    """Return a ``rank_fn`` mirroring ``rank_for_primary_archetype``.

    Same routing table + same response envelope (``ok`` / ``scorer`` /
    ``archetype`` / ``fell_back`` / ``ranked`` with the per-row
    unique-passive fields) so ``plan_build_order`` runs against the real
    scorer math headlessly.
    """

    def adapter(champion, archetype, **kw):
        arch = (archetype or "").strip().lower()
        common = dict(
            level=kw["level"],
            current_item_ids=kw.get("item_ids") or [],
            mode=kw.get("mode", "SR"),
            top_n=kw.get("top", 8),
            sort_by=kw.get("sort_by", "delta"),
            filter_shared_uniques=kw.get("filter_shared_uniques", True),
        )
        if "include_components" in kw:
            common["include_components"] = kw["include_components"]
        dmg = dict(
            target_armor=kw.get("target_armor", 0.0),
            target_mr=kw.get("target_mr", 0.0),
            target_max_hp=kw.get("target_max_hp", 0.0),
            target_bonus_hp=kw.get("target_bonus_hp", 0.0),
        )
        if arch == "tank":
            r = rank_items_by_ehp(snapshot, champion, **common)
            scorer = "ehp"
            delta = lambda x: x.delta_ehp
        elif arch == "bruiser":
            r = rank_items_by_hybrid(snapshot, champion, **dmg, **common)
            scorer = "hybrid"
            delta = lambda x: x.hybrid_delta_pct
        elif arch == "mage":
            r = rank_items_by_ability_dps(snapshot, champion, **dmg, **common)
            scorer = "ability"
            delta = lambda x: x.delta_ability_dps
        elif arch == "assassin":
            r = rank_items_by_burst(snapshot, champion, **dmg, **common)
            scorer = "burst"
            delta = lambda x: x.delta_burst
        elif arch == "enchanter":
            r = rank_items_by_hps(snapshot, champion, **common)
            scorer = "hps"
            delta = lambda x: x.delta_hps
        else:
            r = rank_items(snapshot, champion, **common)
            scorer = "dps"
            delta = lambda x: x.delta_dps
        return {
            "ok": True,
            "scorer": scorer,
            "archetype": arch,
            "fell_back": False,
            "ranked": [
                {
                    "item_id": x.item_id,
                    "item_name": x.item_name,
                    "delta": delta(x),
                    "gold": x.gold,
                    "shares_dead_unique": x.shares_dead_unique,
                    "dead_unique_key": x.dead_unique_key,
                    "unique_passive_key": x.unique_passive_key,
                }
                for x in r.ranked
            ],
        }

    return adapter


class _RealEngineBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        # staticmethod: a plain function stored as a class attribute would
        # bind `self` as its first positional arg when read via
        # ``self.adapter`` - corrupting the ``champion`` parameter.
        cls.adapter = staticmethod(_make_adapter(cls.snap))

    # --- shared helpers (all derive facts from the snapshot, no magic) --

    def _family_of(self, item_id: str) -> str:
        eff = ITEM_EFFECTS.get(str(item_id))
        return getattr(eff, "unique_passive_key", "") if eff is not None else ""

    def _builds_into(self, comp_id: str, target_id: str) -> bool:
        """True iff ``comp_id`` is a direct recipe component of
        ``target_id`` per the snapshot's ``from`` list."""
        rec = self.snap.items.get(str(target_id)) or {}
        return str(comp_id) in [str(x) for x in (rec.get("from") or [])]

    def _plan(self, champ, arch, **over):
        kw = dict(
            level=11, owned_item_ids=[], mode="SR", slots=6,
            rank_fn=self.adapter, **_CTX,
        )
        kw.update(over)
        return plan_build_order(champ, arch, **kw)


class BuildSanityInvariantTests(_RealEngineBase):
    """Sub-area 1 - per-archetype structural invariants on the real
    engine output."""

    def test_no_duplicate_items_any_archetype(self):
        for champ, arch, _ in _ARCH_CASES:
            res = self._plan(champ, arch)
            self.assertIsNotNone(res, f"{champ}/{arch} planned None")
            ids = [s.item_id for s in res.order]
            self.assertEqual(
                len(ids), len(set(ids)),
                f"{champ}/{arch}: duplicate item in planned build {ids}",
            )

    def test_no_two_items_share_a_unique_passive_family(self):
        for champ, arch, _ in _ARCH_CASES:
            res = self._plan(champ, arch)
            fams = [
                self._family_of(s.item_id)
                for s in res.order
                if self._family_of(s.item_id)
            ]
            self.assertEqual(
                len(fams), len(set(fams)),
                f"{champ}/{arch}: two items share a unique-passive family "
                f"{fams} in {[s.item_name for s in res.order]}",
            )
            self.assertTrue(
                res.unique_passive_safe,
                f"{champ}/{arch}: unique_passive_safe is False",
            )

    def test_no_component_whose_completed_item_is_also_present(self):
        # Default planner path (include_components not passed) -> the
        # ranker's terminal-only filter already excludes components, so
        # no (component, its completed item) pair can co-exist.
        for champ, arch, _ in _ARCH_CASES:
            res = self._plan(champ, arch)
            ids = [s.item_id for s in res.order]
            offenders = [
                (a, b)
                for a in ids
                for b in ids
                if a != b and self._builds_into(a, b)
            ]
            self.assertEqual(
                offenders, [],
                f"{champ}/{arch}: component+completed both recommended: "
                f"{offenders}",
            )

    def test_stable_order_for_identical_input(self):
        for champ, arch, _ in _ARCH_CASES:
            runs = [
                tuple(s.item_id for s in self._plan(champ, arch).order)
                for _ in range(3)
            ]
            self.assertEqual(
                len(set(runs)), 1,
                f"{champ}/{arch}: nondeterministic order across runs: "
                f"{runs}",
            )

    def test_item_count_bounded_by_slot_budget(self):
        # A full build is at most ``slots`` NEW picks (boots/owned items
        # would reduce, never increase, this). The planner must never
        # exceed the requested slot budget.
        slots = 6
        for champ, arch, _ in _ARCH_CASES:
            res = self._plan(champ, arch, slots=slots)
            self.assertLessEqual(
                len(res.order), slots,
                f"{champ}/{arch}: {len(res.order)} picks > slot budget "
                f"{slots}",
            )
            self.assertGreater(
                len(res.order), 0,
                f"{champ}/{arch}: degenerate empty build for a valid "
                f"champion",
            )
            # slot numbers are a contiguous 1..n run
            self.assertEqual(
                [s.slot for s in res.order],
                list(range(1, len(res.order) + 1)),
                f"{champ}/{arch}: slot numbering not contiguous",
            )

    def test_owned_items_excluded_and_never_repicked(self):
        # Own two unrelated terminal items; the planner must not re-pick
        # them and must reduce the remaining slot count accordingly.
        owned = ["3031", "3036"]  # Infinity Edge, Lord Dominik's (carry)
        res = self._plan("Jinx", "carry", owned_item_ids=owned, slots=6)
        ids = [s.item_id for s in res.order]
        for o in owned:
            self.assertNotIn(o, ids, f"owned {o} re-picked")
        self.assertLessEqual(len(res.order), 6 - len(owned))


class PhaseCoherenceTests(_RealEngineBase):
    """Sub-area 2 - level axis honored + the only reachable
    component/completed double is still prevented."""

    def test_level_axis_produces_a_build_at_min_and_max_level(self):
        for champ, arch, _ in _ARCH_CASES:
            r1 = self._plan(champ, arch, level=1)
            r18 = self._plan(champ, arch, level=18)
            self.assertTrue(
                r1 and r1.order,
                f"{champ}/{arch}: empty build at level 1",
            )
            self.assertTrue(
                r18 and r18.order,
                f"{champ}/{arch}: empty build at level 18",
            )
            self.assertEqual(r1.level, 1)
            self.assertEqual(r18.level, 18)

    def test_no_component_completed_double_even_with_components_forced(self):
        # include_components=True is the ONLY reachable path that could
        # produce a (component, its completed item) pair. Forced on via
        # the rank_kwargs splat - the planned build must still be free of
        # any such pair (the scorer's value function makes completed
        # items dominate, so a component never out-ranks its upgrade).
        for champ, arch, _ in _ARCH_CASES:
            res = self._plan(
                champ, arch,
                rank_kwargs={"include_components": True},
            )
            self.assertIsNotNone(res)
            ids = [s.item_id for s in res.order]
            offenders = [
                (a, b)
                for a in ids
                for b in ids
                if a != b and self._builds_into(a, b)
            ]
            self.assertEqual(
                offenders, [],
                f"{champ}/{arch}: include_components -> component+"
                f"completed both in build: {offenders}",
            )
            # family rule must still hold on the components path
            fams = [
                self._family_of(i) for i in ids if self._family_of(i)
            ]
            self.assertEqual(len(fams), len(set(fams)))

    def test_rank_kwargs_cannot_disable_the_no_double_rule(self):
        # A caller passing filter_shared_uniques=False through rank_kwargs
        # must not defeat the hard rule - the planner force-sets it True.
        for champ, arch, _ in _ARCH_CASES:
            res = self._plan(
                champ, arch,
                rank_kwargs={"filter_shared_uniques": False},
            )
            fams = [
                self._family_of(s.item_id)
                for s in res.order
                if self._family_of(s.item_id)
            ]
            self.assertEqual(
                len(fams), len(set(fams)),
                f"{champ}/{arch}: family doubled when caller passed "
                f"filter_shared_uniques=False",
            )
            self.assertTrue(res.unique_passive_safe)


class ScorerContractTests(_RealEngineBase):
    """Sub-area 3 - routing has no fallback + the scorer's #1 pick is
    never silently dropped by the planner."""

    def test_each_archetype_reaches_its_scorer_no_fallback(self):
        for champ, arch, expected_scorer in _ARCH_CASES:
            res = self._plan(champ, arch, slots=3)
            self.assertIsNotNone(res, f"{champ}/{arch} -> None")
            self.assertEqual(
                res.scorer, expected_scorer,
                f"{champ}/{arch}: routed to {res.scorer!r}, expected "
                f"{expected_scorer!r}",
            )
            # every engine-picked BuildStep records the same routed scorer.
            # 2026-05-23 (item 164b): boots steps are synthetic post-engine
            # inserts (scorer="boots") - filter them out of this invariant.
            for s in res.order:
                if s.scorer == "boots":
                    continue
                self.assertEqual(s.scorer, expected_scorer)

    def test_unknown_archetype_falls_through_to_dps_branch(self):
        # rank_for_primary_archetype routes any unknown label to ds.dps
        # with fell_back=False (settled). The planner must surface that
        # as scorer="dps", not crash or drop the pick.
        res = self._plan("Jinx", "totally-unknown-archetype")
        self.assertIsNotNone(res)
        self.assertEqual(res.scorer, "dps")
        self.assertTrue(res.order)

    def test_slot1_pick_is_engine_top_legal_candidate(self):
        # The planner must not silently drop the scorer's #1. Slot 1 is
        # planned against an empty build, so it must equal the top row
        # the adapter returns for that same call (filter on, so the top
        # row is already the top *legal* candidate).
        for champ, arch, _ in _ARCH_CASES:
            res = self._plan(champ, arch, slots=6)
            out = self.adapter(
                champ, arch, level=11, item_ids=[], mode="SR",
                filter_shared_uniques=True, top=8, sort_by="delta",
                **_CTX,
            )
            top_rows = [r for r in out["ranked"] if r.get("item_id")]
            self.assertTrue(top_rows, f"{champ}/{arch}: engine returned no rows")
            self.assertEqual(
                res.order[0].item_id, str(top_rows[0]["item_id"]),
                f"{champ}/{arch}: slot-1 {res.order[0].item_name!r} != "
                f"engine top {top_rows[0]['item_name']!r} (top pick dropped)",
            )

    def test_planner_consumes_full_engine_envelope_fields(self):
        # Regression: locked_family must reflect the engine-supplied
        # unique_passive_key of the chosen item (Phase 4d contract).
        res = self._plan("Jinx", "carry", slots=6)
        for s in res.order:
            self.assertEqual(
                s.locked_family, self._family_of(s.item_id),
                f"slot {s.slot} ({s.item_name}): locked_family "
                f"{s.locked_family!r} != engine family "
                f"{self._family_of(s.item_id)!r}",
            )


if __name__ == "__main__":
    unittest.main()
