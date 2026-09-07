"""Meta-data scrapers. All network IO goes through lib.http only.

Each scraper:
  - Respects robots.txt (fetched once per session, cached in-memory).
  - Caches raw payloads to data/meta_build/scraped/<site>/<champion>_<mode>.html (or .json).
  - Stamps _last_fetch.json with per-target ISO timestamps.
  - Returns structured dicts after parsing.

Agent 6 owns reweighting and circuit-trip rules. This module only surfaces
signals (Blocked, CircuitOpen, parse errors) - it does not decide policy.
"""
from lib.scrapers.site_b import SiteBScraper
from lib.scrapers.site_d import SiteDScraper

__all__ = ["SiteBScraper", "SiteDScraper"]
