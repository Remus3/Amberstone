"""Low-level keyboard-hook decoder (in-game hotkey delivery fix).

RegisterHotKey global accelerators are swallowed while League/Overlay Platform M holds
foreground focus, so Ctrl+Shift+A/B never reached the listener in-game. The fix
switches tools/hotkey_listener.py to a WH_KEYBOARD_LL low-level hook, which sees
key events at the OS input queue before the focused app consumes them.

The Win32 plumbing (SetWindowsHookExW / the message pump) is not unit-testable
headlessly, so the firing logic is factored into a pure HotkeyDecoder: given a
keydown vkCode plus the live Ctrl/Shift state, decide which slot (if any) fires.
These cases pin that decode + the press-edge debounce (one fire per physical
press, the NOREPEAT equivalent the old MOD_NOREPEAT flag gave for free).
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


def _fresh():
    return hk.HotkeyDecoder()


def test_ctrl_shift_trigger_keys_fire_their_slots():
    # Ctrl+Shift+1/2 -> coach slots 1/2; +A -> toggle (3); +B -> cycle (4).
    assert _fresh().on_keydown(hk._VK_1, ctrl=True, shift=True) == 1
    assert _fresh().on_keydown(hk._VK_2, ctrl=True, shift=True) == 2
    assert _fresh().on_keydown(hk._VK_A, ctrl=True, shift=True) == hk._SLOT_OVERLAY_TOGGLE
    assert _fresh().on_keydown(hk._VK_B, ctrl=True, shift=True) == hk._SLOT_OVERLAY_PANEL_CYCLE


def test_missing_either_modifier_does_not_fire():
    assert _fresh().on_keydown(hk._VK_B, ctrl=False, shift=False) is None
    assert _fresh().on_keydown(hk._VK_B, ctrl=True, shift=False) is None
    assert _fresh().on_keydown(hk._VK_B, ctrl=False, shift=True) is None


def test_non_trigger_key_never_fires():
    # 'C' (0x43) is deliberately not claimed (Discord/Overlay Platform M contention).
    assert _fresh().on_keydown(0x43, ctrl=True, shift=True) is None


def test_held_key_fires_once_then_debounces():
    d = _fresh()
    assert d.on_keydown(hk._VK_B, ctrl=True, shift=True) == hk._SLOT_OVERLAY_PANEL_CYCLE
    # OS key-repeat sends more WM_KEYDOWN while held -> must not re-fire.
    assert d.on_keydown(hk._VK_B, ctrl=True, shift=True) is None
    assert d.on_keydown(hk._VK_B, ctrl=True, shift=True) is None


def test_release_then_repress_fires_again():
    d = _fresh()
    assert d.on_keydown(hk._VK_A, ctrl=True, shift=True) == hk._SLOT_OVERLAY_TOGGLE
    assert d.on_keydown(hk._VK_A, ctrl=True, shift=True) is None
    d.on_keyup(hk._VK_A)
    assert d.on_keydown(hk._VK_A, ctrl=True, shift=True) == hk._SLOT_OVERLAY_TOGGLE


def test_distinct_keys_debounce_independently():
    d = _fresh()
    assert d.on_keydown(hk._VK_1, ctrl=True, shift=True) == 1
    # A different trigger key held at the same time still fires.
    assert d.on_keydown(hk._VK_2, ctrl=True, shift=True) == 2
    # ...and each is independently debounced.
    assert d.on_keydown(hk._VK_1, ctrl=True, shift=True) is None
    assert d.on_keydown(hk._VK_2, ctrl=True, shift=True) is None


def test_keyup_on_untracked_key_is_safe():
    d = _fresh()
    d.on_keyup(hk._VK_B)  # never pressed; must not raise
    assert d.on_keydown(hk._VK_B, ctrl=True, shift=True) == hk._SLOT_OVERLAY_PANEL_CYCLE


def test_decoder_map_matches_hotkey_table():
    # The decoder's vk->slot map is the single source of truth shared with the
    # _HOTKEYS table the registration test pins; they must not drift apart.
    for slot, vk in hk._HOTKEYS:
        assert _fresh().on_keydown(vk, ctrl=True, shift=True) == slot


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
