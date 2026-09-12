# arch: raw liveclient JSON -> coaching state dict + derived fields | section=vision | frozen=no
"""game_reader.snapshot_normalizer - turns Riot Live Client JSON into the
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
import math
import time
import urllib.parse

from core.mode_capabilities import has_capability

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
    """Strip Riot tag (#NA1 etc.), lowercase, trim whitespace.

    Non-str input yields "". The falsy guard below does NOT cover a TRUTHY
    non-string (a bare int `riotIdGameName` in a transitional payload), and
    `.split` then raises AttributeError out of the self-identification loop
    in `_process_game` - which the relay path calls unwrapped.
    """
    if not isinstance(name, str) or not name:
        return ""
    return name.split("#")[0].strip().lower()


# ----------------------------------------------------------------------
# Live Client subresource degradation observability (silent-except A4)
# ----------------------------------------------------------------------
# `_PollerMixin._get` (game_reader/poller.py:277-280) does NOT swallow - it
# lets urllib raise. That makes the handlers in the rune / ability readers
# below the SOLE swallow point for a 404, endpoint rename or auth change on
# /activeplayerrunes, /playermainrunes and /activeplayerabilities.
#
# TWO CORRECTIONS to the original note (lane 8 cycle 17, both measured).
# (1) The `_get` citation read poller.py:250-253, which is now
#     `_normalise_events`; `_get` moved to :277-280.
# (2) It claimed these fields "feed live coach prompts
#     (coaches/aram_coach.py:350, 352)". They do NOT: those lines are ARAM
#     fountain-rule prose, and a repo-wide grep finds NO production consumer
#     of `my_runes` / `runes_full` / `stat_shards` at all. The endpoints are
#     still read every tick, so the swallow point and its counter remain
#     real - but the justification for paying for them is currently absent.
#     Filed as RM-234 rather than deleted here.
#
# NOTE the swallow point is not the only one over `self._get`:
# poller.py:233-234 catches Exception and passes, wholly silently, for
# /gamestats, /activeplayer, /allplayers and /eventdata - same failure
# class, no counter, no log.
#
# WARNING makes the failure falsifiable; the throttle keeps a continuously
# polling reader from emitting one record per tick. The counter is NOT
# throttled, so the log under-reports frequency but the counter never does.
LIVE_SUBRESOURCE_WARN_INTERVAL = 60.0  # seconds between warnings per subresource

_subresource_failures: dict = {}
_subresource_last_warn: dict = {}


def get_liveclient_subresource_failures() -> dict:
    """Cumulative swallowed-failure count per Live Client subresource."""
    return dict(_subresource_failures)


def reset_liveclient_subresource_failures() -> None:
    """Clear the counters and the throttle state.

    TEST HOOK ONLY. This previously advertised itself as a "new-game hook";
    measured 2026-08-30, it has NO production caller, so the counters and
    the 60s throttle are process-global and survive every game boundary in
    a process that runs for days. Two consequences, both real: the WARNING
    text "so far this session" means the PROCESS, not the game; and a warn
    that fired shortly before a new game silences the first part of that
    game. Wiring it to game start belongs with the worker, not here - filed
    as RM-235.
    """
    _subresource_failures.clear()
    _subresource_last_warn.clear()


def _note_subresource_failure(subresource: str, exc: BaseException) -> None:
    """Count a swallowed subresource read failure and warn (throttled)."""
    count = _subresource_failures.get(subresource, 0) + 1
    _subresource_failures[subresource] = count
    now = time.monotonic()
    last = _subresource_last_warn.get(subresource)
    if last is None or (now - last) >= LIVE_SUBRESOURCE_WARN_INTERVAL:
        _subresource_last_warn[subresource] = now
        _log.warning(
            "live-client subresource unavailable: %s (%s: %s) - "
            "%d failure(s) so far this session; dependent coach prompt "
            "fields degrade to empty",
            subresource, type(exc).__name__, exc, count,
        )


def _coerce_num(value, default=0.0) -> float:
    """Coerce a Live Client JSON numeric to a finite float.

    json.loads accepts the NaN / Infinity / -Infinity literals (a CPython
    extension), so a poisoned value survives the boundary. int(NaN) raises
    ValueError and int(inf) raises OverflowError - and the primary relay read
    path (game_reader.poller.read_game) calls _process_game UNWRAPPED, so such
    an exception crashes the poll tick. Comparisons against NaN also silently
    misbehave. Return `default` for non-finite or non-numeric input.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return float(default)
    return f if math.isfinite(f) else float(default)


def _runes_text_from_structured(runes_full) -> str:
    """Derive the legacy "Keystone | Primary / Secondary" string from the
    structured `_read_my_runes_structured()` result.

    RM-234: `_process_game` used to call `_read_my_runes()` for this string a
    few lines after `_read_my_runes_structured()`, paying a SECOND
    `/activeplayerrunes` GET per tick and counting one 404 TWICE in
    `_subresource_failures`. This is byte-equivalent to that formatter for
    the same payload: "" when the keystone name is empty (or the input is
    not the structured dict), and the same `.strip(" |/")` trim when a tree
    is missing. The one divergence: a NON-STRING keystone displayName (None,
    0) is stringified upstream by `_read_my_runes_structured`, so it reads
    truthy here where the legacy path read it falsy - Riot never sends one.
    Pure - no I/O, never raises on a malformed structure (it runs on the
    poll thread with no try/except around it).
    """
    if not isinstance(runes_full, dict):
        return ""
    keystone = runes_full.get("keystone")
    if not isinstance(keystone, dict):
        return ""
    ks_name = keystone.get("name", "")
    if not ks_name:
        return ""
    pri_name = runes_full.get("primary_tree", "")
    sec_name = runes_full.get("secondary_tree", "")
    return f"{ks_name} | {pri_name} / {sec_name}".strip(" |/")


def _coerce_int(value, default=0) -> int:
    """Coerce a Live Client JSON numeric to an int, via `_coerce_num`.

    The wire carries levels, kill counts and creep scores that RC uses in
    arithmetic, in `>=` comparisons and as LIST INDICES. Every one of those
    raises on a str / None / list, and a float index raises even when the
    value is otherwise sane - all on the unwrapped relay path documented in
    `_coerce_num` above. Route them through here at the point of READ, so a
    shape change upstream degrades one field instead of killing the tick.

    Non-finite input takes `default`, inherited from `_coerce_num`; a
    numeric-looking string ("13") is preserved rather than discarded, because
    that is real upstream drift and the value is still the truth.
    """
    return int(_coerce_num(value, default))


def _turret_side(turret_name) -> str:
    """Map a Live Client turret structure name to the side that LOST it.

    `"Turret_T1_C_05_A"` -> `"ORDER"`, `"Turret_T2_L_03_A"` -> `"CHAOS"`.
    The token convention is authoritative at `core/district_fusion.py:85`
    (`_SIDE_BY_TOKEN = {"T1": "ORDER", "T2": "CHAOS"}`) and names whose
    structure DIED. Returns `""` for anything unrecognised, so an unknown
    or renamed structure credits NEITHER side rather than being laundered
    into a real count.
    """
    if not isinstance(turret_name, str):
        return ""
    parts = turret_name.split("_")
    if len(parts) < 2:
        return ""
    return {"T1": "ORDER", "T2": "CHAOS"}.get(parts[1], "")


def _coerce_identity(value) -> str:
    """Coerce a wire identity field (riotIdGameName / summonerName) to str.

    A str or a number is a usable name; a list, dict or None is shape drift
    and is treated as ABSENT rather than stringified, so we never build a
    `?summonerName=['a']` query out of garbage.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value).strip()
    return ""


class _NormalizerMixin:
    """Snapshot construction + derivation helpers. State
    (`_enemy_last_seen`, `_enemy_death_time`, etc.) is initialized by
    `GameReader.__init__`."""

    # ------------------------------------------------------------------
    # `format_for_claude` REMOVED - lane 8 cycle 17 (dead code, provenance)
    # ------------------------------------------------------------------
    # It built a paste-into-Claude text block from the state dict. Its ONLY
    # caller was `_copy_state_to_clipboard`, a tkinter clipboard button
    # deleted on 2026-05-01 by eefad53e ("strip tkinter overlay shim from RC
    # main"). RC has been tkinter-free since; a repo-wide grep over EVERY
    # file type found exactly one occurrence of the name - its own def. It
    # was also latently broken, subscripting state["items"] / ["game_time"]
    # / ["cs_per_min"] directly, so any minimal or TFT state dict would have
    # raised KeyError had a caller existed. Recover from git if ever wanted.

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
        # Filter to dicts only - list elements can be strings when API is in a transitional state
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
        # P2-W1-app-A NaN/inf hardening: gameTime crosses the json.loads
        # boundary, which accepts NaN/Infinity literals. int(NaN) below
        # (int(game_time // 60)) raises ValueError and int(inf) raises
        # OverflowError, crashing the unwrapped relay read path. Coerce first.
        game_time = _coerce_num(game_info.get("gameTime", 0))
        game_mode = game_info.get("gameMode", "CLASSIC")
        mins = int(game_time // 60)
        secs = int(game_time % 60)
        time_str = f"{mins}:{secs:02d}"

        # -- TFT early exit - return minimal state so overlay detects TFT mode
        if is_tft_mode(game_mode):
            return tft_minimal_state(game_mode, active, game_info, events,
                                     time_str, game_time)

        # -- Detect GameEnd event - return None immediately so the overlay
        # exits game mode without waiting for the 30-second grace period ------
        for ev in events:
            if isinstance(ev, dict) and ev.get("EventName") == "GameEnd":
                _log.info("GameEnd event detected - signalling game over")
                return None

        # -- Robust player name matching ----------------------------------
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

        # -- Fallback: if name match fails, use activePlayer champion name
        # to find ourselves in the player list
        if me is None:
            active_champ = active.get("championName", "")
            if active_champ:
                for p in all_players:
                    if p.get("championName", "") == active_champ:
                        me = p
                        my_team = p.get("team", "ORDER")
                        break

        # -- Champion name: prefer allPlayers (most reliable) ------------
        my_champ = ""
        if me:
            my_champ = me.get("championName", "")
        if not my_champ:
            my_champ = active.get("championName", "")
        if not my_champ:
            my_champ = "Unknown"

        # -- Split teams --------------------------------------------------
        allies = [p for p in all_players if p.get("team") == my_team]
        enemies = [p for p in all_players if p.get("team") != my_team]

        # -- My stats -----------------------------------------------------
        stats = active.get("championStats", {})
        if not isinstance(stats, dict): stats = {}
        # P2-W1-app-A NaN/inf hardening: coerce each Riot float before int()
        # so a NaN/Infinity championStats value can't crash _process_game.
        hp = int(_coerce_num(stats.get("currentHealth", 0)))
        hp_max = int(_coerce_num(stats.get("maxHealth", 1), 1))
        mp = int(_coerce_num(stats.get("resourceValue", 0)))
        mp_max = int(_coerce_num(stats.get("resourceMax", 1), 1))
        hp_pct = int(100 * hp / max(hp_max, 1))
        mp_pct = int(100 * mp / max(mp_max, 1))

        # R65-A (L9/L10): full championStats combat block for downstream DS
        # live math - every value through _coerce_num so a NaN/Infinity from
        # the relay degrades to 0.0 instead of poisoning consumers; a missing
        # or non-dict championStats yields the all-defaults shape.
        combat_stats = {
            "attack_damage":   _coerce_num(stats.get("attackDamage", 0)),
            "ability_power":   _coerce_num(stats.get("abilityPower", 0)),
            "armor":           _coerce_num(stats.get("armor", 0)),
            "magic_resist":    _coerce_num(stats.get("magicResist", 0)),
            "armor_pen_flat":  _coerce_num(stats.get("physicalLethality", 0)),
            "armor_pen_pct":   _coerce_num(stats.get("armorPenetrationPercent", 0)),
            "magic_pen_flat":  _coerce_num(stats.get("magicPenetrationFlat", 0)),
            "magic_pen_pct":   _coerce_num(stats.get("magicPenetrationPercent", 0)),
            "ability_haste":   _coerce_num(stats.get("abilityHaste", 0)),
            "attack_speed":    _coerce_num(stats.get("attackSpeed", 0)),
            "crit_chance":     _coerce_num(stats.get("critChance", 0)),
            "crit_damage":     _coerce_num(stats.get("critDamage", 0)),
            "life_steal":      _coerce_num(stats.get("lifeSteal", 0)),
            "physical_vamp":   _coerce_num(stats.get("physicalVamp", 0)),
            "spell_vamp":      _coerce_num(stats.get("spellVamp", 0)),
            "move_speed":      _coerce_num(stats.get("moveSpeed", 0)),
            "attack_range":    _coerce_num(stats.get("attackRange", 0)),
            "tenacity":        _coerce_num(stats.get("tenacity", 0)),
            "health_regen":    _coerce_num(stats.get("healthRegenRate", 0)),
            "resource_type":   str(stats.get("resourceType", "")),
        }

        my_level = _coerce_int(active.get("level", me.get("level", 1) if me else 1), 1)
        my_gold = int(_coerce_num(active.get("currentGold", 0)))

        cs = 0
        kills = deaths = assists = 0
        my_items = []
        if me:
            sc = me.get("scores", {})
            if not isinstance(sc, dict): sc = {}
            # These four feed arithmetic (`cs_per_min`, :457) and the state
            # dict's typed contract, so they are coerced at the read, not at
            # each use site.
            cs = _coerce_int(sc.get("creepScore", 0))
            kills = _coerce_int(sc.get("kills", 0))
            deaths = _coerce_int(sc.get("deaths", 0))
            assists = _coerce_int(sc.get("assists", 0))
            raw_items = me.get("items", [])
            if not isinstance(raw_items, list): raw_items = []
            my_items = [it.get("displayName", "")
                        for it in raw_items
                        if isinstance(it, dict) and it.get("displayName")]

        # -- Lane quest boots detection -------------------------------------
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

        # -- Enemy details -------------------------------------------------
        enemy_details = []
        dead_enemies = []
        alive_enemies = []
        for e in enemies:
            esc = e.get("scores", {})
            if not isinstance(esc, dict): esc = {}
            ename = e.get("championName", "?")
            elevel = _coerce_int(e.get("level", 0))
            ekda = f"{esc.get('kills',0)}/{esc.get('deaths',0)}/{esc.get('assists',0)}"
            dead = e.get("isDead", False)
            tag = " [DEAD]" if dead else ""
            enemy_details.append(f"{ename} lv{elevel} {ekda}{tag}")
            if dead:
                dead_enemies.append(ename)
            else:
                alive_enemies.append(f"{ename} lv{elevel}")

        # -- Ally details (exclude self) -----------------------------------
        ally_details = []
        for a in allies:
            if me and a.get("championName") == me.get("championName"):
                continue
            asc = a.get("scores", {})
            if not isinstance(asc, dict): asc = {}
            aname = a.get("championName", "?")
            alevel = _coerce_int(a.get("level", 0))
            akda = f"{asc.get('kills',0)}/{asc.get('deaths',0)}/{asc.get('assists',0)}"
            dead = a.get("isDead", False)
            tag = " [DEAD]" if dead else ""
            ally_details.append(f"{aname} lv{alevel} {akda}{tag}")

        # -- Team comps ----------------------------------------------------
        ally_comp = [a.get("championName", "?") for a in allies
                     if a.get("championName") != my_champ]
        enemy_comp = [e.get("championName", "?") for e in enemies]

        # -- Objectives ----------------------------------------------------
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

        # -- Enemy location tracking ---------------------------------------
        my_pos = me.get("position", {}) if me else {}
        if not isinstance(my_pos, dict): my_pos = {}
        self._update_enemy_tracking(enemies, game_time)
        enemy_locs = self._derive_enemy_locations(enemies, game_time, my_pos)

        # -- Enriched coaching context -------------------------------------
        def _safe_kills(players):
            total = 0
            for p in players:
                sc = p.get("scores", {})
                if isinstance(sc, dict):
                    total += _coerce_int(sc.get("kills", 0))
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
        except Exception as exc:  # noqa: BLE001
            _log.debug("_gank_threat failed: %s", exc)
            gank_threat, friendly_jg = "", ""

        try:
            position_note = self._position_assessment(my_pos, allies, me, my_team)
        except Exception as exc:  # noqa: BLE001
            _log.debug("_position_assessment failed: %s", exc)
            position_note = ""

        try:
            # AUDIT-PHASE-2-GR-003: ward hints are SR-only. Spec-W
            # ward-gate: fail-CLOSED capability table replaces the bare
            # game_mode == "CLASSIC" literal (SR behavior identical -
            # "CLASSIC" is the only raw string that maps to has_wards).
            if has_capability(game_mode, "has_wards"):
                ward_hint = self._ward_hint(game_time, obj_timers_dict)
            else:
                ward_hint = ""
        except Exception as exc:  # noqa: BLE001
            _log.debug("_ward_hint failed: %s", exc)
            ward_hint = ""

        try:
            enemy_lane_str = self._enemy_lane_details(enemies, game_time)
        except Exception as exc:  # noqa: BLE001
            _log.debug("_enemy_lane_details failed: %s", exc)
            enemy_lane_str = ""

        # -- Derived overlay fields ----------------------------------------
        risk_lines = self._derive_risk(me, allies, enemies, game_time)
        map_lines  = self._derive_map(allies, enemies, game_time)

        cs_per_min = round(cs / max(game_time / 60, 0.5), 1)

        # R65-A: fetched ONCE and reused for runes_full, stat_shards AND the
        # legacy `my_runes` string. RM-234 (deduped): the tick pays a SINGLE
        # /activeplayerrunes GET - `my_runes` is derived from this payload by
        # `_runes_text_from_structured` instead of a second `_read_my_runes()`
        # GET, so a 404 counts ONCE per tick in `_subresource_failures`.
        # Guarded by tests/test_rm234_runes_single_get.py (transport census,
        # byte-equivalence table, single counter increment).
        runes_full = self._read_my_runes_structured()

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
            # AUDIT-PHASE-2-RUNE-001: rune fields. RM-234: `my_runes` is
            # derived from `runes_full` above - no second GET.
            "my_runes":           _runes_text_from_structured(runes_full),
            "enemy_runes":        self._read_enemy_runes(enemies),
            # R65-A (L9/L10): structured combat/rune/shard ingestion - the
            # legacy my_runes string stays for existing coach prompts.
            "combat_stats":       combat_stats,
            "runes_full":         runes_full,
            "stat_shards":        runes_full.get("stat_runes", []),
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
                # Clear the record's OWN dead flag here, unconditionally.
                # It used to be cleared only inside the `if x or z:` block
                # below, which a champion who respawned and is walking back
                # through FOG never satisfies - the Live Client reports
                # (0, 0) for an unseen player. The record therefore stayed
                # dead=True indefinitely, so `_gank_threat` announced
                # "SAFE - <jungler> is dead" about a living jungler, and
                # `_derive_enemy_locations` threw away a perfectly good
                # last-seen zone as "untracked". The player is alive: say so
                # even though we cannot say WHERE.
                rec = self._enemy_last_seen[name]
                rec["dead"] = False
                rec["dead_time"] = None

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
                    # max(0, ...): game_time can REGRESS when the poller
                    # alternates between a fresh direct :2999 read and a
                    # relay snapshot up to RELAY_MAX_AGE_S=12s stale.
                    # DEFENSIVE ONLY - this clamp provably changes no
                    # outcome here, because every negative and the clamped 0
                    # both fall in the same `< 8` bucket below (verified
                    # exhaustively; the mutation survives and is equivalent).
                    # Kept for consistency with the death-time guard and in
                    # case these thresholds ever move. The sibling clamp in
                    # `_gank_threat` is NOT cosmetic - the value is rendered
                    # into user-facing text there.
                    ago  = max(0, int(game_time - last["time"]))
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
                # The Live Client eventdata schema carries NEITHER "TowerTeam"
                # NOR "TeamID" - it carries the structure NAME, e.g.
                # "Turret_T1_C_05_A". This previously read those two absent
                # keys, so `team` was ALWAYS "", and the `else` fell through to
                # the same counter as the CHAOS branch: every turret in every
                # game was credited to CHAOS and `_order_towers_down` was
                # structurally pinned at 0. The rest of the tree already parses
                # the name (dashboard/_liveclient.py:348-350); the side token
                # convention is authoritative at core/district_fusion.py:85
                # ({"T1": "ORDER", "T2": "CHAOS"}) and names whose structure
                # DIED. An unrecognised name credits NOBODY - laundering it
                # into a real count is what caused this defect.
                side = _turret_side(ev.get("TurretKilled"))
                if side == "ORDER":
                    self._order_towers_down = getattr(self, "_order_towers_down", 0) + 1
                elif side == "CHAOS":
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
                soul_note = f" [SOUL - {dragon_num} kills]" if dragon_num >= 3 else ""
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
            my_lv = _coerce_int(me.get("level", 1), 1)
            for e in enemies:
                if e.get("isDead"):
                    continue
                esc    = e.get("scores", {})
                if not isinstance(esc, dict): esc = {}
                ename  = e.get("championName", "?")
                elv    = _coerce_int(e.get("level", 1), 1)
                ekills = _coerce_int(esc.get("kills", 0))
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
                    total += _coerce_int(sc.get("kills", 0))
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
        # Defence in depth: callers coerce, but `_RESPAWN_BASE` is indexed by
        # this value and Python's negative indexing wraps to the END of the
        # table - level -1 silently returned the LEVEL-18 respawn (54s), the
        # maximally wrong answer. Clamp BOTH ends, not just the top.
        level = max(0, min(_coerce_int(level, 1), 18))
        base = cls._RESPAWN_BASE[level]
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
            level = _coerce_int(e.get("level", 1), 1)
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
            level = _coerce_int(a.get("level", 1), 1)
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
    # Used as a last-resort fallback only - Smite detection (_has_smite) is
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
            # Tier 2: Smite detection - accurate for any champion, no list to maintain.
            for e in enemies:
                if self._has_smite(e):
                    enemy_jg_name = e.get("championName", "?")
                    enemy_jg_data = self._enemy_last_seen.get(enemy_jg_name, {})
                    break
        if not enemy_jg_name:
            # Tier 3: champion-name heuristic - last resort when Smite data absent.
            for e in enemies:
                name = e.get("championName", "?")
                if name in self._JUNGLE_CHAMPS:
                    enemy_jg_name = name
                    enemy_jg_data = self._enemy_last_seen.get(name, {})
                    break

        threat = "Unknown - no jungler identified"
        if enemy_jg_name:
            zone     = enemy_jg_data.get("zone", "unknown")
            last_t   = enemy_jg_data.get("time", 0)
            is_dead  = enemy_jg_data.get("dead", False)
            if last_t == 0:
                if game_time < 180:
                    threat = f"LOW - {enemy_jg_name} not yet spotted (early game, likely starting camps)"
                elif game_time < 480:
                    threat = f"MEDIUM - {enemy_jg_name} untracked, assume near scuttle or bot side"
                else:
                    threat = f"HIGH - {enemy_jg_name} untracked, play safe until spotted"
            else:
                time_ago = max(0, int(game_time - last_t))
                if is_dead:
                    threat = f"SAFE - {enemy_jg_name} is dead"
                elif zone in ("jg bot", "bot side", "bot lane") and time_ago < 12:
                    threat = f"HIGH - {enemy_jg_name} in jg-bot {time_ago}s ago, likely ganking"
                elif zone in ("top lane", "top side", "jg top") and time_ago < 20:
                    threat = f"LOW - {enemy_jg_name} top side ({time_ago}s ago)"
                elif time_ago < 25:
                    threat = f"MEDIUM - {enemy_jg_name} @ {zone} {time_ago}s ago"
                elif time_ago < 60:
                    threat = f"HIGH - {enemy_jg_name} MIA {time_ago}s (last: {zone})"
                else:
                    threat = f"EXTREME - {enemy_jg_name} MIA {min(time_ago, 120)}s, no info"

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
                        friendly = f"{aname} @ {zone} - CLOSE, gank ready"
                    elif dist <= 20:
                        friendly = f"{aname} @ {zone} ~{dist}s - can gank soon"
                    else:
                        friendly = f"{aname} @ {zone} ~{dist}s away"
                else:
                    friendly = f"{aname} @ {zone}"
            else:
                if game_time < 300:
                    friendly = f"{aname} likely at first camps (not yet visible)"
                else:
                    friendly = f"{aname} position unknown - ward river for gank setup"
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
                issues.append("OVEREXTENDED past enemy T1 - extreme gank risk")
            elif x > 9000:
                issues.append("Deep in enemy territory - ward before advancing further")
        else:
            if x < 4000 or (x < 5500 and z < 4000):
                issues.append("OVEREXTENDED past enemy T1 - extreme gank risk")
            elif x < 5500:
                issues.append("Deep in enemy territory - ward before advancing further")

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
            issues.append("Support not nearby - do not trade without peel")
        elif support and support[1] > 8:
            issues.append(f"Support {support[0]} ~{support[1]}s away - reduce exposure")

        return " | ".join(issues) if issues else ""

    def _ward_hint(self, game_time: float, obj_timers: dict) -> str:
        mins = game_time / 60
        dragon_t = obj_timers.get("dragon")
        baron_t  = obj_timers.get("baron")
        hints = []

        if 2.5 * 60 < game_time < 3.5 * 60:
            hints.append("Ward river NOW - scuttle fight at 3:15")
        elif dragon_t is not None and 0 < dragon_t < 90:
            hints.append(f"Ward drake pit entrance - spawns in {dragon_t}s")
        elif baron_t is not None and 0 < baron_t < 90:
            hints.append(f"Ward baron pit mouth - spawns in {baron_t}s")

        if mins > 2 and not hints:
            if mins < 5:
                hints.append("Buy control ward on next recall - place river tri-brush")
            elif mins < 15:
                hints.append("Refresh river ward on next recall - deny gank angles")
            else:
                hints.append("Deep ward enemy jg on next recall - track rotations")

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
            elv    = _coerce_int(e.get("level", 1), 1)
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
        Returns "" on any failure - never raises.
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
        except Exception as exc:  # noqa: BLE001
            _note_subresource_failure("/activeplayerrunes", exc)
        return ""

    def _read_my_runes_structured(self) -> dict:
        """
        Fetch /activeplayerrunes and return the structured form:
        {"keystone": {"id": int, "name": str}, "primary_tree": str,
         "secondary_tree": str, "general_runes": [{"id", "name"}, ...],
         "stat_runes": [int, ...]}
        Returns {} on any failure - never raises.
        """
        try:
            data = self._get(f"{LIVE_API}/activeplayerrunes")
            if not isinstance(data, dict):
                return {}
            keystone = data.get("keystone", {})
            if not isinstance(keystone, dict):
                keystone = {}
            primary = data.get("primaryRuneTree", {})
            secondary = data.get("secondaryRuneTree", {})
            general = data.get("generalRunes", [])
            if not isinstance(general, list):
                general = []
            shards = data.get("statRunes", [])
            if not isinstance(shards, list):
                shards = []
            # ids through _coerce_num so a single NaN/bad id degrades to 0
            # instead of int() raising and blanking the whole structure.
            return {
                "keystone": {
                    "id":   int(_coerce_num(keystone.get("id", 0))),
                    "name": str(keystone.get("displayName", "")),
                },
                "primary_tree":   (str(primary.get("displayName", ""))
                                   if isinstance(primary, dict) else ""),
                "secondary_tree": (str(secondary.get("displayName", ""))
                                   if isinstance(secondary, dict) else ""),
                "general_runes": [
                    {"id":   int(_coerce_num(r.get("id", 0))),
                     "name": str(r.get("displayName", ""))}
                    for r in general if isinstance(r, dict)
                ],
                "stat_runes": [
                    int(_coerce_num(s.get("id", 0)))
                    for s in shards if isinstance(s, dict)
                ],
            }
        except Exception as exc:  # noqa: BLE001
            _note_subresource_failure("/activeplayerrunes", exc)
        return {}

    def _read_enemy_runes(self, enemies: list) -> dict:
        """
        Fetch /playermainrunes?summonerName=X for each enemy.
        Returns {championName: "Keystone | PrimaryPath"} - partial results OK.
        Silently skips failures.
        """
        result = {}
        for e in enemies:
            name = e.get("championName", "")
            if not name:
                continue
            # This line sits OUTSIDE the try below, so a non-string identity
            # field (a bare int riotIdGameName during a transitional payload)
            # raised AttributeError straight onto the unwrapped poll path.
            # A str or a number is a name we can still query; a list or dict
            # is garbage and is treated as absent rather than stringified
            # into a nonsense query.
            summoner = _coerce_identity(
                e.get("riotIdGameName") or e.get("summonerName")
            )
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
            except Exception as exc:  # noqa: BLE001
                _note_subresource_failure("/playermainrunes", exc)
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
        except Exception as exc:  # noqa: BLE001
            _note_subresource_failure("/activeplayerabilities", exc)
            return {}

    # ------------------------------------------------------------------
    # arch: phase 1 step 3 - snapshot factory helpers (to_rift_snapshot, to_aram_snapshot)
    # ------------------------------------------------------------------

    @staticmethod
    def to_rift_snapshot(state_dict: dict):
        if state_dict is None:
            return None
        try:
            from core.game_snapshot import RiftSnapshot
            return RiftSnapshot.from_state_dict(state_dict)
        except Exception as exc:  # noqa: BLE001
            _log.debug("swallowed exception: %s", exc)
        try:
            from core.game_snapshot import RiftSnapshot
            s = RiftSnapshot()
            s.raw_state = state_dict
            try: s.champion     = str(state_dict.get("champion",    ""))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.game_mode    = str(state_dict.get("game_mode",   "CLASSIC"))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.game_time    = str(state_dict.get("game_time",   "0:00"))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.game_seconds = float(state_dict.get("game_seconds", 0))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.level        = int(state_dict.get("level",        1))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.gold         = int(state_dict.get("gold",         0))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.hp_pct       = int(state_dict.get("hp_pct",       100))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try:
                _raw_items = state_dict.get("items", [])
                # A str is iterable, so list("Doran") exploded into five
                # single-character "items". Only a real sequence counts.
                s.items = (list(_raw_items)
                           if isinstance(_raw_items, (list, tuple)) else [])
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            return s
        except Exception as exc:  # noqa: BLE001
            _log.debug("swallowed exception: %s", exc)
        try:
            from core.game_snapshot import RiftSnapshot
            s = RiftSnapshot()
            s.raw_state = state_dict
            return s
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "snapshot factory exhausted all three tiers, returning None "
                "- the consumer degrades to an emergency payload (%s: %s)",
                type(exc).__name__, exc,
            )
            return None

    @staticmethod
    def to_aram_snapshot(state_dict: dict):
        if state_dict is None:
            return None
        try:
            from core.game_snapshot import AramSnapshot
            return AramSnapshot.from_state_dict(state_dict)
        except Exception as exc:  # noqa: BLE001
            _log.debug("swallowed exception: %s", exc)
        try:
            from core.game_snapshot import AramSnapshot
            s = AramSnapshot()
            s.raw_state = state_dict
            try: s.champion     = str(state_dict.get("champion",    ""))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.game_mode    = str(state_dict.get("game_mode",   "ARAM"))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.game_time    = str(state_dict.get("game_time",   "0:00"))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.game_seconds = float(state_dict.get("game_seconds", 0))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.level        = int(state_dict.get("level",        1))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.gold         = int(state_dict.get("gold",         0))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try: s.hp_pct       = int(state_dict.get("hp_pct",       100))
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            try:
                _raw_items = state_dict.get("items", [])
                # A str is iterable, so list("Doran") exploded into five
                # single-character "items". Only a real sequence counts.
                s.items = (list(_raw_items)
                           if isinstance(_raw_items, (list, tuple)) else [])
            except Exception as exc: _log.debug("swallowed exception: %s", exc)  # noqa: BLE001
            return s
        except Exception as exc:  # noqa: BLE001
            _log.debug("swallowed exception: %s", exc)
        try:
            from core.game_snapshot import AramSnapshot
            s = AramSnapshot()
            s.raw_state = state_dict
            return s
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "snapshot factory exhausted all three tiers, returning None "
                "- the consumer degrades to an emergency payload (%s: %s)",
                type(exc).__name__, exc,
            )
            return None
