"""Headless tests for core/build_planner/{scoring,planner}.py (WP-C2).

Proves the adaptive build PLANNER that sits ABOVE Daemon Slayer:

  1. scoring.score_build is PURE + explainable - the DPS term is READ from
     the seed rows' ``delta_dps`` (never recomputed = no split-brain), the
     cohesion term reuses the shipped C1 ``kit_synergy.synergy_score``, and
     every term is surfaced per-build (ScoreTerms) so the planner can show a
     breakdown.
  2. planner.plan_build runs a beam search over ordered partial builds:
     beam returns <= width, depth is respected, builds_evaluated is bounded,
     dedupe-by-set + relative-threshold pruning both fire.
  3. The unique-passive no-double rule is INHERITED from the engine-supplied
     ``unique_passive_key`` on each seed row - no planner-side family map, no
     family LITERAL in the four planning modules (scoring, planner,
     situational, replan; a source scan enforces this over every family the
     engine defines), and no family key as a string constant in ANY
     core/build_planner module (a token-level AST scan with a measured,
     self-checking exemption list).
  4. seed_fn=None yields a seedless (empty) plan, mirroring the
     ``core.build_order.plan_build_order`` None-contract.
  5. No core/build_planner module imports an ``agents.daemon_slayer`` symbol
     (the in-process split-brain guard, mirrored from
     ``TestNoEngineSplitBrain.test_routes_state_has_no_in_process_engine_import``
     in tests/test_ds_preview_e2e_p1l21.py) - DS is reached only over the
     injectable HTTP-boundary seed_fn.

No live HTTP - ``seed_fn`` is injected with a deterministic fake that returns
the same {ranked[], order[]} shape the dashboard routes expose.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from core.build_planner.planner import (
    BuildPlan,
    plan_build,
)
from core.build_planner.scoring import (
    ScoreTerms,
    score_build,
    stage_for,
)

_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Fake seed_fn - mirrors the {ranked[], order[]} shape from
# dashboard/routes_state.py (/api/ds-preview + /api/build-order). Each ranked
# row carries the FULL RankedItem fields the in-process ranker emits
# (``RankedItem`` in agents/daemon_slayer/rank.py) so the planner can exercise
# unique_passive_key inheritance; the row projection in
# ``_serve_ds_preview_post`` (dashboard/routes_state.py) drops some of these,
# so a second fake below returns the THIN projected shape to prove the planner
# tolerates it.
# --------------------------------------------------------------------------- #
# id: (name, delta_dps, gold, unique_passive_key, is_terminal)
_FAKE_CATALOG: dict[str, tuple[str, float, int, str, bool]] = {
    "3031": ("Infinity Edge",       95.0, 3450, "", True),
    "3094": ("Rapid Firecannon",    70.0, 2500, "energized", True),
    "3087": ("Statikk Shiv",        66.0, 2700, "energized", True),
    "3072": ("Bloodthirster",       80.0, 3400, "", True),
    "3036": ("Lord Dominik's",      62.0, 3000, "", True),
    "6672": ("Kraken Slayer",       85.0, 3000, "", True),
    "3046": ("Phantom Dancer",      58.0, 2600, "", True),
    "3033": ("Mortal Reminder",     50.0, 3000, "", True),
}

# A deterministic build-order warm start (BuildStep.to_dict shape).
_FAKE_ORDER: list[dict] = [
    {"slot": 1, "item_id": "6672", "item_name": "Kraken Slayer",
     "delta": 85.0, "gold": 3000, "scorer": "dps", "unit": "dps",
     "locked_family": ""},
    {"slot": 2, "item_id": "3031", "item_name": "Infinity Edge",
     "delta": 95.0, "gold": 3450, "scorer": "dps", "unit": "dps",
     "locked_family": ""},
]


def make_seed_fn(thin: bool = False):
    """Return a deterministic seed_fn(champion, owned_ids, **kw) -> dict.

    ``thin=True`` emulates the /api/ds-preview projection that DROPS
    unique_passive_key / is_terminal / dps_per_1k_gold (routes_state.py
    R3 gap) - the planner must still function (treating missing family as
    no-collision).
    """

    def seed_fn(champion, owned_ids=None, **kw):
        owned = {str(i) for i in (owned_ids or ())}
        ranked: list[dict] = []
        for iid, (name, delta, gold, fam, term) in _FAKE_CATALOG.items():
            if iid in owned:
                continue
            row = {
                "item_id": iid,
                "item_name": name,
                "delta_dps": delta,
                "gold": gold,
            }
            if not thin:
                row["unique_passive_key"] = fam
                row["is_terminal"] = term
                row["dps_per_1k_gold"] = (delta / (gold / 1000.0)) if gold else 0.0
            ranked.append(row)
        ranked.sort(key=lambda r: r["delta_dps"], reverse=True)
        return {"ok": True, "ranked": ranked, "order": list(_FAKE_ORDER)}

    return seed_fn


# A stub champ object - synergy_score resolves the archetype via
# core.archetype_picks for the str name; an unknown name fail-softs to the
# "carry" default vector, which is all these ordinal assertions need.
_CHAMP = "Miss Fortune"


# --------------------------------------------------------------------------- #
# scoring.py
# --------------------------------------------------------------------------- #
class ScoringTests(unittest.TestCase):
    def test_stage_for_shifts_by_clock_and_owned(self):
        early = stage_for(clock_s=300, owned_count=0)
        late = stage_for(clock_s=1800, owned_count=4)
        self.assertNotEqual(early, late)
        # Stages are ordered labels - early precedes late.
        self.assertIn(early, ("early", "mid", "late"))
        self.assertIn(late, ("early", "mid", "late"))

    def test_score_build_returns_scoreterms_with_all_terms(self):
        rows = list(make_seed_fn()(_CHAMP).get("ranked"))
        terms = score_build(
            build_ids=["3031"], champ=_CHAMP, seed_rows=rows,
            clock_s=600, owned_count=0,
        )
        self.assertIsInstance(terms, ScoreTerms)
        # Every weighted term is present + finite (explainability).
        for name in ("dps", "cohesion", "spike", "gold", "situational_fit",
                     "penalties", "total"):
            self.assertTrue(hasattr(terms, name), name)
            self.assertEqual(float(getattr(terms, name)),
                             float(getattr(terms, name)))

    def test_dps_term_reads_seed_delta_not_recomputed(self):
        # The DPS term must be a monotone function of the seed delta_dps sum -
        # a build of two higher-delta rows scores its DPS term above a build
        # of two lower-delta rows. (ordinal, no exact-value compare.)
        rows = list(make_seed_fn()(_CHAMP).get("ranked"))
        hi = score_build(build_ids=["3031", "6672"], champ=_CHAMP,
                         seed_rows=rows, clock_s=600, owned_count=0).dps
        lo = score_build(build_ids=["3046", "3033"], champ=_CHAMP,
                         seed_rows=rows, clock_s=600, owned_count=0).dps
        self.assertGreater(hi, lo)

    def test_situational_fit_is_zero_stub(self):
        rows = list(make_seed_fn()(_CHAMP).get("ranked"))
        terms = score_build(build_ids=["3031"], champ=_CHAMP, seed_rows=rows,
                            clock_s=600, owned_count=0)
        self.assertEqual(terms.situational_fit, 0.0)

    def test_unique_collision_penalizes(self):
        # Two energized items (shared unique_passive_key) carry a strictly
        # larger penalty MAGNITUDE than one energized item alone - penalties is
        # a positive value SUBTRACTED in total, so a worse build has a bigger
        # penalty and a lower total.
        rows = list(make_seed_fn()(_CHAMP).get("ranked"))
        one = score_build(build_ids=["3094"], champ=_CHAMP, seed_rows=rows,
                          clock_s=600, owned_count=0)
        two = score_build(build_ids=["3094", "3087"], champ=_CHAMP,
                          seed_rows=rows, clock_s=600, owned_count=0)
        self.assertGreater(two.penalties, one.penalties)
        # The collision must actually drag the colliding pair's total below
        # what a non-colliding pair of comparable rows scores.
        clean = score_build(build_ids=["3094", "3072"], champ=_CHAMP,
                            seed_rows=rows, clock_s=600, owned_count=0)
        self.assertLess(two.total, clean.total)


# --------------------------------------------------------------------------- #
# planner.py
# --------------------------------------------------------------------------- #
class PlannerBeamTests(unittest.TestCase):
    def test_seed_fn_none_yields_seedless_plan(self):
        plan = plan_build(champion=_CHAMP, seed_fn=None)
        self.assertIsInstance(plan, BuildPlan)
        self.assertEqual(plan.items, [])
        self.assertEqual(plan.builds_evaluated, 0)

    def test_blank_champion_yields_seedless_plan(self):
        plan = plan_build(champion="", seed_fn=make_seed_fn())
        self.assertEqual(plan.items, [])

    def test_beam_returns_at_most_width(self):
        plan = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(),
                          beam_width=5, depth=6)
        self.assertLessEqual(len(plan.beam), 5)
        self.assertGreaterEqual(len(plan.beam), 1)

    def test_beam_width_clamped_to_5_8(self):
        lo = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(),
                        beam_width=1, depth=4)
        hi = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(),
                        beam_width=99, depth=4)
        self.assertGreaterEqual(lo.beam_width, 5)
        self.assertLessEqual(hi.beam_width, 8)

    def test_depth_respected(self):
        plan = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(),
                          beam_width=6, depth=3)
        self.assertLessEqual(len(plan.items), 3)
        self.assertLessEqual(plan.depth_reached, 3)

    def test_builds_evaluated_bounded(self):
        # depth x width x pool is the loose ceiling; assert we never exceed it.
        seed = make_seed_fn()
        pool = len(seed(_CHAMP)["ranked"])
        plan = plan_build(champion=_CHAMP, seed_fn=seed,
                          beam_width=6, depth=6)
        self.assertGreater(plan.builds_evaluated, 0)
        self.assertLessEqual(plan.builds_evaluated, 6 * 8 * (pool + 4))

    def test_at_most_one_item_per_unique_family(self):
        # The two energized items share a family - a single build must never
        # contain both (unique-passive-safe by construction).
        plan = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(),
                          beam_width=8, depth=6)
        for cand in plan.beam:
            fams = [pi.unique_passive_key for pi in cand.items
                    if pi.unique_passive_key]
            self.assertEqual(len(fams), len(set(fams)),
                             f"duplicate family in {[pi.item_id for pi in cand.items]}")

    def test_dedupe_by_set(self):
        # No two distinct beam survivors share the same item SET.
        plan = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(),
                          beam_width=8, depth=6)
        sets = [frozenset(pi.item_id for pi in cand.items) for cand in plan.beam]
        self.assertEqual(len(sets), len(set(sets)))

    def test_threshold_prune_drops_weak_offspring(self):
        # A tighter relative threshold (closer to 1.0) cannot evaluate MORE
        # builds than a looser one - the prune genuinely culls offspring.
        seed = make_seed_fn()
        loose = plan_build(champion=_CHAMP, seed_fn=seed, beam_width=6,
                           depth=6, prune_threshold=0.5)
        tight = plan_build(champion=_CHAMP, seed_fn=seed, beam_width=6,
                           depth=6, prune_threshold=0.99)
        self.assertLessEqual(tight.builds_evaluated, loose.builds_evaluated)

    def test_higher_synergy_item_orders_above_lower_for_fixed_champ(self):
        # For a crit-marksman (MF), Infinity Edge (crit) must out-rank Mortal
        # Reminder (armor-pen, low kit-fit) as the chosen first purchase when
        # their seed DPS deltas are made equal - cohesion (C1) breaks the tie.
        def tie_seed(champion, owned_ids=None, **kw):
            owned = {str(i) for i in (owned_ids or ())}
            base = [
                ("3031", "Infinity Edge", "", True),
                ("3033", "Mortal Reminder", "", True),
            ]
            ranked = [{"item_id": i, "item_name": n, "delta_dps": 90.0,
                       "gold": 3000, "unique_passive_key": f, "is_terminal": t}
                      for (i, n, f, t) in base if i not in owned]
            return {"ok": True, "ranked": ranked, "order": []}

        plan = plan_build(champion=_CHAMP, seed_fn=tie_seed, beam_width=6,
                          depth=1)
        top = plan.items
        self.assertTrue(top)
        self.assertEqual(top[0].item_id, "3031")

    def test_planned_items_carry_score_terms(self):
        # Explainability: every chosen PlannedItem exposes its ScoreTerms.
        plan = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(),
                          beam_width=6, depth=4)
        self.assertTrue(plan.items)
        for pi in plan.items:
            self.assertIsInstance(pi.terms, ScoreTerms)

    def test_thin_projection_seed_still_plans(self):
        # The /api/ds-preview projection drops unique_passive_key/is_terminal -
        # the planner must still return a non-empty plan (missing family ->
        # treated as no-collision).
        plan = plan_build(champion=_CHAMP, seed_fn=make_seed_fn(thin=True),
                          beam_width=6, depth=4)
        self.assertTrue(plan.items)


# --------------------------------------------------------------------------- #
# Structural guards
# --------------------------------------------------------------------------- #
class StructuralGuardTests(unittest.TestCase):
    _SOURCES = (
        _ROOT / "core" / "build_planner" / "scoring.py",
        _ROOT / "core" / "build_planner" / "planner.py",
        _ROOT / "core" / "build_planner" / "situational.py",
        _ROOT / "core" / "build_planner" / "replan.py",
    )
    # Hand-typed when the scan had seven names; kept as a floor so a broken
    # engine import can never shrink the ban below what shipped.
    _FAMILY_FLOOR = (
        "spellblade", "lifeline", "immolate", "hydra_cleave",
        "fiendhunter_barrage", "hellfire_char", "innervating_fill",
    )

    @staticmethod
    def _engine_families() -> frozenset[str]:
        # The family set is the engine's: the distinct non-empty
        # unique_passive_key values over ITEM_EFFECTS (the same derivation as
        # tests/test_unique_passive_family_count_s144d36.py). The TEST imports
        # the engine; the planner sources it scans must not.
        from agents.daemon_slayer.effects import ITEM_EFFECTS
        return frozenset(
            k for k in (getattr(e, "unique_passive_key", "")
                        for e in ITEM_EFFECTS.values()) if k)

    def _banned_families(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._FAMILY_FLOOR) | self._engine_families()))

    def test_no_in_process_engine_import(self):
        # Mirrors
        # TestNoEngineSplitBrain.test_routes_state_has_no_in_process_engine_import
        # in tests/test_ds_preview_e2e_p1l21.py - build_planner must reach DS
        # only over the injectable HTTP-boundary seed_fn, never by importing
        # the in-process engine. Every module of the package, not only the
        # four planning modules: an engine import in a helper module is the
        # same split-brain.
        sources = sorted((_ROOT / "core" / "build_planner").glob("*.py"))
        self.assertGreaterEqual(len(sources), len(self._SOURCES))
        self.assertTrue(set(self._SOURCES) <= set(sources))
        for src_path in sources:
            tree = ast.parse(src_path.read_text(encoding="utf-8"))
            offenders: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        if n.name.startswith("agents.daemon_slayer"):
                            offenders.append(n.name)
                elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agents.daemon_slayer"):
                    offenders.append(node.module or "")
            self.assertEqual(
                offenders, [],
                f"{src_path.name} imports the engine in-process {offenders!r} "
                "- build_planner must use the seed_fn HTTP boundary.")

    def test_no_unique_family_literal_in_source(self):
        # The no-double rule is engine-authoritative (the "No-double rule is
        # engine-authoritative" paragraph of the core/build_order.py module
        # docstring; the family count is re-derived by
        # tests/test_unique_passive_family_count_s144d36.py). The planner must
        # INHERIT unique_passive_key from seed rows, never hardcode a family
        # name - a guard against the s173 anti-drift trap. The ban is every
        # family the engine defines, so a new family is banned the day it
        # lands.
        banned = self._banned_families()
        for src_path in self._SOURCES:
            src = src_path.read_text(encoding="utf-8").lower()
            for fam in banned:
                self.assertNotIn(
                    fam, src,
                    f"{src_path.name} contains family literal {fam!r} - "
                    "inherit unique_passive_key from the seed instead.")

    def test_family_ban_covers_every_engine_family(self):
        # The hand-typed ban had seven names while the engine had nine
        # (last_whisper and void_pen were never scanned for).
        engine = self._engine_families()
        self.assertGreaterEqual(len(engine), 6)
        self.assertTrue(set(self._FAMILY_FLOOR) <= engine,
                        sorted(set(self._FAMILY_FLOOR) - engine))
        self.assertTrue(engine <= set(self._banned_families()))

    # The substring scan above cannot widen past the four planning modules:
    # helper modules use "spellblade" as a mechanic word in prose and
    # identifiers. The token-level scan below covers EVERY module instead.
    # A module listed here may hold the named family tokens as string
    # constants, for the measured reason given.
    _TOKEN_EXEMPT: dict[str, frozenset[str]] = {
        # "spellblade" is an item_effect_flags flag (curated _SPELLBLADE_IDS,
        # read by the cadence and non-user gates), not a no-double family
        # key: the module never reads unique_passive_key.
        "kit_synergy.py": frozenset({"spellblade"}),
    }

    @staticmethod
    def _family_constants(src: str, banned) -> list[tuple[int, str]]:
        # A str constant whose WHOLE value (stripped, lower-cased) is a family
        # key: a dict key, a set member, a comparison operand, a call
        # argument. Comments, identifiers and prose sentences (a docstring
        # that is more than the bare key) never match.
        return [
            (node.lineno, node.value) for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.strip().lower() in banned
        ]

    def test_no_family_key_constant_in_any_module(self):
        banned = frozenset(self._banned_families())
        sources = sorted((_ROOT / "core" / "build_planner").glob("*.py"))
        self.assertTrue(set(self._SOURCES) <= set(sources))
        for src_path in sources:
            allowed = self._TOKEN_EXEMPT.get(src_path.name, frozenset())
            hits = [
                h for h in self._family_constants(
                    src_path.read_text(encoding="utf-8"), banned)
                if h[1].strip().lower() not in allowed
            ]
            self.assertEqual(
                hits, [],
                f"{src_path.name} holds family key constants {hits!r} - "
                "inherit unique_passive_key from the seed instead.")

    def test_token_exemptions_are_live_and_never_meet_the_family_key(self):
        # A stale exemption (the token is gone) or one in a module that has
        # started reading unique_passive_key fails, so the list cannot rot
        # into a blanket pass.
        banned = frozenset(self._banned_families())
        pkg = _ROOT / "core" / "build_planner"
        for name, tokens in self._TOKEN_EXEMPT.items():
            src = (pkg / name).read_text(encoding="utf-8")
            self.assertTrue(tokens <= banned, sorted(tokens - banned))
            found = {v.strip().lower()
                     for _, v in self._family_constants(src, banned)}
            self.assertTrue(tokens <= found,
                            f"stale exemption {sorted(tokens - found)} "
                            f"in {name}")
            self.assertNotIn("unique_passive_key", src,
                             f"{name} reads unique_passive_key, so its "
                             "family tokens are no longer exempt")

    def test_family_constant_scan_has_teeth(self):
        banned = frozenset(self._banned_families())
        hit = self._family_constants(
            'X = {"last_whisper": 1}\nif k == "void_pen":\n    pass\n', banned)
        self.assertEqual(sorted(v for _, v in hit), ["last_whisper", "void_pen"])
        miss = self._family_constants(
            '"""last_whisper prose."""\nlast_whisper = 1\n# "void_pen"\n'
            'Z = "spellblade cadence"\n', banned)
        self.assertEqual(miss, [])


if __name__ == "__main__":
    unittest.main()
