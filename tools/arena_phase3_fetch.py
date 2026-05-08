"""Fetch aggregator J arena pages for the 109 missing champions (Phase 3).

Saves raw HTML into data/meta_build/refresh_2026-05-02/_phase3_html/<slug>.html
so the parsing step is a separate cheap pass.
"""
from __future__ import annotations
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(r"C:/Riot Commander")
DDRAGON = ROOT / "data/meta/ddragon_champions.json"
COVERED = ROOT / "data/meta_build/arena_champion_builds.json"
OUTDIR = ROOT / "data/meta_build/refresh_2026-05-02/_phase3_html"
OUTDIR.mkdir(parents=True, exist_ok=True)

SLUG_OVERRIDES = {
    "Aurelion Sol": "AurelionSol",
    "Bel'Veth": "Belveth",
    "Cho'Gath": "Chogath",
    "Dr. Mundo": "DrMundo",
    "Jarvan IV": "JarvanIV",
    "Kai'Sa": "Kaisa",
    "Kha'Zix": "Khazix",
    "K'Sante": "KSante",
    "Kog'Maw": "KogMaw",
    "LeBlanc": "Leblanc",
    "Lee Sin": "LeeSin",
    "Master Yi": "MasterYi",
    "Miss Fortune": "MissFortune",
    "Nunu & Willump": "Nunu",
    "Rek'Sai": "RekSai",
    "Renata Glasc": "Renata",
    "Tahm Kench": "TahmKench",
    "Twisted Fate": "TwistedFate",
    "Vel'Koz": "Velkoz",
    "Wukong": "MonkeyKing",
    "Xin Zhao": "XinZhao",
}


def slug_for(name: str) -> str:
    if name in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[name]
    return name.replace("'", "").replace(" ", "").replace(".", "")


def load_missing() -> list[str]:
    dd = json.loads(DDRAGON.read_text(encoding="utf-8"))["data"]
    all_names = sorted(v["name"] for v in dd.values())
    covered = set(json.loads(COVERED.read_text(encoding="utf-8")).keys()) - {
        "_meta",
        "_phase2_meta",
        "_phase2_added",
    }
    return [n for n in all_names if n not in covered]


CTX = ssl.create_default_context()
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch(name: str) -> tuple[str, str | None, str | None]:
    slug = slug_for(name)
    url = f"https://aggregator-j.invalid/en/league/champion/{slug}/arena"
    out = OUTDIR / f"{slug}.html"
    if out.exists() and out.stat().st_size > 1000:
        return name, slug, None  # already cached
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            body = r.read()
        out.write_bytes(body)
        return name, slug, None
    except Exception as e:
        return name, slug, str(e)


def main() -> int:
    missing = load_missing()
    print(f"missing: {len(missing)}", flush=True)
    errors: list[tuple[str, str, str]] = []
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fetch, n): n for n in missing}
        for fut in as_completed(futs):
            name, slug, err = fut.result()
            done += 1
            if err:
                errors.append((name, slug, err))
                print(f"[{done}/{len(missing)}] {name} ({slug}) ERR {err}", flush=True)
            else:
                print(f"[{done}/{len(missing)}] {name} ({slug}) ok", flush=True)
    dt = time.time() - t0
    print(f"\nfinished {done}/{len(missing)} in {dt:.1f}s, errors: {len(errors)}", flush=True)
    if errors:
        for n, s, e in errors:
            print(f"  ERR {n} -> {s}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
