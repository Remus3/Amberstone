"""Tests for core.build_order_precompute - the Lane B build-order precompute
(HZ-B1). Characterization vs DS math: a generated cell's ordered build == the
engine's ``core.build_order.plan_build_order`` output for that comp-archetype's
itemization bias (precompute = DS math, the HZ-A1
tests/test_laning_scenario_precompute.py pattern). Pure-helper + persist +
reader round-trip tests need no engine.

The build planner is exercised headless: ``plan_build_order`` accepts an
injectable ``rank_fn`` (the DS dispatcher), so a deterministic fake ranker
stands in for the live :8893 server. The characterization asserts the
precompute module's cell is byte-identical to a direct ``plan_build_order``
call threaded with the SAME comp-archetype bias - i.e. the precompute is a
pure re-parameterization of the shipped engine, no new combat math.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.build_order_precompute as bop  # noqa: E402


# --------------------------------------------------------------------------- #
# Headless fake ranker (the DS dispatcher stand-in)
# --------------------------------------------------------------------------- #
def _fake_rank_fn(ranked_ids):
    """Return a rank_fn(champion, archetype, **kwargs) stub that always yields a
    fixed ranked list (highest first). The bias kwargs (target_armor/mr/hp,
    enemy_*_share, target_current_hp_pct) flow through unchanged - we do not
    branch on them, so the precompute-vs-direct comparison is exact regardless
    of the bias values (the point: the precompute passes the SAME kwargs as a
    direct call, so they cancel)."""

    def _rank(champion, archetype, **kwargs):
        owned = set(str(i) for i in (kwargs.get("item_ids") or ()))
        rows = []
        for iid in ranked_ids:
            if str(iid) in owned:
                continue
            rows.append({
                "item_id": str(iid),
                "item_name": f"Item{iid}",
                "delta": 100.0,
                "gold": 1000,
                "scorer": "dps",
                "unique_passive_key": "",
                "shares_dead_unique": False,
            })
        return {"scorer": "dps", "ranked": rows}

    return _rank


class TaxonomyTests(unittest.TestCase):
    """The comp-archetype taxonomy is a deterministic, documented closed set,
    and every class maps to an itemization bias."""

    def test_comp_archetypes_are_the_expected_closed_set(self):
        self.assertEqual(
            set(bop.COMP_ARCHETYPES),
            {"frontline_heavy", "burst_heavy", "poke", "mixed"},
        )

    def test_every_archetype_has_a_bias(self):
        self.assertEqual(
            set(bop.COMP_BIAS.keys()), set(bop.COMP_ARCHETYPES)
        )

    def test_bias_keys_are_engine_levers(self):
        # Each bias is a dict of exactly the plan_build_order enemy-context
        # levers the precompute threads - no stray keys.
        expected = {
            "target_armor", "target_mr", "target_max_hp", "target_bonus_hp",
            "enemy_ad_share", "enemy_ap_share", "target_current_hp_pct",
        }
        for cls, bias in bop.COMP_BIAS.items():
            self.assertEqual(set(bias.keys()), expected, f"bias for {cls}")

    def test_frontline_is_tankier_than_burst(self):
        # The whole point of the axis: a frontline comp presents more armor/mr
        # and far more HP than a burst comp, so the engine values %max-HP /
        # armor-pen there and raw early power vs burst.
        fl = bop.COMP_BIAS["frontline_heavy"]
        bu = bop.COMP_BIAS["burst_heavy"]
        self.assertGreater(fl["target_max_hp"], bu["target_max_hp"])
        self.assertGreater(fl["target_armor"], bu["target_armor"])
        self.assertGreater(fl["target_mr"], bu["target_mr"])

    def test_shares_sum_within_one(self):
        for cls, bias in bop.COMP_BIAS.items():
            s = bias["enemy_ad_share"] + bias["enemy_ap_share"]
            self.assertLessEqual(s, 1.0 + 1e-9, f"shares over 1.0 for {cls}")

    def test_bias_for_unknown_class_raises(self):
        with self.assertRaises(KeyError):
            bop.bias_for("not_a_class")


class CellEngineCharacterizationTests(unittest.TestCase):
    """A precompute cell == a direct plan_build_order call with the same bias.

    No live engine: a deterministic fake rank_fn is injected into BOTH the
    precompute path and the reference call, so the only thing under test is
    that the precompute threads the comp-archetype bias into plan_build_order
    correctly (the precompute is DS math, not a re-derivation)."""

    def test_cell_equals_direct_plan_for_bias(self):
        from core.build_order import plan_build_order

        rank_fn = _fake_rank_fn(["3153", "3071", "3074", "3033", "3036", "6333"])
        bias = bop.bias_for("frontline_heavy")
        direct, rank_kwargs = bop.split_bias(bias)
        cell = bop.compute_cell(
            "Aatrox", "frontline_heavy", mode="SR",
            archetype="bruiser", level=11, rank_fn=rank_fn,
        )
        ref = plan_build_order(
            "Aatrox", "bruiser", level=11, owned_item_ids=[], mode="SR",
            slots=bop.SLOTS, rank_fn=rank_fn, rank_kwargs=rank_kwargs, **direct,
        )
        self.assertIsNotNone(ref)
        self.assertEqual(cell["order"], [s.item_id for s in ref.order])
        # The provenance records the bias actually applied.
        self.assertEqual(cell["comp_archetype"], "frontline_heavy")
        self.assertEqual(cell["bias"], bias)

    def test_distinct_classes_thread_distinct_context(self):
        # Two classes with different resist/HP profiles must reach the engine
        # with different target_* context (proves the axis is live, not cosmetic).
        seen = {}

        def _spy_rank(champion, archetype, **kwargs):
            seen.setdefault(archetype + "|ctx", []).append({
                k: kwargs.get(k) for k in (
                    "target_armor", "target_mr", "target_max_hp",
                    "enemy_ad_share", "target_current_hp_pct",
                )
            })
            return {"scorer": "dps", "ranked": [{
                "item_id": "3153", "item_name": "x", "delta": 1.0,
                "gold": 1, "scorer": "dps", "unique_passive_key": "",
                "shares_dead_unique": False,
            }]}

        bop.compute_cell("Aatrox", "frontline_heavy", mode="SR",
                         archetype="bruiser", level=11, rank_fn=_spy_rank)
        front_ctx = seen["bruiser|ctx"][0]
        seen.clear()
        bop.compute_cell("Aatrox", "burst_heavy", mode="SR",
                         archetype="bruiser", level=11, rank_fn=_spy_rank)
        burst_ctx = seen["bruiser|ctx"][0]
        self.assertNotEqual(front_ctx, burst_ctx)
        self.assertGreater(front_ctx["target_max_hp"], burst_ctx["target_max_hp"])

    def test_cell_order_nonempty_under_fake_engine(self):
        rank_fn = _fake_rank_fn(["3153", "3071", "3074"])
        cell = bop.compute_cell(
            "Lux", "poke", mode="SR", archetype="mage", level=11, rank_fn=rank_fn,
        )
        self.assertTrue(cell["order"])
        self.assertTrue(all(isinstance(i, str) for i in cell["order"]))

    def test_cell_engine_down_yields_empty_order(self):
        # plan_build_order returns None when the (fake) ranker yields None on
        # the first call - the cell degrades to an empty order, never raises.
        def _down(champion, archetype, **kwargs):
            return None

        cell = bop.compute_cell(
            "Aatrox", "mixed", mode="SR", archetype="bruiser",
            level=11, rank_fn=_down,
        )
        self.assertEqual(cell["order"], [])


class GenerateTableTests(unittest.TestCase):
    """The table sweep emits the documented schema + dimensions stanza."""

    def test_generate_table_schema_and_dimensions(self):
        rank_fn = _fake_rank_fn(["3153", "3071", "3074", "3033"])
        payload = bop.generate_table(
            ["Aatrox", "Lux"], mode="SR", level=11, rank_fn=rank_fn,
        )
        self.assertEqual(payload["mode"], "sr")
        self.assertEqual(payload["schema"], bop.SCHEMA_VERSION)
        self.assertTrue(payload["version"])
        self.assertEqual(payload["engine_version"], bop.engine_version())
        dims = payload["dimensions"]
        self.assertEqual(
            set(dims["comp_archetypes"]), set(bop.COMP_ARCHETYPES)
        )
        self.assertIn("level", dims)
        bo = payload["build_orders"]
        self.assertEqual(set(bo.keys()), {"Aatrox", "Lux"})
        for champ in ("Aatrox", "Lux"):
            self.assertEqual(set(bo[champ].keys()), set(bop.COMP_ARCHETYPES))
            for cls in bop.COMP_ARCHETYPES:
                self.assertIn("order", bo[champ][cls])
                self.assertIn("comp_archetype", bo[champ][cls])
        # ASCII-clean serialization.
        json.dumps(payload, ensure_ascii=True).encode("ascii")

    def test_generate_table_cell_count(self):
        rank_fn = _fake_rank_fn(["3153", "3071"])
        payload = bop.generate_table(
            ["Aatrox", "Lux", "Garen"], mode="SR", level=11, rank_fn=rank_fn,
        )
        cells = sum(len(v) for v in payload["build_orders"].values())
        # 3 champs x 4 comp archetypes = 12 cells.
        self.assertEqual(cells, 12)


class PersistAndReaderTests(unittest.TestCase):
    """atomic_write round-trips ASCII JSON; lookup navigates the nesting;
    a missing DB fails soft to {}/{}."""

    def _payload(self) -> dict:
        cell = {
            "comp_archetype": "frontline_heavy",
            "order": ["3153", "3071", "3074", "3033", "3036", "6333"],
            "bias": bop.bias_for("frontline_heavy"),
        }
        return {
            "version": "16.11.1", "generated_at": "2026-06-08T00:00:00Z",
            "mode": "sr", "schema": bop.SCHEMA_VERSION,
            "engine_version": "1.120.0",
            "dimensions": {"comp_archetypes": list(bop.COMP_ARCHETYPES),
                           "level": 11},
            "build_orders": {"Aatrox": {"frontline_heavy": cell}},
        }

    def test_atomic_write_roundtrip_ascii(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "build_orders_sr.json"
            bop.atomic_write(payload, out)
            raw = out.read_bytes()
            raw.decode("ascii")  # raises if any non-ASCII byte slipped in
            self.assertEqual(json.loads(raw.decode("utf-8")), payload)
            self.assertEqual(list(out.parent.glob("*.tmp")), [])

    def test_lookup_navigates_nesting(self) -> None:
        payload = self._payload()
        cell = bop.lookup(payload, "Aatrox", "frontline_heavy")
        self.assertEqual(
            cell["order"], ["3153", "3071", "3074", "3033", "3036", "6333"]
        )

    def test_lookup_missing_returns_empty(self) -> None:
        payload = self._payload()
        self.assertEqual(bop.lookup(payload, "Nobody", "frontline_heavy"), {})
        self.assertEqual(bop.lookup(payload, "Aatrox", "no_such_class"), {})
        self.assertEqual(bop.lookup({}, "Aatrox", "frontline_heavy"), {})

    def test_load_missing_db_failsoft(self) -> None:
        # A patch with no committed file must degrade to {} (never raise).
        self.assertEqual(
            bop.load_build_order_precompute(mode="sr", patch="0.0.0"), {}
        )

    def test_load_then_lookup_roundtrip(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "build_orders_sr.json"
            bop.atomic_write(payload, out)
            loaded = json.loads(out.read_text(encoding="utf-8"))
            cell = bop.lookup(loaded, "Aatrox", "frontline_heavy")
            self.assertEqual(cell["comp_archetype"], "frontline_heavy")


class PatchAndPathTests(unittest.TestCase):
    """resolve_patch + out path helpers behave for present/absent current.txt
    and the NEW build_orders/ subdir is used (not the flat item-265/266 path)."""

    def test_resolve_patch_fallback_on_missing(self):
        from unittest import mock
        with mock.patch.object(bop, "_CURRENT_TXT", Path("/no/such/current.txt")):
            self.assertEqual(bop.resolve_patch(), bop._FALLBACK_PATCH)

    def test_db_path_uses_build_orders_subdir(self):
        p = bop._db_path("sr", "16.11.1")
        # NEW subdir: data/daemon_slayer/build_orders/<patch>/build_orders_sr.json
        self.assertEqual(p.name, "build_orders_sr.json")
        self.assertEqual(p.parent.name, "16.11.1")
        self.assertEqual(p.parent.parent.name, "build_orders")
        self.assertEqual(p.parent.parent.parent.name, "daemon_slayer")

    def test_out_dir_override_wins(self):
        d = bop.out_dir_for("16.11.1", "/tmp/whatever")
        self.assertEqual(d, Path("/tmp/whatever"))


class SeedTableTests(unittest.TestCase):
    """The committed SR seed table is present, well-formed, and matches the
    module's declared schema + taxonomy (guards a stale / hand-edited file)."""

    def test_committed_sr_seed_is_wellformed(self):
        payload = bop.load_build_order_precompute(mode="sr")
        if not payload:
            self.skipTest("no committed SR seed table for the current patch")
        self.assertEqual(payload["schema"], bop.SCHEMA_VERSION)
        self.assertEqual(
            set(payload["dimensions"]["comp_archetypes"]),
            set(bop.COMP_ARCHETYPES),
        )
        bo = payload["build_orders"]
        self.assertTrue(bo, "seed table has no champions")
        for champ, classes in bo.items():
            self.assertEqual(set(classes.keys()), set(bop.COMP_ARCHETYPES),
                             f"{champ} missing a comp archetype")
            for cls, cell in classes.items():
                self.assertEqual(cell["comp_archetype"], cls)
                self.assertIsInstance(cell["order"], list)


class AsciiHygieneTests(unittest.TestCase):
    """The module + the committed seed table are 7-bit ASCII (CLAUDE.md rule)."""

    def test_module_source_is_ascii(self):
        data = Path(bop.__file__).read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(data) if b >= 0x80]
        self.assertEqual(non_ascii, [], f"non-ASCII in module: {non_ascii[:5]}")

    def test_seed_table_is_ascii(self):
        path = bop._db_path("sr", bop.resolve_patch())
        if not path.exists():
            self.skipTest("no committed SR seed table")
        data = path.read_bytes()
        self.assertTrue(all(b < 0x80 for b in data), "non-ASCII in seed table")


if __name__ == "__main__":
    unittest.main()
