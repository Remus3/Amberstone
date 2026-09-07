"""Versioned OCR region-map ATLAS - persistence + loader for HUD/API-gap rects.

The region-map companion to R121's icon dhash atlas
(core/vision_atlas_precompute.py -> data/daemon_slayer/vision_atlas_manifest.json,
which catalogs ICON hashes - DISTINCT, not touched here). This module catalogs
the pixel RECTS the OCR tier reads for each HUD field, keyed by field, at a
1920x1080 baseline, plus the static API-gap slots that Live Client :2999
structurally cannot provide (enemy positions behind fog, augment choices). It
scales a calibrated rect from the baseline to any target resolution.

Source of truth for the calibrated rects is data/vision_regions.json (the same
20+ rects the vision tier already reads). The minimap fog rect is NOT a static
literal - it is user-scale-dependent, so its slot carries a dynamic_source
pointer to core.minimap_geometry.compute_minimap_rect rather than a baked rect.

Design contract (mirrors R121): PURE (no cv2 / numpy), FAIL-SOFT (never raises;
returns {} / None / an empty frozenset on any error), DETERMINISTIC (no
timestamp - the committed JSON is a pure function of the source). Atomic write:
json.dumps(indent=2, sort_keys=True, ensure_ascii=True) + newline -> sibling
.tmp -> replace, so overlays polling mid-write never see a torn file.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = 1

# Repo-relative paths (this module lives in core/, so the repo root is one up).
_CORE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CORE_DIR.parent
# The committed JSON lives at the top level of data/daemon_slayer/ (exactly
# like R121's vision_atlas_manifest.json).
DEFAULT_ATLAS_PATH = _REPO_ROOT / "data" / "daemon_slayer" / "vision_region_atlas.json"
_REGIONS_SRC = _REPO_ROOT / "data" / "vision_regions.json"

# Baseline the calibrated rects in vision_regions.json are authored against.
_BASELINE_WIDTH = 1920
_BASELINE_HEIGHT = 1080
# Patch the source rects were calibrated on (matches R121's manifest patch).
_PATCH = "16.13.1"

# Static API-gap slots: fields Live Client :2999 structurally cannot supply.
# minimap_fog is DYNAMIC (user-scale-dependent) so it carries a dynamic_source
# pointer instead of a baked rect; the augment cards are OWED (a calibration
# still owed, no rect yet). rect is null for every gap slot.
_API_GAP_SLOTS = {
    "minimap_fog": {
        "rect": None,
        "kind": "region",
        "api_gap": True,
        "feeds": "enemy_positions",
        "calibration": "dynamic",
        "dynamic_source": "core.minimap_geometry.compute_minimap_rect",
    },
    "augment_card_1": {
        "rect": None,
        "kind": "text",
        "api_gap": True,
        "feeds": "augment_choices",
        "calibration": "owed",
    },
    "augment_card_2": {
        "rect": None,
        "kind": "text",
        "api_gap": True,
        "feeds": "augment_choices",
        "calibration": "owed",
    },
    "augment_card_3": {
        "rect": None,
        "kind": "text",
        "api_gap": True,
        "feeds": "augment_choices",
        "calibration": "owed",
    },
}


def build_atlas(regions_src_path=None):
    """Build the region-map atlas dict from data/vision_regions.json.

    Wraps every calibrated source rect as a numeric, non-api-gap region and then
    merges the static API-gap slots. Deterministic (no timestamp) so the
    committed JSON is a pure function of the source. Returns {} on any read
    failure (fail-soft). Never raises.
    """
    try:
        src = _REGIONS_SRC if regions_src_path is None else Path(regions_src_path)
        raw = json.loads(src.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - fail-soft contract
        return {}

    regions = {}
    try:
        for name, rect in raw.items():
            regions[name] = {
                "rect": list(rect),
                "kind": "numeric",
                "api_gap": False,
                "feeds": name,
                "calibration": "calibrated",
            }
    except Exception:  # noqa: BLE001 - fail-soft contract
        return {}

    # Merge the static gap slots (copied so callers cannot mutate the template).
    for name, slot in _API_GAP_SLOTS.items():
        regions[name] = dict(slot)

    return {
        "schema_version": SCHEMA_VERSION,
        "patch": _PATCH,
        "baseline": {"width": _BASELINE_WIDTH, "height": _BASELINE_HEIGHT},
        "regions": regions,
    }


def write_atlas(atlas, path=None):
    """Atomically write the atlas JSON; return the path, or None on failure.

    Writes to a sibling .tmp then replace()-s it into place (overlays poll
    mid-write). JSON is indent=2, sort_keys=True, ensure_ascii=True, trailing
    newline - deterministic bytes. Best-effort removes the .tmp on failure.
    Never raises.
    """
    p = DEFAULT_ATLAS_PATH if path is None else Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(atlas, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        return p
    except Exception:  # noqa: BLE001 - fail-soft contract
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:  # noqa: BLE001 - best-effort tmp cleanup
            pass
        return None


def load_atlas(path=None):
    """Load + parse the committed atlas JSON, or {} on any failure. Never raises."""
    try:
        p = DEFAULT_ATLAS_PATH if path is None else Path(path)
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - fail-soft contract
        return {}


def _resolve(atlas):
    """Return the atlas to operate on (the argument, or the committed one)."""
    return load_atlas() if atlas is None else atlas


def region(name, atlas=None):
    """Return the region dict for `name`, or None if absent. Never raises."""
    try:
        return _resolve(atlas).get("regions", {}).get(name)
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def scale_region(name, width, height, atlas=None):
    """Linear-scale a CALIBRATED rect from the 1920x1080 baseline to WxH.

    Returns an (x0, y0, x1, y1) int tuple, or None when the region is missing,
    is not "calibrated" (dynamic / owed gap slots have a null rect), or the
    target dimensions are unusable. Never raises.
    """
    try:
        r = region(name, atlas)
        if not r or r.get("calibration") != "calibrated":
            return None
        rect = r.get("rect")
        if not rect or len(rect) != 4:
            return None
        if width <= 0 or height <= 0:
            return None
        sx = width / _BASELINE_WIDTH
        sy = height / _BASELINE_HEIGHT
        x0, y0, x1, y1 = rect
        return (
            int(round(x0 * sx)),
            int(round(y0 * sy)),
            int(round(x1 * sx)),
            int(round(y1 * sy)),
        )
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def _feeds_where(atlas, predicate):
    """Collect the `feeds` of every region whose dict satisfies `predicate`."""
    try:
        regions = _resolve(atlas).get("regions", {})
        return frozenset(
            r.get("feeds")
            for r in regions.values()
            if isinstance(r, dict) and predicate(r) and r.get("feeds")
        )
    except Exception:  # noqa: BLE001 - fail-soft contract
        return frozenset()


def api_gap_fields(atlas=None):
    """The `feeds` of every api_gap region (expect enemy_positions/augment_choices)."""
    return _feeds_where(atlas, lambda r: bool(r.get("api_gap")))


def calibrated_fields(atlas=None):
    """The `feeds` of every calibrated region (== the source field names)."""
    return _feeds_where(atlas, lambda r: r.get("calibration") == "calibrated")


def owed_fields(atlas=None):
    """The `feeds` of every region whose calibration is still owed."""
    return _feeds_where(atlas, lambda r: r.get("calibration") == "owed")
