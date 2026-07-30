"""Producer fail-LOUD guards for the build-order precompute family.

The precomputed build-order tables are the substrate the deterministic coaching
path reads, and EVERY consumer of a missing cell degrades silently:
``core/precomputed_build_coach.py`` returns ``[]``, ``core/next_buy_fallback.py``
returns ``[]``, ``dashboard/_deterministic_coaching.py`` returns ``None``,
``core/laning_verdicts.py`` returns ``None``. Nothing downstream can tell a
truncated table from a champion the engine legitimately had no plan for.

That makes the PRODUCER the only place a truncation can be caught, so a producer
that cannot honour an explicit full-roster request - or that computed an entirely
empty table - must fail loudly instead of overwriting a good artifact with a stub
and exiting 0.

These tests pin the loud behaviour. They do NOT touch ``data/``: every write goes
to a tmp ``--out`` override.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import build_order_precompute as bop  # noqa: E402
from core import build_order_variants as bov  # noqa: E402
from tools import daemon_slayer_build_orders_generate as gen  # noqa: E402


def _plan_returning(order_ids):
    """Stand-in ``plan_build_order`` returning a plan with ``order_ids`` (or
    ``None`` when the caller wants the 'engine planned nothing' shape)."""
    class _Slot:
        def __init__(self, item_id):
            self.item_id = item_id

    class _Result:
        def __init__(self, ids):
            self.order = [_Slot(i) for i in ids]

    def _plan(*_a, **_kw):
        return None if order_ids is None else _Result(order_ids)

    return _plan


class RegistryUnreadableTests(unittest.TestCase):
    """``full_roster()`` must RAISE, never substitute the 10-name seed.

    A ``--champions all`` caller asking for 173 and silently receiving 10 would
    replace a complete table with a 6-percent one.
    """

    def _point_registry_at(self, tmp: Path):
        """Redirect the registry lookup at a controlled dir (no data/ writes)."""
        return mock.patch.object(bop, "_DS_DIR", tmp)

    def test_missing_registry_raises(self):
        with TemporaryDirectory() as td:
            with self._point_registry_at(Path(td)):
                with self.assertRaises(bop.RosterUnavailableError):
                    bop.full_roster()

    def test_malformed_registry_raises(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            patch_dir = tmp / bop.resolve_patch()
            patch_dir.mkdir(parents=True)
            (patch_dir / "champions.json").write_text("{not json", encoding="utf-8")
            with self._point_registry_at(tmp):
                with self.assertRaises(bop.RosterUnavailableError):
                    bop.full_roster()

    def test_empty_registry_raises(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            patch_dir = tmp / bop.resolve_patch()
            patch_dir.mkdir(parents=True)
            (patch_dir / "champions.json").write_text(
                json.dumps({"data": {}}), encoding="utf-8")
            with self._point_registry_at(tmp):
                with self.assertRaises(bop.RosterUnavailableError):
                    bop.full_roster()

    def test_never_returns_the_seed(self):
        """The specific regression: a seed-sized list impersonating the roster."""
        with TemporaryDirectory() as td:
            with self._point_registry_at(Path(td)):
                try:
                    roster = bop.full_roster()
                except bop.RosterUnavailableError:
                    return
                self.assertNotEqual(
                    sorted(roster), sorted(bop.SEED_CHAMPIONS),
                    "full_roster() silently substituted SEED_CHAMPIONS",
                )

    def test_all_token_propagates_the_raise(self):
        with TemporaryDirectory() as td:
            with self._point_registry_at(Path(td)):
                with self.assertRaises(bop.RosterUnavailableError):
                    bop.resolve_champions("all")


class SeedPathPreservedTests(unittest.TestCase):
    """The LEGITIMATE seed path stays exactly as it was - only the impersonation
    of a full roster is removed."""

    def test_empty_value_still_yields_the_seed(self):
        self.assertEqual(
            tuple(bop.resolve_champions("")), tuple(bop.SEED_CHAMPIONS))
        self.assertEqual(
            tuple(bop.resolve_champions("   ")), tuple(bop.SEED_CHAMPIONS))

    def test_csv_still_parsed_verbatim(self):
        self.assertEqual(bop.resolve_champions("Ahri, Zed"), ["Ahri", "Zed"])

    def test_seed_path_does_not_touch_the_registry(self):
        """An empty --champions must not even consult the registry, so a broken
        registry cannot break the seed default."""
        with TemporaryDirectory() as td:
            with mock.patch.object(bop, "_DS_DIR", Path(td)):
                self.assertEqual(
                    tuple(bop.resolve_champions("")), tuple(bop.SEED_CHAMPIONS))


class PrecomputeCliExitsNonZeroTests(unittest.TestCase):
    """``--champions all`` against a broken registry exits non-zero + writes
    nothing (both the HZ-B1 table and the HZ-B2 variants table)."""

    def test_precompute_main_exits_non_zero(self):
        with TemporaryDirectory() as td, TemporaryDirectory() as reg:
            with mock.patch.object(bop, "_DS_DIR", Path(reg)):
                rc = bop.main(["--champions", "all", "--dry-run", "--out", td])
            self.assertNotEqual(rc, 0)
            self.assertEqual(list(Path(td).glob("*.json")), [])

    def test_variants_main_exits_non_zero(self):
        with TemporaryDirectory() as td, TemporaryDirectory() as reg:
            with mock.patch.object(bop, "_DS_DIR", Path(reg)):
                rc = bov.main(["--champions", "all", "--dry-run", "--out", td])
            self.assertNotEqual(rc, 0)
            self.assertEqual(list(Path(td).glob("*.json")), [])


class EmptyTableRefusedTests(unittest.TestCase):
    """A sweep whose every cell came back empty must NOT be written.

    ``_engine_up()`` only gates an engine that is dead BEFORE the sweep. An
    engine that dies mid-sweep is swallowed per-cell ('one bad cell never sinks
    the sweep'), which on its own would write a full-size table of empty orders
    and exit 0 - the same silent-truncation failure in a different axis.
    """

    def test_precompute_refuses_an_all_empty_table(self):
        with TemporaryDirectory() as td:
            with mock.patch.object(bop, "plan_build_order", _plan_returning(None)), \
                 mock.patch.object(bop, "_engine_up", return_value=True):
                rc = bop.main(["--mode", "sr", "--champions", "Ahri", "--out", td])
            self.assertNotEqual(rc, 0)
            self.assertEqual(list(Path(td).glob("*.json")), [])

    def test_precompute_writes_a_non_empty_table(self):
        """Control: the guard must not fire on a healthy sweep."""
        with TemporaryDirectory() as td:
            with mock.patch.object(bop, "plan_build_order", _plan_returning([1001])), \
                 mock.patch.object(bop, "_engine_up", return_value=True):
                rc = bop.main(["--mode", "sr", "--champions", "Ahri", "--out", td])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(td) / "build_orders_sr.json").exists())

    def test_variants_refuses_an_all_empty_table(self):
        with TemporaryDirectory() as td:
            with mock.patch.object(bov, "plan_build_order", _plan_returning(None)), \
                 mock.patch.object(bov, "_engine_up", return_value=True):
                rc = bov.main(["--mode", "sr", "--champions", "Ahri", "--out", td])
            self.assertNotEqual(rc, 0)
            self.assertEqual(list(Path(td).glob("*.json")), [])

    def test_generator_refuses_an_all_empty_table(self):
        argv = ["prog", "--mode", "sr", "--out", ""]
        with TemporaryDirectory() as td:
            argv[-1] = td
            with mock.patch.object(gen, "plan_build_order", _plan_returning(None)), \
                 mock.patch.object(gen.dsc, "is_engine_up", return_value=True), \
                 mock.patch.object(gen, "load_champions", return_value=["Ahri"]), \
                 mock.patch.object(gen.sys, "argv", argv):
                rc = gen.main()
            self.assertNotEqual(rc, 0)
            self.assertEqual(list(Path(td).glob("*.json")), [])


class GeneratorRosterTests(unittest.TestCase):
    """``tools/daemon_slayer_build_orders_generate.load_champions`` had the same
    shape: ``raw.get("data", raw) or {}`` yields ``[]`` on a wrong-shaped or
    empty registry, and main() then wrote a ZERO-champion table and exited 0."""

    def test_empty_registry_raises(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "ddragon_champions.json"
            path.write_text(json.dumps({"data": {}}), encoding="utf-8")
            with mock.patch.object(gen, "_CHAMPS_PATH", path):
                with self.assertRaises(bop.RosterUnavailableError):
                    gen.load_champions()

    def test_wrong_shaped_registry_raises(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "ddragon_champions.json"
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            with mock.patch.object(gen, "_CHAMPS_PATH", path):
                with self.assertRaises(bop.RosterUnavailableError):
                    gen.load_champions()

    def test_main_exits_non_zero_on_an_unresolvable_roster(self):
        argv = ["prog", "--mode", "sr", "--out", ""]
        with TemporaryDirectory() as td:
            argv[-1] = td
            boom = mock.Mock(side_effect=bop.RosterUnavailableError("boom"))
            with mock.patch.object(gen.dsc, "is_engine_up", return_value=True), \
                 mock.patch.object(gen, "load_champions", boom), \
                 mock.patch.object(gen.sys, "argv", argv):
                rc = gen.main()
            self.assertNotEqual(rc, 0)
            self.assertEqual(list(Path(td).glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
