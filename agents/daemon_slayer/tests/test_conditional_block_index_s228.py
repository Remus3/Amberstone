"""Phase 5.9.28 (s228, 2026-05-16) - conditional-target-state block_index
schema lift (operator-signed-off option B; Part 1).

Closes the long-deferred "conditional-target-state schema lift" carry-forward
that every prior block_index batch (s191-s227) parked. Operator chose option
B (the multi-session lift): this is **Part 1** - schema + validator +
resolver + 3 flagship seeds. Part 2 (live liveclient HP%/CC predicate
plumbing into the ranking call) is a follow-up session.

Schema lift: ``block_index`` value type widens from ``int | list[int]``
(s207) to ALSO ``dict[str, int | list[int]]`` - a conditional mapping a
target-state condition -> block. ``"default"`` is REQUIRED and is the
operator-commits / canonical-amped branch (the ranking assumption - same
model s191 established). Every other key must be in the CLOSED vocabulary
``_BLOCK_INDEX_CONDITIONS`` and selects a *downgrade* (never more optimistic
than ``"default"``). An unknown key is a registry typo and MUST raise.

Part-1 resolver contract: ``_select_blocks`` resolves any conditional dict
to its ``"default"`` branch UNCONDITIONALLY - byte-identical to the
equivalent unconditional int/list entry (zero regression). Live
target-state predicate evaluation is Part 2.

Engine surface:
  * ``_BLOCK_INDEX_DEFAULT_KEY`` / ``_BLOCK_INDEX_CONDITIONS`` - the
    reserved key + closed condition vocabulary.
  * ``_normalize_block_index_value(v)`` - also accepts a conditional dict;
    rejects missing-``default`` / unknown-condition / nested-dict; int /
    list / bool / str behavior unchanged.
  * ``_select_blocks(... block_index: int | Sequence[int] | dict ...)`` -
    dict path resolves to ``"default"`` then proceeds as int/list.
  * Server ``_parse_block_index`` - accepts a well-formed conditional
    JSON object; skips malformed (defensive, untrusted body).

Flagship seeds (3) - all CONVERSIONS of already-shipped unconditional
entries, so Part 1 is provably no-op vs s204/s204/s223:
  * Zoe     E = {"default": 2, "target_no_setup": 0}   (sleep 2x - s204 E:2)
  * Evelynn Q = {"default": 5, "target_no_setup": 0}   (charm triple-spike
                total - s204 Q:5; sibling R:1 preserved)
  * Kindred E = {"default": 1, "target_full_hp": 0} (7.5%-vs-5% missing-HP
                execute - s223 E:1)
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import (
    AbilityForm,
    DamageBlock,
    reset_default_cache,
)
from agents.daemon_slayer.ability_dps import (
    _BLOCK_INDEX_CONDITIONS,
    _BLOCK_INDEX_DEFAULT_KEY,
    AbilityContext,
    _normalize_block_index_value,
    _resolve_block_index_overrides,
    _select_blocks,
    compute_ability_dps,
    get_block_index_for,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.server import _parse_block_index


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _block(base: list[float]) -> DamageBlock:
    return DamageBlock(attribute="Test", attribute_kind="damage", base=tuple(base))


def _ctx() -> AbilityContext:
    return AbilityContext(
        base_ad=0.0, total_ad=0.0, bonus_ad=0.0, ap=0.0,
        caster_max_hp=0.0, caster_bonus_hp=0.0,
        caster_bonus_armor=0.0, caster_bonus_mr=0.0,
        caster_max_mp=0.0, caster_mp_regen_per_5=0.0,
        target_armor=80.0, target_mr=30.0,
        target_max_hp=2000.0, target_current_hp=2000.0,
        target_missing_hp=0.0, target_bonus_hp=0.0,
    )


# --- closed condition vocabulary ---------------------------------------------


class BlockIndexConditionVocabTests(unittest.TestCase):
    """The condition vocabulary is closed + exactly the documented set."""

    def test_default_key_literal(self) -> None:
        self.assertEqual(_BLOCK_INDEX_DEFAULT_KEY, "default")

    def test_conditions_are_exactly_the_part1_closed_set(self) -> None:
        self.assertEqual(
            _BLOCK_INDEX_CONDITIONS,
            frozenset({"target_full_hp", "target_no_setup"}),
        )

    def test_default_is_not_a_condition(self) -> None:
        # "default" is the reserved fallback, never a condition predicate.
        self.assertNotIn(_BLOCK_INDEX_DEFAULT_KEY, _BLOCK_INDEX_CONDITIONS)


# --- _normalize_block_index_value - conditional dict -------------------------


class NormalizeConditionalTests(unittest.TestCase):
    """Validator accepts a well-formed conditional dict; rejects bad shapes.

    int / list / bool / str behavior is unchanged from s207 (regression
    guard - the lift is purely additive)."""

    # backward-compat (s207 + s191) - unchanged
    def test_int_unchanged(self) -> None:
        self.assertEqual(_normalize_block_index_value(0), 0)
        self.assertEqual(_normalize_block_index_value(5), 5)

    def test_list_unchanged(self) -> None:
        self.assertEqual(_normalize_block_index_value([0, 1, 1]), [0, 1, 1])

    def test_bool_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value(True)

    def test_string_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value("0")

    # conditional dict - accepted shapes
    def test_dict_int_values_accepted(self) -> None:
        self.assertEqual(
            _normalize_block_index_value({"default": 2, "target_no_setup": 0}),
            {"default": 2, "target_no_setup": 0},
        )

    def test_dict_list_value_accepted(self) -> None:
        # default may itself be a sum-of-blocks list (s207 nested in s228).
        self.assertEqual(
            _normalize_block_index_value({"default": [1, 3], "target_full_hp": 0}),
            {"default": [1, 3], "target_full_hp": 0},
        )

    def test_dict_default_only_accepted(self) -> None:
        self.assertEqual(
            _normalize_block_index_value({"default": 4}), {"default": 4}
        )

    def test_dict_all_conditions_accepted(self) -> None:
        v = {"default": 2, "target_no_setup": 0, "target_full_hp": 1}
        self.assertEqual(_normalize_block_index_value(v), v)

    # conditional dict - rejected shapes
    def test_dict_missing_default_rejected(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _normalize_block_index_value({"target_no_setup": 0})
        self.assertIn("default", str(cm.exception))

    def test_dict_unknown_condition_rejected(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _normalize_block_index_value({"default": 0, "bogus_cond": 1})
        self.assertIn("unknown block_index condition", str(cm.exception))

    def test_dict_nested_conditional_rejected(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _normalize_block_index_value({"default": {"default": 0}})
        self.assertIn("nested", str(cm.exception))

    def test_dict_bool_nested_value_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value({"default": True})

    def test_dict_string_nested_value_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value({"default": "0", "target_no_setup": 1})


# --- _select_blocks - Part-1 dict resolution (default branch only) -----------


class SelectBlocksConditionalTests(unittest.TestCase):
    """Part 1: a conditional dict resolves to its ``"default"`` branch,
    byte-identical to the equivalent unconditional int/list call.
    Condition keys are PRESENT but IGNORED until Part 2."""

    def setUp(self) -> None:
        # rank-0 damage blocks: 100, 50, 25
        self.blocks = (_block([100.0]), _block([50.0]), _block([25.0]))
        self.ctx = _ctx()

    def _sel(self, bi):
        return _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=bi)

    def test_dict_resolves_to_default_int(self) -> None:
        self.assertEqual(
            self._sel({"default": 2, "target_no_setup": 0}),
            self._sel(2),  # == forced block 2 (= 25.0)
        )
        self.assertEqual(self._sel({"default": 2, "target_no_setup": 0}), 25.0)

    def test_dict_condition_branches_ignored_part1(self) -> None:
        # target_no_setup=0 would be block 0 (=100) IF predicates fired; in
        # Part 1 the default (block 1 = 50) is used regardless.
        self.assertEqual(self._sel({"default": 1, "target_no_setup": 0}), 50.0)

    def test_dict_default_list_sums(self) -> None:
        # default may be a sum-of-blocks list (s207 semantics preserved
        # inside a conditional): [0, 1] = 100 + 50 = 150.
        self.assertEqual(self._sel({"default": [0, 1], "target_full_hp": 0}), 150.0)

    def test_dict_default_clamps_like_int(self) -> None:
        # out-of-range default clamps to last block, same as the int path.
        self.assertEqual(self._sel({"default": 9}), self._sel(9))
        self.assertEqual(self._sel({"default": 9}), 25.0)

    def test_int_and_list_paths_byte_identical(self) -> None:
        # Regression guard: non-dict block_index unchanged by s228.
        self.assertEqual(self._sel(0), 100.0)
        self.assertEqual(self._sel([0, 2]), 125.0)


# --- _resolve_block_index_overrides - conditional merge ----------------------


class ResolveConditionalMergeTests(unittest.TestCase):
    """Caller conditional dict wins per-key; registry conditional used when
    caller passes None; source field correct."""

    def setUp(self) -> None:
        reset_block_index_cache()

    def test_registry_conditional_used_when_no_caller(self) -> None:
        merged, source = _resolve_block_index_overrides("Zoe", None)
        self.assertEqual(merged.get("E"), {"default": 2, "target_no_setup": 0})
        self.assertEqual(source, "champion")

    def test_caller_conditional_wins_per_key(self) -> None:
        merged, source = _resolve_block_index_overrides(
            "Zoe", {"E": {"default": 0}}
        )
        self.assertEqual(merged.get("E"), {"default": 0})
        self.assertEqual(source, "override")

    def test_caller_int_wins_over_registry_conditional(self) -> None:
        merged, source = _resolve_block_index_overrides("Zoe", {"E": 1})
        self.assertEqual(merged.get("E"), 1)
        # registry sibling keys still fill the gaps
        self.assertEqual(merged.get("Q"), 1)
        self.assertEqual(source, "override")

    def test_caller_can_add_conditional_for_unmapped_champion(self) -> None:
        merged, source = _resolve_block_index_overrides(
            "Yasuo", {"Q": {"default": 1, "target_full_hp": 0}}
        )
        self.assertEqual(merged.get("Q"), {"default": 1, "target_full_hp": 0})
        self.assertEqual(source, "override")


# --- registry seed entries (3 flagship conversions) --------------------------


class RegistrySeedEntriesS228Tests(unittest.TestCase):
    """The 3 flagship seeds load as the expected conditional dicts; their
    non-converted sibling keys stay int (no collateral schema change)."""

    def setUp(self) -> None:
        reset_block_index_cache()

    def test_zoe_E_is_conditional_sleep(self) -> None:
        m, src = get_block_index_for("Zoe")
        self.assertEqual(m["E"], {"default": 2, "target_no_setup": 0})
        # siblings preserved as plain ints (s195/s201 entries)
        self.assertEqual(m["Q"], 1)
        self.assertEqual(m["W"], 1)
        self.assertEqual(src, "champion")

    def test_evelynn_Q_is_conditional_charm_R_preserved(self) -> None:
        m, _ = get_block_index_for("Evelynn")
        # s228's durable property: Q is the charm target_no_setup
        # conditional. The R sibling was a plain int 1 at s228; s231
        # Phase 5.9.31 converted it to a target_full_hp execute
        # conditional (default=1 == that s204 int - provable Part-1
        # no-op, so s228's "R unchanged in effect" intent still holds).
        self.assertEqual(m["Q"], {"default": 5, "target_no_setup": 0})
        self.assertEqual(m["R"], {"default": 1, "target_full_hp": 0})

    def test_kindred_E_is_conditional_execute(self) -> None:
        m, _ = get_block_index_for("Kindred")
        self.assertEqual(m["E"], {"default": 1, "target_full_hp": 0})

    def test_seed_count_is_three(self) -> None:
        # s228's durable property: each of the THREE s228 seed keys
        # (Zoe E, Evelynn Q, Kindred E) is a conditional dict. The total
        # dict-count across these champions grows as later sessions add
        # more conditionals (s231 made Evelynn R conditional too), so
        # pin the specific s228 seed keys, not a now-stale grand total.
        zoe, _ = get_block_index_for("Zoe")
        eve, _ = get_block_index_for("Evelynn")
        kin, _ = get_block_index_for("Kindred")
        self.assertIsInstance(zoe["E"], dict)
        self.assertIsInstance(eve["Q"], dict)
        self.assertIsInstance(kin["E"], dict)


# --- compute_ability_dps - Part-1 zero-regression invariant ------------------


class AbilityDpsPart1InvariantTests(unittest.TestCase):
    """Each seed's registry conditional resolves byte-identical to the
    equivalent forced ``default`` int - proving the schema lift adds zero
    numeric change in Part 1 (the whole point of the phased ship)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _spell(self, champ, key, **extra):
        out = compute_ability_dps(
            self.snap, champ, level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            **extra,
        )
        return next((s for s in out.per_spell if s.key == key), None), out

    def test_zoe_E_registry_equals_forced_default_2(self) -> None:
        reg, ro = self._spell("Zoe", "E")
        forced, fo = self._spell("Zoe", "E", block_index_overrides={"E": 2})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9
        )
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9
        )

    def test_zoe_E_default_is_2x_block_0(self) -> None:
        # Verified vs Meraki 16.10.1: DMGIDX[2] = exactly 2x DMGIDX[0].
        reg, _ = self._spell("Zoe", "E")
        b0, _ = self._spell("Zoe", "E", block_index_overrides={"E": 0})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, 2.0 * b0.raw_damage_per_cast, places=4
        )

    def test_evelynn_Q_registry_equals_forced_default_5(self) -> None:
        reg, ro = self._spell("Evelynn", "Q")
        forced, fo = self._spell("Evelynn", "Q", block_index_overrides={"Q": 5})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9
        )
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9
        )

    def test_kindred_E_registry_equals_forced_default_1(self) -> None:
        reg, ro = self._spell("Kindred", "E")
        forced, fo = self._spell("Kindred", "E", block_index_overrides={"E": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9
        )
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9
        )

    def test_kindred_E_seed_is_load_bearing_at_low_hp(self) -> None:
        # Kindred E blocks differ ONLY in target_missing_hp_pct (DMGIDX[1]
        # 7.5%/stack vs DMGIDX[0] 5%/stack) - identical base + bAD. At full
        # HP (Part-1 default ctx) the missing-HP term is 0 so default(1) ==
        # block 0 (an honest Part-1 no-op). The seed becomes load-bearing
        # only against a missing-HP target - which is exactly the signal
        # Part 2's live HP% plumbing will carry. Prove it at 30% HP.
        def spell(**ov):
            out = compute_ability_dps(
                self.snap, "Kindred", level=11, item_ids=[], mode="SR",
                target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
                target_current_hp_pct=0.30, **ov,
            )
            return next((s for s in out.per_spell if s.key == "E"), None)
        reg = spell()
        b0 = spell(block_index_overrides={"E": 0})
        self.assertGreater(reg.raw_damage_per_cast, b0.raw_damage_per_cast)
        # full-HP honesty: default(1) == block 0 when nothing is missing.
        full_reg, _ = self._spell("Kindred", "E")
        full_b0, _ = self._spell("Kindred", "E", block_index_overrides={"E": 0})
        self.assertAlmostEqual(
            full_reg.raw_damage_per_cast, full_b0.raw_damage_per_cast, places=6
        )

    def test_block_index_source_is_champion_for_seeds(self) -> None:
        _, out = self._spell("Zoe", "E")
        self.assertEqual(out.block_index_source, "champion")
        self.assertEqual(out.block_index_resolved["E"], {"default": 2, "target_no_setup": 0})


# --- compute_burst_damage - conditional resolves in the combo walker ---------


class BurstConditionalTests(unittest.TestCase):
    """The burst combo walker resolves a conditional entry to its default
    branch identically to the int form (Evelynn Q is in the assassin
    combo template)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _burst_total(self, champ, **extra) -> float:
        out = compute_burst_damage(
            self.snap, champ, level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            target_bonus_hp=0.0, **extra,
        )
        return out.total_burst_damage

    def test_evelynn_burst_registry_equals_forced_default(self) -> None:
        reg = self._burst_total("Evelynn")
        forced = self._burst_total(
            "Evelynn", block_index_overrides={"Q": 5, "R": 1}
        )
        self.assertAlmostEqual(reg, forced, places=6)

    def test_zoe_burst_registry_equals_forced_default(self) -> None:
        reg = self._burst_total("Zoe")
        forced = self._burst_total(
            "Zoe", block_index_overrides={"E": 2, "Q": 1, "W": 1}
        )
        self.assertAlmostEqual(reg, forced, places=6)


# --- server _parse_block_index - conditional decoder (pure unit) -------------


class ParseBlockIndexConditionalTests(unittest.TestCase):
    """The body decoder accepts well-formed conditional objects and skips
    malformed ones defensively (untrusted input -> registry fallback, no
    500). int / list decoding unchanged."""

    def test_int_and_list_unchanged(self) -> None:
        self.assertEqual(
            _parse_block_index({"block_index": {"E": 1, "W": [0, 1]}}),
            {"E": 1, "W": [0, 1]},
        )

    def test_well_formed_conditional_accepted(self) -> None:
        out = _parse_block_index(
            {"block_index": {"e": {"default": 2, "target_no_setup": 0}}}
        )
        self.assertEqual(out, {"E": {"default": 2, "target_no_setup": 0}})

    def test_conditional_list_default_accepted(self) -> None:
        out = _parse_block_index(
            {"block_index": {"R": {"default": [1, 3], "target_full_hp": 0}}}
        )
        self.assertEqual(out, {"R": {"default": [1, 3], "target_full_hp": 0}})

    def test_missing_default_skipped(self) -> None:
        # Skipped entry -> empty map (engine falls back to registry).
        self.assertEqual(
            _parse_block_index({"block_index": {"E": {"target_no_setup": 0}}}), {}
        )

    def test_unknown_condition_skipped(self) -> None:
        self.assertEqual(
            _parse_block_index({"block_index": {"E": {"default": 0, "x": 1}}}),
            {},
        )

    def test_bad_nested_value_skipped(self) -> None:
        self.assertEqual(
            _parse_block_index(
                {"block_index": {"E": {"default": "two", "target_no_setup": 0}}}
            ),
            {},
        )

    def test_mixed_valid_and_invalid(self) -> None:
        # Valid int kept; malformed conditional dropped.
        out = _parse_block_index(
            {"block_index": {"Q": 1, "E": {"no_default": 0}}}
        )
        self.assertEqual(out, {"Q": 1})

    def test_absent_field_returns_none(self) -> None:
        self.assertIsNone(_parse_block_index({}))


# --- backward-compat: pre-s228 int / list entries unchanged ------------------


class BackwardCompatPreS228Tests(unittest.TestCase):
    """A representative s191 int entry + s207 list entry are byte-identical
    post-s228 (the lift is additive only)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()
        reset_block_index_cache()

    def test_cassiopeia_E_s230_conditional_part1_preserves_s191(self) -> None:
        # s228 left Cassi E a plain int (the irregular Meraki array was
        # deferred). s230 Phase 5.9.30 converted it to a conditional
        # ({default:1, target_no_setup:0}); this evolution guard now
        # asserts the new shape AND that Part-1 resolves byte-identical
        # to the s191 int 1 (the conversion is a provable no-op).
        m, _ = get_block_index_for("Cassiopeia")
        self.assertEqual(m["E"], {"default": 1, "target_no_setup": 0})
        reg = next(
            s for s in compute_ability_dps(
                self.snap, "Cassiopeia", level=11, mode="SR",
                target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            ).per_spell if s.key == "E"
        )
        forced1 = next(
            s for s in compute_ability_dps(
                self.snap, "Cassiopeia", level=11, mode="SR",
                target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
                block_index_overrides={"E": 1, "W": 1},
            ).per_spell if s.key == "E"
        )
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced1.raw_damage_per_cast, places=9)

    def test_camille_W_still_list(self) -> None:
        m, _ = get_block_index_for("Camille")
        self.assertEqual(m["W"], [0, 1])

    def test_cassiopeia_E_ability_dps_unchanged(self) -> None:
        out = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        e = next((s for s in out.per_spell if s.key == "E"), None)
        forced = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            block_index_overrides={"E": 1},
        )
        ef = next((s for s in forced.per_spell if s.key == "E"), None)
        self.assertAlmostEqual(
            e.raw_damage_per_cast, ef.raw_damage_per_cast, places=9
        )


# --- live server route (skips if DS server down) -----------------------------


class ServerRouteConditionalS228Tests(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8860"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            urlopen(f"{cls.BASE_URL}/health", timeout=2).read()
        except Exception as e:  # pragma: no cover - env-dependent
            raise unittest.SkipTest(f"DS server unavailable: {e}")

    def _spell(self, champion: str, key: str, **extra):
        body = {
            "champion": champion, "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30, "target_max_hp": 2000,
        }
        body.update(extra)
        req = Request(
            f"{self.BASE_URL}/ability-dps",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        out = json.loads(urlopen(req, timeout=10).read())
        return next((s for s in out.get("per_spell", []) if s["key"] == key), None)

    def test_zoe_E_registry_equals_forced_default_via_route(self) -> None:
        reg = self._spell("Zoe", "E")
        forced = self._spell("Zoe", "E", block_index={"E": 2})
        self.assertAlmostEqual(
            reg["raw_damage_per_cast"], forced["raw_damage_per_cast"], places=4
        )

    def test_caller_conditional_dict_via_route(self) -> None:
        # Body-supplied conditional resolves to its default branch.
        s = self._spell(
            "Zoe", "E", block_index={"E": {"default": 0, "target_no_setup": 2}}
        )
        s0 = self._spell("Zoe", "E", block_index={"E": 0})
        self.assertAlmostEqual(
            s["raw_damage_per_cast"], s0["raw_damage_per_cast"], places=4
        )

    def test_malformed_conditional_falls_back_to_registry(self) -> None:
        # Missing "default" -> decoder skips -> engine uses registry (E:2).
        s_bad = self._spell("Zoe", "E", block_index={"E": {"target_no_setup": 0}})
        s_reg = self._spell("Zoe", "E")
        self.assertAlmostEqual(
            s_bad["raw_damage_per_cast"], s_reg["raw_damage_per_cast"], places=4
        )


# --- ENGINE_VERSION pin ------------------------------------------------------


class EngineVersionS228Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer

        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.273.0")


if __name__ == "__main__":
    unittest.main()
