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
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.build_order_precompute as bop  # noqa: E402


# --------------------------------------------------------------------------- #
# Shipped-table gate - SHARED, imported by the sibling HZ precompute suites
# (test_build_order_variants, test_hz_precompute_canonical_keyspace,
# test_build_order_axis_parity). One implementation, not seven copies.
# --------------------------------------------------------------------------- #
REQUIRE_TABLES_ENV = "RC_REQUIRE_BUILD_ORDER_TABLES"


def build_order_tables_are_required() -> bool:
    """True when the CALLER has declared the shipped tables must be present.

    Set by the `check` job in .github/workflows/ci.yml, which checks out a tree
    where every table under data/daemon_slayer/build_orders/ IS tracked. Unset
    on a working copy sitting in the post-patch-bump regen gap, which is the one
    situation where "no table yet" is a legitimate reason not to assert.
    """
    return os.environ.get(REQUIRE_TABLES_ENV, "").strip().lower() not in (
        "", "0", "false", "no", "off",
    )


def require_shipped_table(path: Path, label: str) -> Path:
    """Skip when the table has not been generated - unless the caller SAID it is.

    MEASURED 2026-07-26 (skip audit): seven guards over the shipped build-order
    tables - schema version, comp-archetype taxonomy, per-champion completeness,
    canonical-vs-display keyspace, the anti-tank pivot, ASCII hygiene - were all
    written as `if not load_...(): self.skipTest(...)`. That loader is fail-soft
    to `{}` on ANY missing-or-parse error (core/build_order_precompute.py:472),
    so at the skip site an absent table and a CORRUPT one are the same value.
    Both reported green, and they reported green at exactly the moment the
    guards matter - a patch bump, when the table is regenerated. The tables feed
    the live dashboard build-order panel, so a stale or malformed one ships
    wrong item orders behind a green suite.

    The split is: ABSENCE is a capability question and may skip; anything else
    the file says is an assertion and must be able to fail. See
    `load_shipped_table` for the second half.

    Deleting the skip outright is not the fix - a checkout mid-regen genuinely
    has no current-patch table and would fail forever. The opt-in is the fix:
    with RC_REQUIRE_BUILD_ORDER_TABLES set, "not generated" stops being an
    excuse. Copied from RC_REQUIRE_HOOK_GATE in tests/test_drift_guard.py, which
    closed the identical hole in the git-hook gate the same day.
    """
    if path.is_file():
        return path
    if build_order_tables_are_required():
        raise AssertionError(
            f"{REQUIRE_TABLES_ENV} is set, so the shipped tables were supposed "
            f"to be PRESENT - but {label} is missing at {path}. Regenerate with "
            "python -m core.build_order_precompute --champions all"
        )
    raise unittest.SkipTest(
        f"no committed {label} table at {path} (set {REQUIRE_TABLES_ENV}=1 to "
        "make this a failure)"
    )


_LFS_POINTER_MAGIC = "version https://git-lfs.github.com/spec/v1"


def _is_lfs_pointer(raw: str) -> bool:
    """An LFS-tracked file whose CONTENT was never fetched into this checkout.

    MEASURED 2026-07-27, and this guard produced the false positive itself on
    its first CI run. `actions/checkout` does not fetch LFS objects by default,
    and the `laning_scenarios` tables are ~64MB LFS blobs, so on a runner the
    path EXISTS and holds a 130-byte pointer stub - which is, correctly, not
    valid JSON. Reporting that as a corrupt shipped table is wrong twice over:
    it blames the artifact for a checkout setting, and it fires on every CI run
    forever, which is how a guard gets loosened by whoever is tired of it.

    An unfetched pointer is a CAPABILITY condition - the same category as "not
    generated yet" - so it routes to the absence branch and skips. A file whose
    content IS present and malformed remains a hard failure. Keeping those two
    apart is the entire point of this module's split.
    """
    return raw.lstrip().startswith(_LFS_POINTER_MAGIC)


def load_shipped_table(path: Path, label: str) -> dict:
    """`require_shipped_table` plus a read that is deliberately NOT fail-soft.

    The production loader swallows a parse error into `{}` on purpose - the live
    dashboard must degrade, not crash. A TEST inheriting that swallow is how a
    corrupt shipped table came to report as "no table yet, skipped". Once the
    file exists AND its content is materialized, every byte is under assertion.
    """
    require_shipped_table(path, label)
    raw = path.read_text(encoding="utf-8")
    if _is_lfs_pointer(raw):
        # Skips even when RC_REQUIRE_BUILD_ORDER_TABLES is armed, deliberately.
        # That flag asserts the tables were GENERATED; whether LFS content was
        # FETCHED into this checkout is a different question with a different
        # owner (actions/checkout `lfs: true`, and ~190MB of transfer). Making
        # one flag mean both would force CI to choose between a permanent red
        # and paying for LFS on every run - and a permanently red guard gets
        # deleted, not fixed. If asserting LFS-backed tables in CI is ever
        # wanted, turn on LFS checkout; do not weaken this branch.
        raise unittest.SkipTest(
            f"{label} at {path} is an unfetched git-lfs pointer - the content "
            "is not in this checkout, so there is nothing to assert against"
        )
    try:
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - a corrupt shipped table is a FAIL
        raise AssertionError(
            f"{label} exists at {path} but is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AssertionError(
            f"{label} at {path} parsed to {type(payload).__name__}, not a dict"
        )
    return payload


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
    module's declared schema + taxonomy (guards a stale / hand-edited file).

    Read through `load_shipped_table`, NOT the fail-soft production loader: a
    file that exists must be asserted, never skipped past.
    """

    def test_committed_sr_seed_is_wellformed(self):
        payload = load_shipped_table(
            bop._db_path("sr", bop.resolve_patch()), "HZ-B1 build_orders/sr",
        )
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
        path = require_shipped_table(
            bop._db_path("sr", bop.resolve_patch()), "HZ-B1 build_orders/sr",
        )
        data = path.read_bytes()
        self.assertTrue(all(b < 0x80 for b in data), "non-ASCII in seed table")


class ShippedTableGateTests(unittest.TestCase):
    """Guards the gate itself, both directions.

    The skip this gate replaced was not wrong, it was unfalsifiable - it
    reported green in precisely the state it existed to catch. A replacement
    that can only ever skip would be the same bug wearing a new name, so both
    arms are pinned: absent-and-not-required SKIPS, absent-and-required FAILS,
    and a file that exists but is corrupt FAILS rather than skipping.
    """

    def _write(self, body: str) -> Path:
        p = Path(tempfile.mkdtemp()) / "table.json"
        p.write_text(body, encoding="utf-8")
        return p

    def test_an_unfetched_lfs_pointer_skips_rather_than_reading_as_corrupt(self) -> None:
        """CI found this by failing on it - see `_is_lfs_pointer`.

        actions/checkout does not fetch LFS objects, and the laning_scenarios
        tables are ~64MB LFS blobs, so on a runner the path exists and holds a
        pointer stub. That stub is legitimately not JSON, and calling it a
        corrupt shipped table blames the artifact for a checkout setting.
        """
        p = self._write(
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:0123456789abcdef\nsize 4242\n")
        os.environ.pop(REQUIRE_TABLES_ENV, None)
        with self.assertRaises(unittest.SkipTest):
            load_shipped_table(p, "lfs-backed table")

    def test_the_lfs_pointer_skip_is_not_overridden_by_the_require_flag(self) -> None:
        """The flag asserts GENERATION, not LFS FETCH - different owners.

        Conflating them would force CI to choose between a permanent red and
        paying ~190MB of LFS transfer per run, and a permanently red guard gets
        deleted rather than fixed.
        """
        p = self._write("version https://git-lfs.github.com/spec/v1\nsize 1\n")
        prev = os.environ.get(REQUIRE_TABLES_ENV)
        os.environ[REQUIRE_TABLES_ENV] = "1"
        try:
            with self.assertRaises(unittest.SkipTest):
                load_shipped_table(p, "lfs-backed table")
        finally:
            if prev is None:
                os.environ.pop(REQUIRE_TABLES_ENV, None)
            else:
                os.environ[REQUIRE_TABLES_ENV] = prev

    def test_a_corrupt_non_lfs_file_still_fails_and_is_not_mistaken_for_a_pointer(self) -> None:
        """The narrowing must not have widened into 'anything unparseable skips'."""
        p = self._write("{ this is not json")
        os.environ.pop(REQUIRE_TABLES_ENV, None)
        with self.assertRaises(AssertionError):
            load_shipped_table(p, "real but corrupt table")

    def _missing(self) -> Path:
        return Path(tempfile.mkdtemp()) / "build_orders_sr.json"

    def test_env_unset_is_not_required(self) -> None:
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(REQUIRE_TABLES_ENV, None)
            self.assertFalse(build_order_tables_are_required())

    def test_env_set_to_one_is_required(self) -> None:
        from unittest import mock
        with mock.patch.dict(os.environ, {REQUIRE_TABLES_ENV: "1"}):
            self.assertTrue(build_order_tables_are_required())

    def test_falsey_spellings_are_not_required(self) -> None:
        """`RC_REQUIRE_BUILD_ORDER_TABLES=0` must not arm this by accident."""
        from unittest import mock
        for value in ("0", "", "false", "FALSE", "no", "off", "  "):
            with mock.patch.dict(os.environ, {REQUIRE_TABLES_ENV: value}):
                self.assertFalse(
                    build_order_tables_are_required(),
                    f"{value!r} must read as not-required",
                )

    def test_absent_table_skips_when_not_required(self) -> None:
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(REQUIRE_TABLES_ENV, None)
            with self.assertRaises(unittest.SkipTest):
                require_shipped_table(self._missing(), "probe")

    def test_absent_table_FAILS_when_required(self) -> None:
        """The whole point: a declared-present table that is absent is a fail."""
        from unittest import mock
        with mock.patch.dict(os.environ, {REQUIRE_TABLES_ENV: "1"}):
            with self.assertRaises(AssertionError) as ctx:
                require_shipped_table(self._missing(), "probe")
        self.assertNotIsInstance(
            ctx.exception, unittest.SkipTest, "must not degrade back into a skip"
        )

    def test_present_table_is_returned(self) -> None:
        p = Path(tempfile.mkdtemp()) / "t.json"
        p.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(require_shipped_table(p, "probe"), p)

    def test_corrupt_table_FAILS_and_never_skips(self) -> None:
        """The conflation this whole gate exists to close.

        The production loader returns `{}` for a corrupt file exactly as it does
        for an absent one, so the old `if not payload: skipTest` could not tell
        them apart. Here a corrupt file must raise AssertionError - and must do
        so with the env flag UNSET, because corruption is never a capability
        question.
        """
        from unittest import mock
        p = Path(tempfile.mkdtemp()) / "t.json"
        p.write_text("{ this is not json", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(REQUIRE_TABLES_ENV, None)
            with self.assertRaises(AssertionError) as ctx:
                load_shipped_table(p, "probe")
        self.assertNotIsInstance(ctx.exception, unittest.SkipTest)
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_non_dict_table_FAILS(self) -> None:
        p = Path(tempfile.mkdtemp()) / "t.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(AssertionError):
            load_shipped_table(p, "probe")


if __name__ == "__main__":
    unittest.main()
