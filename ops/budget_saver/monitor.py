"""RC Budget-Saver standalone monitor (C8).

Serves a tiny status page on 127.0.0.1:4100 showing the current launch
profile/model (from state.json), the DEFER-TO-CLAUDE queue depth, and
whether the LiteLLM proxy is reachable on :4000. Links out to the LiteLLM
/ui and the RC loop-monitor for deeper drill-down.

Launch via pythonw.exe (no console flash) - see README for the shim.
"""
import html
import http.server
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state
import defer_queue  # noqa: E402  (sibling modules, path inserted above)

PROXY_HEALTH_URL = "http://127.0.0.1:4000/health/liveliness"
LITELLM_UI_URL = "http://127.0.0.1:4000/ui"
LOOP_MONITOR_URL = "https://127.0.0.1:8888/loop-monitor"
MONITOR_HOST = "127.0.0.1"
MONITOR_PORT = 4100


def _check_proxy_up(timeout: float = 3.0) -> bool:
    """Best-effort ping of the LiteLLM proxy. Any connection error (proxy
    down, refused, timeout, malformed response) is treated as not-up -
    never raises. OSError covers socket/connection/timeout failures;
    URLError/HTTPError cover urllib's own wrapped failure modes."""
    try:
        req = urllib.request.Request(PROXY_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return False


def render_status() -> dict:
    """Assemble the current budget-saver status. Reads state + defer_queue
    as module attributes (not direct imports) so tests can monkeypatch
    mon.state / mon.defer_queue with stub modules."""
    s = state.read()
    depth = len(defer_queue.load())
    return {
        "profile": s.get("profile"),
        "model": s.get("model"),
        "started_at": s.get("started_at"),
        "defer_depth": depth,
        "proxy_up": _check_proxy_up(),
    }


def _render_html(status: dict) -> bytes:
    rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in status.items()
    )
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>RC Budget-Saver Monitor</title></head>
<body>
<h1>RC Budget-Saver</h1>
<table border="1" cellpadding="6">
<tr><th>key</th><th>value</th></tr>
{rows}
</table>
<p><a href="{LITELLM_UI_URL}">LiteLLM /ui</a></p>
<p><a href="{LOOP_MONITOR_URL}">RC loop-monitor</a></p>
</body></html>"""
    return page.encode("utf-8")


class _MonitorHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
        pass  # keep the monitor quiet; state is visible on the page itself

    def do_GET(self):  # noqa: N802 - stdlib handler name
        if self.path in ("/", "/status.json") :
            status = render_status()
            if self.path == "/status.json":
                body = json.dumps(status, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = _render_html(status)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def serve(host: str = MONITOR_HOST, port: int = MONITOR_PORT) -> None:
    """Run the monitor HTTP server forever. Bound to 127.0.0.1 only per
    the budget-saver security constraint (no LAN exposure)."""
    httpd = http.server.HTTPServer((host, port), _MonitorHandler)
    print(f"[monitor] serving http://{host}:{port}/  (links: {LITELLM_UI_URL} , {LOOP_MONITOR_URL})")
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
