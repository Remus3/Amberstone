"""RM-662 (L-02): ARAM modifier source-parity guard, wiki sidecar vs aram_modifiers.

The engine's ARAM per-champion modifiers (the ``aram_modifiers`` block of each
``champions.json`` row, extracted from external reference L) stayed at
their 16.18.1 values for a whole cycle while our OWN wiki sidecar
(``wiki_stats.json`` -> ``mode_modifiers.aram``) already carried the newer
numbers: 19 of 363 overlapping fields disagreed. Nothing compared the two.

This guard compares them per champion, per field, at the CURRENT patch. It is a
cross-check only: the wiki does NOT become the primary ARAM source (that
reverses a Settled line and needs an ADR plus an adjudicator).

Only fields PRESENT in the wiki row are compared: the wiki omits neutral
values, so an absent field is "no data", not 1.0.
"""

import json
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO_ROOT / "data" / "daemon_slayer"

# wiki mode_modifiers.aram key -> aram_modifiers key.
FIELD_MAP = {
    "dmg_dealt": "aramDamageDealt",
    "dmg_taken": "aramDamageTaken",
    "healing": "aramHealing",
    "shielding": "aramShielding",
    "tenacity": "aramTenacity",
    "total_as": "aramAttackSpeed",
    "ability_haste": "aramAbilityHaste",
}

# Wiki ARAM keys with no aram_modifiers counterpart. Any OTHER unmapped key
# fails the guard, so a new wiki field is mapped or excluded on purpose.
EXCLUDED_FIELDS = {
    # Energy-regen multiplier (energy champions). aram_modifiers has no energy
    # axis and no DS scorer reads energy regen.
    "energyregen_mod": "no aram_modifiers counterpart",
}

# Display-name spellings -> DDragon champion id. The sidecar is keyed by
# DDragon id today (Kaisa, MonkeyKing), so these resolve nothing at 16.19.1;
# they exist so a re-key of the sidecar to wiki display names cannot silently
# drop a champion from the comparison (the resolve test fails instead).
ALIASES = {
    "Kai'Sa": "Kaisa",
    "Wukong": "MonkeyKing",
    "Cho'Gath": "Chogath",
    "Kha'Zix": "Khazix",
    "Kog'Maw": "KogMaw",
    "Vel'Koz": "Velkoz",
    "Bel'Veth": "Belveth",
    "Rek'Sai": "RekSai",
    "Nunu & Willump": "Nunu",
    "Renata Glasc": "Renata",
    "LeBlanc": "Leblanc",
    "Dr. Mundo": "DrMundo",
}

# (champion id, wiki field) pairs allowed to disagree, each with its reason.
# An entry that stops disagreeing FAILS the guard so the list cannot rot.
ALLOWLIST = {
    ("Kled", "dmg_dealt"): (
        "Genuine source disagreement, measured 2026-10-04: the live wiki "
        "Module:ChampionData Kled record (id 240) reads aram dmg_dealt 1.05, "
        "external reference L moved Kled 1.05 -> 1 at 16.19.1. Neither side "
        "is confirmed by patch notes, so neither is overwritten."
    ),
    ("Kled", "dmg_taken"): (
        "Sidecar parse artifact, not a source disagreement: the wiki module "
        "carries a second Kled record (id 240.1, 'Kled and Skaarl') whose aram "
        "block is Lua-COMMENTED OUT (--[\"dmg_taken\"] = 0.9). "
        "tools/daemon_slayer_wiki_stats_extract.py does not skip Lua comments "
        "and the second record overwrites the first, so the sidecar reads 0.9 "
        "where the live record 240 reads 1, which matches aram_modifiers."
    ),
}

# The overlap measured 2026-10-04 is 363 fields; a floor well below it keeps
# the guard from passing vacuously if a re-key or schema change empties it.
MIN_OVERLAP = 300


def _current_patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _load(patch: str):
    wiki = json.loads((_DS_DATA / patch / "wiki_stats.json").read_text(encoding="utf-8"))
    champs = json.loads((_DS_DATA / patch / "champions.json").read_text(encoding="utf-8"))
    return wiki["champions"], champs["data"]


def _resolve(wiki_key: str, champs: dict) -> str | None:
    if wiki_key in champs:
        return wiki_key
    alias = ALIASES.get(wiki_key)
    if alias in champs:
        return alias
    for cid, rec in champs.items():
        if rec.get("name") == wiki_key:
            return cid
    return None


def compare(wiki_patch: str, aram_patch: str | None = None):
    """Return (overlap, mismatches, unresolved, unknown_fields).

    mismatches: sorted list of (champ_id, wiki_field, wiki_value, aram_value).
    """
    wiki, _ = _load(wiki_patch)
    _, champs = _load(aram_patch or wiki_patch)
    overlap = 0
    mismatches = []
    unresolved = []
    unknown = set()
    for wkey, row in wiki.items():
        aram = ((row or {}).get("mode_modifiers") or {}).get("aram") or {}
        if not aram:
            continue
        cid = _resolve(wkey, champs)
        if cid is None:
            unresolved.append(wkey)
            continue
        mods = (champs[cid].get("lolmath") or {}).get("aram_modifiers") or {}
        for field, wval in aram.items():
            if field in EXCLUDED_FIELDS:
                continue
            target = FIELD_MAP.get(field)
            if target is None:
                unknown.add(field)
                continue
            overlap += 1
            lval = mods.get(target)
            if lval is None or abs(float(lval) - float(wval)) > 1e-9:
                mismatches.append((cid, field, wval, lval))
    return overlap, sorted(mismatches), sorted(unresolved), sorted(unknown)


class AramModifierSourceParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = _current_patch()
        cls.overlap, cls.mismatches, cls.unresolved, cls.unknown = compare(cls.patch)

    def test_every_wiki_row_resolves_to_a_champion(self) -> None:
        self.assertEqual(self.unresolved, [])

    def test_no_unmapped_wiki_aram_field(self) -> None:
        self.assertEqual(self.unknown, [])

    def test_overlap_is_not_vacuous(self) -> None:
        self.assertGreaterEqual(self.overlap, MIN_OVERLAP)

    def test_aram_modifiers_agree_with_wiki_sidecar(self) -> None:
        unexplained = [m for m in self.mismatches if (m[0], m[1]) not in ALLOWLIST]
        self.assertEqual(
            unexplained, [],
            f"{len(unexplained)} ARAM modifier field(s) disagree between "
            f"aram_modifiers and the wiki sidecar at {self.patch} "
            "(champ, wiki field, wiki value, aram_modifiers value). Re-extract "
            "the patch, or add an ALLOWLIST entry WITH a measured reason.",
        )

    def test_allowlist_entries_still_disagree(self) -> None:
        live = {(m[0], m[1]) for m in self.mismatches}
        stale = sorted(set(ALLOWLIST) - live)
        self.assertEqual(stale, [], "allowlisted pairs now agree - remove them")

    def test_allowlist_reasons_are_written(self) -> None:
        for key, reason in ALLOWLIST.items():
            self.assertGreater(len(reason), 40, key)

    def test_guard_catches_the_16_18_1_lag(self) -> None:
        # Frozen history: the committed 16.18.1 snapshot is the failure this
        # guard exists for. Comparing the CURRENT wiki sidecar against the
        # 16.18.1 aram_modifiers must surface the lagged fields, so the
        # comparator itself cannot go blind.
        if not (_DS_DATA / "16.18.1" / "champions.json").exists():
            self.skipTest("16.18.1 snapshot not on disk")
        _, mism, _, _ = compare(self.patch, "16.18.1")
        unexplained = {(m[0], m[1]) for m in mism if (m[0], m[1]) not in ALLOWLIST}
        for pair in (("Qiyana", "ability_haste"), ("Ziggs", "dmg_dealt"),
                     ("Xayah", "total_as"), ("Vladimir", "healing")):
            self.assertIn(pair, unexplained)


if __name__ == "__main__":
    unittest.main()
