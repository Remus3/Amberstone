"""Offline, build-time, versioned dhash-index generator for the Lane E CV atlas.

This is the missing PRECOMPUTED ATLAS layer from docs/NO_LLM_PRECOMPUTE_PLAN.md:
the R96 CV template-match tier (core/vision_template_match.py) rescans
data/icons/{champions,items,spells}/*.png on every cold start with NO persisted
manifest. This module freezes that atlas into a single deterministic, patch-
versioned JSON manifest of perceptual (dhash) fingerprints so a later runtime
tier can load one file instead of re-walking the icon tree.

Design goals:
  - REUSE core.vision_template_match as the single source of the atlas surface
    (available_categories / _CATEGORY_DIRS / list_ids) so the manifest indexes
    EXACTLY the matcher's atlas and cannot drift out from under it.
  - Deterministic output: same icons -> byte-identical manifest (no timestamp
    field, sorted keys) for stable git diffs.
  - Default-OFF: nothing in the RC runtime loop imports this module. It is an
    offline generator run by hand (its main()) or a future build step. A live
    flip is a later, deliberate, versioned decision.

Fail-soft, NEVER raises: cv2/numpy absent, unreadable icon, missing patch file,
malformed input, or numeric trouble all degrade to a safe default (None / {} /
[] / an empty-but-valid manifest). Lazy cv2/numpy imports inside the functions
that need them, so the module imports cleanly with neither installed.

Perceptual hash: a standard difference-hash (dhash). The icon is reduced to
grayscale, block-mean downsampled to (hash_size, hash_size + 1), and each pixel
is compared to its right neighbor; a brighter-left pixel is a 1 bit. The bits
are packed row-major, most-significant-bit first, into a hash_size*hash_size-bit
integer. Similarity is Hamming distance over those bits.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import core.vision_template_match as vtm

_REPO = Path(__file__).resolve().parent.parent
_HASH_SIZE = 8  # produces a 64-bit dhash (hash_size * hash_size bits)
_SCHEMA_VERSION = 1
_PATCH_FILE = _REPO / "data" / "daemon_slayer" / "current.txt"
_MANIFEST_PATH = _REPO / "data" / "daemon_slayer" / "vision_atlas_manifest.json"

_log = logging.getLogger("rc.vision_atlas_precompute")


def _patch() -> str:
    """Current patch string from data/daemon_slayer/current.txt, or 'unknown'.

    Read + strip; any failure (missing file, unreadable) or an empty file yields
    'unknown' so the manifest always carries a usable patch label. Never raises.
    """
    try:
        text = _PATCH_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 - fail-soft contract
        return "unknown"
    return text or "unknown"


def _downsample(arr, out_h, out_w):
    """Block-mean downsample a 2D array to shape (out_h, out_w) deterministically.

    Coerce input to float64; return None when it is not 2D or out dims are < 1.
    Integer bin edges via np.linspace(0, n, out + 1).astype(int) partition the
    rows / cols; each output cell is the mean of its (possibly ragged) block.
    Empty blocks are avoided by clamping the block end to at least start + 1.
    Returns an (out_h, out_w) float64 ndarray, or None on any failure.
    """
    try:
        import numpy as np
    except Exception:  # noqa: BLE001 - numpy optional
        return None
    try:
        a = np.asarray(arr, dtype=np.float64)
        if a.ndim != 2:
            return None
        h, w = int(a.shape[0]), int(a.shape[1])
        oh, ow = int(out_h), int(out_w)
        if h < 1 or w < 1 or oh < 1 or ow < 1:
            return None
        row_edges = np.linspace(0, h, oh + 1).astype(int)
        col_edges = np.linspace(0, w, ow + 1).astype(int)
        out = np.zeros((oh, ow), dtype=np.float64)
        for i in range(oh):
            r0 = int(row_edges[i])
            r1 = int(row_edges[i + 1])
            r1 = max(r1, r0 + 1)
            r1 = min(r1, h)
            for j in range(ow):
                c0 = int(col_edges[j])
                c1 = int(col_edges[j + 1])
                c1 = max(c1, c0 + 1)
                c1 = min(c1, w)
                out[i, j] = float(a[r0:r1, c0:c1].mean())
        return out
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def dhash(gray, hash_size=_HASH_SIZE):
    """Difference-hash of a grayscale (or coercible) image as a Python int.

    Coerce to a 2D float64 array (a 3D array is averaged over its last axis to
    grayscale). Downsample to (hash_size, hash_size + 1), compute the boolean
    matrix d[:, :-1] > d[:, 1:] (left pixel brighter than its right neighbor ->
    bit 1), shape (hash_size, hash_size), and pack it row-major, most-significant
    -bit first, into an int. Deterministic (same array -> same int). Returns None
    on any failure or non-2D input. Never raises.
    """
    try:
        import numpy as np
    except Exception:  # noqa: BLE001 - numpy optional
        return None
    try:
        a = np.asarray(gray, dtype=np.float64)
        if a.ndim == 3:
            a = a.mean(axis=-1)
        if a.ndim != 2:
            return None
        hs = int(hash_size)
        if hs < 1:
            return None
        d = _downsample(a, hs, hs + 1)
        if d is None:
            return None
        diff = d[:, :-1] > d[:, 1:]
        value = 0
        for bit in diff.ravel():
            value = (value << 1) | int(bit)
        return value
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def _coerce_int(x):
    """Coerce x to a non-negative int (int as-is, str parsed as hex), else None.

    bool is rejected. A hex string is parsed via int(x, 16). Any negative result
    or non-coercible input yields None. Never raises.
    """
    try:
        if isinstance(x, bool):
            return None
        if isinstance(x, int):
            v = x
        elif isinstance(x, str):
            v = int(x.strip(), 16)
        else:
            return None
        if v < 0:
            return None
        return v
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def hamming(a, b):
    """Hamming distance between two hashes (int or hex string), or None.

    Each operand is coerced via _coerce_int (int accepted directly, str parsed as
    hex). Returns (a ^ b).bit_count(); returns None if either operand cannot be
    coerced to a non-negative int. Never raises.
    """
    ia = _coerce_int(a)
    ib = _coerce_int(b)
    if ia is None or ib is None:
        return None
    try:
        return (ia ^ ib).bit_count()
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def hex64(h, hash_size=_HASH_SIZE):
    """Lower-case, zero-padded hex string of a dhash int (16 chars for 64-bit).

    Width is (hash_size * hash_size) // 4 nibbles; the value is masked to that
    bit width first. On non-coercible input returns an all-zero string of the
    right width. Never raises.
    """
    try:
        hs = int(hash_size)
    except Exception:  # noqa: BLE001 - fail-soft contract
        hs = _HASH_SIZE
    if hs < 1:
        hs = _HASH_SIZE
    nbits = hs * hs
    width = nbits // 4
    if width < 1:
        width = 1
    try:
        return format(int(h) & ((1 << nbits) - 1), "0" + str(width) + "x")
    except Exception:  # noqa: BLE001 - fail-soft contract
        return "0" * width


def icon_hash(path):
    """dhash int of a single icon PNG read grayscale, or None.

    Lazy cv2. cv2.imread(str(path), IMREAD_GRAYSCALE) then dhash. Returns None if
    cv2 is absent, the file is unreadable, or hashing fails. Never raises.
    """
    try:
        import cv2
    except Exception:  # noqa: BLE001 - opencv optional
        return None
    try:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return dhash(img)
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def build_manifest(categories=None):
    """Build the deterministic dhash manifest over the template-match atlas.

    categories: an optional non-empty list/tuple of category names; otherwise all
    of vtm.available_categories(). Each category is resolved to its icon dir via
    vtm._CATEGORY_DIRS (skipped when absent); every stem from vtm.list_ids(cat)
    (sorted) is hashed and stored as icons[stem] = hex64(hash). Icons that fail to
    hash are skipped (debug-logged).

    Returns a dict with schema_version / generator / hash_algo / hash_bits /
    patch / categories / total_icons and NO timestamp (determinism). On a
    catastrophic failure returns a minimally-valid manifest with empty categories
    and total_icons 0. Never raises.
    """
    try:
        if isinstance(categories, (list, tuple)) and categories:
            cats = list(categories)
        else:
            cats = vtm.available_categories()
        cat_map = {}
        total = 0
        for cat in cats:
            dir_path = vtm._CATEGORY_DIRS.get(cat)
            if dir_path is None:
                continue
            icons = {}
            for stem in sorted(vtm.list_ids(cat) or []):
                h = icon_hash(dir_path / (stem + ".png"))
                if h is None:
                    _log.debug("vision_atlas_precompute: icon hash miss %s/%s", cat, stem)
                    continue
                icons[stem] = hex64(h)
            cat_map[cat] = {"count": len(icons), "icons": icons}
            total += len(icons)
        return {
            "schema_version": _SCHEMA_VERSION,
            "generator": "core.vision_atlas_precompute",
            "hash_algo": "dhash",
            "hash_bits": _HASH_SIZE * _HASH_SIZE,
            "patch": _patch(),
            "categories": cat_map,
            "total_icons": total,
        }
    except Exception:  # noqa: BLE001 - fail-soft contract
        return {
            "schema_version": _SCHEMA_VERSION,
            "generator": "core.vision_atlas_precompute",
            "hash_algo": "dhash",
            "hash_bits": _HASH_SIZE * _HASH_SIZE,
            "patch": "unknown",
            "categories": {},
            "total_icons": 0,
        }


def nearest(query_hash, icons, top_k=5):
    """Top-k (stem, hamming_distance) matches for a query hash within an index.

    icons may be a flat {stem: hexstr_or_int} map OR a category sub-dict of the
    manifest containing an "icons" key (auto-unwrapped). query_hash is coerced
    via int-or-hex. Entries whose stored hash will not coerce are skipped. Returns
    the top_k tuples sorted ascending by (distance, stem). Fail-soft [] on bad or
    empty input. Never raises.
    """
    try:
        q = _coerce_int(query_hash)
        if q is None:
            return []
        if (
            isinstance(icons, dict)
            and isinstance(icons.get("icons"), dict)
        ):
            table = icons["icons"]
        elif isinstance(icons, dict):
            table = icons
        else:
            return []
        try:
            k = int(top_k)
        except Exception:  # noqa: BLE001 - fail-soft contract
            k = 5
        if k < 0:
            k = 0
        results = []
        for stem, stored in table.items():
            dist = hamming(q, stored)
            if dist is None:
                continue
            results.append((stem, dist))
        results.sort(key=lambda item: (item[1], item[0]))
        return results[:k]
    except Exception:  # noqa: BLE001 - fail-soft contract
        return []


def load_manifest(path=None):
    """Load + parse the JSON manifest, or {} on any failure. Never raises."""
    try:
        p = _MANIFEST_PATH if path is None else Path(path)
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - fail-soft contract
        return {}


def write_manifest(manifest, path=None):
    """Atomically write the manifest JSON; return the path, or None on failure.

    Writes to a sibling .tmp then os.replace()-s it into place (overlays poll
    mid-write). JSON is indented, sort_keys=True, ensure_ascii=True, trailing
    newline - deterministic bytes. Best-effort removes the .tmp on failure.
    Never raises.
    """
    p = _MANIFEST_PATH if path is None else Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
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


def main(argv=None):
    """CLI: build the manifest and write it, printing a per-category summary.

    --categories: comma-separated category names (default: all available).
    --out: manifest output path (default: the canonical manifest path).
    Returns 0 on success, 1 on any failure.
    """
    try:
        import argparse

        parser = argparse.ArgumentParser(
            description="Offline Lane E CV atlas dhash-index generator (default-OFF).",
        )
        parser.add_argument(
            "--categories",
            default="",
            help="Comma-separated categories to index (default: all available).",
        )
        parser.add_argument(
            "--out",
            default=str(_MANIFEST_PATH),
            help="Manifest output path (default: the canonical manifest path).",
        )
        args = parser.parse_args(argv)

        raw = (args.categories or "").strip()
        if raw:
            cats = [c.strip() for c in raw.split(",") if c.strip()]
        else:
            cats = vtm.available_categories()

        manifest = build_manifest(cats)
        written = write_manifest(manifest, Path(args.out))

        cat_map = manifest.get("categories", {})
        for cat in sorted(cat_map.keys()):
            count = cat_map.get(cat, {}).get("count", 0)
            print(f"{cat}: {count} icons")
        print(f"total_icons: {manifest.get('total_icons', 0)}")
        print(f"patch: {manifest.get('patch', 'unknown')}")
        print(f"output: {written if written is not None else 'WRITE FAILED'}")
        return 0
    except Exception:  # noqa: BLE001 - fail-soft contract
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
