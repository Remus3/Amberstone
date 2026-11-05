"""gated_lx11_minimap_check.py - plan and grade the LX-11 replay-scrubber minimap check.

LX-11 (RM-612) is a RENDER question on the real dashboard: on the Replay view
the past-match minimap draws its map art, a champion badge with an ally or
enemy ring for every champion it can place, the "sampled every 60 s" note, and
it HIDES a champion for the whole of a death window (a cross marks the spot).

The positions come from Match-V5 timeline frames already stored in
``rewind_history.db`` (``core/replay_history.match_detail``, served as
``/api/replay/match/<id>``), so the row needs a REAL stored match and the REAL
dashboard, not a game in progress.

Two subcommands, both READ-ONLY (they read files and print; no network call,
no write, no tick):

``plan --match-json F``
    F is the body of ``/api/replay/match/<id>`` saved from the real dashboard.
    Node runs the SHIPPED ``web/js/panels/replay_minimap.js`` (``buildModel`` /
    ``stateAt`` / ``worldToCanvas``, the code ``dev.js`` draws with; nothing is
    re-implemented here) over every stored frame, and the tool picks the first
    slider index whose canvas holds at least one dead champion and one ally and
    one enemy badge that do not overlap anything else (``--index`` overrides).
    It prints what the canvas MUST show at that index: canvas pixel centres of
    every badge with its ring role, every death cross, the map clock text and
    the frame clock text.

``grade --plan P --evidence E``
    E is the bundle the ``snippet`` subcommand's browser expression returns in
    the dashboard tab (DOM text, the resolved ring colour tokens and the canvas
    as a PNG data URL). The grader samples the canvas: map art coverage, the
    ring annulus at radius R around each unobstructed badge, and, for each
    dead champion, that NO ring is drawn at its death spot while the cross is.

NO MATCH ID IS EVER PRINTED (RM-906). The plan carries only a truncated
SHA-256 of the match id; the grader hashes the id it finds in the evidence's
``#replay-meta`` text and reports ``match_tie`` true / false.

SUBSTITUTION. ``tests/test_gated_lx11_minimap_check.py`` reaches ``PASS`` from
canvases drawn by PIL and a hand-built match. A PASS here counts only when the
evidence bundle was read from the real dashboard tab (``href`` on the :8888
origin, ``ui_mock`` not "1": the ui_mock fixture serves
``/data/ui_mock/replay.json`` instead of ``/api/replay/*``) for the same match
the plan was built from (``match_tie``), at the planned index (both clocks).

Exit codes: 0 = PASS (grade) or a plan printed; 1 = FAIL (a definite
contradiction on PROVEN evidence - real origin, ui_mock off, the planned
match: a missing ring, a ring on a dead champion, no art, a hidden Replay view
or figure, a canvas of another size, wrong note); 3 = INCONCLUSIVE (nothing contradicts, but a needed check
could not be made, or the bundle is not evidence for this plan: wrong origin,
ui_mock on, another match, or a capture at the wrong slider index or clock);
2 = unreadable input, a hidden-map match, or
a usage error.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
MINIMAP_JS = ROOT / "web" / "js" / "panels" / "replay_minimap.js"
INDEX_HTML = ROOT / "web" / "index.html"

COLOR_TOL = 60.0          # RGB distance for "this pixel is the ring colour"
RING_OK_FRAC = 0.6        # solid ring: share of annulus samples on colour
RING_OK_FRAC_DASHED = 0.35  # revive-suspected ring is dashed [4, 3]
RING_ABSENT_FRAC = 0.2
CROSS_MARGIN = 20.0       # a cross pixel is this much closer to the colour than its control
CROSS_OK_FRAC = 0.6
ART_OK_FRAC = 0.9         # share of opaque pixels when the map art is drawn
ART_MISSING_FRAC = 0.3
ART_MIN_COLOURS = 16      # distinct colours on a sample grid; a flat fill is not map art
RING_SAMPLES = 72
NOTE_FRAGMENT = "sampled every 60 s"

_NODE_SRC = r"""
import { readFileSync } from "node:fs";
const req = JSON.parse(readFileSync(0, "utf8"));
const mm = await import(req.module_url);
const d = req.match;
const W = req.w, H = req.h;
const model = mm.buildModel(d);
const out = { kind: model.kind, hidden: model.hidden, frames: [] };
if (!model.hidden) {
  const tracked = (d.participants || []).find((p) =>
    p.champion_id === (d.tracked && d.tracked.champion_id));
  out.ally_team = tracked ? tracked.team_id : 100;
  out.units_to_px = W / (mm.MAP_WORLD[model.kind] || mm.MAP_WORLD.sr);
  (d.snapshots || []).forEach((snap, idx) => {
    const t = Number(snap.timestamp_ms);
    const states = [];
    for (const p of d.participants || []) {
      const s = mm.stateAt(model, p.participant_id, t);
      const row = { pid: p.participant_id, team: p.team_id,
                    visible: !!s.visible, dead: !!s.dead };
      if (s.visible) {
        row.xy = mm.worldToCanvas(s.pos, model.kind, W, H);
        row.halo_units = s.haloUnits;
        row.revive = !!s.revive;
        row.src = s.src;
      }
      if (s.dead && s.deathPos) row.cross_xy = mm.worldToCanvas(s.deathPos, model.kind, W, H);
      states.push(row);
    }
    out.frames.push({ idx, t_ms: t, minute: snap.minute, states });
  });
}
process.stdout.write(JSON.stringify(out));
"""

SNIPPET = r"""() => {
  const $ = (id) => document.getElementById(id);
  const cs = getComputedStyle(document.documentElement);
  const c = $("replay-map-canvas"), fig = $("replay-map-figure");
  const note = fig ? fig.querySelector(".replay-map-note") : null;
  const txt = (el) => (el ? el.textContent : null);
  return {
    tool: "gated_lx11_minimap_check",
    captured_at: new Date().toISOString(),
    href: location.href,
    ui_mock: (document.body && document.body.dataset.uiMock) || "",
    view_hidden: $("view-replay") ? $("view-replay").hidden : null,
    figure_hidden: fig ? fig.hidden : null,
    note_text: txt(note),
    note_visible: note ? (note.getClientRects().length > 0
      && getComputedStyle(note).visibility !== "hidden") : null,
    map_clock_text: txt($("replay-map-clock")),
    frame_clock_text: txt($("replay-clock")),
    slider_value: $("replay-slider") ? $("replay-slider").value : null,
    meta_text: txt($("replay-meta")),
    flags_text: txt($("replay-map-flags")),
    ally_color: cs.getPropertyValue("--signal-info").trim(),
    enemy_color: cs.getPropertyValue("--signal-bad").trim(),
    text_color: cs.getPropertyValue("--text").trim(),
    canvas_w: c ? c.width : null,
    canvas_h: c ? c.height : null,
    canvas_png: c ? c.toDataURL("image/png") : null,
  };
}"""


class InputError(Exception):
    """Unreadable or unusable input (exit 2)."""


# --- shared helpers ----------------------------------------------------------------

def match_sha(match_id) -> str:
    return hashlib.sha256(str(match_id).encode("utf-8")).hexdigest()[:16]


def dur_str(seconds: int) -> str:
    # dev.js _replayDurStr
    return f"{seconds // 60}:{seconds % 60:02d}"


def canvas_size(index_html: Path = INDEX_HTML) -> tuple[int, int]:
    text = index_html.read_text(encoding="utf-8")
    m = re.search(r'<canvas id="replay-map-canvas"[^>]*?width="(\d+)"[^>]*?height="(\d+)"',
                  text, re.DOTALL)
    if not m:
        raise InputError("replay-map-canvas width/height not found in web/index.html")
    return int(m.group(1)), int(m.group(2))


def badge_radius(w: int) -> int:
    # dev.js _replayMapDraw: R = Math.round(W / 30); JS rounds .5 up
    return int(math.floor(w / 30 + 0.5))


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# --- plan --------------------------------------------------------------------------

def run_node_model(match: dict, w: int, h: int, node: str = "node") -> dict:
    payload = json.dumps({"module_url": MINIMAP_JS.resolve().as_uri(),
                          "match": match, "w": w, "h": h})
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run([node, "--input-type=module", "-e", _NODE_SRC],
                              input=payload, capture_output=True, text=True,
                              encoding="utf-8", timeout=120, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InputError(f"node did not run: {type(exc).__name__}") from exc
    if proc.returncode != 0:
        raise InputError("node failed: " + (proc.stderr or "").strip()[-400:])
    return json.loads(proc.stdout)


def _annotate(frame: dict, w: int, h: int, r: int) -> dict:
    """Mark which badges / crosses can be sampled without touching anything else."""
    k = r * 0.5
    arm = k * math.sqrt(2.0)
    badges = [s for s in frame["states"] if s["visible"]]
    crosses = [s for s in frame["states"] if s["dead"] and s.get("cross_xy")]

    def near_edge(xy, pad):
        return xy[0] < pad or xy[1] < pad or xy[0] > w - pad or xy[1] > h - pad

    for b in badges:
        c = b["xy"]
        b["obstructed"] = (
            near_edge(c, r + 3)
            or any(o is not b and _dist(c, o["xy"]) < 2 * r + 3 for o in badges)
            or any(_dist(c, x["cross_xy"]) < r + arm + 3 for x in crosses))
    for x in crosses:
        c = x["cross_xy"]
        x["obstructed"] = (
            near_edge(c, r + 3)
            or any(_dist(c, b["xy"]) < 2 * r + 3 for b in badges)
            or any(o is not x and _dist(c, o["cross_xy"]) < r + arm + 3 for o in crosses))
    return frame


def build_plan(match: dict, index: int | None = None, node: str = "node",
               index_html: Path = INDEX_HTML) -> dict:
    w, h = canvas_size(index_html)
    r = badge_radius(w)
    model = run_node_model(match, w, h, node=node)
    if model.get("hidden"):
        raise InputError("the minimap is hidden for this match (queue "
                         f"{match.get('queue_id')}: Arena / Mayhem / no stored positions); "
                         "pick an SR or ARAM match")
    ally = model["ally_team"]
    frames = [_annotate(f, w, h, r) for f in model["frames"]]
    for f in frames:
        for s in f["states"]:
            s["role"] = "ally" if s["team"] == ally else "enemy"

    def usable(f):
        clear = [s for s in f["states"] if s["visible"] and not s["obstructed"]]
        dead = [s for s in f["states"] if s["dead"] and s.get("cross_xy") and not s["obstructed"]]
        return (dead and any(s["role"] == "ally" for s in clear)
                and any(s["role"] == "enemy" for s in clear))

    if index is None:
        pick = next((f for f in frames if f["idx"] >= 1 and usable(f)), None)
        if pick is None:
            raise InputError("no stored frame has an unobstructed dead champion plus an "
                             "unobstructed ally and enemy badge; pass --index")
    else:
        if not 0 <= index < len(frames):
            raise InputError(f"--index {index} outside 0..{len(frames) - 1}")
        pick = frames[index]
    t_ms = int(pick["t_ms"])
    return {
        "tool": "gated_lx11_minimap_check",
        "match_sha": match_sha(match.get("match_id")),
        "queue_id": match.get("queue_id"),
        "kind": model["kind"],
        "canvas": {"w": w, "h": h, "r": r},
        "ally_team": ally,
        "slider_index": pick["idx"],
        "t_ms": t_ms,
        "expect_frame_clock": f"t = {float(pick['minute']):.1f}min",
        "expect_map_clock": "Map at " + dur_str(t_ms // 1000),
        "frames_total": len(frames),
        "usable_by_rule": bool(usable(pick)),
        "badges": [{k: s.get(k) for k in ("pid", "role", "xy", "revive", "src",
                                           "halo_units", "obstructed")}
                   for s in pick["states"] if s["visible"]],
        "dead": [{"pid": s["pid"], "role": s["role"], "cross_xy": s.get("cross_xy"),
                  "obstructed": s.get("obstructed", True)}
                 for s in pick["states"] if s["dead"]],
        "unknown": [s["pid"] for s in pick["states"] if not s["visible"] and not s["dead"]],
    }


# --- grade -------------------------------------------------------------------------

def parse_color(text) -> tuple[int, int, int] | None:
    s = str(text or "").strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", s)
    if m:
        hx = m.group(1)
        if len(hx) == 3:
            hx = "".join(ch * 2 for ch in hx)
        return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+%?\s*)?\)", s)
    if not m:
        m = re.fullmatch(r"rgba?\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:/\s*[\d.]+%?\s*)?\)", s)
    if m:
        rgb = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return rgb if all(0 <= v <= 255 for v in rgb) else None
    return None


def token_color(token, fallback):
    """dev.js falls back to --text only when the token is EMPTY; an unparseable value is None."""
    if not str(token or "").strip():
        return fallback
    return parse_color(token)


def decode_canvas(data_url):
    try:
        from PIL import Image
    except ImportError as exc:
        raise InputError("Pillow is not installed") from exc
    if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
        raise InputError("evidence canvas_png is not a PNG data URL")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # any decode failure is an input error
        raise InputError(f"canvas_png does not decode: {type(exc).__name__}") from exc
    return img.convert("RGBA")


def _cdist(px, col) -> float:
    return math.sqrt((px[0] - col[0]) ** 2 + (px[1] - col[1]) ** 2 + (px[2] - col[2]) ** 2)


def _px(img, x, y):
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < img.width and 0 <= yi < img.height):
        return None
    return img.getpixel((xi, yi))


def ring_fraction(img, xy, r, col):
    """Share of on-colour samples on the ring circle, or None when most fall off the canvas."""
    hits = total = 0
    for i in range(RING_SAMPLES):
        a = 2 * math.pi * i / RING_SAMPLES
        p = _px(img, xy[0] + r * math.cos(a), xy[1] + r * math.sin(a))
        if p is None:
            continue
        total += 1
        if _cdist(p, col) <= COLOR_TOL:
            hits += 1
    return hits / total if total >= RING_SAMPLES // 2 else None


def cross_fraction(img, xy, r, col) -> float:
    k = r * 0.5
    ok = total = 0
    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        for f in (0.35, 0.5, 0.65, 0.8):
            d = k * f
            on = _px(img, xy[0] + sx * d, xy[1] + sy * d)
            # control: same distance, rotated 45 degrees onto an axis (off the cross)
            ctl = _px(img, xy[0] + sx * d * math.sqrt(2.0), xy[1])
            if on is None or ctl is None:
                continue
            total += 1
            if _cdist(on, col) + CROSS_MARGIN < _cdist(ctl, col):
                ok += 1
    return ok / total if total else 0.0


def opaque_fraction(img) -> float:
    alpha = img.getchannel("A")
    hist = alpha.histogram()
    return sum(hist[250:]) / float(img.width * img.height)


def art_colours(img, step: int = 12) -> int:
    """Distinct RGB colours on a coarse grid: map art has many, a flat fill has one."""
    seen = set()
    for y in range(step // 2, img.height, step):
        for x in range(step // 2, img.width, step):
            seen.add(img.getpixel((x, y))[:3])
    return len(seen)


def _finite_xy(xy) -> bool:
    return (isinstance(xy, list) and len(xy) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                    for v in xy))


def check_plan_shape(plan) -> None:
    """A plan this tool did not write is an input error (exit 2), never a FAIL of the row."""
    if not isinstance(plan, dict):
        raise InputError("plan must be a JSON object")
    c = plan.get("canvas")
    if not (isinstance(c, dict) and all(isinstance(c.get(k), int) and not isinstance(c.get(k), bool)
                                        and 0 < c[k] <= 4096 for k in ("w", "h", "r"))):
        raise InputError("plan canvas w / h / r must be positive integers")
    if c["r"] * 4 > min(c["w"], c["h"]):
        raise InputError("plan canvas r is too large for the canvas")
    si = plan.get("slider_index")
    if not (isinstance(si, int) and not isinstance(si, bool) and si >= 0):
        raise InputError("plan slider_index must be a non-negative integer")
    for key in ("expect_map_clock", "expect_frame_clock", "match_sha"):
        if not isinstance(plan.get(key), str):
            raise InputError(f"plan {key} missing")
    for key, xy_key in (("badges", "xy"), ("dead", "cross_xy")):
        rows = plan.get(key)
        if not isinstance(rows, list):
            raise InputError(f"plan {key} must be a list")
        for row in rows:
            if not isinstance(row, dict) or row.get("role") not in ("ally", "enemy"):
                raise InputError(f"plan {key} row has no ally / enemy role")
            xy = row.get(xy_key)
            if xy is None and key == "dead":
                continue
            if not _finite_xy(xy) or not (-c["r"] <= xy[0] <= c["w"] + c["r"]
                                           and -c["r"] <= xy[1] <= c["h"] + c["r"]):
                raise InputError(f"plan {key} row {xy_key} is not a point on the canvas")


def grade(plan: dict, ev: dict) -> dict:
    check_plan_shape(plan)
    if not isinstance(ev, dict):
        raise InputError("evidence must be a JSON object")
    checks: dict = {}
    fails: list[str] = []
    gaps: list[str] = []

    href = str(ev.get("href") or "")
    try:
        port = urlparse(href).port
    except ValueError:
        port = None
    real_origin = href.startswith("https://") and port == 8888
    checks["real_origin"] = real_origin
    mock = ev.get("ui_mock")
    checks["ui_mock"] = str(mock if mock is not None else "")
    provenance: list[str] = []
    if not real_origin:
        provenance.append("evidence href is not the https :8888 dashboard")
    if mock not in (None, "", "0", 0, False):
        provenance.append("ui_mock is on: the fixture replay, not /api/replay/*")

    meta = str(ev.get("meta_text") or "")
    mid = meta.split(" - ", 1)[0].strip()
    checks["match_tie"] = bool(mid) and match_sha(mid) == plan.get("match_sha")
    if not checks["match_tie"]:
        provenance.append("evidence match is not the planned match")

    if ev.get("view_hidden") is True:
        fails.append("Replay view hidden")
    elif ev.get("view_hidden") is not False:
        gaps.append("Replay view state not captured")
    if ev.get("figure_hidden") is True:
        fails.append("minimap figure hidden")
    elif ev.get("figure_hidden") is not False:
        gaps.append("minimap figure state not captured")
    note = ev.get("note_text")
    vis = ev.get("note_visible")
    if not isinstance(note, str) or not isinstance(vis, bool):
        checks["note_ok"] = None
        gaps.append("note text / visibility not captured")
    else:
        checks["note_ok"] = NOTE_FRAGMENT in note and vis
        if not checks["note_ok"]:
            fails.append("'sampled every 60 s' note missing or not visible")
    # A wrong clock or slider is a CAPTURE mistake (wrong index, or read before the
    # next animation frame redrew the map). The canvas then shows another moment, so
    # its pixels cannot fail the row: like a provenance miss it forces INCONCLUSIVE.
    def _text(key):
        v = ev.get(key)
        return v.strip() if isinstance(v, str) else None
    checks["map_clock_ok"] = _text("map_clock_text") == plan["expect_map_clock"]
    checks["frame_clock_ok"] = _text("frame_clock_text") == plan["expect_frame_clock"]
    checks["slider_ok"] = str(ev.get("slider_value")) == str(plan.get("slider_index"))
    if not checks["map_clock_ok"]:
        provenance.append("map clock is not the planned time (re-capture after the redraw)")
    if not checks["frame_clock_ok"]:
        provenance.append("frame clock is not the planned index")
    if not checks["slider_ok"]:
        provenance.append("slider is not at the planned index")

    fg = parse_color(ev.get("text_color"))
    ally_col = token_color(ev.get("ally_color"), fg)
    enemy_col = token_color(ev.get("enemy_color"), fg)
    cols = {"ally": ally_col, "enemy": enemy_col}
    if ally_col is None or enemy_col is None:
        gaps.append("ring colour token unparseable")
    elif _cdist(ally_col, enemy_col) <= COLOR_TOL:
        gaps.append("ally and enemy ring colours are too close to tell apart")

    c = plan["canvas"]
    img = decode_canvas(ev.get("canvas_png"))
    if (img.width, img.height) != (c["w"], c["h"]):
        fails.append(f"canvas {img.width}x{img.height} is not the planned {c['w']}x{c['h']}")
    art = opaque_fraction(img)
    checks["art_opaque_frac"] = round(art, 3)
    checks["art_colours"] = art_colours(img)
    checks["art"] = ("ART_MISSING" if art <= ART_MISSING_FRAC
                     else "ART_PARTIAL" if art < ART_OK_FRAC
                     else "ART_FLAT" if checks["art_colours"] < ART_MIN_COLOURS
                     else "ART_DRAWN")
    if checks["art"] == "ART_MISSING":
        fails.append("map art not drawn")
    elif checks["art"] == "ART_PARTIAL":
        gaps.append("map art coverage partial")
    elif checks["art"] == "ART_FLAT":
        gaps.append("canvas is opaque but nearly one colour: not the map art")

    r = c["r"]
    badge_rows = []
    if ally_col is not None and enemy_col is not None:
        for b in plan["badges"]:
            if b.get("obstructed"):
                badge_rows.append({"pid": b["pid"], "role": b["role"], "ring": "SKIPPED"})
                continue
            frac = ring_fraction(img, b["xy"], r, cols[b["role"]])
            need = RING_OK_FRAC_DASHED if b.get("revive") else RING_OK_FRAC
            verdict = ("RING_UNCLEAR" if frac is None
                       else "RING_OK" if frac >= need
                       else "RING_ABSENT" if frac <= RING_ABSENT_FRAC else "RING_UNCLEAR")
            badge_rows.append({"pid": b.get("pid"), "role": b["role"], "ring": verdict,
                               "frac": None if frac is None else round(frac, 3)})
            if verdict == "RING_ABSENT":
                fails.append(f"no {b['role']} ring on pid {b['pid']}")
            elif verdict == "RING_UNCLEAR":
                gaps.append(f"ring unclear on pid {b['pid']}")
    checks["badges"] = badge_rows
    for role in ("ally", "enemy"):
        if not any(x["role"] == role and x["ring"] == "RING_OK" for x in badge_rows):
            gaps.append(f"no {role} ring confirmed")

    dead_rows = []
    if ally_col is not None and enemy_col is not None:
        for dd in plan["dead"]:
            if dd.get("obstructed") or not dd.get("cross_xy"):
                dead_rows.append({"pid": dd["pid"], "role": dd["role"], "hidden": "SKIPPED"})
                continue
            col = cols[dd["role"]]
            ring = ring_fraction(img, dd["cross_xy"], r, col)
            cross = cross_fraction(img, dd["cross_xy"], r, col)
            hidden = ("UNCLEAR" if ring is None
                      else "HIDDEN" if ring <= RING_ABSENT_FRAC
                      else "BADGE_DRAWN" if ring >= RING_OK_FRAC else "UNCLEAR")
            cross_v = "CROSS_SEEN" if cross >= CROSS_OK_FRAC else "CROSS_UNCLEAR"
            dead_rows.append({"pid": dd.get("pid"), "role": dd["role"], "hidden": hidden,
                              "ring_frac": None if ring is None else round(ring, 3),
                              "cross": cross_v,
                              "cross_frac": round(cross, 3)})
            if hidden == "BADGE_DRAWN":
                fails.append(f"dead pid {dd['pid']} still has a badge at its death spot")
            elif hidden == "UNCLEAR":
                gaps.append(f"death spot of pid {dd['pid']} unclear")
            if cross_v != "CROSS_SEEN":
                gaps.append(f"death cross of pid {dd['pid']} not confirmed")
    checks["dead"] = dead_rows
    if not any(x.get("hidden") == "HIDDEN" and x.get("cross") == "CROSS_SEEN" for x in dead_rows):
        gaps.append("no dead champion confirmed hidden with its cross")

    if provenance:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "FAIL" if fails else ("INCONCLUSIVE" if gaps else "PASS")
    return {"tool": "gated_lx11_minimap_check", "verdict": verdict, "provenance": provenance,
            "slider_index": plan.get("slider_index"), "t_ms": plan.get("t_ms"),
            "captured_at": ev.get("captured_at"), "checks": checks,
            "fails": fails, "gaps": gaps}


# --- cli ---------------------------------------------------------------------------

def _load_json(path: str):
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise InputError(f"{p.name}: {type(exc).__name__}") from exc


def _print_plan(plan: dict) -> None:
    print(f"LX-11 plan: queue {plan['queue_id']} map {plan['kind']} "
          f"slider index {plan['slider_index']} of 0..{plan['frames_total'] - 1}")
    print(f"  expect: '{plan['expect_frame_clock']}' and '{plan['expect_map_clock']}'")
    print(f"  canvas {plan['canvas']['w']}x{plan['canvas']['h']} R={plan['canvas']['r']} "
          f"ally team {plan['ally_team']}")
    for b in plan["badges"]:
        flag = " (obstructed)" if b["obstructed"] else ""
        dash = " dashed" if b.get("revive") else ""
        print(f"  badge pid {b['pid']:>2} {b['role']:<5} at "
              f"({b['xy'][0]:.0f}, {b['xy'][1]:.0f}){dash}{flag}")
    for d in plan["dead"]:
        where = (f"cross at ({d['cross_xy'][0]:.0f}, {d['cross_xy'][1]:.0f})"
                 if d.get("cross_xy") else "no kill position")
        flag = " (obstructed)" if d["obstructed"] else ""
        print(f"  DEAD  pid {d['pid']:>2} {d['role']:<5} {where}, no badge{flag}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only LX-11 replay minimap plan / grade")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plan", help="what the canvas must show at one slider index")
    pp.add_argument("--match-json", required=True,
                    help="saved body of /api/replay/match/<id> from the real dashboard")
    pp.add_argument("--index", type=int, default=None)
    pp.add_argument("--node", default="node")
    pp.add_argument("--json", action="store_true")
    gp = sub.add_parser("grade", help="grade an evidence bundle against a plan")
    gp.add_argument("--plan", required=True)
    gp.add_argument("--evidence", required=True)
    gp.add_argument("--json", action="store_true")
    sub.add_parser("snippet", help="print the browser expression that captures the evidence")
    args = ap.parse_args(argv)

    if args.cmd == "snippet":
        print(SNIPPET)
        return 0
    try:
        if args.cmd == "plan":
            match = _load_json(args.match_json)
            if not isinstance(match, dict):
                raise InputError("match JSON must be an object")
            try:
                plan = build_plan(match, index=args.index, node=args.node)
            except (KeyError, TypeError, ValueError, IndexError, AttributeError,
                    ArithmeticError, RecursionError) as exc:
                raise InputError(f"match JSON has the wrong shape: {type(exc).__name__}") from exc
            if args.json:
                print(json.dumps(plan, indent=2))
            else:
                _print_plan(plan)
            return 0
        plan, ev = _load_json(args.plan), _load_json(args.evidence)
        if not isinstance(plan, dict) or not isinstance(ev, dict):
            raise InputError("plan and evidence must be JSON objects")
        try:
            res = grade(plan, ev)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError,
                ArithmeticError, RecursionError) as exc:
            # a wrong-shaped file is an input error, never a FAIL of the row
            raise InputError(f"plan or evidence has the wrong shape: {type(exc).__name__}") from exc
    except InputError as exc:
        print(f"LX-11: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"LX-11 verdict {res['verdict']} at slider index {res['slider_index']}")
        for line in res["provenance"]:
            print("  NOT EVIDENCE " + line)
        for line in res["fails"]:
            print("  FAIL " + line)
        for line in res["gaps"]:
            print("  GAP  " + line)
    return {"PASS": 0, "FAIL": 1}.get(res["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
