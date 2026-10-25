"""Win32 overlay content ON/OFF signal writer (S134 overlay toggle icon).

The operator asked for an in-game icon that turns the visual overlay on and
off. Its keyboard twin rides the SAME Win32 hotkey_listener + signal-file path
that Ctrl+Shift+A (ACTIVE toggle) and Ctrl+Shift+B (panel cycle) use, because
Electron globalShortcut does not deliver while League holds foreground focus.
rc-shell's startVisibleToggleWatch polls the file (rc-shell/src/main.js); the
rc-shell suite (rc-shell/test/overlay_toggle.test.js) pins the file name on
the JS side.

This covers the Python half: Ctrl+Shift+O is claimed under its own slot, the
decoder fires it, and the writer stamps an advancing epoch to its own file,
atomically, without ever raising.
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


def test_visible_signal_file_is_its_own_file():
    # Sharing a file with another signal would make one press fire both.
    assert hk.VISIBLE_TOGGLE_SIGNAL_FILE.endswith("overlay_visible_toggle.txt")
    others = {hk.TOGGLE_SIGNAL_FILE, hk.PANEL_CYCLE_SIGNAL_FILE}
    assert hk.VISIBLE_TOGGLE_SIGNAL_FILE not in others


def test_ctrl_shift_o_is_claimed_under_its_own_slot():
    assert hk._VK_O == 0x4F
    assert (hk._SLOT_OVERLAY_VISIBLE, hk._VK_O) in hk._HOTKEYS
    slots = [s for s, _ in hk._HOTKEYS]
    assert slots.count(hk._SLOT_OVERLAY_VISIBLE) == 1
    assert hk._SLOT_OVERLAY_VISIBLE not in (
        hk._SLOT_OVERLAY_TOGGLE,
        hk._SLOT_OVERLAY_PANEL_CYCLE,
        hk._SLOT_MOMENT_MARK,
    )


def test_decoder_fires_the_visible_slot_only_with_both_modifiers():
    d = hk.HotkeyDecoder()
    assert d.on_keydown(hk._VK_O, ctrl=True, shift=True) == hk._SLOT_OVERLAY_VISIBLE
    for ctrl, shift in ((False, False), (True, False), (False, True)):
        assert hk.HotkeyDecoder().on_keydown(hk._VK_O, ctrl=ctrl, shift=shift) is None


def test_dispatch_routes_the_visible_slot_to_its_writer(monkeypatch):
    calls = []
    monkeypatch.setattr(hk, "signal_overlay_visible_toggle", lambda: calls.append("visible"))
    monkeypatch.setattr(hk, "signal_overlay_active_toggle", lambda: calls.append("active"))
    hk._dispatch_one(None, hk._SLOT_OVERLAY_VISIBLE)
    assert calls == ["visible"]


def test_signal_writes_advancing_epoch(tmp_path, monkeypatch):
    target = tmp_path / "overlay_visible_toggle.txt"
    monkeypatch.setattr(hk, "VISIBLE_TOGGLE_SIGNAL_FILE", str(target))

    hk.signal_overlay_visible_toggle()
    assert target.exists(), "signal file not written"
    first = float(target.read_text(encoding="ascii").strip())

    hk.signal_overlay_visible_toggle()
    second = float(target.read_text(encoding="ascii").strip())
    assert second >= first, "epoch must not go backwards on a second press"


def test_signal_never_raises_on_bad_path(monkeypatch):
    monkeypatch.setattr(
        hk,
        "VISIBLE_TOGGLE_SIGNAL_FILE",
        str(Path("Z:/nonexistent/overlay_visible_toggle.txt")),
    )
    hk.signal_overlay_visible_toggle()  # must not raise
