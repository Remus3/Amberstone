"""Y-11 (external reference L2): ONE asset fileset for both reload signals.

Defect measured 2026-10-04 at origin/main d1d078aab: dashboard/_static.py
compute_asset_hash and dashboard/routes_state.py _asset_stamp_mtime each
hand-listed index.html + css/dashboard.css + css/overlay.css + js/main.js +
js/overlay_pulse.js and then walked css/panels, js/panels, js/lib. The three
stylesheets dashboard.css @imports from the css/ root (tokens.css :15,
themes.css :19, hextech.css :36) were in NEITHER list, so a design-token edit
never moved the ?v= hash, /api/ui-version, or /api/asset-stamp (ADR-008 key too
narrow). The fix derives the fileset from a glob of the served trees, shared by
both callers, so a hand list cannot go stale again.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from unittest import mock

from dashboard import _static
from dashboard import routes_state as rs
from dashboard._context import APP_DIR
from tests._repo_walk import tracked_relpaths

WEB = APP_DIR / "web"

# The test's OWN statement of what may be pruned. If asset_fileset() ever
# widens its prune set, this literal has to be edited deliberately too.
_EXPECTED_PRUNE = frozenset({"test", "node_modules", "__pycache__"})


def _fileset_rels(web_root: Path | None = None) -> list[str]:
    return [rel for rel, _p in _static.asset_fileset(web_root)]


def _expected_web_assets() -> set[str]:
    """Every .css / .js under web/ (git index first, disk walk as fallback),
    relative to web/, minus only the explicitly pruned directory segments."""
    tracked = tracked_relpaths()
    out: set[str] = set()
    if tracked is not None:
        for rel in tracked:
            if rel.startswith("web/") and rel.endswith((".css", ".js")):
                out.add(rel[len("web/"):])
    else:  # pragma: no cover - git absent
        for dirpath, _dirs, files in os.walk(WEB):
            for name in files:
                if name.endswith((".css", ".js")):
                    full = Path(dirpath) / name
                    out.add(full.relative_to(WEB).as_posix())
    return {r for r in out
            if not (set(r.split("/")[:-1]) & _EXPECTED_PRUNE)
            and not any(seg.startswith(".") for seg in r.split("/")[:-1])}


def test_prune_set_is_the_declared_one():
    assert frozenset(_static.ASSET_PRUNE_DIRS) == _EXPECTED_PRUNE


def test_every_web_css_and_js_is_in_the_fileset():
    expected = _expected_web_assets()
    # Non-empty anchor: an empty enumeration must not pass as "all covered".
    assert len(expected) >= 50, f"enumeration suspiciously small: {len(expected)}"
    assert "css/tokens.css" in expected and "js/main.js" in expected
    got = set(_fileset_rels())
    missing = sorted(expected - got)
    assert not missing, f"served assets missing from asset_fileset(): {missing}"
    assert "index.html" in got


def test_every_dashboard_css_import_is_in_the_fileset():
    """Derived from the pipeline's own source: every local @import in
    dashboard.css must be watched (the exact class of file Y-11 found)."""
    src = (WEB / "css" / "dashboard.css").read_text(encoding="utf-8")
    imports = re.findall(r"""@import\s+(?:url\()?['"](\./[^'"]+\.css)['"]""", src)
    assert len(imports) >= 3, imports
    got = set(_fileset_rels())
    resolved = [Path("css", imp[2:]).as_posix() for imp in imports]
    for name in ("css/tokens.css", "css/themes.css", "css/hextech.css"):
        assert name in resolved, f"{name} is no longer @imported - re-measure"
    missing = [r for r in resolved if r not in got]
    assert not missing, f"@imported stylesheets not watched: {missing}"


def test_fileset_is_sorted_and_prunes_explicitly(tmp_path):
    web = tmp_path / "web"
    for rel in ("index.html", "css/b.css", "css/a/deep.css", "js/z.js",
                "js/lib/m.js", "js/test/t.js", "js/node_modules/n.js",
                "css/.cache/h.css", "js/__pycache__/p.js", "js/notes.txt",
                "css/x.js", "legacy_index.html"):
        p = web / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    rels = _fileset_rels(web)
    assert rels == sorted(rels)
    assert rels == ["css/a/deep.css", "css/b.css", "index.html",
                    "js/lib/m.js", "js/z.js"]


def _bump(path: Path, delta: float = 200_000.0):
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + delta))
    return st


def test_touching_tokens_css_moves_both_hash_and_stamp():
    tokens = WEB / "css" / "tokens.css"
    assert tokens.is_file()
    _static._ASSET_HASH_CACHE.update({"hash": "", "mtime": 0.0})
    h0 = _static.compute_asset_hash()
    st = _bump(tokens)
    try:
        _static._ASSET_HASH_CACHE.update({"hash": "", "mtime": 0.0})
        h1 = _static.compute_asset_hash()
        stamp = rs._asset_stamp_mtime()
        assert h1 != h0, "tokens.css edit did not change the asset hash"
        assert stamp >= st.st_mtime + 200_000.0 - 1, (
            "tokens.css edit did not move /api/asset-stamp")
    finally:
        os.utime(tokens, (st.st_atime, st.st_mtime))
        _static._ASSET_HASH_CACHE.update({"hash": "", "mtime": 0.0})


def test_both_callers_share_one_fileset_function(tmp_path):
    """Swap the ONE function and both signals must follow it."""
    lone = tmp_path / "only.css"
    lone.write_text("x", encoding="utf-8")
    future = 4_000_000_000.0
    os.utime(lone, (future, future))
    calls: list[str] = []

    def fake(web_root=None):
        calls.append("x")
        return [("only.css", lone)]

    _static._ASSET_HASH_CACHE.update({"hash": "", "mtime": 0.0})
    with mock.patch.object(_static, "asset_fileset", side_effect=fake):
        h = _static.compute_asset_hash()
        stamp = rs._asset_stamp_mtime()
    _static._ASSET_HASH_CACHE.update({"hash": "", "mtime": 0.0})
    assert len(calls) == 2, f"expected both callers to use asset_fileset: {calls}"
    assert stamp == future
    import hashlib
    assert h == hashlib.sha1(f"only.css:{int(future)}".encode()).hexdigest()[:10]
