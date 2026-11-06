"""gated_g423_base_capture.py - read-only watcher + grader for G4-23.

G4-23 asks for a live re-validation of the L-01 base-capture fix (``eece8500``):
the vision self-grab (``vision_server/_frame.py``) calls
``core.vision_profiles.save_reference_image(img)``, whose AUTO path saves the
native base still only when (a) ``ops/runtime/health.json`` ``has_game`` is
true, (b) the Windows foreground process is ``League of Legends.exe``, and
(c) no base still exists yet for the active HUD ``config_key``.

Facts measured at source (s144 lane gated c77) that shape the check:

- Gate (c) MASKS gate (b). Once a config has a still, the auto path never writes
  again, whatever the foreground is. Every still under
  ``data/vision_calib_reference/`` was written 2026-07-05 / 2026-07-06 and none
  since, so an ordinary game on a calibrated config proves nothing about the
  alt-tab guard: "the still did not change while I alt-tabbed" is a
  SUBSTITUTION. The check is ARMED only when the active config has NO base still
  at the first sample (a HUD setting value never played before, e.g. a
  MinimapScale not in the ``refs`` list).
- A forced write (``capture_reference`` / the ``/vision-calibrator`` refresh /
  ``ingest_reference_from_path``) bypasses all three gates and looks exactly like
  an auto write on disk. Nobody may touch the calibrator during the window.
- The tool samples the foreground itself (``_foreground_image_name``, read-only
  Win32 queries). The vision process samples it at its own grab moment, so a write
  is graded on the samples on BOTH sides of it; a split bracket is AMBIGUOUS.

Sub-commands (READ-ONLY: reads health.json, the reference dir, League's
game.cfg via ``core.hud_settings`` and the foreground window; no write, no
restart, no LCU call, no tick):

  refs [--root DIR]
      The active config_key, whether it is ARMED (no base still), and every
      existing still (config_key, state, written ISO, dims, sha12).
  watch [--samples N] [--interval S] [--json] [--root DIR]
      Sample every S seconds, then grade. Verdicts: PASS_CANDIDATE (exit 0);
      FAIL_CLOBBER / FAIL_NO_GAME / FAIL_REGRAB / NO_WRITE_WHILE_ELIGIBLE (exit 3);
      GATE_C_MASKED / NOT_EXERCISED / AMBIGUOUS / VOID / NO_EVIDENCE (exit 4).

PASS_CANDIDATE never ticks G4-23: the row also needs the operator's eyeball of
the new still (an in-game HUD frame, not a desktop or a load screen). Prints no
game id or player id.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TOOL = "gated_g423_base_capture"
REF_REL = Path("data") / "vision_calib_reference"
HEALTH_REL = Path("ops") / "runtime" / "health.json"
LEAGUE_EXE = "league of legends.exe"   # core/vision_profiles.py _LEAGUE_EXE
ALT_MIN_SAMPLES = 3       # alt-tab stretch: has_game, not League, still absent
ALT_MIN_SPAN_S = 6.0
ELIGIBLE_MAX_S = 60.0     # armed + has_game + League foreground this long, no write
MAX_SAMPLES = 1800


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def safe_name(config_key: str) -> str:
    """The file stem ``core.vision_profiles._safe`` gives a config_key."""
    from core.vision_profiles import _safe
    return _safe(config_key)


def snapshot_refs(ref_dir: Path) -> dict:
    """{file name: {sha12, ts, config_key, state, w, h}} for every still."""
    out: dict = {}
    if not ref_dir.is_dir():
        return out
    for p in sorted(ref_dir.glob("*.jpg")):
        try:
            sha = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        except OSError:
            continue
        meta: dict = {}
        try:
            m = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
            meta = m if isinstance(m, dict) else {}
        except (OSError, ValueError):
            meta = {}
        ts = meta.get("ts")
        out[p.name] = {"sha12": sha, "ts": ts if _finite(ts) else None,
                       "config_key": meta.get("config_key"),
                       "state": meta.get("state", "base"),
                       "w": meta.get("width"), "h": meta.get("height")}
    return out


def read_has_game(health_path: Path) -> Optional[bool]:
    try:
        d = json.loads(health_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return bool(d.get("has_game")) if isinstance(d, dict) else None


def make_sample(t: float, has_game: Optional[bool], fg_name: str,
                config_key: str, refs: dict) -> dict:
    stem = safe_name(config_key)
    return {"t": t, "has_game": has_game, "fg_league": fg_name == LEAGUE_EXE,
            "config_key": config_key, "base_name": f"{stem}.jpg",
            "armed": f"{stem}.jpg" not in refs, "refs": refs}


def _verdict(v: str, **kw: Any) -> dict:
    return {"tool": TOOL, "verdict": v, **kw}


def grade(samples: list) -> dict:
    """Grade a watch window. Pure: every input is in ``samples``."""
    if not samples:
        return _verdict("NO_EVIDENCE", reason="no samples")
    first = samples[0]
    start_refs = first["refs"]
    seen: dict = {}
    for s in samples:
        for name, r in seen.items():
            now = s["refs"].get(name)
            if now is None:
                return _verdict("VOID", reason=f"a still vanished mid-window: {name}")
            if r["ts"] is None and now["sha12"] == r["sha12"]:
                r["ts"] = now["ts"]   # the jpg lands before its meta json
            elif now["sha12"] != r["sha12"] or now["ts"] != r["ts"]:
                return _verdict("FAIL_REGRAB", still=name, t=s["t"],
                                reason="a still was rewritten after it was first seen "
                                       "(gate c broken, or a forced calibrator write: triage)")
        for name, r in s["refs"].items():
            seen.setdefault(name, {"sha12": r["sha12"], "ts": r["ts"]})
    new_base = []
    for i in range(1, len(samples)):
        for name in samples[i]["refs"]:
            if name not in samples[i - 1]["refs"] and name not in start_refs:
                new_base.append((i, name))
    named = [n for i, n in new_base if samples[i]["refs"][n]["state"] != "base"]
    if named:
        return _verdict("VOID", reason=f"a named-state still appeared (forced ingest): {named}")
    if any(s["config_key"] == "unknown" for s in samples):
        # read_hud_settings found no usable game.cfg [General] Width/Height
        # (measured at idle 2026-11-05): a still filed under "unknown" is not
        # the calibrated config's, so it neither arms nor grades the row.
        return _verdict("AMBIGUOUS", reason="config_key unknown in the window "
                                            "(game.cfg Width/Height unreadable): file it")
    if not first["armed"]:
        return _verdict("GATE_C_MASKED", config_key=first["config_key"],
                        reason="the active config already had a base still, so the "
                               "auto path cannot write and the foreground gate is "
                               "untested; arm with a never-played HUD config")
    if len(new_base) > 1:
        return _verdict("AMBIGUOUS", reason="more than one base still appeared",
                        stills=[n for _, n in new_base])
    if not new_base:
        alt = _alt_stretch(samples, len(samples), first["config_key"])
        elig = _eligible_span(samples)
        if elig >= ELIGIBLE_MAX_S:
            return _verdict("NO_WRITE_WHILE_ELIGIBLE", eligible_s=round(elig, 1),
                            reason="armed, in game, League foreground and no write: triage "
                                   "the self-grab gates (vision /status capture skips)")
        return _verdict("NO_EVIDENCE", reason="armed but no still was written",
                        eligible_s=round(elig, 1), alt_tab=alt)
    i, name = new_base[0]
    before, after = samples[i - 1], samples[i]
    if name != before["base_name"] or name != after["base_name"]:
        return _verdict("AMBIGUOUS", still=name,
                        reason="the still is not the active config's (config changed "
                               "across the write)")
    alt = _alt_stretch(samples, i, after["config_key"])
    ts = seen[name]["ts"]
    bracket = {"t_before": before["t"], "t_after": after["t"], "meta_ts": ts,
               "meta_in_bracket": ts is not None and before["t"] <= ts <= after["t"]}
    games = (before["has_game"], after["has_game"])
    fgs = (before["fg_league"], after["fg_league"])
    if games == (False, False):
        return _verdict("FAIL_NO_GAME", still=name, bracket=bracket,
                        reason="written with has_game false on both sides")
    if fgs == (False, False):
        return _verdict("FAIL_CLOBBER", still=name, bracket=bracket,
                        reason="written with League NOT foreground on both sides")
    if games != (True, True) or fgs != (True, True):
        return _verdict("AMBIGUOUS", still=name, bracket=bracket,
                        reason="split bracket: re-run with a shorter --interval")
    if not bracket["meta_in_bracket"]:
        # The jpg lands before its meta json (core/vision_profiles.py), and a
        # write outside the bracket is not described by its samples.
        return _verdict("AMBIGUOUS", still=name, bracket=bracket,
                        reason="meta ts missing or outside the bracket")
    if alt["samples"] < ALT_MIN_SAMPLES or alt["span_s"] < ALT_MIN_SPAN_S:
        return _verdict("NOT_EXERCISED", still=name, bracket=bracket, alt_tab=alt,
                        reason="clean write, but no alt-tab stretch preceded it")
    return _verdict("PASS_CANDIDATE", still=name, bracket=bracket, alt_tab=alt,
                    config_key=after["config_key"],
                    still_needs="operator eyeball of the still: in-game HUD frame")


def _alt_stretch(samples: list, upto: int, config_key: str) -> dict:
    """Longest run of armed + has_game + NOT League foreground before ``upto``,
    on the same config_key as the still being graded."""
    best = {"samples": 0, "span_s": 0.0}
    run: list = []
    for s in samples[:upto]:
        if s["armed"] and s["has_game"] is True and not s["fg_league"] \
                and s["config_key"] == config_key:
            run.append(s["t"])
            if len(run) > best["samples"]:
                best = {"samples": len(run), "span_s": round(run[-1] - run[0], 1)}
        else:
            run = []
    return best


def _eligible_span(samples: list) -> float:
    best = 0.0
    start: Optional[float] = None
    for s in samples:
        if s["armed"] and s["has_game"] is True and s["fg_league"]:
            start = s["t"] if start is None else start
            best = max(best, s["t"] - start)
        else:
            start = None
    return best


def _base(arg: Optional[str]) -> Path:
    """Runtime root: --root, else the main checkout (a worktree has no stills)."""
    from tools.gated_frame_readback import main_checkout
    return Path(arg) if arg else (main_checkout(_ROOT) or _ROOT)


def _hud_key() -> str:
    from core.hud_settings import read_hud_settings
    return str(read_hud_settings().get("config_key", "unknown"))


def _fg_name() -> str:
    from core.vision_profiles import _foreground_image_name
    return _foreground_image_name()


def _sample_live(base: Path, key: Callable[[], str] = _hud_key,
                 fg: Callable[[], str] = _fg_name) -> dict:
    return make_sample(time.time(), read_has_game(base / HEALTH_REL), fg(), key(),
                       snapshot_refs(base / REF_REL))


def _iso(ts: Any) -> Optional[str]:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if _finite(ts) else None


def refs_report(sample: dict) -> dict:
    known = sample["config_key"] != "unknown"
    return {"tool": TOOL, "active_config_key": sample["config_key"],
            "armed": sample["armed"] and known, "config_key_known": known,
            "has_game": sample["has_game"],
            "stills": [{"config_key": r["config_key"], "state": r["state"],
                        "written": _iso(r["ts"]), "dims": [r["w"], r["h"]],
                        "sha12": r["sha12"]} for r in sample["refs"].values()]}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G4-23 base-capture re-validation (read-only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("refs")
    pr.add_argument("--root", help="runtime root (default: the main checkout)")
    pw = sub.add_parser("watch")
    pw.add_argument("--samples", type=int, default=150)
    pw.add_argument("--interval", type=float, default=2.0)
    pw.add_argument("--json", action="store_true")
    pw.add_argument("--root", help="runtime root (default: the main checkout)")
    return p


_EXIT = {"PASS_CANDIDATE": 0, "FAIL_CLOBBER": 3, "FAIL_NO_GAME": 3, "FAIL_REGRAB": 3,
         "NO_WRITE_WHILE_ELIGIBLE": 3}


def run(args: argparse.Namespace, sampler: Optional[Callable[[], dict]] = None,
        sleep: Callable[[float], None] = time.sleep) -> int:
    base = _base(args.root)
    take = sampler or (lambda: _sample_live(base))
    if args.cmd == "refs":
        print(json.dumps(refs_report(take()), indent=2))
        return 0
    if not 1 <= args.samples <= MAX_SAMPLES or not _finite(args.interval) \
            or args.interval < 0:
        raise ValueError("samples must be 1..1800 and interval a finite >= 0")
    samples = []
    for i in range(args.samples):
        if i:
            sleep(args.interval)
        samples.append(take())
    result = grade(samples)
    result["samples_taken"] = len(samples)
    if args.json:
        result["timeline"] = [{k: s[k] for k in ("t", "has_game", "fg_league", "armed")}
                              for s in samples]
    print(json.dumps(result, indent=2))
    return _EXIT.get(result["verdict"], 4)


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
