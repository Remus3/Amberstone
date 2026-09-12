"""core/smoothed_rates_101qq.py - 101.qq.com duo-synergy consumer.

Item 199 Slice CD (2026-05-25). Wires the operator-captured 101.qq.com
hero-rank-double bot+sup duo win-rate seed into `core.smoothed_rates`
so the dashboard's champ-select view can surface "best bot/sup
pairings" while the operator + ally lock in.

Data sources (operator-captured 2026-05-25, top-200 bot-lane meta tier):

  * `data/external/101qq_hero_rank_double_tier200_capture_20260525.json`
    wrapped envelope `{"code":0,"data":[...200 records...],"message":"success"}`.
    Each record: championid1, championid2, doublewinrate, iwinrate1,
    iwinrate2, itemp1, vitemp1, irank, lane1=bottom, lane2=support.

  * `data/external/101qq_id_map.json` 65-entry numeric-string ->
    DDragon-name mapping. Tencent IDs are 1:1 with Riot DDragon `key`
    field at patch 16.10.1.

Public API:

  top_duos_for_bot(bot_champ, top_n=4) -> list[DuoRec]
      Sorted by doublewinrate DESC (smoothed via Laplace). Picks the
      top N support pairings for a locked bot.

  top_duos_for_sup(sup_champ, top_n=4) -> list[DuoRec]
      Sorted by doublewinrate DESC. Picks the top N bot pairings for
      a locked sup.

  top_solo_picks(role, top_n=4) -> list[SoloRec]
      Top N picks for "bot" or "sup" when nothing is locked. Sorted
      by aggregated rank weight (champion's median irank across all
      pairings, lower = better).

  pair_synergy(bot_champ, sup_champ) -> DuoRec | None
      The specific pair record (None if the pair isn't in the top 200).

  source() -> str
      The seed behind the served snapshot: live | static | none. Provenance
      only - it says nothing about age, by decision. Freshness is health().

  health() -> dict
      Machine-readable freshness: snapshot age, degraded flag, failed-
      refresh count, plus the coverage() block. A persistently failing
      live source KEEPS the previous snapshot, which is correct; this is
      how a consumer learns the panel has been serving it for N hours.

Smoothing notes:
  doublewinrate is already a percentage (e.g. 0.5653 = 56.53%). itemp1
  is a "play rate at tier" percentage (e.g. "4.78%") proxy for sample
  size. We treat sample_size ~= itemp1_float * 1000 (rounded) as a
  rough win-count proxy and apply `smoothed_rates.laplace_rate` so
  thin-sample pairings (irank 195 + itemp1 0.30%) don't outrank well-
  evidenced ones (irank 1 + itemp1 4.78%) when ordering by smoothed
  win-rate. The raw irank is preserved as a ground-truth tie-breaker
  + display field.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core import smoothed_rates as _sr

log = logging.getLogger("rc.web_dashboard")

# --------------------------------------------------------------------
# Paths + cache
# --------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "external"
_RECORDS_PATH = _DATA_DIR / "101qq_hero_rank_double_tier200_capture_20260525.json"
_ID_MAP_PATH = _DATA_DIR / "101qq_id_map.json"

# Lock discipline (lane 8, 2026-08-30). Two locks, one order:
#
#   _CACHE_LOCK    guards ONLY the published snapshot globals below. It is
#                  never held across I/O - the load reads the network and the
#                  disk seed first, then publishes under it in a handful of
#                  assignments. Re-entrant because a public accessor may take
#                  it around a read that itself calls a helper.
#   _REFRESH_LOCK  admits exactly ONE loader at a time (single flight), so a
#                  crowd of callers cannot each fire their own fetch.
#
# _REFRESH_LOCK is always acquired BEFORE _CACHE_LOCK and never the reverse,
# so the pair cannot deadlock; a stale reader only ever tries it non-blocking.
_CACHE_LOCK = threading.RLock()
_REFRESH_LOCK = threading.Lock()
_REFRESH_THREAD: threading.Thread | None = None   # in-flight background refresh
_CACHE_GEN = 0                      # bumped by _reset_cache; stale publishes drop
_LOADED = False
_LOADED_AT: float = 0.0             # monotonic stamp of last (re)load ATTEMPT
_SOURCE: str = "none"               # "live" | "static" | "none" - which seed won
# RM-295a staleness trio. `_LOADED_AT` is the TTL stamp and is deliberately
# bumped even by a refresh that landed NOTHING (so the retry is one TTL out,
# not on every read), which makes it useless as an age. These three describe
# the DATA rather than the retry schedule:
_LAST_GOOD_AT: float = 0.0          # monotonic stamp of the last publish that
#                                     actually swapped records in
_FAILED_REFRESHES: int = 0          # consecutive refreshes that landed nothing
_DEGRADED_SINCE: float | None = None  # monotonic stamp of the first of them
_ID_TO_NAME: dict[int, str] = {}
_NAME_TO_ID: dict[str, int] = {}
_DUO_RECS: list[dict] = []          # raw records (envelope unwrapped)
_PAIR_INDEX: dict[tuple[int, int], dict] = {}    # (bot_id, sup_id) -> rec
_BOTS_BY_SUP: dict[int, list[dict]] = {}         # sup_id -> sorted bot recs
_SUPS_BY_BOT: dict[int, list[dict]] = {}         # bot_id -> sorted sup recs

# Sample-size proxy from itemp1 percentage ("4.78%") -> 1000-scaled.
# A 4.78%-of-tier-200 representation is "well evidenced"; 0.30% is the
# Laplace pull-toward-50% boundary. Tunable - operator-gated.
_ITEMP_TO_SAMPLE_SCALE = 1000.0

# Default Laplace alpha (mirrors core.smoothed_rates default).
_LAPLACE_ALPHA = 1.0

# Prefix `health()["source"]` puts in front of the seed name once the served
# snapshot is frozen. A prefix, not a replacement, so the seed that built the
# frozen data stays recoverable: `src.split(":")[-1]`.
#
# It lives ONLY on the health block. `source()` was deliberately left
# unqualified at merge - see the refusal note in that function.
_STALE_PREFIX = "stale:"

# Live refresh (item 277): pull the duo table from the Tencent getRankDouble
# endpoint via core.synergy_external_source, falling back to the committed
# static seed when the CN endpoint is unreachable. The data is daily-refreshed
# so re-index every few hours. Operator-gated OFF via RC_DUO_SYNERGY_LIVE=0
# (default ON - the operator chose the live dependency, item 277).
_LIVE_TTL_S = 6 * 3600.0
_clock = time.monotonic


def _live_enabled() -> bool:
    return os.environ.get("RC_DUO_SYNERGY_LIVE", "1").strip().lower() not in (
        "0", "false", "no", "off", "",
    )


def _live_data_rows() -> list | None:
    """Live raw bottom/support rows from the Tencent endpoint, or None
    (fail-soft - disabled, unreachable, or empty)."""
    if not _live_enabled():
        return None
    try:
        from core.synergy_external_source import fetch_rows
        rows = fetch_rows("bottom", "support", tier=200)
        return rows or None
    except Exception:  # noqa: BLE001
        return None


def _name_fallback(champ_id: int) -> str:
    """Resolve a champion numeric key the static id_map does not cover
    (live rows may include champs added after the May-25 capture). Fail-soft
    to "" so the row is skipped rather than mis-rendered."""
    try:
        from core.archetype_picks import champion_name_by_key
        return str(champion_name_by_key(champ_id) or "")
    except Exception:  # noqa: BLE001
        return ""


@dataclass(frozen=True)
class DuoRec:
    """One bot+sup pair record from 101.qq.com seed.

    bot / sup are DDragon names (case + punctuation preserved e.g.
    "Kaisa", "TahmKench"). bot_id / sup_id are numeric DDragon keys.
    doublewinrate / iwinrate_bot / iwinrate_sup are raw rates [0..1].
    itemp_bot is the play-rate float (e.g. 0.0478 = 4.78% of tier).
    irank is the source pair rank [1..200] (lower = better).
    smoothed_rate is the Laplace-smoothed doublewinrate; sample-size
    weighted so thin pairings get pulled toward 0.5.
    """
    bot: str
    sup: str
    bot_id: int
    sup_id: int
    doublewinrate: float
    iwinrate_bot: float
    iwinrate_sup: float
    itemp_bot: float
    irank: int
    smoothed_rate: float


@dataclass(frozen=True)
class SoloRec:
    """One single-role top pick when nothing locked. role is bot|sup.

    rank is the median irank across all pairings this champion appears
    in for the role; lower = better. iwinrate is the per-role solo
    win-rate aggregated (mean across appearances). itemp is the mean
    itemp_bot across appearances (proxy for play-rate share).
    """
    champ: str
    champ_id: int
    role: str
    rank: float
    iwinrate: float
    itemp: float
    smoothed_rate: float


# --------------------------------------------------------------------
# Loader (lazy, thread-safe, idempotent)
# --------------------------------------------------------------------


def _as_int(value) -> int | None:
    """Tolerant int coercion for a field on a payload RC does not own.

    RM-291 Sweep B. This is a THIRD-PARTY feed and it demonstrably
    string-encodes numbers: every `championid1` in the captured seed is a
    STRING ("22"), and `itemp1` is a percent-suffixed string ("4.78%").
    A bare `int()` was therefore one upstream formatting choice ("22.0")
    away from raising ValueError - the LEDGER 1299 W1 class - which the
    enclosing handler turned into a silently DROPPED ROW.

    Returns None when the value carries no usable integer, so the CALLER
    decides whether that is row-fatal. Non-finite is None on purpose:
    `int(inf)` raises OverflowError, which is not a ValueError and so is a
    third handler class the original guard never covered.

    DUPLICATED, not imported, from the `_as_int`/`_as_float` pair in
    `core/augment_external_source.py`: those are private to a module that
    owns a different feed and its own network I/O, and they default on
    failure where this call site needs None-on-failure so it can tell an
    absent secondary field from an unusable primary one.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            f = float(value.strip())
        except (TypeError, ValueError):
            return None
        return int(f) if math.isfinite(f) else None
    return None


def _as_rate(value) -> float | None:
    """Tolerant win-rate coercion, percent-aware. Twin of `_as_int`.

    `itemp1` already arrives as "4.78%", so a sibling rate field could
    arrive that way too. A trailing '%' divides by 100; a bare numeric
    string is already a decimal share (0.5653 = 56.53%) and is taken
    as-is. Returns None when the value carries no usable rate.

    Non-finite is None deliberately: a NaN reaching the dashboard JSON
    blanks the whole panel, and `float("nan")` passes an `isinstance`
    check that a plain float() guard would wave through.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (OverflowError, ValueError):
            return None
        return f if math.isfinite(f) else None
    if isinstance(value, str):
        s = value.strip()
        pct = s.endswith("%")
        if pct:
            s = s[:-1].strip()
        try:
            f = float(s)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(f):
            return None
        return f / 100.0 if pct else f
    return None


def _parse_itemp(raw: str | float | None) -> float:
    """Parse "4.78%" -> 0.0478 (decimal share). Returns 0.0 on garbage."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().rstrip("%")
    try:
        return float(s) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _rows_to_records(data, id_to_name: dict[int, str]) -> list[dict]:
    """Normalize raw Tencent-schema rows (live OR static) into records.

    Shared by both seeds - they carry the same row schema. Rows that cannot
    be coerced, or whose champion ids resolve to no name, are skipped, so an
    empty return means "these rows yielded nothing usable" and is what makes
    the static fallback fire. Does no I/O and raises nothing.
    """
    records: list[dict] = []
    if not isinstance(data, list):
        return records
    for rec in data:
        if not isinstance(rec, dict):
            continue
        # RM-291 Sweep B: tolerant coercion, because this feed sends ids as
        # STRINGS ("22") and could send "22.0". `_as_int` returns None on
        # anything unusable, which the existing id guard already treats as
        # row-fatal - an unresolvable champion is not a pairing.
        bot_id = _as_int(rec.get("championid1"))
        sup_id = _as_int(rec.get("championid2"))
        if not (bot_id and sup_id):
            continue
        bot_name = id_to_name.get(bot_id) or _name_fallback(bot_id)
        sup_name = id_to_name.get(sup_id) or _name_fallback(sup_id)
        if not (bot_name and sup_name):
            continue
        # doublewinrate is the payload this row exists to carry. If it will
        # not coerce the row is DROPPED rather than invented as 0.0, which
        # would rank a real pairing dead last in the "best pairings" list.
        # Same doctrine as core/augment_external_source.py, where win_rate is
        # likewise the one field whose absence still drops the row.
        doublewr = _as_rate(rec.get("doublewinrate"))
        if doublewr is None:
            continue
        # Secondary display / aggregation fields keep the original `or`
        # tolerance: an absent value here is a legitimate 0, not a parse
        # failure, so only a present-but-unusable value drops the row.
        iwr1 = _as_rate(rec.get("iwinrate1") or 0.0)
        iwr2 = _as_rate(rec.get("iwinrate2") or 0.0)
        irank = _as_int(rec.get("irank") or 0)
        if iwr1 is None or iwr2 is None or irank is None:
            continue
        itemp = _parse_itemp(rec.get("itemp1"))
        # Sample-size proxy: itemp1 is play-rate share; scale to
        # wins-count proxy and Laplace-smooth. doublewr * proxy
        # = wins, proxy = games, alpha = 1.0.
        sample = max(0.0, itemp * _ITEMP_TO_SAMPLE_SCALE)
        wins = doublewr * sample
        smoothed = _sr.laplace_rate(wins, sample, _LAPLACE_ALPHA)
        records.append({
            "bot": bot_name,
            "sup": sup_name,
            "bot_id": bot_id,
            "sup_id": sup_id,
            "doublewinrate": doublewr,
            "iwinrate_bot": iwr1,
            "iwinrate_sup": iwr2,
            "itemp_bot": itemp,
            "irank": irank,
            "smoothed_rate": smoothed,
        })
    return records


def _build_snapshot() -> dict:
    """Read + index both seeds and return a self-contained snapshot.

    ALL of the blocking work lives here - the live Tencent fetch (up to 3
    sequential GETs at a 6s socket timeout each) and the static-seed disk
    read - and NONE of it runs under a lock. The caller publishes the result
    with `_publish()`, which is pure assignment. Writes no globals.

    Silent on missing files (yields an empty snapshot); the API layer
    surfaces that as "no data" rather than 500.
    """
    # ID map: numeric-string keys -> DDragon names
    id_to_name: dict[int, str] = {}
    name_to_id: dict[str, int] = {}
    try:
        raw_map = json.loads(_ID_MAP_PATH.read_text(encoding="utf-8"))
        for k, v in raw_map.items():
            try:
                cid = int(k)
            except (TypeError, ValueError):
                continue
            if not isinstance(v, str) or not v:
                continue
            id_to_name[cid] = v
            name_to_id[v.lower()] = cid
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass

    # Records source (item 277): live Tencent rows first, static seed
    # fallback. Both are the same row schema; the indexer is shared.
    #
    # Lane 8 (2026-08-31): the fallback used to trigger on "the live source
    # returned NO rows". That is the wrong predicate - a live response can be
    # non-empty and still yield ZERO usable records (ids in neither the id_map
    # nor DDragon, so every row is skipped below). The seed was then never
    # consulted and an empty snapshot shipped labelled source="live". The
    # predicate is now "the live source yielded no usable RECORDS", which is
    # what the fallback was always for.
    _src = "none"
    try:
        live_rows = _live_data_rows()
    except Exception:  # noqa: BLE001 - the live seam is a monkey-patchable
        # third-party boundary; a raising live source must degrade to the
        # static seed (that is what the fallback exists for), never propagate.
        live_rows = None
    records: list[dict] = []
    if live_rows:
        records = _rows_to_records(live_rows, id_to_name)
        if records:
            _src = "live"
    if not records:
        try:
            raw_env = json.loads(_RECORDS_PATH.read_text(encoding="utf-8"))
            d = raw_env.get("data") if isinstance(raw_env, dict) else None
            static_rows = d if isinstance(d, list) else []
        # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            static_rows = []
        records = _rows_to_records(static_rows, id_to_name)
        if records:
            _src = "static"

    # Build per-side indices, sorted by smoothed_rate DESC for the
    # "given a locked partner, who pairs best with them" queries.
    pair_index: dict[tuple[int, int], dict] = {}
    bots_by_sup: dict[int, list[dict]] = {}
    sups_by_bot: dict[int, list[dict]] = {}
    for r in records:
        pair_index[(r["bot_id"], r["sup_id"])] = r
        bots_by_sup.setdefault(r["sup_id"], []).append(r)
        sups_by_bot.setdefault(r["bot_id"], []).append(r)
    # Sort each list by smoothed_rate DESC then irank ASC (tiebreaker).
    for v in bots_by_sup.values():
        v.sort(key=lambda x: (-x["smoothed_rate"], x["irank"]))
    for v in sups_by_bot.values():
        v.sort(key=lambda x: (-x["smoothed_rate"], x["irank"]))

    return {
        "id_to_name": id_to_name,
        "name_to_id": name_to_id,
        "records": records,
        "pair_index": pair_index,
        "bots_by_sup": bots_by_sup,
        "sups_by_bot": sups_by_bot,
        "source": _src,
    }


def _mark_frozen_locked(reason: str) -> None:
    """Record that a refresh did NOT land new data. Call with _CACHE_LOCK held.

    RM-295a. Every path that leaves the previous snapshot in place is CORRECT
    - serving hours-old pairings beats blanking the panel - but each of them
    used to be invisible past a single log line, so `source()` kept naming
    the seed that built the snapshot and nothing could say "this has been
    frozen for N hours". This is the one place that fact is written down.

    Only meaningful while something is being served: before the first
    successful publish there is no snapshot to freeze, so a cold-start
    failure is not degradation, it is absence (`loaded` covers that).
    """
    global _FAILED_REFRESHES, _DEGRADED_SINCE
    if not _LOADED:
        return
    _FAILED_REFRESHES += 1
    if _DEGRADED_SINCE is None:
        _DEGRADED_SINCE = _clock()
    log.warning(
        "duo-synergy: refresh did not land (%s); serving a %d-record %s "
        "snapshot frozen for %.2f h (%d consecutive failed refreshes)",
        reason, len(_DUO_RECS), _SOURCE,
        max(0.0, _clock() - _LAST_GOOD_AT) / 3600.0, _FAILED_REFRESHES)


def _mark_frozen(reason: str) -> None:
    """Lock-taking wrapper for callers that do not already hold the lock."""
    with _CACHE_LOCK:
        _mark_frozen_locked(reason)


def _publish(snapshot: dict, gen: int) -> None:
    """Swap a freshly built snapshot in. Assignment only - no I/O, so the
    cache lock is held for microseconds.

    Drops the publish when `gen` no longer matches `_CACHE_GEN`: a
    `_reset_cache()` landed while this load was out on the network, and
    republishing pre-reset data would resurrect it.

    Also drops an EMPTY rebuild over a non-empty snapshot. `_refresh` states
    that "a failed refresh must leave the previous snapshot in place", but
    pre-2026-08-31 that only held when `_build_snapshot` RAISED - and the
    builder is written never to raise, swallowing OSError/JSONDecodeError and
    returning an empty snapshot instead. So the designed failure path was the
    one that wiped a good cache, blanking /api/duo-synergy for a full TTL.
    The TTL stamp is still refreshed so the retry lands one TTL later rather
    than on every single read.
    """
    global _LOADED, _LOADED_AT, _SOURCE, _ID_TO_NAME, _NAME_TO_ID, _DUO_RECS
    global _PAIR_INDEX, _BOTS_BY_SUP, _SUPS_BY_BOT
    global _LAST_GOOD_AT, _FAILED_REFRESHES, _DEGRADED_SINCE
    with _CACHE_LOCK:
        if gen != _CACHE_GEN:
            return
        if not snapshot["records"] and _DUO_RECS:
            _mark_frozen_locked("rebuild yielded 0 records")
            _LOADED_AT = _clock()
            return
        _ID_TO_NAME = snapshot["id_to_name"]
        _NAME_TO_ID = snapshot["name_to_id"]
        _DUO_RECS = snapshot["records"]
        _PAIR_INDEX = snapshot["pair_index"]
        _BOTS_BY_SUP = snapshot["bots_by_sup"]
        _SUPS_BY_BOT = snapshot["sups_by_bot"]
        _LOADED = True
        _LOADED_AT = _clock()
        _SOURCE = snapshot["source"]
        # Real data landed: this is the only place the age clock restarts
        # and the only place degradation clears.
        _LAST_GOOD_AT = _LOADED_AT
        _FAILED_REFRESHES = 0
        _DEGRADED_SINCE = None


def _refresh(gen: int) -> None:
    """Build outside every lock, then publish. Fail-soft end to end."""
    try:
        snapshot = _build_snapshot()
    except Exception as exc:  # noqa: BLE001 - belt and braces: this runs on a
        # background thread whose exception nothing would ever see, and a
        # failed refresh must leave the previous snapshot in place.
        #
        # RM-295a sibling of the _publish keep-branch: this path froze the
        # snapshot with NO log at all, which is the same silence one level
        # louder. It is marked so the frozen age is still accountable.
        _mark_frozen(f"builder raised: {exc.__class__.__name__}")
        return
    _publish(snapshot, gen)


def _start_background_refresh(gen: int) -> None:
    """Refresh an expired snapshot off the caller's thread (single flight).

    Only reached when a previous snapshot exists, so readers keep being
    served stale data while this runs. If a refresh is already in flight the
    non-blocking acquire fails and the caller simply keeps the stale data -
    no caller ever waits on the network here.
    """
    global _REFRESH_THREAD
    if not _REFRESH_LOCK.acquire(blocking=False):
        return

    def _run() -> None:
        try:
            _refresh(gen)
        finally:
            _REFRESH_LOCK.release()

    # The lock is released by _run, so it is only ever safe to hand it over
    # once the thread is genuinely running. A refused thread (the OS is out
    # of them - RuntimeError) previously leaked it permanently: every later
    # refresh silently no-opped on the failed non-blocking acquire, and any
    # cold start blocked on it forever. Release here and stay fail-soft; a
    # thread-starved box must not turn a cached read into a 500.
    try:
        t = threading.Thread(
            target=_run, name="rc-duo-synergy-refresh", daemon=True)
        t.start()
    except RuntimeError:
        _REFRESH_LOCK.release()
        # RM-295a: third freeze path. It already logged, but the log was the
        # ONLY trace - mark it so the age is machine-readable like the rest.
        _mark_frozen("refresh thread could not be started")
        return
    _REFRESH_THREAD = t


def _load_once() -> None:
    """Ensure a usable snapshot is published. Thread-safe, idempotent.

    Three paths:
      * fresh cache            -> one lock acquire, no work;
      * expired cache          -> hand back the STALE snapshot immediately
                                  and refresh in the background;
      * cold start (no data)   -> block until the first load completes.

    The cold-start block is deliberate and is the only blocking path: there
    is no snapshot to serve, so there is nothing to hand back. Every other
    cold-start caller waits on _REFRESH_LOCK (never on _CACHE_LOCK) and
    re-checks, so exactly one load runs however many callers arrive.
    """
    with _CACHE_LOCK:
        gen = _CACHE_GEN
        if _LOADED and (_clock() - _LOADED_AT) < _LIVE_TTL_S:
            return
        have_stale = _LOADED
    if have_stale:
        _start_background_refresh(gen)
        return
    with _REFRESH_LOCK:
        with _CACHE_LOCK:
            if _LOADED:
                return          # another cold-start caller just landed one
            gen = _CACHE_GEN
        _refresh(gen)


def source() -> str:
    """Which seed the live cache is currently serving: live | static | none.

    This answers PROVENANCE only, and deliberately says nothing about age.

    RM-295a built a `"stale:"`-prefixed fourth/fifth return value here, so a
    frozen snapshot reported `"stale:live"`. It was measured working and then
    REFUSED at merge on 2026-09-12. Do not re-pitch it. Three reasons, the
    first two of which outlive the argument that killed the row's own stated
    justification:

      * shipping it required WIDENING `test_source_stays_in_the_declared_domain`
        (tests/test_smoothed_rates_101qq_lock.py:375), a guard pinning this
        domain to exactly ("live", "static", "none"), so that the change
        could pass. Editing a guard to admit your own change is the
        anti-pattern, not a migration;
      * provenance and freshness are different questions and want different
        fields. `health()` answers freshness - `degraded`, `age_s`,
        `stale_for_s`, `last_refresh_ok`, `failed_refreshes`;
      * the fence in BACKLOG.md:126 gave a reason that is FALSE at HEAD (it
        claimed the duo-synergy route and a UI badge read these values; the
        route has zero `source()` calls and no such badge exists). That kills
        the reason, not the fence - and the fence was only ever crossed
        because a slice prompt said to, which is not re-litigation on merit.

    So: freshness callers read `health()`. This returns the bare seed forever.
    """
    _load_once()
    with _CACHE_LOCK:
        return _SOURCE


def _reset_cache() -> None:
    """Test-only: clear cache so the next call re-reads from disk.

    Bumps the generation so a refresh still out on the network cannot
    republish the data this call just dropped.
    """
    global _LOADED, _LOADED_AT, _SOURCE, _ID_TO_NAME, _NAME_TO_ID, _DUO_RECS
    global _PAIR_INDEX, _BOTS_BY_SUP, _SUPS_BY_BOT, _CACHE_GEN
    global _LAST_GOOD_AT, _FAILED_REFRESHES, _DEGRADED_SINCE
    with _CACHE_LOCK:
        _CACHE_GEN += 1
        _LOADED = False
        _LOADED_AT = 0.0
        _LAST_GOOD_AT = 0.0
        _FAILED_REFRESHES = 0
        _DEGRADED_SINCE = None
        _SOURCE = "none"
        _ID_TO_NAME = {}
        _NAME_TO_ID = {}
        _DUO_RECS = []
        _PAIR_INDEX = {}
        _BOTS_BY_SUP = {}
        _SUPS_BY_BOT = {}


def _resolve_id(champ: str) -> int:
    """Champion name -> DDragon numeric id, case-insensitive. 0 if not in
    the 101.qq seed coverage (65 unique IDs)."""
    if not champ:
        return 0
    _load_once()
    with _CACHE_LOCK:
        return _NAME_TO_ID.get(str(champ).strip().lower(), 0)


def _rec_to_duo(rec: dict) -> DuoRec:
    """Internal raw dict -> typed DuoRec."""
    return DuoRec(
        bot=rec["bot"],
        sup=rec["sup"],
        bot_id=rec["bot_id"],
        sup_id=rec["sup_id"],
        doublewinrate=rec["doublewinrate"],
        iwinrate_bot=rec["iwinrate_bot"],
        iwinrate_sup=rec["iwinrate_sup"],
        itemp_bot=rec["itemp_bot"],
        irank=rec["irank"],
        smoothed_rate=rec["smoothed_rate"],
    )


# --------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------


def top_duos_for_bot(bot_champ: str, top_n: int = 4) -> list[DuoRec]:
    """Top N support pairings for a locked bot, sorted by smoothed_rate
    DESC then irank ASC. Empty list if champ isn't in coverage or has
    no pairings."""
    _load_once()
    bot_id = _resolve_id(bot_champ)
    if not bot_id:
        return []
    # A background refresh may republish between the resolve and the read;
    # take the index under the cache lock so one call sees one snapshot.
    with _CACHE_LOCK:
        recs = list(_SUPS_BY_BOT.get(bot_id) or ())
    n = max(0, min(int(top_n), len(recs)))
    return [_rec_to_duo(r) for r in recs[:n]]


def top_duos_for_sup(sup_champ: str, top_n: int = 4) -> list[DuoRec]:
    """Top N bot pairings for a locked sup, sorted by smoothed_rate DESC
    then irank ASC."""
    _load_once()
    sup_id = _resolve_id(sup_champ)
    if not sup_id:
        return []
    with _CACHE_LOCK:
        recs = list(_BOTS_BY_SUP.get(sup_id) or ())
    n = max(0, min(int(top_n), len(recs)))
    return [_rec_to_duo(r) for r in recs[:n]]


def pair_synergy(bot_champ: str, sup_champ: str) -> DuoRec | None:
    """Return the specific pair record or None if not in coverage."""
    _load_once()
    bot_id = _resolve_id(bot_champ)
    sup_id = _resolve_id(sup_champ)
    if not (bot_id and sup_id):
        return None
    with _CACHE_LOCK:
        rec = _PAIR_INDEX.get((bot_id, sup_id))
    return _rec_to_duo(rec) if rec else None


def top_solo_picks(role: Literal["bot", "sup"], top_n: int = 4) -> list[SoloRec]:
    """Top N picks for a role when nothing is locked.

    Aggregates each champion's median irank across all pairings (lower
    = better), mean iwinrate, mean itemp_bot, and Laplace-smoothed
    doublewinrate (mean across pairings, weighted by itemp_bot sample
    proxy). Returns sorted by smoothed_rate DESC then median rank ASC.
    """
    _load_once()
    r = role.lower() if role else ""
    if r not in ("bot", "sup"):
        return []
    # One coherent snapshot per call: grab the references under the cache
    # lock (published structures are swapped, never mutated in place, so the
    # aggregation below is safe to run outside it).
    with _CACHE_LOCK:
        duo_recs = _DUO_RECS
        id_to_name = _ID_TO_NAME
    # Group records by champion id (depending on role side).
    buckets: dict[int, list[dict]] = {}
    for rec in duo_recs:
        cid = rec["bot_id"] if r == "bot" else rec["sup_id"]
        buckets.setdefault(cid, []).append(rec)
    aggregates: list[SoloRec] = []
    for cid, recs in buckets.items():
        if not recs:
            continue
        name = id_to_name.get(cid, "")
        if not name:
            continue
        ranks = sorted(x["irank"] for x in recs)
        median_rank = float(ranks[len(ranks) // 2])
        # Per-role solo iwinrate is constant for a given champ across
        # the seed (it's the champion's own ranked WR), so mean = the
        # value any record carries. Defensive mean handles edge cases.
        side_key = "iwinrate_bot" if r == "bot" else "iwinrate_sup"
        iwinrates = [x[side_key] for x in recs]
        mean_iwr = sum(iwinrates) / len(iwinrates) if iwinrates else 0.0
        itemps = [x["itemp_bot"] for x in recs]
        mean_itemp = sum(itemps) / len(itemps) if itemps else 0.0
        # Sample-weighted mean of smoothed doublewinrate: heavier
        # pairings dominate the aggregate so a one-irank=1 entry
        # doesn't outrank a champion with consistent strong pairings.
        total_w = sum(max(0.0001, x["itemp_bot"]) for x in recs)
        weighted_sr = sum(
            x["smoothed_rate"] * max(0.0001, x["itemp_bot"]) for x in recs
        ) / total_w if total_w > 0 else 0.0
        aggregates.append(SoloRec(
            champ=name,
            champ_id=cid,
            role=r,
            rank=median_rank,
            iwinrate=mean_iwr,
            itemp=mean_itemp,
            smoothed_rate=weighted_sr,
        ))
    aggregates.sort(key=lambda x: (-x.smoothed_rate, x.rank))
    n = max(0, min(int(top_n), len(aggregates)))
    return aggregates[:n]


def coverage() -> dict:
    """Diagnostic: how many unique champs + records are loaded.

    RM-295b verdict ADOPT, not delete (2026-09-12). Re-measured: this has no
    production consumer at all - `dashboard/routes_duo_synergy.py` reaches
    only `_resolve_id` / `pair_synergy` / `top_duos_for_bot` /
    `top_duos_for_sup` / `top_solo_picks`, `dashboard/routes_draft_score.py`
    imports only `pair_synergy`, the module declares no `__all__` and nothing
    reflects over it, so only tests ever called this. Kept rather than deleted
    because it returns exactly the four numbers a duo-synergy diagnostic
    wants: `health()` now carries it, so the one route wiring that lands
    `health()` adopts this with it. It is STILL unreached until that wiring
    lands, and saying otherwise would be the claim this row exists to kill.
    """
    _load_once()
    with _CACHE_LOCK:
        return {
            "unique_champions": len(_ID_TO_NAME),
            "total_records":    len(_DUO_RECS),
            "unique_bot_ids":   len(_SUPS_BY_BOT),
            "unique_sup_ids":   len(_BOTS_BY_SUP),
        }


def health() -> dict:
    """Machine-readable freshness of the served snapshot (RM-295a).

    The keep-the-previous-snapshot degrade is correct but was silent: a
    frozen cache and a fresh one looked identical from outside. This is the
    signal that tells them apart, and it is JSON-safe so a route can embed
    it verbatim.

        source           qualified seed - "live", or "stale:live" once the
                         snapshot is frozen. This DIFFERS from `source()`
                         on purpose: that function answers provenance and
                         stays bare, this one is the freshness surface
        seed             the UNqualified seed that built the served data
        loaded           False before the first successful publish
        degraded         True once a refresh has failed to land new data
        age_s            seconds since the data itself last changed. NOT
                         `_LOADED_AT`, which a failed refresh also bumps
        age_hours        the same figure in the units the alert is phrased in
        degraded_for_s   seconds since the FIRST failed refresh (0 when fresh)
        failed_refreshes consecutive refreshes that landed nothing
        last_refresh_ok  RM-295a's name for `not degraded`
        stale_for_s      RM-295a's name for `age_s`
        coverage         the `coverage()` block, unchanged

    The RM-295a row specifies `stale_for_s` as "now minus `_LOADED_AT`". That
    parenthetical is WRONG and following it would have shipped a signal that
    reads 0 during the exact outage it exists to report: the keep-branch bumps
    `_LOADED_AT` on every failed refresh precisely so the retry is one TTL out.
    The figure is measured from `_LAST_GOOD_AT` instead - the last time the
    data actually changed - which is the quantity the row's own prose asks for
    ("a snapshot that stopped advancing days ago").

    `coverage()` is called BEFORE `_CACHE_LOCK` is taken on purpose: it calls
    `_load_once()`, whose cold-start path takes `_REFRESH_LOCK`, and this
    module's lock order is _REFRESH_LOCK before _CACHE_LOCK, never the
    reverse. The two reads can therefore straddle a refresh - acceptable
    because both halves are diagnostics and no invariant binds them, and a
    deadlock to keep them coherent would be a far worse trade.
    """
    cov = coverage()
    with _CACHE_LOCK:
        seed = _SOURCE
        loaded = _LOADED
        failed = _FAILED_REFRESHES
        degraded = bool(loaded and failed)
        age = max(0.0, _clock() - _LAST_GOOD_AT) if loaded else 0.0
        degraded_for = (
            max(0.0, _clock() - _DEGRADED_SINCE)
            if degraded and _DEGRADED_SINCE is not None else 0.0)
    return {
        "source":           (_STALE_PREFIX + seed) if degraded else seed,
        "seed":             seed,
        "loaded":           loaded,
        "degraded":         degraded,
        "age_s":            round(age, 3),
        "age_hours":        round(age / 3600.0, 3),
        "degraded_for_s":   round(degraded_for, 3),
        "failed_refreshes": failed,
        "last_refresh_ok":  not degraded,
        "stale_for_s":      round(age, 3),
        "coverage":         cov,
    }
