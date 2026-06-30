"""Regression: /api/asset-stamp must track per-panel ESM modules.

The Electron overlay's in-page hot-reload poller (web/js/main.js _hotReloadInit)
reloads on an /api/asset-stamp mtime bump. The original stamp only stat'd
index.html / css/dashboard.css / js/main.js, so edits to a js/panels/* module
never bumped the stamp -> the overlay never auto-reloaded -> the operator saw
stale panel JS until a manual rc-shell relaunch (the electron_overlay_only trap).
The stamp must mirror the fileset compute_asset_hash already walks.
"""
import os

from dashboard._context import APP_DIR
from dashboard.routes_state import _asset_stamp_mtime


def test_asset_stamp_reflects_panel_module_mtime():
    panel = APP_DIR / "web" / "js" / "panels" / "minimap_zoi.js"
    assert panel.exists(), "fixture panel module missing"
    orig = os.path.getmtime(panel)
    future = orig + 100_000.0  # well past any other web/ asset
    try:
        os.utime(panel, (future, future))
        stamp = _asset_stamp_mtime()
        # The stamp must move to (at least) the freshly-bumped panel file; the
        # old three-file implementation would have ignored js/panels entirely.
        assert stamp >= future, (
            f"asset-stamp {stamp} did not track the panel module mtime {future}"
        )
    finally:
        os.utime(panel, (orig, orig))


def test_asset_stamp_is_positive_float():
    stamp = _asset_stamp_mtime()
    assert isinstance(stamp, float)
    assert stamp > 0.0
