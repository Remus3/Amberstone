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
                   Accepted for API compatibility but NOT read: the
                   profile is champion-only (lane-8 audit s144 cycle 233
                   measured the old "detects lethality stacking" claim
                   false - no line ever consumed the argument).

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
     "reason": "revives once after fatal hit * vs Rengar burst",
     "score": 8.5},
    ...
  ]

Both functions are deterministic + pure - no network calls, no LCU. The
threat profile is recomputed every tick from the live state; the
recommendation list is filtered against the operator's owned_items (item
ids, mode-mirror ids or names) so nothing already-bought is recommended.

Input contract (lane-8 audit, s144 cycle 233): every public function is
total over junk input. A non-string / blank enemy name is skipped and does
not count toward the team average; a non-numeric, non-finite or
out-of-range threat value reads as the nearest point of the documented
0..10 scale (junk = 0); one malformed DDragon entry costs that entry, not
the whole champion index.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from core.failed_load_gate import FailedLoadGate

_log = logging.getLogger("rc.defensive_picks")

_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

# Module-level cache: champion-name -> {tags, attack, magic, defense, difficulty}.
_CHAMP_INFO: dict[str, dict] | None = None
# RM-443: a failed load is NOT cached - retried after the gate's backoff and
# warned once per failure streak (core/failed_load_gate.py).
_CHAMP_INFO_GATE = FailedLoadGate()


def _stat(value: object) -> int:
    """One DDragon ``info`` stat -> int clamped to the documented 0..10.

    Junk (a non-numeric string, a list, a bool, NaN / inf) reads as 0 - the
    same value the loader always gave a MISSING stat - instead of raising
    and costing the whole index (pre-audit: one ``"attack": "high"`` row
    emptied it for every champion).
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, min(10, value))
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return 0
    if not isinstance(value, float) or not math.isfinite(value):
        return 0
    return max(0, min(10, int(value)))


def _slim_info(entry: dict) -> dict:
    info = entry.get("info")
    if not isinstance(info, dict):
        info = {}
    tags = entry.get("tags")
    if not isinstance(tags, (list, tuple)):
        tags = ()  # a bare string is NOT exploded into characters
    return {
        "tags":       [t for t in tags if isinstance(t, str)],
        "attack":     _stat(info.get("attack")),
        "magic":      _stat(info.get("magic")),
        "defense":    _stat(info.get("defense")),
        "difficulty": _stat(info.get("difficulty")),
    }


def _load_champ_info() -> dict[str, dict]:
    """Build name -> info map from ddragon_champions.json. Handles
    apostrophe variants (Kai'Sa / KaiSa) and spaces (Miss Fortune /
    MissFortune) by storing under both keys.

    A malformed ENTRY is dropped (counted, warned once per load); an
    unreadable or wrongly shaped FILE, or one with no usable entry, is a
    failed load: not cached, retried after the gate's backoff."""
    global _CHAMP_INFO
    if _CHAMP_INFO is not None:
        return _CHAMP_INFO
    if not _CHAMP_INFO_GATE.should_attempt():
        return {}
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        entries = list(data.values())
    except FileNotFoundError:
        if _CHAMP_INFO_GATE.record_failure():
            _log.warning("defensive_picks: %s missing - using empty index", _CHAMPS_PATH)
        return {}
    except Exception as exc:  # noqa: BLE001
        if _CHAMP_INFO_GATE.record_failure():
            _log.warning("defensive_picks: champ info load failed: %s", exc)
        return {}
    out: dict[str, dict] = {}
    dropped = 0
    for entry in entries:
        if not isinstance(entry, dict):
            dropped += 1
            continue
        slim = _slim_info(entry)
        indexed = False
        for key in (entry.get("name"), entry.get("id")):
            if not isinstance(key, str) or not key.strip():
                continue  # a non-string key raised AttributeError pre-audit
            out[key] = slim
            out[key.replace("'", "")] = slim          # Kai'Sa -> KaiSa
            out[key.replace(" ", "")] = slim          # Miss Fortune -> MissFortune
            out[key.replace("'", "").replace(" ", "")] = slim
            indexed = True
        if not indexed:
            dropped += 1
    if not out:
        if _CHAMP_INFO_GATE.record_failure():
            _log.warning("defensive_picks: %s has no usable champion entry - "
                         "using empty index", _CHAMPS_PATH)
        return {}
    if dropped:
        _log.warning("defensive_picks: dropped %d malformed champion entries",
                     dropped)
    _CHAMP_INFO_GATE.record_success()
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


def _name_key(name: str) -> str:
    """Case / punctuation-free champion key: "Kha'Zix", "Khazix" and
    "KhaZix" all read "khazix", so a DDragon id ("Leblanc") matches the
    display name ("LeBlanc") in the static burster list."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


_KNOWN_BURSTER_KEYS = frozenset(_name_key(n) for n in _KNOWN_BURSTERS)

# Curated defensive item catalog. Each entry: id, name, category,
# stats summary, reason template. Categories drive the threat->item
# match. SR-tier 4-digit ids - the catalog file (ddragon_items.json)
# has both these AND the 6-digit ARAM variants under the same names.
# Every id must be an SR-purchasable item of the same NAME in the tracked
# DDragon file (guard: tests/test_defensive_picks_true_audit_s144t233.py).
# Lane-8 audit s144 cycle 233, measured at DDragon 16.22.1: Abyssal Mask
# moved 3001 -> 8020 (3001 is now Evenshroud, unpurchasable - the strip
# showed the Evenshroud icon), and Adaptive Helm (3194), Gargoyle
# Stoneplate (3193) and Silvermere Dawn (6035) are no longer SR-purchasable,
# so they were dropped rather than recommended.
_DEFENSIVE_ITEMS = [
    # ARMOR / vs AD
    {"id": "3047", "name": "Plated Steelcaps", "category": "armor",
     "tags": ["boots"], "reason": "+25 armor + 10% basic-attack DR - cheap"},
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
    {"id": "8020", "name": "Abyssal Mask", "category": "mr",
     "tags": ["aura"], "reason": "45 MR + 350 HP + aura: nearby enemies take more magic damage"},
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
    {"id": "3140", "name": "Quicksilver Sash", "category": "tenacity",
     "tags": ["cleanse"], "reason": "30 MR + cleanse active vs hard CC"},
]


def _scale(value: object) -> float:
    """A threat value -> float on the documented 0..10 scale.

    Junk (non-numeric, NaN, inf, a list) reads 0.0; out-of-range clamps.
    Pre-audit a string raised ValueError and NaN / inf flowed into the
    scores, where ``json.dumps`` writes the bare ``NaN`` / ``Infinity``
    tokens a browser ``JSON.parse`` rejects."""
    if isinstance(value, bool):
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(f):
        return 0.0
    return max(0.0, min(10.0, f))


def _top_n(value: object, default: int = 4) -> int:
    """``top_n`` -> a non-negative int; a non-int uses ``default``.
    Pre-audit a negative value sliced from the END (``[:-1]`` = all but
    the last pick) and a string raised TypeError."""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


def _canonical_id(item_id: str) -> str:
    try:
        from core.build_planner.kit_synergy import canonical_item_id
    except ImportError:  # pragma: no cover - planner package absent
        return item_id
    return canonical_item_id(item_id) or item_id


def _owned_keys(my_owned_items: object) -> set[str]:
    """Owned inventory -> lowercased lookup keys (ids, canonical ids, names).

    /api/ds-preview passes item IDS (dashboard/routes_state.py), other
    callers pass names; a mode-mirror id (ARAM / map-30 ``223026``) folds to
    its SR id through ``kit_synergy.canonical_item_id``. Pre-audit the match
    was by NAME only, so a bought Guardian Angel stayed in the strip. A bare
    string or int is one item, never iterated per character."""
    if isinstance(my_owned_items, bool):
        return set()
    if isinstance(my_owned_items, (str, int)):
        raw_items: list | tuple | set | frozenset = [my_owned_items]
    elif isinstance(my_owned_items, (list, tuple, set, frozenset)):
        raw_items = my_owned_items
    else:
        return set()
    keys: set[str] = set()
    for raw in raw_items:
        if isinstance(raw, bool) or not isinstance(raw, (str, int)):
            continue
        text = str(raw).strip()
        if not text:
            continue
        keys.add(text.lower())
        if text.isdigit():
            keys.add(_canonical_id(text))
    return keys


def _is_owned(item: dict, owned: set[str]) -> bool:
    return item["id"] in owned or item["name"].lower() in owned


def compute_threat_profile(enemy_champions: list, enemy_items: list | None = None) -> dict:
    """Classify the enemy team's damage profile + identify top threats.

    ``enemy_champions``: list of champion display names (DDragon ids
    resolve too). Non-string and blank entries are skipped and do not
    count toward the team average.
    ``enemy_items``: accepted for API compatibility, NOT read (the
    profile is champion-only; the old docstring's lethality / lifesteal
    adjustments never existed in code).

    The scoring uses DDragon's per-champion info.attack / info.magic
    (1-10) as the base, then bumps burst when champions are in
    ``_KNOWN_BURSTERS`` or have tag in {Assassin}. ``info.defense`` is
    used to identify glass-cannon enemies (defense <= 3 + high damage
    = the assassin profile).
    """
    info_idx = _load_champ_info()
    names: list[str] = []
    if isinstance(enemy_champions, list):
        names = [n.strip() for n in enemy_champions
                 if isinstance(n, str) and n.strip()]
    if not names:
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
    # Pre-audit the denominator counted skipped blank slots, so
    # ["Zed", "", "", "", ""] averaged Zed's attack over five (2.8, not 9).
    n_enemies = len(names)

    for name in names:
        info = info_idx.get(name) or info_idx.get(name.replace("'", "")) or {}
        if not isinstance(info, dict):
            info = {}
        attack = _stat(info.get("attack", 5))
        magic  = _stat(info.get("magic", 5))
        defense = _stat(info.get("defense", 5))
        tags = info.get("tags")
        if not isinstance(tags, (list, tuple)):
            tags = ()

        ad_sum += attack
        ap_sum += magic

        # Burst signal: assassin tag, low defense + high single-stat,
        # known burst champion, OR very high attack+magic combo
        is_assassin = "Assassin" in tags
        is_known_burst = _name_key(name) in _KNOWN_BURSTER_KEYS
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
    summary = " | ".join(bits) or f"balanced (AD {ad_threat:.0f} / AP {ap_threat:.0f})"

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

    Skips anything already in ``my_owned_items`` (item id, mode-mirror id
    or case-insensitive name). Returns up to ``top_n`` ranked picks; threat
    values are read on the 0..10 scale (junk = 0, out-of-range clamped).
    """
    if not isinstance(threat, dict):
        return []
    ad    = _scale(threat.get("ad_threat"))
    ap    = _scale(threat.get("ap_threat"))
    burst = _scale(threat.get("burst_threat"))
    tank  = _scale(threat.get("tank_pressure"))

    owned = _owned_keys(my_owned_items)
    scored: list[dict] = []

    for item in _DEFENSIVE_ITEMS:
        name = item["name"]
        if _is_owned(item, owned):
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
    return scored[:_top_n(top_n)]


# Phase 1 (s174, 2026-05-12) - EHP-driven defensive picks. Option B layering:
# curated catalog is the whitelist, math drives order. Soft dep on the DS
# engine (HTTP :8860) - falls back to ``recommend_defensive_items`` heuristic
# when the engine is unreachable so the dashboard never goes dark.

def _threat_to_damage_shares(threat: dict) -> tuple[float, float]:
    """Map threat profile -> ``(enemy_ad_share, enemy_ap_share)`` floats in [0,1].

    Normalizes ``ad_threat`` (0..10) and ``ap_threat`` (0..10) to shares
    summing to <= 1.0. When both signals are strong (>=6 each) reserves
    ~10% true-damage share - real teams have at least some true damage
    (Talon E, Wukong R, Cho ult, item procs) that the blended_ehp shouldn't
    over-fit to one resist for.

    Inputs are read on the 0..10 scale (junk / NaN = 0, clamped), so the
    shares can never leave [0, 1] - pre-audit ``ad_threat=-5`` returned
    ``(-1.0, 2.0)`` and NaN returned ``(nan, nan)``.
    """
    ad = _scale(threat.get("ad_threat"))
    ap = _scale(threat.get("ap_threat"))
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
      * Engine raises, or returns no usable row inside the curated catalog
        (pre-audit: a raise escaped and an all-unknown answer returned [])

    ``my_level`` is coerced to an int in 1..18 (junk = 11). No shipped
    caller reaches this path today (measured s144 cycle 233); it is the
    documented integration point of core/daemon_slayer_client.rank_tank_for.

    Threat -> damage-share mapping via :func:`_threat_to_damage_shares`.
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
    owned = _owned_keys(my_owned_items)
    catalog_by_id = {item["id"]: item for item in _DEFENSIVE_ITEMS}
    catalog_ids = [
        iid for iid, info in catalog_by_id.items()
        if not _is_owned(info, owned)
    ]
    if not catalog_ids:
        return []

    try:
        ranked = rank_tank_for(
            my_champion,
            level=_level(my_level),
            item_ids=[],  # Baseline = naked. ``my_owned_items`` filtering happens
                          # via the catalog whitelist above. For Phase 1 the
                          # absolute delta from naked is the comparable scoring
                          # signal across all whitelisted picks.
            mode=str(my_mode),
            enemy_ad_share=ad_share,
            enemy_ap_share=ap_share,
            only_item_ids=catalog_ids,
            top=_top_n(top_n),
        )
    except Exception as exc:  # noqa: BLE001 - optional advisory; heuristic fallback below
        _log.debug("defensive_picks: rank_tank_for failed: %s", type(exc).__name__)
        ranked = None

    out: list[dict] = []
    for entry in ranked or ():
        item_id = str(getattr(entry, "item_id", "") or "")
        info = catalog_by_id.get(item_id)
        delta = _finite(getattr(entry, "delta_ehp", None))
        if info is None or delta is None:
            continue  # only_item_ids should guarantee membership; be defensive
        out.append({
            "item_id":  item_id,
            "name":     info["name"],
            "category": info["category"],
            "reason":   info["reason"],
            "score":    round(delta, 1),
        })
    if not out:
        return recommend_defensive_items(
            threat, my_champion, my_owned_items, top_n=top_n,
        )
    return out


def _level(value: object, default: int = 11) -> int:
    """Champion level -> int in 1..18; junk (incl. NaN / inf) = ``default``."""
    if isinstance(value, bool):
        return default
    try:
        level = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, min(18, level))


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None
