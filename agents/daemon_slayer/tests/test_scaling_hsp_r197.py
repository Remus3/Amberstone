"""R197 - SCALING Heal/Shield Power grants (the mana-regen axis).

The defect class this pins: ``enchanter_items.json``'s ``heal_shield_amp_pct``
stores ONLY the FLAT printed Heal-and-Shield-Power stat. Items that grant
ADDITIONAL HSP through a SCALING clause carry that clause in the Meraki
``passives[].effects`` PROSE field and in the DDragon ``description`` passive
body - never in a stat key - and their Meraki top-level ``stats`` is ``None``, so
a stat-key scan finds nothing. Dawncore prints 16% HSP and the curated field
stores exactly 0.16; its First Light clause ("Gain 2% heal and shield power ...
for every additional 100% base mana regeneration") earns ZERO today.

Everything asserted here is read back out of the SHIPPED patch snapshot
(``data/daemon_slayer/<patch>/items.json`` + ``items_meraki.json``), never from a
hand-copied constant, so a patch re-extract that moves a magnitude fails loudly.

The most valuable test in this file is ``ScalingHspClassCompletenessTests``: it
re-derives the candidate class from the shipped prose AT TEST TIME and asserts
the module's ARMED registry plus its KNOWN-EXCLUDED set together account for
every candidate. That makes the class enumeration machine-checked rather than a
claim in a commit message - a new patch item mentioning HSP in prose fails the
suite until a human classifies it.
"""
from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._hsp_amp import sum_wielder_hsp_pct
from agents.daemon_slayer._scaling_hsp import (
    KNOWN_EXCLUDED_SCALING_HSP_IDS,
    MANA_REGEN_STEP_PCT,
    SCALING_HSP_CLASS_IDS,
    SCALING_HSP_PER_MANA_REGEN_STEP,
    load_base_mana_regen_pct_table,
    sum_scaling_hsp_pct,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# ARMED ids - the mana-regen axis (First Light). Each mirror carries its OWN
# per-step magnitude AND its own printed base mana regen (R161 doctrine B).
_DAWNCORE_SR = "6621"
_DAWNCORE_ARENA = "226621"
_DAWNCORE_ARAM = "326621"

# KNOWN-EXCLUDED - HSP CONSUMERS. Byte-similar prose, opposite direction: these
# read the wielder's HSP and pay out attack speed. A name/substring fold would
# wrongly include them.
_SWORD_BLOSSOMING_DAWN = ("4011", "124011", "664011")
_PUPPETEER = "447123"

# KNOWN-EXCLUDED - live target state.
_ELEISAS_MIRACLE = "443063"

# KNOWN-EXCLUDED - bonus-mana axis (REFUTED at this seam, see the module).
_WHISPERING_CIRCLET = ("2526", "222526", "322526")
_DIADEM_OF_SONGS = ("2530", "222530", "322530")

# Flat-HSP controls that must never gain a scaling term.
_REDEMPTION = "3107"
_MIKAEL = "3222"
_MOONSTONE = "6617"  # ally_chain_only - the R143 skip must survive


def _current_patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _curated_enchanter_items() -> dict:
    path = _DATA_ROOT / _current_patch() / "enchanter_items.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def _ddragon_items() -> dict:
    path = _DATA_ROOT / _current_patch() / "items.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _meraki_items() -> dict:
    path = _DATA_ROOT / _current_patch() / "items_meraki.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


_TAG = re.compile(r"<[^>]+>")
_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.DOTALL | re.IGNORECASE)
_WS = re.compile(r"\s+")
_HSP_PHRASE = re.compile(r"heal and shield power", re.IGNORECASE)
_BMR_LINE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*Base Mana Regen", re.IGNORECASE)


def _plain(text: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", text or "")).strip()


def _passive_body(description: str) -> str:
    """DDragon description with the printed <stats> block REMOVED.

    Why: the flat HSP stat lives in that block on ~14 items that carry no
    scaling clause at all. Scanning the whole description would fold the flat
    stat line into the scaling-clause candidate set.
    """
    return _plain(_STATS_BLOCK.sub(" ", description or ""))


def _expected_flat_hsp(item_ids) -> float:
    """Re-implement the PRE-CHANGE sum straight from the curated JSON.

    Deliberately does NOT import a stored snapshot of expected values - this is
    the independent oracle the OFF-is-identical sweep compares against.
    """
    items = _curated_enchanter_items()
    total = 0.0
    for iid in item_ids:
        rec = items.get(str(iid))
        if rec is None:
            continue
        if rec.get("ally_chain_only"):
            continue
        total += float(rec.get("heal_shield_amp_pct") or 0.0)
    return total


class OffIsByteIdenticalTests(unittest.TestCase):
    """The DEFAULT-OFF contract: every existing caller is untouched."""

    def test_every_curated_id_singleton_matches_the_pre_change_sum(self) -> None:
        items = _curated_enchanter_items()
        self.assertGreater(len(items), 0)
        for iid in sorted(items, key=int):
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(
                    sum_wielder_hsp_pct([iid]),
                    _expected_flat_hsp([iid]),
                    places=12,
                )

    def test_default_call_signature_is_unchanged_for_multi_item_builds(self) -> None:
        builds = [
            [_REDEMPTION, _MIKAEL],
            [_DAWNCORE_SR, _REDEMPTION, _MIKAEL],
            [_DAWNCORE_ARENA, "223107", "223222"],
            [_DAWNCORE_ARAM, "323107", "323222"],
            [_DAWNCORE_SR, _MOONSTONE, _REDEMPTION],
            [_DAWNCORE_SR] + list(_WHISPERING_CIRCLET),
            list(_SWORD_BLOSSOMING_DAWN) + [_ELEISAS_MIRACLE, _PUPPETEER],
            [_DAWNCORE_SR, "9999999", _REDEMPTION],
        ]
        for build in builds:
            with self.subTest(build=repr(build)):
                self.assertAlmostEqual(
                    sum_wielder_hsp_pct(build),
                    _expected_flat_hsp(build),
                    places=12,
                )

    def test_explicit_off_equals_default(self) -> None:
        build = [_DAWNCORE_SR, _REDEMPTION, _MIKAEL]
        self.assertEqual(
            sum_wielder_hsp_pct(build),
            sum_wielder_hsp_pct(build, assume_scaling_hsp_grants=False),
        )

    def test_moonstone_ally_chain_skip_is_not_resurrected_when_armed(self) -> None:
        """R143: Moonstone is an ally-chain ratio, not a wielder stat."""
        off = sum_wielder_hsp_pct([_MOONSTONE])
        armed = sum_wielder_hsp_pct([_MOONSTONE], assume_scaling_hsp_grants=True)
        self.assertAlmostEqual(off, 0.0, places=12)
        self.assertAlmostEqual(armed, 0.0, places=12)


class DawncoreArmedCharacterizationTests(unittest.TestCase):
    """Exact ARMED magnitudes, arithmetic spelled out for a hand check."""

    def test_dawncore_sr_alone(self) -> None:
        # 6621 prints 100% Base Mana Regen and grants 2% HSP per 100% step.
        #   steps = floor(100 / 100) = 1
        #   scaling = 1 * 0.02 = 0.02
        table = load_base_mana_regen_pct_table()
        self.assertAlmostEqual(table[_DAWNCORE_SR], 100.0, places=6)
        self.assertAlmostEqual(SCALING_HSP_PER_MANA_REGEN_STEP[_DAWNCORE_SR], 0.02)
        self.assertAlmostEqual(sum_scaling_hsp_pct([_DAWNCORE_SR]), 0.02, places=12)
        # Total through the seam = flat 0.16 + scaling 0.02 = 0.18.
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([_DAWNCORE_SR], assume_scaling_hsp_grants=True),
            0.18,
            places=12,
        )

    def test_dawncore_arena_mirror_alone(self) -> None:
        # 226621 prints 200% Base Mana Regen and grants 3% HSP per 100% step.
        #   steps = floor(200 / 100) = 2
        #   scaling = 2 * 0.03 = 0.06
        table = load_base_mana_regen_pct_table()
        self.assertAlmostEqual(table[_DAWNCORE_ARENA], 200.0, places=6)
        self.assertAlmostEqual(SCALING_HSP_PER_MANA_REGEN_STEP[_DAWNCORE_ARENA], 0.03)
        self.assertAlmostEqual(sum_scaling_hsp_pct([_DAWNCORE_ARENA]), 0.06, places=12)
        # Total = flat 0.12 + scaling 0.06 = 0.18.
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([_DAWNCORE_ARENA], assume_scaling_hsp_grants=True),
            0.18,
            places=12,
        )

    def test_dawncore_aram_mirror_alone_floors_to_one_step(self) -> None:
        # 326621 prints 150% Base Mana Regen and grants 2% HSP per 100% step.
        #   steps = floor(150 / 100) = 1   <- the 50% remainder earns NOTHING
        #   scaling = 1 * 0.02 = 0.02
        table = load_base_mana_regen_pct_table()
        self.assertAlmostEqual(table[_DAWNCORE_ARAM], 150.0, places=6)
        self.assertAlmostEqual(SCALING_HSP_PER_MANA_REGEN_STEP[_DAWNCORE_ARAM], 0.02)
        self.assertAlmostEqual(sum_scaling_hsp_pct([_DAWNCORE_ARAM]), 0.02, places=12)
        # Total = flat 0.20 + scaling 0.02 = 0.22.
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([_DAWNCORE_ARAM], assume_scaling_hsp_grants=True),
            0.22,
            places=12,
        )

    def test_regen_from_other_items_advances_the_step_count(self) -> None:
        # 6621 (100%) + 3107 Redemption (100%) = 200% -> floor(200/100) = 2 steps
        #   scaling = 2 * 0.02 = 0.04
        table = load_base_mana_regen_pct_table()
        self.assertAlmostEqual(table[_REDEMPTION], 100.0, places=6)
        self.assertAlmostEqual(
            sum_scaling_hsp_pct([_DAWNCORE_SR, _REDEMPTION]), 0.04, places=12
        )

    def test_a_sub_step_remainder_earns_nothing(self) -> None:
        # 6621 (100%) + 2526 Whispering Circlet (75%) = 175% -> 1 step -> 0.02.
        table = load_base_mana_regen_pct_table()
        self.assertAlmostEqual(table["2526"], 75.0, places=6)
        self.assertAlmostEqual(
            sum_scaling_hsp_pct([_DAWNCORE_SR, "2526"]), 0.02, places=12
        )

    def test_step_count_is_a_floor_of_the_summed_regen(self) -> None:
        table = load_base_mana_regen_pct_table()
        for build in (
            [_DAWNCORE_SR],
            [_DAWNCORE_SR, _REDEMPTION],
            [_DAWNCORE_SR, _MIKAEL, "3504"],
            [_DAWNCORE_ARENA, "223107"],
            [_DAWNCORE_ARAM, "323107", "323222"],
        ):
            with self.subTest(build=repr(build)):
                total_regen = sum(table.get(i, 0.0) for i in set(build))
                steps = math.floor(total_regen / MANA_REGEN_STEP_PCT)
                rate = max(SCALING_HSP_PER_MANA_REGEN_STEP[i] for i in build
                           if i in SCALING_HSP_PER_MANA_REGEN_STEP)
                self.assertAlmostEqual(
                    sum_scaling_hsp_pct(build), steps * rate, places=12
                )

    def test_int_ids_resolve_like_str_ids(self) -> None:
        self.assertAlmostEqual(sum_scaling_hsp_pct([6621]), 0.02, places=12)

    def test_a_repeated_armed_id_is_credited_once(self) -> None:
        """First Light is a UNIQUE passive over a SHARED regen pool."""
        self.assertAlmostEqual(
            sum_scaling_hsp_pct([_DAWNCORE_SR, _DAWNCORE_SR]), 0.02, places=12
        )

    def test_the_clause_is_applied_once_at_the_highest_registered_rate(self) -> None:
        """A synthetic build listing two mirrors applies First Light ONCE.

        The ``_item_mana_health`` Awe doctrine: a unique passive over a shared
        conversion pool, so the highest single instance applies. This input is
        impossible in a real build (Dawncore is unique and the mode mirrors are
        mutually exclusive), which is exactly why it is worth pinning - the
        engine must not turn an inconsistent synthetic inventory into a
        per-mirror double application.

        Arithmetic: pooled regen 100 + 200 = 300 -> floor(300/100) = 3 steps.
          credited  = 3 * max(0.02, 0.03) = 3 * 0.03 = 0.09
          per-item  = 3 * (0.02 + 0.03)   = 0.15      <- what must NOT happen
        """
        both = sum_scaling_hsp_pct([_DAWNCORE_SR, _DAWNCORE_ARENA])
        rates = SCALING_HSP_PER_MANA_REGEN_STEP
        self.assertAlmostEqual(both, 3 * max(rates[_DAWNCORE_SR],
                                             rates[_DAWNCORE_ARENA]), places=12)
        self.assertAlmostEqual(both, 0.09, places=12)
        self.assertLess(
            both, 3 * (rates[_DAWNCORE_SR] + rates[_DAWNCORE_ARENA]) - 1e-12
        )


class OwnPrintedRegenAssumptionTests(unittest.TestCase):
    """Names the shipped reading of "for every ADDITIONAL 100%"."""

    def test_dawncores_own_printed_regen_counts_toward_its_own_threshold(self) -> None:
        # ASSUMPTION SHIPPED: "additional" is measured over the champion's
        # innate 100% baseline, and item-granted regen IS that additional
        # amount, so the item's OWN printed line counts. Dawncore alone
        # therefore earns exactly one step, not zero.
        self.assertGreater(sum_scaling_hsp_pct([_DAWNCORE_SR]), 0.0)
        self.assertAlmostEqual(sum_scaling_hsp_pct([_DAWNCORE_SR]), 0.02, places=12)

    def test_the_champion_innate_baseline_is_not_added_in(self) -> None:
        # If the innate 100% were added, 6621 alone would read 200% -> 2 steps
        # -> 0.04. It reads 0.02, so the baseline is excluded.
        self.assertNotAlmostEqual(sum_scaling_hsp_pct([_DAWNCORE_SR]), 0.04, places=6)


class NoScalingItemNoOpTests(unittest.TestCase):
    """Exact no-op when the inventory carries no ARMED scaling item."""

    def test_flat_hsp_only_build_is_zero(self) -> None:
        self.assertAlmostEqual(
            sum_scaling_hsp_pct([_REDEMPTION, _MIKAEL, "3504"]), 0.0, places=12
        )

    def test_armed_seam_equals_off_seam_without_a_scaling_item(self) -> None:
        build = [_REDEMPTION, _MIKAEL, "3114", "6616"]
        self.assertEqual(
            sum_wielder_hsp_pct(build),
            sum_wielder_hsp_pct(build, assume_scaling_hsp_grants=True),
        )

    def test_regen_without_an_armed_item_earns_nothing(self) -> None:
        """Base mana regen alone is inert - the grant clause is what pays."""
        self.assertAlmostEqual(
            sum_scaling_hsp_pct([_REDEMPTION, "3222", "3504", "6616"]),
            0.0,
            places=12,
        )


class HspConsumerExclusionTests(unittest.TestCase):
    """Sword of Blossoming Dawn READS HSP - it must never GRANT it."""

    def test_all_three_sword_ids_contribute_exactly_zero(self) -> None:
        for iid in _SWORD_BLOSSOMING_DAWN:
            with self.subTest(item_id=iid):
                self.assertEqual(sum_scaling_hsp_pct([iid]), 0.0)
                self.assertNotIn(iid, SCALING_HSP_PER_MANA_REGEN_STEP)
                self.assertIn(iid, KNOWN_EXCLUDED_SCALING_HSP_IDS)

    def test_sword_does_not_perturb_an_armed_dawncore_build(self) -> None:
        alone = sum_scaling_hsp_pct([_DAWNCORE_SR])
        with_sword = sum_scaling_hsp_pct([_DAWNCORE_SR, "4011"])
        self.assertAlmostEqual(alone, with_sword, places=12)

    def test_puppeteer_is_a_consumer_too(self) -> None:
        """447123 pays attack speed FROM your HSP - same direction as the Sword."""
        self.assertEqual(sum_scaling_hsp_pct([_PUPPETEER]), 0.0)
        self.assertIn(_PUPPETEER, KNOWN_EXCLUDED_SCALING_HSP_IDS)

    def test_the_shipped_prose_confirms_the_consumer_direction(self) -> None:
        meraki = _meraki_items()
        for iid in ("4011", _PUPPETEER):
            with self.subTest(item_id=iid):
                prose = " ".join(
                    (p.get("effects") or "")
                    for p in (meraki[iid].get("passives") or [])
                ).lower()
                self.assertIn("heal and shield power", prose)
                self.assertIn("attack speed", prose)


class EleisasMiracleKnownExcludedTests(unittest.TestCase):
    """443063 scales on MISSING CURRENT HEALTH - live target state, not inventory."""

    def test_eleisas_miracle_contributes_zero_and_is_registered_excluded(self) -> None:
        self.assertEqual(sum_scaling_hsp_pct([_ELEISAS_MIRACLE]), 0.0)
        self.assertNotIn(_ELEISAS_MIRACLE, SCALING_HSP_PER_MANA_REGEN_STEP)
        self.assertIn(_ELEISAS_MIRACLE, KNOWN_EXCLUDED_SCALING_HSP_IDS)

    def test_the_exclusion_reason_is_recorded_not_merely_omitted(self) -> None:
        reason = KNOWN_EXCLUDED_SCALING_HSP_IDS[_ELEISAS_MIRACLE]
        self.assertTrue(reason.strip())
        self.assertIn("health", reason.lower())

    def test_the_shipped_prose_still_says_missing_health(self) -> None:
        prose = " ".join(
            (p.get("effects") or "")
            for p in (_meraki_items()[_ELEISAS_MIRACLE].get("passives") or [])
        ).lower()
        self.assertIn("heal and shield power", prose)
        self.assertIn("missing", prose)


class BonusManaAxisRefuteTests(unittest.TestCase):
    """REFUTE: bonus mana is NOT derivable from an item-id list at this seam.

    ``_item_mana_health`` already settled the doctrine for the same quantity -
    its Awe lane takes ``bonus_mana`` as a CALLER-SUPPLIED argument computed
    from the resolved stat block, because item-printed ``FlatMPPoolMod`` is only
    a floor: it omits Tear-family stacked mana, the Manaflow Band rune, and
    Whispering Circlet's own up-to-360 Manaflow charges.
    ``sum_wielder_hsp_pct`` receives ONLY item ids, so the quantity is
    unreachable here. Shipping a number would be a fabrication.
    """

    def test_whispering_and_diadem_contribute_zero(self) -> None:
        for iid in _WHISPERING_CIRCLET + _DIADEM_OF_SONGS:
            with self.subTest(item_id=iid):
                self.assertEqual(sum_scaling_hsp_pct([iid]), 0.0)
                self.assertNotIn(iid, SCALING_HSP_PER_MANA_REGEN_STEP)
                self.assertIn(iid, KNOWN_EXCLUDED_SCALING_HSP_IDS)

    def test_the_refutation_reason_names_bonus_mana(self) -> None:
        for iid in _WHISPERING_CIRCLET + _DIADEM_OF_SONGS:
            with self.subTest(item_id=iid):
                self.assertIn(
                    "bonus mana", KNOWN_EXCLUDED_SCALING_HSP_IDS[iid].lower()
                )

    def test_both_diadem_mirrors_exist_in_the_shipped_index(self) -> None:
        """The orchestrator asked which Diadem mirrors exist - both do."""
        dd = _ddragon_items()
        for iid in _DIADEM_OF_SONGS:
            with self.subTest(item_id=iid):
                self.assertIn(iid, dd)
                self.assertEqual(dd[iid]["name"], "Diadem of Songs")

    def test_the_shipped_prose_still_says_bonus_mana(self) -> None:
        meraki = _meraki_items()
        for iid in ("2526", "2530"):
            with self.subTest(item_id=iid):
                prose = " ".join(
                    (p.get("effects") or "")
                    for p in (meraki[iid].get("passives") or [])
                ).lower()
                self.assertIn("heal and shield power", prose)
                self.assertIn("mana", prose)


class BaseManaRegenTableTests(unittest.TestCase):
    """The regen table is parsed from the PRINTED stats block only."""

    def test_table_is_non_empty_and_keyed_by_id_string(self) -> None:
        table = load_base_mana_regen_pct_table()
        self.assertGreater(len(table), 10)
        for key in table:
            self.assertIsInstance(key, str)

    def test_every_entry_matches_the_shipped_stats_block(self) -> None:
        table = load_base_mana_regen_pct_table()
        dd = _ddragon_items()
        for iid, pct in sorted(table.items(), key=lambda kv: int(kv[0])):
            with self.subTest(item_id=iid):
                block = _STATS_BLOCK.search(dd[iid].get("description") or "")
                self.assertIsNotNone(block)
                found = _BMR_LINE.findall(_plain(block.group(1)))
                self.assertEqual([float(f) for f in found], [pct])

    def test_dawncore_passive_text_does_not_double_count_its_own_regen(self) -> None:
        """The trap: "per 100% Base Mana Regen" also matches the naive regex.

        6621's raw description carries TWO "% Base Mana Regen" hits - the
        printed 100% stat line AND the passive clause. Scoping to <stats> is
        what keeps the Arena mirror at 200 rather than 300.
        """
        dd = _ddragon_items()
        table = load_base_mana_regen_pct_table()
        for iid, printed in (
            (_DAWNCORE_SR, 100.0),
            (_DAWNCORE_ARENA, 200.0),
            (_DAWNCORE_ARAM, 150.0),
        ):
            with self.subTest(item_id=iid):
                whole = _BMR_LINE.findall(_plain(dd[iid].get("description") or ""))
                self.assertEqual(len(whole), 2)
                self.assertAlmostEqual(table[iid], printed, places=6)

    def test_table_is_cached_across_calls(self) -> None:
        self.assertIs(load_base_mana_regen_pct_table(), load_base_mana_regen_pct_table())

    def test_items_without_a_regen_line_are_absent(self) -> None:
        for iid in ("3053", "6673", _ELEISAS_MIRACLE):
            with self.subTest(item_id=iid):
                self.assertNotIn(iid, load_base_mana_regen_pct_table())


class FailSoftTests(unittest.TestCase):
    """Empty / None / junk inputs return 0.0, never raise."""

    def test_empty_and_none(self) -> None:
        self.assertEqual(sum_scaling_hsp_pct([]), 0.0)
        self.assertEqual(sum_scaling_hsp_pct(None), 0.0)
        self.assertEqual(sum_scaling_hsp_pct(()), 0.0)

    def test_non_iterable(self) -> None:
        self.assertEqual(sum_scaling_hsp_pct(12345), 0.0)
        self.assertEqual(sum_scaling_hsp_pct(object()), 0.0)

    def test_none_and_blank_entries_are_skipped(self) -> None:
        self.assertAlmostEqual(
            sum_scaling_hsp_pct([None, "", _DAWNCORE_SR, None]), 0.02, places=12
        )

    def test_unknown_ids(self) -> None:
        self.assertEqual(sum_scaling_hsp_pct(["9999999", "-1", "abc"]), 0.0)

    def test_missing_patch_snapshot_is_fail_soft(self) -> None:
        self.assertEqual(
            sum_scaling_hsp_pct([_DAWNCORE_SR], patch="0.0.0-does-not-exist"), 0.0
        )
        self.assertEqual(
            load_base_mana_regen_pct_table(patch="0.0.0-does-not-exist"), {}
        )

    def test_the_seam_is_fail_soft_when_armed(self) -> None:
        self.assertEqual(
            sum_wielder_hsp_pct(None, assume_scaling_hsp_grants=True), 0.0
        )
        self.assertEqual(
            sum_wielder_hsp_pct([], assume_scaling_hsp_grants=True), 0.0
        )


class ScalingHspClassCompletenessTests(unittest.TestCase):
    """Machine-check the class enumeration against the shipped prose.

    A CANDIDATE is any item whose HSP mention lives OUTSIDE the printed stat
    line - the DDragon passive body (stats block removed) or the Meraki
    ``passives[].effects`` prose. No attempt is made to auto-classify grant vs
    consume: the assertion is that every candidate is either ARMED or recorded
    as KNOWN-EXCLUDED with a reason, so a new patch item fails the suite until a
    human classifies it.
    """

    def _candidates(self) -> set:
        found = set()
        for iid, entry in _ddragon_items().items():
            if _HSP_PHRASE.search(_passive_body(entry.get("description") or "")):
                found.add(str(iid))
        for iid, entry in _meraki_items().items():
            prose = " ".join(
                (p.get("effects") or "") for p in (entry.get("passives") or [])
            )
            if _HSP_PHRASE.search(prose):
                found.add(str(iid))
        return found

    def test_registry_and_excluded_are_disjoint(self) -> None:
        self.assertEqual(
            set(SCALING_HSP_PER_MANA_REGEN_STEP)
            & set(KNOWN_EXCLUDED_SCALING_HSP_IDS),
            set(),
        )

    def test_class_ids_is_the_union_of_the_two_sets(self) -> None:
        self.assertEqual(
            set(SCALING_HSP_CLASS_IDS),
            set(SCALING_HSP_PER_MANA_REGEN_STEP)
            | set(KNOWN_EXCLUDED_SCALING_HSP_IDS),
        )

    def test_every_prose_candidate_is_accounted_for(self) -> None:
        candidates = self._candidates()
        self.assertTrue(candidates)
        unaccounted = candidates - set(SCALING_HSP_CLASS_IDS)
        self.assertEqual(
            unaccounted,
            set(),
            "Unclassified scaling-HSP prose candidates: "
            + repr(sorted(unaccounted)),
        )

    def test_no_registered_id_is_a_phantom(self) -> None:
        """Every id the module names must exist in the shipped item index."""
        dd = _ddragon_items()
        for iid in sorted(SCALING_HSP_CLASS_IDS, key=int):
            with self.subTest(item_id=iid):
                self.assertIn(iid, dd)

    def test_the_class_is_not_wider_than_the_prose_evidence(self) -> None:
        stale = set(SCALING_HSP_CLASS_IDS) - self._candidates()
        self.assertEqual(
            stale, set(), "Class rows with no prose evidence: " + repr(sorted(stale))
        )

    def test_every_excluded_row_carries_a_non_empty_reason(self) -> None:
        for iid, reason in KNOWN_EXCLUDED_SCALING_HSP_IDS.items():
            with self.subTest(item_id=iid):
                self.assertTrue(str(reason).strip())

    def test_every_armed_magnitude_matches_the_shipped_ddragon_clause(self) -> None:
        """No invented coefficients - re-read the per-step percent from prose."""
        dd = _ddragon_items()
        clause = re.compile(
            r"Gain\s*\+?\s*(\d+(?:\.\d+)?)\s*%\s*Heal and Shield Power",
            re.IGNORECASE,
        )
        for iid, rate in SCALING_HSP_PER_MANA_REGEN_STEP.items():
            with self.subTest(item_id=iid):
                body = _passive_body(dd[iid].get("description") or "")
                match = clause.search(body)
                self.assertIsNotNone(match)
                self.assertAlmostEqual(float(match.group(1)) / 100.0, rate, places=9)
                self.assertIn("base mana regen", body.lower())


if __name__ == "__main__":
    unittest.main()
