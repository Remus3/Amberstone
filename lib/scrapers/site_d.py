"""aggregator D scraper primitive.

This layer only fetches + caches raw HTML. Parsing into build objects is the
coach-side job (Agent 4) and will plug into the cached HTML from
``data/meta_build/scraped/site_d/``.

URL shape (2026): https://aggregator-d.invalid/lol/<champ>/build/?lane=<lane>&mode=<mode>
Mode mapping: aram, arena, default (SR), bravebrawl, etc.
"""
from __future__ import annotations

from lib.scrapers._base import ScraperBase


class SiteDScraper(ScraperBase):
    site = "aggregator D"
    base_url = "https://aggregator-d.invalid"

    MODE_PATH = {
        "sr": "lol/{champ}/build/",
        "aram": "lol/{champ}/aram/build/",
        "arena": "lol/{champ}/arena/build/",
        "brawl": "lol/{champ}/bravebrawl/build/",
    }

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
