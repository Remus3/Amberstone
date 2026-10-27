"""True-audit (s144 lane 8) of dashboard/routes_history.py.

Four read-only GET routes over match_history.db / rewind_history.db /
champion_loadouts.json: /api/session/summary, /api/history,
/api/loadouts/all and /api/home/summary. Findings pinned here, each with a
test that was RED on the pre-audit module:

  F1  /api/history?scope=<anything else> silently answered the WHOLE DB
      (dashboard/builders.py _build_history has no else branch, so an
      unknown scope is "all") and echoed the bogus scope back as if it had
      been honoured. Now: 400 {"error": "bad_scope"} before any build;
      absent / empty still means the 14d default.
  F2  prefix("/api/history") and prefix("/api/loadouts/all") answered 200
      with real data for non-routes like /api/historyX or /api/history-foo,
      and would shadow any later route registered under that stem. Now
      exact-path matchers (path or path?query).
  F3  json.dumps defaulted to allow_nan=True, so a NaN / Infinity in a
      builder result was emitted as a bare NaN token that the browser's
      JSON.parse rejects - the panel died on a 200. Now strict JSON; a
      non-finite value is a logged 500 with the generic body, and it is
      never cached.
  F4  when the 200 send itself raised (client gone: the header flush hits
      a reset socket), the except branch sent a SECOND response (500) onto
      the same dead connection and its raise escaped the route. Now one
      send per request; an OSError from it is logged, not re-answered.
  F5  the /api/home/summary cache-hit path called h._send while holding
      _CACHE_LOCK, so one slow reader serialised every other tab's poll
      behind its socket write. The send now happens outside the lock.

Stub-handler shape (``path`` + ``_send(code, body, ctype)``) mirrors
tests/test_home_summary_cache.py. ASCII-only authored content.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard import routes_history as rh  # noqa: E402


class _Stub:
    def __init__(self, path: str, send_error: BaseException | None = None):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []
        self._send_error = send_error

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.responses.append((code, body, ctype))
        if self._send_error is not None:
            raise self._send_error


def _strict_loads(body: bytes):
    def _bad(tok):
        raise ValueError(f"non-strict JSON token {tok!r}")
    return json.loads(body.decode("utf-8"), parse_constant=_bad)


def _route_for(path: str):
    for matcher, fn in rh.GET_ROUTES:
        if matcher(path):
            return fn
    return None


@pytest.fixture(autouse=True)
def _clear_home_cache():
    with rh._CACHE_LOCK:
        rh._CACHE.clear()
    yield
    with rh._CACHE_LOCK:
        rh._CACHE.clear()


# -- F1: scope whitelist ---------------------------------------------------

@pytest.mark.parametrize("scope", ["14d", "season", "prior_season", "all"])
def test_known_scopes_reach_the_builder(scope):
    h = _Stub(f"/api/history?scope={scope}")
    with mock.patch.object(rh, "_build_history",
                           side_effect=lambda s: {"scope": s}) as b:
        rh._serve_history(h)
    b.assert_called_once_with(scope)
    assert h.responses[0][0] == 200
    assert _strict_loads(h.responses[0][1]) == {"scope": scope}


@pytest.mark.parametrize("path", [
    "/api/history", "/api/history?scope=", "/api/history?other=1",
])
def test_absent_or_empty_scope_defaults_to_14d(path):
    h = _Stub(path)
    with mock.patch.object(rh, "_build_history",
                           side_effect=lambda s: {"scope": s}) as b:
        rh._serve_history(h)
    b.assert_called_once_with("14d")
    assert h.responses[0][0] == 200


def test_scope_is_case_and_space_tolerant():
    h = _Stub("/api/history?scope=%20Season%20")
    with mock.patch.object(rh, "_build_history",
                           side_effect=lambda s: {"scope": s}) as b:
        rh._serve_history(h)
    b.assert_called_once_with("season")


@pytest.mark.parametrize("scope", [
    "garbage", "30d", "ALLX", "%C2%B2", "14d%00",
    pytest.param("x" * 5000, id="5000-chars"),
])
def test_unknown_scope_answers_400_without_building(scope):
    h = _Stub(f"/api/history?scope={scope}")
    with mock.patch.object(rh, "_build_history") as b:
        rh._serve_history(h)
    b.assert_not_called()
    assert len(h.responses) == 1
    code, body, ctype = h.responses[0]
    assert code == 400
    assert ctype == "application/json"
    assert _strict_loads(body) == {"error": "bad_scope"}


# -- F2: exact-path matchers -----------------------------------------------

@pytest.mark.parametrize("path,fn_name", [
    ("/api/history", "_serve_history"),
    ("/api/history?scope=all", "_serve_history"),
    ("/api/loadouts/all", "_serve_loadouts_all"),
    ("/api/loadouts/all?mode=sr", "_serve_loadouts_all"),
    ("/api/session/summary", "_serve_session_summary"),
    ("/api/home/summary?mode=ARAM", "_serve_home_summary"),
])
def test_real_paths_still_route(path, fn_name):
    fn = _route_for(path)
    assert fn is not None and fn.__name__ == fn_name


@pytest.mark.parametrize("path", [
    "/api/historyX", "/api/history-foo", "/api/history_resolved",
    "/api/history/extra", "/api/loadouts/allx", "/api/loadouts/all/x",
])
def test_non_routes_are_not_claimed(path):
    assert _route_for(path) is None


# -- F3: strict JSON on every route ----------------------------------------

_NAN_CASES = [
    ("_serve_session_summary", "_build_session_summary",
     "/api/session/summary"),
    ("_serve_history", "_build_history", "/api/history?scope=all"),
    ("_serve_loadouts_all", "_build_loadouts_all", "/api/loadouts/all"),
    ("_serve_home_summary", "_build_home_summary", "/api/home/summary"),
]


@pytest.mark.parametrize("serve,build,path", _NAN_CASES)
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_payload_is_a_generic_500_never_a_nan_token(
        serve, build, path, bad):
    h = _Stub(path)
    with mock.patch.object(rh, build, return_value={"v": bad}):
        getattr(rh, serve)(h)
    assert len(h.responses) == 1
    code, body, _ = h.responses[0]
    assert code == 500
    assert _strict_loads(body) == {"error": rh._GENERIC_ERR}


def test_non_finite_home_summary_is_not_cached():
    h = _Stub("/api/home/summary")
    with mock.patch.object(rh, "_build_home_summary",
                           return_value={"v": float("nan")}):
        rh._serve_home_summary(h)
    assert rh._CACHE == {}


@pytest.mark.parametrize("serve,build,path", _NAN_CASES)
def test_ok_bodies_are_strict_json(serve, build, path):
    h = _Stub(path)
    with mock.patch.object(rh, build, return_value={"v": 1.5, "s": "a"}):
        getattr(rh, serve)(h)
    code, body, ctype = h.responses[0]
    assert code == 200 and ctype == "application/json"
    assert _strict_loads(body) == {"v": 1.5, "s": "a"}


# -- F4: one response per request, even when the send fails ----------------

@pytest.mark.parametrize("serve,build,path", _NAN_CASES)
@pytest.mark.parametrize("err", [ConnectionResetError(10054, "reset"),
                                 BrokenPipeError(32, "pipe")])
def test_failed_send_is_never_answered_twice(serve, build, path, err):
    h = _Stub(path, send_error=err)
    with mock.patch.object(rh, build, return_value={"v": 1}):
        getattr(rh, serve)(h)  # must not raise
    assert [r[0] for r in h.responses] == [200]


def test_failed_500_send_does_not_raise():
    h = _Stub("/api/session/summary", send_error=BrokenPipeError(32, "p"))
    with mock.patch.object(rh, "_build_session_summary",
                           side_effect=RuntimeError("db")):
        rh._serve_session_summary(h)
    assert [r[0] for r in h.responses] == [500]


def test_failed_400_send_does_not_raise():
    h = _Stub("/api/history?scope=bogus", send_error=BrokenPipeError(32, "p"))
    rh._serve_history(h)
    assert [r[0] for r in h.responses] == [400]


# -- F5: no socket write while holding the cache lock ----------------------

class _LockProbe(_Stub):
    def __init__(self, path):
        super().__init__(path)
        self.lock_held: list[bool] = []

    def _send(self, code, body, ctype="application/json"):
        self.lock_held.append(rh._CACHE_LOCK.locked())
        super()._send(code, body, ctype)


def test_cache_hit_sends_outside_the_lock():
    with mock.patch.object(rh, "_build_home_summary",
                           return_value={"ok": 1}) as b:
        miss = _LockProbe("/api/home/summary?mode=SR")
        rh._serve_home_summary(miss)
        hit = _LockProbe("/api/home/summary?mode=SR")
        rh._serve_home_summary(hit)
    assert b.call_count == 1  # second call really was a cache hit
    assert hit.responses[0][1] == miss.responses[0][1]
    assert miss.lock_held == [False]
    assert hit.lock_held == [False]


# -- error-handling characterization: raw text never reaches the body ------

@pytest.mark.parametrize("serve,build,path", _NAN_CASES)
def test_builder_error_text_is_logged_not_served(serve, build, path, caplog):
    h = _Stub(path)
    boom = RuntimeError(r"sqlite blew up at <repo>\data\secret.db")
    with caplog.at_level("WARNING", logger="rc.web_dashboard"):
        with mock.patch.object(rh, build, side_effect=boom):
            getattr(rh, serve)(h)
    code, body, _ = h.responses[0]
    assert code == 500
    assert b"secret" not in body
    assert any("secret.db" in r.getMessage() for r in caplog.records)
