# arch: lolmath-wiki per-ability param sidecar extractor (ChampionData + Template:Data -> wiki_ability_stats.json) | section=tools | frozen=no
"""LoL wiki ``Template:Data <Champion>/<Ability>`` params -> per-ability sidecar JSON.

A thin OPTIONAL sidecar extractor for the per-ability structured params the
Meraki bulk + DDragon do NOT carry and that DS cooldown/CC modeling wants:

  * STATIC-COOLDOWN FLAG (the net-new prize) - ``static`` (Anivia Glacial Storm
    ``|static = 1`` => the cooldown does NOT scale with ability haste). Plus the
    raw ``cooldown`` / ``cdstart`` / ``ontargetcd`` / ``ontargetcdstatic`` markup
    where present.
  * RECHARGE TIME - ``recharge`` (Teemo trap ``{{ap|35 to 25}}``, Heimer turret
    ``20``). Captured raw AND resolved to a per-rank array when it is a trivial
    ``{{ap|X to Y}}`` / ``{{fd|N}}`` wrapper.
  * TYPED CC-CLASS BOOLEANS - ``knockdown`` / ``silence`` / ``grounded`` /
    ``spellshield`` / ``parry`` / ``terraingrace`` / ``callforhelp``. Values like
    ``true`` / ``True`` / ``1`` -> True; ``false`` / ``False`` -> False; the
    tri-state ``spellshield = Special`` (and any other non-empty/non-bool token)
    is kept as the raw string; an EMPTY param (``|grounded =``) -> omitted.
  * GEOMETRY - ``effect radius`` / ``width`` / ``angle`` / ``collision radius`` /
    ``inner radius`` / ``tether radius`` / ``speed`` / ``cast time`` - captured as
    RAW strings (markup-laden, e.g. ``{{tip|cr}} 450`` / ``{{ap|...}}`` / ``none``);
    NOT over-cleaned.

There is NO CC-duration-seconds param on these pages - CC duration lives ONLY in
the free-text ``leveling`` / ``description`` / ``{{st|Stun Duration|...}}`` lines,
not in a queryable param. This tool does NOT attempt to extract CC durations; the
absence is noted in ``_note``.

ACCESS (verified live 2026-05-30):
  * Host ``https://wiki.leagueoflegends.com`` (the Riot vanity alias for the
    wiki.gg backend). The bare ``leagueoflegends.wiki.gg`` host edge-blocks
    this development host's egress (HTTP 401 host-wide); the alias is
    reachable (HTTP 200).
  * User-Agent MUST be NON-browser (e.g. ``Amberstone-DaemonSlayer/1.0``). A
    ``Mozilla/5.0`` UA trips a Cloudflare challenge -> 403. stdlib urllib only.

EFFICIENT FETCH (the key design choice): do NOT GET ~1080 ability pages one at a
time (slow + edge-block / rate-trip risk - a prior session tripped a 401 burst on
the chatty per-field path). Instead BATCH via the MediaWiki query API:
  GET /en-us/api.php?action=query&prop=revisions&rvslots=main&rvprop=content
      &format=json&titles=Template:Data Aatrox/The Darkin Blade|...
with UP TO 50 titles per request (the MediaWiki non-bot limit). 174 champ blocks
x ~6 abilities = ~1080 titles / 50 = ~22 requests total, with a polite ``--sleep``
between batch calls. Missing pages come back with ``pid=-1`` + ``missing=True``
(fail-soft -> ``_missing_pages``).

TITLE LIST is built from the wiki ``Module:ChampionData/data`` raw module (the
SAME source the sibling ``daemon_slayer_wiki_stats_extract.py`` brace-parses; this
tool reuses that parse shape). Each champ block has ``skill_i`` / ``skill_q`` /
``skill_w`` / ``skill_e`` / ``skill_r`` = arrays of ability DISPLAY NAMES, e.g.
Aatrox ``skill_q = {[1]="The Darkin Blade", [2]="The Darkin Blade 2", ...}``. The
``Template:Data`` title is ``Template:Data <ChampDisplayName>/<AbilityName>`` where
``<ChampDisplayName>`` is the wiki BLOCK KEY (e.g. "Aatrox", "Kai'Sa", "Wukong",
"Nunu & Willump" - NOT the apiname). Some forms (e.g. "The Darkin Blade 2") have no
Data page of their own -> fail-soft, that ability just gets no record.

NOT a live dependency: an OFFLINE patch-refresh tool, the SAME contract as
``daemon_slayer_abilities_extract.py`` + ``daemon_slayer_wiki_stats_extract.py``.
The DS engine reads the committed sidecar JSON, never the network. Absent sidecar
-> current behavior. INERT until a consumer opts in (no wiring this run - data
only, no ENGINE bump, no DS restart).

Run from any host that reaches the alias:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_ability_extract.py            # current.txt patch
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_ability_extract.py --patch 16.11.1
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_ability_extract.py --limit 3  # first 3 champs (~1 batch)
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_wiki_ability_extract.py --dry-run  # no write
Then inspect ``_ability_count`` / ``_with_static`` / ``_errors`` before trusting
it: a run that edge-blocks the host records 0 abilities (fail-soft), so an
``_ability_count == 0`` means the host could not reach the wiki - do NOT commit.
(``_with_static == 0`` with ``_ability_count > 0`` is plausibly fine; ``static`` is
a RARE param - only a handful of toggle/turret/trap abilities carry it.)

Design (don't re-litigate):
  * stdlib ``urllib`` only - no new pip dep (the DS data-pipeline rule).
  * Non-browser User-Agent (a browser UA trips Cloudflare 403).
  * Batched ``titles=`` (<= ``_MAX_TITLES_PER_BATCH`` per call); polite ``--sleep``
    between batches; ~22 batch calls total, not ~1080 page GETs.
  * fail-soft: a missing page -> ``_missing_pages``; a bad batch response -> the
    whole batch's titles -> ``_errors`` (the run continues to the next batch).
  * Atomic write: tmp.write_text + os.replace (overlays poll mid-write).
  * ASCII-only SOURCE (the no-em-dash repo rule). Ability names from the wiki may
    contain apostrophes (Kai'Sa) - those live in DATA strings written with
    ensure_ascii=True, fine; the .py SOURCE stays 7-bit ASCII.
  * Output keyed by ``<ChampDisplayName>/<AbilityName>`` (the wiki block key +
    ability display name == the Template:Data title minus the ``Template:Data ``
    prefix), so a consumer can join on either the title or the (champ, ability)
    pair. Only params actually present on a page are emitted (the rest omitted).
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

# The .wiki.gg host edge-blocks this host (HTTP 401 host-wide). The Riot vanity
# alias is the SAME wiki.gg backend and is reachable. See module docstring.
WIKI_HOST = "https://wiki.leagueoflegends.com"
WIKI_API = WIKI_HOST + "/en-us/api.php"
WIKI_RAW_MODULE = WIKI_HOST + "/en-us/Module:ChampionData/data?action=raw"
# A NON-browser UA. A Mozilla/5.0 UA trips a Cloudflare challenge -> 403.
HEADER_UA = "Amberstone-DaemonSlayer/1.0 (offline patch-refresh extractor; local coaching tool)"
_HTTP_TIMEOUT = 40

# MediaWiki non-bot query API allows up to 50 titles per request.
_MAX_TITLES_PER_BATCH = 50

_TEMPLATE_PREFIX = "Template:Data "

# The skill slots, in a stable order (i = passive/inherent, then q/w/e/r).
_SKILL_SLOTS = ("i", "q", "w", "e", "r")

# Wiki slot token -> the AbilitiesSnapshot key letter (RM-95b B2 join key).
# The wiki calls the passive "i" (inherent); the snapshot calls it "P".
_SLOT_LETTER = {"i": "P", "q": "Q", "w": "W", "e": "E", "r": "R"}

# Typed CC-class boolean params (true/True/1 -> True; false/False -> False;
# the tri-state spellshield=Special and any other non-empty/non-bool token is
# kept as the raw string; an EMPTY param value -> omitted).
_CC_FLAG_PARAMS = (
    "knockdown",
    "silence",
    "grounded",
    "spellshield",
    "parry",
    "terraingrace",
    "callforhelp",
)

# Cooldown-family params captured RAW (the markup is preserved for audit).
_COOLDOWN_PARAMS = (
    "cooldown",
    "cdstart",
    "recharge",
    "ontargetcd",
    "ontargetcdstatic",
)

# Geometry params captured RAW (markup-laden; not over-cleaned). The output key
# normalizes a space to an underscore + appends ``_raw`` (e.g. effect radius ->
# effect_radius_raw).
_GEOMETRY_PARAMS = (
    "effect radius",
    "width",
    "angle",
    "collision radius",
    "inner radius",
    "tether radius",
    "speed",
    "cast time",
)

# Leveling params captured RAW (RM-95b B2). These are the ONLY multi-line params
# on a Template:Data page: the {{st|Label|Value|...}} payload wraps across as
# many lines as the editor liked, so they are read by a brace-depth scan rather
# than the line-anchored _param_re the other families use. Numbered variants are
# listed explicitly because _param_re / _block_param both exclude a digit that
# sits between the name and the ``=``.
_LEVELING_PARAMS = (
    "leveling",
    "leveling2",
    "leveling3",
    "leveling4",
    "leveling5",
)


def _fetch(url: str, timeout: int = _HTTP_TIMEOUT) -> str:
    """GET text with a NON-browser UA header (a browser UA trips Cloudflare)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": HEADER_UA, "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _fetch_raw_module(timeout: int = _HTTP_TIMEOUT) -> str:
    """GET the Module:ChampionData/data raw wikitext (the Lua return table)."""
    return _fetch(WIKI_RAW_MODULE, timeout=timeout)


def _fetch_batch(titles: list[str], timeout: int = _HTTP_TIMEOUT) -> dict[str, Any]:
    """GET the query-API JSON for a batch of titles (<= 50). Returns the parsed dict."""
    params = {
        "action": "query",
        "prop": "revisions",
        "rvslots": "main",
        "rvprop": "content",
        "format": "json",
        "titles": "|".join(titles),
    }
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    return json.loads(_fetch(url, timeout=timeout))


def _resolve_patch(patch: Optional[str]) -> str:
    if patch:
        return patch
    cur = (DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    if not cur:
        raise SystemExit("current.txt empty; pass --patch")
    return cur


def _load_champion_apinames(patch: str) -> set[str]:
    """The DDragon ids (== wiki ``apiname``) in the committed abilities snapshot.

    Used to restrict the title list to the champs the DS engine actually models
    (the wiki ChampionData table has a few extra/event entries). The abilities
    file keys champions under the top-level ``data`` dict.
    """
    abil = DATA_DIR / patch / "champion_abilities.json"
    if not abil.exists():
        raise SystemExit(f"abilities file missing: {abil} (run the abilities extractor first)")
    raw = json.loads(abil.read_text(encoding="utf-8"))
    champs = raw.get("data") or raw.get("champions") or {}
    if not champs:
        raise SystemExit(f"abilities file {abil} has no 'data' champion container")
    return set(champs.keys())


def _load_roster_apinames(patch: str) -> set[str]:
    """The DDragon ids in the committed ROSTER snapshot (``champions.json``).

    A-26 / RM-95b. ``champion_abilities.json`` is a Meraki derivative and the
    Meraki champions artifact has been frozen upstream since 2025-08-01, so it
    is 2 champions short of the live roster (Locke, Zaahen). The DDragon roster
    file is the wider, live source and keys champions under ``data`` the same
    way. OPT-IN ONLY - see ``_resolve_keep_apinames``.
    """
    roster = DATA_DIR / patch / "champions.json"
    if not roster.exists():
        raise SystemExit(f"roster file missing: {roster} (run the champions extractor first)")
    raw = json.loads(roster.read_text(encoding="utf-8"))
    champs = raw.get("data") or {}
    if not champs:
        raise SystemExit(f"roster file {roster} has no 'data' champion container")
    return set(champs.keys())


def _resolve_keep_apinames(patch: str, full_roster: bool) -> set[str]:
    """Pick the champion keyspace: the abilities snapshot (default) or the roster.

    ``full_roster=False`` is the pre-A-26 behavior and MUST stay byte-identical:
    it delegates to ``_load_champion_apinames`` unchanged.
    """
    if full_roster:
        return _load_roster_apinames(patch)
    return _load_champion_apinames(patch)


_BLOCK_OPEN_RE = re.compile(r'\["([^"]+)"\]\s*=\s*\{')
_APINAME_RE = re.compile(r'\["apiname"\]\s*=\s*"([^"]+)"')
# A skill_<slot> array: ["skill_q"] = {[1] = "Name", [2] = "Name2", ...}. The
# value has no nested braces (flat string entries), so a non-greedy [^}]* is safe.
_SKILL_ARRAY_RE = re.compile(r'\["skill_([iqwer])"\]\s*=\s*\{([^}]*)\}')
_SKILL_ENTRY_RE = re.compile(r'\[\d+\]\s*=\s*"([^"]*)"')


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


def _parse_champion_skills(raw: str) -> dict[str, dict[str, Any]]:
    """Parse Module:ChampionData/data action=raw -> {apiname: {display, skills}}.

    Brace-scans each top-level champion block (identified by an ``id`` +
    ``apiname`` head, which excludes nested subtables like ``stats``) and pulls:
      * ``display`` = the wiki BLOCK KEY (e.g. "Kai'Sa", "Wukong", "Nunu &
        Willump") - this is the ``Template:Data <display>/...`` title prefix.
      * ``skills`` = {slot: [ability display names]} for slots i/q/w/e/r.
    Keyed by ``apiname`` (== the Riot/DDragon champion id) for joining to the
    abilities snapshot.
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
        am = _APINAME_RE.search(blk)
        if not am:
            continue
        skills: dict[str, list[str]] = {}
        for sm in _SKILL_ARRAY_RE.finditer(blk):
            slot = sm.group(1)
            names = [e.group(1).strip() for e in _SKILL_ENTRY_RE.finditer(sm.group(2))]
            names = [n for n in names if n]
            if names:
                skills[slot] = names
        out[am.group(1)] = {"display": m.group(1), "skills": skills}
    return out


def _build_title_index(
    skills_by_api: dict[str, dict[str, Any]],
    keep_apinames: Optional[set[str]],
) -> list[tuple[str, str, str, str]]:
    """The (apiname, slot, display, ability_name) rows for every skill entry.

    RM-95b B2: the SLOT is carried here because the emitted sidecar record needs
    an ``apiname`` + ``P/Q/W/E/R`` join key to reach an ``AbilitiesSnapshot``
    form; keying on ``display + "/" + ability_name`` alone cannot. ``_build_titles``
    is the 3-tuple wrapper that predates this and stays byte-identical.

    Restricts to ``keep_apinames`` when given (the abilities-snapshot champs).
    De-dups identical (display, ability_name) pairs across slots (rare). Order:
    sorted by apiname, then slot order, then array order.
    """
    rows: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for api in sorted(skills_by_api):
        if keep_apinames is not None and api not in keep_apinames:
            continue
        rec = skills_by_api[api]
        display = rec.get("display") or api
        skills = rec.get("skills") or {}
        for slot in _SKILL_SLOTS:
            for name in skills.get(slot, []):
                key = (display, name)
                if key in seen:
                    continue
                seen.add(key)
                rows.append((api, _SLOT_LETTER[slot], display, name))
    return rows


def _build_titles(skills_by_api: dict[str, dict[str, Any]],
                  keep_apinames: Optional[set[str]]) -> list[tuple[str, str, str]]:
    """Build the (apiname, display, ability_name) tuples for every skill entry.

    Thin wrapper over ``_build_title_index`` that drops the slot letter. Kept at
    its original 3-tuple shape because existing callers and tests unpack three.
    """
    return [(api, display, name) for api, _slot, display, name in
            _build_title_index(skills_by_api, keep_apinames)]


# --------------------------------------------------------------------------- param parsing
_AP_WRAPPER_RE = re.compile(r"\{\{\s*ap\s*\|\s*([0-9.]+)\s+to\s+([0-9.]+)\s*\}\}", re.IGNORECASE)
_FD_WRAPPER_RE = re.compile(r"\{\{\s*fd\s*\|\s*([0-9.]+)\s*\}\}", re.IGNORECASE)


def _resolve_ap(raw: str) -> Optional[list[float]]:
    """``{{ap|X to Y}}`` -> 5-rank linear interp [X, .., Y]; else None.

    ``{{ap|35 to 25}}`` => [35.0, 32.5, 30.0, 27.5, 25.0]. Only fires when the
    string IS (or contains) a clean ap wrapper; returns None for anything else
    (the caller still keeps the raw string).
    """
    m = _AP_WRAPPER_RE.search(raw or "")
    if not m:
        return None
    try:
        a = float(m.group(1))
        b = float(m.group(2))
    except (TypeError, ValueError):
        return None
    steps = 5
    return [round(a + (b - a) * i / (steps - 1), 6) for i in range(steps)]


def _resolve_fd(raw: str) -> Optional[float]:
    """``{{fd|N}}`` -> N (a single fixed value); else None."""
    m = _FD_WRAPPER_RE.search(raw or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def _resolve_recharge(raw: str) -> Optional[Any]:
    """Resolve a ``recharge`` raw value to per-rank array / scalar where trivial.

    ``{{ap|35 to 25}}`` -> [35, 32.5, 30, 27.5, 25]; ``{{fd|0.25}}`` -> 0.25; a
    bare number (``20``) -> 20.0; otherwise None (caller keeps recharge_raw). The
    ap form is tried before fd (an ap wrapper never matches the fd regex).
    """
    s = (raw or "").strip()
    if not s:
        return None
    ranks = _resolve_ap(s)
    if ranks is not None:
        return ranks
    fd = _resolve_fd(s)
    if fd is not None:
        return fd
    # Bare-number fallback: ``float()`` parses "inf" / "nan" / "Infinity" from
    # verbatim wiki markup; a non-finite value would be written into
    # recharge_ranks and ``json.dumps`` then emits a BARE NaN/Infinity token
    # (invalid JSON). Reject non-finite so the caller keeps only recharge_raw.
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _norm_cc_flag(raw: str) -> Optional[Any]:
    """Normalize a CC-class param value.

    Returns True for true/True/1/yes; False for false/False/0/no; the raw token
    (stripped) for any other non-empty value (e.g. ``Special``); None for an
    EMPTY value (``|grounded =``) so the param is omitted from the record.
    """
    s = (raw or "").strip()
    if not s:
        return None
    low = s.lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return s  # tri-state token like "Special"


def _param_re(name: str) -> "re.Pattern[str]":
    """A regex matching ``|<name> = <value>`` up to end-of-line.

    Wiki params have variable whitespace before ``=`` (``|effect radius    =``).
    The value runs to the line end (the Template:Data params are one-per-line).
    Captures the value group (may be empty). The post-``=`` whitespace is
    HORIZONTAL-only (``[^\\S\\n]*``) NOT ``\\s*``: an empty param ``|grounded =``
    followed by a newline must capture "" - a greedy ``\\s*`` would swallow the
    newline and grab the NEXT line's content as the value. Numbered variants
    like ``effect radius2`` are excluded because the digit sits between the name
    and the ``=`` so the ``\\s*=`` does not match.
    """
    return re.compile(
        r"\|\s*" + re.escape(name) + r"[^\S\n]*=[^\S\n]*([^\n]*)", re.IGNORECASE
    )


# Pre-compile every param regex once (module-level; the same patterns run across
# every page).
_STATIC_RE = _param_re("static")
_CC_FLAG_RES = {p: _param_re(p) for p in _CC_FLAG_PARAMS}
_COOLDOWN_RES = {p: _param_re(p) for p in _COOLDOWN_PARAMS}
_GEOMETRY_RES = {p: _param_re(p) for p in _GEOMETRY_PARAMS}


def _first_param(wikitext: str, rx: "re.Pattern[str]") -> Optional[str]:
    """The FIRST occurrence of a param's value (stripped), or None if absent."""
    m = rx.search(wikitext or "")
    if not m:
        return None
    return m.group(1).strip()


def _block_param(wikitext: str, name: str) -> Optional[str]:
    """A param value that MAY SPAN LINES, terminated by brace depth (RM-95b B2).

    ``_param_re`` stops at end-of-line on purpose: the params it was written for
    are one-per-line. ``leveling`` is not - its ``{{st|Label|Value|...}}`` payload
    wraps freely, so a line-anchored capture truncates it mid-template. Scanning
    ``{{``/``}}`` and ``[[``/``]]`` depth is the only correct terminator.

    The value is returned VERBATIM (markup preserved) with runs of whitespace
    collapsed to single spaces so the emitted JSON stays one line. Terminates on
    a newline or a fresh ``|`` at depth 0, or on the outer template's own ``}}``.
    An absent OR empty param returns None, matching the ``if v:`` gate the
    cooldown / geometry families already use.
    """
    m = re.search(
        r"\|\s*" + re.escape(name) + r"[^\S\n]*=[^\S\n]*",
        wikitext or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    i, n = m.end(), len(wikitext)
    depth = 0
    out: list[str] = []
    while i < n:
        two = wikitext[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            out.append(two)
            i += 2
            continue
        if two in ("}}", "]]"):
            if depth <= 0:
                break  # the ENCLOSING template closed; the value ended
            depth -= 1
            out.append(two)
            i += 2
            continue
        ch = wikitext[i]
        if ch == "\n":
            if depth <= 0:
                break
            out.append(" ")
            i += 1
            continue
        if ch == "|" and depth <= 0:
            break
        out.append(ch)
        i += 1
    return " ".join("".join(out).split()) or None


def _geom_key(param_name: str) -> str:
    """``effect radius`` -> ``effect_radius_raw`` (output key for a geometry param)."""
    return param_name.replace(" ", "_") + "_raw"


def _parse_ability_page(wikitext: str) -> dict[str, Any]:
    """Extract the params we care about from one Template:Data page's wikitext.

    Only params actually present are included (absent / empty -> omitted).
    Returns the per-ability record (no champ/ability identity - the caller keys
    it).
    """
    rec: dict[str, Any] = {}

    # --- static-cooldown flag (the prize) + cooldown family (raw) ---
    static_raw = _first_param(wikitext, _STATIC_RE)
    if static_raw is not None:
        static_flag = _norm_cc_flag(static_raw)
        if static_flag is not None:
            rec["static"] = static_flag

    for p in _COOLDOWN_PARAMS:
        v = _first_param(wikitext, _COOLDOWN_RES[p])
        if v:  # non-empty
            rec[p + "_raw"] = v

    # recharge resolution (per-rank array / scalar where trivial)
    rech_raw = rec.get("recharge_raw")
    if rech_raw is not None:
        resolved = _resolve_recharge(rech_raw)
        if resolved is not None:
            rec["recharge_ranks"] = resolved

    # --- typed CC-class booleans ---
    for p in _CC_FLAG_PARAMS:
        raw = _first_param(wikitext, _CC_FLAG_RES[p])
        if raw is None:
            continue
        val = _norm_cc_flag(raw)
        if val is not None:  # omit empty params
            rec[p] = val

    # --- geometry (raw) ---
    for p in _GEOMETRY_PARAMS:
        v = _first_param(wikitext, _GEOMETRY_RES[p])
        if v:  # non-empty
            rec[_geom_key(p)] = v

    # --- leveling family (raw, MULTI-LINE; RM-95b B2) ---
    for p in _LEVELING_PARAMS:
        v = _block_param(wikitext, p)
        if v:  # non-empty
            rec[p + "_raw"] = v

    return rec


# --------------------------------------------------------------------------- batch walk
def _extract_page_text(page: dict[str, Any]) -> Optional[str]:
    """Pull the main-slot wikitext out of one query-API page object; None if absent."""
    revs = page.get("revisions") or []
    if not revs:
        return None
    slots = (revs[0] or {}).get("slots") or {}
    main = slots.get("main") or {}
    txt = main.get("*")
    return txt if isinstance(txt, str) else None


def _atomic_write_json(path: Path, payload: Any) -> None:
    """tmp.write_text + os.replace - the repo atomic-write rule."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=True, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def _chunk(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def extract(patch: str, sleep_s: float, limit: Optional[int], verbose: bool,
            *, full_roster: bool = False,
            _module_text: Optional[str] = None,
            _batch_fn: Optional[Any] = None) -> dict[str, Any]:
    """Extract the per-ability sidecar payload for ``patch`` (does NOT write).

    ``limit`` caps the number of CHAMPS (first N apinames, sorted) - used for the
    smoke test. ``_module_text`` / ``_batch_fn`` are test seams (inject a canned
    ChampionData module text + a canned batch fetcher); in production they default
    to the live wiki fetchers.

    Flow: fetch+parse the ChampionData module -> build the title list -> batch the
    query API (<= 50 titles/call) -> parse each returned page -> assemble. A
    missing page -> ``_missing_pages``; a failed batch -> the batch's titles ->
    ``_errors`` (the run continues).

    ``full_roster`` (A-26 / RM-95b, DEFAULT-OFF) sources the champion keyspace
    from ``champions.json`` (173) instead of ``champion_abilities.json`` (171),
    which is what lets Locke and Zaahen through. Off, output is unchanged.
    """
    keep = _resolve_keep_apinames(patch, full_roster)

    module_text = _module_text if _module_text is not None else _fetch_raw_module()
    skills_by_api = _parse_champion_skills(module_text)
    triples = _build_title_index(skills_by_api, keep)

    if limit:
        keep_apis = sorted({t[0] for t in triples})[:limit]
        keep_set = set(keep_apis)
        triples = [t for t in triples if t[0] in keep_set]

    # title -> (display, ability) so we can re-key the returned pages. The wiki
    # may NORMALIZE a title (it did not in probing, but be safe): we match on the
    # ``Template:Data <display>/<ability>`` string we sent.
    title_for: dict[str, tuple[str, str]] = {}
    ident_for: dict[str, tuple[str, str]] = {}  # title -> (apiname, slot letter)
    titles: list[str] = []
    for api, slot, display, ability in triples:
        title = _TEMPLATE_PREFIX + display + "/" + ability
        title_for[title] = (display, ability)
        ident_for[title] = (api, slot)
        titles.append(title)

    batch_fn = _batch_fn if _batch_fn is not None else _fetch_batch

    abilities: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    errs: list[str] = []
    batches = _chunk(titles, _MAX_TITLES_PER_BATCH)
    for bi, batch in enumerate(batches):
        try:
            doc = batch_fn(batch)
        except Exception as exc:  # noqa: BLE001 - fail-soft per batch
            errs.append(
                f"batch {bi + 1}/{len(batches)} ({len(batch)} titles) failed: "
                f"{type(exc).__name__}: {str(exc)[:140]}"
            )
            if verbose:
                print(f"[batch {bi + 1}/{len(batches)}] ERROR {type(exc).__name__}")
            continue
        pages = ((doc or {}).get("query") or {}).get("pages") or {}
        got = 0
        for _pid, page in pages.items():
            title = page.get("title") or ""
            ident = title_for.get(title)
            if ident is None:
                # the wiki normalized a title we sent (rare); skip - cannot re-key
                continue
            display, ability = ident
            okey = display + "/" + ability
            if "missing" in page:
                missing.append(okey)
                continue
            wt = _extract_page_text(page)
            if wt is None:
                missing.append(okey)
                continue
            parsed = _parse_ability_page(wt)
            # RM-95b B2 join key: apiname + P/Q/W/E/R. Additive - every
            # pre-existing consumer keys on the ``display/ability`` map key.
            api_slot = ident_for.get(title)
            if api_slot is not None:
                parsed["apiname"], parsed["slot"] = api_slot
            abilities[okey] = parsed
            got += 1
        if verbose:
            print(f"[batch {bi + 1}/{len(batches)}] {len(batch)} titles -> {got} parsed")
        if sleep_s > 0 and bi + 1 < len(batches):
            time.sleep(sleep_s)

    with_static = sum(1 for r in abilities.values() if "static" in r)
    with_recharge = sum(1 for r in abilities.values() if "recharge_raw" in r)
    with_cc = sum(
        1 for r in abilities.values()
        if any(p in r for p in _CC_FLAG_PARAMS)
    )
    with_leveling = sum(
        1 for r in abilities.values()
        if any(p + "_raw" in r for p in _LEVELING_PARAMS)
    )

    return {
        "_source": (
            "wiki.leagueoflegends.com Template:Data <Champion>/<Ability> via "
            "action=query (batched titles, <=50/req); title list from "
            "Module:ChampionData/data skill_* arrays"
        ),
        "_patch": patch,
        "_note": (
            "OPTIONAL DS per-ability overlay. static = cooldown does NOT scale "
            "with ability haste (rare; toggle/turret/trap abilities). recharge = "
            "charge regen (recharge_raw kept verbatim; recharge_ranks resolves a "
            "trivial {{ap|X to Y}}/{{fd|N}}/bare wrapper). CC-class booleans "
            "(knockdown/silence/grounded/spellshield/parry/terraingrace/"
            "callforhelp): true/True/1 -> true, false/False -> false, the "
            "tri-state spellshield=Special kept as the raw string, empty param "
            "omitted. Geometry (*_raw) kept verbatim (markup-laden). There is NO "
            "CC-duration-seconds param on these pages - CC duration lives only in "
            "the free-text leveling/description payload, which is NOT typed here: "
            "RM-95b B2 captures leveling / leveling2..5 VERBATIM as leveling*_raw "
            "(multi-line, brace-depth terminated) and promoting it to typed blocks "
            "is a separate consumer-side step. Each record also carries its "
            "apiname + slot (P/Q/W/E/R) as the AbilitiesSnapshot join key. "
            "Only params "
            "present on a page are emitted. An _ability_count==0 means the host "
            "could not reach the wiki (edge block) - do NOT commit."
        ),
        "_ability_count": len(abilities),
        "_with_static": with_static,
        "_with_recharge": with_recharge,
        "_with_cc_flags": with_cc,
        "_with_leveling": with_leveling,
        "_missing_pages": sorted(missing),
        "_errors": errs,
        "abilities": abilities,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--patch", help="patch id, e.g. 16.11.1; default current.txt")
    ap.add_argument(
        "--out",
        help="output path; default data/daemon_slayer/<patch>/wiki_ability_stats.json",
    )
    ap.add_argument(
        "--sleep", type=float, default=1.0,
        help="seconds between batch query calls (default 1.0)",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="extract only the first N champs (smoke test)",
    )
    ap.add_argument(
        "--full-roster", action="store_true",
        help="A-26/RM-95b: source champs from champions.json (173) instead of "
             "champion_abilities.json (171); the only way Locke + Zaahen are reached",
    )
    ap.add_argument("--dry-run", action="store_true", help="extract but do not write")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-batch progress")
    args = ap.parse_args(argv)

    patch = _resolve_patch(args.patch)
    out_path = Path(args.out) if args.out else (DATA_DIR / patch / "wiki_ability_stats.json")

    payload = extract(patch, args.sleep, args.limit or None, args.verbose,
                      full_roster=args.full_roster)
    print(
        f"patch={patch} abilities={payload['_ability_count']} "
        f"with_static={payload['_with_static']} "
        f"with_recharge={payload['_with_recharge']} "
        f"with_cc_flags={payload['_with_cc_flags']} "
        f"missing_pages={len(payload['_missing_pages'])} "
        f"errors={len(payload['_errors'])}"
    )
    if payload["_errors"]:
        for e in payload["_errors"][:10]:
            print("  ERR", e)
    if payload["_ability_count"] == 0:
        print("WARNING: 0 abilities parsed - host likely cannot reach the wiki "
              "(edge block); NOT a committable sidecar.")

    if args.dry_run:
        print("(dry-run; not written)")
        return 0
    _atomic_write_json(out_path, payload)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
