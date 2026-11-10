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
  screenPositionBottom values simultaneously. At h=8000 all 10 report at once,
  so one seek plus one camera placement yields the whole team.

  TWO OPERATIONAL REQUIREMENTS, both learned by getting them wrong:

  1. fogOfWar MUST be False. A champion inside fog does not render and
     reports FLT_MAX, so a sampling pass with fog on silently returns a
     partial team and looks like a visibility failure. Restoring fog to True
     after an experiment and then re-sampling cost exactly this.

  2. NORMALISE CHAMPION NAMES before joining to Match-V5. The live client
     spells them differently from DDragon ids - "Lee Sin" vs "LeeSin",
     "Kog'Maw" vs "KogMaw". A raw-string join silently drops those champions
     and the pass looks like it merely could not see them. Strip everything
     outside [a-z] and lowercase both sides. See memory
     reference_liveclient_name_vs_ddragon_id, which already warned about this.

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
  ground plane. That solve is now below: see "Analytic ray / ground-plane
  solve" for the viewport and fieldOfView measurements it settled.

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
back-projection all measured live. The first geometry helpers below
(`solve_scale`, `back_project`) are the crude affine version and are
deliberately calibration-first: `solve_scale` derives the factor from an
observed camera displacement rather than assuming an undocumented projection
matrix, and returns None instead of a fabricated default when the camera did
not move. The analytic solve further down (`screen_to_map`, `map_to_screen`)
supersedes them; wire any coaching derivation to that one.

PREREQUISITE: `cameraMode` must be `fps` before any cameraPosition write. That
is the real gate, measured. `EnableDirectedCamera=0` in game.cfg `[Replay]` is
worth keeping so the client does not fight the camera during playback, but it
is NOT what was blocking writes.
"""
from __future__ import annotations

import http.client
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# The client writes FLT_MAX into screen position when a champion is off screen.
# Compare with a wide margin rather than for equality - it arrives as a decimal
# string with 7 fractional digits.
FLT_MAX_SENTINEL = 1e38

BASE = "https://127.0.0.1:2999"

# Largest response body read from the client. A render state is under 2 KB, so
# 8 MiB is far above any real one and still bounds what one misbehaving local
# listener can make us buffer.
MAX_BODY_BYTES = 8 * 1024 * 1024

# How close a read-back must land to count as the camera write having stuck.
WRITE_TOLERANCE_UNITS = 50.0

# The measured default replay pose, used only when neither the caller nor the
# camera state says otherwise. See the module docstring.
DEFAULT_YAW_DEG = 0.0
DEFAULT_PITCH_DEG = 56.0

# Two fieldOfView readings closer than this are the same setting.
_FOV_TOLERANCE = 0.01

# Longest timeout or settle accepted. A far larger one raises OverflowError from
# the socket or from time.sleep, and the sleep only runs after the write is sent.
_MAX_WAIT_S = 3600.0

# The client serves a self-signed cert; this is loopback to a local process.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The replay API never redirects, so one is refused rather than followed
    somewhere the unverified TLS context was never meant to reach."""

    def redirect_request(self, *_args, **_kwargs):
        return None


# Private opener rather than urlopen: urllib's default opener hands even a
# 127.0.0.1 request to a proxy named in the environment (proxy_bypass reads
# False for it), which would send replay state off the box or simply fail.
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=_CTX),
    _NoRedirect())


class RenderError(RuntimeError):
    """A render read or write failed, or its payload has no usable camera.
    Never a fabricated camera: (0, 0, 0) would read as a real map position."""


def _finite(value: object) -> float | None:
    """A finite int / float as a float, else None. ``bool`` is not a number
    here, and an int too large for a float is not a coordinate."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


# A plain decimal number: no underscores ("1_000" parses in Python, never on
# the wire), no "nan" / "inf" words, no hex, ASCII digits only.
_NUMERIC = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)


def _wire_number(value: object) -> float | None:
    """A finite number from a payload field (a number or numeric string)."""
    if isinstance(value, str):
        text = value.strip()
        if not _NUMERIC.fullmatch(text):
            return None
        return _finite(float(text))
    return _finite(value)


def _required_finite(value: object, name: str) -> float:
    number = _finite(value)
    if number is None:
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


@dataclass(frozen=True)
class ScreenPos:
    x: float
    y: float


@dataclass(frozen=True)
class CameraState:
    x: float          # map x
    y: float          # HEIGHT, not a map axis
    z: float          # map z
    fov: float        # 0.0 = the render did not report one
    mode: str = ""
    yaw: float | None = None    # degrees; None = the render did not report it
    pitch: float | None = None  # degrees; None = the render did not report it


def parse_screen_pos(raw):
    """'1285.67,592.20' -> ScreenPos, or None when off screen.

    Off-screen is FLT_MAX in both components. Returning None rather than a
    huge number is the point: a caller that forgets to check would otherwise
    back-project 3.4e38 into a map coordinate and get nonsense that still
    looks numeric. Anything that is not two plain decimal numbers reads the
    same way: float() also accepts "nan", "inf" and "1_000", and a NaN passes
    every comparison below it.
    """
    if not raw or not isinstance(raw, str):
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        return None
    x, y = _wire_number(parts[0]), _wire_number(parts[1])
    if x is None or y is None:
        return None
    if abs(x) > FLT_MAX_SENTINEL or abs(y) > FLT_MAX_SENTINEL:
        return None
    return ScreenPos(x=x, y=y)


def _optional_number(section: dict, key: str, name: str) -> float | None:
    """None when *key* is absent; RenderError when it is there but malformed."""
    value = section.get(key)
    if value is None:
        return None
    number = _wire_number(value)
    if number is None:
        raise RenderError(f"render {name} is not a finite number")
    return number


def camera_from(render: dict) -> CameraState:
    """The camera described by a /replay/render payload.

    The position is required: a render without a real one raises RenderError
    rather than reading as a camera parked at (0, 0, 0). An absent fieldOfView
    reads 0.0 and an absent rotation axis reads None, both meaning "not
    reported"; a malformed one raises. Roll is not modelled (camera_basis
    takes yaw and pitch only).
    """
    if not isinstance(render, dict):
        raise RenderError("render payload is not an object")
    position = render.get("cameraPosition")
    if not isinstance(position, dict):
        raise RenderError("render payload has no cameraPosition object")
    axes = [_wire_number(position.get(axis)) for axis in ("x", "y", "z")]
    if None in axes:
        raise RenderError("render cameraPosition needs finite x, y and z")
    fov = _optional_number(render, "fieldOfView", "fieldOfView")
    if fov is not None and fov < 0:
        raise RenderError("render fieldOfView is negative")
    rotation = render.get("cameraRotation")
    if rotation is None:
        rotation = {}
    elif not isinstance(rotation, dict):
        raise RenderError("render cameraRotation is not an object")
    mode = render.get("cameraMode")
    return CameraState(
        x=axes[0], y=axes[1], z=axes[2],
        fov=fov if fov is not None else 0.0,
        mode=mode if isinstance(mode, str) else "",
        # cameraRotation is {x: YAW, y: PITCH, z: roll} - measured.
        yaw=_optional_number(rotation, "x", "cameraRotation.x"),
        pitch=_optional_number(rotation, "y", "cameraRotation.y"))


def solve_scale(cam_a: CameraState, screen_a: ScreenPos,
                cam_b: CameraState, screen_b: ScreenPos):
    """Map-units per screen-pixel, derived from a KNOWN camera displacement.

    Move the camera a known distance with everything else fixed, watch a
    stationary champion's screen position shift, and the ratio is the scale.
    This is measured rather than derived from an assumed projection matrix,
    because the exact one Riot uses here is undocumented and a wrong assumption
    would produce plausible coordinates that are quietly wrong.

    Returns (units_per_px_x, units_per_px_z), or None when the camera did not
    actually move on an axis, the champion did not slide on one (division by
    zero) or a value is not finite - never a fabricated default. A camera
    still on an axis would otherwise yield a scale of 0.0 there, which
    collapses every champion onto the camera's own coordinate.
    """
    deltas = (screen_b.x - screen_a.x, screen_b.y - screen_a.y,
              cam_b.x - cam_a.x, cam_b.z - cam_a.z)
    if not all(math.isfinite(d) and abs(d) >= 1e-6 for d in deltas):
        return None
    dsx, dsz, dmx, dmz = deltas
    scale = (-dmx / dsx, -dmz / dsz)
    return scale if _all_finite(*scale) else None


def back_project(cam: CameraState, screen: ScreenPos, centre: ScreenPos,
                 scale):
    """Screen position -> map (x, z), given a calibrated scale.

    In top-down mode with a fixed camera height the mapping is affine, so a
    champion's offset from screen centre times the calibrated scale is its
    offset from the camera's map position. Returns None when the result is not
    finite. A None scale (solve_scale's refusal) stays a TypeError.
    """
    ux, uz = scale
    map_x = cam.x + (screen.x - centre.x) * ux
    map_z = cam.z + (screen.y - centre.y) * uz
    return (map_x, map_z) if _all_finite(map_x, map_z) else None


def _all_finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def _read_capped(resp) -> bytes:
    body = resp.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise RenderError(f"replay API body exceeds {MAX_BODY_BYTES} bytes")
    # read(amount) returns a short body with no IncompleteRead, unlike read().
    # `length` is what an http.client response still expects from its
    # Content-Length, and is None when it declared none.
    if getattr(resp, "length", None):
        raise RenderError("replay API body is shorter than its Content-Length")
    return body


class RenderClient:
    """Read/write the replay render state.

    Every transport or payload failure is a RenderError. A bad argument is a
    ValueError raised before anything is sent.
    """

    def __init__(self, base: str = BASE, timeout_s: float = 5.0,
                 settle_s: float = 1.2):
        if not isinstance(base, str):
            raise ValueError(f"base must be a string, got {base!r}")
        parts = urllib.parse.urlsplit(base)
        # An opener also takes file:// and ftp:// URLs, and the unverified TLS
        # context is only meant for the client's own HTTP(S) listener.
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"base must be an http(s) URL with a host, "
                             f"got {base!r}")
        timeout = _finite(timeout_s)
        if timeout is None or not 0 < timeout <= _MAX_WAIT_S:
            raise ValueError(f"timeout_s must be a number in (0, {_MAX_WAIT_S}],"
                             f" got {timeout_s!r}")
        settle = _finite(settle_s)
        if settle is None or not 0 <= settle <= _MAX_WAIT_S:
            raise ValueError(f"settle_s must be a number in [0, {_MAX_WAIT_S}],"
                             f" got {settle_s!r}")
        self.base = base.rstrip("/")
        self.timeout_s = timeout_s
        self.settle_s = settle_s

    def _exchange(self, req: urllib.request.Request) -> bytes:
        what = f"{req.get_method()} {req.selector}"
        try:
            with _OPENER.open(req, timeout=self.timeout_s) as resp:
                return _read_capped(resp)
        except urllib.error.HTTPError as exc:
            # The error object owns the response socket.
            exc.close()
            raise RenderError(f"{what} returned HTTP {exc.code}") from exc
        except (OSError, http.client.HTTPException, UnicodeError) as exc:
            # UnicodeError: a host or path that cannot be encoded for sending.
            raise RenderError(f"{what} failed: {type(exc).__name__}") from exc

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.base}{path}",
                                     headers={"Accept": "application/json"})
        raw = self._exchange(req)
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError) as exc:
            raise RenderError(f"GET {path} body is not JSON") from exc
        if not isinstance(doc, dict):
            raise RenderError(f"GET {path} body is not an object")
        return doc

    def _post(self, path: str, payload: dict):
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}{path}", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        self._exchange(req)
        time.sleep(self.settle_s)

    def _write_position(self, x: float, y: float, z: float) -> None:
        self._post("/replay/render",
                   {"cameraPosition": {"x": x, "y": y, "z": z}})

    def get_render(self) -> dict:
        return self._get("/replay/render")

    def set_camera(self, x: float, y: float, z: float) -> CameraState:
        """Move the camera and return where it ACTUALLY landed.

        Returns the observed state rather than assuming the write took: outside
        cameraMode "fps" the POST returns 200 and is silently ignored, so a
        caller must compare what it asked for against what it got.
        """
        self._write_position(_required_finite(x, "x"),
                             _required_finite(y, "y"),
                             _required_finite(z, "z"))
        return camera_from(self.get_render())

    def camera_writable(self, probe_delta: float = 1500.0) -> bool:
        """Does a camera write actually stick? Measured, never assumed.

        The probe must be larger than WRITE_TOLERANCE_UNITS, or a camera that
        ignored the write would still land "close enough" and read writable.
        The camera goes back where it was on every path once a write was
        attempted, and a failed restore raises rather than returning an answer
        that hides a moved camera.
        """
        delta = _required_finite(probe_delta, "probe_delta")
        if abs(delta) <= WRITE_TOLERANCE_UNITS:
            raise ValueError(f"probe_delta must exceed "
                             f"{WRITE_TOLERANCE_UNITS} units, got {delta!r}")
        before = camera_from(self.get_render())
        target_x = before.x + delta
        try:
            after = self.set_camera(target_x, before.y, before.z)
            return abs(after.x - target_x) < WRITE_TOLERANCE_UNITS
        finally:
            self._write_position(before.x, before.y, before.z)


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
    """Viewport geometry. Solve once per viewport size, then reuse.

    `fov` is the fieldOfView the solve was made at, 0.0 when not recorded.
    focal_px holds for that setting only, and the client's default is 40.
    """

    principal_x: float
    principal_y: float
    focal_px: float
    ground_y: float = 50.0
    fov: float = 0.0

    def __post_init__(self):
        """Require finite intrinsics, a positive focal length and a non-negative fov."""
        for name in ("principal_x", "principal_y", "focal_px", "ground_y",
                     "fov"):
            _required_finite(getattr(self, name), name)
        if self.focal_px <= 0:
            raise ValueError(f"focal_px must be > 0, got {self.focal_px!r}")
        if self.fov < 0:
            raise ValueError(f"fov must be >= 0, got {self.fov!r}")


# Solved on Legion's 2560x1440 client at fieldOfView 60. The implied viewport
# was 2518 x 1458 and the implied VERTICAL fov 58.3 deg, so `fieldOfView` is
# vertical, near enough. Fixing the principal point at the exact screen centre
# scored WORSE (mean 184 vs 167), so it is kept as solved rather than idealised.
LEGION_2560x1440_FOV60 = Intrinsics(principal_x=1259.0, principal_y=735.0,
                                    focal_px=1291.0, ground_y=50.0, fov=60.0)


def camera_basis(yaw_deg: float, pitch_deg: float):
    """Forward / right / up unit vectors for a replay camera.

    cameraRotation is {x: YAW, y: PITCH, z: roll} in degrees - measured, and
    the opposite of the obvious reading. Pitch is a downward tilt, so forward
    carries a negative y component. A non-finite angle is a ValueError.
    """
    y = math.radians(_required_finite(yaw_deg, "yaw_deg"))
    p = math.radians(_required_finite(pitch_deg, "pitch_deg"))
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

    Only a height >= 0 and a downward tilt in (0, 90] degrees meet the ground;
    anything else is a ValueError, never a negative or infinite distance.
    """
    h = _required_finite(height, "height")
    p = _required_finite(pitch_deg, "pitch_deg")
    if h < 0:
        raise ValueError(f"height must be >= 0, got {height!r}")
    if not 0 < p <= 90:
        raise ValueError(f"pitch_deg must be in (0, 90], got {pitch_deg!r}")
    tangent = math.tan(math.radians(p))
    offset = h / tangent if tangent > 0 else math.inf
    if not math.isfinite(offset):
        raise ValueError(f"pitch_deg {pitch_deg!r} at height {height!r} never "
                         f"meets the ground")
    return offset


def _pose(cam: CameraState, intr: Intrinsics, yaw_deg, pitch_deg):
    """The yaw and pitch to solve with: explicit, else the camera's own, else
    the measured default. Also refuses intrinsics solved at another fieldOfView,
    because focal_px is only true at its own and the answer would be wrong with
    no other sign of it. Either side at exactly 0.0 means unknown and is not
    checked; the negated comparison also refuses a NaN camera reading.
    """
    if (intr.fov != 0 and cam.fov != 0
            and not abs(intr.fov - cam.fov) <= _FOV_TOLERANCE):
        raise ValueError(f"camera fieldOfView {cam.fov!r} does not match the "
                         f"intrinsics, solved at {intr.fov!r}")
    if yaw_deg is None:
        yaw_deg = cam.yaw if cam.yaw is not None else DEFAULT_YAW_DEG
    if pitch_deg is None:
        pitch_deg = cam.pitch if cam.pitch is not None else DEFAULT_PITCH_DEG
    return yaw_deg, pitch_deg


def screen_to_map(cam: CameraState, screen: ScreenPos, intr: Intrinsics,
                  yaw_deg: float | None = None, pitch_deg: float | None = None):
    """Screen pixel -> map (x, z), by ray/ground-plane intersection.

    Returns None when the ray does not descend toward the ground, rather than
    a point behind the camera that would look like a legitimate coordinate, and
    when a non-finite input leaves no real point.
    """
    yaw_deg, pitch_deg = _pose(cam, intr, yaw_deg, pitch_deg)
    fwd, right, up = camera_basis(yaw_deg, pitch_deg)
    dx = (screen.x - intr.principal_x) / intr.focal_px
    dy = -(screen.y - intr.principal_y) / intr.focal_px
    d = tuple(dx * right[i] + dy * up[i] + fwd[i] for i in range(3))
    if d[1] >= -1e-9:                      # not pointing down: no intersection
        return None
    t = (intr.ground_y - cam.y) / d[1]
    if t <= 0:
        return None
    map_x, map_z = cam.x + t * d[0], cam.z + t * d[2]
    return (map_x, map_z) if _all_finite(map_x, map_z) else None


def map_to_screen(cam: CameraState, map_x: float, map_z: float,
                  intr: Intrinsics, yaw_deg: float | None = None,
                  pitch_deg: float | None = None):
    """Map (x, z) -> screen pixel. The forward direction, for round-tripping.

    Returns None behind the camera, and when a non-finite input leaves no real
    pixel.
    """
    yaw_deg, pitch_deg = _pose(cam, intr, yaw_deg, pitch_deg)
    fwd, right, up = camera_basis(yaw_deg, pitch_deg)
    v = (map_x - cam.x, intr.ground_y - cam.y, map_z - cam.z)
    zc = sum(v[i] * fwd[i] for i in range(3))
    if zc <= 1e-9:                          # behind the camera
        return None
    xc = sum(v[i] * right[i] for i in range(3))
    yc = sum(v[i] * up[i] for i in range(3))
    px = intr.principal_x + intr.focal_px * xc / zc
    py = intr.principal_y - intr.focal_px * yc / zc
    return ScreenPos(x=px, y=py) if _all_finite(px, py) else None
