"""Heartsteel damage-half cadence correction (A-04 / RM-99b).

Heartsteel's Colossal Consumption damage half used to carry
``every_n_seconds=3.5`` on BOTH ids (SR 3084 + Arena mirror 223084). That constant
is neither of the two intervals the item's OWN feed data states: the 1-second stack
charge (3 stacks, so a 3-second charge window) or the 30-second PER-TARGET cooldown
that actually gates the empowered attack. ``dps._periodic_proc_dps`` computes
``procs = duration / every_n_seconds``, so a single-target rotation was credited
30 / 3.5 = 8.5714x the real proc count.

SHAPE AS SHIPPED (operator decision 2026-07-24):
  * SR 3084 carries the corrected ``every_n_seconds=30.0`` DIRECTLY in
    ``ITEM_EFFECTS``. The correction is DEFAULT-ON for SR and rides no flag at all,
    because all six scorer modules read ``ITEM_EFFECTS`` directly, so fixing the
    data table needs no consumer wire.
  * Arena mirror 223084 deliberately KEEPS 3.5. Per R161 doctrine B the mirror is
    credited from its own feed, and no feed states a cooldown for it: it is absent
    from Meraki entirely and its own DDragon description renders the cooldown as a
    zeroed ``(0s) per target`` template. 30s there would be inherited from the SR
    twin and unsourced, and Riot demonstrably retuned this mirror on other axes
    (700 vs 900 Health, 2500g vs 3000g).
  * ``HEARTSTEEL_CADENCE_FIX_IDS`` is therefore the Arena mirror ONLY, and
    ``apply_heartsteel_cadence_fix`` still defaults OFF - flipping it now moves the
    Arena mirror and nothing else.

What this file pins:
  * The SR value is 30.0 AND 30.0 is the FEED number - parsed out of the vendored
    Meraki passive text rather than typed here, so a patch that retunes the cooldown
    fails loudly instead of leaving a stale literal in a test. Because the SR
    correction is now the default, this pin is what stops the module from becoming a
    tautology that merely re-asserts whatever the table happens to say.
  * 3.5 is NOT the shipped SR value, so a revert of the table is loud.
  * The AGREEMENT between the item's two halves: R137's
    ``_item_health_stack._ASSUMED_PROCS_BY_LEVEL`` is derived from the per-target
    cooldown and its docstring says so. For SR the damage half and the EHP half now
    agree UNCONDITIONALLY, with no flag. For the Arena mirror they still disagree
    while the seam is off, and that is the deliberate, recorded state.
  * The measured magnitude, as a COMPUTED ratio at realistic shipped build depth
    (build_orders_*.json prefixes), never at ``item_ids=[]`` - the empty-build probe
    artifact has manufactured false headlines here three times - and never as a
    hardcoded DPS number.
"""
from __future__ import annotations

import dataclasses
import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer import _item_health_stack
from agents.daemon_slayer._effects_data import (
    HEARTSTEEL_CADENCE_FIX_IDS,
    HEARTSTEEL_PER_TARGET_COOLDOWN_S,
    ITEM_EFFECTS,
    apply_heartsteel_cadence_fix,
    heartsteel_per_target_cooldown_s,
)
from agents.daemon_slayer._effects_types import CallContext
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

_HEARTSTEEL = "3084"
_HEARTSTEEL_ARENA = "223084"

# The pre-correction constant. Still SHIPPED on the Arena mirror (deliberately) and
# still the value the SR entry must never drift back to.
_LEGACY_CADENCE = 3.5

# Shared context for the formula-preservation check (the correction must move the
# firing rate and nothing else).
_CTX = CallContext(base_ad=100.0, bonus_ad=80.0, level=16, caster_max_hp=3500.0)

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


def _meraki_items() -> dict:
    body = json.loads((_patch_dir() / "items_meraki.json").read_text(encoding="utf-8"))
    return body["items"]


def _ddragon_items() -> dict:
    body = json.loads((_patch_dir() / "items.json").read_text(encoding="utf-8"))
    return body["data"]


def _feed_per_target_cooldown_s() -> float:
    """Parse the per-target cooldown out of Meraki's OWN 3084 passive text.

    The passive body reads "... (30 second cooldown per target)". Parsing it keeps
    this file's expected value sourced rather than typed, which is the whole reason
    the module still proves something now that the correction is the default.
    """
    passives = _meraki_items()[_HEARTSTEEL]["passives"]
    for p in passives:
        m = re.search(
            r"\((\d+(?:\.\d+)?)\s*second cooldown per target\)",
            str(p.get("effects") or ""),
            re.I,
        )
        if m:
            return float(m.group(1))
    raise AssertionError("Meraki 3084 passive text no longer states a per-target cooldown")


def _cadence_of(effects: dict, item_id: str) -> float:
    procs = effects[item_id].periodics
    assert len(procs) == 1, f"{item_id} no longer has exactly one proc"
    return float(procs[0].every_n_seconds)


def _retimed(item_id: str, seconds: float):
    """The live entry with its seconds-based procs re-timed - formula untouched."""
    entry = ITEM_EFFECTS[item_id]
    return dataclasses.replace(
        entry,
        periodics=tuple(
            dataclasses.replace(p, every_n_seconds=seconds) for p in entry.periodics
        ),
    )


def _proc_stripped(item_id: str):
    return dataclasses.replace(ITEM_EFFECTS[item_id], periodics=())


def _shipped_build(filename: str, champion: str, depth: int = 5) -> list[str]:
    body = json.loads(
        (_patch_dir() / filename).read_text(encoding="utf-8")
    )["build_orders"]
    order = body[champion].get("balanced") or body[champion]["ad_heavy"]
    return list(order[:depth])


def _dps_with_entry(item_id: str, entry, champion: str, items: list[str], mode: str) -> float:
    """weighted_dps with ``item_id``'s effect entry swapped in, then restored.

    ``dps.py`` resolves item effects through the module-level ``ITEM_EFFECTS`` dict
    object, so the measurement swaps that one key in place.
    """
    saved = ITEM_EFFECTS[item_id]
    try:
        ITEM_EFFECTS[item_id] = entry
        res = compute_dps(
            _snap(), champion, 16, item_ids=items, mode=mode,
            target_armor=100.0, target_mr=60.0, target_max_hp=2400.0,
        )
        return float(res.weighted_dps)
    finally:
        ITEM_EFFECTS[item_id] = saved


# ---------------- the corrected constant is FEED-sourced ----------------


class CorrectedCadenceIsFeedSourcedTests(unittest.TestCase):
    def test_registry_covers_the_arena_mirror_only(self) -> None:
        self.assertEqual(set(HEARTSTEEL_CADENCE_FIX_IDS), {_HEARTSTEEL_ARENA})

    def test_sr_id_is_no_longer_behind_the_seam(self) -> None:
        # The SR correction shipped in the data table, so routing it through the
        # flag again would silently make it opt-in.
        self.assertNotIn(_HEARTSTEEL, HEARTSTEEL_CADENCE_FIX_IDS)

    def test_module_constant_equals_the_meraki_per_target_cooldown(self) -> None:
        self.assertAlmostEqual(
            HEARTSTEEL_PER_TARGET_COOLDOWN_S, _feed_per_target_cooldown_s(), places=9
        )

    def test_accessor_equals_the_meraki_per_target_cooldown(self) -> None:
        self.assertAlmostEqual(
            heartsteel_per_target_cooldown_s(), _feed_per_target_cooldown_s(), places=9
        )

    def test_corrected_cadence_is_not_the_legacy_constant(self) -> None:
        # Guards the whole point of the slice: a no-op "fix" must fail loudly.
        self.assertNotAlmostEqual(
            heartsteel_per_target_cooldown_s(), _LEGACY_CADENCE, places=6
        )

    def test_corrected_cadence_is_not_the_charge_window_either(self) -> None:
        # The stack charge is 1s x 3 stacks = 3s. The filing's whole complaint is
        # that 3.5 is NEITHER interval; the correction must pick the cooldown.
        self.assertNotAlmostEqual(heartsteel_per_target_cooldown_s(), 3.0, places=6)


# ---------------- SR ships the correction, unconditionally ----------------


class ShippedSrCadenceIsTheCorrectedOneTests(unittest.TestCase):
    """Anti-tautology pins for the DEFAULT-ON half.

    The SR correction is now the default, so a test that just reads the table back
    would prove nothing. Every assertion here is anchored to the number parsed out
    of the Meraki feed, or to the explicit statement that the legacy 3.5 is gone.
    """

    def test_sr_table_ships_the_feed_sourced_per_target_cooldown(self) -> None:
        self.assertAlmostEqual(
            _cadence_of(ITEM_EFFECTS, _HEARTSTEEL),
            _feed_per_target_cooldown_s(),
            places=9,
        )

    def test_sr_table_does_not_ship_the_legacy_cadence(self) -> None:
        # A revert of the table entry lands here first.
        self.assertNotAlmostEqual(
            _cadence_of(ITEM_EFFECTS, _HEARTSTEEL), _LEGACY_CADENCE, places=6
        )

    def test_sr_note_advertises_the_feed_cooldown_not_the_legacy_one(self) -> None:
        note = ITEM_EFFECTS[_HEARTSTEEL].note or ""
        self.assertIn(f"{int(_feed_per_target_cooldown_s()):d}s", note)
        self.assertNotIn(str(_LEGACY_CADENCE), note)

    def test_sr_entry_still_carries_exactly_one_seconds_based_proc(self) -> None:
        procs = ITEM_EFFECTS[_HEARTSTEEL].periodics
        self.assertEqual(len(procs), 1)
        self.assertGreater(procs[0].every_n_seconds, 0.0)
        self.assertEqual(procs[0].every_n_attacks, 0)


# ---------------- flag OFF leaves the shipped table alone ----------------


class FlagOffLeavesTheShippedTableAloneTests(unittest.TestCase):
    def test_default_call_returns_the_live_mapping_itself(self) -> None:
        self.assertIs(apply_heartsteel_cadence_fix(), ITEM_EFFECTS)

    def test_explicit_false_returns_the_live_mapping_itself(self) -> None:
        self.assertIs(
            apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=False),
            ITEM_EFFECTS,
        )

    def test_sr_cadence_is_already_corrected_with_the_flag_off(self) -> None:
        off = apply_heartsteel_cadence_fix()
        self.assertAlmostEqual(
            _cadence_of(off, _HEARTSTEEL), _feed_per_target_cooldown_s(), places=9
        )

    def test_arena_mirror_holds_the_legacy_cadence_with_the_flag_off(self) -> None:
        off = apply_heartsteel_cadence_fix()
        self.assertAlmostEqual(
            _cadence_of(off, _HEARTSTEEL_ARENA), _LEGACY_CADENCE, places=9
        )

    def test_a_supplied_mapping_is_returned_unchanged_when_off(self) -> None:
        src = dict(ITEM_EFFECTS)
        self.assertIs(apply_heartsteel_cadence_fix(src), src)


# ---------------- flag ON corrects ONLY the Arena mirror ----------------


class FlagOnCorrectsOnlyTheArenaMirrorTests(unittest.TestCase):
    def test_registered_ids_read_the_per_target_cooldown_when_on(self) -> None:
        on = apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        for iid in HEARTSTEEL_CADENCE_FIX_IDS:
            self.assertAlmostEqual(
                _cadence_of(on, iid), heartsteel_per_target_cooldown_s(), places=9, msg=iid
            )

    def test_sr_entry_is_the_same_object_and_cadence_when_on(self) -> None:
        on = apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        self.assertIs(on[_HEARTSTEEL], ITEM_EFFECTS[_HEARTSTEEL])
        self.assertAlmostEqual(
            _cadence_of(on, _HEARTSTEEL), _feed_per_target_cooldown_s(), places=9
        )

    def test_flag_on_does_not_mutate_the_module_registry(self) -> None:
        apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        self.assertAlmostEqual(
            _cadence_of(ITEM_EFFECTS, _HEARTSTEEL_ARENA), _LEGACY_CADENCE, places=9
        )
        self.assertAlmostEqual(
            _cadence_of(ITEM_EFFECTS, _HEARTSTEEL),
            _feed_per_target_cooldown_s(),
            places=9,
        )

    def test_flag_on_preserves_every_non_cadence_field(self) -> None:
        on = apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        for iid in HEARTSTEEL_CADENCE_FIX_IDS:
            before, after = ITEM_EFFECTS[iid], on[iid]
            self.assertEqual(after.item_id, before.item_id)
            self.assertEqual(after.name, before.name)
            self.assertEqual(after.note, before.note)
            b, a = before.periodics[0], after.periodics[0]
            self.assertEqual(a.name, b.name)
            self.assertEqual(a.damage_type, b.damage_type)
            self.assertEqual(a.every_n_attacks, b.every_n_attacks)
            # The damage FORMULA must be untouched - only the firing rate moves.
            self.assertAlmostEqual(
                a.bonus_damage(_CTX), b.bonus_damage(_CTX), places=9, msg=iid
            )

    def test_only_the_registered_arena_mirror_moves_when_on(self) -> None:
        on = apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        self.assertEqual(set(on), set(ITEM_EFFECTS))
        moved = {i for i in on if on[i] is not ITEM_EFFECTS[i]}
        self.assertEqual(moved, set(HEARTSTEEL_CADENCE_FIX_IDS))


# ---------------- the two halves ----------------


class BothHalvesAgreeOnPerTargetCooldownTests(unittest.TestCase):
    """The actual invariant worth pinning (A-04).

    R137's EHP half derives its proc curve from the per-target cooldown for BOTH
    ids; the damage half must read the same number. For SR that now holds with no
    flag. For the Arena mirror the disagreement survives on purpose, because 30s is
    unsourced on 223084's own feed (R161 doctrine B).
    """

    def test_ehp_half_documents_the_same_per_target_cooldown(self) -> None:
        cd = _feed_per_target_cooldown_s()
        doc = _item_health_stack.__doc__ or ""
        self.assertRegex(
            doc,
            rf"{int(cd):d}[ -]second cooldown PER TARGET",
            msg="the R137 EHP half no longer cites the per-target cooldown this "
                "correction is anchored to",
        )

    def test_sr_halves_agree_under_either_flag_state(self) -> None:
        # The A-04 inversion: no flag is involved for SR any more.
        cd = _feed_per_target_cooldown_s()
        for flag in (False, True):
            mapping = apply_heartsteel_cadence_fix(
                apply_heartsteel_per_target_cadence=flag
            )
            self.assertAlmostEqual(
                _cadence_of(mapping, _HEARTSTEEL), cd, places=9, msg=f"flag={flag}"
            )

    def test_the_arena_mirror_halves_disagree_while_the_flag_is_off(self) -> None:
        # Rewritten from the old SR-scoped claim, which is now FALSE. This is the
        # honest remainder: the mirror is the only half-disagreement still shipped,
        # so a default flip there becomes a visible edit to this file.
        off = apply_heartsteel_cadence_fix()
        self.assertNotAlmostEqual(
            _cadence_of(off, _HEARTSTEEL_ARENA), _feed_per_target_cooldown_s(), places=6
        )

    def test_the_arena_mirror_halves_agree_when_the_flag_is_on(self) -> None:
        on = apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        self.assertAlmostEqual(
            _cadence_of(on, _HEARTSTEEL_ARENA), _feed_per_target_cooldown_s(), places=9
        )


# ---------------- Arena mirror, R161 doctrine B ----------------


class ArenaMirrorProvenanceTests(unittest.TestCase):
    def test_arena_mirror_matches_the_sr_cadence_only_when_on(self) -> None:
        sr = _cadence_of(ITEM_EFFECTS, _HEARTSTEEL)
        off = apply_heartsteel_cadence_fix()
        on = apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        self.assertNotAlmostEqual(_cadence_of(off, _HEARTSTEEL_ARENA), sr, places=6)
        self.assertAlmostEqual(_cadence_of(on, _HEARTSTEEL_ARENA), sr, places=9)

    def test_arena_mirror_is_absent_from_meraki(self) -> None:
        # Pins WHY the mirror's cooldown would be inherited rather than sourced.
        self.assertNotIn(_HEARTSTEEL_ARENA, _meraki_items())

    def test_arena_mirror_ddragon_states_no_usable_cooldown(self) -> None:
        entry = _ddragon_items()[_HEARTSTEEL_ARENA]
        text = re.sub(r"<[^>]+>", " ", str(entry.get("description", "")))
        self.assertIn("per target", text.lower())
        stated = {float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*s\b", text)}
        # The template renders zeroed - so no positive cooldown is recoverable.
        self.assertTrue(
            all(v == 0.0 for v in stated),
            msg="223084's own DDragon description now states a cooldown - source the "
                "mirror from it and retire the seam instead of holding 3.5",
        )

    def test_arena_mirror_still_carries_exactly_one_legacy_timed_proc(self) -> None:
        procs = ITEM_EFFECTS[_HEARTSTEEL_ARENA].periodics
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0].every_n_attacks, 0)
        self.assertAlmostEqual(procs[0].every_n_seconds, _LEGACY_CADENCE, places=9)


# ---------------- measured magnitude at REAL build depth ----------------


_SR_CHAMPION = "Aatrox"


class MeasuredMagnitudeAtRealBuildDepthTests(unittest.TestCase):
    """The SHIPPED SR proc term must be the 30-second term, not the 3.5-second one.

    Re-anchored for the default flip: the flag no longer moves SR, so the
    measurement compares the SHIPPED entry against a hypothetical legacy-timed
    entry instead of against a flag state. Measured on a prefix of the SHIPPED SR
    build order (build_orders_sr.json), never at ``item_ids=[]`` - the empty-build
    probe artifact has manufactured false headlines three times. Asserted as a RATIO
    of computed quantities so no DPS literal can go stale.
    """

    def _build(self) -> list[str]:
        """A realistic-depth bruiser build that is GUARANTEED to hold Heartsteel.

        A-04 follow-up (2026-07-24): this used to read the shipped SR build order
        for ``_SR_CHAMPION`` and assert Heartsteel was in it. That assertion was
        self-defeating - the whole point of the cadence correction is that
        Heartsteel largely STOPS being bought (SR occurrences fell 135 -> 6 in the
        post-fix regen, and Aatrox now takes Randuin's 3143 in that slot), so the
        table this test read no longer contains the item it measures. The guard
        fired correctly; the anchor was wrong.

        Anchor instead on the shipped build with Heartsteel SUBSTITUTED into it.
        Depth, champion and the surrounding item stats stay real - which is the
        property that matters, since ``item_ids=[]`` under-ranks amp items and has
        manufactured false headlines three times - while the presence of the item
        under measurement no longer depends on the engine still recommending it.
        """
        items = list(_shipped_build("build_orders_sr.json", _SR_CHAMPION))
        self.assertGreaterEqual(
            len(items), 3, msg=f"shipped {_SR_CHAMPION} SR build is too short to measure"
        )
        if _HEARTSTEEL not in items:
            # Substitute rather than append: keep the slot count (and so the
            # rotation depth) identical to the shipped build.
            items[-1] = _HEARTSTEEL
        self.assertIn(_HEARTSTEEL, items)
        return items

    def _dps(self, entry, items: list[str]) -> float:
        return _dps_with_entry(_HEARTSTEEL, entry, _SR_CHAMPION, items, "SR")

    def _terms(self) -> tuple[float, float]:
        """(shipped proc term, legacy-timed proc term) isolated from item stats."""
        items = self._build()
        dps_none = self._dps(_proc_stripped(_HEARTSTEEL), items)
        dps_shipped = self._dps(ITEM_EFFECTS[_HEARTSTEEL], items)
        dps_legacy = self._dps(_retimed(_HEARTSTEEL, _LEGACY_CADENCE), items)
        return dps_shipped - dps_none, dps_legacy - dps_none

    def test_shipped_dps_equals_the_feed_cadence_dps(self) -> None:
        # Computed, not hardcoded: re-timing the entry to the FEED number must be a
        # no-op on credited DPS, which is what "the correction shipped" means.
        items = self._build()
        shipped = self._dps(ITEM_EFFECTS[_HEARTSTEEL], items)
        feed_timed = self._dps(
            _retimed(_HEARTSTEEL, _feed_per_target_cooldown_s()), items
        )
        self.assertAlmostEqual(shipped, feed_timed, places=9)

    def test_shipped_proc_term_is_the_legacy_term_over_the_cadence_ratio(self) -> None:
        term_shipped, term_legacy = self._terms()
        self.assertGreater(term_shipped, 0.0)
        expected = _feed_per_target_cooldown_s() / _LEGACY_CADENCE
        self.assertAlmostEqual(term_legacy / term_shipped, expected, places=3)

    def test_shipped_proc_term_is_strictly_smaller_than_the_legacy_one(self) -> None:
        term_shipped, term_legacy = self._terms()
        self.assertLess(term_shipped, term_legacy)


class ArenaMirrorMeasuredMagnitudeTests(unittest.TestCase):
    """The same magnitude claim on the mirror, where the flag DOES still move it.

    Measured at shipped Arena build depth (build_orders_arena.json prefix), same
    computed-ratio discipline, never at ``item_ids=[]``.
    """

    def _build(self) -> list[str]:
        items = _shipped_build("build_orders_arena.json", _SR_CHAMPION)
        self.assertIn(
            _HEARTSTEEL_ARENA,
            items,
            msg=f"shipped {_SR_CHAMPION} Arena build no longer buys the Heartsteel mirror",
        )
        return items

    def _dps(self, entry, items: list[str]) -> float:
        return _dps_with_entry(_HEARTSTEEL_ARENA, entry, _SR_CHAMPION, items, "ARENA")

    def test_shipped_arena_dps_is_the_legacy_cadence_dps(self) -> None:
        # The mirror ships the legacy cadence on purpose, so re-timing it to the FEED
        # number must MOVE credited DPS (the SR-side no-op does not hold here).
        items = self._build()
        shipped = self._dps(ITEM_EFFECTS[_HEARTSTEEL_ARENA], items)
        legacy = self._dps(_retimed(_HEARTSTEEL_ARENA, _LEGACY_CADENCE), items)
        feed_timed = self._dps(
            _retimed(_HEARTSTEEL_ARENA, _feed_per_target_cooldown_s()), items
        )
        self.assertAlmostEqual(shipped, legacy, places=9)
        self.assertGreater(shipped, feed_timed)

    def test_flag_on_shrinks_the_term_by_exactly_the_cadence_ratio(self) -> None:
        items = self._build()
        dps_none = self._dps(_proc_stripped(_HEARTSTEEL_ARENA), items)
        off = apply_heartsteel_cadence_fix()
        on = apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)
        term_off = self._dps(off[_HEARTSTEEL_ARENA], items) - dps_none
        term_on = self._dps(on[_HEARTSTEEL_ARENA], items) - dps_none
        self.assertGreater(term_on, 0.0)
        expected = _feed_per_target_cooldown_s() / _LEGACY_CADENCE
        self.assertAlmostEqual(term_off / term_on, expected, places=3)

    def test_flag_on_strictly_lowers_credited_arena_dps(self) -> None:
        items = self._build()
        dps_off = self._dps(apply_heartsteel_cadence_fix()[_HEARTSTEEL_ARENA], items)
        dps_on = self._dps(
            apply_heartsteel_cadence_fix(apply_heartsteel_per_target_cadence=True)[
                _HEARTSTEEL_ARENA
            ],
            items,
        )
        self.assertLess(dps_on, dps_off)


if __name__ == "__main__":
    unittest.main()
