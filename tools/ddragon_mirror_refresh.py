"""DDragon mirror auto-refresh.

Resolves the latest DDragon patch via the CDN versions endpoint, pulls the
canonical bundle JSONs (champion / item / runesReforged / summoner /
profileicon) into ``data/meta_build/ddragon/<ver>/``, enumerates every
asset URL each bundle implies, and downloads the deltas into
``web/data/ddragon/<ver>/img/<class>/`` for the dashboard to serve locally.

Asset classes covered:
- img/champion/<Name>.png            (champion square portraits)
- img/spell/<Spell>.png              (champion ability + summoner spell icons)
- img/passive/<Passive>.png          (champion passives)
- img/item/<id>.png                  (every shop item)
- img/profileicon/<id>.png           (every profile icon)
- img/map/map<N>.png                 (SR=11, ARAM=12, Cherry=30)
- img/<perk path>                    (rune tree + rune icons; version-less)

Augment icons are NOT in DDragon; CommunityDragon serves them via the
cherry-augments.json route. Out of scope for v1 - flagged for a separate
cdragon adapter.

Modes:
  --check-only      exit 0 if up-to-date, 1 if a flip / delta is pending
  --dry-run         enumerate the plan, no network writes
  (default)         idempotent fetch - skip files already present
  --check-changed   HEAD probe + re-fetch when ETag/size differs (mid-patch)
  --full            ignore manifest, re-fetch every asset for the version
  --version <pin>   pin a specific patch version (escape hatch)

Atomic writes throughout (tmp.write_bytes -> os.replace). py_compile clean.
Fail-loud on bundle JSON corruption. After a clean (non-dry) run, stale
``web/data/ddragon/<semver>/`` dirs beyond the retention set (current patch
+ one previous; ``--retain`` / ``--no-prune`` to adjust) are deleted -
deep-audit item 396 retention; git-tracked bundle archives under
data/meta_build/ are never pruned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import ntpath
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parent.parent
META_DIR = ROOT / "data" / "meta_build" / "ddragon"
WEB_DIR = ROOT / "web" / "data" / "ddragon"
INDEX_PATH = META_DIR / "_index.json"

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
VERSIONS_URL = f"{DDRAGON_BASE}/api/versions.json"
USER_AGENT = "Amberstone/3.0 ddragon-mirror-refresh"
DEFAULT_TIMEOUT = 20.0
MIN_INTERVAL_SEC = 0.05  # bundle-pull cadence; asset fetches use a worker pool
DEFAULT_WORKERS = 8       # parallel asset fetches against CloudFront
# Retry sleeps for transient errors (URLError / timeout / HTTP 429+5xx).
# len() of this tuple == max retry count; one timeout per cron tick is the
# operational symptom we observed (item 109 carry).
RETRY_BACKOFFS = (1.0, 2.0)
TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
# A handful of transient single-asset flakes across thousands of CDN probes is
# operationally normal; only a failure RATIO above this trips a non-zero exit
# (item 376 - benign nightly result=2 from one 404 among ~6800 assets).
FAIL_RATIO_TOLERANCE = 0.005

# RM-353: the version string is CDN input and it becomes a filesystem path
# segment (META_DIR / version, WEB_DIR / version, and CACHE_ROOT / version in
# lib/ddragon/fetch.py), so it is validated at every entry point before any
# join. `pathlib` does NOT normalise, and on Windows an anchored element
# ("C:/x") REPLACES the left operand outright.
#
# The accepted shape is deliberately the shape `prune_stale_versions` scans
# for - `_SEMVER_DIR` below is this same object, not a second copy - because a
# directory the retention pass cannot recognise is a directory it can never
# delete. Anything created must stay prunable.
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def validate_version(version: Any) -> str:
    """Return `version` if it is a safe DDragon patch string, else raise.

    Rejects, in order of how they actually arrive: a non-string (a malformed
    body yields a dict / int / None), a path-traversal or anchored element,
    and anything that is not ``<major>.<minor>.<patch>``. That last check is
    what catches a JSON *string* body - ``"maintenance"`` makes ``versions[0]``
    the single character ``"m"``, which is a legal directory name and would
    pass a traversal-only or basename-only test.
    """
    if not isinstance(version, str) or isinstance(version, bool):
        raise ValueError(f"DDragon version must be a string, got {type(version).__name__}")
    # fullmatch, not match: `$` also matches BEFORE a trailing newline, so
    # `match` would accept "16.15.1\n" - a control character in a name this
    # code is about to create a directory from. Found by the RM-353
    # adversarial pass. The pruner keeps `.match` deliberately: it must still
    # recognise such a directory as a prune candidate if one ever exists.
    if not VERSION_RE.fullmatch(version):
        raise ValueError(
            f"refusing unsafe DDragon version {version!r} - expected <major>.<minor>.<patch>"
        )
    return version

# Maps used by the dashboard. DDragon ships map11.png (SR), map12.png (ARAM),
# map30.png (Cherry/Arena). Brawl (35) is map11 reskin and has no DDragon asset.
MAP_IDS = (11, 12, 30)

# DDragon bundle names pulled at /cdn/<ver>/data/en_US/<name>.json. The
# "champion" summary endpoint does NOT include per-champion `spells` or
# `passive`; for those we fetch /cdn/<ver>/data/<locale>/champion/<Name>.json
# per champion (see pull_champion_details).
BUNDLE_NAMES = ("champion", "item", "runesReforged", "summoner", "profileicon")

DEFAULT_LOCALE = "en_US"

logger = logging.getLogger("ddragon_mirror_refresh")


# ---------------------------------------------------------------------------
# tiny HTTP helpers (stdlib only; lib.http enforces 1 req/sec/host which is
# too slow for ~900 sequential small PNG fetches and not warranted vs Cloudflare)


@dataclass
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes


def _http(method: str, url: str, *, headers: dict[str, str] | None = None,
          timeout: float = DEFAULT_TIMEOUT) -> HttpResult:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    last_url_err: urllib_error.URLError | None = None
    for attempt in range(len(RETRY_BACKOFFS) + 1):
        req = urllib_request.Request(url, headers=h, method=method)
        try:
            with urllib_request.urlopen(req, timeout=timeout) as r:
                body = b"" if method == "HEAD" else r.read()
                return HttpResult(r.status, {k.lower(): v for k, v in r.headers.items()}, body)
        except urllib_error.HTTPError as e:
            if e.code in TRANSIENT_HTTP_CODES and attempt < len(RETRY_BACKOFFS):
                time.sleep(RETRY_BACKOFFS[attempt])
                continue
            body = b"" if method == "HEAD" else (e.read() or b"")
            return HttpResult(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body)
        except urllib_error.URLError as e:
            last_url_err = e
            if attempt < len(RETRY_BACKOFFS):
                time.sleep(RETRY_BACKOFFS[attempt])
                continue
            raise
    # Unreachable: the loop above either returns or raises on the last attempt.
    raise last_url_err if last_url_err else RuntimeError("unreachable")


def http_get(url: str, headers: dict[str, str] | None = None) -> HttpResult:
    return _http("GET", url, headers=headers)


def http_head(url: str) -> HttpResult:
    return _http("HEAD", url)


# ---------------------------------------------------------------------------


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # 2-space indent + trailing newline = friendly diffs in tracked manifests.
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _safe_basename(name: str | None) -> str | None:
    """Reject any path-shaped value that could escape the destination dir.

    Mirrors lib/icons/downloader.py:_safe_basename for the same reason
    (defense-in-depth against a CDN regression or MITM serving "../etc/x.png").
    """
    if not name or not isinstance(name, str):
        return None
    if "/" in name or "\\" in name:
        return None
    if name in (".", "..") or name.startswith("."):
        return None
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch != "\x00")
    # ntpath.basename also strips a Windows drive prefix ("C:foo" -> "foo") on
    # POSIX, so a drive-letter asset name is rejected on the Linux CI too.
    if (cleaned != name or os.path.basename(name) != name
            or ntpath.basename(name) != name):
        return None
    return name


def _safe_relpath(rel: str | None) -> str | None:
    """Validate a multi-segment relative asset path (rune icons).

    DDragon rune icons are referenced like
    ``perk-images/Styles/Domination/Electrocute/Electrocute.png`` and must
    stay rooted under img/. Reject absolute paths, ``..`` traversal,
    backslashes, and any segment that fails _safe_basename.
    """
    if not rel or not isinstance(rel, str):
        return None
    if "\\" in rel or rel.startswith("/"):
        return None
    parts = rel.split("/")
    if not parts:
        return None
    for p in parts:
        if _safe_basename(p) is None:
            return None
    return "/".join(parts)


# ---------------------------------------------------------------------------


@dataclass
class Asset:
    """One file we plan to download.

    ``rel_dest`` is the path under ``web/data/ddragon/<ver>/`` (forward slashes).
    """
    cls: str
    url: str
    rel_dest: str


@dataclass
class PlanStats:
    total: int = 0
    skipped_present: int = 0
    fetched_new: int = 0
    fetched_changed: int = 0
    failed: int = 0
    by_class: dict[str, list[int]] = field(default_factory=dict)  # cls -> [total,new,changed,fail]

    def bump(self, cls: str, key: str) -> None:
        row = self.by_class.setdefault(cls, [0, 0, 0, 0])
        idx = {"total": 0, "new": 1, "changed": 2, "fail": 3}[key]
        row[idx] += 1


# ---------------------------------------------------------------------------


def resolve_latest_version() -> str:
    """Pull versions.json and return entry [0] (the live patch)."""
    res = http_get(VERSIONS_URL)
    if res.status != 200:
        raise RuntimeError(f"versions.json HTTP {res.status}")
    versions = json.loads(res.body.decode("utf-8"))
    if not versions or not isinstance(versions, list):
        raise RuntimeError("versions.json returned empty list")
    # RM-353: entry [0] becomes META_DIR / WEB_DIR path segments downstream.
    return validate_version(versions[0])


def read_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {}


def write_index(version: str, bundles: Iterable[str]) -> None:
    _atomic_write_json(INDEX_PATH, {
        "latest_pulled": version,
        "locale": DEFAULT_LOCALE,
        "bundles": sorted(set(bundles)),
    })


def manifest_path(version: str) -> Path:
    return META_DIR / version / "_assets_manifest.json"


def read_manifest(version: str) -> dict:
    p = manifest_path(version)
    if not p.exists():
        return {"version": version, "assets": {}}
    raw = p.read_text(encoding="utf-8")
    if not raw.strip():
        return {"version": version, "assets": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("manifest %s corrupt - rebuilding from scratch", p)
        return {"version": version, "assets": {}}
    if not isinstance(data, dict):
        return {"version": version, "assets": {}}
    data.setdefault("version", version)
    data.setdefault("assets", {})
    return data


def write_manifest(version: str, manifest: dict) -> None:
    manifest["version"] = version
    manifest["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _atomic_write_json(manifest_path(version), manifest)


# ---------------------------------------------------------------------------


def pull_bundle(version: str, name: str) -> Any:
    """Download a bundle JSON and persist it under data/meta_build/ddragon/<ver>/."""
    url = f"{DDRAGON_BASE}/cdn/{version}/data/{DEFAULT_LOCALE}/{name}.json"
    res = http_get(url)
    if res.status != 200:
        raise RuntimeError(f"bundle {name}@{version}: HTTP {res.status}")
    try:
        data = json.loads(res.body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"bundle {name}@{version}: invalid JSON ({e})") from e
    if not data:
        raise RuntimeError(f"bundle {name}@{version}: empty body")
    dest = META_DIR / version / f"{name}.json"
    _atomic_write_json(dest, data)
    logger.info("bundle %s@%s cached (%d bytes)", name, version, len(res.body))
    return data


def read_or_pull_bundle(version: str, name: str, *, force: bool = False) -> Any:
    dest = META_DIR / version / f"{name}.json"
    if dest.exists() and not force:
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
            if data:
                return data
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning("bundle cache %s corrupt (%s) - re-pulling", dest, e)
    return pull_bundle(version, name)


def pull_champion_detail(version: str, champion_key: str) -> dict | None:
    """Fetch /cdn/<ver>/data/<locale>/champion/<Name>.json (per-champion detail).

    The summary champion.json does NOT include ``spells`` / ``passive``;
    those live in the per-champion detail JSON. Cached under
    ``data/meta_build/ddragon/<ver>/champion_detail/<Name>.json`` so an
    unchanged-patch re-run is a no-op.
    """
    url = f"{DDRAGON_BASE}/cdn/{version}/data/{DEFAULT_LOCALE}/champion/{champion_key}.json"
    res = http_get(url)
    if res.status != 200:
        logger.warning("champion detail %s@%s: HTTP %d", champion_key, version, res.status)
        return None
    try:
        data = json.loads(res.body.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.warning("champion detail %s@%s: invalid JSON (%s)", champion_key, version, e)
        return None
    dest = META_DIR / version / "champion_detail" / f"{champion_key}.json"
    _atomic_write_json(dest, data)
    return data


def read_or_pull_champion_detail(version: str, champion_key: str, *,
                                 force: bool = False) -> dict | None:
    dest = META_DIR / version / "champion_detail" / f"{champion_key}.json"
    if dest.exists() and not force:
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
            if data:
                return data
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning("champion detail cache %s corrupt (%s) - re-pulling", dest, e)
    return pull_champion_detail(version, champion_key)


def pull_all_champion_details(version: str, summary: dict, *, force: bool = False,
                              rate_limit: float = MIN_INTERVAL_SEC) -> dict[str, dict]:
    """Pull per-champion detail for every champion in the summary bundle."""
    out: dict[str, dict] = {}
    keys = list((summary or {}).get("data", {}).keys())
    last = 0.0
    for key in keys:
        delta = time.monotonic() - last
        if delta < rate_limit:
            time.sleep(rate_limit - delta)
        data = read_or_pull_champion_detail(version, key, force=force)
        last = time.monotonic()
        if data:
            out[key] = data
    logger.info("champion_detail pulled %d/%d", len(out), len(keys))
    return out


# ---------------------------------------------------------------------------


def enumerate_assets(version: str, bundles: dict[str, Any]) -> list[Asset]:
    """Walk each bundle JSON and yield every Asset URL we want mirrored."""
    out: list[Asset] = []

    base = f"{DDRAGON_BASE}/cdn/{version}/img"

    # Champions - square portrait (from summary) + ability spells + passive
    # (from per-champion detail; the summary bundle drops both).
    champs = bundles.get("champion", {}).get("data", {})
    for key, meta in champs.items():
        img = (meta.get("image") or {}).get("full")
        bn = _safe_basename(img)
        if bn:
            out.append(Asset("champion", f"{base}/champion/{bn}", f"img/champion/{bn}"))
        # Inline spells/passive only fire when the caller stitched the detail
        # JSON into the summary entry (the stub bundles in tests do this).
        passive = (meta.get("passive") or {}).get("image") or {}
        pn = _safe_basename(passive.get("full"))
        if pn:
            out.append(Asset("passive", f"{base}/passive/{pn}", f"img/passive/{pn}"))
        for spell in meta.get("spells") or []:
            sn = _safe_basename((spell.get("image") or {}).get("full"))
            if sn:
                out.append(Asset("spell", f"{base}/spell/{sn}", f"img/spell/{sn}"))

    # Per-champion detail bundles (champion_detail[Name]["data"][Name]).
    details = bundles.get("champion_detail") or {}
    for key, detail in details.items():
        rec = ((detail or {}).get("data") or {}).get(key) or {}
        passive = (rec.get("passive") or {}).get("image") or {}
        pn = _safe_basename(passive.get("full"))
        if pn:
            out.append(Asset("passive", f"{base}/passive/{pn}", f"img/passive/{pn}"))
        for spell in rec.get("spells") or []:
            sn = _safe_basename((spell.get("image") or {}).get("full"))
            if sn:
                out.append(Asset("spell", f"{base}/spell/{sn}", f"img/spell/{sn}"))

    # Items
    for iid, meta in bundles.get("item", {}).get("data", {}).items():
        bn = _safe_basename((meta.get("image") or {}).get("full"))
        if bn:
            out.append(Asset("item", f"{base}/item/{bn}", f"img/item/{bn}"))

    # Summoner spells
    for _key, meta in bundles.get("summoner", {}).get("data", {}).items():
        bn = _safe_basename((meta.get("image") or {}).get("full"))
        if bn:
            out.append(Asset("spell", f"{base}/spell/{bn}", f"img/spell/{bn}"))

    # Profile icons
    for _key, meta in bundles.get("profileicon", {}).get("data", {}).items():
        bn = _safe_basename((meta.get("image") or {}).get("full"))
        if bn:
            out.append(Asset("profileicon", f"{base}/profileicon/{bn}", f"img/profileicon/{bn}"))

    # Maps
    for mid in MAP_IDS:
        bn = f"map{mid}.png"
        out.append(Asset("map", f"{base}/map/{bn}", f"img/map/{bn}"))

    # Runes - icons live under /cdn/img/<perk path>, version-less.
    runes_root = bundles.get("runesReforged", [])
    if isinstance(runes_root, list):
        for tree in runes_root:
            tree_icon = _safe_relpath(tree.get("icon"))
            if tree_icon:
                out.append(Asset("rune", f"{DDRAGON_BASE}/cdn/img/{tree_icon}",
                                 f"img/{tree_icon}"))
            for slot in tree.get("slots") or []:
                for rune in slot.get("runes") or []:
                    ri = _safe_relpath(rune.get("icon"))
                    if not ri:
                        continue
                    out.append(Asset("rune", f"{DDRAGON_BASE}/cdn/img/{ri}", f"img/{ri}"))

    # De-dup by rel_dest (summoner+champion both write img/spell/...)
    seen: set[str] = set()
    deduped: list[Asset] = []
    for a in out:
        if a.rel_dest in seen:
            continue
        seen.add(a.rel_dest)
        deduped.append(a)
    return deduped


# ---------------------------------------------------------------------------


def _sha256_hex(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fetch_one(asset: Asset, dest: Path, *, manifest_entry: dict | None,
              check_changed: bool, force: bool) -> tuple[str, dict | None]:
    """Fetch (or skip) a single asset.

    Returns (status, new_manifest_entry):
      status in {"skip_present", "new", "changed", "fail_404", "fail_other"}.
      new_manifest_entry is None on skip; populated dict otherwise.
    """
    if force:
        decide = "fetch"
    elif not dest.exists():
        decide = "fetch"
    elif check_changed:
        # HEAD probe; compare against manifest etag/size.
        head = http_head(asset.url)
        if head.status != 200:
            decide = "fetch"  # treat HEAD failure as "go fetch and let GET handle it"
        else:
            etag = head.headers.get("etag")
            length = head.headers.get("content-length")
            try:
                size_new = int(length) if length is not None else None
            except ValueError:
                size_new = None
            known_etag = (manifest_entry or {}).get("etag")
            known_size = (manifest_entry or {}).get("size")
            if etag and known_etag and etag == known_etag:
                return "skip_present", None
            if size_new is not None and known_size == size_new and not known_etag:
                # Same size, no etag tracked - good enough to skip.
                return "skip_present", None
            decide = "fetch"
    else:
        return "skip_present", None

    headers: dict[str, str] = {}
    if check_changed and manifest_entry and manifest_entry.get("etag"):
        headers["If-None-Match"] = manifest_entry["etag"]

    res = http_get(asset.url, headers=headers)
    if res.status == 404:
        # CDN edge 404s under load can be transient; one retry before failing.
        res = http_get(asset.url, headers=headers)
    if res.status == 304:
        return "skip_present", None
    if res.status == 404:
        return "fail_404", None
    if res.status != 200:
        return "fail_other", None

    _atomic_write_bytes(dest, res.body)
    new_entry = {
        "size": len(res.body),
        "sha256": _sha256_hex(res.body),
    }
    et = res.headers.get("etag")
    if et:
        new_entry["etag"] = et
    lm = res.headers.get("last-modified")
    if lm:
        new_entry["last_modified"] = lm
    status = "changed" if manifest_entry is not None else "new"
    return status, new_entry


def run(version: str, *, dry_run: bool, check_changed: bool, force: bool,
        rate_limit: float = MIN_INTERVAL_SEC,
        workers: int = DEFAULT_WORKERS) -> PlanStats:
    manifest = read_manifest(version)
    bundles: dict[str, Any] = {}
    for name in BUNDLE_NAMES:
        bundles[name] = read_or_pull_bundle(version, name, force=force)

    # Per-champion detail JSONs (for spells + passive icons).
    bundles["champion_detail"] = pull_all_champion_details(
        version, bundles.get("champion") or {}, force=force, rate_limit=rate_limit,
    )

    assets = enumerate_assets(version, bundles)
    stats = PlanStats(total=len(assets))
    version_dir = WEB_DIR / version

    if dry_run:
        for a in assets:
            stats.bump(a.cls, "total")
        return stats

    manifest_lock = threading.Lock()
    stats_lock = threading.Lock()

    def _work(a: Asset) -> None:
        dest = version_dir / a.rel_dest
        with manifest_lock:
            me = manifest["assets"].get(a.rel_dest)
        with stats_lock:
            stats.bump(a.cls, "total")
        try:
            status, new_entry = fetch_one(a, dest, manifest_entry=me,
                                          check_changed=check_changed, force=force)
        except Exception as e:  # noqa: BLE001 - network anomalies are heterogeneous
            logger.warning("fetch %s failed: %s", a.url, e)
            with stats_lock:
                stats.failed += 1
                stats.bump(a.cls, "fail")
            return
        with stats_lock:
            if status == "skip_present":
                stats.skipped_present += 1
            elif status == "new":
                stats.fetched_new += 1
                stats.bump(a.cls, "new")
            elif status == "changed":
                stats.fetched_changed += 1
                stats.bump(a.cls, "changed")
            elif status.startswith("fail"):
                stats.failed += 1
                stats.bump(a.cls, "fail")
                logger.warning("fetch %s -> %s", a.url, status)
        if new_entry is not None and status in ("new", "changed"):
            with manifest_lock:
                manifest["assets"][a.rel_dest] = new_entry

    stats.total = len(assets)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = [ex.submit(_work, a) for a in assets]
        # Drain via as_completed for prompt error visibility; result is None.
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                logger.warning("worker raised: %s", e)
                with stats_lock:
                    stats.failed += 1

    write_manifest(version, manifest)
    return stats


# ---------------------------------------------------------------------------


# RM-353: the SAME object the version validator accepts, aliased rather than
# re-declared so the "everything we create is prunable" invariant cannot drift.
_SEMVER_DIR = VERSION_RE
RETAIN_VERSIONS = 2  # current patch + one previous


def prune_stale_versions(current: str, *, retain: int = RETAIN_VERSIONS,
                         web_dir: Path = WEB_DIR, dry_run: bool = False) -> list[str]:
    """Delete stale ``web_dir/<semver>/`` mirror dirs beyond the retention set.

    The retention set is the current patch plus the newest dirs until
    ``retain`` versions are held. Only semver-named directories directly
    under ``web_dir`` are candidates - ``_index.json``, perk-image trees and
    anything else are never touched, and the git-tracked bundle archives
    under data/meta_build/ are out of scope entirely. Returns the sorted
    names of removed (or, under ``dry_run``, would-be-removed) dirs.
    """
    if not web_dir.is_dir():
        return []
    versioned = [d for d in web_dir.iterdir()
                 if d.is_dir() and _SEMVER_DIR.match(d.name)]
    versioned.sort(key=lambda d: tuple(int(x) for x in d.name.split(".")),
                   reverse=True)
    keep = {current}
    for d in versioned:
        if len(keep) >= max(retain, 1):
            break
        keep.add(d.name)
    removed = []
    for d in versioned:
        if d.name in keep:
            continue
        removed.append(d.name)
        if not dry_run:
            # A version entry can be a symlink/junction alias (the live
            # mirror had 16.9.1 -> 16.8.1); rmtree refuses reparse points,
            # so unlink the link itself and leave its target alone.
            if d.is_symlink() or d.is_junction():
                os.rmdir(d)
            else:
                shutil.rmtree(d)
            logger.info("pruned stale mirror dir %s", d)
    return sorted(removed)


def cmd_check_only(latest: str, cached: str | None) -> int:
    if latest != cached:
        print(f"flip_pending latest={latest} cached={cached!r}")
        return 1
    # If versions match, the cheap heuristic is "are there any assets at all in
    # web/data/ddragon/<ver>/?" If yes, assume up-to-date. A --check-changed run
    # is the real mid-patch trigger.
    version_dir = WEB_DIR / latest
    if not version_dir.exists():
        print(f"no_mirror_dir latest={latest}")
        return 1
    print(f"up_to_date version={latest}")
    return 0


def render_stats_table(stats: PlanStats) -> str:
    lines = ["class         total   new  chg  fail"]
    for cls in sorted(stats.by_class):
        row = stats.by_class[cls]
        lines.append(f"  {cls:<10} {row[0]:>5}  {row[1]:>4} {row[2]:>4} {row[3]:>5}")
    lines.append(f"TOTAL         {stats.total:>5}  "
                 f"new={stats.fetched_new} chg={stats.fetched_changed} "
                 f"skip={stats.skipped_present} fail={stats.failed}")
    return "\n".join(lines)


def _failures_within_tolerance(stats: PlanStats) -> bool:
    """True when the run had no failures, or only a tolerable transient ratio.

    A handful of transient single-asset HEAD/GET flakes across thousands of CDN
    probes is operationally normal. This predicate is the single source of truth
    for "was this run effectively clean?" - both the exit code and the index
    advance gate consume it, so a tolerable flake never blocks a version flip.
    """
    if not stats.failed:
        return True
    return stats.failed / (stats.total or 1) <= FAIL_RATIO_TOLERANCE


def _exit_code_for(stats: PlanStats) -> int:
    """Map run stats to a process exit code.

    Exit 2 only when the failure ratio exceeds FAIL_RATIO_TOLERANCE (a genuine
    partial outage / mass-missing-asset event); a tolerable transient flake
    exits 0 so it never trips the nightly cron's last_result canary.
    """
    if _failures_within_tolerance(stats):
        if stats.failed:
            logger.warning("tolerating %d/%d transient asset failures (%.3f%% <= %.1f%%)",
                           stats.failed, stats.total,
                           stats.failed / (stats.total or 1) * 100,
                           FAIL_RATIO_TOLERANCE * 100)
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Refresh the local DDragon mirror.")
    p.add_argument("--check-only", action="store_true",
                   help="exit 0 if up-to-date, 1 if a flip is pending")
    p.add_argument("--dry-run", action="store_true",
                   help="enumerate the asset plan but make no network writes")
    p.add_argument("--check-changed", action="store_true",
                   help="HEAD probe + re-fetch when ETag/size differs")
    p.add_argument("--full", action="store_true",
                   help="ignore manifest, re-fetch every asset")
    p.add_argument("--version", default=None,
                   help="pin a specific patch version (default = CDN latest)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"parallel asset fetchers (default {DEFAULT_WORKERS})")
    p.add_argument("--retain", type=int, default=RETAIN_VERSIONS,
                   help=f"mirror version dirs to keep (default {RETAIN_VERSIONS})")
    p.add_argument("--no-prune", action="store_true",
                   help="skip stale version-dir pruning after a clean run")
    p.add_argument("--log-level", default="INFO",
                   choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # RM-353: --version is operator input and reaches the same path joins, so
    # it is validated here rather than inside the resolver alone.
    latest = validate_version(args.version or resolve_latest_version())
    index = read_index()
    cached = index.get("latest_pulled")

    if args.check_only:
        return cmd_check_only(latest, cached)

    logger.info("ddragon_mirror_refresh start version=%s cached=%s mode=%s",
                latest, cached,
                "dry-run" if args.dry_run else
                "full" if args.full else
                "check-changed" if args.check_changed else "default")

    stats = run(latest, dry_run=args.dry_run, check_changed=args.check_changed,
                force=args.full, workers=args.workers)

    print(render_stats_table(stats))

    if (not args.dry_run and _failures_within_tolerance(stats)
            and (stats.fetched_new or stats.fetched_changed or cached != latest)):
        write_index(latest, BUNDLE_NAMES)
        logger.info("index updated latest_pulled=%s", latest)
    elif stats.failed and not _failures_within_tolerance(stats):
        logger.warning("kept index at %s due to %d/%d failures over tolerance",
                       cached, stats.failed, stats.total)

    if not args.dry_run and not args.no_prune and _failures_within_tolerance(stats):
        pruned = prune_stale_versions(latest, retain=args.retain)
        if pruned:
            print(f"pruned stale mirror dirs: {', '.join(pruned)}")

    return _exit_code_for(stats)


if __name__ == "__main__":
    sys.exit(main())
