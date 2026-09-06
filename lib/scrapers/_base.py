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

# RM-354. A bot wall is served as HTTP 200, so `status >= 400` is not an
# acceptance test for the BODY. These are the interstitials the two shipped
# targets actually sit behind (Cloudflare on aggregator D, a JS challenge on
# aggregator B) plus the other three walls in common use. Each entry is a phrase
# specific to a challenge page, never a bare vendor name: "cloudflare" alone
# would fire on any page that links a Cloudflare-hosted asset.
#
# Measured 2026-09-06 against the six real pages cached on Legion
# (data/meta_build/scraped/{aggregator D,ugg}/*.html, 2.9M characters): zero
# markers matched, scanning each document WHOLE. That measurement is what
# licenses the whole-document scan below - a head-only prefix would miss a
# marker pushed down by a long preamble, and the false-positive risk the
# prefix was meant to bound turned out not to exist.
BOT_WALL_MARKERS: tuple[str, ...] = (
    "just a moment...",
    "checking your browser before accessing",
    "attention required! | cloudflare",
    "cf-browser-verification",
    "cf_chl_opt",
    "__cf_chl",
    "enable javascript and cookies to continue",
    "ddos-guard",
    "please verify you are a human",
    "verifying you are human",
    "/_incapsula_resource",
    "px-captcha",
    "captcha-delivery.com",
)

# A floor, not a size estimate. It exists to catch the empty and truncated
# 200s that carry no marker at all; the real build pages this package fetches
# are 330KB-666KB, so nothing legitimate is anywhere near it.
MIN_BODY_BYTES = 512


class UnacceptableBody(RuntimeError):
    """A 2xx response whose body is not the document that was requested.

    Deliberately a ``RuntimeError`` subclass. The one production caller,
    ``agents/agent2_backend/pipeline/orchestrator.py:149`` and ``:162``,
    already catches ``RuntimeError`` from ``fetch``, so an interstitial now
    takes the same per-source degradation path an HTTP 500 always did with
    no caller change.
    """


def _reject_reason(text: str, body: bytes) -> str | None:
    """Why this 2xx body must not be cached, or None if it is acceptable.

    Returns a short stamp-safe token, never a raw remote string - the reason
    is written into ``_last_fetch.json`` and read by health probes.

    Markers are checked BEFORE the length floor, because the token is a
    diagnosis and both can be true of the same body: a short interstitial
    reported as "too_short" tells an operator nothing, where "bot_wall" tells
    them to back off or rotate the user agent. Measured while writing the
    RM-354 tests - the row's own filed example,
    ``<html><title>Just a moment...</title></html>``, is 44 bytes, so a
    floor-first order labelled the canonical bot wall a truncation.
    """
    lowered = text.lower()
    for marker in BOT_WALL_MARKERS:
        if marker in lowered:
            return "bot_wall"
    if len(body) < MIN_BODY_BYTES:
        return f"too_short_{len(body)}b"
    return None


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

    def can_fetch(self, url: str, user_agent: str = "Amberstone/3.0") -> bool:
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
        # RM-354. The body is judged BEFORE it reaches the cache. Writing
        # first and validating after would already have destroyed the
        # previous good page - `cache_path` is only ever a write target in
        # this class, so there is no read-back to recover it from.
        reason = _reject_reason(text, resp.body)
        if reason is not None:
            self.stamp_last_fetch(cache_key, status=reason, bytes=len(resp.body))
            self._log.warning(
                "%s %s: HTTP %d but body rejected (%s) - cache left intact",
                self.site, url, resp.status, reason,
            )
            raise UnacceptableBody(
                f"{self.site} {url}: HTTP {resp.status} but body rejected ({reason})")
        _atomic_write_text(self.cache_path(cache_key, ext=ext), text)
        self.stamp_last_fetch(cache_key, status="ok", bytes=len(resp.body))
        return text
