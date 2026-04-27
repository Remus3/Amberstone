"""
coaches/arena_coach.py

Arena (2v2v2v2) full coaching engine.

Architecture:
  - Self-polls Riot API every 1.5s for all 8 teams' HP via allPlayers
  - Calls Claude on round start, augment select, HP threshold events
  - Vision fires every 12s to detect: augment choices, item anvil, round phase
  - Spawns 3 dedicated overlay windows
  - Writes to data/arena_coaching_data.json

Output: action, round_strategy, fight_rule, augment_advice, anvil_advice,
        risk, camp_phase, target_priority, augment_play, teams (HP list),
        round, rank, alive_teams, hp_pct, wins, losses
"""

import sys
import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("rc.coaches.arena")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a Challenger-level Arena 2v2v2v2 coach. Rotating opponents, no waves, HP carries between rounds.

CHAMPION: {profile}

═══ ARENA PRIORITY DECISION TREE ═══
Opponent HP > 70%: standard fight — do NOT overcommit; trade efficiently and kite
Opponent HP 40-70%: all-in when your burst combo is up + escape ready
Opponent HP < 40%: play safe — they will desperate all-in; kite and poke to close
Your HP < 25%: NEVER all-in; kite, disengage, survive to next camp phase
Your HP > 70%: aggressive — you can afford to make plays and take risks

═══ ROUND FIGHT RULES ═══
Your pair: stay within 300 units of your partner. Peel for each other.
Engage when: BOTH abilities are off cooldown + carry is isolated + escape path clear
Disengage when: you or partner HP < 20% OR enemy pair has both CC abilities ready
Target priority: 1) [E] carry (lowest HP, highest threat), 2) [E] CC holder, 3) tank last
Augment active: use EVERY fight — never save for "perfect" moment
Kiting: orbwalk every single auto. Never stand still during fights.
Anvil phase: ALWAYS take. Complete carry item first, then defensive stat stick.

═══ CAMP PHASE ═══
Always: buy components, upgrade if 2 copies available, heal at campfire
Priority spend: carry item completion > defensive component > sell weakest unit
Augment select at camp: pick damage amp or reset-on-kill for carry; HP/resist for tank

═══ AUGMENT SELECTION FRAMEWORK ═══
1. Does it combo with your kit? (e.g. dash → Sudden Impact; CC → Glacial Augment)
2. Does it scale with your items? (AD items → Conqueror; AP → Luden's)
3. Is it reliable in 2v2? (avoid conditional augments requiring 5+ enemies)
Best for carries: Cut Down, Sudden Impact, Eyeball Collection, Absolute Focus
Best for tanks: Bone Plating, Grasp, Shield Bash, Unflinching

NAME TAGS: [A]Ally[/A]  [E]Enemy[/E]  [T]timing[/T]

OUTPUT FORMAT — exactly 7 fields, NO markdown:
Action: <1-3 WORDS ALL-CAPS — e.g. ALL IN / KITE BACK / BUY ITEMS / FOCUS CARRY / CAMP PHASE>
Round strategy: <opponent HP + your HP + correct approach, use [E] tag, max 20 words>
Fight rule: <exact engage condition with [E] carry + specific ability window, max 20 words>
Augment advice: <if augment select: take X — why. Else: play your current augment this way>
Anvil advice: <if anvil open: take X to complete Y. Else: next component to build>
Target priority: <kill [E]name[/E] first — why — then who>
Risk: <[E]ability[/E] to dodge + when it's up>
"""

_USER_TEMPLATE = """\
=== Arena Round {round} ===
Your champion: {champion}
Partner: {partner}
HP: {hp_pct}%  Gold: {gold}g  Level: {level}  KDA: {kda}
Items: {items}

Your rank: #{rank} of {alive} teams remaining
Next opponent: {next_opp}

Team health rankings:
{team_rankings}

Active augments: {augments}
{vision_context}
"""

_AUGMENT_SELECT_PROMPT = """\
You are a Challenger Arena coach. Choose the best augment.

Current state:
Champion: {champion}  Partner: {partner}
Items: {items}  HP: {hp_pct}%  Round: {round}

AUGMENT CHOICES:
{choices}

NO markdown. Output exactly:
Take: <augment name>
Why: <one sentence — why it works for this champion + round>
Gameplan: <how to fight differently because of this augment>
"""


class Coach:
    """Arena 2v2v2v2 coach — self-polls, manages own overlay."""

    GAME_MODES = ("ARENA", "CHERRY")

    def __init__(self, data_file, debug: bool = False):
        self._data_file  = Path(data_file) if not isinstance(data_file, Path) else data_file
        self._debug      = debug
        self._running    = False
        self._overlay    = {}
        self._lock       = threading.Lock()
        self._last_state = {}
        self._last_coach_time = 0.0
        self._last_round      = 0
        # Phase 6 Step 2 Fix 2: event-stream round counter (more truthful than kills+deaths+1)
        self._event_round_count = 0
        self._last_event_count  = 0

        self._arena_file  = self._data_file.parent / "arena_coaching_data.json"
        self._vision_state = {}
        self._last_vision  = 0.0
        self._ensure_data()

        self._api_key = _read_api_key(_APP_DIR)
        self._client  = None
        if self._api_key:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)

        self._running = True
        threading.Thread(target=self._poll_loop, daemon=True, name="ArenaPoll").start()
        threading.Thread(target=self._vision_loop, daemon=True, name="ArenaVision").start()
        self._last_force_check = 0.0
        try:
            from core.hotkeys import register_coach as _hk_reg
            _hk_reg(self)
        except Exception: pass
        logger.info("Arena Coach started")

    def submit_state(self, state: dict): pass

    def _update_round_from_events(self, state: dict) -> str:
        """
        Stateful round tracker: increments _event_round_count only when the
        cumulative combat-event count from the API grows (delta > 0).

        This avoids the false-precision problem of presenting a raw cumulative
        event count as if it were an exact round number.  One Arena round can
        produce multiple ChampionKill/TurretKilled events, so a direct count
        overstates the round number.  Instead we treat each polling delta as
        "at least one new round action happened" and increment by 1 per delta
        window, capped at 30.

        The result is labeled "~N" (tilde = explicitly approximate) so the
        consumer and the coach prompt both know this is not the true round.
        The API does not expose an Arena round counter directly.
        """
        new_count = state.get("_raw_event_count", 0)
        if new_count > self._last_event_count:
            # New combat events observed since last poll — advance round by 1.
            # We deliberately do NOT advance by the raw delta because multiple
            # kills per round would cause over-counting.
            self._event_round_count = min(self._event_round_count + 1, 30)
            self._last_event_count  = new_count
        # Return a labeled approximate string, not a bare integer.
        return f"~{max(self._event_round_count, 1)}"

    def reset_state(self):
        self._last_state = {}
        self._last_coach_time = 0.0
        self._last_round = 0
        # Phase 6 Step 2 Fix 2: reset event-based round counter
        self._event_round_count = 0
        self._last_event_count  = 0
        # Phase 6 Step 2 Fix 7: always write blank artifact on reset
        self._write_blank_artifact()

    def _write_blank_artifact(self):
        """Write a blank/neutral Arena coaching artifact. Safe to call on reset."""
        try:
            self._arena_file.parent.mkdir(parents=True, exist_ok=True)
            _safe_write(self._arena_file, {
                "mode": "arena", "action": "", "round_strategy": "",
                "fight_rule": "", "augment_advice": "", "anvil_advice": "",
                "target_priority": "", "risk": "", "teams": [],
                "round": 0, "rank": "?", "alive_teams": 8, "hp_pct": 100,
            })
        except Exception as exc:
            logger.warning("Arena blank artifact write: %s", exc)

    def shutdown(self):
        self._running = False
        try:
            from core.hotkeys import unregister_coach as _hk_unreg
            _hk_unreg(self)
        except Exception: pass
        self._teardown_overlay()
        logger.info("Arena Coach shutdown")

    def attach_overlay(self, root):
        try:
            from modes.arena_overlay import ArenaRightTop, ArenaRightBot, ArenaBottomStrip
            self._overlay = {
                "rtop":   ArenaRightTop(root),
                "rbot":   ArenaRightBot(root),
                "bottom": ArenaBottomStrip(root),
            }
            root.after(500, lambda: self._poll_overlay_file(root))
            logger.info("Arena overlay attached")
        except Exception as e:
            logger.error("Arena overlay attach failed: %s", e)

    def detach_overlay(self):
        self._teardown_overlay()

    # ── Loops ─────────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                state = self._read_game_state()
                if state:
                    # Phase 6 Step 2.1 Fix 2: set round via stateful delta
                    # tracker before storing or coaching on this state.
                    state["round"] = self._update_round_from_events(state)
                    self._last_state = state
                    self._maybe_coach(state)
            except Exception as exc:
                logger.debug("Arena poll error: %s", exc)
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
                logger.debug("Arena vision error: %s", exc)
            time.sleep(3.0)

    def _run_vision(self):
        # Phase 3 Step 1: gate vision loop by live_coaching policy.
        # Suppresses Sonnet screenshot calls when coaching is disabled.
        try:
            from core.feature_policy import is_allowed as _fp_ok
            if not _fp_ok("arena", "live_coaching"):
                return
        except Exception:
            pass  # policy unavailable -- allow
        try:
            reader = ArenaVisionReader(self._api_key)
            state  = reader.read()
            if not state:
                return
            self._vision_state = state

            if state.get("augment_select") and state.get("augment_choices"):
                self._handle_augment_select(state)
                return
            if state.get("anvil_choices"):
                self._handle_anvil(state)

        except Exception as exc:
            logger.debug("Arena vision run failed: %s", exc)

    def _maybe_coach(self, state: dict):
        now   = time.time()
        # Phase 6 Step 2.1: round is now a labeled string ("~N"); compare
        # against the numeric counter directly to detect round advances.
        hp    = state.get("hp_pct", 100)
        last_hp = self._last_state.get("hp_pct", 100) if self._last_state else 100

        new_round = self._event_round_count != self._last_round and self._event_round_count > 0
        hp_drop   = last_hp - hp >= 10
        debounce  = now - self._last_coach_time

        if new_round:
            self._last_round = self._event_round_count

        if (new_round or hp_drop) and debounce > 1.5:
            pass
        elif debounce < 4.0:
            return

        if not self._lock.acquire(blocking=False):
            return
        self._last_coach_time = now
        threading.Thread(target=self._run_coach, args=(dict(state),),
                         daemon=True, name="ArenaCoach").start()
        self._lock.release()

    def _run_coach(self, state: dict):
        # Phase 2 Step 1 / 1.1: policy gate runs BEFORE _client check so that
        # disabled-policy neutralization works even when _client is unavailable.
        try:
            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
            if not _fp_ok("arena", "live_coaching"):
                _fp_wr("arena")
                return
        except Exception:
            pass  # policy unavailable — allow by default
        if not self._client:
            return
        try:
            from coach_integration import CHAMPION_PROFILES, GENERIC_PROFILE
            champ   = state.get("champion", "Unknown")
            profile = CHAMPION_PROFILES.get(champ, GENERIC_PROFILE)
            system  = _SYSTEM_PROMPT.format(profile=profile)

            teams   = state.get("teams", [])
            rankings = "\n".join(
                f"  {'[YOU]' if t.get('is_you') else '     '} "
                f"{t.get('name','?')[:12]:12}  {t.get('hp_pct',100):3d}%"
                + (" [NEXT OPP]" if t.get("is_next_opponent") else "")
                + (" [DEAD]" if t.get("is_dead") else "")
                for t in sorted(teams, key=lambda x: -x.get("hp_pct",0))
            ) or "  Team data loading..."

            partner = next(
                (t.get("name","?") for t in teams if t.get("is_partner")), "Unknown")
            next_opp = next(
                (t.get("name","?") for t in teams if t.get("is_next_opponent")), "Unknown")
            augments = ", ".join(state.get("augments", [])) or "none"

            vs = self._vision_state
            vision_ctx = ""
            if vs.get("camp_phase"):
                vision_ctx = "CAMP PHASE ACTIVE — buy/upgrade items and heal now."
            elif vs.get("anvil_choices"):
                vision_ctx = f"ITEM ANVIL available: {', '.join(vs.get('anvil_choices',[]))}"

            user = _USER_TEMPLATE.format(
                round       = state.get("round", 0),
                champion    = champ,
                partner     = partner,
                hp_pct      = state.get("hp_pct", 100),
                gold        = state.get("gold", 0),
                level       = state.get("level", 1),
                kda         = state.get("kda", "0/0/0"),
                items       = ", ".join(state.get("items", [])) or "none",
                rank        = state.get("rank", "?"),
                alive       = state.get("alive_teams", 8),
                next_opp    = next_opp,
                team_rankings = rankings,
                augments    = augments,
                vision_context = vision_ctx,
            )

            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=650,
                system=system, messages=[{"role":"user","content":user}],
                timeout=20,
            )
            raw    = resp.content[0].text
            fields = _parse_fields(raw)
            if not fields:
                logger.warning("Arena: no fields parsed")
                return

            current = _load_json(self._arena_file)
            current.update({
                "action":         fields.get("action", "").upper(),
                "round_strategy": fields.get("round strategy", ""),
                "fight_rule":     fields.get("fight rule", ""),
                "augment_advice": fields.get("augment advice", ""),
                "anvil_advice":   fields.get("anvil advice", ""),
                "target_priority":fields.get("target priority",""),
                "risk":           fields.get("risk", ""),
                "teams":          teams,
                "round":          state.get("round", 0),
                "rank":           state.get("rank", "?"),
                "alive_teams":    state.get("alive_teams", 8),
                "hp_pct":         state.get("hp_pct", 100),
                "wins":           state.get("wins", 0),
                "losses":         state.get("losses", 0),
                "game_time_s":    state.get("game_seconds", 0),
                "camp_phase":     vs.get("camp_phase", False),
            })
            _safe_write(self._arena_file, current)
            logger.debug("Arena coaching written (%d fields)", len(fields))
            # Phase 3 Step 1: write Arena coaching timestamp for MetricsCache.
            try:
                from core.coaching_timestamps import write_coaching_ts as _wts
                _wts("arena")
            except Exception:
                pass  # non-fatal

        except Exception as exc:
            logger.error("Arena coach error: %s", exc)

    def _handle_augment_select(self, vision_state: dict):
        if not self._client:
            return
        gs    = self._last_state
        choices = vision_state.get("augment_choices", [])
        champ = gs.get("champion", "Unknown")
        teams = gs.get("teams", [])
        partner = next((t.get("name","?") for t in teams if t.get("is_partner")), "?")

        prompt = _AUGMENT_SELECT_PROMPT.format(
            champion = champ,
            partner  = partner,
            items    = ", ".join(gs.get("items", [])) or "none",
            hp_pct   = gs.get("hp_pct", 100),
            round    = gs.get("round", 0),
            choices  = "\n".join(f"- {c}" for c in choices),
        )
        try:
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=250,
                messages=[{"role":"user","content":prompt}], timeout=15,
            )
            raw = resp.content[0].text
            current = _load_json(self._arena_file)
            current["augment_select"]  = True
            current["aug_take"]        = _field(raw, "Take")
            current["aug_why"]         = _field(raw, "Why")
            current["aug_plan"]        = _field(raw, "Gameplan")
            current["augment_choices"] = choices
            _safe_write(self._arena_file, current)
        except Exception as exc:
            logger.error("Arena augment select error: %s", exc)

    def _handle_anvil(self, vision_state: dict):
        choices = vision_state.get("anvil_choices", [])
        if not choices or not self._client:
            return
        gs  = self._last_state
        prompt = (
            f"Arena item anvil. Champion: {gs.get('champion','?')}. "
            f"Current items: {', '.join(gs.get('items',[]) or ['none'])}. "
            f"Anvil choices: {', '.join(choices)}. "
            f"HP: {gs.get('hp_pct',100)}%. Round: {gs.get('round',0)}. "
            "NO markdown. Output: Take: <item>\nWhy: <one line reason>"
        )
        try:
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=100,
                messages=[{"role":"user","content":prompt}], timeout=10,
            )
            raw = resp.content[0].text
            current = _load_json(self._arena_file)
            current["anvil_advice"] = f"Take: {_field(raw,'Take')} — {_field(raw,'Why')}"
            _safe_write(self._arena_file, current)
        except Exception as exc:
            logger.error("Arena anvil error: %s", exc)

    # ── Overlay poll ───────────────────────────────────────────────────────────

    def _poll_overlay_file(self, root):
        if not self._overlay or not self._running:
            return
        try:
            if self._arena_file.exists():
                data  = json.loads(self._arena_file.read_text(encoding="utf-8"))
                teams = data.get("teams", [])
                for win in self._overlay.values():
                    try:
                        if hasattr(win, "update"):
                            win.update(data, teams)
                    except Exception: pass
        except Exception as exc:
            logger.debug("Arena overlay poll: %s", exc)
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
            return _parse_arena_state(raw)
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
            self._arena_file.parent.mkdir(parents=True, exist_ok=True)
            if not self._arena_file.exists():
                _safe_write(self._arena_file, {
                    "mode": "arena", "action": "", "round_strategy": "",
                    "fight_rule": "", "augment_advice": "", "anvil_advice": "",
                    "target_priority": "", "risk": "", "teams": [],
                    "round": 0, "rank": "?", "alive_teams": 8, "hp_pct": 100,
                })
        except Exception as exc:
            logger.warning("Could not create Arena data file: %s", exc)


# ── Vision reader ─────────────────────────────────────────────────────────────

class ArenaVisionReader:
    PROMPT = """\
Analyze this Arena (2v2v2v2) League of Legends screenshot.
Return ONLY valid JSON:
{
  "augment_select": false,
  "augment_choices": [],
  "anvil_choices": [],
  "camp_phase": false,
  "round_number": 1,
  "teams": [
    {"name": "Jinx", "hp_pct": 100, "is_you": false, "is_partner": false, "is_dead": false}
  ]
}
Rules:
- augment_select: true if large augment card selection panel visible
- augment_choices: list of augment names if selection visible
- anvil_choices: list of item names if item anvil visible
- camp_phase: true if in the between-round camp phase (not in combat arena)
- teams: extract all visible team health bars (4 pairs = 8 players)
- is_you: true for your own character; is_partner: true for your pair partner
- hp_pct: health percentage 0-100
- Return ONLY the JSON
"""

    def __init__(self, api_key: str):
        import anthropic
        from modes.shared_vision import GameVisionReader
        r = GameVisionReader.__new__(GameVisionReader)
        r._client = anthropic.Anthropic(api_key=api_key)
        r._model  = "claude-sonnet-4-6"
        r._last   = {}
        r.PROMPT  = self.PROMPT
        self._reader = r

    def read(self):
        return self._reader.read()


# ── Arena game state parser ───────────────────────────────────────────────────

def _parse_arena_state(raw: dict) -> dict:
    ap    = raw.get("activePlayer", {})
    gd    = raw.get("gameData", {})
    all_p = [p for p in (raw.get("allPlayers", []) or []) if isinstance(p, dict)]
    events = (raw.get("events", {}) or {}).get("Events", [])

    game_time = float(gd.get("gameTime", 0))
    game_mode = gd.get("gameMode", "ARENA")

    stats  = ap.get("championStats", {}) or {}
    hp     = int(stats.get("currentHealth", 0))
    hp_max = int(stats.get("maxHealth", 1))
    hp_pct = int(100 * hp / max(hp_max, 1))

    my_name = ap.get("summonerName") or ap.get("riotIdGameName") or ""
    me = None
    for p in all_p:
        pn = (p.get("summonerName") or "").split("#")[0]
        mn = my_name.split("#")[0]
        if pn == mn or p.get("championName") == ap.get("championName"):
            me = p
            break

    sc     = (me or {}).get("scores", {}) or {}
    kills  = sc.get("kills", 0)
    deaths = sc.get("deaths", 0)
    assists= sc.get("assists", 0)
    items  = [(it.get("displayName","")) for it in ((me or {}).get("items") or [])
              if isinstance(it, dict) and it.get("displayName")]

    alive = sum(1 for p in all_p if not p.get("isDead"))
    dead  = sum(1 for p in all_p if p.get("isDead"))

    # Build teams list from allPlayers
    my_team_id = (me or {}).get("team", "ORDER") if me else "ORDER"
    teams = []
    for i, p in enumerate(all_p):
        teams.append({
            "name":             p.get("championName", f"Player{i}"),
            "hp_pct":           100 if not p.get("isDead") else 0,
            "is_you":           p is me,
            "is_partner":       p.get("team") == my_team_id and p is not me,
            "is_dead":          p.get("isDead", False),
            "is_next_opponent": False,  # set by vision
        })

    # Phase 6 Step 2.1 Fix 1 (corrected): rank from HP sort — only emit a
    # numeric best-effort rank when the available data actually supports a
    # meaningful ordering.  The Riot Live Client API only provides isDead
    # (boolean), so hp_pct in the teams list is always 100 (alive) or 0 (dead).
    # When all living teams tie at hp_pct=100 the sort order is insertion-order
    # (arbitrary), which is NOT a real rank.  In that case we emit "?" so the
    # consumer sees an explicitly degraded value rather than a fake numeric rank.
    # A non-binary ordering is only available when vision data has been merged
    # into the teams list (hp_pct values other than 0 or 100).  In that case
    # the sort is meaningful and we emit "~N" (tilde = still approximate).
    rank_str = "?"
    hp_values = [t["hp_pct"] for t in teams if not t["is_dead"]]
    has_real_hp_variance = any(v not in (0, 100) for v in hp_values)
    if has_real_hp_variance and teams:
        sorted_teams = sorted(teams, key=lambda t: -t["hp_pct"])
        for idx, t in enumerate(sorted_teams):
            if t["is_you"]:
                rank_str = f"~{idx + 1}"  # ~ = best-effort from vision HP data
                break
    # else: all living teams tied at 100% — insertion-order sort is meaningless;
    # emit "?" rather than a fake numeric rank.

    # Phase 6 Step 2.1 Fix 2 (corrected): pass raw events through to the Coach
    # instance so the stateful delta tracker (_event_round_count) can compute
    # a per-poll increment rather than re-counting the cumulative stream.
    # _parse_arena_state is a pure parser — it does NOT set round here.
    # round is now set by the Coach._update_round_from_events() method which
    # tracks the previous event count and increments only on new events.
    # We pass _raw_event_count so Coach can detect changes without re-filtering.
    combat_events = [
        ev for ev in events
        if isinstance(ev, dict) and ev.get("EventName") in (
            "TurretKilled", "ChampionKill", "FirstBlood"
        )
    ]
    raw_event_count = len(combat_events)

    return {
        "game_mode":      game_mode,
        "game_seconds":   game_time,
        "champion":       (me or ap).get("championName", "Unknown"),
        "hp_pct":         hp_pct,
        "gold":           int(ap.get("currentGold", 0)),
        "level":          ap.get("level", 1),
        "kda":            f"{kills}/{deaths}/{assists}",
        "items":          items,
        "wins":           kills,
        "losses":         deaths,
        "alive_teams":    (alive + 1) // 2,
        "rank":           rank_str,
        "round":          None,          # set by Coach._update_round_from_events()
        "teams":          teams,
        "augments":       [],
        "_raw_event_count": raw_event_count,  # for stateful Coach-side delta tracking
    }


# ── Shared helpers ────────────────────────────────────────────────────────────

def _read_api_key(app_dir: Path) -> str:
    for p in [app_dir / "API-Key-Claude.txt"]:
        if p.exists():
            k = p.read_text(encoding="utf-8").strip()
            if k.startswith("sk-ant-"):
                return k
    return os.environ.get("ANTHROPIC_API_KEY", "")


def _parse_fields(text: str) -> dict:
    import re
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    fields = {}
    _KEYS = ["action","round strategy","fight rule","augment advice",
             "anvil advice","target priority","risk"]
    for line in text.strip().splitlines():
        s = line.strip()
        for key in _KEYS:
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
