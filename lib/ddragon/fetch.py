"""DDragon static data fetcher.

DDragon is Riot's CDN-hosted, versioned static data bundle. Endpoints:
  https://ddragon.leagueoflegends.com/api/versions.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/champion.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/item.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/runesReforged.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/summoner.json

Cached to ``data/meta_build/ddragon/`` using atomic writes. Agent 6 schedules
refresh on patch-day triggers; direct call sites use ``fetch_all()`` to refresh
all bundles or ``DDragon(...)`` for per-bundle control.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from lib.http import get_client
from tools.ddragon_mirror_refresh import prune_stale_versions, validate_version

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
DEFAULT_LOCALE = "en_US"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_ROOT = _PROJECT_ROOT / "data" / "meta_build" / "ddragon"

logger = logging.getLogger("lib.ddragon")


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def latest_version(client=None) -> str:
    client = client or get_client()
    resp = client.get(f"{DDRAGON_BASE}/api/versions.json")
    # RM-352: HttpClient RETURNS a Response for 4xx/5xx instead of raising, so
    # without this a maintenance page or a bot interstitial reached json() and
    # surfaced as JSONDecodeError - a class no caller here catches. Same guard
    # and same message shape as _pull() below.
    if resp.status != 200:
        raise RuntimeError(f"DDragon versions: HTTP {resp.status}")
    versions = resp.json()
    if not versions:
        raise RuntimeError("DDragon returned empty versions list")
    # RM-353: entry [0] is CDN input. A JSON *string* body makes this a single
    # character ("maintenance" -> "m"); a list element can be "../../evil" or
    # an anchored "C:/...". This function is exported from lib/ddragon, so the
    # guard belongs here as well as at the path join in DDragon.__init__.
    return validate_version(versions[0])


class DDragon:
    """Single-version DDragon pull + cache."""

    def __init__(self, version: str | None = None, locale: str = DEFAULT_LOCALE) -> None:
        self._client = get_client()
        self._locale = locale
        # RM-353: validate BEFORE the join, not after. `version` may be an
        # explicit caller argument (fetch_all, IconDownloader, the agent2
        # orchestrator) that never passed through latest_version, and pathlib
        # does not normalise - on Windows an anchored segment replaces
        # CACHE_ROOT outright, so the mkdir below would land anywhere.
        self._version = validate_version(version or latest_version(self._client))
        self._root = CACHE_ROOT / self._version
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def version(self) -> str:
        return self._version

    @property
    def cache_dir(self) -> Path:
        return self._root

    def _cached(self, name: str) -> Path:
        return self._root / f"{name}.json"

    def _pull(self, name: str) -> dict:
        url = f"{DDRAGON_BASE}/cdn/{self._version}/data/{self._locale}/{name}.json"
        resp = self._client.get(url)
        if resp.status != 200:
            raise RuntimeError(f"DDragon {name}: HTTP {resp.status}")
        data = resp.json()
        _atomic_write_json(self._cached(name), data)
        logger.info("ddragon %s@%s cached (%d bytes)", name, self._version, len(resp.body))
        return data

    # AUDIT P-audit3-m02 (2026-04-22): wrap every cache read in the same
    # stale-while-revalidate pattern - a corrupt/partial cache file used
    # to crash the caller (every coach hits this path). Now we log at
    # WARNING and re-pull.
    def _read_cached(self, name: str):
        p = self._cached(name)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning(
                "ddragon cache %s corrupt (%s) - re-pulling", p.name, e,
            )
            return None

    def champions(self, refresh: bool = False) -> dict:
        if not refresh:
            cached = self._read_cached("champion")
            if cached is not None:
                return cached
        return self._pull("champion")

    def items(self, refresh: bool = False) -> dict:
        if not refresh:
            cached = self._read_cached("item")
            if cached is not None:
                return cached
        return self._pull("item")

    def runes(self, refresh: bool = False) -> list:
        if not refresh:
            cached = self._read_cached("runesReforged")
            if cached is not None:
                return cached
        return self._pull("runesReforged")

    def summoner_spells(self, refresh: bool = False) -> dict:
        if not refresh:
            cached = self._read_cached("summoner")
            if cached is not None:
                return cached
        return self._pull("summoner")

    def pull_all(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "champions": self.champions(refresh=True),
            "items": self.items(refresh=True),
            "runes": self.runes(refresh=True),
            "summoner_spells": self.summoner_spells(refresh=True),
        }


def fetch_all(version: str | None = None) -> dict:
    dd = DDragon(version=version)
    dd.pull_all()
    index_path = CACHE_ROOT / "_index.json"
    _atomic_write_json(
        index_path,
        {
            "latest_pulled": dd.version,
            "locale": DEFAULT_LOCALE,
            "bundles": ["champion", "item", "runesReforged", "summoner"],
        },
    )
    # Retention (item 397, gemini-confirmed current+previous window): the
    # bundle cache otherwise accretes one tracked dir per patch forever.
    # Prune failure must never break a successful fetch.
    try:
        pruned = prune_stale_versions(dd.version, web_dir=CACHE_ROOT)
        if pruned:
            logger.info("pruned stale meta_build ddragon cache dirs: %s", pruned)
    except OSError as exc:
        logger.warning("meta_build cache prune skipped: %s", exc)
    return {"version": dd.version, "cache_dir": str(dd.cache_dir)}
