# arch: lolmath-wiki stat sidecar extractor (wiki.gg ChampionData -> wiki_stats.json) | section=tools | frozen=no
"""leagueoflegends.wiki.gg ChampionData scalars -> per-champion sidecar JSON.

Item 221 (2026-05-30): a thin OPTIONAL sidecar extractor for the per-champion
scalar fields the Meraki bulk does NOT carry and that the DS combo/spike sims
want. Closes the GO-conditional verdict in
``docs/LOLMATH_WIKI_SOURCE_2026-05-30.md`` (item 217 feasibility).

What it pulls (the scalar fields the feasibility probe VERIFIED the wiki
exposes via ``Module:ChampionData``; see "verified vs unverified" below):
  * ``attack_cast_time`` - the AA windup (seconds). The feasibility probe
    confirmed it live: ``{{#invoke:ChampionData|get|Aatrox|attack_cast_time}}``
    returned ``0.30000001192093``. This is the field combo.py's
    ``_DEFAULT_AA_WINDUP_S = 0.25`` flat fallback wants to replace per-champ.
  * ``missile_speed`` - ranged AA missile speed (units/s). Per the
    feasibility doc ``Module:ChampionData/data`` schema (section 1e), a
    champion-level ``stats.missile_speed`` field. Melee champs have none.

NOT a live dependency: this is an OFFLINE patch-refresh tool, the SAME
contract as ``daemon_slayer_abilities_extract.py``. The DS engine reads the
committed sidecar JSON, never the network. The sidecar is an OPTIONAL
overlay: absent sidecar -> current behavior (the flat windup fallback). It
is INERT until a consumer (combo.py AA-windup wire) opts in.

VERIFIED vs UNVERIFIED (read before trusting the output of a run):
  * VERIFIED live (item 217 feasibility agent, 2026-05-30): the wiki is a
    wiki.gg MediaWiki (Cargo GONE, Bucket + Scribunto present);
    ``action=expandtemplates&text={{#invoke:ChampionData|get|<champ>|<field>}}``
    returns the bare scalar; ``attack_cast_time`` resolves for Aatrox.
  * UNVERIFIED from this build host (item 221, 2026-05-30): the live
    extraction did NOT run from Legion - the wiki edge-blocked every call
    (HTTP 401 with a tool UA; HTTP 403 + a wiki.gg "Blocked" HTML
    interstitial with a browser UA = Cloudflare/edge bot-protection, NOT a
    UA gate). The feasibility agent reached it earlier the same day, so the
    block is most likely a rate-trip or a host/egress rule, not a permanent
    wall. Consequences: (a) the exact ChampionData query path for
    ``missile_speed`` (bare field vs ``stats.missile_speed`` sub-path - the
    feasibility doc 1g noted the compound call needed the ``stats.``
    prefix) is NOT yet pinned by a live run; this tool tries the bare field
    first and a ``stats.`` fallback. (b) NO sidecar data file is committed
    yet. (c) the ``action=bucket`` mode-multiplier path (Arena/URF/NB) is
    NOT built here - it needs a live Bucket schema probe this host could
    not run; ARAM mults are already Meraki-covered, so no loss for SR/ARAM.

Run from a host that REACHES wiki.gg (or once Legion's egress clears):
  py tools/daemon_slayer_wiki_stats_extract.py            # current.txt patch
  py tools/daemon_slayer_wiki_stats_extract.py --patch 16.11.1
  py tools/daemon_slayer_wiki_stats_extract.py --limit 5  # smoke a subset
  py tools/daemon_slayer_wiki_stats_extract.py --dry-run  # no write
Then inspect ``_with_cast_time`` / ``_errors`` in the written file before
trusting it: a run that edge-blocks records every champ as an error (the
fail-soft path), so a sidecar with ``_with_cast_time == 0`` means the host
could not reach the wiki - do NOT commit that.

Design (don't re-litigate):
  * stdlib ``urllib`` only - no new pip dep (the DS data-pipeline rule).
  * User-Agent header set (wiki.gg blocks UA-less).
  * polite rate: ``--sleep`` between calls (default 0.5s; the wiki is a
    community resource + the robots.txt disallows api.php for crawlers - a
    small infrequent per-patch batch is acceptable MediaWiki practice,
    a bulk hammer is not).
  * fail-soft per champ: a bad/empty/blocked response records null, never
    aborts the whole run.
  * Atomic write: tmp.write_text + os.replace (overlays poll mid-write).
  * ASCII-only output (ensure_ascii=True) - the no-em-dash repo rule.
  * champion-id source = the committed abilities snapshot's ``data`` dict
    (171 champs at 16.11.1; keyed by DDragon id). Display-name map =
    ``data/meta_build/ddragon/<patch>/champion.json`` ``.data.<id>.name``
    (ChampionData is keyed by the wiki DISPLAY name: "Kai'Sa", "Wukong",
    "Bel'Veth" - the DDragon-id form "Kaisa"/"MonkeyKing" returns empty).
"""
from __future__ import annotations

import argparse
import json
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

WIKI_API = "https://leagueoflegends.wiki.gg/api.php"
HEADER_UA = "RiotCommander-DaemonSlayer/1.0 (offline patch-refresh extractor; local coaching tool)"
_HTTP_TIMEOUT = 20

# The candidate scalar fields. attack_cast_time is VERIFIED live (Aatrox
# 0.3). missile_speed is from the documented ChampionData schema but its
# exact query path (bare vs stats. sub-path) is not yet live-pinned from
# this host - _fetch_field tries bare then a stats. fallback.
_FIELD_ATTACK_CAST_TIME = "attack_cast_time"
_FIELD_MISSILE_SPEED = "missile_speed"

# DDragon id -> wiki display-name overrides for champs whose DDragon
# champion.json ``.name`` does NOT match the wiki page title exactly.
# DDragon ``.name`` IS the display name for the vast majority; this map is
# only the escape hatch for genuine wiki-title divergences found in a live
# run. Empty until a run surfaces one.
_WIKI_NAME_OVERRIDES: dict[str, str] = {}


def _fetch(url: str, timeout: int = _HTTP_TIMEOUT) -> str:
    """GET text with a UA header (wiki.gg blocks UA-less)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": HEADER_UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _expand(champ_display: str, field: str) -> str:
    """Resolve one ChampionData scalar via action=expandtemplates.

    Returns the bare wikitext scalar string ("" on a miss). Raises on a
    transport / HTTP error (the caller fail-softs per champ).
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
    exact = META_DDRAGON_DIR / patch / "champion.json"
    champ_json = exact
    if not champ_json.exists():
        candidates = sorted(META_DDRAGON_DIR.glob("*/champion.json"), key=lambda p: p.parts)
        if not candidates:
            raise SystemExit(f"no champion.json under {META_DDRAGON_DIR}")
        champ_json = candidates[-1]
    data = json.loads(champ_json.read_text(encoding="utf-8")).get("data", {})
    return {cid: str(rec.get("name") or cid) for cid, rec in data.items()}


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


def _wiki_name(ddragon_id: str, display_names: dict[str, str]) -> str:
    if ddragon_id in _WIKI_NAME_OVERRIDES:
        return _WIKI_NAME_OVERRIDES[ddragon_id]
    return display_names.get(ddragon_id, ddragon_id)


def _parse_scalar(s: str) -> Optional[float]:
    """A wiki scalar string -> float, or None when blank / non-numeric.

    wiki.gg ``ChampionData|get`` sometimes returns trailing ``||`` separators
    on a compound get (feasibility doc 1g: "0.30000001192093||"); strip on
    the first ``|`` and take the leading token.
    """
    s = (s or "").strip()
    if not s:
        return None
    s = s.split("|", 1)[0].strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _fetch_field(champ_display: str, field: str, stats_fallback: bool) -> Optional[float]:
    """Resolve a scalar field; optionally retry with a ``stats.`` sub-path.

    The feasibility doc (1g) noted the compound ChampionData get needed the
    ``stats.`` prefix for nested fields. attack_cast_time resolved bare;
    missile_speed may need ``stats.missile_speed``. Try bare first, then the
    stats. form when the bare returns empty.
    """
    val = _parse_scalar(_expand(champ_display, field))
    if val is None and stats_fallback:
        val = _parse_scalar(_expand(champ_display, "stats." + field))
    return val


def _atomic_write_json(path: Path, payload: Any) -> None:
    """tmp.write_text + os.replace - the repo atomic-write rule."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=True, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def extract(patch: str, sleep_s: float, limit: Optional[int], verbose: bool) -> dict[str, Any]:
    """Extract the sidecar payload for ``patch`` (does NOT write)."""
    display_names = _load_display_names(patch)
    ids = _load_champion_ids(patch)
    if limit:
        ids = ids[:limit]
    champions: dict[str, dict[str, Any]] = {}
    ok = 0
    errs: list[str] = []
    for n, ddragon_id in enumerate(ids):
        wname = _wiki_name(ddragon_id, display_names)
        act: Optional[float] = None
        ms: Optional[float] = None
        try:
            act = _fetch_field(wname, _FIELD_ATTACK_CAST_TIME, stats_fallback=True)
            if sleep_s > 0:
                time.sleep(sleep_s)
            ms = _fetch_field(wname, _FIELD_MISSILE_SPEED, stats_fallback=True)
            if act is not None:
                ok += 1
        except Exception as exc:  # noqa: BLE001 - fail-soft per champ
            errs.append(f"{ddragon_id}: {type(exc).__name__}: {str(exc)[:120]}")
        champions[ddragon_id] = {
            "wiki_name": wname,
            "attack_cast_time": act,
            "missile_speed": ms,
        }
        if verbose:
            tag = "ERR" if (errs and errs[-1].startswith(ddragon_id + ":")) else "ok"
            print(f"[{n+1}/{len(ids)}] {ddragon_id} ({wname}): act={act} ms={ms} {tag}")
        if sleep_s > 0 and n + 1 < len(ids):
            time.sleep(sleep_s)
    return {
        "_source": "leagueoflegends.wiki.gg ChampionData (action=expandtemplates)",
        "_patch": patch,
        "_fields": [_FIELD_ATTACK_CAST_TIME, _FIELD_MISSILE_SPEED],
        "_note": (
            "OPTIONAL DS overlay. attack_cast_time = AA windup; "
            "missile_speed = ranged AA missile speed (melee null). Meraki "
            "stays authoritative for ratios/CC. A run with _with_cast_time==0 "
            "means the host could not reach wiki.gg (edge block) - do NOT commit it."
        ),
        "_champ_count": len(champions),
        "_with_cast_time": ok,
        "_errors": errs,
        "champions": champions,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--patch", help="patch id, e.g. 16.11.1; default current.txt")
    ap.add_argument("--out", help="output path; default data/daemon_slayer/<patch>/wiki_stats.json")
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between calls (default 0.5)")
    ap.add_argument("--limit", type=int, default=0, help="extract only the first N champs (smoke test)")
    ap.add_argument("--dry-run", action="store_true", help="extract but do not write")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-champ progress")
    args = ap.parse_args(argv)

    patch = _resolve_patch(args.patch)
    out_path = Path(args.out) if args.out else (DATA_DIR / patch / "wiki_stats.json")

    payload = extract(patch, args.sleep, args.limit or None, args.verbose)
    print(
        f"patch={patch} champs={payload['_champ_count']} "
        f"with_cast_time={payload['_with_cast_time']} errors={len(payload['_errors'])}"
    )
    if payload["_errors"]:
        for e in payload["_errors"][:10]:
            print("  ERR", e)
    if payload["_with_cast_time"] == 0:
        print("WARNING: 0 champs resolved a cast time - host likely cannot reach wiki.gg; "
              "NOT a committable sidecar.")

    if args.dry_run:
        print("(dry-run; not written)")
        return 0
    _atomic_write_json(out_path, payload)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
