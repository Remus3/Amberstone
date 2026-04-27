"""Round 40 — dev preview mode (sim fixtures + supervisor route)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


# ── fixture files on disk ───────────────────────────────────────────

_SIM_DIR = Path("data/sim")


def test_manifest_exists_and_lists_fixtures() -> None:
    mf_path = _SIM_DIR / "manifest.json"
    assert mf_path.exists(), "data/sim/manifest.json missing"
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    assert "fixtures" in mf
    assert len(mf["fixtures"]) >= 3


def test_every_manifest_fixture_file_exists() -> None:
    mf = json.loads((_SIM_DIR / "manifest.json").read_text(encoding="utf-8"))
    for f in mf["fixtures"]:
        p = _SIM_DIR / f"{f['name']}.json"
        assert p.exists(), f"fixture {f['name']}.json referenced by manifest is missing"


def test_fixture_shape_has_required_keys() -> None:
    mf = json.loads((_SIM_DIR / "manifest.json").read_text(encoding="utf-8"))
    for f in mf["fixtures"]:
        data = json.loads((_SIM_DIR / f"{f['name']}.json").read_text(encoding="utf-8"))
        assert "meta" in data
        assert "health" in data and data["health"].get("type") == "health"
        assert "state" in data and data["state"].get("type") == "state"
        # State must have a payload.
        assert isinstance(data["state"].get("payload"), dict)


def test_aram_blitz_has_expected_coaching_fields() -> None:
    data = json.loads((_SIM_DIR / "aram_blitz.json").read_text(encoding="utf-8"))
    p = data["state"]["payload"]
    for k in ("game_time", "kda", "champion", "action", "item_build",
              "enemy_comp"):
        assert k in p, f"aram_blitz missing state payload key {k}"


# ── /api/sim/ route (via mocked handler) ────────────────────────────

class _MockHandler:
    def __init__(self, path: str, command: str = "GET") -> None:
        self.path = path
        self.command = command
        self.responses: list[tuple[int, Any]] = []
        self.raw_responses: list[tuple[int, dict, bytes]] = []
        self._pending_status: int | None = None
        self._pending_headers: dict[str, str] = {}

    # JSON sender the real handler uses.
    def _send_json(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def send_error(self, status: int, *_args) -> None:
        self.responses.append((status, {}))

    # Methods the raw-body branch invokes.
    def send_response(self, status: int) -> None:
        self._pending_status = status
    def send_header(self, k: str, v: str) -> None:
        self._pending_headers[k.lower()] = v
    def end_headers(self) -> None:
        pass
    @property
    def wfile(self):
        parent = self
        class W:
            def write(self, data: bytes) -> None:
                parent.raw_responses.append(
                    (parent._pending_status or 200,
                     dict(parent._pending_headers),
                     data),
                )
        return W()


def _make_handler(path: str, command: str = "GET"):
    from agents.supervisor import _QuietHandler
    h = _MockHandler(path, command=command)
    h._handle_sim_fixture = _QuietHandler._handle_sim_fixture.__get__(h)
    h._SIM_DIR = _QuietHandler._SIM_DIR
    return h


def test_sim_route_serves_existing_fixture() -> None:
    h = _make_handler("/api/sim/aram_blitz")
    h._handle_sim_fixture()
    assert h.raw_responses, "expected raw body write"
    status, headers, body = h.raw_responses[0]
    assert status == 200
    assert "application/json" in headers.get("content-type", "")
    data = json.loads(body.decode("utf-8"))
    assert data["meta"]["name"] == "aram_blitz"


def test_sim_route_without_name_returns_manifest() -> None:
    h = _make_handler("/api/sim/")
    h._handle_sim_fixture()
    status, _, body = h.raw_responses[0]
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert "fixtures" in data


def test_sim_route_manifest_alias() -> None:
    h = _make_handler("/api/sim/_manifest")
    h._handle_sim_fixture()
    status, _, body = h.raw_responses[0]
    assert status == 200
    assert b"fixtures" in body


def test_sim_route_rejects_traversal() -> None:
    h = _make_handler("/api/sim/..%2Fconfig")
    h._handle_sim_fixture()
    status, body = h.responses[0]
    assert status == 400


def test_sim_route_rejects_bad_chars() -> None:
    h = _make_handler("/api/sim/foo$bar")
    h._handle_sim_fixture()
    status, _ = h.responses[0]
    assert status == 400


def test_sim_route_404_on_missing() -> None:
    h = _make_handler("/api/sim/definitely_not_a_fixture_xyz")
    h._handle_sim_fixture()
    status, _ = h.responses[0]
    assert status == 404


def test_sim_route_accepts_dot_json_suffix() -> None:
    """clients may request .json suffix; handler should strip it."""
    h = _make_handler("/api/sim/aram_blitz.json")
    h._handle_sim_fixture()
    status, _, body = h.raw_responses[0]
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["meta"]["name"] == "aram_blitz"


def test_sim_route_head_sends_headers_without_body() -> None:
    """HEAD must route through and send headers but skip the body."""
    h = _make_handler("/api/sim/aram_blitz", command="HEAD")
    h._handle_sim_fixture()
    # No raw body write when command is HEAD.
    assert h.raw_responses == []
    assert h._pending_status == 200


# ── HTML + JS wiring ────────────────────────────────────────────────

def test_html_has_sim_banner_scaffold() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="sim-banner"' in html
    assert 'id="sim-select"' in html
    assert "DEV PREVIEW" in html
    # sim.js must be loaded BEFORE dashboard.js.
    idx_sim = html.index("sim.js")
    idx_dash = html.index("dashboard.js")
    assert idx_sim < idx_dash, "sim.js must load before dashboard.js"


def test_sim_js_intercepts_api_and_websocket() -> None:
    js = Path("web/js/sim.js").read_text(encoding="utf-8")
    assert "window.fetch" in js
    assert "window.WebSocket" in js
    assert "FakeSocket" in js
    assert "/api/sim/" in js
    # Banner wiring.
    assert "sim-banner" in js
    assert "sim-select" in js


def test_sim_js_noops_without_sim_param() -> None:
    """Defensive: the very first check should bail on no sim param."""
    js = Path("web/js/sim.js").read_text(encoding="utf-8")
    assert 'if (!simName) return' in js


def test_css_has_sim_banner_rules() -> None:
    css = Path("web/css/dashboard.css").read_text(encoding="utf-8")
    assert ".sim-banner" in css
    assert ".sim-missing" in css
