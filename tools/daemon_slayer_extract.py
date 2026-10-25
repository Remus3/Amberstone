"""
tools/daemon_slayer_extract.py - Phase 1 data extractor for the Daemon Slayer
build engine.

Produces a versioned snapshot under ``data/daemon_slayer/<patch>/``:

    champions.json  - per-champion sheet (DDragon stats + lolmath cooldowns,
                      roles, healing/shielding ratings)
    items.json      - DDragon item catalog (full, version-pinned)
    scenarios.json  - lolmath playstyle scenario records, keyed by championKey
                      (e.g. ``aatrox``); includes every variant the bundle
                      defines (e.g. Akali "Shadow Assassin", Aphelios "Ap")
    manifest.json   - provenance: timestamps, source URLs, validation counts

Plus ``data/daemon_slayer/current.txt`` (plain-text patch string the engine
points at).

Usage:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_extract.py            # idempotent - skips if patch is already extracted
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_extract.py --force    # re-extract regardless of patch state
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_extract.py --chunk-url URL  # override chunk autodiscovery
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_extract.py --lolmath-only --patch 16.21.1  # refresh lolmath only

A lolmath ARAM modifier table that comes back >= 95 percent neutral stops the
extract with exit code 3 and nothing written (RM-805); ``--allow-neutral-aram
REASON`` accepts it after an adjudication, logged and recorded in the manifest.
The damage-split and skill-order blocks get the same gate (RM-807): a block
that is >= 95 percent degenerate (all-zero split rows, empty skill orders, or
an empty block) exits 5 with nothing written, past it only with
``--allow-degenerate-lolmath REASON``; a degenerate row below the floor is
named in a WARNING. A Meraki items payload under 160 or an Arena augments
payload under 110 (RM-807 (d); every snapshot measured 320 / 220-227) exits 6
with nothing written, past it only with ``--allow-short-upstream REASON``.

``--lolmath-only`` re-runs ONLY the lolmath extract against an EXISTING
snapshot (it needs ``<patch>/manifest.json``; ``--patch`` defaults to
``current.txt``) and never combines with ``--force``: lolmath ships on its own
cadence, and a forced re-extract would re-fetch Meraki, which is never forced.
It fetches nothing from DDragon, Meraki or CDragon (ids and version come from
the snapshot's ``champions.json``) and rewrites only each champion's
``lolmath`` sub-object in ``champions.json``, ``scenarios.json``, and the
lolmath sources / counts / refresh stamp in ``manifest.json``. The RM-805 gate
applies unchanged. A table that passes it without an override supersedes an
adjudicated ``aram_modifiers_carry`` (dropped); with ``--allow-neutral-aram``
the carry and its carried rows stay.

Design rationale (see project_daemon_slayer_engine.md):
  - DDragon is the canonical source for champion/item/stat data.
  - lolmath provides only the *scenario* priors - playstyle weight tables,
    expected-time-alive, statPreference, proficiency. lolmath.net's
    optimizer is a static SPA whose payload lives entirely in a single
    Turbopack chunk (currently ``14.<hash>.js``); the chunk hash rotates
    when lolmath rebuilds.
  - No JS parser needed: the chunk's data is reachable with a small
    substitution table + json5 + a two-pass resolver for spread/wrapper
    references between variant scenarios.

Phase 1 step 1 verdict (2026-05-03 probe): regex+json5 extraction is
sufficient - 172/172 champions resolved, 196/196 top-level records parse.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import json5  # third-party; pure-Python JSON5 parser

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.daemon_slayer.mode_variants import (  # noqa: E402
    canonical_champions,
    canonical_items,
)

DATA_ROOT = ROOT / "data" / "daemon_slayer"
LOG_FILE = ROOT / "logs" / "daemon_slayer_extract.log"

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
LOLMATH_ROOT = "https://lolmath.net/"
MERAKI_BASE = "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions"
# Bulk roster map (171 champions as of 2026-07-18). Preferred over the
# per-champion endpoint, which 404s for champions Meraki has not published
# individually - see fetch_meraki_perlevel_overlay.
MERAKI_BULK_URL = "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json"
# Phase 4 batch 20 (2026-05-04): Meraki bulk items endpoint. Single 3.2 MB
# request returns 320 items keyed by id; per-item endpoints (.../items/<id>.json)
# observed stale on 2026-05-04 (e.g. ER showed only Essence Drain, missing
# Spellblade). Always prefer bulk for the snapshot - atomic + current.
MERAKI_ITEMS_URL = "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/items.json"
CDRAGON_ARENA_URL = "https://raw.communitydragon.org/latest/cdragon/arena/en_us.json"
USER_AGENT = "Amberstone/DaemonSlayer-extract/1.0"

# Markers used to identify the right chunk among lolmath's ~20 chunks.
# `statPreference:` is the strongest signal for the scenarios chunk - appears
# 170+ times there, zero anywhere else. The data chunk (Phase 1.5) is a
# separate ~1.5MB chunk holding 12 JSON.parse blocks; `aramDamageTaken` is
# its strongest anchor (172 hits, one per champion).
SCENARIO_CHUNK_ANCHOR = "statPreference:"
DATA_CHUNK_ANCHOR = "aramDamageTaken"
COOLDOWN_PAYLOAD_ANCHOR = '{"Aatrox":{"Q":'
# 16.21.1: the full scenario table (one `statPreference:` per champion
# scenario - 175 hits) moved into a LAZILY loaded chunk; the root set keeps
# only the default champion's scenario (1 hit). A root best below this floor
# is a fragment, not the table, so discovery crawls the chunk graph for it.
SCENARIO_ANCHOR_MIN_HITS = 100
# The ratings dict (`{Aatrox:{ratings:{...}}}`) left the scenario chunk at
# 16.21.1 too; a chunk carrying this marker is searched for it.
_RATINGS_MARKER = "ratings:{"

# Anchors for the three Phase 1.5 JSON.parse payloads inside the data chunk.
# Each must appear inside the first 80 chars of its block's payload (the
# `_extract_json_parse_string` window), and must NOT collide with any earlier
# block's first 80 chars - verified 2026-05-03.
ARAM_MODIFIERS_ANCHOR = "aramDamageTaken"
DAMAGE_DISTRIBUTION_ANCHOR = '"trued":'
SKILL_ORDER_ANCHOR = '["Q","E","W"'

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


# --- HTTP helpers -------------------------------------------------------------

def _fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _fetch_json(url: str, timeout: int = 15) -> Any:
    return json.loads(_fetch_text(url, timeout=timeout))


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Bytes, not write_text. Every target here is TRACKED and pinned eol=lf by
    # .gitattributes, and on Windows write_text rewrites each LF as CRLF while
    # read_text translates it back - so the extra bytes are invisible to every
    # reader AND `git status` stays clean, because git normalizes them in the
    # index. An indent=2 payload is line-dense, so the on-disk size is off by
    # the line count and any digest or byte-length compare over
    # data/daemon_slayer/**.json is wrong. Same fix and same reason as RM-287
    # (coaches/_base_coach.safe_write, core/polled_json.atomic_write_json).
    # Guarded by tests/test_tracked_json_producers_emit_lf_bytes.py.
    tmp.write_bytes(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))
    tmp.replace(path)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Bytes for the same reason as _atomic_write_json above. Today's only
    # caller writes data/daemon_slayer/current.txt, a bare patch string with
    # no LF in it, so this is byte-identical NOW - it is the writer, not the
    # current payload, that has to be safe.
    tmp.write_bytes(content.encode("utf-8"))
    tmp.replace(path)


# --- Chunk discovery ---------------------------------------------------------

_CHUNK_BODIES: dict[str, str] = {}  # url -> body (populated by discover_chunks)


def fetch_chunk(url: str) -> str:
    if url in _CHUNK_BODIES:
        return _CHUNK_BODIES[url]
    body = _fetch_text(url)
    _CHUNK_BODIES[url] = body
    return body


def discover_chunks(scenario_override: str | None = None,
                    data_override: str | None = None) -> tuple[str, str]:
    """Locate the lolmath scenarios + data chunks in a single enumeration pass.

    lolmath.net is a Next.js SPA whose chunk filenames are content-hashed; the
    hash rotates on rebuild. We enumerate every script tag in the root HTML,
    fetch each chunk once, and pick the highest-scoring chunk per anchor:

      * scenarios chunk: ``statPreference:`` (175 hits in scenarios chunk, 0 elsewhere)
      * data chunk:      ``aramDamageTaken`` (172 hits in data chunk, 0 elsewhere)

    Bodies are cached in ``_CHUNK_BODIES`` keyed by URL so subsequent
    ``fetch_chunk`` calls don't refetch.

    Returns ``(scenarios_url, data_url)``. Raises if either chunk is missing.
    """
    # Honor full override pair without enumerating.
    if scenario_override and data_override:
        fetch_chunk(scenario_override)
        fetch_chunk(data_override)
        log.info("chunk URL overrides: scenarios=%s data=%s",
                 scenario_override, data_override)
        return scenario_override, data_override

    html = _fetch_text(LOLMATH_ROOT)
    chunks = sorted(set(re.findall(r"/_next/static/chunks/([^\"'\s>]+\.js)", html)))
    log.info("found %d chunk references on lolmath.net root", len(chunks))

    scenarios_best: tuple[int, str, str] | None = None  # (score, url, relpath)
    data_best: tuple[int, str, str] | None = None
    for relpath in chunks:
        url = "https://lolmath.net/_next/static/chunks/" + relpath
        try:
            body = fetch_chunk(url)
        except Exception as e:
            log.warning("  chunk fetch failed %s: %s", relpath, e)
            continue
        s_score = body.count(SCENARIO_CHUNK_ANCHOR)
        d_score = body.count(DATA_CHUNK_ANCHOR)
        if s_score > 0 and (scenarios_best is None or s_score > scenarios_best[0]):
            scenarios_best = (s_score, url, relpath)
        if d_score > 0 and (data_best is None or d_score > data_best[0]):
            data_best = (d_score, url, relpath)

    # 16.18.1: the ARAM table moved into a LAZILY loaded chunk the root HTML
    # never names; 16.21.1 did the same to the scenario table. Only when the
    # root set misses one of them, walk the chunk graph for the missing ones.
    need_data = data_best is None and not data_override
    need_scen = not scenario_override and (
        scenarios_best is None or scenarios_best[0] < SCENARIO_ANCHOR_MIN_HITS
    )
    if need_data or need_scen:
        roots = ["https://lolmath.net/_next/static/chunks/" + r for r in chunks]
        anchors = tuple(a for _, a in _DATA_BLOCKS) if need_data else ()
        min_hits: dict[str, int] = {}
        if need_scen:
            anchors += (SCENARIO_CHUNK_ANCHOR,)
            min_hits[SCENARIO_CHUNK_ANCHOR] = SCENARIO_ANCHOR_MIN_HITS
        for url in _crawl_lazy_chunks(roots, anchors, min_hits):
            body = _CHUNK_BODIES[url]
            if need_data:
                d_score = body.count(DATA_CHUNK_ANCHOR)
                if d_score > 0 and (data_best is None or d_score > data_best[0]):
                    data_best = (d_score, url, url.rsplit("/", 1)[-1])
            if need_scen:
                s_score = body.count(SCENARIO_CHUNK_ANCHOR)
                if s_score > 0 and (scenarios_best is None or s_score > scenarios_best[0]):
                    scenarios_best = (s_score, url, url.rsplit("/", 1)[-1])

    if scenario_override:
        s_url = scenario_override
        fetch_chunk(s_url)
    elif scenarios_best is None:
        raise RuntimeError(
            f"no chunk on lolmath.net contains {SCENARIO_CHUNK_ANCHOR!r}; "
            "lolmath may have changed structure"
        )
    else:
        score, s_url, relpath = scenarios_best
        log.info("scenarios chunk found: %s (%d bytes, %d %s hits)",
                 relpath, len(_CHUNK_BODIES[s_url]), score, SCENARIO_CHUNK_ANCHOR)

    if data_override:
        d_url = data_override
        fetch_chunk(d_url)
    elif data_best is None:
        raise RuntimeError(
            f"no chunk on lolmath.net contains {DATA_CHUNK_ANCHOR!r}; "
            "lolmath may have changed structure"
        )
    else:
        score, d_url, relpath = data_best
        log.info("data chunk found: %s (%d bytes, %d %s hits)",
                 relpath, len(_CHUNK_BODIES[d_url]), score, DATA_CHUNK_ANCHOR)

    return s_url, d_url


_CHUNK_BASE_URL = "https://lolmath.net/_next/static/chunks/"
# Two reference shapes seen in the Turbopack chunks: a worker manifest lists
# ``"static/chunks/<id>.js"`` and a loader call passes a bare ``"<id>.js"``.
_CHUNK_REF_RES = (
    re.compile(r"static/chunks/([A-Za-z0-9_\-.]+\.js)"),
    re.compile(r"\"([A-Za-z0-9_\-]{8,20}\.js)\""),
)
LAZY_CHUNK_CRAWL_MAX = 400
LAZY_CHUNK_CRAWL_DEPTH = 3


def _referenced_chunks(body: str) -> list[str]:
    """Return every chunk filename a chunk body references, sorted."""
    refs: set[str] = set()
    for rx in _CHUNK_REF_RES:
        refs.update(rx.findall(body))
    return sorted(refs)


def _crawl_lazy_chunks(root_urls: list[str], anchors: tuple[str, ...],
                       min_hits: dict[str, int] | None = None) -> list[str]:
    """Breadth-first walk of the chunk graph below ``root_urls``.

    Fetches (into ``_CHUNK_BODIES``) the chunks the roots reference, then the
    chunks those reference, up to ``LAZY_CHUNK_CRAWL_DEPTH`` hops and
    ``LAZY_CHUNK_CRAWL_MAX`` fetches, stopping as soon as every anchor in
    ``anchors`` appears in some cached body - at least ``min_hits[anchor]``
    times in ONE body when ``min_hits`` names it (default once). Returns the
    URLs fetched by the crawl, in order. A chunk that fails to fetch is
    logged and skipped.
    """
    floors = min_hits or {}

    def _all_present() -> bool:
        return all(
            any(b.count(a) >= floors.get(a, 1) for b in _CHUNK_BODIES.values())
            for a in anchors
        )

    seen = set(root_urls)
    frontier = list(root_urls)
    fetched: list[str] = []
    for _depth in range(LAZY_CHUNK_CRAWL_DEPTH):
        nxt: list[str] = []
        for parent in frontier:
            body = _CHUNK_BODIES.get(parent)
            if body is None:
                continue
            for ref in _referenced_chunks(body):
                url = _CHUNK_BASE_URL + ref
                if url in seen:
                    continue
                seen.add(url)
                if len(fetched) >= LAZY_CHUNK_CRAWL_MAX:
                    log.warning("lazy chunk crawl hit the %d-fetch cap", LAZY_CHUNK_CRAWL_MAX)
                    return fetched
                try:
                    child = fetch_chunk(url)
                except Exception as e:
                    log.warning("  lazy chunk fetch failed %s: %s", ref, e)
                    continue
                fetched.append(url)
                nxt.append(url)
                if any(a in child for a in anchors) and _all_present():
                    log.info("lazy chunk crawl: all of %r present after %d fetches",
                             anchors, len(fetched))
                    return fetched
        frontier = nxt
        if not frontier:
            break
    return fetched


# --- Module slicing within the Turbopack chunk --------------------------------

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


# Turbopack module-factory headers. The parameter names are minifier-assigned
# and re-roll on a lolmath redeploy (16.21.1: `(e,a,t)=>{a.exports=` became
# `(a,i,e)=>{i.exports=`, `e=>{"use strict";` became `a=>` / `l=>`), so match
# ANY identifier, never a pinned letter.
_OBJ_FACTORY_RE = re.compile(
    r"\d+,\((?:[A-Za-z_$][\w$]*,?)+\)=>\{[A-Za-z_$][\w$]*\.exports="
)
_USE_STRICT_FACTORY_RE = re.compile(r'(?<![\w$])[A-Za-z_$][\w$]*=>\{"use strict";')


def _extract_obj_factory(chunk: str, marker: str) -> dict:
    """Pull and parse a Turbopack module whose body starts with
    ``<id>.exports={...}`` and whose factory contains the given marker.
    """
    # Find every "<num>,(<params>)=><id>.exports=" header, look for one whose
    # following object literal has the marker.
    for m in _OBJ_FACTORY_RE.finditer(chunk):
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


_ROLE_CLASSES = frozenset({"FIGHTER", "TANK", "MAGE", "ASSASSIN", "MARKSMAN", "SUPPORT"})


def _extract_roles(chunk: str) -> dict:
    """Return lolmath's champion -> class-token-list table.

    Several Turbopack factories start ``{Aatrox:...``; 16.18.1 ships a
    ``{Aatrox:"General",...}`` survivability-label object AHEAD of the class
    lists, so "first factory with Aatrox:" silently yielded strings. Pick the
    factory whose every value is a non-empty list of known class tokens.
    """
    for m in _OBJ_FACTORY_RE.finditer(chunk):
        body_start = m.end()
        if chunk[body_start] != "{":
            continue
        end = _walk_balanced(chunk, body_start)
        if end < 0:
            continue
        body = chunk[body_start:end + 1]
        if "Aatrox:" not in body[:200]:
            continue
        try:
            parsed = json5.loads(body)
        except Exception:  # noqa: BLE001 - not a plain literal, try the next
            continue
        if isinstance(parsed, dict) and parsed and all(
            isinstance(v, list) and v and set(v) <= _ROLE_CLASSES
            for v in parsed.values()
        ):
            return parsed
    raise RuntimeError("no lolmath roles factory with class-token lists found")


def _extract_use_strict_factory_body(chunk: str) -> str:
    """Return the body text of the FIRST ``<id>=>{"use strict"; ...}`` factory."""
    m = _USE_STRICT_FACTORY_RE.search(chunk)
    if not m:
        raise RuntimeError('"use strict" factory not found in chunk')
    body_open = chunk.index("{", m.start())
    body_close = _walk_balanced(chunk, body_open)
    if body_close < 0:
        raise RuntimeError("could not find end of use-strict factory body")
    return chunk[body_open + 1:body_close]


def _iter_use_strict_factory_bodies(chunk: str):
    """Yield the body text of EVERY balanced ``<id>=>{"use strict"; ...}``
    factory in ``chunk``, in source order; an unbalanced one is skipped."""
    pos = 0
    while True:
        m = _USE_STRICT_FACTORY_RE.search(chunk, pos)
        if not m:
            return
        body_open = chunk.index("{", m.start())
        body_close = _walk_balanced(chunk, body_open)
        if body_close < 0:
            pos = m.end()
            continue
        yield chunk[body_open + 1:body_close]
        pos = body_close + 1


# --- Top-level binding extraction & parsing ---------------------------------

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
    # Enum constants of the form `<alias>.<Enum>.<leaf>` -> leaf as a string
    # literal. The ALIAS is a minifier-assigned identifier and re-rolls on a
    # lolmath redeploy (16.18.1: A.ChampionKey -> x.ChampionKey,
    # k.DamageType -> I.DamageType, w.LanePosition -> A.LanePosition), so
    # match ANY alias and key on the enum name. Pinning the letter made every
    # enum fall through to the dotted-ref -> null rule below and silently
    # emptied scenarios + lane_positions.
    (re.compile(
        r"(?<![\w$.])[A-Za-z_$][\w$]*\."
        r"(?:ChampionKey|DamageType|TargetType|UsageType|LanePosition|GameModes|MapId)"
        r"\.([A-Za-z_$][\w$]*)"
    ), r'"\1"'),
    # Cooldown helper calls - minified per champion (different letter each time):
    # `<id>("P")`, `<id>("Q")`, etc. Replace with null; cooldown table is sourced separately.
    # Lookbehind, not `\b`: a `$`-led name (16.18.1 Ashe: `$("P")`) has no
    # word boundary before it, and missing it drops the whole champion.
    (re.compile(r'(?<![\w$])[A-Za-z_$][\w$]*\("[PQWER]"\)'), "null"),
    # Computed keys like `[j.calibrumBasic]:` or `[ny.ZaahenAbilities.Q2]:`
    # -> keep the trailing leaf segment as a quoted string key.
    (re.compile(r"\[[A-Za-z_$][\w$.]*\.([A-Za-z_$][\w$]*)\]\s*:"), r'"\1":'),
    # Numeric object keys - JSON5 requires them to be quoted.
    (re.compile(r"([{,])\s*(\d+)\s*:"), r'\1"\2":'),
    # Surviving dotted member references in *value* positions -> null.
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
        # No trailing comma - the surrounding source already has separators,
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


# --- Lolmath chunk -> structured records --------------------------------------

@dataclass
class LolmathExtract:
    # Sourced from the scenarios chunk:
    cooldowns: dict[str, dict[str, list[float | None]]]
    roles: dict[str, list[str]]
    ratings: dict[str, dict[str, Any]]
    lane_positions: list[str]
    scenarios: dict[str, list[dict]]   # championKey -> list of scenario records
    chunk_url: str
    chunk_bytes: int
    # Sourced from the data chunk (Phase 1.5):
    aram_modifiers: dict[str, dict[str, float]]      # DDragon-id -> modifier dict
    damage_distribution: dict[str, dict[str, float]]  # DDragon-id -> {physical, magical, trued}
    skill_orders: dict[str, list[str]]                # DDragon-id -> ["Q","E","W",...]
    data_chunk_url: str
    data_chunk_bytes: int
    # block -> chunk URL; the three blocks live in different chunks since 16.18.1.
    data_block_sources: dict[str, str] = field(default_factory=dict)
    # piece -> chunk URL (``scenarios`` -> list of URLs); the scenario-chunk
    # pieces live in different chunks since 16.21.1.
    scenario_sources: dict[str, Any] = field(default_factory=dict)


_LANE_TOKENS = frozenset({"top", "jungle", "mid", "adc", "support"})
# A use-strict factory without one of these cannot hold a scenario record, the
# ratings dict or the lane list, so it is not parsed.
_SCENARIO_FACTORY_MARKERS = ("championKey", _RATINGS_MARKER, "LanePosition")


def extract_from_chunk(chunk: str, chunk_url: str) -> LolmathExtract:
    """Single-chunk layout (through 16.20.1): every piece in ``chunk``."""
    return extract_from_bodies({chunk_url: chunk}, preferred=chunk_url)


def extract_from_bodies(bodies: dict[str, str], preferred: str) -> LolmathExtract:
    """Pull the scenario-chunk pieces from WHICHEVER fetched chunk holds each.

    Through 16.20.1 one chunk carried the cooldown ``JSON.parse`` table, the
    roles factory, the ratings dict, the lane list and every scenario record.
    16.21.1 split them: cooldowns + the default champion's scenario in one
    root chunk, roles + ratings + lanes in another, the other scenarios in a
    lazily loaded chunk. Each piece is searched in ``preferred`` (the
    scenarios chunk) first, then every other body in URL order, so the
    single-chunk layout resolves exactly as before. Scenario records are
    merged across every use-strict factory of every body that carries
    ``statPreference:`` or the ratings marker. ``chunk_url`` stays
    ``preferred``.
    """
    order = ([preferred] if preferred in bodies else []) + sorted(
        u for u in bodies if u != preferred
    )
    sources: dict[str, Any] = {}

    cooldowns: dict | None = None
    for url in order:
        try:
            payload = _extract_json_parse_string(bodies[url], COOLDOWN_PAYLOAD_ANCHOR)
        except RuntimeError:
            continue
        if isinstance(payload, dict):
            cooldowns = payload
            sources["cooldowns"] = url
            break
    if cooldowns is None:
        raise RuntimeError(
            f"JSON.parse(...) with anchor {COOLDOWN_PAYLOAD_ANCHOR!r} not found "
            "in any fetched chunk"
        )

    roles: dict | None = None
    for url in order:
        try:
            roles = _extract_roles(bodies[url])
        except RuntimeError:
            continue
        sources["roles"] = url
        break
    if roles is None:
        raise RuntimeError("no lolmath roles factory with class-token lists found")

    parsed_by_url: list[tuple[str, dict[str, Any]]] = []
    for url in order:
        chunk = bodies[url]
        if SCENARIO_CHUNK_ANCHOR not in chunk and _RATINGS_MARKER not in chunk:
            continue
        for body in _iter_use_strict_factory_bodies(chunk):
            if not any(m in body for m in _SCENARIO_FACTORY_MARKERS):
                continue
            bindings = _walk_top_level_bindings(body)
            parsed = _parse_top_level(bindings)
            log.info("use-strict factory in %s: parsed %d/%d bindings",
                     url.rsplit("/", 1)[-1], len(parsed), len(bindings))
            parsed_by_url.append((url, parsed))

    # Collect scenarios - they're arrays whose first element has settings.championKey.
    scenarios: dict[str, list[dict]] = {}
    scenario_urls: list[str] = []

    def collect_scenario(rec: Any) -> bool:
        if not isinstance(rec, list) or not rec:
            return False
        first = rec[0]
        if not isinstance(first, dict):
            return False
        ck = first.get("settings", {}).get("championKey") if isinstance(first.get("settings"), dict) else None
        if ck:
            existing = scenarios.get(ck)
            if existing is None or len(rec) > len(existing):
                scenarios[ck] = rec
            return True
        return False

    for url, parsed in parsed_by_url:
        hit = False
        for val in parsed.values():
            hit = collect_scenario(val) or hit
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
        if hit and url not in scenario_urls:
            scenario_urls.append(url)
    sources["scenarios"] = scenario_urls

    # Ratings, lane positions: lookup by content shape, first body in `order`.
    # `let D = {<champname>: {ratings: {...}}}` is the global ratings dict; the
    # lane table is a list of lane tokens ONLY (a broader multi-chunk scan
    # meets long string lists that merely contain a lane word).
    ratings: dict[str, dict[str, Any]] = {}
    lane_positions: list[str] = []
    for url, parsed in parsed_by_url:
        for val in parsed.values():
            if (
                not ratings
                and isinstance(val, dict)
                and "Aatrox" in val
                and isinstance(val["Aatrox"], dict)
                and "ratings" in val["Aatrox"]
            ):
                ratings = val
                sources["ratings"] = url
            elif (
                not lane_positions
                and isinstance(val, list)
                and val
                and all(isinstance(x, str) for x in val)
                and set(val) <= _LANE_TOKENS
            ):
                lane_positions = val
                sources["lane_positions"] = url

    log.info(
        "extract: cooldowns=%d roles=%d ratings=%d lanes=%d scenarios=%d sources=%s",
        len(cooldowns), len(roles), len(ratings), len(lane_positions), len(scenarios),
        sources,
    )
    return LolmathExtract(
        cooldowns=cooldowns,
        roles=roles,
        ratings=ratings,
        lane_positions=lane_positions,
        scenarios=scenarios,
        chunk_url=preferred,
        chunk_bytes=len(bodies.get(preferred, "")),
        aram_modifiers={},
        damage_distribution={},
        skill_orders={},
        data_chunk_url="",
        data_chunk_bytes=0,
        scenario_sources=sources,
    )


# --- Phase 1.5: data chunk extraction ----------------------------------------

def extract_data_chunk(chunk: str, chunk_url: str) -> dict[str, Any]:
    """Pull the three Phase 1.5 datasets from the data chunk.

    The data chunk ships 12 ``JSON.parse('...')`` blocks. We only need three:
      * ARAM per-champion modifier table (block 0)
      * physical/magical/trued damage distribution (block 5)
      * canonical skill-up order (block 9)

    All three are keyed by DDragon id (``Aatrox``, ``MonkeyKing``, etc.) - no
    lolmath alias dance needed. Returned dict has keys ``aram_modifiers``,
    ``damage_distribution``, ``skill_orders``, ``data_chunk_url``,
    ``data_chunk_bytes``.
    """
    aram = _extract_json_parse_string(chunk, ARAM_MODIFIERS_ANCHOR)
    damage = _extract_json_parse_string(chunk, DAMAGE_DISTRIBUTION_ANCHOR)
    skills = _extract_json_parse_string(chunk, SKILL_ORDER_ANCHOR)

    if not isinstance(aram, dict) or not isinstance(damage, dict) or not isinstance(skills, dict):
        raise RuntimeError("data chunk anchors did not yield dict payloads")

    log.info(
        "data chunk extract: aram=%d damage=%d skills=%d",
        len(aram), len(damage), len(skills),
    )
    return {
        "aram_modifiers": aram,
        "damage_distribution": damage,
        "skill_orders": skills,
        "data_chunk_url": chunk_url,
        "data_chunk_bytes": len(chunk),
    }


def check_lolmath_coverage(lolmath: LolmathExtract) -> list[str]:
    """Make a partial scenarios-chunk parse loud instead of silent.

    Raises when the scenario or lane table is EMPTY (the 16.18.1 enum-alias
    re-roll produced exactly that with no exception). Otherwise returns, and
    logs, the DDragon ids that have a cooldown row but no scenario - a
    single-champion parse miss (16.18.1 Ashe) that would otherwise just
    shrink scenarios.json by one.
    """
    if not lolmath.scenarios:
        raise RuntimeError("lolmath extract produced 0 scenarios - parser drift")
    if not lolmath.lane_positions:
        raise RuntimeError("lolmath extract produced 0 lane positions - parser drift")
    ids = set(lolmath.cooldowns)
    covered = {_championkey_to_ddragon_id(ck, ids) for ck in lolmath.scenarios}
    missing = sorted(ids - covered)
    if missing:
        log.warning("lolmath: %d champion(s) have no scenario: %s", len(missing), missing)
    return missing


# RM-805: a (near) all-neutral ARAM modifier table is not a balance patch. The
# committed snapshots 16.10.1 .. 16.20.1 carry 21-24 percent neutral rows; the
# 16.21.1 lolmath table came back 173/173 neutral and was accepted silently
# until an adjudication carried the 16.20.1 block forward. A table at or above
# this fraction stops the extract before anything is written; the only way
# past it is ``--allow-neutral-aram REASON``, which is logged and recorded in
# the manifest (``aram_modifiers_neutral_override``).
ARAM_NEUTRAL_FAIL_FRACTION = 0.95
EXIT_ARAM_NEUTRAL = 3
# Same field semantics as core/aram_balance_context.py (_GRID_MULT_FIELDS /
# _GRID_FLAT_FIELDS): the multipliers are neutral at 1.0, ability haste is an
# additive flat value, neutral at 0. A missing or non-numeric field carries no
# information and counts as neutral.
_ARAM_MULT_FIELDS = (
    "aramDamageDealt",
    "aramDamageTaken",
    "aramHealing",
    "aramShielding",
    "aramTenacity",
    "aramAttackSpeed",
)
_ARAM_FLAT_FIELDS = ("aramAbilityHaste",)


class NeutralAramTableError(RuntimeError):
    """The lolmath ARAM modifier table came back (near) all-neutral (RM-805)."""


def _aram_row_is_neutral(row: Any) -> bool:
    if not isinstance(row, dict):
        return True
    for fields, neutral in ((_ARAM_MULT_FIELDS, 1.0), (_ARAM_FLAT_FIELDS, 0.0)):
        for key in fields:
            val = row.get(key)
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            if val != neutral:
                return False
    return True


def check_aram_neutrality(aram_modifiers: dict[str, Any],
                          override_reason: str | None = None) -> dict[str, Any]:
    """Fail loudly when the ARAM table is >= 95 percent neutral (RM-805).

    Returns the measurement ``{rows, neutral_rows, neutral_fraction,
    threshold}``. At or above ``ARAM_NEUTRAL_FAIL_FRACTION`` (an empty table
    included) it raises ``NeutralAramTableError`` naming the counts, unless
    ``override_reason`` is a non-blank string: then it logs a WARNING and adds
    ``override_reason`` to the measurement so the caller records it.
    """
    rows = len(aram_modifiers)
    neutral_rows = sum(1 for row in aram_modifiers.values() if _aram_row_is_neutral(row))
    fraction = neutral_rows / rows if rows else 1.0
    out: dict[str, Any] = {
        "rows": rows,
        "neutral_rows": neutral_rows,
        "neutral_fraction": round(fraction, 4),
        "threshold": ARAM_NEUTRAL_FAIL_FRACTION,
    }
    reason = (override_reason or "").strip()
    if fraction < ARAM_NEUTRAL_FAIL_FRACTION:
        if reason:
            log.info("--allow-neutral-aram not needed: ARAM table %d/%d neutral",
                     neutral_rows, rows)
        return out
    shape = f"{neutral_rows}/{rows} neutral ({fraction:.1%})" if rows else "empty (0 rows)"
    if not reason:
        raise NeutralAramTableError(
            f"RM-805: the lolmath ARAM modifier table is {shape}, at or above "
            f"the {ARAM_NEUTRAL_FAIL_FRACTION:.0%} floor - an upstream reset or "
            "parser drift, not a balance patch; nothing was written. Adjudicate "
            "it, then re-run with --allow-neutral-aram REASON to accept it as an "
            "explicit, recorded act (a carry-forward is recorded in the manifest "
            "as aram_modifiers_carry)."
        )
    log.warning(
        "RM-805 override: accepting a lolmath ARAM modifier table that is %s "
        "(floor %.0f%%) - reason: %s",
        shape, ARAM_NEUTRAL_FAIL_FRACTION * 100, reason,
    )
    out["override_reason"] = reason
    return out


# RM-807 (a) + (b): the damage-split and skill-order blocks have RM-805's
# silent-default shape. An all-zero split reads downstream as "no damage axis"
# and an empty skill order as "no order", and both were written into
# champions.json like real data. Every committed snapshot 16.10.1 .. 16.21.1
# carries 0 degenerate rows in either block, so a block at or above this
# fraction (an empty block included) stops the extract before anything is
# written; the only way past it is ``--allow-degenerate-lolmath REASON``,
# logged and recorded in the manifest (``lolmath_degenerate_override``).
LOLMATH_BLOCK_FAIL_FRACTION = 0.95
EXIT_LOLMATH_DEGENERATE = 5
_DAMAGE_SPLIT_FIELDS = ("physical", "magical", "trued")
_SKILL_SLOTS = frozenset({"Q", "W", "E", "R"})


class DegenerateLolmathBlockError(RuntimeError):
    """A lolmath damage-split or skill-order block came back degenerate (RM-807)."""


def _damage_row_is_degenerate(row: Any) -> bool:
    """True unless one of the three split fields is a positive finite share."""
    if not isinstance(row, dict):
        return True
    for key in _DAMAGE_SPLIT_FIELDS:
        val = row.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        if math.isfinite(val) and val > 0:
            return False
    return True


def _skill_order_is_degenerate(row: Any) -> bool:
    """True unless the order is a list naming at least one Q / W / E / R slot.

    Real orders carry a ``None`` at some levels, so a gap is not degenerate.
    """
    if not isinstance(row, list):
        return True
    return not any(isinstance(s, str) and s in _SKILL_SLOTS for s in row)


def check_lolmath_blocks(damage_distribution: dict[str, Any],
                         skill_orders: dict[str, Any],
                         override_reason: str | None = None) -> dict[str, Any]:
    """Fail loudly when a damage-split or skill-order block is degenerate (RM-807).

    Returns ``{damage_distribution: {rows, degenerate_rows,
    degenerate_fraction}, skill_orders: {...}, threshold}``. A block at or
    above ``LOLMATH_BLOCK_FAIL_FRACTION`` (an empty one included) raises
    ``DegenerateLolmathBlockError`` naming every such block, unless
    ``override_reason`` is a non-blank string: then it logs a WARNING and adds
    ``override_reason``. Degenerate rows below the floor are named in a WARNING.
    """
    out: dict[str, Any] = {"threshold": LOLMATH_BLOCK_FAIL_FRACTION}
    failing: list[str] = []
    for name, table, is_degenerate in (
            ("damage_distribution", damage_distribution, _damage_row_is_degenerate),
            ("skill_orders", skill_orders, _skill_order_is_degenerate)):
        rows = len(table)
        bad = sorted(cid for cid, row in table.items() if is_degenerate(row))
        fraction = len(bad) / rows if rows else 1.0
        out[name] = {
            "rows": rows,
            "degenerate_rows": len(bad),
            "degenerate_fraction": round(fraction, 4),
        }
        if fraction >= LOLMATH_BLOCK_FAIL_FRACTION:
            shape = f"{len(bad)}/{rows} degenerate ({fraction:.1%})" if rows else "empty (0 rows)"
            failing.append(f"{name} {shape}")
        elif bad:
            log.warning("lolmath %s: %d/%d degenerate row(s): %s",
                        name, len(bad), rows, bad)
    reason = (override_reason or "").strip()
    if not failing:
        if reason:
            log.info("--allow-degenerate-lolmath not needed: no block at the floor")
        return out
    detail = "; ".join(failing)
    if not reason:
        raise DegenerateLolmathBlockError(
            f"RM-807: lolmath {detail}, at or above the "
            f"{LOLMATH_BLOCK_FAIL_FRACTION:.0%} floor - an upstream reset or "
            "parser drift, not a balance patch; nothing was written. Adjudicate "
            "it, then re-run with --allow-degenerate-lolmath REASON to accept it "
            "as an explicit, recorded act."
        )
    log.warning(
        "RM-807 override: accepting lolmath %s (floor %.0f%%) - reason: %s",
        detail, LOLMATH_BLOCK_FAIL_FRACTION * 100, reason,
    )
    out["override_reason"] = reason
    return out


def _degenerate_override_record(block_check: dict[str, Any]) -> dict[str, Any]:
    return {
        "flag": "--allow-degenerate-lolmath",
        "reason": block_check["override_reason"],
        "threshold": block_check["threshold"],
        "blocks": {name: dict(block_check[name])
                   for name in ("damage_distribution", "skill_orders")},
    }


_DATA_BLOCKS = (
    ("aram_modifiers", ARAM_MODIFIERS_ANCHOR),
    ("damage_distribution", DAMAGE_DISTRIBUTION_ANCHOR),
    ("skill_orders", SKILL_ORDER_ANCHOR),
)


def extract_data_blocks(bodies: dict[str, str], preferred: str) -> dict[str, Any]:
    """Pull the three Phase 1.5 datasets from WHICHEVER fetched chunk holds each.

    Until 16.15.1 all three lived in one "data chunk"; at 16.18.1 lolmath split
    them across three chunks (ARAM table in a lazily loaded chunk, damage
    distribution in the scenarios chunk, skill orders in a third). Each block
    is searched in ``preferred`` first, then in every other body in URL order,
    so the single-chunk layout resolves exactly as before. Returns the
    ``extract_data_chunk`` keys plus ``block_sources`` (block -> chunk URL);
    ``data_chunk_url`` stays the chunk that holds the ARAM table. Raises
    ``RuntimeError`` naming any block no body carries.
    """
    order = ([preferred] if preferred in bodies else []) + sorted(
        u for u in bodies if u != preferred
    )
    found: dict[str, dict] = {}
    sources: dict[str, str] = {}
    for key, anchor in _DATA_BLOCKS:
        for url in order:
            try:
                payload = _extract_json_parse_string(bodies[url], anchor)
            except RuntimeError:
                continue
            if isinstance(payload, dict):
                found[key] = payload
                sources[key] = url
                break
    missing = [key for key, _ in _DATA_BLOCKS if key not in found]
    if missing:
        raise RuntimeError(
            f"lolmath data blocks not found in any fetched chunk: {missing}"
        )
    log.info(
        "data blocks extract: aram=%d damage=%d skills=%d sources=%s",
        len(found["aram_modifiers"]), len(found["damage_distribution"]),
        len(found["skill_orders"]), sources,
    )
    aram_url = sources["aram_modifiers"]
    return {
        "aram_modifiers": found["aram_modifiers"],
        "damage_distribution": found["damage_distribution"],
        "skill_orders": found["skill_orders"],
        "data_chunk_url": aram_url,
        "data_chunk_bytes": len(bodies[aram_url]),
        "block_sources": sources,
    }


# --- DDragon -----------------------------------------------------------------

@dataclass
class DDragonSnapshot:
    version: str
    champions: dict[str, dict]   # championId (e.g. "Aatrox") -> DDragon champion record
    items: dict[str, dict]       # itemId-string -> DDragon item record


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


# --- Meraki perlevel backfill (Phase 1.5) ------------------------------------

# DDragon's bulk and per-champion endpoints both ship `attackdamageperlevel: 0`
# for every champion as of patch 16.x - Riot stopped exporting AD growth even
# though the in-game value is non-zero. Meraki Analytics scrapes the actual
# game data and exposes it under `stats.attackDamage.perLevel`. We overlay
# only this one field; the other zero perlevel fields in DDragon (Jhin AS,
# Thresh armor, Briar HP-regen, every champion's crit growth) are correct.
def _meraki_perlevel_of(payload: Any) -> Any:
    """Safely read ``stats.attackDamage.perLevel`` out of a Meraki champion."""
    if not isinstance(payload, dict):
        return None
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        return None
    ad = stats.get("attackDamage")
    if not isinstance(ad, dict):
        return None
    return ad.get("perLevel")


def _fetch_meraki_bulk() -> dict | None:
    """Fetch the Meraki BULK champions map (one request for the whole roster)."""
    try:
        raw = _fetch_json(MERAKI_BULK_URL, timeout=90)
    except Exception as e:  # noqa: BLE001 - bulk is best-effort, we fall back
        log.warning("meraki bulk fetch failed (%s); falling back per-champion", e)
        return None
    return raw if isinstance(raw, dict) else None


def _fetch_meraki_champion(cid: str) -> dict | None:
    """Fetch a single champion from the Meraki PER-CHAMPION endpoint."""
    try:
        req = urllib.request.Request(
            f"{MERAKI_BASE}/{cid}.json",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log.warning("meraki fetch failed for %s: %s", cid, e)
        return None


def fetch_meraki_perlevel_overlay(
    ddragon_ids: set[str],
    *,
    _bulk_fn=None,
    _per_champ_fn=None,
) -> dict[str, dict[str, float]]:
    """Fetch attackdamageperlevel from Meraki Analytics for each champion.

    Returns ``{ddragon_id: {ddragon_field_name: value}}`` only for champions
    where Meraki has a non-zero value. Failures (HTTP errors, missing
    champions) are logged and skipped - extraction continues with whatever
    DDragon shipped for that champion.

    Reads the BULK endpoint first (one request for the whole roster) and only
    falls back to the per-champion endpoint for champions the bulk map does not
    cover. 2026-07-18: the per-champion endpoint 404s for champions Meraki has
    not published individually (Locke, Zaahen, Yunara), and because DDragon
    ships ``attackdamageperlevel: 0`` for EVERY champion, a failed backfill
    silently persists a FALSE ZERO. Yunara sits in the bulk map at
    ``perLevel = 2.5`` while her per-champion URL 404s, so bulk-first recovers
    her; Locke and Zaahen are absent from Meraki entirely and still miss.
    Genuine zeros (Senna, who gains AD from Mist souls) stay unwritten via the
    ``> 0`` guard below.

    ``_bulk_fn`` / ``_per_champ_fn`` are offline test seams.
    """
    bulk_fn = _bulk_fn or _fetch_meraki_bulk
    per_champ_fn = _per_champ_fn or _fetch_meraki_champion

    overlay: dict[str, dict[str, float]] = {}
    misses: list[str] = []
    log.info("meraki perlevel backfill starting (%d champions)", len(ddragon_ids))
    t0 = time.time()

    bulk = bulk_fn()
    if not isinstance(bulk, dict):
        bulk = {}
    from_bulk = 0
    for cid in sorted(ddragon_ids):
        m = bulk.get(cid)
        if m is not None:
            from_bulk += 1
        else:
            m = per_champ_fn(cid)
        if m is None:
            misses.append(cid)
            continue
        ad_growth = _meraki_perlevel_of(m)
        if isinstance(ad_growth, (int, float)) and ad_growth > 0:
            overlay[cid] = {"attackdamageperlevel": float(ad_growth)}

    elapsed = time.time() - t0
    log.info(
        "meraki perlevel backfill: %d filled (%d from bulk), %d skipped (%.1fs)",
        len(overlay), from_bulk, len(misses), elapsed,
    )
    if misses:
        log.warning("meraki misses: %s", misses)
    return overlay


# --- Meraki items (Phase 4 batch 20) -----------------------------------------

# DDragon item ``description`` strips numeric coefficients from passive prose
# (Hullbreaker Skipper "consumes all stacks to deal bonus physical damage" -
# no number; Essence Reaver Spellblade "deals bonus physical damage" - no
# number). Meraki Analytics scrapes the wiki + game data and exposes the
# numeric formula text in ``passives[*].effects`` as wikitext (the {{as|...|ad}}
# token format). The engine consumer (effects.py) doesn't parse the wikitext
# at runtime - coefficients still get pinned by hand per patch - but having
# the structured Meraki snapshot in the extracted bundle:
#   1. Makes the manual pinning auditable ("here's the source text I read")
#   2. Surfaces patch-to-patch text changes (next extract diff flags drift)
#   3. Unblocks future automated coefficient-extractor passes (defer until
#      we have >10 items demanding it)
def fetch_meraki_items() -> dict:
    """Fetch Meraki's bulk items endpoint and return a normalized payload.

    Returns ``{"fetched_at": <iso>, "source": <url>, "count": N,
               "items": {<id>: {name, passives, active, simpleDescription, ...}}}``

    Failure raises - Meraki bulk items is small (~3.2MB) and stable.
    """
    log.info("fetching Meraki bulk items: %s", MERAKI_ITEMS_URL)
    raw = _fetch_json(MERAKI_ITEMS_URL)
    if not isinstance(raw, dict):
        raise RuntimeError(f"Meraki items: expected dict, got {type(raw).__name__}")
    items_out: dict[str, dict] = {}
    for iid, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        # Trim to the fields the engine + audit need; drop the 30+ stat
        # buckets DDragon already covers (we have items.json for that).
        items_out[str(iid)] = {
            "name": entry.get("name"),
            "id": entry.get("id"),
            "tier": entry.get("tier"),
            "rank": entry.get("rank"),
            "removed": entry.get("removed", False),
            "simpleDescription": entry.get("simpleDescription") or "",
            "passives": entry.get("passives") or [],
            "active": entry.get("active") or [],
            "shop": entry.get("shop") or {},
            "noEffects": entry.get("noEffects", False),
        }
    log.info("Meraki items fetched: %d", len(items_out))
    return {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": MERAKI_ITEMS_URL,
        "count": len(items_out),
        "items": items_out,
    }


# --- Arena augments (Phase 6) ------------------------------------------------

# cdragon's arena dump has 219 augments across 4 rarities:
#   0 = Silver, 1 = Gold, 2 = Prismatic, 4 = Hero (GoH = Guardian of Heaven)
# Source is "latest" - augment rotations don't fully align with DDragon patches,
# so the arena_augments file carries its own `cdragon_fetched_at` timestamp.
def fetch_arena_augments() -> dict:
    """Fetch the cdragon Arena augment dump and return a normalized payload.

    Returns ``{"fetched_at": <iso>, "source": <url>, "count": N,
               "augments": [{id, apiName, name, rarity, desc, tooltip,
                             dataValues, calculations, iconLarge, iconSmall}, ...]}``

    NOTE: this docstring used to advertise a ``version`` key that the function
    never actually returned. The patch marker is applied at the WRITE site by
    ``stamp_patch`` (spelled ``patch``), not here - the fetch helper stays pure
    transport.

    Failure raises - augment data is small (~400KB) and rarely flaky.
    """
    log.info("fetching cdragon arena augments: %s", CDRAGON_ARENA_URL)
    raw = _fetch_json(CDRAGON_ARENA_URL)
    augs_in = raw.get("augments", []) if isinstance(raw, dict) else []
    augs_out: list[dict] = []
    for a in augs_in:
        if not isinstance(a, dict):
            continue
        augs_out.append({
            "id": a.get("id"),
            "apiName": a.get("apiName"),
            "name": a.get("name"),
            "rarity": a.get("rarity"),
            "desc": a.get("desc", ""),
            "tooltip": a.get("tooltip", ""),
            "dataValues": a.get("dataValues") or {},
            "calculations": a.get("calculations") or {},
            "iconLarge": a.get("iconLarge"),
            "iconSmall": a.get("iconSmall"),
        })
    log.info("arena augments fetched: %d", len(augs_out))
    return {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": CDRAGON_ARENA_URL,
        "count": len(augs_out),
        "augments": augs_out,
    }


# RM-807 (d): both fetchers above read an empty upstream (an empty dict, a
# missing "augments" key, a non-dict body) as count 0, and it was written into
# items_meraki.json / arena_augments.json and the manifest like real data.
# Every committed snapshot 16.10.1 .. 16.21.1 carries 320 Meraki items and
# 220-227 Arena augments, so the floors sit at half the measured minimum: a
# count below one is an upstream reset or shape drift, not a patch. The gate
# runs before the per-champion overlay fetch and any write; the only way past
# it is ``--allow-short-upstream REASON``, logged and recorded in the manifest
# (``upstream_short_override``).
MERAKI_ITEMS_MIN = 160
ARENA_AUGMENTS_MIN = 110
EXIT_UPSTREAM_SHORT = 6


class ShortUpstreamError(RuntimeError):
    """The Meraki items or CDragon Arena augment upstream came back short (RM-807)."""


def check_upstream_counts(arena_augments: dict | None, meraki_items: dict | None,
                          override_reason: str | None = None) -> dict[str, Any]:
    """Fail loudly when the Meraki items or Arena augments payload is short (RM-807).

    The count is measured from the payload body (``augments`` list, ``items``
    dict), never its ``count`` key. Returns ``{arena_augments: {count, floor},
    meraki_items: {count, floor}}``. A payload under its floor raises
    ``ShortUpstreamError`` naming every such source, unless
    ``override_reason`` is a non-blank string: then it logs a WARNING and adds
    ``override_reason``.
    """
    augs = arena_augments if isinstance(arena_augments, dict) else {}
    mer = meraki_items if isinstance(meraki_items, dict) else {}
    aug_body = augs.get("augments")
    mer_body = mer.get("items")
    counts = (
        ("arena_augments", len(aug_body) if isinstance(aug_body, list) else 0,
         ARENA_AUGMENTS_MIN),
        ("meraki_items", len(mer_body) if isinstance(mer_body, dict) else 0,
         MERAKI_ITEMS_MIN),
    )
    out: dict[str, Any] = {name: {"count": n, "floor": floor}
                           for name, n, floor in counts}
    failing = [f"{name} {n} (floor {floor})" for name, n, floor in counts if n < floor]
    reason = (override_reason or "").strip()
    if not failing:
        if reason:
            log.info("--allow-short-upstream not needed: every upstream at its floor")
        return out
    detail = "; ".join(failing)
    if not reason:
        raise ShortUpstreamError(
            f"RM-807: upstream {detail} - an upstream reset or shape drift, not "
            "a patch; nothing was written. Adjudicate it, then re-run with "
            "--allow-short-upstream REASON to accept it as an explicit, recorded act."
        )
    log.warning("RM-807 override: accepting upstream %s - reason: %s", detail, reason)
    out["override_reason"] = reason
    return out


def _short_upstream_override_record(upstream_check: dict[str, Any]) -> dict[str, Any]:
    return {
        "flag": "--allow-short-upstream",
        "reason": upstream_check["override_reason"],
        **{name: dict(upstream_check[name]) for name in ("arena_augments", "meraki_items")},
    }


# --- Patch stamping (RM-81 residual) -----------------------------------------

# arena_augments.json and items_meraki.json were the only two artifacts under
# data/daemon_slayer/<patch>/ with NO internal patch marker of any spelling
# (measured 2026-07-24 across 16.10.1 .. 16.14.1). Both are re-fetched every
# extract from MUTABLE `latest` endpoints, so a patch-refresh commit that copied
# either forward was undetectable by inspection - the RM-81 bug class that
# `cdragon_ability_ratios.json` already closed for itself.
#
# Every other artifact stamps itself at build time (champions/items/scenarios
# via `version`, manifest via `ddragon_version`). These two are stamped here at
# the write site instead of inside the fetchers, so the fetch helpers stay pure
# transport and the stamp lives next to the directory it must agree with.
#
# `patch` is the canonical spelling - it is what the RM-81 reference guard
# (agents/daemon_slayer/abilities.cdragon_sidecar_patch) reads. The four other
# spellings already on disk (`_patch`, `rc_patch`, `ddragon_version`, `version`)
# are pre-existing divergence: read tolerantly by
# abilities.artifact_patch_marker, never re-spelled here.
def stamp_patch(payload: dict, patch: str) -> dict:
    """Return a copy of ``payload`` declaring the ``patch`` it was built for.

    Non-mutating so a caller that reuses the payload (build_manifest reads both
    of these) sees no surprise key.
    """
    return {**payload, "patch": patch}


# --- Emission ----------------------------------------------------------------

_CANONICAL_ALIAS_PATH = (
    Path(__file__).parent.parent / "web" / "data" / "champion_aliases.json"
)


def _load_champion_aliases() -> dict[str, str]:
    """Load the canonical display-name -> DDragon-id alias map.

    Source of truth at ``web/data/champion_aliases.json``; the same file is
    fetched at runtime by ``web/js/lib/items_index.js``. Keys are
    lowercase-alphanumeric of the source
    name (matching the JS ``replace(/[^a-z0-9]/g, "")`` normalization).
    """
    return json.loads(_CANONICAL_ALIAS_PATH.read_text("utf-8"))


# Aliases for champions whose DDragon id doesn't match their lolmath
# camelCase key after case+alphanum normalization. Loaded from the canonical
# JSON file shared with the JS resolvers.
_LOLMATH_TO_DDRAGON_ALIAS = _load_champion_aliases()


def _championkey_to_ddragon_id(key: str, ddragon_ids: set[str]) -> str | None:
    """lolmath uses camelCase keys (``aatrox``, ``leBlanc``, ``drMundo``);
    DDragon uses PascalCase ids (``Aatrox``, ``Leblanc``, ``DrMundo``)."""
    if not key:
        return None
    # Canonical alias keys are lowercase-alphanumeric (matches the JS
    # resolver); normalize the lolmath camelCase key the same way before
    # lookup so "nunuWillump" -> "nunuwillump" finds the canonical entry.
    norm_key = re.sub(r"[^a-z0-9]", "", key.lower())
    if norm_key in _LOLMATH_TO_DDRAGON_ALIAS:
        cand = _LOLMATH_TO_DDRAGON_ALIAS[norm_key]
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


def _lolmath_block(lolmath: LolmathExtract, champ_id: str) -> dict[str, Any]:
    """One champion's ``lolmath`` sub-object in ``champions.json``.

    Shared by the full extract and ``--lolmath-only`` so both write the same
    shape for the same lolmath data.
    """
    rating_rec = lolmath.ratings.get(champ_id)
    ratings = rating_rec.get("ratings") if isinstance(rating_rec, dict) else None
    return {
        "cooldowns": lolmath.cooldowns.get(champ_id),                    # {Q: [...], W: [...], E: [...], R: [...]}
        "roles": lolmath.roles.get(champ_id),                            # ["FIGHTER", "TANK"]
        "ratings": ratings,                                              # {healing, shielding}
        "aram_modifiers": lolmath.aram_modifiers.get(champ_id),          # {aramDamageTaken, aramDamageDealt, ...}
        "damage_distribution": lolmath.damage_distribution.get(champ_id),  # {physical, magical, trued}
        "skill_order": lolmath.skill_orders.get(champ_id),               # ["Q","E","W",...]  (length 18)
    }


def build_champions_payload(
    lolmath: LolmathExtract,
    dd: DDragonSnapshot,
    perlevel_overlay: dict[str, dict[str, float]] | None = None,
) -> dict:
    """Merge DDragon champion data with lolmath cooldowns/roles/ratings + Phase 1.5 fields.

    ``perlevel_overlay`` (optional): per-champion ``{field: value}`` map from
    :func:`fetch_meraki_perlevel_overlay`; values are written ONLY when DDragon
    has zero in the same field, so legitimate zeros (Jhin AS, Thresh armor) stay
    untouched.
    """
    out: dict[str, Any] = {"version": dd.version, "data": {}}
    # DDragon ships a THROWBACK-MODE registry beside the live one (16.15.1 adds
    # 60 Jade_<Champion> rows at base_key + 60000). Nothing downstream can cover
    # them - Meraki 404s all 60 - so they never enter the snapshot. See
    # agents.daemon_slayer.mode_variants.
    dd_champions = canonical_champions(dd.champions)
    ddids = set(dd_champions.keys())

    # Start with lolmath's PascalCase champion key set (it's the canonical set the
    # engine cares about). For each, find the DDragon id if any.
    for champ_id, dd_record in dd_champions.items():
        stats = dict(dd_record.get("stats", {}))
        if perlevel_overlay:
            for field, value in perlevel_overlay.get(champ_id, {}).items():
                if stats.get(field, 0) == 0:
                    stats[field] = value
        out["data"][champ_id] = {
            "id": champ_id,
            "key": dd_record.get("key"),
            "name": dd_record.get("name"),
            "title": dd_record.get("title"),
            "tags": dd_record.get("tags", []),
            "stats": stats,
            "info": dd_record.get("info", {}),
            "partype": dd_record.get("partype"),
            "lolmath": _lolmath_block(lolmath, champ_id),
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
    # Same partition on the item axis: 16.15.1 adds 162 throwback rows in
    # [770000, 780000) - retired gear (Sightstone, Zz'Rot Portal, Hex Core) most
    # of which is flagged map-12 legal, which would pollute the ARAM pool.
    return {"version": dd.version, "data": canonical_items(dd.items)}


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


def _meraki_content_patch_from_abilities(patch_dir: Path) -> str | None:
    """Best-effort Meraki CONTENT patch for the manifest provenance.

    The phase-4a abilities extractor records ``meraki_content_patch`` (the
    newest ``patchLastChanged`` across Meraki's frozen ``latest`` snapshot;
    DS source-adoption WIN 2) into the sibling ``champion_abilities.json``.
    Both the Meraki items and the Meraki champion abilities come from the
    same frozen ``latest`` endpoint, so that same content patch describes
    the items pulled here. Returns ``None`` when the sibling file is absent
    or pre-dates WIN 2 (no field) - the manifest must never lie that the
    content is as fresh as ``fetched_at`` implies.
    """
    p = patch_dir / "champion_abilities.json"
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc.get("meraki_content_patch")


def build_manifest(lolmath: LolmathExtract, dd: DDragonSnapshot,
                   patch_dir: Path,
                   perlevel_overlay: dict[str, dict[str, float]] | None = None,
                   arena_augments: dict | None = None,
                   meraki_items: dict | None = None,
                   aram_neutral_override: dict | None = None,
                   lolmath_degenerate_override: dict | None = None,
                   upstream_short_override: dict | None = None) -> dict:
    overlay = perlevel_overlay or {}
    augs = arena_augments or {}
    mer_items = meraki_items or {}
    manifest = {
        "engine": "daemon_slayer",
        "phase": 1.5,
        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ddragon_version": dd.version,
        # Counts describe what the SNAPSHOT ships, so they follow the same
        # throwback partition the payload builders apply. A raw len() here
        # records 233/868 beside a 173/706 file and breaks the manifest-vs-file
        # integrity check.
        "ddragon_champion_count": len(canonical_champions(dd.champions)),
        "ddragon_item_count": len(canonical_items(dd.items)),
        "sources": {
            "ddragon_versions": f"{DDRAGON_BASE}/api/versions.json",
            "ddragon_champions": f"{DDRAGON_BASE}/cdn/{dd.version}/data/en_US/champion.json",
            "ddragon_items": f"{DDRAGON_BASE}/cdn/{dd.version}/data/en_US/item.json",
            **_lolmath_sources(lolmath),
            "meraki_perlevel": f"{MERAKI_BASE}/<champion>.json",
            "meraki_items": MERAKI_ITEMS_URL,
        },
        "lolmath_counts": _lolmath_counts(lolmath),
        "meraki_perlevel_backfill": {
            "champions_filled": len(overlay),
            "fields_filled": sum(len(v) for v in overlay.values()),
            "fields_targeted": sorted({k for v in overlay.values() for k in v}),
        },
        "arena_augments": {
            "count": augs.get("count", 0),
            "fetched_at": augs.get("fetched_at"),
            "source": augs.get("source", CDRAGON_ARENA_URL),
        },
        "meraki_items": {
            "count": mer_items.get("count", 0),
            "fetched_at": mer_items.get("fetched_at"),
            "source": mer_items.get("source", MERAKI_ITEMS_URL),
            "content_patch": _meraki_content_patch_from_abilities(patch_dir),
        },
        "outputs": {
            "champions": str((patch_dir / "champions.json").relative_to(ROOT)),
            "items": str((patch_dir / "items.json").relative_to(ROOT)),
            "scenarios": str((patch_dir / "scenarios.json").relative_to(ROOT)),
            "arena_augments": str((patch_dir / "arena_augments.json").relative_to(ROOT)),
            "items_meraki": str((patch_dir / "items_meraki.json").relative_to(ROOT)),
        },
    }
    if aram_neutral_override:
        # RM-805: the gate was passed by the explicit flag; record who/why.
        manifest["aram_modifiers_neutral_override"] = _neutral_override_record(
            aram_neutral_override)
    if lolmath_degenerate_override:
        manifest["lolmath_degenerate_override"] = _degenerate_override_record(
            lolmath_degenerate_override)
    if upstream_short_override:
        manifest["upstream_short_override"] = _short_upstream_override_record(
            upstream_short_override)
    return manifest


def _lolmath_sources(lolmath: LolmathExtract) -> dict[str, Any]:
    """The lolmath keys of ``manifest["sources"]`` (full extract and refresh)."""
    return {
        "lolmath_scenarios_chunk": lolmath.chunk_url,
        "lolmath_scenarios_chunk_bytes": lolmath.chunk_bytes,
        "lolmath_data_chunk": lolmath.data_chunk_url,
        "lolmath_data_chunk_bytes": lolmath.data_chunk_bytes,
        "lolmath_data_blocks": dict(lolmath.data_block_sources),
        "lolmath_scenario_pieces": dict(lolmath.scenario_sources),
    }


def _lolmath_counts(lolmath: LolmathExtract) -> dict[str, int]:
    return {
        "cooldowns": len(lolmath.cooldowns),
        "roles": len(lolmath.roles),
        "ratings": len(lolmath.ratings),
        "lane_positions": len(lolmath.lane_positions),
        "scenarios": len(lolmath.scenarios),
        "aram_modifiers": len(lolmath.aram_modifiers),
        "damage_distribution": len(lolmath.damage_distribution),
        "skill_orders": len(lolmath.skill_orders),
    }


def _neutral_override_record(aram_check: dict[str, Any]) -> dict[str, Any]:
    return {
        "flag": "--allow-neutral-aram",
        "reason": aram_check["override_reason"],
        "rows": aram_check["rows"],
        "neutral_rows": aram_check["neutral_rows"],
        "neutral_fraction": aram_check["neutral_fraction"],
        "threshold": aram_check["threshold"],
    }


def refresh_manifest_lolmath(manifest: dict[str, Any], lolmath: LolmathExtract,
                             aram_check: dict[str, Any], *,
                             keep_carry: bool,
                             block_check: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a copy of an existing manifest with only its lolmath parts renewed.

    ``--lolmath-only``: the lolmath keys of ``sources`` are replaced in place
    (key order kept), ``lolmath_counts`` is recomputed and ``lolmath_refresh``
    records when and how. ``extracted_at``, the DDragon / Meraki / arena
    blocks and ``outputs`` keep describing the full extract that fetched
    them. The RM-805 records follow the gate: an override is recorded (a stale
    one dropped when the gate passes cleanly), and ``aram_modifiers_carry``
    is dropped unless ``keep_carry``. The RM-807 ``block_check`` record
    follows its gate the same way.
    """
    out = copy.deepcopy(manifest)
    sources = out.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    sources.update(_lolmath_sources(lolmath))
    out["sources"] = sources
    out["lolmath_counts"] = _lolmath_counts(lolmath)
    out["lolmath_refresh"] = {
        "flag": "--lolmath-only",
        "refreshed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": ("lolmath only; DDragon, Meraki and CDragon were not re-fetched, "
                 "so their provenance stays at extracted_at"),
    }
    if "override_reason" in aram_check:
        out["aram_modifiers_neutral_override"] = _neutral_override_record(aram_check)
    else:
        out.pop("aram_modifiers_neutral_override", None)
    if block_check and "override_reason" in block_check:
        out["lolmath_degenerate_override"] = _degenerate_override_record(block_check)
    else:
        out.pop("lolmath_degenerate_override", None)
    if not keep_carry:
        out.pop("aram_modifiers_carry", None)
    return out


# --- Entry point -------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Daemon Slayer Phase 1 data extractor.")
    ap.add_argument("--force", action="store_true",
                    help="re-extract even if the patch directory already exists")
    ap.add_argument("--chunk-url", default=None,
                    help="bypass autodiscovery and fetch this URL for the scenarios chunk")
    ap.add_argument("--data-chunk-url", default=None,
                    help="bypass autodiscovery and fetch this URL for the data chunk (Phase 1.5)")
    ap.add_argument("--patch", default=None,
                    help="override patch label for the output directory (default: DDragon current)")
    ap.add_argument("--allow-neutral-aram", default=None, metavar="REASON",
                    # argparse %-expands help text, so the literal percent is doubled.
                    help="RM-805: accept a lolmath ARAM table that is >= 95%% neutral "
                         f"(the extract otherwise exits {EXIT_ARAM_NEUTRAL} and writes "
                         "nothing); REASON names the adjudication and is logged and "
                         "recorded in the manifest")
    ap.add_argument("--allow-degenerate-lolmath", default=None, metavar="REASON",
                    help="RM-807: accept a lolmath damage-split or skill-order block "
                         "that is >= 95%% degenerate (all-zero splits / empty orders; "
                         f"the extract otherwise exits {EXIT_LOLMATH_DEGENERATE} and "
                         "writes nothing); REASON is logged and recorded in the manifest")
    ap.add_argument("--allow-short-upstream", default=None, metavar="REASON",
                    help=f"RM-807: accept a Meraki items payload under {MERAKI_ITEMS_MIN} "
                         f"or an Arena augments payload under {ARENA_AUGMENTS_MIN} "
                         f"(the extract otherwise exits {EXIT_UPSTREAM_SHORT} and writes "
                         "nothing); REASON is logged and recorded in the manifest")
    ap.add_argument("--lolmath-only", action="store_true",
                    help="refresh ONLY the lolmath data of an existing snapshot "
                         "(needs <patch>/manifest.json; --patch defaults to "
                         "current.txt): no DDragon / Meraki / CDragon fetch; rewrites "
                         "the champions.json lolmath sub-objects, scenarios.json and "
                         "the manifest lolmath fields. Never combines with --force")
    args = ap.parse_args()
    if args.lolmath_only and args.force:
        ap.error("--lolmath-only cannot be combined with --force: a forced "
                 "re-extract re-fetches Meraki, which is never forced")

    log.info("=" * 60)
    if args.lolmath_only:
        log.info("daemon_slayer extract starting (lolmath-only)")
        return _main_lolmath_only(args)
    log.info("daemon_slayer extract starting (force=%s)", args.force)

    # Fetch DDragon first - its version is also the patch label for output.
    dd = fetch_ddragon()
    patch = args.patch or dd.version
    patch_dir = DATA_ROOT / patch

    if patch_dir.exists() and not args.force:
        if (patch_dir / "manifest.json").exists():
            log.info("patch %s already extracted at %s - skip (use --force to redo)",
                     patch, patch_dir)
            _atomic_write_text(DATA_ROOT / "current.txt", patch)
            return 0
        log.info("patch dir %s exists but no manifest - re-extracting", patch_dir)

    # RM-805 / RM-807: the gates run before the remaining fetches and any write.
    try:
        lolmath, aram_check, block_check = _extract_lolmath(args)
    except NeutralAramTableError as exc:
        log.error("%s", exc)
        return EXIT_ARAM_NEUTRAL
    except DegenerateLolmathBlockError as exc:
        log.error("%s", exc)
        return EXIT_LOLMATH_DEGENERATE

    # RM-807 (d): the two bulk fetches are gated before the per-champion
    # overlay fetch and any write.
    arena_augments = fetch_arena_augments()
    meraki_items = fetch_meraki_items()
    try:
        upstream_check = check_upstream_counts(arena_augments, meraki_items,
                                               args.allow_short_upstream)
    except ShortUpstreamError as exc:
        log.error("%s", exc)
        return EXIT_UPSTREAM_SHORT
    perlevel_overlay = fetch_meraki_perlevel_overlay(set(dd.champions.keys()))

    champions_payload = build_champions_payload(lolmath, dd, perlevel_overlay)
    items_payload = build_items_payload(dd)
    scenarios_payload = build_scenarios_payload(lolmath, dd)
    manifest = build_manifest(
        lolmath, dd, patch_dir, perlevel_overlay, arena_augments, meraki_items,
        aram_neutral_override=aram_check if "override_reason" in aram_check else None,
        lolmath_degenerate_override=block_check if "override_reason" in block_check else None,
        upstream_short_override=(upstream_check if "override_reason" in upstream_check
                                 else None),
    )

    _atomic_write_json(patch_dir / "champions.json", champions_payload)
    _atomic_write_json(patch_dir / "items.json", items_payload)
    _atomic_write_json(patch_dir / "scenarios.json", scenarios_payload)
    _atomic_write_json(patch_dir / "arena_augments.json", stamp_patch(arena_augments, patch))
    _atomic_write_json(patch_dir / "items_meraki.json", stamp_patch(meraki_items, patch))
    _atomic_write_json(patch_dir / "manifest.json", manifest)
    _atomic_write_text(DATA_ROOT / "current.txt", patch)

    log.info("wrote %s/{champions,items,scenarios,arena_augments,items_meraki,manifest}.json", patch_dir)
    log.info("current.txt -> %s", patch)
    return 0


def _extract_lolmath(
        args: argparse.Namespace) -> tuple[LolmathExtract, dict[str, Any], dict[str, Any]]:
    """Fetch and parse every lolmath dataset, then run the RM-805 and RM-807 gates.

    Shared by the full extract and ``--lolmath-only``. Returns the extract and
    both gate measurements; raises ``NeutralAramTableError`` or
    ``DegenerateLolmathBlockError`` (nothing written) on a failing block
    without its override.
    """
    scen_url, data_url = discover_chunks(args.chunk_url, args.data_chunk_url)
    fetch_chunk(scen_url)
    fetch_chunk(data_url)
    lolmath = extract_from_bodies(_CHUNK_BODIES, preferred=scen_url)
    check_lolmath_coverage(lolmath)
    data_extract = extract_data_blocks(_CHUNK_BODIES, preferred=data_url)
    lolmath.aram_modifiers = data_extract["aram_modifiers"]
    lolmath.damage_distribution = data_extract["damage_distribution"]
    lolmath.skill_orders = data_extract["skill_orders"]
    lolmath.data_chunk_url = data_extract["data_chunk_url"]
    lolmath.data_chunk_bytes = data_extract["data_chunk_bytes"]
    lolmath.data_block_sources = data_extract["block_sources"]
    aram_check = check_aram_neutrality(
        lolmath.aram_modifiers, override_reason=args.allow_neutral_aram,
    )
    block_check = check_lolmath_blocks(
        lolmath.damage_distribution, lolmath.skill_orders,
        override_reason=args.allow_degenerate_lolmath,
    )
    return lolmath, aram_check, block_check


EXIT_LOLMATH_ONLY_NO_SNAPSHOT = 4


def _main_lolmath_only(args: argparse.Namespace) -> int:
    """``--lolmath-only``: renew the lolmath parts of an existing snapshot.

    No DDragon / Meraki / CDragon fetch: champion ids and the version come
    from the snapshot's own ``champions.json``. Writes ``champions.json``
    (each champion's ``lolmath`` sub-object only), ``scenarios.json`` and
    ``manifest.json``; never ``current.txt`` or any other file.
    """
    patch = args.patch
    if not patch:
        current = DATA_ROOT / "current.txt"
        patch = current.read_text(encoding="utf-8").strip() if current.is_file() else ""
    if not patch:
        log.error("--lolmath-only: no --patch and no current.txt - nothing to refresh")
        return EXIT_LOLMATH_ONLY_NO_SNAPSHOT
    patch_dir = DATA_ROOT / patch
    manifest_path = patch_dir / "manifest.json"
    champions_path = patch_dir / "champions.json"
    missing = [p.name for p in (manifest_path, champions_path) if not p.is_file()]
    if missing:
        log.error("--lolmath-only: patch %s has no %s at %s - run a full extract first",
                  patch, " / ".join(missing), patch_dir)
        return EXIT_LOLMATH_ONLY_NO_SNAPSHOT
    champions_doc = json.loads(champions_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    champ_data = champions_doc["data"]

    try:
        lolmath, aram_check, block_check = _extract_lolmath(args)
    except NeutralAramTableError as exc:
        log.error("%s", exc)
        return EXIT_ARAM_NEUTRAL
    except DegenerateLolmathBlockError as exc:
        log.error("%s", exc)
        return EXIT_LOLMATH_DEGENERATE

    # An adjudicated carry survives only an explicit override: then the carried
    # rows stay too, so the manifest never claims a carry champions.json lacks.
    keep_carry = bool(manifest.get("aram_modifiers_carry")) and "override_reason" in aram_check
    for champ_id, rec in champ_data.items():
        block = _lolmath_block(lolmath, champ_id)
        if keep_carry:
            block["aram_modifiers"] = (rec.get("lolmath") or {}).get("aram_modifiers")
        rec["lolmath"] = block
    absent = sorted(set(lolmath.cooldowns) - set(champ_data))
    if absent:
        log.warning("lolmath has %d champions absent from the %s snapshot: %s",
                    len(absent), patch, absent)

    dd = DDragonSnapshot(version=champions_doc["version"], champions=champ_data, items={})
    scenarios_payload = build_scenarios_payload(lolmath, dd)
    new_manifest = refresh_manifest_lolmath(manifest, lolmath, aram_check,
                                            keep_carry=keep_carry,
                                            block_check=block_check)

    _atomic_write_json(champions_path, champions_doc)
    _atomic_write_json(patch_dir / "scenarios.json", scenarios_payload)
    _atomic_write_json(manifest_path, new_manifest)
    log.info("lolmath-only: wrote %s/{champions,scenarios,manifest}.json "
             "(carry %s)", patch_dir,
             "kept" if keep_carry else ("dropped" if manifest.get("aram_modifiers_carry") else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
