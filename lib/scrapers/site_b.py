"""Site B build-page scraper primitive.

URL shape (2026): <base>/lol/champions/<champ>/build
ARAM: /lol/champions/aram/<champ>-aram
Arena: /lol/champions/arena/<champ>-arena-build

The host itself is operator configuration (``site_b_base_url`` in
``config/external_sources.json``), resolved on every access rather than
frozen at import, so an install can point this somewhere else - or nowhere -
without editing the module.
"""
from __future__ import annotations

from typing import ClassVar

from core import external_sources
from lib.scrapers._base import ScraperBase, champion_slug, mode_template, query_token


class SiteBScraper(ScraperBase):
    site = "site_b"

    MODE_PATH: ClassVar[dict] = {
        "sr": "lol/champions/{champ}/build",
        "aram": "lol/champions/aram/{champ}-aram",
        "arena": "lol/champions/arena/{champ}-arena-build",
        # This source rarely separates brawl; the SR build is the fallback.
        "brawl": "lol/champions/{champ}/build",
    }

    @property
    def base_url(self) -> str:
        return external_sources.value("site_b_base_url")

    def fetch_champion(self, champ: str, mode: str = "sr", role: str | None = None) -> str:
        """Fetch champion build page HTML for the requested mode.

        ``champ``, ``mode`` and (for sr only) ``role`` are checked by
        ``lib.scrapers._base`` before any URL or cache name is built from
        them; a bad one raises ``InvalidTarget`` with no I/O (S144-T-599).
        """
        slug = champion_slug(champ)
        path = mode_template(self.MODE_PATH, mode).format(champ=slug)
        token = query_token(role, "role") if mode == "sr" else None
        if token is not None:
            path += f"?role={token}"
        cache_key = f"{slug}_{mode}" + (f"_{token}" if token is not None else "")
        return self.fetch(path, cache_key=cache_key, ext="html")
