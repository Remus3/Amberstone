"""Lane 8 true-audit (s144 cycle 240): lib/ddragon/fetch.py.

Five findings, each pinned red-first against the pre-fix module:

F1  `_read_cached` gated ENCODING only, so a cache file that parses but is not
    the requested document (`{"error": "blocked"}`, `"maintenance"`, a dict in
    runesReforged.json) was served forever - the read-side twin of RM-373,
    which only guarded the write. A wrong-shape cache now re-pulls.
F2  `_is_ddragon_payload` was not bundle-aware: a list body was accepted for
    champion.json and `{"data": {}}` for runesReforged.json, so the wrong
    document type was written over the cache. The check is per bundle now.
F3  A 200 body that is not JSON (a captive-portal or CDN HTML page), or a
    versions body that is not a list (`{"a": 1}`, `5`), raised
    JSONDecodeError / KeyError / TypeError - classes outside the module's
    stated RuntimeError contract (RM-352). They raise `DDragonBodyError`,
    which is BOTH RuntimeError and ValueError, so no existing catcher changes.
F4  The cache path ignored the locale: a `ko_KR` pull overwrote the en_US
    champion.json every RC consumer reads, and a `ko_KR` read served en_US.
    The locale was also an unvalidated URL segment. A non-default locale now
    caches under its own subdirectory and must look like `xx_YY`.

Considered and NOT changed: the constructor's eager `<ver>/` mkdir. It is a
pinned contract (tests/test_ddragon_version_path_guard.py
test_ddragon_happy_path_still_creates_the_cache_dir) and the version it
creates came from the CDN's own versions list or an explicit caller argument.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.ddragon.fetch as fetch_mod
from lib.http.client import Response

VER = "16.15.1"
CHAMP = {"type": "champion", "data": {"Ahri": {"id": "Ahri", "key": "103"}}}
ITEM = {"type": "item", "data": {"1001": {"name": "Boots"}}}
SUMM = {"type": "summoner", "data": {"SummonerFlash": {"key": "4"}}}
RUNES = [{"id": 8100, "key": "Domination", "slots": []}]
GOOD = {"champion": CHAMP, "item": ITEM, "summoner": SUMM, "runesReforged": RUNES}


class _Client:
    """Serve `GOOD[<bundle>]` (or a per-bundle override) and record URLs."""

    def __init__(self, bodies=None, status=200, versions=b'["16.15.1"]'):
        self.bodies = bodies or {}
        self.status = status
        self.versions = versions
        self.urls: list[str] = []

    def get(self, url, **_kw):
        self.urls.append(url)
        if url.endswith("/api/versions.json"):
            return Response(200, {}, self.versions, url)
        name = url.rsplit("/", 1)[-1][:-len(".json")]
        body = self.bodies.get(name)
        if body is None:
            body = json.dumps(GOOD[name]).encode("utf-8")
        return Response(self.status, {}, body, url)


@pytest.fixture
def root(monkeypatch, tmp_path) -> Path:
    r = tmp_path / "data" / "meta_build" / "ddragon"
    monkeypatch.setattr(fetch_mod, "CACHE_ROOT", r)
    return r


def _dd(monkeypatch, client, **kw):
    monkeypatch.setattr(fetch_mod, "get_client", lambda: client)
    return fetch_mod.DDragon(**kw)


def _seed(root: Path, name: str, payload) -> Path:
    p = root / VER / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(json.dumps(payload).encode("utf-8"))
    return p


_GETTERS = {
    "champion": "champions",
    "item": "items",
    "summoner": "summoner_spells",
    "runesReforged": "runes",
}


# ---------------------------------------------------------------- characterize


@pytest.mark.parametrize("name", sorted(_GETTERS))
def test_a_valid_cache_is_served_without_a_request(monkeypatch, root, name):
    _seed(root, name, GOOD[name])
    client = _Client()
    dd = _dd(monkeypatch, client, version=VER)
    assert getattr(dd, _GETTERS[name])() == GOOD[name]
    assert client.urls == []


def test_default_locale_url_and_cache_path_are_unchanged(monkeypatch, root):
    client = _Client()
    dd = _dd(monkeypatch, client, version=VER)
    dd.champions(refresh=True)
    assert client.urls == [
        f"{fetch_mod.DDRAGON_BASE}/cdn/{VER}/data/en_US/champion.json"]
    assert (root / VER / "champion.json").is_file()


# ---------------------------------------------------------------- F1


@pytest.mark.parametrize("name,poison", [
    ("champion", {"error": "blocked"}),
    ("champion", "maintenance"),
    ("champion", [{"id": 1}]),
    ("item", {"data": []}),
    ("summoner", {}),
    ("champion", {"type": "champion", "data": {}}),
    ("runesReforged", {"data": {}}),
    ("runesReforged", []),
    ("runesReforged", [1, 2]),
])
def test_a_wrong_shape_cache_is_re_pulled_and_repaired(monkeypatch, root, name, poison):
    p = _seed(root, name, poison)
    client = _Client()
    dd = _dd(monkeypatch, client, version=VER)
    assert getattr(dd, _GETTERS[name])() == GOOD[name]
    assert len(client.urls) == 1
    # The ALREADY-BAD file is repaired on disk, not just bypassed.
    assert json.loads(p.read_text(encoding="utf-8")) == GOOD[name]


# ---------------------------------------------------------------- F2


@pytest.mark.parametrize("name,body", [
    ("champion", b'[{"id": 1}]'),
    ("item", b'[{"name": "x"}]'),
    ("summoner", b'{"data": [1]}'),
    ("runesReforged", b'{"data": {}}'),
    ("runesReforged", b"[1, 2]"),
    ("runesReforged", b'[{"id": 1}, 7]'),
])
def test_a_wrong_document_type_is_not_written(monkeypatch, root, name, body):
    p = _seed(root, name, GOOD[name])
    before = p.read_bytes()
    dd = _dd(monkeypatch, _Client(bodies={name: body}), version=VER)
    with pytest.raises(RuntimeError):
        dd._pull(name)
    assert p.read_bytes() == before


# ---------------------------------------------------------------- F3


@pytest.mark.parametrize("body", [
    b"<html><body>captive portal</body></html>",
    b'{"a": 1}',
    b"5",
    b"null",
    b'"maintenance"',
    b"[]",
])
def test_a_bad_versions_body_raises_the_contract_class(body):
    class _C:
        def get(self, url, **_kw):
            return Response(200, {}, body, url)

    with pytest.raises(fetch_mod.DDragonBodyError) as info:
        fetch_mod.latest_version(_C())
    # Both historical contracts hold: RM-352 callers catch RuntimeError, the
    # RM-353 tests expect ValueError for a non-version body.
    assert isinstance(info.value, RuntimeError)
    assert isinstance(info.value, ValueError)


def test_an_unsafe_version_string_still_raises_value_error():
    class _C:
        def get(self, url, **_kw):
            return Response(200, {}, b'["../../evil"]', url)

    with pytest.raises(ValueError):
        fetch_mod.latest_version(_C())


def test_a_non_json_200_bundle_body_raises_runtime_error_and_keeps_cache(monkeypatch, root):
    p = _seed(root, "champion", CHAMP)
    before = p.read_bytes()
    dd = _dd(monkeypatch, _Client(bodies={"champion": b"<html>oops</html>"}), version=VER)
    with pytest.raises(RuntimeError):
        dd._pull("champion")
    assert p.read_bytes() == before


# ---------------------------------------------------------------- F4


def test_a_non_default_locale_never_touches_the_en_us_cache(monkeypatch, root):
    en = _seed(root, "champion", CHAMP)
    before = en.read_bytes()
    ko = {"type": "champion", "data": {"Ahri": {"id": "Ahri", "name": "ko"}}}
    client = _Client(bodies={"champion": json.dumps(ko).encode("utf-8")})
    dd = _dd(monkeypatch, client, version=VER, locale="ko_KR")
    # A ko_KR read must not serve the en_US file...
    assert dd.champions() == ko
    assert client.urls == [
        f"{fetch_mod.DDRAGON_BASE}/cdn/{VER}/data/ko_KR/champion.json"]
    # ...and its pull must not overwrite it.
    assert en.read_bytes() == before
    assert dd._cached("champion").parent == root / VER / "ko_KR"
    assert dd._cached("champion").is_file()


@pytest.mark.parametrize("locale", [
    "../x", "en_US/../..", "", "en-US", "EN_us", "en_US\n", 5, None,
])
def test_an_unsafe_locale_is_refused_before_any_request(monkeypatch, root, locale):
    client = _Client()
    with pytest.raises(ValueError):
        _dd(monkeypatch, client, version=VER, locale=locale)
    assert client.urls == []
    assert not root.exists()
