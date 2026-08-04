"""RM-42 Akshan - Dirty Fighting's second shot, and the ranker seam that
makes any kit passive visible to the CARRY item scorer.

TWO defects, one slice.

**(1) The registry was invisible to the ranker.** `_passive_damage_overrides`
holds 33 entries and `apply_passive_damage` reaches `compute_dps` (`/dps`) and
`rank_items_by_onhit` (`/rank-onhit`, default True) - but NOT
`rank.rank_items`, which is the CARRY scorer and the route every marksman build
table and coach tick goes through. Measured 2026-08-04 at ENGINE 1.272.0:
`grep apply_passive_damage rank.py` returned ZERO. So Caitlyn's Headshot,
Jhin's Whisper, Kai'Sa's Plasma and thirty more were priced nowhere the item
ranking could see them. A docstring at `server.py:1609` asserted the opposite -
that `/rank` parses the flag - which is the "ownership prose lies in both
directions" trap; it is corrected in this slice.

**(2) Akshan's passive was absent from the registry.** Ground truth,
`data/daemon_slayer/16.15.1/champion_abilities.json` -> Akshan -> P
"Dirty Fighting", verbatim:

    "Innate: Whenever Akshan uses a basic attack, he fires an additional shot
    after a delay that deals 50% AD physical damage, increased to 100% AD
    against minions."
    "The additional shot applies on-hit effects, triggers on-attack effects,
    and can critically strike[ for (22.5% + 12%) bonus damage. ][ 100% base
    damage + 30% bonus critical damage. ]"

**THE FILING WAS WRONG ABOUT THIS ABILITY AND THE PRESCRIPTION FOLLOWED IT.**
`project_ds_sweep_akshan_crit_passive` (and the ROADMAP row) describe a
"reworked Dirty Fighting passive = 200% crit double-shot" and predict that
modelling it will "drop generic not-built on-hit (BotRK/Runaan's/Guinsoo's) out
of the lead". The shipped data says the second shot is a flat 50% AD physical
hit that **APPLIES ON-HIT EFFECTS**. Crediting the passive faithfully therefore
gives on-hit items MORE per-auto value on Akshan, not less. This suite asserts
what the model DOES, and deliberately does NOT assert the filing's predicted
direction - see `test_onhit_lead_is_not_asserted_away` for why that is a
refusal rather than an omission.

WHAT THIS SLICE DOES NOT MODEL - **SHIPPED SEPARATELY 2026-08-04, see
`test_extra_shot_procs_rm42.py`**: the second shot's **on-hit application** and
its **independent crit** are both outside this registry's expressive range. The registry carries
a damage magnitude on a cadence; it has no channel for "this champion applies
on-hit N times per auto" and none for per-passive crit. Caitlyn's own entry
already records the crit half of that limit verbatim ("+crit-chance AD
multiplier omitted (AA-crit seam)"). Those two are the aa-empower machinery the
RM-42 spec actually needs, and they are filed as the follow-on.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import _passive_damage_overrides as pdo
from agents.daemon_slayer import rank
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.rank import rank_items

_SNAP = DataSnapshot.load()
_LEVEL = 16
# Sweep-standard tanky target (docs/DS_SWEEP_TRACKER.md probe recipe).
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)
# His dominant real line, so the depth probe is not the known empty-build
# artifact that manufactured RM-35's retracted headline.
DEPTH = ["6672", "2523", "3006"]   # Kraken + Hexoptics C44 + Berserker's

_HEXOPTICS = "2523"
_IE = "3031"
_BOTRK = "3153"
_RUNAANS = "3085"


def _rank(champ, items=(), **kw):
    return rank_items(
        _SNAP, champ, level=_LEVEL, current_item_ids=list(items),
        mode="SR", top_n=None, **TARGET, **kw,
    )


def _ids(res):
    return tuple(r.item_id for r in res.ranked)


def _rows(res):
    """Full row fingerprint - proves byte-identity, not merely ordering."""
    return tuple(
        (r.item_id, r.delta_dps, r.new_dps, r.dps_per_1k_gold) for r in res.ranked
    )


class AkshanRegistryEntryTest(unittest.TestCase):
    """The authored entry matches the cited DDragon text, not the filing."""

    def test_akshan_passive_is_registered(self):
        self.assertIn(("Akshan", "P", 0), pdo._PASSIVE_DAMAGE_OVERRIDES)

    def test_entry_is_a_flat_50_pct_total_ad_physical_on_hit(self):
        e = pdo._PASSIVE_DAMAGE_OVERRIDES[("Akshan", "P", 0)]
        self.assertEqual(e.damage_type, "PHYSICAL")
        self.assertEqual(e.cadence, "on_hit")
        # "deals 50% AD physical damage" - flat at every level, no lerp, no
        # step. A level-scaled tuple here would be an invention.
        self.assertEqual(set(e.total_ad_pct), {50.0})
        self.assertEqual(len(e.total_ad_pct), pdo._LEVEL_COUNT)
        # Nothing else scales it. In particular there is no AP term: the 60% AP
        # in his innate belongs to the THIRD-STACK magic proc, a different
        # effect on a different cadence, and is deliberately not folded in.
        self.assertEqual(e.ap_pct, 0.0)
        self.assertEqual(e.bonus_ad_pct, 0.0)
        self.assertEqual(e.base, (0.0,))

    def test_note_records_both_unmodelled_halves(self):
        note = pdo._PASSIVE_DAMAGE_OVERRIDES[("Akshan", "P", 0)].note.lower()
        self.assertIn("on-hit", note)
        self.assertIn("crit", note)

    def test_akshan_is_on_the_every_aa_routing_allowlist(self):
        """The registry entry alone is INERT - the consumer reads a 5-member
        every-AA allowlist, not the registry at large. Measured 2026-08-04:
        adding the entry and nothing else left `compute_dps` byte-identical
        with the flag ON, no note emitted. Both edits are required."""
        self.assertIn(("Akshan", "P", 0), pdo._AA_ROUTED_ON_HIT_KEYS)
        self.assertIsNotNone(pdo.aa_routed_on_hit_entry("Akshan"))

    def test_an_every_nth_passive_stays_off_the_allowlist(self):
        """The allowlist's bar is EVERY basic attack with no internal CD, no
        mark to consume and no empowered-first-hit gate. Caitlyn Headshot is
        every Nth, so routing it would attribute a periodic bonus to every hit.
        Pinned so the Akshan addition cannot be read as licence to widen."""
        self.assertIn(("Caitlyn", "P", 0), pdo._PASSIVE_DAMAGE_OVERRIDES)
        self.assertNotIn(("Caitlyn", "P", 0), pdo._AA_ROUTED_ON_HIT_KEYS)
        self.assertIsNone(pdo.aa_routed_on_hit_entry("Caitlyn"))

    def test_the_100_pct_minion_variant_is_not_used(self):
        # "increased to 100% AD against minions" - the engine scores a
        # CHAMPION target, so crediting 100% would over-value him everywhere.
        e = pdo._PASSIVE_DAMAGE_OVERRIDES[("Akshan", "P", 0)]
        self.assertNotIn(100.0, set(e.total_ad_pct))


class PassiveDamageReachesTheCarryRankerTest(unittest.TestCase):
    def test_rank_items_carries_the_flag_default_off(self):
        import inspect

        params = inspect.signature(rank_items).parameters
        self.assertIn("apply_passive_damage", params)
        self.assertIs(params["apply_passive_damage"].default, False)

    def test_default_is_byte_identical(self):
        off = _rank("Akshan")
        explicit = _rank("Akshan", apply_passive_damage=False)
        self.assertEqual(_rows(off), _rows(explicit))

    def test_armed_flag_reorders_akshan_at_depth(self):
        off = _rank("Akshan", DEPTH)
        on = _rank("Akshan", DEPTH, apply_passive_damage=True)
        self.assertNotEqual(_ids(off), _ids(on))

    def test_a_champion_with_no_registry_entry_is_untouched(self):
        # The seam must be champion-SENSITIVE, not a blanket rescale. Resolved
        # from the registry rather than hard-coded, so that adding an entry for
        # this champion later fails here loudly instead of going vacuous.
        keys = {c for (c, _s, _i) in pdo._PASSIVE_DAMAGE_OVERRIDES}
        control = next(c for c in ("Aphelios", "Sivir", "Tristana") if c not in keys)
        off = _rank(control, DEPTH)
        on = _rank(control, DEPTH, apply_passive_damage=True)
        self.assertEqual(_rows(off), _rows(on), control)

    def test_the_passive_actually_adds_damage_for_akshan(self):
        """Not vacuous: the entry has to move compute_dps, or the reorder above
        would be measuring some unrelated flag side effect."""
        kw = dict(level=_LEVEL, mode="SR", item_ids=tuple(DEPTH), **TARGET)
        off = compute_dps(_SNAP, champion_id="Akshan", **kw)
        on = compute_dps(_SNAP, champion_id="Akshan", apply_passive_damage=True, **kw)
        self.assertGreater(on.weighted_dps, off.weighted_dps)


class AkshanOrderingIsMeasuredNotAssertedTest(unittest.TestCase):
    def test_hexoptics_is_reachable_and_ranked(self):
        """RM-42's one concrete pool claim: Hexoptics C44 2523 is IN the pool,
        merely under-ranked. Pinned so a future pool edit cannot silently make
        the rest of this file untestable."""
        res = _rank("Akshan")
        self.assertIn(_HEXOPTICS, _ids(res))

    def test_rm42_ordering_claim_is_REFUTED_by_the_completed_model(self):
        """RESOLVED 2026-08-04 by the follow-on. This test was authored as a
        non-closure marker that "SHOULD go red when the aa-empower follow-on
        ships". It did not go red, and that is the answer.

        The follow-on shipped the two halves this registry could not express -
        the second shot's on-hit APPLICATION and its independent CRIT
        (`_extra_shot_overrides`, ENGINE 1.274.0). With BOTH flags armed the
        model is +80.9 pct weighted DPS at depth, and on-hit items rise while
        crit items barely move: Guinsoo's #7 -> #6, Terminus #7 -> #5, Yun Tal
        #6 -> #7 DOWN, Hexoptics C44 #19 -> #17, and Runaan's / BotRK still
        take #1 / #2 at depth.

        So RM-42's prediction - that modelling Dirty Fighting drops generic
        on-hit out of the lead and lifts Hexoptics to his top-4 - is REFUTED by
        the completed model, not merely unproven by a partial one. It was an
        artifact of the filing's "200% crit double-shot" mis-read; the shipped
        text says the shot APPLIES ON-HIT, so a faithful model necessarily
        raises on-hit value.

        This assertion is kept, with its meaning inverted: it now pins the
        REFUTATION. If a future change makes crit lead here, that is a real
        finding about some other seam and this should be re-opened
        deliberately - not quietly deleted.
        """
        on = _rank("Akshan", DEPTH, apply_passive_damage=True)
        self.assertIn(_ids(on)[0], (_BOTRK, _RUNAANS))

    def test_onhit_lead_is_not_asserted_away(self):
        """A REFUSAL, recorded on purpose.

        The RM-42 filing predicts that modelling Dirty Fighting drops BotRK and
        Runaan's out of the lead. The shipped ability text says the second shot
        APPLIES ON-HIT EFFECTS, so a faithful model pushes on-hit value UP, not
        down. Asserting the filing's direction here would be shaping the test
        to a prediction the data contradicts - and this suite would then pin the
        wrong behaviour forever.

        What IS asserted: the flag moves the order (above), the movement is
        champion-specific (above), and whatever the on-hit items do under it is
        REPORTED in the ledger rather than legislated here. If a future slice
        models the second shot's on-hit application and crit, THAT is when the
        direction question can be asked honestly.
        """
        on = _rank("Akshan", DEPTH, apply_passive_damage=True)
        ids = _ids(on)
        # Both are still legitimate candidates for him - Runaan's is
        # ranged-purchasable and BotRK is in-pool. Their POSITION is the open
        # question; their PRESENCE is not a defect.
        self.assertIn(_BOTRK, ids)
        self.assertIn(_RUNAANS, ids)


class RoutePlumbTest(unittest.TestCase):
    """All three gates - engine kwarg, route parse, client."""

    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer import server

        server._CACHE.set(_SNAP)

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
                     "apply_passive_damage": True}
                )
        finally:
            server.rank_items = real
        self.assertTrue(seen.get("apply_passive_damage"))

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
        self.assertFalse(seen.get("apply_passive_damage"))

    def test_client_puts_the_flag_on_the_wire_only_when_armed(self):
        import core.daemon_slayer_client as dsc

        bodies = []

        def _post(path, body, *a, **kw):
            bodies.append(body)
            return {"ranked": [], "baseline_dps": 0.0}

        real = dsc._post_json
        dsc._post_json = _post
        try:
            dsc.rank_for("Akshan", level=16, item_ids=[], apply_passive_damage=True)
            dsc.rank_for("Akshan", level=16, item_ids=[])
        finally:
            dsc._post_json = real
        self.assertTrue(bodies[0].get("apply_passive_damage"))
        self.assertNotIn("apply_passive_damage", bodies[1])

    def test_stale_docstring_no_longer_claims_rank_already_parses_it(self):
        """`server.py` asserted that `/rank` parses `apply_passive_damage`
        while it provably did not. Now that it DOES, the sentence must not read
        as though it always did - the correction is the point."""
        from pathlib import Path

        src = Path("agents/daemon_slayer/server.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "NOT the ``apply_passive_damage`` flag that ``/rank`` and "
            "``/rank-onhit`` parse", src,
        )


if __name__ == "__main__":
    unittest.main()
