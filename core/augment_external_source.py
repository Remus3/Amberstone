"""
core/augment_external_source.py - external Mayhem/Arena augment win-rate prior.

Cold-start substrate for the augment recommender (CLAUDE.md #88, plan
`Desktop/MAYHEM_AUGMENT_RECOMMENDER_PLAN_2026-05-17.md` S4, Option B).

RC's own ingested augment history is extremely sparse (Task-1 audit
2026-05-17: 13 Mayhem matches, ~48 tracked-player augment-instances over a
~199-augment pool -> per-augment n_own ~ 0-2). The recommender therefore
bootstraps from an external per-augment marginal win-rate prior and blends
toward own-history as ingest grows (`w = n_own/(n_own+K)`).

Source (validated + LOCKED 2026-05-17 - do not re-research): Overlay App E's
unauthenticated data backend. Plain GET, no params, public cert, BunnyCDN
~1h. The `overlay app E` HTML is bot-protected; this data host is not.

  GET https://data.v2.iesdev.com/api/v1/query_objects/prod/lol/aram_mayhem_augments
  GET https://data.v2.iesdev.com/api/v1/query_objects/prod/lol/arena_augments

Response: ``{"data": [ {augment_id, patch, dt, stats:{win_rate, num_games,
num_win_games, pick_rate, tier, augment_stage_stats:[per-round], ...}}, ...],
"meta": {count, generated_at, ...}}``. `augment_id` is a numeric **string**
that maps 1:1 to Riot augment ids (== `playerAugment{i}` ints in
`lcu_match_detail`, == `cherry-augments.json` `id`).

Caching contract (S4): patch-pinned snapshot alongside `arena_augments.json`
at ``data/daemon_slayer/<rc_patch>/<mode>_augment_stats.json``. Refresh
trigger = patch flip (a new patch dir simply has no file -> fetch). Network
failure degrades to the last cached snapshot; nothing cached -> an empty
table (the recommender then falls back to the LLM prompt path). This module
never raises into its callers except via the explicit `refresh_cache`
``force`` path.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.polled_json import atomic_write_json, read_json_dict

_log = logging.getLogger("rc.augment_external_source")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DS_DATA_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"
_PATCH_FILE = _DS_DATA_DIR / "current.txt"

_BASE = "https://data.v2.iesdev.com/api/v1/query_objects/prod/lol"
MAYHEM_ENDPOINT = f"{_BASE}/aram_mayhem_augments"
ARENA_ENDPOINT = f"{_BASE}/arena_augments"

_ENDPOINTS = {"mayhem": MAYHEM_ENDPOINT, "arena": ARENA_ENDPOINT}

_SCHEMA = 1
_HTTP_TIMEOUT_S = 15.0
_USER_AGENT = "rc-augment-source/1"
# Cap on a response body from a host RC does not own. The two real payloads
# are well under 2 MB (cherry-augments.json is 568 entries, the Overlay App E table
# ~199 augments), so 32 MB is generous headroom that still bounds memory.
_MAX_BODY_BYTES = 32 * 1024 * 1024

# Process cache: (mode -> AugmentPriorTable), mtime-gated like
# daemon_slayer_resolver so a patch flip / external refresh is picked up
# without a restart.
_lock = threading.Lock()
_cache: dict[str, "AugmentPriorTable"] = {}
_cache_mtime: dict[str, float] = {}


class AugmentSourceError(RuntimeError):
    """Raised only by ``refresh_cache(..., force=True)`` so an explicit
    operator/tool refresh surfaces failures. The normal ``get_priors`` path
    swallows errors and degrades to cache/empty."""


@dataclass(frozen=True)
class AugmentPriorTable:
    """Immutable per-augment external prior. Lookups accept int or str
    augment ids (callers hold ints from ``playerAugment{i}``)."""

    mode: str
    rc_patch: str = ""
    source_patch: str = ""
    source_generated_at: str = ""
    fetched_at: str = ""
    # augment-id (str) -> {win_rate, num_games, num_win_games, pick_rate,
    #                      tier, stage_win_rate:{stage(str): wr}}
    augments: dict[str, dict] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return bool(self.augments)

    @property
    def count(self) -> int:
        return len(self.augments)

    def _row(self, augment_id) -> Optional[dict]:
        if augment_id is None:
            return None
        return self.augments.get(str(augment_id))

    def win_rate(self, augment_id: int | str | None) -> Optional[float]:
        """External marginal win-rate for an augment, or None if unknown."""
        row = self._row(augment_id)
        if not row:
            return None
        return _finite(row.get("win_rate"))

    def num_games(self, augment_id: int | str | None) -> int:
        row = self._row(augment_id)
        if not row:
            return 0
        n = row.get("num_games")
        return int(n) if isinstance(n, (int, float)) else 0

    def stage_win_rate(self, augment_id: int | str | None, stage: int | str) -> Optional[float]:
        """Per-Mayhem-round (1-5) win-rate, for optional round-aware
        sharpening. None if absent."""
        row = self._row(augment_id)
        if not row:
            return None
        return _finite((row.get("stage_win_rate") or {}).get(str(stage)))


def _current_patch() -> str:
    try:
        return _PATCH_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        # LANE 8 CYCLE 33: UnicodeDecodeError is a ValueError, NOT an OSError,
        # so a non-UTF-8 current.txt used to escape this function and every
        # "never raises" accessor below it. Same class core/polled_json.py
        # fixed in cycle 24; fixed at the root here rather than by widening a
        # caller's handler, which is what that module's comment warns about.
        return ""


def _reject_non_finite(token: str):
    """json.loads parse_constant hook - see the call site in _http_get."""
    raise AugmentSourceError(f"non-finite JSON literal {token!r} in payload")


def _finite(value) -> Optional[float]:
    """Coerce to a finite float, or None. The last line that can keep a
    NaN/Infinity out of the scorer when it came from a snapshot written
    before the parse_constant guard above existed - read_json_dict goes
    through a plain json.loads, which ACCEPTS those literals."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _as_int(value, default: int = 0) -> int:
    """Tolerant numeric coercion for a field on a payload RC does not own.

    LANE 8 CYCLE 33: this feed demonstrably string-encodes numbers -
    `augment_id` arrives as a numeric STRING - so bare int() on a sibling
    field was a live ValueError waiting on an upstream formatting choice
    ("1500.0" and "n/a" both proven). A wrong-typed COUNT must not cost the
    win rate that row exists to carry, so it degrades to `default`; the one
    field whose absence still drops the row is win_rate itself, asserted in
    tests/test_augment_external_source_hardening.py.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (TypeError, ValueError):
            return default
    return default


def _as_float(value, default: float = 0.0) -> float:
    """Tolerant float twin of `_as_int`. Same rationale."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return default
    return default


def _cache_path(mode: str, patch: str) -> Path:
    return _DS_DATA_DIR / patch / f"{mode}_augment_stats.json"


def _http_get(url: str, timeout_s: float):
    """One-shot HTTPS GET -> parsed JSON (dict or list). Encapsulated so
    tests can monkey-patch this rather than urllib internals (riot_api
    pattern). Raises AugmentSourceError on any failure."""
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            if r.status != 200:
                raise AugmentSourceError(f"{url} -> HTTP {r.status}")
            # LANE 8 CYCLE 33: bounded. This is a third-party host RC does
            # not control, and a bare r.read() would buffer whatever it
            # chose to send into a coach-path process that runs for days.
            # Read one byte past the cap so an over-cap body is detectable
            # rather than silently truncated into a JSON parse error.
            body = r.read(_MAX_BODY_BYTES + 1)
            if len(body) > _MAX_BODY_BYTES:
                raise AugmentSourceError(
                    f"{url} body too large (over {_MAX_BODY_BYTES} bytes)"
                )
    except AugmentSourceError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise AugmentSourceError(f"{url} fetch failed: {exc}") from exc
    try:
        # LANE 8 CYCLE 33: parse_constant fires on exactly the three
        # NON-STANDARD literals json.loads accepts by default - NaN,
        # Infinity, -Infinity. They must die at the door, because
        # isinstance(float("nan"), float) is True so a non-finite survives
        # every type check below, every comparison against it is False so
        # the recommender's ranking degrades SILENTLY rather than failing,
        # and json.dumps re-emits it as a bare NaN token (allow_nan
        # defaults True) which makes the written cache file invalid JSON.
        # core/synergy_external_source.py:135-147 is the twin that already
        # guards this; found by grepping this root cause, not by reading.
        return json.loads(body, parse_constant=_reject_non_finite)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AugmentSourceError(f"{url} bad JSON: {exc}") from exc


def _http_get_json(url: str, timeout_s: float) -> dict:
    """GET expecting a JSON object (win-rate API path)."""
    data = _http_get(url, timeout_s)
    if not isinstance(data, dict):
        raise AugmentSourceError(f"{url} top-level is {type(data).__name__}, want dict")
    return data


def _normalize(mode: str, rc_patch: str, raw: dict) -> dict:
    """External payload -> on-disk snapshot schema. Tolerant of missing
    sub-fields; an augment row with no usable win_rate is dropped (so the
    recommender's "unknown -> no external prior" path is exercised)."""
    rows = raw.get("data")
    if not isinstance(rows, list):
        raise AugmentSourceError("payload.data is not a list")
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    augments: dict[str, dict] = {}
    source_patch = ""
    for r in rows:
        if not isinstance(r, dict):
            continue
        aid = r.get("augment_id")
        if aid is None:
            continue
        aid = str(aid).strip()
        if not aid:
            continue
        st = r.get("stats") if isinstance(r.get("stats"), dict) else {}
        # win_rate is the ONE field whose absence drops the row: a count that
        # will not coerce degrades to 0 (see _as_int), but a missing or
        # non-finite win rate must not become a silent 0.0 that scores as a
        # 0-percent augment. _finite also rejects bool, which isinstance
        # (int, float) would have accepted as 0/1.
        wr = _finite(st.get("win_rate"))
        if wr is None:
            continue
        if not source_patch and isinstance(r.get("patch"), str):
            source_patch = r["patch"]
        stage_wr: dict[str, float] = {}
        for s in st.get("augment_stage_stats") or []:
            if not isinstance(s, dict):
                continue
            stg = s.get("augment_stage")
            swr = s.get("win_rate")
            if stg is not None and isinstance(swr, (int, float)):
                stage_wr[str(stg)] = float(swr)
        augments[aid] = {
            "win_rate": float(wr),
            "num_games": _as_int(st.get("num_games")),
            "num_win_games": _as_int(st.get("num_win_games")),
            "pick_rate": _as_float(st.get("pick_rate")),
            "tier": st.get("tier"),
            "stage_win_rate": stage_wr,
        }
    if not augments:
        raise AugmentSourceError("payload yielded zero usable augment rows")
    return {
        "schema": _SCHEMA,
        "mode": mode,
        "endpoint": _ENDPOINTS.get(mode, ""),
        "rc_patch": rc_patch,
        "source_patch": source_patch,
        "source_generated_at": str(meta.get("generated_at") or ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(augments),
        "augments": augments,
    }


def _table_from_snapshot(mode: str, snap: dict) -> AugmentPriorTable:
    augs = snap.get("augments")
    return AugmentPriorTable(
        mode=mode,
        rc_patch=str(snap.get("rc_patch") or ""),
        source_patch=str(snap.get("source_patch") or ""),
        source_generated_at=str(snap.get("source_generated_at") or ""),
        fetched_at=str(snap.get("fetched_at") or ""),
        augments=augs if isinstance(augs, dict) else {},
    )


def refresh_cache(
    mode: str = "mayhem",
    *,
    force: bool = False,
    timeout_s: float = _HTTP_TIMEOUT_S,
) -> AugmentPriorTable:
    """Ensure a snapshot exists for the current RC patch and return its
    table. Patch-pinned: if the file already exists for this patch and
    ``force`` is False, no network call is made (refresh trigger = patch
    flip per S4). With ``force=True`` a failed fetch raises
    AugmentSourceError; without it, fetch failure degrades to the last
    cached snapshot (any patch) or an empty table."""
    if mode not in _ENDPOINTS:
        raise AugmentSourceError(f"unknown mode {mode!r}")
    patch = _current_patch()
    path = _cache_path(mode, patch) if patch else None

    if path and path.exists() and not force:
        snap = read_json_dict(path)
        if snap.get("augments"):
            return _table_from_snapshot(mode, snap)
        # present-but-corrupt -> fall through to re-fetch

    try:
        raw = _http_get_json(_ENDPOINTS[mode], timeout_s)
        snap = _normalize(mode, patch, raw)
    except AugmentSourceError as exc:
        if force:
            raise
        _log.warning("augment_external_source: %s refresh failed (%s); degrading", mode, exc)
        return _load_degraded(mode)

    if path is not None:
        try:
            atomic_write_json(path, snap)
        except OSError as exc:  # cache write best-effort; still return data
            _log.warning("augment_external_source: cache write failed: %s", exc)
    return _table_from_snapshot(mode, snap)


def _load_degraded(mode: str) -> AugmentPriorTable:
    """Last-known snapshot for ``mode`` across any patch dir (newest by
    mtime), or an empty table. Used when a live fetch fails."""
    best: Optional[Path] = None
    best_mtime = -1.0
    if _DS_DATA_DIR.exists():
        for patch_dir in _DS_DATA_DIR.iterdir():
            cand = patch_dir / f"{mode}_augment_stats.json"
            try:
                m = cand.stat().st_mtime
            except OSError:
                continue
            if m > best_mtime:
                best, best_mtime = cand, m
    if best is None:
        return AugmentPriorTable(mode=mode)
    snap = read_json_dict(best)
    _log.info("augment_external_source: degraded to cached %s", best)
    return _table_from_snapshot(mode, snap)


def get_priors(mode: str = "mayhem", *, force_refresh: bool = False) -> AugmentPriorTable:
    """Process-cached accessor for the recommender. mtime-gated against the
    current-patch snapshot so a background refresh / patch flip is picked up
    without a restart. Never raises - degrades to empty on every failure."""
    if mode not in _ENDPOINTS:
        return AugmentPriorTable(mode=mode)
    patch = _current_patch()
    path = _cache_path(mode, patch) if patch else None
    try:
        mtime = path.stat().st_mtime if path and path.exists() else -1.0
    except OSError:
        mtime = -1.0

    with _lock:
        cached = _cache.get(mode)
        if (
            cached is not None
            and not force_refresh
            and _cache_mtime.get(mode, -2.0) == mtime
        ):
            return cached

    table = refresh_cache(mode, force=False)

    with _lock:
        _cache[mode] = table
        # Re-stat: refresh_cache may have just written the file.
        try:
            _cache_mtime[mode] = (
                path.stat().st_mtime if path and path.exists() else mtime
            )
        except OSError:
            _cache_mtime[mode] = mtime
    return table


# -- augment metadata (id -> name / rarity / icon) ------------------------
#
# CommunityDragon mirror of the static LCU asset
# `/lol-game-data/assets/v1/cherry-augments.json` - authoritative
# id->{nameTRA, rarity, icon} for the whole Cherry/Mayhem augment universe
# (568 entries; rarity as kSilver/kGold/kPrismatic/kEventChoice/kBronze).
# Complements RC's existing per-patch `arena_augments.json` (220 entries,
# carries `desc` + an int rarity). Used to reconcile a vision-OCR'd
# display name -> numeric id, which then keys both the external WR prior
# (Task 2) and own-history (`playerAugment{i}` ints).

CHERRY_AUGMENTS_URL = (
    "https://raw.communitydragon.org/latest/plugins/"
    "rcp-be-lol-game-data/global/default/v1/cherry-augments.json"
)
_META_SCHEMA = 1

_meta_lock = threading.Lock()
_meta_cache: Optional["AugmentMetaTable"] = None
_meta_cache_mtime: float = -2.0


def _norm_name(s: str) -> str:
    """Normalize a display name for fuzzy id resolution: lowercase, keep
    only alphanumerics. "Bread And Butter" / "bread-and-butter" / "BREAD
    AND BUTTER!" all collapse to "breadandbutter"."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


@dataclass(frozen=True)
class AugmentMetaTable:
    """Immutable id->metadata + a normalized name->id reverse index."""

    rc_patch: str = ""
    fetched_at: str = ""
    # id (str) -> {name, rarity, icon}
    augments: dict[str, dict] = field(default_factory=dict)
    # normalized-name -> id (int)
    _name_index: dict[str, int] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return bool(self.augments)

    @property
    def count(self) -> int:
        return len(self.augments)

    def _row(self, augment_id) -> Optional[dict]:
        if augment_id is None:
            return None
        return self.augments.get(str(augment_id))

    def name(self, augment_id: int | str | None) -> Optional[str]:
        row = self._row(augment_id)
        return row.get("name") if row else None

    def rarity(self, augment_id: int | str | None) -> Optional[str]:
        row = self._row(augment_id)
        return row.get("rarity") if row else None

    def icon_path(self, augment_id: int | str | None) -> Optional[str]:
        row = self._row(augment_id)
        return row.get("icon") if row else None

    def resolve_id(self, display_name: str) -> Optional[int]:
        """Reverse OCR display name -> numeric augment id (normalized
        match), or None if unrecognized."""
        if not display_name:
            return None
        return self._name_index.get(_norm_name(display_name))


def _arena_augments_path(patch: str) -> Path:
    return _DS_DATA_DIR / patch / "arena_augments.json"


def _build_meta(rc_patch: str, cherry: list) -> dict:
    """cherry-augments.json list -> snapshot. Reconciles secondary names
    from RC's existing arena_augments.json (apiName + name) so OCR strings
    in either vocabulary resolve. cherry-augments.json `id` is canonical;
    arena_augments.json only *adds* alias names, never overrides id."""
    augs: dict[str, dict] = {}
    name_index: dict[str, int] = {}
    for x in cherry:
        if not isinstance(x, dict):
            continue
        aid = x.get("id")
        if not isinstance(aid, int):
            continue
        nm = str(x.get("nameTRA") or x.get("simpleNameTRA") or "").strip()
        augs[str(aid)] = {
            "name": nm,
            "rarity": x.get("rarity"),
            "icon": x.get("augmentSmallIconPath") or "",
        }
        if nm:
            name_index.setdefault(_norm_name(nm), aid)

    # Secondary alias source: RC's arena_augments.json (apiName/name).
    arena_path = _arena_augments_path(rc_patch)
    arena = read_json_dict(arena_path)
    for a in arena.get("augments") or []:
        if not isinstance(a, dict):
            continue
        aid = a.get("id")
        if not isinstance(aid, int):
            continue
        for alias in (a.get("name"), a.get("apiName")):
            if alias:
                name_index.setdefault(_norm_name(alias), aid)

    return {
        "schema": _META_SCHEMA,
        "source": CHERRY_AUGMENTS_URL,
        "rc_patch": rc_patch,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(augs),
        "augments": augs,
        "name_index": name_index,
    }


def _meta_path(patch: str) -> Path:
    return _DS_DATA_DIR / patch / "cherry_augments.json"


def _table_from_meta_snapshot(snap: dict) -> AugmentMetaTable:
    augs = snap.get("augments")
    idx = snap.get("name_index")
    return AugmentMetaTable(
        rc_patch=str(snap.get("rc_patch") or ""),
        fetched_at=str(snap.get("fetched_at") or ""),
        augments=augs if isinstance(augs, dict) else {},
        _name_index=_index_from_snapshot(idx),
    )


def _index_from_snapshot(idx) -> dict[str, int]:
    """Rebuild the normalized-name -> id reverse index from a cached
    snapshot, dropping entries that will not coerce.

    LANE 8 CYCLE 33: this was `{k: int(v) for k, v in idx.items()}`, so a
    single junk value in a cached cherry_augments.json raised ValueError (or
    TypeError for a dict/list) out of `get_augment_meta`, whose docstring
    calls it a "never-raises accessor". Dropping the bad row costs one OCR
    alias; raising cost the whole augment surface.
    """
    if not isinstance(idx, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in idx.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            continue
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _load_degraded_meta() -> AugmentMetaTable:
    best: Optional[Path] = None
    best_mtime = -1.0
    if _DS_DATA_DIR.exists():
        for patch_dir in _DS_DATA_DIR.iterdir():
            cand = patch_dir / "cherry_augments.json"
            try:
                m = cand.stat().st_mtime
            except OSError:
                continue
            if m > best_mtime:
                best, best_mtime = cand, m
    if best is None:
        return AugmentMetaTable()
    _log.info("augment_external_source: degraded to cached meta %s", best)
    return _table_from_meta_snapshot(read_json_dict(best))


def refresh_meta_cache(
    *, force: bool = False, timeout_s: float = _HTTP_TIMEOUT_S
) -> AugmentMetaTable:
    """Patch-pinned cherry-augments.json cache. Same contract as
    `refresh_cache`: file present for current patch + not `force` -> no
    network; fetch failure raises only when `force`, else degrades to the
    last cached snapshot or an empty table."""
    patch = _current_patch()
    path = _meta_path(patch) if patch else None

    if path and path.exists() and not force:
        snap = read_json_dict(path)
        if snap.get("augments"):
            return _table_from_meta_snapshot(snap)

    try:
        cherry = _http_get(CHERRY_AUGMENTS_URL, timeout_s)
        if not isinstance(cherry, list) or not cherry:
            raise AugmentSourceError("cherry-augments.json not a non-empty list")
        snap = _build_meta(patch, cherry)
    except AugmentSourceError as exc:
        if force:
            raise
        _log.warning("augment_external_source: meta refresh failed (%s); degrading", exc)
        return _load_degraded_meta()

    if path is not None:
        try:
            atomic_write_json(path, snap)
        except OSError as exc:
            _log.warning("augment_external_source: meta cache write failed: %s", exc)
    return _table_from_meta_snapshot(snap)


def get_augment_meta(*, force_refresh: bool = False) -> AugmentMetaTable:
    """Process-cached, mtime-gated, never-raises accessor."""
    global _meta_cache, _meta_cache_mtime
    patch = _current_patch()
    path = _meta_path(patch) if patch else None
    try:
        mtime = path.stat().st_mtime if path and path.exists() else -1.0
    except OSError:
        mtime = -1.0

    with _meta_lock:
        if (
            _meta_cache is not None
            and not force_refresh
            and _meta_cache_mtime == mtime
        ):
            return _meta_cache

    table = refresh_meta_cache(force=False)

    with _meta_lock:
        _meta_cache = table
        try:
            _meta_cache_mtime = (
                path.stat().st_mtime if path and path.exists() else mtime
            )
        except OSError:
            _meta_cache_mtime = mtime
    return table


def reset_cache() -> None:
    """Test hook - clear both process caches (WR prior + metadata)."""
    global _meta_cache, _meta_cache_mtime
    with _lock:
        _cache.clear()
        _cache_mtime.clear()
    with _meta_lock:
        _meta_cache = None
        _meta_cache_mtime = -2.0
