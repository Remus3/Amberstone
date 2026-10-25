"""tests/test_gated_frame_readback.py

`tools/gated_frame_readback.py` is the one-command S6 read-back for lane 9. Two
s134 gated cycles lost that read-back to two traps it must now absorb:

- c12: the relay answers a JSON envelope (`vision_server/_frame.py`
  `get_latest_frame`: `b64`, `ts`, `size`, `source`, ...), so handing the body
  straight to Pillow does not decode.
- c13: `core.vision_token` raises at import in a lane worktree, because the
  gitignored `config/vision_token.txt` exists only in the main checkout.

Every test here runs on tmp_path and a loopback server on an ephemeral port; no
test reads the real token or reaches the live :8889 relay.
"""
from __future__ import annotations

import base64
import http.server
import io
import json
import threading

import pytest
from PIL import Image

from tools import gated_frame_readback as gfr

TOKEN = "tok-abcdef0123456789"  # rc-credential-scan: allow-fixture


def _png(w: int = 8, h: int = 4) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 200, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _linked_worktree(tmp_path, main_token: str | None):
    """A fake main checkout + linked worktree laid out the way git does it."""
    main = tmp_path / "main"
    gitdir = main / ".git" / "worktrees" / "lane"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    if main_token is not None:
        (main / "config").mkdir()
        (main / "config" / "vision_token.txt").write_text(main_token + "\n",
                                                          encoding="utf-8")
    return main, wt


# --- main checkout + token resolution --------------------------------------

def test_main_checkout_from_linked_worktree(tmp_path):
    main, wt = _linked_worktree(tmp_path, None)
    assert gfr.main_checkout(wt) == main.resolve()


def test_main_checkout_none_for_a_plain_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    assert gfr.main_checkout(tmp_path) is None
    assert gfr.main_checkout(tmp_path / "missing") is None


def test_token_falls_back_to_the_main_checkout(tmp_path):
    _, wt = _linked_worktree(tmp_path, TOKEN)
    assert gfr.resolve_token(wt, environ={}) == (TOKEN, "main-config")


def test_token_order_env_then_own_config_then_main(tmp_path):
    _, wt = _linked_worktree(tmp_path, "main-token")
    (wt / "config").mkdir()
    (wt / "config" / "vision_token.txt").write_text("own-token\n", encoding="utf-8")
    assert gfr.resolve_token(wt, environ={}) == ("own-token", "config")
    assert gfr.resolve_token(wt, environ={"RC_VISION_TOKEN": " env-token "}) == (
        "env-token", "env")


def test_illegal_token_is_skipped_not_sent(tmp_path):
    _, wt = _linked_worktree(tmp_path, "bad token")  # internal space
    assert gfr.resolve_token(wt, environ={"RC_VISION_TOKEN": "a\tb"}) == ("", "none")


# --- envelope decode --------------------------------------------------------

def test_envelope_b64_is_decoded_and_meta_kept():
    png = _png()
    body = json.dumps({"b64": base64.b64encode(png).decode("ascii"),
                       "ts": 12.5, "source": "self_grab"}).encode("ascii")
    raw, meta = gfr.decode_envelope(body)
    assert raw == png
    assert meta == {"ts": 12.5, "source": "self_grab"}


def test_envelope_without_b64_yields_no_image():
    raw, meta = gfr.decode_envelope(b'{"b64": null, "ts": 0.0}')
    assert raw is None
    assert meta == {"ts": 0.0}


def test_non_json_body_passes_through_as_raw_bytes():
    png = _png()
    raw, meta = gfr.decode_envelope(png)
    assert raw == png and meta == {}


# --- the one GET, end to end on loopback ------------------------------------

class _Relay(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        self.server.hits += 1
        if self.headers.get("X-RC-Token") != TOKEN:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "unauthorized"}')
            return
        if self.server.status != 200:
            self.send_response(self.server.status)
            if self.server.status == 302:
                self.send_header("Location", "/elsewhere")
            self.end_headers()
            self.wfile.write(self.server.body)
            return
        body = self.server.body
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        return


@pytest.fixture
def relay():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Relay)
    srv.hits = 0
    srv.body = b""
    srv.status = 200
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _url(srv) -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}/latest-frame"


def test_read_back_decodes_one_frame_in_one_request(relay, tmp_path):
    _, wt = _linked_worktree(tmp_path, TOKEN)
    relay.body = json.dumps({"b64": base64.b64encode(_png(16, 9)).decode("ascii"),
                             "ts": 1000.0, "source": "self_grab",
                             "format": "png"}).encode("ascii")
    code, report = gfr.read_back(_url(relay), root=wt, environ={},
                                 now=lambda: 1002.5)
    assert code == 0, report
    assert relay.hits == 1
    assert report["http"] == 200
    assert report["token_source"] == "main-config"
    assert report["age_s"] == 2.5
    pil = report["pillow"]
    assert (pil["format"], pil["width"], pil["height"], pil["mode"]) == (
        "PNG", 16, 9, "RGB")
    assert TOKEN not in json.dumps(report)
    assert TOKEN not in gfr._render(report)


def test_read_back_reports_401_for_a_wrong_token(relay, tmp_path):
    _, wt = _linked_worktree(tmp_path, "some-other-token")
    code, report = gfr.read_back(_url(relay), root=wt, environ={})
    assert code == 1
    assert report["http"] == 401
    assert relay.hits == 1


def test_read_back_without_a_token_makes_no_request(relay, tmp_path):
    _, wt = _linked_worktree(tmp_path, None)
    code, report = gfr.read_back(_url(relay), root=wt, environ={})
    assert code == 2
    assert relay.hits == 0


def test_read_back_empty_envelope_is_exit_3(relay, tmp_path):
    _, wt = _linked_worktree(tmp_path, TOKEN)
    relay.body = b'{"b64": null, "ts": 0.0}'
    code, report = gfr.read_back(_url(relay), root=wt, environ={})
    assert code == 3
    assert "age_s" not in report


def test_read_back_undecodable_bytes_is_exit_3(relay, tmp_path):
    _, wt = _linked_worktree(tmp_path, TOKEN)
    relay.body = json.dumps({"b64": base64.b64encode(b"not an image").decode(
        "ascii"), "ts": 5.0}).encode("ascii")
    code, report = gfr.read_back(_url(relay), root=wt, environ={})
    assert code == 3
    assert report["error"].startswith("Pillow could not decode")


def test_read_back_keeps_the_relay_404_reason(relay, tmp_path):
    # vision_server/_http.py answers 404 no_frame_yet before the first frame.
    _, wt = _linked_worktree(tmp_path, TOKEN)
    relay.status = 404
    relay.body = b'{"error": "no_frame_yet"}'
    code, report = gfr.read_back(_url(relay), root=wt, environ={})
    assert code == 1
    assert report["http"] == 404
    assert "no_frame_yet" in report["error"]


def test_read_back_never_follows_a_redirect(relay, tmp_path):
    _, wt = _linked_worktree(tmp_path, TOKEN)
    relay.status = 302
    code, report = gfr.read_back(_url(relay), root=wt, environ={})
    assert code == 1
    assert report["http"] == 302
    assert relay.hits == 1
