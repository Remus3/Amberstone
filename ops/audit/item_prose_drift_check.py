"""Item PASSIVE-PROSE number drift-check over every engine item row (RM-808 (c)).

RM-804 found DDragon 16.21.1 moving numbers inside the passive PROSE of seven
engine-registered items (Turbo Chemtank canister heal 4% -> 20%, Dawncore
First Light AP 10 -> 15, Hubris Eminence numbers gone, ...). The ``<stats>``
block has its own checkers (``item_pen_drift_check.py``,
``item_ah_drift_check.py``) and the extractor reads it, but no tool read the
passive clauses, so the RM-766 patch refresh carried a stale "4% max HP" engine
note through green. RM-804 then guarded those 7 rows only.

This checker covers EVERY ``ITEM_EFFECTS`` row. For each row present in the
DDragon ``items.json`` of both the current patch (``current.txt``) and the
previous snapshot on disk (the newest older patch directory, by VERSION order),
it compares the ordered tuple of numbers in the passive prose - the
``description`` with its ``<stats>...</stats>`` block removed and every tag
stripped. Numbers are compared as printed strings, so "1.5" -> "1" is a move.

A moved row is DRIFT unless ``REVIEWED[<current patch>][<item id>]`` names its
new numbers - the record that a person re-read the engine row against the new
prose (fixed the modeled number or note, or decided nothing modeled moved). A
row present in the previous snapshot but absent from the current one is drift
unless reviewed as ``None``. A review entry whose numbers no longer match the
live prose, or that names a row which did not move, is STALE and fails, so the
table cannot rot. Entries for other patches are history and are not read.

Scope, on purpose: engine rows only (a non-engine item's prose is not this
tool's business); the ``<stats>`` block is excluded (other checkers own it).
It detects MOVES between snapshots; it does not judge whether a number the
engine models is right at a single patch.

Read-only. Exit 0 = in sync, 1 = drift / stale review, 2 = no current or no
previous snapshot.

    python ops/audit/item_prose_drift_check.py [--data-root <data/daemon_slayer>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_ROOT = ROOT / "data" / "daemon_slayer"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# patch -> {item id -> reviewed numbers at that patch (None = reviewed removal)}.
REVIEWED: dict[str, dict[str, Optional[tuple[str, ...]]]] = {
    # 16.20.1 -> 16.21.1: the RM-766 description diff, reviewed by RM-804
    # (370d1b15a; engine notes synced) and settled for the modeled halves by
    # RM-808 (a) Hubris (CommunityDragon 16.21 game data) and RM-808 (b)
    # Dawncore (First Light AP modeled).
    "16.21.1": {
        "2520": ("0", "3", "25000", "3"),       # Bastionbreaker Sabotage 90 -> 25000 s (placeholder; utility, not modeled)
        "6621": ("2", "15", "100"),             # Dawncore First Light AP 10 -> 15 (modeled, RM-808 b)
        "6697": ("3", "90"),                    # Hubris Eminence numbers unrendered (RM-808 a: game data)
        "226621": ("3", "15", "100"),           # Dawncore (Arena) AP 10 -> 15 (modeled, RM-808 b)
        "226697": ("3",),                       # Hubris (Arena) numbers unrendered (game data 15 + 2)
        "326621": ("2", "15", "100"),           # Dawncore (ARAM) AP 10 -> 15 (modeled, RM-808 b)
        "443079": ("15", "20"),                 # Turbo Chemtank canister heal 4% -> 20% (not modeled; note synced)
        "444636": ("0", "60", "1"),             # Night Harvester Soulrend MS 40% -> 60%, 1.5 -> 1 s (MS not modeled)
        "447100": ("15", "5"),                  # Mirage Blade Blur 20% -> 15% (not modeled; note synced)
        "447110": ("90", "3", "0.3"),           # Moonflair Spellblade Relentless 2 -> 3, 0.5 -> 0.3 s (not modeled)
    },
}

_STATS_RE = re.compile(r"<stats>.*?</stats>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_PATCH_RE = re.compile(r"^\d+(?:\.\d+)+$")


def prose_numbers(description: Optional[str]) -> tuple[str, ...]:
    """Ordered numbers of the passive prose (``<stats>`` block removed, tags stripped)."""
    body = _STATS_RE.sub(" ", description or "")
    return tuple(_NUM_RE.findall(_TAG_RE.sub(" ", body)))


def patch_key(patch: str) -> tuple[int, ...]:
    return tuple(int(p) for p in patch.split("."))


def list_patches(data_root: Path) -> list[str]:
    """Patch directories holding an ``items.json``, in VERSION order."""
    if not data_root.is_dir():
        return []
    found = [
        p.name for p in data_root.iterdir()
        if p.is_dir() and _PATCH_RE.match(p.name) and (p / "items.json").is_file()
    ]
    return sorted(found, key=patch_key)


def previous_patch(data_root: Path, current: str) -> Optional[str]:
    older = [p for p in list_patches(data_root) if patch_key(p) < patch_key(current)]
    return older[-1] if older else None


def current_patch(data_root: Path) -> Optional[str]:
    try:
        text = (data_root / "current.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def load_engine_ids() -> set[str]:
    from agents.daemon_slayer.effects import ITEM_EFFECTS

    return {str(k) for k in ITEM_EFFECTS}


def _load_items(data_root: Path, patch: str) -> dict:
    blob = json.loads((data_root / patch / "items.json").read_text(encoding="utf-8"))
    data = blob.get("data") if isinstance(blob, dict) else None
    return data if isinstance(data, dict) else {}


@dataclass
class ProseReport:
    current: Optional[str] = None
    previous: Optional[str] = None
    compared: int = 0
    names: dict[str, str] = field(default_factory=dict)
    # item id -> (previous numbers, current numbers)
    unreviewed: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    reviewed_ok: list[str] = field(default_factory=list)
    # item id -> (reviewed numbers, live numbers or None when the row did not move)
    stale_reviews: dict[str, tuple[object, object]] = field(default_factory=dict)

    @property
    def missing_snapshot(self) -> bool:
        return self.current is None or self.previous is None

    @property
    def drift(self) -> bool:
        return bool(self.unreviewed or self.removed or self.stale_reviews)


def check(
    data_root: Path = DATA_ROOT,
    current: Optional[str] = None,
    engine_ids: Optional[Iterable[str]] = None,
    reviewed: Optional[dict[str, dict[str, Optional[tuple[str, ...]]]]] = None,
) -> ProseReport:
    """Diff every engine row's passive-prose numbers, previous snapshot -> current."""
    rep = ProseReport()
    cur = current or current_patch(data_root)
    if cur is None or not (data_root / cur / "items.json").is_file():
        return rep
    rep.current = cur
    prev = previous_patch(data_root, cur)
    if prev is None:
        return rep
    rep.previous = prev
    ids = {str(i) for i in (load_engine_ids() if engine_ids is None else engine_ids)}
    table = (REVIEWED if reviewed is None else reviewed).get(cur, {})
    old_items, new_items = _load_items(data_root, prev), _load_items(data_root, cur)
    moved: set[str] = set()
    for iid in sorted(ids, key=lambda s: (len(s), s)):
        if iid not in old_items:
            continue
        old_nums = prose_numbers(old_items[iid].get("description"))
        if iid not in new_items:
            rep.names[iid] = str(old_items[iid].get("name", "?"))
            moved.add(iid)
            if iid in table and table[iid] is None:
                rep.reviewed_ok.append(iid)
            elif iid not in table:
                rep.removed.append(iid)
            continue
        rep.compared += 1
        rep.names[iid] = str(new_items[iid].get("name", "?"))
        new_nums = prose_numbers(new_items[iid].get("description"))
        if new_nums == old_nums:
            continue
        moved.add(iid)
        if iid not in table:
            rep.unreviewed[iid] = (old_nums, new_nums)
        elif table[iid] == new_nums:
            rep.reviewed_ok.append(iid)
    for iid, nums in sorted(table.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if iid not in moved:
            rep.stale_reviews[iid] = (nums, None)
        elif iid not in rep.reviewed_ok:
            live = prose_numbers(new_items[iid].get("description")) if iid in new_items else None
            rep.stale_reviews[iid] = (nums, live)
    return rep


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = ap.parse_args(argv)
    rep = check(data_root=args.data_root)
    if rep.missing_snapshot:
        print(
            f"NO SNAPSHOT PAIR under {args.data_root}: current={rep.current} "
            f"previous={rep.previous}",
            file=sys.stderr,
        )
        return 2
    print(
        f"DDragon {rep.previous} -> {rep.current}: engine rows compared {rep.compared} "
        f"| moved and reviewed {len(rep.reviewed_ok)} | unreviewed {len(rep.unreviewed)} "
        f"| dropped {len(rep.removed)} | stale reviews {len(rep.stale_reviews)}"
    )
    if rep.unreviewed:
        print("\n-- UNREVIEWED PROSE MOVE (re-read the engine row, then add REVIEWED) --")
        for iid, (old, new) in rep.unreviewed.items():
            print(f"  {iid:>7} {rep.names.get(iid, '?'):32} {old} -> {new}")
    if rep.removed:
        print("\n-- DROPPED FROM DDRAGON (engine row has no current prose) --")
        for iid in rep.removed:
            print(f"  {iid:>7} {rep.names.get(iid, '?')}")
    if rep.stale_reviews:
        print("\n-- STALE REVIEW ENTRY (numbers do not match, or the row did not move) --")
        for iid, (nums, live) in rep.stale_reviews.items():
            print(f"  {iid:>7} {rep.names.get(iid, '?'):32} reviewed={nums} live={live}")
    print("\nRESULT:", "DRIFT" if rep.drift else "IN SYNC")
    return 1 if rep.drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
