"""gated_g313_mayhem_aug.py - G3-13 drain helper: sample and grade the ARAM Mayhem augment reco.

G3-13 (docs/LIVE_GAME_GATED_SYNC.md GATE 3) asks whether the Mayhem augment
recommendation RENDERS on screen while the in-game augment panel is open. Since
RM-860 (``9b51bc90f`` + ``32f625d4c``) ``coaches/aram_coach.py``
``_handle_augment_select`` stamps the ``aug_reco*`` keys from
``core.augment_recommender.recommend(mode="mayhem")`` into
``data/aram_coaching_data.json``, which ``/api/state`` serves as ``coach``, and
``web/js/panels/augment_reco.js`` ``renderAugmentReco`` shows them (``PICK NOW``
while ``augment_select`` is true, ``TOP PICK`` after). RM-877 retired the Haiku
fallback, so an offer whose cards do not resolve leaves the panel DARK.

This tool samples ``/api/state`` plus ``:8889/latest-frame/meta`` across the
augment window and grades the COMPUTE half only. Whether the panel actually drew
the pick, and whether the frame shows those cards, stays the operator's glance:
this tool's PASS is never the row's PASS (the SUBSTITUTION kill, GATE 0).

PREDICATES (stated in docs/LIVE_GAME_GATED_SYNC.md G3-13 before any game):
  game     PASS iff a sample has ``mode_key`` aram and a non-empty ``liveclient``;
           else NO_GAME.
  mayhem   PASS iff an in-game sample's ``liveclient.game_mode`` is Mayhem
           (``core.mayhem_detect.is_mayhem``: KIWI live) - the Live Client, not
           the coach artifact, so a stale coach file cannot vouch for itself;
           NOT_MAYHEM otherwise (plain ARAM: then no sample may carry an
           ``aug_reco``, else FAIL - the plain-ARAM negative control).
  panel    SEEN iff a sample has ``coach.augment_select`` true AND a non-empty
           ``coach.augment_choices``; else NOT_SEEN. The handler writes those two
           keys ONLY together with a ranking, so the artifact cannot tell a scan
           that missed the panel from an offer whose cards did not resolve (the
           panel then stays DARK on screen): in a Mayhem game NOT_SEEN is the
           verdict, and the operator's glance decides which it was.
  reco     PASS iff an open-panel sample has a non-empty ``aug_reco``,
           ``aug_reco_mode`` "mayhem" and an ``aug_reco_top`` whose normalised
           name (``core.augment_external_source._norm_name``: lowercase,
           alphanumerics only) equals a normalised offered card. FAIL iff an
           open-panel sample carries a reco whose mode is not "mayhem" or whose
           top is not an offered card (a wrong reco is worse than a dark one;
           an OCR alias name can trip this - confirm by eye before filing).
           DARK iff open-panel samples exist and none carried a reco (only a
           stale open flag left by an earlier panel produces that shape).
  clear    PASS iff a sample after the first open-panel sample has
           ``augment_select`` not true; STUCK (FAIL) iff it stays true over more
           than STUCK_AFTER_S of game time; else INCOMPLETE.
  frame    for the first PASSing reco sample: FRESH iff 0 <= sample time minus
           the frame meta ``ts`` <= FRAME_FRESH_S, else STALE (the eye check then
           needs a fresher sample; the compute verdict is unchanged).
  stage    reported only: ``aug_reco_stage`` of the first reco sample (1 for the
           game-start panel when the coach saw it inside _AUGMENT_WINDOW_S,
           None when the coach started mid-game).

READ-ONLY: it GETs two local endpoints and reads one file named on the command
line; it writes nothing (samples go to stdout, the grade to stderr), sends no
LCU request, never prints the relay token, and keeps no game id, puuid or Riot
ID - the samples hold augment names, flags and times only.

USAGE (from the repo root or a worktree; RC must be up)
    python tools/gated_g313_mayhem_aug.py --samples 45 --interval 4 > <evidence>.jsonl
    python tools/gated_g313_mayhem_aug.py --grade <evidence>.jsonl [--json]
    python tools/gated_g313_mayhem_aug.py            (one sample, graded)
Exit 0 = reco PASS and clear PASS (frame may be STALE; the on-screen glance is
still owed), 1 = INCOMPLETE / NO_GAME / NOT_MAYHEM / NOT_SEEN / DARK, 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DASH_BASE = "https://127.0.0.1:8888"
RELAY_BASE = "http://127.0.0.1:8889"  # plain HTTP and token-gated, never https
TIMEOUT_S = 3.0
FRAME_FRESH_S = 10.0
STUCK_AFTER_S = 75.0  # panel ~10-15 s + one 25 s vision scan + Sonnet escalation, with margin
RECO_MODE = "mayhem"

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE  # :8888 is mkcert self-signed (every local RC probe)

Fetch = Callable[[str, "str | None"], "dict | None"]


def norm_name(s: Any) -> str:
    """The resolver's normalisation (augment_external_source._norm_name)."""
    try:
        from core.augment_external_source import _norm_name
        return _norm_name(str(s))
    except Exception:  # noqa: BLE001 - same rule, inlined, if core is unimportable
        return "".join(ch for ch in str(s).lower() if ch.isalnum())


def is_mayhem_mode(game_mode: Any) -> bool:
    """core.mayhem_detect.is_mayhem on a bare game_mode string."""
    try:
        from core.mayhem_detect import is_mayhem
        return bool(is_mayhem(str(game_mode or "")))
    except Exception:  # noqa: BLE001 - same token set, inlined, if core is unimportable
        gm = str(game_mode or "").upper()
        return any(tok in gm for tok in ("KIWI", "MAYHEM", "ARAM_MAYHEM"))


def _relay_token() -> str:
    try:
        from core.vision_token import get_vision_token
        return get_vision_token() or ""
    except Exception:  # noqa: BLE001 - fail-soft: no header, the probe reports 401
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
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _names(v: Any) -> list[str]:
    return [str(x) for x in v if isinstance(x, (str, int, float))] if isinstance(v, list) else []


def sample(fetch: Fetch = _http_json, now: Callable[[], float] = time.time,
           dash_base: str = DASH_BASE, relay_base: str = RELAY_BASE,
           token: str | None = None) -> dict:
    """One read of /api/state + the frame meta, reduced to the G3-13 fields."""
    t = now()
    st = fetch(f"{dash_base}/api/state", None)
    tok = _relay_token() if token is None else token
    meta = fetch(f"{relay_base}/latest-frame/meta", tok)
    st = st if isinstance(st, dict) else {}
    coach = st.get("coach") if isinstance(st.get("coach"), dict) else {}
    lc = st.get("liveclient")
    reco = coach.get("aug_reco") if isinstance(coach.get("aug_reco"), list) else []
    fts = _num((meta or {}).get("ts"))
    return {
        "t": round(t, 3),
        "state_ok": bool(st),
        "mode_key": st.get("mode_key"),
        "liveclient": bool(lc),
        "game_time_s": _num(lc.get("game_time_s")) if isinstance(lc, dict) else None,
        "game_mode": lc.get("game_mode") if isinstance(lc, dict) else None,
        "coach_mayhem": coach.get("mayhem") is True,
        "augment_select": coach.get("augment_select") is True,
        "augment_choices": _names(coach.get("augment_choices")),
        "aug_reco": [str(r.get("name")) for r in reco if isinstance(r, dict)],
        "aug_reco_top": coach.get("aug_reco_top"),
        "aug_reco_mode": coach.get("aug_reco_mode"),
        "aug_reco_stage": coach.get("aug_reco_stage"),
        "frame_ts": fts,
        "frame_age_s": None if not fts else round(t - fts, 2),
    }


def _in_game(s: dict) -> bool:
    return s.get("mode_key") == "aram" and bool(s.get("liveclient"))


def _open(s: dict) -> bool:
    return bool(s.get("augment_select")) and bool(s.get("augment_choices"))


def _reco_problem(s: dict) -> str | None:
    """None when the sample's reco is well-formed for its offer, else why not."""
    if s.get("aug_reco_mode") != RECO_MODE:
        return f"aug_reco_mode {s.get('aug_reco_mode')!r}, not {RECO_MODE!r}"
    top = s.get("aug_reco_top") or (s.get("aug_reco") or [""])[0]
    offered = {norm_name(c) for c in s.get("augment_choices") or []}
    if norm_name(top) not in offered:
        return f"top {top!r} is not an offered card {s.get('augment_choices')!r}"
    return None


def grade(samples: list[dict]) -> dict:
    """Grade a sample list against the predicates in the module docstring."""
    checks: dict[str, dict] = {}
    game = [s for s in samples if _in_game(s)]
    checks["game"] = {"state": "PASS" if game else "NO_GAME", "in_game_samples": len(game)}
    if not game:
        return {"verdict": "NO_GAME", "samples": len(samples), "checks": checks}

    mayhem = any(is_mayhem_mode(s.get("game_mode")) for s in game)
    checks["mayhem"] = {"state": "PASS" if mayhem else "NOT_MAYHEM"}
    if not mayhem:
        leak = [s for s in game if s.get("aug_reco")]
        checks["negative"] = {"state": "FAIL" if leak else "PASS", "reco_samples": len(leak)}
        return {"verdict": "FAIL" if leak else "NOT_MAYHEM", "samples": len(samples),
                "checks": checks}

    opened = [i for i, s in enumerate(game) if _open(s)]
    checks["panel"] = {"state": "SEEN" if opened else "NOT_SEEN", "open_samples": len(opened)}
    if not opened:
        checks["panel"]["note"] = ("vision missed the panel OR its cards did not resolve"
                                   " (dark on screen); the operator's glance decides")
        return {"verdict": "NOT_SEEN", "samples": len(samples), "checks": checks}

    first_ok = None
    problems = []
    for i in opened:
        s = game[i]
        if not s.get("aug_reco"):
            continue
        why = _reco_problem(s)
        if why:
            problems.append({"t": s.get("t"), "game_time_s": s.get("game_time_s"), "why": why})
        elif first_ok is None:
            first_ok = s
    if problems:
        reco_state = "FAIL"
    elif first_ok is not None:
        reco_state = "PASS"
    else:
        reco_state = "DARK"
    checks["reco"] = {"state": reco_state, "problems": problems}
    if first_ok is not None:
        checks["reco"].update(top=first_ok.get("aug_reco_top"),
                              offered=first_ok.get("augment_choices"),
                              game_time_s=first_ok.get("game_time_s"), t=first_ok.get("t"))
        age = first_ok.get("frame_age_s")
        fresh = age is not None and 0 <= age <= FRAME_FRESH_S
        checks["frame"] = {"state": "FRESH" if fresh else "STALE", "frame_age_s": age}
        checks["stage"] = {"state": "INFO", "aug_reco_stage": first_ok.get("aug_reco_stage")}

    start = opened[0]
    after = game[start + 1:]
    t0 = _num(game[start].get("game_time_s"))
    if any(not s.get("augment_select") for s in after):
        clear = "PASS"
    else:
        last = max((_num(s.get("game_time_s")) or 0.0 for s in after), default=None)
        held = None if t0 is None or last is None else last - t0
        clear = "STUCK" if held is not None and held > STUCK_AFTER_S else "INCOMPLETE"
    checks["clear"] = {"state": clear}

    states = [c["state"] for c in checks.values()]
    if "FAIL" in states or "STUCK" in states:
        verdict = "FAIL"
    elif reco_state == "PASS" and clear == "PASS":
        verdict = "PASS"
    else:
        verdict = "INCOMPLETE"
    return {"verdict": verdict, "samples": len(samples), "checks": checks}


EXIT = {"PASS": 0, "FAIL": 2}


def render(result: dict) -> str:
    lines = [f"G3-13 compute half: {result['verdict']} ({result['samples']} samples)"]
    for name, c in result["checks"].items():
        extra = ", ".join(f"{k}={v}" for k, v in c.items() if k != "state")
        lines.append(f"  {name}: {c['state']}" + (f" ({extra})" if extra else ""))
    lines.append("  on-screen: OWED - the operator confirms the panel drew that top pick over"
                 " those cards; this tool never ticks the row")
    return "\n".join(lines)


def load_samples(path: Path) -> list[dict]:
    out = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
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
    ap.add_argument("--interval", type=float, default=4.0, help="seconds between samples")
    ap.add_argument("--json", action="store_true", help="print the grade as JSON")
    a = ap.parse_args(argv)
    if a.grade is not None:
        if not a.grade.is_file():
            print(f"no such sample file: {a.grade}", file=sys.stderr)
            return 1
        samples = load_samples(a.grade)
        out = sys.stdout
    else:
        samples = []
        for i in range(max(1, a.samples)):
            if i:
                time.sleep(max(0.0, a.interval))
            s = sample()
            samples.append(s)
            print(json.dumps(s, sort_keys=True), flush=True)
        out = sys.stderr
    result = grade(samples)
    print(json.dumps(result, sort_keys=True) if a.json else render(result), file=out)
    return EXIT.get(result["verdict"], 1)


if __name__ == "__main__":
    sys.exit(main())
