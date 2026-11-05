"""gated_rm869_vision_fields.py - RM-869 read-back: did the mode's OWN vision fields reach disk?

RM-869 (``bfa4bbfbe``, LEDGER 1833) moved the ARAM and Brawl vision readers off
the promptless TFT relay (``USE_RELAY = False``), so their own PROMPT fields can
reach Sonnet. Its live half is one ARAM Mayhem or Nexus Blitz game after an RC
restart that loads the fix. The only on-disk trace of those fields is the mode's
coaching file in the MAIN checkout's ``data/``, written by the coach's
``_run_vision`` and by nothing else:

  aram  ``data/aram_coaching_data.json`` ``my_tower_hp`` / ``enemy_tower_hp`` /
        ``wave_pct`` / ``hp_packs`` (``coaches/aram_coach.py`` ``_run_vision``,
        written only when the read returns a non-null value).
  nb    ``data/brawl_coaching_data.json`` ``event_name`` / ``event_timer`` /
        ``event_location`` / ``my_nexus_hp`` / ``enemy_nexus_hp``
        (``coaches/brawl_coach.py`` ``_run_vision``). One For All and GAMEMODEX
        get the same prompt and ``mode`` value, so an nb PASS counts only in a
        game whose live-client ``gameMode`` is NEXUSBLITZ (the doc row says so).

A new coach instance writes ``_blank_artifact_data()`` first
(``coaches/_base_coach.py`` ``_ensure_data``: "a new coach instance means a new
game"), so after that the SEED values below are the only values a vision read
did not write. URF has NO on-disk trace: ``heal_enemies`` / ``poke_phase`` /
``deaths_visible`` land only in the in-memory ``_vision_state`` and nothing reads
them, so this tool reports URF as UNOBSERVABLE and never passes it.

THE MERGE-SHADOW LOG IS NOT EVIDENCE HERE. ``core/vision_routing.py``
``read_or_escalate`` appends to ``data/vision_merge_shadow.jsonl`` only when the
escalation answers keys nobody asked for. A direct read that answers exactly its
own prompt writes no row, so "no new merge-shadow rows" proves nothing either way.

PREDICATES (stated in docs/LIVE_GAME_GATED_SYNC.md RM-869 row before any game):
  restart  PASS iff the cutoff is at or after FIX_COMMITTED_UTC; else FAIL.
  fields   PASS iff at least one FRESH sample (file mtime at or after the cutoff,
           ``mode`` equal to the mode's value) holds a field at a non-seed,
           non-null value; SEED_ONLY iff fresh samples exist and every field is
           at its seed in all of them; NO_GAME iff no fresh sample exists.
           SEED_ONLY is not a FAIL by itself: the doc row names the live context
           (alive, fresh frame, a tower or nexus visibly damaged, a Nexus Blitz
           event on screen) that turns it into one.

READ-ONLY: it reads files only; it never writes, moves, locks or deletes
anything, prints no game id and no path, and never ticks a row - its output is
the INPUT to the four-part evidence contract, never the evidence by itself.

USAGE (from a worktree it reads the MAIN checkout's data/)
    python tools/gated_rm869_vision_fields.py --mode aram --samples 30 --interval 10
    python tools/gated_rm869_vision_fields.py --mode nb --samples 60 --interval 10 --json
Exit 0 = PASS, 1 = NO_GAME / SEED_ONLY / UNOBSERVABLE / INCOMPLETE, 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_frame_readback import main_checkout  # noqa: E402
from tools.gated_g717_arena_readback import parse_utc, resolve_cutoff  # noqa: E402

# Committer time of bfa4bbfbe (2026-10-25 02:01:01 -05:00), the RM-869 landing.
FIX_COMMITTED_UTC = datetime(2026, 10, 25, 7, 1, 1, tzinfo=timezone.utc)

# mode -> (coaching file, artifact ``mode`` value, {field: seed}). The seeds are
# the ``_blank_artifact_data()`` values (pinned by test); a field the blank
# artifact omits seeds as None.
MODES: dict[str, tuple[Path, str, dict[str, Any]]] = {
    "aram": (Path("data") / "aram_coaching_data.json", "aram", {
        "my_tower_hp": 100, "enemy_tower_hp": 100,
        "wave_pct": 50, "hp_packs": [True, True],
    }),
    "nb": (Path("data") / "brawl_coaching_data.json", "brawl", {
        "event_name": "", "event_timer": 0, "event_location": None,
        "my_nexus_hp": 100, "enemy_nexus_hp": 100,
    }),
}
UNOBSERVABLE = ("urf",)


def snapshot(path: Path, fields: list[str]) -> dict[str, Any]:
    """One read of the coaching file: mtime, mode and the vision fields only."""
    try:
        mtime = path.stat().st_mtime
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {"present": False}
    if not isinstance(data, dict):
        return {"present": False}
    return {"present": True,
            "mtime_utc": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
            "mode": data.get("mode"),
            "fields": {f: data.get(f) for f in fields}}


def check_restart(cutoff: datetime | None, source: str) -> dict[str, Any]:
    if cutoff is None:
        return {"status": "INCOMPLETE", "source": source,
                "note": "no cutoff: pass --since or keep ops/runtime/health.json started_at"}
    ok = cutoff >= FIX_COMMITTED_UTC
    return {"status": "PASS" if ok else "FAIL", "source": source,
            "cutoff_utc": cutoff.isoformat(), "fix_committed_utc": FIX_COMMITTED_UTC.isoformat()}


def is_fresh(snap: dict, mode_value: str, cutoff: datetime | None) -> bool:
    t = parse_utc(snap.get("mtime_utc"))
    return bool(snap.get("present") and snap.get("mode") == mode_value
                and cutoff is not None and t is not None and t >= cutoff)


def check_fields(snaps: list[dict], mode_value: str, seeds: dict[str, Any],
                 cutoff: datetime | None) -> dict[str, Any]:
    fresh = [s for s in snaps if is_fresh(s, mode_value, cutoff)]
    seen: dict[str, list] = {f: [] for f in seeds}
    for s in fresh:
        for f, seed in seeds.items():
            v = s["fields"].get(f)
            # "" is an empty read (event_location defaults to it), never a hit.
            if v is not None and v not in ("", seed) and v not in seen[f]:
                seen[f].append(v)
    hits = {f: vals for f, vals in seen.items() if vals}
    if not fresh:
        status = "NO_GAME"
    elif hits:
        status = "PASS"
    else:
        status = "SEED_ONLY"
    return {"status": status, "snapshots": len(snaps), "fresh": len(fresh),
            "non_seed": hits, "last": fresh[-1]["fields"] if fresh else None}


def report(mode: str, snaps: list[dict], cutoff: datetime | None, source: str) -> dict[str, Any]:
    restart = check_restart(cutoff, source)
    if mode in UNOBSERVABLE:
        return {"schema": "gated_rm869_vision_fields/v1", "mode": mode,
                "verdict": "UNOBSERVABLE", "checks": {"restart": restart},
                "note": "URF fields land only in the in-memory _vision_state; nothing on disk reads them"}
    _rel, mode_value, seeds = MODES[mode]
    fields = check_fields(snaps, mode_value, seeds, cutoff)
    if restart["status"] == "FAIL":
        verdict = "FAIL"
    elif restart["status"] == "PASS" and fields["status"] == "PASS":
        verdict = "PASS"
    elif restart["status"] == "PASS":
        verdict = fields["status"]
    else:
        verdict = "INCOMPLETE"
    # No path and no game id in the output: a drain pastes it into a tracked doc.
    return {"schema": "gated_rm869_vision_fields/v1", "mode": mode, "verdict": verdict,
            "checks": {"restart": restart, "fields": fields}}


def render(rep: dict[str, Any]) -> str:
    lines = [f"RM-869 read-back ({rep['mode']}): {rep['verdict']}"]
    r = rep["checks"]["restart"]
    lines.append(f"- restart: {r['status']} cutoff {r.get('cutoff_utc')} ({r['source']}),"
                 f" fix committed {r.get('fix_committed_utc')}")
    if "fields" in rep["checks"]:
        f = rep["checks"]["fields"]
        lines.append(f"- fields: {f['status']} fresh {f['fresh']}/{f['snapshots']},"
                     f" non-seed {f['non_seed']}, last {f['last']}")
    else:
        lines.append(f"- fields: {rep['note']}")
    lines.append("Not a tick: record value + source + ts + predicate in the RM-869 row.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=sorted(MODES) + list(UNOBSERVABLE), default="aram")
    ap.add_argument("--since", default=None,
                    help="cutoff, any ISO time (default: health.json started_at)")
    ap.add_argument("--data-root", default=None, help="checkout whose data/ is read")
    ap.add_argument("--samples", type=int, default=1, help="coaching-file reads")
    ap.add_argument("--interval", type=float, default=10.0, help="seconds between reads")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    data_root = Path(a.data_root) if a.data_root else (main_checkout(_ROOT) or _ROOT)
    cutoff, source = resolve_cutoff(a.since, data_root)
    snaps: list[dict] = []
    if a.mode in MODES:
        rel, _mv, seeds = MODES[a.mode]
        for i in range(max(1, a.samples)):
            if i:
                time.sleep(max(0.0, a.interval))
            snaps.append(snapshot(data_root / rel, list(seeds)))
    rep = report(a.mode, snaps, cutoff, source)
    print(json.dumps(rep, indent=2) if a.json else render(rep))
    return {"PASS": 0, "FAIL": 2}.get(rep["verdict"], 1)


if __name__ == "__main__":
    sys.exit(main())
