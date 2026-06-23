"""Behavior tests for dashboard.routes_auto_accept (LIFT 5).

GET /api/lcu/auto-accept reports the core.auto_accept_pref flag; POST with
{"enabled": bool} persists it. The route must be fail-soft, reject a
missing / non-bool "enabled" field with 400, and never leak raw exception
text. Both handlers are driven through a stub handler capturing
_send(status, body, ctype) - the loop_control / aram_balance idiom.

The underlying pref IO is redirected at core.auto_accept_pref._PREF_PATH to
a tmp file so the LIVE data/auto_accept_pref.json is never written. A final
test asserts the live flag is still enabled (or absent) so a redirect
regression can't leave auto-accept OFF on disk.
"""
from __future__ import annotations

import json

import pytest

from core import auto_accept_pref
from dashboard import routes_auto_accept as mod


class FakeHandler:
    """Minimal handler stand-in capturing _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/lcu/auto-accept") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture(autouse=True)
def pref_file(tmp_path, monkeypatch):
    """Redirect the pref file to tmp for every test in this module."""
    p = tmp_path / "auto_accept_pref.json"
    monkeypatch.setattr(auto_accept_pref, "_PREF_PATH", p)
    return p


def _get():
    h = FakeHandler()
    mod._serve_get(h)
    assert h.sent is not None
    status, raw, ctype = h.sent
    return status, json.loads(raw.decode("utf-8")), ctype


def _post(body):
    h = FakeHandler()
    mod._serve_post(h, body)
    assert h.sent is not None
    status, raw, ctype = h.sent
    return status, json.loads(raw.decode("utf-8")), ctype


# --------------------------------------------------------------------- GET
def test_get_default_enabled(pref_file):
    status, payload, ctype = _get()
    assert status == 200 and ctype == "application/json"
    assert payload == {"ok": True, "enabled": True}


def test_get_reflects_disabled(pref_file):
    auto_accept_pref.set_enabled(False)
    status, payload, _ = _get()
    assert status == 200
    assert payload == {"ok": True, "enabled": False}


# --------------------------------------------------------------------- POST
def test_post_disable_persists(pref_file):
    status, payload, ctype = _post({"enabled": False})
    assert status == 200 and ctype == "application/json"
    assert payload == {"ok": True, "enabled": False}
    # Side effect actually persisted.
    assert auto_accept_pref.is_enabled() is False
    assert json.loads(pref_file.read_text(encoding="utf-8")) == {"enabled": False}


def test_post_enable_persists(pref_file):
    auto_accept_pref.set_enabled(False)
    status, payload, _ = _post({"enabled": True})
    assert status == 200
    assert payload == {"ok": True, "enabled": True}
    assert auto_accept_pref.is_enabled() is True


def test_post_missing_enabled_400(pref_file):
    status, payload, _ = _post({"other": 1})
    assert status == 400 and payload["ok"] is False
    assert "error" in payload
    # Nothing persisted; default still True.
    assert auto_accept_pref.is_enabled() is True


def test_post_non_bool_enabled_400(pref_file):
    status, payload, _ = _post({"enabled": "yes"})
    assert status == 400 and payload["ok"] is False
    assert "error" in payload
    assert auto_accept_pref.is_enabled() is True


def test_post_non_dict_body_400(pref_file):
    status, payload, _ = _post(["not", "a", "dict"])
    assert status == 400 and payload["ok"] is False


def test_post_int_one_rejected_not_coerced(pref_file):
    # bool is the contract; 1 is not a bool -> 400 (isinstance(1, bool) False).
    status, payload, _ = _post({"enabled": 1})
    assert status == 400 and payload["ok"] is False


# ------------------------------------------------------------- registration
def test_routes_registered():
    assert len(mod.GET_ROUTES) == 1
    assert len(mod.POST_ROUTES) == 1
    gm, _gfn = mod.GET_ROUTES[0]
    pm, _pfn = mod.POST_ROUTES[0]
    assert gm("/api/lcu/auto-accept") is True
    assert gm("/api/lcu/auto-accept?x=1") is True
    assert gm("/api/lcu/other") is False
    assert pm("/api/lcu/auto-accept") is True


def test_registered_in_dispatch():
    """The route is wired into the dispatcher's GET + POST registries."""
    from dashboard import _dispatch

    # Reset caches so a prior import order doesn't mask the registration.
    _dispatch._GET_CACHE = None
    _dispatch._POST_CACHE = None
    get_paths = [m for m, _ in _dispatch._gather_get()]
    post_paths = [m for m, _ in _dispatch._gather_post()]
    assert any(m("/api/lcu/auto-accept") for m in get_paths), (
        "GET /api/lcu/auto-accept not registered in _dispatch"
    )
    assert any(m("/api/lcu/auto-accept") for m in post_paths), (
        "POST /api/lcu/auto-accept not registered in _dispatch"
    )


def test_live_pref_left_enabled():
    """CRITICAL: the live flag the tick reads must be enabled (or absent)
    after these tests run. The autouse fixture redirects _PREF_PATH to tmp
    so the real file is never written - this guards a redirect regression."""
    from pathlib import Path

    live = (Path(auto_accept_pref.__file__).resolve().parent.parent
            / "data" / "auto_accept_pref.json")
    if live.exists():
        data = json.loads(live.read_text(encoding="utf-8"))
        assert data.get("enabled") is True, (
            f"live auto_accept_pref left disabled: {data!r}"
        )
