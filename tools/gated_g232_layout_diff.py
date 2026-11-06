"""gated_g232_layout_diff.py - read-only before / after reader for G2-32.

G2-32 asks for a live, per-panel verify of the RM-05 round-2 drag / move fixes in
``web/js/lib/overlay_layout.js`` (LEDGER 914 S2): the ``_effectiveXY`` drag origin,
the window-level move / up / cancel binds with the temporary ``data-rc-zone``
mark, and the handle-only edge press (a press whose target is the widget element
itself is ignored in ACTIVE).

Facts measured at source (s144 lane gated c70) that shape the check:

- A drop persists through ``_persist`` (400 ms debounce) to ``localStorage`` AND,
  via ``window.rcShell.setWidgetLayout``, to the shell's on-disk state:
  ``rc-shell/src/main.js`` handler ``rc-shell:overlay-layout:set`` saves
  ``overlay.widgetLayout`` into ``<userData>/rc-shell-state.json``, and
  ``rc-shell/src/overlay_state.js`` ``sanitizeWidgetLayout`` rounds x / y and keeps
  only x, y, hidden, scale per id.
- ``<userData>`` is ``<appData>/<productName>`` (``rc-shell/package.json``
  ``productName``; the S6 ``migrateUserData`` copied the old ``rc-shell`` folder
  across once), so the default path below reads that name from the package file.
- Both drag paths store the CLAMPED position (``_clampXY``: x in [0, W - 48],
  y in [0, H - 48], design px). A stored x or y below 0 is therefore always a
  breach; the upper bound depends on the overlay's design size (window size over
  the body zoom), so it is checked only when ``--width`` and ``--height`` are given.

What this reader proves and what it does not: a MOVED row is the on-disk trace of
a real drop that went through the live Electron IPC. It does NOT show that the
panel followed the cursor 1:1, that the drag survived leaving the handle, or that
an edge press stayed inert: those are eyeball halves of the row. PERSISTED never
ticks G2-32 by itself.

Sub-commands (READ-ONLY: one JSON file read, plus the registry read from
``web/js/lib/overlay_layout.js`` and ``rc-shell/package.json``; no write, no
restart, no click, no capture):

  snap [--state PATH]
      Print {"read_at", "state_mtime", "widgetLayout"} to stdout. Redirect it to
      a scratch file outside the tracked tree.
  diff BEFORE [--state PATH] [--game league|tft|all] [--width W --height H] [--json]
      Compare BEFORE (a snap) with the current file. Per registry widget: MOVED,
      UNMOVED, HIDDEN_CHANGED, SCALE_CHANGED, NEW_ENTRY, NOT_STORED. Verdict:
      PERSISTED (exit 0) when at least one widget MOVED and none is off-clamp;
      CLAMP_BREACH (exit 3) when any stored x or y is below 0, or a MOVED widget
      sits past the given --width / --height minus 48; NO_EVIDENCE
      (exit 4) when nothing moved. Exit 2 = unreadable input.

Prints no path, game id or player id (ids here are widget ids only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYOUT_JS = ROOT / "web" / "js" / "lib" / "overlay_layout.js"
SHELL_PKG = ROOT / "rc-shell" / "package.json"
STATE_NAME = "rc-shell-state.json"
FALLBACK_PRODUCT = "Amberstone Shell"
MIN_VISIBLE = 48  # overlay_layout.js MIN_VISIBLE

_ENTRY_RE = re.compile(r'\{\s*id:\s*"(w-[a-z0-9-]+)"[^}]*\}')
_GAME_RE = re.compile(r'game:\s*"([^"]*)"')

EXIT_OK = 0
EXIT_BAD_INPUT = 2
EXIT_BREACH = 3
EXIT_NO_EVIDENCE = 4


def registry(js_text: str) -> dict[str, str]:
    """Widget id -> game scope ("league" when the entry has no ``game:``)."""
    out: dict[str, str] = {}
    for m in _ENTRY_RE.finditer(js_text):
        g = _GAME_RE.search(m.group(0))
        out.setdefault(m.group(1), g.group(1) if g else "league")
    return out


def product_name(pkg_text: str | None) -> str:
    try:
        name = json.loads(pkg_text or "").get("productName")
    except (ValueError, AttributeError):
        name = None
    return name if isinstance(name, str) and name.strip() else FALLBACK_PRODUCT


def default_state_path() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    try:
        pkg = SHELL_PKG.read_text(encoding="utf-8")
    except OSError:
        pkg = None
    return Path(appdata) / product_name(pkg) / STATE_NAME


def layout_from_state(state: object) -> dict[str, dict]:
    """Mirror of overlay_state.js widgetLayoutFrom + sanitizeWidgetLayout."""
    if not isinstance(state, dict):
        return {}
    overlay = state.get("overlay")
    if not isinstance(overlay, dict):
        return {}
    raw = overlay.get("widgetLayout")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for wid, e in raw.items():
        if not isinstance(e, dict):
            continue
        clean: dict = {}
        for k in ("x", "y"):
            v = e.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                clean[k] = round(v)
        if isinstance(e.get("hidden"), bool):
            clean["hidden"] = e["hidden"]
        s = e.get("scale")
        if isinstance(s, (int, float)) and not isinstance(s, bool):
            clean["scale"] = s
        out[str(wid)] = clean
    return out


def clamp_problem(entry: dict, width: int | None, height: int | None) -> str | None:
    """Why a stored position breaks _clampXY semantics, or None."""
    x, y = entry.get("x"), entry.get("y")
    if x is None or y is None:
        return None
    if x < 0 or y < 0:
        return "below 0"
    if width and height and (x > max(0, width - MIN_VISIBLE) or y > max(0, height - MIN_VISIBLE)):
        return f"past {width}x{height} minus {MIN_VISIBLE}"
    return None


def classify(before: dict | None, after: dict | None) -> list[str]:
    if after is None:
        return ["NOT_STORED"] if before is None else ["NOT_STORED", "ENTRY_DROPPED"]
    if before is None:
        return ["NEW_ENTRY", "MOVED"] if "x" in after or "y" in after else ["NEW_ENTRY"]
    tags = []
    if (before.get("x"), before.get("y")) != (after.get("x"), after.get("y")):
        tags.append("MOVED")
    if before.get("hidden", False) != after.get("hidden", False):
        tags.append("HIDDEN_CHANGED")
    if before.get("scale", 1) != after.get("scale", 1):
        tags.append("SCALE_CHANGED")
    return tags or ["UNMOVED"]


def diff(before_layout: dict, after_layout: dict, reg: dict[str, str], game: str,
         width: int | None = None, height: int | None = None) -> dict:
    rows = []
    breaches = []
    for wid, scope in reg.items():
        if game != "all" and scope not in (game, "*"):
            continue
        b, a = before_layout.get(wid), after_layout.get(wid)
        tags = classify(b, a)
        row = {"id": wid, "tags": tags}
        was_moved = "MOVED" in tags and a is not None
        if was_moved:
            row["after"] = [a.get("x"), a.get("y")]
            if b is not None and all(isinstance(e.get(k), int) for e in (a, b) for k in ("x", "y")):
                row["dx"] = a["x"] - b["x"]
                row["dy"] = a["y"] - b["y"]
        # The upper bound only binds a panel dragged in THIS window: an undragged
        # position saved at another window size is not a drag defect.
        problem = clamp_problem(a or {}, width if was_moved else None,
                                height if was_moved else None)
        if problem:
            row["clamp"] = problem
            breaches.append(wid)
        rows.append(row)
    stale = sorted(k for k in after_layout if k not in reg)
    moved = [r["id"] for r in rows if "MOVED" in r["tags"]]
    if breaches:
        verdict = "CLAMP_BREACH"
    elif moved:
        verdict = "PERSISTED"
    else:
        verdict = "NO_EVIDENCE"
    return {"verdict": verdict, "moved": moved, "breaches": breaches,
            "rows": rows, "stale_ids": stale,
            "upper_bound_checked": bool(width and height)}


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def cmd_snap(args: argparse.Namespace) -> int:
    path = Path(args.state) if args.state else default_state_path()
    if path is None or not path.is_file():
        print("state file not found", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        state = _load_json(path)
        mtime = path.stat().st_mtime
    except (OSError, ValueError) as exc:
        print(f"state file unreadable: {type(exc).__name__}", file=sys.stderr)
        return EXIT_BAD_INPUT
    snap = {"read_at": _iso(datetime.now(timezone.utc).timestamp()),
            "state_mtime": _iso(mtime), "widgetLayout": layout_from_state(state)}
    print(json.dumps(snap, indent=1, sort_keys=True))
    return EXIT_OK


def cmd_diff(args: argparse.Namespace) -> int:
    path = Path(args.state) if args.state else default_state_path()
    try:
        before = _load_json(Path(args.before))
        before_layout = before.get("widgetLayout") if isinstance(before, dict) else None
        if not isinstance(before_layout, dict):
            raise ValueError("no widgetLayout in BEFORE")
        if path is None or not path.is_file():
            raise OSError("state file not found")
        after_layout = layout_from_state(_load_json(path))
        mtime = _iso(path.stat().st_mtime)
        reg = registry(LAYOUT_JS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"unreadable input: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    res = diff(before_layout, after_layout, reg, args.game, args.width, args.height)
    res["before_state_mtime"] = before.get("state_mtime")
    res["after_state_mtime"] = mtime
    if args.json:
        print(json.dumps(res, indent=1, sort_keys=True))
    else:
        print(f"verdict {res['verdict']}  moved {len(res['moved'])}  "
              f"state_mtime {res['before_state_mtime']} -> {mtime}")
        for r in res["rows"]:
            extra = ""
            if "dx" in r:
                extra = f"  d=({r['dx']},{r['dy']})"
            if "after" in r:
                extra += f"  at={tuple(r['after'])}"
            if "clamp" in r:
                extra += f"  CLAMP: {r['clamp']}"
            print(f"  {r['id']:<16} {','.join(r['tags'])}{extra}")
        if res["stale_ids"]:
            print(f"  not in registry (ignored by the overlay): {', '.join(res['stale_ids'])}")
        if not res["upper_bound_checked"]:
            print("  upper clamp bound not checked (pass --width and --height in design px)")
    return {"PERSISTED": EXIT_OK, "CLAMP_BREACH": EXIT_BREACH}.get(res["verdict"], EXIT_NO_EVIDENCE)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snap")
    s.add_argument("--state")
    d = sub.add_parser("diff")
    d.add_argument("before")
    d.add_argument("--state")
    d.add_argument("--game", choices=("league", "tft", "all"), default="league")
    d.add_argument("--width", type=int)
    d.add_argument("--height", type=int)
    d.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return cmd_snap(args) if args.cmd == "snap" else cmd_diff(args)


if __name__ == "__main__":
    sys.exit(main())
