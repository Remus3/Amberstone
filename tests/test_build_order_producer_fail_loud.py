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
import os
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


def _real_registries() -> list[Path]:
    """Every REAL DDragon champion registry reachable from this machine.

    Always this checkout's own committed registry, plus:
    * ``RC_TEST_DDRAGON_CHAMPIONS`` when set (an out-of-tree copy - how a
      not-yet-committed DDragon drop is exercised without importing it into
      ``data/``), and
    * the MAIN worktree's registry when this checkout is a git worktree
      (``<main>/.claude/worktrees/<name>``), so a pending drop staged in the
      main tree is covered from here too.

    Deliberately real files, not a synthetic fixture: the duplicate SHAPE is the
    thing under test, and a hand-built fixture would only re-assert whatever
    shape the author imagined.
    """
    candidates = [_ROOT / "data" / "meta" / "ddragon_champions.json"]
    env = os.environ.get("RC_TEST_DDRAGON_CHAMPIONS", "").strip()
    if env:
        candidates.append(Path(env))
    parts = _ROOT.resolve().parts
    if len(parts) >= 3 and parts[-3:-1] == (".claude", "worktrees"):
        main_root = _ROOT.resolve().parents[2]
        candidates.append(main_root / "data" / "meta" / "ddragon_champions.json")
    out: list[Path] = []
    for path in candidates:
        if path.is_file() and path.resolve() not in {p.resolve() for p in out}:
            out.append(path)
    return out


class RosterDedupeTests(unittest.TestCase):
    """``load_champions`` must return DISTINCT names.

    DDragon 16.15.1 adds 60 ``Jade_<Champion>`` THROWBACK-MODE VARIANT entries
    at ``base_key + 60000``. They are NOT aliases: each carries its own
    older-patch stat line (``Jade_Ahri`` key 60103 hp 460 against ``Ahri`` key
    103 hp 590) and only the display ``name`` collides with the base champion.
    That takes the registry from 173 to 233 entries which still describe 173
    champions. The pre-fix loader appended one name per entry, so the day that
    drop is committed the display-name roster silently inflates to 233 - 60
    phantom duplicates, each swept twice, with nothing failing.

    The dedupe below is therefore a DISPLAY-NAME collapse for the generator's
    own sweep, not a claim that the two rows are the same champion row. The
    engine classifies by the key floor, never by the ``Jade_`` name prefix -
    see ``agents/daemon_slayer/mode_variants.py`` and
    ``tests/test_champion_mode_variants.py``.
    """

    def test_names_are_distinct_on_every_real_registry(self):
        registries = _real_registries()
        self.assertTrue(registries, "no real DDragon registry found")
        for path in registries:
            with self.subTest(registry=str(path)):
                raw = json.loads(path.read_text(encoding="utf-8"))
                data = raw.get("data", raw)
                with mock.patch.object(gen, "_CHAMPS_PATH", path):
                    names = gen.load_champions()
                self.assertEqual(
                    len(names), len(set(names)),
                    f"{path} produced duplicate champion names",
                )
                expected = {
                    str(e.get("name") or e.get("id"))
                    for e in data.values()
                    if isinstance(e, dict) and (e.get("name") or e.get("id"))
                }
                self.assertEqual(set(names), expected)
                self.assertEqual(names, sorted(names, key=str.lower))

    def test_alias_heavy_registry_collapses_to_the_base_roster(self):
        """The exact 233-entry -> 173-name regression, on real data."""
        alias_heavy = [
            p for p in _real_registries()
            if len(json.loads(p.read_text(encoding="utf-8")).get("data", {}))
            > len({
                str(e.get("name") or e.get("id"))
                for e in json.loads(
                    p.read_text(encoding="utf-8")).get("data", {}).values()
                if isinstance(e, dict)
            })
        ]
        if not alias_heavy:
            self.skipTest(
                "no alias-carrying DDragon registry reachable (set "
                "RC_TEST_DDRAGON_CHAMPIONS to a 16.15.1+ copy to exercise it)")
        for path in alias_heavy:
            with self.subTest(registry=str(path)):
                raw = json.loads(path.read_text(encoding="utf-8"))
                entries = len(raw.get("data", raw))
                with mock.patch.object(gen, "_CHAMPS_PATH", path):
                    names = gen.load_champions()
                self.assertLess(
                    len(names), entries,
                    "alias entries were not collapsed",
                )
                self.assertEqual(len(names), len(set(names)))
                # The aliases are name-equal to a champion already present, so
                # nothing may be LOST by deduping.
                for entry in raw.get("data", raw).values():
                    nm = entry.get("name") or entry.get("id")
                    if nm:
                        self.assertIn(str(nm), names)

    def test_full_roster_is_deduped_by_construction(self):
        """Sibling shape: full_roster() sorted a generator, not a set, so its
        'deduped' guarantee held only by accident of today's clean registry."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            patch_dir = tmp / bop.resolve_patch()
            patch_dir.mkdir(parents=True)
            (patch_dir / "champions.json").write_text(json.dumps({"data": {
                "Ahri": {"id": "Ahri"},
                "Ahri_dup": {"id": "Ahri"},
                "Zed": {"id": "Zed"},
            }}), encoding="utf-8")
            with mock.patch.object(bop, "_DS_DIR", tmp):
                roster = bop.full_roster()
            self.assertEqual(roster, ["Ahri", "Zed"])


if __name__ == "__main__":
    unittest.main()
