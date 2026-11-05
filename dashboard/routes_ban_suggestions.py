"""s210: Suggestions panel - global ban suggestions endpoint.

GET /api/champ-select/ban-suggestions?exclude=119,236,86,99,51,150&top=4

Returns the top-N globally-banned champions from
``data/meta/global_top_bans.json``, filtered to exclude champions
already banned by either team. Stateless + file-backed; the operator
edits the JSON when the meta shifts.

Distinct from /api/champ-select/pickban-recs (which reads operator-
specific match history). The Suggestions panel surfaces what the
global player base bans; the Pick & Ban panel surfaces what the
operator personally struggles against.

Response:
  {
    "ok": true,
    "patch": "16.10.1",
    "suggestions": [
      {"champId": 777, "name": "Yone", "icon": "/icons/champions/Yone.png",
       "rank": 1},
      ...up to 4
    ],
    "excluded_count": int,
    "fell_back": bool   // true when fewer than N suggestions remained after filtering
  }

``rank`` (OQ9, QA26 remainder) is the champion's 1-based position in the
meta ``top_bans`` list - the honest why-banned signal for the suggestion
card label ("meta ban #N"). It is NOT re-numbered after exclusion
filtering, so a card can honestly read "meta ban #3" even when ranks 1-2
were already banned. Additive field, appended at END of dict.

True-audit s144 cycle 111 (RM-1446) contract, each line pinned by
tests/test_routes_ban_suggestions_true_audit.py:

* ``icon`` names the DDragon slug PNG (``Wukong`` -> ``MonkeyKing.png``,
  ``Kha'Zix`` -> ``Khazix.png``), the file name data/icons/champions/
  actually carries. A display-name-derived slug is only the fallback for a
  champion the DDragon index does not know.
* A failed DDragon load is NOT cached: the next request retries, so one
  transient read error cannot blank the panel until a restart.
* A malformed bans document (not an object, ``top_bans`` not a list,
  non-string entries, non-string ``patch``) degrades to fewer / no
  suggestions and ``patch: "unknown"``, never a 500.
* A champion listed twice (spelling variants) yields ONE card, at its
  first rank.
* ``exclude`` counts only positive decimal ids; Python-literal forms
  (``1_000``, ``+5``) and non-positive ids are ignored.
* The loaders swallow only I/O and JSON errors (``RecursionError``
  included: a pathologically nested file is a malformed file); anything
  else reaches the route's generic 500 (raw text stays in the log).
* A DDragon ``key`` counts only as a positive decimal string or a plain
  int; floats, bools, ``Infinity`` and Python-literal forms skip the row.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("rc.web_dashboard")

_BANS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "global_top_bans.json"
_CHAMPS_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_champions.json"

_TOP_DEFAULT = 4
_TOP_MIN = 1
_TOP_MAX = 10
_EMPTY_BANS = {"top_bans": [], "patch": "unknown"}
_ID_MAX_DIGITS = 9
# What a file read + json.loads may legitimately raise on bad bytes:
# OSError (I/O), ValueError (JSONDecodeError, UnicodeDecodeError) and
# RecursionError (nesting deeper than the parser's stack).
_LOAD_ERRORS = (OSError, ValueError, RecursionError)

# Module-level champion index: (display-name/slug variant -> id,
# id -> DDragon slug). ddragon_champions.json does not change across
# requests, so a SUCCESSFUL load is cached for the process lifetime; a
# failed or empty load is not, so the next request retries. The bans file
# is small enough to re-read each call (~1KB, sub-ms) so operator edits are
# picked up without a restart.
_CHAMP_INDEX: tuple[dict[str, int], dict[int, str]] | None = None
_INDEX_LOCK = threading.Lock()


def _name_variants(name: str) -> tuple[str, ...]:
    """Spelling variants a bans-file author may use for one display name:
    as written, without apostrophes, without spaces, without both."""
    no_apos = name.replace("'", "")
    return (name, no_apos, name.replace(" ", ""), no_apos.replace(" ", ""))


def _champ_key(key: object) -> int | None:
    """A DDragon champion ``key`` ("266") as a positive int, else None."""
    if isinstance(key, bool):
        return None
    if isinstance(key, int):
        return key if key > 0 else None
    if isinstance(key, str):
        return _positive_id(key.strip())
    return None


def _positive_id(token: str) -> int | None:
    """A positive ASCII-decimal id of at most _ID_MAX_DIGITS digits, else
    None. The length cap keeps int() far below Python's 4300-digit
    string-conversion limit; no champion id comes close to 9 digits."""
    if not (token.isascii() and token.isdigit()) or len(token) > _ID_MAX_DIGITS:
        return None
    value = int(token)
    return value if value > 0 else None


def _build_champ_index() -> tuple[dict[str, int], dict[int, str]] | None:
    """Read ddragon_champions.json into the two lookup maps. Returns None
    when the file cannot be read or is not the expected shape; skips (does
    not abort on) an individual malformed champion row."""
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
    except _LOAD_ERRORS as exc:
        log.warning("ban-suggestions: ddragon_champions load failed: %s", exc)
        return None
    data = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        log.warning("ban-suggestions: ddragon_champions has no champion map")
        return None
    name_to_id: dict[str, int] = {}
    id_to_slug: dict[int, str] = {}
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        name = entry.get("name")
        slug = entry.get("id")
        if not isinstance(name, str) or not name:
            continue
        cid = _champ_key(key)
        if cid is None:
            continue
        for variant in _name_variants(name):
            name_to_id[variant] = cid
        if isinstance(slug, str) and slug:
            name_to_id[slug] = cid                     # DDragon slug ("KaiSa")
            id_to_slug[cid] = slug
    if not name_to_id:
        log.warning("ban-suggestions: ddragon_champions yielded no champions")
        return None
    return name_to_id, id_to_slug


def _load_champ_index() -> tuple[dict[str, int], dict[int, str]]:
    global _CHAMP_INDEX
    cached = _CHAMP_INDEX
    if cached is not None:
        return cached
    with _INDEX_LOCK:
        if _CHAMP_INDEX is None:
            built = _build_champ_index()
            if built is None:
                return {}, {}                          # not cached: retry next call
            _CHAMP_INDEX = built
        return _CHAMP_INDEX


def _load_name_to_id() -> dict[str, int]:
    """Display-name -> numeric-id index. Stores apostrophe + space
    variants under the same id so 'Kai'Sa' and 'KaiSa' both resolve."""
    return _load_champ_index()[0]


def _load_id_to_slug() -> dict[int, str]:
    """Numeric-id -> DDragon slug, the champion icon file name."""
    return _load_champ_index()[1]


def _parse_int_csv(raw: str) -> set[int]:
    """Positive decimal champion ids from a comma list; anything else
    (signs, underscores, decimals, words, zero) is ignored."""
    out: set[int] = set()
    for chunk in (raw or "").split(","):
        value = _positive_id(chunk.strip())
        if value is not None:
            out.add(value)
    return out


def _parse_top(raw: str) -> int:
    try:
        return max(_TOP_MIN, min(_TOP_MAX, int(raw)))
    except ValueError:
        return _TOP_DEFAULT


def _load_bans_file() -> dict:
    try:
        return json.loads(_BANS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("ban-suggestions: %s missing", _BANS_PATH)
    except _LOAD_ERRORS as exc:
        log.warning("ban-suggestions: load failed: %s", exc)
    return dict(_EMPTY_BANS)


def _icon_slug(cid: int, name: str, id_to_slug: dict[int, str]) -> str:
    slug = id_to_slug.get(cid)
    if slug:
        return slug
    # Fallback for a champion the DDragon index does not carry.
    return name.replace(" ", "").replace("'", "").replace(".", "")


def _resolve(name: str, idx: dict[str, int]) -> int | None:
    for variant in _name_variants(name):
        cid = idx.get(variant)
        if cid is not None:
            return cid
    return None


def _serve_ban_suggestions(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        excluded = _parse_int_csv((qs.get("exclude") or [""])[0])
        top = _parse_top((qs.get("top") or [str(_TOP_DEFAULT)])[0])

        bans_doc = _load_bans_file()
        if not isinstance(bans_doc, dict):
            log.warning("ban-suggestions: bans file is not a JSON object")
            bans_doc = {}
        top_bans = bans_doc.get("top_bans")
        if not isinstance(top_bans, list):
            if top_bans is not None:
                log.warning("ban-suggestions: top_bans is not a list")
            top_bans = []
        patch = bans_doc.get("patch")
        if not isinstance(patch, str) or not patch:
            patch = "unknown"

        idx = _load_name_to_id()
        id_to_slug = _load_id_to_slug()

        suggestions: list[dict] = []
        seen: set[int] = set()
        for rank, name in enumerate(top_bans, start=1):
            if len(suggestions) >= top:
                break
            if not isinstance(name, str) or not name:
                continue
            cid = _resolve(name, idx)
            if cid is None:
                log.debug("ban-suggestions: unresolved name %r", name)
                continue
            if cid in excluded or cid in seen:
                continue
            seen.add(cid)
            suggestions.append({
                "champId": cid,
                "name":    name,
                "icon":    f"/icons/champions/{_icon_slug(cid, name, id_to_slug)}.png",
                # OQ9 (QA26 remainder): 1-based meta-list rank - the
                # why-banned label source. Kept TRUE to the source list
                # (not re-numbered post-filter). Additive, END of dict.
                "rank":    rank,
            })

        h._send(200, json.dumps({
            "ok": True,
            "patch": patch,
            "suggestions": suggestions,
            "excluded_count": len(excluded),
            "fell_back": len(suggestions) < top,
        }).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-select/ban-suggestions: %s", exc)
        # Raw exception text stays in the log only.
        h._send(500, json.dumps(
            {"ok": False, "error": "internal error - see logs"}).encode(),
            "application/json")


def _equals(p: str):
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/champ-select/ban-suggestions"), _serve_ban_suggestions),
]
POST_ROUTES: list = []
