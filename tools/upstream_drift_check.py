# arch: daily upstream content-drift detector (ddragon / meraki / cdragon) | section=tools | frozen=no
"""Daily upstream content-drift detector.

Probes three upstream sources for ACTUAL content changes (not fetch-time),
compares each signal against a persisted per-machine sentinel, advances the
sentinel, and on drift can optionally send a cross-Claude bridge note and/or
auto-trigger the DDragon mirror refresh.

The three signals (each probe is individually fail-soft -> None + error str):

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

USER_AGENT = "RiotCommander/upstream-drift-check/1.0"
DEFAULT_TIMEOUT = 20.0
# len() of this tuple == max retry count. Mirrors the compact retry style in
# tools/ddragon_mirror_refresh.py (transient: URLError / timeout / 429+5xx).
RETRY_BACKOFFS = (1.0, 2.0)
TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})

# The 3 signal keys, in display order.
FIELD_NAMES = ("ddragon_version", "meraki_content_patch", "cdragon_content_version")

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


# --------------------------------------------------------------------------- sentinel
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _null_sentinel() -> dict:
    return {
        "ddragon_version": None,
        "meraki_content_patch": None,
        "cdragon_content_version": None,
        "updated_at": None,
        "last_drift_at": None,
    }


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

        if args.patch:
            ddragon = args.patch
        else:
            ddragon = probe_ddragon_version()
        meraki = probe_meraki_content_patch()
        cdragon = probe_cdragon_content_version()

        current = {
            "ddragon_version": ddragon,
            "meraki_content_patch": meraki,
            "cdragon_content_version": cdragon,
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
