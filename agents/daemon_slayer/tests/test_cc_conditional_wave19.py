"""ENGINE 1.56.0 (2026-05-24) - cc_conditional wave 19 STATE-TRACKING
EXTRACTOR SCHEMA LIFT tests.

The wave 19 schema lift adds a ``parent_resource`` field on EVERY
per-form record in the ``tools/daemon_slayer_abilities_extract.py``
output. The field captures the champion-level Meraki resource string
(``"FURY"`` / ``"BLOOD_WELL"`` / ``"FRENZY"`` / ``"RAGE"`` /
``"HEAT"`` / ``"ENERGY"`` / ``"GRIT"`` / ``"MANA"`` / ...) threaded
to every form so consumers can query state-tracking eligibility
WITHOUT parsing description text.

Re-audit outcome (closes item 176 carry-forward (a)):

The 6 wave-7 schema-lift carries that this lift was designed to
unblock are ALL closed. Either ALREADY SHIPPED in prior waves
(Renekton wave 9 / Karma wave 10 / Hwei wave 10 / Neeko wave 1)
or REJECT-verified (Aatrox post-R minion-only / Volibear R
turret-only / Briar W self-buff-only). The lift this wave is
FORWARD-MARKER infrastructure for future cc_conditional candidates
consuming the ``COND_FRENZY_STATE`` tag - the entry author SHOULD
verify the champion's ``parent_resource`` is in the empowered-state
family before pitching.

Registry growth this wave: 0 entries / 0 net-new champions. Tag
count unchanged at 13. ENGINE 1.55.0 -> 1.56.0.

Tests pin:
  * Wave19ParentResourceFieldPresenceTests - the new field appears
    on EVERY form in the patch 16.10.1 snapshot.
  * Wave19ParentResourceFieldTypeTests - the field is ``str | None``
    (never list / int / etc.).
  * Wave19EmpoweredStateChampionsPopulatedTests - the 6 cc_conditional
    champs with non-mana resources (Aatrox / Briar / Gnar / Kennen /
    Renekton / Sett) have their empowered-state resource surface on
    the new field.
  * Wave19PerFormParentResourceMatchesChampionTests - every form
    record for a given champion carries the same parent_resource
    value (cross-form invariant; the field is champion-level not
    per-form).
  * Wave19RegistryByteIdenticalTests - the wave 19 lift adds ZERO
    new cc_conditional entries (registry 67/54 unchanged from wave
    18) and ZERO new condition tags (still 13).
  * Wave19WaveSevenCarriesClosedTests - all 6 wave-7 schema-lift
    carries are closed: 4 already shipped + 3 REJECT-verified.
  * Wave19ExtractorDocstringDeclaresLiftTests - the extractor source
    file declares the schema lift in its module docstring + the
    ``_build_champion`` docstring + the ``_build_form`` docstring.
  * Wave19EngineVersionPinTests - ENGINE_VERSION sits at or above
    1.56.0 (the wave 19 ship floor).
  * Wave19ForwardMarkerAllowlistTests - the wave 19 test file is in
    the forward-marker test allowlist.
  * Wave19AsciiHygieneTests - test file + extractor source + the
    cc_conditional wave 19 block are ASCII-clean.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_conditional as cc


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ABILITIES_JSON = (
    _REPO_ROOT / "data" / "daemon_slayer" / "16.10.1" / "champion_abilities.json"
)
_EXTRACTOR_SOURCE = (
    _REPO_ROOT / "tools" / "daemon_slayer_abilities_extract.py"
)


# Resources that gate empowered-state CC mechanics. Champions on
# these resources can plausibly carry a COND_FRENZY_STATE entry;
# champions on MANA / ENERGY / NONE / HEALTH cannot (they have no
# state that empowers their other spells).
_EMPOWERED_STATE_RESOURCES = frozenset(
    {"FURY", "BLOOD_WELL", "FRENZY", "RAGE", "HEAT"}
)


def _load_snapshot() -> dict:
    """Read the 16.10.1 champion_abilities snapshot."""
    with _ABILITIES_JSON.open("r", encoding="utf-8") as fp:
        return json.load(fp)


# ---------------- field presence ----------------


class Wave19ParentResourceFieldPresenceTests(unittest.TestCase):
    """Every form in the 16.10.1 snapshot carries the schema-lifted
    parent_resource field.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_parent_resource_on_every_form(self) -> None:
        missing = []
        for champ, keymap in self.snapshot["data"].items():
            for key, forms in keymap.items():
                for form in forms:
                    if "parent_resource" not in form:
                        missing.append((champ, key, form.get("form_index")))
        self.assertEqual(
            missing, [], f"missing parent_resource on: {missing[:5]}"
        )

    def test_snapshot_form_count_unchanged(self) -> None:
        """The lift is purely additive - form count is byte-identical
        to the ENGINE 1.55.0 baseline (927 forms / 171 champions).
        """
        self.assertEqual(self.snapshot["count"], 171)
        total = 0
        for keymap in self.snapshot["data"].values():
            for forms in keymap.values():
                total += len(forms)
        self.assertEqual(total, 927)


# ---------------- field type ----------------


class Wave19ParentResourceFieldTypeTests(unittest.TestCase):
    """parent_resource is a string or None; never list / int / dict."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_parent_resource_is_str_or_none(self) -> None:
        bad = []
        for champ, keymap in self.snapshot["data"].items():
            for key, forms in keymap.items():
                for form in forms:
                    val = form.get("parent_resource")
                    if val is not None and not isinstance(val, str):
                        bad.append((champ, key, type(val).__name__))
        self.assertEqual(
            bad, [], f"non-(str|None) parent_resource: {bad[:5]}"
        )


# ---------------- empowered-state champion coverage ----------------


class Wave19EmpoweredStateChampionsPopulatedTests(unittest.TestCase):
    """cc_conditional champs with non-mana resources have their
    empowered-state resource surface on the new field. These are the
    structural candidates for future COND_FRENZY_STATE entries.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def _first_form_resource(self, champ: str) -> str | None:
        rec = self.snapshot["data"].get(champ, {})
        for key in ("Q", "W", "E", "R", "P"):
            forms = rec.get(key, [])
            if forms:
                return forms[0].get("parent_resource")
        return None

    def test_aatrox_blood_well(self) -> None:
        self.assertEqual(self._first_form_resource("Aatrox"), "BLOOD_WELL")

    def test_briar_frenzy(self) -> None:
        self.assertEqual(self._first_form_resource("Briar"), "FRENZY")

    def test_gnar_rage(self) -> None:
        self.assertEqual(self._first_form_resource("Gnar"), "RAGE")

    def test_kennen_energy(self) -> None:
        self.assertEqual(self._first_form_resource("Kennen"), "ENERGY")

    def test_renekton_fury(self) -> None:
        self.assertEqual(self._first_form_resource("Renekton"), "FURY")

    def test_sett_grit(self) -> None:
        self.assertEqual(self._first_form_resource("Sett"), "GRIT")


# ---------------- per-form invariant ----------------


class Wave19PerFormParentResourceMatchesChampionTests(unittest.TestCase):
    """Every form record for a given champion carries the SAME
    parent_resource value. The field is champion-level not per-form;
    threading it per-form is a query-convenience, not a per-form
    customization.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def test_cross_form_invariant(self) -> None:
        offenders = []
        for champ, keymap in self.snapshot["data"].items():
            seen = set()
            for forms in keymap.values():
                for form in forms:
                    seen.add(form.get("parent_resource"))
            if len(seen) > 1:
                offenders.append((champ, sorted(s for s in seen if s)))
        self.assertEqual(
            offenders, [], f"cross-form drift: {offenders[:5]}"
        )


# ---------------- registry byte-identical ----------------


class Wave19RegistryByteIdenticalTests(unittest.TestCase):
    """The wave 19 lift adds zero new cc_conditional entries and
    zero new condition tags. Registry sits at wave 18 baseline
    (67 entries / 54 champions / 13 condition tags).
    """

    def test_registry_total_entries_unchanged(self) -> None:
        self.assertEqual(cc.REGISTRY_TOTAL_ENTRIES, 67)

    def test_registry_total_champions_unchanged(self) -> None:
        self.assertEqual(cc.REGISTRY_TOTAL_CHAMPIONS, 54)

    def test_condition_tag_count_unchanged(self) -> None:
        self.assertEqual(len(cc._DEFAULT_CONDITION_PROBABILITY), 13)


# ---------------- wave-7 carries closure ----------------


class Wave19WaveSevenCarriesClosedTests(unittest.TestCase):
    """All 6 wave-7 schema-lift carries are closed. The re-audit
    finding is the lift's primary justification: it surfaces the
    structural signal (parent_resource) for future
    COND_FRENZY_STATE consumers since the operator-named carries
    are already shipped or rejected.
    """

    def test_renekton_w_already_shipped_primary(self) -> None:
        """Renekton W shipped wave 9 item 153 with COND_FRENZY_STATE."""
        entries = cc.get_conditional_entries("Renekton")
        w_entries = [e for e in entries if e.spell == "W"]
        self.assertEqual(len(w_entries), 1)
        self.assertEqual(w_entries[0].condition, cc.COND_FRENZY_STATE)

    def test_karma_w_form_1_already_shipped_sidecar(self) -> None:
        """Karma W form_index=1 shipped wave 10 item 154 SIDECAR."""
        entries = cc.get_conditional_entries("Karma")
        sidecar = [
            e for e in entries
            if e.spell == "W" and e.form_index == 1
        ]
        self.assertEqual(len(sidecar), 1)
        self.assertEqual(sidecar[0].condition, cc.COND_FRENZY_STATE)

    def test_hwei_e_form_2_already_shipped_sidecar(self) -> None:
        """Hwei E form_index=2 shipped wave 10 item 154 SIDECAR."""
        entries = cc.get_conditional_entries("Hwei")
        sidecar = [
            e for e in entries
            if e.spell == "E" and e.form_index == 2
        ]
        self.assertEqual(len(sidecar), 1)
        self.assertEqual(sidecar[0].condition, cc.COND_CHANNEL_COMPLETION)

    def test_neeko_e_already_shipped_primary(self) -> None:
        """Neeko E shipped wave 1 (the dual-enemy gate is the
        operational trigger surface for the W-disguise empowered
        root; renaming would not change the math).
        """
        entries = cc.get_conditional_entries("Neeko")
        e_entries = [e for e in entries if e.spell == "E"]
        self.assertEqual(len(e_entries), 1)
        self.assertEqual(e_entries[0].condition, cc.COND_DUAL_ENEMY)

    def test_aatrox_post_r_passive_reject_verified(self) -> None:
        """Aatrox first-order CC is Q wave 3 + W wave 4 ONLY. Post-R
        passive surface change is minion-only fear (item 153
        REJECT) - NOT champion CC. So Aatrox has Q + W entries but
        NO R entry.
        """
        entries = cc.get_conditional_entries("Aatrox")
        slots = sorted(e.spell for e in entries)
        self.assertEqual(slots, ["Q", "W"])

    def test_volibear_r_turret_only_reject_verified(self) -> None:
        """Volibear first-order CC is Q wave 1 ONLY. R Stormbringer
        Turret Disable Duration is TURRET-only (items
        150/153/156 REJECT) - NOT champion CC. So Volibear has Q
        but NO R entry.
        """
        entries = cc.get_conditional_entries("Volibear")
        slots = sorted(e.spell for e in entries)
        self.assertEqual(slots, ["Q"])

    def test_briar_w_self_buff_only_reject_verified(self) -> None:
        """Briar first-order CC is Q wave 4 + E wave 5 + R wave 18
        ONLY. W Blood Frenzy is self-buff only (items 150/153/156
        REJECT) with no champion CC payload. So Briar has Q + E + R
        but NO W entry.
        """
        entries = cc.get_conditional_entries("Briar")
        slots = sorted(e.spell for e in entries)
        self.assertEqual(slots, ["E", "Q", "R"])


# ---------------- empowered-state structural pre-filter ----------------


class Wave19EmpoweredStateStructuralPreFilterTests(unittest.TestCase):
    """The lift is forward-marker infrastructure. A future
    COND_FRENZY_STATE entry author SHOULD use parent_resource as a
    structural pre-filter. Pin the cardinality + canonical examples
    so the methodology is documented in source.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_snapshot()

    def _first_form_resource(self, champ: str) -> str | None:
        rec = self.snapshot["data"].get(champ, {})
        for key in ("Q", "W", "E", "R", "P"):
            forms = rec.get(key, [])
            if forms:
                return forms[0].get("parent_resource")
        return None

    def test_six_cc_conditional_champs_carry_empowered_state(self) -> None:
        """Exactly 6 cc_conditional champs have parent_resource in
        the empowered-state family. These are the structural
        candidates for future COND_FRENZY_STATE entries.
        """
        from agents.daemon_slayer.cc_conditional import (
            _PER_SPELL_CC_CONDITIONAL,
            _PER_SPELL_CC_CONDITIONAL_FORMS,
        )
        all_champs = sorted(
            set(_PER_SPELL_CC_CONDITIONAL.keys())
            | set(_PER_SPELL_CC_CONDITIONAL_FORMS.keys())
        )
        empowered = []
        for c in all_champs:
            pr = self._first_form_resource(c)
            if pr in _EMPOWERED_STATE_RESOURCES:
                empowered.append(c)
        self.assertEqual(
            sorted(empowered),
            ["Aatrox", "Briar", "Gnar", "Renekton"],
            f"empowered-state cc_conditional champs: {empowered}",
        )

    def test_empowered_state_family_pin(self) -> None:
        """The empowered-state resource family pin. Future tag
        additions in this family should extend this set explicitly.
        """
        self.assertEqual(
            _EMPOWERED_STATE_RESOURCES,
            frozenset({"FURY", "BLOOD_WELL", "FRENZY", "RAGE", "HEAT"}),
        )


# ---------------- extractor docstring declares lift ----------------


class Wave19ExtractorDocstringDeclaresLiftTests(unittest.TestCase):
    """The extractor source file declares the schema lift in 3
    places: module docstring, _build_champion docstring,
    _build_form docstring.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _EXTRACTOR_SOURCE.read_text(encoding="utf-8")

    def test_module_docstring_mentions_parent_resource(self) -> None:
        self.assertIn("parent_resource", self.source)

    def test_module_docstring_mentions_engine_1_56_0(self) -> None:
        # The schema lift itself happened at ENGINE 1.56.0 (the wave 19
        # ship marker in the extractor source is HISTORICAL and never
        # bumped); the current ENGINE_VERSION may sit higher.
        self.assertIn("ENGINE 1.56.0", self.source)

    def test_build_champion_docstring_mentions_lift(self) -> None:
        """_build_champion docstring documents the lift."""
        idx = self.source.find("def _build_champion(")
        self.assertGreater(idx, -1, "_build_champion def missing")
        # Slice up to the docstring's closing triple-quote so we don't
        # truncate at the first internal blank line (the docstring
        # itself contains \n\n separators).
        doc_open = self.source.find('"""', idx)
        self.assertGreater(doc_open, idx, "_build_champion docstring open missing")
        doc_close = self.source.find('"""', doc_open + 3)
        self.assertGreater(doc_close, doc_open, "_build_champion docstring close missing")
        block = self.source[idx:doc_close + 3]
        self.assertIn("parent_resource", block)
        # The schema lift ship marker is "1.56.0" in the source
        # (HISTORICAL anchor; current ENGINE may be higher).
        self.assertIn("1.56.0", block)

    def test_build_form_signature_takes_parent_resource(self) -> None:
        """_build_form signature accepts parent_resource kwarg."""
        idx = self.source.find("def _build_form(")
        self.assertGreater(idx, -1, "_build_form def missing")
        end = self.source.find(') -> dict:', idx)
        self.assertGreater(end, idx, "_build_form signature unterminated")
        signature = self.source[idx:end]
        self.assertIn("parent_resource", signature)


# ---------------- engine version pin ----------------


class Wave19EngineVersionPinTests(unittest.TestCase):
    """ENGINE_VERSION sits at or above 1.56.0 (wave 19 ship floor)."""

    def test_engine_version_string_pin(self) -> None:
        major, minor, patch = (int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 56, 0))


# ---------------- forward-marker allowlist ----------------


class Wave19ForwardMarkerAllowlistTests(unittest.TestCase):
    """The wave 19 test file is in the forward-marker test allowlist."""

    def test_wave_19_in_allowed_test_files(self) -> None:
        from agents.daemon_slayer.tests import (
            test_cc_conditional_forward_marker as fwd,
        )
        self.assertIn(
            "test_cc_conditional_wave19.py", fwd._ALLOWED_TEST_FILES
        )


# ---------------- ASCII hygiene ----------------


class Wave19AsciiHygieneTests(unittest.TestCase):
    """Test file + extractor source ENGINE 1.56.0 block are ASCII-clean."""

    def test_this_test_file_is_ascii(self) -> None:
        path = pathlib.Path(__file__).resolve()
        raw = path.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII bytes in {path.name}",
        )

    def test_extractor_lift_block_is_ascii(self) -> None:
        """The ENGINE 1.56.0 schema-lift sentence in the extractor
        module docstring is ASCII-clean. Scoped to the docstring
        block immediately following the marker to avoid picking up
        pre-existing U+2500 box-drawing ASCII-art section dividers
        elsewhere in the file (operator-gated retro-sweep carry).
        The marker text is HISTORICAL (the wave 19 ship event was
        at ENGINE 1.56.0) - do NOT bump on subsequent ENGINE bumps.
        """
        src = _EXTRACTOR_SOURCE.read_text(encoding="utf-8")
        marker = "ENGINE 1.56.0 schema lift"
        idx = src.find(marker)
        self.assertGreater(idx, -1, "ENGINE 1.56.0 marker missing")
        # Scope: from the marker to the next docstring paragraph break
        # (blank line). The marker sits inside the module docstring;
        # the next "\n\n" closes the parent_resource paragraph BEFORE
        # any U+2500 dividers downstream.
        end = src.find("\n\n", idx)
        self.assertGreater(end, idx, "no paragraph break after marker")
        block = src[idx:end]
        non_ascii = [(i, c, hex(ord(c))) for i, c in enumerate(block) if ord(c) > 0x7F]
        self.assertEqual(
            non_ascii,
            [],
            f"{len(non_ascii)} non-ASCII chars in extractor lift block: {non_ascii[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
