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

from core import external_sources
from lib.scrapers._base import ScraperBase


class SiteDScraper(ScraperBase):
    site = "site_d"

    MODE_PATH = {
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
        """
        champ = champ.strip().lower().replace(" ", "").replace("'", "")
        path_tmpl = self.MODE_PATH.get(mode)
        if path_tmpl is None:
            raise ValueError(f"unsupported mode: {mode}")
        path = path_tmpl.format(champ=champ)
        if lane and mode == "sr":
            path += f"?lane={lane}"
        cache_key = f"{champ}_{mode}" + (f"_{lane}" if lane and mode == "sr" else "")
        return self.fetch(path, cache_key=cache_key, ext="html")
