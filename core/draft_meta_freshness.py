"""core/draft_meta_freshness.py - staleness signal for hand-curated draft meta.

data/meta/champion_counters.json (pick & ban counters) and
data/meta/global_top_bans.json (ban suggestions) are operator-edited lists
stamped with the ``patch`` and ``updated`` they were written for. RC has no
first-party source that can re-derive them soundly (s156 S3: the rewind
corpus holds about 85 SR games, the newest at 16.14, all from the operator's
own lobbies; the champ-select draft_log table has no rows), so they are NOT
refreshed by machine. What RC can do honestly is say how old they are.

``meta_freshness(doc)`` reads the document's own stamp and compares it with
the live DDragon patch (data/meta/ddragon_version.json). Pure apart from that
one small read, never raises, ASCII only.

Shape (additive response field on the draft routes):
    {
      "source_patch":   "16.10.1" | None,
      "source_updated": "2026-05-15" | None,
      "current_patch":  "16.22.1" | None,
      "patches_behind": 12 | None,   # None when either patch is unknown or
                                     # the major versions differ, or
                                     # the source is AHEAD of the live
                                     # patch (never negative)
      "age_days":       177 | None,  # None when ``updated`` is unknown or
                                     # in the future (never negative)
      "stale":          bool,        # True unless the source patch is known
                                     # and equals the current patch
    }

A patch is ``major.minor[.hotfix]`` in ASCII digits; surrounding whitespace
is dropped and the canonical (stripped) string is what is returned, so a
padded or non-ASCII-digit stamp can never reach the payload. The version
file may carry a UTF-8 BOM (what PowerShell 5.1 writes).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Optional

_DDRAGON_VERSION = (Path(__file__).resolve().parent.parent
                    / "data" / "meta" / "ddragon_version.json")

# re.ASCII: a bare \d also matches Arabic-Indic / fullwidth digits, which
# int() accepts, so such a stamp would pass and leak non-ASCII text.
_PATCH_RE = re.compile(r"(\d{1,3})\.(\d{1,3})(?:\.\d{1,4})?", re.ASCII)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOAD_ERRORS = (OSError, ValueError, RecursionError)


def _canon_patch(value: object) -> Optional[str]:
    """The stripped patch string when ``value`` is a valid patch, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _PATCH_RE.fullmatch(value) else None


def _patch_pair(value: object) -> Optional[tuple[int, int]]:
    canon = _canon_patch(value)
    if canon is None:
        return None
    m = _PATCH_RE.fullmatch(canon)
    return int(m.group(1)), int(m.group(2))


def current_ddragon_patch(path: Optional[Path] = None) -> Optional[str]:
    """The live DDragon patch string, or None when it cannot be read."""
    try:
        doc = json.loads((path or _DDRAGON_VERSION)
                         .read_text(encoding="utf-8-sig"))
    except _LOAD_ERRORS:
        return None
    return _canon_patch(doc.get("version") if isinstance(doc, dict) else None)


def _source_date(value: object) -> Optional[_dt.date]:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def _today(today: object) -> _dt.date:
    """``today`` as a date; a datetime gives its own date, anything else the
    local calendar date from an aware clock (no naive datetime)."""
    if isinstance(today, _dt.datetime):
        return today.date()
    if isinstance(today, _dt.date):
        return today
    return _dt.datetime.now().astimezone().date()


def meta_freshness(doc: object, *, current_patch: Optional[str] = None,
                   today: Optional[_dt.date] = None) -> dict:
    """Staleness of a curated draft-meta document (see module docstring).

    ``current_patch`` / ``today`` are injectable for tests; by default the
    live DDragon version file and the local date are used. An injected
    ``current_patch`` that is not a valid patch reads as unknown (it does not
    fall back to the file).
    """
    doc = doc if isinstance(doc, dict) else {}
    src_patch = _canon_patch(doc.get("patch"))
    src_date = _source_date(doc.get("updated"))
    cur = _canon_patch(current_patch if current_patch is not None
                       else current_ddragon_patch())

    behind: Optional[int] = None
    sp, cp = _patch_pair(src_patch), _patch_pair(cur)
    if sp and cp and sp[0] == cp[0] and cp[1] >= sp[1]:
        # A source stamped AHEAD of the live patch means one of the two
        # stamps is wrong; it is not "behind" by any count.
        behind = cp[1] - sp[1]

    age: Optional[int] = None
    if src_date is not None:
        days = (_today(today) - src_date).days
        # A future ``updated`` is a typo, not a negative age.
        age = days if days >= 0 else None

    stale = not (sp and cp and sp == cp)
    return {
        "source_patch": src_patch,
        "source_updated": src_date.isoformat() if src_date else None,
        "current_patch": cur,
        "patches_behind": behind,
        "age_days": age,
        "stale": bool(stale),
    }
