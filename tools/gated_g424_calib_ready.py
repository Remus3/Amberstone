"""gated_g424_calib_ready.py - read-only calibration-readiness grader for G4-24.

G4-24 asks for the VISION-OCR boxes to be recalibrated at 2560x1440 through
``/vision-calibrator`` against a reference still in
``data/vision_calib_reference/``, and then validated against rendered in-game
HUD pixels. Facts measured at source (s144 lane gated c80) that shape it:

- A calibration is keyed by the FULL HUD ``config_key``
  (``core.hud_settings.read_hud_settings``: ``WxH`` plus every
  ``_LAYOUT_KEYS`` toggle), and ``core.vision_profiles.load_profile`` uses a
  profile only on an EXACT key match (tier ``profile``); anything else falls to
  a proportional seed (tier ``resolution_seed``) or the 1080p legacy table
  (tier ``legacy_seed``). A profile calibrated at one GlobalScale /
  MinimapScale says nothing about another.
- ``tools/gated_g241_ocr_native.py`` refuses a decisive verdict unless
  ``load_profile()`` reports ``source == "profile"``, so G2-41's A/B waits on
  this row whenever the live key has no profile.

This tool answers, with no game needed and nothing written: is there a
calibrated profile for the live key, a base still to calibrate against, and if
not, which toggles separate the live HUD from every calibrated profile.

READ-ONLY: reads League's game.cfg via ``core.hud_settings``, and the JSON files
under ``<root>/data/vision_profiles/`` and ``<root>/data/vision_calib_reference/``
(root = --root, else the main checkout). No write, no capture, no restart, no
LCU call, no tick. Prints no game id or player id.

Verdicts: CALIBRATED (exit 0) - an exact profile exists, so the recalibration
half is not owed for this key and only the live read validation (G2-41's probe)
is left; READY_TO_CALIBRATE (exit 3) - a base still exists for the key but no
profile; NEEDS_REFERENCE (exit 3) - neither exists, so a G4-23 base still comes
first; KEY_UNKNOWN (exit 4) - game.cfg yields no config_key (no usable
Width/Height), so nothing can be keyed yet. No verdict ticks G4-24.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TOOL = "gated_g424_calib_ready"
PROFILES_REL = Path("data") / "vision_profiles"
REF_REL = Path("data") / "vision_calib_reference"
UNKNOWN = "unknown"
MAX_FILE_BYTES = 1 << 20
_EXIT = {"CALIBRATED": 0, "READY_TO_CALIBRATE": 3, "NEEDS_REFERENCE": 3,
         "KEY_UNKNOWN": 4}


def parse_key(config_key: Any) -> Optional[tuple]:
    """``(res, {toggle: value})`` for a ``WxH|K=V|...`` key, else None."""
    parts = str(config_key or "").split("|")
    res = parts[0].strip()
    if not res or res == UNKNOWN or "x" not in res:
        return None
    toggles = {}
    for p in parts[1:]:
        k, sep, v = p.partition("=")
        if not sep or not k:
            return None
        toggles[k] = v
    return res, toggles


def live_layout(hud: dict) -> dict:
    """The live layout toggles, keyed like a config_key (known or not)."""
    from core.hud_settings import _LAYOUT_KEYS
    layout = hud.get("layout") or {}
    return {k: str(layout.get(k, "?")) for k in _LAYOUT_KEYS}


def _read_json(path: Path) -> Optional[dict]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def scan_keys(directory: Path, *, base_only: bool = False) -> list:
    """Sorted config_keys named INSIDE the JSON files of ``directory``.

    ``base_only`` skips named-state sidecars (``<stem>__<state>.json``), which
    are not the base still a calibration is drawn on."""
    keys = set()
    if not directory.is_dir():
        return []
    for p in sorted(directory.glob("*.json")):
        if base_only and "__" in p.stem:
            continue
        d = _read_json(p)
        ck = d.get("config_key") if d else None
        if isinstance(ck, str) and parse_key(ck):
            keys.add(ck)
    return sorted(keys)


def diff_toggles(layout: dict, config_key: str, live_res: Optional[str] = None) -> dict:
    """{toggle: [live, calibrated]} for every toggle that differs, plus
    ``_res`` when the live resolution is known and differs."""
    parsed = parse_key(config_key)
    if not parsed:
        return {"_unparseable": [None, config_key]}
    res, cal = parsed
    out = {k: [layout.get(k), cal.get(k)]
           for k in sorted(set(layout) | set(cal)) if layout.get(k) != cal.get(k)}
    if live_res and live_res != res:
        out["_res"] = [live_res, res]
    return out


def predicted_tier(live_key: str, profiles: list, res: Optional[str]) -> str:
    """The ``load_profile`` tier the live key would resolve to (no seed FILE
    is assumed: data/vision_profiles/ seeds are not written in production)."""
    if live_key in profiles:
        return "profile"
    if res and res in profiles:
        return "resolution_seed"
    from core.vision_profiles import SEED_BASES
    if res and [int(n) for n in res.split("x")] in SEED_BASES:
        return "resolution_seed"
    return "legacy_seed"


def grade(hud: dict, profiles: list, refs: list) -> dict:
    live_key = str(hud.get("config_key") or UNKNOWN)
    layout = live_layout(hud)
    parsed = parse_key(live_key)
    res = parsed[0] if parsed else None
    nearest = sorted(({"config_key": ck, "differs": diff_toggles(layout, ck, res)}
                      for ck in profiles),
                     key=lambda r: (len(r["differs"]), r["config_key"]))
    out = {"tool": TOOL, "live_config_key": live_key, "live_layout": layout,
           "profiles": profiles, "base_stills": refs,
           "layout_matches_a_profile": any(not r["differs"] for r in nearest),
           "nearest_profiles": nearest}
    if not parsed:
        out.update(verdict="KEY_UNKNOWN", predicted_tier="legacy_seed",
                   why="game.cfg gives no usable Width/Height, so no profile can key")
    elif live_key in profiles:
        out.update(verdict="CALIBRATED", predicted_tier="profile",
                   why="exact profile exists; only the live read validation is left")
    elif live_key in refs:
        out.update(verdict="READY_TO_CALIBRATE",
                   predicted_tier=predicted_tier(live_key, profiles, res),
                   why="base still exists for the live key, no profile")
    else:
        out.update(verdict="NEEDS_REFERENCE",
                   predicted_tier=predicted_tier(live_key, profiles, res),
                   why="no profile and no base still for the live key")
    return out


def _base(arg: Optional[str]) -> Path:
    """Runtime root: --root, else the main checkout (a worktree has no data)."""
    from tools.gated_frame_readback import main_checkout
    return Path(arg) if arg else (main_checkout(_ROOT) or _ROOT)


def _read_hud() -> dict:
    from core.hud_settings import read_hud_settings
    return read_hud_settings()


def run(root: Path, hud: Optional[dict] = None) -> tuple:
    h = _read_hud() if hud is None else hud
    result = grade(h, scan_keys(root / PROFILES_REL),
                   scan_keys(root / REF_REL, base_only=True))
    return result, _EXIT[result["verdict"]]


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="G4-24 calibration readiness (read-only)")
    p.add_argument("--root", help="runtime root (default: the main checkout)")
    args = p.parse_args(argv)
    try:
        result, code = run(_base(args.root))
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
