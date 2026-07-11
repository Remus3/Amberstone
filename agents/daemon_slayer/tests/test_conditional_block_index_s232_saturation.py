"""Phase 5.9.32 (s232, 2026-05-16) - conditional pure-data vein
SATURATION PROOF (no registry/engine change; ENGINE stays 1.3.0).

Operator chose "Accept loop complete" after s232's rigorous scan showed
the autonomous pure-data conditional-seed-expansion vein is exhausted -
the same conclusion the s223->s227 pure-data registry sweep reached for
the unconditional registries. This file is the s223-style machine-
checked saturation guard so no future session re-mines an empty vein,
and so a future Meraki re-extract that introduces a genuinely-new clean
execute candidate trips a test (the signal to revisit).

THE EXHAUSTION ARGUMENT (verified by tools/ds_cond_pair_prefilter.py +
tools/ds_execute_prefilter.py, both kept as durable per-patch tools):

  * ``target_full_hp`` (execute) vein: the clean discrete amped/un-amped
    executes were Evelynn R + KogMaw R (s231) and Kindred E (s228). The
    ONLY other true target_missing_hp_pct / target_current_hp_pct pairs
    are cases where the engine-default block 0 ALREADY carries the
    higher coefficient (Jinx R: block 0 = 25-35% missing-HP, the max -
    s217's determination) or are deliberately R-entangled skips (Varus
    W blocks 5/6 - s225 chose block 2 to keep W's score R-independent).
    No unaddressed clean execute candidate remains.
  * ``target_no_setup`` (self-applied-debuff amp) vein: the one genuine
    correctness fix was Fiddlesticks Q (s230). Everything else the pair
    scanner finds is already correctly plain-int mapped to the amped
    block - converting those to conditionals is a pure Part-1 no-op
    that adds zero ranking value until a Part-2 live-advisory surface
    consumes the downgrade branch (deliberately not built; s229
    reframed per-tick B-2 as a mis-feature for item ranking).
  * All other discrete-pair scanner hits are ``target_max_hp_pct``,
    which is NOT the ``target_full_hp`` execute semantic (max-HP
    scaling is a flat fraction of the health bar, not HP-gated) and is
    already mapped-correctly.

The high-ROI remaining DS work is Part-2 (live target-state plumbing)
- architectural, wants operator sign-off, NOT autonomous pure-data.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import load_default, reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _BLOCK_INDEX_CONDITIONS,
    get_block_index_for,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot

# Every conditional shipped s228->s231 - the terminal set of the
# autonomous pure-data conditional vein.
_SHIPPED_CONDITIONALS = {
    ("Kindred", "E"): {"default": 1, "target_full_hp": 0},      # s228
    ("Zoe", "E"): {"default": 2, "target_no_setup": 0},         # s228/s229
    ("Evelynn", "Q"): {"default": 5, "target_no_setup": 0},     # s228/s229
    ("Anivia", "E"): {"default": 1, "target_no_setup": 0},      # s229
    ("Brand", "W"): {"default": 1, "target_no_setup": 0},       # s229
    ("Morgana", "W"): {"default": 3, "target_full_hp": 2},      # s229
    ("Fiddlesticks", "Q"): {                                    # s230
        "default": [2, 3], "target_no_setup": [0, 1]},
    ("Cassiopeia", "E"): {"default": 1, "target_no_setup": 0},  # s230
    ("Evelynn", "R"): {"default": 1, "target_full_hp": 0},      # s231
    ("KogMaw", "R"): {"default": 1, "target_full_hp": 0},       # s231
}


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


class VocabAndShippedConditionalsTests(unittest.TestCase):
    """The vocab stays exactly two terms (s227 "don't over-build"); the
    full shipped conditional set is intact and is terminal for the
    autonomous pure-data vein."""

    def setUp(self) -> None:
        reset_block_index_cache()

    def test_vocab_is_exactly_two_terms(self) -> None:
        self.assertEqual(
            _BLOCK_INDEX_CONDITIONS,
            frozenset({"target_full_hp", "target_no_setup"}),
        )

    def test_all_shipped_conditionals_intact(self) -> None:
        for (champ, key), shape in _SHIPPED_CONDITIONALS.items():
            m, _ = get_block_index_for(champ)
            self.assertEqual(
                m.get(key), shape,
                f"{champ}.{key} conditional drifted from shipped shape",
            )

    def test_registry_still_125_champions(self) -> None:
        reg = json.loads(
            Path("agents/daemon_slayer/champion_block_index.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 125)


class DocumentedExecuteSkipsTests(unittest.TestCase):
    """The two true-missing-HP pairs that are deliberately NOT
    conditional must stay that way (the exhaustion argument rests on
    them being already-correct, not overlooked)."""

    def setUp(self) -> None:
        reset_block_index_cache()

    def test_jinx_R_unmapped_block0_is_canonical_max_missing_hp(self) -> None:
        # Engine default = block 0. s217 determined block 0 is the
        # canonical max-distance primary-target value AND it carries
        # the HIGHEST missing-HP coefficient - so no entry is needed.
        m, _ = get_block_index_for("Jinx")
        self.assertNotIn("R", m)
        reset_default_cache()
        blocks = load_default().champions["Jinx"]["R"][0].damage_blocks
        dmg = [b for b in blocks if b.attribute_kind == "damage"]
        b0_mh = dmg[0].target_missing_hp_pct[0]
        self.assertTrue(
            all(b0_mh >= (b.target_missing_hp_pct[0]
                          if b.target_missing_hp_pct else 0.0)
                for b in dmg),
            "Jinx R block 0 must hold the max missing-HP coeff "
            "(engine default already correct)",
        )

    def test_varus_W_stays_block2_R_independent(self) -> None:
        # s225: blocks 5/6 are the R-entangled missing-HP Blight amp;
        # W must score R-independent -> mapped to block 2 (max-HP
        # 3-stack detonation), NOT a missing-HP conditional.
        m, _ = get_block_index_for("Varus")
        self.assertEqual(m.get("W"), 2)
        self.assertEqual(m.get("Q"), 1)

    def test_veigar_R_stays_deferred_int(self) -> None:
        # Clean 2.0x execute but the canonical stable-int test fixture
        # (s229/s231 deliberately picked non-fixture executes instead).
        m, _ = get_block_index_for("Veigar")
        self.assertEqual(m.get("R"), 1)


class MissingHpExecuteVeinSaturationGuard(unittest.TestCase):
    """Machine-checked saturation proof: enumerate EVERY ability form
    with two same-shape filtered damage blocks differing (monotone) in
    a true execute coefficient (target_missing_hp_pct /
    target_current_hp_pct), and assert each (champ,key) is ACCOUNTED
    FOR - already a conditional, OR engine-default block 0 already
    holds the higher coefficient, OR a documented skip. A NEW unaccounted
    clean execute pair (e.g. from a future Meraki re-extract) trips this
    test -> the signal to revisit the vein.
    """

    _EXEC_FIELDS = ("target_missing_hp_pct", "target_current_hp_pct")
    # Aligned to the actual DamageBlock dataclass attributes (no
    # caster_missing_hp_pct field exists on the block).
    _SCALE = (
        "base", "total_ad_pct", "bonus_ad_pct", "ap_pct",
        "caster_max_hp_pct", "caster_bonus_hp_pct", "caster_max_mp_pct",
        "target_max_hp_pct", "target_missing_hp_pct",
        "target_current_hp_pct", "target_bonus_hp_pct",
        "target_armor_pct", "bonus_armor_pct", "bonus_mr_pct",
    )
    # Documented as engine-default-correct or deliberate skip (with the
    # session that established it). Anything NOT here that surfaces a
    # clean execute pair fails the guard.
    _DOCUMENTED_NON_CONDITIONAL = {
        ("Jinx", "R"),    # s217 - block 0 is canonical max missing-HP
        ("Varus", "W"),   # s225 - blocks 5/6 R-entangled; block 2 chosen
        ("Veigar", "R"),  # s229/s231 - deferred stable-int fixture
    }

    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.ab = load_default()

    def _shape(self, b):
        return frozenset(f for f in self._SCALE if getattr(b, f, None))

    def _f(self, b, name):
        v = getattr(b, name, None)
        return v[0] if v else 0.0

    def test_no_unaccounted_clean_execute_pair(self) -> None:
        reset_block_index_cache()
        offenders = []
        for champ, keys in self.ab.champions.items():
            for key, forms in keys.items():
                for form in forms:
                    dmg = [b for b in form.damage_blocks
                           if b.attribute_kind == "damage"]
                    if len(dmg) < 2:
                        continue
                    for i in range(len(dmg)):
                        for j in range(len(dmg)):
                            if i == j:
                                continue
                            lo, hi = dmg[i], dmg[j]
                            sh = self._shape(lo)
                            if not sh or sh != self._shape(hi):
                                continue
                            # monotone amp touching an execute coeff
                            if any(self._f(hi, f) < self._f(lo, f) - 1e-9
                                   for f in sh):
                                continue
                            if not any(
                                f in sh
                                and self._f(hi, f) > self._f(lo, f) + 1e-9
                                for f in self._EXEC_FIELDS
                            ):
                                continue
                            # found a clean execute pair - must be
                            # accounted for.
                            m, _ = get_block_index_for(champ)
                            cur = m.get(key)
                            if isinstance(cur, dict):
                                continue  # already conditional
                            if (champ, key) in (
                                self._DOCUMENTED_NON_CONDITIONAL
                            ):
                                continue  # documented skip
                            # engine default is block 0; if block 0
                            # already holds the >= max execute coeff
                            # the engine is already correct.
                            b0 = dmg[0]
                            if all(
                                self._f(b0, f) >= self._f(hi, f) - 1e-9
                                for f in self._EXEC_FIELDS
                                if f in self._shape(b0)
                            ) and self._shape(b0):
                                continue
                            offenders.append(
                                f"{champ}.{key} f{form.form_index} "
                                f"{i}->{j} {sorted(sh)}")
        self.assertEqual(
            offenders, [],
            "Unaccounted clean execute pair(s) - the conditional vein "
            "is NOT saturated anymore; investigate + either add a "
            "conditional or document the skip:\n  "
            + "\n  ".join(sorted(set(offenders))),
        )


class EngineVersionUnchangedS232Tests(unittest.TestCase):
    def test_engine_version_unchanged(self) -> None:
        from agents import daemon_slayer

        # s232 itself was a saturation-proof + tooling + docs commit ONLY
        # (no registry/engine change of its own). This pin tracks the
        # live ENGINE_VERSION stamp, which later milestones legitimately
        # bump - it is 1.9.0 as of the P1-L23 BRAWL map-legality fix
        # (the Riot stat-growth quadratic fix was 1.5.0)
        # (quadratic per-level base-stat scaling).
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.196.0")


if __name__ == "__main__":
    unittest.main()
