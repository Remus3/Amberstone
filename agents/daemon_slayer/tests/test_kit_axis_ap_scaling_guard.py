"""Kit-axis chokepoint fix + the explicit AP-scaling guard on the AD-axis term.

TWO COUPLED PARTS. Part 1 must hold so Part 2 is safe.

THE DEFECT (Part 2). ``hybrid._damage_axis`` classified a champion's damage
axis from the DDragon ``info.attack`` / ``info.magic`` cosmetic 0-10 designer
ratings. Those ratings reflect base stat GROWTH, not build reality - the same
complaint ``onhit_dps.py:315-324`` already wrote down when it had to bolt on a
local ``_onhit_ap_axis`` workaround for Gwen and KogMaw. Measured against the
live snapshot the rating split disagrees with the kit's own
``lolmath.damage_distribution`` for 12 of 173 champions:

    Alistar Gwen KogMaw Leona Locke Ornn Rell Seraphine TwistedFate Vex
        ad -> ap
    Belveth Qiyana
        ap -> ad

Only three of the twelve reach ``_damage_axis`` at all (its consumers are the
bruiser scorer here and the on-hit scorer in ``onhit_dps``). Belveth was the
broken and UNMITIGATED one: on the "ap" branch (``hybrid.py`` compute_hybrid)
the damage term becomes ``_ability_damage`` alone and ``weighted_dps`` is
dropped, so the live engine served her Liandry's Torment #1 and Blackfire
Torch #2 - AP burn on a kit that is 0.698 physical / 0.115 magical. Gwen and
KogMaw were already rescued locally by ``_onhit_ap_axis``; the chokepoint now
resolves them directly.

THE TRAP (Part 1). Before this change the axis split was the ONLY thing
keeping the RM-39 / RM-43 AD-axis ability term away from AP-SCALING TRUE rows.
The damage-type filter cannot stop them because the L2 widen credits TRUE.
Measured on the live snapshot, summing ``ap_pct`` over the ``damage`` blocks of
each form:

    Belveth R Endless Banquet  TRUE  ap_pct_sum 300.0
    Chogath R Feast            TRUE  ap_pct_sum 150.0

Routing Belveth to the AD branch without an explicit guard would have traded
one bug for another. Part 1 makes the guard explicit and local: the row carries
its own ``ap_pct_sum`` and the AD-axis term excludes any row that scales with
AP on its own merits, regardless of damage type.

The 5 in-cohort TRUE rows the L2 widen exists to credit all measure
``ap_pct_sum`` 0.0 and are unaffected: Olaf E Reckless Swing, Vayne W Silver
Bolts, Darius R Noxian Guillotine, MasterYi E Wuju Style, Garen R Demacian
Justice.

MEASURED COLLATERAL, recorded here deliberately: Vayne Q Tumble is PHYSICAL and
carries ``ap_pct`` (50.0,)*5 alongside ``total_ad_pct`` (75..115), so it is a
genuinely dual-scaling row and the guard drops it from the AD-axis term. That
is the guard behaving as specified ("an AP-scaling row never belongs in the AD
axis"), not an accident - see ``test_vayne_q_dual_scaling_row_is_excluded``.

``apply_ad_axis_ability_damage`` is DEFAULT-OFF, so Part 1 changes nothing at
the default posture - pinned by ``DefaultPostureTests``.

NO ENGINE_VERSION pin here - the merger owns the bump.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agents.daemon_slayer import ability_dps as ability_dps_mod
from agents.daemon_slayer import _ad_axis_ability, hybrid
from agents.daemon_slayer.abilities import DamageBlock
from agents.daemon_slayer.ability_dps import (
    AbilityDpsResult,
    AbilitySpellDps,
    _form_ap_pct_sum,
    compute_ability_dps,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

_LEVEL = 13
_TARGET_KW = {
    "target_armor": 100.0,
    "target_mr": 60.0,
    "target_max_hp": 2500.0,
    "target_bonus_hp": 1200.0,
}

# The 12 measured disagreements between the DDragon rating split and the kit's
# own damage_distribution, spelled out as (champion, old_axis, new_axis).
_EXPECTED_FLIPS = {
    "Alistar": ("ad", "ap"),
    "Belveth": ("ap", "ad"),
    "Gwen": ("ad", "ap"),
    "KogMaw": ("ad", "ap"),
    "Leona": ("ad", "ap"),
    "Locke": ("ad", "ap"),
    "Ornn": ("ad", "ap"),
    "Qiyana": ("ap", "ad"),
    "Rell": ("ad", "ap"),
    "Seraphine": ("ad", "ap"),
    "TwistedFate": ("ad", "ap"),
    "Vex": ("ad", "ap"),
}

# The 5 in-cohort TRUE rows the L2 widen credits. (champion, spell key).
_TRUE_COHORT = (
    ("Olaf", "E"),        # Reckless Swing
    ("Vayne", "W"),       # Silver Bolts
    ("Darius", "R"),      # Noxian Guillotine
    ("MasterYi", "E"),    # Wuju Style
    ("Garen", "R"),       # Demacian Justice
)

_LIANDRYS = "6653"
_BLACKFIRE = "2503"

# Package root, anchored on __file__ so this file stays self-contained and
# resolves from any working directory.
# The cross-package threshold-parity check against core/archetype_picks.py
# lives in tests/test_hybrid_kit_axis_parity.py for exactly that reason.
_PKG_ROOT = Path(__file__).resolve().parents[3]
_HYBRID_SRC = _PKG_ROOT / "agents" / "daemon_slayer" / "hybrid.py"


def _spell(key: str, damage_type, dps_value: float,
           ap_pct_sum: float = 0.0) -> AbilitySpellDps:
    """Per-spell row carrying only the fields the AD-axis filter reads."""
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
        post_mitigation_damage_per_cast=100.0,
        casts_per_sec=0.5,
        casts_per_sec_source="measured",
        mana_uptime_factor=1.0,
        dps=dps_value,
        ap_pct_sum=ap_pct_sum,
    )


def _result(rows) -> AbilityDpsResult:
    """Stub result whose total DELIBERATELY disagrees with the credited sum."""
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


def _legacy_axis(snapshot, champion_id: str) -> str:
    """The PRE-FIX rule, re-implemented here so the flip set is a real claim.

    Importing the engine's own resolver would make this tautological.
    """
    rec = snapshot.champions.get(str(champion_id)) or {}
    info = rec.get("info") or {}
    attack = int(info.get("attack", 0) or 0)
    magic = int(info.get("magic", 0) or 0)
    return "ap" if magic > attack else "ad"


def _ap_pct_sum_for(champion_id: str, key: str) -> float:
    """Independent re-derivation of a form's AP-scaling sum from raw blocks."""
    from agents.daemon_slayer.abilities import load_default

    forms = load_default().get_abilities(champion_id).get(key, ())
    if not forms:
        return 0.0
    return sum(
        sum(block.ap_pct)
        for block in forms[0].damage_blocks
        if block.attribute_kind == "damage" and block.ap_pct
    )


class ApPctSumFieldTests(unittest.TestCase):
    """Part 1a - AbilitySpellDps carries the row's own AP scaling."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_field_exists_and_defaults_to_zero(self):
        row = AbilitySpellDps(
            key="Q", form_name="f", form_index=0, rank=1, cooldown=1.0,
            cost=0.0, damage_type="PHYSICAL", resource=None,
            raw_damage_per_cast=0.0, post_mode_damage_per_cast=0.0,
            post_mitigation_damage_per_cast=0.0, casts_per_sec=0.0,
            casts_per_sec_source="missing", mana_uptime_factor=1.0, dps=0.0,
        )
        self.assertEqual(row.ap_pct_sum, 0.0)

    def test_field_is_appended_at_the_end_of_the_dataclass(self):
        """Repo rule - a new dataclass field goes at the END with a default.

        Every field declared before ``ap_pct_sum`` must therefore still be
        constructible positionally, and no field after it may be required.
        """
        import dataclasses

        fields = [f for f in dataclasses.fields(AbilitySpellDps)]
        names = [f.name for f in fields]
        self.assertIn("ap_pct_sum", names)
        idx = names.index("ap_pct_sum")
        # Everything from the first defaulted field onward must be defaulted.
        first_defaulted = next(
            i for i, f in enumerate(fields)
            if f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING
        )
        self.assertGreater(idx, first_defaulted)

    def test_belveth_r_row_carries_its_ap_scaling(self):
        res = compute_ability_dps(
            self.snap, champion_id="Belveth", level=_LEVEL, item_ids=[],
            mode="SR", **_TARGET_KW,
        )
        row = next(r for r in res.per_spell if r.key == "R")
        self.assertGreater(row.ap_pct_sum, 0.0)
        self.assertAlmostEqual(row.ap_pct_sum, _ap_pct_sum_for("Belveth", "R"))

    def test_chogath_r_row_carries_its_ap_scaling(self):
        res = compute_ability_dps(
            self.snap, champion_id="Chogath", level=_LEVEL, item_ids=[],
            mode="SR", **_TARGET_KW,
        )
        row = next(r for r in res.per_spell if r.key == "R")
        self.assertGreater(row.ap_pct_sum, 0.0)
        self.assertAlmostEqual(row.ap_pct_sum, _ap_pct_sum_for("Chogath", "R"))

    def test_true_cohort_rows_carry_zero_ap_scaling(self):
        for champ, key in _TRUE_COHORT:
            with self.subTest(champion=champ, key=key):
                res = compute_ability_dps(
                    self.snap, champion_id=champ, level=_LEVEL, item_ids=[],
                    mode="SR", **_TARGET_KW,
                )
                row = next(r for r in res.per_spell if r.key == key)
                self.assertEqual((row.damage_type or "").upper(), "TRUE")
                self.assertEqual(row.ap_pct_sum, 0.0)

    def test_zero_spell_rows_carry_zero_ap_scaling(self):
        """A champion with an unleveled / absent key still gets 0.0."""
        res = compute_ability_dps(
            self.snap, champion_id="Garen", level=1, item_ids=[],
            mode="SR", **_TARGET_KW,
        )
        zeroed = [r for r in res.per_spell if r.rank < 0]
        self.assertTrue(zeroed, "expected at least one locked spell at level 1")
        for row in zeroed:
            self.assertEqual(row.ap_pct_sum, 0.0, row.key)


class FormApPctSumTests(unittest.TestCase):
    """Part 1a - the extractor reads DAMAGE blocks and nothing else."""

    @staticmethod
    def _form(*blocks):
        class _F:
            damage_blocks = tuple(blocks)

        return _F()

    @staticmethod
    def _block(kind: str, ap_pct):
        return DamageBlock(attribute="stub", attribute_kind=kind, ap_pct=ap_pct)

    def test_damage_blocks_are_summed(self):
        form = self._form(
            self._block("damage", (50.0, 50.0, 50.0)),
            self._block("damage", (10.0,)),
        )
        self.assertAlmostEqual(_form_ap_pct_sum(form), 160.0)

    def test_non_damage_blocks_are_ignored(self):
        """An AP-scaling HEAL does not make the spell's DAMAGE AP-scaling.

        Without this gate the extractor would tag half the roster's sustain
        kits as AP-scaling and silently strip their real physical rows out of
        the AD-axis term.
        """
        for kind in ("heal", "shield", "modifier", "duration", "slow", "other"):
            with self.subTest(attribute_kind=kind):
                form = self._form(self._block(kind, (300.0, 300.0, 300.0)))
                self.assertEqual(_form_ap_pct_sum(form), 0.0)

    def test_mixed_form_counts_only_the_damage_half(self):
        form = self._form(
            self._block("damage", (25.0, 25.0)),
            self._block("heal", (900.0,)),
            self._block("modifier", (900.0,)),
        )
        self.assertAlmostEqual(_form_ap_pct_sum(form), 50.0)

    def test_absent_ap_pct_is_zero(self):
        form = self._form(
            self._block("damage", None),
            self._block("damage", ()),
        )
        self.assertEqual(_form_ap_pct_sum(form), 0.0)

    def test_empty_form_is_zero(self):
        self.assertEqual(_form_ap_pct_sum(self._form()), 0.0)


class ApScalingExclusionTests(unittest.TestCase):
    """Part 1b - the AD-axis term excludes AP-scaling rows on their own merits."""

    def setUp(self):
        self._orig = _ad_axis_ability.compute_ability_dps
        self.addCleanup(setattr, _ad_axis_ability, "compute_ability_dps", self._orig)

    def _credited(self, rows, **kw) -> float:
        _ad_axis_ability.compute_ability_dps = lambda *a, **k: _result(rows)
        return _ad_axis_ability.physical_ability_damage(
            None, "0", _LEVEL, (), "SR", 0.0, 0.0, 0.0, 0.0, (), **kw
        )

    def test_ap_scaling_true_row_is_excluded(self):
        self.assertEqual(
            self._credited([_spell("R", "TRUE", 500.0, ap_pct_sum=300.0)]), 0.0
        )

    def test_ap_scaling_physical_row_is_excluded(self):
        self.assertEqual(
            self._credited([_spell("Q", "PHYSICAL", 500.0, ap_pct_sum=50.0)]), 0.0
        )

    def test_non_ap_scaling_true_row_is_still_credited(self):
        self.assertAlmostEqual(
            self._credited([_spell("E", "TRUE", 500.0, ap_pct_sum=0.0)]), 500.0
        )

    def test_non_ap_scaling_physical_row_is_still_credited(self):
        self.assertAlmostEqual(
            self._credited([_spell("Q", "PHYSICAL", 12.5, ap_pct_sum=0.0)]), 12.5
        )

    def test_mixed_population_only_the_ap_scaling_row_drops(self):
        rows = [
            _spell("Q", "PHYSICAL", 10.0, ap_pct_sum=0.0),
            _spell("R", "TRUE", 7.0, ap_pct_sum=0.0),
            _spell("W", "TRUE", 999.0, ap_pct_sum=300.0),
        ]
        self.assertAlmostEqual(self._credited(rows), 17.0)

    def test_propensity_path_also_excludes_ap_scaling_rows(self):
        """The RM-98 delta path must not re-admit what the sum excluded.

        The row is shaped so its propensity delta is provably NONZERO (short
        cooldown, low measured rate) - otherwise this test would pass even if
        the delta were computed over the UNFILTERED rows, which is exactly the
        vacuous-green trap. ``test_propensity_delta_is_nonzero_for_this_shape``
        pins that premise.
        """
        ap_row = replace(
            _spell("R", "TRUE", 500.0, ap_pct_sum=300.0),
            cooldown=2.0, casts_per_sec=0.01,
        )
        self.assertEqual(
            self._credited([ap_row], apply_cast_rate_propensity_prior=True), 0.0
        )

    def test_propensity_delta_is_nonzero_for_this_shape(self):
        """Premise guard for the test above - the delta really would move."""
        from agents.daemon_slayer.cast_propensity import (
            propensity_adjusted_dps_delta,
        )

        row = replace(
            _spell("R", "TRUE", 500.0, ap_pct_sum=300.0),
            cooldown=2.0, casts_per_sec=0.01,
        )
        self.assertNotEqual(
            propensity_adjusted_dps_delta(
                [row], credited_damage_types=frozenset({"PHYSICAL", "TRUE"})
            ),
            0.0,
        )

    def test_propensity_path_still_moves_a_clean_row(self):
        """Control - the delta path is not simply dead after the guard.

        A low measured rate against a short cooldown is the case where
        ``combat_basis_casts_per_sec`` rebases ABOVE the measured floor, so the
        delta is nonzero and the exclusion above is proved to be selective
        rather than a blanket zeroing of the RM-98 path.
        """
        clean = _spell("R", "TRUE", 500.0, ap_pct_sum=0.0)
        clean = replace(clean, cooldown=2.0, casts_per_sec=0.01)
        with_prior = self._credited([clean], apply_cast_rate_propensity_prior=True)
        without = self._credited([clean])
        self.assertNotAlmostEqual(with_prior, without)


class KitAxisChokepointTests(unittest.TestCase):
    """Part 2 - _damage_axis reads the kit's own damage_distribution."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_belveth_resolves_ad(self):
        self.assertEqual(hybrid._damage_axis(self.snap, "Belveth"), "ad")

    def test_chogath_axis_is_unchanged_ap(self):
        self.assertEqual(hybrid._damage_axis(self.snap, "Chogath"), "ap")

    def test_gwen_resolves_ap(self):
        self.assertEqual(hybrid._damage_axis(self.snap, "Gwen"), "ap")

    def test_kogmaw_resolves_ap(self):
        self.assertEqual(hybrid._damage_axis(self.snap, "KogMaw"), "ap")

    def test_ad_anchor_cohort_is_unchanged(self):
        for champ in ("Aatrox", "Ambessa", "Darius", "Olaf", "Vayne",
                      "MasterYi", "Garen"):
            with self.subTest(champion=champ):
                self.assertEqual(hybrid._damage_axis(self.snap, champ), "ad")

    def test_ap_anchor_is_unchanged(self):
        self.assertEqual(hybrid._damage_axis(self.snap, "Veigar"), "ap")

    def test_flip_set_is_exactly_the_twelve_measured_champions(self):
        flips = {}
        for cid in self.snap.champions:
            old = _legacy_axis(self.snap, cid)
            new = hybrid._damage_axis(self.snap, cid)
            if old != new:
                flips[cid] = (old, new)
        self.assertEqual(flips, _EXPECTED_FLIPS)

    def test_indecisive_distribution_falls_back_to_the_rating_split(self):
        """A genuine hybrid keeps the legacy verdict, it does not flip on noise.

        Measured indecisive cohort at this patch: DrMundo Jax Kaisa Sejuani
        Shaco Shen Shyvana Udyr Volibear Warwick.
        """
        for champ in ("Shaco", "Jax", "Kaisa", "Udyr", "Warwick"):
            with self.subTest(champion=champ):
                self.assertEqual(
                    hybrid._damage_axis(self.snap, champ),
                    _legacy_axis(self.snap, champ),
                )

    def test_missing_or_malformed_distribution_falls_back(self):
        class _Snap:
            def __init__(self, rec):
                self.champions = {"X": rec}

        for rec in (None, {}, {"lolmath": None}, {"lolmath": {}},
                    {"lolmath": {"damage_distribution": {}}},
                    {"lolmath": {"damage_distribution": None}},
                    {"lolmath": {"damage_distribution": {"magical": "x"}}},
                    {"lolmath": {"damage_distribution": []}}):
            with self.subTest(rec=rec):
                base = dict(rec) if isinstance(rec, dict) else {}
                base["info"] = {"attack": 2, "magic": 9}
                self.assertEqual(hybrid._damage_axis(_Snap(base), "X"), "ap")
                base["info"] = {"attack": 9, "magic": 2}
                self.assertEqual(hybrid._damage_axis(_Snap(base), "X"), "ad")

    def test_thresholds_are_the_documented_literals(self):
        """The gates are the values the comment block claims they are.

        Cross-package parity with ``core.archetype_picks`` is asserted in
        ``tests/test_hybrid_kit_axis_parity.py`` - it cannot live here, because
        this file must stay runnable against the engine package alone, which
        does not carry ``core/``.
        """
        self.assertEqual(hybrid._AXIS_DOMINANT_MIN, 0.55)
        self.assertEqual(hybrid._AXIS_MARGIN_MIN, 0.20)

    def test_hybrid_does_not_import_core(self):
        """Share-mirror standalone contract (hybrid.py module docstring)."""
        tree = ast.parse(_HYBRID_SRC.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(
                        a.name == "core" or a.name.startswith("core."), a.name
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertFalse(
                    mod == "core" or mod.startswith("core."), mod
                )


class BelvethIntegrationTests(unittest.TestCase):
    """Parts 1 and 2 together on the champion that motivated the fix."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _credited(self, champ: str) -> float:
        return _ad_axis_ability.physical_ability_damage(
            self.snap, champ, _LEVEL, (), "SR",
            _TARGET_KW["target_armor"], _TARGET_KW["target_mr"],
            _TARGET_KW["target_max_hp"], _TARGET_KW["target_bonus_hp"], (),
        )

    def _rows(self, champ: str):
        return compute_ability_dps(
            self.snap, champion_id=champ, level=_LEVEL, item_ids=[],
            mode="SR", **_TARGET_KW,
        ).per_spell

    def test_belveth_r_dps_is_nonzero_but_not_credited(self):
        """The row exists and carries real DPS - it is EXCLUDED, not empty."""
        r = next(row for row in self._rows("Belveth") if row.key == "R")
        self.assertGreater(r.dps, 0.0)
        self.assertGreater(r.ap_pct_sum, 0.0)
        credited = self._credited("Belveth")
        expected = sum(
            row.dps for row in self._rows("Belveth")
            if (row.damage_type or "MAGIC").upper() in ("PHYSICAL", "TRUE")
            and row.ap_pct_sum == 0.0
        )
        self.assertAlmostEqual(credited, expected)
        # And the excluded row is genuinely absent, not merely equal by luck.
        naive = sum(
            row.dps for row in self._rows("Belveth")
            if (row.damage_type or "MAGIC").upper() in ("PHYSICAL", "TRUE")
        )
        self.assertAlmostEqual(naive - credited, r.dps)

    def test_chogath_r_is_not_credited_either(self):
        r = next(row for row in self._rows("Chogath") if row.key == "R")
        self.assertGreater(r.ap_pct_sum, 0.0)
        credited = self._credited("Chogath")
        expected = sum(
            row.dps for row in self._rows("Chogath")
            if (row.damage_type or "MAGIC").upper() in ("PHYSICAL", "TRUE")
            and row.ap_pct_sum == 0.0
        )
        self.assertAlmostEqual(credited, expected)

    def test_true_cohort_rows_stay_credited(self):
        for champ, key in _TRUE_COHORT:
            with self.subTest(champion=champ, key=key):
                row = next(r for r in self._rows(champ) if r.key == key)
                credited = self._credited(champ)
                self.assertGreaterEqual(credited, row.dps)

    def test_vayne_q_dual_scaling_row_is_excluded(self):
        """MEASURED COLLATERAL, pinned so it is a decision and not a surprise.

        Vayne Q Tumble is PHYSICAL and carries both ``total_ad_pct`` and a
        nonzero ``ap_pct``. The guard is axis-based, not damage-type-based, so
        a dual-scaling row leaves the AD-axis term. Her TRUE W row is
        unaffected - that is the row the L2 widen exists for.
        """
        q = next(r for r in self._rows("Vayne") if r.key == "Q")
        self.assertEqual((q.damage_type or "").upper(), "PHYSICAL")
        self.assertGreater(q.ap_pct_sum, 0.0)
        credited = self._credited("Vayne")
        expected = sum(
            r.dps for r in self._rows("Vayne")
            if (r.damage_type or "MAGIC").upper() in ("PHYSICAL", "TRUE")
            and r.ap_pct_sum == 0.0
        )
        self.assertAlmostEqual(credited, expected)

    def test_belveth_bruiser_top_pick_is_not_off_axis(self):
        """Regression pin on COMPUTED axis behavior, not an item-name list.

        Off-axis-ness is decided by the same data-driven helper the burst
        scorer uses (``_burst_off_axis``), so this cannot rot into a brittle
        literal list. Pre-fix the top two were Liandry's Torment and Blackfire
        Torch, BOTH magic-only offense on a 0.698-physical kit; the assertion
        is that neither leading slot is off-axis any more.

        DELIBERATELY SCOPED TO THE TOP TWO. ``hybrid_score`` is
        ``alpha * dps + beta * ehp`` and Liandry's carries 300 HP, so it still
        earns a mid-table slot on the EHP half. That is the bruiser scorer
        working as designed, not residue of the defect - what was wrong was it
        LEADING the list off the back of a mis-routed damage axis.
        """
        from agents.daemon_slayer._burst_off_axis import (
            champion_burst_axis,
            is_off_axis_candidate,
        )

        axis = champion_burst_axis(self.snap.champions.get("Belveth"))
        self.assertEqual(axis, "ad")
        res = rank_items_by_hybrid(
            self.snap, champion_id="Belveth", level=_LEVEL,
            current_item_ids=[], mode="SR", top_n=5, **_TARGET_KW,
        )
        self.assertGreaterEqual(len(res.ranked), 2)
        lead_ids = [str(r.item_id) for r in res.ranked[:2]]
        for iid in lead_ids:
            with self.subTest(item_id=iid):
                self.assertFalse(
                    is_off_axis_candidate(self.snap.items.get(iid), axis),
                    f"{iid} is pure off-axis offense for an AD kit",
                )
        self.assertNotIn(_LIANDRYS, lead_ids)
        self.assertNotIn(_BLACKFIRE, lead_ids)

    def test_belveth_hybrid_damage_term_is_the_ad_branch(self):
        """At the default the AD branch binds raw weighted_dps."""
        from agents.daemon_slayer.dps import compute_dps

        res = compute_hybrid(
            self.snap, champion_id="Belveth", level=_LEVEL, item_ids=[],
            mode="SR", **_TARGET_KW,
        )
        raw = compute_dps(
            self.snap, champion_id="Belveth", level=_LEVEL, item_ids=[],
            mode="SR", **_TARGET_KW,
        )
        self.assertAlmostEqual(res.dps, raw.weighted_dps)


class DefaultPostureTests(unittest.TestCase):
    """apply_ad_axis_ability_damage is DEFAULT-OFF - Part 1 is inert there."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_default_never_calls_the_ad_axis_term(self):
        """Hard proof: poison the helper and run the default path anyway."""
        orig = _ad_axis_ability.physical_ability_damage

        def _boom(*a, **k):
            raise AssertionError(
                "_physical_ability_damage called at the default posture"
            )

        _ad_axis_ability.physical_ability_damage = _boom
        self.addCleanup(setattr, _ad_axis_ability, "physical_ability_damage", orig)
        for champ in ("Aatrox", "Darius", "Olaf", "Garen", "Belveth"):
            with self.subTest(champion=champ):
                compute_hybrid(
                    self.snap, champion_id=champ, level=_LEVEL, item_ids=[],
                    mode="SR", **_TARGET_KW,
                )

    def test_seam_default_is_still_off(self):
        import inspect

        sig = inspect.signature(compute_hybrid)
        self.assertFalse(sig.parameters["apply_ad_axis_ability_damage"].default)

    def test_ap_pct_sum_does_not_perturb_any_dps_number(self):
        """The new field is carried, never consumed by the default math.

        NOT a tautology: the earlier form of this test compared ``dps``
        against ``post_mitigation_damage_per_cast * casts_per_sec``, which
        is how ``dps`` is DEFINED at ``ability_dps.py:1323`` - it held by
        construction and survived every mutant. This version forces the
        field to a value it could never legitimately take and asserts every
        computed number is byte-identical, so it goes RED the moment
        ``ap_pct_sum`` is wired into the default math.
        """
        for champ in ("Aatrox", "Belveth", "Vayne", "Chogath"):
            with self.subTest(champion=champ):
                kw = dict(
                    champion_id=champ, level=_LEVEL, item_ids=[],
                    mode="SR", **_TARGET_KW,
                )
                baseline = compute_ability_dps(self.snap, **kw)
                with mock.patch.object(
                    ability_dps_mod, "_form_ap_pct_sum", return_value=9999.0,
                ):
                    poisoned = compute_ability_dps(self.snap, **kw)
                # The field itself must actually have moved, else the poison
                # never landed and the comparison below proves nothing.
                self.assertTrue(
                    any(r.ap_pct_sum == 9999.0 for r in poisoned.per_spell),
                    "poison did not reach any row - test would be vacuous",
                )
                self.assertEqual(
                    [r.dps for r in baseline.per_spell],
                    [r.dps for r in poisoned.per_spell],
                )
                self.assertEqual(
                    baseline.total_ability_dps, poisoned.total_ability_dps,
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
