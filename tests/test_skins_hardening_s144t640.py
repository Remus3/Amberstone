"""Lane 8 true-audit (s144 cycle 235, S144-T-640..646): core/skins.py hardening.

The module docstring and docs/SKINS_CHROMAS.md promise that every public
function "degrades to an empty / None result on missing or bad data and never
raises", and that the CDragon refresh is "https only, returns False on any
failure". Each test below pins one place where the shipped code broke that
promise. Synthetic fixtures only; no network.
"""
from __future__ import annotations

import http.client
import io
import json

import pytest

from core import skins
from tests._module_view import bind_urlopen


class _Resp(io.BytesIO):
    """Stand-in for the urlopen response context manager."""

    def __init__(self, body: bytes, url: str = "https://example.invalid/skins.json"):
        super().__init__(body)
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self._url


def _serve(monkeypatch, doc, url="https://example.invalid/skins.json"):
    body = doc if isinstance(doc, bytes) else json.dumps(doc).encode("utf-8")
    bind_urlopen(monkeypatch, skins, lambda *a, **k: _Resp(body, url))


_GOOD = {"1001": {"name": "A", "chromas": [{"id": 1010, "name": "R"}]}}


def _good_cache(tmp_path):
    c = tmp_path / "c.json"
    c.write_text(json.dumps(_GOOD), encoding="utf-8")
    return c


# S144-T-640: a non-list truthy "chromas" field raised TypeError out of a
# function documented never to raise.
@pytest.mark.parametrize("junk", [5, 1.5, True, {"id": 1}, "abc"])
def test_refresh_survives_non_list_chromas(tmp_path, monkeypatch, junk):
    _serve(monkeypatch, {"1001": {"id": 1001, "name": "A", "chromas": junk},
                         "1002": {"id": 1002, "name": "B", "chromas": []}})
    c = tmp_path / "c.json"
    assert skins.refresh_cdragon_cache(cache=c) is True
    doc = json.loads(c.read_text(encoding="utf-8"))
    assert doc["1001"]["chromas"] == []
    assert doc["1002"] == {"name": "B", "chromas": []}


# S144-T-641: http.client.HTTPException (IncompleteRead, BadStatusLine,
# LineTooLong) is NOT an OSError, so a truncated response escaped.
@pytest.mark.parametrize("exc", [
    http.client.IncompleteRead(b"x", 10),
    http.client.BadStatusLine("junk"),
    http.client.LineTooLong("header"),
])
def test_refresh_returns_false_on_http_protocol_errors(tmp_path, monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    bind_urlopen(monkeypatch, skins, boom)
    c = _good_cache(tmp_path)
    assert skins.refresh_cdragon_cache(cache=c) is False
    assert json.loads(c.read_text(encoding="utf-8")) == _GOOD


# S144-T-642: an upstream document with ZERO usable rows replaced a good
# cache with "{}" and reported success.
@pytest.mark.parametrize("doc", [{}, {"x": 3, "y": {"id": "junk"}}, {"z": None}])
def test_refresh_never_clobbers_cache_with_empty_result(tmp_path, monkeypatch, doc):
    _serve(monkeypatch, doc)
    c = _good_cache(tmp_path)
    assert skins.refresh_cdragon_cache(cache=c) is False
    assert json.loads(c.read_text(encoding="utf-8")) == _GOOD


# S144-T-643: urllib follows an https -> http redirect, so the https-only
# check was bypassable; the FINAL url is what must be https.
def test_refresh_rejects_redirect_off_https(tmp_path, monkeypatch):
    _serve(monkeypatch, {"1": {"id": 1, "name": "A", "chromas": []}},
           url="http://example.invalid/skins.json")
    c = tmp_path / "c.json"
    assert skins.refresh_cdragon_cache(cache=c) is False
    assert not c.exists()


def test_refresh_rejects_body_over_cap(tmp_path, monkeypatch):
    """An over-cap body is refused outright, not silently truncated."""
    doc = {"1": {"id": 1, "name": "A", "chromas": []}}
    # One byte over the cap: the whole (valid) body arrives, so only the
    # explicit length check - not a JSON parse failure - can refuse it.
    monkeypatch.setattr(skins, "_FETCH_CAP", len(json.dumps(doc).encode()) - 1)
    _serve(monkeypatch, doc)
    c = _good_cache(tmp_path)
    assert skins.refresh_cdragon_cache(cache=c) is False
    assert json.loads(c.read_text(encoding="utf-8")) == _GOOD


# S144-T-644: junk chroma ids and non-string names were copied verbatim into
# the cache; the writer now keeps only what the reader would accept.
def test_refresh_slims_and_validates_rows(tmp_path, monkeypatch):
    _serve(monkeypatch, {"1": {"id": 1, "name": 7, "chromas": [
        {"id": "bad"}, {"id": 5, "name": 3}, {"id": "6", "name": "Ruby"}, "x"]}})
    c = tmp_path / "c.json"
    assert skins.refresh_cdragon_cache(cache=c) is True
    doc = json.loads(c.read_text(encoding="utf-8"))
    assert doc == {"1": {"name": "1", "chromas": [
        {"id": 5, "name": "5"}, {"id": 6, "name": "Ruby"}]}}
    assert skins.chromas_for(1, cache=c) == [
        {"id": 5, "name": "5"}, {"id": 6, "name": "Ruby"}]


def test_refresh_uses_per_writer_scratch_and_leaves_none(tmp_path, monkeypatch):
    """The cache write goes through core.polled_json (per-writer scratch name,
    bounded WinError-5 retry, scratch removed on failure), not a fixed
    `<name>.tmp` sibling shared by every concurrent refresh."""
    from core import polled_json
    calls = []
    real = polled_json.atomic_write_bytes

    def spy(path, data):
        calls.append(path)
        real(path, data)
    monkeypatch.setattr(polled_json, "atomic_write_bytes", spy)
    _serve(monkeypatch, {"1": {"id": 1, "name": "A", "chromas": []}})
    c = tmp_path / "sub" / "c.json"
    assert skins.refresh_cdragon_cache(cache=c) is True
    assert calls == [c]
    assert sorted(p.name for p in c.parent.iterdir()) == ["c.json"]


def test_refresh_write_failure_returns_false_and_keeps_cache(tmp_path, monkeypatch):
    from core import polled_json

    def deny(path, data):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(polled_json, "atomic_write_bytes", deny)
    _serve(monkeypatch, {"1": {"id": 1, "name": "A", "chromas": []}})
    c = _good_cache(tmp_path)
    assert skins.refresh_cdragon_cache(cache=c) is False
    assert json.loads(c.read_text(encoding="utf-8")) == _GOOD


# S144-T-645: _latest_detail_dir trusted `latest_pulled` through a
# `[0-9.]{1,12}` regex that admits "..", escaping the DDragon root; and a
# directory name with a non-ASCII digit raised ValueError out of the sort key.
@pytest.mark.parametrize("ver", ["..", ".", "...", "1..2", ".15", "15."])
def test_latest_detail_dir_rejects_dot_versions(tmp_path, ver):
    base = tmp_path / "dd"
    (base / "15.1.1" / "champion_detail").mkdir(parents=True)
    (tmp_path / "champion_detail").mkdir()
    (base / "_index.json").write_text(json.dumps({"latest_pulled": ver}),
                                      encoding="utf-8")
    got = skins._latest_detail_dir(base)
    assert got == base / "15.1.1" / "champion_detail"


def test_latest_detail_dir_honours_valid_index(tmp_path):
    base = tmp_path / "dd"
    for v in ("15.1.1", "15.2.1"):
        (base / v / "champion_detail").mkdir(parents=True)
    (base / "_index.json").write_text(json.dumps({"latest_pulled": "15.1.1"}),
                                      encoding="utf-8")
    assert skins._latest_detail_dir(base) == base / "15.1.1" / "champion_detail"


def test_latest_detail_dir_survives_non_ascii_digit_dir(tmp_path):
    base = tmp_path / "dd"
    (base / "15.9.1" / "champion_detail").mkdir(parents=True)
    (base / "15.10.1" / "champion_detail").mkdir(parents=True)
    (base / ("16." + chr(0xB2)) / "champion_detail").mkdir(parents=True)
    (base / "zz_scratch" / "champion_detail").mkdir(parents=True)
    assert skins._latest_detail_dir(base) == base / "15.10.1" / "champion_detail"


# S144-T-646: with no usable local cell id, `None == None` matched the first
# myTeam row lacking a cellId, and a bool cell id matched cellId 1 - both
# returned ANOTHER player's skin.
@pytest.mark.parametrize("payload,cell", [
    ({"myTeam": [{"selectedSkinId": 77}]}, None),
    ({"localPlayerCellId": None, "myTeam": [{"cellId": None, "selectedSkinId": 77}]}, None),
    ({"localPlayerCellId": True, "myTeam": [{"cellId": 1, "selectedSkinId": 77}]}, None),
    ({"localPlayerCellId": 2, "myTeam": [{"cellId": True, "selectedSkinId": 77}]}, 1),
    ({"localPlayerCellId": "1", "myTeam": [{"cellId": 1, "selectedSkinId": 77}]}, None),
    ({"localPlayerCellId": 1, "myTeam": [{"cellId": 1.0, "selectedSkinId": 77}]}, None),
])
def test_selected_skin_requires_an_int_cell(payload, cell):
    assert skins.selected_skin_from_lcu(payload, cell_id=cell) is None


def test_selected_skin_cell_zero_and_explicit_override_still_work():
    sess = {"localPlayerCellId": 0, "myTeam": [
        {"cellId": 0, "selectedSkinId": 1001}, {"cellId": 3, "selectedSkinId": 3003}]}
    assert skins.selected_skin_from_lcu(sess) == 1001
    assert skins.selected_skin_from_lcu(sess, cell_id=3) == 3003
