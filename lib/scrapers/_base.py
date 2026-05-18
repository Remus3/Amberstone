"""Shared scraper primitives: robots.txt + response cache + last-fetch stamp."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from lib.http import Blocked, HttpError, get_client

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRAPED_ROOT = _PROJECT_ROOT / "data" / "meta_build" / "scraped"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2))


class ScraperBase:
    site: str = ""  # subclass must set
    base_url: str = ""  # subclass must set, scheme+host only

    def __init__(self, logger_name: str | None = None) -> None:
        assert self.site and self.base_url, "subclass must set site and base_url"
        self._client = get_client()
        self._robots: RobotFileParser | None = None
        self._robots_loaded = False
        self._cache_dir = SCRAPED_ROOT / self.site
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_fetch_path = SCRAPED_ROOT / "_last_fetch.json"
        self._log = logging.getLogger(logger_name or f"lib.scrapers.{self.site}")

    # ----- robots.txt -----------------------------------------------
    def _load_robots(self) -> None:
        if self._robots_loaded:
            return
        self._robots_loaded = True
        rp = RobotFileParser()
        url = f"{self.base_url.rstrip('/')}/robots.txt"
        try:
            resp = self._client.get(url, timeout=10.0)
            if resp.status == 200:
                rp.parse(resp.text().splitlines())
                self._robots = rp
                self._log.info("robots.txt loaded for %s", self.site)
            else:
                self._log.warning("robots.txt %s: HTTP %d - permissive fallback", self.site, resp.status)
        except (HttpError, Blocked) as e:
            self._log.warning("robots.txt fetch failed for %s: %s - permissive fallback", self.site, e)

    def can_fetch(self, url: str, user_agent: str = "RiotCommander/3.0") -> bool:
        self._load_robots()
        if self._robots is None:
            return True  # permissive fallback when robots.txt is unreachable
        return self._robots.can_fetch(user_agent, url)

    # ----- cache / stamping -----------------------------------------
    def cache_path(self, name: str, ext: str = "html") -> Path:
        safe = name.replace("/", "_").replace("\\", "_")
        return self._cache_dir / f"{safe}.{ext}"

    def stamp_last_fetch(self, key: str, status: str = "ok", **extra: Any) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            cur = json.loads(self._last_fetch_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            cur = {}
        bucket = cur.setdefault(self.site, {})
        entry: dict[str, Any] = {"ts": ts, "status": status}
        entry.update(extra)
        bucket[key] = entry
        _atomic_write_json(self._last_fetch_path, cur)

    # ----- fetch helper ---------------------------------------------
    def fetch(self, path: str, cache_key: str, ext: str = "html") -> str:
        url = path if path.startswith("http") else f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if not self.can_fetch(url):
            self.stamp_last_fetch(cache_key, status="robots_disallowed")
            raise PermissionError(f"robots.txt disallows {url} for {self.site}")
        try:
            resp = self._client.get(url)
        except (HttpError, Blocked) as e:
            self.stamp_last_fetch(cache_key, status="network_error", error=str(e))
            raise
        if resp.status >= 400:
            self.stamp_last_fetch(cache_key, status=f"http_{resp.status}")
            raise RuntimeError(f"{self.site} {url}: HTTP {resp.status}")
        text = resp.text()
        _atomic_write_text(self.cache_path(cache_key, ext=ext), text)
        self.stamp_last_fetch(cache_key, status="ok", bytes=len(resp.body))
        return text
