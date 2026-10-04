# arch: game-data spec / patch watch - key and field diff of the DDragon index, idempotent post, exit 2 on fetch/parse failure | section=tools | frozen=no
"""Spec / patch watch over the game-data version feed and data index (P1-3).

Keeps a standing promise without anyone remembering it: "when Riot ships a
new patch, or a new champion / item / field appears in the official data, that
is recorded as a fact once". Each run:

1. fetches the version feed (Data Dragon ``versions.json``) and, for the
   newest version, the champion and item data index;
2. reduces them to a SNAPSHOT: the version string, the champion ids, the item
   ids and the union of field paths per entity kind (top-level keys plus one
   nested level, e.g. ``stats.hp``, ``gold.total``);
3. diffs the snapshot against the stored one; a change gets an idempotency
   MARKER (sha256 of the change, 16 hex) and is posted ONCE to the tracking
   feed ``ops/runtime/spec_watch_events.jsonl``.

Rules:
- the first run is a BASELINE: it stores the snapshot and posts nothing
  (history is not news);
- a marker already posted, or present in the tracking feed with any status
  (``open`` or ``closed`` - a closed tracker also counts as said), is never
  posted again;
- the stored snapshot advances only after delivery is confirmed, so a failed
  delivery re-offers the same change next run (exit 1);
- if the feed or the index cannot be fetched or parsed the run FAILS with exit
  2 and writes nothing - it never passes quietly;
- a manual run is a DRY RUN unless ``--apply`` is given. The daily
  RC-UpstreamDriftCheck task runs it with apply via
  ``upstream_drift_check.py --spec-watch``.

Network: the game-data pipeline's client (lib/game_data/fetch.live_client):
one in-process client, blocklist, 1 request/second per host, environment
proxies ignored. Three requests per run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.game_data.sources import DDRAGON_VERSIONS_URL, SourceParseError, parse_versions  # noqa: E402

STATE_PATH = ROOT / "ops" / "runtime" / "spec_watch_state.json"
EVENTS_PATH = ROOT / "ops" / "runtime" / "spec_watch_events.jsonl"
_INDEX = "https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/{name}.json"


class SpecUnavailable(RuntimeError):
    """The upstream document could not be fetched or parsed."""


def _get_json(client: Any, url: str) -> Any:
    try:
        resp = client.get(url)
    except Exception as exc:  # noqa: BLE001 - any transport failure is "unavailable"
        raise SpecUnavailable(f"fetch failed: {url}: {exc.__class__.__name__}") from exc
    if getattr(resp, "status", 200) != 200:
        raise SpecUnavailable(f"HTTP {resp.status}: {url}")
    try:
        return json.loads(resp.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SpecUnavailable(f"not JSON: {url}") from exc


def _field_paths(entities: dict) -> list[str]:
    paths: set[str] = set()
    for ent in entities.values():
        if not isinstance(ent, dict):
            raise SpecUnavailable("entity is not an object")
        for key, val in ent.items():
            paths.add(key)
            if isinstance(val, dict):
                paths.update(f"{key}.{sub}" for sub in val)
    return sorted(paths)


def take_snapshot(client: Any) -> dict:
    """Fetch and reduce the spec. Raises SpecUnavailable on any fetch/parse failure."""
    try:
        resp = client.get(DDRAGON_VERSIONS_URL)
        if getattr(resp, "status", 200) != 200:
            raise SpecUnavailable(f"HTTP {resp.status}: {DDRAGON_VERSIONS_URL}")
        version = parse_versions(resp.body)[0]
    except SourceParseError as exc:
        raise SpecUnavailable(str(exc)) from exc
    except SpecUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - transport failure
        raise SpecUnavailable(f"fetch failed: {DDRAGON_VERSIONS_URL}: {exc.__class__.__name__}") from exc
    snap: dict[str, Any] = {"version": version, "fields": {}}
    for kind, name in (("champion", "champion"), ("item", "item")):
        blob = _get_json(client, _INDEX.format(v=version, name=name))
        data = blob.get("data") if isinstance(blob, dict) else None
        if not isinstance(data, dict) or not data:
            raise SpecUnavailable(f"{name}.json for {version}: no data map")
        snap[f"{kind}s"] = sorted(data)
        snap["fields"][kind] = _field_paths(data)
    return snap


def _added_removed(old: list, new: list) -> dict:
    return {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new))}


def diff_snapshots(prev: dict, cur: dict) -> Optional[dict]:
    change = {
        "from_version": prev.get("version"),
        "to_version": cur["version"],
        "champions": _added_removed(prev.get("champions", []), cur["champions"]),
        "items": _added_removed(prev.get("items", []), cur["items"]),
        "fields": {
            k: _added_removed(prev.get("fields", {}).get(k, []), cur["fields"][k]) for k in ("champion", "item")
        },
    }
    moved = change["from_version"] != change["to_version"] or any(
        v for part in (change["champions"], change["items"], *change["fields"].values()) for v in part.values()
    )
    return change if moved else None


def marker_of(change: dict) -> str:
    canon = json.dumps(change, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("ascii")).hexdigest()[:16]


def _tracked_markers(events_path: Path) -> set[str]:
    out: set[str] = set()
    if not events_path.is_file():
        return out
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("marker"), str):
            out.add(rec["marker"])
    return out


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="ascii", newline="\n")
    tmp.replace(path)


def append_event(events_path: Path, record: dict) -> dict:
    """Default delivery: one JSON line appended to the tracking feed."""
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="ascii", newline="\n") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return {"ok": True, "detail": str(events_path.name)}


def run(
    *,
    apply: bool = False,
    client: Any = None,
    state_path: Path = STATE_PATH,
    events_path: Path = EVENTS_PATH,
    deliver: Optional[Callable[[dict], dict]] = None,
    now: Optional[str] = None,
) -> tuple[int, dict]:
    """Returns (exit_code, summary). 0 ok, 1 delivery failed, 2 spec unavailable."""
    if client is None:
        from lib.game_data.fetch import live_client

        client = live_client()
    summary: dict[str, Any] = {"dry_run": not apply}
    try:
        cur = take_snapshot(client)
    except SpecUnavailable as exc:
        summary.update(outcome="fetch-failed", detail=str(exc))
        return 2, summary
    summary["version"] = cur["version"]
    state: dict = {}
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="ascii"))
    prev = state.get("snapshot")
    if prev is None:
        summary["outcome"] = "baseline"
        if apply:
            _write_state(state_path, {"snapshot": cur, "posted": {}})
        return 0, summary
    change = diff_snapshots(prev, cur)
    if change is None:
        summary["outcome"] = "nothing-new"
        return 0, summary
    marker = marker_of(change)
    summary.update(marker=marker, change=change)
    posted = dict(state.get("posted") or {})
    if marker in posted or marker in _tracked_markers(events_path):
        summary["outcome"] = "already-said"
        if apply:
            _write_state(state_path, {"snapshot": cur, "posted": posted})
        return 0, summary
    if not apply:
        summary["outcome"] = "would-post"
        return 0, summary
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {"marker": marker, "status": "open", "posted_at": stamp, "change": change}
    sink = deliver if deliver is not None else (lambda rec: append_event(events_path, rec))
    try:
        result = sink(record)
    except Exception as exc:  # noqa: BLE001 - a raising sink is a failed delivery
        result = {"ok": False, "detail": f"{exc.__class__.__name__}: {exc}"}
    if not (isinstance(result, dict) and result.get("ok") is True):
        summary.update(outcome="deliver-failed", detail=(result or {}).get("detail") if isinstance(result, dict) else None)
        return 1, summary
    posted[marker] = {"posted_at": stamp, "to_version": change["to_version"]}
    _write_state(state_path, {"snapshot": cur, "posted": posted})
    summary["outcome"] = "posted"
    return 0, summary


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Game-data spec / patch watch (dry run unless --apply).")
    ap.add_argument("--apply", action="store_true", help="write state and post (the scheduled run passes this)")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    code, summary = run(apply=args.apply)
    print(json.dumps({k: v for k, v in summary.items() if k != "change"}, sort_keys=True))
    if "change" in summary:
        print(json.dumps(summary["change"], indent=1, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
