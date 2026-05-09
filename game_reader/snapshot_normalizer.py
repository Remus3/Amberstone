# arch: raw liveclient JSON → coaching state dict + derived fields | section=vision | frozen=no
"""game_reader.snapshot_normalizer — turns Riot Live Client JSON into the
coaching state dict consumed by the dashboard and per-mode coaches.

Holds `_process_game` (the orchestrator, ~350 LOC) plus all derivation
helpers: enemy tracking, objective timers, gank threat, ward hints,
position assessment, rune/ability reads, and the
`to_rift_snapshot` / `to_aram_snapshot` static factories.

`_NormalizerMixin` is mixed into `GameReader` (`game_reader.__init__`).
Cross-mixin calls into `_PollerMixin` (e.g. `self._get` for rune
endpoints) resolve through MRO at runtime.
"""

import logging
import urllib.parse

from .mode_router import is_tft_mode, tower_count_for, tft_minimal_state
from .poller import LIVE_API

_log = logging.getLogger("game_reader.snapshot_normalizer")

# Objective respawn timers (seconds)
DRAGON_RESPAWN = 300
BARON_RESPAWN = 360
FIRST_DRAGON = 300       # 5:00
FIRST_RIFT_HERALD = 480  # 8:00
FIRST_BARON = 1200       # 20:00
FIRST_ATAKHAN = 1200     # 20:00


def _normalize_name(name: str) -> str:
    """Strip Riot tag (#NA1 etc.), lowercase, trim whitespace."""
    if not name:
        return ""
    return name.split("#")[0].strip().lower()


class _NormalizerMixin:
    """Snapshot construction + derivation helpers. State
    (`_enemy_last_seen`, `_enemy_death_time`, etc.) is initialized by
    `GameReader.__init__`."""

    # ------------------------------------------------------------------
    # Snapshot text formatter
    # ------------------------------------------------------------------

    def format_for_claude(self, state):
        """Format game state into the Live Input Template for pasting into Claude."""
        if not state:
            return ""

        items = ", ".join(state["items"]) if state["items"] else "Starting items"
        ally_comp = ", ".join(state["ally_comp"])
        enemy_comp = ", ".join(state["enemy_comp"])
        dead = ", ".join(state["dead_enemies"]) if state["dead_enemies"] else "None"
        alive_enemies = ", ".join(state["alive_enemies"]) if state["alive_enemies"] else "All dead"

        lines = [
            f"Time: {state['game_time']}",
            f"Champion: {state['champion']}",
            f"Our comp: {ally_comp}",
            f"Enemy comp: {enemy_comp}",
            f"Me HP/Mana: {state['hp']} / {state['mana']}",
            f"Items: {items}",
            f"Levels: {state['level']}",
            f"CS: {state['cs']} ({state['cs_per_min']}/min)",
            f"KDA: {state['kda']}",
            f"Gold: {state['gold']}g",
            f"Nearby enemies: {alive_enemies}",
            f"Dead enemies: {dead}",
            f"Objective timer: {state['objectives']}",
        ]

        summ_d = state.get("summoner_d", "")
        summ_f = state.get("summoner_f", "")
        if summ_d or summ_f:
            lines.append(f"Summoners: D={summ_d or '?'}  F={summ_f or '?'}")

        # Add ally details
        if state.get("ally_details"):
            lines.append("Allies:")
            for a in state["ally_details"]:
                lines.append(f"  {a}")

        # Add enemy details
        if state.get("enemy_details"):
            lines.append("Enemies:")
            for e in state["enemy_details"]:
                lines.append(f"  {e}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Game data processing
    # ------------------------------------------------------------------

    def _process_game(self, raw):
        active = raw.get("activePlayer", {})
        if not isinstance(active, dict):
            active = {}
        game_info = raw.get("gameData", {})
        if not isinstance(game_info, dict):
            game_info = {}
        # Filter to dicts only — list elements can be strings when API is in a transitional state
        raw_players = raw.get("allPlayers", [])
        all_players = [p for p in (raw_players if isinstance(raw_players, list) else [])
                       if isinstance(p, dict)]
        events_wrap = raw.get("events", {})
        if not isinstance(events_wrap, dict):
            events_wrap = {}
        events = events_wrap.get("Events", [])
        if not isinstance(events, list):
            events = []
        # Reset per-game event counters before reprocessing
        self._order_towers_down = 0
        self._chaos_towers_down = 0
        self._inhib_kill_count  = 0
        self._first_blood       = False

        # Game time
        game_time = game_info.get("gameTime", 0)
        game_mode = game_info.get("gameMode", "CLASSIC")
        mins = int(game_time // 60)
        secs = int(game_time % 60)
        time_str = f"{mins}:{secs:02d}"

        # ── TFT early exit — return minimal state so overlay detects TFT mode
        if is_tft_mode(game_mode):
            return tft_minimal_state(game_mode, active, game_info, events,
                                     time_str, game_time)

        # ── Detect GameEnd event — return None immediately so the overlay
        # exits game mode without waiting for the 30-second grace period ──────
        for ev in events:
            if isinstance(ev, dict) and ev.get("EventName") == "GameEnd":
                _log.info("GameEnd event detected — signalling game over")
                return None

        # ── Robust player name matching ──────────────────────────────────
        # activePlayer may use riotIdGameName, riotIdPlusTagLine, or summonerName.
        # allPlayers may have slightly different format. Normalize before comparing.
        my_name_candidates = set()
        for field in ("riotIdGameName", "summonerName", "riotIdPlusTagLine", "riotId"):
            val = active.get(field) or ""
            normalized = _normalize_name(val)
            if normalized:
                my_name_candidates.add(normalized)

        me = None
        my_team = "ORDER"
        for p in all_players:
            for field in ("riotIdGameName", "summonerName", "riotIdPlusTagLine", "riotId"):
                pname = _normalize_name(p.get(field) or "")
                if pname and pname in my_name_candidates:
                    me = p
                    my_team = p.get("team", "ORDER")
                    break
            if me:
                break

        # ── Fallback: if name match fails, use activePlayer champion name
        # to find ourselves in the player list
        if me is None:
            active_champ = active.get("championName", "")
            if active_champ:
                for p in all_players:
                    if p.get("championName", "") == active_champ:
                        me = p
                        my_team = p.get("team", "ORDER")
                        break

        # ── Champion name: prefer allPlayers (most reliable) ────────────
        my_champ = ""
        if me:
            my_champ = me.get("championName", "")
        if not my_champ:
            my_champ = active.get("championName", "")
        if not my_champ:
            my_champ = "Unknown"

        # ── Split teams ──────────────────────────────────────────────────
        allies = [p for p in all_players if p.get("team") == my_team]
        enemies = [p for p in all_players if p.get("team") != my_team]

        # ── My stats ─────────────────────────────────────────────────────
        stats = active.get("championStats", {})
        if not isinstance(stats, dict): stats = {}
        hp = int(stats.get("currentHealth", 0))
        hp_max = int(stats.get("maxHealth", 1))
        mp = int(stats.get("resourceValue", 0))
        mp_max = int(stats.get("resourceMax", 1))
        hp_pct = int(100 * hp / max(hp_max, 1))
        mp_pct = int(100 * mp / max(mp_max, 1))

        my_level = active.get("level", me.get("level", 1) if me else 1)
        my_gold = int(active.get("currentGold", 0))

        cs = 0
        kills = deaths = assists = 0
        my_items = []
        if me:
            sc = me.get("scores", {})
            if not isinstance(sc, dict): sc = {}
            cs = sc.get("creepScore", 0)
            kills = sc.get("kills", 0)
            deaths = sc.get("deaths", 0)
            assists = sc.get("assists", 0)
            raw_items = me.get("items", [])
            if not isinstance(raw_items, list): raw_items = []
            my_items = [it.get("displayName", "")
                        for it in raw_items
                        if isinstance(it, dict) and it.get("displayName")]

        # ── Lane quest boots detection ─────────────────────────────────────
        ADVANCED_BOOTS = {
            "berserker's greaves", "plated steelcaps", "mercury's treads",
            "sorcerer's shoes", "boots of swiftness", "ionian boots of lucidity",
            "mobility boots", "boots of speed",
        }
        items_lower = [i.lower() for i in my_items]
        has_visible_boots = any(b in items_lower for b in ADVANCED_BOOTS)
        consumables = {"total biscuit of everlasting will", "refillable potion",
                       "health potion", "stealth ward", "control ward", "elixir of wrath",
                       "elixir of iron", "elixir of sorcery", "oracle lens",
                       "doran's blade", "doran's ring", "doran's shield", "dagger",
                       "long sword", "pickaxe", "bf sword", "recurve bow",
                       "cloth armor", "null-magic mantle", "ruby crystal"}
        combat_items = [i for i in items_lower
                        if i and i not in consumables and "ward" not in i]
        quest_boots_owned = has_visible_boots or len(combat_items) >= 3
        summ_d = ""
        summ_f = ""
        if me:
            ss = me.get("summonerSpells", {})
            if not isinstance(ss, dict): ss = {}
            ss_d = ss.get("summonerSpellOne", {})
            ss_f = ss.get("summonerSpellTwo", {})
            summ_d = ss_d.get("displayName", "") if isinstance(ss_d, dict) else ""
            summ_f = ss_f.get("displayName", "") if isinstance(ss_f, dict) else ""

        # ── Enemy details ─────────────────────────────────────────────────
        enemy_details = []
        dead_enemies = []
        alive_enemies = []
        for e in enemies:
            esc = e.get("scores", {})
            if not isinstance(esc, dict): esc = {}
            ename = e.get("championName", "?")
            elevel = e.get("level", 0)
            ekda = f"{esc.get('kills',0)}/{esc.get('deaths',0)}/{esc.get('assists',0)}"
            dead = e.get("isDead", False)
            tag = " [DEAD]" if dead else ""
            enemy_details.append(f"{ename} lv{elevel} {ekda}{tag}")
            if dead:
                dead_enemies.append(ename)
            else:
                alive_enemies.append(f"{ename} lv{elevel}")

        # ── Ally details (exclude self) ───────────────────────────────────
        ally_details = []
        for a in allies:
            if me and a.get("championName") == me.get("championName"):
                continue
            asc = a.get("scores", {})
            if not isinstance(asc, dict): asc = {}
            aname = a.get("championName", "?")
            alevel = a.get("level", 0)
            akda = f"{asc.get('kills',0)}/{asc.get('deaths',0)}/{asc.get('assists',0)}"
            dead = a.get("isDead", False)
            tag = " [DEAD]" if dead else ""
            ally_details.append(f"{aname} lv{alevel} {akda}{tag}")

        # ── Team comps ────────────────────────────────────────────────────
        ally_comp = [a.get("championName", "?") for a in allies
                     if a.get("championName") != my_champ]
        enemy_comp = [e.get("championName", "?") for e in enemies]

        # ── Objectives ────────────────────────────────────────────────────
        objectives = self._calc_objectives(events, game_time, dead_enemies)
        obj_timers_dict = self._calc_obj_dict(events, game_time)
        # Tower state from event counters (populated by _calc_objectives)
        _max_t = tower_count_for(game_mode)
        _ord_t = getattr(self, "_order_towers_down", 0)
        _cha_t = getattr(self, "_chaos_towers_down", 0)
        _ord_up = max(0, _max_t - _ord_t)
        _cha_up = max(0, _max_t - _cha_t)
        _inh    = getattr(self, "_inhib_kill_count", 0)
        if my_team == "ORDER":
            my_tower_hp_str    = f"{_ord_up}/{_max_t}" + (" INHIBS:"+str(_inh) if _inh else "")
            enemy_tower_hp_str = f"{_cha_up}/{_max_t}"
        else:
            my_tower_hp_str    = f"{_cha_up}/{_max_t}" + (" INHIBS:"+str(_inh) if _inh else "")
            enemy_tower_hp_str = f"{_ord_up}/{_max_t}"

        # ── Enemy location tracking ───────────────────────────────────────
        my_pos = me.get("position", {}) if me else {}
        if not isinstance(my_pos, dict): my_pos = {}
        self._update_enemy_tracking(enemies, game_time)
        enemy_locs = self._derive_enemy_locations(enemies, game_time, my_pos)

        # ── Enriched coaching context ─────────────────────────────────────
        def _safe_kills(players):
            total = 0
            for p in players:
                sc = p.get("scores", {})
                if isinstance(sc, dict):
                    total += sc.get("kills", 0)
            return total

        ally_kills_total  = _safe_kills(allies)
        enemy_kills_total = _safe_kills(enemies)
        dead_respawn_str  = self._dead_respawn_str(enemies, game_time)
        ally_status_str   = self._ally_status_str(allies, me, game_time)
        walk_time_drake   = self._walk_time(my_pos, {"x": 10400, "z": 5000})
        walk_time_baron   = self._walk_time(my_pos, {"x": 5200, "z": 10900})
        # AUDIT-PHASE-2-GR-003: camp hints are SR-only
        camp_hint         = (self._camp_hint(my_pos, my_team, game_time, obj_timers_dict)
                             if game_mode == "CLASSIC" else "")

        try:
            gank_threat, friendly_jg = self._gank_threat(enemies, allies, my_pos, game_time, my_team)
        except Exception as exc:
            _log.debug("_gank_threat failed: %s", exc)
            gank_threat, friendly_jg = "", ""

        try:
            position_note = self._position_assessment(my_pos, allies, me, my_team)
        except Exception as exc:
            _log.debug("_position_assessment failed: %s", exc)
            position_note = ""

        try:
            # AUDIT-PHASE-2-GR-003: ward hints are SR-only
            if game_mode == "CLASSIC":
                ward_hint = self._ward_hint(game_time, obj_timers_dict)
            else:
                ward_hint = ""
        except Exception as exc:
            _log.debug("_ward_hint failed: %s", exc)
            ward_hint = ""

        try:
            enemy_lane_str = self._enemy_lane_details(enemies, game_time)
        except Exception as exc:
            _log.debug("_enemy_lane_details failed: %s", exc)
            enemy_lane_str = ""

        # ── Derived overlay fields ────────────────────────────────────────
        risk_lines = self._derive_risk(me, allies, enemies, game_time)
        map_lines  = self._derive_map(allies, enemies, game_time)

        cs_per_min = round(cs / max(game_time / 60, 0.5), 1)

        return {
            "game_time":          time_str,
            "game_seconds":       game_time,
            "champion":           my_champ,
            "level":              my_level,
            "gold":               my_gold,
            "cs":                 cs,
            "cs_per_min":         cs_per_min,
            "kda":                f"{kills}/{deaths}/{assists}",
            "kills":              kills,
            "deaths":              deaths,
            "assists":             assists,
            "hp":                 f"{hp}/{hp_max} ({hp_pct}%)",
            "mana":               f"{mp}/{mp_max} ({mp_pct}%)",
            "hp_pct":             hp_pct,
            "mana_pct":           mp_pct,
            "hp_abs":             hp,
            "hp_max":             hp_max,
            "mp_abs":             mp,
            "mp_max":             mp_max,
            "items":              my_items,
            "summoner_d":         summ_d,
            "summoner_f":         summ_f,
            "ally_comp":          ally_comp,
            "enemy_comp":         enemy_comp,
            "ally_details":       ally_details,
            "enemy_details":      enemy_details,
            "dead_enemies":       dead_enemies,
            "dead_count":         len(dead_enemies),
            "alive_enemies":      alive_enemies,
            "enemy_locs":         enemy_locs,
            "ally_kills_total":   ally_kills_total,
            "enemy_kills_total":  enemy_kills_total,
            "dead_respawn_str":   dead_respawn_str,
            "ally_status_str":    ally_status_str,
            "walk_time_drake":    walk_time_drake,
            "walk_time_baron":    walk_time_baron,
            "camp_hint":          camp_hint,
            "gank_threat":        gank_threat,
            "friendly_jg":        friendly_jg,
            "position_note":      position_note,
            "ward_hint":          ward_hint,
            "enemy_lane_str":     enemy_lane_str,
            "quest_boots_owned":  quest_boots_owned,
            "game_mode":          game_mode,
            "objectives":         objectives,
            "obj_timers_dict":    obj_timers_dict,
            "my_tower_hp":        my_tower_hp_str,
            "enemy_tower_hp":     enemy_tower_hp_str,
            "first_blood":        getattr(self, "_first_blood", False),
            "risk_derived":       risk_lines,
            "map_derived":        map_lines,
            "reset_derived":      f"{my_gold}g available | Items: {', '.join(my_items) if my_items else 'None'}",
            # AUDIT-PHASE-2-RUNE-001: rune fields
            "my_runes":           self._read_my_runes(),
            "enemy_runes":        self._read_enemy_runes(enemies),
            # API-002: ability cooldowns
            "my_abilities":       self._read_my_abilities(),
            # DS calibration: Riot game_id from LCU relay ('' when no game or agent stale)
            "game_id":            self._try_lcu_game_id(),
        }

    # ------------------------------------------------------------------
    # Derived overlay fields
    # ------------------------------------------------------------------

    @staticmethod
    def _map_zone(x: float, z: float) -> str:
        """Return approximate map zone name from in-game coordinates."""
        if 9200 < x < 11600 and 3800 < z < 6200:
            return "drake"
        if 3800 < x < 6400 and 9600 < z < 12300:
            return "baron"
        if x < 4500 and z > 9000:
            return "top lane"
        if x > 10500 and z < 4800:
            return "bot lane"
        if 5000 < x < 10500 and 5000 < z < 10500 and abs(x - z) < 2800:
            return "mid"
        if x < 7000 and z > 8000:
            return "jg top"
        if x > 8000 and z < 6500:
            return "jg bot"
        if 6000 < x < 10000 and z < 5000:
            return "bot side"
        if x < 5000 and 5000 < z < 9000:
            return "top side"
        return "river"

    def _update_enemy_tracking(self, enemies: list, game_time: float):
        """Update last-seen record and death times for each enemy."""
        for e in enemies:
            name = e.get("championName", "?")
            pos  = self._safe_pos(e)
            x, z = pos.get("x", 0.0), pos.get("z", 0.0)

            if e.get("isDead"):
                was_alive = not self._enemy_last_seen.get(name, {}).get("dead", False)
                if was_alive:
                    self._enemy_death_time[name] = game_time
                rec = self._enemy_last_seen.setdefault(name, {})
                rec["dead"] = True
                rec["dead_time"] = self._enemy_death_time.get(name, game_time)
                continue

            if self._enemy_last_seen.get(name, {}).get("dead"):
                self._enemy_death_time.pop(name, None)

            if x or z:
                self._enemy_last_seen[name] = {
                    "zone":      self._map_zone(x, z),
                    "time":      game_time,
                    "x": x, "z": z,
                    "dead":      False,
                    "dead_time": None,
                }

    def _derive_enemy_locations(self, enemies: list,
                                 game_time: float, my_pos: dict) -> str:
        NEARBY = 3500.0
        px = my_pos.get("x", 0.0) if my_pos else 0.0
        pz = my_pos.get("z", 0.0) if my_pos else 0.0

        visible, mia, dead = [], [], []

        for e in enemies:
            name = e.get("championName", "?")
            pos  = self._safe_pos(e)
            x, z = pos.get("x", 0.0), pos.get("z", 0.0)

            if e.get("isDead"):
                dead.append(name)
                continue

            if x or z:
                zone = self._map_zone(x, z)
                dist = ((x - px) ** 2 + (z - pz) ** 2) ** 0.5
                tag  = "CLOSE" if (px or pz) and dist < NEARBY else zone
                visible.append(f"{name} [{tag}]")
            else:
                last = self._enemy_last_seen.get(name)
                if last and not last.get("dead") and last.get("time"):
                    ago  = int(game_time - last["time"])
                    zone = last["zone"]
                    if ago < 8:
                        visible.append(f"{name} [{zone}]")
                    elif ago < 45:
                        mia.append(f"{name} MIA {ago}s ({zone})")
                    else:
                        mia.append(f"{name} MIA ({zone} last seen)")
                else:
                    mia.append(f"{name} untracked")

        parts = visible + mia
        if dead:
            parts.append(f"Dead: {', '.join(dead)}")
        return "\n".join(parts) if parts else "No enemy data"

    def _calc_objectives(self, events: list, game_time: float,
                          dead_enemies=None) -> str:
        dragon_kills = []
        last_baron_time = None
        for ev in events:
            if not isinstance(ev, dict): continue
            en, et = ev.get("EventName", ""), ev.get("EventTime", 0)
            if en == "DragonKill":
                dragon_kills.append(et)
            elif en == "BaronKill":
                last_baron_time = et
            elif en == "TurretKilled":
                team = ev.get("TowerTeam", ev.get("TeamID", ""))
                if str(team) in ("100", "ORDER"):
                    self._order_towers_down = getattr(self, "_order_towers_down", 0) + 1
                elif str(team) in ("200", "CHAOS"):
                    self._chaos_towers_down = getattr(self, "_chaos_towers_down", 0) + 1
                else:
                    self._chaos_towers_down = getattr(self, "_chaos_towers_down", 0) + 1
            elif en == "InhibKilled":
                self._inhib_kill_count = getattr(self, "_inhib_kill_count", 0) + 1
            elif en == "FirstBloodKill":
                self._first_blood = True

        last_dragon_time = dragon_kills[-1] if dragon_kills else None
        dragon_num = len(dragon_kills)

        lines = []

        if game_time < FIRST_DRAGON:
            remain = int(FIRST_DRAGON - game_time)
            lines.append(f"First drake in {remain // 60}:{remain % 60:02d}")
        elif last_dragon_time:
            nxt = last_dragon_time + DRAGON_RESPAWN
            if nxt > game_time:
                remain = int(nxt - game_time)
                soul_note = f" [SOUL — {dragon_num} kills]" if dragon_num >= 3 else ""
                lines.append(f"Drake #{dragon_num + 1} in {remain // 60}:{remain % 60:02d}{soul_note}")
            else:
                soul_note = f" [{dragon_num} kills]" if dragon_num >= 2 else ""
                lines.append(f"Drake UP{soul_note}")
        else:
            lines.append("Drake UP")

        if game_time < FIRST_BARON:
            remain = int(FIRST_BARON - game_time)
            lines.append(f"Baron in {remain // 60}:{remain % 60:02d}")
        elif last_baron_time:
            nxt = last_baron_time + BARON_RESPAWN
            if nxt > game_time:
                remain = int(nxt - game_time)
                lines.append(f"Baron in {remain // 60}:{remain % 60:02d}")
            else:
                lines.append("Baron UP")
        else:
            lines.append("Baron UP")

        return "\n".join(lines)

    def _calc_obj_dict(self, events: list, game_time: float) -> dict:
        dragon_kills = []
        last_baron_time = None
        for ev in events:
            if not isinstance(ev, dict): continue
            en, et = ev.get("EventName", ""), ev.get("EventTime", 0)
            if en == "DragonKill":
                dragon_kills.append(et)
            elif en == "BaronKill":
                last_baron_time = et

        last_dragon_time = dragon_kills[-1] if dragon_kills else None

        def timer(last_kill, respawn, first_spawn):
            if game_time < first_spawn:
                return int(first_spawn - game_time)
            if last_kill is None:
                return None
            nxt = last_kill + respawn
            return max(0, int(nxt - game_time)) if nxt > game_time else None

        return {
            "dragon": timer(last_dragon_time, DRAGON_RESPAWN, FIRST_DRAGON),
            "baron":  timer(last_baron_time,  BARON_RESPAWN,  FIRST_BARON),
        }

    def _derive_risk(self, me, allies, enemies, game_time):
        lines = []
        dead_allies = [a.get("championName", "?") for a in allies if a.get("isDead")]
        if dead_allies:
            lines.append(f"Dead allies: {', '.join(dead_allies)}")
        if me:
            my_lv = me.get("level", 1)
            for e in enemies:
                if e.get("isDead"):
                    continue
                esc    = e.get("scores", {})
                if not isinstance(esc, dict): esc = {}
                ename  = e.get("championName", "?")
                elv    = e.get("level", 1)
                ekills = esc.get("kills", 0)
                if elv >= my_lv + 2:
                    lines.append(f"{ename} lv{elv} (+{elv - my_lv} levels)")
                elif ekills >= 4:
                    lines.append(f"{ename} fed ({ekills} kills)")
        if not lines:
            lines.append("No major threats detected")
        return "\n".join(lines)

    def _derive_map(self, allies: list, enemies: list, game_time: float) -> str:
        def _kills(players):
            total = 0
            for p in players:
                sc = p.get("scores", {})
                if isinstance(sc, dict):
                    total += sc.get("kills", 0)
            return total

        ally_kills  = _kills(allies)
        enemy_kills = _kills(enemies)
        diff        = ally_kills - enemy_kills

        if diff > 0:
            kill_line = f"Kill lead: +{diff} ({ally_kills} vs {enemy_kills})"
        elif diff < 0:
            kill_line = f"Kill deficit: {diff} ({ally_kills} vs {enemy_kills})"
        else:
            kill_line = f"Kills even ({ally_kills} vs {enemy_kills})"

        dead  = [e.get("championName", "?") for e in enemies if e.get("isDead")]
        alive = sum(1 for e in enemies if not e.get("isDead"))

        lines = [kill_line, f"Enemies: {alive}/5 alive"]
        if dead:
            lines.append(f"Dead: {', '.join(dead)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Enriched coaching context helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_pos(player_or_pos) -> dict:
        if isinstance(player_or_pos, dict):
            if "x" in player_or_pos or "z" in player_or_pos:
                return player_or_pos
            pos = player_or_pos.get("position", {})
            return pos if isinstance(pos, dict) else {}
        return {}

    _RESPAWN_BASE = [0, 8, 10, 12, 14, 16, 18, 21, 24, 27,
                     30, 34, 37, 40, 43, 47, 50, 52, 54]

    @classmethod
    def _respawn_secs(cls, level: int, game_time_s: float) -> int:
        base = cls._RESPAWN_BASE[min(level, 18)]
        if game_time_s > 25 * 60:
            scale = 1.0 + min(0.5, (game_time_s - 25 * 60) / 60 * 0.0045)
            base = int(base * scale)
        elif game_time_s > 15 * 60:
            scale = 1.0 + min(0.2, (game_time_s - 15 * 60) / 60 * 0.002)
            base = int(base * scale)
        return base

    def _dead_respawn_str(self, enemies: list, game_time: float) -> str:
        parts = []
        for e in enemies:
            if not e.get("isDead"):
                continue
            name  = e.get("championName", "?")
            level = e.get("level", 1)
            death_t = self._enemy_death_time.get(name, game_time)
            elapsed = max(0, game_time - death_t)
            total   = self._respawn_secs(level, game_time)
            remaining = max(0, int(total - elapsed))
            parts.append(f"{name} ~{remaining}s")
        return ", ".join(parts) if parts else ""

    def _ally_status_str(self, allies: list, me, game_time: float) -> str:
        parts = []
        my_champ = me.get("championName", "") if me else ""
        for a in allies:
            if a.get("championName") == my_champ:
                continue
            name  = a.get("championName", "?")
            level = a.get("level", 1)
            sc    = a.get("scores", {})
            if a.get("isDead"):
                respawn = self._respawn_secs(level, game_time)
                parts.append(f"{name} [DEAD ~{respawn}s]")
            else:
                kda = f"{sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}"
                parts.append(f"{name} {kda}")
        return ", ".join(parts) if parts else "unknown"

    @staticmethod
    def _walk_time(from_pos: dict, to_pos: dict):
        if not from_pos:
            return None
        fx, fz = from_pos.get("x", 0.0), from_pos.get("z", 0.0)
        if not (fx or fz):
            return None
        dx = fx - to_pos["x"]
        dz = fz - to_pos["z"]
        dist = (dx ** 2 + dz ** 2) ** 0.5
        return max(5, int(dist / 375))

    def _camp_hint(self, my_pos: dict, my_team: str, game_time: float,
                   obj_timers: dict) -> str:
        if not my_pos or not (my_pos.get("x") or my_pos.get("z")):
            return ""

        soonest_obj = None
        for t in obj_timers.values():
            if t is not None and (soonest_obj is None or t < soonest_obj):
                soonest_obj = t

        camps = {
            "ORDER": [
                ("Raptors",  {"x": 9050, "z": 3700}, 15, 145),
                ("Krugs",    {"x": 11000, "z": 6200}, 20, 160),
                ("Red buff", {"x": 11200, "z": 5800}, 18, 110),
            ],
            "CHAOS": [
                ("Krugs",    {"x": 3500,  "z": 8000}, 20, 160),
                ("Raptors",  {"x": 5400,  "z": 11000}, 15, 145),
                ("Red buff", {"x": 4000,  "z": 10500}, 18, 110),
            ],
        }
        team_camps = camps.get(my_team, camps["ORDER"])

        suggestions = []
        for camp_name, camp_pos, clear_time, gold_val in team_camps:
            walk = self._walk_time(my_pos, camp_pos)
            if walk is None or walk > 20:
                continue
            total_time = walk + clear_time
            if soonest_obj is not None and soonest_obj < total_time + 15:
                continue
            suggestions.append(f"{camp_name} ~{walk}s walk, {clear_time}s clear, {gold_val}g")

        return suggestions[0] if suggestions else ""

    # AUDIT-PHASE-2-GR-002: refreshed jungle champion set
    # Used as a last-resort fallback only — Smite detection (_has_smite) is
    # checked first and is authoritative for any champion. This list only
    # fires when summoner-spell data is absent (relay warm-up frames, etc.).
    _JUNGLE_CHAMPS = {
        # Dedicated junglers
        "Hecarim","Lee Sin","Vi","Warwick","Amumu","Jarvan IV","Nocturne",
        "Graves","Kindred","Nidalee","Kayn","Rengar","Kha'Zix","Shaco",
        "Evelynn","Sejuani","Volibear","Olaf","Udyr","Master Yi",
        "Nunu & Willump","Rammus","Zac","Elise","Fiddlesticks","Ivern",
        "Gragas","Xin Zhao","Diana","Ekko","Bel'Veth","Briar","Viego",
        "Lillia","Poppy","Wukong","Gwen","Taliyah","Tryndamere",
        # Flex junglers (GR-002, deduped)
        "Rek'Sai","Karthus","Shyvana","Skarner","Pantheon","Camille",
        "Trundle","Sylas","Zed","Qiyana","Talon","Twitch","Morgana",
        "Fizz","Maokai","Nautilus","Leona","Swain","Zyra","Brand",
        "Neeko","Aurora","Naafiri","Lux",
    }

    @staticmethod
    def _has_smite(player: dict) -> bool:
        """Return True if the player has Smite as a summoner spell."""
        ss = player.get("summonerSpells")
        if not isinstance(ss, dict):
            return False
        for key in ("summonerSpellOne", "summonerSpellTwo"):
            entry = ss.get(key)
            if isinstance(entry, dict):
                if "Smite" in (entry.get("displayName") or ""):
                    return True
        return False

    def _gank_threat(self, enemies: list, allies: list, my_pos: dict,
                     game_time: float, my_team: str) -> tuple:
        enemy_jg_name = None
        enemy_jg_data = {}

        for e in enemies:
            name = e.get("championName", "?")
            if e.get("isDead"):
                continue
            last = self._enemy_last_seen.get(name, {})
            zone = last.get("zone", "")
            if zone in ("jg top", "jg bot", "baron", "drake"):
                enemy_jg_name = name
                enemy_jg_data = last
                break

        if not enemy_jg_name:
            # Tier 2: Smite detection — accurate for any champion, no list to maintain.
            for e in enemies:
                if self._has_smite(e):
                    enemy_jg_name = e.get("championName", "?")
                    enemy_jg_data = self._enemy_last_seen.get(enemy_jg_name, {})
                    break
        if not enemy_jg_name:
            # Tier 3: champion-name heuristic — last resort when Smite data absent.
            for e in enemies:
                name = e.get("championName", "?")
                if name in self._JUNGLE_CHAMPS:
                    enemy_jg_name = name
                    enemy_jg_data = self._enemy_last_seen.get(name, {})
                    break

        threat = "Unknown — no jungler identified"
        if enemy_jg_name:
            zone     = enemy_jg_data.get("zone", "unknown")
            last_t   = enemy_jg_data.get("time", 0)
            is_dead  = enemy_jg_data.get("dead", False)
            if last_t == 0:
                if game_time < 180:
                    threat = f"LOW — {enemy_jg_name} not yet spotted (early game, likely starting camps)"
                elif game_time < 480:
                    threat = f"MEDIUM — {enemy_jg_name} untracked, assume near scuttle or bot side"
                else:
                    threat = f"HIGH — {enemy_jg_name} untracked, play safe until spotted"
            else:
                time_ago = int(game_time - last_t)
                if is_dead:
                    threat = f"SAFE — {enemy_jg_name} is dead"
                elif zone in ("jg bot", "bot side", "bot lane") and time_ago < 12:
                    threat = f"HIGH — {enemy_jg_name} in jg-bot {time_ago}s ago, likely ganking"
                elif zone in ("top lane", "top side", "jg top") and time_ago < 20:
                    threat = f"LOW — {enemy_jg_name} top side ({time_ago}s ago)"
                elif time_ago < 25:
                    threat = f"MEDIUM — {enemy_jg_name} @ {zone} {time_ago}s ago"
                elif time_ago < 60:
                    threat = f"HIGH — {enemy_jg_name} MIA {time_ago}s (last: {zone})"
                else:
                    threat = f"EXTREME — {enemy_jg_name} MIA {min(time_ago, 120)}s, no info"

        ally_jg = None
        for a in allies:
            if self._has_smite(a):
                ally_jg = a
                break
        if not ally_jg:
            for a in allies:
                if a.get("championName", "?") in self._JUNGLE_CHAMPS:
                    ally_jg = a
                    break

        if ally_jg:
            adead = ally_jg.get("isDead", False)
            aname = ally_jg.get("championName", "?")
            apos  = self._safe_pos(ally_jg)
            ax, az = apos.get("x", 0), apos.get("z", 0)
            if adead:
                friendly = f"{aname} [DEAD]"
            elif ax or az:
                zone = self._map_zone(ax, az)
                dist = self._walk_time(apos, my_pos) if my_pos else None
                if dist is not None:
                    if dist <= 8:
                        friendly = f"{aname} @ {zone} — CLOSE, gank ready"
                    elif dist <= 20:
                        friendly = f"{aname} @ {zone} ~{dist}s — can gank soon"
                    else:
                        friendly = f"{aname} @ {zone} ~{dist}s away"
                else:
                    friendly = f"{aname} @ {zone}"
            else:
                if game_time < 300:
                    friendly = f"{aname} likely at first camps (not yet visible)"
                else:
                    friendly = f"{aname} position unknown — ward river for gank setup"
        else:
            friendly = "Jungler not identified"

        return threat, friendly

    def _position_assessment(self, my_pos: dict, allies: list,
                              me, my_team: str) -> str:
        if not my_pos or not (my_pos.get("x") or my_pos.get("z")):
            return ""

        x, z = my_pos.get("x", 0), my_pos.get("z", 0)
        zone = self._map_zone(x, z)
        issues = []

        if my_team == "ORDER":
            if x > 11000 or (x > 9500 and z > 6000):
                issues.append("OVEREXTENDED past enemy T1 — extreme gank risk")
            elif x > 9000:
                issues.append("Deep in enemy territory — ward before advancing further")
        else:
            if x < 4000 or (x < 5500 and z < 4000):
                issues.append("OVEREXTENDED past enemy T1 — extreme gank risk")
            elif x < 5500:
                issues.append("Deep in enemy territory — ward before advancing further")

        my_champ = me.get("championName", "") if me else ""
        support = None
        for a in allies:
            aname = a.get("championName", "?")
            if aname == my_champ:
                continue
            apos = self._safe_pos(a)
            ax, az = apos.get("x", 0), apos.get("z", 0)
            if ax or az:
                dist = ((x - ax) ** 2 + (z - az) ** 2) ** 0.5
                if dist < 5000:
                    support = (aname, int(dist / 375))
                    break

        if support is None and zone in ("bot lane", "bot side"):
            issues.append("Support not nearby — do not trade without peel")
        elif support and support[1] > 8:
            issues.append(f"Support {support[0]} ~{support[1]}s away — reduce exposure")

        return " | ".join(issues) if issues else ""

    def _ward_hint(self, game_time: float, obj_timers: dict) -> str:
        mins = game_time / 60
        dragon_t = obj_timers.get("dragon")
        baron_t  = obj_timers.get("baron")
        hints = []

        if 2.5 * 60 < game_time < 3.5 * 60:
            hints.append("Ward river NOW — scuttle fight at 3:15")
        elif dragon_t is not None and 0 < dragon_t < 90:
            hints.append(f"Ward drake pit entrance — spawns in {dragon_t}s")
        elif baron_t is not None and 0 < baron_t < 90:
            hints.append(f"Ward baron pit mouth — spawns in {baron_t}s")

        if mins > 2 and not hints:
            if mins < 5:
                hints.append("Buy control ward on next recall — place river tri-brush")
            elif mins < 15:
                hints.append("Refresh river ward on next recall — deny gank angles")
            else:
                hints.append("Deep ward enemy jg on next recall — track rotations")

        return hints[0] if hints else ""

    def _enemy_lane_details(self, enemies: list, game_time: float) -> str:
        parts = []
        for e in enemies:
            ename = e.get("championName", "?")
            epos  = self._safe_pos(e)
            ex, ez = epos.get("x", 0), epos.get("z", 0)
            if not (ex or ez):
                continue
            zone = self._map_zone(ex, ez)
            if zone not in ("bot lane", "bot side"):
                continue
            elv    = e.get("level", 1)
            edead  = e.get("isDead", False)
            eitems = [it.get("displayName", "") for it in e.get("items", []) if it.get("displayName")]
            eitemsStr = ", ".join(eitems[:3]) if eitems else "starter items"
            if not edead:
                parts.append(f"{ename} lv{elv} [{eitemsStr}]")
        return " | ".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # AUDIT-PHASE-2-RUNE-001: rune ingestion methods
    # ------------------------------------------------------------------

    def _read_my_runes(self) -> str:
        """
        Fetch /activeplayerrunes and return a compact string:
        "Keystone | PrimaryPath / SecondaryPath"
        Returns "" on any failure — never raises.
        """
        try:
            data = self._get(f"{LIVE_API}/activeplayerrunes")
            if not isinstance(data, dict):
                return ""
            keystone  = data.get("keystone", {})
            primary   = data.get("primaryRuneTree", {})
            secondary = data.get("secondaryRuneTree", {})
            ks_name   = keystone.get("displayName", "")  if isinstance(keystone, dict)  else ""
            pri_name  = primary.get("displayName", "")   if isinstance(primary, dict)   else ""
            sec_name  = secondary.get("displayName", "") if isinstance(secondary, dict) else ""
            if ks_name:
                return f"{ks_name} | {pri_name} / {sec_name}".strip(" |/")
        except Exception:
            pass
        return ""

    def _read_enemy_runes(self, enemies: list) -> dict:
        """
        Fetch /playermainrunes?summonerName=X for each enemy.
        Returns {championName: "Keystone | PrimaryPath"} — partial results OK.
        Silently skips failures.
        """
        result = {}
        for e in enemies:
            name = e.get("championName", "")
            if not name:
                continue
            summoner = (e.get("riotIdGameName") or e.get("summonerName") or "").strip()
            if not summoner:
                continue
            try:
                encoded = urllib.parse.quote(summoner)
                data = self._get(f"{LIVE_API}/playermainrunes?summonerName={encoded}")
                if not isinstance(data, dict):
                    continue
                keystone = data.get("keystone", {})
                primary  = data.get("primaryRuneTree", {})
                ks_name  = keystone.get("displayName", "") if isinstance(keystone, dict) else ""
                pri_name = primary.get("displayName", "")  if isinstance(primary, dict)  else ""
                if ks_name:
                    result[name] = f"{ks_name} | {pri_name}".strip(" |")
            except Exception:
                pass
        return result

    def _read_my_abilities(self) -> dict:
        """
        Fetch /activeplayerabilities -> {q/w/e/r: {name, cooldown, level}}
        Returns {} on any failure.
        """
        try:
            data = self._get(f"{LIVE_API}/activeplayerabilities")
            if not isinstance(data, dict):
                return {}
            result = {}
            for slot in ("Q", "W", "E", "R"):
                ability = data.get(slot) or data.get(slot.lower())
                if not isinstance(ability, dict):
                    continue
                name = ability.get("displayName") or ability.get("name") or ""
                cd   = ability.get("cooldown")
                lvl  = ability.get("abilityLevel") or ability.get("level")
                if name:
                    result[slot.lower()] = {
                        "name":     name,
                        "cooldown": round(float(cd), 1) if cd is not None else None,
                        "level":    int(lvl) if lvl is not None else None,
                    }
            return result
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # arch: phase 1 step 3 — snapshot factory helpers (to_rift_snapshot, to_aram_snapshot)
    # ------------------------------------------------------------------

    @staticmethod
    def to_rift_snapshot(state_dict: dict):
        if state_dict is None:
            return None
        try:
            from core.game_snapshot import RiftSnapshot
            return RiftSnapshot.from_state_dict(state_dict)
        except Exception:
            pass
        try:
            from core.game_snapshot import RiftSnapshot
            s = RiftSnapshot()
            s.raw_state = state_dict
            try: s.champion     = str(state_dict.get("champion",    ""))
            except Exception: pass
            try: s.game_mode    = str(state_dict.get("game_mode",   "CLASSIC"))
            except Exception: pass
            try: s.game_time    = str(state_dict.get("game_time",   "0:00"))
            except Exception: pass
            try: s.game_seconds = float(state_dict.get("game_seconds", 0))
            except Exception: pass
            try: s.level        = int(state_dict.get("level",        1))
            except Exception: pass
            try: s.gold         = int(state_dict.get("gold",         0))
            except Exception: pass
            try: s.hp_pct       = int(state_dict.get("hp_pct",       100))
            except Exception: pass
            try: s.items        = list(state_dict.get("items",        []))
            except Exception: pass
            return s
        except Exception:
            pass
        try:
            from core.game_snapshot import RiftSnapshot
            s = RiftSnapshot()
            s.raw_state = state_dict
            return s
        except Exception:
            return None

    @staticmethod
    def to_aram_snapshot(state_dict: dict):
        if state_dict is None:
            return None
        try:
            from core.game_snapshot import AramSnapshot
            return AramSnapshot.from_state_dict(state_dict)
        except Exception:
            pass
        try:
            from core.game_snapshot import AramSnapshot
            s = AramSnapshot()
            s.raw_state = state_dict
            try: s.champion     = str(state_dict.get("champion",    ""))
            except Exception: pass
            try: s.game_mode    = str(state_dict.get("game_mode",   "ARAM"))
            except Exception: pass
            try: s.game_time    = str(state_dict.get("game_time",   "0:00"))
            except Exception: pass
            try: s.game_seconds = float(state_dict.get("game_seconds", 0))
            except Exception: pass
            try: s.level        = int(state_dict.get("level",        1))
            except Exception: pass
            try: s.gold         = int(state_dict.get("gold",         0))
            except Exception: pass
            try: s.hp_pct       = int(state_dict.get("hp_pct",       100))
            except Exception: pass
            try: s.items        = list(state_dict.get("items",        []))
            except Exception: pass
            return s
        except Exception:
            pass
        try:
            from core.game_snapshot import AramSnapshot
            s = AramSnapshot()
            s.raw_state = state_dict
            return s
        except Exception:
            return None
