"""
coaches/brawl_coach.py  — v2  (ARCH-002 BaseCoach inheritance)

Nexus Blitz / URF / ARURF / One For All coaching engine.
Inherits lifecycle from coaches.BaseCoach.
Self-polls Riot API every 1.5s.
Vision fires every 12s for event detection (Nexus Blitz).
Writes: data/brawl_coaching_data.json

ARCH-002 (full) — 2026-04-18
"""

import os
import sys
import json
import logging
from pathlib import Path

from coaches._base_coach import (
    BaseCoach,
    load_json,
    safe_write,
    mirror_live_stats,
    parse_fields,
    read_api_key,
    fmt_abilities,
)

logger = logging.getLogger("rc.coaches.brawl")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


# ── System prompts ────────────────────────────────────────────────────────────

_NB_SYSTEM_PROMPT = """\
You are a Challenger Nexus Blitz coach. Two lanes, jungle, rotating random events.
CHAMPION: {profile}
{adaptation_hint}
═══ NEXUS BLITZ EVENT PRIORITY ═══
When event spawns: EVERYTHING ELSE STOPS. Respond immediately.
Event priority over: last-hitting, trading, cooldowns, base trips
Star Guardian (top): hard engage, your team fights for the ghost
Bardle Royale (both): hard push to center zone IMMEDIATELY, do not get zoned
Protect the SVP (bot): peel your highest-kill ally; tank/CC anything diving them
Scuttle Puddle (river): contest if you won lane; yield only if 2+ enemies incoming
Prize Fight (center): group fast after nearest wave crash; dive their carry first
Final City: NEVER split. One fight. Your damage source goes in second, not first.

═══ LANE + ROTATION RULES ═══
Win lane first — then look for event rotation
Rotate to event: ONLY if your wave is crashed AND travel time < 15s
Do NOT abandon a winning trade to chase an event you won't reach in time
After event win: crash nearest wave — THEN push objective
After event loss: defensive recall, buy, come back stronger

═══ OBJECTIVES ═══
T1 turret: push with 2+ numbers advantage after kills
Inhibitor: only when 3+ enemies dead with 30s+ respawn
Nexus: group + dive in order (tank first, carry second, mop up third)

NAME TAGS: [A]Ally[/A]  [E]Enemy[/E]  [T]timing[/T]

OUTPUT FORMAT — exactly 8 fields, NO markdown:
Champion build: {brawl_meta}
Action: <1-3 WORDS ALL-CAPS — GROUP MID / PUSH BOT / CONTEST EVENT / FIGHT NOW / BASE>
Immediate: <what to do RIGHT NOW, [A]/[E] tags, max 15 words>
Event: <event name + action + [T]timer[/T] + lane location>
Fight rule: <engage condition [E] carry + exact mechanic, max 20 words>
Wave: <freeze/slow/crash/bounce + reason>
Reset / item: <recall/base condition + next item spike>
Objective: <structure target + rotate timing [T]>
Risk: <[E]ability[/E] to respect + cooldown context>
"""

_URF_SYSTEM_PROMPT = """\
You are coaching a challenger player in URF (Ultra Rapid Fire). No CD limits. Spamming is the meta.
CHAMPION: {profile}
{adaptation_hint}
═══ URF PRIORITIES ═══
1. Ability spam — your strongest abilities should be firing on every CD
2. Anti-heal — Grievous Wounds is mandatory vs any sustain; buy it by item 2
3. Positioning — URF burst is massive; stay at max range and never tank
4. Snowball — first death matters; URF games end fast; deny early kills
5. Objective speed — objectives die fast; always rotate for free turrets after kill

═══ URF COMBAT RULES ═══
ALL-IN: only when you have full combo available + enemy key escape/burst is down
POKE: spam your longest range ability every CD — chip them to 60% then all-in
ANTI-POKE: dodge the first ability then punish the re-cast window
CHASE: abilities are faster than movement — use dashes/slows aggressively

═══ URF ITEMS ═══
Build damage over utility — healing is reduced, damage is NOT
AP carries: Luden's Companion → Shadowflame → Rabadon's → Void Staff
AD carries: Trinity Force → Navori Flickerblades → The Collector (crit path)
On-hit: Nashor's Tooth → Guinsoo's Rageblade → Kraken Slayer
Anti-heal by item 2 vs ANY sustain — Mortal Reminder replaces last damage item
Champion-specific build notes are in the CHAMPION BUILD field below

NAME TAGS: [A]Ally[/A]  [E]Enemy[/E]  [T]timing[/T]

OUTPUT FORMAT — 8 fields, NO markdown:
Action: <1-3 WORDS ALL-CAPS>
Immediate: <what to do RIGHT NOW, max 15 words>
Fight rule: <engage/disengage with [E] tags>
Wave: <shove or freeze>
Reset / item: <next spike + gold check>
Objective: <rotate or hold>
Risk: <specific [E] spell to dodge>
Comp analysis: <your damage type vs enemy — exploit their weakness>
"""

_OFA_SYSTEM_PROMPT = """\
You are coaching a challenger player in One For All (all 5 players play the same champion).
CHAMPION: {champion} x5
{adaptation_hint}
═══ ONE FOR ALL PRIORITIES ═══
1. Exploit champion multiplier — 5x the same kit = 5x the same synergy. Stack it.
2. CC chains — if your champion has CC, chain with teammates for infinite stuns
3. Dive or poke — your champion does one well; commit to that strategy
4. Spread if assassin — don't all 5 clump vs AOE; spread and pick 1v1
5. Stack actives — if items have active abilities, use them simultaneously for burst windows

═══ FIGHT RULE ═══
ENGAGE: wait for all 5 to have key ability up, then hard engage simultaneously
DISENGAGE: if more than 2 allies are dead or CC'd, do NOT engage
OBJECTIVE: fight for every objective — 5 same champions = predictable burst timing

NAME TAGS: [A]Ally[/A]  [E]Enemy[/E]  [T]timing[/T] — use in all fields.

OUTPUT FORMAT — 7 fields, NO markdown:
Action: <1-3 WORDS ALL-CAPS>
Immediate: <right now, max 15 words>
Fight rule: <stack condition + timing>
Wave: <shove or hold>
Reset / item: <next item>
Objective: <take/hold>
Risk: <enemy exploit vs your champion weakness>
"""

_NB_OUTPUT_KEYS  = ["action", "immediate", "event", "fight rule", "wave", "reset / item", "objective", "risk"]
_URF_OUTPUT_KEYS = ["action", "immediate", "fight rule", "wave", "reset / item", "objective", "risk", "comp analysis"]
_OFA_OUTPUT_KEYS = ["action", "immediate", "fight rule", "wave", "reset / item", "objective", "risk"]


# ══════════════════════════════════════════════════════════════════════════════
# Coach class
# ══════════════════════════════════════════════════════════════════════════════


def _load_brawl_build_note(champion: str, mode: str = "") -> str:
    """Load champion build note from aram_champion_builds.json for Brawl modes.
    URF: notes CDR changes. NexusBlitz/OFA: direct ARAM build with SR framing.
    """
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
        fb   = entry.get("full_build", [])
        vt   = entry.get("vs_tanks", "")
        vh   = entry.get("vs_healing", "")
        build_str = ", ".join(fb) if fb else ""
        mode_upper = mode.upper()
        if "URF" in mode_upper:
            urf_note = (f"{tier} tier — URF: abilities spam freely; rush damage items. "
                        f"Build: {build_str}. {note[:120] if note else ''}")
            return urf_note[:300]
        else:
            result = f"{tier} tier — {note}" if tier and note else note or tier
            if build_str:
                result += f" | Build: {build_str}"
            return result[:280]
    except Exception:
        return ""


class Coach(BaseCoach):
    """Brawl coach — handles NEXUSBLITZ, ULTBOOK (URF), GAMEMODEX (OFA/etc)."""

    GAME_MODES     = ("NEXUSBLITZ", "ULTBOOK", "GAMEMODEX")
    _MODE_NAME     = "brawl"
    _DATA_FILENAME = "brawl_coaching_data.json"

    # Brawl is faster — tighter debounce, lower HP threshold
    _VISION_INTERVAL   = 12.0
    _DEBOUNCE_S        = 3.5
    _FAST_PATH_MIN_S   = 1.5
    _HP_DROP_THRESHOLD = 10.0

    # ── BaseCoach abstract implementations ────────────────────────────────────

    def _blank_artifact_data(self) -> dict:
        return {
            "mode": "brawl", "action": "", "immediate": "",
            "event_advice": "", "fight_rule": "", "wave": "",
            "reset_item": "", "objective": "", "risk": "",
            "event_name": "", "event_timer": 0,
            "my_nexus_hp": 100, "enemy_nexus_hp": 100,
        }

    def _parse_raw_state(self, raw: dict) -> dict:
        return _parse_brawl_state(raw)

    # ── Vision ────────────────────────────────────────────────────────────────

    def _run_vision(self) -> None:
        try:
            from core.feature_policy import is_allowed as _fp_ok
            if not _fp_ok("brawl", "live_coaching"):
                return
        except Exception:
            pass
        try:
            reader = BrawlVisionReader(self._api_key, self._last_state.get("game_mode", ""))
            state  = reader.read()
            if not state:
                return
            self._vision_state = state

            current = load_json(self._out)
            if state.get("current_event"):
                current["event_name"]     = state["current_event"]
                current["event_timer"]    = state.get("event_timer",    0)
                current["event_location"] = state.get("event_location", "")
            if state.get("nexus_hp_my") is not None:
                current["my_nexus_hp"]    = state["nexus_hp_my"]
            if state.get("nexus_hp_enemy") is not None:
                current["enemy_nexus_hp"] = state["nexus_hp_enemy"]
            safe_write(self._out, current)
        except Exception as exc:
            logger.debug("Brawl vision run: %s", exc)

    # ── Daemon Slayer mode routing (s75) ────────────────────────────────────
    #
    # Brawl coach is the umbrella for several quick-play modes (BRAWL,
    # NEXUSBLITZ, URF/ULTBOOK, ONEFORALL/GAMEMODEX). Only "BRAWL" is on
    # DDragon map 35. The others ride on map 11 (SR) or map 21 (Nexus
    # Blitz; not in the resolver). We route resolver mode='brawl' for
    # actual Brawl, 'sr' otherwise — SR base IDs are valid for all those
    # modes' item pools. Engine mode follows the same split: 'BRAWL'
    # becomes engine identity-mode (no aram_modifiers) which is correct
    # because Brawl doesn't have aramAttackSpeed-style tweaks.
    @staticmethod
    def _ds_resolver_mode(game_mode_upper: str) -> str:
        return "brawl" if "BRAWL" in (game_mode_upper or "") else "sr"

    @staticmethod
    def _ds_engine_mode(game_mode_upper: str) -> str:
        return "BRAWL" if "BRAWL" in (game_mode_upper or "") else "SR"

    # ── Target-bonus-HP estimator (s75 — Phase 4 batch 19 wire-in) ──────────

    def _estimate_target_bonus_hp(self, state: dict | None = None) -> float:
        """Estimate enemy bonus HP from items. Brawl port of aram_coach's
        s74 estimator. Same shape: walks ``state['enemies']``, filters
        alive opponents, sums HP per opponent, returns MAX clamped at
        1500 (LDR cap). No round-count fallback (Brawl modes don't have
        rounds either) — vision gap returns 0.0 = "no signal".

        Resolver mode routes via ``_ds_resolver_mode`` so BRAWL game mode
        gets map-35 items and the SR-on-other-map modes (URF/OFA/Nexus
        Blitz) get SR base items. Both paths give correct base HP
        values, never the 22XXXX Arena alias HP.
        """
        state = state or {}
        enemies = state.get("enemies") or []
        opp_items: list[list[str]] = [
            (e.get("items") or []) for e in enemies if not e.get("is_dead")
        ]
        if not any(opp_items):
            return 0.0
        from core import daemon_slayer_resolver as _ds_res
        resolver_mode = self._ds_resolver_mode(
            (state.get("game_mode") or "").upper()
        )
        best = 0.0
        for items in opp_items:
            if not items:
                continue
            ids = _ds_res.resolve_many(items, mode=resolver_mode)
            hp = _ds_res.total_bonus_hp(ids)
            if hp > best:
                best = hp
        return min(1500.0, best) if best > 0 else 0.0

    # ── Coach ─────────────────────────────────────────────────────────────────

    def _run_coach(self, state: dict) -> None:
        try:
            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
            if not _fp_ok("brawl", "live_coaching"):
                _fp_wr("brawl")
                return
        except Exception:
            pass
        if not self._client:
            return
        try:
            from coach_integration import CHAMPION_PROFILES, GENERIC_PROFILE
            champ   = state.get("champion", "Unknown")
            profile = CHAMPION_PROFILES.get(champ, GENERIC_PROFILE)
            mode    = state.get("game_mode", "NEXUSBLITZ").upper()

            _hint = ""
            if os.environ.get("RC_COACH_ADAPTATION") == "1":
                try:
                    from coaches.adaptation_hint import format_hint_line as _fhl
                    _hint = _fhl(champ, "brawl", state.get("enemy_comp", []))
                except Exception:
                    pass
            if "ULTBOOK" in mode or "URF" in mode:
                brawl_meta  = _load_brawl_build_note(champ, "URF")
                system      = _URF_SYSTEM_PROMPT.format(profile=profile, brawl_meta=brawl_meta, adaptation_hint=_hint)
                output_keys = _URF_OUTPUT_KEYS
            elif "GAMEMODEX" in mode or "OFA" in mode:
                brawl_meta  = _load_brawl_build_note(champ, "ONEFORALL")
                system      = _OFA_SYSTEM_PROMPT.format(champion=champ, brawl_meta=brawl_meta, adaptation_hint=_hint)
                output_keys = _OFA_OUTPUT_KEYS
            else:
                brawl_meta  = _load_brawl_build_note(champ, "NEXUSBLITZ")
                system      = _NB_SYSTEM_PROMPT.format(profile=profile, brawl_meta=brawl_meta, adaptation_hint=_hint)
                output_keys = _NB_OUTPUT_KEYS

            vs = self._vision_state
            event_ctx = ""
            if vs.get("current_event"):
                ev  = vs["current_event"]
                t   = vs.get("event_timer", 0)
                loc = vs.get("event_location", "")
                event_ctx = f"\nACTIVE EVENT: {ev}"
                if t:   event_ctx += f" ({t}s remaining)"
                if loc: event_ctx += f" at {loc.upper()}"

            _resp = state.get("dead_respawn_str", "")
            user = (
                f"=== {state.get('game_time','0:00')} | {mode} ===\n"
                f"HP: {state.get('hp_pct',100)}%  Mana: {state.get('mana_pct',100)}%"
                f"  Gold: {state.get('gold',0)}g\n"
                f"Level: {state.get('level',1)}  KDA: {state.get('kda','0/0/0')}\n"
                f"My abilities: {fmt_abilities(state.get('my_abilities', {}))}\n"
                f"Items: {', '.join(state.get('items', [])) or 'none'}\n"
                f"Your team: {', '.join(state.get('ally_comp', [])) or 'unknown'}\n"
                f"Enemy team: {', '.join(state.get('enemy_comp', [])) or 'unknown'}\n"
                f"Dead enemies: {', '.join(state.get('dead_enemies', [])) or 'none'}{(' Respawns: ' + _resp) if _resp else ''}"
                f"{event_ctx}\n"
                + (
                    f"My Nexus HP: {vs.get('nexus_hp_my', 100)}%  "
                    f"Enemy Nexus HP: {vs.get('nexus_hp_enemy', 100)}%"
                    if "NEXUSBLITZ" in mode else ""
                )
            )

            import time as _time_a
            _t0 = _time_a.perf_counter()
            # AUDIT 2026-04-29 (gap E): cache_control: ephemeral.
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=600,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                timeout=20,
            )
            # AUDIT 2026-04-29 (gap A): cost + trace telemetry.
            self._record_coach_call(resp, system=system, user=user,
                                    t0_perf=_t0,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="brawl_coach")
            raw    = resp.content[0].text
            fields = parse_fields(raw, output_keys)
            if not fields:
                logger.warning("Brawl: no fields parsed")
                return

            current = load_json(self._out)
            _champ = state.get("champion", "")
            current.update({
                "action":        fields.get("action",       "").upper(),
                "immediate":     fields.get("immediate",    ""),
                "event_advice":  fields.get("event",        ""),
                "fight_rule":    fields.get("fight rule",   ""),
                "wave":          fields.get("wave",         ""),
                "reset_item":    fields.get("reset / item", ""),
                "objective":     fields.get("objective",    ""),
                "risk":          fields.get("risk",         ""),
                "comp_analysis": fields.get("comp analysis",""),
                "game_time_s":   state.get("game_seconds",  0),
                "hp_pct":        state.get("hp_pct",        100),
                "kda":           state.get("kda",           "0/0/0"),
                "gold":          state.get("gold",          0),
                "game_mode":     mode,
                # (audit cycle 4) Mirror ARAM coach: write champion +
                # ally_spells so the dashboard's header pill flips
                # immediately at champ-pop instead of relying on the
                # /api/locked-champion fallback poll.
                "champion":      _champ,
                "ally_spells":   {_champ: [{"spell": state.get("summoner_d", ""), "cd_s": 0},
                                           {"spell": state.get("summoner_f", ""), "cd_s": 0}]}
                                if _champ and (state.get("summoner_d") or state.get("summoner_f")) else {},
            })
            mirror_live_stats(current, state)

            # s75 — Daemon Slayer wire-in. Mirrors aram_coach's s74 pattern.
            # BRAWL game_mode routes to engine mode='BRAWL' (identity, no
            # mode-specific stat overlays); URF/OFA/NB route to 'SR'.
            # target_bonus_hp estimator handles the per-mode resolver
            # routing internally. Engine down → field absent.
            try:
                from core import daemon_slayer_client as _ds_client
                from core.daemon_slayer_resolver import resolve_many as _ds_resolve_many
                _gm_upper = mode  # already upper()'d at line 258
                resolver_mode = self._ds_resolver_mode(_gm_upper)
                engine_mode   = self._ds_engine_mode(_gm_upper)
                owned_ids = _ds_resolve_many(state.get("items", []), mode=resolver_mode)
                target_bonus_hp = self._estimate_target_bonus_hp(state)
                ds_rows = _ds_client.rank_for(
                    champion=champ,
                    level=int(state.get("level", 1)) or 1,
                    item_ids=owned_ids,
                    mode=engine_mode,
                    target_armor=80.0,
                    target_bonus_hp=target_bonus_hp,
                    top=5,
                )
                if ds_rows:
                    current["daemon_slayer_picks"] = [
                        {"id": r.item_id, "name": r.item_name,
                         "delta_dps": round(r.delta_dps, 2), "gold": r.gold}
                        for r in ds_rows
                    ]
                elif ds_rows == []:
                    current["daemon_slayer_picks"] = []
                # ds_rows is None → engine down; leave field untouched.
            except Exception as exc:
                logger.debug("Brawl daemon_slayer wire-in: %s", exc)

            safe_write(self._out, current)
            logger.debug("Brawl coaching written (%d fields)", len(fields))
            try:
                from core.coaching_timestamps import write_coaching_ts as _wts
                _wts("brawl")
            except Exception:
                pass
        except Exception as exc:
            logger.error("Brawl coach: %s", exc)


# ── Vision reader ─────────────────────────────────────────────────────────────

class BrawlVisionReader:
    _NB_PROMPT = """\
Analyze this Nexus Blitz screenshot. Return ONLY valid JSON:
{
  "current_event": "Star Guardian",
  "event_timer": 45,
  "event_location": "top",
  "nexus_hp_my": 100,
  "nexus_hp_enemy": 100,
  "turret_count_my": 3,
  "turret_count_enemy": 2
}
Rules:
- current_event: event name shown on screen, or null if no active event
- event_timer: seconds remaining on event countdown, or 0
- event_location: "top"/"bot"/"river"/"jungle"/"map" where event is happening
- nexus_hp_my: YOUR nexus HP%, or 100 if not visible
- nexus_hp_enemy: ENEMY nexus HP%, or 100 if not visible
- Return ONLY JSON
"""
    _URF_PROMPT = """\
Analyze this URF League of Legends screenshot. Return ONLY valid JSON:
{
  "heal_enemies": false,
  "poke_phase": true,
  "deaths_visible": 0
}
Return ONLY JSON.
"""

    def __init__(self, api_key: str, mode: str):
        import anthropic
        from modes.shared_vision import GameVisionReader
        r = GameVisionReader.__new__(GameVisionReader)
        r._client = anthropic.Anthropic(api_key=api_key)
        r._model  = "claude-sonnet-4-6"
        r._last   = {}
        if "ULTBOOK" in mode.upper() or "URF" in mode.upper():
            r.PROMPT = self._URF_PROMPT
        else:
            r.PROMPT = self._NB_PROMPT
        self._reader = r

    def read(self):
        return self._reader.read()


# ── Brawl game state parser ───────────────────────────────────────────────────

def _parse_brawl_state(raw: dict) -> dict:
    ap     = raw.get("activePlayer", {})
    gd     = raw.get("gameData", {})
    all_p  = [p for p in (raw.get("allPlayers", []) or []) if isinstance(p, dict)]
    events = (raw.get("events", {}) or {}).get("Events", [])

    game_time = float(gd.get("gameTime", 0))
    game_mode = gd.get("gameMode", "NEXUSBLITZ")
    mins = int(game_time // 60)
    secs = int(game_time % 60)

    stats  = ap.get("championStats", {}) or {}
    hp     = int(stats.get("currentHealth", 0))
    hp_max = int(stats.get("maxHealth",     1))
    mp     = int(stats.get("resourceValue", 0))
    mp_max = int(stats.get("resourceMax",   1))

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
    sc      = (me or {}).get("scores", {}) or {}
    items   = [
        it.get("displayName", "")
        for it in ((me or {}).get("items") or [])
        if isinstance(it, dict) and it.get("displayName")
    ]

    # s75 — structured per-enemy entries for daemon_slayer
    # target_bonus_hp estimator (mirrors ARAM coach's s74 shape).
    enemies_struct: list[dict] = []
    for _e in enemies:
        _ei = [
            _it.get("displayName", "")
            for _it in (_e.get("items") or [])
            if isinstance(_it, dict) and _it.get("displayName")
        ]
        enemies_struct.append({
            "name":    _e.get("championName", "?"),
            "is_dead": bool(_e.get("isDead")),
            "items":   _ei,
        })

    event_name = ""
    for ev in events:
        if not isinstance(ev, dict):
            continue
        en = ev.get("EventName", "")
        if en in ("PrizeFight", "StarGuardian", "BardleRoyale",
                  "ProtectTheSVP", "ScuttlePuddle"):
            event_name = en
            break

    return {
        "game_mode":     game_mode,
        "game_time":     f"{mins}:{secs:02d}",
        "game_seconds":  game_time,
        "champion":      (me or ap).get("championName", "Unknown"),
        "hp_pct":        int(100 * hp / max(hp_max, 1)),
        "mana_pct":      int(100 * mp / max(mp_max, 1)),
        "gold":          int(ap.get("currentGold", 0)),
        "level":         ap.get("level", 1),
        "kda":           f"{sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}",
        "items":         items,
        "ally_comp":     [
            a.get("championName", "?") for a in allies
            if a.get("championName") != (me or {}).get("championName")
        ],
        "enemy_comp":    [e.get("championName", "?") for e in enemies],
        "enemies":       enemies_struct,  # s75 — structured per-enemy {name,is_dead,items}
        "dead_enemies":     [e.get("championName", "?") for e in enemies if e.get("isDead")],
        "alive_enemies":    [e.get("championName", "?") for e in enemies if not e.get("isDead")],
        "dead_respawn_str": raw.get("dead_respawn_str", ""),
        "event_name":    event_name,
    }
