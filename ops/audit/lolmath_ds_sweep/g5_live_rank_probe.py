"""G5 live-engine confirmation: where do the lolmath-favored 'never
recommended' items actually RANK in the live DS scorer? If they appear in
the ranked list at a low position, the gap is scorer valuation (in-pool,
out-ranked), not pool membership. Probes live :8893.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"C:\Riot Commander")))
from core.daemon_slayer_client import rank_for_primary_archetype  # noqa: E402

# (champion, archetype, [lolmath-wanted item NAMES to locate in the ranking])
CASES = [
    ("Talon", "assassin", ["Profane Hydra", "Hubris", "Youmuu's Ghostblade",
                            "Serylda's Grudge", "Umbral Glaive"]),
    ("Akali", "assassin", ["Lich Bane", "Hextech Gunblade", "Stormsurge",
                           "Shadowflame", "Rabadon's Deathcap"]),
    ("Lux", "mage", ["Liandry's Torment", "Blackfire Torch", "Shadowflame",
                     "Stormsurge", "Cryptbloom"]),
    ("Jhin", "carry", ["Hubris", "The Collector", "Lord Dominik's Regards",
                       "Infinity Edge"]),
]

for champ, arch, wanted in CASES:
    out = rank_for_primary_archetype(
        champ, arch, level=11, item_ids=[], mode="SR",
        target_armor=80.0, target_mr=60.0, target_max_hp=2400.0,
        target_bonus_hp=1000.0, top=120, filter_shared_uniques=True,
    )
    if not out or not out.get("ok"):
        print(f"\n{champ} [{arch}]: ENGINE UNREACHABLE ({out})")
        continue
    ranked = out.get("ranked") or []
    pos_by_name = {}
    for i, r in enumerate(ranked, 1):
        pos_by_name.setdefault(r.get("item_name"), i)
    print(f"\n{champ} [{arch}] scorer={out.get('scorer')} ranked_len={len(ranked)}")
    top6 = [r.get("item_name") for r in ranked[:6]]
    print(f"  DS top6: {top6}")
    for nm in wanted:
        p = pos_by_name.get(nm)
        print(f"    {nm:26} -> {'rank #' + str(p) if p else 'ABSENT from ranking'}")
