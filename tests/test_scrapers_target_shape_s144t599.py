"""S144-T-599: the site scrapers check the champion / mode / role / lane shape
before a URL or a cache path is built from it.

Measured before the fix (lib/scrapers/site_d.py and site_b.py,
``fetch_champion``; Python 3.14 on Windows):

- the champion name only lost spaces and apostrophes, so ``#``, ``?``, ``/``,
  ``..`` and ``:`` reached the URL path and the cache key. ``"ahri#"`` fetched
  ``/lol/ahri`` (the fragment drops the rest of the path) and cached that page
  as ``ahri#_sr``; ``"x/../../admin"`` walked the same host's path tree;
- ``"c:zz"`` made the cache key ``c:zz_sr``, and ``Path(cache_dir) /
  "c:zz_sr.html"`` is a DRIVE-RELATIVE path on Windows, so the page was written
  at the root of another drive, outside the scrape cache;
- a role / lane value went into the query string unencoded (``"top&x=1"``
  added a parameter), and ``"c:q"`` made a cache name NTFS reads as an
  alternate data stream (OSError after the network fetch);
- None raised AttributeError, an unhashable mode TypeError, an embedded NUL
  ValueError after the fetch - none of which the one production caller
  (agents/agent2_backend/pipeline/orchestrator.py ``_scrape_one``) catches, so
  one bad roster entry aborted the whole mode refresh;
- an empty name fetched ``lol//build/`` and cached it as ``_sr``.

Contract now: the champion is a str, ASCII, and after the existing
normalisation (strip, lower, drop spaces and apostrophes) 1-32 of [a-z0-9];
the mode is a str key of MODE_PATH; a role / lane, when it is used (sr only),
is None / "" (no parameter) or 1-16 ASCII letters, passed through unchanged.
Anything else raises ``InvalidTarget`` (a ValueError AND a RuntimeError, so
the orchestrator's existing RuntimeError arm degrades that one source) before
the network, robots, the cache or the stamp file is touched, and the message
never echoes the caller's value. ``cache_path`` also maps ``:`` to ``_``.
Every input that was valid keeps its exact URL and cache key.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.http.client import Response
from lib.scrapers import _base as scrapers_base
from lib.scrapers._base import InvalidTarget
from lib.scrapers.site_b import SiteBScraper
from lib.scrapers.site_d import SiteDScraper

_GOOD = "<!DOCTYPE html><html><body>" + ("<div>item</div>" * 200) + "</body></html>"
_BASE = "https://fake.example"


class _Stub:
    def __init__(self):
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return Response(status=200, headers={}, body=_GOOD.encode(), url=url)


class _FakeD(SiteDScraper):
    base_url = _BASE


class _FakeB(SiteBScraper):
    base_url = _BASE


# (scraper class, name of the sr-only query keyword)
_SITES = [(_FakeD, "lane"), (_FakeB, "role")]
_SITE_IDS = ["site_d", "site_b"]


@pytest.fixture
def writes(tmp_path, monkeypatch):
    """Point the cache at tmp_path and RECORD page writes instead of doing
    them, so a red run (old code) can never write outside tmp_path - the
    old code wrote ``c:zz_sr.html`` to the root of another drive."""
    monkeypatch.setattr(scrapers_base, "SCRAPED_ROOT", Path(tmp_path))
    seen = []
    real = scrapers_base._atomic_write_text

    def record(path, text):
        # The stamp file lives in tmp_path and is written for real; every
        # other write is a cache page and is only recorded.
        if Path(path).name == "_last_fetch.json" and Path(path).parent == Path(tmp_path):
            real(path, text)
        else:
            seen.append(str(path))

    monkeypatch.setattr(scrapers_base, "_atomic_write_text", record)
    return seen


def _make(cls):
    s = cls()
    s._client = _Stub()
    s._robots_loaded = True
    s._robots = None
    return s


def _old_target(cls, champ, mode, extra):
    """Inlined copy of the pre-fix body: the URL path and cache key it built."""
    champ = champ.strip().lower().replace(" ", "").replace("'", "")
    path = cls.MODE_PATH[mode].format(champ=champ)
    kw = "lane" if issubclass(cls, SiteDScraper) else "role"
    val = extra.get(kw)
    if val and mode == "sr":
        path += f"?{kw}={val}"
    key = f"{champ}_{mode}" + (f"_{val}" if val and mode == "sr" else "")
    return f"{_BASE}/{path}", key


_VALID = [
    ("Ahri", "sr", {}),
    ("ahri", "aram", {}),
    ("Kai'Sa", "arena", {}),
    ("  Lee Sin ", "brawl", {}),
    ("MonkeyKing", "sr", {"q": "top"}),
    ("KSante", "sr", {"q": "Jungle"}),
    ("Belveth", "aram", {"q": "mid"}),
    ("Nunu", "sr", {"q": ""}),
    ("Nunu", "sr", {"q": None}),
    ("a" * 32, "sr", {}),
    ("Lux2", "sr", {"q": "a" * 16}),
]


@pytest.mark.parametrize("cls,kw", _SITES, ids=_SITE_IDS)
@pytest.mark.parametrize("champ,mode,extra", _VALID)
def test_valid_input_keeps_its_exact_url_and_cache_key(writes, cls, kw, champ, mode, extra):
    s = _make(cls)
    kwargs = {kw: extra["q"]} if "q" in extra else {}
    assert s.fetch_champion(champ, mode, **kwargs) == _GOOD
    url, key = _old_target(cls, champ, mode, kwargs)
    assert s._client.calls == [url]
    assert writes == [str(s.cache_path(key, ext="html"))]


_BAD_CHAMPS = [
    None, 7, 1.5, b"ahri", ["ahri"], "", "   ", "'", "ahri#", "ahri?x=1",
    "x/../../admin", "..", "a\\b", "c:zz", "a\x00b", "dr.mundo", "Dr. Mundo",
    "nunu&willump", "ah\tri", "ah-ri", "a" * 33, "\u212aayle", "kai\u2019sa",
    "ahr\u0131", "\uff41hri",
]


@pytest.mark.parametrize("cls,kw", _SITES, ids=_SITE_IDS)
@pytest.mark.parametrize("champ", _BAD_CHAMPS)
def test_bad_champion_is_refused_before_any_io(writes, tmp_path, cls, kw, champ):
    s = _make(cls)
    with pytest.raises(InvalidTarget) as ei:
        s.fetch_champion(champ, "sr")
    assert s._client.calls == []
    assert writes == []
    assert not (tmp_path / "_last_fetch.json").exists()
    if isinstance(champ, str) and champ.strip():
        assert champ.strip() not in str(ei.value)


_BAD_MODES = ["SR", "", "sr ", "sr\x00", None, 3, ["sr"], {"sr": 1}, ("sr",)]


@pytest.mark.parametrize("cls,kw", _SITES, ids=_SITE_IDS)
@pytest.mark.parametrize("mode", _BAD_MODES)
def test_bad_mode_is_refused_before_any_io(writes, tmp_path, cls, kw, mode):
    s = _make(cls)
    with pytest.raises(InvalidTarget, match="unsupported mode"):
        s.fetch_champion("ahri", mode)
    assert s._client.calls == []
    assert writes == []
    assert not (tmp_path / "_last_fetch.json").exists()


_BAD_TOKENS = ["top&x=1", "c:q", "top ", " top", "t#p", "to/p", "t%70",
               "\u212a", "a" * 17, "top\x00", 5, ["top"], True, b"top"]


@pytest.mark.parametrize("cls,kw", _SITES, ids=_SITE_IDS)
@pytest.mark.parametrize("token", _BAD_TOKENS)
def test_bad_role_or_lane_is_refused_before_any_io(writes, tmp_path, cls, kw, token):
    s = _make(cls)
    with pytest.raises(InvalidTarget) as ei:
        s.fetch_champion("ahri", "sr", **{kw: token})
    assert s._client.calls == []
    assert writes == []
    assert not (tmp_path / "_last_fetch.json").exists()
    if isinstance(token, str) and token.strip():
        assert token.strip() not in str(ei.value)


@pytest.mark.parametrize("cls,kw", _SITES, ids=_SITE_IDS)
def test_role_or_lane_is_still_ignored_outside_sr(writes, cls, kw):
    s = _make(cls)
    s.fetch_champion("ahri", "aram", **{kw: "top&x=1"})
    assert len(s._client.calls) == 1
    assert "?" not in s._client.calls[0]
    assert writes == [str(s.cache_path("ahri_aram", ext="html"))]


def test_invalid_target_is_both_a_value_error_and_a_runtime_error():
    # ValueError: what a bad argument is (and what the old unsupported-mode
    # refusal raised). RuntimeError: what _scrape_one already catches per
    # source, so one bad roster name degrades instead of aborting the mode.
    assert issubclass(InvalidTarget, ValueError)
    assert issubclass(InvalidTarget, RuntimeError)


@pytest.mark.parametrize("name", ["c:zz", "c:", "a:b:c", "ahri_sr_c:q"])
def test_cache_path_never_leaves_the_site_cache_dir(writes, name):
    s = _make(_FakeD)
    p = s.cache_path(name)
    assert p.parent == s._cache_dir
    assert ":" not in p.name


def test_cache_path_mapping_for_plain_names_is_unchanged(writes):
    s = _make(_FakeD)
    assert s.cache_path("ahri_sr") == s._cache_dir / "ahri_sr.html"
    assert s.cache_path("a/b\\c", ext="json") == s._cache_dir / "a_b_c.json"


def _orchestrator(monkeypatch):
    from agents.agent2_backend.pipeline import orchestrator as orch_mod

    orch = object.__new__(orch_mod.PipelineOrchestrator)
    orch._site_d = _make(_FakeD)
    orch._site_b = _make(_FakeB)
    orch._ddragon = None
    return orch_mod, orch


def test_orchestrator_degrades_one_bad_name_per_source(writes, monkeypatch):
    orch_mod, orch = _orchestrator(monkeypatch)
    out = orch._scrape_one("ahri#", "sr_draft")
    for site in ("site_d", "site_b"):
        assert out["sources"][site]["status"] == "error"
        assert "ahri#" not in out["sources"][site]["error"]
    assert orch._site_d._client.calls == []
    assert orch._site_b._client.calls == []
    assert writes == []


def test_orchestrator_cache_key_uses_the_shared_slug(monkeypatch):
    orch_mod, _ = _orchestrator(monkeypatch)
    assert orch_mod._cache_key("Kai'Sa", "sr") == "kaisa_sr"
    assert orch_mod._cache_key("  Lee Sin ", "aram") == "leesin_aram"
    with pytest.raises(InvalidTarget):
        orch_mod._cache_key("c:zz", "sr")


def test_orchestrator_reports_the_same_cache_file_the_scraper_wrote(writes, monkeypatch):
    orch_mod, orch = _orchestrator(monkeypatch)
    out = orch._scrape_one("Kai'Sa", "aram")
    assert out["sources"]["site_d"]["status"] == "ok"
    assert len(writes) == 2
    reported = Path(out["sources"]["site_d"]["cache"])
    assert reported.name == Path(writes[0]).name == "kaisa_aram.html"


def test_stamp_file_untouched_by_a_refusal_even_after_a_good_fetch(writes, tmp_path):
    s = _make(_FakeB)
    s.stamp_last_fetch("ahri_sr", status="ok")
    before = (tmp_path / "_last_fetch.json").read_bytes()
    with pytest.raises(InvalidTarget):
        s.fetch_champion("c:zz", "sr")
    assert (tmp_path / "_last_fetch.json").read_bytes() == before
    assert json.loads(before)["site_b"]["ahri_sr"]["status"] == "ok"
