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

  OPEN - champion VISIBILITY. Every attempt left all ten screenPositionCenter
  values at FLT_MAX, so nothing could be back-projected. cameraRotation
  semantics are undocumented and unmeasured: the observed default is
  {x: 0, y: 56, z: 0}, and pitch guesses of +/-90 on the x axis pointed the
  camera at empty space (which also blanks the render, and looks like a
  crash). Solve rotation FIRST - the maths below is untestable until at least
  one champion reports a real screen position.

  ORACLE IS READY for the moment visibility works: seek to a Match-V5 frame
  timestamp (e.g. 600263 ms) and all ten true map positions are known, so a
  back-projection can be scored directly rather than eyeballed.

STATUS: the geometry below is UNVERIFIED against live bytes. It is written to
be calibrated, not trusted - `solve_scale` derives the screen-to-map factor
empirically by moving the camera a known distance and observing the screen
delta, rather than assuming a projection matrix that Riot has not documented.
Do not wire any coaching derivation to this until `calibrate` has run against a
live replay and its residuals are reported.

PREREQUISITE: `cameraMode` must be `fps` before any cameraPosition write. That
is the real gate, measured. `EnableDirectedCamera=0` in game.cfg `[Replay]` is
worth keeping so the client does not fight the camera during playback, but it
is NOT what was blocking writes.
"""
from __future__ import annotations

import json
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
