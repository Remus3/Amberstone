# arch: static champion data thin loader | section=coaching | frozen=no
"""
champion_profiles.py - loads per-champion data from data/champion_profiles/*.json.

Fields per champion: dmg, role, mana, sustain, mechanic, aram.
Source of truth is the JSON files; edit those, not this loader.
"""
import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data" / "champion_profiles"

CHAMPIONS: dict[str, dict] = {
    p.stem: json.loads(p.read_text(encoding="utf-8"))
    for p in sorted(_DATA_DIR.glob("*.json"))
}

TANKS          = {n for n, d in CHAMPIONS.items() if d["role"] == "tank"}
FIGHTERS       = {n for n, d in CHAMPIONS.items() if d["role"] == "fighter"}
MAGES          = {n for n, d in CHAMPIONS.items() if d["role"] == "mage"}
ASSASSINS      = {n for n, d in CHAMPIONS.items() if d["role"] == "assassin"}
MARKSMEN       = {n for n, d in CHAMPIONS.items() if d["role"] == "marksman"}
SUPPORTS       = {n for n, d in CHAMPIONS.items() if d["role"] == "support"}

AD_CHAMPS      = {n for n, d in CHAMPIONS.items() if d["dmg"] == "ad"}
AP_CHAMPS      = {n for n, d in CHAMPIONS.items() if d["dmg"] == "ap"}
HYBRID_CHAMPS  = {n for n, d in CHAMPIONS.items() if d["dmg"] == "hybrid"}
SUSTAIN_CHAMPS = {n for n, d in CHAMPIONS.items() if d.get("sustain")}
MANA_CHAMPS    = {n for n, d in CHAMPIONS.items() if d.get("mana")}
