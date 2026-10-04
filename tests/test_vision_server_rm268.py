"""RM-268 (with RM-266 / RM-267 / RM-268): residues of the vision_server/_relay.py
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


# -- RM-268 ------------------------------------------------------------------

@pytest.mark.parametrize("body", [b"[1,2]", b'"x"', b"5", b"null", b"true"])
def test_non_object_lcu_cmd_is_400_and_queues_nothing(server, body):
    status, payload = _req(server, "/lcu-cmd", body)
    assert status == 400
    assert payload == {"error": "body must be a JSON object"}
    assert len(_relay._lcu_cmd_queue) == 0


def test_object_lcu_cmd_is_still_queued(server):
    status, payload = _req(server, "/lcu-cmd", b'{"action": "accept"}')
    assert status == 200
    assert isinstance(payload["id"], int)
    assert len(_relay._lcu_cmd_queue) == 1


def test_non_object_lcu_cmd_done_is_400(server):
    status, payload = _req(server, "/lcu-cmd-done", b"[1]")
    assert status == 400
    assert payload == {"error": "body must be a JSON object"}
    assert _relay._lcu_cmd_results == {}


def test_lcu_cmd_done_records_result(server):
    status, _ = _req(server, "/lcu-cmd-done", b'{"id": 7, "result": {"ok": 1}}')
    assert status == 200
    assert _relay._lcu_cmd_results[7]["result"] == {"ok": 1}
