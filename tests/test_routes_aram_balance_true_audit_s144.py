"""True-audit (s144 lane 8, S144-T-755) of dashboard/routes_aram_balance.py.

GET /api/aram-balance feeds web/js/panels/aram_balance.js, which caches a
resolved ``champions`` map client-side for the page lifetime and renders a
champion absent from it as the positive claim "no ARAM changes". The route:

- read data/daemon_slayer/current.txt with plain utf-8, so a UTF-8-BOM file
  (what PowerShell 5.1 writes) put U+FEFF into the reply's patch, and put any
  file content at all (several lines, a path, markup, non-ASCII digits, a
  megabyte) into the payload unvalidated;
- memoized a FAILED patch read as "" for the process lifetime;
- answered a grid that failed to load (core.aram_balance_context degrades to
  an empty map on any read failure) as ``200 {"ok": true, "champions": {}}``,
  which the panel caches and renders as "no ARAM changes" on every row;
- sent its 200 inside the catch-all, so a failure while writing it sent a
  SECOND status line (the 500 envelope) onto the same response, and the inner
  ``except Exception: pass`` hid a failing error send from the dispatcher;
- serialized with allow_nan=True, so a non-finite value went out as a bare
  NaN token that the browser's JSON parser rejects.

Every test drives the real route function through a stub handler.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import aram_balance_context as abc
from dashboard import routes_aram_balance as mod


class _H:
    """Stub request handler recording every _send call."""

    def __init__(self, fail_first: BaseException | None = None):
        self.path = "/api/aram-balance"
        self.calls: list[tuple[int, bytes, str]] = []
        self._fail_first = fail_first

    def _send(self, status, body, ctype):
        self.calls.append((status, body, ctype))
        if self._fail_first is not None and len(self.calls) == 1:
            raise self._fail_first

    def only(self) -> tuple[int, dict]:
        assert len(self.calls) == 1, self.calls
        status, body, ctype = self.calls[0]
        assert ctype == "application/json"
        body.decode("ascii")

        def _reject(token):
            raise AssertionError(f"non-strict JSON token {token!r}")

        return status, json.loads(body, parse_constant=_reject)


@pytest.fixture(autouse=True)
def _fresh_caches():
    mod._reset_caches()
    yield
    mod._reset_caches()


@pytest.fixture
def ds_dir(tmp_path, monkeypatch):
    """Point the route's current.txt read at a temp DS data dir."""
    # raising=True: a renamed attribute must fail loudly, never let the
    # good-path tests silently read the real current.txt.
    monkeypatch.setattr(mod, "_DS_DIR", tmp_path)
    return tmp_path


def _write_patch(ds_dir, raw: bytes) -> None:
    (ds_dir / "current.txt").write_bytes(raw)


def _serve() -> tuple[int, dict]:
    h = _H()
    mod._serve_aram_balance(h)
    return h.only()


# --------------------------------------------------------------------------
# characterization: the good path is unchanged
# --------------------------------------------------------------------------

def test_good_patch_and_real_grid(ds_dir):
    _write_patch(ds_dir, b"16.22.1")
    status, body = _serve()
    assert status == 200
    assert body["ok"] is True
    assert body["patch"] == "16.22.1"
    assert body["champions"] == abc.balance_grid_map()
    assert body["champions"]["Aatrox"] == {"aramDamageDealt": 1.05}


@pytest.mark.parametrize("raw", [b"16.22.1\n", b"  16.22.1  \r\n", b"16.22"])
def test_good_patch_forms_are_kept(ds_dir, raw):
    _write_patch(ds_dir, raw)
    assert _serve()[1]["patch"] == raw.decode("ascii").strip()


def test_good_result_is_memoized_per_process(ds_dir):
    _write_patch(ds_dir, b"16.22.1")
    assert _serve()[1]["patch"] == "16.22.1"
    # The grid is built once at import of core.aram_balance_context, so the
    # label it is served under is pinned with it.
    _write_patch(ds_dir, b"16.23.1")
    assert _serve()[1]["patch"] == "16.22.1"


# --------------------------------------------------------------------------
# F1 / F2: the patch is BOM-tolerant and canonical
# --------------------------------------------------------------------------

def test_bom_patch_is_read_without_the_bom(ds_dir):
    _write_patch(ds_dir, b"\xef\xbb\xbf16.22.1\r\n")
    status, body = _serve()
    assert status == 200
    assert body["patch"] == "16.22.1"


@pytest.mark.parametrize("raw", [
    b"16.22.1\n16.21.1\n",                       # two lines
    b"../../secrets",                            # path
    b"16.22.1<img src=x onerror=alert(1)>",      # markup
    "\u0661\u0666.\u0662\u0662.1".encode("utf-8"),  # Arabic-Indic digits
    "\uff11\uff16.22.1".encode("utf-8"),         # fullwidth digits
    b"16",                                       # no minor
    b"16.22.1.4",                                # four parts
    b"1234.22.1",                                # absurd major
    b"16.22.12345",                              # absurd build
    b"-16.22.1",
    b"16.22.1\x00",
    b"\xff\xfe1\x006\x00",                       # not UTF-8
    b"",
    b"   \n",
])
def test_junk_patch_is_blank_and_grid_still_served(ds_dir, raw):
    _write_patch(ds_dir, raw)
    status, body = _serve()
    assert status == 200
    assert body["patch"] == ""
    assert body["champions"] == abc.balance_grid_map()


def test_oversized_patch_file_is_refused(ds_dir):
    _write_patch(ds_dir, b"16.22.1" + b" " * 10_000)
    assert _serve()[1]["patch"] == ""


def test_missing_patch_file_is_blank(ds_dir):
    status, body = _serve()
    assert status == 200
    assert body["patch"] == ""


# --------------------------------------------------------------------------
# F3: a failed patch read is not pinned for the process
# --------------------------------------------------------------------------

def test_failed_patch_read_is_retried(ds_dir):
    assert _serve()[1]["patch"] == ""            # current.txt absent
    _write_patch(ds_dir, b"16.22.1")
    assert _serve()[1]["patch"] == "16.22.1"


def test_junk_patch_is_retried(ds_dir):
    _write_patch(ds_dir, b"\xef\xbb\xbfnot-a-patch")
    assert _serve()[1]["patch"] == ""
    _write_patch(ds_dir, b"16.22.1")
    assert _serve()[1]["patch"] == "16.22.1"


# --------------------------------------------------------------------------
# F4: an empty grid is a load failure, never a resolved "no changes" map
# --------------------------------------------------------------------------

def test_empty_grid_is_503_unavailable(ds_dir, monkeypatch):
    _write_patch(ds_dir, b"16.22.1")
    monkeypatch.setattr(abc, "balance_grid_map", dict)
    status, body = _serve()
    assert status == 503
    assert body == {"ok": False, "error": "aram-balance unavailable - see logs"}


def test_empty_grid_is_not_memoized(ds_dir, monkeypatch):
    _write_patch(ds_dir, b"16.22.1")
    real = abc.balance_grid_map
    monkeypatch.setattr(abc, "balance_grid_map", dict)
    assert _serve()[0] == 503
    monkeypatch.setattr(abc, "balance_grid_map", real)
    status, body = _serve()
    assert status == 200
    assert body["champions"]["Aatrox"] == {"aramDamageDealt": 1.05}


def test_empty_grid_logs_once(ds_dir, monkeypatch, caplog):
    _write_patch(ds_dir, b"16.22.1")
    monkeypatch.setattr(abc, "balance_grid_map", dict)
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        for _ in range(3):
            assert _serve()[0] == 503
    lines = [r for r in caplog.records if "aram-balance" in r.getMessage()]
    assert len(lines) == 1


# --------------------------------------------------------------------------
# F5: a failure while writing the 200 never sends a second status line
# --------------------------------------------------------------------------

def test_send_failure_is_not_followed_by_a_500(ds_dir):
    _write_patch(ds_dir, b"16.22.1")
    h = _H(fail_first=ConnectionResetError("peer reset"))
    with pytest.raises(ConnectionResetError):
        mod._serve_aram_balance(h)
    assert [c[0] for c in h.calls] == [200]


def test_failing_error_send_reaches_the_dispatcher(ds_dir, monkeypatch):
    # The grid build fails AND the error reply cannot be written: the
    # dispatcher (_handler._guarded_dispatch) must see it to close the
    # connection; it used to be swallowed by an inner except-pass.
    def _boom():
        raise OSError("disk gone")

    monkeypatch.setattr(mod, "_get_grid", _boom)
    h = _H(fail_first=ConnectionAbortedError("gone"))
    with pytest.raises(ConnectionAbortedError):
        mod._serve_aram_balance(h)
    assert [c[0] for c in h.calls] == [500]


# --------------------------------------------------------------------------
# F6: the reply is strict JSON
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_value_never_reaches_the_wire(ds_dir, monkeypatch, bad):
    _write_patch(ds_dir, b"16.22.1")
    monkeypatch.setattr(abc, "balance_grid_map",
                        lambda: {"Aatrox": {"aramHealing": bad}})
    status, body = _serve()
    assert status == 500
    assert body == {"ok": False, "error": "aram-balance failed - see logs"}


# --------------------------------------------------------------------------
# RM-835 contract kept: an unexpected failure is the fixed 500 line
# --------------------------------------------------------------------------

def test_unexpected_failure_is_fixed_500_line(monkeypatch):
    def _boom():
        raise RuntimeError("<repo>/secret/path marker-xyz")

    monkeypatch.setattr(mod, "_get_grid", _boom)
    status, body = _serve()
    assert status == 500
    assert body == {"ok": False, "error": "aram-balance failed - see logs"}


def test_routes_table():
    assert len(mod.GET_ROUTES) == 1
    assert mod.GET_ROUTES[0][1] is mod._serve_aram_balance
    assert mod.POST_ROUTES == []
