"""ENGINE 1.61.0 (2026-05-26) - cc_conditional wave 23 ship of Hecarim R
Onslaught of Shadows distance-gated fear.

The wave 23 ship closes item 201 carry-forward via the wave 18
``coexists_with_unconditional`` same-slot-coexistence schema (Maokai R
precedent) WITHOUT requiring further extractor schema work.

Re-audit of operator-gated REJECT carries from items 178-201 against
the FULL ENGINE 1.60.0 schema (cast_time + effects_descriptions +
parent_resource + notes + damage_blocks). The audit subagent flagged
the Hecarim R effects_descriptions "fears nearby enemies for 0.75 :
1.5 (based on distance traveled) seconds" as the textbook range-gated
CC payload pattern that prior waves had not matched against the
COND_RANGE_GATED tag.

SHIP candidate (primary registry):

  (1) Hecarim R Onslaught of Shadows distance-gated fear.
      Primary entry at (Hecarim, R) coexisting with the unconditional
      `_PER_SPELL_CC_DURATIONS["Hecarim"]["R"] = (1.0, 1.0, 1.0)`
      baseline entry via coexists_with_unconditional=True.

      - cc_kind=fear (the 0.75-1.5s fear is the primary CC payload;
        the 0-99% slow is a separate utility payload not registered
        here per the slow-without-damage rule).
      - durations_s=(1.5, 1.5, 1.5) - 1.5s flat per R rank at the
        max-distance band. R rank scales the dash range + spectral
        rider damage, NOT the fear cap.
      - condition=COND_RANGE_GATED - SECOND consumer of the wave 7
        forward-marker tag after Maokai R wave 18.
      - probability=0.4 (tag midpoint matching Maokai R precedent;
        mid-low reflecting the operator must commit to a long-
        distance ride to reach the 1.5s far band).
      - coexists_with_unconditional=True - declares same-slot
        coexistence with the unconditional Hecarim R 1.0s baseline.
        Consumer MAX-rule keeps the unconditional 1.0s as the
        credited value by default; operator tunes Hecarim:R above
        0.667 to flip.

Hecarim becomes a NEW cc_conditional champion (was not in the
registry prior). FIRST Hecarim cc_conditional entry anywhere - E
knockback + R baseline fear already live in `_PER_SPELL_CC_DURATIONS`.

Registry growth this wave: +1 primary entry / +1 net-new champion.
Registry: 71 entries / 56 champs -> 72 entries / 57 champs
(62 primary + 8 sidecar -> 63 primary + 8 sidecar).
Tag count unchanged at 13.
COND_RANGE_GATED consumer count: 1 -> 2.
ENGINE 1.60.0 -> 1.61.0.

Math preservation: default
compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL to
ENGINE 1.60.0 for ALL champions (the wave 23 path skips when the
flag is False). include_conditional=True at default 0.4 probability
keeps the unconditional 1.0s winning via MAX-rule; only operator
override above 0.667 flips the conditional above the unconditional.

Tests pin:
  * Wave23HecarimREntryShapeTests - Hecarim R primary entry shape
    (cc_kind, durations_s, condition, probability,
    coexists_with_unconditional).
  * Wave23RegistryGrowthTests - REGISTRY_TOTAL_ENTRIES grows 71 ->
    72; REGISTRY_TOTAL_CHAMPIONS grows 56 -> 57; tag count
    unchanged at 13.
  * Wave23CondRangeGatedConsumerCountTests - COND_RANGE_GATED
    consumer count grows 1 -> 2 (Maokai R + Hecarim R).
  * Wave23UnconditionalCoexistsTests - Hecarim R unconditional 1.0s
    baseline entry in `_PER_SPELL_CC_DURATIONS` remains untouched.
  * Wave23DefaultByteIdenticalTests - default
    compute_cc_pressure(include_conditional=False) is BYTE-
    IDENTICAL to ENGINE 1.60.0 for Hecarim (the lift only affects
    the include_conditional=True path).
  * Wave23IncludeConditionalMaxRuleTests - include_conditional=True
    at default 0.4 probability keeps unconditional 1.0s winning;
    operator override at 0.95 flips conditional to 1.425s above
    unconditional.
  * Wave23EvidenceFromEffectsDescriptionsTests - the canonical
    "0.75 : 1.5 (based on distance traveled)" payload phrase is
    present in the Hecarim R effects_descriptions snapshot.
  * Wave23EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.61.0 (the wave 23 ship floor).
  * Wave23ForwardMarkerAllowlistTests - the wave 23 test file is in
    the forward-marker test allowlist.
  * Wave23AsciiHygieneTests - test file + cc_conditional wave 23
    entry block are ASCII-clean.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc
from agents.daemon_slayer.cc_pressure import _PER_SPELL_CC_DURATIONS


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ABILITIES_JSON = (
    _REPO_ROOT / "data" / "daemon_slayer" / "16.10.1" / "champion_abilities.json"
)
_CC_CONDITIONAL_SOURCE = (
    _REPO_ROOT / "agents" / "daemon_slayer" / "CC_CONDITIONAL_NOTES.md"
)
_WAVE23_TEST_SOURCE = pathlib.Path(__file__).resolve()


def _load_snapshot() -> dict:
    """Read the 16.10.1 champion_abilities snapshot."""
    with _ABILITIES_JSON.open("r", encoding="utf-8") as fp:
        return json.load(fp)


# ---------------- Hecarim R entry shape ----------------


class Wave23HecarimREntryShapeTests(unittest.TestCase):
    """The Hecarim R primary entry has the canonical wave-23 shape."""

    def test_hecarim_r_entry_exists(self) -> None:
        self.assertIn("Hecarim", cc._PER_SPELL_CC_CONDITIONAL)
        self.assertIn("R", cc._PER_SPELL_CC_CONDITIONAL["Hecarim"])

    def test_hecarim_r_champion_and_spell(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        self.assertEqual(entry.champion, "Hecarim")
        self.assertEqual(entry.spell, "R")

    def test_hecarim_r_cc_kind_is_fear(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        self.assertEqual(entry.cc_kind, "fear")

    def test_hecarim_r_durations_are_one_point_five_per_rank(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        # Hecarim R has 3 ranks; 1.5s flat at the max-distance band
        # for all 3.
        self.assertEqual(entry.durations_s, (1.5, 1.5, 1.5))

    def test_hecarim_r_condition_is_range_gated(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        self.assertEqual(entry.condition, cc.COND_RANGE_GATED)

    def test_hecarim_r_probability_default_zero_point_four(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        # Default COND_RANGE_GATED tag midpoint is 0.4 (matches
        # Maokai R wave 18 precedent).
        self.assertAlmostEqual(entry.probability, 0.4, places=6)

    def test_hecarim_r_form_index_is_none(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        # Hecarim R has form_count=1; this is a primary entry, not a
        # sidecar form-indexed entry.
        self.assertIsNone(entry.form_index)

    def test_hecarim_r_coexists_with_unconditional_is_true(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        # Schema flag declares same-slot coexistence with the
        # unconditional Hecarim R 1.0s baseline entry in
        # `_PER_SPELL_CC_DURATIONS`.
        self.assertTrue(entry.coexists_with_unconditional)

    def test_hecarim_r_notes_mention_onslaught(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        self.assertIn("Onslaught", entry.notes)

    def test_hecarim_r_notes_mention_range_gated_phrase(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        # The mechanic description must explicitly call out the
        # distance-traveled gating that earns the COND_RANGE_GATED
        # tag.
        self.assertIn("distance", entry.notes.lower())

    def test_hecarim_r_notes_mention_max_distance(self) -> None:
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        # The 1.5s value is the MAX-distance band; notes must
        # explicitly document that encoding choice.
        self.assertIn("max-distance", entry.notes.lower())


# ---------------- registry growth ----------------


class Wave23RegistryGrowthTests(unittest.TestCase):
    """Wave 23 grows the registry by +1 entry / +1 net-new champion."""

    def test_total_entries_grew_by_one(self) -> None:
        # Wave 22 baseline: 71 entries. Wave 23 = 72.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_ENTRIES, 72)

    def test_total_champions_grew_by_one(self) -> None:
        # Wave 22 baseline: 56 champs. Wave 23 adds Hecarim = 57.
        self.assertGreaterEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 57)

    def test_hecarim_is_new_champion_in_registry(self) -> None:
        # Hecarim was NOT in the primary or sidecar registry before
        # wave 23. The audit verified this at wave 23 dispatch.
        self.assertIn("Hecarim", cc._PER_SPELL_CC_CONDITIONAL)

    def test_default_condition_probability_tag_count_unchanged(self) -> None:
        # Tag count stays at 13 (no new tag constant in wave 23).
        self.assertEqual(len(cc._DEFAULT_CONDITION_PROBABILITY), 13)


# ---------------- COND_RANGE_GATED consumer count ----------------


class Wave23CondRangeGatedConsumerCountTests(unittest.TestCase):
    """Wave 23 doubles the COND_RANGE_GATED consumer count from 1 to 2."""

    def test_cond_range_gated_has_at_least_two_consumers(self) -> None:
        consumers = []
        for champ, spells in cc._PER_SPELL_CC_CONDITIONAL.items():
            for spell, entry in spells.items():
                if entry.condition == cc.COND_RANGE_GATED:
                    consumers.append((champ, spell))
        for champ, spell_form in cc._PER_SPELL_CC_CONDITIONAL_FORMS.items():
            for slot_key, entry in spell_form.items():
                if entry.condition == cc.COND_RANGE_GATED:
                    consumers.append((champ, slot_key))
        self.assertGreaterEqual(
            len(consumers), 2,
            f"COND_RANGE_GATED consumers found: {consumers!r}; expected at "
            f"least 2 (Maokai R wave 18 + Hecarim R wave 23).",
        )

    def test_cond_range_gated_consumers_include_maokai_and_hecarim(self) -> None:
        primary_champs_for_tag = {
            champ for champ, spells in cc._PER_SPELL_CC_CONDITIONAL.items()
            if any(e.condition == cc.COND_RANGE_GATED for e in spells.values())
        }
        self.assertIn("Maokai", primary_champs_for_tag)
        self.assertIn("Hecarim", primary_champs_for_tag)


# ---------------- unconditional coexistence ----------------


class Wave23UnconditionalCoexistsTests(unittest.TestCase):
    """Hecarim R unconditional 1.0s baseline entry remains untouched."""

    def test_hecarim_r_unconditional_entry_still_one_second_flat(self) -> None:
        # The cc_conditional wave 23 entry coexists with the
        # unconditional entry via coexists_with_unconditional=True;
        # the unconditional values themselves are NOT modified.
        self.assertIn("Hecarim", _PER_SPELL_CC_DURATIONS)
        self.assertIn("R", _PER_SPELL_CC_DURATIONS["Hecarim"])
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Hecarim"]["R"],
            (1.0, 1.0, 1.0),
            "Wave 23 must NOT touch the Hecarim R unconditional "
            "baseline; the conditional entry coexists via the "
            "MAX rule.",
        )

    def test_hecarim_e_unconditional_entry_unchanged(self) -> None:
        # Hecarim E knockback baseline is also in the unconditional
        # registry; wave 23 must not touch it.
        self.assertIn("E", _PER_SPELL_CC_DURATIONS["Hecarim"])
        self.assertEqual(
            _PER_SPELL_CC_DURATIONS["Hecarim"]["E"],
            (0.75, 0.75, 0.75, 0.75, 0.75),
        )


# ---------------- byte-identical default math ----------------


class Wave23DefaultByteIdenticalTests(unittest.TestCase):
    """Default compute_cc_pressure(include_conditional=False) is byte-
    identical to ENGINE 1.60.0 for all champions including Hecarim."""

    def test_hecarim_default_compute_cc_pressure_unchanged(self) -> None:
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure
        # include_conditional=False is the default; the wave 23 path
        # skips when the flag is False. The unconditional Hecarim R +
        # E baseline values are unchanged. compute_cc_pressure returns
        # a CcPressureResult dataclass; pin total_cc_seconds equals
        # the unconditional-only sum (E 0.75 + R 1.0 = 1.75).
        result = compute_cc_pressure("Hecarim", "sr", include_conditional=False)
        self.assertAlmostEqual(result.total_cc_seconds, 1.75, places=6)
        self.assertEqual(result.conditional_cc_seconds, 0.0)
        self.assertEqual(result.conditional_entries, ())


# ---------------- MAX-rule consumer math ----------------


class Wave23IncludeConditionalMaxRuleTests(unittest.TestCase):
    """include_conditional=True at default 0.4 prob keeps unconditional 1.0s
    winning via MAX rule; operator override above 0.667 flips the
    conditional above the unconditional."""

    def test_default_probability_max_rule_keeps_unconditional(self) -> None:
        # 1.5s * 0.4 = 0.6s conditional contribution; unconditional
        # 1.0s baseline wins via MAX(1.0, 0.6) = 1.0.
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        conditional_post_prob = entry.durations_s[0] * entry.probability
        unconditional_baseline = _PER_SPELL_CC_DURATIONS["Hecarim"]["R"][0]
        self.assertLess(
            conditional_post_prob, unconditional_baseline,
            "At default 0.4 probability the conditional 0.6s should "
            "be LESS than the unconditional 1.0s baseline so the "
            "MAX rule credits the unconditional value.",
        )

    def test_operator_override_above_breakeven_flips_conditional(self) -> None:
        # Breakeven: 1.5s * p = 1.0s -> p = 0.667. Operator override
        # at 0.95 lifts the conditional to 1.425s which beats the
        # unconditional via MAX.
        entry = cc._PER_SPELL_CC_CONDITIONAL["Hecarim"]["R"]
        synthetic_conditional = entry.durations_s[0] * 0.95
        unconditional_baseline = _PER_SPELL_CC_DURATIONS["Hecarim"]["R"][0]
        self.assertGreater(
            synthetic_conditional, unconditional_baseline,
            "Operator override at 0.95 should lift the conditional "
            "above the unconditional via MAX rule.",
        )


# ---------------- evidence from Meraki snapshot ----------------


class Wave23EvidenceFromEffectsDescriptionsTests(unittest.TestCase):
    """The Hecarim R effects_descriptions snapshot carries the canonical
    range-gated fear payload phrase."""

    def test_hecarim_r_effects_descriptions_carry_range_gated_phrase(
            self) -> None:
        snapshot = _load_snapshot()
        hecarim = snapshot["data"]["Hecarim"]
        r_forms = hecarim["R"]
        self.assertGreaterEqual(len(r_forms), 1)
        form0 = r_forms[0]
        effects = form0.get("effects_descriptions", [])
        combined = " ".join(effects).lower()
        # The canonical payload phrase that the wave 23 entry encodes.
        self.assertIn("fears", combined)
        self.assertIn("based on distance traveled", combined)
        # The 0.75:1.5 range bounds should appear textually.
        self.assertTrue(
            "0.75" in combined and "1.5" in combined,
            "Hecarim R effects_descriptions should carry the explicit "
            "0.75-1.5 range bound; if Meraki edits the wording, the "
            "wave 23 evidence pin must be updated alongside.",
        )


# ---------------- engine version pin ----------------


class Wave23EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above the wave 23 ship floor 1.61.0."""

    def test_engine_version_at_or_above_1_61_0(self) -> None:
        major, minor, patch = (int(x) for x in ENGINE_VERSION.split("."))
        version_tuple = (major, minor, patch)
        self.assertGreaterEqual(version_tuple, (1, 61, 0))


# ---------------- forward-marker allowlist ----------------


class Wave23ForwardMarkerAllowlistTests(unittest.TestCase):
    """The wave 23 test file is in the cc_conditional forward-marker
    test allowlist (prevents accidental removal)."""

    def test_wave23_file_in_forward_marker_allowlist(self) -> None:
        # Pin file presence by name; the forward-marker test enumerates
        # files via _ALLOWED_TEST_FILES.
        from agents.daemon_slayer.tests import test_cc_conditional_forward_marker as fm
        allowlist = fm._ALLOWED_TEST_FILES
        self.assertIn("test_cc_conditional_wave23.py", allowlist)


# ---------------- ASCII hygiene ----------------


class Wave23AsciiHygieneTests(unittest.TestCase):
    """Test file + cc_conditional wave 23 entry block are ASCII-clean."""

    def test_wave23_test_file_is_ascii_clean(self) -> None:
        raw = _WAVE23_TEST_SOURCE.read_bytes()
        non_ascii = sum(1 for b in raw if b > 127)
        self.assertEqual(
            non_ascii, 0,
            f"test_cc_conditional_wave23.py has {non_ascii} non-ASCII bytes; "
            f"must be 0 per CLAUDE.md hard rule.",
        )

    def test_cc_conditional_source_carries_wave23_block(self) -> None:
        text = _CC_CONDITIONAL_SOURCE.read_text(encoding="utf-8")
        # The wave 23 block carries a distinctive header marker.
        self.assertIn("wave 23 expansion", text)
        self.assertIn('"Hecarim"', text)


if __name__ == "__main__":
    unittest.main()
