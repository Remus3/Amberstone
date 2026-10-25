"""Set-agnostic CommunityDragon TFT ingest (RM-840).

Reads raw.communitydragon.org/<branch>/cdragon/tft/en_us.json (about 24 MB,
every set) and writes a REDUCED extract for one set to
data/meta/tft_set<N>_cdragon.json - champions, costs, traits + breakpoints,
items and augments. Never the raw payload.

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
import json
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
          "role": c.get("role")}
         for c in champs if c.get("traits")),
        key=lambda u: (u["cost"] if isinstance(u["cost"], int) else 99,
                       u["name"], u["apiName"]),
    )
    unit_costs: dict = {}
    unit_traits: dict = {}
    for u in units:
        unit_costs.setdefault(u["name"], u["cost"])
        unit_traits[u["name"]] = _unique(unit_traits.get(u["name"], []) + u["traits"])

    traits = sorted(
        ({"apiName": _text(t.get("apiName")), "name": _text(t.get("name")),
          "breakpoints": [e.get("minUnits") for e in t.get("effects") or []
                          if isinstance(e, dict)],
          "desc": _text(t.get("desc"))}
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
            e = {"apiName": _text(api), "name": _text(it.get("name")),
                 "desc": _text(it.get("desc"))}
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
                 "are counted in _counts.champions_raw but not listed.",
        "_counts": {"champions_raw": len(champs), "units": len(units),
                    "champions": len(champions), "traits": len(traits),
                    "items": len(items), "augments": len(augments)},
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
