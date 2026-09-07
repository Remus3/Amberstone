"""RM-115: the EHP-family seam block, wired end to end through the client.

Twenty seams parsed by ``/ehp``, ``/hybrid``, ``/rank-tank`` and
``/rank-bruiser`` were route-complete and engine-complete but unreachable from
``core/daemon_slayer_client.py`` - 76 of the 101 per-(route, seam) stranded
pairs measured at ENGINE 1.252.0. This file is the behavioural half of that
wiring: the structural half is
``test_route_seams_reach_the_client_per_route.py``, which proves REACHABILITY
for all 76 pairs by introspection. Here each seam is proven to actually DO
something, once, on its most diagnostic route, against a NAMED control.

WHY EACH CONTROL IS A CONTROL
-----------------------------
Every control below is registry-proven, not observed. "It did not move" is not
evidence; "it cannot move, because the registry has no key for it" is. Where a
champion control would be invalid the test says so - notably ``apply_item_mana_health``,
where a manaless champion is NOT a valid control because the item's own mana
makes ``bonus_mana`` positive (measured: Garen 5099.337 -> 5242.948).

THREE SEAMS PROVABLY CANNOT REORDER, AND THAT IS RECORDED AS A FINDING
----------------------------------------------------------------------
``apply_survival_window``, ``apply_passive_revive`` and (without
``apply_build_tenacity``) ``apply_champion_tenacity`` fold into a UNIFORM
multiplier on the EHP numerator. A ratio-based sort key is invariant under a
uniform scale, so no rank can move by construction - the handful of "moved"
rows seen while probing were 1e-12 ULP ties between already-equal deltas.
Their acceptance is therefore a SCALAR on /ehp, never a rank position. Writing
a rank assertion for them would be unsatisfiable, and a future author reading
only the seam list would waste a session discovering that.

COMPANION GATES - EACH ONE READS AS A FALSE NEGATIVE IF MISSED
--------------------------------------------------------------
  * ``apply_rune_*``            need ``rune_ids`` carrying the exact runes the
                                registry keys on; the client had NO rune_ids
                                transport before this wiring.
  * ``apply_rune_hsp_amp``      additionally needs a SHIELD source in the build
                                (it amplifies shields; inert at shield_any 0).
  * ``assume_item_health_stacks`` needs level >= 7 (assumed procs are 0 below).
  * ``apply_item_spell_shield`` / ``apply_spell_shield`` need ``enemies``, and
                                an UNSATURATED comp - a 5-champion heavy-CC
                                comp pins cc_pressure_fraction at 1.0 and the
                                seam is swallowed by the clamp.
  * ``apply_champion_tenacity`` only reorders with ``apply_build_tenacity`` ON,
                                because tenacity stacks multiplicatively and is
                                build-independent until items also contribute.
  * ``apply_mode_modifiers``    moves on URF, NOT on ARAM (the ARAM axes apply
                                unconditionally; the flag gates the wiki
                                sidecar lane, which has no ARAM entry).
  * ``apply_ad_axis_ability_damage`` needs a non-zero ``target_max_hp``; the
                                route parses target_max_hp / target_bonus_hp,
                                NOT target_hp.

LIVE: these hit the running DS server on :8860 through the real client, which
is the whole point - an in-process engine call would prove nothing about gate 3.
Skipped when the engine is down. Host-dependent: it imports ``core.*``, so it
does not stand alone against the DS package by itself.
"""
from __future__ import annotations

import unittest

import core.daemon_slayer_client as dsc

_SCALAR_KEYS = (
    "blended_ehp",
    "ehp_without_sustain",
    "effective_ehp_with_sustain",
    "cc_blended_ehp",
)


def _ids(rows) -> list[str]:
    return [r.item_id for r in rows]


def _rank_of(order: list[str], item_id: str):
    return order.index(item_id) + 1 if item_id in order else None


def _scalars(resp: dict) -> tuple:
    return tuple(resp[k] for k in _SCALAR_KEYS)


class EhpFamilySeamsReachTheClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # RM-119 B2 (2026-08-06): routed through the shared gate, so
        # RC_REQUIRE_DS_ENGINE=1 turns a down engine into a failure here
        # instead of a green skip. This module is host-dependent already - it
        # imports core.daemon_slayer_client at module level - so reaching for
        # a tests/ helper costs it nothing. The eleven stdlib-only DS-tree
        # gates cannot do this and stay class-wide.
        from tests.test_ds_live_route_gate import require_live_engine
        require_live_engine("the RM-115 EHP family seam reachability class",
                            up=dsc.is_engine_up(timeout=2.0))

    # ------------------------------------------------------------ item lane
    def test_item_resist_grants_reorders_and_control_holds(self) -> None:
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        off = _ids(dsc.rank_tank_for("Sion", **kw))
        on = _ids(dsc.rank_tank_for("Sion", **kw, apply_item_resist_grants=True))
        # Jak'Sho 6665 and Terminus 3302 are registry keys; Terminus scores 0.0
        # with the seam off, which is why it sits ~#115 and needs top=300.
        self.assertLess(_rank_of(on, "6665"), _rank_of(off, "6665"))
        self.assertLess(_rank_of(on, "3302"), _rank_of(off, "3302"))
        # CONTROL: none of these five ids is in _ITEM_RESIST_GRANTS.
        ctl = dict(kw, only_item_ids=["3143", "3110", "3742", "3083", "3084"])
        self.assertEqual(
            _ids(dsc.rank_tank_for("Sion", **ctl)),
            _ids(dsc.rank_tank_for("Sion", **ctl, apply_item_resist_grants=True)),
        )

    def test_item_bonus_hp_amp_takes_the_head_and_arena_mirror_is_excluded(self) -> None:
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        off = _ids(dsc.rank_tank_for("Sion", **kw))
        on = _ids(dsc.rank_tank_for("Sion", **kw, apply_item_bonus_hp_amp=True))
        self.assertEqual(_rank_of(off, "3083"), 2)
        self.assertEqual(_rank_of(on, "3083"), 1, "Warmog's must take the head")
        # CONTROL: the Arena mirror 443083 was deliberately REMOVED from the
        # registry (RM-102) because it does not carry Warmog's Vitality. It is
        # in the Arena pool, so this pins the removal rather than an absence.
        base = dict(champion="Sion", level=13, item_ids=["3068", "443083"], mode="ARENA")
        self.assertEqual(
            _scalars(dsc.ehp_for(**base)),
            _scalars(dsc.ehp_for(**base, apply_item_bonus_hp_amp=True)),
        )

    def test_item_mana_health_moves_and_a_champion_control_would_be_invalid(self) -> None:
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        off = _ids(dsc.rank_tank_for("Sion", **kw))
        on = _ids(dsc.rank_tank_for("Sion", **kw, apply_item_mana_health=True))
        self.assertLess(_rank_of(on, "3119"), _rank_of(off, "3119"))
        # CONTROL must be an ITEM-set control. A manaless champion is NOT valid:
        # item_mana_health_hp zeroes only on bonus_mana <= 0, and Winter's
        # Approach supplies its own mana, so even Garen moves.
        ctl = dict(kw, only_item_ids=["3143", "3110", "3742", "3083", "3084"])
        self.assertEqual(
            _ids(dsc.rank_tank_for("Sion", **ctl)),
            _ids(dsc.rank_tank_for("Sion", **ctl, apply_item_mana_health=True)),
        )
        garen = dict(champion="Garen", level=13, item_ids=["3068", "3119"], mode="SR")
        self.assertNotEqual(
            _scalars(dsc.ehp_for(**garen)),
            _scalars(dsc.ehp_for(**garen, apply_item_mana_health=True)),
            "a manaless champion still moves - do not use one as a control here",
        )

    def test_item_health_stacks_moves_and_is_level_gated(self) -> None:
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        off = _ids(dsc.rank_tank_for("Sion", **kw))
        on = _ids(dsc.rank_tank_for("Sion", **kw, assume_item_health_stacks=True))
        self.assertLess(_rank_of(on, "3084"), _rank_of(off, "3084"))
        # CONTROL: the SAME item at level 6, where the assumed-proc table is 0.
        # A level gate is a stronger control than a different item - it proves
        # the mechanism, not just the absence of a key.
        l6 = dict(champion="Sion", level=6, item_ids=["3068", "3084"], mode="SR")
        self.assertEqual(
            _scalars(dsc.ehp_for(**l6)),
            _scalars(dsc.ehp_for(**l6, assume_item_health_stacks=True)),
        )
        l13 = dict(l6, level=13)
        self.assertNotEqual(
            _scalars(dsc.ehp_for(**l13)),
            _scalars(dsc.ehp_for(**l13, assume_item_health_stacks=True)),
        )

    def test_item_spell_shield_needs_enemies_and_an_unsaturated_comp(self) -> None:
        # One moderate-CC enemy: five heavy-CC enemies pin cc_pressure_fraction
        # at 1.0 and the 20 pct cut vanishes into the clamp (0/138 rows move).
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300,
                  enemies=["Leona"], score_by="cc_blended")
        off = _ids(dsc.rank_tank_for("Sion", **kw))
        on = _ids(dsc.rank_tank_for("Sion", **kw, apply_item_spell_shield=True))
        self.assertLess(_rank_of(on, "3814"), _rank_of(off, "3814"))
        self.assertLess(_rank_of(on, "3102"), _rank_of(off, "3102"))
        # CONTROL (gate, not registry): with no enemies the consuming branch is
        # never entered, so the seam is inert even with Banshee's ranked.
        noenemy = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        self.assertEqual(
            _ids(dsc.rank_tank_for("Sion", **noenemy)),
            _ids(dsc.rank_tank_for("Sion", **noenemy, apply_item_spell_shield=True)),
        )

    # ------------------------------------------------------------ rune lane
    def test_rune_seams_ride_the_new_rune_ids_transport(self) -> None:
        base = dict(champion="Ornn", level=13,
                    item_ids=["3068", "3075", "3143"], mode="SR")
        plain = _scalars(dsc.ehp_for(**base))
        for seam, ids in (
            ("apply_rune_resist_grants", ["8439", "8429", "8242"]),
            ("apply_rune_health_grants", ["8437", "8451"]),
            ("apply_rune_flat_mitigation", ["8473"]),
        ):
            with self.subTest(seam=seam):
                got = _scalars(
                    dsc.ehp_for(**base, rune_ids=ids, **{seam: True})
                )
                self.assertNotEqual(plain, got, f"{seam} did not move")
                # CONTROL: the flag ON with runes it cannot key. Stronger than
                # an empty page - it proves id ROUTING, not just the flag.
                other = ["8005", "8009", "9104", "8014"]  # Precision, offensive
                self.assertEqual(
                    plain,
                    _scalars(dsc.ehp_for(**base, rune_ids=other, **{seam: True})),
                    f"{seam} fired on runes outside its registry",
                )

    def test_rune_hsp_amp_is_inert_without_a_shield_source(self) -> None:
        noshield = dict(champion="Ornn", level=13,
                        item_ids=["3068", "3075", "3143"], mode="SR")
        self.assertEqual(
            _scalars(dsc.ehp_for(**noshield)),
            _scalars(dsc.ehp_for(**noshield, rune_ids=["8453"],
                                 apply_rune_hsp_amp=True)),
            "Revitalize amplifies shields; with no shield it must be inert",
        )
        # Sterak's Gage supplies the shield the seam amplifies.
        shielded = dict(noshield, item_ids=["3053", "3075", "3143"])
        self.assertNotEqual(
            _scalars(dsc.ehp_for(**shielded)),
            _scalars(dsc.ehp_for(**shielded, rune_ids=["8453"],
                                 apply_rune_hsp_amp=True)),
        )

    # -------------------------------------------------- champion / passive lane
    def test_passive_resist_reorders_for_a_registry_champion(self) -> None:
        kw = dict(level=11, item_ids=["3068", "3075"], mode="SR", top=300)
        off = _ids(dsc.rank_tank_for("Malphite", **kw))
        on = _ids(dsc.rank_tank_for("Malphite", **kw, apply_passive_resist=True))
        self.assertNotEqual(off, on, "Malphite W is in _PASSIVE_RESIST_OVERRIDES")
        # CONTROL: Ornn is NOT in the 22-champion registry. (Ornn and Sion were
        # both suggested as movers during triage and both are absent - the real
        # movers are Malphite and Rammus.)
        self.assertEqual(
            _ids(dsc.rank_tank_for("Ornn", **kw)),
            _ids(dsc.rank_tank_for("Ornn", **kw, apply_passive_resist=True)),
        )

    def test_passive_mitigation_reorders_only_for_per_type_dr(self) -> None:
        kw = dict(level=11, item_ids=["3068", "3075"], mode="SR", top=300)
        # Kassadin's P is MAGIC-only DR -> asymmetric -> genuinely reorders.
        off = _ids(dsc.rank_tank_for("Kassadin", **kw))
        on = _ids(dsc.rank_tank_for("Kassadin", **kw, apply_passive_mitigation=True))
        self.assertNotEqual(off, on)
        # CONTROL: Ornn is absent from the 5-champion registry.
        self.assertEqual(
            _ids(dsc.rank_tank_for("Ornn", **kw)),
            _ids(dsc.rank_tank_for("Ornn", **kw, apply_passive_mitigation=True)),
        )

    def test_passive_revive_moves_the_scalar_and_cannot_reorder(self) -> None:
        base = dict(champion="Anivia", level=11,
                    item_ids=["3068", "3075"], mode="SR")
        self.assertNotEqual(
            _scalars(dsc.ehp_for(**base)),
            _scalars(dsc.ehp_for(**base, apply_passive_revive=True)),
            "Anivia P is one of the two revive entries",
        )
        # CONTROL: Ornn - the registry holds only Anivia and Zac.
        ctl = dict(base, champion="Ornn")
        self.assertEqual(
            _scalars(dsc.ehp_for(**ctl)),
            _scalars(dsc.ehp_for(**ctl, apply_passive_revive=True)),
        )

    def test_build_tenacity_is_tri_state_and_reorders(self) -> None:
        """The one seam in this block whose client default is None, not False.

        ``_route_rank_tank`` reads it as None-when-absent and the engine turns
        it ON by default under score_by="cc_blended". A plain ``bool = False``
        with an emit-when-True rule could never express the OFF, so the wiring
        would have shipped an off switch that cannot switch anything off.
        """
        kw = dict(level=11, item_ids=["3068", "3075"], mode="SR", top=300,
                  enemies=["Leona", "Ashe"], score_by="cc_blended")
        off = _ids(dsc.rank_tank_for("Ornn", **kw, apply_build_tenacity=False))
        on = _ids(dsc.rank_tank_for("Ornn", **kw, apply_build_tenacity=True))
        self.assertNotEqual(off, on)
        self.assertEqual(_rank_of(on, "3053"), 1, "Sterak's Gage must take the head")
        # Omitting the key must inherit the engine default (ON), NOT the False.
        inherited = _ids(dsc.rank_tank_for("Ornn", **kw))
        self.assertEqual(
            inherited, on,
            "omitting apply_build_tenacity must inherit the engine's default-ON; "
            "if this equals the OFF ordering the tri-state wiring has regressed "
            "to a plain bool",
        )

    def test_champion_tenacity_reorders_only_with_build_tenacity_on(self) -> None:
        kw = dict(level=11, item_ids=["3068", "3075"], mode="SR", top=300,
                  enemies=["Leona", "Ashe"], score_by="cc_blended")
        # Alone it is a uniform scale - scalar moves, order does not.
        off = _ids(dsc.rank_tank_for("Garen", **kw, apply_build_tenacity=False))
        alone = _ids(dsc.rank_tank_for("Garen", **kw, apply_build_tenacity=False,
                                       apply_champion_tenacity=True))
        self.assertEqual(off, alone, "champion tenacity alone is a uniform scale")
        # With build tenacity credited too, tenacity becomes build-dependent.
        both_off = _ids(dsc.rank_tank_for("Garen", **kw, apply_build_tenacity=True))
        both_on = _ids(dsc.rank_tank_for("Garen", **kw, apply_build_tenacity=True,
                                         apply_champion_tenacity=True))
        self.assertNotEqual(
            both_off, both_on,
            "tenacity stacks multiplicatively - a 'no reorder' verdict measured "
            "with build tenacity OFF is a false negative",
        )
        # CONTROL: Ornn is absent from the 3-champion tenacity registry.
        self.assertEqual(
            _ids(dsc.rank_tank_for("Ornn", **kw, apply_build_tenacity=True)),
            _ids(dsc.rank_tank_for("Ornn", **kw, apply_build_tenacity=True,
                                   apply_champion_tenacity=True)),
        )

    def test_survival_window_moves_the_scalar_and_cannot_reorder(self) -> None:
        base = dict(champion="Tryndamere", level=13,
                    item_ids=["3068", "3075", "3143"], mode="SR")
        self.assertNotEqual(
            _scalars(dsc.ehp_for(**base)),
            _scalars(dsc.ehp_for(**base, apply_survival_window=True)),
        )
        # CONTROL: Garen has no key in the 10-entry champion/ability registry.
        ctl = dict(base, champion="Garen")
        self.assertEqual(
            _scalars(dsc.ehp_for(**ctl)),
            _scalars(dsc.ehp_for(**ctl, apply_survival_window=True)),
        )

    # ------------------------------------------------------- assume / mode lane
    def test_item_general_dr_reorders(self) -> None:
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        off = _ids(dsc.rank_tank_for("Malphite", **kw))
        on = _ids(dsc.rank_tank_for("Malphite", **kw, assume_item_general_dr=True))
        self.assertLess(
            _rank_of(on, "664644"), _rank_of(off, "664644"),
            "Crown of the Shattered Queen is one of the two priced ids",
        )
        # CONTROL: Randuin's Omen is absent from _ITEM_GENERAL_DR.
        ctl = dict(champion="Malphite", level=13,
                   item_ids=["3068", "3075", "3143"], mode="SR")
        self.assertEqual(
            _scalars(dsc.ehp_for(**ctl)),
            _scalars(dsc.ehp_for(**ctl, assume_item_general_dr=True)),
        )

    def test_item_proc_heal_reorders(self) -> None:
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        off = _ids(dsc.rank_tank_for("Malphite", **kw))
        on = _ids(dsc.rank_tank_for("Malphite", **kw, assume_item_proc_heal=True))
        self.assertLess(
            _rank_of(on, "2502"), _rank_of(off, "2502"),
            "Unending Despair is the registry's only SR id",
        )
        ctl = dict(champion="Malphite", level=13,
                   item_ids=["3068", "3075", "3143"], mode="SR")
        self.assertEqual(
            _scalars(dsc.ehp_for(**ctl)),
            _scalars(dsc.ehp_for(**ctl, assume_item_proc_heal=True)),
        )

    def test_champion_spell_shield_needs_enemies(self) -> None:
        base = dict(champion="Morgana", level=13, item_ids=["3068", "3075"],
                    mode="SR", enemies=["Leona", "Amumu", "Sett"])
        self.assertNotEqual(
            _scalars(dsc.ehp_for(**base)),
            _scalars(dsc.ehp_for(**base, apply_spell_shield=True)),
            "Morgana E is one of the four spell-shield champions",
        )
        # CONTROL: Malphite is absent from _CHAMPION_SPELL_SHIELD_OVERRIDES.
        ctl = dict(base, champion="Malphite")
        self.assertEqual(
            _scalars(dsc.ehp_for(**ctl)),
            _scalars(dsc.ehp_for(**ctl, apply_spell_shield=True)),
        )

    def test_mode_modifiers_moves_on_urf_and_is_inert_on_aram_and_sr(self) -> None:
        urf = dict(champion="Aatrox", level=13, item_ids=["3068", "3075"], mode="URF")
        self.assertNotEqual(
            _scalars(dsc.ehp_for(**urf)),
            _scalars(dsc.ehp_for(**urf, apply_mode_modifiers=True)),
        )
        # CONTROL 1: SR has no wiki sidecar entry at all.
        sr = dict(urf, mode="SR")
        self.assertEqual(
            _scalars(dsc.ehp_for(**sr)),
            _scalars(dsc.ehp_for(**sr, apply_mode_modifiers=True)),
        )
        # CONTROL 2 - the counter-intuitive one, recorded so it is not
        # re-derived: ARAM is INERT for this flag. The ARAM balance axes are
        # applied unconditionally by the engine; the flag gates the wiki
        # sidecar lane, which deliberately excludes ARAM to avoid double
        # counting. An ARAM acceptance case here would look like a bug.
        aram = dict(urf, mode="ARAM")
        self.assertEqual(
            _scalars(dsc.ehp_for(**aram)),
            _scalars(dsc.ehp_for(**aram, apply_mode_modifiers=True)),
        )

    def test_ad_axis_ability_damage_is_bruiser_only(self) -> None:
        kw = dict(level=13, item_ids=["3071", "3053"], mode="SR",
                  target_armor=100.0, target_mr=60.0,
                  target_max_hp=2500.0, target_bonus_hp=1200.0, top=300)
        off = _ids(dsc.rank_bruiser_for("Garen", **kw))
        on = _ids(dsc.rank_bruiser_for("Garen", **kw,
                                       apply_ad_axis_ability_damage=True))
        self.assertNotEqual(off, on)
        # CONTROL: Warwick is ON the AD branch (so the gate admits him) but all
        # four of his per-spell rows normalise to MAGIC, which the credited set
        # {PHYSICAL, TRUE} excludes - the sum is exactly 0.0. A stronger control
        # than an AP champion, whose branch is never entered at all.
        self.assertEqual(
            _ids(dsc.rank_bruiser_for("Warwick", **kw)),
            _ids(dsc.rank_bruiser_for("Warwick", **kw,
                                      apply_ad_axis_ability_damage=True)),
        )

    # --------------------------------------------------------- the block default
    def test_the_whole_block_omitted_is_byte_identical(self) -> None:
        """The contract that lets 20 seams ship at once: absent == off.

        Every seam except apply_build_tenacity is emitted only when True, so a
        call that sets none of them must reproduce the pre-wiring request.
        """
        kw = dict(level=13, item_ids=["3068", "3075"], mode="SR", top=300)
        a = _ids(dsc.rank_tank_for("Sion", **kw))
        b = _ids(dsc.rank_tank_for(
            "Sion", **kw,
            apply_item_resist_grants=False,
            apply_item_bonus_hp_amp=False,
            apply_item_mana_health=False,
            apply_item_spell_shield=False,
            apply_spell_shield=False,
            apply_passive_resist=False,
            apply_passive_mitigation=False,
            apply_passive_revive=False,
            apply_champion_tenacity=False,
            apply_survival_window=False,
            apply_mode_modifiers=False,
            apply_rune_resist_grants=False,
            apply_rune_health_grants=False,
            apply_rune_hsp_amp=False,
            apply_rune_flat_mitigation=False,
            assume_item_general_dr=False,
            assume_item_health_stacks=False,
            assume_item_proc_heal=False,
        ))
        self.assertEqual(a, b, "an all-False call must be byte-identical")


if __name__ == "__main__":
    unittest.main()
