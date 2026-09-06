# arch: ARAM + Mayhem mode coach - DS-before-Haiku | section=coaching | frozen=no
"""
coaches/aram_coach.py  - v3  (ARCH-002 BaseCoach inheritance)

ARAM / ARAM Mayhem full coaching engine.
Inherits lifecycle from coaches.BaseCoach.
Self-polls Riot API every 1.5s.
Vision fires every 25s (Sonnet): tower HP, health packs, fight state, augments,
dropping to 6s inside the Mayhem game-start augment window (bounded, see
_select_vision_interval).
Claude Haiku coaches every ~8s or on kill/HP events.
Writes: data/aram_coaching_data.json
"""

import os
import sys
import json
import logging
from core.safe_coach_output import safe_coach_output
from pathlib import Path

from coaches._base_coach import (
    BaseCoach,
    finite,
    load_json,
    safe_write,
    mirror_live_stats,
    parse_field,
    parse_fields,
)
from core.aram_tenacity_context import (
    aram_tenacity_line,
    enemy_aram_tenacity_line,
)
from core.aram_balance_context import aram_balance_line
from core.cc_blended_ehp_context import cc_blended_ehp_impact_line
from core.cc_conditional_impact_context import (
    cc_conditional_impact_line,
)
from core.enemy_cc_threat_context import enemy_cc_threat_line
# RM-364: `augment_choices` is Haiku-VISION OCR output. Sanitised at prompt
# ASSEMBLY, which is the point both egress paths share.
from core.prompt_sanitize import clean_iter as _clean_for_prompt
from core.death_patterns_loader import personal_context_block
from core.mayhem_detect import is_mayhem

logger = logging.getLogger("rc.coaches.aram")
_APP_DIR = Path(__file__).parent.parent

# -- Same-state Haiku-skip debounce (BACKLOG.md:59) ----------------------------
# DEFAULT-OFF, fidelity-gated. When OFF (default) behavior is byte-identical to
# the always-call-Haiku path. When ON (RC_ARAM_STATE_DEBOUNCE=1), the coach
# computes a COARSE signature of only the coaching-relevant snapshot fields
# (continuous values bucketed so tiny jitter does not bust the cache); if the
# signature equals the last-coached signature AND the cached coaching is younger
# than the hard max-staleness ceiling, the redundant messages.create is skipped
# and the prior coaching artifact is reused. The ceiling guarantees the coach
# can never go truly stale: once it expires, the next tick always re-calls Haiku
# even on an unchanged signature. Serves the cost objective + Haiku-to-ZERO north
# star without trading fidelity (the cardinal "never trade fidelity for cost").
# Validate against a live/replayed game before flipping ON (do-not-flip-blind).
_STATE_DEBOUNCE = os.getenv("RC_ARAM_STATE_DEBOUNCE", "0") == "1"
# Hard max-staleness ceiling (seconds): the longest the coach may reuse a cached
# same-state coaching before it MUST re-call Haiku regardless of signature.
# 45s sits above the stable poll cadence (_STABLE_DEBOUNCE_S=25s) so a stable
# board skips at most ~1 redundant call between refreshes, yet is short enough
# that the coach text never feels frozen mid-game.
_STATE_DEBOUNCE_MAX_STALE_S = 45.0

# How much of each live Haiku response is preserved in the log.
#
# This capture is the ONLY offline record of the live coach column, so the
# Haiku-to-ZERO shadow comparison can replay it (tools/aram_raw_replay.py) only
# as far as the capture reaches. The previous 600-char bound sat below the
# observed 1200-2100 char response range, which cut the trailing `Choices:`
# line off most records - and a clipped record is indistinguishable from a
# model that never emitted the field, so the live column read as permanently
# empty.
#
# 4000 covers the whole response the call can physically produce: max_tokens is
# 900, and ~4 chars/token puts the ceiling near 3600. It stays a bound rather
# than becoming unbounded because a model repetition loop would otherwise flood
# the day's log (a prior cost sweep traced 97 percent of a log file to exactly
# that shape).
_RAW_LOG_CHARS = 4000


def _coach_state_signature(state: dict, vision_state: dict) -> tuple:
    """COARSE signature of only the coaching-relevant snapshot fields.

    Continuous / noisy values are BUCKETED so sub-bucket jitter (a 1% HP tick,
    a few seconds of game time, a handful of gold) does NOT bust the cache and
    force a redundant Haiku call. Discrete tactical state (level, dead-enemy
    count, owned items, augments, augment-select, wave bucket, tower buckets,
    pack availability) IS in the signature so any real change always re-calls.

    Deliberately COARSE for cost, but NOT so coarse it hides a mid-fight shift:
    HP is bucketed in 10% bands (aligns with the prompt's HP decision-tree
    thresholds at 80/60/40/30), which keeps the action tier responsive while
    collapsing micro-jitter. Used only when _STATE_DEBOUNCE is ON.
    """
    state = state or {}
    vs = vision_state or {}

    def _bucket(v, size, default=0):
        try:
            return int(float(v) // size)
        except (TypeError, ValueError):
            return default

    hp_band = _bucket(state.get("hp_pct", 100), 10)
    mana_band = _bucket(state.get("mana_pct", 100), 25)
    # Gold in ~300g bands: enough to shift a completed-item recommendation,
    # small enough to ignore per-tick passive income.
    gold_band = _bucket(state.get("gold", 0), 300)
    # Game time in 30s bands - coarse phase signal, not a per-second buster.
    time_band = _bucket(state.get("game_seconds", 0), 30)
    wave_band = _bucket(vs.get("wave_pct", 50), 25)
    my_tower_band = _bucket(vs.get("my_tower_hp", 100), 25)
    en_tower_band = _bucket(vs.get("enemy_tower_hp", 100), 25)
    packs = vs.get("hp_packs", [True, True])
    packs_t = tuple(bool(p) for p in packs) if isinstance(packs, list) else ()
    augs = vs.get("augments", [])
    augs_t = tuple(augs) if isinstance(augs, list) else ()

    return (
        state.get("champion", ""),
        state.get("game_mode", "ARAM"),
        int(state.get("level", 1) or 1),
        hp_band,
        mana_band,
        gold_band,
        time_band,
        len(state.get("dead_enemies", [])),
        tuple(state.get("items", []) or []),
        tuple(state.get("enemy_comp", []) or []),
        wave_band,
        my_tower_band,
        en_tower_band,
        packs_t,
        augs_t,
        bool(vs.get("augment_select")),
    )

# Live metric recording: the enable gate (env RC_LIVE_METRICS=1 OR config
# live_metrics_enabled, re-read live) + per-match streamer dispatch live in
# core.live_metrics. Wired into the coaching write below via live_metrics.stream;
# OFF by default, never crashes the coach.
from core import live_metrics


def _parse_item_reasons(reasons_str: str) -> dict:
    """Parse "Item reasons:" output line into a {item_name: reason} map.

    Format (as specified in the ARAM prompt): semicolon-separated
    "ItemName=reason" pairs, e.g.
      "Liandry's=anti-tank HP burn; Zhonya's=vs Zed R; Rylai's=kite slow"

    The UI hover tooltip reads from p.item_build_reasons[name] and
    appends the reason to the name + cost on the Recommended tile.

    Returns {} on empty or malformed input.
    """
    if not reasons_str:
        return {}
    out: dict[str, str] = {}
    for pair in reasons_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, reason = pair.partition("=")
        name, reason = name.strip(), reason.strip()
        if name and reason:
            out[name] = reason
    return out


# Item-class peer table (2026-04-26): items in the same set are functional
# alternates - buying a 2nd one is almost always wrong (you've already paid
# the slot for the role). The dedup helper below uses this to strip from
# the recommended next-buy any item whose CLASS PEER is already owned, not
# just the literal owned name. Catches "MR owned, coach suggests LDR" (both
# anti-armor + grievous-wounds for ADCs).
_ITEM_CLASS_PEERS: tuple[tuple[str, ...], ...] = (
    # Anti-armor / armor-pen ADC items - pick one. User-reported regression
    # 2026-04-26: coach kept suggesting Lord Dominik's even after Mortal
    # Reminder was built, then Serylda's after that.
    ("lord dominik", "mortal reminder", "serylda"),
    # Anti-heal grievous-wounds items spanning roles (only ONE makes sense
    # and the *finished* slot covers it). Components like Executioner's /
    # Oblivion Orb are NOT in this list - those are upgrade paths.
    ("morellonomicon", "chempunk chainsword"),
    # Mythic mage burst-cap items that overlap heavily on AP scaling.
    # ("luden", "shadowflame"),  # disabled - these stack fine in many builds
    # ADC mythic-tier crit cores - IE is the canonical first; second crit
    # mythic is rare. Leave commented unless user complains.
    # ("infinity edge", "navori"),
    # Boots - only ONE boot pair fits the slot. All purchasable boot types
    # are peers so the coach never recommends a second pair after boots are
    # owned. Gluttonous/Gunmetal Greaves (jungle/smite only) and Mobility
    # Boots (SR-only) are intentionally excluded as not ARAM-purchasable.
    ("berserker", "ionian", "steelcap", "mercury", "sorcerer", "symbiotic",
     "swiftness", "spellslinger"),
    # Spellblade passive - shared by Trinity Force, Lich Bane, Divine
    # Sunderer, and Essence Reaver. Passive does NOT stack; only the
    # last-triggered proc applies, making a second Spellblade item a dead slot.
    # "sunderer" used (not "divine") to avoid collision with "Sword of the Divine".
    ("trinity", "lich bane", "sunderer", "essence reaver"),
)


def _dedup_build_vs_owned(item_build: str, items_display: str) -> str:
    """Strip from `item_build` any item already present in `items_display`,
    OR any item whose CLASS PEER is owned (e.g. don't suggest Lord Dominik's
    when Mortal Reminder is built - both are anti-armor finishers).

    The LLM occasionally keeps the next-slot item the same as a completed
    item in inventory (Zhonya's appears in both "owned" and "next to buy"),
    producing the coach bug where the Recommended tile highlights a
    completed item. Match is case/space-normalised and substring-both-ways
    so short form ("Zhonya's") catches long form ("Zhonya's Hourglass").

    Arrow separator in item_build is U+2192 "->" per coach prompt convention.
    """
    if not item_build or not items_display:
        return item_build or ""
    def _norm(s: str) -> str:
        return "".join(c.lower() for c in s if c.isalnum())
    owned = [_norm(s) for s in items_display.split(",")]
    owned = [o for o in owned if len(o) >= 3]
    if not owned:
        return item_build
    # Build a banned-class set: every class peer of any owned item.
    # Match owned against each peer string with substring-both-ways so the
    # canonical short form ("lord dominik") catches "Lord Dominik's Regards".
    banned_peers: set[str] = set()
    for owned_norm in owned:
        for peer_set in _ITEM_CLASS_PEERS:
            owned_in_class = any(_norm(p) in owned_norm or owned_norm in _norm(p)
                                  for p in peer_set)
            if owned_in_class:
                banned_peers.update(_norm(p) for p in peer_set)
    # AUDIT 2026-04-26: Haiku now returns items COMMA-separated (not "->");
    # splitting only on "->" produced a single 6-item blob whose normalised
    # form contained every owned item as a substring, so the dedup
    # nuked the entire build. Split on BOTH separators so individual
    # items get matched correctly.
    import re as _re
    parts = [p.strip() for p in _re.split(r'[→,]', item_build) if p.strip()]
    kept = []
    for p in parts:
        np = _norm(p)
        if len(np) < 3:
            kept.append(p)
            continue
        is_dupe = any((np in o) or (o in np) for o in owned)
        is_class_dupe = any((b in np) or (np in b) for b in banned_peers)
        if not is_dupe and not is_class_dupe:
            kept.append(p)
    return " → ".join(kept)


def _split_item_build_like_ui(item_build: str) -> list:
    """Split a coach item_build string EXACTLY the way the dashboard strip does.

    Copied from web/js/lib/items_index.js:60-64 (_splitItemList with
    splitArrow=true), which item_build.js:209 uses to build the Recommended
    tile name list:
        const sep = /\\s*(?:,|<U+2192>|->)\\s*/;
        String(str).split(sep).map(s => s.trim()).filter(Boolean);
    Keeping the separator set identical is what makes the cue keys match the
    rendered tile names byte-for-byte. The arrow literal is spelled via
    chr(0x2192) so this source file stays 7-bit ASCII.

    NOTE: the frontend applies one further owned-item dedup pass
    (item_build.js:222-226) before rendering. It is a defensive no-op here
    because the artifact's item_build has already been through the
    server-side _dedup_build_vs_owned, so the name sets agree.
    """
    if not item_build:
        return []
    import re as _re
    _arrow = chr(0x2192)
    sep = r"\s*(?:,|" + _arrow + r"|->)\s*"
    return [p.strip() for p in _re.split(sep, str(item_build)) if p.strip()]


def _item_interaction_block(item_build: str, enemy_champions, game_time_s,
                            game_mode) -> dict:
    """Build the additive {item_interaction_cues, item_interaction_provenance}
    artifact fragment for the dashboard item strip.

    The context module is imported LAZILY inside this function so a missing or
    broken core.aram_item_interaction_context can never kill a coaching tick;
    any failure degrades to the neutral fragment ({} / "").
    """
    try:
        from core.aram_item_interaction_context import (
            cue_provenance,
            item_interaction_cues,
        )
        names = _split_item_build_like_ui(item_build)
        cues = item_interaction_cues(
            enemy_champions or [],
            game_time_s,
            names,
            game_mode=game_mode,
        )
        return {
            "item_interaction_cues": dict(cues or {}),
            "item_interaction_provenance": str(cue_provenance() or ""),
        }
    except Exception as _cue_exc:  # noqa: BLE001
        logger.debug("ARAM item-interaction cues: %s", _cue_exc)
        return {"item_interaction_cues": {}, "item_interaction_provenance": ""}


if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


# -- Challenger system prompt ---------------------------------------------------
_SYSTEM = """\
You are a Challenger-level ARAM{mayhem_tag} coach on Howling Abyss.

CHAMPION: {profile}
Recommended runes: {rune_rec}
ARAM meta: {aram_meta}
{adaptation_hint}
═══ ARAM DECISION TREE ═══
WAVE POSITION (wave_pct field): 0=crashed to your base | 50=mid-lane | 100=pushed into enemy base
  wave_pct >65 -> wave punishes enemy for dying; extend aggression by one tier
  wave_pct <35 -> wave punishes YOU for fighting; drop one tier (e.g. POKE->HOLD)
  wave_pct 35-65 -> neutral, use HP thresholds below as written
HP > 80% AND enemy has ≥2 targets low → ALL-IN  → push for kills
HP 60-80% AND poke available → POKE PHASE  → trade single abilities, deny packs
HP 40-60% → HOLD  → stay behind your frontline, poke only when totally safe
HP 30-40% → DISENGAGE → collect health pack if safe to reach, retreat to your tower
HP < 30% → FALL BACK → step into your turret range, wait for HP regen / pack / death

═══ ARAM FOUNTAIN RULE (HARD) ═══
ARAM has NO recall. You CANNOT base. The fountain only restores you on
death-respawn or if you have the AUGMENT "Cheater" (which adds normal
recall). Therefore:
  - The word "fountain" MUST NOT appear in the Action label OR the
    Immediate text UNLESS the augment list explicitly contains
    "Cheater" (case-insensitive substring match).
  - For the Action label specifically: do NOT use "FOUNTAIN", "BASE",
    "RECALL", "FOUNTAIN NOW", "FOUNTAIN FALL BACK", or any variant.
    Use instead: "FALL BACK", "DISENGAGE", "HOLD", "WAIT RESPAWN",
    "HUG TOWER", "GRAB PACK", "SPRINT TO PACK".
  - Without Cheater: low HP → use health packs, hug tower, wait for
    regen, or accept the death and use the respawn fountain time to
    reposition. NEVER advise leaving lane to fountain.
  - "reset / item" advice: only "Wait for respawn fountain" (passive,
    after death) is acceptable phrasing - that means buying when you
    next die and respawn at fountain, not walking there now. Default
    to "Buy after next death - N gold short of <item>" or
    "Complete <item> on respawn".

═══ FIGHT COMMITMENT RULES ═══
ALL-IN requires: your key damage ability ready + at least 1 ally CC ability up + enemy tank not blocking + enemy carry within range
DO NOT all-in: when enemy has stacked engage ready (Malphite, Amumu, Zac ult off CD)
NEVER chase past enemy T1 range without 2+ your allies ahead of you
RESET PRIORITY: if enemy T1 is dead and inhib open → group + push ONLY with numbers advantage

═══ POSITIONING ═══
Always: stand at maximum effective range for your champion
Poke phase: step up → throw poke → immediately step back behind your frontline
Melee ADC (Nilah/Yasuo): find isolated poke targets only; do not walk into poke range
Caitlyn/Jinx/Tristana: use superior range; never let a diver close to auto range without peel
Health pack collection: grab when HP < 50% AND you have safe path; do not greed into death

═══ OBJECTIVE ═══
Your T1 up → defend first; dying to save T1 is correct if it buys 1min+ respawn time
Enemy T1 dead → push wave to their base; group mid ONLY if enemy inhib is accessible
Enemy inhib dead → team fight to force Nexus; never solo-push

═══ HEALTH PACK RULES ═══
HP packs restore ~30% HP. Treat them as a key resource, not a bonus.
Both packs available: you can trade more aggressively → you have a safety net.
One pack available: take calculated risks only; do not greed into low HP.
No packs available: play conservatively until packs respawn or you use fountain.
Pack is reachable AND you are HP<50%: collect it BEFORE re-engaging.
Do NOT walk into enemy range to reach a pack. Path safety first.
Report pack status in Positioning or Reset/item fields whenever relevant.

═══ ARAM MAYHEM AUGMENT RULES ═══
Active augments should be used in EVERY trade window, not saved
Best augments for carries: Shield Bash, Eyeball Collection, Cut Down, Sudden Impact
Prioritize augments that proc on your main damage type (AD vs AP)

═══ ═══ ARAM ITEM RESTRICTIONS ═══
This is ARAM (Howling Abyss) NOT Summoner's Rift. STRICTLY:
- No control wards, no stealth wards, no ward items
- No jungle items (Smite, camp items)
- No lane-specific quest items unavailable in ARAM
- Recommend only items purchasable on Howling Abyss
- ARAM has health packs, NOT bushes or warding zones
- No dragon/baron/rift herald - only towers and Nexus matter
Use enemy items (provided in user context) to adapt build recommendations.
Item build MUST contain only FULLY COMPLETED items (e.g. Infinity Edge, Bloodthirster).

OUTPUT FORMAT ═══
Exactly 7 fields, NO markdown, NO filler. Choices is REQUIRED and is the PRIMARY actionable surface (the operator picks one via Alt+1/2/3 hotkey). Do NOT emit an Immediate prose field - that slot has been retired in favour of the Choices array.
Action: <1-3 WORDS ALL-CAPS - single decision>
Fight rule: <one engage condition, [E] ability to respect, max 12 words>
Reset / item: <fountain yes/no + next ARAM item (no wards, no jungle items), max 10 words>
Risk: <single most dangerous enemy ability, max 10 words>
Item build: <comma-separated FULL COMPLETED items ONLY, 4-6 items - NO components (no Dagger, Long Sword, Pickaxe, B.F. Sword, etc.); omit boots unless critical; prefix 7th item with "+" if excess gold warrants it>
Item extra: <ONLY if no 7th item: "Pot: X" for potion boots OR "Shard: X" for rune shard - else omit>
Item reasons: <per-item one-liner (max 6 words each), semicolon-separated, format "ItemName=reason"; e.g. "Liandry's=anti-tank HP burn; Zhonya's=vs Zed R; Rylai's=kite slow" - only for items in Item build>
Choices: <REQUIRED compact single-line JSON array of 2-3 micro-decisions the player faces RIGHT NOW. Schema: [{{"key":"A","label":"<3-5 word option>","expected_outcome":"<one sentence what likely happens>","confidence":"low" or "mid" or "high","source_tag":"<3-10 char descriptor>"}}, ...]. Keys are A/B/C in order. Use confidence honestly: "high" only for textbook plays; "mid" for situational reads; "low" for high-uncertainty calls. Set source_tag to a short descriptor like "fight-trade", "pack-grab", "scaling", "siege-call", "augment-pivot". Return [] ONLY if no decision is on the clock (dead waiting respawn, mid-fountain). The default expectation is 2-3 choices reflecting the live tactical fork. Output MUST be a single line of valid JSON (no markdown, no line breaks inside the array).>
""" + personal_context_block()

_USER_TMPL = """\
=== {game_time} | ARAM{mayhem_tag} ===
HP: {hp}%  Mana: {mp}%  Gold: {gold}g  Level: {lv}  KDA: {kda}
Wave position: {wave_pct}% (0=your base, 50=mid, 100=enemy base)
Items: {items}
Your team: {allies}
Enemy team: {enemies}
Enemy items (from API): {enemy_items}
Priority items vs enemy: {matchup_ctx}
Dead enemies: {dead}  Alive: {alive}  Respawns: {dead_resp}
My T1: {my_t}%  Enemy T1: {en_t}%
Augments: {augs}
HP packs available: {packs}
My abilities (Q/W/E/R): {my_abilities}
My runes: {my_runes}
Enemy keystones: {enemy_runes}
{aram_tenacity}
{enemy_aram_tenacity}
{aram_balance}
{enemy_cc_threats}
{cc_blended_ehp_impact}
{cc_conditional_impact}
DS top items ({ds_label} ranked, own-items-accounted): {ds_picks}
{event_line}
"""

# NOT a cache_control candidate (item 286): static portion ~62 tok, far below
# the 2048-tok Haiku prompt-cache floor - a static/data split caches nothing.
# Guard: tests/test_prompt_cache_floor_item286.py.
_AUG_SELECT_PROMPT = """\
ARAM{mayhem} augment select. Challenger coaching.
Your champion: {champion}  HP: {hp}%
Allies: {allies}
Enemies: {enemies}
Choices: {choices}
NO markdown. Output exactly:
Take: <augment name>
Why: <one sentence mechanical reason>
Gameplan: <how this changes your fight window>
"""

_VISION_PROMPT = """\
Analyze this ARAM (Howling Abyss) League of Legends screenshot.
Return ONLY valid JSON with no markdown:
{
  "my_tower_hp": 85,
  "enemy_tower_hp": 60,
  "augments": [],
  "augment_select": false,
  "augment_choices": [],
  "hp_packs": [true, true],
  "wave_pct": 50,
  "fight_state": "poke"
}
Rules:
- my_tower_hp: YOUR nearest tower HP% (0-100), or null if not visible
- enemy_tower_hp: ENEMY nearest tower HP%, or null if not visible
- augments: active augment names visible in HUD (Mayhem mode only), empty list if none
- augment_select: true ONLY if augment card selection panel is visible
- augment_choices: list of augment names from selection panel, empty if not selecting
- hp_packs: [left_pack_available, right_pack_available]
  Detection rules:
  true  = green/white circular pack icon IS visible at that lane position
  false = spawn point is empty (consumed or not yet respawned)
  Default both to true ONLY when lane is fully off-screen; never default true when uncertain
  A consumed pack shows an empty ring or nothing -- not a green icon
  Accurate pack detection directly affects coaching quality
- wave_pct: estimated minion wave position as 0-100 (0=at your base, 100=at enemy base)
- fight_state: "poke" / "all-in" / "retreating" / "idle"
- Return ONLY the JSON object, no markdown
"""


# -- Rune recommendation loader -------------------------------------------------

def _load_rune_rec(champion: str, mode: str = "aram") -> str:
    """Load recommended rune string for a champion from meta_build JSON."""
    try:
        # KIWI = ARAM Mayhem; both map to ARAM rune recommendations
        _ARAM_MODES = {"ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM"}
        fname = (
            "rune_recommendations_aram.json"
            if mode.upper() in _ARAM_MODES or "aram" in mode.lower()
            else "rune_recommendations_sr.json"
        )
        p = _APP_DIR / "data" / "meta_build" / fname
        if not p.exists():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
        rec = data.get(champion)
        if not rec:
            return ""
        ks   = rec.get("keystone", "")
        pri  = rec.get("primary_tree", "")
        sec  = rec.get("secondary_tree", "")
        note = rec.get("coaching_note", "")
        result = f"{ks} | {pri} / {sec}"
        if note:
            result += f" - {note}"
        return result
    except Exception:  # noqa: BLE001
        return ""


def _load_build_note(champion: str) -> str:
    """Load ARAM build note + tier for a champion from aram_champion_builds.json."""
    try:
        p = _APP_DIR / "data" / "meta_build" / "aram_champion_builds.json"
        if not p.exists():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
        entry = data.get(champion)
        if not entry or isinstance(entry, str):
            return ""
        tier = entry.get("aram_tier", "")
        note = entry.get("build_note", "")
        result = f"{tier} tier - {note}" if tier and note else note or tier
        return result[:220]
    except Exception:  # noqa: BLE001
        return ""


def _fmt_abilities(abilities: dict) -> str:
    """Format ability dict as compact string for Haiku prompt."""
    if not abilities:
        return "unknown"
    parts = []
    for slot in ("q", "w", "e", "r"):
        ab = abilities.get(slot)
        if not ab:
            continue
        name = ab.get("name", slot.upper())
        cd   = ab.get("cooldown")
        lvl  = ab.get("level")
        part = f"{slot.upper()}:{name}"
        if lvl is not None:
            part += f"(lv{lvl})"
        if cd is not None:
            part += f" cd={cd}s"
        parts.append(part)
    return " | ".join(parts) or "unknown"


# ==============================================================================
# Coach class
# ==============================================================================

class Coach(BaseCoach):
    """ARAM / ARAM Mayhem coach. Inherits full lifecycle from BaseCoach."""

    GAME_MODES     = ("ARAM",)
    _MODE_NAME     = "aram"
    _DATA_FILENAME = "aram_coaching_data.json"

    # Cost-tuned 2026-05-04 (post-audit): bumped from VISION 15->25 /
    # DEBOUNCE 8->12 to cut API call rate ~33%.
    # Dynamic debounce: _DEBOUNCE_S is reactive (state change detected);
    # _STABLE_DEBOUNCE_S applies when no kill/item/level/hp change detected.
    _VISION_INTERVAL    = 25.0
    _DEBOUNCE_S         = 12.0
    _STABLE_DEBOUNCE_S  = 25.0
    _FAST_PATH_MIN_S    = 5.0
    _HP_DROP_THRESHOLD  = 20.0

    # Mayhem augment-window fast poll. The augment panel is on screen for only
    # ~10-15s at game start, so a single 25s-cadence tick usually lands outside
    # it and the reco never fires (live-eyeballed 2026-07-12). These bound the
    # fast cadence three independent ways - clock ceiling, catch latch, scan cap
    # - so no single one failing can leave the coach fast-polling all game.
    _AUGMENT_WINDOW_S       = 45.0
    _FAST_VISION_INTERVAL   = 6.0
    _AUGMENT_FAST_MAX_SCANS = 6

    # Tiered vision-reader config lifted from _run_vision to class level so it is
    # introspectable without an Anthropic key. The trailing block is the Lane E
    # CV OCR shadow-only numerics - registered for R101-A OCR-vs-Sonnet logging,
    # never read into the served coaching dict.
    _ARAM_TIERED_FIELDS = [
        "timer",               # OCR canary (validates in-game frame)
        "my_tower_hp", "enemy_tower_hp",
        "wave_pct", "hp_packs", "fight_state",
        "augments", "augment_select", "augment_choices",
        # B-01b re-home: the live relay answers every mode with the TFT prompt
        # (vision_server/_inference.py:36), which emits the augment flag as
        # `is_augment_select`. modes/shared_vision._postprocess aliases it into
        # the consumed `augment_select`, so it IS a requested field for this
        # mode - declaring it here stops RC_VISION_MERGE_STRICT filtering it out
        # before the alias runs. ARAM Mayhem has augments (live-verified
        # 2026-07-12), so this coach owns the flag.
        "is_augment_select",
        "ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp",
        "gold", "level", "cs", "kda",
    ]
    _ARAM_SHADOW_FIELDS = [
        "ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp",
        "gold", "level", "cs", "kda",
    ]
    _ARAM_TIERED_VALIDATORS = {
        "my_tower_hp":     lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "enemy_tower_hp":  lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "wave_pct":        lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "hp_packs":        lambda v: isinstance(v, list),
        "fight_state":     lambda v: isinstance(v, str) and bool(v),
        "augments":        lambda v: isinstance(v, list),
        "augment_select":  lambda v: isinstance(v, bool),
        "is_augment_select": lambda v: isinstance(v, bool),
        "augment_choices": lambda v: isinstance(v, list),
        "ally_1_hp":       lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "ally_2_hp":       lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "ally_3_hp":       lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "ally_4_hp":       lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "gold":            lambda v: isinstance(v, int) and 0 <= v <= 99999,
        "level":           lambda v: isinstance(v, int) and 1 <= v <= 18,
        "cs":              lambda v: isinstance(v, int) and 0 <= v <= 1000,
        "kda":             lambda v: isinstance(v, str) and v.count("/") == 2,
    }

    # -- BaseCoach hooks -------------------------------------------------------

    def _init_extra(self) -> None:
        """Seed the augment fast-poll counters before the loops start."""
        self._augment_resolved   = False
        self._augment_fast_scans = 0
        self._fast_mode          = False

    def _reset_extra(self) -> None:
        # Fires per new game (coaches/_base_coach.py:361). The interval is reset
        # alongside the counters because it is an INSTANCE attr the vision loop
        # reads every tick - leaving a previous game's fast value on the
        # instance would fast-poll the whole next game.
        self._init_extra()
        self._VISION_INTERVAL = type(self)._VISION_INTERVAL

    def _select_vision_interval(
        self, state: dict, *, augment_resolved: bool, fast_scans: int
    ) -> float:
        """Effective seconds between vision scans for this tick.

        Reads `type(self)._VISION_INTERVAL` rather than the instance attr for
        the default: `_update_vision_cadence` mutates the instance attr, so
        reading it here would feed the fast value back into itself and latch
        fast forever. Same trick as the `type(self)._DEBOUNCE_S` read below.
        """
        # Plain ARAM has no augments, so a fast poll there is pure Sonnet spend
        # for a panel that can never appear.
        if not is_mayhem(state):
            return type(self)._VISION_INTERVAL
        try:
            gs = float(state.get("game_seconds"))
        except (TypeError, ValueError):
            return type(self)._VISION_INTERVAL
        in_window = (
            gs < self._AUGMENT_WINDOW_S
            and not augment_resolved
            and fast_scans < self._AUGMENT_FAST_MAX_SCANS
        )
        return (
            self._FAST_VISION_INTERVAL if in_window
            else type(self)._VISION_INTERVAL
        )

    def _update_vision_cadence(self, state: dict) -> None:
        """Publish the effective interval to the vision loop.

        The loop re-reads `self._VISION_INTERVAL` on every 3s iteration
        (coaches/_base_coach.py:462), so a plain float assignment from the poll
        thread is the whole mechanism - GIL-atomic, no lock, identical to the
        already-shipped `self._DEBOUNCE_S` mutation.
        """
        interval = self._select_vision_interval(
            state,
            augment_resolved=self._augment_resolved,
            fast_scans=self._augment_fast_scans,
        )
        self._VISION_INTERVAL = interval
        self._fast_mode = (interval == self._FAST_VISION_INTERVAL)

    def _blank_artifact_data(self) -> dict:
        return {
            "mode": "aram", "action": "", "immediate": "", "fight_rule": "",
            "reset_item": "", "risk": "", "item_build": "", "item_extra": "",
            "my_tower_hp": 100, "enemy_tower_hp": 100,
            "wave_pct": 50, "hp_packs": [True, True],
            "game_id": "",
        }

    def _parse_raw_state(self, raw: dict) -> dict:
        return _parse_state(raw)

    def _on_state_received(self, state: dict) -> None:
        """AUDIT-OPUS BUG-2: eagerly write my_team for CHAOS-side orientation."""
        try:
            mt = state.get("my_team")
            if mt:
                cur = load_json(self._out)
                if cur.get("my_team") != mt:
                    cur["my_team"] = mt
                    safe_write(self._out, cur)
        # D-CLASS: callee already swallows. load_json (_base_coach.py:66-68)
        # returns {} on any error and safe_write (:100-102) returns after
        # logging, so no exception from either can reach this handler. It is
        # mechanically unreachable and cannot be narrowed.
        except Exception:  # noqa: BLE001
            pass
        # Dynamic debounce: relax polling rate when game state is stable
        prev = self._last_state
        if prev:
            changed = (
                len(state.get("dead_enemies", [])) != len(prev.get("dead_enemies", [])) or
                state.get("items") != prev.get("items") or
                state.get("level") != prev.get("level") or
                (prev.get("hp_pct", 100) - state.get("hp_pct", 100)) >= 10
            )
            self._DEBOUNCE_S = (
                type(self)._DEBOUNCE_S if changed else self._STABLE_DEBOUNCE_S
            )
        self._update_vision_cadence(state)

    def _run_vision(self) -> None:
        if self._fetch_game_data() is None:
            return
        # Counted here rather than in the loop gate so a scan the spend-gate
        # skipped never burns cap budget - the cap exists to bound real Sonnet
        # calls, not loop ticks.
        if self._fast_mode:
            self._augment_fast_scans += 1
        try:
            from core.feature_policy import is_allowed as _fp_ok
            if not _fp_ok("aram", "live_coaching"):
                return
        # is_allowed (core/feature_policy.py:305-350) is total by construction:
        # _check_reload is already guarded internally, every branch returns a
        # bool, the mode/feature literals here are str, and _matrix is only ever
        # assigned a validated dict. The import is the only raising statement.
        except ImportError:
            pass

        _ai = self._overlay.get("ai_bar") if self._overlay else None
        if _ai:
            try:
                _ai.set_scanning(0)
            # LEFT BROAD (silent-except triage, C-class declined): _ai comes
            # from self._overlay, which BaseCoach initialises to {} at
            # coaches/_base_coach.py:297 and nothing in the coach package ever
            # populates. set_scanning has no implementation in this repo (only
            # test stubs), so the callee is an unconstrained duck-typed object
            # and no exception set is provable from the source.
            except Exception:  # noqa: BLE001
                pass
        try:
            import anthropic
            from modes.shared_vision import GameVisionReader
            r = GameVisionReader.__new__(GameVisionReader)
            r._client = anthropic.Anthropic(api_key=self._api_key, base_url="https://api.anthropic.com")
            r._model  = "claude-sonnet-4-6"
            r._last   = {}
            r.PROMPT  = _VISION_PROMPT
            r.TIERED_FIELDS = self._ARAM_TIERED_FIELDS
            r.SHADOW_FIELDS = self._ARAM_SHADOW_FIELDS
            r.TIERED_VALIDATORS = self._ARAM_TIERED_VALIDATORS
            state = r.read_tiered()
            if not state:
                return
            self._vision_state = state
            cur = load_json(self._out)
            for k, v in [
                ("my_tower_hp",    state.get("my_tower_hp")),
                ("enemy_tower_hp", state.get("enemy_tower_hp")),
                ("wave_pct",       state.get("wave_pct")),
                ("hp_packs",       state.get("hp_packs")),
            ]:
                if v is not None:
                    cur[k] = v
            if state.get("augments"):
                cur["augments"] = ", ".join(state["augments"])
            if state.get("augment_select") and state.get("augment_choices"):
                # Latch BEFORE the reco call: the fast poll's contract is "land
                # a scan inside the window", and a landed scan fulfils it.
                # _handle_augment_select re-raises on API failure, so gating the
                # cadence latch on its success would couple vision spend to an
                # unrelated Haiku outcome.
                self._augment_resolved = True
                self._handle_augment_select(state)
            # (2026-04-25) Always-on champion + self-spell write - pulls
            # from self._last_state (live-client snapshot, refreshed every
            # 1.5s by _base_coach._poll_loop), so the dashboard's header
            # self-spells pill flips D/F -> Flash/Heal as soon as the
            # vision tick fires (~every 8-12s on this mode), not gated
            # on the slower coach-Haiku-API tick. Same envelope shape as
            # the API tick path; harmless if pre-existing keys differ.
            ls = self._last_state or {}
            _champ = ls.get("champion", "")
            _sd = ls.get("summoner_d", "")
            _sf = ls.get("summoner_f", "")
            if _champ:
                cur["champion"] = _champ
            if _champ and (_sd or _sf):
                cur["ally_spells"] = {
                    _champ: [{"spell": _sd, "cd_s": 0},
                             {"spell": _sf, "cd_s": 0}],
                }
            safe_write(self._out, cur)
            _ai2 = self._overlay.get("ai_bar") if self._overlay else None
            if _ai2:
                try:
                    _ai2.set_done()
                # LEFT BROAD (silent-except triage, C-class declined): same
                # unconstrained duck-typed overlay callee as the set_scanning
                # site above; no exception set is provable from the source.
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("ARAM vision run: %s", exc)

    # -- Target-bonus-HP estimator (s74 - Phase 4 batch 19 wire-in) ----------

    def _estimate_target_bonus_hp(self, state: dict | None = None) -> float:
        """Estimate enemy bonus HP from items. ARAM port of arena_coach's
        s73 estimator, but with no round-count fallback (ARAM doesn't have
        rounds - emit 0 = "no signal" when items unavailable).

        Walks ``state["enemies"]`` (structured list, populated in
        ``_to_state``), filters alive opponents, resolves their item
        display names via ``daemon_slayer_resolver`` with ``mode="aram"``
        (gets SR base IDs, NOT Arena 22XXXX aliases), sums bonus HP per
        opponent, returns MAX. Capped at 1500 to match LDR Giant Slayer's
        engine-side cap.

        MAX (not avg/sum) for the same reason as arena_coach: Giant Slayer
        is target-conditional; if ANY enemy is tanky, the recommendation
        should escalate against THAT target.
        """
        state = state or {}
        enemies = state.get("enemies") or []
        opp_items: list[list[str]] = [
            (e.get("items") or []) for e in enemies if not e.get("is_dead")
        ]
        if not any(opp_items):
            return 0.0
        from core import daemon_slayer_resolver as _ds_res
        best = 0.0
        for items in opp_items:
            if not items:
                continue
            ids = _ds_res.resolve_many(items, mode="aram")
            hp = _ds_res.total_bonus_hp(ids)
            if hp > best:
                best = hp
        return min(1500.0, best) if best > 0 else 0.0

    @safe_coach_output("ARAM")
    def _run_coach(self, state: dict) -> None:
        try:
            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
            if not _fp_ok("aram", "live_coaching"):
                _fp_wr("aram")
                return
        except Exception:  # noqa: BLE001
            pass
        if not self._client:
            return
        try:
            from coach_integration import CHAMPION_PROFILES, GENERIC_PROFILE
            champ    = state.get("champion", "Unknown")
            profile  = CHAMPION_PROFILES.get(champ, GENERIC_PROFILE)
            gm       = state.get("game_mode", "ARAM")
            # Detect Mayhem via the canonical helper. Pre-2026-05-03 this
            # checked `"MAYHEM" in gm.upper()` which never matched because
            # Riot's live value is "KIWI" - see core/mayhem_detect.py.
            is_mayhem_mode = is_mayhem(gm)
            mayhem   = " Mayhem" if is_mayhem_mode else ""
            rune_rec  = _load_rune_rec(champ, gm)
            aram_meta = _load_build_note(champ)
            # (2026-04-26) USER EXPERIMENTAL OVERRIDE - when the champ has a
            # current entry in experimental_builds.json, append it as a hard
            # override hint so Haiku biases item recommendations toward the
            # user's intended experimental build (e.g. on-hit AS Senna).
            try:
                _exp_path = _APP_DIR / "data" / "experimental_builds.json"
                if _exp_path.exists():
                    _exp_data = json.loads(_exp_path.read_text(encoding="utf-8"))
                    _exp_cur = ((_exp_data.get(champ) or {}).get("current") or {})
                    _exp_label = _exp_cur.get("label")
                    _exp_items = _exp_cur.get("items") or []
                    if _exp_label and _exp_items:
                        _exp_line = (
                            f"\n\nUSER EXPERIMENTAL INTENT (HARD OVERRIDE) - label: {_exp_label}. "
                            f"Items pool: {', '.join(_exp_items)}. "
                            "Recommend ONLY items from this pool (complete the most-progressed "
                            "component first; do not pivot to the default "
                            "meta build for this champion this match."
                        )
                        aram_meta = (aram_meta or "unknown") + _exp_line
            except Exception:  # noqa: BLE001
                pass
            try:
                from item_advisor import get_matchup_context as _gmc
                matchup_ctx = _gmc(state.get("enemy_comp", []))
            except Exception:  # noqa: BLE001
                matchup_ctx = ""
            _hint = ""
            if os.environ.get("RC_COACH_ADAPTATION") == "1":
                try:
                    from coaches.adaptation_hint import format_hint_line as _fhl
                    _hint = _fhl(champ, "aram", state.get("enemy_comp", []))
                except Exception:  # noqa: BLE001
                    pass
            system   = _SYSTEM.format(
                profile=profile, mayhem_tag=mayhem,
                rune_rec=rune_rec or "unknown",
                aram_meta=aram_meta or "unknown",
                adaptation_hint=_hint,
            )

            vs = self._vision_state
            _packs_raw = vs.get("hp_packs", [True, True])
            if isinstance(_packs_raw, list) and len(_packs_raw) >= 2:
                _left  = "available" if _packs_raw[0] else "consumed"
                _right = "available" if _packs_raw[1] else "consumed"
                packs_str = f"Left: {_left}, Right: {_right}"
            else:
                packs_str = "unknown"
            event_line = "AUGMENT SELECTION ACTIVE" if vs.get("augment_select") else ""

            # Run DS before Haiku so picks appear in the user turn.
            # Moved from post-Haiku (s74 wire-in) - ds_rows reused below
            # to write daemon_slayer_picks to the output JSON for the UI.
            # s182 (2026-05-13): swapped rank_for() -> archetype dispatcher
            # so the scorer matches the operator's chosen archetype for `champ`
            # (carry/bruiser/tank/mage/assassin/enchanter -> ds.dps/hybrid/ehp/
            # ability/burst/hps).
            _ds_dispatch = None
            _ds_picks_str = "unavailable"
            _ds_label = "DPS"
            try:
                from core.daemon_slayer_resolver import resolve_inventory as _ds_resolve_inventory
                from coach_integration.enemy_stats import compute_enemy_stats as _ds_enemy_stats
                from coach_integration.archetype_dispatch import (
                    dispatch_for_coach as _ds_dispatch_for_coach,
                    display_label as _ds_display_label,
                )
                # Trinkets + consumables share the Live Client inventory array
                # with shop items, so the raw list charges the engine's 6-slot
                # budget for a slot no build item occupies - and the same list
                # is persisted as the calibration row's owned_items below.
                _owned_ids = _ds_resolve_inventory(state.get("items", []), mode="aram")
                _target_bhp = self._estimate_target_bonus_hp(state)
                _lvl = int(state.get("level", 1)) or 1
                # s170: target_armor was hardcoded 80.0; now scales with
                # level + ARAM economy. Item-aware bonus_hp estimator wins
                # when items are visible (passed via override).
                _es = _ds_enemy_stats(
                    mode="aram",
                    game_seconds=int(state.get("game_seconds", 0) or 0),
                    level=_lvl,
                    bonus_hp_override=_target_bhp if _target_bhp > 0 else None,
                    enemy_champions=state.get("enemy_comp", []),
                )
                _ds_dispatch = _ds_dispatch_for_coach(
                    champion=champ,
                    mode_engine="ARAM",
                    level=_lvl,
                    item_ids=_owned_ids,
                    enemy_stats=_es,
                    top=5,
                    # R5 self-HP: absent -> dispatch guard yields 0.0 (OFF).
                    caster_hp=state.get("hp"),
                    caster_hp_max=state.get("hp_max"),
                )
                if _ds_dispatch is not None:
                    _ds_picks_str = _ds_dispatch.picks_str
                    _ds_label = _ds_display_label(_ds_dispatch.scorer)
            except Exception as _ds_exc:  # noqa: BLE001
                logger.debug("ARAM daemon_slayer pre-call: %s", _ds_exc)
            if _ds_dispatch is not None and _ds_dispatch.rows:
                try:
                    from core.ds_calibration import log_ds_run as _ds_log
                    # D-01b: ARAM never surfaces a Live Client game_id, so mint
                    # the shared per-match key (same seam the metric streamer
                    # uses) or these rows stay permanently unjoinable.
                    _ds_mk = live_metrics.match_key(
                        self, {"champion": champ,
                               "game_time_s": state.get("game_seconds")},
                        state, "ARAM")
                    _ds_log(champion=champ, mode="ARAM", level=int(state.get("level", 1)) or 1,
                            owned_items=list(_owned_ids), match_key=_ds_mk,
                            ds_picks=[{"item_id": _r["id"], "item_name": _r["name"],
                                       "delta_dps": _r["delta_dps"], "gold": _r["gold"],
                                       "scorer": _r["scorer"]}
                                      for _r in _ds_dispatch.display_rows])
                except Exception:  # noqa: BLE001
                    pass

            user = _USER_TMPL.format(
                game_time   = state.get("game_time",  "0:00"),
                mayhem_tag  = mayhem,
                hp          = state.get("hp_pct",     100),
                mp          = state.get("mana_pct",   100),
                gold        = state.get("gold",        0),
                lv          = state.get("level",       1),
                kda         = state.get("kda",         "0/0/0"),
                items       = ", ".join(state.get("items", [])) or "none",
                allies      = ", ".join(state.get("ally_comp",  [])) or "unknown",
                enemies     = ", ".join(state.get("enemy_comp", [])) or "unknown",
                enemy_items = state.get("enemy_items", "unknown"),
                matchup_ctx = matchup_ctx or "none",
                dead        = ", ".join(state.get("dead_enemies",  [])) or "none",
                alive       = ", ".join(state.get("alive_enemies", [])) or "all",
                dead_resp   = state.get("dead_respawn_str", "") or "none",
                my_t        = vs.get("my_tower_hp")    if vs.get("my_tower_hp")    is not None else "?",
                en_t        = vs.get("enemy_tower_hp") if vs.get("enemy_tower_hp") is not None else "?",
                augs        = ", ".join(vs.get("augments", [])) or "none",
                packs       = packs_str,
                wave_pct    = vs.get("wave_pct", 50),
                my_abilities = _fmt_abilities(state.get("my_abilities", {})),
                my_runes    = state.get("my_runes",   "") or "unknown",
                enemy_runes = ", ".join(
                    f"{ch}: {ks}" for ch, ks in
                    (state.get("enemy_runes") or {}).items()
                ) or "unknown",
                aram_tenacity = aram_tenacity_line(
                    state.get("champion"), state.get("game_mode", "ARAM")
                ),
                enemy_aram_tenacity = enemy_aram_tenacity_line(
                    state.get("enemy_comp", []),
                    state.get("game_mode", "ARAM"),
                ),
                aram_balance = aram_balance_line(
                    state.get("champion"), state.get("game_mode", "ARAM")
                ),
                enemy_cc_threats = enemy_cc_threat_line(
                    state.get("enemy_comp", []),
                    state.get("game_mode", "ARAM"),
                ),
                cc_blended_ehp_impact = cc_blended_ehp_impact_line(
                    state.get("enemy_comp", []),
                    state.get("game_mode", "ARAM"),
                ),
                cc_conditional_impact = cc_conditional_impact_line(
                    state.get("enemy_comp", []),
                    state.get("game_mode", "ARAM"),
                ),
                ds_picks    = _ds_picks_str,
                ds_label    = _ds_label,
                event_line  = event_line,
            )

            # -- Same-state Haiku-skip debounce (DEFAULT-OFF) --------------
            # When ON, skip the redundant messages.create if the coarse
            # coaching-relevant signature is unchanged AND the cached
            # coaching is younger than the hard max-staleness ceiling. The
            # prior coaching artifact is already on disk (written by the
            # last non-skipped tick) so reuse is a no-op write. When OFF
            # (default) this block is inert and behavior is byte-identical.
            if _STATE_DEBOUNCE:
                import time as _time_dbnc
                _sig = _coach_state_signature(state, vs)
                _last_sig = getattr(self, "_state_dbnc_sig", None)
                _last_ts = getattr(self, "_state_dbnc_ts", 0.0)
                _now_dbnc = _time_dbnc.time()
                if (
                    _last_sig is not None
                    and _sig == _last_sig
                    and (_now_dbnc - _last_ts) < _STATE_DEBOUNCE_MAX_STALE_S
                ):
                    logger.debug(
                        "ARAM state-debounce: signature unchanged "
                        "(age %.1fs < %.0fs ceiling) - reusing cached coaching",
                        _now_dbnc - _last_ts, _STATE_DEBOUNCE_MAX_STALE_S,
                    )
                    return

            _cb = self._overlay.get("coach_bar") if self._overlay else None
            if _cb:
                try:
                    _cb.set_calling()
                except Exception:  # noqa: BLE001
                    pass

            import time as _time_a
            _t0 = _time_a.perf_counter()
            # AUDIT 2026-04-29 (gap E): mark the system prompt with
            # cache_control: ephemeral so subsequent ticks reuse the
            # cached prefix at ~10% of input-token cost. SR coach has
            # this since batch 5 (5.3) but ARAM/Arena/Brawl were
            # missed; in-game telemetry showed cache_r=0 on every call.
            resp = self._client.messages.create(
                model      = "claude-haiku-4-5-20251001",
                max_tokens = 900,
                system     = [{"type": "text", "text": system,
                               "cache_control": {"type": "ephemeral"}}],
                messages   = [{"role": "user", "content": user}],
                timeout    = 20,
            )
            # AUDIT 2026-04-29 (gap A): cost + trace telemetry.
            self._record_coach_call(resp, system=system, user=user,
                                    t0_perf=_t0,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="aram_coach")
            raw  = resp.content[0].text
            # AUDIT 2026-04-26: log raw response so we can diagnose when
            # parse_fields returns empty values (output format drift, etc).
            try:
                logger.info("ARAM Haiku raw (%d chars): %s",
                            len(raw or ""),
                            (raw or "")[:_RAW_LOG_CHARS].replace("\n", " | "))
            except Exception:  # noqa: BLE001
                pass
            flds = parse_fields(raw, [
                "action", "immediate", "fight rule",
                "reset / item", "risk", "item build", "item extra",
                "item reasons", "choices",
            ])
            if not flds:
                logger.warning("ARAM: no fields parsed (raw len=%d)", len(raw or ""))
                return
            if not (flds.get("action") or flds.get("immediate")):
                logger.warning("ARAM: parsed but action+immediate empty. flds keys: %s",
                               list(flds.keys()))

            # Self-spell pair, shaped to match the dashboard's expected
            # `ally_spells[champion] -> [{spell, cd_s}, ...]` envelope.
            # Live cooldowns aren't tracked here yet (cd_s=0); that wires
            # in later when the spell-CD pipeline lands. For now this is
            # enough to flip the header self-spells pill from "D / F"
            # placeholder text to the real Flash/Heal/etc. icons.
            _champ = state.get("champion", "")
            _spell_d = state.get("summoner_d", "")
            _spell_f = state.get("summoner_f", "")
            _ally_spells = (
                {_champ: [{"spell": _spell_d, "cd_s": 0},
                          {"spell": _spell_f, "cd_s": 0}]}
                if _champ and (_spell_d or _spell_f) else {}
            )
            # AUDIT 2026-04-26: server-side fountain scrub.
            # ARAM has no recall - the word "fountain" in Action/Immediate
            # is misleading unless the user has the "Cheater" augment.
            # Strip "FOUNTAIN" from Action label and rewrite Immediate
            # references to "fountain" -> "respawn" so the coach never
            # tells the user to leave lane to base.
            _augs = (state.get("augments") or [])
            _aug_str = ", ".join(_augs) if isinstance(_augs, list) else str(_augs)
            _has_cheater = "cheater" in _aug_str.lower()
            _action_raw = flds.get("action", "")
            _imm_raw    = flds.get("immediate", "")
            if not _has_cheater:
                # Strip leading "FOUNTAIN" tokens from action label.
                import re as _re
                _action_raw = _re.sub(r'\bFOUNTAIN\s*', '', _action_raw, flags=_re.I).strip()
                if not _action_raw or _action_raw.upper() == "FALL BACK":
                    _action_raw = "FALL BACK"
                # Soften "go to fountain" / "return to fountain" in Immediate.
                _imm_raw = _re.sub(
                    r'\b(go|return|sprint|head|walk|run)\s+to\s+(the\s+)?fountain\b',
                    r'fall back to your tower',
                    _imm_raw, flags=_re.I,
                )
                _imm_raw = _re.sub(
                    r'\bfountain\s+now\b', 'fall back', _imm_raw, flags=_re.I,
                )
            # Passthrough for the optional native-emit `choices` JSON array.
            # The model returns a single-line JSON list (per the OUTPUT FORMAT
            # block); parse_fields stores it as a string. from_fields routes it
            # through the model's before-validator and hands back a real Python
            # list, so the dashboard state builder picks it up via
            # core.coach_choices.parse_choices. Malformed / absent input
            # decodes to [] and the synthesizer fallback in _state_builder
            # covers the tick; the choices field is OPTIONAL by contract.
            from core.coach_output import CoachOutput
            _choices_list = CoachOutput.from_fields(flds).choices

            # Deduped build path - hoisted out of the cur.update() literal so
            # the item-interaction cue keys are derived from the SAME string
            # the dashboard strip renders (see _split_item_build_like_ui).
            _item_build_str = _dedup_build_vs_owned(
                flds.get("item build", ""),
                user.split("Items:")[-1].split("\n")[0].strip(),
            )

            cur = load_json(self._out)
            cur.update({
                "action":        _action_raw.upper(),
                "immediate":     _imm_raw,
                "fight_rule":    flds.get("fight rule", ""),
                "positioning":   "",
                "reset_item":    flds.get("reset / item", ""),
                "objective":     flds.get("objective", ""),
                "risk":          flds.get("risk", ""),
                "choices":       _choices_list,
                "game_time":     state.get("game_time",    "0:00"),
                "game_time_s":   state.get("game_seconds",  0),
                "hp_pct":        state.get("hp_pct",        100),
                "kda":           state.get("kda",           "0/0/0"),
                "champion":      _champ,
                "ally_spells":   _ally_spells,
                "items_display": user.split("Items:")[-1].split("\n")[0].strip(),
                "game_mode":     gm,
                "mayhem":        is_mayhem_mode,
                "my_team":       state.get("my_team", "ORDER"),
                # Strip already-owned items from the build path so the
                # Recommended tile never highlights a completed legendary
                # (the "Zhonya's bug" - see _dedup_build_vs_owned docstring).
                "item_build":    _item_build_str,
                "item_extra":    flds.get("item extra", ""),
                # Per-item coach reasons - keyed by item name so the UI
                # can show "why this next" on the Recommended tile hover
                # (opts.reasons -> tile.title in renderItemTiles).
                "item_build_reasons": _parse_item_reasons(flds.get("item reasons", "")),
                # Comp-conditioned item-interaction cues, keyed by the same
                # rendered tile name as item_build_reasons. Fail-soft: the
                # helper never raises, degrading to {} / "".
                # enemy roster source: state["enemy_comp"] (also consumed at
                # the _USER_TMPL fill site, coaches/aram_coach.py:839).
                **_item_interaction_block(
                    _item_build_str,
                    state.get("enemy_comp", []),
                    state.get("game_seconds", 0),
                    gm,
                ),
            })
            mirror_live_stats(cur, state)

            # DS was already called before the Haiku call; reuse _ds_rows
            # to update the UI JSON (daemon_slayer_picks) without a second
            # round-trip to the engine.
            if _ds_dispatch is not None:
                cur["daemon_slayer_picks"] = _ds_dispatch.display_rows

            safe_write(self._out, cur)

            # -- Same-state Haiku-skip debounce: record the signature + ts
            # of THIS just-coached state so the next tick can skip a
            # redundant call. Only tracked when the gate is ON; inert (and
            # byte-identical) when OFF. Computed from the same state/vs that
            # drove this call so the cached artifact matches the signature.
            if _STATE_DEBOUNCE:
                import time as _time_dbnc2
                self._state_dbnc_sig = _coach_state_signature(state, vs)
                self._state_dbnc_ts = _time_dbnc2.time()

            # -- Live metric streaming (feature-flagged) --------------
            # Shared gate + per-match streamer dispatch in core.live_metrics
            # (env RC_LIVE_METRICS=1 OR config live_metrics_enabled). Decides
            # internally whether this tick crosses a milestone + emits 60s
            # periodic samples. Never crashes the coach.
            live_metrics.stream(self, cur, state, self._MODE_NAME)

            if _cb:
                try:
                    _cb.set_done(cur.get("action", ""))
                except Exception:  # noqa: BLE001
                    pass
            try:
                from core.coaching_timestamps import write_coaching_ts as _wts
                _wts("aram")
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:
            raise exc

    @safe_coach_output("ARAM")
    def _handle_augment_select(self, vs: dict) -> None:
        if not self._client:
            return
        gs = self._last_state
        choices = vs.get("augment_choices", [])
        # Canonical Mayhem detection - the live value is "KIWI", which the
        # old '"MAYHEM" in gm' substring check never matched (same bug
        # fixed in _run_coach 2026-05-03; this path was missed).
        mayhem  = " Mayhem" if is_mayhem(gs) else ""
        prompt  = _AUG_SELECT_PROMPT.format(
            mayhem   = mayhem,
            champion = gs.get("champion", "?"),
            hp       = gs.get("hp_pct", 100),
            allies   = ", ".join(gs.get("ally_comp",  [])) or "unknown",
            enemies  = ", ".join(gs.get("enemy_comp", [])) or "unknown",
            # RM-364: a newline inside one OCR choice forges an extra bullet.
            choices  = "\n".join(f"- {c}" for c in _clean_for_prompt(choices)),
        )
        try:
            import time as _time_b
            _t0b = _time_b.perf_counter()
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=250,
                messages=[{"role": "user", "content": prompt}], timeout=15,
            )
            # AUDIT 2026-04-29 (gap A): augment-select call telemetry.
            self._record_coach_call(resp, system="", user=prompt,
                                    t0_perf=_t0b,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="aram_aug_select")
            raw = resp.content[0].text
            cur = load_json(self._out)
            cur.update({
                "augment_select":  True,
                "aug_take":        parse_field(raw, "Take"),
                "aug_why":         parse_field(raw, "Why"),
                "aug_plan":        parse_field(raw, "Gameplan"),
                "augment_choices": choices,
            })
            safe_write(self._out, cur)
        except Exception as exc:
            raise exc


# ==============================================================================
# State parser
# ==============================================================================

def _parse_state(raw: dict) -> dict:
    ap    = raw.get("activePlayer", {})
    gd    = raw.get("gameData", {})
    all_p = [p for p in (raw.get("allPlayers", []) or []) if isinstance(p, dict)]

    game_time = finite(gd.get("gameTime", 0))
    game_mode = gd.get("gameMode", "ARAM")
    mins, secs = int(game_time // 60), int(game_time % 60)

    stats  = ap.get("championStats", {}) or {}
    hp     = int(finite(stats.get("currentHealth",  0)))
    hp_max = int(finite(stats.get("maxHealth",      1), 1))
    mp     = int(finite(stats.get("resourceValue",  0)))
    mp_max = int(finite(stats.get("resourceMax",    1), 1))

    my_name = (ap.get("summonerName") or ap.get("riotIdGameName") or "").split("#")[0]
    me = None
    my_team = "ORDER"
    for p in all_p:
        pn = (p.get("summonerName") or "").split("#")[0]
        if pn == my_name or p.get("championName") == ap.get("championName"):
            me = p
            my_team = p.get("team", "ORDER")
            break

    allies  = [p for p in all_p if p.get("team") == my_team]
    enemies = [p for p in all_p if p.get("team") != my_team]
    sc = ((me or {}).get("scores") or {})
    items = [
        it.get("displayName", "")
        for it in ((me or {}).get("items") or [])
        if isinstance(it, dict) and it.get("displayName")
    ]

    enemy_items_map = {}
    enemies_struct: list[dict] = []
    for _e in enemies:
        _en = _e.get("championName", "?")
        _ei = [
            _it.get("displayName", "")
            for _it in (_e.get("items") or [])
            if isinstance(_it, dict) and _it.get("displayName")
        ]
        if _ei:
            enemy_items_map[_en] = _ei
        # s74 - structured per-enemy entries for daemon_slayer
        # target_bonus_hp estimator. Mirrors arena_coach's teams[] shape
        # (name + is_dead + items) but stays on a separate key so the
        # existing enemy_items / enemy_comp / dead_enemies flat fields
        # used by Haiku prompt + dashboard renderers don't shift.
        enemies_struct.append({
            "name":    _en,
            "is_dead": bool(_e.get("isDead")),
            "items":   _ei,
        })
    enemy_items_str = (
        "; ".join(f"{k}: {', '.join(v)}" for k, v in enemy_items_map.items())
        or "unknown"
    )

    my_runes    = raw.get("my_runes",    "")   # game_reader key (no _ prefix)
    enemy_runes = raw.get("enemy_runes", {})   # game_reader key (no _ prefix)

    return {
        "game_mode":     game_mode,
        "game_time":     f"{mins}:{secs:02d}",
        "game_seconds":  game_time,
        "champion":      (me or ap).get("championName", "Unknown"),
        "hp_pct":        int(100 * hp / max(hp_max, 1)),
        # R5 self-HP: raw numeric hp/hp_max so dispatch_for_coach can derive
        # caster_missing_hp_pct (state.get("hp") was absent -> seam zeroed).
        "hp":            hp,
        "hp_max":        hp_max,
        "mana_pct":      int(100 * mp / max(mp_max, 1)),
        "gold":          int(finite(ap.get("currentGold", 0))),
        "level":         int(finite(ap.get("level", 1), 1)),
        "kda":           f"{sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}",
        "items":         items,
        "my_team":       my_team,
        "ally_comp":     [
            a.get("championName", "?") for a in allies
            if a.get("championName") != (me or {}).get("championName")
        ],
        "enemy_comp":    [e.get("championName", "?") for e in enemies],
        "enemy_items":   enemy_items_str,
        "enemies":       enemies_struct,  # s74 - structured per-enemy {name,is_dead,items}
        "dead_enemies":     [e.get("championName", "?") for e in enemies if e.get("isDead")],
        "alive_enemies":    [e.get("championName", "?") for e in enemies if not e.get("isDead")],
        "dead_respawn_str": raw.get("dead_respawn_str", ""),  # from game_reader
        "my_abilities":  raw.get("my_abilities", {}),
        "my_runes":      my_runes,
        "enemy_runes":   enemy_runes,
    }
