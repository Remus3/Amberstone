"""RM-258 residual: the site scrapers' cache writer goes through core.polled_json.

``lib/scrapers/_base.py`` ``_atomic_write_text`` hand-rolled the atomic write:
a FIXED ``<dest>.tmp`` scratch name, ``Path.write_text`` and a bare
``os.replace``. Three defects followed, each pinned below:

  1. Text mode on Windows rewrites every ``\\n`` as ``\\r\\n``, so a cached page
     whose body already carried ``\\r\\n`` landed on disk as ``\\r\\r\\n`` and
     ``_last_fetch.json`` grew a CR per line. The cache must hold the body's
     bytes verbatim.
  2. The fixed scratch name is shared by every writer of the same target, and
     anything already sitting at ``<dest>.tmp`` (a leftover, a directory) broke
     the write. core.polled_json uses a per-writer scratch name.
  3. A bare ``os.replace`` raised on the first transient ``PermissionError``
     (WinError 5, a reader holding the destination open) and left the scratch
     file behind. core.polled_json retries with a bounded backoff and never
     leaves its scratch file.

The guard ``tests/test_atomic_write_guard_rm258_rm261.py`` carried this module
in ``_LIB_UNCLASSIFIED``; the conversion drops it from that baseline.

Every test here is platform-portable: the transient failure is a monkeypatched
``os.replace``, never a held Windows handle.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from lib.http.client import Response
from lib.scrapers import _base as scrapers_base
from lib.scrapers._base import ScraperBase

# Long enough to clear MIN_BODY_BYTES, no bot-wall marker, and CRLF line ends
# the way a Windows-authored page is served.
_CRLF_PAGE = "<!DOCTYPE html>\r\n<html><body>\r\n" + (
    "<div class=\"item\">Ludens Companion</div>\r\n" * 40) + "</body></html>\r\n"


class _Stub:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def get(self, url, timeout=None):
        return Response(status=200, headers={}, body=self._body, url=url)


class _Fake(ScraperBase):
    site = "fakesite"
    base_url = "https://fake.example"


@pytest.fixture()
def scraper(tmp_path, monkeypatch):
    monkeypatch.setattr(scrapers_base, "SCRAPED_ROOT", Path(tmp_path))
    s = _Fake()
    s._client = _Stub(_CRLF_PAGE.encode("utf-8"))
    s._robots_loaded = True
    s._robots = None
    return s


def test_text_writer_puts_the_exact_utf8_bytes_on_disk(tmp_path):
    target = tmp_path / "page.html"
    text = "line one\nline two\r\nnon-ascii \u00e9\n"
    scrapers_base._atomic_write_text(target, text)
    assert target.read_bytes() == text.encode("utf-8")


def test_json_writer_emits_no_carriage_return(tmp_path):
    target = tmp_path / "_last_fetch.json"
    payload = {"fakesite": {"k": {"ts": "t", "status": "ok"}}}
    scrapers_base._atomic_write_json(target, payload)
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw == json.dumps(payload, indent=2).encode("utf-8")


def test_fetch_caches_a_crlf_page_byte_for_byte(scraper):
    scraper.fetch("lol/ahri/build/", cache_key="ahri_sr")
    assert scraper.cache_path("ahri_sr").read_bytes() == _CRLF_PAGE.encode("utf-8")
    assert b"\r" not in scraper._last_fetch_path.read_bytes()


def test_a_leftover_at_the_old_fixed_scratch_name_does_not_block_the_write(tmp_path):
    """The old writer always used ``<dest>.tmp``; a directory squatting on that
    name made every write fail. A per-writer scratch name is unaffected."""
    target = tmp_path / "page.html"
    (tmp_path / "page.html.tmp").mkdir()
    scrapers_base._atomic_write_text(target, "fresh\n")
    assert target.read_bytes() == b"fresh\n"


def test_a_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    target = tmp_path / "page.html"
    target.write_bytes(b"old\n")
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    scrapers_base._atomic_write_text(target, "new\n")
    assert target.read_bytes() == b"new\n"
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["page.html"]


def test_an_exhausted_replace_leaves_the_target_and_no_scratch(tmp_path, monkeypatch):
    target = tmp_path / "page.html"
    target.write_bytes(b"old\n")

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        scrapers_base._atomic_write_text(target, "new\n")
    assert target.read_bytes() == b"old\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["page.html"]


def test_the_module_does_not_hand_roll_the_rename():
    """Source pin: the writer delegates instead of renaming itself."""
    src = Path(scrapers_base.__file__).read_text(encoding="utf-8")
    assert "os.replace(" not in src
    assert '".tmp"' not in src
    assert "from core.polled_json import atomic_write_text" in src
