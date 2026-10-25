# arch: RM-838 - non-DS reply bodies outside the RM-835 set never carry exception text | section=tests | frozen=no
"""RM-838 (non-DS half): reply bodies outside the RM-835 set never carry
exception text.

Measured at main ee882c98a, before the fix:

- (a) Vision :8889 ``vision_server/_http.py`` ``do_POST`` answered a
  ``_BadBody`` with ``{"error": str(e)}``. Both raisers pass a fixed token
  today, so the reply is only as safe as every future raiser.
- (b) The :8888 HTTPError proxy passthroughs forwarded the upstream's error
  body verbatim: ``dashboard/routes_loadout.py`` ``_serve_lcu_cmd_result_get``
  (to :8889) and ``dashboard/_handler.py`` ``_proxy_to_supervisor`` (to
  :8890, which also forwarded the upstream's own Content-Type).
- (c) The Phase 3 supervisor stored ``{"error": str(e)}`` as
  ``_auto_analyze_last_summary``, which ``/api/env`` serves (through the
  :8888 proxy) as ``auto_analyze.last_summary``.

Decision for (b), recorded in the LEDGER entry: SCRUB the forwarded error body
to a fixed line per status (the status code is kept) rather than keep the
passthrough and fix every upstream. Why: the proxy is the trust boundary, the
two live consumers of ``/api/lcu-cmd-result`` (``web/js/main.js``
``lcuPollResult`` and ``web/js/panels/champ_select.js``) read the body only on
a 200, and "fix every upstream" leaves the class open to the next upstream
regression. The 2xx passthrough is unchanged (a 200 body is the data itself),
which is why (c) is fixed at its source too.

The DS :8860-only sites of the row (``agents/daemon_slayer/**``) are NOT
covered here: that path is owned by an in-session lane this session.

Each case drives the real code path with an exception (or an upstream error
body) whose text carries a marker, a filesystem path and control characters,
and asserts the status and envelope keys are kept, none of that text reaches
the reply, the reply is FIXED (two different texts give the same reply), and
the cause reached the log with its type name, scrubbed.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tests._asyncio_isolation import run_coro
from tests._module_view import this_thread_only

SECRET_PATH = r"C:\Example Repo\data\secret_rm838.db"
_CONTROL_CHARS = ("\x1b", "\r", "\x85", "\x7f")
_LEAKS = ("Example Repo", "secret_rm838", "FAKE-LINE", "Errno",
          "\\u001b", "\\r", "\\n", "\\u0085")


def _evil(marker: str) -> str:
    """Text with a marker, a filesystem path and control characters."""
    return f"{marker} at {SECRET_PATH} \x1b[31m\r\nFAKE-LINE\x85\x7f"


def _assert_clean(raw: bytes | str, *markers: str) -> None:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    for needle in (*_LEAKS, *markers):
        assert needle not in text, f"reply leaks {needle!r}: {text!r}"
    for ch in _CONTROL_CHARS:
        assert ch not in text, f"reply carries control char {ch!r}"


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def text(self) -> str:
        return "\n".join(r.getMessage() for r in self.records)


@pytest.fixture
def capture():
    """Attach a capturing handler to a named logger, isolating it from the
    logger's real handlers (the supervisor logger writes files) AND from its
    filters: ``rc.web_dashboard`` carries the RM-811 ``ScrubFilter``, which
    would mask a call site that stopped scrubbing (measured: that mutant
    survived until the filters were lifted here)."""
    attached: list[tuple[logging.Logger, list, list, bool, int]] = []

    def _attach(name: str) -> _Cap:
        lg = logging.getLogger(name)
        attached.append((lg, list(lg.handlers), list(lg.filters),
                         lg.propagate, lg.level))
        cap = _Cap()
        lg.handlers = [cap]
        lg.filters = []
        lg.propagate = False
        lg.setLevel(logging.DEBUG)
        return cap

    try:
        yield _attach
    finally:
        for lg, handlers, filters, propagate, level in attached:
            lg.handlers = handlers
            lg.filters = filters
            lg.propagate = propagate
            lg.setLevel(level)


# ============================================================ (a) vision :8889
@pytest.fixture()
def vision_server():
    from vision_server._http import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _vision_post(port: int, path: str, body: bytes) -> tuple[int, bytes]:
    from vision_server._config import AUTH_HEADER, AUTH_TOKEN
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body,
        headers={AUTH_HEADER: AUTH_TOKEN}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        finally:
            e.close()


def test_vision_bad_body_reply_never_echoes_the_exception_text(
        vision_server, monkeypatch, capture):
    """A _BadBody raised with any text but a fixed token answers the fixed
    400 line; the raised text goes to the log, scrubbed, with its type."""
    from vision_server import _http
    cap = capture("moon_vision")
    replies = []
    for marker in ("MARKER-ONE", "MARKER-TWO"):
        def _raise(body, _m=marker):
            raise _http._BadBody(_evil(_m))
        monkeypatch.setattr(_http, "_post_lcu_cmd", _raise)
        status, raw = _vision_post(vision_server, "/lcu-cmd", b"{}")
        assert status == 400
        payload = json.loads(raw)
        assert set(payload) == {"error"}
        _assert_clean(raw, marker)
        replies.append(raw)
    assert replies[0] == replies[1], "the 400 reply must be fixed"
    assert json.loads(replies[0]) == {"error": _http._BAD_BODY}
    logged = cap.text()
    assert "_BadBody" in logged and "MARKER-ONE" in logged
    for ch in _CONTROL_CHARS:
        assert ch not in logged, "the logged cause must be scrubbed"


def test_vision_fixed_tokens_still_reach_the_client(vision_server):
    """The two fixed tokens are the contract (RM-268 / RM-760c) and stay."""
    from vision_server import _http
    status, raw = _vision_post(vision_server, "/lcu-cmd", b"[1]")
    assert (status, json.loads(raw)) == (400, {"error": _http._BAD_BODY})
    status, raw = _vision_post(vision_server, "/lcu-cmd", b"{not json")
    assert (status, json.loads(raw)) == (400, {"error": _http._BAD_JSON})


# ================================================ (b) :8888 proxy passthroughs
class _FakeHTTPError(urllib.error.HTTPError):
    """An upstream non-2xx whose body is attacker- or exception-shaped."""

    def __init__(self, code: int, body: bytes, ctype: str) -> None:
        self.code = code
        self._body = body
        self.headers = {"Content-Type": ctype}
        self.closed_n = 0

    def read(self, *a):
        return self._body

    def close(self):
        self.closed_n += 1


def _evil_body(marker: str) -> bytes:
    # RAW bytes, not JSON: a JSON body would arrive with its control
    # characters already escaped, and the log-scrub assertion could pass on
    # an unscrubbed log line.
    return _evil(marker).encode("utf-8")


class _LoadoutHandler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.sent = None

    def _send(self, status, body, ctype, cache_control=None):
        self.sent = (status, body, ctype)


@pytest.mark.parametrize("code", [400, 401, 404, 500])
def test_lcu_cmd_result_proxy_scrubs_the_upstream_error_body(
        code, monkeypatch, capture):
    from dashboard import routes_loadout as mod
    cap = capture("rc.web_dashboard")
    replies = []
    for marker in ("MARKER-ONE", "MARKER-TWO"):
        err = _FakeHTTPError(code, _evil_body(marker), "text/html")

        def _boom(req, timeout=None, _e=err):
            raise _e
        monkeypatch.setattr(mod, "_urlopen", _boom)
        h = _LoadoutHandler("/api/lcu-cmd-result?id=7")
        mod._serve_lcu_cmd_result_get(h)
        status, raw, ctype = h.sent
        assert status == code, "the upstream status code is kept"
        assert ctype == "application/json"
        assert set(json.loads(raw)) == {"error"}
        _assert_clean(raw, marker)
        assert err.closed_n == 1, "the upstream error response is closed"
        replies.append(raw)
    assert replies[0] == replies[1], "the forwarded error body must be fixed"
    logged = cap.text()
    assert "MARKER-ONE" in logged, "the upstream body is logged"
    for ch in _CONTROL_CHARS:
        assert ch not in logged, "the logged upstream body must be scrubbed"


def test_lcu_cmd_result_proxy_keeps_the_pending_404_token(monkeypatch):
    """404 means "not answered yet" to the pollers; its fixed line stays
    "pending" whatever the upstream wrote."""
    from dashboard import routes_loadout as mod

    def _boom(req, timeout=None):
        raise _FakeHTTPError(404, _evil_body("MARKER"), "application/json")
    monkeypatch.setattr(mod, "_urlopen", _boom)
    h = _LoadoutHandler("/api/lcu-cmd-result?id=7")
    mod._serve_lcu_cmd_result_get(h)
    status, raw, _ = h.sent
    assert (status, json.loads(raw)) == (404, {"error": "pending"})


class _ProxyHandler:
    """The attributes `_proxy_to_supervisor` reads on its handler."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.command = "GET"
        self.headers = {}
        self.sent = None
        self.no_frame = 0

    def _send(self, code, body, ctype, cache_control=None):
        self.sent = (code, body, ctype)

    def _minimap_no_frame(self):
        self.no_frame += 1


@pytest.mark.parametrize("code", [400, 404, 500, 503])
def test_supervisor_proxy_scrubs_the_upstream_error_body(
        code, monkeypatch, capture):
    from dashboard import _handler
    cap = capture("rc.web_dashboard")
    replies = []
    for marker in ("MARKER-ONE", "MARKER-TWO"):
        err = _FakeHTTPError(code, _evil_body(marker), f"text/x-{marker}")

        def _boom(req, timeout=None, _e=err):
            raise _e
        monkeypatch.setattr(urllib.request, "urlopen",
                            this_thread_only(_boom, urllib.request.urlopen))
        h = _ProxyHandler("/api/env")
        _handler.Handler._proxy_to_supervisor(h)
        status, raw, ctype = h.sent
        assert status == code, "the upstream status code is kept"
        assert ctype == "application/json", "the upstream Content-Type is not forwarded"
        assert set(json.loads(raw)) == {"error"}
        _assert_clean(raw, marker)
        replies.append(raw)
    assert replies[0] == replies[1], "the forwarded error body must be fixed"
    logged = cap.text()
    assert "MARKER-ONE" in logged, "the upstream body is logged"
    for ch in _CONTROL_CHARS:
        assert ch not in logged, "the logged upstream body must be scrubbed"


def test_supervisor_proxy_minimap_still_collapses_to_204(monkeypatch):
    from dashboard import _handler

    def _boom(req, timeout=None):
        raise _FakeHTTPError(500, _evil_body("MARKER"), "application/json")
    monkeypatch.setattr(urllib.request, "urlopen",
                        this_thread_only(_boom, urllib.request.urlopen))
    h = _ProxyHandler("/api/minimap-crop?mode=sr")
    _handler.Handler._proxy_to_supervisor(h)
    assert h.no_frame == 1 and h.sent is None


def test_supervisor_proxy_2xx_body_is_still_forwarded(monkeypatch):
    """The 2xx passthrough is the data itself and is unchanged."""
    from dashboard import _handler

    class _Resp:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", this_thread_only(
        lambda req, timeout=None: _Resp(), urllib.request.urlopen))
    h = _ProxyHandler("/api/env")
    _handler.Handler._proxy_to_supervisor(h)
    assert h.sent == (200, b'{"ok": true}', "application/json")


# ============================================= (c) supervisor auto-analyze
def test_auto_analyze_failure_summary_never_carries_the_exception_text(
        monkeypatch, capture):
    import agents.agent2_backend.win_reconcile as win_reconcile
    import agents.supervisor as sup_mod
    cap = capture(sup_mod.log.name)
    monkeypatch.setattr(sup_mod, "IDLE_ANALYZE_SEC", 0)
    summaries = []
    for marker in ("MARKER-ONE", "MARKER-TWO"):
        def _raise(_m=marker):
            raise OSError(5, _evil(_m), SECRET_PATH)
        monkeypatch.setattr(win_reconcile, "reconcile_all", _raise)
        sup = sup_mod.Supervisor.__new__(sup_mod.Supervisor)
        sup._auto_analyze_scheduled_at = None
        sup._auto_analyze_running_since = None
        sup._auto_analyze_last_done_at = None
        sup._auto_analyze_last_summary = None
        run_coro(sup._auto_analyze_after_idle())
        stats = sup.auto_analyze_stats()
        summary = stats["last_summary"]
        assert set(summary) == {"error"}, "the envelope key is kept"
        _assert_clean(json.dumps(summary), marker)
        summaries.append(summary)
    assert summaries[0] == summaries[1], "the stored summary must be fixed"
    logged = cap.text()
    assert "OSError" in logged and "MARKER-ONE" in logged
    for ch in _CONTROL_CHARS:
        assert ch not in logged, "the logged cause must be scrubbed"


# ====================== (c) sibling: the per-mode analyze result (/api/analyze)
def test_analyze_all_per_mode_error_never_carries_the_exception_text(
        monkeypatch, capture):
    """Same root cause as (c), found by the RM-838 verifier's sweep:
    ``analyze_all`` stored ``{"error": str(e)}`` per mode, which the
    supervisor's POST /api/analyze returns as ``per_mode`` in a 200 and the
    :8888 ``/api/analyze`` route forwards verbatim."""
    from agents.agent4_coach_mentor import analyzer
    cap = capture(analyzer.logger.name)
    results = []
    for marker in ("MARKER-ONE", "MARKER-TWO"):
        def _raise(mode, _m=marker):
            raise OSError(5, _evil(_m), SECRET_PATH)
        monkeypatch.setattr(analyzer, "analyze_mode", _raise)
        out = analyzer.analyze_all()
        assert set(out) == set(analyzer.SUPPORTED_MODES)
        for per in out.values():
            assert set(per) == {"error"}, "the envelope key is kept"
        _assert_clean(json.dumps(out), marker)
        results.append(out)
    assert results[0] == results[1], "the per-mode error must be fixed"
    logged = cap.text()
    assert "OSError" in logged and "MARKER-ONE" in logged
    for ch in _CONTROL_CHARS:
        assert ch not in logged, "the logged cause must be scrubbed"


def test_analyze_all_missing_db_skip_is_unchanged(monkeypatch):
    from agents.agent4_coach_mentor import analyzer

    def _missing(mode):
        raise FileNotFoundError(_evil("MARKER"))
    monkeypatch.setattr(analyzer, "analyze_mode", _missing)
    out = analyzer.analyze_all()
    assert all(v == {"skipped": True, "reason": "mode DB missing"}
               for v in out.values())
