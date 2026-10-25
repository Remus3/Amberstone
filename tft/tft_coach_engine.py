"""
tft/tft_coach_engine.py

Challenger-level TFT coaching engine.
Analyses live game state and produces structured advice for all coaching panels.
Writes structured JSON to data/tft_coaching_data.json for the overlay.
The system prompt is built per resolved set by tft/tft_prompt.py (RM-845).
"""

import json
import logging
import threading
import time
from pathlib import Path

import anthropic

from core import anthropic_key
from core.coaching_payload import tft_advice_payload, tft_blank_payload
from core.polled_json import atomic_write_json

logger = logging.getLogger("rc.tft.coach")

# RM-845: the system prompt is no longer a constant. The hand-written Set 17
# copy that lived here (3471 chars: Realm of Gods round structure, nine gods
# with hand-graded boon tiers) went to every game after RM-840 made Set 18 the
# default. tft/tft_prompt.py now builds it per resolved set from that set's
# ingested data files. (The PBE twin engine that sent the same text was
# deleted by RM-292 (b), 2026-10-25.)


def _system_prompt() -> str:
    """The resolved set's system prompt (tft/tft_prompt.py; never raises)."""
    from tft import tft_prompt
    return tft_prompt.build_system_prompt()


def _set_has_gods() -> bool:
    """True only when the resolved set's meta records Realm of the Gods."""
    try:
        from tft import tft_prompt
        return tft_prompt.set_has_gods()
    except Exception:  # noqa: BLE001
        return False


def _meta_verified() -> bool:
    """True only when the resolved set's meta holds verified comp data.

    RM-845 / RM-846: the meta's comps, trait_augments and double_up sections
    were third-party opinion (tiers, ratings, comp plans) until RM-846 cut
    Set 17 to a skeleton like Set 18. _build_prompt uses those sections only
    behind this gate, so a skeleton - or the same content flagged unverified
    - adds no line rather than a borrowed or invented tier.
    """
    try:
        from tft import tft_prompt
        return tft_prompt.meta_verified()
    except Exception:  # noqa: BLE001
        return False


FIELD_MAP = {
    "action":    "action",
    "board":     "board",
    "econ":      "econ",
    "rolldown":  "rolldown",
    "items":     "items",
    # LANE 8 CYCLE 30 (W1): the Set 17 prompt asks for "God pick:" and the
    # payload contract (core/coaching_payload.TftPayload.god_pick, and the
    # reset defaults in coaches/tft_coach.py) reads god_pick. FIELD_MAP knew
    # only "carousel", so the God pick line matched NO prefix, fell into the
    # continuation branch, and was appended to the PRECEDING field (items).
    # RM-845: the label is per set (tft/tft_prompt.py pick_label) - "God
    # pick" for a Realm of the Gods set, "Carousel" when the set's data names
    # carousel rounds, else "Pick". All three land in god_pick, the one key
    # the payload contract declares.
    "god pick":  "god_pick",
    "carousel":  "god_pick",
    "pick":      "god_pick",
    "placement": "placement",
    "upgrade":   "upgrade",
    "risk":      "risk",
}


# RM-840: one section of the RESOLVED set's meta file (tft/tft_set.py picks
# the set: live set id, then RC_TFT_SET, then the newest ingested set; PBE
# twin when comp_state.json says pbe and the set has one). Cached per
# (path, section), so a set change mid-process reads the new set's file
# instead of serving the first set forever. Before RM-840 both loaders were
# hard-wired to tft_set17_*.json and cached for the process lifetime.
_META_SECTION_CACHE: dict = {}


def _load_meta_section(section: str) -> dict:
    try:
        from tft import tft_set
        path = tft_set.meta_path(pbe=tft_set.pbe_flag())
    except Exception:  # noqa: BLE001
        return {}
    key = (str(path), section)
    if key not in _META_SECTION_CACHE:
        value = tft_set.load_json_file(path).get(section, {})
        _META_SECTION_CACHE[key] = value if isinstance(value, dict) else {}
    return _META_SECTION_CACHE[key]


def _load_trait_augment_data() -> dict:
    """Trait augment definitions of the resolved set (cached per meta path)."""
    return _load_meta_section("trait_augments")


def _load_double_up_rules() -> dict:
    """Double Up rules of the resolved set (cached per meta path)."""
    return _load_meta_section("double_up")


def _build_augment_context(items_str: str, trait_augments: dict, gods: bool = True) -> list:
    """
    Parse active augments from items_str and inject trait augment bonuses.
    Handles three augment name formats:
      1. Standard Heart/Crest/Crown: "Vanguard Heart", "Rogue Crest", "N.O.V.A. Crown"
      2. Reversed: "Heart of Vanguard", "Crest of Rogue"
      3. Realm of the Gods boon: "Soraka God of Stars - Giant's Belt", "Aurelion Sol God of Wonders - Trait Quest"
         - only when ``gods`` (RM-845: the resolved set's meta records that mechanic)
    Returns a list of prompt lines describing each active trait augment and its decision impact.
    """
    if not items_str or not trait_augments:
        return []

    lines = []
    augment_keywords = [p.strip() for p in items_str.split(",") if p.strip()]
    if not augment_keywords:
        return []

    matched_augments = []
    for aug_name in augment_keywords:
        aug_lower = aug_name.lower()

        # Skip clearly non-augment strings
        if len(aug_lower) < 4:
            continue

        # Realm of the Gods boon format: "[God] God of [Domain] - [Item/Effect]"
        # These provide item components, not trait bonuses  -  note them but skip DB match
        if gods and (" god of " in aug_lower or " god " in aug_lower):
            item_part = ""
            if " - " in aug_name:
                item_part = aug_name.split(" - ", 1)[1].strip()
            if item_part:
                lines_buf = [
                    f"  [GOD BOON] {aug_name}",
                    f"    Effect: Provides {item_part} component/item  -  equip on priority carry immediately.",
                ]
                if "trait quest" in aug_lower:
                    lines_buf.append("    Decision: Trait Quest boon  -  activate your dominant trait at max breakpoint to trigger bonus.")
                matched_augments.append(("_god_boon", aug_name, lines_buf))
            continue

        # Try trait augment DB match (Heart/Crest/Crown)
        for trait_name, variants in trait_augments.items():
            if trait_name.startswith("_"):
                continue
            for variant_key, aug_data in variants.items():
                if not isinstance(aug_data, dict):
                    continue
                trait_lower = trait_name.lower()
                variant_lower = variant_key.lower()
                # Match forward ("Vanguard Heart") and reverse ("Heart of Vanguard")
                if ((trait_lower in aug_lower and variant_lower in aug_lower) or
                        (variant_lower in aug_lower and trait_lower in aug_lower)):
                    matched_augments.append((trait_name, variant_key, aug_data))
                    break

    if not matched_augments:
        return []

    lines.append("ACTIVE AUGMENTS  -  DECISION IMPACT:")
    for entry in matched_augments:
        if entry[0] == "_god_boon":
            lines.extend(entry[2])
            continue
        trait_name, variant_key, aug_data = entry
        tier = aug_data.get("tier", "unknown").upper()
        category = aug_data.get("category", "")
        effect = aug_data.get("effect", "")
        decision_note = aug_data.get("decision_note", "")
        impact = aug_data.get("impact", 1)
        best_holders = aug_data.get("best_holders", [])
        pivot = aug_data.get("pivot_threshold", "")
        impact_label = {1: "minor", 2: "notable", 3: "comp-shifting", 4: "WIN-CONDITION"}.get(impact, "")
        lines.append(f"  [{tier}] {trait_name} {variant_key} ({category}, impact={impact_label}): {effect}")
        if decision_note:
            lines.append(f"    Decision: {decision_note}")
        if best_holders:
            lines.append(f"    Best holders: {', '.join(best_holders)}")
        if pivot:
            lines.append(f"    Pivot threshold: {pivot}")

    return lines


def _build_prompt(state: dict) -> str:
    level     = state.get("level", 1)
    stage     = state.get("stage", 1)
    rnd       = state.get("round", 1)
    streak    = state.get("streak", 0)
    event     = state.get("round_event", "pvp")
    is_car    = state.get("is_carousel", False)
    tempo     = state.get("tempo_note", "")
    kills     = state.get("kills", 0)
    deaths    = state.get("deaths", 0)
    alive     = state.get("alive_others", 7)
    dead      = state.get("dead_others", 0)
    items_str = state.get("items_str", "none")
    variant   = state.get("variant", "standard")

    streak_str = (f"WIN+{streak}" if streak > 0
                  else f"LOSS{streak}" if streak < 0 else "NEUTRAL")

    # RM-845: set-specific wording follows the resolved set's data, and the
    # meta's opinion sections are read only from a verified meta.
    _gods = _set_has_gods()
    _pick_noun = "God boon" if _gods else "carousel"
    _verified = _meta_verified()

    round_type = "CAROUSEL" if is_car else ("PVE" if event == "pve" else "PVP")
    max_level_for_stage = {1: 3, 2: 5, 3: 6, 4: 8, 5: 9, 6: 9, 7: 9}.get(stage, 9)

    _live_hp = None; _live_gold = None; _live_traits = ""; _live_board = ""
    _live_augments = []
    try:
        import json as _j
        from pathlib import Path as _P
        _ld = _j.loads((_P(__file__).parent.parent / "data" / "tft_live_data.json").read_text(encoding="utf-8"))
        _live_hp = _ld.get("hp")
        _live_gold = _ld.get("gold") if _ld.get("gold") else None
        _live_traits = ", ".join(_ld.get("traits_active") or [])
        _live_board = ", ".join(u for u in (_ld.get("board_units") or []) if u and u != "empty")
        _live_augments = _ld.get("augments") or []
    except Exception:  # noqa: BLE001
        pass
    hp_display = _live_hp if _live_hp else state.get("health", "?")
    gold_display = _live_gold if _live_gold else "unknown"

    # Resolve partner HP for Double Up
    _partner_hp = state.get("partner_hp", None)
    try:
        from pathlib import Path as _PP
        import json as _pj
        _pd = _pj.loads((_PP(__file__).parent.parent / "data" / "tft_live_data.json").read_text(encoding="utf-8"))
        _partner_hp = _pd.get("partner_hp", _partner_hp)
    except Exception:  # noqa: BLE001
        pass

    lines = [
        f"=== Stage {stage}-{rnd} | Level {level} | Round type: {round_type} ===",
        f"Game time: {int(state.get('game_time_s', 0)//60)}:{int(state.get('game_time_s', 0)%60):02d}",
        f"HP: {hp_display}  Gold: {gold_display}",
        f"Streak: {streak_str}  Rounds won/lost: {kills}/{deaths}",
    ]

    if variant == "double_up":
        partner_hp_str = str(int(_partner_hp)) if _partner_hp is not None else "?"
        player_count = alive + 1
        team_count = (player_count + 1) // 2
        lines.append(f"Players alive: {player_count} ({team_count} teams) | Your HP: {hp_display} | Partner HP: {partner_hp_str}")
        if _partner_hp is not None:
            if int(_partner_hp) < 25:
                lines.append(f"[!]  PARTNER HP CRITICAL ({_partner_hp})  -  donate tank unit immediately")
            elif int(_partner_hp) < 35:
                lines.append(f"Partner HP low ({_partner_hp})  -  consider donating frontline unit")
    else:
        lines.append(f"Players alive: {alive+1} ({dead} eliminated)")

    lines += [
        f"Board size: {level} units | Grid: Row 4=FRONTLINE(enemy side), Row 1=BACKLINE(bench side), Col 1=left Col 7=right",
        f"Max feasible level this stage: {max_level_for_stage}",
    ]

    if _live_traits:
        lines.append(f"Active traits: {_live_traits}")
    if _live_board:
        lines.append(f"Board units: {_live_board}")

    #  -  -  Augment context  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
    # Build augment string from live data or items_str
    _aug_str = ""
    if _live_augments:
        _aug_str = ", ".join(str(a) for a in _live_augments if a)
    elif items_str and items_str != "none":
        _aug_str = items_str

    # Inject trait augment decision data (verified meta only - the ratings
    # in this section were third-party until RM-846 emptied it)
    trait_augment_db = _load_trait_augment_data() if _verified else {}
    augment_context_lines = _build_augment_context(_aug_str, trait_augment_db, gods=_gods)
    if augment_context_lines:
        lines.append("")
        lines.extend(augment_context_lines)

    # XP context for leveling decisions
    from tft.tft_data import XP_TO_LEVEL, XP_BUY_COST
    next_lv = level + 1
    if next_lv <= 10:
        xp_needed = XP_TO_LEVEL.get(next_lv, 0)
        gold_for_level = (xp_needed // XP_BUY_COST) * XP_BUY_COST
        lines.append(f"XP to Lv{next_lv}: {xp_needed}XP = ~{xp_needed//XP_BUY_COST} buys ({gold_for_level}g at {XP_BUY_COST}g each)")

    # Interest context from vision
    if _live_gold and isinstance(_live_gold, (int, float)) and _live_gold > 0:
        _interest = min(5, int(_live_gold) // 10)
        lines.append(f"Current gold: {int(_live_gold)}g | Interest: +{_interest}g/round | {'AT CAP' if _interest >= 5 else f'Next bracket: {(_interest+1)*10}g'}")

    if is_car:
        lines.append(f"CAROUSEL ROUND: Do NOT suggest rolling or leveling  -  only {_pick_noun} pick advice.")
        try:
            import json as _json
            from pathlib import Path as _Path
            _live = _json.loads((_Path(__file__).parent.parent / "data" / "tft_live_data.json").read_text(encoding="utf-8"))
            _comp = _live.get("comp", "") or ""
            _traits = ", ".join(_live.get("traits_active") or [])
            if _comp or _traits:
                lines.append(f"Current comp: {_comp}  Active traits: {_traits}")
                lines.append(f"{_pick_noun.capitalize()} advice: recommend completed items for this carry, or emblems for active traits.")
        except Exception:  # noqa: BLE001
            pass

    if event == "pve":
        lines.append("PVE ROUND: No opponent to position against  -  focus on econ/leveling decisions.")
    if tempo:
        lines.append(f"Milestone: {tempo}")

    if variant == "hyper_roll":
        lines += [
            "",
            "MODE: HYPER ROLL  -  Gold cap 10g. No interest economy. Roll every round.",
            "Hyper Roll rules: ALWAYS roll  -  never save gold. Prioritize 3-starring cheap units.",
            "Win condition: 3-star a 1-2 cost carry ASAP. Reroll aggressively every round.",
        ]
    elif variant == "double_up":
        du_rules = _load_double_up_rules() if _verified else {}
        coord_signals = du_rules.get("coordination_signals", {})
        if not isinstance(coord_signals, dict):
            coord_signals = {}
        lines += [
            "",
            "MODE: DOUBLE UP (PBE)  -  Playing with a partner. Shared HP pool.",
            "Coordination: ONE player AD carry, ONE player AP carry. Do not contest partner reroll targets.",
            "Donation rule: Send overflow units + 2nd tank if partner HP < 30.",
        ]
        if coord_signals:
            lines.append("Donation signals: " + " | ".join(f"{k}: {v}" for k, v in list(coord_signals.items())[:3]))

    lines += [
        "",
        f"Your items/augments: {items_str}",
    ]

    #  -  -  Selected comp context (from overlay comp selector)  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
    try:
        # Phase 7 P1-A PBE-aware meta path; RM-840: the set comes from
        # tft/tft_set.py, never a hard-wired tft_set17_*.json.
        from tft import tft_set as _ts
        _cs = _ts.comp_state()
        _meta_file = _ts.meta_path(pbe=bool(_cs.get("pbe", False)))
        if _cs and _meta_file.exists():
            _comp_name = _cs.get("selected", "")
            _ignore_emb = _cs.get("ignore_emblems", False)
            # RM-845: a comp is cited only from a verified meta. On a
            # skeleton (Set 17 and 18 since RM-846) a stale comp_state
            # selection adds no line, so no comp plan is borrowed or invented.
            if _comp_name and _verified:
                _meta = _ts.load_json_file(_meta_file)
                _comps = _meta.get("comps")
                _cd = _comps.get(_comp_name, {}) if isinstance(_comps, dict) else {}
                if _cd and isinstance(_cd, dict):
                    _lvplan = _cd.get("level_plan", "")
                    _gplan  = _cd.get("gameplan", "")
                    _core   = ", ".join(_cd.get("core_units", [])[:5])
                    _lv9    = ", ".join(_cd.get("lv9", [])[:9])
                    _aug    = _cd.get("augment_advice", {})
                    _items_d= _cd.get("items", {})
                    _pivot  = _cd.get("pivot_conditions", "")
                    # Build comp section
                    lines.append("")
                    lines.append(f"SELECTED COMP: {_comp_name}")
                    if _lvplan: lines.append(f"  Level plan: {_lvplan}")
                    if _gplan:  lines.append(f"  Gameplan: {_gplan}")
                    if _core:   lines.append(f"  Core units: {_core}")
                    if _lv9:    lines.append(f"  Lv9 board: {_lv9}")
                    if _pivot:  lines.append(f"  Pivot trigger: {_pivot}")
                    # BIS items per carry
                    _built = _cs.get("built_items", {})
                    if _built:
                        _bl = [f"{k}: {v}" for k,v in _built.items() if v]
                        if _bl:
                            lines.append(f"  BUILT ITEMS (equipped): {' | '.join(_bl[:6])}")
                            lines.append("  Do NOT re-recommend already-built items.")
                    if _items_d and not _cs.get("ignore_emblems", False):
                        _bis_lines = []
                        for _u, _ui in list(_items_d.items())[:4]:
                            _bis = ", ".join((_ui.get("bis") or [])[:3])
                            if _bis: _bis_lines.append(f"{_u}: {_bis}")
                        if _bis_lines:
                            lines.append(f"  BIS items: {' | '.join(_bis_lines)}")
                    # Phase 7 P2-A: suppress emblem advice when ignore_emblems=True
                    _ignore_emb = _cs.get("ignore_emblems", False)

                    # Augment priorities
                    if _aug and not _ignore_emb:
                        _pris = ", ".join((_aug.get("prismatic") or [])[:3])
                        _gold = ", ".join((_aug.get("gold") or [])[:3])
                        if _pris: lines.append(f"  Prismatic augments: {_pris}")
                        if _gold: lines.append(f"  Gold augments: {_gold}")
                    # Pivot advice vs current board
                    if _live_traits and _comp_name:
                        _ct_lower = _live_traits.lower()
                        _expected_traits = [t.lower() for t in (_cd.get("core_units", []) or [])]
                        lines.append("  Tailor all advice (Board/Items/Econ/Upgrade) to this comp.")
                        lines.append(f"  If current traits diverge significantly from {_comp_name}, advise pivot in Upgrade field.")
    except Exception:  # noqa: BLE001
        pass

    from tft.tft_data import TIER_ODDS
    next_lvl = level + 1
    if next_lvl <= 10:
        odds_now  = TIER_ODDS.get(level, {})
        odds_next = TIER_ODDS.get(next_lvl, {})
        lines += [
            "",
            f"Roll odds at Lv{level}: " +
                "  ".join(f"{c}c={v:.0%}" for c, v in odds_now.items() if v > 0),
            f"Roll odds at Lv{next_lvl}: " +
                "  ".join(f"{c}c={v:.0%}" for c, v in odds_next.items() if v > 0),
        ]

    return "\n".join(lines)


def _parse_response(text: str, *, gods: bool | None = None) -> dict:
    """Model reply -> payload fields. ``gods`` None = the resolved set's
    (RM-845): only a Realm of the Gods set rewrites "carousel" to "God boon"."""
    import re
    if gods is None:
        gods = _set_has_gods()
    fields      = {}
    current_key = None
    current_val = []

    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)

    for line in text.strip().splitlines():
        s = line.strip()
        if not s:
            continue
        matched = False
        for prefix, key in FIELD_MAP.items():
            if s.lower().startswith(prefix + ":"):
                if current_key:
                    fields[current_key] = " ".join(current_val).strip()
                current_key = key
                current_val = [s[len(prefix)+1:].strip()]
                matched = True
                break
        if not matched and current_key:
            current_val.append(s)

    if current_key:
        fields[current_key] = " ".join(current_val).strip()

    _CUTOFF = ("---", "**context", "**reasoning", "context:",
               "reasoning:", "note:", "explanation:")
    _BANNED  = ("placeholder", "<placeholder>", "[placeholder]",
                "blank", "n/a", "<none>", "[none]")
    for key, val in list(fields.items()):
        if not val:
            continue
        val = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', val)
        lower = val.lower()
        if lower.strip() in _BANNED:
            fields[key] = ""
            continue
        for marker in _CUTOFF:
            idx = lower.find(marker)
            if idx > 10:
                val = val[:idx].rstrip(" .-")
                lower = val.lower()
        if len(val) > 150:
            val = val[:147].rstrip() + "..."
        fields[key] = val.strip()

    if "action" in fields:
        fields["action"] = re.sub(r'[^A-Z0-9 /]', '',
                                   fields["action"].upper()).strip()

    # Strip "contested" from all fields
    for _fkey in list(fields.keys()):
        _fval = fields.get(_fkey, "")
        if isinstance(_fval, str) and "contested" in _fval.lower():
            for _cw in ["heavily contested", "highly contested", "contested", "Contested"]:
                _fval = _fval.replace(_cw, "uncertain")
            fields[_fkey] = _fval

    # A Realm of the Gods set has no carousel: replace "carousel" with
    # "God boon". RM-845: ONLY for such a set - this ran for every set, so it
    # rewrote real carousel advice in a Set 18 game.
    if gods:
        for _fk2 in list(fields.keys()):
            _fv2 = fields.get(_fk2, "")
            if isinstance(_fv2, str) and "carousel" in _fv2.lower():
                _fv2 = _fv2.replace("carousel", "God boon").replace("Carousel", "God boon").replace("CAROUSEL", "GOD BOON")
                fields[_fk2] = _fv2
        if fields.get("action", "").upper() in ("CAROUSEL PICK", "CAROUSEL"):
            fields["action"] = "GOD BOON"

    # Validate ACTION against current stage
    _stage = 0
    try:
        _sr = fields.get("_stage_round", "")
        if "-" in str(_sr):
            _sp = str(_sr).split("-")
            _stage = int(_sp[0])
    except Exception:  # noqa: BLE001
        pass

    _action = fields.get("action", "").upper()
    if "LEVEL 9" in _action and _stage < 5:
        fields["action"] = "LEVEL 8" if _stage >= 4 else "PLAY STRONGEST BOARD"
    if "LEVEL 8" in _action and _stage < 3:
        fields["action"] = "PLAY STRONGEST BOARD"
    if "LEVEL 7" in _action and _stage < 3:
        fields["action"] = "PLAY STRONGEST BOARD"

    for _ek in ["econ", "rolldown", "upgrade"]:
        _ev = fields.get(_ek, "")
        if isinstance(_ev, str):
            if "level 9" in _ev.lower() and _stage < 5:
                fields[_ek] = _ev.replace("level 9", "hold").replace("Level 9", "hold").replace("LEVEL 9", "hold")

    _action = fields.get("action", "").upper()
    if "LEVEL 9" in _action:
        fields["action"] = "PLAY STRONGEST BOARD"

    for _ek in ["econ", "rolldown", "upgrade"]:
        _ev = fields.get(_ek, "")
        if isinstance(_ev, str) and "7-5" in _ev:
            fields[_ek] = _ev.replace("7-5", "7-3")

    # Sanitize hallucinated rounds
    import re as _re
    _max_rnd = {1: 3}
    for _fk in ("econ", "rolldown", "upgrade", "risk"):
        _fv = fields.get(_fk, "")
        if not _fv:
            continue
        for _rm in _re.finditer(r'(\d)-(\d+)', _fv):
            _s, _r = int(_rm.group(1)), int(_rm.group(2))
            _mr = _max_rnd.get(_s, 5)
            if _r > _mr:
                _ns, _nr = _s + 1, 1
                fields[_fk] = _fv.replace(_rm.group(0), f"{_ns}-{_nr}")

    return fields


class TftCoachEngine:
    def __init__(self, data_file: Path, debug: bool = False) -> None:
        self._data_file   = data_file
        self._debug       = debug
        self._lock        = threading.Lock()
        self._last_call   = 0.0
        self._last_round  = (0, 0)
        self._last_fields: dict = {}

        # ENV-APIKEY (s112): the ONE shared lookup (env first VALID, then the
        # repo-root key file), replacing a private `env or _read_key_file()`.
        api_key = anthropic_key.read_anthropic_key()
        self._client = anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com") if api_key else None

        cfg_path = Path(__file__).parent.parent / "config" / "coach_settings.json"
        self._model      = "claude-haiku-4-5-20251001"
        self._debounce_s = 45.0   # raised from 15s  -  fires once per round + max 1 urgent/30s
        self._timeout    = 20
        self._max_tokens = 600    # reduced from 800  -  9 short fields don't need more
        if cfg_path.exists():
            try:
                self._apply_config(json.loads(cfg_path.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001
                logger.warning("coach_settings.json unreadable, using defaults: %s", exc)

        # LANE 8 CYCLE 30 (W7): this line used to say "ready" unconditionally.
        # With no API key `submit()` returns immediately at every call, so a
        # key-less box logged a healthy start and then silently never coached -
        # byte-identical, from outside, to a working engine.
        if self._client is None:
            logger.warning(
                "TftCoachEngine DISABLED: no API key (checked ANTHROPIC_API_KEY "
                "and API-Key-Claude.txt) - TFT text coaching will not run")
        else:
            logger.info("TftCoachEngine ready [v3-trait-augments] (model=%s debounce=%.0fs)",
                        self._model, self._debounce_s)

    def _apply_config(self, cfg: dict) -> None:
        """Adopt coach_settings.json values, rejecting anything unusable.

        LANE 8 CYCLE 30 (W9): these were adopted verbatim. A string
        `debounce_seconds` made `(now - self._last_call) < self._debounce_s`
        raise TypeError out of submit() and into the TFT poll loop; a
        non-positive `max_tokens` or `timeout` is refused by the API on every
        call. A bad config value degrades to the default, loudly.
        """
        if not isinstance(cfg, dict):
            logger.warning("coach_settings.json is not an object, using defaults")
            return

        def _num(key, current, *, minimum, maximum, cast):
            if key not in cfg:
                return current
            val = cfg[key]
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                logger.warning("coach_settings.%s must be a number, got %r - keeping %r",
                               key, val, current)
                return current
            if not (minimum <= val <= maximum):
                logger.warning("coach_settings.%s out of range [%s, %s], got %r - keeping %r",
                               key, minimum, maximum, val, current)
                return current
            return cast(val)

        model = cfg.get("model", self._model)
        if isinstance(model, str) and model.strip():
            self._model = model
        elif "model" in cfg:
            logger.warning("coach_settings.model must be a non-empty string, got %r - keeping %r",
                           model, self._model)

        self._debounce_s = _num("debounce_seconds", self._debounce_s,
                                minimum=0, maximum=3600, cast=float)
        self._timeout    = _num("timeout", self._timeout,
                                minimum=1, maximum=600, cast=float)
        self._max_tokens = _num("max_tokens", self._max_tokens,
                                minimum=1, maximum=8192, cast=int)

    @staticmethod
    def _coerce_hp(value):
        """One definition of a usable vision HP reading, shared by the urgency
        gate and the rendered payload.

        LANE 8 CYCLE 30 (W10): submit() accepted a STRING hp for the urgency
        decision while _write_fields rejected it for the payload, so the two
        halves disagreed about the same file; and _write_fields' isinstance
        check accepted a BOOL, because bool subclasses int, rendering
        `"hp": true` as 1 HP (critical).
        """
        if isinstance(value, bool) or value is None:
            return None
        try:
            hp = float(value)
        except (TypeError, ValueError):
            return None
        if not (0 < hp <= 100):
            return None
        return int(hp)

    def _vision_hp(self, loader=None):
        """Read hp from data/tft_live_data.json, or None if unusable."""
        try:
            if loader is not None:
                data = loader()
            else:
                path = Path(__file__).parent.parent / "data" / "tft_live_data.json"
                data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return self._coerce_hp(data.get("hp"))
        except Exception:  # noqa: BLE001
            return None

    def _resolve_hp(self, state: dict, default: int = 100) -> int:
        """Vision HP wins, then API state, then the default."""
        vision = self._vision_hp()
        if vision is not None:
            return vision
        api = self._coerce_hp(state.get("health"))
        if api is not None:
            return api
        return default

    def submit(self, state: dict) -> None:
        if not self._client:
            return
        now       = time.time()
        sr        = (state.get("stage", 0), state.get("round", 0))
        # Use vision HP for urgency check when API health is unavailable
        hp = self._resolve_hp(state)
        new_round = sr != self._last_round
        # Urgent: HP critical, but cap at one call per 30s to prevent end-game burst
        urgent    = hp <= 30 and (now - self._last_call) >= 30.0

        if new_round:
            pass  # new round always fires once
        elif urgent:
            pass  # HP critical fires at most every 30s
        elif (now - self._last_call) < self._debounce_s:
            return

        self._last_round = sr
        self._last_call  = now
        threading.Thread(target=self._run_safe, args=(state,),
                         daemon=True, name="TftCoach").start()

    def reset_state(self) -> None:
        self._last_round  = (0, 0)
        self._last_call   = 0.0
        self._last_fields = {}
        # Phase 6 Step 2 Fix 7: write blank TFT coaching artifact on reset
        # so stale TFT advice from the previous game is not visible.
        # RM-292 (d): the blank is the declared TftPayload shape, not a
        # hand-copied literal. Its numbers are overlay-neutral (0), where the
        # literal's level 1 pinned the dashboard level and its stage 1 fed
        # performance_tracker's stage fallback a stage nobody measured.
        # alive_others is not declared (an undeclared key's default is its
        # own decision), so the blank omits it and save_tft_rating keeps its
        # .get default of 7 - the same placement the old literal produced.
        try:
            atomic_write_json(self._data_file, tft_blank_payload())
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to reset TFT coaching data: %s", exc)

    def shutdown(self) -> None:
        logger.info("TftCoachEngine shutdown")

    def _run_safe(self, state: dict):
        if not self._lock.acquire(blocking=False):
            logger.debug("TFT coach busy  -  skipping")
            return
        try:
            self._run(state)
        except Exception as exc:  # noqa: BLE001
            # Raw exception goes to the log only - the risk field rendered by
            # _write_status is user-facing, so degrade to a friendly message.
            logger.error("TFT coach error: %s", exc)
            self._write_status("Coaching paused - retrying")
        finally:
            self._lock.release()

    def _run(self, state: dict):
        # Spend-gate: TFT Anthropic calls off via Settings kill-switch.
        # LANE 8 CYCLE 30 (W8): this used to `pass` on any failure, so a
        # broken cost_tracker import turned the operator's spend kill-switch
        # into a no-op and the paid call went out anyway. Fail CLOSED.
        try:
            from core.cost_tracker import get_tracker as _gt
            if _gt().gate_disabled("tft"):
                return
        except Exception as exc:  # noqa: BLE001
            logger.error("TFT spend-gate unavailable, refusing to call: %s", exc)
            return
        t0     = time.time()
        prompt = _build_prompt(state)
        if self._debug:
            logger.debug("TFT prompt:\n%s", prompt)

        # LANE 8 CYCLE 30 (W6): self._timeout was assigned twice and read
        # nowhere, so this call carried only the SDK default. _run_safe holds
        # self._lock across it, so one hung request wedged the TFT coach and
        # every later submit logged "busy - skipping" for the duration.
        response = self._client.messages.create(
            model      = self._model,
            max_tokens = self._max_tokens,
            timeout    = self._timeout,
            system     = [{"type": "text", "text": _system_prompt(),
                           "cache_control": {"type": "ephemeral"}}],
            messages   = [{"role": "user", "content": prompt}],
        )
        # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker. POLLING
        # cadence (45s debounce) - the biggest untracked HAIKU lane.
        try:
            from core.cost_tracker import record_anthropic_response
            record_anthropic_response(response, model=self._model, purpose="tft_coach")
        except Exception as exc:  # noqa: BLE001
            logger.debug("cost_tracker record: %s", exc)
        latency = int((time.time() - t0) * 1000)
        raw     = response.content[0].text
        logger.info("TFT coach response in %dms", latency)
        if self._debug:
            logger.debug("TFT response:\n%s", raw)
        self._write_fields(raw, state)

    def _write_fields(self, raw: str, state: dict):
        fields = _parse_response(raw)
        # LANE 8 CYCLE 30 (W5): `fields["_stage_round"]` used to be assigned
        # HERE, one line above the guard, so `not fields` could never be true
        # and the guard below was dead code. An unparseable response therefore
        # blanked every field on the overlay instead of retaining the last good
        # advice, and the diagnostic warning never once fired.
        if not fields:
            logger.warning("TFT: no fields parsed from response (first 200 chars): %s",
                           raw[:200].replace("\n", " | "))
            return
        fields["_stage_round"] = state.get("stage_round", "")

        _WATCH = ("action", "board", "econ", "rolldown", "items",
                  "god_pick", "placement", "upgrade", "risk")
        if self._last_fields:
            changed = any(fields.get(k) != self._last_fields.get(k) for k in _WATCH)
            if not changed:
                logger.debug("TFT: advice unchanged, skipping overlay write")
                return
        self._last_fields = dict(fields)

        # Resolve authoritative HP: prefer vision HP, fallback to API state, fallback to 100
        _out_hp = self._resolve_hp(state)

        output = {
            "mode":         "tft",
            "game_time_s":  state.get("game_time_s",  0),
            "stage":        state.get("stage",         1),
            "round":        state.get("round",         1),
            "level":        state.get("level",         1),
            "gold":         state.get("gold",          0),
            "health":       _out_hp,
            "stage_round":  state.get("stage_round",   ""),
            "kills":        state.get("kills",         0),
            "deaths":       state.get("deaths",        0),
            "alive_others": state.get("alive_others",  7),
            "items_str":    state.get("items_str",     ""),
            "traits_str":   state.get("traits_str",    ""),
            "board_str":    state.get("board_str",     ""),
            "bench_str":    state.get("bench_str",     ""),
            "shop_str":     state.get("shop_str",      ""),
            "variant":      state.get("variant",       "standard"),
            "partner_hp":   state.get("partner_hp",    None),
            "action":       fields.get("action",       ""),
            "board":        fields.get("board",        ""),
            "econ":         fields.get("econ",         ""),
            "rolldown":     fields.get("rolldown",     ""),
            "items":        fields.get("items",        ""),
            "god_pick":     fields.get("god_pick",     ""),
            "placement":    fields.get("placement",    ""),
            "upgrade":      fields.get("upgrade",      ""),
            "risk":         fields.get("risk",         ""),
        }

        try:
            atomic_write_json(self._data_file, output)
            logger.debug("TFT coaching data written (%d fields)", len(fields))
            # arch: phase 3 step 1.1 - write TFT coaching timestamp only after payload write succeeds
            # Mirrors SR/ARAM/Arena/Brawl successful-write semantics.
            try:
                from core.coaching_timestamps import write_coaching_ts as _wcts
                _wcts("tft")
            except Exception:  # noqa: BLE001
                pass  # non-fatal
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write TFT coaching data: %s", exc)

    def _write_status(self, msg: str):
        """Degraded-mode payload. `msg` is ALWAYS a friendly string chosen by
        the caller - never raw API error text (CLAUDE.md "Error Handling").

        LANE 8 CYCLE 30 (RM-211): this wrote the polled destination DIRECTLY -
        no scratch file, no rename - so a poller mid-read saw a truncated
        artifact. The sibling PBE engine (deleted by RM-292 (b), 2026-10-25)
        had carried the atomic fix since 2026-04-27; the audit that fixed the
        twin missed the LIVE engine.

        RM-292 (d): the keys are the ADVICE shape (core.coaching_payload
        ``tft_advice_payload``: mode, action and the advice strings), the
        same shape as the disabled placeholder. This docstring used to say
        they "mirror the reset payload"; they never did, and they must not:
        this write lands MID-GAME, and a numeric seed key would render as 0
        on the dashboard wherever the live value is absent.
        """
        try:
            payload = tft_advice_payload(action="ERROR", risk=msg)
            atomic_write_json(self._data_file, payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write TFT status payload: %s", exc)
