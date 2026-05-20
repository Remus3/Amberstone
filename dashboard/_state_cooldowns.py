# arch: adapts Live Client snapshot -> compute_cooldowns input | section=dashboard | frozen=no
"""Live Client snapshot -> summoner_cooldowns adapter.

Bridges the raw `/allgamedata` shape that the Game-PC liveclient relay
publishes into the participant + event dict shape that
``core.summoner_cooldowns.compute_cooldowns`` expects.

Shipped via ``dashboard/_state_builder.build_state`` as the
``summoner_cooldowns`` key on ``/api/state``. Null when no game is
running (``lc`` is empty / liveclient cache stale).

Live Client realities baked in:
  1. The Live Client API does NOT emit ``SUMMONER_SPELL_USED`` or
     ``ULTIMATE_USED`` events - the only events that show up in
     ``gameData.events.Events`` are ``ChampionKill``, ``DragonKill``,
     ``BaronKill``, ``TurretKilled``, ``InhibKilled``, ``Multikill``,
     ``Ace``, ``FirstBlood``, ``GameStart``, ``MinionsSpawning``, etc.
     We pass an empty event list to ``compute_cooldowns`` - every
     summoner + ult renders as READY (``cd_remaining_s == 0``).
     The panel still gets useful info: who has Flash vs Ignite, who has
     Cleanse vs Heal, the Ionian / Cosmic CDR-aware effective cd if/when
     a future event source (decision_detector? OCR?) lands. Wiring the
     panel today does not block on the event-source slice.
  2. ``allPlayers[].summonerSpells.summonerSpellOne/Two.displayName`` is
     a string ("Flash", "Smite"), NOT the Riot numeric id. We invert
     ``SUMMONER_SPELL_NAME`` to map name -> numeric id; misses (Cherry
     Flash, Poro Toss, etc.) fall back to id=None which renders as a
     READY 0-cd row.
  3. Live Client does not expose puuid in ``allPlayers``; we match
     events by ``summoner_name`` only (``compute_cooldowns`` supports
     both paths via its ``_events_for_participant`` helper).
  4. Live Client does not expose per-player rune ids or item ids unless
     vision OCR fills them in. For now we leave runes=[] and items=[]
     for non-self players (no CDR applied to enemies until OCR catches
     them). The active player's items DO arrive via
     ``activePlayer.fullRunes`` (rune ids) and ``allPlayers[i].items[].itemID``;
     we wire both.
  5. Ultimate ids are not exposed by Live Client. We pass ``ult_id=None``
     and the default 100 s base CD; the panel renders an ult row with the
     conservative midgame cd. A future patch can plug champion->ult-id
     resolution.

Returns ``None`` when no live game (lc empty), otherwise the list returned
by ``compute_cooldowns`` (length matches the number of resolvable players,
sorted by next-up ascending).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.summoner_cooldowns import SUMMONER_SPELL_NAME, compute_cooldowns

log = logging.getLogger("rc.dashboard.cooldowns")


# Inverted ``SUMMONER_SPELL_NAME`` (defined once at import; the mapping
# is small + immutable so a class-level dict is fine).
_NAME_TO_ID: dict[str, int] = {
    name: spell_id for spell_id, name in SUMMONER_SPELL_NAME.items()
}


def _name_to_id(display_name: str | None) -> int | None:
    """Map a Live Client ``displayName`` to Riot's integer spell id.

    Returns ``None`` for unknown / event-mode spells (Cherry Flash, Poro
    Toss, Mark, etc.) - the cooldown module treats these as 0-base / READY.
    """
    if not display_name:
        return None
    return _NAME_TO_ID.get(str(display_name))


def _side_for(team: str | None) -> str:
    """Live Client emits ``ORDER`` / ``CHAOS`` team strings."""
    if team == "ORDER":
        return "blue"
    if team == "CHAOS":
        return "red"
    return ""


def _participants_from_liveclient(data: dict) -> list[dict]:
    """Build the participants list ``compute_cooldowns`` expects.

    One entry per ``allPlayers[i]``. Missing fields degrade gracefully
    (None / [] / "") - ``compute_cooldowns`` is defensive against that.
    """
    all_players = data.get("allPlayers") or []
    active = data.get("activePlayer") or {}
    me_name = active.get("summonerName", "") if isinstance(active, dict) else ""
    # ``activePlayer.fullRunes`` carries the operator's rune ids; only
    # the active player gets this. Enemies + allies show up as runes=[].
    active_rune_ids: list[int] = []
    if isinstance(active, dict):
        runes_block = active.get("fullRunes") or {}
        if isinstance(runes_block, dict):
            primary = runes_block.get("generalRunes") or []
            keystone = runes_block.get("keystone") or {}
            if isinstance(keystone, dict) and keystone.get("id") is not None:
                try:
                    active_rune_ids.append(int(keystone["id"]))
                except (TypeError, ValueError):
                    pass
            for r in primary:
                if isinstance(r, dict) and r.get("id") is not None:
                    try:
                        active_rune_ids.append(int(r["id"]))
                    except (TypeError, ValueError):
                        pass

    out: list[dict] = []
    for p in all_players:
        if not isinstance(p, dict):
            continue
        ss = p.get("summonerSpells") or {}
        if not isinstance(ss, dict):
            ss = {}
        ss_d = ss.get("summonerSpellOne") or {}
        ss_f = ss.get("summonerSpellTwo") or {}
        d_name = ss_d.get("displayName") if isinstance(ss_d, dict) else None
        f_name = ss_f.get("displayName") if isinstance(ss_f, dict) else None

        items_raw = p.get("items") or []
        item_ids: list[int] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            iid = it.get("itemID")
            if iid is None:
                continue
            try:
                item_ids.append(int(iid))
            except (TypeError, ValueError):
                continue

        is_me = bool(me_name) and p.get("summonerName") == me_name
        runes = active_rune_ids if is_me else []

        out.append({
            "puuid": None,                                     # Live Client lacks it.
            "summoner_name": p.get("summonerName") or "",
            "champion_id": None,                               # Resolve later if needed.
            "champion_name": p.get("championName") or "",      # Useful for the panel.
            "side": _side_for(p.get("team")),
            "d_spell_id": _name_to_id(d_name),
            "f_spell_id": _name_to_id(f_name),
            "ult_id": None,                                    # Champion->ult-id TBD.
            "ult_base_cd": 100.0,                              # Conservative default.
            "runes": runes,
            "items": item_ids,
        })
    return out


def _events_from_liveclient(data: dict) -> list[dict]:
    """Live Client never emits SUMMONER_SPELL_USED / ULTIMATE_USED.

    Returned list is empty by design - the panel renders all spells as
    READY until an event source (decision_detector, vision OCR, future
    LCU plugin) fills it in. Kept as a function so the wire path is
    explicit and a future event-source can slot in without changing the
    builder.
    """
    return []


def compute_state_cooldowns(lc: dict | None) -> list[dict] | None:
    """Top-level wire helper. Pass the trimmed ``lc`` from
    ``liveclient_summary()`` - any falsy value (no game) returns ``None``.

    Fetches the FULL raw allgamedata from ``core.liveclient_cache.get()``
    so we can read ``allPlayers``, ``activePlayer.fullRunes``, etc.
    """
    if not lc:
        return None
    try:
        from core.liveclient_cache import get as _lc_get
        snap = _lc_get()
        if snap.data is None or snap.age_s >= 8.0:
            return None
        participants = _participants_from_liveclient(snap.data)
        if not participants:
            return None
        events = _events_from_liveclient(snap.data)
        return compute_cooldowns(participants, events, now_s=time.time())
    except Exception as exc:
        log.debug("compute_state_cooldowns: %s", exc)
        return None


__all__ = ["compute_state_cooldowns"]
