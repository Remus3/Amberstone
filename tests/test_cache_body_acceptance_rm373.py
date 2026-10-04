"""RM-373: two more caches took a 200 body with no acceptance test.

(1) lib/icons/downloader.py `_download` wrote ANY 200 body over the icon -
    an HTML error page included - and returned True. It now requires image
    magic bytes (PNG, or JPEG) before the write; a non-image 200 leaves the
    existing file byte-unchanged and returns False. NOT the HTML marker list
    from lib/scrapers (the payload is binary).
(2) lib/ddragon/fetch.py `_pull` gated ENCODING (resp.json()) but not SHAPE,
    so a well-formed `{"error":"blocked"}` or `"maintenance"` was written over
    champion.json. It now requires the DDragon envelope - a dict carrying a
    dict `data` (champion / item / summoner) or a non-empty list
    (runesReforged) - and raises before the write otherwise.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.ddragon.fetch as fetch_mod
import lib.icons.downloader as dl
from lib.http.client import Response

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class _Client:
    def __init__(self, body, status=200):
        self.body, self.status, self.urls = body, status, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return Response(self.status, {}, self.body, url)


def _icons(monkeypatch, body):
    client = _Client(body)
    monkeypatch.setattr(dl, "get_client", lambda: client)
    monkeypatch.setattr(dl, "DDragon", lambda version=None: type(
        "D", (), {"version": "16.15.1"})())
    return dl.IconDownloader()


@pytest.mark.parametrize("body", [b"<html>error</html>", b"", b'{"error":"x"}'])
def test_non_image_200_does_not_overwrite_icon(monkeypatch, tmp_path, body):
    target = tmp_path / "Ahri.png"
    target.write_bytes(PNG)
    d = _icons(monkeypatch, body)
    assert d._download("https://ddragon/x.png", target, force=True) is False
    assert target.read_bytes() == PNG


@pytest.mark.parametrize("body", [PNG, JPG])
def test_real_image_still_writes(monkeypatch, tmp_path, body):
    target = tmp_path / "Ahri.png"
    d = _icons(monkeypatch, body)
    assert d._download("https://ddragon/x.png", target, force=True) is True
    assert target.read_bytes() == body


def _dd(monkeypatch, tmp_path, body):
    monkeypatch.setattr(fetch_mod, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(fetch_mod, "get_client", lambda: _Client(body))
    return fetch_mod.DDragon(version="16.15.1")


@pytest.mark.parametrize("body", [b'{"error":"blocked"}', b'"maintenance"',
                                  b'{"data": "x"}', b"[]", b"5"])
def test_shape_poisoned_json_does_not_overwrite_cache(monkeypatch, tmp_path, body):
    dd = _dd(monkeypatch, tmp_path, body)
    cached = dd._cached("champion")
    good = json.dumps({"data": {"Ahri": {}}}).encode()
    cached.write_bytes(good)
    with pytest.raises(RuntimeError):
        dd._pull("champion")
    assert cached.read_bytes() == good


def test_valid_envelopes_still_write(monkeypatch, tmp_path):
    dd = _dd(monkeypatch, tmp_path, json.dumps({"type": "champion",
                                                "data": {"Ahri": {}}}).encode())
    assert dd._pull("champion")["data"] == {"Ahri": {}}
    assert Path(dd._cached("champion")).is_file()
    dd2 = _dd(monkeypatch, tmp_path, json.dumps([{"id": 8100}]).encode())
    assert dd2._pull("runesReforged") == [{"id": 8100}]
