# arch: curated DDragon info.attack/magic overrides for damage-type classification | section=core | frozen=no
"""core/champion_info_overrides.py - curated damage-profile info for champions
DDragon leaves zeroed.

DDragon's champion.json `info.attack` / `info.magic` 1-10 ratings are the signal
RC uses to classify a champion AD vs AP (the champ-select enemy chip in
dashboard.routes_dictionary + the team damage-mix meter in
dashboard.routes_pickban). For a handful of champions Riot never populated the
block - it is all-zero for Akshan / Rell / Seraphine / Vex, and Qiyana carries
`attack=0` despite being an AD assassin. This was VERIFIED as upstream Riot data,
not a local mirror bug: data/meta/ddragon_champions.json is byte-identical to the
raw DDragon champion.json (data/meta_build/ddragon/<patch>/champion.json) for
these entries, and the same zeros appear across patches 16.11 - 16.13. So a raw
re-fetch would only re-zero them (the operator-reported symptom: Seraphine
rendered "AD SUPPORT" from the 0>=0 tie, 2026-06-30).

These curated ratings restore the correct AD/AP polarity + a rough magnitude so
both consumers read each champ's real damage type. Only champs whose DDragon zero
produces a WRONG result are listed - pure-AD champs with a legit `magic=0`
(Ambessa / Naafiri / Yunara) and pure-AP Lillia (`attack=0`) already classify
correctly and are intentionally omitted. The overlay fills ONLY fields DDragon
left zero/absent, so if Riot later populates a real value it wins.
"""
from __future__ import annotations

# Display-name -> curated info block. Values are DDragon-style 1-10 damage-profile
# ratings chosen to match each champion's real identity (only the attack-vs-magic
# polarity + rough lean drive any decision; `difficulty` is cosmetic).
CHAMPION_INFO_OVERRIDES: dict[str, dict[str, int]] = {
    "Seraphine": {"attack": 2, "magic": 8, "defense": 1, "difficulty": 8},  # AP enchanter support
    "Akshan":    {"attack": 8, "magic": 1, "defense": 4, "difficulty": 6},  # AD marksman / assassin
    "Rell":      {"attack": 2, "magic": 6, "defense": 8, "difficulty": 4},  # AP tank support
    "Vex":       {"attack": 2, "magic": 9, "defense": 4, "difficulty": 5},  # AP burst mage
    "Qiyana":    {"attack": 8, "magic": 3, "defense": 3, "difficulty": 8},  # AD assassin (DDragon attack=0)
}


def merged_info(name, raw_info):
    """Return `raw_info` overlaid with any curated override for `name`.

    Fills ONLY the fields DDragon left zero or absent, so a future DDragon fix to
    a real (non-zero) value is respected rather than clobbered. Qiyana keeps her
    real DDragon `magic=4` while her missing `attack` fills to 8, which still
    resolves AD (8 >= 4). A non-dict `raw_info` is treated as empty. Never
    mutates the input; returns a new dict."""
    base = dict(raw_info) if isinstance(raw_info, dict) else {}
    override = CHAMPION_INFO_OVERRIDES.get(name)
    if not override:
        return base
    for field, value in override.items():
        if not base.get(field):  # 0 / None / missing -> DDragon has no signal
            base[field] = value
    return base
