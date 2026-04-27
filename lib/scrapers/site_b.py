"""aggregator B scraper primitive.

URL shape (2026): https://aggregator-b.invalid/lol/champions/<champ>/build
ARAM: /lol/champions/aram/<champ>-aram
Arena: /lol/champions/arena/<champ>-arena-build
"""
from __future__ import annotations

from lib.scrapers._base import ScraperBase


class UggScraper(ScraperBase):
    site = "ugg"
    base_url = "https://aggregator-b.invalid"

    MODE_PATH = {
        "sr": "lol/champions/{champ}/build",
        "aram": "lol/champions/aram/{champ}-aram",
        "arena": "lol/champions/arena/{champ}-arena-build",
        "brawl": "lol/champions/{champ}/build",  # aggregator B rarely separates brawl; SR build is the fallback
    }

    def fetch_champion(self, champ: str, mode: str = "sr", role: str | None = None) -> str:
        champ = champ.strip().lower().replace(" ", "").replace("'", "")
        tmpl = self.MODE_PATH.get(mode)
        if tmpl is None:
            raise ValueError(f"unsupported mode: {mode}")
        path = tmpl.format(champ=champ)
        if role and mode == "sr":
            path += f"?role={role}"
        cache_key = f"{champ}_{mode}" + (f"_{role}" if role and mode == "sr" else "")
        return self.fetch(path, cache_key=cache_key, ext="html")
