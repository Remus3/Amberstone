"""SR Draft Theatre - 3-build profile generator.

Phase 8 step 1 (thin slice, 2026-05-04): stub envelope + queue gate.
Phase 8 step 2 (2026-05-04): engine-backed body - calls Daemon Slayer
`/beam` 3× with primary / alt-playstyle / experimental presets and
maps each to the canonical profile shape consumed by P8-5's UI.

`build_profile(champion, role, my_team, their_team, queue_id)` is the
single entry point. It returns a stable shape so the dashboard route +
smoke test can lock in. P8-3 will append user-curated builds with
`kind: "user"`; engine outputs get `kind: "engine"`.

Operator-additive invariant: this generator NEVER reads or writes the
user-curated store at `data/daemon_slayer/user_builds.json`. Merge
happens at the route layer in P8-3.

Caching: profile generation is keyed by
`(champion, role, allies_sig, enemies_sig, level, phase, ...)` and
cached for `_PROFILE_TTL_S`. Champ-select sessions run ~30-60s; the
TTL is generous enough to avoid 3 engine round-trips per dashboard
poll, tight enough that a re-query still fires on a comp change.

Engine connection: HTTP POST to `127.0.0.1:8893/beam`. Engine downtime
or HTTP error => `profiles=[]`, `engine_version=None`, `notes` records
the failure. Caller handles graceful degradation (UI shows "engine
unreachable" hint).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("rc.sr_draft")

# SR queue IDs that should engage the 3-build profile generator.
SR_DRAFT_QUEUE_IDS = frozenset({
    400,  # Normal Draft Pick
    420,  # Ranked Solo/Duo
    430,  # Normal Blind Pick (no draft phase, but champ-select is structurally identical)
    440,  # Ranked Flex
})

_ENGINE_URL = "http://127.0.0.1:8893"
_ENGINE_TIMEOUT_S = 4.0  # /beam ~1s warm; 4s covers cold start

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PRESETS_PATH = _PROJECT_ROOT / "data" / "daemon_slayer" / "sr_draft_presets.json"

# Profile cache: (cache_key -> (ts, profile_envelope))
_PROFILE_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_PROFILE_TTL_S = 60.0
# Bound the cache (audit P2-W1): TTL alone never evicts, so a long RC
# run accumulates one entry per distinct champ-select comp forever.
_PROFILE_CACHE_MAX = 64

# Engine version cache (per-process; engine restarts on version bump).
_ENGINE_VERSION: Optional[str] = None
_ENGINE_VERSION_TS: float = 0.0
_ENGINE_VERSION_TTL_S = 300.0

# Presets cache (mtime-aware so hand-edits land live).
_PRESETS_CACHE: dict[str, Any] | None = None
_PRESETS_MTIME: int | None = None

# Default fallback presets if the JSON is missing/broken - keeps the
# generator alive when the file is being hand-edited.
_FALLBACK_PRESETS: dict[str, Any] = {
    "engine_query": {
        "primary":      {"label": "Primary",      "level": 11, "target_armor": 80,  "target_mr": 50, "phase": None,    "beam_width": 10, "slots": 6, "top": 1},
        "alt":          {"label": "Alt-playstyle","level": 14, "target_armor": 150, "target_mr": 60, "phase": "late",  "beam_width": 10, "slots": 6, "top": 1},
        "experimental": {"label": "Experimental", "level": 9,  "target_armor": 40,  "target_mr": 30, "phase": "early", "beam_width": 20, "slots": 6, "top": 1},
    },
    "rune_defaults_by_role": {
        "TOP":     {"primary": "Conqueror",        "alt": "Grasp of the Undying", "experimental": "Phase Rush"},
        "JUNGLE":  {"primary": "Conqueror",        "alt": "Hail of Blades",       "experimental": "Press the Attack"},
        "MIDDLE":  {"primary": "Electrocute",      "alt": "Arcane Comet",         "experimental": "Phase Rush"},
        "BOTTOM":  {"primary": "Press the Attack", "alt": "Lethal Tempo",         "experimental": "Fleet Footwork"},
        "UTILITY": {"primary": "Glacial Augment",  "alt": "Summon Aery",          "experimental": "Guardian"},
    },
    "tree_by_keystone": {},
    "spells_by_role": {
        "TOP": [4, 12], "JUNGLE": [4, 11], "MIDDLE": [4, 14],
        "BOTTOM": [4, 7], "UTILITY": [4, 14], "_unknown": [4, 14],
    },
    "skeleton_split": {"start": [0, 2], "core": [2, 4], "final": [4, 6]},
}


# ── Public API ───────────────────────────────────────────────────────


def is_sr_draft_queue(queue_id: Optional[int]) -> bool:
    """True when queue_id corresponds to a Summoner's Rift queue that
    Phase 8 should activate for. Centralised so the state builder + the
    route handler agree on the gate."""
    if queue_id is None:
        return False
    try:
        return int(queue_id) in SR_DRAFT_QUEUE_IDS
    except (TypeError, ValueError):
        return False


def build_profile(
    champion: str,
    role: Optional[str] = None,
    my_team: Optional[list[dict[str, Any]]] = None,
    their_team: Optional[list[dict[str, Any]]] = None,
    queue_id: Optional[int] = None,
) -> dict[str, Any]:
    """Return the 3-build profile envelope for an SR champ-select pick.

    Calls Daemon Slayer `/beam` 3× (primary / alt / experimental) and
    maps each to a profile dict. On engine error, returns the empty
    envelope with a `notes` entry.

    Result is cached by `(champion, role, allies_sig, enemies_sig)` for
    `_PROFILE_TTL_S` so repeat polls during a single champ-select don't
    re-hit the engine.
    """
    role_norm = _normalize_role(role)
    allies_sig  = _team_sig(my_team)
    enemies_sig = _team_sig(their_team)
    cache_key = (champion, role_norm, allies_sig, enemies_sig)

    now = time.time()
    cached = _PROFILE_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _PROFILE_TTL_S:
        return cached[1]

    presets = _load_presets()
    notes: list[str] = []
    profiles: list[dict[str, Any]] = []
    engine_version: Optional[str] = None

    queries = presets.get("engine_query", {})
    for kind in ("primary", "alt", "experimental"):
        q = queries.get(kind)
        if not isinstance(q, dict):
            notes.append(f"{kind}: preset missing in sr_draft_presets.json")
            continue
        beam_resp, err = _call_beam(champion, q)
        if err:
            notes.append(f"{kind}: {err}")
            continue
        if engine_version is None:
            engine_version = beam_resp.get("engine_version") or _engine_version()
        profile = _profile_from_beam(
            champion=champion,
            role=role_norm,
            kind=kind,
            preset=q,
            beam_resp=beam_resp,
            presets=presets,
        )
        if profile is not None:
            profiles.append(profile)

    envelope = {
        "champion": champion,
        "role": role_norm,
        "queue_id": queue_id,
        "sr_draft": is_sr_draft_queue(queue_id),
        "engine_version": engine_version,
        "profiles": profiles,
        "notes": notes,
    }
    if len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
        _evict_profile_cache(now)
    _PROFILE_CACHE[cache_key] = (now, envelope)
    return envelope


def _evict_profile_cache(now: float) -> None:
    """Drop expired entries; if still at cap, drop oldest-first."""
    expired = [k for k, (ts, _) in _PROFILE_CACHE.items()
               if (now - ts) >= _PROFILE_TTL_S]
    for k in expired:
        _PROFILE_CACHE.pop(k, None)
    while len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
        oldest = min(_PROFILE_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _PROFILE_CACHE.pop(oldest, None)


def clear_cache() -> None:
    """Test hook: drop the in-process profile + engine-version caches."""
    global _ENGINE_VERSION, _ENGINE_VERSION_TS
    _PROFILE_CACHE.clear()
    _ENGINE_VERSION = None
    _ENGINE_VERSION_TS = 0.0


def _engine_version() -> Optional[str]:
    """Fetch + cache engine_version from /health. /beam doesn't echo it."""
    global _ENGINE_VERSION, _ENGINE_VERSION_TS
    now = time.time()
    if _ENGINE_VERSION and (now - _ENGINE_VERSION_TS) < _ENGINE_VERSION_TTL_S:
        return _ENGINE_VERSION
    try:
        with urllib.request.urlopen(f"{_ENGINE_URL}/health", timeout=1.0) as r:
            d = json.loads(r.read().decode("utf-8"))
        v = d.get("engine_version")
        if isinstance(v, str):
            _ENGINE_VERSION = v
            _ENGINE_VERSION_TS = now
            return v
    except Exception:
        pass
    return None


# ── Internals ────────────────────────────────────────────────────────


def _normalize_role(role: Optional[str]) -> Optional[str]:
    """Coerce role to one of {TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY} or None."""
    if not isinstance(role, str):
        return None
    r = role.strip().upper()
    if r in {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}:
        return r
    # LCU sometimes emits MID / BOT / SUPPORT - coerce.
    aliases = {"MID": "MIDDLE", "BOT": "BOTTOM", "ADC": "BOTTOM",
               "SUPPORT": "UTILITY", "SUP": "UTILITY", "JG": "JUNGLE"}
    return aliases.get(r)


def _team_sig(team: Optional[list[dict[str, Any]]]) -> tuple:
    """Order-independent signature for cache keying."""
    if not isinstance(team, list):
        return ()
    ids = []
    for p in team:
        if isinstance(p, dict):
            cid = p.get("championId")
            if cid:
                # Tolerate malformed payloads ("garbage", "12.5") -
                # a bad entry must not crash the whole profile build.
                try:
                    ids.append(int(cid))
                except (TypeError, ValueError):
                    continue
    return tuple(sorted(ids))


def _load_presets() -> dict[str, Any]:
    """mtime-aware reader so operator hand-edits land without restart."""
    global _PRESETS_CACHE, _PRESETS_MTIME
    try:
        if not _PRESETS_PATH.exists():
            return _FALLBACK_PRESETS
        mt = _PRESETS_PATH.stat().st_mtime_ns
        if _PRESETS_CACHE is not None and _PRESETS_MTIME == mt:
            return _PRESETS_CACHE
        raw = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _FALLBACK_PRESETS
        _PRESETS_CACHE = raw
        _PRESETS_MTIME = mt
        return raw
    except Exception as exc:
        _log.warning("sr_draft presets load failed: %s", exc)
        return _FALLBACK_PRESETS


def _call_beam(champion: str, preset: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
    """POST /beam with the preset's engine_query fields. Returns (resp, err)."""
    body = {
        "champion":     champion,
        "level":        int(preset.get("level", 11)),
        "mode":         "SR",
        "target_armor": float(preset.get("target_armor", 80)),
        "target_mr":    float(preset.get("target_mr", 50)),
        "slots":        int(preset.get("slots", 6)),
        "beam_width":   int(preset.get("beam_width", 10)),
        "top":          int(preset.get("top", 1)),
    }
    phase = preset.get("phase")
    if phase is not None:
        body["phase"] = str(phase)
    try:
        req = urllib.request.Request(
            f"{_ENGINE_URL}/beam",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_ENGINE_TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8")
        except Exception:
            err_body = str(exc)
        return {}, f"engine HTTP {exc.code}: {err_body[:200]}"
    except urllib.error.URLError as exc:
        return {}, f"engine unreachable: {exc.reason}"
    except Exception as exc:
        return {}, f"engine error: {exc}"


def _profile_from_beam(
    *,
    champion: str,
    role: Optional[str],
    kind: str,
    preset: dict[str, Any],
    beam_resp: dict[str, Any],
    presets: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Map a beam response → a profile dict in the canonical shape."""
    ranked = beam_resp.get("ranked")
    if not isinstance(ranked, list) or not ranked:
        return None
    top = ranked[0]
    if not isinstance(top, dict):
        return None
    item_names: list[str] = list(top.get("item_names") or [])
    item_ids:   list[str] = [str(i) for i in (top.get("item_ids") or [])]
    if not item_names:
        return None

    skel = _split_skeleton(item_names, item_ids, presets)
    keystone, runes = _runes_for(role, kind, presets)
    spells = _spells_for(role, presets)

    return {
        "kind":           "engine",
        "key":            kind,                          # primary / alt / experimental
        "label":          preset.get("label") or kind,
        "description":    preset.get("description") or "",
        "champion":       champion,
        "keystone":       keystone,
        "runes":          runes,
        "summoner_spells": spells,
        "item_skeleton":  skel,
        "build_path":     item_names,
        "item_ids":       item_ids,
        "engine": {
            "final_dps":       top.get("final_dps"),
            "baseline_dps":    top.get("baseline_dps"),
            "delta_dps":       top.get("delta_dps"),
            "dps_per_1k_gold": top.get("dps_per_1k_gold"),
            "total_gold":      top.get("total_gold"),
            "phase":           preset.get("phase"),
            "level":           preset.get("level"),
            "target_armor":    preset.get("target_armor"),
            "target_mr":       preset.get("target_mr"),
        },
    }


def _split_skeleton(
    names: list[str],
    ids: list[str],
    presets: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    """Split a 6-item beam result into start / core / final slices."""
    cuts = presets.get("skeleton_split") or _FALLBACK_PRESETS["skeleton_split"]
    out: dict[str, list[dict[str, str]]] = {}
    for slot in ("start", "core", "final"):
        rng = cuts.get(slot) or _FALLBACK_PRESETS["skeleton_split"][slot]
        try:
            lo, hi = int(rng[0]), int(rng[1])
        except (ValueError, IndexError, TypeError):
            lo, hi = 0, 0
        slice_names = names[lo:hi]
        slice_ids   = ids[lo:hi]
        out[slot] = [
            {"name": n, "id": (slice_ids[i] if i < len(slice_ids) else "")}
            for i, n in enumerate(slice_names)
        ]
    return out


def _runes_for(
    role: Optional[str],
    kind: str,
    presets: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    """Pick a keystone and its tree pair for (role, kind)."""
    by_role = presets.get("rune_defaults_by_role", {})
    role_key = role or "BOTTOM"  # safest default for unassigned
    keystones = by_role.get(role_key) or {}
    keystone = keystones.get(kind) or keystones.get("primary") or "Press the Attack"
    trees = (presets.get("tree_by_keystone") or {}).get(keystone) or {}
    runes = {
        "keystone":  keystone,
        "primary":   trees.get("primary")   or "Precision",
        "secondary": trees.get("secondary") or "Domination",
    }
    return keystone, runes


def _spells_for(role: Optional[str], presets: dict[str, Any]) -> list[int]:
    """Role-keyed default summoner spell pair [d_spell_id, f_spell_id]."""
    spells_by_role = presets.get("spells_by_role") or {}
    pair = spells_by_role.get(role or "_unknown") or spells_by_role.get("_unknown") or [4, 14]
    try:
        return [int(pair[0]), int(pair[1])]
    except (ValueError, IndexError, TypeError):
        return [4, 14]
