"""gated_g241_ocr_native.py - read-only A/B grader for G2-41 (OCR native-res crop).

G2-41 asks whether the live OCR read path should crop from a NATIVE screen grab
(``core/screen_grab.grab_native``) instead of the 1280-wide relay frame it reads
today. Measured at source (s144 lane gated c45):

- ``grab_native`` has NO production caller. The coach OCR path is
  ``modes/shared_vision._capture_screen`` -> GET ``:8889/latest-frame`` ->
  ``core/vision_routing.read_or_escalate`` -> ``core/vision_tesseract
  .read_fast_fields``, and that frame is downscaled to
  ``vision_server/_frame.py`` ``_SELF_GRAB_MAX_WIDTH`` (1280), so a native
  2560x1440 profile's boxes are scaled down 0.5x at crop time
  (``_scale_bbox``; guarded by ``tests/test_vision_tesseract_halved_frame_r98.py``).
- ``read_fast_fields`` cannot be called twice in one process to compare two
  frames: ``timer`` is a SLOW field read on one call in ``_SLOW_MODULO`` (5)
  and otherwise served from the module-global ``_slow_cache``, so the second
  frame would silently report the FIRST frame's clock. ``_DROP_FIELDS`` is
  module-global too. This tool therefore runs the same per-field crop and
  parse (``_regions`` / ``_decode_img`` / ``_scale_bbox`` / ``_crop`` /
  ``_parse_field``) on each frame directly, with no cadence, cache or drop set.

One sample = truth read 0 (``:2999`` ``activePlayer.currentGold`` /
``activePlayer.level`` / ``gameData.gameTime``), the relay frame (halved), the
native grab, truth read 1. Each frame's OCR of ``gold`` / ``level`` / ``timer``
is graded against the truth bracket (predicates in ``grade_value``; stated
before any game). The verdict over all samples:

  NATIVE_BETTER  native match rate >= halved on every conclusive field and
                 higher on at least one by >= 2 samples' worth (one buy or kill
                 just before read 0 can cost the older relay frame one sample)
                 -> wiring is worth a flagged
                 slice (still default OFF until a drain re-reads it wired).
  NO_GAIN        neither of the above: equal rates, or a native gain worth
                 under 2 samples, on every conclusive field -> the halved frame
                 already reads these fields; wiring buys nothing measured.
  HALVED_BETTER  halved beats native on some field -> do NOT wire; look at
                 the native grab (alt-tab, black frame, wrong monitor).
  NO_RESULT      fewer than ``--min-valid`` valid samples on every field, no
                 MATCH at all on either path (no Tesseract, wrong boxes, a
                 menu over the HUD), or the regions are not a calibrated native
                 profile (run it from the MAIN checkout: the profiles under
                 ``data/vision_profiles/`` are gitignored and per machine).

READ-ONLY. It never writes, never saves a frame, never prints the token, and
never ticks a row. It REFUSES (exit 2) before ANY capture unless ``:2999``
answers with an ``activePlayer`` (a game is up), and it skips the native grab
whenever League is not the foreground window (an alt-tabbed grab would be the
desktop). The native grab is a screen capture: run it only in a live drain.

USAGE
    python tools/gated_g241_ocr_native.py [--samples 5] [--interval 3]
        [--max-age 2.0] [--min-valid 3] [--json]

Exit 0 = a decisive verdict; 1 = NO_RESULT; 2 = not in game (nothing
captured); 3 = no vision token.
"""
from __future__ import annotations

import argparse
import json
import math
from fractions import Fraction
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

FIELDS = ("gold", "level", "timer")
DECISIVE = ("NATIVE_BETTER", "NO_GAIN", "HALVED_BETTER")
# Passive gold income on SR is about 2 g/s; 3 g/s plus a 2 g floor-and-rounding
# slack is the most the HUD can move between two reads with no kill or buy.
GOLD_RATE_MAX = 3.0
GOLD_SLACK = 2
TIMER_SLACK_S = 1
FUTURE_SKEW_S = 0.5      # a relay ts this far ahead of the probe clock is bad
MARGIN_SAMPLES = 2       # NATIVE_BETTER needs a gain worth >= 2 samples
_RELAY_URL = "http://127.0.0.1:8889/latest-frame"
_TIMEOUT = 5.0


def _game_url() -> str:
    sys.path.insert(0, str(_ROOT))
    from core.game_host import GAME_HOST  # noqa: PLC0415
    return f"https://{GAME_HOST}:2999/liveclientdata/allgamedata"


def parse_clock(text) -> int | None:
    """``"m:ss"`` -> seconds, else None."""
    if not isinstance(text, str) or text.count(":") != 1:
        return None
    mm, ss = text.split(":")
    if not (mm.isdigit() and ss.isdigit() and len(ss) == 2 and int(ss) < 60):
        return None
    return int(mm) * 60 + int(ss)


def truth_from(doc, wall: float) -> dict | None:
    """``{wall, game_time, gold, level}`` from an allgamedata reply, or None."""
    if not isinstance(doc, dict):
        return None
    ap = doc.get("activePlayer")
    gd = doc.get("gameData")
    if not isinstance(ap, dict) or not isinstance(gd, dict):
        return None
    gold, level, gt = ap.get("currentGold"), ap.get("level"), gd.get("gameTime")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in (gold, level, gt)):
        return None
    return {"wall": float(wall), "game_time": float(gt),
            "gold": int(math.floor(gold)), "level": int(level)}


def grade_value(field: str, value, t0: dict, t1: dict, tc: float) -> tuple[str, str]:
    """``(grade, why)`` for one OCR value captured at wall time ``tc``.

    grade is MATCH, MISS, NONE (OCR returned nothing; counts as a miss) or
    VOID (the truth moved too much to grade this field in this sample).
    Predicates, fixed before any game:
      level  MATCH iff level0 == level1 == value; VOID if the level changed.
      gold   VOID if |gold1 - gold0| > 3 g/s x (t1 - t0) + 2 (a kill or a buy
             inside the sample). Else MATCH iff value lies in
             [min(g0, g1) - 3 x max(0, t0 - tc) - 2, max(g0, g1) + 2].
      timer  MATCH iff the m:ss value in seconds lies in
             [floor(gt0 - max(0, t0 - tc)) - 1, floor(gt1) + 1].
    """
    lead = max(0.0, t0["wall"] - tc)
    if field == "level":
        if t0["level"] != t1["level"]:
            return "VOID", "level changed inside the sample"
        if value is None:
            return "NONE", "no read"
        return ("MATCH", "") if value == t0["level"] else ("MISS", f"truth {t0['level']}")
    if field == "gold":
        g0, g1 = t0["gold"], t1["gold"]
        span = max(0.0, t1["wall"] - t0["wall"])
        if abs(g1 - g0) > GOLD_RATE_MAX * span + GOLD_SLACK:
            return "VOID", f"gold moved {g0} -> {g1} (kill or buy)"
        if value is None:
            return "NONE", "no read"
        lo = min(g0, g1) - GOLD_RATE_MAX * lead - GOLD_SLACK
        hi = max(g0, g1) + GOLD_SLACK
        ok = isinstance(value, (int, float)) and lo <= value <= hi
        return ("MATCH", "") if ok else ("MISS", f"truth {g0}..{g1}")
    if field == "timer":
        if value is None:
            return "NONE", "no read"
        secs = parse_clock(value)
        lo = math.floor(t0["game_time"] - lead) - TIMER_SLACK_S
        hi = math.floor(t1["game_time"]) + TIMER_SLACK_S
        if secs is not None and lo <= secs <= hi:
            return "MATCH", ""
        return "MISS", f"truth {lo + TIMER_SLACK_S}..{hi - TIMER_SLACK_S} s"
    raise ValueError(f"unknown field {field!r}")


def verdict(samples: list[dict], min_valid: int = 3) -> dict:
    """Tally every graded sample and name the row verdict."""
    rates: dict = {}
    for f in FIELDS:
        row = {}
        for path in ("halved", "native"):
            grades = [s[path]["grades"][f][0] for s in samples
                      if s.get(path, {}).get("grades", {}).get(f)]
            valid = [g for g in grades if g != "VOID"]
            row[path] = {"valid": len(valid), "match": valid.count("MATCH")}
        row["conclusive"] = all(row[p]["valid"] >= min_valid for p in ("halved", "native"))
        rates[f] = row
    conclusive = [f for f in FIELDS if rates[f]["conclusive"]]
    if not conclusive:
        return {"verdict": "NO_RESULT", "why": f"no field has {min_valid} valid samples on both paths",
                "fields": rates}

    if not any(rates[f][p]["match"] for f in conclusive for p in ("halved", "native")):
        # 0 of N on both paths is not "no gain": OCR read nothing at all
        # (no Tesseract, wrong boxes, a menu over the HUD).
        return {"verdict": "NO_RESULT", "why": "neither path matched any field",
                "fields": rates}

    def rate(f, p):
        return Fraction(rates[f][p]["match"], rates[f][p]["valid"])

    worse = [f for f in conclusive if rate(f, "halved") > rate(f, "native")]
    # One buy, kill or level-up between the relay frame's capture and truth
    # read 0 turns a halved read into a MISS the VOID rules cannot see, so a
    # native gain must be worth at least MARGIN_SAMPLES samples.
    better = [f for f in conclusive
              if (rate(f, "native") - rate(f, "halved"))
              * min(rates[f]["halved"]["valid"], rates[f]["native"]["valid"]) >= MARGIN_SAMPLES]
    if worse:
        v = "HALVED_BETTER"
    elif better:
        v = "NATIVE_BETTER"
    else:
        v = "NO_GAIN"
    return {"verdict": v, "conclusive": conclusive, "native_better_on": better,
            "halved_better_on": worse, "fields": rates}


# -- seams the tests replace -------------------------------------------------

def _default_truth_fetch() -> dict | None:
    sys.path.insert(0, str(_ROOT))
    from core.tls_policy import client_context_noverify  # noqa: PLC0415
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=client_context_noverify()))
    try:
        with opener.open(_game_url(), timeout=3.0) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _default_relay_fetch(token: str) -> tuple[str | None, dict]:
    """``(b64, meta)`` from ONE relay GET; b64 None on any failure."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gated_frame_readback as fr  # noqa: PLC0415 - sibling tool
    req = urllib.request.Request(_RELAY_URL, headers={"X-RC-Token": token})
    try:
        with fr._OPENER.open(req, timeout=_TIMEOUT) as resp:
            body = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        return None, {"error": type(exc).__name__}
    try:
        env = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, {"error": "reply is not a JSON envelope"}
    if not isinstance(env, dict) or not isinstance(env.get("b64"), str):
        return None, {"error": "envelope carried no b64"}
    return env["b64"], {k: v for k, v in env.items() if k != "b64"}


def _default_native_grab() -> dict:
    sys.path.insert(0, str(_ROOT))
    from core.screen_grab import grab_native  # noqa: PLC0415
    return grab_native()


def _default_foreground() -> bool:
    sys.path.insert(0, str(_ROOT))
    from core.vision_profiles import _league_is_foreground  # noqa: PLC0415
    return _league_is_foreground()


def _default_token() -> tuple[str, str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gated_frame_readback as fr  # noqa: PLC0415
    return fr.resolve_token()


def ocr_fields(img_b64: str, fields=FIELDS, vt=None) -> dict:
    """Per-field crop + parse of ONE frame, with no cadence, cache or drop set.

    Same functions ``read_fast_fields`` runs per field; see the module doc for
    why that function itself cannot be used for an A/B in one process.
    """
    if vt is None:
        sys.path.insert(0, str(_ROOT))
        from core import vision_tesseract as vt  # noqa: PLC0415
    vt._ensure_tesseract()
    regions = vt._regions()
    img = vt._decode_img(img_b64)
    fw, fh = img.size
    out = {"frame": [fw, fh], "values": {}, "boxes": {}}
    for name in fields:
        bbox = regions.get(name)
        if not bbox:
            out["values"][name] = None
            continue
        box = vt._scale_bbox(bbox, fw, fh)
        out["boxes"][name] = list(box)
        try:
            out["values"][name] = vt._parse_field(name, vt._crop(img, box))
        except Exception as exc:  # noqa: BLE001 - one field failing is a NONE
            out["values"][name] = None
            out.setdefault("errors", {})[name] = type(exc).__name__
    return out


def regions_facts(vt=None) -> dict:
    """Which region table the probe process loaded, and at which base."""
    if vt is None:
        sys.path.insert(0, str(_ROOT))
        from core import vision_tesseract as vt  # noqa: PLC0415
    facts = {"source": "unknown"}
    try:
        from core.vision_profiles import load_profile  # noqa: PLC0415
        prof = load_profile()
        facts["source"] = prof.get("source", "unknown")
        facts["config_key"] = prof.get("config_key")
    except Exception as exc:  # noqa: BLE001
        facts["error"] = type(exc).__name__
    vt._regions()
    facts["base"] = list(vt._BASE_CACHE)
    facts["hud_color_installed"] = bool(getattr(vt, "_HUD_COLOR", {}))
    return facts


def _grade_frame(ocr: dict, t0: dict, t1: dict, tc: float) -> dict:
    return {f: list(grade_value(f, ocr["values"].get(f), t0, t1, tc)) for f in FIELDS}


def collect(samples: int = 5, interval: float = 3.0, max_age: float = 2.0,
            truth_fetch=None, relay_fetch=None, native_grab=None,
            foreground=None, token=None, ocr=None, clock=time.time,
            sleep=time.sleep) -> tuple[int, dict]:
    """Take the samples and return ``(exit_code, report)``."""
    truth_fetch = truth_fetch or _default_truth_fetch
    relay_fetch = relay_fetch or _default_relay_fetch
    native_grab = native_grab or _default_native_grab
    foreground = foreground or _default_foreground
    ocr = ocr or ocr_fields
    report: dict = {"samples": []}
    first = truth_from(truth_fetch(), clock())
    if first is None:
        report["verdict"] = {"verdict": "NOT_IN_GAME",
                             "why": ":2999 gave no activePlayer; nothing captured"}
        return 2, report
    tok, tok_source = (token or _default_token)()
    report["token_source"] = tok_source
    if not tok:
        report["verdict"] = {"verdict": "NO_RESULT", "why": "no vision token"}
        return 3, report
    for i in range(samples):
        if i:
            sleep(interval)
        t0 = first if i == 0 else truth_from(truth_fetch(), clock())
        if t0 is None:
            report["samples"].append({"i": i, "void": "game ended"})
            break
        s: dict = {"i": i, "t0": t0}
        b64, meta = relay_fetch(tok)
        meta = meta if isinstance(meta, dict) else {}
        t_relay = clock()
        ts = meta.get("ts") if isinstance(meta, dict) else None
        has_ts = isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0
        tc_h = float(ts) if has_ts else t_relay
        s["halved_meta"] = {k: meta.get(k) for k in ("source", "width", "height", "error")
                            if isinstance(meta, dict) and k in meta}
        s["halved_meta"]["age_s"] = round(t_relay - tc_h, 2) if has_ts else None
        fg = bool(foreground())
        s["foreground"] = fg
        native = native_grab() if fg else {"ok": False, "error": "League not foreground"}
        tc_n = clock()
        t1 = truth_from(truth_fetch(), clock())
        if t1 is None:
            s["void"] = "game ended mid-sample"
            report["samples"].append(s)
            break
        s["t1"] = t1
        age = t_relay - tc_h
        if not b64:
            s["halved_void"] = meta.get("error") or "no frame"
        elif not has_ts:
            s["halved_void"] = "frame carries no ts"     # capture time unknown
        elif age < -FUTURE_SKEW_S:
            s["halved_void"] = "frame ts in the future"
        elif age > max_age:
            s["halved_void"] = f"frame older than {max_age} s"
        else:
            o = ocr(b64)
            s["halved"] = {"frame": o["frame"], "values": o["values"],
                           "grades": _grade_frame(o, t0, t1, tc_h)}
        if native.get("ok"):
            o = ocr(native["b64"])
            s["native"] = {"frame": o["frame"], "values": o["values"],
                           "grades": _grade_frame(o, t0, t1, tc_n)}
        else:
            s["native_void"] = native.get("reason") or native.get("error")
        report["samples"].append(s)
    return 0, report


def _render(report: dict) -> str:
    out = []
    reg = report.get("regions") or {}
    if reg:
        out.append(f"regions source {reg.get('source')}  base {reg.get('base')}  "
                   f"hud_color {reg.get('hud_color_installed')}")
    for s in report.get("samples", []):
        line = [f"#{s['i']}"]
        if "t0" in s:
            line.append(f"gt {s['t0']['game_time']:.1f}")
        for p in ("halved", "native"):
            if p in s:
                g = s[p]["grades"]
                line.append(f"{p} {s[p]['frame'][0]}x{s[p]['frame'][1]} "
                            + " ".join(f"{f}={s[p]['values'].get(f)}:{g[f][0]}" for f in FIELDS))
            elif f"{p}_void" in s:
                line.append(f"{p} VOID ({s[p + '_void']})")
        if "void" in s:
            line.append(f"VOID ({s['void']})")
        out.append("  ".join(line))
    v = report.get("verdict", {})
    out.append(f"VERDICT {v.get('verdict')}  {v.get('why', '')}".rstrip())
    for f, row in (v.get("fields") or {}).items():
        out.append(f"  {f}: halved {row['halved']['match']}/{row['halved']['valid']}  "
                   f"native {row['native']['match']}/{row['native']['valid']}  "
                   f"conclusive {row['conclusive']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--max-age", type=float, default=2.0)
    ap.add_argument("--min-valid", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    code, report = collect(a.samples, a.interval, a.max_age)
    if code == 0:
        try:
            sys.path.insert(0, str(_ROOT))
            from core import vision_tesseract as vt  # noqa: PLC0415
            vt._ensure_tesseract()
            report["regions"] = regions_facts(vt)
        except Exception as exc:  # noqa: BLE001
            report["regions"] = {"source": "unknown", "error": type(exc).__name__}
        report["verdict"] = verdict(report["samples"], a.min_valid)
        if report["regions"].get("source") != "profile" and report["verdict"]["verdict"] in DECISIVE:
            report["verdict"] = {"verdict": "NO_RESULT", "fields": report["verdict"]["fields"],
                                 "why": f"regions source {report['regions'].get('source')}, "
                                        "not a calibrated native profile (run from the main checkout)"}
        if report["verdict"]["verdict"] not in DECISIVE:
            code = 1
    print(json.dumps(report, indent=2, sort_keys=True) if a.json else _render(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
