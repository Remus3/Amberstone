"""
tft/assets/icon_cache.py
Runtime cache of TFT champion / item / trait / augment icons for one set
(TFT-03; docs/TFT_PROGRAM.md section 3.6 and section 7; ADR-018).

LICENCE GATE (CLAUDE.md "Third-party lift"): DO-NOT-VENDOR. Every icon is
Riot art - the running League client's own lol-game-data files, or
CommunityDragon's mirror of them (CommunityDragon publishes no licence and
mirrors Riot game files; NOTICE "CommunityDragon (CDragon)"). RC is PUBLIC
Apache-2.0, so the icons are fetched at runtime into the GITIGNORED tree
data/tft/icon_cache/<set>/<category>/ and used locally only: never committed,
never exported in a fixture. The cache root drops a self-ignoring
`.gitignore` ("*") so `git add -A` cannot stage it even before the repo-level
`data/tft/` ignore rule (TFT-01) lands. NOTICE carries the matching line.

WHAT IS FETCHED
- Membership (which apiNames belong to the set) comes from the tracked
  reduced CommunityDragon extract data/meta/tft_set<N>_cdragon.json
  (tft/tft_set.py `load_cdragon`): units -> champion, traits -> trait,
  items -> item, augments -> augment. Without an extract, champions come from
  the planner rows of TFTSet<N> and traits from the tfttraits.json rows whose
  `set` is TFTSet<N>; items and augments then stay empty because
  tftitems.json carries no set field (measured).
- Icon paths come from the client's game-data documents (measured shapes,
  passive LCU GET, live Set 18 client, 2026-10-25):
    tftchampions.json   [{"character_record": {"character_id", "squareIconPath"}}]
    tftchampions-teamplanner.json {"TFTSet18": [{"character_id", "squareIconPath"}]}
    tfttraits.json      [{"trait_id", "set", "icon_path"}]
    tftitems.json       [{"nameId", "squareIconPath"}]  (augments included)
  All 1481 Set 18 members (74 units, 36 traits, 776 items, 595 augments)
  resolved to a `/lol-game-data/assets/...` .png / .jpg path that day, 686
  distinct paths (items share icons, so a run GETs each path once: the live
  fill made 686 LCU GETs).

SOURCES, IN ORDER (passive GET only - no other HTTP method exists here)
1. LCU: https://<RC_GAME_HOST>:<lockfile port>/lol-game-data/assets/... with
   the lockfile's Basic auth (lcu/lcu_client.py `_parse_lockfile_fields`).
   Local, no internet, exactly the running client's art.
2. CommunityDragon: the same plugin files and assets under
   raw.communitydragon.org/<branch>/plugins/rcp-be-lol-game-data/global/default/
   with the path after /lol-game-data/assets/ lowercased (measured 200
   image/png 2026-10-25). Adjudicated against the spec's alternative of
   resolving paths from cdragon/tft/en_us.json: that document is 24 MB versus
   about 2.5 MB for the four plugin files, its game-WAD .tex paths need a
   second, different URL rule (a converted Set 18 trait path measured 404),
   and the plugin mirror lets ONE parser serve both sources.
The catalogue (game-data documents) comes from the first source that answers
every needed document; each icon is then tried on every live source in order.
The LCU password is sent to the LCU only, never to CommunityDragon.

OFFLINE-SAFE: no source answering = status "offline" and the cache is left
byte-for-byte untouched. A re-run reuses every entry whose file still hashes
to its index sha256 and whose asset path is unchanged, so it fetches nothing.
RATE-LIMITED: each source keeps a minimum interval between its GETs.

INDEX: data/tft/icon_cache/<set>/index.json (ASCII, LF, atomic) maps
category -> apiName -> {"file", "sha256", "bytes", "src", "asset"}. Read it
through `icon_path` (TFT-09 serves /api/tft/icon/<cat>/<api> from it, 404 when
None). Files are named <apiName>.<png|jpg> by magic bytes, so the TFT-05 atlas
loader (core/vision_template_match.py reads <dir>/*.png by stem) can point at
`category_dir`; a stale file from an older patch is never deleted here, so a
consumer that must be exact reads the index, not the directory.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request as urllib_request
from dataclasses import dataclass, field
from pathlib import Path

from core import polled_json, tls_policy
from tft import tft_set

logger = logging.getLogger("rc.tft.icons")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_REL = Path("data") / "tft" / "icon_cache"
INDEX_NAME = "index.json"
INDEX_SCHEMA = 1
CATEGORIES = ("champion", "item", "trait", "augment")
EXTRACT_KEYS = {"champion": "units", "item": "items", "trait": "traits",
                "augment": "augments"}

# The running set is tftsets.json mDefaultSet unless the queue says otherwise
# (queue 6110 = the "Set 17 (Normal)" revival while mDefaultSet reads
# TFTSet18). ONE table, owned by tft/tft_set.py (LT-01); this is an alias.
QUEUE_SET = tft_set.QUEUE_SETS

DOC_SETS = "tftsets.json"
DOC_CHAMPIONS = "tftchampions.json"
DOC_PLANNER = "tftchampions-teamplanner.json"
DOC_TRAITS = "tfttraits.json"
DOC_ITEMS = "tftitems.json"
GAME_DATA_DOCS = (DOC_CHAMPIONS, DOC_PLANNER, DOC_TRAITS, DOC_ITEMS)
DOCS_FOR = {"champion": (DOC_CHAMPIONS, DOC_PLANNER), "trait": (DOC_TRAITS,),
            "item": (DOC_ITEMS,), "augment": (DOC_ITEMS,)}

LCU_ASSET_PREFIX = "/lol-game-data/assets/"
LCU_GAME_DATA_V1 = LCU_ASSET_PREFIX + "v1/"
LCU_GAMEFLOW_SESSION = "/lol-gameflow/v1/session"
CDRAGON_PLUGIN = ("https://raw.communitydragon.org/{branch}/plugins/"
                  "rcp-be-lol-game-data/global/default/")
BRANCHES = ("latest", "pbe")
USER_AGENT = "Amberstone/tft-icon-cache/1.0"

LCU_INTERVAL_S = 0.05
CDRAGON_INTERVAL_S = 0.25
LCU_TIMEOUT_S = 10.0
CDRAGON_TIMEOUT_S = 30.0
MAX_ICON_BYTES = 4 * 1024 * 1024
MAX_DOC_BYTES = 32 * 1024 * 1024
# Consecutive failed icon GETs after which a source is skipped for the rest of
# the run (the client closed mid-run, or the CDN is down): bounds a dead
# source's cost to this many timeouts instead of one per icon.
SOURCE_FAIL_LIMIT = 25
INDEX_FLUSH_EVERY = 100
MAX_FAILURES_KEPT = 200

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_ASSET_RE = re.compile(
    r"^/lol-game-data/assets/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?i:png|jpe?g)$")
_FILE_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:png|jpg)$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL",
                       *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))})
_STEM_MAX = 96


# -- paths ------------------------------------------------------------------------

def _set_number(set_number) -> int:
    n = tft_set.parse_set_id(set_number)
    if n is None:
        raise ValueError(f"not a TFT set number: {set_number!r}")
    return n


def cache_root(root=None) -> Path:
    return Path(root if root is not None else ROOT) / CACHE_REL


def set_dir(set_number, root=None) -> Path:
    return cache_root(root) / str(_set_number(set_number))


def category_dir(set_number, category, root=None) -> Path:
    """The per-category icon directory (the TFT-05 atlas dir)."""
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}, got {category!r}")
    return set_dir(set_number, root) / category


# -- pure helpers -----------------------------------------------------------------

def running_set(tftsets, queue_id=None) -> int | None:
    """tftsets.json mDefaultSet, overridden by a queue that runs another set.
    The pairing rule is tft/tft_set.py `set_from_lcu` (LT-01); this only digs
    the default set's name out of the tftsets.json document."""
    mode = tftsets.get("LCTFTModeData") if isinstance(tftsets, dict) else None
    default = mode.get("mDefaultSet") if isinstance(mode, dict) else None
    name = None
    if isinstance(default, dict):
        name = default.get("SetCoreName")
        if tft_set.parse_set_id(name) is None:
            name = default.get("SetName")
    return tft_set.set_from_lcu(name, queue_id)


def detect_set(sources, queue_id=None) -> int | None:
    """Ask each source able to (the LCU) for tftsets.json and the queue id."""
    for src in sources or ():
        get_sets = getattr(src, "tftsets", None)
        if not callable(get_sets):
            continue
        doc = get_sets()
        if not isinstance(doc, dict):
            continue
        q = queue_id
        if q is None:
            get_queue = getattr(src, "queue_id", None)
            q = get_queue() if callable(get_queue) else None
        n = running_set(doc, q)
        if n is not None:
            return n
    return tft_set.set_from_lcu(None, queue_id)


def valid_asset_path(path) -> bool:
    """A client asset path safe to put in a URL: /lol-game-data/assets/...png|jpg,
    7-bit [A-Za-z0-9_.-] segments, no empty / dot / dot-dot segment."""
    if not isinstance(path, str) or not _ASSET_RE.match(path):
        return False
    segments = path[len(LCU_ASSET_PREFIX):].split("/")
    return all(s and not s.startswith(".") for s in segments)


def cdragon_url(path, branch="latest") -> str:
    """LCU asset path -> CommunityDragon plugin-mirror URL (lowercased)."""
    if branch not in BRANCHES:
        raise ValueError(f"branch must be one of {BRANCHES}, got {branch!r}")
    if not valid_asset_path(path):
        raise ValueError(f"unsafe asset path: {path!r}")
    return CDRAGON_PLUGIN.format(branch=branch) + path[len(LCU_ASSET_PREFIX):].lower()


def image_kind(data) -> str | None:
    """'png' / 'jpg' by magic bytes, else None (an HTML error page is not an icon)."""
    if not isinstance(data, (bytes, bytearray)):
        return None
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpg"
    return None


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def file_stem(api_name, used=None) -> str:
    """A filesystem-safe stem for an apiName. Unchanged when already safe;
    otherwise sanitised plus a hash suffix. `used` (casefolded stem -> api)
    keeps stems distinct on a case-insensitive filesystem."""
    api = str(api_name)
    stem = _UNSAFE.sub("_", api).strip(".")[:_STEM_MAX] or "_"
    if stem != api or stem.split(".")[0].upper() in _RESERVED:
        stem = f"{stem}-{_short_hash(api)}"
    if used is not None:
        owner = used.get(stem.casefold())
        if owner is not None and owner != api:
            stem = f"{stem}-{_short_hash(api)}"
        used[stem.casefold()] = api
    return stem


# -- catalogue ----------------------------------------------------------------------

@dataclass
class Catalogue:
    paths: dict          # category -> {apiName: asset path}
    missing: dict        # category -> [apiName with no usable path]
    membership: str      # "extract" | "game_data"


def _rows(doc) -> list:
    return [r for r in doc if isinstance(r, dict)] if isinstance(doc, list) else []


def _first_valid(*paths) -> str | None:
    for p in paths:
        if valid_asset_path(p):
            return p
    return None


def _unique_api_names(rows) -> list:
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else []:
        api = r.get("apiName") if isinstance(r, dict) else None
        if isinstance(api, str) and api and api not in seen:
            seen.add(api)
            out.append(api)
    return out


def _members(n: int, docs: dict, extract) -> tuple:
    if isinstance(extract, dict) and extract.get("_set") in (None, n) and any(
            isinstance(extract.get(k), list) and extract.get(k) for k in EXTRACT_KEYS.values()):
        return {c: _unique_api_names(extract.get(EXTRACT_KEYS[c])) for c in CATEGORIES}, "extract"
    set_name = f"TFTSet{n}"
    planner = docs.get(DOC_PLANNER)
    planner_rows = _rows(planner.get(set_name)) if isinstance(planner, dict) else []
    champs = [r.get("character_id") for r in planner_rows]
    traits = [r.get("trait_id") for r in _rows(docs.get(DOC_TRAITS)) if r.get("set") == set_name]

    def uniq(values):
        out = []
        for v in values:
            if isinstance(v, str) and v and v not in out:
                out.append(v)
        return out

    return {"champion": uniq(champs), "trait": uniq(traits), "item": [], "augment": []}, "game_data"


def build_catalogue(set_number, docs, extract=None) -> Catalogue:
    """Set members (extract first) mapped to their client icon paths."""
    n = _set_number(set_number)
    docs = docs if isinstance(docs, dict) else {}
    members, membership = _members(n, docs, extract)
    set_name = f"TFTSet{n}"

    champ_paths: dict = {}
    for r in _rows(docs.get(DOC_CHAMPIONS)):
        rec = r.get("character_record")
        if isinstance(rec, dict) and isinstance(rec.get("character_id"), str):
            champ_paths.setdefault(rec["character_id"], rec.get("squareIconPath"))
    planner_paths: dict = {}
    planner = docs.get(DOC_PLANNER)
    if isinstance(planner, dict):
        keys = [set_name] + sorted(k for k in planner if k != set_name)
        for key in keys:
            for r in _rows(planner.get(key)):
                if isinstance(r.get("character_id"), str):
                    planner_paths.setdefault(r["character_id"], r.get("squareIconPath"))
    trait_paths: dict = {}
    trait_rows = _rows(docs.get(DOC_TRAITS))
    for r in sorted(trait_rows, key=lambda t: t.get("set") != set_name):
        if isinstance(r.get("trait_id"), str) and valid_asset_path(r.get("icon_path")):
            trait_paths.setdefault(r["trait_id"], r["icon_path"])
    item_paths: dict = {}
    for r in _rows(docs.get(DOC_ITEMS)):
        if isinstance(r.get("nameId"), str) and valid_asset_path(r.get("squareIconPath")):
            item_paths.setdefault(r["nameId"], r["squareIconPath"])

    def resolve(category, api):
        if category == "champion":
            return _first_valid(champ_paths.get(api), planner_paths.get(api))
        if category == "trait":
            return trait_paths.get(api)
        return item_paths.get(api)

    paths = {c: {} for c in CATEGORIES}
    missing = {c: [] for c in CATEGORIES}
    for c in CATEGORIES:
        for api in members[c]:
            p = resolve(c, api)
            if p:
                paths[c][api] = p
            else:
                missing[c].append(api)
    return Catalogue(paths=paths, missing=missing, membership=membership)


# -- HTTP (GET only) ------------------------------------------------------------------

def _http_get(url, *, headers=None, private_headers=None, context=None,
              timeout=CDRAGON_TIMEOUT_S, max_bytes=MAX_ICON_BYTES) -> bytes | None:
    """One passive GET; the body, or None on any failure or an oversize body.

    private_headers are attached as urllib UNREDIRECTED headers: the redirect
    handler never copies them onto a redirected request, so a credential sent
    to one host cannot follow a redirect to another."""
    req = urllib_request.Request(url, headers=dict(headers or {}), method="GET")
    for key, value in (private_headers or {}).items():
        req.add_unredirected_header(key, value)
    try:
        with urllib_request.urlopen(req, context=context, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        logger.debug("GET %s failed: %s", url.split("?")[0], type(exc).__name__)
        return None
    if not isinstance(body, (bytes, bytearray)) or len(body) > max_bytes:
        return None
    return bytes(body)


def _json(body):
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


class LcuSource:
    """The running League client's own lol-game-data assets (GET only)."""

    name = "lcu"

    def __init__(self, port, password, *, host=None, min_interval_s=LCU_INTERVAL_S,
                 timeout=LCU_TIMEOUT_S):
        if host is None:
            from core.game_host import GAME_HOST
            host = GAME_HOST
        self.port = int(port)
        self.host = host
        self.min_interval_s = float(min_interval_s)
        self.timeout = float(timeout)
        token = base64.b64encode(f"riot:{password}".encode()).decode("ascii")
        self._headers = {"Accept": "*/*"}
        self._auth = {"Authorization": f"Basic {token}"}
        # The LCU serves Riot's self-signed certificate on loopback: the RC
        # no-verify client context at the RM-752 protocol floor.
        self._ctx = tls_policy.client_context_noverify()

    @classmethod
    def discover(cls, *, lockfiles=None, host=None, min_interval_s=LCU_INTERVAL_S):
        """A source from the first readable lockfile, else None (client closed)."""
        from lcu.lcu_client import _LOCKFILE_PATHS, _parse_lockfile_fields
        for lf in lockfiles if lockfiles is not None else _LOCKFILE_PATHS:
            try:
                text = Path(lf).read_text(encoding="utf-8")
                port, password = _parse_lockfile_fields(text)
            except (OSError, IndexError, ValueError):
                continue
            return cls(port, password, host=host, min_interval_s=min_interval_s)
        return None

    def _get(self, path, max_bytes):
        return _http_get(f"https://{self.host}:{self.port}{path}", headers=self._headers,
                         private_headers=self._auth, context=self._ctx,
                         timeout=self.timeout, max_bytes=max_bytes)

    def game_data(self, doc):
        if doc not in GAME_DATA_DOCS and doc != DOC_SETS:
            return None
        return _json(self._get(LCU_GAME_DATA_V1 + doc, MAX_DOC_BYTES))

    def asset(self, path):
        if not valid_asset_path(path):
            return None
        return self._get(path, MAX_ICON_BYTES)

    def tftsets(self):
        doc = self.game_data(DOC_SETS)
        return doc if isinstance(doc, dict) else None

    def queue_id(self):
        doc = _json(self._get(LCU_GAMEFLOW_SESSION, MAX_DOC_BYTES))
        game = doc.get("gameData") if isinstance(doc, dict) else None
        queue = game.get("queue") if isinstance(game, dict) else None
        qid = queue.get("id") if isinstance(queue, dict) else None
        return qid if isinstance(qid, int) and not isinstance(qid, bool) and qid > 0 else None


class CDragonSource:
    """CommunityDragon's mirror of the same lol-game-data plugin (GET only)."""

    name = "cdragon"

    def __init__(self, branch="latest", *, min_interval_s=CDRAGON_INTERVAL_S,
                 timeout=CDRAGON_TIMEOUT_S):
        if branch not in BRANCHES:
            raise ValueError(f"branch must be one of {BRANCHES}, got {branch!r}")
        self.branch = branch
        self.min_interval_s = float(min_interval_s)
        self.timeout = float(timeout)
        self._headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}

    def game_data(self, doc):
        if doc not in GAME_DATA_DOCS:
            return None
        url = CDRAGON_PLUGIN.format(branch=self.branch) + "v1/" + doc
        return _json(_http_get(url, headers=self._headers, timeout=self.timeout,
                               max_bytes=MAX_DOC_BYTES))

    def asset(self, path):
        try:
            url = cdragon_url(path, self.branch)
        except ValueError:
            return None
        return _http_get(url, headers=self._headers, timeout=self.timeout,
                         max_bytes=MAX_ICON_BYTES)


# -- index ----------------------------------------------------------------------------

def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Per-writer scratch + fsync + retried rename (RM-258 / RM-261 contract)."""
    polled_json.atomic_write_bytes(path, data)


def load_index(set_number, root=None) -> dict:
    """The set's index, or {} when absent / unreadable / another schema."""
    try:
        doc = json.loads((set_dir(set_number, root) / INDEX_NAME).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != INDEX_SCHEMA:
        return {}
    return doc


def _entry_file(base: Path, category: str, entry) -> Path | None:
    rel = entry.get("file") if isinstance(entry, dict) else None
    if not isinstance(rel, str):
        return None
    parts = rel.split("/")
    if len(parts) != 2 or parts[0] != category or not _FILE_RE.match(parts[1]):
        return None
    p = base / category / parts[1]
    return p if p.is_file() else None


def _sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def icon_path(set_number, category, api_name, root=None, verify=False) -> Path | None:
    """The cached icon file for (set, category, apiName), or None (= HTTP 404).
    verify=True also re-hashes the file against the index sha256."""
    if category not in CATEGORIES:
        return None
    try:
        base = set_dir(set_number, root)
    except ValueError:
        return None
    entries = load_index(set_number, root).get("entries")
    cat = entries.get(category) if isinstance(entries, dict) else None
    entry = cat.get(api_name) if isinstance(cat, dict) else None
    p = _entry_file(base, category, entry)
    if p is None:
        return None
    if verify and _sha256_file(p) != entry.get("sha256"):
        return None
    return p


def _reusable(base: Path, category: str, entry, asset: str) -> bool:
    if not isinstance(entry, dict) or entry.get("asset") != asset:
        return False
    p = _entry_file(base, category, entry)
    if p is None:
        return False
    try:
        data = p.read_bytes()
    except OSError:
        return False
    return image_kind(data) is not None and hashlib.sha256(data).hexdigest() == entry.get("sha256")


def _ensure_self_ignored(root=None) -> None:
    marker = cache_root(root) / ".gitignore"
    try:
        if marker.read_bytes() == b"*\n":
            return
    except OSError:
        pass
    _atomic_write_bytes(marker, b"*\n")


# -- fill -------------------------------------------------------------------------------

def _zero_counts() -> dict:
    return {"wanted": 0, "cached": 0, "fetched": 0, "failed": 0, "skipped": 0}


@dataclass
class FillReport:
    set_number: int
    cache_dir: Path
    status: str = "offline"            # ok | partial | offline | dry_run
    catalogue_source: str | None = None
    membership: str | None = None
    counts: dict = field(default_factory=dict)
    by_source: dict = field(default_factory=dict)
    missing: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)
    planned: int = 0                   # dry run: icons that would be fetched
    planned_gets: int = 0              # dry run: distinct asset GETs for them

    def summary(self) -> str:
        if self.status == "offline":
            return (f"set {self.set_number}: offline - no source answered the game-data "
                    f"catalogue; cache unchanged ({self.cache_dir})")
        parts = []
        for c, k in self.counts.items():
            parts.append(f"{c} {k['cached'] + k['fetched']}/{k['wanted']}")
        tot = {key: sum(k[key] for k in self.counts.values())
               for key in ("cached", "fetched", "failed", "skipped")}
        srcs = ", ".join(f"{name} {n}" for name, n in sorted(self.by_source.items())) or "none"
        tail = (f"would fetch {self.planned} icons in {self.planned_gets} GETs"
                if self.status == "dry_run" else
                f"fetched {tot['fetched']} ({srcs}), cached {tot['cached']}, "
                f"failed {tot['failed']}, skipped {tot['skipped']}")
        n_missing = sum(len(v) for v in self.missing.values())
        return (f"set {self.set_number} ({self.catalogue_source} catalogue, {self.membership} "
                f"membership): {', '.join(parts)}; {tail}; no icon path {n_missing} "
                f"-> {self.cache_dir} [{self.status}]")


class _Pacer:
    """Minimum interval between successive GETs to the same source."""

    def __init__(self, clock, sleep):
        self._clock = clock
        self._sleep = sleep
        self._last: dict = {}

    def wait(self, src) -> None:
        interval = max(0.0, float(getattr(src, "min_interval_s", 0.0) or 0.0))
        last = self._last.get(id(src))
        if last is not None and interval > 0:
            gap = self._clock() - last
            if gap < interval:
                self._sleep(interval - gap)
        self._last[id(src)] = self._clock()


def _call(fn, arg):
    try:
        return fn(arg)
    except (OSError, ValueError, TypeError) as exc:
        logger.debug("source call failed: %s", type(exc).__name__)
        return None


def _iso_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_index(base: Path, n: int, entries: dict, missing: dict, report: FillReport) -> None:
    doc = {
        "schema": INDEX_SCHEMA,
        "set": n,
        "updated": _iso_now(),
        "note": ("Riot game art cached at runtime by scripts/fetch_tft_icons.py for local "
                 "use only; never committed, never exported (NOTICE)."),
        "catalogue_source": report.catalogue_source,
        "membership": report.membership,
        "counts": {c: len(entries.get(c) or {}) for c in CATEGORIES},
        "entries": {c: dict(sorted((entries.get(c) or {}).items())) for c in CATEGORIES},
        "missing": {c: sorted(missing.get(c) or []) for c in CATEGORIES},
    }
    data = (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    _atomic_write_bytes(base / INDEX_NAME, data)


def fill_cache(set_number, sources, *, root=None, categories=CATEGORIES, extract=None,
               force=False, limit=None, dry_run=False, sleep=time.sleep,
               clock=time.monotonic) -> FillReport:
    """Fill data/tft/icon_cache/<set>/ from `sources` (LCU first, CDragon second).

    extract=None reads data/meta/tft_set<N>_cdragon.json under root. limit caps
    the icon GETs this run. dry_run fetches the catalogue only and writes nothing.
    """
    n = _set_number(set_number)
    cats = tuple(categories)
    bad = [c for c in cats if c not in CATEGORIES]
    if bad or not cats:
        raise ValueError(f"categories must be drawn from {CATEGORIES}, got {categories!r}")
    if limit is not None and int(limit) < 0:
        raise ValueError("limit must be >= 0")
    sources = list(sources or ())
    base = set_dir(n, root)
    report = FillReport(set_number=n, cache_dir=base, counts={c: _zero_counts() for c in cats})
    pacer = _Pacer(clock, sleep)
    if extract is None:
        extract = tft_set.load_cdragon(n, root=root)

    needed = [d for d in GAME_DATA_DOCS if any(d in DOCS_FOR[c] for c in cats)]
    down: set = set()
    catalogue_docs = None
    for src in sources:
        got: dict = {}
        for doc in needed:
            pacer.wait(src)
            value = _call(src.game_data, doc)
            if not isinstance(value, (dict, list)):
                got = None
                break
            got[doc] = value
        if got is None:
            down.add(id(src))
            continue
        report.catalogue_source = src.name
        catalogue_docs = got
        break
    if catalogue_docs is None:
        report.status = "offline"
        return report

    catalogue = build_catalogue(n, catalogue_docs, extract)
    report.membership = catalogue.membership
    for c in cats:
        report.counts[c]["wanted"] = len(catalogue.paths[c]) + len(catalogue.missing[c])
        report.missing[c] = list(catalogue.missing[c])

    old = load_index(n, root)
    old_entries = old.get("entries") if isinstance(old.get("entries"), dict) else {}
    old_missing = old.get("missing") if isinstance(old.get("missing"), dict) else {}
    entries = {c: ({} if c in cats else dict(old_entries.get(c) or {})) for c in CATEGORIES}
    missing = {c: (report.missing[c] if c in cats else list(old_missing.get(c) or []))
               for c in CATEGORIES}
    used = {c: {} for c in CATEGORIES}
    fails = {id(s): 0 for s in sources}
    fetched_assets: dict = {}          # asset path -> (bytes, source name) or (None, None)
    planned_gets: set = set()
    attempts = 0
    unflushed = 0

    def fetch(asset):
        for src in sources:
            if id(src) in down:
                continue
            pacer.wait(src)
            data = _call(src.asset, asset)
            if image_kind(data) is not None and len(data) <= MAX_ICON_BYTES:
                fails[id(src)] = 0
                report.by_source[src.name] = report.by_source.get(src.name, 0) + 1
                return bytes(data), src.name
            fails[id(src)] += 1
            if fails[id(src)] >= SOURCE_FAIL_LIMIT:
                down.add(id(src))
                logger.info("TFT icons: %s skipped after %d failed GETs in a row",
                            src.name, fails[id(src)])
        return None, None

    for c in cats:
        prev_cat = old_entries.get(c) if isinstance(old_entries.get(c), dict) else {}
        for api, asset in catalogue.paths[c].items():
            prev = prev_cat.get(api)
            if not force and _reusable(base, c, prev, asset):
                entries[c][api] = prev
                used[c][Path(prev["file"]).stem.casefold()] = api
                report.counts[c]["cached"] += 1
                continue
            if dry_run:
                report.planned += 1
                planned_gets.add(asset)
                continue
            if asset not in fetched_assets:
                if limit is not None and attempts >= int(limit):
                    report.counts[c]["skipped"] += 1
                    continue
                attempts += 1
                fetched_assets[asset] = fetch(asset)
            data, src_name = fetched_assets[asset]
            if data is None:
                report.counts[c]["failed"] += 1
                if len(report.failures) < MAX_FAILURES_KEPT:
                    report.failures.append((c, api, "no source returned an image"))
                continue
            stem = file_stem(api, used=used[c])
            name = f"{stem}.{image_kind(data)}"
            _ensure_self_ignored(root)
            _atomic_write_bytes(base / c / name, data)
            entries[c][api] = {"file": f"{c}/{name}", "sha256": hashlib.sha256(data).hexdigest(),
                               "bytes": len(data), "src": src_name, "asset": asset}
            report.counts[c]["fetched"] += 1
            unflushed += 1
            if unflushed >= INDEX_FLUSH_EVERY:
                _write_index(base, n, entries, missing, report)
                unflushed = 0

    if dry_run:
        report.planned_gets = len(planned_gets)
        report.status = "dry_run"
        return report
    _ensure_self_ignored(root)
    _write_index(base, n, entries, missing, report)
    clean = all(k["failed"] == 0 and k["skipped"] == 0 for k in report.counts.values())
    report.status = "ok" if clean and not any(report.missing.values()) else "partial"
    return report
