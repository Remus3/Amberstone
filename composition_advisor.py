"""
composition_advisor.py
Analyzes team compositions to validate and recommend items.

Key functions:
  enemy_damage_profile()   — % AD vs % AP of the enemy team
  validate_item()          — flags bad purchases (Collector vs tanks, MR vs AD team, etc.)
  suggest_items()          — ordered list of recommended items with reason
  aram_item_priority()     — ARAM-specific item priorities

Used by item_advisor.py for context-aware build advice.
"""

from champion_profiles import (
    CHAMPIONS, TANKS, FIGHTERS, AD_CHAMPS, AP_CHAMPS,
    HYBRID_CHAMPS, SUSTAIN_CHAMPS, MANA_CHAMPS,
)

# ── Item property maps ─────────────────────────────────────────────────────────

# Items that provide MR — buying these vs AD-heavy team is inefficient
MR_ITEMS = {
    "Abyssal Mask", "Banshee's Veil", "Force of Nature", "Hollow Radiance",
    "Kaenic Rookern", "Mercury's Treads", "Maw of Malmortius",
    "Mercurial Scimitar", "Null-Magic Mantle", "Negatron Cloak",
    "Spirit Visage", "Sterak's Gage",
}

# Items that provide armor — buying these vs AP-heavy team is inefficient
ARMOR_ITEMS = {
    "Bramble Vest", "Chain Vest", "Dead Man's Plate", "Frozen Heart",
    "Gargoyle Stoneplate", "Plated Steelcaps", "Randuin's Omen",
    "Sunfire Aegis", "Thornmail", "Warden's Mail", "Warmog's Armor",
}

# Items with lethality (armor pen) — poor vs HP-stacking / low-armor targets
LETHALITY_ITEMS = {
    "Axiom Arc", "Duskblade of Draktharr", "Edge of Night",
    "Ghostblade", "Opportunity", "Profane Hydra",
    "Serpent's Fang", "Serylda's Grudge", "Youmuu's Ghostblade",
    "The Collector",
}

# Items with % armor pen (better vs tanks)
ARMOR_PEN_ITEMS = {
    "Lord Dominik's Regards", "Mortal Reminder", "Serylda's Grudge",
    "Last Whisper", "Void Staff",  # Void Staff is % magic pen
}

# Items that provide mana — usually bad on non-mana champions
MANA_ITEMS = {
    "Archangel's Staff", "Banshee's Veil", "Catalyst of Aeons",
    "Caulfield's Warhammer", "Essence Reaver", "Frozen Heart",
    "Hextech Rocketbelt", "Lost Chapter", "Luden's Tempest",
    "Luden's Companion", "Manamune", "Muramana",
    "Rod of Ages", "Seraph's Embrace", "Sheen",
    "Tear of the Goddess", "Trinity Force",
}

# Grievous Wounds items
GW_ITEMS = {
    "Chempunk Chainsword", "Executioner's Calling", "Mortal Reminder",
    "Shadowflame", "Thornmail", "Oblivion Orb",
}

# Items particularly strong in ARAM (constant combat, no recalling)
ARAM_STRONG = {
    "Immortal Shieldbow", "Ravenous Hydra", "Heartsteel",
    "Warmog's Armor", "Spirit Visage", "Death's Dance", "Sterak's Gage",
}


# ── Damage profile ─────────────────────────────────────────────────────────────

def enemy_damage_profile(enemy_champs: list) -> dict:
    """
    Return {'ad': float 0-1, 'ap': float 0-1, 'mixed': bool,
            'ad_count': int, 'ap_count': int, 'tank_count': int,
            'sustain_count': int}
    for an enemy team.
    """
    ad = ap = tanks = sustain = 0
    total = max(1, len(enemy_champs))

    for name in enemy_champs:
        data = CHAMPIONS.get(name, {})
        dmg = data.get("dmg", "ad")
        role = data.get("role", "fighter")

        if dmg == "ad":
            ad += 1.0
        elif dmg == "ap":
            ap += 1.0
        elif dmg == "hybrid":
            ad += 0.5
            ap += 0.5

        if role == "tank":
            tanks += 1
        elif role == "fighter" and dmg != "ap":
            tanks += 0.5     # fighters are semi-tanky

        if data.get("sustain", False):
            sustain += 1

    return {
        "ad":            round(ad / total, 2),
        "ap":            round(ap / total, 2),
        "mixed":         0.3 <= (ad / total) <= 0.7,
        "ad_count":      int(ad),
        "ap_count":      int(ap),
        "tank_count":    round(tanks),
        "sustain_count": sustain,
    }


# ── Item validation ────────────────────────────────────────────────────────────

def validate_item(item_name: str, champion: str,
                  enemy_champs: list, ally_champs: list,
                  current_items: list, game_mode: str = "CLASSIC") -> tuple:
    """
    Returns (ok: bool, warning: str).
    ok=False means the item is suboptimal enough to flag.
    """
    profile  = enemy_damage_profile(enemy_champs)
    ad_pct   = profile["ad"]
    ap_pct   = profile["ap"]
    tanks    = profile["tank_count"]
    has_sustain = profile["sustain_count"] >= 2
    champ_data = CHAMPIONS.get(champion, {})
    item_lower = item_name.lower()
    is_aram  = "ARAM" in game_mode

    # ── Mana items on non-mana champion ────────────────────────────────
    if any(m.lower() in item_lower for m in MANA_ITEMS):
        needs_mana = champ_data.get("mana", True)  # default True if unknown
        if not needs_mana:
            return False, (
                f"{champion} doesn't use mana — {item_name} wastes its mana stats. "
                f"Replace with a stat-efficient alternative."
            )

    # ── Heavy MR vs AD-heavy team ───────────────────────────────────────
    if any(m.lower() in item_lower for m in MR_ITEMS):
        if ad_pct >= 0.75:
            return False, (
                f"Enemy team is {ad_pct:.0%} AD — {item_name} provides MR with minimal value. "
                f"Build armor (Thornmail, Randuin's, Frozen Heart) instead."
            )

    # ── Heavy armor vs AP-heavy team ────────────────────────────────────
    if any(m.lower() in item_lower for m in ARMOR_ITEMS) and item_name not in ("Warmog's Armor",):
        if ap_pct >= 0.75:
            return False, (
                f"Enemy team is {ap_pct:.0%} AP — {item_name} provides armor with minimal value. "
                f"Build MR (Banshee's, Force of Nature, Spirit Visage) instead."
            )

    # ── Collector/lethality vs tanks ────────────────────────────────────
    if any(m.lower() in item_lower for m in LETHALITY_ITEMS):
        if tanks >= 3:
            return False, (
                f"{item_name} has lethality (flat armor pen) — poor vs {tanks} tanks. "
                f"Build Last Whisper, Black Cleaver, or Void Staff for % armor penetration instead."
            )

    # ── No Grievous Wounds vs heavy healing ─────────────────────────────
    # (Not a flag but a reminder — handled in suggestions)

    # ── ARAM: mana items double-check ──────────────────────────────────
    if is_aram and any(m.lower() in item_lower for m in {"Tear of the Goddess", "Manamune", "Archangel's Staff"}):
        needs_mana = champ_data.get("mana", True)
        if not needs_mana:
            return False, (
                f"ARAM: {item_name} is a mana item but {champion} doesn't use mana. "
                f"Every slot matters in ARAM — pick a combat-relevant item."
            )

    return True, ""


# ── Item suggestions ────────────────────────────────────────────────────────────

def suggest_items(champion: str, enemy_champs: list, ally_champs: list,
                  current_items: list, gold: int,
                  game_mode: str = "CLASSIC") -> list:
    """
    Returns list of (item_name, reason) tuples — ordered by priority.
    These are suggestions based on what's missing given the composition.
    """
    profile    = enemy_damage_profile(enemy_champs)
    ad_pct     = profile["ad"]
    ap_pct     = profile["ap"]
    tanks      = profile["tank_count"]
    has_sustain = profile["sustain_count"] >= 2
    champ_data = CHAMPIONS.get(champion, {})
    role       = champ_data.get("role", "marksman")
    dmg        = champ_data.get("dmg", "ad")
    is_aram    = "ARAM" in game_mode

    # Normalise current items to lowercase for lookup
    owned_lower = {i.lower() for i in (current_items or [])}
    has_gw = any(g.lower() in owned_lower for g in GW_ITEMS)

    suggestions = []

    # ── Grievous Wounds ─────────────────────────────────────────────────
    if has_sustain and not has_gw:
        if dmg in ("ad", "hybrid"):
            suggestions.append(("Mortal Reminder",
                f"Enemy has {profile['sustain_count']} healing champions — Grievous Wounds is mandatory"))
        else:
            suggestions.append(("Shadowflame",
                f"Enemy has {profile['sustain_count']} healing champions — Grievous Wounds is mandatory"))

    # ── Anti-tank items ─────────────────────────────────────────────────
    if tanks >= 2:
        if dmg in ("ad", "hybrid") and not any("lord" in i or "mortal" in i or "black cleaver" in i
                                                 for i in owned_lower):
            suggestions.append(("Last Whisper / Lord Dominik's Regards",
                f"{tanks} tanks in enemy comp — % armor penetration is required"))
        elif dmg == "ap" and not any("void staff" in i for i in owned_lower):
            suggestions.append(("Void Staff",
                f"{tanks} tanks in enemy comp — % magic penetration is required"))

    # ── Defensive items based on enemy damage type ──────────────────────
    if ap_pct >= 0.6 and role not in ("marksman", "assassin"):
        if not any(m.lower() in owned_lower for m in ("banshee", "spirit visage", "force of nature")):
            if champ_data.get("sustain"):
                suggestions.append(("Spirit Visage",
                    f"Amplifies your healing vs {ap_pct:.0%} AP team"))
            else:
                suggestions.append(("Banshee's Veil",
                    f"Spellshield blocks initiation vs {ap_pct:.0%} AP team"))

    if ad_pct >= 0.6 and role not in ("marksman", "mage"):
        if not any(m.lower() in owned_lower for m in ("thornmail", "frozen heart", "randuin")):
            has_adc_enemy = any(CHAMPIONS.get(e, {}).get("role") == "marksman" for e in enemy_champs)
            if has_adc_enemy:
                suggestions.append(("Thornmail",
                    f"Reflect damage to enemy ADC; Grievous Wounds for their healers vs {ad_pct:.0%} AD team"))
            else:
                suggestions.append(("Frozen Heart",
                    f"Reduces nearby attack speed vs {ad_pct:.0%} AD team"))

    # ── ARAM-specific extras ────────────────────────────────────────────
    if is_aram:
        if not any("warmog" in i for i in owned_lower) and role == "tank":
            suggestions.append(("Warmog's Armor",
                "ARAM tanks need Warmog's for the HP regen threshold"))
        if role in ("fighter", "tank") and not any("death's dance" in i or "sterak" in i
                                                     for i in owned_lower) and dmg == "ad":
            suggestions.append(("Death's Dance / Sterak's Gage",
                "ARAM: sustained fights reward damage-reducing defensive items"))

    return suggestions[:4]  # top 4 suggestions


# ── Full composition context string ────────────────────────────────────────────

def comp_context_str(champion: str, current_items: list,
                     enemy_champs: list, ally_champs: list,
                     enemy_items_flat: list, game_mode: str = "CLASSIC") -> str:
    """
    Returns a short formatted string suitable for injecting into the coaching prompt.
    Covers: enemy damage profile, bad-item warnings, top suggestions.
    """
    profile  = enemy_damage_profile(enemy_champs)
    ad_pct   = profile["ad"]
    ap_pct   = profile["ap"]
    tanks    = profile["tank_count"]
    sustain  = profile["sustain_count"]

    lines = []

    # Damage profile
    if ad_pct >= 0.75:
        lines.append(f"Enemy: {ad_pct:.0%} AD — prioritize armor items")
    elif ap_pct >= 0.75:
        lines.append(f"Enemy: {ap_pct:.0%} AP — prioritize MR items")
    else:
        lines.append(f"Enemy: mixed {ad_pct:.0%} AD / {ap_pct:.0%} AP")

    if tanks >= 3:
        lines.append(f"  {tanks} tanks — % armor/magic pen is required")
    if sustain >= 2:
        lines.append(f"  {sustain} healing champions — Grievous Wounds needed")

    # Item validation on current build
    warnings = []
    for item in (current_items or []):
        ok, warn = validate_item(item, champion, enemy_champs, ally_champs,
                                  current_items, game_mode)
        if not ok:
            warnings.append(warn)

    if warnings:
        lines.append("Build warnings:")
        for w in warnings[:2]:
            lines.append(f"  ✗ {w}")

    # Suggestions
    suggestions = suggest_items(champion, enemy_champs, ally_champs,
                                 current_items, 0, game_mode)
    if suggestions:
        lines.append("Item priority:")
        for item, reason in suggestions[:2]:
            lines.append(f"  → {item}: {reason}")

    return "\n".join(lines)
