"""
scripts/data_pipeline.py - Amberstone data asset pipeline.

Usage:
    python data_pipeline.py ddragon         # Download DDragon meta JSON files
    python data_pipeline.py runes           # Download DDragon rune metadata + icons
    python data_pipeline.py icons           # Download champion / spell / item icons
    python data_pipeline.py meta            # Print current patch version info
    python data_pipeline.py aram_builds     # Update ARAM tier rankings (or verify)
    python data_pipeline.py aram_builds --verify  # Print current tier distribution
    python data_pipeline.py rank_tiers      # Stamp live patch onto the rank-tier stats-panel artifact
    python data_pipeline.py all             # Run ddragon + runes + icons + aram_builds + rank_tiers

Downloads to:
    data/meta/ddragon_version.json
    data/meta/ddragon_champions.json
    data/meta/ddragon_items.json
    data/meta/ddragon_runes.json
    data/meta/ddragon_summoner_spells.json
    data/icons/champions/     (champion square PNGs)
    data/icons/spells/        (summoner spell PNGs)
    data/icons/runes/         (keystone + rune tree PNGs)

Version-aware: skips downloads if patch version unchanged.
Logs to logs/data_pipeline.log
"""

import json
import math
import sys
import time
import logging
import urllib.request
import urllib.error
from pathlib import Path

ROOT     = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.daemon_slayer import mode_variants  # noqa: E402
from core import external_sources  # noqa: E402

DATA     = ROOT / "data"
META     = DATA / "meta"
ICONS    = DATA / "icons"
LOG_FILE = ROOT / "logs" / "data_pipeline.log"

# Overlay item 8 Phase 2: the rank-tier stats-panel ingest artifact. The seed is
# committed (a hand-curated estimate); the live file is gitignored + patch-stamped
# here. Module-level so tests can redirect them into a tmp dir.
RANK_TIERS_DIR  = DATA / "rank_tiers"
RANK_TIERS_SEED = RANK_TIERS_DIR / "rank_tier_averages.seed.json"
RANK_TIERS_LIVE = RANK_TIERS_DIR / "rank_tier_averages.json"

META.mkdir(parents=True, exist_ok=True)
ICONS.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# RC-PatchRefresh runs this under pythonw.exe (a console interpreter flashes a
# window on the operator's desktop - see the LW-CIWatchdog case, 2026-08-02), and
# under pythonw BOTH sys.stdout and sys.stderr are None. A StreamHandler built on
# them would then raise on every single record and have the error swallowed by
# logging.handleError, so the handler is only attached when a real stream exists.
_handlers = [logging.FileHandler(str(LOG_FILE), encoding="utf-8")]
if sys.stdout is not None:
    _handlers.insert(0, logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("data_pipeline")

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
VERSIONS_URL = f"{DDRAGON_BASE}/api/versions.json"


# -- Utilities -----------------------------------------------------------------

def _fetch_json(url: str, timeout: int = 15) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "Amberstone/3.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _fetch_bytes(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Amberstone/3.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _drop_throwback_rows(filename: str, doc):
    """Strip DDragon THROWBACK-MODE rows from a freshly fetched meta doc.

    16.15.1 shipped a parallel legacy registry beside the live one: 60
    ``Jade_<Champion>`` rows at ``base_key + 60000``, 162 items in
    ``[770000, 780000)`` (retired gear - Sightstone, Zz'Rot Portal, Hex Core),
    and 16 summoner spells whose ``modes`` list is exactly ``["JADE"]``.

    ``data/meta/*`` is not an upstream mirror - it is RC's LIVE-ROSTER cache,
    read by ~15 modules that treat it as "the champions/items in play" and
    frequently key by display NAME, which the throwback rows duplicate (they
    diverge on armor and hp for all 60, attack damage for 58, movespeed for 21).
    The faithful upstream copy is kept separately under
    ``data/meta_build/ddragon/<patch>/``, so nothing is lost here.

    Revisit when a JADE mode is wired into mode detection - note the live Flash
    row already advertises a ``KIWI_JADE`` mode, so an ARAM-Mayhem-Jade variant
    is the likely first contact.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), dict):
        return doc
    rows = doc["data"]
    if filename == "ddragon_champions.json":
        kept = mode_variants.canonical_champions(rows)
    elif filename == "ddragon_items.json":
        kept = mode_variants.canonical_items(rows)
    elif filename == "ddragon_summoner_spells.json":
        kept = {
            sid: entry
            for sid, entry in rows.items()
            if not (
                isinstance(entry, dict)
                and list(entry.get("modes") or []) == ["JADE"]
            )
        }
    else:
        return doc
    dropped = len(rows) - len(kept)
    if dropped:
        log.info("  %s: dropped %d throwback-mode row(s)", filename, dropped)
    return {**doc, "data": kept}


def _write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _get_live_version() -> str:
    versions = _fetch_json(VERSIONS_URL)
    return versions[0]


def _get_cached_version() -> str:
    p = META / "ddragon_version.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")).get("version", "")
    return ""


def _download_icon(url: str, dest: Path, label: str = "") -> bool:
    """Download a single icon. Returns True on success, False on skip/fail."""
    if dest.exists():
        return False  # already have it
    try:
        data = _fetch_bytes(url)
        _write_bytes(dest, data)
        if label:
            log.debug("  icon: %s", label)
        time.sleep(0.05)  # polite rate limit
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("  icon failed %s: %s", url, e)
        return False


def _wr_to_tier(raw, thresholds: list[tuple[float, str]]) -> str | None:
    """Map a tier-source winrate cell to a tier letter. Pure + fail-soft.

    Returns the tier string (highest threshold met, else "D") or ``None``
    when the cell cannot be trusted - in which case the caller SKIPS that
    champion rather than fabricating a tier. Two faults this guards:

      * non-finite winrate (NaN / inf): every ``wr >= threshold`` check is
        False for NaN, so the inline version silently tagged the LOWEST
        tier "D". A non-finite winrate is no data, not a floor result.
      * non-numeric cell: coercion fails -> ``None`` so one malformed row
        skips only itself instead of raising mid-loop and aborting tier
        extraction for every remaining champion.

    Accepts both fraction (0.54) and percent (54.0) encodings; a value
    below 1.0 is read as a fraction and scaled to percent.
    """
    try:
        wr = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(wr):
        return None
    if wr < 1.0:
        wr *= 100.0
    for threshold, letter in thresholds:
        if wr >= threshold:
            return letter
    return "D"


# -- Commands ------------------------------------------------------------------

def cmd_items_index(force: bool = False) -> bool:
    """Regenerate web/data/items_index.json from data/meta/ddragon_items.json.

    Output schema mirrors the existing index used by web/js/lib/items_index.js:
      {
        "version": "<patch>",
        "byName":  { "<lowercased-stripped-name>": "<id-string>", ... },
        "byId":    { "<id-string>": "<display-name>", ... },
      }

    No-op if web/data/items_index.json's version already matches the
    cached DDragon patch (unless force=True). Run after
    `cmd_ddragon` to keep the dashboard's item resolution in sync with
    the latest patch automatically.
    """
    src = META / "ddragon_items.json"
    dest = ROOT / "web" / "data" / "items_index.json"
    if not src.exists():
        log.error("ddragon_items.json missing - run `data_pipeline.py ddragon` first")
        return False
    try:
        d = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("ddragon_items.json parse failed: %s", e)
        return False

    version = d.get("version", "")
    items   = d.get("data", {}) or {}

    # Skip if already current
    if dest.exists() and not force:
        try:
            existing = json.loads(dest.read_text(encoding="utf-8"))
            if existing.get("version") == version:
                log.info("items_index.json already at patch %s - skipping (use force=True)", version)
                return True
        except Exception:  # noqa: BLE001
            pass

    by_name: dict[str, str] = {}
    by_id:   dict[str, str] = {}
    # Sort shorter IDs first so canonical IDs (e.g. "2502") win over 6-digit
    # alias mirrors (e.g. "222502") when DDragon 16.9+ includes both under
    # the same display name. setdefault then picks the canonical on first-seen.
    for item_id, info in sorted(items.items(), key=lambda kv: len(kv[0])):
        name = info.get("name") or ""
        if not name:
            continue
        # byName key matches the items_index.js name normalizer: lowercase, strip non-alnum.
        norm = "".join(c for c in name.lower() if c.isalnum())
        by_name.setdefault(norm, str(item_id))
        by_id[str(item_id)] = name

    payload = {"version": version, "byName": by_name, "byId": by_id}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    log.info("items_index.json: %d items, patch %s - written to %s",
             len(by_id), version, dest)
    return True


def cmd_champions_index(force: bool = False) -> bool:
    """Regenerate web/data/champions_index.json from data/meta/ddragon_champions.json.

    Output schema (matches web/js/lib/items_index.js consumer):
      {
        "version": "<patch>",
        "byId":   { "<numeric-key>": "<DDragon-id>", ... },
        "byName": { "<normalized-id>": "<DDragon-id>", ... },
      }

    byName normalizes the DDragon id (lowercase, strip non-alnum); display-name
    renames like Wukong/Kha'Zix/etc are handled separately via
    /data/champion_aliases.json (loaded async in items_index.js).
    No-op if dest already matches the bundle patch (unless force=True).
    """
    src = META / "ddragon_champions.json"
    dest = ROOT / "web" / "data" / "champions_index.json"
    if not src.exists():
        log.error("ddragon_champions.json missing - run `data_pipeline.py ddragon` first")
        return False
    try:
        d = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("ddragon_champions.json parse failed: %s", e)
        return False

    version = d.get("version", "")
    champs  = d.get("data", {}) or {}

    if dest.exists() and not force:
        try:
            existing = json.loads(dest.read_text(encoding="utf-8"))
            if existing.get("version") == version:
                log.info("champions_index.json already at patch %s - skipping (use force=True)", version)
                return True
        except Exception:  # noqa: BLE001
            pass

    by_id:   dict[str, str] = {}
    by_name: dict[str, str] = {}
    for cid in sorted(champs.keys()):
        info = champs[cid]
        key  = str(info.get("key", "")).strip()
        if not key:
            continue
        by_id[key] = cid
        norm = "".join(c for c in cid.lower() if c.isalnum())
        by_name[norm] = cid

    payload = {"version": version, "byId": by_id, "byName": by_name}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    log.info("champions_index.json: %d champs, patch %s - written to %s",
             len(by_id), version, dest)
    return True


def cmd_spells_index(force: bool = False) -> bool:
    """Regenerate web/data/spells_index.json from data/meta/ddragon_summoner_spells.json.

    Output schema (matches web/js/lib/items_index.js consumer):
      {
        "version": "<patch>",
        "byName": {
          "<normalized-name-or-id>": {"id":..., "name":..., "img":..., "cd":...},
          ...,
          "tp": {... SummonerTeleport entry ...}  # hand alias
        }
      }

    Iteration order = spells sorted by numeric .key ascending so canonical
    Riot ordering (Flash=4 wins 'flash' over CherryFlash=2202; Snowball=32
    wins 'mark' over SnowURFSnowball_Mark=39). setdefault means first-seen
    wins on display-name collisions. Hand alias 'tp' -> SummonerTeleport.
    """
    src = META / "ddragon_summoner_spells.json"
    dest = ROOT / "web" / "data" / "spells_index.json"
    if not src.exists():
        log.error("ddragon_summoner_spells.json missing - run `data_pipeline.py ddragon` first")
        return False
    try:
        d = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("ddragon_summoner_spells.json parse failed: %s", e)
        return False

    version = d.get("version", "")
    spells  = d.get("data", {}) or {}

    if dest.exists() and not force:
        try:
            existing = json.loads(dest.read_text(encoding="utf-8"))
            if existing.get("version") == version:
                log.info("spells_index.json already at patch %s - skipping (use force=True)", version)
                return True
        except Exception:  # noqa: BLE001
            pass

    def _norm(s: str) -> str:
        return "".join(c for c in s.lower() if c.isalnum())

    def _entry(sid: str, info: dict) -> dict:
        cd_list = info.get("cooldown") or [0]
        try:
            cd = cd_list[0]
        except (IndexError, TypeError):
            cd = 0
        return {
            "id":   sid,
            "name": info.get("name", ""),
            "img":  (info.get("image", {}) or {}).get("full", ""),
            "cd":   cd,
        }

    # Sort by numeric .key ascending; iteration order drives setdefault wins.
    sorted_ids = sorted(spells.keys(), key=lambda s: int(spells[s].get("key", 0) or 0))

    by_name: dict[str, dict] = {}
    for sid in sorted_ids:
        info  = spells[sid]
        entry = _entry(sid, info)
        nname = _norm(info.get("name", ""))
        nid   = _norm(sid)
        if nname:
            by_name.setdefault(nname, entry)
        if nid:
            by_name.setdefault(nid, entry)

    # Hand alias: 'tp' is a common shorthand for Teleport that doesn't fall
    # out of any normalization rule.
    if "SummonerTeleport" in spells:
        by_name["tp"] = _entry("SummonerTeleport", spells["SummonerTeleport"])

    payload = {"version": version, "byName": by_name}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    # Match the existing compact-on-one-line layout.
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    tmp.replace(dest)
    log.info("spells_index.json: %d entries, patch %s - written to %s",
             len(by_name), version, dest)
    return True


def cmd_meta():
    """Print current version state without downloading anything."""
    cached = _get_cached_version()
    try:
        live = _get_live_version()
    except Exception as e:  # noqa: BLE001
        live = f"(fetch failed: {e})"
    log.info("Cached patch: %s", cached or "(none)")
    log.info("Live patch:   %s", live)
    if cached and live and cached == live:
        log.info("Status: UP TO DATE")
    else:
        log.info("Status: UPDATE AVAILABLE" if cached else "Status: NOT DOWNLOADED")


def cmd_ddragon(force: bool = False):
    """Download DDragon champion, item, spell JSON files."""
    log.info("=== DDragon meta download ===")
    try:
        live = _get_live_version()
    except Exception as e:  # noqa: BLE001
        log.error("Cannot fetch version list: %s", e)
        return False

    cached = _get_cached_version()
    if cached == live and not force:
        log.info("Already on patch %s - skipping (use force=True to override)", live)
        return True

    log.info("Downloading patch %s meta...", live)
    base = f"{DDRAGON_BASE}/cdn/{live}/data/en_US"

    targets = {
        "ddragon_champions.json":       f"{base}/champion.json",
        "ddragon_items.json":           f"{base}/item.json",
        "ddragon_summoner_spells.json": f"{base}/summoner.json",
    }

    ok = True
    for filename, url in targets.items():
        dest = META / filename
        try:
            log.info("  Fetching %s...", filename)
            data = _fetch_json(url)
            data = _drop_throwback_rows(filename, data)
            _write_json(dest, data)
            log.info("  OK: %s (%d bytes)", filename, dest.stat().st_size)
        except Exception as e:  # noqa: BLE001
            log.error("  FAILED %s: %s", filename, e)
            ok = False

    if ok:
        _write_json(META / "ddragon_version.json", {"version": live, "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")})
        log.info("DDragon meta complete - patch %s", live)
    return ok


def cmd_runes(force: bool = False):
    """Download DDragon rune metadata JSON + keystone/tree icons."""
    log.info("=== Rune metadata + icons download ===")

    try:
        live = _get_live_version()
    except Exception as e:  # noqa: BLE001
        log.error("Cannot fetch version list: %s", e)
        return False

    rune_dest = META / "ddragon_runes.json"
    rune_url  = f"{DDRAGON_BASE}/cdn/{live}/data/en_US/runesReforged.json"

    if not rune_dest.exists() or force:
        try:
            log.info("  Fetching runesReforged.json...")
            data = _fetch_json(rune_url)
            _write_json(rune_dest, data)
            log.info("  OK: ddragon_runes.json (%d bytes)", rune_dest.stat().st_size)
        except Exception as e:  # noqa: BLE001
            log.error("  FAILED rune JSON: %s", e)
            return False
    else:
        log.info("  ddragon_runes.json already exists - skipping JSON fetch")
        data = json.loads(rune_dest.read_text(encoding="utf-8"))

    rune_icon_dir = ICONS / "runes"
    rune_icon_dir.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = failed = 0
    for tree in data:
        tree_icon_url  = f"{DDRAGON_BASE}/cdn/img/{tree.get('icon', '')}"
        tree_icon_name = Path(tree.get("icon", "")).name
        if tree_icon_name:
            result = _download_icon(tree_icon_url, rune_icon_dir / tree_icon_name, tree.get("name", ""))
            if result: downloaded += 1
            else: skipped += 1

        for slot in tree.get("slots", []):
            for rune in slot.get("runes", []):
                rune_icon_url  = f"{DDRAGON_BASE}/cdn/img/{rune.get('icon', '')}"
                rune_icon_name = Path(rune.get("icon", "")).name
                if rune_icon_name:
                    result = _download_icon(rune_icon_url, rune_icon_dir / rune_icon_name, rune.get("name", ""))
                    if result: downloaded += 1
                    else: skipped += 1

    log.info("Rune icons: %d downloaded, %d already existed, %d failed", downloaded, skipped, failed)
    return True


def cmd_icons(force: bool = False):
    """Download champion square icons and summoner spell icons."""
    log.info("=== Champion + spell icon download ===")

    try:
        live = _get_live_version()
    except Exception as e:  # noqa: BLE001
        log.error("Cannot fetch version list: %s", e)
        return False

    base_img = f"{DDRAGON_BASE}/cdn/{live}/img"

    champ_dir = ICONS / "champions"
    champ_dir.mkdir(parents=True, exist_ok=True)

    champ_json = META / "ddragon_champions.json"
    if not champ_json.exists():
        log.warning("ddragon_champions.json missing - run 'ddragon' first")
    else:
        champs = json.loads(champ_json.read_text(encoding="utf-8")).get("data", {})
        log.info("  Downloading %d champion icons...", len(champs))
        dl = sk = 0
        for name, info in champs.items():
            icon_file = info.get("image", {}).get("full", f"{name}.png")
            url  = f"{base_img}/champion/{icon_file}"
            dest = champ_dir / icon_file
            if _download_icon(url, dest, name): dl += 1
            else: sk += 1
        log.info("  Champion icons: %d downloaded, %d already existed", dl, sk)

    spell_dir = ICONS / "spells"
    spell_dir.mkdir(parents=True, exist_ok=True)

    spell_json = META / "ddragon_summoner_spells.json"
    if not spell_json.exists():
        log.warning("ddragon_summoner_spells.json missing - run 'ddragon' first")
    else:
        spells = json.loads(spell_json.read_text(encoding="utf-8")).get("data", {})
        log.info("  Downloading %d summoner spell icons...", len(spells))
        dl = sk = 0
        for name, info in spells.items():
            icon_file = info.get("image", {}).get("full", f"{name}.png")
            url  = f"{base_img}/spell/{icon_file}"
            dest = spell_dir / icon_file
            if _download_icon(url, dest, name): dl += 1
            else: sk += 1
        log.info("  Spell icons: %d downloaded, %d already existed", dl, sk)

    return True


def cmd_aram_builds(force: bool = False) -> bool:
    """
    Update ARAM champion tier rankings in data/meta_build/aram_champion_builds.json.

    Attempts an automated fetch from the configured tier source. Falls back
    gracefully (non-fatal) when it is unset or unavailable - anti-scraping
    protections are common on stats sites.

    Manual update guide (patch day):
      1. https://www.leagueoflegends.com/en-us/news/game-updates/patch-notes/
      2. Find ARAM balance section
      3. Edit aram_tier fields in data/meta_build/aram_champion_builds.json
      4. Verify: python data_pipeline.py aram_builds --verify

    Tier mapping: S>=55% | A>=53% | B>=51% | C>=49% | D<49%
    """
    log.info("=== ARAM champion tier update ===")

    BUILDS_FILE = ROOT / "data" / "meta_build" / "aram_champion_builds.json"
    if not BUILDS_FILE.exists():
        log.error("aram_champion_builds.json not found"); return False

    try:
        builds = json.loads(BUILDS_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("Failed to load aram_champion_builds.json: %s", e); return False

    # --verify flag: print current tier distribution without updating
    if len(sys.argv) > 2 and sys.argv[2] == "--verify":
        tiers: dict = {}
        for k, v in builds.items():
            if k.startswith("_") or not isinstance(v, dict): continue
            t = v.get("aram_tier", "?")
            tiers.setdefault(t, []).append(k)
        note = builds.get("_note", "(no note)")
        log.info("Build note: %s", note)
        log.info("Tier distribution:")
        for tier in ("S", "A", "B", "C", "D", "?"):
            champs = tiers.get(tier, [])
            if champs:
                log.info("  %s (%d): %s%s", tier, len(champs),
                         ", ".join(sorted(champs)[:15]),
                         "..." if len(champs) > 15 else "")
        return True

    live_version = ""
    try:
        live_version = _get_live_version()
    except Exception:  # noqa: BLE001
        pass

    note = builds.get("_note", "")
    if not force and live_version and live_version in note:
        log.info("Already at patch %s - skipping (use force=True to override)", live_version)
        log.info("Patch notes: https://www.leagueoflegends.com/en-us/news/game-updates/patch-notes/")
        return True

    tier_data: dict[str, str] = {}

    # Try the configured ARAM tier table. The endpoint is operator config
    # (`aram_tier_table` in config/external_sources.json), read here rather
    # than at import so an unconfigured install resolves to the empty string,
    # fails inside this try, and lands on the manual-update warning below.
    try:
        raw = _fetch_json(external_sources.value("aram_tier_table"), timeout=12)
        ddragon_champs = {}
        _dd = ROOT / "data" / "meta" / "ddragon_champions.json"
        if _dd.exists():
            for key, v in (json.loads(_dd.read_text(encoding="utf-8")).get("data") or {}).items():
                ddragon_champs[str(v.get("key", ""))] = v.get("id", key)

        WR_THRESHOLDS = [(55.0, "S"), (53.0, "A"), (51.0, "B"), (49.0, "C")]
        for entry in (raw if isinstance(raw, list) else []):
            if not isinstance(entry, list) or len(entry) < 4: continue
            champ_id   = str(entry[0])
            champ_name = ddragon_champs.get(champ_id, "")
            if not champ_name: continue
            tier = _wr_to_tier(entry[3], WR_THRESHOLDS)
            if tier is None: continue  # non-numeric / non-finite cell - skip, never floor-tag
            tier_data[champ_name] = tier

        if tier_data:
            log.info("tier source: fetched tier data for %d champions", len(tier_data))
    except Exception as e:  # noqa: BLE001
        log.warning("tier source fetch failed (%s) - automated tier update unavailable", e)

    if not tier_data:
        log.warning(
            "Automated tier sources unavailable (anti-scraping protections).\n"
            "  Manual update: edit aram_tier in data/meta_build/aram_champion_builds.json\n"
            "  Patch notes:   https://www.leagueoflegends.com/en-us/news/game-updates/patch-notes/\n"
            "  Verify after:  python data_pipeline.py aram_builds --verify"
        )
        return True  # Non-fatal

    updated = unchanged = skipped = 0
    for champ_key, champ_data in builds.items():
        if champ_key.startswith("_") or not isinstance(champ_data, dict): continue
        fetched = tier_data.get(champ_key) or tier_data.get(champ_key.replace(" ", ""))
        if fetched is None: skipped += 1; continue
        if fetched != champ_data.get("aram_tier", ""):
            champ_data["aram_tier"] = fetched; updated += 1
        else:
            unchanged += 1

    if live_version:
        builds["_note"] = (
            f"ARAM builds for full champion roster. "
            f"Patch {live_version}. Updated {time.strftime('%Y-%m-%d')}. "
            f"Tiers auto-updated; build notes manually curated."
        )

    tmp = BUILDS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(builds, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(BUILDS_FILE)
    log.info("ARAM builds: %d updated, %d unchanged, %d not in source", updated, unchanged, skipped)
    return True


def cmd_rank_tiers(force: bool = False) -> bool:
    """Refresh the rank-tier stats-panel ingest artifact (overlay item 8 Phase 2).

    Stamps the CURRENT live patch onto the gitignored live file
    data/rank_tiers/rank_tier_averages.json. Today the payload is seeded from the
    committed estimate seed (rank_tier_averages.seed.json) - a hand-curated
    "estimate-not-measured" reference; its `source` provenance is carried
    verbatim so the overlay badges it and coaching never leans on it as ground
    truth. When a live aggregate source is later configured, this is the
    subcommand where a fetched payload would land instead of the seed copy.

    Version-aware like the sibling commands: a no-op when the live file already
    carries the live patch (unless force). Fail-soft:
      * a missing seed logs a WARNING and returns True (non-fatal, so cmd_all is
        never aborted over this artifact),
      * a failed live-version fetch falls back to the seed's own patch stamp.
    Atomic write (tmp.write + tmp.replace); the emitted JSON stays 7-bit ASCII.
    """
    log.info("=== Rank-tier stats-panel ingest ===")
    if not RANK_TIERS_SEED.exists():
        log.warning("rank_tier_averages.seed.json missing at %s - skipping (non-fatal)",
                    RANK_TIERS_SEED)
        return True
    try:
        seed = json.loads(RANK_TIERS_SEED.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("rank_tier seed parse failed: %s - skipping (non-fatal)", e)
        return True

    seed_patch = str(seed.get("patch") or "")
    try:
        live_version = _get_live_version()
    except Exception as e:  # noqa: BLE001 - offline is fine, fall back to seed patch
        log.info("live version unavailable (%s) - using seed patch %s", e, seed_patch or "(none)")
        live_version = seed_patch
    patch = live_version or seed_patch

    # Version-aware skip: don't rewrite when already stamped at the live patch.
    if RANK_TIERS_LIVE.exists() and not force:
        try:
            existing = json.loads(RANK_TIERS_LIVE.read_text(encoding="utf-8"))
            if existing.get("patch") == patch:
                log.info("rank_tier_averages.json already at patch %s - skipping (use force=True)",
                         patch or "(none)")
                return True
        except Exception:  # noqa: BLE001
            pass

    out = dict(seed)
    out["patch"] = patch
    out["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    RANK_TIERS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RANK_TIERS_LIVE.with_suffix(".json.tmp")
    # ensure_ascii=True: the artifact must stay 7-bit ASCII (repo hard rule).
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=True), encoding="utf-8")
    tmp.replace(RANK_TIERS_LIVE)
    n_tiers = len(out.get("tiers") or {})
    log.info("rank_tier_averages.json: %d tiers, patch %s - written to %s",
             n_tiers, patch or "(none)", RANK_TIERS_LIVE)
    return True


def cmd_all():
    """Run full pipeline: ddragon + items_index + runes + icons + aram_builds
    + rank_tiers."""
    log.info("=== Full data pipeline run ===")
    ok = True
    ok &= cmd_ddragon()
    ok &= cmd_items_index()
    ok &= cmd_champions_index()
    ok &= cmd_spells_index()
    ok &= cmd_runes()
    ok &= cmd_icons()
    ok &= cmd_aram_builds()
    ok &= cmd_rank_tiers()
    if ok:
        log.info("=== Pipeline complete ===")
    else:
        log.warning("=== Pipeline completed with errors - check log ===")
    return ok


# -- Entry point ---------------------------------------------------------------

COMMANDS = {
    "ddragon":         cmd_ddragon,
    "items_index":     cmd_items_index,
    "champions_index": cmd_champions_index,
    "spells_index":    cmd_spells_index,
    "runes":           cmd_runes,
    "icons":           cmd_icons,
    "meta":            cmd_meta,
    "aram_builds":     cmd_aram_builds,
    "rank_tiers":      cmd_rank_tiers,
    "all":             cmd_all,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python data_pipeline.py [{' | '.join(COMMANDS)}]")
        print("       python data_pipeline.py aram_builds --verify")
        sys.exit(1)
    cmd = sys.argv[1]
    log.info("data_pipeline: running '%s'", cmd)
    result = COMMANDS[cmd]()
    sys.exit(0 if result is not False else 1)
