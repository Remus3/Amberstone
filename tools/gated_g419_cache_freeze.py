"""gated_g419_cache_freeze.py - read-only sampler + grader for G4-19.

G4-19 asks for a live re-verify of the ``core/liveclient_cache.py`` self-heal
(``03868b03``): when the async poll task ends while the process lives on,
``_task_alive()`` treats it as dead and ``get()`` / ``start()`` respawn it, so
``/api/state.liveclient`` stops collapsing to ``{}`` while ``:2999`` serves a game.

Facts measured at source (s144 lane gated c63) that shape the check:

- ``/api/state.liveclient`` IS ``dashboard._liveclient.liveclient_summary()``
  (``dashboard/_state_builder.py`` builds ``"liveclient": lc``), and that returns
  ``{}`` when ``snap.data is None or snap.age_s > 5`` (``STATE_TTL_S``).
- ``Snapshot.age_s`` is measured from the RELAY's own ``ts``, not from the cache's
  last fetch. So an empty ``liveclient`` has FOUR causes: a frozen cache (this
  row), a stale relay (the separate "5 s TTL vs 8-11 s capture" defect at the top
  of docs/LIVE_GAME_GATED_SYNC.md), ``liveclient_summary`` raising (its outer
  ``except`` returns ``{}`` with nothing logged), and RC's own relay fetch failing
  (401, timeout, parse, error body: ``_fetch_once`` publishes ``data=None``).
  ``sample`` reads the relay directly and never calls an empty ``liveclient`` a
  freeze unless the relay was fresh at the same moment, which excludes the second.
  It cannot tell the other three apart, so its verdict is FREEZE_CANDIDATE and
  lists them (``causes_not_excluded``); triage is the main session's. In TFT, an
  empty summary is replaced by the ``tft_standalone`` fill-in
  (``dashboard/_state_builder.py``), so that source counts as empty.
- The respawn path only runs when the poll task ends INSIDE a live process. A
  supervisor restart of RC starts a new process whose module state
  is fresh (``_task`` is None), so it never touches ``_task_alive``. The commit's
  own "live-verified after an RC restart" is therefore not evidence for the fix.
  ``respawns`` reads the log for a ``liveclient_cache started (..., async)`` line
  more than ``GRACE_S`` after the process start (``ops/runtime/health.json``
  ``started_at``): only such a line shows the self-heal path ran. The log carries
  no pid, so the ``started_at`` cut is the only process boundary. A dev-runtime
  reload of the module (``ops/rc_dev_runtime.py`` ``_reload_modules``) also resets
  ``_task`` and logs a start, so a result file under ``ops/runtime/control/results``
  naming the module since the process start voids the read.

Sub-commands (READ-ONLY: GETs to :8888 and :8889, reads of one log file,
health.json and the dev-runtime result files; no write, no restart, no LCU call,
no tick):

  sample [--samples N] [--interval S] [--json]
      Per sample: relay data age and /api/state liveclient key count. Classes: OK,
      EMPTY_WHILE_FRESH, RELAY_STALE, AMBIGUOUS, NO_GAME, RELAY_DOWN, DASH_DOWN.
      Verdict FREEZE_CANDIDATE (exit 3) when FROZEN_STREAK consecutive EMPTY_WHILE_FRESH
      samples span at least FROZEN_SPAN_S; HEALTHY (exit 0) when at least MIN_OK
      samples are OK and no frozen streak exists; else NO_EVIDENCE (exit 4).
  respawns [--log FILE] [--started-at ISO] [--grace S] [--root DIR]
      In-process respawns of the poll task after the process start. Exit 0 when at
      least one is found and no module reload voids it (self-heal exercised), else 4. The default log is the
      process-start day's under the main checkout; a game after midnight needs
      ``--log`` for that day.

HEALTHY never ticks G4-19: it proves the cache did not freeze in that window, and
the row also needs the render half (the overlay leaves the dashboard), which this
tool cannot see. Prints no path, game id or player id.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TOOL = "gated_g419_cache_freeze"
STATE_TTL_S = 5.0        # dashboard/_liveclient.py liveclient_summary gate
FRESH_MAX_S = 2.5        # relay age at or under this leaves margin for poll + build
FROZEN_STREAK = 3
# Since 03868b03 the next get() (about 2/s from /api/state) respawns a dead task, so
# a healed freeze lasts about a second. 10 s also outlasts a few 2 s fetch timeouts.
FROZEN_SPAN_S = 10.0
MIN_OK = 10
GRACE_S = 90.0
MAX_SAMPLES = 1800
TFT_STANDALONE = "tft_standalone"
FROZEN_CAUSES = ("the cache poll task froze and did not self-heal (G4-19)",
                 "liveclient_summary raised and its outer except returned {}",
                 "RC's own relay fetch kept failing (401, timeout, parse, error body) "
                 "while this tool's fetch succeeded")
# The async-task path only: the thread fallback is not the 03868b03 fix path.
_START_RE = re.compile(r"^(\d\d):(\d\d):(\d\d)(?:\.\d+)?\s.*liveclient_cache started "
                       r"\(poll=[\d.]+s, async\)")
RELOAD_MODULE = "core.liveclient_cache"
RESULTS_REL = Path("ops") / "runtime" / "control" / "results"
_ENDED_RE = re.compile(r"^(\d\d):(\d\d):(\d\d)(?:\.\d+)?\s.*liveclient_cache poll task ended")
_LOG_NAME_RE = re.compile(r"(\d{4})-(\d\d)-(\d\d)\.log$")


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_404(err: Optional[str]) -> bool:
    return bool(err) and "404" in str(err)


def classify_sample(relay: Any, relay_err: Optional[str], state: Any,
                    state_err: Optional[str], now: float) -> dict:
    """One sample's class from a relay envelope and an /api/state body."""
    out: dict = {"t": now, "relay_age_s": None, "lc_keys": None,
                 "game_time_s": None, "game_mode": None}
    if relay is None:
        out["cls"] = "NO_GAME" if _is_404(relay_err) else "RELAY_DOWN"
        return out
    data = relay.get("data") if isinstance(relay, dict) else None
    if not isinstance(data, dict) or "error" in relay or not data.get("activePlayer"):
        out["cls"] = "NO_GAME"
        return out
    game = data.get("gameData") if isinstance(data.get("gameData"), dict) else {}
    if _finite(game.get("gameTime")):
        out["game_time_s"] = round(float(game["gameTime"]), 1)
    if isinstance(game.get("gameMode"), str):
        out["game_mode"] = game["gameMode"]
    ts = relay.get("ts")
    age = now - ts if _finite(ts) else None
    out["relay_age_s"] = None if age is None else round(age, 2)
    if state is None or not isinstance(state, dict):
        out["cls"] = "DASH_DOWN"
        return out
    lc = state.get("liveclient")
    keys = len(lc) if isinstance(lc, dict) else 0
    if isinstance(lc, dict) and lc.get("source") == TFT_STANDALONE:
        keys = 0  # the TFT fill-in replaces an EMPTY summary; it masks a freeze
    out["lc_keys"] = keys
    if age is None or age < -1.0:
        out["cls"] = "AMBIGUOUS"
    elif age > STATE_TTL_S:
        out["cls"] = "RELAY_STALE"
    elif keys > 0:
        out["cls"] = "OK"
    elif age <= FRESH_MAX_S:
        out["cls"] = "EMPTY_WHILE_FRESH"
    else:
        out["cls"] = "AMBIGUOUS"
    return out


def grade_samples(samples: list) -> dict:
    """FROZEN / HEALTHY / NO_EVIDENCE over samples in time order."""
    counts: dict = {}
    for s in samples:
        counts[s["cls"]] = counts.get(s["cls"], 0) + 1
    worst: list = []
    run: list = []
    for s in samples:
        if s["cls"] == "EMPTY_WHILE_FRESH":
            run.append(s)
            if len(run) > len(worst):
                worst = list(run)
        else:
            run = []
    span = (worst[-1]["t"] - worst[0]["t"]) if len(worst) > 1 else 0.0
    clock = [s["game_time_s"] for s in samples if s.get("game_time_s") is not None]
    if len(worst) >= FROZEN_STREAK and span >= FROZEN_SPAN_S:
        verdict = "FREEZE_CANDIDATE"
    elif counts.get("OK", 0) >= MIN_OK:
        verdict = "HEALTHY"
    else:
        verdict = "NO_EVIDENCE"
    return {"tool": TOOL, "verdict": verdict, "counts": counts,
            "causes_not_excluded": (list(FROZEN_CAUSES) if verdict == "FREEZE_CANDIDATE"
                                    else []),
            "longest_empty_while_fresh": len(worst), "streak_span_s": round(span, 2),
            "game_modes": sorted({s["game_mode"] for s in samples if s.get("game_mode")}),
            "game_time_first_last_s": clock[:1] + clock[-1:],
            "note": "not a tick: HEALTHY proves no freeze in this window only; the "
                    "overlay render half is the operator's eyeball"}


def parse_log_events(text: str, log_date: datetime) -> list:
    """(local datetime, 'started' | 'ended') for every cache start / end line."""
    events = []
    for line in text.splitlines():
        for kind, rx in (("started", _START_RE), ("ended", _ENDED_RE)):
            m = rx.match(line)
            if m:
                h, mi, s = (int(g) for g in m.groups())
                if h < 24 and mi < 60 and s < 60:
                    events.append((log_date.replace(hour=h, minute=mi, second=s,
                                                    microsecond=0), kind))
    return events


def parse_started_at(text: Any) -> datetime:
    """health.json ``started_at`` to a naive LOCAL datetime (the log's clock)."""
    if not isinstance(text, str) or not text:
        raise ValueError("started_at is not a non-empty string")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def find_respawns(events: list, started_local: datetime, grace_s: float = GRACE_S,
                  reloads: int = 0) -> dict:
    """Async starts after process start + grace are in-process respawns.

    ``reloads`` counts dev-runtime reloads of the cache module since the process
    start (``ops/rc_dev_runtime.py`` ``_reload_modules``): a reload resets ``_task``
    and logs a start too, with no line of its own, so it voids the read.
    """
    cut = started_local + timedelta(seconds=grace_s)
    after = [(t, k) for t, k in events if t >= started_local]
    respawns = [t for t, k in after if k == "started" and t > cut]
    ended = [t for t, k in after if k == "ended"]
    boot = [t for t, k in after if k == "started" and t <= cut]
    return {"tool": TOOL, "process_start_local": started_local.strftime("%H:%M:%S"),
            "boot_starts": len(boot), "respawns": [t.strftime("%H:%M:%S") for t in respawns],
            "ended_warnings": [t.strftime("%H:%M:%S") for t in ended],
            "module_reloads": reloads,
            "self_heal_exercised": bool(respawns) and not reloads,
            "note": "a cancel logs no ended warning; a module reload since the process "
                    "start voids the read"}


def count_reloads(results_dir: Path, since_epoch: float) -> int:
    """Dev-runtime result files newer than ``since_epoch`` naming the cache module."""
    if not results_dir.is_dir():
        return 0
    n = 0
    for path in results_dir.glob("*.result.json"):
        try:
            if path.stat().st_mtime < since_epoch:
                continue
            if RELOAD_MODULE in path.read_text(encoding="utf-8", errors="replace"):
                n += 1
        except OSError:
            n += 1  # unreadable: fail closed, count it against the read
    return n


def _log_date(path: Path) -> datetime:
    m = _LOG_NAME_RE.search(path.name)
    if not m:
        raise ValueError("log file name is not YYYY-MM-DD.log")
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _base(arg: Optional[str]) -> Path:
    """Runtime root: --root, else the main checkout (a worktree has no logs/)."""
    from tools.gated_frame_readback import main_checkout
    return Path(arg) if arg else (main_checkout(_ROOT) or _ROOT)


def _read_health(base: Path) -> dict:
    doc = json.loads((base / "ops" / "runtime" / "health.json").read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("health.json is not an object")
    return doc


def _probe_once() -> dict:
    from tools.gated_live_probe import _DASH_BASE, _RELAY_BASE, _get_json
    relay, relay_err = _get_json(f"{_RELAY_BASE}/latest-liveclient")
    now = time.time()
    state, state_err = _get_json(f"{_DASH_BASE}/api/state", None)
    return classify_sample(relay, relay_err, state, state_err, now)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G4-19 liveclient_cache freeze check (read-only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sample")
    ps.add_argument("--samples", type=int, default=30)
    ps.add_argument("--interval", type=float, default=2.0)
    ps.add_argument("--json", action="store_true")
    pr = sub.add_parser("respawns")
    pr.add_argument("--log")
    pr.add_argument("--started-at")
    pr.add_argument("--grace", type=float, default=GRACE_S)
    pr.add_argument("--root", help="runtime root (default: the main checkout)")
    return p


def run(args: argparse.Namespace, probe=_probe_once, sleep=time.sleep) -> int:
    if args.cmd == "sample":
        if not 1 <= args.samples <= MAX_SAMPLES or not _finite(args.interval) \
                or args.interval < 0:
            raise ValueError("samples must be 1..1800 and interval a finite >= 0")
        samples = []
        for i in range(args.samples):
            if i:
                sleep(args.interval)
            samples.append(probe())
        result = grade_samples(samples)
        if args.json:
            result["samples"] = samples
        print(json.dumps(result, indent=2))
        return {"HEALTHY": 0, "FREEZE_CANDIDATE": 3}.get(result["verdict"], 4)
    base = _base(args.root)
    started = args.started_at or _read_health(base).get("started_at")
    started_local = parse_started_at(started)
    log = Path(args.log) if args.log else (
        base / "logs" / f"{started_local.strftime('%Y-%m-%d')}.log")
    if not _finite(args.grace) or args.grace < 0:
        raise ValueError("grace must be a finite number >= 0")
    events = parse_log_events(log.read_text(encoding="utf-8", errors="replace"),
                              _log_date(log))
    reloads = count_reloads(base / RESULTS_REL, started_local.timestamp())
    result = find_respawns(events, started_local, args.grace, reloads)
    print(json.dumps(result, indent=2))
    return 0 if result["self_heal_exercised"] else 4


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
