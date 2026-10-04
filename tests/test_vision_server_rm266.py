"""RM-266 (with RM-266 / RM-267 / RM-268): residues of the vision_server/_relay.py
audit (lane 8 cycle 25), exercised against the REAL Handler on a loopback
port.

RM-266: /lcu-cmd-result hand-rolled the lookup lcu_get_result exists for;
        one lookup now, and the served row is a COPY.
RM-267: /stats was the only unauthenticated data GET on :8889.
RM-268: /lcu-cmd queued any JSON value (list, string, number) as `cmd`;
        a non-object body now gets a fixed 400 token and NOTHING is queued.
"""
from __future__ import annotations

import ast
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from vision_server import _relay
from vision_server._config import AUTH_HEADER, AUTH_TOKEN
from vision_server._http import Handler

_HTTP_SRC = Path(__file__).resolve().parent.parent / "vision_server" / "_http.py"


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


# -- RM-266 ------------------------------------------------------------------

def test_lcu_cmd_result_route_uses_lcu_get_result(server, monkeypatch):
    calls = []

    def spy(cmd_id):
        calls.append(cmd_id)
        return {"result": {"via": "spy"}, "ts": 1.0}

    import vision_server._http as http_mod
    monkeypatch.setattr(http_mod, "lcu_get_result", spy)
    status, payload = _req(server, "/lcu-cmd-result?id=42")
    assert status == 200
    assert calls == [42]
    assert payload["result"] == {"via": "spy"}


def test_lcu_cmd_result_pending_and_bad_id(server):
    assert _req(server, "/lcu-cmd-result?id=9")[0] == 404
    assert _req(server, "/lcu-cmd-result")[0] == 400


def test_http_module_no_longer_touches_the_results_dict():
    tree = ast.parse(_HTTP_SRC.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_lcu_cmd_results" not in names
    assert "_lcu_cmd_lock" not in names
