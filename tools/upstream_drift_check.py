# arch: daily upstream content-drift detector (ddragon / meraki / cdragon / qq / queues) | section=tools | frozen=no
"""Daily upstream content-drift detector.

Probes five upstream sources for ACTUAL content changes (not fetch-time),
compares each signal against a persisted per-machine sentinel, advances the
sentinel, and on drift can optionally send a cross-Claude bridge note and/or
auto-trigger the DDragon mirror refresh.

The five signals (each probe is individually fail-soft -> None + error str):

1. DDragon live patch version
   GET https://ddragon.leagueoflegends.com/api/versions.json
   JSON list of strings; element [0] is the live patch (e.g. "16.11.1").

2. Meraki content patch (the honest data-age signal; ``fetched_at`` lies)
   GET https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json
   dict keyed by champion; signal = NEWEST ``patchLastChanged`` across all dict
   values that carry the field, ranked NUMERICALLY by (major, minor).

3. CDragon content build version (bumps on every content rebuild)
   GET https://raw.communitydragon.org/latest/content-metadata.json
   {"version": "16.11.7829736+branch...content.release"}; signal = the FULL
   ``version`` string verbatim (the build number is what changes on a rebuild).

4. 101.qq duo-synergy envelope SHAPE (RM-131)
   core.synergy_external_source.fetch_rows() against a canary lane pair.
   Signal = row-count BUCKET + a hash of the first row's key set - deliberately
   NOT the win-rate values, which move daily and would make this a noise
   generator instead of a drift alarm. Exists because that source fails SILENT:
   on any HTTP error or envelope-shape change `_validate_rows` drops RC back to
   the frozen May-25 static seed and nothing anywhere says so, so RC can serve
   stale duo-synergy forever. An unreachable endpoint shows here as ERR.

5. CDragon queue catalog SHAPE (RM-128)
   GET .../rcp-be-lol-game-data/global/default/v1/queues.json
   A LIST (not a dict) of queue records. Signal = a hash over the sorted
   ``id:gameSelectModeGroup`` pairs, so it moves when Riot adds, removes or
   re-groups a queue - which is the event that can silently strand RC's
   hand-maintained ``core/queue_modes.QUEUE_ID_TO_MODE_KEY``.

A field is ``changed`` ONLY when current is not None AND previous is not None
AND current != previous. A first-ever run (previous null) is baseline seeding,
NOT drift. A field whose probe errored this run carries the previous value
forward and is never ``changed``.

Modes:
  (default)      probe + compare + print + ADVANCE the sentinel; on drift log a
                 WARNING and fire --bridge-note / --auto-refresh side effects.
  --check-only   probe + compare + print, but do NOT write the sentinel and do
                 NOT fire side effects. Exit 1 if any drift else 0 (cron gate).
  --json PATH    also dump the full structured report.
  --patch PIN    skip the versions.json fetch and use PIN as the ddragon signal.
  --log-level    DEBUG/INFO/WARNING/ERROR (default INFO).

Structured so collection is import-safe: all network lives under functions,
``main(argv=None)`` returns an int.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parent.parent
SENTINEL_PATH = ROOT / "ops" / "runtime" / "upstream_drift.json"

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
MERAKI_CHAMPIONS_URL = (
    "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json"
)
CDRAGON_METADATA_URL = "https://raw.communitydragon.org/latest/content-metadata.json"
CDRAGON_QUEUES_URL = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data"
    "/global/default/v1/queues.json"
)

# Canary lane pair for the duo-synergy shape probe. bot/support is the pair the
# champ-select grid actually consumes, so a shape change here is the one that
# would break a live surface rather than a hypothetical one.
QQ_CANARY_LANES = ("bottom", "support")
# Row counts wobble day to day; bucket them so only a structural collapse (or a
# pagesize change) moves the signal.
QQ_ROWCOUNT_BUCKET = 25

# On-disk grounding snapshot for the queue catalog (RM-128). The daily probe
# detects that the catalog moved; this file is what the offline test compares
# core/queue_modes.QUEUE_ID_TO_MODE_KEY against, so the suite never needs the
# network. Refresh with --refresh-queue-snapshot after reviewing a drift.
QUEUE_SNAPSHOT_PATH = ROOT / "data" / "queue_catalog_snapshot.json"

USER_AGENT = "RiotCommander/upstream-drift-check/1.0"
DEFAULT_TIMEOUT = 20.0
# len() of this tuple == max retry count. Mirrors the compact retry style in
# tools/ddragon_mirror_refresh.py (transient: URLError / timeout / 429+5xx).
RETRY_BACKOFFS = (1.0, 2.0)
TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})

# The signal keys, in display order. Appending is safe: a sentinel written
# before a key existed simply reads that key as None, which is baseline seeding
# and never drift.
FIELD_NAMES = (
    "ddragon_version",
    "meraki_content_patch",
    "cdragon_content_version",
    "qq_synergy_shape",
    "cdragon_queue_catalog",
)

logger = logging.getLogger("upstream_drift_check")


# --------------------------------------------------------------------------- HTTP
def _http_get(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """GET ``url`` and return the body bytes.

    Retries on URLError / timeout / HTTP 429+5xx with the RETRY_BACKOFFS
    schedule. Raises on a non-transient HTTP error or after exhausting retries.
    """
    headers = {"User-Agent": USER_AGENT}
    last_url_err: urllib_error.URLError | None = None
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
        except urllib_error.URLError as e:
            last_url_err = e
            if attempt < len(RETRY_BACKOFFS):
                time.sleep(RETRY_BACKOFFS[attempt])
                continue
            raise
    # Unreachable: the loop returns or raises on the final attempt.
    raise last_url_err if last_url_err else RuntimeError("unreachable")


# --------------------------------------------------------------------------- meraki helpers
def _patch_sort_key(patch):
    """NUMERIC (major, minor) sort key so 25.15 > 25.9 (not lexical)."""
    try:
        major, minor = str(patch).split(".")[:2]
        return (int(major), int(minor))
    except (ValueError, AttributeError, TypeError):
        return (-1, -1)


def _meraki_content_patch(raw):
    """Newest ``patchLastChanged`` across dict-valued champion records."""
    patches = [v["patchLastChanged"] for v in raw.values()
               if isinstance(v, dict) and v.get("patchLastChanged")]
    return max(patches, key=_patch_sort_key) if patches else None


# --------------------------------------------------------------------------- probes
# Each probe returns the signal string or None. On failure it records the error
# via the module-level _LAST_ERRORS map so a transient failure on one source
# neither crashes the run nor false-alarms. Probes are monkeypatched in tests.

_LAST_ERRORS: dict[str, str | None] = {k: None for k in FIELD_NAMES}


def _set_error(field: str, exc: Exception) -> None:
    _LAST_ERRORS[field] = f"{type(exc).__name__}: {exc}"
    logger.warning("probe %s failed: %s", field, exc)


def probe_ddragon_version() -> str | None:
    field = "ddragon_version"
    try:
        body = _http_get(DDRAGON_VERSIONS_URL)
        versions = json.loads(body.decode("utf-8"))
        if not isinstance(versions, list) or not versions:
            raise ValueError("versions.json not a non-empty list")
        val = versions[0]
        if not isinstance(val, str) or not val:
            raise ValueError("versions[0] not a non-empty string")
        return val
    except Exception as e:  # noqa: BLE001 - fail-soft per source
        _set_error(field, e)
        return None


def probe_meraki_content_patch() -> str | None:
    field = "meraki_content_patch"
    try:
        body = _http_get(MERAKI_CHAMPIONS_URL)
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("champions.json not a dict")
        return _meraki_content_patch(raw)
    except Exception as e:  # noqa: BLE001 - fail-soft per source
        _set_error(field, e)
        return None


def probe_cdragon_content_version() -> str | None:
    field = "cdragon_content_version"
    try:
        body = _http_get(CDRAGON_METADATA_URL)
        meta = json.loads(body.decode("utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("content-metadata.json not a dict")
        val = meta.get("version")
        if not isinstance(val, str) or not val:
            raise ValueError("metadata.version not a non-empty string")
        return val
    except Exception as e:  # noqa: BLE001 - fail-soft per source
        _set_error(field, e)
        return None


def _short_hash(parts) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8"))
    return h.hexdigest()[:16]


def probe_qq_synergy_shape() -> str | None:
    """RM-131: envelope-shape fingerprint for the 101.qq duo-synergy source.

    Returns ``n<bucket>+<keyhash>`` or None. Values are deliberately excluded -
    win rates move daily and a value-sensitive signal would report drift every
    single run, which is the same as reporting nothing.
    """
    field = "qq_synergy_shape"
    try:
        root = str(ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)
        from core import synergy_external_source as ses

        rows = ses.fetch_rows(*QQ_CANARY_LANES, force_refresh=True)
        if not rows:
            raise ValueError(
                f"no rows for lanes {QQ_CANARY_LANES} - endpoint unreachable or "
                "envelope rejected (RC is silently serving the static seed)")
        first = rows[0]
        if not isinstance(first, dict):
            raise ValueError(f"row 0 is {type(first).__name__}, want dict")
        bucket = (len(rows) // QQ_ROWCOUNT_BUCKET) * QQ_ROWCOUNT_BUCKET
        return f"n{bucket}+{_short_hash(sorted(str(k) for k in first))}"
    except Exception as e:  # noqa: BLE001 - fail-soft per source
        _set_error(field, e)
        return None


def _queue_catalog_pairs(catalog) -> list[str]:
    """Sorted ``id:gameSelectModeGroup`` pairs - the queue-catalog signal body."""
    if not isinstance(catalog, list) or not catalog:
        raise ValueError("queues.json not a non-empty list")
    pairs = [
        f"{e['id']}:{e.get('gameSelectModeGroup') or '-'}"
        for e in catalog
        if isinstance(e, dict) and isinstance(e.get("id"), int)
    ]
    if not pairs:
        raise ValueError("queues.json carried zero int-id records")
    return sorted(pairs)


def fetch_queue_catalog() -> list:
    """GET the CDragon queue catalog. Raises - callers decide fail-soft."""
    body = _http_get(CDRAGON_QUEUES_URL)
    return json.loads(body.decode("utf-8"))


def probe_cdragon_queue_catalog() -> str | None:
    """RM-128: fingerprint the queueId -> gameSelectModeGroup catalog.

    Moves when Riot adds, removes or re-groups a queue - the event that can
    strand ``core/queue_modes.QUEUE_ID_TO_MODE_KEY``, which is hand-maintained
    from a stashed LCU payload and has no upstream tie today.
    """
    field = "cdragon_queue_catalog"
    try:
        return _short_hash(_queue_catalog_pairs(fetch_queue_catalog()))
    except Exception as e:  # noqa: BLE001 - fail-soft per source
        _set_error(field, e)
        return None


# RM-140 coverage census. RM-128 measured that "every id in these groups must
# be mapped" is unimplementable - 16 kARAM and 256 kAlternativeLeagueGameModes
# records against 21 mapped ids, the remainder being retired and cosmetic
# content. The discriminator that DOES make it implementable is the client's
# own menu ordering: `gameSelectPriority > 0` is what the League client uses to
# place a queue in the play menu, so a positive priority means a human can
# actually queue into it today. Narrowed further to the two groups whose every
# member is genuinely that mode (kSummonersRift, kARAM, and kJade since
# RM-141) and to non-custom categories, the "unmapped" list is a real coverage
# gap rather than a forever-red rule. Do NOT widen this to
# kAlternativeLeagueGameModes: RM-128 refuted that, and eight already-mapped
# ids live there under three different mode_keys. kJade is admissible for the
# opposite reason - every one of its members is the throwback Rift mode, and
# its kCustom rows self-exclude through COVERAGE_EXCLUDED_CATEGORIES below.
COVERAGE_GROUPS = ("kARAM", "kJade", "kSummonersRift")
COVERAGE_EXCLUDED_CATEGORIES = ("kCustom",)


def _coverage_candidates(by_id: dict, mapped: dict) -> dict:
    """Client-visible queues in the groups RC claims to cover, mapped or not."""
    out = {}
    for qid, e in sorted(by_id.items()):
        if (e.get("gameSelectPriority") or 0) <= 0:
            continue
        if e.get("gameSelectModeGroup") not in COVERAGE_GROUPS:
            continue
        if e.get("gameSelectCategory") in COVERAGE_EXCLUDED_CATEGORIES:
            continue
        out[str(qid)] = {
            "group": e.get("gameSelectModeGroup"),
            "category": e.get("gameSelectCategory"),
            "priority": e.get("gameSelectPriority"),
            "name": e.get("name"),
            "mapped_to": mapped.get(qid),
        }
    return out


def write_queue_snapshot(catalog=None) -> dict:
    """Refresh ``data/queue_catalog_snapshot.json`` from the live catalog.

    Records ONLY what the offline grounding test needs: the fingerprint, the
    group census, the per-id group/name for the ids RC actually maps, and the
    RM-140 coverage census (client-visible ids in the groups RC claims to
    cover, mapped or not). The full 352 KB catalog is not committed - the rest
    is noise the test would never read.
    """
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from core.queue_modes import QUEUE_ID_TO_MODE_KEY

    cat = fetch_queue_catalog() if catalog is None else catalog
    pairs = _queue_catalog_pairs(cat)
    by_id = {e["id"]: e for e in cat if isinstance(e, dict) and isinstance(e.get("id"), int)}
    groups: dict[str, int] = {}
    for e in by_id.values():
        g = e.get("gameSelectModeGroup") or "-"
        groups[g] = groups.get(g, 0) + 1
    snap = {
        "source": CDRAGON_QUEUES_URL,
        "fetched_at": _now_iso(),
        "fingerprint": _short_hash(pairs),
        "entry_count": len(by_id),
        "group_counts": dict(sorted(groups.items())),
        "mapped_queues": {
            str(qid): {
                "mode_key": mode_key,
                "group": (by_id.get(qid) or {}).get("gameSelectModeGroup"),
                "name": (by_id.get(qid) or {}).get("name"),
                "present": qid in by_id,
            }
            for qid, mode_key in sorted(QUEUE_ID_TO_MODE_KEY.items())
        },
        "coverage_candidates": _coverage_candidates(by_id, QUEUE_ID_TO_MODE_KEY),
    }
    QUEUE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE_SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, QUEUE_SNAPSHOT_PATH)
    return snap


# --------------------------------------------------------------------------- sentinel
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _null_sentinel() -> dict:
    # Derived from FIELD_NAMES so adding a signal cannot leave the baseline and
    # the probe list out of step (they were two hand-kept lists before RM-131).
    base: dict = {name: None for name in FIELD_NAMES}
    base["updated_at"] = None
    base["last_drift_at"] = None
    return base


def load_sentinel() -> dict:
    """Load the sentinel; a missing/corrupt file yields an all-null baseline."""
    base = _null_sentinel()
    if not SENTINEL_PATH.exists():
        return base
    try:
        data = json.loads(SENTINEL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning("sentinel %s unreadable (%s) - treating as baseline",
                       SENTINEL_PATH, e)
        return base
    if not isinstance(data, dict):
        return base
    base.update({k: data.get(k) for k in base if k in data})
    return base


def _atomic_write_sentinel(obj: dict) -> None:
    SENTINEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SENTINEL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, SENTINEL_PATH)


def advance_sentinel(previous: dict, current: dict, fields, *, drift: bool) -> dict:
    """Write the advanced sentinel.

    For each signal key write the current value if non-None, else carry the
    previous value forward. ``updated_at`` always refreshes; ``last_drift_at``
    advances to now only when ``drift`` else carries the prior value.
    """
    now = _now_iso()
    out = {}
    for name in FIELD_NAMES:
        cur = current.get(name)
        out[name] = cur if cur is not None else previous.get(name)
    out["updated_at"] = now
    out["last_drift_at"] = now if drift else previous.get("last_drift_at")
    _atomic_write_sentinel(out)
    return out


# --------------------------------------------------------------------------- drift logic
@dataclass
class FieldDrift:
    name: str
    previous: str | None
    current: str | None
    error: str | None
    changed: bool


def compute_fields(previous: dict, current: dict, errors: dict) -> list[FieldDrift]:
    out: list[FieldDrift] = []
    for name in FIELD_NAMES:
        prev = previous.get(name)
        cur = current.get(name)
        err = errors.get(name)
        changed = cur is not None and prev is not None and cur != prev
        out.append(FieldDrift(name=name, previous=prev, current=cur,
                              error=err, changed=changed))
    return out


def any_drift(fields) -> bool:
    return any(f.changed for f in fields)


# --------------------------------------------------------------------------- side effects
def send_bridge_note(drift_fields) -> tuple[bool, str]:
    """Log upstream content drift locally. Never raises; returns (ok, detail).

    The cross-Claude bridge was decommissioned 2026-06-24, so drift is now
    recorded to the log only (was a bridge note to Peer)."""
    try:
        changed = [f.name for f in drift_fields if f.changed]
        logger.info("upstream content drift: %s", ", ".join(changed))
        return True, "drift logged locally (bridge decommissioned)"
    except Exception as e:  # noqa: BLE001 - side effect must never crash main
        logger.warning("send_bridge_note failed: %s", e)
        return False, f"{type(e).__name__}: {e}"


def trigger_refresh() -> tuple[bool, str]:
    """Kick the mid-week refreshers on upstream drift. Never raises.

    Two sub-runs, each fail-soft and folded into one verdict:
      1. the DDragon mirror refresh (--check-changed), and
      2. the rank-tier stats-panel ingest (scripts/data_pipeline.py rank_tiers,
         overlay item 8 Phase 2) so a mid-week patch drift re-stamps the
         rank-tier artifact too.
    rc in (0, 1) is a benign changed/no-op exit for both; any other rc or an
    exception marks that sub-run not-ok. Returns (all_ok, detail)."""
    runs = (
        ([sys.executable, str(ROOT / "tools" / "ddragon_mirror_refresh.py"),
          "--check-changed"], "ddragon"),
        ([sys.executable, str(ROOT / "scripts" / "data_pipeline.py"),
          "rank_tiers"], "rank_tiers"),
    )
    all_ok = True
    details: list[str] = []
    for cmd, label in runs:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ok = proc.returncode in (0, 1)
            all_ok = all_ok and ok
            details.append(f"{label} rc={proc.returncode}")
        except Exception as e:  # noqa: BLE001 - side effect must never crash main
            logger.warning("trigger_refresh %s failed: %s", label, e)
            all_ok = False
            details.append(f"{label} err={type(e).__name__}")
    return all_ok, "; ".join(details)


# --------------------------------------------------------------------------- rendering
def run_staleness_recent(days: int = 7) -> tuple[bool, str]:
    """RM-81 daily watchdog: re-check champions whose wiki Data pages changed.

    Deliberately NOT drift-gated. A champion's live values can change without
    any ddragon/meraki/cdragon version moving (and when a version DOES move a
    full re-extract runs anyway), so gating this on ``any_drift`` would fire it
    exactly when it is least needed.

    Fail-soft: returns ``(False, reason)`` on any failure and never raises, so
    an unreachable wiki cannot flip the drift detector's exit code.
    """
    try:
        tools_dir = str(Path(__file__).resolve().parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import ds_wiki_staleness_check as sc

        champs = sc.champions_from_titles(sc.fetch_recent_titles(days=days))
        if not champs:
            return True, f"no Data-template edits in {days}d"
        patch = sc._current_patch()
        report = sc.run(patch, champs)
        # checked=champs -> merge, so this narrow pass cannot erase a full sweep.
        sc.write_report(report, patch, checked=champs)
        return True, f"checked {len(champs)} champ(s)"
    except Exception as e:  # noqa: BLE001 - side effect never fatal
        return False, f"{type(e).__name__}: {e}"


def _fmt(val: str | None) -> str:
    return val if val is not None else "-"


def render_table(fields) -> str:
    lines = ["field                     previous -> current                 status"]
    for f in fields:
        if f.error:
            status = "ERR"
        elif f.changed:
            status = "CHANGED"
        else:
            status = "ok"
        transition = f"{_fmt(f.previous)} -> {_fmt(f.current)}"
        lines.append(f"  {f.name:<24} {transition:<35} {status}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Detect upstream content drift (ddragon / meraki / cdragon).")
    p.add_argument("--check-only", action="store_true",
                   help="probe + compare only; do not write sentinel or fire "
                        "side effects. Exit 1 on drift, 0 otherwise.")
    p.add_argument("--bridge-note", action="store_true",
                   help="deprecated (bridge decommissioned, ADR-012); on drift, "
                        "log it locally. Flag kept for back-compat with the "
                        "RC-UpstreamDriftCheck task + tests.")
    p.add_argument("--auto-refresh", action="store_true",
                   help="on drift, trigger the ddragon mirror refresh")
    p.add_argument("--staleness-recent", action="store_true",
                   help="RM-81: re-check champions whose wiki ability pages "
                        "changed recently and refresh ability_staleness.json. "
                        "Runs regardless of drift; never affects the exit code.")
    p.add_argument("--staleness-days", type=int, default=7, metavar="N",
                   help="lookback window for --staleness-recent (default 7)")
    p.add_argument("--refresh-queue-snapshot", action="store_true",
                   help="RM-128: re-fetch queues.json and rewrite "
                        "data/queue_catalog_snapshot.json, then exit. Run this "
                        "only after REVIEWING a cdragon_queue_catalog drift - "
                        "it is the human step that re-grounds the queue map.")
    p.add_argument("--json", default=None, metavar="PATH",
                   help="also dump the full structured report to PATH")
    p.add_argument("--patch", default=None, metavar="PIN",
                   help="skip versions.json and use PIN as the ddragon signal")
    p.add_argument("--log-level", default="INFO",
                   choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        # Reset the per-run error map (probes set entries on failure).
        for k in FIELD_NAMES:
            _LAST_ERRORS[k] = None

        if args.refresh_queue_snapshot:
            snap = write_queue_snapshot()
            print(f"queue snapshot -> {QUEUE_SNAPSHOT_PATH} "
                  f"({snap['entry_count']} queues, fp {snap['fingerprint']})")
            return 0

        if args.patch:
            ddragon = args.patch
        else:
            ddragon = probe_ddragon_version()
        meraki = probe_meraki_content_patch()
        cdragon = probe_cdragon_content_version()
        qq_shape = probe_qq_synergy_shape()
        queue_catalog = probe_cdragon_queue_catalog()

        current = {
            "ddragon_version": ddragon,
            "meraki_content_patch": meraki,
            "cdragon_content_version": cdragon,
            "qq_synergy_shape": qq_shape,
            "cdragon_queue_catalog": queue_catalog,
        }
        previous = load_sentinel()
        errors = {k: _LAST_ERRORS.get(k) for k in FIELD_NAMES}
        fields = compute_fields(previous, current, errors)
        drift = any_drift(fields)

        print(render_table(fields))

        if args.json:
            report = {
                "current": current,
                "previous": {k: previous.get(k) for k in FIELD_NAMES},
                "fields": [
                    {"name": f.name, "previous": f.previous, "current": f.current,
                     "error": f.error, "changed": f.changed}
                    for f in fields
                ],
                "any_drift": drift,
                "generated_at": _now_iso(),
            }
            json_path = Path(args.json)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        if args.check_only:
            # Cron gate: do NOT write the sentinel, do NOT fire side effects.
            return 1 if drift else 0

        advance_sentinel(previous, current, fields, drift=drift)

        if args.staleness_recent:
            # run_staleness_recent is already fail-soft, but guard the call site
            # too (as the bridge-note / auto-refresh sites do) so a refactor that
            # drops that guarantee cannot turn a wiki outage into exit 2.
            try:
                ok, detail = run_staleness_recent(days=args.staleness_days)
                logger.info("staleness-recent: ok=%s detail=%s", ok, detail)
            except Exception as e:  # noqa: BLE001 - side effect never fatal
                logger.warning("staleness-recent raised: %s", e)

        if drift:
            changed = ", ".join(f.name for f in fields if f.changed)
            logger.warning("upstream content drift detected: %s", changed)
            if args.bridge_note:
                # Defensive: send_bridge_note is already fail-soft, but guard
                # the call site too so a monkeypatched/refactored raiser can
                # never flip the detector's exit code.
                try:
                    ok, detail = send_bridge_note(fields)
                    logger.info("bridge note: ok=%s detail=%s", ok, detail)
                except Exception as e:  # noqa: BLE001 - side effect never fatal
                    logger.warning("bridge note raised: %s", e)
            if args.auto_refresh:
                try:
                    ok, detail = trigger_refresh()
                    logger.info("auto-refresh: ok=%s detail=%s", ok, detail)
                except Exception as e:  # noqa: BLE001 - side effect never fatal
                    logger.warning("auto-refresh raised: %s", e)
        else:
            logger.info("no upstream drift (sentinel advanced)")

        return 0
    except Exception as e:  # noqa: BLE001 - hard unexpected failure -> exit 2
        logger.exception("upstream_drift_check hard error: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
