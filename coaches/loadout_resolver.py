"""coaches/loadout_resolver.py - Phase 2 champion loadout resolver.

Reads `data/champion_loadouts.json` (single mode-keyed file with per-
champion variants) and resolves a variant choice to concrete LCU
payloads ready for the lcu_agent command queue:

  - rune perk_ids + tree IDs  -> apply_runes command
  - item ID list              -> apply_item_set command
  - summoner spell IDs        -> set_summoners command

Variants are scoped per champion. Mode (aram / sr / arena) filters
which variants are visible - a variant only shows in a mode if that
mode appears in its `modes` array. The default variant per mode is
controlled by `default_per_mode`; changing it just edits the JSON.

The resolver re-checks the file mtime on every call so hand-edits to
champion_loadouts.json are picked up live (no RC restart needed).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

# These are private constants in the frozen lcu_rune_writer, but we
# need them to translate variant rune names into LCU perk IDs. We're
# not modifying the file - only importing constants.
from lcu.lcu_rune_writer import _TREES, build_perk_ids, load_rune_rec

_log = logging.getLogger("rc.loadout")

_ROOT           = Path(__file__).resolve().parent.parent
_LOADOUTS_PATH  = _ROOT / "data" / "champion_loadouts.json"
_DDRAGON_ITEMS  = _ROOT / "data" / "meta" / "ddragon_items.json"
_DDRAGON_CHAMPS = _ROOT / "data" / "meta" / "ddragon_champions.json"

_loadouts_cache: dict | None = None
_items_by_name_cache: dict[str, str] | None = None
_champ_id_by_name_cache: dict[str, int] | None = None


def _norm(name: str) -> str:
    """Fuzzy normalizer: lowercase, strip apostrophes/spaces/punctuation."""
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _lookup_champ(loadouts: dict, champion: str) -> dict:
    """Resolve a champion entry tolerant of name-form drift.

    The champ-select view passes the DDragon-key form (CHAMPS.byId, e.g.
    "Kaisa") while the store is keyed by display name ("Kai'Sa"). Exact
    match first, then a fuzzy-normalized fallback so every special-char
    champ (Kai'Sa / Kha'Zix / Kog'Maw / Rek'Sai / Cho'Gath / Vel'Koz /
    Bel'Veth) resolves from either form. Without this the champ-select build
    chooser is empty for those champs (the lookup never finds the entry).
    """
    champ = loadouts.get(champion)
    if champ:
        return champ
    want = _norm(champion)
    if not want:
        return {}
    for key, val in loadouts.items():
        if isinstance(key, str) and _norm(key) == want:
            return val or {}
    return {}


def _load_items_by_name() -> dict[str, str]:
    global _items_by_name_cache
    if _items_by_name_cache is not None:
        return _items_by_name_cache
    out: dict[str, str] = {}
    try:
        d = json.loads(_DDRAGON_ITEMS.read_text(encoding="utf-8"))
        for item_id, info in (d.get("data") or {}).items():
            nm = info.get("name") or ""
            if nm:
                out[_norm(nm)] = str(item_id)
    except Exception as exc:  # noqa: BLE001
        # Do NOT cache on failure - a transient read error (file
        # mid-write) would otherwise poison resolution for the whole
        # process lifetime. Next call retries the read.
        _log.warning("ddragon items load failed: %s", exc)
        return out
    _items_by_name_cache = out
    return out


def _load_champ_id_by_name() -> dict[str, int]:
    global _champ_id_by_name_cache
    if _champ_id_by_name_cache is not None:
        return _champ_id_by_name_cache
    out: dict[str, int] = {}
    try:
        d = json.loads(_DDRAGON_CHAMPS.read_text(encoding="utf-8"))
        for slug, info in (d.get("data") or {}).items():
            try:
                cid = int(info.get("key", -1))
                if cid > 0:
                    out[info.get("name", slug)] = cid
                    out[slug] = cid
            except (ValueError, TypeError):
                pass
    except Exception as exc:  # noqa: BLE001
        # Mirror _load_items_by_name: never poison the cache on a
        # transient read failure.
        _log.warning("ddragon champs load failed: %s", exc)
        return out
    _champ_id_by_name_cache = out
    return out


def _load_loadouts() -> dict:
    """Load + mtime-check loadouts so hand-edits are picked up live."""
    global _loadouts_cache
    try:
        if not _LOADOUTS_PATH.exists():
            return {"champions": {}}
        mt = _LOADOUTS_PATH.stat().st_mtime_ns
        if _loadouts_cache is not None and _loadouts_cache.get("_mtime") == mt:
            return _loadouts_cache
        raw = json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))
        raw["_mtime"] = mt
        _loadouts_cache = raw
        return raw
    except Exception as exc:  # noqa: BLE001
        _log.warning("loadouts load failed: %s", exc)
        return {"champions": {}}


def _normalize_mode(mode: str) -> str:
    """Map LCU/queue mode strings -> variant mode keys (aram/sr/arena/tft).

    Tolerates raw int queue ids (450 / 1700 / ...) - the docstring table
    below matches them in string form."""
    m = str(mode or "").lower()
    if "aram" in m or m in ("kiwi", "450", "920"):
        return "aram"
    if "arena" in m or m in ("1700", "1710", "1750"):
        return "arena"
    if "tft" in m or "teamfight" in m:
        return "tft"
    return "sr"


def list_variants(champion: str, mode: str) -> list[dict]:
    """Return per-variant rows for this mode.

    Each row: {key, label, is_default, keystone, primary, secondary,
    summoners, item_names, item_ids}. The extra fields let the dashboard
    render an inline preview (icons + keystone) per build without a
    second round-trip to /api/loadout/apply.

    Item 213 (2026-05-28): the synthetic ARAM "experimental" row was
    removed - the experimental build chooser is gone for all champs +
    all modes/pages.
    """
    loadouts = _load_loadouts().get("champions", {}) or {}
    champ = _lookup_champ(loadouts, champion)
    variants = champ.get("variants") or {}
    mode_key = _normalize_mode(mode)
    defaults = champ.get("default_per_mode") or {}
    default_key = defaults.get(mode_key, "")

    # The rune the lcu_rune_writer.RuneWriter ACTUALLY auto-applies comes from
    # rune_recommendations_{aram,sr}.json - a separate source from the loadout
    # build-card keystones above. Surface it per row so the champ-select view
    # can mark the genuinely-applied keystone as recommended (display ==
    # applied) instead of the loadout card's own keystone, which can disagree
    # (Caitlyn: loadout=Press the Attack, auto-applied=Arcane Comet). Same
    # ARAM/SR routing the writer uses; computed once per champion.
    _wmode = "ARAM" if mode_key == "aram" else "CLASSIC"
    _auto = load_rune_rec(champion, _wmode)
    auto_ks, auto_pri, auto_sec = _auto if _auto else ("", "", "")

    def _row(key: str, v: dict, is_default: bool) -> dict:
        runes = v.get("runes") or {}
        items = list(v.get("items") or [])
        summ = v.get("summoners") or []
        try:
            d_id, f_id = (int(summ[0]), int(summ[1])) if len(summ) >= 2 else (0, 0)
        except (ValueError, TypeError):
            d_id, f_id = 0, 0
        # Item 178 (2026-05-24): SR variants may carry ``build_paths`` -
        # one collapsed variant per champion with N labeled build-path
        # rows shown vertically inside. Each path is {key, label, items,
        # runes?, summoners?, _archetype?, _source_variant_key?}. The
        # variant-level items/runes/summoners stay populated from the
        # primary path so legacy callers see no shape change. Surface
        # the resolved item_ids per path here so the frontend doesn't
        # have to re-call ddragon resolution.
        build_paths_in = v.get("build_paths") or []
        build_paths_out: list[dict] = []
        for p in build_paths_in:
            if not isinstance(p, dict):
                continue
            p_items = list(p.get("items") or [])
            p_runes = p.get("runes") or {}
            p_summ = p.get("summoners") or []
            try:
                p_d, p_f = (int(p_summ[0]), int(p_summ[1])) if len(p_summ) >= 2 else (d_id, f_id)
            except (ValueError, TypeError):
                p_d, p_f = d_id, f_id
            build_paths_out.append({
                "key":        p.get("key") or "",
                "label":      p.get("label") or "Variant",
                "items":      p_items,
                "item_ids":   _resolve_item_ids(p_items),
                "keystone":   p_runes.get("keystone") or runes.get("keystone") or "",
                "primary":    p_runes.get("primary") or runes.get("primary") or "",
                "secondary":  p_runes.get("secondary") or runes.get("secondary") or "",
                "summoners":  [p_d, p_f],
                "_archetype": p.get("_archetype") or "",
                "_is_primary": bool(p.get("_is_primary", False)),
            })
        return {
            "key":         key,
            "label":       v.get("label") or key,
            "is_default":  is_default,
            "keystone":    runes.get("keystone") or "",
            "primary":     runes.get("primary") or runes.get("primary_tree") or "",
            "secondary":   runes.get("secondary") or runes.get("secondary_tree") or "",
            "summoners":   [d_id, f_id],
            "item_names":  items,
            "item_ids":    _resolve_item_ids(items),
            "build_paths": build_paths_out,
            "_collapsed":  bool(v.get("_collapsed", False)),
            # The keystone the auto-writer applies (display-match source).
            "auto_keystone":   auto_ks,
            "auto_primary":    auto_pri,
            "auto_secondary":  auto_sec,
        }

    out = []
    for key, v in variants.items():
        modes = [str(m).lower() for m in (v.get("modes") or [])]
        if mode_key not in modes:
            continue
        out.append(_row(key, v, key == default_key))
    out.sort(key=lambda r: (not r["is_default"], r["label"]))
    return out


def default_variant(champion: str, mode: str) -> str:
    """Return the default variant key for this champion+mode, or ''."""
    loadouts = _load_loadouts().get("champions", {}) or {}
    champ = _lookup_champ(loadouts, champion)
    mode_key = _normalize_mode(mode)
    default_key = (champ.get("default_per_mode") or {}).get(mode_key, "")
    variants = champ.get("variants") or {}
    if default_key and variants.get(default_key):
        modes = [str(m).lower() for m in (variants[default_key].get("modes") or [])]
        if mode_key in modes:
            return default_key
    # Fallback: first variant that allows this mode
    for key, v in variants.items():
        modes = [str(m).lower() for m in (v.get("modes") or [])]
        if mode_key in modes:
            return key
    return ""


def resolve(champion: str, variant: str, mode: str) -> dict:
    """Resolve champion+variant+mode -> concrete LCU command payloads.

    Returns:
        {
          "ok": bool, "champion", "variant", "label", "mode": str,
          "rune_cmd":  {cmd, page_name, primary_id, sub_id, perk_ids} | None,
          "item_cmd":  {cmd, set_uid, title, champion_id, blocks}     | None,
          "summ_cmd":  {cmd, d, f}                                     | None,
          "raw_items": [str item names - for UI display]
        }
    """
    loadouts = _load_loadouts().get("champions", {}) or {}
    champ = _lookup_champ(loadouts, champion)
    variants = champ.get("variants") or {}
    mode_key = _normalize_mode(mode)
    # Item 178 (2026-05-24): collapsed SR variants accept a sub-path key
    # via "<variant>:<path-key>" so the frontend can apply a specific
    # build path WITHOUT mutating the variant-level fields. When the
    # colon form is passed, the resolver selects the matching path
    # from build_paths[] and overlays its items + (optional) runes +
    # (optional) summoners on the resolved entry. The variant key
    # before the colon must still exist in the file.
    path_key = ""
    if ":" in variant:
        base_variant, _, path_key = variant.partition(":")
        variant = base_variant.strip()
        path_key = path_key.strip()
    # Item 213 (2026-05-28): the experimental variant special-case was
    # removed - the experimental chooser row no longer exists.
    v = variants.get(variant)
    if not v:
        return {"ok": False, "err": f"no variant {variant!r} for {champion!r}"}
    if mode_key not in [str(m).lower() for m in (v.get("modes") or [])]:
        return {"ok": False, "err": f"variant {variant!r} not allowed in {mode_key}"}
    # Item 178: if caller passed a sub-path key on a collapsed variant,
    # overlay that path's items / runes / summoners onto the variant
    # dict before the rune+item+summ cmds are built below. Empty
    # path_key keeps the variant-level defaults (primary path).
    if path_key:
        paths = v.get("build_paths") or []
        matched = None
        for p in paths:
            if isinstance(p, dict) and (p.get("key") or "") == path_key:
                matched = p
                break
        if matched is None:
            return {"ok": False,
                    "err": f"no build_path {path_key!r} for {champion!r}:{variant!r}"}
        # Defensive copy + overlay (items/runes/summoners only).
        v_overlay = dict(v)
        v_overlay["items"] = list(matched.get("items") or v.get("items") or [])
        if matched.get("runes"):
            v_overlay["runes"] = dict(matched.get("runes") or {})
        if matched.get("summoners"):
            v_overlay["summoners"] = list(matched.get("summoners") or [])
        # Suffix the label so the page_name / set_uid carry the
        # path identity (mostly cosmetic - shows up in LCU's set
        # title in-game).
        base_label = v.get("label") or variant
        v_overlay["label"] = f"{base_label} - {matched.get('label') or path_key}"
        v = v_overlay

    # Item 178: identity string baked into page_name / set_uid / title.
    # When a path_key was supplied, the identity includes the path so
    # different paths produce distinct LCU sets (rather than overwriting
    # each other by-uid).
    identity = f"{variant}-{path_key}" if path_key else variant
    out: dict = {
        "ok": True,
        "champion": champion,
        "variant":  variant if not path_key else f"{variant}:{path_key}",
        "path_key": path_key,
        "label":    v.get("label") or variant,
        "mode":     mode_key,
        "rune_cmd": None,
        "item_cmd": None,
        "summ_cmd": None,
        "raw_items": list(v.get("items") or []),
    }

    # Runes ----------------------------------------------------------------
    runes = v.get("runes") or {}
    keystone  = runes.get("keystone") or ""
    primary   = runes.get("primary")   or runes.get("primary_tree")   or ""
    secondary = runes.get("secondary") or runes.get("secondary_tree") or ""
    if keystone and primary and secondary:
        is_aram = (mode_key == "aram")
        perk_ids = build_perk_ids(keystone, primary, secondary, is_aram)
        primary_id = _TREES.get(primary, 0)
        sub_id = _TREES.get(secondary, 0)
        if perk_ids and primary_id and sub_id:
            out["rune_cmd"] = {
                "cmd": "apply_runes",
                "page_name": f"RC: {champion} {identity} ({mode_key.upper()})"[:75],
                "primary_id": primary_id,
                "sub_id":     sub_id,
                "perk_ids":   perk_ids,
            }

    # Items ----------------------------------------------------------------
    item_ids = _resolve_item_ids(out["raw_items"])
    if item_ids:
        champ_id = _load_champ_id_by_name().get(champion, 0)
        out["item_cmd"] = {
            "cmd": "apply_item_set",
            "set_uid":    f"RC-{_norm(champion)}-{mode_key}-{_norm(identity)}",
            "title":      f"RC: {champion} {identity.replace('-', ' ')} ({mode_key.upper()})"[:50],
            "champion_id": champ_id,
            "blocks": [{
                "type":  "Build (RC)",
                "items": [{"id": i, "count": 1} for i in item_ids],
            }],
        }

    # Summoners ------------------------------------------------------------
    summ = v.get("summoners") or []
    if isinstance(summ, list) and len(summ) >= 2:
        try:
            out["summ_cmd"] = {
                "cmd": "set_summoners",
                "d": int(summ[0]), "f": int(summ[1]),
            }
        except (ValueError, TypeError):
            pass

    return out


def _resolve_item_ids(names: list[str]) -> list[str]:
    """Resolve display names to ddragon item IDs. Drops names that miss
    after both exact-fuzzy AND substring fallback (handles abbreviations
    like 'Deathcap' -> 'Rabadon's Deathcap' that LLMs sometimes produce)."""
    by_name = _load_items_by_name()
    # Build inverted lookup: list of (norm_name, id) tuples for substring search
    norm_pairs = [(n, i) for n, i in by_name.items()]
    out: list[str] = []
    for nm in names or []:
        n = _norm(nm)
        rid = by_name.get(n)
        if not rid and len(n) >= 5:
            # Substring fallback - find a ddragon name that CONTAINS this token.
            # Bias toward shortest match (most specific).
            candidates = [(len(full), iid) for full, iid in norm_pairs if n in full]
            if candidates:
                candidates.sort()
                rid = candidates[0][1]
        if rid:
            out.append(rid)
        else:
            _log.debug("loadout: item resolve miss: %s", nm)
    return out
