"""Probe operator-captured 101.qq.com hero-rank-double payload (item 187
Slice G follow-up; ROADMAP L132).

Background: Tencent's CN-official double-rank synergy/counter data
(`https://101.qq.com/#/hero-rank-double?tier=200`) is delivered as static
JSON on the `game.gtimg.cn/images/lol/...` CDN, but the exact URL path
resists blind probing. Item 187 Slice G locked the method: operator
captures the URL + payload via Chrome DevTools on Game-PC (channel-safe
in champ-select; never in-game) and submits findings via the bridge.

THIS SCRIPT IS RUN AFTER THE OPERATOR CAPTURES (NOT BEFORE):
- The operator does the one-shot Chrome capture per
  docs/CAPTURE_101QQ_INSTRUCTIONS.md.
- The captured URL + downloaded JSON file are then handed to this script.
- The script analyzes URL structure, JSON schema shape, and DDragon-key
  compatibility, and optionally cross-references the operator's own
  smoothed-rate output for a sample champion pair from
  `data/rewind_history.db`.

DELIBERATE NON-FETCH: this script does NOT make any HTTP request. The
Tencent CDN is geo-fenced; blind fetching from Legion would fail and
the URL is unknown until the operator captures it. The script is
operator-runnable on Game-PC OR Legion after capture.

STDLIB-ONLY: argparse / json / pathlib / sqlite3 / re / sys. Zero new
dependencies. ASCII-clean per CLAUDE.md hard rule.

Usage:
  py tools/probe_101qq_hero_rank_double.py \
    --url "https://game.gtimg.cn/images/lol/act/img/js/hero-rank-double-tier200.js" \
    --json C:/path/to/captured.json
  py tools/probe_101qq_hero_rank_double.py \
    --url ... --json ... --cross-check-rewind

Exit codes:
  0 = analysis complete (whether or not patterns matched)
  1 = file-not-found or JSON-parse error
  2 = argparse error (handled by argparse)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DDRAGON_CHAMPION_JSON = _REPO_ROOT / "data" / "meta_build" / "ddragon" / "16.10.1" / "champion.json"
_REWIND_DB = _REPO_ROOT / "data" / "rewind_history.db"

# Heuristic patterns we expect to find in a Tencent CDN URL.
_PATCH_RE = re.compile(r"(?:\b|/)(\d+(?:_\d+)?(?:_\d+)?)(?:\.|/|\b)")
_TIER_RE = re.compile(r"tier[=_]?(\d+|all|gold|plat|diamond|master|grandmaster|challenger)", re.IGNORECASE)
_REGION_RE = re.compile(r"(?:/|_)(cn|tencent|kr|euw|na|all)(?:/|_|\.|\b)", re.IGNORECASE)


def analyze_url(url: str) -> dict:
    """Heuristic decomposition of a captured URL.

    Looks for patch tokens, tier stratification, regional path segments.
    Pure-text; no network. Returns a dict of findings."""
    findings: dict = {
        "url": url,
        "host": "",
        "path": "",
        "is_gtimg": False,
        "patch_token": None,
        "tier_token": None,
        "region_token": None,
        "looks_static_json": False,
        "looks_jsonp": False,
    }
    # Crude host/path split (stdlib urllib.parse would also work).
    m = re.match(r"https?://([^/]+)(/.*)?$", url)
    if m:
        findings["host"] = m.group(1)
        findings["path"] = m.group(2) or ""
    findings["is_gtimg"] = "gtimg.cn" in findings["host"].lower()
    findings["looks_static_json"] = findings["path"].lower().endswith(".json")
    findings["looks_jsonp"] = findings["path"].lower().endswith(".js") or findings["path"].lower().endswith(".jsonp")
    pm = _PATCH_RE.search(findings["path"])
    if pm:
        findings["patch_token"] = pm.group(1)
    tm = _TIER_RE.search(url)
    if tm:
        findings["tier_token"] = tm.group(1)
    rm = _REGION_RE.search(url)
    if rm:
        findings["region_token"] = rm.group(1)
    return findings


def load_json(path: Path) -> object:
    """Read + parse a captured JSON file. Tolerant of UTF-8 BOM + JSONP
    wrapper (Tencent CDNs occasionally serve `varName=({...});` or
    `var name = ({...});` or bare `name({...});`)."""
    raw = path.read_text(encoding="utf-8-sig")
    raw = raw.strip()
    # JSONP unwrap: locate the first `{` or `[` and the matching trailing
    # `}` or `]`, ignore everything outside (var prefix, function name,
    # parens, trailing semicolon). Pure-text; no AST.
    first = -1
    for i, ch in enumerate(raw):
        if ch in ("{", "["):
            first = i
            break
    if first > 0:
        last_brace = raw.rfind("}")
        last_bracket = raw.rfind("]")
        last = max(last_brace, last_bracket)
        if last > first:
            raw = raw[first:last + 1]
    return json.loads(raw)


def analyze_schema(obj: object) -> dict:
    """Walk top-level shape of the captured payload.

    Reports top-level keys, array shapes, and tries to identify the
    champion-keying convention (DDragon int IDs vs Tencent hero IDs vs
    name strings). Operator's real capture will validate / correct these
    heuristic guesses."""
    summary: dict = {
        "top_level_type": type(obj).__name__,
        "top_level_keys": [],
        "top_level_len": 0,
        "champion_key_format_guess": "unknown",
        "sample_keys": [],
        "sample_entry": None,
        "likely_pair_structure": "unknown",
    }
    if isinstance(obj, dict):
        keys = list(obj.keys())
        summary["top_level_keys"] = keys[:20]
        summary["top_level_len"] = len(keys)
        if keys:
            summary["sample_keys"] = keys[:5]
            summary["sample_entry"] = _summarize_value(obj[keys[0]])
            summary["champion_key_format_guess"] = _guess_key_format(keys)
    elif isinstance(obj, list):
        summary["top_level_len"] = len(obj)
        if obj:
            summary["sample_entry"] = _summarize_value(obj[0])
            if isinstance(obj[0], dict):
                inner_keys = list(obj[0].keys())
                summary["sample_keys"] = inner_keys[:5]
    if summary["sample_entry"] and isinstance(obj, (dict, list)):
        # Look for a sub-list whose entries look like (otherChamp, winRate, games)
        sample = obj[summary["sample_keys"][0]] if isinstance(obj, dict) and summary["sample_keys"] else obj[0]
        if isinstance(sample, list) and sample and isinstance(sample[0], (list, dict)):
            summary["likely_pair_structure"] = "list_of_pairs"
    return summary


def _summarize_value(v: object, depth: int = 0) -> object:
    """Truncate deep / wide values for readable printing."""
    if depth >= 2:
        return "..."
    if isinstance(v, dict):
        keys = list(v.keys())[:5]
        return {k: _summarize_value(v[k], depth + 1) for k in keys}
    if isinstance(v, list):
        return [_summarize_value(x, depth + 1) for x in v[:3]]
    if isinstance(v, str):
        return v[:60]
    return v


def _guess_key_format(keys: list) -> str:
    """Heuristic: are these DDragon ints (`266`), name strings (`Aatrox`),
    or hero-codes like `aatuoluosi`?"""
    if not keys:
        return "unknown"
    sample = [str(k) for k in keys[:10]]
    if all(s.isdigit() for s in sample):
        return "numeric_ddragon_or_tencent_id"
    if all(s.isalpha() and s[0].isupper() for s in sample):
        return "ddragon_name_pascalcase"
    if all(s.isalpha() and s.islower() for s in sample):
        return "tencent_hero_code_lower"
    return "mixed_or_unknown"


def load_ddragon_keys() -> dict:
    """Return {numeric_id: ddragon_name} from the bundled DDragon
    champion.json. Used to cross-reference whether Tencent's keys map
    cleanly to RC's champion set."""
    if not _DDRAGON_CHAMPION_JSON.exists():
        return {}
    raw = json.loads(_DDRAGON_CHAMPION_JSON.read_text(encoding="utf-8"))
    out: dict = {}
    for name, payload in (raw.get("data") or {}).items():
        key = str(payload.get("key", "")).strip()
        if key.isdigit():
            out[key] = name
    return out


def cross_reference_ddragon(payload_keys: list, ddragon_map: dict) -> dict:
    """Check how many of the payload's top-level keys map to a DDragon
    champion (by numeric id OR by name string). Cheap classifier."""
    out: dict = {
        "total_payload_keys": len(payload_keys),
        "matched_as_numeric_ddragon_key": 0,
        "matched_as_ddragon_name": 0,
        "unmatched_sample": [],
    }
    ddragon_names_lower = {n.lower(): n for n in ddragon_map.values()}
    for k in payload_keys:
        s = str(k)
        if s in ddragon_map:
            out["matched_as_numeric_ddragon_key"] += 1
        elif s.lower() in ddragon_names_lower:
            out["matched_as_ddragon_name"] += 1
        else:
            if len(out["unmatched_sample"]) < 8:
                out["unmatched_sample"].append(s)
    return out


def cross_check_rewind(payload: object, ddragon_map: dict) -> dict:
    """Pull one champion-pair from the payload, look up the equivalent
    pair in `data/rewind_history.db` via a light SQL query, and report
    side-by-side. Operator-eyes the alignment.

    This is intentionally lightweight - it does NOT compute Laplace blend
    here (use core.smoothed_rates if you need that downstream); it just
    surfaces the comparison candidates so the operator can validate
    whether Tencent's CN aggregate broadly agrees with RC's small local
    sample."""
    out: dict = {
        "rewind_db_exists": _REWIND_DB.exists(),
        "payload_pair_sample": None,
        "rewind_pair_sample": None,
        "note": "",
    }
    if not _REWIND_DB.exists():
        out["note"] = "rewind_history.db not present; skipping cross-check"
        return out
    pair = _first_pair_from_payload(payload, ddragon_map)
    if not pair:
        out["note"] = "could not extract a champion pair from the payload (schema unfamiliar)"
        return out
    out["payload_pair_sample"] = pair
    try:
        conn = sqlite3.connect(str(_REWIND_DB))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('matches','participants')"
            )
            ntables = cur.fetchone()[0]
            if ntables < 2:
                out["note"] = "rewind_history.db lacks expected tables; skipping pair lookup"
                return out
            out["rewind_pair_sample"] = {
                "champion_a": pair["champion_a"],
                "champion_b": pair["champion_b"],
                "queried": True,
                "note": "use core.smoothed_rates.laplace_rate on the joined counts for the actual blend",
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        out["note"] = f"rewind_history.db query error: {exc}"
    return out


def _first_pair_from_payload(payload: object, ddragon_map: dict) -> dict:
    """Best-effort extraction of one (champion_a, champion_b) pair from
    the captured payload. Heuristic; operator's real shape will validate."""
    if not isinstance(payload, dict):
        return {}
    keys = list(payload.keys())
    if not keys:
        return {}
    first_key = keys[0]
    name_a = ddragon_map.get(str(first_key), str(first_key))
    sub = payload[first_key]
    if isinstance(sub, list) and sub:
        candidate = sub[0]
        if isinstance(candidate, dict):
            inner_keys = list(candidate.keys())
            for k in inner_keys:
                v = candidate[k]
                if isinstance(v, str) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
                    return {"champion_a": name_a, "champion_b": str(v)}
        elif isinstance(candidate, (list, tuple)) and candidate:
            return {"champion_a": name_a, "champion_b": str(candidate[0])}
    if isinstance(sub, dict):
        sub_keys = list(sub.keys())
        if sub_keys:
            return {"champion_a": name_a, "champion_b": ddragon_map.get(str(sub_keys[0]), str(sub_keys[0]))}
    return {"champion_a": name_a, "champion_b": ""}


def _print_section(title: str, data: object) -> None:
    print("")
    print(f"== {title} ==")
    print(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True))


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze operator-captured 101.qq.com hero-rank-double payload.",
    )
    parser.add_argument("--url", required=True, help="The captured URL (from Chrome DevTools Network tab).")
    parser.add_argument("--json", required=True, help="Path to the downloaded JSON file on disk.")
    parser.add_argument(
        "--cross-check-rewind",
        action="store_true",
        help="Also surface a sample pair vs data/rewind_history.db for operator sanity-check.",
    )
    args = parser.parse_args(argv)

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"ERROR: JSON file not found: {json_path}", file=sys.stderr)
        return 1

    try:
        payload = load_json(json_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not parse JSON: {exc}", file=sys.stderr)
        return 1

    url_findings = analyze_url(args.url)
    schema = analyze_schema(payload)
    ddragon_map = load_ddragon_keys()
    payload_keys = list(payload.keys()) if isinstance(payload, dict) else []
    xref = cross_reference_ddragon(payload_keys, ddragon_map)

    _print_section("url_structure", url_findings)
    _print_section("json_schema", schema)
    _print_section("ddragon_cross_reference", xref)

    if args.cross_check_rewind:
        rw = cross_check_rewind(payload, ddragon_map)
        _print_section("rewind_history_cross_check", rw)

    print("")
    print("Done. Submit findings via the bridge for Legion-side integration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
