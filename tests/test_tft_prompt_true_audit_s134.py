"""True-audit (s134, lane true-audit cycle 3): tft/tft_prompt.py hardening.

Measured before the fix (lane/true-audit on local main 5004e7986):
  F1 tft/tft_prompt.py:210 `for b in row.get("breakpoints") or []` iterates a
     scalar: ONE CommunityDragon trait row carrying `"breakpoints": 4` raised
     TypeError out of set_profile, and build_system_prompt (:469-475) dropped
     the WHOLE set block - every trait, unit and mechanic - for every call.
  F2 the degraded profile (:473) is built for tft_set.FALLBACK_SET (17) when
     no set_number is passed, although resolve_set had already resolved the
     live set: a Set 18 game was told "SET 17 - no game data ingested".
  F3 a build failure is never cached (:319-357), so every coach call re-read
     both files and logged the same warning again; the three gates
     (set_has_gods / meta_verified / pick_label, :487-508) swallowed the same
     failure with no log at all.
  F4 the cache key (:318) holds the files' mtimes, so a transient read
     failure of an EXISTING file (tft_set.load_json_file returns {} on any
     OSError) was cached as "no data" until the file changed again.
  F5 the cache key holds mtime_ns only: a rewrite that keeps the mtime (a
     copy2-style restore) served the previous file's profile.

Names used, cited:
  tft/tft_set.py:47 FALLBACK_SET, :63 meta_dir, :145 resolve_set, :180
      load_json_file, :197 comp_state (patched off, as in the RM-845 tests)
  tft/tft_prompt.py set_profile, build_system_prompt, set_has_gods,
      meta_verified, pick_label, _traits, _CACHE, logger "rc.tft.prompt"
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from tft import tft_prompt, tft_set


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """No env pin, no noted live set, no live comp_state.json, empty cache."""
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    monkeypatch.setattr(tft_set, "comp_state", lambda root=None: {})
    tft_set.clear_live_set()
    tft_prompt._CACHE.clear()
    monkeypatch.setattr(tft_prompt, "_WARNED", [None], raising=False)
    yield
    tft_set.clear_live_set()
    tft_prompt._CACHE.clear()


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=1).encode("utf-8") + b"\n")


def _cd_path(root: Path, n: int = 18) -> Path:
    return root / "data" / "meta" / f"tft_set{n}_cdragon.json"


def _cd(**over) -> dict:
    doc = {
        "_set": 18, "_content_version": "16.21.1", "_fetched": "2026-10-25",
        "traits": [{"name": "Beta", "breakpoints": [2, 4]}],
        "unit_costs": {"Ahri": 4, "Teemo": 2},
        "augments": [],
    }
    doc.update(over)
    return doc


def _prompt_warnings(caplog) -> list:
    return [r for r in caplog.records
            if r.name == "rc.tft.prompt" and r.levelno >= logging.WARNING]


# -- F1: one malformed row must not erase the set block -----------------------

def _assert_row_kept(tmp_path, bad) -> None:
    _write(_cd_path(tmp_path), _cd(traits=[
        {"name": "Alpha", "breakpoints": bad},
        {"name": "Beta", "breakpoints": [2, 4]},
    ]))
    p = tft_prompt.build_system_prompt(18, root=tmp_path)
    assert "no game data ingested" not in p
    assert "Beta 2/4" in p
    assert "Alpha" in p  # the row survives, without breakpoints
    assert "Ahri" in p and "Teemo" in p


@pytest.mark.parametrize("bad", [4, 2.5, True])
def test_scalar_breakpoints_row_keeps_the_rest_of_the_set_block(tmp_path, bad):
    """Regression (red on main): a scalar raised TypeError out of set_profile."""
    _assert_row_kept(tmp_path, bad)


@pytest.mark.parametrize("bad", ["2/4/6", {"a": 1}])
def test_iterable_non_list_breakpoints_row_is_kept(tmp_path, bad):
    """Characterization (green on main too): iterables never raised; pinned so
    the list-only guard keeps them working."""
    _assert_row_kept(tmp_path, bad)


def test_tuple_breakpoints_are_still_read(tmp_path):
    """Characterization: an in-memory tuple row reads like a JSON list."""
    assert tft_prompt._traits({"traits": [{"name": "Delta", "breakpoints": (3, 5)}]}, {}) \
        == (("Delta", "3/5"),)


# -- F2: the degraded block names the RESOLVED set -----------------------------

def _boom(*_a, **_k):
    raise RuntimeError("synthetic profile failure")


def test_degraded_prompt_names_the_resolved_set_not_the_fallback(tmp_path, monkeypatch):
    assert tft_set.FALLBACK_SET != 18  # else this test proves nothing
    _write(_cd_path(tmp_path), _cd())
    assert tft_set.resolve_set(root=tmp_path) == 18
    monkeypatch.setattr(tft_prompt, "_traits", _boom)
    p = tft_prompt.build_system_prompt(root=tmp_path)
    assert "SET 18 - no game data ingested" in p
    assert f"SET {tft_set.FALLBACK_SET}" not in p
    assert "tft_set18_meta.json" in p
    assert f"tft_set{tft_set.FALLBACK_SET}_meta.json" not in p


def test_degraded_prompt_does_not_call_an_existing_meta_absent(tmp_path, monkeypatch):
    """Regression (red on main, which said "no <meta> on file" while the meta
    file sat on disk): a degraded build with a meta present says UNVERIFIED."""
    _write(_cd_path(tmp_path), _cd())
    _write(tmp_path / "data" / "meta" / "tft_set18_meta.json",
           {"_set": 18, "_note": "SKELETON - UNVERIFIED.", "comps": {}})
    monkeypatch.setattr(tft_prompt, "_traits", _boom)
    p = tft_prompt.build_system_prompt(18, root=tmp_path)
    assert "META: tft_set18_meta.json is UNVERIFIED" in p
    assert "no tft_set18_meta.json on file" not in p


# -- F3: one failure is logged once per data version, gates included ----------

def test_profile_failure_is_logged_once_and_not_rebuilt_per_call(tmp_path, monkeypatch, caplog):
    _write(_cd_path(tmp_path), _cd())
    calls = []

    def _counting_boom(*a, **k):
        calls.append(1)
        raise RuntimeError("synthetic profile failure")

    monkeypatch.setattr(tft_prompt, "_traits", _counting_boom)
    caplog.set_level(logging.DEBUG, logger="rc.tft.prompt")
    for _ in range(3):
        tft_prompt.build_system_prompt(18, root=tmp_path)
    assert tft_prompt.set_has_gods(18, root=tmp_path) is False
    assert tft_prompt.meta_verified(18, root=tmp_path) is False
    assert tft_prompt.pick_label(18, root=tmp_path) == tft_prompt.PICK_GENERIC
    assert len(calls) == 1
    warns = _prompt_warnings(caplog)
    assert len(warns) == 1
    assert "synthetic profile failure" in warns[0].getMessage()


def test_uncacheable_failure_is_still_logged_once(tmp_path, monkeypatch, caplog):
    """Regression (red on main): an existing meta that is not a JSON object
    loads as {} and is never cached; a failing build there still warns once
    per data version, not once per coach call."""
    _write(_cd_path(tmp_path), _cd())
    _write(tmp_path / "data" / "meta" / "tft_set18_meta.json", [])
    monkeypatch.setattr(tft_prompt, "_traits", _boom)
    caplog.set_level(logging.DEBUG, logger="rc.tft.prompt")
    for _ in range(3):
        tft_prompt.build_system_prompt(18, root=tmp_path)
    assert tft_prompt._CACHE == {}
    assert len(_prompt_warnings(caplog)) == 1


def test_a_changed_file_retries_a_failed_profile(tmp_path, monkeypatch):
    """Characterization (green on main, which never cached a failure): the
    F3 failure cache must end when the data file changes."""
    path = _cd_path(tmp_path)
    _write(path, _cd())
    real = tft_prompt._traits
    monkeypatch.setattr(tft_prompt, "_traits", _boom)
    assert "no game data ingested" in tft_prompt.build_system_prompt(18, root=tmp_path)
    monkeypatch.setattr(tft_prompt, "_traits", real)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert "Beta 2/4" in tft_prompt.build_system_prompt(18, root=tmp_path)


# -- F4: a transient read failure of an existing file is not cached -----------

def test_transient_unreadable_existing_file_is_not_cached(tmp_path, monkeypatch):
    _write(_cd_path(tmp_path), _cd())
    real = tft_set.load_json_file
    state = {"fail": True}

    def _flaky(path):
        if state["fail"] and Path(path).name.endswith("_cdragon.json"):
            return {}  # what load_json_file returns on a sharing violation
        return real(path)

    monkeypatch.setattr(tft_set, "load_json_file", _flaky)
    first = tft_prompt.build_system_prompt(18, root=tmp_path)
    assert "Beta 2/4" not in first
    state["fail"] = False
    assert "Beta 2/4" in tft_prompt.build_system_prompt(18, root=tmp_path)


def test_absent_file_profile_is_still_cached(tmp_path, monkeypatch):
    """Characterization (green on main too): the F4 guard must not stop an
    ABSENT file's profile from being cached - that would rebuild for nothing."""
    _write(_cd_path(tmp_path), _cd())  # the meta file stays absent
    tft_prompt.set_profile(18, root=tmp_path)
    loads = []
    real = tft_set.load_json_file
    monkeypatch.setattr(tft_set, "load_json_file",
                        lambda path: loads.append(path) or real(path))
    tft_prompt.set_profile(18, root=tmp_path)
    assert loads == []


# -- F5: a same-mtime rewrite is seen ----------------------------------------

def test_same_mtime_rewrite_of_a_different_size_is_seen(tmp_path):
    path = _cd_path(tmp_path)
    _write(path, _cd())
    st = path.stat()
    assert "Beta 2/4" in tft_prompt.build_system_prompt(18, root=tmp_path)
    _write(path, _cd(traits=[{"name": "Gammaray", "breakpoints": [3, 6, 9]}]))
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert path.stat().st_mtime_ns == st.st_mtime_ns
    assert path.stat().st_size != st.st_size
    p = tft_prompt.build_system_prompt(18, root=tmp_path)
    assert "Gammaray 3/6/9" in p and "Beta" not in p


# -- characterization: the healthy path is unchanged ---------------------------

def test_healthy_profile_is_cached_on_the_data_version(tmp_path, monkeypatch):
    """Characterization (green on main too): a healthy profile is served from
    the cache without touching the files again."""
    _write(_cd_path(tmp_path), _cd())
    a = tft_prompt.set_profile(18, root=tmp_path)
    monkeypatch.setattr(tft_set, "load_json_file", _boom)
    assert tft_prompt.set_profile(18, root=tmp_path) is a
    assert a.source == "cdragon" and a.traits == (("Beta", "2/4"),)
    assert a.units_by_cost == ((2, ("Teemo",)), (4, ("Ahri",)))
