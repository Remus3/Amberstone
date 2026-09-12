"""
item_advisor.py - ADC Item Recommendation Engine (Season 16 / Patch 26.8)

Given: champion, current items, gold, enemy comp, ally comp
Returns: full build path, next purchase, affordable components

Supports: Jinx, Vayne, Tristana, Caitlyn, Nilah, Miss Fortune
Item costs updated for Season 16. Easy to update - just edit ITEMS dict.
"""

COMPONENTS = {
    "Long Sword":         {"cost": 350,  "from": []},
    "Dagger":             {"cost": 300,  "from": []},
    "Pickaxe":            {"cost": 875,  "from": []},
    "B.F. Sword":         {"cost": 1300, "from": []},
    "Cloak of Agility":   {"cost": 600,  "from": []},
    "Recurve Bow":        {"cost": 1000, "from": []},
    "Vampiric Scepter":   {"cost": 900,  "from": []},
    "Noonquiver":         {"cost": 1100, "from": ["Long Sword", "Dagger"], "combine": 450},
    "Zeal":               {"cost": 1050, "from": ["Dagger", "Dagger"], "combine": 450},
    "Last Whisper":       {"cost": 1450, "from": ["Long Sword", "Long Sword"], "combine": 750},
    "Executioner's Calling": {"cost": 800, "from": ["Long Sword"], "combine": 450},
    "Quicksilver Sash":   {"cost": 1300, "from": [], "combine": 0},
    "Boots":              {"cost": 300,  "from": []},
    "Berserker's Greaves": {"cost": 1100, "from": ["Boots", "Dagger"], "combine": 500},
}

ITEMS = {
    "Kraken Slayer": {
        "cost": 3000, "from": ["Noonquiver", "Pickaxe", "Dagger"], "combine": 725,
        "stats": "45 AD, 40% AS, 4% MS", "tag": "dps",
    },
    "Yun Tal Wildarrows": {
        "cost": 3000, "from": ["B.F. Sword", "Noonquiver"], "combine": 600,
        "stats": "50 AD, 25% crit", "tag": "crit_ad",
    },
    "Hexoptics C44": {
        "cost": 3000, "from": ["Pickaxe", "Noonquiver", "Long Sword"], "combine": 675,
        "stats": "50 AD, 25% crit, range scaling", "tag": "range",
    },
    "Phantom Dancer": {
        "cost": 2650, "from": ["Zeal", "Dagger", "Dagger"], "combine": 1000,
        "stats": "65% AS, 25% crit, 10% MS", "tag": "as",
    },
    "Runaan's Hurricane": {
        "cost": 2650, "from": ["Zeal", "Dagger", "Dagger"], "combine": 1000,
        "stats": "45% AS, 25% crit, multi-bolt", "tag": "as_aoe",
    },
    "Rapid Firecannon": {
        "cost": 2650, "from": ["Zeal", "Dagger", "Dagger"], "combine": 1000,
        "stats": "45% AS, 25% crit, range burst", "tag": "as",
    },
    "Statikk Shiv": {
        "cost": 2650, "from": ["Zeal", "Dagger", "Dagger"], "combine": 1000,
        "stats": "45% AS, 25% crit, waveclear", "tag": "as_wave",
    },
    "Stormrazor": {
        "cost": 3000, "from": ["B.F. Sword", "Zeal"], "combine": 650,
        "stats": "45 AD, 25% AS, 25% crit, energized", "tag": "burst",
    },
    "Infinity Edge": {
        "cost": 3600, "from": ["B.F. Sword", "Pickaxe", "Cloak of Agility"], "combine": 825,
        "stats": "70 AD, 25% crit, 200% crit dmg", "tag": "crit_cap",
    },
    "Lord Dominik's Regards": {
        "cost": 3000, "from": ["Last Whisper", "Pickaxe", "Cloak of Agility"], "combine": 75,
        "stats": "35 AD, 25% crit, 35% armor pen", "tag": "armor_pen",
    },
    "Mortal Reminder": {
        "cost": 3200, "from": ["Executioner's Calling", "Zeal", "Long Sword"], "combine": 1000,
        "stats": "30 AD, 25% AS, 25% crit, anti-heal", "tag": "anti_heal",
    },
    "Bloodthirster": {
        "cost": 3400, "from": ["B.F. Sword", "Vampiric Scepter", "Cloak of Agility"], "combine": 600,
        "stats": "55 AD, 18% lifesteal, 25% crit, shield", "tag": "lifesteal",
    },
    "Immortal Shieldbow": {
        "cost": 3200, "from": ["B.F. Sword", "Vampiric Scepter", "Cloak of Agility"], "combine": 400,
        "stats": "50 AD, 15% lifesteal, 25% crit, lifeline", "tag": "lifeline",
    },
    "Guardian Angel": {
        "cost": 3200, "from": ["B.F. Sword", "Long Sword"], "combine": 1550,
        "stats": "55 AD, 45 armor, revive", "tag": "revive",
    },
    "Mercurial Scimitar": {
        "cost": 3200, "from": ["Quicksilver Sash", "Pickaxe", "Cloak of Agility"], "combine": 425,
        "stats": "40 AD, 25% crit, 30 MR, QSS", "tag": "qss",
    },
    "Banshee's Veil": {
        "cost": 2600, "from": [], "combine": 0,
        "stats": "70 AP, 40 MR, spell shield", "tag": "spell_shield",
    },
    "Blade of the Ruined King": {
        "cost": 3200, "from": ["Vampiric Scepter", "Recurve Bow", "Long Sword"], "combine": 950,
        "stats": "40 AD, 25% AS, 8% lifesteal, %HP on-hit", "tag": "on_hit",
    },
    "Berserker's Greaves": {
        "cost": 1100, "from": ["Boots", "Dagger"], "combine": 500,
        "stats": "35% AS, 45 MS", "tag": "boots",
    },
}


# =========================================================================
# CHAMPION BUILD PATHS
# =========================================================================

CHAMPION_BUILDS = {
    "Jinx": {
        "default": ["Yun Tal Wildarrows", "Runaan's Hurricane", "Infinity Edge",
                     "Lord Dominik's Regards", "Phantom Dancer", "Bloodthirster"],
        "alt":     ["Hexoptics C44", "Phantom Dancer", "Infinity Edge",
                     "Lord Dominik's Regards", "Runaan's Hurricane", "Bloodthirster"],
        "boots": 1, "boots_item": "Berserker's Greaves",
        "anti_tank": {"slot": 3, "item": "Lord Dominik's Regards"},
        "anti_heal": {"slot": 3, "item": "Mortal Reminder"},
        "anti_burst": {"slot": 4, "item": "Immortal Shieldbow"},
        "anti_cc": {"slot": 4, "item": "Mercurial Scimitar"},
        "range_ok": True,
    },
    "Vayne": {
        "default": ["Blade of the Ruined King", "Phantom Dancer", "Infinity Edge",
                     "Runaan's Hurricane", "Guardian Angel", "Bloodthirster"],
        "alt":     ["Kraken Slayer", "Phantom Dancer", "Infinity Edge",
                     "Lord Dominik's Regards", "Guardian Angel", "Bloodthirster"],
        "boots": 1, "boots_item": "Berserker's Greaves",
        "anti_tank": {"slot": 3, "item": "Lord Dominik's Regards"},
        "anti_heal": {"slot": 3, "item": "Mortal Reminder"},
        "anti_burst": {"slot": 4, "item": "Immortal Shieldbow"},
        "anti_cc": {"slot": 4, "item": "Mercurial Scimitar"},
        "range_ok": False,
    },
    "Tristana": {
        "default": ["Yun Tal Wildarrows", "Stormrazor", "Infinity Edge",
                     "Rapid Firecannon", "Lord Dominik's Regards", "Guardian Angel"],
        "alt":     ["Kraken Slayer", "Phantom Dancer", "Infinity Edge",
                     "Lord Dominik's Regards", "Bloodthirster", "Guardian Angel"],
        "boots": 1, "boots_item": "Berserker's Greaves",
        "anti_tank": {"slot": 4, "item": "Lord Dominik's Regards"},
        "anti_heal": {"slot": 4, "item": "Mortal Reminder"},
        "anti_burst": {"slot": 5, "item": "Immortal Shieldbow"},
        "anti_cc": {"slot": 5, "item": "Mercurial Scimitar"},
        "range_ok": False,
    },
    "Caitlyn": {
        "default": ["Hexoptics C44", "Stormrazor", "Infinity Edge",
                     "Rapid Firecannon", "Lord Dominik's Regards", "Bloodthirster"],
        "alt":     ["Yun Tal Wildarrows", "Phantom Dancer", "Infinity Edge",
                     "Lord Dominik's Regards", "Rapid Firecannon", "Bloodthirster"],
        "boots": 1, "boots_item": "Berserker's Greaves",
        "anti_tank": {"slot": 4, "item": "Lord Dominik's Regards"},
        "anti_heal": {"slot": 4, "item": "Mortal Reminder"},
        "anti_burst": {"slot": 5, "item": "Immortal Shieldbow"},
        "anti_cc": {"slot": 5, "item": "Mercurial Scimitar"},
        "range_ok": True,
    },
    "Nilah": {
        "default": ["Kraken Slayer", "Phantom Dancer", "Infinity Edge",
                     "Bloodthirster", "Lord Dominik's Regards", "Guardian Angel"],
        "alt":     ["Blade of the Ruined King", "Phantom Dancer", "Infinity Edge",
                     "Lord Dominik's Regards", "Bloodthirster", "Guardian Angel"],
        "boots": 1, "boots_item": "Berserker's Greaves",
        "anti_tank": {"slot": 4, "item": "Lord Dominik's Regards"},
        "anti_heal": {"slot": 3, "item": "Mortal Reminder"},
        "anti_burst": {"slot": 3, "item": "Immortal Shieldbow"},
        "anti_cc": {"slot": 5, "item": "Mercurial Scimitar"},
        "range_ok": False,
    },
    "Miss Fortune": {
        "default": ["Yun Tal Wildarrows", "Stormrazor", "Infinity Edge",
                     "Lord Dominik's Regards", "Phantom Dancer", "Bloodthirster"],
        "alt":     ["Hexoptics C44", "Phantom Dancer", "Infinity Edge",
                     "Lord Dominik's Regards", "Rapid Firecannon", "Bloodthirster"],
        "boots": 1, "boots_item": "Berserker's Greaves",
        "anti_tank": {"slot": 3, "item": "Lord Dominik's Regards"},
        "anti_heal": {"slot": 3, "item": "Mortal Reminder"},
        "anti_burst": {"slot": 4, "item": "Immortal Shieldbow"},
        "anti_cc": {"slot": 4, "item": "Mercurial Scimitar"},
        "range_ok": True,
    },
}


# =========================================================================
# ENEMY COMP ANALYSIS
# =========================================================================

CHAMPION_TAGS = {
    # Tanks / armor stackers
    "Malphite": ["tank", "armor"], "Rammus": ["tank", "armor"],
    "Ornn": ["tank", "armor"], "Leona": ["tank", "engage"],
    "Sejuani": ["tank", "cc"], "Amumu": ["tank", "cc"],
    "Maokai": ["tank", "cc"], "Nautilus": ["tank", "cc", "engage"],
    "Thresh": ["tank", "cc", "engage"], "Alistar": ["tank", "engage"],
    "Braum": ["tank"], "Tahm Kench": ["tank"],
    "Cho'Gath": ["tank", "cc"], "Zac": ["tank", "cc", "engage"],
    "Sion": ["tank", "armor"], "Poppy": ["tank", "anti_dash"],
    "K'Sante": ["tank"], "Rell": ["tank", "engage", "cc"],
    "Shen": ["tank"], "Galio": ["tank", "cc"],
    # Assassins / divers
    "Zed": ["assassin", "burst"], "Talon": ["assassin", "burst"],
    "Fizz": ["assassin", "burst"], "Akali": ["assassin", "burst"],
    "Katarina": ["assassin", "burst"], "Ekko": ["assassin", "burst"],
    "LeBlanc": ["assassin", "burst"], "Qiyana": ["assassin", "burst"],
    "Rengar": ["assassin", "burst", "dive"], "Kha'Zix": ["assassin", "burst"],
    "Evelynn": ["assassin", "burst"], "Shaco": ["assassin"],
    "Nocturne": ["assassin", "dive"], "Diana": ["dive", "burst"],
    "Vi": ["dive", "cc"], "Jarvan IV": ["dive", "cc", "engage"],
    "Camille": ["dive"], "Irelia": ["dive", "burst"],
    "Yone": ["dive", "burst"], "Yasuo": ["dive"],
    "Master Yi": ["dive", "dps"],
    # Healers
    "Soraka": ["healer"], "Yuumi": ["healer"],
    "Sona": ["healer"], "Nami": ["healer", "cc"],
    "Lulu": ["healer", "cc"], "Janna": ["healer"],
    "Vladimir": ["healer", "burst"], "Swain": ["healer"],
    "Sylas": ["healer", "burst"], "Aatrox": ["healer", "dive"],
    "Dr. Mundo": ["healer", "tank"], "Warwick": ["healer", "dive", "cc", "suppress"],
    "Briar": ["healer", "dive"],
    # Heavy CC / suppressors
    "Morgana": ["cc"], "Lux": ["cc", "burst"],
    "Ashe": ["cc"], "Veigar": ["cc", "burst"],
    "Cassiopeia": ["cc"], "Twisted Fate": ["cc"],
    "Lissandra": ["cc", "burst"], "Malzahar": ["cc", "suppress"],
    "Skarner": ["cc", "suppress"], "Mordekaiser": ["bruiser", "suppress"],
    # Bruisers
    "Darius": ["bruiser", "armor"], "Garen": ["bruiser", "armor"],
    "Nasus": ["bruiser", "armor"], "Jax": ["bruiser", "dive"],
    "Wukong": ["bruiser", "dive", "cc"],
    "Riven": ["bruiser", "dive"], "Fiora": ["bruiser"],
    "Ambessa": ["bruiser", "dive"],
    # Supports / engagers (expanded patch 26.8)
    "Blitzcrank": ["tank", "cc", "engage"], "Pyke": ["assassin", "cc"],
    "Rakan": ["engage", "cc"], "Karma": ["healer", "cc"],
    "Bard": ["cc", "engage"], "Zyra": ["cc"],
    "Vel'Koz": ["cc", "burst"], "Seraphine": ["healer", "cc"],
    "Renata Glasc": ["healer", "cc"], "Ivern": ["healer"],
    "Taric": ["healer", "tank"], "Zilean": ["healer", "cc"],
    # Divers / fighters (expanded)
    "Hecarim": ["dive", "cc", "engage"], "Volibear": ["dive", "cc", "engage"],
    "Xin Zhao": ["dive", "cc"], "Trundle": ["bruiser"],
    "Gangplank": ["bruiser"], "Urgot": ["bruiser", "dive"],
    "Naafiri": ["assassin", "dive", "burst"],
    "Kayn": ["dive"], "Viego": ["dive", "burst", "healer"],
    # ADCs (secondary threats)
    "Draven": ["burst"], "Varus": ["cc"],
    "Kai'Sa": ["dive", "burst"], "Xayah": ["cc"],
    "Jinx": ["dps"], "Caitlyn": ["dps"], "Tristana": ["dive"],
    "Samira": ["burst", "dive"], "Lucian": ["burst"],
    "Miss Fortune": ["cc", "burst"], "Twitch": ["dps"],
    "Aphelios": ["dps"], "Sivir": ["dps"], "Kog'Maw": ["dps"],
    "Jhin": ["cc", "burst"], "Ezreal": ["burst"], "Nilah": ["dive"],
    # Mages
    "Annie": ["burst", "cc"], "Syndra": ["cc", "burst"],
    "Orianna": ["cc", "burst"], "Zoe": ["cc", "burst"],
    "Hwei": ["cc", "burst"], "Vex": ["cc", "burst"],
    "Aurora": ["cc", "burst"], "Heimerdinger": ["dps"], "Ziggs": ["burst"],
    # Misc
    "Gnar": ["tank", "cc", "engage"], "Kennen": ["cc", "dive"],
    "Kled": ["dive"], "Udyr": ["dive", "engage"],
    "Gragas": ["cc", "engage", "tank"],
}


# -- Matchup weights loader ---------------------------------------------------
import json as _json
import logging as _logging
from pathlib import Path as _Path

_log = _logging.getLogger(__name__)

_MATCHUP_WEIGHTS_PATH = _Path(__file__).parent / "data" / "meta_build" / "matchup_weights.json"
_MATCHUP_WEIGHTS = None

# Paths whose load failure has already been logged in this process. A failed
# load is deliberately NOT cached (see _load_exclusions), so without this
# guard a persistently missing file would warn on every is_redundant() call.
_WARNED_LOAD_PATHS: set = set()


def _warn_load_once(path, exc) -> None:
    key = str(path)
    if key in _WARNED_LOAD_PATHS:
        return
    _WARNED_LOAD_PATHS.add(key)
    _log.warning(
        "item_advisor: could not load %s (%s: %s) - running degraded, "
        "will retry on next call", path, type(exc).__name__, exc,
    )


def _load_matchup_weights():
    """Lazily load matchup_weights.json. Returns None on failure.

    A failure is NOT cached: the next call retries, so a transient read error
    (AV scan / editor lock on Windows, or a deploy that lands the file late)
    self-heals. It is logged once per process rather than silently swallowed.
    """
    global _MATCHUP_WEIGHTS
    if _MATCHUP_WEIGHTS is not None:
        return _MATCHUP_WEIGHTS
    try:
        _MATCHUP_WEIGHTS = _json.loads(_MATCHUP_WEIGHTS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _warn_load_once(_MATCHUP_WEIGHTS_PATH, exc)
    return _MATCHUP_WEIGHTS


def get_matchup_context(enemy_champs):
    """Return a concise string of priority item overrides for the enemy comp."""
    weights = _load_matchup_weights()
    if not weights:
        return ""
    overrides = weights.get("enemy_item_overrides", {})
    notes = []
    seen_items = set()
    for champ in (enemy_champs or []):
        ov = overrides.get(champ)
        if ov and ov.get("priority_item") not in seen_items:
            item = ov["priority_item"]
            reason = ov.get("reason", "")[:60]
            notes.append(f"vs {champ}: {item} - {reason}")
            seen_items.add(item)
    return "; ".join(notes[:3])


def analyze_enemy_comp(enemy_champs):
    """Analyze enemy team and return threat flags."""
    tags = {"tank": 0, "armor": 0, "assassin": 0, "burst": 0,
            "dive": 0, "healer": 0, "cc": 0, "suppress": 0,
            "engage": 0, "anti_dash": 0}

    for champ in enemy_champs:
        champ_tags = CHAMPION_TAGS.get(champ, [])
        for t in champ_tags:
            if t in tags:
                tags[t] += 1

    return {
        "need_armor_pen": tags["tank"] >= 2 or tags["armor"] >= 2,
        "need_anti_heal": tags["healer"] >= 2,
        "need_anti_burst": tags["assassin"] >= 1 or tags["dive"] >= 2,
        "need_qss":        tags["suppress"] >= 1,
        "heavy_cc":        tags["cc"] >= 3,
        "heavy_engage":    tags["engage"] >= 2,
        "tags": tags,
    }


# =========================================================================
# BUILD RESOLVER
# =========================================================================

def resolve_build(champion, enemy_champs, current_items=None):
    """
    Determine the optimal build path for the given champion and enemy comp.
    Returns ordered list of item names (including boots).
    """
    if champion not in CHAMPION_BUILDS:
        return []

    cfg = CHAMPION_BUILDS[champion]
    build = list(cfg["default"])
    threats = analyze_enemy_comp(enemy_champs)

    if threats["need_qss"] and "anti_cc" in cfg:
        slot = cfg["anti_cc"]["slot"]
        item = cfg["anti_cc"]["item"]
        if slot < len(build) and item not in build:
            build[slot] = item

    if threats["need_anti_heal"] and "anti_heal" in cfg:
        slot = cfg["anti_heal"]["slot"]
        item = cfg["anti_heal"]["item"]
        if slot < len(build) and item not in build:
            build[slot] = item

    if threats["need_armor_pen"] and "anti_tank" in cfg:
        slot = cfg["anti_tank"]["slot"]
        item = cfg["anti_tank"]["item"]
        if item not in build and slot < len(build):
            build[slot] = item

    if threats["need_anti_burst"] and "anti_burst" in cfg:
        slot = cfg["anti_burst"]["slot"]
        item = cfg["anti_burst"]["item"]
        if slot < len(build) and item not in build:
            build[slot] = item

    boots_pos = cfg.get("boots", 1)
    boots_item = cfg.get("boots_item", "Berserker's Greaves")
    build.insert(boots_pos, boots_item)

    # Filter exclusion-redundant items out of the suggested path
    # (e.g., never suggest Lord Dominik's after Mortal Reminder is in build).
    if current_items:
        cleaned = []
        owned_so_far = list(current_items)
        for it in build:
            redundant, _why = is_redundant(it, owned_so_far + cleaned)
            if not redundant:
                cleaned.append(it)
        build = cleaned

    return build


# =========================================================================
# EXCLUSIONS / REDUNDANCY  (data/item_exclusions.json)
# =========================================================================


_EXCLUSIONS_PATH = _Path(__file__).parent / "data" / "item_exclusions.json"
_EXCLUSIONS_CACHE = None


def _load_exclusions():
    """Load and cache the exclusion table."""
    global _EXCLUSIONS_CACHE
    if _EXCLUSIONS_CACHE is not None:
        return _EXCLUSIONS_CACHE
    try:
        raw = _json.loads(_EXCLUSIONS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError(f"expected a JSON object, got {type(raw).__name__}")
    except Exception as exc:  # noqa: BLE001
        # Do NOT promote the failure into the cache. A {} cached here is
        # success-shaped (the `is not None` sentinel above accepts it), so one
        # transient read error would leave is_redundant() exclusion-blind for
        # the whole process lifetime with nothing retrying and nothing logged.
        _warn_load_once(_EXCLUSIONS_PATH, exc)
        return {}
    out = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if not isinstance(v, dict):
            continue
        out[k] = {
            "kind": v.get("kind", "functional"),
            "rule": v.get("rule", ""),
            "items": [s.lower().strip() for s in v.get("items", [])],
            "upgrade_chain": v.get("upgrade_chain", False),
        }
    _EXCLUSIONS_CACHE = out
    return _EXCLUSIONS_CACHE


def _norm(name):
    return (name or "").lower().strip()


def is_redundant(item_name, owned_items):
    """Returns (True, reason_str) if buying `item_name` would be redundant
    given `owned_items` (list/set of names). False otherwise.

    Allows the candidate to upgrade FROM an owned component (e.g. owning
    Bramble Vest does NOT make Thornmail redundant - Thornmail is the
    upgrade path).
    """
    cand = _norm(item_name)
    owned_set = {_norm(x) for x in (owned_items or [])}
    if not cand or cand in owned_set:
        return True, "already owned"
    # Componentry: if the candidate's recipe lists a component the player
    # owns, that means we're upgrading - not redundant by exclusion.
    item_def = ITEMS.get(item_name) or COMPONENTS.get(item_name) or {}
    parts_lc = {_norm(p) for p in item_def.get("from", [])}
    for group_key, group in _load_exclusions().items():
        if cand not in group["items"]:
            continue
        cand_idx = group["items"].index(cand)
        for owned in owned_set:
            if owned == cand or owned not in group["items"]:
                continue
            # Recipe-component upgrade is always allowed.
            if owned in parts_lc:
                continue
            # upgrade_chain groups list items in component -> finished order.
            # A candidate later in the chain than the owned item is an upgrade.
            if group.get("upgrade_chain"):
                owned_idx = group["items"].index(owned)
                if cand_idx > owned_idx:
                    continue
            return True, f"{group_key}: owned {owned}"
    return False, ""


# =========================================================================
# BOOTS LIFECYCLE  (early buy -> mid upgrade -> endgame sell-for-X)
# =========================================================================

# Boot upgrades (post 14.x). Maps base boots -> upgrade name.
_BOOT_UPGRADES = {
    "Berserker's Greaves":     "Symbiotic Soles",
    "Plated Steelcaps":        "Crimson Lucidity",
    "Mercury's Treads":        "Forever Forward",
    "Sorcerer's Shoes":        "Echoing Flames",
    "Ionian Boots of Lucidity": "Crimson Lucidity",
    "Boots of Swiftness":      "Forever Forward",
    "Mobility Boots":          "Forever Forward",
}


def boots_phase(level, gold, owned_count, owned_items=None,
                quest_boots_owned=False):
    """Return one of: 'skip', 'buy_basic', 'upgrade', 'consider_sell',
    'sell_for_quest', 'ok'.

    - skip: very early; would benefit more from a damage component
            (level 1-2, gold < 300)
    - buy_basic: 300g basic Boots OR 1100g specialized boots fits the breakpoint
    - upgrade: level 11+ AND have ~3000g free for Symbiotic/Crimson/Forever
    - consider_sell: 6 items + boots filled, level 16+, late game - selling
                     boots for a 6th legendary often increases survivability
                     or DPS more
    - sell_for_quest: lane quest is complete -> invisible "quest boots" are
                      active -> bought boots are now redundant. Sell them
                      anytime; even before full build this frees a slot
                      for a damage/defensive item without losing movement.

    Note: TRINKET is never suggested for sale. Trinkets occupy a separate
    slot the game refuses to make purchasable; the inventory slot count
    excludes the trinket.
    """
    owned_items = owned_items or []
    base_boots = {_norm(b) for b in _BOOT_UPGRADES} | {"boots"}
    upgrade_set = {_norm(u) for u in _BOOT_UPGRADES.values()}
    boot_set = base_boots | upgrade_set
    has_boots = any(_norm(x) in boot_set for x in owned_items)
    has_upgraded = any(_norm(x) in upgrade_set for x in owned_items)

    # Quest-completed: visible boots are obsolete because the invisible
    # quest-boots already give the movement bonus. Sell the bought pair
    # to free a slot regardless of game stage.
    if quest_boots_owned and has_boots:
        return "sell_for_quest"

    if level <= 2 and gold < 300 and not has_boots:
        return "skip"
    if not has_boots:
        return "buy_basic"
    if has_upgraded:
        if owned_count >= 6 and level >= 16:
            return "consider_sell"
        return "ok"
    if level >= 11 and gold >= 750 and not has_upgraded:
        return "upgrade"
    return "ok"


def endgame_boots_swap_target(champion, enemy_champs, owned_items):
    """When the player is full-build (6 items + boots) and considering selling
    boots, pick a 6th-item swap target based on enemy threats and champion.
    Returns (item_name, reason) or (None, '') if no clear winner.
    """
    threats = analyze_enemy_comp(enemy_champs or [])
    owned_set = {_norm(x) for x in (owned_items or [])}

    # Priority order: highest functional gain first
    # 1. Anti-CC if heavy CC and no QSS-class item
    qss_owned = any(o in owned_set for o in
                    ("quicksilver sash", "mercurial scimitar", "banshee's veil"))
    if threats.get("need_qss") and not qss_owned:
        return ("Mercurial Scimitar", "heavy enemy CC, no cleanse owned")
    # 2. Anti-heal if not satisfied
    ah_ad = {"executioner's calling", "mortal reminder", "chempunk chainsword",
             "morellonomicon"}
    if threats.get("need_anti_heal") and not (owned_set & ah_ad):
        return ("Mortal Reminder", "enemy heavy healing, no AD anti-heal owned")
    # 3. Anti-burst Maw if no lifeline
    lifeline = {"maw of malmortius", "sterak's gage", "hexdrinker"}
    if threats.get("need_anti_burst") and not (owned_set & lifeline):
        return ("Maw of Malmortius", "enemy burst, no lifeline owned")
    # 4. Armor pen for AD vs tanks
    pen = {"lord dominik's regards", "mortal reminder"}
    if threats.get("need_armor_pen") and not (owned_set & pen):
        return ("Lord Dominik's Regards", "enemy stacking armor, no AD pen owned")
    # 5. Default: replace boots with a defensive (Banshee's Veil for AP threats,
    #    Guardian Angel for general survivability).
    enemy_str = " ".join(enemy_champs or []).lower()
    if any(c in enemy_str for c in ("syndra", "ahri", "veigar", "ekko", "zoe")):
        if "banshee's veil" not in owned_set:
            return ("Banshee's Veil", "AP burst threats, default defensive")
    if "guardian angel" not in owned_set:
        return ("Guardian Angel", "default endgame survivability")
    return (None, "no clear swap target")


# =========================================================================
# PURCHASE ADVISOR
# =========================================================================

def _get_all_components(item_name):
    item = ITEMS.get(item_name) or COMPONENTS.get(item_name)
    if not item:
        return []
    parts = item.get("from", [])
    if not parts:
        return [(item_name, item["cost"])]
    result = []
    for part in parts:
        result.extend(_get_all_components(part))
    return result


def _component_cost_remaining(item_name, owned_items):
    item = ITEMS.get(item_name) or COMPONENTS.get(item_name)
    if not item:
        return 9999
    if item_name in owned_items:
        return 0
    parts = item.get("from", [])
    combine = item.get("combine", 0)
    if not parts:
        return item["cost"]
    cost = combine
    for part in parts:
        if part in owned_items:
            continue
        cost += _component_cost_remaining(part, owned_items)
    return cost


def get_purchase_advice(champion, current_items, gold, enemy_champs,
                        ally_champs=None, enemy_items_flat=None, game_mode="CLASSIC",
                        is_dead=False, death_timer=0, gold_per_sec=0):
    """
    Main entry point. Returns dict with build_path, next_item, buy_now, display.
    """
    # Decide "unknown" on the table, not on the resolved list: resolve_build
    # also returns [] for a KNOWN champion whose every curated item is owned
    # or exclusion-redundant, and that case is BUILD COMPLETE (below), not
    # an unknown champion. The frozen caller app/_game_lifecycle.py renders
    # this display string verbatim.
    if champion not in CHAMPION_BUILDS:
        return {"display": "Unknown champion", "build_path": [], "buy_now": []}
    build = resolve_build(champion, enemy_champs, current_items)

    owned = set(current_items or [])
    owned_normalized = {n.lower().replace("'", "").replace(" ", "") for n in owned}

    remaining_build = []
    for item in build:
        norm = item.lower().replace("'", "").replace(" ", "")
        if norm not in owned_normalized:
            remaining_build.append(item)

    if not remaining_build:
        return {"display": "BUILD COMPLETE", "build_path": build, "buy_now": [], "next_item": None}

    next_item = remaining_build[0]
    next_cost = _component_cost_remaining(next_item, owned)

    buy_now = []

    def _get_buyable_parts(item_name, owned):
        item = ITEMS.get(item_name) or COMPONENTS.get(item_name)
        if not item:
            return []
        parts = item.get("from", [])
        result = []
        for part in parts:
            if part in owned:
                continue
            p = ITEMS.get(part) or COMPONENTS.get(part)
            if not p:
                continue
            cost = _component_cost_remaining(part, owned)
            result.append((part, cost))
            sub_parts = p.get("from", [])
            for sp in sub_parts:
                if sp not in owned:
                    sp_data = COMPONENTS.get(sp)
                    if sp_data:
                        result.append((sp, sp_data["cost"]))
        return result

    if gold >= next_cost:
        buy_now.append((next_item, next_cost, True))
    else:
        buyable = _get_buyable_parts(next_item, owned)
        seen = {}
        for name, cost in buyable:
            if name not in seen or cost > seen[name]:
                seen[name] = cost
        buyable = [(n, c) for n, c in seen.items()]
        buyable.sort(key=lambda x: x[1], reverse=True)
        spent = 0
        for name, cost in buyable:
            if spent + cost <= gold:
                buy_now.append((name, cost, False))
                spent += cost

    projected_gold = gold
    if is_dead and death_timer > 0:
        projected_gold = gold + int(death_timer * gold_per_sec)

    path_names = [_short_name(i) for i in remaining_build[:5]]
    lines = [
        "PATH: " + " -> ".join(path_names),
        "",
        f">> {next_item}",
    ]
    if gold >= next_cost:
        lines.append(f"  BUY NOW ({next_cost}g)")
    else:
        lines.append(f"  Need {next_cost}g (have {gold}g, -{next_cost - gold}g)")
    if buy_now and not (len(buy_now) == 1 and buy_now[0][2]):
        for name, cost, is_complete in buy_now:
            if not is_complete:
                lines.append(f"  -> {name} ({cost}g)")
    if is_dead and death_timer > 0 and projected_gold > gold:
        lines.append(f"  Respawn gold: ~{projected_gold}g")

    return {
        "display": "\n".join(lines),
        "build_path": build,
        "remaining": remaining_build,
        "next_item": next_item,
        "next_cost": next_cost,
        "buy_now": buy_now,
        "gold": gold,
    }


def _short_name(item_name):
    shorts = {
        "Berserker's Greaves": "Boots", "Kraken Slayer": "Kraken",
        "Yun Tal Wildarrows": "Yun Tal", "Hexoptics C44": "Hexoptics",
        "Phantom Dancer": "PD", "Runaan's Hurricane": "Runaan's",
        "Rapid Firecannon": "RFC", "Statikk Shiv": "Shiv",
        "Infinity Edge": "IE", "Lord Dominik's Regards": "LDR",
        "Mortal Reminder": "Mortal", "Bloodthirster": "BT",
        "Immortal Shieldbow": "Shieldbow", "Guardian Angel": "GA",
        "Mercurial Scimitar": "QSS", "Blade of the Ruined King": "BotRK",
    }
    return shorts.get(item_name, item_name)


if __name__ == "__main__":
    # Quick smoke tests
    r = get_purchase_advice("Jinx", ["Doran's Blade"], 784, ["Caitlyn", "Seraphine", "Wukong"])
    print("Jinx @ 784g:", r["display"])
    ctx = get_matchup_context(["Malphite", "Warwick", "Soraka"])
    print("Matchup ctx:", ctx)
