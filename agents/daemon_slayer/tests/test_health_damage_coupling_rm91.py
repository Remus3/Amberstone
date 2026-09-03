"""RM-91 T1: the champion HEALTH -> DAMAGE coupling seam (DEFAULT-OFF).

THE DEFECT
----------
``ehp.py`` imports no abilities module and reads zero ``damage_blocks``, so a
champion whose OWN KIT spends its health as damage (Shen E: 11 percent bonus
health as physical; Sejuani W: 12 percent maximum health as physical) gets that
second, genuinely-real payment credited NOWHERE. The tank objective prices a
health item on the DENOMINATOR axis only.

This is the HEALTH-axis twin of the shipped RESIST-axis lever
(``_resist_damage_coupling`` / RM-87). The two registries are DISJOINT - zero
champion overlap - and ride separate flags on purpose: a champion that converts
resists and a champion that converts health are different populations, and one
merged flag would arm a credit the other champion's kit never earns.

WHAT THIS SEAM DOES
-------------------
``rank_items_by_ehp(apply_health_damage_coupling=True, health_coupling_strength=X)``
folds a normalized, sort-ONLY credit into ``_base_key``, following the existing
``_conv_key`` / ``_coupling_key`` precedent: no row VALUE is ever mutated, only
the ordering view. DEFAULT-OFF and byte-identical when off.

THE GUARDS HERE
---------------
1. The NAMED byte-identical control - the full ``rank_items_by_ehp`` payload for
   all 11 seeded champions with the flags OMITTED still hashes to the digest
   captured from the PRE-CHANGE tree, and a second arm with the flags sent at
   strength 0.0 matches too.
2. The registry population is exactly 11 - a silent seed drift fails.
3. Eleven per-champion armed tests, one each. Never one generic tank shape.
4. Poppy + Leona are the negative controls - byte-identical even armed.
5. Sett + Sion are pinned OUT of the registry, so the refutation is not
   re-widened from memory.
6. The credit scales with the conversion magnitude - Shen (11.0) earns strictly
   more than Tahm Kench (4.0) at an equal health delta.
7. A non-positive health delta is returned unchanged (Frozen Heart 3110 is a
   resist-only candidate and grants zero health).
8. The Arena mirror credits its OWN DDragon stat line (R161 doctrine B).
9. A labelled KNOWN-LIMIT pin: T1 is MONOTONE in ``delta_max_hp``, so it can
   raise health over resists but can never move a 600-HP item above a 1000-HP
   one. That limit is asserted so it stays a documented boundary rather than
   being re-discovered later as a bug. Crediting an ITEM's own caster-HP proc is
   a separate follow-on (T2) and is out of scope for this slice.

OFFLINE ONLY: no live :8860, no network.
"""
from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import unittest
from unittest import mock

from agents.daemon_slayer import ehp as ehp_mod
from agents.daemon_slayer._health_damage_coupling import (
    _CHAMPION_HEALTH_DAMAGE_COUPLING,
    HealthDamageCouplingEntry,
    coupled_health_points,
    health_damage_coupling,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.rank import mode_filter_note

_SNAP = None

# PIN THE DATA, NOT THE CODE. _PRE_CHANGE_DIGESTS below are SHA-256 of a full
# ranking payload, so they are only meaningful against the snapshot they were
# captured on. Following the live patch would re-break all 26 controls on every
# DDragon refresh for reasons that have nothing to do with this feature - at
# 16.15.1 they moved purely from upstream item/champion stat drift plus a
# fresher CDragon ratio sidecar (VERIFIED 2026-07-30: all 13 reproduce
# byte-exactly when recomputed against 16.14.1). What these controls exist to
# prove is that _health_damage_coupling is INERT when off, and that proof needs
# a fixed substrate.
_DIGEST_PATCH = "16.14.1"


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load(patch=_DIGEST_PATCH)
    return _SNAP


# The 11 tank-primary champions whose kits spend their OWN health as damage,
# re-derived from data/daemon_slayer/16.14.1/champion_abilities.json.
_SEEDED = (
    "Braum", "Chogath", "DrMundo", "KSante", "Maokai", "Nunu",
    "Sejuani", "Shen", "Skarner", "TahmKench", "Zac",
)

# Probe hygiene (reference_ds_probe_empty_build_artifact): NEVER an empty item
# list - an empty build under-ranks amp / complementary items and manufactures
# artifacts. Two real early-tank items, matching the RM-87 sibling test.
_BUILD = ("3068", "3047")     # Sunfire Aegis + Plated Steelcaps

# NO truncation (reference_ds_probe_depth_top40_truncation): a finite top_n is
# applied AFTER the sort, so a reorder changes WHICH rows survive the cut and the
# OFF / ON row SETS stop being comparable.
_TOP_N = None
_LEVEL = 13

# Matched BY ID, never by name. The Arena pool carries 44-prefixed MIRRORS of the
# SR items; 443083 is Warmog's Armor's Arena mirror and it credits its OWN
# DDragon stat line (R161 doctrine B), not 3083's.
_ARENA_WARMOGS = "443083"

# Operator-tunable lever magnitude. DEFAULT-OFF at 0.0; these runs engage it.
# Measured floor for a visible reorder on the SMALLEST seeded converter
# (Braum, 2.5 percent of TOTAL max health) - the larger converters move at far
# less, so one shared value keeps the eleven per-champion tests uniform.
_STRENGTH = 8.0

# SHA-256 of the full ``rank_items_by_ehp(...).to_dict()`` payload captured from
# the PRE-CHANGE tree (before _health_damage_coupling existed), canonicalized as
# json.dumps(sort_keys=True, separators=(",", ":")).
#
# ONE documented exclusion: the additive ``delta_max_hp`` observability key is
# popped from every row before hashing, because a new key in ``to_dict`` cannot
# by construction be present in a pre-change capture. Its OFF value is pinned
# separately at 0.0 for every row, so nothing is hidden by the exclusion - what
# the digest proves is that no VALUE and no ORDERING moved.
_PRE_CHANGE_DIGESTS = {
    "Braum": "c4ea805c625d088709c96f01794682b3c8c7108e59c295c4513b078036e29bd0",
    "Chogath": "a7718e59d817c39582afd7c47dda0a125222f8be4ac6904bb0445a7fa297d919",
    "DrMundo": "a4ecb38659035d5923d5ffd02165e86d7e103e61cf571873edda13d926b5844d",
    "KSante": "a343ef94765b80af567b8953eaa632dd7d3b05b673f9370ed5b35db41945bbec",
    "Maokai": "43de6657b666cf7e8c896fb39fe3e1ebda723cc688bed671327610eba85ca589",
    "Nunu": "85934d03467573fd9a6f6fe80979a5523315612d51a738fc6f3d47081edf0055",
    "Sejuani": "884c3d67e58931eb154c3bfaa96fcf3a0835c3353fed5ee640221c6dfe0a04eb",
    "Shen": "b36698736900ddbfb955b606b713f1e2ab80a1bfc691e6377e9ff715c70cb42e",
    "Skarner": "1afdfc5545ce0a57596f894d517f4c63a3c762442274a5d55f006598e03d5f77",
    "TahmKench": "63dd1376e8822a8dab51635b10f87aa1e579aee8fcd0772ebc83212571d41275",
    "Zac": "be688c76b145e2038924eebe2d327b481925372755d334c9d45afc61a2e39b6d",
    "Poppy": "e81fcc5bfe8cc2c056006f32109bbb89c821c4f0e88d3d1b7f86f29c838e92f7",
    "Leona": "d3f206395933c77c4c06241bcf77716e2fac5649e842ce13342462231b1cff48",
}


def _rank(champion: str, mode: str = "SR", **kwargs):
    return rank_items_by_ehp(
        _snap(),
        champion_id=champion,
        level=_LEVEL,
        current_item_ids=list(_BUILD),
        mode=mode,
        enemy_ad_share=0.5,
        enemy_ap_share=0.4,
        top_n=_TOP_N,
        **kwargs,
    )


def _armed(champion: str, strength: float = _STRENGTH, mode: str = "SR"):
    return _rank(
        champion,
        mode=mode,
        apply_health_damage_coupling=True,
        health_coupling_strength=strength,
    )


def _order(result) -> tuple[str, ...]:
    return tuple(r.item_id for r in result.ranked)


def _rows(result) -> tuple[tuple, ...]:
    return tuple(
        (
            r.item_id,
            r.delta_ehp,
            r.new_ehp,
            r.ehp_per_1k_gold,
            r.delta_cc_blended_ehp,
            r.delta_team_blended_ehp,
            r.survivability_score,
            r.delta_armor,
            r.delta_mr,
            r.delta_max_hp,
        )
        for r in result.ranked
    )


def _digest(result, drop_notes: bool = False) -> str:
    payload = result.to_dict()
    for row in payload["ranked"]:
        row.pop("delta_max_hp", None)
        # RM-118 mana lane (2026-08-02): the same exclusion, same reason - a
        # to_dict key introduced AFTER this digest was captured cannot by
        # construction appear in the pre-change capture. Its OFF value is pinned
        # at 0.0 in the mana lane's own test module, so nothing is hidden.
        row.pop("delta_max_mp", None)
    # RM-329 (2026-09-03): the mode-provenance note is the NOTES-side twin of
    # the row-key exclusions above, and it is dropped for the identical reason -
    # a note first emitted AFTER this digest was captured cannot by construction
    # appear in a pre-change capture. It is removed BY VALUE (never a prefix
    # sweep) so no other note can hide behind the exclusion, and it is asserted
    # in full by test_mode_provenance_notes_rm329.py rather than lost here.
    payload["notes"] = [
        n for n in payload.get("notes", ())
        if n != mode_filter_note(payload["mode"])
    ]
    if drop_notes:
        # For an ARMED-but-inert run the ONLY legitimate payload difference is
        # the operator-facing "ON but inert" note, which is positive evidence
        # the lane ran and declined. Callers that drop it assert the note
        # separately rather than losing it.
        payload.pop("notes", None)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _notes_free_digest_off(champion: str) -> str:
    return _digest(_rank(champion), drop_notes=True)


class RegistryPopulationTests(unittest.TestCase):
    """Exactly 11 tank-primary champions, re-derived from the patch data."""

    def test_population_is_exactly_eleven(self) -> None:
        self.assertEqual(len(_CHAMPION_HEALTH_DAMAGE_COUPLING), 11)
        self.assertEqual(tuple(sorted(_CHAMPION_HEALTH_DAMAGE_COUPLING)), tuple(sorted(_SEEDED)))

    def test_every_entry_is_shaped_and_sourced(self) -> None:
        for champ in _SEEDED:
            with self.subTest(champ=champ):
                entry = health_damage_coupling(champ)
                self.assertIsNotNone(entry, msg=f"{champ} must be seeded")
                self.assertIn(entry.pct_base, ("total", "bonus"))
                self.assertGreater(entry.max_hp_pct + entry.bonus_hp_pct, 0.0)
                self.assertGreater(entry.conditional_probability, 0.0)
                self.assertLessEqual(entry.conditional_probability, 1.0)
                self.assertTrue(entry.attribute, msg=f"{champ} needs the cited attribute")
                self.assertTrue(entry.note, msg=f"{champ} needs a sourced note")

    def test_one_value_per_champion_matches_the_basis_it_names(self) -> None:
        # The double-count trap: a champion is seeded on exactly ONE of the two
        # health bases, and ``pct_base`` names that same basis, so the credit's
        # numerator and its normalizing pool always read the same pool.
        for champ in _SEEDED:
            with self.subTest(champ=champ):
                entry = health_damage_coupling(champ)
                if entry.pct_base == "total":
                    self.assertGreater(entry.max_hp_pct, 0.0)
                    self.assertEqual(entry.bonus_hp_pct, 0.0)
                else:
                    self.assertGreater(entry.bonus_hp_pct, 0.0)
                    self.assertEqual(entry.max_hp_pct, 0.0)

    def test_ksante_all_out_is_not_a_permanent_conversion(self) -> None:
        # K'Sante R "All Out" is gated on the ult FORM (120/100/80s cooldown,
        # 15s window), so a 1.0 cadence would over-model it outright.
        entry = health_damage_coupling("KSante")
        self.assertIsNotNone(entry)
        self.assertLess(entry.conditional_probability, 1.0)

    def test_fail_soft_on_unknown_and_empty(self) -> None:
        self.assertIsNone(health_damage_coupling(""))
        self.assertIsNone(health_damage_coupling("NotAChampion"))

    def test_registries_are_disjoint_from_the_rm87_resist_lever(self) -> None:
        from agents.daemon_slayer._resist_damage_coupling import (
            _CHAMPION_RESIST_DAMAGE_COUPLING,
        )
        self.assertEqual(
            set(_CHAMPION_HEALTH_DAMAGE_COUPLING)
            & set(_CHAMPION_RESIST_DAMAGE_COUPLING),
            set(),
            msg="the health and resist levers must never overlap on a champion",
        )


class DocumentedRejectTests(unittest.TestCase):
    """The rejects are pinned so they are not re-widened from memory."""

    def test_sett_and_sion_are_not_in_the_registry(self) -> None:
        # champion_abilities.json 16.14.1: Sett Q "Knuckle Down" carries
        # target_max_hp_pct 1.0 / 2.0 and R "The Show Stopper"
        # target_bonus_hp_pct 40/50/60; Sion W "Soul Furnace" carries
        # target_max_hp_pct 14.0. Those read the TARGET's health, which is
        # already modelled and does NOT make the caster's own health offensive.
        for champ in ("Sett", "Sion"):
            with self.subTest(champ=champ):
                self.assertIsNone(health_damage_coupling(champ))

    def test_other_archetype_routes_stay_out(self) -> None:
        # Gnar + Volibear are Fighter-primary -> ds.hybrid, which already prices
        # this via apply_ad_axis_ability_damage. Vladimir is Mage-primary ->
        # ds.ability evaluates his blocks directly. Wiring any here double-counts.
        for champ in ("Gnar", "Volibear", "Vladimir"):
            with self.subTest(champ=champ):
                self.assertIsNone(health_damage_coupling(champ))


class CoupledPointsTests(unittest.TestCase):

    def test_linear_and_probability_free(self) -> None:
        entry = HealthDamageCouplingEntry(bonus_hp_pct=10.0, pct_base="bonus",
                                          conditional_probability=0.5)
        # Probability-FREE: the caller applies conditional_probability ONCE.
        self.assertAlmostEqual(coupled_health_points(entry, 0.0, 400.0), 40.0)
        entry_total = HealthDamageCouplingEntry(max_hp_pct=12.0, pct_base="total")
        self.assertAlmostEqual(coupled_health_points(entry_total, 500.0, 0.0), 60.0)

    def test_negative_health_floors_at_zero(self) -> None:
        entry = HealthDamageCouplingEntry(max_hp_pct=12.0, bonus_hp_pct=12.0)
        self.assertAlmostEqual(coupled_health_points(entry, -500.0, -500.0), 0.0)

    def test_credit_scales_with_conversion_magnitude(self) -> None:
        # Guard 6: Shen (11.0 percent bonus health) must earn strictly more than
        # Tahm Kench (4.0 percent bonus health) at an EQUAL health delta.
        shen = health_damage_coupling("Shen")
        tk = health_damage_coupling("TahmKench")
        self.assertEqual(shen.pct_base, tk.pct_base)
        self.assertEqual(shen.conditional_probability, tk.conditional_probability)
        delta = 400.0
        self.assertGreater(
            coupled_health_points(shen, delta, delta),
            coupled_health_points(tk, delta, delta),
        )
        self.assertAlmostEqual(
            coupled_health_points(shen, delta, delta) / coupled_health_points(tk, delta, delta),
            11.0 / 4.0,
        )


class SignatureConventionTests(unittest.TestCase):

    def test_kwargs_are_appended_with_defaults_off(self) -> None:
        params = inspect.signature(rank_items_by_ehp).parameters
        names = tuple(params)
        i = names.index("apply_health_damage_coupling")
        self.assertEqual(
            names[i:i + 2],
            ("apply_health_damage_coupling", "health_coupling_strength"),
        )
        for later in names[i:]:
            self.assertIsNot(
                params[later].default, inspect.Parameter.empty,
                f"{later} follows the RM-91 pair but has no default",
            )
        self.assertIs(params["apply_health_damage_coupling"].default, False)
        self.assertEqual(params["health_coupling_strength"].default, 0.0)

    def test_delta_max_hp_is_appended_at_the_very_end_with_a_default(self) -> None:
        fields = list(dataclasses.fields(ehp_mod.EhpRankedItem))
        names = [f.name for f in fields]
        # The RM-118 mana lane (2026-08-02) appended ``delta_max_mp`` after this
        # field, so ``delta_max_hp`` is no longer the literal tail. What this
        # guard protects is that it was APPENDED with a default and never
        # re-inserted mid-class (the item-216 rule), which the index-from-the-end
        # assertion plus the defaults sweep below both still prove. A new row
        # field appends AFTER these and re-offsets this guard.
        self.assertEqual(names[-1], "delta_max_mp")
        self.assertEqual(names[-2], "delta_max_hp")
        self.assertEqual(fields[-1].default, 0.0)
        self.assertEqual(fields[-2].default, 0.0)
        # Everything from the first defaulted field onward must keep a default -
        # a required field appearing after one is what breaks every existing
        # positional construction (the item-216 rule).
        seen_default = False
        for f in fields:
            has_default = (
                f.default is not dataclasses.MISSING
                or f.default_factory is not dataclasses.MISSING
            )
            if has_default:
                seen_default = True
            elif seen_default:
                self.fail(
                    f"{f.name} has no default but follows a defaulted field"
                )

    def test_delta_max_hp_is_serialized(self) -> None:
        row = ehp_mod.EhpRankedItem(
            item_id="3083", item_name="Warmog's Armor", gold=3100,
            delta_ehp=1.0, new_ehp=2.0, ehp_per_1k_gold=0.5,
            is_terminal=True, tags=(),
        )
        self.assertIn("delta_max_hp", row.to_dict())
        self.assertEqual(row.to_dict()["delta_max_hp"], 0.0)

    def test_negative_strength_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _rank("Shen", apply_health_damage_coupling=True,
                  health_coupling_strength=-1.0)


class ByteIdenticalControlTests(unittest.TestCase):
    """Guard 1: the NAMED pre-change control, both arms."""

    def test_flags_omitted_match_the_pre_change_digest(self) -> None:
        for champ, digest in _PRE_CHANGE_DIGESTS.items():
            with self.subTest(champ=champ):
                self.assertEqual(_digest(_rank(champ)), digest)

    def test_flags_sent_at_zero_strength_match_the_pre_change_digest(self) -> None:
        for champ, digest in _PRE_CHANGE_DIGESTS.items():
            with self.subTest(champ=champ):
                armed_zero = _rank(
                    champ,
                    apply_health_damage_coupling=True,
                    health_coupling_strength=0.0,
                )
                self.assertEqual(_digest(armed_zero), digest)

    def test_flag_false_with_a_positive_strength_is_still_inert(self) -> None:
        # BOTH must be engaged. A strength with no flag is an exact no-op.
        for champ in ("Shen", "Sejuani"):
            with self.subTest(champ=champ):
                self.assertEqual(
                    _rows(_rank(champ)),
                    _rows(_rank(champ, apply_health_damage_coupling=False,
                                health_coupling_strength=_STRENGTH)),
                )

    def test_off_leaves_the_observability_field_at_identity(self) -> None:
        for row in _rank("Shen").ranked:
            self.assertEqual(row.delta_max_hp, 0.0, msg=row.item_id)


class PerChampionArmedTests(unittest.TestCase):
    """Guard 3: one armed test EACH for all 11 - never one generic tank shape."""

    def _assert_armed(self, champ: str) -> None:
        off = _rank(champ)
        on = _armed(champ)
        # Sort-only: the row VALUES are untouched, only the order moves.
        self.assertEqual(
            {r.item_id: r.delta_ehp for r in off.ranked},
            {r.item_id: r.delta_ehp for r in on.ranked},
            msg=f"{champ}: sort-only seam must not mutate row values",
        )
        self.assertNotEqual(_order(off), _order(on), msg=f"{champ}: ON must reorder")
        # The observability field is populated and reads the health axis.
        by_id = {r.item_id: r for r in on.ranked}
        warmogs = by_id.get("3083")
        self.assertIsNotNone(warmogs, msg=f"{champ}: Warmog's must be pooled")
        self.assertGreater(
            warmogs.delta_max_hp, 0.0,
            msg=f"{champ}: a pure-health item must show a positive health delta",
        )

    def test_braum(self) -> None:
        self._assert_armed("Braum")

    def test_chogath(self) -> None:
        self._assert_armed("Chogath")

    def test_drmundo(self) -> None:
        self._assert_armed("DrMundo")

    def test_ksante(self) -> None:
        self._assert_armed("KSante")

    def test_maokai(self) -> None:
        self._assert_armed("Maokai")

    def test_nunu(self) -> None:
        self._assert_armed("Nunu")

    def test_sejuani(self) -> None:
        self._assert_armed("Sejuani")

    def test_shen(self) -> None:
        self._assert_armed("Shen")

    def test_skarner(self) -> None:
        self._assert_armed("Skarner")

    def test_tahmkench(self) -> None:
        self._assert_armed("TahmKench")

    def test_zac(self) -> None:
        self._assert_armed("Zac")


class NegativeControlTests(unittest.TestCase):
    """Guard 4: neither Poppy nor Leona carries a caster-HP damage block."""

    def _assert_inert(self, champ: str) -> None:
        off, on = _rank(champ), _armed(champ)
        self.assertEqual(_order(off), _order(on))
        self.assertEqual(_rows(off), _rows(on))
        # Every row value and the whole ordering are unmoved. The ONLY payload
        # difference an armed-but-unseeded champion may carry is the
        # operator-facing "ON but inert" note.
        self.assertEqual(_digest(on, drop_notes=True), _notes_free_digest_off(champ))
        self.assertTrue(
            any("apply_health_damage_coupling=ON but inert" in n for n in on.notes),
            msg=f"{champ}: the inert note must say the lane declined",
        )

    def test_poppy_is_byte_identical_armed(self) -> None:
        # Poppy Q "Hammer Shock" carries target_max_hp_pct 9.0 / 18.0 - the
        # TARGET's health, not hers.
        self._assert_inert("Poppy")

    def test_leona_is_byte_identical_armed(self) -> None:
        # Leona carries NO caster-health damage block of any kind at 16.14.1.
        self._assert_inert("Leona")


class CodePathProvenanceTests(unittest.TestCase):
    """Prove the NEW code path produced the delta - not incidental float drift."""

    def test_off_never_consults_the_registry(self) -> None:
        with mock.patch.object(
            ehp_mod, "health_damage_coupling", wraps=health_damage_coupling
        ) as spy:
            _rank("Shen")
        spy.assert_not_called()

    def test_on_consults_the_registry_with_the_champion_id(self) -> None:
        with mock.patch.object(
            ehp_mod, "health_damage_coupling", wraps=health_damage_coupling
        ) as spy:
            _armed("Shen")
        spy.assert_called_once_with("Shen")

    def test_a_none_lookup_collapses_the_seam_to_a_no_op(self) -> None:
        off = _rank("Shen")
        with mock.patch.object(ehp_mod, "health_damage_coupling", return_value=None):
            on = _armed("Shen")
        self.assertEqual(_order(off), _order(on))

    def test_perturbing_the_magnitude_changes_the_order(self) -> None:
        shipped = _armed("Shen")
        entry = _CHAMPION_HEALTH_DAMAGE_COUPLING["Shen"]
        tiny = HealthDamageCouplingEntry(
            max_hp_pct=0.0,
            bonus_hp_pct=0.1,
            pct_base=entry.pct_base,
            conditional_probability=entry.conditional_probability,
            attribute=entry.attribute,
            note="mutation-check stub",
        )
        with mock.patch.dict(
            _CHAMPION_HEALTH_DAMAGE_COUPLING, {"Shen": tiny}, clear=False
        ):
            mutated = _armed("Shen")
        self.assertNotEqual(
            _order(shipped), _order(mutated),
            msg="the order must depend on the registry magnitude",
        )


class ResistOnlyCandidateTests(unittest.TestCase):
    """Guard 7: a non-positive health delta is returned unchanged."""

    def test_frozen_heart_grants_no_health_and_takes_no_credit(self) -> None:
        on = _armed("Shen")
        by_id = {r.item_id: r for r in on.ranked}
        frozen_heart = by_id.get("3110")
        self.assertIsNotNone(frozen_heart, msg="Frozen Heart 3110 must be pooled")
        self.assertAlmostEqual(frozen_heart.delta_max_hp, 0.0, places=6)
        # It IS a resist roller, though - the two levers read disjoint
        # quantities, and the health lever declining here is the whole point.
        base = compute_ehp(
            _snap(), champion_id="Shen", level=_LEVEL,
            item_ids=list(_BUILD), mode="SR",
            enemy_ad_share=0.5, enemy_ap_share=0.4,
        )
        with_fh = compute_ehp(
            _snap(), champion_id="Shen", level=_LEVEL,
            item_ids=list(_BUILD) + ["3110"], mode="SR",
            enemy_ad_share=0.5, enemy_ap_share=0.4,
        )
        self.assertGreater(with_fh.armor, base.armor)
        self.assertAlmostEqual(with_fh.hp, base.hp, places=6)


class ArenaMirrorTests(unittest.TestCase):
    """Guard 8: the Arena mirror credits its OWN statline (R161 doctrine B)."""

    def test_arena_reorders_and_reads_the_arena_stat_line(self) -> None:
        off = _rank("Shen", mode="ARENA")
        on = _armed("Shen", mode="ARENA")
        self.assertNotEqual(_order(off), _order(on))
        by_id = {r.item_id: r for r in on.ranked}
        # Matched BY ID: the Arena pool carries the 44-prefixed MIRROR of
        # Warmog's Armor (443083), not the SR id 3083, and the mirror is scored
        # off its own DDragon stat line (R161 doctrine B).
        self.assertNotIn("3083", by_id, msg="the SR id must not be Arena-pooled")
        warmogs = by_id.get(_ARENA_WARMOGS)
        self.assertIsNotNone(warmogs)
        # The credited health delta must equal the ARENA-resolved delta computed
        # independently off the MIRROR id - never the SR twin's.
        base = compute_ehp(
            _snap(), champion_id="Shen", level=_LEVEL,
            item_ids=list(_BUILD), mode="ARENA",
            enemy_ad_share=0.5, enemy_ap_share=0.4,
        )
        with_item = compute_ehp(
            _snap(), champion_id="Shen", level=_LEVEL,
            item_ids=list(_BUILD) + [_ARENA_WARMOGS], mode="ARENA",
            enemy_ad_share=0.5, enemy_ap_share=0.4,
        )
        self.assertAlmostEqual(
            warmogs.delta_max_hp, with_item.hp - base.hp, places=6
        )
        self.assertGreater(warmogs.delta_max_hp, 0.0)


class KnownLimitTests(unittest.TestCase):
    """KNOWN LIMIT - deliberately pinned, NOT a bug to fix in this slice.

    T1 credits the CANDIDATE's health delta through a factor that is monotone
    increasing in that delta. So for any two candidates where A already ranks
    above B on the raw metric AND A grants at least as much health as B, arming
    the lever can never invert them: a 600-HP item can never overtake a 1000-HP
    item. The lever raises health-granting candidates relative to resist-only
    ones - that is its whole job - but it cannot re-order WITHIN the health axis.

    Crediting an ITEM's own caster-HP-scaling proc is a separate follow-on, and
    it SHIPPED as T2 (ENGINE 1.259.0, ``_item_caster_hp_proc``). This pin is
    still correct and still load-bearing: it constrains T1's OWN flag, which is
    what the runs below arm. T2 lifts the limit only under its own separate flag
    (``apply_item_caster_hp_proc``), and
    ``tests/test_item_caster_hp_proc_rm91_t2.py::KnownLimitLiftedTests`` asserts
    both halves of that - this pin holding under T1 alone, and the same
    dominating pair inverting once T2 is armed.
    """

    def test_monotone_in_delta_max_hp_cannot_invert_a_dominating_pair(self) -> None:
        on = _armed("Shen", strength=25.0)
        rows = list(on.ranked)
        pos = {r.item_id: i for i, r in enumerate(rows)}
        checked = 0
        for a in rows:
            for b in rows:
                if a.item_id == b.item_id:
                    continue
                if a.delta_ehp > b.delta_ehp and a.delta_max_hp >= b.delta_max_hp:
                    checked += 1
                    self.assertLess(
                        pos[a.item_id], pos[b.item_id],
                        msg=(
                            f"KNOWN LIMIT violated: {a.item_id} dominates "
                            f"{b.item_id} on both axes but ranks below it"
                        ),
                    )
        self.assertGreater(checked, 0, msg="the limit pin must not be vacuous")


if __name__ == "__main__":
    unittest.main()
