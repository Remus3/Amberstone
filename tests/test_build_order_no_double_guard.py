"""Anti-drift guard for the HARD RULE — no two items sharing a unique
passive in a planned build (2026-05-17).

The operator's hard rule is enforced engine-side: core.build_order
iterates rank_for_primary_archetype with filter_shared_uniques forced
True, so the engine's own collect_effects / current_unique_keys dedup
(source of truth = agents/daemon_slayer/effects.py) excludes every
same-family candidate once one is picked. The planner therefore has NO
family map of its own.

That property is load-bearing and must not rot:

  * If the planner ever grew a hardcoded family list it could drift from
    effects.py (the s173 anti-drift trap) — Test A forbids that.
  * effects.py defines SIX families today (spellblade/lifeline/immolate
    + the single-item fiendhunter_barrage/hellfire_char/innervating_fill).
    A family-agnostic planner covers all of them — and any future family
    added to effects.py — for free. Tests B/C prove that by deriving the
    family set from ITEM_EFFECTS at runtime and asserting no family is
    ever doubled in a planned order. A 7th family added later is covered
    automatically; a family tag accidentally dropped from effects.py
    trips Test C (s232-style saturation tripwire).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.effects import ITEM_EFFECTS
from core.build_order import plan_build_order

_BUILD_ORDER_SRC = Path(__file__).resolve().parent.parent / "core" / "build_order.py"


def _engine_families() -> set[str]:
    """The unique-passive family set as the engine actually defines it —
    the source of truth the planner must defer to."""
    return {
        e.unique_passive_key
        for e in ITEM_EFFECTS.values()
        if getattr(e, "unique_passive_key", "")
    }


class PlannerIsFamilyAgnosticTests(unittest.TestCase):
    """Test A — the planner must NOT hardcode any family name. The rule
    is enforced by engine iteration, not a local map that could drift."""

    def test_no_family_literal_in_planner_source(self):
        src = _BUILD_ORDER_SRC.read_text(encoding="utf-8")
        # Strip the module docstring + comments — prose may name families
        # to explain *why* the design is family-agnostic; only executable
        # code must be clean.
        code_lines = []
        in_doc = False
        for ln in src.splitlines():
            s = ln.strip()
            if s.startswith('"""') and not in_doc:
                in_doc = not (s.count('"""') >= 2)
                continue
            if in_doc:
                if s.endswith('"""') or s.count('"""') >= 1:
                    in_doc = False
                continue
            code_lines.append(ln.split("#", 1)[0])
        code = "\n".join(code_lines).lower()
        for fam in _engine_families():
            self.assertNotIn(
                f'"{fam}"', code,
                f"planner code references family literal {fam!r} — it must "
                f"stay family-agnostic (engine is the source of truth)",
            )
            self.assertNotIn(f"'{fam}'", code)

    def test_planner_forces_engine_dedup(self):
        # The actual enforcement mechanism must be present + forced.
        src = _BUILD_ORDER_SRC.read_text(encoding="utf-8")
        self.assertIn('filter_shared_uniques"] = True', src,
                       "planner must force filter_shared_uniques=True so a "
                       "caller cannot weaken the no-double rule")


# --- family-aware fake engine, catalog DERIVED from the real family set --

def _make_fake_catalog() -> dict:
    """Two synthetic items per real engine family + two family-less
    fillers. Derived at runtime so a new effects.py family is covered
    automatically."""
    cat: dict[str, tuple[str, float, str]] = {}
    base = 100.0
    for i, fam in enumerate(sorted(_engine_families())):
        cat[f"9{i}01"] = (f"{fam}-A", base - i, fam)
        cat[f"9{i}02"] = (f"{fam}-B", base - i - 0.5, fam)
    cat["8001"] = ("Filler-1", 70.0, "")
    cat["8002"] = ("Filler-2", 69.0, "")
    return cat


class _FakeEngine:
    """Mirrors rank.py: skips owned ids; with filter_shared_uniques=True
    omits any candidate whose family is already represented in item_ids."""

    def __init__(self, catalog: dict):
        self.cat = catalog

    def __call__(self, champion, archetype, **kw):
        item_ids = [str(i) for i in (kw.get("item_ids") or [])]
        filt = bool(kw.get("filter_shared_uniques", True))
        owned_fams = {
            self.cat[i][2] for i in item_ids
            if i in self.cat and self.cat[i][2]
        }
        rows = []
        for iid, (name, delta, fam) in self.cat.items():
            if iid in item_ids:
                continue
            if fam and fam in owned_fams and filt:
                continue
            rows.append({"item_id": iid, "item_name": name, "delta": delta,
                         "gold": 3000, "shares_dead_unique": False,
                         "dead_unique_key": ""})
        rows.sort(key=lambda r: r["delta"], reverse=True)
        return {"ok": True, "scorer": "dps", "archetype": archetype,
                "ranked": rows[: int(kw.get("top", 8) or 8)],
                "fell_back": False}


class EveryEngineFamilyCoveredTests(unittest.TestCase):
    """Tests B/C — the planner never doubles ANY family the engine
    defines, including the single-item ones, with zero family-aware code
    in the planner."""

    def setUp(self):
        self.cat = _make_fake_catalog()
        self.fam_of = {iid: f for iid, (_, _, f) in self.cat.items()}
        self.eng = _FakeEngine(self.cat)

    def test_no_family_doubled_in_a_full_plan(self):
        res = plan_build_order(
            "AnyChamp", "carry", level=18, owned_item_ids=[], mode="SR",
            slots=6, rank_fn=self.eng,
        )
        self.assertIsNotNone(res)
        fams = [self.fam_of[s.item_id] for s in res.order
                if self.fam_of.get(s.item_id)]
        for fam in _engine_families():
            self.assertLessEqual(
                fams.count(fam), 1,
                f"family {fam!r} appears >1× in the planned order — "
                f"HARD RULE violated",
            )
        self.assertTrue(res.unique_passive_safe)

    def test_whitelist_of_pure_family_yields_exactly_one(self):
        # Force the engine to only offer items of ONE family — correct
        # behavior is the order stops at exactly one (rest engine-deduped).
        for fam in sorted(_engine_families()):
            ids = [iid for iid, (_, _, f) in self.cat.items() if f == fam]
            if len(ids) < 2:
                continue
            eng = _FakeEngine({i: self.cat[i] for i in ids})
            res = plan_build_order(
                "AnyChamp", "carry", level=11, owned_item_ids=[],
                mode="SR", slots=6, rank_fn=eng,
            )
            self.assertEqual(
                len(res.order), 1,
                f"family {fam!r}: planner emitted {len(res.order)} items "
                f"from a single-family pool — engine dedup not enforced "
                f"through iteration",
            )
            self.assertTrue(res.unique_passive_safe)

    def test_family_set_has_not_regressed(self):
        # s232-style tripwire: the 6 known families must still be tagged
        # in effects.py. A drop here means a unique-passive item lost its
        # tag (silent no-double regression) — investigate effects.py, do
        # not just lower this bound.
        fams = _engine_families()
        for known in ("spellblade", "lifeline", "immolate"):
            self.assertIn(known, fams,
                          f"{known!r} family vanished from effects.py")
        self.assertGreaterEqual(
            len(fams), 6,
            f"expected >=6 unique-passive families, found {len(fams)}: "
            f"{sorted(fams)} — a family tag was likely dropped",
        )


if __name__ == "__main__":
    unittest.main()
