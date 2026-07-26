"""Recover champion MAP coordinates from a replay by back-projecting screen space.

WHY THIS EXISTS: Match-V5 samples position every 60 s, and a calibration over
308 drake samples showed positional signal decaying to noise by that interval
(0.688 accuracy at a 30 s lead, 0.516 at 120 s). `:2999` reports
`allPlayers[].position` as a ROLE STRING, so it looked like sub-minute position
required parsing the .rofl chunk stream (Layer-2, fenced).

But `/replay/render` DOES expose real geometry:
  cameraPosition  map coordinates - the map is the x/z plane, y is HEIGHT
  cameraRotation, fieldOfView (40.0 default), nearClip / farClip
and every player carries `screenPositionCenter` / `screenPositionBottom`,
which hold a real screen-space projection when the champion is on screen and
FLT_MAX (3.4028235e38) when it is not.

So a champion's map position is recoverable by inverting the camera projection,
at ARBITRARY time resolution, without touching Layer-2.

LIVE-MEASURED 2026-07-26 against NA1_5607614664 - what is settled and what
is not:

  SETTLED - the render POST works. fogOfWar, interfaceAll, fieldOfView,
  cameraMode and the health-bar toggles all take and stick, 200 each.

  SETTLED - cameraPosition is writable ONLY in cameraMode "fps". In "top"
  mode every write returns 200 and is silently ignored. Once in fps the
  writes are EXACT: (9866, 1800, 4414) and (5000, 2500, 5000) both landed on
  the requested value to the float.

  CORRECTED - EnableDirectedCamera was NOT the blocker. It read 0 in game.cfg
  the whole time the writes were failing; the camera mode was the cause. An
  earlier note in this repo blamed the directed camera; do not inherit it.

  SOLVED - cameraRotation is {x: YAW, y: PITCH, z: roll}, degrees. The
  observed default y=56 is the standard SR top-down pitch. The camera does NOT
  look at its own map coordinates: at pitch p and height h it looks at a point
  h/tan(p) further along the facing direction (1289 units at the default
  h=1911, p=56). Park it at (target_x, h, target_z - h/tan(p)) with yaw 0 and
  the target is on screen. Guessing +/-90 pitch on the WRONG axis is what
  pointed the camera at empty space earlier.

  SOLVED - visibility. With cameraMode fps, fov 60, h=4000 and the offset
  above, 6 of 10 champions reported real screenPositionCenter /
  screenPositionBottom values simultaneously.

  MEASURED ACCURACY, and it is approximate rather than exact. Scored against
  Match-V5 frame 600263 ms as ground truth, screen -> map by least-squares
  AFFINE fit on the visible champions:
      same-view fit residual        mean  88, max 208 map units
      transfer to a camera moved 900 units   mean 168, max 348
      transfer to a camera moved 900 on z    mean 293, max 472
  screenPositionBottom (feet) and screenPositionCenter score identically, so
  model elevation is not the error source. A homography fit scored WORSE
  (mean 277) - ill-conditioned on 6 near-collinear points, do not reach for it
  with a small sample.

  WHY AFFINE IS THE WRONG MODEL, and what to do instead: under perspective the
  screen-to-ground scale varies with depth, which an affine map cannot express
  - hence the residual growing on transfer. The principled fix needs NO
  empirical calibration at all: camera position, yaw, pitch and fov are all
  readable, so cast a ray from the camera through the pixel and intersect the
  ground plane. The only unmeasured inputs are the viewport pixel size and
  whether fieldOfView is horizontal or vertical. Do that before trusting any
  number here.

  FIT FOR PURPOSE TODAY: ~100-300 units of error on a 14820-unit map is fine
  for coarse questions - the calibrated drake threshold is 2750 units, an order
  of magnitude above the noise. It is NOT fine for lane-trade geometry, where
  auto-attack range is ~550 and champion radius ~65.

  ORACLE, used above and reusable: seek to a Match-V5 frame timestamp (e.g.
  600263 ms) and all ten true map positions are known, so any back-projection
  is scored against ground truth rather than eyeballed. Note the truth itself
  carries error - a champion moves ~300 units/s, so a sub-second mismatch
  between the frame instant and the rendered instant is worth ~100 units on
  its own. Some of the residual above is that, not model error.

STATUS: the route WORKS end to end - camera control, visibility and a scored
back-projection all measured live. The geometry helpers below are the crude
affine version and are deliberately calibration-first: `solve_scale` derives
the factor from an observed camera displacement rather than assuming an
undocumented projection matrix, and returns None instead of a fabricated
default when the camera did not move. Replace them with the analytic
ray/ground-plane solve before wiring any coaching derivation to this.

PREREQUISITE: `cameraMode` must be `fps` before any cameraPosition write. That
is the real gate, measured. `EnableDirectedCamera=0` in game.cfg `[Replay]` is
worth keeping so the client does not fight the camera during playback, but it
is NOT what was blocking writes.
"""
from __future__ import annotations

import json
import math
import ssl
import time
import urllib.request
from dataclasses import dataclass

# The client writes FLT_MAX into screen position when a champion is off screen.
# Compare with a wide margin rather than for equality - it arrives as a decimal
# string with 7 fractional digits.
FLT_MAX_SENTINEL = 1e38

BASE = "https://127.0.0.1:2999"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


@dataclass(frozen=True)
class ScreenPos:
    x: float
    y: float


@dataclass(frozen=True)
class CameraState:
    x: float          # map x
    y: float          # HEIGHT, not a map axis
    z: float          # map z
    fov: float
    mode: str = ""


def parse_screen_pos(raw):
    """'1285.67,592.20' -> ScreenPos, or None when off screen.

    Off-screen is FLT_MAX in both components. Returning None rather than a
    huge number is the point: a caller that forgets to check would otherwise
    back-project 3.4e38 into a map coordinate and get nonsense that still
    looks numeric.
    """
    if not raw or not isinstance(raw, str):
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        return None
    try:
        x, y = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if abs(x) > FLT_MAX_SENTINEL or abs(y) > FLT_MAX_SENTINEL:
        return None
    return ScreenPos(x=x, y=y)


def camera_from(render: dict) -> CameraState:
    pos = (render or {}).get("cameraPosition") or {}
    return CameraState(
        x=float(pos.get("x") or 0.0),
        y=float(pos.get("y") or 0.0),
        z=float(pos.get("z") or 0.0),
        fov=float((render or {}).get("fieldOfView") or 0.0),
        mode=str((render or {}).get("cameraMode") or ""))


def solve_scale(cam_a: CameraState, screen_a: ScreenPos,
                cam_b: CameraState, screen_b: ScreenPos):
    """Map-units per screen-pixel, derived from a KNOWN camera displacement.

    Move the camera a known distance with everything else fixed, watch a
    stationary champion's screen position shift, and the ratio is the scale.
    This is measured rather than derived from an assumed projection matrix,
    because the exact one Riot uses here is undocumented and a wrong assumption
    would produce plausible coordinates that are quietly wrong.

    Returns (units_per_px_x, units_per_px_z) or None when the camera did not
    actually move on an axis (division by zero) - never a fabricated default.
    """
    dsx = screen_b.x - screen_a.x
    dsz = screen_b.y - screen_a.y
    dmx = cam_b.x - cam_a.x
    dmz = cam_b.z - cam_a.z
    if abs(dsx) < 1e-6 or abs(dsz) < 1e-6:
        return None
    return (-dmx / dsx, -dmz / dsz)


def back_project(cam: CameraState, screen: ScreenPos, centre: ScreenPos,
                 scale) -> tuple:
    """Screen position -> map (x, z), given a calibrated scale.

    In top-down mode with a fixed camera height the mapping is affine, so a
    champion's offset from screen centre times the calibrated scale is its
    offset from the camera's map position.
    """
    ux, uz = scale
    return (cam.x + (screen.x - centre.x) * ux,
            cam.z + (screen.y - centre.y) * uz)


class RenderClient:
    """Read/write the replay render state."""

    def __init__(self, base: str = BASE, timeout_s: float = 5.0,
                 settle_s: float = 1.2):
        self.base = base.rstrip("/")
        self.timeout_s = timeout_s
        self.settle_s = settle_s

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.base}{path}",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s,
                                    context=_CTX) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, path: str, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}{path}", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=self.timeout_s, context=_CTX).read()
        time.sleep(self.settle_s)

    def get_render(self) -> dict:
        return self._get("/replay/render")

    def set_camera(self, x: float, y: float, z: float) -> CameraState:
        """Move the camera and return where it ACTUALLY landed.

        Returns the observed state rather than assuming the write took: with
        the directed camera enabled the POST succeeds and is then overridden,
        so a caller must compare what it asked for against what it got.
        """
        self._post("/replay/render",
                   {"cameraPosition": {"x": float(x), "y": float(y),
                                       "z": float(z)}})
        return camera_from(self.get_render())

    def camera_writable(self, probe_delta: float = 1500.0) -> bool:
        """Does a camera write actually stick? Measured, never assumed."""
        before = camera_from(self.get_render())
        after = self.set_camera(before.x + probe_delta, before.y, before.z)
        moved = abs(after.x - (before.x + probe_delta)) < 50.0
        self.set_camera(before.x, before.y, before.z)
        return moved


# ---------------------------------------------------------------------------
# Analytic ray / ground-plane solve. This SUPERSEDES the affine helpers above.
#
# Cast a ray from the camera through a screen pixel and intersect the ground
# plane. Needs no per-view calibration: camera pose comes from /replay/render
# and the intrinsics below are a one-time solve for a given viewport.
#
# MEASURED 2026-07-26, 31 observations over 5 camera poses at one instant:
#   model self-consistency  mean 19, median 17, max 36 map units
#   agreement with Match-V5  mean 167
# The self-consistency number is the model's own precision - it involves no
# timeline at all, just the same champion back-projected from different
# cameras. At 19 units against a ~65-unit champion radius the projection is
# effectively exact, and the 167 is the TIMELINE's sampling offset, not ours
# (a champion moves ~300 units/s, so the frame instant and the rendered
# instant need only differ slightly).
#
# Ground height barely matters: sweeping it from -300 to +500 moved the mean by
# one unit (best 50). Terrain elevation is NOT a significant error source here.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Intrinsics:
    """Viewport geometry. Solve once per viewport size, then reuse."""

    principal_x: float
    principal_y: float
    focal_px: float
    ground_y: float = 50.0


# Solved on Legion's 2560x1440 client at fieldOfView 60. The implied viewport
# was 2518 x 1458 and the implied VERTICAL fov 58.3 deg, so `fieldOfView` is
# vertical, near enough. Fixing the principal point at the exact screen centre
# scored WORSE (mean 184 vs 167), so it is kept as solved rather than idealised.
LEGION_2560x1440_FOV60 = Intrinsics(principal_x=1259.0, principal_y=735.0,
                                    focal_px=1291.0, ground_y=50.0)


def camera_basis(yaw_deg: float, pitch_deg: float):
    """Forward / right / up unit vectors for a replay camera.

    cameraRotation is {x: YAW, y: PITCH, z: roll} in degrees - measured, and
    the opposite of the obvious reading. Pitch is a downward tilt, so forward
    carries a negative y component.
    """
    y = math.radians(yaw_deg)
    p = math.radians(pitch_deg)
    fwd = (math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p))
    right = (math.cos(y), 0.0, -math.sin(y))
    up = (fwd[1] * right[2] - fwd[2] * right[1],
          fwd[2] * right[0] - fwd[0] * right[2],
          fwd[0] * right[1] - fwd[1] * right[0])
    return fwd, right, up


def look_at_offset(height: float, pitch_deg: float) -> float:
    """How far AHEAD of its own coordinates the camera actually looks.

    The camera does not look straight down at its own map position: at pitch p
    and height h it looks h/tan(p) further along its facing direction (1289
    units at the default h=1911, p=56). Park the camera at
    (target_x, h, target_z - look_at_offset(h, p)) with yaw 0 to put a target
    on screen. Not knowing this is what made every early attempt see nothing.
    """
    return height / math.tan(math.radians(pitch_deg))


def screen_to_map(cam: CameraState, screen: ScreenPos, intr: Intrinsics,
                  yaw_deg: float = 0.0, pitch_deg: float = 56.0):
    """Screen pixel -> map (x, z), by ray/ground-plane intersection.

    Returns None when the ray does not descend toward the ground, rather than
    a point behind the camera that would look like a legitimate coordinate.
    """
    fwd, right, up = camera_basis(yaw_deg, pitch_deg)
    dx = (screen.x - intr.principal_x) / intr.focal_px
    dy = -(screen.y - intr.principal_y) / intr.focal_px
    d = tuple(dx * right[i] + dy * up[i] + fwd[i] for i in range(3))
    if d[1] >= -1e-9:                      # not pointing down: no intersection
        return None
    t = (intr.ground_y - cam.y) / d[1]
    if t <= 0:
        return None
    return (cam.x + t * d[0], cam.z + t * d[2])


def map_to_screen(cam: CameraState, map_x: float, map_z: float,
                  intr: Intrinsics, yaw_deg: float = 0.0,
                  pitch_deg: float = 56.0):
    """Map (x, z) -> screen pixel. The forward direction, for round-tripping."""
    fwd, right, up = camera_basis(yaw_deg, pitch_deg)
    v = (map_x - cam.x, intr.ground_y - cam.y, map_z - cam.z)
    zc = sum(v[i] * fwd[i] for i in range(3))
    if zc <= 1e-9:                          # behind the camera
        return None
    xc = sum(v[i] * right[i] for i in range(3))
    yc = sum(v[i] * up[i] for i in range(3))
    return ScreenPos(x=intr.principal_x + intr.focal_px * xc / zc,
                     y=intr.principal_y - intr.focal_px * yc / zc)
