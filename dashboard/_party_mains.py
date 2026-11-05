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

Trust boundary (s144 true-audit cycle 120): the lobby members are forwarded
LCU bytes RC did not author, and the mastery rows are a Riot API body. At the
boundary:

- a member identity is its ``game_name`` + ``tag_line`` as plain strings,
  stripped, printable and length-bounded; anything else is not eligible, and
  at most ``_MAX_MEMBERS`` distinct identities are looked up per refresh;
- the member-set cache key is built from that SAME normalised identity (plus
  the region) - never from the separate ``riot_id`` field, which may be empty
  or disagree with what is actually queried;
- a card carries a positive integer champion id, integer-or-None mastery
  numbers and a bounded string player label;
- one member's lookup raising drops only that member, logged by exception
  type (never the message, which may carry another player's Riot ID);
- the TTL runs on the monotonic clock, a refresh started for an older lobby
  never overwrites a newer one's result, a thread that cannot start releases
  its in-flight key, and every caller gets its own copy of the cards.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("rc.party_mains")

_TTL_S = 300.0          # real result good for 5 min (mains do not shift fast)
_EMPTY_RETRY_S = 20.0   # an empty/failed result is retried much sooner
_DEFAULT_REGION = "na1"

# Bounds on forwarded lobby bytes. Riot IDs are 3-16 character game names and
# 3-5 character tags; the limits are deliberately looser so no real identity is
# refused, while a junk or hostile value cannot reach a lookup or a cache key.
_MAX_GAME_NAME = 32
_MAX_TAG = 8
_MAX_PLAYER = 64
# A custom 5v5 lobby holds 10, so 10 non-self members is the most a real lobby
# can need; a longer list never fans out more Riot calls than that.
_MAX_MEMBERS = 10
# Mastery has been uncapped since 2024 (levels well past 7); bounds sit far
# above any real account and only reject nonsense.
_MAX_CHAMPION_ID = 1_000_000
_MAX_MASTERY_LEVEL = 10_000
_MAX_MASTERY_POINTS = 1_000_000_000

_lock = threading.Lock()
_cache: dict = {"key": None, "data": [], "fetched_at": 0.0, "ttl": _TTL_S,
                "gen": 0}
_refreshing: set = set()
_next_gen = 0


def _reset_cache_for_tests() -> None:
    global _next_gen
    with _lock:
        _cache.update(key=None, data=[], fetched_at=0.0, ttl=_TTL_S, gen=0)
        _refreshing.clear()
        _next_gen = 0


def _clean_text(value, limit: int) -> str:
    """A stripped, printable string of at most ``limit`` chars, or ``""``."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or len(text) > limit or not text.isprintable():
        return ""
    return text


def _identity(member) -> tuple[str, str] | None:
    """``(game_name, tag_line)`` for a usable member, else None."""
    if not isinstance(member, dict):
        return None
    game = _clean_text(member.get("game_name"), _MAX_GAME_NAME)
    tag = _clean_text(member.get("tag_line"), _MAX_TAG)
    if not (game and tag):
        return None
    return game, tag


def _norm_identity(ident: tuple[str, str]) -> str:
    return f"{ident[0]}#{ident[1]}".casefold()


def _eligible(members) -> list:
    """Non-self lobby members that carry a usable riot-id (game_name + tag).

    Distinct by normalised identity (first occurrence wins) and capped at
    ``_MAX_MEMBERS``.
    """
    if not isinstance(members, list):
        return []
    out: list = []
    seen: set = set()
    for m in members:
        if not isinstance(m, dict) or m.get("is_self"):
            continue
        ident = _identity(m)
        if ident is None:
            continue
        norm = _norm_identity(ident)
        if norm in seen:
            continue
        seen.add(norm)
        out.append(m)
        if len(out) >= _MAX_MEMBERS:
            break
    return out


def _member_key(members, *, region: str = _DEFAULT_REGION) -> tuple:
    """Cache key for this member-set: the region plus the sorted normalised
    identities that are actually looked up. Empty tuple = nothing to look up."""
    idents = sorted(_norm_identity(_identity(m)) for m in _eligible(members))
    if not idents:
        return ()
    return (str(region).casefold(), *idents)


def _champion_id(raw) -> int | None:
    """A positive integer champion id (int or ASCII-digit string), else None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not (text.isascii() and text.isdigit() and len(text) <= 7):
            return None
        value = int(text)
    else:
        return None
    return value if 0 < value <= _MAX_CHAMPION_ID else None


def _count(raw, limit: int) -> int | None:
    """A non-negative integer no larger than ``limit``, else None."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if 0 <= raw <= limit else None


def _player_label(member: dict, ident: tuple[str, str]) -> str:
    for field in ("summoner_name", "riot_id"):
        text = _clean_text(member.get(field), _MAX_PLAYER)
        if text:
            return text
    return f"{ident[0]}#{ident[1]}"


def _member_top_main(member: dict, *, region: str = _DEFAULT_REGION) -> dict | None:
    """One member -> the party_mains card shape, or None (fail-soft).

    Shape mirrors what ``web/js/main.js`` renders:
    ``{name, player, mastery_level, mastery_points}``. The overall/averaged
    stats the panel also shows need that player's match history, which RC does
    not hold, so they degrade to "-" in the panel - the mastery core is what is
    available for an arbitrary other player. A raise (including an import
    failure) propagates to ``build_party_mains``, which drops only this member.
    """
    ident = _identity(member)
    if ident is None:
        return None
    from core import riot_api
    from core.archetype_picks import champion_name_by_key
    acct = riot_api.get_account_by_riot_id(ident[0], ident[1])
    if not isinstance(acct, dict):
        return None
    puuid = acct.get("puuid")
    if not isinstance(puuid, str) or not puuid.strip():
        return None
    tops = riot_api.get_top_champion_masteries(puuid, count=1, region=region)
    if not isinstance(tops, list) or not tops or not isinstance(tops[0], dict):
        return None
    top = tops[0]
    cid = _champion_id(top.get("championId"))
    if cid is None:
        return None
    name = champion_name_by_key(cid)
    if not isinstance(name, str) or not name.strip():
        name = str(cid)
    return {
        "name":           name,
        "player":         _player_label(member, ident),
        "mastery_level":  _count(top.get("championLevel"), _MAX_MASTERY_LEVEL),
        "mastery_points": _count(top.get("championPoints"), _MAX_MASTERY_POINTS),
    }


def build_party_mains(members, *, region: str = _DEFAULT_REGION) -> list:
    """Synchronous: top champion mastery card for each eligible non-self member.
    Fail-soft per member (a failed or raising lookup is dropped, the rest
    stand). No caching/threads - this is the pure compute used by the
    background refresh and by tests."""
    out: list = []
    for m in _eligible(members):
        try:
            entry = _member_top_main(m, region=region)
        except Exception as exc:  # noqa: BLE001 - one member must not drop the rest
            log.warning("party_mains: member lookup failed (%s)",
                        type(exc).__name__)
            continue
        if entry:
            out.append(entry)
    return out


def _refresh(members, key, region, gen=None) -> None:
    """Background body: fetch, then publish under the lock unless a refresh
    triggered LATER (higher ``gen``) has already published. ``gen=None`` (a
    direct call) always publishes. The in-flight key is released on every
    path."""
    rate_limited = False
    scope = None
    try:
        try:
            from core import riot_api
            with riot_api.track_outcomes() as scope:
                data = build_party_mains(members, region=region)
            rate_limited = scope.rate_limited
        except Exception as exc:  # noqa: BLE001 - a refresh must never kill its thread silently
            log.warning("party_mains refresh failed (%s)", type(exc).__name__)
            data = []
        if rate_limited:
            # A throttled member was DROPPED, not absent. Holding the partial
            # result for the full 5-min TTL would hide that member's card for 5
            # minutes; retry on the short cadence instead.
            log.info("party_mains: Riot API rate limited (outcomes=%s)",
                     ",".join(scope.outcomes))
        with _lock:
            if gen is not None and gen < _cache.get("gen", 0):
                log.debug("party_mains: dropped a superseded refresh")
                return
            _cache.update(
                key=key, data=data, fetched_at=time.monotonic(),
                ttl=_TTL_S if (data and not rate_limited) else _EMPTY_RETRY_S,
                gen=_cache.get("gen", 0) if gen is None else gen)
    finally:
        with _lock:
            _refreshing.discard(key)


def _maybe_trigger(members, key, region) -> None:
    """Spawn a background refresh when the cache for this member-set is stale and
    no refresh is already in flight. A thread that cannot start releases its
    key so the next poll retries, and never raises."""
    global _next_gen
    with _lock:
        fresh = (_cache["key"] == key
                 and (time.monotonic() - _cache["fetched_at"]) < _cache["ttl"])
        if fresh or key in _refreshing:
            return
        _refreshing.add(key)
        _next_gen += 1
        gen = _next_gen
    try:
        threading.Thread(target=_refresh, args=(list(members), key, region, gen),
                         daemon=True, name="party-mains-refresh").start()
    except RuntimeError as exc:
        with _lock:
            _refreshing.discard(key)
        log.warning("party_mains: refresh thread did not start (%s)",
                    type(exc).__name__)


def enrich_party_mains(lcu_snapshot, *, region: str = _DEFAULT_REGION):
    """Inject ``lcu_snapshot['party_mains']`` from the forwarded lobby members.

    Non-blocking: triggers a background Riot fetch when stale, and injects
    whatever is currently cached for this exact member-set (as copies the
    caller may mutate). No-op (snapshot returned unchanged) when there is no
    lobby, the party is solo, the snapshot is already enriched, or no member
    carries a riot-id. Never raises.
    """
    if not isinstance(lcu_snapshot, dict) or lcu_snapshot.get("party_mains"):
        return lcu_snapshot
    lobby = lcu_snapshot.get("lobby")
    members = lobby.get("members") if isinstance(lobby, dict) else None
    if not isinstance(members, list) or len(members) < 2:
        return lcu_snapshot
    key = _member_key(members, region=region)
    if not key:
        return lcu_snapshot
    _maybe_trigger(members, key, region)
    with _lock:
        if _cache["key"] == key and _cache["data"]:
            lcu_snapshot["party_mains"] = [dict(c) for c in _cache["data"]]
    return lcu_snapshot
