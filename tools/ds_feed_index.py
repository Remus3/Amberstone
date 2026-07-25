"""DS feed provenance index - content-addressed body hashes + declared stamps.

Two design points that MUST survive any later "simplification":

(a) The index is CONTENT-ADDRESSED and is deliberately NOT a payload-patch
    compare. The sanctioned patch-refresh ritual sed-flips `_patch` on
    copied-forward wiki_stats / wiki_ability_stats, so a stamp-only compare
    passes a feed whose body never actually moved. Only a body hash that
    ignores the stamp can tell "refreshed" from "relabelled".

(b) For AUTHORED files the correct invariant is "body changed implies stamp
    changed" - NOT "stamp equals directory". An authored feed can sit
    unchanged and correct in a newer patch dir while still declaring the
    patch it was authored against. That is why enchanter_items.json is
    exception-listed in known_stamp_lag rather than reported red.

Modes:
    python tools/ds_feed_index.py --write    regenerate the index
    python tools/ds_feed_index.py --check    recompute + diff, exit 1 on any
                                             disagreement

Read-only in --check. Exit 0 = in sync, exit 1 = drift, exit 2 = bad usage.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DATA = ROOT / "data" / "daemon_slayer"
_CURRENT_TXT = _DATA / "current.txt"
_INDEX_PATH = Path(__file__).resolve().parent / "ds_feed_index.json"

SEMVER_DIR = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

# Stripped BY KEY NAME ONLY. Never a value-shape regex: wiki_ability_stats
# carries bare numeric strings (speed_raw='1800', cast_time_raw fractions) that
# any "looks like a version or a number" matcher would eat.
_WALL_CLOCK = (
    "fetched_at", "generated_at", "extracted_at", "_generated_at",
    "source_generated_at", "timestamp",
)
_PROSE = ("generated_note", "_note")
_STAMP = (
    "version", "patch", "_patch", "rc_patch", "source_patch", "ddragon_version",
    "patch_segment", "_patch_segment", "meraki_content_patch",
    "_meraki_content_patch", "content_patch",
)
_STRIP = frozenset(_WALL_CLOCK + _PROSE + _STAMP)

# Measured facts (2026-07-19), each verified against the 16.14.1 dir on disk.
KNOWN_STAMP_LAG = {
    "cherry_augments.json":
        "declares rc_patch 16.10.1 - Arena augment set copied forward unchanged "
        "since 16.10.1; authored feed, body has not moved",
    "mayhem_augment_stats.json":
        "declares rc_patch 16.10.1 - Mayhem augment stats sourced at 16.10 and "
        "carried forward; event-mode feed with no newer upstream",
}
# enchanter_items.json was dropped 2026-07-26: the 16.14.1 copy declares
# _meta.patch 16.14.1 (restamped at ENGINE 1.230.0, commit da5cb2ae), so it is
# no longer lagging and the guard test correctly rejected the stale entry. The
# 16.10.1 through 16.13.1 copies still declare 16.9.1; that is historical-dir
# lag, which this list does not track.


def live_patch() -> str:
    """Default patch, resolved from current.txt. NEVER a literal."""
    return _CURRENT_TXT.read_text(encoding="utf-8").strip()


def semver_dirs(root: Path, retired: frozenset[str]) -> list[str]:
    """Top-level semver dirs only. iterdir(), never rglob().

    This is what keeps data/daemon_slayer/build_orders/ and the LFS-tracked
    data/daemon_slayer/laning_scenarios/ out of the index.
    """
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and SEMVER_DIR.match(p.name) and p.name not in retired
    )


def canonical_body(obj):
    """Recursively drop wall-clock, prose, and stamp keys by NAME."""
    if isinstance(obj, dict):
        return {k: canonical_body(v) for k, v in obj.items() if k not in _STRIP}
    if isinstance(obj, list):
        return [canonical_body(v) for v in obj]
    return obj


def body_md5(obj) -> str:
    blob = json.dumps(canonical_body(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:8]


def extract_stamp(obj) -> tuple[str | None, str | None]:
    """Computed, not tabulated: the declared patch stamp and the key it came from.

    Collects every stamp-group key at the top level plus one level down (this
    is what reaches _meta.patch and meraki_items.content_patch), keeps only
    values with exactly 3 dot-separated segments, and tie-breaks
    lexicographically by key name. Measured: zero ties across all 20 feeds.
    """
    if not isinstance(obj, dict):
        return None, None
    found: dict[str, str] = {}
    for key, val in obj.items():
        if key in _STAMP and isinstance(val, str):
            found[key] = val
        if isinstance(val, dict):
            for k2, v2 in val.items():
                if k2 in _STAMP and isinstance(v2, str):
                    found[f"{key}.{k2}"] = v2
    ok = {k: v for k, v in found.items() if len(v.split(".")) == 3}
    if not ok:
        return None, None
    name = sorted(ok)[0]
    return name, ok[name]


def build_index() -> dict:
    sys.path.insert(0, str(ROOT / "tests"))
    from test_ds_fixture_policy import RETIRED_FIXTURES  # type: ignore

    dirs: dict[str, dict] = {}
    for patch in semver_dirs(_DATA, frozenset(RETIRED_FIXTURES)):
        feeds: dict[str, dict] = {}
        for path in sorted((_DATA / patch).glob("*.json")):
            obj = json.loads(path.read_text(encoding="utf-8"))
            field, declared = extract_stamp(obj)
            feeds[path.name] = {
                "body_md5": body_md5(obj),
                "stamp_field": field,
                "declared_patch": declared,
            }
        dirs[patch] = feeds
    return {
        "generated_from_current_txt": live_patch(),
        "known_stamp_lag": dict(KNOWN_STAMP_LAG),
        "dirs": dirs,
    }


def _dump(index: dict) -> str:
    return json.dumps(index, indent=2, sort_keys=True) + "\n"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if mode not in ("--write", "--check"):
        print(f"usage: {Path(__file__).name} [--write|--check]", file=sys.stderr)
        return 2

    fresh = build_index()
    rows = sum(len(v) for v in fresh["dirs"].values())

    if mode == "--write":
        tmp = _INDEX_PATH.with_suffix(".json.tmp")
        tmp.write_text(_dump(fresh), encoding="utf-8")
        tmp.replace(_INDEX_PATH)
        print(f"WROTE {_INDEX_PATH.name}: {len(fresh['dirs'])} dirs, {rows} rows")
        return 0

    if not _INDEX_PATH.exists():
        print(f"NO index at {_INDEX_PATH} - run --write", file=sys.stderr)
        return 1
    stored = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))

    drift: list[str] = []
    if stored.get("generated_from_current_txt") != fresh["generated_from_current_txt"]:
        drift.append(
            f"  current.txt: stored={stored.get('generated_from_current_txt')} "
            f"-> live={fresh['generated_from_current_txt']}"
        )
    if stored.get("known_stamp_lag") != fresh["known_stamp_lag"]:
        drift.append("  known_stamp_lag: stored differs from tool-declared")

    s_dirs, f_dirs = stored.get("dirs", {}), fresh["dirs"]
    for patch in sorted(set(s_dirs) | set(f_dirs)):
        s_feeds, f_feeds = s_dirs.get(patch, {}), f_dirs.get(patch, {})
        for feed in sorted(set(s_feeds) | set(f_feeds)):
            s_row, f_row = s_feeds.get(feed), f_feeds.get(feed)
            if s_row is None:
                drift.append(f"  {patch}/{feed}: MISSING from index")
            elif f_row is None:
                drift.append(f"  {patch}/{feed}: in index, gone from disk")
            elif s_row != f_row:
                drift.append(f"  {patch}/{feed}: {s_row} -> {f_row}")

    print(f"index {len(f_dirs)} dirs / {rows} rows | patch {fresh['generated_from_current_txt']}")
    if drift:
        print("\n-- DRIFT --")
        for line in drift:
            print(line)
    print("\nRESULT:", "DRIFT" if drift else "IN SYNC")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
