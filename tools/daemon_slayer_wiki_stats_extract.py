# arch: lolmath-wiki + cdragon stat sidecar extractor (ChampionData + bin -> wiki_stats.json) | section=tools | frozen=no
"""LoL wiki ChampionData + CommunityDragon scalars -> per-champion sidecar JSON.

Item 221 (2026-05-30): a thin OPTIONAL sidecar extractor for the per-champion
scalar fields the Meraki bulk does NOT carry and that the DS combo/spike sims
want. Closes the GO-conditional verdict in
``docs/LOLMATH_WIKI_SOURCE_2026-05-30.md`` (item 217 feasibility).

CDragon backfill (2026-05-30 follow-up): the wiki ``action=raw`` table omits
the stat scalars for MOST champs (its getter fills a runtime default but the raw
dump stores nothing; at 16.11.1 only 49/171 carry attack_cast_time, 81/171
missile_speed). A second SOURCE - CommunityDragon character bins - carries
attack_cast_time for EVERY champ, so a backfill stage fills the wiki nulls and
lifts attack_cast_time coverage to 171/171. The WIKI value WINS where present
(operator chose the wiki as the named source); CDragon fills ONLY the nulls.
Each scalar carries a ``*_src`` provenance field ("wiki" | "cdragon" | null).

What it pulls:
  * ``attack_cast_time`` - the AA windup (seconds). This is the field combo.py's
    ``_DEFAULT_AA_WINDUP_S = 0.25`` flat fallback replaces per-champ.
  * ``attack_total_time`` - the full AA cycle (seconds) at base AS. Bonus field
    from the same parse; windup ratio = cast / total. No consumer yet.
  * ``missile_speed`` - ranged AA missile speed (units/s). Melee champs have
    none (null).
  * ``mode_modifiers`` - per-mode balance changes parsed from the SAME raw
    module (zero extra network cost; the mode sub-blocks are nested inside each
    champ's ``["stats"]`` block). {mode_key: {inner_key: float}} for every mode
    sub-block present, ``{}`` when a champ has none. aram/urf/nb/ofa/usb store
    MULTIPLIERS (dmg_dealt 1.05 = +5%); ar (Arena/CHERRY) + swift (Swiftplay)
    store ADDEND stat-overrides (hp_lvl 17 = +17 hp/level). Inner keys stored
    verbatim (no multiplier-vs-addend coercion). Wiki-sourced only (no cdragon
    backfill, no default fill, no <field>_src). No DS consumer yet.

HOW (item 221 deep-dive, 2026-05-30 - the working method, verified live):
  * The ``leagueoflegends.wiki.gg`` host edge-blocks this development host's
    egress (HTTP 401 "Not authorized - wiki.gg", host-wide, not api.php-specific;
    persists hours after a probe burst). The block is HOSTNAME-SPECIFIC: the
    Riot vanity alias ``wiki.leagueoflegends.com`` (SAME wiki.gg backend) is
    reachable from the same host (HTTP 200). A hosted-agent fetch is ALSO
    blocked on the .wiki.gg host, so the alias is the path that works.
  * WIKI PRIMARY = ONE request: ``action=raw`` on ``Module:ChampionData/data``
    over the alias (~380 KB Lua ``return {...}`` table). A brace-scan parser
    keyed by each block's ``apiname`` (== the Riot/DDragon champion id; verified
    171/171 match the abilities snapshot) pulls the 3 scalars. This avoids the
    chatty per-field ``expandtemplates`` path. The raw table stores explicit
    values for ONLY ~49 champs at 16.11.1; the rest are filled by the getter
    fallback (a few) + CDragon (the bulk).
  * WIKI FALLBACK = per-champ ``action=expandtemplates`` getter over the SAME
    alias, used for a champ the raw parse missed an ``attack_cast_time`` for.
  * CDRAGON BACKFILL fills every wiki null (see below).

NOT a live dependency: this is an OFFLINE patch-refresh tool, the SAME contract
as ``daemon_slayer_abilities_extract.py``. The DS engine reads the committed
sidecar JSON, never the network. Absent sidecar -> current behavior (the flat
windup fallback). It is INERT until a consumer (combo.py AA-windup wire) opts in.

Run from any host that reaches the alias + CDragon:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_stats_extract.py            # current.txt patch
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_stats_extract.py --patch 16.11.1
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_stats_extract.py --limit 5  # smoke a subset
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_stats_extract.py --dry-run  # no write
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_stats_extract.py --source wiki     # wiki only (legacy)
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_stats_extract.py --source cdragon  # cdragon only
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_stats_extract.py --source both     # default
Then inspect ``_with_cast_time`` / ``_errors`` before trusting it: a run that
edge-blocks BOTH sources records 0 cast times (the fail-soft path), so a sidecar
with ``_with_cast_time == 0`` means the host could not reach either - do NOT
commit. With ``--source both`` a normal run reaches 171/171 cast times.

CDragon source (the backfill, 2026-05-30):
  * URL ``https://raw.communitydragon.org/latest/game/data/characters/<slug>/<slug>.bin.json``
    (verified live; the bare ``<slug>.json`` 404s). <slug> = lowercased DDragon
    id; verified 171/171 resolve at 16.11.1 (no override map needed -
    monkeyking/kaisa/belveth/nunu/fiddlesticks all work bare). An override hook
    (``_CDRAGON_SLUG_OVERRIDES``) is kept for future patch drift.
  * Field paths (verified live against aatrox.bin.json, root key
    ``/Characters/<Name>``): attack_cast_time =
    ``CharacterRecords/Root/basicAttack/mAttackCastTime``; attack_total_time =
    ``.../basicAttack/mAttackTotalTime``; missile_speed =
    ``Spells/<Name>BasicAttack/mSpell/missileSpeed``. A recursive walk captures
    cast/total only when the ANCESTOR path contains ``basicAttack`` (the
    CharacterRecords block; excludes ``extraAttacks[..]/mAttackCastTime``) and
    missileSpeed only when the parent path ENDS WITH ``BasicAttack/mSpell`` (the
    primary basic-attack spell; excludes R/E/passive/crit/extra basic-attack
    spells which also carry a missileSpeed).
  * Melee guard: CDragon stores a basic-attack ``missileSpeed`` even for melee
    swings (e.g. Aatrox 347.8); the bin has NO ``attackRange`` field. The wiki
    marks melee missile_speed null, so the backfill keeps a CDragon
    missile_speed ONLY when the champ's DDragon ``stats.attackrange`` (from the
    meta_build mirror) >= 350 (ranged); melee stays null. attack_cast_time +
    attack_total_time are kept for ALL champs.

Design (don't re-litigate):
  * stdlib ``urllib`` only - no new pip dep (the DS data-pipeline rule).
  * User-Agent header set (the wiki blocks UA-less).
  * wiki action=raw is ONE request; CDragon is one request per champ (171 small
    bins, with a backoff retry over the occasionally-flapping CDN ``latest``
    symlink); the wiki per-champ getter fallback fires only for raw omitters.
    The ``--sleep`` gap applies to per-champ network calls (CDragon + getter).
  * WIKI WINS, CDRAGON FILLS NULLS: the merge never overwrites a non-null wiki
    scalar; CDragon only supplies a value the wiki left null. Provenance is
    recorded per scalar in ``<field>_src`` ("wiki" | "cdragon" | null).
  * fail-soft per champ: a bad/empty/blocked response records null, never
    aborts the whole run; a failed wiki raw fetch degrades to per-champ getter;
    a failed CDragon fetch records an error + leaves that champ's nulls.
  * Atomic write: tmp.write_text + os.replace (overlays poll mid-write).
  * ASCII-only output (ensure_ascii=True) - the no-em-dash repo rule.
  * champion-id source = the committed abilities snapshot's ``data`` dict
    (171 champs at 16.11.1; keyed by DDragon id). The wiki block's ``apiname``
    field == that DDragon id, so the parse keys by apiname directly. Display-name
    + attackrange map come from the meta_build DDragon ``champion.json`` mirror;
    the CDragon slug is ``id.lower()``.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "daemon_slayer"
META_DDRAGON_DIR = PROJECT_ROOT / "data" / "meta_build" / "ddragon"

# The .wiki.gg host edge-blocks this host (HTTP 401 host-wide). The Riot vanity
# alias is the SAME wiki.gg backend and is reachable. See module docstring.
WIKI_HOST = "https://wiki.leagueoflegends.com"
WIKI_API = WIKI_HOST + "/api.php"
WIKI_RAW_MODULE = WIKI_HOST + "/en-us/Module:ChampionData/data?action=raw"
HEADER_UA = "Amberstone-DaemonSlayer/1.0 (offline patch-refresh extractor; local coaching tool)"
_HTTP_TIMEOUT = 40

# CommunityDragon character-bin source (the backfill). Filename is
# <slug>.bin.json (verified live; the bare <slug>.json 404s). See the module
# docstring for the field paths walked out of it.
CDRAGON_CHAR_URL = "https://raw.communitydragon.org/latest/game/data/characters/{slug}/{slug}.bin.json"
# attackrange (DDragon meta_build stat) >= this => treat the champ as ranged and
# keep its CDragon missile_speed; below it the champ is melee and missile_speed
# stays null (the wiki convention). Verified live: Aatrox 175 / Garen 175 melee;
# Thresh 450 / Ahri 550 / Caitlyn 650 ranged. 350 is a safe split (no champ
# basic-attacks between 175 and 450).
_RANGED_ATTACK_RANGE_MIN = 350.0
# CDragon ``latest`` 404s in short bursts while its CDN rebuilds the symlink; a
# couple of backoff retries rides over a typical window. Module-level so tests
# can shrink them (the default sleeps would slow a fail-soft test).
_CDRAGON_RETRIES = 3
_CDRAGON_RETRY_BACKOFF_S = 3.0
# DDragon id -> CDragon slug override, for future patch drift. Empty: every
# 16.11.1 id resolves with the bare ``id.lower()`` slug (verified 171/171).
_CDRAGON_SLUG_OVERRIDES: dict[str, str] = {}

_FIELD_ATTACK_CAST_TIME = "attack_cast_time"
_FIELD_ATTACK_TOTAL_TIME = "attack_total_time"
_FIELD_MISSILE_SPEED = "missile_speed"
# Wiki-raw source fields for the offset-derived windup tier (Win 1). NOT output
# scalars - they are parsed from the same ChampionData block (zero extra network)
# and converted to an attack_cast_time when a champ has no explicit cast time.
# attack_delay_offset is NEGATIVE for most champs (needs the signed parse).
_FIELD_ATTACK_DELAY_OFFSET = "attack_delay_offset"
_FIELD_AS_BASE = "as_base"
# Per-champion per-mode balance multipliers/addends parsed from the SAME wiki
# raw module (zero extra network cost). Wiki-only - no cdragon/default fill, so
# no <field>_src provenance; it is documented as wiki-sourced in the meta _note.
_FIELD_MODE_MODIFIERS = "mode_modifiers"
_SRC_SUFFIX = "_src"

# Default basic-attack windup (seconds) for champs neither source measures.
# VERIFIED live: a CDragon character bin stores ``basicAttack/mAttackCastTime``
# ONLY when the champ OVERRIDES the engine default; the ~110 champs without it
# (Garen / Caitlyn / Leona / Ahri / ...) carry no explicit value in CDragon OR
# the wiki. So attack_cast_time gets a THIRD fill tier: any champ with no
# measured (wiki/cdragon) value is filled with this default (provenance
# "default") so the field reaches an honest 171/171 - measured where measured,
# default elsewhere, all auditable via attack_cast_time_src.
#
# The value is PINNED to the consumer's own fallback (combo.py
# ``_DEFAULT_AA_WINDUP_S`` = 0.25) ON PURPOSE: combo.py uses the sidecar value
# when present ELSE 0.25, with a "byte-identical to no-sidecar" contract. A
# "default" entry that restates 0.25 keeps every default-filled champ
# byte-identical to the no-sidecar path (zero consumer regression) while still
# giving the field full coverage; only the MEASURED entries (wiki/cdragon)
# change combo timing, which is the whole point of the sidecar. Keeping the two
# constants equal is a deliberate invariant (a test pins it). (attack_total_time
# + missile_speed get NO default; they stay null when unmeasured.) Disable the
# tier with --no-default-cast.
_ENGINE_DEFAULT_CAST_TIME = 0.25

# Windup base for the offset-derived tier (Win 1). The wiki publishes a per-champ
# attack_delay_offset; real basic-attack windup FRACTION = 0.300 + offset
# (validated 4/4 EXACT vs the wiki's own published Windup% for Caitlyn/Ashe/
# Vayne/Jinx). combo.py is a FIXED-windup model (absolute seconds, no AS curve),
# so it is stored as SECONDS at base AS: (0.300 + offset) / as_base. Recovers a
# real per-champ windup for the ~109 champs that would otherwise take the flat
# 0.25 default (only Alistar has neither an explicit cast time nor an offset).
_WINDUP_OFFSET_BASE = 0.300

# DDragon id -> wiki display-name overrides for champs whose DDragon
# champion.json ``.name`` does NOT match the wiki page title exactly. Used only
# by the getter-fallback path + the stored wiki_name reference. The raw path
# keys by ``apiname`` so it needs no override. Empty until a run surfaces one.
_WIKI_NAME_OVERRIDES: dict[str, str] = {}

# Cache for the parsed raw module table (apiname -> scalar dict). Populated by
# _load_wiki_table(); kept module-level so a single extract() run fetches once.
_WIKI_TABLE_CACHE: Optional[dict[str, dict[str, Any]]] = None


def _fetch(url: str, timeout: int = _HTTP_TIMEOUT) -> str:
    """GET text with a UA header (the wiki blocks UA-less)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": HEADER_UA, "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _fetch_with_retry(url: str, retries: int = _CDRAGON_RETRIES,
                      backoff_s: float = _CDRAGON_RETRY_BACKOFF_S) -> str:
    """``_fetch`` with a few backoff retries (for the flapping CDragon CDN)."""
    last: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            return _fetch(url)
        except Exception as exc:  # noqa: BLE001 - retry transient CDN 404/5xx
            last = exc
            if attempt + 1 < retries and backoff_s > 0:
                time.sleep(backoff_s * (attempt + 1))
    raise last if last is not None else RuntimeError("fetch failed")


def _expand(champ_display: str, field: str) -> str:
    """Resolve one ChampionData scalar via action=expandtemplates (getter).

    Returns the bare wikitext scalar string ("" on a miss). Raises on a
    transport / HTTP error (the caller fail-softs per champ). This is the
    FALLBACK path; the raw module is the primary.
    """
    invoke = "{{#invoke:ChampionData|get|" + champ_display + "|" + field + "}}"
    params = {
        "action": "expandtemplates",
        "format": "json",
        "prop": "wikitext",
        "text": invoke,
    }
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    raw = _fetch(url)
    return (json.loads(raw).get("expandtemplates", {}) or {}).get("wikitext", "")


def _fetch_raw_module(timeout: int = _HTTP_TIMEOUT) -> str:
    """GET the Module:ChampionData/data raw wikitext (the Lua return table)."""
    return _fetch(WIKI_RAW_MODULE, timeout=timeout)


def _resolve_patch(patch: Optional[str]) -> str:
    if patch:
        return patch
    cur = (DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    if not cur:
        raise SystemExit("current.txt empty; pass --patch")
    return cur


def _load_display_names(patch: str) -> dict[str, str]:
    """DDragon id -> display name from the meta_build DDragon mirror.

    Prefers the same-patch champion.json; falls back to the newest
    available mirror if the exact patch dir is absent.
    """
    data = _load_meta_champ_data(patch)
    return {cid: str(rec.get("name") or cid) for cid, rec in data.items()}


def _load_attack_ranges(patch: str) -> dict[str, float]:
    """DDragon id -> base attackrange from the meta_build DDragon mirror.

    Used for the CDragon missile_speed melee guard (the CDragon bin carries no
    attackRange). Missing/degenerate -> champ omitted (treated as melee -> no
    CDragon missile_speed fill).
    """
    data = _load_meta_champ_data(patch)
    out: dict[str, float] = {}
    for cid, rec in data.items():
        ar = (rec.get("stats") or {}).get("attackrange")
        if isinstance(ar, (int, float)) and not isinstance(ar, bool):
            out[cid] = float(ar)
    return out


def _load_meta_champ_data(patch: str) -> dict[str, Any]:
    """The meta_build DDragon champion.json ``data`` dict (exact patch or newest)."""
    exact = META_DDRAGON_DIR / patch / "champion.json"
    champ_json = exact
    if not champ_json.exists():
        candidates = sorted(META_DDRAGON_DIR.glob("*/champion.json"), key=lambda p: p.parts)
        if not candidates:
            raise SystemExit(f"no champion.json under {META_DDRAGON_DIR}")
        champ_json = candidates[-1]
    return json.loads(champ_json.read_text(encoding="utf-8")).get("data", {})


def _load_roster_champion_ids(patch: str) -> list[str]:
    """DDragon ids from the committed ROSTER snapshot (``champions.json``).

    A-26 / RM-95b. The abilities snapshot is a Meraki derivative frozen upstream
    since 2025-08-01 and is 2 champions short of the live roster (Locke,
    Zaahen). The roster file keys champions under ``data`` the same way.
    OPT-IN ONLY - reached via ``_load_champion_ids(..., full_roster=True)``.
    """
    roster = DATA_DIR / patch / "champions.json"
    if not roster.exists():
        raise SystemExit(f"roster file missing: {roster} (run the champions extractor first)")
    raw = json.loads(roster.read_text(encoding="utf-8"))
    champs = raw.get("data") or {}
    if not champs:
        raise SystemExit(f"roster file {roster} has no 'data' champion container")
    return sorted(champs.keys())


def _load_champion_ids(patch: str) -> list[str]:
    """DDragon ids to extract, from the committed abilities snapshot.

    The abilities file keys champions under the top-level ``data`` dict
    (NOT ``champions``; the top level also holds version/fetched_at/source/
    engine_phase/count/coverage).
    """
    abil = DATA_DIR / patch / "champion_abilities.json"
    if not abil.exists():
        raise SystemExit(f"abilities file missing: {abil} (run the abilities extractor first)")
    raw = json.loads(abil.read_text(encoding="utf-8"))
    champs = raw.get("data") or raw.get("champions") or {}
    if not champs:
        raise SystemExit(f"abilities file {abil} has no 'data' champion container")
    return sorted(champs.keys())


def _resolve_champion_ids(patch: str, full_roster: bool) -> list[str]:
    """Pick the champion keyspace: the abilities snapshot (default) or the roster.

    ``full_roster=False`` is the pre-A-26 behavior and MUST stay byte-identical:
    it delegates to ``_load_champion_ids`` unchanged.
    """
    if full_roster:
        return _load_roster_champion_ids(patch)
    return _load_champion_ids(patch)


def _wiki_name(ddragon_id: str, display_names: dict[str, str]) -> str:
    if ddragon_id in _WIKI_NAME_OVERRIDES:
        return _WIKI_NAME_OVERRIDES[ddragon_id]
    return display_names.get(ddragon_id, ddragon_id)


def _parse_scalar(s: str) -> Optional[float]:
    """A wiki scalar string -> float, or None when blank / non-numeric.

    wiki ``ChampionData|get`` sometimes returns trailing ``||`` separators on a
    compound get (feasibility doc 1g: "0.30000001192093||"); strip on the first
    ``|`` and take the leading token.

    NON-FINITE GUARD: ``float()`` happily parses "inf" / "nan" / "Infinity".
    The raw-module path gates those out with a ``[0-9.]+`` regex, but the
    getter-fallback path (``action=expandtemplates``) feeds arbitrary wikitext
    here unmasked. A non-finite value would be written into the sidecar and
    ``json.dumps`` then emits a BARE ``NaN`` / ``Infinity`` token (invalid JSON
    for strict parsers + JS ``JSON.parse``, and silently re-accepted by our own
    ``json.loads`` on the next run). Treat a non-finite token as non-numeric so
    the value falls through to the next fill tier.
    """
    s = (s or "").strip()
    if not s:
        return None
    s = s.split("|", 1)[0].strip()
    if not s:
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


_BLOCK_OPEN_RE = re.compile(r'\["([^"]+)"\]\s*=\s*\{')


def _scan_block_end(text: str, open_brace_idx: int) -> int:
    """Index just past the ``}`` matching the ``{`` at ``open_brace_idx``."""
    depth = 0
    n = len(text)
    k = open_brace_idx
    while k < n:
        c = text[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return k + 1
        k += 1
    return n


def _scalar_in_block(blk: str, field: str) -> Optional[float]:
    """Pull a numeric ``["field"] = N`` scalar from a champ block; None if absent."""
    m = re.search(r'\["' + re.escape(field) + r'"\]\s*=\s*([0-9.]+)', blk)
    return _parse_scalar(m.group(1)) if m else None


def _signed_scalar_in_block(blk: str, field: str) -> Optional[float]:
    """Like ``_scalar_in_block`` but captures a leading minus.

    ``attack_delay_offset`` is NEGATIVE for most champs (Akali -0.161, Ahri
    -0.1); the unsigned ``_scalar_in_block`` regex would silently drop the sign
    (no match -> None), so the offset tier needs this signed variant.
    """
    m = re.search(r'\["' + re.escape(field) + r'"\]\s*=\s*(-?[0-9.]+)', blk)
    return _parse_scalar(m.group(1)) if m else None


# Per-champion balance-modifier mode keys nested INSIDE the ``["stats"]`` block
# of each champ. aram/urf/nb/ofa/usb store MULTIPLIERS (dmg_dealt 1.05 = +5%);
# ar (Arena/CHERRY) + swift (Swiftplay) store ADDEND stat-overrides (hp_lvl 17 =
# +17 hp per level). Verified live (16.11.1): roster mode counts aram 161 / urf
# 102 / ofa 82 / usb 45 / ar 45 / nb 32 / swift 13. The set is closed at the
# observed roster; an unknown future mode key is simply not captured (no crash).
_MODE_KEYS = ("aram", "urf", "nb", "ofa", "usb", "ar", "swift")
# A signed Lua number (int or float, optional leading -). The mode sub-blocks
# carry only numeric scalars (multipliers + per-level addends); negatives appear
# in the addend modes (e.g. swift arm_lvl = -0.5).
_MODE_SCALAR_RE = re.compile(r'\["([a-z0-9_]+)"\]\s*=\s*(-?[0-9.]+)')
_MODE_OPEN_RE = re.compile(r'\["(' + "|".join(_MODE_KEYS) + r')"\]\s*=\s*\{')


def _parse_mode_block(inner: str) -> dict[str, float]:
    """Parse the scalar inner keys of ONE mode sub-block body (inside its braces).

    ``inner`` is the text between (not including) the ``{`` and matching ``}`` of
    a ``["<mode>"] = { ... }`` block. Captures every ``["<key>"] = <number>``
    scalar verbatim (signed; the addend modes carry negative per-level deltas);
    a missing trailing comma before ``}`` is fine (the scalar regex does not need
    it). Non-scalar entries (none observed in mode blocks) are ignored. The keys
    are stored as-is (dmg_dealt / dmg_taken / ability_haste / ms_mod / hp_lvl /
    arm_lvl / ...) - no coercion of multiplier-vs-addend semantics.
    """
    out: dict[str, float] = {}
    for m in _MODE_SCALAR_RE.finditer(inner):
        val = _parse_scalar(m.group(2))
        if val is not None:
            out[m.group(1)] = val
    return out


def _parse_mode_modifiers_in_stats(stats_blk: str) -> dict[str, dict[str, float]]:
    """Find each ``["<mode>"] = {...}`` sub-block inside a champ's stats block.

    ``stats_blk`` is the full ``["stats"] = { ... }`` text (braces included). For
    every recognized mode key, brace-scans to the matching ``}`` (reusing
    ``_scan_block_end`` so nested braces are handled) and parses the scalar inner
    keys. Returns {mode_key: {inner_key: float}} for each mode block present;
    empty dict when the champ has no mode blocks. A block with no parseable
    scalars is omitted (keeps the output honest - mode_modifiers reflects only
    real data).
    """
    out: dict[str, dict[str, float]] = {}
    for m in _MODE_OPEN_RE.finditer(stats_blk):
        mode = m.group(1)
        open_idx = stats_blk.find("{", m.start())
        if open_idx < 0:
            continue
        end = _scan_block_end(stats_blk, open_idx)
        inner = stats_blk[open_idx + 1:end - 1]  # body between the braces
        scalars = _parse_mode_block(inner)
        if scalars:
            out[mode] = scalars
    return out


def _stats_block_of(blk: str) -> Optional[str]:
    """Return the ``["stats"] = { ... }`` sub-block text of a champ block, or None.

    Brace-scans to the matching ``}`` so the returned slice contains the full
    nested stats subtable (including its mode sub-blocks).
    """
    sm = re.search(r'\["stats"\]\s*=\s*\{', blk)
    if not sm:
        return None
    open_idx = blk.find("{", sm.start())
    if open_idx < 0:
        return None
    end = _scan_block_end(blk, open_idx)
    return blk[open_idx:end]


def _parse_lua_table(raw: str) -> dict[str, dict[str, Any]]:
    """Parse Module:ChampionData/data action=raw text into {apiname: {...}}.

    Brace-scans each top-level champion block (identified by an ``id`` +
    ``apiname`` key in the block head, which excludes nested subtables like
    ``stats``/``aram``) and pulls the scalar stat fields. Keyed by ``apiname``
    (== the Riot/DDragon champion id).
    """
    out: dict[str, dict[str, Any]] = {}
    for m in _BLOCK_OPEN_RE.finditer(raw):
        open_idx = raw.find("{", m.start())
        if open_idx < 0:
            continue
        end = _scan_block_end(raw, open_idx)
        blk = raw[m.start():end]
        head = blk[:400]
        if '["id"]' not in head or '["apiname"]' not in head:
            continue  # nested subtable, not a champion block
        am = re.search(r'\["apiname"\]\s*=\s*"([^"]+)"', blk)
        if not am:
            continue
        # Mode-modifier sub-blocks live nested inside ["stats"]; scope the scan to
        # that subtable so a (hypothetical) top-level mode key cannot leak in.
        stats_blk = _stats_block_of(blk)
        mode_modifiers = (
            _parse_mode_modifiers_in_stats(stats_blk) if stats_blk is not None else {}
        )
        out[am.group(1)] = {
            "wiki_name": m.group(1),
            _FIELD_ATTACK_CAST_TIME: _scalar_in_block(blk, _FIELD_ATTACK_CAST_TIME),
            _FIELD_ATTACK_TOTAL_TIME: _scalar_in_block(blk, _FIELD_ATTACK_TOTAL_TIME),
            _FIELD_MISSILE_SPEED: _scalar_in_block(blk, _FIELD_MISSILE_SPEED),
            # offset tier source (Win 1): signed offset + base AS, same block.
            _FIELD_ATTACK_DELAY_OFFSET: _signed_scalar_in_block(
                blk, _FIELD_ATTACK_DELAY_OFFSET),
            _FIELD_AS_BASE: _signed_scalar_in_block(blk, _FIELD_AS_BASE),
            _FIELD_MODE_MODIFIERS: mode_modifiers,
        }
    return out


def _load_wiki_table() -> dict[str, dict[str, Any]]:
    """Fetch + parse the raw ChampionData module once; cache for the run."""
    global _WIKI_TABLE_CACHE
    if _WIKI_TABLE_CACHE is None:
        _WIKI_TABLE_CACHE = _parse_lua_table(_fetch_raw_module())
    return _WIKI_TABLE_CACHE


def _fetch_field(champ_display: str, field: str, stats_fallback: bool) -> Optional[float]:
    """Getter fallback: resolve a scalar; optionally retry with a ``stats.`` sub-path.

    The feasibility doc (1g) noted the compound ChampionData get needed the
    ``stats.`` prefix for some nested fields. Try bare first, then the stats.
    form when the bare returns empty. Used only when the raw parse missed a
    field for a champ.
    """
    val = _parse_scalar(_expand(champ_display, field))
    if val is None and stats_fallback:
        val = _parse_scalar(_expand(champ_display, "stats." + field))
    return val


# --------------------------------------------------------------------------- CDragon backfill
def _cdragon_slug(ddragon_id: str) -> str:
    """DDragon id -> CDragon character slug (lowercased id, override-able)."""
    if ddragon_id in _CDRAGON_SLUG_OVERRIDES:
        return _CDRAGON_SLUG_OVERRIDES[ddragon_id]
    return ddragon_id.lower()


def _parse_cdragon_bin(doc: Any) -> dict[str, Optional[float]]:
    """Walk a CDragon character bin, pulling the basic-attack stat scalars.

    Captures ``mAttackCastTime`` / ``mAttackTotalTime`` only when the ancestor
    path contains ``basicAttack`` (the CharacterRecords basic-attack block; this
    excludes ``extraAttacks[..]/mAttackCastTime``) and ``missileSpeed`` only when
    the parent path ends with ``BasicAttack/mSpell`` (the primary basic-attack
    spell; excludes R/E/passive/crit/extra basic-attack spells which also carry a
    missileSpeed). Returns raw floats (the melee guard + rounding happen in the
    caller). Missing -> None. First match wins for each field.
    """
    found: dict[str, Optional[float]] = {
        _FIELD_ATTACK_CAST_TIME: None,
        _FIELD_ATTACK_TOTAL_TIME: None,
        _FIELD_MISSILE_SPEED: None,
    }

    def _num(v: Any) -> Optional[float]:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        return None

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                np = path + "/" + str(k)
                if k == "mAttackCastTime" and "basicAttack" in path:
                    n = _num(v)
                    if n is not None and found[_FIELD_ATTACK_CAST_TIME] is None:
                        found[_FIELD_ATTACK_CAST_TIME] = n
                elif k == "mAttackTotalTime" and "basicAttack" in path:
                    n = _num(v)
                    if n is not None and found[_FIELD_ATTACK_TOTAL_TIME] is None:
                        found[_FIELD_ATTACK_TOTAL_TIME] = n
                elif k == "missileSpeed" and path.endswith("BasicAttack/mSpell"):
                    n = _num(v)
                    if n is not None and found[_FIELD_MISSILE_SPEED] is None:
                        found[_FIELD_MISSILE_SPEED] = n
                walk(v, np)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + "[" + str(i) + "]")

    walk(doc, "")
    return found


def _round6(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(float(v), 6)


def _cdragon_scalars(ddragon_id: str, attack_range: Optional[float]) -> dict[str, Optional[float]]:
    """Fetch + parse one champ's CDragon bin -> {cast, total, missile} (rounded).

    Applies the melee guard: missile_speed is kept ONLY when the DDragon
    ``attack_range`` is ranged (>= ``_RANGED_ATTACK_RANGE_MIN``); melee (or
    unknown range) -> None. Raises on a transport / HTTP error (the caller
    fail-softs per champ).
    """
    url = CDRAGON_CHAR_URL.format(slug=_cdragon_slug(ddragon_id))
    raw = _fetch_with_retry(url)
    parsed = _parse_cdragon_bin(json.loads(raw))
    ms = parsed.get(_FIELD_MISSILE_SPEED)
    if ms is not None and (attack_range is None or attack_range < _RANGED_ATTACK_RANGE_MIN):
        ms = None  # melee: drop the basic-attack swing missileSpeed (wiki = null)
    return {
        _FIELD_ATTACK_CAST_TIME: _round6(parsed.get(_FIELD_ATTACK_CAST_TIME)),
        _FIELD_ATTACK_TOTAL_TIME: _round6(parsed.get(_FIELD_ATTACK_TOTAL_TIME)),
        _FIELD_MISSILE_SPEED: _round6(ms),
    }


def _merge_fill(rec: dict[str, Any], field: str, wiki_val: Optional[float],
                cd_val: Optional[float], default_val: Optional[float] = None,
                offset_val: Optional[float] = None) -> None:
    """Set ``rec[field]`` + ``rec[field+'_src']`` per the source-precedence rule.

    Precedence: wiki (the operator-named source) wins where non-null; else
    CDragon fills; else the offset-derived windup ``offset_val`` (Win 1: only
    attack_cast_time passes one - the wiki attack_delay_offset converted to
    seconds); else the engine ``default_val`` fills (only attack_cast_time passes
    one - see ``_ENGINE_DEFAULT_CAST_TIME``); else null. Provenance is "wiki" /
    "cdragon" / "wiki_offset" / "default" / null respectively.
    """
    if wiki_val is not None:
        rec[field] = wiki_val
        rec[field + _SRC_SUFFIX] = "wiki"
    elif cd_val is not None:
        rec[field] = cd_val
        rec[field + _SRC_SUFFIX] = "cdragon"
    elif offset_val is not None:
        rec[field] = offset_val
        rec[field + _SRC_SUFFIX] = "wiki_offset"
    elif default_val is not None:
        rec[field] = default_val
        rec[field + _SRC_SUFFIX] = "default"
    else:
        rec[field] = None
        rec[field + _SRC_SUFFIX] = None


def _atomic_write_json(path: Path, payload: Any) -> None:
    """tmp.write_text + os.replace - the repo atomic-write rule."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=True, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def extract(patch: str, sleep_s: float, limit: Optional[int], verbose: bool,
            source: str = "both", default_cast: bool = True,
            *, full_roster: bool = False) -> dict[str, Any]:
    """Extract the sidecar payload for ``patch`` (does NOT write).

    ``source``: ``wiki`` (action=raw + getter fallback only), ``cdragon``
    (character bins only), or ``both`` (default: wiki primary, CDragon fills the
    nulls). ``default_cast``: when True (default), any champ still missing an
    attack_cast_time after wiki+CDragon is filled with the default 0.25s
    (provenance "default"; equals combo.py's fallback so default-filled champs
    stay byte-identical to no-sidecar), so attack_cast_time reaches 171/171.

    Wiki stage: one action=raw fetch of the ChampionData module keyed by apiname,
    with a per-champ getter fallback for a champ the raw parse missed an
    attack_cast_time for. CDragon stage: one character-bin fetch per champ,
    walked for the basic-attack scalars (melee missile_speed dropped via the
    DDragon attackrange guard); CDragon stores mAttackCastTime ONLY for champs
    that override the default, so it fills ~12 of the wiki nulls and the rest
    fall to the engine default. The merge keeps the highest-precedence value;
    provenance is stamped per scalar in ``<field>_src``.
    """
    use_wiki = source in ("wiki", "both")
    use_cdragon = source in ("cdragon", "both")
    display_names = _load_display_names(patch)
    attack_ranges = _load_attack_ranges(patch)
    ids = _resolve_champion_ids(patch, full_roster)
    if limit:
        ids = ids[:limit]

    # --- wiki stage (raw table + per-champ getter fallback) ---
    table: dict[str, dict[str, Any]] = {}
    table_err: Optional[str] = None
    if use_wiki:
        try:
            table = _load_wiki_table()
        except Exception as exc:  # noqa: BLE001 - degrade to per-champ getter
            table_err = f"raw module fetch failed: {type(exc).__name__}: {str(exc)[:140]}"

    champions: dict[str, dict[str, Any]] = {}
    ok = 0
    ms_ok = 0
    cd_fill = 0
    default_fill = 0
    offset_fill = 0
    mode_mod_ok = 0
    errs: list[str] = []
    if table_err:
        errs.append(table_err)
    for n, ddragon_id in enumerate(ids):
        wname = _wiki_name(ddragon_id, display_names)
        rec = table.get(ddragon_id) or {}
        w_act: Optional[float] = rec.get(_FIELD_ATTACK_CAST_TIME)
        w_tot: Optional[float] = rec.get(_FIELD_ATTACK_TOTAL_TIME)
        w_ms: Optional[float] = rec.get(_FIELD_MISSILE_SPEED)
        did_net = False
        err_here = False
        try:
            if use_wiki and w_act is None:
                # raw omitted it (defaulter) or champ absent -> authoritative getter
                w_act = _fetch_field(wname, _FIELD_ATTACK_CAST_TIME, stats_fallback=True)
                did_net = True
            if use_wiki and ddragon_id not in table and w_ms is None:
                # champ entirely absent from the raw table -> try getter for ms too
                w_ms = _fetch_field(wname, _FIELD_MISSILE_SPEED, stats_fallback=True)
                did_net = True
        except Exception as exc:  # noqa: BLE001 - fail-soft per champ
            errs.append(f"{ddragon_id} wiki: {type(exc).__name__}: {str(exc)[:120]}")
            err_here = True

        # --- cdragon stage (only when a scalar is still null AND backfill on) ---
        cd: dict[str, Optional[float]] = {}
        need_cd = use_cdragon and (w_act is None or w_tot is None or w_ms is None)
        if need_cd:
            try:
                cd = _cdragon_scalars(ddragon_id, attack_ranges.get(ddragon_id))
                did_net = True
            except Exception as exc:  # noqa: BLE001 - fail-soft per champ
                errs.append(f"{ddragon_id} cdragon: {type(exc).__name__}: {str(exc)[:120]}")
                err_here = True

        out_rec: dict[str, Any] = {"wiki_name": wname}
        cast_default = _ENGINE_DEFAULT_CAST_TIME if default_cast else None
        # Win 1 offset tier: when neither source measures a cast time, derive the
        # windup from the wiki attack_delay_offset (seconds at base AS). Sits
        # between cdragon and the flat default in _merge_fill's precedence.
        w_off = rec.get(_FIELD_ATTACK_DELAY_OFFSET)
        w_asb = rec.get(_FIELD_AS_BASE)
        off_cast = (
            _round6((_WINDUP_OFFSET_BASE + w_off) / w_asb)
            if (w_off is not None and w_asb) else None
        )
        _merge_fill(out_rec, _FIELD_ATTACK_CAST_TIME, w_act,
                    cd.get(_FIELD_ATTACK_CAST_TIME), cast_default,
                    offset_val=off_cast)
        _merge_fill(out_rec, _FIELD_ATTACK_TOTAL_TIME, w_tot, cd.get(_FIELD_ATTACK_TOTAL_TIME))
        _merge_fill(out_rec, _FIELD_MISSILE_SPEED, w_ms, cd.get(_FIELD_MISSILE_SPEED))
        # Mode modifiers are wiki-only (parsed from the raw-table entry); no
        # cdragon/default fill, no _src. Absent champ / no mode blocks -> {}.
        mode_modifiers = rec.get(_FIELD_MODE_MODIFIERS) or {}
        out_rec[_FIELD_MODE_MODIFIERS] = mode_modifiers
        champions[ddragon_id] = out_rec

        if out_rec[_FIELD_ATTACK_CAST_TIME] is not None:
            ok += 1
        if out_rec[_FIELD_MISSILE_SPEED] is not None:
            ms_ok += 1
        if out_rec[_FIELD_ATTACK_CAST_TIME + _SRC_SUFFIX] == "cdragon":
            cd_fill += 1
        if out_rec[_FIELD_ATTACK_CAST_TIME + _SRC_SUFFIX] == "wiki_offset":
            offset_fill += 1
        if out_rec[_FIELD_ATTACK_CAST_TIME + _SRC_SUFFIX] == "default":
            default_fill += 1
        if mode_modifiers:
            mode_mod_ok += 1

        if verbose:
            tag = "ERR" if err_here else "ok"
            modes_str = ",".join(sorted(mode_modifiers)) if mode_modifiers else "-"
            print(
                f"[{n+1}/{len(ids)}] {ddragon_id} ({wname}): "
                f"act={out_rec[_FIELD_ATTACK_CAST_TIME]} "
                f"[{out_rec[_FIELD_ATTACK_CAST_TIME + _SRC_SUFFIX]}] "
                f"ms={out_rec[_FIELD_MISSILE_SPEED]} "
                f"[{out_rec[_FIELD_MISSILE_SPEED + _SRC_SUFFIX]}] "
                f"modes=[{modes_str}] {tag}"
            )
        if sleep_s > 0 and did_net and n + 1 < len(ids):
            time.sleep(sleep_s)

    src_label = {
        "wiki": "wiki.leagueoflegends.com Module:ChampionData/data (action=raw + getter fallback)",
        "cdragon": "CommunityDragon game/data/characters/<slug>/<slug>.bin.json",
        "both": (
            "wiki.leagueoflegends.com Module:ChampionData/data (action=raw + getter "
            "fallback) PRIMARY; CommunityDragon character bins BACKFILL of nulls"
        ),
    }[source]
    return {
        "_source": src_label,
        "_source_mode": source,
        "_patch": patch,
        "_fields": [
            _FIELD_ATTACK_CAST_TIME, _FIELD_ATTACK_TOTAL_TIME, _FIELD_MISSILE_SPEED,
            _FIELD_MODE_MODIFIERS,
        ],
        "_note": (
            "OPTIONAL DS overlay. attack_cast_time = AA windup (s); "
            "attack_total_time = full AA cycle (s); missile_speed = ranged AA "
            "missile speed (melee null). Each scalar carries a <field>_src "
            "provenance: 'wiki' (operator-named source, wins) > 'cdragon' (fills "
            "wiki nulls) > 'wiki_offset' (windup derived from the wiki "
            "attack_delay_offset: (0.300+offset)/as_base, for champs with no "
            "explicit cast time; attack_cast_time only) > 'default' (0.25s = "
            "combo.py fallback, for champs no source/offset covers; "
            "attack_cast_time only) > null. "
            "mode_modifiers = per-mode balance changes parsed from the SAME wiki "
            "raw module (wiki-sourced only, no _src; {} when a champ has none): "
            "aram/urf/nb/ofa/usb store MULTIPLIERS (dmg_dealt 1.05 = +5%), ar "
            "(Arena/CHERRY) + swift (Swiftplay) store ADDEND stat-overrides "
            "(hp_lvl 17 = +17 hp/level); inner keys stored verbatim, not coerced. "
            "Meraki stays authoritative for ratios/CC. A run with "
            "_with_cast_measured==0 means the host could not reach either source "
            "(edge block) - do NOT commit."
        ),
        "_champ_count": len(champions),
        "_with_cast_time": ok,
        "_with_cast_measured": ok - default_fill,
        "_with_missile_speed": ms_ok,
        "_cdragon_cast_fills": cd_fill,
        "_offset_cast_fills": offset_fill,
        "_default_cast_fills": default_fill,
        "_with_mode_modifiers": mode_mod_ok,
        "_errors": errs,
        "champions": champions,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--patch", help="patch id, e.g. 16.11.1; default current.txt")
    ap.add_argument("--out", help="output path; default data/daemon_slayer/<patch>/wiki_stats.json")
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between per-champ network calls (default 0.5)")
    ap.add_argument("--limit", type=int, default=0, help="extract only the first N champs (smoke test)")
    ap.add_argument(
        "--source", choices=("wiki", "cdragon", "both"), default="both",
        help="data source: wiki only, cdragon only, or both (default: wiki wins, cdragon fills nulls)",
    )
    ap.add_argument(
        "--no-default-cast", action="store_true",
        help="do NOT fill the 0.25s default for champs with no measured cast time "
             "(leaves them null instead of 171/171)",
    )
    ap.add_argument(
        "--full-roster", action="store_true",
        help="A-26/RM-95b: source champs from champions.json (173) instead of "
             "champion_abilities.json (171); the only way Locke + Zaahen are reached",
    )
    ap.add_argument("--dry-run", action="store_true", help="extract but do not write")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-champ progress")
    args = ap.parse_args(argv)

    patch = _resolve_patch(args.patch)
    out_path = Path(args.out) if args.out else (DATA_DIR / patch / "wiki_stats.json")

    payload = extract(patch, args.sleep, args.limit or None, args.verbose, args.source,
                      default_cast=not args.no_default_cast,
                      full_roster=args.full_roster)
    print(
        f"patch={patch} source={args.source} champs={payload['_champ_count']} "
        f"with_cast_time={payload['_with_cast_time']} "
        f"(measured={payload['_with_cast_measured']} offset={payload['_offset_cast_fills']} "
        f"default={payload['_default_cast_fills']}) "
        f"with_missile_speed={payload['_with_missile_speed']} "
        f"cdragon_cast_fills={payload['_cdragon_cast_fills']} "
        f"errors={len(payload['_errors'])}"
    )
    if payload["_errors"]:
        for e in payload["_errors"][:10]:
            print("  ERR", e)
    if payload["_with_cast_measured"] == 0:
        print("WARNING: 0 champs resolved a MEASURED cast time - host likely cannot reach "
              "the source(s); NOT a committable sidecar (only engine defaults present).")

    if args.dry_run:
        print("(dry-run; not written)")
        return 0
    _atomic_write_json(out_path, payload)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
