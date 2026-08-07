"""Tests for core.build_order_variants - the HZ-B2 anti-tank / anti-squishy
build-order VARIANT layer on top of HZ-B1 (core.build_order_precompute).

HZ-B2 is the enemy-comp BRANCH: per (champ x mode) it emits an explicit
``anti_tank`` (vs a high-HP / frontline wall) vs ``anti_squishy`` (vs a
burst / low-HP comp) pair, driven by the DS anti-tank axis A3
(``core.ds_antitank_hint`` -> ``build_antitank_hint``). The A3 signal decides
HOW HARD a champion pivots anti-tank: a champion whose own kit already shreds
tanks (``lean_in``) gets a softer wall + lower expected anti-tank-item count
than a flat-damage champion that must itemize the shred (``recommend_
antitank_items``).

Characterization, not prediction: each variant cell is the SHIPPED
``core.build_order.plan_build_order`` output under that variant's enemy-stat
bias - the precompute is a pure re-parameterization of the engine. The build
planner is exercised headless where a fixed order suffices (an injected fake
``rank_fn`` standing in for the live :8860 dispatcher); the ITEM-PIVOT assertion
(anti_tank surfaces a penetration / %max-HP item the anti_squishy variant drops)
runs against the LIVE engine and skips when it is down, so CI never depends on
:8860.

Distinct from HZ-B1: HZ-B1's ``frontline_heavy`` is one of four comp-SHAPE
classes (a fixed enemy stat block); HZ-B2 is a champion-DECISION axis - the
anti_tank vs anti_squishy EXTREMES modulated PER champion by that champion's own
A3 anti-tank score. The two tables share ``SEED_CHAMPIONS`` so they align.
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

import core.build_order_variants as bov  # noqa: E402
import core.build_order_precompute as bop  # noqa: E402

# The shipped-table gate lives in the HZ-B1 suite (one implementation, not
# seven copies). Importing the two FUNCTIONS by name binds only those names -
# the sibling module's TestCase classes are not pulled into this namespace and
# so are not collected twice.
from tests.test_build_order_precompute import (  # noqa: E402
    load_shipped_table,
    require_shipped_table,
)


# --------------------------------------------------------------------------- #
# Headless fake ranker (the DS dispatcher stand-in) - mirrors the HZ-B1 test.
# --------------------------------------------------------------------------- #
def _fake_rank_fn(ranked_ids):
    """rank_fn(champion, archetype, **kwargs) stub yielding a fixed ranked list
    (highest first), skipping anything already in item_ids. The bias kwargs flow
    through unchanged - the stub does not branch on them, so a precompute cell
    is byte-identical to a direct plan_build_order call threaded the same way."""

    def _rank(champion, archetype, **kwargs):
        owned = {str(i) for i in (kwargs.get("item_ids") or ())}
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
    """The variant axis is a deterministic, documented closed pair, each mapping
    to an enemy-stat bias; it is DISTINCT from the HZ-B1 comp-archetype axis."""

    def test_variants_are_the_expected_closed_pair(self):
        self.assertEqual(set(bov.VARIANTS), {"anti_tank", "anti_squishy"})

    def test_every_variant_has_a_base_bias(self):
        self.assertEqual(set(bov.VARIANT_BIAS.keys()), set(bov.VARIANTS))

    def test_bias_keys_are_engine_levers(self):
        expected = {
            "target_armor", "target_mr", "target_max_hp", "target_bonus_hp",
            "enemy_ad_share", "enemy_ap_share", "target_current_hp_pct",
        }
        for variant, bias in bov.VARIANT_BIAS.items():
            self.assertEqual(set(bias.keys()), expected, f"bias for {variant}")

    def test_anti_tank_is_a_tankier_wall_than_anti_squishy(self):
        at = bov.VARIANT_BIAS["anti_tank"]
        sq = bov.VARIANT_BIAS["anti_squishy"]
        self.assertGreater(at["target_max_hp"], sq["target_max_hp"])
        self.assertGreater(at["target_armor"], sq["target_armor"])
        self.assertGreater(at["target_mr"], sq["target_mr"])

    def test_seed_aligns_with_hz_b1(self):
        # The two tables MUST share the seed so they line up champ-for-champ.
        self.assertEqual(tuple(bov.SEED_CHAMPIONS), tuple(bop.SEED_CHAMPIONS))

    def test_variant_bias_for_unknown_raises(self):
        with self.assertRaises(KeyError):
            bov.variant_bias_for("Garen", "not_a_variant")


class A3SignalTests(unittest.TestCase):
    """The A3 anti-tank axis (ds_antitank_hint) drives HOW HARD a champion
    pivots anti-tank - this is what makes HZ-B2 the anti-tank BRANCH, not a
    second copy of HZ-B1's frontline class."""

    def test_signal_reports_a3_fields(self):
        sig = bov.antitank_signal("Vayne", mode="SR")
        for key in (
            "my_antitank_score", "shreds_resist", "lean_in",
            "recommend_antitank_items",
        ):
            self.assertIn(key, sig)
        # Vayne's kit melts tanks (A3 score high) -> lean_in true.
        self.assertGreater(sig["my_antitank_score"], 0.0)
        self.assertTrue(sig["lean_in"])

    def test_signal_flatdamage_champ_recommends_items(self):
        # Lux is a flat-damage mage (A3 score ~0): she cannot shred a tank with
        # her kit, so the anti-tank pivot must come from ITEMS.
        sig = bov.antitank_signal("Lux", mode="SR")
        self.assertEqual(sig["my_antitank_score"], 0.0)
        self.assertFalse(sig["lean_in"])
        self.assertTrue(sig["recommend_antitank_items"])

    def test_a3_modulates_anti_tank_wall(self):
        # A champion that already shreds (lean_in) faces a SOFTER synthetic wall
        # than a flat-damage champion that must itemize the shred - the A3 score
        # is plumbed into the anti_tank enemy model. anti_squishy is A3-invariant
        # (no wall to shred there).
        shredder = bov.variant_bias_for("Vayne", "anti_tank")
        flat = bov.variant_bias_for("Lux", "anti_tank")
        self.assertLess(
            shredder["target_max_hp"], flat["target_max_hp"],
            "A3 lean_in should soften the anti_tank wall vs a flat-damage champ",
        )
        # anti_squishy bias does not depend on the champion's A3 score.
        self.assertEqual(
            bov.variant_bias_for("Vayne", "anti_squishy"),
            bov.variant_bias_for("Lux", "anti_squishy"),
        )


class CellEngineCharacterizationTests(unittest.TestCase):
    """A variant cell == a direct plan_build_order call with that variant's
    (A3-modulated) bias - the precompute is DS math, no re-derivation."""

    def test_cell_equals_direct_plan_for_bias(self):
        from core.build_order import plan_build_order

        rank_fn = _fake_rank_fn(["3153", "3036", "6694", "3033", "3031", "3006"])
        bias = bov.variant_bias_for("Caitlyn", "anti_tank")
        direct, rank_kwargs = bop.split_bias(bias)
        cell = bov.compute_variant_cell(
            "Caitlyn", "anti_tank", mode="SR",
            archetype="carry", level=13, rank_fn=rank_fn,
        )
        ref = plan_build_order(
            "Caitlyn", "carry", level=13, owned_item_ids=[], mode="SR",
            slots=bop.SLOTS, rank_fn=rank_fn, rank_kwargs=rank_kwargs, **direct,
        )
        self.assertIsNotNone(ref)
        self.assertEqual(cell["order"], [s.item_id for s in ref.order])
        self.assertEqual(cell["variant"], "anti_tank")
        self.assertEqual(cell["bias"], bias)
        # The A3 stanza is stamped on the cell (provenance of the pivot).
        self.assertIn("antitank", cell)
        self.assertIn("my_antitank_score", cell["antitank"])

    def test_variants_thread_distinct_context(self):
        seen = {}

        def _spy_rank(champion, archetype, **kwargs):
            seen.setdefault("ctx", []).append({
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

        bov.compute_variant_cell("Caitlyn", "anti_tank", mode="SR",
                                 archetype="carry", level=13, rank_fn=_spy_rank)
        at_ctx = seen["ctx"][0]
        seen.clear()
        bov.compute_variant_cell("Caitlyn", "anti_squishy", mode="SR",
                                 archetype="carry", level=13, rank_fn=_spy_rank)
        sq_ctx = seen["ctx"][0]
        self.assertNotEqual(at_ctx, sq_ctx)
        self.assertGreater(at_ctx["target_max_hp"], sq_ctx["target_max_hp"])

    def test_cell_engine_down_yields_empty_order(self):
        def _down(champion, archetype, **kwargs):
            return None

        cell = bov.compute_variant_cell(
            "Caitlyn", "anti_tank", mode="SR", archetype="carry",
            level=13, rank_fn=_down,
        )
        self.assertEqual(cell["order"], [])


class LiveEnginePivotTests(unittest.TestCase):
    """The defining HZ-B2 assertion: for a champion that CAN, the anti_tank
    variant actually pivots toward an anti-tank ITEM (a penetration / %max-HP
    item) that the anti_squishy variant drops. Runs against the LIVE engine -
    skips when :8860 is down so CI never depends on it."""

    # Engine anti-tank items: %armor/%MR penetration, flat lethality-agnostic
    # armor-pen, %max-HP shred, antiheal. A non-fragile SET membership check
    # (not an exact-list assert): the anti_tank order must contain at least one,
    # and at least one the anti_squishy order does NOT.
    _ANTI_TANK_ITEM_IDS = frozenset({
        "3036",    # Lord Dominik's Regards (%armor pen + %max-HP)
        "6694",    # Serylda's Grudge (armor pen)
        "6695",    # Serpent's Fang
        "3033",    # Mortal Reminder (armor pen + antiheal)
        "3153",    # Blade of The Ruined King (%current-HP on-hit)
        "8001",    # (defensive alias slot; harmless if unused)
        "3135",    # Void Staff (%MR pen)
        "3137",    # Cryptbloom (%MR pen)
        "4015",    # (defensive alias slot; harmless if unused)
    })

    def setUp(self):
        # MEASURED 2026-07-26 (skip audit): this used to be one try block with a
        # bare `except Exception` wrapped around BOTH the import and the
        # skipTest below it. `unittest.SkipTest` subclasses `Exception`, so the
        # "engine is down" skip was caught by its own handler and re-raised as
        # "DS client import failed". Probed the same day: the import succeeds -
        # every transient :8860 timeout for the life of this test was reported
        # to the operator as a broken import, pointing debugging at the wrong
        # half of the system.
        #
        # 2026-07-27 skip audit: the import guard is now GONE entirely.
        # core/daemon_slayer_client.py is TRACKED, so it imports in every
        # checkout; a failure there is the thing under test being broken, not an
        # absent capability. Letting the ImportError propagate makes it a hard
        # error instead of a green skip. Only the :8860 liveness gate below is a
        # real capability check.
        #
        # RM-119 B2 (2026-08-06): the liveness gate now routes through the
        # shared one in tests/test_ds_live_route_gate.py, so
        # RC_REQUIRE_DS_ENGINE=1 turns "the engine is down" from a green skip
        # into a failure on a host where it is supposed to be up. Behaviour
        # without that flag is unchanged - a down engine is still a skip,
        # which is correct in CI and in a fresh clone.
        from core import daemon_slayer_client as dsc
        from tests.test_ds_live_route_gate import require_live_engine
        require_live_engine("the HZ-B2 live engine pivot",
                            up=dsc.is_engine_up(timeout=1.5))

    def test_anti_tank_surfaces_a_penetration_or_hp_item(self):
        cell = bov.compute_variant_cell(
            "Caitlyn", "anti_tank", mode="SR", archetype="carry", level=13,
        )
        order = set(cell["order"])
        self.assertTrue(
            order & self._ANTI_TANK_ITEM_IDS,
            f"anti_tank order had no penetration/%HP item: {cell['order']}",
        )

    def test_anti_tank_differs_from_anti_squishy_for_a_pivoting_champ(self):
        at = bov.compute_variant_cell(
            "Caitlyn", "anti_tank", mode="SR", archetype="carry", level=13,
        )
        sq = bov.compute_variant_cell(
            "Caitlyn", "anti_squishy", mode="SR", archetype="carry", level=13,
        )
        self.assertNotEqual(
            at["order"], sq["order"],
            "anti_tank and anti_squishy variants must differ for Caitlyn",
        )
        # The anti_tank variant must surface an anti-tank item the anti_squishy
        # variant does NOT - the item-level pivot, the heart of HZ-B2.
        at_only = set(at["order"]) - set(sq["order"])
        self.assertTrue(
            at_only & self._ANTI_TANK_ITEM_IDS,
            f"anti_tank had no anti-tank item the squishy build dropped: "
            f"at={at['order']} sq={sq['order']}",
        )


class GenerateTableTests(unittest.TestCase):
    """The table sweep emits the documented schema + a dimensions stanza naming
    the variants."""

    def test_generate_table_schema_and_dimensions(self):
        rank_fn = _fake_rank_fn(["3153", "3036", "6694", "3033"])
        payload = bov.generate_table(
            ["Caitlyn", "Lux"], mode="SR", level=13, rank_fn=rank_fn,
        )
        self.assertEqual(payload["mode"], "sr")
        self.assertEqual(payload["schema"], bov.SCHEMA_VERSION)
        self.assertTrue(payload["version"])
        self.assertEqual(payload["engine_version"], bov.engine_version())
        dims = payload["dimensions"]
        self.assertEqual(set(dims["variants"]), set(bov.VARIANTS))
        self.assertIn("level", dims)
        # Names the A3 axis it is driven by (provenance, machine-checkable).
        self.assertIn("driven_by", dims)
        bo = payload["build_orders"]
        self.assertEqual(set(bo.keys()), {"Caitlyn", "Lux"})
        for champ in ("Caitlyn", "Lux"):
            self.assertEqual(set(bo[champ].keys()), set(bov.VARIANTS))
            for variant in bov.VARIANTS:
                self.assertIn("order", bo[champ][variant])
                self.assertIn("variant", bo[champ][variant])
                self.assertIn("antitank", bo[champ][variant])
        json.dumps(payload, ensure_ascii=True).encode("ascii")

    def test_generate_table_cell_count(self):
        rank_fn = _fake_rank_fn(["3153", "3036"])
        payload = bov.generate_table(
            ["Caitlyn", "Lux", "Garen"], mode="SR", level=13, rank_fn=rank_fn,
        )
        cells = sum(len(v) for v in payload["build_orders"].values())
        # 3 champs x 2 variants = 6 cells.
        self.assertEqual(cells, 6)


class PersistAndReaderTests(unittest.TestCase):
    """atomic_write round-trips ASCII JSON; lookup navigates the nesting; a
    missing DB fails soft to {}/{}."""

    def _payload(self) -> dict:
        cell = {
            "variant": "anti_tank",
            "order": ["3153", "3036", "6694", "3033", "3031", "3006"],
            "bias": bov.variant_bias_for("Caitlyn", "anti_tank"),
            "antitank": {
                "my_antitank_score": 0.0, "shreds_resist": False,
                "lean_in": False, "recommend_antitank_items": False,
                "top_kind": "",
            },
        }
        return {
            "version": "16.11.1", "generated_at": "2026-06-08T00:00:00Z",
            "mode": "sr", "schema": bov.SCHEMA_VERSION,
            "engine_version": "1.120.0",
            "dimensions": {"variants": list(bov.VARIANTS), "level": 13,
                           "driven_by": "ds_antitank_hint/A3"},
            "build_orders": {"Caitlyn": {"anti_tank": cell}},
        }

    def test_atomic_write_roundtrip_ascii(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "build_order_variants_sr.json"
            bov.atomic_write(payload, out)
            raw = out.read_bytes()
            raw.decode("ascii")
            self.assertEqual(json.loads(raw.decode("utf-8")), payload)
            self.assertEqual(list(out.parent.glob("*.tmp")), [])

    def test_lookup_navigates_nesting(self) -> None:
        payload = self._payload()
        cell = bov.lookup(payload, "Caitlyn", "anti_tank")
        self.assertEqual(
            cell["order"], ["3153", "3036", "6694", "3033", "3031", "3006"]
        )

    def test_lookup_missing_returns_empty(self) -> None:
        payload = self._payload()
        self.assertEqual(bov.lookup(payload, "Nobody", "anti_tank"), {})
        self.assertEqual(bov.lookup(payload, "Caitlyn", "no_such_variant"), {})
        self.assertEqual(bov.lookup({}, "Caitlyn", "anti_tank"), {})

    def test_load_missing_db_failsoft(self) -> None:
        # Per-mode table path must fail-soft to {} for every shipped mode
        # (sr/aram/arena, items 377/386/388) - guards per-mode load routing.
        for mode in ("sr", "aram", "arena"):
            self.assertEqual(
                bov.load_build_order_variants(mode=mode, patch="0.0.0"), {}
            )

    def test_load_then_lookup_roundtrip(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "build_order_variants_sr.json"
            bov.atomic_write(payload, out)
            loaded = json.loads(out.read_text(encoding="utf-8"))
            cell = bov.lookup(loaded, "Caitlyn", "anti_tank")
            self.assertEqual(cell["variant"], "anti_tank")


class PatchAndPathTests(unittest.TestCase):
    """resolve_patch + out-path helpers behave; the variant table lives in the
    HZ-B1 build_orders/ subdir under a DISTINCT filename."""

    def test_resolve_patch_fallback_on_missing(self):
        from unittest import mock
        # resolve_patch is imported from build_order_precompute and reads THAT
        # module's _CURRENT_TXT / _FALLBACK_PATCH - patch the defining module,
        # not bov's re-exported copies (the latter masked the fallback whenever
        # the live current.txt happened to equal _FALLBACK_PATCH).
        with mock.patch.object(bop, "_CURRENT_TXT", Path("/no/such/current.txt")):
            self.assertEqual(bov.resolve_patch(), bop._FALLBACK_PATCH)

    def test_db_path_uses_build_orders_subdir_distinct_file(self):
        p = bov._db_path("sr", "16.11.1")
        # data/daemon_slayer/build_orders/<patch>/build_order_variants_sr.json
        self.assertEqual(p.name, "build_order_variants_sr.json")
        self.assertEqual(p.parent.name, "16.11.1")
        self.assertEqual(p.parent.parent.name, "build_orders")
        self.assertEqual(p.parent.parent.parent.name, "daemon_slayer")
        # Distinct from HZ-B1's file so neither clobbers the other.
        self.assertNotEqual(p.name, bop._db_path("sr", "16.11.1").name)

    def test_out_dir_override_wins(self):
        d = bov.out_dir_for("16.11.1", "/tmp/whatever")
        self.assertEqual(d, Path("/tmp/whatever"))


class SeedTableTests(unittest.TestCase):
    """The committed SR variant seed table is present, well-formed, and matches
    the module's declared schema + taxonomy. The anti_tank variant of at least
    one seeded champ DIFFERS from its anti_squishy variant (the table actually
    encodes a pivot, not two identical builds).

    Read through `load_shipped_table`, NOT the fail-soft production loader: only
    an ABSENT table may skip, and a corrupt one must fail."""

    def test_committed_sr_seed_is_wellformed(self):
        payload = load_shipped_table(
            bov._db_path("sr", bov.resolve_patch()),
            "HZ-B2 build_order_variants/sr",
        )
        self.assertEqual(payload["schema"], bov.SCHEMA_VERSION)
        self.assertEqual(
            set(payload["dimensions"]["variants"]), set(bov.VARIANTS)
        )
        bo = payload["build_orders"]
        self.assertTrue(bo, "variant seed table has no champions")
        for champ, variants in bo.items():
            self.assertEqual(set(variants.keys()), set(bov.VARIANTS),
                             f"{champ} missing a variant")
            for variant, cell in variants.items():
                self.assertEqual(cell["variant"], variant)
                self.assertIsInstance(cell["order"], list)
                self.assertIn("antitank", cell)

    def test_committed_seed_has_a_real_pivot(self):
        payload = load_shipped_table(
            bov._db_path("sr", bov.resolve_patch()),
            "HZ-B2 build_order_variants/sr",
        )
        bo = payload["build_orders"]
        differs = [
            champ for champ, v in bo.items()
            if v["anti_tank"]["order"] and v["anti_squishy"]["order"]
            and v["anti_tank"]["order"] != v["anti_squishy"]["order"]
        ]
        self.assertTrue(
            differs,
            "no seeded champion's anti_tank order differs from anti_squishy - "
            "the variant table encodes no pivot",
        )


class AsciiHygieneTests(unittest.TestCase):
    """The module + the committed seed table are 7-bit ASCII (CLAUDE.md rule)."""

    def test_module_source_is_ascii(self):
        data = Path(bov.__file__).read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(data) if b >= 0x80]
        self.assertEqual(non_ascii, [], f"non-ASCII in module: {non_ascii[:5]}")

    def test_seed_table_is_ascii(self):
        path = require_shipped_table(
            bov._db_path("sr", bov.resolve_patch()),
            "HZ-B2 build_order_variants/sr",
        )
        data = path.read_bytes()
        self.assertTrue(all(b < 0x80 for b in data), "non-ASCII in seed table")


if __name__ == "__main__":
    unittest.main()
