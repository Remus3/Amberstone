"""Pure geometry for the screen-to-map back-projection. Headless.

The live half (camera writability, champion visibility) is recorded in the
module docstring as measured facts; only the maths is unit-tested here.
"""
from __future__ import annotations

from core import replay_camera as rcam


def test_an_offscreen_champion_reads_as_none_not_a_huge_number():
    # The client writes FLT_MAX when a champion is off screen. Returning None
    # is the whole point: back-projecting 3.4e38 yields a numeric-looking
    # coordinate that is complete nonsense.
    raw = "340282346638528859811704183484516925440.0000000,340282346638528859811704183484516925440.0000000"
    assert rcam.parse_screen_pos(raw) is None


def test_a_visible_champion_parses_into_a_screen_position():
    p = rcam.parse_screen_pos("1285.6757813,592.2059937")
    assert p is not None
    assert round(p.x, 2) == 1285.68
    assert round(p.y, 2) == 592.21


def test_malformed_screen_positions_are_none_rather_than_raising():
    for bad in (None, "", "1285.6", "a,b", 42):
        assert rcam.parse_screen_pos(bad) is None


def test_camera_from_reads_map_axes_as_x_and_z_with_y_as_height():
    cam = rcam.camera_from({
        "cameraPosition": {"x": 9043.26, "y": 1911.84, "z": 881.18},
        "fieldOfView": 40.0, "cameraMode": "top"})
    assert round(cam.x) == 9043      # map axis
    assert round(cam.z) == 881       # map axis
    assert round(cam.y) == 1912      # HEIGHT, not a map axis
    assert cam.fov == 40.0


def test_scale_is_solved_from_a_known_camera_displacement():
    a = rcam.CameraState(x=1000.0, y=1900.0, z=2000.0, fov=40.0)
    b = rcam.CameraState(x=1100.0, y=1900.0, z=2050.0, fov=40.0)
    # Camera moved +100 map-x; a stationary champion slid -10 px on screen.
    scale = rcam.solve_scale(a, rcam.ScreenPos(500.0, 400.0),
                             b, rcam.ScreenPos(490.0, 395.0))
    assert scale is not None
    assert round(scale[0], 3) == 10.0     # 100 units per 10 px
    assert round(scale[1], 3) == 10.0


def test_scale_returns_none_when_the_camera_did_not_move():
    a = rcam.CameraState(x=1000.0, y=1900.0, z=2000.0, fov=40.0)
    # Identical screen positions - no displacement to divide by. Must refuse
    # rather than fabricate a default scale.
    assert rcam.solve_scale(a, rcam.ScreenPos(500.0, 400.0),
                            a, rcam.ScreenPos(500.0, 400.0)) is None


def test_back_projection_recovers_the_camera_point_at_screen_centre():
    cam = rcam.CameraState(x=7000.0, y=1900.0, z=7000.0, fov=40.0)
    centre = rcam.ScreenPos(960.0, 540.0)
    got = rcam.back_project(cam, centre, centre, (10.0, 10.0))
    assert got == (7000.0, 7000.0)


def test_back_projection_offsets_from_screen_centre_by_the_scale():
    cam = rcam.CameraState(x=7000.0, y=1900.0, z=7000.0, fov=40.0)
    centre = rcam.ScreenPos(960.0, 540.0)
    got = rcam.back_project(cam, rcam.ScreenPos(1060.0, 640.0), centre,
                            (10.0, 10.0))
    assert got == (8000.0, 8000.0)


def test_the_sentinel_threshold_sits_far_below_flt_max():
    assert rcam.FLT_MAX_SENTINEL < 3.4028235e38
    assert rcam.FLT_MAX_SENTINEL > 1e30
