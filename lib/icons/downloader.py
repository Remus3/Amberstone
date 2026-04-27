"""DDragon icon downloader.

Fetches PNG assets from:
  https://ddragon.leagueoflegends.com/cdn/<ver>/img/champion/<Name>.png
  https://ddragon.leagueoflegends.com/cdn/<ver>/img/spell/<SpellId>.png
  https://ddragon.leagueoflegends.com/cdn/<ver>/img/item/<itemId>.png
  https://ddragon.leagueoflegends.com/cdn/img/perk-images/Styles/<icon>      (runes — version-less)

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
            if not img:
                continue
            url = f"{DDRAGON_CDN}/{self._version}/img/champion/{img}"
            if self._download(url, out / img, force):
                n += 1
        return n

    def spells(self, force: bool = False) -> int:
        data = self._dd.summoner_spells()
        out = ICONS_ROOT / "spell"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for key, meta in data.get("data", {}).items():
            img = (meta.get("image") or {}).get("full")
            if not img:
                continue
            url = f"{DDRAGON_CDN}/{self._version}/img/spell/{img}"
            if self._download(url, out / img, force):
                n += 1
        return n

    def items(self, force: bool = False) -> int:
        data = self._dd.items()
        out = ICONS_ROOT / "item"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for item_id, meta in data.get("data", {}).items():
            img = (meta.get("image") or {}).get("full")
            if not img:
                continue
            url = f"{DDRAGON_CDN}/{self._version}/img/item/{img}"
            if self._download(url, out / img, force):
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
                url = f"{DDRAGON_CDN}/img/{icon}"
                target = out / Path(icon).name
                if self._download(url, target, force):
                    n += 1
            for slot in tree.get("slots", []):
                for rune in slot.get("runes", []):
                    icon = rune.get("icon")
                    if not icon:
                        continue
                    url = f"{DDRAGON_CDN}/img/{icon}"
                    target = out / Path(icon).name
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
