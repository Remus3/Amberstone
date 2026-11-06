"""True-audit s144 cycle 158: dashboard/routes_champions.py (GET /api/champions).

The route serves the DDragon championId -> {name, slug} map the user-build
datalist reads (web/js/main.js `_ubChampionsList`). Findings pinned here:

- RM-1935: ONE failed read (file absent, mid-replace, bad JSON) was cached
  as `{}` for the whole process lifetime, so the map stayed empty until an RC
  restart even after the file came back.
- RM-1936: a DDragon patch refresh (new champion) never reached the map
  until a restart - the first read was cached forever, with no change check.
- RM-1937: junk ids were accepted - `True` read as champion 1, `266.7` was
  truncated to 266, zero / negative ids and whitespace-padded strings passed.
- RM-1938: a null / non-string / empty name was served as the name instead
  of falling back to the slug.
- RM-1939: a broad `except Exception` turned a programming error into a
  silent empty map; only the expected read / parse failures degrade now.
"""
from __future__ import annotations

import json
import os

import pytest

from dashboard import routes_champions as rc


class _FakeHandler:
    def __init__(self) -> None:
        self.sent: list[tuple[int, bytes, str]] = []

    def _send(self, status, body, ctype):
        self.sent.append((status, body, ctype))


def _get(app_dir) -> tuple[int, dict]:
    h = _FakeHandler()
    rc._serve_champions(h)
    assert len(h.sent) == 1
    status, body, ctype = h.sent[0]
    assert ctype == "application/json"
    return status, json.loads(body.decode("utf-8"))


def _write(app_dir, payload, *, bump: int = 0) -> None:
    p = app_dir / "data" / "meta" / "ddragon_champions.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    p.write_bytes(text.encode("utf-8"))
    if bump:
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + bump))


def _entry(key, name="N"):
    return {"key": key, "name": name}


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "APP_DIR", tmp_path)
    monkeypatch.setattr(rc, "_CACHE", None)
    return tmp_path


# ---- characterization (held before and after the rewrite) ------------------

def test_valid_map_is_served(app_dir):
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri"),
                              "KSante": _entry(897, "K'Sante")}})
    status, body = _get(app_dir)
    assert status == 200
    assert body == {"103": {"name": "Ahri", "slug": "Ahri"},
                    "897": {"name": "K'Sante", "slug": "KSante"}}


def test_missing_name_falls_back_to_slug(app_dir):
    _write(app_dir, {"data": {"Ahri": {"key": "103"}}})
    assert _get(app_dir)[1] == {"103": {"name": "Ahri", "slug": "Ahri"}}


def test_missing_file_serves_empty_map_at_200(app_dir):
    status, body = _get(app_dir)
    assert (status, body) == (200, {})


@pytest.mark.parametrize("payload", ["[]", "null", '"x"', "{bad json",
                                     '{"data": []}', '{"data": null}',
                                     '{"data": "x"}'])
def test_malformed_document_serves_empty_map(app_dir, payload):
    _write(app_dir, payload)
    assert _get(app_dir) == (200, {})


def test_non_dict_entry_is_skipped(app_dir):
    _write(app_dir, {"data": {"Bad": ["103"], "Nul": None,
                              "Ahri": _entry("103", "Ahri")}})
    assert _get(app_dir)[1] == {"103": {"name": "Ahri", "slug": "Ahri"}}


class _JsonSpy:
    """Stands in for the route module's `json` only (never the global one)."""

    def __init__(self, loads=None) -> None:
        self.calls = 0
        self._loads = loads or json.loads

    def loads(self, *a, **k):
        self.calls += 1
        return self._loads(*a, **k)

    dumps = staticmethod(json.dumps)


def test_repeat_read_is_served_from_cache(app_dir, monkeypatch):
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri")}})
    first = _get(app_dir)
    spy = _JsonSpy()
    monkeypatch.setattr(rc, "json", spy)
    assert _get(app_dir) == first
    assert spy.calls == 0


def test_non_ascii_name_is_escaped_on_the_wire(app_dir):
    _write(app_dir, {"data": {"Nunu": _entry("20", "Nunu & Willump"),
                              "Zed": _entry("238", "Z\u00e9d")}})
    h = _FakeHandler()
    rc._serve_champions(h)
    raw = h.sent[0][1]
    raw.decode("ascii")
    assert json.loads(raw)["238"]["name"] == "Z\u00e9d"


# ---- RM-1935: a failed read is never cached for the process lifetime -----

def test_missing_file_then_present_recovers_without_restart(app_dir):
    assert _get(app_dir)[1] == {}
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri")}})
    assert _get(app_dir)[1] == {"103": {"name": "Ahri", "slug": "Ahri"}}


def test_bad_json_then_fixed_recovers_without_restart(app_dir):
    _write(app_dir, "{half written")
    assert _get(app_dir)[1] == {}
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri")}}, bump=10**9)
    assert _get(app_dir)[1] == {"103": {"name": "Ahri", "slug": "Ahri"}}


def test_transient_failure_keeps_the_last_good_map(app_dir):
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri")}})
    good = _get(app_dir)[1]
    _write(app_dir, "{half written", bump=10**9)
    assert _get(app_dir)[1] == good
    (app_dir / "data" / "meta" / "ddragon_champions.json").unlink()
    assert _get(app_dir)[1] == good


# ---- RM-1936: a patch refresh reaches the map without a restart ----------

def test_patch_refresh_adds_the_new_champion(app_dir):
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri")}})
    assert set(_get(app_dir)[1]) == {"103"}
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri"),
                              "Mel": _entry("800", "Mel")}}, bump=10**9)
    assert set(_get(app_dir)[1]) == {"103", "800"}


# ---- RM-1937: junk ids are skipped, never coerced ------------------------

@pytest.mark.parametrize("key", [True, False, 266.7, 266.0, 0, -5, "0", "-5",
                                 " 266 ", "266\n", "+266", "1_0", "\u00b2",
                                 "\u0663", "1" * 5000, None, [], {}, ""])
def test_junk_key_is_skipped(app_dir, key):
    _write(app_dir, {"data": {"Junk": _entry(key, "Junk"),
                              "Ahri": _entry("103", "Ahri")}})
    assert _get(app_dir)[1] == {"103": {"name": "Ahri", "slug": "Ahri"}}


def test_leading_zero_string_key_normalises(app_dir):
    _write(app_dir, {"data": {"Ahri": _entry("0103", "Ahri")}})
    assert _get(app_dir)[1] == {"103": {"name": "Ahri", "slug": "Ahri"}}


# ---- RM-1938: a junk name falls back to the slug -------------------------

@pytest.mark.parametrize("name", [None, 123, "", "   ", {"x": 1}, ["Ahri"],
                                  True])
def test_junk_name_falls_back_to_slug(app_dir, name):
    _write(app_dir, {"data": {"Ahri": _entry("103", name)}})
    assert _get(app_dir)[1] == {"103": {"name": "Ahri", "slug": "Ahri"}}


# ---- RM-1939: an unexpected error surfaces instead of an empty map -------

def test_programming_error_is_not_swallowed(app_dir, monkeypatch):
    _write(app_dir, {"data": {"Ahri": _entry("103", "Ahri")}})

    def _boom(*_a, **_k):
        raise TypeError("planted bug")

    monkeypatch.setattr(rc, "json", _JsonSpy(loads=_boom))
    with pytest.raises(TypeError, match="planted bug"):
        rc._serve_champions(_FakeHandler())


def test_deeply_nested_document_degrades_not_raises(app_dir):
    _write(app_dir, "[" * 200000 + "]" * 200000)
    assert _get(app_dir) == (200, {})
