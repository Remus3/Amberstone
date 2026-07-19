"""RM-39 / RM-43 - apply_ad_axis_ability_damage seam: the MISSING ability
term on the AD branch of the BRUISER (hybrid) scorer.

Adjudicated in docs/specs/SPEC_rm39_rm43_ability_haste.md section 2.2
(VERDICT: BUILD_DIFFERENT_THING). The named mechanism in the original work
item - ability haste - is inert for these champions; the real defect is that
92 of 173 champions resolve ``_damage_axis`` to "ad" and are then scored on
auto-attack DPS ALONE. All three ``_ability_damage`` call sites
(``compute_hybrid`` + the ranker baseline + the ranker per-candidate) gate on
the "ap" branch, and ``dps.py:34`` says the AD branch omits ability damage by
design. Their real ability DPS is computed nowhere.

The seam is DEFAULT-OFF. When ON, the AD branch becomes
``weighted_dps + _physical_ability_damage(...)``. The AP branch is untouched
on BOTH paths.

MANDATORY DAMAGE-TYPE GUARD - PHYSICAL only. Per the spec, an UNFILTERED
ability term promotes Liandry's Torment to #1 for Aatrox, importing AP burn
items onto an AD bruiser. ``_physical_ability_damage`` therefore sums only
per-spell rows whose ``damage_type`` normalizes to "PHYSICAL" under the
canonical ``ability_dps.py:371`` idiom ``(damage_type or "MAGIC").upper()``,
so a None damage_type falls back to MAGIC and is EXCLUDED. TRUE and MAGIC are
excluded in this first slice by CLAUDE.md engine convention (tightest matching
set first; widen only on test evidence).

Ground truth anchors (probed against the live snapshot this session, ENGINE
1.221.0 / patch 16.14.1, level 13, items=[], target 100/60/2500/1200):
  * Aatrox   attack 8 magic 3 -> axis "ad"; Q + W PHYSICAL, E + R None.
    total_ability_dps 17.356 == physical-only 17.356.
  * Ambessa  attack 9 magic 0 -> axis "ad"; all four spells PHYSICAL.
    total_ability_dps 16.227 == physical-only 16.227.
  * Darius   attack 9 magic 1 -> axis "ad"; Q + W PHYSICAL, E None,
    R "TRUE" (Noxian Guillotine). total 9.878 > physical-only 8.050 - the
    REAL-DATA proof that the filter drops a non-PHYSICAL row.
  * Veigar   attack 2 magic 10 -> axis "ap"; every spell MAGIC ->
    physical-only 0.0. AP-branch control.

Numeric expectations below are recomputed from the engine at assert time
rather than pinned as literals (no data-fragile cross-item comparisons).

NO ENGINE_VERSION pin here - the orchestrator owns the bump.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from agents.daemon_slayer import burst, dps, ehp, hybrid, rank, server
from agents.daemon_slayer.ability_dps import (
    AbilityDpsResult,
    AbilitySpellDps,
    compute_ability_dps,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

_FLAG = "apply_ad_axis_ability_damage"

# AD-axis anchors named by the work item, plus Darius for the TRUE-damage
# filter proof. Veigar is the AP-branch control.
_AATROX = "Aatrox"
_AMBESSA = "Ambessa"
_DARIUS = "Darius"
_VEIGAR = "Veigar"
_LEVEL = 13

# The ORIGINAL RM-39 sweep target. The route defaults are all-zero, and a
# 0-HP / 0-resist target is a known probe trap (it sinks %-max-HP on-hit items
# ~50 places) - see reference_ds_probe_zero_target_defaults.
_TARGET_KW = {
    "target_armor": 100.0,
    "target_mr": 60.0,
    "target_max_hp": 2500.0,
    "target_bonus_hp": 1200.0,
}

# A small controlled candidate pool for the ranker tests.
_STERAKS = "3053"    # Sterak's Gage
_WARMOG = "3083"     # Warmog's Armor
_BOTRK = "3153"      # Blade of the Ruined King


def _spell(key: str, damage_type, dps_value: float) -> AbilitySpellDps:
    """Minimal per-spell row carrying only the two fields the filter reads."""
    return AbilitySpellDps(
        key=key,
        form_name=f"stub {key}",
        form_index=0,
        rank=1,
        cooldown=10.0,
        cost=0.0,
        damage_type=damage_type,
        resource=None,
        raw_damage_per_cast=0.0,
        post_mode_damage_per_cast=0.0,
        post_mitigation_damage_per_cast=0.0,
        casts_per_sec=0.1,
        casts_per_sec_source="measured",
        mana_uptime_factor=1.0,
        dps=dps_value,
    )


def _result(rows) -> AbilityDpsResult:
    """Stub AbilityDpsResult whose total DELIBERATELY disagrees with the
    physical-only sum, so a test that accidentally reads total_ability_dps
    cannot pass."""
    return AbilityDpsResult(
        champion_id="0",
        champion_name="Stub",
        level=_LEVEL,
        item_ids=(),
        mode="SR",
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=0.0,
        target_bonus_hp=0.0,
        mode_multiplier=1.0,
        per_spell=tuple(rows),
        total_ability_dps=999_999.0,
        primary_scaling="AD",
        max_priority=("Q", "W", "E"),
        block_strategy="stub",
    )


class HelperFilterTests(unittest.TestCase):
    """_physical_ability_damage sums PHYSICAL rows ONLY.

    Stubs ``hybrid.compute_ability_dps`` (bound by name at hybrid.py:43, so
    the module attribute is the live call target) and asserts on rows the
    test constructs itself - a real assertion about the filter, not a
    data-shaped coincidence.
    """

    def setUp(self):
        self._orig = hybrid.compute_ability_dps
        self.addCleanup(setattr, hybrid, "compute_ability_dps", self._orig)

    def _phys(self, rows) -> float:
        hybrid.compute_ability_dps = lambda *a, **kw: _result(rows)
        return hybrid._physical_ability_damage(
            None, "0", _LEVEL, (), "SR", 0.0, 0.0, 0.0, 0.0, (),
        )

    def test_physical_rows_sum(self):
        self.assertAlmostEqual(
            self._phys([_spell("Q", "PHYSICAL", 10.0), _spell("W", "PHYSICAL", 2.5)]),
            12.5,
        )

    def test_magic_row_contributes_zero(self):
        self.assertEqual(self._phys([_spell("Q", "MAGIC", 500.0)]), 0.0)

    def test_true_row_contributes_zero(self):
        self.assertEqual(self._phys([_spell("R", "TRUE", 500.0)]), 0.0)

    def test_none_damage_type_falls_back_to_magic_and_is_excluded(self):
        # ability_dps.py:371 - a None damage_type normalizes to MAGIC. It must
        # never be treated as physical.
        self.assertEqual(self._phys([_spell("E", None, 500.0)]), 0.0)

    def test_mixed_row_contributes_zero(self):
        self.assertEqual(self._phys([_spell("Q", "MIXED", 500.0)]), 0.0)

    def test_case_insensitive_match(self):
        # The canonical idiom upper-cases before comparing.
        self.assertAlmostEqual(self._phys([_spell("Q", "physical", 7.0)]), 7.0)

    def test_only_physical_survives_a_mixed_set(self):
        rows = [
            _spell("Q", "PHYSICAL", 10.0),
            _spell("W", "MAGIC", 100.0),
            _spell("E", None, 100.0),
            _spell("R", "TRUE", 100.0),
        ]
        self.assertAlmostEqual(self._phys(rows), 10.0)

    def test_empty_per_spell_is_zero(self):
        self.assertEqual(self._phys([]), 0.0)


class AxisCharacterizationTests(unittest.TestCase):
    """Anchor the real-snapshot inputs the seam consumes (pre-existing math)."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _phys_and_total(self, champ):
        r = compute_ability_dps(
            self.snap, champion_id=champ, level=_LEVEL, item_ids=[], mode="SR",
            **_TARGET_KW,
        )
        phys = sum(
            row.dps for row in r.per_spell
            if (row.damage_type or "MAGIC").upper() == "PHYSICAL"
        )
        return phys, r.total_ability_dps

    def test_anchors_are_ad_axis(self):
        for champ in (_AATROX, _AMBESSA, _DARIUS):
            self.assertEqual(hybrid._damage_axis(self.snap, champ), "ad", champ)

    def test_veigar_is_ap_axis(self):
        self.assertEqual(hybrid._damage_axis(self.snap, _VEIGAR), "ap")

    def test_anchors_have_nonzero_physical_ability_damage(self):
        for champ in (_AATROX, _AMBESSA, _DARIUS):
            phys, _ = self._phys_and_total(champ)
            self.assertGreater(phys, 0.0, champ)

    def test_darius_true_damage_r_is_excluded_by_the_filter(self):
        # REAL-DATA guard proof: Noxian Guillotine is damage_type "TRUE", so
        # the physical-only sum is STRICTLY below the unfiltered total.
        phys, total = self._phys_and_total(_DARIUS)
        self.assertGreater(total, phys)
        true_rows = [
            row for row in compute_ability_dps(
                self.snap, champion_id=_DARIUS, level=_LEVEL, item_ids=[],
                mode="SR", **_TARGET_KW,
            ).per_spell
            if (row.damage_type or "MAGIC").upper() == "TRUE"
        ]
        self.assertTrue(true_rows)
        self.assertAlmostEqual(total - phys, sum(r.dps for r in true_rows))

    def test_veigar_has_zero_physical_ability_damage(self):
        phys, total = self._phys_and_total(_VEIGAR)
        self.assertEqual(phys, 0.0)
        self.assertGreater(total, 0.0)


class ComputeHybridSeamTests(unittest.TestCase):
    """compute_hybrid: OFF byte-identical, ON adds exactly the physical term."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _hybrid(self, champ, item_ids=(), **kw):
        return compute_hybrid(
            self.snap, champion_id=champ, level=_LEVEL, item_ids=list(item_ids),
            **_TARGET_KW, **kw,
        )

    def _phys(self, champ, item_ids=()):
        r = compute_ability_dps(
            self.snap, champion_id=champ, level=_LEVEL, item_ids=list(item_ids),
            mode="SR", **_TARGET_KW,
        )
        return sum(
            row.dps for row in r.per_spell
            if (row.damage_type or "MAGIC").upper() == "PHYSICAL"
        )

    def test_off_omitted_equals_explicit_false(self):
        for champ in (_AATROX, _AMBESSA):
            omitted = self._hybrid(champ)
            explicit = self._hybrid(champ, **{_FLAG: False})
            self.assertEqual(omitted.to_dict(), explicit.to_dict(), champ)

    def test_off_ad_branch_is_raw_weighted_dps(self):
        # The OFF path must bind the SAME raw value (a name bind, not a float
        # op): hybrid_score recomposes exactly from the surfaced components.
        for champ in (_AATROX, _AMBESSA):
            off = self._hybrid(champ)
            self.assertEqual(
                off.hybrid_score, off.alpha * off.dps + off.beta * off.ehp, champ,
            )

    def test_on_strictly_increases_ad_branch_damage(self):
        for champ in (_AATROX, _AMBESSA, _DARIUS):
            off = self._hybrid(champ)
            on = self._hybrid(champ, **{_FLAG: True})
            self.assertGreater(on.dps, off.dps, champ)
            self.assertGreater(on.hybrid_score, off.hybrid_score, champ)

    def test_on_adds_exactly_the_physical_term(self):
        for champ in (_AATROX, _AMBESSA, _DARIUS):
            off = self._hybrid(champ)
            on = self._hybrid(champ, **{_FLAG: True})
            self.assertAlmostEqual(on.dps, off.dps + self._phys(champ), places=9)

    def test_on_excludes_darius_true_damage_ultimate(self):
        # The credit must be the PHYSICAL sum, NOT total_ability_dps.
        off = self._hybrid(_DARIUS)
        on = self._hybrid(_DARIUS, **{_FLAG: True})
        total = compute_ability_dps(
            self.snap, champion_id=_DARIUS, level=_LEVEL, item_ids=[], mode="SR",
            **_TARGET_KW,
        ).total_ability_dps
        self.assertLess(on.dps - off.dps, total)
        self.assertAlmostEqual(on.dps - off.dps, self._phys(_DARIUS), places=9)

    def test_ap_branch_unchanged_on_and_off(self):
        off = self._hybrid(_VEIGAR)
        on = self._hybrid(_VEIGAR, **{_FLAG: True})
        self.assertEqual(on.to_dict(), off.to_dict())


class MagicRowGuardTests(unittest.TestCase):
    """A MAGIC per_spell row contributes ZERO through the AD branch.

    Stubs the engine call so the ONLY ability damage available is MAGIC. If
    the filter were missing (or read total_ability_dps), the ON score would
    explode; the contract is that ON is bit-for-bit OFF.
    """

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def setUp(self):
        self._orig = hybrid.compute_ability_dps
        self.addCleanup(setattr, hybrid, "compute_ability_dps", self._orig)

    def test_all_magic_kit_yields_identical_on_and_off(self):
        hybrid.compute_ability_dps = lambda *a, **kw: _result(
            [_spell("Q", "MAGIC", 5000.0), _spell("W", None, 5000.0),
             _spell("R", "TRUE", 5000.0)]
        )
        off = compute_hybrid(
            self.snap, champion_id=_AATROX, level=_LEVEL, item_ids=[], **_TARGET_KW,
        )
        on = compute_hybrid(
            self.snap, champion_id=_AATROX, level=_LEVEL, item_ids=[],
            **_TARGET_KW, **{_FLAG: True},
        )
        self.assertEqual(on.dps, off.dps)
        self.assertEqual(on.hybrid_score, off.hybrid_score)

    def test_single_physical_row_is_the_only_credit(self):
        hybrid.compute_ability_dps = lambda *a, **kw: _result(
            [_spell("Q", "PHYSICAL", 42.0), _spell("W", "MAGIC", 5000.0)]
        )
        off = compute_hybrid(
            self.snap, champion_id=_AATROX, level=_LEVEL, item_ids=[], **_TARGET_KW,
        )
        on = compute_hybrid(
            self.snap, champion_id=_AATROX, level=_LEVEL, item_ids=[],
            **_TARGET_KW, **{_FLAG: True},
        )
        self.assertAlmostEqual(on.dps - off.dps, 42.0, places=9)


class RankerSeamTests(unittest.TestCase):
    """rank_items_by_hybrid: OFF byte-identical, ON lifts baseline + candidates."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _rank(self, champ, current=(), only=(_STERAKS, _WARMOG, _BOTRK), **kw):
        return rank_items_by_hybrid(
            self.snap, champion_id=champ, level=_LEVEL,
            current_item_ids=list(current), only_item_ids=list(only),
            **_TARGET_KW, **kw,
        )

    @staticmethod
    def _row(result, item_id):
        matches = [r for r in result.ranked if r.item_id == item_id]
        assert len(matches) == 1, f"expected exactly 1 row for {item_id}"
        return matches[0]

    def test_ranker_off_byte_identical(self):
        for champ in (_AATROX, _AMBESSA):
            omitted = self._rank(champ)
            explicit = self._rank(champ, **{_FLAG: False})
            self.assertEqual(omitted.baseline_dps, explicit.baseline_dps, champ)
            self.assertEqual(len(omitted.ranked), len(explicit.ranked), champ)
            for ra, rb in zip(omitted.ranked, explicit.ranked):
                self.assertEqual(ra.item_id, rb.item_id, champ)
                self.assertEqual(ra.new_dps, rb.new_dps, champ)
                self.assertEqual(ra.delta_dps, rb.delta_dps, champ)
                self.assertEqual(ra.delta_ehp, rb.delta_ehp, champ)
                self.assertEqual(ra.hybrid_delta_pct, rb.hybrid_delta_pct, champ)
                self.assertEqual(ra.hybrid_score, rb.hybrid_score, champ)

    def test_ranker_on_lifts_baseline(self):
        for champ in (_AATROX, _AMBESSA):
            off = self._rank(champ)
            on = self._rank(champ, **{_FLAG: True})
            self.assertGreater(on.baseline_dps, off.baseline_dps, champ)

    def test_ranker_on_lifts_every_candidate_new_dps(self):
        for champ in (_AATROX, _AMBESSA):
            off = self._rank(champ)
            on = self._rank(champ, **{_FLAG: True})
            for item_id in (_STERAKS, _WARMOG, _BOTRK):
                self.assertGreater(
                    self._row(on, item_id).new_dps,
                    self._row(off, item_id).new_dps,
                    f"{champ}/{item_id}",
                )

    def test_ranker_ap_branch_unchanged(self):
        off = self._rank(_VEIGAR)
        on = self._rank(_VEIGAR, **{_FLAG: True})
        self.assertEqual(on.baseline_dps, off.baseline_dps)
        for ra, rb in zip(on.ranked, off.ranked):
            self.assertEqual(ra.item_id, rb.item_id)
            self.assertEqual(ra.new_dps, rb.new_dps)
            self.assertEqual(ra.hybrid_delta_pct, rb.hybrid_delta_pct)


class RouteSurfaceTests(unittest.TestCase):
    """POST /rank-bruiser accepts the flag; default body stays byte-identical."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)

    BODY = {
        "champion": _AATROX,
        "level": _LEVEL,
        "mode": "SR",
        "top": 40,
        "only": [_STERAKS, _WARMOG, _BOTRK],
        "target_armor": 100.0,
        "target_mr": 60.0,
        "target_max_hp": 2500.0,
        "target_bonus_hp": 1200.0,
    }

    def test_default_body_byte_identical_to_explicit_false(self):
        omitted = server._route_rank_bruiser(dict(self.BODY))
        explicit = server._route_rank_bruiser({**self.BODY, _FLAG: False})
        self.assertEqual(omitted, explicit)

    def test_route_threads_the_flag_on(self):
        off = server._route_rank_bruiser(dict(self.BODY))
        on = server._route_rank_bruiser({**self.BODY, _FLAG: True})
        self.assertGreater(on["baseline_dps"], off["baseline_dps"])

    def test_route_accepts_truthy_string(self):
        # _opt_bool coerces "1"/"true"/"yes"/"on".
        on_bool = server._route_rank_bruiser({**self.BODY, _FLAG: True})
        on_str = server._route_rank_bruiser({**self.BODY, _FLAG: "true"})
        self.assertEqual(on_bool["baseline_dps"], on_str["baseline_dps"])


class ScopeGuardTests(unittest.TestCase):
    """The seam exists ONLY on the two bruiser entry points, END-appended."""

    # The pre-RM-39 trailing parameter of each entry point (the R58 seam).
    # Anchored rather than pinned to names[-1] so a LATER END-appended seam
    # does not break this guard - the exact over-tight assertion that
    # test_ms_utility_r58.py originally carried and this slice had to relax.
    _PRE_RM39_TAIL = "assume_ms_utility"

    def test_seam_scope_and_end_append(self):
        for fn in (compute_hybrid, rank_items_by_hybrid):
            params = inspect.signature(fn).parameters
            names = list(params)
            self.assertIn(_FLAG, names, fn.__name__)
            # END-APPENDED after every parameter that existed before it
            # (CLAUDE.md Python Conventions - a mid-signature insert breaks
            # positional construction).
            self.assertIn(self._PRE_RM39_TAIL, names, fn.__name__)
            self.assertGreater(
                names.index(_FLAG), names.index(self._PRE_RM39_TAIL), fn.__name__,
            )
            self.assertIs(params[_FLAG].default, False, fn.__name__)
        for fn in (
            rank.rank_items,
            dps.compute_dps,
            ehp.compute_ehp,
            burst.compute_burst_damage,
        ):
            self.assertNotIn(_FLAG, inspect.signature(fn).parameters, fn.__name__)

    def test_flag_is_not_a_haste_flag(self):
        # RM-39/RM-43 were re-scoped off ability haste (spec section 2.2 +
        # the CORRECTION OF RECORD). The seam must not piggyback on one.
        self.assertNotIn("haste", _FLAG)


class AutoAttackDisjointnessTests(unittest.TestCase):
    """The ON path is ``weighted_dps + _physical_ability_damage(...)``. That sum
    is only sound while the two terms price DISJOINT events - if the auto term
    ever also priced an ability cast, the sum would double-count that swing.

    This was investigated directly (2026-07-19) because the cohort golden diff
    showed Zeri at +217.7%, the largest lift of the 92, and Zeri's Q replaces
    her basic attack outright. The surface reading - "her Q is her auto, so the
    engine must be counting it twice" - is WRONG, and was asserted twice from
    the damage ratio alone before anyone read ``dps.py``. It is a DENOMINATOR
    artifact: ``dps.py`` models Zeri as landing ~1 real basic per rotation
    (weighted_dps 9.04 against peer ADCs at 28-41), so a mid-pack absolute
    ability term of 19.69 reads as a huge PERCENTAGE lift off a small base.

    Verified in the source, not inferred: ``_rotation_attack_dps``
    (``dps.py:508``) reads ONLY ``duration`` / ``basic`` / ``basicTime`` /
    ``numberOfTargets`` from the rotation dict. The rotation dicts DO carry
    per-spell cast counts under "q"/"w"/"e"/"r"/"p", and ``dps.py`` never reads
    any of them anywhere, so an ability cast cannot reach the auto term.

    This guard pins that invariant structurally. It is the lock that must hold
    before the flag is ever considered for default-ON: if a future slice wires
    ability casts into the AA term (an empowered-auto or auto-reset model, say)
    WITHOUT subtracting them from the ability term, this fails loudly instead of
    silently inflating every AD bruiser.
    """

    _AA_ONLY_ROTATION_KEYS = {"basic", "basicTime", "duration", "numberOfTargets"}
    _ABILITY_CAST_KEYS = {"q", "w", "e", "r", "p"}

    def _rotation_keys_read_by_dps_module(self) -> set[str]:
        """Every string key dps.py reads off a rotation-ish mapping."""
        source = Path(dps.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        found: set[str] = set()

        def _is_rotation_ref(node: ast.AST) -> bool:
            # PREFIX match, not substring: ``stats_for_rotation`` is the STATS
            # mapping (dps.py:945/950/967 read "crit"/"as"/"ad" off it) and is
            # NOT a rotation dict. A substring test swept it in and produced a
            # false positive on the allowlist guard below.
            if isinstance(node, ast.Name):
                name = node.id.lower()
                return name == "rot" or name.startswith("rotation")
            if isinstance(node, ast.Attribute):
                return node.attr.lower().startswith("rotation")
            return False

        for node in ast.walk(tree):
            # rotation["key"]
            if isinstance(node, ast.Subscript) and _is_rotation_ref(node.value):
                if isinstance(node.slice, ast.Constant) and isinstance(
                    node.slice.value, str
                ):
                    found.add(node.slice.value)
            # rotation.get("key", ...)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and _is_rotation_ref(node.func.value)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.add(node.args[0].value)
        return found

    def test_auto_term_never_reads_an_ability_cast_count(self):
        keys = self._rotation_keys_read_by_dps_module()
        # Sanity: the walker actually found the AA reads, so an empty result
        # cannot masquerade as a pass.
        self.assertIn("basic", keys, "AST walk found no rotation reads at all")
        leaked = keys & self._ABILITY_CAST_KEYS
        self.assertEqual(
            leaked,
            set(),
            "dps.py now reads ability cast counts "
            f"{sorted(leaked)} off the rotation dict. The AD-axis ON path adds "
            "_physical_ability_damage to weighted_dps, so an ability cast "
            "reaching the auto term makes that sum DOUBLE-COUNT. Subtract it "
            "from one side or gate the seam before shipping this.",
        )

    def test_rotation_reads_stay_within_the_auto_only_key_set(self):
        keys = self._rotation_keys_read_by_dps_module()
        unexpected = keys - self._AA_ONLY_ROTATION_KEYS
        self.assertEqual(
            unexpected,
            set(),
            f"dps.py reads new rotation keys {sorted(unexpected)}. Confirm they "
            "carry no ability-cast damage before widening this allowlist - see "
            "the class docstring.",
        )


if __name__ == "__main__":
    unittest.main()
