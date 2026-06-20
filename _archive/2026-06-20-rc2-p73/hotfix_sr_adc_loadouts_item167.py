"""Item 167 ADC pollution hot-fix - patches sr-collapsed for 7 polluted champs.

Replaces auto-aligned junk (Trinity Force/Bastionbreaker/Heartsteel/Umbral mixed
on ADC primaries) with 16.10.x champ-specific meta builds. Atomic write.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def path(key, label, items, ks, prim, sec, summs=(4, 21), arch="", is_primary=False):
    r = {
        "key": key,
        "label": label,
        "items": list(items),
        "runes": {"keystone": ks, "primary": prim, "secondary": sec},
        "summoners": list(summs),
        "_source_variant_key": key,
    }
    if arch:
        r["_archetype"] = arch
    if is_primary:
        r["_is_primary"] = True
    return r


PATCH = {
    "Caitlyn": [
        path("adc-crit", "Crit",
             ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
             "Press the Attack", "Precision", "Domination", is_primary=True),
        path("lethality-poke", "Lethality",
             ["Eclipse", "Berserker's Greaves", "Opportunity",
              "Serylda's Grudge", "Edge of Night", "Lord Dominik's Regards"],
             "Fleet Footwork", "Precision", "Sorcery"),
        path("auto-sr-primary-carry", "Carry",
             ["Blade of The Ruined King", "Berserker's Greaves", "Runaan's Hurricane",
              "Lord Dominik's Regards", "Yun Tal Wildarrows", "Infinity Edge"],
             "Lethal Tempo", "Precision", "Domination", arch="carry"),
    ],
    "Ezreal": [
        path("manamune", "Manamune",
             ["Manamune", "Berserker's Greaves", "Trinity Force",
              "Lord Dominik's Regards", "Serylda's Grudge", "Edge of Night"],
             "First Strike", "Inspiration", "Sorcery", is_primary=True),
        path("adc-crit", "Crit",
             ["Essence Reaver", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
             "Fleet Footwork", "Precision", "Sorcery"),
        path("auto-sr-primary-carry", "Carry",
             ["Manamune", "Berserker's Greaves", "Trinity Force",
              "Muramana", "Serylda's Grudge", "Edge of Night"],
             "First Strike", "Inspiration", "Sorcery", arch="carry"),
    ],
    "Jinx": [
        path("adc-crit", "Crit",
             ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
             "Lethal Tempo", "Precision", "Domination", is_primary=True),
        path("adc-on-hit", "On-Hit",
             ["Blade of The Ruined King", "Berserker's Greaves", "Runaan's Hurricane",
              "Wit's End", "Lord Dominik's Regards", "Phantom Dancer"],
             "Lethal Tempo", "Precision", "Domination"),
        path("auto-sr-primary-carry", "Carry",
             ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Lord Dominik's Regards", "Runaan's Hurricane", "Bloodthirster"],
             "Press the Attack", "Precision", "Domination", arch="carry"),
    ],
    "Kai'Sa": [
        path("adc-on-hit", "On-Hit",
             ["Blade of The Ruined King", "Berserker's Greaves", "Runaan's Hurricane",
              "Nashor's Tooth", "Riftmaker", "Lord Dominik's Regards"],
             "Hail of Blades", "Domination", "Precision", is_primary=True),
        path("adc-crit", "Crit",
             ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
             "Press the Attack", "Precision", "Domination"),
        path("ap-burst", "AP Hybrid",
             ["Hubris", "Berserker's Greaves", "Nashor's Tooth",
              "Rabadon's Deathcap", "Void Staff", "Shadowflame"],
             "Electrocute", "Domination", "Sorcery"),
    ],
    "Kayn": [
        path("jg-bruiser", "Rhaast (Red)",
             ["Sundered Sky", "Plated Steelcaps", "Death's Dance",
              "Sterak's Gage", "Spear of Shojin", "Guardian Angel"],
             "Conqueror", "Precision", "Resolve", summs=(4, 11), is_primary=True),
        path("jg-assassin", "Shadow (Blue)",
             ["Eclipse", "Mercury's Treads", "Edge of Night",
              "Serylda's Grudge", "Death's Dance", "Maw of Malmortius"],
             "Hail of Blades", "Domination", "Precision", summs=(4, 11)),
        path("jg-lethality", "Lethality",
             ["Profane Hydra", "Mercury's Treads", "Edge of Night",
              "Serylda's Grudge", "Opportunity", "Lord Dominik's Regards"],
             "Electrocute", "Domination", "Precision", summs=(4, 11)),
    ],
    "Pantheon": [
        path("lethality", "Lethality",
             ["Eclipse", "Mercury's Treads", "Black Cleaver",
              "Sundered Sky", "Sterak's Gage", "Maw of Malmortius"],
             "Conqueror", "Precision", "Resolve", summs=(4, 12), is_primary=True),
        path("bruiser", "Bruiser",
             ["Sundered Sky", "Plated Steelcaps", "Black Cleaver",
              "Sterak's Gage", "Death's Dance", "Maw of Malmortius"],
             "Conqueror", "Precision", "Resolve", summs=(4, 12)),
        path("sup-lethality", "Sup Roam",
             ["Profane Hydra", "Mobility Boots", "Opportunity",
              "Edge of Night", "Serylda's Grudge", "Umbral Glaive"],
             "Electrocute", "Domination", "Precision", summs=(4, 14)),
    ],
    "Varus": [
        path("lethality", "Lethality",
             ["Eclipse", "Berserker's Greaves", "Opportunity",
              "Serylda's Grudge", "Edge of Night", "Lord Dominik's Regards"],
             "Press the Attack", "Precision", "Sorcery", is_primary=True),
        path("adc-on-hit", "On-Hit",
             ["Blade of The Ruined King", "Berserker's Greaves", "Runaan's Hurricane",
              "Wit's End", "Lord Dominik's Regards", "Phantom Dancer"],
             "Lethal Tempo", "Precision", "Domination"),
        path("adc-crit", "Crit",
             ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
             "Lethal Tempo", "Precision", "Domination"),
    ],
}


def main():
    p = Path(r"C:\Riot Commander\data\champion_loadouts.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    ch = d["champions"]
    flips = 0
    for name, paths in PATCH.items():
        if name not in ch:
            print(f"SKIP {name} not in roster")
            continue
        v = ch[name]["variants"].get("sr-collapsed")
        if not v:
            print(f"SKIP {name} no sr-collapsed")
            continue
        prim = next(pp for pp in paths if pp.get("_is_primary"))
        v["runes"] = dict(prim["runes"])
        v["summoners"] = list(prim["summoners"])
        v["items"] = list(prim["items"])
        v["build_paths"] = paths
        flips += 1
        print(f"  patched {name}: PRIMARY = {prim['label']} {prim['items'][:3]}...")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=True, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    print(f"OK {flips} champs patched, atomic write done")


if __name__ == "__main__":
    main()
