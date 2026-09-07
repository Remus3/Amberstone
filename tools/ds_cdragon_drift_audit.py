"""Offline drift-audit validator for the DS CDragon ability-ratio re-source cutover.

Classifies each "changed" row in a cdragon_ratio_drift.json report into a
suspicion class so a human (or the next loop cycle) can review only the
suspects before flipping prefer_cdragon_ratios default-on.

Usage:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_cdragon_drift_audit.py [--drift PATH] [--json]

    --drift PATH  path to cdragon_ratio_drift.json
                  default: data/daemon_slayer/<current-patch>/cdragon_ratio_drift.json
    --json        print the full audit dict as JSON instead of a summary table
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DS_DATA = REPO_ROOT / "data" / "daemon_slayer"

# Thresholds for explosion detection
_EXPLOSION_PCT_ABS = 1000.0   # abs value for *_pct fields
_EXPLOSION_BASE_ABS = 5000.0  # abs value for "base" field

# Threshold for large_divergence: ratio >= 2x or <= 0.5x
_DIVERGE_HIGH = 2.0
_DIVERGE_LOW = 0.5

# Relative tolerance for approximate equality comparisons
_REL_TOL = 1e-3

# Summary preview: max suspects to print in human mode
_PREVIEW_SUSPECTS = 30


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------


def _approx_eq(a: float, b: float, rel_tol: float = _REL_TOL) -> bool:
    """Return True if a and b are within rel_tol of each other."""
    if a == b:
        return True
    # math.isclose with abs_tol=0 would fail for near-zero; use a small abs floor
    abs_tol = 1e-9
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def _is_off_by_one_residue(meraki: list[float], cdragon: list[float]) -> bool:
    """Return True if cdragon looks like meraki with an extra leading rank-0 prepended.

    Detection rule: for positions i in 1..L-1 (where L = len(meraki)),
    majority of cdragon[i] approx== meraki[i-1], while cdragon[i] != meraki[i].
    Majority means >= ceil((L-1) / 1) which per spec is ALL of them (>= L-1).

    Guard: L must be >= 2 and both arrays must have the same length.
    """
    L = len(meraki)
    if L < 2 or len(cdragon) != L:
        return False

    overlap = L - 1  # positions 1..L-1
    shifted_matches = sum(
        1 for i in range(1, L) if _approx_eq(cdragon[i], meraki[i - 1])
    )
    # majority = >= ceil(overlap / 1) = overlap (all must match)
    required = math.ceil(overlap / 1)
    if shifted_matches < required:
        return False

    # Also verify that cdragon[i] != meraki[i] for those positions
    # (if they happen to be equal the shift detection is ambiguous - not a confident flag)
    non_match_straight = sum(
        1 for i in range(1, L) if not _approx_eq(cdragon[i], meraki[i])
    )
    return non_match_straight >= required


def _is_benign_trailing_extra(meraki: list[float], cdragon: list[float]) -> bool:
    """Return True if cdragon is meraki plus ANY number of extra trailing ranks,
    AND the overlapping prefix matches within rel_tol.

    A trailing extra rank is benign because no ability rank beyond meraki's length
    is ever read (basics cap at rank 5, ults at rank 3). The CDragon resolver emits
    a length-6 array (the len-7 live bin minus the trimmed leading rank-0), so an
    ult block (length-3 meraki) carries +3 unread trailing ranks - those must count
    as benign, not a shape mismatch.
    """
    extra = len(cdragon) - len(meraki)
    if extra < 1:
        return False
    # prefix of cdragon must match meraki exactly (within tol)
    return all(_approx_eq(cdragon[i], meraki[i]) for i in range(len(meraki)))


def _first_nonzero_pair(
    meraki: list[float], cdragon: list[float]
) -> tuple[float, float] | None:
    """Return the first (m, c) pair where both are non-zero, or None."""
    for m, c in zip(meraki, cdragon):
        if m != 0.0 and c != 0.0:
            return m, c
    return None


def classify_row(row: dict) -> str:
    """Classify a single "changed" drift row into a suspicion class.

    Returns one of:
        "explosion"
        "off_by_one_residue"
        "large_divergence"
        "rank_shape_mismatch"
        "clean_balance_drift"
    """
    field: str = row.get("field", "")
    meraki: list[float] | None = row.get("meraki")
    cdragon: list[float] | None = row.get("cdragon")

    # Normalise to lists of floats (guard against None already filtered upstream,
    # but be safe)
    if not meraki or not cdragon:
        return "clean_balance_drift"

    # 1. Explosion check
    is_pct = field.endswith("_pct")
    threshold = _EXPLOSION_PCT_ABS if is_pct else _EXPLOSION_BASE_ABS
    if any(abs(v) > threshold for v in cdragon):
        return "explosion"

    # 2. Off-by-one residue
    if _is_off_by_one_residue(meraki, cdragon):
        return "off_by_one_residue"

    # 3. Large divergence (check before shape mismatch - shape may differ but ratio is key signal)
    pair = _first_nonzero_pair(meraki, cdragon)
    if pair is not None:
        m_val, c_val = pair
        ratio = c_val / m_val
        if ratio >= _DIVERGE_HIGH or ratio <= _DIVERGE_LOW:
            return "large_divergence"

    # 4. Rank shape mismatch
    if len(meraki) != len(cdragon):
        # Check if the extra length is benign (cdragon longer by 1-2, prefix matches)
        if not _is_benign_trailing_extra(meraki, cdragon):
            return "rank_shape_mismatch"

    # 5. Clean balance drift - expected live re-source change
    return "clean_balance_drift"


# ---------------------------------------------------------------------------
# Audit aggregator
# ---------------------------------------------------------------------------

_SUSPECT_CLASSES = frozenset(
    {"explosion", "off_by_one_residue", "large_divergence", "rank_shape_mismatch"}
)


def audit_drift(drift: dict) -> dict:
    """Classify all changed rows and return a structured audit result.

    Returns:
        {
          "summary": {n_changed, explosion, off_by_one_residue,
                      large_divergence, rank_shape_mismatch,
                      clean_balance_drift, n_suspect},
          "suspects": [{champion, slot, field, class, meraki, cdragon, delta}, ...]
        }
    """
    rows = drift.get("rows", [])
    changed = [r for r in rows if r.get("kind") == "changed"]

    counts: dict[str, int] = {
        "explosion": 0,
        "off_by_one_residue": 0,
        "large_divergence": 0,
        "rank_shape_mismatch": 0,
        "clean_balance_drift": 0,
    }
    suspects: list[dict] = []

    for row in changed:
        cls = classify_row(row)
        counts[cls] = counts.get(cls, 0) + 1
        if cls in _SUSPECT_CLASSES:
            suspects.append(
                {
                    # the drift report keys champion as "champ" and the slot as
                    # "ability"; fall back to the alt names for forward-compat.
                    "champion": row.get("champ", row.get("champion", "")),
                    "slot": row.get("ability", row.get("slot", "")),
                    "field": row.get("field", ""),
                    "class": cls,
                    "meraki": row.get("meraki"),
                    "cdragon": row.get("cdragon"),
                    "delta": row.get("delta"),
                }
            )

    n_suspect = sum(counts[c] for c in _SUSPECT_CLASSES)

    summary = {
        "n_changed": len(changed),
        "explosion": counts["explosion"],
        "off_by_one_residue": counts["off_by_one_residue"],
        "large_divergence": counts["large_divergence"],
        "rank_shape_mismatch": counts["rank_shape_mismatch"],
        "clean_balance_drift": counts["clean_balance_drift"],
        "n_suspect": n_suspect,
    }
    return {"summary": summary, "suspects": suspects}


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _resolve_drift_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    cur = DS_DATA / "current.txt"
    patch: str | None = None
    if cur.exists():
        txt = cur.read_text(encoding="utf-8").strip()
        if txt:
            patch = txt.splitlines()[0].strip()
    if patch is None:
        sys.exit(
            "Cannot resolve patch from data/daemon_slayer/current.txt - "
            "pass --drift explicitly."
        )
    return DS_DATA / patch / "cdragon_ratio_drift.json"


def _print_summary(result: dict) -> None:
    s = result["summary"]
    print(
        f"n_changed={s['n_changed']}  "
        f"explosion={s['explosion']}  "
        f"off_by_one_residue={s['off_by_one_residue']}  "
        f"large_divergence={s['large_divergence']}  "
        f"rank_shape_mismatch={s['rank_shape_mismatch']}  "
        f"clean_balance_drift={s['clean_balance_drift']}  "
        f"n_suspect={s['n_suspect']}"
    )
    suspects = result["suspects"]
    if not suspects:
        print("No suspects.")
        return
    print(f"\nSuspects (first {min(_PREVIEW_SUSPECTS, len(suspects))}):")
    hdr = f"  {'champion':<20} {'slot':<5} {'field':<20} {'class'}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for s_row in suspects[:_PREVIEW_SUSPECTS]:
        print(
            f"  {s_row['champion']:<20} {s_row['slot']:<5} "
            f"{s_row['field']:<20} {s_row['class']}"
        )
    if len(suspects) > _PREVIEW_SUSPECTS:
        print(f"  ... and {len(suspects) - _PREVIEW_SUSPECTS} more (use --json for full list)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Classify CDragon ratio drift rows into suspicion classes."
    )
    parser.add_argument(
        "--drift",
        default=None,
        metavar="PATH",
        help="path to cdragon_ratio_drift.json (default: auto from current.txt)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print full audit result as JSON",
    )
    args = parser.parse_args(argv)

    drift_path = _resolve_drift_path(args.drift)
    if not drift_path.exists():
        sys.exit(f"Drift file not found: {drift_path}")

    drift = json.loads(drift_path.read_text(encoding="utf-8"))
    result = audit_drift(drift)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        _print_summary(result)


if __name__ == "__main__":
    main()
