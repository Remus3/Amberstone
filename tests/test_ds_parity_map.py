"""RM-143 P1 - route-vs-ENGINE parity map (the half no existing guard asks).

WHY THIS EXISTS ALONGSIDE THE TWO CLIENT-REACHABILITY GUARDS
------------------------------------------------------------
``agents/daemon_slayer/tests/test_route_seams_reach_the_client.py`` and its
``_per_route`` sibling both ask the SERVER-vs-CLIENT question: given a seam a
route parses, can ``core/daemon_slayer_client.py`` express it. That is a real
question and those guards answer it well.

They do not ask the SERVER-vs-ENGINE question, and they cannot, because both
filter body keys down to a seam-SHAPED name first::

    _SEAM_PREFIXES = ("apply_", "assume_", "gate_", "exclude_")

A TRANSPORT key carries none of those prefixes. ``rune_ids``, ``runes``,
``enemies``, ``targets_in_rotation``, ``caster_current_hp_pct`` and
``target_preset`` are all invisible to both guards BY CONSTRUCTION. That is
exactly the hole RM-118 fell through: ``apply_rune_offense_grants`` was wired
onto a route whose body never carried ``rune_ids``, so the seam was settable,
guard-green and arithmetically INERT - "wiring the flag alone would have made
the seam reachable and dead (the RM-115 failure mode)", as
``server.py:_route_dps`` now says in its own comment.

Transports have so far been defended one incident at a time
(``test_oq17_route_seam_transport.py``, ``test_oq18_route_seam_transport.py``,
``test_rune_lane_route_seams_rm118.py``) - a per-instance test written AFTER
each discovery. This file is the standing, name-filter-free version.

WHAT IS CHECKED
---------------
By introspection over ``server.py`` (AST) plus ``inspect.signature`` of each
engine callee - never a docstring, because the RM-118 ownership prose was
measured wrong in BOTH directions in a single 2026-07-30 run:

  1. every route in ``_POST_ROUTES`` appears in the map;
  2. DROPPED - body keys a handler parses but never forwards to its engine
     callee - equals a ledger;
  3. UNREACHABLE - engine parameters no route forwards - equals a ledger;
  4. every flag in ``FLAG_TRANSPORTS`` is accompanied, on the SAME route, by
     the transport key it needs. No ledger, no allowlist: this one is the bug
     class and it is asserted absolutely.

Ledgers 2 and 3 are debt ledgers in the established house style (equality, not
subset), so they are green on arrival and can only shrink.
"""
from __future__ import annotations

import unittest

from tools.ds_parity_map import FLAG_TRANSPORTS, build_map

# Body keys a handler parses and never forwards. Measured EMPTY on arrival
# (2026-08-01, ENGINE 1.268.0) and asserted absolutely: a key a caller can set
# with no effect is the /rank enemy_ad_share failure shape, and there is
# currently not one instance of it. Two apparent hits during development were
# analyzer false positives (a ``**splat`` dict and an aliased local), fixed in
# ds_parity_map._collect_parses rather than papered over here.
_DROPPED_OK: set[tuple[str, str]] = set()

# Engine parameters no route forwards - a caller cannot reach them over HTTP at
# all. DEBT LEDGER, not an exemption: measured 2026-08-04 at ENGINE 1.274.0,
# 59 pairs across 15 routes (was 65 across 16 at 1.268.0 - the RM-118
# stranded-seam slice drained six pairs: apply_crit_chance_overrides on /dps,
# apply_ability_hsp_amp on /hps, and apply_cast_rate_propensity_prior +
# assume_ms_utility on both /hybrid and /rank-bruiser, which emptied the
# /rank-bruiser row entirely). Equality (not subset) makes it self-cleaning in
# both directions - a NEW unreachable param turns this RED, and wiring one up
# turns it RED until the line is deleted here. Sampled and confirmed against
# source: /v2/matchup parses a single body and never ``sequence_a``/
# ``sequence_b`` (matchup.py:220-221); /rank-onhit never parses ``phase`` or
# ``apply_mode_modifiers`` though rank_items_by_onhit accepts both.
_UNREACHABLE_OK: dict[str, set[str]] = {
    '/ability-dps':        {'assume_ability_amp', 'assume_item_lowhp_magic_crit', 'assume_magic_burst', 'assume_physical_burst', 'assume_shielded_target'},
    '/anti-tank':          {'stats'},
    '/burst':              {'assume_ally_detonation', 'assume_caster_lowhp', 'assume_item_lowhp_magic_crit', 'assume_lifeline_shield', 'assume_passive_reflect', 'caster_hp_pct', 'game_time_s'},
    '/dps':                {'apply_crit_conversion', 'assume_ally_detonation', 'assume_caster_lowhp', 'assume_lifeline_shield', 'assume_passive_reflect', 'assume_takedown', 'only_phase', 'target_current_hp_pct'},
    '/ehp':                {'apply_build_tenacity', 'apply_egg_resist', 'apply_resist_damage_coupling', 'assume_chainlaced_shield', 'assume_eclipse_shield', 'assume_fimbulwinter_shield', 'assume_item_aa_dr', 'assume_item_crit_dr', 'assume_item_enemy_as_slow', 'assume_kaenic_shield', 'assume_seraphs_shield', 'caster_current_hp_pct', 'enemy_armor_pen_pct', 'enemy_lethality', 'enemy_magic_pen_flat', 'enemy_magic_pen_pct', 'enemy_shred_pct', 'external_flat_hp', 'resist_coupling_strength'},
    '/hps':                {'assume_missing_hp_heal_amp', 'caster_missing_hp_pct', 'formulas'},
    '/hybrid':             {'apply_ad_axis_ability_damage', 'apply_melee_aa_gate', 'assume_hsp_amp', 'caster_current_hp_pct'},
    '/rank':               {'mana_value_per_point'},
    '/rank-enchanter':     {'formulas'},
    '/rank-mage':          {'kit_conversion_strength'},
    '/rank-onhit':         {'apply_mode_modifiers', 'phase'},
    '/rank-tank':          {'kit_conversion_strength'},
    '/stats':              {'apply_mode_modifiers'},
    '/v2/fight-report':    {'caster_hp_pct', 'game_time_s', 'recharge_window_s'},
    '/v2/matchup':         {'sequence_a', 'sequence_b'},
}


class ParityMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.m = build_map()

    def test_every_post_route_is_mapped(self) -> None:
        from agents.daemon_slayer import server

        self.assertEqual(set(self.m), set(server._POST_ROUTES))

    def test_every_route_resolves_at_least_one_engine_callee(self) -> None:
        blind = sorted(r for r, e in self.m.items() if not e["engines"])
        self.assertEqual(
            blind, [],
            "these routes resolved no engine callee, so the map is blind to "
            f"them and every other assertion here is vacuous for them: {blind}",
        )

    def test_parsed_body_keys_are_forwarded(self) -> None:
        dropped = {
            (route, key)
            for route, entry in self.m.items()
            for key in entry["dropped"]
        }
        self.assertEqual(
            dropped, set(_DROPPED_OK),
            "a body key parsed but never forwarded is a key the caller can set "
            "with no effect - the /rank enemy_ad_share failure shape",
        )

    def test_engine_params_are_reachable(self) -> None:
        unreachable = {
            route: set(entry["unreachable"])
            for route, entry in self.m.items()
            if entry["unreachable"]
        }
        self.assertEqual(unreachable, _UNREACHABLE_OK)

    def test_every_flag_carries_its_transport(self) -> None:
        """The RM-118 class, asserted with no allowlist.

        A route that parses a seam flag but not the transport that flag reads
        ships a seam which is settable, guard-green and arithmetically inert.
        """
        broken = []
        for route, entry in self.m.items():
            parsed = set(entry["body_keys"])
            for flag, transports in FLAG_TRANSPORTS.items():
                if flag not in parsed:
                    continue
                missing = sorted(t for t in transports if t not in parsed)
                if missing:
                    broken.append(f"{route}: {flag} needs {missing}")
        self.assertEqual(
            broken, [],
            "seam flag(s) wired onto a route that cannot carry their input",
        )


if __name__ == "__main__":
    unittest.main()
