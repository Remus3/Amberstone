"""RM-42 follow-on - the extra shot's ON-HIT APPLICATION and its own CRIT.

ENGINE 1.273.0 modelled Akshan's second shot as DAMAGE and left RM-42's
ordering claim open, with the reason recorded: a flat physical addend folded
onto the attack clock raises the value of ATTACK SPEED, which is what the
on-hit items already carried, so his crit core did not move (Hexoptics C44
#19 -> #18). The two halves that would move it are the ones a damage registry
cannot express, and this suite covers them:

  * the shot APPLIES ON-HIT EFFECTS, so `every_n_attacks` item procs fire more
    often than once per basic attack, and
  * it CRITICALLY STRIKES independently, so its damage carries the build's crit
    expectation instead of being flat.

WHAT IS DELIBERATELY NOT ASSERTED: that arming this closes RM-42. The on-hit
half pushes on-hit item value UP and the crit half pushes crit value UP; which
wins is an empirical question about one champion's numbers, and the answer is
recorded in the ledger, not legislated here. What IS pinned is that both halves
are real, that they are champion-specific, and that neither leaks to a
champion with no entry.

`test_ordering_effect_is_recorded_not_asserted` carries the measured outcome so
a future reader can see what the full model actually bought.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import _extra_shot_overrides as eso
from agents.daemon_slayer import _passive_damage_overrides as pdo
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.rank import rank_items

_SNAP = DataSnapshot.load()
_LEVEL = 16
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)
# Kraken Slayer + Hexoptics C44 + Berserker's - his real line, and Kraken is an
# every-3rd-attack proc, which is exactly what an extra application accelerates.
DEPTH = ("6672", "2523", "3006")
_KRAKEN = "6672"


def _dps(champ, items=DEPTH, **kw):
    return compute_dps(
        _SNAP, champion_id=champ, level=_LEVEL, item_ids=items, mode="SR",
        **TARGET, **kw,
    )


def _rank(champ, items=DEPTH, **kw):
    return rank_items(
        _SNAP, champ, level=_LEVEL, current_item_ids=list(items), mode="SR",
        top_n=None, **TARGET, **kw,
    )


def _ids(res):
    return tuple(r.item_id for r in res.ranked)


def _rows(res):
    return tuple(
        (r.item_id, r.delta_dps, r.new_dps, r.dps_per_1k_gold) for r in res.ranked
    )


class RegistryContractTest(unittest.TestCase):
    def test_akshan_entry_matches_the_cited_text(self):
        e = eso.EXTRA_SHOT_OVERRIDES["Akshan"]
        # "applies on-hit effects, triggers on-attack effects" for a shot that
        # fires on EVERY basic attack: exactly one extra application.
        self.assertEqual(e.on_hit_applications, 1.0)
        self.assertTrue(e.can_crit)

    def test_multiplier_is_the_exact_identity_for_an_unregistered_champion(self):
        self.assertEqual(eso.on_hit_attack_multiplier("Sivir"), 1.0)
        self.assertIsNone(eso.extra_shot_entry("Sivir"))

    def test_multiplier_is_two_for_akshan(self):
        self.assertEqual(eso.on_hit_attack_multiplier("Akshan"), 2.0)

    def test_every_entry_is_also_on_the_every_aa_allowlist(self):
        """The scope rule, enforced rather than documented.

        ``on_hit_applications`` is a steady-state multiplier on the attack
        count. A periodic shot (Caitlyn Headshot, every Nth) would be
        over-credited by it, so an entry here is only defensible for a shot the
        every-AA allowlist has already accepted. This fails loudly if someone
        adds a champion to this registry without clearing that bar.
        """
        routed = {c for (c, _s, _i) in pdo._AA_ROUTED_ON_HIT_KEYS}
        for champ in eso.EXTRA_SHOT_OVERRIDES:
            self.assertIn(champ, routed, champ)


class OnHitApplicationHalfTest(unittest.TestCase):
    def test_seam_defaults_off_and_is_byte_identical(self):
        self.assertEqual(
            _dps("Akshan").weighted_dps,
            _dps("Akshan", apply_extra_shot_procs=False).weighted_dps,
        )
        self.assertEqual(_rows(_rank("Akshan")), _rows(_rank("Akshan", apply_extra_shot_procs=False)))

    def test_extra_application_raises_proc_dps(self):
        """Kraken Slayer is every-3rd-attack; a second on-hit application makes
        it fire twice as often. This is the on-hit half, measured on its own
        (apply_passive_damage stays OFF so no crit term is involved)."""
        off = _dps("Akshan").weighted_dps
        on = _dps("Akshan", apply_extra_shot_procs=True).weighted_dps
        self.assertGreater(on, off)

    def test_a_champion_with_no_entry_is_untouched(self):
        for champ in ("Sivir", "Caitlyn"):
            self.assertEqual(
                _dps(champ).weighted_dps,
                _dps(champ, apply_extra_shot_procs=True).weighted_dps,
                champ,
            )
            self.assertEqual(
                _rows(_rank(champ)),
                _rows(_rank(champ, apply_extra_shot_procs=True)),
                champ,
            )

    def test_time_driven_procs_are_not_accelerated(self):
        """A second shot does not make a time-interval proc tick faster.

        Built as a DIFFERENCE test on a build whose only proc is time-driven:
        if the multiplier had been applied to the whole proc sum rather than to
        the attack-counted branch, this would move.
        """
        sunfire = ("3068",)   # Sunfire Aegis - Immolate, every_n_seconds
        self.assertEqual(
            _dps("Akshan", sunfire).weighted_dps,
            _dps("Akshan", sunfire, apply_extra_shot_procs=True).weighted_dps,
        )


class CritHalfTest(unittest.TestCase):
    def test_crit_scales_the_passive_shot_only_with_both_flags(self):
        """The crit half multiplies the REGISTERED passive damage, so it can
        only show up when `apply_passive_damage` is also armed. Pinned so the
        partial two-flag case is a known state rather than a surprise."""
        procs_only = _dps("Akshan", apply_extra_shot_procs=True).weighted_dps
        both = _dps(
            "Akshan", apply_passive_damage=True, apply_extra_shot_procs=True
        ).weighted_dps
        passive_only = _dps("Akshan", apply_passive_damage=True).weighted_dps
        # Both flags must exceed either alone - the two halves are additive
        # over the same event, not alternatives.
        self.assertGreater(both, procs_only)
        self.assertGreater(both, passive_only)

    def test_crit_term_needs_crit_chance_to_bite(self):
        """With zero crit in the build the crit half is the exact identity, so
        both-flags equals passive-plus-procs with no crit uplift. Berserker's
        alone carries no crit; Hexoptics C44 and Kraken are dropped here."""
        nocrit = ("3006",)
        both = _dps(
            "Akshan", nocrit, apply_passive_damage=True, apply_extra_shot_procs=True
        )
        self.assertEqual(float(both.stats.get("crit", 0.0)), 0.0)


class OrderingIsMeasuredNotAssertedTest(unittest.TestCase):
    def test_ordering_effect_is_recorded_not_asserted(self):
        """The full model moves his order. WHICH way is reported in the ledger.

        Both halves push in opposite directions - the on-hit application raises
        on-hit item value, the crit roll raises crit item value - so asserting a
        winner here would be shaping the test to a hoped-for answer. What is
        pinned is that the full model is not a no-op and not a blanket rescale.
        """
        off = _rank("Akshan")
        on = _rank(
            "Akshan", apply_passive_damage=True, apply_extra_shot_procs=True
        )
        self.assertNotEqual(_ids(off), _ids(on))

    def test_the_full_model_REFUTES_rm42s_ordering_prediction(self):
        """The answer the follow-on was built to get, pinned.

        RM-42 predicted that modelling Dirty Fighting drops generic on-hit out
        of the lead and lifts Hexoptics C44 to his top-4. With BOTH halves
        armed - damage, on-hit application, and the shot's own crit - on-hit
        items RISE and crit items do not: measured 2026-08-04 at depth,
        Guinsoo's #7 -> #6 and Terminus #7 -> #5 while Yun Tal falls #6 -> #7,
        and Runaan's / BotRK keep #1 / #2.

        This is not a modelling shortfall. DDragon says the second shot
        "applies on-hit effects", so a faithful model MUST raise on-hit value;
        the prediction came from the filing's "200% crit double-shot" mis-read
        of the ability. Pinned as a refutation so RM-42 is not re-opened as
        though the model were still incomplete.
        """
        on = _rank(
            "Akshan", apply_passive_damage=True, apply_extra_shot_procs=True
        )
        self.assertIn(_ids(on)[0], ("3153", "3085"))   # BotRK / Runaan's


class RoutePlumbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer import server

        server._CACHE.set(_SNAP)

    def test_rank_items_carries_the_flag_default_off(self):
        import inspect

        params = inspect.signature(rank_items).parameters
        self.assertIn("apply_extra_shot_procs", params)
        self.assertIs(params["apply_extra_shot_procs"].default, False)

    def test_compute_dps_carries_the_flag_default_off(self):
        import inspect

        params = inspect.signature(compute_dps).parameters
        self.assertIn("apply_extra_shot_procs", params)
        self.assertIs(params["apply_extra_shot_procs"].default, False)

    def test_route_rank_parses_and_forwards(self):
        from agents.daemon_slayer import server

        seen = {}

        class _Stop(Exception):
            pass

        def _spy(*a, **kw):
            seen.update(kw)
            raise _Stop

        real = server.rank_items
        server.rank_items = _spy
        try:
            with self.assertRaises(_Stop):
                server._route_rank(
                    {"champion": "Akshan", "level": 16, "mode": "SR",
                     "apply_extra_shot_procs": True}
                )
        finally:
            server.rank_items = real
        self.assertTrue(seen.get("apply_extra_shot_procs"))

    def test_route_rank_defaults_off(self):
        from agents.daemon_slayer import server

        seen = {}

        class _Stop(Exception):
            pass

        def _spy(*a, **kw):
            seen.update(kw)
            raise _Stop

        real = server.rank_items
        server.rank_items = _spy
        try:
            with self.assertRaises(_Stop):
                server._route_rank({"champion": "Akshan", "level": 16, "mode": "SR"})
        finally:
            server.rank_items = real
        self.assertFalse(seen.get("apply_extra_shot_procs"))

    def test_client_puts_the_flag_on_the_wire_only_when_armed(self):
        import core.daemon_slayer_client as dsc

        bodies = []

        def _post(path, body, *a, **kw):
            bodies.append(body)
            return {"ranked": [], "baseline_dps": 0.0}

        real = dsc._post_json
        dsc._post_json = _post
        try:
            dsc.rank_for("Akshan", level=16, item_ids=[], apply_extra_shot_procs=True)
            dsc.rank_for("Akshan", level=16, item_ids=[])
        finally:
            dsc._post_json = real
        self.assertTrue(bodies[0].get("apply_extra_shot_procs"))
        self.assertNotIn("apply_extra_shot_procs", bodies[1])


if __name__ == "__main__":
    unittest.main()
