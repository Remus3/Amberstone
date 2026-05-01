"""Live Client + LCU relay summary helpers.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

Both summaries pull from the in-process vision server on Legion
(`127.0.0.1:8889`), which mirrors the latest LCU + Live Client
snapshots pushed by the Game-PC agents (`gamepc_lcu_agent.py`,
`gamepc_liveclient_relay.py`). Each summary is a best-effort cheap
shape used by the dashboard:

  lcu_summary()        — champ-select / lobby / queue context
  liveclient_summary() — in-game derived fields (game_time, kda,
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
filter). The import is hoisted to module scope — `item_advisor` is
pure-Python data dicts at load time with no expensive side effects.
"""
from __future__ import annotations

import json
import time
import urllib.request

from core.vision_token import get_vision_token
from item_advisor import (
    boots_phase,
    endgame_boots_swap_target,
    is_redundant,
    resolve_build,
)

_VISION_TOKEN = get_vision_token()


def lcu_summary() -> dict:
    """Read latest LCU snapshot pushed by gamepc_lcu_agent.py.
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
    except Exception:
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
        if me_pl:
            s = me_pl.get("scores") or {}
            out["kda"] = f'{s.get("kills",0)}/{s.get("deaths",0)}/{s.get("assists",0)}'
            out["cs"]  = s.get("creepScore", 0)
            out["champion"] = me_pl.get("championName")
            owned_items = [it.get("displayName", "") for it in (me_pl.get("items") or [])]
            my_team = me_pl.get("team")
            enemy_team = [p.get("championName", "") for p in (d.get("allPlayers") or [])
                          if p.get("team") and p.get("team") != my_team]
        out["game_mode"] = gd.get("gameMode")
        out["owned_items"] = owned_items
        out["enemy_team"]  = enemy_team

        # Build path + boots phase via item_advisor (works for SR/Practice;
        # ARAM/Arena/Brawl have their own flows but this fallback is OK).
        try:
            champ = out.get("champion", "")
            if champ:
                build = resolve_build(champ, enemy_team, owned_items)
                norm_owned = {x.lower().strip() for x in owned_items}
                build_lc = {x.lower().strip() for x in build}
                items_view = []
                # 1. Owned items first (green) — skip trinket since it never sells.
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
        except Exception:
            pass
    except Exception:
        return {}
    return out
