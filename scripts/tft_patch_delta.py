"""What changed in one TFT set between two CommunityDragon patch directories (RM-894).

Diffs two RAW raw.communitydragon.org/<dir>/cdragon/tft/en_us.json payloads
for one set mutator (default TFTSet18) and writes a CLIENT-FILE DELTA, not
patch notes: every unit stat / cost / trait list, trait breakpoint, augment
and item effect the game files carry, including changes the official notes
leave out, and nothing the files do not carry. Current-set ability numbers are
absent from every CDragon source (BACKLOG RM-894 cycle 6 closed negative), so
the output says so in `ability_values` rather than reporting "no change".

    python scripts/tft_patch_delta.py 16.20 16.21
    python scripts/tft_patch_delta.py latest pbe --mutator TFTSet18
    python scripts/tft_patch_delta.py 16.20 16.21 --old-source a.json --new-source b.json

A directory is `latest`, `pbe` or a numbered patch directory (`16.21`);
anything else is refused before any fetch or path is built. Reads go through
scripts/fetch_cdragon_tft.py `_http_get`. A numbered directory never changes,
so its raw payload is cached under the gitignored data/tft/cdragon_raw/; a
moving branch is re-read every run. The delta goes to the gitignored
data/tft/patch_delta/, never to tracked data/meta/ (the tree tracks reduced
extracts only). Values are the payload's own, verbatim (float32 noise such as
0.8500000238418579 kept); hashed trait keys are passed through verbatim, never
renamed or guessed. Display use is pre-game or post-game only (RM-892).

Data terms: CommunityDragon, credited in NOTICE ("CommunityDragon (CDragon)");
no third-party stat or patch-note site.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import fetch_cdragon_tft as fct  # noqa: E402

DEFAULT_MUTATOR = "TFTSet18"
BRANCHES = fct.BRANCHES
SECTIONS = ("units", "traits", "augments", "items")
ABILITY_NOT_CARRIED = "not carried by source"
DEFAULT_CACHE = ROOT / "data" / "tft" / "cdragon_raw"
# A numbered patch directory; [0-9] so no non-ASCII digit passes.
_PATCH_DIR_RE = re.compile(r"[0-9]{1,2}\.[0-9]{1,2}")
# A mutator becomes an output file-name segment, so it is held to this.
_MUTATOR_RE = re.compile(r"[A-Za-z0-9_]{1,64}")
_NOTE = ("Client-file delta between two CommunityDragon payloads, not patch "
         "notes: it lists what the game files changed (unit stats, costs and "
         "traits, trait breakpoints, augment and item effects and text), "
         "including changes the official notes omit, and cannot show what the "
         "files do not carry (see ability_values). Values verbatim; hashed "
         "keys verbatim, never renamed.")


def check_directory(directory) -> str:
    if isinstance(directory, str) and (directory in BRANCHES
                                       or _PATCH_DIR_RE.fullmatch(directory)):
        return directory
    raise ValueError(f"directory must be one of {BRANCHES} or a numbered patch "
                     f"directory such as 16.21, got {directory!r}")


def check_mutator(mutator) -> str:
    if isinstance(mutator, str) and _MUTATOR_RE.fullmatch(mutator):
        return mutator
    raise ValueError(f"mutator must match {_MUTATOR_RE.pattern}, got {mutator!r}")


def patch_url(directory) -> str:
    return f"{fct.CDRAGON_BASE}/{check_directory(directory)}/cdragon/tft/en_us.json"


def patch_metadata_url(directory) -> str:
    return f"{fct.CDRAGON_BASE}/{check_directory(directory)}/content-metadata.json"


def default_out(mutator: str, old: str, new: str, root: Path = ROOT) -> Path:
    return (Path(root) / "data" / "tft" / "patch_delta"
            / f"{check_mutator(mutator)}_{check_directory(old)}_{check_directory(new)}.json")


def _value(v):
    """JSON-safe comparable form: nan / inf / bools-as-numbers never leak."""
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _value(x) for k, x in v.items()}
    if isinstance(v, str):
        return fct._text(v)
    if v is None or isinstance(v, bool):
        return v
    return fct._number(v)


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _rows(v) -> list:
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _strs(v) -> list:
    return [fct._text(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _delta(old: dict, new: dict) -> dict:
    """{key: {"old", "new"}} for every key whose value differs (absent = None)."""
    out = {}
    for k in sorted(set(old) | set(new), key=str):
        a, b = _value(old.get(k)), _value(new.get(k))
        if a != b:
            out[str(k)] = {"old": a, "new": b}
    return out


def _by_api(rows) -> dict:
    out: dict = {}
    for r in _rows(rows):
        api = fct._text(r.get("apiName"))
        if api:
            out.setdefault(api, r)
    return out


def _set_row(raw, mutator: str):
    for r in _rows(_dict(raw).get("setData")):
        if r.get("mutator") == mutator:
            return r
    return None


def _ability_vars(champ: dict) -> dict:
    return fct._ability(champ.get("ability"))["variables"]


def _unit_entry(a: dict, b: dict) -> dict:
    e = {}
    if _value(a.get("cost")) != _value(b.get("cost")):
        e["cost"] = {"old": _value(a.get("cost")), "new": _value(b.get("cost"))}
    if _strs(a.get("traits")) != _strs(b.get("traits")):
        e["traits"] = {"old": _strs(a.get("traits")), "new": _strs(b.get("traits"))}
    stats = _delta(_dict(a.get("stats")), _dict(b.get("stats")))
    if stats:
        e["stats"] = stats
    ability = _delta(_ability_vars(a), _ability_vars(b))
    if ability:
        e["ability"] = ability
    return e


def _breakpoints(a: dict, b: dict) -> list:
    ea, eb = _rows(a.get("effects")), _rows(b.get("effects"))
    out = []
    for i in range(max(len(ea), len(eb))):
        x = ea[i] if i < len(ea) else None
        y = eb[i] if i < len(eb) else None
        cur = y if y is not None else x
        entry = {"index": i, "minUnits": _value(cur.get("minUnits")),
                 "maxUnits": _value(cur.get("maxUnits"))}
        if x is None:
            entry["added"] = True
        elif y is None:
            entry["removed"] = True
        else:
            bounds = _delta({k: x.get(k) for k in ("minUnits", "maxUnits")},
                            {k: y.get(k) for k in ("minUnits", "maxUnits")})
            if bounds:
                entry["bounds"] = bounds
        variables = _delta(_dict((x or {}).get("variables")), _dict((y or {}).get("variables")))
        if variables:
            entry["variables"] = variables
        if len(entry) > 3:
            out.append(entry)
    return out


def _trait_entry(a: dict, b: dict) -> dict:
    e = {}
    bps = _breakpoints(a, b)
    if bps:
        e["breakpoints"] = bps
    if fct._text(a.get("desc")) != fct._text(b.get("desc")):
        e["desc"] = {"old": fct._text(a.get("desc")), "new": fct._text(b.get("desc"))}
    return e


def _item_entry(a: dict, b: dict) -> dict:
    e = {}
    effects = _delta(_dict(a.get("effects")), _dict(b.get("effects")))
    if effects:
        e["effects"] = effects
    if fct._text(a.get("desc")) != fct._text(b.get("desc")):
        e["desc"] = {"old": fct._text(a.get("desc")), "new": fct._text(b.get("desc"))}
    return e


def _section(old: dict, new: dict, entry) -> tuple[dict, list, list]:
    changed = {}
    for api in sorted(set(old) & set(new)):
        e = entry(old[api], new[api])
        if e:
            changed[api] = e
    return changed, sorted(set(new) - set(old)), sorted(set(old) - set(new))


def _ability_note(old_units: dict, new_units: dict) -> str:
    apis = set(old_units) | set(new_units)
    carried = sum(1 for api in apis
                  if _ability_vars(old_units.get(api, {})) or _ability_vars(new_units.get(api, {})))
    if not carried:
        return ABILITY_NOT_CARRIED
    return f"carried for {carried} of {len(apis)} units; the rest {ABILITY_NOT_CARRIED}"


def _skeleton(mutator, old_label, new_label, old_version, new_version) -> dict:
    return {
        "_kind": "client_file_delta",
        "_mutator": mutator,
        "_old": {"directory": old_label, "content_version": old_version},
        "_new": {"directory": new_label, "content_version": new_version},
        "_source": "CommunityDragon cdragon/tft/en_us.json (game data mirror; "
                   "terms: CommunityDragon's, Riot's underneath - see NOTICE)",
        "_note": _NOTE,
        "ability_values": ABILITY_NOT_CARRIED,
        "reason": None,
        "_counts": {k: 0 for k in SECTIONS + ("added", "removed")},
        **{k: {} for k in SECTIONS},
        "added": {k: [] for k in SECTIONS},
        "removed": {k: [] for k in SECTIONS},
    }


def diff_set(old_raw, new_raw, mutator: str = DEFAULT_MUTATOR, *, old_label=None,
             new_label=None, old_version=None, new_version=None) -> dict:
    """Delta of one set mutator between two raw payloads. Never raises: a
    payload without the mutator (or not a payload) gives an empty delta whose
    `reason` says which side lacked it."""
    d = _skeleton(mutator, old_label, new_label, old_version, new_version)
    rows = {"old": _set_row(old_raw, mutator), "new": _set_row(new_raw, mutator)}
    missing = [side for side, row in rows.items() if row is None]
    if missing:
        d["reason"] = f"mutator {mutator} not in the {' and '.join(missing)} payload"
        return d
    try:
        a, b = rows["old"], rows["new"]
        units = (_by_api(a.get("champions")), _by_api(b.get("champions")))
        items = (_by_api(_dict(old_raw).get("items")), _by_api(_dict(new_raw).get("items")))
        sections = {
            "units": _section(*units, _unit_entry),
            "traits": _section(_by_api(a.get("traits")), _by_api(b.get("traits")), _trait_entry),
        }
        for key in ("augments", "items"):
            sections[key] = _section({api: _dict(items[0].get(api)) for api in _strs(a.get(key))},
                                     {api: _dict(items[1].get(api)) for api in _strs(b.get(key))},
                                     _item_entry)
        for key, (changed, added, removed) in sections.items():
            d[key] = changed
            d["added"][key] = added
            d["removed"][key] = removed
            d["_counts"][key] = len(changed)
        d["_counts"]["added"] = sum(len(v) for v in d["added"].values())
        d["_counts"]["removed"] = sum(len(v) for v in d["removed"].values())
        d["ability_values"] = _ability_note(*units)
    except (TypeError, ValueError, AttributeError) as exc:  # malformed payload
        reasoned = _skeleton(mutator, old_label, new_label, old_version, new_version)
        reasoned["reason"] = f"malformed payload: {type(exc).__name__}"
        return reasoned
    return d


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _version(meta_bytes) -> str | None:
    try:
        meta = json.loads(meta_bytes.decode("utf-8"))
    except (AttributeError, ValueError):
        return None
    v = meta.get("version") if isinstance(meta, dict) else None
    return v if isinstance(v, str) else None


def load_payload(directory: str, *, cache_dir: Path = DEFAULT_CACHE) -> tuple:
    """(raw payload, content version) for one directory; a numbered directory
    is read from / written to the cache, a moving branch is always fetched."""
    d = check_directory(directory)
    numbered = d not in BRANCHES
    cache = Path(cache_dir) / d
    raw_path, meta_path = cache / "en_us.json", cache / "content-metadata.json"
    if numbered and raw_path.is_file():
        raw_bytes = raw_path.read_bytes()
        meta_bytes = meta_path.read_bytes() if meta_path.is_file() else None
    else:
        raw_bytes = fct._http_get(patch_url(d))
        try:
            meta_bytes = fct._http_get(patch_metadata_url(d))
        except (OSError, ValueError):
            meta_bytes = None
        if numbered:
            cache.mkdir(parents=True, exist_ok=True)
            _write_bytes_atomic(raw_path, raw_bytes)
            if meta_bytes is not None:
                _write_bytes_atomic(meta_path, meta_bytes)
    return json.loads(raw_bytes.decode("utf-8")), _version(meta_bytes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old", help="latest, pbe or a patch directory such as 16.20")
    ap.add_argument("new", help="latest, pbe or a patch directory such as 16.21")
    ap.add_argument("--mutator", default=DEFAULT_MUTATOR)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--old-source", type=Path, default=None,
                    help="read a local en_us.json for OLD instead of the network")
    ap.add_argument("--new-source", type=Path, default=None,
                    help="read a local en_us.json for NEW instead of the network")
    args = ap.parse_args(argv)
    try:
        old, new = check_directory(args.old), check_directory(args.new)
        mutator = check_mutator(args.mutator)
        loaded = []
        for directory, source in ((old, args.old_source), (new, args.new_source)):
            if source is not None:
                loaded.append((json.loads(Path(source).read_bytes().decode("utf-8")), None))
            else:
                loaded.append(load_payload(directory, cache_dir=args.cache_dir))
        delta = diff_set(loaded[0][0], loaded[1][0], mutator, old_label=old, new_label=new,
                         old_version=loaded[0][1], new_version=loaded[1][1])
        target = args.out if args.out is not None else default_out(mutator, old, new)
        target.parent.mkdir(parents=True, exist_ok=True)
        fct.write_atomic(target, delta)
    except (OSError, ValueError) as exc:
        print(f"tft_patch_delta: {exc}", file=sys.stderr)
        return 1
    c = delta["_counts"]
    print(f"{mutator} {old} -> {new}: changed {c['units']} units, {c['traits']} traits, "
          f"{c['augments']} augments, {c['items']} items; added {c['added']}, "
          f"removed {c['removed']} -> {target}")
    if delta["reason"]:
        print(f"tft_patch_delta: {delta['reason']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
