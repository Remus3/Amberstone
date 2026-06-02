"""Tests for tools/daemon_slayer_build_orders_generate.py (Lane B table gen).

NO live engine: ``plan_build_order`` is monkeypatched to a deterministic fake
so the schema / enemy-class mapping / atomic-write / filter / dry-run
behavior is exercised without :8893.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import tools.daemon_slayer_build_orders_generate as gen


class _FakeStep:
    """Stand-in for core.build_order.BuildStep - only ``item_id`` is read."""

    def __init__(self, item_id: str):
        self.item_id = item_id


class _FakeResult:
    """Stand-in for BuildOrderResult - only ``order`` is read."""

    def __init__(self, ids):
        self.order = [_FakeStep(i) for i in ids]


def _fake_plan_factory(ids=("1001", "3006", "3031", "3036", "3072", "3094")):
    """Return a plan_build_order stub that always yields a fixed 6-id build."""

    def _fake(*_args, **_kwargs):
        return _FakeResult(ids)

    return _fake


class SchemaTests(unittest.TestCase):
    """The generator produces the correct 3-class nested schema per champ."""

    def test_generate_mode_nested_schema(self):
        with mock.patch.object(gen, "plan_build_order", _fake_plan_factory()):
            payload = gen.generate_mode("sr", ["Aatrox", "Lux"], "16.11.1")
        self.assertEqual(payload["mode"], "sr")
        self.assertEqual(payload["version"], "16.11.1")
        self.assertIn("generated_at", payload)
        bo = payload["build_orders"]
        self.assertEqual(set(bo.keys()), {"Aatrox", "Lux"})
        for champ in ("Aatrox", "Lux"):
            self.assertEqual(
                set(bo[champ].keys()),
                {"ad_heavy", "balanced", "ap_heavy"},
            )
            for cls in ("ad_heavy", "balanced", "ap_heavy"):
                self.assertEqual(
                    bo[champ][cls],
                    ["1001", "3006", "3031", "3036", "3072", "3094"],
                )

    def test_build_orders_for_champion_three_classes(self):
        with mock.patch.object(gen, "plan_build_order", _fake_plan_factory(("3153",))):
            out = gen.build_orders_for_champion("Jinx", "aram")
        self.assertEqual(set(out.keys()), {"ad_heavy", "balanced", "ap_heavy"})
        self.assertEqual(out["ad_heavy"], ["3153"])

    def test_item_ids_are_strings(self):
        # BuildStep.item_id may be coerced from non-str; generator forces str.
        with mock.patch.object(gen, "plan_build_order",
                               lambda *a, **k: _FakeResult([1001, 3006])):
            ids = gen.build_order_for_class("Ahri", "mage", "sr", "balanced")
        self.assertEqual(ids, ["1001", "3006"])
        self.assertTrue(all(isinstance(i, str) for i in ids))

    def test_empty_id_steps_filtered(self):
        with mock.patch.object(gen, "plan_build_order",
                               lambda *a, **k: _FakeResult(["1001", "", "3006"])):
            ids = gen.build_order_for_class("Ahri", "mage", "sr", "balanced")
        self.assertEqual(ids, ["1001", "3006"])


class EnemyClassMappingTests(unittest.TestCase):
    """Each enemy-comp class passes the right enemy_ad_share into the engine."""

    def _capture_share(self, comp_class: str) -> float:
        seen = {}

        def _spy(*_args, **kwargs):
            seen.update(kwargs.get("rank_kwargs") or {})
            return _FakeResult(["1001"])

        with mock.patch.object(gen, "plan_build_order", _spy):
            gen.build_order_for_class("Aatrox", "bruiser", "sr", comp_class)
        return seen["enemy_ad_share"]

    def test_ad_heavy_share(self):
        self.assertEqual(self._capture_share("ad_heavy"), 0.7)

    def test_balanced_share(self):
        self.assertEqual(self._capture_share("balanced"), 0.5)

    def test_ap_heavy_share(self):
        self.assertEqual(self._capture_share("ap_heavy"), 0.3)

    def test_shares_table_complete(self):
        # Every declared class has a share tuple summing to 1.0.
        self.assertEqual(set(gen._COMP_SHARES.keys()), set(gen.ENEMY_COMP_CLASSES))
        for ad, ap in gen._COMP_SHARES.values():
            self.assertAlmostEqual(ad + ap, 1.0, places=6)

    def test_typical_enemy_block_passed(self):
        # The shared level-11 typical-enemy stat block reaches the engine.
        seen = {}

        def _spy(*_args, **kwargs):
            seen.update(kwargs)
            return _FakeResult(["1001"])

        with mock.patch.object(gen, "plan_build_order", _spy):
            gen.build_order_for_class("Aatrox", "bruiser", "sr", "balanced")
        self.assertEqual(seen["level"], 11)
        self.assertEqual(seen["target_armor"], 80.0)
        self.assertEqual(seen["target_mr"], 60.0)
        self.assertEqual(seen["target_max_hp"], 2000.0)
        self.assertEqual(seen["target_bonus_hp"], 600.0)
        self.assertEqual(seen["slots"], 6)


class FailSoftTests(unittest.TestCase):
    """A raising / empty engine yields [] for that cell, never crashes."""

    def test_engine_raises_yields_empty(self):
        def _boom(*_a, **_k):
            raise RuntimeError("engine down")

        with mock.patch.object(gen, "plan_build_order", _boom):
            ids = gen.build_order_for_class("Aatrox", "bruiser", "sr", "ad_heavy")
        self.assertEqual(ids, [])

    def test_none_result_yields_empty(self):
        with mock.patch.object(gen, "plan_build_order", lambda *a, **k: None):
            ids = gen.build_order_for_class("Aatrox", "bruiser", "sr", "ad_heavy")
        self.assertEqual(ids, [])

    def test_empty_order_yields_empty(self):
        with mock.patch.object(gen, "plan_build_order",
                               lambda *a, **k: _FakeResult([])):
            ids = gen.build_order_for_class("Aatrox", "bruiser", "sr", "ad_heavy")
        self.assertEqual(ids, [])


class AtomicWriteTests(unittest.TestCase):
    """atomic_write replaces a tmp file with valid sorted ASCII JSON."""

    def test_atomic_write_valid_sorted_ascii(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sub" / "build_orders_sr.json"
            payload = {
                "version": "16.11.1",
                "generated_at": "2026-06-02T00:00:00Z",
                "mode": "sr",
                "build_orders": {
                    "Zac": {"ad_heavy": ["1"], "balanced": ["2"], "ap_heavy": ["3"]},
                    "Aatrox": {"ad_heavy": ["4"], "balanced": ["5"], "ap_heavy": ["6"]},
                },
            }
            gen.atomic_write(payload, out)
            self.assertTrue(out.exists())
            raw = out.read_text(encoding="utf-8")
            # valid JSON
            loaded = json.loads(raw)
            self.assertEqual(loaded["mode"], "sr")
            self.assertEqual(loaded["build_orders"]["Zac"]["ad_heavy"], ["1"])
            # sorted keys: Aatrox before Zac in serialized text
            self.assertLess(raw.index('"Aatrox"'), raw.index('"Zac"'))
            # ensure_ascii: no tmp leftover
            leftovers = list(out.parent.glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_atomic_write_ascii_escapes_nonascii(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "build_orders_sr.json"
            # A champ display name with an apostrophe-ish high char would be
            # escaped under ensure_ascii; assert no raw non-ASCII byte lands.
            name = "Kai" + chr(0x2019) + "Sa"
            payload = {"version": "x", "generated_at": "x", "mode": "sr",
                       "build_orders": {name: {"ad_heavy": [],
                                        "balanced": [], "ap_heavy": []}}}
            gen.atomic_write(payload, out)
            raw_bytes = out.read_bytes()
            self.assertTrue(all(b < 0x80 for b in raw_bytes))


class ChampionFilterTests(unittest.TestCase):
    """--champion restricts output to the named champion only."""

    def test_main_champion_filter(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            argv = ["prog", "--mode", "sr", "--champion", "Jinx", "--out", td]
            with mock.patch.object(gen, "plan_build_order", _fake_plan_factory()), \
                 mock.patch.object(gen.dsc, "is_engine_up", return_value=True), \
                 mock.patch.object(gen, "load_champions",
                                   return_value=["Aatrox", "Jinx", "Lux"]), \
                 mock.patch.object(gen.sys, "argv", argv):
                rc = gen.main()
            self.assertEqual(rc, 0)
            out = Path(td) / "build_orders_sr.json"
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(set(payload["build_orders"].keys()), {"Jinx"})

    def test_main_unknown_champion_errors(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            argv = ["prog", "--mode", "sr", "--champion", "Nope", "--out", td]
            with mock.patch.object(gen.dsc, "is_engine_up", return_value=True), \
                 mock.patch.object(gen, "load_champions",
                                   return_value=["Aatrox", "Jinx"]), \
                 mock.patch.object(gen.sys, "argv", argv):
                rc = gen.main()
            self.assertEqual(rc, 2)


class DryRunTests(unittest.TestCase):
    """--dry-run writes nothing and does not require a live engine."""

    def test_dry_run_writes_nothing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            argv = ["prog", "--mode", "all", "--dry-run", "--out", td]
            with mock.patch.object(gen, "plan_build_order", _fake_plan_factory()), \
                 mock.patch.object(gen, "load_champions",
                                   return_value=["Aatrox"]), \
                 mock.patch.object(gen.sys, "argv", argv):
                rc = gen.main()
            self.assertEqual(rc, 0)
            # No JSON files written under the override dir.
            self.assertEqual(list(Path(td).glob("*.json")), [])

    def test_dry_run_skips_engine_check(self):
        # is_engine_up must NOT gate a dry-run (engine never queried).
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            argv = ["prog", "--mode", "sr", "--dry-run", "--out", td]
            up_spy = mock.Mock(return_value=False)
            with mock.patch.object(gen, "plan_build_order", _fake_plan_factory()), \
                 mock.patch.object(gen.dsc, "is_engine_up", up_spy), \
                 mock.patch.object(gen, "load_champions",
                                   return_value=["Aatrox"]), \
                 mock.patch.object(gen.sys, "argv", argv):
                rc = gen.main()
            self.assertEqual(rc, 0)
            up_spy.assert_not_called()


class EngineGateTests(unittest.TestCase):
    """A non-dry run refuses when the engine is down (returns 2, no write)."""

    def test_engine_down_refuses(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            argv = ["prog", "--mode", "sr", "--out", td]
            with mock.patch.object(gen.dsc, "is_engine_up", return_value=False), \
                 mock.patch.object(gen, "load_champions",
                                   return_value=["Aatrox"]), \
                 mock.patch.object(gen.sys, "argv", argv):
                rc = gen.main()
            self.assertEqual(rc, 2)
            self.assertEqual(list(Path(td).glob("*.json")), [])


class PatchResolveTests(unittest.TestCase):
    """resolve_patch + out_dir_for behave for present/absent current.txt."""

    def test_resolve_patch_fallback_on_missing(self):
        with mock.patch.object(gen, "_CURRENT_TXT", Path("/no/such/current.txt")):
            self.assertEqual(gen.resolve_patch(), gen._FALLBACK_PATCH)

    def test_out_dir_override_wins(self):
        d = gen.out_dir_for("16.11.1", "/tmp/whatever")
        self.assertEqual(d, Path("/tmp/whatever"))

    def test_out_dir_default_uses_patch(self):
        d = gen.out_dir_for("16.99.9", None)
        self.assertEqual(d.name, "16.99.9")
        self.assertEqual(d.parent.name, "daemon_slayer")


class AsciiHygieneTests(unittest.TestCase):
    """The generator source is 7-bit ASCII (CLAUDE.md hard rule)."""

    def test_generator_source_is_ascii(self):
        src = (gen.__file__)
        data = Path(src).read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(data) if b >= 0x80]
        self.assertEqual(non_ascii, [], f"non-ASCII bytes in generator: {non_ascii[:5]}")


if __name__ == "__main__":
    unittest.main()
