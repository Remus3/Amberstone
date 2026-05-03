"""
tools/daemon_slayer_extract.py — Phase 1 data extractor for the Daemon Slayer
build engine.

Produces a versioned snapshot under ``data/daemon_slayer/<patch>/``:

    champions.json  — per-champion sheet (DDragon stats + lolmath cooldowns,
                      roles, healing/shielding ratings)
    items.json      — DDragon item catalog (full, version-pinned)
    scenarios.json  — lolmath playstyle scenario records, keyed by championKey
                      (e.g. ``aatrox``); includes every variant the bundle
                      defines (e.g. Akali "Shadow Assassin", Aphelios "Ap")
    manifest.json   — provenance: timestamps, source URLs, validation counts

Plus ``data/daemon_slayer/current.txt`` (plain-text patch string the engine
points at).

Usage:
    py tools/daemon_slayer_extract.py            # idempotent — skips if patch is already extracted
    py tools/daemon_slayer_extract.py --force    # re-extract regardless of patch state
    py tools/daemon_slayer_extract.py --chunk-url URL  # override chunk autodiscovery

Design rationale (see project_daemon_slayer_engine.md):
  - DDragon is the canonical source for champion/item/stat data.
  - lolmath provides only the *scenario* priors — playstyle weight tables,
    expected-time-alive, statPreference, proficiency. lolmath.net's
    optimizer is a static SPA whose payload lives entirely in a single
    Turbopack chunk (currently ``14.<hash>.js``); the chunk hash rotates
    when lolmath rebuilds.
  - No JS parser needed: the chunk's data is reachable with a small
    substitution table + json5 + a two-pass resolver for spread/wrapper
    references between variant scenarios.

Phase 1 step 1 verdict (2026-05-03 probe): regex+json5 extraction is
sufficient — 172/172 champions resolved, 196/196 top-level records parse.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json5  # third-party; pure-Python JSON5 parser

ROOT = Path(__file__).parent.parent
DATA_ROOT = ROOT / "data" / "daemon_slayer"
LOG_FILE = ROOT / "logs" / "daemon_slayer_extract.log"

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
LOLMATH_ROOT = "https://lolmath.net/"
USER_AGENT = "RiotCommander/DaemonSlayer-extract/1.0"

# Markers used to identify the right chunk among lolmath's ~20 chunks.
# `statPreference:` is the strongest signal — it appears 170+ times in the
# scenarios chunk and zero times anywhere else. Several other chunks contain
# the cooldown table or champion-name-keyed JSON, but only the scenarios chunk
# defines per-champion playstyle priors.
SCENARIO_CHUNK_ANCHOR = "statPreference:"
COOLDOWN_PAYLOAD_ANCHOR = '{"Aatrox":{"Q":'

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("daemon_slayer_extract")


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _fetch_json(url: str, timeout: int = 15) -> Any:
    return json.loads(_fetch_text(url, timeout=timeout))


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ─── Chunk discovery ─────────────────────────────────────────────────────────

def discover_chunk_url(override: str | None = None) -> str:
    """Locate the lolmath JS chunk containing champion/scenario data.

    lolmath.net is a Next.js SPA whose chunk filenames are content-hashed
    (currently ``14.ejgq2van4b.js``). The hash rotates on rebuild, so we
    enumerate every script tag in the root HTML and probe each chunk's
    head for the cooldown-table anchor.
    """
    if override:
        log.info("chunk URL override: %s", override)
        return override

    html = _fetch_text(LOLMATH_ROOT)
    # Find every /_next/static/chunks/<id>.<hash>.js reference.
    chunks = sorted(set(re.findall(r"/_next/static/chunks/([^\"'\s>]+\.js)", html)))
    log.info("found %d chunk references on lolmath.net root", len(chunks))

    candidates = []  # (score, url, body)
    for relpath in chunks:
        url = "https://lolmath.net/_next/static/chunks/" + relpath
        try:
            body = _fetch_text(url)
        except Exception as e:
            log.warning("  chunk fetch failed %s: %s", relpath, e)
            continue
        score = body.count(SCENARIO_CHUNK_ANCHOR)
        if score > 0:
            candidates.append((score, url, body, relpath))

    if not candidates:
        raise RuntimeError(
            f"no chunk on lolmath.net contains {SCENARIO_CHUNK_ANCHOR!r}; "
            "lolmath may have changed structure"
        )

    # Highest score wins — the "real" scenarios chunk has 170+ hits while
    # spurious matches (a Redux handler param named championKey, etc.) are 0.
    candidates.sort(key=lambda t: t[0], reverse=True)
    score, url, body, relpath = candidates[0]
    log.info("scenarios chunk found: %s (%d bytes, %d %s hits)",
             relpath, len(body), score, SCENARIO_CHUNK_ANCHOR)
    _CHUNK_CACHE["text"] = body
    return url


_CHUNK_CACHE: dict[str, str] = {}


def fetch_chunk(url: str) -> str:
    if "text" in _CHUNK_CACHE:
        return _CHUNK_CACHE["text"]
    return _fetch_text(url)


# ─── Module slicing within the Turbopack chunk ────────────────────────────────

def _walk_balanced(text: str, open_pos: int) -> int:
    """Return the index of the matching closing delimiter, or -1."""
    open_ch = text[open_pos]
    close_ch = "}" if open_ch == "{" else "]" if open_ch == "[" else None
    if close_ch is None:
        return -1
    depth = 1
    in_str: str | None = None
    bs = False
    j = open_pos + 1
    while j < len(text):
        c = text[j]
        if in_str:
            if bs:
                bs = False
            elif c == "\\":
                bs = True
            elif c == in_str:
                in_str = None
        elif c in ('"', "'"):
            in_str = c
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _extract_json_parse_string(chunk: str, anchor_substr: str) -> dict:
    """Pull and parse ``JSON.parse('...')`` whose payload starts with anchor_substr."""
    needle = "JSON.parse('"
    pos = 0
    while True:
        i = chunk.find(needle, pos)
        if i < 0:
            raise RuntimeError(f"JSON.parse(...) with anchor {anchor_substr!r} not found")
        start = i + len(needle)
        # Walk forward to first unescaped single quote.
        end = start
        bs = False
        while end < len(chunk):
            c = chunk[end]
            if bs:
                bs = False
            elif c == "\\":
                bs = True
            elif c == "'":
                break
            end += 1
        payload = chunk[start:end]
        if anchor_substr in payload[:80]:
            # Convert JS-string \' back to ' (rest of escapes already match JSON syntax).
            return json.loads(payload.replace("\\'", "'"))
        pos = end + 1


def _extract_obj_factory(chunk: str, marker: str) -> dict:
    """Pull and parse a Turbopack module whose body starts with
    ``a.exports={...}`` and whose factory contains the given marker.
    """
    # Find every "<num>,(<params>)=>{a.exports=" header, look for one whose
    # following object literal has the marker.
    for m in re.finditer(r"\d+,\(([a-z],?)+\)=>\{a\.exports=", chunk):
        body_start = m.end()
        if chunk[body_start] != "{":
            continue
        end = _walk_balanced(chunk, body_start)
        if end < 0:
            continue
        body = chunk[body_start:end + 1]
        if marker not in body[:200]:
            continue
        return json5.loads(body)
    raise RuntimeError(f"no obj-literal factory body containing marker {marker!r}")


def _extract_use_strict_factory_body(chunk: str) -> str:
    """Return the body text of the giant ``e=>{"use strict"; ...}`` factory."""
    m = re.search(r'e=>\{"use strict";', chunk)
    if not m:
        raise RuntimeError('"use strict" factory not found in chunk')
    body_open = chunk.index("{", m.start())
    body_close = _walk_balanced(chunk, body_open)
    if body_close < 0:
        raise RuntimeError("could not find end of use-strict factory body")
    return chunk[body_open + 1:body_close]


# ─── Top-level binding extraction & parsing ─────────────────────────────────

@dataclass
class TopLevelBinding:
    name: str
    text: str  # raw JS-source text starting with `{` or `[`


def _walk_top_level_bindings(body: str) -> list[TopLevelBinding]:
    """Yield each ``<id>=<obj-or-arr-literal>`` declared at depth 0 in body."""
    binding_re = re.compile(
        r"(?:\b(?:let|var|const)\s+|,)\s*([A-Za-z_$][\w$]*)\s*=\s*([\{\[])"
    )
    out: list[TopLevelBinding] = []
    n = len(body)
    i = 0
    in_str: str | None = None
    bs = False
    paren_d = brace_d = bracket_d = 0
    while i < n:
        c = body[i]
        if in_str:
            if bs:
                bs = False
            elif c == "\\":
                bs = True
            elif c == in_str:
                in_str = None
            i += 1
            continue
        if c in ('"', "'"):
            in_str = c
            i += 1
            continue
        if paren_d == 0 and brace_d == 0 and bracket_d == 0:
            mm = binding_re.match(body, i)
            if mm:
                name = mm.group(1)
                open_pos = mm.start(2)
                end = _walk_balanced(body, open_pos)
                if end >= 0:
                    out.append(TopLevelBinding(name, body[open_pos:end + 1]))
                    i = end + 1
                    continue
        if c == "(":
            paren_d += 1
        elif c == ")":
            paren_d -= 1
        elif c == "[":
            bracket_d += 1
        elif c == "]":
            bracket_d -= 1
        elif c == "{":
            brace_d += 1
        elif c == "}":
            brace_d -= 1
        i += 1
    return out


# Substitution table: convert lolmath JS-isms into JSON5-parseable form.
_SUBS_PRECOMPILED = [
    # Enum constants of the form `<X>.<Y>.<Z>` → leaf as a string literal.
    (re.compile(r"\bA\.ChampionKey\.([A-Za-z_$][\w$]*)"), r'"\1"'),
    (re.compile(r"\bk\.DamageType\.([A-Za-z_$][\w$]*)"), r'"\1"'),
    (re.compile(r"\bk\.TargetType\.([A-Za-z_$][\w$]*)"), r'"\1"'),
    (re.compile(r"\bk\.UsageType\.([A-Za-z_$][\w$]*)"), r'"\1"'),
    (re.compile(r"\bw\.LanePosition\.([A-Za-z_$][\w$]*)"), r'"\1"'),
    (re.compile(r"\bI\.GameModes\.([A-Za-z_$][\w$]*)"), r'"\1"'),
    (re.compile(r"\bH\.MapId\.([A-Za-z_$][\w$]*)"), r'"\1"'),
    # Cooldown helper calls — minified per champion (different letter each time):
    # `<id>("P")`, `<id>("Q")`, etc. Replace with null; cooldown table is sourced separately.
    (re.compile(r'\b[A-Za-z_$][\w$]*\("[PQWER]"\)'), "null"),
    # Computed keys like `[j.calibrumBasic]:` or `[ny.ZaahenAbilities.Q2]:`
    # → keep the trailing leaf segment as a quoted string key.
    (re.compile(r"\[[A-Za-z_$][\w$.]*\.([A-Za-z_$][\w$]*)\]\s*:"), r'"\1":'),
    # Numeric object keys — JSON5 requires them to be quoted.
    (re.compile(r"([{,])\s*(\d+)\s*:"), r'\1"\2":'),
    # Surviving dotted member references in *value* positions → null.
    # Limited to value contexts (after `:` `,` or `[`) so we don't corrupt
    # member-access on parsed-data identifiers.
    (re.compile(r"(?<=[:,\[])\s*[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+"), " null"),
    # JS minification truthy shortcuts.
    (re.compile(r"!0\b"), "true"),
    (re.compile(r"!1\b"), "false"),
]


def _substitute(text: str) -> str:
    for pat, repl in _SUBS_PRECOMPILED:
        text = pat.sub(repl, text)
    return text.replace("void 0", "null")


def _resolve_text(rec_text: str,
                  name_to_text: dict[str, str],
                  name_to_parsed: dict[str, Any]) -> str:
    """Inline wrapper-array refs (`[az,aU]`) and spread refs (`...az.settings`)."""
    # Wrapper array of bare identifier references.
    wrapper = re.fullmatch(
        r"\[([A-Za-z_$][\w$]*(?:,[A-Za-z_$][\w$]*)+)\]", rec_text.strip()
    )
    if wrapper:
        names = wrapper.group(1).split(",")
        if all(n in name_to_parsed for n in names):
            return json.dumps([name_to_parsed[n] for n in names])
        if all(n in name_to_text for n in names):
            inner = ",".join(
                _resolve_text(name_to_text[n], name_to_text, name_to_parsed)
                for n in names
            )
            return "[" + inner + "]"

    def spread_repl(mm: re.Match) -> str:
        ref_name = mm.group(1)
        path = mm.group(2)
        target = name_to_parsed.get(ref_name)
        if target is None:
            return mm.group(0)
        if path:
            for seg in path.lstrip(".").split("."):
                if isinstance(target, dict) and seg in target:
                    target = target[seg]
                else:
                    return mm.group(0)
        if not isinstance(target, dict):
            return mm.group(0)
        if not target:
            return ""
        # No trailing comma — the surrounding source already has separators,
        # and we collapse any double-commas afterwards.
        return json.dumps(target)[1:-1]

    rec_text = re.sub(
        r"\.\.\.([A-Za-z_$][\w$]*)((?:\.[A-Za-z_$][\w$]*)*)",
        spread_repl,
        rec_text,
    )
    rec_text = re.sub(r",\s*,+", ",", rec_text)
    rec_text = re.sub(r"([{\[])\s*,", r"\1", rec_text)
    return rec_text


def _parse_top_level(bindings: list[TopLevelBinding]) -> dict[str, Any]:
    """Return ``{name: parsed}`` for every binding, resolving spreads/wrappers."""
    name_to_text = {b.name: b.text for b in bindings}
    name_to_parsed: dict[str, Any] = {}

    for b in bindings:
        try:
            name_to_parsed[b.name] = json5.loads(_substitute(b.text))
        except Exception:
            pass

    pending = {b.name for b in bindings if b.name not in name_to_parsed}
    for _ in range(8):
        if not pending:
            break
        progressed = set()
        for nm in list(pending):
            resolved = _resolve_text(name_to_text[nm], name_to_text, name_to_parsed)
            try:
                name_to_parsed[nm] = json5.loads(_substitute(resolved))
                progressed.add(nm)
            except Exception:
                pass
        if not progressed:
            break
        pending -= progressed

    if pending:
        log.warning("could not parse %d top-level bindings: %s", len(pending), sorted(pending))

    return name_to_parsed


# ─── Lolmath chunk → structured records ──────────────────────────────────────

@dataclass
class LolmathExtract:
    cooldowns: dict[str, dict[str, list[float | None]]]
    roles: dict[str, list[str]]
    ratings: dict[str, dict[str, Any]]
    lane_positions: list[str]
    scenarios: dict[str, list[dict]]   # championKey → list of scenario records
    chunk_url: str
    chunk_bytes: int


def extract_from_chunk(chunk: str, chunk_url: str) -> LolmathExtract:
    cooldowns = _extract_json_parse_string(chunk, COOLDOWN_PAYLOAD_ANCHOR)
    roles = _extract_obj_factory(chunk, "Aatrox:")
    body = _extract_use_strict_factory_body(chunk)
    bindings = _walk_top_level_bindings(body)
    log.info("use-strict factory: %d top-level bindings", len(bindings))
    parsed = _parse_top_level(bindings)
    log.info("parsed %d/%d bindings", len(parsed), len(bindings))

    # Collect scenarios — they're arrays whose first element has settings.championKey.
    scenarios: dict[str, list[dict]] = {}

    def collect_scenario(rec: Any) -> None:
        if not isinstance(rec, list) or not rec:
            return
        first = rec[0]
        if not isinstance(first, dict):
            return
        ck = first.get("settings", {}).get("championKey") if isinstance(first.get("settings"), dict) else None
        if ck:
            existing = scenarios.get(ck)
            if existing is None or len(rec) > len(existing):
                scenarios[ck] = rec

    for val in parsed.values():
        collect_scenario(val)
        # Wrapper arrays of scenarios show up at top-level too:
        # they contain >=2 dicts each carrying championKey.
        if isinstance(val, list) and len(val) >= 2 and all(isinstance(x, dict) for x in val):
            ck = (
                val[0].get("settings", {}).get("championKey")
                if isinstance(val[0].get("settings"), dict)
                else None
            )
            if ck:
                scenarios[ck] = val

    # Ratings, lane positions: lookup by content shape.
    # `let D = {<champname>: {ratings: {...}}}` is the global ratings dict.
    ratings: dict[str, dict[str, Any]] = {}
    lane_positions: list[str] = []
    for val in parsed.values():
        if (
            isinstance(val, dict)
            and "Aatrox" in val
            and isinstance(val["Aatrox"], dict)
            and "ratings" in val["Aatrox"]
        ):
            ratings = val
        elif (
            isinstance(val, list)
            and val
            and all(isinstance(x, str) for x in val)
            and any(x in {"top", "jungle", "mid", "adc", "support"} for x in val)
        ):
            lane_positions = val

    log.info(
        "extract: cooldowns=%d roles=%d ratings=%d lanes=%d scenarios=%d",
        len(cooldowns), len(roles), len(ratings), len(lane_positions), len(scenarios),
    )
    return LolmathExtract(
        cooldowns=cooldowns,
        roles=roles,
        ratings=ratings,
        lane_positions=lane_positions,
        scenarios=scenarios,
        chunk_url=chunk_url,
        chunk_bytes=len(chunk),
    )


# ─── DDragon ─────────────────────────────────────────────────────────────────

@dataclass
class DDragonSnapshot:
    version: str
    champions: dict[str, dict]   # championId (e.g. "Aatrox") → DDragon champion record
    items: dict[str, dict]       # itemId-string → DDragon item record


def fetch_ddragon() -> DDragonSnapshot:
    versions = _fetch_json(f"{DDRAGON_BASE}/api/versions.json")
    version = versions[0]
    log.info("DDragon current version: %s", version)
    champ = _fetch_json(f"{DDRAGON_BASE}/cdn/{version}/data/en_US/champion.json")
    items = _fetch_json(f"{DDRAGON_BASE}/cdn/{version}/data/en_US/item.json")
    return DDragonSnapshot(
        version=version,
        champions=champ.get("data", {}),
        items=items.get("data", {}),
    )


# ─── Emission ────────────────────────────────────────────────────────────────

# Hard-coded aliases for champions whose DDragon id doesn't match their lolmath
# camelCase key after case+alphanum normalization.
_LOLMATH_TO_DDRAGON_ALIAS = {
    "wukong": "MonkeyKing",
    "nunuWillump": "Nunu",
    "renataGlasc": "Renata",
}


def _championkey_to_ddragon_id(key: str, ddragon_ids: set[str]) -> str | None:
    """lolmath uses camelCase keys (``aatrox``, ``leBlanc``, ``drMundo``);
    DDragon uses PascalCase ids (``Aatrox``, ``Leblanc``, ``DrMundo``)."""
    if not key:
        return None
    if key in _LOLMATH_TO_DDRAGON_ALIAS:
        cand = _LOLMATH_TO_DDRAGON_ALIAS[key]
        return cand if cand in ddragon_ids else None
    lc = key.lower()
    for did in ddragon_ids:
        if did.lower() == lc:
            return did
    norm = re.sub(r"[^a-z]", "", lc)
    for did in ddragon_ids:
        if re.sub(r"[^a-z]", "", did.lower()) == norm:
            return did
    return None


def build_champions_payload(lolmath: LolmathExtract, dd: DDragonSnapshot) -> dict:
    """Merge DDragon champion data with lolmath cooldowns/roles/ratings."""
    out: dict[str, Any] = {"version": dd.version, "data": {}}
    ddids = set(dd.champions.keys())

    # Start with lolmath's PascalCase champion key set (it's the canonical set the
    # engine cares about). For each, find the DDragon id if any.
    for champ_id, dd_record in dd.champions.items():
        cooldown = lolmath.cooldowns.get(champ_id)
        roles = lolmath.roles.get(champ_id)
        ratings = lolmath.ratings.get(champ_id, {}).get("ratings") if isinstance(lolmath.ratings.get(champ_id), dict) else None
        out["data"][champ_id] = {
            "id": champ_id,
            "key": dd_record.get("key"),
            "name": dd_record.get("name"),
            "title": dd_record.get("title"),
            "tags": dd_record.get("tags", []),
            "stats": dd_record.get("stats", {}),
            "info": dd_record.get("info", {}),
            "partype": dd_record.get("partype"),
            "lolmath": {
                "cooldowns": cooldown,                  # {Q: [...], W: [...], E: [...], R: [...]}
                "roles": roles,                          # ["FIGHTER", "TANK"]
                "ratings": ratings,                      # {healing, shielding}
            },
        }

    # Surface lolmath champions DDragon doesn't know about (newly released, etc.)
    missing = sorted(set(lolmath.cooldowns) - ddids)
    if missing:
        log.warning(
            "lolmath has %d champions absent from DDragon %s: %s",
            len(missing), dd.version, missing,
        )
    return out


def build_items_payload(dd: DDragonSnapshot) -> dict:
    return {"version": dd.version, "data": dd.items}


def build_scenarios_payload(lolmath: LolmathExtract, dd: DDragonSnapshot) -> dict:
    """Reorganize scenarios under DDragon ids where possible.

    lolmath uses ``championKey:"aatrox"``-style camelCase keys; we emit a
    map keyed by both the lolmath key (lossless) and a DDragon-id alias
    when one resolves.
    """
    ddids = set(dd.champions.keys())
    out_by_ddragon: dict[str, list[dict]] = {}
    out_by_lolmath: dict[str, list[dict]] = {}
    for ck, scenarios in lolmath.scenarios.items():
        out_by_lolmath[ck] = scenarios
        ddragon_id = _championkey_to_ddragon_id(ck, ddids)
        if ddragon_id:
            out_by_ddragon[ddragon_id] = scenarios
    return {
        "version": dd.version,
        "championCount": len(out_by_lolmath),
        "byDDragonId": out_by_ddragon,
        "byLolmathKey": out_by_lolmath,
    }


def build_manifest(lolmath: LolmathExtract, dd: DDragonSnapshot,
                   patch_dir: Path) -> dict:
    return {
        "engine": "daemon_slayer",
        "phase": 1,
        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ddragon_version": dd.version,
        "ddragon_champion_count": len(dd.champions),
        "ddragon_item_count": len(dd.items),
        "sources": {
            "ddragon_versions": f"{DDRAGON_BASE}/api/versions.json",
            "ddragon_champions": f"{DDRAGON_BASE}/cdn/{dd.version}/data/en_US/champion.json",
            "ddragon_items": f"{DDRAGON_BASE}/cdn/{dd.version}/data/en_US/item.json",
            "lolmath_chunk": lolmath.chunk_url,
            "lolmath_chunk_bytes": lolmath.chunk_bytes,
        },
        "lolmath_counts": {
            "cooldowns": len(lolmath.cooldowns),
            "roles": len(lolmath.roles),
            "ratings": len(lolmath.ratings),
            "lane_positions": len(lolmath.lane_positions),
            "scenarios": len(lolmath.scenarios),
        },
        "outputs": {
            "champions": str((patch_dir / "champions.json").relative_to(ROOT)),
            "items": str((patch_dir / "items.json").relative_to(ROOT)),
            "scenarios": str((patch_dir / "scenarios.json").relative_to(ROOT)),
        },
    }


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Daemon Slayer Phase 1 data extractor.")
    ap.add_argument("--force", action="store_true",
                    help="re-extract even if the patch directory already exists")
    ap.add_argument("--chunk-url", default=None,
                    help="bypass autodiscovery and fetch this URL for the data chunk")
    ap.add_argument("--patch", default=None,
                    help="override patch label for the output directory (default: DDragon current)")
    args = ap.parse_args()

    log.info("=" * 60)
    log.info("daemon_slayer extract starting (force=%s)", args.force)

    # Fetch DDragon first — its version is also the patch label for output.
    dd = fetch_ddragon()
    patch = args.patch or dd.version
    patch_dir = DATA_ROOT / patch

    if patch_dir.exists() and not args.force:
        if (patch_dir / "manifest.json").exists():
            log.info("patch %s already extracted at %s — skip (use --force to redo)",
                     patch, patch_dir)
            _atomic_write_text(DATA_ROOT / "current.txt", patch)
            return 0
        log.info("patch dir %s exists but no manifest — re-extracting", patch_dir)

    chunk_url = discover_chunk_url(args.chunk_url)
    chunk = fetch_chunk(chunk_url)
    lolmath = extract_from_chunk(chunk, chunk_url)

    champions_payload = build_champions_payload(lolmath, dd)
    items_payload = build_items_payload(dd)
    scenarios_payload = build_scenarios_payload(lolmath, dd)
    manifest = build_manifest(lolmath, dd, patch_dir)

    _atomic_write_json(patch_dir / "champions.json", champions_payload)
    _atomic_write_json(patch_dir / "items.json", items_payload)
    _atomic_write_json(patch_dir / "scenarios.json", scenarios_payload)
    _atomic_write_json(patch_dir / "manifest.json", manifest)
    _atomic_write_text(DATA_ROOT / "current.txt", patch)

    log.info("✓ wrote %s/{champions,items,scenarios,manifest}.json", patch_dir)
    log.info("✓ current.txt → %s", patch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
