"""
tft/tft_coach_engine.py

Challenger-level TFT coaching engine.
Analyses live game state and produces structured advice for all coaching panels.
Writes structured JSON to data/tft_coaching_data.json for the overlay.
"""

import json
import logging
import threading
import time
from pathlib import Path

import anthropic

logger = logging.getLogger("rc.tft.coach")

TFT_SYSTEM_PROMPT = """\
Challenger TFT Set 17 "Space Gods" Double Up coach. Max density, no padding.

ROUND STRUCTURE: Stage 1=3 rounds. Stages 2-7: X-1/2/3=PvP, X-4=Realm of Gods (NOT carousel), X-5=PvE, X-6=PvP, 4-7=God Boon armory. NO carousels in Set 17. Never say "carousel" â€” say "God boon"/"Realm of Gods".

LEVEL TIMING: Lv6@3-2, Lv7@4-1, Lv8@4-2(rolldown), Lv9@5-1+. Fast8=Lv8@4-1 with 50g+. Fast9=Lv9@5-1 needs econ aug or winstreak. HP<35=roll now, board>econ. Never suggest Lv9 before stage 5.

AUGMENTS: Heart=+1 trait (free slot). Crest=emblem item (commit to that trait). Crown=emblem+bonus (hard pivot). Prismatic>Gold>Silver. Reflect augment in Action/Items/Econ/Upgrade every call. Never invent augment names.

DOUBLE UP: Shared HP pool. Placement field MUST have donation note every round ("Donate X to partner" / "Hold"). Partner HP<30=donate 2nd tank now. Never contest partner reroll targets. Stagger rolldowns. Split AD/AP carry between boards.

BOARD (Row A=front/enemy, D=back/bench, cols 1-7): Tanks A-row spread wide (A1,A3,A5). Ranged carry D6-7. Melee carry B-row. Support C-row near carry. Anti-assassin: move carry to D1. HP>40=fine. HP<35=low pressure. HP<25=critical. Stage 1 HP=100 (vision error if lower).

COMP ID: Name after dominant trait (most units). 1-unit splash = ignore. Crest/Crown active = comp named after that trait. Commit to ID once set.

FEASIBILITY: Never suggest actions that require gold you don't have. No PvP tips during PVE rounds. No board swaps during God rounds.

GOD ALIGNMENT (Set 17 mechanic â€” replaces carousel):
  Stage X-4 = choose between 2 god offerings. Stage 4-7 = God Boon armory. Every offering includes a component.
  ALIGN RULE: Take same god â‰¥2 times on stages 2/3/4 to unlock their Boon at 4-7.
  
  9 GODS â€” tier and strategy:
  S-TIER BOONS (take these):
  â€¢ Evelynn (Temptation): Instinct artifact boon. Strong frontline-light boards. Execute + AS burst.
  â€¢ Yasuo (Abyss): Empowers hexes. Best for comps that want hex positioning (Stargazer, Conduit).
  
  A-TIER BOONS:
  â€¢ Ekko (???): Delayed value â€” delayed components/power. Prioritize when loss-streaking.
  â€¢ Varus (Love): Offers 3/4/5-cost unit selectors. Best when you need a specific 4-5 cost.
  â€¢ Soraka (Stars): HP-focused. Soraka's Miracle artifact. Best when HP-pressured or loss-streaking.
  
  B-TIER BOONS:
  â€¢ Ahri (Opulence): Gold/econ boons. Good for fast-9 boards. Foxfire artifact for AP carries.
  â€¢ Aurelion Sol (Wonders): Quest boon â€” complete trait breakpoints for bonus. Risky/conditional.
  â€¢ Kayle (Exaltation): Extra components. Kayle's Exaltation artifact â€” radiant items after 18s.
  â€¢ Thresh (???): Pulls bench unit to board. Thresh's Lantern artifact â€” redirects damage.
  
  OFFERING CHOICE: Take the offering that best fits current streak/board state.
  Win streak â†' take combat-power offering. Loss streak â†' take econ/delayed-value offering.
  Pengu offering: higher cost units if HP is low (catch-up mechanism).



OUTPUT â€” 9 fields only, no markdown, no bullets, max 15 words each:
Action: ALL-CAPS 1-3 words
Board: actual unit names + grid positions (tanks A wide, carries D6-7)
Econ: level/gold timing
Rolldown: trigger + stagger note
Items: component names + holder
God pick: Realm of Gods offering choice (componentâ†'carry; God Boonâ†'best boon for comp)
Placement: anti-flank + Double Up donation/request (required every round)
Upgrade: pivot trigger
Risk: single threat (include partner HP if critical)
"""

FIELD_MAP = {
    "action":    "action",
    "board":     "board",
    "econ":      "econ",
    "rolldown":  "rolldown",
    "items":     "items",
    "carousel":  "carousel",
    "placement": "placement",
    "upgrade":   "upgrade",
    "risk":      "risk",
}


def _load_trait_augment_data() -> dict:
    """Load trait augment definitions -- cached at module level after first call."""
    if _load_trait_augment_data._cache is None:
        try:
            # Phase 7 P1-A: PBE-aware meta path
            _cs = Path(__file__).parent.parent / "data" / "comp_state.json"
            try:
                import json as _jx
                _pbe = _jx.loads(_cs.read_text(encoding="utf-8")).get("pbe", False) if _cs.exists() else False
            except Exception:
                _pbe = False
            _mfn = "tft_set17_pbe_meta.json" if _pbe else "tft_set17_meta.json"
            meta_path = Path(__file__).parent.parent / "data" / "meta" / _mfn
            if not meta_path.exists():
                meta_path = Path(__file__).parent.parent / "data" / "meta" / "tft_set17_meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            _load_trait_augment_data._cache = meta.get("trait_augments", {})
        except Exception:
            _load_trait_augment_data._cache = {}
    return _load_trait_augment_data._cache

_load_trait_augment_data._cache = None


def _load_double_up_rules() -> dict:
    """Load Double Up rules -- cached at module level after first call."""
    if _load_double_up_rules._cache is None:
        try:
            # Phase 7 P1-A: PBE-aware meta path
            _cs = Path(__file__).parent.parent / "data" / "comp_state.json"
            try:
                import json as _jy
                _pbe = _jy.loads(_cs.read_text(encoding="utf-8")).get("pbe", False) if _cs.exists() else False
            except Exception:
                _pbe = False
            _mfn = "tft_set17_pbe_meta.json" if _pbe else "tft_set17_meta.json"
            meta_path = Path(__file__).parent.parent / "data" / "meta" / _mfn
            if not meta_path.exists():
                meta_path = Path(__file__).parent.parent / "data" / "meta" / "tft_set17_meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            _load_double_up_rules._cache = meta.get("double_up", {})
        except Exception:
            _load_double_up_rules._cache = {}
    return _load_double_up_rules._cache

_load_double_up_rules._cache = None


def _build_augment_context(items_str: str, trait_augments: dict) -> list:
    """
    Parse active augments from items_str and inject trait augment bonuses.
    Handles three augment name formats:
      1. Standard Heart/Crest/Crown: "Vanguard Heart", "Rogue Crest", "N.O.V.A. Crown"
      2. Reversed: "Heart of Vanguard", "Crest of Rogue"
      3. Set 17 God boon: "Soraka God of Stars - Giant's Belt", "Aurelion Sol God of Wonders - Trait Quest"
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

        # Handle Set 17 God boon format: "[God] God of [Domain] - [Item/Effect]"
        # These provide item components, not trait bonuses â€” note them but skip DB match
        if " god of " in aug_lower or " god " in aug_lower:
            item_part = ""
            if " - " in aug_name:
                item_part = aug_name.split(" - ", 1)[1].strip()
            if item_part:
                lines_buf = [
                    f"  [GOD BOON] {aug_name}",
                    f"    Effect: Provides {item_part} component/item â€” equip on priority carry immediately.",
                ]
                if "trait quest" in aug_lower:
                    lines_buf.append("    Decision: Trait Quest boon â€” activate your dominant trait at max breakpoint to trigger bonus.")
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

    lines.append("ACTIVE AUGMENTS â€” DECISION IMPACT:")
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

    round_type = "CAROUSEL" if is_car else ("PVE" if event == "pve" else "PVP")
    max_level_for_stage = {1: 3, 2: 5, 3: 6, 4: 8, 5: 9, 6: 9, 7: 9}.get(stage, 9)

    _live_hp = None; _live_gold = None; _live_traits = ""; _live_board = ""
    _live_augments = []
    try:
        import json as _j
        from pathlib import Path as _P
        _ld = _j.loads((_P(__file__).parent.parent / "data" / "tft_live_data.json").read_text())
        _live_hp = _ld.get("hp")
        _live_gold = _ld.get("gold") if _ld.get("gold") else None
        _live_traits = ", ".join(_ld.get("traits_active") or [])
        _live_board = ", ".join(u for u in (_ld.get("board_units") or []) if u and u != "empty")
        _live_augments = _ld.get("augments") or []
    except Exception:
        pass
    hp_display = _live_hp if _live_hp else state.get("health", "?")
    gold_display = _live_gold if _live_gold else "unknown"

    # Resolve partner HP for Double Up
    _partner_hp = state.get("partner_hp", None)
    try:
        from pathlib import Path as _PP
        import json as _pj
        _pd = _pj.loads((_PP(__file__).parent.parent / "data" / "tft_live_data.json").read_text())
        _partner_hp = _pd.get("partner_hp", _partner_hp)
    except Exception:
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
                lines.append(f"âš  PARTNER HP CRITICAL ({_partner_hp}) â€” donate tank unit immediately")
            elif int(_partner_hp) < 35:
                lines.append(f"Partner HP low ({_partner_hp}) â€” consider donating frontline unit")
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

    # â”€â”€ Augment context â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Build augment string from live data or items_str
    _aug_str = ""
    if _live_augments:
        _aug_str = ", ".join(str(a) for a in _live_augments if a)
    elif items_str and items_str != "none":
        _aug_str = items_str

    # Inject trait augment decision data
    trait_augment_db = _load_trait_augment_data()
    augment_context_lines = _build_augment_context(_aug_str, trait_augment_db)
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
        lines.append("CAROUSEL ROUND: Do NOT suggest rolling or leveling â€” only carousel/God boon pick advice.")
        try:
            import json as _json
            from pathlib import Path as _Path
            _live = _json.loads((_Path(__file__).parent.parent / "data" / "tft_live_data.json").read_text())
            _comp = _live.get("comp", "") or ""
            _traits = ", ".join(_live.get("traits_active") or [])
            if _comp or _traits:
                lines.append(f"Current comp: {_comp}  Active traits: {_traits}")
                lines.append("Carousel/God boon advice: recommend completed items for this carry, or emblems for active traits.")
        except Exception:
            pass

    if event == "pve":
        lines.append("PVE ROUND: No opponent to position against â€” focus on econ/leveling decisions.")
    if tempo:
        lines.append(f"Milestone: {tempo}")

    if variant == "hyper_roll":
        lines += [
            "",
            "MODE: HYPER ROLL â€” Gold cap 10g. No interest economy. Roll every round.",
            "Hyper Roll rules: ALWAYS roll â€” never save gold. Prioritize 3-starring cheap units.",
            "Win condition: 3-star a 1-2 cost carry ASAP. Reroll aggressively every round.",
        ]
    elif variant == "double_up":
        du_rules = _load_double_up_rules()
        coord_signals = du_rules.get("coordination_signals", {})
        lines += [
            "",
            "MODE: DOUBLE UP (PBE) â€” Playing with a partner. Shared HP pool.",
            "Coordination: ONE player AD carry, ONE player AP carry. Do not contest partner reroll targets.",
            "Donation rule: Send overflow units + 2nd tank if partner HP < 30.",
        ]
        if coord_signals:
            lines.append("Donation signals: " + " | ".join(f"{k}: {v}" for k, v in list(coord_signals.items())[:3]))

    lines += [
        "",
        f"Your items/augments: {items_str}",
    ]

    # â”€â”€ Selected comp context (from overlay comp selector) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        import json as _cj
        from pathlib import Path as _cp
        _cs_file = _cp(__file__).parent.parent / "data" / "comp_state.json"
        # Phase 7 P1-A: use PBE-aware meta path
        _pbe_flag = False
        if _cs_file.exists():
            _cs = _cj.loads(_cs_file.read_text(encoding="utf-8"))
            _pbe_flag = _cs.get("pbe", False)
        _meta_fn = "tft_set17_pbe_meta.json" if _pbe_flag else "tft_set17_meta.json"
        _meta_file = _cp(__file__).parent.parent / "data" / "meta" / _meta_fn
        if not _meta_file.exists():
            _meta_file = _cp(__file__).parent.parent / "data" / "meta" / "tft_set17_meta.json"
        if _cs_file.exists() and _meta_file.exists():
            _cs = _cj.loads(_cs_file.read_text(encoding="utf-8"))
            _comp_name = _cs.get("selected", "")
            _ignore_emb = _cs.get("ignore_emblems", False)
            if _comp_name:
                _meta = _cj.loads(_meta_file.read_text(encoding="utf-8"))
                _cd = _meta.get("comps", {}).get(_comp_name, {})
                if _cd:
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
    except Exception:
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


def _parse_response(text: str) -> dict:
    import re
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

    # Set 17: replace "carousel" with "God boon"
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
    except Exception:
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

        api_key = (
            __import__("os").environ.get("ANTHROPIC_API_KEY", "") or
            self._read_key_file()
        )
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

        cfg_path = Path(__file__).parent.parent / "config" / "coach_settings.json"
        self._model      = "claude-haiku-4-5-20251001"
        self._debounce_s = 45.0   # raised from 15s â€” fires once per round + max 1 urgent/30s
        self._timeout    = 20
        self._max_tokens = 600    # reduced from 800 â€” 9 short fields don't need more
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                self._model      = cfg.get("model",            self._model)
                self._debounce_s = cfg.get("debounce_seconds", self._debounce_s)
                self._timeout    = cfg.get("timeout",          self._timeout)
                self._max_tokens = cfg.get("max_tokens",       self._max_tokens)
            except Exception:
                pass

        logger.info("TftCoachEngine ready [v3-trait-augments] (model=%s debounce=%.0fs)",
                    self._model, self._debounce_s)

    def _read_key_file(self) -> str:
        for p in [Path(__file__).parent.parent / "API-Key-Claude.txt"]:
            if p.exists():
                k = p.read_text(encoding="utf-8").strip()
                if k.startswith("sk-ant-"):
                    return k
        return ""

    def submit(self, state: dict) -> None:
        if not self._client:
            return
        now       = time.time()
        sr        = (state.get("stage", 0), state.get("round", 0))
        # Use vision HP for urgency check when API health is unavailable
        hp = state.get("health")
        if hp is None:
            try:
                import json as _hj
                from pathlib import Path as _hp2
                _hd = _hj.loads((_hp2(__file__).parent.parent / "data" / "tft_live_data.json").read_text())
                _vhp = _hd.get("hp")
                hp = int(float(_vhp)) if _vhp and 0 < float(_vhp) <= 100 else 100
            except Exception:
                hp = 100
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
        try:
            blank = {
                "mode": "tft",
                "action": "", "board": "", "econ": "", "rolldown": "",
                "items": "", "carousel": "", "placement": "",
                "upgrade": "", "risk": "",
                "stage": 1, "round": 1, "level": 1,
                "gold": 0, "health": 100, "alive_others": 7,
            }
            tmp = self._data_file.with_suffix(".tmp")
            tmp.write_text(__import__("json").dumps(blank, indent=2), encoding="utf-8")
            tmp.replace(self._data_file)
        except Exception:
            pass

    def shutdown(self) -> None:
        logger.info("TftCoachEngine shutdown")

    def _run_safe(self, state: dict):
        if not self._lock.acquire(blocking=False):
            logger.debug("TFT coach busy â€” skipping")
            return
        try:
            self._run(state)
        except Exception as exc:
            logger.error("TFT coach error: %s", exc)
            self._write_status(f"Coach error: {str(exc)[:60]}")
        finally:
            self._lock.release()

    def _run(self, state: dict):
        t0     = time.time()
        prompt = _build_prompt(state)
        if self._debug:
            logger.debug("TFT prompt:\n%s", prompt)

        response = self._client.messages.create(
            model      = self._model,
            max_tokens = self._max_tokens,
            system     = [{"type": "text", "text": TFT_SYSTEM_PROMPT,
                           "cache_control": {"type": "ephemeral"}}],
            messages   = [{"role": "user", "content": prompt}],
        )
        # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker. POLLING
        # cadence (45s debounce) - the biggest untracked HAIKU lane.
        try:
            from core.cost_tracker import record_anthropic_response
            record_anthropic_response(response, model=self._model, purpose="tft_coach")
        except Exception as exc:
            logger.debug("cost_tracker record: %s", exc)
        latency = int((time.time() - t0) * 1000)
        raw     = response.content[0].text
        logger.info("TFT coach response in %dms", latency)
        if self._debug:
            logger.debug("TFT response:\n%s", raw)
        self._write_fields(raw, state)

    def _write_fields(self, raw: str, state: dict):
        fields = _parse_response(raw)
        fields["_stage_round"] = state.get("stage_round", "")
        if not fields:
            logger.warning("TFT: no fields parsed from response (first 200 chars): %s",
                           raw[:200].replace("\n", " | "))
            return

        _WATCH = ("action", "board", "econ", "rolldown", "items",
                  "carousel", "placement", "upgrade", "risk")
        if self._last_fields:
            changed = any(fields.get(k) != self._last_fields.get(k) for k in _WATCH)
            if not changed:
                logger.debug("TFT: advice unchanged, skipping overlay write")
                return
        self._last_fields = dict(fields)

        # Resolve authoritative HP: prefer vision HP, fallback to API state, fallback to 100
        _out_hp = state.get("health")  # may be None if state reader didn't get HP from API
        try:
            import json as _ohj
            from pathlib import Path as _ohp
            _ohd = _ohj.loads((_ohp(__file__).parent.parent / "data" / "tft_live_data.json").read_text())
            _vision_hp = _ohd.get("hp")
            if _vision_hp and isinstance(_vision_hp, (int, float)) and 0 < float(_vision_hp) <= 100:
                _out_hp = int(float(_vision_hp))
        except Exception:
            pass
        if _out_hp is None:
            _out_hp = 100

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
            "carousel":     fields.get("carousel",     ""),
            "placement":    fields.get("placement",    ""),
            "upgrade":      fields.get("upgrade",      ""),
            "risk":         fields.get("risk",         ""),
        }

        try:
            tmp = self._data_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(output, indent=2), encoding="utf-8")
            tmp.replace(self._data_file)
            logger.debug("TFT coaching data written (%d fields)", len(fields))
            # arch: phase 3 step 1.1 - write TFT coaching timestamp only after payload write succeeds
            # Mirrors SR/ARAM/Arena/Brawl successful-write semantics.
            try:
                from core.coaching_timestamps import write_coaching_ts as _wcts
                _wcts("tft")
            except Exception:
                pass  # non-fatal
        except Exception as exc:
            logger.error("Failed to write TFT coaching data: %s", exc)

    def _write_status(self, msg: str):
        try:
            self._data_file.write_text(
                json.dumps({"mode": "tft", "action": "ERROR", "risk": msg},
                           indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
