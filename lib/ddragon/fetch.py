"""DDragon static data fetcher.

DDragon is Riot's CDN-hosted, versioned static data bundle. Endpoints:
  https://ddragon.leagueoflegends.com/api/versions.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/champion.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/item.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/runesReforged.json
  https://ddragon.leagueoflegends.com/cdn/<ver>/data/en_US/summoner.json

Cached to ``data/meta_build/ddragon/<ver>/`` using atomic writes (a non-default
locale under ``<ver>/<locale>/``, so it never overwrites the en_US files every
RC consumer reads). Agent 6 schedules
refresh on patch-day triggers; direct call sites use ``fetch_all()`` to refresh
all bundles or ``DDragon(...)`` for per-bundle control.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.polled_json import atomic_write_bytes
from lib.http import get_client
from tools.ddragon_mirror_refresh import prune_stale_versions, validate_version

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
DEFAULT_LOCALE = "en_US"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_ROOT = _PROJECT_ROOT / "data" / "meta_build" / "ddragon"

logger = logging.getLogger("lib.ddragon")

# DDragon locales are `<lang>_<REGION>` (en_US, ko_KR, zh_CN, ...). The value is
# a URL segment and, for a non-default locale, a cache directory name.
_LOCALE_RE = re.compile(r"[a-z]{2}_[A-Z]{2}")

# The bundles whose document is a list; every other bundle is `{"data": {...}}`.
_LIST_BUNDLES = frozenset({"runesReforged"})


class DDragonBodyError(RuntimeError, ValueError):
    """A DDragon body that is not the requested document.

    BOTH bases on purpose: RM-352 callers degrade on RuntimeError, and the
    RM-353 contract (a malformed versions body) has always surfaced as
    ValueError, so neither existing catcher changes.
    """


def validate_locale(locale: Any) -> str:
    """Return `locale` if it is a DDragon `xx_YY` locale string, else raise."""
    if not isinstance(locale, str) or not _LOCALE_RE.fullmatch(locale):
        raise ValueError(f"refusing unsafe DDragon locale {locale!r} - expected xx_YY")
    return locale


def _json_body(resp, what: str) -> Any:
    # A 200 that is not JSON (a captive-portal or CDN HTML page) used to escape
    # as JSONDecodeError, outside the RuntimeError contract below.
    try:
        return resp.json()
    except ValueError as exc:
        raise DDragonBodyError(f"DDragon {what}: 200 body is not JSON") from exc


def _atomic_write_json(path: Path, data: Any) -> None:
    # RM-258 residual: the scratch name, fsync, WinError 5 retry and scratch
    # cleanup are core.polled_json's (the old fixed `<dest>.tmp` and bare
    # os.replace broke on a squatter and leaked the scratch on a failed swap).
    # Bytes, not write_text - this writes the same TRACKED, eol=lf-pinned files
    # as tools/ddragon_mirror_refresh._atomic_write_json, where write_text put
    # CRLF on disk while git's index normalization kept `git status` clean. The
    # compact separators leave no LF in today's payload, so this is byte-for-byte
    # identical now; it is the writer, not the current payload, that has to be
    # safe, because adding an `indent=` here would silently reintroduce the
    # defect against files nothing would flag as dirty.
    atomic_write_bytes(path, json.dumps(data, separators=(",", ":")).encode("utf-8"))


def latest_version(client=None) -> str:
    client = client or get_client()
    resp = client.get(f"{DDRAGON_BASE}/api/versions.json")
    # RM-352: HttpClient RETURNS a Response for 4xx/5xx instead of raising, so
    # without this a maintenance page or a bot interstitial reached json() and
    # surfaced as JSONDecodeError - a class no caller here catches. Same guard
    # and same message shape as _pull() below.
    if resp.status != 200:
        raise RuntimeError(f"DDragon versions: HTTP {resp.status}")
    versions = _json_body(resp, "versions")
    # A dict / int / null / bare string body used to reach `versions[0]` and
    # raise KeyError or TypeError (or index a string to one character).
    if not isinstance(versions, list):
        raise DDragonBodyError(
            f"DDragon returned no versions list ({type(versions).__name__})")
    if not versions:
        raise DDragonBodyError("DDragon returned empty versions list")
    # RM-353: entry [0] is CDN input. A JSON *string* body makes this a single
    # character ("maintenance" -> "m"); a list element can be "../../evil" or
    # an anchored "C:/...". This function is exported from lib/ddragon, so the
    # guard belongs here as well as at the path join in DDragon.__init__.
    return validate_version(versions[0])


def _is_ddragon_payload(data: Any, name: str) -> bool:
    """champion / item / summoner are `{"data": {...}}`; runesReforged is a
    non-empty list of style dicts. Anything else - including the RIGHT shape
    for the WRONG bundle - is not the requested document."""
    if name in _LIST_BUNDLES:
        return (isinstance(data, list) and len(data) > 0
                and all(isinstance(row, dict) for row in data))
    return (isinstance(data, dict) and isinstance(data.get("data"), dict)
            and len(data["data"]) > 0)


class DDragon:
    """Single-version DDragon pull + cache."""

    def __init__(self, version: str | None = None, locale: str = DEFAULT_LOCALE) -> None:
        # Validated before anything else: it is a URL segment and, for a
        # non-default locale, a cache directory name.
        self._locale = validate_locale(locale)
        self._client = get_client()
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
        # A non-default locale gets its own subdirectory: sharing the en_US
        # path let a ko_KR pull overwrite the files RC's consumers read.
        if self._locale == DEFAULT_LOCALE:
            return self._root / f"{name}.json"
        return self._root / self._locale / f"{name}.json"

    def _pull(self, name: str) -> dict:
        url = f"{DDRAGON_BASE}/cdn/{self._version}/data/{self._locale}/{name}.json"
        resp = self._client.get(url)
        if resp.status != 200:
            raise RuntimeError(f"DDragon {name}: HTTP {resp.status}")
        data = _json_body(resp, name)
        # RM-373: the parse gates ENCODING, not SHAPE - a well-formed
        # {"error": "blocked"} or "maintenance" parsed fine and was written
        # over the cache, which _read_cached then served forever. Require the
        # DDragon envelope before the write.
        if not _is_ddragon_payload(data, name):
            raise DDragonBodyError(
                f"DDragon {name}: 200 body is not a DDragon payload "
                f"({type(data).__name__}) - cache left unchanged")
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
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning(
                "ddragon cache %s corrupt (%s) - re-pulling", p.name, e,
            )
            return None
        # The read-side twin of RM-373: a file that parses but is not the
        # bundle (a body cached before the write gate, or the wrong document
        # type) was served forever. Re-pull, which also repairs the file.
        if not _is_ddragon_payload(data, name):
            logger.warning(
                "ddragon cache %s is not a %s payload (%s) - re-pulling",
                p.name, name, type(data).__name__,
            )
            return None
        return data

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
