"""RM-267 (with RM-266 / RM-267 / RM-268): residues of the vision_server/_relay.py
audit (lane 8 cycle 25), exercised against the REAL Handler on a loopback
port.

RM-266: /lcu-cmd-result hand-rolled the lookup lcu_get_result exists for;
        one lookup now, and the served row is a COPY.
RM-267: /stats was the only unauthenticated data GET on :8889.
RM-268: /lcu-cmd queued any JSON value (list, string, number) as `cmd`;
        a non-object body now gets a fixed 400 token and NOTHING is queued.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from vision_server import _relay
from vision_server._config import AUTH_HEADER, AUTH_TOKEN
from vision_server._http import Handler

@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    with _relay._lcu_cmd_lock:
        _relay._lcu_cmd_queue.clear()
        _relay._lcu_cmd_results.clear()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
        with _relay._lcu_cmd_lock:
            _relay._lcu_cmd_queue.clear()
            _relay._lcu_cmd_results.clear()


def _req(port, path, body=None, auth=True):
    headers = {AUTH_HEADER: AUTH_TOKEN} if auth else {}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, headers=headers,
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# -- RM-267 ------------------------------------------------------------------

def test_stats_requires_auth(server):
    status, payload = _req(server, "/stats", auth=False)
    assert status == 401
    assert payload == {"error": "unauthorized"}


def test_stats_with_auth_is_served(server):
    status, payload = _req(server, "/stats")
    assert status == 200
    assert isinstance(payload, dict)


def test_health_stays_public(server):
    # Positive control: /health is the one deliberately public probe.
    status, payload = _req(server, "/health", auth=False)
    assert status == 200
    assert "alive" in payload
