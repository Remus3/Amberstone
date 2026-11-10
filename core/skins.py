"""LoL skins and chromas reader (s156 S4; spec docs/SKINS_CHROMAS.md).

Read-only. Sources, in order of authority:

- local DDragon ``champion_detail/<Champ>.json`` ``skins[]`` (gitignored mirror
  under ``data/meta_build/ddragon/<patch>/``): id, num, name, chromas flag;
- an OPTIONAL runtime-fetched CommunityDragon ``skins.json`` cache (gitignored
  ``data/cache/cdragon_skins.json``) that carries the chroma lists;
- the LCU champ-select session payload (selected skin id).

No art is read, fetched or stored here; only names and numeric ids. Every
public function degrades to an empty / None result on missing or bad data and
never raises on data problems.

Lane 8 true-audit (s144 cycle 235, S144-T-640..646) closed the places where
that promise was broken: the CDragon refresh raised on a non-list ``chromas``
field and on ``http.client.HTTPException`` (not an OSError), replaced a good
cache with ``{}`` when upstream had no usable row, accepted an https -> http
redirect, copied junk rows verbatim and wrote through a fixed ``.tmp``
sibling; ``_latest_detail_dir`` accepted ``latest_pulled = ".."`` and, in
its fallback scan, raised on a non-ASCII digit directory name and ranked
non-version directories; ``selected_skin_from_lcu`` matched
another player's row when the local cell id was absent or not an int.
Pinned by tests/test_skins_hardening_s144t640.py.
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import urllib.request
from pathlib import Path

from core import polled_json

log = logging.getLogger("rc.skins")

_APP_DIR = Path(__file__).resolve().parent.parent
_DDRAGON_ROOT = _APP_DIR / "data" / "meta_build" / "ddragon"
CDRAGON_CACHE = _APP_DIR / "data" / "cache" / "cdragon_skins.json"
CDRAGON_URL = ("https://raw.communitydragon.org/latest/plugins/"
               "rcp-be-lol-game-data/global/default/v1/skins.json")

_NAME_RE = re.compile(r"[A-Za-z0-9]{1,40}")
_READ_ERRORS = (OSError, ValueError, RecursionError)
# http.client.HTTPException (IncompleteRead, BadStatusLine, LineTooLong) is
# NOT an OSError, so a truncated or malformed response needs naming here.
_FETCH_ERRORS = (*_READ_ERRORS, http.client.HTTPException)
# A DDragon patch directory name: dot-separated ASCII digit groups. The old
# ``[0-9.]{1,12}`` admitted "..", which resolved outside the DDragon root.
_VERSION_RE = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,4}){0,3}")
_FETCH_CAP = 64 * 1024 * 1024


def _int_id(raw) -> int | None:
    """Positive int from an int or an ASCII-digit string, else None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and re.fullmatch(r"[0-9]{1,9}", raw):
        return int(raw) or None
    return None


def _cell_id(raw) -> int | None:
    """A champ-select cell id: a real int (bool and float rejected), else None."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    return None


def _label(raw, fallback_id: int) -> str:
    """A non-blank string name, else the id as text."""
    return raw if isinstance(raw, str) and raw.strip() else str(fallback_id)


def _chroma_rows(raw) -> list[dict]:
    """[{id, name}] from a raw chroma list; junk rows and non-lists drop out."""
    out = []
    for c in raw if isinstance(raw, list) else []:
        cid = _int_id(c.get("id")) if isinstance(c, dict) else None
        if cid is None:
            continue
        out.append({"id": cid, "name": _label(c.get("name"), cid)})
    return out


def _version_key(path: Path) -> list[int]:
    # Only called on names that passed _VERSION_RE (ASCII digit groups). The
    # old key used str.isdigit(), which is True for U+00B2 (superscript two) - int() raised.
    return [int(x) for x in path.name.split(".")]


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except _READ_ERRORS as exc:
        log.debug("skins: read %s failed: %s", path.name, exc)
        return None


def _latest_detail_dir(root: Path | None = None) -> Path | None:
    base = root if root is not None else _DDRAGON_ROOT
    try:
        idx = _read_json(base / "_index.json")
        ver = idx.get("latest_pulled") if isinstance(idx, dict) else None
        if isinstance(ver, str) and _VERSION_RE.fullmatch(ver):
            d = base / ver / "champion_detail"
            if d.is_dir():
                return d
        vers = sorted((p for p in base.iterdir()
                       if _VERSION_RE.fullmatch(p.name)
                       and (p / "champion_detail").is_dir()),
                      key=_version_key)
        return vers[-1] / "champion_detail" if vers else None
    except OSError:
        return None


def skins_for(champion: str, *, detail_dir: Path | None = None) -> list[dict]:
    """[{id, num, name, has_chromas}] for a champion slug, [] when unknown."""
    if not isinstance(champion, str) or not _NAME_RE.fullmatch(champion):
        return []
    d = detail_dir if detail_dir is not None else _latest_detail_dir()
    if d is None:
        return []
    doc = _read_json(Path(d) / f"{champion}.json")
    try:
        raw = doc["data"][champion]["skins"]
    except (TypeError, KeyError):
        return []
    out = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        sid = _int_id(s.get("id"))
        if sid is None:
            continue
        num = s.get("num")
        out.append({
            "id": sid,
            "num": num if isinstance(num, int) and not isinstance(num, bool) else 0,
            "name": _label(s.get("name"), sid),
            "has_chromas": s.get("chromas") is True,
        })
    return out


def skin_count(champion: str, *, detail_dir: Path | None = None) -> int:
    """Number of skins excluding the default (num 0)."""
    return sum(1 for s in skins_for(champion, detail_dir=detail_dir) if s["num"] > 0)


def skin_name(skin_id, champion: str, *, detail_dir: Path | None = None) -> str | None:
    sid = _int_id(skin_id)
    for s in skins_for(champion, detail_dir=detail_dir):
        if s["id"] == sid:
            return s["name"]
    return None


def chromas_for(skin_id, *, cache: Path | None = None) -> list[dict]:
    """[{id, name}] chromas of a skin from the CDragon cache, [] if absent."""
    sid = _int_id(skin_id)
    if sid is None:
        return []
    doc = _read_json(cache if cache is not None else CDRAGON_CACHE)
    entry = doc.get(str(sid)) if isinstance(doc, dict) else None
    return _chroma_rows(entry.get("chromas") if isinstance(entry, dict) else None)


def selected_skin_from_lcu(payload, *, cell_id=None) -> int | None:
    """Selected skin id from a champ-select payload, else None.

    Accepts the session dict (``myTeam[].selectedSkinId``; ``cell_id`` picks
    the local player, else ``localPlayerCellId``) or a skin-carousel list
    (the entry flagged ``selected``). A zero / junk id is None, and so is a
    missing or non-int cell id: it never falls through to another player's
    row (``None == None`` used to match the first row without a cellId).
    """
    if isinstance(payload, list):
        for it in payload:
            if isinstance(it, dict) and it.get("selected") is True:
                return _int_id(it.get("id"))
        return None
    if not isinstance(payload, dict):
        return None
    cell = _cell_id(cell_id if cell_id is not None
                    else payload.get("localPlayerCellId"))
    if cell is None:
        return None
    team = payload.get("myTeam")
    for p in team if isinstance(team, list) else []:
        if isinstance(p, dict) and _cell_id(p.get("cellId")) == cell:
            return _int_id(p.get("selectedSkinId"))
    return None


def refresh_cdragon_cache(*, url: str = CDRAGON_URL, cache: Path | None = None,
                          timeout: float = 15.0) -> bool:
    """Fetch CDragon skins.json, keep id -> {name, chromas[]}, write atomically.

    Returns False (never raises) on any network, protocol or parse failure,
    on a redirect that leaves https, on a body over 64 MiB and on a document
    with no usable row - the existing cache is then left untouched rather
    than replaced with ``{}``. Rows are normalised exactly as ``chromas_for``
    reads them. On-demand only; art paths are dropped, so no Riot art is
    stored. The write goes through ``core.polled_json`` (per-writer scratch
    name, bounded WinError-5 retry, scratch removed on failure).
    """
    target = cache if cache is not None else CDRAGON_CACHE
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            final = r.geturl() if hasattr(r, "geturl") else url
            if not isinstance(final, str) or not final.startswith("https://"):
                log.warning("skins: cdragon fetch left https; refused")
                return False
            body = r.read(_FETCH_CAP + 1)
        if len(body) > _FETCH_CAP:
            log.warning("skins: cdragon body over %d bytes; refused", _FETCH_CAP)
            return False
        doc = json.loads(body.decode("utf-8"))
    except _FETCH_ERRORS as exc:
        log.warning("skins: cdragon fetch failed: %s", exc)
        return False
    if not isinstance(doc, dict):
        return False
    slim = {}
    for v in doc.values():
        sid = _int_id(v.get("id")) if isinstance(v, dict) else None
        if sid is None:
            continue
        slim[str(sid)] = {"name": _label(v.get("name"), sid),
                          "chromas": _chroma_rows(v.get("chromas"))}
    if not slim:
        log.warning("skins: cdragon document had no usable row; cache kept")
        return False
    try:
        # core.polled_json: per-writer scratch name, fsync, retry, and the
        # scratch is never left behind (RM-258 / RM-261); bytes, so no CRLF.
        target.parent.mkdir(parents=True, exist_ok=True)
        polled_json.atomic_write_bytes(
            target, json.dumps(slim, separators=(",", ":")).encode("utf-8"))
    except OSError as exc:
        log.warning("skins: cache write failed: %s", exc)
        return False
    return True
