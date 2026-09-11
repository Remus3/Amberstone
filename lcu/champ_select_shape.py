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
# RM-140 (2026-08-02) added the rest of the client-visible Mayhem family
# (2401/2403/2405 variants, 2410 Tournament, 2450 Classic-ish) for exactly
# the reason above: an unmapped Mayhem id reproduces the 2026-05-17 bug.
ARAM_QUEUE_IDS = frozenset({450, 720, 920, 2400, 2401, 2403, 2405, 2410, 2450})

# 1750 = live Arena 3x6 (CHERRY); 1700/1710 retained as legacy aliases for
# replay/history match data.
ARENA_QUEUE_IDS = (1700, 1710, 1750)


# -- Fail-soft field readers -------------------------------------------------
# This module is called from two places that both swallow exceptions, so a
# raise here still costs the whole champ-select payload:
#
#   dashboard/_lcu_inprocess.py:255-257  catches Exception and returns None,
#       and the in-process L3 path falls back to the :8889 relay hop that L3
#       exists to remove. RM-312 (2026-09-11) made that degrade VISIBLE - it
#       now WARNs once per distinct fault signature - so the fault is no
#       longer invisible, but the payload for that build is still gone.
#   tools/lcu_agent.py:1612              calls capture_state() inside the
#       state push loop, so the whole snapshot for that tick is lost, and
#       that half is still silent.
#
# The module already fails soft nearly everywhere (isinstance guards on
# trades, bench entries, action groups, team entries). These readers exist so
# that decision is applied UNIFORMLY - the sites below were the ones it had
# been missed at. lcu/snapshot_shape.py:509-517 records the identical defect
# found in its own gameflow read, eleven lines after it calls into here.

def _as_dict(value) -> dict:
    """``value`` when it is a dict, else an empty dict.

    ``payload.get(key, {})`` hands back the default only when the key is
    ABSENT. LCU routinely emits a present-and-NULL sub-object, and the
    chained ``.get`` on that None then raised AttributeError.
    """
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    """``value`` when it is a list, else an empty list.

    NOT the same as ``value or []``, which forwards any truthy non-list
    unchanged: a string then iterates per character and an int raises
    TypeError. Both shapes reached this module's loops.
    """
    return value if isinstance(value, list) else []


def _as_int(value, default: int) -> int:
    """``int(value)`` when it coerces, else ``default``.

    A ``.get(key, default)`` default only fires for an ABSENT key, so a
    present-and-null field reached ``int()`` and raised.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def active_round(sess: dict) -> dict | None:
    """Derive the active pick/ban round from ``session.actions``.

    ``actions`` is a list of groups; each entry carries at least
    ``actorCellId``, ``type`` (pick|ban), ``championId``,
    ``completed`` (bool), ``isInProgress`` (bool). The cells currently on
    the clock are the in-progress entries; the round's type is the action
    type they share (ban or pick). Used by the dashboard to highlight the
    active border on ally + enemy slots.
    """
    actions = _as_list(sess.get("actions"))
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
    for e in _as_list(arr):
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
    raw = _as_list(sess.get("additionalSubteamData"))
    if not raw:
        return []
    my_subteam = None
    local_cell = _as_int(sess.get("localPlayerCellId", -1), -1)
    if local_cell >= 0:
        for tm in raw:
            if not isinstance(tm, dict):
                continue
            members = _as_list(tm.get("members"))
            if any(isinstance(m, dict)
                   and _as_int(m.get("cellId"), -2) == local_cell
                   for m in members):
                my_subteam = tm.get("subteamId") or tm.get("id")
                break
    out = []
    for tm in raw:
        if not isinstance(tm, dict):
            continue
        sid = tm.get("subteamId") or tm.get("id")
        cells = []
        for m in _as_list(tm.get("members")):
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


def _obfuscated_name(index: int, cell_id, local_cell) -> str:
    """Riot-compliant champ-select display name for one roster slot.

    Riot compliance 2026-08-11: "All instances of non-party Summoner Names in
    Champion Select should be replaced with Ally #", and the designation must be
    CONSISTENT ACROSS ALL CLIENTS. The label is therefore derived from the slot's
    position in the LCU team array, which every client observes identically -
    never from a local sort, a name or a puuid.

    The local player keeps a real label ("You") because it is the operator's own
    name, not another player's. RC has no party roster at this seam, so every
    other slot is obfuscated - over-complying rather than guessing at premades.
    The rule is scoped to Champion Select only; the loading screen and post-game
    surfaces are exempt and are unaffected by this helper.
    See docs/OVERLAY_COMPLIANCE_PLAN.md.
    """
    try:
        if local_cell is not None and cell_id is not None and int(cell_id) == int(local_cell):
            return "You"
    except (TypeError, ValueError):
        pass
    return f"Ally {index + 1}"


def _team_picks(team_arr, local_cell=None) -> list[dict]:
    """Slim a myTeam / theirTeam array for the dashboard.

    2026-04-25: the full arrays ship so the dashboard can run cold-start
    adaptation lookups during champ-select (champion + matchup history)
    without waiting for the game to start.
    """
    out = []
    for _idx, p in enumerate(_as_list(team_arr)):
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
            # Riot compliance 2026-08-11: the real LCU name is NOT emitted here.
            # Obfuscation happens at the PRODUCER so every consumer - dashboard,
            # overlay, coach prompt, mock fixtures - inherits it and no renderer
            # can leak a name by forgetting to mask. Do not restore
            # summonerInternalName / displayName; see docs/OVERLAY_COMPLIANCE_PLAN.md.
            "summonerName": _obfuscated_name(_idx, p.get("cellId"), local_cell),
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
    for group in _as_list(sess.get("actions")):
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

    _q = _as_dict(_as_dict(sess.get("gameData")).get("queue"))
    cs_debug["queue_obj"] = {
        "id":       _q.get("id"),
        "mapId":    _q.get("mapId"),
        "gameMode": _q.get("gameMode"),
        "type":     _q.get("type"),
        "category": _q.get("category"),
    }
    cs_debug["bench_len"] = len(_as_list(sess.get("benchChampions")))

    # s155 (tools/lcu_agent.py:919-921): some LCU builds emit
    # localPlayerCellId / cellId as JSON strings depending on the patch.
    # A bare == then silently missed on any MIXED pairing, so my_champion
    # read 0 and the dashboard lock button never activated. That cast was
    # applied to the agent's lock_pick handler and never to the shaper.
    # Normalize once, then compare like against like.
    local_cell = _as_int(sess.get("localPlayerCellId", -1), -1)
    my_pick = next((p for p in _as_list(sess.get("myTeam"))
                    if isinstance(p, dict)
                    and _as_int(p.get("cellId"), -2) == local_cell), None)
    queue_id = _q.get("id", 0) or 0
    # 2026-05-09 (s154): /lol-champ-select/v1/session frequently omits
    # gameData during BAN_PICK, leaving queue_id=0. The dashboard's
    # sr_draft gate (is_sr_draft_queue) then evaluates False and the
    # entire DS engine-profile chooser block stays hidden - no champion
    # hints during draft. Fall back to /lol-gameflow/v1/session, which
    # carries gameData.queue.id reliably from queue-pop onward.
    if not queue_id:
        gf, _ = request("GET", "/lol-gameflow/v1/session")
        queue_id = _as_dict(
            _as_dict(_as_dict(gf).get("gameData")).get("queue")
        ).get("id", 0) or 0

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
        "local_cell":   local_cell,
        "my_champion":  _my_locked or _my_intent,
        "my_champion_locked":  _my_locked,
        "my_champion_intent":  _my_intent,
        "my_completed": _local_pick_completed(sess, local_cell),
        "my_summoners": [
            (my_pick or {}).get("spell1Id", 0),
            (my_pick or {}).get("spell2Id", 0),
        ],
        "bench": [c.get("championId")
                  for c in _as_list(sess.get("benchChampions"))
                  if isinstance(c, dict)],
        "phase": _as_dict(sess.get("timer")).get("phase"),
        "my_team":     _team_picks(sess.get("myTeam"), local_cell),
        "their_team":  _team_picks(sess.get("theirTeam"), local_cell),
        "trades": [
            {"id": t.get("id"), "cellId": t.get("cellId"),
             "state": t.get("state")}
            for t in _as_list(sess.get("trades"))
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
