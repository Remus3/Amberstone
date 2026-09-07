"""tools/champion_loadout_cleanup_pollution_item213.py

Item 213 (2026-05-28) - comprehensive loadout-data pollution cleanup.

Operator ask: "search and correct item/rune/summoner spell pollution for
ALL champions, rebuild as necessary to provide the 2-3+ item build paths
for all modes".

``data/champion_loadouts.json`` accumulated four classes of pollution
across its collapsed ``sr-collapsed`` / ``aram-collapsed`` /
``arena-collapsed`` variants:

  1. NON-PURCHASABLE / OFF-MODE / JOKE items leaked into build_paths.
     The dominant offender is "Golden Spatula" (the ARAM anvil id 994403
     + the Arena prismatic anvil tokens "The Golden Spatula"), plus the
     Arena "Stat Bonus" / "Legendary <class> Item" placeholder tokens
     and "Juice of *" consumables, plus a handful of SR-only items
     (Mejai's / Bastionbreaker / Goredrinker / ...) that bled into ARAM
     paths.
  2. DUPLICATE + REDUNDANT build_paths - the ``auto-<mode>-primary-*`` /
     ``auto-<mode>-secondary-*`` seed paths that duplicate the curated
     named paths (order-insensitive item-list equality).
  3. MISLABELED paths whose label / archetype no longer matches their
     item identity (lighter touch: relabel by detected identity).
  4. RUNE / SUMMONER mismatches (spot fixes: SR carry Flash+Barrier
     [4,21] per item 169; ARAM Flash+Mark [4,32]; Arena Flash+Heal
     [4,7]; with the support-duo / Senna / Kalista / Yuumi Flash+Heal
     keep-list on SR).

Plus a 5th, test-pinned fix carried from the item-213 ALPHA marksman
work: ranged ADCs must not carry off-class melee items
(Plated Steelcaps / Trinity Force / Bastionbreaker / Sundered Sky /
Umbral Glaive) in their SR + ARAM PRIMARY path. We promote the first
melee-free sibling path to primary and strip the off-class melee items
from the remaining ranged-ADC paths.

Purchasability is authoritative from the DS item catalog
``data/daemon_slayer/<patch>/items.json`` ``maps`` flags (map 11 = SR,
12 = ARAM, 30 = Arena). The DDragon ``gold.purchasable`` flag is
unreliable for many real items (boots-tier bases report ``false``) so
we use ``maps`` only and never combine it with ``purchasable``.

After stripping, any path that drops below 4 items is back-filled
deterministically + offline from a per-archetype legendary pool keyed
off items already present in the same mode (so builds stay coherent and
clash-free) - we do NOT call the live DS engine.

Usage::

    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/champion_loadout_cleanup_pollution_item213.py [--dry-run]
        [--no-backup]

Atomic write (tmp.write_text + tmp.replace; ensure_ascii=True). Idempotent.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_LOADOUTS_PATH = _ROOT / "data" / "champion_loadouts.json"
_CURRENT_PATCH = (_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
    encoding="utf-8"
).strip() or "16.11.1"
_ITEMS_PATH = _ROOT / "data" / "daemon_slayer" / _CURRENT_PATCH / "items.json"
_CHAMPS_PATH = (
    _ROOT / "data" / "daemon_slayer" / _CURRENT_PATCH / "champions.json"
)

_MAP_FOR_MODE = {"sr": "11", "aram": "12", "arena": "30"}

# Item 208 carry (2026-06-10): the original pass stripped off-class melee
# only on SR/ARAM via the Marksman-tag >= 525 set, and the Arena carry
# backfill pool itself seeded Trinity Force + Heartsteel - so a re-run
# would re-pollute the ranged-ADC carry rows the item-208 backfill
# recovered. Carry rows are now gated by the same range-keyed mechanic
# as the live scorer (core.daemon_slayer_client carry branch) so the
# layers cannot disagree. Bruiser/assassin rows of ranged champs keep
# melee items - they are archetype-legitimate there.
from core.daemon_slayer_client import (  # noqa: E402
    CARRY_RANGED_ATTACKRANGE_FLOOR,
    CARRY_RANGED_OFFCLASS_ITEM_NAMES,
    champion_attackrange,
)

# Item s8 (2026-06-10): operator-set exact build lengths (SR 7 / ARAM 6
# / Arena 6). Single source shared with the producers + the sweep guard.
from tools.champion_loadout_invariants import TARGET_LEN  # noqa: E402

# Operator-pinned carry rows the item-208 gate must skip - hand-fixes
# are not generated pollution. Corki's SR "ad" path keeps Trinity Force
# by the item-269 hand-fix (tools/hotfix_sibling_pollution_item269
# _CORKI; Sheen rides Corki's magic-damage passive) and that state is
# test-pinned. The item-208 guard test + backfill tool carry the same
# exemption.
ITEM208_OPERATOR_PINNED_CARRY_ROWS: frozenset = frozenset({
    ("Corki", "sr-collapsed", "ad"),
})

# Joke / anvil / placeholder item NAMES - never a coachable build item.
_JOKE_NAMES = {
    "golden spatula",
    "the golden spatula",
    "stat bonus",
    "legendary fighter item",
    "legendary marksman item",
    "legendary assassin item",
    "legendary mage item",
    "legendary tank item",
    "legendary enchanter item",
    "juice of power",
    "juice of vitality",
    "juice of haste",
}

# Off-class melee / tank items stripped from ranged-ADC SR + ARAM paths.
_OFFCLASS_MELEE = {
    "plated steelcaps",
    "trinity force",
    "bastionbreaker",
    "sundered sky",
    "umbral glaive",
}

# Boots display names that resolve to core.build_order._BOOTS_IDS.
# Kept in lock-step with tests/test_champion_loadouts_meta_conformance.py.
_BOOTS_NAMES = (
    "Berserker's Greaves",
    "Boots of Swiftness",
    "Plated Steelcaps",
    "Mercury's Treads",
    "Sorcerer's Shoes",
    "Ionian Boots of Lucidity",
    "Mobility Boots",
    "Symbiotic Soles",
    "Synchronized Souls",
    "Slightly Magical Footwear",
)
_BOOTS_NORM = frozenset(n.strip().lower() for n in _BOOTS_NAMES)
_BOOTSLESS_CHAMPS = frozenset({"Yuumi", "Cassiopeia"})

# Default boots per archetype for SR/ARAM (item 166 boots-injection rule).
_DEFAULT_BOOTS = {
    "carry": "Berserker's Greaves",
    "mage": "Sorcerer's Shoes",
    "bruiser": "Plated Steelcaps",
    "tank": "Mercury's Treads",
    "enchanter": "Mercury's Treads",
    "assassin": "Sorcerer's Shoes",
}

# SR carry summoner default Flash+Barrier [4,21] (item 169), except the
# support-duo / sustain marksmen keep Flash+Heal [4,7].
_SR_CARRY_SUMMS = [4, 21]
_SR_HEAL_KEEP = {"Senna", "Kalista", "Yuumi"}
_ARAM_SUMMS = [4, 32]
_ARENA_SUMMS = [4, 7]

# Per-archetype clean backfill pools (item NAME strings). Originally
# used only when a path dropped below 4 items after stripping; the
# item-s8 length rule (TARGET_LEN: SR 7 / ARAM 6 / Arena 6, see
# tools/champion_loadout_invariants.py) refills every short row to its
# exact mode target, so the pools were deepened (item s8, 2026-06-10) -
# a 6-item row that already holds most of a shallow pool must still be
# able to reach target without a unique-family clash. Entries are
# appended in order, skipping anything already present, off-mode, or
# that would create a unique-passive clash. The pools are curated from
# items already heavily used in each mode so backfills stay coherent.
# SR/ARAM gained assassin pools (lethality) - assassin rows previously
# fell through to the carry pool and could pick up crit items.
_BACKFILL_SR = {
    "carry": [
        "Infinity Edge",
        "Lord Dominik's Regards",
        "Runaan's Hurricane",
        "Yun Tal Wildarrows",
        "Bloodthirster",
        "Phantom Dancer",
        "The Collector",
        "Rapid Firecannon",
        "Mortal Reminder",
        "Navori Flickerblade",
        "Stormrazor",
        "Wit's End",
    ],
    "mage": [
        "Rabadon's Deathcap",
        "Void Staff",
        "Shadowflame",
        "Zhonya's Hourglass",
        "Stormsurge",
        "Horizon Focus",
        "Cryptbloom",
        "Rylai's Crystal Scepter",
        "Morellonomicon",
        "Banshee's Veil",
        "Cosmic Drive",
    ],
    "bruiser": [
        "Sterak's Gage",
        "Death's Dance",
        "Spear of Shojin",
        "Black Cleaver",
        "Maw of Malmortius",
        "Hullbreaker",
        "Titanic Hydra",
        "Experimental Hexplate",
        "Ravenous Hydra",
        "Guardian Angel",
    ],
    "tank": [
        "Sunfire Aegis",
        "Thornmail",
        "Spirit Visage",
        "Kaenic Rookern",
        "Dead Man's Plate",
        "Randuin's Omen",
        "Jak'Sho, The Protean",
        "Unending Despair",
        "Frozen Heart",
        "Force of Nature",
    ],
    "enchanter": [
        "Ardent Censer",
        "Staff of Flowing Water",
        "Redemption",
        "Moonstone Renewer",
        "Echoes of Helia",
        "Dawncore",
        "Mikael's Blessing",
        "Imperial Mandate",
        "Shurelya's Battlesong",
        "Locket of the Iron Solari",
    ],
    "assassin": [
        "Youmuu's Ghostblade",
        "Edge of Night",
        "Serylda's Grudge",
        "Opportunity",
        "Axiom Arc",
        "Hubris",
        "Profane Hydra",
        "Serpent's Fang",
        "Voltaic Cyclosword",
        "Black Cleaver",
    ],
}
_BACKFILL_ARAM = {
    "carry": [
        "Infinity Edge",
        "Lord Dominik's Regards",
        "Runaan's Hurricane",
        "Yun Tal Wildarrows",
        "Bloodthirster",
        "Phantom Dancer",
        "The Collector",
        "Rapid Firecannon",
        "Mortal Reminder",
        "Navori Flickerblade",
        "Stormrazor",
        "Wit's End",
    ],
    "mage": [
        "Rabadon's Deathcap",
        "Void Staff",
        "Shadowflame",
        "Zhonya's Hourglass",
        "Cosmic Drive",
        "Horizon Focus",
        "Cryptbloom",
        "Rylai's Crystal Scepter",
        "Morellonomicon",
        "Banshee's Veil",
        "Stormsurge",
    ],
    "bruiser": [
        "Sterak's Gage",
        "Death's Dance",
        "Spear of Shojin",
        "Black Cleaver",
        "Maw of Malmortius",
        "Hullbreaker",
        "Titanic Hydra",
        "Experimental Hexplate",
        "Ravenous Hydra",
    ],
    "tank": [
        "Sunfire Aegis",
        "Thornmail",
        "Spirit Visage",
        "Kaenic Rookern",
        "Dead Man's Plate",
        "Randuin's Omen",
        "Jak'Sho, The Protean",
        "Unending Despair",
        "Frozen Heart",
        "Force of Nature",
    ],
    "enchanter": [
        "Ardent Censer",
        "Staff of Flowing Water",
        "Redemption",
        "Moonstone Renewer",
        "Echoes of Helia",
        "Dawncore",
        "Mikael's Blessing",
        "Imperial Mandate",
        "Shurelya's Battlesong",
        "Locket of the Iron Solari",
    ],
    "assassin": [
        "Youmuu's Ghostblade",
        "Edge of Night",
        "Serylda's Grudge",
        "Opportunity",
        "Axiom Arc",
        "Hubris",
        "Profane Hydra",
        "Serpent's Fang",
        "Voltaic Cyclosword",
        "Black Cleaver",
    ],
}
# Arena legendaries (map 30 names) per archetype - real meta picks.
_BACKFILL_ARENA = {
    "carry": [
        "Trinity Force",
        "Heartsteel",
        "Statikk Shiv",
        "Hamstringer",
        "Kraken Slayer",
        "Essence Reaver",
        "Infinity Edge",
        "Lord Dominik's Regards",
        "Phantom Dancer",
        "Runaan's Hurricane",
        "The Collector",
        "Rapid Firecannon",
        "Navori Flickerblades",
        "Bloodthirster",
    ],
    "mage": [
        "Wooglet's Witchcap",
        "Innervating Locket",
        "Demonic Embrace",
        "Everfrost",
        "Lich Bane",
        "Twilight's Edge",
        "Rabadon's Deathcap",
        "Void Staff",
        "Shadowflame",
        "Luden's Echo",
        "Horizon Focus",
        "Stormsurge",
        "Cryptbloom",
        "Rylai's Crystal Scepter",
    ],
    "bruiser": [
        "Void Immolation",
        "Heartsteel",
        "Hamstringer",
        "Divine Sunderer",
        "Warmog's Armor",
        "Black Cleaver",
        "Sterak's Gage",
        "Death's Dance",
        "Sundered Sky",
        "Spear of Shojin",
        "Overlord's Bloodmail",
        "Titanic Hydra",
        "Experimental Hexplate",
        "Maw of Malmortius",
    ],
    "assassin": [
        "Divine Sunderer",
        "Sundered Sky",
        "Twilight's Edge",
        "Galeforce",
        "Hamstringer",
        "Eclipse",
        "Duskblade of Draktharr",
        "Edge of Night",
        "Youmuu's Ghostblade",
        "Prowler's Claw",
        "Profane Hydra",
        "Opportunity",
        "Serpent's Fang",
        "The Collector",
    ],
    "tank": [
        "Void Immolation",
        "Warmog's Armor",
        "Shield of Molten Stone",
        "Heartsteel",
        "Jak'Sho, The Protean",
        "Sunfire Aegis",
        "Thornmail",
        "Kaenic Rookern",
        "Dead Man's Plate",
        "Randuin's Omen",
        "Gargoyle Stoneplate",
        "Force of Nature",
        "Spirit Visage",
        "Unending Despair",
        "Hollow Radiance",
    ],
    "enchanter": [
        "Ardent Censer",
        "Redemption",
        "Mikael's Blessing",
        "Imperial Mandate",
        "Staff of Flowing Water",
        "Moonstone Renewer",
        "Echoes of Helia",
        "Dawncore",
        "Shurelya's Battlesong",
        "Locket of the Iron Solari",
        "Knight's Vow",
    ],
}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _load_item_index() -> dict[str, list[dict]]:
    data = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))["data"]
    idx: dict[str, list[dict]] = {}
    for _iid, it in data.items():
        idx.setdefault(_norm(it.get("name", "")), []).append(it)
    return idx


def _name_to_family() -> dict[str, str]:
    from agents.daemon_slayer._effects_data import ITEM_EFFECTS

    out: dict[str, str] = {}
    for _iid, eff in ITEM_EFFECTS.items():
        upk = getattr(eff, "unique_passive_key", None)
        nm = getattr(eff, "name", None)
        if upk and nm:
            out[
                _norm(nm).replace(" ", "").replace("'", "").replace("-", "")
            ] = upk
    return out


def _fam_norm(s: str) -> str:
    return _norm(s).replace(" ", "").replace("'", "").replace("-", "")


def _ranged_marksmen() -> set[str]:
    data = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))["data"]
    out: set[str] = set()
    for _k, c in data.items():
        rng = (c.get("stats") or {}).get("attackrange", 0)
        if "Marksman" in (c.get("tags") or []) and rng >= 525:
            out.add(c.get("name", ""))
    return out


def _on_map(item_idx: dict[str, list[dict]], name: str, mode: str) -> bool:
    """True if any item id for ``name`` is purchasable on ``mode``'s map."""
    mid = _MAP_FOR_MODE[mode]
    recs = item_idx.get(_norm(name), [])
    if not recs:
        # try casing fixes for "the"/"The"
        for alt in (
            _norm(name).replace(" the ", " the "),
            _norm(name),
        ):
            recs = item_idx.get(alt, [])
            if recs:
                break
    return any((it.get("maps") or {}).get(mid) for it in recs)


class Cleaner:
    def __init__(self) -> None:
        self.item_idx = _load_item_index()
        self.fam = _name_to_family()
        self.ranged_mm = _ranged_marksmen()
        # stats
        self.stripped: dict[str, int] = {}
        self.dups_removed = 0
        self.gs_before = 0
        self.gs_after = 0
        self.paths_before = 0
        self.paths_after = 0
        self.backfilled = 0
        self.rune_summ_fixes: list[str] = []
        self.primary_promotions: list[str] = []

    def _is_polluted(self, name: str, mode: str) -> bool:
        n = _norm(name)
        if n in _JOKE_NAMES or "spatula" in n:
            return True
        # off-mode: not on this mode's map AND it resolves to a known item
        if mode in ("sr", "aram") and self.item_idx.get(n):
            if not _on_map(self.item_idx, name, mode):
                return True
        return False

    def _families_in(self, items: list[str]) -> set[str]:
        out: set[str] = set()
        for it in items:
            f = self.fam.get(_fam_norm(it))
            if f:
                out.add(f)
        return out

    def _dedupe_unique_families(self, items: list[str]) -> list[str]:
        """Drop the second + later items that share a unique-passive
        family with an earlier item (engine-authoritative no-double-
        unique rule, e.g. Trinity Force + Essence Reaver = spellblade).

        Mirrors ``tools/champion_loadout_align._dedupe_items`` and uses
        the same family registry. First occurrence wins so the higher-
        ranked engine pick survives. Items with no family pass through.
        """
        out: list[str] = []
        seen_fams: set[str] = set()
        for it in items:
            f = self.fam.get(_fam_norm(it))
            if f and f in seen_fams:
                continue
            if f:
                seen_fams.add(f)
            out.append(it)
        return out

    def _backfill(
        self, items: list[str], mode: str, archetype: str,
        skip_names: frozenset = frozenset(),
        target: int | None = None,
    ) -> list[str]:
        """Append archetype-appropriate items until len>=target, offline.

        ``target`` defaults to the operator-set per-mode build length
        (item s8: SR 7 / ARAM 6 / Arena 6)."""
        if target is None:
            target = TARGET_LEN[mode]
        pool_map = {
            "sr": _BACKFILL_SR,
            "aram": _BACKFILL_ARAM,
            "arena": _BACKFILL_ARENA,
        }[mode]
        pool = pool_map.get(archetype) or pool_map.get("carry") or []
        have = {_norm(i) for i in items}
        fams = self._families_in(items)
        for cand in pool:
            if len(items) >= target:
                break
            if cand in skip_names:
                continue
            cn = _norm(cand)
            if cn in have:
                continue
            if mode in ("sr", "aram") and not _on_map(
                self.item_idx, cand, mode
            ):
                continue
            if mode == "arena" and not _on_map(self.item_idx, cand, mode):
                continue
            f = self.fam.get(_fam_norm(cand))
            if f and f in fams:
                continue
            items.append(cand)
            have.add(cn)
            if f:
                fams.add(f)
            self.backfilled += 1
        return items

    @staticmethod
    def _detect_archetype(bp: dict, mode: str) -> str:
        """Best-effort archetype for backfill pool selection."""
        a = (bp.get("_archetype") or "").strip().lower()
        if a:
            # normalize to pool keys
            if "tank" in a:
                return "tank"
            if "bruiser" in a or "fighter" in a:
                return "bruiser"
            if "mage" in a or "burst" in a or "ap" in a:
                return "mage"
            if "enchant" in a or "support" in a:
                return "enchanter"
            if "assassin" in a:
                # Item s8: SR/ARAM gained lethality pools, so assassin
                # rows no longer fall back to the carry (crit) pool.
                return "assassin"
            return "carry"
        key = (bp.get("key") or "").lower()
        for token, arch in (
            ("tank", "tank"),
            ("bruiser", "bruiser"),
            ("fighter", "bruiser"),
            ("enchanter", "enchanter"),
            ("assassin", "assassin"),
            ("mage", "mage"),
            ("ap", "mage"),
            ("burst", "mage"),
        ):
            if token in key:
                return arch
        return "carry"

    def _strip_path_items(
        self, items: list[str], mode: str, ranged: bool
    ) -> list[str]:
        out: list[str] = []
        for it in items:
            if "spatula" in _norm(it):
                if mode in ("sr", "aram"):
                    self.gs_before += 1
            if self._is_polluted(it, mode):
                self.stripped[it.strip()] = self.stripped.get(
                    it.strip(), 0
                ) + 1
                continue
            if (
                ranged
                and mode in ("sr", "aram")
                and _norm(it) in _OFFCLASS_MELEE
            ):
                self.stripped[it.strip()] = self.stripped.get(
                    it.strip(), 0
                ) + 1
                continue
            out.append(it)
        return out

    def _reseat_boots(
        self, champ: str, mode: str, items: list[str], archetype: str
    ) -> list[str]:
        """SR/ARAM non-bootsless paths: exactly one boots item at index 1.

        Arena + bootsless champs get all boots removed. Mirrors the
        item-166 boots-injection rule + core.build_order._select_boots
        post-engine_call_i==1 placement.
        """
        boots = [i for i in items if _norm(i) in _BOOTS_NORM]
        non_boots = [i for i in items if _norm(i) not in _BOOTS_NORM]

        if mode == "arena" or champ in _BOOTSLESS_CHAMPS:
            return non_boots

        # pick the single boots to keep (first present, else archetype default)
        if boots:
            keep = boots[0]
        else:
            keep = _DEFAULT_BOOTS.get(archetype, "Berserker's Greaves")

        if not non_boots:
            # degenerate; keep boots first so list is non-empty
            return [keep]
        # core item at index 0, boots at index 1, rest after
        return [non_boots[0], keep] + non_boots[1:]

    def enforce_length(
        self, champ: str, mode: str, archetype: str, items: list[str],
        skip_names: frozenset = frozenset(),
    ) -> list[str]:
        """Item s8 - shape one row to the canonical per-mode form:
        unique-family duplicates dropped (no-double-unique rule),
        boots reseated (index 1 on SR/ARAM, none on Arena/bootsless),
        refilled from the archetype pool to the exact mode target, then
        tail-trimmed to target. Shared by the autogen producer and the
        item-s8 sweep so generation and repair cannot disagree.

        The unique-family dedup is FIRST so a clashing pair the DS flat
        ranker emitted (Trinity Force + Essence Reaver, both spellblade)
        is collapsed before reseat/backfill - otherwise an autogen run
        wrote the clash straight into the curated JSON and broke the
        no-unique-clash drift guard. align dedupes upstream already; the
        sweep relies on this step for the same guarantee."""
        items = self._dedupe_unique_families(list(items))
        items = self._reseat_boots(champ, mode, items, archetype)
        if len(items) < TARGET_LEN[mode]:
            items = self._backfill(
                items, mode, archetype, skip_names=skip_names,
            )
        if len(items) > TARGET_LEN[mode]:
            items = items[:TARGET_LEN[mode]]
        return items

    def _fix_summoners(
        self, champ: str, mode: str, bp: dict
    ) -> None:
        summ = bp.get("summoners")
        if mode == "aram":
            want = _ARAM_SUMMS
        elif mode == "arena":
            want = _ARENA_SUMMS
        else:  # sr - only fix carry-ish paths; keep heal for sustain duo
            arch = self._detect_archetype(bp, mode)
            if arch in ("enchanter", "tank", "bruiser"):
                return
            if champ in _SR_HEAL_KEEP:
                return
            # only correct the clear Flash+Heal -> Flash+Barrier carry case
            if summ == [4, 7]:
                want = _SR_CARRY_SUMMS
            else:
                return
        if summ is not None and list(summ) != want:
            bp["summoners"] = list(want)
            self.rune_summ_fixes.append(
                f"{champ}|{mode}|{bp.get('key')}: summoners {summ} -> {want}"
            )

    def clean_variant(
        self, champ: str, vk: str, mode: str, v: dict
    ) -> None:
        ranged = champ in self.ranged_mm
        bps = v.get("build_paths") or []
        self.paths_before += len(bps)

        kept: list[dict] = []
        seen: dict[frozenset, str] = {}
        for bp in bps:
            items = list(bp.get("items") or [])
            items = self._strip_path_items(items, mode, ranged)
            if not items:
                continue
            arch = self._detect_archetype(bp, mode)
            # Item 208 carry: range-gate carry rows on every mode (the
            # sr/aram strip above is path-archetype-blind and skips arena
            # by design) and keep the backfill pool from re-seeding the
            # same four polluters.
            gate_carry = (
                arch == "carry"
                and (champ, vk, str(bp.get("key") or ""))
                not in ITEM208_OPERATOR_PINNED_CARRY_ROWS
                and champion_attackrange(champ)
                >= CARRY_RANGED_ATTACKRANGE_FLOOR
            )
            if gate_carry:
                items = [
                    i for i in items
                    if i not in CARRY_RANGED_OFFCLASS_ITEM_NAMES
                ]
            # Item s8: enforce the exact per-mode build length (SR 7 /
            # ARAM 6 / Arena 6). Reseat first so boots sit at index 1,
            # then refill to target (appends at the tail, never disturbs
            # the boots slot), then trim overlong rows from the tail.
            items = self._reseat_boots(champ, mode, items, arch)
            if len(items) < TARGET_LEN[mode]:
                items = self._backfill(
                    items, mode, arch,
                    skip_names=(
                        CARRY_RANGED_OFFCLASS_ITEM_NAMES
                        if gate_carry else frozenset()
                    ),
                )
            if len(items) > TARGET_LEN[mode]:
                items = items[:TARGET_LEN[mode]]
            if len(items) < 4:
                # still short (rare): drop it; dedup/backfill below ensures
                # the variant keeps >=2 via sibling paths
                continue
            key = frozenset(_norm(i) for i in items)
            if key in seen:
                self.dups_removed += 1
                continue
            bp["items"] = items
            seen[key] = bp.get("key")
            kept.append(bp)

        # Promote a melee-free path to primary for ranged ADCs (SR/ARAM).
        if ranged and mode in ("sr", "aram") and kept:
            def _clean_primary(bp: dict) -> bool:
                return not any(
                    _norm(i) in _OFFCLASS_MELEE for i in bp.get("items") or []
                )

            if not _clean_primary(kept[0]):
                for i in range(1, len(kept)):
                    if _clean_primary(kept[i]):
                        kept.insert(0, kept.pop(i))
                        self.primary_promotions.append(
                            f"{champ}|{mode}: promoted "
                            f"{kept[0].get('key')!r} to primary"
                        )
                        break

        # Guarantee >=2 paths: if dedup collapsed to 1, clone-diversify
        # by appending one extra coherent item to a copy.
        if len(kept) == 1:
            base = kept[0]
            arch = self._detect_archetype(base, mode)
            alt_items = list(base.get("items"))
            # swap last item for a pool alternative not already present
            pool_map = {
                "sr": _BACKFILL_SR,
                "aram": _BACKFILL_ARAM,
                "arena": _BACKFILL_ARENA,
            }[mode]
            pool = pool_map.get(arch) or pool_map.get("carry") or []
            have = {_norm(i) for i in alt_items}
            fams = self._families_in(alt_items)
            for cand in pool:
                if _norm(cand) in have:
                    continue
                if mode in ("sr", "aram") and not _on_map(
                    self.item_idx, cand, mode
                ):
                    continue
                f = self.fam.get(_fam_norm(cand))
                if f and f in fams:
                    continue
                alt_items = alt_items[:-1] + [cand]
                break
            alt_items = self._reseat_boots(champ, mode, alt_items, arch)
            if frozenset(_norm(i) for i in alt_items) != frozenset(
                _norm(i) for i in base.get("items")
            ):
                alt = {
                    "key": (base.get("key") or "alt") + "-alt",
                    "label": (base.get("label") or "Build") + " (alt)",
                    "items": alt_items,
                    "runes": base.get("runes"),
                    "summoners": base.get("summoners"),
                    "_archetype": base.get("_archetype"),
                    "_source_variant_key": base.get(
                        "_source_variant_key"
                    ),
                }
                kept.append(alt)

        # Reassert primary marker + relabel auto-* keys + fix summoners.
        for i, bp in enumerate(kept):
            bp["_is_primary"] = i == 0
            if i != 0 and "_is_primary" in bp and not bp["_is_primary"]:
                # leave falsey marker off non-primary for compactness
                bp.pop("_is_primary", None)
            self._fix_summoners(champ, mode, bp)

        v["build_paths"] = kept
        # keep variant-level back-compat fields synced to primary
        if kept:
            prim = kept[0]
            v["items"] = list(prim.get("items"))
            if prim.get("runes"):
                v["runes"] = prim["runes"]
            if prim.get("summoners"):
                v["summoners"] = list(prim["summoners"])
        self.paths_after += len(kept)

    def run(self, loadouts: dict) -> dict:
        for cn, c in (loadouts.get("champions") or {}).items():
            for vk, v in (c.get("variants") or {}).items():
                if not v.get("_collapsed"):
                    continue
                mode = (
                    "sr"
                    if "sr" in vk
                    else ("aram" if "aram" in vk else "arena")
                )
                self.clean_variant(cn, vk, mode, v)
        # recount golden spatula after
        for cn, c in (loadouts.get("champions") or {}).items():
            for vk, v in (c.get("variants") or {}).items():
                if not v.get("_collapsed"):
                    continue
                mode = (
                    "sr"
                    if "sr" in vk
                    else ("aram" if "aram" in vk else "arena")
                )
                if mode not in ("sr", "aram"):
                    continue
                for bp in v.get("build_paths") or []:
                    for it in bp.get("items") or []:
                        if "spatula" in _norm(it):
                            self.gs_after += 1
        return loadouts


def _atomic_write(path: Path, obj: Any) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=True) + "\n"
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    import os

    os.close(fd)
    tmp_p = Path(tmp)
    tmp_p.write_text(text, encoding="ascii")
    tmp_p.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    loadouts = json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))
    cleaner = Cleaner()
    cleaned = cleaner.run(loadouts)

    print(f"patch: {_CURRENT_PATCH}")
    print(f"build_paths: {cleaner.paths_before} -> {cleaner.paths_after}")
    print(f"duplicate paths removed: {cleaner.dups_removed}")
    print(
        f"Golden Spatula (SR+ARAM) occurrences: "
        f"{cleaner.gs_before} -> {cleaner.gs_after}"
    )
    print(f"backfill item appends: {cleaner.backfilled}")
    print(f"primary promotions (ranged ADC): {len(cleaner.primary_promotions)}")
    print(f"rune/summoner fixes: {len(cleaner.rune_summ_fixes)}")
    print("stripped items (name -> count):")
    for nm, ct in sorted(
        cleaner.stripped.items(), key=lambda kv: -kv[1]
    ):
        print(f"    {ct:5}  {nm!r}")

    if args.dry_run:
        print("[dry-run] no write")
        return 0

    if not args.no_backup:
        ts = time.strftime("%Y%m%d-%H%M%S")
        bak = _LOADOUTS_PATH.with_suffix(
            f".json.bak-item213-{ts}"
        )
        shutil.copy2(_LOADOUTS_PATH, bak)
        print(f"backup: {bak.name}")

    _atomic_write(_LOADOUTS_PATH, cleaned)
    print("wrote data/champion_loadouts.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
