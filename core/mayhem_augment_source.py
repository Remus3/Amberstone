"""
core/mayhem_augment_source.py - ARAM Mayhem augment MAGNITUDES from CommunityDragon.

RM-866. RC's augment surfaces knew Mayhem augment names, rarity and icons
(``cherry_augments.json``) and win rates (``mayhem_augment_stats.json``) but
no magnitudes: ``cherry-augments.json`` carries none, and the Arena
``cdragon/arena/en_us.json`` dataValues match zero Mayhem ids (measured
2026-10-25, RM-482 strike). The magnitudes are public in CommunityDragon's
mirror of the Mayhem map bin:

  GET https://raw.communitydragon.org/<cdragon patch>/game/maps/modespecificdata/kiwi.bin.json

(about 13.7 MB at 16.21). The bin is one flat object keyed by object path.
Shape measured on the 16.21 bin (2026-10-25):

* 249 ``AugmentData`` rows. Each has ``AugmentPlatformId`` (the Riot augment
  id - the same key as ``playerAugment{i}`` and ``cherry-augments.json``
  ``id``), ``AugmentNameId`` and a ``RootSpell`` object path.
* Every RootSpell resolves to a ``SpellObject``. 219 carry
  ``mSpell.DataValues``: a list of ``{"name", "values"}`` entries, ``values``
  one number per rank (7 slots). 30 carry no DataValues key at all (only
  ``mSpellCalculations`` formulas, which this extract does not evaluate).
* 8 DataValue entries carry a name and no ``values`` key; one spell (2034)
  repeats a name. Both are kept as found: the per-rank list goes null and the
  entry order is the source order.
* 25 spells carry a ``DataValuesModeOverride`` keyed ``cherry`` (Arena). The
  base DataValues are the ones this extract keeps; the override mode names are
  recorded per row so a consumer can see a value differs in another mode.

Output: a patch-pinned ``data/daemon_slayer/<rc_patch>/mayhem_augments.json``
beside ``cherry_augments.json``, keyed by AugmentPlatformId, with a
source / rc_patch / cdragon_patch / fetched_at header. A row whose spell is
missing or whose DataValues are absent or empty is KEPT with ``values: null``
and a reason from ``NULL_REASONS``; a number that is not in the bin is never
written. The serialization is deterministic (rows in numeric id order, every
other key sorted, ASCII, LF) and goes through ``core.polled_json``'s
tmp-then-replace writer.

Licence: CommunityDragon is already credited in ``NOTICE`` (the
"CommunityDragon (CDragon)" entry); this is the same Riot game data RC reads
from it today (cherry-augments.json, cdragon spell stats). No third-party
tier, win-rate or comp data is involved.

The fetch path is the one ``core/augment_external_source.py`` uses for the
CDragon ``cherry-augments.json`` pull (``CHERRY_AUGMENTS_URL``, patch-pinned
cache ``_meta_path``): the same bounded, NaN-rejecting ``_http_get``.

Scope: this module only produces the data file. Nothing reads it yet (RM-860
picks the surface; RM-664 / RM-671 grade coverage against it); it is not an
engine input.

CLI (writes the file for the live patch in data/daemon_slayer/current.txt):

    python -m core.mayhem_augment_source [--patch 16.21.1]
        [--cdragon-patch 16.21|latest] [--ids-from <json>]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from core import augment_external_source as _aes
from core.augment_external_source import AugmentSourceError
from core.polled_json import atomic_write_bytes

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DS_DATA_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"
_PATCH_FILE = _DS_DATA_DIR / "current.txt"

CDRAGON_BASE = "https://raw.communitydragon.org"
KIWI_BIN_PATH = "game/maps/modespecificdata/kiwi.bin.json"
FILENAME = "mayhem_augments.json"
SCHEMA = 1

# The bin is ~13.7 MB; the shared fetcher caps the body at 32 MB. A generous
# timeout, because this is an operator / tool run, never a coach tick.
_HTTP_TIMEOUT_S = 120.0

# Floors for "a large drop fails loudly". Measured at 16.21 (2026-10-25):
# 249 rows, 219 with at least one number. A bin below either floor is treated
# as a broken or truncated upstream and is never written over a good file.
MIN_ROWS = 200
MIN_WITH_VALUES = 150

# Why a row carries values: null (or, for the last one, no number at all).
NULL_REASONS = (
    "root_spell_missing",
    "root_spell_not_a_spell_object",
    "no_data_values",
    "empty_data_values",
    "all_values_missing",
)

# S144-T-697: matched with fullmatch, never re.match + "$" - "$" also matches
# just before a trailing newline, so "16.21.1" plus a newline passed as an RC
# patch (a directory name carrying the newline) and "16.21" plus one as a
# CDragon dir (a URL carrying it).
_RC_PATCH_RE = re.compile(r"([0-9]+)\.([0-9]+)\.[0-9]+")
_CDRAGON_PATCH_RE = re.compile(r"latest|pbe|[0-9]+\.[0-9]+")
_ID_TEXT_RE = re.compile(r"[0-9]+")


class MayhemAugmentSourceError(AugmentSourceError):
    """A fetched bin that is not usable (wrong shape, or below a floor)."""


def _http_get(url: str, timeout_s: float):
    """Bounded, NaN-rejecting GET -> parsed JSON. Delegates to the CDragon /
    vendor fetcher in core/augment_external_source.py so there is one body
    cap and one non-finite guard. Tests monkeypatch THIS name."""
    return _aes._http_get(url, timeout_s)


def live_patch() -> str:
    """The live RC patch from data/daemon_slayer/current.txt. utf-8-sig, so a
    file saved with a BOM (PowerShell 5.1 ``-Encoding UTF8``) reads as the
    patch rather than as junk; OSError on a missing file propagates."""
    return _PATCH_FILE.read_text(encoding="utf-8-sig").strip()


def cdragon_patch_for(rc_patch: str) -> str:
    """RC patch ``16.21.1`` -> CommunityDragon patch dir ``16.21``."""
    m = _RC_PATCH_RE.fullmatch(rc_patch) if isinstance(rc_patch, str) else None
    if not m:
        raise ValueError(f"not an RC patch (want N.N.N): {rc_patch!r}")
    return f"{int(m.group(1))}.{int(m.group(2))}"


def kiwi_bin_url(cdragon_patch: str) -> str:
    if not (isinstance(cdragon_patch, str) and _CDRAGON_PATCH_RE.fullmatch(cdragon_patch)):
        raise ValueError(f"not a CommunityDragon patch dir: {cdragon_patch!r}")
    return f"{CDRAGON_BASE}/{cdragon_patch}/{KIWI_BIN_PATH}"


def output_path(rc_patch: str, data_dir: Optional[Path] = None) -> Path:
    cdragon_patch_for(rc_patch)  # validates; a path never comes from junk
    return Path(data_dir or _DS_DATA_DIR) / rc_patch / FILENAME


# -- extraction ------------------------------------------------------------------


def _per_rank(values) -> Optional[list]:
    """The entry's per-rank list, or None when absent or not all FINITE numbers.

    S144-T-697: the shared fetcher's parse_constant guard only sees the three
    non-standard literals (NaN, Infinity, -Infinity); an overflowing literal
    such as ``1e999`` is parsed by float() into inf and passes it. A
    non-finite rank is not a magnitude, so the entry goes null like any other
    unusable payload rather than being written as a bare Infinity token."""
    if not isinstance(values, list) or not values:
        return None
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        if isinstance(v, float) and not math.isfinite(v):
            return None
    return list(values)


def _row_values(spell: object) -> tuple[Optional[list], Optional[str], list]:
    """(values, reason, override_modes) for one resolved RootSpell target."""
    if not isinstance(spell, dict) or spell.get("__type") != "SpellObject":
        return None, "root_spell_not_a_spell_object", []
    mspell = spell.get("mSpell")
    mspell = mspell if isinstance(mspell, dict) else {}
    override = mspell.get("DataValuesModeOverride")
    modes = sorted(str(k) for k in override) if isinstance(override, dict) else []
    dvs = mspell.get("DataValues")
    if dvs is None or not isinstance(dvs, list):
        return None, "no_data_values", modes
    if not dvs:
        return None, "empty_data_values", modes
    out = []
    for entry in dvs:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        out.append({
            "name": name if isinstance(name, str) else None,
            "per_rank": _per_rank(entry.get("values")),
        })
    if not out:
        return None, "empty_data_values", modes
    if all(e["per_rank"] is None for e in out):
        return out, "all_values_missing", modes
    return out, None, modes


def extract_rows(kiwi: dict) -> tuple[dict[str, dict], dict[str, int]]:
    """Bin -> ({str(id): row}, {"skipped_no_id", "duplicate_ids"}).

    Pure. AugmentData rows are visited in object-path order, so a duplicated
    AugmentPlatformId keeps the same winner whatever the input order.
    """
    rows: dict[str, dict] = {}
    skipped = 0
    dupes = 0
    for path in sorted(k for k in kiwi if isinstance(k, str)):
        obj = kiwi[path]
        if not isinstance(obj, dict) or obj.get("__type") != "AugmentData":
            continue
        pid = obj.get("AugmentPlatformId")
        if isinstance(pid, bool) or not isinstance(pid, int):
            skipped += 1
            continue
        key = str(pid)
        if key in rows:
            dupes += 1
            continue
        name_id = obj.get("AugmentNameId")
        root = obj.get("RootSpell")
        root = root if isinstance(root, str) and root else None
        if root is None or root not in kiwi:
            values, reason, modes = None, "root_spell_missing", []
        else:
            values, reason, modes = _row_values(kiwi[root])
        rows[key] = {
            "name_id": name_id if isinstance(name_id, str) else None,
            "root_spell": root,
            "values": values,
            "reason": reason,
            "override_modes": modes,
        }
    return rows, {"skipped_no_id": skipped, "duplicate_ids": dupes}


def _has_values(row: dict) -> bool:
    return any(e.get("per_rank") is not None for e in row.get("values") or [])


def build_snapshot(
    kiwi: dict,
    *,
    rc_patch: str,
    source_url: str,
    cdragon_patch: str,
    fetched_at: str,
) -> dict:
    rows, stats = extract_rows(kiwi)
    ordered = {k: rows[k] for k in sorted(rows, key=int)}
    reasons = Counter(r["reason"] for r in ordered.values() if r["values"] is None)
    return {
        "schema": SCHEMA,
        "source": source_url,
        "rc_patch": rc_patch,
        "cdragon_patch": cdragon_patch,
        "fetched_at": fetched_at,
        "count": len(ordered),
        "with_values": sum(1 for r in ordered.values() if _has_values(r)),
        "null_reasons": dict(sorted(reasons.items())),
        "skipped_no_id": stats["skipped_no_id"],
        "duplicate_ids": stats["duplicate_ids"],
        "augments": ordered,
    }


def _sorted_keys(obj):
    """Recursively rebuild every dict with its keys in sorted order. Lists
    keep their order (DataValue entries and per-rank values are ordered)."""
    if isinstance(obj, dict):
        return {k: _sorted_keys(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_sorted_keys(v) for v in obj]
    return obj


def serialize(snap: dict) -> bytes:
    """Deterministic ASCII + LF bytes: header keys sorted, then ``augments``
    last with rows in NUMERIC id order (a sort_keys dump would put "12317"
    before "2034"), keys inside a row sorted, DataValue entries in source
    order. json.dumps always emits "\\n", and the bytes are written as-is, so
    no CRLF translation can happen on Windows. allow_nan=False: a non-finite
    number raises ValueError here instead of becoming a NaN / Infinity token
    that no strict JSON reader accepts (S144-T-697)."""
    augs = snap.get("augments") or {}
    doc = _sorted_keys({k: v for k, v in snap.items() if k != "augments"})
    doc["augments"] = {k: _sorted_keys(augs[k]) for k in sorted(augs, key=int)}
    text = json.dumps(doc, indent=2, ensure_ascii=True, allow_nan=False)
    return (text + "\n").encode("ascii")


def write_snapshot(path: Path, snap: dict) -> None:
    """tmp-then-replace via core.polled_json (never a partial file)."""
    atomic_write_bytes(Path(path), serialize(snap))


def check_floor(snap: dict) -> None:
    if snap["count"] < MIN_ROWS or snap["with_values"] < MIN_WITH_VALUES:
        raise MayhemAugmentSourceError(
            f"kiwi.bin coverage dropped: {snap['count']} rows "
            f"(floor {MIN_ROWS}), {snap['with_values']} with values "
            f"(floor {MIN_WITH_VALUES}); refusing to write"
        )


def coverage(snap: dict, ids: Optional[Iterable[int]] = None) -> dict:
    augs = snap.get("augments") or {}
    out = {
        "rows": len(augs),
        "with_values": sum(1 for r in augs.values() if _has_values(r)),
    }
    if ids is not None:
        want = {str(int(i)) for i in ids}
        out["ids"] = len(want)
        out["ids_with_row"] = sum(1 for i in want if i in augs)
        out["ids_with_values"] = sum(
            1 for i in want if i in augs and _has_values(augs[i])
        )
    return out


def refresh(
    rc_patch: Optional[str] = None,
    *,
    cdragon_patch: Optional[str] = None,
    data_dir: Optional[Path] = None,
    timeout_s: float = _HTTP_TIMEOUT_S,
) -> dict:
    """Fetch the bin, build the snapshot, enforce the floors, write the file.

    Raises AugmentSourceError (fetch), MayhemAugmentSourceError (shape or
    floor), ValueError (a malformed patch, before any fetch) or OSError (an
    unreadable current.txt before any fetch, or a failed write, which leaves
    the old file in place); nothing is written on any failure."""
    rc_patch = rc_patch or live_patch()
    cd_patch = cdragon_patch or cdragon_patch_for(rc_patch)
    url = kiwi_bin_url(cd_patch)
    target = output_path(rc_patch, data_dir)
    kiwi = _http_get(url, timeout_s)
    if not isinstance(kiwi, dict) or not kiwi:
        raise MayhemAugmentSourceError(f"{url} is not a non-empty bin object")
    snap = build_snapshot(
        kiwi,
        rc_patch=rc_patch,
        source_url=url,
        cdragon_patch=cd_patch,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    check_floor(snap)
    write_snapshot(target, snap)
    return snap


def _id_of(key) -> int:
    """One augment id from an ids file: a non-negative non-bool int, or a
    string of ASCII digits. Anything else is a ValueError naming the bad key."""
    if isinstance(key, int) and not isinstance(key, bool) and key >= 0:
        return key
    if isinstance(key, str) and _ID_TEXT_RE.fullmatch(key):
        return int(key)
    raise ValueError(f"not an augment id: {key!r}")


def _ids_from(path: Path) -> list[int]:
    """Augment ids from a JSON list, a dict keyed by id, or a document whose
    ``augments`` dict is keyed by id (the mayhem / cherry file shape).

    S144-T-697: every key is validated (``true`` is not id 1, ``1.5`` is not
    id 1, a bare string is not a list of its characters), and the CLI calls
    this BEFORE the fetch, so a junk file costs no download and never follows
    a write. Raises OSError or ValueError (UnicodeDecodeError and
    JSONDecodeError are ValueErrors)."""
    doc = json.loads(Path(path).read_bytes().decode("utf-8-sig"))
    if isinstance(doc, dict) and "augments" in doc:
        doc = doc["augments"]
    if isinstance(doc, dict):
        keys = list(doc)
    elif isinstance(doc, list):
        keys = doc
    else:
        raise ValueError(f"ids file is a {type(doc).__name__}, want a list or an object")
    return [_id_of(k) for k in keys]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("--patch", default=None, help="RC patch dir (default: current.txt)")
    ap.add_argument("--cdragon-patch", default=None,
                    help="CommunityDragon dir (default: major.minor of --patch)")
    ap.add_argument("--ids-from", default=None,
                    help="JSON of augment ids (list, or a dict / {'augments': dict} keyed by id)"
                         " for a subset census")
    args = ap.parse_args(argv)
    # S144-T-697: the ids file is read FIRST and every failure - a junk ids
    # file, a missing current.txt, a failed write - is one FAILED line, never
    # a traceback, and never a traceback printed after the data file was
    # already replaced.
    try:
        ids = _ids_from(Path(args.ids_from)) if args.ids_from else None
        snap = refresh(args.patch, cdragon_patch=args.cdragon_patch)
    except (AugmentSourceError, ValueError, OSError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    cov = coverage(snap, ids)
    print(f"WROTE {output_path(snap['rc_patch']).as_posix()}")
    print(f"source {snap['source']}")
    print(f"rows {cov['rows']} with_values {cov['with_values']} "
          f"null_reasons {json.dumps(snap['null_reasons'], sort_keys=True)} "
          f"skipped_no_id {snap['skipped_no_id']} duplicate_ids {snap['duplicate_ids']}")
    if ids is not None:
        print(f"subset ids {cov['ids']} with_row {cov['ids_with_row']} "
              f"with_values {cov['ids_with_values']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
