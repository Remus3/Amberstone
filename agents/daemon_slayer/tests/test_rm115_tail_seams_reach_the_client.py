"""RM-115 tail: the 21 remaining (route, seam) pairs, wired end to end.

Sibling of ``test_ehp_family_seams_reach_the_client_rm115.py`` (the 1.253.0
EHP-family block). Same contract: the structural half proves REACHABILITY by
introspection, and this file proves each newly wired seam actually MOVES A
NUMBER when driven through ``core/daemon_slayer_client.py`` against the live
engine on :8860. The routes covered here are ``/dps``, ``/ability-dps``,
``/burst``, ``/rank``, ``/rank-mage`` and ``/rank-assassin``.

WHY EACH CONTROL IS A CONTROL
-----------------------------
Every negative below is registry-proven or gate-proven, not merely observed.
"It did not move" is not evidence; "it cannot move, because the registry has no
key for it" - or "because the guard it rides is not satisfied" - is.

SCALAR ROUTES CANNOT CARRY A RANK ASSERTION
-------------------------------------------
``/dps``, ``/ability-dps`` and ``/burst`` are single-build scalar computes with
no candidate loop. Every acceptance on those three routes is therefore a
SCALAR, and a rank criterion is unsatisfiable by construction - recorded here
so a future author does not spend a session discovering it.

TRANSPORT TRAPS - EACH ONE READS AS A FALSE NEGATIVE IF MISSED
---------------------------------------------------------------
  * ``gate_target_hp_amp`` / ``gate_caster_hp_amp`` are inert without the
    ``runes`` transport, and ``gate_caster_hp_amp`` additionally needs
    ``caster_current_hp_pct`` < 1.0. Both transports were stranded (neither is
    seam-prefixed, so no RM-115 guard could see them) and both were wired in
    the same pass. ``test_burst_gates_are_reachable_and_dead_without_runes``
    is the reason they were wired at all.
  * ``score_completion_runes`` is the same shape: it needs ``runes`` AND the
    flag; either alone is byte-identical.
  * ``assume_takedown``'s Collector arm is disabled by ``target_max_hp == 0.0``
    which IS ``rank_assassin_for``'s own default, so the client's default
    silently kills half the seam.
  * ``assume_squishy_target`` is guarded on ``target_armor <= 0.0``; any
    positive armor turns it off with no error.
  * ``exclude_off_axis_items`` on ``/rank`` is invisible at the client default
    ``top=8`` - the stripped rows all sit deeper than the page. ``top`` is a
    load-bearing transport for this seam.
  * ``apply_ability_amps`` has a staged-block lane keyed ``("Hwei","Q",2)``, so
    it needs ``form_index={"Q": 2}`` to fire on that arm.
  * ``apply_mode_modifiers`` moves on URF and on ARENA, never on SR (no wiki
    sidecar key) and never on ARAM (the engine applies the ARAM axes
    unconditionally; the flag gates the sidecar lane only).

TWO ORIENTATION CONTROLS DID NOT REPRODUCE OVER LIVE HTTP - RECORDED, NOT DROPPED
---------------------------------------------------------------------------------
The pre-wiring in-process pass named two specific movers that this live path
contradicts. The SEAM still moves in both cases; only the named row is wrong,
so the assertions below pin the rows that actually move:
  * ``/rank`` ``apply_mode_modifiers`` on Quinn/ARENA: Arena Lord Dominik's
    ``223036`` holds rank 22 at top=50 AND at top=200. The real movers are
    Phantom Dancer ``223046`` (19 -> 16) and Dusk and Dawn ``222510``
    (36 -> 30).
  * ``/rank-mage`` ``apply_ability_amps`` on Hwei: Rabadon's ``3089`` and
    Shadowflame ``4645`` hold 2 and 5. The real movers are Liandry's Torment
    ``6653`` (10 -> 8, a genuine delta gap of 6.03 -> 10.56 against Luden's
    6.17 -> 10.37, not a ULP tie) and Abyssal Mask ``8020`` (20 -> 16).

LIVE: these hit the running DS server on :8860 through the real client, which
is the whole point - an in-process engine call would prove nothing about gate 3.
Skipped when the engine is down. Host-dependent: it imports ``core.*``, so it
does not stand alone against the DS package by itself.
"""
from __future__ import annotations

import unittest

import core.daemon_slayer_client as dsc

# The client default is 0.5 s, tuned so a coach tick can never stall. A deep
# candidate page (top=200) legitimately exceeds it and would return None, which
# would read as "engine down" rather than "slow" - so every call here is given
# room. This is a test-harness concern only; production keeps the tight bound.
_T = 60.0

# The shared scalar target used for every /dps, /ability-dps and /burst case.
_TARGET = dict(
    target_armor=80.0,
    target_mr=60.0,
    target_max_hp=2200.0,
    target_bonus_hp=1000.0,
)


def _ids(rows) -> list[str]:
    return [r.item_id for r in rows]


def _rank_of(order: list[str], item_id: str):
    return order.index(item_id) + 1 if item_id in order else None


def _dps(champion: str, items, mode: str = "SR", **kw) -> float:
    resp = dsc.dps_for(champion, level=11, item_ids=items, mode=mode,
                       timeout=_T, **_TARGET, **kw)
    return resp["weighted_dps"]


def _ability_dps(champion: str, items, **kw) -> float:
    resp = dsc.ability_dps_for(champion, level=11, item_ids=items, mode="SR",
                               timeout=_T, **_TARGET, **kw)
    return resp["total_ability_dps"]


def _burst(champion: str, items, **kw) -> float:
    resp = dsc.burst_for(champion, level=11, item_ids=items, mode="SR",
                         timeout=_T, **_TARGET, **kw)
    return resp["total_burst_damage"]


class Rm115TailSeamsReachTheClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # RM-119 B2 (2026-08-06): routed through the shared gate. See the
        # sibling note in test_ehp_family_seams_reach_the_client_rm115.py -
        # both modules are host-dependent already, so reaching for a tests/
        # helper costs them nothing.
        from tests.test_ds_live_route_gate import require_live_engine
        require_live_engine("the RM-115 tail seam reachability class",
                            up=dsc.is_engine_up(timeout=2.0))

    # ----------------------------------------------------------------- /dps
    def test_dps_mode_modifiers_moves_on_urf_and_is_inert_on_aram_and_sr(self) -> None:
        urf = _dps("Aatrox", ["3085"], "URF")
        self.assertGreater(_dps("Aatrox", ["3085"], "URF",
                                apply_mode_modifiers=True), urf)
        # CONTROL 1: SR has no wiki sidecar entry at all.
        sr = _dps("Aatrox", ["3085"], "SR")
        self.assertEqual(sr, _dps("Aatrox", ["3085"], "SR",
                                  apply_mode_modifiers=True))
        # CONTROL 2 - the counter-intuitive one, recorded so it is not
        # re-derived: ARAM is INERT. dps.py applies the ARAM balance axes
        # unconditionally; the flag gates only the elif sidecar lane, which
        # excludes ARAM to avoid double counting. An ARAM acceptance case here
        # would look like a bug.
        aram = _dps("Aatrox", ["3085"], "ARAM")
        self.assertEqual(aram, _dps("Aatrox", ["3085"], "ARAM",
                                    apply_mode_modifiers=True))

    def test_dps_ability_amps_moves_and_a_placeholder_entry_is_inert(self) -> None:
        base = _dps("Fiora", ["3085"])
        self.assertGreater(_dps("Fiora", ["3085"], apply_ability_amps=True), base)
        # CONTROL: Caitlyn IS present in _ability_amp_overrides but her entry is
        # a 0.0 placeholder. A registry-present, value-zero row is a stronger
        # control than an absent champion - it proves the VALUE is read, not
        # just the key lookup.
        cait = _dps("Caitlyn", ["3085"])
        self.assertEqual(cait, _dps("Caitlyn", ["3085"], apply_ability_amps=True))

    def test_dps_passive_damage_moves(self) -> None:
        base = _dps("Orianna", ["3085"])
        self.assertGreater(_dps("Orianna", ["3085"], apply_passive_damage=True),
                           base)

    def test_dps_passive_as_stacks_moves(self) -> None:
        base = _dps("Irelia", ["3085"])
        self.assertGreater(
            _dps("Irelia", ["3085"], assume_passive_as_stacks=True), base)

    def test_dps_target_vuln_moves(self) -> None:
        # Evenshroud 3001 is the vulnerability source; the seam credits the
        # amp the item applies to the target.
        base = _dps("Talon", ["3001"])
        self.assertGreater(_dps("Talon", ["3001"], apply_target_vuln=True), base)

    def test_dps_melee_aa_gate_is_negative_on_melee_and_inert_on_ranged(self) -> None:
        """The one seam in this file whose honest direction is DOWN.

        Runaan's Hurricane 3085 is ``ranged_only``. With the gate OFF the engine
        credits its bolts to a melee caster; ON, it deletes them. A test written
        to expect an increase would have been "fixed" by disabling the gate.
        """
        base = _dps("Fiora", ["3085"])
        self.assertLess(_dps("Fiora", ["3085"], apply_melee_aa_gate=True), base)
        # CONTROL: Caitlyn is ranged, so the gate has nothing to withdraw.
        cait = _dps("Caitlyn", ["3085"])
        self.assertEqual(cait, _dps("Caitlyn", ["3085"], apply_melee_aa_gate=True))

    def test_dps_block_omitted_is_byte_identical(self) -> None:
        """The contract that lets six seams ship on one route: absent == off."""
        base = _dps("Fiora", ["3085"])
        allfalse = _dps(
            "Fiora", ["3085"],
            apply_ability_amps=False,
            apply_melee_aa_gate=False,
            apply_mode_modifiers=False,
            apply_passive_damage=False,
            apply_target_vuln=False,
            assume_passive_as_stacks=False,
        )
        self.assertEqual(base, allfalse, "an all-False call must be identical")

    # --------------------------------------------------------- /ability-dps
    def test_ability_dps_amps_move_on_both_arms_and_ahri_is_inert(self) -> None:
        morde = _ability_dps("Mordekaiser", ["6655"])
        self.assertGreater(
            _ability_dps("Mordekaiser", ["6655"], apply_ability_amps=True), morde)
        # The staged-block arm is keyed ("Hwei","Q",2) - without form_index it
        # never fires, so this is a transport assertion as much as a seam one.
        hwei_kw = dict(form_index={"Q": 2})
        hwei = _ability_dps("Hwei", ["6655"], **hwei_kw)
        self.assertGreater(
            _ability_dps("Hwei", ["6655"], **hwei_kw, apply_ability_amps=True),
            hwei)
        # CONTROL: Ahri is absent from all three amp registries.
        ahri = _ability_dps("Ahri", ["6655"])
        self.assertEqual(ahri,
                         _ability_dps("Ahri", ["6655"], apply_ability_amps=True))

    # --------------------------------------------------------------- /burst
    def test_burst_assume_takedown_moves_both_registry_arms(self) -> None:
        hubris = _burst("Talon", ["6697"])
        self.assertGreater(_burst("Talon", ["6697"], assume_takedown=True),
                           hubris)
        collector = _burst("Talon", ["6676"])
        self.assertGreater(_burst("Talon", ["6676"], assume_takedown=True),
                           collector)

    def test_burst_assume_ability_amp_moves(self) -> None:
        base = _burst("Talon", ["3161"])
        self.assertGreater(_burst("Talon", ["3161"], assume_ability_amp=True),
                           base)

    def test_burst_assume_magic_burst_moves(self) -> None:
        # The lever /rank-assassin correctly refuses (rank_items_by_burst has no
        # such parameter); /burst is the route that does parse it.
        base = _burst("Lux", ["6655"])
        self.assertGreater(_burst("Lux", ["6655"], assume_magic_burst=True), base)

    def test_burst_assume_physical_burst_moves(self) -> None:
        base = _burst("Talon", ["226630"])
        self.assertGreater(
            _burst("Talon", ["226630"], assume_physical_burst=True), base)

    def test_burst_assume_shielded_target_moves(self) -> None:
        # Serpent's Fang 6695 is the shield-cutting item; the seam supplies the
        # shield it cuts.
        base = _burst("Talon", ["6695"])
        self.assertGreater(
            _burst("Talon", ["6695"], assume_shielded_target=True), base)

    def test_burst_gate_target_hp_amp_withdraws_the_amp_at_full_target_hp(self) -> None:
        """DOWN is the honest direction here, and that is not a bug.

        The gate is an HONESTY gate, not an enabler: OFF applies Coup de Grace's
        amp unconditionally, ON applies it only when the gate is met. At
        ``target_current_hp_pct=1.0`` the gate is NOT met, so turning it on
        correctly REMOVES the amp. An "increase" assertion would be wrong.
        """
        kw = dict(runes=[8014], target_current_hp_pct=1.0)
        ungated = _burst("Talon", ["3161"], **kw)
        gated = _burst("Talon", ["3161"], **kw, gate_target_hp_amp=True)
        self.assertLess(gated, ungated)
        # And the withdrawn value lands exactly on the no-rune baseline, which
        # proves the amp - not some unrelated term - is what moved.
        self.assertEqual(gated, _burst("Talon", ["3161"]))

    def test_burst_gate_caster_hp_amp_moves_at_low_caster_hp(self) -> None:
        # Last Stand 8299 ramps 1.05 -> 1.11 over caster HP 0.60 -> 0.30, so the
        # caster_current_hp_pct transport is load-bearing: at the default 1.0
        # the ramp contributes nothing.
        kw = dict(runes=[8299], caster_current_hp_pct=0.30)
        ungated = _burst("Talon", ["3161"], **kw)
        self.assertGreater(_burst("Talon", ["3161"], **kw, gate_caster_hp_amp=True),
                           ungated)

    def test_burst_gates_are_reachable_and_dead_without_runes(self) -> None:
        """THE reachable-and-dead guard - the reason the transports were wired.

        ``runes`` and ``caster_current_hp_pct`` are not seam-prefixed, so no
        RM-115 reachability guard can see them. Without them BOTH gate flags are
        expressible from the client and completely inert - a seam that reads
        GREEN on every structural check while doing nothing at all. That is the
        exact illusion RM-115 exists to kill, so it is pinned here: with runes
        omitted, either gate ON must be byte-identical to baseline.
        """
        base = _burst("Talon", ["3161"])
        self.assertEqual(base, _burst("Talon", ["3161"], gate_target_hp_amp=True),
                         "gate_target_hp_amp fired with no runes transport")
        self.assertEqual(base, _burst("Talon", ["3161"], gate_caster_hp_amp=True),
                         "gate_caster_hp_amp fired with no runes transport")
        # Same shape for the third rune-dependent seam: BOTH halves are needed.
        self.assertEqual(base, _burst("Talon", ["3161"], runes=[8401]),
                         "Shield Bash must not score without the flag")
        self.assertEqual(base, _burst("Talon", ["3161"],
                                      score_completion_runes=True),
                         "the flag must not score without the runes transport")
        self.assertGreater(
            _burst("Talon", ["3161"], runes=[8401], score_completion_runes=True),
            base, "runes + flag together must move the score")

    # ---------------------------------------------------------------- /rank
    def test_rank_mode_modifiers_reorders_on_arena_and_is_uniform_on_urf(self) -> None:
        kw = dict(level=13, item_ids=["3031", "3006"], top=50, timeout=_T)
        off = _ids(dsc.rank_for("Quinn", mode="ARENA", **kw))
        on = _ids(dsc.rank_for("Quinn", mode="ARENA", **kw,
                               apply_mode_modifiers=True))
        self.assertNotEqual(off, on, "the Arena sidecar lane must reorder")
        # Named movers, measured live. NOT Arena Lord Dominik's 223036 - it
        # holds rank 22 at top=50 and at top=200 (see the module docstring).
        self.assertLess(_rank_of(on, "223046"), _rank_of(off, "223046"))
        self.assertLess(_rank_of(on, "222510"), _rank_of(off, "222510"))
        # CONTROL: Aatrox has no "ar" key in wiki_stats.json, so the sidecar
        # lookup returns nothing and the flag cannot do anything on ARENA.
        self.assertEqual(
            _ids(dsc.rank_for("Aatrox", mode="ARENA", **kw)),
            _ids(dsc.rank_for("Aatrox", mode="ARENA", **kw,
                              apply_mode_modifiers=True)),
        )

    def test_rank_mode_modifiers_on_urf_moves_the_scalar_but_cannot_reorder(self) -> None:
        """A rank criterion on the URF lane is unsatisfiable by construction.

        URF's sidecar entry is a UNIFORM damage multiplier. Every candidate's
        delta scales by the same factor, and a sort key is invariant under a
        uniform positive scale - so the ORDER cannot move however large the
        multiplier is. The acceptance on this lane is therefore the delta, and a
        "URF reorders" expectation would burn a session.
        """
        kw = dict(level=13, item_ids=["3031", "3006"], top=50, timeout=_T)
        off = dsc.rank_for("Jhin", mode="URF", **kw)
        on = dsc.rank_for("Jhin", mode="URF", **kw, apply_mode_modifiers=True)
        self.assertEqual(_ids(off), _ids(on), "a uniform scale cannot reorder")
        self.assertGreater(on[0].delta_dps, off[0].delta_dps,
                           "the scalar must still move")

    def test_rank_exclude_off_axis_strips_ap_rows_for_a_pure_ad_carry(self) -> None:
        """``top`` is a load-bearing transport for this seam.

        At the client default ``top=8`` the call is byte-identical: every row
        this seam strips sits deeper than the first page (Nashor's is #42,
        Void Staff #78, Rabadon's #84). A verdict measured at the default is a
        false negative, which is asserted here rather than described.
        """
        shallow = dict(level=13, item_ids=["3031", "3006"], mode="SR", top=8,
                       timeout=_T)
        self.assertEqual(
            _ids(dsc.rank_for("Jhin", **shallow)),
            _ids(dsc.rank_for("Jhin", **shallow, exclude_off_axis_items=True)),
            "at top=8 the seam is invisible - that is the trap, not a pass",
        )
        deep = dict(shallow, top=200)
        off = _ids(dsc.rank_for("Jhin", **deep))
        on = _ids(dsc.rank_for("Jhin", **deep, exclude_off_axis_items=True))
        self.assertLess(len(on), len(off), "rows must be STRIPPED, not resorted")
        self.assertEqual([], [i for i in on if i not in off],
                         "the seam may only remove rows, never add them")
        for ap_id in ("3115", "3089", "3135"):  # Nashor's, Rabadon's, Void Staff
            self.assertIn(ap_id, off)
            self.assertNotIn(ap_id, on)
        # CONTROL: Kai'Sa's damage_distribution margin is 0.153, below
        # _AXIS_MARGIN_MIN 0.20, so her axis resolves to None and the seam has
        # nothing to exclude. A hybrid champion is the right control here - an
        # AP champion would merely strip a different set.
        self.assertEqual(
            _ids(dsc.rank_for("Kai'Sa", **deep)),
            _ids(dsc.rank_for("Kai'Sa", **deep, exclude_off_axis_items=True)),
        )

    # ----------------------------------------------------------- /rank-mage
    def test_rank_mage_ability_amps_reorders_for_hwei_and_ahri_is_inert(self) -> None:
        kw = dict(level=18, item_ids=["3020", "3135"], mode="SR",
                  form_index={"Q": 2}, top=30, timeout=_T)
        off = _ids(dsc.rank_mage_for("Hwei", **kw))
        on = _ids(dsc.rank_mage_for("Hwei", **kw, apply_ability_amps=True))
        self.assertNotEqual(off, on)
        # Measured movers. NOT Rabadon's 3089 / Shadowflame 4645, which hold
        # ranks 2 and 5 either way (see the module docstring). Liandry's gains
        # on Luden's by a real margin (6.03 -> 10.56 vs 6.17 -> 10.37), so this
        # is a genuine crossing and not a ULP tie between equal deltas.
        self.assertLess(_rank_of(on, "6653"), _rank_of(off, "6653"))
        self.assertLess(_rank_of(on, "8020"), _rank_of(off, "8020"))
        # CONTROL: Ahri is absent from all three amp registries. She also needs
        # no form_index, so this pins the registry, not the transport.
        plain = dict(level=18, item_ids=["3020", "3135"], mode="SR", top=30,
                     timeout=_T)
        self.assertEqual(
            _ids(dsc.rank_mage_for("Ahri", **plain)),
            _ids(dsc.rank_mage_for("Ahri", **plain, apply_ability_amps=True)),
        )

    # ------------------------------------------------------- /rank-assassin
    def test_rank_assassin_takedown_collector_arm_needs_target_max_hp(self) -> None:
        """The client's OWN default silently kills half this seam.

        ``rank_assassin_for`` defaults ``target_max_hp=0.0``, and the Collector
        arm of ``assume_takedown`` is disabled at exactly that value. Both
        halves are asserted: with HP supplied The Collector climbs; with the
        default it does not, while Hubris climbs either way. A single-arm test
        would have shipped a seam that is half dead in production.
        """
        kw = dict(level=13, item_ids=["3142", "3006"], mode="SR", top=20,
                  timeout=_T)
        off = _ids(dsc.rank_assassin_for("Zed", **kw, target_max_hp=2400.0))
        on = _ids(dsc.rank_assassin_for("Zed", **kw, target_max_hp=2400.0,
                                        assume_takedown=True))
        self.assertLess(_rank_of(on, "6676"), _rank_of(off, "6676"),
                        "The Collector must climb when target_max_hp is set")
        self.assertIsNotNone(_rank_of(on, "6697"), "Hubris must enter the page")
        # TRANSPORT PROOF: same call at the function's own default HP.
        off0 = _ids(dsc.rank_assassin_for("Zed", **kw, target_max_hp=0.0))
        on0 = _ids(dsc.rank_assassin_for("Zed", **kw, target_max_hp=0.0,
                                         assume_takedown=True))
        self.assertGreaterEqual(
            _rank_of(on0, "6676"), _rank_of(off0, "6676"),
            "the Collector arm must be DEAD at target_max_hp=0.0",
        )
        self.assertLess(_rank_of(on0, "6697"), _rank_of(off0, "6697"),
                        "Hubris rides a different arm and must still climb")

    def test_rank_assassin_squishy_target_is_gated_on_zero_target_armor(self) -> None:
        kw = dict(level=13, item_ids=["3142", "3006"], mode="SR", top=20,
                  timeout=_T)
        off = _ids(dsc.rank_assassin_for("Zed", **kw, target_armor=0.0))
        on = _ids(dsc.rank_assassin_for("Zed", **kw, target_armor=0.0,
                                        assume_squishy_target=True))
        self.assertNotEqual(off, on)
        self.assertIsNone(_rank_of(off, "3036"))
        self.assertIsNotNone(_rank_of(on, "3036"),
                             "Lord Dominik's must enter the page")
        # TRANSPORT PROOF: the substitution is guarded on target_armor <= 0.0,
        # so a coach that supplies a MEASURED enemy armor turns the seam off
        # with no error and no log line.
        armored = dict(kw, target_armor=60.0)
        self.assertEqual(
            _ids(dsc.rank_assassin_for("Zed", **armored)),
            _ids(dsc.rank_assassin_for("Zed", **armored,
                                       assume_squishy_target=True)),
            "positive target_armor must make the seam byte-identical",
        )

    def test_rank_assassin_ability_amp_needs_an_ability_in_the_combo(self) -> None:
        kw = dict(level=13, item_ids=["3142", "3006"], mode="SR", top=20,
                  timeout=_T)
        off = _ids(dsc.rank_assassin_for("Zed", **kw))
        on = _ids(dsc.rank_assassin_for("Zed", **kw, assume_ability_amp=True))
        self.assertIsNone(_rank_of(off, "3161"))
        self.assertIsNotNone(_rank_of(on, "3161"),
                             "Spear of Shojin must enter the top page")
        self.assertNotEqual(off, on)
        # TRANSPORT PROOF: an all-AA combo has no ability to amplify, so the
        # seam is inert - the combo_sequence, not just the flag, decides.
        aa = dict(kw, combo_sequence=["AA", "AA", "AA"])
        self.assertEqual(
            _ids(dsc.rank_assassin_for("Zed", **aa)),
            _ids(dsc.rank_assassin_for("Zed", **aa, assume_ability_amp=True)),
        )

    def test_rank_assassin_exclude_off_axis_keeps_the_hybrid_item(self) -> None:
        kw = dict(level=13, item_ids=["3152", "3020"], mode="SR", top=200,
                  timeout=_T)
        off = _ids(dsc.rank_assassin_for("Akali", **kw))
        on = _ids(dsc.rank_assassin_for("Akali", **kw,
                                        exclude_off_axis_items=True))
        self.assertLess(len(on), len(off))
        for ad_id in ("3153", "3508", "3078"):  # BotRK, Essence Reaver, Trinity
            self.assertIn(ad_id, off)
            self.assertNotIn(ad_id, on)
        # The load-bearing half: a HYBRID row must SURVIVE the strip. Hextech
        # Gunblade 3146 is 80 AP / 40 AD, so an exclusion implemented as "drop
        # anything carrying AD" would delete it - this is the assertion that
        # distinguishes an axis filter from a stat blacklist.
        self.assertIn("3146", on)
        self.assertLess(_rank_of(on, "3146"), _rank_of(off, "3146"))

    def test_rank_assassin_target_preset_is_the_squishy_superset(self) -> None:
        """DSP8: the preset agrees with the binary alias on ARMOR, and adds MR.

        With a caller-supplied target MR the preset's MR substitution is
        suppressed (the engine only fills a resist that is <= 0), and the
        squishy preset reuses the DSV3 armor constants - so the two paths must
        agree exactly. At target_mr=0.0 they legitimately DIVERGE, because the
        preset then also substitutes MR and the alias never does. That
        divergence is the superset, not a defect, and it is why a naive
        "preset == alias" assertion at the client defaults would fail.
        """
        kw = dict(level=13, item_ids=["3142", "3006"], mode="SR", top=20,
                  timeout=_T, target_armor=0.0, target_mr=60.0)
        alias = _ids(dsc.rank_assassin_for("Zed", **kw,
                                           assume_squishy_target=True))
        preset = _ids(dsc.rank_assassin_for("Zed", **kw, target_preset="squishy"))
        self.assertEqual(alias, preset,
                         "squishy preset must reuse the DSV3 armor curve")
        tank = _ids(dsc.rank_assassin_for("Zed", **kw, target_preset="tank"))
        self.assertNotEqual(preset, tank,
                            "the presets must not collapse to one profile")
        # The MR half of the superset, pinned: at zero caller MR the preset
        # substitutes MR too and therefore parts company with the alias.
        nomr = dict(kw, target_mr=0.0)
        self.assertNotEqual(
            _ids(dsc.rank_assassin_for("Zed", **nomr,
                                       assume_squishy_target=True)),
            _ids(dsc.rank_assassin_for("Zed", **nomr, target_preset="squishy")),
            "the preset substitutes MR that the binary alias omits",
        )


if __name__ == "__main__":
    unittest.main()
