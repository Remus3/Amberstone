"""Per-champion deterministic scoring coverage - the operator directive "that
same deterministic scoring, per champion, for all champions" generalized from the
single WP-B4 Miss Fortune oracle to the WHOLE 173-champion roster.

For every champion, the C2 scorer (core.build_planner.scoring.score_build) must
rank the champion's OWN-archetype canonical build above an OPPOSITE-damage-type
build. That proves the per-champion kit-synergy model (champ_kit_data) actually
discriminates kit-fit for each champion - not just the ~6 WP-C1 curated champs.

Deterministic + hermetic: pinned canonical item sets (real 16.13.1 item NAMES
resolved to ids against the patch items.json) + the pure score_build (no live
API, no DS engine) + the kit-derived archetype DEFAULT (default_for_champion,
which reads only git-tracked DDragon/DS data). It deliberately does NOT call
get_archetype_for, whose operator champ-select picks live in the gitignored
data/cs_archetype_picks.json - reading those made this non-hermetic (green on a
clean CI checkout, red on a machine where the operator pinned a champ off its
kit axis, e.g. Lulu -> carry). ASCII only - use " - " for a clause break.
"""
from __future__ import annotations

import json
import unittest
from collections import defaultdict
from pathlib import Path

from core.archetype_picks import default_for_champion, kit_damage_axis
from core.build_planner.scoring import score_build

REPO = Path(__file__).resolve().parent.parent
_DS = REPO / "data" / "daemon_slayer"

# Canonical 6-item archetype sets - real 16.13.1 item NAMES, resolved to ids.
_CANON_NAMES = {
    "carry": ["Infinity Edge", "Yun Tal Wildarrows", "Runaan's Hurricane",
              "Lord Dominik's Regards", "Blade of The Ruined King", "The Collector"],
    "mage": ["Rabadon's Deathcap", "Void Staff", "Zhonya's Hourglass",
             "Shadowflame", "Rylai's Crystal Scepter", "Luden's Echo"],
    "tank": ["Sunfire Aegis", "Thornmail", "Randuin's Omen", "Frozen Heart",
             "Warmog's Armor", "Gargoyle Stoneplate"],
    "bruiser": ["Black Cleaver", "Sterak's Gage", "Death's Dance", "Titanic Hydra",
                "Ravenous Hydra", "Trinity Force"],
    "assassin": ["Youmuu's Ghostblade", "Eclipse", "Serylda's Grudge",
                 "Edge of Night", "Duskblade of Draktharr", "Serpent's Fang"],
    "enchanter": ["Ardent Censer", "Moonstone Renewer", "Mikael's Blessing",
                  "Redemption", "Staff of Flowing Water", "Imperial Mandate"],
}

# Opposite damage-type misfit per archetype: AD archetypes are tested against the
# AP mage set; AP/utility archetypes against the AD-crit carry set.
_OPPOSITE = {
    "carry": "mage", "bruiser": "mage", "assassin": "mage",
    "mage": "carry", "enchanter": "carry", "tank": "carry",
}

# Documented principled exception: Kog'Maw is archetype-labeled "mage" but is an
# attack-speed / on-hit MARKSMAN that genuinely builds the AD-carry set over pure
# AP - the scorer ranking carry > mage for Kog is correct; the label is the quirk.
_EXCEPTIONS = {"Kog'Maw"}


def _patch():
    return (_DS / "current.txt").read_text(encoding="utf-8").strip()


def _items_name2id():
    data = json.loads(
        (_DS / _patch() / "items.json").read_text(encoding="utf-8")
    ).get("data", {})
    out = {}
    for iid, it in data.items():
        nm = (it.get("name") or "").strip().lower()
        if nm:
            out.setdefault(nm, str(iid))
    return out


def _roster():
    data = json.loads(
        (_DS / _patch() / "champions.json").read_text(encoding="utf-8")
    ).get("data", {})
    return [(c.get("name") or cid) for cid, c in data.items()]


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        n2i = _items_name2id()
        cls.canon = {a: [n2i[n.lower()] for n in ns if n.lower() in n2i]
                     for a, ns in _CANON_NAMES.items()}
        cls.roster = _roster()


class CanonicalSets(_Base):
    def test_full_roster_present(self):
        # Guards a clean-checkout stub from making the coverage vacuous.
        self.assertGreater(len(self.roster), 150)

    def test_sets_resolve(self):
        for a, ids in self.canon.items():
            self.assertGreaterEqual(len(ids), 6, f"{a} set under-resolved: {ids}")


class PerChampionCoverage(_Base):
    def test_own_archetype_beats_opposite_damage_type(self):
        failures = []
        for champ in self.roster:
            prim = default_for_champion(champ)[0]
            opp = _OPPOSITE.get(prim, "mage")
            if opp == prim:
                opp = "carry" if prim != "carry" else "mage"
            own = score_build(self.canon[prim], champ, [], owned_count=6).total
            mis = score_build(self.canon[opp], champ, [], owned_count=6).total
            if not (own > mis):
                failures.append((champ, prim, round(own, 3), opp, round(mis, 3)))
        # Every failure must be a documented principled exception. A NEW champ
        # failing (a model regression) trips this loudly.
        #
        # AP-kit assassins (Akali / Ekko / Evelynn / Fizz / Katarina / Leblanc /
        # Diana) are a principled AXIS exception: _AP_ASSASSIN_IDS routes them to
        # the assassin archetype - the axis-agnostic ds.burst scorer, validated in
        # test_ap_assassin_override + live - but this test's canonical "assassin"
        # set is AD-lethality (Youmuu's / Duskblade / Serylda's), which an AP kit
        # cannot use. An AP assassin therefore correctly scores higher on the AP
        # (mage) set; the AD-canonical-set comparison is meaningless for it. Its
        # kit-fit is proven by the ds.burst routing, not this AD set.
        def _ap_assassin_axis_exception(f):
            return f[1] == "assassin" and kit_damage_axis(f[0]) == "ap"

        unexpected = [
            f for f in failures
            if f[0] not in _EXCEPTIONS and not _ap_assassin_axis_exception(f)
        ]
        self.assertEqual(unexpected, [], f"unexpected coverage failures: {unexpected}")

    def test_within_archetype_score_variation(self):
        # The model is genuinely per-champion: within each archetype, the own-set
        # score is NOT constant across champs (WP-C1 collapsed it to one value).
        byarch = defaultdict(set)
        for champ in self.roster:
            prim = default_for_champion(champ)[0]
            s = round(score_build(self.canon[prim], champ, [], owned_count=6).total, 3)
            byarch[prim].add(s)
        for arch, scores in byarch.items():
            self.assertGreater(len(scores), 1,
                               f"{arch} own-set score is flat - not per-champion")


if __name__ == "__main__":
    unittest.main()
