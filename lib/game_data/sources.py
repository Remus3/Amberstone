"""Game-data sources for the reconciliation pipeline (P1-4).

Each source declares where its bodies live for a patch, whether it is
ERA-ADDRESSABLE (can serve an old patch's tables) and the terms it is used
under, and parses its bodies into one normalised shape:

    {"champions": {ddragon_id: {field: number}}, "items": {item_id: {field: number}}}

Field names are the pipeline's own (``lib.game_data.build.CHAMPION_FIELDS`` /
``ITEM_FIELDS``); a source that does not publish a field simply omits it.

Preference order is official API first: Data Dragon is Riot's own static data
(version-pinned URLs); Meraki is a community-extracted JSON feed ("latest"
only); the League wiki is read through ONE request for the raw
``Module:ChampionData/data`` table - never page scraping - with an identifying
User-Agent, at most one request per run, and the shared client's per-host rate
gate (1 request per second).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

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


def _json(body: bytes, what: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SourceParseError(f"{what}: not JSON ({exc.__class__.__name__})") from None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


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
    champ = _json(bodies["champion"], "ddragon champion.json")
    item = _json(bodies["item"], "ddragon item.json")
    if not isinstance(champ, dict) or not isinstance(champ.get("data"), dict):
        raise SourceParseError("ddragon champion.json: no data map")
    if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
        raise SourceParseError("ddragon item.json: no data map")
    champions = {}
    for cid, c in champ["data"].items():
        stats = c.get("stats") or {}
        champions[cid] = {f: _num(stats.get(k)) for f, k in _DD_CHAMP.items() if _num(stats.get(k)) is not None}
    items = {}
    for iid, it in item["data"].items():
        stats = it.get("stats") or {}
        row = {f: _num(stats.get(k, 0)) for f, k in _DD_ITEM_STATS.items()}
        gold = (it.get("gold") or {}).get("total")
        if _num(gold) is not None:
            row["gold_total"] = gold
        items[iid] = {k: v for k, v in row.items() if v is not None}
    return {"champions": champions, "items": items, "version": champ.get("version")}


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
    champs = _json(bodies["champions"], "meraki champions.json")
    items = _json(bodies["items"], "meraki items.json")
    if not isinstance(champs, dict) or not isinstance(items, dict):
        raise SourceParseError("meraki: top level is not an object")
    out_c = {}
    for cid, c in champs.items():
        stats = (c or {}).get("stats") if isinstance(c, dict) else None
        if not isinstance(stats, dict):
            raise SourceParseError(f"meraki champions.json: {cid} has no stats")
        row = {}
        for f, (k, sub) in _MK_CHAMP.items():
            v = _num((stats.get(k) or {}).get(sub))
            if v is not None:
                row[f] = v
        out_c[cid] = row
    out_i = {}
    for iid, it in items.items():
        if not isinstance(it, dict) or it.get("removed"):
            continue
        stats = it.get("stats") or {}
        row = {f: _num((stats.get(k) or {}).get("flat")) for f, k in _MK_ITEM.items()}
        total = _num(((it.get("shop") or {}).get("prices") or {}).get("total"))
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
_ENTRY = re.compile(r'^  \["[^"]+"\] = \{', re.M)
_APINAME = re.compile(r'\["apiname"\]\s*=\s*"([^"]+)"')
_SCALAR = re.compile(r'^\s*\["([a-z0-9_]+)"\]\s*=\s*(-?\d+(?:\.\d+)?)\s*,?\s*$', re.M)


def _block(text: str, open_idx: int) -> str:
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx: i + 1]
    raise SourceParseError("wiki ChampionData: unbalanced braces")


def _wiki_parse(bodies: Mapping[str, bytes]) -> dict:
    try:
        text = bodies["module"].decode("utf-8")
    except UnicodeDecodeError:
        raise SourceParseError("wiki ChampionData: not UTF-8") from None
    if "return {" not in text:
        raise SourceParseError("wiki ChampionData: not a Lua data table")
    champions = {}
    for m in _ENTRY.finditer(text):
        entry = _block(text, text.index("{", m.start()))
        api = _APINAME.search(entry)
        si = entry.find('["stats"] = {')
        if api is None or si < 0:
            continue
        stats_blk = _block(entry, entry.index("{", si))
        # Only depth-1 scalars of the stats block: drop nested mode tables.
        flat = re.sub(r'\["[a-z_]+"\]\s*=\s*\{[^{}]*\},?', "", stats_blk[1:-1])
        scal = {k: float(v) for k, v in _SCALAR.findall(flat)}
        row = {}
        for f, k in _WIKI_CHAMP.items():
            if k in scal:
                v = scal[k]
                row[f] = int(v) if v.is_integer() else v
        champions[api.group(1)] = row
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
    versions = _json(body, "ddragon versions.json")
    if not isinstance(versions, list) or not versions or not all(isinstance(v, str) for v in versions):
        raise SourceParseError("ddragon versions.json: not a non-empty list of strings")
    return versions
