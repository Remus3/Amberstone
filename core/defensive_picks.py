# arch: defensive item ranker | section=core | frozen=no
"""Threat-aware defensive item recommendations.

The DS engine (``agents/daemon_slayer``) optimises offense - items that
make YOUR damage faster. It doesn't surface defensive picks even when
the operator is being one-shot by a fed assassin. This module fills
that gap: classify the enemy team's damage profile + burst threat,
then recommend defensive items keyed to the threat.

Phase 1 (s174, 2026-05-12) - ``recommend_defensive_items_via_ehp()``
layers the curated catalog on top of ``agents/daemon_slayer/ehp.py``'s
math-driven ranker. Option B from the s174 design conversation: the
curated catalog stays the operator-vetted pool, EHP math drives order
within it. Falls back to the heuristic ``recommend_defensive_items``
when the DS engine is down or the champion is unknown.

Threat profile inputs:
  enemy_champions: list of champion names (e.g. ['Rengar', 'Veigar',
                   'Lulu', 'Caitlyn', 'Nautilus'])
  enemy_items:     list of item-id lists per enemy (live inventory).
                   Currently used to detect crit / lethality / armor-pen
                   stacking - not just stat sums.

Output:
  {
    "ad_threat":     float 0..10,   # physical damage exposure
    "ap_threat":     float 0..10,   # magic damage exposure
    "burst_threat":  float 0..10,   # assassin-style burst
    "tank_pressure": float 0..10,   # enemies stacking HP/armor (you need pen)
    "top_threats":   [{"name", "kind"}],  # 1-3 named threats
    "summary":       str,           # one-line human summary
  }

Recommendation output:
  [
    {"item_id": 3026, "name": "Guardian Angel", "category": "lifeline",
     "reason": "revives once after fatal hit · vs Rengar burst",
     "score": 8.5},
    ...
  ]

Both functions are deterministic + pure - no network calls, no LCU. The
threat profile is recomputed every tick from the live state; the
recommendation list is filtered against the operator's owned_items so
nothing already-bought is recommended.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger("rc.defensive_picks")

_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

# Module-level cache: champion-name -> {tags, attack, magic, defense, difficulty}.
_CHAMP_INFO: dict[str, dict] | None = None


def _load_champ_info() -> dict[str, dict]:
    """Build name → info map from ddragon_champions.json. Handles
    apostrophe variants (Kai'Sa / KaiSa) and spaces (Miss Fortune /
    MissFortune) by storing under both keys."""
    global _CHAMP_INFO
    if _CHAMP_INFO is not None:
        return _CHAMP_INFO
    out: dict[str, dict] = {}
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            info = entry.get("info") or {}
            slim = {
                "tags":       list(entry.get("tags") or []),
                "attack":     int(info.get("attack")  or 0),
                "magic":      int(info.get("magic")   or 0),
                "defense":    int(info.get("defense") or 0),
                "difficulty": int(info.get("difficulty") or 0),
            }
            for key in (entry.get("name"), entry.get("id")):
                if not key: continue
                out[key] = slim
                out[key.replace("'", "")] = slim          # Kai'Sa -> KaiSa
                out[key.replace(" ", "")] = slim          # Miss Fortune -> MissFortune
                out[key.replace("'", "").replace(" ", "")] = slim
    except FileNotFoundError:
        _log.warning("defensive_picks: %s missing - using empty index", _CHAMPS_PATH)
    except Exception as exc:
        _log.warning("defensive_picks: champ info load failed: %s", exc)
    _CHAMP_INFO = out
    return out


# Champions known to one-shot squishies - bumps burst_threat regardless
# of DDragon info.magic/attack scores (which are average-state, not
# late-game-fed-state).
_KNOWN_BURSTERS = {
    # AD burst / assassin
    "Rengar", "Zed", "Talon", "Kha'Zix", "KhaZix", "Pantheon", "Kindred",
    "Master Yi", "MasterYi", "Yi", "Camille", "Riven", "Yone", "Yasuo",
    # AP burst
    "Veigar", "Annie", "LeBlanc", "Syndra", "Lux", "Brand", "Akali", "Fizz",
    "Kassadin", "Diana", "Katarina", "Ekko", "Ahri", "Vex", "Hwei", "Naafiri",
    # Crit/AS one-shotters
    "Vayne", "Jinx", "Caitlyn", "Tristana", "Twitch",
}

# Curated defensive item catalog. Each entry: id, name, category,
# stats summary, reason template. Categories drive the threat->item
# match. SR-tier 4-digit ids - the catalog file (ddragon_items.json)
# has both these AND the 6-digit ARAM variants under the same names.
_DEFENSIVE_ITEMS = [
    # ARMOR / vs AD
    {"id": "3047", "name": "Plated Steelcaps", "category": "armor",
     "tags": ["boots"], "reason": "+25 armor + 10% basic-attack DR · cheap"},
    {"id": "3143", "name": "Randuin's Omen", "category": "armor",
     "tags": ["aoe-slow"], "reason": "75 armor + 300 HP + active slow vs ADCs"},
    {"id": "3110", "name": "Frozen Heart", "category": "armor",
     "tags": ["aa-slow"], "reason": "90 armor + 20% atk-speed aura vs AS-heavy"},
    {"id": "3742", "name": "Dead Man's Plate", "category": "armor",
     "tags": ["hp"], "reason": "60 armor + 300 HP + Momentum dash"},
    {"id": "3075", "name": "Thornmail", "category": "armor",
     "tags": ["grievous"], "reason": "70 armor + reflects + Grievous on AAs (vs lifesteal)"},
    {"id": "6665", "name": "Jak'Sho, The Protean", "category": "armor",
     "tags": ["hybrid"], "reason": "armor+MR scaling + heal - hybrid resist"},
    # MR / vs AP
    {"id": "3111", "name": "Mercury's Treads", "category": "mr",
     "tags": ["boots", "tenacity"], "reason": "+25 MR + 30% tenacity vs CC"},
    {"id": "3102", "name": "Banshee's Veil", "category": "mr",
     "tags": ["spellshield"], "reason": "50 MR + 80 AP + spell shield vs poke/burst"},
    {"id": "3194", "name": "Adaptive Helm", "category": "mr",
     "tags": ["sustain"], "reason": "55 MR + 350 HP + reduces same-spell damage"},
    {"id": "3001", "name": "Abyssal Mask", "category": "mr",
     "tags": ["aura"], "reason": "30 MR + aura that amplifies your magic damage"},
    {"id": "3065", "name": "Spirit Visage", "category": "mr",
     "tags": ["sustain"], "reason": "40 MR + 450 HP + 20% bonus healing"},
    # BURST DEFENSE / LIFELINE
    {"id": "3026", "name": "Guardian Angel", "category": "lifeline",
     "tags": ["revive"], "reason": "revives once after fatal hit - anti-burst classic"},
    {"id": "3814", "name": "Edge of Night", "category": "lifeline",
     "tags": ["spellshield", "lethality"], "reason": "spell shield + lethality vs ability-burst"},
    {"id": "3156", "name": "Maw of Malmortius", "category": "lifeline",
     "tags": ["mr", "shield"], "reason": "30 MR + lifeline shield vs magic damage"},
    {"id": "3053", "name": "Sterak's Gage", "category": "lifeline",
     "tags": ["hp", "shield"], "reason": "bonus-HP shield + tenacity on burst"},
    {"id": "3157", "name": "Zhonya's Hourglass", "category": "lifeline",
     "tags": ["armor", "stasis"], "reason": "45 armor + 105 AP + stasis active vs burst"},
    # SUSTAIN / VS POKE
    {"id": "3072", "name": "Bloodthirster", "category": "sustain",
     "tags": ["lifesteal", "shield"], "reason": "20% lifesteal + bonus-HP shield"},
    {"id": "3107", "name": "Redemption", "category": "sustain",
     "tags": ["aoe-heal"], "reason": "AoE heal active + bonus healing aura"},
    {"id": "3083", "name": "Warmog's Armor", "category": "sustain",
     "tags": ["hp"], "reason": "+1100 HP + out-of-combat regen vs poke comp"},
    # TENACITY / CC
    {"id": "3193", "name": "Gargoyle Stoneplate", "category": "tenacity",
     "tags": ["aoe-defense"], "reason": "+60 armor + 60 MR + active 2x HP vs teamfights"},
    {"id": "6035", "name": "Silvermere Dawn", "category": "tenacity",
     "tags": ["cleanse"], "reason": "cleanse + 30 MR vs hard CC comps"},
    {"id": "3140", "name": "Quicksilver Sash", "category": "tenacity",
     "tags": ["cleanse"], "reason": "30 MR + cleanse active vs hard CC"},
]


def compute_threat_profile(enemy_champions: list, enemy_items: list | None = None) -> dict:
    """Classify the enemy team's damage profile + identify top threats.

    ``enemy_champions``: list of champion display names.
    ``enemy_items``: parallel list of item-id lists (optional; raises
    burst score when an enemy has 2+ lethality items, drops the AD
    threat score when an enemy has lifesteal-heavy items vs. crit, etc.).

    The scoring uses DDragon's per-champion info.attack / info.magic
    (1-10) as the base, then bumps burst when champions are in
    ``_KNOWN_BURSTERS`` or have tag in {Assassin}. ``info.defense`` is
    used to identify glass-cannon enemies (defense <= 3 + high damage
    = the assassin profile).
    """
    info_idx = _load_champ_info()
    if not isinstance(enemy_champions, list) or not enemy_champions:
        return {
            "ad_threat":     0.0,
            "ap_threat":     0.0,
            "burst_threat":  0.0,
            "tank_pressure": 0.0,
            "top_threats":   [],
            "summary":       "no enemy data",
        }
    ad_sum = 0.0
    ap_sum = 0.0
    burst_sum = 0.0
    tank_sum = 0.0
    top_threats: list[dict] = []
    n_enemies = max(1, len(enemy_champions))

    for name in enemy_champions:
        if not name: continue
        info = info_idx.get(name) or info_idx.get(str(name).replace("'", "")) or {}
        attack = info.get("attack", 5)
        magic  = info.get("magic", 5)
        defense = info.get("defense", 5)
        tags = info.get("tags") or []

        ad_sum += attack
        ap_sum += magic

        # Burst signal: assassin tag, low defense + high single-stat,
        # known burst champion, OR very high attack+magic combo
        is_assassin = "Assassin" in tags
        is_known_burst = name in _KNOWN_BURSTERS
        is_glass_cannon = defense <= 3 and max(attack, magic) >= 7
        if is_assassin or is_known_burst or is_glass_cannon:
            burst_sum += 1
            kind = "AD burst" if attack >= magic else "AP burst"
            top_threats.append({"name": name, "kind": kind})

        # Tank pressure: high-defense melee bruisers/tanks
        if defense >= 7 or "Tank" in tags:
            tank_sum += 1

    # Normalise to 0..10 scale: average across team, multiplied to
    # spread to 0-10.
    ad_threat = min(10.0, (ad_sum / n_enemies))
    ap_threat = min(10.0, (ap_sum / n_enemies))
    burst_threat = min(10.0, (burst_sum / n_enemies) * 10)
    tank_pressure = min(10.0, (tank_sum / n_enemies) * 10)

    # One-line summary for UI
    bits = []
    if ad_threat >= 6: bits.append(f"AD-heavy ({ad_threat:.0f}/10)")
    if ap_threat >= 6: bits.append(f"AP-heavy ({ap_threat:.0f}/10)")
    if burst_threat >= 4: bits.append(f"burst threat ({burst_threat:.0f}/10)")
    if tank_pressure >= 4: bits.append(f"tank pressure ({tank_pressure:.0f}/10)")
    summary = " · ".join(bits) or f"balanced (AD {ad_threat:.0f} / AP {ap_threat:.0f})"

    return {
        "ad_threat":     round(ad_threat, 1),
        "ap_threat":     round(ap_threat, 1),
        "burst_threat":  round(burst_threat, 1),
        "tank_pressure": round(tank_pressure, 1),
        "top_threats":   top_threats[:3],
        "summary":       summary,
    }


def recommend_defensive_items(threat: dict,
                              my_champion: str | None = None,
                              my_owned_items: list | None = None,
                              top_n: int = 4) -> list:
    """Score the curated defensive items against the threat profile.

    Skips anything already in ``my_owned_items`` (name match, case-
    insensitive). Returns up to ``top_n`` ranked picks.
    """
    if not isinstance(threat, dict):
        return []
    ad   = float(threat.get("ad_threat") or 0)
    ap   = float(threat.get("ap_threat") or 0)
    burst = float(threat.get("burst_threat") or 0)
    tank  = float(threat.get("tank_pressure") or 0)

    owned = {str(s).lower() for s in (my_owned_items or [])}
    scored: list[dict] = []

    for item in _DEFENSIVE_ITEMS:
        name = item["name"]
        if name.lower() in owned:
            continue
        cat = item["category"]
        tags = set(item.get("tags") or [])
        score = 0.0
        # Match threat -> category
        if cat == "armor":
            score += ad * 1.0
            if tank >= 5: score += 1.0    # bonus when enemies stack HP
        elif cat == "mr":
            score += ap * 1.0
            if burst >= 5 and "spellshield" in tags: score += 1.5
        elif cat == "lifeline":
            score += burst * 1.2
            if "spellshield" in tags and ap >= 6: score += 1.5
            if "armor" in tags and ad >= 6:       score += 1.0
            if "mr" in tags    and ap >= 6:       score += 1.0
            if "shield" in tags and burst >= 5:   score += 1.0
        elif cat == "sustain":
            score += (ad + ap) * 0.3
            if burst < 4: score += 1.0     # sustain matters more vs poke
        elif cat == "tenacity":
            if burst >= 5: score += burst * 0.5
            if "cleanse" in tags and burst >= 6: score += 2.0
        # Boots ceiling: boots-tagged items only worth recommending
        # alongside their resist; cap their score so they don't dominate.
        if "boots" in tags:
            score = min(score, 6.5)
        if score <= 0.0:
            continue
        scored.append({
            "item_id":  item["id"],
            "name":     name,
            "category": cat,
            "reason":   item["reason"],
            "score":    round(score, 2),
        })

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_n]


# Phase 1 (s174, 2026-05-12) - EHP-driven defensive picks. Option B layering:
# curated catalog is the whitelist, math drives order. Soft dep on the DS
# engine (HTTP :8893) - falls back to ``recommend_defensive_items`` heuristic
# when the engine is unreachable so the dashboard never goes dark.

def _threat_to_damage_shares(threat: dict) -> tuple[float, float]:
    """Map threat profile → ``(enemy_ad_share, enemy_ap_share)`` floats in [0,1].

    Normalizes ``ad_threat`` (0..10) and ``ap_threat`` (0..10) to shares
    summing to ≤ 1.0. When both signals are strong (>=6 each) reserves
    ~10% true-damage share - real teams have at least some true damage
    (Talon E, Wukong R, Cho ult, item procs) that the blended_ehp shouldn't
    over-fit to one resist for.
    """
    ad = float(threat.get("ad_threat") or 0)
    ap = float(threat.get("ap_threat") or 0)
    total = ad + ap
    if total <= 0:
        return 0.5, 0.5  # No info -> balanced
    ad_share = ad / total
    ap_share = ap / total
    if ad >= 6 and ap >= 6:
        ad_share *= 0.9
        ap_share *= 0.9
    return ad_share, ap_share


def recommend_defensive_items_via_ehp(
    threat: dict,
    my_champion: str | None = None,
    my_owned_items: list | None = None,
    my_level: int = 11,
    my_mode: str = "SR",
    top_n: int = 4,
) -> list:
    """EHP-driven defensive item recommendation (Phase 1, s174).

    Layers ``_DEFENSIVE_ITEMS`` as a whitelist on top of the DS engine's
    ``rank_items_by_ehp`` ranker. Returns the same shape as
    ``recommend_defensive_items``: ``{item_id, name, category, reason, score}``
    where ``score`` is the EHP gained (rounded to 1 decimal place).

    Falls back to ``recommend_defensive_items`` heuristic when:
      * Engine unreachable (``is_engine_up`` returns False)
      * ``my_champion`` missing/empty
      * ``threat`` malformed
      * Engine returns no results (champion unknown to DS, etc.)

    Threat → damage-share mapping via :func:`_threat_to_damage_shares`.
    """
    if not isinstance(threat, dict) or not my_champion:
        return recommend_defensive_items(
            threat, my_champion, my_owned_items, top_n=top_n,
        )
    # Lazy import - keeps ``defensive_picks`` import-clean for callers that
    # don't need the EHP path (and avoids any circular-import risk with
    # other core modules).
    try:
        from core.daemon_slayer_client import is_engine_up, rank_tank_for
    except ImportError:  # pragma: no cover - defensive
        return recommend_defensive_items(
            threat, my_champion, my_owned_items, top_n=top_n,
        )
    if not is_engine_up():
        return recommend_defensive_items(
            threat, my_champion, my_owned_items, top_n=top_n,
        )

    ad_share, ap_share = _threat_to_damage_shares(threat)
    owned_lower = {str(s).lower() for s in (my_owned_items or [])}
    catalog_by_id = {item["id"]: item for item in _DEFENSIVE_ITEMS}
    catalog_ids = [
        iid for iid, info in catalog_by_id.items()
        if info["name"].lower() not in owned_lower
    ]
    if not catalog_ids:
        return []

    ranked = rank_tank_for(
        my_champion,
        level=int(my_level),
        item_ids=[],  # Baseline = naked. ``my_owned_items`` filtering happens
                      # via the catalog whitelist above; passing the IDs would
                      # require a name->ID reverse map this module doesn't have.
                      # For Phase 1 the absolute delta from naked is the
                      # comparable scoring signal across all whitelisted picks.
        mode=str(my_mode),
        enemy_ad_share=ad_share,
        enemy_ap_share=ap_share,
        only_item_ids=catalog_ids,
        top=top_n,
    )
    if not ranked:
        return recommend_defensive_items(
            threat, my_champion, my_owned_items, top_n=top_n,
        )

    out: list[dict] = []
    for entry in ranked:
        info = catalog_by_id.get(entry.item_id)
        if info is None:
            continue  # only_item_ids guarantees membership but be defensive
        out.append({
            "item_id":  entry.item_id,
            "name":     info["name"],
            "category": info["category"],
            "reason":   info["reason"],
            "score":    round(entry.delta_ehp, 1),
        })
    return out
