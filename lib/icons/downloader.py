"""DDragon icon downloader.

Fetches PNG assets from:
  https://ddragon.leagueoflegends.com/cdn/<ver>/img/champion/<Name>.png
  https://ddragon.leagueoflegends.com/cdn/<ver>/img/spell/<SpellId>.png
  https://ddragon.leagueoflegends.com/cdn/<ver>/img/item/<itemId>.png
  https://ddragon.leagueoflegends.com/cdn/img/perk-images/Styles/<icon>      (runes - version-less)

Caches to ``data/icons/<kind>/<file>.png`` with atomic writes. Idempotent:
skips already-cached files unless ``force=True``.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from lib.ddragon import DDragon
from lib.http import HttpError, get_client

logger = logging.getLogger("lib.icons")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ICONS_ROOT = _PROJECT_ROOT / "data" / "icons"

DDRAGON_CDN = "https://ddragon.leagueoflegends.com/cdn"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _safe_basename(img: str) -> str | None:
    """AUDIT 2026-04-28 (P-audit4-m01): defense-in-depth for DDragon icon
    filenames. A future Riot CDN regression - or an attacker who
    successfully MITMs DDragon (TLS bypass) - could return ``image.full``
    of ``../../../etc/x.png``. We accept ONLY a plain basename: no path
    separators, no leading dot, no drive letter.

    Returns the validated basename, or None to reject."""
    if not img or not isinstance(img, str):
        return None
    if "/" in img or "\\" in img:
        return None
    if img in (".", "..") or img.startswith(".") or img.startswith("..."):
        return None
    # Strip control chars + null bytes; reject if anything was stripped.
    cleaned = "".join(ch for ch in img if ch.isprintable() and ch != "\x00")
    if cleaned != img:
        return None
    # Final sanity: basename must equal input (catches ":" device paths
    # like "C:foo" on Windows that os.path treats as having a drive).
    if os.path.basename(img) != img:
        return None
    return img


def _safe_relpath(rel: str | None) -> str | None:
    """Validate a MULTI-SEGMENT relative asset path (RM-359: rune icons).

    DDragon rune icons are referenced like
    ``perk-images/Styles/Domination/Electrocute/Electrocute.png``, so
    ``_safe_basename`` cannot be applied to the whole string - it rejects
    every separator and would reduce ``runes()`` to a permanent no-op.
    Instead require every SEGMENT to pass ``_safe_basename``, which rejects
    ``.``, ``..``, dotfiles, backslashes, control characters and drive
    prefixes wherever they appear in the path.

    This mirrors ``tools/ddragon_mirror_refresh.py:_safe_relpath``, the live
    twin that already guards the mirror refresh; only this library copy had
    been left without it.

    Returns the validated relative path, or None to reject.
    """
    if not rel or not isinstance(rel, str):
        return None
    if "\\" in rel or rel.startswith("/"):
        return None
    parts = rel.split("/")
    if not parts:
        return None
    for p in parts:
        if _safe_basename(p) is None:
            return None
    return "/".join(parts)


class IconDownloader:
    def __init__(self, version: str | None = None) -> None:
        self._client = get_client()
        self._dd = DDragon(version=version)
        self._version = self._dd.version

    @property
    def version(self) -> str:
        return self._version

    def _download(self, url: str, target: Path, force: bool) -> bool:
        if target.exists() and not force:
            return False
        try:
            resp = self._client.get(url)
        except HttpError as e:
            logger.warning("icon %s: %s", url, e)
            return False
        if resp.status != 200:
            logger.warning("icon %s: HTTP %d", url, resp.status)
            return False
        _atomic_write_bytes(target, resp.body)
        return True

    def champions(self, force: bool = False) -> int:
        data = self._dd.champions()
        out = ICONS_ROOT / "champion"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for key, meta in data.get("data", {}).items():
            img = (meta.get("image") or {}).get("full")
            bn = _safe_basename(img) if img else None
            if not bn:
                if img:
                    logger.warning("rejecting suspicious champion icon name %r for %s", img, key)
                continue
            url = f"{DDRAGON_CDN}/{self._version}/img/champion/{bn}"
            if self._download(url, out / bn, force):
                n += 1
        return n

    def spells(self, force: bool = False) -> int:
        data = self._dd.summoner_spells()
        out = ICONS_ROOT / "spell"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for key, meta in data.get("data", {}).items():
            img = (meta.get("image") or {}).get("full")
            bn = _safe_basename(img) if img else None
            if not bn:
                if img:
                    logger.warning("rejecting suspicious spell icon name %r for %s", img, key)
                continue
            url = f"{DDRAGON_CDN}/{self._version}/img/spell/{bn}"
            if self._download(url, out / bn, force):
                n += 1
        return n

    def items(self, force: bool = False) -> int:
        data = self._dd.items()
        out = ICONS_ROOT / "item"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for item_id, meta in data.get("data", {}).items():
            img = (meta.get("image") or {}).get("full")
            bn = _safe_basename(img) if img else None
            if not bn:
                if img:
                    logger.warning("rejecting suspicious item icon name %r for %s", img, item_id)
                continue
            url = f"{DDRAGON_CDN}/{self._version}/img/item/{bn}"
            if self._download(url, out / bn, force):
                n += 1
        return n

    def runes(self, force: bool = False) -> int:
        data = self._dd.runes()
        out = ICONS_ROOT / "rune"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for tree in data:
            icon = tree.get("icon")
            if icon:
                rel = _safe_relpath(icon)
                if not rel:
                    logger.warning("rejecting suspicious rune tree icon path %r", icon)
                else:
                    url = f"{DDRAGON_CDN}/img/{rel}"
                    target = out / Path(rel).name
                    if self._download(url, target, force):
                        n += 1
            for slot in tree.get("slots", []):
                for rune in slot.get("runes", []):
                    icon = rune.get("icon")
                    if not icon:
                        continue
                    rel = _safe_relpath(icon)
                    if not rel:
                        logger.warning("rejecting suspicious rune icon path %r", icon)
                        continue
                    url = f"{DDRAGON_CDN}/img/{rel}"
                    target = out / Path(rel).name
                    if self._download(url, target, force):
                        n += 1
        return n


def download_all(force: bool = False, version: str | None = None) -> dict:
    dl = IconDownloader(version=version)
    return {
        "version": dl.version,
        "champions": dl.champions(force=force),
        "spells": dl.spells(force=force),
        "items": dl.items(force=force),
        "runes": dl.runes(force=force),
    }
