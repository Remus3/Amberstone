"""Game-data sources for the reconciliation pipeline (P1-4).

Each source declares where its bodies live for a patch, whether it is
ERA-ADDRESSABLE (can serve an old patch's tables) and the terms it is used
under, and parses its bodies into one normalised shape:

    {"champions": {ddragon_id: {field: number}}, "items": {item_id: {field: number}},
     "version": str | None}

Field names are the pipeline's own (``lib.game_data.build.CHAMPION_FIELDS`` /
``ITEM_FIELDS``); a source that does not publish a field simply omits it.

Contract with ``lib.game_data.fetch`` (S144-T-702): a body the parser cannot
read - missing, not bytes, not JSON / Lua, or an entry of the wrong shape -
raises ``SourceParseError`` and nothing else, because ``fetch`` catches only
that and turns it into a ``MissingSourceError`` naming the source. Every
number emitted is finite: ``json.loads`` accepts ``NaN`` / ``Infinity``, and
the reconciler's disagreement test (``abs(a - b) > tol``) is False for NaN,
so a non-finite value is dropped as "not published" rather than chosen
silently. A sub-field of the wrong shape (a non-object ``gold``, ``shop`` or
Meraki stat) reads as absent.

Preference order is official API first: Data Dragon is Riot's own static data
(version-pinned URLs); Meraki is a community-extracted JSON feed ("latest"
only); the League wiki is read through ONE request for the raw
``Module:ChampionData/data`` table - never page scraping - with an identifying
User-Agent, at most one request per run, and the shared client's per-host rate
gate (1 request per second). Since ruling 51 (``RM962-S146-R51``, RM-1227)
``lib.game_data.fetch`` requests the wiki url only when ``lib.wiki_consent``
finds a consent record; otherwise the wiki source is excluded and the refusal
recorded. ``_wiki_parse`` itself is unchanged and still parses a supplied body.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from lib.game_data.lua_text import block_end, champion_blocks

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
_DDRAGON_DATA = "https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/{name}.json"
_MERAKI = "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/{name}.json"
_WIKI_MODULE = "https://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw"


class SourceParseError(ValueError):
    """A source body did not have the shape the parser requires."""


@dataclass(frozen=True)
class Source:
    id: str
    kind: str  # official | community | wiki
    era_addressable: bool
    terms: str
    urls: Callable[[str], Mapping[str, str]]
    parse: Callable[[Mapping[str, bytes]], dict]


def _body(bodies: Mapping[str, bytes], name: str, what: str) -> bytes:
    """The raw bytes of body ``name``, or ``SourceParseError`` naming ``what``."""
    if not isinstance(bodies, Mapping) or name not in bodies:
        raise SourceParseError(f"{what}: body missing")
    body = bodies[name]
    if not isinstance(body, (bytes, bytearray)):
        raise SourceParseError(f"{what}: body is not bytes ({type(body).__name__})")
    return bytes(body)


def _json(body: bytes, what: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise SourceParseError(f"{what}: not JSON ({exc.__class__.__name__})") from None


def _num(v: Any) -> float | None:
    """``v`` when it is a finite int / float (never a bool), else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _obj(v: Any) -> Mapping:
    """``v`` when it is an object, else an empty one (a sub-field read as absent)."""
    return v if isinstance(v, dict) else {}


def _entry_stats(entry: Any, what: str, eid: str) -> Mapping:
    """The ``stats`` object of one roster entry; a missing / null / ``[]`` one is empty.

    An entry that is not an object, or a ``stats`` that is present but not an
    object, is a malformed body: ``SourceParseError``.
    """
    if not isinstance(entry, dict):
        raise SourceParseError(f"{what}: entry {eid!r} is not an object")
    stats = entry.get("stats")
    if stats is None or stats == []:
        return {}  # absent, null, or an empty object serialised as ``[]``
    if not isinstance(stats, dict):
        raise SourceParseError(f"{what}: entry {eid!r} stats is not an object")
    return stats


# ------------------------------------------------------------------ ddragon

_DD_CHAMP = {
    "hp": "hp", "hp_per_level": "hpperlevel", "armor": "armor", "armor_per_level": "armorperlevel",
    "mr": "spellblock", "mr_per_level": "spellblockperlevel", "ad": "attackdamage",
    "ad_per_level": "attackdamageperlevel", "attack_speed": "attackspeed",
    "as_per_level": "attackspeedperlevel", "move_speed": "movespeed", "attack_range": "attackrange",
}
_DD_ITEM_STATS = {
    "ad": "FlatPhysicalDamageMod", "ap": "FlatMagicDamageMod", "armor": "FlatArmorMod",
    "mr": "FlatSpellBlockMod", "hp": "FlatHPPoolMod",
}


def _ddragon_parse(bodies: Mapping[str, bytes]) -> dict:
    c_what, i_what = "ddragon champion.json", "ddragon item.json"
    champ = _json(_body(bodies, "champion", c_what), c_what)
    item = _json(_body(bodies, "item", i_what), i_what)
    if not isinstance(champ, dict) or not isinstance(champ.get("data"), dict):
        raise SourceParseError(f"{c_what}: no data map")
    if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
        raise SourceParseError(f"{i_what}: no data map")
    champions = {}
    for cid, c in champ["data"].items():
        stats = _entry_stats(c, c_what, cid)
        row = {f: _num(stats.get(k)) for f, k in _DD_CHAMP.items()}
        champions[cid] = {k: v for k, v in row.items() if v is not None}
    items = {}
    for iid, it in item["data"].items():
        stats = _entry_stats(it, i_what, iid)
        # DDragon lists only an item's non-zero stats, so an unlisted one is 0.
        row = {f: _num(stats.get(k, 0)) for f, k in _DD_ITEM_STATS.items()}
        gold = _num(_obj(it.get("gold")).get("total"))
        if gold is not None:
            row["gold_total"] = gold
        items[iid] = {k: v for k, v in row.items() if v is not None}
    version = champ.get("version")
    return {"champions": champions, "items": items, "version": version if isinstance(version, str) else None}


def _ddragon_urls(version: str) -> dict:
    return {n: _DDRAGON_DATA.format(v=version, name=n) for n in ("champion", "item")}


# ------------------------------------------------------------------ meraki

_MK_CHAMP = {
    "hp": ("health", "flat"), "hp_per_level": ("health", "perLevel"),
    "armor": ("armor", "flat"), "armor_per_level": ("armor", "perLevel"),
    "mr": ("magicResistance", "flat"), "mr_per_level": ("magicResistance", "perLevel"),
    "ad": ("attackDamage", "flat"), "ad_per_level": ("attackDamage", "perLevel"),
    "attack_speed": ("attackSpeed", "flat"), "as_per_level": ("attackSpeed", "perLevel"),
    "as_ratio": ("attackSpeedRatio", "flat"), "move_speed": ("movespeed", "flat"),
    "attack_range": ("attackRange", "flat"),
}
_MK_ITEM = {"ad": "attackDamage", "ap": "abilityPower", "armor": "armor", "mr": "magicResistance", "hp": "health"}


def _meraki_parse(bodies: Mapping[str, bytes]) -> dict:
    c_what, i_what = "meraki champions.json", "meraki items.json"
    champs = _json(_body(bodies, "champions", c_what), c_what)
    items = _json(_body(bodies, "items", i_what), i_what)
    if not isinstance(champs, dict) or not isinstance(items, dict):
        raise SourceParseError("meraki: top level is not an object")
    out_c = {}
    for cid, c in champs.items():
        stats = c.get("stats") if isinstance(c, dict) else None
        if not isinstance(stats, dict):
            raise SourceParseError(f"{c_what}: {cid} has no stats")
        row = {}
        for f, (k, sub) in _MK_CHAMP.items():
            v = _num(_obj(stats.get(k)).get(sub))
            if v is not None:
                row[f] = v
        out_c[cid] = row
    out_i = {}
    for iid, it in items.items():
        # A non-object or removed item is skipped (Meraki keeps retired rows).
        if not isinstance(it, dict) or it.get("removed"):
            continue
        stats = _obj(it.get("stats"))
        row = {f: _num(_obj(stats.get(k)).get("flat")) for f, k in _MK_ITEM.items()}
        total = _num(_obj(_obj(it.get("shop")).get("prices")).get("total"))
        if total is not None:
            row["gold_total"] = total
        out_i[str(iid)] = {k: v for k, v in row.items() if v is not None}
    return {"champions": out_c, "items": out_i, "version": None}


def _meraki_urls(_version: str) -> dict:
    return {n: _MERAKI.format(name=n) for n in ("champions", "items")}


# ------------------------------------------------------------------ wiki

_WIKI_CHAMP = {
    "hp": "hp_base", "hp_per_level": "hp_lvl", "armor": "arm_base", "armor_per_level": "arm_lvl",
    "mr": "mr_base", "mr_per_level": "mr_lvl", "ad": "dam_base", "ad_per_level": "dam_lvl",
    "attack_speed": "as_base", "as_per_level": "as_lvl", "as_ratio": "as_ratio",
    "move_speed": "ms", "attack_range": "range",
}
_SCALAR = re.compile(r'^\s*\["([a-z0-9_]+)"\]\s*=\s*(-?\d+(?:\.\d+)?)\s*,?\s*$', re.MULTILINE)
_STATS_OPEN = re.compile(r'\["stats"\]\s*=\s*\{')


def _depth_one(inner: str) -> str:
    """``inner`` with every nested ``{...}`` table removed, braces included.

    Only the stats block's own scalars survive; a mode table (``["aram"] =
    {...}``) at any nesting depth, whatever its key, never contributes a line
    to ``_SCALAR`` - its ``["hp_base"]`` used to override the base stat when
    it came later, and a key with a digit escaped the old strip regex.
    """
    out = []
    depth = 0
    for ch in inner:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(depth - 1, 0)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _wiki_parse(bodies: Mapping[str, bytes]) -> dict:
    what = "wiki ChampionData"
    try:
        text = _body(bodies, "module", what).decode("utf-8")
    except UnicodeDecodeError:
        raise SourceParseError(f"{what}: not UTF-8") from None
    if "return {" not in text:
        raise SourceParseError("wiki ChampionData: not a Lua data table")
    # RM-787 (the RM-600 rule): comments stripped first, so a trailing
    # ``--note`` no longer hides a scalar from the end-anchored _SCALAR (Gnar's
    # range), and Kled's primary record (id 240) wins over "Kled & Skaarl".
    try:
        entries = champion_blocks(text)
    except ValueError:
        raise SourceParseError("wiki ChampionData: unbalanced braces") from None
    champions = {}
    for apiname, entry in entries.items():
        m = _STATS_OPEN.search(entry)
        if m is None:
            continue
        open_idx = m.end() - 1
        try:
            close = block_end(entry, open_idx)
        except ValueError:
            raise SourceParseError(f"{what}: unbalanced braces") from None
        # Only depth-1 scalars of the stats block: drop nested mode tables.
        flat = _depth_one(entry[open_idx + 1: close - 1])
        scal = {k: float(v) for k, v in _SCALAR.findall(flat)}
        row = {}
        for f, k in _WIKI_CHAMP.items():
            v = scal.get(k)
            if v is None or not math.isfinite(v):
                continue  # absent, or a digit run that overflows to inf
            row[f] = int(v) if v.is_integer() else v
        champions[apiname] = row
    if not champions:
        raise SourceParseError("wiki ChampionData: no champion entries parsed")
    return {"champions": champions, "items": {}, "version": None}


def _wiki_urls(_version: str) -> dict:
    return {"module": _WIKI_MODULE}


SOURCES: tuple[Source, ...] = (
    Source(
        "ddragon", "official", True,
        "Riot Data Dragon static data; version-pinned URLs; public CDN.",
        _ddragon_urls, _ddragon_parse,
    ),
    Source(
        "wiki", "wiki", False,
        "League wiki raw Module:ChampionData (CC BY-SA); ONE request per run, identifying UA, "
        "rate-gated; numbers only are kept, never page text.",
        _wiki_urls, _wiki_parse,
    ),
    Source(
        "meraki", "community", False,
        "Meraki Analytics community-extracted JSON; 'latest' only (not era-addressable).",
        _meraki_urls, _meraki_parse,
    ),
)


def parse_versions(body: bytes) -> list[str]:
    """The DDragon version feed, newest first; ``versions[0]`` becomes the patch.

    Every entry must be a non-blank string with no surrounding whitespace: an
    empty or padded entry would be spliced into a CDN url (``cdn//data``) and a
    cache directory name.
    """
    what = "ddragon versions.json"
    if not isinstance(body, (bytes, bytearray)):
        raise SourceParseError(f"{what}: body is not bytes ({type(body).__name__})")
    versions = _json(bytes(body), what)
    if not isinstance(versions, list) or not versions or not all(
        isinstance(v, str) and v and v == v.strip() for v in versions
    ):
        raise SourceParseError(f"{what}: not a non-empty list of non-blank, unpadded strings")
    return versions
