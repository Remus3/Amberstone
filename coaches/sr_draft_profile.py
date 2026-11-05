"""SR Draft Theatre - 3-build profile generator.

Phase 8 step 1 (thin slice, 2026-05-04): stub envelope + queue gate.
Phase 8 step 2 (2026-05-04): engine-backed body - calls Daemon Slayer
`/beam` 3x with primary / alt-playstyle / experimental presets and
maps each to the canonical profile shape consumed by P8-5's UI.

`build_profile(champion, role, my_team, their_team, queue_id)` is the
single entry point. It returns a stable shape so the dashboard route +
smoke test can lock in. P8-3 will append user-curated builds with
`kind: "user"`; engine outputs get `kind: "engine"`.

Live reach (measured s144 cycle 118): `is_sr_draft_queue` runs on every
dashboard state build (`dashboard/_state_builder.py`), so it must never
raise on any queue id the LCU snapshot carries. `build_profile` has no
live HTTP caller since item 186 retired the POST route; tests and any
future consumer import it directly.

Operator-additive invariant: this generator NEVER reads or writes the
user-curated store at `data/daemon_slayer/user_builds.json`. Merge
happens at the route layer in P8-3.

Caching: profile generation is keyed by
`(champion, role, allies_sig, enemies_sig)` and cached for
`_PROFILE_TTL_S` on the MONOTONIC clock (a wall-clock step must not pin
or flush an entry). Champ-select sessions run ~30-60s; the TTL is
generous enough to avoid 3 engine round-trips per dashboard poll, tight
enough that a re-query still fires on a comp change. Every caller gets
its own deep copy, so a caller that merges user builds into the result
cannot corrupt the cached envelope.

Engine connection: HTTP POST to `127.0.0.1:8860/beam`. Engine downtime
or HTTP error => `profiles=[]`, `engine_version=None`, `notes` records
the failure as a FIXED friendly string (the raw engine body or exception
text is logged to `rc.sr_draft`, never put in `notes`, per the CLAUDE.md
error-handling rule). Caller handles graceful degradation (UI shows
"engine unreachable" hint).

Untrusted inputs (s144 cycle 118 hardening): the LCU payload (queue id,
team champion ids), the hand-edited presets file and the engine's JSON
body are all validated at this boundary - junk falls back to a default
or is dropped, never raises and never ships a NaN / Infinity on the wire.
"""
from __future__ import annotations

import copy
import http.client
import json
import logging
import math
import threading
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

_ENGINE_URL = "http://127.0.0.1:8860"
_ENGINE_TIMEOUT_S = 4.0  # /beam ~1s warm; 4s covers cold start
_HEALTH_TIMEOUT_S = 1.0

# Read caps: the engine is loopback and RC-authored, but a wedged or
# replaced listener must not make one profile build buffer without bound.
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_ERROR_BODY_BYTES = 4096
_MAX_ENGINE_VERSION_LEN = 64
_MAX_CHAMPION_LEN = 64
_MAX_ITEM_NAME_LEN = 128

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PRESETS_PATH = _PROJECT_ROOT / "data" / "daemon_slayer" / "sr_draft_presets.json"

# Profile cache: (cache_key -> (monotonic_ts, profile_envelope)), guarded
# by _PROFILE_LOCK. The lock is never held across an engine call.
_PROFILE_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_PROFILE_LOCK = threading.Lock()
_PROFILE_TTL_S = 60.0
# Bound the cache (audit P2-W1): TTL alone never evicts, so a long RC
# run accumulates one entry per distinct champ-select comp forever.
_PROFILE_CACHE_MAX = 64

# Engine version cache (per-process; engine restarts on version bump).
_ENGINE_VERSION: Optional[str] = None
_ENGINE_VERSION_TS: float = 0.0
_ENGINE_VERSION_TTL_S = 300.0

# Presets cache (mtime-aware so hand-edits land live). A file that failed
# to load is remembered by its mtime so it is parsed and warned about ONCE,
# not on every call, until it changes.
_PRESETS_CACHE: dict[str, Any] | None = None
_PRESETS_MTIME: int | None = None
_PRESETS_BAD_MTIME: int | None = None

_ROLES = frozenset({"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"})
_ROLE_ALIASES = {"MID": "MIDDLE", "BOT": "BOTTOM", "ADC": "BOTTOM",
                 "SUPPORT": "UTILITY", "SUP": "UTILITY", "JG": "JUNGLE"}
_PROFILE_KINDS = ("primary", "alt", "experimental")
# The engine's /beam route 400s any other phase (agents/daemon_slayer/server.py
# `_route_beam`), so a junk phase is dropped here instead of failing the call.
_BEAM_PHASES = frozenset({"early", "mid", "late"})

# engine_query numeric fields: name -> (default, lo, hi). An absent,
# non-numeric, non-finite, boolean or out-of-range value uses the default.
_QUERY_INT_FIELDS: dict[str, tuple[int, int, int]] = {
    "level": (11, 1, 18),
    "slots": (6, 1, 6),
    "beam_width": (10, 1, 64),
    "top": (1, 1, 20),
}
_QUERY_FLOAT_FIELDS: dict[str, tuple[float, float, float]] = {
    "target_armor": (80.0, 0.0, 1000.0),
    "target_mr": (50.0, 0.0, 1000.0),
}
_DEFAULT_SPELLS = [4, 14]
_DEFAULT_KEYSTONE = "Press the Attack"

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


# -- Coercion helpers ---------------------------------------------------


def _as_int(value: Any) -> Optional[int]:
    """An integral id from an int, an integral finite float, or a decimal
    digit string; None for anything else (bool, bytes, NaN, Infinity,
    fractional, overflow, containers)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("-", "+"):
            sign, digits = text[0], text[1:]
        else:
            sign, digits = "", text
        if not digits or len(digits) > 18 or not digits.isascii() or not digits.isdigit():
            return None
        return int(sign + digits)
    return None


def _as_finite(value: Any) -> Optional[float]:
    """A finite number from a real number or a numeric string; None for
    bool, NaN, Infinity and anything non-numeric. An int that fits a float
    stays an int, so an echoed count (total_gold, target_armor) keeps its
    wire type."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            return value if math.isfinite(float(value)) else None
        except OverflowError:
            return None
    if isinstance(value, float):
        try:
            out = float(value)
        except OverflowError:
            return None
    elif isinstance(value, str) and len(value) <= 64:
        try:
            out = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return out if math.isfinite(out) else None


def _clean_str(value: Any, max_len: int) -> Optional[str]:
    """A stripped non-empty str no longer than MAX_LEN, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_len:
        return None
    return text


def _section(presets: Any, key: str) -> dict[str, Any]:
    """PRESETS[KEY] when it is a dict, else the fallback's section."""
    sec = presets.get(key) if isinstance(presets, dict) else None
    if isinstance(sec, dict):
        return sec
    return _FALLBACK_PRESETS[key]


# -- Public API -------------------------------------------------------


def is_sr_draft_queue(queue_id: Any) -> bool:
    """True when queue_id corresponds to a Summoner's Rift queue that
    Phase 8 should activate for. Centralised so the state builder + the
    route handler agree on the gate. Never raises: it runs on every
    dashboard state build."""
    qid = _as_int(queue_id)
    return qid is not None and qid in SR_DRAFT_QUEUE_IDS


def build_profile(
    champion: Any,
    role: Optional[str] = None,
    my_team: Optional[list[dict[str, Any]]] = None,
    their_team: Optional[list[dict[str, Any]]] = None,
    queue_id: Any = None,
) -> dict[str, Any]:
    """Return the 3-build profile envelope for an SR champ-select pick.

    Calls Daemon Slayer `/beam` 3x (primary / alt / experimental) and
    maps each to a profile dict. On engine error, returns the empty
    envelope with a `notes` entry.

    Result is cached by `(champion, role, allies_sig, enemies_sig)` for
    `_PROFILE_TTL_S` so repeat polls during a single champ-select don't
    re-hit the engine. A missing / non-string / oversize champion gets
    the empty envelope at once: no engine call, nothing cached.
    """
    role_norm = _normalize_role(role)
    qid = _as_int(queue_id)
    champ = _clean_str(champion, _MAX_CHAMPION_LEN)
    if champ is None:
        return _envelope(None, role_norm, qid, None, [],
                         ["no champion selected - build profiles skipped"])

    allies_sig = _team_sig(my_team)
    enemies_sig = _team_sig(their_team)
    cache_key = (champ, role_norm, allies_sig, enemies_sig)

    with _PROFILE_LOCK:
        cached = _PROFILE_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < _PROFILE_TTL_S:
            return copy.deepcopy(cached[1])

    presets = _load_presets()
    notes: list[str] = []
    profiles: list[dict[str, Any]] = []
    engine_version: Optional[str] = None

    queries = _section(presets, "engine_query")
    for kind in _PROFILE_KINDS:
        q = queries.get(kind)
        if not isinstance(q, dict):
            notes.append(f"{kind}: preset missing in sr_draft_presets.json")
            continue
        beam_resp, err = _call_beam(champ, q)
        if err:
            notes.append(f"{kind}: {err}")
            continue
        if engine_version is None:
            engine_version = (_clean_str(beam_resp.get("engine_version"),
                                         _MAX_ENGINE_VERSION_LEN)
                              or _engine_version())
        profile = _profile_from_beam(
            champion=champ,
            role=role_norm,
            kind=kind,
            preset=q,
            beam_resp=beam_resp,
            presets=presets,
        )
        if profile is not None:
            profiles.append(profile)

    envelope = _envelope(champ, role_norm, qid, engine_version, profiles, notes)
    with _PROFILE_LOCK:
        now = time.monotonic()
        if len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
            _evict_profile_cache(now)
        _PROFILE_CACHE[cache_key] = (now, envelope)
    return copy.deepcopy(envelope)


def _envelope(
    champion: Optional[str],
    role: Optional[str],
    queue_id: Optional[int],
    engine_version: Optional[str],
    profiles: list[dict[str, Any]],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "champion": champion,
        "role": role,
        "queue_id": queue_id,
        "sr_draft": queue_id is not None and queue_id in SR_DRAFT_QUEUE_IDS,
        "engine_version": engine_version,
        "profiles": profiles,
        "notes": notes,
    }


def _evict_profile_cache(now: float) -> None:
    """Drop expired entries; if still at cap, drop oldest-first.
    Caller holds _PROFILE_LOCK."""
    expired = [k for k, (ts, _) in _PROFILE_CACHE.items()
               if (now - ts) >= _PROFILE_TTL_S]
    for k in expired:
        _PROFILE_CACHE.pop(k, None)
    while _PROFILE_CACHE and len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
        oldest = min(_PROFILE_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _PROFILE_CACHE.pop(oldest, None)


def clear_cache() -> None:
    """Test hook: drop the in-process profile + engine-version caches."""
    global _ENGINE_VERSION, _ENGINE_VERSION_TS
    with _PROFILE_LOCK:
        _PROFILE_CACHE.clear()
        _ENGINE_VERSION = None
        _ENGINE_VERSION_TS = 0.0


def _engine_version() -> Optional[str]:
    """Fetch + cache engine_version from /health. /beam doesn't echo it."""
    global _ENGINE_VERSION, _ENGINE_VERSION_TS
    now = time.monotonic()
    if _ENGINE_VERSION and (now - _ENGINE_VERSION_TS) < _ENGINE_VERSION_TTL_S:
        return _ENGINE_VERSION
    try:
        with urllib.request.urlopen(f"{_ENGINE_URL}/health",
                                    timeout=_HEALTH_TIMEOUT_S) as r:
            d = _parse_json_body(r)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        _log.debug("sr_draft engine /health read failed: %s", exc)
        return None
    v = _clean_str(d.get("engine_version") if isinstance(d, dict) else None,
                   _MAX_ENGINE_VERSION_LEN)
    if v is not None:
        _ENGINE_VERSION = v
        _ENGINE_VERSION_TS = now
    return v


# -- Internals --------------------------------------------------------


def _normalize_role(role: Optional[str]) -> Optional[str]:
    """Coerce role to one of {TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY} or None."""
    if not isinstance(role, str):
        return None
    r = role.strip().upper()
    if r in _ROLES:
        return r
    # LCU sometimes emits MID / BOT / SUPPORT - coerce.
    return _ROLE_ALIASES.get(r)


def _team_sig(team: Optional[list[dict[str, Any]]]) -> tuple:
    """Order-independent signature for cache keying. Only positive
    integral champion ids count (0 = unpicked); a malformed entry is
    skipped, never fatal."""
    if not isinstance(team, list):
        return ()
    ids = []
    for p in team:
        if isinstance(p, dict):
            cid = _as_int(p.get("championId"))
            if cid is not None and cid > 0:
                ids.append(cid)
    return tuple(sorted(ids))


def _load_presets() -> dict[str, Any]:
    """mtime-aware reader so operator hand-edits land without restart.

    A missing file, unreadable file, bad JSON or a non-object top level
    yields the in-module fallback; a bad file is parsed and warned about
    once per mtime. A UTF-8 BOM (Windows editors add one) is accepted.
    """
    global _PRESETS_CACHE, _PRESETS_MTIME, _PRESETS_BAD_MTIME
    try:
        mt = _PRESETS_PATH.stat().st_mtime_ns
    except OSError:
        return _FALLBACK_PRESETS
    if _PRESETS_CACHE is not None and mt == _PRESETS_MTIME:
        return _PRESETS_CACHE
    if mt == _PRESETS_BAD_MTIME:
        return _FALLBACK_PRESETS
    try:
        raw = json.loads(_PRESETS_PATH.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        # RecursionError: a hand-edit nested deeper than the decoder's stack.
        raw, reason = None, type(exc).__name__ + ": " + str(exc)[:200]
    else:
        reason = "top level is not a JSON object"
    if not isinstance(raw, dict):
        _PRESETS_BAD_MTIME = mt
        _log.warning("sr_draft presets load failed (%s); using built-in defaults",
                     reason)
        return _FALLBACK_PRESETS
    _PRESETS_CACHE = raw
    _PRESETS_MTIME = mt
    _PRESETS_BAD_MTIME = None
    return raw


def _preset_number(preset: dict[str, Any], name: str) -> float:
    """PRESET[NAME] for a _QUERY_FLOAT_FIELDS field when it is a finite
    in-range number (an int stays an int), else the field's default."""
    fdefault, flo, fhi = _QUERY_FLOAT_FIELDS[name]
    f = _as_finite(preset.get(name))
    return f if f is not None and flo <= f <= fhi else fdefault


def _query_body(champion: str, preset: dict[str, Any], *,
                warn: bool = True) -> dict[str, Any]:
    """The /beam request body for PRESET, every field coerced and bounded."""
    body: dict[str, Any] = {"champion": champion, "mode": "SR"}
    for name, (default, lo, hi) in _QUERY_INT_FIELDS.items():
        v = _as_int(preset.get(name))
        body[name] = v if v is not None and lo <= v <= hi else default
    for name in _QUERY_FLOAT_FIELDS:
        body[name] = float(_preset_number(preset, name))
    phase = preset.get("phase")
    if isinstance(phase, str) and phase in _BEAM_PHASES:
        body["phase"] = phase
    elif phase is not None and warn:
        _log.warning("sr_draft preset phase %r is not early|mid|late; omitted",
                     phase if isinstance(phase, str) else type(phase).__name__)
    return body


def _read_capped(stream: Any, cap: int) -> bytes:
    """At most CAP bytes from STREAM; ValueError when it holds more."""
    data = stream.read(cap + 1)
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("engine body is not bytes")
    if len(data) > cap:
        raise ValueError(f"engine body exceeds {cap} bytes")
    return bytes(data)


def _parse_json_body(stream: Any) -> Any:
    """Decode a capped JSON body. A body nested deeper than the C decoder's
    stack (e.g. 200 KB of "[") raises RecursionError, which is NOT a
    ValueError - re-raised as one so every caller's decode branch takes it."""
    text = _read_capped(stream, _MAX_RESPONSE_BYTES).decode("utf-8")
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise ValueError("engine body nests too deeply") from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    """A bounded, log-only excerpt of an HTTPError body."""
    try:
        raw = exc.read(_MAX_ERROR_BODY_BYTES)
    except (OSError, ValueError, http.client.HTTPException, AttributeError, TypeError):
        return ""
    if not isinstance(raw, (bytes, bytearray)):
        return ""
    return bytes(raw[:_MAX_ERROR_BODY_BYTES]).decode("utf-8", "replace")


def _call_beam(champion: str, preset: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
    """POST /beam with the preset's engine_query fields. Returns (resp, err).

    `err` is a FIXED friendly string (the HTTP status is the only detail it
    carries); the raw engine body or exception text goes to the log only.
    An exception outside the transport / decode families is a real bug and
    propagates.
    """
    body = _query_body(champion, preset)
    req = urllib.request.Request(
        f"{_ENGINE_URL}/beam",
        data=json.dumps(body, allow_nan=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_ENGINE_TIMEOUT_S) as r:
            resp = _parse_json_body(r)
    except urllib.error.HTTPError as exc:
        _log.warning("sr_draft /beam HTTP %s for %s: %s",
                     exc.code, champion, _read_error_body(exc)[:200])
        return {}, f"engine HTTP {exc.code}"
    except urllib.error.URLError as exc:
        _log.warning("sr_draft /beam unreachable: %s", exc.reason)
        return {}, "engine unreachable"
    except (ValueError, UnicodeDecodeError) as exc:
        _log.warning("sr_draft /beam malformed response: %s", exc)
        return {}, "engine returned a malformed response"
    except (OSError, http.client.HTTPException) as exc:
        _log.warning("sr_draft /beam transport error: %r", exc)
        return {}, "engine error"
    if not isinstance(resp, dict):
        _log.warning("sr_draft /beam body is %s, not an object",
                     type(resp).__name__)
        return {}, "engine returned a malformed response"
    return resp, None


def _profile_from_beam(
    *,
    champion: str,
    role: Optional[str],
    kind: str,
    preset: dict[str, Any],
    beam_resp: dict[str, Any],
    presets: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Map a beam response -> a profile dict in the canonical shape.

    None when the response carries no usable top row (no ranked list, a
    non-dict row, or no string item names). Item names keep only non-empty
    strings; ids keep their slot (a junk id becomes ""); engine numbers
    are finite floats or None so the envelope is strict JSON."""
    ranked = beam_resp.get("ranked") if isinstance(beam_resp, dict) else None
    if not isinstance(ranked, list) or not ranked:
        return None
    top = ranked[0]
    if not isinstance(top, dict):
        return None
    raw_names = top.get("item_names")
    if not isinstance(raw_names, list):
        return None
    item_names = [n for n in (_clean_str(x, _MAX_ITEM_NAME_LEN) for x in raw_names)
                  if n is not None]
    if not item_names:
        return None
    raw_ids = top.get("item_ids")
    item_ids = [_item_id(i) for i in raw_ids] if isinstance(raw_ids, list) else []

    skel = _split_skeleton(item_names, item_ids, presets)
    keystone, runes = _runes_for(role, kind, presets)
    spells = _spells_for(role, presets)
    query = _query_body(champion, preset, warn=False)

    return {
        "kind":           "engine",
        "key":            kind,                          # primary / alt / experimental
        "label":          _clean_str(preset.get("label"), 64) or kind,
        "description":    _clean_str(preset.get("description"), 256) or "",
        "champion":       champion,
        "keystone":       keystone,
        "runes":          runes,
        "summoner_spells": spells,
        "item_skeleton":  skel,
        "build_path":     item_names,
        "item_ids":       item_ids,
        "engine": {
            "final_dps":       _as_finite(top.get("final_dps")),
            "baseline_dps":    _as_finite(top.get("baseline_dps")),
            "delta_dps":       _as_finite(top.get("delta_dps")),
            "dps_per_1k_gold": _as_finite(top.get("dps_per_1k_gold")),
            "total_gold":      _as_finite(top.get("total_gold")),
            "phase":           query.get("phase"),
            "level":           query["level"],
            "target_armor":    _preset_number(preset, "target_armor"),
            "target_mr":       _preset_number(preset, "target_mr"),
        },
    }


def _item_id(value: Any) -> str:
    """A string item id ("3031") from a str or int id; "" for junk."""
    if isinstance(value, str):
        return value.strip() if len(value) <= 16 else ""
    n = _as_int(value)
    return str(n) if n is not None and n >= 0 else ""


def _cut(rng: Any) -> Optional[tuple[int, int]]:
    if not isinstance(rng, (list, tuple)) or len(rng) < 2:
        return None
    lo, hi = _as_int(rng[0]), _as_int(rng[1])
    if lo is None or hi is None or lo < 0 or hi < lo:
        return None
    return lo, hi


def _split_skeleton(
    names: list[str],
    ids: list[str],
    presets: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    """Split a 6-item beam result into start / core / final slices.

    A cut that is not a non-negative, non-decreasing integer pair uses the
    default cut for that slot, so a hand-edit can never index from the end
    of the build."""
    cuts = _section(presets, "skeleton_split")
    default_cuts = _FALLBACK_PRESETS["skeleton_split"]
    out: dict[str, list[dict[str, str]]] = {}
    for slot in ("start", "core", "final"):
        lo, hi = _cut(cuts.get(slot)) or tuple(default_cuts[slot])
        slice_names = names[lo:hi]
        slice_ids = ids[lo:hi]
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
    by_role = _section(presets, "rune_defaults_by_role")
    role_key = role or "BOTTOM"  # safest default for unassigned
    keystones = by_role.get(role_key)
    if not isinstance(keystones, dict):
        keystones = {}
    keystone = (_clean_str(keystones.get(kind), 64)
                or _clean_str(keystones.get("primary"), 64)
                or _DEFAULT_KEYSTONE)
    trees = _section(presets, "tree_by_keystone").get(keystone)
    if not isinstance(trees, dict):
        trees = {}
    runes = {
        "keystone":  keystone,
        "primary":   _clean_str(trees.get("primary"), 64) or "Precision",
        "secondary": _clean_str(trees.get("secondary"), 64) or "Domination",
    }
    return keystone, runes


def _spell_pair(pair: Any) -> Optional[list[int]]:
    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
        return None
    d, f = _as_int(pair[0]), _as_int(pair[1])
    if d is None or f is None or d <= 0 or f <= 0:
        return None
    return [d, f]


def _spells_for(role: Optional[str], presets: dict[str, Any]) -> list[int]:
    """Role-keyed default summoner spell pair [d_spell_id, f_spell_id]."""
    spells_by_role = _section(presets, "spells_by_role")
    return (_spell_pair(spells_by_role.get(role or "_unknown"))
            or _spell_pair(spells_by_role.get("_unknown"))
            or list(_DEFAULT_SPELLS))
