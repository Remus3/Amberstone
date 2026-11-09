"""Site D build-page scraper primitive.

This layer only fetches + caches raw HTML. Parsing into build objects is the
coach-side job (Agent 4) and will plug into the cached HTML from
``data/meta_build/scraped/site_d/``.

URL shape (2026): <base>/lol/<champ>/build/?lane=<lane>
Mode mapping: aram, arena, default (SR), bravebrawl, etc.

The host itself is operator configuration (``site_d_base_url`` in
``config/external_sources.json``), resolved on every access rather than
frozen at import, so an install can point this somewhere else - or nowhere -
without editing the module.
"""
from __future__ import annotations

from typing import ClassVar

from core import external_sources
from lib.scrapers._base import ScraperBase, champion_slug, mode_template, query_token


class SiteDScraper(ScraperBase):
    site = "site_d"

    MODE_PATH: ClassVar[dict] = {
        "sr": "lol/{champ}/build/",
        "aram": "lol/{champ}/aram/build/",
        "arena": "lol/{champ}/arena/build/",
        "brawl": "lol/{champ}/bravebrawl/build/",
    }

    @property
    def base_url(self) -> str:
        return external_sources.value("site_d_base_url")

    def fetch_champion(self, champ: str, mode: str = "sr", lane: str | None = None) -> str:
        """Fetch champion build page HTML for the requested mode.

        Returns raw HTML (also written to cache).

        ``champ``, ``mode`` and (for sr only) ``lane`` are checked by
        ``lib.scrapers._base`` before any URL or cache name is built from
        them; a bad one raises ``InvalidTarget`` with no I/O (S144-T-599).
        """
        slug = champion_slug(champ)
        path = mode_template(self.MODE_PATH, mode).format(champ=slug)
        token = query_token(lane, "lane") if mode == "sr" else None
        if token is not None:
            path += f"?lane={token}"
        cache_key = f"{slug}_{mode}" + (f"_{token}" if token is not None else "")
        return self.fetch(path, cache_key=cache_key, ext="html")
