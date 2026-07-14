"""RED-first tests for the mtime-guarded parse cache on read_hud_settings.

core/league_settings.read_hud_settings is called on every dashboard build_state
(minimap_rect_payload -> read_hud_settings) while the browser polls /api/state
about once a second, and each call currently re-reads + re-parses game.cfg with
no cache. This module locks in a per-path parse cache keyed on the file's
(st_mtime_ns, st_size): the common file-unchanged call skips the read + INI scan,
but game.cfg is a MUTABLE operator file (MinimapScale can change mid-session), so
any edit bumps the mtime and forces a fresh parse. Output must stay identical to
the uncached reader in every case (same values, same None fail-soft).

ASCII only (repo hard rule).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core import league_settings
from core.league_settings import LeagueHudSettings, read_hud_settings

# Realistic game.cfg slice: [General] native size + [HUD] MinimapScale + Flip.
_SAMPLE = """
[General]
Width=2560
Height=1440
[HUD]
MinimapScale=1.6200
FlipMiniMap=0
"""

# Same file BYTE-LENGTH as _SAMPLE (1.0000 and 1.6200 are both 6 chars) so a
# size-only cache would wrongly return the stale scale - only the mtime saves us.
_SAMPLE_SCALE_1 = """
[General]
Width=2560
Height=1440
[HUD]
MinimapScale=1.0000
FlipMiniMap=0
"""


def _write(tmp_path: Path, text: str, name: str = "game.cfg") -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


@pytest.fixture(autouse=True)
def _clear_cache():
    # The parse cache is a process-global dict; isolate every test. Tolerant of
    # the pre-cache module so the RED run reaches the real assertion, not an
    # AttributeError in setup.
    def _clear():
        cache = getattr(league_settings, "_CACHE", None)
        if cache is not None:
            cache.clear()

    _clear()
    yield
    _clear()


def _spy_read_text(monkeypatch):
    """Wrap pathlib.Path.read_text with a call counter (original still runs)."""
    calls = {"n": 0}
    orig = Path.read_text

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    return calls


def test_equivalence_matches_fresh_parse(tmp_path):
    # Byte-identical output guard: the cached reader returns exactly the
    # documented parse of the sample (scale / flip / native w+h).
    p = _write(tmp_path, _SAMPLE)
    s = read_hud_settings(p)
    assert isinstance(s, LeagueHudSettings)
    assert s.minimap_scale == pytest.approx(1.62)
    assert s.flip_minimap is False
    assert s.native_w == 2560
    assert s.native_h == 1440


def test_cache_hit_skips_reread(tmp_path, monkeypatch):
    # RED on the original (no cache): the second call re-reads, so read_text
    # fires twice. With the mtime-guarded cache it fires exactly once.
    p = _write(tmp_path, _SAMPLE)
    calls = _spy_read_text(monkeypatch)
    first = read_hud_settings(p)
    second = read_hud_settings(p)
    assert first == second
    assert calls["n"] == 1


def test_cache_refreshes_on_mtime_bump(tmp_path):
    # Safety: game.cfg is mutable (operator can change MinimapScale mid-session).
    # A newer mtime must invalidate the cache even when the file size is equal.
    p = _write(tmp_path, _SAMPLE)
    s1 = read_hud_settings(p)
    assert s1.minimap_scale == pytest.approx(1.62)

    # Overwrite with scale 1.00 (SAME byte length) then bump mtime deterministically
    # so the test does not depend on wall-clock / filesystem timestamp resolution.
    Path(p).write_text(_SAMPLE_SCALE_1, encoding="utf-8")
    new_ns = os.stat(p).st_mtime_ns + 1_000_000_000
    os.utime(p, ns=(new_ns, new_ns))

    s2 = read_hud_settings(p)
    assert s2.minimap_scale == pytest.approx(1.0)


def test_missing_file_still_none(tmp_path):
    # Fail-soft preserved: a non-existent path returns None and is NOT cached.
    missing = str(tmp_path / "does_not_exist.cfg")
    assert read_hud_settings(missing) is None
    assert missing not in league_settings._CACHE


def test_no_hud_section_cached_none(tmp_path, monkeypatch):
    # A valid file with no [HUD] section returns None, and that None is a validly
    # cached result: the second call is a cache hit (exactly one read_text).
    p = _write(tmp_path, "[General]\nWidth=1920\nHeight=1080\n")
    calls = _spy_read_text(monkeypatch)
    assert read_hud_settings(p) is None
    assert read_hud_settings(p) is None
    assert calls["n"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
