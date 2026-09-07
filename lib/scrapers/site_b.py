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

from core import external_sources
from lib.scrapers._base import ScraperBase


class SiteBScraper(ScraperBase):
    site = "site_b"

    MODE_PATH = {
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
        champ = champ.strip().lower().replace(" ", "").replace("'", "")
        tmpl = self.MODE_PATH.get(mode)
        if tmpl is None:
            raise ValueError(f"unsupported mode: {mode}")
        path = tmpl.format(champ=champ)
        if role and mode == "sr":
            path += f"?role={role}"
        cache_key = f"{champ}_{mode}" + (f"_{role}" if role and mode == "sr" else "")
        return self.fetch(path, cache_key=cache_key, ext="html")
