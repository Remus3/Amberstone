"""Champ-select payload shaping, decoupled from any LCU transport.

Extracted verbatim from ``tools/lcu_agent.capture_state()`` (2026-07-20,
RC2 lever L3). The dashboard's ``build_state`` wants champ-select from an
in-process ``LcuClient`` instead of the relay hop, but the payload every
consumer reads is AGENT-shaped: slimmed teams, hover/lock split, bench
ids, swap entries, the active round and the Arena sub-team roster. A raw
``LcuClient.get_champ_select()`` is not shape-compatible, so the shaping
had to become callable outside the agent process before either L3 variant
can be wired.

The only dependency is an injected request callable with the agent's
contract::

    request(method: str, path: str, body: dict | None = None)
        -> (payload: object, err: str | None)

so this module holds no connection, no lockfile, no globals, and imports
nothing beyond the stdlib - it is importable from the dashboard process
without dragging in the agent's push loops.

``shape_champ_select`` returns a dict with these keys:

  ``cs_debug``      always present for a champ-select phase. Partial keys
                    the caller MERGES into its own cs_debug breadcrumb:
                    ``cs_session_is_dict``, plus ``queue_obj`` +
                    ``bench_len`` when LCU returned a session dict.
  ``champ_select``  the shaped session. ABSENT (not None) when LCU has no
                    session dict yet, so the caller leaves its own key
                    unset exactly as before.

An empty dict is returned for any phase outside CHAMP_SELECT_PHASES; no
LCU round-trip is spent on a payload the caller would discard.
"""
from __future__ import annotations

from typing import Callable

CHAMP_SELECT_PHASES = ("ChampSelect", "GameStart", "InProgress")

# ARAM-family queue IDs. Mirror of the aram keys in
# core/queue_modes.QUEUE_ID_TO_MODE_KEY (the agent that consumes this runs
# standalone and can't import core.*, so it's a hand-kept mirror - keep
# the two in sync). 2400 = ARAM Mayhem (KIWI gameMode); its absence
# here is why is_aram was False for Mayhem -> the dashboard's
# _csvDetectMode fell through to "sr" and the bench / quick-swap UI
# never rendered (KNOWN BUG 2026-05-17).
ARAM_QUEUE_IDS = frozenset({450, 720, 920, 2400})

# 1750 = live Arena 3x6 (CHERRY); 1700/1710 retained as legacy aliases for
# replay/history match data.
ARENA_QUEUE_IDS = (1700, 1710, 1750)


def active_round(sess: dict) -> dict | None:
    """Derive the active pick/ban round from ``session.actions``.

    ``actions`` is a list of groups; each entry carries at least
    ``actorCellId``, ``type`` (pick|ban), ``championId``,
    ``completed`` (bool), ``isInProgress`` (bool). The cells currently on
    the clock are the in-progress entries; the round's type is the action
    type they share (ban or pick). Used by the dashboard to highlight the
    active border on ally + enemy slots.
    """
    actions = sess.get("actions") or []
    for group in actions:
        if not isinstance(group, list):
            continue
        in_progress = [a for a in group
                       if isinstance(a, dict) and a.get("isInProgress")]
        if not in_progress:
            continue
        # Group should be homogeneous (all bans or all picks). Pick the
        # type from the first in-progress entry and collect its cells.
        kind = "ban" if str(in_progress[0].get("type", "")) == "ban" else "pick"
        cell_ids = [a.get("actorCellId") for a in in_progress
                    if str(a.get("type", "")) == kind
                    and a.get("actorCellId") is not None]
        return {"type": kind, "cell_ids": cell_ids}
    return None


def swap_entries(arr) -> list[dict]:
    """Slim ``positionSwaps`` / ``pickOrderSwaps`` for the push.

    Each LCU entry carries id + cellId + state (AVAILABLE / SENT / RECEIVED /
    ACCEPTED / DECLINED / BUSY / INVALID). The dashboard only needs those
    three fields to render and the agent's swap handlers look them up by
    cell_id on swap requests.
    """
    out = []
    for e in arr or []:
        if not isinstance(e, dict):
            continue
        out.append({
            "id":     e.get("id"),
            "cellId": e.get("cellId"),
            "state":  e.get("state"),
        })
    return out


def arena_teams(sess: dict) -> list[dict]:
    """Distil ``additionalSubteamData`` for the dashboard's Arena enemies
    pane (TEAM 2 / TEAM 3 / TEAM 4 stacked cards).

    LCU emits one entry per sub-team in 2v2v2v2; we forward id, name, an
    ``is_me`` flag (subteam id matches the local cell's subteam id), and
    a slim members list (cellId + championId only - the dashboard already
    has summoner names in ``my_team``/``their_team``).

    Returns an empty list when the session is not in a subteamed queue
    or when LCU has not yet populated the field (pre-reveal).
    """
    raw = sess.get("additionalSubteamData") or []
    if not isinstance(raw, list) or not raw:
        return []
    my_subteam = None
    try:
        local_cell = int(sess.get("localPlayerCellId", -1))
    except (TypeError, ValueError):
        local_cell = -1
    if local_cell >= 0:
        for tm in raw:
            if not isinstance(tm, dict):
                continue
            members = tm.get("members") or []
            if any(isinstance(m, dict) and int(m.get("cellId", -2)) == local_cell
                   for m in members):
                my_subteam = tm.get("subteamId") or tm.get("id")
                break
    out = []
    for tm in raw:
        if not isinstance(tm, dict):
            continue
        sid = tm.get("subteamId") or tm.get("id")
        cells = []
        for m in tm.get("members") or []:
            if not isinstance(m, dict):
                continue
            cells.append({
                "cellId":     m.get("cellId"),
                "championId": m.get("championId", 0),
            })
        out.append({
            "id":    sid,
            "name":  tm.get("name") or f"Team {sid}",
            "is_me": (my_subteam is not None and sid == my_subteam),
            "cells": cells,
        })
    return out


def _team_picks(team_arr) -> list[dict]:
    """Slim a myTeam / theirTeam array for the dashboard.

    2026-04-25: the full arrays ship so the dashboard can run cold-start
    adaptation lookups during champ-select (champion + matchup history)
    without waiting for the game to start.
    """
    out = []
    for p in team_arr or []:
        if not isinstance(p, dict):
            continue
        # s171 hover fix: championId is 0 until lock; the hovered champ
        # lives in championPickIntent. Surface both so the dashboard can
        # render hover state and locked state distinctly, and
        # ``championId`` falls back to the intent so legacy renderers that
        # read only championId still see the hover.
        cid_locked = p.get("championId", 0) or 0
        cid_intent = p.get("championPickIntent", 0) or 0
        cid_effective = cid_locked or cid_intent
        out.append({
            "cellId":      p.get("cellId"),
            "championId":  cid_effective,
            "champion_pick_intent": cid_intent,
            "champion_locked": cid_locked,
            "summonerId":  p.get("summonerId"),
            "summonerName": p.get("summonerInternalName") or p.get("displayName") or "",
            # FU02 team-context refresh needs PUUIDs to fan out
            # to Riot Web API. theirTeam may carry empty puuid
            # before reveal in some queue types - that's fine,
            # the route's worker skips entries with no puuid.
            "puuid":       p.get("puuid") or "",
            "completed":   p.get("completed", False),
            "assignedPosition": p.get("assignedPosition") or "",
            # s166 Phase 3 step 4: per-player summoner-spell ids
            # so the Loading view can render the D/F icons next
            # to each summoner. 0/0 when not yet picked.
            "summoners":   [p.get("spell1Id", 0),
                            p.get("spell2Id", 0)],
        })
    return out


def _local_pick_completed(sess: dict, local_cell) -> bool:
    """True once the local cell's pick action is locked in.

    s171.3: my_completed cannot come from myTeam[i] - LCU's schema has no
    ``completed`` field there, so it always read False and the dashboard
    showed "HOVERING" forever after lock. The true lock state is
    ``sess.actions[N][M].completed`` for the local cell's pick action.
    """
    for group in sess.get("actions", []) or []:
        if not isinstance(group, list):
            continue
        for action in group:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "pick":
                continue
            try:
                actor = int(action.get("actorCellId", -2))
            except (TypeError, ValueError):
                continue
            try:
                local = int(local_cell) if local_cell is not None else -1
            except (TypeError, ValueError):
                local = -1
            if actor != local:
                continue
            if action.get("completed"):
                return True
    return False


def shape_champ_select(
    request: Callable[..., tuple], phase: str,
) -> dict:
    """Fetch + shape champ-select for ``phase`` using ``request``.

    See the module docstring for the return contract.
    """
    if phase not in CHAMP_SELECT_PHASES:
        return {}

    sess, _ = request("GET", "/lol-champ-select/v1/session")
    # KNOWN-BUG diagnostic enrichment: did /lol-champ-select/v1/
    # session even return a dict for this mode? For KIWI / Mayhem
    # the open question is whether the agent ever sees a populated
    # champ-select session at all. The full queue object (id /
    # mapId / gameMode / type) is the robust signal a future
    # is_aram could key off instead of a brittle queue-id list -
    # capture its real shape live rather than guessing it now.
    cs_debug: dict = {"cs_session_is_dict": isinstance(sess, dict)}
    if not isinstance(sess, dict):
        return {"cs_debug": cs_debug}

    _q = (sess.get("gameData", {}).get("queue", {})
          if "gameData" in sess else {})
    cs_debug["queue_obj"] = {
        "id":       _q.get("id"),
        "mapId":    _q.get("mapId"),
        "gameMode": _q.get("gameMode"),
        "type":     _q.get("type"),
        "category": _q.get("category"),
    }
    cs_debug["bench_len"] = len(sess.get("benchChampions", []) or [])

    local_cell = sess.get("localPlayerCellId", -1)
    my_pick = next((p for p in sess.get("myTeam", [])
                    if p.get("cellId") == local_cell), None)
    queue_id = (sess.get("gameData", {}).get("queue", {}).get("id", 0)
                if "gameData" in sess else 0)
    # 2026-05-09 (s154): /lol-champ-select/v1/session frequently omits
    # gameData during BAN_PICK, leaving queue_id=0. The dashboard's
    # sr_draft gate (is_sr_draft_queue) then evaluates False and the
    # entire DS engine-profile chooser block stays hidden - no champion
    # hints during draft. Fall back to /lol-gameflow/v1/session, which
    # carries gameData.queue.id reliably from queue-pop onward.
    if not queue_id:
        gf, _ = request("GET", "/lol-gameflow/v1/session")
        if isinstance(gf, dict):
            queue_id = (gf.get("gameData", {}).get("queue", {})
                        .get("id", 0) or 0)

    # s171 hover fix: my_champion = locked OR hovered. The lock
    # button visibility on the dashboard depends on this - if
    # the operator is hovering Vayne, my_champion should be 67
    # so the lock button activates.
    _my_locked = (my_pick or {}).get("championId", 0) or 0
    _my_intent = (my_pick or {}).get("championPickIntent", 0) or 0
    champ_select = {
        "queue_id":     queue_id,
        "is_aram":      queue_id in ARAM_QUEUE_IDS,
        # s171.3: local_cell exposed so the dashboard's role
        # resolver (_csvResolveRole) can find my_team[i] by
        # cellId == local_cell to read assignedPosition. Without
        # this the role stays "-" and the P&B fetch never fires.
        "local_cell":   local_cell if isinstance(local_cell, int) else -1,
        "my_champion":  _my_locked or _my_intent,
        "my_champion_locked":  _my_locked,
        "my_champion_intent":  _my_intent,
        "my_completed": _local_pick_completed(sess, local_cell),
        "my_summoners": [
            (my_pick or {}).get("spell1Id", 0),
            (my_pick or {}).get("spell2Id", 0),
        ],
        "bench": [c.get("championId") for c in sess.get("benchChampions", [])
                  if isinstance(c, dict)],
        "phase": (sess.get("timer") or {}).get("phase"),
        "my_team":     _team_picks(sess.get("myTeam")),
        "their_team":  _team_picks(sess.get("theirTeam")),
        "trades": [
            {"id": t.get("id"), "cellId": t.get("cellId"),
             "state": t.get("state")}
            for t in (sess.get("trades") or [])
            if isinstance(t, dict)
        ],
        # Swap candidate lists. Mirror trades - slim id/cellId/state
        # so the dashboard can render the SWAP popup and the
        # request_position_swap / request_pick_order_swap handlers
        # resolve cell_id -> swap id without a 2nd LCU GET.
        "position_swaps":   swap_entries(sess.get("positionSwaps")),
        "pick_order_swaps": swap_entries(sess.get("pickOrderSwaps")),
        # Active round (cells on the clock + pick|ban). Drives the
        # ally/enemy gold (pick) / red (ban) active border in the
        # Champ Select view.
        "active_round": active_round(sess),
    }
    # Arena (2v2v2v2 / Cherry) extras. LCU surfaces sub-team
    # rosters via ``additionalSubteamData`` (id, name, intro
    # animation, members[cellId, championId]); the dashboard
    # consumes ``arena_teams`` as a flat list. Augment intent +
    # options need /lol-cherry/v1/* discovery against a live
    # Arena game - until then we only forward the subteam roster
    # so allies + enemies render correctly; augments stays an
    # empty scaffold and ``set_augment_intent`` no-ops.
    if queue_id in ARENA_QUEUE_IDS:
        champ_select["arena_teams"] = arena_teams(sess)
        champ_select["augments"] = {
            "my_slots":      ["", "", ""],
            "options":       [],
            "current_round": 0,
        }

    return {"cs_debug": cs_debug, "champ_select": champ_select}
