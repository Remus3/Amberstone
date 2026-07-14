"""Carry build coherence re-rank (found 2026-07-13, DS build-reco QA).

The AD/carry ds.dps scorer offers cross-archetype ARTIFACT items no crit ADC
builds - Essence Reaver (3508) floats to the top-4 for Twitch/Jinx/Caitlyn/Ashe
(its Spellblade proc is modeled at an ability-cast tempo a pure auto-attacker
lacks, and its mana + ability haste are DPS-invisible but unpenalized), while
the crit AMPLIFIER core (Infinity Edge 3031 etc.) is buried at rank 6-9 (greedy
single-item delta_dps cannot see accumulated-crit synergy). See
ops/audit/DS_BUILD_RECO_OVERLAY_QA.md + docs/specs/2026-07-13-ds-build-coherence-refactor.md.

The fix is a METRIC (not win-rate, not blacklist) soft coherence re-rank applied
at the carry chokepoint: dock off-axis / wasted-stat items and nudge on-axis fit,
computed from core.build_planner.kit_synergy primitives. This test drives the
pure re-rank helper directly with REAL engine rows (rank_items in-process, no
live :8893), so it is server-free and deterministic. The control asserts the
artifact IS in the raw top-6 (proving the defect + that the re-rank is the lever).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items
from core.build_planner.coherence import coherence_rerank

_ER = "3508"        # Essence Reaver - the systemic artifact (caster-marksman)
_ECLIPSE = "6692"   # Eclipse - off-class lethality on a crit ADC
_IE = "3031"        # Infinity Edge - the buried crit amplifier that must surface

# Caster / spellblade marksmen (Marksman + Mage tag) - their Sheen-line / mana
# core is LEGIT, so the coherence dock must leave them byte-identical.
_CASTER_MARKSMEN = ("Ezreal", "Corki")
# Their real spellblade / mana core - at least one must survive the re-rank.
_CASTER_CORE = frozenset({"3508", "3078", "3042", "3004"})  # ER / Trinity / Mura / Manamune

# A realistic ARAM cell (the Step-1 spec's measured cell: ER ~#4, IE ~#7).
_ARAM = dict(
    level=18, current_item_ids=[], mode="ARAM", top_n=40, sort_by="delta",
    filter_shared_uniques=True, target_armor=60.0, target_mr=40.0,
    target_max_hp=1900.0, target_bonus_hp=500.0,
)

# Crit ADCs whose real core the sustained-DPS scorer buries.
_CRIT_ADCS = ("Twitch", "Jinx", "Caitlyn", "Ashe")

# Crit / on-hit ADCs that carry an INCIDENTAL secondary Mage tag. The original
# is_caster_marksman gate (Marksman + Mage tag) wrongly exempted them from the
# dock, so their Essence Reaver / Eclipse artifact survived (live-confirmed
# 2026-07-13). The ability-AP-scaling floor tightening reaches them now. Keyed by
# canonical DDragon id (rank_items needs the id, not the display name).
_MAGE_TAGGED_CRIT_ADCS = ("MissFortune", "Jhin", "Kaisa", "Varus")


class CarryCoherenceRerankTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _raw_rows(self, champ):
        # Wide window so the buried crit core is present to re-rank.
        return rank_items(self.snap, champ, **_ARAM).ranked

    def test_essence_reaver_is_the_defect_control(self):
        """Control: Essence Reaver sits in the RAW carry top-6 for the crit ADCs -
        the artifact the re-rank must remove (and proof the re-rank is the lever)."""
        hits = []
        for champ in _CRIT_ADCS:
            top6 = {str(x.item_id) for x in self._raw_rows(champ)[:6]}
            if _ER in top6:
                hits.append(champ)
        self.assertTrue(
            hits, f"Essence Reaver not in any crit-ADC raw top-6 - the test "
            f"would not prove the defect (checked {_CRIT_ADCS})",
        )

    def test_coherence_rerank_demotes_artifacts_surfaces_crit_core(self):
        for champ in _CRIT_ADCS:
            rows = self._raw_rows(champ)
            got = [str(x.item_id) for x in coherence_rerank(rows, champ, top=6)]
            gotset = set(got)
            self.assertNotIn(
                _ER, gotset,
                f"{champ}: Essence Reaver (3508) still in coherence top-6: {got}",
            )
            self.assertNotIn(
                _ECLIPSE, gotset,
                f"{champ}: Eclipse (6692) still in coherence top-6: {got}",
            )
            self.assertIn(
                _IE, gotset,
                f"{champ}: Infinity Edge (3031) not surfaced in coherence top-6: {got}",
            )

    def test_caster_marksman_core_not_stripped(self):
        """Regression guard (2026-07-13): a caster / spellblade marksman (Ezreal,
        Corki - Marksman + Mage tag) genuinely builds a Sheen-line spellblade /
        mana core, so the coherence dock must NOT strip it. They are excluded from
        the re-rank (byte-identical to raw), and their real core survives."""
        for champ in _CASTER_MARKSMEN:
            rows = self._raw_rows(champ)
            self.assertTrue(rows, f"{champ}: no engine rows to guard")
            raw6 = [str(r.item_id) for r in rows[:6]]
            got = [str(r.item_id) for r in coherence_rerank(rows, champ, top=6)]
            # Byte-identical: caster-marksmen are excluded from the dock.
            self.assertEqual(
                got, raw6,
                f"{champ}: coherence must be a byte-identical no-op for a "
                f"caster-marksman - got {got} vs raw {raw6}",
            )
            # And the guard is meaningful - their real spellblade / mana core is
            # present in the top-6 (so it is retained, not stripped).
            self.assertTrue(
                _CASTER_CORE & set(got),
                f"{champ}: spellblade/mana core {sorted(_CASTER_CORE)} not "
                f"retained in coherence top-6: {got}",
            )

    def test_mage_tagged_crit_adcs_now_docked(self):
        """Gate tightening (2026-07-13): a crit / on-hit ADC with an incidental
        secondary Mage tag (Miss Fortune / Jhin / Kai'Sa / Varus) is NO LONGER
        exempt from the dock, so its Essence Reaver / Eclipse artifact is removed
        from the coherence top-6. Control-gated per champ: only asserts removal of
        an artifact that was actually in that champ's RAW top-6 (else the check is
        vacuous), and requires at least one real removal across the set."""
        removed = []
        for champ in _MAGE_TAGGED_CRIT_ADCS:
            rows = self._raw_rows(champ)
            self.assertTrue(rows, f"{champ}: no engine rows")
            raw6 = {str(x.item_id) for x in rows[:6]}
            got = {str(x.item_id) for x in coherence_rerank(rows, champ, top=6)}
            for art in (_ER, _ECLIPSE):
                if art in raw6:
                    removed.append((champ, art))
                    self.assertNotIn(
                        art, got,
                        f"{champ}: artifact {art} still in coherence top-6 after "
                        f"the gate tightening: {sorted(got)}",
                    )
        self.assertTrue(
            removed,
            "no Mage-tagged crit ADC had ER/Eclipse in its raw top-6 - the test "
            f"would not prove the fix (checked {_MAGE_TAGGED_CRIT_ADCS})",
        )

    def test_noncarry_archetype_is_byte_identical_noop(self):
        """Byte-identical control: a mage (Lux) and a tank (Ornn) are NOT the
        carry archetype, so coherence_rerank hits the defensive early-return and
        yields rows[:top] UNCHANGED - the clean mage / tank / enchanter scorers
        must never move (proven by item_id, both order and the returned objects).
        """
        for champ in ("Lux", "Ornn"):
            rows = self._raw_rows(champ)
            self.assertTrue(rows, f"{champ}: no engine rows to control against")
            for top in (6, 8):
                out = coherence_rerank(rows, champ, top=top)
                self.assertEqual(
                    [str(r.item_id) for r in out],
                    [str(r.item_id) for r in rows[:top]],
                    f"{champ}: coherence_rerank(top={top}) must be a no-op",
                )
                # Same row objects, not reconstructed copies.
                self.assertEqual(list(out), list(rows[:top]))


if __name__ == "__main__":
    unittest.main()
