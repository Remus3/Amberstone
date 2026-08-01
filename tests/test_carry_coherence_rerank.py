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
live :8860), so it is server-free and deterministic. The control asserts the
artifact IS in the raw top-6 (proving the defect + that the re-rank is the lever).
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items
from core.build_planner import coherence as coherence_mod
from core.build_planner.champ_kit_data import _AP_HYBRID_ITEM_IDS
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


# LEAP-07 DD1 - the AP-on-AD-marksman ("Zeri") class.
_LICH = "3100"        # Lich Bane
_LIANDRYS = "6653"    # Liandry's Torment
_STORM = "3097"       # Stormrazor - Zeri's next-best on-hit/AS slot-4 candidate
# The MEASURED membership cell (spec DD1 "Engine-AP-credit control", re-run at
# engine 1.245.0): SR level 13 at an explicit armor-100 target. Explicit target
# stats are mandatory - the ranker defaults are all 0.0 and a zero-HP target
# nullifies every percent-max-HP effect (Liandry's burn).
_AP_CREDIT_CELL = dict(
    level=13, current_item_ids=[], mode="SR", top_n=706, sort_by="delta",
    filter_shared_uniques=True, target_armor=100.0, target_mr=50.0,
    target_max_hp=2000.0, target_bonus_hp=800.0,
)
# The greedy prefix that surfaces Liandry's for Zeri in the build-order path:
# BORK + Plated Steelcaps + Dusk and Dawn (2510, a GHOST-LIST legit on-hit
# hybrid carrying 60 AP).
_GREEDY_PREFIX = ["3153", "3047", "2510"]


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


class ApHybridMarksmanClassSeam(unittest.TestCase):
    """LEAP-07 DD1 - the AP-on-AD-marksman coherence class, wired at the carry
    chokepoint (docs/specs/leap/LEAP-07-build-coherence-calibration-r2.md).

    The allow-map ships EMPTY, so production behavior is byte-identical. A test
    that only asserted "nothing moved" would be vacuous, so these prove the
    predicate is genuinely CONSULTED on the carry path and that the member
    branch CHANGES the ranking the moment a champion qualifies.
    """

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _delta(self, champ, item_id, **overrides):
        cell = dict(_AP_CREDIT_CELL, **overrides)
        for row in rank_items(self.snap, champ, **cell).ranked:
            if str(row.item_id) == item_id:
                return float(row.delta_dps)
        return None

    def test_measured_membership_rule_keeps_zeri_out(self):
        """The DD1 membership rule, re-measured at the LIVE engine: a marksman
        joins the class ONLY if its AP-hybrid deltas materially EXCEED a pure-AD
        marksman control (Caitlyn / Jinx) at a fixed target. Zeri's deltas sit
        BELOW both controls for both items - the engine does not credit her Q
        ability-AP above a pure-AD baseline - so the allow-map stays empty.

        A failure here means the engine moved and DD1 membership must be
        re-adjudicated (per the spec), NOT that this assertion needs relaxing.
        """
        for item in (_LICH, _LIANDRYS):
            zeri = self._delta("Zeri", item)
            cait = self._delta("Caitlyn", item)
            jinx = self._delta("Jinx", item)
            self.assertIsNotNone(zeri, f"{item}: Zeri row absent - probe is vacuous")
            self.assertIsNotNone(cait, f"{item}: Caitlyn row absent")
            self.assertIsNotNone(jinx, f"{item}: Jinx row absent")
            self.assertLess(
                zeri, min(cait, jinx),
                f"item {item}: Zeri delta {zeri:.3f} is NOT below the pure-AD "
                f"control (Caitlyn {cait:.3f} / Jinx {jinx:.3f}) - re-adjudicate "
                f"_AP_HYBRID_MARKSMAN membership per LEAP-07 DD1",
            )

    def test_greedy_liandrys_is_champion_invariant_not_an_ap_hybrid_artifact(self):
        """The DD1 CONTINGENCY probe (no off-axis AP-waste dock shipped).

        Zeri's greedy build surfaces Liandry's at #4, but the driver is the
        Dusk-and-Dawn (2510, 60 AP) prefix, not her kit: given the IDENTICAL
        prefix a pure-AD control (Jinx) credits Liandry's at least as much. A
        champion-invariant effect is not an AP-on-AD-marksman coherence artifact,
        so the contingency dock is NOT warranted - it would be a general
        item-valuation change owned by a different slice.
        """
        zeri = self._delta("Zeri", _LIANDRYS, current_item_ids=_GREEDY_PREFIX)
        jinx = self._delta("Jinx", _LIANDRYS, current_item_ids=_GREEDY_PREFIX)
        self.assertIsNotNone(zeri, "Zeri Liandry's row absent at the greedy prefix")
        self.assertIsNotNone(jinx, "Jinx Liandry's row absent at the greedy prefix")
        self.assertGreaterEqual(
            jinx, zeri,
            f"pure-AD control Jinx ({jinx:.3f}) credits Liandry's LESS than Zeri "
            f"({zeri:.3f}) at the shared prefix - the effect would then be "
            f"kit-driven and the DD1 contingency dock must be re-opened",
        )

    def test_class_predicate_is_consulted_on_the_carry_path(self):
        """REACHABILITY: the carry chokepoint actually calls the class predicate
        for a carry marksman (and not only for a hypothetical member)."""
        seen = []

        def spy(champ):
            seen.append(champ)
            return False

        rows = rank_items(self.snap, "Zeri", **_AP_CREDIT_CELL).ranked
        self.assertTrue(rows, "no engine rows for Zeri")
        with mock.patch.object(coherence_mod, "is_ap_hybrid_marksman", spy):
            coherence_rerank(rows, "Zeri", top=6)
        self.assertIn(
            "Zeri", seen,
            "coherence_rerank never consulted is_ap_hybrid_marksman on the "
            "carry path - the DD1 seam is not wired",
        )

    def test_member_exempts_ap_hybrid_items_from_the_waste_dock(self):
        """CLASS BEHAVIOR: for a MEMBER the AP-hybrid item set is ON-AXIS and
        exempt from the wasted-stat dock; every other item keeps its dock.

        Driven with a FORCED nonzero penalty so the exemption is observable (the
        live penalty for these ids happens to be 0.0 today, which would make the
        assertion vacuous)."""
        forced_pen = 1.0

        def fake_pen(item, champ, *a, **kw):
            return forced_pen if str(item) in _AP_HYBRID_ITEM_IDS | {_ER} else 0.0

        rows = [
            SimpleNamespace(item_id=_LIANDRYS, delta_dps=40.0, effective_score=0.0),
            SimpleNamespace(item_id=_ER, delta_dps=40.0, effective_score=0.0),
            SimpleNamespace(item_id=_STORM, delta_dps=29.0, effective_score=0.0),
        ]
        with mock.patch.object(coherence_mod, "anti_synergy_penalty", fake_pen):
            with mock.patch.object(
                coherence_mod, "is_ap_hybrid_marksman", lambda c: False
            ):
                non_member = [
                    str(r.item_id) for r in coherence_rerank(rows, "Zeri", top=3)
                ]
                er_non_member = coherence_mod._coherence_adj(rows[1], "Zeri")
            with mock.patch.object(
                coherence_mod, "is_ap_hybrid_marksman", lambda c: True
            ):
                member = [
                    str(r.item_id) for r in coherence_rerank(rows, "Zeri", top=3)
                ]
                er_member = coherence_mod._coherence_adj(rows[1], "Zeri")

        self.assertNotEqual(
            non_member[0], _LIANDRYS,
            f"non-member: the docked AP-hybrid item still leads: {non_member}",
        )
        self.assertEqual(
            member[0], _LIANDRYS,
            f"member: the exempt AP-hybrid item must lead: {member}",
        )
        # SCOPED: an off-set artifact (Essence Reaver) keeps its dock for a
        # member - the exemption applies only to _AP_HYBRID_ITEM_IDS.
        self.assertAlmostEqual(
            er_member, er_non_member, places=9,
            msg="membership must not exempt Essence Reaver (3508) from its dock",
        )

    def test_nonmember_carry_marksman_is_byte_identical_today(self):
        """Ship-state pin: with the allow-map EMPTY, a carry marksman's coherence
        top-6 is exactly what it was before the DD1 seam (the member branch is
        unreachable in production)."""
        for champ in ("Zeri", "Jinx", "Caitlyn"):
            rows = rank_items(self.snap, champ, **_AP_CREDIT_CELL).ranked
            self.assertTrue(rows, f"{champ}: no engine rows")
            live = [str(r.item_id) for r in coherence_rerank(rows, champ, top=6)]
            with mock.patch.object(
                coherence_mod, "is_ap_hybrid_marksman", lambda c: False
            ):
                forced_nonmember = [
                    str(r.item_id) for r in coherence_rerank(rows, champ, top=6)
                ]
            self.assertEqual(live, forced_nonmember, champ)


if __name__ == "__main__":
    unittest.main()
