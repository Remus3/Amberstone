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
"""
from __future__ import annotations

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


def _int_id(raw) -> int | None:
    """Positive int from an int or an ASCII-digit string, else None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and re.fullmatch(r"[0-9]{1,9}", raw):
        return int(raw) or None
    return None


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
        if isinstance(ver, str) and re.fullmatch(r"[0-9.]{1,12}", ver):
            d = base / ver / "champion_detail"
            if d.is_dir():
                return d
        vers = sorted((p for p in base.iterdir()
                       if (p / "champion_detail").is_dir()),
                      key=lambda p: [int(x) if x.isdigit() else 0
                                     for x in p.name.split(".")])
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
        name = s.get("name")
        num = s.get("num")
        out.append({
            "id": sid,
            "num": num if isinstance(num, int) and not isinstance(num, bool) else 0,
            "name": name if isinstance(name, str) and name.strip() else str(sid),
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
    raw = entry.get("chromas") if isinstance(entry, dict) else None
    out = []
    for c in raw if isinstance(raw, list) else []:
        cid = _int_id(c.get("id")) if isinstance(c, dict) else None
        if cid is None:
            continue
        nm = c.get("name")
        out.append({"id": cid,
                    "name": nm if isinstance(nm, str) and nm.strip() else str(cid)})
    return out


def selected_skin_from_lcu(payload, *, cell_id=None) -> int | None:
    """Selected skin id from a champ-select payload, else None.

    Accepts the session dict (``myTeam[].selectedSkinId``; ``cell_id`` picks
    the local player, else ``localPlayerCellId``) or a skin-carousel list
    (the entry flagged ``selected``). A zero / junk id is None.
    """
    if isinstance(payload, list):
        for it in payload:
            if isinstance(it, dict) and it.get("selected") is True:
                return _int_id(it.get("id"))
        return None
    if not isinstance(payload, dict):
        return None
    cell = cell_id if cell_id is not None else payload.get("localPlayerCellId")
    team = payload.get("myTeam")
    for p in team if isinstance(team, list) else []:
        if isinstance(p, dict) and p.get("cellId") == cell:
            return _int_id(p.get("selectedSkinId"))
    return None


def refresh_cdragon_cache(*, url: str = CDRAGON_URL, cache: Path | None = None,
                          timeout: float = 15.0) -> bool:
    """Fetch CDragon skins.json, keep id -> {name, chromas[]}, write atomically.

    Returns False (never raises) on any network or parse failure. On-demand
    only; art paths are dropped, so no Riot art is stored.
    """
    target = cache if cache is not None else CDRAGON_CACHE
    if not url.startswith("https://"):
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            doc = json.loads(r.read(64 * 1024 * 1024).decode("utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        log.warning("skins: cdragon fetch failed: %s", exc)
        return False
    if not isinstance(doc, dict):
        return False
    slim = {}
    for v in doc.values():
        sid = _int_id(v.get("id")) if isinstance(v, dict) else None
        if sid is None:
            continue
        chromas = [{"id": c.get("id"), "name": c.get("name")}
                   for c in (v.get("chromas") or []) if isinstance(c, dict)]
        slim[str(sid)] = {"name": v.get("name"), "chromas": chromas}
    try:
        # core.polled_json: per-writer scratch name, fsync, retry, and the
        # scratch is never left behind (RM-258 / RM-261); bytes, so no CRLF.
        polled_json.atomic_write_bytes(
            target, json.dumps(slim, separators=(",", ":")).encode("utf-8"))
    except OSError as exc:
        log.warning("skins: cache write failed: %s", exc)
        return False
    return True
