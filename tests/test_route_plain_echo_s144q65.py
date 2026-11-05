"""RM-1376: two dashboard 400 replies interpolated caller text with a plain
``{x}`` f-string field, which the RM-1255 repr guard
(tests/test_dashboard_route_no_repr_echo_guard_rm1255.py) cannot see.

- dashboard/routes_sr_user_builds.py ``_serve_user_builds_post`` answered an
  unknown ``action`` with ``f"unknown action: {action[:32]}"`` - the caller's
  token, clipped but echoed.
- dashboard/routes_vision_calibrator.py ``validate_regions`` prefixed each
  box refusal with the caller's region ``{name}``.

Fixed: the action 400 is one fixed text naming the parameter and the allowed
values; a box refusal names the region by its 1-based POSITION in the
submitted object ("region 2: ..."), which the server derives and the caller
cannot steer into the text. The calibrator page renders the error with
``textContent`` after "SAVE FAILED: " (web/vision_calibrator.html setStatus),
so the position still tells the operator which box to fix.

Every case is driven through the route entry point the dashboard dispatches
to, with a marker string that must not come back.
"""
from __future__ import annotations

import json

import pytest

from dashboard import routes_sr_user_builds as ub
from dashboard import routes_vision_calibrator as vc

_MARK = "ECHOMARKq65"


class _Handler:
    def __init__(self, path: str = "/"):
        self.path = path
        self.sent = None

    def _send(self, code, body, ctype):
        self.sent = (code, body, ctype)

    @property
    def code(self):
        return self.sent[0]

    @property
    def raw(self) -> str:
        return self.sent[1].decode("utf-8")

    @property
    def payload(self):
        return json.loads(self.raw)


# -- sr user-builds: unknown action ----------------------------------------

_ACTION_TEXT = "action: must be list, add, update or delete"


@pytest.mark.parametrize("action", [_MARK, _MARK * 20, "x" + _MARK],
                         ids=["mark", "mark-x20", "prefixed"])
def test_unknown_action_400_is_fixed_text_and_echoes_nothing(action):
    h = _Handler("/api/sr-draft/user-builds")
    ub._serve_user_builds_post(h, {"action": action, "champion": "Tristana"})
    assert h.code == 400
    assert h.payload == {"error": _ACTION_TEXT}
    assert _MARK not in h.raw
    assert _MARK.lower() not in h.raw


def test_known_actions_are_not_refused_as_unknown(tmp_path, monkeypatch):
    # Positive control: the four real actions never reach the unknown-action
    # reply. The store is redirected to tmp_path so the real one is never
    # read or written; list answers 200, the other three their own 400.
    from coaches import sr_user_builds as store
    monkeypatch.setattr(store, "_STORE_PATH", tmp_path / "user_builds.json")
    store.clear_cache()
    try:
        expected = {"list": 200, "add": 400, "update": 400, "delete": 400}
        for action, code in expected.items():
            h = _Handler("/api/sr-draft/user-builds")
            ub._serve_user_builds_post(
                h, {"action": action, "champion": "Tristana"})
            assert h.code == code, action
            if code == 400:
                assert h.payload.get("error") != _ACTION_TEXT, action
    finally:
        store.clear_cache()
    assert not (tmp_path / "user_builds.json").exists()


# -- vision calibrator: region-name echo -----------------------------------

_BAD_BOXES = [
    ([1, 2, 3], "expected [x1,y1,x2,y2]"),
    ([1, 2, 3, "x"], "coordinates must be numbers"),
    ([1, 2, 3, float("nan")], "coordinates must be finite"),
    ([-5, 2, 30, 40], "coordinates out of range"),
    ([900, 10, 800, 40], "x2>x1 and y2>y1 required (non-empty box)"),
]


@pytest.mark.parametrize("box,tail", _BAD_BOXES)
def test_validate_regions_names_the_position_not_the_name(box, tail):
    regions = {"hp": [0, 0, 10, 10], _MARK: box}
    ok, err, clean = vc.validate_regions(regions)
    assert ok is False
    assert clean == {}
    assert err == f"region 2: {tail}"
    assert _MARK not in err


@pytest.mark.parametrize("box,tail", _BAD_BOXES)
def test_regions_post_400_echoes_no_region_name(box, tail, tmp_path,
                                                 monkeypatch):
    target = tmp_path / "vision_regions.json"
    target.write_bytes(b'{"hp": [1, 2, 3, 4]}\n')
    monkeypatch.setattr(vc, "REGIONS_PATH", target)
    h = _Handler("/api/vision-regions")
    vc._serve_regions_post(h, {"regions": {_MARK: box}})
    assert h.code == 400
    assert h.payload == {"ok": False, "error": f"region 1: {tail}"}
    assert _MARK not in h.raw
    assert target.read_bytes() == b'{"hp": [1, 2, 3, 4]}\n'


@pytest.mark.parametrize("box,tail", _BAD_BOXES)
def test_profile_post_400_echoes_no_region_name(box, tail, monkeypatch):
    from core import vision_profiles as vp
    calls = []
    monkeypatch.setattr(vp, "save_profile", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(vp, "active_config_key", lambda: "cfg")
    h = _Handler("/api/vision-regions")
    vc._serve_regions_post(h, {"regions": {"a": [0, 0, 5, 5],
                                           "b": [0, 0, 5, 5], _MARK: box},
                               "base": [2560, 1440]})
    assert h.code == 400
    assert h.payload == {"ok": False, "error": f"region 3: {tail}"}
    assert _MARK not in h.raw
    assert calls == []


def test_valid_regions_still_pass_unchanged():
    ok, err, clean = vc.validate_regions({_MARK: [0, 0, 10, 10]})
    assert ok, err
    assert clean == {_MARK: [0, 0, 10, 10]}
