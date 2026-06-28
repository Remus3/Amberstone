# arch: PARTY MAINS lobby enrichment (Legion-side, Riot Champion-Mastery-V4) | section=dashboard | frozen=no
"""PARTY MAINS enrichment for the pre-game lobby.

The LCU agent is forwarder-only (ADR-011 - it runs as a bare script and cannot
import ``core.*``); it forwards the raw lobby members. Legion enriches: for each
non-self party member, surface their most-played champion via the Riot
Champion-Mastery-V4 API so the dashboard PARTY MAINS panel (``web/js/main.js``,
which reads ``lcu.party_mains``) shows real data instead of dashed placeholders.

PUUID note: the member PUUID the LCU lobby exposes on current client builds is a
different form that 400s the mastery endpoint, so we resolve the Riot-API
encrypted PUUID from the member's riot-id via Account-V1 first (verified live
2026-06-27).

Non-blocking: ``build_state()`` runs on every ``/api/state`` poll, so the Riot
lookups run in a background thread and ``enrich_party_mains`` serves whatever is
cached (placeholders on the first poll after entering a lobby, real data ~1 poll
later). TTL-cached by member-set so a stable lobby is not re-fetched. Fail-soft
throughout: any lookup failure drops that member's card, never raises.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("rc.party_mains")

_TTL_S = 300.0          # real result good for 5 min (mains do not shift fast)
_EMPTY_RETRY_S = 20.0   # an empty/failed result is retried much sooner
_DEFAULT_REGION = "na1"

_lock = threading.Lock()
_cache: dict = {"key": None, "data": [], "fetched_at": 0.0, "ttl": _TTL_S}
_refreshing: set = set()


def _reset_cache_for_tests() -> None:
    with _lock:
        _cache.update(key=None, data=[], fetched_at=0.0, ttl=_TTL_S)
        _refreshing.clear()


def _eligible(members) -> list:
    """Non-self lobby members that carry a usable riot-id (game_name + tag)."""
    if not isinstance(members, list):
        return []
    return [
        m for m in members
        if isinstance(m, dict) and not m.get("is_self")
        and str(m.get("game_name") or "").strip()
        and str(m.get("tag_line") or "").strip()
    ]


def _member_key(members) -> tuple:
    return tuple(sorted(str(m.get("riot_id") or "") for m in _eligible(members)))


def _member_top_main(member: dict, *, region: str = _DEFAULT_REGION) -> dict | None:
    """One member -> the party_mains card shape, or None (fail-soft).

    Shape mirrors what ``web/js/main.js`` renders:
    ``{name, player, mastery_level, mastery_points}``. The overall/averaged
    stats the panel also shows need that player's match history, which RC does
    not hold, so they degrade to "-" in the panel - the mastery core is what is
    available for an arbitrary other player.
    """
    game_name = str(member.get("game_name") or "").strip()
    tag_line = str(member.get("tag_line") or "").strip()
    if not (game_name and tag_line):
        return None
    try:
        from core import riot_api
        from core.archetype_picks import champion_name_by_key
    except Exception:  # noqa: BLE001 - import failure must not break the state build
        return None
    acct = riot_api.get_account_by_riot_id(game_name, tag_line)
    if not isinstance(acct, dict) or not acct.get("puuid"):
        return None
    tops = riot_api.get_top_champion_masteries(acct["puuid"], count=1, region=region)
    if not isinstance(tops, list) or not tops or not isinstance(tops[0], dict):
        return None
    top = tops[0]
    cid = top.get("championId")
    name = champion_name_by_key(cid) or (str(cid) if cid is not None else "")
    if not name:
        return None
    return {
        "name":           name,
        "player":         member.get("summoner_name") or member.get("riot_id") or "",
        "mastery_level":  top.get("championLevel"),
        "mastery_points": top.get("championPoints"),
    }


def build_party_mains(members, *, region: str = _DEFAULT_REGION) -> list:
    """Synchronous: top champion mastery card for each eligible non-self member.
    Fail-soft per member (a failed lookup is dropped). No caching/threads - this
    is the pure compute used by the background refresh and by tests."""
    out: list = []
    for m in _eligible(members):
        entry = _member_top_main(m, region=region)
        if entry:
            out.append(entry)
    return out


def _refresh(members, key, region) -> None:
    try:
        data = build_party_mains(members, region=region)
    except Exception as exc:  # noqa: BLE001
        log.warning("party_mains refresh failed: %s", exc)
        data = []
    with _lock:
        _cache.update(key=key, data=data, fetched_at=time.time(),
                      ttl=_TTL_S if data else _EMPTY_RETRY_S)
        _refreshing.discard(key)


def _maybe_trigger(members, key, region) -> None:
    """Spawn a background refresh when the cache for this member-set is stale and
    no refresh is already in flight."""
    with _lock:
        fresh = (_cache["key"] == key
                 and (time.time() - _cache["fetched_at"]) < _cache["ttl"])
        if fresh or key in _refreshing:
            return
        _refreshing.add(key)
    threading.Thread(target=_refresh, args=(members, key, region),
                     daemon=True, name="party-mains-refresh").start()


def enrich_party_mains(lcu_snapshot, *, region: str = _DEFAULT_REGION):
    """Inject ``lcu_snapshot['party_mains']`` from the forwarded lobby members.

    Non-blocking: triggers a background Riot fetch when stale, and injects
    whatever is currently cached for this exact member-set. No-op (snapshot
    returned unchanged) when there is no lobby, the party is solo, the snapshot
    is already enriched, or no member carries a riot-id. Never raises.
    """
    if not isinstance(lcu_snapshot, dict) or lcu_snapshot.get("party_mains"):
        return lcu_snapshot
    lobby = lcu_snapshot.get("lobby")
    members = lobby.get("members") if isinstance(lobby, dict) else None
    if not isinstance(members, list) or len(members) < 2:
        return lcu_snapshot
    key = _member_key(members)
    if not key:
        return lcu_snapshot
    _maybe_trigger(members, key, region)
    with _lock:
        if _cache["key"] == key and _cache["data"]:
            lcu_snapshot["party_mains"] = list(_cache["data"])
    return lcu_snapshot
