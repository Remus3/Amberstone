# arch: GET /api/team-context + POST /api/team-context/refresh | section=dashboard | frozen=no
"""Team-context routes for the FU02 champ-select 5+5 enrichment panel.

Wire shape:
  POST /api/team-context/refresh  <- Legion LCU agent on ChampSelect
                                    transition. Body is the 10-player
                                    roster + queue_id. Local-only now
                                    (loopback / Tailnet); the former
                                    cross-Claude bridge auth posture is
                                    retired with the bridge decommission.
  GET  /api/team-context           <- Dashboard poll. No auth (loopback /
                                    Tailnet-only, served by HTTPS dashboard).

Storage: in-memory dict guarded by a Lock - single-process, so it lives
as long as the RC process (a restart empties it), which is the desired
lifetime for a per-game enrichment payload. Readers get a SNAPSHOT copied
under the lock, never the dict the fan-out worker mutates.

Soft-fail invariants:
  - GET on cold cache returns `{"team_context": null, "age_s": null}`
    (HTTP 200). Dashboard treats null as "not in champ-select".
  - POST with a non-object body or a non-list / oversized roster -> 400
    (the dispatcher's api_schema model rejects wrong field types first).
    Each slot is normalised into the skeleton shape; missing fields take
    the skeleton default, extra fields are dropped. There is no auth: the
    route is local-only since the bridge decommission (ADR-012).

Re-POST (s144 true-audit): the LCU agent re-POSTs the whole roster on every
lock / swap. A re-POST keeps the enrichment already fetched for the same
player (rank, mains, win rate, streak, riot_status; mastery only while the
locked champion is unchanged), and a live worker re-enriches every entry
whose (puuid, side, champion) it has not enriched yet before it flips
partial=False - it never marks a roster it did not enrich complete.

Fan-out (FU02 main):
  After the skeleton roster is stored, the POST handler dispatches a
  background worker that calls `core.riot_api` to enrich each entry.
  Priority-1 (mastery + rank) fires first - those land in <30s of
  champ-select start under the 100/2min rate limit. Priority-2
  (mains + winrate + W/L streak) fires after, paced through the
  remaining ~60s of champ-select. The dashboard polls /api/state and
  re-renders as each field arrives - no blocking on full enrichment.

  Dispatch is via a module-level `_FANOUT_DISPATCHER` callable so tests
  can replace it with a no-op without monkey-patching `core.riot_api`.
  The default dispatcher checks `core.riot_api.is_configured()` first;
  if the API key is missing, the fan-out is skipped (skeleton-only).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from dashboard._dispatch import equals

log = logging.getLogger("rc.routes_team_context")

# Module-level cache of the latest team_context payload. None when no
# champ-select has fired since RC boot. _state_builder reads this via
# get_team_context() to splice into /api/state.
_LOCK = threading.Lock()
_CACHE: Optional[dict] = None
_CACHE_TS: float = 0.0

# Hard cap on stored roster size. The LCU agent forwards exactly 10
# players in champ-select; anything bigger is malformed.
_MAX_ROSTER = 10

# Tracks the in-flight fan-out worker so a re-POST during the same
# champ-select doesn't spawn parallel duplicates. None when idle.
_WORKER: Optional[threading.Thread] = None
# True once _WORKER has taken its final look at the roster (or given up).
# From then on it enriches nothing more, so a POST must spawn a new worker
# even though the thread has not exited yet. Guarded by _LOCK.
_WORKER_SETTLED = False

# Enrichment a re-POST carries over for the same player. mastery_on_locked
# is carried separately, and only while the locked champion is unchanged.
# summoner_name is never carried: it is the ranked-blank gate's field.
_CARRY_FIELDS = ("rank", "w_l_streak_7", "mains", "win_rate_recent",
                 "riot_status")
# Every mastery the worker fetched, keyed (puuid, champion) - recorded even
# when the write was refused because the player had re-locked meanwhile.
# A re-POST restores a champion's points from here, so a swap and swap-back
# (Jax -> Fiora -> Jax) keeps Jax's points: the worker counts (puuid, Jax)
# as enriched and will not fetch it again. Pruned to the current roster on
# every store. Guarded by _LOCK.
_MASTERY_SEEN: dict = {}

# Ranked-queue gate: queue IDs where summoner names must NOT be sent to
# the dashboard until loading-screen flag flips. Match-V5 docs queue
# list - Ranked Solo (420), Ranked Flex (440). The render layer also
# enforces this; backend blanking is defense in depth.
_RANKED_BLANK_QUEUES = frozenset({420, 440})


def _snapshot(cache: Optional[dict]) -> Optional[dict]:
    """Copy of the cache down to each entry and its lists. Caller holds
    _LOCK, so a reader sees one consistent state and can never mutate the
    dict the fan-out worker writes into."""
    if cache is None:
        return None
    out = dict(cache)
    for side in ("allies", "enemies"):
        entries = cache.get(side)
        if isinstance(entries, list):
            out[side] = [
                {k: (list(v) if isinstance(v, list) else v)
                 for k, v in e.items()} if isinstance(e, dict) else e
                for e in entries
            ]
    return out


def get_team_context() -> Optional[dict]:
    """Return a snapshot of the latest stored team_context, or None if the
    cache is empty. Used by `dashboard._state_builder.build_state()` to
    splice into `/api/state.coach.team_context` during champ-select."""
    with _LOCK:
        return _snapshot(_CACHE)


def _carry_enrichment(payload: dict, prior: Optional[dict]) -> None:
    """Copy the enrichment `prior` already holds onto the same players in
    `payload` (matched by side + non-empty puuid). Caller holds _LOCK."""
    if not isinstance(prior, dict):
        return
    for side in ("allies", "enemies"):
        old_by_puuid: dict = {}
        for old in prior.get(side) or []:
            if isinstance(old, dict) and old.get("puuid"):
                old_by_puuid.setdefault(old["puuid"], old)
        for entry in payload.get(side) or []:
            if not isinstance(entry, dict):
                continue
            old = old_by_puuid.get(entry.get("puuid") or "")
            if old is None:
                continue
            for field in _CARRY_FIELDS:
                if field in old:
                    entry[field] = old[field]
            seen = _MASTERY_SEEN.get(
                (entry.get("puuid"), entry.get("locked_champion") or ""))
            if seen is not None:
                entry["mastery_on_locked"] = seen
            elif old.get("locked_champion") == entry.get("locked_champion"):
                entry["mastery_on_locked"] = old.get("mastery_on_locked", 0)


def _store(payload: dict) -> None:
    global _CACHE, _CACHE_TS
    with _LOCK:
        _carry_enrichment(payload, _CACHE)
        roster = {e.get("puuid") for side in ("allies", "enemies")
                  for e in (payload.get(side) or []) if isinstance(e, dict)}
        for key in [k for k in _MASTERY_SEEN if k[0] not in roster]:
            del _MASTERY_SEEN[key]
        _CACHE = payload
        _CACHE_TS = time.time()


def _clear() -> None:
    """Reset the cache + cancel any in-flight worker reference. Tests
    rely on this to isolate cases."""
    global _CACHE, _CACHE_TS, _WORKER, _WORKER_SETTLED
    with _LOCK:
        _CACHE = None
        _CACHE_TS = 0.0
        _WORKER = None
        _WORKER_SETTLED = False
        _MASTERY_SEEN.clear()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _as_int(value: Any, default: int = 0) -> int:
    """Best-effort int coercion. Cycle-8 audit: a non-numeric queue_id /
    team_id in the refresh body used to raise ValueError out of the
    handler - the dispatcher has no catch-all, so the caller saw a
    connection reset instead of the documented soft-fail. An infinite
    float raises OverflowError, caught the same way."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _update_entry(team: str, puuid: str,
                  only_if_champion: Optional[str] = None,
                  **fields: Any) -> None:
    """Mutate a single entry in the live cache by team + puuid.

    `team` is one of "allies"/"enemies". Atomically takes the lock,
    bumps `refreshed_at`, applies the supplied fields, and releases.
    Called by the fan-out worker as each Riot API response lands.

    `only_if_champion` (mastery writes): skip the write unless the cached
    entry is still locked on that champion - a re-POST may have swapped it
    while the worker was fetching the old champion's points.
    """
    if not fields:
        return
    global _CACHE, _CACHE_TS
    with _LOCK:
        if only_if_champion is not None and "mastery_on_locked" in fields:
            _MASTERY_SEEN[(puuid, only_if_champion)] = \
                fields["mastery_on_locked"]
        if _CACHE is None:
            return
        entries = _CACHE.get(team)
        if not isinstance(entries, list):
            return
        for entry in entries:
            if isinstance(entry, dict) and entry.get("puuid") == puuid:
                if (only_if_champion is not None
                        and entry.get("locked_champion") != only_if_champion):
                    return
                entry.update(fields)
                _CACHE["refreshed_at"] = _now_iso()
                _CACHE_TS = time.time()
                return


def _mark_complete() -> None:
    """Flip partial=False once the fan-out worker drains. Caller is
    responsible for ensuring this is only called when ALL priority tiers
    have completed (or been skipped)."""
    global _CACHE, _CACHE_TS
    with _LOCK:
        if _CACHE is None:
            return
        _CACHE["partial"] = False
        _CACHE["refreshed_at"] = _now_iso()
        _CACHE_TS = time.time()


def _skeleton_entry(slot: dict, blank_names: bool = False) -> dict:
    """Build a TeamContextEntry-shaped dict from an LCU roster slot.

    Initial population covers the fields the LCU payload already carries
    (puuid, summoner_name, team_id, locked_champion). Riot API enrichment
    (rank, mastery, mains, winrate, streak) lands later via the fan-out
    worker, which mutates each entry in place.

    When `blank_names` is True (ranked queues 420/440), summoner_name is
    forced empty regardless of what the LCU payload supplied - keeps the
    Riot-policy compliance gate visible at the storage layer too.
    """
    name = "" if blank_names else str(slot.get("summoner_name") or "")
    return {
        "puuid":             str(slot.get("puuid") or ""),
        "summoner_name":     name,
        "team_id":           _as_int(slot.get("team_id") or 0),
        "locked_champion":   str(slot.get("locked_champion") or ""),
        "rank":              "",
        "mastery_on_locked": 0,
        "w_l_streak_7":      [0, 0],
        "mains":             [],
        "win_rate_recent":   0.0,
        # "" or "rate_limited". Set by the fan-out when Riot throttled this
        # player's lookups, so the panel can say "rate limited - retrying"
        # instead of painting the throttle as missing data.
        "riot_status":       "",
    }


# -- Riot API fan-out ----------------------------------------------------

# Number of recent matches to scan for mains / winrate / streak.
# Personal-tier ceiling makes 20 the practical max - 10 players x 20
# matches x ~1 cache-miss per call ~ 200 calls in a cold cache, well
# under the 100/2min x full-window budget once paced.
_RECENT_MATCH_DEPTH = 20
# Max time the fan-out worker spends cumulatively before giving up. Champ
# select itself runs ~95s including loading screen; the worker exits
# whenever the dashboard moves out of ChampSelect (no signal yet, so a
# wall clock is the cheap guard).
_FANOUT_DEADLINE_S = 180.0

# Rate-limit retry: how many extra passes the worker makes over entries Riot
# throttled, and the floor/ceiling on each wait between passes. The wait
# follows the bucket's own 429 cooldown (Riot's Retry-After), floored so a
# zero cooldown cannot spin and capped so one long Retry-After cannot eat the
# whole champ-select window in a single sleep.
_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_WAIT_MIN_S = 2.0
_RATE_LIMIT_WAIT_MAX_S = 30.0

# Indirection so tests can skip the real wait.
_sleep = time.sleep

_RATE_LIMITED = "rate_limited"


def _team_of(entry: dict) -> str:
    return "allies" if int(entry.get("team_id") or 0) != 200 else "enemies"


def _note_rate_limited(team: str, puuid: str, tier: str, scope: Any) -> None:
    """Mark the entry and log the raw detail (outcomes) to the RC log only.
    The panel shows a friendly message; the raw outcome never reaches it."""
    log.info("team-context %s: Riot API rate limited (outcomes=%s)",
             tier, ",".join(scope.outcomes))
    _update_entry(team, puuid, riot_status=_RATE_LIMITED)


def _enrich_priority_1(entry: dict, locked_champion_id: Optional[int]) -> bool:
    """Priority-1 fan-out for one entry: mastery + rank.

    Both calls are TTL-cached (5 min) so re-firing the same lobby twice
    is free. Each result mutates the live cache via `_update_entry`.

    Returns True when Riot rate-limited any of the calls (the entry is then
    marked `riot_status="rate_limited"` for the worker to retry).
    """
    from core import riot_api

    puuid = entry.get("puuid") or ""
    if not puuid:
        return False
    team = _team_of(entry)

    with riot_api.track_outcomes() as scope:
        # League-V4 rank. Empty list = unranked; we still want to flag the
        # entry as "looked up" so the skeleton "-" is replaced with the
        # actual rank string ("UNRANKED" sentinel left blank for now;
        # render shows skel placeholder when rank == "").
        entries = riot_api.get_summoner_rank(puuid)
        if entries is not None:
            solo = riot_api.pick_solo_rank(entries)
            rank_str = riot_api.format_rank_entry(solo) if solo else ""
            _update_entry(team, puuid, rank=rank_str)

        # Champion-Mastery-V4 on the locked champion. Skipped when the
        # player hasn't locked yet (championId 0).
        if locked_champion_id and locked_champion_id > 0:
            m = riot_api.get_champion_mastery(puuid, locked_champion_id)
            if isinstance(m, dict):
                mastery_pts = int(m.get("championPoints") or 0)
                _update_entry(
                    team, puuid,
                    only_if_champion=entry.get("locked_champion") or "",
                    mastery_on_locked=mastery_pts)

    if scope.rate_limited:
        _note_rate_limited(team, puuid, "priority-1", scope)
        return True
    return False


def _enrich_priority_2(entry: dict) -> bool:
    """Priority-2 fan-out: recent-matches -> mains / winrate / W/L streak.

    Returns True when Riot rate-limited any of the calls. A throttled
    match-id list or a throttled match detail inside `summarize_recent` both
    count: either way the summary is incomplete, not "no games".
    """
    from core import riot_api

    puuid = entry.get("puuid") or ""
    if not puuid:
        return False
    team = _team_of(entry)

    with riot_api.track_outcomes() as scope:
        match_ids = riot_api.get_recent_matches(puuid, count=_RECENT_MATCH_DEPTH)
        summary = None
        if match_ids:
            summary = riot_api.summarize_recent(puuid, match_ids)
    if summary is not None:
        _update_entry(
            team, puuid,
            mains=summary.get("mains") or [],
            win_rate_recent=float(summary.get("win_rate_recent") or 0.0),
            w_l_streak_7=summary.get("w_l_streak_7") or [0, 0],
        )
    if scope.rate_limited:
        _note_rate_limited(team, puuid, "priority-2", scope)
        return True
    return False


# Map the locked-champion name (LCU payload key) -> numeric ID. The LCU
# agent posts `locked_champion` as the champion's display name string;
# Champion-Mastery-V4 needs the numeric ID. The mapping is read lazily from
# the TRACKED DDragon bundle `data/meta_build/ddragon/<ver>/champion.json`
# (s144 true-audit: the old glob named `data/ddragon/*/data/en_US/`, a path
# that does not exist, so every lookup missed and mastery was never fetched).
# <ver> is `_index.json` `latest_pulled` (the core/rune_wpa.py idiom), else
# the highest version directory compared numerically. A failed load is not
# cached, and a name miss reloads only when the bundle path changed.
# Soft-fail - a missing ID just skips the mastery call for that entry.
_DDRAGON_DIR = (Path(__file__).resolve().parent.parent
                / "data" / "meta_build" / "ddragon")
_CHAMP_NAME_TO_ID_CACHE: Optional[dict] = None
_CHAMP_NAME_TO_ID_SOURCE = ""
_CHAMP_NAMES_LOCK = threading.Lock()


def _version_key(name: str) -> Optional[tuple]:
    """(16, 10, 1) for "16.10.1"; None for anything that is not a version."""
    parts = name.split(".")
    if len(parts) < 2 or not all(p.isascii() and p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def _champion_bundle() -> Optional[Path]:
    """Path of the patch-current champion.json, or None when none exists."""
    root = _DDRAGON_DIR
    try:
        doc = json.loads((root / "_index.json").read_text(encoding="utf-8"))
        ver = doc.get("latest_pulled") if isinstance(doc, dict) else ""
        ver = ver.strip() if isinstance(ver, str) else ""
    except (OSError, ValueError):
        ver = ""
    if ver and _version_key(ver) is not None:
        cand = root / ver / "champion.json"
        if cand.is_file():
            return cand
    best: Optional[tuple] = None
    try:
        for child in root.iterdir():
            key = _version_key(child.name)
            cand = child / "champion.json"
            if key is not None and cand.is_file() and (
                    best is None or key > best[0]):
                best = (key, cand)
    except OSError:
        return None
    return best[1] if best else None


def _load_champion_ids(path: Path) -> dict:
    """{lowercased display name or DDragon id: numeric key}; {} on failure."""
    try:
        with path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        log.debug("champ-name lookup load failed: %s", exc)
        return {}
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return {}
    mapping: dict = {}
    for data_key, cdef in data.items():
        if not isinstance(cdef, dict):
            continue
        try:
            cid = int(cdef.get("key"))
        except (TypeError, ValueError, OverflowError):
            continue
        if cid <= 0:
            continue
        for label in (cdef.get("name"), cdef.get("id"), data_key):
            if isinstance(label, str) and label.strip():
                mapping.setdefault(label.strip().lower(), cid)
    return mapping


def _champ_name_to_id(name: str) -> Optional[int]:
    """Resolve champion display name (or DDragon id) -> Riot champion ID.
    Returns None on any miss; caller skips the mastery call."""
    global _CHAMP_NAME_TO_ID_CACHE, _CHAMP_NAME_TO_ID_SOURCE
    if not isinstance(name, str) or not name.strip():
        return None
    needle = name.strip().lower()
    with _CHAMP_NAMES_LOCK:
        cache = _CHAMP_NAME_TO_ID_CACHE
        if cache is None or needle not in cache:
            path = _champion_bundle()
            if path is not None and (cache is None
                                     or str(path) != _CHAMP_NAME_TO_ID_SOURCE):
                mapping = _load_champion_ids(path)
                if mapping:
                    _CHAMP_NAME_TO_ID_CACHE = cache = mapping
                    _CHAMP_NAME_TO_ID_SOURCE = str(path)
        return (cache or {}).get(needle)


def _identity(entry: dict) -> tuple:
    """What one enrichment covers: the player, their side, their champion."""
    return (entry.get("puuid") or "", _team_of(entry),
            entry.get("locked_champion") or "")


def _settle_or_pending(done: set) -> Optional[list]:
    """The worker's look at the CURRENT roster after a round.

    Returns copies of the entries a re-POST added or changed since the
    worker started (identity not in `done`) for one more round. Otherwise
    flips partial=False, marks the worker settled - all under one lock
    hold, so a POST either lands before (and is seen here) or after (and
    finds the worker settled, so it spawns its own) - and returns None.
    A roster the re-POST turned into a TFT queue is never enriched (S134
    N2) and is left partial, the way the route leaves a TFT POST.
    """
    from core.queue_modes import is_tft_queue
    global _CACHE_TS
    with _LOCK:
        if _CACHE is not None and not is_tft_queue(
                _as_int(_CACHE.get("queue_id"))):
            pending = [
                dict(e)
                for side in ("allies", "enemies")
                for e in (_CACHE.get(side) or [])
                if isinstance(e, dict) and _identity(e) not in done
            ]
            if pending:
                return pending
            _CACHE["partial"] = False
            _CACHE["refreshed_at"] = _now_iso()
            _CACHE_TS = time.time()
        _settle_worker_locked()
    return None


def _settle_worker_locked() -> None:
    """Mark the running worker settled. Caller holds _LOCK."""
    global _WORKER_SETTLED
    if _WORKER is threading.current_thread():
        _WORKER_SETTLED = True


def _fanout_worker(allies: list, enemies: list, queue_id: int) -> None:
    """Fan-out worker - runs in a daemon thread.

    Walks the roster twice: priority-1 across all players first, then
    priority-2. The rate limiter inside `core.riot_api` provides natural
    back-pressure; the worker simply keeps requesting until the bucket
    has room. After each round it re-reads the cache: entries a re-POST
    added or re-locked meanwhile get one more round (same deadline), and
    only a fully enriched roster is marked complete.
    """
    deadline = time.monotonic() + _FANOUT_DEADLINE_S
    everyone = list(allies) + list(enemies)
    log.info("team-context fan-out start: queue=%d roster=%d",
             queue_id, len(everyone))
    done: set = set()
    try:
        while True:
            if not _enrich_round(everyone, deadline):
                return
            done.update(_identity(e) for e in everyone)
            pending = _settle_or_pending(done)
            if pending is None:
                break
            if time.monotonic() >= deadline:
                log.warning("team-context fan-out: roster changed after "
                            "the deadline, %d entries left", len(pending))
                return
            log.info("team-context fan-out: roster changed, enriching %d "
                     "more entries", len(pending))
            everyone = pending
    finally:
        with _LOCK:
            _settle_worker_locked()
    log.info("team-context fan-out done: queue=%d", queue_id)


def _enrich_round(everyone: list, deadline: float) -> bool:
    """One pass over `everyone` plus the rate-limit retries. False when
    priority-1 hit the deadline (the worker then exits without marking
    the roster complete, the pre-existing behaviour)."""
    throttled = _run_pass(everyone, deadline)
    if throttled is None:
        return False

    # Rate-limit retry. An entry Riot throttled is NOT "no data", so it gets
    # re-asked once the bucket's 429 cooldown has run out, a bounded number
    # of times and never past the deadline. The panel reads "rate limited -
    # retrying" while this runs (partial=True) and the entry keeps its mark
    # if every retry is throttled too.
    for attempt in range(_RATE_LIMIT_RETRIES):
        if not throttled:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log.warning("team-context fan-out rate-limit retry hit deadline")
            break
        _sleep(min(remaining, _rate_limit_wait_s()))
        log.info("team-context fan-out rate-limit retry %d/%d: %d entries",
                 attempt + 1, _RATE_LIMIT_RETRIES, len(throttled))
        retry = _run_pass(throttled, deadline, retrying=True)
        if retry is None:
            break
        throttled = retry
    return True


def _rate_limit_wait_s() -> float:
    """Seconds to wait before re-asking Riot: the live 429 cooldown, clamped."""
    cooldown = 0.0
    try:
        from core import riot_api
        snap = riot_api.bucket_snapshot()
        cooldown = float(snap.get("cooldown_remaining_s") or 0.0)
        # A full LONG bucket (100/120s) carries no cooldown - it drains by
        # age - so the floor alone would burn every retry in seconds against
        # a bucket that cannot admit. Wait the ceiling instead.
        if int(snap.get("long_used") or 0) >= int(snap.get("long_cap") or 1):
            cooldown = _RATE_LIMIT_WAIT_MAX_S
    except Exception:    # noqa: BLE001 - a wait estimate must not kill the worker
        cooldown = 0.0
    return max(_RATE_LIMIT_WAIT_MIN_S, min(_RATE_LIMIT_WAIT_MAX_S, cooldown))


def _run_pass(entries: list, deadline: float,
              retrying: bool = False) -> Optional[list]:
    """Priority-1 over every entry, then priority-2 over every entry.

    Returns the entries Riot rate-limited (retry candidates), or None when
    priority-1 hit the deadline (the worker then exits without completing,
    the pre-existing behaviour). An entry that comes back clean has its
    `riot_status` mark cleared.
    """
    p1_throttled: set = set()
    # Priority-1 - mastery + rank for every entry. Tight loop, no pacing
    # - short bucket (20/s) handles 20 calls in ~1s.
    for entry in entries:
        if time.monotonic() >= deadline:
            log.warning("team-context fan-out priority-1 hit deadline")
            return None
        try:
            cid = _champ_name_to_id(entry.get("locked_champion") or "")
            if _enrich_priority_1(entry, cid):
                p1_throttled.add(id(entry))
        except Exception as exc:    # noqa: BLE001 - must not kill the worker
            log.warning("team-context priority-1 entry failed: %s", exc)

    # Priority-2 - recent matches per player. Cold-cache cost is heavy
    # (each player = 1 list call + <=20 match-detail calls); the long
    # bucket (100/120s) gates this naturally so we don't have to add
    # explicit sleeps.
    throttled: list = []
    for entry in entries:
        if time.monotonic() >= deadline:
            log.warning("team-context fan-out priority-2 hit deadline")
            break
        hit = id(entry) in p1_throttled
        try:
            if _enrich_priority_2(entry):
                hit = True
        except Exception as exc:    # noqa: BLE001
            log.warning("team-context priority-2 entry failed: %s", exc)
        if hit:
            throttled.append(entry)
        else:
            # A clean fetch clears a mark - set by an earlier pass, or
            # carried over by a re-POST, so a first pass can hold one too.
            # `retrying` no longer gates this; _clear_rate_limited writes
            # only when a mark is there, so refreshed_at (the panel's
            # repaint signature) never moves for no change.
            puuid = entry.get("puuid") or ""
            if puuid:
                _clear_rate_limited(_team_of(entry), puuid)
    return throttled


def _clear_rate_limited(team: str, puuid: str) -> None:
    """Clear the entry's riot_status mark, bumping refreshed_at only when
    there was one to clear."""
    global _CACHE_TS
    with _LOCK:
        if _CACHE is None:
            return
        entries = _CACHE.get(team)
        if not isinstance(entries, list):
            return
        for entry in entries:
            if isinstance(entry, dict) and entry.get("puuid") == puuid:
                if entry.get("riot_status"):
                    entry["riot_status"] = ""
                    _CACHE["refreshed_at"] = _now_iso()
                    _CACHE_TS = time.time()
                return


def _default_dispatch_fanout(allies: list, enemies: list, queue_id: int) -> None:
    """Default fan-out dispatcher - spawns a daemon thread iff the
    Riot API is configured. Tests override _FANOUT_DISPATCHER to skip
    real network work."""
    try:
        from core import riot_api
    except ImportError:
        log.debug("team-context fan-out skipped: core.riot_api unavailable")
        return
    if not riot_api.is_configured():
        log.info("team-context fan-out skipped: riot_api not configured")
        return
    global _WORKER, _WORKER_SETTLED
    # If a previous worker is still enriching, leave it: before it marks
    # the roster complete it re-reads the cache and enriches every entry
    # this POST added or re-locked (_settle_or_pending). Re-issuing here
    # would double the API call cost without changing the render. A worker
    # that has already SETTLED enriches nothing more, so it does not count.
    with _LOCK:
        if (_WORKER is not None and _WORKER.is_alive()
                and not _WORKER_SETTLED):
            log.debug("team-context fan-out: prior worker still running, skip")
            return
        t = threading.Thread(
            target=_fanout_worker,
            args=(list(allies), list(enemies), _as_int(queue_id)),
            name="rc-team-context-fanout",
            daemon=True,
        )
        _WORKER = t
        _WORKER_SETTLED = False
    t.start()


# Pluggable dispatcher - tests replace this to assert call shape without
# spawning real network work. The route handler always dispatches via
# this module-level reference.
_FANOUT_DISPATCHER: Callable[[list, list, int], None] = _default_dispatch_fanout


def _serve_refresh_post(h, body) -> None:
    """POST /api/team-context/refresh - receive 10-player roster from
    Legion LCU agent on ChampSelect transition.

    Body shape:
        {
          "queue_id": 420,
          "roster": [
            {"puuid": "...", "summoner_name": "...", "team_id": 100,
             "locked_champion": "Camille"},
            ...
          ]
        }

    Local-only: the Legion LCU agent POSTs to 127.0.0.1. The cross-Claude
    bearer auth was removed when the bridge was decommissioned (2026-06-24).
    """
    if not isinstance(body, dict):
        h._send(400, b'{"error":"body_must_be_object"}', "application/json")
        return

    roster = body.get("roster") or []
    if not isinstance(roster, list):
        h._send(400, b'{"error":"roster_must_be_list"}', "application/json")
        return
    if len(roster) > _MAX_ROSTER:
        h._send(400,
                json.dumps({"error": "roster_too_large",
                            "max": _MAX_ROSTER,
                            "got": len(roster)}).encode(),
                "application/json")
        return

    queue_id = _as_int(body.get("queue_id") or 0)
    blank_names = queue_id in _RANKED_BLANK_QUEUES
    allies: list = []
    enemies: list = []
    for slot in roster:
        if not isinstance(slot, dict):
            continue
        entry = _skeleton_entry(slot, blank_names=blank_names)
        # team_id 100=blue=allies-by-convention. The LCU agent stamps
        # this from `myTeam`/`theirTeam`; treat 100 as allies, 200 as
        # enemies. Anything else falls into allies as a soft default
        # so the dashboard still renders SOMETHING.
        if entry["team_id"] == 200:
            enemies.append(entry)
        else:
            allies.append(entry)

    payload = {
        "allies":       allies,
        "enemies":      enemies,
        "refreshed_at": _now_iso(),
        "partial":      True,    # flipped to False by _mark_complete()
        "queue_id":     queue_id,
    }
    _store(payload)
    log.info("team-context refresh: queue=%d allies=%d enemies=%d",
             queue_id, len(allies), len(enemies))

    # Dispatch the Riot-API fan-out. Default dispatcher spawns a daemon
    # thread iff `core.riot_api.is_configured()`; tests swap in a no-op.
    # Failure here MUST NOT break the route - the skeleton is already
    # stored, the dashboard renders just fine without enrichment.
    # S134 N2: the fan-out is League-V4 + Match-V5 (League-only routes);
    # for TFT queue 1090 both answered 400 on 2026-10-25. Skip it for TFT.
    from core.queue_modes import is_tft_queue
    if is_tft_queue(queue_id):
        log.info("team-context fan-out skipped: TFT queue=%d", queue_id)
    else:
        try:
            _FANOUT_DISPATCHER(allies, enemies, queue_id)
        except Exception as exc:    # noqa: BLE001
            log.warning("team-context fan-out dispatch failed: %s", exc)

    h._send(200, json.dumps({"ok": True,
                             "stored": {"allies": len(allies),
                                        "enemies": len(enemies)}}).encode(),
            "application/json")


def _serve_get(h) -> None:
    """GET /api/team-context - dashboard poll.

    Returns `{"team_context": <obj|null>, "age_s": <float>}`. Age is
    computed from the last successful refresh; null cache -> age=null.
    """
    with _LOCK:
        cache = _snapshot(_CACHE)
        ts = _CACHE_TS
    if cache is None:
        body: dict = {"team_context": None, "age_s": None}
    else:
        body = {"team_context": cache,
                "age_s":         round(max(0.0, time.time() - ts), 1)}
    h._send(200, json.dumps(body).encode(), "application/json")


GET_ROUTES = [
    (equals("/api/team-context"),         _serve_get),
]

POST_ROUTES = [
    (equals("/api/team-context/refresh"), _serve_refresh_post),
]
