"""Agent 2 - Data pipeline orchestrator.

Ties together DDragon static data and the scraper primitives into a
per-mode coach cache under ``data/coach_cache/``. That cache is the
primary input for Agent 4's learn-and-adapt loop and for the coaches
themselves when they need build/rune/matchup hints.

Data flow per run:

    DDragon version + champion roster
        |
        v
    For each (champion, mode):
        SiteDScraper.fetch_champion(champ, mode)     ----+
        SiteBScraper.fetch_champion(champ, mode)     ----+---> merge
                                                         |
        Agent 4 curated JSON (if present)         -------+
        |
        v
    Aggregated build bundle per champ+mode
        |
        v
    data/coach_cache/<mode>.json    (atomic-written)

Respects:
  * lib.http rate limit (<= 1 req/sec per host; shared with any other
    Phase 3 code using lib.http).
  * Circuit breaker (owned by Agent 6 via source_quality.json).
  * Scraper robots.txt checks (lib.scrapers._base.ScraperBase).

Usage:

    # Full refresh (all modes, all champions) - heavy
    python -m agents.agent2_backend.pipeline.orchestrator --all

    # One mode
    python -m agents.agent2_backend.pipeline.orchestrator --mode aram

    # Demo: 3 champions only, one mode
    python -m agents.agent2_backend.pipeline.orchestrator --mode sr_draft --limit 3 --champs Ahri Lux Darius

    # Just refresh the DDragon cache (cheap, 4 HTTP calls)
    python -m agents.agent2_backend.pipeline.orchestrator --ddragon-only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Iterable

from lib.ddragon import DDragon, fetch_all as ddragon_fetch_all
from lib.http import Blocked, CircuitOpen, HttpError
from lib.scrapers import SiteBScraper, SiteDScraper

logger = logging.getLogger("agent2.pipeline")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
COACH_CACHE_DIR = _PROJECT_ROOT / "data" / "coach_cache"
CURATED_DIR = _PROJECT_ROOT / "data" / "meta_build" / "curated"

from lib.modes import PHASE3_MODES as SUPPORTED_MODES

# Mode mapping for scraper backends. SR ranked and SR draft share the
# same scrape target (build paths aren't materially different per Riot's
# queue split). Brawl has no dedicated pages; fall back to SR.
MODE_TO_SCRAPER_MODE = {
    "sr_draft": "sr",
    "sr_ranked": "sr",
    "aram":     "aram",
    "arena":    "arena",
    "brawl":    "brawl",
}


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


class PipelineOrchestrator:
    def __init__(self) -> None:
        self._site_d = SiteDScraper()
        self._site_b = SiteBScraper()
        self._ddragon: DDragon | None = None

    # ---- DDragon -----------------------------------------------------
    def refresh_ddragon(self) -> dict:
        """Pull + cache the current DDragon bundles. ~4 HTTP calls."""
        t0 = time.time()
        result = ddragon_fetch_all()
        self._ddragon = DDragon(version=result["version"])
        logger.info("ddragon refresh OK: version=%s in %.1fs",
                    result["version"], time.time() - t0)
        return result

    def ddragon(self) -> DDragon:
        if self._ddragon is None:
            self._ddragon = DDragon()
        return self._ddragon

    def champion_roster(self) -> list[str]:
        """Return the current champion list (as Riot champion IDs - e.g. ``Ahri``,
        ``XinZhao``). Uses the most recent cached DDragon bundle."""
        champions = self.ddragon().champions()
        # DDragon's champion.json has shape {"data": {"Ahri": {...}, ...}}
        return sorted(champions.get("data", {}).keys())

    # ---- per-champion scrape ----------------------------------------
    def _scrape_one(self, champ: str, mode: str) -> dict:
        """Fetch raw HTML from each scraper + surface the curated fallback.

        Returns:
            {
              "champion": "Ahri",
              "mode": "aram",
              "fetched_at": "2026-04-22T...",
              "sources": {
                  "site_d":  {"status": "ok" | "...", "bytes": int, "cache": str},
                  "site_b":  {...},
                  "curated":    {"present": bool, "path": "..." | None},
              }
            }
        """
        scraper_mode = MODE_TO_SCRAPER_MODE[mode]
        out: dict = {
            "champion": champ,
            "mode": mode,
            "scraper_mode": scraper_mode,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": {},
        }

        # --- site D ---
        try:
            html = self._site_d.fetch_champion(champ, mode=scraper_mode)
            out["sources"]["site_d"] = {
                "status": "ok",
                "bytes": len(html),
                "cache": str(self._site_d.cache_path(
                    _cache_key(champ, scraper_mode), ext="html")),
            }
        except (HttpError, Blocked, CircuitOpen, PermissionError, RuntimeError) as e:
            out["sources"]["site_d"] = {"status": "error", "error": str(e)[:200]}
            logger.warning("site_d %s/%s: %s", champ, mode, e)

        # --- site B ---
        try:
            html = self._site_b.fetch_champion(champ, mode=scraper_mode)
            out["sources"]["site_b"] = {
                "status": "ok",
                "bytes": len(html),
                "cache": str(self._site_b.cache_path(
                    _cache_key(champ, scraper_mode), ext="html")),
            }
        except (HttpError, Blocked, CircuitOpen, PermissionError, RuntimeError) as e:
            out["sources"]["site_b"] = {"status": "error", "error": str(e)[:200]}
            logger.warning("site_b %s/%s: %s", champ, mode, e)

        # --- curated fallback (Agent 4 writes here) ---
        curated_path = CURATED_DIR / mode / f"{champ.lower()}.json"
        out["sources"]["curated"] = {
            "present": curated_path.exists(),
            "path": str(curated_path) if curated_path.exists() else None,
        }

        return out

    # ---- per-mode aggregation ---------------------------------------
    def refresh_mode(
        self,
        mode: str,
        champs: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict:
        """Scrape all (or selected) champions for a mode and write the
        aggregated coach-cache JSON to ``data/coach_cache/<mode>.json``.
        """
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"unsupported mode: {mode}")

        roster = list(champs) if champs else self.champion_roster()
        if limit is not None:
            roster = roster[:limit]

        logger.info("pipeline: mode=%s champions=%d", mode, len(roster))
        entries: dict[str, dict] = {}
        t0 = time.time()
        for i, champ in enumerate(roster, start=1):
            if i == 1 or i % 10 == 0 or i == len(roster):
                logger.info("  [%d/%d] %s", i, len(roster), champ)
            entries[champ] = self._scrape_one(champ, mode)

        bundle = {
            "mode": mode,
            "ddragon_version": self.ddragon().version,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "champion_count": len(entries),
            "elapsed_sec": round(time.time() - t0, 1),
            "champions": entries,
        }
        target = COACH_CACHE_DIR / f"{mode}.json"
        _atomic_write_json(target, bundle)
        logger.info("pipeline: wrote %s (%d champions, %.1fs)",
                    target.name, len(entries), bundle["elapsed_sec"])
        return bundle

    def refresh_all(self, limit: int | None = None) -> dict[str, dict]:
        self.refresh_ddragon()
        results: dict[str, dict] = {}
        for mode in SUPPORTED_MODES:
            try:
                results[mode] = self.refresh_mode(mode, limit=limit)
            except Exception as e:       # noqa: BLE001
                logger.exception("pipeline %s failed: %s", mode, e)
                results[mode] = {"error": str(e)}
        return results


def _cache_key(champ: str, mode: str) -> str:
    """Mirror the cache-key shape the scrapers use internally."""
    return f"{champ.strip().lower().replace(' ', '').replace(chr(39), '')}_{mode}"


# -- module-level conveniences used by Agent 1 dispatch payloads -----

def refresh_ddragon() -> dict:
    return PipelineOrchestrator().refresh_ddragon()


def refresh_mode(mode: str, champs: list[str] | None = None, limit: int | None = None) -> dict:
    orch = PipelineOrchestrator()
    if not champs:
        orch.refresh_ddragon()    # ensure DDragon is current before scraping
    return orch.refresh_mode(mode, champs=champs, limit=limit)


def refresh_all(limit: int | None = None) -> dict[str, dict]:
    return PipelineOrchestrator().refresh_all(limit=limit)


# -- CLI -------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Agent 2 data pipeline")
    p.add_argument("--ddragon-only", action="store_true",
                   help="Refresh DDragon cache only (skip scrapers)")
    p.add_argument("--all", action="store_true",
                   help="Refresh DDragon + every mode")
    p.add_argument("--mode", choices=SUPPORTED_MODES, help="Refresh one mode")
    p.add_argument("--champs", nargs="+", help="Limit scrape to specific champions")
    p.add_argument("--limit", type=int, help="Cap champions per mode to N")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    orch = PipelineOrchestrator()
    if args.ddragon_only:
        orch.refresh_ddragon()
        return 0
    if args.all:
        orch.refresh_all(limit=args.limit)
        return 0
    if args.mode:
        orch.refresh_ddragon()
        orch.refresh_mode(args.mode, champs=args.champs, limit=args.limit)
        return 0
    p.error("must pass --ddragon-only, --all, or --mode")
    return 1   # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
