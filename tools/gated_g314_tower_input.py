"""gated_g314_tower_input.py - G3-14 drain helper: does the ARAM tower input ever leave the 100 / 100 seed?

G3-14 (docs/LIVE_GAME_GATED_SYNC.md GATE 3) finding (3): over every R78 shadow
row the deterministic ARAM objective took only two of its six branches, because
its inputs ``my_tower_hp`` / ``enemy_tower_hp`` (``dashboard/_deterministic_coaching.py``)
come from the coach artifact, which ``_blank_artifact_data`` seeds 100 / 100
(``coaches/aram_coach.py``) and which ``_run_vision`` overwrites only when the
Sonnet tower read returns a non-null value. The row's CHECK asks, in the next
ARAM Mayhem game, whether the tower field moves around a real turret kill.

This tool samples ``/api/state`` (``liveclient.game_time_s`` / ``hp`` /
``turret_events``, ``dashboard/_liveclient.py``), the MAIN checkout's
``data/aram_coaching_data.json`` (``mode`` / ``my_team`` / the two tower
fields, plus its mtime), the tail row of ``data/aram_coach_shadow.jsonl``
(``ts`` / ``mode`` / ``enemy_comp`` size, ``core/aram_coach_shadow.py``) and
``:8889/latest-frame/meta`` ``ts``, then grades the predicates below. Whether the
turret was ON SCREEN below full HP is a pixel question this tool never answers,
so it never returns the row's FAIL by itself (HELD_100 is the input to it).

PREDICATES (stated in docs/LIVE_GAME_GATED_SYNC.md G3-14 before any game):
  game    PASS iff a sample has ``mode_key`` aram and a non-empty ``liveclient``;
          else NO_GAME.
  writer  PASS iff a sampled shadow tail row has ``ts`` at or after the game
          start (first in-game sample time minus its ``game_time_s``), ``mode``
          aram and a 5-name ``enemy_comp``; FAIL (writer dead) iff none did over
          at least WRITER_MIN_S of sampled game time; else INCOMPLETE.
  tower   On the FIRST turret kill (lowest ``down_at_s``) the side comes from
          its name (``_T1_`` ORDER, ``_T2_`` CHAOS - an ASSUMPTION the row says
          to confirm on that first event) against the fresh artifact's
          ``my_team``: own side -> ``my_tower_hp``, else ``enemy_tower_hp``.
          Window = in-game samples with a FRESH artifact (mtime at or after the
          game start, ``mode`` aram) and ``game_time_s`` from 90 s before to
          60 s after ``down_at_s``.
          PASS iff that field takes at least two DIFFERENT values in the window
          and at least one is below 100.
          HELD_100 iff both fields read exactly 100 at EVERY window sample, the
          window reaches COVER_BEFORE_S before and COVER_AFTER_S after the kill
          with no gap over MAX_GAP_S, the player is alive (hp > 0) and the frame
          fresh (0 <= age <= FRAME_FRESH_S) at every window sample. The row's
          FAIL is HELD_100 PLUS the operator having seen that turret on screen
          below full HP in a sampled frame; without that it is NO RESULT.
          NO_RESULT otherwise (no turret fell, unknown side, no fresh artifact,
          a dead player, a stale frame, a coverage gap, or a held non-100 value).
  record  reported only: the field's values after the kill and whether it ever
          read 0 (``_TOWER_DEAD``); "nearest tower" may be the next tower at full HP.

READ-ONLY: it GETs two local endpoints and reads two files; it writes nothing
(samples go to stdout, the grade to stderr), sends no LCU request, never prints
the relay token or a path, and keeps no game id, puuid, Riot ID or champion
name - the samples hold numbers, flags, team sides and turret names only.

USAGE (from the repo root or a worktree; RC must be up; start past the load screen)
    python tools/gated_g314_tower_input.py --samples 80 --interval 25 > <evidence>.jsonl
    python tools/gated_g314_tower_input.py --grade <evidence>.jsonl [--json]
    python tools/gated_g314_tower_input.py            (one sample, graded)
Exit 0 = tower PASS and writer PASS, 1 = NO_GAME / INCOMPLETE / NO_RESULT /
HELD_100, 2 = writer FAIL.
"""
from __future__ import annotations

import argparse
import json
import math
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_frame_readback import main_checkout, resolve_token  # noqa: E402

DASH_BASE = "https://127.0.0.1:8888"
RELAY_BASE = "http://127.0.0.1:8889"  # plain HTTP and token-gated, never https
TIMEOUT_S = 3.0
COACH_REL = Path("data") / "aram_coaching_data.json"
SHADOW_REL = Path("data") / "aram_coach_shadow.jsonl"
SEED_HP = 100
BEFORE_S = 90.0
AFTER_S = 60.0
COVER_BEFORE_S = 60.0
COVER_AFTER_S = 30.0
MAX_GAP_S = 35.0
FRAME_FRESH_S = 10.0
WRITER_MIN_S = 180.0
TAIL_BYTES = 65536
SIDES = {"_T1_": "ORDER", "_T2_": "CHAOS"}

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE  # :8888 is mkcert self-signed (every local RC probe)

Fetch = Callable[[str, "str | None"], "dict | None"]


def _relay_token() -> str:
    """env, this checkout's config, then the MAIN checkout's (a worktree has no token file)."""
    try:
        return resolve_token(_ROOT)[0] or ""
    except Exception:  # noqa: BLE001 - fail-soft: no header, the meta read is None
        return ""


def _http_json(url: str, token: str | None) -> dict | None:
    headers = {"X-RC-Token": token} if token else {}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_SSL) as r:
            body = json.loads(r.read().decode("utf-8"))
        return body if isinstance(body, dict) else None
    except Exception:  # noqa: BLE001 - fail-soft probe
        return None


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _epoch(ts: Any) -> float | None:
    """An ISO time string (naive = UTC, as the shadow writer never writes one) to epoch."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def read_coach(path: Path) -> dict:
    """The artifact fields the CHECK reads, plus the file mtime; {} when unreadable."""
    try:
        mtime = path.stat().st_mtime
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {"file_mtime": round(mtime, 3), "file_mode": data.get("mode"),
            "my_team": data.get("my_team"),
            "my_tower_hp": _num(data.get("my_tower_hp")),
            "enemy_tower_hp": _num(data.get("enemy_tower_hp"))}


def read_shadow_tail(path: Path, tail_bytes: int = TAIL_BYTES) -> dict | None:
    """The LAST complete JSON row of the shadow log, reduced to ts / mode / enemy count."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            raw = fh.read()
    except OSError:
        return None
    for line in reversed(raw.decode("utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            ec = rec.get("enemy_comp")
            return {"ts": rec.get("ts") if isinstance(rec.get("ts"), str) else None,
                    "mode": rec.get("mode"),
                    "n_enemy": len([e for e in ec if e]) if isinstance(ec, list) else 0}
    return None


def _turrets(v: Any) -> list[dict]:
    out = []
    for ev in v if isinstance(v, list) else []:
        if isinstance(ev, dict) and _num(ev.get("down_at_s")) is not None:
            name = ev.get("name")
            out.append({"down_at_s": _num(ev.get("down_at_s")),
                        "name": name if isinstance(name, str) else None})
    return out


def sample(fetch: Fetch = _http_json, now: Callable[[], float] = time.time,
           data_root: Path | None = None, dash_base: str = DASH_BASE,
           relay_base: str = RELAY_BASE, token: str | None = None) -> dict:
    """One read of the artifact, the shadow tail, /api/state and the frame meta."""
    root = data_root if data_root is not None else (main_checkout(_ROOT) or _ROOT)
    coach = read_coach(root / COACH_REL)
    shadow = read_shadow_tail(root / SHADOW_REL)
    t = now()
    st = fetch(f"{dash_base}/api/state", None)
    tok = _relay_token() if token is None else token
    meta = fetch(f"{relay_base}/latest-frame/meta", tok)
    st = st if isinstance(st, dict) else {}
    lc = st.get("liveclient") if isinstance(st.get("liveclient"), dict) else {}
    fts = _num((meta or {}).get("ts"))
    return {
        "t": round(t, 3),
        "state_ok": bool(st),
        "mode_key": st.get("mode_key"),
        "liveclient": bool(lc),
        "game_time_s": _num(lc.get("game_time_s")),
        "hp": _num(lc.get("hp")),
        "turret_events": _turrets(lc.get("turret_events")),
        "file_mtime": coach.get("file_mtime"),
        "file_mode": coach.get("file_mode"),
        "my_team": coach.get("my_team"),
        "my_tower_hp": coach.get("my_tower_hp"),
        "enemy_tower_hp": coach.get("enemy_tower_hp"),
        "shadow_last": shadow,
        "frame_ts": fts,
        "frame_age_s": None if fts is None else round(t - fts, 2),
    }


def _in_game(s: dict) -> bool:
    return (s.get("mode_key") == "aram" and bool(s.get("liveclient"))
            and _num(s.get("game_time_s")) is not None and _num(s.get("t")) is not None)


def side_of(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    hits = {side for tag, side in SIDES.items() if tag in name}
    return hits.pop() if len(hits) == 1 else None


def _fresh(s: dict, start: float) -> bool:
    m = _num(s.get("file_mtime"))
    return s.get("file_mode") == "aram" and m is not None and m >= start


def check_writer(game: list[dict], start: float) -> dict:
    ok = None
    for s in game:
        row = s.get("shadow_last") if isinstance(s.get("shadow_last"), dict) else {}
        ts = _epoch(row.get("ts"))
        if ts is not None and ts >= start and row.get("mode") == "aram" and row.get("n_enemy") == 5:
            ok = s
            break
    gts = [_num(s.get("game_time_s")) for s in game]
    span = round(max(gts) - min(gts), 1) if gts else 0.0
    if ok is not None:
        return {"state": "PASS", "first_at_game_time_s": ok.get("game_time_s"), "span_s": span}
    state = "FAIL" if span >= WRITER_MIN_S else "INCOMPLETE"
    return {"state": state, "span_s": span,
            "note": "no fresh aram shadow row with a 5-name enemy_comp"}


def check_tower(game: list[dict], start: float) -> dict:
    kills: dict[tuple, dict] = {}
    for s in game:
        for ev in s.get("turret_events") or []:
            if isinstance(ev, dict) and _num(ev.get("down_at_s")) is not None:
                kills[(ev.get("down_at_s"), ev.get("name"))] = ev
    if not kills:
        return {"state": "NO_RESULT", "reason": "no turret fell in the sampled window"}
    first = min(kills.values(), key=lambda e: _num(e.get("down_at_s")))
    d = _num(first["down_at_s"])
    side = side_of(first.get("name"))
    fresh = [s for s in game if _fresh(s, start)]
    teams = {s.get("my_team") for s in fresh if s.get("my_team") in ("ORDER", "CHAOS")}
    base = {"turret": first.get("name"), "down_at_s": d, "turret_side": side,
            "side_mapping": "ASSUMED _T1_=ORDER _T2_=CHAOS: confirm on this first event"}
    if side is None:
        return {"state": "NO_RESULT", "reason": "turret name carries no single _T1_/_T2_ side", **base}
    if len(teams) != 1:
        return {"state": "NO_RESULT", "reason": f"fresh artifact my_team not one side: {sorted(teams)}",
                **base}
    my_team = teams.pop()
    field = "my_tower_hp" if side == my_team else "enemy_tower_hp"
    base.update({"my_team": my_team, "field": field})
    window = sorted((s for s in fresh if d - BEFORE_S <= _num(s["game_time_s"]) <= d + AFTER_S),
                    key=lambda s: _num(s["game_time_s"]))
    post = [s.get(field) for s in fresh if _num(s["game_time_s"]) > d]
    base["record"] = {"after_kill_values": sorted({v for v in post if v is not None}),
                      "reached_zero": any(v == 0 for v in post)}
    if not window:
        return {"state": "NO_RESULT", "reason": "no fresh artifact sample inside the window", **base}
    vals = [s.get(field) for s in window]
    distinct = sorted({v for v in vals if v is not None})
    base.update({"window_samples": len(window), "window_values": distinct})
    if len(distinct) >= 2 and distinct[0] < SEED_HP:
        return {"state": "PASS", **base}
    gts = [_num(s["game_time_s"]) for s in window]
    gaps = [b - a for a, b in zip(gts, gts[1:])]
    problems = []
    if any(s.get("my_tower_hp") != SEED_HP or s.get("enemy_tower_hp") != SEED_HP for s in window):
        problems.append("a window sample is not 100 / 100 yet the field did not move")
    if gts[0] > d - COVER_BEFORE_S or gts[-1] < d + COVER_AFTER_S:
        problems.append(f"window covers {gts[0] - d:+.0f} s to {gts[-1] - d:+.0f} s around the kill")
    if gaps and max(gaps) > MAX_GAP_S:
        problems.append(f"sample gap {max(gaps):.0f} s over {MAX_GAP_S:.0f} s")
    if any((_num(s.get("hp")) or 0) <= 0 for s in window):
        problems.append("player dead at a window sample")
    ages = [_num(s.get("frame_age_s")) for s in window]
    if any(a is None or a < 0 or a > FRAME_FRESH_S for a in ages):
        problems.append("frame stale or unknown at a window sample")
    if problems:
        return {"state": "NO_RESULT", "reason": "; ".join(problems), **base}
    return {"state": "HELD_100", **base,
            "note": "row FAIL only if the operator saw this turret on screen below full HP in a"
                    " sampled frame; otherwise NO RESULT"}


def grade(samples: list[dict]) -> dict:
    """Grade a sample list against the predicates in the module docstring."""
    game = sorted((s for s in samples if isinstance(s, dict) and _in_game(s)),
                  key=lambda s: _num(s["t"]))
    checks: dict[str, dict] = {"game": {"state": "PASS" if game else "NO_GAME",
                                        "in_game_samples": len(game)}}
    if not game:
        return {"verdict": "NO_GAME", "samples": len(samples), "checks": checks}
    start = _num(game[0]["t"]) - _num(game[0]["game_time_s"])
    checks["writer"] = check_writer(game, start)
    checks["tower"] = check_tower(game, start)
    if checks["writer"]["state"] == "FAIL":
        verdict = "FAIL"
    elif checks["writer"]["state"] == "PASS":
        verdict = checks["tower"]["state"]
    else:
        verdict = "INCOMPLETE"
    return {"verdict": verdict, "samples": len(samples), "checks": checks}


EXIT = {"PASS": 0, "FAIL": 2}


def render(result: dict) -> str:
    lines = [f"G3-14 tower input: {result['verdict']} ({result['samples']} samples)"]
    for name, c in result["checks"].items():
        extra = ", ".join(f"{k}={v}" for k, v in c.items() if k != "state")
        lines.append(f"  {name}: {c['state']}" + (f" ({extra})" if extra else ""))
    lines.append("  not a tick: paste value + source + ts + predicate into the G3-14 row")
    return "\n".join(lines)


def load_samples(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--grade", type=Path, help="grade a saved JSONL sample file instead of sampling")
    ap.add_argument("--samples", type=int, default=1, help="samples to take (default 1)")
    ap.add_argument("--interval", type=float, default=25.0, help="seconds between samples")
    ap.add_argument("--data-root", type=Path, default=None, help="checkout whose data/ is read")
    ap.add_argument("--json", action="store_true", help="print the grade as JSON")
    a = ap.parse_args(argv)
    if a.grade is not None:
        if not a.grade.is_file():
            print("no such sample file", file=sys.stderr)
            return 1
        samples = load_samples(a.grade)
        out = sys.stdout
    else:
        samples = []
        try:
            for i in range(max(1, a.samples)):
                if i:
                    time.sleep(max(0.0, a.interval))
                s = sample(data_root=a.data_root)
                samples.append(s)
                print(json.dumps(s, sort_keys=True), flush=True)
        except KeyboardInterrupt:  # Ctrl-C ends sampling early; grade what was taken
            pass
        out = sys.stderr
    result = grade(samples)
    print(json.dumps(result, sort_keys=True) if a.json else render(result), file=out)
    return EXIT.get(result["verdict"], 1)


if __name__ == "__main__":
    sys.exit(main())
