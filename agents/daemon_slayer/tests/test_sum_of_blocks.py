"""Phase 5.9.20 (s207, 2026-05-14) — sum-of-blocks block_index_overrides.

Closes the s205 + s206 carry-forward "sum-of-blocks bucket warranted soon
— 10+ candidates queued". Schema lift: ``block_index_overrides`` value
type widens from ``int`` to ``int | list[int]``. When a list is supplied
under the ``"indexed"`` strategy, the evaluated damage at each (clamped)
index is summed. Used to express "operator commits to landing every
component" cases where the realistic single-target damage is the sum
across multiple Meraki damage blocks.

Engine surface:
  * ``_select_blocks(... block_index: int | Sequence[int] = 0, ...)``
    — int path unchanged; list path loops + sums per-element.
  * ``_normalize_block_index_value(v)`` — rejects non-int, non-list[int]
    payloads with ValueError; preserves bool-as-int rejection.
  * ``get_block_index_for(champion_id) -> tuple[dict[str, int | list[int]], str]``
    — registry value type widens.
  * ``_resolve_block_index_overrides(champion_id, explicit) -> tuple[dict[str, int | list[int]], str]``
    — caller value type widens; same caller-wins-per-key merge.
  * Server ``_parse_block_index`` — accepts JSON arrays alongside ints.

Seed entries (4):
  * Camille W=[0, 1]      — Tactical Sweep base + Outer Cone Bonus
  * Malphite W=[2, 3]     — active cast + first empowered AA
  * Heimerdinger W=[0,1,1,1,1] — Initial + 4× Subsequent rockets
  * Katarina R=[1, 3]     — full Death Lotus single-target totals

Backward-compat: existing single-int entries unchanged; single-int callers
retain identical pre-s207 behavior. Existing tests in
``test_block_index_overrides.py`` continue to pass.
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


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _block(base: list[float]) -> DamageBlock:
    """Minimal damage-only fixture for unit tests — base scalar at every rank."""
    return DamageBlock(
        attribute="Test",
        attribute_kind="damage",
        base=tuple(base),
    )


def _ctx() -> AbilityContext:
    """Zero-stat context — _evaluate_block reads via getattr-with-default,
    but the dataclass needs all fields constructed."""
    return AbilityContext(
        base_ad=0.0, total_ad=0.0, bonus_ad=0.0, ap=0.0,
        caster_max_hp=0.0, caster_bonus_hp=0.0,
        caster_bonus_armor=0.0, caster_bonus_mr=0.0,
        caster_max_mp=0.0, caster_mp_regen_per_5=0.0,
        target_armor=80.0, target_mr=30.0,
        target_max_hp=2000.0, target_current_hp=2000.0,
        target_missing_hp=0.0, target_bonus_hp=0.0,
    )


# ─── _normalize_block_index_value ────────────────────────────────────────────


class NormalizeBlockIndexValueTests(unittest.TestCase):
    """Validator accepts int or list[int] only."""

    def test_int_returned_unchanged(self) -> None:
        self.assertEqual(_normalize_block_index_value(0), 0)
        self.assertEqual(_normalize_block_index_value(5), 5)

    def test_list_of_ints_returned_as_list(self) -> None:
        self.assertEqual(_normalize_block_index_value([0, 1]), [0, 1])
        self.assertEqual(_normalize_block_index_value([0, 1, 1, 1, 1]), [0, 1, 1, 1, 1])

    def test_empty_list_allowed(self) -> None:
        # Empty list returns empty list — _select_blocks handles it (returns 0.0).
        self.assertEqual(_normalize_block_index_value([]), [])

    def test_list_returns_defensive_copy(self) -> None:
        src = [0, 1]
        result = _normalize_block_index_value(src)
        self.assertIsNot(result, src)

    def test_bool_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value(True)

    def test_list_with_bool_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value([0, True])

    def test_string_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value("0")

    def test_float_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value(1.5)

    def test_none_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_block_index_value(None)


# ─── _select_blocks list-path semantics ──────────────────────────────────────


class SelectBlocksListTests(unittest.TestCase):
    """List-valued block_index sums per-element evaluated damage."""

    def setUp(self) -> None:
        # 3 damage blocks at rank 0: 100, 50, 25
        self.blocks = (
            _block([100.0]),
            _block([50.0]),
            _block([25.0]),
        )
        self.ctx = _ctx()

    def test_int_path_unchanged_block_0(self) -> None:
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=0),
            100.0,
        )

    def test_int_path_unchanged_block_2(self) -> None:
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=2),
            25.0,
        )

    def test_list_two_blocks(self) -> None:
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=[0, 1]),
            150.0,
        )

    def test_list_with_repetition(self) -> None:
        # [0, 1, 1, 1, 1] = 100 + 4×50 = 300 (Heimerdinger W shape)
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=[0, 1, 1, 1, 1]),
            300.0,
        )

    def test_list_clamps_overflow_per_element(self) -> None:
        # Index 5 clamps to last (idx 2 = 25); [0, 5] = 100 + 25 = 125
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=[0, 5]),
            125.0,
        )

    def test_list_clamps_negative_per_element(self) -> None:
        # Index -1 clamps to 0 (= 100); [-1, 1] = 100 + 50 = 150
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=[-1, 1]),
            150.0,
        )

    def test_empty_list_returns_zero(self) -> None:
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=[]),
            0.0,
        )

    def test_tuple_accepted_as_sequence(self) -> None:
        # Sequence type covers both list and tuple.
        self.assertEqual(
            _select_blocks(self.blocks, 0, self.ctx, "indexed", block_index=(0, 1)),
            150.0,
        )


# ─── Registry shape — 4 seed entries ─────────────────────────────────────────


class RegistrySeedEntriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_camille_W_is_two_block_sum(self) -> None:
        m, src = get_block_index_for("Camille")
        self.assertEqual(src, "champion")
        # Pre-s207 Q=2 still present (s195); W=[0,1] new.
        self.assertEqual(m.get("Q"), 2)
        self.assertEqual(m.get("W"), [0, 1])

    def test_malphite_W_is_two_block_sum(self) -> None:
        m, src = get_block_index_for("Malphite")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("W"), [2, 3])

    def test_heimerdinger_W_is_initial_plus_four_subsequent(self) -> None:
        m, src = get_block_index_for("Heimerdinger")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("W"), [0, 1, 1, 1, 1])

    def test_katarina_R_is_physical_plus_magic_max(self) -> None:
        m, src = get_block_index_for("Katarina")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("R"), [1, 3])


# ─── _resolve_block_index_overrides preserves list values ────────────────────


class ResolveBlockIndexListMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_caller_int_wins_over_registry_list(self) -> None:
        # Caller passes Camille W=0 (single block) — wins over registry [0,1].
        merged, src = _resolve_block_index_overrides("Camille", {"W": 0})
        self.assertEqual(src, "override")
        self.assertEqual(merged.get("W"), 0)

    def test_caller_list_wins_over_registry_int(self) -> None:
        # Veigar registry has R=1; caller passes R=[0,1] — wins.
        merged, src = _resolve_block_index_overrides("Veigar", {"R": [0, 1]})
        self.assertEqual(src, "override")
        self.assertEqual(merged.get("R"), [0, 1])

    def test_registry_list_preserved_when_no_caller_override(self) -> None:
        merged, src = _resolve_block_index_overrides("Heimerdinger", None)
        self.assertEqual(src, "champion")
        self.assertEqual(merged.get("W"), [0, 1, 1, 1, 1])

    def test_caller_can_add_list_for_unmapped_champion(self) -> None:
        # Yasuo not in registry; caller passes a list-valued override.
        merged, src = _resolve_block_index_overrides("Yasuo", {"Q": [0, 1]})
        self.assertEqual(src, "override")
        self.assertEqual(merged.get("Q"), [0, 1])


# ─── compute_ability_dps integration — 4 seed entries ────────────────────────


class AbilityDpsSumOfBlocksTests(unittest.TestCase):
    """The 4 seed entries deliver canonical single-target totals."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _spell(self, champion: str, key: str, *, level: int = 11):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=[],
            mode="SR", target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def _spell_forced(self, champion: str, key: str, forced_block: int, *, level: int = 11):
        """Force a single block_index for A/B comparison."""
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=[],
            mode="SR", target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
            block_index_overrides={key: forced_block},
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_camille_W_sum_exceeds_block_0_alone(self) -> None:
        s_sum = self._spell("Camille", "W")
        s_forced = self._spell_forced("Camille", "W", 0)
        # Sum of [0, 1] should be strictly greater than block 0 alone.
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_camille_W_sum_matches_explicit_arithmetic(self) -> None:
        s_sum = self._spell("Camille", "W")
        s_block0 = self._spell_forced("Camille", "W", 0)
        s_block1 = self._spell_forced("Camille", "W", 1)
        # raw sum equals individual blocks added.
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_block0.raw_damage_per_cast + s_block1.raw_damage_per_cast,
            places=4,
        )

    def test_malphite_W_sum_exceeds_block_2_alone(self) -> None:
        s_sum = self._spell("Malphite", "W")
        s_forced = self._spell_forced("Malphite", "W", 2)
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_malphite_W_sum_matches_explicit_arithmetic(self) -> None:
        s_sum = self._spell("Malphite", "W")
        s_block2 = self._spell_forced("Malphite", "W", 2)
        s_block3 = self._spell_forced("Malphite", "W", 3)
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_block2.raw_damage_per_cast + s_block3.raw_damage_per_cast,
            places=4,
        )

    def test_heimerdinger_W_sum_is_5x_pattern(self) -> None:
        s_sum = self._spell("Heimerdinger", "W")
        s_block0 = self._spell_forced("Heimerdinger", "W", 0)
        s_block1 = self._spell_forced("Heimerdinger", "W", 1)
        # [0, 1, 1, 1, 1] = block 0 + 4× block 1
        expected = s_block0.raw_damage_per_cast + 4 * s_block1.raw_damage_per_cast
        self.assertAlmostEqual(s_sum.raw_damage_per_cast, expected, places=4)

    def test_heimerdinger_W_sum_strictly_exceeds_either_alone(self) -> None:
        s_sum = self._spell("Heimerdinger", "W")
        s_block0 = self._spell_forced("Heimerdinger", "W", 0)
        s_block1 = self._spell_forced("Heimerdinger", "W", 1)
        self.assertGreater(s_sum.raw_damage_per_cast, s_block0.raw_damage_per_cast)
        self.assertGreater(s_sum.raw_damage_per_cast, s_block1.raw_damage_per_cast)

    def test_katarina_R_sum_combines_physical_and_magic(self) -> None:
        s_sum = self._spell("Katarina", "R")
        s_block1 = self._spell_forced("Katarina", "R", 1)
        s_block3 = self._spell_forced("Katarina", "R", 3)
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_block1.raw_damage_per_cast + s_block3.raw_damage_per_cast,
            places=4,
        )


# ─── compute_burst_damage integration ────────────────────────────────────────


class BurstSumOfBlocksTests(unittest.TestCase):
    """ComboCast rows for sum-of-blocks entries reflect summed damage."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _w_cast(self, champion: str, level: int = 11, **kwargs):
        out = compute_burst_damage(
            self.snap, champion, level=level, item_ids=[],
            mode="SR", target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0, **kwargs,
        )
        return next(
            (c for c in out.per_cast if c.is_ability and c.ability_key == "W"),
            None,
        )

    def test_heimerdinger_W_burst_uses_summed_blocks(self) -> None:
        c_sum = self._w_cast("Heimerdinger")
        c_forced0 = self._w_cast("Heimerdinger", block_index_overrides={"W": 0})
        # Sum should be strictly larger than block 0 alone.
        self.assertGreater(c_sum.raw_damage, c_forced0.raw_damage)

    def test_camille_W_burst_uses_summed_blocks(self) -> None:
        c_sum = self._w_cast("Camille")
        c_forced0 = self._w_cast("Camille", block_index_overrides={"W": 0})
        self.assertGreater(c_sum.raw_damage, c_forced0.raw_damage)

    def test_malphite_W_burst_uses_summed_blocks(self) -> None:
        c_sum = self._w_cast("Malphite")
        c_forced2 = self._w_cast("Malphite", block_index_overrides={"W": 2})
        self.assertGreater(c_sum.raw_damage, c_forced2.raw_damage)


# ─── Backward-compat — single-int registry entries unchanged ─────────────────


class BackwardCompatIntEntriesTests(unittest.TestCase):
    """Existing int-valued entries in the registry still resolve to int."""

    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_veigar_R_still_int(self) -> None:
        # s191 seed, never touched — should still be int.
        m, _ = get_block_index_for("Veigar")
        self.assertEqual(m.get("R"), 1)
        self.assertIsInstance(m.get("R"), int)

    def test_cassiopeia_E_converted_to_conditional_s230(self) -> None:
        # Was an int exemplar through s207; s230 Phase 5.9.30 converted
        # Cassi E to a conditional dict (default=1 == the s191 int —
        # provable Part-1 no-op). Veigar R remains this class's
        # untouched-int exemplar.
        m, _ = get_block_index_for("Cassiopeia")
        self.assertEqual(m.get("E"), {"default": 1, "target_no_setup": 0})

    def test_camille_Q_still_int_alongside_new_W_list(self) -> None:
        # Q=2 (s195) preserved as int; W=[0,1] (s207) added as list.
        m, _ = get_block_index_for("Camille")
        self.assertEqual(m.get("Q"), 2)
        self.assertIsInstance(m.get("Q"), int)
        self.assertIsInstance(m.get("W"), list)


# ─── Live server route checks ────────────────────────────────────────────────


class ServerRouteSumOfBlocksTests(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8893"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            urlopen(f"{cls.BASE_URL}/health", timeout=2).read()
        except Exception as e:  # pragma: no cover — env-dependent
            raise unittest.SkipTest(f"DS server unavailable: {e}")

    def _ability_dps(self, champion: str, **extra) -> dict:
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
        return json.loads(urlopen(req, timeout=10).read())

    def _spell(self, champion: str, key: str, **extra):
        out = self._ability_dps(champion, **extra)
        spells = out.get("per_spell", [])
        return next((s for s in spells if s["key"] == key), None)

    def test_camille_W_via_route_uses_summed_blocks(self) -> None:
        s_sum = self._spell("Camille", "W")
        s_forced = self._spell("Camille", "W", block_index={"W": 0})
        self.assertGreater(s_sum["raw_damage_per_cast"], s_forced["raw_damage_per_cast"])

    def test_heimerdinger_W_via_route_uses_summed_blocks(self) -> None:
        s_sum = self._spell("Heimerdinger", "W")
        s_forced = self._spell("Heimerdinger", "W", block_index={"W": 0})
        self.assertGreater(s_sum["raw_damage_per_cast"], s_forced["raw_damage_per_cast"])

    def test_katarina_R_via_route_uses_summed_blocks(self) -> None:
        s_sum = self._spell("Katarina", "R")
        s_forced = self._spell("Katarina", "R", block_index={"R": 1})
        self.assertGreater(s_sum["raw_damage_per_cast"], s_forced["raw_damage_per_cast"])

    def test_caller_can_pass_list_via_route(self) -> None:
        # Yasuo not in registry; caller-supplied list works through the route.
        s = self._spell("Yasuo", "Q", block_index={"Q": [0, 0]})
        self.assertIsNotNone(s)
        # Forced single-block reference for comparison.
        s_single = self._spell("Yasuo", "Q", block_index={"Q": 0})
        # [0, 0] = block 0 + block 0 = 2× block 0.
        self.assertAlmostEqual(
            s["raw_damage_per_cast"],
            2 * s_single["raw_damage_per_cast"],
            places=4,
        )

    def test_route_rejects_malformed_block_index_silently(self) -> None:
        # Garbage value is skipped per defensive policy — route still
        # returns a valid response (using registry default).
        s = self._spell("Camille", "W", block_index={"W": "not-an-int"})
        # Falls through to registry [0, 1] sum, NOT the default int 0.
        s_default = self._spell("Camille", "W")
        self.assertEqual(s["raw_damage_per_cast"], s_default["raw_damage_per_cast"])


if __name__ == "__main__":
    unittest.main()
