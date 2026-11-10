"""s144 true-audit cycle 175: dashboard/_static.py.

The module behind the ADR-008 reload signal (the `?v=` rewrite in index.html
and /api/ui-version both go through compute_asset_hash), the /icons/* path
resolver and three cached static responses. Findings, each measured on the
pre-fix module before any edit:

F1  compute_asset_hash keyed every file on int(st_mtime). A second save inside
    the same wall-clock second as the previous hash left the hash unchanged,
    so the browser and the overlay never reloaded that edit (it stayed stale
    until some other asset changed). A content change that kept the mtime
    (same second, different size) was invisible the same way. Now keyed on
    st_mtime_ns plus st_size.
F2  the 2 s hash cache was aged on time.time(). A backward wall-clock step
    (NTP correction, manual clock set) made `now - cached` negative, which is
    "< 2.0", so the cached hash was served for as long as the step lasted (an
    hour back = an hour with no reload signal). Now aged on time.monotonic()
    and a negative age is treated as expired.
F3  inject_asset_hash rewrote `?v=` with a `[^"']+` tail, so it swallowed
    every later query parameter (`a.css?v=1&theme=dark` became `a.css?v=H`),
    contradicting its own docstring ("unrelated query strings aren't
    disturbed"). Latent: web/index.html carries no such parameter today.
F4  resolve_safe_icon caught `Exception` around Path.resolve, so a programming
    error there became a silent 404. Narrowed to OSError / ValueError /
    RuntimeError (the failures resolve really raises: bad name, symlink
    loop); anything else now reaches the route's logged 500.
F5  legacy_index_html / manifest_bytes / icon_svg_bytes cached their bytes for
    the life of the process, so an edit to web/legacy_index.html (the live
    fallback UI), web/manifest.json or web/icon.svg was never served until RC
    restarted. They now re-read when the file's (mtime_ns, size) changes.

Characterization tests (green before and after, labelled `char`) pin the
behaviour the rewrite must keep: the traversal refusals, the 2 s cache inside
its window, and FileNotFoundError on a missing static file.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from dashboard import _static


class _Clock:
    """Stands in for the `time` module inside dashboard._static: both the
    wall clock and the monotonic clock read the same settable value, so a
    test can step time backwards whichever clock the module uses."""

    def __init__(self, t: float) -> None:
        self.t = t

    def time(self) -> float:
        return self.t

    def monotonic(self) -> float:
        return self.t


def _reset_cache() -> None:
    _static._ASSET_HASH_CACHE.update({"hash": "", "mtime": 0.0, "at": 0.0})


def _set_ns(p: Path, ns: int) -> None:
    os.utime(p, ns=(ns, ns))


@pytest.fixture
def one_asset(tmp_path):
    f = tmp_path / "a.js"
    f.write_bytes(b"x")
    _set_ns(f, 10_100_000_000)
    _reset_cache()
    with mock.patch.object(_static, "asset_fileset", return_value=[("a.js", f)]):
        yield f
    _reset_cache()


# -- F1: the hash must see a sub-second edit --------------------------------

def test_f1_edit_inside_the_same_second_moves_the_hash(one_asset):
    h0 = _static.compute_asset_hash()
    one_asset.write_bytes(b"xyz changed")
    _set_ns(one_asset, 10_900_000_000)  # same whole second as before
    _reset_cache()
    h1 = _static.compute_asset_hash()
    assert h1 != h0, "a second save in the same second never reloads the page"


def test_f1_same_mtime_different_size_moves_the_hash(one_asset):
    h0 = _static.compute_asset_hash()
    one_asset.write_bytes(b"a much longer body than before")
    _set_ns(one_asset, 10_100_000_000)  # mtime restored exactly
    _reset_cache()
    h1 = _static.compute_asset_hash()
    assert h1 != h0, "a content change that kept the mtime is invisible"


def test_f1_identical_tree_keeps_the_hash_char(one_asset):
    h0 = _static.compute_asset_hash()
    _reset_cache()
    assert _static.compute_asset_hash() == h0


def test_f1_a_vanished_file_still_hashes_char(one_asset):
    h0 = _static.compute_asset_hash()
    one_asset.unlink()
    _reset_cache()
    h1 = _static.compute_asset_hash()
    assert isinstance(h1, str) and len(h1) == 10
    assert h1 != h0


# -- F2: the 2 s cache must not freeze on a backward clock step -------------

def test_f2_backward_clock_step_does_not_freeze_the_hash(one_asset):
    clock = _Clock(100_000.0)
    with mock.patch.object(_static, "time", clock):
        h0 = _static.compute_asset_hash()
        one_asset.write_bytes(b"edited after the clock moved back")
        _set_ns(one_asset, 20_000_000_000)
        clock.t = 100_000.0 - 3600.0  # clock stepped back one hour
        h1 = _static.compute_asset_hash()
    assert h1 != h0, "a backward clock step served the cached hash"


def test_f2_cache_holds_inside_its_window_char(one_asset):
    clock = _Clock(100_000.0)
    with mock.patch.object(_static, "time", clock):
        h0 = _static.compute_asset_hash()
        one_asset.write_bytes(b"edited inside the window")
        _set_ns(one_asset, 20_000_000_000)
        clock.t = 100_001.0
        assert _static.compute_asset_hash() == h0
        clock.t = 100_002.5
        assert _static.compute_asset_hash() != h0


# -- F3: the ?v= rewrite keeps the other query parameters -------------------

def test_f3_inject_keeps_a_following_query_parameter():
    with mock.patch.object(_static, "compute_asset_hash", return_value="HHHH"):
        out = _static.inject_asset_hash(
            b'<link href="/css/a.css?v=1&theme=dark" />'
            b"<script src='/js/m.js?v=2#frag'></script>")
    assert out == (b'<link href="/css/a.css?v=HHHH&theme=dark" />'
                   b"<script src='/js/m.js?v=HHHH#frag'></script>")


def test_f3_inject_rewrites_every_css_and_js_ref_only_char():
    src = (b'<link href="/css/dashboard.css?v=2026051125" />'
           b'<link href="/css/overlay.css?v=2026060901" />'
           b'<script src="/js/main.js?v=2026051211"></script>'
           b'<a href="/data/x.json?v=7">x</a>')
    with mock.patch.object(_static, "compute_asset_hash", return_value="abc123"):
        out = _static.inject_asset_hash(src).decode("ascii")
    assert out.count("?v=abc123") == 3
    assert "x.json?v=7" in out


# -- F4: resolve_safe_icon catches only what resolve really raises ----------

def test_f4_unexpected_error_in_resolve_is_not_swallowed(tmp_path):
    (tmp_path / "ok.png").write_bytes(b"p")
    with mock.patch.object(Path, "resolve", side_effect=TypeError("bug")):
        with pytest.raises(TypeError):
            _static.resolve_safe_icon(tmp_path, "ok.png")


@pytest.mark.parametrize("exc", [OSError("io"), ValueError("bad"),
                                 RuntimeError("symlink loop")])
def test_f4_expected_resolve_failures_still_refuse_char(tmp_path, exc):
    (tmp_path / "ok.png").write_bytes(b"p")
    with mock.patch.object(Path, "resolve", side_effect=exc):
        assert _static.resolve_safe_icon(tmp_path, "ok.png") is None


def test_f4_real_icon_resolves_char(tmp_path):
    (tmp_path / "ok.png").write_bytes(b"p")
    got = _static.resolve_safe_icon(tmp_path, "ok.png")
    assert got == (tmp_path / "ok.png").resolve()


@pytest.mark.parametrize("rel", [
    "", "ok.PNG", "ok.png.txt", "../ok.png", "..\\ok.png", "sub/ok.png",
    "sub\\ok.png", "\x00ok.png", "C:ok.png", "NUL.png", "CON.png",
    "ok.png:x.png", "missing.png", "dir.png",
])
def test_f4_refusals_char(tmp_path, rel):
    root = tmp_path / "icons"
    root.mkdir()
    (root / "ok.png").write_bytes(b"p")
    (root / "dir.png").mkdir()
    (tmp_path / "ok.png").write_bytes(b"outside")
    assert _static.resolve_safe_icon(root, rel) is None


def test_f4_symlink_out_of_root_refused_char(tmp_path):
    root = tmp_path / "icons"
    root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"s")
    try:
        (root / "link.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this host")
    assert _static.resolve_safe_icon(root, "link.png") is None


# -- F5: cached static responses follow an edit -----------------------------

_CACHED = [
    ("legacy_index_html", "_LEGACY_INDEX_PATH", "_LEGACY_INDEX_CACHE"),
    ("manifest_bytes", "_MANIFEST_PATH", "_MANIFEST_CACHE"),
    ("icon_svg_bytes", "_ICON_SVG_PATH", "_ICON_SVG_CACHE"),
]


@pytest.mark.parametrize(("fn", "path_attr", "cache_attr"), _CACHED)
def test_f5_cached_static_file_follows_an_edit(tmp_path, monkeypatch, fn,
                                               path_attr, cache_attr):
    target = tmp_path / "static.bin"
    target.write_bytes(b"first")
    monkeypatch.setattr(_static, path_attr, target)
    monkeypatch.setattr(_static, cache_attr, None, raising=False)
    reader = getattr(_static, fn)
    assert reader() == b"first"
    target.write_bytes(b"second, edited while RC runs")
    assert reader() == b"second, edited while RC runs"


@pytest.mark.parametrize(("fn", "path_attr", "cache_attr"), _CACHED)
def test_f5_unchanged_file_is_served_from_cache_char(tmp_path, monkeypatch,
                                                     fn, path_attr, cache_attr):
    target = tmp_path / "static.bin"
    target.write_bytes(b"body")
    monkeypatch.setattr(_static, path_attr, target)
    monkeypatch.setattr(_static, cache_attr, None, raising=False)
    reader = getattr(_static, fn)
    first = reader()
    with mock.patch.object(Path, "read_bytes",
                           side_effect=AssertionError("re-read")):
        assert reader() == first


@pytest.mark.parametrize(("fn", "path_attr", "cache_attr"), _CACHED)
def test_f5_missing_file_raises_char(tmp_path, monkeypatch, fn, path_attr,
                                     cache_attr):
    monkeypatch.setattr(_static, path_attr, tmp_path / "absent.bin")
    monkeypatch.setattr(_static, cache_attr, None, raising=False)
    with pytest.raises(FileNotFoundError):
        getattr(_static, fn)()
