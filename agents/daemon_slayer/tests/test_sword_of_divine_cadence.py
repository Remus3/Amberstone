"""Sword of the Divine (3131) active-cooldown cadence correction.

3131's Divine Judgment proc used to carry ``every_n_seconds=15.0``. That constant
is uncited: nothing in any loaded feed states 15 seconds for this item. The item's
OWN DDragon line states a 90 second active cooldown twice - once rendered into the
description text as ``(90(0s))`` and once as ``effect.Effect5Amount = "90"``.
``dps._periodic_proc_dps`` computes ``procs = duration / every_n_seconds``, so the
old constant credited 90 / 15 = 6x the real proc count.

3131 is absent from Meraki entirely, so DDragon is the only feed carrying a number
for it; per R161 doctrine B the correction is sourced from 3131's own feed line and
never inherited from a same-named sibling.

WHAT THIS FILE PINS

  * The shipped cadence equals the number PARSED OUT OF the description text in
    ``items.json``, not a literal typed here. Because the correction ships
    DEFAULT-ON in the data table, a test that merely read the table back would be
    a tautology; anchoring to the feed means a patch that retunes the cooldown
    fails loudly instead of leaving a stale constant behind.
  * The two independent statements of the cooldown on that same feed line - the
    description render and ``effect.Effect5Amount`` - agree with each other.
  * 15.0 is NOT the shipped value and is NOT a number the feed states, so a revert
    is loud and so is a re-introduction of the uncited constant.
  * The MAP LEGALITY of 3131, which is the blast-radius fact: maps 11 / 12 / 30 /
    35 are all false and only 21 (Nexus Blitz) is true. The item is therefore
    unbuyable in every mode ``rank.MODE_MAP_ID`` wires (SR, ARAM, ARENA, BRAWL)
    and cannot enter a candidate pool in any of them. NOTE this contradicts a
    common mis-reading of the feed: map 21 is Nexus Blitz, NOT the Howling Abyss.
    ARAM is map 12, and 3131's map-12 flag is FALSE.
  * The measured magnitude as a COMPUTED ratio at realistic shipped-build depth
    (a build_orders_aram.json prefix with 3131 substituted into the last slot),
    never at ``item_ids=[]`` - the empty-build probe artifact has manufactured
    false headlines here three times - and never as a hardcoded DPS number.
  * That the proc lambda is actually INVOKED at that build depth, via a spy, so a
    "no movement" reading can never be mistaken for a dead code path.
"""
from __future__ import annotations

import dataclasses
import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import PHYSICAL, CallContext
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.rank import MODE_MAP_ID, _filter_candidates, _is_legal_in_mode

_SOTD = "3131"

# The pre-correction constant. Uncited by any feed; the value the entry must never
# drift back to.
_LEGACY_CADENCE = 15.0

# DDragon map ids. 21 is Nexus Blitz - the only map 3131 is legal on.
_MAP_SR = "11"
_MAP_ARAM = "12"
_MAP_NEXUS_BLITZ = "21"
_MAP_ARENA = "30"
_MAP_BRAWL = "35"

_CTX = CallContext(base_ad=110.0, bonus_ad=140.0, level=16, crit_chance=0.6)

_DATA_ROOT = Path(__file__).resolve().parents[3] / "data" / "daemon_slayer"

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _patch_dir() -> Path:
    patch = (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()
    return _DATA_ROOT / patch


def _ddragon_items() -> dict:
    body = json.loads((_patch_dir() / "items.json").read_text(encoding="utf-8"))
    return body["data"]


def _plain_description(item_id: str) -> str:
    return re.sub(r"<[^>]+>", " ", str(_ddragon_items()[item_id].get("description") or ""))


def _feed_active_cooldown_s() -> float:
    """Parse the active cooldown out of 3131's OWN DDragon description text.

    DDragon renders the cooldown as ``(90(0s))`` - the authored number followed by
    a zeroed template. Parsing it keeps the expected value sourced rather than
    typed, which is the only reason this module proves anything now that the
    correction is the shipped default.
    """
    text = _plain_description(_SOTD)
    m = re.search(r"\((\d+(?:\.\d+)?)\(\d+(?:\.\d+)?s\)\)", text)
    if m is None:
        raise AssertionError(
            "3131's DDragon description no longer renders a cooldown in the "
            "'<n>(<t>s)' form - re-source the cadence before trusting this file"
        )
    return float(m.group(1))


def _feed_effect_cooldown_s() -> float:
    """The same cooldown as stated by the structured ``effect`` block."""
    effect = _ddragon_items()[_SOTD].get("effect") or {}
    raw = effect.get("Effect5Amount")
    if raw is None:
        raise AssertionError("3131's DDragon effect block no longer carries Effect5Amount")
    return float(raw)


def _cadence_of(item_id: str) -> float:
    procs = ITEM_EFFECTS[item_id].periodics
    assert len(procs) == 1, f"{item_id} no longer has exactly one proc"
    return float(procs[0].every_n_seconds)


def _retimed(item_id: str, seconds: float):
    """The live entry with its seconds-based proc re-timed - formula untouched."""
    entry = ITEM_EFFECTS[item_id]
    return dataclasses.replace(
        entry,
        periodics=tuple(
            dataclasses.replace(p, every_n_seconds=seconds) for p in entry.periodics
        ),
    )


def _proc_stripped(item_id: str):
    return dataclasses.replace(ITEM_EFFECTS[item_id], periodics=())


def _aram_build_with_sotd(champion: str, depth: int = 5) -> list[str]:
    """A shipped ARAM build prefix with 3131 substituted into the trailing slot.

    3131 never appears in a generated build order (it is map-illegal everywhere
    RC coaches), so the honest probe is a SUBSTITUTION into a real build rather
    than a ranking anchored on the engine recommending it - and never the empty
    build, whose probe artifact under-ranks amp / complementary items.
    """
    body = json.loads(
        (_patch_dir() / "build_orders_aram.json").read_text(encoding="utf-8")
    )["build_orders"]
    order = body[champion].get("balanced") or body[champion]["ad_heavy"]
    return list(order[:depth]) + [_SOTD]


def _dps_with_entry(entry, champion: str, items: list[str]) -> float:
    """weighted_dps with 3131's effect entry swapped in, then restored.

    ``dps.py`` resolves item effects through the module-level ``ITEM_EFFECTS``
    dict object, so the measurement swaps that one key in place.
    """
    saved = ITEM_EFFECTS[_SOTD]
    try:
        ITEM_EFFECTS[_SOTD] = entry
        res = compute_dps(
            _snap(), champion, 16, item_ids=items, mode="ARAM",
            target_armor=100.0, target_mr=60.0, target_max_hp=2400.0,
        )
        return float(res.weighted_dps)
    finally:
        ITEM_EFFECTS[_SOTD] = saved


# ---------------- the corrected constant is FEED-sourced ----------------


class CorrectedCadenceIsFeedSourcedTests(unittest.TestCase):
    def test_description_states_a_positive_active_cooldown(self) -> None:
        self.assertGreater(_feed_active_cooldown_s(), 0.0)

    def test_description_and_effect_block_agree(self) -> None:
        # Two independent statements on the SAME feed line. If they ever diverge,
        # the cadence needs re-sourcing rather than a silent pick.
        self.assertAlmostEqual(
            _feed_active_cooldown_s(), _feed_effect_cooldown_s(), places=9
        )

    def test_feed_cooldown_is_not_the_legacy_constant(self) -> None:
        # The whole filing: 15.0 is a number no feed states.
        self.assertNotAlmostEqual(_feed_active_cooldown_s(), _LEGACY_CADENCE, places=6)

    def test_no_feed_number_on_this_line_equals_the_legacy_constant(self) -> None:
        # Stronger than the pin above: 15 is not recoverable from ANY field of
        # 3131's own DDragon record, so it cannot be defended as a re-read.
        effect = _ddragon_items()[_SOTD].get("effect") or {}
        stated = {float(v) for v in effect.values()}
        stated |= {
            float(v) for v in re.findall(r"\d+(?:\.\d+)?", _plain_description(_SOTD))
        }
        self.assertNotIn(_LEGACY_CADENCE, stated)

    def test_item_is_absent_from_meraki_so_ddragon_is_the_only_source(self) -> None:
        meraki = json.loads(
            (_patch_dir() / "items_meraki.json").read_text(encoding="utf-8")
        )["items"]
        self.assertNotIn(_SOTD, meraki)


# ---------------- the shipped table carries the feed number ----------------


class ShippedCadenceIsTheCorrectedOneTests(unittest.TestCase):
    def test_table_ships_the_feed_sourced_active_cooldown(self) -> None:
        self.assertAlmostEqual(_cadence_of(_SOTD), _feed_active_cooldown_s(), places=9)

    def test_table_does_not_ship_the_legacy_cadence(self) -> None:
        self.assertNotAlmostEqual(_cadence_of(_SOTD), _LEGACY_CADENCE, places=6)

    def test_entry_still_carries_exactly_one_seconds_based_proc(self) -> None:
        procs = ITEM_EFFECTS[_SOTD].periodics
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0].name, "Divine Judgment")
        self.assertGreater(procs[0].every_n_seconds, 0.0)
        self.assertEqual(procs[0].every_n_attacks, 0)

    def test_lethality_and_damage_type_are_untouched(self) -> None:
        entry = ITEM_EFFECTS[_SOTD]
        self.assertAlmostEqual(entry.lethality, 18.0, places=2)
        self.assertEqual(entry.periodics[0].damage_type, PHYSICAL)

    def test_damage_formula_is_still_one_guaranteed_crit_worth_of_total_ad(self) -> None:
        # Only the firing RATE moves in this slice; the magnitude is deliberately
        # left alone (see the entry comment on the unmodelled timed window).
        proc = ITEM_EFFECTS[_SOTD].periodics[0]
        self.assertAlmostEqual(
            proc.bonus_damage(_CTX), 0.75 * (_CTX.base_ad + _CTX.bonus_ad), places=6
        )

    def test_note_advertises_the_feed_cooldown_not_the_legacy_one(self) -> None:
        note = ITEM_EFFECTS[_SOTD].note or ""
        self.assertIn(f"{int(_feed_active_cooldown_s()):d}s", note)
        self.assertNotIn(f"{int(_LEGACY_CADENCE):d}s", note)


# ---------------- map legality (the blast radius) ----------------


class MapLegalityTests(unittest.TestCase):
    """3131 is a Nexus Blitz item. It is NOT ARAM-legal and NOT SR-legal.

    Map 21 is Nexus Blitz; the Howling Abyss is map 12. The map-21 pool on this
    feed is the classic Nexus Blitz set (Ghostcrawlers 3005, Deathfire Grasp
    3128, Innervating Locket 4402, The Golden Spatula 4403, and 3131), which is
    what makes the reading unambiguous.
    """

    def setUp(self) -> None:
        self.maps = _ddragon_items()[_SOTD]["maps"]

    def test_legal_on_nexus_blitz(self) -> None:
        self.assertTrue(self.maps[_MAP_NEXUS_BLITZ])

    def test_not_legal_on_summoners_rift(self) -> None:
        self.assertFalse(self.maps[_MAP_SR])

    def test_not_legal_on_the_howling_abyss(self) -> None:
        # The ARAM claim, stated the right way round.
        self.assertFalse(self.maps[_MAP_ARAM])

    def test_not_legal_on_arena_or_brawl(self) -> None:
        self.assertFalse(self.maps[_MAP_ARENA])
        self.assertFalse(self.maps[_MAP_BRAWL])

    def test_map_21_is_nexus_blitz_not_the_howling_abyss(self) -> None:
        # Anchors the id reading itself: an ARAM-only staple is map 12 and a
        # Rift staple is map 11, so 21 can be neither.
        items = _ddragon_items()
        self.assertTrue(items["3031"]["maps"][_MAP_SR])       # Infinity Edge, SR
        self.assertTrue(items["3031"]["maps"][_MAP_ARAM])     # ... and ARAM
        self.assertTrue(items["3005"]["maps"][_MAP_NEXUS_BLITZ])   # Ghostcrawlers
        self.assertFalse(items["3005"]["maps"][_MAP_SR])
        self.assertFalse(items["3005"]["maps"][_MAP_ARAM])

    def test_illegal_in_every_wired_engine_mode(self) -> None:
        record = _ddragon_items()[_SOTD]
        for mode in MODE_MAP_ID:
            self.assertFalse(_is_legal_in_mode(record, mode), msg=mode)

    def test_never_enters_a_candidate_pool_in_any_wired_mode(self) -> None:
        for mode in MODE_MAP_ID:
            pool = _filter_candidates(
                _snap(), mode, set(), None, True, None,
            )
            self.assertNotIn(_SOTD, {iid for iid, _ in pool}, msg=mode)

    def test_absent_from_every_shipped_build_order_artifact(self) -> None:
        for name in ("build_orders_sr.json", "build_orders_aram.json",
                     "build_orders_arena.json"):
            body = json.loads((_patch_dir() / name).read_text(encoding="utf-8"))
            ids = {i for order in body["build_orders"].values()
                   for slots in order.values() for i in slots}
            self.assertNotIn(_SOTD, ids, msg=name)


# ---------------- no mirror inherits, and no sibling is touched ----------------


class SiblingProvenanceTests(unittest.TestCase):
    def test_no_id_suffix_sibling_exists(self) -> None:
        # R161 doctrine B: a mirror would need its OWN source. There is none.
        hits = [i for i in _ddragon_items() if i.endswith(_SOTD)]
        self.assertEqual(hits, [_SOTD])

    def test_same_named_siblings_are_a_different_item_and_untouched(self) -> None:
        # 443060 / 663060 share the display NAME but carry Excoriate (bonus crit
        # damage), have no periodic proc at all, and must not inherit this fix.
        for sibling in ("443060", "663060"):
            self.assertIn("Excoriate", _plain_description(sibling), msg=sibling)
            self.assertEqual(ITEM_EFFECTS[sibling].periodics, (), msg=sibling)


# ---------------- measured magnitude, at shipped-build depth ----------------


class MeasuredOverCreditTests(unittest.TestCase):
    """The correction must reduce credited DPS by exactly the cadence ratio.

    ``_periodic_proc_dps`` is linear in ``1 / every_n_seconds``, so the proc's
    contribution above a proc-stripped baseline scales exactly with the cadence.
    Asserting the RATIO rather than a DPS number keeps this valid across patches.
    """

    CHAMPION = "Jinx"

    def setUp(self) -> None:
        self.items = _aram_build_with_sotd(self.CHAMPION)

    def test_the_probe_build_is_a_realistic_depth_not_an_empty_list(self) -> None:
        self.assertEqual(len(self.items), 6)
        self.assertIn(_SOTD, self.items)

    def test_proc_lambda_is_actually_invoked_at_this_build_depth(self) -> None:
        # Proves any "no movement" reading below is a real measurement of a live
        # code path, not a silently skipped proc.
        calls: list[float] = []
        base = ITEM_EFFECTS[_SOTD].periodics[0]

        def _spy(ctx: CallContext) -> float:
            value = 0.75 * (ctx.base_ad + ctx.bonus_ad)
            calls.append(value)
            return value

        spied = dataclasses.replace(
            ITEM_EFFECTS[_SOTD],
            periodics=(dataclasses.replace(base, bonus_damage=_spy),),
        )
        _dps_with_entry(spied, self.CHAMPION, self.items)
        self.assertTrue(calls, "Divine Judgment never resolved - probe is dead")
        self.assertTrue(all(v > 0.0 for v in calls))

    def test_corrected_cadence_credits_strictly_less_than_the_legacy_one(self) -> None:
        corrected = _dps_with_entry(ITEM_EFFECTS[_SOTD], self.CHAMPION, self.items)
        legacy = _dps_with_entry(
            _retimed(_SOTD, _LEGACY_CADENCE), self.CHAMPION, self.items
        )
        self.assertLess(corrected, legacy)

    def test_proc_contribution_shrinks_by_exactly_the_cadence_ratio(self) -> None:
        stripped = _dps_with_entry(
            _proc_stripped(_SOTD), self.CHAMPION, self.items
        )
        corrected = _dps_with_entry(ITEM_EFFECTS[_SOTD], self.CHAMPION, self.items)
        legacy = _dps_with_entry(
            _retimed(_SOTD, _LEGACY_CADENCE), self.CHAMPION, self.items
        )
        self.assertGreater(corrected - stripped, 0.0)
        self.assertAlmostEqual(
            (legacy - stripped) / (corrected - stripped),
            _feed_active_cooldown_s() / _LEGACY_CADENCE,
            places=6,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
