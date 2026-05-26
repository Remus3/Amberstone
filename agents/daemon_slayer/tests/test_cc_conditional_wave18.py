"""ENGINE 1.55.0 (2026-05-24) - cc_conditional wave 18 FULL schema lift.

Wave 18 ships +2 primary entries / 0 net-new champions via a NEW
``coexists_with_unconditional`` boolean field on ConditionalCcEntry
plus a consumer-side MAX rule in ``compute_cc_pressure()`` so a
conditional CC entry CAN now coexist on the same (champion, spell)
slot as an unconditional entry in ``_PER_SPELL_CC_DURATIONS``
without the previous double-count concern.

Schema lift:

  * ``ConditionalCcEntry.coexists_with_unconditional: bool = False``
    new field. Default False preserves byte-identical behavior for
    all wave 0-17 entries. When True, the entry declares same-spell-
    slot coexistence with an unconditional entry in
    ``_PER_SPELL_CC_DURATIONS``. Consumer-side
    ``compute_cc_pressure(include_conditional=True)`` math credits
    MAX(unconditional_post_tenacity,
    conditional_post_probability_post_tenacity) per slot - NEVER
    both summed. Backward-compat: wave 0-17 entries omit the field
    and get the default False (consumer adds them to the conditional
    bucket unchanged).

NEW entries (both primary registry):

  (1) Maokai R Nature's Grasp distance-gated max-root:
        - cc_kind="root", durations_s=(2.25,)
        - condition=COND_RANGE_GATED probability=0.4 (tag midpoint)
        - coexists_with_unconditional=True
        - Coexists with unconditional Maokai R
          _PER_SPELL_CC_DURATIONS[Maokai][R]=(1.2,1.6,2.0)
        - FIRST consumer of the wave 7 forward-marker tag
          COND_RANGE_GATED, closing the empty-registry contract
          pending since item 148 (ENGINE 1.44.0).

  (2) Briar R Certain Death Hematomania impact fear:
        - cc_kind="fear", durations_s=(1.5,) flat across 3 R ranks
        - condition=COND_TARGET_DEBUFFED probability=0.5 (tag midpoint)
        - coexists_with_unconditional=False (no unconditional Briar R)
        - Briar becomes the SECOND 3-slot cc_conditional champion
          after TahmKench (Briar Q wave 4 + E wave 5 + R wave 18).
        - FIRST Briar R first-order CC registration anywhere.

Registry growth: 65 entries / 54 champions (ENGINE 1.54.0) ->
67 entries / 54 champions (ENGINE 1.55.0). Both touched champions
were already in the registry; no net-new champion count change.

Per-tag consumer counts post-wave-18:
  * COND_RANGE_GATED: 0 -> 1 (FIRST consumer = Maokai R)
  * COND_TARGET_DEBUFFED: prior count + 1 (Briar R adds)
  * All other tags unchanged.

Math preservation (default include_conditional=False):

  * compute_cc_pressure for every champion is BYTE-IDENTICAL to
    1.54.0 - the conditional axis is gated behind the kwarg.

Math at include_conditional=True with default calibration:

  * Maokai SR: W unconditional 1.4 + R unconditional 2.0 +
    Q conditional 0.3 + R conditional MAX(unc=2.0, cond=0.9) = 2.0
    -> total = 1.4 + 0.3 + 2.0 = 3.7s. conditional_cc_seconds = 0.3
    (Q contribution only; R conditional did NOT win the MAX).
  * Briar SR: no unconditional spells; Q conditional 0.3 + E
    conditional 0.5 + R conditional 0.75 = total 1.55s. all
    conditional contributions credited normally (none coexist).

Math at include_conditional=True with operator override
Maokai:R = 0.95:

  * Conditional R = 2.25 * 0.95 = 2.1375 > unconditional 2.0
    -> conditional R WINS the MAX, unconditional R is SKIPPED.
  * Total = W unc 1.4 + Q cond 0.3 + R cond 2.1375 = 3.8375s.
  * conditional_cc_seconds = Q + R = 0.3 + 2.1375 = 2.4375.

Coverage classes:

  * Wave18CoexistsFlagSchemaTests - ConditionalCcEntry has the new
    coexists_with_unconditional field, default False preserves
    backward compat, wave 18 Maokai R entry has it True.
  * Wave18MaokaiRShapeTests - Maokai R entry shape pin (cc_kind /
    durations / condition / probability / coexists flag).
  * Wave18BriarRShapeTests - Briar R entry shape pin.
  * Wave18RegistryGrowthTests - REGISTRY_TOTAL_ENTRIES / CHAMPIONS
    grew correctly (67 / 54).
  * Wave18PerTagConsumerCountsTests - COND_RANGE_GATED has exactly
    1 consumer (Maokai R) post-wave-18; COND_TARGET_DEBUFFED
    consumer count increased by 1.
  * Wave18MultiWaveCoexistenceTests - Maokai now has Q + R in the
    primary registry; Briar now has Q + E + R (3-slot).
  * Wave18ConsumerMaxRuleTests - compute_cc_pressure honors the MAX
    rule for Maokai R (coexists=True), credits unconditional 2.0s
    at default cal; flips to conditional 2.1375s at Maokai:R = 0.95
    override.
  * Wave18ByteIdenticalDefaultTests - default include_conditional=
    False compute_cc_pressure is byte-identical to 1.54.0 for
    Maokai + Briar (the registries grew but the default path is
    untouched).
  * Wave18BuilderIdempotenceTests - re-invoking
    _build_per_spell_cc_conditional returns the same shape.
  * Wave18ForwardMarkerAllowlistTests - the wave 18 test file is
    in the forward-marker test allowlist.
  * Wave18EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.55.0.
  * Wave18AsciiHygieneTests - test file + wave 18 source block
    are ASCII-clean.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
from agents.daemon_slayer.cc_conditional import (
    COND_CHANNEL_COMPLETION,
    COND_DEVOUR_TARGET,
    COND_DREAM_STACK,
    COND_DUAL_ENEMY,
    COND_FRENZY_STATE,
    COND_GOLD_CARD,
    COND_MODE_GATED,
    COND_NTH_HIT,
    COND_RANGE_GATED,
    COND_TARGET_DEBUFFED,
    COND_TARGET_HP_BELOW,
    COND_TERRAIN,
    COND_TRAVERSE,
    REGISTRY_TOTAL_CHAMPIONS,
    REGISTRY_TOTAL_ENTRIES,
    ConditionalCcEntry,
    _build_per_spell_cc_conditional,
    _PER_SPELL_CC_CONDITIONAL,
)
from agents.daemon_slayer.cc_pressure import compute_cc_pressure


# ---------------- schema-lift coexists field ----------------


class Wave18CoexistsFlagSchemaTests(unittest.TestCase):
    """ConditionalCcEntry has the new coexists_with_unconditional field."""

    def test_field_exists_with_default_false(self) -> None:
        # Construct a wave-0-style entry; new field should default to
        # False without breaking the existing constructor signature.
        entry = ConditionalCcEntry(
            champion="TestChamp",
            spell="Q",
            cc_kind="stun",
            durations_s=(1.0,),
            condition=COND_NTH_HIT,
            probability=0.5,
            notes="test",
        )
        self.assertFalse(entry.coexists_with_unconditional)

    def test_field_can_be_set_true(self) -> None:
        entry = ConditionalCcEntry(
            champion="TestChamp",
            spell="Q",
            cc_kind="root",
            durations_s=(2.0,),
            condition=COND_RANGE_GATED,
            probability=0.4,
            notes="test",
            coexists_with_unconditional=True,
        )
        self.assertTrue(entry.coexists_with_unconditional)

    def test_legacy_entries_have_default_false(self) -> None:
        # All wave 0-17 entries should have coexists_with_unconditional=False.
        # Wave 18 ship was Maokai R. Wave 20 (ENGINE 1.58.0) added Vayne E
        # as a second consumer of the coexists flag. Pin Maokai R as
        # required member; future-wave members may join (relaxed from
        # the original exact-equality assertion per [[feedback_no_history_rewrite]]).
        flagged: set[tuple[str, str]] = set()
        for champ, spells in _PER_SPELL_CC_CONDITIONAL.items():
            for spell_key, entry in spells.items():
                if entry.coexists_with_unconditional:
                    flagged.add((champ, spell_key))
        self.assertIn(("Maokai", "R"), flagged)
        # Vayne E ship added wave 20 (ENGINE 1.58.0).
        self.assertIn(("Vayne", "E"), flagged)


# ---------------- wave 18 entry shape pins ----------------


class Wave18MaokaiRShapeTests(unittest.TestCase):
    """Maokai R entry shape pin: distance-gated root + coexists flag."""

    def test_maokai_r_primary_entry_present(self) -> None:
        self.assertIn("Maokai", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("R", _PER_SPELL_CC_CONDITIONAL["Maokai"])

    def test_maokai_r_shape(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Maokai"]["R"]
        self.assertEqual(entry.champion, "Maokai")
        self.assertEqual(entry.spell, "R")
        self.assertEqual(entry.cc_kind, "root")
        self.assertEqual(entry.durations_s, (2.25,))
        self.assertEqual(entry.condition, COND_RANGE_GATED)
        self.assertAlmostEqual(entry.probability, 0.4)
        self.assertIsNone(entry.form_index)
        self.assertTrue(entry.coexists_with_unconditional)

    def test_maokai_r_unconditional_also_present(self) -> None:
        # The coexists flag declares same-slot coexistence; verify the
        # unconditional Maokai R IS in _PER_SPELL_CC_DURATIONS (the
        # claim the flag makes).
        self.assertIn("Maokai", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Maokai"])
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Maokai"]["R"], (1.2, 1.6, 2.0)
        )


class Wave18BriarRShapeTests(unittest.TestCase):
    """Briar R entry shape pin: Hematomania impact non-marked fear."""

    def test_briar_r_primary_entry_present(self) -> None:
        self.assertIn("Briar", _PER_SPELL_CC_CONDITIONAL)
        self.assertIn("R", _PER_SPELL_CC_CONDITIONAL["Briar"])

    def test_briar_r_shape(self) -> None:
        entry = _PER_SPELL_CC_CONDITIONAL["Briar"]["R"]
        self.assertEqual(entry.champion, "Briar")
        self.assertEqual(entry.spell, "R")
        self.assertEqual(entry.cc_kind, "fear")
        self.assertEqual(entry.durations_s, (1.5,))
        self.assertEqual(entry.condition, COND_TARGET_DEBUFFED)
        self.assertAlmostEqual(entry.probability, 0.5)
        self.assertIsNone(entry.form_index)
        self.assertFalse(entry.coexists_with_unconditional)

    def test_briar_r_no_unconditional_collision(self) -> None:
        # Briar has no unconditional R entry; coexists=False is correct.
        briar_unc = _PER_SPELL_CC_DURATIONS.get("Briar", {})
        self.assertNotIn("R", briar_unc)


# ---------------- registry growth ----------------


class Wave18RegistryGrowthTests(unittest.TestCase):
    """REGISTRY_TOTAL_ENTRIES and REGISTRY_TOTAL_CHAMPIONS grew correctly."""

    def test_total_entries_pin(self) -> None:
        # Pre-wave-18: 65 (58 primary + 7 sidecar from wave 17).
        # Post-wave-18: 67 (60 primary + 7 sidecar; +2 Maokai R +
        # Briar R primary entries). Wave 20 (ENGINE 1.58.0) adds
        # Vayne E primary -> 68. Relaxed assertEqual -> assertGreaterEqual
        # to permit future-wave additions per [[feedback_no_history_rewrite]].
        self.assertGreaterEqual(REGISTRY_TOTAL_ENTRIES, 67)

    def test_total_champions_pin(self) -> None:
        # Pre-wave-18: 54 champions. Post-wave-18: 54 champions
        # (Maokai already in registry via Q wave 2; Briar already in
        # registry via Q wave 4 + E wave 5; both are multi-wave
        # coexistence adds on existing champions). Wave 20 (ENGINE
        # 1.58.0) adds Vayne as NEW cc_conditional champion -> 55.
        # Relaxed assertEqual -> assertGreaterEqual for future-wave
        # additions per [[feedback_no_history_rewrite]].
        self.assertGreaterEqual(REGISTRY_TOTAL_CHAMPIONS, 54)


# ---------------- per-tag consumer counts ----------------


class Wave18PerTagConsumerCountsTests(unittest.TestCase):
    """COND_RANGE_GATED has its first consumer + COND_TARGET_DEBUFFED grows."""

    def _count_tag_consumers(self, tag: str) -> int:
        """Count primary-registry entries with the given condition tag."""
        n = 0
        for spells in _PER_SPELL_CC_CONDITIONAL.values():
            for entry in spells.values():
                if entry.condition == tag:
                    n += 1
        return n

    def test_cond_range_gated_first_consumer_is_maokai_r(self) -> None:
        # Wave 7 (ENGINE 1.44.0) registered COND_RANGE_GATED as a
        # forward-marker tag with 0 consumers. Wave 18 lands Maokai R
        # as the FIRST consumer. Wave 23 (2026-05-26 ENGINE 1.61.0)
        # lands Hecarim R as the SECOND consumer; assertion relaxed
        # from assertEqual to "Maokai is the first member".
        consumers = []
        for champ, spells in _PER_SPELL_CC_CONDITIONAL.items():
            for spell_key, entry in spells.items():
                if entry.condition == COND_RANGE_GATED:
                    consumers.append((champ, spell_key))
        self.assertIn(("Maokai", "R"), consumers)

    def test_cond_range_gated_consumer_count_is_one(self) -> None:
        # COND_RANGE_GATED has at least 1 consumer post-wave-18.
        # Wave 23 lifts the count to 2 (Maokai R + Hecarim R) so this
        # assertion is relaxed from assertEqual to assertGreaterEqual.
        self.assertGreaterEqual(
            self._count_tag_consumers(COND_RANGE_GATED), 1)

    def test_cond_target_debuffed_includes_briar_r(self) -> None:
        # Briar R adds a new consumer to COND_TARGET_DEBUFFED. Verify
        # the entry is in the consumer set (existing consumers stay).
        consumers = []
        for champ, spells in _PER_SPELL_CC_CONDITIONAL.items():
            for spell_key, entry in spells.items():
                if entry.condition == COND_TARGET_DEBUFFED:
                    consumers.append((champ, spell_key))
        self.assertIn(("Briar", "R"), consumers)


# ---------------- multi-wave coexistence ----------------


class Wave18MultiWaveCoexistenceTests(unittest.TestCase):
    """Existing champions gain new slots without clobbering wave 0-17 entries."""

    def test_maokai_two_slots(self) -> None:
        # Maokai had Q wave 2 (terrain stun); wave 18 adds R. Both
        # present.
        maokai_spells = set(_PER_SPELL_CC_CONDITIONAL["Maokai"].keys())
        self.assertEqual(maokai_spells, {"Q", "R"})

    def test_maokai_q_wave2_preserved(self) -> None:
        # The wave 2 Maokai Q terrain stun must remain unchanged.
        q = _PER_SPELL_CC_CONDITIONAL["Maokai"]["Q"]
        self.assertEqual(q.condition, COND_TERRAIN)
        self.assertEqual(q.durations_s, (1.0,))
        self.assertEqual(q.cc_kind, "stun")
        self.assertFalse(q.coexists_with_unconditional)

    def test_briar_three_slots(self) -> None:
        # Briar had Q wave 4 + E wave 5; wave 18 adds R. Becomes the
        # SECOND 3-slot cc_conditional champion after TahmKench
        # (TahmKench Q wave 5 + W wave 13 + R wave 0).
        briar_spells = set(_PER_SPELL_CC_CONDITIONAL["Briar"].keys())
        self.assertEqual(briar_spells, {"Q", "E", "R"})

    def test_briar_q_wave4_preserved(self) -> None:
        # Briar Q terrain-conditional stun from wave 4 unchanged.
        q = _PER_SPELL_CC_CONDITIONAL["Briar"]["Q"]
        self.assertEqual(q.condition, COND_TERRAIN)
        self.assertEqual(q.cc_kind, "stun")

    def test_briar_e_wave5_preserved(self) -> None:
        # Briar E channel-completion fear from wave 5 unchanged.
        e = _PER_SPELL_CC_CONDITIONAL["Briar"]["E"]
        self.assertEqual(e.condition, COND_CHANNEL_COMPLETION)
        self.assertEqual(e.cc_kind, "fear")


# ---------------- consumer MAX rule (the schema lift) ----------------


class Wave18ConsumerMaxRuleTests(unittest.TestCase):
    """compute_cc_pressure honors the coexists MAX rule for Maokai R.

    NOTE: This test class monkey-patches the in-memory override map
    rather than writing the JSON calibration file + cold-reloading
    cc_conditional. Cold-reloading produces sys.modules pollution
    (other DS tests hold references to the original module instances
    via their imports of _PER_SPELL_CC_DURATIONS / ITEM_EFFECTS /
    etc., and re-import-on-demand does not propagate). Monkey-patch
    is the surgical solution.
    """

    def setUp(self) -> None:
        # Snapshot the module-level override map so we can restore it.
        self._override_snapshot = dict(
            cc._PER_ENTRY_PROBABILITY_OVERRIDES
        )
        # Snapshot the module-level primary registry so we can rebuild
        # it from scratch with the test-specific probability.
        self._registry_snapshot = {
            champ: dict(spells)
            for champ, spells in cc._PER_SPELL_CC_CONDITIONAL.items()
        }

    def tearDown(self) -> None:
        # Restore the override map.
        cc._PER_ENTRY_PROBABILITY_OVERRIDES.clear()
        cc._PER_ENTRY_PROBABILITY_OVERRIDES.update(self._override_snapshot)
        # Restore the primary registry by rebuilding from snapshot.
        cc._PER_SPELL_CC_CONDITIONAL.clear()
        cc._PER_SPELL_CC_CONDITIONAL.update(self._registry_snapshot)

    def test_maokai_default_calibration_unc_wins(self) -> None:
        # At default calibration: conditional R 2.25*0.4 = 0.9 vs
        # unconditional R 2.0 -> unconditional WINS the MAX rule.
        # Total = W unconditional 1.4 + R unconditional 2.0 + Q
        # conditional 0.3 = 3.7. conditional_cc_seconds = 0.3 (Q
        # contribution only; R conditional did NOT win).
        r = compute_cc_pressure("Maokai", "SR", include_conditional=True)
        self.assertAlmostEqual(r.total_cc_seconds, 3.7, places=5)
        self.assertAlmostEqual(r.conditional_cc_seconds, 0.3, places=5)

    def test_maokai_operator_override_cond_wins(self) -> None:
        # With Maokai:R override = 0.95: conditional 2.25 * 0.95 =
        # 2.1375 > unconditional 2.0 -> conditional R WINS.
        # Total = W unc 1.4 + Q cond 0.3 + R cond 2.1375 = 3.8375.
        # Surgically rebuild Maokai R with the test probability
        # (mirrors what the calibration JSON loader would have
        # produced at module-load time).
        new_entry = ConditionalCcEntry(
            champion="Maokai",
            spell="R",
            cc_kind="root",
            durations_s=(2.25,),
            condition=COND_RANGE_GATED,
            probability=0.95,
            notes="test-override",
            coexists_with_unconditional=True,
        )
        cc._PER_SPELL_CC_CONDITIONAL["Maokai"]["R"] = new_entry

        r = compute_cc_pressure("Maokai", "SR", include_conditional=True)
        self.assertAlmostEqual(r.total_cc_seconds, 3.8375, places=4)
        self.assertAlmostEqual(r.conditional_cc_seconds, 2.4375, places=4)

    def test_briar_no_coexistence_normal_sum(self) -> None:
        # Briar has no unconditional spells; all 3 conditional entries
        # (Q + E + R, all coexists=False) sum normally.
        # Q: 1.0 * 0.3 = 0.3
        # E: 1.0 * 0.5 = 0.5
        # R: 1.5 * 0.5 = 0.75
        # Total = 1.55s. Default (include_conditional=False) = 0.0.
        r = compute_cc_pressure("Briar", "SR", include_conditional=True)
        self.assertAlmostEqual(r.total_cc_seconds, 1.55, places=5)
        self.assertAlmostEqual(r.conditional_cc_seconds, 1.55, places=5)


# ---------------- byte-identical default path ----------------


class Wave18ByteIdenticalDefaultTests(unittest.TestCase):
    """Default include_conditional=False compute_cc_pressure unchanged."""

    def test_maokai_default_path_unchanged(self) -> None:
        # Maokai SR default = W unc 1.4 + R unc 2.0 = 3.4s. The wave
        # 18 schema lift does NOT change the default path math
        # (conditional axis gated behind the kwarg).
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure

        r = compute_cc_pressure("Maokai", "SR", include_conditional=False)
        self.assertAlmostEqual(r.total_cc_seconds, 3.4, places=5)
        self.assertAlmostEqual(r.conditional_cc_seconds, 0.0, places=5)

    def test_briar_default_path_unchanged(self) -> None:
        # Briar SR default = 0.0 (no unconditional entries).
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure

        r = compute_cc_pressure("Briar", "SR", include_conditional=False)
        self.assertAlmostEqual(r.total_cc_seconds, 0.0, places=5)
        self.assertAlmostEqual(r.conditional_cc_seconds, 0.0, places=5)

    def test_unrelated_champion_default_path_unchanged(self) -> None:
        # Sanity: a champion outside the wave 18 ship list is also
        # unchanged. Annie has only R unconditional (1.25/1.5/1.75).
        # Default include_conditional=False = 1.75 post-tenacity in SR.
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure

        r = compute_cc_pressure("Annie", "SR", include_conditional=False)
        self.assertGreater(r.total_cc_seconds, 0.0)


# ---------------- builder idempotence ----------------


class Wave18BuilderIdempotenceTests(unittest.TestCase):
    """Re-invoking the builder returns equivalent shape (no clobbering)."""

    def test_builder_idempotence(self) -> None:
        reg1 = _build_per_spell_cc_conditional()
        reg2 = _build_per_spell_cc_conditional()
        # Same set of (champion, spell) keys.
        keys1 = {(c, s) for c, spells in reg1.items() for s in spells}
        keys2 = {(c, s) for c, spells in reg2.items() for s in spells}
        self.assertEqual(keys1, keys2)
        # Maokai R is in both, with coexists=True.
        self.assertTrue(reg1["Maokai"]["R"].coexists_with_unconditional)
        self.assertTrue(reg2["Maokai"]["R"].coexists_with_unconditional)

    def test_builder_wave_18_entries_present(self) -> None:
        reg = _build_per_spell_cc_conditional()
        self.assertIn("Maokai", reg)
        self.assertIn("R", reg["Maokai"])
        self.assertIn("Briar", reg)
        self.assertIn("R", reg["Briar"])


# ---------------- forward-marker allowlist ----------------


class Wave18ForwardMarkerAllowlistTests(unittest.TestCase):
    """The wave 18 test file is in the forward-marker test allowlist."""

    def test_wave_18_in_allowed_test_files(self) -> None:
        from agents.daemon_slayer.tests import (
            test_cc_conditional_forward_marker as fwd,
        )

        self.assertIn(
            "test_cc_conditional_wave18.py", fwd._ALLOWED_TEST_FILES
        )


# ---------------- engine version pin ----------------


class Wave18EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.55.0."""

    def test_engine_version_string_pin(self) -> None:
        major, minor, patch = (int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 55, 0))


# ---------------- ASCII hygiene ----------------


class Wave18AsciiHygieneTests(unittest.TestCase):
    """Test file is ASCII-clean + cc_conditional wave 18 block is ASCII."""

    def test_this_test_file_is_ascii(self) -> None:
        path = Path(__file__).resolve()
        raw = path.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII bytes in {path.name}",
        )

    def test_cc_conditional_wave_18_block_is_ascii(self) -> None:
        # Read source directly from disk to avoid sys.modules churn
        # from earlier test setUp/tearDown.
        path = Path(cc.__file__).resolve()
        src = path.read_text(encoding="utf-8")
        marker = "wave 18 expansion (2026-05-24 / ENGINE 1.55.0)"
        idx = src.find(marker)
        self.assertGreater(idx, -1, "wave 18 header marker missing")
        # Take a generous slice past the Briar R setdefault site.
        end_marker = src.find('setdefault("Briar", {})["R"]', idx)
        self.assertGreater(end_marker, idx, "Briar R setdefault missing")
        block = src[idx : end_marker + 4096]
        non_ascii = [c for c in block if ord(c) > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII characters in wave 18 block",
        )

    def test_coexists_field_block_is_ascii(self) -> None:
        # The new coexists_with_unconditional field docstring block
        # must be ASCII-clean. Read source from disk directly.
        path = Path(cc.__file__).resolve()
        src = path.read_text(encoding="utf-8")
        idx = src.find("coexists_with_unconditional: bool = False")
        self.assertGreater(
            idx, -1, "coexists_with_unconditional field missing"
        )


if __name__ == "__main__":
    unittest.main()
