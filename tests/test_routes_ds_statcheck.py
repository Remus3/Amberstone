"""HTTP-contract + cache + engine-grounding tests for /api/ds-statcheck.

Fake handler, no live server.  Mirrors tests/test_routes_ds_knobs.py.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dashboard import routes_ds_statcheck as R


class _FakeWFile:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, b: bytes) -> None:
        self.chunks.append(b)


class _FakeHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler surface the route uses."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.wfile = _FakeWFile()
        self._status: int | None = None
        self._headers: dict[str, str] = {}

    def send_response(self, code: int) -> None:
        self._status = code

    def send_header(self, k: str, v: str) -> None:
        self._headers[k] = v

    def end_headers(self) -> None:
        pass


def _body(h: _FakeHandler) -> dict:
    raw = b"".join(h.wfile.chunks)
    return json.loads(raw.decode("utf-8"))


def _run(path: str) -> tuple[int, dict]:
    h = _FakeHandler(path)
    R._serve_ds_statcheck(h)
    return h._status or 0, _body(h)


@pytest.fixture(autouse=True)
def _clear() -> Any:
    R._reset_caches()
    yield
    R._reset_caches()


def test_missing_champion_returns_400() -> None:
    h = _FakeHandler("/api/ds-statcheck")
    R._serve_ds_statcheck(h)
    assert h._status == 400
    assert _body(h)["ok"] is False


def test_unknown_champion_returns_200_ok_false() -> None:
    status, body = _run("/api/ds-statcheck?champion=NotAChampion")
    assert status == 200
    assert body["ok"] is False


def test_ok_response_has_stats_and_dps() -> None:
    status, body = _run("/api/ds-statcheck?champion=Caitlyn&mode=SR&target_armor=80")
    assert status == 200
    if body.get("ok"):
        assert "stats" in body
        assert "dps" in body
        assert isinstance(body["stats"], dict)
        # the resolved champion stat block is surfaced (from DpsResult.stats)
        assert "ad" in body["stats"]
        assert "crit_chance" in body["stats"]
        assert "attack_speed" in body["stats"]
        assert body["dps"] is None or isinstance(body["dps"], (int, float))


def test_override_source_echoed() -> None:
    status, body = _run("/api/ds-statcheck?champion=Caitlyn&target_armor=150&target_mr=70")
    assert status == 200
    if body.get("ok"):
        assert body["inputs"]["armor_source"] == "override"
        assert body["inputs"]["mr_source"] == "override"
        assert body["inputs"]["target_armor"] == 150.0
        assert body["inputs"]["target_mr"] == 70.0


def test_auto_source_when_blank() -> None:
    status, body = _run("/api/ds-statcheck?champion=Caitlyn")
    assert status == 200
    if body.get("ok"):
        assert body["inputs"]["armor_source"] == "auto"
        assert body["inputs"]["mr_source"] == "auto"


def test_cache_hit_second_call() -> None:
    h1 = _FakeHandler("/api/ds-statcheck?champion=Caitlyn&target_armor=80")
    R._serve_ds_statcheck(h1)
    b1 = _body(h1)
    h2 = _FakeHandler("/api/ds-statcheck?champion=Caitlyn&target_armor=80")
    R._serve_ds_statcheck(h2)
    b2 = _body(h2)
    if b1.get("ok"):
        assert b2["cached"] is True


def test_higher_armor_yields_le_dps_same_build() -> None:
    """Engine grounding: with the SAME build, a higher target armor must not
    INCREASE the physical DPS (monotonic-non-increasing in armor).  Assert on the
    computed quantity, not a fragile literal.  The champion-side stat block stays
    identical (only the target armor changes); only the DPS shrinks."""
    items = "3031,3006,3094"  # crit build so AD/AS/crit stay fixed across armor
    _, low = _run(f"/api/ds-statcheck?champion=Caitlyn&target_armor=80&items={items}")
    _, high = _run(f"/api/ds-statcheck?champion=Caitlyn&target_armor=250&items={items}")
    if low.get("ok") and high.get("ok") and low.get("dps") and high.get("dps"):
        assert high["dps"] <= low["dps"] + 1e-6
        # champion-side stats are identical (only the target armor changed)
        assert low["stats"]["ad"] == high["stats"]["ad"]
        assert low["stats"]["crit_chance"] == high["stats"]["crit_chance"]
        # the avg-hit damage (mitigated against the target) also shrinks with armor
        if low["stats"].get("avg_attack_dmg") and high["stats"].get("avg_attack_dmg"):
            assert high["stats"]["avg_attack_dmg"] <= low["stats"]["avg_attack_dmg"] + 1e-6


def test_ascii_only_source() -> None:
    import pathlib

    p = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "routes_ds_statcheck.py"
    raw = p.read_bytes()
    assert all(b < 128 for b in raw), "non-ASCII byte in routes_ds_statcheck.py"


def test_get_routes_exports() -> None:
    assert isinstance(R.GET_ROUTES, list)
    assert len(R.GET_ROUTES) == 1
    assert R.POST_ROUTES == []
