# arch: tests for POST /api/loadout/rune-pages (rune-follows-build model surface) | section=tests | frozen=no
"""Behavior tests for dashboard.routes_loadout._serve_rune_pages_post.

Item 1 Phase 1 (rune-follows-build): a thin POST route that exposes the
already-shipped coaches.rune_pages.enumerate_pages model to the champ-select
frontend. The route validates {champion, mode} (mode defaults to "sr",
champion is required), echoes champion + mode back alongside the deduped
pages + build->page map, and NEVER surfaces a raw error string to the client
(every exception collapses to the generic envelope + a WARNING log).

Harness mirrors tests/test_loop_status_route.py: a minimal FakeHandler that
captures the _send(status, body, ctype) triple, driven directly against the
handler (no live HTTP server).
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard import routes_loadout as mod


class FakeHandler:
    """Minimal StubHandler stand-in capturing _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/loadout/rune-pages") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


def _serve(payload, path: str = "/api/loadout/rune-pages"):
    h = FakeHandler(path)
    mod._serve_rune_pages_post(h, payload)
    assert h.sent is not None
    status, body, ctype = h.sent
    return status, json.loads(body.decode("utf-8")), ctype


# --------------------------------------------------------------------------- success
def test_valid_payload_returns_pages_and_builds():
    status, body, ctype = _serve({"champion": "Jinx", "mode": "sr"})
    assert status == 200
    assert ctype == "application/json"
    assert body["champion"] == "Jinx"
    assert body["mode"] == "sr"
    assert isinstance(body["pages"], list)
    assert isinstance(body["builds"], list)
    # Every build entry carries the buildId -> recommendedPageId mapping.
    for b in body["builds"]:
        assert "buildId" in b
        assert "recommendedPageId" in b


def test_mode_defaults_to_sr_when_absent():
    status, body, _ = _serve({"champion": "Jinx"})
    assert status == 200
    assert body["mode"] == "sr"


# --------------------------------------------------------------------------- validation
def test_missing_champion_is_400():
    status, body, _ = _serve({"mode": "sr"})
    assert status == 400
    assert body["error"] == "champion required"


def test_empty_champion_is_400():
    status, body, _ = _serve({"champion": "   ", "mode": "sr"})
    assert status == 400
    assert body["error"] == "champion required"


# --------------------------------------------------------------------------- pass-through
def test_enumerate_pages_output_passed_through(monkeypatch):
    # Deterministic pass-through: the handler must echo champion + mode and
    # splice enumerate_pages(champ, mode) verbatim (pages + builds).
    sentinel = {
        "pages": [{"pageId": "pTEST", "keystone": "Lethal Tempo",
                   "primary": "Precision", "secondary": "Domination",
                   "perk_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9]}],
        "builds": [{"buildId": "sentinel-build", "recommendedPageId": "pTEST"}],
    }
    monkeypatch.setattr("coaches.rune_pages.enumerate_pages",
                        lambda champ, mode: sentinel)
    status, body, _ = _serve({"champion": "Whatever", "mode": "aram"})
    assert status == 200
    assert body["champion"] == "Whatever"
    assert body["mode"] == "aram"
    assert body["pages"] == sentinel["pages"]
    assert body["builds"] == sentinel["builds"]


# --------------------------------------------------------------------------- error envelope
def test_exception_collapses_to_generic_500(monkeypatch):
    def _boom(champ, mode):
        raise RuntimeError("secret path C:\\leak.json should never leak")

    monkeypatch.setattr("coaches.rune_pages.enumerate_pages", _boom)
    status, body, _ = _serve({"champion": "Jinx", "mode": "sr"})
    assert status == 500
    assert body["error"] == mod._GENERIC_ERR
    # Raw exception text (file paths etc.) must never reach the client.
    assert "leak.json" not in json.dumps(body)


# --------------------------------------------------------------------------- registration
def test_route_registered():
    paths = [m for m, _ in mod.POST_ROUTES]
    assert any(matcher("/api/loadout/rune-pages") for matcher in paths)


# --------------------------------------------------------------------------- ascii hygiene
def test_this_file_is_ascii():
    raw = Path(__file__).read_bytes()
    bad = [i for i, b in enumerate(raw) if b > 0x7F]
    assert bad == [], f"non-ASCII bytes at offsets {bad[:8]}"
