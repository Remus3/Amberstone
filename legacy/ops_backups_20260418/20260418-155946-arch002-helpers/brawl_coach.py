"""
coaches/brawl_coach.py

Nexus Blitz / URF / ARURF / One For All coaching engine.

Architecture:
  - Self-polls Riot API every 1.5s
  - Detects game mode (NEXUSBLITZ, ULTBOOK, GAMEMODEX) and adjusts prompt/strategy
  - Vision reader fires every 12s for event detection (Nexus Blitz)
  - Spawns BrawlRightTop, BrawlRightBot, BrawlBottomStrip overlays
  - Writes to data/brawl_coaching_data.json

Nexus Blitz: event detection, two-lane awareness, event-action guidance
URF/ARURF:   ability spam optimization, anti-healing priority, HP management
One For All: team synergy, stack-ability combos, focus targeting
"""

import sys
import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("rc.coaches.brawl")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# ── System prompts ────────────────────────────────────────────────────────────

_NB_SYSTEM_PROMPT = """\
You are a Challenger Nexus Blitz coach. Two lanes, jungle, rotating random events.
CHAMPION: {profile}

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
Action: <1-3 WORDS ALL-CAPS — GROUP MID / PUSH BOT / CONTEST EVENT / FIGHT NOW / BASE>
Immediate: <what to do RIGHT NOW, [A]/[E] tags, max 15 words>
Event: <event name + action + [T]timer[/T] + lane location>
Fight rule: <engage condition [E] carry + exact mechanic, max 20 words>
Wave: <freeze/slow/crash/bounce + reason>
Reset / item: <fountain condition + item name>
Objective: <structure target + rotate timing [T]>
Risk: <[E]ability[/E] to respect + cooldown context>
"""

_URF_SYSTEM_PROMPT = """\
You are coaching a challenger player in URF (Ultra Rapid Fire). No CD limits. Spamming is the meta.
CHAMPION: {profile}

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
Build damage over utility — healing is reduced but damage is unreduced
Skip healing items (enemy has Grievous Wounds) — go pure damage
Mythic → Rabadon/IE → damage finisher
Anti-heal (Mortal Reminder / Grievous Wounds) by 2nd item always vs sustain

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


class Coach:
    """Brawl coach — handles NEXUSBLITZ, ULTBOOK (URF), GAMEMODEX (OFA/etc)."""

    GAME_MODES = ("NEXUSBLITZ", "ULTBOOK", "GAMEMODEX")

    def __init__(self, data_file, debug: bool = False):
        self._data_file  = Path(data_file) if not isinstance(data_file, Path) else data_file
        self._debug      = debug
        self._running    = False
        self._overlay    = {}
        self._lock       = threading.Lock()
        self._last_state = {}
        self._last_coach_time = 0.0
        self._vision_state    = {}
        self._last_vision     = 0.0

        self._brawl_file = self._data_file.parent / "brawl_coaching_data.json"
        self._ensure_data()

        self._api_key = _read_api_key(_APP_DIR)
        self._client  = None
        if self._api_key:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)

        self._running = True
        threading.Thread(target=self._poll_loop, daemon=True, name="BrawlPoll").start()
        threading.Thread(target=self._vision_loop, daemon=True, name="BrawlVision").start()
        self._last_force_check = 0.0
        try:
            from core.hotkeys import register_coach as _hk_reg
            _hk_reg(self)
        except Exception: pass
        logger.info("Brawl Coach started")

    def submit_state(self, state: dict): pass
    def reset_state(self):
        self._last_state = {}
        self._last_coach_time = 0.0
        # Phase 6 Step 2 Fix 7: always write blank artifact on reset
        self._write_blank_artifact()

    def _write_blank_artifact(self):
        """Write a blank/neutral Brawl coaching artifact. Safe to call on reset."""
        try:
            self._brawl_file.parent.mkdir(parents=True, exist_ok=True)
            _safe_write(self._brawl_file, {
                "mode": "brawl", "action": "", "immediate": "",
                "event_advice": "", "fight_rule": "", "wave": "",
                "reset_item": "", "objective": "", "risk": "",
                "event_name": "", "event_timer": 0,
                "my_nexus_hp": 100, "enemy_nexus_hp": 100,
            })
        except Exception as exc:
            logger.warning("Brawl blank artifact write: %s", exc)

    def shutdown(self):
        self._running = False
        try:
            from core.hotkeys import unregister_coach as _hk_unreg
            _hk_unreg(self)
        except Exception: pass
        self._teardown_overlay()
        logger.info("Brawl Coach shutdown")

    def attach_overlay(self, root):
        try:
            from modes.brawl_overlay import BrawlRightTop, BrawlRightBot, BrawlBottomStrip
            self._overlay = {
                "rtop":   BrawlRightTop(root),
                "rbot":   BrawlRightBot(root),
                "bottom": BrawlBottomStrip(root),
            }
            root.after(500, lambda: self._poll_overlay_file(root))
            logger.info("Brawl overlay attached")
        except Exception as e:
            logger.error("Brawl overlay attach failed: %s", e)

    def detach_overlay(self):
        self._teardown_overlay()

    # ── Loops ─────────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                state = self._read_game_state()
                if state:
                    self._last_state = state
                    self._maybe_coach(state)
            except Exception as exc:
                logger.debug("Brawl poll error: %s", exc)
            time.sleep(1.5)

    def _vision_loop(self):
        _force_file = _APP_DIR / "data" / "force_scan.json"
        while self._running:
            try:
                now = time.time()
                forced = False
                try:
                    if _force_file.exists():
                        import json as _jj
                        _ft = _jj.loads(_force_file.read_text(encoding="utf-8")).get("force",0)
                        if _ft > getattr(self, "_last_force_check", 0):
                            self._last_force_check = _ft
                            forced = True
                except Exception: pass
                if forced or now - self._last_vision >= 12.0:
                    self._last_vision = now
                    self._run_vision()
            except Exception as exc:
                logger.debug("Brawl vision error: %s", exc)
            time.sleep(3.0)

    def _run_vision(self):
        # Phase 3 Step 1: gate vision loop by live_coaching policy.
        # Suppresses Sonnet screenshot calls when coaching is disabled.
        try:
            from core.feature_policy import is_allowed as _fp_ok
            if not _fp_ok("brawl", "live_coaching"):
                return
        except Exception:
            pass  # policy unavailable -- allow
        try:
            reader = BrawlVisionReader(self._api_key,
                                       self._last_state.get("game_mode", ""))
            state  = reader.read()
            if not state:
                return
            self._vision_state = state

            # Merge event info into coaching data immediately
            current = _load_json(self._brawl_file)
            if state.get("current_event"):
                current["event_name"]     = state["current_event"]
                current["event_timer"]    = state.get("event_timer", 0)
                current["event_location"] = state.get("event_location", "")
            if state.get("nexus_hp_my") is not None:
                current["my_nexus_hp"]    = state["nexus_hp_my"]
            if state.get("nexus_hp_enemy") is not None:
                current["enemy_nexus_hp"] = state["nexus_hp_enemy"]
            _safe_write(self._brawl_file, current)

        except Exception as exc:
            logger.debug("Brawl vision run failed: %s", exc)

    def _maybe_coach(self, state: dict):
        now = time.time()
        hp  = state.get("hp_pct", 100)
        last_hp = self._last_state.get("hp_pct", 100) if self._last_state else 100
        hp_drop = last_hp - hp >= 10
        kills   = len(state.get("dead_enemies", [])) > len(
                      self._last_state.get("dead_enemies", []))
        debounce= now - self._last_coach_time

        if (hp_drop or kills) and debounce > 1.5:
            pass
        elif debounce < 3.5:
            return

        if not self._lock.acquire(blocking=False):
            return
        self._last_coach_time = now
        threading.Thread(target=self._run_coach, args=(dict(state),),
                         daemon=True, name="BrawlCoach").start()
        self._lock.release()

    def _run_coach(self, state: dict):
        # Phase 2 Step 1 / 1.1: policy gate runs BEFORE _client check so that
        # disabled-policy neutralization works even when _client is unavailable.
        try:
            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
            if not _fp_ok("brawl", "live_coaching"):
                _fp_wr("brawl")
                return
        except Exception:
            pass  # policy unavailable — allow by default
        if not self._client:
            return
        try:
            from coach_integration import CHAMPION_PROFILES, GENERIC_PROFILE
            champ   = state.get("champion", "Unknown")
            profile = CHAMPION_PROFILES.get(champ, GENERIC_PROFILE)
            mode    = state.get("game_mode", "NEXUSBLITZ").upper()

            # Select prompt based on mode
            if "ULTBOOK" in mode or "URF" in mode:
                system = _URF_SYSTEM_PROMPT.format(profile=profile)
                output_keys = ["action","immediate","fight rule","wave",
                               "reset / item","objective","risk","comp analysis"]
            elif "GAMEMODEX" in mode or "OFA" in mode:
                system = _OFA_SYSTEM_PROMPT.format(champion=champ)
                output_keys = ["action","immediate","fight rule","wave",
                               "reset / item","objective","risk"]
            else:  # NEXUSBLITZ default
                system = _NB_SYSTEM_PROMPT.format(profile=profile)
                output_keys = ["action","immediate","event","fight rule","wave",
                               "reset / item","objective","risk"]

            vs = self._vision_state
            event_ctx = ""
            if vs.get("current_event"):
                t = vs.get("event_timer", 0)
                ev= vs["current_event"]
                loc = vs.get("event_location", "")
                event_ctx = f"\nACTIVE EVENT: {ev}"
                if t:   event_ctx += f" ({t}s remaining)"
                if loc: event_ctx += f" at {loc.upper()}"

            ally_comp  = ", ".join(state.get("ally_comp", []))  or "unknown"
            enemy_comp = ", ".join(state.get("enemy_comp", [])) or "unknown"
            dead_str   = ", ".join(state.get("dead_enemies", [])) or "none"

            user = (
                f"=== {state.get('game_time','0:00')} | {mode} ===\n"
                f"HP: {state.get('hp_pct',100)}%  Mana: {state.get('mana_pct',100)}%"
                f"  Gold: {state.get('gold',0)}g\n"
                f"Level: {state.get('level',1)}  KDA: {state.get('kda','0/0/0')}\n"
                f"Items: {', '.join(state.get('items',[]))  or 'none'}\n"
                f"Your team: {ally_comp}\n"
                f"Enemy team: {enemy_comp}\n"
                f"Dead enemies: {dead_str}"
                f"{event_ctx}\n"
                # Phase 6 Step 4 Fix 3: only include nexus HP for NB where it is
                # a meaningful strategic signal. URF/OFA nexus HP is not tracked
                # by vision and showing a stale 100% value would be misleading.
                + (f"My Nexus HP: {vs.get('nexus_hp_my', 100)}%  "
                   f"Enemy Nexus HP: {vs.get('nexus_hp_enemy', 100)}%"
                   if "NEXUSBLITZ" in mode else "")
            )

            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=600,
                system=system, messages=[{"role":"user","content":user}],
                timeout=20,
            )
            raw    = resp.content[0].text
            fields = _parse_fields(raw, output_keys)
            if not fields:
                logger.warning("Brawl: no fields parsed")
                return

            current = _load_json(self._brawl_file)
            current.update({
                "action":         fields.get("action",      "").upper(),
                "immediate":      fields.get("immediate",   ""),
                "event_advice":   fields.get("event",       ""),
                "fight_rule":     fields.get("fight rule",  ""),
                "wave":           fields.get("wave",        ""),
                "reset_item":     fields.get("reset / item",""),
                "objective":      fields.get("objective",   ""),
                "risk":           fields.get("risk",        ""),
                "comp_analysis":  fields.get("comp analysis",""),
                "game_time_s":    state.get("game_seconds", 0),
                "hp_pct":         state.get("hp_pct", 100),
                "kda":            state.get("kda", "0/0/0"),
                "gold":           state.get("gold", 0),
                "game_mode":      mode,
            })
            _safe_write(self._brawl_file, current)
            logger.debug("Brawl coaching written (%d fields)", len(fields))
            # Phase 3 Step 1: write Brawl coaching timestamp for MetricsCache.
            try:
                from core.coaching_timestamps import write_coaching_ts as _wts
                _wts("brawl")
            except Exception:
                pass  # non-fatal

        except Exception as exc:
            logger.error("Brawl coach error: %s", exc)

    # ── Overlay poll ───────────────────────────────────────────────────────────

    def _poll_overlay_file(self, root):
        if not self._overlay or not self._running:
            return
        try:
            if self._brawl_file.exists():
                data = json.loads(self._brawl_file.read_text(encoding="utf-8"))
                for win in self._overlay.values():
                    try: win.update(data)
                    except Exception: pass
        except Exception as exc:
            logger.debug("Brawl overlay poll: %s", exc)
        root.after(500, lambda: self._poll_overlay_file(root))

    # ── Game state ────────────────────────────────────────────────────────────

    def _read_game_state(self) -> dict:
        import ssl
        import urllib.request
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        try:
            req = urllib.request.Request("https://192.168.8.237:2999/liveclientdata/allgamedata")
            with urllib.request.urlopen(req, context=ctx, timeout=2) as r:
                raw = json.loads(r.read())
            return _parse_brawl_state(raw)
        except Exception:
            return {}

    def _teardown_overlay(self):
        for win in list(self._overlay.values()):
            try:
                if hasattr(win, "destroy_clock"): win.destroy_clock()
                win.destroy()
            except Exception: pass
        self._overlay = {}

    def _ensure_data(self):
        try:
            self._brawl_file.parent.mkdir(parents=True, exist_ok=True)
            if not self._brawl_file.exists():
                _safe_write(self._brawl_file, {
                    "mode": "brawl", "action": "", "immediate": "",
                    "event_advice": "", "fight_rule": "", "wave": "",
                    "reset_item": "", "objective": "", "risk": "",
                    "event_name": "", "event_timer": 0,
                    "my_nexus_hp": 100, "enemy_nexus_hp": 100,
                })
        except Exception as exc:
            logger.warning("Could not create Brawl data file: %s", exc)


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
    """Reuse ARAM state parsing logic — same API structure."""
    ap    = raw.get("activePlayer", {})
    gd    = raw.get("gameData", {})
    all_p = [p for p in (raw.get("allPlayers", []) or []) if isinstance(p, dict)]
    events = (raw.get("events", {}) or {}).get("Events", [])

    game_time = float(gd.get("gameTime", 0))
    game_mode = gd.get("gameMode", "NEXUSBLITZ")
    mins = int(game_time // 60)
    secs = int(game_time % 60)

    stats  = ap.get("championStats", {}) or {}
    hp     = int(stats.get("currentHealth", 0))
    hp_max = int(stats.get("maxHealth", 1))
    mp     = int(stats.get("resourceValue", 0))
    mp_max = int(stats.get("resourceMax", 1))

    my_name = ap.get("summonerName") or ap.get("riotIdGameName") or ""
    me = None
    my_team = "ORDER"
    for p in all_p:
        pn = (p.get("summonerName") or "").split("#")[0]
        mn = my_name.split("#")[0]
        if pn == mn or p.get("championName") == ap.get("championName"):
            me = p
            my_team = p.get("team", "ORDER")
            break

    allies  = [p for p in all_p if p.get("team") == my_team]
    enemies = [p for p in all_p if p.get("team") != my_team]

    sc     = (me or {}).get("scores", {}) or {}
    kills  = sc.get("kills", 0)
    deaths = sc.get("deaths", 0)
    assists= sc.get("assists", 0)
    items  = [(it.get("displayName","")) for it in ((me or {}).get("items") or [])
              if isinstance(it, dict) and it.get("displayName")]

    dead_enemies  = [e.get("championName","?") for e in enemies if e.get("isDead")]
    alive_enemies = [e.get("championName","?") for e in enemies if not e.get("isDead")]
    ally_comp     = [a.get("championName","?") for a in allies
                     if a.get("championName") != (me or {}).get("championName")]
    enemy_comp    = [e.get("championName","?") for e in enemies]

    # Parse NB events from event stream
    event_name = ""
    for ev in events:
        if not isinstance(ev, dict): continue
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
        "kda":           f"{kills}/{deaths}/{assists}",
        "items":         items,
        "ally_comp":     ally_comp,
        "enemy_comp":    enemy_comp,
        "dead_enemies":  dead_enemies,
        "alive_enemies": alive_enemies,
        "event_name":    event_name,
    }


# ── Shared helpers ────────────────────────────────────────────────────────────

def _read_api_key(app_dir: Path) -> str:
    for p in [app_dir / "API-Key-Claude.txt"]:
        if p.exists():
            k = p.read_text(encoding="utf-8").strip()
            if k.startswith("sk-ant-"):
                return k
    return os.environ.get("ANTHROPIC_API_KEY", "")


def _parse_fields(text: str, keys: list) -> dict:
    import re
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    fields = {}
    for line in text.strip().splitlines():
        s = line.strip()
        for key in keys:
            if s.lower().startswith(key + ":"):
                val = s[len(key)+1:].strip()
                val = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', val)
                fields[key] = val[:200]
                break
    return fields


def _field(text: str, key: str) -> str:
    for line in text.strip().splitlines():
        s = line.strip()
        if s.lower().startswith(key.lower() + ":"):
            return s[len(key)+1:].strip()
    return ""


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _safe_write(path: Path, data: dict):
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        logger.error("Write failed %s: %s", path, exc)
