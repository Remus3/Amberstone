"""Set-agnostic CommunityDragon TFT ingest (RM-840).

Reads raw.communitydragon.org/<branch>/cdragon/tft/en_us.json (about 24 MB,
every set) and writes a REDUCED extract for one set to
data/meta/tft_set<N>_cdragon.json - champions, costs, traits + breakpoints,
items and augments. Never the raw payload.

Numbers are kept, not just words (RM-891): augment and item `desc`
placeholders (`@Gold@`, `@AS*100@`) are filled from the row's own `effects` by
name (exact, then case-folded, then the FNV-1a bin hash of the name); units keep
`stats` and their ability variables; traits keep each breakpoint's variables,
with a hashed key renamed only when the trait's own desc names a placeholder
whose hash equals it. A placeholder with no value in the payload (runtime
counters such as `@TFTUnitProperty.item:...@`) stays in the text verbatim, never
guessed; `_placeholders` records the total and resolved count per kind.

    python scripts/fetch_cdragon_tft.py --set 18
    python scripts/fetch_cdragon_tft.py --set 17 --branch pbe
    python scripts/fetch_cdragon_tft.py --set 18 --source <local en_us.json>

The extract carries the key shapes the TFT lane already reads out of
data/meta/tft_set17_meta.json (champions / unit_costs / unit_traits /
all_traits) so tft/tft_set.py can read a roster off either file.

Data terms: CommunityDragon mirrors Riot game files and publishes no licence
of its own; the data stays governed by CDragon's terms and Riot's underneath
them (NOTICE, "CommunityDragon (CDragon)"). Only game data goes in the
extract - comps and tier lists from third-party sites stay out of the repo.

Writes are atomic (tmp then replace), 7-bit ASCII (non-ASCII escaped) and
LF-only. Superseded one-off: scripts/fetch_cdragon_pbe.py (Set 17 only).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import decimal
import json
import math
import re
import sys
import time
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parent.parent
CDRAGON_BASE = "https://raw.communitydragon.org"
BRANCHES = ("latest", "pbe")
USER_AGENT = "Amberstone/fetch-cdragon-tft/1.0"
DEFAULT_TIMEOUT = 120.0
RETRY_BACKOFFS = (2.0, 5.0)
TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
# Invisible formatting characters CDragon text sometimes carries.
_STRIP_CHARS = dict.fromkeys((0x200B, 0xFEFF), None)  # ZWSP, BOM


def tft_url(branch: str) -> str:
    return f"{CDRAGON_BASE}/{branch}/cdragon/tft/en_us.json"


def metadata_url(branch: str) -> str:
    return f"{CDRAGON_BASE}/{branch}/content-metadata.json"


def default_out(set_number: int, root: Path = ROOT) -> Path:
    return Path(root) / "data" / "meta" / f"tft_set{int(set_number)}_cdragon.json"


def _http_get(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """GET with the retry idiom of tools/upstream_drift_check.py._http_get."""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(len(RETRY_BACKOFFS) + 1):
        req = urllib_request.Request(url, headers=headers, method="GET")
        try:
            with urllib_request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib_error.HTTPError as e:
            if e.code in TRANSIENT_HTTP_CODES and attempt < len(RETRY_BACKOFFS):
                time.sleep(RETRY_BACKOFFS[attempt])
                continue
            raise
        except urllib_error.URLError:
            if attempt < len(RETRY_BACKOFFS):
                time.sleep(RETRY_BACKOFFS[attempt])
                continue
            raise
    raise RuntimeError("unreachable")


# No whitespace inside: a stray single `@` in prose must not pair with the next
# placeholder's opening `@` and swallow it.
_PLACEHOLDER_RE = re.compile(r"@([^@\s]*)@")


def bin_hash(name: str) -> str:
    """CDragon's hashed-key form: FNV-1a 32 of the lower-cased name, `{%08x}`."""
    h = 0x811C9DC5
    for b in str(name).lower().encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return "{" + format(h, "08x") + "}"


# Past 1e15 a value (or a product) no longer prints exactly through a float;
# game values never get near it, so such a value stays unresolved.
_MAX_MAGNITUDE = 10 ** 15
# CDragon multipliers are short (`*100`); bounded so a product is exact.
_MULTIPLIER_RE = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9})?")
# repr of a float carries at most 17 significant digits and a multiplier 18,
# so 40 digits hold every product exactly (the default context rounds at 28).
_EXACT = decimal.Context(prec=40)
_SIX = decimal.Context(prec=6)  # six significant digits, round half even


def _number(value):
    """A finite real number, or None (bools, strings, nan, inf are not values)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if abs(value) <= _MAX_MAGNITUDE else None


def _clean_value(value):
    """A number, or a list of numbers, made JSON-safe (a bad entry -> None)."""
    if isinstance(value, list):
        return [_number(v) for v in value]
    return _number(value)


def _fmt_number(value) -> str:
    """One rounding, from the payload's own decimal text (a float's shortest
    repr, or the exact Decimal product of it and a multiplier): six significant
    digits under 1e5, so float32 noise such as 3.999996 or 10.000002 reads as
    the game shows it; exact at or above 1e5; ints exact; never rounded to 0."""
    if isinstance(value, int):
        return str(value)
    d = value if isinstance(value, decimal.Decimal) else decimal.Decimal(repr(value))
    return _decimal_text(d if abs(d) >= 100000 else _SIX.plus(d))


def _decimal_text(d: decimal.Decimal) -> str:
    """Plain text for a Decimal, trailing zeros dropped, never rounded."""
    if d == 0:
        return "0"
    if d.adjusted() < -6:
        mantissa, _, exp = format(d, "e").partition("e")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}e{exp}"
    text = format(d, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _lookup(name: str, values: dict):
    """Value for a placeholder name: exact key, case-folded key, bin hash."""
    if name in values:
        return _number(values[name])
    folded = [v for k, v in values.items() if str(k).lower() == name.lower()]
    if len(folded) > 1:
        return None  # two keys differ only in case: ambiguous, never guessed
    if folded:
        return _number(folded[0])
    if bin_hash(name) in values:
        return _number(values[bin_hash(name)])
    return None


def _resolve(text: str, values: dict, tally: dict) -> str:
    """Fill `@Name@` / `@Name*K@` from values; leave the rest verbatim."""
    def _sub(m):
        tally["total"] += 1
        name, star, mult = m.group(1).partition("*")
        value = _lookup(name, values) if name else None
        if star and not _MULTIPLIER_RE.fullmatch(mult):
            value = None
        if value is not None and star:
            # Decimal from the value's shortest repr times the multiplier as
            # written: binary float would print 1234567 * 0.1 as 123456.70000000001.
            product = _EXACT.multiply(decimal.Decimal(repr(value)), decimal.Decimal(mult))
            value = product if abs(product) <= _MAX_MAGNITUDE else None
        if value is None:
            return m.group(0)
        tally["resolved"] += 1
        return _fmt_number(value)
    return _PLACEHOLDER_RE.sub(_sub, text)


def _ability(raw) -> dict:
    ab = raw if isinstance(raw, dict) else {}
    rows = ab.get("variables") if isinstance(ab.get("variables"), list) else []
    variables = {}
    for v in rows:
        if isinstance(v, dict) and isinstance(v.get("name"), str) and v["name"]:
            variables[_text(v["name"])] = _clean_value(v.get("value"))
    return {"name": _text(ab.get("name")), "desc": _text(ab.get("desc")),
            "variables": variables}


def _stats(raw) -> dict:
    """Unit stats, numbers only (a nan would write a non-JSON NaN token)."""
    rows = raw if isinstance(raw, dict) else {}
    return {str(k): v for k, v in rows.items() if _number(v) is not None}


def _usable(value) -> bool:
    if isinstance(value, list):
        return any(v is not None for v in value)
    return value is not None


def _trait_key(key, by_hash: dict, variables: dict):
    """The desc's name for a hashed key, unless that name is already a key."""
    name = by_hash.get(key)
    return name if name is not None and name not in variables else key


def _trait_effects(trait: dict, tally: dict) -> list:
    """Per-breakpoint variables; a hashed key is named only by its own desc."""
    names = [m.partition("*")[0] for m in _PLACEHOLDER_RE.findall(_text(trait.get("desc")))]
    by_hash = {bin_hash(n): n for n in names if n}
    rows = [e for e in trait.get("effects") or [] if isinstance(e, dict)]
    keys = set()  # keys holding a usable value at one breakpoint at least
    out = []
    for e in rows:
        variables = e.get("variables") if isinstance(e.get("variables"), dict) else {}
        keys |= {k for k, v in variables.items() if _usable(_clean_value(v))}
        out.append({"minUnits": _number(e.get("minUnits")),
                    "maxUnits": _number(e.get("maxUnits")),
                    "variables": {_trait_key(k, by_hash, variables): _clean_value(v)
                                  for k, v in variables.items()}})
    folded = {str(k).lower() for k in keys}
    for n in names:
        tally["total"] += 1
        if n.lower() in ("minunits", "maxunits") or n.lower() in folded or bin_hash(n) in keys:
            tally["resolved"] += 1
    return out


def _text(value) -> str:
    return str(value or "").translate(_STRIP_CHARS).strip()


def _unique(seq) -> list:
    seen, out = set(), []
    for v in seq:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _base_set_row(raw: dict, n: int) -> dict:
    rows = [r for r in raw.get("setData") or [] if isinstance(r, dict)]
    for r in rows:
        if r.get("mutator") == f"TFTSet{n}":
            return r
    for r in rows:
        if r.get("number") == n:
            return r
    return {}


def build_extract(raw: dict, set_number: int, *, branch: str,
                  content_version: str | None, fetched: str) -> dict:
    n = int(set_number)
    s = (raw.get("sets") or {}).get(str(n))
    if not isinstance(s, dict):
        have = sorted((raw.get("sets") or {}), key=lambda k: (len(k), k))
        raise ValueError(f"set {n} not in CDragon payload (sets: {have})")

    champs = [c for c in s.get("champions") or [] if isinstance(c, dict)]
    units = sorted(
        ({"apiName": _text(c.get("apiName")), "name": _text(c.get("name")),
          "cost": c.get("cost"),
          "traits": [_text(t) for t in c.get("traits") or []],
          "role": c.get("role"),
          "stats": _stats(c.get("stats")),
          "ability": _ability(c.get("ability"))}
         for c in champs if c.get("traits")),
        key=lambda u: (u["cost"] if isinstance(u["cost"], int) else 99,
                       u["name"], u["apiName"]),
    )
    unit_costs: dict = {}
    unit_traits: dict = {}
    for u in units:
        unit_costs.setdefault(u["name"], u["cost"])
        unit_traits[u["name"]] = _unique(unit_traits.get(u["name"], []) + u["traits"])

    tallies = {k: {"total": 0, "resolved": 0} for k in ("augments", "items", "traits")}
    traits = sorted(
        ({"apiName": _text(t.get("apiName")), "name": _text(t.get("name")),
          "breakpoints": [e.get("minUnits") for e in t.get("effects") or []
                          if isinstance(e, dict)],
          "desc": _text(t.get("desc")),
          "effects": _trait_effects(t, tallies["traits"])}
         for t in s.get("traits") or [] if isinstance(t, dict)),
        key=lambda t: (t["name"], t["apiName"]),
    )

    row = _base_set_row(raw, n)
    by_api = {i.get("apiName"): i for i in raw.get("items") or []
              if isinstance(i, dict) and i.get("apiName")}

    def _entries(api_names, want_augment):
        out = []
        for api in sorted(set(api_names or [])):
            it = by_api.get(api)
            if not it or bool(it.get("isAugment")) != want_augment:
                continue
            effects = it.get("effects") if isinstance(it.get("effects"), dict) else {}
            tally = tallies["augments" if want_augment else "items"]
            e = {"apiName": _text(api), "name": _text(it.get("name")),
                 "desc": _resolve(_text(it.get("desc")), effects, tally)}
            if want_augment:
                e["associatedTraits"] = [_text(t) for t in it.get("associatedTraits") or []]
            else:
                e["composition"] = [_text(c) for c in it.get("composition") or []]
            out.append(e)
        return out

    items = _entries(row.get("items"), False)
    augments = _entries(row.get("augments"), True)
    champions = sorted(unit_costs)

    return {
        "_set": n,
        "_cdragon_set_name": _text(s.get("name")),
        "_mutator": _text(row.get("mutator")) or None,
        "_source": "CommunityDragon cdragon/tft/en_us.json (game data mirror; "
                   "terms: CommunityDragon's, Riot's underneath - see NOTICE)",
        "_source_url": tft_url(branch),
        "_branch": branch,
        "_content_version": content_version,
        "_fetched": fetched,
        "_note": "Reduced extract written by scripts/fetch_cdragon_tft.py. "
                 "Game data only - no third-party comps or tier lists. "
                 "units = champion rows that carry traits (shop roster plus "
                 "trait-bearing summons/variants); PvE monsters and anvils "
                 "are counted in _counts.champions_raw but not listed. "
                 "Augment / item desc placeholders are filled from the row's "
                 "effects; one left as @Name@ had no value in the payload.",
        "_counts": {"champions_raw": len(champs), "units": len(units),
                    "champions": len(champions), "traits": len(traits),
                    "items": len(items), "augments": len(augments)},
        "_placeholders": tallies,
        "champions": champions,
        "unit_costs": {k: unit_costs[k] for k in champions},
        "unit_traits": {k: unit_traits[k] for k in champions},
        "all_traits": sorted({t["name"] for t in traits if t["name"]}),
        "units": units,
        "traits": traits,
        "items": items,
        "augments": augments,
    }


def write_atomic(path: Path, obj: dict) -> None:
    """ASCII + LF bytes via tmp then replace (overlays poll mid-write)."""
    path = Path(path)
    data = (json.dumps(obj, indent=1, ensure_ascii=True) + "\n").encode("ascii")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def fetch_set(set_number: int, *, branch: str = "latest", out: Path | None = None,
              source: Path | None = None) -> Path:
    if branch not in BRANCHES:
        raise ValueError(f"branch must be one of {BRANCHES}, got {branch!r}")
    if source is not None:
        raw = json.loads(Path(source).read_bytes().decode("utf-8"))
        version = None
    else:
        raw = json.loads(_http_get(tft_url(branch)).decode("utf-8"))
        try:
            meta = json.loads(_http_get(metadata_url(branch)).decode("utf-8"))
            version = meta.get("version") if isinstance(meta, dict) else None
        except (OSError, ValueError):
            version = None
    fetched = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    extract = build_extract(raw, set_number, branch=branch,
                            content_version=version, fetched=fetched)
    target = Path(out) if out is not None else default_out(set_number)
    write_atomic(target, extract)
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", dest="set_number", type=int, required=True)
    ap.add_argument("--branch", choices=BRANCHES, default="latest")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--source", type=Path, default=None,
                    help="read a local en_us.json instead of the network")
    args = ap.parse_args(argv)
    try:
        target = fetch_set(args.set_number, branch=args.branch, out=args.out,
                           source=args.source)
    except (OSError, ValueError) as exc:
        print(f"fetch_cdragon_tft: {exc}", file=sys.stderr)
        return 1
    ex = json.loads(target.read_bytes())
    c = ex["_counts"]
    print(f"set {ex['_set']}: {c['champions']} champions ({c['champions_raw']} rows), "
          f"{c['traits']} traits, {c['items']} items, {c['augments']} augments "
          f"-> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
