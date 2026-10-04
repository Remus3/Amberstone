"""RM-374: `ScraperBase.fetch` let an absolute URL bypass `base_url`, then
authorized it with the BASE site's robots.txt (RobotFileParser matches on
PATH only) and cached it under the base site's directory.

Decided contract (a stated change): an absolute URL is accepted only when its
scheme + host match `base_url`; a foreign-host URL raises `PermissionError` (the
robots-refusal type, which the orchestrator already degrades on) before
robots, network or cache are touched, and `_last_fetch.json` records
`foreign_host`. A same-host absolute URL keeps working.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.http.client import Response
from lib.scrapers import _base as scrapers_base
from lib.scrapers._base import ScraperBase

_GOOD = "<!DOCTYPE html><html><body>" + ("<div>item</div>" * 200) + "</body></html>"


class _Stub:
    def __init__(self):
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return Response(status=200, headers={}, body=_GOOD.encode(), url=url)


class _Fake(ScraperBase):
    site = "fakesite"
    base_url = "https://fake.example"


@pytest.fixture()
def scraper(tmp_path, monkeypatch):
    monkeypatch.setattr(scrapers_base, "SCRAPED_ROOT", Path(tmp_path))
    s = _Fake()
    s._client = _Stub()
    s._robots_loaded = True
    s._robots = None
    s.robots_seen = []
    real = s.can_fetch

    def spy(url, *a, **k):
        s.robots_seen.append(url)
        return real(url, *a, **k)

    s.can_fetch = spy
    return s


def test_foreign_absolute_url_is_refused(scraper, tmp_path):
    with pytest.raises(PermissionError):
        scraper.fetch("https://evil.example/x", cache_key="k")
    assert scraper._client.calls == []
    assert scraper.robots_seen == []
    assert not scraper.cache_path("k").exists()
    stamp = json.loads((tmp_path / "_last_fetch.json").read_text())["fakesite"]["k"]
    assert stamp["status"] == "foreign_host"


@pytest.mark.parametrize("url", ["http://fake.example/x", "https://fake.example.evil/x",
                                 "https://sub.fake.example/x"])
def test_scheme_or_host_mismatch_is_refused(scraper, url):
    with pytest.raises(PermissionError):
        scraper.fetch(url, cache_key="k")
    assert scraper._client.calls == []


def test_same_host_absolute_url_still_works(scraper):
    assert scraper.fetch("https://fake.example/lol/ahri", cache_key="a") == _GOOD
    assert scraper._client.calls == ["https://fake.example/lol/ahri"]


def test_relative_path_unchanged(scraper):
    assert scraper.fetch("lol/ahri", cache_key="b") == _GOOD
    assert scraper._client.calls == ["https://fake.example/lol/ahri"]
