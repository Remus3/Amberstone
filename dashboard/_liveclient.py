"""Live Client + LCU relay summary helpers.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

Both summaries pull from the in-process vision server on Legion
(`127.0.0.1:8889`), which mirrors the latest LCU + Live Client
snapshots pushed by the relay agents (`lcu_agent.py`,
`liveclient_relay.py`, relocated 2026-05-29, ADR-011; the relay
self-heals by reading `:2999`/LCU in-process). Each summary
is a best-effort cheap
shape used by the dashboard:

  lcu_summary()        - champ-select / lobby / queue context
  liveclient_summary() - in-game derived fields (game_time, kda,
                         hp/mana/level/gold/cs) plus the SR build path
                         + owned-items list rendered by the icon grid

Both treat any HTTP failure or stale (>5 s) snapshot as "not in a
game / not in champ select" and return `{}` so callers can `if lc:`
cheaply.

The vision server requires the `X-RC-Token` header (auth handled
inside the same Legion process). Token is sourced via
`core.vision_token` so it picks up the env / config rotation path.

`liveclient_summary()` enriches the raw frame with a curated build
path via `item_advisor.resolve_build` (+ boots phase + redundancy
filter). The import is hoisted to module scope - `item_advisor` is
pure-Python data dicts at load time with no expensive side effects.
"""
from __future__ import annotations

import json
import time
import urllib.request

from core.vision_token import get_vision_token
from core.ward_cue import compute_ward_cue
from item_advisor import (
    boots_phase,
    endgame_boots_swap_target,
    is_redundant,
    resolve_build,
)

_VISION_TOKEN = get_vision_token()


def lcu_summary() -> dict:
    """Read latest LCU snapshot pushed by lcu_agent.py.
    Returns {} if relay isn't running or last push is stale (>5s)."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8889/latest-lcu",
            headers={"X-RC-Token": _VISION_TOKEN},
        )
        with urllib.request.urlopen(req, timeout=1) as r:
            wrap = json.loads(r.read())
        if "error" in wrap:
            return {}
        if (time.time() - wrap.get("ts", 0)) > 5:
            return {}
        return wrap.get("data", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def liveclient_summary() -> dict:
    """Pull a few derived fields from the latest Live Client snapshot
    cached on the vision server. Used to fill dashboard placeholders that
    aren't in coach output (game_time, kda, hp/mana, level, gold, cs).
    Also computes the SR build path + owned-items list for the icon
    display."""
    out: dict = {}
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8889/latest-liveclient",
            headers={"X-RC-Token": _VISION_TOKEN},
        )
        with urllib.request.urlopen(req, timeout=1) as r:
            wrap = json.loads(r.read())
        if "error" in wrap:
            return {}
        if (time.time() - wrap.get("ts", 0)) > 5:
            return {}
        d = wrap.get("data", {})
        ap = d.get("activePlayer") or {}
        gd = d.get("gameData") or {}
        cs = ap.get("championStats") or {}
        me_name = ap.get("summonerName", "")
        me_pl = next(
            (p for p in (d.get("allPlayers") or [])
             if p.get("summonerName") == me_name),
            None,
        )
        gt = gd.get("gameTime", 0)
        out["game_time_s"] = int(gt)
        mm, ss = divmod(int(gt), 60)
        out["game_time"] = f"{mm}:{ss:02d}"
        out["level"] = ap.get("level")
        out["gold"]  = int(ap.get("currentGold", 0))
        out["hp"]    = int(cs.get("currentHealth", 0))
        out["hp_max"]   = int(cs.get("maxHealth", 0))
        out["mana"]  = int(cs.get("resourceValue", 0))
        out["mana_max"] = int(cs.get("resourceMax", 0))
        owned_items: list = []
        enemy_team: list = []
        ally_team: list = []
        enemy_item_ids: list = []
        ally_item_ids: list = []
        if me_pl:
            s = me_pl.get("scores") or {}
            out["kda"] = f'{s.get("kills",0)}/{s.get("deaths",0)}/{s.get("assists",0)}'
            out["cs"]  = s.get("creepScore", 0)
            out["champion"] = me_pl.get("championName")
            owned_items = [it.get("displayName", "") for it in (me_pl.get("items") or [])]
            # s184 - parallel item-id list so server-side consumers
            # (archetype_mismatch nudge) don't need a name -> id resolver
            # for the operator's own inventory. Same order as owned_items.
            owned_item_ids = [str(it.get("itemID", "")) for it in (me_pl.get("items") or [])]
            my_team = me_pl.get("team")
            all_players = d.get("allPlayers") or []
            enemy_team = [p.get("championName", "") for p in all_players
                          if p.get("team") and p.get("team") != my_team]
            # Symmetric ally roster (full same-team champion list, incl the
            # operator). Consumed by routes_peel_priority (item 304 Phase D),
            # which drops self for its teammate-only peel verdict.
            ally_team = [p.get("championName", "") for p in all_players
                         if p.get("team") and p.get("team") == my_team]
            # Per-team item-id pools for the deterministic heal-threat nudge
            # (core.heal_threat). allPlayers[].items is PUBLIC scoreboard data
            # for ALL 10 players (unlike gold, which is activePlayer-only), so
            # scanning enemy sustain + ally anti-heal is a hard live fact.
            enemy_item_ids = [str(it.get("itemID", "")) for p in all_players
                              if p.get("team") and p.get("team") != my_team
                              for it in (p.get("items") or [])]
            ally_item_ids = [str(it.get("itemID", "")) for p in all_players
                             if p.get("team") and p.get("team") == my_team
                             for it in (p.get("items") or [])]
            # Per-player position + creep_score slice consumed by
            # _adaptation_latch.compute() to derive csd_at_15 (SR only).
            # is_active flags the operator's own row so the latch can find
            # the active player's position without a second summoner-name
            # match. Emitted as a flat list so the latch stays HTTP-agnostic.
            out["players"] = [
                {
                    "position":    p.get("position") or "",
                    "team":        p.get("team") or "",
                    "creep_score": int((p.get("scores") or {}).get("creepScore", 0)),
                    "is_active":   p.get("summonerName") == me_name,
                }
                for p in all_players
                if isinstance(p, dict)
            ]
            # Kill Participation (item 281) - a fully LIVE-derivable STATS
            # metric. allPlayers[].scores carries kills/assists for ALL 10
            # players (public scoreboard data, unlike gold), so summing the
            # active player's team kills + crediting the operator's own
            # kills+assists is a hard live fact. KP = involvements / team
            # kills. Emit ONLY when the denominator is > 0 (KP undefined at
            # 0 team kills) - isolated try so any non-numeric score degrades
            # to an omitted key, never an exception.
            try:
                team_kills = sum(
                    int((p.get("scores") or {}).get("kills", 0))
                    for p in all_players
                    if p.get("team") and p.get("team") == my_team
                )
                if team_kills > 0:
                    involved = int(s.get("kills", 0)) + int(s.get("assists", 0))
                    pct = round(100 * involved / team_kills)
                    out["kill_participation_pct"] = f"{pct}%"
            except Exception:  # noqa: BLE001
                pass
        else:
            owned_item_ids = []
        out["game_mode"] = gd.get("gameMode")
        out["owned_items"] = owned_items
        out["owned_item_ids"] = owned_item_ids
        # QA1 overlay ward-ready cue: trinket off-cooldown (items[].canUse) +
        # control ward held (item 2055 count). Pure extract over the operator's
        # own inventory; always present (all-off when no live player) so the
        # overlay glyph can edge-detect the not-ready -> ready transition.
        out["ward_cue"] = compute_ward_cue(me_pl.get("items") if me_pl else None)
        out["enemy_team"]  = enemy_team
        out["ally_team"]   = ally_team
        out["enemy_item_ids"] = enemy_item_ids
        out["ally_item_ids"]  = ally_item_ids
        # Inhibitor-down events for the respawn-timing callout. Live Client
        # emits InhibKilled with EventTime (s) + the structure name; we surface
        # raw {down_at_s, name} and let core.event_callouts compute the 300s
        # respawn ETA + parse the lane. Isolated try so a malformed events
        # block degrades to [] without dropping the rest of the summary.
        inhib_events: list = []
        try:
            for ev in (gd.get("events") or {}).get("Events") or []:
                if not isinstance(ev, dict) or ev.get("EventName") != "InhibKilled":
                    continue
                t = ev.get("EventTime")
                if isinstance(t, (int, float)) and not isinstance(t, bool):
                    inhib_events.append({"down_at_s": float(t),
                                         "name": ev.get("InhibKilled")})
        except Exception:  # noqa: BLE001
            inhib_events = []
        out["inhib_events"] = inhib_events
        # RC2 P5.7 (WS4): neutral-objective kill events (dragon/baron/herald) for
        # the lost-objective macro response (core.macro_response). Same Live Client
        # events stream + EventTime (s) pattern as inhib_events above. KillerName is
        # a champion display name, so classify killer_team against the rosters built
        # above (enemy_team / ally_team) - macro_response keys on enemy kills.
        # Isolated try so a malformed events block degrades to [] without dropping
        # the rest of the summary.
        objective_events: list = []
        try:
            _obj_names = {"DragonKill": "dragon", "BaronKill": "baron",
                          "HeraldKill": "herald"}
            enemy_set = {c for c in enemy_team if c}
            ally_set = {c for c in ally_team if c}
            for ev in (gd.get("events") or {}).get("Events") or []:
                if not isinstance(ev, dict):
                    continue
                obj = _obj_names.get(ev.get("EventName"))
                if obj is None:
                    continue
                t = ev.get("EventTime")
                if not isinstance(t, (int, float)) or isinstance(t, bool):
                    continue
                killer = ev.get("KillerName")
                if killer in enemy_set:
                    killer_team = "enemy"
                elif killer in ally_set:
                    killer_team = "ally"
                else:
                    killer_team = "unknown"
                objective_events.append({"name": obj, "killer_team": killer_team,
                                         "down_at_s": float(t)})
        except Exception:  # noqa: BLE001
            objective_events = []
        out["objective_events"] = objective_events
        # s184 - surface liveclient's gameId for per-game dedup tokens
        # (archetype-nudge state). Live Client doesn't always expose this
        # at gameData root; fall back to "" so callers detect absence.
        gid = gd.get("gameId") or gd.get("gameID") or ""
        out["game_id"] = str(gid) if gid else ""

        # Build path + boots phase via item_advisor (works for SR/Practice;
        # ARAM/Arena/Brawl have their own flows but this fallback is OK).
        try:
            champ = out.get("champion", "")
            if champ:
                build = resolve_build(champ, enemy_team, owned_items)
                norm_owned = {x.lower().strip() for x in owned_items}
                build_lc = {x.lower().strip() for x in build}
                items_view = []
                # 1. Owned items first (green) - skip trinket since it never sells.
                for it in owned_items:
                    if not it: continue
                    if it.lower().strip() in {"farsight alteration", "stealth ward",
                                              "oracle lens", "scrying orb",
                                              "warding totem"}:
                        continue
                    items_view.append({"name": it, "owned": True, "next": False})
                # 2. Suggested next items (not owned). Skip exclusion-redundant ones.
                for it in build:
                    if it.lower().strip() in norm_owned:
                        continue
                    redundant, _why = is_redundant(it, owned_items)
                    if redundant:
                        continue
                    items_view.append({"name": it, "owned": False, "next": True})
                out["sr_items"] = items_view[:9]  # cap at 9 for grid sanity
                out["sr_boots_phase"] = boots_phase(
                    out.get("level") or 1,
                    out.get("gold") or 0,
                    sum(1 for x in owned_items if x),
                    owned_items,
                )
                if out["sr_boots_phase"] in ("consider_sell", "sell_for_quest"):
                    swap = endgame_boots_swap_target(champ, enemy_team, owned_items)
                    if swap and swap[0]:
                        out["sr_boots_swap"] = {"item": swap[0], "reason": swap[1]}
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        return {}
    return out
