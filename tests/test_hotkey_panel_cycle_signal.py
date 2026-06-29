"""Win32 panel-cycle signal writer (overlay build-panel reachability fix).

The overlay build widget only shows in the `build` panelset, and the only
in-game switch to it (Alt+Shift+C) is on the Electron globalShortcut path that
is dead while League holds foreground focus. The fix routes a panel-cycle
through the SAME Win32 hotkey_listener + signal-file path that Ctrl+Shift+A
(ACTIVE toggle) uses, so rc-shell's startPanelCycleWatch can poll it.

This covers the Python signal writer: it stamps an advancing epoch to its own
signal file, atomically, and never raises.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# tools.hotkey_listener binds user32 via ctypes.WinDLL at import (Windows-only)
if sys.platform != "win32":
    pytest.skip("Windows-only Win32 hotkey listener", allow_module_level=True)

import tools.hotkey_listener as hk  # noqa: E402


def test_panel_cycle_signal_file_is_distinct_from_active_toggle():
    # The two signals must target different files or one press flips both.
    assert hk.PANEL_CYCLE_SIGNAL_FILE != hk.TOGGLE_SIGNAL_FILE
    assert hk.PANEL_CYCLE_SIGNAL_FILE.endswith("overlay_panel_cycle.txt")


def test_signal_writes_advancing_epoch(tmp_path, monkeypatch):
    target = tmp_path / "overlay_panel_cycle.txt"
    monkeypatch.setattr(hk, "PANEL_CYCLE_SIGNAL_FILE", str(target))

    hk.signal_overlay_panel_cycle()
    assert target.exists(), "signal file not written"
    first = float(target.read_text(encoding="ascii").strip())

    hk.signal_overlay_panel_cycle()
    second = float(target.read_text(encoding="ascii").strip())
    assert second >= first, "epoch must not go backwards on a second press"


def test_signal_never_raises_on_bad_path(monkeypatch):
    # Point at an unwritable directory path -> swallowed, no raise.
    monkeypatch.setattr(
        hk, "PANEL_CYCLE_SIGNAL_FILE", str(Path("Z:/nonexistent/overlay_panel_cycle.txt"))
    )
    hk.signal_overlay_panel_cycle()  # must not raise


def test_panel_cycle_hotkey_registered():
    # Ctrl+Shift+B (_VK_B) must be in the claimed hotkey set under its own slot
    # (B not C: Ctrl+Shift+C is commonly bound by other apps).
    ids = {hid for hid, _vk in hk._HOTKEYS}
    assert hk._SLOT_OVERLAY_PANEL_CYCLE in ids
    assert (hk._SLOT_OVERLAY_PANEL_CYCLE, hk._VK_B) in hk._HOTKEYS
    # Distinct slot id from the ACTIVE toggle.
    assert hk._SLOT_OVERLAY_PANEL_CYCLE != hk._SLOT_OVERLAY_TOGGLE


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
